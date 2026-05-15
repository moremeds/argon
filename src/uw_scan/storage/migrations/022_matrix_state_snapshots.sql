-- 022_matrix_state_snapshots.sql — Cockpit 6-dimension matrix state.
-- See docs/superpowers/research/six-dimension-matrix/00-overview.md §0
-- for the direction-mapping, consistency-tier, and cluster-coverage rules
-- that produce the rows in this table.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.matrix_state_snapshots (
    ticker              TEXT NOT NULL,
    market_date         DATE NOT NULL,
    -- 6-dim directional labels per 00-overview.md §0.1.
    -- Each label is one of: 'vol_up' | 'vol_down' | 'neutral' | 'stale'.
    -- Flow combines the IM and Flow sub-readings per §0.1 footnote.
    vanna_state         TEXT,
    charm_state         TEXT,
    skew_state          TEXT,
    term_state          TEXT,
    im_state            TEXT,
    flow_state          TEXT,
    vrp_state           TEXT,
    -- Aggregate (per §0.2). 'strict' = 6/6 agree, 'strong' = 5/6,
    -- 'weak' = 4/6 with neither neutral being VRP or Term,
    -- 'no_trade' = anything weaker, 'insufficient_data' = ≥2 stale.
    consistency_tier    TEXT CHECK (consistency_tier IN (
        'strict', 'strong', 'weak', 'no_trade', 'insufficient_data'
    )),
    -- True when at least one of (Vanna, Charm) is non-neutral AND VRP
    -- sign-flip rule did not override per §0.2 cluster-coverage rules.
    cluster_coverage_ok BOOLEAN,
    -- Term classifier output (in addition to vol-direction label).
    -- 'contango' (front < back) | 'event_back' (event-driven inversion)
    -- | 'liquidity_back' (liquidity-driven inversion) | 'mixed'.
    term_classification TEXT,
    -- Snapshot of inputs that produced the labels — kept for replay/audit
    -- and for empirical threshold calibration (Phase 2 of backtest plan).
    skew_25d_zscore_180d NUMERIC,
    iv_atm_30d           NUMERIC,
    rv_30d               NUMERIC,
    vrp                  NUMERIC,
    vrp_zscore_60d       NUMERIC,
    implied_move_pct     NUMERIC,
    front_iv             NUMERIC,
    back_iv              NUMERIC,
    pin_distance_sigma   NUMERIC,
    -- Provenance
    source              TEXT NOT NULL DEFAULT 'cockpit_daily_snapshot',
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    inserted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.matrix_state_snapshots
    IS '6-dimension matrix state, one row per (ticker, market_date). '
       'Inputs in greeks_by_expiry_strike, exposures_by_expiry_strike, '
       'risk_reversal_skew_history, iv_term_snapshots, interpolated_iv_snapshots, '
       'realized_volatility_history. Derivation rules in research doc §0.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.consistency_tier
    IS 'Aggregate consistency label per §0.2. Drives Cockpit display tier '
       'and (post-calibration) trade-vs-no-trade gate.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.cluster_coverage_ok
    IS 'False when both Vanna and Charm are neutral (no dealer-flow '
       'confirmation per Limitation #1) — forces NO-TRADE in §0.2.';

COMMENT ON COLUMN uw_scan.matrix_state_snapshots.term_classification
    IS 'Categorical term-structure state. Independent of vol-direction '
       'label because Strategy 1 requires event_back AND vol_down.';

-- Reverse-chrono lookup for the most recent state per ticker.
CREATE INDEX IF NOT EXISTS idx_matrix_state_snapshots_recent
    ON uw_scan.matrix_state_snapshots (ticker, market_date DESC);

COMMIT;
