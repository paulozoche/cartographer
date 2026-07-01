import json
import re

import httpx
import wmill

COLUMN_INTENT_KEYWORDS = ("detalhe", "detalhes", "mostre", "mostra")
ANALYSIS_KEYWORDS = ("analise", "analisa", "analisar", "explore", "explorar", "mostre", "mostra")
STRIP_KEYWORDS = {
    "analise",
    "analisa",
    "analisar",
    "explore",
    "explorar",
    "mostre",
    "mostra",
    "detalhe",
    "detalhes",
    "tabela",
    "tabelas",
    "coluna",
    "colunas",
    "cruze",
    "cruce",
    "cruzar",
    "recall",
    "unidade",
    "unidades",
    "a",
    "o",
    "as",
    "os",
    "da",
    "de",
    "do",
    "das",
    "dos",
    "na",
    "no",
    "nas",
    "nos",
    "em",
    "um",
    "uma",
}

CONFIRMATION_WORDS = frozenset(
    {
        "sim",
        "si",
        "ok",
        "okay",
        "confirme",
        "confirma",
        "pode",
        "prossiga",
        "continue",
        "vai",
        "execute",
        "beleza",
        "claro",
    }
)

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
4. action pode ser: analyze_unit, analyze_vertical ou clarify.
5. Para analyze_vertical, inclua column com o termo da coluna mencionada pelo usuário.
6. Para analyze_unit, o usuário quer analisar/explorar a tabela como um todo.
7. Referências como "a tabela da X" ou "dados de X" indicam intenção de analyze_unit quando X mapeia a uma unidade.

## CONTEXTO DE SESSÃO
- Use history (mensagens anteriores) e last_action para interpretar mensagens curtas ou ambíguas.
- Se o usuário confirmar algo sugerido antes, pending_action terá prioridade (tratado fora deste script).
- Se a intenção for vaga mas houver uma ação plausível, use action="pending".

## SAÍDA (JSON apenas, sem texto fora do JSON)
{
  "reasoning": "breve explicação do raciocínio semântico",
  "action": "analyze_unit|analyze_vertical|clarify|pending",
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


def _match_unit_name(candidate: str, units: list[str]) -> str | None:
    candidate_norm = _normalize(candidate)
    for unit in units:
        if _normalize(unit) == candidate_norm:
            return unit
    return None


def _extract_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9_]+", text) if token]


def _extract_search_term(message: str) -> str:
    normalized = _normalize(message)
    normalized = re.sub(
        r"^(?:analise|analisa|analisar|explore|explorar|mostre|mostra|detalhe|detalhes|cruze|cruce|cruzar|recall)\s+",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s+(?:em|na\s+tabela|da\s+tabela|de)\s+[a-z0-9_]+$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    tokens = [
        token
        for token in _extract_tokens(normalized)
        if _normalize(token) not in STRIP_KEYWORDS
    ]
    return " ".join(tokens).strip()


def _partial_unit_matches(search_term: str, units: list[str]) -> list[str]:
    term = _normalize(search_term)
    if not term:
        return []

    term_compact = term.replace(" ", "_")
    matches: list[str] = []
    for unit in units:
        unit_norm = _normalize(unit)
        if term in unit_norm or term_compact in unit_norm:
            matches.append(unit)
    return matches


def _mentioned_unit(message: str, units: list[str]) -> str | None:
    normalized = _normalize(message)
    for unit in sorted(units, key=len, reverse=True):
        unit_norm = _normalize(unit)
        if unit_norm and unit_norm in normalized:
            return unit
    return None


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
) -> dict:
    prompt = json.dumps(
        {
            "user_message": message,
            "available_units": units,
            "history": history or [],
            "last_action": last_action,
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


def _resolve_unit_name(
    message: str,
    units: list[str],
    api_key: str | None = None,
    *,
    history: list | None = None,
    last_action: dict | None = None,
) -> str:
    search_term = _extract_search_term(message)

    if search_term:
        exact = _match_unit_name(search_term, units)
        if exact is not None:
            return exact

        partial = _partial_unit_matches(search_term, units)
        if partial:
            return partial[0]

        for token in _extract_tokens(search_term):
            if _normalize(token) in STRIP_KEYWORDS or len(token) < 2:
                continue
            token_matches = _partial_unit_matches(token, units)
            if token_matches:
                return token_matches[0]

    mentioned = _mentioned_unit(message, units)
    if mentioned is not None:
        return mentioned

    if len(units) == 1:
        return units[0]

    if api_key:
        llm_result = _llm_interpret_intent(
            message,
            units,
            api_key,
            history=history,
            last_action=last_action,
        )
        if llm_result.get("action") == "pending":
            suggested = llm_result.get("suggested_action") or {}
            unit = suggested.get("unit_name")
            if unit:
                return str(unit)
            raise ValueError(str(llm_result.get("suggestion") or llm_result.get("response")))
        return llm_result["unit_name"]

    available = ", ".join(units)
    if search_term:
        raise ValueError(
            f"Nenhuma unidade encontrada para '{search_term}'. "
            f"Unidades disponíveis: {available}"
        )
    raise ValueError(
        "Não foi possível identificar a unidade. "
        f"Unidades disponíveis: {available}"
    )


def _looks_like_unit_reference(phrase: str) -> bool:
    normalized = _normalize(phrase)
    unit_reference_patterns = (
        r"^(?:a\s+)?tabelas?\s+(?:da|de|do|das|dos)\s+",
        r"^(?:a\s+)?dados?\s+(?:da|de|do|das|dos)\s+",
    )
    return any(re.match(pattern, normalized) for pattern in unit_reference_patterns)


def _strip_unit_suffix(phrase: str, units: list[str]) -> str:
    match = re.search(r"\s+(?:em|na\s+tabela|da\s+tabela|de)\s+(.+)$", phrase, flags=re.IGNORECASE)
    if not match:
        return phrase.strip()
    suffix = match.group(1).strip()
    if _match_unit_name(suffix, units) or _mentioned_unit(suffix, units):
        return phrase[: match.start()].strip()
    if _partial_unit_matches(suffix, units):
        return phrase[: match.start()].strip()
    return phrase.strip()


def _extract_column_phrase(message: str, units: list[str]) -> str | None:
    normalized = _normalize(message)
    patterns = [
        r"(?:detalhe|detalhes)(?:\s+da\s+coluna|\s+de\s+coluna|\s+coluna)?\s+(.+)$",
        r"(?:mostre|mostra)(?:\s+a\s+coluna|\s+coluna)?\s+(.+)$",
        r"(?:analise|analisa|analisar|explore|explorar)(?:\s+a\s+coluna|\s+coluna)\s+(.+)$",
        r"(?:analise|analisa|analisar|explore|explorar)\s+(?:a\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        phrase = _strip_unit_suffix(match.group(1).strip(), units)
        if phrase:
            return phrase
    return None


def _get_api_key() -> str | None:
    try:
        api_key = wmill.get_variable("f/cartographer/DEEPSEEK_API_KEY").strip()
    except Exception:
        return None
    return api_key or None


def _strip_trailing_punctuation(text: str) -> str:
    return re.sub(r"[.!?]+$", "", text).strip()


def _is_short_confirmation(message: str) -> bool:
    normalized = _strip_trailing_punctuation(_normalize(message))
    return normalized in CONFIRMATION_WORDS


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
    message: str,
    session_id: str,
    units: list[str],
    pending_action: dict | None,
) -> dict | None:
    if not _is_short_confirmation(message):
        return None

    normalized = _normalize_pending_action(pending_action, units)
    if normalized is not None:
        result = dict(normalized)
        result["session_id"] = session_id
        return result

    return {
        "action": "clarify",
        "response": "Não há ação pendente.",
        "session_id": session_id,
    }


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

    normalized = _normalize(message)
    core_api_url = wmill.get_variable("f/cartographer/CORE_API_URL").rstrip("/")
    units = _fetch_units(session_id, core_api_url)
    if not units:
        raise ValueError("Sessão sem unidades disponíveis.")

    conversation_history = history if isinstance(history, list) else []

    confirmation = _resolve_confirmation(message, session_id, units, pending_action)
    if confirmation is not None:
        return confirmation

    api_key = _get_api_key()
    unit_names_lower = {_normalize(unit) for unit in units}
    column_phrase = _extract_column_phrase(message, units)
    has_column_intent = any(keyword in normalized for keyword in COLUMN_INTENT_KEYWORDS) or "coluna" in normalized

    if column_phrase and _looks_like_unit_reference(column_phrase):
        column_phrase = None

    if column_phrase:
        matched_unit = _match_unit_name(column_phrase, units)
        if matched_unit is None:
            partial = _partial_unit_matches(column_phrase, units)
            if partial:
                matched_unit = partial[0]

        if matched_unit is not None:
            return {
                "action": "analyze_unit",
                "unit_name": matched_unit,
                "session_id": session_id,
            }

        if has_column_intent or _normalize(column_phrase) not in unit_names_lower:
            unit_name = _resolve_unit_name(
                message,
                units,
                api_key,
                history=conversation_history,
                last_action=last_action,
            )
            return {
                "action": "analyze_vertical",
                "unit_name": unit_name,
                "column": column_phrase,
                "depth": "layer2",
                "session_id": session_id,
            }

    if any(keyword in normalized for keyword in ANALYSIS_KEYWORDS):
        unit_name = _resolve_unit_name(
            message,
            units,
            api_key,
            history=conversation_history,
            last_action=last_action,
        )
        return {
            "action": "analyze_unit",
            "unit_name": unit_name,
            "session_id": session_id,
        }

    numeric_result = _resolve_numeric_list_selection(message, units, conversation_history)
    if numeric_result is not None:
        numeric_result["session_id"] = session_id
        return numeric_result

    if api_key:
        llm_result = _llm_interpret_intent(
            message,
            units,
            api_key,
            history=conversation_history,
            last_action=last_action,
        )
        llm_result["session_id"] = session_id
        return llm_result

    raise ValueError(
        "Não foi possível identificar a ação. "
        "Use 'analise [unidade]' ou 'detalhe/mostre [coluna]'."
    )
