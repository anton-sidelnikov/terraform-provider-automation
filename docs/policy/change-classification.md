# Change Classification Policy

Policy ID: change-classification  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Authority

Classification is performed by trusted deterministic code. Caller-provided kinds and model output are hints only and cannot override repository or catalog evidence.

## 2. Change kinds

### 2.1 New service

Use `new_service` only when an eligible documentation repository has no reviewed SDK/provider mapping.

### 2.2 Feature

Use `feature` for a new endpoint, operation, route, or HTTP method/path.

### 2.3 Fix

Use `fix` for a correction to an existing parameter, request, response, status code, or observable behavior.

### 2.4 Update

Use `update` for additive fields or attributes that do not add a new operation.

### 2.5 Refactoring

Use `refactoring` when repository analysis confirms a legacy or mixed SDK layout requiring operation-per-file migration without intended API behavior changes.

## 3. Evidence precedence

Reviewed catalog mappings and repository analysis take precedence over request wording. Revision-pinned API evidence controls API behavior. Ambiguous text must not be converted into a confident classification by a model.

## 4. Confidence and blocking

Generation requires confidence of at least `0.70`. Lower confidence produces a blocked plan with a specific clarification request. Bootstrap and repository-confirmed refactoring classifications may use confidence `1.0`.

## 5. Review checklist

- [ ] The kind matches the definitions in section 2.
- [ ] Repository evidence was considered when available.
- [ ] Caller or model hints did not override trusted evidence.
- [ ] Confidence meets the generation threshold.
- [ ] Ambiguity is surfaced rather than guessed.

