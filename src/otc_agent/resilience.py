from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, TypeVar


T = TypeVar("T")


class Dependency(StrEnum):
    MODEL = "model"
    RETRIEVAL = "retrieval"
    TOOL = "tool"


class FailureAction(StrEnum):
    RETRY = "retry"
    USE_VERIFIED_SNAPSHOT = "use_verified_snapshot"
    FALLBACK_MODEL = "fallback_model"
    RECONCILE = "reconcile"
    BLOCK = "block"


class DependencyUnavailable(RuntimeError):
    def __init__(self, dependency: Dependency, message: str):
        super().__init__(message)
        self.dependency = dependency


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 2.0


def decide_failure(
    dependency: Dependency,
    failure_class: str,
    *,
    attempt: int,
    idempotent: bool = False,
    verified_snapshot: bool = False,
) -> FailureAction:
    """Return a fail-closed action; callers cannot reinterpret policy with a model."""
    if failure_class in {"authentication", "authorization", "invalid_request", "policy_violation"}:
        return FailureAction.BLOCK
    transient = failure_class in {"timeout", "rate_limited", "server_error", "connection"}
    if dependency == Dependency.RETRIEVAL and transient and attempt >= 3:
        return FailureAction.USE_VERIFIED_SNAPSHOT if verified_snapshot else FailureAction.BLOCK
    if dependency == Dependency.MODEL and transient and attempt >= 3:
        return FailureAction.FALLBACK_MODEL
    if dependency == Dependency.TOOL and failure_class == "unknown_write_result":
        return FailureAction.RECONCILE
    if transient and attempt < 3 and (dependency != Dependency.TOOL or idempotent):
        return FailureAction.RETRY
    return FailureAction.BLOCK


def retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    retryable: Callable[[Exception], bool],
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    last_error: Exception | None = None
    for attempt in range(policy.attempts):
        try:
            return operation()
        except Exception as exc:  # policy owns classification
            last_error = exc
            if not retryable(exc) or attempt + 1 == policy.attempts:
                raise
            cap = min(policy.max_delay_seconds, policy.base_delay_seconds * (2**attempt))
            sleep(random.uniform(0, cap))
    raise AssertionError("unreachable") from last_error
