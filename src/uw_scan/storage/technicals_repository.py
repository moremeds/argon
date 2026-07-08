"""Standalone repository for the technical_daily domain (Technicals tab)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

_SERIES_COLS = (
    "as_of",
    "close",
    "sma20",
    "sma50",
    "sma200",
    "z_vs_200dma",
    "z_band",
    "sma200_slope_ann",
    "slope_regime",
    "rsi14",
    "macd_hist_atr",
    "rs_ratio",
)


def series_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame from build_technical_series -> JSON/SQL-safe dicts
    (NaN/inf -> None, numpy scalars -> python)."""
    records: list[dict] = []
    for rec in df[list(_SERIES_COLS)].to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for k, v in rec.items():
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                clean[k] = None
            elif isinstance(v, float):
                clean[k] = float(v)
            elif hasattr(v, "item"):  # numpy scalar
                item = v.item()
                clean[k] = (
                    None
                    if isinstance(item, float) and not math.isfinite(item)
                    else item
                )
            else:
                clean[k] = v
        records.append(clean)
    return records


class TechnicalsRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_series(self, ticker: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        params = [{**r, "ticker": ticker.upper()} for r in rows]
        sql = """
            INSERT INTO technical_daily
                (ticker, as_of, close, sma20, sma50, sma200, z_vs_200dma,
                 z_band, sma200_slope_ann, slope_regime, rsi14,
                 macd_hist_atr, rs_ratio)
            VALUES
                (%(ticker)s, %(as_of)s, %(close)s, %(sma20)s, %(sma50)s,
                 %(sma200)s, %(z_vs_200dma)s, %(z_band)s,
                 %(sma200_slope_ann)s, %(slope_regime)s, %(rsi14)s,
                 %(macd_hist_atr)s, %(rs_ratio)s)
            ON CONFLICT (ticker, as_of) DO UPDATE SET
                close            = EXCLUDED.close,
                sma20            = EXCLUDED.sma20,
                sma50            = EXCLUDED.sma50,
                sma200           = EXCLUDED.sma200,
                z_vs_200dma      = EXCLUDED.z_vs_200dma,
                z_band           = EXCLUDED.z_band,
                sma200_slope_ann = EXCLUDED.sma200_slope_ann,
                slope_regime     = EXCLUDED.slope_regime,
                rsi14            = EXCLUDED.rsi14,
                macd_hist_atr    = EXCLUDED.macd_hist_atr,
                rs_ratio         = EXCLUDED.rs_ratio,
                inserted_at      = now()
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def set_latest_detail(
        self, ticker: str, as_of: date, *, detail: dict, forward_returns: list[dict]
    ) -> None:
        t = ticker.upper()
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE technical_daily SET detail = NULL, forward_returns = NULL "
                "WHERE ticker = %s AND as_of <> %s AND detail IS NOT NULL",
                (t, as_of),
            )
            cur.execute(
                "UPDATE technical_daily SET detail = %s, forward_returns = %s, "
                "bars_n = %s WHERE ticker = %s AND as_of = %s",
                (Jsonb(detail), Jsonb(forward_returns), detail.get("bars_n"), t, as_of),
            )
        self._conn.commit()

    def fetch_series(self, ticker: str, *, limit: int = 504) -> list[dict]:
        sql = """
            SELECT * FROM (
                SELECT as_of, close, sma20, sma50, sma200, z_vs_200dma, z_band,
                       sma200_slope_ann, slope_regime, rsi14, macd_hist_atr,
                       rs_ratio, detail, forward_returns
                  FROM technical_daily
                 WHERE ticker = %s
                 ORDER BY as_of DESC
                 LIMIT %s
            ) t ORDER BY as_of ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), limit))
            cols = [c.name for c in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def fetch_latest(self, ticker: str) -> dict | None:
        sql = """
            SELECT ticker, as_of, close, sma20, sma50, sma200, z_vs_200dma,
                   z_band, sma200_slope_ann, slope_regime, rsi14,
                   macd_hist_atr, rs_ratio, bars_n, detail, forward_returns
              FROM technical_daily
             WHERE ticker = %s
             ORDER BY as_of DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description or []]
            return dict(zip(cols, row, strict=True))

    def fetch_latest_macd_all(self) -> list[dict]:
        sql = """
            SELECT DISTINCT ON (ticker) ticker, macd_hist_atr
              FROM technical_daily
             ORDER BY ticker, as_of DESC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)
            cols = [c.name for c in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
