"""Historized issuer identity (migration 134). Standalone repository.

`fundamental_company_type` answers "what type is this name TODAY". This answers
"what type was it WHEN", which is the question a historical result needs and the
one an UPDATE-in-place table destroys.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg

STATUS_EVIDENCED = "evidenced"
STATUS_DEFAULTED = "defaulted"
STATUS_MANUAL = "manual"


class CompanyIdentityRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def assign(
        self,
        ticker: str,
        *,
        company_type: str,
        status: str,
        evidence: str,
        sector: str | None = None,
        currency: str | None = None,
        issuer_cik: str | None = None,
        note: str | None = None,
    ) -> bool:
        """Open a new interval if anything material changed. Returns whether it did.

        No-ops when the open interval already carries the same classification —
        which is what makes a nightly reseed cost nothing and, more importantly,
        keeps the history readable: a table of 400 identical intervals per name
        records nothing except how often the job ran.

        A `manual` interval is never superseded by a non-manual assignment. That
        mirrors `fundamental_company_type.assign`'s existing rule, so a hand
        correction survives a reseed here too.
        """
        current = self.current(ticker)
        if current is not None:
            if current["status"] == STATUS_MANUAL and status != STATUS_MANUAL:
                return False
            unchanged = (
                current["company_type"] == company_type
                and current["status"] == status
                and current["sector"] == sector
                and current["issuer_cik"] == issuer_cik
            )
            if unchanged:
                return False

        with self.conn.cursor() as cur:
            # Close and open in ONE transaction. A crash between them would
            # leave either two open intervals (the unique index refuses) or
            # none — and "none" reads as a name that was never classified.
            cur.execute(
                f"""UPDATE {self._schema}.company_identity
                       SET valid_to = now()
                     WHERE ticker = %s AND valid_to IS NULL""",
                (ticker.upper(),),
            )
            cur.execute(
                f"""INSERT INTO {self._schema}.company_identity
                            (ticker, issuer_cik, company_type, sector, currency,
                             status, evidence, note)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    ticker.upper(),
                    issuer_cik,
                    company_type,
                    sector,
                    currency,
                    status,
                    evidence,
                    note,
                ),
            )
        self.conn.commit()
        return True

    def current(self, ticker: str) -> dict[str, Any] | None:
        return self._one(
            f"""SELECT * FROM {self._schema}.company_identity
                 WHERE ticker = %s AND valid_to IS NULL""",
            (ticker.upper(),),
        )

    def at(self, ticker: str, as_of: datetime) -> dict[str, Any] | None:
        """The interval covering `as_of`. None if the name was unclassified then.

        Returning None rather than falling back to the current interval is the
        whole point: a result computed before any classification existed was not
        computed under today's type, and saying so is the honest answer.
        """
        return self._one(
            f"""SELECT * FROM {self._schema}.company_identity
                 WHERE ticker = %s
                   AND valid_from <= %s
                   AND (valid_to IS NULL OR valid_to > %s)""",
            (ticker.upper(), as_of, as_of),
        )

    def history(self, ticker: str) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT identity_id, company_type, sector, status, evidence,
                           note, valid_from, valid_to
                      FROM {self._schema}.company_identity
                     WHERE ticker = %s
                     ORDER BY valid_from""",
                (ticker.upper(),),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def _one(self, sql: str, params: tuple) -> dict[str, Any] | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row, strict=True))

    # ---------------- coverage ----------------

    def coverage(self, tier: str = "ranked") -> dict[str, Any]:
        """Classification coverage over a universe tier, and the unclassified list.

        Persisted-by-query rather than a stored counter: the answer must never be
        able to disagree with the table it describes.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(*)                                        AS names,
                       count(i.identity_id)                            AS classified,
                       count(*) FILTER (WHERE i.status = 'evidenced')  AS evidenced,
                       count(*) FILTER (WHERE i.status = 'defaulted')  AS defaulted,
                       count(*) FILTER (WHERE i.status = 'manual')     AS manual
                  FROM {self._schema}.fundamental_universe u
                  LEFT JOIN {self._schema}.company_identity i
                         ON i.ticker = u.ticker AND i.valid_to IS NULL
                 WHERE u.tier = %s AND u.removed_at IS NULL
                """,
                (tier,),
            )
            names, classified, evidenced, defaulted, manual = cur.fetchone()
            cur.execute(
                f"""
                SELECT u.ticker
                  FROM {self._schema}.fundamental_universe u
                  LEFT JOIN {self._schema}.company_identity i
                         ON i.ticker = u.ticker AND i.valid_to IS NULL
                 WHERE u.tier = %s AND u.removed_at IS NULL
                   AND (i.identity_id IS NULL OR i.status = 'defaulted')
                 ORDER BY u.ticker
                """,
                (tier,),
            )
            unresolved = [r[0] for r in cur.fetchall()]
        return {
            "tier": tier,
            "names": int(names),
            "classified": int(classified),
            "evidenced": int(evidenced),
            "defaulted": int(defaulted),
            "manual": int(manual),
            "unresolved": unresolved,
        }

    def shared_issuers(self, tickers: Sequence[str] | None = None) -> dict[str, list[str]]:
        """CIK -> the tickers claiming it, where more than one does.

        Two share classes of one issuer file ONE set of financials. Admitting
        both to a cross-section gives that issuer double weight, which is a
        silent bias rather than an error anything would raise.
        """
        where = "WHERE i.valid_to IS NULL AND i.issuer_cik IS NOT NULL"
        params: list[Any] = []
        if tickers:
            where += " AND i.ticker = ANY(%s)"
            params.append([t.upper() for t in tickers])
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT i.issuer_cik, array_agg(i.ticker ORDER BY i.ticker)
                  FROM {self._schema}.company_identity i
                  {where}
                 GROUP BY i.issuer_cik
                HAVING count(*) > 1
                """,
                params,
            )
            return {cik: list(names) for cik, names in cur.fetchall()}
