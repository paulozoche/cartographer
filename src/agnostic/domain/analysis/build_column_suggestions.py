from __future__ import annotations

from agnostic.domain.heuristics.base import HeuristicResult

_HEURISTIC_SUGGESTIONS = {
    "identifier_signal": "Investigar registros únicos ou correspondências",
    "high_cardinality_signal": "Explorar valores raros ou exceções",
    "pattern_signal": "Analisar padrões e possíveis formatos",
    "sequential_signal": "Verificar progressões ou quebras de sequência",
    "near_unique_conflict": "invesigar valores duplicados ou inconsistentes",
}


def build_column_suggestions(heuristics_results: list[HeuristicResult]) -> list[str]:
    suggestions: dict[str, None] = {}
    for heuristic in heuristics_results:
        if not heuristic.triggered:
            continue
        suggestion = _HEURISTIC_SUGGESTIONS.get(heuristic.name)
        if suggestion:
            suggestions[suggestion] = None
    return list(suggestions.keys())
