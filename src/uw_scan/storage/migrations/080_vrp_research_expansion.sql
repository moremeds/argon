-- 080_vrp_research_expansion.sql
-- VRP research expansion: corp-action history, exact-RV validation, and the
-- three markout axes (sector, multi-horizon, directional/ΔVRP). Idempotent.
-- Design: docs/superpowers/plans/2026-06-22-vrp-research-expansion.md
SET search_path TO uw_scan, public;

BEGIN;

-- item 1: full corporate-action event history (massive_fundamentals keeps only
-- the LATEST split/dividend; split-adjusting a 13-month series needs all events).
CREATE TABLE IF NOT EXISTS uw_scan.corporate_actions (
    ticker        TEXT NOT NULL,
    event_type    TEXT NOT NULL,            -- 'split' | 'dividend'
    event_date    DATE NOT NULL,            -- split execution_date | dividend ex_dividend_date
    split_ratio   NUMERIC,                  -- split_to/split_from (splits only)
    cash_amount   NUMERIC,                  -- dividend cash (dividends only)
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, event_type, event_date)
);

COMMENT ON TABLE uw_scan.corporate_actions
    IS 'Per-event split/dividend history (item 1). Feeds split-adjusted price series for exact forward RV.';

-- item 1 diagnostic: per-ticker approximation-vs-exact forward-RV deviation.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_rv_validation (
    ticker            TEXT NOT NULL,
    horizon           INTEGER NOT NULL,
    n                 INTEGER NOT NULL DEFAULT 0,
    mean_abs_dev      NUMERIC,              -- mean |approx_rv - exact_rv| (vol points)
    mean_signed_dev   NUMERIC,              -- mean (approx_rv - exact_rv); sign of bias
    p95_abs_dev       NUMERIC,
    corr              NUMERIC,              -- pearson(approx, exact)
    as_of             DATE,
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, horizon)
);

COMMENT ON TABLE uw_scan.vrp_rv_validation
    IS 'Item 1: approximation (trailing-21d RV read forward) vs exact ([t,t+h] adjusted-price RV) deviation per ticker/horizon.';

-- item 2: single-name harvest re-cut by sector (asset_class fixed = single_name).
CREATE TABLE IF NOT EXISTS uw_scan.vrp_harvest_by_sector (
    sector                TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    verdict               TEXT NOT NULL,
    mean_realized_vrp     NUMERIC,
    mean_holdout          NUMERIC,
    rich_cheap_spread     NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sector, deviation_class)
);

COMMENT ON TABLE uw_scan.vrp_harvest_by_sector
    IS 'Item 2: single-name VRP harvest re-bucketed by sector — WHERE is single-name vol (un)sellable?';

-- item 4: harvest at multiple horizons (decay curve).
CREATE TABLE IF NOT EXISTS uw_scan.vrp_harvest_multihorizon (
    asset_class           TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    horizon               INTEGER NOT NULL,
    verdict               TEXT NOT NULL,
    mean_realized_vrp     NUMERIC,
    mean_holdout          NUMERIC,
    rich_cheap_spread     NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, deviation_class, horizon)
);

COMMENT ON TABLE uw_scan.vrp_harvest_multihorizon
    IS 'Item 4: VRP harvest at horizons {5,20,60} — the premium decay curve.';

-- item 5a (Pass-2 redesign): does the RICH cohort OUT-RETURN the CHEAP cohort?
-- Long-short (RICH − CHEAP) forward-return DIFFERENTIAL per asset_class, with OOS
-- run on the per-date differential series itself (Bollerslev: high VRP → high
-- return; NOT cross-sectionally demeaned). Keyed (asset_class, horizon) because
-- the differential collapses deviation_class into one long-short series.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_directional_verdicts (
    asset_class           TEXT NOT NULL,
    horizon               INTEGER NOT NULL,
    verdict               TEXT NOT NULL,    -- BULLISH_TILT | BEARISH_TILT | NEUTRAL
    mean_differential     NUMERIC,          -- mean over dates of [meanRet(RICH) − meanRet(CHEAP)]
    mean_holdout          NUMERIC,          -- same on the latest-40% holdout
    mean_rich_return      NUMERIC,          -- descriptive: RICH cohort mean fwd return
    mean_cheap_return     NUMERIC,          -- descriptive: CHEAP cohort mean fwd return
    n                     INTEGER NOT NULL DEFAULT 0,   -- # of differential dates
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, horizon)
);

COMMENT ON TABLE uw_scan.vrp_directional_verdicts
    IS 'Item 5a: RICH−CHEAP forward-return long-short differential per (asset_class, horizon), OOS on the differential series (Bollerslev: high VRP → high return).';

-- item 5b: does VRP mean-revert? forward ΔVRP conditioned on the z-score.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_dvrp_reversion (
    asset_class           TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    horizon               INTEGER NOT NULL,
    verdict               TEXT NOT NULL,    -- REVERTS | PERSISTS | NEUTRAL
    mean_fwd_dvrp         NUMERIC,          -- mean (vrp(t+h) - vrp(t))
    mean_holdout          NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, deviation_class, horizon)
);

COMMENT ON TABLE uw_scan.vrp_dvrp_reversion
    IS 'Item 5b: forward ΔVRP (vrp(t+h)-vrp(t)) by bucket — does rich VRP mean-revert?';

COMMIT;
