-- 041_vcg_snapshots.sql
--
-- Volatility-Credit Gap (VCG) scanner snapshots. Append-only — every scan
-- inserts a new row. Latest-wins via ORDER BY scanned_at DESC LIMIT 1.
-- Indexable scalars are generated columns extracted from the JSONB payload
-- (mirrors the cri_snapshots / gex_snapshots pattern).
--
-- Schema: see src/uw_scan/cards/vcg_scoring.py for payload shape.
-- Source scanner: src/uw_scan/scanners/vcg.py
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vcg_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_date       DATE,
    payload         JSONB NOT NULL,

    credit_proxy    TEXT          GENERATED ALWAYS AS (payload->>'credit_proxy') STORED,
    vcg_score       NUMERIC(10,4) GENERATED ALWAYS AS (((payload->'signal')->>'vcg')::numeric) STORED,
    vcg_adj         NUMERIC(10,4) GENERATED ALWAYS AS (((payload->'signal')->>'vcg_adj')::numeric) STORED,
    interpretation  TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'interpretation') STORED,
    regime          TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'regime') STORED,
    tier            INTEGER       GENERATED ALWAYS AS (((payload->'signal')->>'tier')::int) STORED,
    ro              INTEGER       GENERATED ALWAYS AS (((payload->'signal')->>'ro')::int) STORED,
    edr             INTEGER       GENERATED ALWAYS AS (((payload->'signal')->>'edr')::int) STORED,
    bounce          INTEGER       GENERATED ALWAYS AS (((payload->'signal')->>'bounce')::int) STORED,
    vix             NUMERIC(8,2)  GENERATED ALWAYS AS (((payload->'signal')->>'vix')::numeric) STORED,
    vvix            NUMERIC(8,2)  GENERATED ALWAYS AS (((payload->'signal')->>'vvix')::numeric) STORED,
    credit_price    NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'signal')->>'credit_price')::numeric) STORED,
    vvix_severity   TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'vvix_severity') STORED
);

CREATE INDEX IF NOT EXISTS ix_vcg_scanned_at        ON uw_scan.vcg_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_vcg_data_date         ON uw_scan.vcg_snapshots (data_date DESC);
CREATE INDEX IF NOT EXISTS ix_vcg_credit_proxy_date ON uw_scan.vcg_snapshots (credit_proxy, data_date DESC);

COMMIT;
