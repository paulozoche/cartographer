from __future__ import annotations

import json
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

_BUFFER_MAXLEN = 2000
_TRUNCATE_LIMIT = 5000
_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

_buffer: deque[dict[str, Any]] = deque(maxlen=_BUFFER_MAXLEN)
_lock = threading.Lock()
_installed = False


class _DebugLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "lineno": record.lineno,
            }
            with _lock:
                _buffer.append(entry)
        except Exception:
            pass


def install_debug_logging() -> None:
    global _installed
    if _installed:
        return
    handler = _DebugLogHandler()
    handler.setLevel(logging.DEBUG)
    for name in ("uvicorn.access", "uvicorn.error", "web.diag"):
        log = logging.getLogger(name)
        log.addHandler(handler)
        if log.level == logging.NOTSET or log.level > logging.DEBUG:
            log.setLevel(logging.DEBUG)
        log.propagate = False
    _installed = True


def _get_logs(limit: int, level: str | None) -> list[dict[str, Any]]:
    min_level = _LEVEL_ORDER.get(level.upper(), 0) if level else 0
    with _lock:
        entries = list(_buffer)
    if min_level:
        entries = [
            entry
            for entry in entries
            if _LEVEL_ORDER.get(entry["level"], 0) >= min_level
        ]
    if limit > 0:
        entries = entries[-limit:]
    return entries


def truncate_text(text: str, limit: int = _TRUNCATE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncado, {len(text)} chars total]"


def preview_json(value: Any) -> str:
    try:
        return truncate_text(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return truncate_text(repr(value))


class Diag:
    _logger = logging.getLogger("web.diag")

    @classmethod
    def _format_fields(cls, fields: dict[str, Any]) -> str:
        parts: list[str] = []
        for key, value in fields.items():
            if isinstance(value, (dict, list, tuple)):
                parts.append(f"{key}={preview_json(value)}")
            elif value is None:
                parts.append(f"{key}=null")
            else:
                parts.append(f"{key}={value}")
        return " | ".join(parts)

    @classmethod
    def info(cls, event: str, **fields: Any) -> None:
        try:
            suffix = cls._format_fields(fields) if fields else ""
            message = f"[{event}] {suffix}".rstrip()
            cls._logger.info(message)
        except Exception:
            pass

    @classmethod
    def warning(cls, event: str, **fields: Any) -> None:
        try:
            suffix = cls._format_fields(fields) if fields else ""
            message = f"[{event}] {suffix}".rstrip()
            cls._logger.warning(message)
        except Exception:
            pass

    @classmethod
    def error(cls, event: str, **fields: Any) -> None:
        try:
            suffix = cls._format_fields(fields) if fields else ""
            message = f"[{event}] {suffix}".rstrip()
            cls._logger.error(message)
        except Exception:
            pass

    @classmethod
    def exception(cls, event: str, exc: BaseException | None = None, **fields: Any) -> None:
        try:
            suffix = cls._format_fields(fields) if fields else ""
            message = f"[{event}] {suffix}".rstrip()
            cls._logger.exception(message, exc_info=exc)
        except Exception:
            pass


diag = Diag()

_DEBUG_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Debug Logs</title>
  <style>
    body { font-family: monospace; background: #1e1e1e; color: #d4d4d4; margin: 0; padding: 1rem; }
    header { display: flex; align-items: center; gap: 1rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
    h1 { font-size: 1.1rem; margin: 0; color: #569cd6; }
    #copyBtn {
      font-family: monospace; font-size: 0.8rem; cursor: pointer;
      background: #2d2d2d; color: #d4d4d4; border: 1px solid #555; padding: 0.35rem 0.75rem;
    }
    #copyBtn:hover { background: #3c3c3c; }
    #copyBtn.ok { color: #4ec9b0; border-color: #4ec9b0; }
    #status { font-size: 0.85rem; color: #808080; margin-bottom: 0.5rem; }
    #logs { white-space: pre-wrap; word-break: break-word; font-size: 0.8rem; line-height: 1.4; }
    .DEBUG { color: #808080; }
    .INFO { color: #4ec9b0; }
    .WARNING { color: #dcdcaa; }
    .ERROR, .CRITICAL { color: #f44747; }
  </style>
</head>
<body>
  <header>
    <h1>Debug Logs</h1>
    <button id="copyBtn" type="button">Copiar tudo</button>
  </header>
  <div id="status">Carregando…</div>
  <div id="logs"></div>
  <script>
    const logsEl = document.getElementById("logs");
    const statusEl = document.getElementById("status");
    const copyBtn = document.getElementById("copyBtn");
    let allLogs = [];

    function formatEntry(entry) {
      const ts = entry.timestamp || "";
      const level = entry.level || "INFO";
      const logger = entry.logger || "";
      const msg = entry.message || "";
      return `[${ts}] ${level} ${logger}: ${msg}`;
    }

    function renderEntry(entry) {
      const cls = entry.level || "INFO";
      return `<div class="${cls}">${formatEntry(entry)}</div>`;
    }

    async function fetchAllLogs() {
      const res = await fetch("/api/debug/logs?limit=2000");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      allLogs = data.logs || [];
      return allLogs;
    }

    async function refresh() {
      try {
        const logs = await fetchAllLogs();
        logsEl.innerHTML = logs.map(renderEntry).join("");
        statusEl.textContent = `${logs.length} entradas · atualizado ${new Date().toLocaleTimeString()}`;
        window.scrollTo(0, document.body.scrollHeight);
      } catch (err) {
        statusEl.textContent = "Falha ao buscar logs";
      }
    }

    copyBtn.addEventListener("click", async () => {
      try {
        const logs = allLogs.length ? allLogs : await fetchAllLogs();
        const text = logs.map(formatEntry).join("\\n");
        await navigator.clipboard.writeText(text);
        copyBtn.textContent = `Copiado (${logs.length})`;
        copyBtn.classList.add("ok");
        setTimeout(() => {
          copyBtn.textContent = "Copiar tudo";
          copyBtn.classList.remove("ok");
        }, 2000);
      } catch (err) {
        copyBtn.textContent = "Falha ao copiar";
        setTimeout(() => { copyBtn.textContent = "Copiar tudo"; }, 2000);
      }
    });

    refresh();
    setInterval(refresh, 1500);
  </script>
</body>
</html>
"""


def register_debug_routes(app: FastAPI) -> None:
    @app.get("/debug", response_class=HTMLResponse)
    async def debug_page() -> HTMLResponse:
        return HTMLResponse(content=_DEBUG_HTML)

    @app.get("/api/debug/logs")
    async def debug_logs_api(
        limit: int = Query(default=200, ge=1, le=_BUFFER_MAXLEN),
        level: str | None = Query(default=None),
    ) -> JSONResponse:
        if level and level.upper() not in _LEVEL_ORDER:
            raise HTTPException(
                status_code=400,
                detail=f"Nível inválido: {level}",
            )
        return JSONResponse(content={"logs": _get_logs(limit, level)})
