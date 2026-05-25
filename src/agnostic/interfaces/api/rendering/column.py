from __future__ import annotations

from html import escape
from typing import Any
from agnostic.interfaces.api.rendering.decisions import _collect_column_decisions
from agnostic.interfaces.api.rendering.signatures import (
    _build_synthetic_signatures,
    _collect_triggered_signal_names,
    _signal_explanation,
    _signal_label,
)


def _render_focused_column(
    *,
    result: dict[str, Any] | None,
    selected_unit: str,
    selected_column: str | None,
    signature_path: str,
    lang: str,
) -> str:
    if not result or not selected_column:
        return ""
    units = result.get("tabelas") or []
    if not units:
        return ""
    current = None
    for unit in units:
        if str(unit.get("tabela_nome") or "") == selected_unit:
            current = unit
            break
    if current is None:
        current = units[0]
    columns = current.get("columns") or {}
    column = columns.get(selected_column)
    if not column:
        return ""

    standardized = current.get("standardized") or {}
    values = list((standardized.get("columns") or {}).get(selected_column) or [])
    unit_label = str(current.get("tabela_nome") or selected_unit or "—")
    row_count_raw = standardized.get("row_count")
    row_count = int(row_count_raw) if row_count_raw is not None else None
    cardinality_raw = (column.get("layer1_metrics") or {}).get("cardinality")
    cardinality = int(cardinality_raw) if cardinality_raw is not None else None
    null_ratio_raw = (column.get("layer1_metrics") or {}).get("null_ratio")
    null_ratio = float(null_ratio_raw) if null_ratio_raw is not None else None
    unique_ratio_raw = (column.get("layer1_metrics") or {}).get("unique_ratio")
    unique_ratio = float(unique_ratio_raw) if unique_ratio_raw is not None else None

    path_suffix = " / exceção" if signature_path == "valor/celula" else ""
    context_lines: list[str] = [
        f"<div class='origin-line'>Caminho: origem / {escape(unit_label)} / {escape(selected_column)}{path_suffix}</div>",
        f"<div class='origin-line'>Coluna: {escape(selected_column)}</div>",
    ]
    metrics_lines: list[str] = []
    if row_count is not None:
        metrics_lines.append(f"<div class='origin-line'>Linhas: {row_count}</div>")
    if cardinality is not None:
        metrics_lines.append(f"<div class='origin-line'>Cardinalidade: {cardinality}</div>")
    if null_ratio is not None:
        metrics_lines.append(f"<div class='origin-line'>Nulos: {null_ratio:.2f}</div>")
    if unique_ratio is not None:
        metrics_lines.append(f"<div class='origin-line'>Únicos: {unique_ratio:.2f}</div>")

    signal_lines: list[str] = []
    triggered_signals = _collect_triggered_signal_names(column if isinstance(column, dict) else None)
    for signal_name in triggered_signals[:4]:
        signal_lines.append(
            f"<div class='origin-line'>{escape(_signal_label(signal_name))}: {escape(_signal_explanation(signal_name))}</div>"
        )

    standardized_columns = (standardized.get("columns") or {}) if isinstance(standardized, dict) else {}
    synthetic_signatures = _build_synthetic_signatures(
        column_payload=column if isinstance(column, dict) else None,
        values=values,
        selected_column=str(selected_column),
        standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
    )
    column_decisions = _collect_column_decisions(column if isinstance(column, dict) else None)
    column_decisions = [*column_decisions, *synthetic_signatures]

    context_html = (
        "".join(context_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Métricas</strong></div>"
        + "".join(metrics_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Sinais</strong></div>"
        + "".join(signal_lines)
    )

    return f"""
      <div class="results-title">Contexto da coluna</div>
      <section class="origin-overview">
        {context_html}
      </section>
    """
