from agnostic.domain.analysis.build_column_explanation import build_column_explanation
from agnostic.domain.heuristics.base import HeuristicResult


def test_build_column_explanation_uses_only_triggered_heuristics() -> None:
    heuristics = [
        HeuristicResult(name="identifier_signal", triggered=True, score=0.8),
        HeuristicResult(name="high_cardinality_signal", triggered=True, score=0.7),
        HeuristicResult(name="pattern_signal", triggered=False, score=0.9),
    ]

    explanation = build_column_explanation(heuristics)

    assert explanation == "Identificador provável + Alta cardinalidade"


def test_build_column_explanation_includes_near_unique_conflict_label() -> None:
    heuristics = [
        HeuristicResult(name="near_unique_conflict", triggered=True, score=1.0),
    ]
    assert build_column_explanation(heuristics) == "quase único com pequena inconsistência estrutural"
