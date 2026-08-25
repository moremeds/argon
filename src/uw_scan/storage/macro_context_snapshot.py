"""Persistence for the macro context snapshot (migration 130).

Separate module rather than an extension of ``repository.py``: a new domain gets its own
seam from method one, which is the rule ``repository.py`` exists to demonstrate the cost of
ignoring.

The write is idempotent on ``(as_of, assembler_version, inputs_hash)``. A nightly rerun
over unchanged states must return the existing snapshot rather than manufacture a second
identical answer, and the domain rows are written only when the snapshot row is new -- so a
rerun cannot append a duplicate edge either.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from uw_scan.macro.snapshot import MacroContextSnapshot


def _require_aware(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


class _MacroContextSnapshotMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_macro_context_snapshot(self, snapshot: MacroContextSnapshot) -> int:
        """Persist a snapshot and its domain rows; return the snapshot id.

        Re-inserting the same identity returns the id already stored. The domain rows are
        inserted only alongside a NEW snapshot row: writing them on the idempotent path
        would either duplicate the edges or require an upsert whose conflict behaviour is a
        second place for the two writes to disagree.
        """
        _require_aware("as_of", snapshot.as_of)
        _require_aware("assembled_at", snapshot.assembled_at)

        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.macro_context_snapshots
                  (as_of, assembled_at, status, status_reasons_jsonb,
                   inputs_hash, assembler_version)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (as_of, assembler_version, inputs_hash) DO NOTHING
                RETURNING snapshot_id
                """,
                (
                    snapshot.as_of,
                    snapshot.assembled_at,
                    snapshot.status,
                    json.dumps([r.as_json() for r in snapshot.reasons]),
                    snapshot.inputs_hash,
                    snapshot.assembler_version,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    f"""
                    SELECT snapshot_id FROM {self._schema}.macro_context_snapshots
                    WHERE as_of = %s AND assembler_version = %s AND inputs_hash = %s
                    """,
                    (snapshot.as_of, snapshot.assembler_version, snapshot.inputs_hash),
                )
                existing = cur.fetchone()
                if existing is None:  # pragma: no cover - a row that conflicted must exist
                    raise RuntimeError("snapshot conflicted but could not be read back")
                return int(existing["snapshot_id"])

            snapshot_id = int(row["snapshot_id"])
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.macro_context_snapshot_domains
                  (snapshot_id, domain, state_id, ordinal)
                VALUES (%s, %s, %s, %s)
                """,
                [
                    (snapshot_id, d.domain, d.state_id, d.ordinal)
                    for d in snapshot.domains
                ],
            )
            return snapshot_id

    def fetch_macro_context_snapshot(self, snapshot_id: int) -> dict[str, Any] | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT * FROM {self._schema}.macro_context_snapshots WHERE snapshot_id = %s",
                (snapshot_id,),
            )
            return cur.fetchone()

    def fetch_macro_context_snapshot_as_of(
        self, as_of: datetime
    ) -> dict[str, Any] | None:
        """The newest snapshot answering for a time at or before ``as_of``.

        Returns ``None`` before any snapshot existed rather than an empty snapshot. An
        invented "we knew nothing" row would be a claim Argon never made, and a reader
        cannot tell one from a real refusal.
        """
        _require_aware("as_of", as_of)
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT * FROM {self._schema}.macro_context_snapshots
                WHERE as_of <= %s
                ORDER BY as_of DESC, assembled_at DESC, snapshot_id DESC
                LIMIT 1
                """,
                (as_of,),
            )
            return cur.fetchone()

    def fetch_macro_context_snapshot_domains(
        self, snapshot_id: int
    ) -> list[dict[str, Any]]:
        """The domain answers a snapshot holds, in the causal order it was assembled with.

        Joins each domain state's own answer, because "the snapshot holds state 41" is not
        yet useful -- what that state SAID is what a reader is after.
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT sd.domain, sd.state_id, sd.ordinal,
                       s.state, s.direction, s.confidence,
                       s.as_of AS state_as_of, s.engine_version, s.inputs_hash
                FROM {self._schema}.macro_context_snapshot_domains sd
                JOIN {self._schema}.macro_domain_states s ON s.state_id = sd.state_id
                WHERE sd.snapshot_id = %s
                ORDER BY sd.ordinal
                """,
                (snapshot_id,),
            )
            return [dict(row) for row in cur.fetchall()]
