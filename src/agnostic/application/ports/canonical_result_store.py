from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class CanonicalResultStore(Protocol):
    def save(self, kind: str, unit_name: str, payload: dict[str, Any]) -> Path: ...
