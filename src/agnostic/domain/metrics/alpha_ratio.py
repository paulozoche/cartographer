from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def alpha_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(value for value in column_data if value is not None)
    if not values:
        return 0.0

    alpha_count = sum(1 for value in values if _is_alpha(value))
    return alpha_count / len(values)


def _is_alpha(value: Any) -> bool:
    text = str(value).strip()
    if not text:
        return False
    return text.isalpha()
