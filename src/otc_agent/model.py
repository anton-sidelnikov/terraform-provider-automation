from __future__ import annotations

import asyncio
import json
import math
import os
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from copilot import CopilotClient, RuntimeConnection
from copilot.client import JsonRpcError, ProcessExitedError
from copilot.session_events import AssistantMessageData

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
    provider: str = "unknown"
    endpoint: str | None = None


class StructuredModel(Protocol):
    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult: ...


class CopilotSDKModel:
    """GitHub Copilot SDK adapter using CLI authentication and tool-free sessions."""

    def __init__(
        self,
        model: str,
        *,
        timeout_seconds: float = 120,
        cli_path: str | None = None,
        runtime_url: str | None = None,
        github_token: str | None = None,
        client_factory: Callable[..., CopilotClient] = CopilotClient,
    ):
        if not model:
            raise ModelError("Copilot model name is required")
        if cli_path and runtime_url:
            raise ModelError("configure either a Copilot CLI path or runtime URL, not both")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.cli_path = cli_path
        self.runtime_url = runtime_url
        self.github_token = github_token
        self.client_factory = client_factory

    @classmethod
    def from_environment(cls, *, prefix: str = "OTC_MODEL") -> "CopilotSDKModel":
        return cls(
            os.environ.get(f"{prefix}_NAME", ""),
            timeout_seconds=float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS") or "120"),
            cli_path=os.environ.get("OTC_COPILOT_CLI_PATH") or None,
            runtime_url=os.environ.get("OTC_COPILOT_RUNTIME_URL") or None,
            github_token=os.environ.get("COPILOT_GITHUB_TOKEN") or None,
        )

    @property
    def endpoint(self) -> str:
        if self.runtime_url:
            return self.runtime_url
        if self.cli_path:
            return f"stdio:{self.cli_path}"
        return "stdio:bundled"

    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._generate_json(system=system, user=user, budget=budget))
        raise ModelError("CopilotSDKModel cannot run synchronously inside an active asyncio event loop")

    async def _generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult:
        connection = None
        if self.runtime_url:
            connection = RuntimeConnection.for_uri(self.runtime_url)
        elif self.cli_path:
            connection = RuntimeConnection.for_stdio(path=self.cli_path)
        client = self.client_factory(
            connection=connection,
            github_token=self.github_token,
            mode="empty",
            use_logged_in_user=None if self.github_token is None else False,
        )
        try:
            async with client:
                async with await client.create_session(
                    model=self.model,
                    tools=[],
                    available_tools=[],
                    system_message={"mode": "replace", "content": system},
                    enable_session_store=False,
                    enable_config_discovery=False,
                    skip_custom_instructions=True,
                    skip_embedding_retrieval=True,
                    enable_skills=False,
                ) as session:
                    response = await session.send_and_wait(user, timeout=self.timeout_seconds)
        except (JsonRpcError, ProcessExitedError, OSError, TimeoutError) as exc:
            raise ModelError("GitHub Copilot SDK request failed") from exc
        if response is None or not isinstance(response.data, AssistantMessageData):
            raise ModelError("GitHub Copilot SDK returned no assistant message")
        content = response.data.content
        value = _parse_json_object(content)
        input_tokens = math.ceil((len(system) + len(user)) / 4)
        output_tokens = response.data.output_tokens or math.ceil(len(content) / 4)
        budget.charge(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=0)
        return ModelResult(
            value=value,
            model=response.data.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=0,
            provider="copilot",
            endpoint=self.endpoint,
        )


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
        return ModelResult(
            value,
            self.model,
            input_tokens,
            output_tokens,
            cost,
            provider="openai-compatible",
            endpoint=self.url.removesuffix("/chat/completions"),
        )


def model_from_environment(*, role: str = "author", tier: str | None = None) -> StructuredModel:
    if role == "reviewer":
        prefix = "OTC_REVIEW_MODEL"
    elif tier and os.environ.get(f"OTC_{tier.upper()}_MODEL_NAME"):
        prefix = f"OTC_{tier.upper()}_MODEL"
    else:
        prefix = "OTC_MODEL"
    provider = os.environ.get(f"{prefix}_PROVIDER", "copilot").strip().lower()
    if provider == "copilot":
        return CopilotSDKModel.from_environment(prefix=prefix)
    if provider == "openai-compatible":
        return OpenAICompatibleModel(
            os.environ.get(f"{prefix}_BASE_URL", ""),
            os.environ.get(f"{prefix}_API_KEY", ""),
            os.environ.get(f"{prefix}_NAME", ""),
            timeout_seconds=float(os.environ.get(f"{prefix}_TIMEOUT_SECONDS") or "120"),
            input_cost_per_million=float(os.environ.get(f"{prefix}_INPUT_USD_PER_MILLION") or "0"),
            output_cost_per_million=float(os.environ.get(f"{prefix}_OUTPUT_USD_PER_MILLION") or "0"),
        )
    raise ModelError(f"unsupported model provider {provider!r}")


def _parse_json_object(content: str) -> dict[str, object]:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1])
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ModelError("model output must be a JSON object")
    return parsed
