from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agnostic.domain.metrics.numeric_stats import (
    numeric_max,
    numeric_mean,
    numeric_median,
    numeric_min,
    numeric_quartiles,
    numeric_std_dev,
)


NUMERIC_STATS_METRICS = {
    "numeric_min": numeric_min,
    "numeric_max": numeric_max,
    "numeric_mean": numeric_mean,
    "numeric_median": numeric_median,
    "numeric_std_dev": numeric_std_dev,
    "numeric_quartiles": numeric_quartiles,
}

_NUMERIC_STATS_SURFACE_KEYS = {
    "numeric_min": "min",
    "numeric_max": "max",
    "numeric_mean": "mean",
    "numeric_median": "median",
    "numeric_std_dev": "std_dev",
    "numeric_quartiles": "quartiles",
}


def build_numeric_stats_surface(column_data: Iterable[Any]) -> dict[str, object]:
    surface: dict[str, object] = {}
    for metric_name, metric_func in NUMERIC_STATS_METRICS.items():
        surface_key = _NUMERIC_STATS_SURFACE_KEYS[metric_name]
        surface[surface_key] = metric_func(column_data)
    return surface
