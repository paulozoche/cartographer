from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agnostic.application.planning.focus_state import FocusState, ensure_focus_state


@dataclass
class PlanningContext:
    pending_requirements: list[dict[str, object]] = field(default_factory=list)
    focus_state: FocusState = field(default_factory=FocusState)
    available_units: list[str] = field(default_factory=list)
    unit_summaries: list[dict[str, object]] = field(default_factory=list)
    recent_nodes: list[dict[str, object]] = field(default_factory=list)
    last_presented_options: list[dict[str, object]] = field(default_factory=list)
    known_entities: list[dict[str, str]] = field(default_factory=list)
    execution_log: list[dict[str, object]] = field(default_factory=list)
    unit_columns: dict[str, list[str]] = field(default_factory=dict)
    select_clause_builder: Callable[[str, str], str] | None = None
    raw_session: Any | None = None

    def __post_init__(self) -> None:
        self.focus_state = ensure_focus_state(self.focus_state)
