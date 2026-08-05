# Threat model

## Trust boundaries

Untrusted inputs include issue/PR text, API documentation, repository source, diffs, test logs, model responses, tool output, URLs, filenames, and retrieved chunks. Trusted inputs are versioned policy, reviewed service mappings, fixed tool definitions, protected-environment approvals, and identities issued by the deployment platform.

| Threat | Required control | Failure behavior |
|---|---|---|
| Prompt injection in docs or issues | Treat content as quoted data; isolate policy; scan signals; no model-selected tools | Quarantine, warn, require security review |
| Command/path injection | Fixed argv tools; path allow-list; no shell interpolation; disposable worktree | Reject output before write |
| SSRF | HTTPS and exact-host allow-list; resolve/check all addresses; block redirects to other hosts and private ranges | Block retrieval |
| Secret exfiltration | No secrets in model jobs; egress allow-list; redaction; canary secret tests | Revoke token and stop run |
| Supply-chain compromise | Pin actions by SHA, Python version, source commits, model/prompt versions; verify artifact hashes | Block promotion |
| Poisoned retrieval/index | Commit-pinned sources, content hashes, provenance metadata, api-ref-only rule | Rebuild or block |
| Excessive agency | Separate planner, executor, and publisher identities; human environment approvals | No PR/merge |
| Resource/cost exhaustion | Input/output limits, per-run token/cost/time budgets, concurrency caps | Checkpoint then stop |
| Cross-tenant data leak | Namespace indexes/runs, tenant-scoped encryption and identity | Fail closed |
| Malicious generated test | Tests execute unprivileged, network-disabled, read-only credentials, cgroup/seccomp limits | Destroy sandbox |

## GitHub Actions rules

- Fork PR workflows are credential-free and use `persist-credentials: false`.
- Never use `pull_request_target` to execute contributor-controlled code.
- Pin every third-party action to a full commit SHA; Dependabot proposes updates.
- Put online credentials in the `online-evaluation` environment and publishing credentials in separate `sdk-publish`/`provider-publish` environments.
- Use a GitHub App installation token scoped to `contents:write` and `pull_requests:write` only for the publisher job. The model worker never receives it.
- Apply branch protection: required CI/evaluation checks, CODEOWNERS approval, signed commits where supported, no force pushes, and no workflow-file changes from the patch worker.
- Treat Actions artifacts as untrusted until the downstream job verifies the recorded SHA-256 digest and originating run/revision.

## Model safety policy

System policy must say that evidence may contain instructions and those instructions have no authority. Require structured output and reject unknown fields. Never expose environment variables, credentials, private repository content outside the approved model boundary, or chain-of-thought. Store concise rationales, citations, and explicit assumptions instead.

High-risk changes always need specialist review: authentication/signing, endpoints/regions, destructive deletes, force-new/schema migrations, state upgrades, import identifiers, retry/idempotency behavior, pagination, security groups/networking, and any workflow or dependency change.

## Incident response

On suspected exfiltration: stop workers, revoke the workload/GitHub/model credentials, preserve redacted audit events, identify affected run and evidence hashes, invalidate caches, notify repository owners, and rotate any potentially exposed credentials. Do not delete evidence until the security owner releases it.

