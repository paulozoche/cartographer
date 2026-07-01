from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

load_dotenv(ROOT / ".env")

CORE_API_URL = os.getenv("CORE_API_URL", "http://localhost:8000").rstrip("/")
WINDMILL_WEBHOOK_URL = os.getenv(
    "WINDMILL_WEBHOOK_URL",
    "http://localhost:8002/api/w/admins/jobs/run_wait_result/f/f/cartographer/cartographer_chat?token=BT6FcYapV7hnxcLkl2odDWCEwxrzpGJ5",
)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
PROXY_TIMEOUT_SECONDS = 300.0

CONFIRMATION_WORDS = frozenset(
    {"sim", "si", "ok", "confirme", "pode", "prossiga", "continue", "vai", "execute"}
)
ANALYSIS_PREFIXES = ("analise", "analisa", "analisar", "explore", "explorar")


sessions: dict[str, dict[str, Any]] = {}


def _empty_session() -> dict[str, Any]:
    return {
        "history": [],
        "last_action": None,
        "last_result": None,
        "pending_action": None,
    }


def _get_session(session_id: str) -> dict[str, Any]:
    session = sessions.get(session_id)
    if session is None:
        session = _empty_session()
        sessions[session_id] = session
    return session

ASSIST_SYSTEM_PROMPT = """Você é um assistente de navegação do Cartographer.
- Ajude o usuário a decidir o próximo passo.
- Use APENAS o contexto fornecido (units, last_result, message).
- NUNCA invente dados, colunas ou unidades que não existem.
- NUNCA sugira ações que o sistema não suporta (apenas analyze_unit, analyze_vertical, analyze_horizontal, recall).
- Retorne uma sugestão em linguagem natural e uma lista de opções.
- Se a mensagem já for uma ação direta (ex: "analise X"), apenas confirme e sugira a ação.

Responda SOMENTE com um JSON válido no formato:
{"suggestion": "...", "options": ["...", "..."]}
"""

app = FastAPI(title="Cartographer Web Proxy")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    units: list[str]


class AssistContext(BaseModel):
    units: list[str] = Field(default_factory=list)
    last_result: dict[str, Any] | None = None


class AssistRequest(BaseModel):
    session_id: str
    message: str
    context: AssistContext = Field(default_factory=AssistContext)


class AssistResponse(BaseModel):
    suggestion: str
    options: list[str]
    session_id: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


def _extract_upstream_detail(response: httpx.Response, service_name: str) -> str:
    try:
        body = response.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
            if isinstance(detail, list):
                return "; ".join(str(item) for item in detail)
            return str(detail)
    except Exception:
        pass
    text = response.text.strip()
    if text:
        return text
    return f"{service_name} retornou HTTP {response.status_code}"


def _is_short_confirmation(message: str) -> bool:
    return message.lower().strip() in CONFIRMATION_WORDS


def _normalize_action(action: dict[str, Any] | None, units: list[str]) -> dict[str, Any] | None:
    if not isinstance(action, dict):
        return None

    action_name = str(action.get("action", "")).strip()
    units_map = {unit.casefold(): unit for unit in units}

    if action_name == "analyze_unit":
        unit_name = str(action.get("unit_name", "")).strip()
        canonical = units_map.get(unit_name.casefold())
        if not canonical:
            return None
        return {"action": "analyze_unit", "unit_name": canonical}

    if action_name == "analyze_vertical":
        unit_name = str(action.get("unit_name", "")).strip()
        column = str(action.get("column", "")).strip()
        canonical = units_map.get(unit_name.casefold())
        if not canonical or not column:
            return None
        depth = str(action.get("depth", "layer2")).strip() or "layer2"
        return {
            "action": "analyze_vertical",
            "unit_name": canonical,
            "column": column,
            "depth": depth,
        }

    return None


def _pending_action_from_assist(options: list[str]) -> dict[str, Any] | None:
    if len(options) == 1:
        return {"action": "analyze_unit", "unit_name": options[0]}
    return None


def _infer_action_from_message(message: str, units: list[str]) -> dict[str, Any] | None:
    normalized = message.lower().strip()
    for prefix in ANALYSIS_PREFIXES:
        if not normalized.startswith(f"{prefix} "):
            continue
        remainder = message[len(prefix) :].strip()
        if not remainder:
            return None
        units_by_length = sorted(units, key=len, reverse=True)
        remainder_lower = remainder.lower()
        for unit in units_by_length:
            unit_lower = unit.lower()
            if unit_lower == remainder_lower or unit_lower in remainder_lower:
                return {"action": "analyze_unit", "unit_name": unit}
        token = re.sub(r"^(?:a\s+)?tabela\s+(?:da|de|do|das|dos)\s+", "", remainder_lower).strip()
        for unit in units_by_length:
            unit_lower = unit.lower()
            if token and (token in unit_lower or unit_lower in token):
                return {"action": "analyze_unit", "unit_name": unit}
    return None


def _remember_executed_action(session: dict[str, Any], action: dict[str, Any] | None) -> None:
    if not isinstance(action, dict) or not action.get("action"):
        return
    session["last_action"] = dict(action)
    session["pending_action"] = None


def _append_history(session: dict[str, Any], role: str, content: str) -> None:
    text = content.strip()
    if not text:
        return
    session["history"].append({"role": role, "content": text})


def _apply_windmill_session_updates(
    session: dict[str, Any],
    body: dict[str, Any],
    *,
    executed_action: dict[str, Any] | None = None,
) -> None:
    suggested_action = body.get("suggested_action")
    if isinstance(suggested_action, dict) and suggested_action.get("action"):
        session["pending_action"] = dict(suggested_action)
        return

    if body.get("action") == "pending" and isinstance(body.get("suggested_action"), dict):
        session["pending_action"] = dict(body["suggested_action"])
        return

    last_result = body.get("last_result")
    if isinstance(last_result, dict):
        session["last_result"] = last_result

    if executed_action is not None:
        _remember_executed_action(session, executed_action)


def _parse_windmill_chat_response(response: httpx.Response, fallback_session_id: str) -> tuple[ChatResponse, dict[str, Any]]:
    try:
        body = response.json()
    except Exception:
        text = response.text.strip()
        if not text:
            raise HTTPException(
                status_code=502,
                detail="Windmill retornou resposta vazia",
            )
        return ChatResponse(response=text, session_id=fallback_session_id), {}, {}

    if not isinstance(body, dict):
        return ChatResponse(response=str(body), session_id=fallback_session_id), {}

    response_text = body.get("response")
    if response_text is None:
        raise HTTPException(
            status_code=502,
            detail="Windmill retornou JSON sem campo 'response'",
        )

    return (
        ChatResponse(
            response=str(response_text),
            session_id=str(body.get("session_id", fallback_session_id)),
        ),
        body,
    )


@app.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    files = {
        "file": (
            file.filename or "upload",
            file_bytes,
            file.content_type or "application/octet-stream",
        )
    }

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            upstream = await client.post(f"{CORE_API_URL}/sessions", files=files)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Timeout ao criar sessão no core_api",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"core_api indisponível: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=_extract_upstream_detail(upstream, "core_api"),
        )

    try:
        payload = upstream.json()
        session_id = str(payload["session_id"])
        units = payload.get("units", [])
        if not isinstance(units, list):
            raise ValueError("units inválido")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="core_api retornou payload inválido ao criar sessão",
        ) from exc

    return UploadResponse(
        session_id=session_id,
        filename=file.filename or "upload",
        units=[str(unit) for unit in units],
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id obrigatório.")

    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    session = _get_session(session_id)
    _append_history(session, "user", message)

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            units = await _fetch_session_units(client, session_id)
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Timeout ao validar sessão no core_api",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"core_api indisponível: {exc}",
        ) from exc

    executed_action: dict[str, Any] | None = None

    if _is_short_confirmation(message):
        normalized = _normalize_action(session.get("pending_action"), units)
        if normalized is None:
            response_text = "Não há ação pendente."
            _append_history(session, "assistant", response_text)
            return ChatResponse(response=response_text, session_id=session_id)
        executed_action = normalized
    else:
        inferred = _infer_action_from_message(message, units)
        if inferred is not None:
            executed_action = inferred

    payload: dict[str, Any] = {
        "session_id": session_id,
        "message": message,
        "history": list(session["history"]),
        "pending_action": session.get("pending_action"),
        "last_action": session.get("last_action"),
        "last_result": session.get("last_result"),
    }

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            upstream = await client.post(WINDMILL_WEBHOOK_URL, json=payload)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Timeout no webhook Windmill",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Windmill indisponível: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=_extract_upstream_detail(upstream, "Windmill"),
        )

    chat_response, windmill_body = _parse_windmill_chat_response(upstream, session_id)
    _apply_windmill_session_updates(session, windmill_body, executed_action=executed_action)
    _append_history(session, "assistant", chat_response.response)

    return chat_response


async def _fetch_session_units(client: httpx.AsyncClient, session_id: str) -> list[str]:
    upstream = await client.get(f"{CORE_API_URL}/sessions/{session_id}/units")
    if upstream.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Sessão não encontrada: {session_id}")
    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=_extract_upstream_detail(upstream, "core_api"),
        )
    try:
        payload = upstream.json()
        units = payload.get("units", [])
        if not isinstance(units, list):
            raise ValueError("units inválido")
        return [str(unit) for unit in units if str(unit).strip()]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="core_api retornou lista de unidades inválida",
        ) from exc


def _build_assist_user_prompt(
    message: str,
    units: list[str],
    last_result: dict[str, Any] | None,
) -> str:
    parts = [
        f"Mensagem do usuário: {message}",
        f"Unidades disponíveis: {json.dumps(units, ensure_ascii=False)}",
    ]
    if last_result is not None:
        parts.append(
            f"Último resultado: {json.dumps(last_result, ensure_ascii=False)}"
        )
    return "\n".join(parts)


def _filter_assist_options(options: list[Any], units: list[str]) -> list[str]:
    allowed = {unit.casefold(): unit for unit in units}
    filtered: list[str] = []
    for option in options:
        normalized = str(option).strip()
        if not normalized:
            continue
        canonical = allowed.get(normalized.casefold())
        if canonical and canonical not in filtered:
            filtered.append(canonical)
    return filtered


def _parse_assist_llm_content(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek retornou JSON inválido para /assist",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail="DeepSeek retornou payload inválido para /assist",
        )
    return payload


def _fallback_assist_response(session_id: str, units: list[str]) -> AssistResponse:
    count = len(units)
    if count == 1:
        suggestion = f"Há 1 unidade disponível: {units[0]}. Deseja analisá-la?"
    else:
        suggestion = f"Encontrei {count} unidades. Qual você quer analisar primeiro?"
    return AssistResponse(
        suggestion=suggestion,
        options=list(units),
        session_id=session_id,
    )


async def _call_deepseek_assist(user_prompt: str) -> dict[str, Any]:
    if not DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY não configurada para /assist",
        )

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": ASSIST_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            upstream = await client.post(
                f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Timeout ao chamar DeepSeek para /assist",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek indisponível: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=_extract_upstream_detail(upstream, "DeepSeek"),
        )

    try:
        body = upstream.json()
        content = str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek retornou resposta sem conteúdo para /assist",
        ) from exc

    return _parse_assist_llm_content(content)


@app.post("/assist", response_model=AssistResponse)
async def assist(request: AssistRequest) -> AssistResponse:
    session_id = request.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id obrigatório.")

    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            units = await _fetch_session_units(client, session_id)
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Timeout ao validar sessão no core_api",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"core_api indisponível: {exc}",
        ) from exc

    if not units:
        raise HTTPException(status_code=400, detail="Sessão sem unidades disponíveis.")

    user_prompt = _build_assist_user_prompt(
        message,
        units,
        request.context.last_result,
    )

    try:
        llm_payload = await _call_deepseek_assist(user_prompt)
    except HTTPException as exc:
        if exc.status_code in {503, 502, 504}:
            return _fallback_assist_response(session_id, units)
        raise

    suggestion = str(llm_payload.get("suggestion", "")).strip()
    raw_options = llm_payload.get("options", [])
    if not isinstance(raw_options, list):
        raw_options = []

    options = _filter_assist_options(raw_options, units)
    if not options:
        options = list(units)

    if not suggestion:
        fallback = _fallback_assist_response(session_id, options)
        suggestion = fallback.suggestion

    pending = _pending_action_from_assist(options)
    if pending is not None:
        assist_session = _get_session(session_id)
        assist_session["pending_action"] = dict(pending)

    return AssistResponse(
        suggestion=suggestion,
        options=options,
        session_id=session_id,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web:app", host="127.0.0.1", port=8080, reload=False)
