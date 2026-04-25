from __future__ import annotations

from agnostic.infrastructure.storage.revocation_store_redis import RedisRevocationStore


class _FakeRedisClient:
    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = {}

    def sismember(self, name: str, value: str) -> int:
        return 1 if value in self._sets.get(name, set()) else 0

    def sadd(self, name: str, *values: str) -> int:
        bucket = self._sets.setdefault(name, set())
        before = len(bucket)
        bucket.update(values)
        return len(bucket) - before

    def srem(self, name: str, *values: str) -> int:
        bucket = self._sets.setdefault(name, set())
        removed = 0
        for value in values:
            if value in bucket:
                bucket.remove(value)
                removed += 1
        return removed


def test_redis_revocation_store_share_id_lifecycle() -> None:
    store = RedisRevocationStore(client=_FakeRedisClient())

    assert store.is_share_id_revoked("sh_01") is False
    store.revoke_share_id("sh_01")
    assert store.is_share_id_revoked("sh_01") is True
    store.unrevoke_share_id("sh_01")
    assert store.is_share_id_revoked("sh_01") is False


def test_redis_revocation_store_key_id_lifecycle() -> None:
    store = RedisRevocationStore(client=_FakeRedisClient())

    assert store.is_key_id_revoked("k1") is False
    store.revoke_key_id("k1")
    assert store.is_key_id_revoked("k1") is True
    store.unrevoke_key_id("k1")
    assert store.is_key_id_revoked("k1") is False
