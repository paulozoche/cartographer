from __future__ import annotations

import csv
import hashlib
import os
from collections.abc import Iterator

import chardet

from agnostic.domain.models.tabular import (
    ColumnStructure,
    SourceMetadata,
    UnitMetadata,
    UnitStructure,
)

_ENCODING_SAMPLE_SIZE = 65536


def _detect_encoding(file_path: str) -> str:
    with open(file_path, "rb") as handle:
        raw = handle.read()

    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    sample = raw[:_ENCODING_SAMPLE_SIZE]
    detected = chardet.detect(sample)
    encoding = str(detected.get("encoding") or "").strip()
    confidence = float(detected.get("confidence") or 0)
    if encoding and confidence >= 0.5:
        return encoding

    return "latin-1"


class CSVDataSource:
    source_type = "csv"
    connector_name = "csv"
    connector_version = "python-stdlib"

    def __init__(self, file_path: str, encoding: str | None = None):
        self._file_path = file_path
        self._encoding = encoding if encoding is not None else _detect_encoding(file_path)

    @property
    def display_name(self) -> str:
        return os.path.basename(self._file_path) or self._file_path

    def get_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            source_type=self.source_type,
            display_name=self.display_name,
            source_identifier=self._file_path,
            fingerprint=self._fingerprint(),
            connector_name=self.connector_name,
            connector_version=self.connector_version,
            unit_count=1,
            raw_attributes={"encoding": self._encoding},
        )

    def list_units(self) -> list["CSVTabularUnit"]:
        return [CSVTabularUnit(self._file_path, self.display_name, self._encoding)]

    def _fingerprint(self) -> str:
        digest = hashlib.sha256()
        with open(self._file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"


class CSVTabularUnit:
    def __init__(self, file_path: str, unit_name: str, encoding: str = "utf-8"):
        self._file_path = file_path
        self._unit_name = unit_name
        self._encoding = encoding

    @property
    def unit_name(self) -> str:
        return self._unit_name

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name=self._unit_name,
            source_unit_identifier=self._file_path,
            row_count=None,
            raw_attributes={"encoding": self._encoding},
        )

    def get_structure(self) -> UnitStructure:
        with open(self._file_path, "r", encoding=self._encoding, newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)

        if header is None:
            raise ValueError(f"CSV unit '{self._unit_name}' is empty.")

        columns = tuple(
            ColumnStructure(
                name=column_name,
                position=index,
            )
            for index, column_name in enumerate(header)
        )

        return UnitStructure(
            unit_name=self._unit_name,
            columns=columns,
            raw_attributes={"format": "csv"},
        )

    def get_rows(self) -> Iterator[tuple[object, ...]]:
        with open(self._file_path, "r", encoding=self._encoding, newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            for row in reader:
                yield tuple(row)
