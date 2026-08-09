"""Empirical option bid-ask spreads in VOL POINTS, from real IB NBBO.

`svi_residual_net_of_cost` sweeps an assumed spread because the surface archive
carries no bid/ask and UW 403s per-strike history — the historical spread is
unrecoverable. This supplies the missing anchor from the one place argon banks
real quotes: `vrp_macro_entry_quote`, whose `source='xenon_ib'` rows are live IB
NBBO captured 8x/day alongside that leg's IV and vega.

Spread in vol points is the multiplier-free invariant:

    spread_vp = (ask - bid) / vega_per_vol_point

`vrp_macro_entry_quote.vega` is stored per-SHARE per-1.00-vol (IB's per-1%-vol
value rescaled x100 — see the root CLAUDE.md), so vega_per_vol_point = vega/100
and spread_vp = 100 * (ask - bid) / vega. Both numerator and denominator are
per-share, so the contract multiplier cancels — this ratio is directly comparable
to the sweep's `spread_vp` axis.

CAVEAT: these legs are SPX puts. SPX is not SPY/QQQ/single-names, and this is a
~6-week window. It anchors the ORDER OF MAGNITUDE of a real index-option spread,
it does not measure the panel the backtest trades.

ZERO UW/IB calls — reads banked rows only.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.svi_residual_spread_anchor
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import numpy as np
import psycopg

from uw_scan.config import Settings

logger = logging.getLogger("spread_anchor")
logging.basicConfig(level=logging.INFO, format="%(message)s")

OUT = Path("docs/research/svi-surface-fit")
VEGA_PER_VOL_POINT_DIVISOR = 100.0  # stored per-1.00-vol -> per-1-vol-point
PCTILES = [10, 25, 50, 75, 90]

QUERY = """
SELECT q.as_of::date        AS d,
       q.leg,
       q.strike,
       q.nbbo_bid,
       q.nbbo_ask,
       q.iv,
       q.vega,
       q.und_spot,
       e.expiry
FROM vrp_macro_entry_quote q
JOIN vrp_macro_entry e USING (entry_id)
WHERE q.source = 'xenon_ib'
  AND q.nbbo_bid IS NOT NULL
  AND q.nbbo_ask IS NOT NULL
  AND q.nbbo_ask > q.nbbo_bid
  AND q.vega > 0
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    rows = []
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        cur.execute(QUERY)
        for d, leg, strike, bid, ask, iv, vega, spot, expiry in cur.fetchall():
            vega_vp = float(vega) / VEGA_PER_VOL_POINT_DIVISOR
            if vega_vp <= 0:
                continue
            spread_abs = float(ask) - float(bid)
            mid = (float(ask) + float(bid)) / 2.0
            rows.append(
                {
                    "date": d,
                    "leg": leg,
                    "strike": float(strike),
                    "expiry": expiry,
                    "dte": (expiry - d).days,
                    "bid": float(bid),
                    "ask": float(ask),
                    "mid": round(mid, 4),
                    "iv": float(iv) if iv is not None else None,
                    "vega_per_volpt": round(vega_vp, 4),
                    "spread_abs": round(spread_abs, 4),
                    "spread_vp": round(spread_abs / vega_vp, 4),
                    "spread_pct_of_mid": round(spread_abs / mid, 4)
                    if mid > 0
                    else None,
                    "moneyness": round(float(strike) / float(spot), 4)
                    if spot
                    else None,
                }
            )

    if not rows:
        logger.error("no xenon_ib NBBO rows with usable vega")
        return 1

    with (OUT / "spread_anchor_quotes.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    vp = np.array([r["spread_vp"] for r in rows], float)
    dates = sorted({r["date"] for r in rows})
    logger.info(
        "n=%d quotes  %s -> %s  (%d distinct dates)",
        len(vp),
        dates[0],
        dates[-1],
        len(dates),
    )
    logger.info("spread in VOL POINTS, all legs:")
    for p in PCTILES:
        logger.info("   p%-3d = %.3f vp", p, float(np.percentile(vp, p)))
    logger.info("   mean = %.3f vp", float(vp.mean()))

    summary = [
        {
            "bucket": "ALL",
            "n": len(vp),
            **{f"p{p}": round(float(np.percentile(vp, p)), 4) for p in PCTILES},
            "mean": round(float(vp.mean()), 4),
        }
    ]
    # short_* legs sit near the money, wing_* are further OTM — spreads differ a lot
    for bucket in sorted({r["leg"] for r in rows}):
        sub = np.array([r["spread_vp"] for r in rows if r["leg"] == bucket], float)
        if sub.size < 20:
            continue
        summary.append(
            {
                "bucket": bucket,
                "n": int(sub.size),
                **{f"p{p}": round(float(np.percentile(sub, p)), 4) for p in PCTILES},
                "mean": round(float(sub.mean()), 4),
            }
        )
        logger.info(
            "   %-13s n=%-5d p25=%.3f p50=%.3f p75=%.3f",
            bucket,
            sub.size,
            float(np.percentile(sub, 25)),
            float(np.percentile(sub, 50)),
            float(np.percentile(sub, 75)),
        )

    with (OUT / "spread_anchor_summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        w.writerows(summary)

    logger.info(
        "wrote %s (%d quotes) and %s",
        OUT / "spread_anchor_quotes.csv",
        len(rows),
        OUT / "spread_anchor_summary.csv",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
