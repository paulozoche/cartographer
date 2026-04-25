from agnostic.domain.analysis.compute_consistency_score import compute_consistency_score
from agnostic.domain.heuristics.base import HeuristicResult


def test_compute_consistency_score_uses_only_triggered_near_unique_conflict() -> None:
    heuristics = [
        HeuristicResult(name="near_unique_conflict", triggered=True, score=6.9),
        HeuristicResult(name="near_unique_conflict", triggered=False, score=9.0),
        HeuristicResult(name="identifier_signal", triggered=True, score=1.0),
    ]

    assert compute_consistency_score(heuristics) == 6.9
