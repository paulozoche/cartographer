from __future__ import annotations

from typing import Any


def build_table_signal(columns: dict[str, Any]) -> float:
    if not columns:
        return 0.0
    values = [float(getattr(column, "signal", 0.0) or 0.0) for column in columns.values()]
    return sum(values) / max(len(values), 1)


def build_table_explanation(columns: dict[str, Any]) -> str:
    if not columns:
        return ""
    ranked = sorted(
        columns.values(),
        key=lambda column: float(getattr(column, "signal", 0.0) or 0.0),
        reverse=True,
    )
    labels: list[str] = []
    for column in ranked[:3]:
        explanation = str(getattr(column, "explanation", "") or "").strip()
        if explanation:
            labels.append(explanation)
    return " + ".join(labels)


def build_table_suggested_actions(columns: dict[str, Any]) -> list[str]:
    ranked = sorted(
        columns.values(),
        key=lambda column: float(getattr(column, "signal", 0.0) or 0.0),
        reverse=True,
    )
    suggestions: dict[str, None] = {}
    for column in ranked:
        for action in tuple(getattr(column, "suggested_actions", ()) or ()):
            normalized = str(action).strip()
            if normalized:
                suggestions[normalized] = None
    return list(suggestions.keys())
