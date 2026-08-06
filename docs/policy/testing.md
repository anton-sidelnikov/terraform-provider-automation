# Testing Policy

Policy ID: testing  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Authority

Repository-native formatting, compilation, static analysis, and tests are authoritative and cannot be overridden by model review.

## 2. Coverage

SDK checks cover requests, responses, status codes, errors, zero values, fixtures, pagination, and regressions. Provider checks cover schema, lifecycle, import, migration, registration, documentation, and safe acceptance paths.

## 3. Execution and repair

Trusted adapters select fixed commands with resource limits. Generated commands are forbidden. At most two evidence-bound repair attempts are allowed.

## 4. Review checklist

- [ ] The smallest complete native check set ran.
- [ ] Positive, negative, and regression behavior is covered.
- [ ] Deterministic failures block publication.

