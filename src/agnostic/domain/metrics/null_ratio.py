from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def null_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(column_data)
    if not values:
        return 0.0
    return values.count(None) / len(values)
