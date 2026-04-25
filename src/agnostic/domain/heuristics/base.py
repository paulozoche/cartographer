from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HeuristicResult:
    name: str
    triggered: bool
    score: float
    evidence: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


class ColumnHeuristic(Protocol):
    name: str

    def __call__(self, column_metrics: dict[str, object]) -> HeuristicResult: ...
