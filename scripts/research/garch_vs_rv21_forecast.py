#!/usr/bin/env python3
"""Stage A — vol-forecast horse race: GARCH(1,1) vs argon's trailing RV21 vs EWMA.

WHY
---
argon's VRP is ``vrp = iv - rv`` where ``rv`` is a *trailing 21d* realized vol
(``reports/volatility_series.py::_fill_rv_from_price``, window=21). The IV leg
looks ~30d FORWARD. That is a horizon mismatch: a backward window cannot know
that a vol spike mean-reverts, so ``vrp`` is mechanically depressed right after
any vol burst.

GARCH(1,1) is the minimal fix, because its h-step forecast decays a shock back
to the unconditional level at rate (alpha+beta)^h. The question this script
answers is narrow and decisive:

    Does a GARCH 21d-ahead forecast predict the NEXT 21 days of realized vol
    better than the trailing 21d realized vol argon uses today?

If no, the whole "GARCH-ify the VRP" idea dies here and we never touch the
signal layer. This stage deliberately uses NO implied-vol data, so it is not
limited to argon's thin 304-day IV panel — it runs on 15 years of prices and
therefore has ~60x the statistical power of the IV-window test.

ESTIMATORS (all produce an annualised vol in decimal, e.g. 0.153)
    rv21   trailing 21d stdev of log returns * sqrt(252)   <- argon TODAY
    ewma   RiskMetrics lambda=0.94, flat (IGARCH) forecast <- exponential weighting,
                                                              but NO mean reversion
    garch  GARCH(1,1)-t, params refit every REFIT_EVERY bars on an expanding
           window, conditional variance filtered forward daily between refits,
           then integrated 21 steps ahead and annualised

    The ewma leg is the control that isolates WHICH part of GARCH matters: if
    ewma alone closes the gap, the win is just recency weighting; only if garch
    beats ewma is mean reversion doing real work.

TARGET
    rv_fwd21(t) = stdev(r[t+1 .. t+21]) * sqrt(252)

LOSSES (both reported; QLIKE is the primary)
    QLIKE = log(s2_hat) + rv_fwd^2 / s2_hat      variance-proxy robust, lower better
    RMSE  on the vol scale                        interpretable, lower better
    also Spearman corr(forecast, rv_fwd21)

HONESTY
    * Walk-forward only. GARCH params at date t are fit on data <= t.
    * adj_close from the market-warehouse bronze lake, so splits are handled.
    * Overlapping 21d forward windows => obs are ~21x redundant. Significance is
      computed by BLOCK BOOTSTRAP over non-overlapping date blocks, never by a
      naive pooled t-test.

Reproduce:
    uv run python scripts/research/garch_vs_rv21_forecast.py --start 2010-01-01
    uv run python scripts/research/garch_vs_rv21_forecast.py --tickers SPY,NVDA --start 2015-01-01

Writes: <out-prefix>.per_obs.parquet   full per-(ticker,date) trace
        <out-prefix>.summary.json      machine-readable verdict
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

LAKE = "/Users/chenxi/market-warehouse/data-lake/bronze/asset_class=equity"
HORIZON = 21  # trading days ahead — matches UW's ~30 calendar-day IV
RV_WINDOW = 21  # argon's current trailing window
REFIT_EVERY = 63  # refit GARCH params quarterly; filter daily in between
MIN_FIT_OBS = 750  # ~3y burn-in before the first fit
MAX_FIT_OBS = 2500  # cap the expanding window (~10y) to bound fit cost
EWMA_LAMBDA = 0.94  # RiskMetrics
ANN = math.sqrt(252.0)
RNG = np.random.default_rng(20260729)


# ── data ──────────────────────────────────────────────────────────────────


def lake_tickers() -> list[str]:
    return sorted(
        d.split("=", 1)[1]
        for d in os.listdir(LAKE)
        if d.startswith("symbol=")
        and os.path.exists(os.path.join(LAKE, d, "1d.parquet"))
    )


def load_returns(ticker: str, start: str) -> pd.Series:
    """Daily log returns (decimal) from lake adj_close, indexed by trade_date."""
    path = os.path.join(LAKE, f"symbol={ticker}", "1d.parquet")
    df = pd.read_parquet(path, columns=["trade_date", "adj_close"])
    df = df.dropna(subset=["adj_close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df[df["adj_close"] > 0].sort_values("trade_date").set_index("trade_date")
    px = df["adj_close"].astype(float)
    # Keep some pre-`start` history so the GARCH burn-in does not eat the sample.
    r = np.log(px).diff().dropna()
    return r[r.index >= pd.Timestamp(start) - pd.Timedelta(days=365 * 12)]


# ── estimators ────────────────────────────────────────────────────────────


def ewma_var(r: np.ndarray, lam: float = EWMA_LAMBDA) -> np.ndarray:
    """RiskMetrics one-step-ahead variance. out[i] = forecast for bar i+1 using r[:i+1]."""
    out = np.empty(len(r))
    s2 = float(np.var(r[: min(len(r), 60)], ddof=1))
    for i, x in enumerate(r):
        s2 = lam * s2 + (1.0 - lam) * x * x
        out[i] = s2
    return out


def garch_integrated_vol(
    s2_next: float, omega: float, alpha: float, beta: float, h: int = HORIZON
) -> float:
    """Annualised vol implied by the h-step INTEGRATED GARCH(1,1) variance forecast.

    s2_{t+k} = sbar + (alpha+beta)^(k-1) * (s2_{t+1} - sbar),  sbar = omega/(1-alpha-beta)
    A shock therefore decays toward sbar — the property a trailing window cannot have.
    """
    persist = alpha + beta
    if persist >= 1.0 or persist <= 0.0:  # IGARCH / degenerate -> flat forecast
        return math.sqrt(max(s2_next, 1e-12) * 252.0)
    sbar = omega / (1.0 - persist)
    s2, total = s2_next, 0.0
    for _ in range(h):
        total += s2
        s2 = sbar + persist * (s2 - sbar)
    return math.sqrt(max(total / h, 1e-12) * 252.0)


@dataclass
class GarchParams:
    omega: float
    alpha: float
    beta: float
    ok: bool


def fit_garch(r_pct: np.ndarray) -> GarchParams:
    """GARCH(1,1) with Student-t innovations on returns in PERCENT units."""
    from arch import arch_model

    try:
        res = arch_model(
            r_pct, mean="Zero", vol="Garch", p=1, q=1, dist="t", rescale=False
        ).fit(disp="off", show_warning=False)
        p = res.params
        return GarchParams(
            float(p["omega"]), float(p["alpha[1]"]), float(p["beta[1]"]), True
        )
    except Exception:
        return GarchParams(0.0, 0.0, 0.0, False)


# ── per-ticker walk-forward ───────────────────────────────────────────────


def run_ticker(ticker: str, start: str) -> pd.DataFrame | None:
    r = load_returns(ticker, start)
    if len(r) < MIN_FIT_OBS + HORIZON + 60:
        return None

    dates = r.index
    rv = r.to_numpy()
    r_pct = rv * 100.0  # arch is happier on ~unit-scale data
    n = len(rv)

    # --- targets & the trailing-window baseline, vectorised -----------------
    s = pd.Series(rv)
    rv21_back = (s.rolling(RV_WINDOW).std(ddof=1) * ANN).to_numpy()
    # forward target: stdev of r[t+1 .. t+HORIZON]. Written as an explicit loop —
    # the shift/rolling one-liner is easy to get off-by-one and this runs once.
    rv_fwd = np.full(n, np.nan)
    for t in range(n - HORIZON):
        rv_fwd[t] = np.std(rv[t + 1 : t + 1 + HORIZON], ddof=1) * ANN

    # Halt / stale-padding detector. A vol FLOOR does not catch this: NBIS
    # (ex-Yandex, halted 2022-24) has stretches that are ~flat but not exactly
    # zero, so they survive a 1% floor and then blow up QLIKE's a^2/s^2 term.
    # Counting literally-zero returns targets the pathology directly.
    is_zero = (rv == 0.0).astype(float)
    zero_back = pd.Series(is_zero).rolling(RV_WINDOW).mean().to_numpy()
    zero_fwd = np.full(n, np.nan)
    for t in range(n - HORIZON):
        zero_fwd[t] = is_zero[t + 1 : t + 1 + HORIZON].mean()
    stale_frac = np.fmax(zero_back, zero_fwd)

    ew = ewma_var(rv)  # decimal variance, one-step-ahead
    ewma_vol = np.sqrt(ew * 252.0)  # IGARCH => flat term structure

    # --- GARCH walk-forward -------------------------------------------------
    garch_vol = np.full(n, np.nan)
    params = GarchParams(0.0, 0.0, 0.0, False)
    s2 = float(np.var(r_pct[:60], ddof=1))  # conditional var in PERCENT^2
    last_fit = -(10**9)

    for t in range(n):
        if t >= MIN_FIT_OBS and (t - last_fit) >= REFIT_EVERY:
            lo = max(0, t - MAX_FIT_OBS)
            new = fit_garch(r_pct[lo : t + 1])
            if new.ok:
                params = new
                last_fit = t
                # re-filter the conditional variance from the fit window start
                sbar_pct = (
                    params.omega / (1 - params.alpha - params.beta)
                    if 0 < params.alpha + params.beta < 1
                    else float(np.var(r_pct[lo : t + 1], ddof=1))
                )
                s2 = sbar_pct
                for x in r_pct[lo : t + 1]:
                    s2 = params.omega + params.alpha * x * x + params.beta * s2
        elif params.ok:
            # online filter: fold today's return into the conditional variance
            s2 = params.omega + params.alpha * r_pct[t] ** 2 + params.beta * s2

        if params.ok and t >= MIN_FIT_OBS:
            # s2 is the forecast for t+1, in PERCENT^2 -> back to decimal^2
            garch_vol[t] = garch_integrated_vol(
                s2 / 10000.0,
                params.omega / 10000.0,
                params.alpha,
                params.beta,
            )

    out = pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates,
            "rv21": rv21_back,
            "ewma": ewma_vol,
            "garch": garch_vol,
            "rv_fwd": rv_fwd,
            "stale_frac": stale_frac,
        }
    )
    out = out[out["date"] >= pd.Timestamp(start)]
    return out.dropna(subset=["rv21", "ewma", "garch", "rv_fwd"])


# ── scoring ───────────────────────────────────────────────────────────────


def qlike(fc_vol: np.ndarray, actual_vol: np.ndarray) -> np.ndarray:
    s2 = np.maximum(fc_vol, 1e-6) ** 2
    a2 = np.maximum(actual_vol, 1e-6) ** 2
    return np.log(s2) + a2 / s2


def block_bootstrap_delta(
    df: pd.DataFrame, col_a: str, col_b: str, n_boot: int = 2000
) -> dict:
    """Mean QLIKE(col_a) - QLIKE(col_b), CI by resampling NON-OVERLAPPING date blocks.

    Blocks are HORIZON days wide because the forward windows overlap that much;
    a naive pooled t-test would overstate significance by ~sqrt(21).
    """
    d = df.copy()
    d["q_a"] = qlike(d[col_a].to_numpy(), d["rv_fwd"].to_numpy())
    d["q_b"] = qlike(d[col_b].to_numpy(), d["rv_fwd"].to_numpy())
    d["delta"] = d["q_a"] - d["q_b"]
    d = d.sort_values("date")
    codes = pd.factorize(d["date"])[0]
    d["block"] = codes // HORIZON
    per_block = d.groupby("block")["delta"].mean().to_numpy()
    if len(per_block) < 5:
        return {"mean": float(np.mean(per_block)), "ci_lo": None, "ci_hi": None}
    draws = RNG.choice(per_block, size=(n_boot, len(per_block)), replace=True).mean(1)
    return {
        "mean": float(per_block.mean()),
        "ci_lo": float(np.percentile(draws, 2.5)),
        "ci_hi": float(np.percentile(draws, 97.5)),
        "p_worse_or_equal": float((draws >= 0).mean()),
        "n_blocks": int(len(per_block)),
    }


# 3% annualised. No liquid optionable US name forecasts or realises below this —
# TLT sits near 7%, a calm mega-cap near 10%. The floor catches TWO distinct
# pathologies with one rule:
#   (a) halted/stale bars, where rv21 and rv_fwd are literally 0 (NBIS, ex-Yandex,
#       halted 2022-24);
#   (b) POISONED GARCH FITS — the more dangerous one. A fit window containing a
#       long halt drives omega -> 0 and the conditional variance collapses; on
#       2024-11-25 NBIS forecast 0.0057% vol into a 135% realised move, and
#       QLIKE's a^2/s^2 term returned 5.6e8. That row's own `stale_frac` is 0.05:
#       the contamination lives in the fitted PARAMS, not in the current bar, so
#       no input-side filter can see it. Only 137 bars panel-wide, but they alone
#       decide whether the single-name verdict reads p=0.10 or p=0.00.
# PRODUCTION NOTE: this is a fallback policy, not data cleaning. A live system
# must floor the GARCH output and fall back to EWMA on rejection.
MIN_VOL = 0.03

# Index/sector ETFs in argon's universe. Split out because GARCH has no event
# term: single names carry scheduled earnings jumps it structurally cannot model,
# indices do not. The edge is expected to be LARGER on the ETF leg.
ETF_TICKERS = {
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "ARKK",
    "SMH",
    "GLD",
    "TLT",
    "HYG",
    "EEM",
    "FXI",
    "EWZ",
    "KRE",
    "XBI",
    "IBB",
    "XLE",
    "XLF",
    "VXX",
    "UVXY",
    "TQQQ",
    "SQQQ",
    "USO",
    "UNG",
    "EFA",
    "VTI",
    "LQD",
    "GDX",
    "XOP",
    "ITB",
    "JETS",
}


def filter_degenerate(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop bars where any leg is a non-market (halted / stale-padded closes).

    NBIS (ex-Yandex, halted 2022-24) and ANET contribute 21-day stretches of
    IDENTICAL closes -> rv == 0 -> QLIKE's a^2/s^2 term diverges and destroys the
    mean. 0.25% of rows, but they dominate an unfiltered average.
    """
    cols = ["rv21", "ewma", "garch", "rv_fwd"]
    keep = (df[cols] >= MIN_VOL).all(axis=1)
    return df[keep].copy(), int((~keep).sum())


def _core_score(df: pd.DataFrame) -> dict:
    res: dict = {
        "n_obs": int(len(df)),
        "n_tickers": int(df["ticker"].nunique()),
        "date_range": [str(df["date"].min().date()), str(df["date"].max().date())],
    }
    for c in ("rv21", "ewma", "garch"):
        q = qlike(df[c].to_numpy(), df["rv_fwd"].to_numpy())
        res[c] = {
            "qlike": float(np.mean(q)),
            "qlike_median": float(np.median(q)),  # robust check on the mean
            "rmse": float(np.sqrt(np.mean((df[c] - df["rv_fwd"]) ** 2))),
            "spearman": float(df[c].corr(df["rv_fwd"], method="spearman")),
            "mean_vol": float(df[c].mean()),
        }
    res["mean_rv_fwd"] = float(df["rv_fwd"].mean())
    res["garch_vs_rv21"] = block_bootstrap_delta(df, "garch", "rv21")
    res["garch_vs_ewma"] = block_bootstrap_delta(df, "garch", "ewma")
    res["ewma_vs_rv21"] = block_bootstrap_delta(df, "ewma", "rv21")
    return res


def score(df: pd.DataFrame) -> dict:
    df, n_dropped = filter_degenerate(df)
    res = _core_score(df)
    res["n_dropped_degenerate"] = n_dropped
    # Event-risk split: GARCH cannot model scheduled earnings jumps, so its edge
    # should be larger on ETFs than on single names. If it is not, suspect a bug.
    is_etf = df["ticker"].isin(ETF_TICKERS)
    if is_etf.any() and (~is_etf).any():
        res["by_kind"] = {
            "etf": _core_score(df[is_etf]),
            "single_name": _core_score(df[~is_etf]),
        }
    return res


# ── reporting ─────────────────────────────────────────────────────────────


def _print_block(tag: str, s: dict) -> None:
    print(
        f"\n{tag}  n={s['n_obs']:,}  {s['n_tickers']} tickers  {s['date_range']}",
        file=sys.stderr,
    )
    for c in ("rv21", "ewma", "garch"):
        m = s[c]
        print(
            f"  {c:6s} qlike={m['qlike']:+.5f} (med {m['qlike_median']:+.5f})  "
            f"rmse={m['rmse']:.5f}  spearman={m['spearman']:.4f}",
            file=sys.stderr,
        )
    for k in ("garch_vs_rv21", "garch_vs_ewma", "ewma_vs_rv21"):
        d = s[k]
        print(
            f"  {k:16s} dQLIKE={d['mean']:+.5f} "
            f"CI[{d['ci_lo']:+.5f},{d['ci_hi']:+.5f}] "
            f"p(no better)={d['p_worse_or_equal']:.3f} blocks={d['n_blocks']}",
            file=sys.stderr,
        )


def emit(df: pd.DataFrame, out_prefix: str) -> dict:
    summary = score(df)
    clean, _ = filter_degenerate(df)

    per_ticker = {}
    for t, g in clean.groupby("ticker"):
        if len(g) < 100:
            continue
        per_ticker[t] = {
            c: float(np.mean(qlike(g[c].to_numpy(), g["rv_fwd"].to_numpy())))
            for c in ("rv21", "ewma", "garch")
        }
    summary["per_ticker_qlike"] = per_ticker
    wins = sum(1 for v in per_ticker.values() if v["garch"] < v["rv21"])
    summary["garch_beats_rv21_ticker_count"] = [wins, len(per_ticker)]

    with open(f"{out_prefix}.summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 72, file=sys.stderr)
    print(
        f"QLIKE lower=better · dropped {summary['n_dropped_degenerate']} "
        f"degenerate bars (vol < {MIN_VOL:.0%})",
        file=sys.stderr,
    )
    _print_block("ALL", summary)
    for kind in ("etf", "single_name"):
        if "by_kind" in summary:
            _print_block(kind.upper(), summary["by_kind"][kind])
    print(f"\n  garch beats rv21 on {wins}/{len(per_ticker)} tickers", file=sys.stderr)
    print(f"✓ {out_prefix}.summary.json", file=sys.stderr)
    return summary


# ── main ──────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma list; default = argon IV universe ∩ lake")
    ap.add_argument("--start", default="2010-01-01", help="first TEST date")
    ap.add_argument("--dsn", default="dbname=option_wizard_local")
    ap.add_argument("--out-prefix", default="/tmp/garch_stage_a")
    ap.add_argument(
        "--rescore",
        help="re-score an existing .per_obs.parquet; skips the (slow) GARCH refits",
    )
    args = ap.parse_args()

    if args.rescore:
        df = pd.read_parquet(args.rescore)
        emit(df, args.out_prefix)
        return

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        import psycopg

        with psycopg.connect(args.dsn) as c:
            iv_syms = {
                r[0]
                for r in c.execute(
                    "select distinct ticker from uw_scan.realized_volatility_history "
                    "where implied_volatility is not null"
                )
            }
        tickers = sorted(iv_syms & set(lake_tickers()))

    print(f"Stage A: {len(tickers)} tickers, test from {args.start}", file=sys.stderr)
    frames = []
    for i, t in enumerate(tickers, 1):
        try:
            d = run_ticker(t, args.start)
        except Exception as exc:
            print(f"  [{i}/{len(tickers)}] {t}: FAIL {exc}", file=sys.stderr)
            continue
        if d is None or d.empty:
            print(
                f"  [{i}/{len(tickers)}] {t}: skipped (short history)", file=sys.stderr
            )
            continue
        frames.append(d)
        print(f"  [{i}/{len(tickers)}] {t}: {len(d)} obs", file=sys.stderr, flush=True)

    if not frames:
        print("no data", file=sys.stderr)
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    df.to_parquet(f"{args.out_prefix}.per_obs.parquet", index=False)
    emit(df, args.out_prefix)


if __name__ == "__main__":
    main()
