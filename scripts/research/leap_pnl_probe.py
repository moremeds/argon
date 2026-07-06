"""Stage 2 — forward vega-alpha P&L on Stage-1-flagged LEAP entries (read-only).

Reads gap_observations.csv, marks each flagged (gap >= FLAG_THRESHOLD) entry forward h
grid-rows on the SAME held contract, and decomposes per-share P&L:
    pnl_vega  = call_vega * ΔIV * 100   (grid vega is per-1%-vol -> ΔIV decimal * 100)
    pnl_delta = call_delta * ΔS         (directional; hedged, not harvested)
    pnl_theta = call_theta * days       (grid theta is per-DAY)
Units confirmed empirically (Task 5 Step 1): AAPL 1.2yr ATM vega=1.35 (per-1%), theta=-0.05
(per-day). The headline verdict — mean signed vega HARVEST in vol points vs a realistic
ATM-LEAP round-trip spread of ~1-5 vp — is vega-unit-INDEPENDENT (harvest_vp = ΔIV*100).
The $ split only decides whether the edge is vega or delta/skew migration (codex #4).

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

import numpy as np
import psycopg

from scripts.research.leap_convergence_probe import apex_closes
from uw_scan.config import Settings

logger = logging.getLogger("leap_pnl")
logging.basicConfig(level=logging.INFO, format="%(message)s")

OUT = Path("docs/research/leap-vega-alpha")
# Lowest gap threshold that passed the Stage-1 gate in BOTH horizons (all four passed).
FLAG_THRESHOLD = 0.10
VEGA_PER_PCT = (
    100.0  # grid vega is per-1%-vol; * ΔIV(decimal) * 100 -> $/share (Step 1)
)


def _greeks(cur, ticker, expiry, strike, mdate):
    cur.execute(
        "SELECT call_iv, call_delta, call_vega, call_theta FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND strike=%s AND market_date=%s",
        (ticker, expiry, strike, mdate),
    )
    r = cur.fetchone()
    if not r or any(v is None for v in r):
        return None
    return {
        "iv": float(r[0]),
        "delta": float(r[1]),
        "vega": float(r[2]),
        "theta": float(r[3]),
    }


def main() -> int:
    src = OUT / "gap_observations.csv"
    if not src.exists():
        logger.info("run Stage 1 first (%s missing)", src)
        return 1
    with src.open() as f:
        flagged = [r for r in csv.DictReader(f) if float(r["gap"]) >= FLAG_THRESHOLD]
    logger.info("flagged entries (gap >= %.2f): %d", FLAG_THRESHOLD, len(flagged))
    s = Settings.from_env()
    pnl_rows: list[dict] = []
    close_cache: dict[str, dict] = {}
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        tdates_cache: dict[str, list] = {}
        for r in flagged:
            tk, exp = r["ticker"], dt.date.fromisoformat(r["expiry"])
            strike = float(r["strike"])
            m0, h = dt.date.fromisoformat(r["market_date"]), int(r["horizon"])
            g0 = _greeks(cur, tk, exp, strike, m0)
            if g0 is None:
                continue
            if tk not in tdates_cache:
                cur.execute(
                    "SELECT DISTINCT market_date FROM option_surface_grid_daily "
                    "WHERE ticker=%s ORDER BY market_date",
                    (tk,),
                )
                tdates_cache[tk] = [x[0] for x in cur.fetchall()]
            tdates = tdates_cache[tk]
            if m0 not in tdates:
                continue
            j = tdates.index(m0) + h
            if j >= len(tdates):
                continue
            m1 = tdates[j]
            g1 = _greeks(cur, tk, exp, strike, m1)
            if g1 is None:
                continue
            if tk not in close_cache:
                close_cache[tk] = apex_closes(
                    tk, m0 - dt.timedelta(days=10), tdates[-1]
                )
            closes = close_cache[tk]
            if m0 not in closes or m1 not in closes:
                continue
            d_iv = g1["iv"] - g0["iv"]
            d_s = closes[m1] - closes[m0]
            n_days = (m1 - m0).days
            pnl_vega = g0["vega"] * d_iv * VEGA_PER_PCT
            pnl_delta = g0["delta"] * d_s
            pnl_theta = g0["theta"] * n_days
            gross = pnl_vega + pnl_delta + pnl_theta
            pnl_rows.append(
                {
                    "ticker": tk,
                    "asset_class": r.get("asset_class"),
                    "market_date": m0,
                    "expiry": exp,
                    "strike": strike,
                    "horizon": h,
                    "gap": r["gap"],
                    "d_iv": round(d_iv, 5),
                    "d_s": round(d_s, 4),
                    "pnl_vega": round(pnl_vega, 4),
                    "pnl_delta": round(pnl_delta, 4),
                    "pnl_theta": round(pnl_theta, 4),
                    "gross": round(gross, 4),
                    "vega": g0["vega"],
                    # Vega edge in VOL POINTS (long vega -> harvest = +ΔIV). Break-even
                    # round-trip spread = |harvest|; vega cancels -> vega-unit-free verdict.
                    "harvest_vp": round(d_iv * 100.0, 4),
                    "breakeven_spread_vp": round(abs(d_iv) * 100.0, 4),
                }
            )
    _write(pnl_rows)
    return 0


def _write(rows: list[dict]) -> None:
    if not rows:
        logger.info("no flagged P&L rows")
        return
    with (OUT / "pnl_metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("wrote %s (%d rows)", OUT / "pnl_metrics.csv", len(rows))

    def summarize(label: str, rs: list[dict]) -> None:
        if not rs:
            return
        harv = np.array([x["harvest_vp"] for x in rs])
        pv = np.array([x["pnl_vega"] for x in rs])
        pd_ = np.array([x["pnl_delta"] for x in rs])
        pt = np.array([x["pnl_theta"] for x in rs])
        gross = np.array([x["gross"] for x in rs])
        logger.info(
            "[%s] n=%d | mean harvest=%.2f vp | $/share vega=%.3f delta=%.3f theta=%.3f "
            "gross=%.3f | win%%=%.0f",
            label,
            len(rs),
            harv.mean(),
            pv.mean(),
            pd_.mean(),
            pt.mean(),
            gross.mean(),
            100 * (gross > 0).mean(),
        )

    for h in sorted({x["horizon"] for x in rows}):
        hr = [x for x in rows if x["horizon"] == h]
        summarize(f"h={h} ALL", hr)
        summarize(
            f"h={h} single-name", [x for x in hr if x["asset_class"] == "single_name"]
        )
        summarize(f"h={h} etf", [x for x in hr if x["asset_class"] == "etf"])
    # cost sensitivity: fraction of entries whose vega harvest clears a 1/2/5 vp round-trip spread
    harv = np.array([x["harvest_vp"] for x in rows])
    logger.info("mean signed vega harvest (all) = %.2f vp", float(harv.mean()))
    for sp in (1.0, 2.0, 5.0):
        logger.info(
            "  clears %.0f vp spread: %.0f%% of entries (net mean harvest %.2f vp)",
            sp,
            100 * (harv > sp).mean(),
            float((harv - sp).mean()),
        )


if __name__ == "__main__":
    raise SystemExit(main())
