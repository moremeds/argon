-- 083_vrp_macro_signal_daily.sql
-- VRP macro short-vol signal daily snapshot (Layer-3 deploy of reports/vrp_macro_signal.py).
-- One row per (name, snapshot_date): the weekly bull-put-spread readout (TRADE/SKIP +
-- modeled strikes/credit/max-loss) plus the full-history backtest headline as of that run.
-- Persisting the trace is mandatory (CLAUDE.md: never leave research/backtest output in
-- memory-only). Idempotent; never wiped — a daily snapshot accumulates a track record.
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_signal_daily (
    name            TEXT NOT NULL,        -- SPX | QQQ | IWM
    snapshot_date   DATE NOT NULL,        -- compute date (ET) the job ran for
    as_of           DATE NOT NULL,        -- vol-data date the signal is based on (reveals staleness vs snapshot_date)
    spot            NUMERIC NOT NULL,
    iv              NUMERIC NOT NULL,
    rv20            NUMERIC,
    vrp             NUMERIC,
    vrp_z           NUMERIC,
    weight          NUMERIC NOT NULL,     -- ramp+ size multiplier in [0,1]
    action          TEXT NOT NULL,        -- TRADE | SKIP
    short_put       NUMERIC,              -- NULL on SKIP
    long_put        NUMERIC,
    put_width       NUMERIC,
    credit          NUMERIC,              -- flat-vol modeled floor; real put skew pays more
    max_loss        NUMERIC,
    hold_days       INTEGER NOT NULL,
    short_delta     NUMERIC NOT NULL,
    wing_delta      NUMERIC NOT NULL,
    bt_n            INTEGER,              -- backtest_laddered headline as of this run
    bt_sharpe       NUMERIC,             -- NULL when non-finite (nan/inf)
    bt_maxdd        NUMERIC,
    bt_annror       NUMERIC,
    bt_calmar       NUMERIC,
    config_jsonb    JSONB,               -- MacroSignalConfig used (provenance)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (name, snapshot_date)
);

COMMENT ON TABLE uw_scan.vrp_macro_signal_daily
    IS 'Daily VRP macro short-vol signal snapshot (Layer-3 of reports/vrp_macro_signal.py). action=TRADE iff weight>0 (ramp+ vrp-z sizing); strikes/credit/max_loss are flat-vol modeled. Latest row per name = current signal; compare snapshot_date vs as_of for staleness.';

COMMIT;
