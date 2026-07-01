from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from agnostic.application import (
    summarize_tabular_analysis,
)
from agnostic.application.cache.runtime_analysis_cache import (
    _cache_get,
    _cache_set,
)
from agnostic.config import load_app_config
from agnostic.core.errors import AnalysisBoundaryViolation
from agnostic.domain.analysis.analyze_tabular_unit import analyze_tabular_unit
from agnostic.infrastructure.export.persist_canonical_result import persist_canonical_result
from agnostic.infrastructure.storage.canonical_result_store import JsonFileCanonicalResultStore
from agnostic.presentation.summaries.summarize_tabular_analysis import summarize_unit_metrics


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


__all__ = ["build_source_result"]
