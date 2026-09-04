-- 148_agent_runs.sql — one structured agent run, stored as an append-only row.
--
-- WHY THE TABLE KNOWS NOTHING ABOUT WHAT IT HOLDS
-- -----------------------------------------------
-- The producer of these rows is multi-tenant: one tenant mails a daily brief,
-- another heals a data pipeline. All of them produce the same SHAPE — a dated
-- run, under a tenant, of some kind, carrying a document only that tenant
-- understands. A column naming one tenant's phases, or a CHECK enumerating
-- them, would turn the second tenant into a migration instead of an insert.
-- `kind` is therefore an opaque, tenant-chosen label and `view_jsonb` is a
-- document this schema never interprets. The reader decides what it can render.
--
-- APPEND-ONLY AND VERSIONED
-- -------------------------
-- Same discipline as `research_reports` (migration 143): a re-render publishes
-- version N+1 beside version N and nothing is ever rewritten, so a page read
-- yesterday can still be re-opened as it was. `code_sha` records which build
-- wrote each version, which is the only way to explain a difference between two
-- versions of the same day without guessing.
--
-- WHY `run_id` IS UNIQUE PER TENANT
-- ---------------------------------
-- That uniqueness IS the idempotency of ingest. The writer retries blind — a
-- timeout it never saw the answer to, a redelivery, a restarted job — and the
-- second POST of the same run must return the version it already has rather
-- than publish a duplicate the reader would see as a second run.
--
-- WHY `week_key` IS STORED, NOT GENERATED
-- ---------------------------------------
-- A Monday review of the week that just ended belongs to that EARLIER week.
-- Only the writer knows a run is backward-looking, so the writer decides the
-- grouping key and this table stores it verbatim. Deriving it from `run_day`
-- here would silently file every such review under the wrong week.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.agent_runs (
    agent_run_id   bigserial PRIMARY KEY,
    tenant         text NOT NULL,
    kind           text NOT NULL,
    run_day        date NOT NULL,      -- the tenant's own report timezone; never re-derived here
    week_key       text NOT NULL,
    run_id         text NOT NULL,
    version_no     integer NOT NULL,
    code_sha       text NOT NULL,
    schema_version integer NOT NULL,
    outcome        text NOT NULL,
    headline       text NOT NULL DEFAULT '',   -- lifted out so an index need not parse the document
    view_jsonb     jsonb NOT NULL,
    report_jsonb   jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_runs_tenant_shape CHECK (tenant ~ '^[a-z0-9][a-z0-9-]{0,63}$'),
    CONSTRAINT agent_runs_kind_shape   CHECK (kind   ~ '^[a-z0-9][a-z0-9-]{0,31}$'),
    CONSTRAINT agent_runs_week_shape   CHECK (week_key ~ '^[0-9]{4}-W[0-9]{2}$'),
    CONSTRAINT agent_runs_outcome_check CHECK (outcome IN ('completed','DEGRADED','FAILED')),
    CONSTRAINT agent_runs_version_positive CHECK (version_no >= 1),
    CONSTRAINT agent_runs_version_uq UNIQUE (tenant, kind, run_day, version_no),
    CONSTRAINT agent_runs_run_uq     UNIQUE (tenant, run_id)   -- idempotency key
);

COMMENT ON TABLE uw_scan.agent_runs IS
    'One structured agent run per row, append-only and versioned. The table is '
    'deliberately generic: a tenant column, an opaque kind, and a document this '
    'schema never interprets. A second tenant is an insert, not a migration.';

COMMENT ON COLUMN uw_scan.agent_runs.kind IS
    'Opaque, tenant-chosen label for what this run is. Never enumerated here — a '
    'CHECK listing one tenant''s labels would make every new tenant a migration.';

COMMENT ON COLUMN uw_scan.agent_runs.week_key IS
    'ISO-style grouping key supplied by the writer and stored verbatim. A review '
    'published on a Monday belongs to the week that just ended, and only the '
    'writer knows that; deriving it from run_day would misfile every such run.';

COMMENT ON COLUMN uw_scan.agent_runs.run_id IS
    'The writer''s own id for this run, unique per tenant. That uniqueness is the '
    'idempotency of ingest: a blind retry returns the stored version instead of '
    'publishing a duplicate the reader would see as a second run.';

COMMENT ON COLUMN uw_scan.agent_runs.view_jsonb IS
    'The rendering document, opaque to this schema. schema_version states which '
    'shape the writer sent; the reader decides whether it can render it.';

CREATE INDEX IF NOT EXISTS ix_agent_runs_week
    ON uw_scan.agent_runs (tenant, week_key, run_day, kind, version_no DESC);
CREATE INDEX IF NOT EXISTS ix_agent_runs_latest
    ON uw_scan.agent_runs (tenant, kind, run_day DESC, version_no DESC);
CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_week
    ON uw_scan.agent_runs (tenant, week_key DESC);
