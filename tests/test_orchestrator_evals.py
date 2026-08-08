import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(report.cases, 11)
        self.assertEqual(report.critical_failures, ())
        self.assertEqual(report.as_dict()["schema_version"], 2)

    def test_online_workflow_scores_validation_iteration_latency_and_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "online.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "id": "workflow",
                        "suite": "workflow",
                        "critical": True,
                        "input": {"service": "apigw"},
                        "expected": {"minimum_replies": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            response = online_workflow_response()
            with patch("otc_agent.evals._call_workflow_endpoint", return_value=response):
                report = run_evaluation(
                    dataset,
                    self.catalog,
                    mode="online",
                    workflow_endpoint="https://workflow.example.test",
                )

        self.assertTrue(report.passed)
        self.assertEqual(report.score, 1.0)
        self.assertEqual(report.p95_latency_ms, 1250.0)
        self.assertEqual(report.average_cost_usd, 0.25)

    def test_online_workflow_critical_failure_is_non_compensating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "online.jsonl"
            dataset.write_text(
                json.dumps(
                    {
                        "id": "workflow",
                        "suite": "workflow",
                        "critical": True,
                        "input": {"service": "apigw"},
                        "expected": {"minimum_replies": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            response = online_workflow_response()
            response["iteration"]["same_pull_request"] = False
            with patch("otc_agent.evals._call_workflow_endpoint", return_value=response):
                report = run_evaluation(
                    dataset,
                    self.catalog,
                    mode="online",
                    workflow_endpoint="https://workflow.example.test",
                )

        self.assertGreater(report.score, 0.85)
        self.assertFalse(report.passed)
        self.assertEqual(len(report.critical_failures), 1)

def online_workflow_response() -> dict[str, object]:
    return {
        "case_id": "workflow",
        "status": "passed",
        "validation": {
            "compilation": {
                "status": "passed",
                "command": "go test -run '^$' ./...",
                "sha256": "a" * 64,
            },
            "repository_tests": {
                "status": "passed",
                "native": True,
                "command": "go test ./...",
                "sha256": "b" * 64,
            },
        },
        "iteration": {
            "status": "completed",
            "command": "/agent iterate",
            "same_pull_request": True,
            "append_only": True,
            "replied_comments": 1,
        },
        "metrics": {"latency_ms": 1250, "cost_usd": 0.25},
    }


if __name__ == "__main__":
    unittest.main()
