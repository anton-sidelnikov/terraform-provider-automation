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
- direct legacy-layout evidence, adopted policy-contract compliance, bounded review repair, and PR-command replay idempotency;
- replayed model/retrieval/tool timeouts and malformed outputs.

The current gate is `score >= 0.90`. Cases marked `critical` are non-compensating: any failure blocks the report even when the aggregate score remains above the threshold. Security, SDK ordering, legacy classification, policy compliance, review repair, and PR idempotency use this fail-closed path.

## Candidate evaluator-optimizer gate

Model-generated SDK/provider candidates first pass non-compensating deterministic schema, citation-provenance, and path-scope checks. An independent equal-or-stronger reviewer then scores correctness, evidence, tests, scope, and maintainability. Acceptance requires mean score `>= 0.85`, every dimension `>= 0.75`, and decision `pass`. A `block` decision stops immediately; `revise` permits at most two complete replacement candidates from the author route, each of which must repeat deterministic validation and independent evaluation. All scores, findings, routes, and diagnostics are stored in generation evidence.

## Online evaluation

The scheduled/manual workflow uses two separated endpoints:

- `OTC_AGENT_EVAL_URL` calls the credential-free deployed `/v1/plans` endpoint for deterministic planning.
- `OTC_AGENT_WORKFLOW_EVAL_URL` calls a governed agent runner's `/v1/evaluations` endpoint for generation, compilation, repository-native tests, and same-PR comment iteration. The runner owns its model and narrowly scoped GitHub credentials; they are never passed to the planning API or evaluation client.

Workflow responses must correlate the dataset case ID, report successful compilation and repository-native test evidence with SHA-256 digests, confirm an exact `/agent iterate` command updated the same PR using append-only history, and include end-to-end latency and model cost. These workflow cases are critical and non-compensating. The aggregate gate is:

- task score `>= 0.85`;
- regression from the last promoted baseline `<= 0.03`;
- p95 plan latency `<= 20 s`;
- mean model cost per successful task `<= $1.00`;
- zero critical policy violations, secret leakage, unsupported API claims, or writes outside the sandbox.

The online harness scores mapping, required stages, compilation, repository-native tests, comment iteration, latency, and cost. Any future model-as-judge score must be calibrated against human labels, use blinded candidate ordering, and cannot override security/test failures.

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
OTC_AGENT_EVAL_URL=https://planner.example.test \
OTC_AGENT_WORKFLOW_EVAL_URL=https://workflow.example.test \
make online-eval
```
