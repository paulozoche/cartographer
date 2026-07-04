from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_PATH))
sys.path.insert(0, str(ROOT_PATH / "src"))

from agnostic.config import load_app_config
from agnostic.domain.analysis.analyze_tabular_unit import (
    ColumnAnalysis,
    TabularUnitAnalysis,
    analyze_tabular_unit,
)
from agnostic.domain.heuristics.base import HeuristicResult
from agnostic.domain.models.tabular import ColumnStructure, UnitMetadata, UnitStructure
from agnostic.domain.normalization.structural_pattern import StructuralPattern
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.presentation.summaries.summarize_tabular_analysis import (
    compute_numeric_correlations,
    summarize_tabular_analysis,
    summarize_unit_metrics,
)
from core_api.analysis_id import (
    AnalysisIdFields,
    build_analysis_id,
    calcular_custo,
    dataset_hash_from_fingerprint,
    sanitize_id_field,
)
from cache.cache_manager import CacheManager


class CoreService:
    def __init__(
        self,
        source_path: str,
        *,
        cache_manager: CacheManager | None = None,
    ) -> None:
        self._init_from_source(SQLiteDataSource(source_path), cache_manager=cache_manager)

    @classmethod
    def from_source(
        cls,
        source: SQLiteDataSource,
        *,
        cache_manager: CacheManager | None = None,
    ) -> CoreService:
        instance = cls.__new__(cls)
        instance._init_from_source(source, cache_manager=cache_manager)
        return instance

    def _init_from_source(
        self,
        source: SQLiteDataSource,
        *,
        cache_manager: CacheManager | None = None,
    ) -> None:
        self._source = source
        self._units = self._source.list_units()
        config = load_app_config()
        self._max_rows = config.analysis.max_rows_per_unit
        self.cache_manager = cache_manager or CacheManager.from_env()
        self._analysis_by_unit: dict[str, TabularUnitAnalysis] = {}
        self._session_id = ""
        self._usuario = "anonimo"
        self._ultimo_id = ""
        self._dataset_hash = self._get_dataset_hash()

    def bind_session(self, session_id: str, *, usuario: str = "anonimo") -> None:
        self._session_id = session_id
        self._usuario = usuario

    @property
    def unit_names(self) -> list[str]:
        return [unit.unit_name for unit in self._units]

    def _get_dataset_hash(self) -> str:
        try:
            fingerprint = self._source.get_metadata().fingerprint
            return dataset_hash_from_fingerprint(fingerprint)
        except (FileNotFoundError, OSError):
            identifier = getattr(self._source, "_db_path", "") or self._source.display_name
            return dataset_hash_from_fingerprint(f"sha256:{identifier}")

    @staticmethod
    def _calcular_custo(
        method: str,
        *,
        linhas: int = 0,
        colunas: int = 0,
    ) -> float:
        return calcular_custo(method, linhas=linhas, colunas=colunas)

    def _short_session_id(self) -> str:
        raw = self._session_id or "local"
        return raw.replace("-", "")[:8]

    def _generate_cache_key(
        self,
        *,
        analysis_type: str,
        origem: str,
        method: str,
        alvo: str = "",
        profundidade: str = "",
        contexto: str = "",
        intencao: str = "",
        importancia: str = "normal",
        ramo: str = "",
        acessos: int = 0,
        linhas: int = 0,
        colunas: int = 0,
        cost_method: str | None = None,
        parent_id: str = "",
    ) -> str:
        custo = self._calcular_custo(
            cost_method or method,
            linhas=linhas,
            colunas=colunas,
        )
        return build_analysis_id(
            AnalysisIdFields(
                namespace="cartographer",
                usuario=self._usuario,
                intencao=intencao,
                tipo=analysis_type,
                sessao=self._short_session_id(),
                dataset_hash=self._dataset_hash,
                origem=origem,
                alvo=alvo,
                profundidade=profundidade,
                contexto=contexto,
                method=method,
                importancia=importancia,
                ramo=ramo,
                acessos=acessos,
                custo=custo,
                parent_id=sanitize_id_field(parent_id),
            ),
            stable=True,
        )

    def _touch_ultimo_id(self, cache_key: str) -> None:
        self._ultimo_id = cache_key

    def _cache_session_id(self) -> str:
        return self._session_id or "local"

    def _get_cache(self, cache_key: str) -> object | None:
        return self.cache_manager.get(self._cache_session_id(), cache_key)

    def _set_cache(self, cache_key: str, value: object) -> None:
        self.cache_manager.set(self._cache_session_id(), cache_key, value)

    def _get_cached_payload(self, cache_key: str) -> dict[str, object] | None:
        cached = self._get_cache(cache_key)
        if cached is None:
            return None
        payload = cached  # type: ignore[assignment]
        self._touch_ultimo_id(cache_key)
        return payload

    def _store_payload(self, cache_key: str, payload: dict[str, object]) -> None:
        payload["cache_key"] = cache_key
        self._set_cache(cache_key, payload)
        self._touch_ultimo_id(cache_key)

    def _unit_row_and_column_counts(self, unit_name: str) -> tuple[int, int]:
        unit = next((item for item in self._units if item.unit_name == unit_name), None)
        if unit is None:
            return 0, 0
        metadata = unit.get_metadata()
        structure = unit.get_structure()
        row_count = metadata.row_count if metadata.row_count is not None else 0
        return int(row_count), len(structure.columns)

    def _unit_analysis_cache_key(self, unit_name: str) -> str:
        row_count, column_count = self._unit_row_and_column_counts(unit_name)
        return self._generate_cache_key(
            analysis_type="unit",
            origem=unit_name,
            profundidade="full",
            method="full",
            linhas=row_count,
            colunas=column_count,
            cost_method="analyze_unit",
        )

    def analyze_unit(self, unit_name: str) -> dict[str, object]:
        unit = next((item for item in self._units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        cache_key = self._unit_analysis_cache_key(unit_name)

        cached = self._get_cached_payload(cache_key)
        if cached is not None:
            return cached

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
            "row_count": analysis.standardized.row_count,
            "column_count": analysis.standardized.column_count,
            "columns": {
                column_name: self._serialize_column_analysis(column)
                for column_name, column in analysis.columns.items()
            },
        }
        self._analysis_by_unit[unit_name] = analysis
        self._store_payload(cache_key, payload)
        return payload

    def _get_cached_unit(self, unit_name: str) -> dict[str, object] | None:
        memory = self._analysis_by_unit.get(unit_name)
        if memory is not None:
            return {
                "source": "memory",
                "unit_name": unit_name,
                "row_count": memory.standardized.row_count,
                "column_count": memory.standardized.column_count,
                "columns": {
                    name: self._serialize_column_analysis(column)
                    for name, column in memory.columns.items()
                },
            }

        cache_key = self._unit_analysis_cache_key(unit_name)
        cached = self._get_cache(cache_key)
        if isinstance(cached, dict) and isinstance(cached.get("columns"), dict):
            return {
                "source": "cache",
                "unit_name": unit_name,
                "row_count": cached.get("row_count", 0),
                "column_count": cached.get("column_count", 0),
                "columns": cached["columns"],
                "cache_key": cache_key,
            }
        return None

    def _load_unit_from_source(self, unit_name: str) -> TabularUnitAnalysis:
        unit = next((item for item in self._units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        analysis = analyze_tabular_unit(unit, max_rows=self._max_rows)
        self._analysis_by_unit[unit_name] = analysis
        return analysis

    @staticmethod
    def _summary_from_cached_column(column_name: str, column_data: dict[str, object]) -> str:
        layer1_metrics = column_data.get("layer1_metrics", {})
        layer2_metrics = column_data.get("layer2_metrics", {})
        if not isinstance(layer1_metrics, dict):
            layer1_metrics = {}
        if not isinstance(layer2_metrics, dict):
            layer2_metrics = {}

        cardinality = int(layer1_metrics.get("cardinality", 0) or 0)
        null_ratio = float(layer1_metrics.get("null_ratio", 0.0) or 0.0)
        numeric_ratio = float(layer2_metrics.get("numeric_ratio", 0.0) or 0.0)
        profile = "predominantemente numérica" if numeric_ratio >= 0.7 else "perfil misto"
        return (
            f"{column_name}: {cardinality} valores distintos, "
            f"{null_ratio:.0%} nulos, {profile}."
        )

    def _calculate_column_from_unit(
        self,
        unit_data: dict[str, object],
        column_name: str,
        depth: str,
        *,
        cache_key: str,
        unit_name: str,
    ) -> dict[str, object]:
        columns = unit_data.get("columns")
        if not isinstance(columns, dict):
            raise ValueError(f"Dados de unidade inválidos no cache: {unit_name}")

        column_data = columns.get(column_name)
        if not isinstance(column_data, dict):
            raise ValueError(f"Coluna não encontrada em {unit_name}: {column_name}")

        layer1_metrics = dict(column_data.get("layer1_metrics", {}))  # type: ignore[arg-type]
        layer2_metrics = dict(column_data.get("layer2_metrics", {}))  # type: ignore[arg-type]
        top_values = self._top_values_from_frequency(layer1_metrics.get("frequency"))
        explanation = str(column_data.get("explanation", "") or "")
        summary = explanation or self._summary_from_cached_column(column_name, column_data)

        return {
            "action": "analyze_vertical",
            "cache_key": cache_key,
            "unit_name": unit_name,
            "column": column_name,
            "depth": depth,
            "summary": summary,
            "layer1_metrics": layer1_metrics,
            "layer2_metrics": layer2_metrics,
            "heuristics": list(column_data.get("heuristics", [])),
            "top_values": top_values,
            "signal": float(column_data.get("signal", 0.0) or 0.0),
            "explanation": explanation,
            "reused_unit_cache": True,
        }

    def _calculate_cross_from_units(
        self,
        unit_a_data: dict[str, object],
        unit_b_data: dict[str, object],
        *,
        cache_key: str,
        unit_a: str,
        unit_b: str,
    ) -> dict[str, object]:
        return {
            "status": "not implemented",
            "unit_a": unit_a,
            "unit_b": unit_b,
            "cache_key": cache_key,
            "reused_unit_cache": True,
            "unit_a_row_count": unit_a_data.get("row_count"),
            "unit_b_row_count": unit_b_data.get("row_count"),
        }

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
    def _serialize_core_value(value: object) -> object:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return {
                field.name: CoreService._serialize_core_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            }
        if isinstance(value, dict):
            return {
                (key if isinstance(key, str) else str(key)): CoreService._serialize_core_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [CoreService._serialize_core_value(item) for item in value]
        return str(value)

    @staticmethod
    def _serialize_heuristic(heuristic: HeuristicResult) -> dict[str, object]:
        return {
            "name": heuristic.name,
            "triggered": heuristic.triggered,
            "score": float(heuristic.score),
            "evidence": CoreService._serialize_core_value(dict(heuristic.evidence)),
            "metadata": CoreService._serialize_core_value(dict(heuristic.metadata)),
        }

    @staticmethod
    def _serialize_heuristics(column: ColumnAnalysis | object) -> list[dict[str, object]]:
        heuristics = getattr(column, "heuristics", ()) or ()
        return [CoreService._serialize_heuristic(heuristic) for heuristic in heuristics]

    @staticmethod
    def _serialize_structural_pattern(pattern: StructuralPattern) -> dict[str, object]:
        return {
            "pattern_id": pattern.pattern_id,
            "regex": pattern.regex,
            "confidence": float(pattern.confidence),
            "raw_type_hint": pattern.raw_type_hint,
            "sample": pattern.sample,
        }

    @staticmethod
    def _serialize_layer1_metrics(metrics: dict[str, object]) -> dict[str, object]:
        return {
            str(name): CoreService._serialize_core_value(value)
            for name, value in metrics.items()
        }

    @staticmethod
    def _serialize_layer2_metrics(metrics: dict[str, float]) -> dict[str, float]:
        return {str(name): float(value) for name, value in metrics.items()}

    @staticmethod
    def _serialize_column_structure(column: ColumnStructure) -> dict[str, object]:
        return {
            "name": column.name,
            "position": column.position,
            "raw_type": column.raw_type,
            "raw_attributes": CoreService._serialize_core_value(dict(column.raw_attributes)),
        }

    @staticmethod
    def _serialize_unit_structure(structure: UnitStructure) -> dict[str, object]:
        return {
            "unit_name": structure.unit_name,
            "columns": [
                CoreService._serialize_column_structure(column)
                for column in structure.columns
            ],
            "raw_attributes": CoreService._serialize_core_value(dict(structure.raw_attributes)),
        }

    @staticmethod
    def _serialize_unit_metadata(metadata: UnitMetadata) -> dict[str, object]:
        return {
            "unit_name": metadata.unit_name,
            "source_unit_identifier": metadata.source_unit_identifier,
            "row_count": metadata.row_count,
            "raw_attributes": CoreService._serialize_core_value(dict(metadata.raw_attributes)),
        }

    @classmethod
    def _serialize_column_analysis(cls, column: ColumnAnalysis) -> dict[str, object]:
        return {
            "type": column.type,
            "name": column.name,
            "column_name": column.column_name,
            "signal": float(column.signal),
            "exploration_score": float(column.exploration_score),
            "consistency_score": float(column.consistency_score),
            "explanation": column.explanation,
            "suggested_actions": list(column.suggested_actions),
            "layer1_metrics": cls._serialize_layer1_metrics(column.layer1_metrics),
            "layer2_metrics": cls._serialize_layer2_metrics(column.layer2_metrics),
            "heuristics": cls._serialize_heuristics(column),
            "structural_pattern": cls._serialize_structural_pattern(column.structural_pattern),
        }

    @classmethod
    def _serialize_tabular_unit_analysis(cls, analysis: TabularUnitAnalysis) -> dict[str, object]:
        return {
            "unit_name": analysis.unit_name,
            "type": analysis.type,
            "name": analysis.name,
            "signal": float(analysis.signal),
            "explanation": analysis.explanation,
            "suggested_actions": list(analysis.suggested_actions),
            "metadata": cls._serialize_unit_metadata(analysis.metadata),
            "structure": cls._serialize_unit_structure(analysis.structure),
            "row_count": analysis.standardized.row_count,
            "column_count": analysis.standardized.column_count,
            "columns": {
                column_name: cls._serialize_column_analysis(column)
                for column_name, column in analysis.columns.items()
            },
            "ranked_units": [
                cls._serialize_core_value(dict(ranked_unit))
                for ranked_unit in analysis.ranked_units
            ],
        }

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

        if self._get_cached_unit(unit_name) is None:
            self.analyze_unit(unit_name)

        cached = self._analysis_by_unit.get(unit_name)
        if cached is not None:
            return cached

        return self._load_unit_from_source(unit_name)

    def analyze_vertical(self, unit_name: str, depth: str, column_key: str) -> dict[str, object]:
        normalized_depth = depth.strip().lower()
        valid_depths = {"layer1", "layer2", "heuristics", "full"}
        if normalized_depth not in valid_depths:
            raise ValueError(f"Profundidade vertical inválida: {depth}")

        column_name = self._resolve_column_name(unit_name, column_key)
        unit_data = self._get_cached_unit(unit_name)
        row_count = int(unit_data["row_count"]) if unit_data else self._unit_row_and_column_counts(unit_name)[0]
        unit_cache_key = self._unit_analysis_cache_key(unit_name)

        cache_key = self._generate_cache_key(
            analysis_type="vertical",
            origem=unit_name,
            alvo=column_name,
            profundidade=normalized_depth,
            method="vertical",
            linhas=row_count,
            colunas=1,
            cost_method=normalized_depth,
            parent_id=unit_cache_key,
        )
        cached = self._get_cached_payload(cache_key)
        if cached is not None:
            return cached

        if unit_data is None:
            self.analyze_unit(unit_name)
            unit_data = self._get_cached_unit(unit_name)
            if unit_data is None:
                raise ValueError(f"Falha ao preparar cache da unidade: {unit_name}")

        payload = self._calculate_column_from_unit(
            unit_data,
            column_name,
            normalized_depth,
            cache_key=cache_key,
            unit_name=unit_name,
        )
        self._store_payload(cache_key, payload)
        return payload

    def analyze_horizontal(self, unit_a: str, unit_b: str) -> dict[str, object]:
        rows_a, _ = self._unit_row_and_column_counts(unit_a)
        rows_b, _ = self._unit_row_and_column_counts(unit_b)
        total_rows = rows_a + rows_b

        cache_key = self._generate_cache_key(
            analysis_type="horizontal",
            origem=unit_a,
            alvo=unit_b,
            method="horizontal",
            linhas=total_rows,
            cost_method="horizontal",
        )
        cached = self._get_cached_payload(cache_key)
        if cached is not None:
            return cached

        unit_a_data = self._get_cached_unit(unit_a)
        unit_b_data = self._get_cached_unit(unit_b)

        if unit_a_data is None:
            self.analyze_unit(unit_a)
            unit_a_data = self._get_cached_unit(unit_a)
        if unit_b_data is None:
            self.analyze_unit(unit_b)
            unit_b_data = self._get_cached_unit(unit_b)

        if unit_a_data is not None and unit_b_data is not None:
            payload = self._calculate_cross_from_units(
                unit_a_data,
                unit_b_data,
                cache_key=cache_key,
                unit_a=unit_a,
                unit_b=unit_b,
            )
        else:
            payload = {
                "status": "not implemented",
                "unit_a": unit_a,
                "unit_b": unit_b,
                "cache_key": cache_key,
                "reused_unit_cache": False,
            }

        self._store_payload(cache_key, payload)
        return payload

    def recall(self, cache_key: str) -> object:
        return self.cache_manager.recall(self._cache_session_id(), cache_key)

    def get_session_structure(self) -> dict[str, object]:
        units_payload: list[dict[str, object]] = []
        for unit in self._units:
            unit_name = unit.unit_name
            structure = unit.get_structure()
            metadata = unit.get_metadata()
            analysis = self._ensure_unit_analysis(unit_name)

            column_summaries: list[dict[str, object]] = []
            for column in structure.columns:
                column_analysis = analysis.columns.get(column.name)
                layer1_metrics = column_analysis.layer1_metrics if column_analysis is not None else {}
                column_summaries.append(
                    {
                        **self._serialize_column_structure(column),
                        "cardinality": layer1_metrics.get("cardinality"),
                        "null_ratio": layer1_metrics.get("null_ratio"),
                        "unique_ratio": layer1_metrics.get("unique_ratio"),
                    }
                )

            units_payload.append(
                {
                    "unit_name": unit_name,
                    "row_count": analysis.standardized.row_count,
                    "column_count": analysis.standardized.column_count,
                    "metadata": self._serialize_unit_metadata(metadata),
                    "columns": column_summaries,
                    "raw_attributes": self._serialize_core_value(dict(structure.raw_attributes)),
                }
            )

        return {"units": units_payload}

    def analyze_unit_full(self, unit_name: str) -> dict[str, object]:
        cache_key = f"unit_full:{unit_name}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        unit = next((item for item in self._units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        analysis = self._ensure_unit_analysis(unit_name)
        payload = self._serialize_tabular_unit_analysis(analysis)
        self._set_cache(cache_key, payload)
        return payload

    def analyze_vertical_full(self, unit_name: str, column_key: str) -> dict[str, object]:
        column_name = self._resolve_column_name(unit_name, column_key)
        analysis = self._ensure_unit_analysis(unit_name)
        column = analysis.columns.get(column_name)
        if column is None:
            raise ValueError(f"Coluna não encontrada em {unit_name}: {column_name}")

        cache_key = f"vertical_full:{unit_name}:{column_name}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        payload: dict[str, object] = {
            "unit_name": unit_name,
            "column": column_name,
            **self._serialize_column_analysis(column),
        }
        self._set_cache(cache_key, payload)
        return payload
