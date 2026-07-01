from agnostic.domain.normalization.compatibility import CompatibilityResult, check_compatibility
from agnostic.domain.normalization.structural_pattern import StructuralPattern, detect_structural_pattern
from agnostic.domain.normalization.value_normalizer import normalize_value_for_comparison

__all__ = [
    "StructuralPattern",
    "CompatibilityResult",
    "detect_structural_pattern",
    "check_compatibility",
    "normalize_value_for_comparison",
]
