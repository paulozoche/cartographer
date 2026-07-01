"""Focus state for Cartographer sessions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FocusState:
    active_focus: dict[str, object] | None = None


def ensure_focus_state(value: FocusState | dict[str, object] | None) -> FocusState:
    if isinstance(value, FocusState):
        return value
    if isinstance(value, dict):
        return FocusState(active_focus=value)
    return FocusState()


def get_session_focus_state(session: object) -> FocusState:
    session_dict = getattr(session, "__dict__", {})
    focus_state = session_dict.get("_focus_state")
    if isinstance(focus_state, FocusState):
        return focus_state
    focus_state = ensure_focus_state(session_dict.get("_active_focus"))
    setattr(session, "_focus_state", focus_state)
    return focus_state


def get_session_active_focus(session: object) -> dict[str, object] | None:
    return get_session_focus_state(session).active_focus


def set_session_active_focus(session: object, value: dict[str, object] | None) -> None:
    get_session_focus_state(session).active_focus = value
    getattr(session, "__dict__", {})["_active_focus"] = value
