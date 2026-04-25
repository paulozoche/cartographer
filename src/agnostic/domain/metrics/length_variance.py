from __future__ import annotations

import statistics
from collections.abc import Iterable
from typing import Any


def length_variance(column_data: Iterable[Any]) -> float:
    lengths = [len(str(value)) for value in column_data if value is not None]
    if len(lengths) < 2:
        return 0.0
    return statistics.variance(lengths)
