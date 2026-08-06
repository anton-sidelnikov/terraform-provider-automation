import hashlib
import json
import unittest

from otc_agent.review import ReviewError, build_review_bundle
from otc_agent.workflow import STAGE_ORDER, ArtifactChain, WorkflowStage


def generation_evidence(patch: str) -> dict[str, object]:
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    chain = ArtifactChain()
    for stage in STAGE_ORDER:
        payload: dict[str, object] = {"stage": stage.value}
        if stage == WorkflowStage.VERIFY:
            payload["patch_sha256"] = patch_sha256
        chain.append(stage, payload)
    artifacts = chain.finish()
    return {
        "patch_sha256": patch_sha256,
        "workflow_artifacts": [artifact.as_dict() for artifact in artifacts],
        "conversation_history": "must not cross the review boundary",
        "raw_prompt": "must not cross the review boundary",
    }


class ReviewTests(unittest.TestCase):
    def test_bundle_contains_only_frozen_inputs_patch_and_diagnostics(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        bundle = build_review_bundle(
            generation_evidence(patch),
            patch,
            [{"tool": "go test", "status": "passed", "sha256": "a" * 64}],
        )
        value = bundle.as_dict()

        self.assertFalse(value["author_context_included"])
        self.assertEqual(
            [artifact["stage"] for artifact in value["artifacts"]],
            ["explore", "specify", "plan", "implement", "verify"],
        )
        serialized = json.dumps(value)
        self.assertNotIn("conversation_history", serialized)
        self.assertNotIn("raw_prompt", serialized)

    def test_rejects_patch_not_bound_to_verify_artifact(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"

        with self.assertRaises(ReviewError):
            build_review_bundle(generation_evidence(patch), patch + "tampered")


if __name__ == "__main__":
    unittest.main()

