BEGIN;

-- Optional default tag scope for an Agent. NULL means whole-KB retrieval.
ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS default_tag_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_agents_default_tag_id_positive'
    ) THEN
        ALTER TABLE agents
            ADD CONSTRAINT chk_agents_default_tag_id_positive
            CHECK (default_tag_id IS NULL OR default_tag_id > 0);
    END IF;
END $$;

COMMIT;
