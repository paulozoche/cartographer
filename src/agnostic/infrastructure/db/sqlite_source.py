from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterator

from agnostic.domain.models.tabular import (
    ColumnStructure,
    SourceMetadata,
    UnitMetadata,
    UnitStructure,
)


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace("\"", "\"\"")}"'


class SQLiteDataSource:
    source_type = "sqlite"
    connector_name = "sqlite3"
    connector_version = sqlite3.sqlite_version

    def __init__(self, db_path: str):
        self._db_path = db_path

    @property
    def display_name(self) -> str:
        return os.path.basename(self._db_path) or self._db_path

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_type=self.source_type,
            display_name=self.display_name,
            source_identifier=self._db_path,
            fingerprint=self._fingerprint(),
            connector_name=self.connector_name,
            connector_version=self.connector_version,
            unit_count=len(self.list_units()),
        )

    def list_units(self) -> list["SQLiteTabularUnit"]:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name;
                """
            )
            rows = cursor.fetchall()

        return [SQLiteTabularUnit(self._db_path, row[0]) for row in rows]

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        with open(self._db_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"


class SQLiteTabularUnit:
    def __init__(self, db_path: str, unit_name: str):
        self._db_path = db_path
        self._unit_name = unit_name

    @property
    def unit_name(self) -> str:
        return self._unit_name

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name=self._unit_name,
            source_unit_identifier=self._unit_name,
            row_count=None,
            raw_attributes={"sqlite_object_type": "table"},
        )

    def get_structure(self) -> UnitStructure:
        quoted_name = _quote_identifier(self._unit_name)
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({quoted_name});")
            rows = cursor.fetchall()

        if not rows:
            raise ValueError(f"Tabular unit '{self._unit_name}' was not found.")

        columns = tuple(
            ColumnStructure(
                name=row[1],
                position=index,
                raw_type=row[2] or None,
                raw_attributes={
                    "sqlite_column_id": row[0],
                    "sqlite_notnull": bool(row[3]),
                    "sqlite_default_value": row[4],
                    "sqlite_primary_key_position": row[5],
                },
            )
            for index, row in enumerate(rows)
        )

        return UnitStructure(
            unit_name=self._unit_name,
            columns=columns,
            raw_attributes={"sqlite_object_type": "table"},
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        quoted_name = _quote_identifier(self._unit_name)
        conn = sqlite3.connect(self._db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {quoted_name};")
            for row in cursor:
                yield tuple(row)
        finally:
            conn.close()
