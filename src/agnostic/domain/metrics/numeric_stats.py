from __future__ import annotations

import statistics
from collections.abc import Iterable
from typing import Any


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def _numeric_values(column_data: Iterable[Any]) -> list[float]:
    values: list[float] = []
    for value in column_data:
        if value is None:
            continue
        converted = _to_float(value)
        if converted is not None:
            values.append(converted)
    return values


def numeric_min(column_data: Iterable[Any]) -> float | None:
    values = _numeric_values(column_data)
    if not values:
        return None
    return min(values)


def numeric_max(column_data: Iterable[Any]) -> float | None:
    values = _numeric_values(column_data)
    if not values:
        return None
    return max(values)


def numeric_mean(column_data: Iterable[Any]) -> float | None:
    values = _numeric_values(column_data)
    if not values:
        return None
    return statistics.fmean(values)


def numeric_median(column_data: Iterable[Any]) -> float | None:
    values = _numeric_values(column_data)
    if not values:
        return None
    return statistics.median(values)


def numeric_std_dev(column_data: Iterable[Any]) -> float | None:
    values = _numeric_values(column_data)
    if len(values) < 2:
        return None
    return statistics.pstdev(values)


def numeric_quartiles(column_data: Iterable[Any]) -> dict[str, float] | None:
    values = _numeric_values(column_data)
    if len(values) < 2:
        return None
    try:
        q1, q2, q3 = statistics.quantiles(values, n=4)
    except statistics.StatisticsError:
        return None
    return {"q1": q1, "q2": q2, "q3": q3}
