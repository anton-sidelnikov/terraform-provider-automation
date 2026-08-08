import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otc_agent.generation import CommandEvidence, generate_sdk_candidate
from otc_agent.model import ModelResult
from otc_agent.routing import ModelRoute, ModelTier


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


class FakeEvaluator:
    def generate_json(self, *, system: str, user: str, budget: object) -> ModelResult:
        return ModelResult(
            value={
                "decision": "pass",
                "scores": {
                    "correctness": 0.95,
                    "evidence": 0.95,
                    "tests": 0.9,
                    "scope": 1.0,
                    "maintainability": 0.9,
                },
                "findings": [],
            },
            model="evaluator-model",
            input_tokens=50,
            output_tokens=20,
            cost_usd=0.001,
        )


EVALUATOR_ROUTE = ModelRoute(
    "reviewer",
    ModelTier.STRONG,
    "copilot",
    "evaluator-model",
    "stdio:evaluator",
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


SDK_GUIDANCE_FILES = {
    "go.mod": "module example.com/sdk\n\ngo 1.22\n",
    "README.md": "SDK\n",
    "FAQ.md": "# FAQ\n",
    "STYLEGUIDE.md": "# Style guide\n",
    "CONTRIBUTING.md": "# Contributing\n",
    "openstack/apigw/v2/widgets/Create.go": "package widgets\n// Create a widget.\n",
    "openstack/apigw/v2/widgets/Create_test.go": (
        "package widgets\n\nimport \"testing\"\n\nfunc TestCreate(t *testing.T) {}\n"
    ),
    "openstack/apigw/v2/widgets/Get.go": "package widgets\n",
    "openstack/apigw/v2/widgets/Get_test.go": (
        "package widgets\n\nimport \"testing\"\n\nfunc TestGet(t *testing.T) {}\n"
    ),
    "openstack/fgs/v2/functions/List.go": "package functions\n",
    "openstack/fgs/v2/functions/List_test.go": (
        "package functions\n\nimport \"testing\"\n\nfunc TestList(t *testing.T) {}\n"
    ),
}


class GenerationTests(unittest.TestCase):
    def test_sdk_generation_produces_cited_new_file_patch_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "sdk"
            docs = root / "docs"
            sdk.mkdir()
            docs.mkdir()
            initialize_repository(sdk, SDK_GUIDANCE_FILES)
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
            model = FakeModel()

            with patch("otc_agent.generation._run", return_value=successful):
                record = generate_sdk_candidate(
                    plan=plan,
                    sdk_root=sdk,
                    docs_root=docs,
                    output_dir=root / "generated",
                    model=model,
                    evaluator_model=FakeEvaluator(),
                    evaluator_route=EVALUATOR_ROUTE,
                )

            candidate = (root / "generated/sdk.patch").read_text(encoding="utf-8")
            evidence = json.loads((root / "generated/sdk-evidence.json").read_text(encoding="utf-8"))
            self.assertIn("openstack/demo/v1/widgets/requests.go", candidate)
            self.assertEqual(record.changed_paths, ("openstack/demo/v1/widgets/requests.go",))
            self.assertEqual(evidence["citations"][0]["path"], "api-ref/source/index.rst")
            self.assertEqual(evidence["model"], "fake-model")
            self.assertEqual(evidence["schema_version"], 5)
            self.assertEqual(evidence["skill"]["id"], "generate-sdk")
            self.assertEqual(evidence["skill"]["version"], 1)
            self.assertEqual(
                {item["id"] for item in evidence["policies"]},
                {"sdk-coding", "testing", "security"},
            )
            self.assertEqual(
                [item["stage"] for item in evidence["workflow_artifacts"]],
                ["explore", "specify", "plan", "implement", "verify", "review", "publish"],
            )
            self.assertEqual(
                evidence["workflow_artifacts"][-1]["previous_sha256"],
                evidence["workflow_artifacts"][-2]["artifact_sha256"],
            )
            self.assertEqual(
                {item["source_kind"] for item in evidence["repository_guidance"]},
                {
                    "faq",
                    "styleguide",
                    "contribution",
                    "reference_implementation",
                    "reference_test",
                },
            )
            self.assertTrue(
                all(item["revision"] == evidence["repository_revision"] for item in evidence["repository_guidance"])
            )
            self.assertIn("PINNED STYLEGUIDE STYLEGUIDE.md", model.user)
            references = [
                item
                for item in evidence["repository_guidance"]
                if item["source_kind"].startswith("reference_")
            ]
            self.assertIn("openstack/apigw/v2/widgets/Create.go", {item["path"] for item in references})
            self.assertIn("openstack/apigw/v2/widgets/Create_test.go", {item["path"] for item in references})
            self.assertTrue(all(item["validation_output_sha256"] for item in references))
            self.assertLessEqual(len(references), 12)
            self.assertEqual(evidence["quality_gate"]["status"], "passed")
            self.assertGreaterEqual(evidence["quality_gate"]["score"], 0.85)

    def test_refactoring_generation_records_refactor_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = root / "sdk"
            docs = root / "docs"
            sdk.mkdir()
            docs.mkdir()
            initialize_repository(sdk, SDK_GUIDANCE_FILES)
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
