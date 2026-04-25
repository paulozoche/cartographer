from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InMemoryRevocationStore:
    revoked_share_ids: set[str] = field(default_factory=set)
    revoked_key_ids: set[str] = field(default_factory=set)

    def is_share_id_revoked(self, share_id: str) -> bool:
        return share_id in self.revoked_share_ids

    def is_key_id_revoked(self, key_id: str) -> bool:
        return key_id in self.revoked_key_ids

    def revoke_share_id(self, share_id: str) -> None:
        self.revoked_share_ids.add(share_id)

    def unrevoke_share_id(self, share_id: str) -> None:
        self.revoked_share_ids.discard(share_id)

    def revoke_key_id(self, key_id: str) -> None:
        self.revoked_key_ids.add(key_id)

    def unrevoke_key_id(self, key_id: str) -> None:
        self.revoked_key_ids.discard(key_id)
