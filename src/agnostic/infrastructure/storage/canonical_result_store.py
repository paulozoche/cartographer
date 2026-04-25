from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agnostic.config import ANONYMOUS_USER_ID, load_app_config

logger = logging.getLogger(__name__)


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip())
    return cleaned or "unnamed"


@dataclass(frozen=True, slots=True)
class JsonFileCanonicalResultStore:
    root_dir: Path
    max_bytes: int = 1_000_000
    persist_enabled: bool = True
    max_files_per_user: int | None = 50
    quota_bytes_per_user: int | None = None  # None = sem limite; plano futuro define valor

    @classmethod
    def default(cls) -> "JsonFileCanonicalResultStore":
        storage = load_app_config().storage
        return cls(
            root_dir=storage.results_dir,
            max_bytes=storage.canonical_result_max_bytes,
            persist_enabled=storage.persist_enabled,
            max_files_per_user=storage.max_files_per_user,
            quota_bytes_per_user=storage.quota_bytes_per_user,
        )

    def user_dir(self, user_id: str = ANONYMOUS_USER_ID) -> Path:
        """Diretório raiz do usuário. Ponto de extensão para planos futuros."""
        return self.root_dir / _sanitize_name(user_id)

    def clear_user_session(self, user_id: str = ANONYMOUS_USER_ID) -> None:
        """
        Limpa todos os resultados do usuário.
        Chamado no startup do servidor para limpeza de sessão anterior.
        No futuro: pode ser chamado por plano ao encerrar sessão autenticada.
        """
        target = self.user_dir(user_id)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
            logger.info("[canonical_result_store] sessão limpa: %s", target)

    def save(
        self,
        kind: str,
        unit_name: str,
        payload: dict[str, Any],
        user_id: str = ANONYMOUS_USER_ID,
    ) -> Path:
        if not self.persist_enabled:
            logger.info(
                "[canonical_result_store] persistência desabilitada — resultado não salvo (unit=%s)",
                unit_name,
            )
            # Retorna caminho fictício para manter contrato da interface
            return self.user_dir(user_id) / _sanitize_name(kind) / f"{_sanitize_name(unit_name)}.json"

        category_dir = self.user_dir(user_id) / _sanitize_name(kind)
        category_dir.mkdir(parents=True, exist_ok=True)

        safe_unit_name = _sanitize_name(unit_name)
        payload_path = category_dir / f"{safe_unit_name}.json"
        latest_path = category_dir / "latest.json"
        self._reserve_file_slot(category_dir, payload_path, user_id)

        record = {
            "kind": kind,
            "unit_name": unit_name,
            "user_id": user_id,
            "persisted_at": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        rendered_record = _render_record_with_limit(record, max_bytes=self.max_bytes)

        # Verificar quota antes de gravar
        if self.quota_bytes_per_user is not None:
            current_usage = _dir_size_bytes(self.user_dir(user_id))
            incoming_bytes = len(rendered_record.encode("utf-8")) * 2  # payload + latest
            if current_usage + incoming_bytes > self.quota_bytes_per_user:
                logger.warning(
                    "[canonical_result_store] quota excedida para user=%s "
                    "(uso=%d bytes, limite=%d bytes) — resultado não salvo",
                    user_id, current_usage, self.quota_bytes_per_user,
                )
                return payload_path

        for target in (payload_path, latest_path):
            with target.open("w", encoding="utf-8") as handle:
                handle.write(rendered_record)

        logger.info(
            "[canonical_result_store] resultado salvo: %s (user=%s)",
            payload_path, user_id,
        )

        # Limpeza por número máximo de arquivos (exclui latest.json da contagem)
        self._enforce_max_files(category_dir, user_id)

        return payload_path

    def _enforce_max_files(self, category_dir: Path, user_id: str) -> None:
        if self.max_files_per_user is None:
            return
        # Conta apenas arquivos de resultado, não latest.json
        result_files = sorted(
            [f for f in category_dir.iterdir() if f.is_file() and f.name != "latest.json"],
            key=lambda f: f.stat().st_mtime,
        )
        excess = len(result_files) - self.max_files_per_user
        if excess > 0:
            for old_file in result_files[:excess]:
                old_file.unlink(missing_ok=True)
                logger.info(
                    "[canonical_result_store] arquivo antigo removido: %s (user=%s)",
                    old_file, user_id,
                )

    def _reserve_file_slot(self, category_dir: Path, payload_path: Path, user_id: str) -> None:
        if self.max_files_per_user is None:
            return
        # Conta apenas arquivos de resultado, não latest.json
        result_files = sorted(
            [f for f in category_dir.iterdir() if f.is_file() and f.name != "latest.json"],
            key=lambda f: f.stat().st_mtime,
        )
        if len(result_files) < self.max_files_per_user:
            return
        # Se for sobrescrita do mesmo arquivo, não cria novo slot.
        if payload_path.exists():
            return
        removals = len(result_files) - self.max_files_per_user + 1
        for old_file in result_files[:removals]:
            old_file.unlink(missing_ok=True)
            logger.info(
                "[canonical_result_store] arquivo antigo removido para abrir slot: %s (user=%s)",
                old_file, user_id,
            )


def _dir_size_bytes(directory: Path) -> int:
    if not directory.exists():
        return 0
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())


def _render_record_with_limit(record: dict[str, Any], *, max_bytes: int) -> str:
    rendered = _serialize_record(record)
    if len(rendered.encode("utf-8")) <= max_bytes:
        return rendered

    payload = record.get("payload")
    reduced_payload = _reduce_payload(payload if isinstance(payload, dict) else {})
    reduced_record = {
        **record,
        "payload_truncated": True,
        "payload_bytes_original": len(rendered.encode("utf-8")),
        "payload_limit_bytes": max_bytes,
        "payload": reduced_payload,
    }
    reduced_rendered = _serialize_record(reduced_record)
    if len(reduced_rendered.encode("utf-8")) <= max_bytes:
        return reduced_rendered

    fallback_record = {
        "kind": record.get("kind"),
        "unit_name": record.get("unit_name"),
        "user_id": record.get("user_id"),
        "persisted_at": record.get("persisted_at"),
        "payload_truncated": True,
        "payload_bytes_original": len(rendered.encode("utf-8")),
        "payload_limit_bytes": max_bytes,
        "payload": {
            "summary": str((payload or {}).get("summary") or ""),
            "unit_name": str((payload or {}).get("unit_name") or record.get("unit_name") or ""),
            "standardized": {
                "row_count": ((payload or {}).get("standardized") or {}).get("row_count"),
                "column_count": ((payload or {}).get("standardized") or {}).get("column_count"),
            },
            "notice": "Payload resumido por limite de saída.",
        },
    }
    return _serialize_record(fallback_record)


def _reduce_payload(payload: dict[str, Any]) -> dict[str, Any]:
    standardized = payload.get("standardized") if isinstance(payload.get("standardized"), dict) else {}
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    reduced_standardized: dict[str, Any] = {}
    for key in ("row_count", "column_count", "column_order"):
        if key in standardized:
            reduced_standardized[key] = standardized[key]

    reduced_source: dict[str, Any] = {}
    for key in ("display_name", "source_identifier", "unit_count", "connector_name", "fingerprint"):
        if key in source:
            reduced_source[key] = source[key]

    reduced: dict[str, Any] = {
        "summary": payload.get("summary"),
        "unit_name": payload.get("unit_name"),
        "truncated_notice": "Payload resumido por limite de persistência.",
    }
    if reduced_standardized:
        reduced["standardized"] = reduced_standardized
    if reduced_source:
        reduced["source"] = reduced_source
    return reduced


def _serialize_record(record: dict[str, Any]) -> str:
    return json.dumps(
        record,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ) + "\n"
