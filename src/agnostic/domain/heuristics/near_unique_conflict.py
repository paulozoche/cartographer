from __future__ import annotations

import math
from typing import Any

from agnostic.domain.heuristics.base import HeuristicResult


def near_unique_conflict(column_metrics: dict[str, object]) -> HeuristicResult:
    unique_ratio = float(column_metrics.get("unique_ratio", 0.0) or 0.0)
    distinct_values = float(column_metrics.get("cardinality", 0.0) or 0.0)
    mode_metric = column_metrics.get("mode_frequency")

    mode_count = _extract_mode_count(mode_metric)
    total_rows = _estimate_total_rows(distinct_values=distinct_values, unique_ratio=unique_ratio)
    collision_count = max(0.0, total_rows - distinct_values)
    collision_ratio = (collision_count / total_rows) if total_rows > 0.0 else 0.0
    mode_ratio = (mode_count / total_rows) if total_rows > 0.0 else 0.0

    triggered = (
        unique_ratio > 0.98
        and collision_count > 0.0
        and collision_ratio < 0.02
        and mode_ratio < 0.1
    )
    consistency_score = (1.0 - collision_ratio) * math.log(max(total_rows, 1.0))

    return HeuristicResult(
        name="near_unique_conflict",
        triggered=triggered,
        score=max(consistency_score, 0.0),
        evidence={
            "total_rows": total_rows,
            "distinct_values": distinct_values,
            "collision_count": collision_count,
            "collision_ratio": collision_ratio,
            "mode_ratio": mode_ratio,
            "unique_ratio": unique_ratio,
        },
        metadata={},
    )


def _estimate_total_rows(*, distinct_values: float, unique_ratio: float) -> float:
    if distinct_values <= 0.0:
        return 0.0
    if unique_ratio <= 0.0:
        return distinct_values
    return distinct_values / unique_ratio


def _extract_mode_count(mode_metric: Any) -> float:
    if isinstance(mode_metric, dict):
        return float(mode_metric.get("count", 0.0) or 0.0)
    return float(getattr(mode_metric, "count", 0.0) or 0.0)
