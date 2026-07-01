from __future__ import annotations

import json
import logging
import re

from agnostic.interface.prompts import INTERFACE_INTENT_TRANSLATOR_SYSTEM_PROMPT
from agnostic.planner import (
    validate_action_payload,
    validate_and_convert_intent,
    _available_units_from_session_or_context,
)

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)


class EmptyLLMResponseError(ValueError):
    """Raised when the LLM returns no parseable content."""


def _parse_intent_json(raw_content: str) -> dict[str, object]:
    stripped = str(raw_content or "").strip()
    if not stripped:
        raise EmptyLLMResponseError("LLM response content is empty")
    fence_match = _JSON_FENCE_RE.match(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def _validate_and_convert_intent(session, parsed: dict, user_text: str = "") -> dict[str, object]:
    """Valida a saída da LLM e converte para ação do sistema."""
    planner = getattr(session, "_planner", None)
    if planner is not None:
        return planner.validate_and_convert_intent(session, parsed, user_text=user_text)
    return validate_and_convert_intent(session, parsed, user_text=user_text)


def _validate_action_payload(session, action_payload: dict) -> dict | None:
    """Valida se a ação é segura e possível."""
    return validate_action_payload(session, action_payload)


def interpret_user_reply_with_interface_context(session, user_text: str, *, llm) -> dict[str, object]:
    """Traduz intenção do usuário usando LLM minimalista."""

    prompt = {
        "available_units": _available_units_from_session_or_context(session),
        "presented_options": [
            {"option_id": o.get("option_id"), "index": o.get("index"), "label": o.get("label")}
            for o in session.rendered_presented_options()
            if o.get("kind") == "executable"
        ],
        "has_pending_action": session.pending_action_snapshot() is not None,
        "pending_action": session.pending_action_snapshot(),
        "last_interface_message": session.last_interface_message(),
        "user_message": user_text,
    }

    try:
        response = llm.send(
            json.dumps(prompt, ensure_ascii=False),
            system_prompt=INTERFACE_INTENT_TRANSLATOR_SYSTEM_PROMPT,
            response_format={"type": "json_object"},
        )
        parsed = _parse_intent_json(response.content)
    except Exception as exc:
        logger.warning("Intent translation failed: %s", exc)
        return {
            "kind": "clarify",
            "response": "Não consegui interpretar. Pode reformular?",
            "reason": f"parse_error:{exc.__class__.__name__}",
        }

    return _validate_and_convert_intent(session, parsed, user_text=user_text)
