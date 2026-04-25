from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from agnostic.domain.models.tabular import FrequencyMetricResult, MetricExecutionPolicy


def frequency(
    column_data: Iterable[Any],
    policy: MetricExecutionPolicy | None = None,
) -> FrequencyMetricResult:
    values = tuple(column_data)
    total_size = len(values)

    if total_size == 0:
        return FrequencyMetricResult(
            counts={},
            sampled=False,
            sample_size=0,
            total_size=0,
            coverage_ratio=0.0,
            sampling_strategy=None,
        )

    policy = policy or MetricExecutionPolicy()
    sampled_values, sampled, sampling_strategy = _apply_policy(values, policy)
    filtered_values = [value for value in sampled_values if value is not None]

    return FrequencyMetricResult(
        counts=dict(Counter(filtered_values)),
        sampled=sampled,
        sample_size=len(sampled_values),
        total_size=total_size,
        coverage_ratio=len(sampled_values) / total_size,
        sampling_strategy=sampling_strategy,
    )


def _apply_policy(
    values: tuple[Any, ...],
    policy: MetricExecutionPolicy,
) -> tuple[tuple[Any, ...], bool, str | None]:
    if policy.mode == "full":
        return values, False, None

    if policy.mode != "sampled":
        raise ValueError(f"Unsupported metric execution mode: {policy.mode}")

    if policy.sampling_strategy != "deterministic_head":
        raise ValueError(
            f"Unsupported sampling strategy: {policy.sampling_strategy}"
        )

    if policy.sample_size is None or policy.sample_size <= 0:
        raise ValueError("sample_size must be a positive integer in sampled mode")

    if policy.sample_size >= len(values):
        return values, False, policy.sampling_strategy

    return values[: policy.sample_size], True, policy.sampling_strategy
