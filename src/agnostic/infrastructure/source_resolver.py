from __future__ import annotations

from pathlib import Path

from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.infrastructure.normalizer import DataNormalizer


def resolve_source(path: str) -> SQLiteDataSource:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Caminho não encontrado: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"O caminho deve apontar para um arquivo: {resolved}")
    connection = DataNormalizer.normalize(str(resolved))
    return SQLiteDataSource.from_connection(connection, str(resolved))
