from __future__ import annotations

import sys
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_PATH / "src"))

from agnostic.config import load_app_config
from agnostic.domain.analysis.analyze_tabular_unit import TabularUnitAnalysis, analyze_tabular_unit
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.presentation.summaries.summarize_tabular_analysis import (
    _column_summary,
    compute_numeric_correlations,
    summarize_tabular_analysis,
    summarize_unit_metrics,
)


class CoreService:
    def __init__(self, source_path: str) -> None:
        self._init_from_source(SQLiteDataSource(source_path))

    @classmethod
    def from_source(cls, source: SQLiteDataSource) -> CoreService:
        instance = cls.__new__(cls)
        instance._init_from_source(source)
        return instance

    def _init_from_source(self, source: SQLiteDataSource) -> None:
        self._source = source
        self._units = self._source.list_units()
        config = load_app_config()
        self._max_rows = config.analysis.max_rows_per_unit
        self._cache: dict[str, object] = {}
        self._analysis_by_unit: dict[str, TabularUnitAnalysis] = {}

    @property
    def unit_names(self) -> list[str]:
        return [unit.unit_name for unit in self._units]

    def analyze_unit(self, unit_name: str) -> dict[str, object]:
        cache_key = f"unit:{unit_name}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        unit = next((item for item in self._units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        analysis = analyze_tabular_unit(unit, max_rows=self._max_rows)

        numeric_ratio_by_column = {
            str(column_name): float(
                analysis.columns[str(column_name)].layer2_metrics.get("numeric_ratio", 0.0) or 0.0
            )
            for column_name in analysis.standardized.column_order
        }
        correlations = compute_numeric_correlations(
            analysis.standardized,
            numeric_ratio_by_column,
        )

        payload: dict[str, object] = {
            "cache_key": cache_key,
            "unit_name": unit_name,
            "summary": summarize_tabular_analysis(analysis),
            "metrics_summary": summarize_unit_metrics(analysis, correlations),
            "correlations": correlations,
        }
        self._analysis_by_unit[unit_name] = analysis
        self._cache[cache_key] = payload
        return payload

    def _resolve_column_name(self, unit_name: str, column_key: str) -> str:
        unit = next((item for item in self._units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        requested = column_key.strip()
        if not requested:
            raise ValueError("Nome da coluna vazio.")

        structure = unit.get_structure()
        columns = [
            str(getattr(column, "name", "")).strip()
            for column in getattr(structure, "columns", ())
            if str(getattr(column, "name", "")).strip()
        ]
        if requested in columns:
            return requested

        requested_lower = requested.lower()
        case_insensitive = [name for name in columns if name.lower() == requested_lower]
        if len(case_insensitive) == 1:
            return case_insensitive[0]
        if len(case_insensitive) > 1:
            raise ValueError(f"Coluna ambígua: {requested}")

        raise ValueError(f"Coluna não encontrada em {unit_name}: {requested}")

    @staticmethod
    def _serialize_heuristics(column: object) -> list[dict[str, object]]:
        heuristics = getattr(column, "heuristics", ()) or ()
        serialized: list[dict[str, object]] = []
        for heuristic in heuristics:
            serialized.append(
                {
                    "name": getattr(heuristic, "name", ""),
                    "triggered": bool(getattr(heuristic, "triggered", False)),
                    "score": float(getattr(heuristic, "score", 0.0) or 0.0),
                    "evidence": dict(getattr(heuristic, "evidence", {}) or {}),
                }
            )
        return serialized

    @staticmethod
    def _top_values_from_frequency(frequency_metric: object, *, limit: int = 10) -> list[dict[str, object]]:
        counts = getattr(frequency_metric, "counts", None)
        if not isinstance(counts, dict) or not counts:
            return []
        ranked = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))
        return [
            {"value": value, "count": int(count)}
            for value, count in ranked[:limit]
        ]

    def _ensure_unit_analysis(self, unit_name: str) -> TabularUnitAnalysis:
        cached = self._analysis_by_unit.get(unit_name)
        if cached is not None:
            return cached
        self.analyze_unit(unit_name)
        cached = self._analysis_by_unit.get(unit_name)
        if cached is None:
            raise ValueError(f"Falha ao analisar unidade: {unit_name}")
        return cached

    def analyze_vertical(self, unit_name: str, depth: str, column_key: str) -> dict[str, object]:
        normalized_depth = depth.strip().lower()
        valid_depths = {"layer1", "layer2", "heuristics", "full"}
        if normalized_depth not in valid_depths:
            raise ValueError(f"Profundidade vertical inválida: {depth}")

        column_name = self._resolve_column_name(unit_name, column_key)
        analysis = self._ensure_unit_analysis(unit_name)
        column = analysis.columns.get(column_name)
        if column is None:
            raise ValueError(f"Coluna não encontrada em {unit_name}: {column_name}")

        cache_key = f"vertical:{unit_name}:{column_name}:{normalized_depth}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        layer1_metrics = dict(column.layer1_metrics)
        layer2_metrics = dict(column.layer2_metrics)
        top_values = self._top_values_from_frequency(layer1_metrics.get("frequency"))

        payload: dict[str, object] = {
            "action": "analyze_vertical",
            "cache_key": cache_key,
            "unit_name": unit_name,
            "column": column_name,
            "depth": normalized_depth,
            "summary": _column_summary(column_name, analysis).lstrip("- ").strip(),
            "layer1_metrics": layer1_metrics,
            "layer2_metrics": layer2_metrics,
            "heuristics": self._serialize_heuristics(column),
            "top_values": top_values,
            "signal": float(getattr(column, "signal", 0.0) or 0.0),
            "explanation": str(getattr(column, "explanation", "") or ""),
        }
        self._cache[cache_key] = payload
        return payload

    def analyze_horizontal(self, unit_a: str, unit_b: str) -> dict[str, str]:
        return {
            "status": "not implemented",
            "unit_a": unit_a,
            "unit_b": unit_b,
        }

    def recall(self, cache_key: str) -> object:
        if cache_key not in self._cache:
            raise KeyError(f"Chave de cache não encontrada: {cache_key}")
        return self._cache[cache_key]
