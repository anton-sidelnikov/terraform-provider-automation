# Position requirements traceability

| `position.md` expectation | Design/implementation evidence |
|---|---|
| Reusable repository analysis and dependency discovery | Reviewed catalog, retrieval broker design, SDK-first state machine |
| Prompts, tools, retrieval, routing, evaluation, retries, approval | Architecture components, failure matrix, GitHub protected environments, offline/online harnesses |
| Git/CI/docs/test/service-catalog integration | Three-repository workflow, `config/services.json`, Actions workflows, evidence bundle |
| Auditable outputs and source references | Commit/path/line/hash evidence model, immutable plan, artifact retention |
| Compare model families | Model gateway/routing contract and versioned online evaluation baseline |
| Python/APIs/orchestration/RAG/tool calling | Dependency-light Python control plane plus isolated model/retrieval/tool adapters |
| Clear logging/error handling/configuration | JSON redaction, metrics, trace correlation, budgets, retry classifier, mapping validation |
| CI/CD, containers, Kubernetes | Pinned CI workflow and production deployment guidance/default-deny boundaries |
| Documentation and evidence packs | This documentation set and required evidence manifest |
| Confidentiality-sensitive human review | No secrets in model jobs, environment approvals, draft PRs, no auto-merge |

