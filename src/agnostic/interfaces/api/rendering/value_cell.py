from __future__ import annotations

from collections import Counter
from html import escape
from typing import Any

from agnostic.interfaces.api.rendering.cards import render_info_card
from agnostic.interfaces.api.rendering.decision import _recorte_decision_kind
from agnostic.interfaces.api.rendering.decisions import _collect_column_decisions
from agnostic.interfaces.api.rendering.signatures import _build_synthetic_signatures
from agnostic.interfaces.value_identity import cell_value_identity_token, resolve_selected_value_impact
from agnostic.domain.analysis.compute_value_cell_metrics import build_value_cell_analysis_payload


def _render_value_cell_details(
    *,
    result: dict[str, Any] | None,
    selected_unit: str,
    selected_column: str | None,
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    focus_mode: bool,
    recorte_id: str,
    relation_column: str,
    relation_values_text: str,
    selected_value: str,
    selected_value_id: str,
    slice_mode: str,
    signature_path: str,
    decision_type: str,
    exception_group: str,
    context_filters_text: str,
    action: str,
    lang: str,
) -> str:
    if not result or not selected_column or not selected_value:
        return ""

    units = result.get("tabelas") or []
    current = None
    for unit in units:
        if str(unit.get("tabela_nome") or "") == str(selected_unit):
            current = unit
            break
    if current is None and units:
        current = units[0]
    if not isinstance(current, dict):
        return content_html

    columns = current.get("columns") or {}
    column_payload = columns.get(selected_column) if isinstance(columns, dict) else None
    standardized = current.get("standardized") or {}
    values = list((standardized.get("columns") or {}).get(selected_column) or [])
    value_counter = Counter(cell_value_identity_token(value) for value in values)
    total_rows = len(values)

    recortes = _collect_column_decisions(column_payload if isinstance(column_payload, dict) else None)
    standardized_columns = (standardized.get("columns") or {}) if isinstance(standardized, dict) else {}
    synthetic_signatures = _build_synthetic_signatures(
        column_payload=column_payload if isinstance(column_payload, dict) else None,
        values=values,
        selected_column=str(selected_column or ""),
        standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
    )
    if synthetic_signatures:
        recortes.extend(synthetic_signatures)

    active_recorte = None
    normalized_decision_type = str(decision_type or "").strip().lower()
    if recorte_id:
        active_recorte = next(
            (item for item in recortes if str(item.get("id") or "") == str(recorte_id)),
            None,
        )
    if active_recorte is None and normalized_decision_type:
        active_recorte = next(
            (item for item in recortes if _recorte_decision_kind(item) == normalized_decision_type),
            None,
        )

    impact = resolve_selected_value_impact(
        selected_value_id=selected_value_id,
        selected_value=selected_value,
        active_recorte=active_recorte,
        total_rows=total_rows,
        fallback_counter=value_counter,
    )
    resolved_value = impact.get("resolved_value")
    resolved_count = int(impact.get("count") or 0)
    decision_kind = _recorte_decision_kind(active_recorte)
    decision_label_map = {
        "exception": "Exceção",
        "dominance": "Dominância",
        "conflict": "Conflito",
        "missing": "Ausência",
    }
    decision_label = decision_label_map.get(decision_kind, "Decisão")
    value_payload = build_value_cell_analysis_payload(
        table=str(selected_unit or current.get("tabela_nome") or "—"),
        column=str(selected_column or "—"),
        decision=decision_label,
        value=resolved_value if resolved_value is not None else selected_value,
        total_rows=total_rows,
        frequency=resolved_count,
        selected_value_id=str(impact.get("resolved_value_id") or selected_value_id or ""),
        standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
        column_order=list(standardized_columns.keys()) if isinstance(standardized_columns, dict) else None,
    )

    representative_row = value_payload.get("representative_row") if isinstance(value_payload, dict) else None
    associated_rows = value_payload.get("associated_rows") if isinstance(value_payload, dict) else []
    rows_total = int(value_payload.get("associated_rows_total") or 0) if isinstance(value_payload, dict) else 0
    rows_hidden = int(value_payload.get("associated_rows_hidden") or 0) if isinstance(value_payload, dict) else 0
    are_identical = value_payload.get("associated_rows_are_identical") if isinstance(value_payload, dict) else None

    row_blocks: list[str] = []
    rows_to_render = associated_rows if isinstance(associated_rows, list) and associated_rows else []
    if not rows_to_render and isinstance(representative_row, dict):
        rows_to_render = [representative_row]

    for row in rows_to_render:
        row_values = row.get("values") if isinstance(row, dict) and isinstance(row.get("values"), dict) else {}
        cells_html = []
        for column_name, column_value in row_values.items():
            value_text = "NULL" if column_value is None else str(column_value)
            value_class = "associated-row-value associated-row-value-long" if len(value_text) > 80 else "associated-row-value"
            cells_html.append(
                f"""
                <div class="associated-row-cell">
                  <div class="small">{escape(str(column_name))}</div>
                  <div class="{value_class}">{escape(value_text)}</div>
                </div>
                """
            )
        row_blocks.append(
            render_info_card(
                title="Linha associada",
                body_html=f'<div class="associated-row-grid">{"".join(cells_html)}</div>',
                class_name="associated-row-card",
                can_add_to_collection=True,
                can_share=True,
                can_mark_seen=True,
            )
        )

    hidden_rows_html = (
        f"<div class='origin-line'>Linhas adicionais ocultas: {rows_hidden}</div>"
        if rows_hidden > 0
        else ""
    )
    row_summary_html = render_info_card(
        title="Valor/célula",
        body_html=(
            f"<div class='origin-line'>Caminho: origem / {escape(str(selected_unit or current.get('tabela_nome') or '—'))} / "
            f"{escape(str(selected_column or '—'))} / {escape(str(resolved_value if resolved_value not in (None, '') else selected_value))}</div>"
            f"<div class='origin-line'>Valor: {escape(str(resolved_value if resolved_value not in (None, '') else selected_value))}</div>"
            f"<div class='origin-line'>Ocorrências observadas: {resolved_count}</div>"
            f"<div class='origin-line'>Linhas associadas: {rows_total}</div>"
            f"<div class='origin-line'>Linhas idênticas: {'sim' if are_identical else 'não' if are_identical is not None else '—'}</div>"
            f"{hidden_rows_html}"
        ),
        can_add_to_collection=True,
        can_share=True,
        can_mark_seen=True,
    )
    return f"""
      <section class="decision-zone">
        <div class='results-title'>Contexto da célula</div>
        <div class='focus-stats focus-cards-horizontal'>
          {row_summary_html}
        </div>
        <div class='results-title'>Linhas associadas</div>
        <div class='focus-stats focus-cards-horizontal'>
          {''.join(row_blocks)}
        </div>
      </section>
    """
