# Pull Request Policy

Policy ID: pull-requests  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Issue and scope

An open approved issue is required and referenced with `For #<issue>`. Approval is represented by the exact `agent-approved` label unless repository policy configures another label through `OTC_APPROVED_ISSUE_LABEL`. SDK pull requests contain exactly one route. A multi-route PR is permitted only when the approved issue also carries the exact `agent-multi-route-approved` label, configurable through `OTC_ROUTE_SCOPE_EXCEPTION_LABEL`. Their bodies link the service landing page and API reference on the authoritative `docs.otc.t-systems.com` portal, derived from the reviewed documentation repository mapping.

Dependent pull requests use the upstream Zuul convention `Depends-On: <pull-request-url>`, once per dependency. Only exact GitHub pull-request URLs are accepted.

## 2. Branch and history

Automation uses an `agent/*` branch from a captured base SHA. Before every publication, Git ancestry verification requires the candidate head to descend from that base and, for review updates, from the previously published head. Review changes append at least one commit; non-fast-forward updates, force pushes, and branch replacement are forbidden.

## 3. Evidence

The body includes documentation links and canonical machine-readable metadata bound to the verified artifact. Metadata records author and publisher skill identities, policy versions, artifact/patch/workflow hashes, repository/documentation/base/head revisions, issue and route scope, and fast-forward-only publication mode.

## 4. Continuation

Feedback updates the existing branch and pull request. Automation never closes and recreates a pull request to avoid review.

## 5. Review checklist

- [ ] Issue, documentation, and evidence are linked.
- [ ] Scope is one route or an approved exception.
- [ ] Review updates preserve branch and history.
