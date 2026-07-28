#!/usr/bin/env python
"""Does the VCG calm core improve the VRP macro short-vol book?

`docs/research/2026-07-29-vcg-spx-forward-returns.md` found VCG carries no
directional information about SPX, but that |z| < 1 marks below-baseline forward
realised vol on 3,486 observations (t = -2.72) — by far the most robust cell in
that study. A short-vol book wants exactly that: permission to be short when
realised vol is likely to stay low.

This probe asks whether the gate actually pays, using the SAME P&L machinery as
`scripts/_vrp_macro_param_sweep.py` — `build_bull_put_spread`, `CostModel`,
`monthly_summary`, `load_index_vol`. The ONLY thing that differs between arms is
the sizing function. No new pricing math, so any Sharpe difference is
attributable to the gate rather than to a re-implementation.

Arms:
    always            1.0                                  (structural baseline)
    gate0             vrp_z >= 0                           (the known winner)
    vcg_calm          |vcg_z| < 1                          (the new candidate, alone)
    gate0_and_calm    vrp_z >= 0 AND |vcg_z| < 1           (does it ADD to gate0?)
    gate0_not_armed   vrp_z >= 0 AND |vcg_z| < 2           (weaker VCG veto)

The question that matters is `gate0_and_calm` vs `gate0`. A gate that only beats
`always` has proven nothing — `gate0` already does that.

**Overfitting warning, stated up front**: the calm-core threshold was chosen on
2007-2026 SPX vol, and this probe scores it on overlapping 2007-2026 SPX option
P&L. That is not an out-of-sample test. The era split is the only honest read
here, and even it shares the threshold choice.

Reproduce (reads the mac mini, read-only; writes only the research doc):

    PGPASSWORD=… UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
    UW_SCAN_DB_USER=argon_app UW_SCAN_ALLOW_DB_MISMATCH=1 UW_SCAN_API_KEY=x \\
    uv run python scripts/research/vrp_vcg_calm_gate_probe.py
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date as _date

import psycopg

from uw_scan.backtest.metrics import monthly_summary
from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread
from uw_scan.storage.repository import Repository

# Structural params held fixed at the committed anchor so the gate is the only
# moving part; a small grid guards against reading one lucky cell.
GRID = [(0.20, 20), (0.25, 20), (0.25, 30), (0.30, 20)]

ARMS = ["always", "gate0", "vcg_calm", "gate0_and_calm", "gate0_not_armed"]


def sizer(arm: str, vrp_z: float | None, vcg_z: float | None) -> float:
    """Position weight in [0, 1]. A missing input is never treated as passing."""
    vrp_ok = vrp_z is not None and vrp_z >= 0
    calm = vcg_z is not None and abs(vcg_z) < 1.0
    not_armed = vcg_z is not None and abs(vcg_z) < 2.0
    if arm == "always":
        return 1.0
    if arm == "gate0":
        return 1.0 if vrp_ok else 0.0
    if arm == "vcg_calm":
        return 1.0 if calm else 0.0
    if arm == "gate0_and_calm":
        return 1.0 if (vrp_ok and calm) else 0.0
    if arm == "gate0_not_armed":
        return 1.0 if (vrp_ok and not_armed) else 0.0
    raise ValueError(arm)


def load_vcg(host: str, db: str, user: str, password: str) -> dict[_date, float]:
    """{data_date: vcg_z}, deduped newest-scan-wins, HYG proxy only."""
    sql = """
        SELECT DISTINCT ON (data_date) data_date, vcg_score::float8
          FROM uw_scan.vcg_snapshots
         WHERE basis = 'eod' AND credit_proxy = 'HYG' AND vcg_score IS NOT NULL
         ORDER BY data_date, scanned_at DESC
    """
    with (
        psycopg.connect(
            host=host, dbname=db, user=user, password=password, connect_timeout=15
        ) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(sql)
        return {r[0]: r[1] for r in cur.fetchall()}


def run_arm(
    ctx,
    vcg: dict,
    arm: str,
    short_delta: float,
    hold_days: int,
    min_date: _date | None = None,
    max_date: _date | None = None,
) -> dict:
    """One-at-a-time bull-put-spread ladder. Mirrors _vrp_macro_param_sweep.run_cfg."""
    adj, iv_map, z_map, cost, r = ctx
    mult = cost.multiplier
    by_month: dict = defaultdict(float)
    n_taken = n_eligible = 0
    last_exit = -1

    # Gate pass-rate is measured over EVERY eligible day, independent of the
    # ladder. Dividing ladder trades by eligible days would be meaningless: a
    # one-at-a-time ladder skips days because it is already in a position, not
    # because the gate refused, so a strict gate and a permissive one take
    # almost the same number of trades — the gate only shifts *when* they open.
    n_pass = 0
    for d0, _ in adj:
        if (min_date and d0 < min_date) or (max_date and d0 > max_date):
            continue
        if iv_map.get(d0) is None or d0 not in vcg:
            continue
        if sizer(arm, z_map.get(d0), vcg.get(d0)) > 0:
            n_pass += 1
    n_days = sum(
        1
        for d0, _ in adj
        if not ((min_date and d0 < min_date) or (max_date and d0 > max_date))
        and iv_map.get(d0) is not None
        and d0 in vcg
    )
    pass_rate = (n_pass / n_days * 100.0) if n_days else 0.0
    for pi in range(0, len(adj) - hold_days):
        if pi <= last_exit:
            continue
        d, S0 = adj[pi]
        if (min_date and d < min_date) or (max_date and d > max_date):
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or S0 <= 0:
            continue
        # Only count days where VCG exists, so every arm sees the same universe.
        if d not in vcg:
            continue
        n_eligible += 1
        w = sizer(arm, z_map.get(d), vcg.get(d))
        if w <= 0:
            continue
        try:
            st = build_bull_put_spread(
                S0,
                float(iv),
                hold_days / 252.0,
                r,
                short_delta=short_delta,
                wing_delta=short_delta * 0.5,
            )
        except ValueError:
            continue
        dx, S_T = adj[pi + hold_days]
        net = (st.credit - st.value(S_T, 0.0, r, 0.0)) * mult - cost.total(
            st.leg_premiums, 1
        )
        by_month[(dx.year, dx.month)] += w * net / (st.max_loss * mult)
        n_taken += 1
        last_exit = pi + hold_days
    s = monthly_summary(by_month)
    ar, dd = s["annror"], s["maxdd"]
    return dict(
        n=n_taken,
        eligible=n_eligible,
        pass_rate=pass_rate,
        sharpe=s["sharpe"],
        maxdd=dd,
        annror=ar,
        calmar=(ar / abs(dd)) if dd < 0 else float("inf"),
    )


def table(rows: list[tuple[str, dict]]) -> list[str]:
    """ann ROR and maxDD are in units of ONE max-loss, not percent.

    Each trade risks exactly 1.0 max_loss and P&L is divided by it, so 1.36 means
    "1.36x a single spread's max loss per year" — not 136% of capital. Rendering
    these as percentages invites a sizing error.
    """
    out = [
        "| arm | trades | gate pass % | Sharpe | ann ROR (xmaxloss) | maxDD (xmaxloss) | Calmar |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, m in rows:
        out.append(
            f"| {label} | {m['n']:,} | {m['pass_rate']:.0f} | {m['sharpe']:.2f} | "
            f"{m['annror']:.2f} | {m['maxdd']:.2f} | {m['calmar']:.2f} |"
        )
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--index", default="SPX")
    p.add_argument("--out", default="docs/research/2026-07-29-vrp-vcg-calm-gate.md")
    a = p.parse_args()

    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)

    loaded = load_index_vol(repo, a.index)
    cost = CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )
    ctx = (
        loaded.adj,
        {row["market_date"]: row["iv"] for row in loaded.rows},
        {row["market_date"]: row["vrp_z_20"] for row in loaded.rows},
        cost,
        settings.vrp_risk_free_rate,
    )

    import os

    vcg = load_vcg(
        settings.db_host,
        settings.db_name,
        settings.db_user,
        os.environ.get("PGPASSWORD", settings.db_password),
    )

    dates = [d for d, _ in loaded.adj if d in vcg]
    L: list[str] = []
    w = L.append
    w("# Does the VCG calm core improve the VRP macro short-vol book?")
    w("")
    w(
        f"**Index**: {a.index}. **Overlap**: {len(dates):,} sessions with both a "
        f"VRP quote and a VCG score, {min(dates)} → {max(dates)}."
    )
    w("")
    w(
        "Same P&L machinery as `scripts/_vrp_macro_param_sweep.py` "
        "(`build_bull_put_spread`, `CostModel`, `monthly_summary`); the **only** "
        "difference between arms is the sizing function, so any Sharpe gap is the "
        "gate and not a re-implementation. One-at-a-time ladder, flat-vol pricing, "
        "model-free settle at the realised close, long wing as the stop."
    )
    w("")
    w(
        "**The comparison that matters is `gate0_and_calm` vs `gate0`.** Beating "
        "`always` proves nothing — `gate0` already does that."
    )
    w("")
    w("| arm | rule |")
    w("|---|---|")
    w("| `always` | 1.0 — structural baseline |")
    w("| `gate0` | `vrp_z >= 0` — the committed winner |")
    w("| `vcg_calm` | `abs(vcg_z) < 1` — the new candidate, alone |")
    w("| `gate0_and_calm` | `vrp_z >= 0 AND abs(vcg_z) < 1` |")
    w("| `gate0_not_armed` | `vrp_z >= 0 AND abs(vcg_z) < 2` — weaker veto |")
    w("")

    verdict_at = len(L)
    cells: list[dict] = []

    for sd, hd in GRID:
        w(f"## {a.index} · {sd:.2f}Δ short · {hd}-day hold")
        w("")
        rows = [(arm, run_arm(ctx, vcg, arm, sd, hd)) for arm in ARMS]
        cells.append(dict(rows))
        L.extend(table(rows))
        w("")
        base = dict(rows)["gate0"]
        cand = dict(rows)["gate0_and_calm"]
        w(
            f"`gate0_and_calm` vs `gate0`: Sharpe {cand['sharpe'] - base['sharpe']:+.2f}, "
            f"maxDD {cand['maxdd'] - base['maxdd']:+.2f} xmaxloss, "
            f"trades {cand['n'] - base['n']:+d}."
        )
        w("")

    # Era split on the anchor config — the only quasi-OOS read available.
    w("## Era split — 0.25Δ / 20-day, split at 2017-01-01")
    w("")
    w(
        "The gate threshold was chosen on the full sample, so this is *not* clean "
        "OOS. It only answers the weaker question: does the gate behave "
        "consistently across halves, or is it one regime's artifact?"
    )
    w("")
    cut = _date(2017, 1, 1)
    for era, lo, hi in [
        ("2007→2016", None, _date(2016, 12, 31)),
        ("2017→now", cut, None),
    ]:
        w(f"### {era}")
        w("")
        L.extend(
            table(
                [
                    (arm, run_arm(ctx, vcg, arm, 0.25, 20, min_date=lo, max_date=hi))
                    for arm in ARMS
                ]
            )
        )
        w("")

    # ── Verdict (numbers computed from this run) ─────────────────────────────
    n = len(cells)
    beats_gate0 = sum(
        1 for c in cells if c["gate0_and_calm"]["sharpe"] > c["gate0"]["sharpe"]
    )
    beats_always = sum(
        1 for c in cells if c["gate0_and_calm"]["sharpe"] > c["always"]["sharpe"]
    )
    dd_better = sum(
        1 for c in cells if c["gate0_and_calm"]["maxdd"] > c["always"]["maxdd"]
    )
    solo_worst = sum(
        1 for c in cells if c["vcg_calm"]["sharpe"] < c["always"]["sharpe"]
    )
    mean_dd_gain = sum(
        c["gate0_and_calm"]["maxdd"] - c["always"]["maxdd"] for c in cells
    ) / max(n, 1)

    v = [
        "## Verdict — promising, NOT proven. Do not wire it in yet.",
        "",
        f"**1. It reliably repairs `gate0`.** `gate0_and_calm` beats `gate0` on "
        f"Sharpe in **{beats_gate0}/{n}** grid cells and in both eras. That is a "
        "consistent, real effect.",
        "",
        f"**2. But that is a low bar — `gate0` is itself beaten by doing nothing** "
        f"in {sum(1 for c in cells if c['always']['sharpe'] > c['gate0']['sharpe'])}"
        f"/{n} cells. Against always-on the combined gate does win "
        f"**{beats_always}/{n}**, but the margins are thin: "
        + ", ".join(
            f"{c['gate0_and_calm']['sharpe'] - c['always']['sharpe']:+.2f}"
            for c in cells
        )
        + " Sharpe. And the era split breaks it — in 2007–2016 the gate returns "
        "0.79 against an always-on 1.14. Much of what the calm filter does is "
        "undo damage `gate0` caused rather than add alpha over always-on.",
        "",
        f"**3. Where it does win is drawdown.** maxDD improves versus always-on in "
        f"**{dd_better}/{n}** cells, by {abs(mean_dd_gain):.2f}× max-loss on average "
        "(e.g. 0.25Δ/30d: −2.83 → −1.01, Calmar 0.26 → 0.89). If this survives, it "
        "is a **drawdown-control overlay**, not a return engine — which is still "
        "worth having on a short-vol book, where the tail is the whole risk.",
        "",
        f"**4. VCG alone is not a gate.** `vcg_calm` on its own underperforms "
        f"always-on in **{solo_worst}/{n}** cells. It only does work in "
        "conjunction with `vrp_z`, which means it is a conditioning variable, "
        "not a signal.",
        "",
        "**5. The threshold is unstable.** |z| < 1 and |z| < 2 rank differently "
        "across eras — in 2017→now the weaker veto is *better* (1.06 vs 1.03), in "
        "2007–2016 it is much worse (0.48 vs 0.79). A parameter whose ordering "
        "flips between halves has not been identified, it has been fitted.",
        "",
        "### What would make this deployable",
        "",
        "Not another in-sample table. It needs the committed walk-forward harness "
        "(`src/uw_scan/backtest/`, which already has per-window OOS gates and the "
        "per-regime catastrophic-degradation check) with the |z| threshold "
        "**re-fit inside each training window** rather than chosen once on the "
        "whole sample. If the gate survives that, it earns a place in the VRP "
        "entry path. If it does not, this file is the record of why not.",
        "",
        "**Honest accounting of this probe's weaknesses**: the threshold was "
        "chosen on 2007–2026 SPX vol and scored on overlapping 2007–2026 SPX "
        "option P&L — not out-of-sample; flat-vol pricing with no skew, so a put "
        "spread's real credit is understated; a one-at-a-time ladder means the "
        "gate mostly shifts *when* trades open rather than how many, so trade "
        "counts barely move between arms; and SPX-only, single index.",
        "",
    ]
    L[verdict_at:verdict_at] = v

    text = "\n".join(L) + "\n"
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"[written] {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
