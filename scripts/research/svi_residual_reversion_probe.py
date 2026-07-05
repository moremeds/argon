"""Does an SVI fitted-vs-marked residual REVERT (i.e. is it a tradable dislocation)?

Reads banked option_surface_grid_daily (mini, read-only), fits raw-SVI per
(ticker, date, expiry), and tracks each strike's residual (marked_iv - fitted_iv,
vol pts) forward in time on the SAME contract. ZERO UW/IB calls.

The edge question is NOT "does the residual shrink" — pure measurement noise shrinks
mechanically (a +2vp fluke averages back toward 0) and you can't trade it. The decider
is PERSISTENCE: lag-1 autocorrelation of the residual. Low autocorr => the apparent
convergence harvest is a noise artifact, not edge. The entry-lag harvest (observe at i,
enter at i+1) is the clincher: if it collapses vs the contemporaneous harvest, the signal
is gone by the time you could trade it.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.svi_residual_reversion_probe
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg

from scripts.research.svi_fit import build_smile, fit_raw_svi, raw_svi_total_variance
from scripts.research.svi_surface_fit_probe import load_smile_rows
from uw_scan.config import Settings

logger = logging.getLogger("svi_reversion")
logging.basicConfig(level=logging.INFO, format="%(message)s")

LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
HORIZONS = [1, 2, 3, 5]  # observation-steps forward (≈ trading days)
MIN_OBS_DATES = 15  # a contract needs this many dates to form a series
TOP_EXPIRIES = 10  # per ticker, the best-observed expiries
DTE_LO, DTE_HI = 5, 120
BIG_VP = 1.0  # |residual| that a trade would target
OUT = Path("docs/research/svi-surface-fit")


def trackable_expiries(cur, ticker):
    cur.execute(
        "SELECT expiry, count(DISTINCT market_date) nd FROM option_surface_grid_daily "
        "WHERE ticker=%s AND (expiry-market_date) BETWEEN %s AND %s "
        "GROUP BY expiry HAVING count(DISTINCT market_date) >= %s "
        "ORDER BY nd DESC LIMIT %s",
        (ticker, DTE_LO, DTE_HI, MIN_OBS_DATES, TOP_EXPIRIES),
    )
    return [r[0] for r in cur.fetchall()]


def expiry_dates(cur, ticker, expiry):
    cur.execute(
        "SELECT DISTINCT market_date FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND (expiry-market_date) BETWEEN %s AND %s "
        "ORDER BY market_date",
        (ticker, expiry, DTE_LO, DTE_HI),
    )
    return [r[0] for r in cur.fetchall()]


def smile_residuals(cur, ticker, mdate, expiry) -> dict[float, float]:
    """{strike: residual_vol_pts} for one fitted smile; {} if it can't be fit."""
    rows, fwd = load_smile_rows(cur, ticker, mdate, expiry)
    if fwd is None or len(rows) < 8:
        return {}
    k, iv, w, t, strikes = build_smile(rows, fwd, mdate, expiry)
    if len(k) < 8 or t <= 0:
        return {}
    try:
        p, _ = fit_raw_svi(k, w)
    except Exception as exc:  # noqa: BLE001 - probe: a failed fit just drops the smile
        logger.debug("fit fail %s %s %s: %s", ticker, mdate, expiry, repr(exc))
        return {}
    iv_fit = np.sqrt(np.maximum(raw_svi_total_variance(k, p), 0.0) / t)
    resid_vp = (iv - iv_fit) * 100.0
    return {float(st): float(r) for st, r in zip(strikes, resid_vp)}


def _corr(a, b):
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _bucket_means(r0, rh, edges=(-2, -1, -0.5, 0.5, 1, 2)):
    """Mean forward residual rh, bucketed by signal r0 — shows rich/cheap convergence."""
    out = []
    lo = -1e9
    for hi in (*edges, 1e9):
        m = (r0 > lo) & (r0 <= hi)
        if m.sum() >= 20:
            out.append(
                (
                    f"({lo:+.1f},{hi:+.1f}]",
                    int(m.sum()),
                    round(float(r0[m].mean()), 3),
                    round(float(rh[m].mean()), 3),
                )
            )
        lo = hi
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    # pairs[h] = list of (r0, rh, gap_days); lag[h] = (r0_signal, r1_entry, r1h_exit)
    pairs: dict[int, list] = defaultdict(list)
    lag_pairs: list = []
    n_smiles = 0
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        for ticker in LIQUID:
            for expiry in trackable_expiries(cur, ticker):
                dates = expiry_dates(cur, ticker, expiry)
                # strike -> ordered [(date, resid)]
                series: dict[float, list] = defaultdict(list)
                for mdate in dates:
                    resid = smile_residuals(cur, ticker, mdate, expiry)
                    if resid:
                        n_smiles += 1
                    for strike, r in resid.items():
                        series[strike].append((mdate, r))
                for strike, seq in series.items():
                    seq.sort(key=lambda x: x[0])
                    n = len(seq)
                    for i in range(n):
                        for h in HORIZONS:
                            if i + h < n:
                                gap = (seq[i + h][0] - seq[i][0]).days
                                pairs[h].append((seq[i][1], seq[i + h][1], gap))
                        # entry-lag (h=1): signal at i, enter i+1, exit i+2
                        if i + 2 < n:
                            lag_pairs.append((seq[i][1], seq[i + 1][1], seq[i + 2][1]))
            logger.info("done %s  cumulative smiles=%d", ticker, n_smiles)

    metrics = []
    for h in HORIZONS:
        arr = np.array(pairs[h], float)
        if arr.size == 0:
            continue
        r0, rh, gap = arr[:, 0], arr[:, 1], arr[:, 2]
        autocorr = _corr(r0, rh)
        harvest = np.sign(r0) * (r0 - rh)  # fade the residual
        big = np.abs(r0) >= BIG_VP
        row = dict(
            horizon_steps=h,
            n_pairs=len(r0),
            median_gap_days=int(np.median(gap)),
            autocorr_r0_rh=round(autocorr, 4),
            harvest_mean_vp=round(float(harvest.mean()), 4),
            harvest_mean_vp_bigsig=round(float(harvest[big].mean()), 4)
            if big.any()
            else None,
            n_bigsig=int(big.sum()),
            resid_std_vp=round(float(r0.std()), 4),
        )
        metrics.append(row)
        logger.info(
            "h=%d n=%d gap=%dd  autocorr=%.3f  harvest=%.3f vp (big|r0|>=%.1f: %.3f, n=%d)",
            h,
            row["n_pairs"],
            row["median_gap_days"],
            autocorr,
            row["harvest_mean_vp"],
            BIG_VP,
            row["harvest_mean_vp_bigsig"] or float("nan"),
            row["n_bigsig"],
        )
        if h == 1:
            for b in _bucket_means(r0, rh):
                logger.info("    signal %s n=%d  mean r0=%.3f -> mean r+1=%.3f", *b)

    # entry-lag clincher (h=1 realized): signal at i, enter i+1, exit i+2. The strategy
    # only fires on |signal|>=BIG_VP, so the big-signal realized harvest is THE tradability
    # number — the full-population value is drowned by the near-zero majority.
    if lag_pairs:
        la = np.array(lag_pairs, float)
        sig, entry, exit_ = la[:, 0], la[:, 1], la[:, 2]
        harvest_contemp = np.sign(entry) * (entry - exit_)  # cheat: know entry resid
        harvest_lag = np.sign(sig) * (entry - exit_)  # realistic: signal is 1 step old
        big = np.abs(sig) >= BIG_VP
        lag_big = float(harvest_lag[big].mean()) if big.any() else float("nan")
        hit_big = float((harvest_lag[big] > 0).mean()) if big.any() else float("nan")
        logger.info(
            "ENTRY-LAG (h=1)  n=%d  contemp=%.3f vp  realized(1-step-old signal)=%.3f vp",
            len(sig),
            float(harvest_contemp.mean()),
            float(harvest_lag.mean()),
        )
        logger.info(
            "  realized on BIG signals |sig|>=%.1f: harvest=%.3f vp  hit-rate=%.1f%%  n=%d",
            BIG_VP,
            lag_big,
            100.0 * hit_big,
            int(big.sum()),
        )
        # threshold sweep: does a rarer/bigger dislocation harvest more (clear a spread)?
        for thr in (1.0, 1.5, 2.0, 2.5, 3.0):
            m = np.abs(sig) >= thr
            if m.sum() >= 50:
                logger.info(
                    "  realized |sig|>=%.1f: harvest=%.3f vp  hit=%.1f%%  n=%d (%.2f%% of pairs)",
                    thr,
                    float(harvest_lag[m].mean()),
                    100.0 * float((harvest_lag[m] > 0).mean()),
                    int(m.sum()),
                    100.0 * float(m.mean()),
                )
        metrics.append(
            dict(
                horizon_steps="lag1",
                n_pairs=len(sig),
                median_gap_days=None,
                autocorr_r0_rh=round(_corr(sig, entry), 4),
                harvest_mean_vp=round(float(harvest_lag.mean()), 4),
                harvest_mean_vp_bigsig=round(lag_big, 4),
                n_bigsig=int(big.sum()),
                resid_std_vp=round(float(sig.std()), 4),
            )
        )

    with (OUT / "reversion_metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(metrics[0].keys()))
        w.writeheader()
        w.writerows(metrics)
    logger.info(
        "wrote %s (%d rows); fitted %d smiles",
        OUT / "reversion_metrics.csv",
        len(metrics),
        n_smiles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
