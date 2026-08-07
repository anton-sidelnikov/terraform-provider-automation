import hashlib
import json
import unittest

from otc_agent.budget import Budget
from otc_agent.model import ModelResult
from otc_agent.review import (
    ReviewError,
    build_review_bundle,
    build_review_history,
    load_review_history,
    run_bounded_repair_iterations,
    run_independent_review,
)
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

    def test_repair_loop_approves_after_two_bounded_iterations(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        bundle = build_review_bundle(generation_evidence(patch), patch)
        route = reviewer_route()
        initial_review = run_independent_review(
            bundle,
            model=SequenceModel([review_result("request_changes", "missing test")]),
            route=route,
            budget=Budget(max_model_calls=1),
        )
        repair_model = SequenceModel(
            [
                repair_result("diff --git a/a.go b/a.go\n+first\n", "missing test"),
                repair_result("diff --git a/a.go b/a.go\n+second\n", "still incomplete"),
            ]
        )
        reviewer_model = SequenceModel(
            [
                review_result("request_changes", "still incomplete"),
                review_result("approve"),
            ]
        )

        outcome = run_bounded_repair_iterations(
            bundle,
            initial_review,
            repair_model=repair_model,
            reviewer_model=reviewer_model,
            reviewer_route=route,
            repair_budget=Budget(max_model_calls=2),
            reviewer_budget=Budget(max_model_calls=2),
            validate_repair=lambda _patch, iteration: [
                {
                    "tool": "go test",
                    "status": "passed",
                    "summary": f"repair {iteration} passed",
                    "sha256": "a" * 64,
                }
            ],
        )

        self.assertEqual(outcome.status, "approved")
        self.assertEqual(len(outcome.rounds), 2)
        self.assertEqual(outcome.rounds[1].proposal.iteration, 2)
        self.assertEqual(repair_model.calls, 2)
        event_types = [item.event_type for item in outcome.history.events]
        self.assertEqual(
            event_types,
            [
                "proposal",
                "validation",
                "review",
                "repair_proposal",
                "repair_validation",
                "repair_review",
                "repair_proposal",
                "repair_validation",
                "repair_review",
            ],
        )
        serialized = json.dumps(outcome.history.as_dict())
        self.assertIn("+first", serialized)
        self.assertIn("+second", serialized)
        self.assertIn("still incomplete", serialized)

    def test_repair_loop_stops_at_hard_limit(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        bundle = build_review_bundle(generation_evidence(patch), patch)
        route = reviewer_route()
        initial_review = run_independent_review(
            bundle,
            model=SequenceModel([review_result("request_changes", "fix it")]),
            route=route,
            budget=Budget(max_model_calls=1),
        )
        outcome = run_bounded_repair_iterations(
            bundle,
            initial_review,
            repair_model=SequenceModel(
                [
                    repair_result("diff --git a/a.go b/a.go\n+one\n", "fix it"),
                    repair_result("diff --git a/a.go b/a.go\n+two\n", "fix it"),
                ]
            ),
            reviewer_model=SequenceModel(
                [
                    review_result("request_changes", "fix it"),
                    review_result("request_changes", "fix it"),
                ]
            ),
            reviewer_route=route,
            repair_budget=Budget(max_model_calls=2),
            reviewer_budget=Budget(max_model_calls=2),
            validate_repair=lambda _patch, _iteration: [
                {"tool": "go test", "status": "passed", "sha256": "b" * 64}
            ],
        )

        self.assertEqual(outcome.status, "repair_limit_reached")
        self.assertEqual(len(outcome.rounds), 2)
        with self.assertRaises(ReviewError):
            run_bounded_repair_iterations(
                bundle,
                initial_review,
                repair_model=SequenceModel([]),
                reviewer_model=SequenceModel([]),
                reviewer_route=route,
                repair_budget=Budget(),
                reviewer_budget=Budget(),
                validate_repair=lambda _patch, _iteration: [],
                max_iterations=3,
            )

    def test_blocked_review_never_invokes_repair_model(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        bundle = build_review_bundle(generation_evidence(patch), patch)
        route = reviewer_route()
        initial_review = run_independent_review(
            bundle,
            model=SequenceModel([review_result("block", "unsafe requirement")]),
            route=route,
            budget=Budget(max_model_calls=1),
        )
        repair_model = SequenceModel([])

        outcome = run_bounded_repair_iterations(
            bundle,
            initial_review,
            repair_model=repair_model,
            reviewer_model=SequenceModel([]),
            reviewer_route=route,
            repair_budget=Budget(),
            reviewer_budget=Budget(),
            validate_repair=lambda _patch, _iteration: [],
        )

        self.assertEqual(outcome.status, "blocked")
        self.assertEqual(repair_model.calls, 0)

    def test_review_history_detects_tampering(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        bundle = build_review_bundle(
            generation_evidence(patch),
            patch,
            [{"tool": "go test", "status": "passed", "sha256": "a" * 64}],
        )
        review = run_independent_review(
            bundle,
            model=SequenceModel([review_result("approve")]),
            route=reviewer_route(),
            budget=Budget(max_model_calls=1),
        )
        value = build_review_history(bundle, review).as_dict()

        loaded = load_review_history(value)
        self.assertEqual(loaded.history_sha256, value["history_sha256"])
        value["events"][0]["payload"]["patch"] += "tampered"
        with self.assertRaises(ReviewError):
            load_review_history(value)


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


class SequenceModel:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self.values = values
        self.calls = 0

    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult:
        value = self.values[self.calls]
        self.calls += 1
        budget.charge(input_tokens=10, output_tokens=5, cost_usd=0)
        return ModelResult(
            value=value,
            model="sequence-model",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0,
        )


def reviewer_route() -> ModelRoute:
    return ModelRoute(
        role="reviewer",
        tier=ModelTier.STRONG,
        provider="copilot",
        model="review-model",
        endpoint="stdio:review",
    )


def review_result(decision: str, finding: str | None = None) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    if finding:
        findings.append({"id": finding, "summary": finding})
    return {"decision": decision, "findings": findings}


def repair_result(patch: str, finding: str) -> dict[str, object]:
    return {
        "patch": patch,
        "summary": f"Address {finding}",
        "addressed_findings": [finding],
    }


if __name__ == "__main__":
    unittest.main()
