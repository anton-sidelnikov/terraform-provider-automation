import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from otc_agent.resume import revalidate_resume_checkpoint, ResumeError
from otc_agent.state import ResumeCheckpoint
from otc_agent.workflow import ArtifactChain, WorkflowStage


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class ResumeTests(unittest.TestCase):
    def test_revalidates_git_revisions_and_frozen_artifact_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            root.mkdir()
            git(root, "init", "--quiet")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.com")
            (root / "file.txt").write_text("base\n", encoding="utf-8")
            git(root, "add", "file.txt")
            git(root, "commit", "-m", "base")
            source_sha = git(root, "rev-parse", "HEAD")
            git(root, "switch", "-c", "agent/change")
            (root / "file.txt").write_text("change\n", encoding="utf-8")
            git(root, "commit", "-am", "change")
            branch_sha = git(root, "rev-parse", "HEAD")
            chain = ArtifactChain()
            artifact = None
            for stage in WorkflowStage:
                current = chain.append(stage, {"stage": stage.value})
                if stage == WorkflowStage.VERIFY:
                    artifact = current
            assert artifact is not None
            artifact_path = Path(directory) / "artifact.json"
            artifact_path.write_text(json.dumps(artifact.as_dict()), encoding="utf-8")
            checkpoint = ResumeCheckpoint(
                run_id="run-123",
                run_status="running",
                run_version=4,
                source_sha=source_sha,
                branch_name="agent/change",
                branch_sha=branch_sha,
                checkpoint_stage="verify",
                checkpoint_attempt=1,
                artifact_sha256=artifact.artifact_sha256,
                previous_artifact_sha256=artifact.previous_sha256,
                checkpoint_source_sha=source_sha,
                checkpoint_branch_sha=branch_sha,
                payload={"passed": True},
            )

            result = revalidate_resume_checkpoint(
                checkpoint=checkpoint,
                repository_root=root,
                artifact_path=artifact_path,
            )

            self.assertEqual(result.branch_sha, branch_sha)
            (root / "file.txt").write_text("rewritten\n", encoding="utf-8")
            git(root, "commit", "-am", "rewrite")
            with self.assertRaisesRegex(ResumeError, "no longer matches"):
                revalidate_resume_checkpoint(
                    checkpoint=checkpoint,
                    repository_root=root,
                    artifact_path=artifact_path,
                )


if __name__ == "__main__":
    unittest.main()
