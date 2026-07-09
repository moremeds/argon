-- 103_vrp_macro_entry_grid_strike_ivs.sql
-- Skew-aware entry-capture leg selection: cache each listed strike's own IV
-- alongside the strike grid, so resolve_entry_contracts can bracket the Δ0.25 /
-- Δ0.125 targets by *real* per-strike delta instead of a flat-vol strike (which
-- SPX put skew makes systematically too shallow — the recorded legs came out at
-- Δ~0.28 / ~0.17 instead of 0.25 / 0.125). Nullable: a legacy row (or a cold
-- cache) with no IV map falls back to the flat-vol path.
SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.vrp_macro_entry_grid
    ADD COLUMN IF NOT EXISTS strike_ivs JSONB;  -- {"<strike>": <iv>} or NULL

COMMENT ON COLUMN uw_scan.vrp_macro_entry_grid.strike_ivs IS
    'Per-strike implied vol {strike: iv} from the nightly UW chain; drives '
    'skew-aware delta bracketing. NULL ⇒ flat-vol fallback.';

COMMIT;
