from __future__ import annotations

import json
import re

from agnostic.interface.formatter import (
    _mixed_format_warnings_from_result_context,
    sanitize_interface_reply,
)
from agnostic.interface.prompts import INTERFACE_SYSTEM_PROMPT, build_interface_prompt
from agnostic.session import SessionManager


def _extract_action_marker_from_reply(reply_text: str) -> tuple[str, dict[str, object] | None]:
    """Extrai o marcador de ação do texto de resposta da Interface.

    Retorna (texto_limpo, action_payload) onde texto_limpo é o reply_text sem o marcador.
    """
    if not isinstance(reply_text, str):
        return reply_text, None

    marker_pattern = r"<!-- action: (\{.*?\}) -->"
    match = re.search(marker_pattern, reply_text, re.DOTALL)

    if not match:
        return reply_text, None

    try:
        action_payload = json.loads(match.group(1))
        clean_text = re.sub(marker_pattern, "", reply_text, flags=re.DOTALL).strip()
        if not isinstance(action_payload, dict):
            return clean_text, None
        return clean_text, action_payload
    except json.JSONDecodeError:
        return reply_text, None

def _build_structured_choice_message(session, lead: str, closing: str) -> str:
    options = session.rendered_presented_options()
    if not options:
        return f"{lead} {closing}".strip()
    if len(options) == 1:
        option = options[0]
        lines = [lead.strip(), f"A opção disponível agora é: {str(option.get('display_text', '')).strip()}.", "Responda sim ou não."]
        return "\n".join(line for line in lines if line)
    lines = [lead.strip(), "Estas são as opções disponíveis:"]
    for option in options:
        lines.append(f"{int(option.get('index', 0))}. {str(option.get('display_text', '')).strip()}")
    lines.append(closing.strip())
    return "\n".join(line for line in lines if line)


def build_unmapped_analysis_reply(session) -> str:
    options: list[dict[str, object]] = []
    try:
        options = session.rendered_presented_options()
    except Exception:
        options = []
    if not options and hasattr(session, "fallback_unexplored_unit_options"):
        fallback = session.fallback_unexplored_unit_options()
        if fallback:
            if hasattr(session, "register_presented_options"):
                session.register_presented_options(fallback)
            else:
                session._last_presented_options = fallback
            try:
                options = session.rendered_presented_options()
            except Exception:
                options = list(fallback)
    if options:
        lines = [
            "Não consigo executar essa análise diretamente.",
            "O que posso fazer:",
        ]
        for option in options:
            label = str(option.get("display_text", option.get("label", ""))).strip()
            if label:
                lines.append(f"{int(option.get('index', 0))}. {label}")
        return "\n".join(lines)
    return (
        "Não consigo executar essa análise diretamente.\n"
        "O que posso fazer: diga o nome de uma unidade para explorar ou reformule sua pergunta."
    )



def render_tables_message(action_result: str) -> str:
    payload = json.loads(action_result)
    tables = payload.get("tables", [])
    return f"Tabelas disponíveis: {', '.join(str(item) for item in tables) if tables else 'nenhuma'}."


def render_schema_message(action_result: str) -> str:
    payload = json.loads(action_result)
    table = str(payload.get("table", ""))
    columns = payload.get("columns", [])
    rendered = []
    for column in columns:
        raw_type = column.get("raw_type")
        if raw_type:
            rendered.append(f"{column.get('name')} ({raw_type})")
        else:
            rendered.append(str(column.get("name")))
    return f"Schema de {table}: {', '.join(rendered) if rendered else 'sem colunas visíveis'}."


def _schema_column_rows_from_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    column_rows: list[dict[str, object]] = []
    for column in payload.get("columns", []):
        if not isinstance(column, dict):
            continue
        name = str(column.get("name", "")).strip()
        if not name:
            continue
        raw_type = column.get("raw_type")
        column_rows.append(
            {
                "name": name,
                "type": str(raw_type).strip() if raw_type not in (None, "") else "sem tipo declarado",
                "position": column.get("position"),
            }
        )
    return column_rows


def build_schema_response_context(
    *,
    action_payload: dict[str, object] | None,
    execution_result: str,
    presented_options: list[dict[str, object]] | None,
    execution_log: list[dict[str, object]] | None,
) -> dict[str, object]:
    from agnostic.interface.formatter import _visible_presented_options

    try:
        payload = json.loads(execution_result)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    table = str(payload.get("table", "")).strip()
    column_rows = _schema_column_rows_from_payload(payload)
    visible_options, has_more_options = _visible_presented_options(
        presented_options,
        execution_log=execution_log,
        just_executed_action=action_payload,
    )
    return {
        "mode": "result_first",
        "result_type": "schema",
        "executed_action": dict(action_payload) if isinstance(action_payload, dict) else {},
        "raw_result": {
            "table": table,
            "columns": column_rows,
        },
        "visible_next_steps": visible_options,
        "presented_options_formatted": [
            {
                "index": int(option.get("index", 0)),
                "label": str(option.get("display_text", option.get("label", ""))).strip(),
                "reason": str(option.get("reason", "")).strip(),
            }
            for option in visible_options
        ],
        "has_more_options": has_more_options,
    }


def _presented_options_after_execution(
    session,
    *,
    action_payload: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    manager = getattr(session, "_session_manager", None)
    if manager is not None:
        manager.update_presented_options(session)
    else:
        SessionManager().update_presented_options(session)
    options = list(getattr(session, "_last_presented_options", []) or [])
    if options:
        return options
    if hasattr(session, "fallback_unexplored_unit_options"):
        fallback = session.fallback_unexplored_unit_options()
        if fallback:
            if hasattr(session, "register_presented_options"):
                session.register_presented_options(fallback)
            else:
                session._last_presented_options = fallback
            return fallback
    return []


def reply_for_unmapped_analysis_request(session) -> str:
    _presented_options_after_execution(session)
    return build_unmapped_analysis_reply(session)


def reply_for_schema_action(
    session,
    action_payload: dict[str, object],
    execution_result: str,
) -> str:
    presented_options = _presented_options_after_execution(session, action_payload=action_payload)
    result_context = build_schema_response_context(
        action_payload=action_payload,
        execution_result=execution_result,
        presented_options=presented_options,
        execution_log=list(getattr(session, "_execution_log", []) or []),
    )
    return session.interface_reply(
        "Apresente o schema da tabela em formato legível (tabela ou lista estruturada com nome e tipo de cada coluna). "
        "Use apenas raw_result.columns. Depois sugira até 3 próximos caminhos com base em visible_next_steps.",
        result_context=json.dumps(result_context, ensure_ascii=False, indent=2, default=str),
    )


def build_result_first_response_context(
    *,
    action_payload: dict[str, object] | None,
    execution_result: str,
    presented_options: list[dict[str, object]] | None,
    execution_log: list[dict[str, object]] | None,
    mode: str = "result_first",
) -> dict[str, object]:
    from agnostic.interface.formatter import (
        _compress_raw_result_for_interface_context,
        _visible_presented_options,
    )

    try:
        payload = json.loads(execution_result)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    visible_options, has_more_options = _visible_presented_options(
        presented_options,
        execution_log=execution_log,
        just_executed_action=action_payload,
    )
    columns = [str(item) for item in payload.get("columns", [])] if isinstance(payload.get("columns"), list) else []
    rows = payload.get("rows", []) if isinstance(payload.get("rows"), list) else []
    limitations: list[str] = []
    if payload.get("truncated") is True:
        limitations.append("resultado parcial")
    if not rows and not payload.get("summary"):
        limitations.append("sem linhas suficientes para concluir")
    for item in payload.get("next_requirements", []) if isinstance(payload.get("next_requirements"), list) else []:
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason", "")).strip()
        if reason:
            limitations.append(reason)
    limitation_texts: list[str] = []
    seen_limitations: set[str] = set()
    for item in limitations:
        normalized = item.strip()
        if not normalized or normalized in seen_limitations:
            continue
        seen_limitations.add(normalized)
        limitation_texts.append(normalized)

    sample_rows = []
    for row in rows[:3]:
        if isinstance(row, (list, tuple)):
            sample_rows.append([row[index] if index < len(row) else None for index in range(len(columns))])

    result_origin = ""
    result_origin_detail = ""
    status = str(payload.get("status", "")).strip().lower()
    if payload.get("truncated") is True:
        result_origin = "truncated"
        row_count = payload.get("row_count_preview")
        result_origin_detail = (
            f"Resultado parcial: {row_count} linhas retornadas de um total maior. "
            "Conclusões sobre padrões globais não são possíveis aqui."
            if row_count is not None
            else "Resultado parcial: conclusões sobre padrões globais não são possíveis aqui."
        )
    elif str(payload.get("action", "")).strip() == "analyze_horizontal":
        join_confidence = [
            item for item in payload.get("join_confidence", [])
            if isinstance(item, dict)
        ] if isinstance(payload.get("join_confidence"), list) else []
        no_overlap = next((item for item in join_confidence if str(item.get("confidence", "")).strip() == "no_overlap"), None)
        low_overlap = next((item for item in join_confidence if str(item.get("confidence", "")).strip() == "low"), None)
        if no_overlap is not None:
            result_origin = "dataset_limit"
            result_origin_detail = "As tabelas não compartilham valores comuns nessa coluna. O JOIN não produziria resultados com os dados disponíveis."
        elif low_overlap is not None:
            result_origin = "dataset_limit"
            result_origin_detail = "A sobreposição entre as chaves é pequena — o JOIN pode retornar poucos ou nenhum resultado."
        elif payload.get("used_sample") is True:
            result_origin = "sample"
            result_origin_detail = "Esta análise foi feita sobre amostra — não sobre o dataset completo."
    elif status == "cached" and payload.get("cache_key"):
        result_origin = "cache"
        result_origin_detail = "Este resultado já estava calculado nesta sessão."

    approximate_reason = str(payload.get("approximate_reason", "")).strip() or str(
        (action_payload or {}).get("approximate_reason", "")
    ).strip()
    approximate_action = str(payload.get("approximate_action_label", "")).strip() or str(
        (action_payload or {}).get("approximate_action_label", "")
    ).strip()
    if approximate_reason or approximate_action:
        result_origin = "approximate"
        result_origin_detail = (
            f"Não encontrei correspondência exata para o que você pediu. Executei a ação mais próxima disponível: {approximate_action}."
            if approximate_action
            else "Não encontrei correspondência exata para o que você pediu. Executei a ação mais próxima disponível."
        )

    raw_result, has_more_columns, total_columns = _compress_raw_result_for_interface_context(payload)
    result: dict[str, object] = {
        "mode": mode,
        "executed_action": dict(action_payload) if isinstance(action_payload, dict) else {},
        "result_type": payload.get("action") or payload.get("template_id") or payload.get("query_id") or "unknown",
        "row_count": payload.get("row_count_preview") if payload.get("row_count_preview") is not None else payload.get("operational_summary", {}).get("row_count") if isinstance(payload.get("operational_summary"), dict) else None,
        "columns": columns,
        "sample_rows": sample_rows,
        "summary": payload.get("summary") if isinstance(payload.get("summary"), str) else "",
        "metrics_summary": payload.get("metrics_summary") if isinstance(payload.get("metrics_summary"), str) else "",
        "limitations": limitation_texts,
        "result_origin": result_origin,
        "result_origin_detail": result_origin_detail,
        "visible_next_steps": visible_options,
        "presented_options_formatted": [
            {
                "index": int(option.get("index", 0)),
                "label": str(option.get("display_text", option.get("label", ""))).strip(),
                "reason": str(option.get("reason", "")).strip(),
            }
            for option in visible_options
        ],
        "has_more_options": has_more_options,
        "raw_result": raw_result,
    }
    compressed_operational_summary = raw_result.get("operational_summary") if isinstance(raw_result, dict) else None
    if isinstance(compressed_operational_summary, dict):
        result["operational_summary"] = {
            key: value
            for key, value in compressed_operational_summary.items()
            if key in {"row_count", "highest_null_ratio_column"}
        }
    if has_more_columns and total_columns is not None:
        result["has_more_columns"] = True
        result["total_columns"] = total_columns
    return result


def interface_reply(
    session,
    user_text: str,
    *,
    result_context: str,
    is_first_call: bool = False,
    llm=None,
) -> str:
    if llm is None:
        llm = session.interface_ai
    system_prompt = INTERFACE_SYSTEM_PROMPT
    prompt = build_interface_prompt(
        source_path=session.source_path,
        source_type=session.source_type,
        history=session.history,
        user_text=user_text,
        result_context=result_context,
        structural_context=session._full_structural_context or session.build_compact_structural_context(),
        compact_structural_context=session.curated_context_for(user_text, is_first_call=False),
        is_first_call=is_first_call,
        pending_requirements=session.pending_requirements(),
        pending_action=session.pending_action_snapshot(),
        last_presented_options=session.rendered_presented_options(),
        opening_context=session.build_opening_context(),
        user_goal=getattr(session, "user_goal", ""),
        index_registry_summary=session._index_registry_summary_for_prompt(),
    )
    response = llm.send(prompt, system_prompt=system_prompt)
    raw_content = "" if response.content is None else str(response.content)
    session.sync_pending_action_from_interface_reply(raw_content, result_context=result_context)
    reply = sanitize_interface_reply(session, raw_content)
    warnings = _mixed_format_warnings_from_result_context(result_context)
    if warnings:
        warning_block = "\n".join(f"⚠ {warning}" for warning in warnings)
        return f"{warning_block}\n\n{reply}".strip()
    return reply
