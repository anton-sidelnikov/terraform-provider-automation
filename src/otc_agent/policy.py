from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyContract:
    policy_id: str
    version: int
    path: str


def default_policy_root() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "policy"


_METADATA = re.compile(r"^(Policy ID|Status|Version|Adopted):\s*(.+?)\s*$", re.MULTILINE)
_SECTION = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)


def load_policy_registry(root: Path) -> tuple[PolicyContract, ...]:
    if not root.is_dir():
        raise PolicyError(f"policy directory does not exist: {root}")
    contracts = tuple(
        _load_policy(path)
        for path in sorted(root.glob("*.md"))
        if path.name != "README.md"
    )
    if not contracts:
        raise PolicyError("policy registry is empty")
    identifiers = [contract.policy_id for contract in contracts]
    if len(identifiers) != len(set(identifiers)):
        raise PolicyError("policy IDs must be unique")
    return contracts


def _load_policy(path: Path) -> PolicyContract:
    content = path.read_text(encoding="utf-8")
    if not re.match(r"^#\s+.+$", content, re.MULTILINE):
        raise PolicyError(f"{path.name}: missing title")
    metadata = dict(_METADATA.findall(content))
    missing = {"Policy ID", "Status", "Version", "Adopted"} - metadata.keys()
    if missing:
        raise PolicyError(f"{path.name}: missing metadata: {', '.join(sorted(missing))}")
    policy_id = metadata["Policy ID"]
    if not re.fullmatch(r"[a-z][a-z0-9-]*", policy_id):
        raise PolicyError(f"{path.name}: invalid policy ID")
    if metadata["Status"] != "Adopted":
        raise PolicyError(f"{path.name}: status must be Adopted")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", metadata["Adopted"]):
        raise PolicyError(f"{path.name}: adopted date must use YYYY-MM-DD")
    try:
        version = int(metadata["Version"])
    except ValueError as exc:
        raise PolicyError(f"{path.name}: version must be an integer") from exc
    sections = _SECTION.findall(content)
    numbers = [int(number) for number, _ in sections]
    if version < 1 or numbers != list(range(1, len(numbers) + 1)):
        raise PolicyError(f"{path.name}: invalid version or section numbering")
    if not sections or sections[-1][1].lower() != "review checklist":
        raise PolicyError(f"{path.name}: final section must be Review checklist")
    if not re.search(r"^- \[[ x]\]\s+", content, re.MULTILINE):
        raise PolicyError(f"{path.name}: review checklist is empty")
    return PolicyContract(policy_id, version, path.as_posix())
