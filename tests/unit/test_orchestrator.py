from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
import types

from agnostic.application.planning.planning_context import PlanningContext
from agnostic.application.planning.rule_based_planner import plan_deterministic_action


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "orchestrator.py"
SPEC = importlib.util.spec_from_file_location("orchestrator_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
orchestrator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = orchestrator
sys.modules["orchestrator"] = orchestrator
SPEC.loader.exec_module(orchestrator)

WEB_SPEC = importlib.util.spec_from_file_location("web_module", ROOT / "web.py")
assert WEB_SPEC is not None and WEB_SPEC.loader is not None
web = importlib.util.module_from_spec(WEB_SPEC)
sys.modules[WEB_SPEC.name] = web
WEB_SPEC.loader.exec_module(web)


def _build_session_with_units(unit_columns: dict[str, list[str]]):
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": unit_name,
                "get_structure": lambda self, columns=columns: type(
                    "Structure",
                    (),
                    {
                        "columns": tuple(
                            type("Column", (), {"name": column, "position": index, "raw_type": "TEXT", "raw_attributes": ""})()
                            for index, column in enumerate(columns)
                        )
                    },
                )(),
            },
        )()
        for unit_name, columns in unit_columns.items()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo recente",
                unit=next(iter(unit_columns.keys())),
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
            )
        ]
    )
    session._execution_log = []
    return session


def test_parse_orchestrator_json_accepts_tables_action() -> None:
    assert orchestrator.parse_orchestrator_json('{"action":"tables"}') == {"action": "tables"}


def test_parse_orchestrator_json_accepts_analyze_unit_action() -> None:
    assert orchestrator.parse_orchestrator_json('{"action":"analyze_unit","unit_name":"events"}') == {
        "action": "analyze_unit",
        "unit_name": "events",
    }


def test_parse_orchestrator_json_accepts_analyze_vertical_action() -> None:
    assert orchestrator.parse_orchestrator_json(
        '{"action":"analyze_vertical","unit_name":"events","depth":"layer1"}'
    ) == {
        "action": "analyze_vertical",
        "unit_name": "events",
        "depth": "layer1",
    }


def test_parse_orchestrator_json_accepts_analyze_horizontal_action() -> None:
    assert orchestrator.parse_orchestrator_json(
        '{"action":"analyze_horizontal","unit_a":"events","unit_b":"users"}'
    ) == {
        "action": "analyze_horizontal",
        "unit_a": "events",
        "unit_b": "users",
    }


def test_parse_orchestrator_json_accepts_recall_action() -> None:
    assert orchestrator.parse_orchestrator_json('{"action":"recall","key":"unit:events"}') == {
        "action": "recall",
        "key": "unit:events",
    }


def test_parse_orchestrator_json_accepts_schema_action() -> None:
    payload = orchestrator.parse_orchestrator_json('{"action":"schema","table":"events"}')
    assert payload == {"action": "schema", "table": "events"}


def test_parse_orchestrator_json_accepts_catalog_query_action() -> None:
    payload = orchestrator.parse_orchestrator_json('{"action":"query","query_id":"generic_query_id"}')
    assert payload == {"action": "query", "query_id": "generic_query_id"}


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


def test_query_catalog_is_empty() -> None:
    assert orchestrator.QUERY_CATALOG == {}


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
    assert '"analysis_intent": "unknown"' in prompt


def test_build_interface_prompt_includes_detected_analysis_intent() -> None:
    prompt = orchestrator.build_interface_prompt(
        source_path="/tmp/sample.db",
        source_type="sqlite",
        history=[],
        user_text="quero entender essa tabela",
        result_context="resultado",
        structural_context="contexto completo",
        is_first_call=False,
    )
    assert '"analysis_intent": "vertical"' in prompt


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
        query_catalog=["generic_query_id"],
        attempt_number=1,
    )
    assert '"is_first_call": false' in prompt
    assert '"structural_context": "events: 10 linhas"' in prompt
    assert "contexto completo" not in prompt
    assert '"query_catalog": [' in prompt
    assert '"analytic_templates": [' in prompt
    assert '"analysis_intent": "unknown"' in prompt
    assert '"knowledge_graph_context": ""' in prompt
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
        query_catalog=["generic_query_id"],
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
    session._core_cache = {}

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
    assert session._core_cache["unit:events"] == first


def test_execute_action_analyze_unit_returns_summary(monkeypatch) -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "events",
                "get_structure": lambda self=None: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "event_id", "raw_type": "INTEGER"})(),
                            type("Column", (), {"name": "category", "raw_type": "TEXT"})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.source_type = "sqlite"
    session.explored_paths = ["events"]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._core_cache = {}
    session._execution_log = []

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
    assert payload["action"] == "analyze_unit"
    assert payload["cache_key"] == "unit:events"
    assert "operational_summary" in payload
    assert "evidence" in payload
    assert payload["next_requirements"]
    assert len(session.knowledge_graph.nodes) == 1
    assert session.knowledge_graph.nodes[0].unit == "events"


def test_execute_action_analyze_vertical_returns_operational_context(monkeypatch) -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "events",
                "get_structure": lambda self=None: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "event_id", "raw_type": "INTEGER"})(),
                            type("Column", (), {"name": "category", "raw_type": "TEXT"})(),
                            type("Column", (), {"name": "created_at", "raw_type": "TEXT"})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.source_type = "sqlite"
    session.analysis_by_unit = {}
    session.explored_paths = []
    session._core_cache = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()

    analysis = type(
        "Analysis",
        (),
        {
            "unit_name": "events",
            "standardized": type("Standardized", (), {"row_count": 3, "column_order": ("id",)})(),
            "columns": {
                "id": type(
                    "Column",
                    (),
                    {
                        "layer1_metrics": {"null_ratio": 0.0},
                        "layer2_metrics": {"entropy": 1.0},
                        "heuristics": ({"name": "identifier"},),
                    },
                )()
            },
        },
    )()

    session.analyze_unit_on_demand = lambda unit_name: analysis
    payload = orchestrator.json.loads(
        session.execute_action({"action": "analyze_vertical", "unit_name": "events", "depth": "layer1"})
    )
    assert payload["action"] == "analyze_vertical"
    assert payload["status"] == "cached"
    assert payload["cache_key"] == "layer1:events"
    assert payload["unit_name"] == "events"
    assert payload["depth"] == "layer1"
    assert "operational_summary" in payload
    assert "evidence" in payload
    assert payload["next_requirements"]
    assert session._core_cache["layer1:events"]["columns"]["id"] == {"null_ratio": 0.0}
    assert session.knowledge_graph.nodes
    assert session.knowledge_graph.nodes[0].cache_key == "layer1:events"


def test_execute_action_recall_returns_cached_result() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {"unit:events": {"unit_name": "events", "signal": 0.9}}

    payload = orchestrator.json.loads(session.execute_action({"action": "recall", "key": "unit:events"}))
    assert payload["found"] is True
    assert payload["cached_result"] == {"unit_name": "events", "signal": 0.9}


def test_execute_action_recall_returns_missing_message() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}

    payload = orchestrator.json.loads(session.execute_action({"action": "recall", "key": "unit:events"}))
    assert payload["found"] is False
    assert "ainda não foi feito" in payload["message"]


def test_execute_action_analyze_horizontal_caches_cross_result() -> None:
    class Unit:
        def __init__(self, unit_name, columns, rows):
            self.unit_name = unit_name
            self._columns = columns
            self._rows = rows

        def get_structure(self):
            return type(
                "Structure",
                (),
                {"columns": tuple(type("Column", (), {"name": name})() for name in self._columns)},
            )()

        def get_rows(self):
            for row in self._rows:
                yield row

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        Unit("events", ["account_id", "city"], [(1, "Boston"), (2, "Salem")]),
        Unit("accounts", ["id", "name"], [(1, "Ana"), (2, "Bob")]),
    ]
    session._core_cache = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []

    payload = orchestrator.json.loads(
        session.execute_action(
            {"action": "analyze_horizontal", "unit_a": "events", "unit_b": "accounts"}
        )
    )
    cache_key = "cross:events:accounts"
    assert payload["cache_key"] == cache_key
    assert payload["units"] == ["events", "accounts"]
    assert payload["join_keys"] == ["events.account_id=accounts.id"]
    assert session._core_cache[cache_key]["same_name_columns"] == []
    assert payload["join_keys"]
    assert payload["next_requirements"]


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
        executed_queries=[{"query_id": "generic_query_id", "sql": "SELECT * FROM events WHERE kind = 'x'"}],
        query_catalog=["generic_query_id"],
        attempt_number=2,
    )
    assert '"attempt_number": 2' in prompt
    assert '"last_error": "Erro operacional: no such table"' in prompt
    assert '"last_result": "{\\"rows\\":[[1]]}"' in prompt
    assert '"executed_queries": [' in prompt
    assert "SELECT * FROM events WHERE kind = 'x'" in prompt


def test_orchestrate_system_prompt_forbids_done_on_error() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/tmp/sample.db"
    session.source_type = "sqlite"
    session.units = [type("Unit", (), {"unit_name": "events"})()]
    session.history = []
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._core_cache = {}
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
        query_catalog=["generic_query_id"],
        attempt_number=2,
    )
    assert payload == {"action": "tables"}
    assert "LEI 1 — FORMATO ABSOLUTO" in captured["system_prompt"]
    assert "LEI 2 — CATÁLOGO É EXATO, NÃO APROXIMADO" in captured["system_prompt"]
    assert "LEI 3 — SEM COBERTURA = request_new_query OBRIGATÓRIO" in captured["system_prompt"]
    assert "LEI 4 — ERRO NÃO É CONCLUSÃO" in captured["system_prompt"]
    assert "LEI 5 — CONFIRMAÇÃO CURTA NÃO ENCERRA E NÃO PARALISA" in captured["system_prompt"]
    assert 'executar a ação sugerida' in captured["system_prompt"]
    assert 'Histórico mostra Interface sugerindo: "Quer que eu explore a unidade principal?"' in captured["system_prompt"]
    assert 'Resposta CORRETA: {"action": "analyze_unit", "unit_name": "nome_da_unidade"}' in captured["system_prompt"]
    assert 'Resposta ERRADA: {"action": "tables"}' in captured["system_prompt"]
    assert 'Resposta ERRADA: {"action": "done", "conclusion": "..."}' in captured["system_prompt"]
    assert 'Se o histórico contém lista numerada de próximos passos e o usuário responde "ok", "sim", "pode", "vai":' in captured["system_prompt"]
    assert "- Execute o PRIMEIRO passo da lista" in captured["system_prompt"]
    assert 'Nunca responder com "preciso de instrução clara"' in captured["system_prompt"]
    assert "LEI 6 — NÃO REEXECUTE" in captured["system_prompt"]
    assert "execution_log contém TODAS as ações executadas com sucesso nesta sessão" in captured["system_prompt"]
    assert "Se uma unidade X já aparece em execution_log com action=analyze_unit, NÃO execute analyze_unit sobre X novamente." in captured["system_prompt"]
    assert "Se um SQL sobre tabela X já aparece em execution_log, NÃO execute SQL sobre X novamente com o mesmo filtro." in captured["system_prompt"]
    assert "Se last_result contém pistas (ex: nomes de ruas, testemunhas, IDs), execute a PRÓXIMA ação lógica baseada nessas pistas." in captured["system_prompt"]
    assert "Exemplo: se execution_log mostra analyze_unit de uma unidade e last_result revela entidades ou chaves concretas" in captured["system_prompt"]
    assert "executed_queries contém queries do turno atual" in captured["system_prompt"]


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
    assert "nunca gere blocos de código SQL na resposta" in captured["system_prompt"]
    assert "A Orquestradora é quem decide e executa o SQL" in captured["system_prompt"]
    assert "Se o resultado contiver operational_summary, evidence ou next_requirements" in captured["system_prompt"]
    assert "sugira o primeiro passo operacional útil e evite sugerir schema ou estrutura de forma redundante" in captured["system_prompt"]
    assert "Quando o resultado contém pistas concretas (nomes, endereços, IDs)" in captured["system_prompt"]
    assert 'NÃO termine com "Qual a sua instrução?" ou "Deseja que eu prepare essa busca?".' in captured["system_prompt"]


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
        last_result='{"query_id":"generic_query_id","row_count_preview":1}',
        executed_queries=[{"query_id": "generic_query_id", "sql": "SELECT * FROM events WHERE kind = 'x'"}],
        query_catalog=["generic_query_id"],
        attempt_number=3,
    )
    assert '"user_message": "sim"' in prompt
    assert 'generic_query_id' in prompt
    assert "SELECT * FROM events WHERE kind = 'x'" in prompt
    assert '"last_result": "{\\"query_id\\":\\"generic_query_id\\",\\"row_count_preview\\":1}"' in prompt
    assert '"last_result_summary": "{\\"query_id\\":\\"generic_query_id\\",\\"row_count_preview\\":1}"' in prompt


def test_plan_deterministic_action_returns_request_new_query_for_explicit_sql() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []

    payload = plan_deterministic_action(session, "SELECT * FROM person")
    assert payload == {
        "action": "request_new_query",
        "description": "consulta SQL informada pelo usuário",
        "suggested_sql": "SELECT * FROM person",
    }


def test_plan_deterministic_action_short_confirmation_consumes_pending_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "person"})()]
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo",
                unit="person",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_1",
                        "kind": "schema",
                        "units": ["person"],
                        "description": "Ver schema de person",
                        "reason": "pendente",
                        "suggested_action": {"action": "schema", "table": "person"},
                        "status": "pending",
                        "source_node_id": "node:1",
                    }
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload["action"] == "schema"
    assert payload["table"] == "person"
    assert payload["__requirement_id"] == "req_1"


def test_plan_deterministic_action_si_is_short_confirmation() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "person"})()]
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo",
                unit="person",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_1",
                        "kind": "schema",
                        "units": ["person"],
                        "description": "Ver schema de person",
                        "reason": "pendente",
                        "suggested_action": {"action": "schema", "table": "person"},
                        "status": "pending",
                        "source_node_id": "node:1",
                    }
                ],
            )
        ]
    )
    payload = plan_deterministic_action(session, "si")
    assert payload["action"] == "schema"


def test_plan_deterministic_action_tables_command() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    assert plan_deterministic_action(session, "tabelas") == {"action": "tables"}


def test_plan_deterministic_action_schema_of_person() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "person"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    assert plan_deterministic_action(session, "schema de person") == {"action": "schema", "table": "person"}


def test_plan_deterministic_action_explore_interview() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "interview"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    assert plan_deterministic_action(session, "explorar interview") == {"action": "analyze_unit", "unit_name": "interview"}


def test_plan_deterministic_action_does_not_reexecute_analyze_unit() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "interview"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = [{"action": "analyze_unit", "unit": "interview"}]
    assert plan_deterministic_action(session, "explorar interview") is None


def test_plan_deterministic_action_cross_tables() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "interview"})(), type("Unit", (), {"unit_name": "person"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    assert plan_deterministic_action(session, "cruzar interview com person") == {
        "action": "analyze_horizontal",
        "unit_a": "interview",
        "unit_b": "person",
    }


def test_plan_deterministic_action_counts_records_using_principal_context_unit() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "orders"})(), type("Unit", (), {"unit_name": "customers"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo",
                unit="orders",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
            )
        ]
    )
    session._execution_log = []
    payload = plan_deterministic_action(session, "quantos registros existem?")
    assert payload == {
        "action": "request_new_query",
        "description": "Contar registros em orders",
        "suggested_sql": 'SELECT COUNT(*) AS total FROM "orders";',
    }
    assert orchestrator.validate_select_sql_text(payload["suggested_sql"])


def test_plan_deterministic_action_counts_records_on_explicit_table_name() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "events"})(), type("Unit", (), {"unit_name": "people"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    payload = plan_deterministic_action(session, "quantas linhas existem na tabela events?")
    assert payload == {
        "action": "request_new_query",
        "description": "Contar registros em events",
        "suggested_sql": 'SELECT COUNT(*) AS total FROM "events";',
    }
    assert orchestrator.validate_select_sql_text(payload["suggested_sql"])


def test_plan_deterministic_action_counts_records_with_single_unit() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "records"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    payload = plan_deterministic_action(session, "quantas linhas tem?")
    assert payload == {
        "action": "request_new_query",
        "description": "Contar registros em records",
        "suggested_sql": 'SELECT COUNT(*) AS total FROM "records";',
    }
    assert orchestrator.validate_select_sql_text(payload["suggested_sql"])


def test_plan_deterministic_action_counts_records_with_approximate_unit_name() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "khipu_main"})(), type("Unit", (), {"unit_name": "aux"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo",
                unit="khipu_main",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
            )
        ]
    )
    session._execution_log = []
    payload = plan_deterministic_action(session, "quantos kipus existem no banco ?")
    assert payload == {
        "action": "request_new_query",
        "description": "Contar registros em khipu_main",
        "suggested_sql": 'SELECT COUNT(*) AS total FROM "khipu_main";',
    }
    assert orchestrator.validate_select_sql_text(payload["suggested_sql"])


def test_plan_deterministic_action_counts_records_returns_none_for_ambiguous_units() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "orders"})(), type("Unit", (), {"unit_name": "customers"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    assert plan_deterministic_action(session, "quantos registros existem?") is None


def test_plan_deterministic_action_groups_count_by_category_dimension() -> None:
    session = _build_session_with_units({"items": ["category", "status", "created_year"]})
    payload = plan_deterministic_action(session, "contagem por categoria")
    assert payload == {
        "action": "request_new_query",
        "description": "agrupar contagem por category em items",
        "suggested_sql": 'SELECT "category" AS value, COUNT(*) AS total FROM "items" GROUP BY "category" ORDER BY total DESC LIMIT 50',
    }
    assert ";" not in payload["suggested_sql"]
    assert orchestrator.validate_select_sql_text(payload["suggested_sql"])


def test_plan_deterministic_action_groups_count_by_status_dimension() -> None:
    session = _build_session_with_units({"items": ["category", "status", "created_year"]})
    payload = plan_deterministic_action(session, "distribuição por status")
    assert payload == {
        "action": "request_new_query",
        "description": "agrupar contagem por status em items",
        "suggested_sql": 'SELECT "status" AS value, COUNT(*) AS total FROM "items" GROUP BY "status" ORDER BY total DESC LIMIT 50',
    }
    assert ";" not in payload["suggested_sql"]


def test_plan_deterministic_action_groups_count_by_created_year_dimension() -> None:
    session = _build_session_with_units({"items": ["category", "status", "created_year"]})
    payload = plan_deterministic_action(session, "count by created year")
    assert payload == {
        "action": "request_new_query",
        "description": "agrupar contagem por created_year em items",
        "suggested_sql": 'SELECT "created_year" AS value, COUNT(*) AS total FROM "items" GROUP BY "created_year" ORDER BY total DESC LIMIT 50',
    }
    assert ";" not in payload["suggested_sql"]


def test_plan_deterministic_action_grouped_count_returns_none_for_missing_dimension() -> None:
    session = _build_session_with_units({"items": ["category", "status", "created_year"]})
    assert plan_deterministic_action(session, "count by owner") is None


def test_plan_deterministic_action_grouped_count_returns_none_for_ambiguous_dimension() -> None:
    session = _build_session_with_units({"items": ["status", "status_code", "created_year"]})
    assert plan_deterministic_action(session, "count by status") is None


def test_plan_deterministic_action_total_count_still_uses_count_star_without_group_by() -> None:
    session = _build_session_with_units({"items": ["category", "status", "created_year"]})
    payload = plan_deterministic_action(session, "quantas linhas tem?")
    assert payload == {
        "action": "request_new_query",
        "description": "Contar registros em items",
        "suggested_sql": 'SELECT COUNT(*) AS total FROM "items";',
    }
    assert "GROUP BY" not in payload["suggested_sql"]


def test_build_planning_context_preserves_expected_data() -> None:
    session = _build_session_with_units({"items": ["category", "status", "created_year"]})
    session._active_focus = {"units": ["items"], "node_id": "node:1"}
    session._last_presented_options = [{"index": 1, "text": "Aprofundar items"}]
    session._execution_log = [{"action": "analyze_unit", "unit": "items"}]
    session._core_cache = {
        "query:q1": {
            "units": ["items"],
            "columns": ["status"],
            "rows": [("open",)],
        }
    }
    context = orchestrator.build_planning_context(session)
    assert context.available_units == ["items"]
    assert context.active_focus == {"units": ["items"], "node_id": "node:1"}
    assert context.last_presented_options == [{"index": 1, "text": "Aprofundar items"}]
    assert context.execution_log == [{"action": "analyze_unit", "unit": "items"}]
    assert context.unit_columns["items"] == ["category", "status", "created_year"]
    assert any(entity["value"] == "open" for entity in context.known_entities)


def test_plan_deterministic_action_accepts_planning_context_directly() -> None:
    context = PlanningContext(
        pending_requirements=[],
        active_focus={"units": ["records"]},
        available_units=["records"],
        recent_nodes=[],
        last_presented_options=[],
        known_entities=[],
        execution_log=[],
        unit_columns={"records": ["id"]},
        text_columns_by_unit={"records": ["id"]},
        categorical_columns_by_unit={"records": ["id"]},
    )
    payload = plan_deterministic_action(context, "quantas linhas tem?")
    assert payload == {
        "action": "request_new_query",
        "description": "Contar registros em records",
        "suggested_sql": 'SELECT COUNT(*) AS total FROM "records";',
    }


def test_knowledge_graph_to_context_does_not_include_rows() -> None:
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="query:1",
                label="query",
                unit="person",
                data={"columns": ["id"], "row_count_preview": 1},
                timestamp="2026-05-27T00:00:00+00:00",
                action="query",
                cache_key="query:person_lookup",
                units=["person"],
                columns=["id"],
            )
        ]
    )
    context = graph.to_context()
    assert "rows" not in context.lower()
    assert "query:person_lookup" in context


def test_register_session_query_saves_cache_key(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE person (id INTEGER)")
        connection.execute("INSERT INTO person (id) VALUES (1)")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}

    payload = session._register_session_query(description="buscar person", suggested_sql="SELECT * FROM person")
    assert payload["cache_key"] == f"query:{payload['query_id']}"
    assert session._core_cache[payload["cache_key"]]["query_id"] == payload["query_id"]
    assert "operational_summary" in payload
    assert "evidence" in payload
    assert payload["next_requirements"]


def test_execute_action_request_new_query_returns_operational_context(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE events (id INTEGER, category TEXT)")
        connection.execute("INSERT INTO events (id, category) VALUES (1, 'a')")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()

    payload = orchestrator.json.loads(
        session.execute_action(
            {
                "action": "request_new_query",
                "description": "listar eventos",
                "suggested_sql": "SELECT id, category FROM events",
            }
        )
    )
    assert payload["action"] == "request_new_query"
    assert payload["cache_key"].startswith("query:")
    assert payload["operational_summary"]["row_count"] == 1
    assert payload["evidence"]["columns"] == ["id", "category"]
    assert payload["next_requirements"]
    assert session.knowledge_graph.nodes


def test_web_run_turn_executes_planner_action_before_interface_reply() -> None:
    events: list[tuple[str, object]] = []

    class FakeSession:
        def __init__(self) -> None:
            self.history = []
            self._cache_keys: list[str] = []
            self.knowledge_graph = orchestrator.KnowledgeGraph()

        def available_cache_keys(self):
            return list(self._cache_keys)

        def execute_action(self, action_payload):
            events.append(("execute_action", action_payload))
            self._cache_keys.append("query:q1")
            self.knowledge_graph.nodes.append(
                orchestrator.KnowledgeNode(
                    id="events:1",
                    label="query",
                    unit="events",
                    data={},
                    timestamp="2026-05-28T00:00:00+00:00",
                    action="query",
                    cache_key="query:q1",
                )
            )
            return orchestrator.json.dumps(
                {
                    "action": "request_new_query",
                    "cache_key": "query:q1",
                    "query_id": "q1",
                    "sql": "SELECT * FROM events WHERE type = 'murder' LIMIT 50",
                }
            )

        def interface_reply(self, user_text, *, result_context, is_first_call=False):
            events.append(("interface_reply", {"user_text": user_text, "result_context": result_context}))
            return "ok"

        def orchestrate(self, *args, **kwargs):
            raise AssertionError("orchestrate should not be called when planner returns action")

        def catalog_for_session(self):
            return {}

    state = web.SessionState(
        session_id="s1",
        file_path="/tmp/x.db",
        orchestrator=FakeSession(),
        structural_context="ctx",
    )

    original_planner = web.plan_deterministic_action
    try:
        web.plan_deterministic_action = lambda *args, **kwargs: {
            "action": "request_new_query",
            "description": "amostrar registros filtrados por valor",
            "suggested_sql": "SELECT * FROM events WHERE type = 'murder' LIMIT 50",
        }
        reply = web._run_turn(state, "amostra murders")
    finally:
        web.plan_deterministic_action = original_planner

    assert reply == "ok"
    assert events[0][0] == "execute_action"
    assert events[1][0] == "interface_reply"
    assert state.orchestrator.available_cache_keys() == ["query:q1"]
    assert state.orchestrator.knowledge_graph.nodes[-1].action == "query"


def test_fallback_calls_orchestrator_only_when_planner_returns_none() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    session.source_path = "/tmp/sample.db"
    session.source_type = "sqlite"
    session.history = []
    session._full_structural_context = "contexto"
    session.curated_context_for = lambda user_text, is_first_call=False: "contexto"

    called = {"count": 0}

    class FakeOrchestratorAI:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            called["count"] += 1
            return type("Response", (), {"content": '{"action":"tables"}'})()

    session.orchestrator_ai = FakeOrchestratorAI()
    assert plan_deterministic_action(session, "tabelas") == {"action": "tables"}
    assert called["count"] == 0
    payload = session.orchestrate("pergunta ambígua", "contexto", executed_queries=[], attempt_number=1)
    assert payload == {"action": "tables"}
    assert called["count"] == 1


def test_rule_based_planner_has_no_dataset_specific_rules() -> None:
    planner_source = (ROOT / "src/agnostic/application/planning/rule_based_planner.py").read_text(encoding="utf-8").lower()
    banned_fragments = [
        "sql murder mystery",
        "crime_scene_report",
        "drivers_license",
        "get_fit_now_member",
    ]
    for fragment in banned_fragments:
        assert fragment not in planner_source


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


def test_update_knowledge_graph_does_not_add_duplicate_node() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.analysis_by_unit = {}
    session.units = []

    class QuietCurator:
        def send(self, prompt: str, *, system_prompt: str | None = None):
            return type("Response", (), {"content": '{"from_id":"","relation":""}'})()

    session.curator_ai = QuietCurator()

    payload = {"unit_name": "events", "summary": "Tabela events com 10 linhas.", "metrics_summary": []}
    session.update_knowledge_graph(payload, action="analyze_unit")
    session.update_knowledge_graph(payload, action="analyze_unit")

    assert len(session.knowledge_graph.nodes) == 1


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
