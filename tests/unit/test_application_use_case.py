from __future__ import annotations

from collections.abc import Iterator

from agnostic.domain.analysis.analyze_tabular_unit import analyze_tabular_unit
from agnostic.domain.models.tabular import UnitMetadata, UnitStructure, ColumnStructure
from agnostic.presentation.summaries.summarize_tabular_analysis import summarize_unit_metrics


class _MemoryUnit:
    def __init__(self) -> None:
        self._rows = [
            (1, "A"),
            (2, "B"),
            (3, "C"),
            (4, "D"),
        ]

    @property
    def unit_name(self) -> str:
        return "events"

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name="events",
            source_unit_identifier="memory://events",
            row_count=4,
        )

    def get_structure(self) -> UnitStructure:
        return UnitStructure(
            unit_name="events",
            columns=(
                ColumnStructure(name="event_id", position=0, raw_type="INTEGER"),
                ColumnStructure(name="category", position=1, raw_type="TEXT"),
            ),
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        yield from self._rows


def test_analyze_tabular_unit_produces_structured_result() -> None:
    analysis = analyze_tabular_unit(_MemoryUnit())

    assert analysis.unit_name == "events"
    assert analysis.type == "table"
    assert analysis.name == "events"
    assert analysis.signal >= 0.0
    assert isinstance(analysis.explanation, str)
    assert isinstance(analysis.suggested_actions, tuple)
    assert analysis.metadata.row_count == 4
    assert analysis.structure.unit_name == "events"
    assert analysis.standardized.row_count == 4
    assert analysis.standardized.column_order == ("event_id", "category")
    assert set(analysis.columns) == {"event_id", "category"}
    ranked_signals = [column.signal for column in analysis.columns.values()]
    assert ranked_signals == sorted(ranked_signals, reverse=True)
    assert all(0.0 <= column.exploration_score <= 1.0 for column in analysis.columns.values())
    assert all(column.consistency_score >= 0.0 for column in analysis.columns.values())
    ranked_triplets = [
        (column.signal, column.exploration_score, column.consistency_score)
        for column in analysis.columns.values()
    ]
    assert ranked_triplets == sorted(ranked_triplets, reverse=True)
    assert analysis.ranked_units
    assert all(item.get("type") == "column" for item in analysis.ranked_units)
    assert any(
        heuristic.name in {"high_cardinality_signal", "identifier_signal", "sequential_signal"}
        for heuristic in analysis.columns["event_id"].heuristics
    )


class _CorrelatedUnit:
    @property
    def unit_name(self) -> str:
        return "correlated"

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name="correlated",
            source_unit_identifier="memory://correlated",
            row_count=4,
        )

    def get_structure(self) -> UnitStructure:
        return UnitStructure(
            unit_name="correlated",
            columns=(
                ColumnStructure(name="value_a", position=0, raw_type="INTEGER"),
                ColumnStructure(name="value_b", position=1, raw_type="INTEGER"),
            ),
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        yield from (
            (1, 1),
            (2, 2),
            (3, 3),
            (4, 4),
        )


def test_summarize_unit_metrics_detects_potential_colinearity() -> None:
    analysis = analyze_tabular_unit(_CorrelatedUnit())

    lines = summarize_unit_metrics(analysis)

    assert any(line.startswith("Colinearidade potencial:") for line in lines)
    assert any("value_a" in line and "value_b" in line for line in lines)
