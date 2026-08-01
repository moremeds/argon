"""Standalone repository for spx_density_forecast (v13 density cone shadow log).

Never extends storage/repository.py (standing rule). Also owns the two vol_index_daily
SPX reads the job needs (series build + settle), keeping the job free of raw SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_COLUMNS = (
    "as_of",
    "h",
    "target_date",
    "scored_horizon",
    "q05",
    "q10",
    "q25",
    "q50",
    "q75",
    "q90",
    "q95",
    "baseline_q05",
    "baseline_q10",
    "baseline_q25",
    "baseline_q50",
    "baseline_q75",
    "baseline_q90",
    "baseline_q95",
    "band80_width",
    "baseline_band80_width",
    "width_ratio",
    "anchor_close",
    "params_jsonb",
    "fallback_used",
    "origin",
    "provenance_jsonb",
    "density_bins_jsonb",
)


class SpxDensityRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(f"%({c})s" for c in _COLUMNS)
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in _COLUMNS if c not in ("as_of", "h")
        )
        sql = f"""
            INSERT INTO {self._schema}.spx_density_forecast ({cols})
            VALUES ({placeholders})
            ON CONFLICT (as_of, h) DO UPDATE SET {updates}
        """
        params = []
        for r in rows:
            p = {c: r.get(c) for c in _COLUMNS}
            p["params_jsonb"] = (
                Jsonb(r["params_jsonb"]) if r.get("params_jsonb") is not None else None
            )
            p["provenance_jsonb"] = Jsonb(r.get("provenance_jsonb") or {})
            bins = r.get("density_bins_jsonb")
            p["density_bins_jsonb"] = Jsonb(bins) if bins is not None else None
            params.append(p)
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(rows)

    def latest_as_of(self) -> date | None:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT MAX(as_of) FROM {self._schema}.spx_density_forecast")
            row = cur.fetchone()
        return row[0] if row else None

    def fetch_recent_as_ofs(self, limit: int) -> list[date]:
        sql = f"""
            SELECT DISTINCT as_of FROM {self._schema}.spx_density_forecast
            ORDER BY as_of DESC LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [r[0] for r in cur.fetchall()]

    def fetch_forecast(self, as_of: date) -> list[dict[str, Any]]:
        sql = f"""
            SELECT * FROM {self._schema}.spx_density_forecast
            WHERE as_of = %s ORDER BY h
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (as_of,)).fetchall()

    def fetch_unsettled(self) -> list[dict[str, Any]]:
        sql = f"""
            SELECT as_of, h, anchor_close, q10, q90
            FROM {self._schema}.spx_density_forecast
            WHERE realised_return IS NULL
            ORDER BY as_of, h
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql).fetchall()

    def settle(
        self,
        as_of: date,
        h: int,
        target_date: date,
        realised_return: float,
        inside_band80: bool,
    ) -> None:
        sql = f"""
            UPDATE {self._schema}.spx_density_forecast
            SET target_date = %s, realised_return = %s, inside_band80 = %s
            WHERE as_of = %s AND h = %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (target_date, realised_return, inside_band80, as_of, h))
        self._conn.commit()

    def hit_rate_tally(self) -> list[dict[str, Any]]:
        # only v13-scored horizons count, split by origin (reconstructed is in-sample)
        sql = f"""
            SELECT origin,
                   COUNT(*) FILTER (WHERE inside_band80)::int AS inside,
                   COUNT(*)::int AS total
            FROM {self._schema}.spx_density_forecast
            WHERE inside_band80 IS NOT NULL AND scored_horizon
            GROUP BY origin
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql).fetchall()

    # --- vol_index_daily SPX reads (series build + settle pass) --------------------------

    def fetch_spx_series(self, first_date: date) -> list[tuple[date, float]]:
        sql = f"""
            SELECT trade_date, close::float8 FROM {self._schema}.vol_index_daily
            WHERE symbol = 'SPX' AND trade_date >= %s ORDER BY trade_date
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (first_date,))
            return [(r[0], r[1]) for r in cur.fetchall()]

    def fetch_spx_closes_after(
        self, after: date, limit: int
    ) -> list[tuple[date, float]]:
        sql = f"""
            SELECT trade_date, close::float8 FROM {self._schema}.vol_index_daily
            WHERE symbol = 'SPX' AND trade_date > %s ORDER BY trade_date LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (after, limit))
            return [(r[0], r[1]) for r in cur.fetchall()]

    def fetch_uw_gamma_levels(self, on_or_before: date) -> dict[str, Any] | None:
        """UW's own SPX dealer levels — the primary source for the chart overlay.
        Most recent session at or before `on_or_before`, so a stale capture degrades to
        an older (labelled) level rather than to nothing."""
        sql = f"""
            SELECT market_date, call_wall::float8 AS call_wall,
                   put_wall::float8 AS put_wall, gamma_flip::float8 AS gamma_flip,
                   spot::float8 AS spot
            FROM {self._schema}.uw_gex_levels_daily
            WHERE ticker = 'SPX' AND market_date <= %s
            ORDER BY market_date DESC LIMIT 1
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (on_or_before,)).fetchone()

    def fetch_gex_snapshot_levels(self, on_or_before: date) -> dict[str, Any] | None:
        """Fallback: the last intraday GEX snapshot of the most recent covered session.
        Column names are aliased to match the UW row so the resolver sees one shape."""
        sql = f"""
            SELECT data_date,
                   level_call_wall_strike::float8 AS call_wall,
                   level_put_wall_strike::float8  AS put_wall,
                   level_gex_flip_strike::float8  AS gamma_flip,
                   spot::float8 AS spot
            FROM {self._schema}.gex_snapshots
            WHERE ticker = 'SPX' AND data_date IS NOT NULL AND data_date <= %s
            ORDER BY data_date DESC, scanned_at DESC LIMIT 1
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            return cur.execute(sql, (on_or_before,)).fetchone()

    def fetch_spx_recent(self, n: int) -> list[dict[str, Any]]:
        """Recent SPX bars for the chart. open/high/low are nullable in vol_index_daily
        (close-only rows exist), so the candlestick renderer must tolerate NULLs — it
        drops those sessions from the candle series rather than inventing a bar."""
        sql = f"""
            SELECT trade_date,
                   open::float8  AS open,
                   high::float8  AS high,
                   low::float8   AS low,
                   close::float8 AS close
            FROM {self._schema}.vol_index_daily
            WHERE symbol = 'SPX' ORDER BY trade_date DESC LIMIT %s
        """
        with self._conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(sql, (n,)).fetchall()
        rows.reverse()
        return rows
