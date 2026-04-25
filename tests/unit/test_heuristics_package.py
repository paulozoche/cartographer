from __future__ import annotations

from agnostic.domain.heuristics.apply import apply_column_heuristics
from agnostic.domain.heuristics.base import HeuristicResult
from agnostic.domain.heuristics.high_cardinality_signal import high_cardinality_signal
from agnostic.domain.heuristics.identifier_signal import identifier_signal
from agnostic.domain.heuristics.near_unique_conflict import near_unique_conflict
from agnostic.domain.heuristics.pattern_signal import pattern_signal
from agnostic.domain.heuristics.sequential_signal import sequential_signal


def test_heuristic_result_contract() -> None:
    result = HeuristicResult(
        name="test_signal",
        triggered=True,
        score=0.75,
        evidence={"metric": 1},
        metadata={"note": "ok"},
    )

    assert result.name == "test_signal"
    assert result.triggered is True
    assert result.score == 0.75
    assert result.evidence == {"metric": 1}
    assert result.metadata == {"note": "ok"}


def test_apply_column_heuristics_returns_empty_list_when_registry_is_empty() -> None:
    results = apply_column_heuristics(
        {
            "cardinality": 95,
            "unique_ratio": 0.95,
            "average_length": 12.0,
            "null_ratio": 0.0,
            "numeric_ratio": 1.0,
            "is_sequential": {
                "is_strictly_sequential": True,
                "is_monotonic_increasing": True,
                "numeric_coverage": 1.0,
                "increment": 1,
            },
            "has_pattern": {
                "matched_pattern": "uuid",
                "match_ratio": 0.95,
                "fixed_length": True,
                "fixed_length_value": 36,
            },
        }
    )
    assert {result.name for result in results} == {
        "high_cardinality_signal",
        "identifier_signal",
        "near_unique_conflict",
        "sequential_signal",
        "pattern_signal",
    }


def test_high_cardinality_signal_triggers_for_high_uniqueness_and_short_values() -> None:
    result = high_cardinality_signal(
        {
            "cardinality": 95,
            "unique_ratio": 0.95,
            "average_length": 12.0,
        }
    )

    assert result.name == "high_cardinality_signal"
    assert result.triggered is True
    assert result.score == 0.95
    assert result.evidence["short_value_bias"] is True


def test_high_cardinality_signal_does_not_trigger_for_long_values() -> None:
    result = high_cardinality_signal(
        {
            "cardinality": 95,
            "unique_ratio": 0.95,
            "average_length": 42.0,
        }
    )

    assert result.triggered is False
    assert result.score == 0.95
    assert result.evidence["short_value_bias"] is False


def test_identifier_signal_triggers_for_high_uniqueness_low_nulls_and_compact_values() -> None:
    result = identifier_signal(
        {
            "unique_ratio": 0.99,
            "null_ratio": 0.0,
            "average_length": 8.0,
            "numeric_ratio": 1.0,
        }
    )

    assert result.name == "identifier_signal"
    assert result.triggered is True
    assert result.score > 0.9


def test_sequential_signal_triggers_for_strict_sequence() -> None:
    result = sequential_signal(
        {
            "is_sequential": {
                "is_strictly_sequential": True,
                "is_monotonic_increasing": True,
                "numeric_coverage": 1.0,
                "increment": 1,
            }
        }
    )

    assert result.name == "sequential_signal"
    assert result.triggered is True
    assert result.score == 1.0


def test_pattern_signal_triggers_when_pattern_is_matched() -> None:
    result = pattern_signal(
        {
            "has_pattern": {
                "matched_pattern": "uuid",
                "match_ratio": 0.95,
                "fixed_length": True,
                "fixed_length_value": 36,
            }
        }
    )

    assert result.name == "pattern_signal"
    assert result.triggered is True
    assert result.score == 1.0


def test_near_unique_conflict_triggers_on_rare_collisions_in_almost_unique_column() -> None:
    result = near_unique_conflict(
        {
            "cardinality": 999,
            "unique_ratio": 0.999,
            "mode_frequency": {"count": 2},
        }
    )

    assert result.name == "near_unique_conflict"
    assert result.triggered is True
