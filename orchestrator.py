from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from agnostic.ai.ports.ai_orchestrator import AIResponse
from agnostic.application.planning.requirement_priority import sort_pending_requirements_for_investigation
from agnostic.application.planning.rule_based_planner import (
    extract_units_from_sql,
    plan_deterministic_action,
)
from agnostic.config import load_app_config
from agnostic.domain.analysis.analyze_tabular_unit import analyze_tabular_unit
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.infrastructure.storage.csv_source import CSVDataSource
from agnostic.infrastructure.storage.parquet_source import ParquetDataSource
from agnostic.presentation.summaries.summarize_tabular_analysis import (
    summarize_tabular_analysis,
    summarize_unit_metrics,
)


SUPPORTED_SUFFIXES = {
    ".csv": "csv",
    ".parquet": "parquet",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
}
QUERY_CATALOG = {}
ANALYTIC_TEMPLATES = {
    "group_feature_signature": """
        SELECT
            {group_expr} AS group_value,
            {feature_expr} AS feature_value,
            {subfeature_expr}
            COUNT(*) AS total,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY {group_expr}), 2) AS pct_group
        FROM {from_clause}
        WHERE {where_clause}
        GROUP BY {group_expr}, {feature_expr}{subfeature_group}
        ORDER BY group_value, pct_group DESC
    """,
    "group_feature_signature_by_entity": """
        SELECT
            {group_expr} AS group_value,
            {entity_expr} AS entity_id,
            {feature_expr} AS feature_value,
            {subfeature_expr}
            COUNT(*) AS total
        FROM {from_clause}
        WHERE {where_clause}
        GROUP BY {group_expr}, {entity_expr}, {feature_expr}{subfeature_group}
        ORDER BY group_value, entity_id, total DESC
    """,
    "exclusive_feature_values_by_group": """
        WITH clean AS (
            SELECT {group_expr} AS group_value, {feature_expr} AS feature_value, COUNT(*) AS total
            FROM {from_clause}
            WHERE {where_clause}
            GROUP BY {group_expr}, {feature_expr}
        ),
        group_count AS (
            SELECT feature_value, COUNT(DISTINCT group_value) AS groups_with_feature
            FROM clean GROUP BY feature_value
        )
        SELECT clean.group_value, clean.feature_value, clean.total
        FROM clean
        JOIN group_count gc ON clean.feature_value = gc.feature_value
        WHERE gc.groups_with_feature = 1
        ORDER BY clean.total DESC
    """,
}
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_TIMEOUT_SECONDS = 30.0
CURATOR_TIMEOUT_SECONDS = 15.0
MAX_ATTEMPTS_PER_TURN = 3
INTERFACE_MODEL = "deepseek-chat"
ORCHESTRATOR_MODEL = "deepseek-chat"
CURATOR_MODEL = "deepseek-chat"
logger = logging.getLogger(__name__)


class DeepSeekAPIError(RuntimeError):
    pass


@dataclass
class KnowledgeNode:
    id: str
    label: str
    unit: str
    data: dict
    timestamp: str
    action: str = ""
    cache_key: str = ""
    units: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    join_keys: list[str] = field(default_factory=list)
    sample_entities: list[str] = field(default_factory=list)
    next_requirements: list[dict[str, object]] = field(default_factory=list)
    status: str = ""


@dataclass
class KnowledgeEdge:
    from_id: str
    to_id: str
    relation: str


@dataclass
class KnowledgeGraph:
    nodes: list[KnowledgeNode] = field(default_factory=list)
    edges: list[KnowledgeEdge] = field(default_factory=list)

    def to_context(self) -> str:
        lines = ["## Grafo de Conhecimento", "", "### Nós"]
        if not self.nodes:
            lines.append("- Nenhum nó registrado.")
        else:
            for node in self.nodes:
                cache_key = f" cache={node.cache_key}" if node.cache_key else ""
                units = f" units={', '.join(node.units)}" if node.units else ""
                columns = f" columns={', '.join(node.columns[:6])}" if node.columns else ""
                joins = f" join_keys={', '.join(node.join_keys[:4])}" if node.join_keys else ""
                candidate_keys = ", ".join(node.data.get("evidence", {}).get("candidate_key_columns", [])[:4]) if isinstance(node.data, dict) else ""
                key_text = f" candidate_keys={candidate_keys}" if candidate_keys else ""
                sample_entities = ", ".join(node.sample_entities[:4]) if node.sample_entities else ""
                sample_text = f" sample_entities={sample_entities}" if sample_entities else ""
                lines.append(
                    f"- {node.id} [{node.unit}] action={node.action or 'unknown'} status={node.status or ''}:{cache_key}{units}{columns}{joins}{key_text}{sample_text} :: {node.label}"
                )
        lines.extend(["", "### Arestas"])
        if not self.edges:
            lines.append("- Nenhuma aresta registrada.")
        else:
            for edge in self.edges:
                lines.append(f"- {edge.from_id} -> {edge.relation} -> {edge.to_id}")
        lines.extend(["", "### Requisitos Pendentes"])
        pending = self.pending_requirements()
        if not pending:
            lines.append("- Nenhum requisito pendente.")
        else:
            for requirement in pending:
                units = ", ".join(str(unit) for unit in requirement.get("units", []))
                lines.append(
                    f"- {requirement.get('id', '')} [{requirement.get('kind', '')}] status={requirement.get('status', '')} units={units}: {requirement.get('description', '')}"
                )
        return "\n".join(lines)

    def pending_requirements(self, active_focus: dict[str, object] | None = None) -> list[dict[str, object]]:
        pending: list[dict[str, object]] = []
        for node in sorted(self.nodes, key=lambda node: str(node.timestamp), reverse=True):
            for requirement in node.next_requirements:
                if str(requirement.get("status", "")).strip().lower() != "pending":
                    continue
                pending.append(requirement)
        return sort_pending_requirements_for_investigation(pending, active_focus=active_focus)

    def mark_requirement_resolved(self, requirement_id: str) -> bool:
        for node in self.nodes:
            for requirement in node.next_requirements:
                if requirement.get("id") == requirement_id:
                    requirement["status"] = "resolved"
                    return True
        return False


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEEPSEEK_BASE_URL,
        timeout_seconds: float = DEEPSEEK_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._call_count = 0

    def send(self, prompt: str, *, system_prompt: str | None = None) -> AIResponse:
        self._call_count += 1
        payload: dict[str, object] = {
            "model": self._model,
            "messages": self._build_messages(prompt, system_prompt=system_prompt),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            request = urllib_request.Request(
                f"{self._base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            message = f"DeepSeek request failed: HTTP {exc.code} {exc.reason}"
            if body:
                message = f"{message} :: {body[:240]}"
            raise DeepSeekAPIError(message) from exc
        except URLError as exc:
            raise DeepSeekAPIError(f"DeepSeek request failed: {exc.reason}") from exc

        try:
            data = json.loads(raw_body)
            content = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DeepSeekAPIError("DeepSeek response did not include message content.") from exc

        return AIResponse(
            provider="deepseek",
            model=self._model,
            content=content,
            call_number=self._call_count,
            remaining_calls=0,
            quota_per_hour=0,
            simulated=False,
        )

    @staticmethod
    def _build_messages(
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages


class OrchestratorSession:
    def __init__(self, source_path: str) -> None:
        self.source_path = str(Path(source_path).expanduser().resolve())
        self.source_type = detect_source_type(self.source_path)
        self.source = resolve_source(self.source_type, self.source_path)
        self.units = self.source.list_units()
        if not self.units:
            raise ValueError("Nenhuma unidade tabular foi encontrada na origem informada.")
        self.analysis_by_unit: dict[str, object] = {}
        self.explored_paths: list[str] = []
        self.knowledge_graph = KnowledgeGraph()
        self.history: list[dict[str, str]] = []
        self._core_cache: dict[str, object] = {}
        self._full_structural_context: str | None = None
        self._curator_cache: dict[str, dict[str, object]] = {}
        self._session_query_catalog: dict[str, str] = {}
        self._candidate_queries: list[tuple[str, str]] = []
        self._execution_log: list[dict[str, str]] = []
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY não encontrada. Verifique o arquivo .env.")
        self.interface_ai = DeepSeekClient(api_key=api_key, model=INTERFACE_MODEL)
        self.orchestrator_ai = DeepSeekClient(api_key=api_key, model=ORCHESTRATOR_MODEL)
        self.curator_ai = DeepSeekClient(
            api_key=api_key,
            model=CURATOR_MODEL,
            timeout_seconds=CURATOR_TIMEOUT_SECONDS,
        )

    def bootstrap(self) -> tuple[str, str]:
        structural_context = self.build_source_overview_context()
        self._full_structural_context = structural_context
        opening = self.interface_reply(
            "Explique o panorama inicial em linguagem humana e sugira o próximo passo de exploração.",
            result_context=structural_context,
            is_first_call=True,
        )
        return structural_context, opening

    def build_source_overview_context(self) -> str:
        sections = [
            f"Origem: {self.source_path}",
            f"Tipo detectado: {self.source_type}",
            f"Unidades detectadas: {', '.join(unit.unit_name for unit in self.units)}",
            "Layer 1 — descoberta inicial: metadata básica por unidade, sem análise profunda.",
        ]
        for unit in self.units:
            metadata = unit.get_metadata()
            structure = unit.get_structure()
            row_count = metadata.row_count if metadata.row_count is not None else "desconhecida"
            column_names = ", ".join(column.name for column in structure.columns) or "sem colunas"
            sections.append(
                f"Unidade {unit.unit_name}: {row_count} linhas; colunas: {column_names}."
            )
            if metadata.row_count == 0:
                sections.append(
                    f"ALERTA: a unidade {unit.unit_name} está vazia (0 linhas). "
                    "Consultas sobre ela não retornarão dados até haver conteúdo."
                )
        return "\n\n".join(sections)

    def analyze_unit_on_demand(self, unit_name: str) -> object:
        cached = self.analysis_by_unit.get(unit_name)
        if cached is not None:
            if unit_name not in self.explored_paths:
                self.explored_paths.append(unit_name)
            self._set_core_cache(f"unit:{unit_name}", cached)
            return cached

        unit = next((item for item in self.units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        max_rows = load_app_config().analysis.max_rows_per_unit
        analysis = analyze_tabular_unit(unit, max_rows=max_rows)
        self.analysis_by_unit[unit_name] = analysis
        self._set_core_cache(f"unit:{unit_name}", analysis)
        if unit_name not in self.explored_paths:
            self.explored_paths.append(unit_name)
        return analysis

    def analyze_vertical(self, unit_name: str, depth: str) -> str:
        normalized_depth = depth.strip().lower()
        valid_depths = {"layer1", "layer2", "heuristics", "full"}
        if normalized_depth not in valid_depths:
            raise ValueError(f"Profundidade vertical inválida: {depth}")

        analysis = self.analyze_unit_on_demand(unit_name)
        if normalized_depth == "full":
            cache_key = f"unit:{unit_name}"
            payload = self._serialize_for_cache(analysis)
        elif normalized_depth == "layer1":
            cache_key = f"layer1:{unit_name}"
            payload = self._extract_layer_metrics(analysis, depth="layer1")
        elif normalized_depth == "layer2":
            cache_key = f"layer2:{unit_name}"
            payload = self._extract_layer_metrics(analysis, depth="layer2")
        else:
            cache_key = f"heuristics:{unit_name}"
            payload = self._extract_heuristics(analysis)

        self._set_core_cache(cache_key, payload)
        return cache_key

    def _build_next_requirements_for_unit(
        self,
        *,
        unit_name: str,
        structure: object,
        analysis: object | None,
        cache_key: str,
    ) -> list[dict[str, object]]:
        classified = classify_columns_from_structure(structure, analysis=analysis)
        requirements: list[dict[str, object]] = []
        source_type = getattr(self, "source_type", "")
        columns = classified["columns"]

        def append_vertical_requirement(requirement_suffix: str, description: str, reason: str, depth: str) -> None:
            requirements.append(
                {
                    "id": f"req_{unit_name}_{requirement_suffix}",
                    "kind": "analyze_vertical",
                    "units": [unit_name],
                    "description": description,
                    "reason": reason,
                    "suggested_action": {
                        "action": "analyze_vertical",
                        "unit_name": unit_name,
                        "depth": depth,
                    },
                    "status": "pending",
                    "source_node_id": "",
                }
            )

        if source_type == "sqlite":
            if classified["categorical_columns"]:
                column = classified["categorical_columns"][0]
                requirements.append(
                    {
                        "id": f"req_{unit_name}_categorical_{column}",
                        "kind": "query",
                        "units": [unit_name],
                        "description": f"Contagem agregada por {column}",
                        "reason": "coluna categórica detectada",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": f"agregar por {column}",
                            "suggested_sql": (
                                f"SELECT {column}, COUNT(*) AS total "
                                f"FROM {unit_name} "
                                f"WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> '' "
                                f"GROUP BY {column} ORDER BY total DESC LIMIT 50"
                            ),
                        },
                        "status": "pending",
                        "source_node_id": "",
                    }
                )
            if classified["text_columns"]:
                column = classified["text_columns"][0]
                selected = ", ".join(classified["text_columns"][:2])
                requirements.append(
                    {
                        "id": f"req_{unit_name}_text_{column}",
                        "kind": "query",
                        "units": [unit_name],
                        "description": f"Amostrar registros textuais de {unit_name}",
                        "reason": "colunas textuais detectadas",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": f"amostrar textos de {unit_name}",
                            "suggested_sql": (
                                f"SELECT {selected} FROM {unit_name} "
                                f"WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> '' LIMIT 50"
                            ),
                        },
                        "status": "pending",
                        "source_node_id": "",
                    }
                )
            if classified["numeric_columns"]:
                column = classified["numeric_columns"][0]
                requirements.append(
                    {
                        "id": f"req_{unit_name}_numeric_{column}",
                        "kind": "query",
                        "units": [unit_name],
                        "description": f"Resumo numérico básico de {column}",
                        "reason": "coluna numérica detectada",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": f"agregação numérica de {column}",
                            "suggested_sql": (
                                f"SELECT COUNT(*) AS total, MIN({column}) AS min_value, MAX({column}) AS max_value, AVG({column}) AS avg_value "
                                f"FROM {unit_name} WHERE {column} IS NOT NULL"
                            ),
                        },
                        "status": "pending",
                        "source_node_id": "",
                    }
                )
            if classified["datetime_like_columns"]:
                column = classified["datetime_like_columns"][0]
                requirements.append(
                    {
                        "id": f"req_{unit_name}_datetime_{column}",
                        "kind": "query",
                        "units": [unit_name],
                        "description": f"Contagem por período de {column}",
                        "reason": "coluna temporal detectada",
                        "suggested_action": {
                            "action": "request_new_query",
                            "description": f"agregar por período em {column}",
                            "suggested_sql": (
                                f"SELECT SUBSTR(CAST({column} AS TEXT), 1, 10) AS period, COUNT(*) AS total "
                                f"FROM {unit_name} WHERE {column} IS NOT NULL "
                                f"GROUP BY SUBSTR(CAST({column} AS TEXT), 1, 10) ORDER BY total DESC LIMIT 50"
                            ),
                        },
                        "status": "pending",
                        "source_node_id": "",
                    }
                )
        elif columns:
            if classified["categorical_columns"]:
                append_vertical_requirement(
                    "categorical_summary",
                    "Aprofundar contagens e distribuições de colunas categóricas/binárias",
                    "colunas categóricas detectadas e exigem exploração operacional",
                    "layer2",
                )
            if classified["numeric_columns"]:
                append_vertical_requirement(
                    "numeric_summary",
                    "Aprofundar métricas numéricas e distribuições",
                    "colunas numéricas detectadas e exigem exploração operacional",
                    "layer2",
                )
            if classified["text_columns"]:
                append_vertical_requirement(
                    "text_sample",
                    "Amostrar conteúdo textual e sinais qualitativos",
                    "colunas textuais detectadas e exigem exploração operacional",
                    "layer2",
                )
            append_vertical_requirement(
                "missingness_summary",
                "Verificar nulos, completude, cardinalidade e possíveis chaves",
                "unidade tabular já analisada e requer exploração operacional complementar",
                "heuristics",
            )
        compatible_units = self._find_compatible_units(unit_name, columns)
        if compatible_units:
            partner = compatible_units[0]
            requirements.append(
                {
                    "id": f"req_{unit_name}_cross_{partner}",
                    "kind": "analyze_horizontal",
                    "units": [unit_name, partner],
                    "description": f"Analisar relação estrutural entre {unit_name} e {partner}",
                    "reason": "colunas potencialmente compatíveis entre unidades",
                    "suggested_action": {"action": "analyze_horizontal", "unit_a": unit_name, "unit_b": partner},
                    "status": "pending",
                    "source_node_id": "",
                }
            )
        if columns and source_type != "sqlite":
            requirements.append(
                {
                    "id": f"req_{unit_name}_schema",
                    "kind": "schema",
                    "units": [unit_name],
                    "description": f"Consultar schema de {unit_name}",
                    "reason": "complementar a exploração operacional com estrutura explícita",
                    "suggested_action": {"action": "schema", "table": unit_name},
                    "status": "pending",
                    "source_node_id": "",
                }
            )
            requirements.append(
                {
                    "id": f"req_{unit_name}_recall",
                    "kind": "recall",
                    "units": [unit_name],
                    "description": f"Recuperar detalhes operacionais já calculados para {unit_name}",
                    "reason": "resultado já calculado e salvo no cache",
                    "suggested_action": {"action": "recall", "key": cache_key},
                    "status": "pending",
                    "source_node_id": "",
                }
            )
        elif not requirements:
            requirements.append(
                {
                    "id": f"req_{unit_name}_schema",
                    "kind": "schema",
                    "units": [unit_name],
                    "description": f"Consultar schema de {unit_name}",
                    "reason": "nenhuma outra heurística aplicável",
                    "suggested_action": {"action": "schema", "table": unit_name},
                    "status": "pending",
                    "source_node_id": "",
                }
            )
            requirements.append(
                {
                    "id": f"req_{unit_name}_recall",
                    "kind": "recall",
                    "units": [unit_name],
                    "description": f"Recuperar detalhes operacionais já calculados para {unit_name}",
                    "reason": "resultado já calculado e salvo no cache",
                    "suggested_action": {"action": "recall", "key": cache_key},
                    "status": "pending",
                    "source_node_id": "",
                }
            )
        return requirements

    def _build_operational_payload_for_unit(
        self,
        *,
        unit_name: str,
        structure: object,
        analysis: object | None,
        cache_key: str,
        action: str,
        depth: str | None = None,
    ) -> dict[str, object]:
        payload = build_operational_summary_for_unit(
            unit_name=unit_name,
            structure=structure,
            analysis=analysis,
            cache_key=cache_key,
            action=action,
            depth=depth,
        )
        payload["next_requirements"] = self._build_next_requirements_for_unit(
            unit_name=unit_name,
            structure=structure,
            analysis=analysis,
            cache_key=cache_key,
        )
        return payload

    def analyze_horizontal(self, unit_a: str, unit_b: str) -> dict[str, object]:
        first = self._find_unit(unit_a)
        second = self._find_unit(unit_b)
        structure_a = first.get_structure()
        structure_b = second.get_structure()
        columns_a = {column.name: column for column in structure_a.columns}
        columns_b = {column.name: column for column in structure_b.columns}
        same_name_columns = sorted(set(columns_a) & set(columns_b))
        join_keys = self._infer_join_keys(unit_a, structure_a, unit_b, structure_b)

        rows_a = list(first.get_rows())[:50]
        rows_b = list(second.get_rows())[:50]
        value_sets_a = self._column_value_sets(structure_a, rows_a)
        value_sets_b = self._column_value_sets(structure_b, rows_b)

        compatible_cardinality: list[dict[str, object]] = []
        matching_value_patterns: list[dict[str, object]] = []
        for column_a in structure_a.columns:
            for column_b in structure_b.columns:
                values_a = value_sets_a.get(column_a.name, set())
                values_b = value_sets_b.get(column_b.name, set())
                if not values_a or not values_b:
                    continue
                len_a = len(values_a)
                len_b = len(values_b)
                ratio = min(len_a, len_b) / max(len_a, len_b)
                if ratio >= 0.8:
                    compatible_cardinality.append(
                        {
                            "column_a": column_a.name,
                            "column_b": column_b.name,
                            "distinct_values_a": len_a,
                            "distinct_values_b": len_b,
                        }
                    )
                overlap = values_a & values_b
                overlap_ratio = len(overlap) / min(len_a, len_b)
                if overlap_ratio >= 0.5:
                    matching_value_patterns.append(
                        {
                            "column_a": column_a.name,
                            "column_b": column_b.name,
                            "overlap_count": len(overlap),
                            "overlap_ratio": round(overlap_ratio, 3),
                            "sample_overlap": sorted(str(item) for item in list(overlap)[:5]),
                        }
                    )

        payload = {
            "action": "analyze_horizontal",
            "status": "cached",
            "cache_key": f"cross:{unit_a}:{unit_b}",
            "units": [unit_a, unit_b],
            "unit_a": unit_a,
            "unit_b": unit_b,
            "same_name_columns": same_name_columns,
            "compatible_cardinality": compatible_cardinality,
            "matching_value_patterns": matching_value_patterns,
            "join_keys": join_keys,
            "sample_entities": extract_sample_entities(
                sorted(set(columns_a) | set(columns_b)),
                rows_a[:5] + rows_b[:5],
                max_entities=10,
            ),
            "operational_summary": {
                "row_count": None,
                "columns": sorted(set(columns_a) | set(columns_b)),
                "metrics_available": False,
                "notes": ["análise horizontal calculada a partir de schema e amostras curtas"],
            },
            "evidence": {
                "columns": sorted(set(columns_a) | set(columns_b)),
                "row_count": None,
                "candidate_key_columns": sorted(set(detect_candidate_key_columns(list(columns_a)) + detect_candidate_key_columns(list(columns_b)))),
                "categorical_columns": [],
                "numeric_columns": [],
                "text_columns": [],
                "datetime_like_columns": [],
            },
        }
        payload["next_requirements"] = self._build_horizontal_requirements(payload)
        cache_key = str(payload["cache_key"])
        self._set_core_cache(cache_key, payload)
        return payload

    def recall_core_cache(self, key: str) -> dict[str, object]:
        payload = getattr(self, "_core_cache", {}).get(key)
        if payload is None:
            return {
                "key": key,
                "found": False,
                "message": "Cálculo ainda não foi feito para esta chave.",
            }
        return {
            "key": key,
            "found": True,
            "cached_result": payload,
        }

    def available_cache_keys(self) -> list[str]:
        return sorted(getattr(self, "_core_cache", {}).keys())

    def pending_requirements(self) -> list[dict[str, object]]:
        graph = getattr(self, "knowledge_graph", KnowledgeGraph())
        return graph.pending_requirements()

    def build_structural_context(self, analyses: list[object]) -> str:
        sections = [
            f"Origem: {self.source_path}",
            f"Tipo detectado: {self.source_type}",
            f"Unidades detectadas: {', '.join(unit.unit_name for unit in self.units)}",
        ]
        for analysis in analyses:
            sections.append(summarize_tabular_analysis(analysis))
            if int(analysis.standardized.row_count) == 0:
                sections.append(
                    f"ALERTA: a unidade {analysis.unit_name} está vazia (0 linhas). "
                    "Consultas sobre ela não retornarão dados até haver conteúdo."
                )
            sections.extend(summarize_unit_metrics(analysis))
        return "\n\n".join(sections)

    def build_compact_structural_context(self) -> str:
        lines = [f"Unidades disponíveis: {', '.join(unit.unit_name for unit in self.units)}"]
        for unit in self.units:
            row_count = "desconhecida"
            try:
                metadata = unit.get_metadata()
                if metadata.row_count is not None:
                    row_count = str(metadata.row_count)
            except Exception:
                row_count = "desconhecida"
            lines.append(f"- {unit.unit_name}: {row_count} linhas")
        return "\n".join(lines)

    def should_use_curator(self, *, is_first_call: bool) -> bool:
        return not is_first_call and len(self.units) > 3 and bool(self._full_structural_context)

    def curated_context_for(self, user_text: str, *, is_first_call: bool) -> str:
        if not self.should_use_curator(is_first_call=is_first_call):
            return self._full_structural_context or self.build_compact_structural_context()
        graph = getattr(self, "knowledge_graph", None)
        curator_context = self._full_structural_context or self.build_compact_structural_context()
        if graph is not None and len(graph.nodes) >= 2:
            curator_context = graph.to_context()
        cache_key = user_text.strip()
        cached = self._curator_cache.get(cache_key)
        if cached is not None:
            curated_context = cached.get("curated_context")
            if isinstance(curated_context, str) and curated_context.strip():
                return curated_context
            return self._full_structural_context or self.build_compact_structural_context()

        system_prompt = (
            "Você é a IA Curadora do Cartographer.\n"
            "Você nunca conversa, nunca executa ações e nunca cria interpretações.\n"
            "Responda somente com JSON válido no formato esperado.\n"
            "Seu trabalho é filtrar o contexto estrutural existente para o subconjunto relevante à pergunta atual.\n"
        )
        prompt = build_curator_prompt(
            user_message=user_text,
            available_units=[unit.unit_name for unit in self.units],
            full_context=curator_context,
        )
        try:
            response = self.curator_ai.send(prompt, system_prompt=system_prompt)
            payload = parse_curator_json(response.content)
        except Exception:
            return self._full_structural_context or self.build_compact_structural_context()

        self._curator_cache[cache_key] = payload
        curated_context = payload.get("curated_context")
        if isinstance(curated_context, str) and curated_context.strip():
            return curated_context
        return self._full_structural_context or self.build_compact_structural_context()

    def interface_reply(self, user_text: str, *, result_context: str, is_first_call: bool = False) -> str:
        system_prompt = (
            "Você é a IA Interface do Cartographer.\n"
            "Seu papel é conversar com o usuário em português claro.\n"
            "Você interpreta apenas resultados produzidos pelo core ou por consultas já executadas.\n"
            "Você nunca inventa análise e nunca emite JSON.\n"
            "Você nunca calcula percentuais, nunca infere números e nunca produz valores que não vieram diretamente do core ou do banco.\n"
            "Você nunca promete executar algo e nunca usa frases como 'vou executar agora', 'vou investigar' ou 'precisamos executar'.\n"
            "PROIBIDO: nunca gere blocos de código SQL na resposta.\n"
            "Se a próxima ação requer uma consulta SQL, descreva o que precisa em português.\n"
            "A Orquestradora é quem decide e executa o SQL — nunca a Interface.\n"
            "Se um resultado não estiver disponível no contexto, diga apenas 'não tenho esse dado, aguarde a execução'.\n"
            "Se o resultado contiver operational_summary, evidence ou next_requirements, explique esse contexto operacional e NÃO diga que o dado está indisponível.\n"
            "Se houver next_requirements ou pending_requirements operacionais, sugira o primeiro passo operacional útil e evite sugerir schema ou estrutura de forma redundante.\n"
            "Quando o resultado contém pistas concretas (nomes, endereços, IDs),\n"
            'NÃO termine com "Qual a sua instrução?" ou "Deseja que eu prepare essa busca?".\n'
            "Informe diretamente o que será executado no próximo passo.\n"
            'Se o resultado contiver "truncated: true", você DEVE avisar o usuário que o resultado está incompleto e NÃO pode concluir sobre padrões, exclusividade ou predominância. Diga apenas: "resultado parcial — não é possível concluir ainda".\n'
            "Para concluir sobre exclusividade, predominância global, ausência ou padrão regional, a query usada deve ser uma query agregada completa.\n"
            "Nunca concluir sobre esses temas a partir de consulta por entidade individual com resultado truncado.\n"
            'Se o resultado vier de uma query por entidade individual e estiver truncado, diga: "resultado parcial — use uma query agregada para conclusões regionais".\n'
            "REGRAS DE LINGUAGEM PARA CONCLUSÕES:\n"
            'Use "assinatura forte" SOMENTE quando:\n'
            "- resultado não truncado\n"
            "- padrão aparece em mais de uma entidade\n"
            "- proporção regional alta\n"
            "- exclusividade confirmada por consulta agregada de exclusividade\n"
            'Use "hipótese" quando:\n'
            "- poucas entidades na amostra\n"
            "- resultado truncado\n"
            "- exclusividade não confirmada\n"
            'Use "pista" quando:\n'
            "- amostra pequena (menos de 3 entidades)\n"
            "- resultado parcial\n"
            'Nunca use "descoberta", "exclusivo" ou "predominante" sem validação completa.\n'
            "Quando o usuário expressar um objetivo aberto (ex: 'encontrar o criminoso', 'descobrir padrões', 'entender essa tabela'):\n"
            "- Identifique se o objetivo requer aprofundar uma tabela (vertical) ou cruzar tabelas (horizontal)\n"
            "- Informe ao usuário qual análise você sugere e por quê\n"
            "- Nunca execute diretamente — informe a intenção para a Orquestradora decidir\n"
            "Análise vertical: quando o usuário quer entender uma tabela em profundidade\n"
            "Análise horizontal: quando o usuário menciona relações entre tabelas ou objetivos que requerem cruzamento\n"
        )
        prompt = build_interface_prompt(
            source_path=self.source_path,
            source_type=self.source_type,
            history=self.history,
            user_text=user_text,
            result_context=result_context,
            structural_context=self._full_structural_context if is_first_call else self.curated_context_for(user_text, is_first_call=is_first_call),
            is_first_call=is_first_call,
        )
        response = self.interface_ai.send(prompt, system_prompt=system_prompt)
        return response.content

    def orchestrate(
        self,
        user_text: str,
        structural_context: str,
        *,
        last_error: str | None = None,
        last_result: str | None = None,
        executed_queries: list[str] | None = None,
        query_catalog: list[str] | None = None,
        attempt_number: int = 1,
    ) -> dict[str, object]:
        system_prompt = (
            "Você é a IA Orquestradora do Cartographer.\n"
            "Sua única função é decidir qual ação executar. Você nunca conversa.\n"
            "Responda SOMENTE com JSON válido. Sem markdown. Sem texto fora do JSON.\n\n"
            "LEIS (em ordem de prioridade — lei superior prevalece):\n\n"
            "LEI 1 — FORMATO ABSOLUTO:\n"
            "Toda resposta deve ser exatamente um destes JSONs:\n"
            '  {"action":"analyze_unit","unit_name":"nome_da_tabela"}\n'
            '  {"action":"analyze_vertical","unit_name":"nome_da_tabela","depth":"layer1|layer2|heuristics|full"}\n'
            '  {"action":"analyze_horizontal","unit_a":"nome_a","unit_b":"nome_b"}\n'
            '  {"action":"recall","key":"unit:nome_da_tabela"}\n'
            '  {"action":"query","query_id":"id_do_catalogo"}\n'
            '  {"action":"template","template_id":"group_feature_signature","params":{"group_expr":"...","feature_expr":"...","from_clause":"...","where_clause":"...","subfeature_expr":"","subfeature_group":""}}\n'
            '  {"action":"request_new_query","description":"o que precisa","suggested_sql":"SELECT ..."}\n'
            '  {"action":"schema","table":"nome"}\n'
            '  {"action":"tables"}\n'
            '  {"action":"done","conclusion":"texto"}\n'
            "Se a mensagem do usuário começar com SELECT, isso é uma query direta.\n"
            "Nesse caso, responda SEMPRE com request_new_query usando suggested_sql exatamente igual ao SQL digitado pelo usuário.\n"
            "Qualquer outro formato é proibido.\n\n"
            "LEI 2 — CATÁLOGO É EXATO, NÃO APROXIMADO:\n"
            "Só use action=query quando o query_id atender EXATAMENTE ao pedido.\n"
            "Exato significa: mesmas colunas, mesmo filtro, mesmo agrupamento.\n"
            "Semelhante não é exato. Parecido não é exato.\n"
            "Escolha action=schema APENAS quando o usuário perguntar explicitamente sobre a estrutura ou colunas de uma tabela.\n"
            '"explorar", "ver", "analisar", "investigar" uma tabela → action=analyze_unit\n'
            '"quais colunas tem", "estrutura de", "schema de" → action=schema\n'
            "Perguntas como 'localize', 'busque', 'encontre' e 'mostre' são sempre action=query ou action=request_new_query.\n"
            "Quando o contexto contiver analysis_intent=vertical:\n"
            "- Use action=analyze_vertical com a tabela mais relevante\n"
            "Quando o contexto contiver analysis_intent=horizontal:\n"
            "- Use action=analyze_horizontal com as duas tabelas mais relevantes\n"
            "Quando o objetivo for aberto e desconhecido:\n"
            "- Use action=analyze_vertical na tabela central primeiro\n"
            "- Depois use action=analyze_horizontal para detectar relações\n"
            "Se houver dúvida, use request_new_query.\n\n"
            "LEI 3 — SEM COBERTURA = request_new_query OBRIGATÓRIO:\n"
            "Se nenhum query_id do catálogo atender exatamente, SEMPRE emita request_new_query.\n"
            "Nunca substitua por query do catálogo quando o usuário forneceu SQL explícito.\n"
            "Nunca emita done quando faltar dados para responder.\n"
            "Nunca deixe a Interface inventar dados.\n"
            "No suggested_sql de request_new_query, gere APENAS SELECT simples com condições básicas.\n"
            "Para cruzar múltiplas tabelas, use subqueries simples.\n"
            "Nunca gere SQL que combine condições de tabelas diferentes sem JOIN explícito.\n\n"
            "LEI 4 — ERRO NÃO É CONCLUSÃO:\n"
            "Nunca emita done quando o contexto contiver 'erro' ou 'error'.\n"
            "Em caso de erro, tente request_new_query com SQL corrigido.\n\n"
            "LEI 5 — CONFIRMAÇÃO CURTA NÃO ENCERRA E NÃO PARALISA:\n"
            "Confirmações curtas normalmente já são resolvidas pelo planner determinístico.\n"
            "Se ainda chegarem aqui, consuma o primeiro pending_requirement aplicável.\n"
            '"sim", "ok", "pode", "prossiga", "continue", "vai", "execute" após uma sugestão da Interface = executar a ação sugerida.\n'
            "Para identificar qual ação executar:\n"
            "1. Ler a última mensagem do histórico da Interface\n"
            "2. Identificar a ação sugerida (query, template, analyze_unit)\n"
            "3. Executar essa ação\n"
            "EXEMPLO LEI 5:\n"
            'Histórico mostra Interface sugerindo: "Quer que eu explore a unidade principal?"\n'
            'Usuário responde: "sim"\n'
            'Resposta CORRETA: {"action": "analyze_unit", "unit_name": "nome_da_unidade"}\n'
            'Resposta ERRADA: {"action": "tables"}\n'
            'Resposta ERRADA: {"action": "done", "conclusion": "..."}\n'
            'Se o histórico contém lista numerada de próximos passos e o usuário responde "ok", "sim", "pode", "vai":\n'
            "- Execute o PRIMEIRO passo da lista\n"
            "- Não paralise esperando instrução mais específica\n"
            'Nunca responder com "preciso de instrução clara" quando houver uma sugestão pendente no histórico.\n\n'
            "LEI 6 — NÃO REEXECUTE:\n"
            "Não reexecute cálculos já presentes em execution_log ou available_cache_keys.\n"
            "Se precisar detalhe de resultado anterior, use recall(cache_key).\n"
            "Se houver pending_requirements, avance para o primeiro requisito não resolvido.\n"
            "execution_log contém TODAS as ações executadas com sucesso nesta sessão (entre turnos).\n"
            "Se uma unidade X já aparece em execution_log com action=analyze_unit, NÃO execute analyze_unit sobre X novamente.\n"
            "Se um SQL sobre tabela X já aparece em execution_log, NÃO execute SQL sobre X novamente com o mesmo filtro.\n"
            "Se last_result contém pistas (ex: nomes de ruas, testemunhas, IDs), execute a PRÓXIMA ação lógica baseada nessas pistas.\n"
            "Exemplo: se execution_log mostra analyze_unit de uma unidade e last_result revela entidades ou chaves concretas,\n"
            "a próxima ação DEVE avançar para a unidade relacionada ou para o requisito pendente correspondente, nunca repetir a análise anterior.\n"
            "executed_queries contém queries do turno atual — não reexecute dentro do mesmo turno.\n"
            '"sim", "localize", "consulte", "faça" após um resultado = AVANÇAR para o próximo passo lógico, nunca repetir.\n'
            "Use execution_log para entender o que já foi feito e decidir o que ainda não foi feito.\n"
            'Quando o usuário quiser aprofundar uma tabela específica, use:\n{"action":"analyze_unit","unit_name":"nome_da_tabela"}\n'
            "Só analise tabelas que o usuário pediu explicitamente.\n"
            "Não analise todas as tabelas de uma vez.\n"
            "Quando o usuário pedir padrões, assinaturas ou diferenças por grupo:\n"
            "- Use action=template com template_id=group_feature_signature\n"
            "- Identifique: grupo, atributo, joins necessários, filtros de limpeza\n"
            "Quando o usuário pedir exclusividade ou ausência:\n"
            "- Use action=template com template_id=exclusive_feature_values_by_group\n"
            "- Nunca deduza exclusividade de preview ou amostra parcial\n"
            "Para validar se padrão vem de múltiplos objetos:\n"
            "- Use action=template com template_id=group_feature_signature_by_entity\n"
            "COMO INSTANCIAR TEMPLATES:\n"
            "1. Leia o contexto estrutural disponível para identificar:\n"
            "- quais tabelas existem\n"
            "- quais colunas cada tabela tem\n"
            "- como as tabelas se relacionam (colunas com mesmo nome ou alta cardinalidade)\n"
            "2. Para group_feature_signature:\n"
            "- group_expr: coluna de agrupamento (ex: categoria, região, país)\n"
            "- feature_expr: coluna de atributo a analisar (ex: tipo, código, status)\n"
            "- from_clause: tabelas e JOINs necessários baseados no schema real\n"
            "- where_clause: filtros para remover nulos e valores vazios das colunas usadas\n"
            "3. Nunca invente nomes de colunas. Use apenas colunas que existem no schema.\n"
            "4. Se não conseguir montar os parâmetros com certeza, use action=schema para consultar a tabela antes de instanciar o template.\n"
        )
        prompt = build_orchestrator_prompt(
            source_path=self.source_path,
            source_type=self.source_type,
            unit_names=[unit.unit_name for unit in self.units],
            structural_context=structural_context,
            history=self.history,
            user_text=user_text,
            compact_structural_context=self.curated_context_for(user_text, is_first_call=False),
            is_first_call=False,
            last_error=last_error,
            last_result=last_result,
            executed_queries=executed_queries or [],
            query_catalog=query_catalog or sorted(self.catalog_for_session().keys()),
            attempt_number=attempt_number,
            execution_log=self._execution_log,
            knowledge_graph_context=self.knowledge_graph.to_context(),
            available_cache_keys=self.available_cache_keys(),
            pending_requirements=self.pending_requirements(),
        )
        response = self.orchestrator_ai.send(prompt, system_prompt=system_prompt)
        return parse_orchestrator_json(response.content)

    def execute_action(self, action_payload: dict[str, object]) -> str:
        action = action_payload["action"]
        requirement_id = str(action_payload.get("__requirement_id", "")).strip()
        if action == "tables":
            return json.dumps(
                {
                    "source_type": self.source_type,
                    "tables": [unit.unit_name for unit in self.units],
                },
                ensure_ascii=False,
                indent=2,
            )
        if action == "analyze_unit":
            unit_name = str(action_payload["unit_name"])
            analysis = self.analyze_unit_on_demand(unit_name)
            structure = getattr(analysis, "structure", self._find_unit(unit_name).get_structure())
            cache_key = f"unit:{unit_name}"
            operational = self._build_operational_payload_for_unit(
                unit_name=unit_name,
                structure=structure,
                analysis=analysis,
                cache_key=cache_key,
                action="analyze_unit",
            )
            payload = {
                "action": "analyze_unit",
                "status": "cached",
                "cache_key": cache_key,
                "unit_name": unit_name,
                "summary": summarize_tabular_analysis(analysis),
                "metrics_summary": summarize_unit_metrics(analysis),
                "cached": True,
                "explored_paths": list(self.explored_paths),
            } | operational
            self.update_knowledge_graph(payload, action="analyze_unit")
            summary_line = summarize_tabular_analysis(analysis).splitlines()[0][:120] if analysis else unit_name
            self._log_execution({"action": "analyze_unit", "unit": unit_name, "summary": summary_line})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "analyze_vertical":
            unit_name = str(action_payload["unit_name"])
            depth = str(action_payload["depth"])
            cache_key = self.analyze_vertical(unit_name, depth)
            analysis = self.analysis_by_unit.get(unit_name)
            structure = getattr(analysis, "structure", self._find_unit(unit_name).get_structure())
            payload = self._build_operational_payload_for_unit(
                unit_name=unit_name,
                structure=structure,
                analysis=analysis,
                cache_key=cache_key,
                action="analyze_vertical",
                depth=depth,
            )
            self.update_knowledge_graph(payload, action="analyze_vertical")
            self._log_execution({"action": "analyze_vertical", "unit": unit_name, "depth": depth, "cache_key": cache_key})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "analyze_horizontal":
            unit_a = str(action_payload["unit_a"])
            unit_b = str(action_payload["unit_b"])
            payload = self.analyze_horizontal(unit_a, unit_b)
            self.update_knowledge_graph(payload, action="analyze_horizontal")
            self._log_execution({"action": "analyze_horizontal", "unit_a": unit_a, "unit_b": unit_b, "cache_key": str(payload.get("cache_key", ""))})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "recall":
            key = str(action_payload["key"])
            payload = self.recall_core_cache(key)
            self._log_execution({"action": "recall", "cache_key": key})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "schema":
            table = str(action_payload["table"])
            return json.dumps(self._schema_for_table(table), ensure_ascii=False, indent=2)
        if action == "query":
            query_id = str(action_payload["query_id"])
            payload = self._run_catalog_query(query_id)
            self.update_knowledge_graph(payload, action="query")
            self._log_execution({"action": "query", "query_id": query_id, "sql": str(payload.get("sql", ""))[:200], "cache_key": str(payload.get("cache_key", ""))})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "template":
            template_id = str(action_payload["template_id"])
            params = dict(action_payload["params"])
            sql = build_sql_from_template(template_id, params)
            validate_select_sql_text(sql)
            validate_sql_by_execution(self.source_path, sql)
            payload = self._validate_and_preview_sql(sql) | {"template_id": template_id, "sql": sql}
            self.update_knowledge_graph(payload, action="template")
            self._log_execution({"action": "template", "template_id": template_id, "sql": sql[:200]})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "request_new_query":
            description = str(action_payload["description"])
            suggested_sql = str(action_payload["suggested_sql"])
            result = self._register_session_query(description=description, suggested_sql=suggested_sql)
            self.update_knowledge_graph(result, action="query")
            self._log_execution({"action": "request_new_query", "description": description[:100], "sql": suggested_sql[:200], "cache_key": str(result.get("cache_key", ""))})
            if requirement_id:
                self.knowledge_graph.mark_requirement_resolved(requirement_id)
            return json.dumps(result, ensure_ascii=False, indent=2, default=str)
        if action == "done":
            return str(action_payload["conclusion"])
        raise ValueError(f"Ação não suportada: {action}")

    def update_knowledge_graph(self, result: dict[str, object], *, action: str) -> None:
        graph = getattr(self, "knowledge_graph", None)
        if graph is None:
            self.knowledge_graph = KnowledgeGraph()
            graph = self.knowledge_graph

        node = self._knowledge_node_from_result(result, action=action)
        if any(existing.unit == node.unit and existing.label == node.label for existing in graph.nodes):
            return
        graph.nodes.append(node)
        heuristic_edge = self._heuristic_knowledge_edge(node)
        if heuristic_edge is not None:
            graph.edges.append(heuristic_edge)
            return
        edge = self._curate_knowledge_edge(node)
        if edge is not None:
            graph.edges.append(edge)

    def render_knowledge_map(self) -> str:
        graph = getattr(self, "knowledge_graph", KnowledgeGraph())
        lines = ["## Mapa do Conhecimento", "", "### Achados"]
        if not graph.nodes:
            lines.append("- Nenhum achado registrado ainda.")
        else:
            children_by_parent: dict[str, list[KnowledgeEdge]] = {}
            child_ids = set()
            for edge in graph.edges:
                children_by_parent.setdefault(edge.from_id, []).append(edge)
                child_ids.add(edge.to_id)
            node_by_id = {node.id: node for node in graph.nodes}
            root_nodes = [node for node in graph.nodes if node.id not in child_ids]
            visited: set[str] = set()
            for node in root_nodes:
                self._append_knowledge_lines(
                    lines,
                    node=node,
                    node_by_id=node_by_id,
                    children_by_parent=children_by_parent,
                    indent="",
                    visited=visited,
                )
            for node in graph.nodes:
                if node.id not in visited:
                    self._append_knowledge_lines(
                        lines,
                        node=node,
                        node_by_id=node_by_id,
                        children_by_parent=children_by_parent,
                        indent="",
                        visited=visited,
                    )

        lines.extend(["", "### Caminhos não explorados"])
        unexplored_units = [
            unit.unit_name
            for unit in getattr(self, "units", [])
            if unit.unit_name not in getattr(self, "analysis_by_unit", {})
        ]
        if not unexplored_units:
            lines.append("- Nenhum caminho pendente nas unidades já descobertas.")
        else:
            for unit_name in unexplored_units:
                lines.append(f"- {unit_name}: não analisado")
        lines.extend(["", "### Cache Keys"])
        cache_keys = self.available_cache_keys()
        if not cache_keys:
            lines.append("- Nenhum cache registrado.")
        else:
            for cache_key in cache_keys:
                lines.append(f"- {cache_key}")
        lines.extend(["", "### Próximos Requisitos"])
        pending_requirements = self.pending_requirements()
        if not pending_requirements:
            lines.append("- Nenhum requisito pendente.")
        else:
            for requirement in pending_requirements:
                lines.append(
                    f"- {requirement.get('id', '')}: {requirement.get('description', '')} [{requirement.get('status', '')}]"
                )
        return "\n".join(lines)

    def _append_knowledge_lines(
        self,
        lines: list[str],
        *,
        node: KnowledgeNode,
        node_by_id: dict[str, KnowledgeNode],
        children_by_parent: dict[str, list[KnowledgeEdge]],
        indent: str,
        visited: set[str],
    ) -> None:
        if node.id in visited:
            return
        visited.add(node.id)
        lines.append(f"{indent}- [{node.unit}] {node.label}")
        graph = getattr(self, "knowledge_graph", None)
        resolved_ids = {
            str(requirement.get("id", "")).strip()
            for graph_node in getattr(graph, "nodes", []) if graph is not None
            for requirement in getattr(graph_node, "next_requirements", [])
            if str(requirement.get("status", "")).strip() == "resolved" and str(requirement.get("id", "")).strip()
        }
        ordered_requirements = sort_pending_requirements_for_investigation(
            list(node.next_requirements),
            active_focus=getattr(self, "_active_focus", None),
        )
        visible_requirement_ids: set[str] = set()
        for requirement in ordered_requirements:
            requirement_id = str(requirement.get("id", "")).strip()
            if (
                requirement_id
                and requirement_id in resolved_ids
                and str(requirement.get("status", "")).strip() != "resolved"
            ):
                continue
            if requirement_id and requirement_id in visible_requirement_ids:
                continue
            if requirement_id:
                visible_requirement_ids.add(requirement_id)
            lines.append(
                f"{indent}  - req {requirement.get('id', '')} [{requirement.get('status', '')}] {requirement.get('description', '')}"
            )
        for edge in children_by_parent.get(node.id, []):
            child = node_by_id.get(edge.to_id)
            if child is None:
                continue
            lines.append(f"{indent}  -> {edge.relation} -> [{child.unit}] {child.label}")
            self._append_knowledge_lines(
                lines,
                node=child,
                node_by_id=node_by_id,
                children_by_parent=children_by_parent,
                indent=f"{indent}    ",
                visited=visited,
            )

    def _knowledge_node_from_result(self, result: dict[str, object], *, action: str) -> KnowledgeNode:
        node_index = len(getattr(self.knowledge_graph, "nodes", [])) + 1
        timestamp = datetime.now(timezone.utc).isoformat()
        unit = self._infer_unit_for_knowledge(result, action=action)
        label = self._build_knowledge_label(result, action=action)
        node_id = f"{unit}:{node_index}"
        units = [item for item in self._serialize_for_cache(result.get("units", [])) if isinstance(item, str)] if isinstance(result.get("units"), list) else ([unit] if unit and unit != "resultado" else [])
        columns = [str(item) for item in result.get("columns", [])[:8]] if isinstance(result.get("columns"), list) else []
        sample_entities = [str(item) for item in result.get("sample_entities", [])[:10]] if isinstance(result.get("sample_entities"), list) else extract_sample_entities(result.get("columns"), result.get("rows"), max_entities=10)
        next_requirements = self._sanitize_requirements(result.get("next_requirements", []))
        return KnowledgeNode(
            id=node_id,
            label=label,
            unit=unit,
            data=self._sanitize_knowledge_payload(result),
            timestamp=timestamp,
            action=action,
            cache_key=str(result.get("cache_key", "")),
            units=units,
            columns=columns,
            join_keys=[str(item) for item in result.get("join_keys", [])[:8]] if isinstance(result.get("join_keys"), list) else [],
            sample_entities=sample_entities,
            next_requirements=next_requirements,
            status=str(result.get("status", "")),
        )

    def _infer_unit_for_knowledge(self, result: dict[str, object], *, action: str) -> str:
        if action == "analyze_unit":
            unit_name = result.get("unit_name")
            if isinstance(unit_name, str) and unit_name.strip():
                return unit_name.strip()
        if action == "analyze_horizontal":
            units = result.get("units")
            if isinstance(units, list) and units:
                first = units[0]
                if isinstance(first, str) and first.strip():
                    return first.strip()
        sql_fields = [
            result.get("sql"),
            result.get("from_clause"),
        ]
        for field_value in sql_fields:
            if isinstance(field_value, str):
                match = re.search(r"\bFROM\s+([A-Za-z0-9_\".]+)", field_value, flags=re.IGNORECASE)
                if match:
                    return match.group(1).strip('"')
        query_id = result.get("query_id") or result.get("template_id")
        if isinstance(query_id, str) and query_id.strip():
            return query_id.strip()
        return "resultado"

    def _build_knowledge_label(self, result: dict[str, object], *, action: str) -> str:
        if action == "analyze_unit":
            summary = str(result.get("summary", "")).strip()
            if summary:
                return summary.splitlines()[0][:120]
            return f"Resumo estrutural de {result.get('unit_name', 'unidade')}"
        if action == "query":
            query_id = str(result.get("query_id", "query")).strip()
            row_count = result.get("row_count_preview")
            return f"{query_id}: {row_count} linhas na prévia"
        if action == "analyze_horizontal":
            units = result.get("units", [])
            return f"Cruzamento estrutural entre {', '.join(str(unit) for unit in units)}"
        if action == "template":
            template_id = str(result.get("template_id", "template")).strip()
            row_count = result.get("row_count_preview")
            return f"{template_id}: {row_count} linhas na prévia"
        return str(result)[:120]

    def _curate_knowledge_edge(self, new_node: KnowledgeNode) -> KnowledgeEdge | None:
        existing_nodes = getattr(self.knowledge_graph, "nodes", [])[:-1]
        if not existing_nodes:
            return None

        system_prompt = (
            "Você é a IA Curadora do Cartographer.\n"
            "Você nunca conversa e nunca cria dados novos.\n"
            "Sua única função aqui é decidir se um novo achado se conecta a um nó já existente do grafo.\n"
            "Responda SOMENTE com JSON válido neste formato:\n"
            '{"from_id":"id_existente_ou_vazio","relation":"aprofunda|confirma|contradiz|"}\n'
            "Se não houver conexão clara, use strings vazias.\n"
        )
        prompt = json.dumps(
            {
                "knowledge_graph": {
                    "nodes": [asdict(node) for node in existing_nodes],
                    "edges": [asdict(edge) for edge in getattr(self.knowledge_graph, "edges", [])],
                },
                "new_finding": asdict(new_node),
            },
            ensure_ascii=False,
            indent=2,
        )
        try:
            response = self.curator_ai.send(prompt, system_prompt=system_prompt)
            payload = json.loads(response.content)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        from_id = payload.get("from_id")
        relation = payload.get("relation")
        valid_relations = {"aprofunda", "confirma", "contradiz"}
        if (
            not isinstance(from_id, str)
            or not from_id.strip()
            or from_id.strip() == new_node.id
            or from_id.strip() not in {node.id for node in existing_nodes}
        ):
            return None
        if not isinstance(relation, str) or relation.strip() not in valid_relations:
            return None
        return KnowledgeEdge(from_id=from_id.strip(), to_id=new_node.id, relation=relation.strip())

    def _heuristic_knowledge_edge(self, new_node: KnowledgeNode) -> KnowledgeEdge | None:
        if not new_node.unit.strip():
            return None
        existing_nodes = getattr(self.knowledge_graph, "nodes", [])[:-1]
        new_node_kind = self._knowledge_node_kind(new_node)
        if new_node_kind != "query":
            return None
        for existing_node in existing_nodes:
            if existing_node.unit != new_node.unit:
                continue
            if self._knowledge_node_kind(existing_node) != "unit":
                continue
            return KnowledgeEdge(from_id=existing_node.id, to_id=new_node.id, relation="aprofunda")
        return None

    def _knowledge_node_kind(self, node: KnowledgeNode) -> str:
        data = node.data if isinstance(node.data, dict) else {}
        if "unit_name" in data:
            return "unit"
        if "query_id" in data or "template_id" in data:
            return "query"
        return "unknown"

    def _log_execution(self, entry: dict[str, object]) -> None:
        log = getattr(self, "_execution_log", None)
        if log is None:
            self._execution_log = []
            log = self._execution_log
        normalized = {str(key): str(value) for key, value in entry.items()}
        log.append(normalized)
        if len(log) > 25:
            self._execution_log = log[-25:]

    def _find_unit(self, unit_name: str):
        unit = next((item for item in getattr(self, "units", []) if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")
        return unit

    def _requirement_exists(self, requirement_id: str) -> bool:
        normalized_id = requirement_id.strip()
        if not normalized_id:
            return False
        return self._find_requirement_in_graph(normalized_id) is not None

    def _append_requirements_to_node(
        self,
        node: KnowledgeNode,
        requirements: list[dict[str, object]],
    ) -> None:
        for requirement in requirements:
            requirement_id = str(requirement.get("id", "")).strip()
            if not requirement_id:
                continue
            if self._requirement_exists(requirement_id):
                continue
            node.next_requirements.append(requirement)

    def _set_core_cache(self, key: str, payload: object) -> None:
        cache = getattr(self, "_core_cache", None)
        if cache is None:
            self._core_cache = {}
            cache = self._core_cache
        cache[key] = payload

    def _extract_layer_metrics(self, analysis: object, *, depth: str) -> dict[str, object]:
        columns = getattr(analysis, "columns", {}) or {}
        payload_columns: dict[str, object] = {}
        for column_name, column in columns.items():
            payload_columns[column_name] = self._serialize_for_cache(getattr(column, f"{depth}_metrics"))
        standardized = getattr(analysis, "standardized", None)
        return {
            "unit_name": getattr(analysis, "unit_name", ""),
            "depth": depth,
            "row_count": getattr(standardized, "row_count", None),
            "column_order": list(getattr(standardized, "column_order", ()) or ()),
            "columns": payload_columns,
        }

    def _extract_heuristics(self, analysis: object) -> dict[str, object]:
        columns = getattr(analysis, "columns", {}) or {}
        payload_columns: dict[str, object] = {}
        for column_name, column in columns.items():
            payload_columns[column_name] = self._serialize_for_cache(getattr(column, "heuristics", ()))
        return {
            "unit_name": getattr(analysis, "unit_name", ""),
            "depth": "heuristics",
            "columns": payload_columns,
        }

    def _serialize_for_cache(self, payload: object) -> object:
        if hasattr(payload, "__dataclass_fields__"):
            return {key: self._serialize_for_cache(value) for key, value in asdict(payload).items()}
        if isinstance(payload, dict):
            return {str(key): self._serialize_for_cache(value) for key, value in payload.items()}
        if isinstance(payload, (list, tuple)):
            return [self._serialize_for_cache(item) for item in payload]
        return payload

    def _column_value_sets(self, structure: object, rows: list[tuple[object, ...]]) -> dict[str, set[str]]:
        columns = list(getattr(structure, "columns", ()) or ())
        result = {column.name: set() for column in columns}
        for row in rows:
            for index, column in enumerate(columns):
                if index >= len(row):
                    continue
                value = row[index]
                if value is None or value == "":
                    continue
                result[column.name].add(str(value))
        return result

    def _infer_join_keys(self, unit_a: str, structure_a: object, unit_b: str, structure_b: object) -> list[str]:
        columns_a = {column.name for column in getattr(structure_a, "columns", ())}
        columns_b = {column.name for column in getattr(structure_b, "columns", ())}
        candidates: list[tuple[str, str]] = []
        for same_name in sorted(columns_a & columns_b):
            normalized = normalize_identifier(same_name)
            if normalized.endswith("id") or normalized.endswith("key") or normalized.endswith("code") or normalized.endswith("ssn"):
                candidates.append((f"{unit_a}.{same_name}", f"{unit_b}.{same_name}"))
        for column_name in sorted(columns_a):
            if not column_name.endswith("_id"):
                continue
            prefix = column_name[:-3]
            if "id" in columns_b and normalize_entity_name(unit_b) == normalize_entity_name(prefix):
                candidates.append((f"{unit_a}.{column_name}", f"{unit_b}.id"))
        for column_name in sorted(columns_b):
            if not column_name.endswith("_id"):
                continue
            prefix = column_name[:-3]
            if "id" in columns_a and normalize_entity_name(unit_a) == normalize_entity_name(prefix):
                candidates.append((f"{unit_b}.{column_name}", f"{unit_a}.id"))
        for same_name in sorted(columns_a & columns_b):
            if same_name in {"id"}:
                continue
            candidates.append((f"{unit_a}.{same_name}", f"{unit_b}.{same_name}"))
        unique = []
        seen = set()
        for left, right in candidates:
            key = f"{left}={right}"
            if key not in seen:
                seen.add(key)
                unique.append(key)
        return unique

    def _find_compatible_units(self, unit_name: str, columns: list[str]) -> list[str]:
        compatible: list[str] = []
        normalized_columns = {normalize_identifier(column) for column in columns}
        for unit in getattr(self, "units", []):
            if unit.unit_name == unit_name:
                continue
            try:
                structure = unit.get_structure()
            except Exception:
                continue
            other_columns = _column_names_from_structure(structure)
            overlap = normalized_columns & {normalize_identifier(column) for column in other_columns}
            if overlap:
                compatible.append(unit.unit_name)
        return compatible

    def _build_horizontal_requirements(self, payload: dict[str, object]) -> list[dict[str, object]]:
        units = list(payload.get("units", []))
        join_keys = list(payload.get("join_keys", []))
        if len(units) != 2 or not join_keys:
            return []
        first_join = join_keys[0]
        if "=" not in first_join:
            return []
        left, right = first_join.split("=", 1)
        left_unit, left_column = left.split(".", 1)
        right_unit, right_column = right.split(".", 1)
        sql = (
            f"SELECT * FROM {left_unit} a "
            f"JOIN {right_unit} b ON a.{left_column} = b.{right_column} "
            "LIMIT 50"
        )
        return [
            {
                "id": f"req_{left_unit}_{right_unit}_{left_column}_{right_column}",
                "kind": "query",
                "units": units,
                "description": f"Executar JOIN entre {left_unit} e {right_unit}",
                "reason": "join_keys observadas na análise horizontal",
                "suggested_action": {
                    "action": "request_new_query",
                    "description": f"cruzar {left_unit} com {right_unit}",
                    "suggested_sql": sql,
                },
                "status": "pending",
                "source_node_id": "",
            }
        ]

    def _sanitize_knowledge_payload(self, payload: dict[str, object]) -> dict[str, object]:
        sanitized = {str(key): self._serialize_for_cache(value) for key, value in payload.items() if key != "rows"}
        if "sample_entities" not in sanitized:
            sanitized["sample_entities"] = extract_sample_entities(payload.get("columns"), payload.get("rows"), max_entities=10)
        return sanitized

    def _sanitize_requirements(self, requirements: object) -> list[dict[str, object]]:
        if not isinstance(requirements, list):
            return []
        sanitized: list[dict[str, object]] = []
        for item in requirements:
            if isinstance(item, dict):
                sanitized.append({str(key): self._serialize_for_cache(value) for key, value in item.items()})
        return sanitized

    def _schema_for_table(self, table_name: str) -> dict[str, object]:
        unit = next((item for item in self.units if item.unit_name == table_name), None)
        if unit is None:
            raise ValueError(f"Tabela/unidade não encontrada: {table_name}")
        structure = unit.get_structure()
        return {
            "table": table_name,
            "columns": [
                {
                    "name": column.name,
                    "position": column.position,
                    "raw_type": column.raw_type,
                    "raw_attributes": column.raw_attributes,
                }
                for column in structure.columns
            ],
        }

    def _run_catalog_query(self, query_id: str) -> dict[str, object]:
        if self.source_type != "sqlite":
            raise ValueError("Ação query está disponível apenas para fontes SQLite neste MVP.")
        sql = self.catalog_for_session().get(query_id)
        if sql is None:
            raise ValueError(f"Query do catálogo não encontrada: {query_id}")
        with sqlite3.connect(self.source_path) as connection:
            cursor = connection.execute(sql)
            column_names = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchmany(200)
        payload = {
            "cache_key": f"query:{query_id}",
            "query_id": query_id,
            "action": "query",
            "status": "cached",
            "sql": sql,
            "units": extract_units_from_sql(sql),
            "columns": column_names,
            "rows": rows,
            "row_count_preview": len(rows),
            "truncated": len(rows) == 200,
        }
        payload |= build_operational_summary_for_query(
            action="query",
            cache_key=str(payload["cache_key"]),
            units=list(payload["units"]),
            columns=column_names,
            rows=rows,
            row_count_preview=len(rows),
            truncated=bool(payload["truncated"]),
            query_id=query_id,
        )
        self._set_core_cache(str(payload["cache_key"]), payload)
        return payload

    def catalog_for_session(self) -> dict[str, str]:
        return {
            **QUERY_CATALOG,
            **getattr(self, "_session_query_catalog", {}),
        }

    def _register_session_query(self, *, description: str, suggested_sql: str) -> dict[str, object]:
        if self.source_type != "sqlite":
            raise ValueError("Queries novas em sessão estão disponíveis apenas para fontes SQLite neste MVP.")
        validated_sql = validate_select_sql_text(suggested_sql)
        validate_sql_by_execution(self.source_path, validated_sql)
        preview = self._validate_and_preview_sql(validated_sql)
        query_id = generate_query_id(description, existing_ids=set(self.catalog_for_session().keys()))
        self._session_query_catalog[query_id] = validated_sql
        candidate = (query_id, validated_sql)
        if candidate not in self._candidate_queries:
            self._candidate_queries.append(candidate)
        units = extract_units_from_sql(validated_sql)
        payload = {
            "action": "request_new_query",
            "status": "cached",
            "cache_key": f"query:{query_id}",
            "query_id": query_id,
            "description": description.strip(),
            "sql": validated_sql,
            "units": units,
            "columns": preview["columns"],
            "rows": preview["rows"],
            "row_count_preview": preview["row_count_preview"],
            "truncated": preview["truncated"],
            "registered_in_session": True,
        }
        payload |= build_operational_summary_for_query(
            action="request_new_query",
            cache_key=str(payload["cache_key"]),
            units=units,
            columns=preview["columns"],
            rows=preview["rows"],
            row_count_preview=int(preview["row_count_preview"]),
            truncated=bool(preview["truncated"]),
            query_id=query_id,
        )
        self._set_core_cache(str(payload["cache_key"]), payload)
        return payload

    def _validate_and_preview_sql(self, sql: str) -> dict[str, object]:
        with sqlite3.connect(self.source_path) as connection:
            cursor = connection.execute(sql)
            column_names = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchmany(200)
        if not rows:
            raise ValueError("A nova query foi rejeitada porque não retornou linhas.")
        return {
            "columns": column_names,
            "rows": rows,
            "row_count_preview": len(rows),
            "truncated": len(rows) == 200,
        }

    def _person_like_units(self) -> list[tuple[str, dict[str, str]]]:
        matches: list[tuple[str, dict[str, str]]] = []
        for unit in getattr(self, "units", []):
            try:
                structure = unit.get_structure()
            except Exception:
                continue
            columns = _column_names_from_structure(structure)
            normalized = {column.lower(): column for column in columns}
            has_name = any(key in normalized for key in ("name",))
            has_street_name = any(key in normalized for key in ("address_street_name", "street_name"))
            has_address_number = "address_number" in normalized
            has_generic_address = any(key in normalized for key in ("address", "street"))
            has_identity = any(key in normalized for key in ("person_id", "id"))
            if not ((has_name or has_identity) and (has_street_name or has_generic_address)):
                continue
            mapping: dict[str, str] = {}
            for key in ("name", "address_street_name", "street_name", "address_number", "address", "street", "person_id", "id"):
                if key in normalized:
                    mapping[key] = normalized[key]
            matches.append((unit.unit_name, mapping))
        return matches

    def _textual_clue_columns(self, columns: list[str]) -> list[str]:
        preferred = ("description", "transcript", "text", "note", "content", "summary", "details")
        selected: list[str] = []
        for column in columns:
            lowered = column.lower()
            if any(token in lowered for token in preferred):
                selected.append(column)
        if selected:
            return selected
        return [column for column in columns if any(token in column.lower() for token in ("desc", "text", "note", "content", "detail", "summary"))]

    def _build_requirements_from_textual_clues(
        self,
        *,
        result: dict[str, object],
        source_node_id: str,
    ) -> list[dict[str, object]]:
        columns = [str(item) for item in result.get("columns", [])] if isinstance(result.get("columns"), list) else []
        rows = result.get("rows", [])
        units = result.get("units", [])
        if not columns or not isinstance(rows, list) or not isinstance(units, list) or not units:
            return []
        clue_columns = self._textual_clue_columns(columns)
        if not clue_columns:
            return []
        person_like_units = self._person_like_units()
        if not person_like_units:
            return []

        def append_requirement(requirement: dict[str, object], bucket: list[dict[str, object]]) -> None:
            if not self._requirement_exists(str(requirement.get("id", ""))):
                bucket.append(requirement)

        requirements: list[dict[str, object]] = []
        patterns = {
            "last_house": re.compile(r'last house on\s+(["\'])(.*?)\1', flags=re.IGNORECASE),
            "named": re.compile(r"\bnamed\s+([A-Za-z][A-Za-z0-9' -]+?)(?:,|\s+lives|\s+live|\.|$)", flags=re.IGNORECASE),
            "lives_somewhere": re.compile(r'lives somewhere on\s+(["\'])(.*?)\1', flags=re.IGNORECASE),
            "lives_on": re.compile(r'lives (?:at|on)\s+(["\'])(.*?)\1', flags=re.IGNORECASE),
        }

        for row in rows[:20]:
            if not isinstance(row, (list, tuple)):
                continue
            for clue_column in clue_columns:
                try:
                    clue_index = columns.index(clue_column)
                except ValueError:
                    continue
                if clue_index >= len(row) or row[clue_index] is None:
                    continue
                text = str(row[clue_index])
                if not text.strip():
                    continue
                last_house_streets = [match[1].strip() for match in patterns["last_house"].findall(text)]
                named_people = [match.strip() for match in patterns["named"].findall(text)]
                somewhere_streets = [match[1].strip() for match in patterns["lives_somewhere"].findall(text)]
                generic_streets = [match[1].strip() for match in patterns["lives_on"].findall(text)]

                for unit_name, mapping in person_like_units:
                    street_column = mapping.get("address_street_name") or mapping.get("street_name") or mapping.get("street") or mapping.get("address")
                    number_column = mapping.get("address_number")
                    name_column = mapping.get("name")
                    if not street_column:
                        continue
                    for street in last_house_streets:
                        safe = re.sub(r"[^a-z0-9]+", "_", street.lower()).strip("_")[:40] or "street"
                        sql = (
                            f"SELECT * FROM {unit_name} WHERE {street_column} = {self._quote_sql_literal(street)} "
                            f"{f'ORDER BY {number_column} DESC ' if number_column else ''}LIMIT 1"
                        )
                        append_requirement(
                            {
                                "id": f"req_{source_node_id}_clue_last_house_{safe}",
                                "kind": "query",
                                "role": "textual_clue",
                                "units": [unit_name],
                                "description": f"Buscar última residência em {street}",
                                "reason": "pista textual extraída de resultado anterior",
                                "source_node_id": source_node_id,
                                "suggested_action": {
                                    "action": "request_new_query",
                                    "description": f"buscar última casa em {street}",
                                    "suggested_sql": sql,
                                },
                                "status": "pending",
                            },
                            requirements,
                        )
                    for street in somewhere_streets + generic_streets:
                        safe = re.sub(r"[^a-z0-9]+", "_", street.lower()).strip("_")[:40] or "street"
                        if name_column and named_people:
                            for person_name in named_people:
                                name_safe = re.sub(r"[^a-z0-9]+", "_", person_name.lower()).strip("_")[:24] or "name"
                                escaped_name = str(person_name).replace("'", "''")
                                sql = (
                                    f"SELECT * FROM {unit_name} WHERE {name_column} LIKE '%{escaped_name}%' "
                                    f"AND {street_column} = {self._quote_sql_literal(street)} LIMIT 50"
                                )
                                append_requirement(
                                    {
                                        "id": f"req_{source_node_id}_clue_named_{name_safe}_{safe}",
                                        "kind": "query",
                                        "role": "textual_clue",
                                        "units": [unit_name],
                                        "description": f"Buscar {person_name} em {street}",
                                        "reason": "pista textual extraída de resultado anterior",
                                        "source_node_id": source_node_id,
                                        "suggested_action": {
                                            "action": "request_new_query",
                                            "description": f"buscar {person_name} em {street}",
                                            "suggested_sql": sql,
                                        },
                                        "status": "pending",
                                    },
                                    requirements,
                                )
                        sql = f"SELECT * FROM {unit_name} WHERE {street_column} = {self._quote_sql_literal(street)} LIMIT 50"
                        append_requirement(
                            {
                                "id": f"req_{source_node_id}_clue_street_{safe}",
                                "kind": "query",
                                "role": "textual_clue",
                                "units": [unit_name],
                                "description": f"Buscar pessoas relacionadas a {street}",
                                "reason": "pista textual extraída de resultado anterior",
                                "source_node_id": source_node_id,
                                "suggested_action": {
                                    "action": "request_new_query",
                                    "description": f"buscar pessoas em {street}",
                                    "suggested_sql": sql,
                                },
                                "status": "pending",
                            },
                            requirements,
                        )
        return requirements

    def _build_related_entity_requirements(
        self,
        *,
        result: dict[str, object],
        source_node_id: str,
    ) -> list[dict[str, object]]:
        columns = [str(item) for item in result.get("columns", [])] if isinstance(result.get("columns"), list) else []
        rows = result.get("rows", [])
        units = result.get("units", [])
        if not columns or not isinstance(rows, list) or not isinstance(units, list) or len(units) != 1:
            return []
        if len(rows) == 0 or len(rows) > 5:
            return []
        source_unit = str(units[0]).strip()
        if not source_unit:
            return []

        source_entity = normalize_entity_name(source_unit)
        source_structure = None
        try:
            source_structure = self._find_unit(source_unit).get_structure()
        except Exception:
            source_structure = None
        source_columns = _column_names_from_structure(source_structure) if source_structure is not None else columns
        source_column_set = {column.lower() for column in source_columns}

        observed_keys: list[dict[str, object]] = []
        seen_observed: set[tuple[str, str]] = set()
        for row in rows[:5]:
            if not isinstance(row, (list, tuple)):
                continue
            for index, column in enumerate(columns):
                if index >= len(row):
                    continue
                value = row[index]
                if value is None or str(value).strip() == "":
                    continue
                normalized_column = str(column).strip().lower()
                if not (
                    normalized_column == "id"
                    or normalized_column.endswith("_id")
                    or normalized_column.endswith("_key")
                    or normalized_column.endswith("_code")
                    or normalized_column in {"key", "ssn", "code"}
                ):
                    continue
                dedupe_key = (normalized_column, str(value).strip())
                if dedupe_key in seen_observed:
                    continue
                seen_observed.add(dedupe_key)
                observed_keys.append(
                    {
                        "column": str(column).strip(),
                        "normalized_column": normalized_column,
                        "value": value,
                    }
                )
        if not observed_keys:
            return []

        executed_filters: set[tuple[str, str, str]] = set()
        graph = getattr(self, "knowledge_graph", None)
        if graph is not None:
            for node in getattr(graph, "nodes", []):
                node_units = getattr(node, "units", []) or ([getattr(node, "unit", "")] if getattr(node, "unit", "") else [])
                node_unit = str(node_units[0]).strip() if node_units else ""
                for requirement in getattr(node, "next_requirements", []):
                    suggested = requirement.get("suggested_action")
                    if not isinstance(suggested, dict):
                        continue
                    sql = str(suggested.get("suggested_sql", "")).strip()
                    if not sql:
                        continue
                    extracted_units = extract_units_from_sql(sql)
                    target_unit = str(extracted_units[0]).strip() if extracted_units else node_unit
                    filter_payload = requirement.get("filter")
                    if isinstance(filter_payload, dict):
                        filter_column = str(filter_payload.get("column", "")).strip().lower()
                        filter_value = str(filter_payload.get("value", "")).strip()
                        if target_unit and filter_column and filter_value:
                            executed_filters.add((target_unit, filter_column, filter_value))
                    if str(requirement.get("status", "")).strip().lower() == "resolved":
                        sql_match = re.search(
                            r"\bWHERE\s+([A-Za-z0-9_]+)\s*=\s*(?:'([^']*(?:''[^']*)*)'|([0-9]+(?:\.[0-9]+)?))",
                            sql,
                            flags=re.IGNORECASE,
                        )
                        if sql_match and target_unit:
                            raw_value = sql_match.group(2) if sql_match.group(2) is not None else sql_match.group(3)
                            if raw_value is not None:
                                executed_filters.add(
                                    (
                                        target_unit,
                                        sql_match.group(1).strip().lower(),
                                        raw_value.replace("''", "'").strip(),
                                    )
                                )

        requirements: list[dict[str, object]] = []
        seen_targets: set[tuple[str, str, str]] = set()
        for unit in getattr(self, "units", []):
            target_unit = str(getattr(unit, "unit_name", "")).strip()
            if not target_unit or target_unit == source_unit:
                continue
            try:
                target_structure = unit.get_structure()
            except Exception:
                continue
            target_columns = _column_names_from_structure(target_structure)
            normalized_target_columns = {column.lower(): column for column in target_columns}
            target_entity = normalize_entity_name(target_unit)

            for observed in observed_keys:
                observed_column = str(observed["column"])
                normalized_observed_column = str(observed["normalized_column"])
                observed_value = observed["value"]
                observed_value_text = str(observed_value).strip()
                if not observed_value_text:
                    continue

                candidate_target_columns: list[str] = []
                if normalized_observed_column == "id":
                    for candidate in (
                        f"{source_entity}_id",
                        f"{source_entity}id",
                        f"{source_entity}_key",
                        f"{source_entity}key",
                        source_entity,
                    ):
                        match = normalized_target_columns.get(candidate)
                        if match and match not in candidate_target_columns:
                            candidate_target_columns.append(match)
                elif normalized_observed_column in {"ssn", "code", "key"} or normalized_observed_column.endswith(("_id", "_key", "_code")):
                    same_name = normalized_target_columns.get(normalized_observed_column)
                    if same_name and same_name not in candidate_target_columns:
                        candidate_target_columns.append(same_name)
                    if normalized_observed_column.endswith(("_id", "_key", "_code")):
                        prefix = normalize_entity_name(observed_column)
                        if prefix and prefix == target_entity:
                            target_id = normalized_target_columns.get("id")
                            if target_id and target_id not in candidate_target_columns:
                                candidate_target_columns.append(target_id)

                for target_column in candidate_target_columns:
                    target_key = (target_unit, target_column.lower(), observed_value_text)
                    if target_key in seen_targets or target_key in executed_filters:
                        continue
                    if target_unit == source_unit and target_column.lower() in source_column_set:
                        continue
                    seen_targets.add(target_key)
                    safe_target_unit = re.sub(r"[^a-z0-9]+", "_", target_unit.lower()).strip("_") or "unit"
                    safe_target_column = re.sub(r"[^a-z0-9]+", "_", target_column.lower()).strip("_") or "column"
                    safe_value = re.sub(r"[^a-z0-9]+", "_", observed_value_text.lower()).strip("_")[:40] or "value"
                    select_clause = self._build_select_columns_for_filtered_query(target_unit, target_column)
                    requirements.append(
                        {
                            "id": f"req_{source_node_id}_related_{safe_target_unit}_{safe_target_column}_{safe_value}",
                            "kind": "query",
                            "role": "related_entity",
                            "units": [target_unit],
                            "description": f"Consultar registros relacionados por {target_column} = {observed_value_text}",
                            "reason": "chave observada em entidade retornada",
                            "source_node_id": source_node_id,
                            "suggested_action": {
                                "action": "request_new_query",
                                "description": f"consultar relacionados em {target_unit} por {target_column}",
                                "suggested_sql": (
                                    f"SELECT {select_clause} FROM {target_unit} "
                                    f"WHERE {target_column} = {self._quote_sql_literal(observed_value)} LIMIT 50"
                                ),
                            },
                            "status": "pending",
                        }
                    )

        return requirements


def detect_source_type(source_path: str) -> str:
    suffix = Path(source_path).suffix.lower()
    source_type = SUPPORTED_SUFFIXES.get(suffix)
    if source_type is None:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f"Extensão não suportada: {suffix or '<sem extensão>'}. Use {supported}.")
    return source_type


def resolve_source(source_type: str, source_path: str):
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Caminho não encontrado: {path}")
    if not path.is_file():
        raise ValueError(f"O caminho deve apontar para um arquivo: {path}")
    if source_type == "csv":
        return CSVDataSource(str(path))
    if source_type == "parquet":
        return ParquetDataSource(str(path))
    if source_type == "sqlite":
        return SQLiteDataSource(str(path))
    raise ValueError(f"Tipo de origem não suportado: {source_type}")


def build_interface_prompt(
    *,
    source_path: str,
    source_type: str,
    history: list[dict[str, str]],
    user_text: str,
    result_context: str,
    structural_context: str,
    is_first_call: bool,
    pending_requirements: list[dict[str, object]] | None = None,
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "history": history[-3:],
        "is_first_call": is_first_call,
        "analysis_intent": detect_analysis_intent(user_text),
        "structural_context": structural_context,
        "user_message": user_text,
        "available_result": result_context,
        "pending_requirements": pending_requirements or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_orchestrator_prompt(
    *,
    source_path: str,
    source_type: str,
    unit_names: list[str],
    structural_context: str,
    history: list[dict[str, str]],
    user_text: str,
    compact_structural_context: str,
    is_first_call: bool,
    last_error: str | None = None,
    last_result: str | None = None,
    executed_queries: list[object] | None = None,
    query_catalog: list[str] | None = None,
    attempt_number: int = 1,
    execution_log: list[dict[str, str]] | None = None,
    knowledge_graph_context: str = "",
    available_cache_keys: list[str] | None = None,
    pending_requirements: list[dict[str, object]] | None = None,
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "unit_names": unit_names,
        "history": history[-3:],
        "is_first_call": is_first_call,
        "attempt_number": attempt_number,
        "analysis_intent": detect_analysis_intent(user_text),
        "user_message": user_text,
        "structural_context": structural_context if is_first_call else compact_structural_context,
        "last_error": last_error or "",
        "last_result": last_result or "",
        "last_result_summary": (last_result or "")[:300],
        "execution_log": execution_log or [],
        "knowledge_graph_context": knowledge_graph_context,
        "available_cache_keys": available_cache_keys or [],
        "pending_requirements": pending_requirements or [],
        "executed_queries": executed_queries or [],
        "query_catalog": query_catalog or sorted(set(QUERY_CATALOG.keys())),
        "analytic_templates": sorted(ANALYTIC_TEMPLATES.keys()),
        "allowed_actions": [
            {"action": "analyze_unit", "unit_name": "nome_da_tabela"},
            {"action": "analyze_vertical", "unit_name": "nome_da_tabela", "depth": "layer1"},
            {"action": "analyze_horizontal", "unit_a": "nome_a", "unit_b": "nome_b"},
            {"action": "recall", "key": "unit:nome_da_tabela"},
            {"action": "query", "query_id": "generic_query_id"},
            {
                "action": "template",
                "template_id": "group_feature_signature",
                "params": {
                    "group_expr": "...",
                    "feature_expr": "...",
                    "from_clause": "...",
                    "where_clause": "...",
                    "subfeature_expr": "",
                    "subfeature_group": "",
                },
            },
            {"action": "request_new_query", "description": "descricao", "suggested_sql": "SELECT ..."},
            {"action": "schema", "table": "nome_da_tabela"},
            {"action": "tables"},
            {"action": "done", "conclusion": "texto da conclusão"},
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_curator_prompt(
    *,
    user_message: str,
    available_units: list[str],
    full_context: str,
) -> str:
    payload = {
        "user_message": user_message,
        "available_units": available_units,
        "full_context": full_context,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def parse_orchestrator_json(raw_content: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta da orquestradora não é JSON válido: {raw_content}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Resposta da orquestradora deve ser um objeto JSON.")
    action = payload.get("action")
    if action == "tables":
        return {"action": "tables"}
    if action == "analyze_unit":
        unit_name = payload.get("unit_name")
        if not isinstance(unit_name, str) or not unit_name.strip():
            raise ValueError("Ação analyze_unit exige o campo 'unit_name'.")
        return {"action": "analyze_unit", "unit_name": unit_name.strip()}
    if action == "analyze_vertical":
        unit_name = payload.get("unit_name")
        depth = payload.get("depth")
        valid_depths = {"layer1", "layer2", "heuristics", "full"}
        if not isinstance(unit_name, str) or not unit_name.strip():
            raise ValueError("Ação analyze_vertical exige o campo 'unit_name'.")
        if not isinstance(depth, str) or depth.strip() not in valid_depths:
            raise ValueError("Ação analyze_vertical exige o campo 'depth' válido.")
        return {"action": "analyze_vertical", "unit_name": unit_name.strip(), "depth": depth.strip()}
    if action == "analyze_horizontal":
        unit_a = payload.get("unit_a")
        unit_b = payload.get("unit_b")
        if not isinstance(unit_a, str) or not unit_a.strip():
            raise ValueError("Ação analyze_horizontal exige o campo 'unit_a'.")
        if not isinstance(unit_b, str) or not unit_b.strip():
            raise ValueError("Ação analyze_horizontal exige o campo 'unit_b'.")
        return {"action": "analyze_horizontal", "unit_a": unit_a.strip(), "unit_b": unit_b.strip()}
    if action == "recall":
        key = payload.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Ação recall exige o campo 'key'.")
        return {"action": "recall", "key": key.strip()}
    if action == "schema":
        table = payload.get("table")
        if not isinstance(table, str) or not table.strip():
            raise ValueError("Ação schema exige o campo 'table'.")
        return {"action": "schema", "table": table.strip()}
    if action == "query":
        query_id = payload.get("query_id")
        if not isinstance(query_id, str) or not query_id.strip():
            raise ValueError("Ação query exige o campo 'query_id'.")
        normalized = query_id.strip()
        return {"action": "query", "query_id": normalized}
    if action == "template":
        template_id = payload.get("template_id")
        params = payload.get("params")
        if not isinstance(template_id, str) or not template_id.strip():
            raise ValueError("Ação template exige o campo 'template_id'.")
        if template_id.strip() not in ANALYTIC_TEMPLATES:
            raise ValueError(f"Template não encontrado: {template_id.strip()}")
        if not isinstance(params, dict):
            raise ValueError("Ação template exige o campo 'params' como objeto.")
        normalized_params = {str(key): str(value) for key, value in params.items()}
        return {"action": "template", "template_id": template_id.strip(), "params": normalized_params}
    if action == "request_new_query":
        description = payload.get("description")
        suggested_sql = payload.get("suggested_sql")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Ação request_new_query exige o campo 'description'.")
        if not isinstance(suggested_sql, str) or not suggested_sql.strip():
            raise ValueError("Ação request_new_query exige o campo 'suggested_sql'.")
        return {
            "action": "request_new_query",
            "description": description.strip(),
            "suggested_sql": suggested_sql.strip(),
        }
    if action == "done":
        conclusion = payload.get("conclusion")
        if not isinstance(conclusion, str) or not conclusion.strip():
            raise ValueError("Ação done exige o campo 'conclusion'.")
        return {"action": "done", "conclusion": conclusion.strip()}
    raise ValueError(f"Ação inválida da orquestradora: {action!r}")


def parse_curator_json(raw_content: str) -> dict[str, object]:
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta da curadora não é JSON válido: {raw_content}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Resposta da curadora deve ser um objeto JSON.")
    relevant_units = payload.get("relevant_units")
    curated_context = payload.get("curated_context")
    if not isinstance(relevant_units, list) or any(not isinstance(item, str) for item in relevant_units):
        raise ValueError("Resposta da curadora exige 'relevant_units' como lista de strings.")
    if not isinstance(curated_context, str) or not curated_context.strip():
        raise ValueError("Resposta da curadora exige 'curated_context' não vazio.")
    return {
        "relevant_units": [item.strip() for item in relevant_units if item.strip()],
        "curated_context": curated_context.strip(),
    }


def detect_analysis_intent(user_text: str) -> str:
    normalized = user_text.strip().lower()
    horizontal_keywords = (
        "entre ",
        "relação",
        "relacao",
        "cruz",
        "juntar",
        "ligação",
        "ligacao",
        "comparar",
        "conectar",
    )
    vertical_keywords = (
        "entender",
        "explorar",
        "analisar",
        "investigar",
        "aprofundar",
        "essa tabela",
        "esta tabela",
        "descobrir padrões",
        "descobrir padroes",
    )
    if any(keyword in normalized for keyword in horizontal_keywords):
        return "horizontal"
    if any(keyword in normalized for keyword in vertical_keywords):
        return "vertical"
    return "unknown"


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


def normalize_identifier(value: str) -> str:
    normalized = value.strip().lower()
    for suffix in ("_id", "_key", "_code"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def normalize_entity_name(value: str) -> str:
    normalized = normalize_identifier(value)
    if normalized.endswith("ies") and len(normalized) > 3:
        return f"{normalized[:-3]}y"
    if normalized.endswith("s") and not normalized.endswith("ss") and len(normalized) > 1:
        return normalized[:-1]
    return normalized


def _column_names_from_structure(structure: object) -> list[str]:
    return [str(getattr(column, "name", "")).strip() for column in getattr(structure, "columns", ()) if str(getattr(column, "name", "")).strip()]


def detect_candidate_key_columns(columns: list[str]) -> list[str]:
    candidates: list[str] = []
    for column in columns:
        normalized = column.lower()
        if normalized == "id" or normalized.endswith("_id") or normalized.endswith("_key") or normalized in {"key", "code", "ssn"}:
            candidates.append(column)
    return candidates


def detect_datetime_like_columns(columns: list[str], raw_types: dict[str, str] | None = None) -> list[str]:
    raw_types = raw_types or {}
    matches: list[str] = []
    for column in columns:
        normalized = column.lower()
        raw_type = raw_types.get(column, "").lower()
        if any(token in normalized for token in ("date", "time", "timestamp", "created_at", "updated_at")) or any(
            token in raw_type for token in ("date", "time")
        ):
            matches.append(column)
    return matches


def detect_numeric_columns(columns: list[str], raw_types: dict[str, str] | None = None, analysis: object | None = None) -> list[str]:
    raw_types = raw_types or {}
    matches: list[str] = []
    analysis_columns = getattr(analysis, "columns", {}) if analysis is not None else {}
    for column in columns:
        raw_type = raw_types.get(column, "").lower()
        metrics = getattr(analysis_columns.get(column), "layer1_metrics", {}) if isinstance(analysis_columns, dict) else {}
        numeric_ratio = float(metrics.get("numeric_ratio", 0.0)) if isinstance(metrics, dict) and metrics.get("numeric_ratio") is not None else 0.0
        if any(token in raw_type for token in ("int", "real", "float", "double", "numeric", "decimal")) or numeric_ratio >= 0.8:
            matches.append(column)
    return matches


def detect_text_columns(columns: list[str], raw_types: dict[str, str] | None = None, analysis: object | None = None) -> list[str]:
    raw_types = raw_types or {}
    matches: list[str] = []
    analysis_columns = getattr(analysis, "columns", {}) if analysis is not None else {}
    for column in columns:
        raw_type = raw_types.get(column, "").lower()
        metrics = getattr(analysis_columns.get(column), "layer1_metrics", {}) if isinstance(analysis_columns, dict) else {}
        avg_length = float(metrics.get("average_length", 0.0)) if isinstance(metrics, dict) and metrics.get("average_length") is not None else 0.0
        alpha_ratio = float(metrics.get("alpha_ratio", 0.0)) if isinstance(metrics, dict) and metrics.get("alpha_ratio") is not None else 0.0
        if any(token in raw_type for token in ("char", "text", "clob", "string")) or (avg_length >= 8 and alpha_ratio >= 0.3):
            matches.append(column)
    return matches


def detect_categorical_columns(columns: list[str], raw_types: dict[str, str] | None = None, analysis: object | None = None) -> list[str]:
    raw_types = raw_types or {}
    matches: list[str] = []
    analysis_columns = getattr(analysis, "columns", {}) if analysis is not None else {}
    for column in columns:
        if column in detect_candidate_key_columns(columns):
            continue
        raw_type = raw_types.get(column, "").lower()
        metrics = getattr(analysis_columns.get(column), "layer1_metrics", {}) if isinstance(analysis_columns, dict) else {}
        unique_ratio = float(metrics.get("unique_ratio", 1.0)) if isinstance(metrics, dict) and metrics.get("unique_ratio") is not None else 1.0
        if any(token in raw_type for token in ("char", "text", "string")) and unique_ratio <= 0.5:
            matches.append(column)
            continue
        normalized = column.lower()
        if normalized.endswith("_type") or normalized.endswith("_status") or normalized.endswith("_category") or normalized.endswith("_group"):
            matches.append(column)
    return matches


def classify_columns_from_structure(structure: object, analysis: object | None = None) -> dict[str, list[str]]:
    columns = _column_names_from_structure(structure)
    raw_types = {
        str(getattr(column, "name", "")).strip(): str(getattr(column, "raw_type", "") or "")
        for column in getattr(structure, "columns", ())
        if str(getattr(column, "name", "")).strip()
    }
    candidate_keys = detect_candidate_key_columns(columns)
    datetime_like = detect_datetime_like_columns(columns, raw_types=raw_types)
    numeric = detect_numeric_columns(columns, raw_types=raw_types, analysis=analysis)
    text = [column for column in detect_text_columns(columns, raw_types=raw_types, analysis=analysis) if column not in datetime_like]
    categorical = [column for column in detect_categorical_columns(columns, raw_types=raw_types, analysis=analysis) if column not in numeric and column not in datetime_like]
    return {
        "columns": columns,
        "candidate_key_columns": candidate_keys,
        "categorical_columns": categorical,
        "numeric_columns": numeric,
        "text_columns": text,
        "datetime_like_columns": datetime_like,
    }


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
    if classified["candidate_key_columns"]:
        notes.append("colunas candidatas a chave detectadas")
    if classified["datetime_like_columns"]:
        notes.append("colunas temporais detectadas")
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
            "candidate_key_columns": classified["candidate_key_columns"],
            "categorical_columns": classified["categorical_columns"],
            "numeric_columns": classified["numeric_columns"],
            "text_columns": classified["text_columns"],
            "datetime_like_columns": classified["datetime_like_columns"],
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
        "candidate_key_columns": detect_candidate_key_columns(columns),
        "categorical_columns": [],
        "numeric_columns": detect_numeric_columns(columns),
        "text_columns": detect_text_columns(columns),
        "datetime_like_columns": detect_datetime_like_columns(columns),
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
            {
                "id": f"req_recall_query_{query_id}",
                "kind": "recall",
                "units": units,
                "description": f"Recuperar detalhes da consulta {query_id}",
                "reason": "resultado já calculado e cacheado",
                "suggested_action": {"action": "recall", "key": cache_key},
                "status": "pending",
                "source_node_id": "",
            }
        ]
    return payload


def validate_select_sql_text(sql: str) -> str:
    normalized = " ".join(sql.strip().split())
    upper = normalized.upper()
    if not upper.startswith("SELECT "):
        raise ValueError("Apenas consultas SELECT são permitidas.")
    forbidden_tokens = [
        " INSERT ",
        " UPDATE ",
        " DELETE ",
        " DROP ",
        " ALTER ",
        " CREATE ",
        " ATTACH ",
        " DETACH ",
        " PRAGMA ",
        " REINDEX ",
        " VACUUM ",
        " TRUNCATE ",
    ]
    if ";" in normalized[:-1]:
        raise ValueError("Apenas uma instrução SELECT é permitida.")
    padded = f" {upper} "
    for token in forbidden_tokens:
        if token in padded:
            raise ValueError("Consulta rejeitada por conter comando não permitido.")
    return normalized


def validate_select_sql(sql: str) -> None:
    validate_select_sql_text(sql)


def build_sql_from_template(template_id: str, params: dict[str, str]) -> str:
    template = ANALYTIC_TEMPLATES.get(template_id)
    if not template:
        raise ValueError(f"Template não encontrado: {template_id}")
    return template.format(**params)


def validate_sql_by_execution(db_path: str, sql: str) -> None:
    test_sql = f"SELECT * FROM ({sql}) AS __cartographer_validation__ LIMIT 0"
    try:
        with sqlite3.connect(db_path) as connection:
            connection.execute(test_sql)
    except sqlite3.Error as exc:
        raise ValueError(f"Query rejeitada pelo SQLite: {exc}") from exc


def generate_query_id(description: str, *, existing_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", description.strip().lower()).strip("_")
    if not base:
        base = "session_query"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def print_session_query_candidates(session: OrchestratorSession) -> None:
    if not session._candidate_queries:
        return
    print("\n=== Queries candidatas para o catálogo permanente ===")
    for query_id, sql in session._candidate_queries:
        print(f'query_id: "{query_id}"')
        print(f'sql: "{sql}"')
    print("Revisar e adicionar manualmente ao QUERY_CATALOG se aprovado.")


def print_help() -> None:
    print(
        "\nComandos especiais:\n"
        "  sair   encerra a conversa\n"
        "  ajuda  mostra esta ajuda\n"
        "  mapa   mostra o grafo de conhecimento da sessão\n"
        "\nFora isso, escreva perguntas livres sobre a exploração do dataset.\n"
    )


def _prompt_source_path(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1].strip():
        return argv[1].strip()
    return input("Arquivo (CSV, SQLite ou Parquet): ").strip()


def compress_assistant_message(text: str, limit: int = 150) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return normalized[:limit]
    return normalized[: limit - 3].rstrip() + "..."


def render_tables_message(action_result: str) -> str:
    payload = json.loads(action_result)
    tables = payload.get("tables", [])
    return f"Tabelas disponíveis: {', '.join(str(item) for item in tables) if tables else 'nenhuma'}."


def render_schema_message(action_result: str) -> str:
    payload = json.loads(action_result)
    table = str(payload.get("table", ""))
    columns = payload.get("columns", [])
    rendered = []
    for column in columns:
        raw_type = column.get("raw_type")
        if raw_type:
            rendered.append(f"{column.get('name')} ({raw_type})")
        else:
            rendered.append(str(column.get("name")))
    return f"Schema de {table}: {', '.join(rendered) if rendered else 'sem colunas visíveis'}."


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv
    source_path = _prompt_source_path(args)
    if not source_path:
        print("Nenhum arquivo informado.")
        return 1

    try:
        session = OrchestratorSession(source_path)
        structural_context, opening = session.bootstrap()
    except Exception as exc:
        print(f"Erro ao iniciar a sessão: {exc}")
        return 1

    print("\nCartographer Orchestrator\n")
    print(opening)
    print_help()

    while True:
        try:
            user_text = input("\nvoce> ").strip()
        except (EOFError, KeyboardInterrupt):
            print_session_query_candidates(session)
            print("\nEncerrando.")
            return 0

        if not user_text:
            continue
        if user_text.lower() == "sair":
            print_session_query_candidates(session)
            return 0
        if user_text.lower() == "ajuda":
            print_help()
            continue
        if user_text.lower() == "mapa":
            print(f"\ncartographer> {session.render_knowledge_map()}")
            continue

        session.history.append({"role": "user", "content": user_text})
        last_error: str | None = None
        last_result: str | None = None
        executed_queries: list[object] = []
        handled = False

        for attempt_number in range(1, MAX_ATTEMPTS_PER_TURN + 1):
            try:
                cache_keys_before = set(session.available_cache_keys())
                action_payload = plan_deterministic_action(
                    session,
                    user_text,
                    last_result=last_result,
                    last_error=last_error,
                )
                if action_payload is None:
                    action_payload = session.orchestrate(
                        user_text,
                        structural_context,
                        last_error=last_error,
                        last_result=last_result,
                        executed_queries=executed_queries,
                        attempt_number=attempt_number,
                    )
                execution_result = session.execute_action(action_payload)
                cache_keys_after = set(session.available_cache_keys())
                logger.debug(
                    "planner_action=%s executed=%s new_cache_keys=%s",
                    action_payload,
                    True,
                    sorted(cache_keys_after - cache_keys_before),
                )
                last_error = None
                last_result = execution_result
                if action_payload["action"] == "query":
                    query_id = str(action_payload.get("query_id", "")).strip()
                    if query_id:
                        executed_queries.append({"query_id": query_id, "sql": ""})
                if action_payload["action"] == "request_new_query":
                    payload = json.loads(execution_result)
                    executed_queries.append({"query_id": str(payload.get("query_id", "")), "sql": str(payload.get("sql", ""))})
                if action_payload["action"] == "done":
                    final_text = session.interface_reply(
                        "Apresente a conclusão final ao usuário com base no texto da orquestradora.",
                        result_context=execution_result,
                    )
                    session.history.append({"role": "assistant", "content": compress_assistant_message(final_text)})
                    print(f"\ncartographer> {final_text}")
                    print_session_query_candidates(session)
                    return 0

                if action_payload["action"] == "tables":
                    reply = render_tables_message(execution_result)
                    session.history.append({"role": "assistant", "content": compress_assistant_message(reply)})
                    print(f"\ncartographer> {reply}")
                    handled = True
                    break

                if action_payload["action"] == "schema":
                    reply = render_schema_message(execution_result)
                    session.history.append({"role": "assistant", "content": compress_assistant_message(reply)})
                    print(f"\ncartographer> {reply}")
                    handled = True
                    break

                reply = session.interface_reply(
                    "Explique este resultado ao usuário, responda à pergunta atual e sugira o próximo passo.",
                    result_context=execution_result,
                )
                session.history.append({"role": "assistant", "content": compress_assistant_message(reply)})
                print(f"\ncartographer> {reply}")
                handled = True
                break
            except Exception as exc:
                last_error = f"Erro operacional: {exc}"
                if attempt_number >= MAX_ATTEMPTS_PER_TURN:
                    error_reply = session.interface_reply(
                        "Explique ao usuário que não foi possível executar a análise pedida após múltiplas tentativas e sugira uma reformulação.",
                        result_context=last_error,
                    )
                    session.history.append({"role": "assistant", "content": compress_assistant_message(error_reply)})
                    print(f"\ncartographer> {error_reply}")
                    handled = True
                    break

        if handled:
            continue


if __name__ == "__main__":
    raise SystemExit(main())
