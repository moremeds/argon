"""Standalone repository for the technical_daily domain (Technicals tab)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

_CORE_COLS = (
    "as_of",
    "open",
    "high",
    "low",
    "close",
    "volume",
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
# Derived per-session metrics stored as a JSONB blob per row (migration 102).
_METRIC_COLS = (
    "rv20",
    "rv20_z",
    "vol_of_vol",
    "skew60",
    "kurt60",
    "jerk20",
    "rsi_z",
    "rsi_slope5",
    "macd_slope3",
    "kin_slope20",
    "kin_slope50",
    "kin_slope200",
    "alignment",
    "fast_macd_hist_atr",
    "slow_macd_hist_atr",
    "fast_macd_line_atr",
    "fast_macd_signal_atr",
    "fast_macd_delta",
    "slow_macd_delta",
    "fast_macd_delta2",
    "fast_macd_norm",
    "slow_macd_norm",
)
_SERIES_COLS = _CORE_COLS  # back-compat alias


def series_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame from build_technical_series -> JSON/SQL-safe dicts (NaN/inf ->
    None, numpy scalars -> python). Includes core columns plus the derived
    metric columns (packed into a metrics JSONB on upsert)."""
    cols = [c for c in (*_CORE_COLS, *_METRIC_COLS) if c in df.columns]
    records: list[dict] = []
    for rec in df[cols].to_dict(orient="records"):
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
        params = []
        for r in rows:
            metrics = {k: r.get(k) for k in _METRIC_COLS if k in r}
            core = {k: r.get(k) for k in _CORE_COLS}
            if core.get("volume") is not None:
                core["volume"] = int(
                    round(core["volume"])
                )  # BIGINT col; pandas float64
            params.append({**core, "ticker": ticker.upper(), "metrics": Jsonb(metrics)})
        sql = """
            INSERT INTO technical_daily
                (ticker, as_of, open, high, low, close, volume, sma20, sma50,
                 sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime,
                 rsi14, macd_hist_atr, rs_ratio, metrics)
            VALUES
                (%(ticker)s, %(as_of)s, %(open)s, %(high)s, %(low)s, %(close)s,
                 %(volume)s, %(sma20)s, %(sma50)s, %(sma200)s, %(z_vs_200dma)s,
                 %(z_band)s, %(sma200_slope_ann)s, %(slope_regime)s, %(rsi14)s,
                 %(macd_hist_atr)s, %(rs_ratio)s, %(metrics)s)
            ON CONFLICT (ticker, as_of) DO UPDATE SET
                open             = EXCLUDED.open,
                high             = EXCLUDED.high,
                low              = EXCLUDED.low,
                close            = EXCLUDED.close,
                volume           = EXCLUDED.volume,
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
                metrics          = EXCLUDED.metrics,
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

    def fetch_series(self, ticker: str, *, limit: int = 1300) -> list[dict]:
        sql = """
            SELECT * FROM (
                SELECT as_of, open, high, low, close, volume, sma20, sma50,
                       sma200, z_vs_200dma, z_band, sma200_slope_ann,
                       slope_regime, rsi14, macd_hist_atr, rs_ratio, metrics,
                       detail, forward_returns
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
            SELECT ticker, as_of, open, high, low, close, volume, sma20, sma50,
                   sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime,
                   rsi14, macd_hist_atr, rs_ratio, bars_n, detail,
                   forward_returns
              FROM technical_daily
             WHERE ticker = %s
             -- Prefer the true computed-latest (the only row carrying detail);
             -- a stale future row from a regressed apex window has detail=NULL
             -- and must not shadow it.
             ORDER BY (detail IS NOT NULL) DESC, as_of DESC
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
