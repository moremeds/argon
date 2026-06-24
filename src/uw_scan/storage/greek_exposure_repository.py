"""Persistence for UW /greek-exposure daily history. New domain — own file."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class GreekExposureDailyRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_rows(self, ticker: str, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        params = [
            {
                "ticker": ticker,
                "trade_date": r["trade_date"],
                "call_gex": r.get("call_gex"),
                "put_gex": r.get("put_gex"),
                "call_delta": r.get("call_delta"),
                "put_delta": r.get("put_delta"),
                "payload": Jsonb(r.get("payload") or {}),
            }
            for r in rows
        ]
        sql = """
            INSERT INTO greek_exposure_daily
                (ticker, trade_date, call_gex, put_gex,
                 call_delta, put_delta, payload)
            VALUES
                (%(ticker)s, %(trade_date)s, %(call_gex)s, %(put_gex)s,
                 %(call_delta)s, %(put_delta)s, %(payload)s)
            ON CONFLICT (ticker, trade_date) DO UPDATE SET
                call_gex   = EXCLUDED.call_gex,
                put_gex    = EXCLUDED.put_gex,
                call_delta = EXCLUDED.call_delta,
                put_delta  = EXCLUDED.put_delta,
                payload    = EXCLUDED.payload
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def fetch_history(self, ticker: str, days: int) -> list[dict]:
        """Return up to `days` most-recent rows, ascending by trade_date."""
        sql = """
            SELECT ticker, trade_date,
                   call_gex::float8,   put_gex::float8,
                   call_delta::float8, put_delta::float8,
                   net_gex::float8,    net_dex::float8
              FROM greek_exposure_daily
             WHERE ticker = %s
             ORDER BY trade_date DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows

    def select_rederived_rows(
        self, ticker: str | None = None, since: date | None = None
    ) -> list[dict]:
        """Sum per-strike GEX/DEX into daily totals, one row per (ticker,
        market_date) using the canonical run.

        Canonical run = the latest run_id for that (ticker, market_date) that is
        status='ok' AND aggregates IS NOT NULL AND not an empty payload — the
        same renderable-run rule latest_run_id uses, applied per historical
        date. Because one scan_run captures exactly one market_date, MAX(run_id)
        per (ticker, market_date) picks the most recent renderable capture and
        avoids double-counting across full_scan + rescans.
        """
        sql = """
            WITH canonical AS (
                SELECT e.ticker, e.market_date, MAX(e.run_id) AS run_id
                  FROM exposures_by_expiry_strike e
                  JOIN scan_runs r ON r.run_id = e.run_id
                 WHERE r.status = 'ok'
                   AND r.aggregates IS NOT NULL
                   AND r.aggregates::text NOT IN ('{}', 'null')
                   AND (%(ticker)s::text IS NULL OR e.ticker = %(ticker)s::text)
                   AND (%(since)s::date IS NULL OR e.market_date >= %(since)s::date)
                 GROUP BY e.ticker, e.market_date
            )
            SELECT e.ticker,
                   e.market_date AS trade_date,
                   SUM(e.call_gex)::float8   AS call_gex,
                   SUM(e.put_gex)::float8    AS put_gex,
                   SUM(e.call_delta)::float8 AS call_delta,
                   SUM(e.put_delta)::float8  AS put_delta
              FROM exposures_by_expiry_strike e
              JOIN canonical c
                ON c.run_id = e.run_id
               AND c.ticker = e.ticker
               AND c.market_date = e.market_date
             GROUP BY e.ticker, e.market_date
             ORDER BY e.ticker, e.market_date
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, {"ticker": ticker, "since": since})
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def compare_to_stored(self, rederived: list[dict]) -> list[dict]:
        """For each re-derived row whose (ticker, trade_date) ALSO has a stored
        row, return the net_gex diff. Dates present in only one source are
        skipped (nothing to compare)."""
        if not rederived:
            return []
        out: list[dict] = []
        with self._conn.cursor() as cur:
            for r in rederived:
                # SUM(call_gex)/SUM(put_gex) are NULL when every contributing
                # strike was NULL — float(None) would crash the job. Nothing to
                # compare, so skip.
                if r.get("call_gex") is None or r.get("put_gex") is None:
                    continue
                cur.execute(
                    """
                    SELECT net_gex::float8 FROM greek_exposure_daily
                     WHERE ticker = %s AND trade_date = %s
                    """,
                    (r["ticker"], r["trade_date"]),
                )
                hit = cur.fetchone()
                if hit is None or hit[0] is None:
                    continue
                stored = float(hit[0])
                rederived_net = float(r["call_gex"]) + float(r["put_gex"])
                abs_diff = abs(rederived_net - stored)
                pct = abs_diff / abs(stored) if stored else None
                out.append(
                    {
                        "ticker": r["ticker"],
                        "trade_date": r["trade_date"],
                        "rederived_net_gex": rederived_net,
                        "stored_net_gex": stored,
                        "abs_diff": abs_diff,
                        "pct_diff": pct,
                    }
                )
        return out

    def insert_validation_rows(self, run_date: date, diffs: list[dict]) -> int:
        if not diffs:
            return 0
        sql = """
            INSERT INTO greek_rederive_validation
                (run_date, ticker, trade_date, rederived_net_gex,
                 stored_net_gex, abs_diff, pct_diff)
            VALUES (%(run_date)s, %(ticker)s, %(trade_date)s,
                    %(rederived_net_gex)s, %(stored_net_gex)s,
                    %(abs_diff)s, %(pct_diff)s)
            ON CONFLICT (run_date, ticker, trade_date) DO UPDATE SET
                rederived_net_gex = EXCLUDED.rederived_net_gex,
                stored_net_gex    = EXCLUDED.stored_net_gex,
                abs_diff          = EXCLUDED.abs_diff,
                pct_diff          = EXCLUDED.pct_diff
        """
        params = [{"run_date": run_date, **d} for d in diffs]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)
