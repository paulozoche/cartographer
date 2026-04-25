from __future__ import annotations

from dataclasses import dataclass

from agnostic.application.ports.tabular_source import TabularUnit
from agnostic.domain.analysis.apply_layer1_metrics import apply_layer1_metrics
from agnostic.domain.analysis.apply_layer2_metrics import apply_layer2_metrics
from agnostic.domain.analysis.build_column_explanation import build_column_explanation
from agnostic.domain.analysis.build_ranked_unit import build_ranked_unit
from agnostic.domain.analysis.build_column_suggestions import build_column_suggestions
from agnostic.domain.analysis.build_table_ranking import (
    build_table_explanation,
    build_table_signal,
    build_table_suggested_actions,
)
from agnostic.domain.analysis.compute_exploration_score import compute_exploration_score
from agnostic.domain.analysis.compute_consistency_score import compute_consistency_score
from agnostic.domain.analysis.compute_column_signal import (
    compute_signal,
    infer_signatures_from_metrics,
)
from agnostic.domain.analysis.standardize import standardize_tabular_unit
from agnostic.domain.heuristics.apply import apply_column_heuristics
from agnostic.domain.heuristics.base import HeuristicResult
from agnostic.domain.models.tabular import (
    StandardizedTabularUnit,
    UnitMetadata,
    UnitStructure,
)


@dataclass(frozen=True, slots=True)
class ColumnAnalysis:
    type: str
    name: str
    column_name: str
    signal: float
    exploration_score: float
    consistency_score: float
    explanation: str
    suggested_actions: tuple[str, ...]
    layer1_metrics: dict[str, object]
    layer2_metrics: dict[str, float]
    heuristics: tuple[HeuristicResult, ...]


@dataclass(frozen=True, slots=True)
class TabularUnitAnalysis:
    type: str
    name: str
    unit_name: str
    signal: float
    explanation: str
    suggested_actions: tuple[str, ...]
    metadata: UnitMetadata
    structure: UnitStructure
    standardized: StandardizedTabularUnit
    columns: dict[str, ColumnAnalysis]
    ranked_units: tuple[dict[str, object], ...]


def analyze_tabular_unit(
    unit: TabularUnit,
    *,
    max_rows: int | None = None,
) -> TabularUnitAnalysis:
    metadata = unit.get_metadata()
    structure = unit.get_structure()
    standardized = standardize_tabular_unit(
        unit_name=unit.unit_name,
        structure=structure,
        rows=unit.get_rows(),
        max_rows=max_rows,
    )

    layer1_metrics = apply_layer1_metrics(standardized)
    layer2_metrics = apply_layer2_metrics(standardized)

    raw_columns: dict[str, ColumnAnalysis] = {}
    for column_name in standardized.column_order:
        combined_metrics = {
            **layer1_metrics[column_name],
            **layer2_metrics[column_name],
        }
        heuristics = tuple(apply_column_heuristics(combined_metrics))
        signatures = infer_signatures_from_metrics(
            heuristics=list(heuristics),
            column_metrics=combined_metrics,
        )
        raw_columns[column_name] = ColumnAnalysis(
            type="column",
            name=column_name,
            column_name=column_name,
            signal=compute_signal(list(heuristics), signatures),
            exploration_score=compute_exploration_score(combined_metrics),
            consistency_score=compute_consistency_score(list(heuristics)),
            explanation=build_column_explanation(list(heuristics)),
            suggested_actions=tuple(build_column_suggestions(list(heuristics))),
            layer1_metrics=layer1_metrics[column_name],
            layer2_metrics=layer2_metrics[column_name],
            heuristics=heuristics,
        )

    ordered_columns = sorted(
        raw_columns.values(),
        key=lambda column: (column.signal, column.exploration_score, column.consistency_score),
        reverse=True,
    )
    columns: dict[str, ColumnAnalysis] = {
        column.column_name: column
        for column in ordered_columns
    }
    ranked_units = tuple(
        build_ranked_unit(
            unit_type=column.type,
            name=column.name,
            signal=column.signal,
            explanation=column.explanation,
            suggested_actions=list(column.suggested_actions),
        )
        for column in ordered_columns
    )
    table_signal = build_table_signal(columns)
    table_explanation = build_table_explanation(columns)
    table_suggested_actions = tuple(build_table_suggested_actions(columns))

    return TabularUnitAnalysis(
        type="table",
        name=unit.unit_name,
        unit_name=unit.unit_name,
        signal=table_signal,
        explanation=table_explanation,
        suggested_actions=table_suggested_actions,
        metadata=metadata,
        structure=structure,
        standardized=standardized,
        columns=columns,
        ranked_units=ranked_units,
    )
