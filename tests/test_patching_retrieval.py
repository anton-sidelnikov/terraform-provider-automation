import subprocess
import tempfile
import unittest
from pathlib import Path

from otc_agent.generation import provider_publish_policy
from otc_agent.model import ModelError, _parse_json_object
from otc_agent.patching import (
    PatchViolation,
    apply_patch,
    provider_policy,
    repository_diff,
    sdk_policy,
    validate_patch,
)
from otc_agent.retrieval import retrieve_api_reference


SDK_PATCH = """diff --git a/openstack/demo/v1/items/requests.go b/openstack/demo/v1/items/requests.go
new file mode 100644
index 0000000..ab00000
--- /dev/null
+++ b/openstack/demo/v1/items/requests.go
@@ -0,0 +1 @@
+package items
"""


class PatchingAndRetrievalTests(unittest.TestCase):
    def test_sdk_patch_is_confined_to_service(self) -> None:
        self.assertEqual(
            validate_patch(SDK_PATCH, sdk_policy("demo")),
            ("openstack/demo/v1/items/requests.go",),
        )
        with self.assertRaises(PatchViolation):
            validate_patch(SDK_PATCH, sdk_policy("other"))

    def test_workflow_and_binary_changes_are_rejected(self) -> None:
        malicious = SDK_PATCH.replace(
            "openstack/demo/v1/items/requests.go", ".github/workflows/pwn.yml"
        )
        with self.assertRaises(PatchViolation):
            validate_patch(malicious, sdk_policy("demo"))
        with self.assertRaises(PatchViolation):
            validate_patch(SDK_PATCH + "\nGIT binary patch\n", sdk_policy("demo"))

    def test_provider_dependency_files_are_executor_only(self) -> None:
        patch = """diff --git a/go.mod b/go.mod
index 1111111..2222222 100644
--- a/go.mod
+++ b/go.mod
@@ -1 +1 @@
-old
+new
"""
        with self.assertRaises(PatchViolation):
            validate_patch(patch, provider_policy("demo"))
        self.assertEqual(validate_patch(patch, provider_publish_policy("demo")), ("go.mod",))

    def test_patch_applies_in_disposable_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "add", "README"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "init"],
                cwd=root,
                check=True,
            )
            paths = apply_patch(root, SDK_PATCH, sdk_policy("demo"))
            self.assertEqual(paths, ("openstack/demo/v1/items/requests.go",))
            self.assertTrue((root / paths[0]).is_file())

    def test_repository_diff_includes_new_service_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "README").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "add", "README"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "init"],
                cwd=root,
                check=True,
            )
            generated = root / "openstack/new_service/v1/client.go"
            generated.parent.mkdir(parents=True)
            generated.write_text("package v1\n", encoding="utf-8")

            patch = repository_diff(root)

            self.assertIn("diff --git a/openstack/new_service/v1/client.go", patch)
            self.assertIn("+package v1", patch)

    def test_retrieval_is_api_ref_only_and_cited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "api-ref" / "source"
            source.mkdir(parents=True)
            (source / "index.rst").write_text("Demo API\n========\n", encoding="utf-8")
            (source / "create.rst").write_text(
                "Create Widget\n=============\nPOST /v1/widgets creates a widget.\n", encoding="utf-8"
            )
            chunks = retrieve_api_reference(
                root, repository="docs/demo", revision="abc", query="new endpoint create widget"
            )
            self.assertIn("POST /v1/widgets", chunks[0].content)
            self.assertTrue(chunks[0].sha256)
            self.assertTrue(chunks[0].path.startswith("api-ref/"))

    def test_model_json_parser_accepts_fence_but_requires_object(self) -> None:
        self.assertEqual(_parse_json_object('```json\n{"ok": true}\n```'), {"ok": True})
        with self.assertRaises(ModelError):
            _parse_json_object("[]")


if __name__ == "__main__":
    unittest.main()
