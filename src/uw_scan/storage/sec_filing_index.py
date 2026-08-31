"""Reads and writes for SEC's mirrored filing index. Standalone repository.

Two tables, one owner: `sec_cik_map` (mutable ticker->CIK) and
`sec_filing_index` (immutable accession-keyed filings). They travel together
because every write path needs both and no other domain reads either.
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from uw_scan.sources.sec_submissions import SecFiling


class SecFilingIndexRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    # ---------------- cik map ----------------

    def upsert_cik_map(self, mapping: dict[str, str]) -> int:
        """Replace the ticker->CIK mapping. Returns rows written.

        `DO UPDATE` here, unlike everywhere else in this module: the mapping is
        current-state, not evidence. A ticker genuinely moves between issuers and
        the fresh answer is the useful one.
        """
        if not mapping:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.sec_cik_map (ticker, cik, refreshed_at)
                 VALUES (%s, %s, now())
            ON CONFLICT (ticker) DO UPDATE
                    SET cik = EXCLUDED.cik, refreshed_at = now()
        """
        rows = [(t.upper(), c) for t, c in mapping.items()]
        with self.conn.cursor() as cur:
            cur.executemany(sql, rows)
        self.conn.commit()
        return len(rows)

    def cik_for(self, tickers: Sequence[str]) -> dict[str, str]:
        if not tickers:
            return {}
        sql = f"SELECT ticker, cik FROM {self._schema}.sec_cik_map WHERE ticker = ANY(%s)"
        with self.conn.cursor() as cur:
            cur.execute(sql, ([t.upper() for t in tickers],))
            return {t: c for t, c in cur.fetchall()}

    # ---------------- filing index ----------------

    def record_filings(
        self, cik: str, ticker: str, filings: Sequence[SecFiling]
    ) -> int:
        """Insert filings for one issuer. Returns rows ACTUALLY written.

        The count is measured, not assumed: `ON CONFLICT DO NOTHING` writes zero
        on a replay, and returning `len(filings)` would report healthy progress
        for a backfill that wrote nothing — the same failure `record_violations`
        avoids for the same reason.
        """
        if not filings:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.sec_filing_index
                        (accession, cik, ticker, form, report_date,
                         filing_date, is_amendment)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO NOTHING
              RETURNING accession
        """
        params = [
            (
                f.accession,
                cik,
                ticker.upper(),
                f.form,
                f.report_date,
                f.filing_date,
                f.is_amendment,
            )
            for f in filings
        ]
        written = 0
        with self.conn.cursor() as cur:
            for row in params:
                cur.execute(sql, row)
                written += len(cur.fetchall())
        self.conn.commit()
        return written

    def filings_for(self, ticker: str) -> list[SecFiling]:
        sql = f"""
            SELECT accession, form, report_date, filing_date, is_amendment
              FROM {self._schema}.sec_filing_index
             WHERE ticker = %s
             ORDER BY report_date, filing_date, accession
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            return [
                SecFiling(
                    accession=a,
                    form=f,
                    report_date=rd,
                    filing_date=fd,
                    is_amendment=amd,
                )
                for a, f, rd, fd, amd in cur.fetchall()
            ]

    def filings_by_ticker(self, tickers: Sequence[str]) -> dict[str, list[SecFiling]]:
        """One query for a whole batch. The evidence job runs over ~400 names."""
        if not tickers:
            return {}
        sql = f"""
            SELECT ticker, accession, form, report_date, filing_date, is_amendment
              FROM {self._schema}.sec_filing_index
             WHERE ticker = ANY(%s)
             ORDER BY ticker, report_date, filing_date, accession
        """
        out: dict[str, list[SecFiling]] = {}
        with self.conn.cursor() as cur:
            cur.execute(sql, ([t.upper() for t in tickers],))
            for tkr, a, f, rd, fd, amd in cur.fetchall():
                out.setdefault(tkr, []).append(
                    SecFiling(
                        accession=a,
                        form=f,
                        report_date=rd,
                        filing_date=fd,
                        is_amendment=amd,
                    )
                )
        return out

    def indexed_tickers(self) -> set[str]:
        sql = f"SELECT DISTINCT ticker FROM {self._schema}.sec_filing_index"
        with self.conn.cursor() as cur:
            cur.execute(sql)
            return {r[0] for r in cur.fetchall()}

    def index_counts(self) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(*),
                       count(*) FILTER (WHERE is_amendment),
                       count(DISTINCT ticker)
                  FROM {self._schema}.sec_filing_index
                """
            )
            total, amended, tickers = cur.fetchone()
            cur.execute(f"SELECT count(*) FROM {self._schema}.sec_cik_map")
            (mapped,) = cur.fetchone()
        return {
            "filings": int(total),
            "amendments": int(amended),
            "tickers": int(tickers),
            "cik_mapped": int(mapped),
        }
