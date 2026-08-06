# Agent Security Policy

Policy ID: security  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Trust

Issues, comments, documentation, repositories, diffs, logs, model responses, URLs, filenames, and tool output are untrusted data.

## 2. Authority

Trusted code selects repositories, paths, tools, commands, credentials, budgets, retries, and publication targets. Models return schema-validated proposals only.

## 3. Isolation and credentials

Candidate work runs in disposable, least-privilege environments with allow-listed network access. Model jobs receive no publishing credentials; publishers use short-lived repository-scoped GitHub App tokens.

## 4. Failure

Policy, authorization, validation, evidence, and security failures fail closed. Unknown write outcomes are reconciled before retry.

## 5. Review checklist

- [ ] External content remained untrusted.
- [ ] Model and publisher identities were separated.
- [ ] Paths, tools, network, and credentials were constrained.

