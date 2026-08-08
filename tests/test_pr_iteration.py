import io
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from otc_agent.budget import Budget
from otc_agent.cli import main
from otc_agent.model import ModelResult
from otc_agent.pr_iteration import (
    append_repair_commit,
    authorize_iteration,
    classify_feedback,
    FeedbackComment,
    FeedbackClassification,
    FeedbackClassificationResult,
    fetch_incremental_feedback,
    find_iteration_command,
    generate_reviewed_repair,
    IncrementalFeedback,
    load_iteration_artifacts,
    PRIterationError,
    RepairCommit,
    reply_to_addressed_feedback,
    validate_iteration_write_command,
)
from otc_agent.routing import ModelRoute, ModelTier
from otc_agent.workflow import ArtifactChain, STAGE_ORDER


CURRENT_PATCH = (
    "diff --git a/openstack/apigw/v2/widgets/Get.go b/openstack/apigw/v2/widgets/Get.go\n"
    "--- a/openstack/apigw/v2/widgets/Get.go\n"
    "+++ b/openstack/apigw/v2/widgets/Get.go\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+current\n"
)


def managed_pull_request_body(
    repository: str = "example/repo",
    artifact_sha256: str = "a" * 64,
    final_workflow_artifact_sha256: str = "b" * 64,
) -> str:
    metadata = {
        "automation": {"tool": "otc-agent"},
        "evidence": {
            "artifact_sha256": artifact_sha256,
            "final_workflow_artifact_sha256": final_workflow_artifact_sha256,
        },
        "publication": {
            "repository": repository,
            "push_mode": "fast-forward-only",
        },
    }
    return (
        "## Summary\n\n"
        "<!-- otc-agent:metadata:start\n"
        f"{json.dumps(metadata, sort_keys=True, separators=(',', ':'))}\n"
        "otc-agent:metadata:end -->\n"
    )


def write_run_artifact(path: Path, patch: str = CURRENT_PATCH) -> tuple[str, str]:
    patch_sha256 = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    chain = ArtifactChain()
    for stage in STAGE_ORDER:
        payload: dict[str, object] = {"stage": stage.value}
        if stage.value == "verify":
            payload["patch_sha256"] = patch_sha256
        chain.append(stage, payload)
    artifacts = [artifact.as_dict() for artifact in chain.finish()]
    path.write_text(
        json.dumps(
            {
                "workflow_artifacts": artifacts,
                "patch_sha256": patch_sha256,
                "model": "author-model",
                "model_provider": "copilot",
                "model_endpoint": "stdio:author",
                "skill": {"id": "generate-sdk", "version": 1, "model_tier": "strong"},
            }
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest(), artifacts[-1]["artifact_sha256"]


class FakeClassificationModel:
    def __init__(self, value: dict[str, object]):
        self.value = value

    def generate_json(self, **_kwargs: object) -> ModelResult:
        return ModelResult(self.value, "classifier", 100, 20, 0.0)


def git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class PRIterationTests(unittest.TestCase):
    def test_finds_latest_exact_iteration_command(self) -> None:
        command = find_iteration_command(
            [
                {
                    "id": 10,
                    "body": "Please run /agent iterate",
                    "author": "reviewer",
                    "author_association": "MEMBER",
                    "url": "https://github.com/example/repo/pull/1#issuecomment-10",
                },
                {
                    "id": 12,
                    "body": "\n/agent iterate\n",
                    "author": "maintainer",
                    "author_association": "OWNER",
                    "url": "https://github.com/example/repo/pull/1#issuecomment-12",
                },
            ]
        )

        self.assertEqual(command.comment_id, 12)
        self.assertEqual(command.body, "/agent iterate")

    def test_rejects_embedded_or_missing_command(self) -> None:
        with self.assertRaisesRegex(PRIterationError, "no exact"):
            find_iteration_command(
                [
                    {
                        "id": 10,
                        "body": "Quoted command: `/agent iterate`",
                        "author": "reviewer",
                        "author_association": "MEMBER",
                        "url": "https://github.com/example/repo/pull/1#issuecomment-10",
                    }
                ]
            )

    def test_iterate_cli_records_requested_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "run.json"
            artifact_sha256, final_sha256 = write_run_artifact(artifact_path)
            input_path = Path(directory) / "iterate.json"
            input_path.write_text(
                json.dumps(
                    {
                        "run_id": "run-123",
                        "artifact": str(artifact_path),
                        "state_path": str(Path(directory) / "iteration-state.json"),
                        "repository": "example/repo",
                        "pull_request": 42,
                        "head_branch": "agent/refactor-widgets",
                        "pull_request_body": managed_pull_request_body(
                            artifact_sha256=artifact_sha256,
                            final_workflow_artifact_sha256=final_sha256,
                        ),
                        "stage": "sdk",
                        "service": "apigw",
                        "current_patch": CURRENT_PATCH,
                        "comments": [
                            {
                                "id": 99,
                                "body": "/agent iterate",
                                "author": "maintainer",
                                "author_association": "MEMBER",
                                "url": "https://github.com/example/repo/pull/42#issuecomment-99",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            with patch(
                "otc_agent.cli.fetch_incremental_feedback",
                return_value=IncrementalFeedback((), (), 10, 20),
            ) as fetch:
                with redirect_stdout(output):
                    result = main(["iterate-pr", "--input", str(input_path)])
                retry_output = io.StringIO()
                with redirect_stdout(retry_output):
                    retry_result = main(["iterate-pr", "--input", str(input_path)])
                self.assertEqual(fetch.call_count, 1)

            value = json.loads(output.getvalue())
            retry_value = json.loads(retry_output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(retry_result, 0)
        self.assertEqual(value["status"], "feedback_classified")
        self.assertEqual(retry_value["status"], "already_processed")
        self.assertEqual(value["command"]["comment_id"], 99)
        self.assertEqual(value["artifacts"]["stages"], [stage.value for stage in STAGE_ORDER])
        self.assertEqual(value["feedback"]["issue_comment_cursor"], 10)
        self.assertEqual(value["state"]["issue_comment_cursor"], 10)

    def test_rejects_untrusted_commenter_or_unmanaged_pull_request(self) -> None:
        command = find_iteration_command(
            [
                {
                    "id": 7,
                    "body": "/agent iterate",
                    "author": "external-user",
                    "author_association": "CONTRIBUTOR",
                    "url": "https://github.com/example/repo/pull/1#issuecomment-7",
                }
            ]
        )

        with self.assertRaisesRegex(PRIterationError, "not a repository maintainer"):
            authorize_iteration(
                command=command,
                repository="example/repo",
                pull_request=1,
                head_branch="agent/change",
                pull_request_body=managed_pull_request_body(),
            )

        trusted = command.__class__(
            command.comment_id,
            command.body,
            command.author,
            "MEMBER",
            command.url,
        )
        with self.assertRaisesRegex(PRIterationError, "not an agent-managed branch"):
            authorize_iteration(
                command=trusted,
                repository="example/repo",
                pull_request=1,
                head_branch="feature/change",
                pull_request_body=managed_pull_request_body(),
            )

    def test_rejects_artifact_not_bound_to_pull_request_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "run.json"
            _artifact_sha256, final_sha256 = write_run_artifact(artifact_path)
            metadata = json.loads(
                managed_pull_request_body(
                    artifact_sha256="0" * 64,
                    final_workflow_artifact_sha256=final_sha256,
                ).splitlines()[3]
            )

            with self.assertRaisesRegex(PRIterationError, "hash does not match"):
                load_iteration_artifacts(artifact_path, metadata)

    def test_fetches_new_issue_comments_and_unresolved_review_threads(self) -> None:
        def runner(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if "graphql" in arguments:
                value = {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "isResolved": False,
                                            "comments": {
                                                "nodes": [
                                                    {
                                                        "databaseId": 31,
                                                        "body": "Please fix this.",
                                                        "url": "https://github.com/example/repo/pull/42#discussion_r31",
                                                        "authorAssociation": "MEMBER",
                                                        "author": {"login": "reviewer"},
                                                    }
                                                ],
                                                "pageInfo": {"hasNextPage": False},
                                            },
                                        },
                                        {
                                            "isResolved": True,
                                            "comments": {
                                                "nodes": [],
                                                "pageInfo": {"hasNextPage": False},
                                            },
                                        },
                                    ],
                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                }
                            }
                        }
                    }
                }
            else:
                value = [
                    {
                        "id": 11,
                        "body": "Old",
                        "html_url": "https://github.com/example/repo/pull/42#issuecomment-11",
                        "author_association": "MEMBER",
                        "user": {"login": "reviewer"},
                    },
                    {
                        "id": 21,
                        "body": "New feedback",
                        "html_url": "https://github.com/example/repo/pull/42#issuecomment-21",
                        "author_association": "MEMBER",
                        "user": {"login": "reviewer"},
                    },
                ]
            return subprocess.CompletedProcess(arguments, 0, json.dumps(value), "")

        feedback = fetch_incremental_feedback(
            repository="example/repo",
            pull_request=42,
            after_issue_comment_id=15,
            after_review_comment_id=30,
            runner=runner,
        )

        self.assertEqual([comment.comment_id for comment in feedback.issue_comments], [21])
        self.assertEqual([comment.comment_id for comment in feedback.review_comments], [31])
        self.assertEqual(feedback.issue_comment_cursor, 21)
        self.assertEqual(feedback.review_comment_cursor, 31)

    def test_classifies_every_feedback_comment_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "run.json"
            artifact_sha256, final_sha256 = write_run_artifact(artifact_path)
            metadata = json.loads(
                managed_pull_request_body(
                    artifact_sha256=artifact_sha256,
                    final_workflow_artifact_sha256=final_sha256,
                ).splitlines()[3]
            )
            artifacts = load_iteration_artifacts(artifact_path, metadata)
            feedback = IncrementalFeedback(
                (
                    FeedbackComment(
                        21,
                        "issue",
                        "Can you explain this choice?",
                        "reviewer",
                        "MEMBER",
                        "https://github.com/example/repo/pull/42#issuecomment-21",
                    ),
                ),
                (
                    FeedbackComment(
                        31,
                        "review",
                        "Rename the in-scope field.",
                        "reviewer",
                        "MEMBER",
                        "https://github.com/example/repo/pull/42#discussion_r31",
                    ),
                ),
                21,
                31,
            )
            model = FakeClassificationModel(
                {
                    "classifications": [
                        {
                            "comment_id": 21,
                            "kind": "issue",
                            "category": "question",
                            "reason": "Requests an explanation.",
                        },
                        {
                            "comment_id": 31,
                            "kind": "review",
                            "category": "actionable",
                            "reason": "Requests an in-scope code change.",
                        },
                    ]
                }
            )

            result = classify_feedback(
                feedback=feedback,
                artifacts=artifacts,
                model=model,
                budget=Budget(1, 10_000, 1_000, 1.0, 30),
            )

            self.assertEqual(
                [classification.category for classification in result.classifications],
                ["question", "actionable"],
            )
            with self.assertRaisesRegex(PRIterationError, "exactly once"):
                classify_feedback(
                    feedback=feedback,
                    artifacts=artifacts,
                    model=FakeClassificationModel(
                        {"classifications": [model.value["classifications"][0]]}
                    ),
                    budget=Budget(1, 10_000, 1_000, 1.0, 30),
                )

    def test_generates_and_independently_reviews_actionable_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "run.json"
            artifact_sha256, final_sha256 = write_run_artifact(artifact_path)
            metadata = json.loads(
                managed_pull_request_body(
                    artifact_sha256=artifact_sha256,
                    final_workflow_artifact_sha256=final_sha256,
                ).splitlines()[3]
            )
            artifacts = load_iteration_artifacts(artifact_path, metadata)
            comment = FeedbackComment(
                31,
                "review",
                "Rename this field.",
                "reviewer",
                "MEMBER",
                "https://github.com/example/repo/pull/42#discussion_r31",
            )
            feedback = IncrementalFeedback((), (comment,), 0, 31)
            classifications = FeedbackClassificationResult(
                (
                    FeedbackClassification(
                        31,
                        "review",
                        "actionable",
                        "Concrete in-scope rename.",
                    ),
                ),
                "classifier",
            )
            replacement = CURRENT_PATCH.replace("+current", "+repaired")

            outcome = generate_reviewed_repair(
                feedback=feedback,
                classifications=classifications,
                artifacts=artifacts,
                current_patch=CURRENT_PATCH,
                diagnostics=[],
                repair_model=FakeClassificationModel(
                    {
                        "patch": replacement,
                        "summary": "Applied maintainer rename.",
                        "addressed_findings": ["comment-31"],
                    }
                ),
                reviewer_model=FakeClassificationModel(
                    {"decision": "approve", "findings": []}
                ),
                reviewer_route=ModelRoute(
                    "reviewer",
                    ModelTier.STRONG,
                    "copilot",
                    "reviewer-model",
                    "stdio:reviewer",
                ),
                repair_budget=Budget(1, 10_000, 1_000, 1.0, 30),
                reviewer_budget=Budget(1, 10_000, 1_000, 1.0, 30),
                validate_repair=lambda patch, _iteration: [
                    {
                        "tool": "patch.validate",
                        "status": "passed",
                        "sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                    }
                ],
            )

            self.assertIsNotNone(outcome)
            assert outcome is not None
            self.assertEqual(outcome.status, "approved")
            self.assertEqual(outcome.patch, replacement)
            calls: list[list[str]] = []

            def reply_runner(
                arguments: list[str],
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                calls.append(arguments)
                return subprocess.CompletedProcess(
                    arguments,
                    0,
                    json.dumps(
                        {
                            "id": 99,
                            "html_url": "https://github.com/example/repo/pull/42#discussion_r99",
                        }
                    ),
                    "",
                )

            replies = reply_to_addressed_feedback(
                repository="example/repo",
                pull_request=42,
                feedback=feedback,
                classifications=classifications,
                repair=outcome,
                commit=RepairCommit(
                    "agent/fix-widget",
                    "a" * 40,
                    "b" * 40,
                    "fast-forward-only",
                ),
                runner=reply_runner,
            )

            self.assertEqual(replies[0].comment_id, 31)
            self.assertTrue(
                any("pulls/42/comments/31/replies" in argument for argument in calls[0])
            )
            body_argument = next(item for item in calls[0] if item.startswith("body="))
            self.assertIn("`" + "b" * 40 + "`", body_argument)
            self.assertIn(outcome.patch_sha256, body_argument)

    def test_appends_and_pushes_repair_commit_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "work"
            remote = Path(directory) / "remote.git"
            root.mkdir()
            git(root, "init", "--quiet")
            git(root, "config", "user.name", "Test")
            git(root, "config", "user.email", "test@example.com")
            source = root / "openstack" / "apigw" / "v2" / "widgets" / "Get.go"
            source.parent.mkdir(parents=True)
            source.write_text("old\n", encoding="utf-8")
            git(root, "add", "--all")
            git(root, "commit", "-m", "base")
            base_sha = git(root, "rev-parse", "HEAD")
            git(root, "switch", "--quiet", "-c", "agent/fix-widget")
            source.write_text("current\n", encoding="utf-8")
            git(root, "commit", "-am", "initial change")
            previous_head_sha = git(root, "rev-parse", "HEAD")
            current_patch = git(root, "diff", base_sha, previous_head_sha) + "\n"
            source.write_text("repaired\n", encoding="utf-8")
            replacement_patch = git(root, "diff", base_sha) + "\n"
            source.write_text("current\n", encoding="utf-8")
            git(remote.parent, "init", "--bare", "--quiet", str(remote))
            git(root, "remote", "add", "origin", str(remote))
            git(root, "push", "-u", "origin", "agent/fix-widget")

            result = append_repair_commit(
                worktree=root,
                branch="agent/fix-widget",
                base_sha=base_sha,
                previous_head_sha=previous_head_sha,
                current_patch=current_patch,
                replacement_patch=replacement_patch,
                commit_message="Address review feedback",
            )

            self.assertEqual(result.previous_head_sha, previous_head_sha)
            self.assertEqual(result.push_mode, "fast-forward-only")
            self.assertEqual(source.read_text(encoding="utf-8"), "repaired\n")
            self.assertEqual(
                git(remote.parent, "--git-dir", str(remote), "rev-parse", "refs/heads/agent/fix-widget"),
                result.commit_sha,
            )

    def test_remote_write_policy_rejects_pr_lifecycle_and_force_pushes(self) -> None:
        validate_iteration_write_command(
            [
                "git",
                "-C",
                "/tmp/work",
                "push",
                "origin",
                "HEAD:refs/heads/agent/fix-widget",
            ]
        )
        validate_iteration_write_command(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "repos/example/repo/pulls/42/comments/31/replies",
                "-f",
                "body=done",
            ]
        )

        with self.assertRaisesRegex(PRIterationError, "normal push"):
            validate_iteration_write_command(
                [
                    "git",
                    "-C",
                    "/tmp/work",
                    "push",
                    "--force",
                    "origin",
                    "HEAD:refs/heads/agent/fix-widget",
                ]
            )
        with self.assertRaisesRegex(PRIterationError, "lifecycle"):
            validate_iteration_write_command(["gh", "pr", "close", "42"])
        with self.assertRaisesRegex(PRIterationError, "GitHub write"):
            validate_iteration_write_command(
                [
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "repos/example/repo/pulls/42",
                    "-f",
                    "state=closed",
                ]
            )


if __name__ == "__main__":
    unittest.main()
