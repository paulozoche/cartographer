from __future__ import annotations

from pathlib import Path

import pytest

from agnostic.domain.analysis.standardize import standardize_tabular_unit
from agnostic.infrastructure.storage.csv_source import CSVDataSource


FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "blind_inputs"
BLIND_CSV_PATHS = sorted(FIXTURES_DIR.glob("blind_*.csv"))


@pytest.mark.parametrize("csv_path", BLIND_CSV_PATHS, ids=lambda path: path.name)
def test_blind_csv_inputs_support_source_contract_and_standardization(csv_path: Path) -> None:
    source = CSVDataSource(str(csv_path))

    metadata = source.get_metadata()
    units = source.list_units()

    assert metadata.source_type == "csv"
    assert metadata.display_name == csv_path.name
    assert metadata.source_identifier == str(csv_path)
    assert metadata.fingerprint is not None
    assert metadata.fingerprint.startswith("sha256:")
    assert metadata.unit_count == len(units) == 1

    unit = units[0]
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

    for values in standardized.columns.values():
        assert isinstance(values, tuple)
        assert len(values) == standardized.row_count
