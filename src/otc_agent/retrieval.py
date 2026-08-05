from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .security import safe_workspace_path


@dataclass(frozen=True)
class EvidenceChunk:
    repository: str
    revision: str
    path: str
    line_start: int
    line_end: int
    sha256: str
    content: str
    score: float

    def metadata(self) -> dict[str, object]:
        value = asdict(self)
        value.pop("content")
        return value


def retrieve_api_reference(
    root: Path,
    *,
    repository: str,
    revision: str,
    query: str,
    limit: int = 18,
    max_total_chars: int = 60_000,
) -> list[EvidenceChunk]:
    root = root.resolve()
    api_root = safe_workspace_path(root, "api-ref")
    if not (api_root / "source" / "index.rst").is_file():
        raise ValueError("documentation repository does not contain api-ref/source/index.rst")
    terms = {term for term in re.findall(r"[a-z0-9_-]{3,}", query.lower()) if term not in _STOP_WORDS}
    candidates: list[EvidenceChunk] = []
    for path in sorted(api_root.rglob("*.rst")):
        if path.is_symlink() or path.stat().st_size > 1_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        for start in range(0, len(lines), 60):
            selected = lines[start : start + 60]
            content = "\n".join(selected).strip()
            if not content:
                continue
            lowered = content.lower()
            score = float(sum(lowered.count(term) for term in terms))
            relative = path.relative_to(root).as_posix()
            if relative.endswith("index.rst"):
                score += 0.25
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            candidates.append(
                EvidenceChunk(repository, revision, relative, start + 1, start + len(selected), digest, content, score)
            )
    candidates.sort(key=lambda item: (-item.score, item.path, item.line_start))
    selected_chunks: list[EvidenceChunk] = []
    total = 0
    for chunk in candidates:
        if len(selected_chunks) >= limit:
            break
        if total + len(chunk.content) > max_total_chars:
            continue
        if chunk.score <= 0 and selected_chunks:
            continue
        selected_chunks.append(chunk)
        total += len(chunk.content)
    if not selected_chunks:
        raise ValueError("retrieval produced no API-reference evidence")
    return selected_chunks


_STOP_WORDS = {
    "about",
    "add",
    "added",
    "change",
    "create",
    "from",
    "into",
    "service",
    "support",
    "that",
    "the",
    "this",
    "with",
}
