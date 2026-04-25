from __future__ import annotations

from pathlib import Path

import pytest

from agnostic.domain.analysis.apply_registered_heuristics import apply_registered_heuristics
from agnostic.domain.analysis.standardize import standardize_tabular_unit
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.infrastructure.storage.csv_source import CSVDataSource
from agnostic.infrastructure.storage.parquet_source import ParquetDataSource


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "blind_inputs"


def _sources() -> list[tuple[str, object]]:
    sources: list[tuple[str, object]] = []
    for path in sorted(FIXTURES_DIR.glob("blind_*.db")):
        sources.append((path.name, SQLiteDataSource(str(path))))
    for path in sorted(FIXTURES_DIR.glob("blind_*.csv")):
        sources.append((path.name, CSVDataSource(str(path))))
    for path in sorted(FIXTURES_DIR.glob("blind_*.parquet")):
        sources.append((path.name, ParquetDataSource(str(path))))
    return sources


@pytest.mark.parametrize(("source_name", "source"), _sources(), ids=lambda item: item if isinstance(item, str) else None)
def test_registered_heuristics_run_on_blind_inputs(source_name: str, source: object) -> None:
    units = source.list_units()
    assert units, source_name

    for unit in units:
        structure = unit.get_structure()
        standardized = standardize_tabular_unit(
            unit_name=unit.unit_name,
            structure=structure,
            rows=unit.get_rows(),
        )
        results = apply_registered_heuristics(standardized)

        assert set(results.keys()) == set(standardized.column_order)
        for payload in results.values():
            assert isinstance(payload, dict)
            assert 0.0 <= float(payload["exploration_score"]) <= 1.0
            assert float(payload["consistency_score"]) >= 0.0
            assert isinstance(payload["explanation"], str)
            assert isinstance(payload["suggested_actions"], list)
            assert isinstance(payload["heuristics"], list)
            assert payload["heuristics"]
            assert float(payload["signal"]) >= 0.0
