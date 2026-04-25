from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

import pyarrow as pa
import pyarrow.parquet as pq

from agnostic.infrastructure.storage.parquet_source import ParquetDataSource


def _build_parquet(parquet_path: Path) -> None:
    table = pa.table(
        {
            "event_id": [1, 2],
            "category": ["A", "B"],
            "amount": [10.5, 11.0],
        }
    )
    pq.write_table(table, parquet_path)


def test_parquet_source_exposes_metadata_and_single_unit(tmp_path: Path) -> None:
    parquet_path = tmp_path / "sample.parquet"
    _build_parquet(parquet_path)

    source = ParquetDataSource(str(parquet_path))
    metadata = source.get_metadata()
    units = source.list_units()

    assert metadata.source_type == "parquet"
    assert metadata.display_name == "sample.parquet"
    assert metadata.source_identifier == str(parquet_path)
    assert metadata.fingerprint.startswith("sha256:")
    assert metadata.unit_count == 1
    assert [unit.unit_name for unit in units] == ["sample.parquet"]


def test_parquet_tabular_unit_exposes_structure_without_interpretation(tmp_path: Path) -> None:
    parquet_path = tmp_path / "sample.parquet"
    _build_parquet(parquet_path)

    source = ParquetDataSource(str(parquet_path))
    unit = source.list_units()[0]

    metadata = unit.get_metadata()
    structure = unit.get_structure()

    assert metadata.unit_name == "sample.parquet"
    assert metadata.row_count == 2
    assert [column.name for column in structure.columns] == ["event_id", "category", "amount"]
    assert [column.position for column in structure.columns] == [0, 1, 2]
    assert structure.columns[0].raw_type == "int64"


def test_parquet_tabular_unit_rows_are_positional_sequences(tmp_path: Path) -> None:
    parquet_path = tmp_path / "sample.parquet"
    _build_parquet(parquet_path)

    source = ParquetDataSource(str(parquet_path))
    unit = source.list_units()[0]

    rows = list(unit.get_rows())

    assert rows == [
        (1, "A", 10.5),
        (2, "B", 11.0),
    ]
