from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


class SDKGuidanceError(ValueError):
    pass


@dataclass(frozen=True)
class PinnedSDKSource:
    revision: str
    path: str
    source_kind: str
    sha256: str
    content: str
    validated_package: str | None = None
    validation_output_sha256: str | None = None

    def metadata(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("content")
        return value


_CONTRIBUTION_PATHS = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md")
_STOP_WORDS = frozenset(
    {
        "add",
        "api",
        "change",
        "documented",
        "endpoint",
        "feature",
        "fix",
        "from",
        "service",
        "support",
        "the",
        "update",
        "with",
    }
)
_HTTP_OPERATIONS = {
    "post": "create",
    "get": "get",
    "put": "update",
    "patch": "update",
    "delete": "delete",
}


def retrieve_sdk_guidance(
    root: Path,
    revision: str,
    *,
    target_service: str,
    query: str,
    max_files: int = 15,
    max_bytes: int = 300_000,
) -> tuple[PinnedSDKSource, ...]:
    sources = [
        _source(root, revision, "FAQ.md", "faq"),
        _source(root, revision, "STYLEGUIDE.md", "styleguide"),
    ]
    contribution_path = next(
        (path for path in _CONTRIBUTION_PATHS if _tracked(root, revision, path)),
        None,
    )
    if contribution_path is None:
        raise SDKGuidanceError("SDK revision is missing contribution guidance")
    sources.append(_source(root, revision, contribution_path, "contribution"))
    reference_paths = select_relevant_sdk_examples(
        root,
        revision,
        target_service=target_service,
        query=query,
        max_files=min(12, max_files - len(sources)),
    )
    validations = _validate_reference_packages(root, revision, reference_paths)
    for path in reference_paths:
        if len(sources) >= max_files:
            break
        package = str(Path(path).parent.as_posix())
        sources.append(
            _source(
                root,
                revision,
                path,
                "reference_test" if path.endswith("_test.go") else "reference_implementation",
                validated_package=package,
                validation_output_sha256=validations[package],
            )
        )
    total = sum(len(source.content.encode("utf-8")) for source in sources)
    if total > max_bytes:
        raise SDKGuidanceError("revision-pinned SDK guidance exceeds the allowed context size")
    return tuple(sources)


def select_relevant_sdk_examples(
    root: Path,
    revision: str,
    *,
    target_service: str,
    query: str,
    max_files: int = 12,
) -> tuple[str, ...]:
    if max_files < 1:
        raise SDKGuidanceError("SDK example file budget must be positive")
    all_paths = tuple(
        path
        for path in _git_lines(root, "ls-tree", "-r", "--name-only", revision, "--", "openstack")
        if path.endswith(".go") and not path.startswith(f"openstack/{target_service}/")
    )
    implementations = tuple(path for path in all_paths if not path.endswith("_test.go"))
    tests = tuple(path for path in all_paths if path.endswith("_test.go"))
    if not implementations or not tests:
        raise SDKGuidanceError("SDK revision has no cross-service reference implementations")
    tokens = _query_tokens(query)
    matched_paths: set[str] = set()
    for token in tokens:
        matched_paths.update(_git_grep_paths(root, revision, token))
    ranked: list[tuple[int, str]] = []
    for path in implementations:
        lower_path = path.lower()
        stem = Path(path).stem.lower()
        score = sum(12 for token in tokens if token in lower_path)
        score += sum(30 for token in tokens if token == stem)
        if path in matched_paths:
            score += 18
        if "/apigw/" in lower_path or "/fgs/" in lower_path:
            score += 3
        if score:
            ranked.append((score, path))
    if not ranked:
        ranked = [(1, path) for path in implementations]
    selected_implementations: list[str] = []
    service_counts: dict[str, int] = {}
    for _score, path in sorted(ranked, key=lambda item: (-item[0], item[1])):
        parts = path.split("/")
        service = parts[1] if len(parts) > 1 else ""
        if service_counts.get(service, 0) >= 3:
            continue
        if not _matching_tests(path, tests, tokens):
            continue
        selected_implementations.append(path)
        service_counts[service] = service_counts.get(service, 0) + 1
        if len(selected_implementations) >= max_files // 2:
            break
    selected: list[str] = []
    for implementation in selected_implementations:
        selected.append(implementation)
        selected.append(_matching_tests(implementation, tests, tokens)[0])
    if not selected:
        raise SDKGuidanceError("no relevant SDK implementation/test pairs were selected")
    return tuple(selected)


def render_sdk_guidance(sources: tuple[PinnedSDKSource, ...]) -> str:
    return "\n\n".join(
        f"PINNED {source.source_kind.upper()} {source.path} @ {source.revision}\n"
        f"<UNTRUSTED_REPOSITORY_SOURCE>\n{source.content}\n</UNTRUSTED_REPOSITORY_SOURCE>"
        for source in sources
    )


def _tracked(root: Path, revision: str, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}:{path}"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def _source(
    root: Path,
    revision: str,
    path: str,
    source_kind: str,
    *,
    validated_package: str | None = None,
    validation_output_sha256: str | None = None,
) -> PinnedSDKSource:
    try:
        result = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SDKGuidanceError(f"unable to read revision-pinned SDK source {path}") from exc
    if result.returncode != 0:
        raise SDKGuidanceError(f"SDK revision is missing required source {path}")
    if len(result.stdout) > 150_000:
        raise SDKGuidanceError(f"SDK source {path} exceeds the per-file size limit")
    try:
        content = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SDKGuidanceError(f"SDK source {path} is not UTF-8") from exc
    return PinnedSDKSource(
        revision=revision,
        path=path,
        source_kind=source_kind,
        sha256=hashlib.sha256(result.stdout).hexdigest(),
        content=content,
        validated_package=validated_package,
        validation_output_sha256=validation_output_sha256,
    )


def _git_lines(root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SDKGuidanceError("unable to enumerate revision-pinned SDK references") from exc
    if result.returncode != 0:
        raise SDKGuidanceError("unable to enumerate revision-pinned SDK references")
    return tuple(line for line in result.stdout.splitlines() if line)


def _query_tokens(query: str) -> tuple[str, ...]:
    raw = re.findall(r"[a-z0-9]+", query.lower())
    tokens = {
        _HTTP_OPERATIONS.get(token, token)
        for token in raw
        if len(token) >= 3 and token not in _STOP_WORDS
    }
    operations = tokens & {"create", "list", "get", "update", "delete"}
    if "get" in tokens and any(word in raw for word in ("all", "many", "page", "pagination")):
        operations.add("list")
    return tuple(sorted(tokens | operations))


def _git_grep_paths(root: Path, revision: str, token: str) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "grep", "-I", "-l", "-i", "-e", token, revision, "--", "openstack"],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SDKGuidanceError("unable to search revision-pinned SDK examples") from exc
    if result.returncode not in (0, 1):
        raise SDKGuidanceError("unable to search revision-pinned SDK examples")
    prefix = f"{revision}:"
    return tuple(
        line.removeprefix(prefix)
        for line in result.stdout.splitlines()
        if line.removeprefix(prefix).endswith(".go")
    )


def _matching_tests(
    implementation: str,
    tests: tuple[str, ...],
    tokens: tuple[str, ...],
) -> tuple[str, ...]:
    directory = str(Path(implementation).parent.as_posix())
    stem = Path(implementation).stem.lower()
    candidates = [path for path in tests if str(Path(path).parent.as_posix()) == directory]
    return tuple(
        sorted(
            candidates,
            key=lambda path: (
                0 if stem in Path(path).stem.lower() else 1,
                -sum(token in path.lower() for token in tokens),
                path,
            ),
        )
    )


def _validate_reference_packages(
    root: Path,
    revision: str,
    paths: tuple[str, ...],
) -> dict[str, str]:
    if _git_lines(root, "rev-parse", "HEAD") != (revision,):
        raise SDKGuidanceError("SDK checkout does not match the captured revision")
    status = _git_lines(root, "status", "--porcelain")
    if status:
        raise SDKGuidanceError("SDK checkout must be clean before validating examples")
    validations: dict[str, str] = {}
    for package in sorted({str(Path(path).parent.as_posix()) for path in paths}):
        try:
            result = subprocess.run(
                ["go", "test", f"./{package}"],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SDKGuidanceError(f"unable to validate SDK example package {package}") from exc
        output = result.stdout + "\n" + result.stderr
        if result.returncode != 0:
            raise SDKGuidanceError(f"selected SDK example package {package} does not pass go test")
        validations[package] = hashlib.sha256(output.encode("utf-8")).hexdigest()
    return validations
