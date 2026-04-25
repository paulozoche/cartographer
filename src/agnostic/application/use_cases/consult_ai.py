from __future__ import annotations

from agnostic.application.ports.ai_orchestrator import AIOrchestrator, AIResponse


def consult_ai(
    prompt: str,
    orchestrator: AIOrchestrator,
    *,
    system_prompt: str | None = None,
) -> AIResponse:
    return orchestrator.send(prompt, system_prompt=system_prompt)
