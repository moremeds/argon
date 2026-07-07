"""Same-day UW fetch dedupe memo (issue #225).

Standalone repository (NOT composed into ``Repository`` — new domain gets its
own module per the storage split rule). Stores the raw UW JSON response keyed
``(ticker, endpoint, as_of_date)`` so the second+ same-day caller of an
identical slow-moving fetch reuses the first result instead of spending UW
budget again.

// ponytail: TTL is deliberately a flat "same trading day" — a row whose
// as_of_date == today is a hit; any other date is a MISS (reader) and gets
// pruned (writer). This is correct for the two endpoints wrapped today
// (option_contracts, greek_exposure_by_expiry) because that data is
// end-of-day-ish stable within a session. UPGRADE PATH: if a future endpoint
// refreshes intraday, add a per-endpoint TTL (e.g. a `ttl_seconds` column or
// an endpoint→interval map consulted against `fetched_at`) rather than
// widening this same-day ceiling for everyone.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb


class UwFetchMemoRepository:
    """Postgres-backed same-day memo over UW fetch responses.

    Shares the caller's connection (the fetcher's ``repo.conn``). Writes are NOT
    committed here — they ride the caller's scan transaction, exactly like the
    audit rows written alongside them. Cross-process dedupe therefore becomes
    visible once the owning scan commits (full_scan commits per ticker), which
    is frequent enough for the intended budget relief.
    """

    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def get(
        self, ticker: str, endpoint: str, as_of_date: date
    ) -> dict[str, Any] | None:
        """Return the memoized payload for today's key, or None on a MISS.

        A HIT atomically records the budget SAVE: hit_count += 1, last_hit_at =
        now(). The single UPDATE ... RETURNING both reads the payload and stamps
        the attribution, so the SAVE is durable and observable.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE uw_fetch_memo
                   SET hit_count = hit_count + 1,
                       last_hit_at = now()
                 WHERE ticker = %s AND endpoint = %s AND as_of_date = %s
                RETURNING payload
                """,
                (ticker, endpoint, as_of_date),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return row[0]

    def put(
        self, ticker: str, endpoint: str, as_of_date: date, payload: dict[str, Any]
    ) -> None:
        """Store the fetched payload for today's key (first caller / MISS path).

        On a race where another process already inserted the row, refresh the
        payload + fetched_at but preserve the accumulated hit_count.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_fetch_memo (ticker, endpoint, as_of_date, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker, endpoint, as_of_date) DO UPDATE
                    SET payload = EXCLUDED.payload,
                        fetched_at = now()
                """,
                (ticker, endpoint, as_of_date, Jsonb(payload)),
            )

    def prune(self, before: date) -> int:
        """Delete memo rows older than `before` (stale trading days). Returns count."""
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM uw_fetch_memo WHERE as_of_date < %s",
                (before,),
            )
            return cur.rowcount
