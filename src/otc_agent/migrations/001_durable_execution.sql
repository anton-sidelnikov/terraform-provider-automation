CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT,
    source_sha TEXT NOT NULL,
    branch_name TEXT,
    branch_sha TEXT,
    issue_number BIGINT,
    pull_request_number BIGINT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_stage_records (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    previous_artifact_sha256 TEXT,
    source_sha TEXT NOT NULL,
    branch_sha TEXT,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, stage, attempt)
);

CREATE TABLE IF NOT EXISTS agent_idempotency_keys (
    idempotency_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_webhook_events (
    delivery_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_by TEXT,
    locked_at TIMESTAMPTZ,
    result JSONB,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_approvals (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    approval_kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    approved_by TEXT,
    metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, approval_kind, external_id)
);

CREATE TABLE IF NOT EXISTS agent_pull_requests (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    branch_name TEXT NOT NULL,
    branch_sha TEXT NOT NULL,
    state TEXT NOT NULL,
    metadata JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, repository, pull_request_number)
);

CREATE TABLE IF NOT EXISTS agent_comments (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    repository TEXT NOT NULL,
    pull_request_number BIGINT NOT NULL,
    comment_id BIGINT NOT NULL,
    comment_kind TEXT NOT NULL,
    processed BOOLEAN NOT NULL,
    metadata JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, comment_kind, comment_id)
);

CREATE TABLE IF NOT EXISTS agent_repair_attempts (
    run_id TEXT NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    input_patch_sha256 TEXT NOT NULL,
    output_patch_sha256 TEXT,
    branch_sha TEXT,
    commit_sha TEXT,
    metadata JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, attempt)
);

CREATE INDEX IF NOT EXISTS agent_stage_records_run_created_idx
    ON agent_stage_records (run_id, created_at);
CREATE INDEX IF NOT EXISTS agent_comments_unprocessed_idx
    ON agent_comments (run_id, processed, comment_kind, comment_id);
CREATE INDEX IF NOT EXISTS agent_webhook_events_ready_idx
    ON agent_webhook_events (status, available_at, created_at);
