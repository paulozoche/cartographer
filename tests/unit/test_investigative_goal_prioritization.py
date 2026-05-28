from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from agnostic.application.planning.rule_based_planner import (
    _rank_search_terms_for_filtering,
    _search_terms_from_free_text,
    _select_independent_filter_terms,
    _validate_generated_select_sql,
    first_pending_requirement,
    focused_pending_requirements,
    plan_direct_value_command,
    plan_deterministic_action,
    plan_filter_for_observed_value,
    plan_multi_value_filter,
    score_related_entity_requirement,
)


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "orchestrator.py"
SPEC = importlib.util.spec_from_file_location("orchestrator_module", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
orchestrator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = orchestrator
SPEC.loader.exec_module(orchestrator)


def test_knowledge_graph_pending_requirements_ordered_by_recency() -> None:
    """Verify that pending_requirements() returns requirements from most recent nodes first."""
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Older node",
                unit="events",
                data={},
                timestamp="2026-05-25T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_old_query",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Old query",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="node:2",
                label="Recent node",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_recent_query",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Recent query",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "node:2",
                    }
                ],
            ),
        ]
    )

    pending = graph.pending_requirements()
    assert len(pending) == 2
    # Most recent node's requirement should come first
    assert pending[0]["id"] == "req_recent_query"
    assert pending[1]["id"] == "req_old_query"


def test_first_pending_requirement_prioritizes_derived_children() -> None:
    """Verify that first_pending_requirement prioritizes derived children (source_node_id not empty)."""
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Old node with generic requirement",
                unit="events",
                data={},
                timestamp="2026-05-25T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_generic_analyze",
                        "kind": "analyze_horizontal",
                        "units": ["events", "users"],
                        "description": "Analyze horizontal",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",  # Not derived
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="node:2",
                label="Recent node with derived requirement",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_derived_child",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explore where type = murder",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "node:2",  # Derived from node:2
                    },
                    {
                        "id": "req_recall",
                        "kind": "recall",
                        "units": ["events"],
                        "description": "Recall",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",
                    },
                ],
            ),
        ]
    )

    # first_pending_requirement should return the derived child from node:2
    # (most recent, derived, kind=query)
    first_req = first_pending_requirement(graph)
    assert first_req is not None
    assert first_req["id"] == "req_derived_child"
    assert str(first_req.get("source_node_id", "")).strip() != ""


def test_build_interface_prompt_includes_pending_requirements() -> None:
    """Verify that build_interface_prompt includes pending_requirements in the JSON payload."""
    pending_reqs = [
        {
            "id": "req_1",
            "kind": "query",
            "description": "Execute query 1",
            "status": "pending",
        },
        {
            "id": "req_2",
            "kind": "recall",
            "description": "Recall data",
            "status": "pending",
        },
    ]

    prompt_json = orchestrator.build_interface_prompt(
        source_path="/data/test.db",
        source_type="sqlite",
        history=[],
        user_text="What do we know?",
        result_context="Some results",
        structural_context="Schema info",
        is_first_call=False,
        pending_requirements=pending_reqs,
    )

    payload = json.loads(prompt_json)
    assert "pending_requirements" in payload
    assert len(payload["pending_requirements"]) == 2
    assert payload["pending_requirements"][0]["id"] == "req_1"
    assert payload["pending_requirements"][1]["id"] == "req_2"


def test_build_interface_prompt_handles_no_pending_requirements() -> None:
    """Verify that build_interface_prompt handles None pending_requirements gracefully."""
    prompt_json = orchestrator.build_interface_prompt(
        source_path="/data/test.db",
        source_type="sqlite",
        history=[],
        user_text="What do we know?",
        result_context="Some results",
        structural_context="Schema info",
        is_first_call=False,
        pending_requirements=None,
    )

    payload = json.loads(prompt_json)
    assert "pending_requirements" in payload
    assert payload["pending_requirements"] == []


def test_first_pending_requirement_from_most_recent_node_first() -> None:
    """Verify that first_pending_requirement iterates nodes in reverse order."""
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="First node",
                unit="events",
                data={},
                timestamp="2026-05-25T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_first",
                        "kind": "query",
                        "units": ["events"],
                        "description": "From first node",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="node:2",
                label="Second node (more recent)",
                unit="events",
                data={},
                timestamp="2026-05-26T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_second",
                        "kind": "query",
                        "units": ["events"],
                        "description": "From second node",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="node:3",
                label="Third node (most recent)",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_third",
                        "kind": "query",
                        "units": ["events"],
                        "description": "From third node",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",
                    }
                ],
            ),
        ]
    )

    first_req = first_pending_requirement(graph)
    assert first_req is not None
    assert first_req["id"] == "req_third", "Should prioritize most recent node first"


def test_first_pending_requirement_prioritizes_derived_over_generic_in_same_node() -> None:
    """Verify that in the same node, derived children are prioritized over generic requirements."""
    graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Node with mixed requirements",
                unit="events",
                data={},
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_generic",
                        "kind": "analyze_horizontal",
                        "units": ["events", "users"],
                        "description": "Generic analysis",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "",  # Not derived
                    },
                    {
                        "id": "req_derived",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Derived from categorization",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "node:1",  # Derived
                    },
                ],
            ),
        ]
    )

    first_req = first_pending_requirement(graph)
    assert first_req is not None
    assert first_req["id"] == "req_derived", "Should prioritize derived child over generic"


def test_plan_deterministic_action_consumes_derived_child_over_recall() -> None:
    """End-to-end: verify that planner consumes derived child before recall."""
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []

    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="node:1",
                label="Categorical aggregation result",
                unit="events",
                action="query",
                data={},
                status="complete",
                timestamp="2026-05-27T01:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_child_murder",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explore where type = 'murder'",
                        "reason": "pendente",
                        "suggested_action": {"action": "request_new_query", "description": "Explore where type = 'murder'"},
                        "status": "pending",
                        "source_node_id": "node:1",  # Derived child
                    },
                    {
                        "id": "req_recall",
                        "kind": "recall",
                        "units": ["events"],
                        "description": "Recall cached data",
                        "reason": "pendente",
                        "suggested_action": {"action": "recall", "key": "unit:events"},
                        "status": "pending",
                        "source_node_id": "",  # Generic, not derived
                    },
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    # Should consume the derived child requirement, not the generic recall
    assert payload.get("action") == "request_new_query"
    assert payload.get("_source_requirement_id") == "req_child_murder"
    assert payload.get("__requirement_id") == "req_child_murder"


def test_plan_deterministic_action_uses_active_focus_drilldown_before_category_sibling() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_child_murder",
        "cache_key": "query:q_murder",
        "units": ["events"],
        "columns": ["id", "type", "city"],
        "filter": {"column": "type", "value": "murder", "operator": "="},
        "node_id": "events:2",
    }
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
                        "id": "req_child_murder",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explore where type = 'murder'",
                        "reason": "pendente",
                        "role": "category_filter",
                        "parent_requirement_id": "req_parent",
                        "suggested_action": {"action": "request_new_query", "description": "murder", "suggested_sql": "SELECT * FROM events WHERE type = 'murder'"},
                        "status": "resolved",
                        "source_node_id": "events:1",
                    },
                    {
                        "id": "req_child_arson",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explore where type = 'arson'",
                        "reason": "pendente",
                        "role": "category_filter",
                        "parent_requirement_id": "req_parent",
                        "suggested_action": {"action": "request_new_query", "description": "arson", "suggested_sql": "SELECT * FROM events WHERE type = 'arson'"},
                        "status": "pending",
                        "source_node_id": "events:1",
                    },
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
                        "id": "req_drilldown_city",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Agrupar por city dentro do filtro",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_child_murder",
                        "suggested_action": {"action": "request_new_query", "description": "city", "suggested_sql": "SELECT city, COUNT(*) AS total FROM events WHERE type = 'murder' GROUP BY city"},
                        "status": "pending",
                        "source_node_id": "events:2",
                    }
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_drilldown_city"
    assert payload.get("__requirement_id") == "req_drilldown_city"


def test_plan_deterministic_action_numeric_without_option_does_not_consume_category_sibling() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
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
                        "id": "req_child_arson",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Explore where type = 'arson'",
                        "reason": "pendente",
                        "role": "category_filter",
                        "parent_requirement_id": "req_parent",
                        "suggested_action": {"action": "request_new_query", "description": "arson", "suggested_sql": "SELECT * FROM events WHERE type = 'arson'"},
                        "status": "pending",
                        "source_node_id": "events:1",
                    }
                ],
            )
        ]
    )

    assert plan_deterministic_action(session, "1") is None


def test_plan_deterministic_action_numeric_option_maps_to_observed_value_filter() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session._core_cache = {
        "query:q1": {
            "units": ["reports"],
            "columns": ["city", "description"],
            "rows": [("SQL City", "note")],
        }
    }
    session._execution_log = []
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
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session._last_presented_options = [
        {"index": 1, "text": "Aprofundar SQL City", "created_at_turn": 3},
        {"index": 2, "text": "Cruzar com outra tabela", "created_at_turn": 3},
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:1",
                label="Amostra",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                sample_entities=["city=SQL City, description=note"],
                next_requirements=[
                    {
                        "id": "req_old_time",
                        "kind": "query",
                        "units": ["reports"],
                        "description": "Agrupar por data",
                        "role": "drilldown",
                        "suggested_action": {"action": "request_new_query", "description": "agrupar por data", "suggested_sql": "SELECT date, COUNT(*) FROM reports GROUP BY date"},
                        "status": "pending",
                        "source_node_id": "reports:1",
                    }
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "1")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert "WHERE LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in payload["suggested_sql"]


def test_numeric_option_with_mapping_does_not_consume_old_drilldown() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session._core_cache = {"query:q1": {"units": ["reports"], "columns": ["city"], "rows": [("SQL City",)]}}
    session._execution_log = []
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "reports",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "city", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),)},
                )(),
            },
        )()
    ]
    session._last_presented_options = [{"index": 1, "text": "Aprofundar SQL City"}]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:1",
                label="Amostra",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                sample_entities=["city=SQL City"],
                next_requirements=[
                    {
                        "id": "req_old_drilldown",
                        "kind": "query",
                        "units": ["reports"],
                        "description": "drilldown antigo",
                        "role": "drilldown",
                        "suggested_action": {"action": "request_new_query", "description": "old", "suggested_sql": "SELECT * FROM reports LIMIT 50"},
                        "status": "pending",
                        "source_node_id": "reports:1",
                    }
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "1")
    assert payload is not None
    assert payload["suggested_sql"] != "SELECT * FROM reports LIMIT 50"


def test_numeric_option_cross_table_without_safe_mapping_returns_none() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
    session.units = []
    session._last_presented_options = [{"index": 2, "text": "Cruzar com outra tabela"}]
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    assert plan_deterministic_action(session, "2") is None


def test_plan_deterministic_action_multi_values_returns_request_new_query_not_schema() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session._core_cache = {
        "query:q1": {
            "units": ["reports"],
            "columns": ["type", "city", "description"],
            "rows": [("murder", "SQL City", "note")],
        }
    }
    session._execution_log = []
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
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "type", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    payload = plan_deterministic_action(session, "murders sql city")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert "WHERE LOWER(CAST(type AS TEXT)) = LOWER('murder') AND LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in payload["suggested_sql"]


def test_schema_requires_explicit_keyword() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "reports"})()]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session._execution_log = []
    payload = plan_deterministic_action(session, "reports sql city")
    assert payload is None or payload.get("action") != "schema"
    assert plan_deterministic_action(session, "schema reports") == {"action": "schema", "table": "reports"}


def test_short_confirmation_prefers_operational_requirement_over_schema_after_analysis() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest", "next_requirements": []}}
    session._active_focus = None
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
                        "source_node_id": "manifest:1",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    },
                    {
                        "id": "req_manifest_category_flag",
                        "kind": "query",
                        "units": ["manifest"],
                        "description": "Contagem agregada por flag",
                        "status": "pending",
                        "source_node_id": "manifest:1",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "agregar por flag",
                            "suggested_sql": "SELECT flag, COUNT(*) AS total FROM manifest GROUP BY flag",
                        },
                    },
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert payload.get("_source_requirement_id") == "req_manifest_category_flag"


def test_short_confirmation_can_execute_schema_when_schema_is_only_pending_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [type("Unit", (), {"unit_name": "manifest"})()]
    session._execution_log = [{"action": "analyze_unit", "unit": "manifest"}]
    session._core_cache = {"unit:manifest": {"unit_name": "manifest"}}
    session._active_focus = None
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
                        "source_node_id": "manifest:1",
                        "suggested_action": {"action": "schema", "table": "manifest"},
                    }
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload["action"] == "schema"
    assert payload["table"] == "manifest"


def test_plan_multi_value_filter_considers_plural_simple_form() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {
        "query:q1": {
            "units": ["reports"],
            "columns": ["type", "city"],
            "rows": [("murder", "SQL City")],
        }
    }
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "reports",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "type", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(), type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})())},
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    payload = plan_multi_value_filter(session, "murders sql city")
    assert payload is not None
    sql = payload["suggested_sql"]
    assert payload["action"] == "request_new_query"
    assert "SELECT" in sql
    assert "FROM" in sql
    assert "WHERE" in sql
    assert "LIMIT 50" in sql
    assert "SELECT FROM" not in sql
    assert "SELECT ," not in sql
    assert "WHERE  LIMIT" not in sql
    assert "FROM  WHERE" not in sql
    assert "murder" in sql
    assert "city" in sql
    assert "AND" in sql
    assert "LOWER(CAST(type AS TEXT)) = LOWER('murder')" in sql
    assert "LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in sql
    assert orchestrator.validate_select_sql_text(sql)


def test_rank_search_terms_for_filtering_prioritizes_useful_terms() -> None:
    ranked_terms = _rank_search_terms_for_filtering(_search_terms_from_free_text("murders sql city"))
    assert ranked_terms.index("murder") < ranked_terms.index("murders sql city")
    assert ranked_terms.index("sql city") < ranked_terms.index("murders sql city")
    assert ranked_terms[:7] == ["murder", "sql city", "murders", "sql", "city", "murders sql", "murders sql city"]


def test_select_independent_filter_terms_prefers_independent_groups() -> None:
    ranked_terms = _rank_search_terms_for_filtering(_search_terms_from_free_text("murders sql city"))
    assert _select_independent_filter_terms(ranked_terms) == ["murder", "sql city"]


def test_plan_multi_value_filter_fallback_uses_and_groups_not_global_or() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "tickets",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "status", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    payload = plan_multi_value_filter(session, "murders sql city")
    assert payload is not None
    sql = payload["suggested_sql"]
    assert payload["action"] == "request_new_query"
    assert "SELECT" in sql
    assert "FROM" in sql
    assert "WHERE" in sql
    assert "LIMIT 50" in sql
    assert " AND " in sql
    assert " OR " in sql
    assert "LOWER(CAST(status AS TEXT)) = LOWER('murder')" in sql
    assert "LOWER(CAST(city AS TEXT)) = LOWER('sql city')" in sql
    assert "LOWER(CAST(description AS TEXT)) = LOWER('murder')" in sql
    assert "LOWER(CAST(description AS TEXT)) = LOWER('sql city')" in sql
    assert "LOWER(CAST(status AS TEXT)) = LOWER('murder') OR LOWER(CAST(city AS TEXT)) = LOWER('sql city')" not in sql
    assert orchestrator.validate_select_sql_text(sql)


def test_plan_multi_value_filter_uses_case_insensitive_observed_values_across_columns() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {
        "query:q1": {
            "units": ["reports"],
            "columns": ["type", "city"],
            "rows": [("Murder", "SQL City")],
        }
    }
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "reports",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "type", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(), type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})())},
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    payload = plan_multi_value_filter(session, "murders sql city")
    assert payload is not None
    sql = payload["suggested_sql"]
    assert "LOWER(CAST(type AS TEXT)) = LOWER('Murder')" in sql
    assert "LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in sql
    assert " AND " in sql


def test_plan_filter_for_observed_value_uses_case_insensitive_observed_value() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {
        "query:q1": {
            "units": ["reports"],
            "columns": ["city"],
            "rows": [("SQL City",)],
        }
    }
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "reports",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "city", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),)},
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    payload = plan_filter_for_observed_value(session, "ver todos os registros de sql city")
    assert payload is not None
    sql = payload["suggested_sql"]
    assert "LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in sql
    assert "LOWER(CAST(city AS TEXT)) = LOWER('sql city')" not in sql


def test_plan_multi_value_filter_returns_none_when_no_safe_sql_can_be_built() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = []
    assert plan_multi_value_filter(session, "murders sql city") is None


def test_validate_generated_select_sql_returns_none_for_invalid_sql() -> None:
    assert _validate_generated_select_sql("SELECT FROM reports WHERE city = 'X' LIMIT 50") is None
    assert _validate_generated_select_sql("SELECT * FROM reports WHERE LIMIT 50") is None


def test_plan_deterministic_action_after_resolved_text_drilldown_advances_to_other_focus_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = [
        {
            "action": "request_new_query",
            "sql": "SELECT id, description FROM events WHERE type = 'murder' AND description IS NOT NULL AND TRIM(CAST(description AS TEXT)) <> '' LIMIT 50",
        }
    ]
    session._active_focus = {
        "source_requirement_id": "req_events_type_murder",
        "cache_key": "query:q_murder",
        "units": ["events"],
        "columns": ["id", "description", "city"],
        "filter": {"column": "type", "value": "murder", "operator": "="},
        "node_id": "events:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
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
                        "reason": "resolvido",
                        "role": "drilldown",
                        "parent_requirement_id": "req_events_type_murder",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "amostrar textos filtrados por type",
                            "suggested_sql": "SELECT id, description FROM events WHERE type = 'murder' AND description IS NOT NULL AND TRIM(CAST(description AS TEXT)) <> '' LIMIT 50",
                        },
                        "status": "resolved",
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
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_events_type_group_city"
    assert payload.get("_source_requirement_id") != "req_events_type_text_description"


def test_plan_filter_for_observed_value_builds_query_from_sample_entity() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "crime_scene_report",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="crime_scene_report:1",
                label="Amostra",
                unit="crime_scene_report",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                sample_entities=["city=SQL City, description=note"],
            )
        ]
    )

    payload = plan_filter_for_observed_value(session, "sim focamos em sql city")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert "WHERE LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in payload["suggested_sql"]


def test_plan_filter_for_observed_value_has_no_hardcoded_sql_city() -> None:
    planner_source = (ROOT / "src/agnostic/application/planning/rule_based_planner.py").read_text(encoding="utf-8")
    assert '"SQL City"' not in planner_source


def test_plan_deterministic_action_prioritizes_observed_value_before_active_focus_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "crime_scene_report",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "id", "position": 0, "raw_type": "INTEGER", "raw_attributes": ""})(),
                            type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "date", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session._active_focus = {
        "source_requirement_id": "req_crime_scene_report_type_murder",
        "cache_key": "query:q1",
        "units": ["crime_scene_report"],
        "columns": ["id", "city", "date", "description"],
        "filter": {"column": "type", "value": "murder", "operator": "="},
        "node_id": "crime_scene_report:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="crime_scene_report:2",
                label="Filtrado",
                unit="crime_scene_report",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                sample_entities=["city=SQL City, description=alley"],
                next_requirements=[
                    {
                        "id": "req_crime_scene_report_type_time_date",
                        "kind": "query",
                        "units": ["crime_scene_report"],
                        "description": "Agrupar por data",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_crime_scene_report_type_murder",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "agrupar dentro do filtro por período",
                            "suggested_sql": "SELECT substr(CAST(date AS TEXT), 1, 10) AS period, COUNT(*) AS total FROM crime_scene_report WHERE type = 'murder' GROUP BY period ORDER BY period LIMIT 50",
                        },
                        "status": "pending",
                        "source_node_id": "crime_scene_report:2",
                    }
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim focamos em sql city")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert "WHERE LOWER(CAST(city AS TEXT)) = LOWER('SQL City')" in payload["suggested_sql"]
    assert "period" not in payload["suggested_sql"].lower()


def test_plan_filter_for_observed_value_escapes_quotes() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
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
                            type("Column", (), {"name": "city", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:1",
                label="Amostra",
                unit="events",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                sample_entities=["city=Bob's Town"],
            )
        ]
    )

    payload = plan_filter_for_observed_value(session, "vamos focar em bob's town")
    assert payload is not None
    assert "WHERE LOWER(CAST(city AS TEXT)) = LOWER('Bob''s Town')" in payload["suggested_sql"]


def test_plan_deterministic_action_without_observed_value_keeps_previous_behavior() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._core_cache = {}
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_child_murder",
        "cache_key": "query:q_murder",
        "units": ["events"],
        "columns": ["id", "type", "city"],
        "filter": {"column": "type", "value": "murder", "operator": "="},
        "node_id": "events:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="events:2",
                label="Registros filtrados por murder",
                unit="events",
                data={},
                timestamp="2026-05-27T01:05:00+00:00",
                next_requirements=[
                    {
                        "id": "req_drilldown_city",
                        "kind": "query",
                        "units": ["events"],
                        "description": "Agrupar por city dentro do filtro",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_child_murder",
                        "suggested_action": {"action": "request_new_query", "description": "city", "suggested_sql": "SELECT city, COUNT(*) AS total FROM events WHERE type = 'murder' GROUP BY city"},
                        "status": "pending",
                        "source_node_id": "events:2",
                    }
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_drilldown_city"


def test_plan_deterministic_action_prioritizes_textual_clue_before_drilldown() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._core_cache = {}
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_last_house_northwestern_dr",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Buscar última residência em Northwestern Dr",
                        "reason": "pendente",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "buscar última casa em Northwestern Dr",
                            "suggested_sql": "SELECT * FROM people WHERE address_street_name = 'Northwestern Dr' ORDER BY address_number DESC LIMIT 1",
                        },
                        "status": "pending",
                        "source_node_id": "reports:2",
                    },
                    {
                        "id": "req_reports_city_time_date",
                        "kind": "query",
                        "units": ["reports"],
                        "description": "Agrupar por data",
                        "reason": "pendente",
                        "role": "drilldown",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "agrupar por data",
                            "suggested_sql": "SELECT substr(CAST(date AS TEXT), 1, 10) AS period, COUNT(*) AS total FROM reports WHERE city = 'SQL City' GROUP BY period ORDER BY period LIMIT 50",
                        },
                        "status": "pending",
                        "source_node_id": "reports:2",
                    },
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_reports:2_clue_last_house_northwestern_dr"


def test_focused_pending_requirements_prioritizes_pending_textual_clue_before_recent_derived_entity_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
        "clue_group_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas textuais",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_northwestern",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Primeira pista",
                        "reason": "resolvido",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "primeira pista"},
                        "status": "resolved",
                        "source_node_id": "reports:2",
                    },
                    {
                        "id": "req_reports:2_clue_annabel",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Segunda pista",
                        "reason": "pendente",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "segunda pista"},
                        "status": "pending",
                        "source_node_id": "reports:2",
                    },
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recém-encontrada",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_person_id_1",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Aprofundar entidade",
                        "reason": "pendente",
                        "suggested_action": {"action": "request_new_query", "description": "aprofundar entidade"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    focused = focused_pending_requirements(session)
    assert [req["id"] for req in focused[:2]] == ["req_reports:2_clue_annabel", "req_person_id_1"]


def test_plan_deterministic_action_prioritizes_active_clue_group_before_recent_derived_entity_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
        "clue_group_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas textuais",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_done",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista resolvida",
                        "reason": "resolvido",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "pista resolvida"},
                        "status": "resolved",
                        "source_node_id": "reports:2",
                    },
                    {
                        "id": "req_reports:2_clue_pending",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista pendente",
                        "reason": "pendente",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "pista pendente"},
                        "status": "pending",
                        "source_node_id": "reports:2",
                    },
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recém-encontrada",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_person_id_1",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Aprofundar entidade",
                        "reason": "pendente",
                        "suggested_action": {"action": "request_new_query", "description": "aprofundar entidade"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_reports:2_clue_pending"


def test_plan_deterministic_action_after_textual_clues_are_resolved_can_consume_recent_derived_entity_requirement() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
        "clue_group_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas textuais",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_done",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista resolvida",
                        "reason": "resolvido",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "pista resolvida"},
                        "status": "resolved",
                        "source_node_id": "reports:2",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recém-encontrada",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_person_id_1",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Aprofundar entidade",
                        "reason": "pendente",
                        "suggested_action": {"action": "request_new_query", "description": "aprofundar entidade"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_person_id_1"


def test_plan_deterministic_action_after_textual_clues_prefers_related_entity_before_drilldown() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
        "clue_group_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas textuais",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_done",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista resolvida",
                        "reason": "resolvido",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "pista resolvida"},
                        "status": "resolved",
                        "source_node_id": "reports:2",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recém-encontrada",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_people_text_name",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Aprofundar textos da própria entidade",
                        "reason": "pendente",
                        "role": "drilldown",
                        "suggested_action": {"action": "request_new_query", "description": "aprofundar entidade"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    },
                    {
                        "id": "req_people_related_interview_person_id_97913",
                        "kind": "query",
                        "units": ["interview"],
                        "description": "Consultar entrevista relacionada",
                        "reason": "chave observada em entidade retornada",
                        "role": "related_entity",
                        "suggested_action": {"action": "request_new_query", "description": "consultar entrevista"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    },
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "sim")
    assert payload is not None
    assert payload.get("_source_requirement_id") == "req_people_related_interview_person_id_97913"


def test_score_related_entity_requirement_prioritizes_textual_target_for_textual_intent() -> None:
    def make_unit(unit_name: str, columns: list[str]):
        return type(
            "Unit",
            (),
            {
                "unit_name": unit_name,
                "get_structure": lambda self: type(
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

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.units = [
        make_unit("witness_notes", ["person_id", "transcript", "statement"]),
        make_unit("event_log", ["person_id", "event_type", "event_timestamp"]),
        make_unit("income", ["person_id", "annual_income", "zip_code"]),
    ]
    session._execution_log = []

    textual_req = {
        "id": "req_textual",
        "role": "related_entity",
        "units": ["witness_notes"],
        "source_node_id": "people:1",
        "suggested_action": {"action": "request_new_query", "suggested_sql": "SELECT transcript FROM witness_notes WHERE person_id = 1 LIMIT 50"},
    }
    log_req = {
        "id": "req_log",
        "role": "related_entity",
        "units": ["event_log"],
        "source_node_id": "people:1",
        "suggested_action": {"action": "request_new_query", "suggested_sql": "SELECT event_type FROM event_log WHERE person_id = 1 LIMIT 50"},
    }
    numeric_req = {
        "id": "req_numeric",
        "role": "related_entity",
        "units": ["income"],
        "source_node_id": "people:1",
        "suggested_action": {"action": "request_new_query", "suggested_sql": "SELECT annual_income FROM income WHERE person_id = 1 LIMIT 50"},
    }

    assert score_related_entity_requirement(session, textual_req, "entrevistas das testemunhas") > score_related_entity_requirement(session, log_req, "entrevistas das testemunhas")
    assert score_related_entity_requirement(session, textual_req, "entrevistas das testemunhas") > score_related_entity_requirement(session, numeric_req, "entrevistas das testemunhas")


def test_plan_deterministic_action_textual_intent_uses_textual_related_entity() -> None:
    def make_unit(unit_name: str, columns: list[str]):
        return type(
            "Unit",
            (),
            {
                "unit_name": unit_name,
                "get_structure": lambda self: type(
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

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = [
        make_unit("witness_notes", ["person_id", "transcript", "statement"]),
        make_unit("event_log", ["person_id", "event_type", "event_timestamp"]),
    ]
    session._execution_log = []
    session._active_focus = None
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidades descobertas",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_log",
                        "kind": "query",
                        "role": "related_entity",
                        "units": ["event_log"],
                        "status": "pending",
                        "source_node_id": "people:3",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "consultar evento",
                            "suggested_sql": "SELECT person_id, event_type FROM event_log WHERE person_id = 97913 LIMIT 50",
                        },
                    },
                    {
                        "id": "req_textual",
                        "kind": "query",
                        "role": "related_entity",
                        "units": ["witness_notes"],
                        "status": "pending",
                        "source_node_id": "people:3",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "consultar depoimento",
                            "suggested_sql": "SELECT person_id, transcript FROM witness_notes WHERE person_id = 97913 LIMIT 50",
                        },
                    },
                ],
            )
        ]
    )

    payload = plan_deterministic_action(session, "entrevistas das testemunhas")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert payload.get("_source_requirement_id") == "req_textual"
    assert "WHERE person_id = 97913" in payload["suggested_sql"]


def test_plan_deterministic_action_textual_related_entities_progress_without_repeating() -> None:
    def make_unit(unit_name: str, columns: list[str]):
        return type(
            "Unit",
            (),
            {
                "unit_name": unit_name,
                "get_structure": lambda self: type(
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

    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = [make_unit("statements", ["person_id", "transcript"])]
    session._execution_log = []
    session._active_focus = None
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidades descobertas",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_textual_1",
                        "kind": "query",
                        "role": "related_entity",
                        "units": ["statements"],
                        "status": "pending",
                        "source_node_id": "people:3",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "consultar depoimento 1",
                            "suggested_sql": "SELECT transcript FROM statements WHERE person_id = 101 LIMIT 50",
                        },
                    },
                    {
                        "id": "req_textual_2",
                        "kind": "query",
                        "role": "related_entity",
                        "units": ["statements"],
                        "status": "pending",
                        "source_node_id": "people:3",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": "consultar depoimento 2",
                            "suggested_sql": "SELECT transcript FROM statements WHERE person_id = 202 LIMIT 50",
                        },
                    },
                ],
            )
        ]
    )

    first_payload = plan_deterministic_action(session, "entrevistas das testemunhas")
    assert first_payload is not None
    assert first_payload.get("_source_requirement_id") == "req_textual_1"

    session._execution_log.append({"action": "request_new_query", "sql": first_payload["suggested_sql"]})
    second_payload = plan_deterministic_action(session, "sim")
    assert second_payload is not None
    assert second_payload.get("_source_requirement_id") == "req_textual_2"


def test_plan_deterministic_action_textual_intent_without_textual_related_keeps_previous_behavior() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
        "clue_group_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Pistas textuais",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_reports:2_clue_done",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista resolvida",
                        "reason": "resolvido",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "pista resolvida"},
                        "status": "resolved",
                        "source_node_id": "reports:2",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="people:3",
                label="Entidade recém-encontrada",
                unit="people",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_people_related_income",
                        "kind": "query",
                        "units": ["income"],
                        "description": "Consultar renda relacionada",
                        "reason": "chave observada em entidade retornada",
                        "role": "related_entity",
                        "suggested_action": {"action": "request_new_query", "description": "consultar renda", "suggested_sql": "SELECT annual_income FROM income WHERE person_id = 97913 LIMIT 50"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    },
                    {
                        "id": "req_people_text_name",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Aprofundar textos da própria entidade",
                        "reason": "pendente",
                        "role": "drilldown",
                        "suggested_action": {"action": "request_new_query", "description": "aprofundar entidade"},
                        "status": "pending",
                        "source_node_id": "people:3",
                    },
                ],
            ),
        ]
    )

    payload = plan_deterministic_action(session, "entrevistas das testemunhas")
    assert payload is None


def test_pending_requirements_without_pending_textual_clue_can_return_recent_derived_requirement_first() -> None:
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
                        "id": "req_group_clue_done",
                        "kind": "query",
                        "role": "textual_clue",
                        "description": "Pista resolvida",
                        "status": "resolved",
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
                        "description": "Aprofundar entidade",
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    pending = graph.pending_requirements(active_focus={"clue_group_id": "reports:2"})
    assert pending
    assert pending[0]["id"] == "req_person_id_1"


def test_focused_pending_requirements_prioritizes_active_clue_group_before_other_textual_clue_groups() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session.source_path = "/data/test.db"
    session.units = []
    session._execution_log = []
    session._active_focus = {
        "source_requirement_id": "req_focus",
        "cache_key": "query:q_focus",
        "units": ["reports"],
        "columns": ["description"],
        "filter": {"column": "city", "value": "SQL City", "operator": "="},
        "node_id": "reports:2",
        "clue_group_id": "reports:2",
    }
    session.knowledge_graph = orchestrator.KnowledgeGraph(
        nodes=[
            orchestrator.KnowledgeNode(
                id="other:1",
                label="Outro grupo",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:00:00+00:00",
                next_requirements=[
                    {
                        "id": "req_other_group_clue",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Outra pista textual",
                        "reason": "pendente",
                        "role": "textual_clue",
                        "suggested_action": {"action": "request_new_query", "description": "outra pista"},
                        "status": "pending",
                        "source_node_id": "other:1",
                    }
                ],
            ),
            orchestrator.KnowledgeNode(
                id="reports:2",
                label="Grupo ativo",
                unit="reports",
                data={},
                timestamp="2026-05-28T00:01:00+00:00",
                next_requirements=[
                    {
                        "id": "req_active_group_clue",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista do grupo ativo",
                        "reason": "pendente",
                        "role": "textual_clue",
                        "parent_requirement_id": "req_focus",
                        "suggested_action": {"action": "request_new_query", "description": "pista ativa"},
                        "status": "pending",
                        "source_node_id": "reports:2",
                    }
                ],
            ),
        ]
    )

    focused = focused_pending_requirements(session)
    assert [req["id"] for req in focused[:2]] == ["req_active_group_clue", "req_other_group_clue"]


def test_first_pending_requirement_prioritizes_textual_clue_globally_before_recent_derived_requirement() -> None:
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
                        "id": "req_textual_clue_1",
                        "kind": "query",
                        "units": ["people"],
                        "description": "Pista textual pendente",
                        "reason": "pendente",
                        "role": "textual_clue",
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
                        "units": ["people"],
                        "description": "Aprofundar entidade",
                        "reason": "pendente",
                        "status": "pending",
                        "source_node_id": "people:3",
                    }
                ],
            ),
        ]
    )

    first_req = first_pending_requirement(graph)
    assert first_req is not None
    assert first_req["id"] == "req_textual_clue_1"


def test_plan_deterministic_action_direct_sample_command_returns_request_new_query() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {
        "query:q1": {
            "units": ["events"],
            "columns": ["type", "description"],
            "rows": [("murder", "alpha")],
        }
    }
    session._execution_log = []
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
                        )
                    },
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()

    payload = plan_deterministic_action(session, "amostra murders")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert "WHERE LOWER(CAST(type AS TEXT)) = LOWER('murder')" in payload["suggested_sql"]


def test_plan_direct_value_command_considers_singular_candidate() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {
        "query:q1": {
            "units": ["events"],
            "columns": ["type"],
            "rows": [("murder",)],
        }
    }
    session._execution_log = []
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "events",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {"columns": (type("Column", (), {"name": "type", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),)},
                )(),
            },
        )()
    ]
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    payload = plan_direct_value_command(session, "amostra murders")
    assert payload is not None
    assert "murder" in payload["suggested_sql"]


def test_plan_direct_value_command_uses_safe_schema_search_when_value_unobserved() -> None:
    session = orchestrator.OrchestratorSession.__new__(orchestrator.OrchestratorSession)
    session._core_cache = {}
    session._execution_log = []
    session.knowledge_graph = orchestrator.KnowledgeGraph()
    session.units = [
        type(
            "Unit",
            (),
            {
                "unit_name": "tickets",
                "get_structure": lambda self: type(
                    "Structure",
                    (),
                    {
                        "columns": (
                            type("Column", (), {"name": "status", "position": 0, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "category", "position": 1, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "description", "position": 2, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "notes", "position": 3, "raw_type": "TEXT", "raw_attributes": ""})(),
                            type("Column", (), {"name": "owner", "position": 4, "raw_type": "TEXT", "raw_attributes": ""})(),
                        )
                    },
                )(),
            },
        )()
    ]

    payload = plan_direct_value_command(session, "mostrar status ativo")
    assert payload is not None
    assert payload["action"] == "request_new_query"
    assert payload["suggested_sql"].count("CAST(") <= 4
    assert "ativo" in payload["suggested_sql"]
