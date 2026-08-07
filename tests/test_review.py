import hashlib
import json
import unittest

from otc_agent.budget import Budget
from otc_agent.model import ModelResult
from otc_agent.review import ReviewError, build_review_bundle, run_independent_review
from otc_agent.routing import ModelRoute, ModelTier
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

    def test_independent_review_records_reviewer_route(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        bundle = build_review_bundle(generation_evidence(patch), patch)
        route = ModelRoute(
            role="reviewer",
            tier=ModelTier.STRONG,
            provider="copilot",
            model="review-model",
            endpoint="stdio:review",
        )

        review = run_independent_review(
            bundle,
            model=FakeReviewer(),
            route=route,
            budget=Budget(max_model_calls=1),
        )

        self.assertEqual(review.decision, "approve")
        self.assertEqual(review.route["role"], "reviewer")
        self.assertEqual(review.route["tier"], "strong")


class FakeReviewer:
    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult:
        self.system = system
        self.user = user
        budget.charge(input_tokens=10, output_tokens=5, cost_usd=0)
        return ModelResult(
            value={"decision": "approve", "findings": []},
            model="review-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0,
        )


if __name__ == "__main__":
    unittest.main()
