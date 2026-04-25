from __future__ import annotations

import unicodedata
import hashlib
from typing import Any


_SEPARATOR_CHARS = {"-", "_", "/", "\\", ".", ":", ";", "|", ","}
_ASSOCIATED_ROWS_LIMIT = 5
_TECHNICAL_ROW_KEYS = frozenset({"row_id", "row_index", "__row_id__", "__row_index__"})


def compute_value_cell_metrics(
    *,
    value: Any,
    total_rows: int | None,
    frequency: int | None,
) -> dict[str, Any]:
    is_null = value is None
    is_empty_string = isinstance(value, str) and value == ""
    text = "" if is_null else str(value)

    char_count = len(text)

    digit_count = 0
    alpha_count = 0
    uppercase_count = 0
    lowercase_count = 0
    space_count = 0
    punctuation_count = 0
    symbol_count = 0
    other_count = 0

    has_non_ascii = False
    has_separator = False
    has_diacritic = False

    for char in text:
        if ord(char) > 127:
            has_non_ascii = True
        if char in _SEPARATOR_CHARS:
            has_separator = True
        if char.isspace():
            space_count += 1
            continue
        if char.isdigit():
            digit_count += 1
            continue
        if char.isalpha():
            alpha_count += 1
            if char.isupper():
                uppercase_count += 1
            if char.islower():
                lowercase_count += 1
            decomposed = unicodedata.normalize("NFD", char)
            if any(unicodedata.category(token) == "Mn" for token in decomposed):
                has_diacritic = True
            continue
        category = unicodedata.category(char)
        if category.startswith("P"):
            punctuation_count += 1
        elif category.startswith("S"):
            symbol_count += 1
        else:
            other_count += 1

    if not has_diacritic and text:
        # Captura caracteres com marca combinante explícita.
        has_diacritic = any(unicodedata.category(char) == "Mn" for char in unicodedata.normalize("NFD", text))

    def _ratio(count: int) -> float:
        if char_count <= 0:
            return 0.0
        return count / char_count

    safe_total_rows = int(total_rows or 0)
    safe_frequency = int(frequency or 0)
    frequency_ratio = (safe_frequency / safe_total_rows) if safe_total_rows > 0 else 0.0

    return {
        "is_null": is_null,
        "is_empty_string": is_empty_string,
        "char_count": char_count,
        "digit_count": digit_count,
        "alpha_count": alpha_count,
        "uppercase_count": uppercase_count,
        "lowercase_count": lowercase_count,
        "space_count": space_count,
        "punctuation_count": punctuation_count,
        "symbol_count": symbol_count,
        "other_count": other_count,
        "digit_ratio": _ratio(digit_count),
        "alpha_ratio": _ratio(alpha_count),
        "uppercase_ratio": _ratio(uppercase_count),
        "lowercase_ratio": _ratio(lowercase_count),
        "space_ratio": _ratio(space_count),
        "punctuation_ratio": _ratio(punctuation_count),
        "symbol_ratio": _ratio(symbol_count),
        "other_ratio": _ratio(other_count),
        "has_digits": digit_count > 0,
        "has_alpha": alpha_count > 0,
        "has_space": space_count > 0,
        "has_punctuation": punctuation_count > 0,
        "has_symbol": symbol_count > 0,
        "has_non_ascii": has_non_ascii,
        "has_diacritic": has_diacritic,
        "has_separator": has_separator,
        "frequency": safe_frequency,
        "frequency_ratio": max(0.0, min(frequency_ratio, 1.0)),
    }


def _stable_value_id(value: Any) -> str:
    if value is None:
        payload = "none:"
    elif isinstance(value, str) and value == "":
        payload = "empty:"
    else:
        payload = f"value:{str(value)}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"vid_{digest[:24]}"


def _row_values_for_index(
    *,
    columns: dict[str, Any],
    column_order: list[str],
    row_index: int,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column_name in column_order:
        column_values = columns.get(column_name)
        if not isinstance(column_values, (list, tuple)):
            continue
        row[column_name] = column_values[row_index] if row_index < len(column_values) else None
    return row


def _signature_value(value: Any) -> Any:
    if isinstance(value, list):
        return ("list", tuple(_signature_value(item) for item in value))
    if isinstance(value, tuple):
        return ("tuple", tuple(_signature_value(item) for item in value))
    if isinstance(value, dict):
        return ("dict", tuple((key, _signature_value(child)) for key, child in value.items()))
    return (type(value).__name__, value)


def _observable_row_signature(row_values: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(
        (key, _signature_value(value))
        for key, value in row_values.items()
        if key not in _TECHNICAL_ROW_KEYS
    )


def build_associated_rows_payload(
    *,
    columns: dict[str, Any] | None,
    column_order: list[str] | tuple[str, ...] | None,
    selected_column: str,
    selected_value_id: str,
    display_limit: int = _ASSOCIATED_ROWS_LIMIT,
) -> dict[str, Any]:
    if not isinstance(columns, dict) or not selected_column or not selected_value_id:
        return {
            "associated_rows_total": 0,
            "associated_rows_displayed": 0,
            "associated_rows_hidden": 0,
            "associated_rows_are_identical": None,
            "associated_rows": [],
            "representative_row": None,
        }

    selected_values = columns.get(selected_column)
    if not isinstance(selected_values, (list, tuple)):
        return {
            "associated_rows_total": 0,
            "associated_rows_displayed": 0,
            "associated_rows_hidden": 0,
            "associated_rows_are_identical": None,
            "associated_rows": [],
            "representative_row": None,
        }

    ordered_columns = [str(item) for item in (column_order or []) if str(item) in columns]
    if not ordered_columns:
        ordered_columns = [str(item) for item in columns.keys()]

    matched_indexes = [
        index
        for index, value in enumerate(selected_values)
        if _stable_value_id(value) == selected_value_id
    ]
    total = len(matched_indexes)
    rows = [
        {
            "row_index": index,
            "values": _row_values_for_index(columns=columns, column_order=ordered_columns, row_index=index),
        }
        for index in matched_indexes
    ]
    signatures = {_observable_row_signature(row["values"]) for row in rows}
    are_identical = (len(signatures) == 1) if rows else None
    if total == 1 or are_identical:
        displayed_rows = rows[:1]
    else:
        displayed_rows = rows[: max(int(display_limit or 0), 0)]

    representative_row = {"values": rows[0]["values"]} if rows else None
    return {
        "associated_rows_total": total,
        "associated_rows_displayed": len(displayed_rows),
        "associated_rows_hidden": max(0, total - len(displayed_rows)),
        "associated_rows_are_identical": are_identical,
        "associated_rows": displayed_rows,
        "representative_row": representative_row,
    }


def build_value_cell_analysis_payload(
    *,
    table: str,
    column: str,
    decision: str,
    value: Any,
    total_rows: int | None,
    frequency: int | None,
    selected_value_id: str | None = None,
    standardized_columns: dict[str, Any] | None = None,
    column_order: list[str] | tuple[str, ...] | None = None,
    associated_rows_limit: int = _ASSOCIATED_ROWS_LIMIT,
) -> dict[str, Any]:
    value_id = selected_value_id or _stable_value_id(value)
    payload = {
        "type": "value",
        "table": table,
        "column": column,
        "decision": decision,
        "value": value,
        "value_id": value_id,
        "impact": {
            "count": int(frequency or 0),
            "ratio": max(0.0, min((int(frequency or 0) / int(total_rows or 1)) if int(total_rows or 0) > 0 else 0.0, 1.0)),
        },
        "metrics": compute_value_cell_metrics(
            value=value,
            total_rows=total_rows,
            frequency=frequency,
        ),
    }
    payload.update(
        build_associated_rows_payload(
            columns=standardized_columns,
            column_order=column_order,
            selected_column=column,
            selected_value_id=value_id,
            display_limit=associated_rows_limit,
        )
    )
    return payload
