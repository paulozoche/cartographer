from __future__ import annotations

import json
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from agnostic.ai.ports.ai_orchestrator import AIResponse

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_TIMEOUT_SECONDS = 30.0


class DeepSeekAPIError(RuntimeError):
    pass


class DeepSeekClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEEPSEEK_BASE_URL,
        timeout_seconds: float = DEEPSEEK_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._call_count = 0

    def send(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        response_format: dict[str, str] | None = None,
    ) -> AIResponse:
        self._call_count += 1
        payload: dict[str, object] = {
            "model": self._model,
            "messages": self._build_messages(prompt, system_prompt=system_prompt),
        }
        # response_format={"type": "json_object"} exige que o system_prompt contenha "json"/"JSON"
        # (requisito da API DeepSeek). INTERFACE_INTENT_TRANSLATOR_SYSTEM_PROMPT já satisfaz isso
        # (prompts.py, ~linhas 53 e 68). Outros prompts usados com este client sem mencionar "json"
        # causarão erro HTTP 400 se response_format for passado.
        if response_format is not None:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            request = urllib_request.Request(
                f"{self._base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                body = ""
            message = f"DeepSeek request failed: HTTP {exc.code} {exc.reason}"
            if body:
                message = f"{message} :: {body[:240]}"
            raise DeepSeekAPIError(message) from exc
        except URLError as exc:
            raise DeepSeekAPIError(f"DeepSeek request failed: {exc.reason}") from exc

        try:
            data = json.loads(raw_body)
            content = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DeepSeekAPIError("DeepSeek response did not include message content.") from exc

        return AIResponse(
            provider="deepseek",
            model=self._model,
            content=content,
            call_number=self._call_count,
            remaining_calls=0,
            quota_per_hour=0,
            simulated=False,
        )

    @staticmethod
    def _build_messages(
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages
