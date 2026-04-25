from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from agnostic.config import AIConfig, load_app_config
from agnostic.application.ports.ai_orchestrator import AIResponse


class AIQuotaExceeded(RuntimeError):
    pass


class GroqAPIError(RuntimeError):
    pass


@dataclass(slots=True)
class GrokUsageLimiter:
    limit_per_hour: int = 30
    window: timedelta = timedelta(hours=1)
    _calls: list[datetime] = field(default_factory=list)

    def reserve(self, now: datetime | None = None) -> tuple[int, int]:
        current_time = now or datetime.now(UTC)
        self._prune(current_time)

        if len(self._calls) >= self.limit_per_hour:
            raise AIQuotaExceeded(
                f"Grok usage limit exceeded: {self.limit_per_hour} calls per hour."
            )

        self._calls.append(current_time)
        call_number = len(self._calls)
        remaining_calls = self.limit_per_hour - call_number
        return call_number, remaining_calls

    def remaining(self, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        self._prune(current_time)
        return self.limit_per_hour - len(self._calls)

    def _prune(self, now: datetime) -> None:
        cutoff = now - self.window
        self._calls = [call_time for call_time in self._calls if call_time > cutoff]


@dataclass(slots=True)
class SimulatedGrokClient:
    model: str = "grok-simulated"
    provider: str = "grok"
    limiter: GrokUsageLimiter = field(default_factory=GrokUsageLimiter)
    response_factory: Callable[[str, str | None], str] | None = None

    def send(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        now: datetime | None = None,
    ) -> AIResponse:
        call_number, remaining_calls = self.limiter.reserve(now=now)
        content = self._render_response(prompt, system_prompt=system_prompt)

        return AIResponse(
            provider=self.provider,
            model=self.model,
            content=content,
            call_number=call_number,
            remaining_calls=remaining_calls,
            quota_per_hour=self.limiter.limit_per_hour,
            simulated=True,
        )

    def _render_response(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        if self.response_factory is not None:
            return self.response_factory(prompt, system_prompt)

        prompt_excerpt = prompt.strip().replace("\n", " ")
        if len(prompt_excerpt) > 180:
            prompt_excerpt = f"{prompt_excerpt[:177]}..."

        if system_prompt:
            system_excerpt = system_prompt.strip().replace("\n", " ")
            if len(system_excerpt) > 120:
                system_excerpt = f"{system_excerpt[:117]}..."
            return f"[simulated grok] {system_excerpt} :: {prompt_excerpt}"

        return f"[simulated grok] {prompt_excerpt}"


@dataclass(slots=True)
class RealGrokClient:
    api_key: str
    model: str = "llama-3.3-70b-versatile"
    base_url: str = "https://api.groq.com/openai/v1"
    timeout_seconds: float = 30.0
    provider: str = "groq"
    limiter: GrokUsageLimiter = field(default_factory=GrokUsageLimiter)

    def send(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        now: datetime | None = None,
    ) -> AIResponse:
        call_number, remaining_calls = self.limiter.reserve(now=now)
        content = self._request_completion(prompt, system_prompt=system_prompt)

        return AIResponse(
            provider=self.provider,
            model=self.model,
            content=content,
            call_number=call_number,
            remaining_calls=remaining_calls,
            quota_per_hour=self.limiter.limit_per_hour,
            simulated=False,
        )

    def _request_completion(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": self._build_messages(prompt, system_prompt=system_prompt),
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            request = urllib_request.Request(
                f"{self.base_url.rstrip('/')}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:  # pragma: no cover - best-effort diagnostics
                body = ""

            message = f"Groq request failed: HTTP {exc.code} {exc.reason}"
            if body:
                message = f"{message} :: {body[:240]}"
            raise GroqAPIError(message) from exc
        except URLError as exc:
            raise GroqAPIError(f"Groq request failed: {exc.reason}") from exc

        try:
            data = json.loads(raw_body)
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GroqAPIError("Groq response did not include message content.") from exc

        if content is None:
            raise GroqAPIError("Groq response content was empty.")
        return str(content)

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


def build_grok_client_from_env() -> SimulatedGrokClient | RealGrokClient:
    return build_ai_client_from_env()


def build_ai_client_from_env() -> SimulatedGrokClient | RealGrokClient:
    config = load_app_config().ai
    if config.provider in {"", "auto"}:
        return _build_groq_or_simulated_client_from_config(config)
    if config.provider == "simulated":
        return SimulatedGrokClient()
    if config.provider == "groq":
        return _build_real_groq_client_from_config(config)
    raise ValueError(
        "Unsupported AGNOSTIC_AI_PROVIDER value. Use auto, simulated, or groq."
    )


def _build_groq_or_simulated_client_from_config(
    config: AIConfig,
) -> SimulatedGrokClient | RealGrokClient:
    if not config.groq_api_key:
        return SimulatedGrokClient()

    return _build_real_groq_client_from_config(config)


def _build_real_groq_client_from_config(config: AIConfig) -> RealGrokClient:
    if not config.groq_api_key:
        raise ValueError(
            "GROQ_API_KEY must be set when AGNOSTIC_AI_PROVIDER=groq."
        )

    return RealGrokClient(
        api_key=config.groq_api_key,
        model=config.groq_model,
        base_url=config.groq_base_url,
        timeout_seconds=config.groq_timeout_seconds,
    )
