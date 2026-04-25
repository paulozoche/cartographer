from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AIResponse:
    provider: str
    model: str
    content: str
    call_number: int
    remaining_calls: int
    quota_per_hour: int
    simulated: bool


class AIOrchestrator(Protocol):
    def send(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> AIResponse: ...
