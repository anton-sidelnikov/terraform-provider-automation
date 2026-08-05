# Architecture

## Decision

Use a deterministic Python control plane around specialized, replaceable agents. A graph framework can be introduced inside the patch-worker boundary later, but workflow state, transitions, budgets, and approvals remain ordinary code. This makes the safety-critical behavior testable without a model and avoids coupling governance to one model vendor.

## Components

```text
GitHub issue / dispatch (untrusted)
            |
            v
  Intake + policy engine -----> immutable run/evidence store
            |
            v
  Catalog resolver ----------- reviewed abbreviation map
            |
            v
  Retrieval broker ----------- docs api-ref + SDK/provider snapshots
            |                   (allow-list, commit pin, hash, citation)
            v
  SDK patch worker -----------> disposable SDK worktree
            |
      validation + approval
            |
            v
  Provider patch worker ------> disposable provider worktree
            |
  docs/tests/release note + evals
            |
      approval + two PRs
```

The patch workers have four logical roles, even if one model serves all of them:

- **Contract analyst** extracts endpoints, request/response fields, constraints, error semantics, pagination, and unknowns from API reference evidence.
- **SDK author** proposes only SDK files and tests, using APIGW for CRUD/pagination structure and FGS for event/configuration patterns.
- **Provider author** starts only from an approved SDK SHA and proposes schema, CRUD/read behavior, state/import behavior, tests, docs, and release notes.
- **Reviewer** compares claims to cited source lines, runs deterministic checks, scores risk, and cannot modify code.

Role separation reduces correlated failure. A high-risk or low-confidence proposal must be reviewed by a human rather than passed between models until they agree.

## State machine

`intake → retrieve → sdk_plan → sdk_generate → sdk_validate → sdk_approval → provider_plan → provider_generate → provider_validate → online_eval → publish`

Every transition has a machine-readable input/output schema, deadline, retry policy, and terminal failure status. `sdk_approval` is a hard barrier. Resumption uses a run ID and verifies all upstream commit IDs and hashes; it does not replay completed write operations.

## Retrieval

The retrieval broker indexes only:

1. `api-ref/**` from the mapped documentation repository;
2. the target service in SDK/provider;
3. APIGW and FGS reference implementations;
4. repository-owned style, contribution, test, and release-note instructions.

Chunks retain `{repository, commit, path, start_line, end_line, sha256, document_type}`. Retrieval uses lexical search for exact field/endpoint names plus embeddings for semantic recall. The reranker favors the target service and API reference over examples. Retrieved text is enclosed as quoted evidence and cannot introduce tools or alter policy. A generated API field without a supporting citation is a blocking error.

Vector indexes are caches, never sources of truth. They are rebuilt for a specific commit and tenant, encrypted at rest, and deleted according to retention policy. Cross-run and cross-tenant retrieval is forbidden.

## Model routing

Use an internal OpenAI-compatible gateway so approved frontier, open-weight, and coding models can be evaluated behind one contract. Route low-risk extraction to the smallest model that meets the quality gate; use a stronger coding model for patch proposals. Model identity, endpoint, parameters, prompt version, token counts, latency, and price-table version are recorded.

Temperature is zero for extraction/review and low for code generation. A fallback model is allowed once for a transient outage. It is not allowed when policy rejected the primary output, since switching models does not remove the unsafe requirement.

## Patch-worker contract

Input is a signed plan, read-only snapshots, a file/path allow-list, evidence chunks, and budgets. Output is JSON containing complete candidate files, citations per behavior, assumptions, and confidence—not commands. The executor:

1. validates the schema and total byte/file limits;
2. rejects symlinks, path traversal, workflow changes, generated binaries, secrets, and out-of-scope files;
3. writes into a disposable worktree as an unprivileged user with network disabled;
4. derives the diff locally;
5. invokes only fixed test commands selected by trusted code;
6. discards the worktree after packaging the diff and evidence.

Publishing runs in a separate job with no model access and a GitHub App token restricted to the target repository. It verifies the artifact digest before opening a draft PR.

## Storage and audit

Store run state in PostgreSQL with optimistic transitions and idempotency keys. Store evidence bundles in versioned object storage with retention lock. Never store raw access tokens or full model payloads that may contain secrets. The minimum evidence bundle contains request digest, normalized request, mapping version, source SHAs, citations, prompts and model metadata, budgets, tool invocations, test output summaries, evaluation report, patch hash, approvals, and PR URLs.

## Deployment

Run the API/control plane, patch workers, retrieval workers, and telemetry collector as separate Kubernetes workloads. Use a queue with visibility timeouts and a dead-letter queue. Apply default-deny network policy; only the retrieval broker reaches allow-listed GitHub endpoints, only the model broker reaches approved model endpoints, and only the publisher reaches GitHub write APIs. Use workload identity and a secrets manager, not long-lived environment credentials.

