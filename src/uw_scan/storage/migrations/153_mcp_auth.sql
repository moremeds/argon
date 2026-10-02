-- 153_mcp_auth.sql — agent-MCP bearer-token auth + per-call access log.
-- Spec: docs/superpowers/specs/2026-10-02-agent-mcp-design.md ("Auth" +
-- "Access log" rows, migration-numbers section).
--
-- mcp_token: one row per agent label ('grok', 'openai', 'local', …). The
-- plaintext token is printed once by `control-argon mcp-token create`; the
-- table stores only its sha256 hex, which is all web/mcp/server.ts needs to
-- verify an Authorization: Bearer header. revoke sets revoked_at — token rows
-- are never deleted, so mcp_access_log.token_label always resolves to a label
-- that was once minted, and a label stays reserved (rotation mints a new one).
--
-- mcp_access_log: append-only, one row per MCP tool call — caller label, tool,
-- args, ok|error, response size, duration. It is the ONLY business-table write
-- the read-only argon_mcp role gets (plus mcp_event_cursor, migration 154).
--
-- Registration with the data-gap healer REGISTRY is workstream C's (it owns
-- all four MCP tables there); the T7 unregistered-temporal-table gate fails
-- until then — expected on this branch.
--
-- Idempotent: IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.mcp_token (
    id          SERIAL PRIMARY KEY,
    label       TEXT NOT NULL UNIQUE,
    token_hash  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS uw_scan.mcp_access_log (
    id              BIGSERIAL PRIMARY KEY,
    token_label     TEXT,
    tool            TEXT,
    args            JSONB,
    status          TEXT,
    response_bytes  INTEGER,
    duration_ms     INTEGER,
    at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
