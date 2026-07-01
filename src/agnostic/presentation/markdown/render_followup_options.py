from __future__ import annotations

import json


def summarize_result_context_for_user(result_context: str) -> str:
    try:
        payload = json.loads(result_context)
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    operational = payload.get("operational_summary")
    if isinstance(operational, dict):
        row_count = operational.get("row_count")
        if row_count is not None:
            return f"Concluí esta etapa e obtive {row_count} linhas no resultado."
    row_count_preview = payload.get("row_count_preview")
    if row_count_preview is not None:
        return f"Concluí esta etapa e obtive {row_count_preview} linhas no resultado."
    summary = payload.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return ""


def render_followup_options_message(
    *,
    result_context: str,
    options: list[dict[str, object]],
    suggested: dict[str, object] | None,
) -> str:
    if not options:
        return "Não consegui formular uma resposta confiável para este resultado. Escolha uma opção válida ou peça para eu reapresentar os caminhos."
    summary = summarize_result_context_for_user(result_context)
    lines = [summary] if summary else []
    if len(options) == 1:
        option = options[0]
        lines.append(f"A próxima ação disponível é: {str(option.get('display_text', '')).strip()}.")
    else:
        lines.append("Encontrei estes próximos passos estruturados:")
        for option in options:
            lines.append(f"{int(option.get('index', 0))}. {str(option.get('display_text', '')).strip()}")
    if isinstance(suggested, dict):
        if len(options) == 1:
            lines.append(f"Minha sugestão é seguir por {str(suggested.get('display_text', '')).strip()}.")
        else:
            lines.append(
                f"Minha sugestão é a opção {int(suggested.get('index', 0))}: {str(suggested.get('display_text', '')).strip()}."
            )
    lines.append("Responda sim ou não." if len(options) == 1 else "Escolha uma opção pelo número.")
    return "\n".join(line for line in lines if line)
