from __future__ import annotations

from agnostic.application.planning.focus_state import get_session_active_focus
from agnostic.application.planning.requirement_priority import sort_pending_requirements_for_investigation
from agnostic.application.planning.requirement_schema import (
    cross_requirement_pair_key,
    is_internal_recall_requirement,
)
from agnostic.domain.knowledge import KnowledgeGraph, KnowledgeNode


def _node_as_dict(node: KnowledgeNode | dict[str, object]) -> dict[str, object]:
    if isinstance(node, dict):
        return node
    return {
        "id": node.id,
        "unit": node.unit,
        "action": node.action,
        "status": node.status,
        "cache_key": node.cache_key,
        "units": node.units,
        "columns": node.columns,
        "join_keys": node.join_keys,
        "data": node.data,
        "sample_entities": node.sample_entities,
        "label": node.label,
    }


def render_knowledge_graph_context(graph: KnowledgeGraph | dict[str, object]) -> str:
    """Retorna representação textual do grafo para consumo por modelos (curador/orquestrador)."""
    if isinstance(graph, KnowledgeGraph):
        nodes = graph.nodes
        edges = graph.edges
        pending = graph.pending_requirements()
    else:
        raw_nodes = graph.get("nodes", [])
        raw_edges = graph.get("edges", [])
        nodes = raw_nodes if isinstance(raw_nodes, list) else []
        edges = raw_edges if isinstance(raw_edges, list) else []
        raw_pending = graph.get("pending_requirements", [])
        pending = raw_pending if isinstance(raw_pending, list) else []

    lines = ["## Grafo de Conhecimento", "", "### Nós"]
    if not nodes:
        lines.append("- Nenhum nó registrado.")
    else:
        for node in nodes:
            node_dict = _node_as_dict(node)
            cache_key = f" cache={node_dict.get('cache_key')}" if node_dict.get("cache_key") else ""
            units_list = node_dict.get("units", [])
            units = f" units={', '.join(units_list)}" if units_list else ""
            columns_list = node_dict.get("columns", [])
            columns = f" columns={', '.join(columns_list[:6])}" if columns_list else ""
            joins_list = node_dict.get("join_keys", [])
            joins = f" join_keys={', '.join(joins_list[:4])}" if joins_list else ""
            sample_entities_list = node_dict.get("sample_entities", [])
            sample_entities = ", ".join(str(item) for item in sample_entities_list[:4]) if sample_entities_list else ""
            sample_text = f" sample_entities={sample_entities}" if sample_entities else ""
            lines.append(
                f"- {node_dict.get('id', '')} [{node_dict.get('unit', '')}] "
                f"action={node_dict.get('action') or 'unknown'} status={node_dict.get('status') or ''}:"
                f"{cache_key}{units}{columns}{joins}{sample_text} :: {node_dict.get('label', '')}"
            )
    lines.extend(["", "### Arestas"])
    if not edges:
        lines.append("- Nenhuma aresta registrada.")
    else:
        for edge in edges:
            if isinstance(edge, dict):
                lines.append(f"- {edge.get('from_id', '')} -> {edge.get('relation', '')} -> {edge.get('to_id', '')}")
            else:
                lines.append(f"- {edge.from_id} -> {edge.relation} -> {edge.to_id}")
    lines.extend(["", "### Requisitos Pendentes"])
    if not pending:
        lines.append("- Nenhum requisito pendente.")
    else:
        for requirement in pending:
            if not isinstance(requirement, dict):
                continue
            units = ", ".join(str(unit) for unit in requirement.get("units", []))
            lines.append(
                f"- {requirement.get('id', '')} [{requirement.get('kind', '')}] "
                f"status={requirement.get('status', '')} units={units}: {requirement.get('description', '')}"
            )
    return "\n".join(lines)


def render_knowledge_map(context: dict[str, object]) -> str:
    """Retorna representação indentada do mapa de conhecimento para humanos."""
    graph = context.get("graph", {})
    if not isinstance(graph, dict):
        graph = {}
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []

    unit_names = context.get("unit_names", [])
    if not isinstance(unit_names, list):
        unit_names = []
    explored_units = context.get("explored_units", [])
    explored_set = set(explored_units) if isinstance(explored_units, (list, set, tuple)) else set()
    cache_keys = context.get("cache_keys", [])
    if not isinstance(cache_keys, list):
        cache_keys = []
    pending_requirements = context.get("pending_requirements", [])
    if not isinstance(pending_requirements, list):
        pending_requirements = []
    indexed_tables = context.get("indexed_tables", [])
    if not isinstance(indexed_tables, list):
        indexed_tables = []
    active_focus = context.get("active_focus")
    if not isinstance(active_focus, dict):
        active_focus = None

    lines = ["## Mapa do Conhecimento", "", "### Achados"]
    if not nodes:
        if not indexed_tables:
            return "Nenhuma fonte carregada."
        lines.append("- Nenhuma tabela explorada ainda.")
        lines.append("")
        lines.append("Unidades disponíveis:")
        for table in indexed_tables:
            if not isinstance(table, dict):
                continue
            lines.append(f"{table.get('index')}. {table.get('name')}")
        lines.append("Escolha pelo número para começar.")
    else:
        children_by_parent: dict[str, list[dict[str, object]]] = {}
        child_ids: set[str] = set()
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            from_id = str(edge.get("from_id", "")).strip()
            children_by_parent.setdefault(from_id, []).append(edge)
            child_ids.add(str(edge.get("to_id", "")).strip())
        node_by_id = {
            str(node.get("id", "")).strip(): node
            for node in nodes
            if isinstance(node, dict) and str(node.get("id", "")).strip()
        }
        root_nodes = [
            node
            for node in nodes
            if isinstance(node, dict) and str(node.get("id", "")).strip() not in child_ids
        ]
        visited: set[str] = set()
        for node in root_nodes:
            _append_knowledge_lines(
                lines,
                node=node,
                node_by_id=node_by_id,
                children_by_parent=children_by_parent,
                indent="",
                visited=visited,
                nodes=nodes,
                active_focus=active_focus,
            )
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id", "")).strip()
            if node_id not in visited:
                _append_knowledge_lines(
                    lines,
                    node=node,
                    node_by_id=node_by_id,
                    children_by_parent=children_by_parent,
                    indent="",
                    visited=visited,
                    nodes=nodes,
                    active_focus=active_focus,
                )

    lines.extend(["", "### Caminhos não explorados"])
    unexplored_units = [str(name) for name in unit_names if str(name) not in explored_set]
    if not unexplored_units:
        lines.append("- Nenhum caminho pendente nas unidades já descobertas.")
    else:
        for unit_name in unexplored_units:
            lines.append(f"- {unit_name}: não analisado")
    lines.extend(["", "### Cache Keys"])
    if not cache_keys:
        lines.append("- Nenhum cache registrado.")
    else:
        for cache_key in cache_keys:
            lines.append(f"- {cache_key}")
    lines.extend(["", "### Próximos Requisitos"])
    if not pending_requirements:
        lines.append("- Nenhum requisito pendente.")
    else:
        for requirement in pending_requirements:
            if not isinstance(requirement, dict):
                continue
            lines.append(
                f"- {requirement.get('id', '')}: {requirement.get('description', '')} [{requirement.get('status', '')}]"
            )
    return "\n".join(lines)


def _append_knowledge_lines(
    lines: list[str],
    *,
    node: dict[str, object],
    node_by_id: dict[str, dict[str, object]],
    children_by_parent: dict[str, list[dict[str, object]]],
    indent: str,
    visited: set[str],
    nodes: list[object],
    active_focus: dict[str, object] | None,
) -> None:
    node_id = str(node.get("id", "")).strip()
    if not node_id or node_id in visited:
        return
    visited.add(node_id)
    lines.append(f"{indent}- [{node.get('unit', '')}] {node.get('label', '')}")
    resolved_ids = {
        str(requirement.get("id", "")).strip()
        for graph_node in nodes
        if isinstance(graph_node, dict)
        for requirement in graph_node.get("next_requirements", []) or []
        if isinstance(requirement, dict)
        and str(requirement.get("status", "")).strip() == "resolved"
        and str(requirement.get("id", "")).strip()
    }
    raw_requirements = node.get("next_requirements", [])
    requirements = list(raw_requirements) if isinstance(raw_requirements, list) else []
    ordered_requirements = sort_pending_requirements_for_investigation(
        [item for item in requirements if isinstance(item, dict)],
        active_focus=active_focus,
    )
    visible_requirement_ids: set[str] = set()
    visible_cross_pairs: set[tuple[str, str]] = set()
    for requirement in ordered_requirements:
        if is_internal_recall_requirement(requirement):
            continue
        requirement_id = str(requirement.get("id", "")).strip()
        if (
            requirement_id
            and requirement_id in resolved_ids
            and str(requirement.get("status", "")).strip() != "resolved"
        ):
            continue
        if requirement_id and requirement_id in visible_requirement_ids:
            continue
        suggested = requirement.get("suggested_action")
        if isinstance(suggested, dict) and str(suggested.get("action", "")).strip() == "analyze_horizontal":
            pair_key = cross_requirement_pair_key(suggested.get("unit_a"), suggested.get("unit_b"))
            if pair_key is not None and pair_key in visible_cross_pairs:
                continue
            if pair_key is not None:
                visible_cross_pairs.add(pair_key)
        if requirement_id:
            visible_requirement_ids.add(requirement_id)
        lines.append(
            f"{indent}  - req {requirement.get('id', '')} [{requirement.get('status', '')}] {requirement.get('description', '')}"
        )
    for edge in children_by_parent.get(node_id, []):
        child = node_by_id.get(str(edge.get("to_id", "")).strip())
        if child is None:
            continue
        lines.append(
            f"{indent}  -> {edge.get('relation', '')} -> [{child.get('unit', '')}] {child.get('label', '')}"
        )
        _append_knowledge_lines(
            lines,
            node=child,
            node_by_id=node_by_id,
            children_by_parent=children_by_parent,
            indent=f"{indent}    ",
            visited=visited,
            nodes=nodes,
            active_focus=active_focus,
        )


def build_knowledge_map_context(session: object) -> dict[str, object]:
    """Monta contexto estruturado para renderização do mapa a partir da sessão."""
    graph = getattr(session, "knowledge_graph", None)
    graph_dict = graph.to_dict(active_focus=get_session_active_focus(session)) if graph is not None else {
        "nodes": [],
        "edges": [],
        "pending_requirements": [],
    }
    ensure_index_registry = getattr(session, "_ensure_index_registry", None)
    indexed_tables: list[dict[str, object]] = []
    if callable(ensure_index_registry):
        registry = ensure_index_registry()
        indexed_tables = [
            {"index": entity.index, "name": entity.name}
            for entity in registry.indexed_tables()
        ]
    explored_units_fn = getattr(session, "_explored_units_for_map", None)
    explored_units = sorted(explored_units_fn()) if callable(explored_units_fn) else []
    available_cache_keys = getattr(session, "available_cache_keys", None)
    cache_keys = list(available_cache_keys()) if callable(available_cache_keys) else []
    pending_requirements_fn = getattr(session, "pending_requirements", None)
    pending_requirements = []
    if callable(pending_requirements_fn):
        pending_requirements = [
            requirement
            for requirement in pending_requirements_fn()
            if not is_internal_recall_requirement(requirement)
        ]
    units = getattr(session, "units", [])
    unit_names = [str(getattr(unit, "unit_name", "")).strip() for unit in units if str(getattr(unit, "unit_name", "")).strip()]
    return {
        "graph": graph_dict,
        "unit_names": unit_names,
        "explored_units": explored_units,
        "cache_keys": cache_keys,
        "pending_requirements": pending_requirements,
        "indexed_tables": indexed_tables,
        "active_focus": get_session_active_focus(session),
    }
