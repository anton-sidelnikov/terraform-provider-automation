# SDK Coding Policy

Policy ID: sdk-coding  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Source authority

Revision-pinned `api-ref/**` content controls endpoint and payload behavior. SDK `FAQ.md`, `STYLEGUIDE.md`, contribution guidance, and current repository examples control structure and style.

## 2. Package and file structure

Service code belongs under `openstack/<service>/<version>/<resource>/`. Public operations use exported PascalCase names and operation-named files. Operation-local options, responses, and helpers remain with the operation; widely reused types may be shared.

## 3. Requests

Request bodies use operation-specific option structs and repository-native request builders. URL-only fields use `json:"-"`. Query parameters use `q` tags and the repository query builder. Required, optional, and meaningful zero values must be represented explicitly.

## 4. Responses and errors

Response structs use API payload JSON tags and repository-native extraction helpers. Accepted status codes, empty bodies, malformed bodies, and service errors must be handled consistently with current SDK conventions.

## 5. Scope and compatibility

Patches are confined to the reviewed service. Refactoring preserves exported signatures and observable behavior unless an approved specification explicitly authorizes change. Unrelated formatting, dependency, workflow, or generated binary changes are forbidden.

## 6. Review checklist

- [ ] Every behavior is supported by revision-pinned API evidence.
- [ ] Package, operation, options, and response naming follow repository conventions.
- [ ] URL, body, query, status, extraction, and error behavior are explicit.
- [ ] Meaningful zero values and pagination are handled where applicable.
- [ ] The patch is confined to the approved service and change scope.

