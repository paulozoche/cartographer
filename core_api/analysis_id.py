from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime


ID_FIELD_COUNT = 17
NAMESPACE = "cartographer"
DEFAULT_USUARIO = "anonimo"
DEFAULT_IMPORTANCIA = "normal"


@dataclass(frozen=True, slots=True)
class AnalysisIdFields:
    namespace: str = NAMESPACE
    usuario: str = DEFAULT_USUARIO
    intencao: str = ""
    tipo: str = ""
    sessao: str = ""
    dataset_hash: str = ""
    origem: str = ""
    alvo: str = ""
    profundidade: str = ""
    contexto: str = ""
    method: str = ""
    importancia: str = DEFAULT_IMPORTANCIA
    ramo: str = ""
    acessos: int = 0
    custo: float = 1.0
    parent_id: str = ""
    timestamp: str = ""


def sanitize_id_field(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace(":", "_").replace("\n", " ").strip()


def short_hash(value: str, *, length: int = 8) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()
    return digest[:length]


def dataset_hash_from_fingerprint(fingerprint: str) -> str:
    hex_part = fingerprint.split(":", 1)[-1] if ":" in fingerprint else fingerprint
    return hex_part[:8]


def build_analysis_id(fields: AnalysisIdFields, *, stable: bool = False) -> str:
    head = [
        sanitize_id_field(fields.namespace),
        sanitize_id_field(fields.usuario),
        sanitize_id_field(fields.intencao),
        sanitize_id_field(fields.tipo),
        sanitize_id_field(fields.sessao),
        sanitize_id_field(fields.dataset_hash),
        sanitize_id_field(fields.origem),
        sanitize_id_field(fields.alvo),
        sanitize_id_field(fields.profundidade),
        sanitize_id_field(fields.contexto),
        sanitize_id_field(fields.method),
        sanitize_id_field(fields.importancia),
        sanitize_id_field(fields.ramo),
        sanitize_id_field(fields.acessos),
        f"{fields.custo:.2f}",
        sanitize_id_field(fields.parent_id),
    ]
    if fields.timestamp:
        timestamp = fields.timestamp
    elif stable:
        timestamp = stable_timestamp_from_head(head)
    else:
        timestamp = datetime.now().isoformat(timespec="seconds")
    return ":".join(head) + ":" + timestamp


def stable_timestamp_from_head(head: list[str]) -> str:
    digest = hashlib.sha256("|".join(head).encode()).hexdigest()
    base = int(digest[:12], 16)
    day = (base % 28) + 1
    hour = (base >> 5) % 24
    minute = (base >> 10) % 60
    second = (base >> 16) % 60
    return f"1970-01-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def parse_analysis_id(cache_key: str) -> AnalysisIdFields:
    parts = cache_key.split(":")
    if len(parts) < ID_FIELD_COUNT:
        raise ValueError(f"ID inválido: esperado {ID_FIELD_COUNT}+ segmentos, recebido {len(parts)}")

    head = parts[: ID_FIELD_COUNT - 1]
    timestamp = ":".join(parts[ID_FIELD_COUNT - 1 :])
    if len(head) != ID_FIELD_COUNT - 1:
        raise ValueError("ID inválido: estrutura de campos inconsistente.")

    custo_match = re.fullmatch(r"(\d+(?:\.\d+)?)", head[14])
    if not custo_match:
        raise ValueError("ID inválido: campo custo malformado.")

    return AnalysisIdFields(
        namespace=head[0],
        usuario=head[1],
        intencao=head[2],
        tipo=head[3],
        sessao=head[4],
        dataset_hash=head[5],
        origem=head[6],
        alvo=head[7],
        profundidade=head[8],
        contexto=head[9],
        method=head[10],
        importancia=head[11],
        ramo=head[12],
        acessos=int(head[13]) if head[13].isdigit() else 0,
        custo=float(custo_match.group(1)),
        parent_id=head[15],
        timestamp=timestamp,
    )


def calcular_custo(
    method: str,
    *,
    linhas: int = 0,
    colunas: int = 0,
) -> float:
    rows = max(linhas, 0)
    cols = max(colunas, 0)
    key = method.strip().lower()

    if key == "recall":
        return 0.1
    if key in {"select", "count", "sum", "mean", "min", "max", "layer1", "layer2"}:
        return 1.0 + (rows * 0.001)
    if key in {"frequency", "heuristics", "vertical"}:
        return 2.0 + (rows * 0.002)
    if key == "sort":
        return 3.0 + (rows * 0.005)
    if key == "group_by":
        return 4.0 + (rows * 0.005)
    if key == "correlation":
        return 7.0 + (rows * 0.01)
    if key in {"join", "horizontal"}:
        return 8.0 + (rows * 0.01)
    if key in {"analyze_unit", "unit", "full"}:
        return 10.0 + (rows * 0.01) + (cols * 0.5)
    return 1.0


def lookup_key(
    *,
    analysis_type: str,
    origem: str,
    alvo: str = "",
    profundidade: str = "",
    method: str = "",
) -> str:
    return "|".join(
        [
            sanitize_id_field(analysis_type),
            sanitize_id_field(origem),
            sanitize_id_field(alvo),
            sanitize_id_field(profundidade),
            sanitize_id_field(method),
        ]
    )
