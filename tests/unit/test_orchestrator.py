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


def test_parse_orchestrator_json_accepts_catalog_query_action() -> None:
    payload = orchestrator.parse_orchestrator_json('{"action":"query","query_id":"knot_type_distribution"}')
    assert payload == {"action": "query", "query_id": "knot_type_distribution"}


def test_parse_orchestrator_json_rejects_non_json() -> None:
    try:
        orchestrator.parse_orchestrator_json("nao-json")
    except ValueError as exc:
        assert "não é JSON válido" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Era esperado erro para conteúdo inválido.")


def test_query_catalog_contains_known_query() -> None:
    assert "knot_type_distribution" in orchestrator.QUERY_CATALOG


def test_parse_orchestrator_json_rejects_unknown_query_id() -> None:
    try:
        orchestrator.parse_orchestrator_json('{"action":"query","query_id":"nao_existe"}')
    except ValueError as exc:
        assert "query_id inválido" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("query_id inválido deveria ser rejeitado.")


def test_build_interface_prompt_includes_first_call_flag() -> None:
    prompt = orchestrator.build_interface_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        history=[],
        user_text="oi",
        result_context="resultado",
        structural_context="contexto completo",
        is_first_call=True,
    )
    assert '"is_first_call": true' in prompt
    assert '"structural_context": "contexto completo"' in prompt


def test_build_orchestrator_prompt_uses_compact_context_after_first_call() -> None:
    prompt = orchestrator.build_orchestrator_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        unit_names=["events"],
        structural_context="contexto completo",
        history=[],
        user_text="listar tabelas",
        compact_structural_context="events: 10 linhas",
        is_first_call=False,
        last_error="",
        last_result="",
        executed_queries=[],
        attempt_number=1,
    )
    assert '"is_first_call": false' in prompt
    assert '"structural_context": "events: 10 linhas"' in prompt
    assert "contexto completo" not in prompt
    assert '"query_catalog": [' in prompt


def test_compress_assistant_message_limits_size() -> None:
    text = "x" * 200
    compressed = orchestrator.compress_assistant_message(text)
    assert len(compressed) == 150
    assert compressed.endswith("...")


def test_render_tables_message_uses_template() -> None:
    message = orchestrator.render_tables_message('{"source_type":"sqlite","tables":["events","users"]}')
    assert message == "Tabelas disponíveis: events, users."


def test_render_schema_message_uses_template() -> None:
    message = orchestrator.render_schema_message(
        '{"table":"events","columns":[{"name":"id","raw_type":"INTEGER"},{"name":"name","raw_type":null}]}'
    )
    assert message == "Schema de events: id (INTEGER), name."


def test_build_curator_prompt_contains_expected_contract() -> None:
    prompt = orchestrator.build_curator_prompt(
        user_message="quero ver eventos",
        available_units=["events", "users"],
        full_context="contexto completo",
    )
    assert '"user_message": "quero ver eventos"' in prompt
    assert '"available_units": [' in prompt
    assert '"full_context": "contexto completo"' in prompt


def test_parse_curator_json_accepts_valid_payload() -> None:
    payload = orchestrator.parse_curator_json(
        '{"relevant_units":["events","users"],"curated_context":"somente tabelas relevantes"}'
    )
    assert payload == {
        "relevant_units": ["events", "users"],
        "curated_context": "somente tabelas relevantes",
    }


def test_parse_curator_json_rejects_invalid_payload() -> None:
    try:
        orchestrator.parse_curator_json('{"relevant_units":"events","curated_context":""}')
    except ValueError as exc:
        assert "relevant_units" in str(exc) or "curated_context" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Payload inválido da curadora deveria ser rejeitado.")


def test_should_use_curator_only_after_first_call_and_with_more_than_three_units() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type("Unit", (), {"unit_name": "a"})(),
        type("Unit", (), {"unit_name": "b"})(),
        type("Unit", (), {"unit_name": "c"})(),
        type("Unit", (), {"unit_name": "d"})(),
    ]
    session._full_structural_context = "contexto"
    assert session.should_use_curator(is_first_call=False) is True
    assert session.should_use_curator(is_first_call=True) is False


def test_curated_context_for_falls_back_to_full_context_on_failure() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type("Unit", (), {"unit_name": "a"})(),
        type("Unit", (), {"unit_name": "b"})(),
        type("Unit", (), {"unit_name": "c"})(),
        type("Unit", (), {"unit_name": "d"})(),
    ]
    session._full_structural_context = "contexto completo"
    session._curator_cache = {}

    class FailingCurator:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            raise RuntimeError("falhou")

    session.curator_ai = FailingCurator()
    result = session.curated_context_for("pergunta", is_first_call=False)
    assert result == "contexto completo"


def test_build_orchestrator_prompt_includes_attempt_and_error_context() -> None:
    prompt = orchestrator.build_orchestrator_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        unit_names=["events"],
        structural_context="contexto completo",
        history=[],
        user_text="rode a query de novo",
        compact_structural_context="events: 10 linhas",
        is_first_call=False,
        last_error="Erro operacional: no such table",
        last_result='{"rows":[[1]]}',
        executed_queries=["knot_type_distribution"],
        attempt_number=2,
    )
    assert '"attempt_number": 2' in prompt
    assert '"last_error": "Erro operacional: no such table"' in prompt
    assert '"last_result": "{\\"rows\\":[[1]]}"' in prompt
    assert '"executed_queries": [' in prompt


def test_orchestrate_system_prompt_forbids_done_on_error() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/tmp/sample.db"
    session.source_type = "sqlite"
    session.units = [type("Unit", (), {"unit_name": "events"})()]
    session.history = []
    session._full_structural_context = "contexto"
    session.curated_context_for = lambda user_text, is_first_call=False: "events: 10 linhas"

    captured: dict[str, str] = {}

    class FakeOrchestratorAI:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            captured["system_prompt"] = system_prompt or ""
            return type("Response", (), {"content": '{"action":"tables"}'})()

    session.orchestrator_ai = FakeOrchestratorAI()
    payload = session.orchestrate(
        "listar tabelas",
        "contexto",
        last_error="Erro operacional: x",
        last_result="",
        executed_queries=[],
        attempt_number=2,
    )
    assert payload == {"action": "tables"}
    assert "Nunca emita 'done' quando o resultado ou contexto de erro contiver 'erro' ou 'error'." in captured["system_prompt"]
    assert "Nunca emita 'done' quando a mensagem do usuário for apenas uma confirmação curta" in captured["system_prompt"]
    assert "Nunca gere SQL livremente." in captured["system_prompt"]


def test_build_orchestrator_prompt_includes_last_result_and_queries() -> None:
    prompt = orchestrator.build_orchestrator_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        unit_names=["events"],
        structural_context="contexto completo",
        history=[],
        user_text="sim",
        compact_structural_context="events: 10 linhas",
        is_first_call=False,
        last_error="",
        last_result='{"query_id":"knot_type_distribution","row_count_preview":1}',
        executed_queries=["knot_type_distribution"],
        attempt_number=3,
    )
    assert '"user_message": "sim"' in prompt
    assert 'knot_type_distribution' in prompt
    assert '"last_result": "{\\"query_id\\":\\"knot_type_distribution\\",\\"row_count_preview\\":1}"' in prompt


def test_run_catalog_query_rejects_unknown_query_id() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = "/tmp/fake.db"
    try:
        session._run_catalog_query("nao_existe")
    except ValueError as exc:
        assert "Query do catálogo não encontrada" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("query_id inexistente deveria falhar.")
