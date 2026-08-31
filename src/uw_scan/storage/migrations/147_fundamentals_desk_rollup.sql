-- 147_fundamentals_desk_rollup.sql
-- Nightly per-name desk rollup (spec 2026-08-26-fundamentals-industry-desk
-- §3c, Task 12): revenue YoY and gross-margin trajectory, persisted so the
-- chain x metric matrix reads it at request time with zero recompute.
--
-- One row per (ticker, period_end), derived from the newest-accepted-version
-- statement panel (`current_statement_panel`) via the SAME `build_features`
-- math the fundamental card uses -- never a private re-derivation. A metric
-- whose raw input field was flagged by an integrity check on that period's
-- own observations is NULL here, never a wrong number and never carried
-- forward from a prior period -- see worker/jobs/fundamentals_desk_rollup.py.
--
-- Overwrites on conflict, unlike earnings_reactions' insert-or-skip: a
-- restatement (new obs_id, same identity) or a violation newly recorded/
-- cleared by `recheck_violations` can change what a period's metric should
-- read, so this is not an immutable fact table -- matches implied_move_daily's
-- upsert-overwrite shape.
--
-- `knowledge_date_known` says whether `knowledge_date` is a real filing date
-- or the `period_end + FALLBACK_LAG_DAYS` estimate. The estimate errs EARLY
-- for late filers, which manufactures look-ahead -- measured cost is composite
-- IC 0.059 with the fallback against 0.039 without -- and it is stored in the
-- same column, in the same shape, as a real filing date. Without this flag the
-- two are indistinguishable and the distinction is destroyed at write time, so
-- no later reader can recover it. NOT NULL and no DEFAULT on purpose: every
-- writer must state which one it produced. See
-- worker/jobs/fundamental_scoring.py::_knowledge_date.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.fundamentals_desk_rollup (
  ticker               TEXT NOT NULL,
  period_end           DATE NOT NULL,
  rev_yoy              NUMERIC,
  gross_margin         NUMERIC,
  gross_profit         NUMERIC,
  knowledge_date       DATE NOT NULL,
  knowledge_date_known BOOLEAN NOT NULL,
  computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, period_end)
);

-- Serves `latest_per_ticker` (matrix cell: newest period per name) and
-- `trajectory` (per-name history, newest-first).
CREATE INDEX IF NOT EXISTS idx_fundamentals_desk_rollup_ticker
  ON uw_scan.fundamentals_desk_rollup (ticker, period_end DESC);

COMMENT ON TABLE uw_scan.fundamentals_desk_rollup
  IS 'Nightly per-name rollup of revenue YoY and gross-margin trajectory from the UW statement store, one row per (ticker, period_end), computed by worker/jobs/fundamentals_desk_rollup.py via fundamentals.features.build_features over storage/fundamental_observation_panels.current_statement_panel. A metric whose input field was flagged by an integrity check is NULL, never wrong and never carried forward. knowledge_date_known=false means knowledge_date is the period_end + FALLBACK_LAG_DAYS estimate, which errs early for late filers and manufactures look-ahead -- a leak-free consumer must filter those rows out.';
