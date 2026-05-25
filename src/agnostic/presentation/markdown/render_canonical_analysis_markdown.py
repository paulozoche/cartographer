from __future__ import annotations

from typing import Any


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_canonical_analysis_markdown(record: dict[str, Any]) -> str:
    kind = str(record.get("kind", "analysis"))
    unit_name = str(record.get("unit_name", "unnamed"))
    persisted_at = str(record.get("persisted_at", "unknown"))
    payload = record.get("payload") or {}

    standardized = payload.get("standardized") or {}
    columns = payload.get("columns") or {}

    lines: list[str] = [
        "# Resumo da análise",
        "",
        f"- Tipo: `{kind}`",
        f"- Unidade: `{unit_name}`",
        f"- Persistido em: `{persisted_at}`",
        "",
    ]

    summary = payload.get("summary")
    if summary:
        lines.extend(["## Resumo humano", "", str(summary), ""])

    if standardized:
        lines.extend(
            [
                "## Estrutura padronizada",
                "",
                f"- Linhas: `{standardized.get('row_count', 'unknown')}`",
                f"- Colunas: `{standardized.get('column_count', 'unknown')}`",
            ]
        )
        column_order = standardized.get("column_order") or []
        if column_order:
            lines.append(f"- Ordem das colunas: `{', '.join(map(str, column_order))}`")
        lines.append("")

    if columns:
        lines.extend(["## Notas das colunas", ""])
        for column_name, column in columns.items():
            layer1 = column.get("layer1_metrics") or {}
            layer2 = column.get("layer2_metrics") or {}
            heuristics = column.get("heuristics") or []
            triggered = [item.get("name", "heuristic") for item in heuristics if item.get("triggered")]
            column_lines = [
                f"- **{column_name}**",
                f"  - Cardinalidade: `{layer1.get('cardinality', 'unknown')}`",
                f"  - Proporção de nulos: `{_format_value(layer1.get('null_ratio', 'unknown'))}`",
                f"  - Proporção de únicos: `{_format_value(layer1.get('unique_ratio', 'unknown'))}`",
                f"  - Proporção numérica: `{_format_value(layer2.get('numeric_ratio', 'unknown'))}`",
            ]
            if triggered:
                column_lines.append(f"  - Heurísticas acionadas: `{', '.join(triggered)}`")
            lines.extend(column_lines)
        lines.append("")

    lines.append("_Gerado por Analisador de Dados Agnóstico._")
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "_format_value",
    "render_canonical_analysis_markdown",
]
