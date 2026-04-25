from __future__ import annotations

from datetime import datetime, UTC
from datetime import timedelta
from hashlib import sha256
import json
from typing import Any
from typing import Literal

from agnostic.application.policies import generate_share_id_v1
from agnostic.application.policies import validate_share_id_format


ShareScope = Literal["private", "unlisted"]
ALLOWED_SHARE_SCOPES: frozenset[str] = frozenset({"private", "unlisted"})
DEFAULT_SHARE_TTL_SECONDS = 7 * 24 * 60 * 60


def _normalize_timestamp(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    normalized = parsed.astimezone(UTC).isoformat()
    return normalized.replace("+00:00", "Z")


def _normalize_envelope_expiration(value: datetime | str) -> str:
    if isinstance(value, datetime):
        candidate = value.isoformat()
    else:
        candidate = value
    normalized = _normalize_timestamp(candidate)
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("expires_at deve incluir timezone explícito.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonicalize_state_value(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for child_key, child_value in value.items():
            if child_value is None:
                continue
            normalized[child_key] = _canonicalize_state_value(child_value, key=child_key)
        return normalized
    if isinstance(value, list):
        return [_canonicalize_state_value(item, key=key) for item in value]
    if isinstance(value, str) and key == "generated_at":
        return _normalize_timestamp(value)
    return value


def canonicalize_share_state_v1(state: dict[str, Any]) -> dict[str, Any]:
    return _canonicalize_state_value(state)


def compute_share_state_hash_v1(state: dict[str, Any]) -> str:
    canonical_state_data = canonicalize_share_state_v1(state)
    canonical_state = json.dumps(
        canonical_state_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_state.encode("utf-8")).hexdigest()


def build_share_link_envelope_v1(
    *,
    share_id: str | None = None,
    state: dict[str, Any],
    scope: ShareScope = "unlisted",
    expires_at: datetime | str | None = None,
) -> dict[str, Any]:
    normalized_share_id = (share_id or "").strip() or generate_share_id_v1()
    validate_share_id_format(normalized_share_id)
    if scope not in ALLOWED_SHARE_SCOPES:
        raise ValueError(f"Escopo de compartilhamento inválido: {scope}")
    if state.get("schema_version") != "share-state.v1":
        raise ValueError("Envelope exige state com schema_version=share-state.v1.")
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(seconds=DEFAULT_SHARE_TTL_SECONDS)
    normalized_expires_at = _normalize_envelope_expiration(expires_at)

    return {
        "format_version": "agnostic-share.v1",
        "share_id": normalized_share_id,
        "scope": scope,
        "expires_at": normalized_expires_at,
        "state_hash": compute_share_state_hash_v1(state),
        "state": state,
    }
