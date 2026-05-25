# interfaces/api/rendering/table.py
from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlencode

from agnostic.interfaces.api.rendering.cards import render_card_header

def _select_unit_name(unit_names: list[str], current: str, action: str) -> str:
    if not unit_names:
        return ""
    if current not in unit_names:
        current = unit_names[0]
    current_index = unit_names.index(current)
    if action == "previous":
        return unit_names[max(0, current_index - 1)]
    if action == "next":
        return unit_names[min(len(unit_names) - 1, current_index + 1)]
    return current


def _render_options(unit_names: list[str], selected: str) -> str:
    if not unit_names:
        return '<option value="">Nenhuma unidade carregada ainda.</option>'
    options = []
    for unit in unit_names:
        selected_attr = " selected" if unit == selected else ""
        options.append(f'<option value="{escape(unit)}"{selected_attr}>{escape(unit)}</option>')
    return "\n".join(options)


def _render_history(unit_names: list[str], selected: str) -> str:
    if not unit_names:
        return "Histórico da exploração: ainda vazio."
    if selected and selected in unit_names:
        return f"Histórico da exploração: {escape(selected)}"
    return f"Histórico da exploração: {escape(unit_names[0])}"


def _render_path_bar(
    *,
    source_display: str,
    selected_unit: str,
    action: str,
    focus_mode: bool,
    unit_names: list[str],
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    lang: str,
) -> str:
    selected = selected_unit or (unit_names[0] if unit_names else "")

    def _pill(label: str, href: str | None = None, active: bool = False) -> str:
        classes = "path-pill" + (" active" if active else "")
        content = escape(label)
        if href:
            return f'<a class="{classes}" href="{escape(href)}">{content}</a>'
        return f'<span class="{classes}">{content}</span>'

    crumbs: list[str] = []
    summary_query = {
        "source_type": source_type,
        "source_path": source_path,
        "columns": columns_text,
        "rows": rows_text,
        "prompt": prompt,
        "focus": "1" if focus_mode else "0",
        "lang": lang,
        "action": "summary",
    }
    crumbs.append(_pill(str(source_display or "Origem"), f"/?{urlencode(summary_query)}", active=not selected))
    if selected:
        detail_query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected,
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "tabela",
        }
        crumbs.append(_pill(selected, f"/?{urlencode(detail_query)}", active=selected == selected_unit))
    return (
        f'<nav class="path-bar"><span class="path-label">Caminho:</span>'
        + "".join(f"<span class=\"path-sep\">/</span>{crumb}" for crumb in crumbs)
        + "</nav>"
    )


def _render_layer_stack(
    *,
    action: str,
    persisted_to: str | None,
    focus_mode: bool,
    slice_mode: str,
    selected_value: str,
    lang: str,
) -> str:
    if action in {"quick", "tabela", "previous", "next", "tabular"}:
        current_layer = "tabela"
    elif action == "coluna":
        current_layer = "coluna"
    elif action == "valor":
        current_layer = "valor_celula"
    else:
        current_layer = "origem"
    if slice_mode == "new_base" and selected_value and action != "coluna":
        current_layer = "base"

    layers = [
        ("origem", "origem", "estado inicial"),
        ("base", "base", "nova base ativa"),
        ("tabela", "tabela", "estado tabular"),
        ("coluna", "Coluna", "estado de coluna"),
        ("recorte", "recorte", "decisão de aprofundamento"),
        ("valor_celula", "valor/célula", "estado de valor/célula"),
        ("caractere", "caractere", "estado de caractere"),
    ]

    items = []
    for key, label, hint in layers:
        active = " active" if key == current_layer else ""
        items.append(
            f'<span class="layer-pill{active}"><strong>{escape(label)}</strong><span>{escape(hint)}</span></span>'
        )
    focus_note = "<span class='small'>Foco ativo</span>" if focus_mode else "<span class='small'>Foco livre</span>"
    persistence_note = "<div class='small' style='margin-top: 8px;'>Persistência disponível</div>" if persisted_to else ""
    return (
        f'<section class="layers-bar"><div class="results-title">Estados da análise</div>'
        f'<div class="layers-row">{"".join(items)}</div>'
        f'<div class="small" style="margin-top: 8px;">{focus_note}</div>'
        f"{persistence_note}"
        f'</section>'
    )


def _render_action_controls(
    *,
    selected_unit: str,
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    focus_mode: bool,
    toggle_href: str,
    lang: str,
) -> str:
    def _href(action: str) -> str:
        query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": action,
        }
        return f"/?{urlencode(query)}"

    return f"""
      <section class="card action-panel">
        <div class="results-title">Calculadoras do core</div>
        <div class="small">Botões que acionam cálculos do core para a unidade selecionada.</div>
        <div class="action-grid">
          <a class="button" href="{escape(_href("quick"))}">Explorar rápido</a>
          <a class="button secondary" href="{escape(_href("tabela"))}">Analisar unidade</a>
          <a class="button secondary" href="{escape(_href("reset"))}">Limpar estado salvo</a>
          <a class="button secondary" href="{escape(toggle_href)}">{"Desativar modo foco" if focus_mode else "Ativar modo foco"}</a>
        </div>
        <div class="small" style="margin-top: 10px;">Unidade ativa: {escape(selected_unit or "—")}</div>
      </section>
    """


def _render_unit_shortcuts(
    unit_names: list[str],
    *,
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    focus_mode: bool,
    selected_unit: str,
    lang: str,
) -> str:
    if not unit_names:
        return '<div class="small">Nenhuma unidade selecionável carregada ainda.</div>'

    items = []
    for unit in unit_names[:8]:
        query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": unit,
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "tabela",
        }
        href = f"/?{urlencode(query)}"
        selected_class = "button" if unit == selected_unit else "button secondary"
        items.append(
            f'<a class="{selected_class}" style="margin-right: 8px; margin-top: 8px;" href="{escape(href)}">{escape(unit)}</a>'
        )
    if len(unit_names) > 8:
        items.append(f'<span class="small" style="margin-left: 4px;">+ {len(unit_names) - 8} mais</span>')
    return "".join(items)


def _render_unit_metrics(
    units: list[dict[str, Any]],
    unit_names: list[str],
    selected_unit: str,
    *,
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    focus_mode: bool,
    lang: str,
) -> str:
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

    ranked_units = sorted(units, key=lambda u: float(u.get("importance_score", 0) or 0), reverse=True)
    if not ranked_units:
        preview = []
        for name in unit_names[:6]:
            is_selected = " selected-metric" if name == selected_unit else ""
            preview.append(
                f"""
                <a class="metric-link" href="{escape(_detail_href(name))}">
                  <section class="metric-card{is_selected}">
                    <div class="metric-body">
                      <div class="metric-name">{escape(name)}</div>
                      <div class="metric-preview">Métricas pendentes</div>
                    </div>
                  </section>
                </a>
                """
            )
        if not preview:
            preview.append("""
                <section class="metric-card">
                  <div class="metric-body">
                    <div class="metric-name">—</div>
                    <div class="metric-preview">Métricas pendentes</div>
                  </div>
                </section>
                """)
        if len(unit_names) > 6:
            preview.append(f'<div class="small">+ {len(unit_names) - 6} unidades adicionais.</div>')
        return "".join(preview)

    blocks = []
    for unit in ranked_units[:9]:
        unit_name = str(unit.get("tabela_nome") or "")
        standardized = unit.get("standardized") or {}
        row_count = standardized.get("row_count")
        column_count = standardized.get("column_count")
        column_order = list(standardized.get("column_order") or [])
        columns_preview = ", ".join(str(item) for item in column_order[:3]) if column_order else ""
        meta_parts = []
        if row_count is not None:
            meta_parts.append(f"{row_count} linhas")
        if column_count is not None:
            meta_parts.append(f"{column_count} colunas")
        meta_html = f'<div class="metric-meta">{escape(" · ".join(meta_parts))}</div>' if meta_parts else ""
        detail_items = [columns_preview] if columns_preview else []
        details_html = (
            '<ul class="metric-list origin-card-list" style="margin-top: 8px;">'
            + "".join(f"<li>{escape(item)}</li>" for item in detail_items)
            + "</ul>"
            if detail_items
            else ""
        )
        selected_class = " selected-metric" if unit_name == selected_unit else ""
        blocks.append(
            f"""
            <a class="metric-link" href="{escape(_detail_href(unit_name))}">
              <section class="metric-card{selected_class}">
                <div class="metric-body">
                  <div class="metric-name">{escape(unit_name or "—")}</div>
                  {meta_html}
                  {details_html}
                  <div class="metric-action">Abrir exploração</div>
                </div>
              </section>
            </a>
            """
        )
    if len(ranked_units) > 9:
        blocks.append(f'<div class="small">+ {len(ranked_units) - 9} unidades adicionais.</div>')
    return "".join(blocks)


def _build_right_panel_audit_text(
    *,
    result: dict[str, Any] | None,
    source_display: str,
    overview_units: int,
    selected_unit: str,
    selected_column: str | None,
    jump_label: str | None,
    status_line: str,
    detail_mode: bool,
    column_mode: bool,
    unit_names: list[str],
) -> str:
    summary_mode = not detail_mode and not column_mode
    lines = [
        f"Origem: {source_display}",
        f"Unidades detectadas: {overview_units}",
    ]
    if summary_mode:
        lines.append("Escopo: origem")
    elif detail_mode:
        lines.append("Escopo: tabela")
    else:
        lines.append("Escopo: coluna")
    if selected_unit:
        lines.append(f"Unidade em foco: {selected_unit}")
    if selected_column:
        lines.append(f"Coluna em foco: {selected_column}")

    if result and result.get("origem"):
        source = result["origem"]
        technical_lines = []
        if source.get("source_type"):
            technical_lines.append(f"Tipo: {source['source_type']}")
        if source.get("source_identifier"):
            technical_lines.append(f"Caminho: {source['source_identifier']}")
        if source.get("connector_name"):
            connector = str(source.get("connector_name"))
            if source.get("connector_version"):
                connector = f"{connector} · {source['connector_version']}"
            technical_lines.append(f"Conector: {connector}")
        if source.get("fingerprint"):
            technical_lines.append(f"Fingerprint: {source['fingerprint']}")
        if technical_lines:
            lines.append("")
            lines.append("Contexto técnico:")
            lines.extend(f"- {line}" for line in technical_lines)

    if result and result.get("summary") and summary_mode:
        lines.append("")
        lines.append("Resumo:")
        lines.extend(str(result["summary"]).splitlines())

    if unit_names and summary_mode:
        lines.append("")
        lines.append(f"Lista completa de unidades: {', '.join(unit_names[:9])}")

    return "\n".join(lines).strip()


def _render_focused_unit(
    *,
    result: dict[str, Any] | None,
    selected_unit: str,
    lang: str,
) -> str:
    if not result:
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
    standardized = current.get("standardized") or {}
    unit_label = str(current.get("tabela_nome") or selected_unit or "—")
    row_count_raw = standardized.get("row_count")
    row_count = int(row_count_raw) if row_count_raw is not None else None
    column_count_raw = standardized.get("column_count")
    column_count = int(column_count_raw) if column_count_raw is not None else None

    lines = [f"<div class='origin-line'>Caminho: origem / {escape(unit_label)}</div>"]
    if row_count is not None:
        lines.append(f"<div class='origin-line'>Linhas: {row_count}</div>")
    if column_count is not None:
        lines.append(f"<div class='origin-line'>Colunas: {column_count}</div>")

    return f"""
      <div class="results-title">Contexto da tabela</div>
      <section class="origin-overview">
        {''.join(lines)}
      </section>
    """


def _render_focused_unit_columns(
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
    context_filters_text: str,
    exception_group: str,
    relation_column: str,
    relation_values_text: str,
    lang: str,
) -> str:
    if not result:
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
    if not columns:
        return '<div class="small">Nenhuma coluna disponível.</div>'

    column_cards = []
    for index, (column_name, column) in enumerate(columns.items(), start=1):
        layer1 = column.get("layer1_metrics") or {}
        cardinality = int(layer1.get("cardinality") or 0)
        null_ratio = float(layer1.get("null_ratio") or 0.0)
        unique_ratio = float(layer1.get("unique_ratio") or 0.0)
        signal_value_raw = column.get("signal")
        signal_value: float | None = None
        if isinstance(signal_value_raw, (int, float)):
            signal_value = max(0.0, min(float(signal_value_raw), 1.0))
        title_text = str(column_name or f"coluna {index}")
        if signal_value is not None:
            title_text = f"{title_text} ({signal_value:.2f})"

        query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "column_name": column_name,
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "coluna",
        }
        column_cards.append(
            f"""
            <a class="metric-link" href="{escape(f'/?{urlencode(query)}')}" aria-label="{escape(column_name)}">
            <article class="focus-column-card{(' selected-metric' if selected_column == column_name else '')}">
              <div class="focus-column-head">
                {render_card_header(
                    title=title_text,
                    occurrences=int(cardinality) if cardinality else None,
                    exploration_level=0.0,
                    can_add_to_collection=True,
                    can_share=True,
                    can_mark_seen=True,
                )}
              </div>
              <div class="focus-column-stat">nulos {null_ratio:.2f} · únicos {unique_ratio:.2f}</div>
              <div class="metric-action">Abrir coluna</div>
            </article>
            </a>
            """
        )

    return f"""
      <div class="focus-columns">{''.join(column_cards)}</div>
    """