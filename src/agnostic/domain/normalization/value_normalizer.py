from __future__ import annotations

from typing import Any

from agnostic.domain.normalization.structural_pattern import StructuralPattern

_TRUTHY = frozenset({"y", "yes", "1", "true", "sim"})
_FALSY = frozenset({"n", "no", "0", "false", "nao"})


def normalize_value_for_comparison(value: Any, pattern: StructuralPattern) -> str | None:
    try:
        if value is None:
            return None
        pattern_id = pattern.pattern_id
        if pattern_id.startswith("date_") or pattern_id.startswith("datetime_"):
            return _normalize_date(value)
        if pattern_id == "integer":
            return _normalize_integer(value)
        if pattern_id == "decimal":
            return _normalize_decimal(value)
        if pattern_id == "boolean":
            return _normalize_boolean(value)
        if pattern_id == "id_padded":
            return _normalize_id_padded(value)
        if pattern_id == "text":
            return str(value).strip().lower()
        return str(value).strip()
    except Exception:
        return None


def _normalize_date(value: Any) -> str | None:
    try:
        from dateutil import parser as date_parser
    except ImportError:
        return None
    try:
        parsed = date_parser.parse(str(value).strip(), dayfirst=False)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed.strftime("%Y%m%d")


def _normalize_integer(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return None
    return str(int(float(text)))


def _normalize_decimal(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    return str(round(float(value), 6))


def _normalize_boolean(value: Any) -> str | None:
    if isinstance(value, bool):
        return "1" if value else "0"
    token = str(value).strip().lower()
    if token in _TRUTHY:
        return "1"
    if token in _FALSY:
        return "0"
    return None


def _normalize_id_padded(value: Any) -> str | None:
    text = str(value).strip()
    if not text.isdigit():
        return None
    return str(int(text))
