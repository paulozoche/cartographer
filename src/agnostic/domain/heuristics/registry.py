from __future__ import annotations

from agnostic.domain.heuristics.base import ColumnHeuristic
from agnostic.domain.heuristics.high_cardinality_signal import high_cardinality_signal
from agnostic.domain.heuristics.identifier_signal import identifier_signal
from agnostic.domain.heuristics.near_unique_conflict import near_unique_conflict
from agnostic.domain.heuristics.pattern_signal import pattern_signal
from agnostic.domain.heuristics.sequential_signal import sequential_signal


COLUMN_HEURISTICS: dict[str, ColumnHeuristic] = {
    "high_cardinality_signal": high_cardinality_signal,
    "identifier_signal": identifier_signal,
    "near_unique_conflict": near_unique_conflict,
    "sequential_signal": sequential_signal,
    "pattern_signal": pattern_signal,
}
