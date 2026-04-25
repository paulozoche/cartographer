from __future__ import annotations


def resolve_optional_limit(request_value: int | None, default_value: int | None) -> int | None:
    if request_value is None:
        return default_value
    if request_value == 0:
        return None
    return request_value


def source_summary_text(display_name: str, unit_count: int | None, unit_names: list[str]) -> str:
    count = unit_count or 0
    if not unit_names:
        return f"Fonte {display_name}: {count} unidades detectadas."
    preview = ", ".join(unit_names[:5])
    suffix = "..." if len(unit_names) > 5 else ""
    return f"Fonte {display_name}: {count} unidades detectadas. Unidades disponíveis: {preview}{suffix}"
