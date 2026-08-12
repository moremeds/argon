"""Which composite construction should stage 2 actually ship?

    uv run python scripts/research/fundamental_weighting_probe.py

THE PROBLEM THIS RESOLVES
-------------------------
The validated result — 2q composite IC 0.039 leak-free, t 2.67 — was produced by an
**equal-weighted** mean of seven raw feature z-scores. Spec §5.2 seeds a *different*
set of weights (0.20 growth / 0.20 profitability / 0.15 capital efficiency / ...),
which §5.2 itself records as **unswept**. Seeding those weights into
`fundamental_method_params` and then citing the IC would ship an unvalidated signal
under a validated number. That is the failure mode this repo keeps writing rules
about, so it gets measured instead of argued.

Three constructions on one panel, same features, same buckets, same metric:

- `equal_7`     — the validated construction. Baseline; nothing else may claim its IC.
- `rubric`      — §5.2's seed weights. Only four of the seven rubric subscores have a
                  measured feature proxy (valuation_position, concentration_risk and
                  expectations_gap draw on inputs this harness does not compute), so
                  0.70 of the stated weight is renormalized to 1.0. That renormalization
                  is itself a departure from the rubric and is why the rubric weights
                  cannot be shipped as "the spec's weights" either.
- `no_margins`  — equal weight over the five features whose measured direction was NOT
                  contradicted, dropping gross_margin and op_margin.

**`no_margins` is post-hoc and is reported as a diagnostic, not a candidate.** It was
constructed after seeing that both margins measured inverted. Selecting components on
their realised sign is exactly the overfit the IC would then be unable to detect, so a
better number here is not evidence it is a better signal — it needs its own out-of-sample
test before it could ship.
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
from fundamental_cost_turnover import build_panel  # noqa: E402
from fundamental_timeseries_test import load_from_db  # noqa: E402

OUT_DIR = Path("docs/research/2026-08-12-fundamental-weighting-probe")

# §5.2 rubric weights mapped onto the features that actually exist. Three rubric
# subscores have no proxy here and are dropped, so the rest renormalize.
RUBRIC: dict[str, float] = {
    "rev_growth": 0.20,  # growth
    "gross_margin": 0.10,  # profitability, split across its two inputs
    "op_margin": 0.10,
    "fcf_margin": 0.075,  # capital_efficiency, split across its two inputs
    "asset_turnover": 0.075,
    "neg_net_debt_ebitda": 0.15,  # balance_sheet
    "roe": 0.0,  # tested but named by no rubric row
}

NO_MARGINS = [f for f in V.FEATURES if f not in ("gross_margin", "op_margin")]

CONSTRUCTIONS: dict[str, dict[str, float]] = {
    "equal_7": {f: 1.0 for f in V.FEATURES},
    "rubric": RUBRIC,
    "no_margins": {f: 1.0 for f in NO_MARGINS},
}


def weighted_composite(
    zs: dict[str, dict[str, float]], tickers: Any, weights: dict[str, float]
) -> dict[str, float]:
    """Weighted mean of available z-scores, renormalized by what is present.

    Mirrors `V.composite_scores` exactly when every weight is 1.0 — verified by
    the self-check below, so `equal_7` genuinely reproduces the validated number
    rather than merely resembling it.
    """
    comp: dict[str, float] = {}
    for t in tickers:
        num = den = 0.0
        got = 0
        for f, w in weights.items():
            if w and f in zs and t in zs[f]:
                num += w * zs[f][t]
                den += w
                got += 1
        if got >= 4 and den:
            comp[t] = num / den
    return comp


def run(
    panel: dict[str, dict[str, Any]], weights: dict[str, float], horizon: int
) -> tuple[dict[str, Any], dict[str, float]]:
    """Returns (summary, per-bucket IC) — the per-bucket series is what makes a
    PAIRED comparison possible. Two constructions built from the same features on
    the same quarters produce heavily correlated IC series, so comparing their
    independent t-stats overstates any difference between them. The difference
    has to be tested on the matched quarters."""
    ics: list[float] = []
    by_bucket: dict[str, float] = {}
    for b in sorted(panel):
        rows = panel[b]
        rets = {t: d["fwd"] for t, d in rows.items() if d["fwd"] is not None}
        if len(rets) < V.MIN_CROSS_SECTION:
            continue
        zs: dict[str, dict[str, float]] = {}
        for feat in V.FEATURES:
            vals = {
                t: rows[t]["features"][feat]
                for t in rets
                if rows[t]["features"].get(feat) is not None
            }
            if len(vals) >= V.MIN_CROSS_SECTION:
                zs[feat] = V.zscore(vals)
        comp = weighted_composite(zs, rets, weights)
        if len(comp) >= V.MIN_CROSS_SECTION:
            ic = V.spearman([comp[t] for t in comp], [rets[t] for t in comp])
            if ic is not None:
                ics.append(ic)
                by_bucket[b] = ic
    return V.summarize(ics), by_bucket


def paired_diff(a: dict[str, float], b: dict[str, float]) -> dict[str, Any]:
    """Paired t-test of (a - b) on the quarters both constructions scored."""
    shared = sorted(set(a) & set(b))
    d = [a[k] - b[k] for k in shared]
    n = len(d)
    if n < 2:
        return {"n": n, "mean_diff": None, "t_stat": None}
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1))
    return {
        "n": n,
        "mean_diff": mu,
        "t_stat": (mu / (sd / math.sqrt(n))) if sd else None,
        "win_rate": sum(1 for x in d if x > 0) / n,
    }


def _self_check(panel: dict[str, dict[str, Any]]) -> None:
    """equal_7 must reproduce V.composite_scores name-for-name, or the baseline
    is not the validated construction and every comparison below is meaningless."""
    for b in sorted(panel)[:5]:
        rows = panel[b]
        rets = {t: d["fwd"] for t, d in rows.items() if d["fwd"] is not None}
        if len(rets) < V.MIN_CROSS_SECTION:
            continue
        zs = {}
        for feat in V.FEATURES:
            vals = {
                t: rows[t]["features"][feat]
                for t in rets
                if rows[t]["features"].get(feat) is not None
            }
            if len(vals) >= V.MIN_CROSS_SECTION:
                zs[feat] = V.zscore(vals)
        a = V.composite_scores(zs, rets)
        b2 = weighted_composite(zs, rets, CONSTRUCTIONS["equal_7"])
        assert a.keys() == b2.keys(), "equal_7 selects a different name set"
        for t in a:
            assert abs(a[t] - b2[t]) < 1e-12, f"equal_7 diverges on {t}"
    print("   self-check ok: equal_7 == V.composite_scores")


def main() -> int:
    panel = build_panel(load_from_db())
    print(f"1. {len(panel)} buckets")
    _self_check(panel)

    results: dict[str, Any] = defaultdict(dict)
    series: dict[str, dict[str, float]] = {}
    for name, weights in CONSTRUCTIONS.items():
        summary, by_bucket = run(panel, weights, 63)
        results[name]["1q"] = summary
        series[name] = by_bucket

    paired = {
        "rubric_vs_equal_7": paired_diff(series["rubric"], series["equal_7"]),
        "no_margins_vs_equal_7": paired_diff(series["no_margins"], series["equal_7"]),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "constructions": {k: v for k, v in CONSTRUCTIONS.items()},
        "note": (
            "no_margins is POST-HOC — components were dropped after seeing their "
            "realised sign. Diagnostic only; not a shippable candidate without an "
            "out-of-sample test."
        ),
        "reproduce": "uv run python scripts/research/fundamental_weighting_probe.py",
        "results": results,
        "paired_vs_baseline": paired,
    }
    (OUT_DIR / "weighting.json").write_text(json.dumps(payload, indent=1))

    lines = [
        "# Which composite construction should ship?",
        "",
        "1q horizon, same panel, same metric. `equal_7` is the validated baseline "
        "and is verified identical to `V.composite_scores`.",
        "",
        "| construction | mean IC | t | quarters |",
        "|---|---:|---:|---:|",
    ]
    print()
    for name in CONSTRUCTIONS:
        r = results[name]["1q"]
        lines.append(
            f"| {name} | {r['mean_ic']:+.4f} | {r['t_stat']:+.2f} | {r['n_quarters']} |"
        )
        print(
            f"   {name:12} IC {r['mean_ic']:+.4f}  t {r['t_stat']:+5.2f}  "
            f"n {r['n_quarters']}"
        )
    lines += [
        "",
        "## Paired against the validated baseline",
        "",
        "Same quarters, matched. Independent t-stats overstate the gap because "
        "both series are built from the same features.",
        "",
        "| comparison | mean IC diff | paired t | quarters | win rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for k, v in paired.items():
        t = "na" if v["t_stat"] is None else f"{v['t_stat']:+.2f}"
        lines.append(
            f"| {k} | {v['mean_diff']:+.4f} | {t} | {v['n']} | {v['win_rate']:.1%} |"
        )
    lines += ["", f"**{payload['note']}**", ""]
    (OUT_DIR / "results.md").write_text("\n".join(lines) + "\n")
    print()
    for k, v in paired.items():
        t = "na" if v["t_stat"] is None else f"{v['t_stat']:+.2f}"
        print(
            f"   paired {k:24} diff {v['mean_diff']:+.4f}  t {t}  "
            f"win {v['win_rate']:.1%}"
        )
    print(f"\n2. wrote {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
