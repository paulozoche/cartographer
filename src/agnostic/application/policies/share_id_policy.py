from __future__ import annotations

import re
from secrets import token_urlsafe


SHARE_ID_PREFIX = "sh_"
SHARE_ID_PATTERN = re.compile(r"^sh_[A-Za-z0-9_-]{22,64}$")


def is_valid_share_id(share_id: str) -> bool:
    return bool(SHARE_ID_PATTERN.fullmatch(share_id.strip()))


def validate_share_id_format(share_id: str) -> None:
    if not is_valid_share_id(share_id):
        raise ValueError(
            "share_id inválido. Use formato `sh_` + token imprevisível "
            "(22 a 64 caracteres com [A-Za-z0-9_-])."
        )


def generate_share_id_v1() -> str:
    while True:
        candidate = f"{SHARE_ID_PREFIX}{token_urlsafe(18)}"
        if is_valid_share_id(candidate):
            return candidate
