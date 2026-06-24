-- 085_vrp_macro_entry.sql
-- Forward entry-capture: the SPX bull-put-spread the macro signal would place,
-- tracked to expiry. One "auto" cohort/day + on-demand "button" cohorts.
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_entry (
    entry_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             TEXT        NOT NULL DEFAULT 'SPX',
    birth_date       DATE        NOT NULL,
    born_at          TIMESTAMPTZ NOT NULL,
    origin           TEXT        NOT NULL,          -- 'auto' | 'button'
    expiry           DATE        NOT NULL,
    hold_days        INTEGER     NOT NULL,
    spot_at_birth    NUMERIC,
    iv_at_birth      NUMERIC,
    vrp_z_at_birth   NUMERIC,
    weight_at_birth  NUMERIC,
    action_at_birth  TEXT,                          -- TRADE/SKIP (recorded anyway)
    short_delta      NUMERIC     NOT NULL,          -- target 0.25
    wing_delta       NUMERIC     NOT NULL,          -- target 0.125
    short_strike_above NUMERIC   NOT NULL,
    short_strike_below NUMERIC   NOT NULL,
    wing_strike_above  NUMERIC   NOT NULL,
    wing_strike_below  NUMERIC   NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Auto cohorts: one per (name, birth_date) — a restart double-fire reuses the row.
-- Button cohorts are NOT constrained here: each click is its own point-in-time
-- capture (never silently mapped onto an earlier click's stale strikes) AND
-- one-shot — fetch_open_vrp_macro_entries returns origin='auto' only, so a button
-- click is captured once and never re-snapshotted. This bounds the 8x/day load to
-- the auto stride set (the auto cohort already tracks the same structure to expiry).
CREATE UNIQUE INDEX IF NOT EXISTS vrp_macro_entry_auto_uniq
    ON uw_scan.vrp_macro_entry (name, birth_date) WHERE origin = 'auto';
CREATE INDEX IF NOT EXISTS vrp_macro_entry_open_idx
    ON uw_scan.vrp_macro_entry (name, expiry);

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_entry_quote (
    entry_id      BIGINT      NOT NULL REFERENCES uw_scan.vrp_macro_entry(entry_id) ON DELETE CASCADE,
    as_of         TIMESTAMPTZ NOT NULL,
    session       TEXT        NOT NULL,             -- 'rth' | 'eod' | 'postclose'
    leg           TEXT        NOT NULL,             -- 'short_above'|'short_below'|'wing_above'|'wing_below'
    strike        NUMERIC     NOT NULL,
    opt_right     CHAR(1)     NOT NULL DEFAULT 'P',
    nbbo_bid      NUMERIC,
    nbbo_ask      NUMERIC,
    iv            NUMERIC,
    delta         NUMERIC,
    gamma         NUMERIC,
    vega          NUMERIC,
    theta         NUMERIC,
    und_spot      NUMERIC,
    source        TEXT        NOT NULL,             -- 'xenon_ib' | 'uw'
    greeks_source TEXT        NOT NULL,             -- 'bs' | 'none'  (bs=BS from marked IV; none=IV absent->0 greeks)
    source_asof   TIMESTAMPTZ,                      -- provider's own ts (UW delay)
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (entry_id, as_of, leg)
);
CREATE INDEX IF NOT EXISTS vrp_macro_entry_quote_entry_idx
    ON uw_scan.vrp_macro_entry_quote (entry_id, as_of DESC);

COMMIT;
