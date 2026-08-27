-- 143_research_reports.sql — the durable research object, versioned and
-- replayable.
--
-- WHY A REPORT IS A ROW AND NOT A RENDERED PAGE
-- ---------------------------------------------
-- The point of this product is that an answer given in August can be re-opened
-- in November and explain what changed. A PDF cannot do that; neither can a
-- page assembled fresh on every request, because it would silently answer
-- November's question with November's data while carrying August's title.
--
-- A report therefore stores its MANIFEST — the exact engine version, taxonomy
-- version, evidence policy, and as-of that produced it — and a content hash of
-- its assembled blocks. Replay is re-assembly from the manifest plus a hash
-- comparison, and it works only because every input this reads is versioned and
-- append-only: statements (114), availability claims (130), scores and
-- dimensions (117/138), taxonomy (137), exposure (138), events (140). A single
-- in-place update anywhere upstream would make this gate unreachable.
--
-- APPEND-ONLY VERSIONS, NOT AN EDITABLE DOCUMENT
-- ----------------------------------------------
-- `(report_key, version_no)` is unique and nothing is ever rewritten. A refresh
-- publishes version N+1 beside version N, and the delta between them IS the
-- product feature — "what changed since the last time I looked" is the question
-- a research object exists to answer.
--
-- WHY A BLOCK CARRIES ITS OWN PROVENANCE
-- --------------------------------------
-- Every factual block names either the typed evidence it rests on or the
-- derivation that produced it. A block with neither is refused at assembly. The
-- alternative is a report whose numbers cannot be traced without re-running the
-- code that made them, which is the state this whole program exists to leave.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.research_reports (
    report_id        bigserial PRIMARY KEY,
    report_key       text NOT NULL,
    report_type      text NOT NULL,
    version_no       integer NOT NULL,
    title            text NOT NULL,
    -- The frozen question. Everything needed to reproduce this report.
    manifest_jsonb   jsonb NOT NULL,
    content_hash     text NOT NULL,
    status           text NOT NULL DEFAULT 'published',
    run_id           bigint REFERENCES uw_scan.fundamental_runs(run_id),
    superseded_by    bigint REFERENCES uw_scan.research_reports(report_id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT research_reports_type_check
        CHECK (report_type IN ('company', 'comparison', 'chain', 'watchlist')),
    CONSTRAINT research_reports_status_check
        CHECK (status IN ('draft', 'partial', 'published', 'superseded',
                          'stale')),
    CONSTRAINT research_reports_version_uq UNIQUE (report_key, version_no)
);

COMMENT ON TABLE uw_scan.research_reports IS
    'Versioned research reports. Append-only: a refresh publishes version N+1 '
    'beside N and the delta between them is the product feature. manifest_jsonb '
    'freezes every version and as-of that produced the content, so the report '
    'replays after new data and methods arrive.';

COMMENT ON COLUMN uw_scan.research_reports.content_hash IS
    'Hash of the assembled blocks. Replay = re-assemble from the manifest and '
    'compare. Only meaningful because every upstream input is versioned and '
    'append-only; one in-place update anywhere would break it.';

COMMENT ON COLUMN uw_scan.research_reports.status IS
    'partial = assembled with a declared unsupported-capability section. stale = '
    'an input moved after publication. Neither is an error: a report that '
    'refused to publish because one block was unsupported would be less useful '
    'than one that publishes and says so.';

CREATE INDEX IF NOT EXISTS ix_research_reports_key
    ON uw_scan.research_reports (report_key, version_no DESC);

CREATE INDEX IF NOT EXISTS ix_research_reports_type
    ON uw_scan.research_reports (report_type, created_at DESC);

CREATE TABLE IF NOT EXISTS uw_scan.research_report_blocks (
    block_id       bigserial PRIMARY KEY,
    report_id      bigint NOT NULL
                   REFERENCES uw_scan.research_reports(report_id)
                   ON DELETE CASCADE,
    ordinal        integer NOT NULL,
    block_kind     text NOT NULL,
    title          text NOT NULL,
    payload_jsonb  jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Typed evidence OR a declared derivation. Never neither.
    evidence_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
    derivation     text,
    authority      text,
    CONSTRAINT research_report_blocks_uq UNIQUE (report_id, ordinal),
    CONSTRAINT research_report_blocks_traceable
        CHECK (derivation IS NOT NULL OR evidence_jsonb <> '{}'::jsonb),
    -- The program ceiling, enforced in the store rather than in the assembler.
    -- A report block is the last surface before a human reads a number, and
    -- `investment_ranking` is the one permission nothing in this program earned.
    CONSTRAINT research_report_blocks_authority_check
        CHECK (authority IS NULL
               OR authority IN ('descriptive', 'research_priority',
                                'directional_monitor'))
);

DO $$
BEGIN
    ALTER TABLE uw_scan.research_report_blocks
        ADD CONSTRAINT research_report_blocks_authority_check
        CHECK (authority IS NULL
               OR authority IN ('descriptive', 'research_priority',
                                'directional_monitor'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN undefined_table THEN NULL;
END $$;

COMMENT ON CONSTRAINT research_report_blocks_traceable
    ON uw_scan.research_report_blocks IS
    'Every block names its evidence or its derivation. A block with neither is a '
    'number nobody can trace without re-running the code that made it.';

COMMENT ON COLUMN uw_scan.research_report_blocks.authority IS
    'The claim-registry permission this block exercises. NULL for a block that '
    'makes no ordering or directional claim at all.';

CREATE INDEX IF NOT EXISTS ix_research_report_blocks_report
    ON uw_scan.research_report_blocks (report_id, ordinal);
