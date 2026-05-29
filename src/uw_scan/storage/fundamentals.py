"""Massive fundamentals snapshot persistence (M5 trade-framework).

One row per (ticker, period_end). See migrations/066_massive_fundamentals.sql
for the column contract and sources/massive_fundamentals.py for the field
provenance. Mirrors storage/positioning.py::_PositioningMixin.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# Column order is load-bearing: upsert builds the params list in this order.
_COLUMNS: tuple[str, ...] = (
    "fiscal_period",
    "filing_date",
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "gross_margin",
    "op_margin",
    "net_margin",
    "total_assets",
    "total_debt",
    "shareholders_equity",
    "diluted_shares",
    "operating_cash_flow",
    "investing_cash_flow",
    "fcf",
    "share_count_delta",
    "last_split_date",
    "last_split_ratio",
    "latest_dividend_amount",
    "latest_dividend_ex_date",
)


class _FundamentalsMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_massive_fundamentals(
        self,
        *,
        ticker: str,
        period_end: _date,
        fiscal_period: str | None = None,
        filing_date: _date | None = None,
        revenue: Decimal | None = None,
        gross_profit: Decimal | None = None,
        operating_income: Decimal | None = None,
        net_income: Decimal | None = None,
        gross_margin: Decimal | None = None,
        op_margin: Decimal | None = None,
        net_margin: Decimal | None = None,
        total_assets: Decimal | None = None,
        total_debt: Decimal | None = None,
        shareholders_equity: Decimal | None = None,
        diluted_shares: Decimal | None = None,
        operating_cash_flow: Decimal | None = None,
        investing_cash_flow: Decimal | None = None,
        fcf: Decimal | None = None,
        share_count_delta: Decimal | None = None,
        last_split_date: _date | None = None,
        last_split_ratio: Decimal | None = None,
        latest_dividend_amount: Decimal | None = None,
        latest_dividend_ex_date: _date | None = None,
        raw_jsonb: dict[str, Any] | None = None,
    ) -> None:
        col_list = ", ".join(_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_COLUMNS))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in _COLUMNS)
        sql = (
            f"INSERT INTO {self._schema}.massive_fundamentals "
            f"(ticker, period_end, {col_list}, raw_jsonb, fetched_at) "
            f"VALUES (%s, %s, {placeholders}, %s, now()) "
            "ON CONFLICT (ticker, period_end) DO UPDATE SET "
            f"{updates}, raw_jsonb=EXCLUDED.raw_jsonb, fetched_at=now()"
        )
        params: list[Any] = [
            ticker.upper(),
            period_end,
            fiscal_period,
            filing_date,
            revenue,
            gross_profit,
            operating_income,
            net_income,
            gross_margin,
            op_margin,
            net_margin,
            total_assets,
            total_debt,
            shareholders_equity,
            diluted_shares,
            operating_cash_flow,
            investing_cash_flow,
            fcf,
            share_count_delta,
            last_split_date,
            last_split_ratio,
            latest_dividend_amount,
            latest_dividend_ex_date,
            Jsonb(raw_jsonb) if raw_jsonb is not None else None,
        ]
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def get_massive_fundamentals(self, ticker: str) -> dict[str, Any] | None:
        """Latest period row for a ticker as a column→value dict (None if absent)."""
        sql = (
            f"SELECT * FROM {self._schema}.massive_fundamentals "
            "WHERE ticker = %s ORDER BY period_end DESC LIMIT 1"
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ticker.upper(),))
            return cur.fetchone()
