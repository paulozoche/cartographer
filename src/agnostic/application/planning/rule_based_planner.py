from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from agnostic.application.planning.requirement_priority import sort_pending_requirements_for_investigation

if TYPE_CHECKING:
    from orchestrator import OrchestratorSession


logger = logging.getLogger(__name__)


SHORT_CONFIRMATIONS = {"sim", "si", "ok", "pode", "prossiga", "continue", "vai", "execute"}
CONTINUATION_WORDS = SHORT_CONFIRMATIONS | {"continue", "continue daí", "continue dai", "siga", "avançe", "avance"}


def normalize_text(text: str) -> str:
    normalized = text.strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return " ".join(normalized.split())


def is_short_confirmation(text: str) -> bool:
    return normalize_text(text) in SHORT_CONFIRMATIONS


def find_mentioned_unit(text: str, unit_names: list[str]) -> str | None:
    normalized = normalize_text(text)
    for unit_name in sorted(unit_names, key=len, reverse=True):
        candidate = normalize_text(unit_name)
        if candidate and candidate in normalized:
            return unit_name
    return None


def find_mentioned_unit_pair(text: str, unit_names: list[str]) -> tuple[str, str] | None:
    normalized = normalize_text(text)
    matches = [unit for unit in unit_names if normalize_text(unit) in normalized]
    if len(matches) >= 2:
        return matches[0], matches[1]
    return None


def extract_units_from_sql(sql: str) -> list[str]:
    return [match.strip('"') for match in re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z0-9_\".]+)", sql, flags=re.IGNORECASE)]


def _quote_sql_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _extract_observed_candidates_from_sample_entities(session: "OrchestratorSession") -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    graph = getattr(session, "knowledge_graph", None)
    for node in reversed(getattr(graph, "nodes", [])) if graph is not None else []:
        unit = str(getattr(node, "unit", "")).strip()
        for entity in getattr(node, "sample_entities", []) or []:
            if not isinstance(entity, str):
                continue
            for part in entity.split(","):
                if "=" not in part:
                    continue
                column, value = part.split("=", 1)
                column = column.strip()
                value = value.strip()
                if column and value:
                    candidates.append({"unit": unit, "column": column, "value": value})
    return candidates


def _extract_observed_candidates_from_cache(session: "OrchestratorSession") -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    cache = getattr(session, "_core_cache", {})
    if not isinstance(cache, dict):
        return candidates
    for payload in cache.values():
        if not isinstance(payload, dict):
            continue
        units = payload.get("units", [])
        columns = payload.get("columns", [])
        rows = payload.get("rows", [])
        unit = str(units[0]).strip() if isinstance(units, list) and units else ""
        if not unit or not isinstance(columns, list) or not isinstance(rows, list):
            continue
        for row in rows[:20]:
            if not isinstance(row, (list, tuple)):
                continue
            for index, column in enumerate(columns):
                if index >= len(row):
                    continue
                value = row[index]
                if value is None:
                    continue
                text_value = str(value).strip()
                if text_value:
                    candidates.append({"unit": unit, "column": str(column).strip(), "value": text_value})
    return candidates


def _textual_columns_for_unit(session: "OrchestratorSession", unit_name: str) -> tuple[list[str], list[str]]:
    raw_columns: list[str] = []
    try:
        structure = session._find_unit(unit_name).get_structure()
        raw_columns = [str(getattr(column, "name", "")).strip() for column in getattr(structure, "columns", ()) if str(getattr(column, "name", "")).strip()]
    except Exception:
        structure = None
    try:
        from orchestrator import classify_columns_from_structure

        classified = classify_columns_from_structure(structure) if structure is not None else None
    except Exception:
        classified = None
    if isinstance(classified, dict):
        text_columns = [str(item) for item in classified.get("text_columns", [])]
        categorical_columns = [str(item) for item in classified.get("categorical_columns", [])]
        return text_columns, categorical_columns
    return raw_columns, raw_columns


def _build_value_filter_sql(session: "OrchestratorSession", *, unit_name: str, column: str | None, value: str) -> str | None:
    select_clause = "*"
    builder = getattr(session, "_build_select_columns_for_filtered_query", None)
    if callable(builder):
        try:
            select_clause = str(builder(unit_name, column or ""))
        except Exception:
            select_clause = "*"
    quoted_value = _quote_sql_literal(value)
    if column:
        return f"SELECT {select_clause} FROM {unit_name} WHERE LOWER(CAST({column} AS TEXT)) = LOWER({quoted_value}) LIMIT 50"
    text_columns, categorical_columns = _textual_columns_for_unit(session, unit_name)
    fallback_columns = []
    for candidate in categorical_columns + text_columns:
        if candidate not in fallback_columns:
            fallback_columns.append(candidate)
    if not fallback_columns:
        return None
    clauses = [f"LOWER(CAST({candidate} AS TEXT)) = LOWER({quoted_value})" for candidate in fallback_columns[:4]]
    escaped_value = value.replace("'", "''")
    like_clauses = [f"LOWER(CAST({candidate} AS TEXT)) LIKE LOWER('%{escaped_value}%')" for candidate in text_columns[:2]]
    predicate = " OR ".join(clauses + like_clauses)
    if not predicate:
        return None
    return f"SELECT {select_clause} FROM {unit_name} WHERE {predicate} LIMIT 50"


def build_safe_select_sql(
    unit: str,
    select_columns: list[str],
    conditions: list[str],
    *,
    mode: str = "AND",
    limit: int = 50,
) -> str | None:
    normalized_unit = unit.strip()
    if not normalized_unit:
        return None
    cleaned_columns: list[str] = []
    for column in select_columns:
        normalized_column = str(column).strip()
        if normalized_column and normalized_column not in cleaned_columns:
            cleaned_columns.append(normalized_column)
    select_clause = ", ".join(cleaned_columns) if cleaned_columns else "*"
    cleaned_conditions: list[str] = []
    for condition in conditions:
        normalized_condition = str(condition).strip()
        if normalized_condition and normalized_condition not in cleaned_conditions:
            cleaned_conditions.append(normalized_condition)
    if not cleaned_conditions:
        return None
    joiner = " AND " if mode == "AND" else " OR "
    where_clause = joiner.join(cleaned_conditions)
    if not where_clause.strip():
        return None
    sql = f"SELECT {select_clause} FROM {normalized_unit} WHERE {where_clause} LIMIT {int(limit)}"
    if "SELECT FROM" in sql or "SELECT ," in sql or "WHERE  LIMIT" in sql or "FROM  WHERE" in sql:
        return None
    return sql


def plan_filter_for_observed_value(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    normalized_user_text = normalize_text(user_text)
    if not normalized_user_text:
        return None
    triggers = ("foc", "aprofund", "consult", "filtr", "buscar", "ver", "investig")
    if not any(token in normalized_user_text for token in triggers) and not normalized_user_text.startswith("sim "):
        return None
    candidates = _extract_observed_candidates_from_sample_entities(session) + _extract_observed_candidates_from_cache(session)
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        unit_name = candidate["unit"]
        column = candidate["column"]
        value = candidate["value"]
        key = (unit_name, column, value)
        if key in seen:
            continue
        seen.add(key)
        if normalize_text(value) not in normalized_user_text:
            continue
        sql = _build_value_filter_sql(session, unit_name=unit_name, column=column or None, value=value)
        if not sql:
            continue
        return {
            "action": "request_new_query",
            "description": f"filtrar registros por valor observado em {column or unit_name}",
            "suggested_sql": sql,
        }
    active_focus = getattr(session, "_active_focus", None)
    if isinstance(active_focus, dict):
        filter_payload = active_focus.get("filter")
        units = active_focus.get("units", [])
        if isinstance(filter_payload, dict) and isinstance(units, list) and units:
            value = str(filter_payload.get("value", "")).strip()
            column = str(filter_payload.get("column", "")).strip()
            unit_name = str(units[0]).strip()
            if value and normalize_text(value) in normalized_user_text:
                sql = _build_value_filter_sql(session, unit_name=unit_name, column=column or None, value=value)
                if sql:
                    return {
                        "action": "request_new_query",
                        "description": f"filtrar registros por valor observado em {column or unit_name}",
                        "suggested_sql": sql,
                    }
    return None


def _direct_value_terms(user_text: str) -> list[str]:
    match = re.match(
        r"^\s*(?:amostra|amostrar|mostrar|ver|explorar|filtrar|buscar|listar)\s+(.+?)\s*$",
        user_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    raw_term = match.group(1).strip()
    if not raw_term:
        return []
    candidates = [raw_term]
    normalized = raw_term.strip()
    if len(normalized) > 3 and normalized.lower().endswith("s"):
        singular = normalized[:-1].strip()
        if singular and singular not in candidates:
            candidates.append(singular)
    return candidates


def _schema_requested_explicitly(normalized_text: str) -> bool:
    tokens = set(normalized_text.split())
    return bool(tokens & {"schema", "colunas", "columns", "estrutura", "campos"})


def _value_forms(value: str) -> list[str]:
    normalized = normalize_text(value)
    forms = [normalized]
    if len(normalized) > 3 and normalized.endswith("s"):
        singular = normalized[:-1].strip()
        if singular and singular not in forms:
            forms.append(singular)
    return forms


def _quote_sql_identifier(identifier: str) -> str:
    parts = []
    for part in str(identifier).split("."):
        part = part.strip()
        if not part:
            continue
        escaped = part.replace('"', '""')
        parts.append(f'"{escaped}"')
    return ".".join(parts) if parts else '""'


def _normalize_for_unit_matching(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _tokenize_for_unit_matching(text: str) -> list[str]:
    return [token for token in _normalize_for_unit_matching(text).split() if token]


def _longest_common_subsequence(a: str, b: str) -> int:
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, char_a in enumerate(a, start=1):
        for j, char_b in enumerate(b, start=1):
            if char_a == char_b:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = dp[i - 1][j] if dp[i - 1][j] >= dp[i][j - 1] else dp[i][j - 1]
    return dp[-1][-1]


def _is_similar_unit_token(text_token: str, unit_token: str) -> bool:
    if not text_token or not unit_token:
        return False
    if text_token == unit_token or text_token in unit_token or unit_token in text_token:
        return True
    if text_token.endswith("s") and text_token[:-1] == unit_token:
        return True
    if unit_token.endswith("s") and unit_token[:-1] == text_token:
        return True
    lcs = _longest_common_subsequence(text_token, unit_token)
    return lcs >= min(len(text_token), len(unit_token)) - 1


def _find_mentioned_unit_approximate(text: str, unit_names: list[str]) -> str | None:
    normalized_text = _normalize_for_unit_matching(text)
    if not normalized_text:
        return None
    for unit_name in sorted(unit_names, key=len, reverse=True):
        normalized_unit = _normalize_for_unit_matching(unit_name)
        if normalized_unit and normalized_unit in normalized_text:
            return unit_name
    text_tokens = _tokenize_for_unit_matching(text)
    if not text_tokens:
        return None
    candidates: list[tuple[int, int, str]] = []
    for unit_name in unit_names:
        unit_tokens = _tokenize_for_unit_matching(unit_name)
        score = 0
        for text_token in text_tokens:
            for unit_token in unit_tokens:
                if _is_similar_unit_token(text_token, unit_token):
                    score += 1
                    break
        if score > 0:
            candidates.append((score, len(unit_tokens), unit_name))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    if len(candidates) > 1 and (candidates[0][0] == candidates[1][0] or candidates[1][0] >= 90):
        return None
    return candidates[0][2]


def _has_contextual_unit_evidence(session: "OrchestratorSession") -> bool:
    if getattr(session, "_active_focus", None):
        return True
    graph = getattr(session, "knowledge_graph", None)
    return bool(graph is not None and getattr(graph, "nodes", []))


def _resolve_target_unit(session: "OrchestratorSession", user_text: str) -> str | None:
    plausible_units = _recent_or_plausible_units(session)
    if not plausible_units:
        return None
    target_unit = _find_mentioned_unit_approximate(user_text, plausible_units)
    if target_unit is not None:
        return target_unit
    if len(plausible_units) == 1:
        return plausible_units[0]
    if _has_contextual_unit_evidence(session):
        return plausible_units[0]
    return None


def _column_tokens(text: str) -> list[str]:
    normalized = normalize_text(str(text).replace("_", " "))
    return [token for token in re.sub(r"[^a-z0-9]+", " ", normalized).split() if token]


def _singularize_token(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _normalize_dimension_phrase(text: str) -> str:
    normalized = normalize_text(text).strip(" ,.:!?")
    return re.sub(r"\s+", " ", normalized)


def _extract_dimension_phrase(user_text: str) -> str | None:
    match = re.search(
        r"(?:\bcontagem\s+por\b|\bcontar\s+por\b|\bquantidade\s+por\b|\btotal\s+por\b|\bdistribuicao\s+por\b|\bagrupar\s+por\b|\bgroup\s+by\b|\bcount\s+by\b)\s+(.+)$",
        normalize_text(user_text),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    dimension = _normalize_dimension_phrase(match.group(1))
    return dimension or None


def _columns_for_unit(session: "OrchestratorSession", unit_name: str) -> list[str]:
    try:
        structure = session._find_unit(unit_name).get_structure()
    except Exception:
        return []
    columns: list[str] = []
    for column in getattr(structure, "columns", ()) or ():
        name = str(getattr(column, "name", "")).strip()
        if name and name not in columns:
            columns.append(name)
    return columns


def _resolve_dimension_column(session: "OrchestratorSession", unit_name: str, dimension_text: str) -> str | None:
    columns = _columns_for_unit(session, unit_name)
    if not columns:
        return None
    phrase = _normalize_dimension_phrase(dimension_text)
    if not phrase:
        return None
    phrase_tokens = [_singularize_token(token) for token in _column_tokens(phrase)]
    if not phrase_tokens:
        return None
    canonical_phrase = "".join(phrase_tokens)
    candidates: list[tuple[int, int, int, str]] = []
    for column in columns:
        column_tokens = [_singularize_token(token) for token in _column_tokens(column)]
        if not column_tokens:
            continue
        canonical_column = "".join(column_tokens)
        score = 0
        matched_tokens = 0
        if canonical_phrase == canonical_column:
            score = 100
            matched_tokens = len(phrase_tokens)
        elif canonical_phrase in canonical_column or canonical_column in canonical_phrase:
            score = 90
            matched_tokens = len(phrase_tokens)
        else:
            for phrase_token in phrase_tokens:
                for column_token in column_tokens:
                    if _is_similar_unit_token(phrase_token, column_token):
                        matched_tokens += 1
                        break
            if matched_tokens == len(phrase_tokens):
                score = 60 + matched_tokens
            elif len(phrase_tokens) == 1 and matched_tokens == 1:
                score = 40
        if score > 0:
            candidates.append((score, matched_tokens, len(column_tokens), column))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    if len(candidates) > 1 and (
        candidates[0][0] == candidates[1][0]
        or (candidates[0][1] == len(phrase_tokens) and candidates[1][1] == len(phrase_tokens))
    ):
        return None
    return candidates[0][3]


def plan_grouped_count_by_dimension(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    normalized_text = normalize_text(user_text)
    if not normalized_text or _schema_requested_explicitly(normalized_text):
        return None
    dimension_text = _extract_dimension_phrase(user_text)
    if not dimension_text:
        return None
    unit_name = _resolve_target_unit(session, user_text)
    if not unit_name:
        return None
    column_name = _resolve_dimension_column(session, unit_name, dimension_text)
    if not column_name:
        return None
    quoted_unit = _quote_sql_identifier(unit_name)
    quoted_column = _quote_sql_identifier(column_name)
    sql = (
        f"SELECT {quoted_column} AS value, COUNT(*) AS total "
        f"FROM {quoted_unit} "
        f"GROUP BY {quoted_column} "
        f"ORDER BY total DESC "
        f"LIMIT 50"
    )
    validated_sql = _validate_generated_select_sql(sql)
    if validated_sql is None:
        return None
    upper = validated_sql.upper()
    invalid_patterns = ("SELECT FROM", "SELECT ,", "GROUP BY ORDER", "; LIMIT", "FROM  GROUP")
    if "GROUP BY" not in upper or "COUNT(" not in upper or "LIMIT" not in upper:
        return None
    if any(pattern in upper for pattern in invalid_patterns):
        return None
    return {
        "action": "request_new_query",
        "description": f"agrupar contagem por {column_name} em {unit_name}",
        "suggested_sql": validated_sql,
    }


def plan_count_records_command(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    normalized_text = normalize_text(user_text)
    if not normalized_text or _schema_requested_explicitly(normalized_text):
        return None
    if _extract_dimension_phrase(user_text):
        return None
    triggers = ("quantos", "quantas", "total", "contagem", "count", "number of", "how many")
    if not any(token in normalized_text for token in triggers):
        return None
    target_unit = _resolve_target_unit(session, user_text)
    if target_unit is None:
        return None
    quoted_unit = _quote_sql_identifier(target_unit)
    return {
        "action": "request_new_query",
        "description": f"Contar registros em {target_unit}",
        "suggested_sql": f"SELECT COUNT(*) AS total FROM {quoted_unit};",
    }


def _rank_search_terms_for_filtering(search_terms: list[str]) -> list[str]:
    if not search_terms:
        return []
    singular_candidates: list[str] = []
    for term in search_terms:
        if " " not in term and term.endswith("s") and term[:-1] in search_terms:
            singular_candidates.append(term[:-1])
    ranked: list[str] = []
    seen: set[str] = set()
    for term in search_terms:
        if term in singular_candidates and term not in seen:
            ranked.append(term)
            seen.add(term)
    best_phrase: str | None = None
    for term in search_terms:
        words = term.split()
        if len(words) == 2 and term not in seen:
            plural_count = sum(1 for word in words if word.endswith("s"))
            if best_phrase is None:
                best_phrase = term
            else:
                existing_plural_count = sum(1 for word in best_phrase.split() if word.endswith("s"))
                if plural_count < existing_plural_count:
                    best_phrase = term
    if best_phrase is not None and best_phrase not in seen:
        ranked.append(best_phrase)
        seen.add(best_phrase)
    for term in search_terms:
        if term not in seen and " " not in term:
            ranked.append(term)
            seen.add(term)
    for term in search_terms:
        if term not in seen and len(term.split()) == 2:
            ranked.append(term)
            seen.add(term)
    for term in search_terms:
        if term not in seen:
            ranked.append(term)
    return ranked


def _select_independent_filter_terms(ranked_terms: list[str]) -> list[str]:
    selected: list[str] = []
    used_tokens: set[str] = set()
    for term in ranked_terms:
        term_tokens = {
            token[:-1] if len(token) > 3 and token.endswith("s") else token
            for token in term.split()
        }
        if not term_tokens & used_tokens:
            selected.append(term)
            used_tokens.update(term_tokens)
    return selected


def _search_terms_from_free_text(user_text: str) -> list[str]:
    normalized = normalize_text(user_text)
    words = [word for word in normalized.split() if word]
    terms: list[str] = []
    for size in (3, 2, 1):
        for index in range(len(words) - size + 1):
            term = " ".join(words[index : index + size]).strip()
            if term and term not in terms:
                terms.append(term)
                if len(term) > 3 and term.endswith("s"):
                    singular = term[:-1].strip()
                    if singular and singular not in terms:
                        terms.append(singular)
    return terms


def plan_multi_value_filter(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    normalized_user_text = normalize_text(user_text)
    if not normalized_user_text or _schema_requested_explicitly(normalized_user_text):
        return None
    if _extract_dimension_phrase(user_text):
        return None
    search_terms = _search_terms_from_free_text(user_text)
    if len(search_terms) < 2:
        return None
    ranked_terms = _rank_search_terms_for_filtering(search_terms)
    independent_terms = _select_independent_filter_terms(ranked_terms)
    observed_candidates = _extract_observed_candidates_from_sample_entities(session) + _extract_observed_candidates_from_cache(session)
    unit_matches: dict[str, list[dict[str, str]]] = {}
    seen_matches: set[tuple[str, str, str]] = set()
    for candidate in observed_candidates:
        unit_name = str(candidate.get("unit", "")).strip()
        column = str(candidate.get("column", "")).strip()
        value = str(candidate.get("value", "")).strip()
        if not unit_name or not column or not value:
            continue
        for form in _value_forms(value):
            if form in search_terms:
                key = (unit_name, column, value)
                if key in seen_matches:
                    break
                seen_matches.add(key)
                unit_matches.setdefault(unit_name, []).append({"column": column, "value": value})
                break
    for unit_name, matches in unit_matches.items():
        by_column: dict[str, str] = {}
        for match in matches:
            by_column.setdefault(match["column"], match["value"])
        if len(by_column) < 2:
            continue
        builder = getattr(session, "_build_select_columns_for_filtered_query", None)
        select_clause = "*"
        if callable(builder):
            try:
                select_clause = str(builder(unit_name, ""))
            except Exception:
                select_clause = "*"
        where_clause = " AND ".join(
            f"LOWER(CAST({column} AS TEXT)) = LOWER({_quote_sql_literal(value)})"
            for column, value in by_column.items()
        )
        return {
            "action": "request_new_query",
            "description": "amostrar registros filtrados por multiplos valores observados",
            "suggested_sql": f"SELECT {select_clause} FROM {unit_name} WHERE {where_clause} LIMIT 50",
        }
    recent_units = _recent_or_plausible_units(session)
    if not recent_units:
        return None
    unit_name = recent_units[0]
    text_columns, categorical_columns = _textual_columns_for_unit(session, unit_name)
    candidate_columns: list[str] = []
    for column in categorical_columns + text_columns:
        if column not in candidate_columns:
            candidate_columns.append(column)
    if not candidate_columns:
        return None
    builder = getattr(session, "_build_select_columns_for_filtered_query", None)
    select_clause = "*"
    if callable(builder):
        try:
            select_clause = str(builder(unit_name, ""))
        except Exception:
            select_clause = "*"
    grouped_clauses: list[str] = []
    for term in independent_terms[:2]:
        quoted = _quote_sql_literal(term)
        term_clauses = [f"LOWER(CAST({column} AS TEXT)) = LOWER({quoted})" for column in candidate_columns[:4]]
        if term_clauses:
            grouped_clauses.append(f"({' OR '.join(term_clauses)})")
    if not grouped_clauses:
        return None
    return {
        "action": "request_new_query",
        "description": "amostrar registros filtrados por multiplos valores",
        "suggested_sql": f"SELECT {select_clause} FROM {unit_name} WHERE {' AND '.join(grouped_clauses)} LIMIT 50",
    }


def _validate_generated_select_sql(sql: str) -> str | None:
    try:
        from orchestrator import validate_select_sql_text

        normalized = validate_select_sql_text(sql)
    except Exception:
        return None
    upper = normalized.upper()
    if (
        "SELECT FROM" in upper
        or "SELECT ," in upper
        or "WHERE LIMIT" in upper
        or "FROM  WHERE" in upper
        or "GROUP BY ORDER" in upper
        or "; LIMIT" in upper
        or "FROM  GROUP" in upper
    ):
        return None
    if "FROM" not in upper:
        return None
    return normalized


def focused_pending_requirements(session: "OrchestratorSession") -> list[dict[str, object]]:
    graph = getattr(session, "knowledge_graph", None)
    if graph is None:
        return []
    active_focus = getattr(session, "_active_focus", None) or {}
    pending: list[dict[str, object]] = []
    for node in reversed(getattr(graph, "nodes", [])):
        for requirement in getattr(node, "next_requirements", []) or []:
            if str(requirement.get("status", "")).strip().lower() != "pending":
                continue
            pending.append(requirement)
    return sort_pending_requirements_for_investigation(pending, active_focus=active_focus)


def _extract_selected_columns_from_sql(sql: str) -> list[str]:
    match = re.search(r"SELECT\s+(.+?)\s+FROM", sql, flags=re.IGNORECASE)
    if not match:
        return []
    clause = match.group(1)
    return [column.strip().split()[-1] for column in clause.split(",") if column.strip()]


def score_related_entity_requirement(session: "OrchestratorSession", requirement: dict[str, object], user_text: str) -> int:
    score = 0
    role = str(requirement.get("role", "")).strip().lower()
    if role == "related_entity":
        score += 10
    normalized_text = normalize_text(user_text)
    units = requirement.get("units") if isinstance(requirement.get("units"), list) else []
    if units:
        target = _find_mentioned_unit_approximate(user_text, [str(units[0])])
        if target:
            score += 20
    suggested_sql = str(requirement.get("suggested_action", {}).get("suggested_sql", ""))
    for column in _extract_selected_columns_from_sql(suggested_sql):
        if normalize_text(column) in normalized_text:
            score += 20
        if normalize_text(column).endswith("id"):
            score += 1
        if normalize_text(column) in {"transcript", "description", "statement", "notes"}:
            score += 5
    if any(keyword in normalized_text for keyword in ("entrevista", "entrevistas", "depoimento", "testemunha", "testemunhas")):
        if "transcript" in suggested_sql.lower() or "witness" in " ".join(str(unit).lower() for unit in units):
            score += 20
    return score


def plan_filter_for_observed_value(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    normalized_user_text = normalize_text(user_text)
    if not normalized_user_text or _schema_requested_explicitly(normalized_user_text):
        return None
    triggers = ("foc", "aprofund", "consult", "filtr", "buscar", "ver", "investig")
    if not any(token in normalized_user_text for token in triggers) and not normalized_user_text.startswith("sim "):
        return None
    candidates = _extract_observed_candidates_from_sample_entities(session) + _extract_observed_candidates_from_cache(session)
    seen: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        unit_name = str(candidate.get("unit", "")).strip()
        column = str(candidate.get("column", "")).strip()
        value = str(candidate.get("value", "")).strip()
        key = (unit_name, column, value)
        if key in seen:
            continue
        seen.add(key)
        if normalize_text(value) not in normalized_user_text:
            continue
        sql = _build_value_filter_sql(session, unit_name=unit_name, column=column or None, value=value)
        if not sql:
            continue
        return {
            "action": "request_new_query",
            "description": f"filtrar registros por valor observado em {column or unit_name}",
            "suggested_sql": sql,
        }
    active_focus = getattr(session, "_active_focus", None)
    if isinstance(active_focus, dict):
        filter_payload = active_focus.get("filter")
        units = active_focus.get("units", [])
        if isinstance(filter_payload, dict) and isinstance(units, list) and units:
            value = str(filter_payload.get("value", "")).strip()
            column = str(filter_payload.get("column", "")).strip()
            unit_name = str(units[0]).strip()
            if value and normalize_text(value) in normalized_user_text:
                sql = _build_value_filter_sql(session, unit_name=unit_name, column=column or None, value=value)
                if sql:
                    return {
                        "action": "request_new_query",
                        "description": f"filtrar registros por valor observado em {column or unit_name}",
                        "suggested_sql": sql,
                    }
    return None


def _recent_or_plausible_units(session: "OrchestratorSession") -> list[str]:
    ordered: list[str] = []
    active_focus = getattr(session, "_active_focus", None)
    if isinstance(active_focus, dict):
        for unit in active_focus.get("units", []):
            if isinstance(unit, str) and unit.strip() and unit not in ordered:
                ordered.append(unit)
    graph = getattr(session, "knowledge_graph", None)
    for node in reversed(getattr(graph, "nodes", [])) if graph is not None else []:
        unit = str(getattr(node, "unit", "")).strip()
        if unit and unit not in ordered:
            ordered.append(unit)
    for unit in getattr(session, "units", []):
        unit_name = getattr(unit, "unit_name", "")
        if isinstance(unit_name, str) and unit_name.strip() and unit_name not in ordered:
            ordered.append(unit_name)
    return ordered


def _direct_search_sql(session: "OrchestratorSession", *, unit_name: str, value: str) -> str | None:
    select_clause = "*"
    builder = getattr(session, "_build_select_columns_for_filtered_query", None)
    if callable(builder):
        try:
            select_clause = str(builder(unit_name, ""))
        except Exception:
            select_clause = "*"
    text_columns, categorical_columns = _textual_columns_for_unit(session, unit_name)
    candidate_columns: list[str] = []
    for column in categorical_columns + text_columns:
        if column not in candidate_columns:
            candidate_columns.append(column)
    if not candidate_columns:
        return None
    quoted_value = _quote_sql_literal(value)
    clauses = [f"LOWER(CAST({column} AS TEXT)) = LOWER({quoted_value})" for column in candidate_columns[:4]]
    if not clauses:
        return None
    return f"SELECT {select_clause} FROM {unit_name} WHERE {' OR '.join(clauses)} LIMIT 50"


def _numeric_option_payload(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    stripped = user_text.strip()
    if not stripped.isdigit():
        return None
    options = getattr(session, "_last_presented_options", None)
    if not isinstance(options, list):
        return None
    for option in options:
        if not isinstance(option, dict):
            continue
        if int(option.get("index", -1)) != int(stripped):
            continue
        option_text = str(option.get("text", "")).strip()
        if not option_text:
            return None
        return plan_filter_for_observed_value(session, option_text)
    return None


def _best_pending_requirement(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    pending = focused_pending_requirements(session)
    if not pending:
        return None
    normalized_text = normalize_text(user_text)
    textual_intent = any(keyword in normalized_text for keyword in ("entrevista", "entrevistas", "depoimento", "depoimentos", "testemunha", "testemunhas"))
    if textual_intent:
        scored: list[tuple[int, dict[str, object]]] = []
        for requirement in pending:
            if str(requirement.get("role", "")).strip().lower() != "related_entity":
                continue
            score = score_related_entity_requirement(session, requirement, user_text)
            if score > 10:
                scored.append((score, requirement))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored[0][1]
        return None
    def fallback_sort_key(requirement: dict[str, object]) -> tuple[int, int, str]:
        kind = str(requirement.get("kind", "")).strip().lower()
        role = str(requirement.get("role", "")).strip().lower()
        kind_score = 0 if kind == "query" else 1 if kind == "analyze_horizontal" else 2 if kind == "schema" else 3
        role_score = 0 if role == "textual_clue" else 1 if role == "related_entity" else 2 if role == "drilldown" else 3
        return (kind_score, role_score, str(requirement.get("id", "")).strip())

    for requirement in sorted(pending, key=fallback_sort_key):
        payload = _action_from_requirement(requirement)
        if payload is not None and not already_executed(session, payload):
            return requirement
    return None


def plan_direct_value_command(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    value_terms = _direct_value_terms(user_text)
    if not value_terms:
        return None
    observed_candidates = _extract_observed_candidates_from_sample_entities(session) + _extract_observed_candidates_from_cache(session)
    active_focus = getattr(session, "_active_focus", None)
    if isinstance(active_focus, dict):
        filter_payload = active_focus.get("filter")
        units = active_focus.get("units", [])
        if isinstance(filter_payload, dict) and isinstance(units, list) and units:
            observed_candidates.append(
                {
                    "unit": str(units[0]).strip(),
                    "column": str(filter_payload.get("column", "")).strip(),
                    "value": str(filter_payload.get("value", "")).strip(),
                }
            )
    for term in value_terms:
        normalized_term = normalize_text(term)
        for candidate in observed_candidates:
            candidate_value = str(candidate.get("value", "")).strip()
            if not candidate_value or normalize_text(candidate_value) != normalized_term:
                continue
            unit_name = str(candidate.get("unit", "")).strip()
            column = str(candidate.get("column", "")).strip()
            if not unit_name:
                continue
            sql = _build_value_filter_sql(session, unit_name=unit_name, column=column or None, value=candidate_value)
            if sql:
                return {
                    "action": "request_new_query",
                    "description": "amostrar registros filtrados por valor observado",
                    "suggested_sql": sql,
                }
    for term in value_terms:
        for unit_name in _recent_or_plausible_units(session):
            sql = _direct_search_sql(session, unit_name=unit_name, value=term)
            if sql:
                return {
                    "action": "request_new_query",
                    "description": "amostrar registros filtrados por valor",
                    "suggested_sql": sql,
                }
    return None

def first_pending_requirement(graph) -> dict[str, object] | None:
    if graph is None:
        return None
    pending = graph.pending_requirements() if hasattr(graph, "pending_requirements") else []
    if not pending:
        return None

    def requirement_sort_key(requirement: dict[str, object]) -> tuple[int, int, int]:
        role = str(requirement.get("role", "")).strip().lower()
        role_score = 0 if role == "textual_clue" else 1 if role == "related_entity" else 2 if role == "drilldown" else 3
        source_node_id = str(requirement.get("source_node_id", "")).strip()
        derived_score = 0 if source_node_id else 1
        kind = str(requirement.get("kind", "")).strip().lower()
        kind_score = 0 if kind == "query" else 1 if kind == "analyze_horizontal" else 2 if kind == "recall" else 3
        return (role_score, derived_score, kind_score)

    best_requirement = pending[0]
    best_key = requirement_sort_key(best_requirement)
    for requirement in pending[1:]:
        current_key = requirement_sort_key(requirement)
        if current_key < best_key:
            best_requirement = requirement
            best_key = current_key
    return best_requirement


def mark_requirement_resolved(graph, requirement_id: str) -> bool:
    if graph is None or not requirement_id or not hasattr(graph, "mark_requirement_resolved"):
        return False
    return bool(graph.mark_requirement_resolved(requirement_id))


def already_executed(session: "OrchestratorSession", action_payload: dict[str, object]) -> bool:
    execution_log = getattr(session, "_execution_log", [])
    action = str(action_payload.get("action", ""))
    if action == "analyze_unit":
        unit_name = str(action_payload.get("unit_name", ""))
        return any(entry.get("action") == "analyze_unit" and entry.get("unit") == unit_name for entry in execution_log)
    if action == "analyze_horizontal":
        unit_a = str(action_payload.get("unit_a", ""))
        unit_b = str(action_payload.get("unit_b", ""))
        for entry in execution_log:
            if entry.get("action") != "analyze_horizontal":
                continue
            seen = {entry.get("unit_a", ""), entry.get("unit_b", "")}
            if seen == {unit_a, unit_b}:
                return True
    if action == "request_new_query":
        sql = str(action_payload.get("suggested_sql", "")).strip()
        sql_units = set(extract_units_from_sql(sql))
        for entry in execution_log:
            entry_sql = str(entry.get("sql", "")).strip()
            if not entry_sql:
                continue
            if set(extract_units_from_sql(entry_sql)) == sql_units and entry_sql == sql:
                return True
    return False


def _is_continuation(text: str) -> bool:
    return normalize_text(text) in CONTINUATION_WORDS


def _action_from_requirement(requirement: dict[str, object]) -> dict[str, object] | None:
    suggested = requirement.get("suggested_action")
    if not isinstance(suggested, dict):
        return None
    payload = dict(suggested)
    requirement_id = str(requirement.get("id", "")).strip()
    if requirement_id:
        payload["__requirement_id"] = requirement_id
        payload["_source_requirement_id"] = requirement_id
    return payload


def plan_deterministic_action(
    session: "OrchestratorSession",
    user_text: str,
    *,
    last_result: str | None = None,
    last_error: str | None = None,
) -> dict[str, object] | None:
    del last_result, last_error
    stripped = user_text.strip()
    normalized = normalize_text(stripped)
    unit_names = [unit.unit_name for unit in getattr(session, "units", [])]
    graph = getattr(session, "knowledge_graph", None)

    if stripped.upper().startswith("SELECT "):
        return {
            "action": "request_new_query",
            "description": "consulta SQL informada pelo usuário",
            "suggested_sql": stripped,
        }

    requirement = _best_pending_requirement(session, stripped)
    if is_short_confirmation(stripped) and requirement is not None:
        payload = _action_from_requirement(requirement)
        if payload is not None and not already_executed(session, payload):
            return payload

    if normalized in {"tabelas", "tables"}:
        return {"action": "tables"}

    if _schema_requested_explicitly(normalized):
        unit_name = find_mentioned_unit(stripped, unit_names)
        if unit_name:
            return {"action": "schema", "table": unit_name}

    grouped_count_action = plan_grouped_count_by_dimension(session, stripped)
    if grouped_count_action is not None and not already_executed(session, grouped_count_action):
        return grouped_count_action

    count_action = plan_count_records_command(session, stripped)
    if count_action is not None and not already_executed(session, count_action):
        return count_action

    direct_value_action = plan_direct_value_command(session, stripped)
    if direct_value_action is not None and not already_executed(session, direct_value_action):
        return direct_value_action

    observed_value_action = plan_filter_for_observed_value(session, stripped)
    if observed_value_action is not None and not already_executed(session, observed_value_action):
        return observed_value_action

    numeric_option_action = _numeric_option_payload(session, stripped)
    if numeric_option_action is not None and not already_executed(session, numeric_option_action):
        return numeric_option_action

    multi_value_action = plan_multi_value_filter(session, stripped)
    if multi_value_action is not None and not already_executed(session, multi_value_action):
        return multi_value_action

    if any(token in normalized for token in ("explorar", "analisar", "investigar", "ver", "aprofundar")):
        unit_name = find_mentioned_unit(stripped, unit_names)
        if unit_name:
            payload = {"action": "analyze_unit", "unit_name": unit_name}
            if not already_executed(session, payload):
                return payload

    if any(token in normalized for token in ("cruzar", "juntar", "relacionar", "conectar")):
        pair = find_mentioned_unit_pair(stripped, unit_names)
        if pair:
            payload = {"action": "analyze_horizontal", "unit_a": pair[0], "unit_b": pair[1]}
            if not already_executed(session, payload):
                return payload

    if requirement is not None and _is_continuation(stripped):
        payload = _action_from_requirement(requirement)
        if payload is not None and not already_executed(session, payload):
            return payload

    if requirement is not None and any(
        keyword in normalized for keyword in ("entrevista", "entrevistas", "depoimento", "depoimentos", "testemunha", "testemunhas")
    ):
        payload = _action_from_requirement(requirement)
        if payload is not None and not already_executed(session, payload):
            return payload

    return None
