-- 041_gold_cot.sql — Phase A1 (Gold).
-- CFTC Commitments of Traders weekly disaggregated report (gold futures).
-- obs_date = Tuesday position date, release_date = Friday publication date.
-- Any backtest must lag inputs to release_date + 3 trading days, never obs_date.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.cot_gold_weekly (
  obs_date          DATE        NOT NULL,
  release_date      DATE        NOT NULL,
  mm_long           NUMERIC     NULL,
  mm_short          NUMERIC     NULL,
  mm_net            NUMERIC     NULL,
  comm_long         NUMERIC     NULL,
  comm_short        NUMERIC     NULL,
  comm_net          NUMERIC     NULL,
  open_interest     NUMERIC     NULL,
  as_of             TIMESTAMPTZ NOT NULL,
  source_url        TEXT        NULL,
  PRIMARY KEY (obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_cot_gold_weekly_release
  ON uw_scan.cot_gold_weekly (release_date DESC);
