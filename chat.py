from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import json
import sys

from agnostic.ai.consult_ai import consult_ai
from agnostic.application import analyze_tabular_unit, summarize_tabular_analysis
from agnostic.config import load_app_config
from agnostic.infrastructure.ai.grok_client import build_ai_client_from_env
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.infrastructure.storage.csv_source import CSVDataSource
from agnostic.infrastructure.storage.parquet_source import ParquetDataSource
from agnostic.presentation.summaries.summarize_tabular_analysis import summarize_unit_metrics


SUPPORTED_SUFFIXES = {
    ".csv": "csv",
    ".parquet": "parquet",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
}


class ChatSession:
    def __init__(self, source_path: str) -> None:
        self.source_path = str(Path(source_path).expanduser().resolve())
        self.source_type = detect_source_type(self.source_path)
        self.source = resolve_source(self.source_type, self.source_path)
        self.units = self.source.list_units()
        if not self.units:
            raise ValueError("Nenhuma unidade tabular foi encontrada na origem informada.")

        self.analysis_by_unit: dict[str, object] = {}
        self.current_unit_name = self.units[0].unit_name
        self.ai_client = build_ai_client_from_env()

    def analyze_unit(self, unit_name: str) -> object:
        cached = self.analysis_by_unit.get(unit_name)
        if cached is not None:
            return cached
        unit = next((item for item in self.units if item.unit_name == unit_name), None)
        if unit is None:
            raise ValueError(f"Unidade não encontrada: {unit_name}")
        analysis = analyze_tabular_unit(
            unit,
            max_rows=load_app_config().analysis.max_rows_per_unit,
        )
        self.analysis_by_unit[unit_name] = analysis
        return analysis

    def bootstrap(self) -> tuple[object, str]:
        analysis = self.analyze_unit(self.current_unit_name)
        summary = summarize_tabular_analysis(analysis)
        guidance = self.ask_ai(
            "Explique o resultado inicial em linguagem humana e sugira o próximo passo mais útil para exploração."
        )
        return analysis, f"{summary}\n\nIA:\n{guidance}"

    def ask_ai(self, user_prompt: str, *, analysis: object | None = None) -> str:
        focus_analysis = analysis or self.analyze_unit(self.current_unit_name)
        system_prompt = build_system_prompt(
            source_path=self.source_path,
            source_type=self.source_type,
            unit_names=[unit.unit_name for unit in self.units],
            current_unit_name=self.current_unit_name,
            analysis=focus_analysis,
        )
        response = consult_ai(user_prompt, self.ai_client, system_prompt=system_prompt)
        return response.content

    def source_overview(self) -> str:
        names = [unit.unit_name for unit in self.units]
        return (
            f"Origem: {self.source_path}\n"
            f"Tipo detectado: {self.source_type}\n"
            f"Unidades disponíveis: {len(names)}\n"
            f"Foco atual: {self.current_unit_name}\n"
            f"Lista: {', '.join(names)}"
        )

    def unit_overview(self, unit_name: str) -> str:
        analysis = self.analyze_unit(unit_name)
        self.current_unit_name = unit_name
        metrics_summary = "\n".join(summarize_unit_metrics(analysis))
        guidance = self.ask_ai(
            "Explique esta unidade e recomende a próxima exploração mais promissora.",
            analysis=analysis,
        )
        return f"{summarize_tabular_analysis(analysis)}\n\nMétricas:\n{metrics_summary}\n\nIA:\n{guidance}"

    def column_overview(self, unit_name: str, column_name: str) -> str:
        analysis = self.analyze_unit(unit_name)
        self.current_unit_name = unit_name
        column = analysis.columns.get(column_name)
        if column is None:
            raise ValueError(f"Coluna não encontrada na unidade {unit_name}: {column_name}")

        payload = asdict(column)
        heuristics = [item["name"] for item in payload["heuristics"] if item.get("triggered")]
        response_lines = [
            f"Unidade: {unit_name}",
            f"Coluna: {column_name}",
            f"Signal: {payload['signal']:.4f}",
            f"Exploration score: {payload['exploration_score']:.4f}",
            f"Consistency score: {payload['consistency_score']:.4f}",
            f"Explicação do core: {payload['explanation']}",
            f"Ações sugeridas pelo core: {', '.join(payload['suggested_actions']) or 'nenhuma'}",
            f"Heurísticas acionadas: {', '.join(heuristics) if heuristics else 'nenhuma'}",
            "Layer 1:",
            json.dumps(payload["layer1_metrics"], ensure_ascii=False, indent=2),
            "Layer 2:",
            json.dumps(payload["layer2_metrics"], ensure_ascii=False, indent=2),
        ]
        guidance = self.ask_ai(
            f"Explique a coluna {column_name} com base nos resultados estruturais e sugira o próximo passo.",
            analysis=analysis,
        )
        response_lines.extend(["", "IA:", guidance])
        return "\n".join(response_lines)


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


def build_system_prompt(
    *,
    source_path: str,
    source_type: str,
    unit_names: list[str],
    current_unit_name: str,
    analysis: object,
) -> str:
    analysis_payload = asdict(analysis)
    compact_payload = {
        "unit_name": analysis_payload["unit_name"],
        "signal": analysis_payload["signal"],
        "explanation": analysis_payload["explanation"],
        "suggested_actions": analysis_payload["suggested_actions"],
        "standardized": {
            "row_count": analysis_payload["standardized"]["row_count"],
            "column_count": analysis_payload["standardized"]["column_count"],
            "column_order": analysis_payload["standardized"]["column_order"],
        },
        "ranked_units": analysis_payload["ranked_units"][:5],
        "columns": {
            name: {
                "signal": column["signal"],
                "exploration_score": column["exploration_score"],
                "consistency_score": column["consistency_score"],
                "explanation": column["explanation"],
                "suggested_actions": column["suggested_actions"],
                "layer1_metrics": column["layer1_metrics"],
                "layer2_metrics": column["layer2_metrics"],
                "heuristics": [
                    heuristic["name"]
                    for heuristic in column["heuristics"]
                    if heuristic.get("triggered")
                ],
            }
            for name, column in analysis_payload["columns"].items()
        },
    }
    return (
        "Você é o guia conversacional do Cartographer.\n"
        "Você nunca inventa análise estrutural e nunca substitui o core determinístico.\n"
        "Explique apenas o que já está presente no resultado fornecido.\n"
        "Quando sugerir próximos passos, limite-se a sugerir ações exploratórias como abrir uma unidade ou inspecionar uma coluna.\n"
        f"Origem: {source_path}\n"
        f"Tipo: {source_type}\n"
        f"Unidades disponíveis: {', '.join(unit_names)}\n"
        f"Unidade em foco: {current_unit_name}\n"
        "Resultado estrutural disponível:\n"
        f"{json.dumps(compact_payload, ensure_ascii=False, indent=2)}"
    )


def print_help() -> None:
    print(
        "\nComandos:\n"
        "  ajuda                     mostra esta ajuda\n"
        "  origem                    resume a origem carregada\n"
        "  unidades                  lista as unidades disponíveis\n"
        "  abrir <unidade>           executa o core para a unidade escolhida\n"
        "  coluna <unidade> <coluna> detalha uma coluna via core\n"
        "  ia <pergunta>             pede interpretação da IA sobre o foco atual\n"
        "  sair                      encerra a conversa\n"
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
        session = ChatSession(source_path)
        _, opening = session.bootstrap()
    except Exception as exc:  # noqa: BLE001
        print(f"Erro ao iniciar a sessão: {exc}")
        return 1

    print("\nCartographer Chat\n")
    print(session.source_overview())
    print()
    print(opening)
    print_help()

    while True:
        try:
            command = input("\ncartographer> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEncerrando.")
            return 0

        if not command:
            continue
        if command == "sair":
            return 0
        if command == "ajuda":
            print_help()
            continue
        if command == "origem":
            print(session.source_overview())
            continue
        if command == "unidades":
            print("\n".join(unit.unit_name for unit in session.units))
            continue
        if command.startswith("abrir "):
            unit_name = command[len("abrir ") :].strip()
            try:
                print(session.unit_overview(unit_name))
            except Exception as exc:  # noqa: BLE001
                print(f"Erro: {exc}")
            continue
        if command.startswith("coluna "):
            remainder = command[len("coluna ") :].strip()
            unit_name, separator, column_name = remainder.partition(" ")
            if not separator or not column_name.strip():
                print("Uso: coluna <unidade> <coluna>")
                continue
            try:
                print(session.column_overview(unit_name.strip(), column_name.strip()))
            except Exception as exc:  # noqa: BLE001
                print(f"Erro: {exc}")
            continue
        if command.startswith("ia "):
            prompt = command[len("ia ") :].strip()
            if not prompt:
                print("Uso: ia <pergunta>")
                continue
            try:
                print(session.ask_ai(prompt))
            except Exception as exc:  # noqa: BLE001
                print(f"Erro: {exc}")
            continue

        print("Comando não reconhecido. Digite 'ajuda' para ver as opções.")


if __name__ == "__main__":
    raise SystemExit(main())
