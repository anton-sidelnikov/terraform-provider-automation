from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .state import ResumeCheckpoint


class ResumeError(ValueError):
    pass


@dataclass(frozen=True)
class ResumeValidation:
    repository_root: str
    source_sha: str
    branch_sha: str | None
    artifact_path: str
    artifact_sha256: str
    documentation_root: str | None
    documentation_revision: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def revalidate_resume_checkpoint(
    *,
    checkpoint: ResumeCheckpoint,
    repository_root: Path,
    artifact_path: Path,
    documentation_root: Path | None = None,
    runner: CommandRunner | None = None,
) -> ResumeValidation:
    command_runner = runner or subprocess.run
    _regular_directory(repository_root, "repository")
    _git_commit(command_runner, repository_root, checkpoint.source_sha)
    if checkpoint.checkpoint_source_sha != checkpoint.source_sha:
        raise ResumeError("checkpoint source revision does not match the durable run")
    if checkpoint.branch_name or checkpoint.branch_sha:
        if not checkpoint.branch_name or not checkpoint.branch_sha:
            raise ResumeError("durable branch name and SHA must be recorded together")
        branch_sha = _git_output(
            command_runner,
            repository_root,
            "rev-parse",
            f"refs/heads/{checkpoint.branch_name}",
        )
        if branch_sha != checkpoint.branch_sha or checkpoint.checkpoint_branch_sha != branch_sha:
            raise ResumeError("repository branch no longer matches the durable checkpoint")
        _git_ancestor(command_runner, repository_root, checkpoint.source_sha, branch_sha)
    artifact = _load_checkpoint_artifact(artifact_path, checkpoint.artifact_sha256)
    if artifact.get("stage") != checkpoint.checkpoint_stage:
        raise ResumeError("checkpoint artifact stage does not match the durable checkpoint")
    documentation_revision = checkpoint.payload.get("documentation_revision")
    validated_documentation_root = None
    if documentation_revision is not None:
        if not isinstance(documentation_revision, str) or len(documentation_revision) != 40:
            raise ResumeError("checkpoint documentation revision is invalid")
        if documentation_root is None:
            raise ResumeError("documentation checkout is required to resume this run")
        _regular_directory(documentation_root, "documentation")
        _git_commit(command_runner, documentation_root, documentation_revision)
        if _git_output(command_runner, documentation_root, "rev-parse", "HEAD") != documentation_revision:
            raise ResumeError("documentation checkout no longer matches the checkpoint revision")
        validated_documentation_root = str(documentation_root.resolve())
    return ResumeValidation(
        repository_root=str(repository_root.resolve()),
        source_sha=checkpoint.source_sha,
        branch_sha=checkpoint.branch_sha,
        artifact_path=str(artifact_path.resolve()),
        artifact_sha256=checkpoint.artifact_sha256,
        documentation_root=validated_documentation_root,
        documentation_revision=documentation_revision,
    )


def _load_checkpoint_artifact(path: Path, expected_sha256: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        raise ResumeError("checkpoint artifact must be a bounded regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResumeError("checkpoint artifact must contain valid UTF-8 JSON") from exc
    candidates = value.get("workflow_artifacts") if isinstance(value, dict) else None
    if isinstance(candidates, list):
        value = next(
            (
                item
                for item in candidates
                if isinstance(item, dict) and item.get("artifact_sha256") == expected_sha256
            ),
            None,
        )
    if not isinstance(value, dict):
        raise ResumeError("checkpoint artifact was not found in the supplied file")
    required = {
        "schema_version",
        "workflow_version",
        "stage",
        "previous_sha256",
        "payload",
        "payload_sha256",
        "artifact_sha256",
    }
    if set(value) != required or value["artifact_sha256"] != expected_sha256:
        raise ResumeError("checkpoint artifact fields or identity do not match")
    payload_json = json.dumps(value["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    if payload_sha256 != value["payload_sha256"]:
        raise ResumeError("checkpoint artifact payload hash does not match")
    envelope = {
        "schema_version": value["schema_version"],
        "workflow_version": value["workflow_version"],
        "stage": value["stage"],
        "previous_sha256": value["previous_sha256"],
        "payload_sha256": value["payload_sha256"],
    }
    artifact_sha256 = hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    if artifact_sha256 != expected_sha256:
        raise ResumeError("checkpoint artifact hash does not match")
    return value


def _regular_directory(path: Path, name: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ResumeError(f"{name} checkout must be a regular directory")


def _git_commit(runner: CommandRunner, root: Path, revision: str) -> None:
    _git_output(runner, root, "cat-file", "-e", f"{revision}^{{commit}}")


def _git_ancestor(runner: CommandRunner, root: Path, ancestor: str, descendant: str) -> None:
    result = _git(runner, root, "merge-base", "--is-ancestor", ancestor, descendant, allowed=(0, 1))
    if result.returncode != 0:
        raise ResumeError("durable source revision is not an ancestor of the branch checkpoint")


def _git_output(runner: CommandRunner, root: Path, *arguments: str) -> str:
    return _git(runner, root, *arguments).stdout.strip()


def _git(
    runner: CommandRunner,
    root: Path,
    *arguments: str,
    allowed: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            ["git", "-C", str(root), *arguments],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResumeError("unable to revalidate resume revision") from exc
    if result.returncode not in allowed:
        raise ResumeError("resume revision revalidation failed")
    return result
