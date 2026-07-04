"""SVI fit feasibility probe over banked option_surface_grid_daily (mini, read-only).

Fits raw-SVI to a real panel of smiles; reports RMSE (vol pts) + butterfly/calendar
violation rates; writes full traces. ZERO UW/IB calls.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.svi_surface_fit_probe
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg

from scripts.research.svi_fit import (
    build_smile,
    butterfly_g,
    calendar_violations,
    fit_raw_svi,
    forward_from_delta,
    raw_svi_total_variance,
    rmse_vol_points,
)
from uw_scan.config import Settings

logger = logging.getLogger("svi_probe")
logging.basicConfig(level=logging.INFO, format="%(message)s")

LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
TARGET_DTES = [7, 30, 90]
DTE_FLOOR = 5
N_DATES = 10
# Fit the tradable smile only: 5-delta put .. 5-delta call. Deep wings in the grid
# carry junk marks (e.g. an SPY strike at k=-5.3 marked 470% IV) that wreck the fit.
DELTA_BAND = (0.05, 0.95)
OUT = Path("docs/research/svi-surface-fit")


def thinnest_tickers(cur, n=2):
    """Data-driven 'illiquid' set: fewest strikes-per-expiry on the latest date."""
    cur.execute(
        "SELECT ticker, count(*)::float / count(DISTINCT expiry) AS spe "
        "FROM option_surface_grid_daily "
        "WHERE market_date=(SELECT max(market_date) FROM option_surface_grid_daily) "
        "GROUP BY ticker ORDER BY spe ASC LIMIT %s",
        (n,),
    )
    return [r[0] for r in cur.fetchall()]


def pick_dates(cur, ticker):
    cur.execute(
        "SELECT DISTINCT market_date FROM option_surface_grid_daily "
        "WHERE ticker=%s ORDER BY market_date",
        (ticker,),
    )
    all_d = [r[0] for r in cur.fetchall()]
    if len(all_d) <= N_DATES:
        return all_d
    idx = np.linspace(0, len(all_d) - 1, N_DATES).round().astype(int)
    return [all_d[i] for i in sorted(set(int(x) for x in idx))]


def nearest_expiries(cur, ticker, mdate):
    cur.execute(
        "SELECT DISTINCT expiry FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND (expiry - market_date) >= %s "
        "ORDER BY expiry",
        (ticker, mdate, DTE_FLOOR),
    )
    exps = [r[0] for r in cur.fetchall()]
    chosen = {}
    for tgt in TARGET_DTES:
        if not exps:
            break
        best = min(exps, key=lambda e: abs((e - mdate).days - tgt))
        chosen[best] = (best - mdate).days
    return chosen


def load_smile_rows(cur, ticker, mdate, expiry):
    """Rows (strike/call_iv/put_iv/call_delta) + forward anchor for one smile.

    Forward = the 50-delta strike (`underlying_spot` is NULL on ~96% of the grid, so
    it can't anchor k); real spot is only the last-resort fallback. Strikes are then
    clipped to DELTA_BAND so junk deep wings don't enter the fit.
    """
    cur.execute(
        "SELECT strike, call_iv, put_iv, call_delta, underlying_spot "
        "FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND expiry=%s ORDER BY strike",
        (ticker, mdate, expiry),
    )
    raw, strikes, cdeltas, spot = [], [], [], None
    for strike, civ, piv, cdelta, us in cur.fetchall():
        raw.append(
            {"strike": strike, "call_iv": civ, "put_iv": piv, "call_delta": cdelta}
        )
        strikes.append(strike)
        cdeltas.append(cdelta)
        if us is not None:
            spot = float(us)
    fwd = forward_from_delta(strikes, cdeltas, fallback=spot)
    lo, hi = DELTA_BAND
    rows = [
        r
        for r in raw
        if r["call_delta"] is not None and lo <= float(r["call_delta"]) <= hi
    ]
    return rows, fwd


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        logger.info("no rows for %s", path)
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("wrote %s (%d rows)", path, len(rows))


def _summary(rows: list[dict]):
    if not rows:
        logger.info("SUMMARY: no fits")
        return
    liq = [r for r in rows if r["liquid"]]
    rmse = np.array([r["rmse_volpts"] for r in liq]) if liq else np.array([np.nan])
    bfly = np.array([r["min_butterfly_g"] for r in rows])
    logger.info(
        "SUMMARY  smiles=%d liquid=%d  RMSE volpts p50=%.3f p90=%.3f",
        len(rows),
        len(liq),
        float(np.median(rmse)),
        float(np.percentile(rmse, 90)),
    )
    logger.info(
        "  butterfly violation rate (min g<0): %.1f%% of %d",
        100.0 * float((bfly < 0).mean()),
        len(bfly),
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    fits_rows: list[dict] = []
    overlay_rows: list[dict] = []
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        panel = LIQUID + thinnest_tickers(cur, 2)
        logger.info("panel: %s", panel)
        for ticker in panel:
            liquid = ticker in LIQUID
            for mdate in pick_dates(cur, ticker):
                fitted_for_cal = []
                start = len(fits_rows)
                for expiry, dte in nearest_expiries(cur, ticker, mdate).items():
                    rows, fwd = load_smile_rows(cur, ticker, mdate, expiry)
                    if fwd is None or len(rows) < 8:
                        continue
                    k, iv, w, t, strikes = build_smile(rows, fwd, mdate, expiry)
                    if len(k) < 8 or t <= 0:
                        continue
                    try:
                        p, _ = fit_raw_svi(k, w)
                    except Exception as exc:
                        logger.info("fit fail %s %s %s: %r", ticker, mdate, expiry, exc)
                        continue
                    gmin = float(
                        butterfly_g(np.linspace(k.min(), k.max(), 200), p).min()
                    )
                    fitted_for_cal.append((expiry, t, p))
                    fits_rows.append(
                        dict(
                            ticker=ticker,
                            market_date=mdate,
                            expiry=expiry,
                            dte=dte,
                            n_strikes=len(k),
                            a=p.a,
                            b=p.b,
                            rho=p.rho,
                            m=p.m,
                            sigma=p.sigma,
                            rmse_volpts=round(rmse_vol_points(k, iv, p, t), 4),
                            min_butterfly_g=round(gmin, 6),
                            liquid=liquid,
                        )
                    )
                    if abs(dte - 30) <= 10:  # eyeball overlay set = the ~30d expiry
                        iv_fit = np.sqrt(
                            np.maximum(raw_svi_total_variance(k, p), 0.0) / t
                        )
                        for st, kk, mi, fi in zip(strikes, k, iv, iv_fit):
                            overlay_rows.append(
                                dict(
                                    ticker=ticker,
                                    market_date=mdate,
                                    expiry=expiry,
                                    strike=st,
                                    k=round(float(kk), 5),
                                    iv_marked=round(float(mi), 5),
                                    iv_fit=round(float(fi), 5),
                                    resid_volpts=round(float((mi - fi) * 100.0), 4),
                                )
                            )
                cal = calendar_violations(fitted_for_cal)
                for fr in fits_rows[start:]:
                    fr["calendar_viol_on_date"] = cal
    _write_csv(OUT / "fits.csv", fits_rows)
    _write_csv(OUT / "overlays.csv", overlay_rows)
    render_figs(overlay_rows, OUT)
    _summary(fits_rows)
    return 0


def render_figs(overlay_rows: list[dict], out_dir: Path, max_figs: int = 8) -> None:
    """One marked-vs-fit PNG per ticker (latest date's ~30d smile), capped at max_figs."""
    if not overlay_rows:
        return
    plt.switch_backend("Agg")  # headless: render to file, no display
    groups: dict = defaultdict(list)
    for r in overlay_rows:
        groups[(r["ticker"], r["market_date"], r["expiry"])].append(r)
    latest: dict = {}
    for key in groups:
        tk, md, _ = key
        if tk not in latest or md > latest[tk][1]:
            latest[tk] = key
    (out_dir / "figs").mkdir(exist_ok=True)
    picked = list(latest.values())[:max_figs]
    for key in picked:
        pts = sorted(groups[key], key=lambda r: r["k"])
        ks = [p["k"] for p in pts]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(
            ks, [p["iv_marked"] for p in pts], s=12, color="#d62728", label="marked IV"
        )
        ax.plot(ks, [p["iv_fit"] for p in pts], color="#1f77b4", label="SVI fit")
        ax.set_xlabel("log-moneyness k")
        ax.set_ylabel("implied vol")
        ax.set_title(f"{key[0]} {key[1]} exp {key[2]}")
        ax.legend()
        fig.tight_layout()
        fname = f"{key[0]}_{key[1]}_{key[2]}.png".replace(" ", "")
        fig.savefig(out_dir / "figs" / fname, dpi=110)
        plt.close(fig)
    logger.info("wrote %d overlay figs to %s", len(picked), out_dir / "figs")


if __name__ == "__main__":
    raise SystemExit(main())
