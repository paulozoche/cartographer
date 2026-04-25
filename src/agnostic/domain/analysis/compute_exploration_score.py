from __future__ import annotations

from typing import Any


def compute_exploration_score(column_metrics: dict[str, Any]) -> float:
    unique_ratio = float(column_metrics.get("unique_ratio", 0.0) or 0.0)
    cardinality = float(column_metrics.get("cardinality", 0.0) or 0.0)
    frequency = column_metrics.get("frequency") if isinstance(column_metrics.get("frequency"), dict) else {}
    mode_metric = column_metrics.get("mode_frequency")
    mode_ratio = float(getattr(mode_metric, "ratio", 0.0) or 0.0)

    total_count = float(sum(int(value) for value in frequency.values())) if frequency else 0.0
    if total_count <= 0.0:
        total_count = max(cardinality, 1.0)
    cardinality_ratio = max(0.0, min(cardinality / total_count, 1.0))

    # Medium-cardinality columns usually offer better exploration branching than near-constant or near-unique columns.
    medium_cardinality_component = max(0.0, 1.0 - (abs(cardinality_ratio - 0.45) / 0.45))
    repetition_component = max(0.0, min(mode_ratio, 1.0))
    non_unique_component = max(0.0, 1.0 - unique_ratio)

    score = (
        (0.45 * repetition_component)
        + (0.35 * medium_cardinality_component)
        + (0.20 * non_unique_component)
    )

    if unique_ratio > 0.98:
        overflow = min(unique_ratio - 0.98, 0.02) / 0.02
        score *= (1.0 - (0.70 * overflow))

    return max(0.0, min(score, 1.0))
