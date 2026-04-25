from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult


def identifier_signal(column_metrics: dict[str, object]) -> HeuristicResult:
    unique_ratio = float(column_metrics.get("unique_ratio", 0.0) or 0.0)
    null_ratio = float(column_metrics.get("null_ratio", 0.0) or 0.0)
    average_length = float(column_metrics.get("average_length", 0.0) or 0.0)
    numeric_ratio = float(column_metrics.get("numeric_ratio", 0.0) or 0.0)

    uniqueness_component = unique_ratio
    completeness_component = max(0.0, 1.0 - null_ratio)
    compactness_component = 1.0 if average_length == 0.0 or average_length <= 30.0 else 0.0
    numeric_component = numeric_ratio

    score = (
        (0.45 * uniqueness_component)
        + (0.25 * completeness_component)
        + (0.20 * compactness_component)
        + (0.10 * numeric_component)
    )
    triggered = unique_ratio >= 0.95 and null_ratio <= 0.05 and compactness_component == 1.0

    return HeuristicResult(
        name="identifier_signal",
        triggered=triggered,
        score=min(max(score, 0.0), 1.0),
        evidence={
            "unique_ratio": unique_ratio,
            "null_ratio": null_ratio,
            "average_length": average_length,
            "numeric_ratio": numeric_ratio,
        },
        metadata={
            "thresholds": {
                "unique_ratio": 0.95,
                "null_ratio_max": 0.05,
                "average_length_max": 30.0,
            }
        },
    )
