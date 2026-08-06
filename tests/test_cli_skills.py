import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from otc_agent.cli import _parser, main


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


if __name__ == "__main__":
    unittest.main()

