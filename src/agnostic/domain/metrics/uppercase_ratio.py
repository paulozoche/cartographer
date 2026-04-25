from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def uppercase_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(value for value in column_data if value is not None)
    if not values:
        return 0.0

    uppercase_count = sum(1 for value in values if _is_uppercase(value))
    return uppercase_count / len(values)


def _is_uppercase(value: Any) -> bool:
    text = str(value).strip()
    if not text:
        return False

    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False

    return all(char.isupper() for char in letters)
