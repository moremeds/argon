"""Stage 1 — LEAP cheap-vol convergence gate (read-only: DB + apex bars, ZERO UW/IB).

Does a wide HV-minus-LEAP-ATM-IV entry gap predict the SAME contract's IV rising
over the next 20/40 trading days? Writes traces + prints the kill decision.

Primary metric = Fama-MacBeth cross-sectional IC on a SINGLE-NAME panel, with a
leave-one-ticker-out floor and an inline non-overlap binding-significance run.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

import httpx
import numpy as np
import psycopg

from scripts.research.leap_vega_alpha import (
    atm_iv,
    cross_sectional_ic,
    entry_gap,
    realized_vol,
    stage1_metrics,
)
from uw_scan.config import Settings

logger = logging.getLogger("leap_probe")
logging.basicConfig(level=logging.INFO, format="%(message)s")

LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
TARGET_DTE = 420
DTE_FLOOR = 365
HORIZONS = [20, 40]
THRESHOLDS = [0.10, 0.15, 0.20, 0.25]
DELTA_BAND = (0.05, 0.95)
# Asset-class tag for the panel split: ETF IV/HV/VRP dynamics differ structurally from
# single names, so a pooled cross-section can let asset class manufacture the IC.
ETFS = {"SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "TLT", "HYG", "GLD"}
APEX = "http://100.66.147.98:8322"
OUT = Path("docs/research/leap-vega-alpha")


def apex_closes(ticker: str, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    """Date->close from apex daily bars. Empty dict on any failure (logged)."""
    url = f"{APEX}/bars/{ticker}?timeframe=1d&start={start}&end={end}"
    try:
        r = httpx.get(url, timeout=15.0)
        r.raise_for_status()
        bars = r.json().get("bars", [])
    except Exception as exc:  # noqa: BLE001 - research probe, log and skip ticker
        logger.info("apex fail %s: %r", ticker, exc)
        return {}
    out = {}
    for b in bars:
        d = dt.date.fromisoformat(b["time"][:10])
        if b.get("close") is not None:
            out[d] = float(b["close"])
    return out


def hv_asof(
    closes_by_date: dict[dt.date, float], asof: dt.date, window: int
) -> float | None:
    series = [c for d, c in sorted(closes_by_date.items()) if d <= asof]
    if len(series) >= window + 1:
        tail = np.asarray(series[-(window + 1) :], dtype=float)
        if float(np.max(np.abs(np.diff(np.log(tail))))) > 0.35:
            return None  # likely unadjusted split in the window (codex #9 guard)
    return realized_vol(series, window)


def top_leap_tickers(cur, n: int) -> list[str]:
    cur.execute(
        "SELECT ticker, count(*) AS c FROM option_surface_grid_daily "
        "WHERE market_date=(SELECT max(market_date) FROM option_surface_grid_daily) "
        "AND (expiry-market_date) >= %s GROUP BY ticker ORDER BY c DESC LIMIT %s",
        (DTE_FLOOR, n),
    )
    return [r[0] for r in cur.fetchall()]


def leap_expiry(cur, ticker: str, mdate: dt.date) -> dt.date | None:
    cur.execute(
        "SELECT expiry FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND (expiry-market_date) >= %s "
        "ORDER BY abs((expiry-market_date) - %s) LIMIT 1",
        (ticker, mdate, DTE_FLOOR, TARGET_DTE),
    )
    row = cur.fetchone()
    return row[0] if row else None


def atm_rows(cur, ticker: str, mdate: dt.date, expiry: dt.date) -> list[dict]:
    cur.execute(
        "SELECT strike, call_iv, call_delta FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND expiry=%s ORDER BY strike",
        (ticker, mdate, expiry),
    )
    lo, hi = DELTA_BAND
    return [
        {
            "strike": s,
            "call_iv": (float(c) if c is not None else None),
            "call_delta": (float(d) if d is not None else None),
        }
        for s, c, d in cur.fetchall()
        if d is not None and lo <= float(d) <= hi
    ]


def iv_on(cur, ticker: str, expiry: dt.date, strike, mdate: dt.date) -> float | None:
    cur.execute(
        "SELECT call_iv FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND strike=%s AND market_date=%s",
        (ticker, expiry, strike, mdate),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    obs: list[dict] = []
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        panel = list(dict.fromkeys(LIQUID + top_leap_tickers(cur, 10)))
        logger.info("panel: %s", panel)
        cur.execute(
            "SELECT DISTINCT market_date FROM option_surface_grid_daily ORDER BY market_date"
        )
        all_dates = [r[0] for r in cur.fetchall()]
        dmin, dmax = all_dates[0], all_dates[-1]
        for ticker in panel:
            closes = apex_closes(ticker, dmin - dt.timedelta(days=120), dmax)
            if not closes:
                continue
            cur.execute(
                "SELECT DISTINCT market_date FROM option_surface_grid_daily "
                "WHERE ticker=%s ORDER BY market_date",
                (ticker,),
            )
            tdates = [r[0] for r in cur.fetchall()]
            for i, mdate in enumerate(tdates):
                expiry = leap_expiry(cur, ticker, mdate)
                if expiry is None:
                    continue
                rows = atm_rows(cur, ticker, mdate, expiry)
                atm = atm_iv(rows)  # interpolated 50-delta -> the GAP (cheapness)
                if atm is None:
                    continue
                held = min(rows, key=lambda r: abs(r["call_delta"] - 0.5))
                if abs(held["call_delta"] - 0.5) > 0.10 or held["call_iv"] is None:
                    continue  # coarse grid: no strike near ATM
                strike, entry_iv_fixed = held["strike"], float(held["call_iv"])
                hv20 = hv_asof(closes, mdate, 20)
                hv60 = hv_asof(closes, mdate, 60)
                gap = entry_gap(hv20, hv60, atm)
                if gap is None:
                    continue
                for h in HORIZONS:
                    j = i + h
                    if j >= len(tdates):
                        continue
                    fwd = iv_on(cur, ticker, expiry, strike, tdates[j])
                    if fwd is None:
                        continue
                    obs.append(
                        {
                            "ticker": ticker,
                            "asset_class": ("etf" if ticker in ETFS else "single_name"),
                            "market_date": mdate,
                            "expiry": expiry,
                            "strike": strike,
                            "dte": (expiry - mdate).days,
                            "hv20": hv20,
                            "hv60": hv60,
                            "atm_iv": atm,
                            "entry_iv_fixed": entry_iv_fixed,
                            "gap": round(gap, 5),
                            "horizon": h,
                            "iv_fwd": fwd,
                            # HELD-CONTRACT mark change (tradable) on the fixed strike — not
                            # the interpolated-ATM convergence. As spot drifts this mixes vol
                            # repricing with moneyness migration; that's the real held P&L.
                            "d_iv": round(fwd - entry_iv_fixed, 5),
                            "entry_idx": i,
                        }
                    )
    _write_csv(OUT / "gap_observations.csv", obs)
    _summary_and_metrics(obs)
    return 0


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.info("no rows for %s", path)
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("wrote %s (%d rows)", path, len(rows))


def _loo_min_ic(rows: list[dict], thr: float) -> float:
    """Min single-name FM mean_ic after dropping each ticker once — kills the case
    where one ticker's persistent gap/ΔIV pattern carries the whole signal."""
    tickers = sorted({o["ticker"] for o in rows})
    if len(tickers) < 3:
        return float("nan")
    vals = [
        cross_sectional_ic([o for o in rows if o["ticker"] != tk], thr)["mean_ic"]
        for tk in tickers
    ]
    vals = [v for v in vals if not np.isnan(v)]
    return float(min(vals)) if vals else float("nan")


def _control_ics(sn_rows: list[dict]) -> dict:
    """Decompose the gap signal. gap = HV - IV, and d_iv = IV_fwd - IV share the entry-IV
    term with opposite signs, so IC(gap, d_iv) mechanically inherits a +var(IV)(1-rho)
    mean-reversion component that has NOTHING to do with HV. Compare:
      IC(gap)   -- the headline
      IC(-IV)   -- the pure IV mean-reversion null (buy whatever has low IV)
      IC(HV)    -- does realized vol add ANY incremental cross-sectional info?
    If IC(gap) ~= IC(-IV) and IC(HV) ~= 0, the 'edge' is mechanical, not radon's thesis.
    """

    def ic(signal):
        recs = [
            {"market_date": o["market_date"], "gap": signal(o), "d_iv": o["d_iv"]}
            for o in sn_rows
        ]
        return cross_sectional_ic(recs, 0.0)["mean_ic"]

    def hv_max(o):
        hvs = [x for x in (o["hv20"], o["hv60"]) if x is not None]
        return max(hvs) if hvs else 0.0

    return {
        "gap": ic(lambda o: o["gap"]),
        "neg_iv": ic(lambda o: -o["atm_iv"]),
        "hv_only": ic(hv_max),
    }


def _summary_and_metrics(obs: list[dict]) -> None:
    metric_rows: list[dict] = []
    for h in HORIZONS:
        sub = [o for o in obs if o["horizon"] == h]
        if len(sub) < 2:
            logger.info("h=%d: under-powered (%d pairs)", h, len(sub))
            continue
        gaps = [o["gap"] for o in sub]
        d_ivs = [o["d_iv"] for o in sub]
        # sanity gates
        ivs = [o["atm_iv"] for o in sub]
        if not all(0.05 <= v <= 3.0 for v in ivs):
            logger.info("WARN h=%d: IV out of plausible band", h)
        if np.std(d_ivs) == 0:
            logger.info("WARN h=%d: degenerate ΔIV (std=0)", h)
        if len(sub) < 200:
            logger.info("WARN h=%d: only %d pairs (<200) — under-powered", h, len(sub))
        sn_all = [o for o in sub if o["asset_class"] == "single_name"]
        etf_all = [o for o in sub if o["asset_class"] == "etf"]
        ctrl = _control_ics(sn_all)  # mean-reversion decomposition (the decider)
        logger.info(
            "h=%d CONTROL single-name FM_IC | gap=%.3f | -IV(mean-rev null)=%.3f | HV-only=%.3f "
            "=> HV incremental=%.3f",
            h,
            ctrl["gap"],
            ctrl["neg_iv"],
            ctrl["hv_only"],
            ctrl["gap"] - ctrl["neg_iv"],
        )
        for thr in THRESHOLDS:
            m = stage1_metrics(gaps, d_ivs, thr)  # confounded pooled (secondary)
            fm = cross_sectional_ic(sub, thr)  # pooled FM
            fm_sn = cross_sectional_ic(sn_all, thr)  # single-name FM = the GATED panel
            fm_etf = cross_sectional_ic(etf_all, thr)  # ETF FM (context only)
            # non-overlap on single names = the BINDING significance (near-independent dates)
            sn_nonov = [o for o in sn_all if o["entry_idx"] % h == 0]
            fm_sn_no = cross_sectional_ic(sn_nonov, thr)
            loo = _loo_min_ic(sn_all, thr)  # drop-one-ticker robustness (min IC)
            m.update(
                horizon=h,
                threshold=thr,
                **{f"fm_{k}": v for k, v in fm.items()},
                fm_ic_sn=fm_sn["mean_ic"],
                fm_t_sn=fm_sn["ic_t_stat"],
                fm_ic_sn_nonoverlap=fm_sn_no["mean_ic"],
                fm_nd_sn_nonoverlap=fm_sn_no["n_dates"],
                fm_ic_etf=fm_etf["mean_ic"],
                loo_min_ic_sn=loo,
                ctrl_ic_gap=ctrl["gap"],
                ctrl_ic_neg_iv=ctrl["neg_iv"],
                ctrl_ic_hv_only=ctrl["hv_only"],
            )
            metric_rows.append(m)
            logger.info(
                "h=%d thr=%.2f | POOLED fm_ic=%.3f | SINGLE-NAME fm_ic=%.3f(t=%.2f) "
                "nonoverlap_ic=%.3f(nd=%d) loo_min=%.3f | ETF fm_ic=%.3f | diff_harvest=%.4f",
                h,
                thr,
                fm["mean_ic"],
                fm_sn["mean_ic"],
                fm_sn["ic_t_stat"],
                fm_sn_no["mean_ic"],
                fm_sn_no["n_dates"],
                loo,
                fm_etf["mean_ic"],
                fm["mean_diff_harvest"],
            )
    _write_csv(OUT / "convergence_metrics.csv", metric_rows)


if __name__ == "__main__":
    raise SystemExit(main())
