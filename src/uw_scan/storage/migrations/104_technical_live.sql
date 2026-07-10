-- Latest-only live-technicals cache (one row per ticker, upsert). Not a
-- (ticker, as_of) temporal table -> no data-gap registry entry needed.
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS technical_live (
    ticker       text PRIMARY KEY,
    captured_at  timestamptz NOT NULL,
    spot         double precision,
    spot_source  text,
    payload      jsonb NOT NULL,
    inserted_at  timestamptz NOT NULL DEFAULT now()
);
