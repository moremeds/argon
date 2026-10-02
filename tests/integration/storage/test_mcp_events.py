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
    last_emitted_state,
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
    assert (
        emit_on_change(conn, snapshot_prev=None, new="ELEVATED", payload={}, **kw) == []
    )
    assert (
        emit_on_change(conn, snapshot_prev="NORMAL", new=None, payload={}, **kw) == []
    )
    assert (
        emit_on_change(conn, snapshot_prev="NORMAL", new="NORMAL", payload={}, **kw)
        == []
    )
    conn.commit()
    assert _count(conn) == 0

    ids = emit_on_change(
        conn, snapshot_prev="NORMAL", new="ELEVATED", payload={"score": 42.0}, **kw
    )
    conn.commit()
    assert len(ids) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM uw_scan.mcp_event WHERE id = %s", (ids[0],))
        payload = cur.fetchone()[0]
    assert payload == {"score": 42.0, "from": "NORMAL", "to": "ELEVATED"}
    assert _count(conn) == 1


def test_emit_on_change_recovers_a_missed_transition(seeded_db_empty_cards):
    """An emit that died after its snapshot committed leaves the persisted
    state (B) ahead of the stream (A): the dead scan's snapshot row carries a
    write time LATER than the anchor event's emitted_at — the timestamp guard
    that tells a missed transition apart from a stale racer. The next call
    sees snapshot_prev=B written after anchor=A and announces the missed
    A→B step first (``recovered: true``), then the current B→C — the stream
    stays continuous for subscribers."""
    conn = seeded_db_empty_cards.conn
    kw = {"kind": "cri_regime", "subject": "CRI", "basis": "eod"}
    emit_event(conn, payload={"from": "NORMAL", "to": "A"}, **kw)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT emitted_at FROM uw_scan.mcp_event ORDER BY id DESC LIMIT 1")
        anchor_emitted_at = cur.fetchone()[0]
    conn.commit()
    # The dead emit's snapshot row was written after the anchor event.
    snapshot_prev_at = anchor_emitted_at + timedelta(seconds=1)

    ids = emit_on_change(
        conn,
        snapshot_prev="B",
        snapshot_prev_at=snapshot_prev_at,
        new="C",
        payload={},
        **kw,
    )
    conn.commit()
    assert len(ids) == 2
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM uw_scan.mcp_event WHERE id = ANY(%s) ORDER BY id",
            (ids,),
        )
        payloads = [r[0] for r in cur.fetchall()]
    assert payloads == [
        {"from": "A", "to": "B", "recovered": True},
        {"from": "B", "to": "C"},
    ]


def test_emit_on_change_without_snapshot_write_time_skips_recovery(
    seeded_db_empty_cards,
):
    """``snapshot_prev_at=None`` (a caller that can't date its prev read) can
    never prove the snapshot outran the stream — no recovered step — but the
    normal anchor-compare still emits the real change."""
    conn = seeded_db_empty_cards.conn
    kw = {"kind": "cri_regime", "subject": "CRI", "basis": "eod"}
    emit_event(conn, payload={"from": "NORMAL", "to": "A"}, **kw)
    conn.commit()
    ids = emit_on_change(conn, snapshot_prev="B", new="C", payload={}, **kw)
    conn.commit()
    assert len(ids) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM uw_scan.mcp_event WHERE id = %s", (ids[0],))
        assert cur.fetchone()[0] == {"from": "A", "to": "C"}


def test_emit_on_change_serializes_racing_callers(seeded_db_empty_cards):
    """Two callers holding the same stale snapshot_prev — the racing manual
    scan + cron shape — must not both fire the flip, on the EOD path
    (cooldown=None). Snapshot A was written at T0; racer 1 emits A→B; racer 2
    re-reads the anchor under the advisory lock, sees the winner's committed
    A→B (emitted AFTER T0), and the timestamp guard proves its snapshot_prev
    is a stale pre-write read, not a missed transition: no recovered B→A and
    no duplicate — exactly one event total."""
    conn = seeded_db_empty_cards.conn
    kw = {"kind": "cri_regime", "subject": "CRI", "basis": "eod"}
    with conn.cursor() as cur:
        cur.execute("SELECT now()")
        snapshot_a_written_at = cur.fetchone()[0]
    conn.commit()
    first = emit_on_change(
        conn,
        snapshot_prev="A",
        snapshot_prev_at=snapshot_a_written_at,
        new="B",
        payload={},
        **kw,
    )
    conn.commit()
    second = emit_on_change(
        conn,
        snapshot_prev="A",
        snapshot_prev_at=snapshot_a_written_at,
        new="B",
        payload={},
        **kw,
    )
    conn.commit()
    assert len(first) == 1
    assert second == []
    assert _count(conn) == 1


def test_last_emitted_state_returns_newest_to(seeded_db_empty_cards):
    """Anchor for self-healing emits: the newest event row's `to` wins;
    a triple with no events — or whose newest row carries no `to` — is None."""
    conn = seeded_db_empty_cards.conn
    kw = {"kind": "cri_regime", "subject": "CRI", "basis": "eod"}
    assert last_emitted_state(conn, **kw) is None

    emit_event(conn, payload={"from": None, "to": "LOW"}, **kw)
    emit_event(conn, payload={"from": "LOW", "to": "HIGH"}, **kw)
    # A neighbouring triple must not leak into this one's anchor.
    emit_event(
        conn,
        kind="cri_regime",
        subject="CRI",
        basis="live",
        payload={"to": "CRITICAL"},
    )
    conn.commit()
    assert last_emitted_state(conn, **kw) == "HIGH"
    assert (
        last_emitted_state(conn, kind="cri_regime", subject="CRI", basis="live")
        == "CRITICAL"
    )

    # The newest row carries no `to` → None → caller falls back to the
    # previous persisted snapshot.
    emit_event(conn, payload={"note": "no state carried"}, **kw)
    conn.commit()
    assert last_emitted_state(conn, **kw) is None


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
