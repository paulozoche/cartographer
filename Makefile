.PHONY: web core-api windmill-deploy

# Prefer project venv; fall back to python3 on PATH.
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
UVICORN := $(if $(wildcard .venv/bin/uvicorn),.venv/bin/uvicorn,uvicorn)

# Proxy fino: frontend → web.py → core_api (dados) + Windmill/n8n (interpretação)
web:
	$(UVICORN) web:app --host 127.0.0.1 --port 8080 --reload

# API determinística de análise estrutural (sem LLM)
core-api:
	$(UVICORN) core_api.app:app --host 127.0.0.1 --port 8000 --reload

# Deploy workflow Cartographer Chat no Windmill (requer WINDMILL_TOKEN ou WINDMILL_PASSWORD)
windmill-deploy:
	$(PYTHON) scripts/deploy_cartographer_windmill.py
