from __future__ import annotations

from pathlib import Path

import pytest

from agnostic.domain.analysis.apply_layer2_metrics import apply_layer2_metrics
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
def test_layer2_metrics_run_on_blind_inputs(source_name: str, source: object) -> None:
    units = source.list_units()
    assert units, source_name

    for unit in units:
        structure = unit.get_structure()
        standardized = standardize_tabular_unit(
            unit_name=unit.unit_name,
            structure=structure,
            rows=unit.get_rows(),
        )
        metrics = apply_layer2_metrics(standardized)

        assert set(metrics.keys()) == set(standardized.column_order)

        for column_name, column_metrics in metrics.items():
            assert column_name in standardized.columns
            assert "numeric_ratio" in column_metrics
            assert "alpha_ratio" in column_metrics
            assert "spaces_ratio" in column_metrics
            assert "uppercase_ratio" in column_metrics
