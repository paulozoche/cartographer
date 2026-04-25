from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from dataclasses import asdict
from typing import Any, Callable

from agnostic.application import (
    analyze_tabular_unit,
    consult_ai,
    persist_canonical_result,
    summarize_tabular_analysis,
)
from agnostic.application.ports.ai_orchestrator import AIResponse
from agnostic.application.use_cases.summarize_tabular_analysis import summarize_unit_metrics
from agnostic.config import load_app_config
from agnostic.core.errors import AnalysisBoundaryViolation
from agnostic.infrastructure.ai.grok_client import build_ai_client_from_env
from agnostic.infrastructure.storage.canonical_result_store import JsonFileCanonicalResultStore


_CACHE = OrderedDict()
_MAX_CACHE = 50


def _make_cache_key(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(payload: dict[str, Any]) -> dict[str, Any] | None:
    key = _make_cache_key(payload)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return deepcopy(_CACHE[key])
    return None


def _cache_set(payload: dict[str, Any], result: dict[str, Any]) -> None:
    key = _make_cache_key(payload)
    _CACHE[key] = deepcopy(result)
    _CACHE.move_to_end(key)
    if len(_CACHE) > _MAX_CACHE:
        _CACHE.popitem(last=False)


def build_source_result(
    source_type: str,
    source_path: str,
    *,
    analyze_units: bool,
    resolve_source_fn: Callable[[str, str], Any],
    preview_source_unit_fn: Callable[[Any], dict[str, Any]],
    ordered_unit_names_fn: Callable[[list[str], list[dict[str, Any]]], list[str]],
    attach_internal_cuts_fn: Callable[[dict[str, Any]], dict[str, Any]],
    source_summary_text_fn: Callable[[str, int | None, list[str]], str],
    resolve_optional_limit_fn: Callable[[int | None, int | None], int | None],
    unit_importance_score_fn: Callable[[dict[str, Any]], float],
    store: Any | None = None,
    max_rows_per_unit: int | None = None,
    unit_name: str | None = None,
    unit_limit: int | None = None,
) -> dict[str, Any]:
    cache_payload = {
        "kind": "source",
        "source_type": source_type,
        "source_path": source_path,
        "analyze_units": analyze_units,
        "unit_name": unit_name,
        "unit_limit": unit_limit,
        "max_rows_per_unit": max_rows_per_unit,
    }
    cached = _cache_get(cache_payload)
    if cached is not None:
        return cached

    analysis_config = load_app_config().analysis
    effective_unit_limit = resolve_optional_limit_fn(unit_limit, analysis_config.max_units_per_source)
    effective_max_rows = max_rows_per_unit if max_rows_per_unit is not None else analysis_config.max_rows_per_unit
    source = resolve_source_fn(source_type, source_path)
    source_metadata = source.get_metadata()
    units = source.list_units()
    tabela_nomes = [unit.unit_name for unit in units]

    if not analyze_units:
        unit_previews = [preview_source_unit_fn(unit) for unit in units]
        ordered_unit_names = ordered_unit_names_fn(tabela_nomes, unit_previews)
        result = {
            "origem": asdict(source_metadata),
            "summary": source_summary_text_fn(
                source_metadata.display_name,
                source_metadata.unit_count,
                ordered_unit_names,
            ),
            "persisted_to": None,
            "tabela_nomes": ordered_unit_names,
            "tabela_previas": unit_previews,
            "tabelas": [],
        }
        _cache_set(cache_payload, result)
        return result

    if unit_name:
        selected_units = [unit for unit in units if unit.unit_name == unit_name]
        if not selected_units:
            raise ValueError(f"Unit not found: {unit_name}")
        remaining_units = [unit for unit in units if unit.unit_name != unit_name]
        if effective_unit_limit is None:
            units_to_analyze = selected_units + remaining_units
        else:
            units_to_analyze = selected_units + remaining_units[: max(0, effective_unit_limit - 1)]
    else:
        units_to_analyze = units[:effective_unit_limit] if effective_unit_limit is not None else units

    resolved_store = store if store is not None else JsonFileCanonicalResultStore.default()

    inspected_units = []
    inspected_summaries = []
    persisted_paths: list[str] = []

    for unit in units_to_analyze:
        analysis = analyze_tabular_unit(unit, max_rows=effective_max_rows)
        analysis_payload = attach_internal_cuts_fn(asdict(analysis))
        if "unit_name" in analysis_payload:
            analysis_payload["tabela_nome"] = analysis_payload.pop("unit_name")
        standardized_payload = analysis_payload.get("standardized")
        if isinstance(standardized_payload, dict) and "unit_name" in standardized_payload:
            standardized_payload["tabela_nome"] = standardized_payload.pop("unit_name")
        summary = summarize_tabular_analysis(analysis)
        metrics_summary = summarize_unit_metrics(analysis)
        persisted_to = persist_canonical_result(
            "source",
            analysis,
            resolved_store,
            summary,
        )
        inspected_units.append(
            {
                **analysis_payload,
                "type": str(analysis_payload.get("type") or "table"),
                "name": str(analysis_payload.get("name") or analysis_payload.get("tabela_nome") or unit.unit_name),
                "summary": summary,
                "metrics_summary": metrics_summary,
                "importance_score": unit_importance_score_fn(
                    {
                        **analysis_payload,
                        "metrics_summary": metrics_summary,
                    }
                ),
                "persisted_to": persisted_to,
            }
        )
        inspected_summaries.append(summary)
        if persisted_to:
            persisted_paths.append(str(persisted_to))

    inspected_units.sort(
        key=lambda unit: float(unit.get("signal") or unit.get("importance_score") or 0.0),
        reverse=True,
    )

    summary_lines = [
        f"Fonte {source_metadata.display_name}: {source_metadata.unit_count or 0} unidades detectadas.",
    ]
    if unit_name:
        summary_lines.append(f"Unidade selecionada: {unit_name}.")
    elif inspected_summaries:
        summary_lines.append(f"Unidade em foco: {units_to_analyze[0].unit_name}.")
        summary_lines.append("Resumo das primeiras unidades:")
    summary_lines.extend(inspected_summaries)
    if persisted_paths:
        summary_lines.append(f"Resultado canônico salvo em {persisted_paths[0]}.")

    unit_previews = [preview_source_unit_fn(unit) for unit in units]
    ordered_unit_names = ordered_unit_names_fn(tabela_nomes, unit_previews)

    result = {
        "origem": asdict(source_metadata),
        "summary": "\n".join(summary_lines),
        "persisted_to": persisted_paths[0] if persisted_paths else None,
        "tabela_nomes": ordered_unit_names,
        "tabela_previas": unit_previews,
        "tabelas": inspected_units,
    }
    _cache_set(cache_payload, result)
    return result


def build_tabular_result(
    unit_name: str,
    columns_text: str,
    rows_text: str,
    *,
    parse_columns_fn: Callable[[str], list[str]],
    parse_rows_fn: Callable[[str], list[list[Any]]],
    inline_tabular_unit_cls: type[Any],
    store: Any | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    cache_payload = {
        "kind": "tabular",
        "unit_name": unit_name,
        "columns_text": columns_text,
        "rows_text": rows_text,
    }
    cached = _cache_get(cache_payload)
    if cached is not None:
        return cached

    analysis_config = load_app_config().analysis
    # `max_rows` follows the public request contract:
    # None -> use configured default
    # 0 -> disable row limit
    # n > 0 -> explicit request limit
    if max_rows is None:
        effective_max_rows = analysis_config.max_rows_per_unit
    elif max_rows == 0:
        effective_max_rows = None
    else:
        effective_max_rows = max_rows
    columns = parse_columns_fn(columns_text)
    rows = parse_rows_fn(rows_text)
    if not columns:
        raise ValueError("É necessário informar pelo menos uma coluna.")
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("Cada linha deve ter a mesma largura da lista de colunas.")
    if effective_max_rows is not None and len(rows) > effective_max_rows:
        raise AnalysisBoundaryViolation(
            kind="row_limit_exceeded",
            detail=f"A unidade excede o limite efetivo de {effective_max_rows} linhas para análise.",
        )

    unit = inline_tabular_unit_cls(
        unit_name=unit_name,
        columns=columns,
        rows=rows,
    )
    resolved_store = store if store is not None else JsonFileCanonicalResultStore.default()

    analysis = analyze_tabular_unit(unit, max_rows=effective_max_rows)
    summary = summarize_tabular_analysis(analysis)
    metrics_summary = summarize_unit_metrics(analysis)
    persisted_to = persist_canonical_result(
        "tabular",
        analysis,
        resolved_store,
        summary,
    )
    result = {
        **asdict(analysis),
        "summary": summary,
        "metrics_summary": metrics_summary,
        "persisted_to": persisted_to,
    }
    if "unit_name" in result:
        result["tabela_nome"] = result.pop("unit_name")
    standardized_payload = result.get("standardized")
    if isinstance(standardized_payload, dict) and "unit_name" in standardized_payload:
        standardized_payload["tabela_nome"] = standardized_payload.pop("unit_name")
    _cache_set(cache_payload, result)
    return result


def build_ai_result(prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
    client = build_ai_client_from_env()
    response: AIResponse = consult_ai(prompt, client, system_prompt=system_prompt)
    return asdict(response)


def build_health_result() -> dict[str, str]:
    return {"status": "ok"}
