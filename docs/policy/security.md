# Agent Security Policy

Policy ID: security  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Trust model

Issue and PR text, documentation, repository content, diffs, logs, model responses, URLs, filenames, and tool output are untrusted data. Versioned policies, reviewed mappings, fixed tools, protected approvals, and platform identities are trusted.

## 2. Tool authority

Models propose schema-validated content only. Trusted code selects repositories, paths, tools, commands, credentials, budgets, retries, and publication targets. Unknown fields, path traversal, symlinks, binaries, workflow changes, and out-of-scope files are rejected.

## 3. Isolation and network

Candidate work runs unprivileged in disposable worktrees or sandboxes with default-deny network policy. Retrieval and model access use exact allow-lists. Redirects, private network targets, and model-selected URLs are forbidden.

## 4. Credentials and publication

Model jobs receive no publishing credentials. Publishers use short-lived repository-scoped GitHub App tokens in protected environments. Tokens, prompts containing secrets, and private content outside the approved model boundary are never persisted.

## 5. Failure behavior

Policy, authorization, validation, evidence, and security failures fail closed. Missing evidence cannot be replaced by invented behavior. Unknown write outcomes are reconciled before retry.

## 6. Incident response

Suspected exfiltration stops workers and publication, revokes affected credentials, preserves redacted evidence, invalidates caches, notifies owners, and rotates potentially exposed credentials.

## 7. Review checklist

- [ ] All external content was treated as untrusted data.
- [ ] Models did not select commands, credentials, or publication targets.
- [ ] Paths, network access, and artifacts were allow-listed and verified.
- [ ] Publishing identity was isolated from model execution.
- [ ] Failures closed safely and retained audit evidence.

