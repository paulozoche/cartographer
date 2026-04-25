from __future__ import annotations

from agnostic.domain.analysis.standardize import standardize_tabular_unit
from agnostic.domain.models.tabular import ColumnStructure, UnitStructure


def _structure() -> UnitStructure:
    return UnitStructure(
        unit_name="events",
        columns=(
            ColumnStructure(name="event_id", position=0),
            ColumnStructure(name="category", position=1),
        ),
    )


def test_standardize_tabular_unit_preserves_column_order_and_values() -> None:
    standardized = standardize_tabular_unit(
        unit_name="events",
        structure=_structure(),
        rows=[
            (1, "A"),
            (2, "B"),
        ],
    )

    assert standardized.unit_name == "events"
    assert standardized.row_count == 2
    assert standardized.column_count == 2
    assert standardized.column_order == ("event_id", "category")
    assert standardized.columns["event_id"] == (1, 2)
    assert standardized.columns["category"] == ("A", "B")


def test_standardize_tabular_unit_preserves_none_values() -> None:
    standardized = standardize_tabular_unit(
        unit_name="events",
        structure=_structure(),
        rows=[
            (1, None),
            (None, "B"),
        ],
    )

    assert standardized.columns["event_id"] == (1, None)
    assert standardized.columns["category"] == (None, "B")


def test_standardize_tabular_unit_rejects_width_mismatch() -> None:
    try:
        standardize_tabular_unit(
            unit_name="events",
            structure=_structure(),
            rows=[
                (1, "A"),
                (2,),
            ],
        )
    except ValueError as exc:
        assert "Inconsistência na unidade 'events'" in str(exc)
    else:
        raise AssertionError("Expected ValueError for row width mismatch.")
