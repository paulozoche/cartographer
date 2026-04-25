from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def length_range(column_data: Iterable[Any]) -> dict[str, int]:
    strings = [str(value) for value in column_data if value is not None and str(value) != ""]
    if not strings:
        return {"min": 0, "max": 0}

    lengths = [len(value) for value in strings]
    return {"min": min(lengths), "max": max(lengths)}
