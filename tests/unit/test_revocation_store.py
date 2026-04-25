from __future__ import annotations

from agnostic.infrastructure.storage.revocation_store import InMemoryRevocationStore


def test_in_memory_revocation_store_revokes_and_unrevokes_share_id() -> None:
    store = InMemoryRevocationStore()

    assert store.is_share_id_revoked("sh_01") is False
    store.revoke_share_id("sh_01")
    assert store.is_share_id_revoked("sh_01") is True
    store.unrevoke_share_id("sh_01")
    assert store.is_share_id_revoked("sh_01") is False


def test_in_memory_revocation_store_revokes_and_unrevokes_key_id() -> None:
    store = InMemoryRevocationStore()

    assert store.is_key_id_revoked("k1") is False
    store.revoke_key_id("k1")
    assert store.is_key_id_revoked("k1") is True
    store.unrevoke_key_id("k1")
    assert store.is_key_id_revoked("k1") is False
