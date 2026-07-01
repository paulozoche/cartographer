from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

try:
    import pyarrow.parquet as pq
except ModuleNotFoundError:  # pragma: no cover - exercised only when the optional dependency is absent.
    pq = None

from agnostic.domain.models.tabular import (
    ColumnStructure,
    SourceMetadata,
    UnitMetadata,
    UnitStructure,
)


def _require_pyarrow_parquet():
    if pq is None:
        raise ModuleNotFoundError(
            "Parquet support requires the optional 'pyarrow' dependency."
        )
    return pq


class ParquetDataSource:
    source_type = "parquet"
    connector_name = "pyarrow"
    connector_version = getattr(pq, "__version__", None) if pq is not None else None

    def __init__(self, file_path: str):
        self._file_path = file_path

    @property
    def display_name(self) -> str:
        return os.path.basename(self._file_path) or self._file_path

    def get_metadata(self) -> SourceMetadata:
        parquet_module = _require_pyarrow_parquet()
        return SourceMetadata(
            source_type=self.source_type,
            display_name=self.display_name,
            source_identifier=self._file_path,
            fingerprint=self._fingerprint(),
            connector_name=self.connector_name,
            connector_version=getattr(parquet_module, "__version__", None),
            unit_count=1,
        )

    def list_units(self) -> list["ParquetTabularUnit"]:
        return [ParquetTabularUnit(self._file_path, self.display_name)]

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        with open(self._file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"


class ParquetTabularUnit:
    def __init__(self, file_path: str, unit_name: str):
        self._file_path = file_path
        self._unit_name = unit_name

    @property
    def unit_name(self) -> str:
        return self._unit_name

    def get_metadata(self) -> UnitMetadata:
        parquet_module = _require_pyarrow_parquet()
        parquet_file = parquet_module.ParquetFile(self._file_path)
        return UnitMetadata(
            unit_name=self._unit_name,
            source_unit_identifier=self._file_path,
            row_count=parquet_file.metadata.num_rows,
            raw_attributes={
                "row_group_count": parquet_file.metadata.num_row_groups,
            },
        )

    def get_structure(self) -> UnitStructure:
        parquet_module = _require_pyarrow_parquet()
        parquet_file = parquet_module.ParquetFile(self._file_path)
        schema = parquet_file.schema_arrow

        columns = tuple(
            ColumnStructure(
                name=field.name,
                position=index,
                raw_type=str(field.type),
                raw_attributes={
                    "nullable": field.nullable,
                },
            )
            for index, field in enumerate(schema)
        )

        return UnitStructure(
            unit_name=self._unit_name,
            columns=columns,
            raw_attributes={
                "row_group_count": parquet_file.metadata.num_row_groups,
            },
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        parquet_module = _require_pyarrow_parquet()
        table = parquet_module.read_table(self._file_path)
        for row in table.to_pylist():
            yield tuple(row[column_name] for column_name in table.column_names)
