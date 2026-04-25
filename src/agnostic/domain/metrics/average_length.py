from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def average_length(column_data: Iterable[Any]) -> float:
    lengths = [len(str(value)) for value in column_data if value is not None]
    if not lengths:
        return 0.0
    return sum(lengths) / len(lengths)
