from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agnostic.ai.ports.ai_orchestrator import AIOrchestrator, AIResponse


def consult_ai(
    prompt: str,
    orchestrator: AIOrchestrator,
    *,
    system_prompt: str | None = None,
) -> AIResponse:
    return orchestrator.send(prompt, system_prompt=system_prompt)


__all__ = [
    "consult_ai",
]
