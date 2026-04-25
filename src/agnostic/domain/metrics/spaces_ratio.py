from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def spaces_ratio(column_data: Iterable[Any]) -> float:
    values = tuple(value for value in column_data if value is not None)
    if not values:
        return 0.0

    strings = [str(value) for value in values]
    has_space = sum(1 for value in strings if " " in value)
    return has_space / len(strings)
