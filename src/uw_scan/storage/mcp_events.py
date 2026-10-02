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
from datetime import datetime, timedelta
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
    snapshot_prev: Any,
    new: Any,
    payload: Mapping[str, Any],
    cooldown: timedelta | None = None,
    snapshot_prev_at: datetime | None = None,
    snapshot_prev_payload: Mapping[str, Any] | None = None,
) -> list[int]:
    """Emit on a real state change; return the ids of the rows written.

    The anchor is the last state the stream actually EMITTED, resolved UNDER
    the advisory lock: an emitter that waited on the lock sees the winner's
    committed row and cannot re-fire the same flip (two callers that both
    read ``prev`` outside the lock used to double-emit it).

    ``snapshot_prev`` is the caller's read of the previous persisted state,
    taken BEFORE its write. It anchors the first-ever emit when the stream
    has no row for the triple, and it exposes a missed transition: an earlier
    emit that died after its snapshot committed leaves the snapshot ahead of
    the stream, so the ``anchor → snapshot_prev`` step is emitted first
    (``recovered: true``) and the normal compare runs from there.

    The missed-transition read needs ``snapshot_prev_at``: the previous
    snapshot row's WRITE time (``scanned_at`` / ``created_at``, all from the
    DB's ``now()``) must be LATER than the anchor event's ``emitted_at``.
    That ordering is what separates a snapshot that advanced past the stream
    from a stale pre-write read — a racing caller that lost the advisory lock
    sees the winner's emit as its anchor while still holding the OLD
    snapshot_prev (written before that emit), and must not report it back as
    a missed step. The timestamp guard makes that distinction.

    The recovered step runs ONLY when ``cooldown`` is None (the EOD sites).
    On a cooldown site a suppressed state differs from the anchor by design —
    the cooldown is what kept it off the stream — so a recovered emit there
    would carry no cooldown and bypass the window; live callers keep the
    anchor-compare alone and pass no ``snapshot_prev_at``.

    ``snapshot_prev_payload`` is the context the normal event carries (e.g.
    ``data_date``, ``score``), read from the SAME previous snapshot row as
    ``snapshot_prev``; the recovered event carries it so a consumer can place
    the missed step. ``None`` values are dropped — never fabricated.

    A first-ever state (no anchor and no snapshot_prev) is not a change, and
    a degraded scan yielding ``new is None`` must not emit a flip to null —
    both no-op. When the change event fires, ``{"from": anchor, "to": new}``
    is merged into the payload.
    """
    ids: list[int] = []
    with conn.cursor() as cur:
        # xact-scoped: stacks harmlessly with emit_event's own acquisition.
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (MCP_EVENT_LOCK,))
    anchor, anchor_at = _last_emitted_state_at(
        conn, kind=kind, subject=subject, basis=basis
    )
    if anchor is None:
        # ponytail: if the very FIRST emit for a triple failed, no stream row
        # exists to anchor on, the fallback below compares the persisted state
        # to itself, and that one flip is still lost.
        anchor = snapshot_prev
    elif (
        cooldown is None
        and snapshot_prev is not None
        and snapshot_prev != anchor
        and snapshot_prev_at is not None
        and snapshot_prev_at > anchor_at
    ):
        # The persisted state moved past the last emitted one without an
        # event — a failed earlier emit (the snapshot row's write time
        # postdates the anchor's emit). Announce the missed step first so
        # the stream stays continuous (anchor → … → new).
        # ponytail: two or more consecutive failed EOD scans recover only the
        # LATEST missed step — snapshot_prev holds only the newest persisted
        # state, and the intermediate ones collapse into it.
        recovered_id = emit_event(
            conn,
            kind=kind,
            subject=subject,
            basis=basis,
            payload={
                **{
                    k: v
                    for k, v in (snapshot_prev_payload or {}).items()
                    if v is not None
                },
                "from": anchor,
                "to": snapshot_prev,
                "recovered": True,
            },
        )
        if recovered_id is not None:
            ids.append(recovered_id)
        anchor = snapshot_prev
    if new is None or anchor is None or new == anchor:
        return ids
    new_id = emit_event(
        conn,
        kind=kind,
        subject=subject,
        basis=basis,
        payload={**payload, "from": anchor, "to": new},
        cooldown=cooldown,
    )
    if new_id is not None:
        ids.append(new_id)
    return ids


def last_emitted_state(
    conn: psycopg.Connection,
    *,
    kind: str,
    subject: str,
    basis: str,
) -> Any | None:
    """Return ``payload->'to'`` of the newest ``mcp_event`` row for the triple.

    ``None`` when the triple has never emitted (or the newest row carries no
    ``to``). ``emit_on_change`` resolves its anchor from this — the last
    state subscribers were actually told about — so a failed emit self-heals
    on the next scan instead of losing the flip. Callers pass their own
    pre-write read as ``snapshot_prev``; they do not call this themselves.
    """
    state, _emitted_at = _last_emitted_state_at(
        conn, kind=kind, subject=subject, basis=basis
    )
    return state


def _last_emitted_state_at(
    conn: psycopg.Connection,
    *,
    kind: str,
    subject: str,
    basis: str,
) -> tuple[Any | None, datetime | None]:
    """Newest ``mcp_event`` row's ``(payload->'to', emitted_at)`` for the
    triple — ``emit_on_change``'s anchor read. The timestamp is what lets a
    missed transition be told apart from a stale racer's pre-write read.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT payload->'to', emitted_at
              FROM {_SCHEMA}.mcp_event
             WHERE kind = %s AND subject = %s AND basis = %s
             ORDER BY id DESC
             LIMIT 1
            """,
            (kind, subject, basis),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row is not None else (None, None)


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
