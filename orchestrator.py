from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import os
import sqlite3
import sys
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
        self.history: list[dict[str, str]] = []
        self._full_structural_context: str | None = None
        self._curator_cache: dict[str, dict[str, object]] = {}
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
        analyses = self.analyze_all_units()
        structural_context = self.build_structural_context(analyses)
        self._full_structural_context = structural_context
        opening = self.interface_reply(
            "Explique o panorama inicial em linguagem humana e sugira o próximo passo de exploração.",
            result_context=structural_context,
            is_first_call=True,
        )
        return structural_context, opening

    def analyze_all_units(self) -> list[object]:
        analyses: list[object] = []
        max_rows = load_app_config().analysis.max_rows_per_unit
        for unit in self.units:
            analysis = self.analysis_by_unit.get(unit.unit_name)
            if analysis is None:
                analysis = analyze_tabular_unit(unit, max_rows=max_rows)
                self.analysis_by_unit[unit.unit_name] = analysis
            analyses.append(analysis)
        return analyses

    def build_structural_context(self, analyses: list[object]) -> str:
        sections = [
            f"Origem: {self.source_path}",
            f"Tipo detectado: {self.source_type}",
            f"Unidades detectadas: {', '.join(unit.unit_name for unit in self.units)}",
        ]
        for analysis in analyses:
            sections.append(summarize_tabular_analysis(analysis))
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
            full_context=self._full_structural_context or "",
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
            "Se o usuário pedir algo que exija ação, explique o que será investigado sem prometer resultado além do contexto recebido.\n"
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
        attempt_number: int = 1,
    ) -> dict[str, object]:
        system_prompt = (
            "Você é a IA Orquestradora do Cartographer.\n"
            "Responda somente com JSON válido, sem markdown e sem texto extra.\n"
            "A saída deve seguir exatamente um destes contratos:\n"
            '{"action":"query","query_id":"knot_type_distribution"}\n'
            '{"action":"schema","table":"nome_da_tabela"}\n'
            '{"action":"tables"}\n'
            '{"action":"done","conclusion":"texto"}\n'
            "Nunca converse com o usuário.\n"
            "Nunca gere SQL livremente.\n"
            "Para action=query, escolha apenas um query_id existente no catálogo disponível.\n"
            "Nunca emita 'done' quando o resultado ou contexto de erro contiver 'erro' ou 'error'.\n"
            "Em caso de erro de consulta, tente outro query_id do catálogo apenas se ele responder melhor à pergunta.\n"
            "Nunca emita 'done' quando a mensagem do usuário for apenas uma confirmação curta como 'sim', 'ok', 'continue' ou 'prossiga'.\n"
            "Se já existir resultado válido no turno atual, use esse resultado para decidir a próxima ação e não reexecute o mesmo query_id.\n"
            "Só emita 'done' quando houver uma conclusão real e bem-sucedida.\n"
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
        if action == "schema":
            table = str(action_payload["table"])
            return json.dumps(self._schema_for_table(table), ensure_ascii=False, indent=2)
        if action == "query":
            query_id = str(action_payload["query_id"])
            return json.dumps(self._run_catalog_query(query_id), ensure_ascii=False, indent=2, default=str)
        if action == "done":
            return str(action_payload["conclusion"])
        raise ValueError(f"Ação não suportada: {action}")

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
        sql = QUERY_CATALOG.get(query_id)
        if sql is None:
            raise ValueError(f"Query do catálogo não encontrada: {query_id}")
        with sqlite3.connect(self.source_path) as connection:
            cursor = connection.execute(sql)
            column_names = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchmany(50)
        return {
            "query_id": query_id,
            "sql": sql,
            "columns": column_names,
            "rows": rows,
            "row_count_preview": len(rows),
            "truncated": len(rows) == 50,
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
        "history": history[-6:],
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
    attempt_number: int = 1,
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "unit_names": unit_names,
        "history": history[-6:],
        "is_first_call": is_first_call,
        "attempt_number": attempt_number,
        "user_message": user_text,
        "structural_context": structural_context if is_first_call else compact_structural_context,
        "last_error": last_error or "",
        "last_result": last_result or "",
        "executed_queries": executed_queries or [],
        "query_catalog": sorted(QUERY_CATALOG.keys()),
        "allowed_actions": [
            {"action": "query", "query_id": "knot_type_distribution"},
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
        if normalized not in QUERY_CATALOG:
            raise ValueError(f"query_id inválido: {normalized}")
        return {"action": "query", "query_id": normalized}
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


def validate_select_sql(sql: str) -> None:
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


def print_help() -> None:
    print(
        "\nComandos especiais:\n"
        "  sair   encerra a conversa\n"
        "  ajuda  mostra esta ajuda\n"
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
            print("\nEncerrando.")
            return 0

        if not user_text:
            continue
        if user_text.lower() == "sair":
            return 0
        if user_text.lower() == "ajuda":
            print_help()
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
