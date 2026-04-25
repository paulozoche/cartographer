from __future__ import annotations


def build_ranked_unit(
    *,
    unit_type: str,
    name: str,
    signal: float,
    explanation: str,
    suggested_actions: list[str],
) -> dict[str, object]:
    return {
        "type": unit_type,
        "name": name,
        "signal": float(signal),
        "explanation": explanation,
        "suggested_actions": list(dict.fromkeys(suggested_actions)),
    }
