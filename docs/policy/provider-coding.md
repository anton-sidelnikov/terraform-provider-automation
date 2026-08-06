# Terraform Provider Coding Policy

Policy ID: provider-coding  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. SDK barrier

Provider work starts only from an independently verified, merged SDK pull request and immutable commit SHA.

## 2. Implementation

Schema, CRUD/read behavior, not-found handling, eventual consistency, timeouts, sensitivity, import, migration, and SDK error propagation must match the approved contract.

## 3. Repository surfaces

Changes include the target service, acceptance tests, required registration, matching documentation, and a Reno note. Dependency files are executor-owned.

## 4. Review checklist

- [ ] The SDK revision is approved and pinned.
- [ ] Schema and lifecycle behavior are complete.
- [ ] Tests, documentation, registration, and release note agree.

