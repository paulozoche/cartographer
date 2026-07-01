#!/usr/bin/env python3
"""Deploy Cartographer Chat workflow to Windmill."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WINDMILL_DIR = ROOT / "windmill" / "f" / "cartographer"

DEFAULT_BASE_URL = "http://localhost:8002/api"
DEFAULT_WORKSPACE = "admins"
FLOW_PATH = "f/cartographer/cartographer_chat"
SCRIPT_PATHS = {
    "interpretar_intencao": "f/cartographer/interpretar_intencao",
    "chamar_core_api": "f/cartographer/chamar_core_api",
    "formatar_resposta": "f/cartographer/formatar_resposta",
}


def _load_env() -> None:
    load_dotenv(ROOT / ".env")


def _api_base() -> str:
    base = os.getenv("WINDMILL_URL", "http://localhost:8002").rstrip("/")
    if not base.endswith("/api"):
        base = f"{base}/api"
    return base


def _auth_token(client: httpx.Client) -> str:
    token = os.getenv("WINDMILL_TOKEN", "").strip()
    if token:
        return token

    email = os.getenv("WINDMILL_EMAIL", "admin@windmill.dev").strip()
    password = os.getenv("WINDMILL_PASSWORD", "").strip()
    if not password:
        raise SystemExit(
            "Defina WINDMILL_TOKEN ou WINDMILL_PASSWORD no .env para autenticar no Windmill."
        )

    response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    body = response.json()
    token = body.get("token") if isinstance(body, dict) else None
    if not token:
        raise SystemExit("Login no Windmill não retornou token.")
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _read_script(name: str) -> str:
    return (WINDMILL_DIR / f"{name}.py").read_text(encoding="utf-8")


def _script_schema(content: str) -> dict:
    # Minimal schema; Windmill accepts empty object for scripts without typed args in metadata.
    if "user_message" in content and "session_id" in content and "core_result" not in content:
        if "unit_name" in content and "action" in content:
            return {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "user_message": {"type": "string"},
                    "session_id": {"type": "string"},
                    "pending_action": {"type": "object"},
                    "last_action": {"type": "object"},
                },
                "required": ["user_message", "session_id"],
            }
        if "unit_name" in content:
            return {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "unit_name": {"type": "string"},
                    "action": {"type": "string", "default": "analyze_unit"},
                    "column": {"type": "string", "default": ""},
                    "depth": {"type": "string", "default": "layer2"},
                    "response": {"type": "string", "default": ""},
                },
                "required": ["session_id", "unit_name"],
            }
    if "core_result" in content and "action" in content:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "core_result": {"type": "object"},
                "session_id": {"type": "string"},
                "action": {"type": "string", "default": "analyze_unit"},
            },
            "required": ["core_result", "session_id"],
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "core_result": {"type": "object"},
            "session_id": {"type": "string"},
        },
        "required": ["core_result", "session_id"],
    }


def _upsert_script(
    client: httpx.Client,
    token: str,
    workspace: str,
    path: str,
    summary: str,
    content: str,
    envs: list[str],
) -> None:
    exists = client.get(
        f"/w/{workspace}/scripts/exists/p/{path}",
        headers=_headers(token),
    )
    payload = {
        "path": path,
        "summary": summary,
        "description": summary,
        "content": content,
        "language": "python3",
        "schema": _script_schema(content),
        "envs": envs,
    }
    if exists.status_code == 200 and exists.json() is True:
        current = client.get(
            f"/w/{workspace}/scripts/get/p/{path}",
            headers=_headers(token),
        )
        current.raise_for_status()
        payload["parent_hash"] = current.json()["hash"]
        create = client.post(
            f"/w/{workspace}/scripts/create",
            headers=_headers(token),
            json=payload,
        )
        if create.status_code == 400 and "same hash" in create.text.lower():
            print(f"Script sem alterações: {path}")
            return
        create.raise_for_status()
        print(f"Atualizado script: {path}")
        return

    create = client.post(
        f"/w/{workspace}/scripts/create",
        headers=_headers(token),
        json=payload,
    )
    if create.status_code == 400 and "same hash" in create.text.lower():
        print(f"Script já existe: {path}")
        return
    create.raise_for_status()
    print(f"Criado script: {path}")


def _upsert_variable(
    client: httpx.Client,
    token: str,
    workspace: str,
    path: str,
    value: str,
    *,
    is_secret: bool,
    description: str,
) -> None:
    exists = client.get(
        f"/w/{workspace}/variables/exists/{path}",
        headers=_headers(token),
    )
    payload = {
        "path": path,
        "value": value,
        "is_secret": is_secret,
        "description": description,
    }
    if exists.status_code == 200 and exists.json() is True:
        update = client.post(
            f"/w/{workspace}/variables/update/{path}",
            headers=_headers(token),
            json={"value": value, "is_secret": is_secret, "description": description},
        )
        update.raise_for_status()
        print(f"Atualizada variável: {path}")
        return

    create = client.post(
        f"/w/{workspace}/variables/create",
        headers=_headers(token),
        json=payload,
    )
    create.raise_for_status()
    print(f"Criada variável: {path}")


def _flow_payload() -> dict:
    return {
        "path": FLOW_PATH,
        "summary": "Cartographer Chat",
        "description": "Workflow de chat do Cartographer (substitui n8n).",
        "schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "message": {"type": "string"},
                "pending_action": {"type": "object"},
                "last_action": {"type": "object"},
                "history": {"type": "array"},
                "last_result": {"type": "object"},
            },
            "required": ["session_id", "message"],
        },
        "value": {
            "modules": [
                {
                    "id": "interpretar_intencao",
                    "summary": "Interpretar intenção do usuário",
                    "value": {
                        "type": "script",
                        "path": SCRIPT_PATHS["interpretar_intencao"],
                        "input_transforms": {
                            "user_message": {
                                "type": "javascript",
                                "expr": "flow_input.message",
                            },
                            "session_id": {
                                "type": "javascript",
                                "expr": "flow_input.session_id",
                            },
                            "pending_action": {
                                "type": "javascript",
                                "expr": "flow_input.pending_action || null",
                            },
                            "last_action": {
                                "type": "javascript",
                                "expr": "flow_input.last_action || null",
                            },
                            "history": {
                                "type": "javascript",
                                "expr": "flow_input.history || []",
                            },
                        },
                    },
                },
                {
                    "id": "chamar_core_api",
                    "summary": "Chamar Core API",
                    "value": {
                        "type": "script",
                        "path": SCRIPT_PATHS["chamar_core_api"],
                        "input_transforms": {
                            "session_id": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.session_id",
                            },
                            "unit_name": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.unit_name || ''",
                            },
                            "action": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.action",
                            },
                            "column": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.column || ''",
                            },
                            "depth": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.depth || 'layer2'",
                            },
                            "response": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.response || ''",
                            },
                            "suggested_action": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.suggested_action || null",
                            },
                        },
                    },
                },
                {
                    "id": "formatar_resposta",
                    "summary": "Formatar resposta para o usuário",
                    "value": {
                        "type": "script",
                        "path": SCRIPT_PATHS["formatar_resposta"],
                        "input_transforms": {
                            "core_result": {
                                "type": "javascript",
                                "expr": "results.chamar_core_api",
                            },
                            "session_id": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.session_id",
                            },
                            "action": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.action",
                            },
                            "suggested_action": {
                                "type": "javascript",
                                "expr": "results.interpretar_intencao.suggested_action || null",
                            },
                        },
                    },
                },
            ],
        },
    }


def _upsert_flow(client: httpx.Client, token: str, workspace: str) -> None:
    path = FLOW_PATH
    exists = client.get(
        f"/w/{workspace}/flows/exists/{path}",
        headers=_headers(token),
    )
    payload = _flow_payload()
    if exists.status_code == 200 and exists.json() is True:
        update = client.post(
            f"/w/{workspace}/flows/update/{path}",
            headers=_headers(token),
            json=payload,
        )
        update.raise_for_status()
        print(f"Atualizado flow: {path}")
        return

    create = client.post(
        f"/w/{workspace}/flows/create",
        headers=_headers(token),
        json=payload,
    )
    create.raise_for_status()
    print(f"Criado flow: {path}")


def _ensure_webhook_token(client: httpx.Client, token: str, workspace: str) -> str:
    label = "cartographer-chat-webhook"
    existing = client.get(
        "/users/tokens/list",
        headers=_headers(token),
    )
    existing.raise_for_status()
    tokens = existing.json()
    for item in tokens if isinstance(tokens, list) else []:
        if item.get("label") == label and item.get("workspace_id") == workspace:
            fallback = os.getenv("WINDMILL_WEBHOOK_TOKEN", os.getenv("WINDMILL_TOKEN", "")).strip()
            if fallback:
                print(f"Reutilizando token existente: {label}")
                return fallback

    scope = f"jobs:run:flows:{FLOW_PATH}"
    create = client.post(
        "/users/tokens/create",
        headers=_headers(token),
        json={
            "label": label,
            "workspace_id": workspace,
            "scopes": [scope],
        },
    )
    create.raise_for_status()
    webhook_token = create.text.strip()
    if not webhook_token:
        raise SystemExit("Não foi possível criar token de webhook.")
    print(f"Criado token de webhook com escopo {scope}")
    return webhook_token


def _webhook_url(workspace: str, webhook_token: str) -> str:
    public_base = os.getenv("WINDMILL_URL", "http://localhost:8002").rstrip("/")
    api_base = public_base if public_base.endswith("/api") else f"{public_base}/api"
    return (
        f"{api_base}/w/{workspace}/jobs/run_wait_result/f/{FLOW_PATH}"
        f"?token={webhook_token}"
    )


def main() -> int:
    _load_env()
    workspace = os.getenv("WINDMILL_WORKSPACE", DEFAULT_WORKSPACE).strip()
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    core_api_url = os.getenv("CORE_API_URL", "http://localhost:8000").strip()
    if not deepseek_key:
        raise SystemExit("DEEPSEEK_API_KEY ausente no .env")
    if not core_api_url:
        raise SystemExit("CORE_API_URL ausente no .env")

    with httpx.Client(base_url=_api_base(), timeout=60.0) as client:
        token = _auth_token(client)
        _upsert_variable(
            client,
            token,
            workspace,
            "f/cartographer/DEEPSEEK_API_KEY",
            deepseek_key,
            is_secret=True,
            description="Chave da API DeepSeek para formatação de respostas",
        )
        _upsert_variable(
            client,
            token,
            workspace,
            "f/cartographer/CORE_API_URL",
            core_api_url,
            is_secret=False,
            description="URL base da Core API",
        )

        for key, path in SCRIPT_PATHS.items():
            content = _read_script(key)
            _upsert_script(
                client,
                token,
                workspace,
                path,
                summary=key.replace("_", " ").title(),
                content=content,
                envs=[],
            )

        _upsert_flow(client, token, workspace)
        webhook_token = _ensure_webhook_token(client, token, workspace)

    webhook_url = _webhook_url(workspace, webhook_token)
    print("\nWebhook síncrono (POST JSON {session_id, message}):")
    print(webhook_url)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except httpx.HTTPStatusError as exc:
        print(f"Erro HTTP {exc.response.status_code}: {exc.response.text}", file=sys.stderr)
        raise SystemExit(1) from exc
