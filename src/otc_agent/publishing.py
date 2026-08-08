from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


class PublicationError(ValueError):
    pass


@dataclass(frozen=True)
class IssueApproval:
    repository: str
    number: int
    url: str
    title: str
    state: str
    approval_label: str
    labels: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PublishPreflight:
    repository: str
    base_sha: str
    artifact_path: str
    artifact_sha256: str
    issue: IssueApproval
    routes: tuple[str, ...]
    route_scope_exception_label: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AppendOnlyHistory:
    worktree: str
    base_sha: str
    candidate_head_sha: str
    previous_head_sha: str | None
    push_mode: str = "fast-forward-only"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

_REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})")
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.:/ -]{0,63})")
_ISSUE_DIRECTIVE = re.compile(r"^For #([1-9][0-9]*)[ \t]*$", re.MULTILINE)
_MAX_PULL_REQUEST_BODY_BYTES = 65_536
_DOCUMENTATION_BLOCK_START = "<!-- otc-agent:documentation:start -->"
_DOCUMENTATION_BLOCK_END = "<!-- otc-agent:documentation:end -->"
_METADATA_BLOCK_START = "<!-- otc-agent:metadata:start"
_METADATA_BLOCK_END = "otc-agent:metadata:end -->"
_ROUTE = re.compile(r"[A-Z][A-Za-z0-9]{0,127}")
_DEPENDENCY_DIRECTIVE = re.compile(r"^Depends-On:[ \t]+(\S+)[ \t]*$", re.MULTILINE)
_GITHUB_PULL_REQUEST_URL = re.compile(
    r"https://github\.com/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})/pull/[1-9][0-9]*"
)


def verify_publish_preflight(
    *,
    artifact: Path,
    repository: str,
    base_sha: str,
    issue: int,
    routes: tuple[str, ...],
    approval_label: str | None = None,
    route_scope_exception_label: str | None = None,
    runner: CommandRunner | None = None,
) -> PublishPreflight:
    if not _REPOSITORY.fullmatch(repository):
        raise PublicationError("repository must be an exact owner/name slug")
    if not _COMMIT_SHA.fullmatch(base_sha):
        raise PublicationError("base_sha must be a full lower-case Git commit SHA")
    if not isinstance(issue, int) or isinstance(issue, bool) or issue < 1:
        raise PublicationError("issue must be a positive integer")
    if artifact.is_symlink() or not artifact.is_file():
        raise PublicationError("publish artifact must be a regular file")
    label = approval_label or os.environ.get("OTC_APPROVED_ISSUE_LABEL", "agent-approved")
    if not _LABEL.fullmatch(label):
        raise PublicationError("approval label contains unsupported characters")
    exception_label = route_scope_exception_label or os.environ.get(
        "OTC_ROUTE_SCOPE_EXCEPTION_LABEL",
        "agent-multi-route-approved",
    )
    if not _LABEL.fullmatch(exception_label):
        raise PublicationError("route scope exception label contains unsupported characters")
    artifact_sha256 = _file_sha256(artifact)
    approval = verify_approved_issue(
        repository=repository,
        issue=issue,
        approval_label=label,
        runner=runner,
    )
    approved_exception = verify_sdk_route_scope(
        routes=routes,
        issue=approval,
        exception_label=exception_label,
    )
    return PublishPreflight(
        repository=repository,
        base_sha=base_sha,
        artifact_path=str(artifact.resolve()),
        artifact_sha256=artifact_sha256,
        issue=approval,
        routes=routes,
        route_scope_exception_label=exception_label if approved_exception else None,
    )


def verify_approved_issue(
    *,
    repository: str,
    issue: int,
    approval_label: str,
    runner: CommandRunner | None = None,
) -> IssueApproval:
    command_runner = runner or subprocess.run
    try:
        result = command_runner(
            [
                "gh",
                "issue",
                "view",
                str(issue),
                "--repo",
                repository,
                "--json",
                "number,state,title,url,labels",
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("unable to query the required GitHub issue") from exc
    if result.returncode != 0:
        raise PublicationError("GitHub issue query failed; check authentication and repository access")
    if len(result.stdout.encode("utf-8")) > 1_000_000:
        raise PublicationError("GitHub issue response exceeds the allowed size")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PublicationError("GitHub issue query returned invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"number", "state", "title", "url", "labels"}:
        raise PublicationError("GitHub issue response fields do not match the expected schema")
    if value["number"] != issue:
        raise PublicationError("GitHub issue response number does not match the requested issue")
    if value["state"] != "OPEN":
        raise PublicationError("publication requires an open GitHub issue")
    title = value["title"]
    url = value["url"]
    labels = value["labels"]
    if not isinstance(title, str) or not title or not isinstance(url, str) or not url:
        raise PublicationError("GitHub issue response is missing title or URL")
    if not isinstance(labels, list):
        raise PublicationError("GitHub issue labels must be an array")
    label_names: set[str] = set()
    for item in labels:
        if not isinstance(item, dict) or set(item) - {"id", "name", "description", "color"}:
            raise PublicationError("GitHub issue contains an invalid label")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise PublicationError("GitHub issue label is missing its name")
        label_names.add(name)
    if approval_label not in label_names:
        raise PublicationError(f"GitHub issue is missing required approval label {approval_label!r}")
    return IssueApproval(repository, issue, url, title, value["state"], approval_label, tuple(sorted(label_names)))


def verify_sdk_route_scope(*, routes: tuple[str, ...], issue: IssueApproval, exception_label: str) -> bool:
    if not routes:
        raise PublicationError("SDK publication requires exactly one API route")
    if len(set(routes)) != len(routes):
        raise PublicationError("SDK publication routes must be unique")
    if any(not isinstance(route, str) or not _ROUTE.fullmatch(route) for route in routes):
        raise PublicationError("SDK publication contains an invalid API route")
    if len(routes) == 1:
        return False
    if exception_label not in issue.labels:
        raise PublicationError(
            f"multi-route SDK publication requires issue label {exception_label!r}"
        )
    return True


def verify_append_only_history(
    *,
    worktree: Path,
    base_sha: str,
    candidate_head_sha: str,
    previous_head_sha: str | None = None,
    runner: CommandRunner | None = None,
) -> AppendOnlyHistory:
    if worktree.is_symlink() or not worktree.is_dir():
        raise PublicationError("publish worktree must be a regular directory")
    revisions = (base_sha, candidate_head_sha) + ((previous_head_sha,) if previous_head_sha else ())
    if any(not _COMMIT_SHA.fullmatch(revision) for revision in revisions):
        raise PublicationError("publication history requires full lower-case Git commit SHAs")
    command_runner = runner or subprocess.run
    _run_git(command_runner, worktree, "rev-parse", "--is-inside-work-tree")
    for revision in revisions:
        _run_git(command_runner, worktree, "cat-file", "-e", f"{revision}^{{commit}}")
    if not _is_ancestor(command_runner, worktree, base_sha, candidate_head_sha):
        raise PublicationError("candidate branch does not descend from the captured base SHA")
    if candidate_head_sha == base_sha:
        raise PublicationError("candidate branch does not contain a publication commit")
    if previous_head_sha:
        if not _is_ancestor(command_runner, worktree, previous_head_sha, candidate_head_sha):
            raise PublicationError("candidate branch update is not append-only")
        if previous_head_sha == candidate_head_sha:
            raise PublicationError("candidate branch update does not append a commit")
    return AppendOnlyHistory(
        worktree=str(worktree.resolve()),
        base_sha=base_sha,
        candidate_head_sha=candidate_head_sha,
        previous_head_sha=previous_head_sha,
    )


def _run_git(runner: CommandRunner, worktree: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            ["git", "-C", str(worktree), *arguments],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("unable to verify publication Git history") from exc
    if result.returncode != 0:
        raise PublicationError("publication Git history verification failed")
    return result


def _is_ancestor(runner: CommandRunner, worktree: Path, ancestor: str, descendant: str) -> bool:
    try:
        result = runner(
            ["git", "-C", str(worktree), "merge-base", "--is-ancestor", ancestor, descendant],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("unable to verify publication Git ancestry") from exc
    if result.returncode not in (0, 1):
        raise PublicationError("publication Git ancestry verification failed")
    return result.returncode == 0


def build_sdk_pull_request_body(
    body: str,
    issue: IssueApproval,
    documentation_repository: str,
    dependencies: tuple[str, ...] = (),
    metadata: dict[str, object] | None = None,
) -> str:
    if "\x00" in body:
        raise PublicationError("pull-request body contains a null byte")
    references = tuple(int(match.group(1)) for match in _ISSUE_DIRECTIVE.finditer(body))
    if any(number != issue.number for number in references):
        raise PublicationError("pull-request body references an issue other than the approved issue")
    if len(references) > 1:
        raise PublicationError("pull-request body must contain the approved issue directive exactly once")
    rendered = body.rstrip()
    if not references:
        rendered = f"{rendered}\n\nFor #{issue.number}" if rendered else f"For #{issue.number}"
    documentation_block = _documentation_portal_block(documentation_repository)
    marker_count = rendered.count(_DOCUMENTATION_BLOCK_START) + rendered.count(_DOCUMENTATION_BLOCK_END)
    if marker_count:
        if marker_count != 2 or rendered.count(documentation_block) != 1:
            raise PublicationError("pull-request body contains conflicting documentation portal metadata")
    else:
        rendered = f"{rendered}\n\n{documentation_block}"
    rendered = _render_dependencies(rendered, dependencies)
    if metadata is not None:
        rendered = _render_metadata(rendered, metadata)
    rendered += "\n"
    if len(rendered.encode("utf-8")) > _MAX_PULL_REQUEST_BODY_BYTES:
        raise PublicationError("pull-request body exceeds the allowed size")
    return rendered


def build_publication_metadata(
    *,
    artifact: Path,
    preflight: PublishPreflight,
    history: AppendOnlyHistory,
    publisher_skill: dict[str, object],
) -> dict[str, object]:
    try:
        value = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicationError("publish artifact must contain valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PublicationError("publish artifact JSON must be an object")
    schema_version = _required_int(value, "schema_version")
    workflow_version = _required_int(value, "workflow_version")
    repository_revision = _required_digest(value, "repository_revision")
    documentation_revision = _required_digest(value, "documentation_revision")
    patch_sha256 = _required_digest(value, "patch_sha256")
    policies = _required_policies(value)
    author_skill = value.get("skill")
    if not isinstance(author_skill, dict) or not isinstance(author_skill.get("id"), str):
        raise PublicationError("publish artifact is missing its author skill identity")
    workflow_artifacts = value.get("workflow_artifacts")
    if not isinstance(workflow_artifacts, list) or not workflow_artifacts:
        raise PublicationError("publish artifact is missing workflow artifact evidence")
    final_workflow_artifact = workflow_artifacts[-1]
    if not isinstance(final_workflow_artifact, dict):
        raise PublicationError("publish artifact contains invalid workflow evidence")
    final_workflow_sha256 = _required_digest(final_workflow_artifact, "artifact_sha256")
    return {
        "schema_version": 1,
        "automation": {
            "tool": "otc-agent",
            "author_skill": author_skill,
            "publisher_skill": publisher_skill,
            "workflow_version": workflow_version,
        },
        "evidence": {
            "artifact_sha256": preflight.artifact_sha256,
            "artifact_schema_version": schema_version,
            "patch_sha256": patch_sha256,
            "final_workflow_artifact_sha256": final_workflow_sha256,
        },
        "source_revisions": {
            "repository": repository_revision,
            "documentation": documentation_revision,
            "base": history.base_sha,
            "candidate_head": history.candidate_head_sha,
            "previous_head": history.previous_head_sha,
        },
        "policies": policies,
        "publication": {
            "repository": preflight.repository,
            "issue": preflight.issue.number,
            "routes": list(preflight.routes),
            "route_scope_exception_label": preflight.route_scope_exception_label,
            "push_mode": history.push_mode,
        },
    }


def _render_metadata(body: str, metadata: dict[str, object]) -> str:
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    block = f"{_METADATA_BLOCK_START}\n{canonical}\n{_METADATA_BLOCK_END}"
    marker_count = body.count(_METADATA_BLOCK_START) + body.count(_METADATA_BLOCK_END)
    if marker_count:
        if marker_count != 2 or body.count(block) != 1:
            raise PublicationError("pull-request body contains conflicting automation metadata")
        return body
    return f"{body}\n\n{block}"


def parse_publication_metadata(body: str) -> dict[str, object]:
    start = body.find(_METADATA_BLOCK_START)
    end = body.find(_METADATA_BLOCK_END)
    if start < 0 or end < 0 or body.find(_METADATA_BLOCK_START, start + 1) >= 0:
        raise PublicationError("pull request is missing unique agent automation metadata")
    content_start = start + len(_METADATA_BLOCK_START)
    if end <= content_start or body.find(_METADATA_BLOCK_END, end + 1) >= 0:
        raise PublicationError("pull request contains malformed agent automation metadata")
    content = body[content_start:end].strip()
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PublicationError("pull request contains invalid agent automation metadata") from exc
    if not isinstance(value, dict):
        raise PublicationError("pull request automation metadata must be an object")
    if json.dumps(value, sort_keys=True, separators=(",", ":")) != content:
        raise PublicationError("pull request automation metadata is not canonical")
    return value


def _required_int(value: dict[str, object], field: str) -> int:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or item < 1:
        raise PublicationError(f"publish artifact contains invalid {field}")
    return item


def _required_digest(value: dict[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}|[0-9a-f]{40}", item):
        raise PublicationError(f"publish artifact contains invalid {field}")
    return item


def _required_policies(value: dict[str, object]) -> list[dict[str, object]]:
    policies = value.get("policies")
    if not isinstance(policies, list) or not policies:
        raise PublicationError("publish artifact is missing policy references")
    normalized: list[dict[str, object]] = []
    for policy in policies:
        if not isinstance(policy, dict) or set(policy) != {"id", "version"}:
            raise PublicationError("publish artifact contains an invalid policy reference")
        policy_id = policy["id"]
        version = policy["version"]
        if not isinstance(policy_id, str) or not policy_id or not isinstance(version, int) or isinstance(version, bool):
            raise PublicationError("publish artifact contains an invalid policy reference")
        normalized.append({"id": policy_id, "version": version})
    return sorted(normalized, key=lambda item: str(item["id"]))


def _render_dependencies(body: str, dependencies: tuple[str, ...]) -> str:
    if len(set(dependencies)) != len(dependencies):
        raise PublicationError("dependent pull requests must be unique")
    if any(not isinstance(url, str) or not _GITHUB_PULL_REQUEST_URL.fullmatch(url) for url in dependencies):
        raise PublicationError("dependency must be an exact GitHub pull-request URL")
    existing = tuple(match.group(1) for match in _DEPENDENCY_DIRECTIVE.finditer(body))
    if existing:
        if existing != dependencies:
            raise PublicationError("pull-request body contains conflicting Depends-On directives")
        return body
    if not dependencies:
        return body
    directives = "\n".join(f"Depends-On: {url}" for url in dependencies)
    return f"{body}\n\n{directives}"


def _documentation_portal_block(repository: str) -> str:
    service_url = f"https://docs.otc.t-systems.com/{repository}/"
    api_reference_url = f"{service_url}api-ref/index.html"
    return "\n".join(
        (
            _DOCUMENTATION_BLOCK_START,
            "## Authoritative documentation",
            "",
            f"- [Service documentation]({service_url})",
            f"- [API reference]({api_reference_url})",
            _DOCUMENTATION_BLOCK_END,
        )
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
