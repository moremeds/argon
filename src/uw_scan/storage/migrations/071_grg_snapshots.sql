-- 071_grg_snapshots.sql
--
-- Gamma Rotation Gap (GRG) scanner snapshots. Append-only — every scan
-- inserts a new row. Latest-wins via ORDER BY scanned_at DESC LIMIT 1.
-- Each row's JSONB payload is SELF-CONTAINED: it embeds the full 90-session
-- history array (recomputed from the UW greek-exposure series each scan),
-- so the API serves one row per request — no multi-row history assembly.
-- Indexable scalars are generated columns over the payload (cri/vcg pattern).
-- `basis` mirrors 070: 'eod' is the only writer today (no WS-spliced live
-- path — dealer gamma isn't in the WS feed), but the column keeps the
-- regime-snapshot contract uniform.
-- Source scanner: src/uw_scan/scanners/grg.py
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.grg_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_date       DATE,
    payload         JSONB NOT NULL,
    basis           TEXT NOT NULL DEFAULT 'eod',

    grg_z           NUMERIC(10,4) GENERATED ALWAYS AS (((payload->'signal')->>'grg_z')::numeric) STORED,
    interpretation  TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'interpretation') STORED,
    pair_state      TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'state') STORED,
    tier            INTEGER       GENERATED ALWAYS AS (((payload->'signal')->>'tier')::int) STORED,
    spy_net_gamma   NUMERIC(18,4) GENERATED ALWAYS AS (((payload->'assets'->'SPY')->>'net_gamma')::numeric) STORED,
    tlt_net_gamma   NUMERIC(18,4) GENERATED ALWAYS AS (((payload->'assets'->'TLT')->>'net_gamma')::numeric) STORED
);

CREATE INDEX IF NOT EXISTS ix_grg_scanned_at       ON uw_scan.grg_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_grg_data_date        ON uw_scan.grg_snapshots (data_date DESC);
CREATE INDEX IF NOT EXISTS ix_grg_basis_scanned_at ON uw_scan.grg_snapshots (basis, scanned_at DESC);

COMMIT;
