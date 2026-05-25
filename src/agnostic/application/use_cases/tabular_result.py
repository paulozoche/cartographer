"""Tabular result builder use case.

Handles inline tabular data: parsing, validation, analysis, persistence, result formatting.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from agnostic.application import summarize_tabular_analysis
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
    """Build analysis result for inline tabular data.
    
    Handles parsing, validation, analysis, persistence and result formatting.
    
    Args:
        unit_name: Name of the tabular unit
        columns_text: Serialized column definitions
        rows_text: Serialized row data
        parse_columns_fn: Function to parse columns_text
        parse_rows_fn: Function to parse rows_text
        inline_tabular_unit_cls: Class to instantiate tabular unit
        store: Optional result store (uses default if None)
        max_rows: Row limit policy:
            - None: use configured default
            - 0: disable limit
            - n > 0: explicit limit
    
    Returns:
        Analysis result dict with analysis, summary, metrics, persistence info.
        
    Raises:
        ValueError: If columns empty or row widths inconsistent
        AnalysisBoundaryViolation: If row count exceeds limit
    """
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
