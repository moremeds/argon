"""MCP event emitter (migration 154) — notify-on-commit, cooldown, change,
retention.

`mcp_event` is the append-only stream the agent MCP server taps over SSE
(LISTEN mcp_event) and replays via `get_events`. These tests pin the guarantees
that design depends on: a NOTIFY is delivered only at the emitter's commit,
the cooldown suppresses a same-(kind, subject, basis) repeat inside its window,
`emit_on_change` fires only on a real state change, and purge removes strictly
old rows.
"""

from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest

from uw_scan.storage.mcp_events import (
    emit_event,
    emit_on_change,
    purge_old_events,
)

pytestmark = pytest.mark.integration


def _count(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.mcp_event")
        return int(cur.fetchone()[0])


def test_emit_delivers_notify_after_commit(seeded_db_empty_cards, _migrated_settings):
    """A LISTENing connection receives the new id once the emitter commits —
    and never before it."""
    repo = seeded_db_empty_cards
    with psycopg.connect(_migrated_settings.db_dsn(), autocommit=True) as listener:
        listener.execute("LISTEN mcp_event")
        new_id = emit_event(
            repo.conn,
            kind="cri_regime",
            subject="CRI",
            basis="eod",
            payload={"from": "NORMAL", "to": "ELEVATED"},
        )
        assert isinstance(new_id, int)
        # pg_notify queues inside the tx; nothing can arrive before commit.
        assert list(listener.notifies(timeout=0.2)) == []
        repo.conn.commit()
        notes = list(listener.notifies(timeout=5, stop_after=1))
        assert [(n.channel, n.payload) for n in notes] == [("mcp_event", str(new_id))]


def test_cooldown_suppresses_a_repeat_inside_the_window_and_allows_it_after(
    seeded_db_empty_cards,
):
    conn = seeded_db_empty_cards.conn
    first = emit_event(
        conn,
        kind="vcg_regime",
        subject="HYG",
        basis="live",
        payload={},
        cooldown=timedelta(hours=1),
    )
    conn.commit()
    assert first is not None

    assert (
        emit_event(
            conn,
            kind="vcg_regime",
            subject="HYG",
            basis="live",
            payload={},
            cooldown=timedelta(hours=1),
        )
        is None
    )
    # A different basis is a different triple — not suppressed.
    assert (
        emit_event(
            conn,
            kind="vcg_regime",
            subject="HYG",
            basis="eod",
            payload={},
            cooldown=timedelta(hours=1),
        )
        is not None
    )
    conn.commit()

    # Move the first row outside the window: the next same-triple emit lands.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.mcp_event "
            "SET emitted_at = now() - interval '2 hours' WHERE id = %s",
            (first,),
        )
    conn.commit()
    assert (
        emit_event(
            conn,
            kind="vcg_regime",
            subject="HYG",
            basis="live",
            payload={},
            cooldown=timedelta(hours=1),
        )
        is not None
    )
    conn.commit()
    assert _count(conn) == 3


def test_emit_on_change_fires_only_on_a_real_change(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    kw = {"kind": "cri_regime", "subject": "CRI", "basis": "eod"}
    # A first-ever row is not a change; a degraded scan must not emit a flip
    # to null; equal states do not emit.
    assert emit_on_change(conn, prev=None, new="ELEVATED", payload={}, **kw) is None
    assert emit_on_change(conn, prev="NORMAL", new=None, payload={}, **kw) is None
    assert emit_on_change(conn, prev="NORMAL", new="NORMAL", payload={}, **kw) is None
    conn.commit()
    assert _count(conn) == 0

    new_id = emit_on_change(
        conn, prev="NORMAL", new="ELEVATED", payload={"score": 42.0}, **kw
    )
    assert new_id is not None
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM uw_scan.mcp_event WHERE id = %s", (new_id,))
        payload = cur.fetchone()[0]
    assert payload == {"score": 42.0, "from": "NORMAL", "to": "ELEVATED"}
    assert _count(conn) == 1


def test_purge_removes_only_rows_older_than_the_window(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    old = emit_event(conn, kind="ops", subject="daily", basis="ops", payload={})
    fresh = emit_event(conn, kind="ops", subject="daily", basis="ops", payload={})
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.mcp_event "
            "SET emitted_at = now() - interval '31 days' WHERE id = %s",
            (old,),
        )
    conn.commit()

    assert purge_old_events(conn) == 1
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM uw_scan.mcp_event ORDER BY id")
        assert [r[0] for r in cur.fetchall()] == [fresh]
