"""Skew First-Principles persistence (snapshots + directional verdicts)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_SNAP_COLUMNS: tuple[str, ...] = (
    "spot",
    "rr_25d",
    "skew_25d",
    "rr_z_180d",
    "rr_pct_252d",
    "deviation_class",
    "skew_term_class",
    "front_rr",
    "back_rr",
    "rho_spotvol_63d",
    "rho_spotvol_21d",
    "rho_sign",
    "drive_class",
    "asset_class",
    "class_expected_sign",
    "borrow_flag",
    "borrow_fee_rate",
    "days_to_cover",
    "earnings_gate",
    "regime",
    "directional_lean",
    "lean_confidence",
    "lean_basis",
    "read_summary",
    "read_json",
)


class _SkewMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_skew_analytics_snapshots(self, rows: Iterable[dict[str, Any]]) -> int:
        cols = ", ".join(_SNAP_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_SNAP_COLUMNS))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in _SNAP_COLUMNS)
        sql = (
            f"INSERT INTO {self._schema}.skew_analytics_snapshot "
            f"(ticker, market_date, basis, {cols}, inserted_at) "
            f"VALUES (%s, %s, %s, {placeholders}, now()) "
            "ON CONFLICT (ticker, market_date, basis) DO UPDATE SET "
            f"{updates}, inserted_at=now()"
        )
        params: list[tuple[Any, ...]] = []
        for r in rows:
            head = (r["ticker"], r["market_date"], r.get("basis", "eod"))
            tail = tuple(
                Jsonb(r.get(c))
                if c == "read_json" and r.get(c) is not None
                else r.get(c)
                for c in _SNAP_COLUMNS
            )
            params.append(head + tail)
        if not params:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def get_skew_analytics_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.skew_analytics_snapshot "
            "WHERE ticker = %s AND basis = 'eod' ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_skew_analytics_history(
        self, ticker: str, *, days: int = 400
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT * FROM {self._schema}.skew_analytics_snapshot "
            "WHERE ticker = %s AND basis = 'eod' "
            "  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_skew_directional_verdict(
        self,
        *,
        asset_class: str,
        deviation_class: str,
        drive_class: str,
        regime: str,
        verdict: str,
        confidence: str | None,
        forward_sep: Any,
        n: int,
        borrow_clean: bool,
        survives_gate: bool,
        as_of: _date,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.skew_directional_verdicts "
            "(asset_class, deviation_class, drive_class, regime, verdict, confidence, "
            " forward_sep, n, borrow_clean, survives_gate, as_of, inserted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (asset_class, deviation_class, drive_class, regime) DO UPDATE SET "
            "verdict=EXCLUDED.verdict, confidence=EXCLUDED.confidence, "
            "forward_sep=EXCLUDED.forward_sep, n=EXCLUDED.n, "
            "borrow_clean=EXCLUDED.borrow_clean, survives_gate=EXCLUDED.survives_gate, "
            "as_of=EXCLUDED.as_of, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    asset_class,
                    deviation_class,
                    drive_class,
                    regime,
                    verdict,
                    confidence,
                    forward_sep,
                    n,
                    borrow_clean,
                    survives_gate,
                    as_of,
                ),
            )

    def get_skew_directional_verdict(
        self, *, asset_class: str, deviation_class: str, drive_class: str, regime: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.skew_directional_verdicts "
            "WHERE asset_class=%s AND deviation_class=%s AND drive_class=%s AND regime=%s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (asset_class, deviation_class, drive_class, regime))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_latest_next_earnings_date(self, ticker: str) -> _date | None:
        sql = (
            f"SELECT next_earnings_date FROM {self._schema}.flow_events "
            "WHERE ticker = %s AND next_earnings_date IS NOT NULL "
            "ORDER BY inserted_at DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            return row[0] if row else None

    def fetch_watchlist_sector(self, ticker: str) -> str | None:
        """Active watchlist sector tag (20-tag taxonomy) for asset-class baseline.
        Real values incl. 'Macro' | 'Credit' | 'Sector-ETF' | 'M7' | 'SaaS' | ..."""
        sql = (
            f"SELECT sector FROM {self._schema}.watchlist "
            "WHERE ticker = %s AND removed_at IS NULL LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            return row[0] if row else None
