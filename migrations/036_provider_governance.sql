BEGIN;

-- Durable, provider-scoped admission state.  Values in these tables are
-- opaque hashes/fingerprints and bounded reason codes only; prompts, users,
-- tokens, credentials and provider URLs must never be persisted here.
CREATE TABLE IF NOT EXISTS provider_call_leases (
    id UUID PRIMARY KEY,
    profile_fingerprint VARCHAR(128) NOT NULL,
    owner_fence VARCHAR(128) NOT NULL,
    request_hash VARCHAR(128) NOT NULL,
    priority SMALLINT NOT NULL CHECK (priority IN (0, 10, 20)),
    state VARCHAR(16) NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'released')),
    expires_at TIMESTAMPTZ NOT NULL,
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at TIMESTAMPTZ,
    release_reason VARCHAR(32),
    CHECK ((state = 'active' AND released_at IS NULL)
        OR (state = 'released' AND released_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_provider_call_leases_active
    ON provider_call_leases(profile_fingerprint, expires_at)
    WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_provider_call_leases_owner
    ON provider_call_leases(id, owner_fence);

CREATE SEQUENCE IF NOT EXISTS provider_waiter_enqueue_seq;
CREATE TABLE IF NOT EXISTS provider_waiters (
    id UUID PRIMARY KEY,
    profile_fingerprint VARCHAR(128) NOT NULL,
    owner_fence VARCHAR(128) NOT NULL,
    request_hash VARCHAR(128) NOT NULL,
    priority SMALLINT NOT NULL CHECK (priority IN (0, 10, 20)),
    concurrency_limit INTEGER NOT NULL CHECK (concurrency_limit > 0),
    enqueue_seq BIGINT NOT NULL DEFAULT nextval('provider_waiter_enqueue_seq'),
    deadline_at TIMESTAMPTZ NOT NULL,
    state VARCHAR(16) NOT NULL DEFAULT 'waiting'
        CHECK (state IN ('waiting', 'claimed', 'cancelled', 'timed_out')),
    lease_id UUID REFERENCES provider_call_leases(id) ON DELETE SET NULL,
    cancel_reason VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_provider_waiters_queue
    ON provider_waiters(profile_fingerprint, state, priority, enqueue_seq);
CREATE INDEX IF NOT EXISTS idx_provider_waiters_deadline
    ON provider_waiters(profile_fingerprint, deadline_at)
    WHERE state = 'waiting';

CREATE TABLE IF NOT EXISTS provider_circuit_state (
    profile_fingerprint VARCHAR(128) PRIMARY KEY,
    state VARCHAR(16) NOT NULL DEFAULT 'closed'
        CHECK (state IN ('closed', 'open', 'half_open')),
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
    opened_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    probe_owner VARCHAR(128),
    probe_expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((state = 'open' AND cooldown_until IS NOT NULL)
        OR state <> 'open')
);

COMMIT;
