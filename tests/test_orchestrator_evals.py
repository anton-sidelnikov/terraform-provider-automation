import unittest
import tempfile
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
        plan = Planner(self.catalog).plan(ChangeRequest("apigw", ChangeKind.FEATURE, "Add a documented endpoint"))
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
        self.assertIn("openstack/modelarts/", plan.required_outputs[0])

    def test_bootstrap_service_key_rejects_path_syntax(self) -> None:
        with self.assertRaises(ValueError):
            Planner(self.catalog).plan(
                ChangeRequest(
                    "../modelarts",
                    None,
                    "Create complete SDK support",
                    docs_repository="modelarts",
                )
            )

    def test_legacy_sdk_layout_adds_refactoring_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sdk_root = Path(directory)
            requests = sdk_root / "openstack" / "apigw" / "v2" / "widgets" / "requests.go"
            requests.parent.mkdir(parents=True)
            requests.write_text("package widgets\nfunc Create() {}\n", encoding="utf-8")

            plan = Planner(self.catalog).plan(
                ChangeRequest("apigw", None, "Add a documented endpoint"),
                sdk_root=sdk_root,
            )

            self.assertEqual(plan.request.kind, ChangeKind.REFACTORING)
            self.assertIn("sdk_refactor", plan.stages)
            self.assertLess(plan.stages.index("sdk_refactor"), plan.stages.index("sdk_plan"))

    def test_offline_evaluation_passes(self) -> None:
        report = run_evaluation(Path("evals/offline.jsonl"), self.catalog, mode="offline")
        self.assertTrue(report.passed)
        self.assertEqual(report.score, 1.0)


if __name__ == "__main__":
    unittest.main()
