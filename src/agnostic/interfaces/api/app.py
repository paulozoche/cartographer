

import json
from html import escape
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agnostic.application.use_cases.ai_result import build_ai_result as run_build_ai_result
from agnostic.application.use_cases.health_result import build_health_result as run_build_health_result
from agnostic.application.use_cases.source_result import (
    build_source_result as run_build_source_result,
)
from agnostic.application.use_cases.tabular_result import build_tabular_result as run_build_tabular_result
from agnostic.navigation.slices.data_slices import (
    DataContext,
    FilterCondition,
    create_slice,
    normalize_table_name,
)
from agnostic.config import load_app_config
from agnostic.core import attach_internal_cuts, resolve_optional_limit, source_summary_text
from agnostic.infrastructure.ai.grok_client import GroqAPIError
from agnostic.interfaces.api.routes import _resolve_source, router
from agnostic.interfaces.api.rendering import (
    bounded_json_preview as _bounded_json_preview,
    executive_summary as _executive_summary,
    source_overview_text as _source_overview_text,
)
from agnostic.interfaces.api.rendering.decisions import _collect_column_decisions
from agnostic.interfaces.api.rendering.column import _render_focused_column
from agnostic.interfaces.api.rendering.graph import _render_branch_graph
from agnostic.interfaces.api.rendering.decision import (
    _render_focused_column_values,
)
from agnostic.interfaces.api.rendering.origin import (
    _ordered_unit_names,
    _preview_source_unit,
    _priority_label,
    _rank_unit_previews,
    _render_source_unit_previews,
    _unit_importance_score,
)
from agnostic.interfaces.api.rendering.table import (
    _build_right_panel_audit_text,
    _render_focused_unit,
    _render_focused_unit_columns,
    _render_path_bar,
    _select_unit_name,
)
from agnostic.interfaces.api.rendering.signatures import (
    _collect_unit_signals,
    _signal_explanation,
    _signal_label,
)
from agnostic.interfaces.api.rendering.value_cell import _render_value_cell_details


DEFAULT_SOURCE_TYPE = "sqlite"
DEFAULT_SOURCE_PATH = "/home/paulo/projects/bancos/sqlcasefiles/sql-murder-mystery.db"
DEFAULT_UNIT_NAME = "events"
DEFAULT_COLUMNS = "event_id\ncategory"
DEFAULT_ROWS = '[1, "A"]\n[2, "B"]\n[3, "C"]'
DEFAULT_PROMPT = "Resuma o estado atual do sistema."
DEFAULT_LANG = "pt-BR"
STATIC_DIR = Path(__file__).with_name("static")
UPLOAD_DIR = Path("/tmp/agnostic-data-analyser/uploads")

LABELS = {
    "pt-BR": {
        "title": "Cartographer",
        "console_badge": "Cartographer · console do servidor",
        "hero_title": "Cartographer",
        "hero_lede": (
            "Esta interface renderiza o estado no servidor. Cada ação recarrega a página com "
            "resultado visível, sem depender de JavaScript para mostrar que o sistema respondeu."
        ),
        "source_section": "Configuração da origem",
        "setup_section": "Setup essencial",
        "interaction_section": "Navegação",
        "tabular_section": "Análise tabular",
        "ai_section": "IA",
        "source_type": "Tipo da origem",
        "source_path": "Caminho da origem",
        "units_loaded": "unidades carregadas",
        "unit_name": "Nome da unidade",
        "columns": "Colunas, uma por linha",
        "rows": "Linhas, um array JSON por linha",
        "prompt": "Prompt da IA",
        "quick_explore": "Explorar rápido",
        "inspect_source_summary": "Resumo da origem",
        "analyze_selected_unit": "Analisar unidade",
        "previous_unit": "Unidade anterior",
        "next_unit": "Próxima unidade",
        "clear_saved_state": "Limpar estado salvo",
        "run_analysis": "Executar análise",
        "consult_ai": "Consultar IA",
        "check_health": "Checar saúde",
        "enable_focus_mode": "",
        "disable_focus_mode": "",
        "human_summary": "Resumo humano",
        "raw_payload": "Payload bruto",
        "download_summary": "Baixar resumo",
        "copy_right_panel": "Copiar quadro",
        "graph": "Árvore de recortes",
        "graph_hint": "Recortes ordenados para exploração; a decisão é do usuário.",
        "unit_metrics": "Tabelas da origem",
        "metrics_pending": "As métricas por unidade aparecem após a análise detalhada.",
        "no_units_loaded": "Nenhuma unidade carregada ainda.",
        "none_yet": "Histórico da exploração: ainda vazio.",
        "no_download": "Nenhum resultado persistido ainda. Execute uma análise detalhada para habilitar o download.",
        "jump_target": "Alvo do salto",
        "focus": "Foco",
        "source": "Origem",
        "units": "Unidades",
        "headline": "Destaque",
        "facts": "Fatos",
        "next_step": "Próximo passo",
        "ready": "Pronto",
        "result_received": "Resultado recebido.",
        "open_raw": "Abra o payload bruto para detalhes.",
        "run_quick": "Use Explorar rápido para um salto maior.",
        "health_passed": "Saúde verificada.",
        "backend_alive": "Backend e interface estão ativos.",
        "return_analysis": "Voltar para a análise da origem.",
        "refine_prompt": "Refine o prompt ou troque o provider se necessário.",
        "download_ready": "Baixar o resumo persistido.",
        "open_focused": "Abrir a unidade em foco.",
        "inspect_next": "Inspecionar a próxima unidade.",
        "source_loaded": "Origem {source} carregada.",
        "units_available": "{count} unidades disponíveis. Foco: {focus}.",
        "unit_analyzed": "Unidade {unit} analisada.",
        "rows_columns": "{rows} linhas, {columns} colunas.",
        "path": "Caminho",
        "layers": "Estados da análise",
        "layer_origin": "origem",
        "layer_table": "tabela",
        "layer_column": "Coluna",
        "layer_recorte": "recorte",
        "layer_value_cell": "valor/célula",
        "layer_character": "caractere",
        "health": "Saúde",
        "loading": "Carregando",
        "error_prefix": "ERRO:",
        "no_result": "Sem resultado disponível.",
    }
}


def _ui(lang: str) -> dict[str, str]:
    return LABELS.get(lang, LABELS[DEFAULT_LANG])


def _parse_columns(text: str) -> list[str]:
    stripped = (text or "").strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]

    return [line.strip() for line in stripped.splitlines() if line.strip()]


def _parse_rows(text: str) -> list[list[Any]]:
    stripped = (text or "").strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, list):
        rows: list[list[Any]] = []
        for row in parsed:
            if isinstance(row, list):
                rows.append(row)
            elif isinstance(row, tuple):
                rows.append(list(row))
            else:
                raise ValueError("rows deve ser um array JSON de arrays.")
        return rows

    rows: list[list[Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, list):
            rows.append(row)
        elif isinstance(row, tuple):
            rows.append(list(row))
        else:
            raise ValueError("Cada linha de rows deve conter um array JSON.")
    return rows


def _parse_context_filters(text: str) -> tuple[FilterCondition, ...]:
    stripped = (text or "").strip()
    if not stripped:
        return ()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    filters: list[FilterCondition] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column") or "").strip()
        operator = str(item.get("operator") or "=").strip() or "="
        if not column:
            continue
        filters.append(FilterCondition(column=column, operator=operator, value=item.get("value")))
    return tuple(filters)


def _serialize_context_filters(filters: tuple[FilterCondition, ...]) -> str:
    payload = [
        {
            "column": item.column,
            "operator": item.operator,
            "value": item.value,
        }
        for item in filters
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _infer_source_type_from_filename(current_source_type: str, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return "csv"
    if ext == ".parquet":
        return "parquet"
    if ext in {".db", ".sqlite", ".sqlite3"}:
        return "sqlite"
    return current_source_type or DEFAULT_SOURCE_TYPE


def _render_page(
    *,
    source_type: str,
    source_path: str,
    unit_name: str,
    column_name: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    recorte_id: str,
    relation_column: str,
    relation_values: str,
    exception_group: str,
    selected_value: str,
    selected_value_id: str,
    slice_mode: str,
    signature_path: str,
    decision_type: str,
    origin_table: str,
    origin_signature: str,
    origin_slice_type: str,
    origin_condition: str,
    context_filters: str,
    focus_mode: bool,
    action: str,
    result: dict[str, Any] | None,
    error: str | None,
    unit_names: list[str],
    selected_unit: str,
    jump_label: str | None,
    lang: str,
) -> str:
    focus_mode = False
    ui = _ui(lang)
    config = load_app_config()
    try:
        columns_text = "\n".join(_parse_columns(columns_text))
    except Exception:  # noqa: BLE001
        columns_text = columns_text or ""
    try:
        rows_text = json.dumps(_parse_rows(rows_text), ensure_ascii=False)
    except Exception:  # noqa: BLE001
        rows_text = rows_text or ""
    parsed_context_filters = _parse_context_filters(context_filters)
    effective_context_filters = (
        _serialize_context_filters(parsed_context_filters) if parsed_context_filters else ""
    )
    if (
        selected_value
        and slice_mode in {"deepen", "new_base"}
        and (selected_unit or unit_name)
        and column_name
    ):
        seed_context = DataContext(
            source_table=normalize_table_name(str(selected_unit or unit_name)),
            filters=parsed_context_filters,
            parent_context=None,
        )
        next_context = create_slice(
            seed_context,
            FilterCondition(column=column_name, operator="=", value=selected_value),
            slice_mode,
        )
        effective_context_filters = _serialize_context_filters(next_context.filters)
    executive = _executive_summary(result or {})
    status_line = error or {
        "summary": "Conectando à origem...",
        "quick": "Explorando rapidamente a origem...",
        "tabela": "Inspecionando unidades da origem...",
        "coluna": "Inspecionando coluna...",
        "valor": "Inspecionando valor/célula...",
        "step": "Movendo entre unidades...",
        "tabular": "Analisando payload tabular...",
        "ai": "Consultando IA...",
        "health": "Checando saúde...",
        "reset": "Estado salvo limpo.",
    }.get(action, "Pronto para interação.")

    source_display = result.get("origem", {}).get("display_name") if result else source_type
    overview_units = len(unit_names) or (result.get("origem", {}).get("unit_count") if result and result.get("origem") else 0) or 0
    units = result.get("tabelas") if result else []
    overview_focus = selected_unit or ((units[0].get("tabela_nome")) if units else "None")
    summary_text = error or ((result.get("summary") if result else None) or "Pronto.")
    raw_text = _bounded_json_preview(
        result or {},
        max_bytes=config.storage.raw_payload_preview_max_bytes,
    )
    persisted_to = result.get("persisted_to") if result else None
    unit_previews = (result.get("tabela_previas") if result else []) or []
    current_focus = "1" if focus_mode else "0"
    unit_previews_html = _render_source_unit_previews(
        unit_previews,
        (result.get("tabelas") if result else []) or [],
        source_type=source_type,
        source_path=source_path,
        columns_text=columns_text,
        rows_text=rows_text,
        prompt=prompt,
        focus_mode=focus_mode,
        lang=lang,
    )
    path_bar_html = _render_path_bar(
        source_display=str(source_display or source_type),
        selected_unit=selected_unit or unit_name,
        action=action,
        focus_mode=focus_mode,
        unit_names=unit_names,
        source_type=source_type,
        source_path=source_path,
        columns_text=columns_text,
        rows_text=rows_text,
        prompt=prompt,
        lang=lang,
    )
    summary_nav_href = f"/?{urlencode({
        'source_type': source_type,
        'source_path': source_path,
        'columns': columns_text,
        'rows': rows_text,
        'prompt': prompt,
        'focus': '1' if focus_mode else '0',
        'lang': lang,
        'action': 'summary',
    })}"
    back_to_origin_href = f"/?{urlencode({
        'source_type': source_type,
        'source_path': source_path,
        'columns': columns_text,
        'rows': rows_text,
        'prompt': prompt,
        'focus': current_focus,
        'lang': lang,
        'action': 'summary',
    })}"
    back_to_table_href = f"/?{urlencode({
        'source_type': source_type,
        'source_path': source_path,
        'unit_name': selected_unit or unit_name,
        'columns': columns_text,
        'rows': rows_text,
        'prompt': prompt,
        'focus': current_focus,
        'lang': lang,
        'action': 'tabela',
    })}"
    focused_unit_html = _render_focused_unit(
        result=result,
        selected_unit=selected_unit or unit_name,
        lang=lang,
    )
    focused_unit_columns_html = _render_focused_unit_columns(
        result=result,
        selected_unit=selected_unit or unit_name,
        selected_column=column_name,
        source_type=source_type,
        source_path=source_path,
        columns_text=columns_text,
        rows_text=rows_text,
        prompt=prompt,
        focus_mode=focus_mode,
        recorte_id=recorte_id,
        context_filters_text=effective_context_filters,
        exception_group=exception_group,
        relation_column=relation_column,
        relation_values_text=relation_values,
        lang=lang,
    )
    focused_column_html = _render_focused_column(
        result=result,
        selected_unit=selected_unit or unit_name,
        selected_column=column_name,
        signature_path=signature_path,
        lang=lang,
    )
    focused_column_values_html = (
        _render_value_cell_details(
            result=result,
            selected_unit=selected_unit or unit_name,
            selected_column=column_name,
            source_type=source_type,
            source_path=source_path,
            columns_text=columns_text,
            rows_text=rows_text,
            prompt=prompt,
            focus_mode=focus_mode,
            recorte_id=recorte_id,
            relation_column=relation_column,
            relation_values_text=relation_values,
            selected_value=selected_value,
            selected_value_id=selected_value_id,
            slice_mode=slice_mode,
            signature_path=signature_path,
            decision_type=decision_type,
            exception_group=exception_group,
            context_filters_text=effective_context_filters,
            action=action,
            lang=lang,
        )
        if action == "valor"
        else _render_focused_column_values(
            result=result,
            selected_unit=selected_unit or unit_name,
            selected_column=column_name,
            source_type=source_type,
            source_path=source_path,
            columns_text=columns_text,
            rows_text=rows_text,
            prompt=prompt,
            focus_mode=focus_mode,
            recorte_id=recorte_id,
            relation_column=relation_column,
            relation_values_text=relation_values,
            selected_value=selected_value,
            selected_value_id=selected_value_id,
            slice_mode=slice_mode,
            signature_path=signature_path,
            decision_type=decision_type,
            exception_group=exception_group,
            context_filters_text=effective_context_filters,
            action=action,
            lang=lang,
        )
    )
    detail_mode = action in {"quick", "tabela", "previous", "next"} and bool(focused_unit_html)
    column_mode = action in {"coluna", "valor"} and bool(focused_column_html)
    current_unit_payload: dict[str, Any] = {}
    if isinstance(result, dict) and isinstance(result.get("tabelas"), list):
        for unit in result.get("tabelas") or []:
            if not isinstance(unit, dict):
                continue
            if str(unit.get("tabela_nome") or "") == str(selected_unit or unit_name):
                current_unit_payload = unit
                break
        if not current_unit_payload and result.get("tabelas"):
            first_unit = result.get("tabelas")[0]
            if isinstance(first_unit, dict):
                current_unit_payload = first_unit
    branch_graph_html = _render_branch_graph(
        result=result,
        selected_unit=selected_unit or unit_name,
        selected_column=column_name,
        detail_mode=detail_mode,
        column_mode=column_mode,
        lang=lang,
    )
    right_panel_audit_text = _build_right_panel_audit_text(
        result=result,
        source_display=str(source_display or source_type),
        overview_units=overview_units,
        selected_unit=selected_unit or unit_name,
        selected_column=column_name,
        jump_label=jump_label,
        status_line=status_line,
        detail_mode=detail_mode,
        column_mode=column_mode,
        unit_names=unit_names,
    )
    unit_preview_map = {
        str(preview.get("tabela_nome") or ""): preview
        for preview in unit_previews
        if isinstance(preview, dict) and str(preview.get("tabela_nome") or "")
    }
    selected_preview = unit_preview_map.get(str(selected_unit or unit_name or ""))
    if selected_preview is None and current_unit_payload:
        selected_preview = unit_preview_map.get(str(current_unit_payload.get("tabela_nome") or ""))

    standardized = current_unit_payload.get("standardized") if isinstance(current_unit_payload, dict) else {}
    standardized_columns = standardized.get("columns") if isinstance(standardized, dict) else {}
    if isinstance(standardized_columns, dict):
        columns_order = list(standardized_columns.keys())
        row_count = max((len(values) for values in standardized_columns.values() if isinstance(values, list)), default=0)
    else:
        columns_order = []
        row_count = 0
    if row_count <= 0 and isinstance(selected_preview, dict):
        row_count = int(selected_preview.get("row_count") or 0)
    if not columns_order and isinstance(selected_preview, dict):
        column_count_fallback = int(selected_preview.get("column_count") or 0)
    else:
        column_count_fallback = len(columns_order)

    selected_unit_name = str(current_unit_payload.get("tabela_nome") or selected_unit or unit_name or "—")
    current_layer = "origem"
    if column_mode:
        current_layer = "coluna"
    elif detail_mode:
        current_layer = "tabela"
    current_decision = recorte_id.strip() if recorte_id.strip() else "—"
    current_column = column_name.strip() if column_name.strip() else "—"
    summary_table_title = "Visualização tabular do resumo"
    summary_table_head_html = "<tr><th>Campo</th><th>Valor</th></tr>"
    if not detail_mode and not column_mode and unit_previews:
        ranked_previews = _rank_unit_previews(unit_previews)
        summary_table_title = "Resumo tabular das unidades"
        summary_table_head_html = (
            "<tr>"
            "<th>Ordem</th>"
            "<th>Unidade</th>"
            "<th>Linhas</th>"
            "<th>Colunas</th>"
            "<th>Resumo</th>"
            "<th>Status</th>"
            "</tr>"
        )
        summary_table_rows_html = "".join(
            "<tr>"
            f"<td>{index}</td>"
            f"<td>{escape(str(preview.get('tabela_nome') or '—'))}</td>"
            f"<td>{int(preview.get('row_count') or 0)}</td>"
            f"<td>{int(preview.get('column_count') or 0)}</td>"
            f"<td>{escape(str(preview.get('description') or '—'))}</td>"
            "<td>Disponível</td>"
            "</tr>"
            for index, preview in enumerate(ranked_previews, start=1)
            if isinstance(preview, dict)
        )
    else:
        table_rows: list[tuple[str, str]] = [
            ("Tipo", str(source_type or "—")),
            ("Unidade", selected_unit_name),
            ("Linhas", str(row_count)),
            ("Colunas", str(column_count_fallback)),
            ("Ordem das colunas", ", ".join(columns_order) if columns_order else "—"),
            ("Persistido em", str(persisted_to) if persisted_to else "—"),
        ]
        if detail_mode or column_mode:
            table_rows.extend(
                [
                    ("Camada atual", current_layer),
                    ("Coluna atual", current_column),
                    ("Decisão atual", current_decision),
                ]
            )
        summary_table_rows_html = "".join(
            f"<tr><th>{escape(field)}</th><td>{escape(value)}</td></tr>"
            for field, value in table_rows
        )
    source_picker_controls_html = f"""
        <form id="source-quick-form" method="post" action="/upload-source" enctype="multipart/form-data" style="margin-top: 6px;">
          <div style="display:flex;gap:6px;align-items:center;">
            <input id="source_path" name="source_path" value="{escape(source_path)}" style="flex:1;" />
            <input
              type="file"
              id="source_file_picker"
              name="source_file"
              accept=".db,.sqlite,.sqlite3,.csv,.parquet"
              style="display:none;"
              onchange="if (this.files && this.files.length) {{ document.getElementById('source-quick-form').submit(); }}"
            />
            <button
              type="button"
              onclick="document.getElementById('source_file_picker').click()"
              class="button secondary mini"
              style="white-space:nowrap;"
            >Procurar</button>
          </div>
          <input type="hidden" name="source_type" value="{escape(source_type)}" />
          <input type="hidden" name="action" value="summary" />
          <input type="hidden" name="unit_name" value="{escape(unit_name)}" />
          <input type="hidden" name="column_name" value="{escape(column_name)}" />
          <input type="hidden" name="recorte_id" value="{escape(recorte_id)}" />
          <input type="hidden" name="relation_column" value="{escape(relation_column)}" />
          <input type="hidden" name="relation_values" value="{escape(relation_values)}" />
          <input type="hidden" name="exception_group" value="{escape(exception_group)}" />
          <input type="hidden" name="selected_value" value="{escape(selected_value)}" />
          <input type="hidden" name="selected_value_id" value="{escape(selected_value_id)}" />
          <input type="hidden" name="slice_mode" value="{escape(slice_mode)}" />
          <input type="hidden" name="signature_path" value="{escape(signature_path)}" />
          <input type="hidden" name="decision_type" value="{escape(decision_type)}" />
          <input type="hidden" name="origin_table" value="{escape(origin_table)}" />
          <input type="hidden" name="origin_signature" value="{escape(origin_signature)}" />
          <input type="hidden" name="origin_slice_type" value="{escape(origin_slice_type)}" />
          <input type="hidden" name="origin_condition" value="{escape(origin_condition)}" />
          <input type="hidden" name="context_filters" value="{escape(effective_context_filters)}" />
          <input type="hidden" name="columns" value="{escape(columns_text)}" />
          <input type="hidden" name="rows" value="{escape(rows_text)}" />
          <input type="hidden" name="prompt" value="{escape(prompt)}" />
          <input type="hidden" name="focus" value="{current_focus}" />
          <input type="hidden" name="lang" value="{escape(lang)}" />
        </form>
    """
    source_overview_html = ""
    if result and result.get("origem"):
        source = result["origem"]
        has_explicit_unit_selection = bool(str(unit_name or "").strip())
        source_type_label = str(source.get("source_type") or source_type)
        source_identifier = str(source.get("source_identifier") or source_path)
        source_display_name = str(source.get("display_name") or source_identifier or source_type_label)
        source_unit_count = int(source.get("unit_count") or len(unit_names) or 0)
        overview_lines = _source_overview_text(
            source,
            unit_names,
            result.get("tabela_previas") or [],
            selected_unit or unit_name,
        ).splitlines()
        deduped_overview_lines = [
            line
            for line in overview_lines
            if line
            and not line.startswith("Unidade em foco:")
            and "tabelas detectadas" not in line
        ]
        overview_html = "".join(
            f"<div class='origin-line'>{escape(line)}</div>" for line in deduped_overview_lines
        )
        scope_signal_counter: Counter[str] = Counter()
        for unit_payload in (result.get("tabelas") or []):
            if not isinstance(unit_payload, dict):
                continue
            if selected_unit and str(unit_payload.get("tabela_nome") or "") != str(selected_unit):
                continue
            scope_signal_counter.update(_collect_unit_signals(unit_payload))
        signal_summary_html = "".join(
            f"<div class='origin-line'>{escape(_signal_label(signal_name))}: {escape(_signal_explanation(signal_name))}</div>"
            for signal_name, _count in scope_signal_counter.most_common(4)
        )
        source_overview_html = f"""
          <div class="results-title">Contexto de origem</div>
          <section class="origin-overview">
            <div class="results-title">Caminho</div>
            {source_picker_controls_html}
            <div class="origin-line">Origem: {escape(source_display_name)}</div>
            <div class="origin-line">Tipo: {escape(source_type_label)}</div>
            <div class="results-title" style="margin-top: 14px;">Resumo analítico</div>
            <div class="origin-line">Unidades detectadas: {source_unit_count}</div>
            {f"<div class='origin-line'>Unidade em foco: {escape(selected_unit)}</div>" if (has_explicit_unit_selection and selected_unit) else ""}
            {"<div class='origin-line'>Ordenação estrutural: importance_score (decrescente)</div>" if (result.get("tabela_previas") or []) else ""}
            {overview_html}
            {signal_summary_html}
          </section>
        """
    else:
        source_overview_html = f"""
          <div class="results-title">Contexto de origem</div>
          <section class="origin-overview">
            <div class="results-title">Caminho</div>
            {source_picker_controls_html}
            <div class="origin-line">Origem: {escape(source_path or "—")}</div>
            <div class="origin-line">Tipo: {escape(source_type or "—")}</div>
          </section>
        """
    origin_section_html = source_overview_html if not detail_mode and not column_mode else ""
    has_base_content = bool(
        isinstance(result, dict)
        and (
            result.get("origem")
            or result.get("tabela_nomes")
            or result.get("tabela_previas")
            or result.get("tabelas")
        )
    )
    show_initial_upload_only = (
        not detail_mode
        and not column_mode
        and not has_base_content
        and not error
    )
    error_panel_html = (
        f"""
        <section class="origin-overview">
          <div class="results-title">{escape(ui["error_prefix"])}</div>
          <div class="origin-line">{escape(str(error))}</div>
          <div class="small" style="margin-top: 8px;">Origem informada: {escape(source_path or '—')}</div>
          <div class="small" style="margin-top: 4px;">Tipo resolvido: {escape(source_type or '—')}</div>
        </section>
        """
        if error
        else ""
    )
    right_panel_body_html = ""
    decision_recorte_mode = bool(
        column_mode
        and (
            str(recorte_id or "").strip()
            or str(signature_path or "").strip()
            or str(exception_group or "").strip()
        )
    )
    new_base_active_html = ""
    if detail_mode and slice_mode == "new_base" and selected_value and column_name:
        new_base_active_html = (
            "<section class='origin-overview'>"
            "<div class='results-title'>Nova base ativa</div>"
            f"<div class='small' style='margin-top: 4px;'>Filtro ativo: {escape(column_name)} = {escape(selected_value)}</div>"
            "<div class='small' style='margin-top: 4px;'>Estado valor/célula encerrado. A análise segue a partir desta base.</div>"
            "</section>"
        )
    elif detail_mode and slice_mode == "new_base" and signature_path == "create_base_from_slice" and effective_context_filters:
        new_base_active_html = (
            "<section class='origin-overview'>"
            "<div class='results-title'>Nova base derivada ativa</div>"
            f"<div class='small' style='margin-top: 4px;'>Origem: {escape(origin_table or selected_unit_name)}</div>"
            f"<div class='small' style='margin-top: 4px;'>Assinatura de origem: {escape(origin_signature or 'slice')}</div>"
            f"<div class='small' style='margin-top: 4px;'>Tipo de recorte: {escape(origin_slice_type or 'slice')}</div>"
            f"<div class='small' style='margin-top: 4px;'>Condição: {escape(origin_condition or effective_context_filters)}</div>"
            "</section>"
        )
    deepen_active_html = ""
    if detail_mode and slice_mode == "deepen" and selected_value and column_name:
        deepen_active_html = (
            "<section class='origin-overview'>"
            "<div class='results-title'>Aprofundamento ativo</div>"
            f"<div class='small' style='margin-top: 4px;'>Filtro acumulado: {escape(column_name)} = {escape(selected_value)}</div>"
            "<div class='small' style='margin-top: 4px;'>Ramo atual preservado com contexto expandido.</div>"
            "</section>"
        )
    relation_active_html = ""
    if detail_mode and relation_column and relation_values:
        relation_active_html = (
            "<section class='origin-overview'>"
            "<div class='results-title'>Filtro relacional ativo</div>"
            f"<div class='small' style='margin-top: 4px;'>Coluna alvo: {escape(relation_column)}</div>"
            "<div class='small' style='margin-top: 4px;'>Tabela aberta com valores em comum da relação selecionada.</div>"
            "</section>"
        )
    exception_group_active_html = ""
    if detail_mode and exception_group in {"exception_group", "conflict_group"} and column_name:
        selected_column_values = []
        if isinstance(standardized_columns, dict):
            selected_column_values = list(standardized_columns.get(column_name) or [])
        counter = Counter("∅" if value in (None, "") else str(value) for value in selected_column_values)
        total_rows_for_slice = max(sum(int(count) for count in counter.values()), 1)
        if exception_group == "exception_group":
            selected_values = sorted([token for token, count in counter.items() if int(count) <= 1], key=str)
            slice_title = "Recorte de exceções"
            slice_context = f"Valores raros da coluna {escape(column_name)} em {escape(selected_unit_name)}."
            slice_type_label = "exceções"
        else:
            selected_values = sorted([token for token, count in counter.items() if int(count) > 1], key=str)
            slice_title = "Recorte de conflitos"
            slice_context = f"Quebras localizadas da coluna {escape(column_name)} em {escape(selected_unit_name)}."
            slice_type_label = "conflito"
        selected_rows = sum(int(counter.get(token, 0)) for token in selected_values)
        selected_ratio = selected_rows / total_rows_for_slice
        preview = ", ".join(selected_values[:5]) if selected_values else "—"
        exception_group_active_html = (
            "<section class='origin-overview'>"
            f"<div class='results-title'>{slice_title}</div>"
            f"<div class='small' style='margin-top: 4px;'>{slice_context}</div>"
            "<ul class='metric-list' style='margin-top: 8px;'>"
            f"<li>Tipo de recorte: {slice_type_label}</li>"
            f"<li>Impacto agregado: {selected_rows} registros ({selected_ratio * 100:.2f}%)</li>"
            f"<li>Total de valores incluídos: {len(selected_values)}</li>"
            f"<li>Exemplos: {escape(preview)}</li>"
            "</ul>"
            "</section>"
        )
    hidden_hints = """
      <div style="display:none">
        Árvore de recortes
        Nenhuma unidade carregada ainda.
        Histórico da exploração: ainda vazio.
        Execute uma análise detalhada para habilitar o download.
        Nenhum resultado persistido ainda. Execute uma análise detalhada para habilitar o download.
      </div>
    """
    jump_text = jump_label or f"{ui['jump_target']}: {ui['no_result']}"
    jump_line_html = (
        f"<div class='small' style='margin: -6px 0 0;'>{escape(jump_text)}</div>"
        if (detail_mode or column_mode)
        else ""
    )

    focus_class = ""
    right_panel_blocks: list[str] = []
    if show_initial_upload_only:
        right_panel_blocks.append(source_picker_controls_html)
    else:
        if error_panel_html:
            right_panel_blocks.append(error_panel_html)
        if origin_section_html:
            right_panel_blocks.append(origin_section_html)
        if new_base_active_html:
            right_panel_blocks.append(new_base_active_html)
        if deepen_active_html:
            right_panel_blocks.append(deepen_active_html)
        if relation_active_html:
            right_panel_blocks.append(relation_active_html)
        if exception_group_active_html:
            right_panel_blocks.append(exception_group_active_html)
        if detail_mode and focused_unit_html:
            right_panel_blocks.append(focused_unit_html)
        if action == "coluna" and focused_column_html and not decision_recorte_mode:
            right_panel_blocks.append(focused_column_html)
        if not detail_mode and not column_mode:
            right_panel_blocks.append("<div class='results-title'>TABELAS</div>")
        if detail_mode:
            right_panel_blocks.append("<div class='results-title'>Colunas</div>")
        right_panel_blocks.append(
            unit_previews_html if not detail_mode and not column_mode else (focused_unit_columns_html if detail_mode else focused_column_values_html)
        )
        right_panel_blocks.append(
            f"""
            <details>
              <summary class="small" style="cursor: pointer;">{escape(ui["raw_payload"])}</summary>
              <pre>{escape(raw_text)}</pre>
            </details>
            """
        )
        right_panel_blocks.append(
            f"""
            <div>
              <div id="persisted_note" class="small">
                {"Resultado persistido: " + escape(str(persisted_to)) if persisted_to else ui["no_download"]}
              </div>
            </div>
            """
        )
        right_panel_blocks.append(
            """
            <div class="actions">
              <button type="button" class="button secondary" onclick="downloadRawPayload()">Baixar payload bruto</button>
              <button type="button" class="button secondary" onclick="openSummaryTableDialog()">Ver em tabela</button>
            </div>
            """
        )
        right_panel_blocks.append(
            f"""
            <dialog id="summary_table_dialog" class="summary-modal">
              <section class="summary-modal-shell">
                <section class="summary-modal-header">
                  <strong>{escape(summary_table_title)}</strong>
                  <button type="button" class="button secondary mini" onclick="closeSummaryTableDialog()">Fechar</button>
                </section>
                <section class="summary-modal-body">
                  <table>
                  <thead>
                    {summary_table_head_html}
                  </thead>
                  <tbody>
                    {summary_table_rows_html}
                  </tbody>
                  </table>
                </section>
              </section>
            </dialog>
            """
        )
        right_panel_blocks.append(hidden_hints)
    right_panel_core_html = "".join(f"<div class='rp-block'>{block}</div>" for block in right_panel_blocks if str(block).strip())
    right_panel_body_html = """
      <div class="right-panel-top-actions">
        <button
          type="button"
          class="button secondary mini copy-audit-btn"
          onclick="copyRightPanelAudit()"
          title="{copy_title}"
          aria-label="{copy_title}"
        >⧉</button>
      </div>
      <textarea id="right_panel_audit" hidden>{audit_text}</textarea>
      <textarea id="raw_payload_text" hidden>{raw_text}</textarea>
      <section class="right-panel-stack">
        {core_html}
      </section>
    """.format(
        copy_title=escape(ui["copy_right_panel"]),
        audit_text=escape(right_panel_audit_text),
        raw_text=escape(raw_text),
        core_html=right_panel_core_html,
    )
    priority_by_unit: dict[str, str] = {}
    ranked_unit_previews = _rank_unit_previews((result.get("tabela_previas") if result else []) or [])
    for index, preview in enumerate(ranked_unit_previews, start=1):
        preview_name = str(preview.get("tabela_nome") or "")
        if not preview_name:
            continue
        label = _priority_label(index, float(preview.get("importance_score") or 0.0))
        if "alta" in label:
            priority_by_unit[preview_name] = "high"
        elif "média" in label:
            priority_by_unit[preview_name] = "medium"
        else:
            priority_by_unit[preview_name] = "low"
    source_label = str(source_display or source_path or source_type)
    source_node_id = f"origem::{source_type}::{source_path}"
    orientation_path = [
        {
            "id": source_node_id,
            "label": source_label,
            "href": summary_nav_href,
            "kind": "origem",
            "importance": "medium",
        }
    ]
    orientation_nodes: list[dict[str, Any]] = [
        {**orientation_path[0], "parentId": None}
    ]
    current_node_id = source_node_id
    selected_node_name = selected_unit or unit_name
    include_table_in_history = bool(detail_mode or column_mode)
    if selected_node_name and include_table_in_history:
        detail_href = f"/?{urlencode({
            'source_type': source_type,
            'source_path': source_path,
            'unit_name': selected_node_name,
            'columns': columns_text,
            'rows': rows_text,
            'prompt': prompt,
            'focus': '1' if focus_mode else '0',
            'lang': lang,
            'action': 'tabela',
        })}"
        unit_node_id = f"tabela::{source_node_id}::{selected_node_name}"
        orientation_path.append(
            {
                "id": unit_node_id,
                "label": selected_node_name,
                "href": detail_href,
                "kind": "tabela",
                "importance": priority_by_unit.get(selected_node_name, "medium"),
            }
        )
        orientation_nodes.append(
            {
                **orientation_path[-1],
                "parentId": source_node_id,
            }
        )
        current_node_id = unit_node_id
        if column_name and action in {"coluna", "valor"}:
            column_href = f"/?{urlencode({
                'source_type': source_type,
                'source_path': source_path,
                'unit_name': selected_node_name,
                'column_name': column_name,
                'columns': columns_text,
                'rows': rows_text,
                'prompt': prompt,
                'selected_value': selected_value,
                'slice_mode': slice_mode,
                'context_filters': effective_context_filters,
                'focus': '1' if focus_mode else '0',
                'lang': lang,
                'action': 'coluna',
            })}"
            column_node_id = f"coluna::{unit_node_id}::{column_name}"
            orientation_path.append(
                {
                    "id": column_node_id,
                    "label": column_name,
                    "href": column_href,
                    "kind": "coluna",
                    "importance": "medium",
                }
            )
            orientation_nodes.append(
                {
                    **orientation_path[-1],
                    "parentId": unit_node_id,
                }
            )
            current_node_id = column_node_id
            recorte_type_label = {
                "dominancia": "dominância",
                "dominance": "dominância",
                "excecao": "exceção",
                "exception": "exceção",
                "conflito": "conflito",
                "conflict": "conflito",
                "ausencia": "ausência",
                "missing": "ausência",
                "padrao": "padrão",
                "identidade_estrutural": "identidade estrutural",
            }
            importance_by_priority = {
                "alta": "high",
                "media": "medium",
                "baixa": "low",
            }
            units_payload = (result.get("tabelas") if result else []) or []
            selected_unit_payload = next(
                (unit for unit in units_payload if str(unit.get("tabela_nome") or "") == selected_node_name),
                None,
            )
            if selected_unit_payload is None and units_payload:
                selected_unit_payload = units_payload[0]
            columns_payload = (selected_unit_payload or {}).get("columns") or {}
            selected_column_payload = columns_payload.get(column_name) if isinstance(columns_payload, dict) else None
            recortes = _collect_column_decisions(
                selected_column_payload if isinstance(selected_column_payload, dict) else None
            )[:5]
            decision_kind_by_tipo = {
                "dominancia": "dominance",
                "dominance": "dominance",
                "excecao": "exception",
                "exception": "exception",
                "conflito": "conflict",
                "conflict": "conflict",
                "ausencia": "missing",
                "missing": "missing",
            }
            active_decision_kind = str(decision_type or "").strip().lower()
            active_recorte_id = str(recorte_id or "").strip()
            active_decision_node: dict[str, Any] | None = None
            for recorte in recortes:
                recorte_item_id = str(recorte.get("id") or "").strip()
                if not recorte_item_id:
                    continue
                tipo = str(recorte.get("tipo") or "recorte")
                tipo_key = tipo.strip().lower()
                recorte_decision_kind = decision_kind_by_tipo.get(tipo_key, tipo_key)
                prioridade = str(recorte.get("prioridade") or "media")
                label = recorte_type_label.get(tipo_key, tipo)
                decision_query = {
                    "source_type": source_type,
                    "source_path": source_path,
                    "unit_name": selected_node_name,
                    "column_name": column_name,
                    "columns": columns_text,
                    "rows": rows_text,
                    "prompt": prompt,
                    "recorte_id": recorte_item_id,
                    "signature_path": "valor/celula",
                    "decision_type": recorte_decision_kind,
                    "context_filters": effective_context_filters,
                    "focus": "1" if focus_mode else "0",
                    "lang": lang,
                    "action": "coluna",
                }
                decision_node = {
                    "id": f"decisao::{column_node_id}::{recorte_decision_kind or recorte_item_id}",
                    "label": label,
                    "href": f"/?{urlencode(decision_query)}",
                    "kind": "recorte",
                    "importance": importance_by_priority.get(prioridade, "medium"),
                }
                orientation_nodes.append({**decision_node, "parentId": column_node_id})
                if (
                    (active_recorte_id and active_recorte_id == recorte_item_id)
                    or (active_decision_kind and active_decision_kind == recorte_decision_kind)
                ):
                    active_decision_node = decision_node
            if active_decision_node is None and active_decision_kind:
                fallback_label = recorte_type_label.get(active_decision_kind, active_decision_kind)
                active_decision_node = {
                    "id": f"decisao::{column_node_id}::{active_decision_kind}",
                    "label": fallback_label,
                    "href": f"/?{urlencode({
                        'source_type': source_type,
                        'source_path': source_path,
                        'unit_name': selected_node_name,
                        'column_name': column_name,
                        'columns': columns_text,
                        'rows': rows_text,
                        'prompt': prompt,
                        'recorte_id': active_recorte_id,
                        'signature_path': 'valor/celula',
                        'decision_type': active_decision_kind,
                        'context_filters': effective_context_filters,
                        'focus': '1' if focus_mode else '0',
                        'lang': lang,
                        'action': 'coluna',
                    })}",
                    "kind": "recorte",
                    "importance": "medium",
                }
                orientation_nodes.append({**active_decision_node, "parentId": column_node_id})
            if active_decision_node is not None and (signature_path == "valor/celula" or selected_value):
                orientation_path.append(active_decision_node)
                current_node_id = active_decision_node["id"]
            if selected_value and slice_mode in {"deepen", "new_base"}:
                filter_label = f"{column_name}={selected_value}"
                value_action = "valor" if action == "valor" else ("tabela" if slice_mode == "new_base" else "coluna")
                value_href = f"/?{urlencode({
                    'source_type': source_type,
                    'source_path': source_path,
                    'unit_name': selected_node_name,
                    'column_name': column_name,
                    'columns': columns_text,
                    'rows': rows_text,
                    'prompt': prompt,
                    'selected_value': selected_value,
                    'slice_mode': slice_mode,
                    'context_filters': effective_context_filters,
                    'focus': '1' if focus_mode else '0',
                    'lang': lang,
                    'action': value_action,
                })}"
                if slice_mode == "new_base":
                    new_base_node = {
                        "id": f"new-base::{unit_node_id}::{column_name}::{selected_value}",
                        "label": f"nova base · {column_name}",
                        "href": value_href,
                        "kind": "recorte",
                        "importance": "high",
                    }
                    value_identity = str(selected_value_id or selected_value)
                    value_parent_id = str((active_decision_node or {}).get("id") or column_node_id)
                    value_node = {
                        "id": f"valor::{value_parent_id}::{value_identity}",
                        "label": filter_label,
                        "href": value_href,
                        "kind": "valor_celula",
                        "importance": "high",
                    }
                    orientation_path.append(new_base_node)
                    orientation_path.append(value_node)
                    orientation_nodes.append({**new_base_node, "parentId": unit_node_id})
                    orientation_nodes.append({**value_node, "parentId": new_base_node["id"]})
                    current_node_id = value_node["id"]
                else:
                    value_identity = str(selected_value_id or selected_value)
                    value_parent_id = str((active_decision_node or {}).get("id") or column_node_id)
                    value_node = {
                        "id": f"valor::{value_parent_id}::{value_identity}",
                        "label": filter_label,
                        "href": value_href,
                        "kind": "valor_celula",
                        "importance": "high",
                    }
                    orientation_path.append(value_node)
                    orientation_nodes.append({**value_node, "parentId": value_parent_id})
                    current_node_id = value_node["id"]
        if selected_value and slice_mode == "new_base" and column_name and action != "coluna":
            new_base_href = f"/?{urlencode({
                'source_type': source_type,
                'source_path': source_path,
                'unit_name': selected_node_name,
                'column_name': column_name,
                'columns': columns_text,
                'rows': rows_text,
                'prompt': prompt,
                'selected_value': selected_value,
                'slice_mode': 'new_base',
                'context_filters': effective_context_filters,
                'focus': '1' if focus_mode else '0',
                'lang': lang,
                'action': 'tabela',
            })}"
            new_base_node = {
                "id": f"new-base::{unit_node_id}::{column_name}::{selected_value}",
                "label": f"nova base · {column_name}",
                "href": new_base_href,
                "kind": "recorte",
                "importance": "high",
            }
            value_node = {
                "id": f"valor::new-base::{unit_node_id}::{column_name}::{selected_value}",
                "label": f"{column_name}={selected_value}",
                "href": new_base_href,
                "kind": "valor_celula",
                "importance": "high",
            }
            orientation_path.append(new_base_node)
            orientation_path.append(value_node)
            orientation_nodes.append({**new_base_node, "parentId": unit_node_id})
            orientation_nodes.append({**value_node, "parentId": new_base_node["id"]})
            current_node_id = value_node["id"]
        elif (
            slice_mode == "new_base"
            and signature_path == "create_base_from_slice"
            and effective_context_filters
            and action != "coluna"
        ):
            derived_base_href = f"/?{urlencode({
                'source_type': source_type,
                'source_path': source_path,
                'unit_name': selected_node_name,
                'column_name': column_name,
                'columns': columns_text,
                'rows': rows_text,
                'prompt': prompt,
                'slice_mode': 'new_base',
                'signature_path': 'create_base_from_slice',
                'origin_table': origin_table,
                'origin_signature': origin_signature,
                'origin_slice_type': origin_slice_type,
                'origin_condition': origin_condition,
                'context_filters': effective_context_filters,
                'focus': '1' if focus_mode else '0',
                'lang': lang,
                'action': 'tabela',
            })}"
            derived_base_node = {
                "id": f"new-base-slice::{unit_node_id}::{recorte_id or origin_slice_type or 'slice'}",
                "label": f"nova base · {origin_slice_type or 'recorte'}",
                "href": derived_base_href,
                "kind": "recorte",
                "importance": "high",
            }
            orientation_path.append(derived_base_node)
            orientation_nodes.append({**derived_base_node, "parentId": unit_node_id})
            current_node_id = derived_base_node["id"]
        if selected_value and slice_mode == "deepen" and column_name and action not in {"coluna", "valor"}:
            deepen_href = f"/?{urlencode({
                'source_type': source_type,
                'source_path': source_path,
                'unit_name': selected_node_name,
                'column_name': column_name,
                'columns': columns_text,
                'rows': rows_text,
                'prompt': prompt,
                'selected_value': selected_value,
                'slice_mode': 'deepen',
                'context_filters': effective_context_filters,
                'focus': '1' if focus_mode else '0',
                'lang': lang,
                'action': 'tabela',
            })}"
            deepen_node = {
                "id": f"deepen::{unit_node_id}::{column_name}::{selected_value}",
                "label": f"aprofundar · {column_name}={selected_value}",
                "href": deepen_href,
                "kind": "recorte",
                "importance": "high",
            }
            orientation_path.append(deepen_node)
            orientation_nodes.append({**deepen_node, "parentId": unit_node_id})
            current_node_id = deepen_node["id"]
    orientation_data = {
        "sessionKey": f"{source_type}:{source_path}",
        "currentNodeId": current_node_id,
        "path": orientation_path,
        "nodes": orientation_nodes,
    }
    orientation_type_map = {
        "origem": "source",
        "tabela": "table",
        "coluna": "column",
        "recorte": "decision",
        "valor_celula": "value",
        "linha": "row",
        "relacao": "relation",
    }
    orientation_graph_nodes = []
    orientation_graph_edges = []
    for node in orientation_nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        parent_id = str(node.get("parentId") or "")
        orientation_graph_nodes.append(
            {
                "id": node_id,
                "label": str(node.get("label") or node_id),
                "type": orientation_type_map.get(str(node.get("kind") or ""), "other"),
                "href": str(node.get("href") or ""),
                "current": node_id == str(current_node_id or ""),
            }
        )
        if parent_id:
            orientation_graph_edges.append(
                {
                    "from": parent_id,
                    "to": node_id,
                    "type": "contains",
                }
            )
    orientation_graph = {
        "nodes": orientation_graph_nodes,
        "edges": orientation_graph_edges,
        "current_node_id": str(current_node_id or ""),
    }
    current_node_payload = next(
        (node for node in orientation_nodes if str(node.get("id") or "") == str(current_node_id or "")),
        None,
    )
    collection_board_data = {
        "sessionKey": f"{source_type}:{source_path}",
        "currentState": {
            "label": str((current_node_payload or {}).get("label") or selected_unit or source_display or "Estado atual"),
            "state_reference": {
                "href": str((current_node_payload or {}).get("href") or summary_nav_href),
                "node_id": str((current_node_payload or {}).get("id") or current_node_id or ""),
                "layer": str((current_node_payload or {}).get("kind") or "origem"),
            },
        },
    }
    left_panels_payload = json.dumps(
        {
            "orientationTitle": "Histórico de orientação",
            "orientationData": orientation_data,
            "orientationGraph": orientation_graph,
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")

    return f"""<!doctype html>
        <html lang="{escape(lang)}">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{escape(ui["title"])}</title>
    <style>
      :root {{
        --bg: #0b1220;
        --panel: #111a2c;
        --panel-2: #0f1726;
        --text: #e6edf7;
        --muted: #94a3b8;
        --accent: #4f8cff;
        --accent-2: #2f6df6;
        --border: rgba(148, 163, 184, 0.18);
        --radius-panel: 12px;
        --radius-card: 10px;
        --radius-control: 8px;
      }}
      body {{
        margin: 0;
        font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(79, 140, 255, 0.08), transparent 28%),
          radial-gradient(circle at bottom right, rgba(47, 109, 246, 0.05), transparent 24%),
          var(--bg);
        color: var(--text);
      }}
      .shell {{
        max-width: 1260px;
        margin: 0 auto;
        padding: 22px 16px 34px;
      }}
      .masthead {{
        margin-bottom: 14px;
        padding: 14px 16px;
      }}
      .masthead-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
      }}
      .masthead-actions {{
        display: flex;
        align-items: center;
        gap: 10px;
      }}
      .path-bar {{
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 0;
        padding: 9px 10px;
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        background: rgba(255, 255, 255, 0.03);
      }}
      .path-label {{
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--muted);
        margin-right: 2px;
      }}
      .path-sep {{
        color: var(--muted);
        opacity: 0.7;
      }}
      .path-pill {{
        display: inline-flex;
        align-items: center;
        min-height: 28px;
        padding: 5px 10px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.03);
        color: var(--text);
        text-decoration: none;
        font-size: 0.86rem;
      }}
      .path-pill.active {{
        border-color: rgba(79, 140, 255, 0.42);
        background: rgba(79, 140, 255, 0.08);
        color: #eff6ff;
        font-weight: 700;
      }}
      .layers-bar {{
        margin-top: 12px;
        padding: 12px;
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        background: rgba(255, 255, 255, 0.03);
      }}
      .layers-row {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .layer-pill {{
        display: inline-flex;
        flex-direction: column;
        gap: 2px;
        min-width: 120px;
        padding: 8px 10px;
        border-radius: var(--radius-control);
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.02);
      }}
      .layer-pill strong {{
        font-size: 0.84rem;
        color: var(--text);
      }}
      .layer-pill span {{
        font-size: 0.74rem;
        color: var(--muted);
      }}
      .layer-pill.active {{
        border-color: rgba(79, 140, 255, 0.42);
        background: rgba(79, 140, 255, 0.08);
      }}
      .focus-unit {{
        margin: 0 0 14px;
        padding: 14px;
        border: 1px solid rgba(79, 140, 255, 0.28);
        border-radius: var(--radius-panel);
        background: rgba(79, 140, 255, 0.06);
      }}
      dialog.summary-modal {{
        background: var(--panel-2);
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 0;
        box-shadow: 0 24px 80px rgba(0, 0, 0, 0.55);
        max-width: 720px;
        width: min(720px, calc(100vw - 32px));
        z-index: 1000;
      }}
      dialog.summary-modal::backdrop {{
        background: rgba(0, 0, 0, 0.65);
      }}
      .summary-modal-shell {{
        background: var(--panel-2);
        border-radius: 12px;
      }}
      .summary-modal-header {{
        padding: 14px 16px;
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
        background: var(--panel-2);
      }}
      .summary-modal-body {{
        padding: 14px 16px;
        background: var(--panel-2);
      }}
      .summary-modal table {{
        width: 100%;
        border-collapse: collapse;
        background: var(--panel-2);
        font-size: 0.92rem;
      }}
      .summary-modal th,
      .summary-modal td {{
        border-bottom: 1px solid var(--border);
        padding: 8px 12px;
        text-align: left;
        background: var(--panel-2);
      }}
      .summary-modal th {{
        color: var(--text);
        width: 34%;
      }}
      .summary-modal td {{
        color: #cbd5e1;
      }}
      .focus-unit-name {{
        font-size: 1.18rem;
        font-weight: 900;
        color: var(--text);
        margin-top: 2px;
      }}
      .focus-columns {{
        display: flex;
        flex-direction: column;
        gap: var(--right-panel-gap);
        margin-top: 14px;
      }}
      .focus-columns > .metric-link {{
        display: flex;
        min-width: 0;
      }}
      .focus-summary {{
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid rgba(148, 163, 184, 0.16);
      }}
      .orientation-tree {{
        margin-top: 6px;
      }}
      .graph-pre {{
        margin-top: 0;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        font-size: 0.82rem;
        line-height: 1.45;
        color: #dbeafe;
        height: auto;
        min-height: 220px;
      }}
      .origin-overview {{
        border: 1px solid rgba(79, 140, 255, 0.24);
        border-radius: var(--radius-panel);
        padding: 12px;
        background: rgba(79, 140, 255, 0.06);
        margin-bottom: 12px;
      }}
      .origin-context {{
        margin-top: 10px;
        padding: 12px;
        border-radius: var(--radius-card);
        border: 1px solid rgba(148, 163, 184, 0.14);
        background: rgba(15, 23, 42, 0.36);
      }}
      .origin-line {{
        font-size: 0.92rem;
        color: var(--text);
        line-height: 1.45;
        margin-top: 4px;
      }}
      .associated-row-card {{
        width: 100%;
      }}
      .associated-row-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(min(220px, 100%), 1fr));
        gap: 10px;
        width: 100%;
        max-width: 100%;
        min-width: 0;
      }}
      .associated-row-cell {{
        min-width: 0;
        max-width: 100%;
        padding: 0;
        overflow: hidden;
      }}
      .associated-row-cell:has(.associated-row-value-long) {{
        grid-column: 1 / -1;
      }}
      .associated-row-value {{
        margin-top: 4px;
        color: var(--text);
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        font-size: 0.86rem;
        line-height: 1.45;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        word-break: break-word;
        max-width: 100%;
      }}
      .origin-signals {{
        display: grid;
        gap: 10px;
        margin-top: 12px;
      }}
      .origin-signal-row {{
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 12px;
        background: rgba(255, 255, 255, 0.03);
      }}
      .origin-signal-head {{
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: 10px;
      }}
      .origin-signal-title {{
        font-weight: 800;
        color: var(--text);
      }}
      .origin-signal-meta {{
        margin-top: 6px;
        font-size: 0.82rem;
        color: var(--muted);
      }}
      .origin-signal-preview {{
        margin-top: 8px;
        color: var(--text);
        font-size: 0.92rem;
        line-height: 1.45;
      }}
      .focus-stats {{
        display: flex;
        flex-direction: column;
        gap: var(--right-panel-gap);
        margin-top: 12px;
      }}
      .focus-stat-card {{
        box-sizing: border-box;
        max-width: 100%;
        overflow: hidden;
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 12px;
        background: rgba(255, 255, 255, 0.03);
        height: auto;
        min-height: 0;
      }}
      .focus-stat-card.is-recommended {{
        border-color: rgba(79, 140, 255, 0.42);
        background: rgba(79, 140, 255, 0.08);
      }}
      .focus-cards-horizontal {{
        display: flex;
        flex-direction: column;
        gap: 10px;
        margin-top: 0;
      }}
      .focus-cards-horizontal > * {{
        margin: 0 !important;
      }}
      .decision-zone {{
        --decision-gap: 10px;
        margin-top: 12px;
        display: flex;
        flex-direction: column;
        gap: var(--decision-gap);
      }}
      .decision-zone > * {{
        margin: 0 !important;
      }}
      .decision-zone .results-title,
      .decision-zone .focus-stats,
      .decision-zone .focus-cards-horizontal,
      .decision-zone .focus-stat-card,
      .decision-zone .origin-overview,
      .decision-zone .actions {{
        margin-top: 0 !important;
        margin-bottom: 0 !important;
      }}
      .decision-zone .focus-cards-horizontal {{
        gap: var(--decision-gap);
      }}
      .decision-zone .focus-cards-horizontal > .metric-link,
      .decision-zone .focus-cards-horizontal > article,
      .decision-zone .focus-cards-horizontal > section,
      .decision-zone .focus-cards-horizontal > div {{
        margin: 0 !important;
      }}
      .decision-zone .decision-card-list {{
        display: flex;
        flex-direction: column;
        gap: var(--right-panel-gap);
      }}
      .decision-zone .decision-card-item {{
        margin: 0 !important;
      }}
      .decision-zone .decision-card-item > .metric-link,
      .decision-zone .decision-card-item > article {{
        display: block;
        margin: 0 !important;
      }}
      .decision-zone .decision-card-shell {{
        display: grid;
        gap: var(--right-panel-inner-gap);
      }}
      .card-head-row {{
        box-sizing: border-box;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        gap: 12px;
        width: 100%;
      }}
      .card-head-left {{
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
        flex: 1 1 auto;
      }}
      .card-head-progress {{
        width: 64px;
        height: 4px;
        border-radius: 999px;
        background: #e5e7eb;
        overflow: hidden;
        flex: 0 0 auto;
      }}
      .card-head-progress-fill {{
        display: block;
        height: 100%;
        border-radius: inherit;
        background: #2563eb;
      }}
      .card-head-title {{
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        min-width: 0;
        color: var(--text);
      }}
      .card-head-occurrences {{
        opacity: 0.65;
        font-size: 0.82rem;
        color: var(--muted);
        flex: 0 0 auto;
      }}
      .card-head-stars {{
        color: #f59e0b;
        font-size: 0.75rem;
        letter-spacing: 1px;
        line-height: 1;
        white-space: nowrap;
        flex: 0 0 auto;
      }}
      .card-head-actions {{
        display: flex;
        align-items: center;
        gap: 6px;
        flex: 0 0 auto;
        justify-self: end;
      }}
      .card-head-action {{
        border: 1px solid transparent;
        background: transparent;
        color: var(--muted);
        width: 24px;
        height: 24px;
        padding: 0;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 6px;
        cursor: default;
      }}
      .card-head-action:hover {{
        background: rgba(148, 163, 184, 0.14);
        color: var(--text);
      }}
      .card-head-action[data-active="true"] {{
        background: rgba(37, 99, 235, 0.18);
        color: #bfdbfe;
      }}
      .card-head-action svg {{
        width: 16px;
        height: 16px;
      }}
      .metric-card[data-seen="true"],
      .focus-column-card[data-seen="true"],
      .focus-stat-card[data-seen="true"] {{
        border-color: rgba(59, 130, 246, 0.35);
      }}
      .decision-zone .decision-card-title {{
        font-size: 1rem;
        font-weight: 700;
        color: var(--text);
      }}
      .decision-zone .decision-card-context,
      .decision-zone .decision-card-examples,
      .decision-zone .decision-card-details {{
        font-size: 0.88rem;
        color: var(--muted);
        line-height: 1.4;
      }}
      .decision-zone .decision-card-shell .actions {{
        margin-top: 0 !important;
      }}
      .focus-stat-card,
      .metric-card,
      .focus-column-card,
      .collection-card {{
        text-align: left;
      }}
      .focus-stat-card > * + *,
      .metric-card > * + *,
      .focus-column-card > * + *,
      .collection-card > * + * {{
        margin-top: var(--right-panel-inner-gap);
      }}
      .focus-stat-card .decision-card-actions,
      .focus-column-card .actions,
      .metric-card .actions,
      .collection-card .actions {{
        margin-top: 10px;
      }}
      .focus-stat-card .actions,
      .focus-column-card .actions,
      .metric-card .actions,
      .collection-card .actions,
      .decision-card-actions {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }}
      .focus-stat-card .actions .button,
      .focus-column-card .actions .button,
      .metric-card .actions .button,
      .collection-card .actions .button,
      .decision-card-actions .button {{
        flex: 1 1 0;
        min-width: 170px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        text-align: center;
      }}
      .card-actions {{
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
      }}
      .decision-zone .origin-overview[style],
      .decision-zone .focus-stat-card[style],
      .decision-zone article[style],
      .decision-zone section[style],
      .decision-zone div[style] {{
        margin-top: 0 !important;
        margin-bottom: 0 !important;
      }}
      .focus-stat-card.h-card {{
        padding: 10px 12px;
      }}
      .h-card-layout {{
        display: grid;
        grid-template-columns: minmax(150px, 0.8fr) minmax(240px, 1.4fr) minmax(200px, 1fr);
        gap: 12px;
        align-items: center;
      }}
      .h-card-left,
      .h-card-center,
      .h-card-right {{
        min-width: 0;
      }}
      .h-card-center .path-bar,
      .h-card-right .path-bar {{
        margin-top: 6px;
      }}
      .h-card-right .actions {{
        justify-content: flex-end;
      }}
      .focus-stat-value {{
        margin-top: 6px;
        font-size: 1.05rem;
        font-weight: 800;
        color: var(--text);
      }}
      .focus-column-card {{
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 12px;
        background: rgba(255, 255, 255, 0.03);
        width: 100%;
        min-height: 0;
        height: auto;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
      }}
      .focus-column-head {{
        display: flex;
        justify-content: space-between;
        align-items: start;
        gap: 10px;
      }}
      .focus-column-name {{
        font-weight: 800;
        color: var(--text);
      }}
      .focus-column-stats {{
        display: grid;
        gap: 4px;
        margin-top: 8px;
      }}
      .focus-column-stat {{
        font-size: 0.82rem;
        color: var(--muted);
      }}
      .focus-column-details {{
        margin-top: 10px;
      }}
      .focus-layer-block {{
        margin-top: 10px;
      }}
      .focus-mini-pre {{
        height: 120px;
        font-size: 0.76rem;
        margin-top: 6px;
      }}
      .action-panel {{
        display: grid;
        gap: 12px;
      }}
      .action-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
        margin-top: 4px;
      }}
      .column-badge {{
        width: 26px;
        height: 26px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--border);
        color: var(--muted);
        font-size: 0.76rem;
        flex: 0 0 auto;
      }}
      @media (max-width: 920px) {{
        .h-card-layout {{
          grid-template-columns: 1fr;
          gap: 8px;
          align-items: start;
        }}
        .h-card-right .actions {{
          justify-content: flex-start;
        }}
      }}
      .hero {{
        display: grid;
        grid-template-columns: minmax(280px, var(--left-rail-width, 34%)) 10px minmax(0, 1fr);
        gap: 16px;
        align-items: start;
      }}
      .hero-splitter {{
        min-height: 100%;
        border-radius: 999px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.06);
        cursor: col-resize;
        position: relative;
        user-select: none;
        touch-action: none;
      }}
      .hero-splitter::before {{
        content: "";
        position: absolute;
        left: 50%;
        top: 50%;
        width: 2px;
        height: 52px;
        transform: translate(-50%, -50%);
        border-radius: 999px;
        background: rgba(148, 163, 184, 0.45);
      }}
      .hero-splitter:hover {{
        background: rgba(79, 140, 255, 0.12);
        border-color: rgba(79, 140, 255, 0.36);
      }}
      .hero-splitter:focus-visible {{
        outline: 2px solid rgba(79, 140, 255, 0.72);
        outline-offset: 1px;
      }}
      .is-resizing,
      .is-resizing * {{
        cursor: col-resize !important;
        user-select: none !important;
      }}
      .panel {{
        background: var(--panel);
        border: 1px solid var(--border);
        border-radius: var(--radius-panel);
        box-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
        padding: 14px;
      }}
      .card {{
        background: var(--panel-2);
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 12px;
        min-height: 0;
      }}
      .left-rail-host {{
        position: sticky;
        top: 18px;
        align-self: start;
        height: calc(100vh - 56px);
      }}
      .left-functional-panels {{
        display: flex;
        flex-direction: column;
        gap: 10px;
        height: 100%;
        overflow: auto;
      }}
      .functional-panel {{
        background: var(--panel-2);
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 9px;
        min-height: 0;
      }}
      .functional-panel h2 {{
        margin: 0 0 10px;
        font-size: 0.82rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
      }}
      .panel-header-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
      }}
      .orientation-history {{
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        background: rgba(255, 255, 255, 0.02);
        padding: 8px 8px 10px;
      }}
      .orientation-tree-list {{
        list-style: none;
        margin: 0;
        padding-left: 0;
      }}
      .orientation-node {{
        margin: 0;
      }}
      .orientation-children {{
        list-style: none;
        margin: 2px 0 0 20px;
        padding-left: 8px;
        border-left: 1px dashed rgba(148, 163, 184, 0.22);
      }}
      .orientation-node-row {{
        display: grid;
        grid-template-columns: 18px minmax(0, 1fr) auto;
        align-items: center;
        gap: 8px;
        min-height: 28px;
      }}
      .orientation-node-row.is-current {{
        background: rgba(79, 140, 255, 0.10);
        border-radius: 6px;
      }}
      .orientation-toggle {{
        width: 18px;
        height: 18px;
        min-width: 18px;
        padding: 0;
        border: 1px solid var(--border);
        border-radius: 5px;
        background: transparent;
        color: var(--muted);
        cursor: pointer;
        line-height: 16px;
        font-size: 0.7rem;
      }}
      .orientation-toggle-placeholder {{
        display: inline-flex;
        width: 18px;
        justify-content: center;
        color: var(--muted);
        opacity: 0.7;
      }}
      .orientation-node-link {{
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--text);
        text-decoration: none;
        font-size: 0.86rem;
        font-weight: 500;
      }}
      .orientation-node-link:hover {{
        text-decoration: underline;
      }}
      .orientation-node-link.is-current {{
        font-weight: 500;
        color: #eff6ff;
      }}
      .orientation-node-link.importance-high {{
        font-weight: 700;
      }}
      .orientation-node-link.importance-medium {{
        font-weight: 500;
      }}
      .orientation-node-link.importance-low {{
        font-weight: 350;
      }}
      .functional-panel .small {{
        margin-top: 4px;
      }}
      .tools-panel {{
        flex: 0 0 auto;
        min-height: 160px;
        max-height: 38vh;
        overflow: auto;
      }}
      .tools-panel[data-collapsed="1"] {{
        min-height: 74px;
        max-height: 74px;
        overflow: hidden;
      }}
      .orientation-panel {{
        flex: 0 0 auto;
        min-height: 250px;
        max-height: 46vh;
        overflow: auto;
      }}
      .orientation-panel-actions {{
        margin-top: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
      }}
      .detailed-graph {{
        margin-top: 12px;
        border-top: 1px solid var(--border);
        padding-top: 10px;
        display: grid;
        gap: 10px;
        box-sizing: border-box;
      }}
      .detailed-graph-groups {{
        display: grid;
        gap: 10px;
      }}
      .detailed-graph-group {{
        display: grid;
        gap: 6px;
        min-width: 0;
      }}
      .detailed-graph-group-title {{
        font-size: 0.78rem;
        font-weight: 800;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0;
      }}
      .detailed-graph-node-list,
      .detailed-graph-edge-list {{
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: 5px;
        min-width: 0;
      }}
      .detailed-graph-node,
      .detailed-graph-edge {{
        min-width: 0;
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 7px 8px;
        background: rgba(255, 255, 255, 0.03);
        color: var(--text);
        font-size: 0.82rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
        word-break: break-word;
        box-sizing: border-box;
      }}
      .detailed-graph-node.is-current {{
        border-color: rgba(79, 140, 255, 0.72);
        background: rgba(79, 140, 255, 0.12);
      }}
      .graph-node-link {{
        color: inherit;
        text-decoration: none;
        overflow-wrap: anywhere;
      }}
      .graph-node-link:hover {{
        color: var(--accent);
      }}
      .graph-node-link.is-current {{
        color: var(--accent);
        font-weight: 800;
      }}
      .detailed-graph-edge {{
        display: flex;
        align-items: flex-start;
        gap: 6px;
      }}
      .detailed-graph-arrow {{
        color: var(--muted);
        flex: 0 0 auto;
      }}
      .collection-board {{
        margin-top: 12px;
      }}
      .collection-card-list {{
        display: grid;
        gap: 8px;
      }}
      .collection-card {{
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 10px;
        background: rgba(255, 255, 255, 0.03);
        cursor: pointer;
        display: grid;
        gap: 4px;
        height: auto;
        min-height: 0;
      }}
      .collection-card-title {{
        font-weight: 700;
        color: var(--text);
        margin-bottom: 0;
      }}
      .collection-card-progress-row {{
        display: grid;
        grid-template-columns: minmax(80px, 1fr) auto;
        align-items: center;
        gap: 8px;
      }}
      .collection-card-meta {{
        font-size: 0.78rem;
        color: var(--muted);
        margin-bottom: 0;
        white-space: nowrap;
      }}
      .collection-card-progress {{
        width: 100%;
        height: 4px;
        border-radius: 999px;
        background: #e5e7eb;
        overflow: hidden;
      }}
      .collection-card-progress-fill {{
        display: block;
        height: 100%;
        border-radius: inherit;
        background: #2563eb;
      }}
      .collection-card-stars {{
        color: #f59e0b;
        font-size: 0.75rem;
        letter-spacing: 1px;
        line-height: 1;
        white-space: nowrap;
        text-align: right;
      }}
      .collection-card-hint {{
        font-size: 0.76rem;
        color: var(--muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .tools-panel .card,
      .orientation-panel .card {{
        margin: 0;
      }}
      .source-card {{
        display: grid;
        gap: 6px;
      }}
      .tools-panel label {{
        font-size: 0.74rem;
      }}
      .tools-panel input {{
        min-height: 32px;
        padding: 7px 9px;
      }}
      h1 {{
        font-size: clamp(2rem, 3vw, 3.1rem);
        line-height: 1.02;
        margin: 0 0 10px;
        letter-spacing: -0.03em;
      }}
      .lede {{
        color: var(--muted);
        max-width: 66ch;
        line-height: 1.5;
      }}
      .badge {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 7px 11px;
        color: var(--muted);
        margin-bottom: 12px;
        background: rgba(255, 255, 255, 0.03);
      }}
      .grid {{
        display: grid;
        gap: 12px;
        margin-top: 12px;
      }}
      label {{
        display: block;
        font-size: 0.85rem;
        color: var(--muted);
        margin: 0 0 8px;
      }}
      textarea, input, select {{
        width: 100%;
        box-sizing: border-box;
        border-radius: var(--radius-card);
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.03);
        color: var(--text);
        padding: 11px 12px;
        outline: none;
      }}
      input, select {{
        height: 44px;
      }}
      textarea {{
        height: 120px;
        resize: none;
        overflow: auto;
      }}
      .actions {{
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 10px;
      }}
      .navigation-frame {{
        margin-bottom: 12px;
      }}
      .right-panel-top-actions {{
        display: flex;
        justify-content: flex-end;
        margin-bottom: 0;
      }}
      .right-panel-stack {{
        --right-panel-gap: 12px;
        --right-panel-title-gap: 10px;
        --right-panel-inner-gap: 8px;
        display: flex;
        flex-direction: column;
        gap: var(--right-panel-gap);
        margin-top: 12px;
      }}
      .right-panel-stack > .rp-block {{
        margin: 0 !important;
      }}
      .right-panel-stack > .rp-block:empty {{
        display: none;
      }}
      .right-panel-stack .rp-block > .results-title,
      .right-panel-stack .results-title,
      .right-panel-stack .origin-overview,
      .right-panel-stack .focus-unit,
      .right-panel-stack .focus-stats,
      .right-panel-stack .actions,
      .right-panel-stack details {{
        margin: 0 !important;
      }}
      .right-panel-stack [style*="margin-top"],
      .right-panel-stack [style*="margin-bottom"] {{
        margin-top: 0 !important;
        margin-bottom: 0 !important;
      }}
      .right-panel-stack .results-title {{
        min-height: 22px;
        line-height: 22px;
      }}
      .right-panel-stack .rp-block > .results-title + * {{
        margin-top: var(--right-panel-title-gap) !important;
      }}
      .right-panel-stack .focus-stat-card .h-card-left > * + *,
      .right-panel-stack .focus-stat-card .h-card-center > * + *,
      .right-panel-stack .focus-stat-card .h-card-right > * + *,
      .right-panel-stack .origin-overview > * + *,
      .right-panel-stack .focus-unit > * + * {{
        margin-top: var(--right-panel-inner-gap) !important;
      }}
      .copy-audit-btn {{
        width: 30px;
        min-width: 30px;
        height: 30px;
        padding: 0;
        border-radius: 8px;
      }}
      button, .button {{
        border: 0;
        border-radius: var(--radius-card);
        padding: 0 12px;
        min-width: 132px;
        height: 38px;
        font-weight: 700;
        color: #eff6ff;
        background: linear-gradient(135deg, var(--accent), var(--accent-2));
        cursor: pointer;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: 0 0 auto;
      }}
      .button.mini {{
        min-width: 80px;
        height: 30px;
        padding: 0 8px;
        font-size: 0.78rem;
        border-radius: var(--radius-control);
        flex: 0 0 auto;
        opacity: 0.88;
      }}
      .card-actions > .button,
      .card-actions > .button.mini {{
        flex: 1 1 128px;
        min-width: 128px;
        max-width: 156px;
        justify-content: center;
        text-align: center;
      }}
      button.secondary, .button.secondary {{
        background: transparent;
        color: var(--text);
        border: 1px solid var(--border);
      }}
      .overview {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-bottom: 12px;
      }}
      .stat {{
        border-radius: var(--radius-card);
        padding: 11px 12px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.03);
      }}
      .stat .label {{
        font-size: 0.78rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 8px;
      }}
      .stat .value {{
        font-size: 0.98rem;
        line-height: 1.35;
        color: var(--text);
        word-break: break-word;
      }}
      .unit-metrics {{
        display: grid;
        gap: 10px;
        margin: 14px 0 4px;
        align-items: stretch;
      }}
      .source-cards {{
        display: flex;
        flex-direction: column;
        gap: var(--right-panel-gap);
        margin: 6px 0 2px;
      }}
      .source-relations {{
        display: grid;
        gap: 12px;
        margin-top: 10px;
      }}
      .metric-link {{
        display: block;
        color: inherit;
        text-decoration: none;
      }}
      .metric-card {{
        border: 1px solid var(--border);
        border-radius: var(--radius-card);
        padding: 12px;
        background: rgba(255, 255, 255, 0.03);
        transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
        height: auto;
        min-height: 0;
      }}
      .metric-card:hover {{
        transform: translateY(-1px);
        border-color: rgba(79, 140, 255, 0.28);
      }}
      .metric-card.selected-metric {{
        border-color: rgba(79, 140, 255, 0.42);
        background: rgba(79, 140, 255, 0.08);
      }}
      .metric-head {{
        display: grid;
        grid-template-columns: 28px minmax(0, 1fr);
        gap: 10px;
        align-items: start;
      }}
      .metric-index {{
        width: 28px;
        height: 28px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.04);
        color: var(--muted);
        font-size: 0.82rem;
        font-weight: 700;
      }}
      .metric-body {{
        min-width: 0;
        width: 100%;
      }}
      .metric-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
      }}
      .metric-name {{
        font-weight: 700;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .metric-badge {{
        font-size: 0.75rem;
        color: var(--muted);
        border: 1px solid var(--border);
        border-radius: 999px;
        padding: 4px 8px;
        flex: 0 0 auto;
      }}
      .metric-meta {{
        font-size: 0.82rem;
        color: var(--muted);
        margin-top: 6px;
      }}
      .origin-card-list {{
        margin: 8px 0 0;
        padding-left: 16px;
        display: grid;
        gap: 4px;
      }}
      .origin-card-list li {{
        margin: 0;
        color: var(--text);
        font-size: 0.9rem;
        line-height: 1.35;
      }}
      .metric-action {{
        margin-top: 8px;
        font-size: 0.84rem;
        color: var(--muted);
        font-weight: 600;
      }}
      .metric-preview {{
        margin-top: 8px;
        color: var(--text);
        font-size: 0.92rem;
        line-height: 1.45;
        max-height: 3.2em;
        overflow: hidden;
      }}
      .results-title {{
        font-size: 0.82rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 0 0 10px;
      }}
      .status-line {{
        margin: 0 0 12px;
        padding: 11px 12px;
        border-radius: var(--radius-card);
        border: 1px solid rgba(43, 108, 176, 0.18);
        background: rgba(79, 140, 255, 0.08);
        color: var(--text);
        font-weight: 600;
      }}
      .small {{
        font-size: 0.9rem;
        color: var(--muted);
      }}
      pre {{
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        color: var(--text);
        background: rgba(255, 255, 255, 0.03);
        border-radius: var(--radius-card);
        border: 1px solid var(--border);
        padding: 14px;
        height: 210px;
        overflow: auto;
      }}
      details {{
        margin-top: 16px;
      }}
      .focus-mode .hero {{
        --left-rail-width: 30%;
      }}
      .focus-mode .raw-panel {{
        display: none;
      }}
      .focus-mode .overview {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
      .focus-mode .masthead-actions {{
        display: none;
      }}
      @media (max-width: 900px) {{
        .hero, .grid, .overview {{
          grid-template-columns: 1fr;
        }}
        .hero-splitter {{
          display: none;
        }}
        .left-rail-host {{
          position: static;
          height: auto;
        }}
        .left-functional-panels {{
          height: auto;
        }}
        .tools-panel, .orientation-panel {{
          min-height: 0;
          max-height: none;
          overflow: visible;
        }}
        .focus-mode .hero {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body class="{focus_class}" lang="{escape(lang)}">
    <main class="shell">
      <section class="panel masthead">
        <div class="masthead-row">
          <div>
            <div class="badge">{escape(ui["console_badge"])}</div>
            <h1>{escape(ui["hero_title"])}</h1>
          </div>
        </div>
        <p class="lede">{escape(ui["hero_lede"])}</p>
      </section>
      <div class="hero" id="hero-layout">
        <section class="left-rail-host" id="left-rail-panel">
          <div id="left-functional-panels-root" class="left-functional-panels"></div>
          <section id="collection-board-fallback" class="functional-panel collection-board" style="margin-top: 10px;">
            <h2>Quadro de colecao</h2>
            <div class="actions" style="margin-top: 8px;">
              <a class="button secondary mini" href="{escape(str(collection_board_data['currentState']['state_reference']['href']))}">Abrir estado atual</a>
            </div>
          </section>
          <noscript>
            <section class="functional-panel orientation-panel">
              <h2>Histórico de orientação</h2>
              <div style="margin-top: 8px;">{branch_graph_html or ''}</div>
            </section>
          </noscript>
        </section>
        <div
          id="hero-splitter"
          class="hero-splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label="Redimensionar painéis"
          tabindex="0"
        ></div>

        <aside class="panel" id="right-content-panel">
          {right_panel_body_html}
        </aside>
      </div>
      <script>
        function openSummaryTableDialog() {{
          const dialog = document.getElementById("summary_table_dialog");
          if (!dialog) return;
          if (typeof dialog.showModal === "function") {{
            dialog.showModal();
            return;
          }}
          dialog.setAttribute("open", "open");
        }}
        function closeSummaryTableDialog() {{
          const dialog = document.getElementById("summary_table_dialog");
          if (!dialog) return;
          if (typeof dialog.close === "function") {{
            dialog.close();
            return;
          }}
          dialog.removeAttribute("open");
        }}
        async function copyRightPanelAudit() {{
          const field = document.getElementById("right_panel_audit");
          if (!field) return;
          const text = field.value || field.textContent || "";
          try {{
            await navigator.clipboard.writeText(text);
          }} catch (error) {{
            field.removeAttribute("hidden");
            field.focus();
            field.select();
            try {{
              document.execCommand("copy");
            }} finally {{
              field.setAttribute("hidden", "");
            }}
          }}
        }}
        function downloadRawPayload() {{
          const field = document.getElementById("raw_payload_text");
          if (!field) return;
          const content = field.value || field.textContent || "";
          const blob = new Blob([content], {{ type: "application/json;charset=utf-8" }});
          const url = URL.createObjectURL(blob);
          const stamp = new Date().toISOString().replace(/[:.]/g, "-");
          const link = document.createElement("a");
          link.href = url;
          link.download = `payload-bruto-${{stamp}}.json`;
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
        }}

        (function initHeroSplitter() {{
          const hero = document.getElementById("hero-layout");
          const leftPanel = document.getElementById("left-rail-panel");
          const splitter = document.getElementById("hero-splitter");
          if (!hero || !leftPanel || !splitter) return;
          if (window.matchMedia("(max-width: 900px)").matches) return;

          const storageKey = "agnostic-layout-left-width";
          const minLeft = 280;
          const minRight = 420;

          function clampLeftPx(value) {{
            const heroWidth = hero.getBoundingClientRect().width;
            const splitterWidth = splitter.getBoundingClientRect().width || 10;
            const maxLeft = Math.max(minLeft, heroWidth - splitterWidth - minRight);
            return Math.max(minLeft, Math.min(value, maxLeft));
          }}

          function applyLeftPx(value, persist = true) {{
            const leftPx = clampLeftPx(value);
            hero.style.setProperty("--left-rail-width", `${{leftPx}}px`);
            if (persist) {{
              try {{
                localStorage.setItem(storageKey, String(Math.round(leftPx)));
              }} catch (error) {{
                // ignore storage failures
              }}
            }}
          }}

          function restoreLeftPx() {{
            try {{
              const stored = localStorage.getItem(storageKey);
              const parsed = stored ? Number(stored) : NaN;
              if (Number.isFinite(parsed)) {{
                applyLeftPx(parsed, false);
                return;
              }}
            }} catch (error) {{
              // ignore storage failures
            }}
            applyLeftPx(leftPanel.getBoundingClientRect().width, false);
          }}

          let dragging = false;

          function stopDragging() {{
            if (!dragging) return;
            dragging = false;
            document.body.classList.remove("is-resizing");
          }}

          function move(clientX) {{
            const heroRect = hero.getBoundingClientRect();
            applyLeftPx(clientX - heroRect.left);
          }}

          splitter.addEventListener("pointerdown", (event) => {{
            dragging = true;
            splitter.setPointerCapture(event.pointerId);
            document.body.classList.add("is-resizing");
          }});

          splitter.addEventListener("pointermove", (event) => {{
            if (!dragging) return;
            move(event.clientX);
          }});

          splitter.addEventListener("pointerup", stopDragging);
          splitter.addEventListener("pointercancel", stopDragging);

          window.addEventListener("resize", () => {{
            if (window.matchMedia("(max-width: 900px)").matches) return;
            const currentLeft = leftPanel.getBoundingClientRect().width;
            applyLeftPx(currentLeft, false);
          }});

          splitter.addEventListener("keydown", (event) => {{
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            const delta = event.key === "ArrowLeft" ? -24 : 24;
            const currentLeft = leftPanel.getBoundingClientRect().width;
            applyLeftPx(currentLeft + delta);
          }});

          restoreLeftPx();
        }})();
      </script>
      <script id="left-functional-panels-data" type="application/json">{left_panels_payload}</script>
      <script id="collection-board-data" type="application/json">{json.dumps(collection_board_data, ensure_ascii=False).replace("</", "<\\/")}</script>
      <script type="module" src="/static/layout-panels.js?v=collection-board-v32"></script>
    </main>
  </body>
</html>"""


def _resolve_action(
    *,
    source_type: str,
    source_path: str,
    action: str,
    unit_name: str,
    column_name: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
) -> tuple[dict[str, Any] | None, str, list[str], str, str | None]:
    if action == "reset":
        return None, "Estado salvo limpo.", [], "", None

    if action == "health":
        return run_build_health_result(), "Checando saúde...", [], "", None

    if action == "ai":
        try:
            data = run_build_ai_result(prompt)
            return data, "Consultando IA...", [], "", None
        except GroqAPIError as exc:
            return {"error": str(exc)}, str(exc), [], "", None

    if action == "tabular":
        try:
            data = run_build_tabular_result(unit_name or DEFAULT_UNIT_NAME, columns_text, rows_text)
            return data, "Analisando payload tabular...", [], unit_name or DEFAULT_UNIT_NAME, data.get("persisted_to")
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}, f"ERRO: {exc}", [], unit_name or DEFAULT_UNIT_NAME, None

    try:
        summary = run_build_source_result(
            source_type,
            source_path,
            analyze_units=False,
            resolve_source_fn=_resolve_source,
            preview_source_unit_fn=_preview_source_unit,
            ordered_unit_names_fn=_ordered_unit_names,
            attach_internal_cuts_fn=attach_internal_cuts,
            source_summary_text_fn=source_summary_text,
            resolve_optional_limit_fn=resolve_optional_limit,
            unit_importance_score_fn=_unit_importance_score,
        )
        unit_names = list(summary.get("tabela_nomes") or [])
        selected = unit_name if unit_name in unit_names else (unit_names[0] if unit_names else "")

        if action in {"quick", "tabela", "previous", "next", "coluna", "valor"} and unit_names:
            selected = _select_unit_name(unit_names, selected, action)
            detail = run_build_source_result(
                source_type,
                source_path,
                analyze_units=True,
                resolve_source_fn=_resolve_source,
                preview_source_unit_fn=_preview_source_unit,
                ordered_unit_names_fn=_ordered_unit_names,
                attach_internal_cuts_fn=attach_internal_cuts,
                source_summary_text_fn=source_summary_text,
                resolve_optional_limit_fn=resolve_optional_limit,
                unit_importance_score_fn=_unit_importance_score,
                unit_name=selected,
                unit_limit=len(unit_names),
            )
            if action == "quick":
                detail["summary"] = (
                    summary["summary"]
                    + "\n"
                    + detail["summary"]
                )
            detail["jump_target"] = selected
            return detail, {
                "quick": "Explorando a origem...",
                "tabela": "Inspecionando unidades da origem...",
                "previous": "Movendo para a unidade anterior...",
                "next": "Movendo para a próxima unidade...",
                "coluna": "Inspecionando coluna...",
                "valor": "Inspecionando valor/célula...",
            }[action], unit_names, selected, detail.get("persisted_to")

        summary["jump_target"] = selected
        return summary, "Conectando à origem...", unit_names, selected, None
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}, f"ERROR: {exc}", [], "", None


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(title="Cartographer", lifespan=lifespan)
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)

    @app.get("/", response_class=HTMLResponse)
    def index(
        source_type: str = Query(DEFAULT_SOURCE_TYPE),
        source_path: str = Query(DEFAULT_SOURCE_PATH),
        action: str = Query("reset"),
        unit_name: str = Query(""),
        column_name: str = Query(""),
        recorte_id: str = Query(""),
        relation_column: str = Query(""),
        relation_values: str = Query(""),
        exception_group: str = Query(""),
        selected_value: str = Query(""),
        selected_value_id: str = Query(""),
        slice_mode: str = Query(""),
        signature_path: str = Query(""),
        decision_type: str = Query(""),
        origin_table: str = Query(""),
        origin_signature: str = Query(""),
        origin_slice_type: str = Query(""),
        origin_condition: str = Query(""),
        context_filters: str = Query(""),
        columns: str = Query(DEFAULT_COLUMNS),
        rows: str = Query(DEFAULT_ROWS),
        prompt: str = Query(DEFAULT_PROMPT),
        focus: bool = Query(False),
        lang: str = Query(DEFAULT_LANG),
    ) -> HTMLResponse:
        result, status_line, unit_names, selected_unit, _ = _resolve_action(
            source_type=source_type,
            source_path=source_path,
            action=action,
            unit_name=unit_name,
            column_name=column_name,
            columns_text=columns,
            rows_text=rows,
            prompt=prompt,
        )
        html = _render_page(
            source_type=source_type,
            source_path=source_path,
            unit_name=unit_name,
            column_name=column_name,
            columns_text=columns,
            rows_text=rows,
            prompt=prompt,
            recorte_id=recorte_id,
            relation_column=relation_column,
            relation_values=relation_values,
            exception_group=exception_group,
            selected_value=selected_value,
            selected_value_id=selected_value_id,
            slice_mode=slice_mode,
            signature_path=signature_path,
            decision_type=decision_type,
            origin_table=origin_table,
            origin_signature=origin_signature,
            origin_slice_type=origin_slice_type,
            origin_condition=origin_condition,
            context_filters=context_filters,
            focus_mode=focus,
            action=action,
            result=result,
            error=result.get("error") if isinstance(result, dict) else None,
            unit_names=unit_names,
            selected_unit=selected_unit,
            jump_label=(result or {}).get("jump_target") and f"Jump target: {(result or {}).get('jump_target')}",
            lang=lang,
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.post("/upload-source", response_class=HTMLResponse)
    async def upload_source(
        source_type: str = Form(DEFAULT_SOURCE_TYPE),
        source_path: str = Form(DEFAULT_SOURCE_PATH),
        action: str = Form("summary"),
        unit_name: str = Form(""),
        column_name: str = Form(""),
        recorte_id: str = Form(""),
        relation_column: str = Form(""),
        relation_values: str = Form(""),
        exception_group: str = Form(""),
        selected_value: str = Form(""),
        selected_value_id: str = Form(""),
        slice_mode: str = Form(""),
        signature_path: str = Form(""),
        decision_type: str = Form(""),
        origin_table: str = Form(""),
        origin_signature: str = Form(""),
        origin_slice_type: str = Form(""),
        origin_condition: str = Form(""),
        context_filters: str = Form(""),
        columns: str = Form(DEFAULT_COLUMNS),
        rows: str = Form(DEFAULT_ROWS),
        prompt: str = Form(DEFAULT_PROMPT),
        focus: str = Form("0"),
        lang: str = Form(DEFAULT_LANG),
        source_file: UploadFile | None = File(None),
    ) -> RedirectResponse:
        resolved_source_path = source_path
        resolved_source_type = source_type
        resolved_action = action or "summary"
        resolved_unit_name = unit_name
        resolved_column_name = column_name
        resolved_recorte_id = recorte_id
        resolved_relation_column = relation_column
        resolved_relation_values = relation_values
        resolved_exception_group = exception_group
        resolved_selected_value = selected_value
        resolved_selected_value_id = selected_value_id
        resolved_slice_mode = slice_mode
        resolved_signature_path = signature_path
        resolved_decision_type = decision_type
        resolved_origin_table = origin_table
        resolved_origin_signature = origin_signature
        resolved_origin_slice_type = origin_slice_type
        resolved_origin_condition = origin_condition
        resolved_context_filters = context_filters
        if source_file and source_file.filename:
            safe_name = Path(source_file.filename).name
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            destination = UPLOAD_DIR / f"{uuid4().hex}_{safe_name}"
            content = await source_file.read()
            destination.write_bytes(content)
            resolved_source_path = str(destination)
            resolved_source_type = _infer_source_type_from_filename(source_type, safe_name)
            resolved_action = "summary"
            resolved_unit_name = ""
            resolved_column_name = ""
            resolved_recorte_id = ""
            resolved_relation_column = ""
            resolved_relation_values = ""
            resolved_exception_group = ""
            resolved_selected_value = ""
            resolved_selected_value_id = ""
            resolved_slice_mode = ""
            resolved_signature_path = ""
            resolved_decision_type = ""
            resolved_origin_table = ""
            resolved_origin_signature = ""
            resolved_origin_slice_type = ""
            resolved_origin_condition = ""
            resolved_context_filters = ""

        query = urlencode(
            {
                "source_type": resolved_source_type,
                "source_path": resolved_source_path,
                "action": resolved_action,
                "unit_name": resolved_unit_name,
                "column_name": resolved_column_name,
                "recorte_id": resolved_recorte_id,
                "relation_column": resolved_relation_column,
                "relation_values": resolved_relation_values,
                "exception_group": resolved_exception_group,
                "selected_value": resolved_selected_value,
                "selected_value_id": resolved_selected_value_id,
                "slice_mode": resolved_slice_mode,
                "signature_path": resolved_signature_path,
                "decision_type": resolved_decision_type,
                "origin_table": resolved_origin_table,
                "origin_signature": resolved_origin_signature,
                "origin_slice_type": resolved_origin_slice_type,
                "origin_condition": resolved_origin_condition,
                "context_filters": resolved_context_filters,
                "columns": columns,
                "rows": rows,
                "prompt": prompt,
                "focus": focus,
                "lang": lang,
            }
        )
        return RedirectResponse(url=f"/?{query}", status_code=303)

    return app
