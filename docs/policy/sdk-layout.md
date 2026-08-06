# SDK Layout Policy

Status: Adopted  
Version: 1  
Adopted: 2026-08-06
Policy ID: sdk-layout

## 1. Scope

This policy governs analysis and migration of service packages under `openstack/<service>/` in `gophertelekomcloud`. It is derived from the repository's revision-pinned `FAQ.md` and `STYLEGUIDE.md`.

## 2. Modern operation layout

### 2.1 Operation files

Each public API operation must live in a file named after its exported operation function, such as `Create.go`, `List.go`, `GetMetadata.go`, or `UpdateEIP.go`.

### 2.2 Operation-local types

Request options, response types, extraction helpers, and small helper types used by only one operation should remain in that operation's file.

### 2.3 Shared types

Types may remain in a common file only when they are reused broadly enough that colocating them would reduce readability or introduce duplication.

## 3. Legacy layout detection

### 3.1 Generic files are signals

Files such as `request.go`, `requests.go`, `urls.go`, and `results.go` are legacy-layout signals, but filenames alone do not prove that a package requires migration.

### 3.2 Operation evidence

A package requires refactoring when exported API operation functions are implemented in generic legacy files instead of corresponding operation-named files.

### 3.3 Mixed packages

A package containing both operation-named implementations and operations in generic legacy files is a mixed layout and requires a scoped migration plan for the remaining legacy operations.

## 4. Classification

Changes involving a confirmed legacy or mixed layout must be classified as `refactoring`. Text-only request classification must not override repository evidence.

## 5. Migration safety

### 5.1 Compatibility

Refactoring must preserve exported function signatures and observable API behavior unless an approved specification explicitly authorizes a behavior change.

### 5.2 Tests

Migration validation must cover request construction, URLs, status codes, response extraction, errors, meaningful zero values, fixtures, and pagination where applicable.

### 5.3 Scope

Refactoring patches must not introduce unrelated endpoint or contract changes.

## 6. Review checklist

- [ ] Every migrated public operation has a matching operation-named file.
- [ ] Operation-local types moved with their operation.
- [ ] Shared types remain common only when reused.
- [ ] Exported compatibility is preserved.
- [ ] Legacy generic files are removed when empty.
- [ ] Existing and migration-specific tests pass.
- [ ] The pull request is limited to a reviewable API route or approved exception.
