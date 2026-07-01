"""AI result builder use case.

Orchestrates AI consultation workflow: client initialization, prompt execution, response formatting.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agnostic.ai.consult_ai import consult_ai
from agnostic.ai.ports.ai_orchestrator import AIResponse
from agnostic.infrastructure.ai.grok_client import build_ai_client_from_env


def build_ai_result(prompt: str, system_prompt: str | None = None) -> dict[str, Any]:
    """Execute AI consultation and return formatted response.
    
    Args:
        prompt: User prompt to send to AI
        system_prompt: Optional system context for AI behavior
        
    Returns:
        Serialized AIResponse as dict
    """
    client = build_ai_client_from_env()
    response: AIResponse = consult_ai(prompt, client, system_prompt=system_prompt)
    return asdict(response)
