-- 054_trade_insight_outcomes.sql — idempotent.
-- Forward-looking outcome ledger for trade_insight_ai_analyses rows.
-- One row per analysis (UNIQUE on analysis_id). Populated by the nightly
-- worker job (`trade_insight_outcome_backfill`) which fetches OHLC for
-- each ticker from snapshot_date forward and computes whether each
-- v5.3 trigger component / invalidation / target actually fired.
--
-- For v4 / v5.0 / v5.1 / v5.2 rows that lack the v5.3 trigger
-- decomposition, only the fixed-window close fields are populated;
-- trigger-component fields stay NULL. The priors view filters by
-- prompt_version when it needs per-archetype accuracy stats.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.trade_insight_outcomes (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id                 UUID NOT NULL,
    ticker                      TEXT NOT NULL,
    provider                    TEXT NOT NULL,
    prompt_version              TEXT NOT NULL,

    -- Snapshot of state at analysis time
    snapshot_date               DATE NOT NULL,
    snapshot_close              NUMERIC(18,4),

    -- Fixed-window forward closes (business days post-snapshot_date)
    close_1d                    NUMERIC(18,4),
    close_1d_date               DATE,
    close_3d                    NUMERIC(18,4),
    close_3d_date               DATE,
    close_5d                    NUMERIC(18,4),
    close_5d_date               DATE,
    close_10d                   NUMERIC(18,4),
    close_10d_date              DATE,

    -- v5.3 trigger-component resolutions (NULL for pre-v5.3 rows)
    thesis_trigger_level        NUMERIC(18,4),
    thesis_trigger_meaning      TEXT,
    thesis_trigger_fired_after  BOOLEAN,
    thesis_trigger_hit_date     DATE,
    entry_trigger_level         NUMERIC(18,4),
    entry_trigger_meaning       TEXT,
    entry_trigger_fired_after   BOOLEAN,
    entry_trigger_hit_date      DATE,
    invalidation_level          NUMERIC(18,4),
    invalidation_hit            BOOLEAN,
    invalidation_hit_date       DATE,
    target_level                NUMERIC(18,4),
    target_hit                  BOOLEAN,
    target_hit_date             DATE,

    -- Resolution summary
    days_to_resolution          INTEGER,
    resolved_outcome            TEXT,
        -- 'target_hit' | 'invalidation_hit' | 'expired_no_resolution' | 'pending'
    notes                       TEXT,

    last_evaluated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 1:1 with analyses — the upsert key for the nightly job.
CREATE UNIQUE INDEX IF NOT EXISTS trade_insight_outcomes_analysis_id_uniq
    ON uw_scan.trade_insight_outcomes (analysis_id);

-- Read pattern: aggregate priors per (provider, prompt_version, archetype).
CREATE INDEX IF NOT EXISTS trade_insight_outcomes_provider_version_idx
    ON uw_scan.trade_insight_outcomes (provider, prompt_version);

-- Read pattern: per-ticker historical outcome timeline.
CREATE INDEX IF NOT EXISTS trade_insight_outcomes_ticker_snapshot_idx
    ON uw_scan.trade_insight_outcomes (ticker, snapshot_date DESC);

-- Read pattern: nightly worker scans rows still in resolution.
CREATE INDEX IF NOT EXISTS trade_insight_outcomes_pending_idx
    ON uw_scan.trade_insight_outcomes (last_evaluated_at)
    WHERE resolved_outcome IS NULL OR resolved_outcome = 'pending';

COMMENT ON TABLE uw_scan.trade_insight_outcomes IS
    'Forward-looking outcome ledger for trade_insight_ai_analyses rows. '
    'Populated nightly by trade_insight_outcome_backfill. Used by the priors '
    'view to compute per-provider per-archetype hit rates.';

COMMENT ON COLUMN uw_scan.trade_insight_outcomes.resolved_outcome IS
    'target_hit (target hit first), invalidation_hit (invalidation hit first), '
    'expired_no_resolution (preferred_expression.expiry passed without '
    'target/invalidation), or pending (still being scored).';
