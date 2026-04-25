from __future__ import annotations

from pathlib import Path

from agnostic.infrastructure.storage.csv_source import CSVDataSource


def _build_csv(csv_path: Path) -> None:
    csv_path.write_text(
        "event_id,category,amount\n"
        "1,A,10.5\n"
        "2,B,11.0\n",
        encoding="utf-8",
    )


def test_csv_source_exposes_metadata_and_single_unit(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    _build_csv(csv_path)

    source = CSVDataSource(str(csv_path))
    metadata = source.get_metadata()
    units = source.list_units()

    assert metadata.source_type == "csv"
    assert metadata.display_name == "sample.csv"
    assert metadata.source_identifier == str(csv_path)
    assert metadata.fingerprint.startswith("sha256:")
    assert metadata.unit_count == 1
    assert [unit.unit_name for unit in units] == ["sample.csv"]


def test_csv_tabular_unit_exposes_header_as_structure(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    _build_csv(csv_path)

    source = CSVDataSource(str(csv_path))
    unit = source.list_units()[0]

    structure = unit.get_structure()

    assert structure.unit_name == "sample.csv"
    assert [column.name for column in structure.columns] == ["event_id", "category", "amount"]
    assert [column.position for column in structure.columns] == [0, 1, 2]


def test_csv_tabular_unit_rows_are_positional_sequences(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    _build_csv(csv_path)

    source = CSVDataSource(str(csv_path))
    unit = source.list_units()[0]

    rows = list(unit.get_rows())

    assert rows == [
        ("1", "A", "10.5"),
        ("2", "B", "11.0"),
    ]
