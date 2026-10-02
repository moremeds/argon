-- 154_mcp_events.sql — agent MCP event stream + per-token replay cursor.
-- Spec: docs/superpowers/specs/2026-10-02-agent-mcp-design.md ("Interface
-- contracts", "Event emission").
--
-- `mcp_event` is the append-only stream the MCP server taps two ways: the SSE
-- hook LISTENs on the `mcp_event` channel (emitters `pg_notify` the new id,
-- delivered on the emitter's commit), and `get_events` replays `id > cursor`.
-- `mcp_event_cursor` is that replay cursor, one row per bearer-token label —
-- the ONLY one of these two tables the `argon_mcp` role may write.
--
-- Ordering guarantee this schema supports: emitters take a fixed
-- pg_advisory_xact_lock before inserting, so commit order == id order and a
-- `get_events` cursor can never advance past a lower id still uncommitted.
-- The (kind, subject, basis, emitted_at DESC) index backs the cooldown probe
-- ("same triple emitted within the window?") which runs inside that lock.
--
-- Idempotent: IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.mcp_event (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,
    subject     text NOT NULL,
    basis       text NOT NULL CHECK (basis IN ('eod','live','ops')),
    payload     jsonb NOT NULL,
    emitted_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS uw_scan.mcp_event_cursor (
    token_label    text PRIMARY KEY,
    last_event_id  bigint NOT NULL DEFAULT 0,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_mcp_event_cooldown
    ON uw_scan.mcp_event (kind, subject, basis, emitted_at DESC);
