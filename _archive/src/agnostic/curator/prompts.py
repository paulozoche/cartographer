from __future__ import annotations

import json


def build_curator_prompt(
    *,
    user_message: str,
    available_units: list[str],
    full_context: str,
) -> str:
    payload = {
        "user_message": user_message,
        "available_units": available_units,
        "full_context": full_context,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
