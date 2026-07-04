import json
import re

import httpx
import wmill

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", re.DOTALL | re.IGNORECASE)
_NUMBERED_LIST_ITEM_RE = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$", re.MULTILINE)

INTENT_RESOLVER_SYSTEM_PROMPT = """Você interpreta mensagens do usuário sobre unidades de dados (tabelas).

O usuário pode usar linguagem natural, sinônimos ou descrições indiretas.
Os nomes técnicos das unidades (ex: get_fit_now_member, person) raramente aparecem literalmente na mensagem.

## ASSOCIAÇÕES SEMÂNTICAS
- Use sinônimos e contexto para encontrar a melhor correspondência na lista available_units.
- Pense sobre a relação entre o significado da mensagem e cada unidade disponível antes de decidir.
- Exemplo: "academia" → get_fit_now_member (academia = fitness/academia de ginástica; get_fit_now_member é a tabela de membros)
- Exemplo: "facebook" → facebook_event_checkin (referência parcial ao nome técnico)
- Exemplo: "carteira de motorista" → drivers_license

## REGRAS
1. unit_name DEVE ser copiado literalmente de available_units quando houver correspondência.
2. Se houver ambiguidade entre duas ou mais unidades plausíveis, use action="clarify" e formule clarifying_question em português.
3. Se nenhuma unidade fizer sentido semântico, use action="clarify" listando as opções disponíveis.
4. action pode ser: analyze_unit, analyze_vertical, clarify, pending ou confirm.
5. Para analyze_vertical, inclua column com o termo da coluna mencionada pelo usuário.
6. Para analyze_unit, o usuário quer analisar/explorar/ver a tabela como um todo.
7. Referências como "a tabela da X", "quero ver a tabela", "me mostra os dados" indicam analyze_unit quando X mapeia a uma unidade.

## CONTEXTO DE SESSÃO
- Use history (mensagens anteriores) e last_action para interpretar mensagens curtas ou ambíguas.
- pending_action contém uma ação sugerida aguardando confirmação do usuário.

## CONFIRMAÇÃO
- Se pending_action existir e o usuário confirmar (em qualquer formulação: sim, ok, pode, vai, beleza, claro, etc.), use action="confirm".
- Se pending_action existir e o usuário recusar ou mudar de assunto, interprete a nova intenção ou use action="clarify".
- Se pending_action for null e o usuário parecer confirmar algo, use action="clarify" explicando que não há ação pendente.

## SAÍDA (JSON apenas, sem texto fora do JSON)
{
  "reasoning": "breve explicação do raciocínio semântico",
  "action": "analyze_unit|analyze_vertical|clarify|pending|confirm",
  "unit_name": "nome exato da unidade ou null",
  "column": "nome da coluna ou null",
  "clarifying_question": "pergunta ao usuário ou null",
  "suggestion": "sugestão em linguagem natural quando action=pending",
  "confidence": "high|medium|low"
}"""


def _normalize(text: str) -> str:
    return text.lower().strip()


def _fetch_units(session_id: str, core_api_url: str) -> list[str]:
    response = httpx.get(f"{core_api_url}/sessions/{session_id}/units", timeout=60.0)
    response.raise_for_status()
    payload = response.json()
    units = payload.get("units", [])
    if not isinstance(units, list):
        raise ValueError("core_api retornou lista de unidades inválida")
    return [str(unit) for unit in units if str(unit).strip()]


def _canonical_unit_name(unit_name: str, units: list[str]) -> str | None:
    unit_norm = _normalize(unit_name)
    for unit in units:
        if _normalize(unit) == unit_norm:
            return unit
    return None


def _parse_json_response(raw_content: str) -> dict:
    stripped = str(raw_content or "").strip()
    if not stripped:
        raise ValueError("LLM retornou resposta vazia")
    fence_match = _JSON_FENCE_RE.match(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("LLM retornou JSON inválido")
    return parsed


def _deepseek_chat(api_key: str, prompt: str, system_message: str) -> str:
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
            "response_format": {"type": "json_object"},
        },
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _llm_interpret_intent(
    message: str,
    units: list[str],
    api_key: str,
    *,
    history: list | None = None,
    last_action: dict | None = None,
    pending_action: dict | None = None,
) -> dict:
    prompt = json.dumps(
        {
            "user_message": message,
            "available_units": units,
            "history": history or [],
            "last_action": last_action,
            "pending_action": pending_action,
        },
        ensure_ascii=False,
        indent=2,
    )
    raw = _deepseek_chat(api_key, prompt, INTENT_RESOLVER_SYSTEM_PROMPT)
    parsed = _parse_json_response(raw)

    action = str(parsed.get("action", "")).strip()
    confidence = str(parsed.get("confidence", "")).strip().lower()
    unit_name = str(parsed.get("unit_name") or "").strip()
    canonical = _canonical_unit_name(unit_name, units) if unit_name else None

    if action == "confirm":
        return {"action": "confirm"}

    if action == "pending" or (action == "clarify" and confidence in {"", "medium", "low"}):
        suggestion = str(parsed.get("suggestion") or parsed.get("clarifying_question") or "").strip()
        if not suggestion:
            suggestion = "Deseja que eu prossiga com essa análise?"
        suggested_action = None
        if canonical is not None:
            column = str(parsed.get("column") or "").strip()
            if column:
                suggested_action = {
                    "action": "analyze_vertical",
                    "unit_name": canonical,
                    "column": column,
                    "depth": "layer2",
                }
            else:
                suggested_action = {"action": "analyze_unit", "unit_name": canonical}
        return {
            "action": "pending",
            "suggested_action": suggested_action,
            "suggestion": suggestion,
            "response": suggestion,
        }

    if action == "clarify":
        question = str(parsed.get("clarifying_question") or "").strip()
        if not question:
            question = (
                "Não consegui identificar a unidade. "
                f"Unidades disponíveis: {', '.join(units)}"
            )
        suggested_action = {"action": "analyze_unit", "unit_name": canonical} if canonical else None
        return {
            "action": "pending",
            "suggested_action": suggested_action,
            "suggestion": question,
            "response": question,
        }

    if canonical is None:
        question = str(parsed.get("clarifying_question") or "").strip()
        if question:
            return {
                "action": "pending",
                "suggested_action": None,
                "suggestion": question,
                "response": question,
            }
        raise ValueError(
            f"Não foi possível identificar a unidade para '{message}'. "
            f"Unidades disponíveis: {', '.join(units)}"
        )

    if action == "analyze_vertical":
        column = str(parsed.get("column") or "").strip()
        if not column:
            suggestion = (
                f"Deseja detalhar uma coluna de {canonical}? "
                "Informe qual coluna ou confirme a análise da tabela."
            )
            return {
                "action": "pending",
                "suggested_action": {"action": "analyze_unit", "unit_name": canonical},
                "suggestion": suggestion,
                "response": suggestion,
            }
        return {
            "action": "analyze_vertical",
            "unit_name": canonical,
            "column": column,
            "depth": "layer2",
        }

    return {
        "action": "analyze_unit",
        "unit_name": canonical,
    }


def _get_api_key() -> str | None:
    try:
        api_key = wmill.get_variable("f/cartographer/DEEPSEEK_API_KEY").strip()
    except Exception:
        return None
    return api_key or None


def _strip_trailing_punctuation(text: str) -> str:
    return re.sub(r"[.!?]+$", "", text).strip()


def _parse_numeric_selection(message: str) -> int | None:
    normalized = _strip_trailing_punctuation(_normalize(message))
    if re.fullmatch(r"\d+", normalized):
        return int(normalized)
    return None


def _parse_numbered_list(text: str) -> dict[int, str]:
    items: dict[int, str] = {}
    for match in _NUMBERED_LIST_ITEM_RE.finditer(text):
        items[int(match.group(1))] = match.group(2).strip()
    return items


def _last_assistant_message(history: list | None) -> str | None:
    if not isinstance(history, list):
        return None
    for entry in reversed(history):
        if isinstance(entry, dict) and entry.get("role") == "assistant":
            content = entry.get("content")
            if content is not None:
                return str(content)
    return None


def _resolve_numeric_list_selection(
    message: str,
    units: list[str],
    history: list | None,
) -> dict | None:
    index = _parse_numeric_selection(message)
    if index is None:
        return None

    assistant_message = _last_assistant_message(history)
    if not assistant_message:
        return None

    numbered_list = _parse_numbered_list(assistant_message)
    if index not in numbered_list:
        return None

    unit_name = _canonical_unit_name(numbered_list[index], units)
    if unit_name is None:
        return None

    return {"action": "analyze_unit", "unit_name": unit_name}


def _normalize_pending_action(pending_action: dict | None, units: list[str]) -> dict | None:
    if not isinstance(pending_action, dict):
        return None

    action = str(pending_action.get("action", "")).strip()
    if action == "analyze_unit":
        unit_name = _canonical_unit_name(str(pending_action.get("unit_name", "")), units)
        if unit_name is None:
            return None
        return {"action": "analyze_unit", "unit_name": unit_name}

    if action == "analyze_vertical":
        unit_name = _canonical_unit_name(str(pending_action.get("unit_name", "")), units)
        column = str(pending_action.get("column", "")).strip()
        if unit_name is None or not column:
            return None
        depth = str(pending_action.get("depth", "layer2")).strip() or "layer2"
        return {
            "action": "analyze_vertical",
            "unit_name": unit_name,
            "column": column,
            "depth": depth,
        }

    return None


def _resolve_confirmation(
    pending_action: dict | None,
    units: list[str],
) -> dict | None:
    normalized = _normalize_pending_action(pending_action, units)
    if normalized is None:
        return None
    return dict(normalized)


def main(
    user_message: str,
    session_id: str,
    pending_action: dict | None = None,
    last_action: dict | None = None,
    history: list | None = None,
):
    message = user_message.strip()
    if not message:
        raise ValueError("Mensagem vazia.")

    core_api_url = wmill.get_variable("f/cartographer/CORE_API_URL").rstrip("/")
    units = _fetch_units(session_id, core_api_url)
    if not units:
        raise ValueError("Sessão sem unidades disponíveis.")

    conversation_history = history if isinstance(history, list) else []

    numeric_result = _resolve_numeric_list_selection(message, units, conversation_history)
    if numeric_result is not None:
        numeric_result["session_id"] = session_id
        return numeric_result

    api_key = _get_api_key()
    if not api_key:
        raise ValueError(
            "Interpretação requer DEEPSEEK_API_KEY configurada. "
            f"Unidades disponíveis: {', '.join(units)}"
        )

    llm_result = _llm_interpret_intent(
        message,
        units,
        api_key,
        history=conversation_history,
        last_action=last_action,
        pending_action=pending_action,
    )

    if llm_result.get("action") == "confirm":
        confirmed = _resolve_confirmation(pending_action, units)
        if confirmed is None:
            return {
                "action": "clarify",
                "response": "Não há ação pendente.",
                "session_id": session_id,
            }
        confirmed["session_id"] = session_id
        return confirmed

    llm_result["session_id"] = session_id
    return llm_result
