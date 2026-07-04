.PHONY: web core-api cache-worker windmill-deploy up up-debug down

# Prefer project venv; fall back to python3 on PATH.
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
UVICORN := $(if $(wildcard .venv/bin/uvicorn),.venv/bin/uvicorn,uvicorn)

# Proxy fino: frontend → web.py → core_api (dados) + Windmill/n8n (interpretação)
web:
	$(UVICORN) web:app --host 127.0.0.1 --port 8080 --reload

# API determinística de análise estrutural (sem LLM)
core-api:
	$(UVICORN) core_api.app:app --host 127.0.0.1 --port 8000 --reload

# Worker de manutenção do cache Redis (requer AGNOSTIC_REDIS_URL ou usa fallback)
cache-worker:
	$(PYTHON) main.py worker

# Deploy workflow Cartographer Chat no Windmill (requer WINDMILL_TOKEN ou WINDMILL_PASSWORD)
windmill-deploy:
	$(PYTHON) scripts/deploy_cartographer_windmill.py

# Sobe Windmill (Docker), Core API e Web em background
up:
	@echo "Subindo Windmill, Core API e Web..."
	docker start windmill || docker compose up -d windmill
	@(make core-api > /tmp/cartographer_core.log 2>&1 &)
	@(make web > /tmp/cartographer_web.log 2>&1 &)
	@sleep 2
	@echo "Core API → :8000  (log: /tmp/cartographer_core.log)"
	@echo "Web       → :8080  (log: /tmp/cartographer_web.log)"
	@echo "Windmill  → :8002"

# Sobe Windmill (Docker), Core API e Web em background com painel de debug
up-debug:
	@echo "Subindo Windmill, Core API e Web (com painel de debug)..."
	docker start windmill || docker compose up -d windmill
	@(make core-api > /tmp/cartographer_core.log 2>&1 &)
	@(DEBUG_MODE=1 make web > /tmp/cartographer_web.log 2>&1 &)
	@sleep 2
	@echo "Core API → :8000  (log: /tmp/cartographer_core.log)"
	@echo "Web       → :8080  (log: /tmp/cartographer_web.log)"
	@echo "Painel de debug → http://localhost:8080/debug"
	@echo "Windmill  → :8002"

# Para Core API e Web (portas 8000 e 8080)
down:
	@fuser -k 8000/tcp 8080/tcp 2>/dev/null || true
	@echo "Core API e Web parados."
