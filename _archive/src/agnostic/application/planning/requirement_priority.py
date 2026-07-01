from __future__ import annotations

from agnostic.application.planning.requirement_schema import normalize_requirement


def sort_pending_requirements_for_investigation(
    requirements: list[dict[str, object]],
    *,
    active_focus: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    if not isinstance(requirements, list):
        return []
    active_focus = active_focus or {}
    active_clue_group = str(active_focus.get("clue_group_id", "") or active_focus.get("node_id", "")).strip()
    prioritized: list[tuple[int, int, dict[str, object]]] = []
    for index, requirement in enumerate(requirements):
        requirement = normalize_requirement(requirement)
        role = str(requirement.get("role", "")).strip().lower()
        source_node_id = str(requirement.get("source_node_id", "")).strip()
        if active_clue_group and source_node_id == active_clue_group and role == "textual_clue":
            priority = 0
        elif role == "textual_clue":
            priority = 1
        elif role == "related_entity":
            priority = 2
        else:
            priority = 3
        prioritized.append((priority, index, requirement))
    return [requirement for _, _, requirement in sorted(prioritized, key=lambda item: (item[0], item[1]))]
