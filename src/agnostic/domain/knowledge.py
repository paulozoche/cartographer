from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class KnowledgeNode:
    id: str
    label: str
    unit: str
    data: dict
    timestamp: str
    action: str = ""
    cache_key: str = ""
    units: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    join_keys: list[str] = field(default_factory=list)
    sample_entities: list[str] = field(default_factory=list)
    next_requirements: list[dict[str, object]] = field(default_factory=list)
    status: str = ""
    table_index: int | None = None
    column_indices: dict[str, int] = field(default_factory=dict)


@dataclass
class KnowledgeEdge:
    from_id: str
    to_id: str
    relation: str


@dataclass
class KnowledgeGraph:
    nodes: list[KnowledgeNode] = field(default_factory=list)
    edges: list[KnowledgeEdge] = field(default_factory=list)

    def to_dict(self, *, active_focus: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
            "pending_requirements": self.pending_requirements(active_focus=active_focus),
        }

    def pending_requirements(self, active_focus: dict[str, object] | None = None) -> list[dict[str, object]]:
        from agnostic.application.planning.requirement_priority import sort_pending_requirements_for_investigation
        from agnostic.application.planning.requirement_schema import normalize_requirement

        pending: list[dict[str, object]] = []
        for node in sorted(self.nodes, key=lambda node: str(node.timestamp), reverse=True):
            for requirement in node.next_requirements:
                normalized_requirement = normalize_requirement(requirement)
                if str(normalized_requirement.get("status", "")).strip().lower() != "pending":
                    continue
                pending.append(normalized_requirement)
        return sort_pending_requirements_for_investigation(pending, active_focus=active_focus)

    def mark_requirement_resolved(self, requirement_id: str) -> bool:
        for node in self.nodes:
            for requirement in node.next_requirements:
                if requirement.get("id") == requirement_id:
                    requirement["status"] = "resolved"
                    return True
        return False
