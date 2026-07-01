"""Intent and action payload validation for the Planner."""

from __future__ import annotations

from agnostic.application.planning.entity_resolution import normalize_text
from agnostic.application.planning.rule_based_planner import is_short_confirmation
from agnostic.planner.explicit import (
    _available_units_from_session_or_context,
    _mentioned_available_unit,
)


def validate_interpreter_execute_action(
    session_or_context,
    action_payload: dict[str, object],
) -> dict[str, object] | None:
    if not isinstance(action_payload, dict):
        return None
    action = str(action_payload.get("action", "")).strip()
    available = {
        normalize_text(unit_name)
        for unit_name in _available_units_from_session_or_context(session_or_context)
    }
    if action == "analyze_unit":
        unit_name = str(action_payload.get("unit_name", "")).strip()
        if not unit_name or normalize_text(unit_name) not in available:
            return None
        canonical = next(
            (
                candidate
                for candidate in _available_units_from_session_or_context(session_or_context)
                if normalize_text(candidate) == normalize_text(unit_name)
            ),
            unit_name,
        )
        return {"action": "analyze_unit", "unit_name": canonical}
    if action == "schema":
        table = str(action_payload.get("table", "")).strip()
        if not table or normalize_text(table) not in available:
            return None
        canonical = next(
            (
                candidate
                for candidate in _available_units_from_session_or_context(session_or_context)
                if normalize_text(candidate) == normalize_text(table)
            ),
            table,
        )
        return {"action": "schema", "table": canonical}
    if action == "request_new_query":
        suggested_sql = str(action_payload.get("suggested_sql", "")).strip()
        description = str(action_payload.get("description", "")).strip()
        if not suggested_sql.upper().startswith("SELECT"):
            return None
        validated: dict[str, object] = {"action": "request_new_query", "suggested_sql": suggested_sql}
        if description:
            validated["description"] = description
        return validated
    return None


def validate_action_payload(session, action_payload: dict) -> dict | None:
    action = action_payload.get("action")
    available_units = _available_units_from_session_or_context(session)
    available_norm = {normalize_text(unit): unit for unit in available_units}

    if action == "analyze_unit":
        unit = action_payload.get("unit_name", "")
        unit_norm = normalize_text(unit)
        if unit_norm in available_norm:
            return {"action": "analyze_unit", "unit_name": available_norm[unit_norm]}
        return None

    if action == "schema":
        table = action_payload.get("table", "")
        table_norm = normalize_text(table)
        if table_norm in available_norm:
            return {"action": "schema", "table": available_norm[table_norm]}
        return None

    if action == "request_new_query":
        sql = action_payload.get("suggested_sql", "")
        if sql.upper().strip().startswith("SELECT"):
            return {"action": "request_new_query", "suggested_sql": sql}
        return None

    return None


def _executable_option_count(session) -> int:
    if hasattr(session, "executable_presented_options"):
        return len(session.executable_presented_options())
    options = getattr(session, "_last_presented_options", []) or []
    return sum(
        1
        for option in options
        if isinstance(option, dict)
        and str(option.get("kind", "")).strip() == "executable"
        and isinstance(option.get("action_payload"), dict)
    )


def _clarify_response(
    session,
    parsed: dict,
    *,
    fallback: str,
    reason: str,
    kind: str = "clarify",
) -> dict[str, object]:
    clarifying = str(parsed.get("clarifying_question") or fallback).strip() or fallback
    if hasattr(session, "_build_structured_choice_message"):
        rendered = session.rendered_presented_options() if hasattr(session, "rendered_presented_options") else []
        if len(rendered) == 1:
            option = rendered[0]
            lines = [
                clarifying,
                f"A opção disponível agora é: {str(option.get('display_text', '')).strip()}.",
                "Responda sim ou não.",
            ]
            return {"kind": kind, "response": "\n".join(line for line in lines if line), "reason": reason}
        if len(rendered) > 1:
            return {
                "kind": kind,
                "response": session._build_structured_choice_message(clarifying, "Escolha uma opção pelo número."),
                "reason": reason,
            }
    return {"kind": kind, "response": clarifying, "reason": reason}


def _ambiguous_execution_prevented(session, parsed: dict) -> dict[str, object] | None:
    if _executable_option_count(session) <= 1:
        return None
    if not is_short_confirmation(str(parsed.get("_user_text", ""))):
        return None
    mode = parsed.get("mode")
    if mode not in {"execute_pending", "confirm_pending", "execute_option", "select_option"}:
        return None
    clarifying = str(parsed.get("clarifying_question") or "").strip()
    if hasattr(session, "_build_structured_choice_message"):
        response = session._build_structured_choice_message(
            clarifying or "Encontrei mais de uma opção executável.",
            "Escolha uma opção pelo número.",
        )
    else:
        response = clarifying or "Escolha uma opção pelo número."
    return {"kind": "clarify", "response": response, "reason": "ambiguous_execution_prevented"}


def validate_and_convert_intent(session, parsed: dict, user_text: str = "") -> dict[str, object]:
    """Validate LLM intent JSON and convert to a system turn decision."""

    working = dict(parsed)
    working["_user_text"] = user_text
    mode = working.get("mode")
    confidence = working.get("confidence", "low")
    reason = str(working.get("reason", ""))

    blocked = _ambiguous_execution_prevented(session, working)
    if blocked is not None:
        return blocked

    if confidence == "low":
        return _clarify_response(
            session,
            working,
            fallback="Pode reformular sua pergunta?",
            reason=reason,
        )

    if mode == "execute_action":
        action_payload = working.get("action_payload")
        if not isinstance(action_payload, dict):
            return {"kind": "clarify", "response": "Ação mal formatada. Pode repetir?", "reason": "invalid_action_payload"}

        validated = validate_action_payload(session, action_payload)
        if validated:
            return {"kind": "execute_pending", "action_payload": validated, "reason": reason}
        return _clarify_response(
            session,
            working,
            fallback="Essa unidade não existe. Escolha uma disponível.",
            reason="invalid_unit",
        )

    if mode in {"execute_option", "select_option"}:
        option_id = working.get("selected_option_id")
        if not option_id:
            return {"kind": "clarify", "response": "Qual opção você quer?", "reason": "missing_option_id"}

        option = session.presented_option_by_id(option_id) if hasattr(session, "presented_option_by_id") else None
        if not option:
            return _clarify_response(
                session,
                working,
                fallback="Essa opção não existe mais.",
                reason="invalid_option",
            )

        action_payload = option.get("action_payload")
        if action_payload:
            return {"kind": "execute_pending", "action_payload": action_payload, "reason": reason}
        return {"kind": "clarify", "response": "Essa opção não é executável.", "reason": "non_executable"}

    if mode in {"execute_pending", "confirm_pending"}:
        pending = session.pending_action_snapshot() if hasattr(session, "pending_action_snapshot") else None
        if pending:
            return {"kind": "execute_pending", "action_payload": pending, "reason": reason}
        return {"kind": "clarify", "response": "Não há ação pendente.", "reason": "no_pending_action"}

    if mode == "reject_pending":
        if hasattr(session, "clear_pending_action"):
            session.clear_pending_action()
        response = str(working.get("clarifying_question") or "Entendido, não vou seguir com a ação sugerida.").strip()
        return {"kind": "reject_pending", "response": response, "reason": reason}

    if mode in {"advise", "ask_advice"}:
        guidance = session.guidance_response_for("") if hasattr(session, "guidance_response_for") else ""
        return {"kind": "advise", "response": guidance, "reason": reason}

    if mode == "register_goal":
        goal = str(working.get("goal") or user_text).strip()
        mentioned_unit = _mentioned_available_unit(session, goal) if goal else None
        if mentioned_unit:
            validated = validate_action_payload(
                session,
                {"action": "analyze_unit", "unit_name": mentioned_unit},
            )
            if validated:
                return {
                    "kind": "execute_pending",
                    "action_payload": validated,
                    "reason": reason or "register_goal_unit_reference",
                }
        if goal and hasattr(session, "user_goal"):
            session.user_goal = goal
            if hasattr(session, "_reorder_fallback_options_for_goal"):
                session._reorder_fallback_options_for_goal()
        clarifying = str(working.get("clarifying_question") or "").strip()
        if clarifying:
            response = clarifying
        elif goal:
            response = (
                f"Entendido. Registrei seu objetivo: \"{goal}\". "
                "Diga qual tabela ou análise quer executar para avançar."
            )
        else:
            response = "Qual é o seu objetivo com esta análise?"
        return {"kind": "clarify", "response": response, "reason": reason or "register_goal"}

    if mode == "conversation_only":
        return _clarify_response(
            session,
            working,
            fallback="Pode reformular sua pergunta?",
            reason=reason or "conversation_only",
            kind="conversation_only",
        )

    return _clarify_response(
        session,
        working,
        fallback="Pode reformular sua pergunta?",
        reason=reason or "unrecognized_mode",
    )
