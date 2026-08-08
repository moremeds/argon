"""Data loaders for the magnet-view research (spec 2026-08-08 §3.1).

Two price scales exist and must never be mixed:

    uw_scan.daily_ohlc              back-adjusted  -> use for RETURNS
    option_surface_grid_daily       as-traded      -> use for STRIKE selection

A ticker that split mid-window has a rescaled OHLC history against unrescaled
strikes; KORU's 20-for-1 put its close at ~$21 while its strikes still spanned
125..1900. load_as_traded_spot carries the strike-range guard that catches the
seam regardless of which source supplied the spot.

ATM IV comes from option_surface_grid_daily ONLY. iv_rank_history holds ~4
tickers per session and its obvious `market_date <= as_of ORDER BY DESC LIMIT 1`
lookup silently returns months-old readings.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

# Grid sessions store IV as either a decimal or a percent. Same threshold as
# theta_harvester_repository.load_atm_iv — keep them identical.
_PERCENT_THRESHOLD = 3.0


def normalize_iv(raw: float) -> float:
    """Grid IV to decimal. Mirrors theta_harvester_repository.load_atm_iv."""
    iv = float(raw)
    return iv / 100.0 if iv > _PERCENT_THRESHOLD else iv


def interp_atm_iv(
    near_iv: float, near_dte: int, far_iv: float, far_dte: int, target_dte: int
) -> float:
    """ATM IV at target_dte, interpolated linearly in TOTAL VARIANCE (sigma^2 * t).

    Not linear in vol: the term structure is steep at short DTE, and a 3-day IV
    read as a 7-day IV biases the calibrated shrink factor systematically. Total
    variance is the standard interpolation space because variance is additive in
    time under the model the cone assumes.
    """
    if target_dte <= 0:
        raise ValueError(f"target_dte must be positive, got {target_dte}")
    if near_dte == far_dte:
        return float(near_iv)
    w_near = near_iv**2 * near_dte
    w_far = far_iv**2 * far_dte
    frac = (target_dte - near_dte) / (far_dte - near_dte)
    w = w_near + frac * (w_far - w_near)
    if w <= 0:
        raise ValueError(f"interpolated total variance non-positive: {w}")
    return math.sqrt(w / target_dte)


def load_adjusted_closes(conn, ticker: str, schema: str = "uw_scan") -> pd.DataFrame:
    """Full back-adjusted OHLCV history, ascending by date.

    Back-adjusted is correct for RETURNS (the adjustment factor cancels in a
    ratio) and for ATR. It is wrong for anything compared against option strikes.
    """
    sql = f"""
        SELECT date, open, high, low, close, volume
          FROM {schema}.daily_ohlc
         WHERE ticker = %s AND close > 0
         ORDER BY date ASC
    """
    rows = conn.execute(sql, (ticker,)).fetchall()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_as_traded_spot(
    conn, ticker: str, as_of: date, schema: str = "uw_scan"
) -> float | None:
    """Session spot on the SAME scale as the chain's strikes, or None.

    Grid `underlying_spot` first, `daily_ohlc.close` second — the column is NULL
    for every session before 2026-06, so without the fallback five of seven
    months return nothing, which reads as "no data" rather than "no column".

    A spot outside the session's own strike range is REJECTED, not returned. A
    scale-mismatched spot is not a worse datapoint, it is a fabricated one.
    """
    sql = f"""
        WITH k AS (
            SELECT MIN(strike) AS lo, MAX(strike) AS hi,
                   MAX(underlying_spot) AS grid_spot
              FROM {schema}.option_surface_grid_daily
             WHERE ticker = %(t)s AND market_date = %(d)s
        )
        SELECT COALESCE(
                   k.grid_spot,
                   (SELECT close FROM {schema}.daily_ohlc
                     WHERE ticker = %(t)s AND date = %(d)s AND close > 0
                     LIMIT 1)
               ) AS spot,
               k.lo, k.hi
          FROM k
    """
    row = conn.execute(sql, {"t": ticker, "d": as_of}).fetchone()
    if not row or row[0] is None or row[1] is None or row[2] is None:
        return None
    spot, lo, hi = float(row[0]), float(row[1]), float(row[2])
    if not (lo <= spot <= hi):
        return None
    return spot


def load_expiry_iv_curve(
    conn, ticker: str, as_of: date, spot: float, schema: str = "uw_scan"
) -> list[tuple[int, float]]:
    """[(dte, atm_iv), ...] ascending, one point per listed expiry.

    Fetched ONCE per (ticker, session) and reused for every horizon. The per
    horizon query this replaces re-scanned the same grid partition for each of
    5d and 10d, doubling ~18k round trips for identical rows.
    """
    sql = f"""
        SELECT DISTINCT ON (expiry)
               expiry, (call_iv + put_iv) / 2.0 AS iv
          FROM {schema}.option_surface_grid_daily
         WHERE ticker = %(t)s AND market_date = %(d)s
           AND call_iv IS NOT NULL AND put_iv IS NOT NULL
           AND expiry > %(d)s
         ORDER BY expiry, abs(strike - %(s)s)
    """
    rows = conn.execute(sql, {"t": ticker, "d": as_of, "s": spot}).fetchall()
    pts = [
        (int((r[0] - as_of).days), normalize_iv(r[1])) for r in rows if r[1] is not None
    ]
    return sorted((d, iv) for d, iv in pts if d > 0 and iv > 0)


def atm_iv_at_horizon(curve: list[tuple[int, float]], target_dte: int) -> float | None:
    """ATM IV at target_dte, term-interpolated across the straddling expiries.

    Falls back to the single nearest expiry when only one side exists, and
    returns None when that expiry is more than 2x target_dte away or less than
    half of it — extrapolating a 5-day cone off a 90-day expiry is not a
    measurement.
    """
    if not curve:
        return None
    below = [p for p in curve if p[0] <= target_dte]
    above = [p for p in curve if p[0] >= target_dte]
    if below and above:
        near_dte, near_iv = below[-1]
        far_dte, far_iv = above[0]
        if near_dte == far_dte:
            return near_iv
        return interp_atm_iv(near_iv, near_dte, far_iv, far_dte, target_dte)

    only_dte, only_iv = below[-1] if below else above[0]
    if only_dte > 2 * target_dte or only_dte * 2 < target_dte:
        return None
    return only_iv
