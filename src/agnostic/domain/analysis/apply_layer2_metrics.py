from __future__ import annotations

from agnostic.domain.metrics.layer2 import LAYER2_METRICS
from agnostic.domain.models.tabular import StandardizedTabularUnit


def apply_layer2_metrics(unit: StandardizedTabularUnit) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}

    for column_name, column_values in unit.columns.items():
        column_metrics: dict[str, float] = {}
        for metric_name, metric_func in LAYER2_METRICS.items():
            column_metrics[metric_name] = metric_func(column_values)
        results[column_name] = column_metrics

    return results
