"""Unit tests for tabular_result module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import pytest

from agnostic.application.use_cases.tabular_result import build_tabular_result
from agnostic.core.errors import AnalysisBoundaryViolation
from agnostic.domain.models.tabular import UnitMetadata


@dataclass
class FakeTabularUnit:
    """Fake tabular unit for testing."""
    unit_name: str
    columns: list[str]
    rows: list[list[Any]]

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name=self.unit_name,
            source_unit_identifier=f"fake://{self.unit_name}",
            row_count=len(self.rows),
        )

    def get_structure(self):
        from agnostic.domain.models.tabular import UnitStructure, ColumnStructure
        return UnitStructure(
            unit_name=self.unit_name,
            columns=tuple(
                ColumnStructure(name=col, position=i, raw_type="TEXT")
                for i, col in enumerate(self.columns)
            ),
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        yield from (tuple(row) for row in self.rows)


def simple_parse_columns(text: str) -> list[str]:
    """Simple column parser."""
    return [col.strip() for col in text.split(",") if col.strip()]


def simple_parse_rows(text: str) -> list[list[Any]]:
    """Simple row parser."""
    if not text.strip():
        return []
    return [
        [cell.strip() for cell in row.split("|")]
        for row in text.strip().split("\n")
        if row.strip()
    ]


def test_build_tabular_result_with_valid_data() -> None:
    """build_tabular_result works with valid data."""
    result = build_tabular_result(
        unit_name="test_table",
        columns_text="id, name",
        rows_text="1 | Alice\n2 | Bob",
        parse_columns_fn=simple_parse_columns,
        parse_rows_fn=simple_parse_rows,
        inline_tabular_unit_cls=FakeTabularUnit,
    )

    assert isinstance(result, dict)
    assert "summary" in result
    assert "metrics_summary" in result
    assert "persisted_to" in result
    assert "tabela_nome" in result  # unit_name should be renamed


def test_build_tabular_result_requires_columns() -> None:
    """build_tabular_result raises if no columns provided."""
    with pytest.raises(ValueError, match="É necessário informar"):
        build_tabular_result(
            unit_name="test",
            columns_text="",
            rows_text="",
            parse_columns_fn=simple_parse_columns,
            parse_rows_fn=simple_parse_rows,
            inline_tabular_unit_cls=FakeTabularUnit,
        )


def test_build_tabular_result_validates_row_width() -> None:
    """build_tabular_result raises if row width mismatches."""
    with pytest.raises(ValueError, match="mesma largura"):
        build_tabular_result(
            unit_name="test",
            columns_text="a, b",
            rows_text="1 | 2 | 3",  # 3 values for 2 columns
            parse_columns_fn=simple_parse_columns,
            parse_rows_fn=simple_parse_rows,
            inline_tabular_unit_cls=FakeTabularUnit,
        )


def test_build_tabular_result_enforces_max_rows_config() -> None:
    """build_tabular_result respects max_rows limit from config."""
    # When max_rows is None, it uses config default (typically 1000 or less)
    # For this test, we'll provide explicit max_rows to control behavior
    with pytest.raises(AnalysisBoundaryViolation) as exc_info:
        build_tabular_result(
            unit_name="test",
            columns_text="id, val",
            rows_text="\n".join(f"{i} | {i*2}" for i in range(10)),
            parse_columns_fn=simple_parse_columns,
            parse_rows_fn=simple_parse_rows,
            inline_tabular_unit_cls=FakeTabularUnit,
            max_rows=5,  # Explicit limit: 5 rows max
        )
    assert exc_info.value.kind == "row_limit_exceeded"


def test_build_tabular_result_max_rows_zero_disables_limit() -> None:
    """build_tabular_result with max_rows=0 disables row limit."""
    # Many rows, but limit is disabled
    result = build_tabular_result(
        unit_name="test",
        columns_text="id, val",
        rows_text="\n".join(f"{i} | {i*2}" for i in range(100)),
        parse_columns_fn=simple_parse_columns,
        parse_rows_fn=simple_parse_rows,
        inline_tabular_unit_cls=FakeTabularUnit,
        max_rows=0,  # Disable limit
    )

    assert isinstance(result, dict)


def test_build_tabular_result_uses_explicit_max_rows() -> None:
    """build_tabular_result uses explicit max_rows when provided."""
    # Within limit: should work
    result = build_tabular_result(
        unit_name="test",
        columns_text="id, val",
        rows_text="\n".join(f"{i} | {i*2}" for i in range(5)),
        parse_columns_fn=simple_parse_columns,
        parse_rows_fn=simple_parse_rows,
        inline_tabular_unit_cls=FakeTabularUnit,
        max_rows=10,  # Explicit limit: 10 rows max
    )

    assert isinstance(result, dict)


def test_build_tabular_result_renames_unit_name_to_tabela_nome() -> None:
    """build_tabular_result renames unit_name to tabela_nome in result."""
    result = build_tabular_result(
        unit_name="my_table",
        columns_text="a, b",
        rows_text="1 | 2",
        parse_columns_fn=simple_parse_columns,
        parse_rows_fn=simple_parse_rows,
        inline_tabular_unit_cls=FakeTabularUnit,
    )

    assert "tabela_nome" in result
    assert result.get("tabela_nome") == "my_table"
