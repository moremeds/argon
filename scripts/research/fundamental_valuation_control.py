#!/usr/bin/env python
"""Do the margin signals survive a valuation control?

Spec: docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md (§13, top
open item after rev 4).

THE QUESTION
------------
The 245-name validation found `gross_margin` (IC -0.022, t -2.02) and
`op_margin` (-0.024, t -2.56) INVERTED: high-margin names underperformed. §5.2
withdrew the direction claim rather than flipping it, on a stated hypothesis —
nothing in that harness controls for valuation, and high-margin firms are
usually richly priced, so a margin ranking may be partly an expensiveness
ranking.

That was a hypothesis with no test behind it. This is the test.

  H: margin's negative IC is valuation in disguise.
  If H holds  -> margin's PARTIAL IC, controlling for a price ratio, moves
                 toward zero, and the price ratio carries the effect.
  If H fails  -> margin stays negative after the control, and "expensiveness"
                 was a comfortable story rather than an explanation.

Either answer is publishable and both change §5.2: H true restores a direction
claim on `profitability` (the raw signal was confounded, not wrong); H false
means the inversion is real and unexplained, which is a stronger reason to keep
withholding the verdict.

MARKET CAP USES RAW `close`, NOT `adj_close`
--------------------------------------------
`adj_close` is retroactively split-adjusted; `common_stock_shares_outstanding`
is as-reported at the filing. Multiplying the two mixes reference frames and
would misprice every name across every split — NVDA's 10:1 alone would move its
market cap by an order of magnitude. Raw close and as-reported shares are both
point-in-time, so their product is the market cap that was actually observable.

PARTIAL CORRELATION
-------------------
Rank-based, computed from three Spearman correlations on the same
cross-section:

    rho(xy|z) = (rho_xy - rho_xz * rho_zy) / sqrt((1 - rho_xz^2)(1 - rho_zy^2))

Every input comes from `fundamental_signal_validation.spearman`, so the control
and the headline are measured with identical math.

Reproduce (uses the wide cache written by the validation run; refetches only if
absent):

    UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_valuation_control.py

Writes `valuation_control.json` + `valuation-control.md` under
`docs/research/2026-08-11-fundamental-signal-validation/`.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

# The validation module reads `--wide` off argv at import time to pick its cache
# and output suffix. Set it before importing so this script binds to the
# 245-name run rather than the 25-name cohort. Explicit, and the alternative is
# duplicating fetch/TTM/spearman here — which would test the copy, not the claim.
_ARGV = list(sys.argv)  # capture before the rewrite below discards our own flags
sys.argv = [sys.argv[0], "--wide"]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fundamental_signal_validation as V  # noqa: E402

OUT_DIR = V.OUT_DIR
LAKE = V.LAKE
HORIZON = "2q"  # where both margin inversions were significant

# Ratios are formed as YIELDS (fundamental / price), never price / fundamental.
# A P/E flips sign through zero earnings and ranks a loss-maker as the cheapest
# name on the board; earnings/price stays monotone across the whole range.
VALUATION = ["earnings_yield", "book_to_price", "fcf_yield"]
TESTED = ["gross_margin", "op_margin"]


def load_raw_close(tickers: list[str]) -> dict[str, list[tuple[date, float]]]:
    """UNADJUSTED daily closes — see the module docstring on why this is not
    `V.load_prices`, which returns adj_close for return computation."""
    out: dict[str, list[tuple[date, float]]] = {}
    for t in tickers:
        f = LAKE / f"symbol={t}" / "1d.parquet"
        if not f.exists():
            continue
        tab = pq.read_table(f, columns=["trade_date", "close"])
        rows = sorted(
            zip(
                [d for d in tab.column("trade_date").to_pylist()],
                [float(c) for c in tab.column("close").to_pylist()],
            )
        )
        out[t] = rows
    return out


def close_on_or_before(series: list[tuple[date, float]], when: date) -> float | None:
    """Last close at or before the knowledge date. Never after — that would be
    the same look-ahead the point-in-time discipline exists to prevent."""
    lo, hi, found = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= when:
            found = series[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return found


def partial_spearman(xs: list[float], ys: list[float], zs: list[float]) -> float | None:
    """rho(x,y | z), rank-based."""
    rxy, rxz, rzy = V.spearman(xs, ys), V.spearman(xs, zs), V.spearman(zs, ys)
    if None in (rxy, rxz, rzy):
        return None
    denom = math.sqrt(max(0.0, (1 - rxz**2) * (1 - rzy**2)))
    if denom < 1e-12:
        return None
    return (rxy - rxz * rzy) / denom


def main() -> int:
    key = os.environ.get("UW_SCAN_API_KEY", "").strip()
    breadth = json.loads((OUT_DIR / "universe_breadth.json").read_text())
    gate = breadth["gates"]["min_quarters"]
    tickers = sorted(
        r["ticker"] for r in breadth["names"] if (r.get("quarters") or 0) >= gate
    )
    print(f"== universe: {len(tickers)} names")

    if not V.CACHE.exists() and not key:
        print("no cache and UW_SCAN_API_KEY unset", file=sys.stderr)
        return 2
    uw = V.fetch_uw(tickers, key)
    feats = V.build_features(uw)
    adj = V.load_prices(tickers)
    raw = load_raw_close(tickers)
    print(f"   prices: {len(adj)} adjusted, {len(raw)} raw")

    # panel keyed on knowledge-date quarter, matching the validation exactly
    panel: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    no_shares = 0
    for t, pf in feats.items():
        if t not in adj or t not in raw:
            continue
        inc = uw[t]["income-statements"]
        bs = uw[t]["balance-sheets"]
        cf = uw[t]["cash-flows"]
        periods = sorted(inc)
        for i, p in enumerate(periods):
            row = pf.get(p)
            if row is None:
                continue
            know = V.knowledge_date(uw, t, p)
            fwd = V.forward_return(adj[t], know, V.HORIZONS[HORIZON])
            if fwd is None:
                continue
            shares = V._f(bs.get(p), "common_stock_shares_outstanding")
            px = close_on_or_before(raw[t], know)
            if not shares or shares <= 0 or not px:
                no_shares += 1
                continue
            mktcap = px * shares
            ni = V._ttm(inc, periods, i, "net_income")
            ocf = V._ttm(cf, periods, i, "operating_cashflow")
            capex = V._ttm(cf, periods, i, "capital_expenditures")
            eq = V._f(bs.get(p), "total_shareholder_equity")
            fcf = (ocf - abs(capex)) if None not in (ocf, capex) else None
            vals = {
                "earnings_yield": ni / mktcap if ni is not None else None,
                "book_to_price": eq / mktcap if eq is not None else None,
                "fcf_yield": fcf / mktcap if fcf is not None else None,
                "gross_margin": row.get("gross_margin"),
                "op_margin": row.get("op_margin"),
            }
            bucket = f"{know.year}Q{(know.month - 1) // 3 + 1}"
            prior = panel[bucket].get(t)
            if prior and prior["period"] >= p:
                continue
            panel[bucket][t] = {"period": p, "fwd": fwd, **vals}

    buckets = sorted(b for b in panel if len(panel[b]) >= V.MIN_CROSS_SECTION)
    widths = [len(panel[b]) for b in buckets]
    print(
        f"   panel: {len(buckets)} quarters, width min {min(widths)} "
        f"median {sorted(widths)[len(widths) // 2]} max {max(widths)}"
    )
    print(f"   dropped for missing shares/price: {no_shares}")

    # ---- 1. does valuation itself order returns? ----
    own: dict[str, list[float]] = defaultdict(list)
    for b in buckets:
        rows = panel[b]
        for f in VALUATION + TESTED:
            pair = [(r[f], r["fwd"]) for r in rows.values() if r.get(f) is not None]
            if len(pair) >= V.MIN_CROSS_SECTION:
                ic = V.spearman([x for x, _ in pair], [y for _, y in pair])
                if ic is not None:
                    own[f].append(ic)

    print(f"\n== {HORIZON} own IC")
    own_summary = {f: V.summarize(v) for f, v in own.items()}
    for f in VALUATION + TESTED:
        s = own_summary.get(f, {})
        print(
            f"   {f:16} IC {str(s.get('mean_ic')):>8}  t {str(s.get('t_stat')):>7}  "
            f"n {s.get('n_quarters')}"
        )

    # ---- 2. margin IC controlling for each valuation ratio ----
    partials: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for b in buckets:
        rows = panel[b]
        for m in TESTED:
            for v in VALUATION:
                trip = [
                    (r[m], r["fwd"], r[v])
                    for r in rows.values()
                    if r.get(m) is not None and r.get(v) is not None
                ]
                if len(trip) < V.MIN_CROSS_SECTION:
                    continue
                pc = partial_spearman(
                    [a for a, _, _ in trip],
                    [b2 for _, b2, _ in trip],
                    [c for _, _, c in trip],
                )
                if pc is not None:
                    partials[m][v].append(pc)

    print(f"\n== {HORIZON} margin IC, controlling for valuation")
    part_summary: dict[str, dict[str, Any]] = {}
    for m in TESTED:
        part_summary[m] = {}
        raw_s = own_summary.get(m, {})
        print(
            f"   {m}  (uncontrolled IC {raw_s.get('mean_ic')}, t {raw_s.get('t_stat')})"
        )
        for v in VALUATION:
            s = V.summarize(partials[m][v])
            part_summary[m][v] = s
            shrink = (
                f"{(1 - abs(s['mean_ic']) / abs(raw_s['mean_ic'])) * 100:+.0f}% toward 0"
                if s.get("mean_ic") and raw_s.get("mean_ic")
                else "—"
            )
            print(
                f"     | {v:16} partial IC {str(s['mean_ic']):>8}  "
                f"t {str(s['t_stat']):>7}  n {s['n_quarters']}   {shrink}"
            )

    payload = {
        "probed_at": "2026-08-11",
        "reproduce": (
            "UW_SCAN_API_KEY=... uv run python "
            "scripts/research/fundamental_valuation_control.py"
        ),
        "horizon": HORIZON,
        "universe": len(tickers),
        "quarters": len(buckets),
        "cross_section": {
            "min": min(widths),
            "median": sorted(widths)[len(widths) // 2],
            "max": max(widths),
        },
        "own_ic": own_summary,
        "partial_ic": part_summary,
        "note": (
            "Market cap uses RAW close x as-reported shares; adj_close would mix "
            "reference frames across splits. Yields are fundamental/price so the "
            "ranking stays monotone through zero earnings."
        ),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "valuation_control.json").write_text(
        json.dumps(payload, indent=2) + "\n"
    )
    (OUT_DIR / "valuation-control.md").write_text(_render(payload))
    print(f"\nwrote {OUT_DIR}/valuation_control.json and valuation-control.md")
    return 0


def _render(p: dict[str, Any]) -> str:
    lines = [
        "# Valuation control — is the margin inversion expensiveness in disguise?",
        "",
        f"*Probed {p['probed_at']} · REGENERATED on every run · "
        f"{p['universe']} names, {p['quarters']} quarters, "
        f"{p['horizon']} forward return*",
        "",
        "```bash",
        p["reproduce"],
        "```",
        "",
        f"Cross-section width: min {p['cross_section']['min']}, "
        f"median {p['cross_section']['median']}, max {p['cross_section']['max']}.",
        "",
        "## Own IC",
        "",
        "| Signal | IC | t | quarters |",
        "|---|---:|---:|---:|",
    ]
    for f, s in p["own_ic"].items():
        lines.append(
            f"| `{f}` | {s.get('mean_ic')} | {s.get('t_stat')} | {s.get('n_quarters')} |"
        )
    lines += [
        "",
        "## Margin IC controlling for valuation",
        "",
        "| Margin | control | partial IC | t | quarters |",
        "|---|---|---:|---:|---:|",
    ]
    for m, byv in p["partial_ic"].items():
        for v, s in byv.items():
            lines.append(
                f"| `{m}` | `{v}` | {s.get('mean_ic')} | {s.get('t_stat')} | "
                f"{s.get('n_quarters')} |"
            )
    lines += ["", f"> {p['note']}", ""]
    return "\n".join(lines)


def _self_check() -> None:
    """The partial-correlation formula is the one piece of new math here, and a
    sign error in it would quietly reverse the verdict. Three cases where the
    answer is known independently of the implementation."""
    # z unrelated to x and y -> partial ~= raw
    x = [1, 2, 3, 4, 5, 6, 7, 8]
    y = [2, 1, 4, 3, 6, 5, 8, 7]
    z = [5, 5, 5, 5, 5, 5, 5, 5.1]  # near-constant: carries no information
    raw = V.spearman(x, y)
    pc = partial_spearman(x, y, z)
    assert pc is not None and abs(pc - raw) < 0.05, (raw, pc)

    # z == x -> controlling for x removes all of x's explanatory power
    pc = partial_spearman(x, y, list(x))
    assert pc is None or abs(pc) < 1e-9, pc

    # a pure confound: y is driven by z, x correlates with y only through z,
    # so the partial must collapse toward zero while the raw stays high.
    z2 = [1, 2, 3, 4, 5, 6, 7, 8]
    y2 = [1, 2, 3, 4, 5, 6, 7, 8]
    x2 = [1, 2, 3, 4, 5, 6, 7, 8]
    assert V.spearman(x2, y2) == 1.0
    pc = partial_spearman(x2, y2, z2)
    assert pc is None or abs(pc) < 1e-9, pc
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in _ARGV:
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
