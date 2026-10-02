"""Agent MCP event emitter (migration 154). Module-level functions, not a
repository class: emitters run inside the CALLER's transaction, so the event
row and the state row that produced it commit together — the advisory lock plus
NOTIFY-on-commit ordering only holds that way.

`mcp_event` is append-only. `pg_notify('mcp_event', <id>)` is queued in the
transaction and delivered at the caller's commit, so a LISTENing subscriber can
never see an id that later rolls back.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_SCHEMA = "uw_scan"

# Fixed advisory-lock key serializing all mcp_event emitters within their
# transaction (pg_advisory_xact_lock — released automatically at commit/rollback).
# Held from probe to commit, it forces commit order == id order: without it a
# `get_events` cursor could advance past a still-uncommitted lower id and lose
# that event for good. It also makes the cooldown probe + insert atomic.
MCP_EVENT_LOCK = 727_000_154


def emit_event(
    conn: psycopg.Connection,
    *,
    kind: str,
    subject: str,
    basis: str,
    payload: Mapping[str, Any],
    cooldown: timedelta | None = None,
) -> int | None:
    """Insert one `mcp_event` row and queue a NOTIFY. Does NOT commit.

    Returns the new event id, or None when `cooldown` suppressed the insert
    (an event with the same (kind, subject, basis) already emitted inside the
    window).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (MCP_EVENT_LOCK,))
        if cooldown is not None:
            cur.execute(
                f"""
                SELECT 1
                  FROM {_SCHEMA}.mcp_event
                 WHERE kind = %s AND subject = %s AND basis = %s
                   AND emitted_at > now() - %s
                 LIMIT 1
                """,
                (kind, subject, basis, cooldown),
            )
            if cur.fetchone() is not None:
                return None
        cur.execute(
            f"""
            INSERT INTO {_SCHEMA}.mcp_event (kind, subject, basis, payload)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (kind, subject, basis, Jsonb(dict(payload))),
        )
        new_id = int(cur.fetchone()[0])
        cur.execute("SELECT pg_notify('mcp_event', %s)", (str(new_id),))
    return new_id


def emit_on_change(
    conn: psycopg.Connection,
    *,
    kind: str,
    subject: str,
    basis: str,
    prev: Any,
    new: Any,
    payload: Mapping[str, Any],
    cooldown: timedelta | None = None,
) -> int | None:
    """Emit only when the persisted state actually changed.

    A first-ever row (`prev is None`) is not a change, and a degraded scan
    yielding `new is None` must not emit a flip to null — both no-op. When the
    event fires, `{"from": prev, "to": new}` is merged into the payload.
    """
    if prev is None or new is None or prev == new:
        return None
    merged = {**payload, "from": prev, "to": new}
    return emit_event(
        conn,
        kind=kind,
        subject=subject,
        basis=basis,
        payload=merged,
        cooldown=cooldown,
    )


def last_emitted_state(
    conn: psycopg.Connection,
    *,
    kind: str,
    subject: str,
    basis: str,
) -> Any | None:
    """Return ``payload->'to'`` of the newest ``mcp_event`` row for the triple.

    ``None`` when the triple has never emitted (or the newest row carries no
    ``to``). Emitters resolve ``prev`` from this FIRST and only fall back to
    the previous persisted snapshot when it is ``None``. The snapshot row
    commits before the emit runs, so a failed emit used to leave the snapshot
    ahead of the stream: the next scan read the new state as ``prev`` and
    ``emit_on_change`` no-oped — the flip was lost for SSE and get_events.
    Anchoring ``prev`` on the event stream makes the emit self-healing: the
    missed flip re-attempts on the next scan, from the last state subscribers
    were actually told about.
    """
    # ponytail: residual ceiling — if the very FIRST event for a triple fails
    # to emit, no stream row exists to anchor on; the snapshot fallback then
    # compares the new state to itself and that one flip is still lost.
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT payload->'to'
              FROM {_SCHEMA}.mcp_event
             WHERE kind = %s AND subject = %s AND basis = %s
             ORDER BY id DESC
             LIMIT 1
            """,
            (kind, subject, basis),
        )
        row = cur.fetchone()
    return row[0] if row is not None else None


def purge_old_events(conn: psycopg.Connection, days: int = 30) -> int:
    """Delete `mcp_event` rows older than `days`; returns the deleted count.

    Does NOT commit — the retention job's caller owns the transaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            DELETE FROM {_SCHEMA}.mcp_event
             WHERE emitted_at < now() - %s * interval '1 day'
            """,
            (days,),
        )
        return cur.rowcount
