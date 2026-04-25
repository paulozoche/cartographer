from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult


def pattern_signal(column_metrics: dict[str, object]) -> HeuristicResult:
    pattern_metric = column_metrics.get("has_pattern", {}) or {}

    matched_pattern = pattern_metric.get("matched_pattern")
    match_ratio = float(pattern_metric.get("match_ratio", 0.0) or 0.0)
    fixed_length = bool(pattern_metric.get("fixed_length", False))
    fixed_length_value = pattern_metric.get("fixed_length_value")

    score = match_ratio
    if fixed_length and match_ratio > 0.0:
        score = min(1.0, score + 0.1)

    triggered = matched_pattern is not None and match_ratio >= 0.7

    return HeuristicResult(
        name="pattern_signal",
        triggered=triggered,
        score=min(max(score, 0.0), 1.0),
        evidence={
            "matched_pattern": matched_pattern,
            "match_ratio": match_ratio,
            "fixed_length": fixed_length,
            "fixed_length_value": fixed_length_value,
        },
        metadata={
            "thresholds": {
                "match_ratio_min": 0.7,
            }
        },
    )
