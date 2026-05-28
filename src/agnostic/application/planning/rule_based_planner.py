from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator import OrchestratorSession


logger = logging.getLogger(__name__)


SHORT_CONFIRMATIONS = {"sim", "si", "ok", "pode", "prossiga", "continue", "vai", "execute"}
CONTINUATION_WORDS = SHORT_CONFIRMATIONS | {"continue", "continue daí", "continue dai", "siga", "avançe", "avance"}
TEXTUAL_INTENT_TERMS = {
    "entrevista",
    "entrevistas",
    "depoimento",
    "depoimentos",
    "relato",
    "relatos",
    "testemunha",
    "testemunhas",
    "transcript",
    "interview",
    "statement",
    "testimony",
}
TEXTUAL_COLUMN_TOKENS = {
    "transcript",
    "description",
    "text",
    "note",
    "content",
    "message",
    "comment",
    "statement",
    "narrative",
    "body",
}
LOW_SIGNAL_LOG_TOKENS = {"event", "log", "checkin", "history", "visit", "activity"}


def sort_pending_requirements_for_investigation(
    requirements: list[dict[str, object]],
    *,
    active_focus: dict[str, object] | None = None,
    session: "OrchestratorSession" | None = None,
    graph: object | None = None,
    user_text: str = "",
) -> list[dict[str, object]]:
    clue_group_id = ""
    if isinstance(active_focus, dict):
        clue_group_id = str(active_focus.get("clue_group_id", "")).strip()

    normalized_user_text = normalize_text(user_text)

    graph_obj = graph if graph is not None else (getattr(session, "knowledge_graph", None) if session is not None else None)

    def _unit_is_already_analyzed(unit_name: str) -> bool:
        if not unit_name:
            return False
        if session is not None:
            execution_log = getattr(session, "_execution_log", [])
            analyzed = any(
                entry.get("action") == "analyze_unit" and entry.get("unit") == unit_name
                for entry in execution_log
            )
            cached = bool(getattr(session, "_core_cache", {}).get(f"unit:{unit_name}"))
            if analyzed or cached:
                return True
            nodes = getattr(graph_obj, "nodes", []) if graph_obj is not None else []
        else:
            nodes = getattr(graph_obj, "nodes", []) if graph_obj is not None else []
        for node in nodes:
            node_unit = str(getattr(node, "unit", "")).strip()
            if node_unit != unit_name:
                continue
            node_columns = getattr(node, "columns", []) or []
            node_data = getattr(node, "data", {})
            if not isinstance(node_data, dict):
                node_data = {}
            evidence = node_data.get("evidence", {})
            operational_summary = node_data.get("operational_summary", {})
            if (
                node_columns
                or isinstance(evidence, dict) and bool(evidence.get("columns"))
                or isinstance(operational_summary, dict) and bool(operational_summary.get("columns"))
                or bool(getattr(node, "next_requirements", []))
            ):
                return True
        return False

    def _is_useful_operational_requirement(requirement: dict[str, object]) -> bool:
        kind = str(requirement.get("kind", "")).strip().lower()
        role = str(requirement.get("role", "")).strip().lower()
        if kind in {"query", "template", "analyze_horizontal", "analyze_vertical"}:
            return True
        if role in {"textual_clue", "related_entity"}:
            return True
        suggested_action = requirement.get("suggested_action")
        if isinstance(suggested_action, dict):
            action = str(suggested_action.get("action", "")).strip().lower()
            if action in {"request_new_query", "analyze_vertical"}:
                return True
        return False

    def schema_deprioritized(requirement: dict[str, object]) -> bool:
        if str(requirement.get("kind", "")).strip().lower() != "schema":
            return False
        if _schema_requested_explicitly(normalized_user_text):
            return False
        units = requirement.get("units", [])
        unit_name = str(units[0]).strip() if isinstance(units, list) and units else ""
        if unit_name and not _unit_is_already_analyzed(unit_name):
            return False
        for candidate in requirements:
            if candidate is requirement or str(candidate.get("status", "")).strip().lower() != "pending":
                continue
            if _is_useful_operational_requirement(candidate):
                return True
        return False

    def role_priority(requirement: dict[str, object]) -> tuple[int, ...]:
        kind = str(requirement.get("kind", "")).strip().lower()
        role = str(requirement.get("role", "")).strip().lower()
        source_node_id = str(requirement.get("source_node_id", "")).strip()
        parent_requirement_id = str(requirement.get("parent_requirement_id", "")).strip()
        active_focus_node_id = str(active_focus.get("node_id", "")).strip() if isinstance(active_focus, dict) else ""
        active_focus_requirement_id = str(active_focus.get("source_requirement_id", "")).strip() if isinstance(active_focus, dict) else ""

        if clue_group_id and role == "textual_clue" and source_node_id == clue_group_id:
            return (0, 0)
        if role == "textual_clue" and source_node_id == active_focus_node_id:
            return (4, 0)
        if role == "drilldown" and (
            source_node_id == active_focus_node_id
            or parent_requirement_id == active_focus_requirement_id
        ):
            return (5, 0)
        if role == "textual_clue":
            return (6, 0)
        if role == "related_entity":
            related_score = score_related_entity_requirement(session, requirement, user_text) if session is not None else (0, 0, 0, 0, 0, 0)
            return (8, *tuple(-int(part) for part in related_score))
        if kind in {"query", "template", "analyze_vertical"}:
            return (11, 0)
        if kind == "analyze_horizontal":
            return (12, 0)
        if role == "drilldown" or source_node_id:
            return (13, 0)
        if kind == "schema":
            return (14 if schema_deprioritized(requirement) else 2, 0)
        if kind == "recall":
            return (15, 0)
        return (16, 0)

    decorated: list[tuple[tuple[int, ...], dict[str, object]]] = []
    for encounter_index, requirement in enumerate(requirements):
        role = str(requirement.get("role", "")).strip().lower()
        source_node_id = str(requirement.get("source_node_id", "")).strip()
        group_order = encounter_index if role == "textual_clue" and source_node_id == clue_group_id else 0
        decorated.append(((*role_priority(requirement), group_order, encounter_index), requirement))
    decorated.sort(key=lambda item: item[0])
    return [requirement for _, requirement in decorated]


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


def _textual_intent_requested(user_text: str) -> bool:
    normalized = normalize_text(user_text)
    if not normalized:
        return False
    terms = set(normalized.split())
    return bool(terms & TEXTUAL_INTENT_TERMS)


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


def score_related_entity_requirement(
    session: "OrchestratorSession" | None,
    requirement: dict[str, object],
    user_text: str = "",
) -> tuple[int, int, int, int, int, int]:
    role = str(requirement.get("role", "")).strip().lower()
    if role != "related_entity":
        return (-1, -1, -1, -1, -1, -1)
    target_units = requirement.get("units", [])
    target_unit = str(target_units[0]).strip() if isinstance(target_units, list) and target_units else ""
    text_columns: list[str] = []
    categorical_columns: list[str] = []
    if session is not None and target_unit:
        text_columns, categorical_columns = _textual_columns_for_unit(session, target_unit)
    normalized_columns = [normalize_text(column).replace(" ", "_") for column in text_columns + categorical_columns]
    strong_text_columns = sum(
        1
        for column in normalized_columns
        if any(token in column for token in TEXTUAL_COLUMN_TOKENS)
    )
    textual_columns = len(text_columns)
    textual_intent = 1 if _textual_intent_requested(user_text) else 0
    direct_key_relation = 0
    suggested = requirement.get("suggested_action")
    if isinstance(suggested, dict):
        sql = str(suggested.get("suggested_sql", "")).strip().lower()
        if " where " in sql and "=" in sql:
            direct_key_relation = 1
    source_from_textual_path = 1 if str(requirement.get("source_node_id", "")).strip() else 0
    unexplored_target = 1
    if session is not None and isinstance(suggested, dict):
        action_payload = dict(suggested)
        if already_executed(session, action_payload):
            unexplored_target = 0
    low_signal_penalty = 0
    normalized_unit = normalize_text(target_unit).replace(" ", "_")
    if strong_text_columns == 0 and any(token in normalized_unit for token in LOW_SIGNAL_LOG_TOKENS):
        low_signal_penalty = 1
    elif strong_text_columns == 0 and textual_columns == 0:
        low_signal_penalty = 1
    return (
        textual_intent * strong_text_columns,
        strong_text_columns,
        textual_intent * textual_columns,
        direct_key_relation + source_from_textual_path + unexplored_target,
        textual_columns,
        -low_signal_penalty,
    )


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


def _rank_search_terms_for_filtering(search_terms: list[str]) -> list[str]:
    normalized_terms = [normalize_text(term) for term in search_terms if normalize_text(term)]
    observed_terms = set(normalized_terms)
    singular_terms: list[str] = []
    preferred_two_word_terms: list[str] = []
    secondary_two_word_terms: list[str] = []
    single_word_terms: list[str] = []
    other_multi_word_terms: list[str] = []
    full_length_terms: list[str] = []
    max_word_count = max((len(term.split()) for term in normalized_terms), default=0)
    seen: set[str] = set()

    for term in normalized_terms:
        if term in seen:
            continue
        seen.add(term)
        word_count = len(term.split())
        is_simple_singular = word_count == 1 and len(term) > 2 and not term.endswith("s") and f"{term}s" in observed_terms
        if is_simple_singular:
            singular_terms.append(term)
        elif word_count == 2:
            first_word = term.split()[0]
            if len(first_word) > 3 and first_word.endswith("s"):
                secondary_two_word_terms.append(term)
            else:
                preferred_two_word_terms.append(term)
        elif word_count == 1:
            single_word_terms.append(term)
        elif word_count == max_word_count and word_count >= 3:
            full_length_terms.append(term)
        else:
            other_multi_word_terms.append(term)

    ranked: list[str] = []
    for bucket in (singular_terms, preferred_two_word_terms, single_word_terms, secondary_two_word_terms, other_multi_word_terms, full_length_terms):
        for term in bucket:
            if term not in ranked:
                ranked.append(term)
    return ranked


def _select_independent_filter_terms(ranked_terms: list[str]) -> list[str]:
    normalized_terms = [normalize_text(term) for term in ranked_terms if normalize_text(term)]
    observed_terms = set(normalized_terms)
    selected: list[str] = []

    def _is_simple_singular(term: str) -> bool:
        return len(term.split()) == 1 and len(term) > 2 and not term.endswith("s") and f"{term}s" in observed_terms

    for term in normalized_terms:
        if term in selected:
            continue
        if len(selected) >= 3:
            break
        term_tokens = set(term.split())
        if len(term.split()) == 1 and len(term) > 3 and term.endswith("s") and term[:-1] in selected:
            continue
        if len(term.split()) > 1:
            skip_term = False
            for chosen in selected:
                chosen_tokens = set(chosen.split())
                if len(chosen.split()) > 1 and term_tokens & chosen_tokens:
                    skip_term = True
                    break
                if len(chosen.split()) == 1 and (chosen in term_tokens or f"{chosen}s" in term_tokens):
                    skip_term = True
                    break
            if skip_term:
                continue
        if len(term.split()) == 1 and any(term in chosen.split() for chosen in selected if len(chosen.split()) > 1):
            if not _is_simple_singular(term):
                continue
        if len(term.split()) > 1:
            selected = [chosen for chosen in selected if chosen not in term.split() or _is_simple_singular(chosen)]
        selected.append(term)
    return selected


def _sanitize_select_clause(select_clause: str) -> str:
    columns = [column.strip() for column in str(select_clause).split(",") if column.strip()]
    if not columns:
        return "*"
    return ", ".join(columns)


def plan_multi_value_filter(session: "OrchestratorSession", user_text: str) -> dict[str, object] | None:
    normalized_user_text = normalize_text(user_text)
    if not normalized_user_text or _schema_requested_explicitly(normalized_user_text):
        return None
    search_terms = _search_terms_from_free_text(user_text)
    if len(search_terms) < 2:
        return None
    ranked_terms = _rank_search_terms_for_filtering(search_terms)
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
                select_clause = _sanitize_select_clause(str(builder(unit_name, "")))
            except Exception:
                select_clause = "*"
        conditions = [f"LOWER(CAST({column} AS TEXT)) = LOWER({_quote_sql_literal(value)})" for column, value in by_column.items()]
        sql = build_safe_select_sql(unit_name, [select_clause], conditions, mode="AND", limit=50)
        if not sql:
            continue
        validated_sql = _validate_generated_select_sql(sql)
        if not validated_sql:
            continue
        return {
            "action": "request_new_query",
            "description": "amostrar registros filtrados por multiplos valores observados",
            "suggested_sql": validated_sql,
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
            select_clause = _sanitize_select_clause(str(builder(unit_name, "")))
        except Exception:
            select_clause = "*"
    selected_terms = _select_independent_filter_terms(ranked_terms)
    groups: list[str] = []
    for term in selected_terms:
        quoted = _quote_sql_literal(term)
        group_clauses: list[str] = []
        for column in candidate_columns[:4]:
            group_clauses.append(f"LOWER(CAST({column} AS TEXT)) = LOWER({quoted})")
        if group_clauses:
            groups.append("(" + " OR ".join(group_clauses) + ")")
    if not groups:
        return None
    sql = build_safe_select_sql(unit_name, [select_clause], groups, mode="AND", limit=50)
    if not sql:
        return None
    validated_sql = _validate_generated_select_sql(sql)
    if not validated_sql:
        return None
    return {
        "action": "request_new_query",
        "description": "amostrar registros filtrados por multiplos valores",
        "suggested_sql": validated_sql,
    }


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
    clauses = [f"CAST({column} AS TEXT) = {quoted_value}" for column in candidate_columns[:4]]
    if not clauses:
        return None
    return f"SELECT {select_clause} FROM {unit_name} WHERE {' OR '.join(clauses)} LIMIT 50"


def _validate_generated_select_sql(sql: str) -> str | None:
    normalized = " ".join(str(sql).strip().split())
    if not normalized:
        return None
    upper = normalized.upper()
    invalid_patterns = ("SELECT FROM", "SELECT ,", ", FROM", "WHERE LIMIT", "FROM WHERE", "WHERE ) LIMIT")
    if not upper.startswith("SELECT ") or " FROM " not in upper or " WHERE " not in upper or " LIMIT " not in upper:
        return None
    if any(pattern in upper for pattern in invalid_patterns):
        return None
    try:
        from orchestrator import validate_select_sql_text
    except Exception:
        return normalized
    try:
        validated = validate_select_sql_text(normalized)
    except Exception:
        return None
    return " ".join(str(validated).strip().split())


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
    pending = getattr(graph, "pending_requirements", lambda: [])()
    if not pending:
        return None
    return pending[0]


def _best_related_entity_requirement(
    session: "OrchestratorSession",
    requirements: list[dict[str, object]],
    user_text: str,
) -> dict[str, object] | None:
    candidates: list[dict[str, object]] = []
    for requirement in requirements:
        if str(requirement.get("role", "")).strip().lower() != "related_entity":
            continue
        payload = _action_from_requirement(requirement)
        if payload is None or already_executed(session, payload):
            continue
        candidates.append(requirement)
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda requirement: score_related_entity_requirement(session, requirement, user_text),
        reverse=True,
    )
    best = ranked[0]
    best_score = score_related_entity_requirement(session, best, user_text)
    if _textual_intent_requested(user_text) and best_score[:3] <= (0, 0, 0):
        return None
    if best_score <= (0, 0, 0, 0, 0, 0):
        return None
    return best


def _first_available_requirement_action(
    session: "OrchestratorSession",
    requirements: list[dict[str, object]],
    *,
    user_text: str = "",
) -> dict[str, object] | None:
    explicit_schema = _schema_requested_explicitly(normalize_text(user_text))
    deferred_schema: list[dict[str, object]] = []
    for requirement in requirements:
        payload = _action_from_requirement(requirement)
        if payload is None or str(payload.get("action", "")).strip() == "tables":
            continue
        if already_executed(session, payload):
            continue
        if (
            not explicit_schema
            and str(requirement.get("kind", "")).strip().lower() == "schema"
            and any(
                str(candidate.get("kind", "")).strip().lower() != "schema"
                and _action_from_requirement(candidate) is not None
                and not already_executed(session, _action_from_requirement(candidate) or {})
                for candidate in requirements
            )
        ):
            deferred_schema.append(requirement)
            continue
        return payload
    for requirement in deferred_schema:
        payload = _action_from_requirement(requirement)
        if payload is not None and not already_executed(session, payload):
            return payload
    return None


def get_structured_option(session: "OrchestratorSession", index: int) -> dict[str, object] | None:
    options = getattr(session, "_last_presented_options", None)
    if not isinstance(options, list) or index <= 0:
        return None
    for option in options:
        if isinstance(option, dict) and int(option.get("index", -1)) == index:
            return dict(option)
    return None


def _structured_option_to_action(session: "OrchestratorSession", option: dict[str, object]) -> dict[str, object] | None:
    suggested_action = option.get("suggested_action")
    if isinstance(suggested_action, dict):
        return dict(suggested_action)
    option_text = str(option.get("text", "")).strip()
    if not option_text:
        return None
    normalized = normalize_text(option_text)
    if any(token in normalized for token in ("cruz", "juntar", "relacionar", "conectar")):
        return None
    observed_value_action = plan_filter_for_observed_value(session, option_text)
    if observed_value_action is not None:
        return observed_value_action
    direct_value_action = plan_direct_value_command(session, option_text)
    if direct_value_action is not None:
        return direct_value_action
    return None


def focused_pending_requirements(session: "OrchestratorSession") -> list[dict[str, object]]:
    graph = getattr(session, "knowledge_graph", None)
    active_focus = getattr(session, "_active_focus", None)
    if graph is None or not isinstance(active_focus, dict):
        return []
    node_id = str(active_focus.get("node_id", "")).strip()
    source_requirement_id = str(active_focus.get("source_requirement_id", "")).strip()
    clue_group_id = str(active_focus.get("clue_group_id", "")).strip()
    if not node_id and not source_requirement_id:
        return []
    focused: list[tuple[int, int, dict[str, object]]] = []
    for node_index, node in enumerate(getattr(graph, "nodes", [])):
        for req_index, requirement in enumerate(getattr(node, "next_requirements", [])):
            if str(requirement.get("status", "")).strip() != "pending":
                continue
            req_node_id = str(requirement.get("source_node_id", "")).strip()
            parent_requirement_id = str(requirement.get("parent_requirement_id", "")).strip()
            role = str(requirement.get("role", "")).strip().lower()
            if (
                req_node_id == node_id
                or parent_requirement_id == source_requirement_id
                or role in {"drilldown", "textual_clue"}
                or req_node_id
            ):
                focused.append((node_index, req_index, requirement))

    return sort_pending_requirements_for_investigation(
        [requirement for _, _, requirement in focused],
        active_focus=active_focus,
        session=session,
        user_text="",
    )


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
    source_node_id = str(requirement.get("source_node_id", "")).strip()
    if source_node_id:
        payload["_requirement_source_node_id"] = source_node_id
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

    if normalized in {"tabelas", "tables"}:
        return {"action": "tables"}

    if _schema_requested_explicitly(normalized):
        unit_name = find_mentioned_unit(stripped, unit_names)
        if unit_name:
            return {"action": "schema", "table": unit_name}

    if _textual_intent_requested(stripped):
        focus_requirements = focused_pending_requirements(session)
        all_pending = getattr(graph, "pending_requirements", lambda **kwargs: [])(
            active_focus=getattr(session, "_active_focus", None)
        )
        related_requirement = _best_related_entity_requirement(
            session,
            focus_requirements or all_pending,
            stripped,
        )
        if related_requirement is None:
            related_requirement = _best_related_entity_requirement(session, all_pending, stripped)
        if related_requirement is not None:
            payload = _action_from_requirement(related_requirement)
            if payload is not None and str(payload.get("action", "")).strip() != "tables":
                return payload

    direct_value_action = plan_direct_value_command(session, stripped)
    if direct_value_action is not None and not already_executed(session, direct_value_action):
        return direct_value_action

    observed_value_action = plan_filter_for_observed_value(session, stripped)
    if observed_value_action is not None and not already_executed(session, observed_value_action):
        return observed_value_action

    multi_value_action = plan_multi_value_filter(session, stripped)
    if multi_value_action is not None and not already_executed(session, multi_value_action):
        return multi_value_action

    if normalized in {"1", "2", "3", "4", "5"}:
        option = get_structured_option(session, int(normalized))
        if option:
            action = _structured_option_to_action(session, option)
            if action is not None and not already_executed(session, action):
                return action
        return None

    focus_requirements = focused_pending_requirements(session)
    all_pending_requirements = getattr(graph, "pending_requirements", lambda **kwargs: [])(
        active_focus=getattr(session, "_active_focus", None)
    )
    requirement = focus_requirements[0] if focus_requirements else first_pending_requirement(graph)
    if is_short_confirmation(stripped):
        for requirement_pool in (focus_requirements, all_pending_requirements):
            if not requirement_pool:
                continue
            payload = _first_available_requirement_action(
                session,
                requirement_pool,
                user_text=stripped,
            )
            if payload is not None:
                return payload

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
        for requirement_pool in (focus_requirements, all_pending_requirements):
            if not requirement_pool:
                continue
            payload = _first_available_requirement_action(
                session,
                requirement_pool,
                user_text=stripped,
            )
            if payload is not None:
                return payload

    return None
