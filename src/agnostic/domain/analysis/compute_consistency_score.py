from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult


def compute_consistency_score(heuristics_results: list[HeuristicResult]) -> float:
    return sum(
        float(heuristic.score or 0.0)
        for heuristic in heuristics_results
        if heuristic.triggered and heuristic.name == "near_unique_conflict"
    )
