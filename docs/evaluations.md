# Evaluation strategy

Evaluation is a release gate, not a dashboard-only metric. Datasets and scoring code are versioned with the service; baseline reports are bound to model, prompt, catalog, and source revisions.

## Offline evaluation

Runs on every pull request with no model, network, cloud credentials, or repository-write token. It tests:

- exact mapping across SDK abbreviation, provider abbreviation, and documentation slug;
- rejection of unknown/ambiguous services and conflicting overrides;
- prompt-injection and oversized/control-character handling;
- stage ordering, especially the SDK approval barrier;
- budgets, retry classification, redaction, URL/path restrictions, and failure-state transitions;
- classification semantics, patch path confinement, citation provenance, documentation sections, and release-note shape;
- replayed model/retrieval/tool timeouts and malformed outputs.

The current gate is `score >= 0.90`; security and SDK-ordering cases are critical and should become non-compensating checks as the dataset grows.

## Online evaluation

The scheduled/manual workflow calls a deployed `/v1/plans` endpoint using a protected environment. Use a dedicated test tenant and read-only or disposable OTC resources. Cases must be idempotent and tagged with run ID for cleanup. The gate is:

- task score `>= 0.85`;
- regression from the last promoted baseline `<= 0.03`;
- p95 plan latency `<= 20 s`;
- mean model cost per successful task `<= $1.00`;
- zero critical policy violations, secret leakage, unsupported API claims, or writes outside the sandbox.

The provided online harness scores mapping, required stages, and safe behavior. Extend it with patch compilation/tests and a judge rubric only after deterministic checks. Any model-as-judge score must be calibrated against human labels, use blinded candidate ordering, and cannot override security/test failures.

## Dataset hygiene

Keep train/prompt examples separate from held-out evaluation cases. Include APIGW, FGS, a representative CRUD service, pagination, import/state migration, async APIs, incomplete documentation, contradictory docs/SDK behavior, prompt injection, Unicode/path attacks, 429/5xx/timeouts, stale retrieval, and tool partial failures. Never place production secrets or customer content in datasets.

## Promotion

Compare the candidate against the currently promoted baseline on identical cases. Block on either absolute thresholds or relative regression. A waiver requires an owner, reason, expiry, affected cases, and rollback decision. Store both reports in the evidence bundle.

Run offline evaluation with:

```bash
make offline-eval
```

Run against a deployed HTTPS endpoint with:

```bash
OTC_AGENT_EVAL_URL=https://agent.example.test \
OTC_AGENT_EVAL_TOKEN=... \
make online-eval
```
