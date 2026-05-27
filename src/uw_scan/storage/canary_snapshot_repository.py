"""Focused storage module for canary_snapshots — never extend repository.py.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §9.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

VALID_FORMS = ("linear", "convex", "concave", "sigmoid")
VALID_BANDS = ("NONE", "WATCH", "BUY", "STRONG_BUY")
VALID_WARNING_STATES = (
    "NONE",
    "CONFIRMED_CANARY_ACTIVE",
    "BUY_THE_DIP_ACTIVE",
    "BOTH_ACTIVE_AMBIGUOUS",
)


class CanarySnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    def insert_snapshot(
        self,
        *,
        payload: dict[str, Any],
        data_date: _date,
        composite_version: int,
        score_form: str,
        score: Decimal,
        raw_score: Decimal,
        band: str,
        tactical_score: Decimal,
        structural_score: Decimal,
        speed_score: int,
        warning_state: str,
        payload_hash: str,
        on_conflict: str = "noop",  # 'noop' | 'overwrite'
    ) -> int | None:
        """Insert a snapshot. Returns the new row id, or None if no-op on conflict.

        on_conflict='overwrite' replaces the existing row, preserving the prior
        payload in payload._prior for audit.
        """
        assert score_form in VALID_FORMS, score_form
        assert band in VALID_BANDS, band
        assert warning_state in VALID_WARNING_STATES, warning_state
        assert speed_score in (0, 8, 20), speed_score

        with self._conn.cursor() as cur:
            if on_conflict == "overwrite":
                cur.execute(
                    f"""
                    SELECT id, payload, payload_hash
                    FROM {self._schema}.canary_snapshots
                    WHERE data_date = %s AND composite_version = %s
                    """,
                    (data_date, composite_version),
                )
                prior = cur.fetchone()
                if prior is not None:
                    payload = {
                        **payload,
                        "_prior": {
                            "row_id": prior[0],
                            "payload_hash": prior[2],
                            "payload": prior[1],
                        },
                    }
                    cur.execute(
                        f"DELETE FROM {self._schema}.canary_snapshots WHERE id = %s",
                        (prior[0],),
                    )

            cur.execute(
                f"""
                INSERT INTO {self._schema}.canary_snapshots
                    (data_date, composite_version, score_form,
                     score, raw_score, band,
                     tactical_score, structural_score, speed_score,
                     warning_state, payload, payload_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (data_date, composite_version) DO NOTHING
                RETURNING id
                """,
                (
                    data_date,
                    composite_version,
                    score_form,
                    score,
                    raw_score,
                    band,
                    tactical_score,
                    structural_score,
                    speed_score,
                    warning_state,
                    Jsonb(payload),
                    payload_hash,
                ),
            )
            row = cur.fetchone()
            # v0.4 patch C2: commit explicitly so scheduler-style runs that close
            # the connection don't roll back the insert (mirrors CriSnapshotRepository).
            self._conn.commit()
            return row[0] if row else None

    # v0.4 patch I8: method naming matches CRI convention (fetch_latest / fetch_history)
    def fetch_latest(self, *, composite_version: int) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT data_date, score, raw_score, band, tactical_score,
                       structural_score, speed_score, warning_state,
                       score_form, payload, payload_hash, inserted_at
                FROM {self._schema}.canary_snapshots
                WHERE composite_version = %s
                ORDER BY data_date DESC
                LIMIT 1
                """,
                (composite_version,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def fetch_history(
        self, *, composite_version: int, days: int
    ) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT data_date, score, raw_score, band, tactical_score,
                       structural_score, speed_score, warning_state,
                       score_form, payload, payload_hash, inserted_at,
                       (payload->'inputs'->>'spx_close')::float8 AS spx_close
                FROM {self._schema}.canary_snapshots
                WHERE composite_version = %s
                ORDER BY data_date DESC
                LIMIT %s
                """,
                (composite_version, days),
            )
            return [self._row_to_dict_with_spx(r) for r in cur.fetchall()]

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        keys = (
            "data_date",
            "score",
            "raw_score",
            "band",
            "tactical_score",
            "structural_score",
            "speed_score",
            "warning_state",
            "score_form",
            "payload",
            "payload_hash",
            "inserted_at",
        )
        return dict(zip(keys, row))

    @staticmethod
    def _row_to_dict_with_spx(row: tuple) -> dict[str, Any]:
        keys = (
            "data_date",
            "score",
            "raw_score",
            "band",
            "tactical_score",
            "structural_score",
            "speed_score",
            "warning_state",
            "score_form",
            "payload",
            "payload_hash",
            "inserted_at",
            "spx_close",
        )
        return dict(zip(keys, row))
