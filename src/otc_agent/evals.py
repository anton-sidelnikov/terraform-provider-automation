from __future__ import annotations

import json
import os
import re
import statistics
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .budget import Budget
from .catalog import Catalog
from .domain import ChangeKind, ChangeRequest
from .model import ModelResult
from .orchestrator import Planner, QualityPolicy
from .policy import load_policy_registry
from .pr_iteration import (
    complete_iteration_state,
    FeedbackComment,
    FeedbackReply,
    IncrementalFeedback,
    IterationCommand,
    load_iteration_state,
)
from .review import build_review_bundle, run_bounded_repair_iterations, run_independent_review
from .routing import ModelRoute, ModelTier
from .sdk_layout import analyze_sdk_layout
from .workflow import ArtifactChain, STAGE_ORDER, WorkflowStage


@dataclass(frozen=True)
class EvalReport:
    mode: str
    score: float
    passed: bool
    cases: int
    p95_latency_ms: float
    average_cost_usd: float
    baseline_score: float | None
    regression: float | None
    failures: tuple[str, ...]
    critical_failures: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "mode": self.mode,
            "score": self.score,
            "passed": self.passed,
            "cases": self.cases,
            "p95_latency_ms": self.p95_latency_ms,
            "average_cost_usd": self.average_cost_usd,
            "baseline_score": self.baseline_score,
            "regression": self.regression,
            "failures": list(self.failures),
            "critical_failures": list(self.critical_failures),
        }


def run_evaluation(
    dataset: Path,
    catalog: Catalog,
    *,
    mode: str,
    policy: QualityPolicy | None = None,
    endpoint: str | None = None,
    workflow_endpoint: str | None = None,
    baseline_score: float | None = None,
) -> EvalReport:
    policy = policy or QualityPolicy()
    planner = Planner(catalog)
    results: list[float] = []
    latencies: list[float] = []
    costs: list[float] = []
    failures: list[str] = []
    critical_failures: list[str] = []
    for line_number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        case = json.loads(line)
        started = time.monotonic()
        reported_latency_ms: float | None = None
        try:
            if mode == "online":
                suite = case.get("suite", "planner")
                if suite == "planner":
                    if not endpoint:
                        raise ValueError("online planning evaluation requires an HTTPS endpoint")
                    plan_value = _call_endpoint(endpoint, case["input"])
                    checks = _evaluate_plan_value(case, plan_value)
                    costs.append(float(plan_value.get("budget", {}).get("cost_usd", 0)))
                elif suite == "workflow":
                    if not workflow_endpoint:
                        raise ValueError("online workflow evaluation requires OTC_AGENT_WORKFLOW_EVAL_URL")
                    workflow_value = _call_workflow_endpoint(
                        workflow_endpoint,
                        {"case_id": case.get("id"), "input": case["input"]},
                    )
                    checks, cost, reported_latency_ms = _evaluate_online_workflow(case, workflow_value)
                    costs.append(cost)
                else:
                    raise ValueError(f"unsupported online evaluation suite: {suite}")
            else:
                checks, cost = _run_offline_case(case, planner)
                costs.append(cost)
            score = sum(checks) / len(checks)
            results.append(score)
            if score < 1:
                message = f"line {line_number} ({case.get('id', 'unnamed')}): expected fields did not match"
                failures.append(message)
                if case.get("critical") is True:
                    critical_failures.append(message)
        except Exception as exc:
            if case["expected"].get("reject", False):
                results.append(1.0)
            else:
                results.append(0.0)
                message = f"line {line_number} ({case.get('id', 'unnamed')}): {type(exc).__name__}: {exc}"
                failures.append(message)
                if case.get("critical") is True:
                    critical_failures.append(message)
        measured_latency_ms = (time.monotonic() - started) * 1000
        latencies.append(reported_latency_ms if reported_latency_ms is not None else measured_latency_ms)
    if not results:
        raise ValueError("evaluation dataset contains no cases")
    score = statistics.fmean(results)
    sorted_latency = sorted(latencies)
    p95 = sorted_latency[min(len(sorted_latency) - 1, int(0.95 * len(sorted_latency)))]
    average_cost = statistics.fmean(costs) if costs else 0.0
    threshold = policy.minimum_offline_score if mode == "offline" else policy.minimum_online_score
    regression = (baseline_score - score) if baseline_score is not None else None
    passed = (
        score >= threshold
        and p95 <= policy.maximum_p95_latency_ms
        and average_cost <= policy.maximum_average_cost_usd
        and (regression is None or regression <= policy.maximum_regression)
        and not critical_failures
    )
    return EvalReport(
        mode,
        score,
        passed,
        len(results),
        p95,
        average_cost,
        baseline_score,
        regression,
        tuple(failures),
        tuple(critical_failures),
    )


def _run_offline_case(case: dict[str, object], planner: Planner) -> tuple[list[bool], float]:
    suite = case.get("suite", "planner")
    if suite == "planner":
        return _evaluate_planner(case, planner)
    if suite == "sdk_layout":
        return _evaluate_sdk_layout(case), 0.0
    if suite == "policy_compliance":
        return _evaluate_policy_compliance(case), 0.0
    if suite == "review_repair":
        return _evaluate_review_repair(case), 0.0
    if suite == "pr_idempotency":
        return _evaluate_pr_idempotency(case), 0.0
    raise ValueError(f"unsupported offline evaluation suite: {suite}")


def _evaluate_planner(case: dict[str, object], planner: Planner) -> tuple[list[bool], float]:
    input_value = _case_object(case, "input")
    plan = planner.plan(
        ChangeRequest(
            service=input_value.get("service"),
            kind=ChangeKind(input_value["kind"]),
            description=input_value["description"],
            docs_repository=input_value.get("docs_repository"),
        ),
        Budget(max_model_calls=0),
        sdk_root=Path(input_value["sdk_root"]) if input_value.get("sdk_root") else None,
    )
    checks = _evaluate_plan_value(case, plan.as_dict())
    return checks, float(plan.budget.get("cost_usd", 0))


def _evaluate_plan_value(case: dict[str, object], plan_value: dict[str, object]) -> list[bool]:
    expected = _case_object(case, "expected")
    mapping = plan_value["mapping"]
    if not isinstance(mapping, dict):
        raise ValueError("evaluation plan mapping must be an object")
    stages = plan_value["stages"]
    classification = plan_value["classification"]
    if not isinstance(stages, (list, tuple)) or not isinstance(classification, dict):
        raise ValueError("evaluation plan stages and classification have invalid schemas")
    warnings = plan_value.get("warnings", [])
    checks = [
        mapping["sdk"] == expected["sdk"],
        mapping["provider"] == expected["provider"],
        mapping["docs"] == expected["docs"],
        all(stage in stages for stage in expected.get("stages", [])),
        bool(warnings) == expected.get("security_warning", False),
    ]
    if "classification" in expected:
        checks.append(classification["kind"] == expected["classification"])
    return checks


def _evaluate_sdk_layout(case: dict[str, object]) -> list[bool]:
    input_value = _case_object(case, "input")
    expected = _case_object(case, "expected")
    analysis = analyze_sdk_layout(Path(input_value["sdk_root"]), str(input_value["service"]))
    return [
        analysis.kind.value == expected["kind"],
        analysis.requires_refactoring is expected["requires_refactoring"],
        sorted(operation.name for operation in analysis.legacy_operations)
        == sorted(expected.get("legacy_operations", [])),
    ]


def _evaluate_policy_compliance(case: dict[str, object]) -> list[bool]:
    input_value = _case_object(case, "input")
    expected = _case_object(case, "expected")
    policies = load_policy_registry(Path(input_value["policy_root"]))
    actual = {policy.policy_id: policy.version for policy in policies}
    return [actual == expected["policies"]]


def _evaluate_review_repair(case: dict[str, object]) -> list[bool]:
    expected = _case_object(case, "expected")
    patch = "diff --git a/openstack/apigw/v2/widgets/Get.go b/openstack/apigw/v2/widgets/Get.go\n"
    evidence = _evaluation_evidence(patch)
    bundle = build_review_bundle(evidence, patch)
    route = ModelRoute("reviewer", ModelTier.STRONG, "offline", "scripted-reviewer", "offline:evaluator")
    initial_review = run_independent_review(
        bundle,
        model=_ScriptedModel([{"decision": "request_changes", "findings": [{"id": "missing-test"}]}]),
        route=route,
        budget=Budget(max_model_calls=1),
    )
    outcome = run_bounded_repair_iterations(
        bundle,
        initial_review,
        repair_model=_ScriptedModel(
            [
                {
                    "patch": patch + "+func TestGet(t *testing.T) {}\n",
                    "summary": "Add the missing test",
                    "addressed_findings": ["missing-test"],
                }
            ]
        ),
        reviewer_model=_ScriptedModel([{"decision": "approve", "findings": []}]),
        reviewer_route=route,
        repair_budget=Budget(max_model_calls=1),
        reviewer_budget=Budget(max_model_calls=1),
        validate_repair=lambda candidate, iteration: [
            {
                "tool": "offline-validator",
                "status": "passed",
                "summary": f"repair {iteration}",
                "sha256": sha256(candidate.encode("utf-8")).hexdigest(),
            }
        ],
    )
    return [
        outcome.status == expected["status"],
        len(outcome.rounds) == expected["rounds"],
        [event.event_type for event in outcome.history.events] == expected["events"],
    ]


def _evaluate_pr_idempotency(case: dict[str, object]) -> list[bool]:
    expected = _case_object(case, "expected")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "iteration-state.json"
        state = load_iteration_state(path, run_id="eval-run", repository="example/repo", pull_request=42)
        command = IterationCommand(
            99,
            "/agent iterate",
            "maintainer",
            "MEMBER",
            "https://github.com/example/repo/pull/42#issuecomment-99",
        )
        feedback = IncrementalFeedback(
            (
                FeedbackComment(
                    100,
                    "issue",
                    "Please add the missing test",
                    "maintainer",
                    "MEMBER",
                    "https://github.com/example/repo/pull/42#issuecomment-100",
                ),
            ),
            (),
            100,
            0,
        )
        first = complete_iteration_state(
            path,
            state=state,
            command=command,
            feedback=feedback,
            repair_commit=None,
            replies=(FeedbackReply(100, "issue", 101, "https://github.com/example/repo/pull/42#issuecomment-101"),),
            status="completed",
        )
        first_bytes = path.read_bytes()
        second = complete_iteration_state(
            path,
            state=first,
            command=command,
            feedback=feedback,
            repair_commit=None,
            replies=(),
            status="unexpected-replay",
        )
        return [
            first == second,
            path.read_bytes() == first_bytes,
            len(second.completed_commands) == expected["completed_commands"],
            list(second.processed_issue_comment_ids) == expected["processed_issue_comment_ids"],
        ]


def _evaluate_online_workflow(
    case: dict[str, object],
    value: dict[str, object],
) -> tuple[list[bool], float, float]:
    expected = _case_object(case, "expected")
    validation = value.get("validation")
    iteration = value.get("iteration")
    metrics = value.get("metrics")
    if not all(isinstance(item, dict) for item in (validation, iteration, metrics)):
        raise ValueError("workflow evaluation response is missing validation, iteration, or metrics")
    compilation = validation.get("compilation")
    repository_tests = validation.get("repository_tests")
    if not isinstance(compilation, dict) or not isinstance(repository_tests, dict):
        raise ValueError("workflow validation response has an invalid schema")
    compilation_digest = compilation.get("sha256")
    test_digest = repository_tests.get("sha256")
    latency_ms = _non_negative_number(metrics.get("latency_ms"), "workflow latency")
    cost_usd = _non_negative_number(metrics.get("cost_usd"), "workflow cost")
    minimum_replies = expected.get("minimum_replies", 1)
    if not isinstance(minimum_replies, int) or isinstance(minimum_replies, bool) or minimum_replies < 0:
        raise ValueError("minimum_replies must be a non-negative integer")
    replied_comments = iteration.get("replied_comments")
    checks = [
        value.get("case_id") == case.get("id"),
        value.get("status") == "passed",
        compilation.get("status") == "passed",
        isinstance(compilation.get("command"), str) and bool(compilation["command"].strip()),
        isinstance(compilation_digest, str) and re.fullmatch(r"[0-9a-f]{64}", compilation_digest) is not None,
        repository_tests.get("status") == "passed",
        repository_tests.get("native") is True,
        isinstance(repository_tests.get("command"), str) and bool(repository_tests["command"].strip()),
        isinstance(test_digest, str) and re.fullmatch(r"[0-9a-f]{64}", test_digest) is not None,
        iteration.get("status") == "completed",
        iteration.get("command") == "/agent iterate",
        iteration.get("same_pull_request") is True,
        iteration.get("append_only") is True,
        isinstance(replied_comments, int)
        and not isinstance(replied_comments, bool)
        and replied_comments >= minimum_replies,
    ]
    return checks, cost_usd, latency_ms


def _evaluation_evidence(patch: str) -> dict[str, object]:
    patch_sha256 = sha256(patch.encode("utf-8")).hexdigest()
    chain = ArtifactChain()
    for stage in STAGE_ORDER:
        payload: dict[str, object] = {"stage": stage.value}
        if stage == WorkflowStage.VERIFY:
            payload["patch_sha256"] = patch_sha256
        chain.append(stage, payload)
    return {
        "patch_sha256": patch_sha256,
        "workflow_artifacts": [artifact.as_dict() for artifact in chain.finish()],
    }


class _ScriptedModel:
    def __init__(self, values: list[dict[str, object]]) -> None:
        self._values = iter(values)

    def generate_json(self, *, system: str, user: str, budget: Budget) -> ModelResult:
        del system, user
        budget.charge(input_tokens=1, output_tokens=1, cost_usd=0.0)
        return ModelResult(next(self._values), "offline-scripted-model", 1, 1, 0.0)


def _case_object(case: dict[str, object], field: str) -> dict[str, object]:
    value = case.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"evaluation case {field} must be an object")
    return value


def _non_negative_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return float(value)


def _call_endpoint(endpoint: str, value: dict[str, object]) -> dict[str, object]:
    return _post_json(endpoint, "/v1/plans", value)


def _call_workflow_endpoint(endpoint: str, value: dict[str, object]) -> dict[str, object]:
    return _post_json(endpoint, "/v1/evaluations", value)


def _post_json(endpoint: str, path: str, value: dict[str, object]) -> dict[str, object]:
    if not endpoint.startswith("https://") and os.environ.get("OTC_AGENT_ALLOW_HTTP_EVAL") != "1":
        raise ValueError("online evaluation endpoint must use HTTPS")
    headers = {"Content-Type": "application/json", "User-Agent": "otc-agent-evaluator/1"}
    request = Request(
        endpoint.rstrip("/") + path,
        data=json.dumps(value).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec: endpoint is operator-controlled
            if response.status != 200:
                raise RuntimeError(f"evaluation endpoint returned HTTP {response.status}")
            result = json.loads(response.read(1_000_000))
            if not isinstance(result, dict):
                raise RuntimeError("evaluation endpoint returned a non-object response")
            return result
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("online evaluation endpoint is unavailable") from exc
