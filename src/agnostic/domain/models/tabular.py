from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_type: str
    display_name: str
    source_identifier: str
    fingerprint: str | None = None
    connector_name: str | None = None
    connector_version: str | None = None
    unit_count: int | None = None
    raw_attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UnitMetadata:
    unit_name: str
    source_unit_identifier: str
    row_count: int | None = None
    raw_attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ColumnStructure:
    name: str
    position: int
    raw_type: str | None = None
    raw_attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class UnitStructure:
    unit_name: str
    columns: tuple[ColumnStructure, ...]
    raw_attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StandardizedTabularUnit:
    unit_name: str
    columns: dict[str, tuple[Any, ...]]
    row_count: int
    column_count: int
    column_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricExecutionPolicy:
    mode: str = "full"
    sample_size: int | None = None
    sampling_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class FrequencyMetricResult:
    counts: dict[Any, int]
    sampled: bool
    sample_size: int
    total_size: int
    coverage_ratio: float
    sampling_strategy: str | None = None


@dataclass(frozen=True, slots=True)
class ModeFrequencyMetricResult:
    value: Any
    count: int
    ratio: float
