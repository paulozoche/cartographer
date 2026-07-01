from __future__ import annotations

import json

from agnostic.curator.prompts import build_curator_prompt
from agnostic.interface.llm import DeepSeekClient
from agnostic.presentation.markdown.render_knowledge_graph import render_knowledge_graph_context

DEFAULT_CURATOR_MODEL = "deepseek-chat"
DEFAULT_CURATOR_TIMEOUT_SECONDS = 15.0

CURATOR_SYSTEM_PROMPT = (
    "Você é a IA Curadora do Cartographer.\n"
    "Você nunca conversa, nunca executa ações e nunca cria interpretações.\n"
    "Responda somente com JSON válido no formato esperado.\n"
    "Seu trabalho é filtrar o contexto estrutural existente para o subconjunto relevante à pergunta atual.\n"
)


def should_use_curator(state, *, is_first_call: bool) -> bool:
    return not is_first_call and len(state.units) > 3 and bool(state._full_structural_context)


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


def curated_context_for(
    llm,
    user_text: str,
    *,
    state,
    full_context: str,
    is_first_call: bool,
) -> str:
    if not should_use_curator(state, is_first_call=is_first_call):
        return full_context
    graph = getattr(state, "knowledge_graph", None)
    curator_context = full_context
    if graph is not None and len(graph.nodes) >= 2:
        curator_context = render_knowledge_graph_context(graph)
    cache_key = user_text.strip()
    curator_cache = getattr(state, "_curator_cache", {})
    cached = curator_cache.get(cache_key)
    if cached is not None:
        curated_context = cached.get("curated_context")
        if isinstance(curated_context, str) and curated_context.strip():
            return curated_context
        return full_context

    prompt = build_curator_prompt(
        user_message=user_text,
        available_units=[unit.unit_name for unit in state.units],
        full_context=curator_context,
    )
    try:
        response = llm.send(prompt, system_prompt=CURATOR_SYSTEM_PROMPT)
        payload = parse_curator_json(response.content)
    except Exception:
        return full_context

    curator_cache[cache_key] = payload
    curated_context = payload.get("curated_context")
    if isinstance(curated_context, str) and curated_context.strip():
        return curated_context
    return full_context


class Curadora:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_CURATOR_MODEL,
        *,
        timeout_seconds: float = DEFAULT_CURATOR_TIMEOUT_SECONDS,
    ) -> None:
        self._llm = DeepSeekClient(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )

    @property
    def llm(self) -> DeepSeekClient:
        return self._llm

    def should_use(self, state, is_first_call: bool) -> bool:
        return should_use_curator(state, is_first_call=is_first_call)

    def curate(self, user_text: str, full_context: str, state, is_first_call: bool) -> str:
        llm = getattr(state, "curator_ai", None) or self._llm
        return curated_context_for(
            llm,
            user_text,
            state=state,
            full_context=full_context,
            is_first_call=is_first_call,
        )
