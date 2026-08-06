from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .budget import Budget
from .catalog import Catalog
from .domain import ChangeKind, ChangeRequest
from .orchestrator import Planner, QualityPolicy


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

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "mode": self.mode,
            "score": self.score,
            "passed": self.passed,
            "cases": self.cases,
            "p95_latency_ms": self.p95_latency_ms,
            "average_cost_usd": self.average_cost_usd,
            "baseline_score": self.baseline_score,
            "regression": self.regression,
            "failures": list(self.failures),
        }


def run_evaluation(
    dataset: Path,
    catalog: Catalog,
    *,
    mode: str,
    policy: QualityPolicy | None = None,
    endpoint: str | None = None,
    baseline_score: float | None = None,
) -> EvalReport:
    policy = policy or QualityPolicy()
    planner = Planner(catalog)
    results: list[float] = []
    latencies: list[float] = []
    costs: list[float] = []
    failures: list[str] = []
    for line_number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        case = json.loads(line)
        started = time.monotonic()
        try:
            if mode == "online":
                if not endpoint:
                    raise ValueError("online evaluation requires an HTTPS endpoint")
                plan_value = _call_endpoint(endpoint, case["input"])
                mapping = plan_value["mapping"]
                stages = plan_value["stages"]
                classification = plan_value["classification"]
                warnings = plan_value.get("warnings", [])
                costs.append(float(plan_value.get("budget", {}).get("cost_usd", 0)))
            else:
                plan = planner.plan(
                    ChangeRequest(
                        service=case["input"].get("service"),
                        kind=ChangeKind(case["input"]["kind"]),
                        description=case["input"]["description"],
                        docs_repository=case["input"].get("docs_repository"),
                    ),
                    Budget(max_model_calls=0),
                    sdk_root=Path(case["input"]["sdk_root"]) if case["input"].get("sdk_root") else None,
                )
                mapping = plan.as_dict()["mapping"]
                stages = plan.stages
                classification = plan.classification
                warnings = plan.warnings
                costs.append(float(plan.budget.get("cost_usd", 0)))
            checks = [
                mapping["sdk"] == case["expected"]["sdk"],
                mapping["provider"] == case["expected"]["provider"],
                mapping["docs"] == case["expected"]["docs"],
                all(stage in stages for stage in case["expected"].get("stages", [])),
                bool(warnings) == case["expected"].get("security_warning", False),
            ]
            if "classification" in case["expected"]:
                checks.append(classification["kind"] == case["expected"]["classification"])
            score = sum(checks) / len(checks)
            results.append(score)
            if score < 1:
                failures.append(f"line {line_number}: one or more expected fields did not match")
        except Exception as exc:
            if case["expected"].get("reject", False):
                results.append(1.0)
            else:
                results.append(0.0)
                failures.append(f"line {line_number}: {type(exc).__name__}: {exc}")
        latencies.append((time.monotonic() - started) * 1000)
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
    )
    return EvalReport(mode, score, passed, len(results), p95, average_cost, baseline_score, regression, tuple(failures))


def _call_endpoint(endpoint: str, value: dict[str, object]) -> dict[str, object]:
    if not endpoint.startswith("https://") and os.environ.get("OTC_AGENT_ALLOW_HTTP_EVAL") != "1":
        raise ValueError("online evaluation endpoint must use HTTPS")
    headers = {"Content-Type": "application/json", "User-Agent": "otc-agent-evaluator/1"}
    request = Request(
        endpoint.rstrip("/") + "/v1/plans",
        data=json.dumps(value).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # nosec: endpoint is operator-controlled
            if response.status != 200:
                raise RuntimeError(f"evaluation endpoint returned HTTP {response.status}")
            return json.loads(response.read(1_000_000))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("online evaluation endpoint is unavailable") from exc
