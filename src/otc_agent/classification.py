from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .domain import ChangeKind, ChangeRequest, ServiceMapping


@dataclass(frozen=True)
class Classification:
    kind: ChangeKind
    confidence: float
    reasons: tuple[str, ...]
    classifier_version: str = "rules-v1"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_ENDPOINT = re.compile(
    r"(?:\b(add|create|introduce|implement|new|support)\b.{0,80}\b(endpoint|api operation|operation|route)s?\b|\b(get|post|put|patch|delete)\s+/[a-z0-9_/{}/.-]+)",
    re.IGNORECASE | re.DOTALL,
)
_ADDITIVE = re.compile(
    r"\b(add|added|adding|introduce|new|expose)\b.{0,80}\b(attribute|attributes|field|fields|property|properties)\b",
    re.IGNORECASE | re.DOTALL,
)
_CONTRACT_CHANGE = re.compile(
    r"\b(fix|correct|change|changed|changing|rename|renamed|remove|removed|type change|parameter|parameters|request|response)\b",
    re.IGNORECASE,
)


def classify_change(request: ChangeRequest, mapping: ServiceMapping) -> Classification:
    """Classify independently of caller input using reviewed product semantics."""
    if mapping.bootstrap:
        return Classification(
            ChangeKind.NEW_SERVICE,
            1.0,
            ("The documentation repository has no reviewed SDK/provider mapping.",),
        )
    description = request.description.strip()
    if _ENDPOINT.search(description):
        return Classification(
            ChangeKind.FEATURE,
            0.92,
            ("The request describes a new endpoint, API operation, route, or HTTP method/path.",),
        )
    if _ADDITIVE.search(description):
        return Classification(
            ChangeKind.UPDATE,
            0.90,
            ("The request adds attributes or fields to existing behavior.",),
        )
    if _CONTRACT_CHANGE.search(description):
        return Classification(
            ChangeKind.FIX,
            0.86,
            ("The request changes existing parameters, request/response shape, or behavior.",),
        )
    return Classification(
        ChangeKind.UPDATE,
        0.35,
        ("No unambiguous endpoint, additive-attribute, or contract-change signal was found.",),
    )
