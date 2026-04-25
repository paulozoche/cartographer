from __future__ import annotations

from typing import Protocol


class RevocationStore(Protocol):
    def is_share_id_revoked(self, share_id: str) -> bool: ...

    def is_key_id_revoked(self, key_id: str) -> bool: ...
