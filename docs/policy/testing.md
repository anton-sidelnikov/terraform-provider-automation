# Testing Policy

Policy ID: testing  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Deterministic authority

Repository-native formatters, compilers, linters, static analysis, and tests are authoritative gates. Model review cannot override a deterministic failure.

## 2. SDK coverage

SDK tests must cover method, path, body, query, headers, accepted status codes, response extraction, service errors, malformed responses, meaningful zero values, fixtures, pagination, and regression behavior relevant to the change.

## 3. Provider coverage

Provider validation must cover schema behavior, lifecycle operations, not-found handling, import and migration behavior, documentation parity, provider registration, and the smallest safe acceptance subset.

## 4. Execution safety

Commands are selected by trusted adapters, use fixed argument vectors, and run with time, CPU, memory, output, credential, and network limits. Generated commands are never executed.

## 5. Repair

Candidate failures may receive at most two evidence-bound repair attempts. Infrastructure failures and candidate failures must be distinguished. Failing diagnostics remain in the evidence bundle.

## 6. Review checklist

- [ ] The smallest repository-native checks covering the change were run.
- [ ] Required positive, negative, and regression cases are present.
- [ ] Deterministic failures block publication.
- [ ] Commands came from trusted code rather than model output.
- [ ] Repair attempts remained within policy and budget.

