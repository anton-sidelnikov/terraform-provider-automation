import unittest

from otc_agent.workflow import (
    STAGE_ORDER,
    ArtifactChain,
    FrozenArtifact,
    WorkflowError,
    WorkflowStage,
    load_frozen_artifacts,
    verify_artifact_chain,
)


class WorkflowTests(unittest.TestCase):
    def test_artifacts_are_ordered_and_hash_linked(self) -> None:
        chain = ArtifactChain()
        for stage in STAGE_ORDER:
            chain.append(stage, {"stage": stage.value})

        artifacts = chain.finish()

        self.assertEqual([artifact.stage for artifact in artifacts], list(STAGE_ORDER))
        self.assertIsNone(artifacts[0].previous_sha256)
        self.assertEqual(artifacts[-1].previous_sha256, artifacts[-2].artifact_sha256)

    def test_rejects_out_of_order_stage(self) -> None:
        chain = ArtifactChain()

        with self.assertRaises(WorkflowError):
            chain.append(WorkflowStage.PLAN, {"invalid": True})

    def test_detects_tampered_payload(self) -> None:
        chain = ArtifactChain()
        for stage in STAGE_ORDER:
            chain.append(stage, {"stage": stage.value})
        artifacts = list(chain.finish())
        original = artifacts[3]
        artifacts[3] = FrozenArtifact(
            schema_version=original.schema_version,
            workflow_version=original.workflow_version,
            stage=original.stage,
            previous_sha256=original.previous_sha256,
            payload_json='{"stage":"tampered"}',
            payload_sha256=original.payload_sha256,
            artifact_sha256=original.artifact_sha256,
        )

        with self.assertRaises(WorkflowError):
            verify_artifact_chain(tuple(artifacts))

    def test_loads_serialized_artifact_chain(self) -> None:
        chain = ArtifactChain()
        for stage in STAGE_ORDER:
            chain.append(stage, {"stage": stage.value})
        serialized = [artifact.as_dict() for artifact in chain.finish()]

        loaded = load_frozen_artifacts(serialized)

        self.assertEqual(loaded[-1].artifact_sha256, chain.artifacts[-1].artifact_sha256)


if __name__ == "__main__":
    unittest.main()
