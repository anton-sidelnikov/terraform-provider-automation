# OTC Terraform Provider Agent

This repository is a governed reference implementation for automating OpenTelekomCloud SDK and Terraform Provider changes. It converts a change request into an auditable, SDK-first delivery plan, maps provider/SDK abbreviations to an authoritative documentation repository, applies security and budget policy, and gates promotion with offline and online evaluations.

The central invariant is:

> No provider change is generated or published until the required `gophertelekomcloud` change, its tests, and its immutable commit SHA have been reviewed and approved.

Authoritative upstreams: [gophertelekomcloud](https://github.com/opentelekomcloud/gophertelekomcloud), [terraform-provider-opentelekomcloud](https://github.com/opentelekomcloud/terraform-provider-opentelekomcloud), and the [OpenTelekomCloud documentation organization](https://github.com/opentelekomcloud-docs).

The repository implements the control plane, secure intake, automatic change classification, api-ref retrieval, an OpenAI-compatible patch worker, path-confined diff application, repository-native validation, evidence manifests, GitHub App publishers, health/metrics API, failure policy, and evaluation harness. Model jobs cannot access publishing credentials, choose repositories, execute model-supplied commands, merge changes, or bypass approval environments.

## Quick start

Python 3.12 or 3.13 is sufficient; the runtime has no third-party dependencies.

```bash
make check

PYTHONPATH=src python -m otc_agent.cli plan \
  --docs-repository modelarts \
  --description "Create complete SDK and provider support from the API reference" \
  --output build/change-plan.json

PYTHONPATH=src python -m otc_agent.cli analyze-sdk-layout \
  --sdk-root ../gophertelekomcloud \
  --service apigw

PYTHONPATH=src python -m otc_agent.cli serve --host 127.0.0.1 --port 8080
```

The service exposes `POST /v1/plans`, `GET /healthz`, `GET /readyz`, and Prometheus-format `GET /metrics`.

## What is automated

1. Validate and quarantine the untrusted request and the manually selected documentation repository.
2. Resolve the reviewed SDK/provider/docs mapping. Only repositories containing `api-ref/source/index.rst` are eligible.
3. Independently classify the request: `feature` for a new endpoint/operation, `fix` for changed parameters/request/response, `update` for additive attributes, and `new_service` for an unmapped service.
4. If no mapping exists, propose an abbreviation from the repository slug and require approval before creating the SDK service completely.
5. Retrieve revision-pinned API evidence and APIGW/FGS examples.
6. Generate the SDK diff and its request/response, error, fixture, and pagination tests.
7. Run SDK format, vet, and unit checks; preserve diagnostics and patch digest.
8. After publisher approval, mint a repository-scoped App token and open a draft SDK PR.
9. After that PR is merged, manually continue with the provider workflow, which verifies SDK PR metadata and commit SHA.
10. Generate provider resources/data sources, registration, acceptance tests, documentation, and a Reno note; pin the SDK commit.
11. Validate and open a separate draft provider PR; never auto-merge.

`Generate SDK pull request` performs intake through draft SDK PR. After the SDK PR is reviewed and merged, `Generate provider pull request` verifies it and performs the provider half. See [docs/workflow.md](docs/workflow.md). This separation prevents untrusted issue/model content from entering a job that holds repository-write credentials.

## Design documents

- [Architecture and trust boundaries](docs/architecture.md)
- [End-to-end workflow and GitHub setup](docs/workflow.md)
- [Threat model](docs/security.md)
- [Evaluations and quality gates](docs/evaluations.md)
- [Operations, SLOs, telemetry, and failure runbooks](docs/operations.md)
- [Service mapping strategy and table](docs/service-catalog.md)
- [APIGW/FGS implementation conventions](docs/reference-conventions.md)
- [Position requirements traceability](docs/requirements-traceability.md)
- [Implementation roadmap and task tracker](tasks.md)
- [Versioned policy registry](docs/policy/README.md)

Governed skills are declared in [`config/skills.json`](config/skills.json). Run `otc-agent policy-check` and `otc-agent skill-check` to validate policy and skill contracts.

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
