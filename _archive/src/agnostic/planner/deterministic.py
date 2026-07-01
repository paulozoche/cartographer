"""Deterministic action planning facade."""

from __future__ import annotations

import re

from agnostic.application.planning.rule_based_planner import (
    plan_deterministic_action as _base_plan_deterministic_action,
)
from agnostic.planner.explicit import (
    _natural_language_option_choice,
    _resolve_explicit_user_action,
    _robust_normalize,
)


def plan_deterministic_action(session_or_context, user_text: str, **kwargs):
    normalized = _robust_normalize(user_text)
    explicit_action = _resolve_explicit_user_action(session_or_context, user_text)
    if explicit_action is not None:
        return explicit_action
    if re.fullmatch(r"\d+", normalized):
        option_choice = _natural_language_option_choice(session_or_context, user_text)
        if option_choice is not None:
            return option_choice
    return _base_plan_deterministic_action(session_or_context, user_text, **kwargs)
