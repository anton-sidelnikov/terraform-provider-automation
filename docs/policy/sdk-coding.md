# SDK Coding Policy

Policy ID: sdk-coding  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Authority

Revision-pinned API references control behavior. SDK `FAQ.md`, `STYLEGUIDE.md`, contribution guidance, and current examples control structure.

## 2. Structure

Code belongs under `openstack/<service>/<version>/<resource>/`. Public operations use PascalCase operation-named files, with operation-local options, responses, and helpers colocated.

## 3. Behavior

Requests, queries, URLs, status codes, response extraction, errors, meaningful zero values, and pagination must follow repository-native patterns and cited evidence.

## 4. Scope

Changes remain inside the reviewed service and preserve compatibility unless an approved specification authorizes a behavior change.

## 5. Review checklist

- [ ] API behavior is cited.
- [ ] File and type layout follows current conventions.
- [ ] Request, response, error, and pagination behavior are covered.

