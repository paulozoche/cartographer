from __future__ import annotations

import json
from typing import Any


def preview(text: str | None, max_lines: int = 4) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return "Nenhum resumo humano disponível."
    clipped = []
    for line in lines[:max_lines]:
        clipped.append(line if len(line) <= 160 else f"{line[:157]}...")
    return "\n".join(clipped)


def bounded_json_preview(value: Any, *, max_bytes: int) -> str:
    rendered = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    encoded = rendered.encode("utf-8")
    if len(encoded) <= max_bytes:
        return rendered

    head_budget = max(max_bytes - 256, 256)
    clipped = encoded[:head_budget].decode("utf-8", errors="ignore").rstrip()
    omitted = len(encoded) - len(clipped.encode("utf-8"))
    notice = (
        "\n\n... [payload truncado para evitar explosão de saída; "
        f"{omitted} bytes omitidos de {len(encoded)} bytes totais]"
    )
    return clipped + notice


def source_overview_text(
    source: dict[str, Any],
    unit_names: list[str],
    unit_previews: list[dict[str, Any]] | None = None,
    selected_unit: str | None = None,
) -> str:
    unit_count = int(source.get("unit_count") or len(unit_names) or 0)
    lines = [f"{unit_count} tabelas detectadas"]
    return "\n".join(lines)


def source_preview_text(unit: dict[str, Any]) -> str:
    summary = str(unit.get("summary") or "").strip()
    if summary:
        return summary.splitlines()[0][:180]
    metrics = unit.get("metrics_summary") or []
    if metrics:
        return str(metrics[0])[:180]
    standardized = unit.get("standardized") or {}
    row_count = standardized.get("row_count")
    column_count = standardized.get("column_count")
    if row_count is not None and column_count is not None:
        return f"{row_count} linhas, {column_count} colunas."
    return "Prévia não disponível."


def executive_summary(data: dict[str, Any]) -> dict[str, str]:
    source_name = data.get("origem", {}).get("display_name") or data.get("display_name") or "origem"
    unit_count = len(data.get("tabela_nomes") or [])
    units = data.get("tabelas") or []
    focused_unit = (units[0].get("tabela_nome") if units else None) or data.get("tabela_nome") or "none"

    if data.get("status") == "ok":
        return {
            "headline": "Verificação de saúde concluída.",
            "facts": "Backend e interface estão ativos.",
            "next_step": "Volte para a análise da origem.",
            "narrative": "O sistema está saudável.",
        }

    if data.get("provider") and data.get("model"):
        return {
            "headline": f"Resposta da IA via {data['provider']}.",
            "facts": f"Modelo: {data['model']}. Chamadas restantes: {data.get('remaining_calls', 'n/a')}.",
            "next_step": "Refine o prompt ou troque de provedor se necessário.",
            "narrative": str(data.get("content") or "A IA retornou uma resposta."),
        }

    if data.get("tabela_nomes") or data.get("tabelas"):
        return {
            "headline": f"Origem {source_name} carregada.",
            "facts": f"{unit_count} unidades disponíveis. Foco: {focused_unit}.",
            "next_step": "Abra a unidade em foco.",
            "narrative": preview(data.get("summary")),
        }

    if data.get("tabela_nome") and data.get("standardized"):
        standardized = data["standardized"]
        return {
            "headline": f"Unidade {data['unit_name']} analisada.",
            "facts": f"{standardized['row_count']} linhas, {standardized['column_count']} colunas.",
            "next_step": "Inspecione a próxima unidade.",
            "narrative": preview(data.get("summary")),
        }

    return {
        "headline": "Resultado recebido.",
        "facts": "Abra o payload bruto para detalhes.",
        "next_step": "Use Explorar rápido para um salto maior.",
        "narrative": preview(data.get("summary")),
    }
