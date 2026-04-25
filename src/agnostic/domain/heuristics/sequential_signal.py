from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult


def sequential_signal(column_metrics: dict[str, object]) -> HeuristicResult:
    is_sequential_metric = column_metrics.get("is_sequential", {}) or {}

    is_strict = bool(is_sequential_metric.get("is_strictly_sequential", False))
    is_monotonic = bool(is_sequential_metric.get("is_monotonic_increasing", False))
    numeric_coverage = float(is_sequential_metric.get("numeric_coverage", 0.0) or 0.0)
    increment = is_sequential_metric.get("increment")

    score = 0.0
    if is_monotonic:
        score += 0.35
    if is_strict:
        score += 0.45
    score += 0.20 * numeric_coverage

    triggered = is_strict and numeric_coverage >= 0.9

    return HeuristicResult(
        name="sequential_signal",
        triggered=triggered,
        score=min(max(score, 0.0), 1.0),
        evidence={
            "is_strictly_sequential": is_strict,
            "is_monotonic_increasing": is_monotonic,
            "numeric_coverage": numeric_coverage,
            "increment": increment,
        },
        metadata={
            "thresholds": {
                "numeric_coverage_min": 0.9,
            }
        },
    )
