from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from agnostic.domain.models.tabular import SourceMetadata, UnitMetadata, UnitStructure

Row = tuple[Any, ...]
RowStream = Iterable[Row]


class TabularUnit(Protocol):
    @property
    def unit_name(self) -> str: ...

    def get_metadata(self) -> UnitMetadata: ...

    def get_structure(self) -> UnitStructure: ...

    def get_rows(self) -> RowStream: ...


class DataSource(Protocol):
    @property
    def source_type(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    def get_metadata(self) -> SourceMetadata: ...

    def list_units(self) -> list[TabularUnit]: ...
