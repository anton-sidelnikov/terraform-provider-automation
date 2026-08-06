from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class PolicyContract:
    policy_id: str
    title: str
    status: str
    version: int
    adopted: str
    path: str
    sections: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


_METADATA = re.compile(r"^(Policy ID|Status|Version|Adopted):\s*(.+?)\s*$", re.MULTILINE)
_SECTION = re.compile(r"^##\s+(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
_POLICY_ID = re.compile(r"[a-z][a-z0-9-]*")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def load_policy_registry(root: Path) -> tuple[PolicyContract, ...]:
    if not root.is_dir():
        raise PolicyError(f"policy directory does not exist: {root}")
    contracts = tuple(
        _load_policy(path, root)
        for path in sorted(root.glob("*.md"))
        if path.name != "README.md"
    )
    if not contracts:
        raise PolicyError("policy registry is empty")
    identifiers = [contract.policy_id for contract in contracts]
    if len(identifiers) != len(set(identifiers)):
        raise PolicyError("policy IDs must be unique")
    return contracts


def _load_policy(path: Path, root: Path) -> PolicyContract:
    content = path.read_text(encoding="utf-8")
    title_match = re.match(r"^#\s+(.+?)\s*$", content, re.MULTILINE)
    if not title_match:
        raise PolicyError(f"{path.name}: missing level-one title")
    metadata = dict(_METADATA.findall(content))
    missing = {"Policy ID", "Status", "Version", "Adopted"} - metadata.keys()
    if missing:
        raise PolicyError(f"{path.name}: missing metadata: {', '.join(sorted(missing))}")
    policy_id = metadata["Policy ID"]
    if not _POLICY_ID.fullmatch(policy_id):
        raise PolicyError(f"{path.name}: invalid policy ID")
    if metadata["Status"] != "Adopted":
        raise PolicyError(f"{path.name}: policy status must be Adopted")
    try:
        version = int(metadata["Version"])
    except ValueError as exc:
        raise PolicyError(f"{path.name}: version must be an integer") from exc
    if version < 1:
        raise PolicyError(f"{path.name}: version must be positive")
    if not _DATE.fullmatch(metadata["Adopted"]):
        raise PolicyError(f"{path.name}: adopted date must use YYYY-MM-DD")
    sections = _SECTION.findall(content)
    section_numbers = [int(number) for number, _ in sections]
    if section_numbers != list(range(1, len(section_numbers) + 1)):
        raise PolicyError(f"{path.name}: sections must be consecutively numbered from 1")
    if not sections or sections[-1][1].lower() != "review checklist":
        raise PolicyError(f"{path.name}: final numbered section must be Review checklist")
    if not re.search(r"^- \[[ x]\]\s+", content, re.MULTILINE):
        raise PolicyError(f"{path.name}: review checklist is empty")
    return PolicyContract(
        policy_id=policy_id,
        title=title_match.group(1),
        status=metadata["Status"],
        version=version,
        adopted=metadata["Adopted"],
        path=path.relative_to(root.parent.parent).as_posix(),
        sections=tuple(title for _, title in sections),
    )
