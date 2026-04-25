from __future__ import annotations

import hashlib
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _string_sample(values: list[object], limit: int = 3) -> list[str]:
    sample: list[str] = []
    for value in values:
        if value is None:
            continue
        sample.append(str(value))
        if len(sample) >= limit:
            break
    return sample


def _build_preview(
    *,
    counts: dict[Any, Any],
    descending: bool,
    limit: int = 3,
) -> list[dict[str, object]]:
    if not counts:
        return []
    ordered = sorted(
        ((key, int(_safe_float(value, 0.0))) for key, value in counts.items()),
        key=lambda item: item[1],
        reverse=descending,
    )
    preview: list[dict[str, object]] = []
    for value, frequency in ordered[:limit]:
        token = "__none__" if value is None else str(value)
        preview.append(
            {
                "value": token,
                "frequency": frequency,
                "value_id": _stable_value_id(value),
            }
        )
    return preview


def _impact_from_priority(priority: str) -> float:
    return {
        "alta": 0.9,
        "media": 0.6,
        "baixa": 0.3,
    }.get(str(priority or "").strip().lower(), 0.5)


def _stable_value_id(value: Any) -> str:
    if value is None:
        payload = "none:"
    elif isinstance(value, str) and value == "":
        payload = "empty:"
    else:
        payload = f"value:{str(value)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"vid_{digest[:24]}"


def _build_dominancia_recorte(
    *,
    unit_name: str,
    column_name: str,
    mode_metric: dict[str, Any],
    counts: dict[Any, Any],
    unique_ratio: float,
    near_unique_conflict_triggered: bool,
) -> dict[str, Any] | None:
    ratio = _safe_float(mode_metric.get("ratio"), 0.0)
    mode_count = int(_safe_float(mode_metric.get("count"), 0.0))
    total_rows = sum(int(_safe_float(value, 0.0)) for value in counts.values())
    distinct_count = len(counts)
    distinct_ratio = (distinct_count / total_rows) if total_rows > 0 else 0.0
    if mode_count <= 1:
        return None
    near_unique_profile = unique_ratio >= 0.98 or distinct_ratio >= 0.98
    low_concentration = ratio < 0.03
    weak_local_max = mode_count < 4
    if near_unique_profile and low_concentration:
        return None
    if near_unique_profile and weak_local_max and not near_unique_conflict_triggered:
        return None
    mode_value = mode_metric.get("value")
    sorted_counts = sorted(
        ((key, int(_safe_float(value, 0.0))) for key, value in counts.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    dominant_limit = min(mode_count, len(sorted_counts))
    dominant_items = sorted_counts[:dominant_limit]
    if not dominant_items:
        return None
    values: list[dict[str, Any]] = []
    for raw_value, frequency in dominant_items:
        token = "__none__" if raw_value is None else str(raw_value)
        ratio_value = (frequency / total_rows) if total_rows > 0 else 0.0
        values.append(
            {
                "value_id": _stable_value_id(raw_value),
                "value": token,
                "count": frequency,
                "ratio": ratio_value,
                "actions": ["deepen", "new_base"],
                "transicoes_permitidas": [
                    {
                        "destino": "valor_celula",
                        "alvo_id": f"vl::{unit_name}::{column_name}::{token}",
                        "motivo": "aprofundar valor dominante",
                    }
                ],
            }
        )
    top_values = [str(item[0]) for item in dominant_items[:3]]
    if ratio >= 0.20:
        prioridade = "alta"
        estado = "ativo"
    elif ratio >= 0.10:
        prioridade = "media"
        estado = "ativo"
    else:
        prioridade = "baixa"
        estado = "ambiguo"
    mode_token = "__none__" if mode_value is None else str(mode_value)
    description = "Valores mais frequentes na distribuição da coluna."
    dominant_counts = {value: frequency for value, frequency in dominant_items}
    preview = _build_preview(counts=dominant_counts, descending=True, limit=3)
    metadata = {
        "name": "dominant_values",
        "mode_ratio": ratio,
        "mode_count": mode_count,
        "dominant_values_total": len(values),
        "total_rows": total_rows,
        "distinct_count": distinct_count,
        "distinct_ratio": distinct_ratio,
        "near_unique_profile": near_unique_profile,
        "near_unique_conflict_triggered": near_unique_conflict_triggered,
        "paths": ["valor/célula"],
        "type": "dominant",
        "priority": prioridade,
    }
    return {
        "id": f"rc::{unit_name}::{column_name}::dominant_values::{mode_token}",
        "tipo": "dominancia",
        "type": "dominance",
        "description": description,
        "paths": ["valor/celula"],
        "impact": _impact_from_priority(prioridade),
        "slice_type": None,
        "metadata": metadata,
        "evidencia": {
            "descricao": description,
            "camada_origem": "coluna",
            "sinais": ["mode_frequency", "frequency", "unique_ratio"],
            "amostra": top_values or [mode_token] + _string_sample(list(counts.keys())),
        },
        "prioridade": prioridade,
        "estado_estrutural": estado,
        "transicoes_permitidas": [
            {
                "destino": "valor_celula",
                "alvo_id": f"vl::{unit_name}::{column_name}::{mode_token}",
                "motivo": "explorar padrão dominante",
            },
        ],
        "preview": preview,
        "values": values,
    }


def _build_excecao_recorte(
    *,
    unit_name: str,
    column_name: str,
    counts: dict[Any, Any],
    unique_ratio: float,
    near_unique_conflict_triggered: bool,
) -> dict[str, Any] | None:
    if not counts:
        return None
    total_rows = sum(int(_safe_float(value, 0.0)) for value in counts.values())
    if total_rows <= 0:
        return None
    rare_items = sorted(
        ((key, int(_safe_float(value, 0.0))) for key, value in counts.items()),
        key=lambda item: item[1],
    )
    rare_items = [item for item in rare_items if item[1] <= 1]
    rare_total = sum(item[1] for item in rare_items)
    rare_ratio = rare_total / total_rows
    max_frequency = max((int(_safe_float(value, 0.0)) for value in counts.values()), default=0)
    mode_ratio = (max_frequency / total_rows) if total_rows > 0 else 0.0
    near_unique_profile = unique_ratio >= 0.98
    rare_mass_high = rare_ratio >= 0.5
    low_concentration = mode_ratio <= 0.01
    structurally_significant = (
        near_unique_conflict_triggered
        or rare_ratio <= 0.35
        or mode_ratio >= 0.03
        or unique_ratio <= 0.95
    )
    if near_unique_profile and rare_mass_high and low_concentration and not near_unique_conflict_triggered:
        return None
    if not structurally_significant:
        return None
    show_group_option = (
        rare_total > 5
        and rare_total < 1000
        and rare_ratio < 0.2
        and unique_ratio < 0.98
    )
    if not rare_items:
        return None
    sample_values = [str(item[0]) for item in rare_items[:3]] or _string_sample(list(counts.keys()))
    prioridade = "alta" if unique_ratio >= 0.9 else "media"
    transicoes = [
        {
            "destino": "valor_celula",
            "alvo_id": f"vl::{unit_name}::{column_name}::outlier",
            "motivo": "inspecionar valores raros",
        },
    ]
    if show_group_option:
        transicoes.append(
            {
                "destino": "recorte",
                "alvo_id": f"rc::{unit_name}::{column_name}::excecao::group",
                "motivo": "agrupar exceções para exploração em conjunto",
            }
        )
    description = "Valores raros ou singulares observados na distribuição da coluna."
    preview = _build_preview(counts=counts, descending=False, limit=3)
    metadata = {
        "rare_total": rare_total,
        "total_rows": total_rows,
        "rare_ratio": rare_ratio,
        "mode_ratio": mode_ratio,
        "near_unique_profile": near_unique_profile,
        "near_unique_conflict_triggered": near_unique_conflict_triggered,
        "structurally_significant": structurally_significant,
        "show_group_option": show_group_option,
    }
    return {
        "id": f"rc::{unit_name}::{column_name}::excecao::cluster",
        "tipo": "excecao",
        "type": "exception",
        "description": description,
        "paths": ["valor/celula"] + (["novo_recorte"] if show_group_option else []),
        "impact": _impact_from_priority(prioridade),
        "slice_type": "exception_group" if show_group_option else None,
        "metadata": metadata,
        "evidencia": {
            "descricao": description,
            "camada_origem": "coluna",
            "sinais": ["frequency", "unique_ratio"],
            "amostra": sample_values,
        },
        "prioridade": prioridade,
        "estado_estrutural": "ativo",
        "transicoes_permitidas": transicoes,
        "preview": preview,
    }


def _build_conflito_recorte(
    *,
    unit_name: str,
    column_name: str,
    counts: dict[Any, Any],
    near_unique_conflict_triggered: bool,
) -> dict[str, Any] | None:
    if not near_unique_conflict_triggered:
        return None
    if not counts:
        return None
    conflict_items = sorted(
        ((key, int(_safe_float(value, 0.0))) for key, value in counts.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    conflict_items = [item for item in conflict_items if item[1] > 1]
    if not conflict_items:
        return None
    conflict_values = [("__none__" if value is None else str(value)) for value, _ in conflict_items]
    sample_values = conflict_values[:3]
    description = "Repetições localizadas em coluna near-unique."
    preview = _build_preview(
        counts={value: frequency for value, frequency in conflict_items},
        descending=True,
        limit=3,
    )
    metadata = {
        "name": "conflict_group",
        "type": "conflict",
        "conflict_value_count": len(conflict_values),
        "conflict_values": conflict_values,
        "paths": ["valor/célula", "recorte"],
    }
    return {
        "id": f"rc::{unit_name}::{column_name}::conflito::cluster",
        "tipo": "conflito",
        "type": "conflict",
        "description": description,
        "paths": ["valor/celula", "novo_recorte"],
        "impact": _impact_from_priority("alta"),
        "slice_type": "conflict_group",
        "metadata": metadata,
        "evidencia": {
            "descricao": description,
            "camada_origem": "coluna",
            "sinais": ["near_unique_conflict", "frequency", "unique_ratio"],
            "amostra": sample_values,
        },
        "prioridade": "alta",
        "estado_estrutural": "ativo",
        "transicoes_permitidas": [
            {
                "destino": "valor_celula",
                "alvo_id": f"vl::{unit_name}::{column_name}::conflict",
                "motivo": "inspecionar valores em conflito",
            },
            {
                "destino": "recorte",
                "alvo_id": f"rc::{unit_name}::{column_name}::conflito::group",
                "motivo": "abrir recorte de conflito",
            },
        ],
        "preview": preview,
    }


def _build_ausencia_recorte(
    *,
    unit_name: str,
    column_name: str,
    null_ratio: float,
    empty_string_ratio: float,
) -> dict[str, Any] | None:
    if max(null_ratio, empty_string_ratio) < 0.10:
        return None
    if max(null_ratio, empty_string_ratio) >= 0.35:
        prioridade = "alta"
    elif max(null_ratio, empty_string_ratio) >= 0.2:
        prioridade = "media"
    else:
        prioridade = "baixa"
    description = (
        "Ausências estruturais detectadas "
        f"(null_ratio={null_ratio:.2f}, empty_string_ratio={empty_string_ratio:.2f})."
    )
    return {
        "id": f"rc::{unit_name}::{column_name}::ausencia::null-empty",
        "tipo": "ausencia",
        "type": "absence",
        "description": description,
        "preview": [{"value": "NULL", "frequency": 0}, {"value": "__empty__", "frequency": 0}],
        "paths": ["subconjunto", "valor/celula"],
        "impact": _impact_from_priority(prioridade),
        "slice_type": None,
        "metadata": {},
        "evidencia": {
            "descricao": description,
            "camada_origem": "coluna",
            "sinais": ["null_ratio", "empty_string_ratio"],
            "amostra": ["NULL", ""],
        },
        "prioridade": prioridade,
        "estado_estrutural": "ativo",
        "transicoes_permitidas": [
            {
                "destino": "subconjunto",
                "alvo_id": f"sb::{unit_name}::{column_name}::ausencia",
                "motivo": "abrir subconjunto com ausências",
            },
            {
                "destino": "valor_celula",
                "alvo_id": f"vl::{unit_name}::{column_name}::__null_or_empty__",
                "motivo": "inspecionar células ausentes",
            },
        ],
    }


def attach_internal_cuts(payload: dict[str, Any]) -> dict[str, Any]:
    unit_name = str(payload.get("unit_name") or "")
    columns = payload.get("columns")
    if not isinstance(columns, dict):
        return payload
    for column_name, column_payload in columns.items():
        if not isinstance(column_payload, dict):
            continue
        layer1 = column_payload.get("layer1_metrics") or {}
        mode_metric = layer1.get("mode_frequency") or {}
        frequency_metric = layer1.get("frequency") or {}
        counts = frequency_metric.get("counts") if isinstance(frequency_metric, dict) else {}
        if not isinstance(counts, dict):
            counts = {}
        unique_ratio = _safe_float(layer1.get("unique_ratio"), 0.0)
        null_ratio = _safe_float(layer1.get("null_ratio"), 0.0)
        empty_string_ratio = _safe_float(layer1.get("empty_string_ratio"), 0.0)
        heuristics = column_payload.get("heuristics") if isinstance(column_payload.get("heuristics"), list) else []
        near_unique_conflict_triggered = any(
            isinstance(item, dict)
            and str(item.get("name") or "") == "near_unique_conflict"
            and bool(item.get("triggered"))
            for item in heuristics
        )
        recortes: list[dict[str, Any]] = []
        dominancia = _build_dominancia_recorte(
            unit_name=unit_name or "unit",
            column_name=str(column_name),
            mode_metric=mode_metric if isinstance(mode_metric, dict) else {},
            counts=counts,
            unique_ratio=unique_ratio,
            near_unique_conflict_triggered=near_unique_conflict_triggered,
        )
        if dominancia:
            recortes.append(dominancia)
        excecao = _build_excecao_recorte(
            unit_name=unit_name or "unit",
            column_name=str(column_name),
            counts=counts,
            unique_ratio=unique_ratio,
            near_unique_conflict_triggered=near_unique_conflict_triggered,
        )
        if excecao:
            recortes.append(excecao)
        conflito = _build_conflito_recorte(
            unit_name=unit_name or "unit",
            column_name=str(column_name),
            counts=counts,
            near_unique_conflict_triggered=near_unique_conflict_triggered,
        )
        if conflito:
            recortes.append(conflito)
        ausencia = _build_ausencia_recorte(
            unit_name=unit_name or "unit",
            column_name=str(column_name),
            null_ratio=null_ratio,
            empty_string_ratio=empty_string_ratio,
        )
        if ausencia:
            recortes.append(ausencia)
        column_payload["recortes_internos"] = recortes[:5]
    return payload
