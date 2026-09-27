-- 152_sector_rs_daily.sql — sector relative strength + breadth, one row per
-- (as_of, group_kind, group_key).
-- Spec: docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md §3.
--
-- Two group kinds share the table and are never joined:
--   gics  — the 11 SPDR sector ETFs. RS = the ETF's adjusted close return minus
--           SPY's; breadth over CURRENT S&P 500 members (applied to every
--           session: survivorship-biased, spec §4) mapped through
--           company_sector (vendor vocabulary).
--   chain — every watchlist_chain chain, equal-weighted member return minus SPY.
-- The vendor `Energy` (oil and gas) and argon's chain `Energy` (power infra)
-- are different groups for exactly that reason — see migration 123's header.
--
-- Units: rs_* are percentage points (group return − SPY return, not a ratio);
-- breadth_* are fractions in [0, 1] (members beating SPY / members priced for
-- that window). n_priced is the 12m count only. A `degraded` row is still
-- written — it is the coverage statement (n_priced < 0.8 × n_members, no
-- members, or the 12m RS input missing).
--
-- Writers: worker/jobs/sector_rs_daily.py (nightly 21:30 ET Mon–Fri,
-- massive-0, flag UW_SCAN_SECTOR_RS_ENABLED) and
-- scripts/backfill/sector_rs_backfill.py, both through
-- storage/sector_rs.SectorRsRepository.upsert_rows (ON CONFLICT DO UPDATE on
-- every column, so re-runs and backfills converge on the same row).
--
-- Idempotent: IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.sector_rs_daily (
    as_of          DATE NOT NULL,
    group_kind     TEXT NOT NULL CHECK (group_kind IN ('gics','chain')),
    group_key      TEXT NOT NULL,          -- 'Technology' | 'Semi-Logic' ...
    weighting      TEXT NOT NULL CHECK (weighting IN ('etf','equal')),
    rs_symbol      TEXT,                   -- 'XLK' for etf rows, NULL for equal
    n_members      INTEGER NOT NULL,       -- constituents in the group at as_of
    n_classified   INTEGER NOT NULL,       -- == n_members for both kinds today (a member with a NULL sector belongs to no group; the index-level unclassified count is a job counter, acceptance §9.3). Kept so a future multi-source label can report partial coverage per row
    n_priced       INTEGER NOT NULL,       -- members with a full 252-bar window
    rs_1m  DOUBLE PRECISION, rs_3m  DOUBLE PRECISION, rs_6m  DOUBLE PRECISION, rs_12m DOUBLE PRECISION,
    breadth_1m DOUBLE PRECISION, breadth_3m DOUBLE PRECISION, breadth_6m DOUBLE PRECISION, breadth_12m DOUBLE PRECISION,
    degraded       BOOLEAN NOT NULL DEFAULT FALSE,  -- n_priced < 0.8 * n_members, or an RS input missing
    source         TEXT NOT NULL,          -- 'apex' | 'daily_ohlc'
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, group_kind, group_key)
);
