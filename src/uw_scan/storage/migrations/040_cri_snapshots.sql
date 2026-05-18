-- 040_cri_snapshots.sql
--
-- Crash Risk Indicator (CRI) scanner snapshots. Append-only — every scan
-- inserts a new row. Latest-wins via ORDER BY scanned_at DESC LIMIT 1.
-- Indexable scalars are generated columns extracted from the JSONB payload
-- (mirrors the gex_snapshots pattern).
--
-- Schema: docs/superpowers/research/regime/ (TBD)
-- Source scanner: src/uw_scan/scanners/cri.py
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.cri_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_date       DATE,
    payload         JSONB NOT NULL,
    cri_score       NUMERIC(6,2) GENERATED ALWAYS AS (((payload->'cri')->>'score')::numeric) STORED,
    cri_level       TEXT         GENERATED ALWAYS AS ((payload->'cri')->>'level') STORED,
    trigger_fired   BOOLEAN      GENERATED ALWAYS AS (((payload->'crash_trigger')->>'fired')::boolean) STORED,
    vix             NUMERIC(8,2) GENERATED ALWAYS AS ((payload->>'vix')::numeric) STORED,
    vvix            NUMERIC(8,2) GENERATED ALWAYS AS ((payload->>'vvix')::numeric) STORED,
    cor1m           NUMERIC(8,2) GENERATED ALWAYS AS ((payload->>'cor1m')::numeric) STORED,
    spx_distance_pct NUMERIC(8,4) GENERATED ALWAYS AS ((payload->>'spx_distance_pct')::numeric) STORED,
    realized_vol    NUMERIC(8,2) GENERATED ALWAYS AS ((payload->>'realized_vol')::numeric) STORED
);

CREATE INDEX IF NOT EXISTS ix_cri_scanned_at ON uw_scan.cri_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_cri_data_date  ON uw_scan.cri_snapshots (data_date DESC);

COMMIT;
