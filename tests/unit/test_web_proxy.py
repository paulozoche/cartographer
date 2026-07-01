from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

import web


@pytest.fixture
def client() -> TestClient:
    return TestClient(web.app)


@pytest.fixture
def mock_async_client(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock_client = AsyncMock()
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=None)
    mock_cls = MagicMock(return_value=mock_context)
    monkeypatch.setattr(web.httpx, "AsyncClient", mock_cls)
    return mock_client


def test_upload_success(mock_async_client: AsyncMock, client: TestClient) -> None:
    mock_async_client.post.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["data", "orders"]},
    )

    response = client.post(
        "/upload",
        files={"file": ("sample.csv", b"id,name\n1,Alice", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "session_id": "sess-123",
        "filename": "sample.csv",
        "units": ["data", "orders"],
    }

    call_args = mock_async_client.post.call_args
    assert call_args.args[0] == f"{web.CORE_API_URL}/sessions"
    assert "file" in call_args.kwargs["files"]


def test_upload_core_api_error(mock_async_client: AsyncMock, client: TestClient) -> None:
    mock_async_client.post.return_value = httpx.Response(
        400,
        json={"detail": "Formato de arquivo inválido"},
    )

    response = client.post(
        "/upload",
        files={"file": ("bad.bin", b"not-a-dataset", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Formato de arquivo inválido"


def test_chat_success(mock_async_client: AsyncMock, client: TestClient) -> None:
    web.sessions.clear()
    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["data", "orders"]},
    )
    mock_async_client.post.return_value = httpx.Response(
        200,
        json={"response": "Análise concluída.", "session_id": "sess-123"},
    )

    response = client.post(
        "/chat",
        json={"session_id": "sess-123", "message": "analise a tabela data"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "response": "Análise concluída.",
        "session_id": "sess-123",
    }

    call_args = mock_async_client.post.call_args
    assert call_args.args[0] == web.WINDMILL_WEBHOOK_URL
    assert call_args.kwargs["json"]["session_id"] == "sess-123"
    assert call_args.kwargs["json"]["message"] == "analise a tabela data"
    assert call_args.kwargs["json"]["history"] == [
        {"role": "user", "content": "analise a tabela data"},
    ]


def test_chat_confirmation_without_pending(mock_async_client: AsyncMock, client: TestClient) -> None:
    web.sessions.clear()
    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["data", "orders"]},
    )

    response = client.post(
        "/chat",
        json={"session_id": "sess-123", "message": "sim"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "response": "Não há ação pendente.",
        "session_id": "sess-123",
    }
    mock_async_client.post.assert_not_called()


def test_chat_confirmation_executes_pending_action(mock_async_client: AsyncMock, client: TestClient) -> None:
    web.sessions.clear()
    session = web._get_session("sess-123")
    session["pending_action"] = {"action": "analyze_unit", "unit_name": "data"}

    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["data", "orders"]},
    )
    mock_async_client.post.return_value = httpx.Response(
        200,
        json={"response": "Análise concluída.", "session_id": "sess-123"},
    )

    response = client.post(
        "/chat",
        json={"session_id": "sess-123", "message": "sim"},
    )

    assert response.status_code == 200
    payload = mock_async_client.post.call_args.kwargs["json"]
    assert payload["pending_action"] == {"action": "analyze_unit", "unit_name": "data"}
    assert payload["last_action"] is None
    assert session["pending_action"] is None
    assert session["last_action"] == {"action": "analyze_unit", "unit_name": "data"}
    assert session["history"] == [
        {"role": "user", "content": "sim"},
        {"role": "assistant", "content": "Análise concluída."},
    ]


def test_chat_windmill_unavailable(mock_async_client: AsyncMock, client: TestClient) -> None:
    web.sessions.clear()
    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["data", "orders"]},
    )
    mock_async_client.post.side_effect = httpx.ConnectError("Connection refused")

    response = client.post(
        "/chat",
        json={"session_id": "sess-123", "message": "oi"},
    )

    assert response.status_code == 502
    assert "Windmill indisponível" in response.json()["detail"]


def test_chat_requires_session_id(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={"session_id": "", "message": "analise a tabela data"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "session_id obrigatório."


def test_index_is_not_cached(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"


def test_assist_success(mock_async_client: AsyncMock, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web, "DEEPSEEK_API_KEY", "test-key")

    def _post_side_effect(url: str, **kwargs):
        if url.endswith("/units"):
            return httpx.Response(
                200,
                json={
                    "session_id": "sess-123",
                    "units": ["crime_scene_report", "person"],
                },
            )
        if url.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "suggestion": "Qual unidade analisar primeiro?",
                                        "options": ["crime_scene_report", "person"],
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected POST URL: {url}")

    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["crime_scene_report", "person"]},
    )
    mock_async_client.post.side_effect = _post_side_effect

    response = client.post(
        "/assist",
        json={
            "session_id": "sess-123",
            "message": "quero encontrar o criminoso",
            "context": {"units": ["crime_scene_report", "person"]},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "suggestion": "Qual unidade analisar primeiro?",
        "options": ["crime_scene_report", "person"],
        "session_id": "sess-123",
    }
    assert web._get_session("sess-123")["pending_action"] is None


def test_assist_sets_pending_action_for_single_option(
    mock_async_client: AsyncMock,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web.sessions.clear()
    monkeypatch.setattr(web, "DEEPSEEK_API_KEY", "test-key")

    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["crime_scene_report"]},
    )
    mock_async_client.post.return_value = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "suggestion": "Deseja analisá-la?",
                                "options": ["crime_scene_report"],
                            }
                        )
                    }
                }
            ]
        },
    )

    response = client.post(
        "/assist",
        json={
            "session_id": "sess-123",
            "message": "quero investigar",
            "context": {"units": ["crime_scene_report"]},
        },
    )

    assert response.status_code == 200
    assert web._get_session("sess-123")["pending_action"] == {
        "action": "analyze_unit",
        "unit_name": "crime_scene_report",
    }


def test_assist_session_not_found(mock_async_client: AsyncMock, client: TestClient) -> None:
    mock_async_client.get.return_value = httpx.Response(
        404,
        json={"detail": "Sessão não encontrada: missing"},
    )

    response = client.post(
        "/assist",
        json={
            "session_id": "missing",
            "message": "quero ajuda",
            "context": {"units": []},
        },
    )

    assert response.status_code == 404
    assert "Sessão não encontrada" in response.json()["detail"]


def test_assist_fallback_without_api_key(
    mock_async_client: AsyncMock,
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web, "DEEPSEEK_API_KEY", "")

    mock_async_client.get.return_value = httpx.Response(
        200,
        json={"session_id": "sess-123", "units": ["crime_scene_report", "person"]},
    )

    response = client.post(
        "/assist",
        json={
            "session_id": "sess-123",
            "message": "quero encontrar o criminoso",
            "context": {"units": ["crime_scene_report", "person"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "sess-123"
    assert payload["options"] == ["crime_scene_report", "person"]
    assert "2 unidades" in payload["suggestion"]


def test_assist_requires_session_id(client: TestClient) -> None:
    response = client.post(
        "/assist",
        json={"session_id": "", "message": "quero ajuda", "context": {"units": []}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "session_id obrigatório."
