from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from .budget import Budget
from .catalog import Catalog
from .domain import ChangePlan, ChangeRequest, RunStatus, Stage
from .security import validate_request
from .telemetry import Metrics, span


@dataclass(frozen=True)
class QualityPolicy:
    minimum_offline_score: float = 0.90
    minimum_online_score: float = 0.85
    maximum_regression: float = 0.03
    maximum_p95_latency_ms: float = 20_000
    maximum_average_cost_usd: float = 1.00


class Planner:
    """Deterministic control plane. Model output may propose content, never policy or commands."""

    def __init__(self, catalog: Catalog, metrics: Metrics | None = None):
        self.catalog = catalog
        self.metrics = metrics or Metrics()
        self.logger = logging.getLogger("otc_agent.planner")

    def plan(self, request: ChangeRequest, budget: Budget | None = None) -> ChangePlan:
        started = time.monotonic()
        run_id = request.correlation_id or uuid.uuid4().hex
        budget = budget or Budget()
        with span(Stage.INTAKE, trace_id=run_id):
            assessment = validate_request(request)
            mapping = (
                self.catalog.resolve(request.service, request.docs_repository)
                if request.service
                else self.catalog.resolve_documentation(request.docs_repository or "")
            )
        warnings: list[str] = []
        if assessment.injection_signals:
            warnings.append(
                "Input contains prompt-injection indicators; retrieval is quarantined and generated patches require security review."
            )
            self.metrics.increment("security_signals_total", service=mapping.sdk or mapping.docs)
        stages = [stage.value for stage in Stage if stage != Stage.SERVICE_DISCOVERY]
        if mapping.bootstrap:
            stages.insert(stages.index(Stage.SDK_PLAN.value), Stage.SERVICE_DISCOVERY.value)
        sdk_name = mapping.sdk or "<reviewed-new-sdk-abbreviation>"
        provider_name = mapping.provider or "<reviewed-new-provider-abbreviation>"
        outputs = [
            f"gophertelekomcloud/openstack/{sdk_name}/... implementation",
            "SDK request/response, negative-path, pagination, and fixture tests",
            "SDK evidence report and reviewer approval",
            f"terraform-provider/opentelekomcloud/services/{provider_name}/... implementation",
            f"terraform-provider/opentelekomcloud/acceptance/{provider_name}/... tests",
            "provider registration and migration/import behavior where applicable",
            "provider documentation matching existing service conventions",
            "Reno release note",
            "offline and credentialed online evaluation reports",
            "signed provenance manifest containing source revisions and file hashes",
        ]
        assumptions = [
            "Only api-ref content is authoritative for API shape; UMN and generated web pages are supplementary.",
            "APIGW is the primary CRUD/pagination reference and FGS is the event/configuration reference.",
            "No provider patch may be published before the corresponding SDK revision is approved and pinned.",
        ]
        if mapping.bootstrap:
            assumptions.insert(
                0,
                "No reviewed service mapping exists: a maintainer must approve the SDK/provider abbreviations and service boundaries before SDK generation.",
            )
        plan = ChangePlan(
            request=request,
            mapping=mapping,
            status=RunStatus.PLANNED,
            stages=stages,
            required_outputs=outputs,
            assumptions=assumptions,
            warnings=warnings,
            budget=budget.snapshot(),
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        metric_service = mapping.sdk or mapping.docs
        self.metrics.increment("plans_total", service=metric_service, status=plan.status.value)
        self.metrics.increment("plan_latency_ms_sum", elapsed_ms, service=metric_service)
        self.logger.info(
            "plan.created digest=%s",
            assessment.digest,
            extra={"run_id": run_id, "service": metric_service, "stage": Stage.INTAKE},
        )
        return plan


FAILURE_POLICY = {
    "model_timeout": "Retry transient errors with jitter, then route once to the approved fallback model; otherwise stop without a patch.",
    "model_invalid_output": "Reject the structured output, retry once with validation errors, then require human repair.",
    "retrieval_unavailable": "Use only a previously verified, revision-pinned snapshot; if absent or stale, block generation.",
    "retrieval_low_confidence": "Produce a gap report and questions; never invent fields, endpoints, or semantics.",
    "tool_failure": "Retry idempotent read-only tools. Do not retry writes unless an idempotency key and observed state prove safety.",
    "test_failure": "Allow bounded repair attempts using only diagnostics; preserve the failing evidence and block publication.",
    "budget_exceeded": "Stop model calls, save checkpoints and evidence, and require an explicit budget override.",
    "quality_regression": "Block promotion when an absolute threshold or relative baseline gate fails.",
}
