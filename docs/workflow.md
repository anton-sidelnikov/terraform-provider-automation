# SDK-first delivery workflow

## Execution boundary

Generation, review, repair, and pull-request iteration run from the local `otc-agent` CLI. GitHub Actions never receive Copilot credentials and never execute model-backed commands. Repository workflows are limited to deterministic CI, catalog auditing, release checks, and optional online evaluation.

The local run checks out and revision-pins the automation, SDK, provider, and documentation repositories. It stores the resulting plan, patch, frozen artifacts, and evidence locally. Publishing uses the operator's authenticated GitHub CLI session or a narrowly scoped GitHub App credential; model execution and GitHub write credentials remain separate.

Enable branch protection and require `CI / offline-verification`, repository-native Go checks, evaluation gates, and CODEOWNERS review.

## Workflow sequence

### 1. Intake

A maintainer invokes the local CLI with the exact repository slug from `opentelekomcloud-docs`, for example `api-gateway`, plus a change description. There is no manual `kind`: trusted rules classify `feature` (new endpoint/operation), `fix` (changed parameter/request/response), `update` (added attributes/fields), or `new_service` (unmapped repository). Confidence below 0.70 blocks generation. A service key is optional and needed for ambiguous variants or to override a proposed bootstrap abbreviation.

If the repository is api-ref eligible but absent from the mapping table, the plan enters `service_discovery` and proposes a deterministic abbreviation (one word stays intact; a hyphenated service uses its initials). A maintainer approves that proposal locally or reruns with an explicit `service_key`. The next stage creates the complete SDK service and tests. Provider generation remains locked behind the normal SDK merge/approval barrier.

### 2. Evidence retrieval

After local plan approval, check out:

- `opentelekomcloud/gophertelekomcloud`;
- the mapped `opentelekomcloud-docs/<slug>` repository;
- APIGW and FGS reference paths if they differ from the target;
- this automation repository at the triggering SHA.

Reject the run if `api-ref/source/index.rst` is absent. Record every Git SHA. Chunk only `api-ref/**`; attach path/line/hash metadata. Do not follow links or directives found in content.

### 3. SDK proposal

The contract analyst first produces a typed contract and gap list. Missing or contradictory semantics become reviewer questions. The SDK author then proposes code using current repository conventions. Required SDK coverage includes request JSON/query construction, response extraction, success/error status codes, required and optional fields including zero values, pagination, endpoint construction, malformed response, server error, and regression coverage for fixes.

Run trusted commands selected by the service adapter (not by a model), normally repository-native format, vet, lint, unit tests, and the smallest safe acceptance subset. Bound each command by time, CPU, memory, output size, and network policy. A repair loop gets diagnostics and the original evidence, with at most two attempts.

Only an independent `request_changes` decision can start repair. Each repair is a complete replacement diff against the original revision, passes deterministic validation before rereview, and is reviewed in a fresh context-isolated bundle. An `approve` decision ends the loop, `block` stops immediately, and a third repair attempt is rejected.

The review output includes an append-only, hash-linked journal. It stores the complete initial proposal, deterministic diagnostics, review decisions and findings, every replacement repair proposal, and every repair validation/rereview result. Canonical payload and chain digests make removal, reordering, or modification detectable.

For confirmed legacy or mixed SDK layouts, `otc-agent refactor-sdk` first creates a deterministic migration plan. The plan maps each remaining legacy operation to its operation-named target file, groups moves by package, and blocks stale analyzer input, duplicate exported operations, or existing target-file collisions before any edit is proposed.

The plan also freezes a Go-parser-derived snapshot of every exported function, method, type, constant, and variable. A candidate checkout may add symbols, but any removal or signature change blocks migration unless its exact package/kind/name identifier appears in the approved specification's `approved_api_changes` list.

With explicit `"apply": true`, the refactoring skill uses Go ASTs to move each operation function together with operation-prefixed options, results, builder interfaces, receiver methods, and unexported helpers into the matching operation file. Unmatched declarations remain in the legacy source, imports are recalculated per file, and all writes roll back if the exported API compatibility check fails.

Declaration ownership is dependency-aware. The executor follows identifier references transitively from every operation; a type, constant, variable, or helper reached by two or more operations remains in the common source file, while declarations exclusively reached by one operation move with it.

After splitting, the executor reparses every legacy `request.go`, `requests.go`, `urls.go`, and `results.go` file. It deletes only files with no remaining non-import declarations; shared or otherwise non-empty legacy files stay in place. Deletions participate in the same compatibility rollback as file writes.

An independent Go AST gate then enumerates recognized exported operation functions across the service. Every operation must be declared exactly once and its source path must end in `<Operation>.go`; duplicate operations or filename mismatches block candidate acceptance and roll back an applied migration.

The final refactoring gate runs `go test ./openstack/<service>/...` and inventories test functions with Go ASTs. Each migrated operation requires request, response, error, zero-value, and fixture evidence; `List*` operations additionally require pagination evidence unless the approved specification supplies an explicit `behavior_checks` list. Missing evidence or a failed Go test blocks and rolls back migration.

A separate semantic snapshot hashes normalized Go AST declarations, including function and method bodies. Refactoring must therefore be a pure declaration relocation by default: added, removed, or changed declarations block the candidate even when exported signatures remain compatible. Deliberate changes require exact declaration identifiers in `approved_behavior_changes`.

Migration planning emits one deterministic `migration_id`, branch suffix, and pull-request title per exported operation. A multi-operation plan cannot be applied without choosing one `migration_id`; the resulting patch moves only that route and validates only that route's file/behavior requirements, leaving remaining legacy operations for later append-only pull requests.

Before any Git write, `otc-agent publish` performs a read-only preflight with the authenticated GitHub CLI. It verifies the exact repository, full base commit SHA, regular evidence artifact and digest, and an open issue carrying the configured approval label (`agent-approved` by default). The input must identify exactly one exported SDK operation route. Multiple routes require the same approved issue to carry `agent-multi-route-approved`, or the label configured through `OTC_ROUTE_SCOPE_EXCEPTION_LABEL`. It then renders the governed SDK pull-request body with exactly one `For #<issue>` directive matching that verified issue and authoritative service/API-reference portal links derived from the reviewed documentation catalog. Conflicting issue directives or documentation metadata stop publication. Missing approval, closed issues, malformed GitHub responses, or authentication failures also stop publication.

The generator queries only revision-pinned `api-ref/**/*.rst`, requires citations from retrieved chunks, accepts only a unified diff under `openstack/<sdk>/**`, applies it in a disposable checkout, runs fixed `gofmt`, `go test`, and `go vet` commands, and records a SHA-256 evidence manifest. The local publisher independently verifies the digest/path scope, pushes `agent/<kind>-<service>-<run-id>`, and opens a draft SDK PR.

### 4. SDK approval continuation

A maintainer continues the local run with the merged SDK PR number and the original repository/service/description. The tool fetches the PR and validates that:

- the repository is exactly `opentelekomcloud/gophertelekomcloud`;
- the commit is reachable from the protected default branch;
- the PR was authored by a bot from an `agent/*` branch;
- the service mapping and classification match the independently recreated plan.

The SDK PR body contains machine-readable automation metadata. Its mapping and independent classification must match the provider plan. A verified merge, not a model assertion or mere job success, unlocks provider generation.

### 5. Provider proposal

Update `go.mod` to the approved SDK version/commit in the disposable provider worktree. Generate only in the target service, target acceptance-test directory, provider registration files when necessary, `docs/resources` or `docs/data-sources`, and `releasenotes/notes`.

When a provider or infrastructure PR depends on another unmerged pull request, the governed body records each exact GitHub PR URL using the upstream `Depends-On: <url>` convention. Conflicting, duplicate, or non-GitHub dependency references block publication.

Publication also resolves the captured base, candidate head, and optional previously published head as commits in the local worktree. The candidate must be a strict descendant of the base; every review update must be a strict descendant of the previous head. Only an ordinary fast-forward push is permitted, so rebases, amended histories, branch replacement, and force pushes are rejected before GitHub access.

The publisher parses the verified JSON artifact and appends a canonical machine-readable PR-body block. It includes policy references, author and publisher skill identities, artifact/patch/final-workflow hashes, repository and documentation revisions, Git base/head revisions, issue, routes, exception approval, and the fast-forward-only mode. Missing or malformed evidence blocks publication; existing conflicting metadata cannot be replaced silently.

Required checks include schema types and validators, create/read/update/delete semantics, eventual consistency and timeout handling, not-found behavior, import, ForceNew/state migration, sensitive fields, SDK error propagation, unit tests where possible, acceptance tests in a disposable OTC project, documentation example and argument/attribute parity, `terraform fmt`, repository lint/vet/test, and a valid Reno note.

Open a separate draft provider PR that links the merged SDK PR and pins the SDK revision. Do not bundle unrelated formatting or dependency updates.

## Model configuration

GitHub Copilot SDK is the default backend. Set `OTC_MODEL_NAME` and authenticate the Copilot CLI locally with the logged-in user, or export `COPILOT_GITHUB_TOKEN` for a licensed and authorized identity. The SDK downloads its pinned runtime on first use. `OTC_COPILOT_CLI_PATH` selects a provisioned runtime, while `OTC_COPILOT_RUNTIME_URL` connects to an existing headless runtime.

Independent review uses `OTC_REVIEW_MODEL_NAME` and optional `OTC_REVIEW_MODEL_TIER` (`fast` or `strong`, default `strong`). It shares Copilot authentication but must use a distinct provider/runtime/model identity from the author route. The router rejects a weaker or identical reviewer.

BYOK remains an explicit fallback. Set `OTC_MODEL_PROVIDER=openai-compatible` (or `OTC_REVIEW_MODEL_PROVIDER`) together with the corresponding `*_BASE_URL`, `*_NAME`, and `*_API_KEY` variables. Optional price variables remain supported for this backend.

GitHub Actions do not run generation or publishing. `deploy/` deploys only the credential-free stateless planning/metrics API used by remote clients and online evaluation. Tagged releases attach Python CLI distributions and publish a separately signed OCI image for this API.

## Reproducibility

- Remaining GitHub Actions are pinned to immutable SHAs and run on an explicit Ubuntu image.
- Python and locale/hash/timezone are fixed; runtime code has no third-party dependencies.
- Model, prompt, policy, skill, catalog, evaluation dataset, price table, and source repository revisions are part of the run manifest.
- Production images must use a base-image digest, locked dependencies with hashes, an SBOM, vulnerability scan, signature, and SLSA provenance. Promote the same digest across environments.
- Model sampling is not perfectly reproducible. Preserve raw structured output (redacted), deterministic parameters, and the exact evidence so a result is auditable even when it cannot be byte-replayed.

## Periodic discovery of new services

`catalog-audit.yml` runs every Monday and can also be dispatched manually. It enumerates active public repositories in `opentelekomcloud-docs`, checks for `api-ref/source/index.rst`, and compares them with the reviewed eligibility snapshot. The workflow summary and artifact distinguish:

- newly discovered or removed API-reference repositories;
- all API-reference repositories that still have no SDK/provider mapping.

Discovery does not start generation automatically. For a new repository, review the API relevance, add only its slug to `eligible_docs_repositories`, merge that catalog PR, and start the local CLI with the repository slug. The bootstrap stage proposes an abbreviation and then owns SDK-first creation.
