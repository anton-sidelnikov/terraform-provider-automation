# Operations and reliability

## Service objectives

| Signal | Objective | Gate/action |
|---|---|---|
| API availability | 99.9% monthly for intake/status | Page on fast-burn error-budget alert |
| Plan latency | p95 < 20 s | Block promotion; investigate dependency spans |
| End-to-end proposal latency | p95 < 30 min excluding human wait | Alert on stuck stage/queue age |
| Offline task quality | >= 0.90 and <= 0.03 regression | Block CI |
| Online task quality | >= 0.85 and <= 0.03 regression | Block promotion/rollback model route |
| Cost | mean <= $1 successful task and configured per-run cap | Stop calls at hard cap |
| Unsupported API claims | zero | Block and security-quality incident |

Set tighter per-stage deadlines. Human approval time is measured separately from service latency.

## Telemetry

Use OpenTelemetry SDKs in the deployed API/workers and export OTLP to a collector. Propagate W3C `traceparent` through API, queue metadata, retrieval, model gateway, sandbox tools, evaluation, and publisher. The reference service emits correlated `trace_id`/`span_id` structured events and Prometheus metrics without requiring third-party packages; replace its span exporter with the standard OTLP exporter in production.

Required spans: `run.intake`, `catalog.resolve`, `retrieval.query`, `retrieval.fetch`, `model.call`, `candidate.validate`, `tool.execute`, `evaluation.case`, `artifact.sign`, and `github.publish`. Attributes must not contain prompts, source content, tokens, URLs with credentials, or customer data.

Required metrics:

- request/run/stage totals by bounded status, service, model route, and failure class;
- stage duration and queue age histograms;
- input/output tokens and estimated USD by model/prompt version;
- retrieval result count, freshness, citation coverage, and cache hit ratio;
- tool executions, timeouts, retries, and exit class;
- offline/online scores, regressions, policy violations, and rollback count;
- active runs, approval wait age, dead-letter queue size, and artifact verification failures.

Do not use run IDs, issue IDs, paths, user IDs, exception text, or model names with arbitrary versions as metric labels. They belong in logs/traces.

Logs are JSON, redacted at source, access-controlled, and retained according to the evidence policy. Include timestamp, severity, service version, environment, run/trace/span IDs, stage, event, failure class, duration, and safe counters. Sample successful debug events but never errors or audit transitions.

## Failure matrix

| Failure | Retry | Degraded behavior | Terminal condition |
|---|---|---|---|
| Model 429/5xx/timeout | Up to 3 with full jitter; honor `Retry-After` | One approved fallback route | Save checkpoint and stop |
| Invalid model schema | One repair with validation errors | None | Human repair required |
| Retrieval outage | Bounded transient retry | Verified fresh snapshot only | Block if no snapshot |
| Empty/low-confidence retrieval | No blind retry | Gap report/questions | Block generation |
| GitHub read outage | Bounded retry | Cached commit only if already verified | Block new intake |
| Tool timeout/infra failure | Retry idempotent read-only execution once | New sandbox | Preserve diagnostics and stop |
| Test assertion failure | At most 2 repair proposals | None | Block publication |
| Write result unknown | Query by idempotency key | Reconcile observed state | Human recovery if ambiguous |
| Budget exhausted | Never increase automatically | Save partial evidence | Explicit owner override |
| Quality regression | No retry unless infrastructure-caused | Route back to promoted model | Block/rollback |

Use circuit breakers per dependency and model route, bulkheads for online evaluation versus change generation, queue backpressure, and a dead-letter queue. Never retry authentication/authorization failures, invalid requests, policy failures, or non-idempotent writes with unknown outcome.

## Runbooks

### Model degradation

Compare errors/latency/quality by model and prompt version, disable the candidate route, restore the last promoted route, drain or checkpoint affected runs, run the held-out online suite, and record the rollback in the evidence store.

### Retrieval degradation

Disable fresh generation, verify repository/API status and index commit/hash, rebuild into a new namespace, compare document counts and sentinel queries, then atomically switch. Never mutate the active index in place.

### Tool/sandbox failure

Determine infrastructure versus candidate failure from exit class and trace. Recreate the sandbox only for infrastructure failures. Preserve capped stdout/stderr, worktree hash, image digest, and invoked fixed tool ID.

### Cost anomaly

Trip the budget breaker, stop new model calls, group spend by model/prompt/stage, check retry amplification and context growth, correct routing/chunk limits, and require evaluation before reopening.

### Stuck run

Inspect state version, queue lease, and last span. Reclaim only after lease expiry. Resume from the last verified checkpoint using the same idempotency key and source hashes.

