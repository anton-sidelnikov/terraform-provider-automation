import json
import tempfile
import unittest
from pathlib import Path

from otc_agent.policy import load_policy_registry
from otc_agent.skill import SkillError, load_skill_registry


class SkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.policies = load_policy_registry(Path("docs/policy"))

    def test_repository_skill_registry_is_valid(self) -> None:
        skills = load_skill_registry(Path("config/skills.json"), self.policies)

        self.assertEqual(
            {skill.skill_id for skill in skills},
            {
                "analyze",
                "spec",
                "refactor-sdk",
                "generate-sdk",
                "generate-provider",
                "review",
                "verify",
                "publish",
                "iterate-pr",
                "resume",
            },
        )
        self.assertEqual(
            {skill.skill_id: skill.version for skill in skills},
            {
                "analyze": 1,
                "spec": 1,
                "refactor-sdk": 1,
                "generate-sdk": 1,
                "generate-provider": 1,
                "review": 1,
                "verify": 1,
                "publish": 7,
                "iterate-pr": 1,
                "resume": 1,
            },
        )
        self.assertTrue(all(skill.policies for skill in skills))
        self.assertTrue(all(skill.tools for skill in skills))

    def test_rejects_unknown_policy_reference(self) -> None:
        value = json.loads(Path("config/skills.json").read_text(encoding="utf-8"))
        value["skills"][0]["policies"][0]["id"] = "not-adopted"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "skills.json"
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaises(SkillError):
                load_skill_registry(path, self.policies)

    def test_model_free_skill_cannot_request_model_calls(self) -> None:
        value = json.loads(Path("config/skills.json").read_text(encoding="utf-8"))
        publish = next(skill for skill in value["skills"] if skill["id"] == "publish")
        publish["budget"]["max_model_calls"] = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "skills.json"
            path.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaises(SkillError):
                load_skill_registry(path, self.policies)


if __name__ == "__main__":
    unittest.main()
