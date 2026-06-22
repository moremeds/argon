"""Persistence for the durable option-surface grid (and the IB-vs-UW IV canary)."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any, Iterable

import psycopg

# Greek/IV keys carried per row, in column order. Spot/source are passed separately.
_GRID_COLS: tuple[str, ...] = (
    "call_iv",
    "put_iv",
    "call_delta",
    "put_delta",
    "call_gamma",
    "put_gamma",
    "call_vega",
    "put_vega",
    "call_theta",
    "put_theta",
    "call_vanna",
    "put_vanna",
    "call_charm",
    "put_charm",
)


class _OptionSurfaceMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_option_surface_grid(
        self,
        ticker: str,
        market_date: _date,
        underlying_spot: Decimal | None,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        """Upsert a full-chain per-strike IV/greeks snapshot for (ticker, market_date).

        Plain upsert (NOT delete-then-insert): a partial re-run must only add/refresh,
        never erase already-captured strikes — the archive only grows. Returns rows seen.
        """
        t = ticker.upper()
        rows = list(rows)
        if not rows:
            return 0
        col_list = ", ".join(
            (
                "ticker",
                "market_date",
                "expiry",
                "strike",
                *_GRID_COLS,
                "underlying_spot",
                "source",
            )
        )
        n_values = 4 + len(_GRID_COLS) + 2  # ticker..strike + greeks + spot + source
        placeholders = ", ".join(["%s"] * n_values)
        set_clause = ", ".join(
            f"{c}=EXCLUDED.{c}" for c in (*_GRID_COLS, "underlying_spot", "source")
        )
        sql = (
            f"INSERT INTO {self._schema}.option_surface_grid_daily ({col_list}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (ticker, market_date, expiry, strike) DO UPDATE SET "
            f"{set_clause}, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    (
                        t,
                        market_date,
                        r["expiry"],
                        r["strike"],
                        *(r.get(c) for c in _GRID_COLS),
                        underlying_spot,
                        r.get("source", "uw_greeks"),
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def upsert_iv_source_validation(
        self,
        ticker: str,
        market_date: _date,
        expiry: _date,
        strike: Decimal,
        right: str,
        uw_iv: Decimal | None,
        ib_iv: Decimal | None,
    ) -> None:
        """Persist one IB-vs-UW IV comparison row. abs_diff is computed when both present."""
        abs_diff = (
            abs(uw_iv - ib_iv) if (uw_iv is not None and ib_iv is not None) else None
        )
        with self._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._schema}.iv_source_validation "
                '(ticker, market_date, expiry, strike, "right", uw_iv, ib_iv, abs_diff, inserted_at) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) "
                'ON CONFLICT (ticker, market_date, expiry, strike, "right") DO UPDATE SET '
                "uw_iv=EXCLUDED.uw_iv, ib_iv=EXCLUDED.ib_iv, abs_diff=EXCLUDED.abs_diff, inserted_at=now()",
                (
                    ticker.upper(),
                    market_date,
                    expiry,
                    strike,
                    right.upper(),
                    uw_iv,
                    ib_iv,
                    abs_diff,
                ),
            )

    def fetch_option_surface_atm_strike(
        self, ticker: str, market_date: _date, expiry: _date, spot: Decimal
    ) -> dict[str, Any] | None:
        """Strike nearest `spot` for (ticker, market_date, expiry) with its call/put IV.
        Source for the IB-vs-UW canary. None if no rows."""
        sql = (
            "SELECT strike, call_iv, put_iv "
            f"FROM {self._schema}.option_surface_grid_daily "
            "WHERE ticker=%s AND market_date=%s AND expiry=%s "
            "ORDER BY abs(strike - %s) ASC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date, expiry, spot))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))
