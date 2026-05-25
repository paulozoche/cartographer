from __future__ import annotations

from dataclasses import asdict
from html import escape
from typing import Any
from urllib.parse import urlencode

from agnostic.application import analyze_tabular_unit, summarize_tabular_analysis
from agnostic.config import load_app_config
from agnostic.interfaces.api.rendering.cards import render_card_header
from agnostic.presentation.summaries.summarize_tabular_analysis import summarize_unit_metrics


def _priority_label(position: int, score: float) -> str:
    if position == 1 or score >= 20:
        return "prioridade alta"
    if position <= 3 or score >= 8:
        return "prioridade média"
    return "prioridade baixa"


def _rank_unit_previews(unit_previews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        unit_previews,
        key=lambda preview: (
            -float(preview.get("importance_score") or 0.0),
            str(preview.get("tabela_nome") or ""),
        ),
    )


def _ordered_unit_names(unit_names: list[str], unit_previews: list[dict[str, Any]]) -> list[str]:
    ranked_previews = _rank_unit_previews(unit_previews)
    ranked_names = [
        str(preview.get("tabela_nome") or "")
        for preview in ranked_previews
        if str(preview.get("tabela_nome") or "")
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in ranked_names + unit_names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _unit_importance_score(unit: dict[str, Any]) -> float:
    standardized = unit.get("standardized") or {}
    columns = unit.get("columns") or {}
    row_count = float(standardized.get("row_count") or 0)
    column_count = float(standardized.get("column_count") or 0)

    triggered_count = 0
    identifier_count = 0
    sparse_count = 0

    for column in columns.values():
        layer1 = column.get("layer1_metrics") or {}
        heuristics = column.get("heuristics") or []
        unique_ratio = float(layer1.get("unique_ratio", 0.0) or 0.0)
        null_ratio = float(layer1.get("null_ratio", 0.0) or 0.0)
        triggered_count += sum(1 for heuristic in heuristics if heuristic.get("triggered"))
        if unique_ratio >= 0.9 and null_ratio <= 0.05:
            identifier_count += 1
        if null_ratio >= 0.25:
            sparse_count += 1

    return (
        triggered_count * 4.0
        + identifier_count * 3.0
        + sparse_count * 0.75
        + min(row_count / 2500.0, 3.0)
        + min(column_count / 10.0, 1.5)
    )


def _preview_source_unit(unit: Any) -> dict[str, Any]:
    metadata = unit.get_metadata()
    structure = unit.get_structure()
    column_names = [column.name for column in structure.columns]
    columns_preview = column_names[:4]

    description_parts: list[str] = []
    try:
        analysis = analyze_tabular_unit(
            unit,
            max_rows=load_app_config().analysis.max_rows_per_unit,
        )
    except Exception:
        analysis = None

    if analysis is not None:
        summary_lines = summarize_tabular_analysis(analysis).splitlines()
        metrics_lines = summarize_unit_metrics(analysis)
        metrics_summary = metrics_lines[:]
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
    else:
        metrics_summary = []

    if not description_parts and column_names:
        preview_text = ", ".join(column_names[:4])
        if len(column_names) > 4:
            preview_text += ", ..."
        description_parts.append(f"Colunas: {preview_text}")

    if not description_parts:
        description_parts.append("Prévia estrutural indisponível")

    sample_preview = " · ".join(description_parts)
    if len(sample_preview) > 260:
        sample_preview = f"{sample_preview[:257]}..."
    importance_score = 0.0
    if analysis is not None:
        importance_score = _unit_importance_score(
            {
                **asdict(analysis),
                "metrics_summary": metrics_summary,
            }
        )
    return {
        "tabela_nome": unit.unit_name,
        "description": sample_preview,
        "row_count": metadata.row_count,
        "column_count": len(column_names),
        "columns_preview": columns_preview,
        "metrics_summary": metrics_summary,
        "importance_score": importance_score,
    }


def _render_source_unit_previews(
    unit_previews: list[dict[str, Any]],
    units_details: list[dict[str, Any]] | None = None,
    *,
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    focus_mode: bool,
    lang: str,
) -> str:
    if not unit_previews:
        return '<div class="small">Nenhuma tabela carregada ainda.</div>'

    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _detail_href(unit_name: str) -> str:
        query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": unit_name,
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "tabela",
        }
        return f"/?{urlencode(query)}"

    cards = []
    ranked_previews = _rank_unit_previews(unit_previews)
    for unit in ranked_previews[:9]:
        unit_name = str(unit.get("tabela_nome") or "—")
        row_count = _coerce_int(unit.get("row_count"))
        column_count = _coerce_int(unit.get("column_count"))
        columns_preview_items = [str(item).strip() for item in (unit.get("columns_preview") or []) if str(item).strip()]
        columns_preview = ", ".join(columns_preview_items[:4]) if columns_preview_items else ""
        meta_parts = [f"{row_count} linhas", f"{column_count} colunas"]
        table_summary_line = " · ".join(meta_parts).strip()
        meta_html = f'<div class="metric-meta">{escape(table_summary_line)}</div>' if table_summary_line else ""
        preview_html = f'<div class="metric-preview">{escape(columns_preview)}</div>' if columns_preview else ""
        cards.append(
            f"""
            <a class="metric-link" href="{escape(_detail_href(unit_name))}">
              <section class="metric-card"{(f' data-summary-line="{escape(table_summary_line)}"' if table_summary_line else "")}>
                <div class="metric-body">
                  {render_card_header(
                      title=unit_name,
                      occurrences=None,
                      exploration_level=0.0,
                      can_add_to_collection=True,
                      can_share=True,
                      can_mark_seen=True,
                  )}
                  {meta_html}
                  {preview_html}
                  <div class="metric-action">Abrir exploração</div>
                </div>
              </section>
            </a>
            """
        )
    if len(ranked_previews) > 9:
        cards.append(f'<div class="small">+ {len(ranked_previews) - 9} unidades adicionais.</div>')

    relation_cards: list[str] = []
    table_payloads = [item for item in (units_details or []) if isinstance(item, dict)]
    if len(table_payloads) >= 2:
        candidates: list[dict[str, Any]] = []
        for left_idx in range(len(table_payloads)):
            left = table_payloads[left_idx]
            left_name = str(left.get("tabela_nome") or "")
            left_columns = ((left.get("standardized") or {}).get("columns") or {})
            if not left_name or not isinstance(left_columns, dict):
                continue
            for right_idx in range(left_idx + 1, len(table_payloads)):
                right = table_payloads[right_idx]
                right_name = str(right.get("tabela_nome") or "")
                right_columns = ((right.get("standardized") or {}).get("columns") or {})
                if not right_name or not isinstance(right_columns, dict):
                    continue
                shared_columns = sorted(set(left_columns.keys()) & set(right_columns.keys()))
                if not shared_columns:
                    continue

                value_overlap_columns = 0
                shared_values_total = 0
                sample_values: list[str] = []
                for col_name in shared_columns:
                    left_values = left_columns.get(col_name) or []
                    right_values = right_columns.get(col_name) or []
                    if not isinstance(left_values, list) or not isinstance(right_values, list):
                        continue
                    left_set = {str(value) for value in left_values if value not in (None, "")}
                    right_set = {str(value) for value in right_values if value not in (None, "")}
                    if not left_set or not right_set:
                        continue
                    shared_values = left_set & right_set
                    if shared_values:
                        value_overlap_columns += 1
                        shared_values_total += len(shared_values)
                        if len(sample_values) < 4:
                            sample_values.extend(sorted(shared_values)[: 4 - len(sample_values)])

                candidates.append(
                    {
                        "left": left_name,
                        "right": right_name,
                        "shared_columns": len(shared_columns),
                        "value_overlap_columns": value_overlap_columns,
                        "shared_values_total": shared_values_total,
                        "samples": sample_values[:4],
                    }
                )

        ranked_candidates = sorted(
            candidates,
            key=lambda item: (int(item["value_overlap_columns"]), int(item["shared_columns"]), int(item["shared_values_total"])),
            reverse=True,
        )[:6]

        for item in ranked_candidates:
            left_query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": item["left"],
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "tabela",
            }
            right_query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": item["right"],
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "tabela",
            }
            samples = ", ".join(item["samples"]) if item["samples"] else "—"
            relation_cards.append(
                f"""
                <article class="focus-stat-card h-card">
                  <div class="h-card-layout">
                    <div class="h-card-left">
                      <div class="focus-stat-value">{escape(str(item["left"]))} ↔ {escape(str(item["right"]))}</div>
                    </div>
                    <div class="h-card-center">
                      <div class="small">{int(item["shared_columns"])} colunas em comum · {int(item["value_overlap_columns"])} com valores compartilhados</div>
                      <div class="small" style="margin-top: 8px;">Exemplos: {escape(samples)}</div>
                    </div>
                    <div class="h-card-right">
                      <a class="button secondary mini" href="/?{escape(urlencode(left_query))}">Abrir {escape(str(item["left"]))}</a>
                      <div style="margin-top: 6px;"><a class="button secondary mini" href="/?{escape(urlencode(right_query))}">Abrir {escape(str(item["right"]))}</a></div>
                    </div>
                  </div>
                </article>
                """
            )

    relations_section_html = ""
    if relation_cards:
        relations_section_html = (
            "<div class='results-title' style='margin-top: 18px;'>RELAÇÕES ENTRE TABELAS</div>"
            + "<section class='source-relations'>"
            + "".join(relation_cards)
            + "</section>"
        )

    return "<section class='source-cards'>" + "".join(cards) + "</section>" + relations_section_html
