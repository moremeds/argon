-- 079_vrp_harvest_verdicts.sql
-- VRP harvest markout verdict store (Spec B: 2026-06-19-vrp-harvest-markout-design).
-- One row per (asset_class, deviation_class) bucket; idempotent; never wiped.
-- Numbered 079 to leapfrog the in-flight option-surface PR's 077/078 on a
-- sibling branch (avoids a same-number filename on main). Gaps are harmless:
-- migrations apply by lexical order with no tracking table.
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_harvest_verdicts (
    asset_class           TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    verdict               TEXT NOT NULL,
    mean_realized_vrp     NUMERIC,
    mean_holdout          NUMERIC,
    rich_cheap_spread     NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, deviation_class)
);

COMMENT ON TABLE uw_scan.vrp_harvest_verdicts
    IS 'Per-bucket VRP harvest markout conclusions (Spec B). verdict HARVEST_SELLABLE only when mean realized VRP clears threshold AND survives walk-forward AND the per-quarter catastrophic gate.';

COMMIT;
