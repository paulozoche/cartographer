from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def numeric_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(value for value in column_data if value is not None)
    if not values:
        return 0.0

    numeric_count = sum(1 for value in values if _is_numeric(value))
    return numeric_count / len(values)


def _is_numeric(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True

    try:
        float(str(value).strip())
        return True
    except (ValueError, TypeError):
        return False
