# OTC Terraform Provider Agent

This repository is a governed reference implementation for automating OpenTelekomCloud SDK and Terraform Provider changes. It converts a change request into an auditable, SDK-first delivery plan, maps provider/SDK abbreviations to an authoritative documentation repository, applies security and budget policy, and gates promotion with offline and online evaluations.

The central invariant is:

> No provider change is generated or published until the required `gophertelekomcloud` change, its tests, and its immutable commit SHA have been reviewed and approved.

Authoritative upstreams: [gophertelekomcloud](https://github.com/opentelekomcloud/gophertelekomcloud), [terraform-provider-opentelekomcloud](https://github.com/opentelekomcloud/terraform-provider-opentelekomcloud), and the [OpenTelekomCloud documentation organization](https://github.com/opentelekomcloud-docs).

The repository currently implements the control plane, secure intake, mapping catalog, deterministic state machine, health/metrics API, failure policy, and evaluation harness. The model-backed patch worker is deliberately an isolated deployment component: it may propose file content in a disposable worktree, but it cannot choose repositories, execute model-supplied commands, access production credentials, merge changes, or bypass approval environments.

## Quick start

Python 3.12 or 3.13 is sufficient; the runtime has no third-party dependencies.

```bash
make check

PYTHONPATH=src python -m otc_agent.cli plan \
  --docs-repository modelarts \
  --kind new_service \
  --description "Create complete SDK and provider support from the API reference" \
  --output build/change-plan.json

PYTHONPATH=src python -m otc_agent.cli serve --host 127.0.0.1 --port 8080
```

The service exposes `POST /v1/plans`, `GET /healthz`, `GET /readyz`, and Prometheus-format `GET /metrics`.

## What is automated

1. Validate and quarantine the untrusted request and the manually selected documentation repository.
2. Resolve the reviewed SDK/provider/docs mapping. Only repositories containing `api-ref/source/index.rst` are eligible.
3. If no mapping exists, enter service bootstrap: approve names/boundaries, then create the SDK service completely before any provider work.
4. Retrieve revision-pinned API evidence and APIGW/FGS examples.
5. Propose the SDK implementation and its request/response, error, fixture, and pagination tests.
6. Run SDK format, vet, lint, unit, and targeted acceptance checks; preserve diagnostics.
7. Require SDK reviewer approval and record the exact SDK revision.
8. Propose provider resources/data sources, registration, unit/acceptance tests, documentation, and a Reno note.
9. Run provider validation and offline regression evaluation.
10. Run credentialed online evaluation in a protected GitHub environment.
11. Produce two reviewable PRs and an evidence manifest; never auto-merge.

The included `Governed OTC change` workflow executes the safe intake and repository/evidence gates. The isolated patch worker contract and continuation events are described in [docs/workflow.md](docs/workflow.md). This separation prevents untrusted issue text from entering a job that holds repository-write or cloud credentials.

## Design documents

- [Architecture and trust boundaries](docs/architecture.md)
- [End-to-end workflow and GitHub setup](docs/workflow.md)
- [Threat model](docs/security.md)
- [Evaluations and quality gates](docs/evaluations.md)
- [Operations, SLOs, telemetry, and failure runbooks](docs/operations.md)
- [Service mapping strategy and table](docs/service-catalog.md)
- [APIGW/FGS implementation conventions](docs/reference-conventions.md)
- [Position requirements traceability](docs/requirements-traceability.md)

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
