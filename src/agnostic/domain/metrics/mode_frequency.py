from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agnostic.domain.models.tabular import ModeFrequencyMetricResult


def mode_frequency(column_data: Iterable[Any]) -> ModeFrequencyMetricResult:
    non_null = tuple(value for value in column_data if value is not None)

    if not non_null:
        return ModeFrequencyMetricResult(value=None, count=0, ratio=0.0)

    counts: dict[Any, int] = {}
    for value in non_null:
        counts[value] = counts.get(value, 0) + 1

    value, count = max(counts.items(), key=lambda item: item[1])
    return ModeFrequencyMetricResult(
        value=value,
        count=count,
        ratio=count / len(non_null),
    )
