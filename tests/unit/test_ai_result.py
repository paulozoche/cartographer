"""Unit tests for ai_result module."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from agnostic.application.use_cases.ai_result import build_ai_result


@dataclass
class FakeAIResponse:
    """Fake AIResponse for testing."""
    content: str = "test response"
    metadata: dict = None
    
    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


def test_build_ai_result_calls_client_builder() -> None:
    """build_ai_result calls build_ai_client_from_env."""
    fake_client = MagicMock()
    fake_response = FakeAIResponse(content="hello")
    
    with patch("agnostic.application.use_cases.ai_result.build_ai_client_from_env") as mock_builder:
        with patch("agnostic.application.use_cases.ai_result.consult_ai") as mock_consult:
            mock_builder.return_value = fake_client
            mock_consult.return_value = fake_response
            
            build_ai_result("test prompt")
            
            mock_builder.assert_called_once()


def test_build_ai_result_passes_prompt_to_consult_ai() -> None:
    """build_ai_result passes prompt to consult_ai."""
    fake_client = MagicMock()
    fake_response = FakeAIResponse(content="hello")
    
    with patch("agnostic.application.use_cases.ai_result.build_ai_client_from_env") as mock_builder:
        with patch("agnostic.application.use_cases.ai_result.consult_ai") as mock_consult:
            mock_builder.return_value = fake_client
            mock_consult.return_value = fake_response
            
            build_ai_result("test prompt")
            
            mock_consult.assert_called_once_with("test prompt", fake_client, system_prompt=None)


def test_build_ai_result_passes_system_prompt() -> None:
    """build_ai_result passes system_prompt to consult_ai."""
    fake_client = MagicMock()
    fake_response = FakeAIResponse(content="hello")
    
    with patch("agnostic.application.use_cases.ai_result.build_ai_client_from_env") as mock_builder:
        with patch("agnostic.application.use_cases.ai_result.consult_ai") as mock_consult:
            mock_builder.return_value = fake_client
            mock_consult.return_value = fake_response
            
            build_ai_result("test prompt", system_prompt="be concise")
            
            mock_consult.assert_called_once_with("test prompt", fake_client, system_prompt="be concise")


def test_build_ai_result_returns_asdict_response() -> None:
    """build_ai_result returns asdict(AIResponse)."""
    fake_client = MagicMock()
    fake_response = FakeAIResponse(content="test content", metadata={"key": "value"})
    
    with patch("agnostic.application.use_cases.ai_result.build_ai_client_from_env") as mock_builder:
        with patch("agnostic.application.use_cases.ai_result.consult_ai") as mock_consult:
            mock_builder.return_value = fake_client
            mock_consult.return_value = fake_response
            
            result = build_ai_result("prompt")
            
            assert isinstance(result, dict)
            assert "content" in result
            assert result["content"] == "test content"


def test_build_ai_result_returns_dict() -> None:
    """build_ai_result returns a dict type."""
    fake_client = MagicMock()
    fake_response = FakeAIResponse(content="result")
    
    with patch("agnostic.application.use_cases.ai_result.build_ai_client_from_env") as mock_builder:
        with patch("agnostic.application.use_cases.ai_result.consult_ai") as mock_consult:
            mock_builder.return_value = fake_client
            mock_consult.return_value = fake_response
            
            result = build_ai_result("prompt")
            
            assert isinstance(result, dict)


def test_build_ai_result_does_not_require_real_env() -> None:
    """build_ai_result works without real AI provider env vars."""
    fake_client = MagicMock()
    fake_response = FakeAIResponse(content="works")
    
    with patch("agnostic.application.use_cases.ai_result.build_ai_client_from_env") as mock_builder:
        with patch("agnostic.application.use_cases.ai_result.consult_ai") as mock_consult:
            mock_builder.return_value = fake_client
            mock_consult.return_value = fake_response
            
            # No actual env vars needed
            result = build_ai_result("test")
            
            assert result is not None
            assert isinstance(result, dict)
