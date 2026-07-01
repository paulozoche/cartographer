from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agnostic.application.planning.entity_resolution import normalize_text
from agnostic.application.planning.planning_context import PlanningContext

if TYPE_CHECKING:
    from orchestrator import OrchestratorSession


SHORT_CONFIRMATIONS = {"sim", "si", "ok", "não", "nao", "pode", "prossiga", "continue", "vai", "execute"}
CONTINUATION_WORDS = SHORT_CONFIRMATIONS | {"continue", "continue daí", "continue dai", "siga", "avançe", "avance"}


def _as_planning_context(session_or_context: "OrchestratorSession | PlanningContext") -> PlanningContext:
    if isinstance(session_or_context, PlanningContext):
        return session_or_context
    from agnostic.planner import build_planning_context

    return build_planning_context(session_or_context)


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


def _numeric_option_payload(session_or_context: "OrchestratorSession | PlanningContext", user_text: str) -> dict[str, object] | None:
    context = _as_planning_context(session_or_context)
    stripped = user_text.strip()
    if not stripped.isdigit():
        return None
    options = context.last_presented_options
    if not isinstance(options, list):
        return None
    for option in options:
        if not isinstance(option, dict):
            continue
        if int(option.get("index", -1)) != int(stripped):
            continue
        for key in ("action_payload", "suggested_action", "payload", "action"):
            payload = option.get(key)
            if isinstance(payload, dict) and str(payload.get("action", "")).strip():
                return dict(payload)
    return None


def _action_from_last_presented_option(session_or_context: "OrchestratorSession | PlanningContext", user_text: str) -> dict[str, object] | None:
    if not is_short_confirmation(user_text):
        return None
    context = _as_planning_context(session_or_context)
    options = context.last_presented_options
    if not isinstance(options, list):
        return None
    actionable_payloads: list[dict[str, object]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        suggested = option.get("suggested_action") or option.get("action_payload") or option.get("payload") or option.get("action")
        if not isinstance(suggested, dict):
            continue
        payload = dict(suggested)
        if not str(payload.get("action", "")).strip():
            continue
        actionable_payloads.append(payload)
    return actionable_payloads[0] if actionable_payloads else None


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


def already_executed(session_or_context: "OrchestratorSession | PlanningContext", action_payload: dict[str, object]) -> bool:
    context = _as_planning_context(session_or_context)
    execution_log = context.execution_log
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
    session_or_context: "OrchestratorSession | PlanningContext",
    user_text: str,
    *,
    last_result: str | None = None,
    last_error: str | None = None,
) -> dict[str, object] | None:
    context = _as_planning_context(session_or_context)
    del last_result, last_error
    stripped = user_text.strip()
    normalized = normalize_text(stripped)

    if normalized in {"tabelas", "tables"}:
        return {"action": "tables"}

    numeric_action = _numeric_option_payload(context, stripped)
    if numeric_action is not None and not already_executed(context, numeric_action):
        return numeric_action

    if is_short_confirmation(stripped):
        option_payload = _action_from_last_presented_option(context, stripped)
        if option_payload is not None and not already_executed(context, option_payload):
            return option_payload

    return None
