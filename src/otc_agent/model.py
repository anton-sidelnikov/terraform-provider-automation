from __future__ import annotations

import json
import os
import math
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .budget import Budget
from .resilience import RetryPolicy, retry


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResult:
    value: dict[str, object]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class StructuredModel(Protocol):
    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult: ...


class OpenAICompatibleModel:
    """Small OpenAI-compatible adapter; endpoint and model are deployment configuration."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 120,
        input_cost_per_million: float = 0,
        output_cost_per_million: float = 0,
    ):
        if not base_url.startswith("https://") and os.environ.get("OTC_MODEL_ALLOW_HTTP") != "1":
            raise ModelError("model base URL must use HTTPS")
        if not api_key or not model:
            raise ModelError("model API key and model name are required")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million

    @classmethod
    def from_environment(cls) -> "OpenAICompatibleModel":
        return cls(
            os.environ.get("OTC_MODEL_BASE_URL", ""),
            os.environ.get("OTC_MODEL_API_KEY", ""),
            os.environ.get("OTC_MODEL_NAME", ""),
            timeout_seconds=float(os.environ.get("OTC_MODEL_TIMEOUT_SECONDS") or "120"),
            input_cost_per_million=float(os.environ.get("OTC_MODEL_INPUT_USD_PER_MILLION") or "0"),
            output_cost_per_million=float(os.environ.get("OTC_MODEL_OUTPUT_USD_PER_MILLION") or "0"),
        )

    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult:
        body = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 32_000,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        def call() -> dict[str, object]:
            request = Request(
                self.url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "otc-provider-agent/1",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec: operator-configured gateway
                    return json.loads(response.read(10_000_000))
            except HTTPError as exc:
                if exc.code in {408, 409, 429, 500, 502, 503, 504}:
                    raise TimeoutError(f"transient model HTTP {exc.code}") from exc
                raise ModelError(f"model returned HTTP {exc.code}") from exc
            except (URLError, TimeoutError) as exc:
                raise TimeoutError("model endpoint unavailable") from exc

        raw = retry(
            call,
            policy=RetryPolicy(attempts=3, base_delay_seconds=1, max_delay_seconds=8),
            retryable=lambda exc: isinstance(exc, TimeoutError),
        )
        try:
            content = raw["choices"][0]["message"]["content"]  # type: ignore[index]
            value = _parse_json_object(str(content))
            usage = raw.get("usage", {})  # type: ignore[union-attr]
            input_tokens = int(usage.get("prompt_tokens", 0))  # type: ignore[union-attr]
            output_tokens = int(usage.get("completion_tokens", 0))  # type: ignore[union-attr]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelError("model response does not match the chat-completions contract") from exc
        if input_tokens <= 0:
            input_tokens = math.ceil((len(system) + len(user)) / 4)
        if output_tokens <= 0:
            output_tokens = math.ceil(len(str(content)) / 4)
        cost = (
            input_tokens * self.input_cost_per_million / 1_000_000
            + output_tokens * self.output_cost_per_million / 1_000_000
        )
        budget.charge(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)
        return ModelResult(value, self.model, input_tokens, output_tokens, cost)


def _parse_json_object(content: str) -> dict[str, object]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1])
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ModelError("model output must be a JSON object")
    return parsed
