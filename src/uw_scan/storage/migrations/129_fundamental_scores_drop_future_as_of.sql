-- 129_fundamental_scores_drop_future_as_of.sql — evict score rows dated in the future.
--
-- `as_of` is the MAX knowledge date across a cross-section, and until the fix in
-- `_build_buckets` a name whose filing date was unknown carried an ESTIMATE of
-- `period_end + 45d`. For a fresh quarter that estimate is a future date, and one
-- such name stamped every row in its bucket with it.
--
-- The damage is on the read path, not the write path: `latest_for_ticker` orders
-- `as_of DESC`, so a future-dated bucket outranks every later run and the card keeps
-- serving one stale compute until the calendar reaches that date. On prod 2026-08-23
-- this was 371 rows across 363 tickers stamped `2026-09-14` (from AMAT and CSCO),
-- shadowing six days of fresher scores.
--
-- Score rows are fully derived — `fundamental_scoring` rebuilds every bucket from the
-- statement panel on each run — so deleting them loses nothing recomputable. No
-- guard is needed for idempotency: once the rows are gone the predicate matches
-- nothing, and if a future-dated row ever reappears, deleting it again is the
-- correct action rather than a destructive one.

SET search_path TO uw_scan, public;

DELETE FROM uw_scan.fundamental_scores WHERE as_of > CURRENT_DATE;
