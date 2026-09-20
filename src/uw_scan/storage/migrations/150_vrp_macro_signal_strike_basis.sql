-- 150_vrp_macro_signal_strike_basis.sql
-- Strike provenance for the VRP macro short-vol signal snapshot.
--
-- The card's strikes used to come from inverting ONE flat ATM vol (VIX), which
-- ignores SPX put skew: the "0.125 delta" wing actually carried ~0.163 delta on
-- 2026-09-18. The signal now prefers the nightly vrp_macro_entry_grid (real
-- listed strikes + each strike's own IV), so these columns record which basis
-- produced the row and, when it is the real chain, the deltas the chosen
-- strikes ACTUALLY carry.
--
-- strike_basis: 'listed_skew' (grid) | 'flat_vol_model' (no grid for the name).
-- short_put_delta/long_put_delta/strike_grid_date/expiry are NULL on the
-- flat-vol path -- that NULL is the statement "these are modeled strikes",
-- never a fabricated delta.

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.vrp_macro_signal_daily
  ADD COLUMN IF NOT EXISTS short_put_delta  NUMERIC,
  ADD COLUMN IF NOT EXISTS long_put_delta   NUMERIC,
  ADD COLUMN IF NOT EXISTS strike_basis     TEXT,
  ADD COLUMN IF NOT EXISTS strike_grid_date DATE,
  ADD COLUMN IF NOT EXISTS expiry           DATE;

COMMENT ON COLUMN uw_scan.vrp_macro_signal_daily.strike_basis
  IS 'How the strikes were resolved: listed_skew (vrp_macro_entry_grid listed strikes, per-leg IV) or flat_vol_model (flat ATM vol inversion; wing sits too shallow under put skew).';
