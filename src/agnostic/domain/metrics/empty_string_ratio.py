from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def empty_string_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(column_data)
    if not values:
        return 0.0
    empty_count = sum(1 for value in values if value == "")
    return empty_count / len(values)
