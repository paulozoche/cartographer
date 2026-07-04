import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import wmill

_BRAKE_MODULE_PATH = Path(__file__).with_name("freio_acelerador.py")
_BRAKE_SPEC = importlib.util.spec_from_file_location("freio_acelerador_local", _BRAKE_MODULE_PATH)
_BRAKE_MODULE = importlib.util.module_from_spec(_BRAKE_SPEC)
assert _BRAKE_SPEC.loader is not None
_BRAKE_SPEC.loader.exec_module(_BRAKE_MODULE)
trim_core_result = _BRAKE_MODULE.trim_core_result
_format_without_llm = _BRAKE_MODULE._format_without_llm

UNIVERSAL_SYSTEM_PROMPT = """Você é a Interface do Cartographer. Sua única função é traduzir resultados do Core para linguagem natural clara e objetiva.

Entrada:
- core_result: objeto com os campos retornados pelo Core
  - summary: resumo textual da análise
  - metrics_summary: lista de métricas
  - correlations: lista de correlações (se houver)
  - unit_name: nome da unidade analisada
  - column_name: nome da coluna (se for analyze_vertical)
  - cache_key: chave para recuperar o resultado

Regras:
1. Traduza APENAS o que está no core_result.
2. NUNCA adicione interpretações, sugestões ou conclusões que não estejam no core_result.
3. NUNCA sugira próximos passos.
4. NUNCA invente dados.
5. Se for analyze_vertical, destaque as estatísticas da coluna (nulos, cardinalidade, valores únicos, etc.).
6. Se for analyze_unit, destaque o resumo geral e as correlações.
7. Use markdown para organizar a resposta."""

LIST_SYSTEM_PROMPT = """Você é a Interface do Cartographer. Sua única função é traduzir listas estruturadas para linguagem natural clara e objetiva.

Entrada:
- formatted_payload: conteúdo já decidido pelo Freio/Acelerador (colunas, unidades ou resumos)
- delivery_plan: plano de entrega com action, format e message

Regras:
1. Traduza APENAS o que está em formatted_payload.
2. NUNCA decida o formato da resposta — isso já foi definido em delivery_plan.
3. NUNCA invente colunas, unidades ou métricas.
4. Inclua a sugestão de próximo passo exatamente como está em formatted_payload.next_step.
5. Use markdown para organizar a resposta."""

_TOP_COLUMNS_LIMIT = 10


def _deepseek_translate(api_key: str, prompt: str, system_message: str) -> str:
    response = httpx.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=300.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _fetch_structure(session_id: str, core_api_url: str) -> dict[str, Any]:
    response = httpx.get(
        f"{core_api_url.rstrip('/')}/sessions/{session_id}/structure",
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("core_api retornou estrutura inválida")
    return payload


def _structure_units(structure: dict[str, Any]) -> list[dict[str, Any]]:
    units = structure.get("units")
    if not isinstance(units, list):
        return []
    return [unit for unit in units if isinstance(unit, dict)]


def _resolve_unit(
    structure: dict[str, Any],
    unit_name: str = "",
    core_result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    units = _structure_units(structure)
    if not units:
        return None

    candidates = [
        unit_name.strip(),
        str((core_result or {}).get("unit_name") or "").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        for unit in units:
            if str(unit.get("unit_name", "")).strip() == candidate:
                return unit

    if len(units) == 1:
        return units[0]
    return None


def _format_ratio(value: object) -> str:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return "?"
    return f"{ratio * 100:.0f}%"


def _column_profile(column: dict[str, Any]) -> str:
    unique_ratio = float(column.get("unique_ratio") or 0.0)
    null_ratio = float(column.get("null_ratio") or 0.0)
    raw_type = str(column.get("raw_type") or "").upper()

    if raw_type in {"INTEGER", "REAL", "NUMERIC", "FLOAT", "DOUBLE"}:
        return "numérica"
    if raw_type in {"TEXT", "VARCHAR", "CHAR", "STRING"}:
        return "textual"
    if unique_ratio >= 0.9 and null_ratio <= 0.05:
        return "identificador"
    return "misto"


def _unit_predominant_type(columns: list[dict[str, Any]]) -> str:
    if not columns:
        return "desconhecido"

    profiles = [_column_profile(column) for column in columns]
    counts: dict[str, int] = {}
    for profile in profiles:
        counts[profile] = counts.get(profile, 0) + 1

    dominant = max(counts, key=counts.get)
    if counts[dominant] >= len(columns) * 0.6:
        mapping = {
            "numérica": "predominantemente numérica",
            "textual": "predominantemente textual",
            "identificador": "predominantemente identificadores",
        }
        return mapping.get(dominant, "perfil misto")
    return "perfil misto"


def _column_summary_entry(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": column.get("name"),
        "cardinality": column.get("cardinality"),
        "null_ratio": column.get("null_ratio"),
        "unique_ratio": column.get("unique_ratio"),
        "raw_type": column.get("raw_type"),
        "profile": _column_profile(column),
    }


def _build_list_with_summary_payload(
    structure: dict[str, Any],
    *,
    unit_name: str = "",
    core_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unit = _resolve_unit(structure, unit_name, core_result)
    if unit is None:
        raise ValueError("Unidade não encontrada na estrutura da sessão")

    unit_label = str(unit.get("unit_name") or "")
    columns = unit.get("columns") if isinstance(unit.get("columns"), list) else []
    column_entries = [_column_summary_entry(column) for column in columns if isinstance(column, dict)]

    return {
        "unit_name": unit_label,
        "row_count": unit.get("row_count"),
        "column_count": unit.get("column_count", len(column_entries)),
        "columns": column_entries,
        "next_step": (
            f"Para aprofundar, peça a análise de uma coluna específica de `{unit_label}` "
            f"ou a análise completa dessa unidade."
        ),
    }


def _build_list_truncated_payload(
    structure: dict[str, Any],
    *,
    unit_name: str = "",
    core_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unit = _resolve_unit(structure, unit_name, core_result)
    if unit is None:
        raise ValueError("Unidade não encontrada na estrutura da sessão")

    unit_label = str(unit.get("unit_name") or "")
    columns = unit.get("columns") if isinstance(unit.get("columns"), list) else []
    column_entries = [_column_summary_entry(column) for column in columns if isinstance(column, dict)]
    total_columns = len(column_entries)
    top_columns = column_entries[:_TOP_COLUMNS_LIMIT]
    remaining = max(0, total_columns - len(top_columns))

    return {
        "unit_name": unit_label,
        "row_count": unit.get("row_count"),
        "column_count": total_columns,
        "top_columns": top_columns,
        "additional_column_count": remaining,
        "next_step": (
            f"Existem {remaining} colunas adicionais em `{unit_label}`. "
            f"Peça a análise de uma coluna específica ou solicite a lista completa."
        ),
    }


def _build_list_units_payload(structure: dict[str, Any]) -> dict[str, Any]:
    units = []
    for unit in _structure_units(structure):
        columns = unit.get("columns") if isinstance(unit.get("columns"), list) else []
        column_entries = [column for column in columns if isinstance(column, dict)]
        units.append(
            {
                "unit_name": unit.get("unit_name"),
                "row_count": unit.get("row_count"),
                "column_count": unit.get("column_count", len(column_entries)),
                "predominant_type": _unit_predominant_type(column_entries),
            }
        )

    return {
        "units": units,
        "unit_count": len(units),
        "next_step": (
            "Para aprofundar, escolha uma unidade e peça sua análise "
            "(ex.: analise a unidade `customers`)."
        ),
    }


def _build_list_units_compact_payload(structure: dict[str, Any]) -> dict[str, Any]:
    units = []
    for unit in _structure_units(structure):
        columns = unit.get("columns") if isinstance(unit.get("columns"), list) else []
        units.append(
            {
                "unit_name": unit.get("unit_name"),
                "column_count": unit.get("column_count", len(columns)),
            }
        )

    return {
        "units": units,
        "unit_count": len(units),
        "next_step": (
            "Para aprofundar, escolha uma unidade e peça sua análise "
            "(ex.: analise a unidade `customers`)."
        ),
    }


def _build_list_payload(
    delivery_action: str,
    structure: dict[str, Any],
    *,
    unit_name: str = "",
    core_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    builders = {
        "list_with_summary": _build_list_with_summary_payload,
        "list_truncated": _build_list_truncated_payload,
        "list_units": lambda s, **kwargs: _build_list_units_payload(s),
        "list_units_compact": lambda s, **kwargs: _build_list_units_compact_payload(s),
    }
    builder = builders.get(delivery_action)
    if builder is None:
        raise ValueError(f"Ação de entrega não suportada: {delivery_action}")
    if delivery_action in {"list_with_summary", "list_truncated"}:
        return builder(structure, unit_name=unit_name, core_result=core_result)
    return builder(structure)


def _format_list_without_llm(payload: dict[str, Any], delivery_action: str) -> str:
    lines: list[str] = []

    if delivery_action == "list_with_summary":
        lines.append(
            f"## Unidade `{payload.get('unit_name')}` "
            f"({payload.get('row_count')} linhas, {payload.get('column_count')} colunas)"
        )
        lines.append("")
        lines.append("### Colunas")
        for column in payload.get("columns") or []:
            lines.append(
                f"- **{column.get('name')}**: {column.get('cardinality')} valores distintos, "
                f"{_format_ratio(column.get('null_ratio'))} nulos, perfil {column.get('profile')}"
            )
    elif delivery_action == "list_truncated":
        lines.append(
            f"## Unidade `{payload.get('unit_name')}` "
            f"({payload.get('column_count')} colunas)"
        )
        lines.append("")
        lines.append("### Principais colunas")
        for column in payload.get("top_columns") or []:
            lines.append(
                f"- **{column.get('name')}**: {column.get('cardinality')} valores distintos, "
                f"{_format_ratio(column.get('null_ratio'))} nulos"
            )
        remaining = payload.get("additional_column_count", 0)
        if remaining:
            lines.append(f"\n*{remaining} colunas adicionais não exibidas.*")
    elif delivery_action == "list_units":
        lines.append(f"## Unidades ({payload.get('unit_count')})")
        lines.append("")
        for unit in payload.get("units") or []:
            lines.append(
                f"- **{unit.get('unit_name')}**: {unit.get('column_count')} colunas, "
                f"{unit.get('row_count')} linhas, {unit.get('predominant_type')}"
            )
    elif delivery_action == "list_units_compact":
        lines.append(f"## Unidades ({payload.get('unit_count')})")
        lines.append("")
        for unit in payload.get("units") or []:
            lines.append(f"- **{unit.get('unit_name')}**: {unit.get('column_count')} colunas")

    next_step = str(payload.get("next_step") or "").strip()
    if next_step:
        lines.extend(["", f"**Próximo passo:** {next_step}"])
    return "\n".join(lines)


def _translate_full_result(core_result: dict, api_key: str, action: str) -> str:
    prompt = f"""Traduza o resultado abaixo para linguagem natural clara e objetiva.

Tipo de análise: {action}

core_result:
{json.dumps(core_result, ensure_ascii=False, indent=2, default=str)}

Regras:
- Traduza APENAS o que está no core_result.
- NUNCA adicione interpretações, sugestões ou conclusões que não estejam no core_result.
- NUNCA sugira próximos passos.
- NUNCA invente dados.
- Se for analyze_vertical, destaque as estatísticas da coluna (nulos, cardinalidade, valores únicos, etc.).
- Se for analyze_unit, destaque o resumo geral e as correlações.
- Use markdown para organizar a resposta."""

    return _deepseek_translate(api_key, prompt, UNIVERSAL_SYSTEM_PROMPT)


def _translate_list_payload(
    payload: dict[str, Any],
    api_key: str,
    delivery_plan: dict[str, Any],
) -> str:
    prompt = f"""Traduza a lista abaixo para linguagem natural clara e objetiva.

delivery_plan:
{json.dumps(delivery_plan, ensure_ascii=False, indent=2, default=str)}

formatted_payload:
{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}

Regras:
- Traduza APENAS o que está em formatted_payload.
- NUNCA decida o formato — siga delivery_plan.format.
- NUNCA invente colunas, unidades ou métricas.
- Inclua formatted_payload.next_step como sugestão de próximo passo.
- Use markdown para organizar a resposta."""

    return _deepseek_translate(api_key, prompt, LIST_SYSTEM_PROMPT)


def _resolve_delivery_action(action: str, delivery_plan: dict[str, Any]) -> str:
    delivery_action = str(delivery_plan.get("action") or "deliver_full").strip()
    if action == "analyze_vertical":
        return "deliver_full"
    return delivery_action or "deliver_full"


def main(
    core_result: dict,
    session_id: str,
    action: str = "analyze_unit",
    suggested_action: dict | None = None,
    delivery_plan: dict | None = None,
    unit_name: str = "",
):
    if action in ("clarify", "pending"):
        message = str(core_result.get("response", "")).strip() or "Não há ação pendente."
        result = {"response": message, "session_id": session_id, "action": action}
        suggested = core_result.get("suggested_action")
        if not isinstance(suggested, dict) and isinstance(suggested_action, dict):
            suggested = suggested_action
        if isinstance(suggested, dict) and suggested.get("action"):
            result["suggested_action"] = suggested
        return result

    plan = delivery_plan if isinstance(delivery_plan, dict) else {}
    delivery_action = _resolve_delivery_action(action, plan)

    if delivery_action == "deliver_full":
        trimmed = trim_core_result(core_result, action, plan)
        if plan.get("use_llm") is False:
            return {
                "response": _format_without_llm(trimmed, action),
                "session_id": session_id,
                "last_result": trimmed,
                "delivery_plan": plan,
            }

        api_key = wmill.get_variable("f/cartographer/DEEPSEEK_API_KEY").strip()
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY não configurada")

        translated = _translate_full_result(trimmed, api_key, action)
        return {
            "response": translated,
            "session_id": session_id,
            "last_result": trimmed,
            "delivery_plan": plan,
        }

    core_api_url = wmill.get_variable("f/cartographer/CORE_API_URL").rstrip("/")
    structure = _fetch_structure(session_id, core_api_url)
    list_payload = _build_list_payload(
        delivery_action,
        structure,
        unit_name=unit_name,
        core_result=core_result,
    )

    if plan.get("use_llm") is False:
        return {
            "response": _format_list_without_llm(list_payload, delivery_action),
            "session_id": session_id,
            "last_result": list_payload,
            "delivery_plan": plan,
        }

    api_key = wmill.get_variable("f/cartographer/DEEPSEEK_API_KEY").strip()
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY não configurada")

    translated = _translate_list_payload(list_payload, api_key, plan)
    return {
        "response": translated,
        "session_id": session_id,
        "last_result": list_payload,
        "delivery_plan": plan,
    }
