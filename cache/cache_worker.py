from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from typing import TYPE_CHECKING

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    def load_dotenv() -> bool:
        return False

load_dotenv()

if TYPE_CHECKING:
    from cache.cache_manager import CacheManager

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 3600


class CacheWorker:
    """Periodic maintenance worker for Cartographer analysis cache."""

    def __init__(
        self,
        cache_manager: CacheManager,
        *,
        interval_seconds: int | None = None,
    ) -> None:
        self._cache = cache_manager
        self._interval_seconds = interval_seconds or _parse_int(
            os.getenv("AGNOSTIC_CACHE_WORKER_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS)),
            default=DEFAULT_INTERVAL_SECONDS,
        )
        self._running = True

    def run_once(self) -> dict[str, int | str]:
        """Execute one maintenance cycle."""
        removed_orphans = self._cleanup_orphan_metadata()
        removed_priority = self._cleanup_orphan_priority_entries()
        expired_fallback = self._cleanup_expired_fallback()
        active = self._cache.reconcile_active_counter()
        metrics = self._cache.get_metrics()

        summary = {
            "orphan_metadata_removed": removed_orphans,
            "orphan_priority_removed": removed_priority,
            "fallback_expired_removed": expired_fallback,
            "active_entries": active,
            "hits": metrics.hits,
            "misses": metrics.misses,
            "hit_rate": metrics.hit_rate,
            "backend": metrics.backend,
        }
        logger.info("Manutenção de cache concluída: %s", summary)
        return summary

    def run_forever(self) -> None:
        logger.info(
            "Cache worker iniciado (intervalo=%ss, backend=%s).",
            self._interval_seconds,
            self._cache.backend,
        )
        while self._running:
            try:
                self.run_once()
            except Exception:
                logger.exception("Erro no ciclo de manutenção do cache.")
            self._sleep_interruptible(self._interval_seconds)

    def stop(self) -> None:
        self._running = False

    def _cleanup_orphan_metadata(self) -> int:
        removed = 0
        if self._cache.backend != "redis" or self._cache._redis is None:
            return removed

        redis = self._cache._redis
        for session_id, cache_key in self._cache.iter_metadata_keys():
            data_key = self._cache._data_key(session_id, cache_key)
            if not redis.exists(data_key):
                meta_key = self._cache._meta_key(session_id, cache_key)
                redis.delete(meta_key)
                redis.zrem(self._cache._priority_key(session_id), cache_key)
                removed += 1
        return removed

    def _cleanup_orphan_priority_entries(self) -> int:
        removed = 0
        if self._cache.backend != "redis" or self._cache._redis is None:
            return removed

        redis = self._cache._redis
        pattern = f"{self._cache._key_prefix}:priority:*"
        prefix = f"{self._cache._key_prefix}:priority:"
        for priority_key in redis.scan_iter(match=pattern, count=50):
            session_id = priority_key[len(prefix):]
            members = redis.zrevrange(priority_key, 0, -1)
            for cache_key in members:
                data_key = self._cache._data_key(session_id, cache_key)
                if not redis.exists(data_key):
                    redis.zrem(priority_key, cache_key)
                    removed += 1
        return removed

    def _cleanup_expired_fallback(self) -> int:
        if self._cache.backend == "redis":
            return 0

        now = time.time()
        expired_keys = [
            key
            for key, entry in self._cache._fallback.items()
            if entry.expires_at <= now
        ]
        for key in expired_keys:
            del self._cache._fallback[key]
        if expired_keys:
            self._cache._fallback_stats["active"] = len(self._cache._fallback)
        return len(expired_keys)

    def _sleep_interruptible(self, seconds: int) -> None:
        deadline = time.time() + seconds
        while self._running and time.time() < deadline:
            time.sleep(min(1.0, deadline - time.time()))


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    from cache.cache_manager import CacheManager

    parser = argparse.ArgumentParser(description="Cartographer cache maintenance worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Executa um único ciclo de manutenção e encerra.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Intervalo entre ciclos em segundos (padrão: 3600).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Ativa logs detalhados.",
    )
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    cache = CacheManager.from_env()
    worker = CacheWorker(cache, interval_seconds=args.interval)

    if args.once:
        worker.run_once()
        return 0

    def _handle_signal(_signum: int, _frame: object) -> None:
        logger.info("Sinal recebido; encerrando worker...")
        worker.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
