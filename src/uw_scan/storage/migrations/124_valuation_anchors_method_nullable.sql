-- 124_valuation_anchors_method_nullable.sql — `method` may be NULL. Idempotent.
--
-- WHY
-- ---
-- Migration 118 declared `method TEXT NOT NULL` because every band and every
-- refusal up to now was taken UNDER a method: a missing FX series, a numerator
-- that went negative, a window too short. The method was known; the data failed
-- it.
--
-- `financials` introduces the state that column cannot express — a refusal
-- because NO method applies. Every yield here is denominated in enterprise
-- value, and for a deposit-funded balance sheet enterprise value is not a
-- meaningful denominator, so there is no method to name. See `FINANCIALS` in
-- `uw_scan.fundamentals.valuation`.
--
-- The alternative was a sentinel string ('none', 'refused'), which would have
-- travelled into `METHOD_LABEL` lookups and the card header as a value that
-- reads like a method. NULL is the honest shape: this row was refused, and not
-- on a method.
--
-- Widening a NOT NULL to NULL cannot invalidate an existing row, so there is no
-- backfill: every row written before this migration carries a real method and
-- keeps it.

ALTER TABLE uw_scan.valuation_anchors ALTER COLUMN method DROP NOT NULL;

COMMENT ON COLUMN uw_scan.valuation_anchors.method IS
  'The valuation yield this row was built from. NULL only when the refusal is '
  'that no method applies to the company type at all (see migration 124).';
