import tempfile
import unittest
from pathlib import Path

from otc_agent.sdk_layout import LayoutKind, analyze_sdk_layout


def write_service(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / "openstack" / "demo" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


class SDKLayoutTests(unittest.TestCase):
    def test_modern_operation_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/Create.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/List.go": "package widgets\nfunc List() {}\n",
                },
            )

            result = analyze_sdk_layout(root, "demo")

            self.assertEqual(result.kind, LayoutKind.MODERN)
            self.assertFalse(result.requires_refactoring)
            self.assertEqual([item.name for item in result.operations], ["Create", "List"])

    def test_legacy_operations_in_generic_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/requests.go": (
                        "package widgets\n"
                        "func Create() {}\n"
                        "func ListWidgets() {}\n"
                    ),
                    "v1/widgets/urls.go": "package widgets\nfunc resourceURL() string { return \"\" }\n",
                },
            )

            result = analyze_sdk_layout(root, "demo")

            self.assertEqual(result.kind, LayoutKind.LEGACY)
            self.assertTrue(result.requires_refactoring)
            self.assertEqual(len(result.legacy_operations), 2)
            self.assertEqual(
                result.legacy_files,
                (
                    "openstack/demo/v1/widgets/requests.go",
                    "openstack/demo/v1/widgets/urls.go",
                ),
            )

    def test_mixed_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/Create.go": "package widgets\nfunc Create() {}\n",
                    "v1/widgets/results.go": "package widgets\nfunc Get() {}\n",
                },
            )

            result = analyze_sdk_layout(root, "demo")

            self.assertEqual(result.kind, LayoutKind.MIXED)
            self.assertTrue(result.requires_refactoring)
            self.assertEqual([item.name for item in result.legacy_operations], ["Get"])

    def test_generic_filenames_without_operations_are_not_legacy_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_service(
                root,
                {
                    "v1/widgets/results.go": "package widgets\ntype Widget struct{}\n",
                },
            )

            result = analyze_sdk_layout(root, "demo")

            self.assertEqual(result.kind, LayoutKind.UNKNOWN)
            self.assertFalse(result.requires_refactoring)


if __name__ == "__main__":
    unittest.main()

