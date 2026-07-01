from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RedisSetClient(Protocol):
    def sismember(self, name: str, value: str) -> bool | int: ...

    def sadd(self, name: str, *values: str) -> int: ...

    def srem(self, name: str, *values: str) -> int: ...


@dataclass(slots=True)
class RedisRevocationStore:
    client: RedisSetClient
    share_ids_key: str = "agnostic:revoked:share_ids"
    key_ids_key: str = "agnostic:revoked:key_ids"

    @classmethod
    def from_url(cls, redis_url: str) -> "RedisRevocationStore":
        try:
            from redis import Redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "Pacote 'redis' não está instalado. Instale para usar RedisRevocationStore.from_url."
            ) from exc

        client = Redis.from_url(redis_url, decode_responses=True)
        return cls(client=client)

    def is_share_id_revoked(self, share_id: str) -> bool:
        return bool(self.client.sismember(self.share_ids_key, share_id))

    def is_key_id_revoked(self, key_id: str) -> bool:
        return bool(self.client.sismember(self.key_ids_key, key_id))

    def revoke_share_id(self, share_id: str) -> None:
        self.client.sadd(self.share_ids_key, share_id)

    def unrevoke_share_id(self, share_id: str) -> None:
        self.client.srem(self.share_ids_key, share_id)

    def revoke_key_id(self, key_id: str) -> None:
        self.client.sadd(self.key_ids_key, key_id)

    def unrevoke_key_id(self, key_id: str) -> None:
        self.client.srem(self.key_ids_key, key_id)
