# Cartographer

> Structural analysis API for tabular data — agnostic, deterministic, AI-assisted.

Cartographer analyzes the **structure** of tabular datasets — not their business meaning. It detects patterns, computes metrics, ranks columns by structural signal, and exposes everything through a clean FastAPI interface. AI is used only after the structural analysis is complete, never to replace it.

---

## What it does

Given a tabular dataset (CSV, Parquet, or SQLite), Cartographer:

- Computes **Layer 1 and Layer 2 metrics** per column: null ratio, cardinality, entropy, frequency distribution, value length statistics, and more
- Applies **registered heuristics**: identifier detection, high cardinality signals, sequential patterns, near-unique conflicts
- Computes a **structural signal** per column that drives ranking
- Generates **explanations and suggestions** per column based on structural evidence
- Renders results as **Markdown summaries**
- Exposes **shareable analysis states** with signed links and revocation support
- Optionally **consults an AI layer** post-analysis for natural language interpretation

---

## Stack

- **Python 3.12** · **FastAPI** · **Pydantic** · **python-multipart** *(uploads)* · **Redis** *(optional)*

---

## Run locally

```bash
git clone https://github.com/paulozoche/cartographer.git
cd cartographer
python -m venv .venv && source .venv/bin/activate

# Install the agnostic library (required before core_api or tests)
pip install -e .

pip install -r requirements.txt
cd core_api && pip install -r requirements.txt && cd ..
```

`python-multipart` is required for file uploads in both `web.py` (`POST /upload`) and `core_api` (`POST /sessions`). It is listed in the root `requirements.txt`; installing only `core_api/requirements.txt` in a separate venv is no longer supported.

### Web proxy (recomendado)

O frontend em `static/index.html` conversa com `web.py`, um proxy fino que delega dados ao **core_api** e interpretação ao **n8n**:

```text
frontend (static/index.html)
    → web.py (:8080)  — GET /, POST /upload, POST /chat
        → core_api (:8000)  — sessões e análise estrutural determinística
        → n8n (:5678)       — webhook de chat / LLM
```

```bash
make core-api   # terminal 1 — API determinística
make web        # terminal 2 — proxy + frontend (http://127.0.0.1:8080/)
# n8n com webhook /webhook/chat — Fase 4
```

Variáveis relevantes (ver `.env.example`): `CORE_API_URL`, `N8N_WEBHOOK_URL`.

### Core API

The deterministic REST service lives in `core_api/`. It depends on the editable `agnostic` package:

```bash
make core-api
# ou: uvicorn core_api.app:app --host 127.0.0.1 --port 8000
```

Endpoints: `POST /sessions` (upload), `GET /sessions/{id}/units`, `GET /sessions/{id}/units/{name}/analysis`.

---

## Tests

```bash
pytest tests/unit/test_web_proxy.py tests/unit/test_interpretar_intencao.py
```

---

## Author

**Paulo Henrique Zoche** · [paulozoche@gmail.com](mailto:paulozoche@gmail.com)
