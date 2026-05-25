from __future__ import annotations

import pytest

from agnostic.sharing.policies.share_id_policy import generate_share_id_v1
from agnostic.sharing.policies.share_id_policy import is_valid_share_id
from agnostic.sharing.policies.share_id_policy import validate_share_id_format


def test_generate_share_id_v1_returns_canonical_unpredictable_id() -> None:
    share_id = generate_share_id_v1()

    assert share_id.startswith("sh_")
    assert is_valid_share_id(share_id) is True


def test_validate_share_id_format_accepts_valid_id() -> None:
    validate_share_id_format("sh_0123456789abcdefABCDEF")


def test_validate_share_id_format_rejects_short_or_noncanonical_id() -> None:
    with pytest.raises(ValueError):
        validate_share_id_format("sh_01HXYZABCD")
