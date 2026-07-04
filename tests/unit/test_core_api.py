from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core_api.analysis_id import AnalysisIdFields, build_analysis_id, calcular_custo, parse_analysis_id
from core_api.app import SESSIONS, app
from core_api.core_service import CoreService


@pytest.fixture
def sqlite_path() -> str:
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        path = tmp.name

    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE customers (id INTEGER, name TEXT)")
    connection.executemany(
        "INSERT INTO customers (id, name) VALUES (?, ?)",
        [(1, "Alice"), (2, "Bob"), (3, "Carol")],
    )
    connection.commit()
    connection.close()
    yield path
    Path(path).unlink(missing_ok=True)


@pytest.fixture
def session_id(sqlite_path: str) -> str:
    SESSIONS.clear()
    service = CoreService(sqlite_path)
    session_id = "938b998d-0000-4000-8000-000000000000"
    service.bind_session(session_id)
    SESSIONS[session_id] = service
    return session_id


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_build_and_parse_analysis_id_roundtrip() -> None:
    cache_key = build_analysis_id(
        AnalysisIdFields(
            namespace="cartographer",
            usuario="anonimo",
            intencao="",
            tipo="unit",
            sessao="938b998d",
            dataset_hash="a1b2c3d4",
            origem="customers",
            alvo="",
            profundidade="full",
            contexto="",
            method="full",
            importancia="normal",
            ramo="",
            acessos=0,
            custo=10.1,
            parent_id="",
            timestamp="2026-07-01T18:32:00",
        )
    )

    parsed = parse_analysis_id(cache_key)
    assert parsed.namespace == "cartographer"
    assert parsed.usuario == "anonimo"
    assert parsed.tipo == "unit"
    assert parsed.sessao == "938b998d"
    assert parsed.dataset_hash == "a1b2c3d4"
    assert parsed.origem == "customers"
    assert parsed.profundidade == "full"
    assert parsed.method == "full"
    assert parsed.importancia == "normal"
    assert parsed.acessos == 0
    assert parsed.custo == pytest.approx(10.1)
    assert parsed.timestamp == "2026-07-01T18:32:00"


def test_calcular_custo_analyze_unit() -> None:
    custo = calcular_custo("analyze_unit", linhas=100, colunas=4)
    assert custo == pytest.approx(10.0 + (100 * 0.01) + (4 * 0.5))


def test_analyze_unit_generates_structured_cache_key(
    client: TestClient,
    session_id: str,
) -> None:
    response = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    )

    assert response.status_code == 200
    payload = response.json()
    cache_key = payload["cache_key"]

    parsed = parse_analysis_id(cache_key)
    assert parsed.namespace == "cartographer"
    assert parsed.usuario == "anonimo"
    assert parsed.tipo == "unit"
    assert parsed.sessao == "938b998d"
    assert parsed.origem == "customers"
    assert parsed.method == "full"
    assert parsed.profundidade == "full"
    assert parsed.custo == pytest.approx(11.0)
    assert parsed.timestamp


def test_analyze_unit_cache_hit_preserves_cache_key(
    client: TestClient,
    session_id: str,
) -> None:
    first = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    second = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()

    assert first["cache_key"] == second["cache_key"]


def test_analyze_vertical_cache_key_fields(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/sessions/{session_id}/analyze_vertical",
        json={"unit_name": "customers", "depth": "layer1", "key": "id"},
    )

    assert response.status_code == 200
    parsed = parse_analysis_id(response.json()["cache_key"])
    assert parsed.tipo == "vertical"
    assert parsed.origem == "customers"
    assert parsed.alvo == "id"
    assert parsed.profundidade == "layer1"
    assert parsed.method == "vertical"


def test_analyze_horizontal_cache_key_fields(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/sessions/{session_id}/analyze_horizontal",
        json={"unit_a": "customers", "unit_b": "customers"},
    )

    assert response.status_code == 200
    payload = response.json()
    parsed = parse_analysis_id(payload["cache_key"])
    assert parsed.tipo == "horizontal"
    assert parsed.origem == "customers"
    assert parsed.alvo == "customers"
    assert parsed.method == "horizontal"
    assert payload["status"] == "not implemented"


def test_recall_by_generated_cache_key(client: TestClient, session_id: str) -> None:
    analyzed = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    cache_key = analyzed["cache_key"]

    recalled = client.post(
        f"/sessions/{session_id}/recall",
        json={"cache_key": cache_key},
    )

    assert recalled.status_code == 200
    assert recalled.json()["cache_key"] == cache_key


def test_parent_id_links_subsequent_analyses(client: TestClient, session_id: str) -> None:
    unit = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    vertical = client.post(
        f"/sessions/{session_id}/analyze_vertical",
        json={"unit_name": "customers", "depth": "full", "key": "id"},
    ).json()

    assert parse_analysis_id(vertical["cache_key"]).parent_id == unit["cache_key"].replace(":", "_")


def test_ultimo_id_tracks_last_analysis(client: TestClient, session_id: str) -> None:
    unit = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    service = SESSIONS[session_id]
    assert service._ultimo_id == unit["cache_key"]


def test_analyze_unit_skips_work_when_cache_hit(
    client: TestClient,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    original = __import__(
        "agnostic.domain.analysis.analyze_tabular_unit",
        fromlist=["analyze_tabular_unit"],
    ).analyze_tabular_unit

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "core_api.core_service.analyze_tabular_unit",
        counted,
    )

    first = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    second = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()

    assert first["cache_key"] == second["cache_key"]
    assert calls["count"] == 1


def test_analyze_unit_uses_cache_manager_with_full_id(
    client: TestClient,
    session_id: str,
) -> None:
    service = SESSIONS[session_id]
    response = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    )
    cache_key = response.json()["cache_key"]

    assert cache_key.startswith("cartographer:")
    parse_analysis_id(cache_key)

    cached = service.cache_manager.get(session_id, cache_key)
    assert cached is not None
    assert cached["cache_key"] == cache_key


def test_recall_uses_cache_manager(client: TestClient, session_id: str) -> None:
    service = SESSIONS[session_id]
    analyzed = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    cache_key = analyzed["cache_key"]

    service.cache_manager.delete(session_id, cache_key)
    with pytest.raises(KeyError):
        service.recall(cache_key)


def test_analyze_vertical_reuses_unit_cache_without_db(
    client: TestClient,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    original = __import__(
        "agnostic.domain.analysis.analyze_tabular_unit",
        fromlist=["analyze_tabular_unit"],
    ).analyze_tabular_unit

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "core_api.core_service.analyze_tabular_unit",
        counted,
    )

    service = SESSIONS[session_id]
    client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    )
    assert calls["count"] == 1

    service._analysis_by_unit.clear()

    response = client.post(
        f"/sessions/{session_id}/analyze_vertical",
        json={"unit_name": "customers", "depth": "layer1", "key": "id"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reused_unit_cache"] is True
    assert payload["column"] == "id"
    assert calls["count"] == 1


def test_analyze_horizontal_reuses_unit_cache(
    client: TestClient,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}
    original = __import__(
        "agnostic.domain.analysis.analyze_tabular_unit",
        fromlist=["analyze_tabular_unit"],
    ).analyze_tabular_unit

    def counted(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "core_api.core_service.analyze_tabular_unit",
        counted,
    )

    service = SESSIONS[session_id]
    client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    )
    service._analysis_by_unit.clear()

    response = client.post(
        f"/sessions/{session_id}/analyze_horizontal",
        json={"unit_a": "customers", "unit_b": "customers"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reused_unit_cache"] is True
    assert calls["count"] == 1


def test_analyze_vertical_preserves_parent_id_from_unit_cache(
    client: TestClient,
    session_id: str,
) -> None:
    unit = client.post(
        f"/sessions/{session_id}/analyze_unit",
        json={"unit_name": "customers"},
    ).json()
    SESSIONS[session_id]._analysis_by_unit.clear()
    vertical = client.post(
        f"/sessions/{session_id}/analyze_vertical",
        json={"unit_name": "customers", "depth": "full", "key": "name"},
    ).json()

    assert vertical["reused_unit_cache"] is True
    assert parse_analysis_id(vertical["cache_key"]).parent_id == unit["cache_key"].replace(":", "_")

