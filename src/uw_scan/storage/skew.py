"""Skew First-Principles persistence (snapshots + directional verdicts)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date as _date
from functools import partial
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

# read_json now embeds structure_detail with Decimal strikes/deltas and date expiries;
# the default json encoder raises on those, so coerce them to str for JSONB. The
# in-memory read dict used to build the typed response is unaffected (only the persisted
# JSON is stringified, and nothing reads structure_detail back from the persisted JSON).
_json_safe_dumps = partial(json.dumps, default=str)

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
                Jsonb(r.get(c), dumps=_json_safe_dumps)
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

    def upsert_skew_rv_reversion_verdict(
        self,
        *,
        asset_class: str,
        deviation_class: str,
        tail: str,
        verdict: str,
        mean_drr: Any,
        mean_drr_holdout: Any,
        n: int,
        n_holdout: int,
        survives_walkforward: bool,
        survives_window_gate: bool,
        as_of: _date,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.skew_rv_reversion_verdicts "
            "(asset_class, deviation_class, tail, verdict, mean_drr, mean_drr_holdout, "
            " n, n_holdout, survives_walkforward, survives_window_gate, as_of, inserted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (asset_class, deviation_class, tail) DO UPDATE SET "
            "verdict=EXCLUDED.verdict, mean_drr=EXCLUDED.mean_drr, "
            "mean_drr_holdout=EXCLUDED.mean_drr_holdout, n=EXCLUDED.n, "
            "n_holdout=EXCLUDED.n_holdout, "
            "survives_walkforward=EXCLUDED.survives_walkforward, "
            "survives_window_gate=EXCLUDED.survives_window_gate, "
            "as_of=EXCLUDED.as_of, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    asset_class,
                    deviation_class,
                    tail,
                    verdict,
                    mean_drr,
                    mean_drr_holdout,
                    n,
                    n_holdout,
                    survives_walkforward,
                    survives_window_gate,
                    as_of,
                ),
            )

    def get_skew_rv_reversion_verdict(
        self, *, asset_class: str, deviation_class: str, tail: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.skew_rv_reversion_verdicts "
            "WHERE asset_class=%s AND deviation_class=%s AND tail=%s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (asset_class, deviation_class, tail))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def upsert_skew_swing_greeks(
        self, ticker: str, market_date: _date, rows: Iterable[dict[str, Any]]
    ) -> int:
        """Replace the swing-expiry per-strike greeks for (ticker, market_date).
        rows: dicts with expiry, strike, dte, call_delta, put_delta. Delete-then-insert
        so a re-run drops strikes that left the chain (clean daily snapshot)."""
        t = ticker.upper()
        rows = list(rows)
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.skew_swing_greeks "
                "WHERE ticker=%s AND market_date=%s",
                (t, market_date),
            )
            if not rows:
                return 0
            cur.executemany(
                f"INSERT INTO {self._schema}.skew_swing_greeks "
                "(ticker, market_date, expiry, strike, dte, call_delta, put_delta, "
                " inserted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (ticker, market_date, expiry, strike) DO UPDATE SET "
                "dte=EXCLUDED.dte, call_delta=EXCLUDED.call_delta, "
                "put_delta=EXCLUDED.put_delta, inserted_at=now()",
                [
                    (
                        t,
                        market_date,
                        r["expiry"],
                        r["strike"],
                        r.get("dte"),
                        r.get("call_delta"),
                        r.get("put_delta"),
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def fetch_latest_swing_greeks_by_strike(
        self, ticker: str, *, dte_lo: int = 21, dte_hi: int = 60
    ) -> list[dict[str, Any]]:
        """Swing-expiry per-strike greeks (incl. call/put delta) for the ticker's most
        recent market_date, within [dte_lo, dte_hi]. Source for skew strike-by-delta
        structure selection. Ordered by expiry, strike ASC. Empty list if none."""
        sql = (
            "SELECT expiry, strike, dte, call_delta, put_delta "
            f"FROM {self._schema}.skew_swing_greeks "
            "WHERE ticker = %s "
            "  AND market_date = ("
            f"    SELECT max(market_date) FROM {self._schema}.skew_swing_greeks "
            "      WHERE ticker = %s) "
            "  AND dte IS NOT NULL AND dte BETWEEN %s AND %s "
            "ORDER BY expiry ASC, strike ASC"
        )
        t = ticker.upper()
        with self._conn.cursor() as cur:
            cur.execute(sql, (t, t, dte_lo, dte_hi))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

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
