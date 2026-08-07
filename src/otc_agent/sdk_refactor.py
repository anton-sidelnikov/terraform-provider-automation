from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .sdk_layout import SDKLayoutAnalysis


class SDKRefactorPlanError(ValueError):
    pass


@dataclass(frozen=True)
class ExportedSymbol:
    identifier: str
    package_path: str
    kind: str
    name: str
    signature: str


@dataclass(frozen=True)
class ExportedAPISnapshot:
    schema_version: int
    service: str
    symbols: tuple[ExportedSymbol, ...]
    snapshot_sha256: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CompatibilityReport:
    compatible: bool
    baseline_sha256: str
    candidate_sha256: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    approved_changes: tuple[str, ...]
    violations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticDeclaration:
    identifier: str
    package_path: str
    kind: str
    name: str
    semantic_sha256: str


@dataclass(frozen=True)
class SemanticSnapshot:
    schema_version: int
    service: str
    declarations: tuple[SemanticDeclaration, ...]
    snapshot_sha256: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SemanticChangeReport:
    compatible: bool
    baseline_sha256: str
    candidate_sha256: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]
    approved_changes: tuple[str, ...]
    violations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OperationFileViolation:
    code: str
    operation: str
    path: str
    expected_path: str


@dataclass(frozen=True)
class OperationFileReport:
    valid: bool
    service: str
    operations: tuple[dict[str, str], ...]
    violations: tuple[OperationFileViolation, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BehaviorRequirement:
    operation: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class BehaviorVerification:
    valid: bool
    test_passed: bool
    test_output_sha256: str
    covered: dict[str, tuple[str, ...]]
    missing: dict[str, tuple[str, ...]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AppliedMigration:
    changed_paths: tuple[str, ...]
    removed_paths: tuple[str, ...]
    moved_declarations: dict[str, tuple[str, ...]]
    compatibility: CompatibilityReport
    semantics: SemanticChangeReport
    operation_files: OperationFileReport
    behavior: BehaviorVerification

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OperationMigration:
    operation: str
    package_path: str
    source_path: str
    target_path: str
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class MigrationBatch:
    migration_id: str
    package_path: str
    operations: tuple[str, ...]
    source_files: tuple[str, ...]
    target_files: tuple[str, ...]
    branch_suffix: str
    pull_request_title: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SDKRefactorPlan:
    schema_version: int
    service: str
    layout_kind: str
    analysis_sha256: str
    status: str
    operations: tuple[OperationMigration, ...]
    batches: tuple[MigrationBatch, ...]
    legacy_files: tuple[str, ...]
    exported_api: ExportedAPISnapshot
    approved_api_changes: tuple[str, ...]
    semantic_snapshot: SemanticSnapshot
    approved_behavior_changes: tuple[str, ...]
    behavior_requirements: tuple[BehaviorRequirement, ...]
    blocked_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def build_operation_migration_plan(
    sdk_root: Path,
    analysis: SDKLayoutAnalysis,
    specification: dict[str, object] | None = None,
) -> SDKRefactorPlan:
    if not analysis.requires_refactoring:
        raise SDKRefactorPlanError("operation migration requires confirmed legacy or mixed SDK layout")
    service_prefix = f"openstack/{analysis.service}/"
    legacy_operations = sorted(analysis.legacy_operations, key=lambda item: (item.path, item.name))
    if not legacy_operations:
        raise SDKRefactorPlanError("layout requires refactoring but contains no legacy operations")

    name_counts: dict[str, int] = {}
    for operation in analysis.operations:
        name_counts[operation.name] = name_counts.get(operation.name, 0) + 1

    migrations: list[OperationMigration] = []
    blocked_reasons: set[str] = set()
    for operation in legacy_operations:
        source = Path(operation.path)
        source_path = source.as_posix()
        if not source_path.startswith(service_prefix) or source.is_absolute() or ".." in source.parts:
            raise SDKRefactorPlanError("layout analysis contains an out-of-scope operation path")
        target = source.with_name(f"{operation.name}.go")
        target_path = target.as_posix()
        conflicts: list[str] = []
        if name_counts[operation.name] > 1:
            conflicts.append(f"exported operation {operation.name} is declared more than once")
        if (sdk_root / target).exists():
            conflicts.append(f"target file already exists: {target_path}")
        blocked_reasons.update(conflicts)
        migrations.append(
            OperationMigration(
                operation=operation.name,
                package_path=source.parent.as_posix(),
                source_path=source_path,
                target_path=target_path,
                conflicts=tuple(conflicts),
            )
        )

    batches = _migration_batches(migrations)
    exported_api = capture_exported_api(sdk_root, analysis.service)
    approved_api_changes = _approved_api_changes(specification or {}, exported_api)
    semantic_snapshot = capture_semantic_snapshot(sdk_root, analysis.service)
    approved_behavior_changes = _approved_behavior_changes(specification or {})
    behavior_requirements = _behavior_requirements(specification or {}, migrations)
    analysis_json = json.dumps(analysis.as_dict(), sort_keys=True, separators=(",", ":"))
    return SDKRefactorPlan(
        schema_version=1,
        service=analysis.service,
        layout_kind=analysis.kind.value,
        analysis_sha256=hashlib.sha256(analysis_json.encode("utf-8")).hexdigest(),
        status="blocked" if blocked_reasons else "ready",
        operations=tuple(migrations),
        batches=batches,
        legacy_files=analysis.legacy_files,
        exported_api=exported_api,
        approved_api_changes=approved_api_changes,
        semantic_snapshot=semantic_snapshot,
        approved_behavior_changes=approved_behavior_changes,
        behavior_requirements=behavior_requirements,
        blocked_reasons=tuple(sorted(blocked_reasons)),
    )


def capture_exported_api(sdk_root: Path, service: str) -> ExportedAPISnapshot:
    service_root = sdk_root / "openstack" / service
    if not service_root.is_dir():
        raise SDKRefactorPlanError(f"SDK service directory does not exist: openstack/{service}")
    with tempfile.TemporaryDirectory() as directory:
        helper = Path(directory) / "snapshot.go"
        helper.write_text(_GO_EXPORT_SNAPSHOT, encoding="utf-8")
        try:
            result = subprocess.run(
                ["go", "run", str(helper), str(sdk_root), service],
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SDKRefactorPlanError("unable to run Go exported-API analyzer") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise SDKRefactorPlanError(f"Go exported-API analyzer failed: {detail}")
    try:
        raw_symbols = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SDKRefactorPlanError("Go exported-API analyzer returned invalid JSON") from exc
    if not isinstance(raw_symbols, list):
        raise SDKRefactorPlanError("Go exported-API analyzer returned an invalid symbol list")
    symbols: list[ExportedSymbol] = []
    for item in raw_symbols:
        if not isinstance(item, dict) or set(item) != {"package_path", "kind", "name", "signature"}:
            raise SDKRefactorPlanError("Go exported-API analyzer returned an invalid symbol")
        values = [item[field] for field in ("package_path", "kind", "name", "signature")]
        if not all(isinstance(value, str) and value for value in values):
            raise SDKRefactorPlanError("Go exported-API analyzer returned an empty symbol field")
        identifier = f"{item['package_path']}::{item['kind']}::{item['name']}"
        symbols.append(ExportedSymbol(identifier, *values))
    symbols.sort(key=lambda item: item.identifier)
    payload = [asdict(item) for item in symbols]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ExportedAPISnapshot(1, service, tuple(symbols), digest)


def validate_exported_api_compatibility(
    baseline: ExportedAPISnapshot,
    candidate: ExportedAPISnapshot,
    approved_changes: tuple[str, ...] = (),
) -> CompatibilityReport:
    if baseline.service != candidate.service:
        raise SDKRefactorPlanError("cannot compare exported API snapshots for different services")
    if len({item.identifier for item in baseline.symbols}) != len(baseline.symbols):
        raise SDKRefactorPlanError("baseline exported API contains duplicate symbol identities")
    if len({item.identifier for item in candidate.symbols}) != len(candidate.symbols):
        raise SDKRefactorPlanError("candidate exported API contains duplicate symbol identities")
    baseline_symbols = {item.identifier: item for item in baseline.symbols}
    candidate_symbols = {item.identifier: item for item in candidate.symbols}
    added = tuple(sorted(set(candidate_symbols) - set(baseline_symbols)))
    removed = tuple(sorted(set(baseline_symbols) - set(candidate_symbols)))
    changed = tuple(
        sorted(
            identifier
            for identifier in set(baseline_symbols) & set(candidate_symbols)
            if baseline_symbols[identifier].signature != candidate_symbols[identifier].signature
        )
    )
    approved = set(approved_changes)
    unknown_approvals = approved - set(baseline_symbols)
    if unknown_approvals:
        raise SDKRefactorPlanError(
            f"approved API changes reference unknown symbols: {', '.join(sorted(unknown_approvals))}"
        )
    violations = tuple(sorted((set(removed) | set(changed)) - approved))
    return CompatibilityReport(
        compatible=not violations,
        baseline_sha256=baseline.snapshot_sha256,
        candidate_sha256=candidate.snapshot_sha256,
        added=added,
        removed=removed,
        changed=changed,
        approved_changes=tuple(sorted(approved)),
        violations=violations,
    )


def capture_semantic_snapshot(sdk_root: Path, service: str) -> SemanticSnapshot:
    with tempfile.TemporaryDirectory() as directory:
        helper = Path(directory) / "semantics.go"
        helper.write_text(_GO_SEMANTIC_SNAPSHOT, encoding="utf-8")
        try:
            result = subprocess.run(
                ["go", "run", str(helper), str(sdk_root), service],
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SDKRefactorPlanError("unable to run Go semantic analyzer") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise SDKRefactorPlanError(f"Go semantic analyzer failed: {detail}")
    try:
        raw_declarations = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SDKRefactorPlanError("Go semantic analyzer returned invalid JSON") from exc
    if not isinstance(raw_declarations, list):
        raise SDKRefactorPlanError("Go semantic analyzer returned an invalid declaration list")
    declarations: list[SemanticDeclaration] = []
    for item in raw_declarations:
        fields = {"package_path", "kind", "name", "semantic_sha256"}
        if (
            not isinstance(item, dict)
            or set(item) != fields
            or not all(isinstance(item[field], str) and item[field] for field in fields)
        ):
            raise SDKRefactorPlanError("Go semantic analyzer returned an invalid declaration")
        identifier = f"{item['package_path']}::{item['kind']}::{item['name']}"
        declarations.append(SemanticDeclaration(identifier=identifier, **item))
    declarations.sort(key=lambda item: item.identifier)
    payload = [asdict(item) for item in declarations]
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SemanticSnapshot(1, service, tuple(declarations), digest)


def validate_semantic_preservation(
    baseline: SemanticSnapshot,
    candidate: SemanticSnapshot,
    approved_changes: tuple[str, ...] = (),
) -> SemanticChangeReport:
    if baseline.service != candidate.service:
        raise SDKRefactorPlanError("cannot compare semantic snapshots for different services")
    if len({item.identifier for item in baseline.declarations}) != len(baseline.declarations):
        raise SDKRefactorPlanError("baseline semantic snapshot contains duplicate declaration identities")
    if len({item.identifier for item in candidate.declarations}) != len(candidate.declarations):
        raise SDKRefactorPlanError("candidate semantic snapshot contains duplicate declaration identities")
    before = {item.identifier: item.semantic_sha256 for item in baseline.declarations}
    after = {item.identifier: item.semantic_sha256 for item in candidate.declarations}
    added = tuple(sorted(set(after) - set(before)))
    removed = tuple(sorted(set(before) - set(after)))
    changed = tuple(
        sorted(identifier for identifier in set(before) & set(after) if before[identifier] != after[identifier])
    )
    approved = set(approved_changes)
    unknown = approved - (set(before) | set(after))
    if unknown:
        raise SDKRefactorPlanError(
            f"approved behavior changes reference unknown declarations: {', '.join(sorted(unknown))}"
        )
    violations = tuple(sorted((set(added) | set(removed) | set(changed)) - approved))
    return SemanticChangeReport(
        compatible=not violations,
        baseline_sha256=baseline.snapshot_sha256,
        candidate_sha256=candidate.snapshot_sha256,
        added=added,
        removed=removed,
        changed=changed,
        approved_changes=tuple(sorted(approved)),
        violations=violations,
    )


def validate_operation_file_correspondence(
    sdk_root: Path,
    service: str,
    operations: tuple[str, ...] | None = None,
) -> OperationFileReport:
    with tempfile.TemporaryDirectory() as directory:
        helper = Path(directory) / "validate.go"
        helper.write_text(_GO_OPERATION_FILE_VALIDATOR, encoding="utf-8")
        try:
            command = ["go", "run", str(helper), str(sdk_root), service]
            if operations is not None:
                command.append(",".join(sorted(operations)))
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SDKRefactorPlanError("unable to run Go operation-file validator") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise SDKRefactorPlanError(f"Go operation-file validator failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SDKRefactorPlanError("Go operation-file validator returned invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"operations", "violations"}:
        raise SDKRefactorPlanError("Go operation-file validator returned invalid fields")
    raw_operations = value["operations"]
    raw_violations = value["violations"]
    if not isinstance(raw_operations, list) or not isinstance(raw_violations, list):
        raise SDKRefactorPlanError("Go operation-file validator returned invalid collections")
    operations: list[dict[str, str]] = []
    for item in raw_operations:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "path"}
            or not all(isinstance(item[field], str) and item[field] for field in ("name", "path"))
        ):
            raise SDKRefactorPlanError("Go operation-file validator returned an invalid operation")
        operations.append(dict(item))
    violations: list[OperationFileViolation] = []
    for item in raw_violations:
        fields = {"code", "operation", "path", "expected_path"}
        if (
            not isinstance(item, dict)
            or set(item) != fields
            or not all(isinstance(item[field], str) and item[field] for field in fields)
        ):
            raise SDKRefactorPlanError("Go operation-file validator returned an invalid violation")
        violations.append(OperationFileViolation(**item))
    return OperationFileReport(not violations, service, tuple(operations), tuple(violations))


def verify_refactor_behavior(
    sdk_root: Path,
    service: str,
    requirements: tuple[BehaviorRequirement, ...],
) -> BehaviorVerification:
    with tempfile.TemporaryDirectory() as directory:
        helper = Path(directory) / "behavior.go"
        helper.write_text(_GO_BEHAVIOR_INVENTORY, encoding="utf-8")
        try:
            inventory_result = subprocess.run(
                ["go", "run", str(helper), str(sdk_root), service],
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SDKRefactorPlanError("unable to inspect Go behavior tests") from exc
    if inventory_result.returncode != 0:
        detail = (inventory_result.stderr or inventory_result.stdout).strip()[:500]
        raise SDKRefactorPlanError(f"Go behavior test inventory failed: {detail}")
    try:
        inventory = json.loads(inventory_result.stdout)
    except json.JSONDecodeError as exc:
        raise SDKRefactorPlanError("Go behavior test inventory returned invalid JSON") from exc
    if not isinstance(inventory, dict) or not all(
        isinstance(operation, str)
        and isinstance(checks, list)
        and all(isinstance(check, str) for check in checks)
        for operation, checks in inventory.items()
    ):
        raise SDKRefactorPlanError("Go behavior test inventory returned invalid coverage")
    covered = {
        requirement.operation: tuple(sorted(set(inventory.get(requirement.operation, []))))
        for requirement in requirements
    }
    missing = {
        requirement.operation: tuple(sorted(set(requirement.checks) - set(covered[requirement.operation])))
        for requirement in requirements
    }
    missing = {operation: checks for operation, checks in missing.items() if checks}
    environment = os.environ.copy()
    if not (sdk_root / "go.mod").is_file():
        environment["GO111MODULE"] = "off"
    try:
        test_result = subprocess.run(
            ["go", "test", f"./openstack/{service}/..."],
            cwd=sdk_root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SDKRefactorPlanError("unable to run SDK behavior tests") from exc
    test_output = test_result.stdout + test_result.stderr
    return BehaviorVerification(
        valid=test_result.returncode == 0 and not missing,
        test_passed=test_result.returncode == 0,
        test_output_sha256=hashlib.sha256(test_output.encode("utf-8")).hexdigest(),
        covered=covered,
        missing=missing,
    )


def apply_operation_file_migration(
    sdk_root: Path,
    plan: SDKRefactorPlan,
) -> AppliedMigration:
    if plan.status != "ready":
        raise SDKRefactorPlanError("cannot apply a blocked SDK refactoring plan")
    request = {
        "legacy_files": list(plan.legacy_files),
        "operations": [
            {
                "operation": item.operation,
                "source_path": item.source_path,
                "target_path": item.target_path,
            }
            for item in plan.operations
        ]
    }
    with tempfile.TemporaryDirectory() as directory:
        helper = Path(directory) / "migrate.go"
        helper.write_text(_GO_OPERATION_MIGRATOR, encoding="utf-8")
        try:
            result = subprocess.run(
                ["go", "run", str(helper), str(sdk_root)],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SDKRefactorPlanError("unable to run Go operation migration analyzer") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise SDKRefactorPlanError(f"Go operation migration analyzer failed: {detail}")
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SDKRefactorPlanError("Go operation migration analyzer returned invalid JSON") from exc
    changes, removed, moved = _validate_migration_response(response, plan)
    backups: dict[Path, bytes | None] = {}
    try:
        for relative in sorted(set(changes) | set(removed)):
            path = sdk_root / relative
            backups[path] = path.read_bytes() if path.exists() else None
        for relative, content in changes.items():
            path = sdk_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.otc-agent.tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
        for relative in removed:
            (sdk_root / relative).unlink(missing_ok=True)
        candidate = capture_exported_api(sdk_root, plan.service)
        compatibility = validate_exported_api_compatibility(
            plan.exported_api,
            candidate,
            plan.approved_api_changes,
        )
        if not compatibility.compatible:
            raise SDKRefactorPlanError(
                f"operation migration changed unapproved exported API: {', '.join(compatibility.violations)}"
            )
        semantics = validate_semantic_preservation(
            plan.semantic_snapshot,
            capture_semantic_snapshot(sdk_root, plan.service),
            plan.approved_behavior_changes,
        )
        if not semantics.compatible:
            raise SDKRefactorPlanError(
                f"operation migration changed unrelated behavior: {', '.join(semantics.violations)}"
            )
        operation_files = validate_operation_file_correspondence(
            sdk_root,
            plan.service,
            tuple(item.operation for item in plan.operations),
        )
        if not operation_files.valid:
            summary = ", ".join(
                f"{item.operation}:{item.code}"
                for item in operation_files.violations
            )
            raise SDKRefactorPlanError(f"operation/file correspondence validation failed: {summary}")
        behavior = verify_refactor_behavior(
            sdk_root,
            plan.service,
            plan.behavior_requirements,
        )
        if not behavior.valid:
            missing = ", ".join(
                f"{operation}={','.join(checks)}"
                for operation, checks in behavior.missing.items()
            )
            if not behavior.test_passed:
                raise SDKRefactorPlanError("SDK behavior tests failed after operation migration")
            raise SDKRefactorPlanError(f"SDK behavior test coverage is incomplete: {missing}")
    except Exception:
        for path, content in backups.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    return AppliedMigration(
        tuple(sorted(set(changes) | set(removed))),
        removed,
        moved,
        compatibility,
        semantics,
        operation_files,
        behavior,
    )


def select_migration(
    plan: SDKRefactorPlan,
    migration_id: str,
) -> SDKRefactorPlan:
    selected_batches = tuple(item for item in plan.batches if item.migration_id == migration_id)
    if len(selected_batches) != 1:
        raise SDKRefactorPlanError(f"unknown migration_id {migration_id!r}")
    selected_batch = selected_batches[0]
    selected_operations = tuple(
        item for item in plan.operations if item.operation in selected_batch.operations
    )
    if len(selected_operations) != 1:
        raise SDKRefactorPlanError("route-scoped migration must contain exactly one operation")
    requirements = tuple(
        item for item in plan.behavior_requirements if item.operation in selected_batch.operations
    )
    return replace(
        plan,
        operations=selected_operations,
        batches=selected_batches,
        behavior_requirements=requirements,
    )


def _validate_migration_response(
    value: object,
    plan: SDKRefactorPlan,
) -> tuple[dict[str, str], tuple[str, ...], dict[str, tuple[str, ...]]]:
    if not isinstance(value, dict) or set(value) != {"files", "removed_files", "moved_declarations"}:
        raise SDKRefactorPlanError("Go operation migration analyzer returned invalid fields")
    raw_files = value["files"]
    raw_removed = value["removed_files"]
    raw_moved = value["moved_declarations"]
    if not isinstance(raw_files, dict) or not isinstance(raw_removed, list) or not isinstance(raw_moved, dict):
        raise SDKRefactorPlanError("Go operation migration analyzer returned invalid mappings")
    allowed_paths = {
        path
        for item in plan.operations
        for path in (item.source_path, item.target_path)
    }
    files: dict[str, str] = {}
    for path, content in raw_files.items():
        if not isinstance(path, str) or path not in allowed_paths or not isinstance(content, str):
            raise SDKRefactorPlanError("Go operation migration analyzer returned an out-of-scope file")
        files[path] = content
    expected_targets = {item.target_path for item in plan.operations}
    if not expected_targets.issubset(files):
        raise SDKRefactorPlanError("Go operation migration analyzer omitted an operation target file")
    removed: list[str] = []
    allowed_removed = set(plan.legacy_files)
    for path in raw_removed:
        if not isinstance(path, str) or path not in allowed_removed or path in files:
            raise SDKRefactorPlanError("Go operation migration analyzer returned an invalid removed file")
        removed.append(path)
    if len(removed) != len(set(removed)):
        raise SDKRefactorPlanError("Go operation migration analyzer returned duplicate removed files")
    moved: dict[str, tuple[str, ...]] = {}
    expected_operations = {item.operation for item in plan.operations}
    for operation, declarations in raw_moved.items():
        if (
            not isinstance(operation, str)
            or operation not in expected_operations
            or not isinstance(declarations, list)
            or not all(isinstance(item, str) and item for item in declarations)
        ):
            raise SDKRefactorPlanError("Go operation migration analyzer returned invalid declaration ownership")
        moved[operation] = tuple(declarations)
    if set(moved) != expected_operations:
        raise SDKRefactorPlanError("Go operation migration analyzer omitted operation declaration ownership")
    return files, tuple(sorted(removed)), moved


def _migration_batches(migrations: list[OperationMigration]) -> tuple[MigrationBatch, ...]:
    batches: list[MigrationBatch] = []
    for item in sorted(migrations, key=lambda migration: (migration.package_path, migration.operation)):
        identity = f"{item.package_path}::{item.operation}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
        operation_slug = _slug(item.operation)
        batches.append(
            MigrationBatch(
                migration_id=f"{operation_slug}-{digest}",
                package_path=item.package_path,
                operations=(item.operation,),
                source_files=(item.source_path,),
                target_files=(item.target_path,),
                branch_suffix=f"refactor-{operation_slug}-{digest}",
                pull_request_title=f"Refactor {item.operation} into operation file",
            )
        )
    return tuple(batches)


def _slug(value: str) -> str:
    characters: list[str] = []
    for index, character in enumerate(value):
        if character.isupper() and index and characters[-1] != "-":
            characters.append("-")
        characters.append(character.lower() if character.isalnum() else "-")
    return "".join(characters).strip("-")


def _approved_api_changes(
    specification: dict[str, object],
    baseline: ExportedAPISnapshot,
) -> tuple[str, ...]:
    value = specification.get("approved_api_changes", [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SDKRefactorPlanError("approved_api_changes must be a string array")
    approved = tuple(sorted(set(value)))
    known = {item.identifier for item in baseline.symbols}
    unknown = set(approved) - known
    if unknown:
        raise SDKRefactorPlanError(
            f"approved API changes reference unknown symbols: {', '.join(sorted(unknown))}"
        )
    return approved


def _approved_behavior_changes(
    specification: dict[str, object],
) -> tuple[str, ...]:
    value = specification.get("approved_behavior_changes", [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SDKRefactorPlanError("approved_behavior_changes must be a string array")
    return tuple(sorted(set(value)))


def _behavior_requirements(
    specification: dict[str, object],
    migrations: list[OperationMigration],
) -> tuple[BehaviorRequirement, ...]:
    allowed = {"request", "response", "error", "zero_value", "pagination", "fixture"}
    configured = specification.get("behavior_checks", {})
    if not isinstance(configured, dict):
        raise SDKRefactorPlanError("behavior_checks must be an object keyed by operation")
    operation_names = {item.operation for item in migrations}
    unknown_operations = set(configured) - operation_names
    if unknown_operations:
        raise SDKRefactorPlanError(
            f"behavior_checks references unknown operations: {', '.join(sorted(unknown_operations))}"
        )
    requirements: list[BehaviorRequirement] = []
    for operation in sorted(operation_names):
        value = configured.get(operation)
        if value is None:
            checks = {"request", "response", "error", "zero_value", "fixture"}
            if operation.startswith("List"):
                checks.add("pagination")
        else:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise SDKRefactorPlanError(f"behavior_checks for {operation} must be a string array")
            checks = set(value)
            unsupported = checks - allowed
            if unsupported:
                raise SDKRefactorPlanError(
                    f"behavior_checks for {operation} contains unsupported checks: "
                    f"{', '.join(sorted(unsupported))}"
                )
            if not checks:
                raise SDKRefactorPlanError(f"behavior_checks for {operation} cannot be empty")
        requirements.append(BehaviorRequirement(operation, tuple(sorted(checks))))
    return tuple(requirements)


_GO_EXPORT_SNAPSHOT = r'''
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type symbol struct {
	PackagePath string `json:"package_path"`
	Kind        string `json:"kind"`
	Name        string `json:"name"`
	Signature   string `json:"signature"`
}

func render(node any) string {
	var output bytes.Buffer
	if err := format.Node(&output, token.NewFileSet(), node); err != nil {
		panic(err)
	}
	return output.String()
}

func receiverName(field *ast.Field) string {
	value := strings.TrimPrefix(render(field.Type), "*")
	if index := strings.Index(value, "["); index >= 0 {
		value = value[:index]
	}
	return value
}

func main() {
	if len(os.Args) != 3 {
		panic("usage: snapshot <sdk-root> <service>")
	}
	root := filepath.Join(os.Args[1], "openstack", os.Args[2])
	var symbols []symbol
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.SkipObjectResolution)
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(os.Args[1], filepath.Dir(path))
		if err != nil {
			return err
		}
		packagePath := filepath.ToSlash(relative)
		for _, declaration := range file.Decls {
			switch item := declaration.(type) {
			case *ast.FuncDecl:
				if !item.Name.IsExported() {
					continue
				}
				name := item.Name.Name
				kind := "func"
				signature := render(item.Type)
				if item.Recv != nil && len(item.Recv.List) == 1 {
					receiver := receiverName(item.Recv.List[0])
					name = receiver + "." + name
					kind = "method"
					signature = receiver + " " + signature
				}
				symbols = append(symbols, symbol{packagePath, kind, name, signature})
			case *ast.GenDecl:
				for _, spec := range item.Specs {
					switch value := spec.(type) {
					case *ast.TypeSpec:
						if value.Name.IsExported() {
							symbols = append(symbols, symbol{packagePath, "type", value.Name.Name, render(value)})
						}
					case *ast.ValueSpec:
						kind := strings.ToLower(item.Tok.String())
						signature := render(value)
						for _, name := range value.Names {
							if name.IsExported() {
								symbols = append(symbols, symbol{packagePath, kind, name.Name, signature})
							}
						}
					}
				}
			}
		}
		return nil
	})
	if err != nil {
		panic(err)
	}
	sort.Slice(symbols, func(i, j int) bool {
		left := symbols[i].PackagePath + "::" + symbols[i].Kind + "::" + symbols[i].Name
		right := symbols[j].PackagePath + "::" + symbols[j].Kind + "::" + symbols[j].Name
		return left < right
	})
	output, err := json.Marshal(symbols)
	if err != nil {
		panic(err)
	}
	fmt.Println(string(output))
}
'''

_GO_SEMANTIC_SNAPSHOT = r'''
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type declaration struct {
	PackagePath   string `json:"package_path"`
	Kind          string `json:"kind"`
	Name          string `json:"name"`
	SemanticSHA256 string `json:"semantic_sha256"`
}

func render(node any) string {
	var output bytes.Buffer
	if err := format.Node(&output, token.NewFileSet(), node); err != nil {
		panic(err)
	}
	return output.String()
}

func digest(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}

func receiverName(field *ast.Field) string {
	value := strings.TrimPrefix(render(field.Type), "*")
	if index := strings.Index(value, "["); index >= 0 {
		value = value[:index]
	}
	return value
}

func main() {
	if len(os.Args) != 3 {
		panic("usage: semantics <sdk-root> <service>")
	}
	root := filepath.Join(os.Args[1], "openstack", os.Args[2])
	var declarations []declaration
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.SkipObjectResolution)
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(os.Args[1], filepath.Dir(path))
		if err != nil {
			return err
		}
		packagePath := filepath.ToSlash(relative)
		for _, item := range file.Decls {
			switch value := item.(type) {
			case *ast.FuncDecl:
				name := value.Name.Name
				kind := "func"
				if value.Recv != nil && len(value.Recv.List) == 1 {
					name = receiverName(value.Recv.List[0]) + "." + name
					kind = "method"
				}
				declarations = append(declarations, declaration{
					PackagePath: packagePath,
					Kind: kind,
					Name: name,
					SemanticSHA256: digest(render(value)),
				})
			case *ast.GenDecl:
				if value.Tok == token.IMPORT {
					continue
				}
				for _, spec := range value.Specs {
					switch typed := spec.(type) {
					case *ast.TypeSpec:
						declarations = append(declarations, declaration{
							PackagePath: packagePath,
							Kind: "type",
							Name: typed.Name.Name,
							SemanticSHA256: digest(render(typed)),
						})
					case *ast.ValueSpec:
						semantic := digest(value.Tok.String() + " " + render(typed))
						for _, name := range typed.Names {
							declarations = append(declarations, declaration{
								PackagePath: packagePath,
								Kind: strings.ToLower(value.Tok.String()),
								Name: name.Name,
								SemanticSHA256: semantic,
							})
						}
					}
				}
			}
		}
		return nil
	})
	if err != nil {
		panic(err)
	}
	sort.Slice(declarations, func(i, j int) bool {
		left := declarations[i].PackagePath + "::" + declarations[i].Kind + "::" + declarations[i].Name
		right := declarations[j].PackagePath + "::" + declarations[j].Kind + "::" + declarations[j].Name
		return left < right
	})
	if err := json.NewEncoder(os.Stdout).Encode(declarations); err != nil {
		panic(err)
	}
}
'''

_GO_OPERATION_MIGRATOR = r'''
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/printer"
	"go/token"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"unicode"
)

type operation struct {
	Operation  string `json:"operation"`
	SourcePath string `json:"source_path"`
	TargetPath string `json:"target_path"`
}

type request struct {
	LegacyFiles []string    `json:"legacy_files"`
	Operations  []operation `json:"operations"`
}

type response struct {
	Files             map[string]string   `json:"files"`
	RemovedFiles      []string            `json:"removed_files"`
	MovedDeclarations map[string][]string `json:"moved_declarations"`
}

func lowerFirst(value string) string {
	runes := []rune(value)
	if len(runes) > 0 {
		runes[0] = unicode.ToLower(runes[0])
	}
	return string(runes)
}

func render(node any) string {
	var output bytes.Buffer
	if err := format.Node(&output, token.NewFileSet(), node); err != nil {
		panic(err)
	}
	return output.String()
}

func receiverName(field *ast.Field) string {
	value := strings.TrimPrefix(render(field.Type), "*")
	if index := strings.Index(value, "["); index >= 0 {
		value = value[:index]
	}
	return value
}

func declarationNames(declaration ast.Decl) []string {
	switch item := declaration.(type) {
	case *ast.FuncDecl:
		if item.Recv != nil && len(item.Recv.List) == 1 {
			return []string{receiverName(item.Recv.List[0]) + "." + item.Name.Name}
		}
		return []string{item.Name.Name}
	case *ast.GenDecl:
		var names []string
		for _, spec := range item.Specs {
			switch value := spec.(type) {
			case *ast.TypeSpec:
				names = append(names, value.Name.Name)
			case *ast.ValueSpec:
				for _, name := range value.Names {
					names = append(names, name.Name)
				}
			}
		}
		return names
	}
	return nil
}

func directOwner(declaration ast.Decl, operations []operation) string {
	if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv == nil {
		for _, item := range operations {
			if function.Name.Name == item.Operation {
				return item.Operation
			}
		}
	}
	best := ""
	for _, name := range declarationNames(declaration) {
		for _, item := range operations {
			lower := lowerFirst(item.Operation)
			if strings.HasPrefix(name, item.Operation) || strings.HasPrefix(name, lower) {
				if len(item.Operation) > len(best) {
					best = item.Operation
				}
			}
		}
	}
	return best
}

func referencedNames(declaration ast.Decl) map[string]bool {
	references := map[string]bool{}
	ast.Inspect(declaration, func(node ast.Node) bool {
		if identifier, ok := node.(*ast.Ident); ok {
			references[identifier.Name] = true
		}
		return true
	})
	for _, name := range declarationNames(declaration) {
		delete(references, name)
		if index := strings.Index(name, "."); index >= 0 {
			delete(references, name[:index])
		}
	}
	return references
}

func importAlias(spec *ast.ImportSpec) string {
	if spec.Name != nil {
		return spec.Name.Name
	}
	value, err := strconv.Unquote(spec.Path.Value)
	if err != nil {
		panic(err)
	}
	return path.Base(value)
}

func usedImportAliases(declarations []ast.Decl) map[string]bool {
	used := map[string]bool{}
	for _, declaration := range declarations {
		ast.Inspect(declaration, func(node ast.Node) bool {
			if selector, ok := node.(*ast.SelectorExpr); ok {
				if identifier, ok := selector.X.(*ast.Ident); ok {
					used[identifier.Name] = true
				}
			}
			return true
		})
	}
	return used
}

func commentsFor(
	comments []*ast.CommentGroup,
	declarations []ast.Decl,
	packageDoc *ast.CommentGroup,
) []*ast.CommentGroup {
	var selected []*ast.CommentGroup
	for _, comment := range comments {
		if comment == packageDoc && packageDoc != nil {
			selected = append(selected, comment)
			continue
		}
		for _, declaration := range declarations {
			isDoc := false
			switch item := declaration.(type) {
			case *ast.FuncDecl:
				isDoc = comment == item.Doc
			case *ast.GenDecl:
				isDoc = comment == item.Doc
			}
			if isDoc || (comment.Pos() >= declaration.Pos() && comment.End() <= declaration.End()) {
				selected = append(selected, comment)
				break
			}
		}
	}
	return selected
}

func buildFile(
	fileSet *token.FileSet,
	packageName *ast.Ident,
	imports []*ast.ImportSpec,
	declarations []ast.Decl,
	comments []*ast.CommentGroup,
	packageDoc *ast.CommentGroup,
) string {
	used := usedImportAliases(declarations)
	var selected []ast.Spec
	for _, spec := range imports {
		alias := importAlias(spec)
		if used[alias] || alias == "_" || alias == "." {
			selected = append(selected, spec)
		}
	}
	var allDeclarations []ast.Decl
	if len(selected) > 0 {
		allDeclarations = append(allDeclarations, &ast.GenDecl{Tok: token.IMPORT, Specs: selected})
	}
	allDeclarations = append(allDeclarations, declarations...)
	file := &ast.File{Name: packageName, Decls: allDeclarations, Doc: packageDoc}
	var output bytes.Buffer
	commented := &printer.CommentedNode{
		Node:     file,
		Comments: commentsFor(comments, declarations, packageDoc),
	}
	if err := format.Node(&output, fileSet, commented); err != nil {
		panic(err)
	}
	return output.String()
}

func declarationsWithoutImports(file *ast.File) []ast.Decl {
	var declarations []ast.Decl
	for _, declaration := range file.Decls {
		if general, ok := declaration.(*ast.GenDecl); ok && general.Tok == token.IMPORT {
			continue
		}
		declarations = append(declarations, declaration)
	}
	return declarations
}

func main() {
	if len(os.Args) != 2 {
		panic("usage: migrate <sdk-root>")
	}
	var input request
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		panic(err)
	}
	bySource := map[string][]operation{}
	for _, item := range input.Operations {
		bySource[item.SourcePath] = append(bySource[item.SourcePath], item)
	}
	deletable := map[string]bool{}
	for _, legacyPath := range input.LegacyFiles {
		deletable[legacyPath] = true
	}
	output := response{
		Files:             map[string]string{},
		RemovedFiles:      []string{},
		MovedDeclarations: map[string][]string{},
	}
	for sourcePath, operations := range bySource {
		fullPath := filepath.Join(os.Args[1], filepath.FromSlash(sourcePath))
		fileSet := token.NewFileSet()
		file, err := parser.ParseFile(fileSet, fullPath, nil, parser.ParseComments|parser.SkipObjectResolution)
		if err != nil {
			panic(err)
		}
		var imports []*ast.ImportSpec
		for _, spec := range file.Imports {
			imports = append(imports, spec)
		}
		declarations := declarationsWithoutImports(file)
		nameToDeclarations := map[string][]int{}
		for index, declaration := range declarations {
			for _, name := range declarationNames(declaration) {
				if separator := strings.Index(name, "."); separator >= 0 {
					name = name[:separator]
				}
				nameToDeclarations[name] = append(nameToDeclarations[name], index)
			}
		}
		owners := make([]map[string]bool, len(declarations))
		for index, declaration := range declarations {
			owners[index] = map[string]bool{}
			if owner := directOwner(declaration, operations); owner != "" {
				owners[index][owner] = true
			}
		}
		changed := true
		for changed {
			changed = false
			for index, declaration := range declarations {
				for reference := range referencedNames(declaration) {
					for _, dependency := range nameToDeclarations[reference] {
						for owner := range owners[index] {
							if !owners[dependency][owner] {
								owners[dependency][owner] = true
								changed = true
							}
						}
					}
				}
			}
		}
		owned := map[string][]ast.Decl{}
		var remaining []ast.Decl
		for index, declaration := range declarations {
			if len(owners[index]) == 1 {
				for owner := range owners[index] {
					owned[owner] = append(owned[owner], declaration)
					output.MovedDeclarations[owner] = append(
						output.MovedDeclarations[owner],
						declarationNames(declaration)...,
					)
				}
			} else {
				remaining = append(remaining, declaration)
			}
		}
		if len(remaining) == 0 && deletable[sourcePath] {
			output.RemovedFiles = append(output.RemovedFiles, sourcePath)
		} else {
			output.Files[sourcePath] = buildFile(fileSet, file.Name, imports, remaining, file.Comments, file.Doc)
		}
		for _, item := range operations {
			declarations := owned[item.Operation]
			foundOperation := false
			for _, declaration := range declarations {
				if function, ok := declaration.(*ast.FuncDecl); ok && function.Recv == nil && function.Name.Name == item.Operation {
					foundOperation = true
				}
			}
			if !foundOperation {
				panic(fmt.Sprintf("operation declaration %s was not found in %s", item.Operation, sourcePath))
			}
			output.Files[item.TargetPath] = buildFile(fileSet, file.Name, imports, declarations, file.Comments, nil)
		}
	}
	processed := map[string]bool{}
	for sourcePath := range bySource {
		processed[sourcePath] = true
	}
	for _, legacyPath := range input.LegacyFiles {
		if processed[legacyPath] {
			continue
		}
		fullPath := filepath.Join(os.Args[1], filepath.FromSlash(legacyPath))
		file, err := parser.ParseFile(token.NewFileSet(), fullPath, nil, parser.SkipObjectResolution)
		if err != nil {
			panic(err)
		}
		if len(declarationsWithoutImports(file)) == 0 {
			output.RemovedFiles = append(output.RemovedFiles, legacyPath)
		}
	}
	if err := json.NewEncoder(os.Stdout).Encode(output); err != nil {
		panic(err)
	}
}
'''

_GO_OPERATION_FILE_VALIDATOR = r'''
package main

import (
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type operation struct {
	Name string `json:"name"`
	Path string `json:"path"`
}

type violation struct {
	Code         string `json:"code"`
	Operation    string `json:"operation"`
	Path         string `json:"path"`
	ExpectedPath string `json:"expected_path"`
}

type response struct {
	Operations []operation `json:"operations"`
	Violations []violation `json:"violations"`
}

var prefixes = []string{
	"Create", "Delete", "Get", "List", "Update", "Batch", "Show", "Set", "Reset",
	"Enable", "Disable", "Associate", "Disassociate", "Attach", "Detach", "Bind",
	"Unbind", "Invoke", "Publish", "Cancel", "Import", "Export",
}

func isOperation(name string) bool {
	if !ast.IsExported(name) {
		return false
	}
	for _, prefix := range prefixes {
		if strings.HasPrefix(name, prefix) {
			return true
		}
	}
	return false
}

func main() {
	if len(os.Args) != 3 && len(os.Args) != 4 {
		panic("usage: validate <sdk-root> <service> [operation,...]")
	}
	root := filepath.Join(os.Args[1], "openstack", os.Args[2])
	selected := map[string]bool{}
	if len(os.Args) == 4 {
		for _, name := range strings.Split(os.Args[3], ",") {
			selected[name] = true
		}
	}
	output := response{Operations: []operation{}, Violations: []violation{}}
	counts := map[string]int{}
	expectedByName := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.SkipObjectResolution)
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(os.Args[1], path)
		if err != nil {
			return err
		}
		relative = filepath.ToSlash(relative)
		for _, declaration := range file.Decls {
			function, ok := declaration.(*ast.FuncDecl)
			if !ok || function.Recv != nil || !isOperation(function.Name.Name) {
				continue
			}
			name := function.Name.Name
			if len(selected) > 0 && !selected[name] {
				continue
			}
			counts[name]++
			output.Operations = append(output.Operations, operation{Name: name, Path: relative})
			expected := filepath.ToSlash(filepath.Join(filepath.Dir(relative), name+".go"))
			if _, exists := expectedByName[name]; !exists {
				expectedByName[name] = expected
			}
			if relative != expected {
				output.Violations = append(output.Violations, violation{
					Code:         "operation_file_mismatch",
					Operation:    name,
					Path:         relative,
					ExpectedPath: expected,
				})
			}
		}
		return nil
	})
	if err != nil {
		panic(err)
	}
	for name, count := range counts {
		if count > 1 {
			expected := expectedByName[name]
			output.Violations = append(output.Violations, violation{
				Code:         "duplicate_operation",
				Operation:    name,
				Path:         expected,
				ExpectedPath: expected,
			})
		}
	}
	sort.Slice(output.Operations, func(i, j int) bool {
		if output.Operations[i].Name == output.Operations[j].Name {
			return output.Operations[i].Path < output.Operations[j].Path
		}
		return output.Operations[i].Name < output.Operations[j].Name
	})
	sort.Slice(output.Violations, func(i, j int) bool {
		left := output.Violations[i].Operation + "::" + output.Violations[i].Code + "::" + output.Violations[i].Path
		right := output.Violations[j].Operation + "::" + output.Violations[j].Code + "::" + output.Violations[j].Path
		return left < right
	})
	if err := json.NewEncoder(os.Stdout).Encode(output); err != nil {
		panic(err)
	}
}
'''

_GO_BEHAVIOR_INVENTORY = r'''
package main

import (
	"bytes"
	"encoding/json"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

var prefixes = []string{
	"Create", "Delete", "Get", "List", "Update", "Batch", "Show", "Set", "Reset",
	"Enable", "Disable", "Associate", "Disassociate", "Attach", "Detach", "Bind",
	"Unbind", "Invoke", "Publish", "Cancel", "Import", "Export",
}

var signals = map[string][]string{
	"request":    {"request", "method", "body", "url", "path"},
	"response":   {"response", "result", "extract"},
	"error":      {"error", "failure", "status"},
	"zero_value": {"zerovalue", "zero_value", "zero value", "empty", "false"},
	"pagination": {"pagination", "page", "next"},
	"fixture":    {"fixture", "setuphttp", "handlefunc", "testserver", "json"},
}

func isOperation(name string) bool {
	if !ast.IsExported(name) {
		return false
	}
	for _, prefix := range prefixes {
		if strings.HasPrefix(name, prefix) {
			return true
		}
	}
	return false
}

func render(node any) string {
	var output bytes.Buffer
	if err := format.Node(&output, token.NewFileSet(), node); err != nil {
		panic(err)
	}
	return output.String()
}

func main() {
	if len(os.Args) != 3 {
		panic("usage: behavior <sdk-root> <service>")
	}
	root := filepath.Join(os.Args[1], "openstack", os.Args[2])
	operations := map[string]bool{}
	var tests []*ast.FuncDecl
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") {
			return nil
		}
		file, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.SkipObjectResolution)
		if err != nil {
			return err
		}
		for _, declaration := range file.Decls {
			function, ok := declaration.(*ast.FuncDecl)
			if !ok || function.Recv != nil {
				continue
			}
			if strings.HasSuffix(path, "_test.go") && strings.HasPrefix(function.Name.Name, "Test") {
				tests = append(tests, function)
			} else if !strings.HasSuffix(path, "_test.go") && isOperation(function.Name.Name) {
				operations[function.Name.Name] = true
			}
		}
		return nil
	})
	if err != nil {
		panic(err)
	}
	output := map[string][]string{}
	for operation := range operations {
		covered := map[string]bool{}
		for _, test := range tests {
			corpus := strings.ToLower(test.Name.Name + " " + render(test))
			if !strings.Contains(corpus, strings.ToLower(operation)) {
				continue
			}
			for category, categorySignals := range signals {
				for _, signal := range categorySignals {
					if strings.Contains(corpus, signal) {
						covered[category] = true
						break
					}
				}
			}
		}
		for category := range covered {
			output[operation] = append(output[operation], category)
		}
		sort.Strings(output[operation])
		if output[operation] == nil {
			output[operation] = []string{}
		}
	}
	if err := json.NewEncoder(os.Stdout).Encode(output); err != nil {
		panic(err)
	}
}
'''
