from __future__ import annotations

import json
import logging
import os
import time
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
DEBUG_MODE = os.getenv("DEBUG_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

logger = logging.getLogger(__name__)


class _DiagNoOp:
    @staticmethod
    def info(*args: Any, **kwargs: Any) -> None:
        pass

    @staticmethod
    def warning(*args: Any, **kwargs: Any) -> None:
        pass

    @staticmethod
    def error(*args: Any, **kwargs: Any) -> None:
        pass

    @staticmethod
    def exception(*args: Any, **kwargs: Any) -> None:
        pass


diag: _DiagNoOp | Any = _DiagNoOp()

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

if DEBUG_MODE:
    from debug_panel import Diag, install_debug_logging, register_debug_routes

    diag = Diag()
    register_debug_routes(app)

    @app.on_event("startup")
    async def _start_debug_logging() -> None:
        install_debug_logging()
else:

    @app.get("/debug")
    async def debug_page_disabled() -> None:
        raise HTTPException(status_code=404, detail="Debug desativado")

    @app.get("/api/debug/logs")
    async def debug_logs_disabled() -> None:
        raise HTTPException(status_code=404, detail="Debug desativado")


_PREVIEW_LIMIT = 5000


def _truncate_text(text: str) -> str:
    if len(text) <= _PREVIEW_LIMIT:
        return text
    return f"{text[:_PREVIEW_LIMIT]}... [truncado, {len(text)} chars total]"


def _preview_json(value: Any) -> str:
    try:
        return _truncate_text(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return _truncate_text(repr(value))


def _response_preview(response: httpx.Response) -> str:
    try:
        text = response.text
        if not text:
            return "(vazio)"
        try:
            return _preview_json(response.json())
        except Exception:
            return _truncate_text(text)
    except Exception:
        return "(ilegível)"


async def _core_api_get(
    client: httpx.AsyncClient,
    path: str,
    *,
    context: str,
) -> httpx.Response:
    url = f"{CORE_API_URL}{path}"
    if not DEBUG_MODE:
        return await client.get(url)
    start = time.perf_counter()
    diag.info(f"{context}/core_api_request", method="GET", endpoint=path)
    try:
        response = await client.get(url)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.info(
            f"{context}/core_api_response",
            method="GET",
            endpoint=path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            body=_response_preview(response),
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.exception(
            f"{context}/core_api_error",
            exc,
            method="GET",
            endpoint=path,
            elapsed_ms=elapsed_ms,
        )
        raise


async def _core_api_post(
    client: httpx.AsyncClient,
    path: str,
    *,
    context: str,
    **kwargs: Any,
) -> httpx.Response:
    url = f"{CORE_API_URL}{path}"
    if not DEBUG_MODE:
        return await client.post(url, **kwargs)
    start = time.perf_counter()
    detail = "json" if "json" in kwargs else "files" if "files" in kwargs else "empty"
    diag.info(
        f"{context}/core_api_request",
        method="POST",
        endpoint=path,
        payload_type=detail,
        payload=_preview_json(kwargs.get("json")) if "json" in kwargs else detail,
    )
    try:
        response = await client.post(url, **kwargs)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.info(
            f"{context}/core_api_response",
            method="POST",
            endpoint=path,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            body=_response_preview(response),
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.exception(
            f"{context}/core_api_error",
            exc,
            method="POST",
            endpoint=path,
            elapsed_ms=elapsed_ms,
        )
        raise


async def _windmill_post(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    *,
    context: str,
) -> httpx.Response:
    if not DEBUG_MODE:
        return await client.post(WINDMILL_WEBHOOK_URL, json=payload)
    start = time.perf_counter()
    diag.info(f"{context}/windmill_request", payload=_preview_json(payload))
    try:
        response = await client.post(WINDMILL_WEBHOOK_URL, json=payload)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.info(
            f"{context}/windmill_response",
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            body=_response_preview(response),
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.exception(
            f"{context}/windmill_error",
            exc,
            elapsed_ms=elapsed_ms,
        )
        raise


async def _deepseek_post(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    context: str,
) -> httpx.Response:
    if not DEBUG_MODE:
        return await client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers=headers,
            json=payload,
        )
    start = time.perf_counter()
    safe_payload = {
        **payload,
        "messages": [
            {**msg, "content": f"({len(str(msg.get('content', '')))} chars)"}
            if msg.get("role") != "system"
            else msg
            for msg in payload.get("messages", [])
        ],
    }
    diag.info(f"{context}/deepseek_request", payload=_preview_json(safe_payload))
    try:
        response = await client.post(
            f"{DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.info(
            f"{context}/deepseek_response",
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            body=_response_preview(response),
        )
        return response
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
        diag.exception(
            f"{context}/deepseek_error",
            exc,
            elapsed_ms=elapsed_ms,
        )
        raise


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


def _pending_action_from_assist(options: list[str]) -> dict[str, Any] | None:
    if len(options) == 1:
        return {"action": "analyze_unit", "unit_name": options[0]}
    return None


def _remember_executed_action(session: dict[str, Any], action: dict[str, Any] | None) -> None:
    if not isinstance(action, dict) or not action.get("action"):
        return
    session["last_action"] = dict(action)
    session["pending_action"] = None
    if DEBUG_MODE:
        diag.info(
            "SESSION/action_executed",
            last_action=action,
            pending_action_cleared=True,
        )


def _append_history(session: dict[str, Any], role: str, content: str) -> None:
    text = content.strip()
    if not text:
        return
    session["history"].append({"role": role, "content": text})


def _apply_windmill_session_updates(
    session: dict[str, Any],
    body: dict[str, Any],
) -> None:
    suggested_action = body.get("suggested_action")
    if isinstance(suggested_action, dict) and suggested_action.get("action"):
        session["pending_action"] = dict(suggested_action)
        if DEBUG_MODE:
            diag.info(
                "SESSION/pending_action_set",
                source="windmill_suggested_action",
                pending_action=suggested_action,
            )
        return

    if body.get("action") == "pending" and isinstance(body.get("suggested_action"), dict):
        session["pending_action"] = dict(body["suggested_action"])
        if DEBUG_MODE:
            diag.info(
                "SESSION/pending_action_set",
                source="windmill_action_pending",
                pending_action=body["suggested_action"],
            )
        return

    last_result = body.get("last_result")
    if isinstance(last_result, dict):
        session["last_result"] = last_result
        if DEBUG_MODE:
            diag.info("SESSION/last_result_updated", last_result=last_result)
        unit_name = str(last_result.get("unit_name", "")).strip()
        if unit_name:
            action_name = str(body.get("action", "")).strip()
            column = str(
                last_result.get("column") or last_result.get("column_name") or ""
            ).strip()
            if action_name == "analyze_vertical" or column:
                _remember_executed_action(
                    session,
                    {
                        "action": "analyze_vertical",
                        "unit_name": unit_name,
                        "column": column,
                        "depth": str(last_result.get("depth", "layer2")).strip() or "layer2",
                    },
                )
            else:
                _remember_executed_action(
                    session,
                    {"action": "analyze_unit", "unit_name": unit_name},
                )
        return


def _parse_windmill_chat_response(response: httpx.Response, fallback_session_id: str) -> tuple[ChatResponse, dict[str, Any]]:
    try:
        body = response.json()
    except Exception as exc:
        text = response.text.strip()
        if DEBUG_MODE:
            diag.warning(
                "CHAT/windmill_non_json_response",
                raw_text=_truncate_text(text) if text else "(vazio)",
            )
        if not text:
            if DEBUG_MODE:
                diag.error("CHAT/windmill_empty_response")
            raise HTTPException(
                status_code=502,
                detail="Windmill retornou resposta vazia",
            ) from exc
        return ChatResponse(response=text, session_id=fallback_session_id), {}

    if not isinstance(body, dict):
        if DEBUG_MODE:
            diag.warning("CHAT/windmill_unexpected_body", body_type=type(body).__name__)
        return ChatResponse(response=str(body), session_id=fallback_session_id), {}

    response_text = body.get("response")
    if response_text is None:
        if DEBUG_MODE:
            diag.error("CHAT/windmill_missing_response_field", body=_preview_json(body))
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
    filename = file.filename or "upload"
    file_bytes = await file.read()
    if DEBUG_MODE:
        diag.info(
            "UPLOAD/received",
            filename=filename,
            size_bytes=len(file_bytes),
            content_type=file.content_type or "application/octet-stream",
        )
    if not file_bytes:
        if DEBUG_MODE:
            diag.warning("UPLOAD/rejected", reason="arquivo_vazio", filename=filename)
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    files = {
        "file": (
            filename,
            file_bytes,
            file.content_type or "application/octet-stream",
        )
    }

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            upstream = await _core_api_post(
                client,
                "/sessions",
                context="UPLOAD",
                files=files,
            )
    except httpx.TimeoutException as exc:
        if DEBUG_MODE:
            diag.exception("UPLOAD/timeout", exc, service="core_api")
        raise HTTPException(
            status_code=504,
            detail="Timeout ao criar sessão no core_api",
        ) from exc
    except httpx.RequestError as exc:
        if DEBUG_MODE:
            diag.exception("UPLOAD/unavailable", exc, service="core_api")
        raise HTTPException(
            status_code=502,
            detail=f"core_api indisponível: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        detail = _extract_upstream_detail(upstream, "core_api")
        if DEBUG_MODE:
            diag.error(
                "UPLOAD/core_api_error",
                status=upstream.status_code,
                detail=detail,
            )
        raise HTTPException(
            status_code=upstream.status_code,
            detail=detail,
        )

    try:
        payload = upstream.json()
        session_id = str(payload["session_id"])
        units = payload.get("units", [])
        if not isinstance(units, list):
            raise ValueError("units inválido")
    except (KeyError, TypeError, ValueError) as exc:
        if DEBUG_MODE:
            diag.exception("UPLOAD/invalid_payload", exc)
        raise HTTPException(
            status_code=502,
            detail="core_api retornou payload inválido ao criar sessão",
        ) from exc

    unit_names = [str(unit) for unit in units]
    if DEBUG_MODE:
        diag.info(
            "UPLOAD/success",
            session_id=session_id,
            filename=filename,
            size_bytes=len(file_bytes),
            units=unit_names,
        )
    return UploadResponse(
        session_id=session_id,
        filename=filename,
        units=unit_names,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id.strip()
    if not session_id:
        if DEBUG_MODE:
            diag.warning("CHAT/rejected", reason="session_id_obrigatorio")
        raise HTTPException(status_code=400, detail="session_id obrigatório.")

    message = request.message.strip()
    if not message:
        if DEBUG_MODE:
            diag.warning("CHAT/rejected", reason="mensagem_vazia", session_id=session_id)
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    session = _get_session(session_id)
    if DEBUG_MODE:
        diag.info(
            "CHAT/received",
            session_id=session_id,
            message=message,
            pending_action=session.get("pending_action"),
            last_action=session.get("last_action"),
        )
    _append_history(session, "user", message)

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            units = await _fetch_session_units(client, session_id)
    except HTTPException as exc:
        if DEBUG_MODE:
            diag.error(
                "CHAT/session_validation_failed",
                session_id=session_id,
                status=exc.status_code,
                detail=exc.detail,
            )
        raise
    except httpx.TimeoutException as exc:
        if DEBUG_MODE:
            diag.exception("CHAT/timeout", exc, service="core_api")
        raise HTTPException(
            status_code=504,
            detail="Timeout ao validar sessão no core_api",
        ) from exc
    except httpx.RequestError as exc:
        if DEBUG_MODE:
            diag.exception("CHAT/unavailable", exc, service="core_api")
        raise HTTPException(
            status_code=502,
            detail=f"core_api indisponível: {exc}",
        ) from exc

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
            upstream = await _windmill_post(client, payload, context="CHAT")
    except httpx.TimeoutException as exc:
        if DEBUG_MODE:
            diag.exception("CHAT/windmill_timeout", exc)
        raise HTTPException(
            status_code=504,
            detail="Timeout no webhook Windmill",
        ) from exc
    except httpx.RequestError as exc:
        if DEBUG_MODE:
            diag.exception("CHAT/windmill_unavailable", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Windmill indisponível: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        detail = _extract_upstream_detail(upstream, "Windmill")
        if DEBUG_MODE:
            diag.error("CHAT/windmill_http_error", status=upstream.status_code, detail=detail)
        raise HTTPException(
            status_code=upstream.status_code,
            detail=detail,
        )

    chat_response, windmill_body = _parse_windmill_chat_response(upstream, session_id)
    if DEBUG_MODE:
        diag.info(
            "CHAT/windmill_parsed",
            raw_body=_preview_json(windmill_body),
            response_text=chat_response.response,
        )
    _apply_windmill_session_updates(session, windmill_body)
    _append_history(session, "assistant", chat_response.response)

    if DEBUG_MODE:
        diag.info(
            "CHAT/response_sent",
            session_id=session_id,
            response=chat_response.response,
            pending_action=session.get("pending_action"),
            last_action=session.get("last_action"),
        )
    return chat_response


async def _fetch_session_units(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    context: str = "CHAT",
) -> list[str]:
    upstream = await _core_api_get(
        client,
        f"/sessions/{session_id}/units",
        context=context,
    )
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
        if DEBUG_MODE:
            diag.exception("CHAT/invalid_units_payload", exc, session_id=session_id)
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
        if DEBUG_MODE:
            diag.exception("ASSIST/invalid_llm_json", exc, content=_truncate_text(text))
        raise HTTPException(
            status_code=502,
            detail="DeepSeek retornou JSON inválido para /assist",
        ) from exc
    if not isinstance(payload, dict):
        if DEBUG_MODE:
            diag.error("ASSIST/invalid_llm_payload", payload_type=type(payload).__name__)
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
            upstream = await _deepseek_post(
                client,
                payload,
                headers,
                context="ASSIST",
            )
    except httpx.TimeoutException as exc:
        if DEBUG_MODE:
            diag.exception("ASSIST/deepseek_timeout", exc)
        raise HTTPException(
            status_code=504,
            detail="Timeout ao chamar DeepSeek para /assist",
        ) from exc
    except httpx.RequestError as exc:
        if DEBUG_MODE:
            diag.exception("ASSIST/deepseek_unavailable", exc)
        raise HTTPException(
            status_code=502,
            detail=f"DeepSeek indisponível: {exc}",
        ) from exc

    if upstream.status_code >= 400:
        detail = _extract_upstream_detail(upstream, "DeepSeek")
        if DEBUG_MODE:
            diag.error("ASSIST/deepseek_http_error", status=upstream.status_code, detail=detail)
        raise HTTPException(
            status_code=upstream.status_code,
            detail=detail,
        )

    try:
        body = upstream.json()
        content = str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if DEBUG_MODE:
            diag.exception("ASSIST/deepseek_invalid_response", exc)
        raise HTTPException(
            status_code=502,
            detail="DeepSeek retornou resposta sem conteúdo para /assist",
        ) from exc

    return _parse_assist_llm_content(content)


@app.post("/assist", response_model=AssistResponse)
async def assist(request: AssistRequest) -> AssistResponse:
    session_id = request.session_id.strip()
    if not session_id:
        if DEBUG_MODE:
            diag.warning("ASSIST/rejected", reason="session_id_obrigatorio")
        raise HTTPException(status_code=400, detail="session_id obrigatório.")

    message = request.message.strip()
    if not message:
        if DEBUG_MODE:
            diag.warning("ASSIST/rejected", reason="mensagem_vazia", session_id=session_id)
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    if DEBUG_MODE:
        diag.info(
            "ASSIST/received",
            session_id=session_id,
            message=message,
            context_units=request.context.units,
        )

    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT_SECONDS) as client:
            units = await _fetch_session_units(client, session_id, context="ASSIST")
    except HTTPException as exc:
        if DEBUG_MODE:
            diag.error(
                "ASSIST/session_validation_failed",
                session_id=session_id,
                status=exc.status_code,
                detail=exc.detail,
            )
        raise
    except httpx.TimeoutException as exc:
        if DEBUG_MODE:
            diag.exception("ASSIST/timeout", exc, service="core_api")
        raise HTTPException(
            status_code=504,
            detail="Timeout ao validar sessão no core_api",
        ) from exc
    except httpx.RequestError as exc:
        if DEBUG_MODE:
            diag.exception("ASSIST/unavailable", exc, service="core_api")
        raise HTTPException(
            status_code=502,
            detail=f"core_api indisponível: {exc}",
        ) from exc

    if not units:
        if DEBUG_MODE:
            diag.warning("ASSIST/rejected", reason="sessao_sem_unidades", session_id=session_id)
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
            if DEBUG_MODE:
                diag.warning(
                    "ASSIST/fallback",
                    reason="deepseek_indisponivel",
                    status=exc.status_code,
                    detail=exc.detail,
                )
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
        if DEBUG_MODE:
            diag.info("ASSIST/suggestion_fallback", suggestion=suggestion)

    pending = _pending_action_from_assist(options)
    if pending is not None:
        assist_session = _get_session(session_id)
        assist_session["pending_action"] = dict(pending)
        if DEBUG_MODE:
            diag.info(
                "SESSION/pending_action_set",
                source="assist_single_option",
                pending_action=pending,
            )

    if DEBUG_MODE:
        diag.info(
            "ASSIST/response_sent",
            session_id=session_id,
            suggestion=suggestion,
            options=options,
        )

    return AssistResponse(
        suggestion=suggestion,
        options=options,
        session_id=session_id,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web:app", host="127.0.0.1", port=8080, reload=False)
