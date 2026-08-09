"""Is the SVI surface residual tradable NET OF COST as a defined-risk vertical?

`svi_residual_reversion_probe` established the residual mean-reverts and that a
1-step-lagged entry realizes ~0.2 vol pts. It stops there — it never forms a
position, so it never answers the only question that matters: does that survive
two legs, two spreads and four commissions?

This probe forms the actual trade. At origin i it reads ONLY date i, picks the
richest/cheapest strike, pairs it with a further-OTM hedge strike (defined risk,
no naked shorts), enters at i+1 and exits at i+1+h. Both legs are priced with
Black-76 on the delta-forward using that date's marked IV.

Two things this file is deliberately loud about:

1. `CONTRACT_MULTIPLIER`. The published verdict in residual-edge-test.md compared
   a PER-SHARE vega-dollar edge against a PER-CONTRACT commission and concluded the
   edge was smaller than one commission. It is 100x larger than that. Dollar math
   lives in code here, with the multiplier named, so the trace can be recomputed.

2. Cost is swept, not assumed. `option_surface_grid_daily` carries no bid/ask and
   UW 403s per-strike history, so the historical spread is UNRECOVERABLE. Rather
   than invent one, this reports net Sharpe as a function of assumed spread and
   solves for the BREAK-EVEN spread. `svi_residual_spread_anchor` then places real
   IB NBBO spreads on that curve.

ZERO UW/IB calls — reads banked tables only.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.svi_residual_net_of_cost
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from math import erf, log, sqrt
from pathlib import Path

import numpy as np
import psycopg

from scripts.research.svi_fit import (
    build_smile,
    fit_raw_svi,
    forward_from_delta,
    raw_svi_total_variance,
)
from uw_scan.backtest import monthly_summary, walkforward_gate
from uw_scan.config import Settings

logger = logging.getLogger("svi_net_of_cost")
logging.basicConfig(level=logging.INFO, format="%(message)s")

# --- contract economics -------------------------------------------------------
# US equity/ETF options. THE constant the published verdict dropped.
CONTRACT_MULTIPLIER = 100
# IB tiered/fixed lands ~0.15-0.65 per contract per side; take the pessimistic end.
COMMISSION_PER_CONTRACT_PER_SIDE = 0.65

# --- panel --------------------------------------------------------------------
LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
DTE_LO, DTE_HI = 5, 120  # 0-4 DTE excluded (#207 lesson)
DELTA_BAND = (0.05, 0.95)  # 5-delta put .. 5-delta call; deep wings carry junk marks
MIN_OBS_DATES = 15
TOP_EXPIRIES = 10
MIN_STRIKES_FOR_FIT = 8

# --- strategy -----------------------------------------------------------------
SIGNAL_THRESHOLDS = [1.0, 1.5, 2.0]  # |residual| vol pts required to fire
HORIZONS = [1, 2, 5]  # holding steps after entry
MAX_WIDTH_PCT = 0.06  # hedge strike within 6% of the short strike
HEDGE_VARIANTS = ["naive", "resid"]

# --- cost sweep ---------------------------------------------------------------
# Per-leg FULL bid-ask in vol points. Half-spread per side x 2 sides = one full
# spread per leg round trip. SPY ~0.06, QQQ ~0.34 were the two live observations.
SPREAD_VP_GRID = [0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]

OUT = Path("docs/research/svi-surface-fit")
SQRT2 = sqrt(2.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / SQRT2))


def black76(forward: float, strike: float, t: float, iv: float, is_call: bool) -> float:
    """Undiscounted Black-76 on the forward.

    Undiscounted on purpose: the discount factor is a common multiplier that moves
    <0.1% over a 1-5 day hold, which is second-order against a ~0.2 vol pt edge, and
    the grid carries no rate. Both legs share it, so the spread P&L is unaffected.
    """
    if t <= 0 or iv <= 0 or forward <= 0 or strike <= 0:
        return max(forward - strike, 0.0) if is_call else max(strike - forward, 0.0)
    v = iv * sqrt(t)
    d1 = (log(forward / strike) + 0.5 * v * v) / v
    d2 = d1 - v
    if is_call:
        return forward * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1)


@dataclass
class Leg:
    strike: float
    iv: float
    vega: float  # $ per vol point PER SHARE (grid convention: per-1%-vol)
    is_call: bool


@dataclass
class Trade:
    ticker: str
    expiry: date
    signal_date: date
    entry_date: date
    exit_date: date
    horizon: int
    threshold: float
    variant: str
    short_strike: float
    hedge_strike: float
    width: float
    signal_resid_vp: float
    hedge_resid_vp: float
    is_credit: bool
    gross_pnl: float  # dollars per 1 spread, after multiplier
    ivonly_pnl: float  # exit IV but ENTRY forward — isolates vol from beta
    max_loss: float  # capital base (defined risk)
    vega_short: float
    vega_hedge: float


def load_expiry_panel(cur, ticker: str, expiry: date) -> dict[date, dict]:
    """All dates for one (ticker, expiry) in ONE query -> {date: {strike: Leg}, fwd}.

    One query per (ticker, expiry) rather than per smile: over Tailscale the
    round-trip latency dominates the SVI fit itself.
    """
    cur.execute(
        "SELECT market_date, strike, call_iv, put_iv, call_delta, call_vega, "
        "       put_vega, underlying_spot "
        "FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND (expiry-market_date) BETWEEN %s AND %s "
        "ORDER BY market_date, strike",
        (ticker, expiry, DTE_LO, DTE_HI),
    )
    by_date: dict[date, list] = defaultdict(list)
    for row in cur.fetchall():
        by_date[row[0]].append(row[1:])
    return by_date


def fit_smile(rows: list, mdate: date, expiry: date) -> dict | None:
    """Fit one smile -> {fwd, t, legs: {strike: Leg}, resid: {strike: vol pts}}."""
    strikes = [r[0] for r in rows]
    cdeltas = [r[3] for r in rows]
    spot = next((float(r[6]) for r in rows if r[6] is not None), None)
    fwd = forward_from_delta(strikes, cdeltas, fallback=spot)
    if fwd is None or fwd <= 0:
        return None

    lo, hi = DELTA_BAND
    kept = [r for r in rows if r[3] is not None and lo <= float(r[3]) <= hi]
    if len(kept) < MIN_STRIKES_FOR_FIT:
        return None

    smile_rows = [
        {"strike": r[0], "call_iv": r[1], "put_iv": r[2], "call_delta": r[3]}
        for r in kept
    ]
    k, iv, w, t, used = build_smile(smile_rows, fwd, mdate, expiry)
    if len(k) < MIN_STRIKES_FOR_FIT or t <= 0:
        return None
    try:
        p, _ = fit_raw_svi(k, w)
    except Exception as exc:  # noqa: BLE001 - a failed fit just drops the smile
        logger.debug("fit fail %s %s: %s", mdate, expiry, repr(exc))
        return None

    iv_fit = np.sqrt(np.maximum(raw_svi_total_variance(k, p), 0.0) / t)
    resid_vp = (iv - iv_fit) * 100.0

    by_strike = {float(r[0]): r for r in kept}
    legs, resid = {}, {}
    for st, marked_iv, rvp in zip(used, iv, resid_vp):
        st = float(st)
        src = by_strike.get(st)
        if src is None:
            continue
        is_call = st >= fwd
        vega = src[4] if is_call else src[5]
        if vega is None:
            continue
        legs[st] = Leg(st, float(marked_iv), float(vega), is_call)
        resid[st] = float(rvp)
    return {"fwd": float(fwd), "t": float(t), "legs": legs, "resid": resid}


def pick_hedge(
    short_strike: float, is_call: bool, resid: dict, variant: str, selling: bool
) -> float | None:
    """Further-OTM strike defining the risk. Uses ONLY signal-date information."""
    span = short_strike * MAX_WIDTH_PCT
    if is_call:
        cands = [s for s in resid if short_strike < s <= short_strike + span]
    else:
        cands = [s for s in resid if short_strike - span <= s < short_strike]
    if not cands:
        return None
    if variant == "naive":
        # nearest listed strike further OTM — pure risk definition
        return min(cands, key=lambda s: abs(s - short_strike))
    # residual-aware: buying the hedge -> want it cheap; selling it -> want it rich
    return (
        min(cands, key=lambda s: resid[s])
        if selling
        else max(cands, key=lambda s: resid[s])
    )


def build_trades(ticker: str, expiry: date, smiles: dict[date, dict]) -> list[Trade]:
    dates = sorted(smiles)
    out: list[Trade] = []
    for i, sig_d in enumerate(dates):
        sig = smiles[sig_d]
        for thr in SIGNAL_THRESHOLDS:
            cands = [s for s, r in sig["resid"].items() if abs(r) >= thr]
            if not cands:
                continue
            k_s = max(cands, key=lambda s: abs(sig["resid"][s]))
            r_s = sig["resid"][k_s]
            selling = r_s > 0  # rich -> sell it; cheap -> buy it
            is_call = sig["legs"][k_s].is_call
            for variant in HEDGE_VARIANTS:
                k_h = pick_hedge(k_s, is_call, sig["resid"], variant, selling)
                if k_h is None:
                    continue
                for h in HORIZONS:
                    if i + 1 + h >= len(dates):
                        continue
                    ent_d, ex_d = dates[i + 1], dates[i + 1 + h]
                    ent, ex = smiles[ent_d], smiles[ex_d]
                    if not all(k in s["legs"] for s in (ent, ex) for k in (k_s, k_h)):
                        continue
                    t = build_trade(
                        ticker,
                        expiry,
                        sig_d,
                        ent_d,
                        ex_d,
                        h,
                        thr,
                        variant,
                        k_s,
                        k_h,
                        r_s,
                        sig["resid"][k_h],
                        selling,
                        is_call,
                        ent,
                        ex,
                    )
                    if t is not None:
                        out.append(t)
    return out


def build_trade(
    ticker,
    expiry,
    sig_d,
    ent_d,
    ex_d,
    h,
    thr,
    variant,
    k_s,
    k_h,
    r_s,
    r_h,
    selling,
    is_call,
    ent,
    ex,
) -> Trade | None:
    qty_s = -1.0 if selling else 1.0
    qty_h = -qty_s

    def px(sm, strike, forward=None):
        leg = sm["legs"][strike]
        return black76(
            forward if forward is not None else sm["fwd"],
            strike,
            sm["t"],
            leg.iv,
            leg.is_call,
        )

    s_in, h_in = px(ent, k_s), px(ent, k_h)
    s_out, h_out = px(ex, k_s), px(ex, k_h)
    # IV-only: exit IV, ENTRY forward -> strips the directional move
    s_out_iv = px(ex, k_s, forward=ent["fwd"])
    h_out_iv = px(ex, k_h, forward=ent["fwd"])

    m = CONTRACT_MULTIPLIER
    gross = m * (qty_s * (s_out - s_in) + qty_h * (h_out - h_in))
    ivonly = m * (qty_s * (s_out_iv - s_in) + qty_h * (h_out_iv - h_in))

    cash_in = m * (-qty_s * s_in - qty_h * h_in)  # >0 credit, <0 debit
    width = abs(k_s - k_h) * m
    max_loss = (width - cash_in) if cash_in > 0 else -cash_in
    if not (max_loss > 1e-6) or not np.isfinite(max_loss):
        return None

    return Trade(
        ticker=ticker,
        expiry=expiry,
        signal_date=sig_d,
        entry_date=ent_d,
        exit_date=ex_d,
        horizon=h,
        threshold=thr,
        variant=variant,
        short_strike=k_s,
        hedge_strike=k_h,
        width=abs(k_s - k_h),
        signal_resid_vp=r_s,
        hedge_resid_vp=r_h,
        is_credit=cash_in > 0,
        gross_pnl=gross,
        ivonly_pnl=ivonly,
        max_loss=max_loss,
        vega_short=ent["legs"][k_s].vega,
        vega_hedge=ent["legs"][k_h].vega,
    )


def net_dollars(t: Trade, spread_vp: float) -> float:
    """Net P&L in dollars per 1 spread. Normalization-free — the honest decider."""
    # half-spread per side x 2 sides = one full spread per leg, round trip
    slip = spread_vp * (t.vega_short + t.vega_hedge) * CONTRACT_MULTIPLIER
    comm = 4.0 * COMMISSION_PER_CONTRACT_PER_SIDE  # 2 legs x 2 sides
    return t.gross_pnl - slip - comm


def net_return(t: Trade, spread_vp: float) -> float:
    """Net-of-cost return on defined-risk capital.

    Denominator is the spread WIDTH, not `max_loss`. max_loss for a debit spread is
    the debit paid, which can be cents — dividing by it turns a $10 P&L into a
    +2000% return, and those trades then dominate every monthly mean and invert the
    Sharpe relative to the actual dollar P&L. Width x multiplier is the bounded,
    always-positive capital for a vertical (and the short-vertical margin
    convention). Conservative for debits, and stable, which is what matters here.
    """
    return net_dollars(t, spread_vp) / (t.width * CONTRACT_MULTIPLIER)


def summarize(trades: list[Trade], spread_vp: float) -> dict:
    if not trades:
        return {}
    monthly: dict[tuple[int, int], list[float]] = defaultdict(list)
    for t in trades:
        monthly[(t.exit_date.year, t.exit_date.month)].append(net_return(t, spread_vp))
    means = {k: float(np.mean(v)) for k, v in monthly.items()}
    s = monthly_summary(means)
    rets = [net_return(t, spread_vp) for t in trades]
    # OOS discipline from the shared harness — no private copies (backtest/CLAUDE.md).
    # Thresholds are 0.0: this asks only "does the edge keep its sign out of sample",
    # magnitude is what the spread sweep is measuring.
    obs = [
        {"market_date": t.exit_date, "value": net_return(t, spread_vp)} for t in trades
    ]
    wf = walkforward_gate(
        obs, value_key="value", min_n=30, threshold=0.0, holdout_threshold=0.0
    )
    return {
        "spread_vp": spread_vp,
        "n_trades": len(trades),
        "n_months": len(means),
        "sharpe": s["sharpe"],
        "maxdd": s["maxdd"],
        "annror": s["annror"],
        "mean_ret": float(np.mean(rets)),
        "hit_rate": float(np.mean([r > 0 for r in rets])),
        "mean_net_dollars": float(np.mean([net_dollars(t, spread_vp) for t in trades])),
        "median_net_dollars": float(
            np.median([net_dollars(t, spread_vp) for t in trades])
        ),
        "mean_gross_dollars": float(np.mean([t.gross_pnl for t in trades])),
        "mean_ivonly_dollars": float(np.mean([t.ivonly_pnl for t in trades])),
        "mean_capital": float(np.mean([t.width * CONTRACT_MULTIPLIER for t in trades])),
        "mean_holdout_ret": wf["mean_holdout"],
        "n_holdout": wf["n_holdout"],
        "survives_walkforward": wf["survives_walkforward"],
        "survives_quarter_gate": wf["survives_window_gate"],
    }


def breakeven_spread_dollars(trades: list[Trade]) -> float | None:
    """Per-leg spread (vol pts) at which MEAN NET DOLLARS hits zero. Closed form.

    This is the primary decider. Sharpe here rests on ~9 monthly observations
    (SE ~ sqrt(12/9) ~ 1.15), so a Sharpe-based break-even is mostly noise; mean
    dollars per trade needs no normalization and no monthly bucketing.

        mean(gross) - s * mean(vega_s + vega_h) * MULT - comm = 0
    """
    if not trades:
        return None
    gross = float(np.mean([t.gross_pnl for t in trades]))
    vega = float(np.mean([t.vega_short + t.vega_hedge for t in trades]))
    comm = 4.0 * COMMISSION_PER_CONTRACT_PER_SIDE
    if vega <= 0:
        return None
    s = (gross - comm) / (vega * CONTRACT_MULTIPLIER)
    return round(s, 4) if s > 0 else None


def breakeven_spread(trades: list[Trade], target_sharpe: float = 0.0) -> float | None:
    """Finest spread level (vol pts) at which net Sharpe still clears the target."""
    lo, hi = 0.0, 1.0
    if (summarize(trades, lo).get("sharpe") or float("-inf")) < target_sharpe:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        s = summarize(trades, mid).get("sharpe")
        if s is not None and np.isfinite(s) and s >= target_sharpe:
            lo = mid
        else:
            hi = mid
    return round(lo, 4)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    all_trades: list[Trade] = []
    n_smiles = 0

    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        for ticker in LIQUID:
            cur.execute(
                "SELECT expiry, count(DISTINCT market_date) nd "
                "FROM option_surface_grid_daily "
                "WHERE ticker=%s AND (expiry-market_date) BETWEEN %s AND %s "
                "GROUP BY expiry HAVING count(DISTINCT market_date) >= %s "
                "ORDER BY nd DESC LIMIT %s",
                (ticker, DTE_LO, DTE_HI, MIN_OBS_DATES, TOP_EXPIRIES),
            )
            expiries = [r[0] for r in cur.fetchall()]
            for expiry in expiries:
                panel = load_expiry_panel(cur, ticker, expiry)
                smiles = {}
                for mdate, rows in panel.items():
                    fitted = fit_smile(rows, mdate, expiry)
                    if fitted and fitted["legs"]:
                        smiles[mdate] = fitted
                        n_smiles += 1
                if len(smiles) >= 3:
                    all_trades.extend(build_trades(ticker, expiry, smiles))
            logger.info("%-5s  smiles=%d  trades=%d", ticker, n_smiles, len(all_trades))

    if not all_trades:
        logger.error("no trades built — check panel filters")
        return 1

    # full trace: every trade
    with (OUT / "net_of_cost_trades.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(all_trades[0]).keys()))
        w.writeheader()
        for t in all_trades:
            w.writerow(asdict(t))

    # sweep: every variant x threshold x horizon x spread assumption
    rows = []
    for variant in HEDGE_VARIANTS:
        for thr in SIGNAL_THRESHOLDS:
            for h in HORIZONS:
                sub = [
                    t
                    for t in all_trades
                    if t.variant == variant and t.threshold == thr and t.horizon == h
                ]
                if len(sub) < 30:
                    continue
                be_usd = breakeven_spread_dollars(sub)
                be0 = breakeven_spread(sub, 0.0)
                be1 = breakeven_spread(sub, 1.0)
                for sv in SPREAD_VP_GRID:
                    r = summarize(sub, sv)
                    r.update(
                        variant=variant,
                        threshold=thr,
                        horizon=h,
                        breakeven_spread_vp_dollars=be_usd,
                        breakeven_spread_vp_sharpe0=be0,
                        breakeven_spread_vp_sharpe1=be1,
                    )
                    rows.append(r)
                z = summarize(sub, 0.0)
                logger.info(
                    "%-5s thr=%.1f h=%d n=%-5d mo=%d  gross$=%+8.2f  net$@0=%+8.2f  "
                    "sharpe@0=%+5.2f  BE$=%s  BE(S=0)=%s",
                    variant,
                    thr,
                    h,
                    len(sub),
                    z["n_months"],
                    z["mean_gross_dollars"],
                    z["mean_net_dollars"],
                    z["sharpe"],
                    be_usd,
                    be0,
                )

    with (OUT / "net_of_cost_sweep.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    logger.info(
        "wrote %s (%d trades) and %s (%d sweep rows); %d smiles fitted",
        OUT / "net_of_cost_trades.csv",
        len(all_trades),
        OUT / "net_of_cost_sweep.csv",
        len(rows),
        n_smiles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
