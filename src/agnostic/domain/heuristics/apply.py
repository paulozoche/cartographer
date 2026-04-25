from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult
from agnostic.domain.heuristics.registry import COLUMN_HEURISTICS


def apply_column_heuristics(column_metrics: dict[str, object]) -> list[HeuristicResult]:
    return [
        heuristic(column_metrics)
        for heuristic in COLUMN_HEURISTICS.values()
    ]
