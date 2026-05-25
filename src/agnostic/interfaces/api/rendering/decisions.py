from __future__ import annotations

from typing import Any


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
