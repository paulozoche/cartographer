from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

SliceMode = Literal["deepen", "new_base"]
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED_OPERATORS = {"=", "!=", "<>", ">", ">=", "<", "<=", "LIKE", "IN"}


@dataclass(frozen=True, slots=True)
class FilterCondition:
    column: str
    operator: str
    value: object


@dataclass(frozen=True, slots=True)
class DataContext:
    source_table: str
    filters: tuple[FilterCondition, ...] = ()
    parent_context: DataContext | None = None


def normalize_table_name(name: str) -> str:
    raw = (name or "").strip().lower()
    if raw.endswith(".csv"):
        raw = raw[:-4]
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    if not normalized:
        normalized = "table"
    if normalized[0].isdigit():
        normalized = f"t_{normalized}"
    return normalized


def create_slice(context: DataContext, new_filter: FilterCondition, mode: SliceMode) -> DataContext:
    if mode == "deepen":
        return DataContext(
            source_table=context.source_table,
            filters=context.filters + (new_filter,),
            parent_context=context,
        )
    if mode == "new_base":
        return DataContext(
            source_table=context.source_table,
            filters=(new_filter,),
            parent_context=None,
        )
    raise ValueError(f"Unsupported slice mode: {mode}")


def build_query(context: DataContext) -> tuple[str, tuple[object, ...]]:
    table = _validate_identifier(context.source_table, "source_table")
    if not context.filters:
        return f"SELECT * FROM {table}", ()

    where_parts: list[str] = []
    params: list[object] = []
    for condition in context.filters:
        column = _validate_identifier(condition.column, "filter column")
        operator = _validate_operator(condition.operator)
        if operator == "IN":
            if not isinstance(condition.value, (list, tuple)):
                raise ValueError("IN operator requires list/tuple value.")
            values = tuple(condition.value)
            if not values:
                raise ValueError("IN operator requires at least one value.")
            placeholders = ", ".join("?" for _ in values)
            where_parts.append(f"{column} IN ({placeholders})")
            params.extend(values)
            continue

        where_parts.append(f"{column} {operator} ?")
        params.append(condition.value)

    sql = f"SELECT * FROM {table} WHERE " + " AND ".join(where_parts)
    return sql, tuple(params)


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or not _SAFE_IDENTIFIER.match(normalized):
        raise ValueError(f"Invalid {field_name}: {value!r}")
    return normalized


def _validate_operator(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in _ALLOWED_OPERATORS:
        raise ValueError(f"Unsupported operator: {value!r}")
    return normalized


__all__ = [
    "SliceMode",
    "FilterCondition",
    "DataContext",
    "normalize_table_name",
    "create_slice",
    "build_query",
    "_SAFE_IDENTIFIER",
    "_ALLOWED_OPERATORS",
    "_validate_identifier",
    "_validate_operator",
]
