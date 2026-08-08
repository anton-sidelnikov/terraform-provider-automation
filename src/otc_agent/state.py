from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any
from urllib.parse import unquote, urlparse


class StateStoreError(RuntimeError):
    pass


class StateConflictError(StateStoreError):
    pass


_MIGRATION_TABLES = (
    (
        "agent_runs",
        (
            "run_id",
            "repository",
            "status",
            "current_stage",
            "source_sha",
            "branch_name",
            "branch_sha",
            "issue_number",
            "pull_request_number",
            "metadata",
            "version",
            "created_at",
            "updated_at",
        ),
        ("run_id",),
        frozenset({"metadata"}),
    ),
    (
        "agent_stage_records",
        (
            "run_id",
            "stage",
            "attempt",
            "status",
            "artifact_sha256",
            "previous_artifact_sha256",
            "source_sha",
            "branch_sha",
            "payload",
            "created_at",
        ),
        ("run_id", "stage", "attempt"),
        frozenset({"payload"}),
    ),
    (
        "agent_idempotency_keys",
        (
            "idempotency_key",
            "run_id",
            "operation",
            "request_sha256",
            "result",
            "created_at",
            "completed_at",
        ),
        ("idempotency_key",),
        frozenset({"result"}),
    ),
    (
        "agent_webhook_events",
        (
            "delivery_id",
            "event_type",
            "payload",
            "status",
            "attempts",
            "available_at",
            "locked_by",
            "locked_at",
            "result",
            "last_error",
            "created_at",
            "updated_at",
        ),
        ("delivery_id",),
        frozenset({"payload", "result"}),
    ),
    (
        "agent_approvals",
        ("run_id", "approval_kind", "external_id", "approved_by", "metadata", "created_at"),
        ("run_id", "approval_kind", "external_id"),
        frozenset({"metadata"}),
    ),
    (
        "agent_pull_requests",
        (
            "run_id",
            "repository",
            "pull_request_number",
            "branch_name",
            "branch_sha",
            "state",
            "metadata",
            "updated_at",
        ),
        ("run_id", "repository", "pull_request_number"),
        frozenset({"metadata"}),
    ),
    (
        "agent_comments",
        (
            "run_id",
            "repository",
            "pull_request_number",
            "comment_id",
            "comment_kind",
            "processed",
            "metadata",
            "updated_at",
        ),
        ("run_id", "comment_kind", "comment_id"),
        frozenset({"metadata"}),
    ),
    (
        "agent_repair_attempts",
        (
            "run_id",
            "attempt",
            "status",
            "input_patch_sha256",
            "output_patch_sha256",
            "branch_sha",
            "commit_sha",
            "metadata",
            "created_at",
        ),
        ("run_id", "attempt"),
        frozenset({"metadata"}),
    ),
)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    repository: str
    status: str
    source_sha: str
    current_stage: str | None = None
    branch_name: str | None = None
    branch_sha: str | None = None
    issue_number: int | None = None
    pull_request_number: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TransitionResult:
    run_id: str
    version: int
    status: str
    current_stage: str | None
    branch_sha: str | None
    replayed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "version": self.version,
            "status": self.status,
            "current_stage": self.current_stage,
            "branch_sha": self.branch_sha,
        }


@dataclass(frozen=True)
class ResumeCheckpoint:
    run_id: str
    run_status: str
    run_version: int
    source_sha: str
    branch_name: str | None
    branch_sha: str | None
    checkpoint_stage: str
    checkpoint_attempt: int
    artifact_sha256: str
    previous_artifact_sha256: str | None
    checkpoint_source_sha: str
    checkpoint_branch_sha: str | None
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_status": self.run_status,
            "run_version": self.run_version,
            "source_sha": self.source_sha,
            "branch_name": self.branch_name,
            "branch_sha": self.branch_sha,
            "checkpoint_stage": self.checkpoint_stage,
            "checkpoint_attempt": self.checkpoint_attempt,
            "artifact_sha256": self.artifact_sha256,
            "previous_artifact_sha256": self.previous_artifact_sha256,
            "checkpoint_source_sha": self.checkpoint_source_sha,
            "checkpoint_branch_sha": self.checkpoint_branch_sha,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class WebhookEvent:
    delivery_id: str
    event_type: str
    payload: dict[str, object]
    attempts: int

    def as_dict(self) -> dict[str, object]:
        return {
            "delivery_id": self.delivery_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "attempts": self.attempts,
        }


class PostgresStateStore:
    def __init__(self, connection: Any):
        self.connection = connection

    @classmethod
    def connect(cls, dsn: str) -> PostgresStateStore:
        if not dsn:
            raise StateStoreError("PostgreSQL DSN is required")
        try:
            import psycopg

            connection = psycopg.connect(dsn)
        except Exception as exc:
            raise StateStoreError("unable to connect to PostgreSQL") from exc
        return cls(connection)

    def close(self) -> None:
        self.connection.close()

    def initialize_schema(self) -> None:
        migration = files("otc_agent.migrations").joinpath("001_durable_execution.sql").read_text(
            encoding="utf-8"
        )
        try:
            with self.connection.transaction():
                self.connection.execute(migration)
        except Exception as exc:
            raise StateStoreError("unable to initialize durable execution schema") from exc

    def create_run(self, record: RunRecord) -> None:
        if not record.run_id or not record.repository or not record.status:
            raise StateStoreError("run identity, repository, and status are required")
        self._execute(
            """
            INSERT INTO agent_runs (
                run_id, repository, status, current_stage, source_sha, branch_name,
                branch_sha, issue_number, pull_request_number, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id) DO NOTHING
            """,
            (
                record.run_id,
                record.repository,
                record.status,
                record.current_stage,
                record.source_sha,
                record.branch_name,
                record.branch_sha,
                record.issue_number,
                record.pull_request_number,
                _json(record.metadata),
            ),
        )

    def record_stage(
        self,
        *,
        run_id: str,
        stage: str,
        attempt: int,
        status: str,
        artifact_sha256: str,
        previous_artifact_sha256: str | None,
        source_sha: str,
        branch_sha: str | None,
        payload: dict[str, object],
    ) -> None:
        self._execute(
            """
            INSERT INTO agent_stage_records (
                run_id, stage, attempt, status, artifact_sha256, previous_artifact_sha256,
                source_sha, branch_sha, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id, stage, attempt) DO UPDATE SET
                status = EXCLUDED.status,
                artifact_sha256 = EXCLUDED.artifact_sha256,
                previous_artifact_sha256 = EXCLUDED.previous_artifact_sha256,
                source_sha = EXCLUDED.source_sha,
                branch_sha = EXCLUDED.branch_sha,
                payload = EXCLUDED.payload
            """,
            (
                run_id,
                stage,
                attempt,
                status,
                artifact_sha256,
                previous_artifact_sha256,
                source_sha,
                branch_sha,
                _json(payload),
            ),
        )

    def record_approval(
        self,
        *,
        run_id: str,
        approval_kind: str,
        external_id: str,
        approved_by: str | None,
        metadata: dict[str, object],
    ) -> None:
        self._execute(
            """
            INSERT INTO agent_approvals (
                run_id, approval_kind, external_id, approved_by, metadata
            ) VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id, approval_kind, external_id) DO UPDATE SET
                approved_by = EXCLUDED.approved_by,
                metadata = EXCLUDED.metadata
            """,
            (run_id, approval_kind, external_id, approved_by, _json(metadata)),
        )

    def record_pull_request(
        self,
        *,
        run_id: str,
        repository: str,
        pull_request_number: int,
        branch_name: str,
        branch_sha: str,
        state: str,
        metadata: dict[str, object],
    ) -> None:
        self._execute(
            """
            INSERT INTO agent_pull_requests (
                run_id, repository, pull_request_number, branch_name, branch_sha, state, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id, repository, pull_request_number) DO UPDATE SET
                branch_name = EXCLUDED.branch_name,
                branch_sha = EXCLUDED.branch_sha,
                state = EXCLUDED.state,
                metadata = EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                run_id,
                repository,
                pull_request_number,
                branch_name,
                branch_sha,
                state,
                _json(metadata),
            ),
        )

    def record_comment(
        self,
        *,
        run_id: str,
        repository: str,
        pull_request_number: int,
        comment_id: int,
        comment_kind: str,
        processed: bool,
        metadata: dict[str, object],
    ) -> None:
        self._execute(
            """
            INSERT INTO agent_comments (
                run_id, repository, pull_request_number, comment_id, comment_kind, processed, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id, comment_kind, comment_id) DO UPDATE SET
                processed = EXCLUDED.processed,
                metadata = EXCLUDED.metadata,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                run_id,
                repository,
                pull_request_number,
                comment_id,
                comment_kind,
                processed,
                _json(metadata),
            ),
        )

    def record_repair_attempt(
        self,
        *,
        run_id: str,
        attempt: int,
        status: str,
        input_patch_sha256: str,
        output_patch_sha256: str | None,
        branch_sha: str | None,
        commit_sha: str | None,
        metadata: dict[str, object],
    ) -> None:
        self._execute(
            """
            INSERT INTO agent_repair_attempts (
                run_id, attempt, status, input_patch_sha256, output_patch_sha256,
                branch_sha, commit_sha, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (run_id, attempt) DO UPDATE SET
                status = EXCLUDED.status,
                output_patch_sha256 = EXCLUDED.output_patch_sha256,
                branch_sha = EXCLUDED.branch_sha,
                commit_sha = EXCLUDED.commit_sha,
                metadata = EXCLUDED.metadata
            """,
            (
                run_id,
                attempt,
                status,
                input_patch_sha256,
                output_patch_sha256,
                branch_sha,
                commit_sha,
                _json(metadata),
            ),
        )

    def transition_run(
        self,
        *,
        run_id: str,
        expected_version: int,
        status: str,
        current_stage: str | None,
        branch_sha: str | None,
        idempotency_key: str,
        operation: str,
        request: dict[str, object],
    ) -> TransitionResult:
        request_sha256 = _request_sha256(request)
        if not idempotency_key or not operation or expected_version < 0:
            raise StateStoreError("transition idempotency key, operation, and version are required")
        try:
            with self.connection.transaction():
                inserted = self.connection.execute(
                    """
                    INSERT INTO agent_idempotency_keys (
                        idempotency_key, run_id, operation, request_sha256
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING idempotency_key
                    """,
                    (idempotency_key, run_id, operation, request_sha256),
                ).fetchone()
                if inserted is None:
                    return self._postgres_replay_transition(
                        idempotency_key,
                        run_id,
                        operation,
                        request_sha256,
                    )
                row = self.connection.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s,
                        current_stage = %s,
                        branch_sha = COALESCE(%s, branch_sha),
                        version = version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE run_id = %s AND version = %s
                    RETURNING version, status, current_stage, branch_sha
                    """,
                    (status, current_stage, branch_sha, run_id, expected_version),
                ).fetchone()
                if row is None:
                    raise StateConflictError("run state version changed before transition")
                result = TransitionResult(run_id, row[0], row[1], row[2], row[3], False)
                self.connection.execute(
                    """
                    UPDATE agent_idempotency_keys
                    SET result = %s::jsonb, completed_at = CURRENT_TIMESTAMP
                    WHERE idempotency_key = %s
                    """,
                    (_json(result.as_dict()), idempotency_key),
                )
                return result
        except StateStoreError:
            raise
        except Exception as exc:
            raise StateStoreError("unable to transition durable run state") from exc

    def _postgres_replay_transition(
        self,
        idempotency_key: str,
        run_id: str,
        operation: str,
        request_sha256: str,
    ) -> TransitionResult:
        row = self.connection.execute(
            """
            SELECT run_id, operation, request_sha256, result
            FROM agent_idempotency_keys
            WHERE idempotency_key = %s
            FOR UPDATE
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None or row[0] != run_id or row[1] != operation or row[2] != request_sha256:
            raise StateConflictError("idempotency key was reused for a different transition")
        return _transition_from_stored_result(row[3])

    def load_resume_checkpoint(self, run_id: str) -> ResumeCheckpoint:
        try:
            with self.connection.transaction():
                run = self.connection.execute(
                    """
                    SELECT run_id, status, version, source_sha, branch_name, branch_sha
                    FROM agent_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                ).fetchone()
                checkpoint = self.connection.execute(
                    """
                    SELECT stage, attempt, artifact_sha256, previous_artifact_sha256,
                           source_sha, branch_sha, payload
                    FROM agent_stage_records
                    WHERE run_id = %s AND status IN ('passed', 'approved', 'completed')
                    ORDER BY created_at DESC, attempt DESC
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
        except Exception as exc:
            raise StateStoreError("unable to load durable resume checkpoint") from exc
        return _resume_checkpoint(run, checkpoint)

    def enqueue_webhook(
        self,
        *,
        delivery_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> bool:
        if not delivery_id or not event_type:
            raise StateStoreError("webhook delivery ID and event type are required")
        try:
            with self.connection.transaction():
                row = self.connection.execute(
                    """
                    INSERT INTO agent_webhook_events (delivery_id, event_type, payload)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (delivery_id) DO NOTHING
                    RETURNING delivery_id
                    """,
                    (delivery_id, event_type, _json(payload)),
                ).fetchone()
                return row is not None
        except Exception as exc:
            raise StateStoreError("unable to enqueue webhook event") from exc

    def claim_webhook(self, worker_id: str) -> WebhookEvent | None:
        if not worker_id:
            raise StateStoreError("webhook worker ID is required")
        try:
            with self.connection.transaction():
                row = self.connection.execute(
                    """
                    WITH candidate AS (
                        SELECT delivery_id
                        FROM agent_webhook_events
                        WHERE status = 'queued' AND available_at <= CURRENT_TIMESTAMP
                        ORDER BY available_at, created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE agent_webhook_events AS event
                    SET status = 'processing',
                        attempts = attempts + 1,
                        locked_by = %s,
                        locked_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    FROM candidate
                    WHERE event.delivery_id = candidate.delivery_id
                    RETURNING event.delivery_id, event.event_type, event.payload, event.attempts
                    """,
                    (worker_id,),
                ).fetchone()
        except Exception as exc:
            raise StateStoreError("unable to claim webhook event") from exc
        return _webhook_event(row)

    def complete_webhook(self, delivery_id: str, result: dict[str, object]) -> None:
        self._webhook_update(
            """
            UPDATE agent_webhook_events
            SET status = 'completed',
                result = %s::jsonb,
                locked_by = NULL,
                locked_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE delivery_id = %s AND status = 'processing'
            RETURNING delivery_id
            """,
            (_json(result), delivery_id),
            "complete",
        )

    def fail_webhook(
        self,
        delivery_id: str,
        *,
        error: str,
        max_attempts: int,
        retry_seconds: int,
    ) -> str:
        if max_attempts < 1 or retry_seconds < 0 or not error:
            raise StateStoreError("invalid webhook failure policy")
        try:
            with self.connection.transaction():
                row = self.connection.execute(
                    """
                    UPDATE agent_webhook_events
                    SET status = CASE WHEN attempts >= %s THEN 'dead_letter' ELSE 'queued' END,
                        available_at = CASE
                            WHEN attempts >= %s THEN available_at
                            ELSE CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')
                        END,
                        last_error = %s,
                        locked_by = NULL,
                        locked_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE delivery_id = %s AND status = 'processing'
                    RETURNING status
                    """,
                    (max_attempts, max_attempts, retry_seconds, error[:4000], delivery_id),
                ).fetchone()
        except Exception as exc:
            raise StateStoreError("unable to fail webhook event") from exc
        if row is None or row[0] not in {"queued", "dead_letter"}:
            raise StateConflictError("webhook event is not in processing state")
        return row[0]

    def _webhook_update(
        self,
        statement: str,
        parameters: tuple[object, ...],
        operation: str,
    ) -> None:
        try:
            with self.connection.transaction():
                row = self.connection.execute(statement, parameters).fetchone()
        except Exception as exc:
            raise StateStoreError(f"unable to {operation} webhook event") from exc
        if row is None:
            raise StateConflictError("webhook event is not in processing state")

    def _execute(self, statement: str, parameters: tuple[object, ...]) -> None:
        try:
            with self.connection.transaction():
                self.connection.execute(statement, parameters)
        except Exception as exc:
            raise StateStoreError("unable to persist durable execution state") from exc


def _json(value: dict[str, object]) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise StateStoreError("durable state metadata must be JSON serializable") from exc


class MySQLStateStore(PostgresStateStore):
    @classmethod
    def connect(cls, dsn: str | None = None) -> MySQLStateStore:
        try:
            import pymysql

            options = _mysql_options(dsn)
            connection = pymysql.connect(**options)
        except Exception as exc:
            raise StateStoreError("unable to connect to local MySQL") from exc
        return cls(connection)

    def initialize_schema(self) -> None:
        migration = files("otc_agent.migrations").joinpath(
            "001_durable_execution_mysql.sql"
        ).read_text(encoding="utf-8")
        try:
            with self.connection.cursor() as cursor:
                for statement in migration.split(";"):
                    if statement.strip():
                        cursor.execute(statement)
            self.connection.commit()
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError("unable to initialize durable execution schema") from exc

    def create_run(self, record: RunRecord) -> None:
        if not record.run_id or not record.repository or not record.status:
            raise StateStoreError("run identity, repository, and status are required")
        self._mysql_execute(
            """
            INSERT INTO agent_runs (
                run_id, repository, status, current_stage, source_sha, branch_name,
                branch_sha, issue_number, pull_request_number, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE run_id = VALUES(run_id)
            """,
            (
                record.run_id,
                record.repository,
                record.status,
                record.current_stage,
                record.source_sha,
                record.branch_name,
                record.branch_sha,
                record.issue_number,
                record.pull_request_number,
                _json(record.metadata),
            ),
        )

    def record_stage(self, **values: Any) -> None:
        self._mysql_execute(
            """
            INSERT INTO agent_stage_records (
                run_id, stage, attempt, status, artifact_sha256, previous_artifact_sha256,
                source_sha, branch_sha, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                artifact_sha256 = VALUES(artifact_sha256),
                previous_artifact_sha256 = VALUES(previous_artifact_sha256),
                source_sha = VALUES(source_sha),
                branch_sha = VALUES(branch_sha),
                payload = VALUES(payload)
            """,
            (
                values["run_id"],
                values["stage"],
                values["attempt"],
                values["status"],
                values["artifact_sha256"],
                values["previous_artifact_sha256"],
                values["source_sha"],
                values["branch_sha"],
                _json(values["payload"]),
            ),
        )

    def record_approval(self, **values: Any) -> None:
        self._mysql_execute(
            """
            INSERT INTO agent_approvals (
                run_id, approval_kind, external_id, approved_by, metadata
            ) VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                approved_by = VALUES(approved_by),
                metadata = VALUES(metadata)
            """,
            (
                values["run_id"],
                values["approval_kind"],
                values["external_id"],
                values["approved_by"],
                _json(values["metadata"]),
            ),
        )

    def record_pull_request(self, **values: Any) -> None:
        self._mysql_execute(
            """
            INSERT INTO agent_pull_requests (
                run_id, repository, pull_request_number, branch_name, branch_sha, state, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                branch_name = VALUES(branch_name),
                branch_sha = VALUES(branch_sha),
                state = VALUES(state),
                metadata = VALUES(metadata)
            """,
            (
                values["run_id"],
                values["repository"],
                values["pull_request_number"],
                values["branch_name"],
                values["branch_sha"],
                values["state"],
                _json(values["metadata"]),
            ),
        )

    def record_comment(self, **values: Any) -> None:
        self._mysql_execute(
            """
            INSERT INTO agent_comments (
                run_id, repository, pull_request_number, comment_id, comment_kind, processed, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                processed = VALUES(processed),
                metadata = VALUES(metadata)
            """,
            (
                values["run_id"],
                values["repository"],
                values["pull_request_number"],
                values["comment_id"],
                values["comment_kind"],
                values["processed"],
                _json(values["metadata"]),
            ),
        )

    def record_repair_attempt(self, **values: Any) -> None:
        self._mysql_execute(
            """
            INSERT INTO agent_repair_attempts (
                run_id, attempt, status, input_patch_sha256, output_patch_sha256,
                branch_sha, commit_sha, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                output_patch_sha256 = VALUES(output_patch_sha256),
                branch_sha = VALUES(branch_sha),
                commit_sha = VALUES(commit_sha),
                metadata = VALUES(metadata)
            """,
            (
                values["run_id"],
                values["attempt"],
                values["status"],
                values["input_patch_sha256"],
                values["output_patch_sha256"],
                values["branch_sha"],
                values["commit_sha"],
                _json(values["metadata"]),
            ),
        )

    def transition_run(self, **values: Any) -> TransitionResult:
        request_sha256 = _request_sha256(values["request"])
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT IGNORE INTO agent_idempotency_keys (
                        idempotency_key, run_id, operation, request_sha256
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        values["idempotency_key"],
                        values["run_id"],
                        values["operation"],
                        request_sha256,
                    ),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        SELECT run_id, operation, request_sha256, result
                        FROM agent_idempotency_keys
                        WHERE idempotency_key = %s
                        FOR UPDATE
                        """,
                        (values["idempotency_key"],),
                    )
                    row = cursor.fetchone()
                    result = _validate_replayed_transition(
                        row,
                        values["run_id"],
                        values["operation"],
                        request_sha256,
                    )
                    self.connection.commit()
                    return result
                cursor.execute(
                    """
                    UPDATE agent_runs
                    SET status = %s,
                        current_stage = %s,
                        branch_sha = COALESCE(%s, branch_sha),
                        version = version + 1
                    WHERE run_id = %s AND version = %s
                    """,
                    (
                        values["status"],
                        values["current_stage"],
                        values["branch_sha"],
                        values["run_id"],
                        values["expected_version"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise StateConflictError("run state version changed before transition")
                cursor.execute(
                    "SELECT version, status, current_stage, branch_sha FROM agent_runs WHERE run_id = %s",
                    (values["run_id"],),
                )
                row = cursor.fetchone()
                if row is None:
                    raise StateConflictError("transitioned run no longer exists")
                result = TransitionResult(values["run_id"], row[0], row[1], row[2], row[3], False)
                cursor.execute(
                    """
                    UPDATE agent_idempotency_keys
                    SET result = %s, completed_at = CURRENT_TIMESTAMP(6)
                    WHERE idempotency_key = %s
                    """,
                    (_json(result.as_dict()), values["idempotency_key"]),
                )
            self.connection.commit()
            return result
        except StateStoreError:
            self.connection.rollback()
            raise
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError("unable to transition durable run state") from exc

    def load_resume_checkpoint(self, run_id: str) -> ResumeCheckpoint:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT run_id, status, version, source_sha, branch_name, branch_sha
                    FROM agent_runs
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                run = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT stage, attempt, artifact_sha256, previous_artifact_sha256,
                           source_sha, branch_sha, payload
                    FROM agent_stage_records
                    WHERE run_id = %s AND status IN ('passed', 'approved', 'completed')
                    ORDER BY created_at DESC, attempt DESC
                    LIMIT 1
                    """,
                    (run_id,),
                )
                checkpoint = cursor.fetchone()
        except Exception as exc:
            raise StateStoreError("unable to load durable resume checkpoint") from exc
        return _resume_checkpoint(run, checkpoint)

    def enqueue_webhook(self, **values: Any) -> bool:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT IGNORE INTO agent_webhook_events (delivery_id, event_type, payload)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        values["delivery_id"],
                        values["event_type"],
                        _json(values["payload"]),
                    ),
                )
                inserted = cursor.rowcount == 1
            self.connection.commit()
            return inserted
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError("unable to enqueue webhook event") from exc

    def claim_webhook(self, worker_id: str) -> WebhookEvent | None:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT delivery_id, event_type, payload, attempts
                    FROM agent_webhook_events
                    WHERE status = 'queued' AND available_at <= CURRENT_TIMESTAMP(6)
                    ORDER BY available_at, created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                row = cursor.fetchone()
                if row is None:
                    self.connection.commit()
                    return None
                cursor.execute(
                    """
                    UPDATE agent_webhook_events
                    SET status = 'processing',
                        attempts = attempts + 1,
                        locked_by = %s,
                        locked_at = CURRENT_TIMESTAMP(6)
                    WHERE delivery_id = %s AND status = 'queued'
                    """,
                    (worker_id, row[0]),
                )
                if cursor.rowcount != 1:
                    raise StateConflictError("webhook event was claimed concurrently")
                event = _webhook_event((row[0], row[1], row[2], row[3] + 1))
            self.connection.commit()
            return event
        except StateStoreError:
            self.connection.rollback()
            raise
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError("unable to claim webhook event") from exc

    def complete_webhook(self, delivery_id: str, result: dict[str, object]) -> None:
        self._mysql_webhook_update(
            """
            UPDATE agent_webhook_events
            SET status = 'completed', result = %s, locked_by = NULL, locked_at = NULL
            WHERE delivery_id = %s AND status = 'processing'
            """,
            (_json(result), delivery_id),
            "complete",
        )

    def fail_webhook(
        self,
        delivery_id: str,
        *,
        error: str,
        max_attempts: int,
        retry_seconds: int,
    ) -> str:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE agent_webhook_events
                    SET status = IF(attempts >= %s, 'dead_letter', 'queued'),
                        available_at = IF(
                            attempts >= %s,
                            available_at,
                            TIMESTAMPADD(SECOND, %s, CURRENT_TIMESTAMP(6))
                        ),
                        last_error = %s,
                        locked_by = NULL,
                        locked_at = NULL
                    WHERE delivery_id = %s AND status = 'processing'
                    """,
                    (max_attempts, max_attempts, retry_seconds, error[:4000], delivery_id),
                )
                if cursor.rowcount != 1:
                    raise StateConflictError("webhook event is not in processing state")
                cursor.execute(
                    "SELECT status FROM agent_webhook_events WHERE delivery_id = %s",
                    (delivery_id,),
                )
                row = cursor.fetchone()
            self.connection.commit()
        except StateStoreError:
            self.connection.rollback()
            raise
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError("unable to fail webhook event") from exc
        if row is None or row[0] not in {"queued", "dead_letter"}:
            raise StateStoreError("webhook failure state is invalid")
        return row[0]

    def _mysql_webhook_update(
        self,
        statement: str,
        parameters: tuple[object, ...],
        operation: str,
    ) -> None:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(statement, parameters)
                if cursor.rowcount != 1:
                    raise StateConflictError("webhook event is not in processing state")
            self.connection.commit()
        except StateStoreError:
            self.connection.rollback()
            raise
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError(f"unable to {operation} webhook event") from exc

    def _mysql_execute(self, statement: str, parameters: tuple[object, ...]) -> None:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(statement, parameters)
            self.connection.commit()
        except Exception as exc:
            self.connection.rollback()
            raise StateStoreError("unable to persist durable execution state") from exc


def connect_state_store(
    postgres_dsn: str | None = None,
    mysql_dsn: str | None = None,
) -> PostgresStateStore:
    configured_postgres = postgres_dsn or os.environ.get("OTC_POSTGRES_DSN")
    if configured_postgres:
        return PostgresStateStore.connect(configured_postgres)
    return MySQLStateStore.connect(mysql_dsn or os.environ.get("OTC_MYSQL_DSN"))


def migrate_mysql_to_postgres(
    *,
    mysql_dsn: str | None,
    postgres_dsn: str | None,
) -> dict[str, int]:
    if not postgres_dsn:
        raise StateStoreError("PostgreSQL DSN is required for state migration")
    source = MySQLStateStore.connect(mysql_dsn)
    target = PostgresStateStore.connect(postgres_dsn)
    try:
        source.initialize_schema()
        target.initialize_schema()
        return migrate_state_connections(source.connection, target.connection)
    finally:
        source.close()
        target.close()


def migrate_state_connections(mysql_connection: Any, postgres_connection: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with postgres_connection.transaction():
            with mysql_connection.cursor() as cursor:
                for table, columns, primary_key, json_columns in _MIGRATION_TABLES:
                    cursor.execute(f"SELECT {', '.join(columns)} FROM {table}")
                    rows = cursor.fetchall()
                    statement = _postgres_migration_upsert(
                        table,
                        columns,
                        primary_key,
                        json_columns,
                    )
                    for row in rows:
                        if not isinstance(row, (tuple, list)) or len(row) != len(columns):
                            raise StateStoreError("MySQL migration row does not match the expected schema")
                        postgres_connection.execute(
                            statement,
                            tuple(
                                _migration_value(column, value, json_columns)
                                for column, value in zip(columns, row, strict=True)
                            ),
                        )
                    counts[table] = len(rows)
    except StateStoreError:
        raise
    except Exception as exc:
        raise StateStoreError("unable to migrate MySQL durable state to PostgreSQL") from exc
    return counts


def _postgres_migration_upsert(
    table: str,
    columns: tuple[str, ...],
    primary_key: tuple[str, ...],
    json_columns: frozenset[str],
) -> str:
    placeholders = [
        "%s::jsonb" if column in json_columns else "%s"
        for column in columns
    ]
    updates = [
        f"{column} = EXCLUDED.{column}"
        for column in columns
        if column not in primary_key
    ]
    return (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT ({', '.join(primary_key)}) DO UPDATE SET {', '.join(updates)}"
    )


def _migration_value(
    column: str,
    value: object,
    json_columns: frozenset[str],
) -> object:
    if column not in json_columns or isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise StateStoreError("MySQL migration contains invalid JSON metadata") from exc


def _request_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _transition_from_stored_result(value: object) -> TransitionResult:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StateConflictError("stored idempotency result is invalid") from exc
    if not isinstance(value, dict):
        raise StateConflictError("idempotent transition has no completed result")
    try:
        return TransitionResult(
            run_id=value["run_id"],
            version=value["version"],
            status=value["status"],
            current_stage=value["current_stage"],
            branch_sha=value["branch_sha"],
            replayed=True,
        )
    except (KeyError, TypeError) as exc:
        raise StateConflictError("stored idempotency result has an invalid schema") from exc


def _validate_replayed_transition(
    row: object,
    run_id: str,
    operation: str,
    request_sha256: str,
) -> TransitionResult:
    if (
        not isinstance(row, (tuple, list))
        or len(row) != 4
        or row[0] != run_id
        or row[1] != operation
        or row[2] != request_sha256
    ):
        raise StateConflictError("idempotency key was reused for a different transition")
    return _transition_from_stored_result(row[3])


def _resume_checkpoint(run: object, checkpoint: object) -> ResumeCheckpoint:
    if not isinstance(run, (tuple, list)) or len(run) != 6:
        raise StateStoreError("durable run was not found")
    if not isinstance(checkpoint, (tuple, list)) or len(checkpoint) != 7:
        raise StateStoreError("durable run has no verified checkpoint")
    payload = checkpoint[6]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise StateStoreError("durable checkpoint payload is invalid") from exc
    if not isinstance(payload, dict):
        raise StateStoreError("durable checkpoint payload must be an object")
    if (
        not isinstance(run[0], str)
        or not isinstance(run[1], str)
        or not isinstance(run[2], int)
        or not isinstance(run[3], str)
        or not isinstance(checkpoint[0], str)
        or not isinstance(checkpoint[1], int)
        or not isinstance(checkpoint[2], str)
        or not isinstance(checkpoint[4], str)
    ):
        raise StateStoreError("durable checkpoint contains invalid identity fields")
    return ResumeCheckpoint(
        run_id=run[0],
        run_status=run[1],
        run_version=run[2],
        source_sha=run[3],
        branch_name=run[4],
        branch_sha=run[5],
        checkpoint_stage=checkpoint[0],
        checkpoint_attempt=checkpoint[1],
        artifact_sha256=checkpoint[2],
        previous_artifact_sha256=checkpoint[3],
        checkpoint_source_sha=checkpoint[4],
        checkpoint_branch_sha=checkpoint[5],
        payload=payload,
    )


def _webhook_event(row: object) -> WebhookEvent | None:
    if row is None:
        return None
    if not isinstance(row, (tuple, list)) or len(row) != 4:
        raise StateStoreError("claimed webhook event has an invalid schema")
    payload = row[2]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise StateStoreError("claimed webhook payload is invalid") from exc
    if (
        not isinstance(row[0], str)
        or not isinstance(row[1], str)
        or not isinstance(payload, dict)
        or not isinstance(row[3], int)
    ):
        raise StateStoreError("claimed webhook event has invalid fields")
    return WebhookEvent(row[0], row[1], payload, row[3])


def _mysql_options(dsn: str | None) -> dict[str, object]:
    if not dsn:
        return {
            "host": os.environ.get("OTC_MYSQL_HOST", "127.0.0.1"),
            "port": int(os.environ.get("OTC_MYSQL_PORT", "3306")),
            "user": os.environ.get("OTC_MYSQL_USER", "root"),
            "password": os.environ.get("OTC_MYSQL_PASSWORD", ""),
            "database": os.environ.get("OTC_MYSQL_DATABASE", "otc_agent"),
            "charset": "utf8mb4",
            "autocommit": False,
        }
    value = urlparse(dsn)
    if value.scheme != "mysql" or not value.hostname or not value.path.strip("/"):
        raise StateStoreError("MySQL DSN must use mysql://user:password@host:port/database")
    return {
        "host": value.hostname,
        "port": value.port or 3306,
        "user": unquote(value.username or "root"),
        "password": unquote(value.password or ""),
        "database": value.path.strip("/"),
        "charset": "utf8mb4",
        "autocommit": False,
    }
