"""Full-scan run bookkeeping over scan_runs (not per-ticker scan results)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg


class _ScanResultsMixin:
    _conn: psycopg.Connection
    _schema: str

    def get_last_full_scan_finished_at(self) -> datetime | None:
        """Latest scan_runs.finished_at where status='ok'. Used by /api/health."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT MAX(finished_at) FROM {self._schema}.scan_runs
                WHERE status='ok' AND finished_at IS NOT NULL
                  -- Full scans only. Partial-write jobs (cockpit / gex / flow /
                  -- discovery / regime / positioning / intraday) carry a
                  -- non-empty notes tag; counting them here lets a fresh partial
                  -- run mask a stalled full_scan in /api/health (the SPX
                  -- coverage-gap incident). notes NULL/'' == the full_scan path.
                  AND (notes IS NULL OR notes = '')
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

    # ------------------------------------------------------------------
    # S3+: watchlist CRUD
    # ------------------------------------------------------------------
