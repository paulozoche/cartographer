from __future__ import annotations

import sys
from pathlib import Path

ROOT_PATH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_PATH))

from cache.cache_manager import CacheManager


def test_cache_get_or_process_fallback() -> None:
    cache = CacheManager(redis_url="", ttl_seconds=60)
    calls = {"count": 0}

    def processor() -> dict[str, str]:
        calls["count"] += 1
        return {"cache_key": "unit:demo", "value": "ok"}

    first = cache.get_or_process("session-1", "unit:demo", processor)
    second = cache.get_or_process("session-1", "unit:demo", processor)

    assert first == second
    assert calls["count"] == 1

    metrics = cache.get_metrics(session_id="session-1")
    assert metrics.hits >= 1
    assert metrics.active == 1
    assert metrics.backend == "memory"


def test_cache_delete_fallback() -> None:
    cache = CacheManager(redis_url="", ttl_seconds=60)
    cache.set("session-1", "unit:x", {"cache_key": "unit:x"})
    assert cache.get("session-1", "unit:x") is not None
    assert cache.delete("session-1", "unit:x") is True
    assert cache.get("session-1", "unit:x") is None


def test_cache_recall_raises_on_miss() -> None:
    cache = CacheManager(redis_url="")
    try:
        cache.recall("session-1", "missing")
        assert False, "expected KeyError"
    except KeyError:
        pass
