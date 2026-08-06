import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otc_agent.generation import CommandEvidence, generate_sdk_candidate
from otc_agent.model import ModelResult


class FakeModel:
    def generate_json(self, *, system: str, user: str, budget: object) -> ModelResult:
        self.system = system
        self.user = user
        return ModelResult(
            value={
                "summary": "Add the documented widget endpoint.",
                "patch": """diff --git a/openstack/demo/v1/widgets/requests.go b/openstack/demo/v1/widgets/requests.go
new file mode 100644
index 0000000..ab00000
--- /dev/null
+++ b/openstack/demo/v1/widgets/requests.go
@@ -0,0 +1 @@
+package widgets
""",
                "assumptions": [],
                "citations": [
                    {
                        "path": "api-ref/source/index.rst",
                        "line_start": 1,
                        "line_end": 3,
                    }
                ],
            },
            model="fake-model",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.001,
        )


def initialize_repository(root: Path, files: dict[str, str]) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.test", "commit", "-qm", "base"],
        cwd=root,
        check=True,
    )


class GenerationTests(unittest.TestCase):
    def test_sdk_generation_produces_cited_new_file_patch_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "sdk"
            docs = root / "docs"
            sdk.mkdir()
            docs.mkdir()
            initialize_repository(sdk, {"README.md": "SDK\n"})
            initialize_repository(
                docs,
                {"api-ref/source/index.rst": "Demo API\n========\nPOST /v1/widgets\n"},
            )
            plan = {
                "mapping": {"sdk": "demo", "provider": "demo", "docs": "demo", "display_name": "Demo"},
                "classification": {"kind": "feature", "confidence": 0.92},
                "request": {"description": "Add the POST /v1/widgets endpoint"},
            }
            successful = CommandEvidence(("test",), 0, 0.01, "ok")

            with patch("otc_agent.generation._run", return_value=successful):
                record = generate_sdk_candidate(
                    plan=plan,
                    sdk_root=sdk,
                    docs_root=docs,
                    output_dir=root / "generated",
                    model=FakeModel(),
                )

            candidate = (root / "generated/sdk.patch").read_text(encoding="utf-8")
            evidence = json.loads((root / "generated/sdk-evidence.json").read_text(encoding="utf-8"))
            self.assertIn("openstack/demo/v1/widgets/requests.go", candidate)
            self.assertEqual(record.changed_paths, ("openstack/demo/v1/widgets/requests.go",))
            self.assertEqual(evidence["citations"][0]["path"], "api-ref/source/index.rst")
            self.assertEqual(evidence["model"], "fake-model")
            self.assertEqual(evidence["schema_version"], 2)
            self.assertEqual(evidence["skill"]["id"], "generate-sdk")
            self.assertEqual(evidence["skill"]["version"], 1)
            self.assertEqual(
                {item["id"] for item in evidence["policies"]},
                {"sdk-coding", "testing", "security"},
            )

    def test_refactoring_generation_records_refactor_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "sdk"
            docs = root / "docs"
            sdk.mkdir()
            docs.mkdir()
            initialize_repository(sdk, {"README.md": "SDK\n"})
            initialize_repository(
                docs,
                {"api-ref/source/index.rst": "Demo API\n========\nPOST /v1/widgets\n"},
            )
            plan = {
                "mapping": {"sdk": "demo", "provider": "demo", "docs": "demo", "display_name": "Demo"},
                "classification": {"kind": "refactoring", "confidence": 1.0},
                "request": {"description": "Migrate the legacy widget operation layout"},
            }
            successful = CommandEvidence(("test",), 0, 0.01, "ok")

            with patch("otc_agent.generation._run", return_value=successful):
                record = generate_sdk_candidate(
                    plan=plan,
                    sdk_root=sdk,
                    docs_root=docs,
                    output_dir=root / "generated",
                    model=FakeModel(),
                )

            self.assertEqual(record.skill["id"], "refactor-sdk")
            self.assertEqual(
                {item["id"] for item in record.policies},
                {"sdk-layout", "sdk-coding", "testing", "security"},
            )


if __name__ == "__main__":
    unittest.main()
