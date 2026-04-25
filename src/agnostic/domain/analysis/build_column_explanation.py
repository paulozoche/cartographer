from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult

_HEURISTIC_LABELS = {
    "identifier_signal": "Identificador provável",
    "high_cardinality_signal": "Alta cardinalidade",
    "pattern_signal": "Padrão consistente",
    "sequential_signal": "Sequência detectada",
    "near_unique_conflict": "quase único com pequena inconsistência estrutural",
}


def build_column_explanation(heuristics_results: list[HeuristicResult]) -> str:
    labels: list[str] = []
    for heuristic in heuristics_results:
        if not heuristic.triggered:
            continue
        label = _HEURISTIC_LABELS.get(heuristic.name)
        if label:
            labels.append(label)
    return " + ".join(labels)
