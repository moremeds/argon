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

-- A methodless row must carry NO levels.
--
-- Dropping NOT NULL opens a state nothing else rejects: a row with `method`
-- NULL and a real `buy_below`. Sibling of `valuation_anchors_band_ascends` in
-- 118, and for the same reason — that constraint exists because an out-of-order
-- band is not a bad number but an inverted recommendation, and this one exists
-- because a methodless priced row is not a bad number either. It is a price
-- level with no stated basis: the card header has nothing to print after the
-- company type, and `GET /api/scanner/value` selects on `buy_below IS NOT NULL`
-- and hands the row to a model whose `method` is non-nullable, so the response
-- fails validation and the endpoint 500s for EVERY name in the list, not just
-- the malformed one.
--
-- In the schema rather than in `build_anchors` because the builder is one
-- writer among the backfills and repairs that will follow, and the invariant is
-- a property of the table. `_no_anchor` already returns `anchors: None`, so
-- every refusal ever written satisfies this; it cannot fail on existing data,
-- where `method` was NOT NULL until the statement above.
--
-- DO block because Postgres has no ADD CONSTRAINT IF NOT EXISTS.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'valuation_anchors_methodless_is_refusal'
      AND conrelid = 'uw_scan.valuation_anchors'::regclass
  ) THEN
    ALTER TABLE uw_scan.valuation_anchors
      ADD CONSTRAINT valuation_anchors_methodless_is_refusal
      CHECK (
          method IS NOT NULL
          OR (buy_below    IS NULL
          AND observe_low  IS NULL
          AND observe_mid  IS NULL
          AND observe_high IS NULL
          AND risk_above   IS NULL)
      );
  END IF;
END $$;
