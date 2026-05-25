from __future__ import annotations

import math
import statistics

from agnostic.domain.analysis.analyze_tabular_unit import TabularUnitAnalysis


_HEURISTIC_LABELS = {
    "identifier_signal": "provável identificador",
    "sequential_signal": "padrão sequencial",
    "pattern_signal": "padrão repetitivo",
    "high_cardinality_signal": "alta cardinalidade",
    "near_unique_conflict": "quase único com pequena inconsistência estrutural",
}


def _format_ratio(value: float) -> str:
    return f"{value * 100:.1f}%"


def _is_numeric(value: object) -> bool:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _as_float(value: object) -> float | None:
    if not _is_numeric(value):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _pairwise_colinearity(analysis: TabularUnitAnalysis) -> list[str]:
    standardized = analysis.standardized
    column_order = list(standardized.column_order)
    if len(column_order) < 2:
        return []

    candidates: list[str] = []
    for index, left_name in enumerate(column_order):
        left_column = standardized.columns[left_name]
        left_analysis = analysis.columns[left_name]
        left_numeric_ratio = float(left_analysis.layer2_metrics.get("numeric_ratio", 0.0) or 0.0)
        for right_name in column_order[index + 1 :]:
            right_column = standardized.columns[right_name]
            right_analysis = analysis.columns[right_name]
            right_numeric_ratio = float(right_analysis.layer2_metrics.get("numeric_ratio", 0.0) or 0.0)

            if left_column == right_column and left_column:
                candidates.append(f"{left_name} ↔ {right_name} (colunas idênticas)")
                continue

            numeric_pairs: list[tuple[float, float]] = []
            if left_numeric_ratio >= 0.8 and right_numeric_ratio >= 0.8:
                for left_value, right_value in zip(left_column, right_column):
                    left_float = _as_float(left_value)
                    right_float = _as_float(right_value)
                    if left_float is None or right_float is None:
                        continue
                    numeric_pairs.append((left_float, right_float))

                if len(numeric_pairs) >= 2:
                    left_values = [pair[0] for pair in numeric_pairs]
                    right_values = [pair[1] for pair in numeric_pairs]
                    if len(set(left_values)) > 1 and len(set(right_values)) > 1:
                        coefficient = statistics.correlation(left_values, right_values)
                        if math.isfinite(coefficient) and abs(coefficient) >= 0.95:
                            candidates.append(
                                f"{left_name} ↔ {right_name} (correlação {coefficient:.2f})"
                            )
    return candidates


def _column_summary(column_name: str, analysis: TabularUnitAnalysis) -> str:
    column = analysis.columns[column_name]
    standardized = analysis.standardized
    values = standardized.columns[column_name]

    unique_ratio = float(column.layer1_metrics.get("unique_ratio", 0.0) or 0.0)
    null_ratio = float(column.layer1_metrics.get("null_ratio", 0.0) or 0.0)
    cardinality = int(column.layer1_metrics.get("cardinality", 0) or 0)
    numeric_ratio = float(column.layer2_metrics.get("numeric_ratio", 0.0) or 0.0)
    alpha_ratio = float(column.layer2_metrics.get("alpha_ratio", 0.0) or 0.0)
    spaces_ratio = float(column.layer2_metrics.get("spaces_ratio", 0.0) or 0.0)

    triggered = [
        _HEURISTIC_LABELS.get(heuristic.name, heuristic.name)
        for heuristic in column.heuristics
        if heuristic.triggered
    ]

    if triggered:
        signal_text = ", ".join(triggered)
        return (
            f"- {column_name}: {cardinality} valores distintos, "
            f"{_format_ratio(null_ratio)} nulos, sinais fortes de {signal_text}."
        )

    if numeric_ratio >= 0.7:
        profile = "predominantemente numérica"
    elif alpha_ratio >= 0.7 and spaces_ratio >= 0.1:
        profile = "predominantemente textual"
    elif unique_ratio >= 0.9 and null_ratio <= 0.05:
        profile = "boa candidata a identificador"
    else:
        profile = "perfil misto"

    sample_preview = ", ".join(repr(value) for value in values[:3])
    return (
        f"- {column_name}: {cardinality} valores distintos, "
        f"{_format_ratio(null_ratio)} nulos, {profile}, exemplo: {sample_preview}."
    )


def summarize_tabular_analysis(analysis: TabularUnitAnalysis) -> str:
    row_count = analysis.standardized.row_count
    column_count = analysis.standardized.column_count
    lines = [
        f"Unidade {analysis.unit_name}: {row_count} linhas e {column_count} colunas.",
    ]

    column_names = list(analysis.standardized.column_order)
    if not column_names:
        lines.append("Nenhuma coluna disponível para resumo.")
        return "\n".join(lines)

    lines.append("Resumo das colunas mais relevantes:")
    for column_name in column_names[:3]:
        lines.append(_column_summary(column_name, analysis))

    if len(column_names) > 3:
        remaining = len(column_names) - 3
        lines.append(f"- {remaining} colunas adicionais analisadas no resultado bruto.")

    return "\n".join(lines)


def summarize_unit_metrics(analysis: TabularUnitAnalysis) -> list[str]:
    row_count = analysis.standardized.row_count
    column_count = analysis.standardized.column_count
    columns = list(analysis.columns.values())
    triggered_columns = []
    identifier_candidates = []
    sparse_columns = []

    for column in columns:
        column_name = column.column_name
        null_ratio = float(column.layer1_metrics.get("null_ratio", 0.0) or 0.0)
        unique_ratio = float(column.layer1_metrics.get("unique_ratio", 0.0) or 0.0)
        triggered = [heuristic.name for heuristic in column.heuristics if heuristic.triggered]
        if triggered:
            triggered_columns.append(column_name)
        if unique_ratio >= 0.9 and null_ratio <= 0.05:
            identifier_candidates.append(column_name)
        if null_ratio >= 0.25:
            sparse_columns.append(column_name)

    lines = [
        f"{analysis.unit_name}: {row_count} linhas, {column_count} colunas.",
    ]
    if identifier_candidates:
        lines.append(f"Identificadores prováveis: {', '.join(identifier_candidates[:3])}.")
    if triggered_columns:
        lines.append(f"Colunas com sinais fortes: {', '.join(triggered_columns[:3])}.")
    else:
        lines.append("Nenhuma heurística forte acionada.")
    if sparse_columns:
        lines.append(f"Colunas com muitos nulos: {', '.join(sparse_columns[:3])}.")
    colinear_pairs = _pairwise_colinearity(analysis)
    if colinear_pairs:
        lines.append(f"Colinearidade potencial: {', '.join(colinear_pairs[:3])}.")
    return lines


__all__ = [
    "_HEURISTIC_LABELS",
    "_format_ratio",
    "_is_numeric",
    "_as_float",
    "_pairwise_colinearity",
    "_column_summary",
    "summarize_tabular_analysis",
    "summarize_unit_metrics",
]
