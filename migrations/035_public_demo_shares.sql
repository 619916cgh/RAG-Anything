-- Public demo links are capability tokens, not users.  The raw token never
-- reaches this table; only its SHA-256 digest is persisted.
CREATE TABLE IF NOT EXISTS demo_shares (
    share_id UUID PRIMARY KEY,
    token_hash CHAR(64) NOT NULL UNIQUE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE RESTRICT,
    kb_name TEXT NOT NULL,
    created_by BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at TIMESTAMPTZ,
    rate_window_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rate_request_count INTEGER NOT NULL DEFAULT 0 CHECK (rate_request_count >= 0),
    active_queries INTEGER NOT NULL DEFAULT 0 CHECK (active_queries >= 0),
    max_requests_per_minute INTEGER NOT NULL DEFAULT 10 CHECK (max_requests_per_minute BETWEEN 1 AND 120),
    max_concurrent_queries INTEGER NOT NULL DEFAULT 2 CHECK (max_concurrent_queries BETWEEN 1 AND 20)
);

CREATE INDEX IF NOT EXISTS idx_demo_shares_active
    ON demo_shares (share_id)
    WHERE revoked_at IS NULL;
