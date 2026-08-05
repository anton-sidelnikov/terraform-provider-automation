# APIGW and FGS reference conventions

The design was checked against the live [SDK](https://github.com/opentelekomcloud/gophertelekomcloud), [provider](https://github.com/opentelekomcloud/terraform-provider-opentelekomcloud), [API Gateway docs](https://github.com/opentelekomcloud-docs/api-gateway), and [FunctionGraph docs](https://github.com/opentelekomcloud-docs/function-graph) repositories on 2026-08-05. References must still be resolved at a commit and re-inspected for every run.

## SDK

APIGW demonstrates a broad, consistent hierarchy under `openstack/apigw/v2/<subresource>` with separate `Create.go`, `Get.go`, `List.go`, `Update.go`, `Delete.go`, association, pagination, and feature operations. Use it as the primary reference for CRUD decomposition, URL construction, request options, list/pagination behavior, and nested API resources.

FGS demonstrates configuration and event-oriented APIs under `openstack/fgs/v2`, including aliases, async configuration, dependencies, events, function code/metadata, invocation, quotas, reserved instances, tags, triggers, and utility operations. Use it for pointer fields where false/zero is meaningful, async configuration, event triggers, and function lifecycle patterns.

For each new SDK operation, the proposal must verify:

- package/version/subresource location and exported naming;
- options structs, `required` behavior, JSON/query tags, and pointer use for meaningful zero values;
- endpoint segments and project-scoping behavior;
- accepted HTTP status codes and body/no-body extraction;
- list response and pagination semantics;
- tests for request method/path/body/query/headers, response decoding, errors, and regression behavior.

Do not mechanically copy either service. The API reference for the target service controls behavior; APIGW/FGS control structure and style.

## Terraform Provider

The provider keeps implementations in `opentelekomcloud/services/<abbr>`, acceptance tests in `opentelekomcloud/acceptance/<abbr>`, user documentation in `docs/resources` and `docs/data-sources`, and release notes in `releasenotes/notes`.

APIGW is the stronger reference for a multi-resource service with resource/data-source registration and dedicated acceptance coverage. FGS is the stronger reference for event/configuration resources, sensitive function configuration, and state updates. A proposal must inspect current files rather than assume their historical names are correct; existing typos or legacy patterns are not templates.

Provider documentation must contain front matter/subcategory, a direct API-reference link, description, executable HCL example, argument reference, attribute reference, import syntax when supported, and timeouts where applicable. Every schema field must appear in the appropriate docs section and vice versa. A Reno YAML note belongs in the correct category (`features`, `fixes`, `upgrade`, `deprecations`, or `other`) and links the provider PR when known.

## Definition of done

An SDK PR with full relevant tests is merged; the provider pins an approved SDK revision; provider unit/acceptance checks pass; documentation and release note validate; offline and online evaluation gates pass; citations and assumptions are complete; and both repository owners approve. “The generated code compiles” alone is never sufficient.
