from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from .model import StructuredModel, model_from_environment


class RoutingError(ValueError):
    pass


class ModelTier(StrEnum):
    FAST = "fast"
    STRONG = "strong"


_TIER_STRENGTH = {
    ModelTier.FAST: 1,
    ModelTier.STRONG: 2,
}


@dataclass(frozen=True)
class ModelRoute:
    role: str
    tier: ModelTier
    provider: str
    model: str
    endpoint: str | None = None

    @property
    def identity(self) -> str:
        return f"{self.provider}::{(self.endpoint or 'default').rstrip('/')}::{self.model}"

    def public_identity(self) -> dict[str, object]:
        return {
            "role": self.role,
            "tier": self.tier.value,
            "provider": self.provider,
            "model": self.model,
            "endpoint": self.endpoint,
        }

    def build_model(self) -> StructuredModel:
        return model_from_environment(role=self.role)


@dataclass(frozen=True)
class AuthorRouteIdentity:
    model: str
    tier: ModelTier
    provider: str | None = None
    endpoint: str | None = None

    @property
    def identity(self) -> str | None:
        if self.provider:
            return f"{self.provider}::{(self.endpoint or 'default').rstrip('/')}::{self.model}"
        return None


class ModelRouter:
    def __init__(self, reviewer: ModelRoute):
        if reviewer.role != "reviewer":
            raise RoutingError("reviewer route must use the reviewer role")
        self.reviewer = reviewer

    @classmethod
    def from_environment(cls) -> ModelRouter:
        return cls(_reviewer_route_from_environment())

    def select_reviewer(self, author: AuthorRouteIdentity) -> ModelRoute:
        if _TIER_STRENGTH[self.reviewer.tier] < _TIER_STRENGTH[author.tier]:
            raise RoutingError("reviewer model tier must be equal to or stronger than author tier")
        if self.reviewer.identity == author.identity:
            raise RoutingError("reviewer route must be independent from the author route")
        if self.reviewer.model == author.model and author.identity is None:
            raise RoutingError("reviewer model must differ when author endpoint identity is unavailable")
        return self.reviewer


def parse_model_tier(value: object) -> ModelTier:
    try:
        return ModelTier(str(value))
    except ValueError as exc:
        raise RoutingError(f"unsupported model tier {value!r}") from exc


def _reviewer_route_from_environment() -> ModelRoute:
    provider = os.environ.get("OTC_REVIEW_MODEL_PROVIDER", "copilot").strip().lower()
    model = os.environ.get("OTC_REVIEW_MODEL_NAME", "")
    if provider not in {"copilot", "openai-compatible"}:
        raise RoutingError(f"unsupported reviewer model provider {provider!r}")
    if not model:
        raise RoutingError("independent review requires OTC_REVIEW_MODEL_NAME")
    endpoint = os.environ.get("OTC_COPILOT_RUNTIME_URL")
    if not endpoint:
        cli_path = os.environ.get("OTC_COPILOT_CLI_PATH")
        endpoint = f"stdio:{cli_path}" if cli_path else "stdio:bundled"
    if provider == "openai-compatible":
        endpoint = os.environ.get("OTC_REVIEW_MODEL_BASE_URL") or None
        if not endpoint or not os.environ.get("OTC_REVIEW_MODEL_API_KEY"):
            raise RoutingError(
                "openai-compatible review requires OTC_REVIEW_MODEL_BASE_URL and OTC_REVIEW_MODEL_API_KEY"
            )
    return ModelRoute(
        role="reviewer",
        tier=parse_model_tier(os.environ.get("OTC_REVIEW_MODEL_TIER", "strong")),
        provider=provider,
        model=model,
        endpoint=endpoint,
    )
