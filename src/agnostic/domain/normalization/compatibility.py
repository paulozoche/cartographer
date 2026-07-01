from __future__ import annotations

from dataclasses import dataclass

from agnostic.domain.normalization.structural_pattern import StructuralPattern

_DATE_PREFIX = "date_"
_DATETIME_PREFIX = "datetime_"


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatible: bool
    confidence: float
    normalization_strategy: str | None
    warning: str | None


def check_compatibility(
    pattern_a: StructuralPattern,
    pattern_b: StructuralPattern,
) -> CompatibilityResult:
    id_a = pattern_a.pattern_id
    id_b = pattern_b.pattern_id

    if id_a == id_b:
        return CompatibilityResult(
            compatible=True,
            confidence=min(pattern_a.confidence, pattern_b.confidence),
            normalization_strategy=None,
            warning=None,
        )

    if _is_date_like(id_a) and _is_date_like(id_b):
        return _compatible_with_warning(
            pattern_a,
            pattern_b,
            normalization_strategy="date_to_yyyymmdd",
        )

    if {id_a, id_b} == {"integer", "id_padded"}:
        return _compatible_with_warning(
            pattern_a,
            pattern_b,
            normalization_strategy="integer_strip_zeros",
        )

    if id_a == "boolean" and id_b == "boolean":
        return CompatibilityResult(
            compatible=True,
            confidence=min(pattern_a.confidence, pattern_b.confidence),
            normalization_strategy="boolean_to_01",
            warning=None,
        )

    if _is_date_like(id_a) and id_b == "integer" and not _is_date_like(id_b):
        return _incompatible(pattern_a, pattern_b)
    if _is_date_like(id_b) and id_a == "integer" and not _is_date_like(id_a):
        return _incompatible(pattern_a, pattern_b)

    if (id_a == "text" and id_b == "integer") or (id_a == "integer" and id_b == "text"):
        return _incompatible(pattern_a, pattern_b)

    return CompatibilityResult(
        compatible=False,
        confidence=0.0,
        normalization_strategy=None,
        warning=None,
    )


def _is_date_like(pattern_id: str) -> bool:
    return pattern_id.startswith(_DATE_PREFIX) or pattern_id.startswith(_DATETIME_PREFIX)


def _compatible_with_warning(
    pattern_a: StructuralPattern,
    pattern_b: StructuralPattern,
    *,
    normalization_strategy: str,
) -> CompatibilityResult:
    warning = None
    if pattern_a.raw_type_hint != pattern_b.raw_type_hint:
        warning = "tipos de dado diferentes — normalização aplicada"
    return CompatibilityResult(
        compatible=True,
        confidence=min(pattern_a.confidence, pattern_b.confidence),
        normalization_strategy=normalization_strategy,
        warning=warning,
    )


def _incompatible(
    pattern_a: StructuralPattern,
    pattern_b: StructuralPattern,
) -> CompatibilityResult:
    return CompatibilityResult(
        compatible=False,
        confidence=0.0,
        normalization_strategy=None,
        warning=None,
    )
