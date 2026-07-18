#!/usr/bin/env python
"""Chanlun trust probe on silver (adjusted) daily bars.

Walk-forward prefix replay over a frozen ~200-name universe. For each mark
(顶/底背离 + 1/2/3 B/S), record the prefix at which it first reaches
confirmed=true, whether that confirmation survives to the final series
(repaint), and signed forward returns from the confirmation close (honest)
and the extreme close (hindsight ghost) vs a same-ticker baseline.

NOT a strategy: no costs/sizing; edge is an upper bound.
Reproduce: uv run python scripts/research/chanlun_trust_probe.py
"""

from __future__ import annotations

import argparse
import bisect
import csv
import random
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from uw_scan.chanlun.full import compute_chanlun_full
from uw_scan.chanlun.lifecycle import derive_marks, mark_side
from uw_scan.chanlun.types import ChanlunBar
from uw_scan.sources.apex import fetch_bars

WARMUP = 60  # skip degenerate early prefixes
HORIZONS = [1, 3, 5, 10, 20]  # trading days
HISTORY_DAYS = int(5.3 * 365)
EDGE_CATEGORIES = ["divergence", "point"]  # vertices are structural, not signals
OUT_DIR = Path("docs/research/2026-07-18-chanlun-trust-silver")
UNIVERSE_CSV = OUT_DIR / "universe.csv"
GEX_CSV = OUT_DIR / "gex_history.csv"  # Phase-2 regime gate (see _chanlun_trust_gex.py)
REPRODUCE = "uv run python scripts/research/chanlun_trust_probe.py"
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 20260718
STATE_LOOKBACK = 20  # trailing sessions defining the momentum "state"
STATE_BUCKETS = 5  # per-ticker quantile buckets of trailing return
COST_HURDLE = 0.0015  # ~15 bps: a rough round-trip cost floor for the reality check


def load_daily(ticker: str):
    """Full-history adjusted 1d bars from apex with an EXPLICIT start.
    Returns (bars, closes, session_dates) or None (never fabricate)."""
    start = date.today() - timedelta(days=HISTORY_DAYS)
    raw = fetch_bars(ticker, "1d", start, limit=0)
    if not raw:
        return None
    bars = [
        ChanlunBar(time=b["time"][:10], high=b["high"], low=b["low"], close=b["close"])
        for b in raw
    ]
    closes = [b.close for b in bars]
    session_dates = [date.fromisoformat(b.time) for b in bars]
    return bars, closes, session_dates


@dataclass
class ConfTrace:
    ticker: str
    category: str
    kind: str
    extreme_date: date
    extreme_price: float
    extreme_idx: int
    confirm_idx: int | None  # session idx where confirmed=true first seen
    ever_confirmed_live: bool
    final_confirmed: bool


def replay_confirmations(ticker, bars, session_dates) -> list[ConfTrace]:
    date_to_idx = {d: i for i, d in enumerate(session_dates)}
    # first_confirmed[key] = session idx i where is_native_confirmed first True
    first_confirmed: dict[tuple, int] = {}
    seen: dict[
        tuple, tuple
    ] = {}  # key -> (category, kind, extreme_date, extreme_price)
    for i in range(WARMUP, len(bars)):
        full = compute_chanlun_full(bars[: i + 1])
        for m in derive_marks(full, bars[: i + 1]):
            key = (m.category, m.kind, m.extreme_date, round(m.extreme_price, 4))
            seen.setdefault(key, (m.category, m.kind, m.extreme_date, m.extreme_price))
            if m.is_native_confirmed and key not in first_confirmed:
                first_confirmed[key] = i
    # Final full-series pass: which keys are confirmed at the end (repaint check).
    full_final = compute_chanlun_full(bars)
    final_conf: set[tuple] = {
        (m.category, m.kind, m.extreme_date, round(m.extreme_price, 4))
        for m in derive_marks(full_final, bars)
        if m.is_native_confirmed
    }
    out: list[ConfTrace] = []
    for key, (cat, kind, xdate, xprice) in seen.items():
        xidx = date_to_idx.get(xdate)
        if xidx is None:
            continue  # extreme not a session date (shouldn't happen) — skip, don't crash the run
        cidx = first_confirmed.get(key)
        out.append(
            ConfTrace(
                ticker=ticker,
                category=cat,
                kind=kind,
                extreme_date=xdate,
                extreme_price=xprice,
                extreme_idx=xidx,
                confirm_idx=cidx,
                ever_confirmed_live=cidx is not None,
                final_confirmed=key in final_conf,
            )
        )
    return out


def fwd_return(closes: list[float], i: int, h: int) -> float | None:
    j = i + h
    if j >= len(closes) or closes[i] == 0:
        return None
    return closes[j] / closes[i] - 1.0


def direction(kind: str) -> float:
    return 1.0 if mark_side(kind) == "bottom" else -1.0


def baseline_means(closes: list[float]) -> dict[int, float]:
    """Unconditional (direction-agnostic) mean forward return per horizon."""
    out: dict[int, float] = {}
    for h in HORIZONS:
        rs = [
            closes[k + h] / closes[k] - 1.0
            for k in range(WARMUP, len(closes) - h)
            if closes[k] != 0
        ]
        out[h] = statistics.fmean(rs) if rs else 0.0
    return out


TREND_WINDOW = 200  # the 200-DMA — the most-replicated mean-reversion regime filter


def rolling_above_sma(closes: list[float], window: int) -> list[bool | None]:
    """above[i] = close[i] >= SMA_window at i (None before the window fills). O(n)
    prefix-sum roll. The 200-DMA trend filter: mean-reversion longs work far better
    ABOVE it (buy dips in uptrends), shorts BELOW it — the single most robust
    conditioner in the reversal literature (Connors/Alvarez + replications)."""
    above: list[bool | None] = [None] * len(closes)
    run = 0.0
    for i, c in enumerate(closes):
        run += c
        if i >= window:
            run -= closes[i - window]
        if i >= window - 1:
            above[i] = c >= run / window
    return above


def trailing_returns(closes: list[float], lookback: int) -> list[float | None]:
    """tr[k] = close[k]/close[k-lookback] - 1, else None (warmup / zero denom)."""
    tr: list[float | None] = [None] * len(closes)
    for k in range(lookback, len(closes)):
        if closes[k - lookback] != 0:
            tr[k] = closes[k] / closes[k - lookback] - 1.0
    return tr


def state_baseline(closes: list[float]):
    """Per-ticker momentum-conditioned baseline. Buckets every bar by its trailing
    STATE_LOOKBACK-session return (per-ticker quantiles) and returns
    (bucket_of(i) -> int|None, base[(bucket, h)] -> mean fwd return). The signal's
    forward return is compared against OTHER bars in the SAME momentum state, so the
    'edge' is the signal's marginal value beyond the regime it fires in — not the
    regime itself. Falls back cleanly (bucket_of -> None) when too few valid bars."""
    tr = trailing_returns(closes, STATE_LOOKBACK)
    valid = sorted(x for x in tr if x is not None)
    if len(valid) < STATE_BUCKETS:
        return (lambda i: None), {}
    # Upper edges of buckets 0..STATE_BUCKETS-2 (last bucket is open-ended).
    thresh = [
        valid[int(q / STATE_BUCKETS * len(valid))] for q in range(1, STATE_BUCKETS)
    ]

    def bucket_of(i: int) -> int | None:
        v = tr[i]
        if v is None:
            return None
        b = 0
        for t in thresh:
            if v > t:
                b += 1
        return b

    acc: dict[tuple, list[float]] = {}
    for k in range(max(STATE_LOOKBACK, WARMUP), len(closes)):
        b = bucket_of(k)
        if b is None:
            continue
        for h in HORIZONS:
            r = fwd_return(closes, k, h)
            if r is not None:
                acc.setdefault((b, h), []).append(r)
    base = {key: statistics.fmean(v) for key, v in acc.items()}
    return bucket_of, base


def cluster_bootstrap_ci(
    rows: list[dict], seed: int, field: str = "edge"
) -> tuple[float, float]:
    """Deterministic 95% CI of the mean edge, resampling TICKERS (clusters), not
    individual marks. Same-ticker forward returns overlap in time and are
    correlated; a per-mark bootstrap would treat them as independent and return a
    spuriously tight CI, overstating significance. Resampling whole tickers
    respects the dominant (within-ticker) correlation. nan if <2 tickers."""
    by_ticker: dict[str, list[float]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r[field])
    tickers = list(by_ticker)
    if len(tickers) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_N):
        pool: list[float] = []
        for _ in range(len(tickers)):
            pool.extend(by_ticker[rng.choice(tickers)])
        if pool:
            means.append(statistics.fmean(pool))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])


def signal_rows(
    trace: ConfTrace,
    closes: list[float],
    base: dict[int, float],
    sbase: dict[tuple, float] | None = None,
    bucket_of=None,
    mid: int | None = None,
    above200: list[bool | None] | None = None,
    regime_at_idx: list[str | None] | None = None,
) -> list[dict]:
    # Score ONLY marks that eventually confirmed, so the confirmation entry and
    # the extreme (ghost) entry measure the SAME population — isolating the cost
    # of entry timing (the ~8-bar lookahead), not also swapping in never-confirmed
    # provisional-tail noise. A mark that never confirms is not a tradeable signal.
    if trace.category not in EDGE_CATEGORIES or trace.confirm_idx is None:
        return []
    d = direction(trace.kind)
    side = mark_side(trace.kind)
    token = trace.kind if trace.category == "point" else trace.category
    rows = []
    for entry_name, entry_idx in (
        ("confirmation", trace.confirm_idx),  # honest
        ("extreme", trace.extreme_idx),  # hindsight ghost
    ):
        if entry_idx is None:
            continue
        b = bucket_of(entry_idx) if bucket_of is not None else None
        period = "H1" if (mid is None or entry_idx < mid) else "H2"
        # Conditioning columns (Phase-1 experiments):
        # trend_agree = mean-reversion-favorable 200-DMA alignment (bottom above /
        #   top below the 200-DMA); depth_favorable = fired from an extreme momentum
        #   bucket in the signal's direction (bottom deep-oversold / top sharp-rally).
        ab = above200[entry_idx] if above200 is not None else None
        trend_agree = None
        if ab is not None:
            trend_agree = ab if side == "bottom" else (not ab)
        depth_favorable = None
        if b is not None:
            depth_favorable = (side == "bottom" and b <= 1) or (
                side == "top" and b >= STATE_BUCKETS - 2
            )
        # Phase-2: dealer-gamma regime as-of the entry (pos = mean-reverting).
        gamma_regime = regime_at_idx[entry_idx] if regime_at_idx is not None else None
        for h in HORIZONS:
            ret = fwd_return(closes, entry_idx, h)
            if ret is None:
                continue
            # State baseline: mean fwd return of same-momentum-bucket bars; falls
            # back to the unconditional baseline when the bucket is unavailable.
            sb = base[h]
            if sbase is not None and b is not None:
                sb = sbase.get((b, h), base[h])
            rows.append(
                {
                    "ticker": trace.ticker,
                    "category_token": token,
                    "kind": trace.kind,
                    "extreme_date": trace.extreme_date.isoformat(),
                    "entry": entry_name,
                    "period": period,
                    "horizon": h,
                    "mom_bucket": b if b is not None else "",
                    "trend_agree": trend_agree,
                    "depth_favorable": depth_favorable,
                    "gamma_regime": gamma_regime,
                    "signed_ret": d * ret,
                    "signed_baseline": d * base[h],
                    "edge": d * (ret - base[h]),
                    "state_edge": d * (ret - sb),
                    "correct": 1 if d * ret > 0 else 0,
                }
            )
    return rows


def aggregate(rows: list[dict], field: str = "edge") -> list[dict]:
    """Group by (category_token, entry, horizon) -> summary. `field` selects which
    edge column ("edge" = unconditional baseline; "state_edge" = momentum-conditioned)
    the mean + bootstrap CI are computed on."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["category_token"], r["entry"], r["horizon"]), []).append(r)
    out = []
    for (token, entry, h), rs in sorted(groups.items()):
        edges = [r[field] for r in rs]
        lo, hi = cluster_bootstrap_ci(rs, BOOTSTRAP_SEED, field)
        out.append(
            {
                "category_token": token,
                "entry": entry,
                "horizon": h,
                "n": len(rs),
                "hit_rate": statistics.fmean(r["correct"] for r in rs),
                "mean_signed_ret": statistics.fmean(r["signed_ret"] for r in rs),
                "median_signed_ret": statistics.median(r["signed_ret"] for r in rs),
                "mean_baseline": statistics.fmean(r["signed_baseline"] for r in rs),
                "mean_edge": statistics.fmean(edges),
                "edge_ci_lo": lo,
                "edge_ci_hi": hi,
                "ci_excludes_zero": lo > 0 or hi < 0,
            }
        )
    return out


def period_robustness(rows: list[dict], field: str = "state_edge") -> list[dict]:
    """Confirmation-entry only: mean `field` per (category_token, horizon) split into
    the first vs second half of each ticker's history. `same_sign` flags where H1 and
    H2 agree in sign — an edge that flips between halves is a period artifact, not a
    durable signal."""
    conf = [r for r in rows if r["entry"] == "confirmation"]
    groups: dict[tuple, dict[str, list[float]]] = {}
    for r in conf:
        g = groups.setdefault((r["category_token"], r["horizon"]), {"H1": [], "H2": []})
        g[r["period"]].append(r[field])
    out = []
    for (token, h), halves in sorted(groups.items()):
        h1 = statistics.fmean(halves["H1"]) if halves["H1"] else float("nan")
        h2 = statistics.fmean(halves["H2"]) if halves["H2"] else float("nan")
        same = (h1 > 0 and h2 > 0) or (h1 < 0 and h2 < 0)
        out.append(
            {
                "category_token": token,
                "horizon": h,
                "n_h1": len(halves["H1"]),
                "n_h2": len(halves["H2"]),
                "edge_h1": h1,
                "edge_h2": h2,
                "same_sign": same,
            }
        )
    return out


CONDITION_HORIZONS = [5, 10]  # the divergence sweet spot from the pooled run


def conditioning_report(rows: list[dict]) -> list[dict]:
    """Phase-1 experiment: does filtering confirmed marks by 200-DMA trend agreement
    and/or oversold/overbought depth lift the state-conditioned edge — and does the
    lift survive the H1/H2 period split? Confirmation entry only, at the sweet-spot
    horizons. Each (category, horizon) emits the pooled row plus the trend / depth /
    trend+depth subsets, with n, hit-rate, mean state_edge, cluster CI, and same_sign."""
    conf = [
        r
        for r in rows
        if r["entry"] == "confirmation" and r["horizon"] in CONDITION_HORIZONS
    ]
    tokens = sorted({r["category_token"] for r in conf})
    out = []
    for token in tokens:
        for h in CONDITION_HORIZONS:
            base_rs = [
                r for r in conf if r["category_token"] == token and r["horizon"] == h
            ]
            filters = [
                ("all", base_rs),
                ("trend", [r for r in base_rs if r["trend_agree"] is True]),
                ("depth", [r for r in base_rs if r["depth_favorable"] is True]),
                (
                    "trend+depth",
                    [
                        r
                        for r in base_rs
                        if r["trend_agree"] is True and r["depth_favorable"] is True
                    ],
                ),
            ]
            for fname, rs in filters:
                if not rs:
                    out.append(
                        {
                            "category_token": token,
                            "horizon": h,
                            "filter": fname,
                            "n": 0,
                            "hit_rate": float("nan"),
                            "mean_edge": float("nan"),
                            "edge_ci_lo": float("nan"),
                            "edge_ci_hi": float("nan"),
                            "ci_excludes_zero": False,
                            "same_sign": False,
                        }
                    )
                    continue
                lo, hi = cluster_bootstrap_ci(rs, BOOTSTRAP_SEED, "state_edge")
                h1 = [r["state_edge"] for r in rs if r["period"] == "H1"]
                h2 = [r["state_edge"] for r in rs if r["period"] == "H2"]
                m1 = statistics.fmean(h1) if h1 else float("nan")
                m2 = statistics.fmean(h2) if h2 else float("nan")
                out.append(
                    {
                        "category_token": token,
                        "horizon": h,
                        "filter": fname,
                        "n": len(rs),
                        "hit_rate": statistics.fmean(r["correct"] for r in rs),
                        "mean_edge": statistics.fmean(r["state_edge"] for r in rs),
                        "edge_ci_lo": lo,
                        "edge_ci_hi": hi,
                        "ci_excludes_zero": lo > 0 or hi < 0,
                        "same_sign": (m1 > 0 and m2 > 0) or (m1 < 0 and m2 < 0),
                    }
                )
    return out


def gex_edge_report(rows: list[dict]) -> list[dict]:
    """Phase-2: does the dealer-gamma regime gate the divergence EDGE? Confirmation
    entry, in-GEX-window rows only (gamma_regime set → post-2023-08). Per (token, h):
    pooled (pos+neg), pos-gamma, neg-gamma, and pos-gamma+trend-agree. GEX is a
    regime gate, not a direction call, so the question is whether the SAME divergence
    performs better in a mean-reverting (positive-gamma) tape."""
    conf = [
        r
        for r in rows
        if r["entry"] == "confirmation"
        and r["horizon"] in CONDITION_HORIZONS
        and r["gamma_regime"] in ("pos", "neg")
    ]
    tokens = sorted({r["category_token"] for r in conf})
    out = []
    for token in tokens:
        for h in CONDITION_HORIZONS:
            base_rs = [
                r for r in conf if r["category_token"] == token and r["horizon"] == h
            ]
            filters = [
                ("in-window", base_rs),
                ("pos-gamma", [r for r in base_rs if r["gamma_regime"] == "pos"]),
                ("neg-gamma", [r for r in base_rs if r["gamma_regime"] == "neg"]),
                (
                    "pos+trend",
                    [
                        r
                        for r in base_rs
                        if r["gamma_regime"] == "pos" and r["trend_agree"] is True
                    ],
                ),
            ]
            for fname, rs in filters:
                if not rs:
                    out.append(
                        {
                            "category_token": token,
                            "horizon": h,
                            "filter": fname,
                            "n": 0,
                            "hit_rate": float("nan"),
                            "mean_edge": float("nan"),
                            "edge_ci_lo": float("nan"),
                            "edge_ci_hi": float("nan"),
                            "ci_excludes_zero": False,
                        }
                    )
                    continue
                lo, hi = cluster_bootstrap_ci(rs, BOOTSTRAP_SEED, "state_edge")
                out.append(
                    {
                        "category_token": token,
                        "horizon": h,
                        "filter": fname,
                        "n": len(rs),
                        "hit_rate": statistics.fmean(r["correct"] for r in rs),
                        "mean_edge": statistics.fmean(r["state_edge"] for r in rs),
                        "edge_ci_lo": lo,
                        "edge_ci_hi": hi,
                        "ci_excludes_zero": lo > 0 or hi < 0,
                    }
                )
    return out


GEX_SURV_HORIZONS = [5, 10, 20]


def gex_survival(
    traces, bars_by_ticker, closes_by_ticker, regime_by_ticker
) -> list[dict]:
    """Phase-2, the research-endorsed use of GEX: does a divergence in a positive-gamma
    (mean-reverting) regime HOLD longer? Divergence only, confirmation entry, split by
    dealer-gamma regime as-of confirmation. Per (regime, horizon): survival (extreme not
    yet re-broken) + mean signed markout."""
    max_t = max(GEX_SURV_HORIZONS)
    surv: dict[tuple, list[int]] = {}
    ret: dict[tuple, list[float]] = {}
    for tr in traces:
        if tr.category != "divergence" or tr.confirm_idx is None:
            continue
        reg = regime_by_ticker.get(tr.ticker)
        regime = reg[tr.confirm_idx] if reg is not None else None
        if regime not in ("pos", "neg"):
            continue
        bars = bars_by_ticker[tr.ticker]
        closes = closes_by_ticker[tr.ticker]
        ci = tr.confirm_idx
        d = direction(tr.kind)
        fbo = _first_breach_offset(
            bars, ci, tr.extreme_price, mark_side(tr.kind), max_t
        )
        for t in GEX_SURV_HORIZONS:
            r = fwd_return(closes, ci, t)
            if r is not None:
                ret.setdefault((regime, t), []).append(d * r)
            if ci + t < len(bars):
                surv.setdefault((regime, t), []).append(
                    1 if (fbo is not None and fbo <= t) else 0
                )
    out = []
    for regime in ("pos", "neg"):
        for t in GEX_SURV_HORIZONS:
            sv = surv.get((regime, t), [])
            rr = ret.get((regime, t), [])
            out.append(
                {
                    "regime": regime,
                    "horizon": t,
                    "n": len(sv),
                    "survival": 1 - statistics.fmean(sv) if sv else float("nan"),
                    "mean_markout": statistics.fmean(rr) if rr else float("nan"),
                }
            )
    return out


def lag_rows(traces: list[ConfTrace]) -> list[dict]:
    """Per category_token: distribution of confirmation lag (confirm_idx - extreme_idx,
    in sessions) among ever-confirmed-live marks. Validates the ~8-bar lag claim on
    clean bars — this lag is the lookahead the extreme (ghost) entry illegitimately
    captures."""
    groups: dict[str, list[int]] = {}
    for t in traces:
        if t.confirm_idx is None:
            continue
        token = t.kind if t.category == "point" else t.category
        groups.setdefault(token, []).append(t.confirm_idx - t.extreme_idx)
    out = []
    for token, lags in sorted(groups.items()):
        lags.sort()
        p90 = lags[min(len(lags) - 1, int(0.9 * len(lags)))]
        out.append(
            {
                "category_token": token,
                "n": len(lags),
                "median_lag": statistics.median(lags),
                "p90_lag": p90,
            }
        )
    return out


MARKOUT_HORIZONS = [1, 3, 5, 10, 20, 40, 60]  # longer tail for the validity question
BOUNCE_H = 5  # a signal "bounced as expected" if signed return is + within a week


def _first_breach_offset(bars, ci: int, level: float, side: str, max_t: int):
    """Sessions after confirmation until price first trades back through the marked
    level (bottom: a later low < level; top: a later high > level). None if it
    survives the whole window (or the window runs off the data)."""
    for off in range(1, max_t + 1):
        j = ci + off
        if j >= len(bars):
            return None
        if side == "bottom" and bars[j].low < level:
            return off
        if side == "top" and bars[j].high > level:
            return off
    return None


def markout_survival(traces, bars_by_ticker, closes_by_ticker):
    """Answer 'how long is the signal valid': from the confirmation bar forward, the
    mean signed markout path AND the survival curve — the fraction of confirmed marks
    whose extreme has NOT yet been breached (bottom: price never re-broke the low; top:
    never re-broke the high). `bounced_breach_rate` conditions on the signal first
    moving the predicted way within BOUNCE_H days, then asks how often it still fails.
    Returns (per-(token,horizon) rows, per-token time-to-breach summary)."""
    max_t = max(MARKOUT_HORIZONS)
    ret_acc: dict[tuple, list[float]] = {}
    surv_acc: dict[tuple, list[int]] = {}  # 1 = breached by t
    bounce_acc: dict[tuple, list[int]] = {}  # breached-by-t among bounced marks
    ttb: dict[str, list[int]] = {}
    for tr in traces:
        if tr.category not in EDGE_CATEGORIES or tr.confirm_idx is None:
            continue
        bars = bars_by_ticker[tr.ticker]
        closes = closes_by_ticker[tr.ticker]
        ci = tr.confirm_idx
        token = tr.kind if tr.category == "point" else tr.category
        d = direction(tr.kind)
        side = mark_side(tr.kind)
        fbo = _first_breach_offset(bars, ci, tr.extreme_price, side, max_t)
        if fbo is not None:
            ttb.setdefault(token, []).append(fbo)
        r5 = fwd_return(closes, ci, BOUNCE_H)
        bounced = r5 is not None and d * r5 > 0
        for t in MARKOUT_HORIZONS:
            r = fwd_return(closes, ci, t)
            if r is not None:
                ret_acc.setdefault((token, t), []).append(d * r)
            if ci + t < len(bars):  # only count survival where the full window exists
                bt = 1 if (fbo is not None and fbo <= t) else 0
                surv_acc.setdefault((token, t), []).append(bt)
                if bounced:
                    bounce_acc.setdefault((token, t), []).append(bt)
    tokens = sorted({k[0] for k in surv_acc})
    rows = []
    for token in tokens:
        for t in MARKOUT_HORIZONS:
            sv = surv_acc.get((token, t), [])
            rr = ret_acc.get((token, t), [])
            bb = bounce_acc.get((token, t), [])
            rows.append(
                {
                    "category_token": token,
                    "horizon": t,
                    "n": len(sv),
                    "mean_markout": statistics.fmean(rr) if rr else float("nan"),
                    "breach_rate": statistics.fmean(sv) if sv else float("nan"),
                    "survival": 1 - statistics.fmean(sv) if sv else float("nan"),
                    "bounced_breach_rate": statistics.fmean(bb) if bb else float("nan"),
                }
            )
    ttb_summary = []
    for token in sorted(ttb):
        lags = sorted(ttb[token])
        p90 = lags[min(len(lags) - 1, int(0.9 * len(lags)))]
        ttb_summary.append(
            {
                "category_token": token,
                "n_breached": len(lags),
                "median_time_to_breach": statistics.median(lags),
                "p90_time_to_breach": p90,
            }
        )
    return rows, ttb_summary


def _selftest() -> None:
    closes = [100.0, 101.0, 102.0, 99.0]
    assert abs(fwd_return(closes, 0, 1) - 0.01) < 1e-9
    assert fwd_return(closes, 3, 1) is None  # off the end
    assert direction("3B") == 1.0 and direction("3S") == -1.0
    assert direction("bottom") == 1.0 and direction("top") == -1.0
    # signed edge: a bearish mark that falls is positive edge vs a flat baseline
    base = {1: 0.0}
    tr = ConfTrace("X", "point", "3S", date(2024, 1, 2), 102.0, 2, 2, True, True)
    r = signal_rows(tr, closes, base)
    conf = [x for x in r if x["entry"] == "confirmation" and x["horizon"] == 1][0]
    assert (
        conf["signed_ret"] > 0 and conf["correct"] == 1
    )  # 102 -> 99 down, bearish correct
    # a never-confirmed mark yields NO edge rows (both entries gated on confirmation)
    assert (
        signal_rows(
            ConfTrace(
                "X", "point", "3S", date(2024, 1, 2), 102.0, 2, None, False, False
            ),
            closes,
            base,
        )
        == []
    )
    # cluster bootstrap is deterministic and brackets a positive mean (2 tickers, all +edge)
    crows = [
        {"ticker": "A", "edge": 0.01},
        {"ticker": "A", "edge": 0.02},
        {"ticker": "B", "edge": 0.015},
        {"ticker": "B", "edge": 0.03},
    ]
    lo, hi = cluster_bootstrap_ci(crows, BOOTSTRAP_SEED)
    assert lo > 0 and hi > lo
    # signal rows now carry period + state_edge; with no state args, state_edge == edge
    assert conf["period"] == "H1" and abs(conf["state_edge"] - conf["edge"]) < 1e-12
    # state baseline: bars beyond WARMUP -> callable bucket + populated table
    sc = [100.0 + i for i in range(90)]
    bof, sb = state_baseline(sc)
    assert bof(89) is not None and sb
    # breach detection: bottom level 99, a later low of 97 breaches at offset 2
    bb = [
        ChanlunBar("2024-01-01", 101, 99, 100),
        ChanlunBar("2024-01-02", 103, 100, 102),
        ChanlunBar("2024-01-03", 101, 97, 98),
    ]
    assert _first_breach_offset(bb, 0, 99.0, "bottom", 5) == 2
    assert _first_breach_offset(bb, 0, 90.0, "bottom", 5) is None
    # period robustness: both halves positive -> same_sign True
    prows = [
        {
            "category_token": "divergence",
            "entry": "confirmation",
            "horizon": 1,
            "period": "H1",
            "state_edge": 0.01,
        },
        {
            "category_token": "divergence",
            "entry": "confirmation",
            "horizon": 1,
            "period": "H2",
            "state_edge": 0.02,
        },
    ]
    assert period_robustness(prows)[0]["same_sign"] is True
    # rolling 200-DMA flag: rising series sits above its trailing mean once filled
    av = rolling_above_sma([100.0 + i for i in range(10)], 5)
    assert av[3] is None and av[4] is True
    # trend_agree derives from side + 200-DMA: bottom above the line -> favorable
    br = signal_rows(
        ConfTrace("X", "point", "1B", date(2024, 1, 2), 99.0, 2, 2, True, True),
        closes,
        {1: 0.0, 3: 0.0, 5: 0.0, 10: 0.0, 20: 0.0},
        None,
        None,
        None,
        [None, None, True, True],
    )
    bc = [x for x in br if x["entry"] == "confirmation" and x["horizon"] == 1][0]
    assert bc["trend_agree"] is True and bc["depth_favorable"] is None
    # conditioning report keeps the trend subset and counts it
    condrows = [
        {
            "category_token": "divergence",
            "entry": "confirmation",
            "horizon": 5,
            "period": "H1",
            "state_edge": 0.02,
            "correct": 1,
            "trend_agree": True,
            "depth_favorable": True,
            "ticker": "A",
        },
        {
            "category_token": "divergence",
            "entry": "confirmation",
            "horizon": 5,
            "period": "H2",
            "state_edge": 0.03,
            "correct": 1,
            "trend_agree": True,
            "depth_favorable": False,
            "ticker": "B",
        },
    ]
    trend_out = [
        r
        for r in conditioning_report(condrows)
        if r["filter"] == "trend" and r["horizon"] == 5
    ]
    assert trend_out and trend_out[0]["n"] == 2
    # GEX regime as-of series: no gamma before the first gex date, sign after
    sess = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    br = build_regime_series(sess, ([date(2024, 1, 2)], [5.0]))
    assert br[0] is None and br[1] == "pos" and br[2] == "pos"
    assert build_regime_series(sess, ([date(2024, 1, 1)], [-3.0]))[2] == "neg"
    # gex edge report keeps the pos-gamma subset and counts it
    grows = [
        {
            "category_token": "divergence",
            "entry": "confirmation",
            "horizon": 5,
            "gamma_regime": "pos",
            "trend_agree": True,
            "state_edge": 0.02,
            "correct": 1,
            "ticker": "A",
        },
        {
            "category_token": "divergence",
            "entry": "confirmation",
            "horizon": 5,
            "gamma_regime": "neg",
            "trend_agree": False,
            "state_edge": -0.01,
            "correct": 0,
            "ticker": "B",
        },
    ]
    pos_out = [
        r
        for r in gex_edge_report(grows)
        if r["filter"] == "pos-gamma" and r["horizon"] == 5
    ]
    assert pos_out and pos_out[0]["n"] == 1
    print("selftest OK")


def load_universe() -> list[str]:
    with UNIVERSE_CSV.open() as f:
        return [row["ticker"] for row in csv.DictReader(f)]


def load_gex_cache() -> dict[str, tuple[list[date], list[float]]]:
    """{ticker: (sorted dates, net_gamma)} from the Phase-2 cache, for as-of lookup.
    Empty dict if the cache is absent (regime gate then silently no-ops)."""
    if not GEX_CSV.exists():
        return {}
    acc: dict[str, list[tuple[date, float]]] = {}
    with GEX_CSV.open() as f:
        for row in csv.DictReader(f):
            acc.setdefault(row["ticker"], []).append(
                (date.fromisoformat(row["date"]), float(row["net_gamma"]))
            )
    out: dict[str, tuple[list[date], list[float]]] = {}
    for t, pairs in acc.items():
        pairs.sort()
        out[t] = ([p[0] for p in pairs], [p[1] for p in pairs])
    return out


def build_regime_series(
    session_dates: list[date], gex: tuple[list[date], list[float]] | None
) -> list[str | None]:
    """regime[i] = dealer-gamma regime as-of session_dates[i]: 'pos' (net gamma >= 0,
    mean-reverting) / 'neg' (< 0, amplifying) / None when no GEX on/before that date
    (pre-2023-08 or missing ticker). As-of (latest gex date <= session date) via
    bisect — no lookahead."""
    if gex is None:
        return [None] * len(session_dates)
    gdates, gvals = gex
    out: list[str | None] = []
    for d in session_dates:
        j = bisect.bisect_right(gdates, d) - 1
        out.append(None if j < 0 else ("pos" if gvals[j] >= 0 else "neg"))
    return out


def repaint_rows(traces: list[ConfTrace]) -> list[dict]:
    """Per category_token: retraction rate among ever-confirmed-live marks."""
    groups: dict[str, list[ConfTrace]] = {}
    for t in traces:
        token = t.kind if t.category == "point" else t.category
        groups.setdefault(token, []).append(t)
    out = []
    for token, ts in sorted(groups.items()):
        conf = [t for t in ts if t.ever_confirmed_live]
        retract = [t for t in conf if not t.final_confirmed]
        out.append(
            {
                "category_token": token,
                "n_marks": len(ts),
                "n_confirmed_live": len(conf),
                "retraction_rate": (len(retract) / len(conf)) if conf else float("nan"),
            }
        )
    return out


def write_trace_csv(rows: list[dict], path: Path) -> None:
    cols = [
        "ticker",
        "category_token",
        "kind",
        "extreme_date",
        "entry",
        "period",
        "horizon",
        "mom_bucket",
        "trend_agree",
        "depth_favorable",
        "gamma_regime",
        "signed_ret",
        "signed_baseline",
        "edge",
        "state_edge",
        "correct",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _edge_table(agg, header_note: str) -> list[str]:
    lines = [
        "",
        header_note,
        "",
        "| category | entry | horizon | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for a in agg:
        lines.append(
            f"| {a['category_token']} | {a['entry']} | {a['horizon']} | {a['n']} "
            f"| {a['hit_rate']:.3f} | {a['mean_edge']:+.4f} | {a['edge_ci_lo']:+.4f} "
            f"| {a['edge_ci_hi']:+.4f} | {'yes' if a['ci_excludes_zero'] else ''} |"
        )
    return lines


def write_summary(
    edge_agg,
    state_agg,
    period_rob,
    lag,
    markout,
    ttb,
    cond,
    gex_edge,
    gex_surv,
    repaint,
    n_tickers,
    path: Path,
) -> None:
    lines = [
        "# Chanlun trust probe — silver (adjusted) daily bars",
        "",
        f"Tickers: {n_tickers} | Edge horizons: {HORIZONS} | Markout horizons: {MARKOUT_HORIZONS}",
        "Entry: confirmation (honest, point-in-time) vs extreme (hindsight ghost).",
        f"Reproduce: `{REPRODUCE}`",
        "",
        "Two baselines for `edge = signed_ret − baseline`, both scored ONLY on marks "
        "that eventually confirmed: **unconditional** (same-ticker mean forward return) "
        "and **state-conditioned** (mean forward return of same-ticker bars in the same "
        f"trailing-{STATE_LOOKBACK}-session momentum quantile bucket). The state baseline "
        "isolates the signal's marginal value beyond the regime it fires in — a 底背离 "
        "fires after a decline, so the unconditional edge partly just captures generic "
        "post-decline drift. `ci_excludes_zero` = cluster-bootstrap 95% CI "
        "(resampled by ticker) entirely one side of 0.",
        "",
        "Caveats: (1) the CI resamples tickers for within-ticker overlap but still "
        "assumes tickers are independent and ignores residual serial correlation — "
        "**suggestive, not a p-value**. (2) **Multiple comparisons**: ~80 cells flagged "
        "at 95% → ~4 false positives expected by chance; trust a category only where the "
        "sign is consistent ACROSS horizons and survives the state baseline + both "
        f"period-halves, not single flagged cells. (3) **Economic floor**: a confirmation "
        f"edge below ~{COST_HURDLE:.2%} round-trip cost is not capturable regardless of "
        "significance. (4) `retraction_rate` counts supersession (mark migrating to a "
        "more-extreme endpoint) as retracted. (5) NOT a strategy: no sizing; mega-cap "
        "survivorship → edge is an upper bound.",
        "",
        "## 1. Repaint stability + confirmation lag",
        "",
        "`retraction_rate` = confirmed-live marks that are no longer confirmed in the "
        "final series. `median_lag`/`p90_lag` = sessions from extreme to first "
        "confirmed=true — this lag is exactly the lookahead the extreme (ghost) entry "
        "illegitimately banks.",
        "",
        "| category | n_marks | n_confirmed | retraction_rate | median_lag | p90_lag |",
        "|---|---|---|---|---|---|",
    ]
    lag_by = {r["category_token"]: r for r in lag}
    for r in repaint:
        lg = lag_by.get(r["category_token"], {})
        ml = lg.get("median_lag", float("nan"))
        p90 = lg.get("p90_lag", float("nan"))
        lines.append(
            f"| {r['category_token']} | {r['n_marks']} | {r['n_confirmed_live']} "
            f"| {r['retraction_rate']:.3f} | {ml} | {p90} |"
        )
    lines += _edge_table(
        edge_agg,
        "## 2. Forward-return edge — UNCONDITIONAL baseline (confirmation = honest; extreme = ghost)",
    )
    lines += _edge_table(
        state_agg,
        "## 3. Forward-return edge — STATE-CONDITIONED baseline (the honest test of marginal value)",
    )
    lines += [
        "",
        "## 4. Period robustness — confirmation entry, state edge, first vs second half",
        "",
        "An edge that flips sign between a ticker's first and second half is a period "
        "artifact. `same_sign` = both halves agree.",
        "",
        "| category | horizon | n_h1 | n_h2 | edge_h1 | edge_h2 | same_sign |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in period_rob:
        lines.append(
            f"| {r['category_token']} | {r['horizon']} | {r['n_h1']} | {r['n_h2']} "
            f"| {r['edge_h1']:+.4f} | {r['edge_h2']:+.4f} | {'yes' if r['same_sign'] else 'NO'} |"
        )
    lines += [
        "",
        "## 5. Markout + breach-survival (how long is the signal valid?)",
        "",
        "From the confirmation bar forward: `mean_markout` = mean signed return path; "
        "`survival` = fraction whose extreme has NOT been breached by day t (bottom: "
        "price never re-broke the low; top: never re-broke the high); `breach_rate` = "
        "1 − survival; `bounced_breach_rate` = among marks that first moved the predicted "
        f"way within {BOUNCE_H}d, how often they still breached by t (the 'bounced then "
        "failed' case you asked about).",
        "",
        "| category | horizon | n | mean_markout | survival | breach_rate | bounced_breach_rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in markout:
        lines.append(
            f"| {r['category_token']} | {r['horizon']} | {r['n']} "
            f"| {r['mean_markout']:+.4f} | {r['survival']:.3f} | {r['breach_rate']:.3f} "
            f"| {r['bounced_breach_rate']:.3f} |"
        )
    lines += [
        "",
        "### Time-to-breach (sessions until the extreme is first re-broken)",
        "",
        "| category | n_breached | median_time_to_breach | p90_time_to_breach |",
        "|---|---|---|---|",
    ]
    for r in ttb:
        lines.append(
            f"| {r['category_token']} | {r['n_breached']} "
            f"| {r['median_time_to_breach']} | {r['p90_time_to_breach']} |"
        )
    lines += [
        "",
        f"## 6. Conditioning experiments (Phase 1) — confirmation entry, state edge, h∈{CONDITION_HORIZONS}",
        "",
        "Does filtering confirmed marks lift the edge? `trend` = 200-DMA agreement "
        "(bottom above / top below — the most-replicated mean-reversion filter); "
        "`depth` = fired from an extreme trailing-momentum bucket in the signal's "
        "direction (deep-oversold bottom / sharp-rally top); `trend+depth` = both. "
        "A conditioner earns its keep only if `mean_edge` rises MATERIALLY over `all`, "
        "`CI≠0`, AND `same_sign` holds across both period-halves — otherwise it is "
        "sample-slicing. Watch `n`: a great edge on n<40 is noise.",
        "",
        "| category | horizon | filter | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 | robust |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in cond:
        lines.append(
            f"| {r['category_token']} | {r['horizon']} | {r['filter']} | {r['n']} "
            f"| {r['hit_rate']:.3f} | {r['mean_edge']:+.4f} | {r['edge_ci_lo']:+.4f} "
            f"| {r['edge_ci_hi']:+.4f} | {'yes' if r['ci_excludes_zero'] else ''} "
            f"| {'yes' if r['same_sign'] else ''} |"
        )
    lines += [
        "",
        f"## 7. Phase-2 GEX dealer-gamma regime gate (orthogonal data, ~2023-08→present, h∈{CONDITION_HORIZONS})",
        "",
        "Only confirmations in the UW GEX window (~2.8y — the tier caps single-name "
        "history at ~730 trading days) get a regime, so `in-window` n is roughly HALF "
        "the pooled divergence count; the pre-2023-08 signals are dark. `net_gamma = "
        "call_gamma + put_gamma`; `pos` = net gamma ≥ 0 (dealers dampen → mean-reverting "
        "tape), `neg` = amplifying. Research says GEX is a HOLD/regime gate, not a "
        "direction call — so the test is whether the SAME divergence pays more in a "
        "positive-gamma tape (and, in §7b, holds longer). Caveat: GEX-regime signals "
        "have tested weak/confounded in this stack before — read conservatively.",
        "",
        "### 7a. Edge by regime (divergence + points, confirmation, state edge)",
        "",
        "| category | horizon | filter | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in gex_edge:
        lines.append(
            f"| {r['category_token']} | {r['horizon']} | {r['filter']} | {r['n']} "
            f"| {r['hit_rate']:.3f} | {r['mean_edge']:+.4f} | {r['edge_ci_lo']:+.4f} "
            f"| {r['edge_ci_hi']:+.4f} | {'yes' if r['ci_excludes_zero'] else ''} |"
        )
    lines += [
        "",
        "### 7b. Survival + markout by regime (divergence, does the bounce hold longer?)",
        "",
        "| regime | horizon | n | survival | mean_markout |",
        "|---|---|---|---|---|",
    ]
    for r in gex_surv:
        lines.append(
            f"| {r['regime']} | {r['horizon']} | {r['n']} "
            f"| {r['survival']:.3f} | {r['mean_markout']:+.4f} |"
        )
    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument(
        "--tickers", default="", help="comma list; overrides universe (smoke)"
    )
    ap.add_argument("--limit", type=int, default=0, help="cap ticker count")
    args = ap.parse_args(argv)
    if args.selftest:
        _selftest()
        return 0

    tickers = args.tickers.split(",") if args.tickers else load_universe()
    if args.limit:
        tickers = tickers[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gex_cache = load_gex_cache()  # Phase-2 regime gate (empty dict → no-ops)
    all_traces: list[ConfTrace] = []
    all_signal_rows: list[dict] = []
    bars_by_ticker: dict[str, list] = {}
    closes_by_ticker: dict[str, list[float]] = {}
    regime_by_ticker: dict[str, list[str | None]] = {}
    skipped = []
    for n, t in enumerate(tickers, 1):
        loaded = load_daily(t)
        if not loaded:
            skipped.append(t)
            continue
        bars, closes, sess = loaded
        traces = replay_confirmations(t, bars, sess)
        base = baseline_means(closes)
        bucket_of, sbase = state_baseline(closes)
        above200 = rolling_above_sma(closes, TREND_WINDOW)
        regime = build_regime_series(sess, gex_cache.get(t))
        mid = len(closes) // 2  # per-ticker session midpoint for the H1/H2 split
        all_traces.extend(traces)
        bars_by_ticker[t] = bars
        closes_by_ticker[t] = closes
        regime_by_ticker[t] = regime
        for tr in traces:
            all_signal_rows.extend(
                signal_rows(tr, closes, base, sbase, bucket_of, mid, above200, regime)
            )
        print(f"[{n}/{len(tickers)}] {t}: {len(traces)} marks")

    edge_agg = aggregate(all_signal_rows, "edge")
    state_agg = aggregate(all_signal_rows, "state_edge")
    period_rob = period_robustness(all_signal_rows, "state_edge")
    lag = lag_rows(all_traces)
    markout, ttb = markout_survival(all_traces, bars_by_ticker, closes_by_ticker)
    cond = conditioning_report(all_signal_rows)
    gex_edge = gex_edge_report(all_signal_rows)
    gex_surv = gex_survival(
        all_traces, bars_by_ticker, closes_by_ticker, regime_by_ticker
    )
    repaint = repaint_rows(all_traces)
    write_trace_csv(all_signal_rows, OUT_DIR / "per_signal_trace.csv")
    write_summary(
        edge_agg,
        state_agg,
        period_rob,
        lag,
        markout,
        ttb,
        cond,
        gex_edge,
        gex_surv,
        repaint,
        len(tickers) - len(skipped),
        OUT_DIR / "summary.md",
    )
    print(
        f"done: {len(all_signal_rows)} signal-rows, skipped {len(skipped)}: {skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
