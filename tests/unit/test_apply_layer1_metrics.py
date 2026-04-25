from __future__ import annotations

from agnostic.domain.analysis.apply_layer1_metrics import apply_layer1_metrics
from agnostic.domain.models.tabular import StandardizedTabularUnit


def test_apply_layer1_metrics_returns_all_metrics_per_column() -> None:
    unit = StandardizedTabularUnit(
        unit_name="events",
        columns={
            "event_id": (1, 2, 2, None),
            "category": ("A", "", "B", "A"),
        },
        row_count=4,
        column_count=2,
        column_order=("event_id", "category"),
    )

    result = apply_layer1_metrics(unit)

    assert set(result.keys()) == {"event_id", "category"}
    assert set(result["event_id"].keys()) == {
        "cardinality",
        "null_ratio",
        "unique_ratio",
        "frequency",
        "mode_frequency",
        "average_length",
        "length_range",
        "length_variance",
        "empty_string_ratio",
    }
    assert result["event_id"]["cardinality"] == 2
    assert result["event_id"]["null_ratio"] == 0.25
    assert result["category"]["empty_string_ratio"] == 0.25
