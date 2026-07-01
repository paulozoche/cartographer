from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agnostic.domain.metrics.alpha_ratio import alpha_ratio
from agnostic.domain.metrics.numeric_ratio import numeric_ratio
from agnostic.domain.models.tabular import MetricExecutionPolicy

_BOOLEAN_VALUES = frozenset(
    {"y", "n", "yes", "no", "1", "0", "true", "false", "sim", "nao"}
)
_DATE_PATTERN_SPECS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("datetime_iso", r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")),
    ("date_iso", r"^\d{4}-\d{2}-\d{2}$", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("date_br", r"^\d{2}/\d{2}/\d{4}$", re.compile(r"^\d{2}/\d{2}/\d{4}$")),
    ("date_us", r"^\d{1,2}/\d{1,2}/\d{4}$", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")),
    ("date_yyyymmdd", r"^\d{8}$", re.compile(r"^\d{8}$")),
)


@dataclass(frozen=True, slots=True)
class StructuralPattern:
    pattern_id: str
    regex: str
    confidence: float
    raw_type_hint: str
    sample: str


def detect_structural_pattern(
    column_data: Iterable[Any],
    policy: MetricExecutionPolicy | None = None,
) -> StructuralPattern:
    values = _sample_values(column_data, policy)
    non_null = [value for value in values if value is not None]
    if not non_null:
        return StructuralPattern(
            pattern_id="unknown",
            regex=".*",
            confidence=0.0,
            raw_type_hint="mixed",
            sample="",
        )

    detectors = (
        _detect_datetime_pattern,
        _detect_integer_pattern,
        _detect_decimal_pattern,
        _detect_boolean_pattern,
        _detect_id_padded_pattern,
        _detect_text_pattern,
    )
    for detector in detectors:
        pattern = detector(non_null)
        if pattern is not None and pattern.confidence >= 0.8:
            return pattern

    return _detect_unknown_pattern(non_null)


def _sample_values(
    column_data: Iterable[Any],
    policy: MetricExecutionPolicy | None,
) -> tuple[Any, ...]:
    values = tuple(column_data)
    policy = policy or MetricExecutionPolicy()
    if policy.mode == "full":
        return values
    if policy.mode != "sampled":
        raise ValueError(f"Unsupported metric execution mode: {policy.mode}")
    if policy.sampling_strategy != "deterministic_head":
        raise ValueError(f"Unsupported sampling strategy: {policy.sampling_strategy}")
    if policy.sample_size is None or policy.sample_size <= 0:
        raise ValueError("sample_size must be a positive integer in sampled mode")
    if policy.sample_size >= len(values):
        return values
    return values[: policy.sample_size]


def _detect_datetime_pattern(values: list[Any]) -> StructuralPattern | None:
    try:
        from dateutil import parser as date_parser
    except ImportError:
        return None

    parsed: list[tuple[str, Any]] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        try:
            parsed.append((text, date_parser.parse(text, dayfirst=False)))
        except (ValueError, TypeError, OverflowError):
            return None

    if not parsed:
        return None

    texts = [item[0] for item in parsed]
    parse_ratio = len(parsed) / len(values)
    if parse_ratio < 0.8:
        return None

    compact_matches = sum(1 for text in texts if _DATE_PATTERN_SPECS[-1][2].match(text))
    if compact_matches / len(texts) >= 0.8:
        sample = texts[0]
        return StructuralPattern(
            pattern_id="date_yyyymmdd",
            regex=_DATE_PATTERN_SPECS[-1][1],
            confidence=compact_matches / len(texts),
            raw_type_hint="text",
            sample=sample,
        )

    with_separators = sum(1 for text in texts if _has_date_separators(text))
    if with_separators / len(texts) < 0.8:
        return None

    pattern_id, regex = _dominant_date_format(texts)
    return StructuralPattern(
        pattern_id=pattern_id,
        regex=regex,
        confidence=with_separators / len(texts),
        raw_type_hint="text",
        sample=texts[0],
    )


def _has_date_separators(text: str) -> bool:
    return bool(re.search(r"[-/T\s]", text))


def _dominant_date_format(texts: list[str]) -> tuple[str, str]:
    counts: dict[str, int] = {}
    regex_by_id: dict[str, str] = {}
    for text in texts:
        for pattern_id, regex, compiled in _DATE_PATTERN_SPECS[:-1]:
            if compiled.match(text):
                counts[pattern_id] = counts.get(pattern_id, 0) + 1
                regex_by_id[pattern_id] = regex
                break
    if not counts:
        return "date_iso", _DATE_PATTERN_SPECS[1][1]
    pattern_id = max(counts, key=counts.get)
    return pattern_id, regex_by_id.get(pattern_id, _DATE_PATTERN_SPECS[1][1])


def _detect_integer_pattern(values: list[Any]) -> StructuralPattern | None:
    if numeric_ratio(values) < 1.0:
        return None
    integer_like = 0
    for value in values:
        text = str(value).strip()
        if not text or "." in text:
            continue
        if text.isdigit() and len(text) > 1 and text[0] == "0":
            continue
        try:
            numeric = float(text)
        except (ValueError, TypeError):
            return None
        if numeric.is_integer():
            integer_like += 1
    confidence = integer_like / len(values)
    if confidence < 0.8:
        return None
    sample = str(values[0]).strip()
    raw_hint = "integer" if all(isinstance(value, int) and not isinstance(value, bool) for value in values) else "text"
    return StructuralPattern(
        pattern_id="integer",
        regex=r"^-?\d+$",
        confidence=confidence,
        raw_type_hint=raw_hint,
        sample=sample,
    )


def _detect_decimal_pattern(values: list[Any]) -> StructuralPattern | None:
    if numeric_ratio(values) < 0.9:
        return None
    decimal_like = 0
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if isinstance(value, float) or "." in text:
            decimal_like += 1
            continue
        try:
            numeric = float(text)
        except (ValueError, TypeError):
            continue
        if numeric != int(numeric):
            decimal_like += 1
    confidence = decimal_like / len(values)
    if confidence < 0.8:
        return None
    return StructuralPattern(
        pattern_id="decimal",
        regex=r"^-?\d+(\.\d+)?$",
        confidence=confidence,
        raw_type_hint="float" if any(isinstance(value, float) for value in values) else "text",
        sample=str(values[0]).strip(),
    )


def _detect_boolean_pattern(values: list[Any]) -> StructuralPattern | None:
    matches = 0
    for value in values:
        token = str(value).strip().lower()
        if token in _BOOLEAN_VALUES:
            matches += 1
    confidence = matches / len(values)
    if confidence < 0.8:
        return None
    return StructuralPattern(
        pattern_id="boolean",
        regex=r"^(?i)(y|n|yes|no|1|0|true|false|sim|nao)$",
        confidence=confidence,
        raw_type_hint="text",
        sample=str(values[0]).strip(),
    )


def _detect_id_padded_pattern(values: list[Any]) -> StructuralPattern | None:
    padded = 0
    for value in values:
        text = str(value).strip()
        if not text.isdigit() or len(text) < 2 or text[0] != "0":
            continue
        try:
            int(text)
        except ValueError:
            continue
        padded += 1
    confidence = padded / len(values)
    if confidence < 0.8:
        return None
    return StructuralPattern(
        pattern_id="id_padded",
        regex=r"^0\d+$",
        confidence=confidence,
        raw_type_hint="text",
        sample=str(values[0]).strip(),
    )


def _detect_text_pattern(values: list[Any]) -> StructuralPattern | None:
    confidence = alpha_ratio(values)
    if confidence < 0.8:
        return None
    sample = str(values[0]).strip()
    return StructuralPattern(
        pattern_id="text",
        regex=r"^[A-Za-z]+$",
        confidence=confidence,
        raw_type_hint="text",
        sample=sample,
    )


def _detect_unknown_pattern(values: list[Any]) -> StructuralPattern:
    sample = str(values[0]).strip()
    return StructuralPattern(
        pattern_id="unknown",
        regex=".*",
        confidence=0.0,
        raw_type_hint="mixed",
        sample=sample,
    )
