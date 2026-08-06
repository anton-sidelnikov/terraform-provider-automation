# Policy registry

Policy documents are adopted behavioral contracts for deterministic code and agent skills. Skills must reference policies by policy ID and version rather than copying requirements into prompts.

| Policy ID | Contract |
|---|---|
| `change-classification` | Change kinds, evidence precedence, and blocking rules |
| `sdk-coding` | SDK implementation and operation-per-file requirements |
| `sdk-layout` | Legacy layout detection and migration safety |
| `provider-coding` | Terraform Provider implementation requirements |
| `testing` | Deterministic validation and test coverage |
| `pull-requests` | Issue, branch, commit, and PR lifecycle requirements |
| `review` | Independent review, repair, and approval requirements |
| `security` | Trust boundaries, tool authority, credentials, and failure behavior |

Every policy must declare `Policy ID`, `Status`, `Version`, and `Adopted` metadata, use numbered sections, and end with a review checklist.

