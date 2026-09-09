-- Durable, document-scoped provenance for citation rendering.
-- Filesystem paths are deliberately excluded from this table and public DTOs.

BEGIN;

CREATE TABLE IF NOT EXISTS citation_provenance (
    id                      BIGSERIAL PRIMARY KEY,
    kb_name                 TEXT NOT NULL,
    document_id             TEXT NOT NULL,
    document_name           TEXT NOT NULL DEFAULT '',
    chunk_id                TEXT NOT NULL,
    source_sha256           VARCHAR(64) NOT NULL,
    provenance_version      VARCHAR(64) NOT NULL DEFAULT 'v1',
    page                    INTEGER,
    page_idx                INTEGER,
    section_path            JSONB NOT NULL DEFAULT '[]'::jsonb,
    modality                VARCHAR(32) NOT NULL DEFAULT 'text',
    media_id                TEXT,
    segment_id              TEXT,
    element_id              TEXT,
    figure_label            TEXT,
    bbox                    JSONB,
    bbox_coordinate_system  JSONB,
    start_ms                BIGINT,
    end_ms                  BIGINT,
    frame_refs              JSONB NOT NULL DEFAULT '[]'::jsonb,
    locator_status          VARCHAR(32) NOT NULL DEFAULT 'unavailable',
    excerpt                 TEXT NOT NULL DEFAULT '',
    ingested_at             TIMESTAMPTZ,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_citation_provenance_identity
        UNIQUE (kb_name, document_id, chunk_id, provenance_version),
    CONSTRAINT ck_citation_provenance_source_sha256
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_citation_provenance_version
        CHECK (BTRIM(provenance_version) <> ''),
    CONSTRAINT ck_citation_provenance_page
        CHECK (page IS NULL OR page > 0),
    CONSTRAINT ck_citation_provenance_page_idx
        CHECK (page_idx IS NULL OR page_idx >= 0),
    CONSTRAINT ck_citation_provenance_page_basis
        CHECK (page IS NULL OR page_idx IS NULL OR page = page_idx + 1),
    CONSTRAINT ck_citation_provenance_section_path
        CHECK (jsonb_typeof(section_path) = 'array'),
    CONSTRAINT ck_citation_provenance_bbox
        CHECK (bbox IS NULL OR jsonb_typeof(bbox) IN ('array', 'object')),
    CONSTRAINT ck_citation_provenance_bbox_coordinate_system
        CHECK (
            bbox_coordinate_system IS NULL
            OR jsonb_typeof(bbox_coordinate_system) = 'object'
        ),
    CONSTRAINT ck_citation_provenance_frame_refs
        CHECK (jsonb_typeof(frame_refs) = 'array'),
    CONSTRAINT ck_citation_provenance_metadata
        CHECK (jsonb_typeof(metadata) = 'object'),
    CONSTRAINT ck_citation_provenance_modality
        CHECK (BTRIM(modality) <> ''),
    CONSTRAINT ck_citation_provenance_locator_status
        CHECK (locator_status IN ('exact', 'page', 'document', 'unavailable')),
    CONSTRAINT ck_citation_provenance_time_range
        CHECK (
            (start_ms IS NULL AND end_ms IS NULL)
            OR (start_ms IS NOT NULL AND end_ms IS NOT NULL
                AND start_ms >= 0 AND end_ms > start_ms)
        )
);

CREATE INDEX IF NOT EXISTS idx_citation_provenance_kb_chunk
    ON citation_provenance (kb_name, chunk_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_citation_provenance_reference
    ON citation_provenance (kb_name, document_id, chunk_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_citation_provenance_document_order
    ON citation_provenance (kb_name, document_id, page NULLS LAST, id);

COMMENT ON TABLE citation_provenance IS
    'Document-scoped citation provenance with no persisted filesystem paths.';

ALTER TABLE query_history
    ADD COLUMN IF NOT EXISTS citations JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_query_history_citations'
          AND conrelid = 'query_history'::regclass
    ) THEN
        ALTER TABLE query_history
            ADD CONSTRAINT ck_query_history_citations
            CHECK (jsonb_typeof(citations) = 'array');
    END IF;
END
$$;

COMMIT;
