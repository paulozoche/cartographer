from agnostic.domain.analysis.build_column_suggestions import build_column_suggestions
from agnostic.domain.heuristics.base import HeuristicResult


def test_build_column_suggestions_uses_triggered_heuristics_without_duplicates() -> None:
    heuristics = [
        HeuristicResult(name="identifier_signal", triggered=True, score=0.9),
        HeuristicResult(name="identifier_signal", triggered=True, score=0.8),
        HeuristicResult(name="pattern_signal", triggered=True, score=0.7),
        HeuristicResult(name="high_cardinality_signal", triggered=False, score=0.6),
    ]

    suggestions = build_column_suggestions(heuristics)

    assert suggestions == [
        "Investigar registros únicos ou correspondências",
        "Analisar padrões e possíveis formatos",
    ]


def test_build_column_suggestions_includes_near_unique_conflict_action() -> None:
    heuristics = [
        HeuristicResult(name="near_unique_conflict", triggered=True, score=1.0),
    ]
    assert build_column_suggestions(heuristics) == ["invesigar valores duplicados ou inconsistentes"]
