from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
import types

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


def test_build_interface_prompt_instructs_interface_to_avoid_redundant_schema_after_analysis() -> None:
    prompt = orchestrator.build_interface_prompt(
        source_path="/tmp/sample.csv",
        source_type="csv",
        history=[],
        user_text="sim",
        result_context='{"operational_summary":{"row_count":10,"columns":["a","b"]},"pending_requirements":[{"id":"req_query"}]}',
        structural_context='{"evidence":{"categorical_columns":["a"],"numeric_columns":["b"],"text_columns":[]}}',
        is_first_call=False,
        pending_requirements=[
            {
                "id": "req_query",
                "kind": "query",
                "role": "",
                "units": ["sample"],
                "description": "Contagem agregada por a",
                "suggested_action": {"action": "request_new_query", "description": "agregar por a", "suggested_sql": "SELECT a, COUNT(*) FROM sample GROUP BY a"},
            },
            {
                "id": "req_schema",
                "kind": "schema",
                "role": "",
                "units": ["sample"],
                "description": "Consultar schema",
                "suggested_action": {"action": "schema", "table": "sample"},
            },
        ],
    )
    payload = orchestrator.json.loads(prompt)
    assert payload["interface_rules"]["avoid_redundant_schema_after_analysis"] is True
    assert "NÃO sugira schema/estrutura/colunas como próximo passo principal" in payload["interface_rules"]["instruction"]
    assert [req["id"] for req in payload["pending_requirements"]] == ["req_query", "req_schema"]


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


def test_build_next_requirements_for_csv_returns_operational_requirements_before_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "csv"
    session.units = []
    session._find_compatible_units = lambda unit_name, columns: []
    structure = type(
        "Structure",
        (),
        {
            "columns": (
                type("Column", (), {"name": "record_id", "raw_type": "INTEGER"})(),
                type("Column", (), {"name": "status", "raw_type": "TEXT"})(),
                type("Column", (), {"name": "amount", "raw_type": "REAL"})(),
                type("Column", (), {"name": "notes", "raw_type": "TEXT"})(),
            )
        },
    )()
    analysis = type("Analysis", (), {"standardized": type("Standardized", (), {"row_count": 10})()})()

    requirements = session._build_next_requirements_for_unit(
        unit_name="manifest",
        structure=structure,
        analysis=analysis,
        cache_key="unit:manifest",
    )

    assert requirements
    assert requirements[0]["kind"] == "analyze_vertical"
    assert requirements[0]["suggested_action"]["action"] == "analyze_vertical"
    assert any(req["kind"] == "analyze_vertical" for req in requirements)
    assert any(req["id"] == "req_manifest_schema" for req in requirements)
    assert next(i for i, req in enumerate(requirements) if req["kind"] == "analyze_vertical") < next(
        i for i, req in enumerate(requirements) if req["kind"] == "schema"
    )


def test_execute_action_analyze_unit_csv_adds_operational_pending_requirements_before_schema(monkeypatch) -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "manifest",
                "get_structure": lambda self=None: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "record_id", "raw_type": "INTEGER"})(),
                            type("Column", (), {"name": "status", "raw_type": "TEXT"})(),
                            type("Column", (), {"name": "amount", "raw_type": "REAL"})(),
                            type("Column", (), {"name": "notes", "raw_type": "TEXT"})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.source_type = "csv"
    session.explored_paths = ["manifest"]
    session.analysis_by_unit = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._core_cache = {}
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
            "unit_name": "manifest",
            "structure": session.units[0].get_structure(),
            "standardized": type("Standardized", (), {"row_count": 10})(),
        },
    )()
    session.analyze_unit_on_demand = lambda unit_name: analysis
    monkeypatch.setattr(orchestrator, "summarize_tabular_analysis", lambda analysis: "Resumo da unidade.")
    monkeypatch.setattr(orchestrator, "summarize_unit_metrics", lambda analysis: ["10 linhas", "4 colunas"])

    payload = orchestrator.json.loads(session.execute_action({"action": "analyze_unit", "unit_name": "manifest"}))

    assert any(req["kind"] == "analyze_vertical" for req in payload["next_requirements"])
    pending = session.knowledge_graph.pending_requirements()
    assert pending[0]["kind"] == "analyze_vertical"
    assert any(req["kind"] == "schema" for req in pending)
    assert next(i for i, req in enumerate(pending) if req["kind"] == "analyze_vertical") < next(
        i for i, req in enumerate(pending) if req["kind"] == "schema"
    )


def test_execute_action_analyze_vertical_does_not_recreate_existing_csv_requirements(monkeypatch) -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    structure = type(
        "Structure",
        (),
        {
            "columns": (
                type("Column", (), {"name": "record_id", "raw_type": "INTEGER"})(),
                type("Column", (), {"name": "status", "raw_type": "TEXT"})(),
                type("Column", (), {"name": "amount", "raw_type": "REAL"})(),
                type("Column", (), {"name": "notes", "raw_type": "TEXT"})(),
            )
        },
    )()
    session.units = [
        type("Unit", (), {"unit_name": "manifest", "get_structure": lambda self=None: structure})()
    ]
    session.source_type = "csv"
    session.explored_paths = ["manifest"]
    session.analysis_by_unit = {}
    session._active_focus = None
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo operacional",
                unit="manifest",
                data={"evidence": {"columns": ["status", "amount", "notes"]}},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_missingness_summary",
                        "kind": "analyze_vertical",
                        "units": ["manifest"],
                        "description": "Verificar nulos, completude, cardinalidade e possíveis chaves",
                        "status": "pending",
                        "suggested_action": {"action": "analyze_vertical", "unit_name": "manifest", "depth": "heuristics"},
                    },
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_recall",
                        "kind": "recall",
                        "units": ["manifest"],
                        "description": "Recuperar detalhes operacionais já calculados para manifest",
                        "status": "pending",
                        "suggested_action": {"action": "recall", "key": "unit:manifest"},
                    },
                ],
            )
        ]
    )
    analysis = type(
        "Analysis",
        (),
        {
            "unit_name": "manifest",
            "structure": structure,
            "standardized": type("Standardized", (), {"row_count": 10, "column_order": ("record_id", "status", "amount", "notes")})(),
            "columns": {
                "record_id": type("Column", (), {"heuristics": ({"name": "identifier"},), "layer1_metrics": {}, "layer2_metrics": {}})(),
            },
        },
    )()
    session.analyze_unit_on_demand = lambda unit_name: analysis

    session.execute_action(
        {
            "action": "analyze_vertical",
            "unit_name": "manifest",
            "depth": "heuristics",
            "_source_requirement_id": "req_manifest_missingness_summary",
        }
    )

    matched = [
        req
        for node in session.knowledge_graph.nodes
        for req in node.next_requirements
        if req.get("id") == "req_manifest_missingness_summary"
    ]
    assert len(matched) == 1
    assert matched[0].get("status") == "resolved"
    pending = session.pending_requirements()
    pending_ids = [req["id"] for req in pending]
    assert "req_manifest_missingness_summary" not in pending_ids
    assert pending_ids.count("req_manifest_schema") == 1
    assert pending_ids.count("req_manifest_recall") == 1


def test_render_knowledge_map_does_not_show_same_requirement_as_resolved_and_pending() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session.analysis_by_unit = {"manifest": object()}
    session.explored_paths = ["manifest"]
    session._active_focus = None
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo",
                unit="manifest",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_missingness_summary",
                        "kind": "analyze_vertical",
                        "units": ["manifest"],
                        "description": "Verificar nulos, completude, cardinalidade e possíveis chaves",
                        "status": "resolved",
                        "suggested_action": {"action": "analyze_vertical", "unit_name": "manifest", "depth": "heuristics"},
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="manifest:2",
                label="Resumo heurístico",
                unit="manifest",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_missingness_summary",
                        "kind": "analyze_vertical",
                        "units": ["manifest"],
                        "description": "Verificar nulos, completude, cardinalidade e possíveis chaves",
                        "status": "pending",
                        "suggested_action": {"action": "analyze_vertical", "unit_name": "manifest", "depth": "heuristics"},
                    },
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                ],
            ),
        ]
    )

    pending_ids = [req["id"] for req in session.pending_requirements()]
    assert pending_ids == ["req_manifest_schema"]
    rendered = session.render_knowledge_map()
    assert rendered.count("req_manifest_missingness_summary [resolved]") == 1
    assert "req_manifest_missingness_summary [pending]" not in rendered


def test_build_next_requirements_for_csv_without_columns_falls_back_to_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "csv"
    session.units = []
    session._find_compatible_units = lambda unit_name, columns: []
    structure = type("Structure", (), {"columns": ()})()

    requirements = session._build_next_requirements_for_unit(
        unit_name="empty",
        structure=structure,
        analysis=None,
        cache_key="unit:empty",
    )

    assert [req["kind"] for req in requirements] == ["schema", "recall"]


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
    assert payload["_source_requirement_id"] == "req_1"


def test_plan_deterministic_action_short_confirmation_prefers_operational_requirement_over_redundant_schema_after_unit_analysis() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session._active_focus = None
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo operacional",
                unit="manifest",
                data={
                    "operational_summary": {"row_count": 10, "columns": ["flag", "amount", "notes"]},
                    "evidence": {
                        "columns": ["flag", "amount", "notes"],
                        "categorical_columns": ["flag"],
                        "numeric_columns": ["amount"],
                        "text_columns": ["notes"],
                    },
                },
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_query",
                        "kind": "query",
                        "units": ["manifest"],
                        "description": "Contagem agregada por flag",
                        "status": "pending",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "agregar por flag",
                            "suggested_sql": "SELECT flag, COUNT(*) AS total FROM manifest GROUP BY flag",
                        },
                    },
                    {
                        "id": "req_manifest_numeric",
                        "kind": "template",
                        "units": ["manifest"],
                        "description": "Resumo numérico de amount",
                        "status": "pending",
                        "suggested_action": {"action": "template", "template_id": "group_feature_signature", "params": {}},
                    },
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload["action"] == "request_new_query"
    assert payload["__requirement_id"] == "req_manifest_query"


def test_plan_deterministic_action_short_confirmation_prefers_csv_operational_requirement_over_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session._active_focus = None
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo operacional",
                unit="manifest",
                data={
                    "operational_summary": {"row_count": 10, "columns": ["status", "amount", "notes"]},
                    "evidence": {
                        "columns": ["status", "amount", "notes"],
                        "categorical_columns": ["status"],
                        "numeric_columns": ["amount"],
                        "text_columns": ["notes"],
                    },
                },
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_vertical_layer2",
                        "kind": "analyze_vertical",
                        "units": ["manifest"],
                        "description": "Aprofundar métricas de colunas, nulos e distribuição",
                        "status": "pending",
                        "suggested_action": {"action": "analyze_vertical", "unit_name": "manifest", "depth": "layer2"},
                    },
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload["action"] == "analyze_vertical"
    assert payload["depth"] == "layer2"
    assert payload["__requirement_id"] == "req_manifest_vertical_layer2"


def test_plan_deterministic_action_short_confirmation_prioritizes_recent_query_over_recall() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "events"})()]
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo antigo",
                unit="events",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_recall_old",
                        "kind": "recall",
                        "units": ["events"],
                        "description": "Recuperar histórico",
                        "reason": "pendente",
                        "suggested_action": {"action": "recall", "key": "unit:events"},
                        "status": "pending",
                        "source_node_id": "node:1",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="node:2",
                label="Resumo recente",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_recent_query",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Executar query recente",
                        "reason": "pendente",
                        "suggested_action": {"action": "query", "query_id": "recent_query"},
                        "status": "pending",
                        "source_node_id": "node:2",
                    },
                    {
                        "id": "req_recall_recent",
                        "kind": "recall",
                        "units": ["events"],
                        "description": "Recuperar detalhes recentes",
                        "reason": "pendente",
                        "suggested_action": {"action": "recall", "key": "unit:events"},
                        "status": "pending",
                        "source_node_id": "node:2",
                    },
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload["action"] == "query"
    assert payload["query_id"] == "recent_query"


def test_plan_deterministic_action_short_confirmation_does_not_return_tables() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "events"})()]
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo recente",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_tables",
                        "kind": "other",
                        "units": ["events"],
                        "description": "Listar tabelas",
                        "reason": "pendente",
                        "suggested_action": {"action": "tables"},
                        "status": "pending",
                        "source_node_id": "node:1",
                    }
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is None


def test_knowledge_graph_to_context_shows_resolved_and_pending_requirements() -> None:
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Resumo",
                unit="person",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_pending",
                        "kind": "query",
                        "units": ["person"],
                        "description": "Continuar",
                        "reason": "pendente",
                        "suggested_action": {"action": "query", "query_id": "q1"},
                        "status": "pending",
                        "source_node_id": "node:1",
                    },
                    {
                        "id": "req_resolved",
                        "kind": "schema",
                        "units": ["person"],
                        "description": "Schema já obtido",
                        "reason": "resolvido",
                        "suggested_action": {"action": "schema", "table": "person"},
                        "status": "resolved",
                        "source_node_id": "node:1",
                    },
                ],
            )
        ]
    )
    context = graph.to_context()
    assert "### Requisitos Resolvidos" in context
    assert "### Requisitos Pendentes" in context
    assert "req_resolved" in context
    assert "req_pending" in context


def test_execute_action_marks_source_requirement_resolved() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    class Column:
        def __init__(self, name, position):
            self.name = name
            self.position = position
            self.raw_type = "TEXT"
            self.raw_attributes = ""

    class TableStructure:
        def __init__(self):
            self.columns = [Column("person", 0)]

    class Unit:
        unit_name = "person"

        def get_structure(self):
            return TableStructure()

    session.units = [Unit()]
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
    session._execution_log = []

    session.execute_action({"action": "schema", "table": "person", "_source_requirement_id": "req_1"})
    assert any(
        req.get("id") == "req_1" and req.get("status") == "resolved"
        for node in session.knowledge_graph.nodes
        for req in node.next_requirements
    )


def test_request_new_query_categorical_distribution_generates_child_requirements(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE events (type TEXT, total INTEGER)")
        connection.execute("INSERT INTO events (type, total) VALUES ('murder', 148)")
        connection.execute("INSERT INTO events (type, total) VALUES ('arson', 148)")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    payload = orchestrator.json.loads(
        session.execute_action(
            {
                "action": "request_new_query",
                "description": "contar tipos",
                "suggested_sql": "SELECT type, total FROM events",
            }
        )
    )

    last_node = session.knowledge_graph.nodes[-1]
    child_reqs = [req for req in last_node.next_requirements if req["id"].startswith("req_events_type_")]
    assert len(child_reqs) >= 2
    assert any(req["suggested_action"]["action"] == "request_new_query" for req in child_reqs)
    assert any("WHERE type = 'murder'" in req["suggested_action"]["suggested_sql"] for req in child_reqs)
    assert any(req.get("role") == "category_filter" for req in child_reqs)
    assert any(isinstance(req.get("filter"), dict) and req["filter"].get("column") == "type" for req in child_reqs)
    assert any(
        "SELECT type FROM events WHERE type =" not in req["suggested_action"]["suggested_sql"]
        for req in child_reqs
    )


def test_request_new_query_categorical_value_escapes_single_quotes(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE events (type TEXT, total INTEGER)")
        connection.execute("INSERT INTO events (type, total) VALUES ('Bob''s category', 42)")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    payload = orchestrator.json.loads(
        session.execute_action(
            {
                "action": "request_new_query",
                "description": "contar tipos",
                "suggested_sql": "SELECT type, total FROM events",
            }
        )
    )

    last_node = session.knowledge_graph.nodes[-1]
    asserted = any(
        "WHERE type = 'Bob''s category'" in req["suggested_action"]["suggested_sql"]
        for req in last_node.next_requirements
    )
    assert asserted


def test_execute_action_request_new_query_resolves_parent_and_creates_children(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE events (type TEXT, total INTEGER)")
        connection.execute("INSERT INTO events (type, total) VALUES ('murder', 148)")
        connection.execute("INSERT INTO events (type, total) VALUES ('arson', 148)")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    parent_node = orchestrator.KnowledgeNode(
        id="node:parent",
        label="Resumo pendente",
        unit="events",
        data={},
        timestamp="2026-05-27T00:00:00+00:00",
        next_requirements=[
            {
                "id": "req_parent",
                "kind": "query",
                "units": ["events"],
                "description": "Explorar tipos",
                "reason": "pendente",
                "suggested_action": {"action": "request_new_query", "description": "contar tipos", "suggested_sql": "SELECT type, total FROM events"},
                "status": "pending",
                "source_node_id": "node:parent",
            }
        ],
    )
    session.knowledge_graph = orchestrator.KnowledgeGraph(nodes=[parent_node])

    session.execute_action(
        {
            "action": "request_new_query",
            "description": "contar tipos",
            "suggested_sql": "SELECT type, total FROM events",
            "_source_requirement_id": "req_parent",
        }
    )

    assert any(
        req.get("id") == "req_parent" and req.get("status") == "resolved"
        for node in session.knowledge_graph.nodes
        for req in node.next_requirements
    )
    assert any(
        req.get("id", "").startswith("req_events_type_") and req.get("status") == "pending"
        for node in session.knowledge_graph.nodes
        for req in node.next_requirements
    )


def test_execute_action_category_filter_sets_active_focus_and_creates_drilldown(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE events (id INTEGER, type TEXT, created_at TEXT, city TEXT, description TEXT)"
        )
        connection.execute(
            "INSERT INTO events (id, type, created_at, city, description) VALUES "
            "(1, 'murder', '2024-01-01', 'A', 'alpha'), "
            "(2, 'murder', '2024-01-02', 'B', 'beta'), "
            "(3, 'arson', '2024-01-03', 'A', 'gamma')"
        )
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session._active_focus = None
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "events",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "type", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "created_at", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 4, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    parent_node = orchestrator.KnowledgeNode(
        id="node:distribution",
        label="Distribuição por type",
        unit="events",
        data={},
        timestamp="2026-05-27T00:00:00+00:00",
        next_requirements=[
            {
                "id": "req_events_type_murder",
                "kind": "query",
                "units": ["events"],
                "description": "Explorar registros onde type = murder",
                "reason": "pendente",
                "role": "category_filter",
                "parent_requirement_id": "req_parent_distribution",
                "filter": {"column": "type", "value": "murder", "operator": "="},
                "suggested_action": {
                    "action": "request_new_query",
                    "description": "explorar murder",
                    "suggested_sql": "SELECT id, created_at, city, description FROM events WHERE type = 'murder' LIMIT 50",
                },
                "status": "pending",
                "source_node_id": "node:distribution",
            },
            {
                "id": "req_events_type_arson",
                "kind": "query",
                "units": ["events"],
                "description": "Explorar registros onde type = arson",
                "reason": "pendente",
                "role": "category_filter",
                "parent_requirement_id": "req_parent_distribution",
                "filter": {"column": "type", "value": "arson", "operator": "="},
                "suggested_action": {
                    "action": "request_new_query",
                    "description": "explorar arson",
                    "suggested_sql": "SELECT id, created_at, city, description FROM events WHERE type = 'arson' LIMIT 50",
                },
                "status": "pending",
                "source_node_id": "node:distribution",
            },
        ],
    )
    session.knowledge_graph = orchestrator.KnowledgeGraph(nodes=[parent_node])

    session.execute_action(
        {
            "action": "request_new_query",
            "description": "explorar murder",
            "suggested_sql": "SELECT id, created_at, city, description FROM events WHERE type = 'murder' LIMIT 50",
            "_source_requirement_id": "req_events_type_murder",
        }
    )

    assert session._active_focus is not None
    assert session._active_focus["source_requirement_id"] == "req_events_type_murder"
    assert session._active_focus["filter"] == {"column": "type", "value": "murder", "operator": "="}
    last_node = session.knowledge_graph.nodes[-1]
    assert session._active_focus["node_id"] == last_node.id
    assert any(req.get("role") == "drilldown" for req in last_node.next_requirements)
    assert any(
        req.get("id") == "req_events_type_murder" and req.get("status") == "resolved"
        for node in session.knowledge_graph.nodes
        for req in node.next_requirements
    )


def test_execute_action_drilldown_marks_requirement_resolved_and_keeps_it_out_of_pending(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE events (id INTEGER, type TEXT, description TEXT, city TEXT)"
        )
        connection.execute(
            "INSERT INTO events (id, type, description, city) VALUES "
            "(1, 'murder', 'alpha', 'A'), "
            "(2, 'murder', 'beta', 'B'), "
            "(3, 'arson', 'gamma', 'A')"
        )
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_events_type_murder",
        "cache_key": "query:q_murder",
        "units": ["events"],
        "columns": ["id", "type", "description", "city"],
        "filter": {"column": "type", "value": "murder", "operator": "="},
        "node_id": "events:2",
    }
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "events",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "type", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Distribuição por type",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_events_type_murder",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explorar registros onde type = murder",
                        "reason": "resolvido",
                        "role": "category_filter",
                        "parent_requirement_id": "req_parent_distribution",
                        "filter": {"column": "type", "value": "murder", "operator": "="},
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "explorar murder",
                            "suggested_sql": "SELECT id, description, city FROM events WHERE type = 'murder' LIMIT 50",
                        },
                        "status": "resolved",
                        "source_node_id": "events:1",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="events:2",
                label="Registros filtrados por murder",
                unit="events",
                data={},
                timestamp="2026-05-27T01:05:00+00:00",
                next_requirements=[
                    {
                        "id": "req_events_type_text_description",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Amostrar textos em events dentro do filtro atual",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_events_type_murder",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "amostrar textos filtrados por type",
                            "suggested_sql": "SELECT id, description FROM events WHERE type = 'murder' AND description IS NOT NULL AND TRIM(CAST(description AS TEXT)) <> '' LIMIT 50",
                        },
                        "status": "pending",
                        "source_node_id": "events:2",
                    },
                    {
                        "id": "req_events_type_group_city",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Agrupar o recorte atual por city",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_events_type_murder",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "agrupar dentro do filtro por city",
                            "suggested_sql": "SELECT city, COUNT(*) AS total FROM events WHERE type = 'murder' GROUP BY city ORDER BY total DESC LIMIT 50",
                        },
                        "status": "pending",
                        "source_node_id": "events:2",
                    },
                ],
            ),
        ]
    )

    session.execute_action(
        {
            "action": "request_new_query",
            "description": "amostrar textos filtrados por type",
            "suggested_sql": "SELECT id, description FROM events WHERE type = 'murder' AND description IS NOT NULL AND TRIM(CAST(description AS TEXT)) <> '' LIMIT 50",
            "_source_requirement_id": "req_events_type_text_description",
        }
    )

    matched = [
        req
        for node in session.knowledge_graph.nodes
        for req in node.next_requirements
        if req.get("id") == "req_events_type_text_description"
    ]
    assert len(matched) == 1
    assert matched[0].get("status") == "resolved"
    assert all(req.get("id") != "req_events_type_text_description" for req in session.pending_requirements())


def test_request_new_query_without_source_requirement_resolves_exact_pending_requirement(tmp_path) -> None:
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
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Resumo",
                unit="events",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_events_list",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Listar eventos",
                        "reason": "pendente",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "listar eventos",
                            "suggested_sql": "SELECT id, category FROM events",
                        },
                        "status": "pending",
                        "source_node_id": "events:1",
                    }
                ],
            )
        ]
    )

    session.execute_action(
        {
            "action": "request_new_query",
            "description": "listar eventos de novo",
            "suggested_sql": " SELECT   id, category   FROM events ",
        }
    )

    requirement = session.knowledge_graph.find_requirement("req_events_list")
    assert requirement is not None
    assert requirement[1]["status"] == "resolved"
    assert all(req.get("id") != "req_events_list" for req in session.pending_requirements())


def test_request_new_query_without_source_requirement_resolves_equivalent_text_drilldown(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE events (id INTEGER, type TEXT, description TEXT, city TEXT)")
        connection.execute("INSERT INTO events (id, type, description, city) VALUES (1, 'murder', 'alpha', 'A')")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_events_type_murder",
        "cache_key": "query:q_murder",
        "units": ["events"],
        "columns": ["id", "type", "description", "city"],
        "filter": {"column": "type", "value": "murder", "operator": "="},
        "node_id": "events:2",
    }
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Distribuição",
                unit="events",
                data={},
                timestamp="2026-05-27T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_events_type_murder",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explorar murder",
                        "reason": "resolvido",
                        "role": "category_filter",
                        "filter": {"column": "type", "value": "murder", "operator": "="},
                        "status": "resolved",
                        "source_node_id": "events:1",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="events:2",
                label="Filtrado",
                unit="events",
                data={},
                timestamp="2026-05-27T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_events_type_text_description",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Amostrar textos",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_events_type_murder",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "amostrar textos filtrados por type",
                            "suggested_sql": "SELECT id, description FROM events WHERE type = 'murder' AND description IS NOT NULL AND TRIM(CAST(description AS TEXT)) <> '' LIMIT 50",
                        },
                        "status": "pending",
                        "source_node_id": "events:2",
                    }
                ],
            ),
        ]
    )

    session.execute_action(
        {
            "action": "request_new_query",
            "description": "amostrar_textos_filtrados_por_type_2",
            "suggested_sql": "SELECT id, description FROM events WHERE type = 'murder' AND description IS NOT NULL AND TRIM(CAST(description AS TEXT)) <> '' LIMIT 50",
        }
    )

    requirement = session.knowledge_graph.find_requirement("req_events_type_text_description")
    assert requirement is not None
    assert requirement[1]["status"] == "resolved"
    assert all(req.get("id") != "req_events_type_text_description" for req in session.pending_requirements())


def test_render_knowledge_map_shows_resolved_drilldown_status() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = []
    session.analysis_by_unit = {}
    session._core_cache = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Registros filtrados",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_events_type_text_description",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Amostrar textos em events dentro do filtro atual",
                        "status": "resolved",
                    },
                    {
                        "id": "req_events_type_group_city",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Agrupar o recorte atual por city",
                        "status": "pending",
                    },
                ],
            )
        ]
    )

    rendered = session.render_knowledge_map()
    assert "req_events_type_text_description [resolved]" in rendered
    assert "req_events_type_group_city [pending]" in rendered


def test_build_requirements_from_textual_clues_generates_last_house_query() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "people",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_street_name", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_number", "position": 3, "raw_type": "INTEGER", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]

    requirements = session._build_requirements_from_textual_clues(
        result={
            "units": ["reports"],
            "columns": ["description"],
            "rows": [[
                'Security footage shows that the first witness lives at the last house on "Northwestern Dr".'
            ]],
        },
        source_node_id="reports:2",
    )

    assert any(req.get("role") == "textual_clue" for req in requirements)
    assert any("ORDER BY address_number DESC LIMIT 1" in req["suggested_action"]["suggested_sql"] for req in requirements)


def test_build_requirements_from_textual_clues_generates_named_street_query() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "people",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_street_name", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]

    requirements = session._build_requirements_from_textual_clues(
        result={
            "units": ["reports"],
            "columns": ["description"],
            "rows": [[
                'The second witness, named Annabel, lives somewhere on "Franklin Ave".'
            ]],
        },
        source_node_id="reports:2",
    )

    assert any("name LIKE '%Annabel%'" in req["suggested_action"]["suggested_sql"] for req in requirements)
    assert any("address_street_name = 'Franklin Ave'" in req["suggested_action"]["suggested_sql"] for req in requirements)


def test_build_requirements_from_textual_clues_escapes_quotes() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "people",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "name", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_street_name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]

    requirements = session._build_requirements_from_textual_clues(
        result={
            "units": ["reports"],
            "columns": ["description"],
            "rows": [[
                'A witness, named O\'Brian, lives somewhere on "King\'s Rd".'
            ]],
        },
        source_node_id="reports:2",
    )

    assert any("name LIKE '%O''Brian%'" in req["suggested_action"]["suggested_sql"] for req in requirements)
    assert any("address_street_name = 'King''s Rd'" in req["suggested_action"]["suggested_sql"] for req in requirements)


def test_build_requirements_from_textual_clues_deduplicates_existing_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="reports",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_last_house_northwestern_dr",
                        "status": "pending",
                    }
                ],
            )
        ]
    )
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "people",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "address_street_name", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_number", "position": 1, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "id", "position": 2, "raw_type": "INTEGER", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    requirements = session._build_requirements_from_textual_clues(
        result={
            "units": ["reports"],
            "columns": ["description"],
            "rows": [['last house on "Northwestern Dr"']],
        },
        source_node_id="reports:2",
    )
    assert requirements == []


def test_build_requirements_from_textual_clues_uses_result_rows_not_node_data() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="reports",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
            )
        ]
    )
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "people",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_number", "position": 2, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_street_name", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]

    requirements = session._build_requirements_from_textual_clues(
        result={
            "units": ["reports"],
            "columns": ["description"],
            "rows": [[
                'The first witness lives at the last house on "Northwestern Dr". The second witness, named Annabel, lives somewhere on "Franklin Ave".'
            ]],
        },
        source_node_id="reports:2",
    )

    assert len([req for req in requirements if req.get("role") == "textual_clue"]) >= 2


def test_build_related_entity_requirements_creates_requirement_for_matching_entity_id() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "entity",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),)},
                )(),
            },
        )(),
        type(
            "Unit",
            (),
            {
                "unit_name": "event_log",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "entity_id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "note", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
    ]

    requirements = session._build_related_entity_requirements(
        result={"units": ["entity"], "columns": ["id", "name"], "rows": [[123, "A"]]},
        source_node_id="entity:1",
    )

    assert len(requirements) == 1
    assert requirements[0]["role"] == "related_entity"
    assert requirements[0]["units"] == ["event_log"]
    assert "WHERE entity_id = 123" in requirements[0]["suggested_action"]["suggested_sql"]


def test_build_related_entity_requirements_finds_generic_related_table_without_hardcode() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "person",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
        type(
            "Unit",
            (),
            {
                "unit_name": "interview",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "person_id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "transcript", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
    ]

    requirements = session._build_related_entity_requirements(
        result={"units": ["person"], "columns": ["id", "name"], "rows": [[97913, "Cameron Dilick"]]},
        source_node_id="person:9",
    )

    assert len(requirements) == 1
    assert requirements[0]["units"] == ["interview"]
    assert "WHERE person_id = 97913" in requirements[0]["suggested_action"]["suggested_sql"]


def test_build_related_entity_requirements_uses_prefixed_key_to_match_related_unit_id() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "person",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "license_id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
        type(
            "Unit",
            (),
            {
                "unit_name": "licenses",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "status", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
    ]

    requirements = session._build_related_entity_requirements(
        result={"units": ["person"], "columns": ["license_id", "name"], "rows": [[971988, "A"]]},
        source_node_id="person:10",
    )

    assert len(requirements) == 1
    assert requirements[0]["units"] == ["licenses"]
    assert "WHERE id = 971988" in requirements[0]["suggested_action"]["suggested_sql"]


def test_build_related_entity_requirements_does_not_create_redundant_executed_filter() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="person:1",
                label="person",
                unit="person",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_person_interview_done",
                        "status": "resolved",
                        "suggested_action": {
                            "action": "request_new_query",
                            "suggested_sql": "SELECT * FROM interview WHERE person_id = 97913 LIMIT 50",
                        },
                    }
                ],
            )
        ]
    )
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "person",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),)},
                )(),
            },
        )(),
        type(
            "Unit",
            (),
            {
                "unit_name": "interview",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "person_id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),)},
                )(),
            },
        )(),
    ]

    requirements = session._build_related_entity_requirements(
        result={"units": ["person"], "columns": ["id"], "rows": [[97913]]},
        source_node_id="person:1",
    )

    assert requirements == []


def test_build_related_entity_requirements_keeps_previous_behavior_when_no_related_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "entity",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),)},
                )(),
            },
        )(),
        type(
            "Unit",
            (),
            {
                "unit_name": "notes",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "text", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),)},
                )(),
            },
        )(),
    ]

    requirements = session._build_related_entity_requirements(
        result={"units": ["entity"], "columns": ["id", "name"], "rows": [[123, "A"]]},
        source_node_id="entity:2",
    )

    assert requirements == []


def test_execute_action_request_new_query_attaches_textual_clue_requirements_to_last_node(tmp_path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE reports (description TEXT, city TEXT)")
        connection.execute(
            "INSERT INTO reports (description, city) VALUES (?, ?)",
            (
                'Security footage shows that there were 2 witnesses. The first witness lives at the last house on "Northwestern Dr". The second witness, named Annabel, lives somewhere on "Franklin Ave".',
                "SQL City",
            ),
        )
        connection.execute(
            "CREATE TABLE people (id INTEGER, name TEXT, address_number INTEGER, address_street_name TEXT)"
        )
        connection.execute("INSERT INTO people (id, name, address_number, address_street_name) VALUES (1, 'Annabel Miller', 4919, 'Franklin Ave')")
        connection.commit()

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_type = "sqlite"
    session.source_path = str(db_path)
    session._session_query_catalog = {}
    session._candidate_queries = []
    session._core_cache = {}
    session._execution_log = []
    session.curator_ai = type(
        "QuietCurator",
        (),
        {"send": lambda self, prompt, system_prompt=None: type("Response", (), {"content": '{"from_id":"","relation":""}'})()},
    )()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "reports",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "description", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
        type(
            "Unit",
            (),
            {
                "unit_name": "people",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "name", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_number", "position": 2, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "address_street_name", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )(),
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    session.execute_action(
        {
            "action": "request_new_query",
            "description": "consultar pistas em sql city",
            "suggested_sql": "SELECT description, city FROM reports WHERE city = 'SQL City' LIMIT 50",
        }
    )

    last_node = session.knowledge_graph.nodes[-1]
    clue_requirements = [req for req in last_node.next_requirements if req.get("role") == "textual_clue"]
    assert len(clue_requirements) >= 2
    assert any("ORDER BY address_number DESC LIMIT 1" in req["suggested_action"]["suggested_sql"] for req in clue_requirements)
    assert any("name LIKE '%Annabel%'" in req["suggested_action"]["suggested_sql"] for req in clue_requirements)


def test_render_knowledge_map_shows_pending_textual_clue_requirements() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = []
    session.analysis_by_unit = {}
    session._core_cache = {}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas em SQL City",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports_2_textual_clue_northwestern",
                        "kind": "query",
                        "role": "textual_clue",
                        "description": "Buscar última residência em Northwestern Dr",
                        "status": "pending",
                    }
                ],
            )
        ]
    )
    rendered = session.render_knowledge_map()
    assert "req_reports_2_textual_clue_northwestern [pending]" in rendered


def test_render_knowledge_map_lists_pending_textual_clue_before_recent_derived_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = []
    session.analysis_by_unit = {}
    session._core_cache = {}
    session._active_focus = {"clue_group_id": "reports:2"}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Grupo de pistas",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_group_clue_pending",
                        "kind": "query",
                        "role": "textual_clue",
                        "description": "Pista textual pendente",
                        "status": "pending",
                        "source_node_id": "reports:2",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recente",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_person_id_1",
                        "kind": "query",
                        "description": "Explorar registro por id",
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    rendered = session.render_knowledge_map()
    assert rendered.index("req_group_clue_pending") < rendered.index("req_person_id_1")


def test_pending_requirements_returns_textual_clue_requirements() -> None:
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports_2_textual_clue_northwestern",
                        "kind": "query",
                        "role": "textual_clue",
                        "description": "Buscar última residência em Northwestern Dr",
                        "status": "pending",
                    }
                ],
            )
        ]
    )
    pending = graph.pending_requirements()
    assert pending
    assert pending[0]["role"] == "textual_clue"


def test_pending_requirements_prioritizes_textual_clue_before_recent_derived_requirement() -> None:
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Grupo de pistas",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_group_clue_pending",
                        "kind": "query",
                        "role": "textual_clue",
                        "description": "Pista textual pendente",
                        "status": "pending",
                        "source_node_id": "reports:2",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recente",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_person_id_1",
                        "kind": "query",
                        "description": "Explorar registro por id",
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    pending = graph.pending_requirements(active_focus={"clue_group_id": "reports:2"})
    assert [req["id"] for req in pending[:2]] == ["req_group_clue_pending", "req_person_id_1"]


def test_session_pending_requirements_prioritizes_operational_requirement_before_redundant_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._active_focus = None
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo estrutural",
                unit="manifest",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_category_flag",
                        "kind": "query",
                        "units": ["manifest"],
                        "description": "Contagem agregada por flag",
                        "status": "pending",
                        "suggested_action": {"action": "request_new_query", "description": "agregar por flag", "suggested_sql": "SELECT flag, COUNT(*) AS total FROM manifest GROUP BY flag"},
                    },
                ],
            )
        ]
    )

    pending = session.pending_requirements()
    assert [req["id"] for req in pending[:2]] == ["req_manifest_category_flag", "req_manifest_schema"]


def test_render_knowledge_map_lists_operational_requirements_before_schema_after_analysis() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session.analysis_by_unit = {"manifest": object()}
    session.explored_paths = ["manifest"]
    session._active_focus = None
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo estrutural",
                unit="manifest",
                data={"evidence": {"columns": ["flag", "amount"]}},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_query",
                        "kind": "query",
                        "units": ["manifest"],
                        "description": "Contagem agregada por flag",
                        "status": "pending",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "agregar por flag",
                            "suggested_sql": "SELECT flag, COUNT(*) AS total FROM manifest GROUP BY flag",
                        },
                    },
                    {
                        "id": "req_manifest_numeric",
                        "kind": "query",
                        "units": ["manifest"],
                        "description": "Resumo numérico de amount",
                        "status": "pending",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "resumo numérico",
                            "suggested_sql": "SELECT MIN(amount), MAX(amount) FROM manifest",
                        },
                    },
                ],
            )
        ]
    )

    pending = session.pending_requirements()
    assert [req["id"] for req in pending] == [
        "req_manifest_query",
        "req_manifest_numeric",
        "req_manifest_schema",
    ]
    rendered = session.render_knowledge_map()
    assert rendered.index("req_manifest_query") < rendered.index("req_manifest_schema")
    assert rendered.index("req_manifest_numeric") < rendered.index("req_manifest_schema")


def test_render_knowledge_map_shows_csv_operational_requirement_before_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session.analysis_by_unit = {"manifest": object()}
    session.explored_paths = ["manifest"]
    session._active_focus = None
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="manifest:1",
                label="Resumo estrutural",
                unit="manifest",
                data={"evidence": {"columns": ["status", "amount", "notes"]}},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_manifest_schema",
                        "kind": "schema",
                        "units": ["manifest"],
                        "description": "Consultar schema de manifest",
                        "status": "pending",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_vertical_layer2",
                        "kind": "analyze_vertical",
                        "units": ["manifest"],
                        "description": "Aprofundar métricas de colunas",
                        "status": "pending",
                        "suggested_action": {"action": "analyze_vertical", "unit_name": "manifest", "depth": "layer2"},
                    },
                ],
            )
        ]
    )

    rendered = session.render_knowledge_map()
    assert rendered.index("req_manifest_vertical_layer2") < rendered.index("req_manifest_schema")


def test_orchestrator_has_no_hardcoded_textual_clue_examples() -> None:
    source = (ROOT / "orchestrator.py").read_text(encoding="utf-8")
    for fragment in ("SQL City", "Northwestern Dr", "Annabel", "Franklin Ave"):
        assert fragment not in source


def test_rule_based_planner_has_no_dataset_specific_rules() -> None:
    planner_source = (ROOT / "src/agnostic/application/planning/rule_based_planner.py").read_text(encoding="utf-8").lower()
    banned_fragments = [
        "sql murder mystery",
        "crime_scene_report",
        "drivers_license",
        "get_fit_now_member",
        "murder",
        "person",
        "interview",
    ]
    for fragment in banned_fragments:
        assert fragment not in planner_source

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
    assert isinstance(payload["next_requirements"], list)


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
    assert isinstance(payload["next_requirements"], list)
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
