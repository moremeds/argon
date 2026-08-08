"""E2 — does the 0.618 measured-move target beat a matched null? (spec §3.4)

A rising leg has upward drift baked into its own definition, so a high raw hit
rate is exactly what "no edge" looks like. Running this geometry over driftless
GBM still returns a 38.3% hit rate across 1517 legs, purely from barrier
asymmetry — `up` is the far stretch target, `down` the nearer support. Only
`edge_vs_null` is interpretable.

The comparison is against a BLOCK-BOOTSTRAP null built from the ticker's own
returns up to the entry bar: it preserves drift, volatility, fat tails and
autocorrelation without estimating any of them, which sidesteps the
drift-estimation problem that makes a parametric GBM null unusable over ~154
days.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def measured_move(
    resistance: float, support: float, ratio: float = 0.618
) -> tuple[float, float]:
    """(stretch, down) = R + ratio*leg, S - ratio*leg where leg = R - S."""
    if resistance <= support:
        raise ValueError(f"resistance {resistance} must exceed support {support}")
    leg = resistance - support
    return resistance + ratio * leg, support - ratio * leg


def first_passage(
    highs: Sequence[float],
    lows: Sequence[float],
    up: float,
    down: float,
    max_bars: int,
) -> str:
    """Which barrier price touches first: "hit" | "stop" | "ambiguous" | "neither".

    Uses high/low rather than close because a target is touched intrabar. When a
    single bar spans BOTH barriers the intrabar order is unknowable from daily
    data — that returns "ambiguous" and is reported as its own bucket. Assigning
    it to either side would silently bias the hit rate in whichever direction was
    guessed.
    """
    for i in range(min(max_bars, len(highs), len(lows))):
        touched_up = highs[i] >= up
        touched_down = lows[i] <= down
        if touched_up and touched_down:
            return "ambiguous"
        if touched_up:
            return "hit"
        if touched_down:
            return "stop"
    return "neither"


def bootstrap_null_hit_rate(
    returns: Sequence[float],
    start_price: float,
    up: float,
    down: float,
    max_bars: int,
    *,
    block: int,
    n_paths: int,
    seed: int,
) -> dict:
    """Outcome shares under paths resampled from the ticker's own log returns.

    Vectorised over paths: the barrier test is an argmax over boolean matrices
    rather than a Python loop per path. The scalar version ran ~10^8 interpreter
    steps across the full sweep.

    Synthetic paths carry no intrabar range, so both barriers are tested against
    the same synthetic close. That makes "ambiguous" impossible in the null and
    is why the observed sample reports it separately rather than folding it in.
    """
    rets = np.asarray(returns, dtype=float)
    rets = rets[np.isfinite(rets)]
    if rets.size < block:
        raise ValueError(f"sample of {rets.size} shorter than block {block}")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(max_bars / block))

    # (n_paths, n_blocks) block starts -> (n_paths, max_bars) return matrix
    starts = rng.integers(0, rets.size - block + 1, size=(n_paths, n_blocks))
    idx = starts[:, :, None] + np.arange(block)[None, None, :]
    paths = start_price * np.exp(
        np.cumsum(rets[idx].reshape(n_paths, -1)[:, :max_bars], axis=1)
    )

    up_hit = paths >= up
    down_hit = paths <= down
    any_up, any_down = up_hit.any(axis=1), down_hit.any(axis=1)
    # argmax on a boolean row returns the first True; guard with any_* since
    # argmax on an all-False row returns 0, which would read as "touched at bar 0".
    first_up = np.where(any_up, up_hit.argmax(axis=1), max_bars + 1)
    first_down = np.where(any_down, down_hit.argmax(axis=1), max_bars + 1)

    n_hit = int(np.sum(first_up < first_down))
    n_stop = int(np.sum(first_down < first_up))
    n_neither = int(np.sum(~any_up & ~any_down))
    return {
        "hit": n_hit / n_paths,
        "stop": n_stop / n_paths,
        "ambiguous": 0.0,
        "neither": n_neither / n_paths,
    }


def clustered_bootstrap_edge(
    legs: Sequence[dict], *, n_boot: int, seed: int, alpha: float
) -> dict:
    """CI on mean(outcome - null_hit), resampling TICKERS not legs.

    Two dependencies make a naive per-leg CI far too narrow:

      1. Legs from one ticker OVERLAP. A leg's 60-bar forward window can contain
         the next leg's entry, so their outcomes share price path.
      2. Tickers share a common market factor, and this watchlist is concentrated
         in AI/semis.

    Resampling whole tickers (a cluster bootstrap) keeps both dependencies intact.
    Resampling legs would treat 20 correlated legs as 20 independent observations
    and shrink the interval by roughly sqrt(20).

    `alpha` is the two-sided level AFTER multiplicity adjustment. E2 sweeps five
    k_atr values and reports the best; testing the best config's point estimate
    against zero at an unadjusted level passes 70-97% of the time when the true
    edge is exactly zero.
    """
    decided = [
        r
        for r in legs
        if r["outcome"] != "ambiguous" and r.get("null_hit") == r.get("null_hit")
    ]
    if not decided:
        return {
            "point": float("nan"),
            "lo": float("nan"),
            "hi": float("nan"),
            "n": 0,
            "n_clusters": 0,
        }

    by_ticker: dict[str, list[float]] = {}
    for r in decided:
        by_ticker.setdefault(r["ticker"], []).append(
            (1.0 if r["outcome"] == "hit" else 0.0) - r["null_hit"]
        )
    keys = list(by_ticker)
    point = float(np.mean([v for vals in by_ticker.values() for v in vals]))
    if len(keys) < 2:
        return {
            "point": point,
            "lo": float("nan"),
            "hi": float("nan"),
            "n": len(decided),
            "n_clusters": len(keys),
        }

    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        picked = rng.integers(0, len(keys), size=len(keys))
        vals = [v for j in picked for v in by_ticker[keys[j]]]
        stats[i] = float(np.mean(vals))
    lo, hi = np.percentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {
        "point": point,
        "lo": float(lo),
        "hi": float(hi),
        "n": len(decided),
        "n_clusters": len(keys),
        "alpha": alpha,
    }
