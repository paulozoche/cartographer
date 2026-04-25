from __future__ import annotations

from typing import Any

from agnostic.domain.heuristics.base import HeuristicResult


def high_cardinality_signal(column_metrics: dict[str, object]) -> HeuristicResult:
    cardinality = int(column_metrics.get("cardinality", 0) or 0)
    unique_ratio = float(column_metrics.get("unique_ratio", 0.0) or 0.0)
    average_length = float(column_metrics.get("average_length", 0.0) or 0.0)

    score = unique_ratio
    short_value_bias = average_length < 30.0 if average_length > 0 else True
    triggered = unique_ratio >= 0.9 and short_value_bias

    return HeuristicResult(
        name="high_cardinality_signal",
        triggered=triggered,
        score=min(max(score, 0.0), 1.0),
        evidence={
            "cardinality": cardinality,
            "unique_ratio": unique_ratio,
            "average_length": average_length,
            "short_value_bias": short_value_bias,
        },
        metadata={
            "thresholds": {
                "unique_ratio": 0.9,
                "average_length_max": 30.0,
            }
        },
    )
