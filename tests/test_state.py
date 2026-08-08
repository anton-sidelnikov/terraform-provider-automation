from __future__ import annotations

import hashlib
import unittest

from unittest.mock import patch

from otc_agent.state import (
    connect_state_store,
    migrate_state_connections,
    MySQLStateStore,
    PostgresStateStore,
    RunRecord,
    StateConflictError,
)


class FakeTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] | None = None,
    ) -> None:
        self.executions.append((statement, parameters))

    def close(self) -> None:
        return None


class Result:
    def __init__(self, row: tuple[object, ...] | None):
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class TransitionConnection(FakeConnection):
    def __init__(self, rows: list[tuple[object, ...] | None]) -> None:
        super().__init__()
        self.rows = rows

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] | None = None,
    ) -> Result:
        self.executions.append((statement, parameters))
        return Result(self.rows.pop(0) if self.rows else None)


class FakeCursor:
    def __init__(
        self,
        executions: list[tuple[str, tuple[object, ...] | None]],
        rows: dict[str, list[tuple[object, ...]]] | None = None,
    ) -> None:
        self.executions = executions
        self.rows = rows or {}
        self.current_rows: list[tuple[object, ...]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] | None = None,
    ) -> None:
        self.executions.append((statement, parameters))
        self.current_rows = next(
            (rows for table, rows in self.rows.items() if f"FROM {table}" in statement),
            [],
        )

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.current_rows


class FakeMySQLConnection(FakeConnection):
    def __init__(self, rows: dict[str, list[tuple[object, ...]]] | None = None) -> None:
        super().__init__()
        self.rows = rows or {}

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.executions, self.rows)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class StateStoreTests(unittest.TestCase):
    def test_schema_covers_all_durable_execution_records(self) -> None:
        connection = FakeConnection()
        store = PostgresStateStore(connection)

        store.initialize_schema()

        statement = connection.executions[0][0]
        for table in (
            "agent_runs",
            "agent_stage_records",
            "agent_idempotency_keys",
            "agent_webhook_events",
            "agent_approvals",
            "agent_pull_requests",
            "agent_comments",
            "agent_repair_attempts",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", statement)

    def test_persists_run_and_related_records_transactionally(self) -> None:
        connection = FakeConnection()
        store = PostgresStateStore(connection)
        store.create_run(
            RunRecord(
                run_id="run-123",
                repository="example/repo",
                status="running",
                source_sha="a" * 40,
            )
        )
        store.record_stage(
            run_id="run-123",
            stage="verify",
            attempt=1,
            status="passed",
            artifact_sha256="b" * 64,
            previous_artifact_sha256="c" * 64,
            source_sha="a" * 40,
            branch_sha="d" * 40,
            payload={"passed": True},
        )
        store.record_approval(
            run_id="run-123",
            approval_kind="issue",
            external_id="42",
            approved_by="maintainer",
            metadata={"label": "agent-approved"},
        )
        store.record_pull_request(
            run_id="run-123",
            repository="example/repo",
            pull_request_number=7,
            branch_name="agent/change",
            branch_sha="d" * 40,
            state="OPEN",
            metadata={},
        )
        store.record_comment(
            run_id="run-123",
            repository="example/repo",
            pull_request_number=7,
            comment_id=99,
            comment_kind="review",
            processed=True,
            metadata={},
        )
        store.record_repair_attempt(
            run_id="run-123",
            attempt=1,
            status="approved",
            input_patch_sha256="e" * 64,
            output_patch_sha256="f" * 64,
            branch_sha="d" * 40,
            commit_sha="1" * 40,
            metadata={},
        )

        self.assertEqual(len(connection.executions), 6)
        self.assertTrue(all("ON CONFLICT" in statement for statement, _params in connection.executions))

    def test_mysql_uses_equivalent_schema_and_upserts(self) -> None:
        connection = FakeMySQLConnection()
        store = MySQLStateStore(connection)

        store.initialize_schema()
        store.create_run(
            RunRecord("run-123", "example/repo", "running", "a" * 40)
        )

        statements = "\n".join(statement for statement, _params in connection.executions)
        self.assertIn("CREATE TABLE IF NOT EXISTS agent_runs", statements)
        self.assertIn("ON DUPLICATE KEY UPDATE", statements)

    def test_factory_prefers_postgres_then_falls_back_to_local_mysql(self) -> None:
        postgres = PostgresStateStore(FakeConnection())
        mysql = MySQLStateStore(FakeMySQLConnection())
        with patch.object(PostgresStateStore, "connect", return_value=postgres) as pg_connect:
            self.assertIs(connect_state_store("postgresql://db/agent"), postgres)
            pg_connect.assert_called_once()
        with patch.object(MySQLStateStore, "connect", return_value=mysql) as mysql_connect:
            self.assertIs(connect_state_store(None, None), mysql)
            mysql_connect.assert_called_once_with(None)

    def test_migrates_mysql_rows_to_postgres_with_upserts(self) -> None:
        mysql = FakeMySQLConnection(
            {
                "agent_runs": [
                    (
                        "run-123",
                        "example/repo",
                        "running",
                        "verify",
                        "a" * 40,
                        "agent/change",
                        "b" * 40,
                        42,
                        7,
                        {"source": "mysql"},
                        3,
                        "2026-08-08 10:00:00",
                        "2026-08-08 10:01:00",
                    )
                ]
            }
        )
        postgres = FakeConnection()

        counts = migrate_state_connections(mysql, postgres)

        self.assertEqual(counts["agent_runs"], 1)
        insert = next(
            (statement, parameters)
            for statement, parameters in postgres.executions
            if "INSERT INTO agent_runs" in statement
        )
        self.assertIn("ON CONFLICT (run_id) DO UPDATE", insert[0])
        self.assertEqual(insert[1][0], "run-123")
        self.assertEqual(insert[1][9], '{"source":"mysql"}')

    def test_optimistic_transition_replays_same_idempotency_key(self) -> None:
        connection = TransitionConnection(
            [
                ("transition-1",),
                (1, "reviewing", "review", "b" * 40),
                None,
            ]
        )
        store = PostgresStateStore(connection)

        first = store.transition_run(
            run_id="run-123",
            expected_version=0,
            status="reviewing",
            current_stage="review",
            branch_sha="b" * 40,
            idempotency_key="transition-1",
            operation="advance-review",
            request={"stage": "review"},
        )

        self.assertEqual(first.version, 1)
        self.assertFalse(first.replayed)
        replay_connection = TransitionConnection(
            [
                None,
                (
                    "run-123",
                    "advance-review",
                    hashlib.sha256(b'{"stage":"review"}').hexdigest(),
                    first.as_dict(),
                ),
            ]
        )
        replay = PostgresStateStore(replay_connection).transition_run(
            run_id="run-123",
            expected_version=0,
            status="reviewing",
            current_stage="review",
            branch_sha="b" * 40,
            idempotency_key="transition-1",
            operation="advance-review",
            request={"stage": "review"},
        )

        self.assertTrue(replay.replayed)
        self.assertEqual(replay.version, 1)

    def test_optimistic_transition_rejects_stale_version(self) -> None:
        connection = TransitionConnection([("transition-2",), None])

        with self.assertRaisesRegex(StateConflictError, "version changed"):
            PostgresStateStore(connection).transition_run(
                run_id="run-123",
                expected_version=0,
                status="reviewing",
                current_stage="review",
                branch_sha=None,
                idempotency_key="transition-2",
                operation="advance-review",
                request={"stage": "review"},
            )

    def test_loads_latest_verified_resume_checkpoint(self) -> None:
        connection = TransitionConnection(
            [
                ("run-123", "running", 4, "a" * 40, "agent/change", "b" * 40),
                ("verify", 1, "c" * 64, "d" * 64, "a" * 40, "b" * 40, {"passed": True}),
            ]
        )

        checkpoint = PostgresStateStore(connection).load_resume_checkpoint("run-123")

        self.assertEqual(checkpoint.checkpoint_stage, "verify")
        self.assertEqual(checkpoint.run_version, 4)
        self.assertEqual(checkpoint.payload, {"passed": True})
