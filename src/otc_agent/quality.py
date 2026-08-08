from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from typing import Callable

from .budget import Budget
from .model import ModelResult, StructuredModel
from .routing import ModelRoute


class QualityGateError(ValueError):
    pass


@dataclass(frozen=True)
class QualityEvaluation:
    iteration: int
    decision: str
    scores: dict[str, float]
    findings: tuple[dict[str, object], ...]
    model: str
    route: dict[str, object]

    @property
    def score(self) -> float:
        return statistics.fmean(self.scores.values())

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["score"] = self.score
        return value


@dataclass(frozen=True)
class QualityOutcome:
    candidate: ModelResult
    evaluations: tuple[QualityEvaluation, ...]
    deterministic_diagnostics: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "status": "passed",
            "score": self.evaluations[-1].score,
            "evaluations": [evaluation.as_dict() for evaluation in self.evaluations],
            "deterministic_diagnostics": list(self.deterministic_diagnostics),
        }


CandidateValidator = Callable[[ModelResult], list[dict[str, object]]]
_DIMENSIONS = ("correctness", "evidence", "tests", "scope", "maintainability")


def run_evaluator_optimizer_gate(
    *,
    initial: ModelResult,
    frozen_context: dict[str, object],
    validator: CandidateValidator,
    optimizer_model: StructuredModel,
    evaluator_model: StructuredModel,
    evaluator_route: ModelRoute,
    optimizer_budget: Budget,
    evaluator_budget: Budget,
    maximum_revisions: int = 2,
    minimum_score: float = 0.85,
    minimum_dimension_score: float = 0.75,
) -> QualityOutcome:
    if maximum_revisions < 0 or maximum_revisions > 2:
        raise QualityGateError("quality optimizer revisions must be between zero and two")
    candidate = initial
    evaluations: list[QualityEvaluation] = []
    diagnostics: list[dict[str, object]] = []
    for iteration in range(maximum_revisions + 1):
        current_diagnostics = validator(candidate)
        if not current_diagnostics or any(item.get("status") != "passed" for item in current_diagnostics):
            raise QualityGateError("candidate failed a non-compensating deterministic quality check")
        diagnostics.extend(current_diagnostics)
        evaluation = _evaluate(
            candidate,
            frozen_context,
            current_diagnostics,
            iteration=iteration,
            model=evaluator_model,
            route=evaluator_route,
            budget=evaluator_budget,
        )
        evaluations.append(evaluation)
        if len(evaluations) > 1 and evaluation.score <= evaluations[-2].score:
            raise QualityGateError("optimizer revision did not improve the independent quality score")
        passed = (
            evaluation.decision == "pass"
            and evaluation.score >= minimum_score
            and min(evaluation.scores.values()) >= minimum_dimension_score
        )
        if passed:
            return QualityOutcome(candidate, tuple(evaluations), tuple(diagnostics))
        if evaluation.decision == "block":
            raise QualityGateError("independent evaluator blocked the candidate")
        if iteration >= maximum_revisions:
            raise QualityGateError("candidate did not pass the bounded evaluator-optimizer gate")
        candidate = _optimize(
            candidate,
            frozen_context,
            evaluation,
            model=optimizer_model,
            budget=optimizer_budget,
            iteration=iteration + 1,
        )
    raise QualityGateError("quality gate ended without an accepted candidate")


def _evaluate(
    candidate: ModelResult,
    frozen_context: dict[str, object],
    diagnostics: list[dict[str, object]],
    *,
    iteration: int,
    model: StructuredModel,
    route: ModelRoute,
    budget: Budget,
) -> QualityEvaluation:
    result = model.generate_json(
        system=(
            "Independently evaluate the candidate against frozen context and deterministic diagnostics. "
            "Return exactly decision (pass, revise, block), scores for correctness, evidence, tests, scope, "
            "and maintainability from 0 to 1, and findings as objects. Security, path, citation, or test "
            "violations must be block and cannot be offset by other scores."
        ),
        user=json.dumps(
            {
                "frozen_context": frozen_context,
                "candidate": candidate.value,
                "diagnostics": diagnostics,
            },
            sort_keys=True,
        ),
        budget=budget,
    )
    value = result.value
    if set(value) != {"decision", "scores", "findings"}:
        raise QualityGateError("quality evaluator returned an invalid schema")
    decision = value["decision"]
    scores = value["scores"]
    findings = value["findings"]
    if decision not in {"pass", "revise", "block"}:
        raise QualityGateError("quality evaluator returned an invalid decision")
    if not isinstance(scores, dict) or set(scores) != set(_DIMENSIONS):
        raise QualityGateError("quality evaluator returned invalid score dimensions")
    normalized_scores: dict[str, float] = {}
    for dimension in _DIMENSIONS:
        score = scores[dimension]
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 1:
            raise QualityGateError("quality evaluator score must be between zero and one")
        normalized_scores[dimension] = float(score)
    if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
        raise QualityGateError("quality evaluator findings must be objects")
    return QualityEvaluation(
        iteration,
        decision,
        normalized_scores,
        tuple(findings),
        result.model,
        route.public_identity(),
    )


def _optimize(
    candidate: ModelResult,
    frozen_context: dict[str, object],
    evaluation: QualityEvaluation,
    *,
    model: StructuredModel,
    budget: Budget,
    iteration: int,
) -> ModelResult:
    return model.generate_json(
        system=(
            "Revise the candidate only to address the independent evaluator findings. Preserve the original "
            "JSON output schema, frozen scope, citations, and unrelated behavior. Return a complete replacement "
            "candidate, not commentary."
        ),
        user=json.dumps(
            {
                "iteration": iteration,
                "frozen_context": frozen_context,
                "candidate": candidate.value,
                "evaluation": evaluation.as_dict(),
            },
            sort_keys=True,
        ),
        budget=budget,
    )
