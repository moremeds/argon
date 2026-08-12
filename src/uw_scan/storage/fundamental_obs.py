"""Tier-1 fundamental observations and the two-tier universe (migration 114).

Standalone repository, never a `Repository` mixin — new persistence domains get
their own module from method one (storage split rule, CLAUDE.md).

**Every writer here commits.** The known failure in this area is a
research-layer refresh that ran, logged success and never committed a row, so
the caller-commits convention is not used in this module.

The write path is insert-or-touch on `content_hash`: an unchanged refetch bumps
`last_seen_at` and writes no fact; a restatement hashes differently and lands as
a new immutable row beside the old one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from uw_scan.fundamentals.statements import Violation

# One statement row is ~1 KB of JSONB; 2,000 keeps a chunk comfortably under the
# parameter ceiling while still amortising round-trips over a 60k-row ingest.
CHUNK = 2000


class FundamentalObsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- universe ----------------

    def list_universe(self, tier: str) -> list[str]:
        """Active tickers in a tier, stable order.

        Returns [] for an unknown or fully-removed tier rather than raising: the
        ingest job gates on this being non-empty, so an unseeded tier must read
        as "nothing to do" and spend zero UW calls, not as a crash.
        """
        sql = f"""
            SELECT ticker FROM {self._schema}.fundamental_universe
             WHERE tier = %s AND removed_at IS NULL
             ORDER BY ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (tier,))
            return [r[0] for r in cur.fetchall()]

    def seed_universe(
        self, tier: str, rows: Sequence[tuple[str, str | None, str | None]]
    ) -> int:
        """Upsert (ticker, layer, reason) members of a tier. Idempotent.

        Re-seeding un-removes a name deliberately: the seed list is the intended
        membership, so a ticker present in it should be active regardless of a
        prior removal.
        """
        sql = f"""
            INSERT INTO {self._schema}.fundamental_universe
                        (tier, ticker, layer, reason)
                 VALUES (%s, %s, %s, %s)
            ON CONFLICT (tier, ticker) DO UPDATE
                    SET layer = EXCLUDED.layer,
                        reason = EXCLUDED.reason,
                        removed_at = NULL
        """
        with self.conn.cursor() as cur:
            cur.executemany(
                sql, [(tier, t, layer, reason) for t, layer, reason in rows]
            )
        self.conn.commit()
        return len(rows)

    # ---------------- observations ----------------

    def record_statements(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """Insert-or-touch a batch of observations. Returns (inserted, touched).

        Counted by table cardinality either side rather than by `rowcount`,
        because `ON CONFLICT DO UPDATE` reports conflicts and inserts alike and
        would make an all-duplicate rerun look like a full ingest.
        """
        batch = list(rows)
        if not batch:
            return (0, 0)

        sql = f"""
            INSERT INTO {self._schema}.fundamental_statement_obs
                        (source, ticker, period_end, period_type, statement,
                         content_hash, provider_record_id, filing_accession,
                         filing_published_at, raw_jsonb, field_map_version)
                 VALUES (%(source)s, %(ticker)s, %(period_end)s, %(period_type)s,
                         %(statement)s, %(content_hash)s, %(provider_record_id)s,
                         %(filing_accession)s, %(filing_published_at)s,
                         %(raw_jsonb)s, %(field_map_version)s)
            ON CONFLICT (source, ticker, period_end, period_type, statement, content_hash)
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

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT count(*) FROM {self._schema}.fundamental_statement_obs"
            )
            return int(cur.fetchone()[0])

    def obs_id(
        self,
        *,
        source: str,
        ticker: str,
        period_end: date,
        period_type: str,
        statement: str,
        content_hash: str,
    ) -> int | None:
        """Resolve an observation's surrogate id from its content identity."""
        sql = f"""
            SELECT obs_id FROM {self._schema}.fundamental_statement_obs
             WHERE source = %s AND ticker = %s AND period_end = %s
               AND period_type = %s AND statement = %s AND content_hash = %s
        """
        with self.conn.cursor() as cur:
            cur.execute(
                sql, (source, ticker, period_end, period_type, statement, content_hash)
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def record_violations(self, obs_id: int, violations: Sequence[Violation]) -> int:
        """Attach integrity failures to one observation. Idempotent per check.

        `DO NOTHING` rather than `DO UPDATE`: a violation is a verdict about an
        immutable payload, so re-running the same check over the same row cannot
        legitimately produce a different answer, and the original `detected_at`
        is the more useful fact to keep.
        """
        if not violations:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.fundamental_obs_violations
                        (obs_id, check_name, field, observed_value, detail_jsonb)
                 VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (obs_id, check_name) DO NOTHING
        """
        with self.conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    (
                        obs_id,
                        v.check_name,
                        v.field,
                        v.observed_value,
                        Jsonb(v.detail) if v.detail else None,
                    )
                    for v in violations
                ],
            )
        self.conn.commit()
        return len(violations)

    # ---------------- reads ----------------

    def coverage(self, tier: str) -> list[dict[str, Any]]:
        """Per-ticker ingest coverage for the tier — what actually landed.

        The point of reporting this per ticker rather than as a total is that a
        total hides the shape that matters: 245 names at 80 quarters and 200
        names at 98 quarters give the same row count and very different panels.
        """
        sql = f"""
            SELECT u.ticker,
                   count(o.obs_id)                    AS rows,
                   count(DISTINCT o.period_end)       AS periods,
                   min(o.period_end)                  AS first_period,
                   max(o.period_end)                  AS last_period,
                   count(*) FILTER (WHERE o.filing_published_at IS NOT NULL) AS with_filing_date
              FROM {self._schema}.fundamental_universe u
              LEFT JOIN {self._schema}.fundamental_statement_obs o
                     ON o.ticker = u.ticker
             WHERE u.tier = %s AND u.removed_at IS NULL
             GROUP BY u.ticker
             ORDER BY u.ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (tier,))
            return [
                {
                    "ticker": r[0],
                    "rows": r[1],
                    "periods": r[2],
                    "first_period": r[3],
                    "last_period": r[4],
                    "with_filing_date": r[5],
                }
                for r in cur.fetchall()
            ]
