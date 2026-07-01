"""Backward-compatible re-exports for focus state helpers."""

from agnostic.session.focus import (
    FocusState,
    ensure_focus_state,
    get_session_active_focus,
    get_session_focus_state,
    set_session_active_focus,
)

__all__ = [
    "FocusState",
    "ensure_focus_state",
    "get_session_active_focus",
    "get_session_focus_state",
    "set_session_active_focus",
]
