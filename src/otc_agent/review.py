from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .workflow import WorkflowStage, load_frozen_artifacts


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewBundle:
    schema_version: int
    workflow_version: int
    source_chain_sha256: str
    review_input_sha256: str
    artifacts: tuple[dict[str, object], ...]
    patch: str
    patch_sha256: str
    diagnostics: tuple[dict[str, object], ...]
    author_context_included: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workflow_version": self.workflow_version,
            "source_chain_sha256": self.source_chain_sha256,
            "review_input_sha256": self.review_input_sha256,
            "artifacts": list(self.artifacts),
            "patch": self.patch,
            "patch_sha256": self.patch_sha256,
            "diagnostics": list(self.diagnostics),
            "author_context_included": self.author_context_included,
            "allowed_context": [
                "frozen_workflow_artifacts",
                "verified_patch",
                "deterministic_diagnostics",
            ],
        }


def build_review_bundle(
    evidence: dict[str, object],
    patch: str,
    diagnostics: list[object] | None = None,
) -> ReviewBundle:
    artifacts = load_frozen_artifacts(evidence.get("workflow_artifacts"))
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    if evidence.get("patch_sha256") != patch_sha256:
        raise ReviewError("review patch does not match generation evidence")
    verify_artifact = next(artifact for artifact in artifacts if artifact.stage == WorkflowStage.VERIFY)
    verify_payload = json.loads(verify_artifact.payload_json)
    if verify_payload.get("patch_sha256") != patch_sha256:
        raise ReviewError("review patch does not match the frozen VERIFY artifact")
    frozen_inputs = tuple(
        artifact.as_dict()
        for artifact in artifacts
        if artifact.stage
        in {
            WorkflowStage.EXPLORE,
            WorkflowStage.SPECIFY,
            WorkflowStage.PLAN,
            WorkflowStage.IMPLEMENT,
            WorkflowStage.VERIFY,
        }
    )
    safe_diagnostics = _validate_diagnostics(diagnostics or [])
    review_input = {
        "artifact_sha256": [item["artifact_sha256"] for item in frozen_inputs],
        "patch_sha256": patch_sha256,
        "diagnostics": list(safe_diagnostics),
    }
    review_input_sha256 = hashlib.sha256(
        json.dumps(review_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ReviewBundle(
        schema_version=1,
        workflow_version=artifacts[0].workflow_version,
        source_chain_sha256=artifacts[-1].artifact_sha256,
        review_input_sha256=review_input_sha256,
        artifacts=frozen_inputs,
        patch=patch,
        patch_sha256=patch_sha256,
        diagnostics=safe_diagnostics,
    )


def _validate_diagnostics(value: list[object]) -> tuple[dict[str, object], ...]:
    diagnostics: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReviewError("review diagnostics must be objects")
        allowed = {"tool", "status", "summary", "sha256"}
        if set(item) - allowed:
            raise ReviewError("review diagnostics contain unsupported fields")
        diagnostics.append(dict(item))
    return tuple(diagnostics)

