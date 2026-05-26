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
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_TIMEOUT_SECONDS = 30.0
INTERFACE_MODEL = "deepseek-chat"
ORCHESTRATOR_MODEL = "deepseek-chat"


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
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY não encontrada. Verifique o arquivo .env.")
        self.interface_ai = DeepSeekClient(api_key=api_key, model=INTERFACE_MODEL)
        self.orchestrator_ai = DeepSeekClient(api_key=api_key, model=ORCHESTRATOR_MODEL)

    def bootstrap(self) -> tuple[str, str]:
        analyses = self.analyze_all_units()
        structural_context = self.build_structural_context(analyses)
        opening = self.interface_reply(
            "Explique o panorama inicial em linguagem humana e sugira o próximo passo de exploração.",
            result_context=structural_context,
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

    def interface_reply(self, user_text: str, *, result_context: str) -> str:
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
        )
        response = self.interface_ai.send(prompt, system_prompt=system_prompt)
        return response.content

    def orchestrate(self, user_text: str, structural_context: str) -> dict[str, object]:
        system_prompt = (
            "Você é a IA Orquestradora do Cartographer.\n"
            "Responda somente com JSON válido, sem markdown e sem texto extra.\n"
            "A saída deve seguir exatamente um destes contratos:\n"
            '{"action":"query","sql":"SELECT ..."}\n'
            '{"action":"schema","table":"nome_da_tabela"}\n'
            '{"action":"tables"}\n'
            '{"action":"done","conclusion":"texto"}\n'
            "Nunca converse com o usuário.\n"
            "Nunca produza SQL que não seja SELECT.\n"
        )
        prompt = build_orchestrator_prompt(
            source_path=self.source_path,
            source_type=self.source_type,
            unit_names=[unit.unit_name for unit in self.units],
            structural_context=structural_context,
            history=self.history,
            user_text=user_text,
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
            sql = str(action_payload["sql"])
            validate_select_sql(sql)
            return json.dumps(self._run_select(sql), ensure_ascii=False, indent=2, default=str)
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

    def _run_select(self, sql: str) -> dict[str, object]:
        if self.source_type != "sqlite":
            raise ValueError("Ação query está disponível apenas para fontes SQLite neste MVP.")
        with sqlite3.connect(self.source_path) as connection:
            cursor = connection.execute(sql)
            column_names = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchmany(50)
        return {
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
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "history": history[-6:],
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
) -> str:
    payload = {
        "source_path": source_path,
        "source_type": source_type,
        "unit_names": unit_names,
        "history": history[-6:],
        "user_message": user_text,
        "structural_context": structural_context,
        "allowed_actions": [
            {"action": "query", "sql": "SELECT ..."},
            {"action": "schema", "table": "nome_da_tabela"},
            {"action": "tables"},
            {"action": "done", "conclusion": "texto da conclusão"},
        ],
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
        sql = payload.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("Ação query exige o campo 'sql'.")
        validate_select_sql(sql)
        return {"action": "query", "sql": sql.strip()}
    if action == "done":
        conclusion = payload.get("conclusion")
        if not isinstance(conclusion, str) or not conclusion.strip():
            raise ValueError("Ação done exige o campo 'conclusion'.")
        return {"action": "done", "conclusion": conclusion.strip()}
    raise ValueError(f"Ação inválida da orquestradora: {action!r}")


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
        try:
            action_payload = session.orchestrate(user_text, structural_context)
            execution_result = session.execute_action(action_payload)
            if action_payload["action"] == "done":
                final_text = session.interface_reply(
                    "Apresente a conclusão final ao usuário com base no texto da orquestradora.",
                    result_context=execution_result,
                )
                session.history.append({"role": "assistant", "content": final_text})
                print(f"\ncartographer> {final_text}")
                return 0

            reply = session.interface_reply(
                "Explique este resultado ao usuário, responda à pergunta atual e sugira o próximo passo.",
                result_context=execution_result,
            )
            session.history.append({"role": "assistant", "content": reply})
            print(f"\ncartographer> {reply}")
        except Exception as exc:
            error_reply = session.interface_reply(
                "Explique o erro de forma útil e oriente o usuário sobre como continuar.",
                result_context=f"Erro operacional: {exc}",
            )
            session.history.append({"role": "assistant", "content": error_reply})
            print(f"\ncartographer> {error_reply}")


if __name__ == "__main__":
    raise SystemExit(main())
