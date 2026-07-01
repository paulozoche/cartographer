from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_PATH / "src"))

import tempfile
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(_PROJECT_ROOT / ".env")

from agnostic.infrastructure.source_resolver import resolve_source

from core_api.core_service import CoreService
from core_api.models import (
    AnalyzeHorizontalRequest,
    AnalyzeUnitRequest,
    AnalyzeVerticalRequest,
    RecallRequest,
    SessionCreateResponse,
    UnitsResponse,
)

SESSIONS: dict[str, CoreService] = {}


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    SESSIONS.clear()
    yield


app = FastAPI(title="Agnostic Core API", version="1.0.0", lifespan=_lifespan)


def _get_session_service(session_id: str) -> CoreService:
    service = SESSIONS.get(session_id)
    if service is None:
        raise HTTPException(status_code=404, detail=f"Sessão não encontrada: {session_id}")
    return service


@app.get("/health")
def health() -> dict[str, str | int]:
    return {"status": "ok", "active_sessions": len(SESSIONS)}


@app.post("/sessions", response_model=SessionCreateResponse)
async def create_session(file: UploadFile = File(...)) -> SessionCreateResponse:
    suffix = Path(file.filename or "upload").suffix or ".sqlite"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        source = resolve_source(tmp_path)
        service = CoreService.from_source(source)
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = service
        return SessionCreateResponse(session_id=session_id, units=service.unit_names)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/sessions/{session_id}/units", response_model=UnitsResponse)
def list_session_units(session_id: str) -> UnitsResponse:
    service = _get_session_service(session_id)
    return UnitsResponse(session_id=session_id, units=service.unit_names)


@app.post("/sessions/{session_id}/analyze_unit")
def analyze_unit(session_id: str, request: AnalyzeUnitRequest) -> dict[str, object]:
    service = _get_session_service(session_id)
    try:
        return service.analyze_unit(request.unit_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/analyze_vertical")
def analyze_vertical(session_id: str, request: AnalyzeVerticalRequest) -> dict[str, object]:
    service = _get_session_service(session_id)
    try:
        return service.analyze_vertical(request.unit_name, request.depth, request.key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/analyze_horizontal")
def analyze_horizontal(session_id: str, request: AnalyzeHorizontalRequest) -> dict[str, str]:
    service = _get_session_service(session_id)
    try:
        return service.analyze_horizontal(request.unit_a, request.unit_b)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/sessions/{session_id}/recall")
def recall(session_id: str, request: RecallRequest) -> object:
    service = _get_session_service(session_id)
    try:
        return service.recall(request.cache_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
