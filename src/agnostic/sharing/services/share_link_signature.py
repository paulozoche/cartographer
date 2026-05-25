from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
import hmac
import json
from typing import AbstractSet
from typing import Any

from agnostic.sharing.ports.revocation_store import RevocationStore
from agnostic.sharing.envelope.build_share_link_envelope_v1 import compute_share_state_hash_v1
from agnostic.sharing.policies.share_key_rotation_policy import ShareSigningKey
from agnostic.sharing.policies.share_key_rotation_policy import build_verification_keyring
from agnostic.sharing.policies.share_key_rotation_policy import resolve_signing_key


SIGNATURE_VERSION = "hmac-sha256.v1"


def _canonical_signing_payload_v1(envelope: dict[str, Any]) -> str:
    minimal_payload = {
        "format_version": envelope.get("format_version"),
        "share_id": envelope.get("share_id"),
        "scope": envelope.get("scope"),
        "expires_at": envelope.get("expires_at"),
        "state_hash": envelope.get("state_hash"),
    }
    return json.dumps(
        minimal_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def compute_share_link_signature_v1(envelope: dict[str, Any], secret: str) -> str:
    normalized_secret = secret.strip()
    if len(normalized_secret) < 8:
        raise ValueError("Segredo de assinatura deve ter no mínimo 8 caracteres.")
    payload = _canonical_signing_payload_v1(envelope)
    digest = hmac.new(normalized_secret.encode("utf-8"), payload.encode("utf-8"), sha256)
    return digest.hexdigest()


def attach_share_link_signature_v1(
    envelope: dict[str, Any],
    *,
    secret: str,
    key_id: str = "default",
) -> dict[str, Any]:
    normalized_key_id = key_id.strip()
    if not normalized_key_id:
        raise ValueError("key_id é obrigatório para assinatura.")
    if envelope.get("format_version") != "agnostic-share.v1":
        raise ValueError("Envelope inválido para assinatura: format_version deve ser agnostic-share.v1.")

    signed = dict(envelope)
    signed["signature"] = {
        "version": SIGNATURE_VERSION,
        "key_id": normalized_key_id,
        "value": compute_share_link_signature_v1(envelope, secret),
    }
    return signed


def attach_share_link_signature_with_rotation_v1(
    envelope: dict[str, Any],
    *,
    signing_keys: list[ShareSigningKey],
    preferred_key_id: str | None = None,
) -> dict[str, Any]:
    signing_key = resolve_signing_key(signing_keys, preferred_key_id=preferred_key_id)
    return attach_share_link_signature_v1(
        envelope,
        secret=signing_key.secret,
        key_id=signing_key.key_id,
    )


def build_share_verification_keyring_v1(signing_keys: list[ShareSigningKey]) -> dict[str, str]:
    return build_verification_keyring(signing_keys)


def verify_share_state_hash_v1(envelope: dict[str, Any]) -> bool:
    state = envelope.get("state")
    declared_hash = str(envelope.get("state_hash") or "")
    if not isinstance(state, dict) or not declared_hash:
        return False
    computed_hash = compute_share_state_hash_v1(state)
    return compare_digest(declared_hash, computed_hash)


def is_share_link_revoked_v1(
    envelope: dict[str, Any],
    *,
    revocation_store: RevocationStore | None = None,
    revoked_share_ids: AbstractSet[str] | None = None,
    revoked_key_ids: AbstractSet[str] | None = None,
) -> bool:
    share_id = str(envelope.get("share_id") or "").strip()
    if share_id and revocation_store and revocation_store.is_share_id_revoked(share_id):
        return True

    revoked_shares = revoked_share_ids or set()
    if share_id and share_id in revoked_shares:
        return True

    signature = envelope.get("signature")
    if not isinstance(signature, dict):
        return False

    key_id = str(signature.get("key_id") or "").strip()
    if key_id and revocation_store and revocation_store.is_key_id_revoked(key_id):
        return True

    revoked_keys = revoked_key_ids or set()
    return bool(key_id and key_id in revoked_keys)


def verify_share_link_signature_v1(
    envelope: dict[str, Any],
    *,
    keyring: dict[str, str],
    revocation_store: RevocationStore | None = None,
    revoked_share_ids: AbstractSet[str] | None = None,
    revoked_key_ids: AbstractSet[str] | None = None,
) -> bool:
    if is_share_link_revoked_v1(
        envelope,
        revocation_store=revocation_store,
        revoked_share_ids=revoked_share_ids,
        revoked_key_ids=revoked_key_ids,
    ):
        return False

    signature = envelope.get("signature")
    if not isinstance(signature, dict):
        return False
    if signature.get("version") != SIGNATURE_VERSION:
        return False

    key_id = str(signature.get("key_id") or "").strip()
    signature_value = str(signature.get("value") or "").strip()
    if not key_id or not signature_value:
        return False

    secret = keyring.get(key_id)
    if not secret:
        return False
    if not verify_share_state_hash_v1(envelope):
        return False

    expected = compute_share_link_signature_v1(envelope, secret)
    return compare_digest(signature_value, expected)
