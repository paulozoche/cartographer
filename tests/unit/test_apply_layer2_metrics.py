from __future__ import annotations

from agnostic.domain.analysis.apply_layer2_metrics import apply_layer2_metrics
from agnostic.domain.models.tabular import StandardizedTabularUnit


def test_apply_layer2_metrics_returns_all_metrics_per_column() -> None:
    unit = StandardizedTabularUnit(
        unit_name="events",
        columns={
            "mixed": ("ABC", "123", "A B", "Abc"),
        },
        row_count=4,
        column_count=1,
        column_order=("mixed",),
    )

    result = apply_layer2_metrics(unit)

    assert set(result.keys()) == {"mixed"}
    assert set(result["mixed"].keys()) == {
        "numeric_ratio",
        "alpha_ratio",
        "spaces_ratio",
        "uppercase_ratio",
    }
