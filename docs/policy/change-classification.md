# Change Classification Policy

Policy ID: change-classification  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Authority

Trusted deterministic code classifies changes. Caller and model-provided kinds are hints and cannot override catalog or repository evidence.

## 2. Kinds

Use `new_service` for an eligible unmapped service, `feature` for a new operation, `fix` for corrected behavior, `update` for additive fields, and `refactoring` for repository-confirmed legacy layout migration.

## 3. Evidence and confidence

Repository evidence takes precedence over request wording. Generation requires confidence of at least `0.70`; ambiguity blocks rather than guesses.

## 4. Review checklist

- [ ] The kind matches trusted evidence.
- [ ] Hints did not override repository analysis.
- [ ] Confidence meets the required threshold.

