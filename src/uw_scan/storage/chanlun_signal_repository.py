"""Standalone repository for the chanlun_signal_events append-mostly log.

Never extends storage/repository.py (standing rule). Upserts are idempotent
(ON CONFLICT DO NOTHING); first_entered_at is preserved across re-runs.
"""

from __future__ import annotations

from datetime import date, datetime

from psycopg import Connection
from psycopg.types.json import Jsonb

# State precedence for the current-state query (higher wins). Equal-rank ties
# (confirmed_native vs invalidated, both terminal) resolve by business time:
# the chronologically-latest as_of wins regardless of insert order, with id as
# the final deterministic tiebreak (rows are scanned ORDER BY as_of, id and the
# >= comparison keeps the last equal-rank row seen).
_STATE_RANK = {
    "pending": 0,
    "confirmed_sublevel": 1,
    "confirmed_native": 2,
    "invalidated": 2,
}


class ChanlunSignalRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_transition(
        self,
        *,
        ticker: str,
        category: str,
        kind: str,
        extreme_date: date,
        extreme_price: float,
        state: str,
        reason: str | None,
        as_of: date,
        details: dict,
        first_entered_at: datetime | None = None,
    ) -> bool:
        with self._conn.cursor() as cur:
            if first_entered_at is None:
                cur.execute(
                    """
                    INSERT INTO chanlun_signal_events
                        (ticker, category, kind, extreme_date, extreme_price,
                         state, reason, as_of, details_jsonb)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, category, kind, extreme_date,
                                 extreme_price, state) DO NOTHING
                    """,
                    (
                        ticker.upper(),
                        category,
                        kind,
                        extreme_date,
                        float(extreme_price),
                        state,
                        reason,
                        as_of,
                        Jsonb(details),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO chanlun_signal_events
                        (ticker, category, kind, extreme_date, extreme_price,
                         state, reason, first_entered_at, as_of, details_jsonb)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, category, kind, extreme_date,
                                 extreme_price, state) DO NOTHING
                    """,
                    (
                        ticker.upper(),
                        category,
                        kind,
                        extreme_date,
                        float(extreme_price),
                        state,
                        reason,
                        first_entered_at,
                        as_of,
                        Jsonb(details),
                    ),
                )
            inserted = cur.rowcount == 1
        self._conn.commit()
        return inserted

    def _rows_for(self, ticker: str) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT category, kind, extreme_date, extreme_price, state,
                       reason, first_entered_at, as_of
                FROM chanlun_signal_events
                WHERE ticker = %s
                ORDER BY as_of ASC, id ASC
                """,
                (ticker.upper(),),
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def current_states(self, ticker: str) -> list[dict]:
        best: dict[tuple, dict] = {}
        for row in self._rows_for(ticker):
            key = (
                row["category"],
                row["kind"],
                row["extreme_date"],
                row["extreme_price"],
            )
            cur_best = best.get(key)
            if (
                cur_best is None
                or _STATE_RANK[row["state"]] >= _STATE_RANK[cur_best["state"]]
            ):
                best[key] = row
        return list(best.values())

    def list_non_terminal(self, ticker: str) -> list[dict]:
        return [
            r
            for r in self.current_states(ticker)
            if r["state"] in ("pending", "confirmed_sublevel")
        ]
