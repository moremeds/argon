-- 039_gold_exchange_inventory.sql — Phase A1 (Gold).
-- COMEX daily registered/eligible ounces; LBMA monthly vault total (row keyed by month-end date).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.exchange_inventory_daily (
  exchange       TEXT        NOT NULL,
  obs_date       DATE        NOT NULL,
  registered_oz  NUMERIC     NULL,
  eligible_oz    NUMERIC     NULL,
  vault_oz       NUMERIC     NULL,
  as_of          TIMESTAMPTZ NOT NULL,
  source_url     TEXT        NULL,
  PRIMARY KEY (exchange, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_exchange_inventory_daily_lookup
  ON uw_scan.exchange_inventory_daily (exchange, obs_date DESC, as_of DESC);
