"""Turn decision orchestration for the Planner."""

from __future__ import annotations

import logging

from agnostic.planner.explicit import _resolve_explicit_user_action

logger = logging.getLogger(__name__)


def decide_interface_turn(session, user_text: str) -> dict[str, object]:
    if hasattr(session, "record_user_turn"):
        session.record_user_turn(user_text)
    elif hasattr(session, "history"):
        session.history.append({"role": "user", "content": user_text})

    explicit_action = _resolve_explicit_user_action(session, user_text)
    if isinstance(explicit_action, dict) and str(explicit_action.get("action", "")).strip():
        if hasattr(session, "clear_pending_action"):
            session.clear_pending_action()
        return {"kind": "execute_pending", "action_payload": dict(explicit_action)}

    option_resolution = (
        session.resolve_presented_option_reference(user_text)
        if hasattr(session, "resolve_presented_option_reference")
        else None
    )
    if not isinstance(option_resolution, dict):
        selected_option = session.option_for_user_choice(user_text) if hasattr(session, "option_for_user_choice") else None
        option_resolution = (
            {"status": "matched", "option": selected_option}
            if isinstance(selected_option, dict)
            else {"status": "no_match"}
        )
    selected_option = option_resolution.get("option") if isinstance(option_resolution, dict) else None

    if option_resolution.get("status") == "ambiguous":
        response = (
            session.clarification_response_for(user_text)
            if hasattr(session, "clarification_response_for")
            else "Encontrei mais de uma opção possível nessa referência. Escolha pelo número da opção ou repita o rótulo com mais precisão."
        )
        return {"kind": "clarify", "response": response}

    if option_resolution.get("status") == "no_active_options":
        response = (
            session.clarification_response_for(user_text)
            if hasattr(session, "clarification_response_for")
            else "Ainda não tenho uma lista ativa de opções para interpretar essa referência. Diga qual tabela ou análise você quer explorar."
        )
        return {"kind": "clarify", "response": response}

    if option_resolution.get("status") == "invalid_index":
        response = (
            session.clarification_response_for(user_text)
            if hasattr(session, "clarification_response_for")
            else "A opção pedida não existe. Escolha uma opção válida pelo número."
        )
        return {"kind": "clarify", "response": response}

    if isinstance(selected_option, dict):
        if str(selected_option.get("kind", "")) == "executable" and isinstance(selected_option.get("action_payload"), dict):
            return {"kind": "execute_pending", "action_payload": dict(selected_option["action_payload"])}
        response = (
            session.clarification_response_for(user_text)
            if hasattr(session, "clarification_response_for")
            else "Esse caminho ainda é apenas orientação. Se quiser, eu explico melhor ou você pode escolher uma opção executável."
        )
        return {"kind": "clarify", "response": response}

    if hasattr(session, "interpret_user_reply_with_interface_context") and hasattr(session, "interface_ai"):
        interpreted = session.interpret_user_reply_with_interface_context(user_text)
        if isinstance(interpreted, dict):
            kind = str(interpreted.get("kind", "")).strip()
            if kind == "execute_pending":
                action_payload = interpreted.get("action_payload")
                if isinstance(action_payload, dict):
                    return {"kind": "execute_pending", "action_payload": dict(action_payload)}
            if kind == "reject_pending":
                if hasattr(session, "clear_pending_action"):
                    session.clear_pending_action()
                response = str(interpreted.get("response", "")).strip()
                if not response and hasattr(session, "_build_structured_choice_message"):
                    response = session._build_structured_choice_message(
                        "Entendido, não vou seguir com a ação sugerida.",
                        "Escolha uma opção pelo número ou peça outro caminho.",
                    )
                return {"kind": "clarify", "response": response}
            if kind in {"clarify", "advise", "conversation_only"}:
                return {
                    "kind": "clarify" if kind == "conversation_only" else kind,
                    "response": str(interpreted.get("response", "")).strip(),
                }

    result = {"kind": "execute"}
    logger.info("decide_interface_turn result: kind=%s", result.get("kind"))
    return result
