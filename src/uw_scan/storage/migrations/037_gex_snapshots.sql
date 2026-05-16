-- 037_gex_snapshots.sql
--
-- GEX snapshots table — mirrors xenon's src/xenon/db/schema.py:577-641
-- JSONB payload + generated columns for indexable scalars.
-- Idempotent (IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.gex_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    data_date       DATE,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload         JSONB NOT NULL,
    spot            NUMERIC(12,4) GENERATED ALWAYS AS ((payload->>'spot')::numeric) STORED,
    net_gex         NUMERIC(14,2) GENERATED ALWAYS AS ((payload->>'net_gex')::numeric) STORED,
    net_dex         NUMERIC(14,2) GENERATED ALWAYS AS ((payload->>'net_dex')::numeric) STORED,
    vol_pc          NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vol_pc')::numeric) STORED,
    iv_30d          NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'iv30d')::numeric) STORED,
    iv_rank         NUMERIC(6,2)  GENERATED ALWAYS AS (((payload->'iv')->>'iv_rank')::numeric) STORED,
    hv_30d          NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'hv30')::numeric) STORED,
    mq_iv_30d       NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'mq_iv30d')::numeric) STORED,
    level_max_magnet_strike       NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'max_magnet')->>'strike')::numeric) STORED,
    level_max_magnet_gamma        NUMERIC(14,4) GENERATED ALWAYS AS (((payload->'levels'->'max_magnet')->>'gamma')::numeric) STORED,
    level_second_magnet_strike    NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'second_magnet')->>'strike')::numeric) STORED,
    level_max_accelerator_strike  NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'max_accelerator')->>'strike')::numeric) STORED,
    level_put_wall_strike         NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'put_wall')->>'strike')::numeric) STORED,
    level_call_wall_strike        NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'call_wall')->>'strike')::numeric) STORED,
    level_gex_flip_strike         NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'gex_flip')->>'strike')::numeric) STORED
);

CREATE INDEX IF NOT EXISTS ix_gex_ticker_time ON uw_scan.gex_snapshots (ticker, scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_gex_scanned_at  ON uw_scan.gex_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_gex_data_date   ON uw_scan.gex_snapshots (data_date);

COMMIT;
