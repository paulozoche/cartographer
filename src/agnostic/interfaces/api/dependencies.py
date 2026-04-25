from __future__ import annotations

from datetime import datetime, UTC
from functools import lru_cache
from typing import Any

from fastapi import HTTPException
from fastapi import status
from agnostic.application import verify_share_link_signature_v1
from agnostic.application.ports.revocation_store import RevocationStore
from agnostic.config import load_app_config
from agnostic.infrastructure.ai.grok_client import build_ai_client_from_env
from agnostic.infrastructure.storage.revocation_store import InMemoryRevocationStore
from agnostic.infrastructure.storage.revocation_store_redis import RedisRevocationStore
from agnostic.interfaces.api.schemas import ShareLinkEnvelopeResponse


def get_ai_client():
    return build_ai_client_from_env()


@lru_cache(maxsize=1)
def _build_revocation_store() -> RevocationStore:
    config = load_app_config().revocation
    if config.backend == "redis":
        if not config.redis_url:
            raise RuntimeError("AGNOSTIC_REDIS_URL é obrigatório quando AGNOSTIC_REVOCATION_STORE=redis.")
        return RedisRevocationStore.from_url(config.redis_url)
    return InMemoryRevocationStore()


def get_revocation_store() -> RevocationStore:
    return _build_revocation_store()


def verify_share_envelope_for_read(
    envelope_payload: dict[str, Any],
    *,
    keyring: dict[str, str],
    revocation_store: RevocationStore | None = None,
    allow_private_scope: bool = False,
) -> ShareLinkEnvelopeResponse:
    envelope = ShareLinkEnvelopeResponse.model_validate(envelope_payload)
    store = revocation_store or get_revocation_store()
    verification_payload = envelope.model_dump(mode="json")
    if not verify_share_link_signature_v1(
        verification_payload,
        keyring=keyring,
        revocation_store=store,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Link compartilhável inválido ou revogado.",
        )
    if envelope.scope == "private" and not allow_private_scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Link compartilhável privado exige contexto autorizado.",
        )
    expires_at = envelope.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if datetime.now(UTC) >= expires_at.astimezone(UTC):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Link compartilhável expirado.",
        )
    return envelope
