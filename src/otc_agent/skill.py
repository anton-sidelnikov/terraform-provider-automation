from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .policy import PolicyContract


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyReference:
    policy_id: str
    minimum_version: int


@dataclass(frozen=True)
class SkillBudget:
    max_model_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_cost_usd: float
    max_wall_seconds: float


@dataclass(frozen=True)
class SkillRetry:
    max_attempts: int
    retryable: tuple[str, ...]


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    version: int
    description: str
    stage: str
    model_tier: str
    policies: tuple[PolicyReference, ...]
    input_schema: dict[str, object]
    output_schema: dict[str, object]
    tools: tuple[str, ...]
    budget: SkillBudget
    retry: SkillRetry

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_ROOT_FIELDS = {"schema_version", "skills"}
_SKILL_FIELDS = {
    "id",
    "version",
    "description",
    "stage",
    "model_tier",
    "policies",
    "input_schema",
    "output_schema",
    "tools",
    "budget",
    "retry",
}
_BUDGET_FIELDS = {
    "max_model_calls",
    "max_input_tokens",
    "max_output_tokens",
    "max_cost_usd",
    "max_wall_seconds",
}
_RETRY_FIELDS = {"max_attempts", "retryable"}


def load_skill_registry(path: Path, policies: tuple[PolicyContract, ...]) -> tuple[SkillManifest, ...]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != _ROOT_FIELDS or value["schema_version"] != 1:
        raise SkillError("skill registry requires schema_version 1 and a skills array")
    raw_skills = value["skills"]
    if not isinstance(raw_skills, list) or not raw_skills:
        raise SkillError("skill registry is empty")
    policy_versions = {policy.policy_id: policy.version for policy in policies}
    manifests = tuple(_parse_skill(item, policy_versions) for item in raw_skills)
    identifiers = [manifest.skill_id for manifest in manifests]
    if len(identifiers) != len(set(identifiers)):
        raise SkillError("skill IDs must be unique")
    return manifests


def _parse_skill(value: object, policy_versions: dict[str, int]) -> SkillManifest:
    if not isinstance(value, dict) or set(value) != _SKILL_FIELDS:
        raise SkillError("skill manifest fields do not match schema")
    skill_id = value["id"]
    if not isinstance(skill_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", skill_id):
        raise SkillError("skill ID must be a lower-case slug")
    version = value["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise SkillError(f"{skill_id}: version must be a positive integer")
    for field in ("description", "stage"):
        if not isinstance(value[field], str) or not value[field]:
            raise SkillError(f"{skill_id}: {field} must be a non-empty string")
    model_tier = value["model_tier"]
    if model_tier not in {"none", "fast", "strong"}:
        raise SkillError(f"{skill_id}: invalid model tier")
    policy_refs = _parse_policies(skill_id, value["policies"], policy_versions)
    input_schema = _parse_schema(skill_id, "input", value["input_schema"])
    output_schema = _parse_schema(skill_id, "output", value["output_schema"])
    tools = value["tools"]
    if not isinstance(tools, list) or not tools or not all(isinstance(tool, str) and tool for tool in tools):
        raise SkillError(f"{skill_id}: tools must be a non-empty string array")
    budget = _parse_budget(skill_id, value["budget"])
    retry = _parse_retry(skill_id, value["retry"])
    if model_tier == "none" and budget.max_model_calls != 0:
        raise SkillError(f"{skill_id}: model-free skills must have zero model calls")
    return SkillManifest(
        skill_id,
        version,
        value["description"],
        value["stage"],
        model_tier,
        policy_refs,
        input_schema,
        output_schema,
        tuple(tools),
        budget,
        retry,
    )


def _parse_policies(
    skill_id: str,
    value: object,
    policy_versions: dict[str, int],
) -> tuple[PolicyReference, ...]:
    if not isinstance(value, list) or not value:
        raise SkillError(f"{skill_id}: policies must be a non-empty array")
    references: list[PolicyReference] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "minimum_version"}:
            raise SkillError(f"{skill_id}: invalid policy reference")
        policy_id = item["id"]
        minimum = item["minimum_version"]
        if policy_id not in policy_versions:
            raise SkillError(f"{skill_id}: unknown policy {policy_id!r}")
        if not isinstance(minimum, int) or minimum < 1 or policy_versions[policy_id] < minimum:
            raise SkillError(f"{skill_id}: policy {policy_id!r} does not meet its minimum version")
        references.append(PolicyReference(policy_id, minimum))
    return tuple(references)


def _parse_schema(skill_id: str, name: str, value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("type") != "object":
        raise SkillError(f"{skill_id}: {name} schema must describe an object")
    if not isinstance(value.get("properties"), dict) or not isinstance(value.get("required"), list):
        raise SkillError(f"{skill_id}: {name} schema requires properties and required")
    properties = value["properties"]
    if not all(isinstance(field, str) and isinstance(schema, dict) for field, schema in properties.items()):
        raise SkillError(f"{skill_id}: invalid {name} schema properties")
    if not all(isinstance(field, str) and field in properties for field in value["required"]):
        raise SkillError(f"{skill_id}: invalid {name} required fields")
    return value


def _parse_budget(skill_id: str, value: object) -> SkillBudget:
    if not isinstance(value, dict) or set(value) != _BUDGET_FIELDS:
        raise SkillError(f"{skill_id}: invalid budget")
    numeric = [value[field] for field in _BUDGET_FIELDS]
    if any(not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0 for item in numeric):
        raise SkillError(f"{skill_id}: budget values must be non-negative numbers")
    return SkillBudget(**value)


def _parse_retry(skill_id: str, value: object) -> SkillRetry:
    if not isinstance(value, dict) or set(value) != _RETRY_FIELDS:
        raise SkillError(f"{skill_id}: invalid retry policy")
    attempts = value["max_attempts"]
    retryable = value["retryable"]
    if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 3:
        raise SkillError(f"{skill_id}: retry attempts must be between 1 and 3")
    if not isinstance(retryable, list) or not all(isinstance(item, str) for item in retryable):
        raise SkillError(f"{skill_id}: retryable must be a string array")
    return SkillRetry(attempts, tuple(retryable))

