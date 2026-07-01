from __future__ import annotations

from typing import Literal

from agnostic.interface.interpreter import interpret_user_reply_with_interface_context as _interpret_user_reply
from agnostic.interface.llm import DeepSeekClient
from agnostic.interface.presenter import interface_reply as _interface_reply
from agnostic.planner.intent import Intent

DEFAULT_INTERFACE_MODEL = "deepseek-chat"


def _decision_to_intent(decision: dict[str, object]) -> Intent:
    kind = str(decision.get("kind", "clarify"))
    kind_to_mode: dict[str, Literal[
        "execute_action",
        "select_option",
        "confirm_pending",
        "reject_pending",
        "ask_advice",
        "clarify",
        "conversation_only",
    ]] = {
        "execute_pending": "execute_action",
        "clarify": "clarify",
        "reject_pending": "reject_pending",
        "advise": "ask_advice",
        "conversation_only": "conversation_only",
    }
    mode = kind_to_mode.get(kind, "clarify")
    action_payload = decision.get("action_payload")
    return Intent(
        mode=mode,
        confidence="high" if kind == "execute_pending" else "medium" if kind == "advise" else "low",
        action_payload=dict(action_payload) if isinstance(action_payload, dict) else None,
        selected_option_id=str(decision.get("selected_option_id")) if decision.get("selected_option_id") else None,
        clarifying_question=str(decision.get("response")) if kind in {"clarify", "conversation_only"} else None,
        user_intent_summary=str(decision.get("user_intent_summary", "")),
        reason=str(decision.get("reason", "")),
    )


class Interface:
    def __init__(self, api_key: str, model: str = DEFAULT_INTERFACE_MODEL) -> None:
        self._llm = DeepSeekClient(api_key=api_key, model=model)

    @property
    def llm(self) -> DeepSeekClient:
        return self._llm

    def interpret(self, user_text: str, state) -> Intent:
        decision = _interpret_user_reply(state, user_text, llm=self._llm)
        return _decision_to_intent(decision)

    def present(
        self,
        user_text: str,
        state,
        result_context: str,
        *,
        is_first_call: bool = False,
    ) -> str:
        return _interface_reply(
            state,
            user_text,
            result_context=result_context,
            is_first_call=is_first_call,
            llm=self._llm,
        )
