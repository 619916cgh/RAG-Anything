BEGIN;

-- Persist the same-context answer completeness guard per Agent. Existing
-- Agents remain disabled until an operator explicitly enables the feature.
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS answer_completeness_guard_enabled
    BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
