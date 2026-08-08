# Temporal Evaluation

Decision: Defer adoption  
Date: 2026-08-08  
Review after: durable execution is operated by multiple concurrent workers or the triggers below are met

## Context

The governed workflow now has versioned skill contracts, a fixed hash-linked stage chain, bounded repair, explicit approvals, optimistic run transitions, request-bound idempotency keys, verified resume checkpoints, GitHub write reconciliation, and a durable webhook queue with dead-letter handling. Execution remains local-first, with PostgreSQL preferred and local MySQL supported when PostgreSQL is unavailable.

Temporal would add durable workflow histories, timers, activity retries, task queues, worker coordination, and visibility. It would also add a continuously operated service, a second persistence model, workflow-versioning constraints, worker deployment and upgrade procedures, and another security boundary around source artifacts and GitHub credentials.

## Decision

Do not add Temporal now.

The current database-backed state machine covers the required behavior:

| Requirement                  | Current mechanism              |
|------------------------------|--------------------------------|
| Durable stage progress       | Run and stage records          |
| Concurrent transition safety | Compare-and-swap run version   |
| Retry deduplication          | Request-bound idempotency keys |
| Crash recovery               | Verified checkpoint resume     |
| External write uncertainty   | Git and GitHub reconciliation  |
| Event intake                 | Delivery-ID webhook inbox      |
| Retry and poison events      | Delayed queue and dead letter  |
| Local operation              | PostgreSQL or local MySQL      |

Temporal does not currently remove enough custom logic to justify operating it. Policies, artifact hashes, repository validation, independent review, and GitHub reconciliation would remain application responsibilities. Requiring a Temporal server would also weaken the local MySQL fallback and make simple local runs dependent on additional infrastructure.

## Adoption triggers

Reevaluate Temporal when at least two of these conditions are sustained:

1. Multiple workers must coordinate the same run across hosts.
2. Runs commonly wait for hours or days on approvals, timers, or external callbacks.
3. Database queue contention or recovery incidents exceed the operating SLO.
4. Workflows require substantial fan-out/fan-in beyond the fixed SDK/provider stage chain.
5. Operators need workflow-level search, replay, cancellation, and visibility that the current audit tables cannot provide economically.
6. PostgreSQL becomes mandatory for all execution environments and the local MySQL fallback is retired.

Before adoption, the stage/event schema must remain backward compatible for two release cycles, every activity must have an idempotency key and reconciliation contract, and migration from existing durable runs must be demonstrated.

## Constraints for a future adoption

- Temporal may orchestrate trusted activities but may not replace policy, artifact, review, or publication checks.
- Source snapshots and evidence remain in repository/object storage; workflow history stores references and hashes, not unrestricted source or secrets.
- GitHub writes remain separate idempotent activities with observed-state reconciliation.
- Model calls remain bounded activities with recorded routing, budget, and evidence.
- Workflow versioning must support in-flight runs during upgrades.
- Temporal deployment must be optional for local development until an approved decision explicitly removes the local database executor.

## Consequences

The project continues with the existing PostgreSQL/MySQL durable executor and webhook queue. Temporal-related dependencies, deployment manifests, and workers are intentionally excluded. This decision should be revisited only against measured operating data and the triggers above.
