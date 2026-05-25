from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from typing import Any


ShareStateKind = Literal["recorte", "subconjunto"]
SharePathLayer = Literal["origem", "tabela", "coluna", "recorte", "subconjunto", "valor_celula", "caractere"]

ALLOWED_SHARE_STATE_KINDS: frozenset[str] = frozenset({"recorte", "subconjunto"})
ALLOWED_SHARE_PATH_LAYERS: frozenset[str] = frozenset(
    {"origem", "tabela", "coluna", "recorte", "subconjunto", "valor_celula", "caractere"}
)


def build_share_state_v1(
    *,
    kind: ShareStateKind,
    source_fingerprint: str,
    unit_name: str,
    source_result_ref: str,
    evidencia: dict[str, Any],
    transicoes_permitidas: list[dict[str, Any]],
    path: list[dict[str, str]],
    column_name: str | None = None,
    recorte_id: str | None = None,
    subconjunto_id: str | None = None,
    criterio_estrutural: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if kind not in ALLOWED_SHARE_STATE_KINDS:
        raise ValueError(f"Tipo de estado compartilhável inválido: {kind}")
    if not source_fingerprint.strip():
        raise ValueError("source_fingerprint é obrigatório.")
    if not unit_name.strip():
        raise ValueError("unit_name é obrigatório.")
    if not source_result_ref.strip():
        raise ValueError("source_result_ref é obrigatório.")
    if not path:
        raise ValueError("path deve possuir ao menos um nó.")

    if not recorte_id and not subconjunto_id:
        raise ValueError("Estado compartilhável deve referenciar recorte_id ou subconjunto_id.")
    if subconjunto_id and not recorte_id:
        raise ValueError("subconjunto_id exige recorte_id de origem para rastreabilidade.")
    if kind == "recorte" and not recorte_id:
        raise ValueError("Estado do tipo recorte exige recorte_id.")
    if kind == "subconjunto" and not subconjunto_id:
        raise ValueError("Estado do tipo subconjunto exige subconjunto_id.")

    normalized_path: list[dict[str, str]] = []
    for node in path:
        layer = str(node.get("layer", "")).strip()
        node_id = str(node.get("node_id", "")).strip()
        label = str(node.get("label", "")).strip()
        if layer not in ALLOWED_SHARE_PATH_LAYERS:
            raise ValueError(f"Camada inválida no path compartilhável: {layer}")
        if not node_id:
            raise ValueError("node_id é obrigatório em cada nó do path.")
        if not label:
            raise ValueError("label é obrigatório em cada nó do path.")
        normalized_path.append({"layer": layer, "node_id": node_id, "label": label})

    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": "share-state.v1",
        "kind": kind,
        "anchor": {
            "source_fingerprint": source_fingerprint.strip(),
            "unit_name": unit_name.strip(),
            "column_name": column_name.strip() if column_name else None,
            "recorte_id": recorte_id.strip() if recorte_id else None,
            "subconjunto_id": subconjunto_id.strip() if subconjunto_id else None,
            "criterio_estrutural": criterio_estrutural.strip() if criterio_estrutural else None,
        },
        "path": normalized_path,
        "evidencia": evidencia,
        "transicoes_permitidas": transicoes_permitidas,
        "source_result_ref": source_result_ref.strip(),
        "generated_at": timestamp.isoformat(),
    }


__all__ = [
    "ShareStateKind",
    "SharePathLayer",
    "ALLOWED_SHARE_STATE_KINDS",
    "ALLOWED_SHARE_PATH_LAYERS",
    "build_share_state_v1",
]
