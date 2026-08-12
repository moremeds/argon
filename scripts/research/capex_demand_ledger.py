"""Does BUYER capex lead SUPPLIER revenue? Measure it, per supply-chain link.

    uv run python scripts/research/capex_demand_ledger.py

Named-customer edges do not exist in filings (spec §3.4: `"NVIDIA accounted for"`
-> 0 EDGAR hits), segment shares need an XBRL hierarchy the feed does not carry
(77/257 computable), and geographic shares have no denominator at all (0/257).
Capex has none of those problems: it is a top-level line in the BUYER's own
cash-flow statement, disclosed quarterly, naming nobody.

So the demand link is approached from the buyer's side. For each curated link,
aggregate buyer capex and supplier revenue per quarter and ask whether the
buyer's growth LEADS the supplier's -- which is the only version of this that is
worth anything, since a contemporaneous ratio tells you nothing you did not
already know when the supplier reported.

METHOD NOTES, each one load-bearing:

* Fiscal calendars differ (NVDA quarters end Apr/Jul/Oct/Jan; MSFT's FY ends in
  June), so every period is bucketed by the calendar quarter it mostly covers:
  `period_end - 1 month`, truncated. Apr 30 covers Feb-Apr -> Q1. Jun 30 covers
  Apr-Jun -> Q2.
* BALANCED PANEL. Aggregate growth across a changing membership is not growth --
  a ticker entering mid-series steps the aggregate for a non-economic reason.
  Only tickers present in EVERY quarter of the window contribute, and the
  dropped names are reported rather than silently excluded.
* Both legs sit inside the same capex expansion, so a correlation of levels, or
  even of YoY growth, is partly mechanical. ACCELERATION (the quarter-over-
  quarter change in YoY growth) is reported beside it as the harder test: it
  removes the shared trend that makes everything in this sector look correlated.
* Correlation at n<12 is reported with its n and nothing is claimed from it.

Nothing is written to Postgres: this decides whether a feature should exist.
Trace lands in docs/research/2026-08-13-ai-capex-demand-ledger/.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from uw_scan.config import Settings  # noqa: E402

OUT = Path("docs/research/2026-08-13-ai-capex-demand-ledger")

#: Curated buyer -> supplier links. Chains come from `uw_scan.watchlist_chain`,
#: which already encodes supply-chain layer; the DIRECTION of spend is the part
#: a taxonomy cannot know, so it is named here explicitly and reviewably.
#:
#: `semi_capex_cycle` is the CONTROL: foundry capex driving wafer-fab-equipment
#: revenue is a decades-old, externally documented relationship. If the method
#: cannot see a lead there, it has not earned belief on the AI link where the
#: answer is unknown.
LINKS: dict[str, dict[str, Any]] = {
    "ai_datacenter": {
        "why": "hyperscaler + neocloud capex builds the datacenter its suppliers sell into",
        "buyers": ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"],
        "suppliers": [
            "Computer/GPU",
            "Memory/Storage",
            "Networking/Optical",
            "Power/Electrical",
            "Cooling/Thermal",
            "EPC/Construction",
        ],
    },
    "semi_capex_cycle": {
        # Memory sits on BOTH sides of this ledger and belongs on both: memory
        # fabs are among the largest wafer-fab-equipment buyers, and HBM/SSD
        # ships into the same datacenters. Excluding them from the buyer leg
        # removes the most cyclical component of WFE demand, which is the swing
        # the control is supposed to detect.
        "why": "CONTROL -- foundry AND memory capex drive wafer-fab-equipment revenue",
        "buyers": ["Foundry", "Memory/Storage"],
        "suppliers": ["Semi-Cap/EDA"],
    },
    "semi_wfe_only": {
        # Same control, one contaminant removed. `Semi-Cap/EDA` carries CDNS and
        # SNPS (EDA software, licensed per-seat), ARM (IP royalties) and AMKR
        # (assembly/test, paid per unit) beside the actual toolmakers. None of
        # those three revenue models track a fab's capex, so leaving them in the
        # supplier leg dilutes exactly the signal the control looks for.
        "why": "CONTROL v2 -- equipment makers only, EDA/IP/OSAT removed",
        "buyers": ["Foundry", "Memory/Storage"],
        "supplier_tickers": [
            "ACLS",
            "AEIS",
            "AMAT",
            "ASML",
            "CAMT",
            "COHU",
            "FORM",
            "ICHR",
            "KLAC",
            "LRCX",
            "NVMI",
            "ONTO",
            "TER",
            "UCTT",
            "VECO",
        ],
    },
    "datacenter_power": {
        "why": "buildout pulls generation and grid equipment",
        "buyers": ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"],
        "suppliers": ["Generation/Nuclear", "Power/Electrical"],
    },
}

#: Quarters required before a link is analysed at all.
MIN_QUARTERS = 12

#: Most recent quarters considered. Balancing happens INSIDE this window -- see
#: `balanced` for why the full history cannot be used.
WINDOW_QUARTERS = 20

BUCKET = "date_trunc('quarter', period_end - interval '1 month')::date"


def series(
    conn,
    chains: list[str] | None,
    statement: str,
    field: str,
    tickers: list[str] | None = None,
) -> dict:
    """Per-(quarter, ticker) values for a chain set, or an explicit ticker list.

    Deduped to the latest `period_end` inside each calendar bucket, because a
    fiscal-calendar shift can land two filings in one bucket.

    `tickers` exists because a chain is not always the right unit: `Semi-Cap/EDA`
    lumps wafer-fab equipment together with EDA software and IP licensing, whose
    revenue does not track anyone's capex.
    """
    member_sql = (
        "join (select unnest(%s::text[]) as ticker) w using (ticker)"
        if tickers is not None
        else """join (select distinct ticker from uw_scan.watchlist_chain
                      where chain = any(%s)) w using (ticker)"""
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            with q as (
              select {BUCKET} as cq, o.ticker,
                     (o.raw_jsonb->>%s)::numeric as v,
                     row_number() over (
                       partition by o.ticker, {BUCKET}
                       order by o.period_end desc) rn
              from uw_scan.fundamental_statement_obs o
              {member_sql}
              where o.period_type = 'quarterly'
                and o.statement = %s
                and o.raw_jsonb->>%s is not null
            )
            select cq, ticker, v from q where rn = 1 order by cq, ticker
            """,
            (field, tickers if tickers is not None else chains, statement, field),
        )
        out: dict = defaultdict(dict)
        for cq, ticker, v in cur.fetchall():
            out[cq][ticker] = float(v)
        return dict(out)


def balanced(
    per_q: dict, min_quarters: int, window: int
) -> tuple[list, list, list[str], list[str]]:
    """Aggregate over the tickers present in EVERY quarter of a RECENT window.

    Returns (quarters, totals, kept, dropped). Growth over a changing membership
    is composition, not growth -- so membership is fixed first and what fell out
    is returned for reporting, never silently discarded.

    The window matters as much as the balancing. Intersecting across the full
    2005->2026 history returns the EMPTY set for any link containing a recent
    listing: CoreWeave and the neoclouds have no 2005 quarter, so demanding
    presence in every quarter drops literally every buyer and silently yields a
    zero series. The link under test only exists in recent history anyway.
    """
    quarters = sorted(q for q in per_q if per_q[q])[-window:]
    if len(quarters) < min_quarters:
        return quarters, [], [], []
    everywhere = set(per_q[quarters[0]])
    for q in quarters[1:]:
        everywhere &= set(per_q[q])
    seen = {t for q in quarters for t in per_q[q]}
    kept, dropped = sorted(everywhere), sorted(seen - everywhere)
    if not kept:
        # No ticker spans the window: an all-zero series would otherwise sail
        # through as a valid result and divide into None ratios downstream.
        return quarters, [], [], dropped
    totals = [sum(abs(per_q[q][t]) for t in kept) for q in quarters]
    return quarters, totals, kept, dropped


def yoy(values: list[float]) -> list[float | None]:
    """Year-over-year growth. None where the base is missing or non-positive."""
    out: list[float | None] = [None] * len(values)
    for i in range(4, len(values)):
        base = values[i - 4]
        out[i] = (values[i] / base - 1.0) if base > 0 else None
    return out


def accel(g: list[float | None]) -> list[float | None]:
    """Change in YoY growth -- the shared-trend-free version of the same test."""
    out: list[float | None] = [None] * len(g)
    for i in range(1, len(g)):
        if g[i] is not None and g[i - 1] is not None:
            out[i] = g[i] - g[i - 1]
    return out


def corr_at_lag(buyer: list, supplier: list, lag: int) -> dict[str, Any]:
    """Pearson correlation of buyer[t] against supplier[t+lag]."""
    pairs = [
        (buyer[i], supplier[i + lag])
        for i in range(len(buyer))
        if i + lag < len(supplier)
        and buyer[i] is not None
        and supplier[i + lag] is not None
    ]
    if len(pairs) < 4:
        return {"lag": lag, "n": len(pairs), "r": None}
    bs = [p[0] for p in pairs]
    ss = [p[1] for p in pairs]
    if len(set(bs)) < 2 or len(set(ss)) < 2:
        return {"lag": lag, "n": len(pairs), "r": None}
    return {"lag": lag, "n": len(pairs), "r": round(statistics.correlation(bs, ss), 4)}


def analyse(conn, name: str, spec: dict) -> dict[str, Any]:
    cap_raw = series(
        conn,
        spec.get("buyers"),
        "cash_flow",
        "capital_expenditures",
        tickers=spec.get("buyer_tickers"),
    )
    rev_raw = series(
        conn,
        spec.get("suppliers"),
        "income",
        "total_revenue",
        tickers=spec.get("supplier_tickers"),
    )

    cq, cap, cap_keep, cap_drop = balanced(cap_raw, MIN_QUARTERS, WINDOW_QUARTERS)
    rq, rev, rev_keep, rev_drop = balanced(rev_raw, MIN_QUARTERS, WINDOW_QUARTERS)
    if not cap or not rev:
        return {
            "why": spec["why"],
            "status": "insufficient_history",
            "buyer_quarters": len(cq),
            "supplier_quarters": len(rq),
        }

    # Intersect the two calendars -- a lag is meaningless across ragged windows.
    common = sorted(set(cq) & set(rq))
    if len(common) < MIN_QUARTERS:
        return {"why": spec["why"], "status": "insufficient_overlap", "n": len(common)}
    cap = [cap[cq.index(q)] for q in common]
    rev = [rev[rq.index(q)] for q in common]

    cap_g, rev_g = yoy(cap), yoy(rev)
    ratio = [round(r / c, 4) if c else None for c, r in zip(cap, rev, strict=True)]
    band = [x for x in ratio if x is not None]

    return {
        "why": spec["why"],
        "status": "ok",
        "quarters": [str(q) for q in common],
        "buyers_kept": cap_keep,
        "buyers_dropped_unbalanced": cap_drop,
        "suppliers_kept": rev_keep,
        "suppliers_dropped_unbalanced": rev_drop,
        "buyer_capex_bn": [round(v / 1e9, 2) for v in cap],
        "supplier_revenue_bn": [round(v / 1e9, 2) for v in rev],
        "supplier_rev_over_buyer_capex": ratio,
        "ratio_band": {
            "min": min(band),
            "max": max(band),
            "median": round(statistics.median(band), 4),
        }
        if band
        else None,
        "growth_yoy": [corr_at_lag(cap_g, rev_g, k) for k in range(5)],
        "acceleration": [corr_at_lag(accel(cap_g), accel(rev_g), k) for k in range(5)],
    }


def main() -> int:
    settings = Settings.from_env()
    results: dict[str, Any] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        for name, spec in LINKS.items():
            results[name] = analyse(conn, name, spec)
            r = results[name]
            print(f"\n=== {name} ({r['status']}) — {spec['why']}")
            if r["status"] != "ok":
                print(f"    {r}")
                continue
            print(
                f"    {len(r['quarters'])}q  buyers={len(r['buyers_kept'])} "
                f"suppliers={len(r['suppliers_kept'])}  "
                f"ratio {r['ratio_band']['min']}..{r['ratio_band']['max']}"
            )
            for label in ("growth_yoy", "acceleration"):
                cells = "  ".join(f"L{c['lag']}={c['r']}(n{c['n']})" for c in r[label])
                print(f"    {label:13s} {cells}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "capex_lead_lag.json").write_text(
        json.dumps(
            {
                "probe": "buyer capex vs supplier revenue, per supply-chain link",
                "reproduce": "uv run python scripts/research/capex_demand_ledger.py",
                "min_quarters": MIN_QUARTERS,
                "links": results,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"\nwrote {OUT / 'capex_lead_lag.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
