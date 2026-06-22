"""VRP research-expansion persistence (items 1-5).

Owns: the historical earnings calendar (item 3, union of massive_fundamentals
filing_date + flow_events next_earnings_date), the raw price series for exact
forward RV, and the five result tables (validation / sector / multi-horizon /
directional / ΔVRP-reversion). Every result table is FULL-REWRITE per run
(clear_* then upsert_*) so dropped buckets never leave stale rows.

Design: docs/superpowers/plans/2026-06-22-vrp-research-expansion.md
"""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import psycopg

# filing_date proxies the earnings ANNOUNCEMENT by 0-14 days (8-K press release
# precedes the 10-Q filing), so filing-sourced events carry a 15-calendar-day
# backward buffer; flow_events.next_earnings_date is the announcement date → 0.
_FILING_BUFFER_DAYS = 15


class _VrpResearchMixin:
    _conn: psycopg.Connection
    _schema: str

    # ── earnings calendar (item 3) ───────────────────────────────────────────
    def fetch_historical_earnings_dates(self, ticker: str) -> set[_date]:
        """Historical earnings calendar = filing_date (massive_fundamentals,
        historical) ∪ next_earnings_date (flow_events, as-known-forward). A
        strict superset of the old flow-only set, so PAST earnings inside a
        (t,t+h] backtest window are no longer silently missed. Used by the
        single_name no-earnings skip guard (truthiness only)."""
        sql = (
            f"SELECT next_earnings_date AS d FROM {self._schema}.flow_events "
            "WHERE ticker = %s AND next_earnings_date IS NOT NULL "
            "UNION "
            f"SELECT filing_date AS d FROM {self._schema}.massive_fundamentals "
            "WHERE ticker = %s AND filing_date IS NOT NULL"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), ticker.upper()))
            return {row[0] for row in cur.fetchall()}

    def fetch_earnings_events(self, ticker: str) -> list[tuple[_date, int]]:
        """Earnings events as (event_date, back_buffer_days). flow_events dates
        carry buffer 0 (already the announcement date); filing dates carry
        _FILING_BUFFER_DAYS (covers the announcement preceding the filing). When
        a date appears in both, the flow (precise) buffer 0 wins. Consumed by the
        markout exclusion: an anchor is excluded if any [e-buffer, e] overlaps
        its forward window."""
        events: dict[_date, int] = {}
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT next_earnings_date FROM {self._schema}.flow_events "
                "WHERE ticker = %s AND next_earnings_date IS NOT NULL",
                (ticker.upper(),),
            )
            for (d,) in cur.fetchall():
                events[d] = 0
            cur.execute(
                f"SELECT filing_date FROM {self._schema}.massive_fundamentals "
                "WHERE ticker = %s AND filing_date IS NOT NULL",
                (ticker.upper(),),
            )
            for (d,) in cur.fetchall():
                events.setdefault(d, _FILING_BUFFER_DAYS)
        return sorted(events.items())

    # ── price series for exact forward RV ────────────────────────────────────
    def fetch_price_series(self, ticker: str) -> list[tuple[_date, float]]:
        """Raw daily close from realized_volatility_history (cast to float to
        match the existing skew_markout._price_series precedent). The report
        layer applies corporate-action adjustment via apply_split_adjustment."""
        sql = (
            "SELECT market_date, price "
            f"FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s AND price IS NOT NULL ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            return [(r[0], float(r[1])) for r in cur.fetchall()]

    # ── generic result-table helpers (DRY; identifiers are hardcoded, never
    #     user input — values always go through %s params) ─────────────────────
    def _vrp_clear(self, table: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._schema}.{table}")

    def _vrp_upsert(self, table: str, pk: tuple[str, ...], row: dict) -> None:
        cols = list(row.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk)
        sql = (
            f"INSERT INTO {self._schema}.{table} ({', '.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(pk)}) DO UPDATE SET {updates}"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))

    def _vrp_fetch(self, table: str, order: str) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {self._schema}.{table} ORDER BY {order}")
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    # ── item 1: RV validation ────────────────────────────────────────────────
    def clear_vrp_rv_validation(self) -> None:
        self._vrp_clear("vrp_rv_validation")

    def upsert_vrp_rv_validation(self, **row: Any) -> None:
        self._vrp_upsert("vrp_rv_validation", ("ticker", "horizon"), row)

    def fetch_vrp_rv_validation(self) -> list[dict[str, Any]]:
        return self._vrp_fetch("vrp_rv_validation", "ticker, horizon")

    # ── item 2: harvest by sector ────────────────────────────────────────────
    def clear_vrp_harvest_by_sector(self) -> None:
        self._vrp_clear("vrp_harvest_by_sector")

    def upsert_vrp_harvest_by_sector(self, **row: Any) -> None:
        self._vrp_upsert("vrp_harvest_by_sector", ("sector", "deviation_class"), row)

    def fetch_vrp_harvest_by_sector(self) -> list[dict[str, Any]]:
        return self._vrp_fetch("vrp_harvest_by_sector", "sector, deviation_class")

    # ── item 4: harvest multi-horizon ────────────────────────────────────────
    def clear_vrp_harvest_multihorizon(self) -> None:
        self._vrp_clear("vrp_harvest_multihorizon")

    def upsert_vrp_harvest_multihorizon(self, **row: Any) -> None:
        self._vrp_upsert(
            "vrp_harvest_multihorizon",
            ("asset_class", "deviation_class", "horizon"),
            row,
        )

    def fetch_vrp_harvest_multihorizon(self) -> list[dict[str, Any]]:
        return self._vrp_fetch(
            "vrp_harvest_multihorizon", "asset_class, deviation_class, horizon"
        )

    # ── item 5a: directional ─────────────────────────────────────────────────
    def clear_vrp_directional_verdicts(self) -> None:
        self._vrp_clear("vrp_directional_verdicts")

    def upsert_vrp_directional_verdict(self, **row: Any) -> None:
        self._vrp_upsert("vrp_directional_verdicts", ("asset_class", "horizon"), row)

    def fetch_vrp_directional_verdicts(self) -> list[dict[str, Any]]:
        return self._vrp_fetch("vrp_directional_verdicts", "asset_class, horizon")

    # ── item 5b: ΔVRP reversion ──────────────────────────────────────────────
    def clear_vrp_dvrp_reversion(self) -> None:
        self._vrp_clear("vrp_dvrp_reversion")

    def upsert_vrp_dvrp_reversion(self, **row: Any) -> None:
        self._vrp_upsert(
            "vrp_dvrp_reversion",
            ("asset_class", "deviation_class", "horizon"),
            row,
        )

    def fetch_vrp_dvrp_reversion(self) -> list[dict[str, Any]]:
        return self._vrp_fetch(
            "vrp_dvrp_reversion", "asset_class, deviation_class, horizon"
        )
