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

Each SDK/provider candidate is internally produced as a hash-linked artifact chain:

`EXPLORE → SPECIFY → PLAN → IMPLEMENT → VERIFY → REVIEW → PUBLISH`

Every accepted phase serializes a canonical JSON payload, records its SHA-256 digest, and includes the preceding artifact digest. The current `REVIEW` artifact represents deterministic citation, path, and repository-native validation; independent model review is added as a separate reviewer without changing the chain contract. `PUBLISH` means ready for the protected publisher, not that a GitHub write occurred.

The review boundary reconstructs and verifies the complete artifact chain, then creates a separate review bundle containing only the frozen `EXPLORE` through `VERIFY` artifacts, the digest-matched patch, and allow-listed deterministic diagnostics. Raw prompts, messages, conversation history, and hidden author reasoning are not copied into reviewer context.

Reviewer execution uses a separately configured model route. Trusted routing code compares capability tiers before the call and requires reviewer strength to be equal to or greater than the author strength recorded by the generation skill. The exact same endpoint/model identity cannot review its own output.

## Retrieval

The retrieval broker indexes only:

1. `api-ref/**` from the mapped documentation repository;
2. the target service in SDK/provider;
3. APIGW and FGS reference implementations;
4. repository-owned style, contribution, test, and release-note instructions.

Chunks retain `{repository, commit, path, start_line, end_line, sha256, document_type}`. Retrieval uses lexical search for exact field/endpoint names plus embeddings for semantic recall. The reranker favors the target service and API reference over examples. Retrieved text is enclosed as quoted evidence and cannot introduce tools or alter policy. A generated API field without a supporting citation is a blocking error.

Vector indexes are caches, never sources of truth. They are rebuilt for a specific commit and tenant, encrypted at rest, and deleted according to retention policy. Cross-run and cross-tenant retrieval is forbidden.

## Model routing

Use GitHub Copilot SDK and its CLI-authenticated runtime as the default model backend. The provider-neutral model contract keeps an OpenAI-compatible BYOK adapter available for approved deployments that require it. Route low-risk extraction to the smallest model that meets the quality gate; use a stronger coding model for patch proposals. Provider, model identity, runtime endpoint, parameters, prompt version, token counts, latency, and available cost metadata are recorded.

Temperature is zero for extraction/review and low for code generation. A fallback model is allowed once for a transient outage. It is not allowed when policy rejected the primary output, since switching models does not remove the unsafe requirement.

## Patch-worker contract

Input is a signed plan, read-only snapshots, a file/path allow-list, evidence chunks, and budgets. Output is JSON containing complete candidate files, citations per behavior, assumptions, and confidence—not commands. The executor:

1. validates the schema and total byte/file limits;
2. rejects symlinks, path traversal, workflow changes, generated binaries, secrets, and out-of-scope files;
3. writes into a disposable worktree as an unprivileged user with network disabled;
4. derives the diff locally;
5. invokes only fixed test commands selected by trusted code;
6. discards the worktree after packaging the diff and evidence.

Publishing runs as an explicit local stage after model sessions are closed. It loads a narrowly scoped GitHub identity only after verifying the artifact digest, then opens or updates the draft PR.

## Storage and audit

Store run state in PostgreSQL with optimistic transitions and idempotency keys. Store evidence bundles in versioned object storage with retention lock. Never store raw access tokens or full model payloads that may contain secrets. The minimum evidence bundle contains request digest, normalized request, mapping version, source SHAs, citations, prompts and model metadata, budgets, tool invocations, test output summaries, evaluation report, patch hash, approvals, and PR URLs.

## Deployment

Run generation, retrieval, review, repair, and publishing through the local CLI. The only Kubernetes workload is the optional stateless planning/health/metrics API for remote clients and online evaluation. It receives no model or publishing credentials and uses default-deny egress. Durable local execution may later use external PostgreSQL and object storage, but those services are not part of the planning API deployment.

Durable CLI execution prefers an external PostgreSQL state store when `OTC_POSTGRES_DSN` is configured. Otherwise it falls back to local MySQL, using `OTC_MYSQL_DSN` or the `OTC_MYSQL_*` settings (default host `127.0.0.1`, port `3306`, user `root`, database `otc_agent`). Equivalent packaged migrations record runs, every stage attempt and artifact link, source and branch revisions, approvals, pull requests, comments, and repair attempts. The remote planning API remains stateless and does not connect to either database.

Run transitions use a compare-and-swap version on the run row and a durable idempotency key bound to the operation and canonical request digest. A stale expected version fails atomically. Retrying the same key and request returns the stored transition result, while reusing a key for different input is rejected. PostgreSQL provides the primary implementation and local MySQL preserves equivalent behavior.

GitHub webhooks enter an idempotent durable inbox keyed by delivery ID. Workers claim ready events transactionally with row locking, dispatch only registered event types, and either record a completed JSON result or requeue with a delay. Attempts are bounded; exhausted or permanently unsupported events enter `dead_letter` with their last error for operator inspection. PostgreSQL and MySQL migrations provide equivalent queue tables and indexes.

Temporal adoption is currently deferred. The existing database executor covers required durability, concurrency, retry, resume, reconciliation, and event-queue behavior while preserving local MySQL operation. The decision, tradeoffs, and measurable adoption triggers are recorded in [the Temporal evaluation](decisions/temporal.md).
