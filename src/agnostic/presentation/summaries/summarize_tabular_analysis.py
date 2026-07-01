from __future__ import annotations

import math
import statistics

from agnostic.domain.analysis.analyze_tabular_unit import TabularUnitAnalysis
from agnostic.domain.models.tabular import StandardizedTabularUnit


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


def _correlation_to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def compute_numeric_correlations(
    standardized: StandardizedTabularUnit,
    numeric_ratio_by_column: dict[str, float],
    *,
    threshold: float = 0.95,
) -> list[dict[str, object]]:
    """Single-pass pairwise Pearson correlation over the dataset.

    This is the one place that walks the full standardized columns to compute
    correlations. Both the orchestrator's ``_compute_column_correlations`` and
    the presentation's ``_pairwise_colinearity`` reuse this output instead of
    recomputing correlations over the entire dataset.

    Only numeric columns (``numeric_ratio >= 0.8``) are considered. A pair is
    returned when it has at least 2 aligned numeric points, the coefficient is
    finite, and ``abs(coefficient) >= threshold``. The ``pair_count`` is exposed
    so each consumer can apply its own minimum (the orchestrator requires >= 3,
    the colinearity summary requires >= 2), preserving prior behaviour while
    avoiding a second full traversal.
    """

    column_order = standardized.column_order or tuple(standardized.columns.keys())
    numeric_columns = [
        str(column_name)
        for column_name in column_order
        if float(numeric_ratio_by_column.get(str(column_name), 0.0) or 0.0) >= 0.8
    ]
    if len(numeric_columns) < 2:
        return []

    correlations: list[dict[str, object]] = []
    for index, column_a in enumerate(numeric_columns):
        series_a = standardized.columns.get(column_a)
        for column_b in numeric_columns[index + 1 :]:
            series_b = standardized.columns.get(column_b)
            if not series_a or not series_b:
                continue
            xs: list[float] = []
            ys: list[float] = []
            for left, right in zip(series_a, series_b):
                converted_left = _correlation_to_float(left)
                converted_right = _correlation_to_float(right)
                if converted_left is not None and converted_right is not None:
                    xs.append(converted_left)
                    ys.append(converted_right)
            if len(xs) < 2:
                continue
            try:
                coefficient = float(statistics.correlation(xs, ys))
            except statistics.StatisticsError:
                continue
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if not math.isfinite(coefficient) or abs(coefficient) < threshold:
                continue
            strength = "strong_positive" if coefficient >= threshold else "strong_negative"
            correlations.append(
                {
                    "column_a": column_a,
                    "column_b": column_b,
                    "correlation": coefficient,
                    "strength": strength,
                    "pair_count": len(xs),
                }
            )
    return correlations


def _pairwise_colinearity(
    analysis: TabularUnitAnalysis,
    precomputed_correlations: list[dict[str, object]] | None = None,
) -> list[str]:
    standardized = analysis.standardized
    column_order = list(standardized.column_order)
    if len(column_order) < 2:
        return []

    if precomputed_correlations is None:
        numeric_ratio_by_column = {
            name: float(analysis.columns[name].layer2_metrics.get("numeric_ratio", 0.0) or 0.0)
            for name in column_order
        }
        precomputed_correlations = compute_numeric_correlations(standardized, numeric_ratio_by_column)

    correlation_by_pair = {
        (str(item.get("column_a")), str(item.get("column_b"))): item
        for item in precomputed_correlations
        if isinstance(item, dict)
    }

    candidates: list[str] = []
    for index, left_name in enumerate(column_order):
        left_column = standardized.columns[left_name]
        for right_name in column_order[index + 1 :]:
            right_column = standardized.columns[right_name]

            if left_column == right_column and left_column:
                candidates.append(f"{left_name} ↔ {right_name} (colunas idênticas)")
                continue

            entry = correlation_by_pair.get((left_name, right_name))
            if entry is None:
                continue
            try:
                pair_count = int(entry.get("pair_count", 0))
            except (TypeError, ValueError):
                pair_count = 0
            if pair_count < 2:
                continue
            coefficient = entry.get("correlation")
            if not isinstance(coefficient, (int, float)) or not math.isfinite(float(coefficient)):
                continue
            candidates.append(f"{left_name} ↔ {right_name} (correlação {float(coefficient):.2f})")
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


def summarize_unit_metrics(
    analysis: TabularUnitAnalysis,
    precomputed_correlations: list[dict[str, object]] | None = None,
) -> list[str]:
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
    colinear_pairs = _pairwise_colinearity(analysis, precomputed_correlations)
    if colinear_pairs:
        lines.append(f"Colinearidade potencial: {', '.join(colinear_pairs[:3])}.")
    return lines


__all__ = [
    "_HEURISTIC_LABELS",
    "_format_ratio",
    "_is_numeric",
    "_as_float",
    "_correlation_to_float",
    "compute_numeric_correlations",
    "_pairwise_colinearity",
    "_column_summary",
    "summarize_tabular_analysis",
    "summarize_unit_metrics",
]
