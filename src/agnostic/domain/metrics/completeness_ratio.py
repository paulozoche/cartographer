from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def completeness_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(column_data)
    if not values:
        return 0.0
    null_count = values.count(None)
    empty_count = sum(1 for value in values if value == "")
    absent = null_count + empty_count
    return 1.0 - absent / len(values)
