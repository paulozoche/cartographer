from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from typing import Any


def entropy(column_data: Iterable[Any]) -> float:
    non_null = tuple(value for value in column_data if value is not None)
    if not non_null:
        return 0.0

    total = len(non_null)
    counts = Counter(non_null)

    entropy_value = 0.0
    for count in counts.values():
        probability = count / total
        entropy_value -= probability * math.log2(probability)

    return entropy_value
