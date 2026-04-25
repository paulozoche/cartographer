from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agnostic.application import (
    analyze_tabular_unit,
    render_canonical_analysis_markdown,
    summarize_tabular_analysis,
)
from agnostic.application.use_cases.runtime_analysis import (
    build_ai_result as run_build_ai_result,
    build_health_result as run_build_health_result,
    build_source_result as run_build_source_result,
    build_tabular_result as run_build_tabular_result,
)
from agnostic.application.use_cases.data_slices import (
    DataContext,
    FilterCondition,
    build_query,
    create_slice,
    normalize_table_name,
)
from agnostic.config import load_app_config
from agnostic.core import attach_internal_cuts, resolve_optional_limit, source_summary_text
from agnostic.infrastructure.ai.grok_client import GroqAPIError
from agnostic.interfaces.api.routes import _InlineTabularUnit, _resolve_source, router
from agnostic.interfaces.api.rendering import (
    bounded_json_preview as _bounded_json_preview,
    executive_summary as _executive_summary,
    preview as _preview,
    render_card_header as _render_card_header,
    render_info_card as _render_info_card,
    source_overview_text as _source_overview_text,
    source_preview_text as _source_preview_text,
)
from agnostic.interfaces.value_identity import (
    cell_value_identity_token,
    stable_value_id,
    resolve_selected_value_impact,
)
from agnostic.application.use_cases.summarize_tabular_analysis import summarize_unit_metrics
from agnostic.domain.analysis.compute_value_cell_metrics import build_value_cell_analysis_payload


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


def _signal_label(signal_name: str) -> str:
    mapping = {
        "identifier_signal": "Identificador",
        "high_cardinality_signal": "Alta cardinalidade",
        "near_unique_conflict": "Conflito near-unique",
        "sequential_signal": "Sequencial",
        "pattern_signal": "Padrão",
    }
    return mapping.get(signal_name, signal_name.replace("_", " ").strip().title())


def _signal_explanation(signal_name: str) -> str:
    explanations = {
        "identifier_signal": "valores quase únicos e estáveis, com perfil de identificador",
        "high_cardinality_signal": "alta diversidade de valores na coluna",
        "near_unique_conflict": "coluna quase única com fuga localizada (duplicado ou nulo pontual)",
        "sequential_signal": "progressão sequencial consistente",
        "pattern_signal": "formato recorrente dominante nos valores",
    }
    return explanations.get(signal_name, "assinatura estrutural detectada")


def _collect_triggered_signal_names(column_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(column_payload, dict):
        return []
    heuristics = column_payload.get("heuristics") or []
    names: list[str] = []
    for item in heuristics:
        if not isinstance(item, dict) or not item.get("triggered"):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _collect_unit_signals(unit_payload: dict[str, Any] | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    if not isinstance(unit_payload, dict):
        return counter
    columns = unit_payload.get("columns") or {}
    if not isinstance(columns, dict):
        return counter
    for column in columns.values():
        for signal in _collect_triggered_signal_names(column if isinstance(column, dict) else None):
            counter[signal] += 1
    return counter


def _heuristic_by_name(column_payload: dict[str, Any] | None, heuristic_name: str) -> dict[str, Any]:
    if not isinstance(column_payload, dict):
        return {}
    heuristics = column_payload.get("heuristics") or []
    for item in heuristics:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") == heuristic_name:
            return item
    return {}


def _build_synthetic_signatures(
    *,
    column_payload: dict[str, Any] | None,
    values: list[Any],
    selected_column: str,
    standardized_columns: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(column_payload, dict):
        return []
    normalized = ["∅" if value in (None, "") else str(value) for value in values]
    counter = Counter(normalized)
    total_rows = max(sum(int(count) for count in counter.values()), 1)
    non_null_tokens = [token for token in normalized if token != "∅"]
    non_null_count = len(non_null_tokens)
    non_null_counter = Counter(non_null_tokens)
    distinct_non_null = len(non_null_counter)
    null_rows = int(counter.get("∅", 0))
    empty_string_rows = sum(1 for value in values if value == "")

    layer1 = column_payload.get("layer1_metrics") or {}
    layer2 = column_payload.get("layer2_metrics") or {}
    unique_ratio = float(layer1.get("unique_ratio") or ((distinct_non_null / total_rows) if total_rows else 0.0))
    null_ratio = float(layer1.get("null_ratio") or (null_rows / total_rows))
    numeric_ratio = float(layer2.get("numeric_ratio") or 0.0)
    alpha_ratio = float(layer2.get("alpha_ratio") or 0.0)
    empty_string_ratio = (empty_string_rows / total_rows) if total_rows else 0.0
    triggered = set(_collect_triggered_signal_names(column_payload))

    existing_types = {
        str(item.get("type") or item.get("tipo") or "").strip().lower()
        for item in _collect_column_decisions(column_payload)
        if isinstance(item, dict)
    }
    signatures: list[dict[str, Any]] = []

    def _preview_from_counter(source_counter: Counter[str], *, limit: int = 5, reverse: bool = True) -> list[dict[str, Any]]:
        items = sorted(source_counter.items(), key=lambda kv: (-kv[1], kv[0]) if reverse else (kv[1], kv[0]))
        return [{"value": key, "frequency": int(freq)} for key, freq in items[:limit]]

    def _append(signature: dict[str, Any]) -> None:
        sig_type = str(signature.get("type") or signature.get("tipo") or "").strip().lower()
        if sig_type and sig_type in existing_types:
            return
        if not isinstance(signature.get("evidencia"), dict):
            preview = signature.get("preview") if isinstance(signature.get("preview"), list) else []
            sample = [
                str(item.get("value") or "")
                for item in preview[:5]
                if isinstance(item, dict) and str(item.get("value") or "").strip()
            ]
            signature["evidencia"] = {
                "descricao": str(signature.get("description") or ""),
                "camada_origem": "coluna",
                "sinais": [],
                "amostra": sample,
            }
        if not isinstance(signature.get("transicoes_permitidas"), list):
            path_map = {
                "valor/celula": "valor_celula",
                "novo_recorte": "recorte",
                "create_base_from_slice": "subconjunto",
            }
            paths = signature.get("paths") if isinstance(signature.get("paths"), list) else []
            signature["transicoes_permitidas"] = [
                {"destino": path_map.get(str(path), str(path)), "motivo": "transição estrutural"}
                for path in paths
                if str(path).strip()
            ]
        if sig_type:
            existing_types.add(sig_type)
        signatures.append(signature)

    # near_unique escape -> conflict
    duplicate_values = [token for token, count in counter.items() if int(count) > 1 and token != "∅"]
    duplicate_rows = sum(int(counter.get(token, 0)) for token in duplicate_values)
    has_escape = duplicate_rows > 0 or null_rows > 0
    if unique_ratio >= 0.98 and has_escape and "conflict" not in existing_types and "conflito" not in existing_types:
        escape_values = sorted(duplicate_values, key=lambda token: (-int(counter.get(token, 0)), token))
        if null_rows > 0:
            escape_values = ["∅", *escape_values]
        preview = [{"value": token, "frequency": int(counter.get(token, 0))} for token in escape_values[:5]]
        _append(
            {
                "id": "conflict_near_unique_escape",
                "tipo": "conflito",
                "type": "conflict",
                "description": "Fuga localizada em coluna near-unique.",
                "prioridade": "alta",
                "preview": preview,
                "paths": ["valor/celula", "novo_recorte"],
                "metadata": {
                    "name": "near_unique_escape",
                    "conflict_values": escape_values,
                    "escape_rows": duplicate_rows + null_rows,
                    "escape_ratio": ((duplicate_rows + null_rows) / total_rows) if total_rows else 0.0,
                },
            }
        )

    # candidate_key
    if (
        unique_ratio > 0.98
        and null_ratio <= 0.05
        and ("identifier_signal" in triggered or "high_cardinality_signal" in triggered)
    ):
        _append(
            {
                "id": "candidate_key_signature",
                "tipo": "candidate_key",
                "type": "candidate_key",
                "description": "Coluna quase única com comportamento de identificador.",
                "prioridade": "alta",
                "preview": _preview_from_counter(non_null_counter, limit=5, reverse=False),
                "paths": ["valor/celula", "novo_recorte", "create_base_from_slice"],
                "metadata": {
                    "unique_ratio": unique_ratio,
                    "null_ratio": null_ratio,
                    "impact_rows": distinct_non_null,
                    "impact_ratio": (distinct_non_null / total_rows) if total_rows else 0.0,
                    "slice_type": "candidate_key_group",
                },
            }
        )

    pattern_entry = _heuristic_by_name(column_payload, "pattern_signal")
    pattern_evidence = pattern_entry.get("evidence") if isinstance(pattern_entry.get("evidence"), dict) else {}
    pattern_ratio = float(pattern_evidence.get("match_ratio") or 0.0)
    fixed_length = bool(pattern_evidence.get("fixed_length"))
    fixed_length_value = pattern_evidence.get("fixed_length_value")
    if "pattern_signal" in triggered and pattern_ratio >= 0.7:
        # format_domain
        if pattern_ratio >= 0.8:
            _append(
                {
                    "id": "format_domain_signature",
                    "tipo": "format_domain",
                    "type": "format_domain",
                    "description": "Formato dominante detectado na coluna.",
                    "prioridade": "media",
                    "preview": _preview_from_counter(non_null_counter, limit=5, reverse=True),
                    "paths": ["valor/celula", "novo_recorte"],
                    "metadata": {
                        "match_ratio": pattern_ratio,
                        "impact_ratio": pattern_ratio,
                        "impact_rows": int(round(non_null_count * pattern_ratio)),
                        "slice_type": "format_domain_group",
                    },
                }
            )
        # format_escape
        escape_rows = 0
        escape_preview: list[dict[str, Any]] = []
        if fixed_length and fixed_length_value is not None:
            try:
                expected_length = int(fixed_length_value)
            except (TypeError, ValueError):
                expected_length = None
            mismatch_counter = Counter(
                token
                for token in non_null_tokens
                if expected_length is not None and len(token) != expected_length
            )
            escape_rows = sum(int(freq) for freq in mismatch_counter.values())
            escape_preview = _preview_from_counter(mismatch_counter, limit=5, reverse=True)
        else:
            estimated_escape_rows = int(round(non_null_count * (1.0 - pattern_ratio)))
            if estimated_escape_rows > 0:
                escape_rows = estimated_escape_rows
                escape_preview = _preview_from_counter(non_null_counter, limit=5, reverse=False)
        if escape_rows > 0:
            _append(
                {
                    "id": "format_escape_signature",
                    "tipo": "format_escape",
                    "type": "format_escape",
                    "description": "Valores fora do padrão dominante de formato.",
                    "prioridade": "media",
                    "preview": escape_preview,
                    "paths": ["valor/celula", "novo_recorte", "create_base_from_slice"],
                    "metadata": {
                        "escape_rows": escape_rows,
                        "escape_ratio": (escape_rows / total_rows) if total_rows else 0.0,
                        "slice_type": "format_escape_group",
                    },
                }
            )

    # sparse_field
    if null_ratio > 0.8 or empty_string_ratio > 0.8:
        non_null_preview = _preview_from_counter(non_null_counter, limit=5, reverse=True)
        _append(
            {
                "id": "sparse_field_signature",
                "tipo": "sparse_field",
                "type": "sparse_field",
                "description": "Predominância de ausência na coluna.",
                "prioridade": "alta",
                "preview": non_null_preview,
                "paths": ["valor/celula", "novo_recorte"],
                "metadata": {
                    "null_ratio": null_ratio,
                    "empty_string_ratio": empty_string_ratio,
                    "impact_ratio": max(null_ratio, empty_string_ratio),
                    "impact_rows": int(round(total_rows * max(null_ratio, empty_string_ratio))),
                    "slice_type": "sparse_field_group",
                },
            }
        )

    # mixed_representation
    max_ratio = max(numeric_ratio, alpha_ratio)
    min_ratio = min(numeric_ratio, alpha_ratio)
    if max_ratio < 0.8 and min_ratio > 0.1:
        _append(
            {
                "id": "mixed_representation_signature",
                "tipo": "mixed_representation",
                "type": "mixed_representation",
                "description": "Representação mista detectada na coluna.",
                "prioridade": "media",
                "preview": _preview_from_counter(non_null_counter, limit=5, reverse=True),
                "paths": ["valor/celula", "novo_recorte"],
                "metadata": {
                    "numeric_ratio": numeric_ratio,
                    "alpha_ratio": alpha_ratio,
                    "impact_ratio": 1.0 - max_ratio,
                    "slice_type": "mixed_representation_group",
                },
            }
        )

    # referential_candidate (same table)
    if isinstance(standardized_columns, dict):
        current_set = {token for token in non_null_tokens if token.strip()}
        current_cardinality = max(len(current_set), 1)
        best_match: dict[str, Any] | None = None
        for other_name, other_values in standardized_columns.items():
            if str(other_name) == str(selected_column) or not isinstance(other_values, list):
                continue
            other_set = {str(item) for item in other_values if item not in (None, "") and str(item).strip()}
            if not other_set:
                continue
            shared = current_set & other_set
            if not shared:
                continue
            overlap = len(shared) / max(min(len(current_set), len(other_set)), 1)
            card_ratio = current_cardinality / max(len(other_set), 1)
            if overlap < 0.12 or not (0.5 <= card_ratio <= 2.0):
                continue
            candidate = {
                "other_column": str(other_name),
                "overlap": overlap,
                "card_ratio": card_ratio,
                "values": sorted(shared)[:5],
            }
            if best_match is None or float(candidate["overlap"]) > float(best_match["overlap"]):
                best_match = candidate
        if best_match:
            preview = [{"value": value, "frequency": int(counter.get(value, 1))} for value in best_match["values"]]
            _append(
                {
                    "id": "referential_candidate_signature",
                    "tipo": "referential_candidate",
                    "type": "referential_candidate",
                    "description": "Possível relação estrutural com outra coluna.",
                    "prioridade": "media",
                    "preview": preview,
                    "paths": ["valor/celula", "novo_recorte", "create_base_from_slice"],
                    "metadata": {
                        "target_column": best_match["other_column"],
                        "overlap_ratio": best_match["overlap"],
                        "cardinality_ratio": best_match["card_ratio"],
                        "impact_ratio": best_match["overlap"],
                        "slice_type": "referential_candidate_group",
                    },
                }
            )

    return signatures


def _infer_source_type_from_filename(current_source_type: str, filename: str) -> str:
    if current_source_type and current_source_type != DEFAULT_SOURCE_TYPE:
        return current_source_type
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return "csv"
    if ext == ".parquet":
        return "parquet"
    if ext in {".db", ".sqlite", ".sqlite3"}:
        return "sqlite"
    return current_source_type or DEFAULT_SOURCE_TYPE


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
    except Exception:  # pragma: no cover - preview must stay resilient
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
        signal_value_raw = unit.get("signal")
        signal_value: float | None = None
        if isinstance(signal_value_raw, (int, float)):
            signal_value = max(0.0, min(float(signal_value_raw), 1.0))
        elif isinstance(signal_value_raw, str):
            try:
                signal_value = max(0.0, min(float(signal_value_raw), 1.0))
            except ValueError:
                signal_value = None
        columns_preview_items = [str(item).strip() for item in (unit.get("columns_preview") or []) if str(item).strip()]
        columns_preview = ", ".join(columns_preview_items[:4]) if columns_preview_items else ""
        meta_parts: list[str] = []
        if signal_value is not None:
            meta_parts.append(f"signal {signal_value:.2f}")
        elif row_count is not None:
            meta_parts.append(f"{row_count} linhas")
        if column_count is not None:
            meta_parts.append(f"{column_count} colunas")
        table_summary_line = " · ".join(meta_parts).strip()
        meta_html = f'<div class="metric-meta">{escape(table_summary_line)}</div>' if table_summary_line else ""
        preview_html = f'<div class="metric-preview">{escape(columns_preview)}</div>' if columns_preview else ""
        cards.append(
            f"""
            <a class="metric-link" href="{escape(_detail_href(unit_name))}">
              <section class="metric-card"{(f' data-summary-line="{escape(table_summary_line)}"' if table_summary_line else "")}>
                <div class="metric-body">
                  {_render_card_header(
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
        cards.append(f'<div class="small">+ {len(ranked_previews) - 9} {escape(_ui(lang)["units"])} adicionais.</div>')

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
                for column_name in shared_columns:
                    left_values = left_columns.get(column_name) or []
                    right_values = right_columns.get(column_name) or []
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

    if result and result.get("tabela_previas") and summary_mode:
        lines.append("")
        lines.append("Cards da origem:")
        ranked_units = _rank_unit_previews(result["tabela_previas"])[:9]
        for index, unit in enumerate(ranked_units, start=1):
            unit_name = str(unit.get("tabela_nome") or "—")
            row_count = unit.get("row_count")
            column_count = unit.get("column_count")
            priority = _priority_label(index, float(unit.get("importance_score") or 0.0))
            lines.append(
                f"- {unit_name} [{priority}] · {row_count if row_count is not None else '—'} linhas · "
                f"{column_count if column_count is not None else '—'} colunas"
            )

    if detail_mode and result and result.get("tabelas"):
        lines.append("")
        lines.append("Resumo da tabela:")
        for unit in result["tabelas"][:1]:
            unit_name = str(unit.get("tabela_nome") or selected_unit or "—")
            metrics = unit.get("metrics_summary") or []
            lines.append(f"- {unit_name}")
            if metrics:
                lines.extend(f"  {line}" for line in metrics[:3])

    if column_mode and result and result.get("tabelas") and selected_column:
        units = result.get("tabelas") or []
        current = None
        for unit in units:
            if str(unit.get("tabela_nome") or "") == selected_unit:
                current = unit
                break
        if current is None and units:
            current = units[0]
        columns = (current or {}).get("columns") or {}
        column = columns.get(selected_column) if isinstance(columns, dict) else None
        recortes = _collect_column_decisions(column if isinstance(column, dict) else None)
        tipo_labels = {
            "dominancia": "dominância",
            "excecao": "exceção",
            "conflito": "conflito",
            "ausencia": "ausência",
            "padrao": "padrão",
            "identidade_estrutural": "identidade estrutural",
        }
        prioridade_labels = {"alta": "alta", "media": "média", "baixa": "baixa"}
        destino_labels = {
            "valor_celula": "valor/célula",
            "recorte": "novo recorte",
            "subconjunto": "subconjunto",
            "caractere": "caractere",
        }
        lines.append("")
        lines.append("Escopo da coluna:")
        lines.append(f"- unidade: {str((current or {}).get('unit_name') or selected_unit or '—')}")
        lines.append(f"- coluna: {selected_column}")
        lines.append(f"- decisões de aprofundamento: {len(recortes)}")
        if recortes:
            prioridade_rank = {"alta": 0, "media": 1, "baixa": 2}
            ordered = sorted(
                recortes,
                key=lambda item: (
                    prioridade_rank.get(str(item.get("prioridade") or ""), 9),
                    str(item.get("tipo") or ""),
                ),
            )[:5]
            lines.append("")
            lines.append("Decisões disponíveis:")
            for recorte in ordered:
                tipo = str(recorte.get("tipo") or "recorte")
                prioridade = str(recorte.get("prioridade") or "media")
                evidencia = recorte.get("evidencia") if isinstance(recorte.get("evidencia"), dict) else {}
                descricao = str(evidencia.get("descricao") or "")
                amostra = [str(item) for item in (evidencia.get("amostra") or [])][:2]
                transicoes = recorte.get("transicoes_permitidas") if isinstance(recorte.get("transicoes_permitidas"), list) else []
                destinos = []
                for transition in transicoes:
                    if not isinstance(transition, dict):
                        continue
                    destino = str(transition.get("destino") or "").strip()
                    if destino and destino not in destinos:
                        destinos.append(destino)
                lines.append(f"- {tipo_labels.get(tipo, tipo)} [{prioridade_labels.get(prioridade, prioridade)}]")
                if descricao:
                    lines.append(f"  {descricao}")
                if amostra:
                    lines.append(f"  amostra: {', '.join(amostra)}")
                if destinos:
                    human_paths = [destino_labels.get(item, item) for item in destinos]
                    lines.append(f"  caminhos: {', '.join(human_paths)}")
        else:
            lines.append("  sem decisões de aprofundamento disponíveis nesta coluna.")

    if unit_names and summary_mode:
        lines.append("")
        lines.append(f"Lista completa de unidades: {', '.join(unit_names[:9])}")

    return "\n".join(lines).strip()


def _build_source_result(
    source_type: str,
    source_path: str,
    *,
    analyze_units: bool,
    unit_name: str | None = None,
    unit_limit: int | None = None,
) -> dict[str, Any]:
    return run_build_source_result(
        source_type,
        source_path,
        analyze_units=analyze_units,
        resolve_source_fn=_resolve_source,
        preview_source_unit_fn=_preview_source_unit,
        ordered_unit_names_fn=_ordered_unit_names,
        attach_internal_cuts_fn=attach_internal_cuts,
        source_summary_text_fn=source_summary_text,
        resolve_optional_limit_fn=resolve_optional_limit,
        unit_importance_score_fn=_unit_importance_score,
        unit_name=unit_name,
        unit_limit=unit_limit,
    )


def _build_tabular_result(unit_name: str, columns_text: str, rows_text: str) -> dict[str, Any]:
    return run_build_tabular_result(
        unit_name,
        columns_text,
        rows_text,
        parse_columns_fn=_parse_columns,
        parse_rows_fn=_parse_rows,
        inline_tabular_unit_cls=_InlineTabularUnit,
    )


def _build_ai_result(prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
    return run_build_ai_result(prompt, system_prompt=system_prompt)


def _build_health_result() -> dict[str, str]:
    return run_build_health_result()


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


def _collect_column_decisions(column_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(column_payload, dict):
        return []
    raw = column_payload.get("recortes_internos")
    if raw is None:
        raw = column_payload.get("recortes")
    if not isinstance(raw, (list, tuple)):
        return []
    legacy_type_map = {
        "dominancia": "dominance",
        "excecao": "exception",
        "conflito": "conflict",
        "ausencia": "absence",
    }
    signature_type_map = {
        "dominance": "dominancia",
        "exception": "excecao",
        "conflict": "conflito",
        "relation": "relacao",
        "absence": "ausencia",
    }
    path_map = {
        "valor_celula": "valor/celula",
        "recorte": "novo_recorte",
        "subconjunto": "subconjunto",
        "caractere": "caractere",
    }
    reverse_path_map = {
        "valor/celula": "valor_celula",
        "novo_recorte": "recorte",
        "subconjunto": "subconjunto",
        "caractere": "caractere",
    }
    decisions: list[dict[str, Any]] = []
    for item in raw:
        current: dict[str, Any] | None = None
        if isinstance(item, dict):
            current = dict(item)
        else:
            model_dump = getattr(item, "model_dump", None)
            if callable(model_dump):
                dumped = model_dump()
                if isinstance(dumped, dict):
                    current = dumped
        if current is None:
            continue
        if not current.get("tipo"):
            current["tipo"] = signature_type_map.get(str(current.get("type") or ""), str(current.get("type") or ""))
        if not current.get("type"):
            current["type"] = legacy_type_map.get(str(current.get("tipo") or ""), str(current.get("tipo") or ""))
        if not current.get("description"):
            evidencia = current.get("evidencia") if isinstance(current.get("evidencia"), dict) else {}
            current["description"] = str(evidencia.get("descricao") or "")
        if not current.get("evidencia"):
            preview = current.get("preview") if isinstance(current.get("preview"), list) else []
            preview_tokens = [
                str(item.get("value") or "")
                for item in preview[:3]
                if isinstance(item, dict) and str(item.get("value") or "").strip()
            ]
            current["evidencia"] = {
                "descricao": str(current.get("description") or ""),
                "camada_origem": "coluna",
                "sinais": [],
                "amostra": preview_tokens,
            }
        if not isinstance(current.get("preview"), list):
            current["preview"] = []
        if not current.get("paths"):
            transicoes = current.get("transicoes_permitidas") if isinstance(current.get("transicoes_permitidas"), list) else []
            current["paths"] = [
                path_map.get(str(transition.get("destino") or ""), str(transition.get("destino") or ""))
                for transition in transicoes
                if isinstance(transition, dict) and str(transition.get("destino") or "").strip()
            ]
        if not current.get("transicoes_permitidas"):
            paths = current.get("paths") if isinstance(current.get("paths"), list) else []
            current["transicoes_permitidas"] = [
                {
                    "destino": reverse_path_map.get(str(path or ""), str(path or "")),
                    "alvo_id": str(current.get("id") or ""),
                    "motivo": "transição estrutural",
                }
                for path in paths
                if str(path or "").strip()
            ]
        if current.get("impact") is None:
            current["impact"] = {
                "alta": 0.9,
                "media": 0.6,
                "baixa": 0.3,
            }.get(str(current.get("prioridade") or ""), 0.5)
        if not current.get("prioridade"):
            impact = float(current.get("impact") or 0.0)
            if impact >= 0.75:
                current["prioridade"] = "alta"
            elif impact >= 0.45:
                current["prioridade"] = "media"
            else:
                current["prioridade"] = "baixa"
        if "slice_type" not in current:
            current["slice_type"] = None
        if not isinstance(current.get("metadata"), dict):
            current["metadata"] = {}
        decisions.append(current)
    return decisions


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
    ui = _ui(lang)
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
    crumbs.append(_pill(str(source_display or ui["source"]), f"/?{urlencode(summary_query)}", active=not selected))
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
        f'<nav class="path-bar"><span class="path-label">{escape(ui["path"])}:</span>'
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
    ui = _ui(lang)

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
        ("origem", ui["layer_origin"], "estado inicial"),
        ("base", "base", "nova base ativa"),
        ("tabela", ui["layer_table"], "estado tabular"),
        ("coluna", ui["layer_column"], "estado de coluna"),
        ("recorte", ui["layer_recorte"], "decisão de aprofundamento"),
        ("valor_celula", ui["layer_value_cell"], "estado de valor/célula"),
        ("caractere", ui["layer_character"], "estado de caractere"),
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
        f'<section class="layers-bar"><div class="results-title">{escape(ui["layers"])}</div>'
        f'<div class="layers-row">{"".join(items)}</div>'
        f'<div class="small" style="margin-top: 8px;">{focus_note}</div>'
        f"{persistence_note}"
        f'</section>'
    )


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
    column_order = standardized.get("column_order") or []
    standardized_columns = standardized.get("columns") or {}
    table_lines: list[str] = [
        f"<div class='origin-line'>Caminho: origem / {escape(unit_label)}</div>",
    ]
    metrics_lines: list[str] = []
    if row_count is not None:
        metrics_lines.append(f"<div class='origin-line'>Linhas: {row_count}</div>")
    if column_count is not None:
        metrics_lines.append(f"<div class='origin-line'>Colunas: {column_count}</div>")
    if row_count is not None and column_count is not None:
        metrics_lines.append(f"<div class='origin-line'>Células estimadas: {row_count * column_count}</div>")
    if isinstance(column_order, list) and column_order:
        metrics_lines.append(
            "<div class='origin-line'>Ordem das colunas: "
            + escape(", ".join(str(item) for item in column_order))
            + "</div>"
        )
    if not metrics_lines:
        metrics_lines.append(f"<div class='origin-line'>{escape(_ui(lang)['metrics_pending'])}</div>")

    table_signal_lines: list[str] = [
        "<div class='origin-line'>Nenhum sinal de escopo de tabela calculado no momento.</div>"
    ]

    relation_count = 0
    relation_examples: list[str] = []
    if isinstance(standardized_columns, dict) and len(standardized_columns) >= 2:
        overlap_candidates: list[tuple[str, str, int, float]] = []
        column_items = [(str(name), values) for name, values in standardized_columns.items() if isinstance(values, list)]
        for left_idx in range(len(column_items)):
            left_name, left_values = column_items[left_idx]
            left_set = {str(value) for value in left_values if value not in (None, "")}
            if not left_set:
                continue
            for right_idx in range(left_idx + 1, len(column_items)):
                right_name, right_values = column_items[right_idx]
                right_set = {str(value) for value in right_values if value not in (None, "")}
                if not right_set:
                    continue
                shared = left_set & right_set
                if not shared:
                    continue
                denominator = max(min(len(left_set), len(right_set)), 1)
                overlap = len(shared) / denominator
                if overlap >= 0.12:
                    overlap_candidates.append((left_name, right_name, len(shared), overlap))
        overlap_candidates.sort(key=lambda item: item[3], reverse=True)
        relation_count = len(overlap_candidates)
        relation_examples = [f"{left} ↔ {right}" for left, right, _shared, _overlap in overlap_candidates[:3]]

    signature_lines: list[str] = []
    if relation_count > 0:
        signature_lines.append(f"<div class='origin-line'>Relações entre colunas: {relation_count}</div>")
        if relation_examples:
            signature_lines.append(
                "<div class='origin-line'>Exemplos: " + escape(", ".join(relation_examples)) + "</div>"
            )
    else:
        signature_lines.append("<div class='origin-line'>Nenhuma assinatura de escopo de tabela detectada.</div>")

    table_lines_html = (
        "".join(table_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Métricas</strong></div>"
        + "".join(metrics_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Sinais</strong></div>"
        + "".join(table_signal_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Assinaturas</strong></div>"
        + "".join(signature_lines)
    )

    return f"""
      <div class="results-title">Contexto da tabela</div>
      <section class="origin-overview">
        {table_lines_html}
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
    standardized_columns = (current.get("standardized") or {}).get("columns") or {}
    filtered_indexes: list[int] | None = None
    if relation_column and relation_values_text and isinstance(standardized_columns, dict):
        relation_values = standardized_columns.get(relation_column) or []
        try:
            parsed_values = json.loads(relation_values_text)
        except json.JSONDecodeError:
            parsed_values = []
        allowed = {str(item) for item in parsed_values} if isinstance(parsed_values, list) else set()
        if allowed:
            filtered_indexes = [idx for idx, value in enumerate(relation_values) if str(value) in allowed]
    parsed_filters = _parse_context_filters(context_filters_text)
    if parsed_filters and isinstance(standardized_columns, dict):
        index_pool: set[int] | None = None
        for condition in parsed_filters:
            column_values = standardized_columns.get(condition.column) or []
            if not isinstance(column_values, list) or not column_values:
                continue
            matched: set[int] = set()
            operator = str(condition.operator or "").upper()
            if operator == "=":
                target = str(condition.value)
                matched = {idx for idx, value in enumerate(column_values) if str(value) == target}
            elif operator == "IN" and isinstance(condition.value, (list, tuple)):
                allowed_values = {str(item) for item in condition.value}
                matched = {idx for idx, value in enumerate(column_values) if str(value) in allowed_values}
            if index_pool is None:
                index_pool = matched
            else:
                index_pool &= matched
        if index_pool is not None:
            filtered_indexes = sorted(index_pool) if filtered_indexes is None else sorted(set(filtered_indexes) & index_pool)

    context_query: dict[str, Any] = {}
    if parsed_filters:
        context_query["context_filters"] = context_filters_text
    if recorte_id:
        context_query["recorte_id"] = recorte_id
    if exception_group:
        context_query["exception_group"] = exception_group

    for index, (column_name, column) in enumerate(columns.items(), start=1):
        layer1 = column.get("layer1_metrics") or {}
        layer2 = column.get("layer2_metrics") or {}
        heuristics = column.get("heuristics") or []
        column_values = list(standardized_columns.get(column_name) or [])
        if filtered_indexes is not None:
            column_values = [value for idx, value in enumerate(column_values) if idx in set(filtered_indexes)]
        scoped_values = [value for value in column_values if value not in (None, "")]
        scoped_row_count = max(len(column_values), 1)
        scoped_cardinality = len({str(value) for value in scoped_values})
        scoped_null_ratio = (sum(1 for value in column_values if value in (None, "")) / scoped_row_count) if column_values else 0.0
        scoped_unique_ratio = (scoped_cardinality / scoped_row_count) if column_values else 0.0
        if filtered_indexes is not None:
            cardinality = scoped_cardinality
            null_ratio = scoped_null_ratio
            unique_ratio = scoped_unique_ratio
        else:
            cardinality = int(layer1.get("cardinality") or scoped_cardinality)
            null_ratio = float(layer1.get("null_ratio") or scoped_null_ratio)
            unique_ratio = float(layer1.get("unique_ratio") or scoped_unique_ratio)
        triggered = [str(item.get("name") or "heurística") for item in heuristics if item.get("triggered")]
        signal_labels = [_signal_label(name) for name in triggered]
        signatures_line = " · ".join(signal_labels[:3]) if signal_labels else ""
        recorte_labels: list[str] = []
        recorte_label_map = {
            "dominancia": "Dominância",
            "dominance": "Dominância",
            "excecao": "Exceção",
            "exception": "Exceção",
            "conflito": "Conflito",
            "conflict": "Conflito",
            "ausencia": "Ausência",
            "absence": "Ausência",
            "relacao": "Relações",
            "relation": "Relações",
        }
        recortes = _collect_column_decisions(column if isinstance(column, dict) else None)
        for recorte in recortes:
            tipo_raw = str(recorte.get("tipo") or recorte.get("type") or "").strip().lower()
            if not tipo_raw:
                continue
            label = recorte_label_map.get(tipo_raw, tipo_raw[:1].upper() + tipo_raw[1:])
            metadata = recorte.get("metadata") if isinstance(recorte.get("metadata"), dict) else {}
            mode_count_raw = metadata.get("mode_count")
            if tipo_raw in {"dominancia", "dominance"} and isinstance(mode_count_raw, (int, float)):
                mode_count = int(mode_count_raw)
                label = f"{label}: {mode_count}"
            if label and label not in recorte_labels:
                recorte_labels.append(label)
            if len(recorte_labels) >= 3:
                break
        recortes_line = " · ".join(recorte_labels[:3]) if recorte_labels else ""
        signal_value_raw = column.get("signal")
        signal_value: float | None = None
        if isinstance(signal_value_raw, (int, float)):
            signal_value = max(0.0, min(float(signal_value_raw), 1.0))
        elif isinstance(signal_value_raw, str):
            try:
                signal_value = max(0.0, min(float(signal_value_raw), 1.0))
            except ValueError:
                signal_value = None
        title_text = str(column_name or column.get("column_name") or f"coluna {index}")
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
        query.update(context_query)
        column_cards.append(
            f"""
            <a class="metric-link" href="{escape(f'/?{urlencode(query)}')}" aria-label="{escape(column_name)}">
            <article class="focus-column-card{(' selected-metric' if selected_column == column_name else '')}">
              <div class="focus-column-head">
                {_render_card_header(
                    title=title_text,
                    occurrences=int(cardinality) if cardinality is not None else None,
                    exploration_level=0.0,
                    can_add_to_collection=True,
                    can_share=True,
                    can_mark_seen=True,
                )}
              </div>
              {f"<div class='small'>{escape(signatures_line)}</div>" if signatures_line else ""}
              {f"<div class='small'>{escape(recortes_line)}</div>" if recortes_line else ""}
              <div class="focus-column-stat">nulos {null_ratio:.2f} · únicos {unique_ratio:.2f}</div>
              <div class="metric-action">Abrir coluna</div>
            </article>
            </a>
            """
        )

    relation_cards: list[str] = []
    if isinstance(standardized_columns, dict) and len(standardized_columns) >= 2:
        overlap_candidates: list[dict[str, Any]] = []
        column_items = [(str(name), values) for name, values in standardized_columns.items() if isinstance(values, list)]
        for left_idx in range(len(column_items)):
            left_name, left_values = column_items[left_idx]
            left_set = {str(value) for value in left_values if value not in (None, "")}
            if not left_set:
                continue
            for right_idx in range(left_idx + 1, len(column_items)):
                right_name, right_values = column_items[right_idx]
                right_set = {str(value) for value in right_values if value not in (None, "")}
                if not right_set:
                    continue
                shared = left_set & right_set
                if not shared:
                    continue
                denominator = max(min(len(left_set), len(right_set)), 1)
                overlap = len(shared) / denominator
                if overlap <= 0.0:
                    continue
                overlap_candidates.append(
                    {
                        "left": left_name,
                        "right": right_name,
                        "shared_count": len(shared),
                        "overlap": overlap,
                        "examples": sorted(shared)[:4],
                    }
                )
        overlap_candidates = sorted(overlap_candidates, key=lambda item: float(item["overlap"]), reverse=True)[:6]
        for item in overlap_candidates:
            relation_query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": selected_unit,
                "column_name": item["left"],
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "coluna",
            }
            examples_text = ", ".join(str(value) for value in item["examples"]) or "—"
            relation_cards.append(
                f"""
                <article class="focus-stat-card h-card">
                  <div class="h-card-layout">
                    <div class="h-card-left">
                      <div class="focus-stat-value">{escape(item["left"])} ↔ {escape(item["right"])}</div>
                    </div>
                    <div class="h-card-center">
                      <div class="small">{item["shared_count"]} valores compartilhados · {float(item["overlap"]) * 100:.1f}% de interseção</div>
                      <div class="small" style="margin-top: 8px;">Exemplos: {escape(examples_text)}</div>
                    </div>
                    <div class="h-card-right">
                      <a class="button secondary mini" href="/?{escape(urlencode(relation_query))}">Abrir coluna</a>
                    </div>
                  </div>
                </article>
                """
            )
    relations_section_html = "".join(relation_cards)

    return f"""
      <div class="focus-columns">{''.join(column_cards)}</div>
      {relations_section_html}
    """


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
    if not metrics_lines:
        metrics_lines.append(f"<div class='origin-line'>{escape(_ui(lang)['metrics_pending'])}</div>")

    signal_lines: list[str] = []
    triggered_signals = _collect_triggered_signal_names(column if isinstance(column, dict) else None)
    for signal_name in triggered_signals[:4]:
        signal_lines.append(
            f"<div class='origin-line'>{escape(_signal_label(signal_name))}: {escape(_signal_explanation(signal_name))}</div>"
        )
    if not signal_lines:
        signal_lines.append("<div class='origin-line'>Nenhum sinal de coluna detectado.</div>")

    signature_lines: list[str] = []
    standardized_columns = (standardized.get("columns") or {}) if isinstance(standardized, dict) else {}
    column_decisions = _collect_column_decisions(column if isinstance(column, dict) else None)
    synthetic_signatures = _build_synthetic_signatures(
        column_payload=column if isinstance(column, dict) else None,
        values=values,
        selected_column=str(selected_column),
        standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
    )
    column_decisions = [*column_decisions, *synthetic_signatures]
    if column_decisions:
        signature_types = []
        for item in column_decisions:
            tipo = str(item.get("tipo") or item.get("type") or "").strip().lower()
            if tipo in {"excecao", "exception"}:
                signature_types.append("Exceção")
            elif tipo in {"dominancia", "dominance"}:
                signature_types.append("Dominância")
            elif tipo in {"conflito", "conflict"}:
                signature_types.append("Conflito")
            elif tipo in {"relacao", "relation"}:
                signature_types.append("Relação")
            elif tipo == "candidate_key":
                signature_types.append("Candidate key")
            elif tipo == "format_domain":
                signature_types.append("Format domain")
            elif tipo == "format_escape":
                signature_types.append("Format escape")
            elif tipo == "sparse_field":
                signature_types.append("Sparse field")
            elif tipo == "mixed_representation":
                signature_types.append("Mixed representation")
            elif tipo == "referential_candidate":
                signature_types.append("Referential candidate")
            elif tipo:
                signature_types.append(tipo.title())
        unique_types = list(dict.fromkeys(signature_types))
        if unique_types:
            signature_lines.append(
                f"<div class='origin-line'>Assinaturas na coluna: {len(unique_types)}</div>"
            )
            signature_lines.append(
                "<div class='origin-line'>Tipos: " + escape(", ".join(unique_types)) + "</div>"
            )
    if isinstance(standardized_columns, dict) and selected_column in standardized_columns:
        current_values = standardized_columns.get(selected_column) or []
        current_set = {str(value) for value in current_values if value not in (None, "")}
        relation_hits = 0
        for other_name, other_values in standardized_columns.items():
            if str(other_name) == str(selected_column) or not isinstance(other_values, list):
                continue
            other_set = {str(value) for value in other_values if value not in (None, "")}
            if not current_set or not other_set:
                continue
            shared = current_set & other_set
            if not shared:
                continue
            denominator = max(min(len(current_set), len(other_set)), 1)
            overlap = len(shared) / denominator
            if overlap >= 0.12:
                relation_hits += 1
        if relation_hits > 0:
            signature_lines.append(f"<div class='origin-line'>Relações com outras colunas: {relation_hits}</div>")
    if not signature_lines:
        signature_lines.append("<div class='origin-line'>Nenhuma assinatura de coluna detectada.</div>")

    context_html = (
        "".join(context_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Métricas</strong></div>"
        + "".join(metrics_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Sinais</strong></div>"
        + "".join(signal_lines)
        + "<div class='origin-line' style='margin-top: 10px;'><strong>Assinaturas</strong></div>"
        + "".join(signature_lines)
    )

    return f"""
      <div class="results-title">Contexto da coluna</div>
      <section class="origin-overview">
        {context_html}
      </section>
    """


def _render_focused_column_values(
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
    column_payload = columns.get(selected_column) if isinstance(columns, dict) else None
    standardized = current.get("standardized") or {}
    values = list((standardized.get("columns") or {}).get(selected_column) or [])
    recortes = _collect_column_decisions(column_payload if isinstance(column_payload, dict) else None)
    layer1_metrics = (column_payload or {}).get("layer1_metrics") if isinstance(column_payload, dict) else {}
    unique_ratio = float((layer1_metrics or {}).get("unique_ratio") or 0.0)
    full_counter = Counter(cell_value_identity_token(value) for value in values)
    all_rare_values_full = sorted([token for token, count in full_counter.items() if int(count) <= 1], key=str)
    total_rows_full = max(sum(int(count) for count in full_counter.values()), 1)
    rare_rows_full = sum(int(full_counter.get(token, 0)) for token in all_rare_values_full)
    rare_group_ratio = rare_rows_full / total_rows_full

    standardized_columns = (standardized.get("columns") or {}) if isinstance(standardized, dict) else {}
    synthetic_signatures = _build_synthetic_signatures(
        column_payload=column_payload if isinstance(column_payload, dict) else None,
        values=values,
        selected_column=str(selected_column or ""),
        standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
    )
    if synthetic_signatures:
        recortes.extend(synthetic_signatures)

    parsed_filters = _parse_context_filters(context_filters_text)
    technical_payload = {
        "selected_unit": current.get("tabela_nome") or selected_unit,
        "selected_column": selected_column,
        "row_count": len(values),
        "recortes_internos": recortes[:5],
        "selected_value": selected_value,
        "selected_value_id": selected_value_id,
        "slice_mode": slice_mode,
        "value_cards": [],
    }

    def _raw_value_from_token(token: str) -> Any:
        if token == "__none__":
            return None
        if token == "__empty__":
            return ""
        return token

    tipo_labels = {
        "dominancia": "dominância",
        "excecao": "exceção",
        "conflito": "conflito",
        "ausencia": "ausência",
        "padrao": "padrão",
        "identidade_estrutural": "identidade estrutural",
        "candidate_key": "Candidate key",
        "format_domain": "Format domain",
        "format_escape": "Format escape",
        "sparse_field": "Sparse field",
        "mixed_representation": "Mixed representation",
        "referential_candidate": "Referential candidate",
    }
    prioridade_rank = {"alta": 0, "media": 1, "baixa": 2}
    destino_labels = {
        "subconjunto": "Subconjunto",
        "recorte": "Novo recorte",
        "valor_celula": "Valor/célula",
        "caractere": "Caractere",
    }

    ordered_recortes = sorted(
        recortes,
        key=lambda item: (
            prioridade_rank.get(str(item.get("prioridade") or ""), 9),
            str(item.get("tipo") or ""),
        ),
    )[:5]

    relation_targets: list[dict[str, Any]] = []
    base_values = {
        str(value)
        for value in values
        if value not in (None, "")
    }
    if base_values and isinstance(result.get("tabelas"), list):
        for unit in result.get("tabelas") or []:
            table_name = str(unit.get("tabela_nome") or "")
            if not table_name or table_name == selected_unit:
                continue
            unit_columns = (unit.get("standardized") or {}).get("columns") or {}
            if not isinstance(unit_columns, dict):
                continue
            for target_column, target_values in unit_columns.items():
                target_set = {
                    str(item)
                    for item in (target_values or [])
                    if item not in (None, "")
                }
                if not target_set:
                    continue
                overlap = base_values & target_set
                denom = max(min(len(base_values), len(target_set)), 1)
                overlap_ratio = len(overlap) / denom
                if overlap_ratio <= 0.1:
                    continue
                relation_targets.append(
                    {
                        "table": table_name,
                        "column": str(target_column),
                        "overlap": overlap_ratio,
                        "values": sorted(overlap)[:50],
                    }
                )
    relation_targets = sorted(relation_targets, key=lambda item: float(item.get("overlap") or 0.0), reverse=True)[:5]
    if not recortes and not relation_targets:
        return """
      <section class="focus-unit">
        <div class="results-title">Contexto do valor / célula</div>
        <div class="small" style="margin-top: 2px;">Ainda não há decisões de aprofundamento disponíveis nesta coluna.</div>
      </section>
    """
    decisions_count = len(ordered_recortes) + (1 if relation_targets else 0)
    has_intermediate_layer = decisions_count > 1
    relation_only_mode = decisions_count == 1 and not ordered_recortes and bool(relation_targets)
    def _recorte_decision_kind(recorte_item: dict[str, Any] | None) -> str:
        if not isinstance(recorte_item, dict):
            return ""
        tipo_local = str(recorte_item.get("tipo") or "").strip().lower()
        metadata_local = recorte_item.get("metadata") if isinstance(recorte_item.get("metadata"), dict) else {}
        type_local = str(metadata_local.get("type") or "").strip().lower()
        name_local = str(metadata_local.get("name") or "").strip().lower()
        if tipo_local == "excecao":
            return "exception"
        if tipo_local == "conflito" or type_local == "conflict" or name_local == "conflict_group":
            return "conflict"
        if tipo_local == "dominancia" or type_local == "dominant" or name_local == "dominant_values":
            return "dominance"
        if tipo_local == "ausencia":
            return "missing"
        return ""

    normalized_decision_type = str(decision_type or "").strip().lower()
    active_recorte = None
    if ordered_recortes:
        if has_intermediate_layer:
            active_recorte = next(
                (item for item in ordered_recortes if str(item.get("id") or "") == recorte_id),
                None,
            )
            if active_recorte is None and normalized_decision_type:
                active_recorte = next(
                    (
                        item
                        for item in ordered_recortes
                        if _recorte_decision_kind(item) == normalized_decision_type
                    ),
                    None,
                )
            if active_recorte is None and signature_path == "valor/celula":
                # Fallback neutro: usa o primeiro recorte que expõe caminho valor/célula.
                for item in ordered_recortes:
                    item_paths = item.get("paths") if isinstance(item.get("paths"), list) else []
                    if "valor/celula" in {str(path).strip() for path in item_paths}:
                        active_recorte = item
                        break
        else:
            active_recorte = ordered_recortes[0]

    recorte_cards = []
    for recorte in ordered_recortes:
        recorte_item_id = str(recorte.get("id") or "").strip()
        tipo = str(recorte.get("tipo") or "recorte")
        prioridade = str(recorte.get("prioridade") or "media")
        evidencia = recorte.get("evidencia") if isinstance(recorte.get("evidencia"), dict) else {}
        descricao = str(evidencia.get("descricao") or "Sem descrição de evidência.")
        preview_items = recorte.get("preview") if isinstance(recorte.get("preview"), list) else []
        transicoes = recorte.get("transicoes_permitidas") if isinstance(recorte.get("transicoes_permitidas"), list) else []
        destinos: list[str] = []
        for transition in transicoes:
            if not isinstance(transition, dict):
                continue
            destino = str(transition.get("destino") or "").strip()
            if destino and destino not in destinos:
                destinos.append(destino)
        caminho_labels = [destino_labels.get(destino, destino) for destino in destinos]
        caminhos_block = ""
        preview_block = ""
        parsed_preview: list[str] = []
        for item in preview_items[:5]:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            frequency = int(item.get("frequency") or 0)
            if not value:
                continue
            parsed_preview.append(f"{value} ({frequency})")
        if parsed_preview:
            preview_block = "<div class='small'>Exemplos: " + escape(", ".join(parsed_preview)) + "</div>"
        title_text = tipo_labels.get(tipo, tipo)
        if title_text:
            title_text = title_text[:1].upper() + title_text[1:]

        repeat_count_label = "Assinatura se repete: —"
        share_label = "Parcela do todo: —"
        occurrence_count: int | None = None
        exploration_level = 0.0
        decision_type_token = {
            "excecao": "exception",
            "exception": "exception",
            "dominancia": "dominance",
            "dominance": "dominance",
            "conflito": "conflict",
            "conflict": "conflict",
            "ausencia": "missing",
            "absence": "missing",
        }.get(str(tipo).strip().lower(), "")

        if tipo == "excecao":
            exception_values = [token for token, count in full_counter.items() if int(count) <= 1]
            exception_rows = sum(int(full_counter.get(token, 0)) for token in exception_values)
            exception_ratio_local = (exception_rows / total_rows_full) if total_rows_full > 0 else 0.0
            occurrence_count = len(exception_values)
            exploration_level = exception_ratio_local
            repeat_count_label = f"Assinatura se repete: {len(exception_values)} exceções"
            share_label = f"Parcela do todo: {exception_ratio_local * 100:.1f}% da coluna"
        elif tipo == "dominancia":
            metadata = recorte.get("metadata") if isinstance(recorte.get("metadata"), dict) else {}
            dominant_count_raw = metadata.get("mode_count")
            dominant_count = int(dominant_count_raw) if isinstance(dominant_count_raw, (int, float)) else len(preview_items)
            dominant_rows = sum(int(item.get("frequency") or 0) for item in preview_items if isinstance(item, dict))
            dominant_ratio = (dominant_rows / total_rows_full) if total_rows_full > 0 else 0.0
            occurrence_count = dominant_count
            exploration_level = dominant_ratio
            repeat_count_label = f"Padrões dominantes: {dominant_count}"
            share_label = f"Parcela do todo: {dominant_ratio * 100:.1f}% da coluna"
        elif tipo == "conflito":
            conflict_values_meta = (
                recorte.get("metadata", {}).get("conflict_values")
                if isinstance(recorte.get("metadata"), dict)
                else []
            )
            if isinstance(conflict_values_meta, list) and conflict_values_meta:
                conflict_values_norm = [str(item) for item in conflict_values_meta if str(item).strip()]
                conflict_count = len(conflict_values_norm)
                conflict_rows = sum(int(full_counter.get(token, 0)) for token in conflict_values_norm)
            else:
                conflict_count = len(preview_items)
                conflict_rows = sum(int(item.get("frequency") or 0) for item in preview_items if isinstance(item, dict))
            conflict_ratio = (conflict_rows / total_rows_full) if total_rows_full > 0 else 0.0
            occurrence_count = conflict_count
            exploration_level = conflict_ratio
            repeat_count_label = f"Assinatura se repete: {conflict_count} conflitos"
            share_label = f"Parcela do todo: {conflict_ratio * 100:.1f}% da coluna"
        elif tipo in {
            "candidate_key",
            "format_domain",
            "format_escape",
            "sparse_field",
            "mixed_representation",
            "referential_candidate",
        }:
            metadata = recorte.get("metadata") if isinstance(recorte.get("metadata"), dict) else {}
            impact_rows = metadata.get("impact_rows")
            impact_ratio = metadata.get("impact_ratio")
            if impact_rows is not None:
                repeat_count_label = f"Assinatura se repete: {int(impact_rows)} ocorrências"
                occurrence_count = int(impact_rows)
            if impact_ratio is not None:
                share_label = f"Parcela do todo: {float(impact_ratio) * 100:.1f}% da coluna"
                exploration_level = float(impact_ratio)
        card_header_html = _render_card_header(
            title=title_text,
            occurrences=occurrence_count,
            exploration_level=0.0,
            can_add_to_collection=True,
            can_share=True,
            can_mark_seen=True,
        )
        action_buttons: list[str] = []
        include_primary_action_button = True
        recorte_query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "column_name": selected_column or "",
            "recorte_id": recorte_item_id,
            "signature_path": "",
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "coluna",
        }
        if decision_type_token:
            recorte_query["decision_type"] = decision_type_token
        if tipo in {
            "excecao",
            "exception",
            "dominancia",
            "dominance",
            "conflito",
            "conflict",
            "ausencia",
            "absence",
            "missing",
        }:
            # Decisões com página própria abrem direto na camada de valores/células.
            recorte_query["signature_path"] = "valor/celula"
        default_recorte_href = f"/?{urlencode(recorte_query)}"
        recorte_href = default_recorte_href
        recorte_cta_label = "Abrir assinatura"
        if tipo in {"excecao", "conflito"}:
            metadata = recorte.get("metadata") if isinstance(recorte.get("metadata"), dict) else {}
            if tipo == "excecao":
                show_group_option = bool(metadata.get("show_group_option"))
                candidate_values = all_rare_values_full
                candidate_rows = rare_rows_full
                candidate_ratio = rare_group_ratio
                slice_group_type = "exception_group"
                can_offer_group_slice = (
                    show_group_option
                    and candidate_values
                    and candidate_ratio < 0.2
                    and unique_ratio < 0.98
                )
            else:
                conflict_values = metadata.get("conflict_values") if isinstance(metadata.get("conflict_values"), list) else []
                candidate_values = [str(item) for item in conflict_values if str(item).strip()]
                candidate_rows = sum(int(full_counter.get(token, 0)) for token in candidate_values)
                candidate_ratio = candidate_rows / total_rows_full
                slice_group_type = "conflict_group"
                can_offer_group_slice = bool(candidate_values)
            if can_offer_group_slice:
                group_filters = parsed_filters + (
                    FilterCondition(column=str(selected_column), operator="IN", value=tuple(candidate_values)),
                )
                group_filters_text = _serialize_context_filters(group_filters)
                group_query = {
                    "source_type": source_type,
                    "source_path": source_path,
                    "unit_name": selected_unit,
                    "column_name": selected_column or "",
                    "recorte_id": recorte_item_id,
                    "signature_path": "novo_recorte",
                    "columns": columns_text,
                    "rows": rows_text,
                    "prompt": prompt,
                    "focus": "1" if focus_mode else "0",
                    "lang": lang,
                    "action": "coluna",
                    "exception_group": slice_group_type,
                    "context_filters": group_filters_text,
                }
                group_href = f"/?{escape(urlencode(group_query))}"
                # Em exceção grande, prioriza atalho direto para recorte agregado.
                if tipo == "excecao" and len(candidate_values) > 10:
                    include_primary_action_button = False
                    recorte_cta_label = "Abrir recorte agregado"
                    base_from_slice_query = {
                        "source_type": source_type,
                        "source_path": source_path,
                        "unit_name": selected_unit,
                        "column_name": selected_column or "",
                        "recorte_id": recorte_item_id,
                        "signature_path": "create_base_from_slice",
                        "columns": columns_text,
                        "rows": rows_text,
                        "prompt": prompt,
                        "focus": "1" if focus_mode else "0",
                        "lang": lang,
                        "action": "tabela",
                        "slice_mode": "new_base",
                        "exception_group": slice_group_type,
                        "context_filters": group_filters_text,
                        "origin_table": str(selected_unit),
                        "origin_signature": "exception",
                        "origin_slice_type": "exception_group",
                        "origin_condition": f"{selected_column} IN rare_values",
                    }
                    action_buttons.append(
                        f"<a class='button secondary mini' href='/?{escape(urlencode(base_from_slice_query))}'>Criar nova base</a>"
                    )
                else:
                    action_buttons.append(
                        f"<a class='button secondary mini' href='{group_href}'>Novo recorte</a>"
                    )
        if include_primary_action_button:
            action_buttons.insert(
                0,
                f"<a class='button secondary mini' href='{escape(recorte_href)}'>{escape(recorte_cta_label)}</a>",
            )
        if tipo in {"excecao", "exception"}:
            # O clique no card de exceção deve sempre abrir a camada de valores/células.
            recorte_href = default_recorte_href
        actions_block = ""
        recorte_node_id = "::".join(
            (
                "recorte",
                source_type or "origem",
                source_path or "default",
                selected_unit or "",
                selected_column or "",
                recorte_item_id or tipo,
            )
        )
        recorte_label = f"{tipo_labels.get(tipo, tipo)} · {selected_column or 'coluna'}"
        recorte_cards.append(
            f"""
            <div class="decision-card-item">
              <a
                class="metric-link state-reference-card"
                href="{escape(recorte_href)}"
                draggable="true"
                data-state-href="{escape(recorte_href)}"
                data-state-node-id="{escape(recorte_node_id)}"
                data-state-layer="recorte"
                data-state-label="{escape(recorte_label)}"
                aria-label="{escape(recorte_label)}"
              >
                <article class="focus-stat-card decision-card-shell">
                  {card_header_html}
                  <div class="decision-card-context">Contexto: {escape(descricao)}</div>
                  <div class="decision-card-details">{escape(repeat_count_label)}</div>
                  <div class="decision-card-details">{escape(share_label)}</div>
                  {("<div class='decision-card-examples'>Exemplo(s): " + escape(", ".join(parsed_preview)) + "</div>") if parsed_preview else ""}
                  {caminhos_block}
                  {actions_block}
                </article>
              </a>
            </div>
            """
        )
    relation_decision_card_html = ""
    if relation_targets:
        top_targets = relation_targets[:5]
        relation_preview = ", ".join(
            f"{item['table']}.{item['column']} ({float(item['overlap']) * 100:.1f}%)"
            for item in top_targets
        )
        first_relation_href = ""
        for item in top_targets:
            relation_query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": item["table"],
                "column_name": item["column"],
                "relation_column": item["column"],
                "relation_values": json.dumps(item["values"], ensure_ascii=False),
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "tabela",
            }
            if not first_relation_href:
                first_relation_href = f"/?{escape(urlencode(relation_query))}"
        relation_href = first_relation_href or f"/?{escape(urlencode({'source_type': source_type, 'source_path': source_path, 'unit_name': selected_unit, 'column_name': selected_column or '', 'columns': columns_text, 'rows': rows_text, 'prompt': prompt, 'focus': '1' if focus_mode else '0', 'lang': lang, 'action': 'coluna'}))}"
        relation_decision_card_html = f"""
            <div class="decision-card-item">
              <a class="metric-link state-reference-card" href="{relation_href}">
                <article class="focus-stat-card decision-card-shell">
                  {_render_card_header(title="Relações", occurrences=len(top_targets), exploration_level=0.0, can_add_to_collection=True, can_share=True, can_mark_seen=True)}
                  <div class="decision-card-context">Contexto: Possíveis conexões com outras tabelas</div>
                  <div class="decision-card-details">Assinatura se repete: {len(top_targets)} relações</div>
                  <div class="decision-card-examples">Exemplo(s): {escape(relation_preview)}</div>
                </article>
              </a>
            </div>
            """
        recorte_cards.append(relation_decision_card_html)

    relation_filter_values: set[str] = set()
    if relation_values_text:
        try:
            parsed_values = json.loads(relation_values_text)
        except json.JSONDecodeError:
            parsed_values = []
        if isinstance(parsed_values, list):
            relation_filter_values = {str(item) for item in parsed_values if item not in (None, "")}
    effective_values = values
    if relation_column and relation_filter_values and relation_column == selected_column:
        effective_values = [value for value in values if str(value) in relation_filter_values]
    value_counter = Counter(cell_value_identity_token(value) for value in effective_values)
    total_rows = max(len(effective_values), 1)
    active_tipo = str((active_recorte or {}).get("tipo") or "").strip()
    active_metadata = (
        (active_recorte or {}).get("metadata")
        if isinstance((active_recorte or {}).get("metadata"), dict)
        else {}
    )
    active_type = str(active_metadata.get("type") or "").strip()
    active_name = str(active_metadata.get("name") or "").strip()
    decision_kind = _recorte_decision_kind(active_recorte)

    active_paths = []
    if isinstance((active_recorte or {}).get("paths"), list):
        active_paths = [str(item) for item in ((active_recorte or {}).get("paths") or []) if str(item).strip()]
    if not active_paths and isinstance((active_recorte or {}).get("transicoes_permitidas"), list):
        _dest_to_path = {
            "valor_celula": "valor/celula",
            "recorte": "novo_recorte",
            "subconjunto": "subconjunto",
            "caractere": "caractere",
        }
        active_paths = [
            _dest_to_path.get(str(item.get("destino") or ""), str(item.get("destino") or ""))
            for item in ((active_recorte or {}).get("transicoes_permitidas") or [])
            if isinstance(item, dict) and str(item.get("destino") or "").strip()
        ]
    active_paths = list(dict.fromkeys(active_paths))
    selected_signature_path = signature_path if signature_path in active_paths else ""
    show_signature_path_layer = bool(active_recorte) and len(active_paths) > 1 and not selected_signature_path and not exception_group
    exception_page_mode = decision_kind == "exception" and signature_path == "valor/celula"
    dominance_page_mode = decision_kind == "dominance" and signature_path == "valor/celula"
    conflict_page_mode = decision_kind == "conflict" and signature_path == "valor/celula"
    absence_page_mode = decision_kind == "missing" and signature_path == "valor/celula"
    decision_value_page_mode = exception_page_mode or dominance_page_mode or conflict_page_mode or absence_page_mode
    decision_open_mode = bool(active_recorte) and (
        bool(str(recorte_id or "").strip())
        or bool(str(decision_type or "").strip())
        or bool(str(signature_path or "").strip())
    )
    value_page_mode = (
        action == "valor"
        and bool(selected_value)
        and slice_mode == "deepen"
        and signature_path == "valor/celula"
        and bool(active_recorte)
    )

    value_limit = 6
    exception_individual_limit = 10
    hidden_values_count = 0
    exception_aggregate_mode = False
    exception_examples: list[tuple[str, int, str]] = []
    exception_total_values = 0
    exception_total_rows = 0
    exception_ratio = 0.0
    exception_group_filters_text = ""
    dominance_total_values = 0
    dominance_rendered_values = 0
    dominance_values_source = ""
    conflict_total_values = 0
    conflict_rendered_values = 0
    conflict_total_rows = 0
    conflict_values_source = ""
    absence_total_values = 0
    absence_rendered_values = 0
    absence_values_source = ""
    value_candidate_ratios: dict[str, float] = {}
    if show_signature_path_layer:
        value_candidates = []
    elif relation_only_mode:
        value_candidates = []
    elif decision_kind == "exception":
        if exception_page_mode and isinstance(active_recorte, dict):
            preview_items = active_recorte.get("preview") if isinstance(active_recorte.get("preview"), list) else []
            payload_candidates: list[tuple[str, int, str]] = []
            for item in preview_items:
                if not isinstance(item, dict) or "value" not in item:
                    continue
                token = str(item.get("value"))
                item_value_id = str(item.get("value_id") or stable_value_id(_raw_value_from_token(token)))
                payload_candidates.append((token, int(item.get("frequency") or 0), item_value_id))
            value_candidates = payload_candidates
            exception_total_rows = sum(int(count) for _, count, _ in payload_candidates)
            exception_ratio = (exception_total_rows / total_rows) if total_rows > 0 else 0.0
            metadata = active_recorte.get("metadata") if isinstance(active_recorte.get("metadata"), dict) else {}
            rare_total_raw = metadata.get("rare_total")
            exception_total_values = int(rare_total_raw) if isinstance(rare_total_raw, (int, float)) else len(payload_candidates)
            hidden_values_count = max(0, exception_total_values - len(payload_candidates))
            exception_examples = payload_candidates[:6]
            exception_aggregate_mode = False
        else:
            rare_values = [(token, count) for token, count in value_counter.items() if int(count) <= 1]
            if not rare_values:
                rare_values = sorted(value_counter.items(), key=lambda item: (item[1], str(item[0])))
            else:
                rare_values = sorted(rare_values, key=lambda item: str(item[0]))
            if len(rare_values) <= exception_individual_limit:
                value_candidates = [
                    (
                        str(token),
                        int(count),
                        stable_value_id(_raw_value_from_token(str(token))),
                    )
                    for token, count in rare_values
                ]
            else:
                step = max((len(rare_values) - 1) / max(exception_individual_limit - 1, 1), 1.0)
                sample_indexes = {min(int(round(index * step)), len(rare_values) - 1) for index in range(exception_individual_limit)}
                ordered_indexes = sorted(sample_indexes)[:exception_individual_limit]
                value_candidates = [
                    (
                        str(rare_values[index][0]),
                        int(rare_values[index][1]),
                        stable_value_id(_raw_value_from_token(str(rare_values[index][0]))),
                    )
                    for index in ordered_indexes
                ]
                hidden_values_count = max(0, len(rare_values) - len(value_candidates))
            exception_total_values = len(rare_values)
            exception_total_rows = sum(int(count) for _, count in rare_values)
            exception_ratio = (exception_total_rows / total_rows) if total_rows > 0 else 0.0
            exception_examples = [
                (
                    str(token),
                    int(count),
                    stable_value_id(_raw_value_from_token(str(token))),
                )
                for token, count in rare_values[:6]
            ]
            exception_aggregate_mode = exception_total_values > exception_individual_limit
            if exception_aggregate_mode:
                value_candidates = []
                hidden_values_count = 0
                exception_group_filters = parsed_filters + (
                    FilterCondition(column=str(selected_column), operator="IN", value=tuple(token for token, _ in rare_values)),
                )
                exception_group_filters_text = _serialize_context_filters(exception_group_filters)
    elif decision_kind == "conflict":
        if conflict_page_mode and isinstance(active_recorte, dict):
            values_items = active_recorte.get("values") if isinstance(active_recorte.get("values"), list) else []
            preview_items = active_recorte.get("preview") if isinstance(active_recorte.get("preview"), list) else []
            payload_candidates: list[tuple[str, int, str]] = []
            if values_items:
                for item in values_items:
                    if not isinstance(item, dict) or "value" not in item:
                        continue
                    token = str(item.get("value"))
                    item_value_id = str(item.get("value_id") or stable_value_id(_raw_value_from_token(token)))
                    count = int(item.get("count") or 0)
                    payload_candidates.append((token, count, item_value_id))
                    ratio_raw = item.get("ratio")
                    if isinstance(ratio_raw, (int, float)):
                        value_candidate_ratios[item_value_id] = max(0.0, min(float(ratio_raw), 1.0))
                conflict_values_source = "values"
            else:
                for item in preview_items:
                    if not isinstance(item, dict) or "value" not in item:
                        continue
                    token = str(item.get("value"))
                    item_value_id = str(item.get("value_id") or stable_value_id(_raw_value_from_token(token)))
                    payload_candidates.append((token, int(item.get("frequency") or 0), item_value_id))
                conflict_values_source = "preview"
            value_candidates = payload_candidates
            conflict_rendered_values = len(payload_candidates)
            conflict_total_rows = sum(int(count) for _, count, _ in payload_candidates)
            metadata = active_recorte.get("metadata") if isinstance(active_recorte.get("metadata"), dict) else {}
            conflict_total_raw = metadata.get("conflict_value_count")
            conflict_total_values = int(conflict_total_raw) if isinstance(conflict_total_raw, (int, float)) else conflict_rendered_values
            hidden_values_count = max(0, conflict_total_values - conflict_rendered_values)
        else:
            conflict_values = sorted(
                [(token, count) for token, count in value_counter.items() if int(count) > 1],
                key=lambda item: (-item[1], str(item[0])),
            )
            selected_conflicts = conflict_values[:value_limit] if conflict_values else value_counter.most_common(value_limit)
            value_candidates = [
                (
                    str(token),
                    int(count),
                    stable_value_id(_raw_value_from_token(str(token))),
                )
                for token, count in selected_conflicts
            ]
    elif decision_kind == "dominance":
        if dominance_page_mode and isinstance(active_recorte, dict):
            values_items = active_recorte.get("values") if isinstance(active_recorte.get("values"), list) else []
            preview_items = active_recorte.get("preview") if isinstance(active_recorte.get("preview"), list) else []
            payload_candidates: list[tuple[str, int, str]] = []
            if values_items:
                for item in values_items:
                    if not isinstance(item, dict) or "value" not in item:
                        continue
                    token = str(item.get("value"))
                    item_value_id = str(item.get("value_id") or stable_value_id(_raw_value_from_token(token)))
                    payload_candidates.append((token, int(item.get("count") or 0), item_value_id))
                dominance_values_source = "values"
            else:
                for item in preview_items:
                    if not isinstance(item, dict) or "value" not in item:
                        continue
                    token = str(item.get("value"))
                    item_value_id = str(item.get("value_id") or stable_value_id(_raw_value_from_token(token)))
                    payload_candidates.append((token, int(item.get("frequency") or 0), item_value_id))
                dominance_values_source = "preview"
            value_candidates = payload_candidates
            metadata = active_recorte.get("metadata") if isinstance(active_recorte.get("metadata"), dict) else {}
            dominant_total_raw = metadata.get("dominant_values_total")
            if not isinstance(dominant_total_raw, (int, float)):
                dominant_total_raw = metadata.get("mode_count")
            dominance_rendered_values = len(payload_candidates)
            if isinstance(dominant_total_raw, (int, float)):
                dominance_total_values = int(dominant_total_raw)
                hidden_values_count = max(0, dominance_total_values - dominance_rendered_values)
            else:
                dominance_total_values = dominance_rendered_values
        else:
            value_candidates = [
                (
                    str(token),
                    int(count),
                    stable_value_id(_raw_value_from_token(str(token))),
                )
                for token, count in value_counter.most_common(value_limit)
            ]
    elif decision_kind == "missing":
        if absence_page_mode and isinstance(active_recorte, dict):
            values_items = active_recorte.get("values") if isinstance(active_recorte.get("values"), list) else []
            payload_candidates: list[tuple[str, int, str]] = []
            for item in values_items:
                if not isinstance(item, dict) or "value" not in item:
                    continue
                token = str(item.get("value"))
                item_value_id = str(item.get("value_id") or stable_value_id(_raw_value_from_token(token)))
                count = int(item.get("count") or item.get("frequency") or 0)
                payload_candidates.append((token, count, item_value_id))
                ratio_raw = item.get("ratio")
                if isinstance(ratio_raw, (int, float)):
                    value_candidate_ratios[item_value_id] = max(0.0, min(float(ratio_raw), 1.0))
            value_candidates = payload_candidates
            absence_rendered_values = len(payload_candidates)
            absence_total_values = absence_rendered_values
            absence_values_source = "values" if values_items else ""
        else:
            value_candidates = [
                (
                    str(item),
                    int(count),
                    stable_value_id(_raw_value_from_token(str(item))),
                )
                for item, count in value_counter.items()
                if str(item) in {"__none__", "__empty__"}
            ][:value_limit]
            if not value_candidates:
                value_candidates = [
                    (
                        str(token),
                        int(count),
                        stable_value_id(_raw_value_from_token(str(token))),
                    )
                    for token, count in value_counter.most_common(value_limit)
                ]
    else:
        value_candidates = [
            (
                str(token),
                int(count),
                stable_value_id(_raw_value_from_token(str(token))),
            )
            for token, count in value_counter.most_common(value_limit)
        ]

    active_mode = slice_mode if slice_mode in {"deepen", "new_base"} else ""
    active_context: DataContext | None = None
    active_query_sql = ""
    active_query_params: tuple[object, ...] = ()
    if selected_value and active_mode:
        base_context = DataContext(
            source_table=normalize_table_name(str(current.get("tabela_nome") or selected_unit)),
            filters=parsed_filters,
            parent_context=None,
        )
        active_context = create_slice(
            base_context,
            FilterCondition(column=str(selected_column), operator="=", value=selected_value),
            active_mode,
        )
        active_query_sql, active_query_params = build_query(active_context)
    effective_filters = active_context.filters if active_context else parsed_filters
    effective_filters_text = _serialize_context_filters(effective_filters)

    value_cards = []
    decision_context_block = ""
    if decision_value_page_mode:
        active_description = str(
            (
                (active_recorte.get("evidencia") or {}).get("descricao")
                if isinstance(active_recorte.get("evidencia"), dict)
                else ""
            )
            or active_recorte.get("description")
            or ""
        ).strip()
        decision_label_map = {
            "exception": "Exceção",
            "dominance": "Dominância",
            "conflict": "Conflito",
            "missing": "Ausência",
        }
        decision_slug_map = {
            "exception": "exceção",
            "dominance": "dominância",
            "conflict": "conflito",
            "missing": "ausência",
        }
        decision_label = decision_label_map.get(decision_kind, "Decisão")
        decision_slug = decision_slug_map.get(decision_kind, "decisão")
        context_lines = [
            f"<div class='origin-line'>Caminho: origem / {escape(str(selected_unit or current.get('tabela_nome') or '—'))} / {escape(str(selected_column or '—'))} / {decision_slug}</div>",
            f"<div class='origin-line'>Tabela: {escape(str(selected_unit or current.get('tabela_nome') or '—'))}</div>",
            f"<div class='origin-line'>Coluna: {escape(str(selected_column or '—'))}</div>",
            f"<div class='origin-line'>Decisão: {decision_label}</div>",
        ]
        if active_description:
            context_lines.append(f"<div class='origin-line'>Resumo: {escape(active_description)}</div>")
        if decision_kind == "dominance":
            context_lines.append(f"<div class='origin-line'>Padrões dominantes: {dominance_total_values}</div>")
            context_lines.append(f"<div class='origin-line'>Valores exibidos: {dominance_rendered_values}</div>")
            if dominance_values_source == "preview":
                context_lines.append("<div class='origin-line'>Fonte dos valores: preview do payload</div>")
        if decision_kind == "conflict":
            context_lines.append(f"<div class='origin-line'>Valores em conflito: {conflict_total_values}</div>")
            context_lines.append(f"<div class='origin-line'>Valores exibidos: {conflict_rendered_values}</div>")
            if conflict_total_rows:
                context_lines.append(f"<div class='origin-line'>Impacto exibido: {conflict_total_rows} registros</div>")
        if decision_kind == "missing":
            if absence_total_values:
                context_lines.append(f"<div class='origin-line'>Casos de ausência: {absence_total_values}</div>")
            context_lines.append(f"<div class='origin-line'>Casos exibidos: {absence_rendered_values}</div>")
            if absence_values_source != "values":
                context_lines.append("<div class='origin-line'>Lista navegável: indisponível no payload</div>")
        context_lines.append("__DECISION_SAMPLE_LINE__")
        decision_context_block = (
            "<div class='results-title'>Contexto da decisão</div>"
            "<section class='origin-overview'>"
            + "".join(context_lines)
            + "</section>"
        )
    if relation_only_mode and relation_decision_card_html:
        value_cards.append(relation_decision_card_html)
    if (
        exception_aggregate_mode
        and exception_group != "exception_group"
        and not exception_page_mode
        and not ((has_intermediate_layer and active_recorte is None) or show_signature_path_layer)
    ):
        aggregate_base_query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "column_name": selected_column or "",
            "recorte_id": str((active_recorte or {}).get("id") or recorte_id or ""),
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "signature_path": "valor/celula",
            "exception_group": "exception_group",
            "context_filters": exception_group_filters_text,
            "origin_table": str(selected_unit),
            "origin_signature": "exception",
            "origin_slice_type": "exception_group",
            "origin_condition": f"{selected_column} IN rare_values",
        }
        aggregate_new_base_query = {
            **aggregate_base_query,
            "action": "tabela",
            "slice_mode": "new_base",
            "signature_path": "create_base_from_slice",
        }
        example_tokens = ", ".join(str(token) for token, _, _ in exception_examples)
        value_cards.append(
            f"""
            <a class="metric-link state-reference-card" href="{escape(f'/?{urlencode(aggregate_new_base_query)}')}">
              <article class="focus-stat-card is-recommended h-card">
                {_render_card_header(
                    title="Exceção",
                    occurrences=exception_total_values,
                    exploration_level=0.0,
                    can_add_to_collection=True,
                    can_share=True,
                    can_mark_seen=True,
                )}
                <div class="h-card-layout">
                  <div class="h-card-left">
                    <div class="small">Exceção</div>
                    <div class="focus-stat-value">Valores raros da coluna</div>
                  </div>
                  <div class="h-card-center">
                    <ul class="metric-list" style="margin-top: 6px;">
                      <li>Impacto agregado: {exception_total_rows} registros ({exception_ratio * 100:.2f}%)</li>
                      <li>Total de valores incluídos: {exception_total_values}</li>
                      <li>Exemplos: {escape(example_tokens or '—')}</li>
                    </ul>
                  </div>
                  <div class="h-card-right"></div>
                </div>
              </article>
            </a>
            """
        )
    for rank, (value_label, frequency, value_id) in enumerate(value_candidates, start=1):
        if (has_intermediate_layer and active_recorte is None) or show_signature_path_layer:
            break
        ratio = value_candidate_ratios.get(value_id, frequency / total_rows)
        is_recommended = rank == 1
        technical_payload["value_cards"].append(
            {
                "type": "value",
                "selectable": True,
                "value": value_label,
                "value_id": value_id,
                "frequency": int(frequency),
                "ratio": ratio,
                "is_recommended": is_recommended,
                "actions": ["deepen", "new_base"],
            }
        )
        deepen_query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "column_name": selected_column or "",
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "coluna",
            "selected_value": value_label,
            "selected_value_id": value_id,
            "slice_mode": "deepen",
            "signature_path": "valor/celula",
            "decision_type": decision_kind,
            "context_filters": effective_filters_text,
            "recorte_id": str((active_recorte or {}).get("id") or recorte_id or ""),
        }
        deepen_value_query = {**deepen_query, "action": "valor"}
        deepen_href = f"/?{urlencode(deepen_value_query)}"
        new_base_query = {
            **deepen_query,
            "slice_mode": "new_base",
            "action": "tabela",
        }
        if decision_kind in {"exception", "dominance", "conflict", "missing"}:
            value_cards.append(
                f"""
                <article class="focus-stat-card h-card{(' is-recommended' if is_recommended else '')}">
                  {_render_card_header(
                      title=str(value_label),
                      occurrences=int(frequency),
                      exploration_level=0.0,
                      can_add_to_collection=True,
                      can_share=True,
                      can_mark_seen=True,
                  )}
                  <div class="small" style="margin-top: 8px;">Impacto: {int(frequency)} registros ({ratio * 100:.2f}%)</div>
                  <div class="decision-card-actions card-actions">
                    <a class="button secondary mini" href="{escape(deepen_href)}">Aprofundar análise</a>
                    <a class="button secondary mini" href="{escape(f'/?{urlencode(new_base_query)}')}">Criar nova base</a>
                  </div>
                </article>
                """
            )
        else:
            value_cards.append(
                f"""
                <a class="metric-link state-reference-card" href="{escape(f'/?{urlencode(deepen_query)}')}">
                  <article class="focus-stat-card h-card{(' is-recommended' if is_recommended else '')}">
                    {_render_card_header(
                        title=str(value_label),
                        occurrences=int(frequency),
                        exploration_level=0.0,
                        can_add_to_collection=True,
                        can_share=True,
                        can_mark_seen=True,
                    )}
                    <div class="h-card-layout">
                      <div class="h-card-left">
                        <div class="small">Valor</div>
                        <div class="focus-stat-value">{escape(value_label)}</div>
                      </div>
                      <div class="h-card-center">
                        <div class="small" style="margin-top: 6px;">{int(frequency)} registros ({ratio * 100:.2f}%)</div>
                      </div>
                      <div class="h-card-right"></div>
                    </div>
                  </article>
                </a>
                """
            )
    if hidden_values_count > 0 and decision_kind == "exception":
        technical_payload["value_cards"].append(
            {
                "type": "sample_summary",
                "selectable": False,
                "actions": [],
                "hidden_rare_values": int(hidden_values_count),
                "summary": f"{hidden_values_count} valores raros não exibidos",
            }
        )
    if decision_value_page_mode and decision_context_block:
        sample_line = f"<div class='origin-line'>Amostra: {hidden_values_count} valores não exibidos</div>" if hidden_values_count > 0 else ""
        decision_context_block = decision_context_block.replace("__DECISION_SAMPLE_LINE__", sample_line)

    active_slice_block = ""
    value_details_block = ""
    associated_rows_block = ""
    active_slice_state: dict[str, Any] | None = None

    def _build_slice_actions_html(slice_state: dict[str, Any]) -> str:
        actions: list[str] = []
        source_table = str(slice_state.get("source_table") or selected_unit)
        source_column = str(slice_state.get("source_column") or (selected_column or ""))
        origin_signature = str(slice_state.get("origin_signature") or "")
        origin_slice_type = str(slice_state.get("origin_slice_type") or "")
        origin_condition = str(slice_state.get("origin_condition") or "")
        context_text = str(slice_state.get("context_filters") or "")
        if bool(slice_state.get("can_explore_columns")):
            explore_query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": source_table,
                "column_name": source_column,
                "recorte_id": str((active_recorte or {}).get("id") or recorte_id or ""),
                "signature_path": "explore_slice_columns",
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "coluna",
                "context_filters": context_text,
                "origin_table": source_table,
                "origin_signature": origin_signature,
                "origin_slice_type": origin_slice_type,
                "origin_condition": origin_condition,
            }
            if slice_state.get("slice_type") in {"exception_group", "conflict_group"}:
                explore_query["exception_group"] = str(slice_state.get("slice_type"))
            actions.append(
                f"<a class='button secondary mini' href='/?{escape(urlencode(explore_query))}'>Explorar colunas deste recorte</a>"
            )
        if bool(slice_state.get("can_create_base")):
            base_query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": source_table,
                "column_name": source_column,
                "recorte_id": str((active_recorte or {}).get("id") or recorte_id or ""),
                "signature_path": "create_base_from_slice",
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "tabela",
                "slice_mode": "new_base",
                "context_filters": context_text,
                "origin_table": source_table,
                "origin_signature": origin_signature,
                "origin_slice_type": origin_slice_type,
                "origin_condition": origin_condition,
            }
            if slice_state.get("slice_type") in {"exception_group", "conflict_group"}:
                base_query["exception_group"] = str(slice_state.get("slice_type"))
            actions.append(
                f"<a class='button secondary mini' href='/?{escape(urlencode(base_query))}'>Criar nova base</a>"
            )
        if not actions:
            return ""
        return "<div class='actions'>" + "".join(actions) + "</div>"
    value_context_block = ""
    if active_context is not None:
        impact_resolution = resolve_selected_value_impact(
            selected_value_id=str(selected_value_id or ""),
            selected_value=str(selected_value),
            active_recorte=active_recorte if isinstance(active_recorte, dict) else None,
            total_rows=total_rows,
            fallback_counter=value_counter,
        )
        selected_rows = int(impact_resolution.get("count") or 0)
        selected_ratio = float(impact_resolution.get("ratio") or 0.0)
        resolved_value_raw = (
            impact_resolution["resolved_value"]
            if "resolved_value" in impact_resolution
            else selected_value
        )
        resolved_selected_value = cell_value_identity_token(resolved_value_raw)
        resolved_selected_value_id = str(impact_resolution.get("resolved_value_id") or selected_value_id)
        technical_payload["active_slice"] = {
            "layer": "slice",
            "slice_type": "single_value" if active_mode == "deepen" else "new_base",
            "column": str(selected_column),
            "selected_value": resolved_selected_value,
            "selected_value_id": resolved_selected_value_id,
            "impact_source": str(impact_resolution.get("source") or ""),
            "rows": selected_rows,
            "ratio": selected_ratio,
        }
        if active_mode == "deepen":
            active_slice_state = {
                "slice_type": "single_value",
                "source_table": str(current.get("tabela_nome") or selected_unit),
                "source_column": str(selected_column),
                "condition": {"operator": "=", "value": resolved_selected_value},
                "impact": {"rows": selected_rows, "ratio": selected_ratio},
                "can_explore_columns": True,
                "can_create_base": True,
                "context_filters": effective_filters_text,
                "origin_table": str(current.get("tabela_nome") or selected_unit),
                "origin_signature": decision_kind or "",
                "origin_slice_type": "single_value",
                "origin_condition": f"{selected_column}={resolved_selected_value}",
            }
            technical_payload["active_slice"] = active_slice_state
            if value_page_mode:
                decision_label_map = {
                    "exception": "Exceção",
                    "conflict": "Conflito",
                    "dominance": "Dominância",
                    "missing": "Ausência",
                }
                decision_label = decision_label_map.get(decision_kind, "Decisão")
                value_analysis = build_value_cell_analysis_payload(
                    table=str(selected_unit or current.get("tabela_nome") or "—"),
                    column=str(selected_column or "—"),
                    decision=str(decision_label),
                    value=resolved_selected_value,
                    total_rows=total_rows,
                    frequency=selected_rows,
                    selected_value_id=resolved_selected_value_id,
                    standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
                    column_order=list((standardized or {}).get("column_order") or []),
                )
                technical_payload["value_analysis"] = value_analysis
                associated_rows_total = int(value_analysis.get("associated_rows_total") or 0)
                associated_rows_displayed = int(value_analysis.get("associated_rows_displayed") or 0)
                associated_rows_hidden = int(value_analysis.get("associated_rows_hidden") or 0)
                associated_rows_are_identical = value_analysis.get("associated_rows_are_identical")
                associated_rows = value_analysis.get("associated_rows") if isinstance(value_analysis.get("associated_rows"), list) else []
                representative_row = value_analysis.get("representative_row") if isinstance(value_analysis.get("representative_row"), dict) else None

                def _render_row_values(row_payload: dict[str, Any] | None) -> str:
                    values_payload = row_payload.get("values") if isinstance(row_payload, dict) else None
                    if not isinstance(values_payload, dict):
                        return ""
                    cells = []
                    for cell_column, cell_value in values_payload.items():
                        display_value = json.dumps(cell_value, ensure_ascii=False, default=str)
                        value_class = "associated-row-value associated-row-value-long" if len(display_value) > 80 else "associated-row-value"
                        cells.append(
                            "<div class='associated-row-cell'>"
                            f"<div class='small'>{escape(str(cell_column))}</div>"
                            f"<div class='{value_class}'>{escape(display_value)}</div>"
                            "</div>"
                        )
                    return "<div class='associated-row-grid'>" + "".join(cells) + "</div>"

                if associated_rows_total == 1:
                    associated_rows_block = (
                        "<div class='results-title'>Linhas associadas</div>"
                        + _render_info_card(
                            title="Linha associada",
                            body_html=_render_row_values(associated_rows[0] if associated_rows else representative_row),
                            class_name="associated-row-card",
                            can_add_to_collection=True,
                            can_share=True,
                            can_mark_seen=True,
                            can_star=True,
                        )
                    )
                elif associated_rows_total > 1 and associated_rows_are_identical is True:
                    associated_rows_block = (
                        "<div class='results-title'>Linhas associadas</div>"
                        + _render_info_card(
                            title="Linha representativa",
                            body_html=_render_row_values(representative_row),
                            class_name="associated-row-card",
                            can_add_to_collection=True,
                            can_share=True,
                            can_mark_seen=True,
                            can_star=True,
                        )
                    )
                elif associated_rows_total > 1 and associated_rows_are_identical is False:
                    rows_html = "".join(
                        _render_info_card(
                            title=f"Linha {int(row.get('row_index')) + 1}" if isinstance(row.get("row_index"), int) else "Linha associada",
                            body_html=_render_row_values(row),
                            class_name="associated-row-card",
                            can_add_to_collection=True,
                            can_share=True,
                            can_mark_seen=True,
                            can_star=True,
                        )
                        for row in associated_rows
                        if isinstance(row, dict)
                    )
                    associated_rows_block = (
                        "<div class='results-title'>Linhas associadas</div>"
                        + rows_html
                    )
                metrics = value_analysis.get("metrics") if isinstance(value_analysis, dict) else {}
                digit_count = int((metrics or {}).get("digit_count") or 0)
                alpha_count = int((metrics or {}).get("alpha_count") or 0)
                space_count = int((metrics or {}).get("space_count") or 0)
                punctuation_count = int((metrics or {}).get("punctuation_count") or 0)
                symbol_count = int((metrics or {}).get("symbol_count") or 0)
                composition_parts: list[str] = []
                if alpha_count > 0:
                    composition_parts.append(f"{alpha_count} letras")
                if digit_count > 0:
                    composition_parts.append(f"{digit_count} dígitos")
                if space_count > 0:
                    composition_parts.append(f"{space_count} espaços")
                if punctuation_count > 0:
                    composition_parts.append(f"{punctuation_count} pontuação")
                if symbol_count > 0:
                    composition_parts.append(f"{symbol_count} símbolos")
                composition = " · ".join(composition_parts) if composition_parts else "sem caracteres observáveis"
                traits: list[str] = []
                if bool((metrics or {}).get("has_digits")):
                    traits.append("dígitos")
                if bool((metrics or {}).get("has_alpha")):
                    traits.append("letras")
                if bool((metrics or {}).get("has_separator")):
                    traits.append("separador")
                if bool((metrics or {}).get("has_non_ascii")):
                    traits.append("não ASCII")
                if bool((metrics or {}).get("has_diacritic")):
                    traits.append("diacrítico")
                traits_line = " · ".join(traits)
                if associated_rows_total <= 0:
                    associated_rows_summary = "indisponíveis no payload"
                elif associated_rows_are_identical is True:
                    associated_rows_summary = f"{associated_rows_total} linhas associadas idênticas"
                elif associated_rows_are_identical is False:
                    associated_rows_summary = f"{associated_rows_total} linhas associadas diferentes"
                else:
                    associated_rows_summary = f"{associated_rows_total} linhas associadas"
                associated_rows_display_line = (
                    f"<div class='origin-line'>Linhas exibidas: {associated_rows_displayed}"
                    + (f" · {associated_rows_hidden} não exibidas" if associated_rows_hidden > 0 else "")
                    + "</div>"
                    if associated_rows_total > 0
                    else ""
                )
                value_context_block = f"""
                  <div class="results-title">Contexto do valor/célula</div>
                  <section class="origin-overview">
                    <div class='origin-line'>Caminho: origem / {escape(str(selected_unit or current.get('tabela_nome') or '—'))} / {escape(str(selected_column or '—'))} / {escape(decision_label.lower())} / {escape(resolved_selected_value)}</div>
                    <div class='origin-line'>Tabela: {escape(str(selected_unit or current.get('tabela_nome') or '—'))}</div>
                    <div class='origin-line'>Coluna: {escape(str(selected_column or '—'))}</div>
                    <div class='origin-line'>Decisão: {escape(decision_label)}</div>
                    <div class='origin-line'>Valor selecionado: {escape(resolved_selected_value)}</div>
                    <div class='origin-line'>Impacto: {selected_rows} registros ({selected_ratio * 100:.2f}%)</div>
                    <div class='origin-line'>Linhas associadas: {escape(associated_rows_summary)}</div>
                    {associated_rows_display_line}
                    <div class='origin-line' style='margin-top: 10px;'><strong>Detalhes estruturais</strong></div>
                    <div class='origin-line'>Comprimento: {int((metrics or {}).get("char_count") or 0)}</div>
                    <div class='origin-line'>Composição: {escape(composition)}</div>
                    {f"<div class='origin-line'>Traços: {escape(traits_line)}</div>" if traits_line else ""}
                    <div class='origin-line'>Frequência: {int((metrics or {}).get("frequency") or 0)} registros ({float((metrics or {}).get("frequency_ratio") or 0.0) * 100:.2f}%)</div>
                  </section>
                """
        else:
            active_slice_block = f"""
              <section class="origin-overview">
                <div class="results-title">Execução do recorte lógico</div>
                <div class="small">Modo escolhido: <strong>{escape(active_mode)}</strong></div>
                <div class="small">Filtro ativo: {escape(str(selected_column))} = {escape(selected_value)}</div>
                <div class="small">Parent: {escape('preservado' if active_context.parent_context else 'null')}</div>
                <pre class="focus-mini-pre">{escape(active_query_sql)}\nparams={escape(json.dumps(active_query_params, ensure_ascii=False, default=str))}</pre>
              </section>
            """
    if exception_group == "exception_group" and decision_kind == "exception" and rare_group_ratio < 0.2 and unique_ratio < 0.98:
        examples = ", ".join(all_rare_values_full[:5]) if all_rare_values_full else "—"
        exception_group_filters = parsed_filters + (
            FilterCondition(column=str(selected_column), operator="IN", value=tuple(all_rare_values_full)),
        )
        active_slice_state = {
            "slice_type": "exception_group",
            "source_table": str(current.get("tabela_nome") or selected_unit),
            "source_column": str(selected_column),
            "condition": {"operator": "in_rare_values", "value": tuple(all_rare_values_full)},
            "impact": {"rows": rare_rows_full, "ratio": rare_group_ratio},
            "can_explore_columns": len(all_rare_values_full) <= 10,
            "can_create_base": True,
            "context_filters": _serialize_context_filters(exception_group_filters),
            "origin_table": str(current.get("tabela_nome") or selected_unit),
            "origin_signature": "exception",
            "origin_slice_type": "exception_group",
            "origin_condition": f"{selected_column} IN rare_values",
        }
        technical_payload["active_slice"] = active_slice_state
        active_slice_block += f"""
          <section class="origin-overview">
            <div class="results-title">Recorte de exceções</div>
            <div class="small">Valores raros da coluna {escape(str(selected_column))} em {escape(str(current.get("tabela_nome") or selected_unit or "—"))}.</div>
            <ul class="metric-list">
              <li>Coluna de origem: {escape(str(selected_column))}</li>
              <li>Impacto agregado: {rare_rows_full} registros ({rare_group_ratio * 100:.2f}%)</li>
              <li>Total de valores incluídos: {len(all_rare_values_full)}</li>
              <li>Exemplos: {escape(examples)}</li>
            </ul>
            {_build_slice_actions_html(active_slice_state)}
          </section>
        """
    if exception_group == "conflict_group" and decision_kind == "conflict":
        conflict_values = active_metadata.get("conflict_values") if isinstance(active_metadata.get("conflict_values"), list) else []
        conflict_values = [str(item) for item in conflict_values if str(item).strip()]
        conflict_rows = sum(int(full_counter.get(token, 0)) for token in conflict_values)
        conflict_ratio = conflict_rows / total_rows_full
        examples = ", ".join(conflict_values[:5]) if conflict_values else "—"
        conflict_group_filters = parsed_filters + (
            FilterCondition(column=str(selected_column), operator="IN", value=tuple(conflict_values)),
        )
        active_slice_state = {
            "slice_type": "conflict_group",
            "source_table": str(current.get("tabela_nome") or selected_unit),
            "source_column": str(selected_column),
            "condition": {"operator": "in_conflict_values", "value": tuple(conflict_values)},
            "impact": {"rows": conflict_rows, "ratio": conflict_ratio},
            "can_explore_columns": True,
            "can_create_base": True,
            "context_filters": _serialize_context_filters(conflict_group_filters),
            "origin_table": str(current.get("tabela_nome") or selected_unit),
            "origin_signature": "conflict",
            "origin_slice_type": "conflict_group",
            "origin_condition": f"{selected_column} IN conflict_values",
        }
        technical_payload["active_slice"] = active_slice_state
        active_slice_block += f"""
          <section class="origin-overview">
            <div class="results-title">Recorte de conflitos</div>
            <div class="small">Quebras localizadas da coluna {escape(str(selected_column))} em {escape(str(current.get("tabela_nome") or selected_unit or "—"))}.</div>
            <ul class="metric-list">
              <li>Coluna de origem: {escape(str(selected_column))}</li>
              <li>Impacto agregado: {conflict_rows} registros ({conflict_ratio * 100:.2f}%)</li>
              <li>Total de valores incluídos: {len(conflict_values)}</li>
              <li>Exemplos: {escape(examples)}</li>
            </ul>
            {_build_slice_actions_html(active_slice_state)}
          </section>
        """

    signature_paths_block = ""
    if show_signature_path_layer and active_recorte is not None:
        path_buttons: list[str] = []
        base_query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "column_name": selected_column or "",
            "recorte_id": str((active_recorte or {}).get("id") or recorte_id or ""),
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "context_filters": effective_filters_text,
        }
        if "valor/celula" in active_paths:
            value_query = {
                **base_query,
                "action": "coluna",
                "signature_path": "valor/celula",
                "exception_group": "",
            }
            path_buttons.append(
                f"<a class='button secondary mini' href='/?{escape(urlencode(value_query))}'>Valor/célula</a>"
            )
        if "novo_recorte" in active_paths and decision_kind in {"exception", "conflict"}:
            if decision_kind == "exception":
                candidate_values = all_rare_values_full
                slice_group_type = "exception_group"
            else:
                conflict_values = active_metadata.get("conflict_values") if isinstance(active_metadata.get("conflict_values"), list) else []
                candidate_values = [str(item) for item in conflict_values if str(item).strip()]
                slice_group_type = "conflict_group"
            if candidate_values:
                group_filters = parsed_filters + (
                    FilterCondition(column=str(selected_column), operator="IN", value=tuple(candidate_values)),
                )
                group_query = {
                    **base_query,
                    "action": "coluna",
                    "signature_path": "novo_recorte",
                    "exception_group": slice_group_type,
                    "context_filters": _serialize_context_filters(group_filters),
                }
                path_buttons.append(
                    f"<a class='button secondary mini' href='/?{escape(urlencode(group_query))}'>Novo recorte</a>"
                )
        if path_buttons:
            signature_paths_block = (
                "<article class='focus-stat-card h-card'>"
                "<div class='h-card-layout'>"
                "<div class='h-card-left'><div class='focus-stat-value'>Caminhos</div></div>"
                "<div class='h-card-center'></div>"
                + "<div class='h-card-right'><div class='actions'>"
                + "".join(path_buttons)
                + "</div></div></div></article>"
            )
    if decision_open_mode:
        signature_paths_block = ""
    if decision_open_mode:
        # Página de exceção é exclusiva: não reaproveita quadro antigo de decisões/caminhos.
        signature_paths_block = ""

    decisions_board_html = (
        "<div class='decision-card-list'>"
        + "".join(recorte_cards)
        + "</div>"
    ) if has_intermediate_layer else ""
    if decision_open_mode:
        decisions_board_html = ""

    values_board_html = ""
    if value_cards and not value_page_mode:
        values_board_html = (
            "<div class='results-title'>VALOR/CÉLULA</div>"
            + "<div class='focus-stats focus-cards-horizontal'>"
            + "".join(value_cards)
            + "</div>"
        )

    decision_zone_blocks: list[str] = []
    if decisions_board_html or signature_paths_block or values_board_html or decision_context_block or value_context_block or associated_rows_block or value_details_block:
        if not decision_open_mode:
            decision_zone_blocks.append("<div class='results-title'>DECISÃO</div>")
    if decision_context_block and not value_page_mode:
        decision_zone_blocks.append(decision_context_block)
    if value_context_block:
        decision_zone_blocks.append(value_context_block)
    if associated_rows_block:
        decision_zone_blocks.append(associated_rows_block)
    if value_details_block:
        decision_zone_blocks.append(value_details_block)
    if decisions_board_html:
        decision_zone_blocks.append(decisions_board_html)
    if signature_paths_block:
        decision_zone_blocks.append(signature_paths_block)
    if values_board_html:
        decision_zone_blocks.append(values_board_html)
    if active_slice_block and not value_page_mode:
        decision_zone_blocks.append(active_slice_block)

    return f"""
      <section class="decision-zone">
      {''.join(decision_zone_blocks)}
      </section>
    """


def _column_capability_profile(
    *,
    column: dict[str, Any],
    values: list[Any],
    lang: str,
) -> dict[str, Any]:
    layer1 = column.get("layer1_metrics") or {}
    layer2 = column.get("layer2_metrics") or {}
    heuristics = column.get("heuristics") or []
    triggered = [str(item.get("name") or "heurística") for item in heuristics if item.get("triggered")]
    normalized_values = ["∅" if value in (None, "") else str(value) for value in values]
    counts = Counter(normalized_values)
    top_values = counts.most_common(5)

    cardinality = int(layer1.get("cardinality") or 0)
    null_ratio = float(layer1.get("null_ratio") or 0.0)
    unique_ratio = float(layer1.get("unique_ratio") or 0.0)
    numeric_ratio = float(layer2.get("numeric_ratio") or 0.0)
    alpha_ratio = float(layer2.get("alpha_ratio") or 0.0)
    spaces_ratio = float(layer2.get("spaces_ratio") or 0.0)
    row_count = max(len(normalized_values), 1)

    identifier_score = min(100.0, unique_ratio * 100.0 + (1.0 - null_ratio) * 18.0)
    relation_score = min(100.0, unique_ratio * 72.0 + min(cardinality / row_count, 1.0) * 28.0)
    quantity_score = min(100.0, numeric_ratio * 100.0)
    category_score = min(100.0, (1.0 - unique_ratio) * 82.0 + (1.0 - null_ratio) * 12.0)
    text_score = min(100.0, max(alpha_ratio, (alpha_ratio * 0.7) + (spaces_ratio * 0.3)) * 100.0)
    absence_score = min(100.0, null_ratio * 100.0)
    sequence_score = 0.0
    if any(token in " ".join(triggered).lower() for token in ("sequ", "order", "progress", "pattern")):
        sequence_score = 78.0
    elif numeric_ratio >= 0.6 and unique_ratio >= 0.5:
        sequence_score = 58.0

    scores = {
        "Identidade": identifier_score,
        "Relação": relation_score,
        "Quantidade": quantity_score,
        "Categoria": category_score,
        "Texto": text_score,
        "Ausência": absence_score,
        "Sequência": sequence_score,
    }
    ranked_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked_scores[0]
    second_score = ranked_scores[1][1] if len(ranked_scores) > 1 else 0.0
    mixed = (top_score < 40.0) or (top_score - second_score <= 10.0) or sum(1 for _, score in ranked_scores if score >= 55.0) > 1
    dominant_profile = "Mista" if mixed else top_name

    signal_lines = [
        f"Cardinalidade: {cardinality}",
        f"Nulos: {null_ratio:.2f}",
        f"Únicos: {unique_ratio:.2f}",
        f"Numérico: {numeric_ratio:.2f}",
        f"Alfabético: {alpha_ratio:.2f}",
        f"Espaços: {spaces_ratio:.2f}",
    ]
    evidence_lines = triggered[:4] or [
        "Nenhuma heurística forte acionada.",
        *[f"Valor: {value}" for value, _ in top_values[:3]],
    ]

    if dominant_profile == "Identidade":
        path_lines = [
            "Investigar vínculos em outras unidades",
            "Comparar com chaves candidatas",
            "Abrir correspondências prováveis",
        ]
        specialized = [
            ("Cobertura", f"{row_count} valores observados"),
            ("Estabilidade", "Verifique repetição e vazio"),
            ("Vínculos", "Procure tabelas relacionadas"),
        ]
    elif dominant_profile == "Relação":
        path_lines = [
            "Cruzar com outras tabelas",
            "Buscar colunas candidatas",
            "Validar força do vínculo",
        ]
        specialized = [
            ("Correspondências", "Parece ligar registros"),
            ("Cobertura", f"{cardinality} valores distintos"),
            ("Ligação", "Teste chaves externas e pares"),
        ]
    elif dominant_profile == "Quantidade":
        path_lines = [
            "Abrir distribuição",
            "Procurar extremos e outliers",
            "Agrupar por faixas",
        ]
        specialized = [
            ("Distribuição", "Observe concentração e dispersão"),
            ("Extremos", "Procure valores raros"),
            ("Agregação", "Teste cortes por faixa"),
        ]
    elif dominant_profile == "Categoria":
        path_lines = [
            "Agrupar categorias",
            "Ver raridades",
            "Comparar concentração",
        ]
        specialized = [
            ("Concentração", "Pares e grupos dominantes"),
            ("Cauda", "Categorias raras e exceções"),
            ("Comparação", "Veja distribuição relativa"),
        ]
    elif dominant_profile == "Texto":
        path_lines = [
            "Descer para fragmentos",
            "Procurar padrões textuais",
            "Ir para caractere",
        ]
        specialized = [
            ("Fragmentos", "Quebre o texto em partes úteis"),
            ("Padrões", "Procure assinaturas recorrentes"),
            ("Ruído", "Separe conteúdo de ruído"),
        ]
    elif dominant_profile == "Ausência":
        path_lines = [
            "Explorar preenchimento",
            "Comparar vazio vs valor",
            "Encontrar contraste informativo",
        ]
        specialized = [
            ("Preenchimento", "A ausência é a assinatura principal"),
            ("Contraste", "Veja onde o valor aparece"),
            ("Distribuição", "Observe o mapa de vazios"),
        ]
    elif dominant_profile == "Sequência":
        path_lines = [
            "Ver progressão",
            "Procurar saltos",
            "Checar continuidade",
        ]
        specialized = [
            ("Progressão", "Há ordem a explorar"),
            ("Saltos", "Procure quebras de padrão"),
            ("Continuidade", "Valide a sequência"),
        ]
    else:
        path_lines = [
            "Decompor subperfis",
            "Testar assinaturas dominantes",
            "Descer conforme a evidência",
        ]
        specialized = [
            ("Subperfil dominante", "Concentra o padrão com maior evidência estrutural."),
            ("Subperfil secundário", "Mantém assinaturas fora do padrão dominante."),
            ("Decomposição", "Divide a mistura em grupos comparáveis."),
        ]

    capability_items = [
        ("Identidade", identifier_score),
        ("Relação", relation_score),
        ("Quantidade", quantity_score),
        ("Categoria", category_score),
        ("Texto", text_score),
        ("Ausência", absence_score),
        ("Sequência", sequence_score),
    ]

    return {
        "signals": signal_lines,
        "evidence": evidence_lines,
        "dominant_profile": dominant_profile,
        "profile_score": top_score,
        "capabilities": capability_items,
        "paths": path_lines,
        "specialized": specialized,
        "top_values": top_values,
        "triggered": triggered,
        "cardinality": cardinality,
        "null_ratio": null_ratio,
        "unique_ratio": unique_ratio,
        "numeric_ratio": numeric_ratio,
        "alpha_ratio": alpha_ratio,
        "spaces_ratio": spaces_ratio,
        "sample_values": normalized_values[:6],
    }


def _column_dominant_recorte(profile: dict[str, Any]) -> tuple[str, str]:
    dominant_profile = str(profile.get("dominant_profile") or "Mista")
    top_values = list(profile.get("top_values") or [])
    top_value = top_values[0][0] if top_values else "—"
    top_count = int(top_values[0][1] or 0) if top_values else 0
    has_exception = bool(top_values and top_values[-1][1] == 1)

    if dominant_profile == "Identidade":
        return "instância destacada", f"{top_value} · {top_count} ocorrências"
    if dominant_profile == "Relação":
        return "vínculo pontual", f"{top_value} · {top_count} ocorrências"
    if dominant_profile == "Quantidade":
        return "faixa / agrupamento", f"{top_value} · {top_count} ocorrências"
    if dominant_profile == "Categoria":
        return "agrupamento", f"{top_value} · {top_count} ocorrências"
    if dominant_profile == "Texto":
        return "fragmento recorrente", f"{top_value} · {top_count} ocorrências"
    if dominant_profile == "Ausência":
        if has_exception:
            return "exceção por vazio", f"{top_values[-1][0]} · {int(top_values[-1][1] or 0)} ocorrência"
        return "zona de ausência", f"{top_value} · {top_count} ocorrências"
    if dominant_profile == "Sequência":
        return "padrão sequencial", f"{top_value} · {top_count} ocorrências"
    if has_exception:
        return "exceção detectada", f"{top_values[-1][0]} · {int(top_values[-1][1] or 0)} ocorrência"
    return "recorte concorrente", f"{top_value} · {top_count} ocorrências"


def _render_branch_graph(
    *,
    result: dict[str, Any] | None,
    selected_unit: str,
    selected_column: str | None,
    detail_mode: bool,
    column_mode: bool,
    lang: str,
) -> str:
    ui = _ui(lang)
    if not result:
        return ""

    if column_mode:
        units = result.get("tabelas") or []
        current = None
        for unit in units:
            if str(unit.get("tabela_nome") or "") == selected_unit:
                current = unit
                break
        if current is None:
            current = units[0] if units else {}
        columns = current.get("columns") or {}
        column = columns.get(selected_column or "")
        if not column:
            return ""
        standardized = current.get("standardized") or {}
        values = list((standardized.get("columns") or {}).get(selected_column or "") or [])
        profile = _column_capability_profile(column=column, values=values, lang=lang)

        lines = [
            f"{ui['layer_column']}: {selected_column or '—'}",
            "├─ Assinaturas",
        ]
        for index, line in enumerate(profile["signals"][:6], start=1):
            connector = "└─" if index == min(len(profile["signals"][:6]), 6) else "├─"
            lines.append(f"│  {connector} {line}")
        lines.append("├─ Capacidades")
        for index, (name, score) in enumerate(profile["capabilities"], start=1):
            connector = "└─" if index == len(profile["capabilities"]) else "├─"
            lines.append(f"│  {connector} {name}: {score:.0f}")
        lines.append(f"├─ Perfil dominante: {profile['dominant_profile']}")
        lines.append("├─ Cards")
        for index, (label, text) in enumerate(profile["specialized"], start=1):
            connector = "└─" if index == len(profile["specialized"]) else "├─"
            lines.append(f"│  {connector} {label} · {text}")
        recortes = _collect_column_decisions(column if isinstance(column, dict) else None)
        lines.append("├─ Decisões de aprofundamento (nível 1)")
        if recortes:
            for index, recorte in enumerate(recortes[:5], start=1):
                connector = "└─" if index == len(recortes[:5]) else "├─"
                tipo = str(recorte.get("tipo") or "recorte")
                prioridade = str(recorte.get("prioridade") or "media")
                estado = str(recorte.get("estado_estrutural") or "ativo")
                lines.append(f"│  {connector} {tipo} · prioridade {prioridade} · estado {estado}")
                transicoes = recorte.get("transicoes_permitidas") if isinstance(recorte.get("transicoes_permitidas"), list) else []
                for transition_index, transition in enumerate(transicoes, start=1):
                    transition_connector = "└─" if transition_index == len(transicoes) else "├─"
                    destino = str(transition.get("destino") or "destino")
                    motivo = str(transition.get("motivo") or "sem motivo")
                    lines.append(f"│  │  {transition_connector} {destino} · {motivo}")
        else:
            lines.append("│  └─ Nenhuma decisão de aprofundamento disponível")
        lines.append("└─ Caminhos por foco")
        for index, line in enumerate(profile["paths"], start=1):
            connector = "└─" if index == len(profile["paths"]) else "├─"
            lines.append(f"   {connector} {line}")
        graph_text = "\n".join(lines)
        return f"""
          <section class="orientation-tree">
            <pre class="graph-pre">{escape(graph_text)}</pre>
          </section>
        """

    if detail_mode:
        units = result.get("tabelas") or []
        current = None
        for unit in units:
            if str(unit.get("tabela_nome") or "") == selected_unit:
                current = unit
                break
        if current is None:
            current = units[0] if units else {}
        columns = current.get("columns") or {}
        if not columns:
            return ""
        lines = [
            f"{ui['layer_table']}: {current.get('unit_name') or selected_unit or '—'}",
            "├─ Dados gerais",
        ]
        standardized = current.get("standardized") or {}
        lines.append(f"│  ├─ Linhas: {standardized.get('row_count', '—')}")
        lines.append(f"│  └─ Colunas: {standardized.get('column_count', '—')}")
        lines.append("├─ Próxima camada")
        for index, (column_name, column) in enumerate(columns.items(), start=1):
            layer1 = column.get("layer1_metrics") or {}
            heuristics = column.get("heuristics") or []
            triggered = [str(item.get("name") or "heurística") for item in heuristics if item.get("triggered")]
            connector = "└─" if index == len(columns) else "├─"
            lines.append(
                f"│  {connector} {column_name} · {int(layer1.get('cardinality') or 0)} valores · {len(triggered)} assinaturas"
            )
        graph_text = "\n".join(lines)
        return f"""
          <section class="orientation-tree">
            <pre class="graph-pre">{escape(graph_text)}</pre>
          </section>
        """

    unit_previews = result.get("tabela_previas") or []
    if not unit_previews:
        return ""
    ranked_units = sorted(
        unit_previews,
        key=lambda preview: float(preview.get("importance_score") or 0.0),
        reverse=True,
    )[:9]
    lines = [f"{ui['source']}: {result.get('source', {}).get('display_name') or '—'}"]
    for index, unit in enumerate(ranked_units, start=1):
        connector = "└─" if index == len(ranked_units) else "├─"
        name = str(unit.get("tabela_nome") or "—")
        priority = unit.get("priority_label") or "prioridade"
        preview = str(unit.get("description") or _source_preview_text(unit))[:120]
        lines.append(f"{connector} {name} · {priority}")
        lines.append(f"   └─ {preview}")
    if len(unit_previews) > len(ranked_units):
        lines.append(f"+ {len(unit_previews) - len(ranked_units)} {ui['units']} adicionais")
    graph_text = "\n".join(lines)
    return f"""
      <section class="orientation-tree">
        <pre class="graph-pre">{escape(graph_text)}</pre>
      </section>
    """


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
          <a class="button" href="{escape(_href("quick"))}">{escape(_ui(lang)["quick_explore"])}</a>
          <a class="button secondary" href="{escape(_href("tabela"))}">{escape(_ui(lang)["analyze_selected_unit"])}</a>
          <a class="button secondary" href="{escape(_href("reset"))}">{escape(_ui(lang)["clear_saved_state"])}</a>
          <a class="button secondary" href="{escape(toggle_href)}">{escape(_ui(lang)["enable_focus_mode"] if not focus_mode else _ui(lang)["disable_focus_mode"])}</a>
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

    ranked_units = sorted(units, key=_unit_importance_score, reverse=True)
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
                      <div class="metric-preview">{escape(_ui(lang)["metrics_pending"])}</div>
                    </div>
                  </section>
                </a>
                """
            )
        if not preview:
            preview.append(
                f"""
                <section class="metric-card">
                  <div class="metric-body">
                    <div class="metric-name">—</div>
                    <div class="metric-preview">{escape(_ui(lang)["metrics_pending"])}</div>
                  </div>
                </section>
                """
            )
        if len(unit_names) > 6:
            preview.append(
                f'<div class="small">+ {len(unit_names) - 6} {escape(_ui(lang)["units"])} adicionais.</div>'
            )
        return "".join(preview)

    blocks: list[str] = []
    for index, unit in enumerate(ranked_units[:9], start=1):
        unit_name = str(unit.get("tabela_nome") or "")
        standardized = unit.get("standardized") or {}
        row_count = standardized.get("row_count")
        column_count = standardized.get("column_count")
        summary_preview = _source_preview_text(unit)
        column_order = list(standardized.get("column_order") or [])
        columns_preview = ", ".join(str(item) for item in column_order[:3]) if column_order else ""
        synthesis = summary_preview if summary_preview and summary_preview != "Prévia não disponível." else "Estrutura disponível para exploração."
        if "colunas mais relevantes" in synthesis.lower():
            synthesis = "Estrutura disponível para exploração."
        if len(synthesis) > 120:
            synthesis = synthesis[:117].rstrip() + "..."
        metrics = unit.get("metrics_summary") or []
        signal_preview = str(metrics[0]).strip() if metrics else ""
        if len(signal_preview) > 120:
            signal_preview = signal_preview[:117].rstrip() + "..."
        meta_parts: list[str] = []
        if row_count is not None:
            meta_parts.append(f"{row_count} linhas")
        if column_count is not None:
            meta_parts.append(f"{column_count} colunas")
        meta_html = (
            f'<div class="metric-meta">{escape(" · ".join(meta_parts))}</div>'
            if meta_parts
            else ""
        )
        detail_items = [item for item in (synthesis, signal_preview, columns_preview) if item]
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
        blocks.append(f'<div class="small">+ {len(ranked_units) - 9} {escape(_ui(lang)["units"])} adicionais.</div>')
    return "".join(blocks)


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
        'action': 'details',
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
    focused_column_values_html = _render_focused_column_values(
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
              onchange="if(this.files && this.files[0]){{document.getElementById('source_path').value=this.files[0].name;document.getElementById('source-quick-form').submit();}}"
            />
            <button type="button" onclick="document.getElementById('source_file_picker').click()" class="button secondary mini" style="white-space:nowrap;">Procurar</button>
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
    initial_upload_only_html = f"""
      {source_picker_controls_html}
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
        right_panel_blocks.append(initial_upload_only_html)
    else:
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
        if column_mode and focused_column_html and not decision_recorte_mode:
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
            'action': 'details',
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
                'action': 'column',
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
        return _build_health_result(), "Checando saúde...", [], "", None

    if action == "ai":
        try:
            data = _build_ai_result(prompt)
            return data, "Consultando IA...", [], "", None
        except GroqAPIError as exc:
            return {"error": str(exc)}, str(exc), [], "", None

    if action == "tabular":
        try:
            data = _build_tabular_result(unit_name or DEFAULT_UNIT_NAME, columns_text, rows_text)
            return data, "Analisando payload tabular...", [], unit_name or DEFAULT_UNIT_NAME, data.get("persisted_to")
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}, f"ERRO: {exc}", [], unit_name or DEFAULT_UNIT_NAME, None

    try:
        summary = _build_source_result(source_type, source_path, analyze_units=False)
        unit_names = list(summary.get("tabela_nomes") or [])
        selected = unit_name if unit_name in unit_names else (unit_names[0] if unit_names else "")

        if action in {"quick", "tabela", "previous", "next", "coluna", "valor"} and unit_names:
            selected = _select_unit_name(unit_names, selected, action)
            detail = _build_source_result(
                source_type,
                source_path,
                analyze_units=True,
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
        action: str = Query("summary"),
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
        if source_file and source_file.filename:
            safe_name = Path(source_file.filename).name
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            destination = UPLOAD_DIR / f"{uuid4().hex}_{safe_name}"
            content = await source_file.read()
            destination.write_bytes(content)
            resolved_source_path = str(destination)
            resolved_source_type = _infer_source_type_from_filename(source_type, safe_name)

        query = urlencode(
            {
                "source_type": resolved_source_type,
                "source_path": resolved_source_path,
                "action": action or "summary",
                "unit_name": unit_name,
                "column_name": column_name,
                "recorte_id": recorte_id,
                "relation_column": relation_column,
                "relation_values": relation_values,
                "exception_group": exception_group,
                "selected_value": selected_value,
                "selected_value_id": selected_value_id,
                "slice_mode": slice_mode,
                "signature_path": signature_path,
                "decision_type": decision_type,
                "origin_table": origin_table,
                "origin_signature": origin_signature,
                "origin_slice_type": origin_slice_type,
                "origin_condition": origin_condition,
                "context_filters": context_filters,
                "columns": columns,
                "rows": rows,
                "prompt": prompt,
                "focus": focus,
                "lang": lang,
            }
        )
        return RedirectResponse(url=f"/?{query}", status_code=303)

    return app
