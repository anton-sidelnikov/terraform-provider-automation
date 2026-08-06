import io
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from otc_agent.cli import _parser, main
from otc_agent.workflow import STAGE_ORDER, ArtifactChain, WorkflowStage


class SkillCLITests(unittest.TestCase):
    def test_all_declared_skill_commands_are_exposed(self) -> None:
        parser = _parser()

        self.assertEqual(parser.parse_args(["analyze", "--service", "apigw", "--description", "Inspect"]).command, "analyze")
        for command in ("spec", "refactor-sdk", "review", "verify", "publish", "iterate-pr", "resume"):
            parsed = parser.parse_args([command, "--input", "input.json"])
            self.assertEqual(parsed.command, command)

    def test_analyze_executes_existing_read_only_skill(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(
                [
                    "analyze",
                    "--service",
                    "apigw",
                    "--description",
                    "Inspect the existing SDK layout",
                    "--sdk-root",
                    "evals/fixtures/legacy-sdk",
                ]
            )

        value = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(value["skill"]["id"], "analyze")
        self.assertEqual(value["classification"]["kind"], "refactoring")
        self.assertEqual(value["layout"]["kind"], "legacy")

    def test_future_skill_command_validates_contract_and_fails_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "resume.json"
            input_path.write_text(json.dumps({"run_id": "run-123"}), encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                result = main(["resume", "--input", str(input_path)])

        value = json.loads(output.getvalue())
        self.assertEqual(result, 4)
        self.assertEqual(value["status"], "not_implemented")
        self.assertEqual(value["skill"]["id"], "resume")
        self.assertEqual(value["skill"]["version"], 1)

    def test_review_command_emits_context_isolated_bundle(self) -> None:
        patch = "diff --git a/a.go b/a.go\n"
        patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        chain = ArtifactChain()
        for stage in STAGE_ORDER:
            payload: dict[str, object] = {"stage": stage.value}
            if stage == WorkflowStage.VERIFY:
                payload["patch_sha256"] = patch_sha256
            chain.append(stage, payload)
        evidence = {
            "patch_sha256": patch_sha256,
            "workflow_artifacts": [artifact.as_dict() for artifact in chain.finish()],
            "conversation_history": "private author context",
        }
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "review.json"
            input_path.write_text(
                json.dumps({"patch": patch, "evidence": evidence}),
                encoding="utf-8",
            )
            output = io.StringIO()

            with redirect_stdout(output):
                result = main(["review", "--input", str(input_path)])

        value = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(value["status"], "ready_for_independent_review")
        self.assertFalse(value["review_bundle"]["author_context_included"])
        self.assertNotIn("private author context", output.getvalue())


if __name__ == "__main__":
    unittest.main()
