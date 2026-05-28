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

- **Python 3.12** · **FastAPI** · **Pydantic** · **Redis** *(optional)*

---

## Run locally

```bash
git clone https://github.com/paulozoche/cartographer.git
cd cartographer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make server
```

---

## Tests

```bash
pytest tests/unit/
pytest tests/integration/
```

---

## Author

**Paulo Henrique Zoche** · [paulozoche@gmail.com](mailto:paulozoche@gmail.com)
