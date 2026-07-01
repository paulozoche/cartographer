from __future__ import annotations

import hashlib
from pathlib import Path


def get_dataset_hash(dataset_path: str) -> str:
    """Retorna hash MD5 (8 primeiros caracteres) do caminho absoluto do dataset."""
    absolute_path = str(Path(dataset_path).resolve())
    return hashlib.md5(absolute_path.encode()).hexdigest()[:8]


def build_internal_id(dataset_hash: str, entity_type: str, identifier: str | int) -> str:
    """Constrói ID interno no formato: <hash>:<tipo>:<identificador>."""
    return f"{dataset_hash}:{entity_type}:{identifier}"


def sanitize_value_identifier(value: str) -> str:
    """Sanitiza valor para uso como identificador interno."""
    return str(value).replace(" ", "_").replace(":", "_")[:50]
