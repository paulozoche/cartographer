from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from agnostic.application import attach_share_link_signature_v1
from agnostic.application import build_share_link_envelope_v1
from agnostic.application import build_share_state_v1
from agnostic.infrastructure.storage.revocation_store import InMemoryRevocationStore
from agnostic.interfaces.api import dependencies as deps


def test_get_revocation_store_defaults_to_memory(monkeypatch) -> None:
    monkeypatch.delenv("AGNOSTIC_REVOCATION_STORE", raising=False)
    monkeypatch.delenv("AGNOSTIC_REDIS_URL", raising=False)
    deps._build_revocation_store.cache_clear()

    store = deps.get_revocation_store()

    assert isinstance(store, InMemoryRevocationStore)


def test_get_revocation_store_uses_redis_backend_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("AGNOSTIC_REVOCATION_STORE", "redis")
    monkeypatch.setenv("AGNOSTIC_REDIS_URL", "redis://fake:6379/0")
    deps._build_revocation_store.cache_clear()

    class _FakeRedisStore:
        def is_share_id_revoked(self, share_id: str) -> bool:
            return False

        def is_key_id_revoked(self, key_id: str) -> bool:
            return False

    fake_instance = _FakeRedisStore()
    monkeypatch.setattr(
        deps.RedisRevocationStore,
        "from_url",
        classmethod(lambda cls, url: fake_instance),
    )

    store = deps.get_revocation_store()

    assert store is fake_instance


def test_get_revocation_store_raises_when_redis_backend_has_no_url(monkeypatch) -> None:
    monkeypatch.setenv("AGNOSTIC_REVOCATION_STORE", "redis")
    monkeypatch.delenv("AGNOSTIC_REDIS_URL", raising=False)
    deps._build_revocation_store.cache_clear()

    try:
        deps.get_revocation_store()
    except RuntimeError as exc:
        assert "AGNOSTIC_REDIS_URL" in str(exc)
    else:
        raise AssertionError("Era esperado RuntimeError quando Redis foi configurado sem URL.")


def _signed_envelope(*, scope: str = "unlisted") -> tuple[dict, InMemoryRevocationStore]:
    state = build_share_state_v1(
        kind="recorte",
        source_fingerprint="src-fp-001",
        unit_name="events",
        source_result_ref="/tmp/results/events.json",
        evidencia={
            "descricao": "Valor dominante observado na coluna.",
            "camada_origem": "coluna",
            "sinais": ["mode_frequency"],
            "amostra": ["A", "B"],
        },
        transicoes_permitidas=[
            {
                "destino": "valor_celula",
                "alvo_id": "vl::events::event_id::A",
                "motivo": "abrir valor dominante",
            }
        ],
        path=[
            {"layer": "origem", "node_id": "src::csv::events", "label": "origem"},
            {"layer": "tabela", "node_id": "tb::events", "label": "events"},
            {"layer": "coluna", "node_id": "col::events::event_id", "label": "event_id"},
            {"layer": "recorte", "node_id": "rc::events::event_id::dominancia::A", "label": "dominancia A"},
        ],
        recorte_id="rc::events::event_id::dominancia::A",
        generated_at=datetime(2026, 4, 17, 16, 0, tzinfo=timezone.utc),
    )
    envelope = build_share_link_envelope_v1(
        share_id="sh_0123456789abcdefABCDEF",
        scope=scope,  # type: ignore[arg-type]
        state=state,
        expires_at="2026-12-31T23:59:59Z",
    )
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )
    return signed, InMemoryRevocationStore()


def test_verify_share_envelope_for_read_accepts_valid_signed_payload() -> None:
    signed, store = _signed_envelope()

    envelope = deps.verify_share_envelope_for_read(
        signed,
        keyring={"k1": "share-secret-01"},
        revocation_store=store,
    )

    assert envelope.share_id == "sh_0123456789abcdefABCDEF"


def test_verify_share_envelope_for_read_rejects_private_scope_without_authorization() -> None:
    signed, store = _signed_envelope(scope="private")

    with pytest.raises(HTTPException) as exc_info:
        deps.verify_share_envelope_for_read(
            signed,
            keyring={"k1": "share-secret-01"},
            revocation_store=store,
        )

    assert exc_info.value.status_code == 403
    assert "privado" in str(exc_info.value.detail)


def test_verify_share_envelope_for_read_accepts_private_scope_with_authorization_flag() -> None:
    signed, store = _signed_envelope(scope="private")

    envelope = deps.verify_share_envelope_for_read(
        signed,
        keyring={"k1": "share-secret-01"},
        revocation_store=store,
        allow_private_scope=True,
    )

    assert envelope.scope == "private"


def test_verify_share_envelope_for_read_rejects_revoked_share_id() -> None:
    signed, store = _signed_envelope()
    store.revoke_share_id("sh_0123456789abcdefABCDEF")

    with pytest.raises(HTTPException) as exc_info:
        deps.verify_share_envelope_for_read(
            signed,
            keyring={"k1": "share-secret-01"},
            revocation_store=store,
        )

    assert exc_info.value.status_code == 403


def test_verify_share_envelope_for_read_rejects_expired_link() -> None:
    signed, store = _signed_envelope()
    signed["expires_at"] = "2020-01-01T00:00:00Z"
    signed = attach_share_link_signature_v1(
        {k: v for k, v in signed.items() if k != "signature"},
        secret="share-secret-01",
        key_id="k1",
    )

    with pytest.raises(HTTPException) as exc_info:
        deps.verify_share_envelope_for_read(
            signed,
            keyring={"k1": "share-secret-01"},
            revocation_store=store,
        )

    assert exc_info.value.status_code == 403
    assert "expirado" in str(exc_info.value.detail)
