from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalyzeUnitRequest(BaseModel):
    unit_name: str = Field(..., min_length=1)


class AnalyzeUnitFullRequest(BaseModel):
    unit_name: str = Field(..., min_length=1)


class AnalyzeVerticalRequest(BaseModel):
    unit_name: str = Field(..., min_length=1)
    depth: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1, description="Nome da coluna")


class AnalyzeVerticalFullRequest(BaseModel):
    unit_name: str = Field(..., min_length=1)
    key: str = Field(..., min_length=1, description="Nome da coluna")


class AnalyzeHorizontalRequest(BaseModel):
    unit_a: str = Field(..., min_length=1)
    unit_b: str = Field(..., min_length=1)


class QueryRequest(BaseModel):
    sql: str = Field(..., min_length=1)


class RecallRequest(BaseModel):
    cache_key: str = Field(..., min_length=1)


class SessionCreateResponse(BaseModel):
    session_id: str
    units: list[str]


class UnitsResponse(BaseModel):
    session_id: str
    units: list[str]


class HeuristicResponse(BaseModel):
    name: str
    triggered: bool
    score: float
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StructuralPatternResponse(BaseModel):
    pattern_id: str
    regex: str
    confidence: float
    raw_type_hint: str
    sample: str


class ColumnAnalysisFullResponse(BaseModel):
    type: str
    name: str
    column_name: str
    signal: float
    exploration_score: float
    consistency_score: float
    explanation: str
    suggested_actions: list[str]
    layer1_metrics: dict[str, Any]
    layer2_metrics: dict[str, float]
    heuristics: list[HeuristicResponse]
    structural_pattern: StructuralPatternResponse


class AnalyzeVerticalFullResponse(ColumnAnalysisFullResponse):
    unit_name: str
    column: str


class TabularUnitAnalysisFullResponse(BaseModel):
    unit_name: str
    type: str
    name: str
    signal: float
    explanation: str
    suggested_actions: list[str]
    metadata: dict[str, Any]
    structure: dict[str, Any]
    row_count: int
    column_count: int
    columns: dict[str, ColumnAnalysisFullResponse]
    ranked_units: list[dict[str, Any]]


class ColumnStructureSummary(BaseModel):
    name: str
    position: int
    raw_type: str | None = None
    raw_attributes: dict[str, Any] = Field(default_factory=dict)
    cardinality: int | None = None
    null_ratio: float | None = None
    unique_ratio: float | None = None


class UnitStructureSummary(BaseModel):
    unit_name: str
    row_count: int
    column_count: int
    metadata: dict[str, Any]
    columns: list[ColumnStructureSummary]
    raw_attributes: dict[str, Any] = Field(default_factory=dict)


class SessionStructureResponse(BaseModel):
    session_id: str
    units: list[UnitStructureSummary]
