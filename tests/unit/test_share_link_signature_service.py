from __future__ import annotations

from datetime import datetime, timezone

from agnostic.application import ShareSigningKey
from agnostic.application import attach_share_link_signature_with_rotation_v1
from agnostic.application import attach_share_link_signature_v1
from agnostic.application import build_share_link_envelope_v1
from agnostic.application import build_share_verification_keyring_v1
from agnostic.application import build_share_state_v1
from agnostic.application import is_share_link_revoked_v1
from agnostic.application import verify_share_link_signature_v1
from agnostic.application import verify_share_state_hash_v1
from agnostic.infrastructure.storage.revocation_store import InMemoryRevocationStore


def _envelope_payload() -> dict:
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
        generated_at=datetime(2026, 4, 17, 15, 0, tzinfo=timezone.utc),
    )
    return build_share_link_envelope_v1(
        share_id="sh_0123456789abcdefABCDEF",
        scope="unlisted",
        state=state,
        expires_at="2026-12-31T23:59:59Z",
    )


def test_share_link_signature_service_signs_and_verifies() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )

    assert verify_share_state_hash_v1(signed) is True
    assert verify_share_link_signature_v1(signed, keyring={"k1": "share-secret-01"}) is True


def test_share_link_signature_service_rejects_tampered_state_hash() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )
    signed["state_hash"] = "0" * 64

    assert verify_share_state_hash_v1(signed) is False
    assert verify_share_link_signature_v1(signed, keyring={"k1": "share-secret-01"}) is False


def test_share_link_signature_service_rejects_unknown_key_id() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )

    assert verify_share_link_signature_v1(signed, keyring={"k2": "share-secret-01"}) is False


def test_share_link_signature_service_rejects_tampered_scope() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )
    signed["scope"] = "private"

    assert verify_share_link_signature_v1(signed, keyring={"k1": "share-secret-01"}) is False


def test_share_link_signature_service_rejects_tampered_expires_at() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )
    signed["expires_at"] = "2030-01-01T00:00:00Z"

    assert verify_share_link_signature_v1(signed, keyring={"k1": "share-secret-01"}) is False


def test_share_link_signature_service_rejects_revoked_share_id() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )

    assert is_share_link_revoked_v1(
        signed,
        revoked_share_ids={"sh_0123456789abcdefABCDEF"},
    ) is True
    assert verify_share_link_signature_v1(
        signed,
        keyring={"k1": "share-secret-01"},
        revoked_share_ids={"sh_0123456789abcdefABCDEF"},
    ) is False


def test_share_link_signature_service_rejects_revoked_key_id() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )

    assert is_share_link_revoked_v1(
        signed,
        revoked_key_ids={"k1"},
    ) is True
    assert verify_share_link_signature_v1(
        signed,
        keyring={"k1": "share-secret-01"},
        revoked_key_ids={"k1"},
    ) is False


def test_share_link_signature_service_rejects_revoked_share_by_store() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )
    store = InMemoryRevocationStore()
    store.revoke_share_id("sh_0123456789abcdefABCDEF")

    assert is_share_link_revoked_v1(signed, revocation_store=store) is True
    assert verify_share_link_signature_v1(
        signed,
        keyring={"k1": "share-secret-01"},
        revocation_store=store,
    ) is False


def test_share_link_signature_service_store_unrevoke_restores_signature_validation() -> None:
    envelope = _envelope_payload()
    signed = attach_share_link_signature_v1(
        envelope,
        secret="share-secret-01",
        key_id="k1",
    )
    store = InMemoryRevocationStore()
    store.revoke_key_id("k1")
    assert verify_share_link_signature_v1(
        signed,
        keyring={"k1": "share-secret-01"},
        revocation_store=store,
    ) is False

    store.unrevoke_key_id("k1")
    assert verify_share_link_signature_v1(
        signed,
        keyring={"k1": "share-secret-01"},
        revocation_store=store,
    ) is True


def test_share_link_signature_service_supports_key_rotation_window() -> None:
    envelope = _envelope_payload()
    signing_keys = [
        ShareSigningKey(key_id="k_legacy", secret="legacy-secret-01", can_sign=False, can_verify=True),
        ShareSigningKey(key_id="k_active", secret="active-secret-01", can_sign=True, can_verify=True),
    ]
    signed = attach_share_link_signature_with_rotation_v1(
        envelope,
        signing_keys=signing_keys,
    )

    keyring = build_share_verification_keyring_v1(signing_keys)

    assert signed["signature"]["key_id"] == "k_active"
    assert verify_share_link_signature_v1(signed, keyring=keyring) is True
