from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
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
        [(1, "Alice"), (2, "Bob"), (3, "Carol"), (4, "Dave"), (5, "Eve")],
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


def test_get_session_structure(client: TestClient, session_id: str) -> None:
    response = client.get(f"/sessions/{session_id}/structure")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert len(payload["units"]) == 1

    unit = payload["units"][0]
    assert unit["unit_name"] == "customers"
    assert unit["row_count"] == 5
    assert unit["column_count"] == 2

    columns = {column["name"]: column for column in unit["columns"]}
    assert columns["id"]["cardinality"] == 5
    assert columns["id"]["null_ratio"] == 0.0
    assert columns["id"]["unique_ratio"] == 1.0


def test_analyze_unit_full(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/sessions/{session_id}/analyze_unit_full",
        json={"unit_name": "customers"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_name"] == "customers"
    assert payload["row_count"] == 5
    assert "id" in payload["columns"]
    assert "name" in payload["columns"]

    id_column = payload["columns"]["id"]
    assert id_column["signal"] == 1.0
    assert id_column["layer1_metrics"]["cardinality"] == 5
    assert id_column["layer2_metrics"]["numeric_ratio"] == 1.0
    assert id_column["structural_pattern"]["pattern_id"] == "integer"
    assert len(id_column["heuristics"]) > 0
    assert len(payload["ranked_units"]) == 2


def test_analyze_vertical_full(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/sessions/{session_id}/analyze_vertical_full",
        json={"unit_name": "customers", "key": "id"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit_name"] == "customers"
    assert payload["column"] == "id"
    assert payload["column_name"] == "id"
    assert payload["layer1_metrics"]["cardinality"] == 5
    assert payload["structural_pattern"]["pattern_id"] == "integer"


def test_analyze_unit_full_unknown_unit(client: TestClient, session_id: str) -> None:
    response = client.post(
        f"/sessions/{session_id}/analyze_unit_full",
        json={"unit_name": "missing"},
    )

    assert response.status_code == 404


def test_core_service_from_connection() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE items (value INTEGER)")
    connection.execute("INSERT INTO items VALUES (10), (20), (30)")
    connection.commit()

    source = SQLiteDataSource.from_connection(connection, ":memory:")
    service = CoreService.from_source(source)
    payload = service.analyze_unit_full("items")

    assert payload["unit_name"] == "items"
    assert payload["columns"]["value"]["layer1_metrics"]["cardinality"] == 3
