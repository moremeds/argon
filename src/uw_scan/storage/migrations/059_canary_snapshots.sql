-- src/uw_scan/storage/migrations/059_canary_snapshots.sql
-- 5% Canary indicator snapshots — one row per (data_date, composite_version).
-- See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §9.

CREATE TABLE IF NOT EXISTS uw_scan.canary_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    data_date         DATE NOT NULL,
    composite_version SMALLINT NOT NULL DEFAULT 1,
    score_form        TEXT NOT NULL,

    score             NUMERIC(5,2) NOT NULL,
    raw_score         NUMERIC(5,2) NOT NULL,
    band              TEXT NOT NULL,
    tactical_score    NUMERIC(5,2) NOT NULL,
    structural_score  NUMERIC(5,2) NOT NULL,
    speed_score       SMALLINT     NOT NULL,
    warning_state     TEXT NOT NULL,

    payload           JSONB NOT NULL,
    payload_hash      TEXT NOT NULL,
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS canary_snapshots_date_version_idx
    ON uw_scan.canary_snapshots (data_date, composite_version);

CREATE INDEX IF NOT EXISTS canary_snapshots_version_date_desc_idx
    ON uw_scan.canary_snapshots (composite_version, data_date DESC);

CREATE INDEX IF NOT EXISTS canary_snapshots_inserted_idx
    ON uw_scan.canary_snapshots (inserted_at DESC);

CREATE INDEX IF NOT EXISTS canary_snapshots_warning_idx
    ON uw_scan.canary_snapshots (warning_state, data_date DESC)
    WHERE warning_state != 'NONE';

-- CHECK constraints (idempotent via DO block — see spec §9)
DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_score_range_chk
        CHECK (score >= 0 AND score <= 100 AND raw_score >= 0 AND raw_score <= 100);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_band_chk
        CHECK (band IN ('NONE', 'WATCH', 'BUY', 'STRONG_BUY'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_warning_state_chk
        CHECK (warning_state IN ('NONE','CONFIRMED_CANARY_ACTIVE','BUY_THE_DIP_ACTIVE','BOTH_ACTIVE_AMBIGUOUS'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_score_form_chk
        CHECK (score_form IN ('linear', 'convex', 'concave', 'sigmoid'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_tier_scores_chk
        CHECK (tactical_score BETWEEN 0 AND 30
               AND structural_score BETWEEN 0 AND 50
               AND speed_score IN (0, 8, 20));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
