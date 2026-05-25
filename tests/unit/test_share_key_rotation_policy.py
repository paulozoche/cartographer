from __future__ import annotations

import pytest

from agnostic.sharing.policies.share_key_rotation_policy import ShareSigningKey
from agnostic.sharing.policies.share_key_rotation_policy import build_verification_keyring
from agnostic.sharing.policies.share_key_rotation_policy import resolve_signing_key
from agnostic.sharing.policies.share_key_rotation_policy import validate_share_signing_keys


def test_resolve_signing_key_returns_single_active_key() -> None:
    keys = [
        ShareSigningKey(key_id="k_old", secret="legacy-secret", can_sign=False, can_verify=True),
        ShareSigningKey(key_id="k_new", secret="active-secret", can_sign=True, can_verify=True),
    ]

    selected = resolve_signing_key(keys)

    assert selected.key_id == "k_new"


def test_build_verification_keyring_includes_active_and_legacy_keys() -> None:
    keys = [
        ShareSigningKey(key_id="k_old", secret="legacy-secret", can_sign=False, can_verify=True),
        ShareSigningKey(key_id="k_new", secret="active-secret", can_sign=True, can_verify=True),
        ShareSigningKey(key_id="k_retired", secret="retired-secret", can_sign=False, can_verify=False),
    ]

    keyring = build_verification_keyring(keys)

    assert keyring == {
        "k_old": "legacy-secret",
        "k_new": "active-secret",
    }


def test_resolve_signing_key_rejects_when_multiple_signing_keys_are_active() -> None:
    keys = [
        ShareSigningKey(key_id="k_a", secret="secret-aaaa", can_sign=True, can_verify=True),
        ShareSigningKey(key_id="k_b", secret="secret-bbbb", can_sign=True, can_verify=True),
    ]

    with pytest.raises(ValueError):
        resolve_signing_key(keys)


def test_validate_share_signing_keys_rejects_duplicate_key_id() -> None:
    keys = [
        ShareSigningKey(key_id="k_dup", secret="secret-aaaa", can_sign=True, can_verify=True),
        ShareSigningKey(key_id="k_dup", secret="secret-bbbb", can_sign=False, can_verify=True),
    ]

    with pytest.raises(ValueError):
        validate_share_signing_keys(keys)
