"""Iteration-4 robustness studies on the macro short-vol WINNER.

Pure orchestration over the validated ledger (reports/vrp_capital_account.simulate_account)
and pricing (reports/vrp_structure.build_bull_put_spread). Adds the analysis the ledger
deliberately omits: smallest viable starting capital, the SPY buy-and-hold benchmark, a
geometric compounding-metric path, and the weekday / bear-start / Monte-Carlo experiments.
No new deps — stdlib statistics + random only. Every result returns a dict the runner
(scripts/research/vrp_robustness_run.py) persists to a CSV. Reproduce: see that runner.
"""

from __future__ import annotations

import dataclasses
import logging
import math
import random
from datetime import date as _date
from statistics import fmean, pstdev
from typing import Any

from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_signal import MacroSignalConfig
from uw_scan.reports.vrp_structure import build_bull_put_spread

log = logging.getLogger(__name__)

CONTRACT_MULTIPLIER = 100


def _pct(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0,1]); empty → nan, single → that value."""
    xs = sorted(v for v in values if v is not None and not math.isnan(v))
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def min_viable_capital(
    loaded,
    settings,
    *,
    short_delta: float = 0.25,
    wing_frac: float = 0.5,
    hold: int = 30,
    min_date: _date | None = None,
    base_risk_pcts: tuple[float, ...] = (0.10, 0.20, 0.50, 1.0),
) -> dict[str, Any]:
    """Smallest C0 that affords >=1 bull-put spread. Returns the first tradeable entry's
    max-loss/contract, the max over the post-start period (what's needed to never skip as
    spot rises), and the floor C0 per risk-%: ceil(mlpc / brp) to $1k."""
    r = settings.vrp_risk_free_rate
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    first_mlpc: float | None = None
    first_date: _date | None = None
    max_mlpc = 0.0
    for pi in range(0, max(0, len(loaded.adj) - hold)):
        d, s0 = loaded.adj[pi]
        if min_date and d < min_date:
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        try:
            st = build_bull_put_spread(
                s0,
                float(iv),
                hold / 252.0,
                r,
                short_delta=short_delta,
                wing_delta=short_delta * wing_frac,
            )
        except ValueError as exc:  # degenerate strikes
            log.debug("min-capital bull-put build skipped %s: %s", d, repr(exc))
            continue
        mlpc = st.max_loss * CONTRACT_MULTIPLIER
        if first_mlpc is None:
            first_mlpc, first_date = mlpc, d
        max_mlpc = max(max_mlpc, mlpc)
    if first_mlpc is None:
        return {
            "first_entry_date": None,
            "first_mlpc": 0.0,
            "max_mlpc": 0.0,
            "c0_floor": {},
        }

    def _ceil1k(x: float) -> float:
        return math.ceil(x / 1000.0) * 1000.0

    return {
        "first_entry_date": first_date,
        "first_mlpc": first_mlpc,
        "max_mlpc": max_mlpc,
        "c0_floor": {brp: _ceil1k(first_mlpc / brp) for brp in base_risk_pcts},
    }


def buy_and_hold(
    adj, capital: float, rf: float, *, min_date: _date | None = None
) -> dict:
    """SPY buy-and-hold benchmark: invest `capital` at the first spot on/after min_date,
    mark to each close. Sharpe on monthly equity-relative returns (annualised)."""
    pts = [
        (d, s) for d, s in adj if s and s > 0 and (min_date is None or d >= min_date)
    ]
    if len(pts) < 2:
        return {
            "ann_return": float("nan"),
            "cagr": float("nan"),
            "sharpe": float("nan"),
            "maxdd_dollars": 0.0,
            "maxdd_pct": 0.0,
            "years": 0.0,
            "start": None,
            "end": None,
        }
    s0 = pts[0][1]
    equity = [(d, capital * s / s0) for d, s in pts]
    by_month: dict[tuple[int, int], float] = {}
    for d, e in equity:
        by_month[(d.year, d.month)] = e  # last write per month wins (month-end)
    months = [by_month[k] for k in sorted(by_month)]
    rets = [months[i] / months[i - 1] - 1.0 for i in range(1, len(months))]
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean(rets) / sd * math.sqrt(12)) if sd > 0 else float("nan")
    peak = mdd = 0.0
    for _d, e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    years = (pts[-1][0] - pts[0][0]).days / 365.25
    cagr = (
        (equity[-1][1] / capital) ** (1.0 / years) - 1.0 if years > 0 else float("nan")
    )
    return {
        "ann_return": fmean(rets) * 12 if rets else float("nan"),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capital if capital else 0.0,
        "years": years,
        "start": pts[0][0],
        "end": pts[-1][0],
    }


def _contiguous_months(
    monthly: dict[tuple[int, int], float],
) -> list[tuple[tuple[int, int], float]]:
    if not monthly:
        return []
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    out: list[tuple[tuple[int, int], float]] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        out.append(((y, m), monthly.get((y, m), 0.0)))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def monthly_equity(res, capital: float) -> list[tuple[tuple[int, int], float]]:
    """Month-end $ equity path = capital + running sum of monthly $P&L
    (monthly_excess is net ÷ initial capital, so $P&L_month = excess × capital)."""
    eq = capital
    out: list[tuple[tuple[int, int], float]] = []
    for ym, exc in _contiguous_months(res.monthly_excess):
        eq += exc * capital
        out.append((ym, eq))
    return out


def equity_curve_metrics(equity_points, capital: float, rf: float) -> dict:
    """Geometric metrics for the compounding read: simple monthly returns
    r_t = E_t / E_{t-1} - 1 with E_0 = capital. Sharpe/CAGR/maxDD on that path."""
    if not equity_points:
        return {
            "ann_return": float("nan"),
            "cagr": float("nan"),
            "sharpe": float("nan"),
            "maxdd_dollars": 0.0,
            "maxdd_pct": 0.0,
            "years": 0.0,
        }
    levels = [capital] + [e for _ym, e in equity_points]
    rets = [
        levels[i] / levels[i - 1] - 1.0
        for i in range(1, len(levels))
        if levels[i - 1] > 0
    ]
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (fmean(rets) / sd * math.sqrt(12)) if sd > 0 else float("nan")
    peak = capital
    mdd = 0.0
    for e in levels:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    years = len(equity_points) / 12.0
    cagr = (
        (levels[-1] / capital) ** (1.0 / years) - 1.0
        if (years > 0 and levels[-1] > 0)
        else float("nan")
    )
    return {
        "ann_return": fmean(rets) * 12 if rets else float("nan"),
        "cagr": cagr,
        "sharpe": sharpe,
        "maxdd_dollars": mdd,
        "maxdd_pct": mdd / capital if capital else 0.0,
        "years": years,
    }


def weekday_sweep(loaded, settings, capcfg: CapitalConfig, rf: float) -> list[dict]:
    """Run the ledger with entries forced to each weekday (Mon..Fri) and to the default
    stride. SPX-only: loadeds = {capcfg.names[0]: loaded}. Returns account_metrics per."""
    name = capcfg.names[0]
    rows: list[dict] = []
    for label in (0, 1, 2, 3, 4, "stride"):
        wd = None if label == "stride" else label
        cfg = dataclasses.replace(capcfg, entry_weekday=wd)
        res = simulate_account({name: loaded}, settings, cfg)
        rows.append({"entry_weekday": label, **account_metrics(res, cfg, rf)})
    return rows


def _window_metrics(equity_points, capital: float, n_months: int) -> dict:
    pts = equity_points[:n_months]
    if not pts:
        return {"ret": float("nan"), "maxdd_pct": float("nan")}
    peak = capital
    mdd = 0.0
    for _ym, e in pts:
        peak = max(peak, e)
        mdd = min(mdd, e - peak)
    return {
        "ret": pts[-1][1] / capital - 1.0,
        "maxdd_pct": mdd / capital if capital else 0.0,
    }


def bear_start_study(
    loaded,
    settings,
    capcfg: CapitalConfig,
    rf: float,
    *,
    starts,
    windows_months: tuple[int, ...] = (6, 12, 36),
) -> tuple[list[dict], list[dict]]:
    """For each bear start: (summary_rows, path_rows). summary = full-path metrics
    (geometric if capcfg.compounding else linear) + fixed forward-window return & maxDD;
    path = long-form month-end equity + drawdown for charting the full lived experience."""
    name = capcfg.names[0]
    summary: list[dict] = []
    path_rows: list[dict] = []
    for start in starts:
        cfg = dataclasses.replace(capcfg, min_date=start)
        res = simulate_account({name: loaded}, settings, cfg)
        eqpts = monthly_equity(res, cfg.capital)
        full = (
            equity_curve_metrics(eqpts, cfg.capital, rf)
            if cfg.compounding
            else account_metrics(res, cfg, rf)
        )
        row: dict[str, Any] = {
            "start": start,
            "n_rungs": len(res.rungs),
            "sharpe": full.get("sharpe"),
            # account_metrics emits cagr_excess; equity_curve_metrics emits cagr
            "cagr": full.get("cagr", full.get("cagr_excess")),
            "maxdd_pct": full.get("maxdd_pct"),
        }
        for w in windows_months:
            wm = _window_metrics(eqpts, cfg.capital, w)
            row[f"ret_{w}m"] = wm["ret"]
            row[f"maxdd_{w}m_pct"] = wm["maxdd_pct"]
        summary.append(row)
        peak = cfg.capital
        for (yy, mm), e in eqpts:
            peak = max(peak, e)
            path_rows.append(
                {
                    "start": start,
                    "year": yy,
                    "month": mm,
                    "equity": e,
                    "drawdown_pct": (e - peak) / cfg.capital if cfg.capital else 0.0,
                }
            )
    return summary, path_rows


def _dist(
    values: list[float], n_trials: int, seed: int, *, metric: str = "sharpe"
) -> dict:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    return {
        "metric": metric,
        "n_trials": n_trials,
        "seed": seed,
        "n_valid": len(clean),
        "mean": fmean(clean) if clean else float("nan"),
        "median": _pct(clean, 0.5),
        "p5": _pct(clean, 0.05),
        "p95": _pct(clean, 0.95),
    }


def _project(m: dict, metric: str) -> float:
    """Bridge the *_excess key names: account_metrics emits cagr_excess/ann_return_excess;
    the geometric path emits plain cagr/ann_return. sharpe/maxdd_pct exist in both."""
    if metric in m:
        return m[metric]
    return m.get(f"{metric}_excess", float("nan"))


def _metric_of(res, cfg, rf: float, *, metric: str) -> float:
    m = (
        equity_curve_metrics(monthly_equity(res, cfg.capital), cfg.capital, rf)
        if cfg.compounding
        else account_metrics(res, cfg, rf)
    )
    return _project(m, metric)


def mc_entry_jitter(
    loaded,
    settings,
    capcfg: CapitalConfig,
    rf: float,
    *,
    n_trials: int = 200,
    jitter: int = 2,
    seed: int = 0,
    metric: str = "sharpe",
) -> dict:
    """Distribution of `metric` over n_trials, each a different jitter_seed so every entry
    day wiggles ± jitter trading days. Per-trial records returned under 'trials'."""
    name = capcfg.names[0]
    trials: list[dict] = []
    for t in range(n_trials):
        js = seed * 100003 + t
        cfg = dataclasses.replace(capcfg, entry_jitter=jitter, jitter_seed=js)
        v = _metric_of(
            simulate_account({name: loaded}, settings, cfg), cfg, rf, metric=metric
        )
        trials.append({"trial": t, "value": v, "param": f"jitter_seed={js}"})
    return {
        **_dist([x["value"] for x in trials], n_trials, seed, metric=metric),
        "trials": trials,
    }


def mc_block_bootstrap(
    monthly_values,
    *,
    n_trials: int = 1000,
    mean_block: float = 6.0,
    seed: int = 0,
    rf: float = 0.04,
) -> dict:
    """Stationary (Politis-Romano) bootstrap of a monthly return series → annualised Sharpe
    distribution. Block length ~ Geometric(1/mean_block); wraps circularly. Feed the
    ZERO-FILLED contiguous series so the distribution centres on the reported base Sharpe."""
    if mean_block <= 0:
        raise ValueError("mean_block must be > 0")
    series = [v for v in monthly_values if v is not None and not math.isnan(v)]
    n = len(series)
    rng = random.Random(seed)
    p = 1.0 / mean_block
    trials: list[dict] = []
    if n >= 2:
        for t in range(n_trials):
            sample: list[float] = []
            while len(sample) < n:
                i = rng.randrange(n)
                while len(sample) < n:
                    sample.append(series[i % n])
                    i += 1
                    if rng.random() < p:
                        break
            sd = pstdev(sample) if len(sample) > 1 else 0.0
            sh = fmean(sample) / sd * math.sqrt(12) if sd > 0 else float("nan")
            trials.append(
                {"trial": t, "value": sh, "param": f"mean_block={mean_block}"}
            )
    return {
        **_dist(
            [x["value"] for x in trials], n_trials, seed, metric="sharpe_bootstrap"
        ),
        "trials": trials,
    }


def mc_random_start(
    loaded,
    settings,
    capcfg: CapitalConfig,
    rf: float,
    *,
    n_trials: int = 200,
    min_tail_months: int = 24,
    seed: int = 0,
    metric: str = "sharpe",
    min_start: _date | None = None,
    max_start: _date | None = None,
) -> dict:
    """Distribution of `metric` over n_trials random start dates (each leaving >= min_tail_months
    of data). Pass min_start/max_start to restrict sampling to a window — e.g. a bear regime,
    which is the design's #5 ('randomised entry points, extension of the bear-market case')."""
    name = capcfg.names[0]
    lo_d = min_start or _date.min
    hi_d = max_start or _date.max
    all_dates = [d for d, _ in loaded.adj]
    tail = min_tail_months * 21
    # eligible starts: inside [min_start, max_start] AND leaving >= tail trading days of
    # FORWARD data in the full series. Measuring the tail against the data end (not the
    # window) keeps GFC-windowed starts near the 2009 bottom eligible — the whole point of #5.
    eligible = [
        d
        for i, d in enumerate(all_dates)
        if lo_d <= d <= hi_d and i < len(all_dates) - tail
    ]
    rng = random.Random(seed)
    trials: list[dict] = []
    if eligible:
        for t in range(n_trials):
            start = eligible[rng.randrange(len(eligible))]
            cfg = dataclasses.replace(capcfg, min_date=start)
            v = _metric_of(
                simulate_account({name: loaded}, settings, cfg), cfg, rf, metric=metric
            )
            trials.append({"trial": t, "value": v, "param": f"start={start}"})
    return {
        **_dist([x["value"] for x in trials], n_trials, seed, metric=metric),
        "trials": trials,
    }


def mc_config_perturb(
    loaded,
    settings,
    capcfg: CapitalConfig,
    rf: float,
    *,
    n_trials: int = 200,
    seed: int = 0,
    metric: str = "sharpe",
) -> dict:
    """Distribution of `metric` over random perturbations of the tuned knobs
    (short_delta∈[0.20,0.30], hold∈[20,40], ramp_full_z∈[0.3,0.7]). Attacks overfit."""
    name = capcfg.names[0]
    rng = random.Random(seed)
    trials: list[dict] = []
    for t in range(n_trials):
        sd_ = round(rng.uniform(0.20, 0.30), 4)
        hd = rng.randint(20, 40)
        rz = round(rng.uniform(0.30, 0.70), 4)
        cfg = dataclasses.replace(
            capcfg,
            base_cfg=MacroSignalConfig(short_delta=sd_, hold_days=hd, ramp_full_z=rz),
        )
        v = _metric_of(
            simulate_account({name: loaded}, settings, cfg), cfg, rf, metric=metric
        )
        trials.append(
            {
                "trial": t,
                "value": v,
                "param": f"short_delta={sd_};hold={hd};ramp_full_z={rz}",
            }
        )
    return {
        **_dist([x["value"] for x in trials], n_trials, seed, metric=metric),
        "trials": trials,
    }
