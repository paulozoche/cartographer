from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    def load_dotenv() -> bool:
        return False

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 8 * 3600
DEFAULT_REDIS_TIMEOUT_SECONDS = 2.0
DEFAULT_KEY_PREFIX = "cartographer:cache"
DEFAULT_FALLBACK_MAX_ITEMS = 200


class RedisClient(Protocol):
    def get(self, name: str) -> bytes | str | None: ...

    def set(self, name: str, value: str | bytes, ex: int | None = None) -> bool | None: ...

    def delete(self, *names: str) -> int: ...

    def expire(self, name: str, time: int) -> bool: ...

    def exists(self, *names: str) -> int: ...

    def hgetall(self, name: str) -> dict[str, str]: ...

    def hset(self, name: str, mapping: dict[str, str | int | float]) -> int: ...

    def hincrby(self, name: str, key: str, amount: int = 1) -> int: ...

    def zincrby(self, name: str, amount: float, value: str) -> float: ...

    def zrevrange(self, name: str, start: int, end: int, withscores: bool = False) -> list: ...

    def zrem(self, name: str, *values: str) -> int: ...

    def scan_iter(self, match: str | None = None, count: int | None = None): ...

    def info(self, section: str | None = None) -> dict[str, Any]: ...

    def ping(self) -> bool: ...


@dataclass(slots=True)
class CacheMetrics:
    hits: int = 0
    misses: int = 0
    active: int = 0
    hit_rate: float = 0.0
    memory_used_bytes: int | None = None
    backend: str = "memory"
    top_analyses: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class _FallbackEntry:
    payload: Any
    expires_at: float
    metadata: dict[str, str]


class CacheManager:
    """Redis-backed cache with TTL renewal, metadata hashes, and metrics."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        ttl_seconds: int | None = None,
        timeout_seconds: float | None = None,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        fallback_max_items: int = DEFAULT_FALLBACK_MAX_ITEMS,
    ) -> None:
        self._ttl_seconds = ttl_seconds or _parse_int(
            os.getenv("AGNOSTIC_CACHE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)),
            default=DEFAULT_TTL_SECONDS,
        )
        self._timeout_seconds = timeout_seconds or _parse_float(
            os.getenv("AGNOSTIC_CACHE_TIMEOUT_SECONDS", str(DEFAULT_REDIS_TIMEOUT_SECONDS)),
            default=DEFAULT_REDIS_TIMEOUT_SECONDS,
        )
        self._key_prefix = key_prefix
        self._fallback_max_items = fallback_max_items
        self._fallback: OrderedDict[str, _FallbackEntry] = OrderedDict()
        self._fallback_stats = {"hits": 0, "misses": 0, "active": 0}
        self._redis: RedisClient | None = None
        self._backend = "memory"

        resolved_url = (redis_url or os.getenv("AGNOSTIC_REDIS_URL", "")).strip()
        if resolved_url:
            self._connect_redis(resolved_url)

    @classmethod
    def from_env(cls) -> CacheManager:
        return cls()

    def _connect_redis(self, redis_url: str) -> None:
        try:
            from redis import Redis
            from redis.exceptions import RedisError
        except ImportError as exc:  # pragma: no cover
            logger.warning("Pacote redis não instalado; usando fallback em memória.")
            return

        self._redis_error = RedisError
        try:
            client = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=self._timeout_seconds,
                socket_timeout=self._timeout_seconds,
            )
            client.ping()
            self._redis = client
            self._backend = "redis"
            logger.info("CacheManager conectado ao Redis.")
        except RedisError as exc:
            logger.warning("Redis indisponível (%s); usando fallback em memória.", exc)
            self._redis = None
            self._backend = "memory"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def _data_key(self, session_id: str, cache_key: str) -> str:
        return f"{self._key_prefix}:data:{session_id}:{cache_key}"

    def _meta_key(self, session_id: str, cache_key: str) -> str:
        return f"{self._key_prefix}:meta:{session_id}:{cache_key}"

    def _priority_key(self, session_id: str) -> str:
        return f"{self._key_prefix}:priority:{session_id}"

    def _stats_key(self) -> str:
        return f"{self._key_prefix}:stats:global"

    @staticmethod
    def _fallback_storage_key(session_id: str, cache_key: str) -> str:
        return f"{session_id}:{cache_key}"

    @staticmethod
    def compute_analysis_hash(payload: Any) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def get(self, session_id: str, cache_key: str) -> Any | None:
        if self._redis is not None:
            try:
                return self._redis_get(session_id, cache_key)
            except self._redis_error as exc:
                logger.warning("GET falhou no Redis (%s); tentando fallback.", exc)

        return self._fallback_get(session_id, cache_key)

    def set(
        self,
        session_id: str,
        cache_key: str,
        payload: Any,
        *,
        analysis_hash: str | None = None,
    ) -> None:
        resolved_hash = analysis_hash or self.compute_analysis_hash(payload)
        if self._redis is not None:
            try:
                self._redis_set(session_id, cache_key, payload, resolved_hash)
                return
            except self._redis_error as exc:
                logger.warning("SET falhou no Redis (%s); usando fallback.", exc)

        self._fallback_set(session_id, cache_key, payload, resolved_hash)

    def delete(self, session_id: str, cache_key: str) -> bool:
        if self._redis is not None:
            try:
                return self._redis_delete(session_id, cache_key)
            except self._redis_error as exc:
                logger.warning("DELETE falhou no Redis (%s); usando fallback.", exc)

        return self._fallback_delete(session_id, cache_key)

    def get_or_process(
        self,
        session_id: str,
        cache_key: str,
        processor: Callable[[], Any],
        *,
        analysis_hash: str | None = None,
    ) -> Any:
        cached = self.get(session_id, cache_key)
        if cached is not None:
            return cached

        result = processor()
        self.set(session_id, cache_key, result, analysis_hash=analysis_hash)
        return result

    def recall(self, session_id: str, cache_key: str) -> Any:
        value = self.get(session_id, cache_key)
        if value is None:
            raise KeyError(f"Chave de cache não encontrada: {cache_key}")
        return value

    def get_metrics(self, session_id: str | None = None, *, top_limit: int = 10) -> CacheMetrics:
        if self._redis is not None:
            try:
                return self._redis_metrics(session_id=session_id, top_limit=top_limit)
            except self._redis_error as exc:
                logger.warning("Métricas indisponíveis no Redis (%s); usando fallback.", exc)

        hits = self._fallback_stats["hits"]
        misses = self._fallback_stats["misses"]
        active = len(self._fallback)
        total = hits + misses
        hit_rate = (hits / total) if total else 0.0
        top = self._fallback_top(session_id, top_limit) if session_id else []
        return CacheMetrics(
            hits=hits,
            misses=misses,
            active=active,
            hit_rate=round(hit_rate, 4),
            memory_used_bytes=None,
            backend=self._backend,
            top_analyses=top,
        )

    def get_top_analyses(self, session_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        metrics = self.get_metrics(session_id=session_id, top_limit=limit)
        return metrics.top_analyses

    def health_check(self) -> dict[str, Any]:
        if self._redis is None:
            return {
                "status": "degraded",
                "backend": "memory",
                "redis": "unavailable",
                "fallback_entries": len(self._fallback),
            }

        try:
            self._redis.ping()
            info = self._redis.info("memory")
            return {
                "status": "ok",
                "backend": "redis",
                "redis": "connected",
                "memory_used_bytes": info.get("used_memory"),
            }
        except self._redis_error as exc:
            return {
                "status": "degraded",
                "backend": "redis",
                "redis": "error",
                "error": str(exc),
                "fallback_entries": len(self._fallback),
            }

    def _redis_get(self, session_id: str, cache_key: str) -> Any | None:
        assert self._redis is not None
        data_key = self._data_key(session_id, cache_key)
        raw = self._redis.get(data_key)
        if raw is None:
            self._redis.hincrby(self._stats_key(), "misses", 1)
            return None

        self._redis.expire(data_key, self._ttl_seconds)
        meta_key = self._meta_key(session_id, cache_key)
        now = str(time.time())
        self._redis.hset(
            meta_key,
            mapping={
                "last_accessed_at": now,
            },
        )
        self._redis.expire(meta_key, self._ttl_seconds)
        self._redis.hincrby(meta_key, "access_count", 1)
        self._redis.hincrby(self._stats_key(), "hits", 1)
        self._redis.zincrby(self._priority_key(session_id), 1, cache_key)
        return json.loads(raw)

    def _redis_set(
        self,
        session_id: str,
        cache_key: str,
        payload: Any,
        analysis_hash: str,
    ) -> None:
        assert self._redis is not None
        encoded = json.dumps(payload, default=str)
        now = str(time.time())
        data_key = self._data_key(session_id, cache_key)
        meta_key = self._meta_key(session_id, cache_key)
        existed = bool(self._redis.exists(data_key))

        pipe = self._redis  # redis-py supports pipeline but keep simple for clarity
        pipe.set(data_key, encoded, ex=self._ttl_seconds)
        pipe.hset(
            meta_key,
            mapping={
                "session_id": session_id,
                "cache_key": cache_key,
                "analysis_hash": analysis_hash,
                "created_at": now,
                "last_accessed_at": now,
                "access_count": "0",
                "size_bytes": str(len(encoded.encode())),
                "rework_count": "0",
                "last_rework_at": "",
                "trace_id": "",
            },
        )
        pipe.expire(meta_key, self._ttl_seconds)
        pipe.zincrby(self._priority_key(session_id), 0, cache_key)
        if not existed:
            pipe.hincrby(self._stats_key(), "active", 1)

    def _redis_delete(self, session_id: str, cache_key: str) -> bool:
        assert self._redis is not None
        data_key = self._data_key(session_id, cache_key)
        meta_key = self._meta_key(session_id, cache_key)
        removed = self._redis.delete(data_key, meta_key)
        self._redis.zrem(self._priority_key(session_id), cache_key)
        if removed:
            self._redis.hincrby(self._stats_key(), "active", -1)
        return bool(removed)

    def _redis_metrics(self, *, session_id: str | None, top_limit: int) -> CacheMetrics:
        assert self._redis is not None
        stats = self._redis.hgetall(self._stats_key())
        hits = int(stats.get("hits", 0))
        misses = int(stats.get("misses", 0))
        active = int(stats.get("active", 0))
        total = hits + misses
        hit_rate = (hits / total) if total else 0.0

        memory_used_bytes: int | None = None
        try:
            info = self._redis.info("memory")
            memory_used_bytes = int(info.get("used_memory", 0))
        except self._redis_error:
            memory_used_bytes = None

        top: list[dict[str, Any]] = []
        if session_id:
            ranked = self._redis.zrevrange(
                self._priority_key(session_id),
                0,
                max(top_limit - 1, 0),
                withscores=True,
            )
            for member, score in ranked:
                meta = self._redis.hgetall(self._meta_key(session_id, member))
                top.append(
                    {
                        "cache_key": member,
                        "access_count": int(meta.get("access_count", score)),
                        "analysis_hash": meta.get("analysis_hash", ""),
                        "last_accessed_at": meta.get("last_accessed_at", ""),
                    }
                )

        return CacheMetrics(
            hits=hits,
            misses=misses,
            active=active,
            hit_rate=round(hit_rate, 4),
            memory_used_bytes=memory_used_bytes,
            backend=self._backend,
            top_analyses=top,
        )

    def _fallback_get(self, session_id: str, cache_key: str) -> Any | None:
        storage_key = self._fallback_storage_key(session_id, cache_key)
        entry = self._fallback.get(storage_key)
        if entry is None:
            self._fallback_stats["misses"] += 1
            return None

        if entry.expires_at <= time.time():
            del self._fallback[storage_key]
            self._fallback_stats["active"] = len(self._fallback)
            self._fallback_stats["misses"] += 1
            return None

        self._fallback.move_to_end(storage_key)
        now = str(time.time())
        entry.metadata["last_accessed_at"] = now
        entry.metadata["access_count"] = str(int(entry.metadata.get("access_count", "0")) + 1)
        self._fallback_stats["hits"] += 1
        entry.expires_at = time.time() + self._ttl_seconds
        return json.loads(json.dumps(entry.payload, default=str))

    def _fallback_set(
        self,
        session_id: str,
        cache_key: str,
        payload: Any,
        analysis_hash: str,
    ) -> None:
        storage_key = self._fallback_storage_key(session_id, cache_key)
        now = str(time.time())
        existed = storage_key in self._fallback
        encoded = json.dumps(payload, default=str)
        self._fallback[storage_key] = _FallbackEntry(
            payload=json.loads(encoded),
            expires_at=time.time() + self._ttl_seconds,
            metadata={
                "session_id": session_id,
                "cache_key": cache_key,
                "analysis_hash": analysis_hash,
                "created_at": now,
                "last_accessed_at": now,
                "access_count": "0",
                "size_bytes": str(len(encoded.encode())),
                "rework_count": "0",
                "last_rework_at": "",
                "trace_id": "",
            },
        )
        self._fallback.move_to_end(storage_key)
        while len(self._fallback) > self._fallback_max_items:
            self._fallback.popitem(last=False)
        if not existed:
            self._fallback_stats["active"] = len(self._fallback)

    def _fallback_delete(self, session_id: str, cache_key: str) -> bool:
        storage_key = self._fallback_storage_key(session_id, cache_key)
        if storage_key not in self._fallback:
            return False
        del self._fallback[storage_key]
        self._fallback_stats["active"] = len(self._fallback)
        return True

    def _fallback_top(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        ranked: list[tuple[str, _FallbackEntry]] = []
        prefix = f"{session_id}:"
        for key, entry in self._fallback.items():
            if key.startswith(prefix):
                ranked.append((key.split(":", 1)[1], entry))
        ranked.sort(key=lambda item: int(item[1].metadata.get("access_count", "0")), reverse=True)
        return [
            {
                "cache_key": cache_key,
                "access_count": int(entry.metadata.get("access_count", "0")),
                "analysis_hash": entry.metadata.get("analysis_hash", ""),
                "last_accessed_at": entry.metadata.get("last_accessed_at", ""),
            }
            for cache_key, entry in ranked[:limit]
        ]

    def iter_metadata_keys(self) -> list[tuple[str, str]]:
        """Return (session_id, cache_key) pairs for maintenance scans."""
        pairs: list[tuple[str, str]] = []
        if self._redis is not None:
            pattern = f"{self._key_prefix}:meta:*"
            prefix_len = len(f"{self._key_prefix}:meta:")
            for key in self._redis.scan_iter(match=pattern, count=100):
                remainder = key[prefix_len:]
                session_id, _, cache_key = remainder.partition(":")
                if session_id and cache_key:
                    pairs.append((session_id, cache_key))
            return pairs

        for storage_key in self._fallback:
            session_id, cache_key = storage_key.split(":", 1)
            pairs.append((session_id, cache_key))
        return pairs

    def reconcile_active_counter(self) -> int:
        """Recount active entries and sync global counter."""
        if self._redis is None:
            self._fallback_stats["active"] = len(self._fallback)
            return self._fallback_stats["active"]

        count = 0
        pattern = f"{self._key_prefix}:data:*"
        for _key in self._redis.scan_iter(match=pattern, count=100):
            count += 1
        self._redis.hset(self._stats_key(), mapping={"active": str(count)})
        return count


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_float(value: str, *, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default
