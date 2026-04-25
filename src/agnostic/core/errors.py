from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BoundaryKind = Literal["row_limit_exceeded"]


@dataclass
class AnalysisBoundaryViolation(ValueError):
    kind: BoundaryKind
    detail: str

    def __str__(self) -> str:
        return self.detail
