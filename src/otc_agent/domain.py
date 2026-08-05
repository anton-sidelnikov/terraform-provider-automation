from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ChangeKind(StrEnum):
    NEW_SERVICE = "new_service"
    FEATURE = "feature"
    FIX = "fix"
    UPDATE = "update"


class Stage(StrEnum):
    INTAKE = "intake"
    RETRIEVE = "retrieve"
    SERVICE_DISCOVERY = "service_discovery"
    SDK_PLAN = "sdk_plan"
    SDK_GENERATE = "sdk_generate"
    SDK_VALIDATE = "sdk_validate"
    SDK_APPROVAL = "sdk_approval"
    PROVIDER_PLAN = "provider_plan"
    PROVIDER_GENERATE = "provider_generate"
    PROVIDER_VALIDATE = "provider_validate"
    ONLINE_EVAL = "online_eval"
    PUBLISH = "publish"


class RunStatus(StrEnum):
    PLANNED = "planned"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class ChangeRequest:
    service: str | None
    kind: ChangeKind | None
    description: str
    issue_url: str | None = None
    docs_repository: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class Evidence:
    repository: str
    revision: str
    path: str
    line_start: int | None = None
    line_end: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class ServiceMapping:
    sdk: str | None
    provider: str | None
    docs: str
    display_name: str
    key: str = ""
    api_ref_path: str = "api-ref"
    aliases: tuple[str, ...] = ()
    reference: bool = False
    bootstrap: bool = False


@dataclass
class ChangePlan:
    request: ChangeRequest
    mapping: ServiceMapping
    status: RunStatus
    stages: list[str]
    required_outputs: list[str]
    evidence: list[Evidence] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    classification: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
