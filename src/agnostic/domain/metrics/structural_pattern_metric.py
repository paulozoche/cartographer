from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agnostic.domain.models.tabular import MetricExecutionPolicy
from agnostic.domain.normalization.structural_pattern import StructuralPattern, detect_structural_pattern


def structural_pattern_metric(
    column_data: Iterable[Any],
    policy: MetricExecutionPolicy | None = None,
) -> StructuralPattern:
    return detect_structural_pattern(column_data, policy=policy)
