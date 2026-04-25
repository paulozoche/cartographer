from __future__ import annotations

import sqlite3
from pathlib import Path

from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource


def _build_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE events (
                event_id INTEGER PRIMARY KEY,
                category TEXT,
                amount REAL
            );
            """
        )
        cursor.executemany(
            "INSERT INTO events (event_id, category, amount) VALUES (?, ?, ?);",
            [
                (1, "A", 10.5),
                (2, "B", 11.0),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_sqlite_source_exposes_metadata_and_units(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.db"
    _build_db(db_path)

    source = SQLiteDataSource(str(db_path))
    metadata = source.get_metadata()
    units = source.list_units()

    assert metadata.source_type == "sqlite"
    assert metadata.display_name == "sample.db"
    assert metadata.source_identifier == str(db_path)
    assert metadata.fingerprint.startswith("sha256:")
    assert metadata.unit_count == 1
    assert [unit.unit_name for unit in units] == ["events"]


def test_sqlite_tabular_unit_exposes_structure_without_interpretation(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.db"
    _build_db(db_path)

    source = SQLiteDataSource(str(db_path))
    unit = source.list_units()[0]

    metadata = unit.get_metadata()
    structure = unit.get_structure()

    assert metadata.unit_name == "events"
    assert metadata.row_count is None
    assert [column.name for column in structure.columns] == ["event_id", "category", "amount"]
    assert [column.position for column in structure.columns] == [0, 1, 2]
    assert structure.columns[0].raw_type == "INTEGER"
    assert structure.columns[1].raw_type == "TEXT"


def test_sqlite_tabular_unit_rows_are_positional_sequences(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.db"
    _build_db(db_path)

    source = SQLiteDataSource(str(db_path))
    unit = source.list_units()[0]

    rows = list(unit.get_rows())

    assert rows == [
        (1, "A", 10.5),
        (2, "B", 11.0),
    ]
