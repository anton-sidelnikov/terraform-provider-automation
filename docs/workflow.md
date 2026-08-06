# SDK-first delivery workflow

## GitHub setup

Create these protected environments:

| Environment                   | Reviewers                  | Secrets/variables                                     | Purpose                                                   |
|-------------------------------|----------------------------|-------------------------------------------------------|-----------------------------------------------------------|
| `sdk-proposal`                | SDK maintainers            | model gateway variables and `OTC_MODEL_API_KEY`       | Approve retrieval and SDK candidate generation            |
| `provider-after-sdk-approval` | SDK + provider maintainers | model gateway variables and `OTC_MODEL_API_KEY`       | Verify merged SDK PR and approve provider generation      |
| `online-evaluation`           | platform/evaluation owners | `OTC_AGENT_EVAL_TOKEN`; `OTC_AGENT_EVAL_URL` variable | Evaluate the deployed service/test tenant                 |
| `sdk-publish`                 | SDK maintainers            | `OTC_APP_ID`, `OTC_APP_PRIVATE_KEY`                   | Mint a short-lived App token and open an SDK draft PR     |
| `provider-publish`            | provider maintainers       | `OTC_APP_ID`, `OTC_APP_PRIVATE_KEY`                   | Mint a short-lived App token and open a provider draft PR |

Enable branch protection and require `CI / offline-verification`, repository-native Go checks, evaluation gates, and CODEOWNERS review. Pin the default SDK/provider/docs branches to captured commit SHAs in each run; never continue from a moving branch.

## Workflow sequence

### 1. Intake

A maintainer dispatches `.github/workflows/agentic-change.yml` and provides the exact repository slug from `opentelekomcloud-docs`, for example `api-gateway`, plus a change description. There is no manual `kind`: trusted rules classify `feature` (new endpoint/operation), `fix` (changed parameter/request/response), `update` (added attributes/fields), or `new_service` (unmapped repository). Confidence below 0.70 blocks generation. A service key is optional and needed for ambiguous variants or to override a proposed bootstrap abbreviation.

If the repository is api-ref eligible but absent from the mapping table, the plan enters `service_discovery` and proposes a deterministic abbreviation (one word stays intact; a hyphenated service uses its initials). Approval of `sdk-proposal` approves that proposal; a maintainer can instead provide `service_key`. The next stage creates the complete SDK service and tests. Provider generation remains locked behind the normal SDK merge/approval barrier.

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

The generator queries only revision-pinned `api-ref/**/*.rst`, requires citations from retrieved chunks, accepts only a unified diff under `openstack/<sdk>/**`, applies it in a disposable checkout, runs fixed `gofmt`, `go test`, and `go vet` commands, and records a SHA-256 evidence manifest. The `sdk-publish` job independently verifies the digest/path scope, mints a one-hour repository-scoped GitHub App token, pushes `agent/<kind>-<service>-<run-id>`, and opens a draft SDK PR.

### 4. SDK approval continuation

A maintainer dispatches `.github/workflows/provider-change.yml` with the merged SDK PR number and the original repository/service/description. The workflow fetches the PR and validates that:

- the repository is exactly `opentelekomcloud/gophertelekomcloud`;
- the commit is reachable from the protected default branch;
- the PR was authored by a bot from an `agent/*` branch;
- the service mapping and classification match the independently recreated plan.

The SDK PR body contains machine-readable automation metadata. Its mapping and independent classification must match the provider plan. A verified merge, not a model assertion or mere job success, unlocks provider generation.

### 5. Provider proposal

Update `go.mod` to the approved SDK version/commit in the disposable provider worktree. Generate only in the target service, target acceptance-test directory, provider registration files when necessary, `docs/resources` or `docs/data-sources`, and `releasenotes/notes`.

Required checks include schema types and validators, create/read/update/delete semantics, eventual consistency and timeout handling, not-found behavior, import, ForceNew/state migration, sensitive fields, SDK error propagation, unit tests where possible, acceptance tests in a disposable OTC project, documentation example and argument/attribute parity, `terraform fmt`, repository lint/vet/test, and a valid Reno note.

Open a separate draft provider PR that links the merged SDK PR and pins the SDK revision. Do not bundle unrelated formatting or dependency updates.

## Model gateway configuration

Both generation environments require `OTC_MODEL_BASE_URL` (an OpenAI-compatible base ending in `/v1`), `OTC_MODEL_NAME`, and secret `OTC_MODEL_API_KEY`. Optional price variables are `OTC_MODEL_INPUT_USD_PER_MILLION` and `OTC_MODEL_OUTPUT_USD_PER_MILLION`. The adapter uses JSON mode, temperature zero, bounded retries, token/cost budgets, and never logs prompts or credentials.

PR generation runs as ephemeral Actions jobs, so no separate patch-worker service is required for the demo. `deploy/` deploys only the stateless planning/metrics API used by online evaluation.

## Reproducibility

- GitHub actions are pinned to immutable SHAs and run on an explicit Ubuntu image.
- Python and locale/hash/timezone are fixed; runtime code has no third-party dependencies.
- Model, prompt, policy, skill, catalog, evaluation dataset, price table, and source repository revisions are part of the run manifest.
- Production images must use a base-image digest, locked dependencies with hashes, an SBOM, vulnerability scan, signature, and SLSA provenance. Promote the same digest across environments.
- Model sampling is not perfectly reproducible. Preserve raw structured output (redacted), deterministic parameters, and the exact evidence so a result is auditable even when it cannot be byte-replayed.

## Periodic discovery of new services

`catalog-audit.yml` runs every Monday and can also be dispatched manually. It enumerates active public repositories in `opentelekomcloud-docs`, checks for `api-ref/source/index.rst`, and compares them with the reviewed eligibility snapshot. The workflow summary and artifact distinguish:

- newly discovered or removed API-reference repositories;
- all API-reference repositories that still have no SDK/provider mapping.

Discovery does not start generation automatically. For a new repository, review the API relevance, add only its slug to `eligible_docs_repositories`, merge that catalog PR, and manually launch `Generate SDK pull request` with the repository slug. The bootstrap workflow proposes an abbreviation and then owns SDK-first creation.
