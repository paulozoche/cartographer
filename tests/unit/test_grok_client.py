from __future__ import annotations

from datetime import UTC, datetime
import json
from urllib.error import HTTPError

import pytest

from agnostic.application import consult_ai
from agnostic.infrastructure.ai import (
    AIQuotaExceeded,
    GroqAPIError,
    GrokUsageLimiter,
    RealGrokClient,
    SimulatedGrokClient,
    build_ai_client_from_env,
    build_grok_client_from_env,
)


def test_simulated_grok_client_enforces_hourly_limit() -> None:
    client = SimulatedGrokClient(limiter=GrokUsageLimiter(limit_per_hour=30))
    now = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)

    last_response = None
    for index in range(30):
        last_response = client.send(f"prompt {index + 1}", now=now)

    assert last_response is not None
    assert last_response.call_number == 30
    assert last_response.remaining_calls == 0
    assert last_response.simulated is True

    with pytest.raises(AIQuotaExceeded):
        client.send("prompt 31", now=now)


def test_consult_ai_uses_orchestrator_contract() -> None:
    client = SimulatedGrokClient()
    response = consult_ai(
        "Summarize the current structural result.",
        client,
        system_prompt="You are a concise assistant.",
    )

    assert response.provider == "grok"
    assert response.simulated is True
    assert "summarize" in response.content.lower()


def test_real_grok_client_uses_openai_compatible_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self._body = body

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self._body).encode("utf-8")

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        recorded["url"] = getattr(request, "full_url")
        recorded["data"] = getattr(request, "data")
        recorded["headers"] = dict(getattr(request, "headers"))
        recorded["timeout"] = timeout
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "Structured answer from Groq.",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("agnostic.infrastructure.ai.grok_client.urllib_request.urlopen", fake_urlopen)

    client = RealGrokClient(
        api_key="test-api-key",
        model="test-model",
        base_url="https://api.groq.com/openai/v1",
        timeout_seconds=12.5,
    )
    response = client.send(
        "Summarize the current structural result.",
        system_prompt="You are a concise assistant.",
        now=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
    )

    assert response.provider == "groq"
    assert response.model == "test-model"
    assert response.simulated is False
    assert response.content == "Structured answer from Groq."
    assert response.call_number == 1
    assert response.remaining_calls == 29
    assert recorded["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert json.loads(recorded["data"].decode("utf-8")) == {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Summarize the current structural result."},
        ],
    }
    assert recorded["timeout"] == 12.5
    header_names = {name.lower(): value for name, value in recorded["headers"].items()}
    assert header_names["authorization"] == "Bearer test-api-key"
    assert header_names["content-type"] == "application/json"
    assert header_names["accept"] == "application/json"


def test_real_grok_client_surfaces_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float) -> object:
        raise HTTPError(
            url=getattr(request, "full_url"),
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("agnostic.infrastructure.ai.grok_client.urllib_request.urlopen", fake_urlopen)

    client = RealGrokClient(api_key="test-api-key")

    with pytest.raises(GroqAPIError, match="401"):
        client.send("Summarize the current structural result.")


def test_build_grok_client_from_env_uses_real_client_when_api_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGNOSTIC_AI_PROVIDER", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-api-key")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "9.5")

    client = build_grok_client_from_env()

    assert isinstance(client, RealGrokClient)
    assert client.api_key == "test-api-key"
    assert client.model == "test-model"
    assert client.base_url == "https://api.groq.com/openai/v1"
    assert client.timeout_seconds == 9.5


def test_build_grok_client_from_env_falls_back_to_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGNOSTIC_AI_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    client = build_grok_client_from_env()

    assert isinstance(client, SimulatedGrokClient)


def test_build_ai_client_from_env_can_force_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGNOSTIC_AI_PROVIDER", "simulated")
    monkeypatch.setenv("GROQ_API_KEY", "test-api-key")

    client = build_ai_client_from_env()

    assert isinstance(client, SimulatedGrokClient)


def test_build_ai_client_from_env_requires_api_key_for_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGNOSTIC_AI_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        build_ai_client_from_env()
