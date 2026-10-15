"""gold_factor_daily persistence (migration 162) and its input read.

Standalone functions over one connection, not a `Repository` mixin: repository.py is
closed to new query methods (root CLAUDE.md module-size rule).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd
import psycopg

from uw_scan.macro.gold_factor import INPUTS, PRICE_LEGS

COLS = (
    "obs_date", "a",
    "b_r", "b_r_lo95", "b_r_hi95",
    "b_d", "b_d_lo95", "b_d_hi95",
    "b_s", "b_s_lo95", "b_s_hi95",
    "explained_share", "raw_label", "published_label",
    "gold_change", "own_trailing_drift", "real_yield_part", "dollar_part", "haven_part",
    "unexplained_1", "unexplained_5", "unexplained_21",
    "real_yield_change_bp", "dollar_change_pct", "haven_change_pct",
)  # fmt: skip


def fetch_yields(conn: psycopg.Connection) -> pd.DataFrame:
    """Latest vintage of the FRED inputs (DFII10, DGS10), one column each, indexed by date.
    The price legs come from the lake (worker/jobs/gold_factor.py)."""
    ids = [s for s in INPUTS if s not in PRICE_LEGS]
    rows = conn.execute(
        """
        SELECT DISTINCT ON (series_id, obs_date) series_id, obs_date, value::float8
        FROM uw_scan.macro_series_daily
        WHERE series_id = ANY(%s)
        ORDER BY series_id, obs_date, as_of DESC
        """,
        (ids,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["series_id", "obs_date", "value"])
    wide = df.pivot(index="obs_date", columns="series_id", values="value")
    wide.index = pd.DatetimeIndex(wide.index)
    return wide.reindex(columns=ids)


def _clean(v: Any) -> Any:
    return None if isinstance(v, float) and math.isnan(v) else v


def upsert_rows(conn: psycopg.Connection, out: pd.DataFrame, computed_at: datetime) -> int:
    """Upsert every row of `gold_factor.compute` output; returns the row count."""
    body = COLS[1:]
    params = [
        (ts.date(), *(_clean(r[c]) for c in body), computed_at)
        for ts, r in out.iterrows()
    ]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in (*body, "computed_at"))
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO uw_scan.gold_factor_daily ({", ".join(COLS)}, computed_at)
            VALUES ({", ".join(["%s"] * (len(COLS) + 1))})
            ON CONFLICT (obs_date) DO UPDATE SET {sets}
            """,
            params,
        )
    return len(params)


def fetch_rows(conn: psycopg.Connection, *, from_date: date | None = None) -> list[dict[str, Any]]:
    cur = conn.execute(
        f"""
        SELECT {", ".join(COLS)}, computed_at FROM uw_scan.gold_factor_daily
        WHERE %(f)s::date IS NULL OR obs_date >= %(f)s::date
        ORDER BY obs_date
        """,
        {"f": from_date},
    )
    names = [c.name for c in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


DXY_COLS = (
    "obs_date", "dxy", "change_pct",
    "eurusd_part", "usdjpy_part", "gbpusd_part", "usdcad_part", "usdsek_part", "usdchf_part",
)  # fmt: skip


def upsert_dxy_rows(conn: psycopg.Connection, out: pd.DataFrame, computed_at: datetime) -> int:
    """Upsert every row of `gold_factor.dxy_daily` output; returns the row count."""
    body = DXY_COLS[1:]
    params = [(ts.date(), *(_clean(r[c]) for c in body), computed_at) for ts, r in out.iterrows()]
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in (*body, "computed_at"))
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO uw_scan.dxy_synthetic_daily ({", ".join(DXY_COLS)}, computed_at)
            VALUES ({", ".join(["%s"] * (len(DXY_COLS) + 1))})
            ON CONFLICT (obs_date) DO UPDATE SET {sets}
            """,
            params,
        )
    return len(params)


def fetch_dxy_rows(conn: psycopg.Connection, *, from_date: date | None = None) -> list[dict[str, Any]]:
    cur = conn.execute(
        f"""
        SELECT {", ".join(DXY_COLS)}, computed_at FROM uw_scan.dxy_synthetic_daily
        WHERE %(f)s::date IS NULL OR obs_date >= %(f)s::date
        ORDER BY obs_date
        """,
        {"f": from_date},
    )
    names = [c.name for c in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
