from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path


class LayoutKind(StrEnum):
    MODERN = "modern"
    LEGACY = "legacy"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class OperationLocation:
    name: str
    path: str
    operation_file: bool


@dataclass(frozen=True)
class SDKLayoutAnalysis:
    service: str
    kind: LayoutKind
    operations: tuple[OperationLocation, ...]
    legacy_files: tuple[str, ...]

    @property
    def requires_refactoring(self) -> bool:
        return self.kind in {LayoutKind.LEGACY, LayoutKind.MIXED}

    @property
    def legacy_operations(self) -> tuple[OperationLocation, ...]:
        return tuple(operation for operation in self.operations if not operation.operation_file)

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["requires_refactoring"] = self.requires_refactoring
        value["legacy_operations"] = [asdict(operation) for operation in self.legacy_operations]
        return value


_SERVICE = re.compile(r"[a-z][a-z0-9_]*")
_OPERATION = re.compile(
    r"^\s*func\s+((?:Create|Delete|Get|List|Update|Batch|Show|Set|Reset|Enable|Disable|"
    r"Associate|Disassociate|Attach|Detach|Bind|Unbind|Invoke|Publish|Cancel|Import|Export)"
    r"[A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_LEGACY_FILENAMES = {"request.go", "requests.go", "urls.go", "results.go"}


def analyze_sdk_layout(sdk_root: Path, service: str) -> SDKLayoutAnalysis:
    if not _SERVICE.fullmatch(service):
        raise ValueError("service must be an exact lower-case SDK package name")
    service_root = sdk_root / "openstack" / service
    if not service_root.is_dir():
        raise ValueError(f"SDK service directory does not exist: openstack/{service}")

    operations: list[OperationLocation] = []
    legacy_files: list[str] = []
    for path in sorted(service_root.rglob("*.go")):
        if path.is_symlink() or path.name.endswith("_test.go"):
            continue
        relative = path.relative_to(sdk_root).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        names = tuple(dict.fromkeys(_OPERATION.findall(content)))
        if path.name in _LEGACY_FILENAMES:
            legacy_files.append(relative)
        for name in names:
            operations.append(
                OperationLocation(
                    name=name,
                    path=relative,
                    operation_file=path.stem == name,
                )
            )

    modern_count = sum(operation.operation_file for operation in operations)
    legacy_count = len(operations) - modern_count
    if legacy_count and modern_count:
        kind = LayoutKind.MIXED
    elif legacy_count:
        kind = LayoutKind.LEGACY
    elif modern_count:
        kind = LayoutKind.MODERN
    else:
        kind = LayoutKind.UNKNOWN
    return SDKLayoutAnalysis(service, kind, tuple(operations), tuple(legacy_files))

