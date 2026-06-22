"""Corporate-action event store (VRP research expansion, item 1 support).

massive_fundamentals keeps only the LATEST split/dividend; split-adjusting a
multi-month price series needs every event, so this domain owns the full
per-event history. Also exposes fetch_distinct_vrp_tickers (the scoring
universe) so the ingestion job stays self-contained.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

import psycopg


class _CorporateActionsMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_corporate_action(
        self,
        *,
        ticker: str,
        event_type: str,
        event_date: _date,
        split_ratio: Decimal | None = None,
        cash_amount: Decimal | None = None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.corporate_actions "
            "(ticker, event_type, event_date, split_ratio, cash_amount) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, event_type, event_date) DO UPDATE SET "
            "split_ratio = EXCLUDED.split_ratio, cash_amount = EXCLUDED.cash_amount"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql, (ticker.upper(), event_type, event_date, split_ratio, cash_amount)
            )

    def fetch_corporate_actions(self, ticker: str) -> list[dict[str, Any]]:
        sql = (
            "SELECT event_type, event_date, split_ratio, cash_amount "
            f"FROM {self._schema}.corporate_actions WHERE ticker = %s "
            "ORDER BY event_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_distinct_vrp_tickers(self) -> list[str]:
        """The VRP scoring universe — every ticker with a vrp_daily panel. The
        corporate-action ingestion covers this ∪ active watchlist so every
        scored ticker has corp-action coverage (research-expansion ISSUE-9)."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT ticker FROM {self._schema}.vrp_daily ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]
