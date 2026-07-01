"""Explicit natural-language action resolution for the Cartographer Planner."""

from __future__ import annotations

import re
import unicodedata

from agnostic.application.planning.entity_resolution import (
    column_names_from_structure,
    normalize_identifier,
    normalize_text,
    resolve_dimension_column,
    resolve_target_unit,
)
from agnostic.application.planning.planning_context import PlanningContext
from agnostic.application.planning.rule_based_planner import (
    find_mentioned_unit_pair,
    _quote_sql_literal,
)
from agnostic.application.planning.sql_generation import validate_generated_select_sql
from agnostic.domain.indexing import (
    SessionIndexRegistry,
    parse_table_pair_index_reference,
    resolve_relationship_reference,
    resolve_slice_reference,
)

from agnostic.planner.context import build_planning_context

def _schema_action_from_natural_language(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    normalized = normalize_text(user_text)
    raw_lower = user_text.strip().lower()
    if not normalized:
        return None
    available_units: list[str] = []
    if isinstance(session_or_context, PlanningContext):
        available_units = [str(item).strip() for item in session_or_context.available_units if str(item).strip()]
    else:
        available_units = [
            str(getattr(unit, "unit_name", "")).strip()
            for unit in getattr(session_or_context, "units", [])
            if str(getattr(unit, "unit_name", "")).strip()
        ]
    if not available_units:
        return None
    mentioned_unit = None
    for unit_name in sorted(available_units, key=len, reverse=True):
        normalized_unit = normalize_text(unit_name)
        if (normalized_unit and normalized_unit in normalized) or unit_name.strip().lower() in raw_lower:
            mentioned_unit = unit_name
            break
    if not mentioned_unit:
        return None
    schema_patterns = (
        "schema de",
        "estrutura de",
        "estrutura do",
        "estrutura da",
        "colunas de",
        "colunas do",
        "colunas da",
        "o que tem em",
        "o que existe em",
        "me mostre a estrutura de",
        "me mostra a estrutura de",
        "existe uma tabela",
        "mostre ",
    )
    if any(pattern in normalized for pattern in schema_patterns):
        return {"action": "schema", "table": mentioned_unit}
    if "?" in user_text and mentioned_unit:
        return {"action": "schema", "table": mentioned_unit}
    return None


def _robust_normalize(text: str) -> str:
    """normalize_text com remoção de acentos via unicodedata, mais robusta do que
    a tabela de substituição manual — garante que 'relação' → 'relacao' mesmo
    para caracteres não cobertos pela tabela de entity_resolution."""
    nfkd = unicodedata.normalize("NFKD", str(text))
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return normalize_text(ascii_text)


def _available_units_from_session_or_context(session_or_context) -> list[str]:
    if isinstance(session_or_context, PlanningContext):
        return [str(item).strip() for item in session_or_context.available_units if str(item).strip()]
    return [
        str(getattr(unit, "unit_name", "")).strip()
        for unit in getattr(session_or_context, "units", [])
        if str(getattr(unit, "unit_name", "")).strip()
    ]


def _unit_name_match_variants(value: str) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    variants = {
        raw,
        raw.replace("_", " "),
        raw.replace(" ", "_"),
    }
    normalized_variants: set[str] = set()
    for item in variants:
        normalized = normalize_text(item)
        if normalized:
            normalized_variants.add(normalized)
    return normalized_variants


def _canonical_unit_space(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    normalized = re.sub(r"[_\s]+", " ", raw).strip()
    return normalize_text(normalized)


def _canonical_unit_underscore(value: str) -> str:
    canonical_space = _canonical_unit_space(value)
    if not canonical_space:
        return ""
    return canonical_space.replace(" ", "_")


def _unit_match_score(user_text: str, unit_name: str) -> tuple[int, int]:
    user_space = _canonical_unit_space(user_text)
    user_underscore = _canonical_unit_underscore(user_text)
    unit_space = _canonical_unit_space(unit_name)
    unit_underscore = _canonical_unit_underscore(unit_name)
    if not user_space or not unit_space:
        return (0, 0)
    unit_tokens = [token for token in unit_space.split(" ") if token]
    if (unit_space and unit_space in user_space) or (unit_underscore and unit_underscore in user_underscore):
        return (3, len(unit_tokens))
    if len(unit_tokens) <= 1:
        return (0, 0)
    for prefix_size in range(len(unit_tokens) - 1, 1, -1):
        prefix_space = " ".join(unit_tokens[:prefix_size])
        prefix_underscore = "_".join(unit_tokens[:prefix_size])
        if prefix_space in user_space or prefix_underscore in user_underscore:
            return (2, prefix_size)
    return (0, 0)


def _levenshtein(a: str, b: str) -> int:
    """Distância de edição (Levenshtein) entre duas strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[-1] + 1, prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def _mentioned_available_unit(session_or_context, user_text: str) -> str | None:
    if not str(user_text or "").strip():
        return None
    available_units = _available_units_from_session_or_context(session_or_context)
    if not available_units:
        return None
    scored_matches: list[tuple[tuple[int, int], str]] = []
    for unit_name in available_units:
        score = _unit_match_score(user_text, unit_name)
        if score > (0, 0):
            scored_matches.append((score, unit_name))
    if not scored_matches:
        # Fallback fuzzy: edit-distance ≤ 2 entre qualquer token do texto e
        # nome da unidade normalizado. Resolve apenas quando há candidato único.
        user_words = [w for w in _robust_normalize(user_text).split() if len(w) >= 3]
        if not user_words:
            return None
        fuzzy: list[tuple[int, str]] = []
        for unit_name in available_units:
            unit_norm = _robust_normalize(unit_name)
            if len(unit_norm) < 3:
                continue
            best_dist = min(_levenshtein(w, unit_norm) for w in user_words)
            if best_dist <= 2:
                fuzzy.append((best_dist, unit_name))
        if not fuzzy:
            return None
        fuzzy.sort()
        best_dist = fuzzy[0][0]
        best_names = [u for d, u in fuzzy if d == best_dist]
        return best_names[0] if len(best_names) == 1 else None
    scored_matches.sort(key=lambda item: (item[0][0], item[0][1], len(item[1])), reverse=True)
    best_score = scored_matches[0][0]
    best_units = [unit_name for score, unit_name in scored_matches if score == best_score]
    if len(best_units) != 1:
        return None
    return best_units[0]



def _presented_options_from_session_or_context(session_or_context) -> list[dict[str, object]]:
    if isinstance(session_or_context, PlanningContext):
        return [
            dict(option)
            for option in getattr(session_or_context, "last_presented_options", []) or []
            if isinstance(option, dict)
        ]
    return [
        dict(option)
        for option in getattr(session_or_context, "_last_presented_options", []) or []
        if isinstance(option, dict)
    ]


def _action_already_executed(session_or_context, action_payload: dict[str, object]) -> bool:
    if not isinstance(action_payload, dict):
        return False
    execution_log = []
    if isinstance(session_or_context, PlanningContext):
        execution_log = list(getattr(session_or_context, "execution_log", []) or [])
    else:
        execution_log = list(getattr(session_or_context, "_execution_log", []) or [])
    normalized_action = str(action_payload.get("action", "")).strip().lower()
    target_unit = str(
        action_payload.get("unit_name")
        or action_payload.get("table")
        or action_payload.get("unit")
        or ""
    ).strip().lower()
    for entry in execution_log:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("action", "")).strip().lower() != normalized_action:
            continue
        entry_unit = str(
            entry.get("unit_name")
            or entry.get("table")
            or entry.get("unit")
            or ""
        ).strip().lower()
        if target_unit and entry_unit == target_unit:
            return True
    return False


def _natural_language_option_choice(session_or_context, user_text: str) -> dict[str, object] | None:
    normalized = normalize_text(user_text)
    requested_index = None
    if re.fullmatch(r"\d+", normalized):
        requested_index = int(normalized)
    elif "caminho" in normalized:
        number_match = re.search(r"\bcaminho\s+(\d+)\b", normalized)
        if number_match:
            requested_index = int(number_match.group(1))
    if requested_index is None:
        return None
    for option in _presented_options_from_session_or_context(session_or_context):
        try:
            option_index = int(option.get("index", 0))
        except Exception:
            option_index = 0
        if option_index != requested_index:
            continue
        payload = option.get("suggested_action") or option.get("action_payload")
        if isinstance(payload, dict):
            return dict(payload)
    return None


def _structural_action_from_natural_language(session_or_context, user_text: str) -> dict[str, object] | None:
    normalized = normalize_text(user_text)
    if not normalized:
        return None
    mentioned_unit = _mentioned_available_unit(session_or_context, user_text)
    if not mentioned_unit:
        return None
    schema_patterns = (
        "estrutura de",
        "estrutura do",
        "estrutura da",
        "colunas de",
        "colunas do",
        "colunas da",
        "schema de",
        "schema da",
        "schema do",
        "o que tem em",
        "o que existe em",
    )
    if any(pattern in normalized for pattern in schema_patterns):
        return {"action": "schema", "table": mentioned_unit}
    if any(
        verb in normalized
        for verb in (
            "explorar ",
            "explore ",
            "analisar ",
            "analise ",
            "investigar ",
            "investigue ",
            "ver ",
            "veja ",
            "abrir ",
            "abra ",
        )
    ):
        candidate = {"action": "analyze_unit", "unit_name": mentioned_unit}
        if not _action_already_executed(session_or_context, candidate):
            return candidate
    if any(verb in normalized for verb in ("consulte ", "consultar ", "acesse ", "acessar ")):
        return {"action": "analyze_unit", "unit_name": mentioned_unit}
    if "mostre " in normalized or "me mostre " in normalized or "me mostra " in normalized:
        if any(pattern in normalized for pattern in ("estrutura", "colunas", "schema")):
            return {"action": "schema", "table": mentioned_unit}
        return {"action": "analyze_unit", "unit_name": mentioned_unit}
    if "cruze com " in normalized or "cruzar com " in normalized or "cruze os " in normalized:
        candidate = {"action": "analyze_unit", "unit_name": mentioned_unit}
        if not _action_already_executed(session_or_context, candidate):
            return candidate
    return None


def _quote_sql_identifier(identifier: str) -> str:
    parts = []
    for part in str(identifier).split("."):
        part = part.strip()
        if not part:
            continue
        escaped = part.replace('"', '""')
        parts.append(f'"{escaped}"')
    return ".".join(parts) if parts else '""'


def _units_from_session_or_context(session_or_context) -> list[object]:
    if hasattr(session_or_context, "units"):
        return list(getattr(session_or_context, "units", []) or [])
    available = _available_units_from_session_or_context(session_or_context)
    return [type("Unit", (), {"unit_name": unit_name})() for unit_name in available]


def _extract_analyze_column_phrase(session_or_context, user_text: str) -> str | None:
    normalized = _robust_normalize(user_text)
    distribution_match = re.search(
        r"\bdistribu(?:icao|uicao)\s+(?:de|por)\s+(.+?)(?:\s+em\s+|\s+na\s+tabela\s+|$)",
        normalized,
    )
    if distribution_match:
        return distribution_match.group(1).strip()
    match = re.search(
        r"\b(?:analisar|analise|analisa)\s+(?:a\s+)?(?:coluna\s+)?(.+)$",
        normalized,
    )
    if not match:
        return None
    remainder = match.group(1).strip()
    if remainder.startswith("coluna "):
        remainder = remainder[7:].strip()
    unit_suffix = re.search(r"\s+(?:em|na tabela|da tabela|de)\s+(.+)$", remainder)
    if unit_suffix:
        suffix_text = unit_suffix.group(1).strip()
        suffix_norm = _robust_normalize(suffix_text)
        available_unit_norms = {
            _robust_normalize(u) for u in _available_units_from_session_or_context(session_or_context)
        }
        suffix_is_unit = (
            suffix_norm in available_unit_norms
            or any(u and (u in suffix_norm or suffix_norm in u) for u in available_unit_norms)
            or bool(_mentioned_available_unit(session_or_context, suffix_text))
            or bool(_mentioned_available_unit(session_or_context, user_text))
        )
        if suffix_is_unit:
            remainder = remainder[: unit_suffix.start()].strip()
    return remainder or None


def _resolve_column_across_units(
    session_or_context,
    column_phrase: str,
    *,
    preferred_unit: str | None = None,
) -> tuple[str, str] | None:
    phrase_norm = _robust_normalize(column_phrase)
    phrase_id = normalize_identifier(column_phrase)
    if not phrase_norm:
        return None

    matches: list[tuple[str, str]] = []

    for unit in _units_from_session_or_context(session_or_context):
        unit_name = str(getattr(unit, "unit_name", "")).strip()
        if not unit_name:
            continue
        try:
            structure = unit.get_structure()
        except Exception:
            continue
        for column_name in column_names_from_structure(structure):
            if _robust_normalize(column_name) == phrase_norm or normalize_identifier(column_name) == phrase_id:
                if (unit_name, column_name) not in matches:
                    matches.append((unit_name, column_name))

    if not matches:
        try:
            ctx = build_planning_context(session_or_context)
            for ctx_unit, ctx_cols in (ctx.unit_columns or {}).items():
                for col in ctx_cols:
                    if _robust_normalize(col) == phrase_norm or normalize_identifier(col) == phrase_id:
                        if (ctx_unit, col) not in matches:
                            matches.append((ctx_unit, col))
        except Exception:
            pass

    if preferred_unit:
        preferred_matches = [item for item in matches if item[0] == preferred_unit]
        if len(preferred_matches) == 1:
            return preferred_matches[0]
    if len(matches) == 1:
        return matches[0]

    try:
        context = build_planning_context(session_or_context)
    except Exception:
        return matches[0] if matches else None
    unit_name = preferred_unit or resolve_target_unit(context, column_phrase)
    if unit_name:
        column_name = resolve_dimension_column(context, unit_name, column_phrase)
        if column_name:
            return unit_name, column_name
    if matches:
        if preferred_unit:
            preferred_matches = [item for item in matches if item[0] == preferred_unit]
            if preferred_matches:
                return preferred_matches[0]
        return matches[0]
    return None


def _column_distribution_action_from_natural_language(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    column_phrase = _extract_analyze_column_phrase(session_or_context, user_text)
    if not column_phrase:
        return None
    available_units = {
        normalize_text(unit_name) for unit_name in _available_units_from_session_or_context(session_or_context)
    }
    if normalize_text(column_phrase) in available_units:
        return None
    preferred_unit = _mentioned_available_unit(session_or_context, user_text)
    resolved = _resolve_column_across_units(
        session_or_context,
        column_phrase,
        preferred_unit=preferred_unit,
    )
    if resolved is None:
        return None
    unit_name, column_name = resolved
    quoted_unit = _quote_sql_identifier(unit_name)
    quoted_column = _quote_sql_identifier(column_name)
    sql = (
        f"SELECT {quoted_column}, COUNT(*) AS total "
        f"FROM {quoted_unit} "
        f"WHERE {quoted_column} IS NOT NULL "
        f"AND TRIM(CAST({quoted_column} AS TEXT)) <> '' "
        f"GROUP BY {quoted_column} "
        f"ORDER BY total DESC "
        f"LIMIT 50"
    )
    validated_sql = validate_generated_select_sql(sql)
    if validated_sql is None:
        return None
    candidate = {
        "action": "request_new_query",
        "description": f"distribuição de {column_name} em {unit_name}",
        "suggested_sql": validated_sql,
    }
    if _action_already_executed(session_or_context, candidate):
        return None
    return candidate


def _is_whole_word_in_text(pattern: str, text: str) -> bool:
    """Retorna True se `pattern` aparece em `text` como palavra completa.
    Trata underscore como separador de palavra, para que 'cord' não faça
    match dentro de 'cord_cluster' ou 'discord'."""
    if not pattern:
        return False
    escaped = re.escape(pattern)
    return bool(re.search(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])", text))


def _mentioned_units_in_text(session_or_context, user_text: str) -> list[str]:
    available_units = _available_units_from_session_or_context(session_or_context)
    normalized = _robust_normalize(user_text)
    matches: list[str] = []
    for unit_name in sorted(available_units, key=len, reverse=True):
        candidate = _robust_normalize(unit_name)
        if candidate and _is_whole_word_in_text(candidate, normalized) and unit_name not in matches:
            matches.append(unit_name)
    return matches


def _session_index_registry(session_or_context) -> SessionIndexRegistry | None:
    if isinstance(session_or_context, PlanningContext):
        return None
    ensure = getattr(session_or_context, "_ensure_index_registry", None)
    if callable(ensure):
        return ensure()
    registry = getattr(session_or_context, "index_registry", None)
    return registry if isinstance(registry, SessionIndexRegistry) else None


def _horizontal_action_from_natural_language(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    normalized = _robust_normalize(user_text)
    if not normalized:
        return None
    registry = _session_index_registry(session_or_context)
    if registry is not None:
        pair_indexes = parse_table_pair_index_reference(user_text)
        if pair_indexes is not None:
            unit_a = registry.resolve_table_index(pair_indexes[0])
            unit_b = registry.resolve_table_index(pair_indexes[1])
            if unit_a and unit_b:
                candidate = {"action": "analyze_horizontal", "unit_a": unit_a, "unit_b": unit_b}
                if not _action_already_executed(session_or_context, candidate):
                    analysis_by_unit = getattr(session_or_context, "analysis_by_unit", None) or {}
                    if isinstance(analysis_by_unit, dict):
                        prereqs = [unit for unit in (unit_a, unit_b) if unit not in analysis_by_unit]
                    else:
                        prereqs = []
                    if prereqs:
                        return {
                            "action": "analyze_horizontal_with_prereqs",
                            "unit_a": unit_a,
                            "unit_b": unit_b,
                            "prereqs": prereqs,
                        }
                    return candidate
    intent_tokens = (
        "relacao",
        "relacao entre",
        "cruzar",
        "conectar",
        "comparar",
        "correlacao",
        "correlacao entre",
        "juntar",
        "ligar",
        "relacionar",
        "ligacao",
        "ligacao entre",
    )
    if not any(token in normalized for token in intent_tokens):
        return None
    available_units = _available_units_from_session_or_context(session_or_context)
    pair = find_mentioned_unit_pair(user_text, available_units)
    if pair is None:
        mentioned_units = _mentioned_units_in_text(session_or_context, user_text)
        if len(mentioned_units) >= 2:
            pair = mentioned_units[0], mentioned_units[1]
    if pair is None:
        return None
    unit_a, unit_b = pair[0], pair[1]
    candidate = {"action": "analyze_horizontal", "unit_a": unit_a, "unit_b": unit_b}
    if _action_already_executed(session_or_context, candidate):
        return None
    # Verificar pré-requisitos: analyze_unit deve ter sido executado para cada unidade
    analysis_by_unit = getattr(session_or_context, "analysis_by_unit", None) or {}
    if isinstance(analysis_by_unit, dict):
        prereqs = [u for u in (unit_a, unit_b) if u not in analysis_by_unit]
    else:
        prereqs = []
    if prereqs:
        return {
            "action": "analyze_horizontal_with_prereqs",
            "unit_a": unit_a,
            "unit_b": unit_b,
            "prereqs": prereqs,
        }
    return candidate


def _extract_table_index_reference(user_text: str) -> int | None:
    normalized = normalize_text(user_text)
    for pattern in (
        r"\btabela\s+(\d+)\b",
        r"\(\s*tabela\s+(\d+)\s*\)",
        r"\bopcao\s+(\d+)\b",
        r"\bopção\s+(\d+)\b",
    ):
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None


def _initial_unit_options_from_session(session_or_context) -> list[dict[str, object]]:
    if isinstance(session_or_context, PlanningContext):
        return []
    return [
        dict(option)
        for option in getattr(session_or_context, "_initial_unit_options", []) or []
        if isinstance(option, dict)
    ]


def _action_payload_from_presented_option(option: dict[str, object]) -> dict[str, object] | None:
    payload = option.get("action_payload") or option.get("suggested_action")
    if isinstance(payload, dict) and str(payload.get("action", "")).strip():
        return dict(payload)
    return None


def _indexed_relationship_action(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    registry = _session_index_registry(session_or_context)
    if registry is None:
        return None
    relationship = resolve_relationship_reference(user_text, registry.relationship_index_map)
    if relationship is None:
        return None
    unit_a = str(relationship.get("table_a", "")).strip()
    unit_b = str(relationship.get("table_b", "")).strip()
    if not unit_a or not unit_b:
        return None
    candidate = {"action": "analyze_horizontal", "unit_a": unit_a, "unit_b": unit_b}
    if _action_already_executed(session_or_context, candidate):
        return None
    analysis_by_unit = getattr(session_or_context, "analysis_by_unit", None) or {}
    if isinstance(analysis_by_unit, dict):
        prereqs = [unit for unit in (unit_a, unit_b) if unit not in analysis_by_unit]
    else:
        prereqs = []
    if prereqs:
        return {
            "action": "analyze_horizontal_with_prereqs",
            "unit_a": unit_a,
            "unit_b": unit_b,
            "prereqs": prereqs,
        }
    return candidate


def _indexed_slice_action(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    registry = _session_index_registry(session_or_context)
    if registry is None or not hasattr(session_or_context, "units"):
        return None
    slice_info = resolve_slice_reference(user_text, registry.slice_index_map)
    if slice_info is None:
        return None
    table = str(slice_info.get("table", "")).strip()
    column = str(slice_info.get("column", "")).strip()
    value = str(slice_info.get("value", "")).strip()
    if not table or not column or not value:
        return None
    sql = (
        f"SELECT * FROM {_quote_sql_identifier(table)} "
        f"WHERE {_quote_sql_identifier(column)} = {_quote_sql_literal(value)} LIMIT 50"
    )
    candidate = {
        "action": "request_new_query",
        "description": f"recorte {slice_info.get('index')}: {column} = {value}",
        "suggested_sql": sql,
    }
    if _action_already_executed(session_or_context, candidate):
        return None
    return candidate


def _indexed_unit_explore_action(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    index = _extract_table_index_reference(user_text)
    if index is None:
        return None
    option_sources = list(_presented_options_from_session_or_context(session_or_context))
    option_sources.extend(_initial_unit_options_from_session(session_or_context))
    for option in option_sources:
        if int(option.get("index", -1)) != index:
            continue
        payload = _action_payload_from_presented_option(option)
        if payload is None:
            continue
        if _action_already_executed(session_or_context, payload):
            return None
        return payload
    registry = _session_index_registry(session_or_context)
    if registry is not None and _initial_unit_options_from_session(session_or_context):
        unit_name = registry.resolve_table_index(index)
        if unit_name:
            candidate = {"action": "analyze_unit", "unit_name": unit_name}
            if not _action_already_executed(session_or_context, candidate):
                return candidate
    return None


def _unit_name_appears_in_text(unit_name: str, user_text: str) -> bool:
    normalized = normalize_text(user_text)
    unit_normalized = normalize_text(unit_name)
    if unit_normalized and unit_normalized in normalized:
        return True
    unit_underscore = _canonical_unit_underscore(unit_name)
    user_underscore = _canonical_unit_underscore(user_text)
    return bool(unit_underscore and unit_underscore in user_underscore)


def _explicit_unit_reference_action(session_or_context, user_text: str) -> dict[str, object] | None:
    if len(_mentioned_units_in_text(session_or_context, user_text)) >= 2:
        return None
    mentioned_unit = _mentioned_available_unit(session_or_context, user_text)
    if not mentioned_unit:
        return None
    normalized = _robust_normalize(user_text)
    if not normalized:
        return None
    if any(
        token in normalized
        for token in (
            "schema",
            "estrutura",
            "colunas de",
            "colunas da",
            "colunas do",
        )
    ):
        return None
    if not _unit_name_appears_in_text(mentioned_unit, user_text):
        return None
    canonical_space = _canonical_unit_space(user_text)
    canonical_underscore = _canonical_unit_underscore(user_text)
    unit_space = _canonical_unit_space(mentioned_unit)
    unit_underscore = _canonical_unit_underscore(mentioned_unit)
    is_direct_reference = canonical_space == unit_space or canonical_underscore == unit_underscore
    is_unique_prefix = len(canonical_space.split()) >= 2 and unit_space.startswith(canonical_space)
    has_contextual_marker = any(
        marker in normalized
        for marker in (
            "explorar",
            "explore",
            "quero",
            "ver ",
            "tabela",
            "nivel",
            "hierarqu",
            "proximo",
            "aprofund",
            "consult",
            "abra",
            "abrir",
            "investig",
            "analis",
        )
    ) or _extract_table_index_reference(user_text) is not None or "—" in user_text or " - " in normalized
    if not is_direct_reference and not is_unique_prefix and not has_contextual_marker:
        return None
    candidate = {"action": "analyze_unit", "unit_name": mentioned_unit}
    if _action_already_executed(session_or_context, candidate):
        return None
    return candidate


def _has_refusal_signal(user_text: str) -> bool:
    normalized = _robust_normalize(user_text)
    return any(
        token in normalized
        for token in (
            "nao quero",
            "nao queira",
            "prefiro",
            "em vez",
            "outra opcao",
            "outro caminho",
            "recuso",
            "sem essa",
            "ignore essa",
            "nao siga",
        )
    )


def _has_clear_analysis_intent(user_text: str, session_or_context=None) -> bool:
    """Retorna True apenas para intenções analíticas unívocas.

    Exclui intenções abertas como 'encontrar', 'descobrir' e 'resolver'
    que exigem clarificação antes da execução, salvo quando há unidade explícita.
    """
    normalized = _robust_normalize(user_text)
    open_intent_tokens = ("encontr", "descobr", "resolv", "investig", "explor")
    if any(token in normalized for token in open_intent_tokens):
        if not _mentioned_available_unit(session_or_context, user_text):
            return False
    return any(
        token in normalized
        for token in (
            "analis",
            "distribu",
            "contag",
            "medi",
            "compar",
            "filtr",
            "agrup",
            "mostr",
            "padrao",
            "tendenc",
            "frequenc",
            "correlac",
            "metrica",
            "coluna",
            "campo",
            "por tipo",
            "por categoria",
            "por regiao",
            "por periodo",
            "histogram",
        )
    )


def _natural_language_analysis_action(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    if not _has_refusal_signal(user_text) and not _has_clear_analysis_intent(user_text, session_or_context):
        return None
    mentioned_unit = _mentioned_available_unit(session_or_context, user_text)
    if not mentioned_unit:
        try:
            context = build_planning_context(session_or_context)
            mentioned_unit = resolve_target_unit(context, user_text)
        except Exception:
            mentioned_unit = None
    if not mentioned_unit:
        return None
    description = user_text.strip()[:240] or "análise solicitada pelo usuário"
    quoted_unit = _quote_sql_identifier(mentioned_unit)
    validated_sql = validate_generated_select_sql(f"SELECT * FROM {quoted_unit} LIMIT 50")
    if validated_sql is None:
        return None
    candidate = {
        "action": "request_new_query",
        "description": description,
        "suggested_sql": validated_sql,
    }
    if _action_already_executed(session_or_context, candidate):
        return None
    return candidate


def _extract_schema_column_index_reference(user_text: str) -> int | None:
    normalized = _robust_normalize(user_text)
    patterns = (
        r"\b(?:ver|veja|vamos ver|mostre|mostra|mostrar|quero ver|analisar|analise|analisa)\s+(?:a\s+)?coluna\s+(\d+)\b",
        r"\bcoluna\s+(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1))
    return None


def _current_table_from_session(session_or_context, user_text: str = "") -> str | None:
    mentioned_unit = _mentioned_available_unit(session_or_context, user_text)
    if mentioned_unit:
        return mentioned_unit

    raw_session = session_or_context.raw_session if isinstance(session_or_context, PlanningContext) else session_or_context
    if raw_session is not None:
        last_payload = getattr(raw_session, "_last_executed_action_payload", None)
        if isinstance(last_payload, dict):
            for key in ("table", "unit_name", "unit"):
                value = str(last_payload.get(key, "")).strip()
                if value:
                    return value
        session_context = getattr(raw_session, "session_context", None)
        planner = getattr(session_context, "planner", None) if session_context is not None else None
        pending_action = getattr(planner, "pending_action", None) if planner is not None else None
        if isinstance(pending_action, dict):
            for key in ("table", "unit_name", "unit"):
                value = str(pending_action.get(key, "")).strip()
                if value:
                    return value

    try:
        context = build_planning_context(session_or_context)
        return resolve_target_unit(context, user_text)
    except Exception:
        return None


def _column_name_at_index(session_or_context, table: str, column_index: int) -> str | None:
    for unit in _units_from_session_or_context(session_or_context):
        unit_name = str(getattr(unit, "unit_name", "")).strip()
        if unit_name != table:
            continue
        try:
            structure = unit.get_structure()
        except Exception:
            return None
        columns = column_names_from_structure(structure)
        if 1 <= column_index <= len(columns):
            return columns[column_index - 1]
    return None


def _schema_column_action_from_natural_language(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    column_index = _extract_schema_column_index_reference(user_text)
    if column_index is None:
        return None
    table = _current_table_from_session(session_or_context, user_text)
    if not table:
        return None
    column_name = _column_name_at_index(session_or_context, table, column_index)
    if not column_name:
        return None
    return {
        "action": "schema_column",
        "table": table,
        "column_index": column_index,
        "column_name": column_name,
    }


def _resolve_explicit_user_action(
    session_or_context,
    user_text: str,
) -> dict[str, object] | None:
    schema_column_action = _schema_column_action_from_natural_language(session_or_context, user_text)
    if schema_column_action is not None:
        return schema_column_action
    schema_action = _schema_action_from_natural_language(session_or_context, user_text)
    if schema_action is not None:
        return schema_action
    column_distribution_action = _column_distribution_action_from_natural_language(
        session_or_context,
        user_text,
    )
    if column_distribution_action is not None:
        return column_distribution_action
    relationship_action = _indexed_relationship_action(session_or_context, user_text)
    if relationship_action is not None:
        return relationship_action
    slice_action = _indexed_slice_action(session_or_context, user_text)
    if slice_action is not None:
        return slice_action
    horizontal_action = _horizontal_action_from_natural_language(session_or_context, user_text)
    if horizontal_action is not None:
        return horizontal_action
    structural_action = _structural_action_from_natural_language(session_or_context, user_text)
    if structural_action is not None:
        return structural_action
    indexed_action = _indexed_unit_explore_action(session_or_context, user_text)
    if indexed_action is not None:
        return indexed_action
    if _has_refusal_signal(user_text) or _has_clear_analysis_intent(user_text, session_or_context):
        prioritized_analysis = _natural_language_analysis_action(session_or_context, user_text)
        if prioritized_analysis is not None:
            return prioritized_analysis
    explicit_unit_reference = _explicit_unit_reference_action(session_or_context, user_text)
    if explicit_unit_reference is not None:
        return explicit_unit_reference
    natural_language_action = _natural_language_analysis_action(session_or_context, user_text)
    if natural_language_action is not None:
        return natural_language_action
    return None


