"""mcp_token / mcp_access_log (migration 153) + control-argon mcp-token round-trip."""

from __future__ import annotations

import pytest

from uw_scan.control_argon_mcp import (
    create_token,
    hash_token,
    list_tokens,
    revoke_token,
)

pytestmark = pytest.mark.integration


def test_create_revoke_list_round_trip(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn

    token = create_token(conn, "grok")
    assert token  # urlsafe(32) → 43 chars, printed once by the CLI
    rows = list_tokens(conn)
    assert [r[0] for r in rows] == ["grok"]
    assert rows[0][2] is None  # active

    # The table stores the hash, never the plaintext.
    with conn.cursor() as cur:
        cur.execute("SELECT token_hash FROM uw_scan.mcp_token WHERE label = 'grok'")
        stored = cur.fetchone()[0]
    assert stored == hash_token(token) and token not in stored

    assert revoke_token(conn, "grok") == "revoked"
    assert revoke_token(conn, "grok") == "already_revoked"  # idempotent
    assert list_tokens(conn)[0][2] is not None


def test_duplicate_label_is_refused_even_after_revoke(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    create_token(conn, "openai")
    with pytest.raises(ValueError, match="already exists"):
        create_token(conn, "openai")
    revoke_token(conn, "openai")
    with pytest.raises(ValueError, match="already exists"):
        create_token(conn, "openai")  # a revoked label stays reserved


def test_revoking_an_unknown_label_raises(seeded_db_empty_cards):
    with pytest.raises(ValueError, match="no token"):
        revoke_token(seeded_db_empty_cards.conn, "nobody")


def test_access_log_accepts_a_tool_call_row(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    create_token(conn, "local")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.mcp_access_log "
            "(token_label, tool, args, status, response_bytes, duration_ms) "
            "VALUES ('local', 'read', '{\"path\": \"/health\"}'::jsonb, 'ok', 512, 7)"
        )
        conn.commit()
        cur.execute(
            "SELECT token_label, tool, status, response_bytes "
            "FROM uw_scan.mcp_access_log"
        )
        assert cur.fetchall() == [("local", "read", "ok", 512)]
