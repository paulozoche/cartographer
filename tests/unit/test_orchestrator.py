from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "orchestrator.py"
SPEC = importlib.util.spec_from_file_location("orchestrator_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
orchestrator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = orchestrator
SPEC.loader.exec_module(orchestrator)


def test_parse_orchestrator_json_accepts_tables_action() -> None:
    assert orchestrator.parse_orchestrator_json('{"action":"tables"}') == {"action": "tables"}


def test_parse_orchestrator_json_accepts_analyze_unit_action() -> None:
    assert orchestrator.parse_orchestrator_json('{"action":"analyze_unit","unit_name":"events"}') == {
        "action": "analyze_unit",
        "unit_name": "events",
    }


def test_parse_orchestrator_json_accepts_schema_action() -> None:
    payload = orchestrator.parse_orchestrator_json('{"action":"schema","table":"events"}')
    assert payload == {"action": "schema", "table": "events"}


def test_parse_orchestrator_json_accepts_catalog_query_action() -> None:
    payload = orchestrator.parse_orchestrator_json('{"action":"query","query_id":"knot_type_distribution"}')
    assert payload == {"action": "query", "query_id": "knot_type_distribution"}


def test_parse_orchestrator_json_accepts_template_action() -> None:
    payload = orchestrator.parse_orchestrator_json(
        '{"action":"template","template_id":"group_feature_signature","params":{"group_expr":"region","feature_expr":"type_code","from_clause":"t","where_clause":"1=1","subfeature_expr":"","subfeature_group":""}}'
    )
    assert payload == {
        "action": "template",
        "template_id": "group_feature_signature",
        "params": {
            "group_expr": "region",
            "feature_expr": "type_code",
            "from_clause": "t",
            "where_clause": "1=1",
            "subfeature_expr": "",
            "subfeature_group": "",
        },
    }


def test_parse_orchestrator_json_accepts_request_new_query_action() -> None:
    payload = orchestrator.parse_orchestrator_json(
        '{"action":"request_new_query","description":"contar eventos","suggested_sql":"SELECT 1"}'
    )
    assert payload == {
        "action": "request_new_query",
        "description": "contar eventos",
        "suggested_sql": "SELECT 1",
    }


def test_parse_orchestrator_json_rejects_non_json() -> None:
    try:
        orchestrator.parse_orchestrator_json("nao-json")
    except ValueError as exc:
        assert "não é JSON válido" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Era esperado erro para conteúdo inválido.")


def test_query_catalog_contains_known_query() -> None:
    assert "knot_type_distribution" in orchestrator.QUERY_CATALOG


def test_analytic_templates_contains_expected_templates() -> None:
    assert set(orchestrator.ANALYTIC_TEMPLATES) == {
        "group_feature_signature",
        "group_feature_signature_by_entity",
        "exclusive_feature_values_by_group",
    }


def test_parse_orchestrator_json_rejects_empty_request_new_query_fields() -> None:
    try:
        orchestrator.parse_orchestrator_json('{"action":"request_new_query","description":"","suggested_sql":""}')
    except ValueError as exc:
        assert "request_new_query" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("request_new_query inválido deveria ser rejeitado.")


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


def test_build_interface_prompt_limits_history_to_last_three_items() -> None:
    prompt = orchestrator.build_interface_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        history=[
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
            {"role": "assistant", "content": "4"},
        ],
        user_text="oi",
        result_context="resultado",
        structural_context="contexto completo",
        is_first_call=False,
    )
    payload = orchestrator.json.loads(prompt)
    assert payload["history"] == [
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
    ]


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
        query_catalog=["knot_type_distribution"],
        attempt_number=1,
    )
    assert '"is_first_call": false' in prompt
    assert '"structural_context": "events: 10 linhas"' in prompt
    assert "contexto completo" not in prompt
    assert '"query_catalog": [' in prompt
    assert '"analytic_templates": [' in prompt
    assert '"action": "analyze_unit"' in prompt


def test_build_orchestrator_prompt_limits_history_to_last_three_items() -> None:
    prompt = orchestrator.build_orchestrator_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        unit_names=["events"],
        structural_context="contexto completo",
        history=[
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": "2"},
            {"role": "user", "content": "3"},
            {"role": "assistant", "content": "4"},
        ],
        user_text="listar tabelas",
        compact_structural_context="events: 10 linhas",
        is_first_call=False,
        last_error="",
        last_result="",
        executed_queries=[],
        query_catalog=["knot_type_distribution"],
        attempt_number=1,
    )
    payload = orchestrator.json.loads(prompt)
    assert payload["history"] == [
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
        {"role": "assistant", "content": "4"},
    ]


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


def test_validate_sql_by_execution_rejects_invalid_join(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE khipu_main (KHIPU_ID TEXT, REGION TEXT)")
        connection.execute("CREATE TABLE cord (CORD_ID TEXT, KHIPU_ID TEXT)")
        connection.commit()
    try:
        orchestrator.validate_sql_by_execution(
            str(db_path),
            'SELECT * FROM khipu_main km JOIN cord c ON km.ID_INEXISTENTE = c.KHIPU_ID',
        )
    except ValueError as exc:
        assert "Query rejeitada pelo SQLite" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("JOIN inválido deveria ser rejeitado.")


def test_validate_sql_by_execution_accepts_valid_join(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE khipu_main (KHIPU_ID TEXT, REGION TEXT)")
        connection.execute("CREATE TABLE cord (CORD_ID TEXT, KHIPU_ID TEXT)")
        connection.execute("INSERT INTO khipu_main (KHIPU_ID, REGION) VALUES ('K1', 'PE')")
        connection.execute("INSERT INTO cord (CORD_ID, KHIPU_ID) VALUES ('C1', 'K1')")
        connection.commit()

    orchestrator.validate_sql_by_execution(
        str(db_path),
        "SELECT km.KHIPU_ID FROM khipu_main km JOIN cord c ON km.KHIPU_ID = c.KHIPU_ID",
    )


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


def test_build_source_overview_context_returns_metadata_only() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/tmp/sample.db"
    session.source_type = "sqlite"
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "events",
                "get_metadata": lambda self: type("Meta", (), {"row_count": 3})(),
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "id"})(), type("Column", (), {"name": "name"})())},
                )(),
            },
        )()
    ]

    context = session.build_source_overview_context()
    assert "Layer 1 — descoberta inicial" in context
    assert "Unidade events: 3 linhas; colunas: id, name." in context


def test_analyze_unit_on_demand_uses_cache(monkeypatch) -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "events"})()]
    session.analysis_by_unit = {}
    session.explored_paths = []

    calls = {"count": 0}

    monkeypatch.setattr(orchestrator, "load_app_config", lambda: type("Cfg", (), {"analysis": type("A", (), {"max_rows_per_unit": 10})()})())

    def fake_analyze(unit, max_rows=None):
        calls["count"] += 1
        return {"unit": unit.unit_name, "max_rows": max_rows}

    monkeypatch.setattr(orchestrator, "analyze_tabular_unit", fake_analyze)

    first = session.analyze_unit_on_demand("events")
    second = session.analyze_unit_on_demand("events")

    assert first == second
    assert calls["count"] == 1
    assert session.explored_paths == ["events"]


def test_execute_action_analyze_unit_returns_summary(monkeypatch) -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.explored_paths = ["events"]
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    class QuietCurator:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            return type("Response", (), {"content": '{"from_id":"","relation":""}'})()

    session.curator_ai = QuietCurator()
    session.analyze_unit_on_demand = lambda unit_name: {"unit_name": unit_name}
    monkeypatch.setattr(orchestrator, "summarize_tabular_analysis", lambda analysis: "Resumo da unidade.")
    monkeypatch.setattr(orchestrator, "summarize_unit_metrics", lambda analysis: ["3 linhas", "2 colunas"])

    payload = orchestrator.json.loads(session.execute_action({"action": "analyze_unit", "unit_name": "events"}))
    assert payload["unit_name"] == "events"
    assert payload["summary"] == "Resumo da unidade."
    assert payload["metrics_summary"] == ["3 linhas", "2 colunas"]
    assert len(session.knowledge_graph.nodes) == 1
    assert session.knowledge_graph.nodes[0].unit == "events"


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


def test_curated_context_for_uses_knowledge_graph_context_when_available() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type("Unit", (), {"unit_name": "a"})(),
        type("Unit", (), {"unit_name": "b"})(),
        type("Unit", (), {"unit_name": "c"})(),
        type("Unit", (), {"unit_name": "d"})(),
    ]
    session._full_structural_context = "contexto completo"
    session._curator_cache = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Tabela events com 10 linhas.",
                unit="events",
                data={"unit_name": "events"},
                timestamp="2026-05-26T00:00:00+00:00",
            ),
            orchestrator.KnowledgeNode(
                id="events:2",
                label="events_by_type: 3 linhas na prévia",
                unit="events",
                data={"query_id": "events_by_type"},
                timestamp="2026-05-26T00:01:00+00:00",
            ),
        ],
        edges=[
            orchestrator.KnowledgeEdge(
                from_id="events:1",
                to_id="events:2",
                relation="aprofunda",
            )
        ],
    )

    class InspectingCurator:
        def __init__(self) -> None:
            self.prompt = ""

        def send(self, prompt: str, *, system_prompt: str | None = None):
            self.prompt = prompt
            return type(
                "Response",
                (),
                {"content": '{"relevant_units":["events"],"curated_context":"contexto curado"}'},
            )()

    curator = InspectingCurator()
    session.curator_ai = curator

    result = session.curated_context_for("pergunta", is_first_call=False)

    assert result == "contexto curado"
    assert "## Grafo de Conhecimento" in curator.prompt
    assert "contexto completo" not in curator.prompt


def test_build_structural_context_flags_empty_units() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/tmp/sample.db"
    session.source_type = "sqlite"
    session.units = [type("Unit", (), {"unit_name": "events"})()]

    analysis = type(
        "Analysis",
        (),
        {
            "unit_name": "events",
            "standardized": type("Standardized", (), {"row_count": 0})(),
        },
    )()

    original_summary = orchestrator.summarize_tabular_analysis
    original_metrics = orchestrator.summarize_unit_metrics
    orchestrator.summarize_tabular_analysis = lambda _: "Unidade events: 0 linhas e 2 colunas."
    orchestrator.summarize_unit_metrics = lambda _: ["events: 0 linhas, 2 colunas."]
    try:
        context = session.build_structural_context([analysis])
    finally:
        orchestrator.summarize_tabular_analysis = original_summary
        orchestrator.summarize_unit_metrics = original_metrics

    assert "ALERTA: a unidade events está vazia (0 linhas)." in context


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
        query_catalog=["knot_type_distribution"],
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
        query_catalog=["knot_type_distribution"],
        attempt_number=2,
    )
    assert payload == {"action": "tables"}
    assert "LEI 1 — FORMATO ABSOLUTO" in captured["system_prompt"]
    assert "LEI 2 — CATÁLOGO É EXATO, NÃO APROXIMADO" in captured["system_prompt"]
    assert "LEI 3 — SEM COBERTURA = request_new_query OBRIGATÓRIO" in captured["system_prompt"]
    assert "LEI 4 — ERRO NÃO É CONCLUSÃO" in captured["system_prompt"]
    assert "LEI 5 — CONFIRMAÇÃO CURTA NÃO ENCERRA" in captured["system_prompt"]
    assert "LEI 6 — NÃO REEXECUTE" in captured["system_prompt"]


def test_interface_prompt_forbids_calculation_and_promises() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/tmp/sample.db"
    session.source_type = "sqlite"
    session.history = []
    session._full_structural_context = "contexto"
    session.curated_context_for = lambda user_text, is_first_call=False: "events: 10 linhas"

    captured: dict[str, str] = {}

    class FakeInterfaceAI:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            captured["system_prompt"] = system_prompt or ""
            return type("Response", (), {"content": "ok"})()

    session.interface_ai = FakeInterfaceAI()
    reply = session.interface_reply("me diga o percentual", result_context="sem dado", is_first_call=False)
    assert reply == "ok"
    assert "nunca calcula percentuais" in captured["system_prompt"]
    assert "não tenho esse dado, aguarde a execução" in captured["system_prompt"]
    assert "nunca promete executar algo" in captured["system_prompt"]


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
        query_catalog=["knot_type_distribution"],
        attempt_number=3,
    )
    assert '"user_message": "sim"' in prompt
    assert 'knot_type_distribution' in prompt
    assert '"last_result": "{\\"query_id\\":\\"knot_type_distribution\\",\\"row_count_preview\\":1}"' in prompt


def test_build_sql_from_template_group_feature_signature() -> None:
    sql = orchestrator.build_sql_from_template(
        "group_feature_signature",
        {
            "group_expr": "region",
            "feature_expr": "type_code",
            "from_clause": "sample_table",
            "where_clause": "1=1",
            "subfeature_expr": "",
            "subfeature_group": "",
        },
    )
    assert "SELECT" in sql
    assert "FROM sample_table" in sql
    assert "GROUP BY region, type_code" in sql


def test_build_sql_from_template_group_feature_signature_by_entity() -> None:
    sql = orchestrator.build_sql_from_template(
        "group_feature_signature_by_entity",
        {
            "group_expr": "region",
            "entity_expr": "entity_id",
            "feature_expr": "type_code",
            "from_clause": "sample_table",
            "where_clause": "1=1",
            "subfeature_expr": "",
            "subfeature_group": "",
        },
    )
    assert "entity_id AS entity_id" in sql
    assert "GROUP BY region, entity_id, type_code" in sql


def test_build_sql_from_template_exclusive_feature_values_by_group() -> None:
    sql = orchestrator.build_sql_from_template(
        "exclusive_feature_values_by_group",
        {
            "group_expr": "region",
            "feature_expr": "type_code",
            "from_clause": "sample_table",
            "where_clause": "1=1",
        },
    )
    assert "WITH clean AS" in sql
    assert "COUNT(DISTINCT group_value)" in sql


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


def test_register_session_query_accepts_valid_sql_and_executes(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE globalid (Country TEXT)")
        connection.execute("INSERT INTO globalid (Country) VALUES ('PE')")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []

    result = session._register_session_query(
        description="GlobalID por país",
        suggested_sql='SELECT "Country", COUNT(*) as total FROM globalid GROUP BY "Country"',
    )

    assert result["registered_in_session"] is True
    assert result["row_count_preview"] == 1
    assert result["query_id"] in session._session_query_catalog


def test_register_session_query_rejects_invalid_sql(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE globalid (Country TEXT)")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []

    try:
        session._register_session_query(
            description="destrutiva",
            suggested_sql="DELETE FROM globalid",
        )
    except ValueError as exc:
        assert "SELECT" in str(exc) or "não permitido" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("SQL inválido deveria ser rejeitado.")


def test_register_session_query_rejects_invalid_join_columns(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE khipu_main (KHIPU_ID TEXT, REGION TEXT)")
        connection.execute("CREATE TABLE cord (CORD_ID TEXT, KHIPU_ID TEXT)")
        connection.execute("INSERT INTO khipu_main (KHIPU_ID, REGION) VALUES ('K1', 'PE')")
        connection.execute("INSERT INTO cord (CORD_ID, KHIPU_ID) VALUES ('C1', 'K1')")
        connection.commit()

    unit_main = type(
        "Unit",
        (),
        {
            "unit_name": "khipu_main",
            "get_structure": lambda self: type(
                "Structure",
                (),
                {
                    "columns": (
                        type("Column", (), {"name": "KHIPU_ID"})(),
                        type("Column", (), {"name": "REGION"})(),
                    )
                },
            )(),
        },
    )()
    unit_cord = type(
        "Unit",
        (),
        {
            "unit_name": "cord",
            "get_structure": lambda self: type(
                "Structure",
                (),
                {
                    "columns": (
                        type("Column", (), {"name": "CORD_ID"})(),
                        type("Column", (), {"name": "KHIPU_ID"})(),
                    )
                },
            )(),
        },
    )()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session.units = [unit_main, unit_cord]
    session._session_query_catalog = {}
    session._candidate_queries = []

    try:
        session._register_session_query(
            description="join inválido",
            suggested_sql=(
                "SELECT * FROM khipu_main km "
                "JOIN cord c ON km.ID_INEXISTENTE = c.KHIPU_ID"
            ),
        )
    except ValueError as exc:
        assert "Query rejeitada pelo SQLite" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("JOIN inválido deveria ser rejeitado.")


def test_session_query_becomes_available_in_same_session(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE globalid (Type TEXT)")
        connection.execute("INSERT INTO globalid (Type) VALUES ('bone')")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []

    result = session._register_session_query(
        description="tipos globalid",
        suggested_sql='SELECT "Type", COUNT(*) as total FROM globalid GROUP BY "Type"',
    )
    rerun = session._run_catalog_query(result["query_id"])
    assert rerun["query_id"] == result["query_id"]
    assert rerun["row_count_preview"] == 1


def test_session_query_does_not_modify_fixed_catalog(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE globalid (Country TEXT)")
        connection.execute("INSERT INTO globalid (Country) VALUES ('PE')")
        connection.commit()

    original_catalog = dict(orchestrator.QUERY_CATALOG)
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []

    session._register_session_query(
        description="GlobalID por país",
        suggested_sql='SELECT "Country", COUNT(*) as total FROM globalid GROUP BY "Country"',
    )

    assert orchestrator.QUERY_CATALOG == original_catalog


def test_update_knowledge_graph_adds_edge_from_curator() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.analysis_by_unit = {}
    session.units = []

    class LinkingCurator:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            return type("Response", (), {"content": '{"from_id":"events:1","relation":"aprofunda"}'})()

    session.curator_ai = LinkingCurator()
    session.update_knowledge_graph(
        {"unit_name": "events", "summary": "Tabela events com 10 linhas.", "metrics_summary": []},
        action="analyze_unit",
    )
    session.update_knowledge_graph(
        {"query_id": "events_by_type", "sql": "SELECT * FROM events", "row_count_preview": 3, "rows": []},
        action="query",
    )

    assert len(session.knowledge_graph.nodes) == 2
    assert len(session.knowledge_graph.edges) == 1
    edge = session.knowledge_graph.edges[0]
    assert edge.from_id == "events:1"
    assert edge.relation == "aprofunda"


def test_render_knowledge_map_lists_findings_and_unexplored_units() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type("Unit", (), {"unit_name": "events"})(),
        type("Unit", (), {"unit_name": "users"})(),
    ]
    session.analysis_by_unit = {"events": {"cached": True}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Tabela events com 10 linhas.",
                unit="events",
                data={"unit_name": "events"},
                timestamp="2026-05-26T00:00:00+00:00",
            ),
            orchestrator.KnowledgeNode(
                id="events:2",
                label="events_by_type: 3 linhas na prévia",
                unit="events",
                data={"query_id": "events_by_type"},
                timestamp="2026-05-26T00:01:00+00:00",
            ),
        ],
        edges=[
            orchestrator.KnowledgeEdge(
                from_id="events:1",
                to_id="events:2",
                relation="aprofunda",
            )
        ],
    )

    rendered = session.render_knowledge_map()
    assert "## Mapa do Conhecimento" in rendered
    assert "- [events] Tabela events com 10 linhas." in rendered
    assert "-> aprofunda -> [events] events_by_type: 3 linhas na prévia" in rendered
    assert "- users: não analisado" in rendered


def test_render_knowledge_map_handles_empty_graph() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "events"})()]
    session.analysis_by_unit = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    rendered = session.render_knowledge_map()
    assert "Nenhum achado registrado ainda." in rendered
    assert "- events: não analisado" in rendered
