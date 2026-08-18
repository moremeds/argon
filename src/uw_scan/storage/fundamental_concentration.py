"""Point-in-time revenue-breakdown observations (migration 122).

Standalone repository, never a `Repository` mixin — new persistence domains get
their own module from method one (storage split rule, CLAUDE.md).

**Every writer here commits**, matching `fundamental_obs`: the known failure in
this area is a research-layer refresh that ran, logged success and never
committed a row.

The write path is insert-or-touch on `content_hash`. An unchanged refetch bumps
`last_seen_at` and writes no fact; a restatement hashes differently and lands as
a new immutable row beside the old one. Nothing here derives a share — the rules
are unproven and live in `uw_scan.fundamentals.concentration`, applied at read
time so a rule change re-derives history instead of requiring a re-fetch that
the provider's window may no longer serve.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

# One breakdown row is a few hundred bytes of JSONB and the widest filer in the
# frozen fixtures publishes 287 rows, so a whole ticker fits in one chunk.
CHUNK = 2000

#: Periods returned to a reader by default. The probe required 6 to carry a
#: trend and capped at 20; 20 also spans enough history for the annual-detection
#: neighbourhood to have real neighbours at both ends of the series.
DEFAULT_PERIOD_LIMIT = 20


class RevenueBreakdownRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def record_rows(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Insert-or-touch a batch of observations. Returns (inserted, touched).

        Counted by table cardinality either side rather than by `rowcount`,
        because `ON CONFLICT DO UPDATE` reports conflicts and inserts alike and
        would make an all-duplicate rerun look like a full capture.
        """
        batch = list(rows)
        if not batch:
            return (0, 0)

        sql = f"""
            INSERT INTO {self._schema}.revenue_breakdown_obs
                        (source, ticker, report_date, rev_group, field,
                         axis, members, value, content_hash, payload_version,
                         raw_jsonb)
                 VALUES (%(source)s, %(ticker)s, %(report_date)s, %(rev_group)s,
                         %(field)s, %(axis)s, %(members)s, %(value)s,
                         %(content_hash)s, %(payload_version)s, %(raw_jsonb)s)
            ON CONFLICT (source, ticker, report_date, rev_group, content_hash)
            DO UPDATE SET last_seen_at = now()
        """
        before = self._count()
        with self.conn.cursor() as cur:
            for i in range(0, len(batch), CHUNK):
                cur.executemany(
                    sql,
                    [
                        {**row, "raw_jsonb": Jsonb(row["raw_jsonb"])}
                        for row in batch[i : i + CHUNK]
                    ],
                )
        self.conn.commit()
        inserted = self._count() - before
        return (inserted, len(batch) - inserted)

    def periods(
        self, ticker: str, *, limit: int = DEFAULT_PERIOD_LIMIT
    ) -> dict[str, list[dict[str, Any]]]:
        """Raw rows for a ticker's most recent periods, keyed by ISO report date.

        Keyed by string rather than `date` because ISO dates sort chronologically
        as text, which is what the derivation's neighbourhood ordering assumes,
        and because the same keys go out over JSON unchanged.

        Only the newest observation of each identity is returned: a restatement
        adds a row beside its predecessor, and a reader asking "what is the
        breakdown" wants the current answer. The superseded row stays in the
        table for anyone asking what changed.
        """
        sql = f"""
            WITH recent AS (
                SELECT DISTINCT report_date
                  FROM {self._schema}.revenue_breakdown_obs
                 WHERE ticker = %s
                 ORDER BY report_date DESC
                 LIMIT %s
            ),
            ranked AS (
                SELECT o.report_date, o.rev_group, o.field, o.axis, o.members,
                       o.value,
                       row_number() OVER (
                           PARTITION BY o.report_date, o.rev_group, o.field,
                                        o.axis, o.members
                               ORDER BY o.last_seen_at DESC, o.obs_id DESC
                       ) AS rn
                  FROM {self._schema}.revenue_breakdown_obs o
                  JOIN recent r ON r.report_date = o.report_date
                 WHERE o.ticker = %s
            )
            SELECT report_date, rev_group, field, axis, members, value
              FROM ranked WHERE rn = 1
             ORDER BY report_date DESC
        """
        out: dict[str, list[dict[str, Any]]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, (ticker, limit, ticker))
            for report_date, rev_group, field, axis, members, value in cur.fetchall():
                out.setdefault(report_date.isoformat(), []).append(
                    {
                        "rev_group": rev_group,
                        "field": field,
                        "axis": list(axis or []),
                        "members": list(members or []),
                        # float, not Decimal: every consumer divides it by the
                        # period total to get a share, and the ratio of two
                        # Decimals is not a float the JSON encoder accepts.
                        "value": float(value),
                    }
                )
        return out

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self._schema}.revenue_breakdown_obs")
            row = cur.fetchone()
            return int(row[0]) if row else 0
