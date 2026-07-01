import json

import httpx
import wmill

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


def _format_result(core_result: dict, api_key: str, action: str) -> str:
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


def main(core_result: dict, session_id: str, action: str = "analyze_unit", suggested_action: dict | None = None):
    if action in ("clarify", "pending"):
        message = str(core_result.get("response", "")).strip() or "Não há ação pendente."
        result = {"response": message, "session_id": session_id, "action": action}
        suggested = core_result.get("suggested_action")
        if not isinstance(suggested, dict) and isinstance(suggested_action, dict):
            suggested = suggested_action
        if isinstance(suggested, dict) and suggested.get("action"):
            result["suggested_action"] = suggested
        return result

    api_key = wmill.get_variable("f/cartographer/DEEPSEEK_API_KEY").strip()
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY não configurada")

    translated = _format_result(core_result, api_key, action)
    return {"response": translated, "session_id": session_id, "last_result": core_result}
