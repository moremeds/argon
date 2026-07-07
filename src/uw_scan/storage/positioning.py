"""UW positioning snapshot persistence (M4 trade-framework).

One wide row per (ticker, snapshot_date) aggregating short interest/float,
analyst ratings, institutional ownership, insider flow, and earnings-reaction
history. See migrations/065_uw_positioning.sql for the column contract and
sources/normalize.py for the aggregation that produces each column.
"""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

# Column order is load-bearing: upsert_uw_positioning builds the params list in
# this exact order, so keep it in sync with the explicit kwargs below.
_COLUMNS: tuple[str, ...] = (
    "si_pct_float",
    "si_short_interest",
    "si_total_float",
    "si_days_to_cover",
    "si_shares_available",
    "si_fee_rate",
    "si_rebate_rate",
    "si_market_date",
    "analyst_buy",
    "analyst_hold",
    "analyst_sell",
    "analyst_target_avg",
    "analyst_target_hi",
    "analyst_target_lo",
    "inst_holder_count",
    "inst_total_value",
    "insider_buy_volume",
    "insider_sell_volume",
    "insider_net_flow",
    "earn_reactions_positive",
    "earn_reactions_total",
    "next_er_date",
)


class _PositioningMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_uw_positioning(
        self,
        *,
        ticker: str,
        snapshot_date: _date,
        si_pct_float: Decimal | None = None,
        si_short_interest: Decimal | None = None,
        si_total_float: Decimal | None = None,
        si_days_to_cover: Decimal | None = None,
        si_shares_available: Decimal | None = None,
        si_fee_rate: Decimal | None = None,
        si_rebate_rate: Decimal | None = None,
        si_market_date: _date | None = None,
        analyst_buy: int | None = None,
        analyst_hold: int | None = None,
        analyst_sell: int | None = None,
        analyst_target_avg: Decimal | None = None,
        analyst_target_hi: Decimal | None = None,
        analyst_target_lo: Decimal | None = None,
        inst_holder_count: int | None = None,
        inst_total_value: Decimal | None = None,
        insider_buy_volume: Decimal | None = None,
        insider_sell_volume: Decimal | None = None,
        insider_net_flow: Decimal | None = None,
        earn_reactions_positive: int | None = None,
        earn_reactions_total: int | None = None,
        next_er_date: _date | None = None,
        raw_jsonb: dict[str, Any] | None = None,
    ) -> None:
        col_list = ", ".join(_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_COLUMNS))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in _COLUMNS)
        sql = (
            f"INSERT INTO {self._schema}.uw_positioning "
            f"(ticker, snapshot_date, {col_list}, raw_jsonb, fetched_at) "
            f"VALUES (%s, %s, {placeholders}, %s, now()) "
            "ON CONFLICT (ticker, snapshot_date) DO UPDATE SET "
            f"{updates}, raw_jsonb=EXCLUDED.raw_jsonb, fetched_at=now()"
        )
        # Order MUST match _COLUMNS.
        params: list[Any] = [
            ticker.upper(),
            snapshot_date,
            si_pct_float,
            si_short_interest,
            si_total_float,
            si_days_to_cover,
            si_shares_available,
            si_fee_rate,
            si_rebate_rate,
            si_market_date,
            analyst_buy,
            analyst_hold,
            analyst_sell,
            analyst_target_avg,
            analyst_target_hi,
            analyst_target_lo,
            inst_holder_count,
            inst_total_value,
            insider_buy_volume,
            insider_sell_volume,
            insider_net_flow,
            earn_reactions_positive,
            earn_reactions_total,
            next_er_date,
            Jsonb(raw_jsonb) if raw_jsonb is not None else None,
        ]
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    def get_uw_positioning(self, ticker: str) -> dict[str, Any] | None:
        """Latest snapshot for a ticker as a column→value dict (None if absent)."""
        sql = (
            f"SELECT * FROM {self._schema}.uw_positioning "
            "WHERE ticker = %s ORDER BY snapshot_date DESC LIMIT 1"
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ticker.upper(),))
            return cur.fetchone()

    def list_uw_positioning_latest(self) -> list[dict[str, Any]]:
        """Latest positioning snapshot per active-watchlist ticker.

        One row per watchlist ticker (newest ``snapshot_date``), with the
        dashboard card's delayed ``spot`` joined on for implied-upside math.
        Read-only; feeds the positioning screener. The (ticker, snapshot_date)
        primary key backs the DISTINCT ON efficiently.
        """
        sql = (
            "SELECT DISTINCT ON (p.ticker) p.*, c.spot "
            f"FROM {self._schema}.uw_positioning p "
            f"JOIN {self._schema}.watchlist w "
            "  ON w.ticker = p.ticker AND w.removed_at IS NULL "
            f"LEFT JOIN {self._schema}.watchlist_card c ON c.ticker = p.ticker "
            "ORDER BY p.ticker, p.snapshot_date DESC"
        )
        with self._conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql)
            return list(cur.fetchall())
