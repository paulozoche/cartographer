from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def unique_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(value for value in column_data if value is not None)
    if not values:
        return 0.0
    return len(set(values)) / len(values)
