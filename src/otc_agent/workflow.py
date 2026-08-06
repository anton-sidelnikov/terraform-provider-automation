from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum


class WorkflowError(ValueError):
    pass


class WorkflowStage(StrEnum):
    EXPLORE = "explore"
    SPECIFY = "specify"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    REVIEW = "review"
    PUBLISH = "publish"


WORKFLOW_VERSION = 1
STAGE_ORDER = tuple(WorkflowStage)


@dataclass(frozen=True)
class FrozenArtifact:
    schema_version: int
    workflow_version: int
    stage: WorkflowStage
    previous_sha256: str | None
    payload_json: str
    payload_sha256: str
    artifact_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_version": self.workflow_version,
            "stage": self.stage.value,
            "previous_sha256": self.previous_sha256,
            "payload": json.loads(self.payload_json),
            "payload_sha256": self.payload_sha256,
            "artifact_sha256": self.artifact_sha256,
        }


class ArtifactChain:
    def __init__(self) -> None:
        self._artifacts: list[FrozenArtifact] = []

    @property
    def artifacts(self) -> tuple[FrozenArtifact, ...]:
        return tuple(self._artifacts)

    def append(self, stage: WorkflowStage, payload: dict[str, object]) -> FrozenArtifact:
        expected = STAGE_ORDER[len(self._artifacts)] if len(self._artifacts) < len(STAGE_ORDER) else None
        if stage != expected:
            raise WorkflowError(f"expected workflow stage {expected!s}, got {stage.value}")
        payload_json = _canonical_json(payload)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        previous_sha256 = self._artifacts[-1].artifact_sha256 if self._artifacts else None
        envelope = {
            "schema_version": 1,
            "workflow_version": WORKFLOW_VERSION,
            "stage": stage.value,
            "previous_sha256": previous_sha256,
            "payload_sha256": payload_sha256,
        }
        artifact_sha256 = hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()
        artifact = FrozenArtifact(
            schema_version=1,
            workflow_version=WORKFLOW_VERSION,
            stage=stage,
            previous_sha256=previous_sha256,
            payload_json=payload_json,
            payload_sha256=payload_sha256,
            artifact_sha256=artifact_sha256,
        )
        self._artifacts.append(artifact)
        return artifact

    def finish(self) -> tuple[FrozenArtifact, ...]:
        if len(self._artifacts) != len(STAGE_ORDER):
            missing = ", ".join(stage.value for stage in STAGE_ORDER[len(self._artifacts) :])
            raise WorkflowError(f"workflow is incomplete; missing stages: {missing}")
        verify_artifact_chain(self.artifacts)
        return self.artifacts


def verify_artifact_chain(artifacts: tuple[FrozenArtifact, ...]) -> None:
    if len(artifacts) != len(STAGE_ORDER):
        raise WorkflowError("artifact chain does not contain every workflow stage")
    previous_sha256 = None
    for expected, artifact in zip(STAGE_ORDER, artifacts, strict=True):
        if artifact.stage != expected or artifact.workflow_version != WORKFLOW_VERSION:
            raise WorkflowError("artifact stage or workflow version mismatch")
        if artifact.previous_sha256 != previous_sha256:
            raise WorkflowError("artifact chain link mismatch")
        payload_sha256 = hashlib.sha256(artifact.payload_json.encode("utf-8")).hexdigest()
        if payload_sha256 != artifact.payload_sha256:
            raise WorkflowError("artifact payload digest mismatch")
        envelope = {
            "schema_version": artifact.schema_version,
            "workflow_version": artifact.workflow_version,
            "stage": artifact.stage.value,
            "previous_sha256": artifact.previous_sha256,
            "payload_sha256": artifact.payload_sha256,
        }
        artifact_sha256 = hashlib.sha256(_canonical_json(envelope).encode("utf-8")).hexdigest()
        if artifact_sha256 != artifact.artifact_sha256:
            raise WorkflowError("artifact digest mismatch")
        previous_sha256 = artifact.artifact_sha256


def load_frozen_artifacts(value: object) -> tuple[FrozenArtifact, ...]:
    if not isinstance(value, list):
        raise WorkflowError("workflow artifacts must be an array")
    artifacts: list[FrozenArtifact] = []
    required = {
        "schema_version",
        "workflow_version",
        "stage",
        "previous_sha256",
        "payload",
        "payload_sha256",
        "artifact_sha256",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise WorkflowError("workflow artifact fields do not match schema")
        try:
            stage = WorkflowStage(item["stage"])
        except (TypeError, ValueError) as exc:
            raise WorkflowError("workflow artifact has an invalid stage") from exc
        payload = item["payload"]
        payload_json = _canonical_json(payload)
        artifacts.append(
            FrozenArtifact(
                schema_version=_required_int(item, "schema_version"),
                workflow_version=_required_int(item, "workflow_version"),
                stage=stage,
                previous_sha256=_optional_digest(item["previous_sha256"]),
                payload_json=payload_json,
                payload_sha256=_required_digest(item, "payload_sha256"),
                artifact_sha256=_required_digest(item, "artifact_sha256"),
            )
        )
    result = tuple(artifacts)
    verify_artifact_chain(result)
    return result


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise WorkflowError("workflow artifact payload must be JSON serializable") from exc


def _required_int(value: dict[str, object], field: str) -> int:
    item = value[field]
    if not isinstance(item, int) or isinstance(item, bool):
        raise WorkflowError(f"workflow artifact {field} must be an integer")
    return item


def _required_digest(value: dict[str, object], field: str) -> str:
    item = value[field]
    if not isinstance(item, str) or len(item) != 64 or any(char not in "0123456789abcdef" for char in item):
        raise WorkflowError(f"workflow artifact {field} must be a SHA-256 digest")
    return item


def _optional_digest(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise WorkflowError("workflow artifact previous_sha256 must be a SHA-256 digest")
    return value
