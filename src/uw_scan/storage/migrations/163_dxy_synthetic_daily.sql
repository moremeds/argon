-- 163_dxy_synthetic_daily.sql — synthetic ICE dollar index, one row per date.
--
-- 50.14348112 x EURUSD^-0.576 x USDJPY^0.136 x GBPUSD^-0.119 x USDCAD^0.091
-- x USDSEK^0.042 x USDCHF^0.036, from the IB 1-day MIDPOINT closes of the six pairs.
-- change_pct is 100 x log change from the previous date with all six pairs; each
-- <pair>_part is exponent x 100 x log change of that pair, so the six parts sum to
-- change_pct exactly. Rows exist on every date with all six pairs (not gated on
-- DFII10 like gold_factor_daily). Stored as a result: the raw pair closes are inputs.
--
-- Writer: worker/jobs/gold_factor.py (nightly, massive-0) recomputes every date and
-- upserts it. Engine: macro/gold_factor.py::dxy_daily.
--
-- Idempotent: IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.dxy_synthetic_daily (
    obs_date     DATE PRIMARY KEY,
    dxy          DOUBLE PRECISION NOT NULL,
    change_pct   DOUBLE PRECISION,
    eurusd_part  DOUBLE PRECISION,
    usdjpy_part  DOUBLE PRECISION,
    gbpusd_part  DOUBLE PRECISION,
    usdcad_part  DOUBLE PRECISION,
    usdsek_part  DOUBLE PRECISION,
    usdchf_part  DOUBLE PRECISION,
    computed_at  TIMESTAMPTZ NOT NULL
);
