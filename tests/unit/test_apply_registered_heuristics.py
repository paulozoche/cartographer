from __future__ import annotations

from agnostic.domain.analysis.apply_registered_heuristics import apply_registered_heuristics
from agnostic.domain.models.tabular import StandardizedTabularUnit


def test_apply_registered_heuristics_returns_results_per_column() -> None:
    unit = StandardizedTabularUnit(
        unit_name="events",
        columns={
            "event_id": (1, 2, 3, 4),
            "token": ("A1", "B2", "C3", "D4"),
        },
        row_count=4,
        column_count=2,
        column_order=("event_id", "token"),
    )

    results = apply_registered_heuristics(unit)

    assert set(results.keys()) == {"event_id", "token"}
    signals: list[float] = []
    for column_name in results:
        payload = results[column_name]
        assert payload["type"] == "column"
        assert payload["name"] == column_name
        assert 0.0 <= float(payload["exploration_score"]) <= 1.0
        assert float(payload["consistency_score"]) >= 0.0
        assert isinstance(payload["explanation"], str)
        assert isinstance(payload["suggested_actions"], list)
        assert isinstance(payload["heuristics"], list)
        assert float(payload["signal"]) >= 0.0
        signals.append(float(payload["signal"]))
    assert signals == sorted(signals, reverse=True)
