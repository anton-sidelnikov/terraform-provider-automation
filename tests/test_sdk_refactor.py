import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from otc_agent.cli import main
from otc_agent.sdk_layout import analyze_sdk_layout
from otc_agent.sdk_refactor import (
    SDKRefactorPlanError,
    apply_operation_file_migration,
    build_operation_migration_plan,
    capture_exported_api,
    capture_semantic_snapshot,
    validate_exported_api_compatibility,
    validate_operation_file_correspondence,
    validate_semantic_preservation,
    verify_refactor_behavior,
)


def write_service(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / "openstack" / "demo" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def write_behavior_tests(root: Path, operations: tuple[str, ...]) -> None:
    tests = ["package widgets\n\nimport \"testing\"\n"]
    for operation in operations:
        tests.append(
            f"func Test{operation}RequestResponseErrorZeroValueFixturePagination(t *testing.T) {{}}\n"
        )
    write_service(root, {"v1/widgets/behavior_test.go": "\n".join(tests)})


class SDKRefactorPlanTests(unittest.TestCase):
    def test_builds_package_scoped_operation_migration_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": "package widgets\nfunc Create() {}\nfunc ListWidgets() {}\n",
                    "v1/widgets/urls.go": "package widgets\nfunc resourceURL() string { return \"\" }\n",
                },
            )

            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            self.assertEqual(plan.status, "ready")
            self.assertEqual(
                [item.target_path for item in plan.operations],
                [
                    "openstack/demo/v1/widgets/Create.go",
                    "openstack/demo/v1/widgets/ListWidgets.go",
                ],
            )
            self.assertEqual(len(plan.batches), 2)
            self.assertEqual(
                [item.operations for item in plan.batches],
                [("Create",), ("ListWidgets",)],
            )
            self.assertTrue(all(item.branch_suffix.startswith("refactor-") for item in plan.batches))
            self.assertIn("openstack/demo/v1/widgets/urls.go", plan.legacy_files)

    def test_plans_only_remaining_legacy_operations_in_mixed_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/Create.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/results.go": "package widgets\nfunc Get() {}\n",
                },
            )

            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            self.assertEqual([item.operation for item in plan.operations], ["Get"])
            self.assertEqual(plan.operations[0].target_path, "openstack/demo/v1/widgets/Get.go")

    def test_blocks_duplicate_operation_or_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/results.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/Create.go": "package widgets\ntype CreateOpts struct{}\n",
                },
            )

            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            self.assertEqual(plan.status, "blocked")
            self.assertTrue(any("declared more than once" in item for item in plan.blocked_reasons))
            self.assertTrue(any("target file already exists" in item for item in plan.blocked_reasons))

    def test_rejects_modern_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(root, {"v1/widgets/Create.go": "package widgets\nfunc Create() {}\n"})

            with self.assertRaises(SDKRefactorPlanError):
                build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

    def test_refactor_cli_rejects_stale_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(root, {"v1/widgets/requests.go": "package widgets\nfunc Create() {}\n"})
            layout = analyze_sdk_layout(root, "demo").as_dict()
            layout["legacy_files"] = []
            input_path = root / "input.json"
            input_path.write_text(
                json.dumps(
                    {
                        "specification": {"kind": "refactoring"},
                        "layout": layout,
                        "sdk_root": str(root),
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "stale"):
                with redirect_stdout(io.StringIO()):
                    main(["refactor-sdk", "--input", str(input_path)])

    def test_exported_api_snapshot_ignores_file_moves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": (
                        "package widgets\n"
                        "type CreateOpts struct { Name string }\n"
                        "func Create(opts CreateOpts) (string, error) { return \"\", nil }\n"
                    )
                },
            )
            baseline = capture_exported_api(root, "demo")
            source = root / "openstack/demo/v1/widgets/requests.go"
            target = source.with_name("Create.go")
            source.rename(target)
            candidate = capture_exported_api(root, "demo")

            report = validate_exported_api_compatibility(baseline, candidate)

            self.assertTrue(report.compatible)
            self.assertEqual(report.changed, ())
            self.assertEqual(report.removed, ())

    def test_exported_signature_change_requires_exact_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {"v1/widgets/requests.go": "package widgets\nfunc Create(name string) error { return nil }\n"},
            )
            baseline = capture_exported_api(root, "demo")
            path = root / "openstack/demo/v1/widgets/requests.go"
            path.write_text(
                "package widgets\nfunc Create(name string, force bool) error { return nil }\n",
                encoding="utf-8",
            )
            candidate = capture_exported_api(root, "demo")
            identifier = "openstack/demo/v1/widgets::func::Create"

            rejected = validate_exported_api_compatibility(baseline, candidate)
            approved = validate_exported_api_compatibility(baseline, candidate, (identifier,))

            self.assertFalse(rejected.compatible)
            self.assertEqual(rejected.violations, (identifier,))
            self.assertTrue(approved.compatible)
            self.assertEqual(approved.changed, (identifier,))

    def test_semantic_guard_rejects_body_change_with_same_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {"v1/widgets/requests.go": "package widgets\nfunc Create() string { return \"before\" }\n"},
            )
            baseline = capture_semantic_snapshot(root, "demo")
            path = root / "openstack/demo/v1/widgets/requests.go"
            path.write_text(
                "package widgets\nfunc Create() string { return \"after\" }\n",
                encoding="utf-8",
            )
            candidate = capture_semantic_snapshot(root, "demo")
            identifier = "openstack/demo/v1/widgets::func::Create"

            rejected = validate_semantic_preservation(baseline, candidate)
            approved = validate_semantic_preservation(baseline, candidate, (identifier,))

            self.assertFalse(rejected.compatible)
            self.assertEqual(rejected.violations, (identifier,))
            self.assertTrue(approved.compatible)
            self.assertEqual(approved.changed, (identifier,))

    def test_refactor_cli_blocks_unapproved_candidate_api_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "baseline"
            candidate = Path(directory) / "candidate"
            write_service(
                root,
                {"v1/widgets/requests.go": "package widgets\nfunc Create(name string) error { return nil }\n"},
            )
            shutil.copytree(root, candidate)
            candidate_file = candidate / "openstack/demo/v1/widgets/requests.go"
            candidate_file.write_text(
                "package widgets\nfunc Create(name string, force bool) error { return nil }\n",
                encoding="utf-8",
            )
            input_path = Path(directory) / "input.json"
            input_path.write_text(
                json.dumps(
                    {
                        "specification": {"kind": "refactoring"},
                        "layout": analyze_sdk_layout(root, "demo").as_dict(),
                        "sdk_root": str(root),
                        "candidate_sdk_root": str(candidate),
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                result = main(["refactor-sdk", "--input", str(input_path)])

            value = json.loads(output.getvalue())
            self.assertEqual(result, 3)
            self.assertEqual(value["status"], "blocked")
            self.assertFalse(value["compatibility"]["compatible"])

    def test_applies_operation_local_declarations_to_operation_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": (
                        "package widgets\n\n"
                        'import "net/url"\n\n'
                        "type Widget struct { ID string }\n"
                        "type CreateOpts struct { Name string }\n"
                        "type CreateResult struct { Body Widget }\n"
                        "type CreateOptsBuilder interface { ToCreateMap() map[string]any }\n"
                        "func (opts CreateOpts) ToCreateMap() map[string]any { return map[string]any{\"name\": opts.Name} }\n"
                        "// createURL keeps the operation endpoint local.\n"
                        "func createURL() string {\n"
                        "\t// Preserve inline migration comments.\n"
                        "\treturn (&url.URL{Path: \"/widgets\"}).String()\n"
                        "}\n"
                        "func sharedURL() string { return \"/widgets\" }\n"
                        "func Create(opts CreateOpts) (CreateResult, error) { "
                        "return CreateResult{Body: Widget{ID: createURL()}}, nil }\n"
                        "func List() ([]Widget, error) { return []Widget{}, nil }\n"
                    )
                },
            )
            write_behavior_tests(root, ("Create", "List"))
            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            applied = apply_operation_file_migration(root, plan)

            target = (root / "openstack/demo/v1/widgets/Create.go").read_text(encoding="utf-8")
            source = (root / "openstack/demo/v1/widgets/requests.go").read_text(encoding="utf-8")
            self.assertIn("type CreateOpts struct", target)
            self.assertIn("type CreateResult struct", target)
            self.assertIn("type CreateOptsBuilder interface", target)
            self.assertIn("func (opts CreateOpts) ToCreateMap()", target)
            self.assertIn("func createURL()", target)
            self.assertIn("// createURL keeps the operation endpoint local.", target)
            self.assertIn("// Preserve inline migration comments.", target)
            self.assertIn("func Create(", target)
            self.assertIn('"net/url"', target)
            self.assertIn("type Widget struct", source)
            self.assertIn("func sharedURL()", source)
            self.assertNotIn("type CreateOpts struct", source)
            self.assertIn(
                "func List() ([]Widget, error)",
                (root / "openstack/demo/v1/widgets/List.go").read_text(encoding="utf-8"),
            )
            self.assertTrue(applied.compatibility.compatible)
            self.assertTrue(applied.semantics.compatible)
            self.assertTrue(applied.operation_files.valid)
            self.assertEqual(
                applied.moved_declarations["Create"],
                (
                    "CreateOpts",
                    "CreateResult",
                    "CreateOptsBuilder",
                    "CreateOpts.ToCreateMap",
                    "createURL",
                    "Create",
                ),
            )

    def test_refactor_cli_applies_migration_only_when_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": (
                        "package widgets\n"
                        "type CreateOpts struct { Name string }\n"
                        "func Create(opts CreateOpts) error { return nil }\n"
                    )
                },
            )
            write_behavior_tests(root, ("Create",))
            input_path = root / "input.json"
            input_path.write_text(
                json.dumps(
                    {
                        "specification": {"kind": "refactoring"},
                        "layout": analyze_sdk_layout(root, "demo").as_dict(),
                        "sdk_root": str(root),
                        "apply": True,
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                result = main(["refactor-sdk", "--input", str(input_path)])

            value = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(value["status"], "ready")
            self.assertTrue(value["compatibility"]["compatible"])
            self.assertTrue((root / "openstack/demo/v1/widgets/Create.go").exists())
            self.assertTrue(value["operation_files"]["valid"])

    def test_multi_operation_apply_requires_and_honors_route_migration_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": (
                        "package widgets\n"
                        "func Create() error { return nil }\n"
                        "func List() error { return nil }\n"
                    )
                },
            )
            write_behavior_tests(root, ("Create", "List"))
            layout = analyze_sdk_layout(root, "demo")
            plan = build_operation_migration_plan(root, layout)
            create_migration = next(
                item for item in plan.batches if item.operations == ("Create",)
            )
            input_path = root / "input.json"
            base_input = {
                "specification": {"kind": "refactoring"},
                "layout": layout.as_dict(),
                "sdk_root": str(root),
                "apply": True,
            }
            input_path.write_text(json.dumps(base_input), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "migration_id"):
                main(["refactor-sdk", "--input", str(input_path)])

            base_input["migration_id"] = create_migration.migration_id
            input_path.write_text(json.dumps(base_input), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["refactor-sdk", "--input", str(input_path)])

            value = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(value["selected_migration"]["operations"], ["Create"])
            self.assertTrue((root / "openstack/demo/v1/widgets/Create.go").exists())
            self.assertFalse((root / "openstack/demo/v1/widgets/List.go").exists())
            self.assertIn(
                "func List() error",
                (root / "openstack/demo/v1/widgets/requests.go").read_text(encoding="utf-8"),
            )

    def test_keeps_transitively_shared_declarations_in_common_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/results.go": (
                        "package widgets\n"
                        "type SharedEnvelope struct { Value string }\n"
                        "type createPayload struct { Envelope SharedEnvelope }\n"
                        "type updatePayload struct { Envelope SharedEnvelope }\n"
                        "func Create() createPayload { return createPayload{} }\n"
                        "func Update() updatePayload { return updatePayload{} }\n"
                    )
                },
            )
            write_behavior_tests(root, ("Create", "Update"))
            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            applied = apply_operation_file_migration(root, plan)

            common = (root / "openstack/demo/v1/widgets/results.go").read_text(encoding="utf-8")
            create = (root / "openstack/demo/v1/widgets/Create.go").read_text(encoding="utf-8")
            update = (root / "openstack/demo/v1/widgets/Update.go").read_text(encoding="utf-8")
            self.assertIn("type SharedEnvelope struct", common)
            self.assertNotIn("type SharedEnvelope struct", create)
            self.assertNotIn("type SharedEnvelope struct", update)
            self.assertIn("type createPayload struct", create)
            self.assertIn("type updatePayload struct", update)
            self.assertNotIn("SharedEnvelope", applied.moved_declarations["Create"])
            self.assertNotIn("SharedEnvelope", applied.moved_declarations["Update"])

    def test_removes_only_semantically_empty_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": "package widgets\nfunc Create() error { return nil }\n",
                    "v1/widgets/urls.go": "package widgets\n",
                    "v1/widgets/results.go": "package widgets\ntype SharedResult struct { ID string }\n",
                },
            )
            write_behavior_tests(root, ("Create",))
            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            applied = apply_operation_file_migration(root, plan)

            self.assertFalse((root / "openstack/demo/v1/widgets/requests.go").exists())
            self.assertFalse((root / "openstack/demo/v1/widgets/urls.go").exists())
            self.assertTrue((root / "openstack/demo/v1/widgets/results.go").exists())
            self.assertEqual(
                applied.removed_paths,
                (
                    "openstack/demo/v1/widgets/requests.go",
                    "openstack/demo/v1/widgets/urls.go",
                ),
            )
            self.assertTrue((root / "openstack/demo/v1/widgets/Create.go").exists())

    def test_behavior_gate_requires_pagination_for_list_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/List.go": "package widgets\nfunc List() error { return nil }\n",
                    "v1/widgets/list_test.go": (
                        "package widgets\n"
                        'import "testing"\n'
                        "func TestListRequestResponseErrorZeroValueFixture(t *testing.T) {}\n"
                    ),
                },
            )
            analysis_root = Path(directory) / "analysis"
            write_service(
                analysis_root,
                {"v1/widgets/requests.go": "package widgets\nfunc List() error { return nil }\n"},
            )
            plan = build_operation_migration_plan(
                analysis_root,
                analyze_sdk_layout(analysis_root, "demo"),
            )

            report = verify_refactor_behavior(root, "demo", plan.behavior_requirements)

            self.assertFalse(report.valid)
            self.assertTrue(report.test_passed)
            self.assertEqual(report.missing, {"List": ("pagination",)})

    def test_missing_behavior_evidence_rolls_back_applied_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {"v1/widgets/requests.go": "package widgets\nfunc Create() error { return nil }\n"},
            )
            plan = build_operation_migration_plan(root, analyze_sdk_layout(root, "demo"))

            with self.assertRaisesRegex(SDKRefactorPlanError, "coverage is incomplete"):
                apply_operation_file_migration(root, plan)

            self.assertTrue((root / "openstack/demo/v1/widgets/requests.go").exists())
            self.assertFalse((root / "openstack/demo/v1/widgets/Create.go").exists())

    def test_go_ast_validator_reports_operation_file_mismatch_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/other.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/List.go": "package widgets\nfunc List() {}\n",
                },
            )

            report = validate_operation_file_correspondence(root, "demo")

            self.assertFalse(report.valid)
            self.assertEqual(
                [item.code for item in report.violations],
                [
                    "duplicate_operation",
                    "operation_file_mismatch",
                    "operation_file_mismatch",
                ],
            )
            self.assertIn(
                {"name": "List", "path": "openstack/demo/v1/widgets/List.go"},
                report.operations,
            )


if __name__ == "__main__":
    unittest.main()
