from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator import (
    MAX_ATTEMPTS_PER_TURN,
    OrchestratorSession,
    compress_assistant_message,
    print_session_query_candidates,
    render_schema_message,
    render_tables_message,
)


load_dotenv()


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
REQUEST_TIMEOUT_SECONDS = 60.0
UPLOAD_TIMEOUT_SECONDS = 300.0

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    session_id: str
    file_path: str
    orchestrator: OrchestratorSession
    structural_context: str


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
    session_id: str


app = FastAPI(title="Cartographer Web")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESSIONS: dict[str, SessionState] = {}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/upload", response_model=ChatResponse)
async def upload(file: UploadFile = File(...)) -> ChatResponse:
    suffix = Path(file.filename or "").suffix or ".bin"
    with NamedTemporaryFile(delete=False, suffix=suffix, dir="/tmp") as tmp:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            tmp.write(chunk)
        temp_path = tmp.name

    try:
        session_id, opening = await asyncio.wait_for(
            asyncio.to_thread(_create_session, temp_path),
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.exception("Upload failed for file %s", file.filename)
        detail = str(exc).strip() or exc.__class__.__name__ or "Erro desconhecido no upload."
        raise HTTPException(status_code=400, detail=detail) from exc

    return ChatResponse(response=opening, session_id=session_id)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    state = SESSIONS.get(request.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia.")

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_run_turn, state, message),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Tempo limite excedido para processar a mensagem.") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChatResponse(response=response, session_id=request.session_id)


def _create_session(file_path: str) -> tuple[str, str]:
    orchestrator = OrchestratorSession(file_path)
    structural_context, opening = orchestrator.bootstrap()
    session_id = str(uuid4())
    SESSIONS[session_id] = SessionState(
        session_id=session_id,
        file_path=file_path,
        orchestrator=orchestrator,
        structural_context=structural_context,
    )
    return session_id, opening


def _run_turn(state: SessionState, user_text: str) -> str:
    session = state.orchestrator
    if user_text.lower() == "ajuda":
        return "Envie uma pergunta sobre o arquivo carregado. Se quiser encerrar, feche a página."
    if user_text.lower() == "mapa":
        return session.render_knowledge_map()
    if user_text.lower() == "sair":
        print_session_query_candidates(session)
        return "Sessão encerrada no chat web. Faça novo upload para recomeçar."

    session.history.append({"role": "user", "content": user_text})
    last_error: str | None = None
    last_result: str | None = None
    executed_queries: list[str] = []

    for attempt_number in range(1, MAX_ATTEMPTS_PER_TURN + 1):
        try:
            action_payload = session.orchestrate(
                user_text,
                state.structural_context,
                last_error=last_error,
                last_result=last_result,
                executed_queries=executed_queries,
                query_catalog=sorted(session.catalog_for_session().keys()),
                attempt_number=attempt_number,
            )
            execution_result = session.execute_action(action_payload)
            last_error = None
            last_result = execution_result
            if action_payload["action"] == "query":
                query_id = str(action_payload.get("query_id", "")).strip()
                if query_id and query_id not in executed_queries:
                    executed_queries.append(query_id)

            if action_payload["action"] == "done":
                final_text = session.interface_reply(
                    "Apresente a conclusão final ao usuário com base no texto da orquestradora.",
                    result_context=execution_result,
                )
                session.history.append({"role": "assistant", "content": compress_assistant_message(final_text)})
                print_session_query_candidates(session)
                return final_text

            if action_payload["action"] == "tables":
                reply = render_tables_message(execution_result)
                session.history.append({"role": "assistant", "content": compress_assistant_message(reply)})
                return reply

            if action_payload["action"] == "schema":
                reply = render_schema_message(execution_result)
                session.history.append({"role": "assistant", "content": compress_assistant_message(reply)})
                return reply

            reply = session.interface_reply(
                "Explique este resultado ao usuário, responda à pergunta atual e sugira o próximo passo.",
                result_context=execution_result,
            )
            session.history.append({"role": "assistant", "content": compress_assistant_message(reply)})
            return reply
        except Exception as exc:
            last_error = f"Erro operacional: {exc}"
            if attempt_number >= MAX_ATTEMPTS_PER_TURN:
                error_reply = session.interface_reply(
                    "Explique ao usuário que não foi possível executar a análise pedida após múltiplas tentativas e sugira uma reformulação.",
                    result_context=last_error,
                )
                session.history.append({"role": "assistant", "content": compress_assistant_message(error_reply)})
                return error_reply

    raise RuntimeError("Fluxo do chat terminou sem resposta.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web:app", host="127.0.0.1", port=8080, reload=False)
