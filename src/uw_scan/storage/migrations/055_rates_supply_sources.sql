-- 055_rates_supply_sources.sql — Treasury auction and FiscalData supply sources.
-- Idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.rates_treasury_auctions (
  cusip               TEXT        NOT NULL,
  security_type       TEXT        NOT NULL,
  security_term       TEXT        NOT NULL,
  auction_date        DATE        NOT NULL,
  issue_date          DATE        NULL,
  offering_amount     NUMERIC     NULL,
  high_rate           NUMERIC     NULL,
  bid_to_cover        NUMERIC     NULL,
  direct_bidder_pct   NUMERIC     NULL,
  indirect_bidder_pct NUMERIC     NULL,
  primary_dealer_pct  NUMERIC     NULL,
  tail_indicator      TEXT        NULL,
  as_of               TIMESTAMPTZ NOT NULL,
  source_url          TEXT        NULL,
  PRIMARY KEY (cusip, auction_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_rates_treasury_auctions_latest
  ON uw_scan.rates_treasury_auctions (auction_date DESC, cusip, as_of DESC);

CREATE TABLE IF NOT EXISTS uw_scan.rates_fiscal_debt_daily (
  record_date       DATE        NOT NULL,
  debt_held_public  NUMERIC     NULL,
  intragov_holdings NUMERIC     NULL,
  total_public_debt NUMERIC     NULL,
  as_of             TIMESTAMPTZ NOT NULL,
  source_url        TEXT        NULL,
  PRIMARY KEY (record_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_rates_fiscal_debt_daily_latest
  ON uw_scan.rates_fiscal_debt_daily (record_date DESC, as_of DESC);
