"""Full-scan universe and result persistence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import psycopg

from .. import models


def _scan_universe_params(
    run_id: int, tickers: Iterable[str], source: str
) -> list[tuple[Any, ...]]:
    return [(run_id, ticker.upper(), source) for ticker in tickers]


def _scan_result_params(
    run_id: int, rows: Iterable[models.ScanTickerResult]
) -> list[tuple[Any, ...]]:
    params: list[tuple[Any, ...]] = []
    for r in rows:
        sr = r.screener_row
        market_date = sr.date if sr is not None else None
        volatility = sr.volatility if sr is not None else None
        iv30d = sr.iv30d if sr is not None else None
        implied_move = sr.implied_move if sr is not None else None
        implied_move_perc = sr.implied_move_perc if sr is not None else None
        gex_ratio = sr.gex_ratio if sr is not None else None
        bullish_premium = sr.bullish_premium if sr is not None else None
        bearish_premium = sr.bearish_premium if sr is not None else None
        call_premium = sr.call_premium if sr is not None else None
        put_premium = sr.put_premium if sr is not None else None
        put_call_ratio = sr.put_call_ratio if sr is not None else None
        marketcap = sr.marketcap if sr is not None else None
        params.append(
            (
                run_id,
                r.ticker,
                market_date,
                r.setup_type,
                r.direction,
                r.score,
                r.net_call_premium,
                r.net_put_premium,
                r.net_premium,
                bullish_premium,
                bearish_premium,
                call_premium,
                put_premium,
                put_call_ratio,
                r.iv_rank,
                volatility,
                iv30d,
                implied_move,
                implied_move_perc,
                r.gex_net_change,
                gex_ratio,
                r.variance_risk_premium,
                r.total_open_interest,
                r.relative_volume,
                r.next_earnings_date,
                r.sector,
                marketcap,
                list(r.signals_present),
                list(r.confirmations),
                list(r.warnings),
                r.notes,
            )
        )
    return params


class _ScanResultsMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_scan_universe(
        self,
        run_id: int,
        tickers: Iterable[str],
        source: str = "hardcoded_s2",
    ) -> int:
        rows = _scan_universe_params(run_id, tickers, source)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.scan_universe (run_id, ticker, source) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (run_id, ticker) DO NOTHING"
        )
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def insert_scan_results(
        self,
        run_id: int,
        results: Iterable[models.ScanTickerResult],
    ) -> int:
        rows = list(results)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.scan_results ("
            "run_id, ticker, market_date, setup_type, direction, score, "
            "net_call_premium, net_put_premium, net_premium, "
            "bullish_premium, bearish_premium, call_premium, put_premium, "
            "put_call_ratio, iv_rank, volatility, iv30d, "
            "implied_move, implied_move_perc, "
            "gex_net_change, gex_ratio, variance_risk_premium, "
            "total_open_interest, relative_volume, next_earnings_date, "
            "sector, marketcap, "
            "signals_present, confirmations, warnings, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker) DO UPDATE SET "
            "setup_type=EXCLUDED.setup_type, direction=EXCLUDED.direction, "
            "score=EXCLUDED.score, signals_present=EXCLUDED.signals_present, "
            "confirmations=EXCLUDED.confirmations, warnings=EXCLUDED.warnings, "
            "notes=EXCLUDED.notes"
        )
        params = _scan_result_params(run_id, rows)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def fetch_scan_universe(self, run_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT ticker, source FROM {self._schema}.scan_universe "
            "WHERE run_id = %s ORDER BY ticker"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_scan_results(self, run_id: int) -> list[dict[str, Any]]:
        sql = (
            f"SELECT run_id, ticker, market_date, setup_type, direction, score, "
            "net_call_premium, net_put_premium, net_premium, "
            "bullish_premium, bearish_premium, call_premium, put_premium, "
            "put_call_ratio, iv_rank, volatility, iv30d, "
            "implied_move, implied_move_perc, "
            "gex_net_change, gex_ratio, variance_risk_premium, "
            "total_open_interest, relative_volume, next_earnings_date, "
            "sector, marketcap, "
            "signals_present, confirmations, warnings, notes "
            f"FROM {self._schema}.scan_results "
            "WHERE run_id = %s "
            "ORDER BY score DESC, ticker ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def get_last_full_scan_finished_at(self) -> datetime | None:
        """Latest scan_runs.finished_at where status='ok'. Used by /api/health."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(finished_at) FROM {self._schema}.scan_runs
                WHERE status='ok' AND finished_at IS NOT NULL
                """
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def list_runs_for_ticker(
        self, ticker: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return recent scan_runs rows for a ticker, newest first."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT run_id, started_at, finished_at, status
                FROM {self._schema}.scan_runs
                WHERE ticker = %s
                ORDER BY run_id DESC
                LIMIT %s
                """,
                (ticker.upper(), limit),
            )
            return [
                {
                    "run_id": int(row[0]),
                    "scanned_at": row[1],
                    "finished_at": row[2],
                    "status": row[3],
                }
                for row in cur.fetchall()
            ]

    def latest_scan_run_id(self) -> int:
        """Return the highest run_id that has scan_results rows, or 0 if none."""
        sql = (
            f"SELECT run_id FROM {self._schema}.scan_results "
            "ORDER BY run_id DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # S3+: watchlist CRUD
    # ------------------------------------------------------------------
