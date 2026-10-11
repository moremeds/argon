-- 162_gold_factor_daily.sql — gold factor model, one row per grid date.
--
-- How much of gold's daily move the 10Y real yield, the dollar (synthetic ICE
-- index) and the safe-haven spread explain: a 252-row rolling OLS with
-- coefficients lagged 2 rows, the 63-row explained share, its label, and each
-- day's move split into parts. Historical description only; the study's
-- direction test failed, so nothing here is a forecast.
-- Engine: src/uw_scan/macro/gold_factor.py (a port of the signal-lab study,
-- parity in docs/research/2026-10-10-gold-factor-parity.json).
--
-- Units: *_part, gold_change, unexplained_* and own_trailing_drift are percent
-- (100 x log change); b_r is % per bp of DFII10; b_d, b_s are % per %.
-- gold_change = own_trailing_drift + real_yield_part + dollar_part
--             + haven_part + unexplained_1 (per row, exactly).
--
-- Writer: worker/jobs/gold_factor.py (nightly, massive-0) recomputes the whole
-- history from macro_series_daily and upserts every row, so a revised input
-- converges on the next run.
--
-- Idempotent: IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.gold_factor_daily (
    obs_date             DATE PRIMARY KEY,
    a                    DOUBLE PRECISION,
    b_r                  DOUBLE PRECISION,
    b_r_lo95             DOUBLE PRECISION,
    b_r_hi95             DOUBLE PRECISION,
    b_d                  DOUBLE PRECISION,
    b_d_lo95             DOUBLE PRECISION,
    b_d_hi95             DOUBLE PRECISION,
    b_s                  DOUBLE PRECISION,
    b_s_lo95             DOUBLE PRECISION,
    b_s_hi95             DOUBLE PRECISION,
    explained_share      DOUBLE PRECISION,
    raw_label            TEXT CHECK (raw_label IN ('much','part','little')),
    published_label      TEXT CHECK (published_label IN ('much','part','little')),
    gold_change          DOUBLE PRECISION NOT NULL,
    own_trailing_drift   DOUBLE PRECISION,
    real_yield_part      DOUBLE PRECISION,
    dollar_part          DOUBLE PRECISION,
    haven_part           DOUBLE PRECISION,
    unexplained_1        DOUBLE PRECISION,
    unexplained_5        DOUBLE PRECISION,
    unexplained_21       DOUBLE PRECISION,
    real_yield_change_bp DOUBLE PRECISION NOT NULL,
    dollar_change_pct    DOUBLE PRECISION NOT NULL,
    haven_change_pct     DOUBLE PRECISION NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL
);
