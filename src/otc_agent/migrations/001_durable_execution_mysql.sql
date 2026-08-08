CREATE TABLE IF NOT EXISTS agent_runs (
    run_id VARCHAR(255) PRIMARY KEY,
    repository VARCHAR(255) NOT NULL,
    status VARCHAR(64) NOT NULL,
    current_stage VARCHAR(64),
    source_sha CHAR(40) NOT NULL,
    branch_name VARCHAR(255),
    branch_sha CHAR(40),
    issue_number BIGINT,
    pull_request_number BIGINT,
    metadata JSON NOT NULL,
    version BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
);

CREATE TABLE IF NOT EXISTS agent_stage_records (
    run_id VARCHAR(255) NOT NULL,
    stage VARCHAR(64) NOT NULL,
    attempt INTEGER NOT NULL,
    status VARCHAR(64) NOT NULL,
    artifact_sha256 CHAR(64) NOT NULL,
    previous_artifact_sha256 CHAR(64),
    source_sha CHAR(40) NOT NULL,
    branch_sha CHAR(40),
    payload JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (run_id, stage, attempt),
    INDEX agent_stage_records_run_created_idx (run_id, created_at),
    CONSTRAINT agent_stage_records_run_fk FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_idempotency_keys (
    idempotency_key VARCHAR(255) PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL,
    operation VARCHAR(255) NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    result JSON,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at TIMESTAMP(6),
    CONSTRAINT agent_idempotency_keys_run_fk FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_webhook_events (
    delivery_id VARCHAR(255) PRIMARY KEY,
    event_type VARCHAR(255) NOT NULL,
    payload JSON NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    locked_by VARCHAR(255),
    locked_at TIMESTAMP(6),
    result JSON,
    last_error TEXT,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX agent_webhook_events_ready_idx (status, available_at, created_at)
);

CREATE TABLE IF NOT EXISTS agent_approvals (
    run_id VARCHAR(255) NOT NULL,
    approval_kind VARCHAR(64) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    approved_by VARCHAR(255),
    metadata JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (run_id, approval_kind, external_id),
    CONSTRAINT agent_approvals_run_fk FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_pull_requests (
    run_id VARCHAR(255) NOT NULL,
    repository VARCHAR(255) NOT NULL,
    pull_request_number BIGINT NOT NULL,
    branch_name VARCHAR(255) NOT NULL,
    branch_sha CHAR(40) NOT NULL,
    state VARCHAR(64) NOT NULL,
    metadata JSON NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (run_id, repository, pull_request_number),
    CONSTRAINT agent_pull_requests_run_fk FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_comments (
    run_id VARCHAR(255) NOT NULL,
    repository VARCHAR(255) NOT NULL,
    pull_request_number BIGINT NOT NULL,
    comment_id BIGINT NOT NULL,
    comment_kind VARCHAR(64) NOT NULL,
    processed BOOLEAN NOT NULL,
    metadata JSON NOT NULL,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (run_id, comment_kind, comment_id),
    INDEX agent_comments_unprocessed_idx (run_id, processed, comment_kind, comment_id),
    CONSTRAINT agent_comments_run_fk FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_repair_attempts (
    run_id VARCHAR(255) NOT NULL,
    attempt INTEGER NOT NULL,
    status VARCHAR(64) NOT NULL,
    input_patch_sha256 CHAR(64) NOT NULL,
    output_patch_sha256 CHAR(64),
    branch_sha CHAR(40),
    commit_sha CHAR(40),
    metadata JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (run_id, attempt),
    CONSTRAINT agent_repair_attempts_run_fk FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE CASCADE
);
