#!/usr/bin/env python3
"""Exemplo de uso do cache Redis integrado ao CoreService."""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_PATH / "src"))
sys.path.insert(0, str(ROOT_PATH))

from dotenv import load_dotenv

load_dotenv(ROOT_PATH / ".env")

from cache.cache_manager import CacheManager
from cache.cache_worker import CacheWorker
from core_api.core_service import CoreService

logger = logging.getLogger(__name__)


class CachedCoreService:
    """Wrapper fino: CoreService + CacheManager compartilhando o contrato de cache_key."""

    def __init__(self, service: CoreService, cache: CacheManager, session_id: str) -> None:
        self._service = service
        self._cache = cache
        self._session_id = session_id

    @property
    def unit_names(self) -> list[str]:
        return self._service.unit_names

    def analyze_unit(self, unit_name: str) -> dict[str, object]:
        cache_key = f"unit:{unit_name}"
        return self._cache.get_or_process(
            self._session_id,
            cache_key,
            lambda: self._service.analyze_unit(unit_name),
        )

    def analyze_vertical(self, unit_name: str, depth: str, column_key: str) -> dict[str, object]:
        column_name = self._service._resolve_column_name(unit_name, column_key)
        normalized_depth = depth.strip().lower()
        cache_key = f"vertical:{unit_name}:{column_name}:{normalized_depth}"
        return self._cache.get_or_process(
            self._session_id,
            cache_key,
            lambda: self._service.analyze_vertical(unit_name, depth, column_key),
        )

    def recall(self, cache_key: str) -> object:
        return self._cache.recall(self._session_id, cache_key)

    def get_metrics(self) -> dict[str, object]:
        metrics = self._cache.get_metrics(session_id=self._session_id)
        return {
            "hits": metrics.hits,
            "misses": metrics.misses,
            "active": metrics.active,
            "hit_rate": metrics.hit_rate,
            "backend": metrics.backend,
            "top_analyses": metrics.top_analyses,
        }


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _demo(source_path: Path) -> None:
    cache = CacheManager.from_env()
    service = CoreService(str(source_path))
    session_id = str(uuid.uuid4())
    cached = CachedCoreService(service, cache, session_id)

    unit_name = cached.unit_names[0]
    logger.info("Sessão=%s unidade=%s backend=%s", session_id, unit_name, cache.backend)

    first = cached.analyze_unit(unit_name)
    second = cached.analyze_unit(unit_name)
    assert first["cache_key"] == second["cache_key"]

    recalled = cached.recall(first["cache_key"])
    assert recalled == second

    metrics = cached.get_metrics()
    logger.info("Métricas: %s", metrics)
    logger.info("Health: %s", cache.health_check())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cartographer cache demo / launcher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="Executa exemplo com CoreService.")
    demo_parser.add_argument(
        "source",
        type=Path,
        help="Caminho para arquivo tabular (.sqlite, .csv, .parquet).",
    )
    demo_parser.add_argument("--verbose", action="store_true")

    worker_parser = subparsers.add_parser("worker", help="Inicia o worker de manutenção.")
    worker_parser.add_argument("--once", action="store_true")
    worker_parser.add_argument("--interval", type=int, default=None)
    worker_parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    if args.command == "demo":
        if not args.source.exists():
            logger.error("Arquivo não encontrado: %s", args.source)
            return 1
        _demo(args.source)
        return 0

    if args.command == "worker":
        cache = CacheManager.from_env()
        worker = CacheWorker(cache, interval_seconds=args.interval)
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
