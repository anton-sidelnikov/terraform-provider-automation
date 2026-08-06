import tempfile
import unittest
from pathlib import Path

from otc_agent.policy import PolicyError, load_policy_registry


class PolicyTests(unittest.TestCase):
    def test_repository_policies_are_valid_and_unique(self) -> None:
        contracts = load_policy_registry(Path("docs/policy"))

        self.assertEqual(
            {contract.policy_id for contract in contracts},
            {
                "change-classification",
                "provider-coding",
                "pull-requests",
                "review",
                "sdk-coding",
                "sdk-layout",
                "security",
                "testing",
            },
        )
        self.assertTrue(all(contract.version >= 1 for contract in contracts))

    def test_rejects_missing_metadata_and_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "invalid.md").write_text(
                "# Invalid\n\nPolicy ID: invalid\nStatus: Adopted\nVersion: 1\n\n## 1. Rules\n",
                encoding="utf-8",
            )

            with self.assertRaises(PolicyError):
                load_policy_registry(root)


if __name__ == "__main__":
    unittest.main()

