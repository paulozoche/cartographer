from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzeUnitRequest(BaseModel):
    unit_name: str = Field(..., min_length=1)


class AnalyzeVerticalRequest(BaseModel):
    unit_name: str = Field(..., min_length=1)
    depth: str = Field(..., min_length=1)
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
