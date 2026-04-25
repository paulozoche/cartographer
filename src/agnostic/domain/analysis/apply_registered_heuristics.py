from __future__ import annotations

from agnostic.domain.analysis.apply_layer1_metrics import apply_layer1_metrics
from agnostic.domain.analysis.apply_layer2_metrics import apply_layer2_metrics
from agnostic.domain.analysis.build_column_explanation import build_column_explanation
from agnostic.domain.analysis.build_column_suggestions import build_column_suggestions
from agnostic.domain.analysis.compute_consistency_score import compute_consistency_score
from agnostic.domain.analysis.compute_exploration_score import compute_exploration_score
from agnostic.domain.analysis.compute_column_signal import (
    compute_signal,
    infer_signatures_from_metrics,
)
from agnostic.domain.heuristics.apply import apply_column_heuristics
from agnostic.domain.heuristics.base import HeuristicResult
from agnostic.domain.models.tabular import StandardizedTabularUnit


def apply_registered_heuristics(unit: StandardizedTabularUnit) -> dict[str, dict[str, object]]:
    layer1_metrics = apply_layer1_metrics(unit)
    layer2_metrics = apply_layer2_metrics(unit)

    results: dict[str, dict[str, object]] = {}
    for column_name in unit.column_order:
        combined_metrics = {
            **layer1_metrics[column_name],
            **layer2_metrics[column_name],
        }
        heuristics = apply_column_heuristics(combined_metrics)
        typed_heuristics = [heuristic for heuristic in heuristics if isinstance(heuristic, HeuristicResult)]
        signatures = infer_signatures_from_metrics(
            heuristics=typed_heuristics,
            column_metrics=combined_metrics,
        )
        results[column_name] = {
            "type": "column",
            "name": column_name,
            "signal": compute_signal(typed_heuristics, signatures),
            "exploration_score": compute_exploration_score(combined_metrics),
            "consistency_score": compute_consistency_score(typed_heuristics),
            "explanation": build_column_explanation(typed_heuristics),
            "suggested_actions": build_column_suggestions(typed_heuristics),
            "heuristics": typed_heuristics,
        }
    return dict(
        sorted(
            results.items(),
            key=lambda item: (
                float((item[1] or {}).get("signal") or 0.0),
                float((item[1] or {}).get("exploration_score") or 0.0),
                float((item[1] or {}).get("consistency_score") or 0.0),
            ),
            reverse=True,
        )
    )
