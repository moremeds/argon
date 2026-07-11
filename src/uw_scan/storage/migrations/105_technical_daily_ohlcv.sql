-- 105_technical_daily_ohlcv.sql
--
-- Carry full OHLCV onto technical_daily (previously close-only) so the
-- Technicals price pane can render candlesticks + volume and anchor VWAP.
-- Values ride the existing nightly full-recompute from apex bars — history
-- self-backfills on each ticker's next refresh; no dedicated backfill.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.technical_daily
    ADD COLUMN IF NOT EXISTS open   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS high   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS low    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS volume BIGINT;

COMMIT;
