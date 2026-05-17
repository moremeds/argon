-- 044_gold_posture_extensions.sql — Phase A1 (Gold).
-- Adds the columns the API models already reference but the original 043 migration
-- did not persist: LBMA momentum, UW skew, DXY/GPR mappings, and 52w percentile
-- derivations. Idempotent (ADD COLUMN IF NOT EXISTS).

SET search_path TO uw_scan, public;

ALTER TABLE uw_scan.gold_posture_daily
  ADD COLUMN IF NOT EXISTS lbma_30d_momentum_t NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS uw_25d_skew_sigma   NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS fx_basket_dxy_z     NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS xau_cny_premium_pct NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS cb_52w_pct          NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS cot_mm_4w_change_sigma NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS t5yifr_pct_52w      NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS dxy                 NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS dxy_60d_sigma       NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS gpr_value           NUMERIC NULL,
  ADD COLUMN IF NOT EXISTS gpr_pct_52w         NUMERIC NULL;
