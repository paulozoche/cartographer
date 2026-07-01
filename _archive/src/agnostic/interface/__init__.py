"""Cartographer Interface — user-facing LLM layer."""

from agnostic.interface.formatter import (
    _align_reply_numbering_with_presented_options,
    _compress_interface_available_result,
    _compress_interface_result_payload,
    _compress_raw_result_for_interface_context,
    _deep_compress_frequency_counts_in_payload,
    _formatted_presented_option_lines,
    _mixed_format_warnings_from_result_context,
    _sanitize_interface_payload,
    sanitize_interface_reply,
)
from agnostic.interface.interface import Interface
from agnostic.interface.interpreter import (
    _validate_action_payload,
    _validate_and_convert_intent,
    interpret_user_reply_with_interface_context,
)
from agnostic.interface.llm import DeepSeekAPIError, DeepSeekClient
from agnostic.interface.presenter import (
    _build_structured_choice_message,
    _extract_action_marker_from_reply,
    build_unmapped_analysis_reply,
    interface_reply,
)
from agnostic.interface.prompts import (
    INTERFACE_INTENT_TRANSLATOR_SYSTEM_PROMPT,
    build_interface_interpreter_prompt,
    build_interface_prompt,
)

__all__ = [
    "DeepSeekAPIError",
    "DeepSeekClient",
    "Interface",
    "INTERFACE_INTENT_TRANSLATOR_SYSTEM_PROMPT",
    "build_interface_interpreter_prompt",
    "build_interface_prompt",
    "build_unmapped_analysis_reply",
    "interface_reply",
    "interpret_user_reply_with_interface_context",
    "sanitize_interface_reply",
]
