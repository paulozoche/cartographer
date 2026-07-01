"""Structured user intent produced by the Interface LLM translator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class Intent:
    mode: Literal[
        "register_goal",
        "execute_action",
        "select_option",
        "confirm_pending",
        "reject_pending",
        "ask_advice",
        "clarify",
        "conversation_only",
    ]
    confidence: Literal["high", "medium", "low"]
    action_payload: Optional[dict] = None
    selected_option_id: Optional[str] = None
    clarifying_question: Optional[str] = None
    user_intent_summary: str = ""
    reason: str = ""
