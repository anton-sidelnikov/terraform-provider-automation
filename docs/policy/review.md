# Independent Review Policy

Policy ID: review  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Independence

The reviewer receives frozen requirements, evidence, candidate files or patch, and deterministic diagnostics. It does not receive the author's hidden reasoning or conversation history.

## 2. Reviewer capability

The reviewer model route must be equal to or stronger than the author route. A model may not approve its own output without an independent review invocation.

## 3. Review scope

Review checks evidence coverage, policy compliance, API behavior, compatibility, tests, security, path scope, documentation, and unresolved assumptions. High-risk authentication, endpoint, destructive, migration, import, retry, pagination, and networking changes require specialist or human review.

## 4. Findings

Findings are structured, evidence-linked, severity-ranked, and actionable. A reviewer cannot modify code. Conflicts between evidence, specification, and implementation block publication.

## 5. Repair and approval

At most two bounded repair rounds are allowed. Each round preserves its input, findings, patch, diagnostics, and outcome. Human approval remains mandatory at protected publication boundaries.

## 6. Review checklist

- [ ] Review used frozen artifacts without author conversation history.
- [ ] Reviewer capability met or exceeded author capability.
- [ ] Findings cite evidence, policy, or deterministic diagnostics.
- [ ] High-risk areas received the required specialist or human review.
- [ ] Repair history and final approval are auditable.

