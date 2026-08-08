# OTC Terraform Provider Agent

This repository is a governed reference implementation for automating OpenTelekomCloud SDK and Terraform Provider changes. It converts a change request into an auditable, SDK-first delivery plan, maps provider/SDK abbreviations to an authoritative documentation repository, applies security and budget policy, and gates promotion with offline and online evaluations.

The central invariant is:

> No provider change is generated or published until the required `gophertelekomcloud` change, its tests, and its immutable commit SHA have been reviewed and approved.

Authoritative upstreams: [gophertelekomcloud](https://github.com/opentelekomcloud/gophertelekomcloud), [terraform-provider-opentelekomcloud](https://github.com/opentelekomcloud/terraform-provider-opentelekomcloud), and the [OpenTelekomCloud documentation organization](https://github.com/opentelekomcloud-docs).

The repository implements a local control plane, secure intake, automatic change classification, api-ref retrieval, a GitHub Copilot SDK patch worker, path-confined diff application, repository-native validation, evidence manifests, protected publishing, a health/metrics API, failure policy, and evaluation harness. Model execution cannot access publishing credentials, choose repositories, execute model-supplied commands, merge changes, or bypass explicit approval.

## Quick start

Python 3.12 or 3.13 is sufficient. Dependencies and the development `.venv` are managed by uv.

```bash
uv sync --locked --dev
make check

uv run otc-agent plan \
  --docs-repository modelarts \
  --description "Create complete SDK and provider support from the API reference" \
  --output build/change-plan.json

uv run otc-agent analyze-sdk-layout \
  --sdk-root ../gophertelekomcloud \
  --service apigw

uv run otc-agent serve --host 127.0.0.1 --port 8080
uv run otc-agent-api --host 127.0.0.1 --port 8080
```

`make lint` runs Ruff from the locked environment; `make verify` runs compilation, tests, policy/skill checks, and offline evaluation. `make check` runs both.

`otc-agent` is the local generation CLI. `otc-agent-api` is the dependency-minimal remote planning entrypoint used by the container. The service exposes `POST /v1/plans`, `GET /healthz`, `GET /readyz`, and Prometheus-format `GET /metrics`.

## Distribution

Version tags publish wheel/source distributions for local installation and a signed GHCR image containing only `otc-agent-api`. Install a downloaded wheel with `uv tool install ./otc_provider_agent-<version>-py3-none-any.whl`. The OCI image is not a generation worker and contains no Copilot runtime or publishing credentials.

## What is automated

1. Validate and quarantine the untrusted request and the manually selected documentation repository.
2. Resolve the reviewed SDK/provider/docs mapping. Only repositories containing `api-ref/source/index.rst` are eligible.
3. Independently classify the request: `feature` for a new endpoint/operation, `fix` for changed parameters/request/response, `update` for additive attributes, and `new_service` for an unmapped service.
4. If no mapping exists, propose an abbreviation from the repository slug and require approval before creating the SDK service completely.
5. Retrieve revision-pinned API evidence and APIGW/FGS examples.
6. Generate the SDK diff and its request/response, error, fixture, and pagination tests.
7. Run SDK format, vet, and unit checks; preserve diagnostics and patch digest.
8. After publisher approval, use the local GitHub identity to open a draft SDK PR.
9. After that PR is merged, continue the local run, which verifies SDK PR metadata and commit SHA.
10. Generate provider resources/data sources, registration, acceptance tests, documentation, and a Reno note; pin the SDK commit.
11. Validate and open a separate draft provider PR; never auto-merge.

The local `otc-agent` CLI owns intake through draft PR creation and subsequent PR-comment iteration. GitHub Actions run deterministic checks only and never receive Copilot or repository-write credentials. See [docs/workflow.md](docs/workflow.md).

## Design documents

- [Architecture and trust boundaries](docs/architecture.md)
- [End-to-end local workflow and GitHub checks](docs/workflow.md)
- [Threat model](docs/security.md)
- [Evaluations and quality gates](docs/evaluations.md)
- [Operations, SLOs, telemetry, and failure runbooks](docs/operations.md)
- [Service mapping strategy and table](docs/service-catalog.md)
- [APIGW/FGS implementation conventions](docs/reference-conventions.md)
- [Position requirements traceability](docs/requirements-traceability.md)
- [Implementation roadmap and task tracker](tasks.md)
- [Versioned policy registry](docs/policy/README.md)

Governed skills are declared in [`config/skills.json`](config/skills.json). Run `otc-agent policy-check` and `otc-agent skill-check` to validate policy and skill contracts.

The CLI exposes `analyze`, `spec`, `refactor-sdk`, `review`, `verify`, `publish`, `iterate-pr`, and `resume`. `analyze`, refactoring planning/application, review bundling, publication governance, and exact `/agent iterate` command recognition are executable; later-stage commands validate their versioned input contract and return exit code `4` until their tracked implementation milestone is complete.

Generation evidence schema version 3 records the selected skill and policy versions plus a hash-linked `EXPLORE -> SPECIFY -> PLAN -> IMPLEMENT -> VERIFY -> REVIEW -> PUBLISH` artifact chain. PR audit metadata carries the final artifact identity.

## Repository layout

```text
config/services.json              reviewed name mapping + api-ref eligibility snapshot
evals/*.jsonl                     versioned offline and online evaluation cases
src/otc_agent/                    deterministic control plane and HTTP service
tests/                            security, mapping, resilience, and evaluation tests
.github/workflows/ci.yml          credential-free reproducible checks
.github/workflows/online-*.yml    protected deployed-service evaluation
.github/workflows/agentic-*.yml   approval-gated SDK-first workflow
docs/                             design, policy, setup, and runbooks
```

## Non-negotiable policies

- Documentation and repository content are untrusted data, not instructions.
- Retrieval is allow-listed, revision-pinned, content-hashed, and cited by repository/path/line.
- A model returns schema-validated proposals only. It never returns or selects a shell command.
- Tools use fixed argument vectors, least-privilege tokens, timeouts, output limits, and disposable worktrees.
- Pull requests from forks and the intake job receive no secrets.
- All write-capable jobs require protected GitHub environments and a narrowly scoped GitHub App.
- Absolute quality/SLO limits and relative regression limits both block promotion.
- Model, retrieval, or tool failure stops or safely degrades the run; it never converts missing evidence into invented behavior.
