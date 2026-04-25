from __future__ import annotations

from collections.abc import Iterable

from agnostic.domain.heuristics.base import HeuristicResult


def compute_signal(heuristics: list[HeuristicResult], signatures: Iterable[str]) -> float:
    relevant_heuristics = {
        "identifier_signal",
        "high_cardinality_signal",
        "pattern_signal",
        "sequential_signal",
    }
    relevance_score = sum(
        float(h.score)
        for h in heuristics
        if h.triggered and h.name in relevant_heuristics
    )
    relevance_score = min(relevance_score, 1.0)

    signatures_set = {str(item).strip() for item in signatures if str(item).strip()}
    consistency_factor = 1.0
    if "near_unique_escape" in signatures_set:
        consistency_factor *= 0.8
    if "mixed_representation" in signatures_set:
        consistency_factor *= 0.85
    if "sparse_field" in signatures_set:
        consistency_factor *= 0.7
    if "format_escape" in signatures_set:
        consistency_factor *= 0.9

    signal = relevance_score * consistency_factor
    return max(0.0, min(signal, 1.0))


def infer_signatures_from_metrics(
    *,
    heuristics: list[HeuristicResult],
    column_metrics: dict[str, object],
) -> set[str]:
    signatures: set[str] = set()

    triggered = {h.name for h in heuristics if h.triggered}
    if "near_unique_conflict" in triggered:
        signatures.add("near_unique_escape")

    null_ratio = float(column_metrics.get("null_ratio", 0.0) or 0.0)
    empty_string_ratio = float(column_metrics.get("empty_string_ratio", 0.0) or 0.0)
    numeric_ratio = float(column_metrics.get("numeric_ratio", 0.0) or 0.0)
    alpha_ratio = float(column_metrics.get("alpha_ratio", 0.0) or 0.0)

    if null_ratio > 0.8 or empty_string_ratio > 0.8:
        signatures.add("sparse_field")

    if max(numeric_ratio, alpha_ratio) < 0.8 and min(numeric_ratio, alpha_ratio) > 0.1:
        signatures.add("mixed_representation")

    if "pattern_signal" in triggered:
        pattern_metric = column_metrics.get("has_pattern", {}) or {}
        if isinstance(pattern_metric, dict):
            match_ratio = float(pattern_metric.get("match_ratio", 0.0) or 0.0)
            if match_ratio >= 0.7 and match_ratio < 1.0:
                signatures.add("format_escape")

    return signatures


def compute_column_signal(
    heuristics_results: list[HeuristicResult],
    signatures: Iterable[str] = (),
) -> float:
    return compute_signal(heuristics_results, signatures)
