import unittest

from otc_agent.budget import Budget
from otc_agent.model import ModelResult
from otc_agent.quality import run_evaluator_optimizer_gate
from otc_agent.routing import ModelRoute, ModelTier


class SequenceModel:
    def __init__(self, values: list[dict[str, object]]):
        self.values = values

    def generate_json(self, **_kwargs: object) -> ModelResult:
        return ModelResult(self.values.pop(0), "model", 10, 10, 0.0)


class QualityTests(unittest.TestCase):
    def test_optimizer_revision_must_improve_and_pass_independent_evaluation(self) -> None:
        initial = ModelResult({"patch": "first"}, "author", 10, 10, 0.0)
        optimizer = SequenceModel([{"patch": "revised"}])
        evaluator = SequenceModel(
            [
                {
                    "decision": "revise",
                    "scores": {
                        "correctness": 0.7,
                        "evidence": 0.8,
                        "tests": 0.7,
                        "scope": 0.9,
                        "maintainability": 0.8,
                    },
                    "findings": [{"id": "missing-test"}],
                },
                {
                    "decision": "pass",
                    "scores": {
                        "correctness": 0.9,
                        "evidence": 0.9,
                        "tests": 0.9,
                        "scope": 0.95,
                        "maintainability": 0.9,
                    },
                    "findings": [],
                },
            ]
        )

        outcome = run_evaluator_optimizer_gate(
            initial=initial,
            frozen_context={"plan": "frozen"},
            validator=lambda candidate: [
                {"tool": "deterministic", "status": "passed", "summary": candidate.value["patch"]}
            ],
            optimizer_model=optimizer,
            evaluator_model=evaluator,
            evaluator_route=ModelRoute(
                "reviewer",
                ModelTier.STRONG,
                "copilot",
                "evaluator",
                "stdio:evaluator",
            ),
            optimizer_budget=Budget(max_model_calls=2),
            evaluator_budget=Budget(max_model_calls=3),
        )

        self.assertEqual(outcome.candidate.value["patch"], "revised")
        self.assertEqual(len(outcome.evaluations), 2)
        self.assertGreaterEqual(outcome.evaluations[-1].score, 0.85)
