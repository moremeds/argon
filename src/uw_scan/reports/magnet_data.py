"""Data loaders for the magnet-view research (spec 2026-08-08 §3.1).

Two price scales exist and must never be mixed:

    uw_scan.daily_ohlc              back-adjusted* -> use for RETURNS
    option_surface_grid_daily       as-traded      -> use for STRIKE selection

*Unreliably. The table is the back-adjusted series in intent, but the livewire
`adj_close` problem lets raw corporate actions through — CRWD's 4:1 and KORU's
20:1 both sit unadjusted in it. Treat "back-adjusted" as the contract, not as a
guarantee, and run returns through `find_price_discontinuities` /
`trim_to_clean_segment` below before trusting them.

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

import numpy as np
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


# A one-session move of 2x or more is a corporate action, not a trade.
#
# Measured 2026-08-09 over all 151 grid tickers: single-day |log return| lands at
# 2.9501 (KORU 20:1), 1.9910 (SPCX 7.3x) and 1.3957 (CRWD 4:1), then nothing at
# all until 0.5428. ln(2) sits inside that 2.6x gap, so the cut is read off the
# data rather than picked. Everything below it is a real move and stays: KORU and
# SOXL are 3x leveraged ETFs, SNPS -36% (2025-09-10) and ORCL +36% (2025-09-10)
# are genuine sessions.
#
# These leak in because daily_ohlc is not reliably back-adjusted — the livewire
# adj_close problem. Three tickers set std(z)=1.1157 against MAD(z)=0.9129 and an
# excess kurtosis of 361; filtered (together with the E1 runner's calendar-span
# guard), the same 5d sample gives std 0.9748 / MAD 0.9126 and kurtosis 0.85.
SPLIT_LOG_RETURN = math.log(2.0)


def find_price_discontinuities(
    df: pd.DataFrame, threshold: float = SPLIT_LOG_RETURN
) -> set[date]:
    """Sessions whose one-day log return implies a corporate action.

    Returns the date the jump lands ON, so a forward window (t, t+h] is
    contaminated exactly when it contains one of these dates.

    Deliberately surgical: the caller drops the affected windows, not the whole
    ticker. Dropping every ticker that ever shows a large move discards 19.8% of
    the sample (23 of 119 tickers) to remove 0.2% of it.
    """
    if len(df) < 2:
        return set()
    px = df["close"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(px))
    # A NaN close yields a NaN return, which compares False here and is therefore
    # never flagged. That is the safe direction: the observation is unusable and
    # gets dropped downstream on its own rather than being called a split.
    dates = df["date"].tolist()
    return {dates[i + 1] for i in np.flatnonzero(np.abs(r) > threshold)}


def trim_to_clean_segment(
    df: pd.DataFrame, threshold: float = SPLIT_LOG_RETURN
) -> pd.DataFrame:
    """History from the last corporate action forward, reindexed from 0.

    For path-dependent work (ATR-ZigZag pivots, first-passage barriers) dropping
    individual windows is not enough: a fake 75% gap manufactures a pivot, and
    every leg built from it is wrong. The pre-action history has to go.

    Starts AT the jump bar, not after it — that bar's own OHLC is already on the
    new scale, only the return INTO it is fabricated.
    """
    jumps = find_price_discontinuities(df, threshold)
    if not jumps:
        return df
    return df[df["date"] >= max(jumps)].reset_index(drop=True)


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


def load_all_session_spots(
    conn, ticker: str, schema: str = "uw_scan"
) -> dict[date, float]:
    """{market_date: as-traded spot} for EVERY session, in one round trip.

    Bulk by design. The per-session equivalent issues one query per session per
    ticker — ~23k round trips across the watchlist, which at a 141 ms Tailscale
    RTT is about 90 minutes of pure latency. Same guards as load_as_traded_spot:
    grid spot first, daily_ohlc close as fallback (the column is NULL for every
    session before 2026-06), and a spot outside the session's own strike range is
    dropped rather than returned.
    """
    sql = f"""
        WITH k AS (
            SELECT market_date,
                   MIN(strike) AS lo,
                   MAX(strike) AS hi,
                   MAX(underlying_spot) AS grid_spot
              FROM {schema}.option_surface_grid_daily
             WHERE ticker = %(t)s
             GROUP BY market_date
        )
        SELECT k.market_date,
               COALESCE(k.grid_spot, o.close) AS spot,
               k.lo, k.hi
          FROM k
          LEFT JOIN {schema}.daily_ohlc o
                 ON o.ticker = %(t)s AND o.date = k.market_date AND o.close > 0
    """
    out: dict[date, float] = {}
    for md, spot, lo, hi in conn.execute(sql, {"t": ticker}).fetchall():
        if spot is None or lo is None or hi is None:
            continue
        s, lo_f, hi_f = float(spot), float(lo), float(hi)
        if lo_f <= s <= hi_f:
            out[md] = s
    return out


def load_all_expiry_iv_curves(
    conn, ticker: str, spots: dict[date, float], schema: str = "uw_scan"
) -> dict[date, list[tuple[int, float]]]:
    """{market_date: [(dte, atm_iv), ...]} for every session, in one round trip.

    The ATM strike is chosen per session against that session's own spot, which
    is passed in as a VALUES list rather than re-derived — the caller already
    applied the strike-range guard, and re-deriving here would risk the two
    disagreeing about which spot a session had.
    """
    if not spots:
        return {}
    values = ", ".join("(%s::date, %s::numeric)" for _ in spots)
    params: list = []
    for d, s in spots.items():
        params.extend([d, s])
    sql = f"""
        WITH s(market_date, spot) AS (VALUES {values})
        SELECT DISTINCT ON (g.market_date, g.expiry)
               g.market_date, g.expiry, (g.call_iv + g.put_iv) / 2.0 AS iv
          FROM {schema}.option_surface_grid_daily g
          JOIN s ON s.market_date = g.market_date
         WHERE g.ticker = %s
           AND g.call_iv IS NOT NULL AND g.put_iv IS NOT NULL
           AND g.expiry > g.market_date
         ORDER BY g.market_date, g.expiry, abs(g.strike - s.spot)
    """
    curves: dict[date, list[tuple[int, float]]] = {}
    for md, expiry, iv in conn.execute(sql, [*params, ticker]).fetchall():
        if iv is None:
            continue
        dte = int((expiry - md).days)
        v = normalize_iv(iv)
        if dte > 0 and v > 0:
            curves.setdefault(md, []).append((dte, v))
    for md in curves:
        curves[md].sort()
    return curves


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
