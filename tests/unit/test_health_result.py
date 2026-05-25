"""Unit tests for health_result module."""

from __future__ import annotations

import pytest

from agnostic.application.use_cases.health_result import build_health_result


def test_build_health_result_returns_ok_status() -> None:
    """Health result returns status ok."""
    result = build_health_result()
    assert result == {"status": "ok"}


def test_build_health_result_returns_dict() -> None:
    """Health result returns a dict."""
    result = build_health_result()
    assert isinstance(result, dict)


def test_build_health_result_has_status_key() -> None:
    """Health result has status key."""
    result = build_health_result()
    assert "status" in result


def test_build_health_result_status_is_string() -> None:
    """Health result status is a string."""
    result = build_health_result()
    assert isinstance(result["status"], str)


def test_build_health_result_consistent() -> None:
    """Health result is consistent across calls."""
    result1 = build_health_result()
    result2 = build_health_result()
    assert result1 == result2
