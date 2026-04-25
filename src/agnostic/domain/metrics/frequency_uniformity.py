from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any


def frequency_uniformity(column_data: Iterable[Any]) -> float:
    non_null = tuple(value for value in column_data if value is not None)
    if not non_null:
        return 1.0

    counts = sorted(Counter(non_null).values())
    distinct_count = len(counts)

    if distinct_count <= 1:
        return 1.0

    total = sum(counts)
    gini = 0.0
    for index, count in enumerate(counts):
        gini += (2 * index - distinct_count + 1) * count

    gini = gini / (distinct_count * total) if total > 0 else 0.0
    return 1.0 - gini
