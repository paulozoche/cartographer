from __future__ import annotations

def _string_field(value: object, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _dict_field(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def normalize_requirement(requirement: object) -> dict[str, object]:
    if not isinstance(requirement, dict):
        return {
            "id": "",
            "kind": "",
            "role": "",
            "status": "pending",
            "source_node_id": "",
            "suggested_action": {},
            "priority_metadata": {},
        }
    normalized = dict(requirement)
    normalized["id"] = _string_field(normalized.get("id", ""))
    normalized["kind"] = _string_field(normalized.get("kind", ""))
    normalized["role"] = _string_field(normalized.get("role", ""))
    normalized["status"] = _string_field(normalized.get("status", "pending")) or "pending"
    normalized["source_node_id"] = _string_field(normalized.get("source_node_id", ""))
    normalized["suggested_action"] = _dict_field(normalized.get("suggested_action"))
    priority_metadata = _dict_field(normalized.get("priority_metadata"))
    priority_metadata.setdefault("role", normalized["role"])
    priority_metadata.setdefault("status", normalized["status"])
    priority_metadata.setdefault("source_node_id", normalized["source_node_id"])
    if "reason" in normalized:
        priority_metadata.setdefault("reason", normalized.get("reason"))
    if "units" in normalized:
        priority_metadata.setdefault("units", normalized.get("units"))
    normalized["priority_metadata"] = priority_metadata
    return normalized


def normalize_requirements(requirements: object) -> list[dict[str, object]]:
    if not isinstance(requirements, list):
        return []
    return [normalize_requirement(requirement) for requirement in requirements if isinstance(requirement, dict)]


def sanitize_requirements(requirements: object, serializer) -> list[dict[str, object]]:
    if not isinstance(requirements, list):
        return []
    sanitized: list[dict[str, object]] = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        sanitized_item = {str(key): serializer(value) for key, value in item.items()}
        sanitized.append(normalize_requirement(sanitized_item))
    return normalize_requirements(sanitized)


def classify_columns_from_structure(structure: object, analysis: object | None = None) -> dict[str, list[str]]:
    columns = [str(getattr(column, "name", "")).strip() for column in getattr(structure, "columns", ()) if str(getattr(column, "name", "")).strip()]
    return {"columns": columns}


def extract_sample_entities(columns: object, rows: object, max_entities: int = 10) -> list[str]:
    if not isinstance(columns, list) or not isinstance(rows, list):
        return []
    entities: list[str] = []
    for row in rows[:max_entities]:
        if not isinstance(row, (list, tuple)):
            continue
        parts: list[str] = []
        for index, column in enumerate(columns[:4]):
            if index >= len(row):
                continue
            value = row[index]
            if value is None or value == "":
                continue
            parts.append(f"{column}={value}")
        if parts:
            entities.append(", ".join(parts))
    return entities[:max_entities]


def build_operational_summary_for_unit(
    *,
    unit_name: str,
    structure: object,
    analysis: object | None,
    cache_key: str,
    action: str,
    depth: str | None = None,
) -> dict[str, object]:
    classified = classify_columns_from_structure(structure, analysis=analysis)
    row_count = None
    if analysis is not None:
        standardized = getattr(analysis, "standardized", None)
        row_count = getattr(standardized, "row_count", None)
    notes: list[str] = []
    return {
        "action": action,
        "status": "cached",
        "unit_name": unit_name,
        "depth": depth,
        "cache_key": cache_key,
        "operational_summary": {
            "row_count": row_count,
            "columns": classified["columns"],
            "metrics_available": analysis is not None,
            "notes": notes,
        },
        "evidence": {
            "columns": classified["columns"],
            "row_count": row_count,
        },
        "next_requirements": [],
    }


def build_operational_summary_for_query(
    *,
    action: str,
    cache_key: str,
    units: list[str],
    columns: list[str],
    rows: list[tuple[object, ...]],
    row_count_preview: int,
    truncated: bool,
    query_id: str | None = None,
) -> dict[str, object]:
    evidence = {
        "columns": columns,
        "row_count": row_count_preview,
    }
    notes = ["preview de consulta SELECT validada"]
    if truncated:
        notes.append("resultado parcial na prévia")
    payload: dict[str, object] = {
        "action": action,
        "status": "cached",
        "cache_key": cache_key,
        "units": units,
        "columns": columns,
        "row_count_preview": row_count_preview,
        "truncated": truncated,
        "operational_summary": {
            "row_count": row_count_preview,
            "columns": columns,
            "metrics_available": False,
            "notes": notes,
        },
        "evidence": evidence,
        "sample_entities": extract_sample_entities(columns, rows, max_entities=10),
        "next_requirements": [],
    }
    if query_id:
        payload["query_id"] = query_id
        payload["next_requirements"] = [
            normalize_requirement(
                {
                    "id": f"req_recall_query_{query_id}",
                    "kind": "recall",
                    "units": units,
                    "role": "",
                    "description": f"Recuperar detalhes da consulta {query_id}",
                    "reason": "resultado já calculado e cacheado",
                    "suggested_action": {"action": "recall", "key": cache_key},
                    "status": "pending",
                    "source_node_id": "",
                }
            )
        ]
    return payload


def cross_requirement_pair_key(unit_a: object, unit_b: object) -> tuple[str, str] | None:
    left = str(unit_a or "").strip()
    right = str(unit_b or "").strip()
    if not left or not right:
        return None
    return tuple(sorted((left, right)))


def is_internal_recall_requirement(requirement: object) -> bool:
    if not isinstance(requirement, dict):
        return False
    requirement_id = str(requirement.get("id", "")).strip().lower()
    description = str(requirement.get("description", "")).strip().lower()
    suggested = requirement.get("suggested_action")
    action_name = str(suggested.get("action", "")).strip().lower() if isinstance(suggested, dict) else ""
    if "recall" in requirement_id:
        return True
    if action_name == "recall":
        return True
    return "recuperar detalhes operacionais" in description
