import unittest
from pathlib import Path

from otc_agent.policy import load_policy_registry


class PolicyTests(unittest.TestCase):
    def test_repository_policy_registry_is_valid(self) -> None:
        policies = load_policy_registry(Path("docs/policy"))

        self.assertEqual(len(policies), 8)
        self.assertEqual(len({policy.policy_id for policy in policies}), 8)


if __name__ == "__main__":
    unittest.main()

