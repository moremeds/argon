#!/usr/bin/env python3
"""GEX regime-persistence validation (candidate #3, 2026-07-06 sweep).

Cheap test of the long/short-gamma dealer-positioning hypothesis on data
already banked in ``uw_scan.gex_snapshots``:

  (a) Regime persistence — does the sign of dealer gamma (net_gex < 0 =
      short-gamma) separate NEXT-day realized move, intraday range, and the
      trend-vs-reversal character of returns? Short-gamma dealers amplify
      moves (bigger |return|, more continuation); long-gamma dealers pin
      (smaller |return|, more mean-reversion).
  (b) Flip velocity — is the rate of gex-flip-strike migration elevated in the
      day(s) before a regime sign flip (a leading tell)?

Design notes / honesty caveats:
  * Regime LABEL comes from gex_snapshots: per session we take the last
    snapshot stamped on the SAME calendar day as data_date (drops the
    overnight/pre-market bleed that freezes `spot` at a stale value).
  * Forward RETURNS come from a REAL close series (uw_scan.daily_ohlc,
    source=massive.com) — NOT the noisy intraday gex `spot` — so the move we
    measure is a clean close-to-close number.
  * n is SMALL (~30 joined sessions for SPY as of 2026-07). We lead with
    effect sizes + bootstrap CIs; p-values are underpowered and reported only
    as a sanity flag. This is a go/no-go recalibration test, not a certified
    signal.

Reproduce:
    # local (option_wizard_local — sparse, code sanity only):
    uv run python scripts/research/gex_regime_persistence.py

    # against the mini's banked history (run ON the mini):
    ssh macmini '/opt/homebrew/bin/uv run --project /Users/moremeds/projects/argon \
        python /Users/moremeds/projects/argon/scripts/research/gex_regime_persistence.py \
        --dsn "dbname=option_wizard" --tickers SPY,TLT --out-prefix /tmp/gex_regime'

Writes: <out-prefix>.<TICKER>.sessions.csv  (full per-session trace)
        <out-prefix>.summary.json            (all buckets + stats, machine-readable)
        <out-prefix>.summary.md              (human writeup)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass

import numpy as np
import psycopg

# --- reproducibility: fixed seed for the bootstrap ---------------------------
RNG = np.random.default_rng(20260706)

QUERY = """
with daily as (
  select
    data_date,
    (array_agg(net_gex               order by scanned_at desc))[1] as net_gex,
    (array_agg(spot                  order by scanned_at desc))[1] as spot,
    (array_agg(level_gex_flip_strike order by scanned_at desc))[1] as flip
  from uw_scan.gex_snapshots
  where ticker = %(ticker)s
    and scanned_at::date = data_date   -- same-calendar-day snapshots only
    and net_gex is not null
  group by data_date
)
select d.data_date, d.net_gex, d.spot, d.flip,
       o.close, o.high, o.low
from daily d
join uw_scan.daily_ohlc o
  on o.ticker = %(ticker)s and o.date = d.data_date
order by d.data_date
"""


@dataclass
class Session:
    date: str
    net_gex: float
    spot: float | None
    flip: float | None
    close: float
    high: float
    low: float
    # derived (filled in pass 2)
    ret: float | None = None  # close[t]/close[t-1]-1 (today's realized move)
    fwd_ret: float | None = None  # close[t+1]/close[t]-1 (what the label predicts)
    fwd_range: float | None = None  # (high[t+1]-low[t+1])/close[t] intraday RV proxy
    fwd_reversal: int | None = None  # 1 if sign(fwd_ret) != sign(ret), else 0
    regime: str = ""  # "short" (net_gex<0) | "long"
    flip_gap: float | None = None  # (spot-flip)/spot
    flip_migration: float | None = None  # (flip[t]-flip[t-1])/close[t]


def _f(x) -> float | None:
    return None if x is None else float(x)


def load_sessions(conn: psycopg.Connection, ticker: str) -> list[Session]:
    with conn.cursor() as cur:
        cur.execute(QUERY, {"ticker": ticker})
        rows = cur.fetchall()
    sess = [
        Session(
            date=str(r[0]),
            net_gex=float(r[1]),
            spot=_f(r[2]),
            flip=_f(r[3]),
            close=float(r[4]),
            high=float(r[5]),
            low=float(r[6]),
        )
        for r in rows
    ]
    # pass 2: derive today/forward return, range, reversal, regime, flip velocity
    for i, s in enumerate(sess):
        s.regime = "short" if s.net_gex < 0 else "long"
        if s.spot and s.flip:
            s.flip_gap = (s.spot - s.flip) / s.spot
        if i > 0 and sess[i - 1].flip and s.flip:
            s.flip_migration = (s.flip - sess[i - 1].flip) / s.close
        if i > 0:
            s.ret = s.close / sess[i - 1].close - 1.0
        if i < len(sess) - 1:
            nxt = sess[i + 1]
            s.fwd_ret = nxt.close / s.close - 1.0
            s.fwd_range = (nxt.high - nxt.low) / s.close
            if s.ret is not None:
                s.fwd_reversal = int((s.fwd_ret < 0) != (s.ret < 0))
    return sess


def _boot_diff_ci(
    a: list[float], b: list[float], n: int = 10000
) -> tuple[float, float]:
    """95% bootstrap CI on mean(a) - mean(b)."""
    if not a or not b:
        return (float("nan"), float("nan"))
    aa, bb = np.array(a), np.array(b)
    diffs = np.empty(n)
    for k in range(n):
        diffs[k] = RNG.choice(aa, aa.size).mean() - RNG.choice(bb, bb.size).mean()
    return (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def _mann_whitney_u_p(a: list[float], b: list[float]) -> float | None:
    """Two-sided Mann-Whitney U p-value via normal approx (no scipy dep)."""
    na, nb = len(a), len(b)
    if na < 3 or nb < 3:
        return None
    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort(key=lambda t: t[0])
    # rank with ties -> average ranks
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-based
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_a = sum(rk for rk, (_, g) in zip(ranks, combined) if g == 0)
    u_a = r_a - na * (na + 1) / 2
    mu = na * nb / 2
    sigma = (na * nb * (na + nb + 1) / 12) ** 0.5
    if sigma == 0:
        return None
    z = (u_a - mu) / sigma
    # two-sided normal tail
    from math import erf, sqrt

    p = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))
    return max(0.0, min(1.0, p))


def _stat_block(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
    }


def analyze(ticker: str, sess: list[Session]) -> dict:
    usable = [s for s in sess if s.fwd_ret is not None]
    short = [s for s in usable if s.regime == "short"]
    long_ = [s for s in usable if s.regime == "long"]

    def col(rows, attr):
        return [getattr(r, attr) for r in rows if getattr(r, attr) is not None]

    abs_short = [abs(r.fwd_ret) for r in short]
    abs_long = [abs(r.fwd_ret) for r in long_]

    rev_short = col(short, "fwd_reversal")
    rev_long = col(long_, "fwd_reversal")

    # flip velocity: |migration| in the 1 day before a regime sign flip vs elsewhere
    pre_flip, baseline = [], []
    for i in range(1, len(sess) - 1):
        mig = sess[i].flip_migration
        if mig is None:
            continue
        regime_flips_next = sess[i].regime != sess[i + 1].regime
        (pre_flip if regime_flips_next else baseline).append(abs(mig))

    out = {
        "ticker": ticker,
        "n_sessions": len(sess),
        "n_usable": len(usable),
        "date_range": [sess[0].date, sess[-1].date] if sess else [],
        "regime_persistence": {
            "abs_fwd_ret": {
                "short_gamma": _stat_block(abs_short),
                "long_gamma": _stat_block(abs_long),
                "diff_short_minus_long": (
                    statistics.fmean(abs_short) - statistics.fmean(abs_long)
                    if abs_short and abs_long
                    else None
                ),
                "boot95_ci_diff": _boot_diff_ci(abs_short, abs_long),
                "mann_whitney_p": _mann_whitney_u_p(abs_short, abs_long),
            },
            "fwd_range_pct": {
                "short_gamma": _stat_block(col(short, "fwd_range")),
                "long_gamma": _stat_block(col(long_, "fwd_range")),
            },
            "signed_fwd_ret": {
                "short_gamma": _stat_block(col(short, "fwd_ret")),
                "long_gamma": _stat_block(col(long_, "fwd_ret")),
            },
            "reversal_rate": {
                "short_gamma": (statistics.fmean(rev_short) if rev_short else None),
                "long_gamma": (statistics.fmean(rev_long) if rev_long else None),
                "note": "higher = more mean-reversion; hypothesis: long>short",
            },
        },
        "flip_velocity": {
            "abs_migration_pre_regime_flip": _stat_block(pre_flip),
            "abs_migration_baseline": _stat_block(baseline),
        },
    }
    return out


def verdict(a: dict) -> str:
    rp = a["regime_persistence"]
    d = rp["abs_fwd_ret"]["diff_short_minus_long"]
    ci = rp["abs_fwd_ret"]["boot95_ci_diff"]
    if d is None:
        return "INSUFFICIENT — one bucket empty"
    lo, hi = ci
    ci_excludes_zero = (lo > 0) or (hi < 0)
    direction_ok = d > 0  # short-gamma bigger move = hypothesis direction
    if ci_excludes_zero and direction_ok:
        return "SEPARATION (CI excludes 0, hypothesis direction) — worth a real build"
    if direction_ok:
        return (
            "DIRECTIONALLY CONSISTENT but CI spans 0 — underpowered, not tradable as-is"
        )
    return "NO SEPARATION / WRONG SIGN — recalibrate positioning-alpha thesis down"


def write_csv(path: str, sess: list[Session]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(sess[0]).keys()) if sess else [])
        w.writeheader()
        for s in sess:
            w.writerow(asdict(s))


def _fmt_pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.3f}%"


def write_md(path: str, results: list[dict]) -> None:
    lines = ["# GEX regime-persistence — validation result\n"]
    lines.append(
        "**Candidate #3** (2026-07-06 sweep). Regime label from "
        "`gex_snapshots` (net_gex sign), forward returns from real "
        "`daily_ohlc` closes.\n"
    )
    for a in results:
        rp = a["regime_persistence"]
        af = rp["abs_fwd_ret"]
        lines.append(
            f"\n## {a['ticker']}  ({a['date_range'][0]} → {a['date_range'][-1]}, "
            f"n_usable={a['n_usable']})\n"
        )
        lines.append(f"**Verdict: {verdict(a)}**\n")
        lines.append(
            "| bucket | n | mean \\|fwd ret\\| | median | fwd range% | reversal rate |"
        )
        lines.append("|---|---|---|---|---|---|")
        for reg, key in [("short-gamma", "short_gamma"), ("long-gamma", "long_gamma")]:
            sb = af[key]
            rng = rp["fwd_range_pct"][key]
            rev = rp["reversal_rate"][key]
            lines.append(
                f"| {reg} | {sb.get('n', 0)} | {_fmt_pct(sb.get('mean'))} | "
                f"{_fmt_pct(sb.get('median'))} | {_fmt_pct(rng.get('mean'))} | "
                f"{'n/a' if rev is None else f'{rev:.2f}'} |"
            )
        diff = af["diff_short_minus_long"]
        lo, hi = af["boot95_ci_diff"]
        lines.append(
            f"\n- Δ mean\\|fwd ret\\| (short−long): **{_fmt_pct(diff)}**, "
            f"boot95 CI [{_fmt_pct(lo)}, {_fmt_pct(hi)}], "
            f"Mann-Whitney p={af['mann_whitney_p']}"
        )
        fv = a["flip_velocity"]
        pre = fv["abs_migration_pre_regime_flip"]
        base = fv["abs_migration_baseline"]
        lines.append(
            f"- Flip velocity: \\|migration\\| pre-regime-flip mean="
            f"{_fmt_pct(pre.get('mean'))} (n={pre.get('n', 0)}) vs baseline "
            f"{_fmt_pct(base.get('mean'))} (n={base.get('n', 0)})"
        )
    lines.append(
        "\n---\n*n is small (~30 sessions); effect sizes + bootstrap CIs "
        "lead, p-values are underpowered sanity flags only.*\n"
    )
    with open(path, "w") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dsn",
        default=os.environ.get("GEX_STUDY_DSN", ""),
        help="psycopg DSN; empty → uw_scan.config.Settings.from_env()",
    )
    ap.add_argument("--tickers", default="SPY,TLT")
    ap.add_argument(
        "--out-prefix", default="docs/research/2026-07-06-gex-regime-persistence"
    )
    args = ap.parse_args()

    dsn = args.dsn
    if not dsn:
        # lazy import so the tripwire only fires when we actually need Settings
        from uw_scan.config import Settings

        dsn = Settings.from_env().db_dsn()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    results = []
    with psycopg.connect(dsn, connect_timeout=8) as conn:
        for tk in tickers:
            sess = load_sessions(conn, tk)
            if not sess:
                print(f"[{tk}] no joined sessions — skipping", file=sys.stderr)
                continue
            write_csv(f"{args.out_prefix}.{tk}.sessions.csv", sess)
            a = analyze(tk, sess)
            results.append(a)
            print(f"[{tk}] {a['n_usable']} usable sessions → {verdict(a)}")

    if not results:
        print("no results (empty join across all tickers)", file=sys.stderr)
        return 1

    with open(f"{args.out_prefix}.summary.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    write_md(f"{args.out_prefix}.summary.md", results)
    print(f"wrote {args.out_prefix}.summary.{{json,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
