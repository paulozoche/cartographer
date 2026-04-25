from __future__ import annotations

from agnostic.domain.metrics.layer1 import LAYER1_METRICS
from agnostic.domain.models.tabular import StandardizedTabularUnit


def apply_layer1_metrics(unit: StandardizedTabularUnit) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}

    for column_name, column_values in unit.columns.items():
        column_metrics: dict[str, object] = {}
        for metric_name, metric_func in LAYER1_METRICS.items():
            column_metrics[metric_name] = metric_func(column_values)
        results[column_name] = column_metrics

    return results
