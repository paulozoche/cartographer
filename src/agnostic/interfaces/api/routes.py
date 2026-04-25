from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import Response

from agnostic.application import analyze_tabular_unit, consult_ai, summarize_tabular_analysis
from agnostic.application import render_canonical_analysis_markdown
from agnostic.application.use_cases.runtime_analysis import (
    build_source_result as run_build_source_result,
    build_tabular_result as run_build_tabular_result,
)
from agnostic.application.use_cases.summarize_tabular_analysis import summarize_unit_metrics
from agnostic.application.ports.ai_orchestrator import AIOrchestrator
from agnostic.config import load_app_config
from agnostic.core import attach_internal_cuts as core_attach_internal_cuts
from agnostic.core import resolve_optional_limit as core_resolve_optional_limit
from agnostic.core import source_summary_text as core_source_summary_text
from agnostic.core.errors import AnalysisBoundaryViolation
from agnostic.infrastructure.ai.grok_client import GroqAPIError
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.infrastructure.storage.csv_source import CSVDataSource
from agnostic.infrastructure.storage.parquet_source import ParquetDataSource
from agnostic.interfaces.api.dependencies import get_ai_client
from agnostic.interfaces.api.schemas import (
    AIConsultRequest,
    AIConsultResponse,
    SourceInspectionRequest,
    SourceInspectionResponse,
    TabularAnalysisRequest,
    TabularAnalysisResponse,
)
from agnostic.domain.models.tabular import ColumnStructure, UnitMetadata, UnitStructure


router = APIRouter()


def _resolve_optional_limit(request_value: int | None, default_value: int | None) -> int | None:
    return core_resolve_optional_limit(request_value, default_value)


class _InlineTabularUnit:
    def __init__(self, unit_name: str, columns: list[str], rows: list[list[object]]) -> None:
        self._unit_name = unit_name
        self._columns = columns
        self._rows = rows

    @property
    def unit_name(self) -> str:
        return self._unit_name

    def get_metadata(self) -> UnitMetadata:
        return UnitMetadata(
            unit_name=self._unit_name,
            source_unit_identifier=f"http://inline/{self._unit_name}",
            row_count=len(self._rows),
        )

    def get_structure(self) -> UnitStructure:
        return UnitStructure(
            unit_name=self._unit_name,
            columns=tuple(
                ColumnStructure(name=column_name, position=index)
                for index, column_name in enumerate(self._columns)
            ),
            raw_attributes={"source": "http-payload"},
        )

    def get_rows(self):
        for row in self._rows:
            yield tuple(row)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_sample(values: list[object], limit: int = 3) -> list[str]:
    sample: list[str] = []
    for value in values:
        if value is None:
            continue
        sample.append(str(value))
        if len(sample) >= limit:
            break
    return sample


def _build_dominancia_recorte(
    *,
    unit_name: str,
    column_name: str,
    mode_metric: dict[str, Any],
    counts: dict[Any, Any],
    unique_ratio: float,
) -> dict[str, Any] | None:
    ratio = _safe_float(mode_metric.get("ratio"), 0.0)
    if ratio < 0.45:
        return None
    mode_value = mode_metric.get("value")
    mode_count = int(_safe_float(mode_metric.get("count"), 0.0))
    if ratio >= 0.75:
        prioridade = "alta"
        estado = "estavel"
    elif ratio >= 0.55:
        prioridade = "media"
        estado = "ativo"
    else:
        prioridade = "baixa"
        estado = "ambiguo"
    mode_token = "__none__" if mode_value is None else str(mode_value)
    return {
        "id": f"rc::{unit_name}::{column_name}::dominancia::{mode_token}",
        "tipo": "dominancia",
        "evidencia": {
            "descricao": f"Valor dominante detectado ({mode_token}) com frequência relativa {_safe_float(ratio):.2f}.",
            "camada_origem": "coluna",
            "sinais": ["mode_frequency", "frequency", "unique_ratio"],
            "amostra": [mode_token] + _string_sample(list(counts.keys())),
        },
        "prioridade": prioridade,
        "estado_estrutural": estado,
        "transicoes_permitidas": [
            {
                "destino": "valor_celula",
                "alvo_id": f"vl::{unit_name}::{column_name}::{mode_token}",
                "motivo": "abrir valor dominante",
            },
            {
                "destino": "recorte",
                "alvo_id": f"rc::{unit_name}::{column_name}::excecao::cluster",
                "motivo": "contrastar com exceções",
            },
        ],
    }


def _build_excecao_recorte(
    *,
    unit_name: str,
    column_name: str,
    counts: dict[Any, Any],
    unique_ratio: float,
) -> dict[str, Any] | None:
    if not counts:
        return None
    rare_items = sorted(
        ((key, int(_safe_float(value, 0.0))) for key, value in counts.items()),
        key=lambda item: item[1],
    )
    rare_items = [item for item in rare_items if item[1] <= 1]
    if not rare_items and unique_ratio < 0.8:
        return None
    sample_values = [str(item[0]) for item in rare_items[:3]] or _string_sample(list(counts.keys()))
    prioridade = "alta" if unique_ratio >= 0.9 else "media"
    return {
        "id": f"rc::{unit_name}::{column_name}::excecao::cluster",
        "tipo": "excecao",
        "evidencia": {
            "descricao": "Valores raros ou singulares observados na distribuição da coluna.",
            "camada_origem": "coluna",
            "sinais": ["frequency", "unique_ratio"],
            "amostra": sample_values,
        },
        "prioridade": prioridade,
        "estado_estrutural": "ativo",
        "transicoes_permitidas": [
            {
                "destino": "valor_celula",
                "alvo_id": f"vl::{unit_name}::{column_name}::outlier",
                "motivo": "inspecionar valores raros",
            },
        ],
    }


def _build_ausencia_recorte(
    *,
    unit_name: str,
    column_name: str,
    null_ratio: float,
    empty_string_ratio: float,
) -> dict[str, Any] | None:
    if max(null_ratio, empty_string_ratio) < 0.10:
        return None
    if max(null_ratio, empty_string_ratio) >= 0.35:
        prioridade = "alta"
    elif max(null_ratio, empty_string_ratio) >= 0.2:
        prioridade = "media"
    else:
        prioridade = "baixa"
    return {
        "id": f"rc::{unit_name}::{column_name}::ausencia::null-empty",
        "tipo": "ausencia",
        "evidencia": {
            "descricao": (
                "Ausências estruturais detectadas "
                f"(null_ratio={null_ratio:.2f}, empty_string_ratio={empty_string_ratio:.2f})."
            ),
            "camada_origem": "coluna",
            "sinais": ["null_ratio", "empty_string_ratio"],
            "amostra": ["NULL", ""],
        },
        "prioridade": prioridade,
        "estado_estrutural": "ativo",
        "transicoes_permitidas": [
            {
                "destino": "subconjunto",
                "alvo_id": f"sb::{unit_name}::{column_name}::ausencia",
                "motivo": "abrir subconjunto com ausências",
            },
            {
                "destino": "valor_celula",
                "alvo_id": f"vl::{unit_name}::{column_name}::__null_or_empty__",
                "motivo": "inspecionar células ausentes",
            },
        ],
    }


def _attach_internal_cuts(payload: dict[str, Any]) -> dict[str, Any]:
    return core_attach_internal_cuts(payload)


def _resolve_source(source_type: str, source_path: str):
    path = Path(source_path)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Caminho da origem não encontrado: {source_path}",
        )
    if not path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"O caminho da origem deve apontar para um arquivo, não para um diretório: {source_path}",
        )

    normalized = source_type.strip().lower()
    if normalized == "sqlite":
        return SQLiteDataSource(source_path)
    if normalized == "csv":
        return CSVDataSource(source_path)
    if normalized == "parquet":
        return ParquetDataSource(source_path)
    raise HTTPException(
        status_code=400,
        detail=f"source_type não suportado '{source_type}'. Use sqlite, csv ou parquet.",
    )


def _source_summary_text(display_name: str, unit_count: int | None, unit_names: list[str]) -> str:
    return core_source_summary_text(display_name, unit_count, unit_names)


def _download_filename(kind: str, unit_name: str) -> str:
    safe_kind = kind.strip().replace(" ", "_") or "analysis"
    safe_unit = unit_name.strip().replace(" ", "_") or "result"
    return f"{safe_kind}-{safe_unit}-summary.md"


def _preview_text_for_unit(unit) -> str:
    metadata = unit.get_metadata()
    structure = unit.get_structure()
    column_names = [column.name for column in structure.columns]

    description_parts: list[str] = []
    try:
        analysis = analyze_tabular_unit(unit)
    except Exception:  # pragma: no cover - preview must stay resilient
        analysis = None

    if analysis is not None:
        summary_lines = summarize_tabular_analysis(analysis).splitlines()
        metrics_lines = summarize_unit_metrics(analysis)
        if summary_lines:
            description_parts.append(summary_lines[0].rstrip("."))
        if len(summary_lines) > 1:
            description_parts.append(summary_lines[1].rstrip("."))
        if len(summary_lines) > 2:
            description_parts.append(summary_lines[2].lstrip("- ").rstrip("."))
        if len(metrics_lines) > 1:
            description_parts.append(metrics_lines[1].rstrip("."))
        elif metrics_lines:
            description_parts.append(metrics_lines[0].rstrip("."))

    if not description_parts and metadata.row_count is not None and column_names:
        columns_preview = ", ".join(column_names[:4])
        if len(column_names) > 4:
            columns_preview += ", ..."
        description_parts.append(
            f"{metadata.row_count} linhas, {len(column_names)} colunas. Colunas: {columns_preview}"
        )
    elif not description_parts and column_names:
        columns_preview = ", ".join(column_names[:4])
        if len(column_names) > 4:
            columns_preview += ", ..."
        description_parts.append(f"Colunas: {columns_preview}")
    elif not description_parts:
        description_parts.append("Prévia estrutural indisponível")

    description = " · ".join(description_parts)
    if len(description) > 260:
        description = f"{description[:257]}..."
    return description


def _preview_unit_payload(unit) -> dict[str, object]:
    metadata = unit.get_metadata()
    structure = unit.get_structure()
    column_names = [column.name for column in structure.columns]
    preview_columns = column_names[:4]
    description = _preview_text_for_unit(unit)
    return {
        "tabela_nome": unit.unit_name,
        "description": description,
        "row_count": metadata.row_count,
        "column_count": len(column_names),
        "columns_preview": preview_columns,
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ai/consult", response_model=AIConsultResponse)
def ai_consult(
    payload: AIConsultRequest,
    ai_client: AIOrchestrator = Depends(get_ai_client),
) -> AIConsultResponse:
    try:
        response = consult_ai(
            payload.prompt,
            ai_client,
            system_prompt=payload.system_prompt,
        )
        return AIConsultResponse.model_validate(response)
    except GroqAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/analysis/tabular", response_model=TabularAnalysisResponse)
def analyze_tabular(
    payload: TabularAnalysisRequest,
) -> TabularAnalysisResponse:
    try:
        response_payload = _attach_internal_cuts(
            run_build_tabular_result(
                payload.unit_name,
                "\n".join(payload.columns),
                "\n".join(json.dumps(row, ensure_ascii=False) for row in payload.rows),
                parse_columns_fn=lambda value: [line.strip() for line in value.splitlines() if line.strip()],
                parse_rows_fn=lambda value: [
                    json.loads(line.strip())
                    for line in value.splitlines()
                    if line.strip()
                ],
                inline_tabular_unit_cls=_InlineTabularUnit,
                max_rows=payload.max_rows,
            )
        )
        return TabularAnalysisResponse.model_validate(response_payload)
    except ValueError as exc:
        if isinstance(exc, AnalysisBoundaryViolation):
            if exc.kind == "row_limit_exceeded":
                raise HTTPException(status_code=413, detail=str(exc)) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        detail = str(exc)
        if "mesma largura" in detail:
            raise HTTPException(status_code=400, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc


@router.get("/analysis/summary/download")
def download_summary(persisted_to: str = Query(min_length=1)) -> Response:
    path = Path(persisted_to)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Resultado persistido não encontrado: {persisted_to}",
        )
    if not path.is_file():
        raise HTTPException(
            status_code=400,
            detail=f"O resultado persistido deve ser um arquivo: {persisted_to}",
        )

    try:
        with path.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON do resultado persistido inválido: {exc}") from exc

    markdown = render_canonical_analysis_markdown(record)
    filename = _download_filename(
        str(record.get("kind", "analysis")),
        str(record.get("unit_name", "result")),
    )
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/analysis/source", response_model=SourceInspectionResponse)
def inspect_source(
    payload: SourceInspectionRequest,
) -> SourceInspectionResponse:
    try:
        config = load_app_config().analysis
        effective_max_rows = _resolve_optional_limit(payload.max_rows_per_unit, config.max_rows_per_unit)
        response_payload = run_build_source_result(
            payload.source_type,
            payload.source_path,
            analyze_units=payload.analyze_units,
            resolve_source_fn=_resolve_source,
            preview_source_unit_fn=_preview_unit_payload,
            ordered_unit_names_fn=lambda names, _previews: names,
            attach_internal_cuts_fn=_attach_internal_cuts,
            source_summary_text_fn=_source_summary_text,
            resolve_optional_limit_fn=_resolve_optional_limit,
            unit_importance_score_fn=lambda _unit: 0.0,
            max_rows_per_unit=effective_max_rows,
            unit_name=payload.unit_name,
            unit_limit=payload.unit_limit,
        )
        return SourceInspectionResponse.model_validate(response_payload)
    except ValueError as exc:
        detail = str(exc)
        if detail.startswith("Unit not found: "):
            raise HTTPException(
                status_code=404,
                detail=f"Unidade não encontrada: {payload.unit_name}",
            ) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive boundary handling
        raise HTTPException(status_code=500, detail=str(exc)) from exc
