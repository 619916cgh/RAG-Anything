-- Retire the DAG workflow feature while preserving immutable migration history.
-- Existing workflow definitions and run records are intentionally deleted.

BEGIN;

UPDATE roles
SET permissions = (
    SELECT COALESCE(jsonb_agg(permission), '[]'::jsonb)
    FROM jsonb_array_elements_text(COALESCE(roles.permissions, '[]'::jsonb))
        AS permission
    WHERE permission NOT IN ('workflow:read', 'workflow:write')
);

DROP TABLE IF EXISTS workflow_runs;
DROP TABLE IF EXISTS workflow_definitions;

COMMIT;
