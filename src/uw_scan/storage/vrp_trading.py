"""VRP tradable-layer persistence: candidates, backtest results/trades, paper
ledger, forward leg-NBBO. Self-contained generic upsert (identifiers hardcoded,
values always parameterized). Full-rewrite where noted; per-row commits are the
CALLER's responsibility (scheduler _repo() does not commit on close).

Design: docs/superpowers/plans/2026-06-22-vrp-tradable-condor-backtest.md
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import psycopg


class _VrpTradingMixin:
    _conn: psycopg.Connection
    _schema: str

    def _vt_upsert(self, table: str, pk: tuple[str, ...], row: dict) -> None:
        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk)
        sql = (
            f"INSERT INTO {self._schema}.{table} ({', '.join(cols)}) "
            f"VALUES ({placeholders}) ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {updates}"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))

    def _vt_fetch(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]

    # ── candidates ───────────────────────────────────────────────────────────
    def clear_vrp_candidates(self, as_of: _date) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.vrp_trade_candidates WHERE as_of = %s",
                (as_of,),
            )

    def upsert_vrp_candidate(self, **row: Any) -> None:
        self._vt_upsert("vrp_trade_candidates", ("ticker", "as_of"), row)

    def fetch_vrp_candidates(self, as_of: _date | None = None) -> list[dict[str, Any]]:
        if as_of is None:
            return self._vt_fetch(
                f"SELECT * FROM {self._schema}.vrp_trade_candidates "
                "WHERE as_of = (SELECT max(as_of) FROM "
                f"{self._schema}.vrp_trade_candidates) ORDER BY ticker"
            )
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_trade_candidates "
            "WHERE as_of = %s ORDER BY ticker",
            (as_of,),
        )

    def fetch_distinct_vrp_tickers(self) -> list[str]:
        # convenience mirror of vrp_markout._all_vrp_tickers for the trading layer
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT ticker FROM {self._schema}.vrp_daily ORDER BY ticker"
            )
            return [r[0] for r in cur.fetchall()]

    # ── backtest ─────────────────────────────────────────────────────────────
    def clear_vrp_backtest_results(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._schema}.vrp_backtest_results")

    def clear_vrp_backtest_trades(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._schema}.vrp_backtest_trades")

    def upsert_vrp_backtest_result(self, **row: Any) -> None:
        self._vt_upsert(
            "vrp_backtest_results",
            ("unit_type", "unit_key", "hold_days", "scope"),
            row,
        )

    def upsert_vrp_backtest_trade(self, **row: Any) -> None:
        self._vt_upsert(
            "vrp_backtest_trades", ("ticker", "entry_date", "hold_days"), row
        )

    def fetch_vrp_backtest_results(
        self, hold_days: int | None = None
    ) -> list[dict[str, Any]]:
        if hold_days is None:
            return self._vt_fetch(
                f"SELECT * FROM {self._schema}.vrp_backtest_results "
                "ORDER BY unit_type, unit_key, scope"
            )
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_backtest_results WHERE hold_days = %s "
            "ORDER BY unit_type, unit_key, scope",
            (hold_days,),
        )

    # ── macro short-vol sweep (research) ─────────────────────────────────────
    def clear_vrp_macro_sweep_results(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._schema}.vrp_macro_sweep_results")

    def upsert_vrp_macro_sweep_result(self, **row: Any) -> None:
        self._vt_upsert(
            "vrp_macro_sweep_results",
            ("ticker", "structure", "gate", "short_delta", "hold_days", "scope"),
            row,
        )

    def fetch_vrp_macro_sweep_results(self) -> list[dict[str, Any]]:
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_macro_sweep_results "
            "ORDER BY ticker, structure, gate, short_delta, hold_days, scope"
        )

    # ── paper ledger ─────────────────────────────────────────────────────────
    def open_vrp_paper_position(self, **row: Any) -> int | None:
        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        sql = (
            f"INSERT INTO {self._schema}.vrp_paper_positions ({', '.join(cols)}) "
            f"VALUES ({placeholders}) ON CONFLICT (ticker, opened_on) DO NOTHING "
            "RETURNING position_id"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))
            got = cur.fetchone()
        return int(got[0]) if got else None

    def fetch_open_vrp_paper_positions(self) -> list[dict[str, Any]]:
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_paper_positions WHERE status = 'open' "
            "ORDER BY opened_on, ticker"
        )

    def fetch_vrp_paper_positions(
        self, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status is None:
            return self._vt_fetch(
                f"SELECT * FROM {self._schema}.vrp_paper_positions "
                "ORDER BY opened_on DESC, ticker"
            )
        return self._vt_fetch(
            f"SELECT * FROM {self._schema}.vrp_paper_positions WHERE status = %s "
            "ORDER BY opened_on DESC, ticker",
            (status,),
        )

    def update_vrp_paper_mark(self, position_id: int, **fields: Any) -> None:
        sets = ", ".join(f"{k} = %s" for k in fields)
        sql = (
            f"UPDATE {self._schema}.vrp_paper_positions SET {sets}, updated_at = now() "
            "WHERE position_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (*fields.values(), position_id))

    def close_vrp_paper_position(self, position_id: int, **fields: Any) -> None:
        fields["status"] = "closed"
        sets = ", ".join(f"{k} = %s" for k in fields)
        sql = (
            f"UPDATE {self._schema}.vrp_paper_positions SET {sets}, updated_at = now() "
            "WHERE position_id = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (*fields.values(), position_id))

    # ── forward true-fill NBBO ───────────────────────────────────────────────
    def upsert_vrp_leg_nbbo(self, **row: Any) -> None:
        self._vt_upsert("vrp_leg_nbbo", ("position_id", "leg", "capture_date"), row)
