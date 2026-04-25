from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def cardinality(column_data: Iterable[Any]) -> int:
    """
    Número de valores distintos, ignorando None.
    """
    return len({value for value in column_data if value is not None})
