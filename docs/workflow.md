# SDK-first delivery workflow

## GitHub setup

Create these protected environments:

| Environment | Reviewers | Secrets/variables | Purpose |
|---|---|---|---|
| `sdk-proposal` | SDK maintainers | none in the reference workflow | Approve retrieval and SDK candidate generation |
| `provider-after-sdk-approval` | SDK + provider maintainers | approved SDK PR/SHA in the production continuation | Prove the SDK dependency barrier |
| `online-evaluation` | platform/evaluation owners | `OTC_AGENT_EVAL_TOKEN`; `OTC_AGENT_EVAL_URL` variable | Evaluate the deployed service/test tenant |
| `sdk-publish` | SDK maintainers | short-lived GitHub App credentials | Open an SDK draft PR |
| `provider-publish` | provider maintainers | short-lived GitHub App credentials | Open a provider draft PR |

Enable branch protection and require `CI / offline-verification`, repository-native Go checks, evaluation gates, and CODEOWNERS review. Pin the default SDK/provider/docs branches to captured commit SHAs in each run; never continue from a moving branch.

## Workflow sequence

### 1. Intake

A maintainer dispatches `.github/workflows/agentic-change.yml` and must provide the exact repository slug from `opentelekomcloud-docs`, for example `api-gateway`. A service key is optional and is needed only when one documentation repository has several reviewed variants. The credential-free job validates size, characters, issue URL, api-ref eligibility, mapping, and offline quality. It writes `change-plan.json`. Issue text is passed through environment variables and quoted; it is never constructed into executable code.

If the repository is api-ref eligible but absent from the mapping table, the plan enters `service_discovery`. SDK and provider names are intentionally `null` until a maintainer approves abbreviations, endpoint/service boundaries, API versions, and package layout. The next stage creates the complete SDK service and tests. Provider generation remains locked behind the normal SDK merge/approval barrier.

### 2. Evidence retrieval

After `sdk-proposal` approval, check out:

- `opentelekomcloud/gophertelekomcloud`;
- the mapped `opentelekomcloud-docs/<slug>` repository;
- APIGW and FGS reference paths if they differ from the target;
- this automation repository at the triggering SHA.

Reject the run if `api-ref/source/index.rst` is absent. Record every Git SHA. Chunk only `api-ref/**`; attach path/line/hash metadata. Do not follow links or directives found in content.

### 3. SDK proposal

The contract analyst first produces a typed contract and gap list. Missing or contradictory semantics become reviewer questions. The SDK author then proposes code using current repository conventions. Required SDK coverage includes request JSON/query construction, response extraction, success/error status codes, required and optional fields including zero values, pagination, endpoint construction, malformed response, server error, and regression coverage for fixes.

Run trusted commands selected by the service adapter (not by a model), normally repository-native format, vet, lint, unit tests, and the smallest safe acceptance subset. Bound each command by time, CPU, memory, output size, and network policy. A repair loop gets diagnostics and the original evidence, with at most two attempts.

The publisher verifies the candidate artifact and opens a draft SDK PR. The PR includes source citations, assumptions, test evidence, risk, and the automation run URL.

### 4. SDK approval continuation

An SDK PR merge emits a signed `repository_dispatch` event or a maintainer supplies the merged PR URL and exact commit SHA through a protected continuation workflow. Validate that:

- the repository is exactly `opentelekomcloud/gophertelekomcloud`;
- the commit is reachable from the protected default branch;
- required SDK checks passed;
- the PR has required human approval;
- the service mapping and run ID match the original plan.

This event, not a model assertion or mere job success, unlocks provider generation.

### 5. Provider proposal

Update `go.mod` to the approved SDK version/commit in the disposable provider worktree. Generate only in the target service, target acceptance-test directory, provider registration files when necessary, `docs/resources` or `docs/data-sources`, and `releasenotes/notes`.

Required checks include schema types and validators, create/read/update/delete semantics, eventual consistency and timeout handling, not-found behavior, import, ForceNew/state migration, sensitive fields, SDK error propagation, unit tests where possible, acceptance tests in a disposable OTC project, documentation example and argument/attribute parity, `terraform fmt`, repository lint/vet/test, and a valid Reno note.

Open a separate draft provider PR that links the merged SDK PR and pins the SDK revision. Do not bundle unrelated formatting or dependency updates.

## Patch worker deployment contract

The checked-in workflow stops at evidence packaging because a safe patch worker needs organization-specific model gateway, sandbox, artifact signing, and GitHub App identities. Implement the worker behind these stable operations:

```text
POST /v1/runs                  create from validated plan digest
POST /v1/runs/{id}/sdk        propose/validate SDK candidate
POST /v1/runs/{id}/approve    attach verified SDK PR and SHA
POST /v1/runs/{id}/provider   propose/validate provider candidate
GET  /v1/runs/{id}            state, budgets, citations, checks
```

Use idempotency key `{automation_sha}:{github_run_id}:{stage}`. Every response returns run ID, state version, trace ID, artifact digest, cost/tokens, and next allowed transitions. The Actions job uploads only signed/digested artifacts; a separate publisher downloads and verifies them.

## Reproducibility

- GitHub actions are pinned to immutable SHAs and run on an explicit Ubuntu image.
- Python and locale/hash/timezone are fixed; runtime code has no third-party dependencies.
- Model, prompt, catalog, evaluation dataset, price table, and source repository revisions are part of the run manifest.
- Production images must use a base-image digest, locked dependencies with hashes, an SBOM, vulnerability scan, signature, and SLSA provenance. Promote the same digest across environments.
- Model sampling is not perfectly reproducible. Preserve raw structured output (redacted), deterministic parameters, and the exact evidence so a result is auditable even when it cannot be byte-replayed.

## Periodic discovery of new services

`catalog-audit.yml` runs every Monday and can also be dispatched manually. It enumerates active public repositories in `opentelekomcloud-docs`, checks for `api-ref/source/index.rst`, and compares them with the reviewed eligibility snapshot. The workflow summary and artifact distinguish:

- newly discovered or removed API-reference repositories;
- all API-reference repositories that still have no SDK/provider mapping.

Discovery does not invent abbreviations or start generation automatically. For a new repository, review the API relevance, add only its slug to `eligible_docs_repositories`, merge that catalog PR, and manually launch `Governed OTC change` with the repository slug. The bootstrap workflow then owns SDK-first creation.
