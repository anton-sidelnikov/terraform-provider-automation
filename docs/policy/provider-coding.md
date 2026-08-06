# Terraform Provider Coding Policy

Policy ID: provider-coding  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. SDK dependency barrier

Provider generation may begin only from a reviewed and merged SDK pull request with an independently verified immutable commit SHA.

## 2. Repository structure

Implementations belong under `opentelekomcloud/services/<service>/`, acceptance tests under `opentelekomcloud/acceptance/<service>/`, user documentation under `docs/resources/` or `docs/data-sources/`, and release notes under `releasenotes/notes/`.

## 3. Schema and lifecycle

Schemas must define correct types, validators, sensitivity, defaults, conflicts, `ForceNew`, and timeout behavior. CRUD and read paths must handle not-found state, eventual consistency, SDK errors, import identifiers, and state migration where applicable.

## 4. Documentation and release notes

Documentation must include an API-reference link, executable example, argument and attribute parity, import syntax when supported, and timeouts when applicable. A Reno note must use the correct category and describe user-visible behavior.

## 5. Scope

The patch may change only the target service, its acceptance tests, required registration, matching documentation, release notes, and executor-owned SDK dependency files. Unrelated dependency or formatting updates are forbidden.

## 6. Review checklist

- [ ] The SDK merge and immutable revision were verified.
- [ ] Schema and lifecycle behavior match the approved contract.
- [ ] Not-found, import, migration, timeout, and sensitive-state behavior were considered.
- [ ] Documentation matches every schema field.
- [ ] Acceptance coverage and a valid Reno note are present.

