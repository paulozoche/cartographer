"""Cartographer Planner — decides which action to execute."""

from __future__ import annotations

from agnostic.planner.context import build_planning_context
from agnostic.planner.deterministic import plan_deterministic_action
from agnostic.planner.explicit import _resolve_explicit_user_action
from agnostic.planner.turn import decide_interface_turn
from agnostic.planner.validation import validate_and_convert_intent, validate_interpreter_execute_action


class Planner:
    """Decision maker — receives state via session, does not execute or converse."""

    def plan_deterministic_action(self, session_or_context, user_text: str, **kwargs):
        return plan_deterministic_action(session_or_context, user_text, **kwargs)

    def build_planning_context(self, session):
        return build_planning_context(session)

    def decide_turn(self, session, user_text: str) -> dict[str, object]:
        return decide_interface_turn(session, user_text)

    def resolve_explicit_action(self, session_or_context, user_text: str) -> dict[str, object] | None:
        return _resolve_explicit_user_action(session_or_context, user_text)

    def validate_interpreter_execute_action(
        self,
        session_or_context,
        action_payload: dict[str, object],
    ) -> dict[str, object] | None:
        return validate_interpreter_execute_action(session_or_context, action_payload)

    def validate_and_convert_intent(self, session, parsed: dict, user_text: str = "") -> dict[str, object]:
        return validate_and_convert_intent(session, parsed, user_text=user_text)
