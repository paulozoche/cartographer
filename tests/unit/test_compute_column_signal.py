from agnostic.domain.analysis.compute_column_signal import compute_column_signal
from agnostic.domain.heuristics.base import HeuristicResult


def test_compute_column_signal_keeps_values_above_one() -> None:
    heuristics = [
        HeuristicResult(name="h1", triggered=True, score=0.8),
        HeuristicResult(name="h2", triggered=True, score=0.6),
        HeuristicResult(name="h3", triggered=False, score=0.9),
    ]

    assert compute_column_signal(heuristics) == 1.4
