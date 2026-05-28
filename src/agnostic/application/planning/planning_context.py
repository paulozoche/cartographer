from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PlanningContext:
    pending_requirements: list[dict[str, object]] = field(default_factory=list)
    active_focus: dict[str, object] | None = None
    available_units: list[str] = field(default_factory=list)
    recent_nodes: list[dict[str, object]] = field(default_factory=list)
    last_presented_options: list[dict[str, object]] = field(default_factory=list)
    known_entities: list[dict[str, str]] = field(default_factory=list)
    execution_log: list[dict[str, object]] = field(default_factory=list)
    unit_columns: dict[str, list[str]] = field(default_factory=dict)
    text_columns_by_unit: dict[str, list[str]] = field(default_factory=dict)
    categorical_columns_by_unit: dict[str, list[str]] = field(default_factory=dict)
    select_clause_builder: Callable[[str, str], str] | None = None
    raw_session: Any | None = None
