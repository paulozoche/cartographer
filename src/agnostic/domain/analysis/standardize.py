from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agnostic.core.errors import AnalysisBoundaryViolation
from agnostic.domain.models.tabular import StandardizedTabularUnit, UnitStructure


def standardize_tabular_unit(
    unit_name: str,
    structure: UnitStructure,
    rows: Iterable[tuple[Any, ...]],
    *,
    max_rows: int | None = None,
) -> StandardizedTabularUnit:
    """
    Converte estrutura + linhas em uma representação canônica coluna-orientada.

    Fronteiras de contrato:
    - não altera valores
    - não infere tipos
    - preserva ordem
    - mantém acoplamento posicional
    """
    column_order = tuple(column.name for column in structure.columns)
    column_data: dict[str, list[Any]] = {column_name: [] for column_name in column_order}

    row_count = 0
    expected_width = len(column_order)

    for row_index, row in enumerate(rows):
        if max_rows is not None and row_count >= max_rows:
            raise AnalysisBoundaryViolation(
                kind="row_limit_exceeded",
                detail=f"Unidade '{unit_name}' excedeu o limite configurado de {max_rows} linhas.",
            )
        if len(row) != expected_width:
            raise ValueError(
                f"Inconsistência na unidade '{unit_name}' na linha {row_index}: "
                f"{len(row)} valores vs {expected_width} colunas."
            )

        for index, value in enumerate(row):
            column_data[column_order[index]].append(value)

        row_count += 1

    return StandardizedTabularUnit(
        unit_name=unit_name,
        columns={name: tuple(values) for name, values in column_data.items()},
        row_count=row_count,
        column_count=expected_width,
        column_order=column_order,
    )
