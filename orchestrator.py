from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from agnostic.ai.ports.ai_orchestrator import AIResponse
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
QUERY_CATALOG = {
    "knot_type_distribution": """
        SELECT TYPE_CODE, COUNT(*) as total,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as pct
        FROM knot GROUP BY TYPE_CODE ORDER BY total DESC
    """,
    "avg_cords_per_khipu": """
        SELECT ROUND(AVG(cord_count), 2) as avg_cords
        FROM (SELECT KHIPU_ID, COUNT(*) as cord_count FROM cord GROUP BY KHIPU_ID)
    """,
    "knot_direction_by_type": """
        SELECT k.TYPE_CODE, k.DIRECTION, COUNT(*) as total
        FROM knot k GROUP BY k.TYPE_CODE, k.DIRECTION ORDER BY total DESC
    """,
    "khipu_by_region": """
        SELECT km.REGION, COUNT(*) as total
        FROM khipu_main km GROUP BY km.REGION ORDER BY total DESC
    """,
    "top_complex_khipus": """
        SELECT km.KHIPU_ID, km.PROVENANCE, km.REGION, COUNT(c.CORD_ID) as total_cords
        FROM khipu_main km JOIN cord c ON km.KHIPU_ID = c.KHIPU_ID
        GROUP BY km.KHIPU_ID ORDER BY total_cords DESC LIMIT 10
    """,
    "knot_position_vs_direction": """
        SELECT KNOT_POS, DIRECTION, COUNT(*) as total
        FROM knot GROUP BY KNOT_POS, DIRECTION ORDER BY KNOT_POS, total DESC
    """,
    "cord_colors_distribution": """
        SELECT AS_COLOR_CD, COUNT(*) as total
        FROM ascher_cord_color GROUP BY AS_COLOR_CD ORDER BY total DESC LIMIT 20
    """,
    "datacao_valida": """
        SELECT KHIPU_ID, EARLIEST_AGE, LATEST_AGE, REGION, PROVENANCE
        FROM khipu_main
        WHERE EARLIEST_AGE != '0000-00-00' AND EARLIEST_AGE IS NOT NULL
        ORDER BY EARLIEST_AGE
    """,
    "globalid_by_country": """
        SELECT "Country", COUNT(*) as total
        FROM globalid GROUP BY "Country" ORDER BY total DESC LIMIT 20
    """,
    "globalid_by_region": """
        SELECT "Political province/region", COUNT(*) as total
        FROM globalid GROUP BY "Political province/region" ORDER BY total DESC LIMIT 20
    """,
    "globalid_age_distribution": """
        SELECT
            MIN(CAST("Model_Age_SK75" AS REAL)) as min_age,
            MAX(CAST("Model_Age_SK75" AS REAL)) as max_age,
            AVG(CAST("Model_Age_SK75" AS REAL)) as avg_age
        FROM globalid WHERE "Model_Age_SK75" != ''
    """,
    "globalid_sample_types": """
        SELECT "Type", COUNT(*) as total
        FROM globalid GROUP BY "Type" ORDER BY total DESC
    """,
}
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


class DeepSeekAPIError(RuntimeError):
    pass


@dataclass
class KnowledgeNode:
    id: str
    label: str
    unit: str
    data: dict
    timestamp: str


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
                lines.append(f"- {node.id} [{node.unit}]: {node.label}")
        lines.extend(["", "### Arestas"])
        if not self.edges:
            lines.append("- Nenhuma aresta registrada.")
        else:
            for edge in self.edges:
                lines.append(f"- {edge.from_id} -> {edge.relation} -> {edge.to_id}")
        return "\n".join(lines)


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
        self._full_structural_context: str | None = None
        self._curator_cache: dict[str, dict[str, object]] = {}
        self._session_query_catalog: dict[str, str] = {}
        self._candidate_queries: list[tuple[str, str]] = []
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
            return cached

        unit = next((item for item in self.units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")

        max_rows = load_app_config().analysis.max_rows_per_unit
        analysis = analyze_tabular_unit(unit, max_rows=max_rows)
        self.analysis_by_unit[unit_name] = analysis
        if unit_name not in self.explored_paths:
            self.explored_paths.append(unit_name)
        return analysis

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
            "Se um resultado não estiver disponível no contexto, diga apenas 'não tenho esse dado, aguarde a execução'.\n"
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
            '"sim", "ok", "pode", "prossiga", "continue", "vai", "execute" após uma sugestão da Interface = executar a ação sugerida.\n'
            "Para identificar qual ação executar:\n"
            "1. Ler a última mensagem do histórico da Interface\n"
            "2. Identificar a ação sugerida (query, template, analyze_unit)\n"
            "3. Executar essa ação\n"
            "EXEMPLO LEI 5:\n"
            'Histórico mostra Interface sugerindo: "Quer que eu explore crime_scene_report?"\n'
            'Usuário responde: "sim"\n'
            'Resposta CORRETA: {"action": "analyze_unit", "unit_name": "crime_scene_report"}\n'
            'Resposta ERRADA: {"action": "tables"}\n'
            'Resposta ERRADA: {"action": "done", "conclusion": "..."}\n'
            'Nunca responder com "preciso de instrução clara" quando houver uma sugestão pendente no histórico.\n\n'
            "LEI 6 — NÃO REEXECUTE:\n"
            "Se já existe resultado válido no turno atual, não reexecute o mesmo query_id.\n"
            "Se o contexto já contém resultado de uma query sobre X, NÃO execute novamente a mesma query sobre X.\n"
            '"sim", "localize", "consulte", "faça" após um resultado significam AVANÇAR para o próximo passo lógico, não repetir.\n'
            "Use o resultado existente para decidir o próximo passo.\n"
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
        )
        response = self.orchestrator_ai.send(prompt, system_prompt=system_prompt)
        return parse_orchestrator_json(response.content)

    def execute_action(self, action_payload: dict[str, object]) -> str:
        action = action_payload["action"]
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
            payload = {
                "unit_name": unit_name,
                "summary": summarize_tabular_analysis(analysis),
                "metrics_summary": summarize_unit_metrics(analysis),
                "cached": True,
                "explored_paths": list(self.explored_paths),
            }
            self.update_knowledge_graph(payload, action="analyze_unit")
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "schema":
            table = str(action_payload["table"])
            return json.dumps(self._schema_for_table(table), ensure_ascii=False, indent=2)
        if action == "query":
            query_id = str(action_payload["query_id"])
            payload = self._run_catalog_query(query_id)
            self.update_knowledge_graph(payload, action="query")
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "template":
            template_id = str(action_payload["template_id"])
            params = dict(action_payload["params"])
            sql = build_sql_from_template(template_id, params)
            validate_select_sql_text(sql)
            validate_sql_by_execution(self.source_path, sql)
            payload = self._validate_and_preview_sql(sql) | {"template_id": template_id, "sql": sql}
            self.update_knowledge_graph(payload, action="template")
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if action == "request_new_query":
            description = str(action_payload["description"])
            suggested_sql = str(action_payload["suggested_sql"])
            return json.dumps(
                self._register_session_query(description=description, suggested_sql=suggested_sql),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
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
        return KnowledgeNode(
            id=node_id,
            label=label,
            unit=unit,
            data=result,
            timestamp=timestamp,
        )

    def _infer_unit_for_knowledge(self, result: dict[str, object], *, action: str) -> str:
        if action == "analyze_unit":
            unit_name = result.get("unit_name")
            if isinstance(unit_name, str) and unit_name.strip():
                return unit_name.strip()
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
        return {
            "query_id": query_id,
            "sql": sql,
            "columns": column_names,
            "rows": rows,
            "row_count_preview": len(rows),
            "truncated": len(rows) == 200,
        }

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
        return {
            "query_id": query_id,
            "description": description.strip(),
            "sql": validated_sql,
            "columns": preview["columns"],
            "rows": preview["rows"],
            "row_count_preview": preview["row_count_preview"],
            "truncated": preview["truncated"],
            "registered_in_session": True,
        }

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
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "history": history[-3:],
        "is_first_call": is_first_call,
        "structural_context": structural_context,
        "user_message": user_text,
        "available_result": result_context,
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
    executed_queries: list[str] | None = None,
    query_catalog: list[str] | None = None,
    attempt_number: int = 1,
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "unit_names": unit_names,
        "history": history[-3:],
        "is_first_call": is_first_call,
        "attempt_number": attempt_number,
        "user_message": user_text,
        "structural_context": structural_context if is_first_call else compact_structural_context,
        "last_error": last_error or "",
        "last_result": last_result or "",
        "executed_queries": executed_queries or [],
        "query_catalog": query_catalog or sorted(set(QUERY_CATALOG.keys())),
        "analytic_templates": sorted(ANALYTIC_TEMPLATES.keys()),
        "allowed_actions": [
            {"action": "analyze_unit", "unit_name": "nome_da_tabela"},
            {"action": "query", "query_id": "knot_type_distribution"},
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
        executed_queries: list[str] = []
        handled = False

        for attempt_number in range(1, MAX_ATTEMPTS_PER_TURN + 1):
            try:
                action_payload = session.orchestrate(
                    user_text,
                    structural_context,
                    last_error=last_error,
                    last_result=last_result,
                    executed_queries=executed_queries,
                    attempt_number=attempt_number,
                )
                execution_result = session.execute_action(action_payload)
                last_error = None
                last_result = execution_result
                if action_payload["action"] == "query":
                    query_id = str(action_payload.get("query_id", "")).strip()
                    if query_id and query_id not in executed_queries:
                        executed_queries.append(query_id)
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
