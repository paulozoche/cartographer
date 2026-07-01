"""Normalizador de formatos de dados para SQLite."""

from __future__ import annotations

import csv
import logging
import os
import sqlite3
from pathlib import Path

from agnostic.infrastructure.normalizer.legacy.csv_source import _detect_encoding

logger = logging.getLogger(__name__)


class DataNormalizer:
    """Converte qualquer formato suportado para SQLite em memória."""

    SUPPORTED_EXTENSIONS = {".csv", ".parquet", ".db", ".sqlite", ".sqlite3"}

    @classmethod
    def normalize(cls, source_path: str, delimiter: str | None = None) -> sqlite3.Connection:
        """
        Converte arquivo para SQLite em memória.

        Args:
            source_path: Caminho do arquivo original
            delimiter: Delimitador para CSV; se None, detecta automaticamente

        Returns:
            Conexão SQLite em memória com os dados
        """
        logger.info("Normalizando: %s", source_path)
        path = Path(source_path).expanduser().resolve()
        suffix = path.suffix.lower()
        logger.info("Extensão: %s", suffix)

        if not path.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {source_path}")
        if not path.is_file():
            raise ValueError(f"O caminho deve apontar para um arquivo: {path}")

        logger.info("Tamanho do arquivo: %s bytes", os.path.getsize(path))

        if suffix in {".db", ".sqlite", ".sqlite3"}:
            return cls._copy_sqlite_to_memory(str(path))

        if suffix == ".csv":
            return cls._csv_to_sqlite(str(path), delimiter)

        if suffix == ".parquet":
            return cls._parquet_to_sqlite(str(path))

        supported = ", ".join(sorted(cls.SUPPORTED_EXTENSIONS))
        raise ValueError(f"Formato não suportado: {suffix or '<sem extensão>'}. Use {supported}.")

    @classmethod
    def _detect_delimiter(cls, csv_path: str, encoding: str) -> str:
        """Detecta o delimitador do CSV analisando a primeira linha."""
        with open(csv_path, "r", encoding=encoding, newline="") as handle:
            first_line = handle.readline()

        delimiters = [";", ",", "\t", "|"]
        for delim in delimiters:
            if delim in first_line:
                count = first_line.count(delim)
                if count >= 2:
                    return delim
        return ","

    @classmethod
    def _csv_to_sqlite(cls, csv_path: str, delimiter: str | None = None) -> sqlite3.Connection:
        """Converte CSV para SQLite em memória com detecção automática de encoding."""
        encoding = _detect_encoding(csv_path)
        if encoding == "utf-8":
            encoding = "utf-8-sig"
        logger.info("Encoding detectado: %s", encoding)

        if delimiter is None:
            delimiter = cls._detect_delimiter(csv_path, encoding)
            logger.info("Delimitador detectado: %s", repr(delimiter))

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cursor = conn.cursor()

        with open(csv_path, "r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            headers = next(reader, None)

        if headers is None:
            raise ValueError(f"CSV vazio: {csv_path}")

        headers = [h.strip().replace(" ", "_") for h in headers]
        columns = ", ".join([f'"{h}" TEXT' for h in headers])
        cursor.execute(f"CREATE TABLE data ({columns})")

        with open(csv_path, "r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            next(reader)
            placeholders = ", ".join(["?"] * len(headers))
            for row in reader:
                if len(row) < len(headers):
                    row.extend([""] * (len(headers) - len(row)))
                cursor.execute(f"INSERT INTO data VALUES ({placeholders})", row[: len(headers)])

        conn.commit()
        return conn

    @classmethod
    def _parquet_to_sqlite(cls, parquet_path: str) -> sqlite3.Connection:
        """Converte Parquet para SQLite em memória."""
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("pandas é necessário para ler arquivos Parquet") from exc

        df = pd.read_parquet(parquet_path)
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        df.to_sql("data", conn, index=False)
        return conn

    @classmethod
    def _copy_sqlite_to_memory(cls, db_path: str) -> sqlite3.Connection:
        """Copia banco SQLite para memória."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        source = sqlite3.connect(db_path, check_same_thread=False)
        try:
            source.backup(conn)
        finally:
            source.close()
        return conn
