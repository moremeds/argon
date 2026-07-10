-- 106_technical_vwap_anchor.sql
--
-- User-set anchored-VWAP state for the Technicals price pane: one anchor per
-- ticker plus the computed [{as_of, vwap}] snapshot (durable record; reads
-- recompute from technical_daily OHLCV when available and fall back to the
-- snapshot). Written only on user click — no scheduled writer. Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.technical_vwap_anchor (
    ticker        TEXT PRIMARY KEY,
    anchor_date   DATE NOT NULL,
    vwap_snapshot JSONB NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
