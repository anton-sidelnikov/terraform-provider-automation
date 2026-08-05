import unittest
from pathlib import Path

from otc_agent.catalog import Catalog, default_catalog_path
from otc_agent.domain import ChangeKind, ChangeRequest, RunStatus
from otc_agent.evals import run_evaluation
from otc_agent.orchestrator import Planner


class OrchestratorAndEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = Catalog.load(default_catalog_path())

    def test_sdk_gate_precedes_provider(self) -> None:
        plan = Planner(self.catalog).plan(ChangeRequest("apigw", ChangeKind.FEATURE, "Add a documented resource"))
        self.assertEqual(plan.status, RunStatus.PLANNED)
        self.assertLess(plan.stages.index("sdk_approval"), plan.stages.index("provider_generate"))
        self.assertIn("api-ref", plan.assumptions[0])

    def test_unmapped_repository_starts_with_full_sdk_bootstrap(self) -> None:
        plan = Planner(self.catalog).plan(
            ChangeRequest(None, ChangeKind.NEW_SERVICE, "Create the new service", docs_repository="modelarts")
        )
        self.assertTrue(plan.mapping.bootstrap)
        self.assertIn("service_discovery", plan.stages)
        self.assertLess(plan.stages.index("sdk_approval"), plan.stages.index("provider_generate"))
        self.assertIn("<reviewed-new-sdk-abbreviation>", plan.required_outputs[0])

    def test_offline_evaluation_passes(self) -> None:
        report = run_evaluation(Path("evals/offline.jsonl"), self.catalog, mode="offline")
        self.assertTrue(report.passed)
        self.assertEqual(report.score, 1.0)


if __name__ == "__main__":
    unittest.main()
