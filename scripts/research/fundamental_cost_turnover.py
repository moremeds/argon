"""Does the 245-name ranking survive turnover and transaction costs?

    uv run python scripts/research/fundamental_cost_turnover.py

An IC of 0.039 is an ordering. The distance from ordering to net-of-cost P&L is
where most signals die, and nothing measured so far has crossed it. This forms an
actual portfolio from the validated composite, measures what it costs to hold,
and reports the cost level at which its edge disappears.

WHAT IS REUSED, AND WHY THAT MATTERS HERE
-----------------------------------------
The composite is scored by `fundamental_signal_validation.composite_scores` — the
same implementation the IC result was produced with, extracted for this purpose
and verified byte-identical against the committed `validation_wide.json`. Costing
a subtly different composite would measure a different signal than the one
validated, and the discrepancy would be invisible in both sets of numbers.
Statements come from Postgres via the time-series test's loader, so there is one
DB reshape in the repo rather than three.

MODEL
-----
- Rebalance quarterly, at knowledge-quarter buckets. Hold the top slice by
  composite, equal-weighted.
- Benchmark is the equal-weighted panel on the same dates. Alpha is the
  difference, so the market leg cancels and what remains is selection.
- One-way turnover = fraction of the book replaced at a rebalance. Cost per
  rebalance = turnover x round-trip bps: replacing 30% of the book means selling
  30% and buying 30%, which is 30% of a round trip.
- Costs are SWEPT (0/5/10/20/50 bps) rather than assumed, and the break-even
  round-trip cost is reported directly. A single assumed number would hide
  whether the answer was the signal or the assumption.

KNOWN IDEALISATIONS, stated rather than buried
----------------------------------------------
- Entry is staggered: each name's forward return starts at its OWN knowledge
  date, so the "quarterly portfolio" is an average of positions opened across the
  quarter, not a single-day rebalance. Standard for this kind of study, and it
  flatters nothing — it is how the IC was measured too.
- No capacity, borrow, or market-impact model. The bps sweep stands in for all of
  it, which is why the break-even number is the honest headline rather than any
  single net figure.
- Survivorship: the panel holds live tickers only, which biases returns UP. The
  net figures are therefore optimistic before any cost assumption is argued.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fundamental_signal_validation as V  # noqa: E402
from fundamental_timeseries_test import knowledge_date, load_from_db  # noqa: E402

OUT_DIR = Path("docs/research/2026-08-12-fundamental-cost-turnover")

HORIZON = 63  # trading days ~ one quarter, matching the rebalance cadence
COST_BPS = [0, 5, 10, 20, 50]
QUARTERS_PER_YEAR = 4


def build_panel(uw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """bucket -> ticker -> {features, fwd}. Knowledge-quarter keyed.

    Keyed on the knowledge quarter, never on `fiscal_date_ending`: filers do not
    share a fiscal calendar, and keying on the raw period end shattered the
    cross-section into thin slices in an earlier revision of the validation.
    """
    feats = V.build_features(uw)
    prices = V.load_prices(sorted(uw))
    panel: dict[str, dict[str, Any]] = defaultdict(dict)
    for t, pf in feats.items():
        px = prices.get(t)
        if not px:
            continue
        for period in sorted(pf):
            know = knowledge_date(uw, t, period)
            fwd = V.forward_return(px, know, HORIZON)
            if fwd is None:
                continue
            bucket = f"{know.year}Q{(know.month - 1) // 3 + 1}"
            prior = panel[bucket].get(t)
            if prior and prior["period"] >= period:
                continue  # one name, one vote per cross-section; keep the fresher
            panel[bucket][t] = {"features": pf[period], "fwd": fwd, "period": period}
    return dict(panel)


def scores_for(rows: dict[str, Any]) -> dict[str, float]:
    """Cross-sectional composite for one bucket, via the validated implementation."""
    zs: dict[str, dict[str, float]] = {}
    for feat in V.FEATURES:
        vals = {
            t: d["features"][feat]
            for t, d in rows.items()
            if d["features"].get(feat) is not None
        }
        if len(vals) >= V.MIN_CROSS_SECTION:
            zs[feat] = V.zscore(vals)
    return V.composite_scores(zs, rows)


def run(
    panel: dict[str, dict[str, Any]], top_frac: float, side: str = "top"
) -> dict[str, Any]:
    """Equal-weighted slice of the ranking, benchmarked against the whole panel.

    `side` exists because a rank IC measures the ordering across the WHOLE
    distribution, which does not say where in it the information sits. A signal
    whose content is entirely in the bottom slice — "these names are worse" —
    produces a real IC and no top-slice alpha at all. That is a different product
    (an avoid-list, usable long-only) than a buy ranking, and only splitting the
    tails distinguishes them.
    """
    buckets = sorted(panel)
    trace: list[dict[str, Any]] = []
    held: set[str] = set()
    for b in buckets:
        rows = panel[b]
        comp = scores_for(rows)
        if len(comp) < V.MIN_CROSS_SECTION:
            continue
        n = max(1, round(len(comp) * top_frac))
        ranked = sorted(comp, key=lambda t: comp[t], reverse=True)
        picks = ranked[:n] if side == "top" else ranked[-n:]
        bench = [d["fwd"] for d in rows.values()]
        gross = sum(rows[t]["fwd"] for t in picks) / len(picks)
        # First rebalance is a full purchase, not a swap: charging it 0 turnover
        # would credit the strategy with a free entry it does not get.
        turnover = 1.0 if not held else 1 - len(held & set(picks)) / len(picks)
        trace.append(
            {
                "bucket": b,
                "n_universe": len(comp),
                "n_held": len(picks),
                "gross": gross,
                "benchmark": sum(bench) / len(bench),
                "alpha": gross - sum(bench) / len(bench),
                "turnover": turnover,
            }
        )
        held = set(picks)

    alphas = [r["alpha"] for r in trace]
    turns = [r["turnover"] for r in trace]
    n = len(alphas)
    mean_alpha = sum(alphas) / n if n else 0.0
    sd = (
        math.sqrt(sum((a - mean_alpha) ** 2 for a in alphas) / (n - 1))
        if n > 1
        else 0.0
    )
    mean_turn = sum(turns) / n if n else 0.0

    net = {}
    for bps in COST_BPS:
        cost = mean_turn * bps / 10_000
        na = mean_alpha - cost
        net[str(bps)] = {
            "quarterly_alpha": na,
            "annualized": na * QUARTERS_PER_YEAR,
            "sharpe": (na / sd * math.sqrt(QUARTERS_PER_YEAR)) if sd else None,
        }
    return {
        "top_frac": top_frac,
        "side": side,
        "quarters": n,
        "gross_quarterly_alpha": mean_alpha,
        "alpha_sd": sd,
        "t_stat": (mean_alpha / (sd / math.sqrt(n))) if sd and n > 1 else None,
        "hit_rate": (sum(1 for a in alphas if a > 0) / n) if n else None,
        "mean_turnover": mean_turn,
        "annual_turnover": mean_turn * QUARTERS_PER_YEAR,
        # The number that decides it: the round-trip cost at which the edge is
        # exactly consumed.
        "breakeven_round_trip_bps": (mean_alpha / mean_turn * 10_000)
        if mean_turn
        else None,
        "net_by_cost_bps": net,
        "trace": trace,
    }


def decile_profile(panel: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Mean return, median return and mean RETURN-RANK per composite decile.

    This is the diagnostic that reconciles a significantly positive rank IC with
    a portfolio that earns nothing, and neither statistic alone can show it:

    - mean return is what an equal-weighted book actually earns;
    - median return is what the typical name in the decile does;
    - mean return-rank (0..1 within each bucket) is what the IC is measuring.

    When median and return-rank climb with the decile but mean does not, the mean
    is being carried by skew rather than by the ordering.
    """
    dec: dict[int, dict[str, list[float]]] = {
        d: {"ret": [], "rank": []} for d in range(10)
    }
    for rows in panel.values():
        comp = scores_for(rows)
        if len(comp) < V.MIN_CROSS_SECTION:
            continue
        ranked = sorted(comp, key=lambda t: comp[t])  # ascending: 0 = worst
        n = len(ranked)
        rets = [rows[t]["fwd"] for t in ranked]
        order = sorted(range(n), key=lambda i: rets[i])
        rr = [0.0] * n
        for pos, i in enumerate(order):
            rr[i] = pos / (n - 1) if n > 1 else 0.5
        for i in range(n):
            d = min(9, int(10 * i / n))
            dec[d]["ret"].append(rets[i])
            dec[d]["rank"].append(rr[i])
    out = []
    for d in range(10):
        r = sorted(dec[d]["ret"])
        if not r:
            continue
        out.append(
            {
                "decile": d,
                "n": len(r),
                "mean_return": sum(r) / len(r),
                "median_return": r[len(r) // 2],
                "mean_return_rank": sum(dec[d]["rank"]) / len(dec[d]["rank"]),
            }
        )
    return out


def main() -> int:
    print("1. loading statements from Postgres ...", flush=True)
    uw = load_from_db()
    panel = build_panel(uw)
    print(f"   {len(panel)} knowledge-quarter buckets")

    # Gate: this panel must reproduce the validated IC, or it is not the same
    # signal and no cost figure computed from it means anything.
    buckets = sorted(panel)
    _, comp_ics = V.quarterly_ics(
        {
            b: {t: {**d, "fwd": {"1q": d["fwd"]}} for t, d in rows.items()}
            for b, rows in panel.items()
        },
        buckets,
        "1q",
    )
    ic_check = V.summarize(comp_ics)
    print(
        f"   panel IC check (1q): {ic_check['mean_ic']:+.4f} "
        f"t {ic_check['t_stat']:+.2f} over {ic_check['n_quarters']} quarters"
    )

    results: dict[str, Any] = {}
    for f in (0.10, 0.20, 0.33):
        for side in ("top", "bottom"):
            results[f"{side}_{int(f * 100)}pct"] = run(panel, f, side)

    # The spread is the honest summary of the ordering's economic content, and is
    # reported for diagnosis only — a 50-name short book is not implementable on
    # this desk, so it must never be quoted as an achievable return.
    for f in (0.10, 0.20, 0.33):
        top = results[f"top_{int(f * 100)}pct"]
        bot = results[f"bottom_{int(f * 100)}pct"]
        by_bucket = {r["bucket"]: r["alpha"] for r in bot["trace"]}
        spread = [
            r["alpha"] - by_bucket[r["bucket"]]
            for r in top["trace"]
            if r["bucket"] in by_bucket
        ]
        n = len(spread)
        mu = sum(spread) / n if n else 0.0
        sd = math.sqrt(sum((x - mu) ** 2 for x in spread) / (n - 1)) if n > 1 else 0.0
        results[f"spread_{int(f * 100)}pct"] = {
            "quarters": n,
            "gross_quarterly_alpha": mu,
            "t_stat": (mu / (sd / math.sqrt(n))) if sd and n > 1 else None,
            "hit_rate": (sum(1 for x in spread if x > 0) / n) if n else None,
            "annualized_gross": mu * QUARTERS_PER_YEAR,
            "note": "diagnostic only — long/short, not implementable on this desk",
        }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "horizon_days": HORIZON,
        "cost_bps_swept": COST_BPS,
        "panel_ic_1q": ic_check,
        "decile_profile": decile_profile(panel),
        "reproduce": "uv run python scripts/research/fundamental_cost_turnover.py",
        "results": results,
    }
    (OUT_DIR / "cost_turnover.json").write_text(json.dumps(payload, indent=1))

    lines = [
        "# Cost and turnover — does the 245-name ranking survive being traded?",
        "",
        f"Quarterly rebalance, {HORIZON}-day holds, equal-weighted, benchmarked "
        "against the equal-weighted panel. Cost per rebalance = turnover x "
        "round-trip bps.",
        "",
        f"Panel IC check (1q): **{ic_check['mean_ic']:+.4f}**, t "
        f"{ic_check['t_stat']:+.2f}, {ic_check['n_quarters']} quarters — the "
        "panel reproduces the validated signal.",
        "",
        "| slice | quarters | gross q-alpha | t | hit | ann. turnover | break-even bps |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, r in results.items():
        t = "na" if r["t_stat"] is None else f"{r['t_stat']:+.2f}"
        be = (
            f"{r['breakeven_round_trip_bps']:,.0f}"
            if r.get("breakeven_round_trip_bps") is not None
            else "na"
        )
        turn = f"{r['annual_turnover']:.2f}x" if "annual_turnover" in r else "—"
        lines.append(
            f"| {name} | {r['quarters']} | {r['gross_quarterly_alpha']:+.4f} | {t} | "
            f"{r['hit_rate']:.1%} | {turn} | {be} |"
        )
    lines += [
        "",
        "## Decile profile — why a positive IC earns nothing",
        "",
        "0 = worst composite, 9 = best. `return-rank` is what the IC measures;",
        "`mean` is what an equal-weighted book earns.",
        "",
        "| decile | mean return | median return | mean return-rank | n |",
        "|---:|---:|---:|---:|---:|",
    ]
    for d in payload["decile_profile"]:
        lines.append(
            f"| {d['decile']} | {d['mean_return']:+.4f} | {d['median_return']:+.4f} "
            f"| {d['mean_return_rank']:.3f} | {d['n']:,} |"
        )
    lines += [
        "",
        "## Net annualized alpha by round-trip cost",
        "",
        "| slice | " + " | ".join(f"{b} bps" for b in COST_BPS) + " |",
        "|---|" + "---:|" * len(COST_BPS),
    ]
    for name, r in results.items():
        if "net_by_cost_bps" not in r:
            continue
        cells = " | ".join(
            f"{r['net_by_cost_bps'][str(b)]['annualized']:+.2%}" for b in COST_BPS
        )
        lines.append(f"| {name} | {cells} |")
    (OUT_DIR / "results.md").write_text("\n".join(lines) + "\n")

    print(f"\n2. wrote {OUT_DIR}/\n")
    for name, r in results.items():
        turn = (
            f"turnover {r['annual_turnover']:.2f}x/yr  "
            if "annual_turnover" in r
            else ""
        )
        be = (
            f"break-even {r['breakeven_round_trip_bps']:,.0f} bps"
            if r.get("breakeven_round_trip_bps") is not None
            else ""
        )
        print(
            f"   {name:16} gross q-alpha {r['gross_quarterly_alpha']:+.4f}  "
            f"t {r['t_stat']:+5.2f}  " + turn + be
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
