from agnostic.domain.analysis.compute_exploration_score import compute_exploration_score
from agnostic.domain.models.tabular import ModeFrequencyMetricResult


def test_compute_exploration_score_penalizes_quasi_unique_columns() -> None:
    quasi_unique = compute_exploration_score(
        {
            "unique_ratio": 0.995,
            "cardinality": 995,
            "frequency": {"x": 1, "y": 1, "z": 1},
            "mode_frequency": ModeFrequencyMetricResult(value="x", count=1, ratio=0.001),
        }
    )
    medium_repetition = compute_exploration_score(
        {
            "unique_ratio": 0.50,
            "cardinality": 50,
            "frequency": {"A": 40, "B": 30, "C": 30},
            "mode_frequency": ModeFrequencyMetricResult(value="A", count=40, ratio=0.40),
        }
    )

    assert quasi_unique < medium_repetition


def test_compute_exploration_score_stays_in_bounds() -> None:
    score = compute_exploration_score(
        {
            "unique_ratio": 0.2,
            "cardinality": 20,
            "frequency": {"A": 80, "B": 20},
            "mode_frequency": ModeFrequencyMetricResult(value="A", count=80, ratio=0.8),
        }
    )
    assert 0.0 <= score <= 1.0
