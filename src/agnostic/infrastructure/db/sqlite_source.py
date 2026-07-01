from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from agnostic.domain.models.tabular import (
    ColumnStructure,
    SourceMetadata,
    UnitMetadata,
    UnitStructure,
)


class SQLiteDataSource:
    source_type = "sqlite"
    connector_name = "sqlite3"
    connector_version = sqlite3.sqlite_version

    def __init__(self, db_path: str, *, connection: sqlite3.Connection | None = None):
        self._db_path = db_path
        self._connection = connection

    @classmethod
    def from_connection(
        cls,
        connection: sqlite3.Connection,
        source_identifier: str,
    ) -> SQLiteDataSource:
        return cls(source_identifier, connection=connection)

    def execution_target(self) -> str | sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        return self._db_path

    @property
    def display_name(self) -> str:
        return os.path.basename(self._db_path) or self._db_path

    @contextmanager
    def connection(self):
        if self._connection is not None:
            self._configure_connection(self._connection)
            yield self._connection
            return
        with sqlite3.connect(self._db_path) as conn:
            self._configure_connection(conn)
            yield conn

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
        with self.connection() as connection:
            cursor = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
            )
            tables = [str(row[0]) for row in cursor.fetchall()]
        return [
            SQLiteTabularUnit(self._db_path, table_name, connection=self._connection)
            for table_name in tables
        ]

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        with open(self._db_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    @staticmethod
    def _configure_connection(connection: sqlite3.Connection) -> None:
        # Negative values set the cache in kibibytes. This keeps larger DBs responsive
        # without changing the public source contract expected by the application.
        connection.execute("PRAGMA cache_size = -2000;")


class SQLiteTabularUnit:
    def __init__(
        self,
        db_path: str,
        unit_name: str,
        *,
        connection: sqlite3.Connection | None = None,
    ):
        self._db_path = db_path
        self._unit_name = unit_name
        self._shared_connection = connection

    @property
    def unit_name(self) -> str:
        return self._unit_name

    @contextmanager
    def _open_connection(self):
        if self._shared_connection is not None:
            SQLiteDataSource._configure_connection(self._shared_connection)
            yield self._shared_connection
            return
        with sqlite3.connect(self._db_path) as conn:
            SQLiteDataSource._configure_connection(conn)
            yield conn

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name=self._unit_name,
            source_unit_identifier=f"{self._db_path}::{self._unit_name}",
            row_count=None,
        )

    def get_structure(self) -> UnitStructure:
        with self._open_connection() as connection:
            cursor = connection.execute(f'PRAGMA table_info("{self._unit_name}")')
            columns = tuple(
                ColumnStructure(
                    name=str(row[1]),
                    position=int(row[0]),
                    raw_type=str(row[2]) if row[2] is not None else None,
                    raw_attributes={
                        "notnull": bool(row[3]),
                        "default_value": row[4],
                        "primary_key_position": int(row[5]),
                    },
                )
                for row in cursor.fetchall()
            )

        return UnitStructure(
            unit_name=self._unit_name,
            columns=columns,
            raw_attributes={"format": "sqlite"},
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        with self._open_connection() as connection:
            cursor = connection.execute(f'SELECT * FROM "{self._unit_name}"')
            for row in cursor:
                yield tuple(row)
