"""Turn-level decision returned by the Planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class TurnDecision:
    kind: Literal["execute_pending", "clarify", "advise", "execute"]
    action_payload: Optional[dict] = None
    response: str = ""
    reason: str = ""
