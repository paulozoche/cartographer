from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "orchestrator.py"
SPEC = importlib.util.spec_from_file_location("orchestrator_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
orchestrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(orchestrator)


def test_parse_orchestrator_json_accepts_tables_action() -> None:
    assert orchestrator.parse_orchestrator_json('{"action":"tables"}') == {"action": "tables"}


def test_parse_orchestrator_json_accepts_schema_action() -> None:
    payload = orchestrator.parse_orchestrator_json('{"action":"schema","table":"events"}')
    assert payload == {"action": "schema", "table": "events"}


def test_parse_orchestrator_json_rejects_non_json() -> None:
    try:
        orchestrator.parse_orchestrator_json("nao-json")
    except ValueError as exc:
        assert "não é JSON válido" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Era esperado erro para conteúdo inválido.")


def test_validate_select_sql_accepts_simple_select() -> None:
    orchestrator.validate_select_sql("SELECT * FROM events")


def test_validate_select_sql_rejects_delete() -> None:
    try:
        orchestrator.validate_select_sql("DELETE FROM events")
    except ValueError as exc:
        assert "SELECT" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("DELETE deveria ser rejeitado.")


def test_validate_select_sql_rejects_multiple_statements() -> None:
    try:
        orchestrator.validate_select_sql("SELECT * FROM events; DROP TABLE events;")
    except ValueError as exc:
        assert "Apenas uma instrução" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Múltiplas instruções deveriam ser rejeitadas.")
