"""Build planning context from session state."""

from __future__ import annotations

from agnostic.application.planning.planning_context import PlanningContext
from agnostic.session import get_session_focus_state


def build_planning_context(session) -> PlanningContext:
    focus_state = get_session_focus_state(session)
    recent_nodes: list[dict[str, object]] = []
    graph = getattr(session, "knowledge_graph", None)
    for node in reversed(getattr(graph, "nodes", [])) if graph is not None else []:
        recent_nodes.append(
            {
                "id": str(getattr(node, "id", "")).strip(),
                "unit": str(getattr(node, "unit", "")).strip(),
                "timestamp": str(getattr(node, "timestamp", "")).strip(),
                "next_requirements": list(getattr(node, "next_requirements", []) or []),
                "sample_entities": list(getattr(node, "sample_entities", []) or []),
            }
        )
    known_entities: list[dict[str, str]] = []
    for node in recent_nodes:
        unit_name = str(node.get("unit", "")).strip()
        for entity in node.get("sample_entities", []) or []:
            if not isinstance(entity, str):
                continue
            for part in entity.split(","):
                if "=" not in part:
                    continue
                column, value = part.split("=", 1)
                column = column.strip()
                value = value.strip()
                if column and value:
                    known_entities.append({"unit": unit_name, "column": column, "value": value})
    cache = getattr(session, "_core_cache", {})
    if isinstance(cache, dict):
        for payload in cache.values():
            if not isinstance(payload, dict):
                continue
            units = payload.get("units", [])
            columns = payload.get("columns", [])
            rows = payload.get("rows", [])
            unit_name = str(units[0]).strip() if isinstance(units, list) and units else ""
            if not unit_name or not isinstance(columns, list) or not isinstance(rows, list):
                continue
            for row in rows[:20]:
                if not isinstance(row, (list, tuple)):
                    continue
                for index, column in enumerate(columns):
                    if index >= len(row):
                        continue
                    value = row[index]
                    if value is None:
                        continue
                    text_value = str(value).strip()
                    if text_value:
                        known_entities.append({"unit": unit_name, "column": str(column).strip(), "value": text_value})
    unit_columns: dict[str, list[str]] = {}
    unit_summaries: list[dict[str, object]] = []
    for unit in getattr(session, "units", []):
        unit_name = str(getattr(unit, "unit_name", "")).strip()
        if not unit_name:
            continue
        try:
            structure = unit.get_structure()
        except Exception:
            structure = None
        columns = (
            [
                str(getattr(column, "name", "")).strip()
                for column in getattr(structure, "columns", ())
                if str(getattr(column, "name", "")).strip()
            ]
            if structure is not None
            else []
        )
        unit_columns[unit_name] = columns
        row_count = None
        analysis_by_unit = getattr(session, "analysis_by_unit", {})
        analysis = analysis_by_unit.get(unit_name) if isinstance(analysis_by_unit, dict) else None
        standardized = getattr(analysis, "standardized", None) if analysis is not None else None
        if standardized is not None:
            row_count = getattr(standardized, "row_count", None)
        unit_summaries.append({"unit_name": unit_name, "row_count": row_count, "columns": list(columns)})
    select_builder = getattr(session, "_build_select_columns_for_filtered_query", None)
    pending_requirements = graph.pending_requirements(active_focus=focus_state.active_focus) if graph is not None else []
    return PlanningContext(
        pending_requirements=list(pending_requirements),
        focus_state=focus_state,
        available_units=[
            str(getattr(unit, "unit_name", "")).strip()
            for unit in getattr(session, "units", [])
            if str(getattr(unit, "unit_name", "")).strip()
        ],
        unit_summaries=unit_summaries,
        recent_nodes=recent_nodes,
        last_presented_options=list(getattr(session, "_last_presented_options", None) or []),
        known_entities=known_entities,
        execution_log=list(getattr(session, "_execution_log", []) or []),
        unit_columns=unit_columns,
        select_clause_builder=select_builder if callable(select_builder) else None,
        raw_session=session,
    )
