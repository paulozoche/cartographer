from __future__ import annotations

from pathlib import Path

import pytest

from agnostic.domain.analysis.standardize import standardize_tabular_unit
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "blind_inputs"
BLIND_SQLITE_PATHS = sorted(FIXTURES_DIR.glob("blind_*.db"))


@pytest.mark.parametrize("db_path", BLIND_SQLITE_PATHS, ids=lambda path: path.name)
def test_blind_sqlite_inputs_support_source_contract_and_standardization(db_path: Path) -> None:
    source = SQLiteDataSource(str(db_path))

    metadata = source.get_metadata()
    units = source.list_units()

    assert metadata.source_type == "sqlite"
    assert metadata.display_name == db_path.name
    assert metadata.source_identifier == str(db_path)
    assert metadata.fingerprint is not None
    assert metadata.fingerprint.startswith("sha256:")
    assert metadata.unit_count == len(units)
    assert units

    for unit in units:
        unit_metadata = unit.get_metadata()
        structure = unit.get_structure()
        standardized = standardize_tabular_unit(
            unit_name=unit.unit_name,
            structure=structure,
            rows=unit.get_rows(),
        )

        assert unit_metadata.unit_name == unit.unit_name
        assert structure.unit_name == unit.unit_name
        assert standardized.unit_name == unit.unit_name
        assert standardized.column_count == len(structure.columns)
        assert standardized.column_order == tuple(column.name for column in structure.columns)
        assert set(standardized.columns.keys()) == set(standardized.column_order)

        for column_name, values in standardized.columns.items():
            assert isinstance(column_name, str)
            assert isinstance(values, tuple)
            assert len(values) == standardized.row_count
