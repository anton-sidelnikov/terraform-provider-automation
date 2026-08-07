import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from otc_agent.cli import main
from otc_agent.publishing import (
    build_sdk_pull_request_body,
    IssueApproval,
    PublicationError,
    verify_append_only_history,
    verify_publish_preflight,
)


def issue_result(*, state: str = "OPEN", labels: tuple[str, ...] = ("agent-approved",)) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(
            {
                "number": 42,
                "state": state,
                "title": "Refactor the widgets API",
                "url": "https://github.com/example/sdk/issues/42",
                "labels": [{"name": label, "color": "ffffff"} for label in labels],
            }
        ),
        stderr="",
    )


def git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def commit_file(directory: Path, content: str, message: str) -> str:
    (directory / "change.txt").write_text(content, encoding="utf-8")
    git(directory, "add", "change.txt")
    git(directory, "commit", "-m", message)
    return git(directory, "rev-parse", "HEAD")


def publication_artifact(repository_revision: str) -> dict[str, object]:
    return {
        "schema_version": 3,
        "workflow_version": 1,
        "skill": {"id": "generate-sdk", "version": 1},
        "policies": [
            {"id": "sdk-coding", "version": 1},
            {"id": "security", "version": 1},
        ],
        "repository_revision": repository_revision,
        "documentation_revision": "d" * 40,
        "patch_sha256": "e" * 64,
        "workflow_artifacts": [{"artifact_sha256": "f" * 64}],
    }


class PublishingTests(unittest.TestCase):
    def test_sdk_pull_request_body_adds_approved_issue_exactly_once(self) -> None:
        issue = IssueApproval(
            repository="example/sdk",
            number=42,
            url="https://github.com/example/sdk/issues/42",
            title="Refactor the widgets API",
            state="OPEN",
            approval_label="agent-approved",
            labels=("agent-approved",),
        )

        body = build_sdk_pull_request_body("## Summary\n\nRefactor widgets.", issue, "api-gateway")
        self.assertIn("For #42\n", body)
        self.assertIn("https://docs.otc.t-systems.com/api-gateway/", body)
        self.assertIn("https://docs.otc.t-systems.com/api-gateway/api-ref/index.html", body)
        self.assertEqual(build_sdk_pull_request_body(body, issue, "api-gateway"), body)

    def test_sdk_pull_request_body_rejects_mismatched_or_duplicate_issue(self) -> None:
        issue = IssueApproval(
            repository="example/sdk",
            number=42,
            url="https://github.com/example/sdk/issues/42",
            title="Refactor the widgets API",
            state="OPEN",
            approval_label="agent-approved",
            labels=("agent-approved",),
        )

        with self.assertRaisesRegex(PublicationError, "other than the approved issue"):
            build_sdk_pull_request_body("For #41", issue, "api-gateway")
        with self.assertRaisesRegex(PublicationError, "exactly once"):
            build_sdk_pull_request_body("For #42\n\nFor #42", issue, "api-gateway")
        with self.assertRaisesRegex(PublicationError, "conflicting documentation"):
            build_sdk_pull_request_body(
                "<!-- otc-agent:documentation:start -->\nUntrusted URL\n<!-- otc-agent:documentation:end -->",
                issue,
                "api-gateway",
            )

    def test_pull_request_body_renders_upstream_dependency_convention(self) -> None:
        issue = IssueApproval(
            repository="example/provider",
            number=42,
            url="https://github.com/example/provider/issues/42",
            title="Add widgets resource",
            state="OPEN",
            approval_label="agent-approved",
            labels=("agent-approved",),
        )
        dependency = "https://github.com/opentelekomcloud/gophertelekomcloud/pull/1234"

        body = build_sdk_pull_request_body(
            "## Summary\n\nAdd widgets.",
            issue,
            "api-gateway",
            (dependency,),
        )

        self.assertIn(f"Depends-On: {dependency}\n", body)
        self.assertEqual(
            build_sdk_pull_request_body(body, issue, "api-gateway", (dependency,)),
            body,
        )
        with self.assertRaisesRegex(PublicationError, "exact GitHub pull-request URL"):
            build_sdk_pull_request_body("", issue, "api-gateway", ("https://example.com/pull/1",))
        with self.assertRaisesRegex(PublicationError, "conflicting Depends-On"):
            build_sdk_pull_request_body(body, issue, "api-gateway", ())

    def test_preflight_requires_open_approved_issue_and_hashes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "evidence.json"
            artifact.write_text('{"status":"approved"}\n', encoding="utf-8")

            preflight = verify_publish_preflight(
                artifact=artifact,
                repository="example/sdk",
                base_sha="a" * 40,
                issue=42,
                routes=("CreateWidget",),
                runner=lambda *_args, **_kwargs: issue_result(),
            )

            self.assertEqual(preflight.issue.approval_label, "agent-approved")
            self.assertEqual(len(preflight.artifact_sha256), 64)

    def test_preflight_rejects_closed_or_unapproved_issue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "evidence.json"
            artifact.write_text("{}", encoding="utf-8")
            arguments = {
                "artifact": artifact,
                "repository": "example/sdk",
                "base_sha": "a" * 40,
                "issue": 42,
                "routes": ("CreateWidget",),
            }

            with self.assertRaisesRegex(PublicationError, "open GitHub issue"):
                verify_publish_preflight(
                    **arguments,
                    runner=lambda *_args, **_kwargs: issue_result(state="CLOSED"),
                )
            with self.assertRaisesRegex(PublicationError, "approval label"):
                verify_publish_preflight(
                    **arguments,
                    runner=lambda *_args, **_kwargs: issue_result(labels=("triage",)),
                )

    def test_publish_cli_executes_read_only_issue_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, "init", "--quiet")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.com")
            base_sha = commit_file(root, "base\n", "base")
            candidate_head_sha = commit_file(root, "candidate\n", "candidate")
            artifact = root / "evidence.json"
            artifact.write_text(
                json.dumps(publication_artifact(base_sha)),
                encoding="utf-8",
            )
            input_path = root / "publish.json"
            input_path.write_text(
                json.dumps(
                    {
                        "artifact": str(artifact),
                        "repository": "example/sdk",
                        "worktree": str(root),
                        "base_sha": base_sha,
                        "candidate_head_sha": candidate_head_sha,
                        "issue": 42,
                        "routes": ["CreateWidget"],
                        "documentation_repository": "api-gateway",
                        "pull_request_body": "## Summary\n\nRefactor widgets.",
                        "depends_on": [
                            "https://github.com/opentelekomcloud/gophertelekomcloud/pull/1234"
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            approval = IssueApproval(
                repository="example/sdk",
                number=42,
                url="https://github.com/example/sdk/issues/42",
                title="Refactor the widgets API",
                state="OPEN",
                approval_label="agent-approved",
                labels=("agent-approved",),
            )

            with patch("otc_agent.publishing.verify_approved_issue", return_value=approval):
                with redirect_stdout(output):
                    result = main(["publish", "--input", str(input_path)])

            value = json.loads(output.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(value["status"], "approved_for_publish")
            self.assertEqual(value["preflight"]["issue"]["number"], 42)
            self.assertEqual(value["preflight"]["routes"], ["CreateWidget"])
            self.assertEqual(value["history"]["push_mode"], "fast-forward-only")
            self.assertEqual(value["metadata"]["evidence"]["patch_sha256"], "e" * 64)
            self.assertIn("<!-- otc-agent:metadata:start", value["pull_request_body"])
            self.assertEqual(value["pull_request_body"].count("For #42"), 1)
            self.assertIn("https://docs.otc.t-systems.com/api-gateway/api-ref/index.html", value["pull_request_body"])
            self.assertIn("Depends-On: https://github.com/opentelekomcloud/gophertelekomcloud/pull/1234", value["pull_request_body"])

    def test_preflight_requires_one_route_or_approved_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "evidence.json"
            artifact.write_text("{}", encoding="utf-8")
            arguments = {
                "artifact": artifact,
                "repository": "example/sdk",
                "base_sha": "a" * 40,
                "issue": 42,
            }

            with self.assertRaisesRegex(PublicationError, "exactly one API route"):
                verify_publish_preflight(
                    **arguments,
                    routes=(),
                    runner=lambda *_args, **_kwargs: issue_result(),
                )
            with self.assertRaisesRegex(PublicationError, "agent-multi-route-approved"):
                verify_publish_preflight(
                    **arguments,
                    routes=("CreateWidget", "DeleteWidget"),
                    runner=lambda *_args, **_kwargs: issue_result(),
                )

            preflight = verify_publish_preflight(
                **arguments,
                routes=("CreateWidget", "DeleteWidget"),
                runner=lambda *_args, **_kwargs: issue_result(
                    labels=("agent-approved", "agent-multi-route-approved")
                ),
            )

            self.assertEqual(preflight.route_scope_exception_label, "agent-multi-route-approved")

    def test_history_verification_requires_append_only_commits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, "init", "--quiet")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.com")
            base = commit_file(root, "base\n", "base")
            previous = commit_file(root, "first\n", "first")
            candidate = commit_file(root, "second\n", "second")

            history = verify_append_only_history(
                worktree=root,
                base_sha=base,
                candidate_head_sha=candidate,
                previous_head_sha=previous,
            )

            self.assertEqual(history.push_mode, "fast-forward-only")
            git(root, "switch", "--quiet", "-c", "rewritten", base)
            rewritten = commit_file(root, "rewritten\n", "rewritten")
            with self.assertRaisesRegex(PublicationError, "not append-only"):
                verify_append_only_history(
                    worktree=root,
                    base_sha=base,
                    candidate_head_sha=rewritten,
                    previous_head_sha=previous,
                )


if __name__ == "__main__":
    unittest.main()
