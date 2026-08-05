from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


class PatchViolation(ValueError):
    pass


@dataclass(frozen=True)
class PatchPolicy:
    allows: Callable[[str], bool]
    max_bytes: int = 500_000
    max_files: int = 80


def validate_patch(patch: str, policy: PatchPolicy) -> tuple[str, ...]:
    encoded = patch.encode("utf-8")
    if not patch or len(encoded) > policy.max_bytes:
        raise PatchViolation("patch is empty or exceeds its byte limit")
    if "GIT binary patch" in patch or "Binary files " in patch:
        raise PatchViolation("binary patches are forbidden")
    paths = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", patch, re.MULTILINE):
        left, right = match.groups()
        if left != right:
            raise PatchViolation("renames and copies are forbidden")
        _validate_path(right)
        if not policy.allows(right):
            raise PatchViolation(f"path {right!r} is outside the stage allow-list")
        paths.append(right)
    if not paths:
        raise PatchViolation("patch contains no diff --git file headers")
    if len(set(paths)) > policy.max_files:
        raise PatchViolation("patch changes too many files")
    return tuple(dict.fromkeys(paths))


def apply_patch(root: Path, patch: str, policy: PatchPolicy) -> tuple[str, ...]:
    paths = validate_patch(patch, policy)
    _git_apply(root, patch, check=True)
    _git_apply(root, patch, check=False)
    for path in paths:
        candidate = root / path
        if candidate.is_symlink():
            raise PatchViolation("generated symlinks are forbidden")
    return paths


def repository_diff(root: Path) -> str:
    # Plain `git diff` omits untracked files. Intent-to-add makes newly
    # generated packages visible without staging their contents for commit.
    prepare = subprocess.run(
        ["git", "add", "--intent-to-add", "--all"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if prepare.returncode != 0:
        raise PatchViolation(f"failed to include new files in candidate diff: {prepare.stderr.strip()[:1000]}")
    result = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD", "--"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    )
    return result.stdout


def sdk_policy(service: str) -> PatchPolicy:
    prefix = f"openstack/{service}/"
    return PatchPolicy(lambda path: path.startswith(prefix) and path.endswith(".go"))


def provider_policy(service: str) -> PatchPolicy:
    service_prefix = f"opentelekomcloud/services/{service}/"
    acceptance_prefix = f"opentelekomcloud/acceptance/{service}/"

    def allows(path: str) -> bool:
        if path == "opentelekomcloud/provider.go":
            return True
        if path.startswith(service_prefix) and path.endswith(".go"):
            return True
        if path.startswith(acceptance_prefix) and path.endswith("_test.go"):
            return True
        if path.startswith("docs/resources/") or path.startswith("docs/data-sources/"):
            return path.endswith(".md") and service.replace("_", "-") in Path(path).name.replace("_", "-")
        if path.startswith("releasenotes/notes/"):
            return path.endswith((".yaml", ".yml"))
        return False

    return PatchPolicy(allows)


def _validate_path(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or ".git" in pure.parts or ".github" in pure.parts:
        raise PatchViolation(f"unsafe patch path {path!r}")
    if any(part in {"", "."} for part in pure.parts):
        raise PatchViolation(f"invalid patch path {path!r}")


def _git_apply(root: Path, patch: str, *, check: bool) -> None:
    command = ["git", "apply", "--whitespace=nowarn"]
    if check:
        command.append("--check")
    result = subprocess.run(
        command,
        cwd=root,
        input=patch,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[:1000]
        raise PatchViolation(f"git apply {'check ' if check else ''}failed: {detail}")
