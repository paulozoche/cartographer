"""Freio/Acelerador — decide o que e como entregar ao usuário."""

from __future__ import annotations

import json
import math
from typing import Any

import httpx
import wmill

LLM_LIMIT = 20_000
RESERVED_OUTPUT_TOKENS = 2_500

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, math.ceil(len(stripped) / CHARS_PER_TOKEN))


def estimate_context_consumed(
    history: list | None,
    last_result: dict | None = None,
) -> int:
    total = 0
    if isinstance(history, list):
        for entry in history:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content")
            if content is not None:
                total += estimate_tokens(str(content))
    if isinstance(last_result, dict) and last_result:
        total += estimate_tokens(json.dumps(last_result, ensure_ascii=False, default=str))
    return total


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _target_unit(structure: dict[str, Any], unit_name: str | None) -> dict[str, Any] | None:
    units = structure.get("units")
    if not isinstance(units, list):
        return None
    if unit_name:
        for unit in units:
            if isinstance(unit, dict) and str(unit.get("unit_name", "")).strip() == unit_name:
                return unit
    if len(units) == 1 and isinstance(units[0], dict):
        return units[0]
    return None


def _structure_unit_count_and_columns(structure: dict[str, Any]) -> tuple[int, int]:
    units = structure.get("units")
    if not isinstance(units, list) or not units:
        return 0, 0

    if isinstance(units[0], dict):
        total_units = len(units)
        total_columns = sum(
            _safe_int(unit.get("column_count"), len(unit.get("columns") or []))
            for unit in units
            if isinstance(unit, dict)
        )
        return total_units, total_columns

    columns_map = structure.get("columns")
    if isinstance(columns_map, dict):
        total_units = len(units)
        total_columns = sum(
            len(columns_map.get(unit, []))
            for unit in units
            if isinstance(columns_map.get(unit), list)
        )
        return total_units, total_columns

    return len(units), 0


def decide_delivery(structure: dict[str, Any]) -> dict[str, Any]:
    """Decide se entrega análise completa (ENTREGAR) ou lista opções (LISTAR)."""
    total_units, total_columns = _structure_unit_count_and_columns(structure)

    if total_units == 1 and total_columns <= 10:
        return {
            "action": "deliver_full",
            "message": "Análise completa entregue.",
            "format": "full_analysis",
        }
    if total_units == 1 and total_columns <= 20:
        return {
            "action": "list_with_summary",
            "message": "Lista de colunas com resumo.",
            "format": "columns_with_summary",
        }
    if total_units == 1 and total_columns > 20:
        return {
            "action": "list_truncated",
            "message": "Lista das 10 principais colunas.",
            "format": "top_10_columns",
        }
    if total_units <= 5:
        return {
            "action": "list_units",
            "message": "Lista de unidades com resumo.",
            "format": "units_with_summary",
        }
    return {
        "action": "list_units_compact",
        "message": "Lista compacta de unidades.",
        "format": "units_compact",
    }


def compute_complexity_score(
    structure: dict[str, Any],
    *,
    unit_name: str | None = None,
) -> float:
    """Score normalizado 0–1: quanto maior, mais caro entregar tudo."""
    units = structure.get("units")
    if not isinstance(units, list) or not units:
        return 0.0

    target = _target_unit(structure, unit_name)
    if target is not None:
        column_count = _safe_int(target.get("column_count"), len(target.get("columns") or []))
        row_count = _safe_int(target.get("row_count"))
        unit_count = 1
    else:
        column_count = sum(
            _safe_int(unit.get("column_count"), len(unit.get("columns") or []))
            for unit in units
            if isinstance(unit, dict)
        )
        row_count = sum(_safe_int(unit.get("row_count")) for unit in units if isinstance(unit, dict))
        unit_count = len(units)

    column_factor = min(column_count / 40.0, 1.0)
    row_factor = min(math.log10(max(row_count, 1) + 1) / 6.0, 1.0)
    unit_factor = min(unit_count / 12.0, 1.0)
    return min(1.0, 0.5 * column_factor + 0.3 * row_factor + 0.2 * unit_factor)


def build_delivery_plan(
    structure: dict[str, Any],
    context_consumed: int,
    *,
    llm_limit: int = LLM_LIMIT,
    action: str = "analyze_unit",
    unit_name: str | None = None,
) -> dict[str, Any]:
    """Calcula modo de entrega com base na complexidade e no orçamento de tokens."""
    remaining = max(0, llm_limit - max(0, context_consumed) - RESERVED_OUTPUT_TOKENS)
    headroom = remaining / llm_limit if llm_limit > 0 else 0.0
    complexity = compute_complexity_score(structure, unit_name=unit_name)
    effective = headroom - complexity * 0.45

    if effective >= 0.55:
        mode = "acelerador"
        depth = "full"
    elif effective >= 0.28:
        mode = "cruise"
        depth = "layer2"
    else:
        mode = "freio"
        depth = "layer1"

    if action == "analyze_vertical":
        vertical_depth = depth
    else:
        vertical_depth = depth

    use_llm = not (mode == "freio" and headroom < 0.12)

    trim = _trim_policy(mode, action)
    strategy = decide_delivery(structure)
    return {
        "mode": mode,
        "depth": vertical_depth,
        "use_llm": use_llm,
        "trim": trim,
        "action": strategy["action"],
        "message": strategy["message"],
        "format": strategy["format"],
        "budget": {
            "llm_limit": llm_limit,
            "context_consumed": context_consumed,
            "remaining_tokens": remaining,
            "headroom_ratio": round(headroom, 4),
            "complexity_score": round(complexity, 4),
            "effective_capacity": round(effective, 4),
        },
    }


def _trim_policy(mode: str, action: str) -> dict[str, Any]:
    if mode == "acelerador":
        return {
            "include_summary": True,
            "include_metrics_summary": action == "analyze_unit",
            "include_correlations": action == "analyze_unit",
            "include_layer1": True,
            "include_layer2": True,
            "include_heuristics": True,
            "include_top_values": 10,
            "include_explanation": True,
            "include_signal": True,
            "max_metrics_columns": None,
        }
    if mode == "cruise":
        return {
            "include_summary": True,
            "include_metrics_summary": action == "analyze_unit",
            "include_correlations": action == "analyze_unit",
            "include_layer1": True,
            "include_layer2": True,
            "include_heuristics": False,
            "include_top_values": 5,
            "include_explanation": True,
            "include_signal": True,
            "max_metrics_columns": 12,
        }
    return {
        "include_summary": True,
        "include_metrics_summary": False,
        "include_correlations": False,
        "include_layer1": True,
        "include_layer2": False,
        "include_heuristics": False,
        "include_top_values": 3,
        "include_explanation": False,
        "include_signal": True,
        "max_metrics_columns": 0,
    }


def trim_core_result(
    core_result: dict[str, Any],
    action: str,
    delivery_plan: dict[str, Any],
) -> dict[str, Any]:
    trim = delivery_plan.get("trim")
    if not isinstance(trim, dict):
        return dict(core_result)

    if action in ("clarify", "pending"):
        return dict(core_result)

    if action == "analyze_unit":
        return _trim_analyze_unit(core_result, trim)

    if action == "analyze_vertical":
        return _trim_analyze_vertical(core_result, trim, delivery_plan.get("depth", "layer2"))

    return dict(core_result)


def _trim_analyze_unit(core_result: dict[str, Any], trim: dict[str, Any]) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for key in ("cache_key", "unit_name"):
        if key in core_result:
            trimmed[key] = core_result[key]
    if trim.get("include_summary", True) and "summary" in core_result:
        trimmed["summary"] = core_result["summary"]
    if trim.get("include_metrics_summary"):
        metrics = core_result.get("metrics_summary")
        if isinstance(metrics, list):
            max_cols = trim.get("max_metrics_columns")
            if isinstance(max_cols, int) and max_cols > 0:
                metrics = metrics[:max_cols]
            elif max_cols == 0:
                metrics = []
            trimmed["metrics_summary"] = metrics
    if trim.get("include_correlations") and "correlations" in core_result:
        trimmed["correlations"] = core_result["correlations"]
    return trimmed


def _trim_analyze_vertical(
    core_result: dict[str, Any],
    trim: dict[str, Any],
    depth: str,
) -> dict[str, Any]:
    normalized_depth = str(depth or "layer2").strip().lower()
    trimmed: dict[str, Any] = {}
    for key in ("action", "cache_key", "unit_name", "column", "depth", "summary"):
        if key in core_result:
            trimmed[key] = core_result[key]

    if trim.get("include_signal", True) and "signal" in core_result:
        trimmed["signal"] = core_result["signal"]
    if trim.get("include_explanation") and "explanation" in core_result:
        trimmed["explanation"] = core_result["explanation"]

    include_layer1 = trim.get("include_layer1", True) and normalized_depth in {
        "layer1",
        "layer2",
        "heuristics",
        "full",
    }
    include_layer2 = trim.get("include_layer2", True) and normalized_depth in {
        "layer2",
        "heuristics",
        "full",
    }
    include_heuristics = trim.get("include_heuristics", False) and normalized_depth in {
        "heuristics",
        "full",
    }
    include_top = trim.get("include_top_values", 0)

    if include_layer1 and "layer1_metrics" in core_result:
        layer1 = dict(core_result["layer1_metrics"])
        frequency = layer1.get("frequency")
        if isinstance(frequency, dict) and include_top:
            counts = frequency.get("counts")
            if isinstance(counts, dict):
                ranked = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
                frequency = dict(frequency)
                frequency["counts"] = dict(ranked[: int(include_top)])
                layer1["frequency"] = frequency
        trimmed["layer1_metrics"] = layer1
    if include_layer2 and "layer2_metrics" in core_result:
        trimmed["layer2_metrics"] = core_result["layer2_metrics"]
    if include_heuristics and "heuristics" in core_result:
        trimmed["heuristics"] = core_result["heuristics"]
    elif "top_values" in core_result and include_top:
        top_values = core_result.get("top_values")
        if isinstance(top_values, list):
            trimmed["top_values"] = top_values[: int(include_top)]

    trimmed["depth"] = normalized_depth
    return trimmed


def _format_without_llm(core_result: dict[str, Any], action: str) -> str:
    if action == "analyze_unit":
        summary = str(core_result.get("summary", "")).strip()
        if summary:
            return summary
        unit_name = core_result.get("unit_name", "")
        return f"Análise estrutural de `{unit_name}` concluída."

    if action == "analyze_vertical":
        parts: list[str] = []
        column = core_result.get("column") or core_result.get("column_name")
        unit_name = core_result.get("unit_name", "")
        if unit_name and column:
            parts.append(f"## Coluna `{column}` em `{unit_name}`")
        summary = str(core_result.get("summary", "")).strip()
        if summary:
            parts.append(summary)
        layer1 = core_result.get("layer1_metrics")
        if isinstance(layer1, dict):
            metrics_line = ", ".join(
                f"{key}={layer1[key]}"
                for key in ("cardinality", "null_ratio", "unique_ratio")
                if key in layer1
            )
            if metrics_line:
                parts.append(f"**Métricas:** {metrics_line}")
        signal = core_result.get("signal")
        if signal is not None:
            parts.append(f"**Signal:** {signal}")
        return "\n\n".join(parts) if parts else "Análise concluída."

    return str(core_result.get("summary") or core_result.get("response") or "Análise concluída.")


def _fetch_structure(session_id: str, core_api_url: str) -> dict[str, Any]:
    response = httpx.get(
        f"{core_api_url.rstrip('/')}/sessions/{session_id}/structure",
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("core_api retornou estrutura inválida")
    return payload


def main(
    session_id: str,
    action: str,
    unit_name: str = "",
    column: str = "",
    depth: str = "layer2",
    response: str = "",
    suggested_action: dict | None = None,
    history: list | None = None,
    last_result: dict | None = None,
    context_consumed: int | None = None,
):
    base = {
        "session_id": session_id,
        "action": action,
        "unit_name": unit_name,
        "column": column,
        "response": response,
    }
    if isinstance(suggested_action, dict):
        base["suggested_action"] = suggested_action

    if action in ("clarify", "pending"):
        base["delivery_plan"] = {
            "mode": "passthrough",
            "depth": depth or "layer2",
            "use_llm": action != "clarify",
            "trim": {},
        }
        return base

    core_api_url = wmill.get_variable("f/cartographer/CORE_API_URL").rstrip("/")
    structure_payload = _fetch_structure(session_id, core_api_url)
    consumed = (
        int(context_consumed)
        if context_consumed is not None
        else estimate_context_consumed(history, last_result)
    )
    delivery_plan = build_delivery_plan(
        structure_payload,
        consumed,
        action=action,
        unit_name=unit_name or None,
    )
    base["depth"] = delivery_plan["depth"]
    base["delivery_plan"] = delivery_plan
    return base
