# Pull Request Policy

Policy ID: pull-requests  
Status: Adopted  
Version: 1  
Adopted: 2026-08-06

## 1. Issue prerequisite

An SDK pull request requires an approved GitHub issue and must reference it using the upstream `For #<issue>` convention.

## 2. Branches and commits

Automation uses an `agent/*` branch created from a captured base SHA. Commits are appended during review. Force pushes, history rewrites, and branch replacement are forbidden.

## 3. Pull request scope

SDK pull requests should implement or migrate one API route unless maintainers approve a documented exception. Dependent pull requests use the upstream pending convention and link their dependency.

## 4. Pull request body

The body includes the request, authoritative documentation links, summary, validation, policy references, evidence citations and hashes, source revisions, automation run, classification, and machine-readable metadata.

## 5. Publication and continuation

Pull requests open as drafts and are never auto-merged. Review feedback updates the existing branch and pull request. Automation must not close and recreate a pull request to avoid addressing feedback.

## 6. Review checklist

- [ ] An approved issue is linked using `For #<issue>`.
- [ ] The branch derives from the recorded base SHA.
- [ ] Scope is one route or has an approved exception.
- [ ] Documentation, policy, validation, and evidence links are present.
- [ ] Review updates append commits to the same branch and PR.

