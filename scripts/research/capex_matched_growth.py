"""Capex lead-lag, measured over FULL history instead of a 20-quarter window.

    uv run python scripts/research/capex_matched_growth.py

`capex_demand_ledger.py` measured this over 20 quarters and its control failed.
That window was not a data limit -- the store holds 83 quarters (2005 Q4 ->
2026 Q2) for AMAT, LRCX, KLAC, ASML, TSM, INTC and MU. The window was imposed by
the BALANCED PANEL: requiring every ticker to be present in every quarter, then
intersecting across 2005->2026, returns the empty set the moment a link contains
a recent listing. Twenty quarters was the largest window that kept CoreWeave.

That is the wrong trade. A semiconductor-capex control measured across a single
AI boom cannot fail informatively -- there is no downturn in it to detect.

MATCHED-SAMPLE GROWTH removes the constraint. Aggregate LEVELS need a fixed
membership or a ticker entering mid-series steps the total for a non-economic
reason. Aggregate GROWTH does not: for each quarter, sum only over the tickers
present in BOTH t and t-4, and take the ratio. Membership may change freely
between quarters, because every quarter's growth is computed against its own
matched base. Same logic as same-store sales. A new listing joins as soon as it
has five quarters and contributes from then on, so the semi control now spans
2008, 2015-16, 2019 and 2020 -- four cycles with real downturns.

What this adds beyond the window fix:

* A CONTROL THE UNIVERSE SUPPORTS. The semi control's buyers are mostly unlisted
  (Samsung, SK Hynix, Kioxia, SMIC, CXMT), which the earlier verdict named as an
  untestable explanation for its failure. Utility capex -> electrical contractor
  revenue has both legs US-listed and 83 quarters: DUK/SO/D/AEP/EXC/ED spend,
  PWR/MTZ/EME/DY build. If the method works anywhere, it works there.
* A DOSE-RESPONSE TEST, which is the way around the segment-data blocker. If
  buyer capex really drives supplier revenue, the effect must be STRONGER for
  suppliers whose revenue is mostly datacenter (VRT, CRDO, ALAB, NVDA, ANET,
  SMCI) than for suppliers where it is a minority (HPQ, DELL, CSCO, ETN, MOD).
  Equal correlations mean both are just tracking the same macro trend. This
  needs no segment disclosure at all -- purity is asserted per ticker, in the
  open, and the two sets are compared over a COMMON window so the pure-plays'
  shorter (boom-only) history cannot manufacture the result.
* SPLIT-HALF STABILITY. n is now large enough to ask whether a correlation
  exists in both halves of its own sample or only one.

CAVEAT, unresolved and load-bearing: YoY growth at quarterly frequency overlaps
four quarters, so the series is strongly autocorrelated and the reported t is
inflated -- effective n is well below nominal n. Treat t as a sorting device
between links, never as a significance test. `acceleration` is differenced and
closer to independent; prefer it whenever the two disagree.

Nothing is written to Postgres: this decides whether a feature should exist.
Trace lands in docs/research/2026-08-13-ai-capex-demand-ledger/.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from uw_scan.config import Settings  # noqa: E402

OUT = Path("docs/research/2026-08-13-ai-capex-demand-ledger")

BUCKET = "date_trunc('quarter', period_end - interval '1 month')::date"

#: Minimum matched quarters before a link is reported at all.
MIN_QUARTERS = 12

#: Suppliers whose revenue is MOSTLY datacenter today. Asserted, not derived --
#: the segment data that would derive it is computable for 77/257 names with
#: every relevant mega-cap failing. Stating the assertion in the open is the
#: honest version; hiding it behind a computation we cannot do is not.
DC_PURE = ["VRT", "CRDO", "ALAB", "NVDA", "ANET", "SMCI"]

#: Suppliers sitting in the same chains whose datacenter exposure is a minority:
#: HPQ (consumer PCs and printers), DELL (about 60% client), CSCO (enterprise
#: campus), ETN and MOD (datacenter is a segment, not the business).
DC_DILUTED = ["HPQ", "DELL", "CSCO", "ETN", "MOD"]

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
        "why": "CONTROL -- foundry AND memory capex drive wafer-fab-equipment revenue",
        "buyers": ["Foundry", "Memory/Storage"],
        "suppliers": ["Semi-Cap/EDA"],
    },
    "semi_wfe_only": {
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
    "utility_grid": {
        # The control the earlier verdict said the universe could not supply.
        # Regulated utilities spend, engineering contractors build. Both legs
        # US-listed, both 83 quarters, and the relationship is externally
        # documented rather than something this probe hopes to discover.
        "why": "CONTROL v3 -- utility capex drives electrical contractor revenue, BOTH legs listed",
        "buyer_tickers": ["DUK", "SO", "D", "AEP", "EXC", "ED"],
        "supplier_tickers": ["PWR", "MTZ", "EME", "DY"],
    },
    "datacenter_power": {
        "why": "buildout pulls generation and grid equipment",
        "buyers": ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"],
        "suppliers": ["Generation/Nuclear", "Power/Electrical"],
    },
    "dc_pure_play": {
        "why": "DOSE-RESPONSE high -- suppliers whose revenue is mostly datacenter",
        "buyers": ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"],
        "supplier_tickers": DC_PURE,
    },
    "dc_diluted": {
        "why": "DOSE-RESPONSE low -- same chains, datacenter is a minority of revenue",
        "buyers": ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"],
        "supplier_tickers": DC_DILUTED,
    },
}


def series(
    conn,
    chains: list[str] | None,
    statement: str,
    field: str,
    tickers: list[str] | None = None,
) -> dict:
    """Per-(quarter, ticker) values, deduped to the latest filing in each bucket.

    Fiscal calendars differ, so each period is bucketed by the calendar quarter
    it mostly covers: `period_end - 1 month`, truncated.
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


def matched_yoy(per_q: dict) -> tuple[list, list[float | None], list[int]]:
    """YoY growth over the tickers present in BOTH t and t-4.

    Returns (quarters, growth, matched_ticker_count). This is the whole point of
    the rewrite: no fixed membership is required, so full history is usable and
    a ticker joins the moment it has five quarters. A quarter whose matched set
    is empty, or whose matched base is non-positive, yields None rather than a
    fabricated number.
    """
    quarters = sorted(q for q in per_q if per_q[q])
    index = {q: i for i, q in enumerate(quarters)}
    growth: list[float | None] = []
    counts: list[int] = []
    for i, q in enumerate(quarters):
        base_q = quarters[i - 4] if i >= 4 else None
        # Four positions back is only four QUARTERS back if the series has no
        # holes; check the calendar rather than trusting the index.
        if (
            base_q is None
            or (q.year - base_q.year) * 4 + (q.month - base_q.month) // 3 != 4
        ):
            base_q = next(
                (
                    p
                    for p in quarters
                    if (q.year - p.year) * 4 + (q.month - p.month) // 3 == 4
                ),
                None,
            )
        if base_q is None or base_q not in index:
            growth.append(None)
            counts.append(0)
            continue
        both = set(per_q[q]) & set(per_q[base_q])
        now = sum(abs(per_q[q][t]) for t in both)
        then = sum(abs(per_q[base_q][t]) for t in both)
        growth.append(now / then - 1.0 if then > 0 and both else None)
        counts.append(len(both))
    return quarters, growth, counts


def accel(g: list[float | None]) -> list[float | None]:
    """Change in YoY growth -- differenced, so far less autocorrelated."""
    out: list[float | None] = [None] * len(g)
    for i in range(1, len(g)):
        if g[i] is not None and g[i - 1] is not None:
            out[i] = g[i] - g[i - 1]
    return out


def corr(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Pearson r and its naive t. The t is INFLATED for overlapping YoY series."""
    if len(xs) < 4 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None, None
    r = statistics.correlation(xs, ys)
    if abs(r) >= 1.0:
        return round(r, 4), None
    t = r * math.sqrt((len(xs) - 2) / (1 - r * r))
    return round(r, 4), round(t, 2)


def pairs_at_lag(buyer: list, supplier: list, lag: int) -> tuple[list, list]:
    """buyer[t] against supplier[t+lag]. NEGATIVE lag = the supplier leads.

    The lower bound is not defensive padding: a negative index in Python wraps
    to the end of the list, so without it lag -2 would silently pair the first
    quarters of the buyer series against the LAST two quarters of the supplier's
    and return a number that looks like a correlation.
    """
    got = [
        (buyer[i], supplier[i + lag])
        for i in range(len(buyer))
        if 0 <= i + lag < len(supplier)
        and buyer[i] is not None
        and supplier[i + lag] is not None
    ]
    return [p[0] for p in got], [p[1] for p in got]


def lag_profile(buyer: list, supplier: list, halves: bool = True) -> list[dict]:
    """Correlation at lags 0-4, each with n, t, and a split-half check.

    A relationship that appears in only one half of its own sample is a period
    effect, not a relationship -- and with full history there are finally enough
    observations to ask.
    """
    rows = []
    for lag in range(5):
        xs, ys = pairs_at_lag(buyer, supplier, lag)
        r, t = corr(xs, ys)
        row: dict[str, Any] = {"lag": lag, "n": len(xs), "r": r, "t_naive": t}
        if halves and len(xs) >= 16:
            mid = len(xs) // 2
            row["r_first_half"] = corr(xs[:mid], ys[:mid])[0]
            row["r_second_half"] = corr(xs[mid:], ys[mid:])[0]
        rows.append(row)
    return rows


def analyse(conn, spec: dict, window: int | None = None) -> dict[str, Any]:
    """`window` truncates to the last N matched quarters AFTER growth is computed.

    That ordering is the point of the flag. `capex_demand_ledger.py` restricted
    the window BEFORE aggregating and had to fix membership to do it, so window
    and method were confounded: its result could have come from either. Here the
    growth series is identical in both runs and only its tail is selected, which
    isolates the window as the single moving part.
    """
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
    cq, cap_g, cap_n = matched_yoy(cap_raw)
    rq, rev_g, rev_n = matched_yoy(rev_raw)

    common = sorted(set(cq) & set(rq))
    if window:
        common = common[-window:]
    if len(common) < MIN_QUARTERS:
        return {"why": spec["why"], "status": "insufficient_overlap", "n": len(common)}
    cap_g = [cap_g[cq.index(q)] for q in common]
    rev_g = [rev_g[rq.index(q)] for q in common]
    cap_n = [cap_n[cq.index(q)] for q in common]
    rev_n = [rev_n[rq.index(q)] for q in common]

    return {
        "why": spec["why"],
        "status": "ok",
        "span": [str(common[0]), str(common[-1])],
        "quarters": len(common),
        "buyers_matched_last": cap_n[-1],
        "suppliers_matched_last": rev_n[-1],
        "buyer_growth_yoy": [round(g, 4) if g is not None else None for g in cap_g],
        "supplier_growth_yoy": [round(g, 4) if g is not None else None for g in rev_g],
        "growth_yoy": lag_profile(cap_g, rev_g),
        "acceleration": lag_profile(accel(cap_g), accel(rev_g)),
    }


def dose_response(results: dict) -> dict[str, Any]:
    """Compare pure-play against diluted suppliers on a COMMON window.

    The pure-plays are younger, so their unrestricted history sits entirely
    inside the AI boom -- which would hand them a higher correlation for a
    reason that has nothing to do with purity. Both sets are therefore reported
    with their spans so the comparison can be read honestly.
    """
    pure, dil = results.get("dc_pure_play"), results.get("dc_diluted")
    if not pure or not dil or pure["status"] != "ok" or dil["status"] != "ok":
        return {"status": "unavailable"}
    out = {"status": "ok", "pure_span": pure["span"], "diluted_span": dil["span"]}
    for metric in ("growth_yoy", "acceleration"):
        out[metric] = [
            {
                "lag": p["lag"],
                "pure_r": p["r"],
                "diluted_r": d["r"],
                "gap": round(p["r"] - d["r"], 4)
                if p["r"] is not None and d["r"] is not None
                else None,
            }
            for p, d in zip(pure[metric], dil[metric], strict=True)
        ]
    return out


def per_supplier(conn, spec: dict, window: int | None) -> list[dict]:
    """Each supplier's OWN revenue growth against the shared buyer-capex growth.

    The aggregate hides its own dispersion. A set-level correlation of -0.29 can
    mean every member is -0.29, or that one name dominates the matched sum and
    the rest are noise around zero -- and those support opposite conclusions.
    Per-ticker is also the honest unit for the dose-response claim: purity is
    asserted per ticker, so it should be checked per ticker.
    """
    cap_raw = series(
        conn,
        spec.get("buyers"),
        "cash_flow",
        "capital_expenditures",
        tickers=spec.get("buyer_tickers"),
    )
    cq, cap_g, _ = matched_yoy(cap_raw)
    rev_raw = series(
        conn,
        spec.get("suppliers"),
        "income",
        "total_revenue",
        tickers=spec.get("supplier_tickers"),
    )
    tickers = sorted({t for q in rev_raw for t in rev_raw[q]})
    rows = []
    for tkr in tickers:
        own = {q: {tkr: v[tkr]} for q, v in rev_raw.items() if tkr in v}
        rq, rev_g, _ = matched_yoy(own)
        common = sorted(set(cq) & set(rq))
        if window:
            common = common[-window:]
        if len(common) < MIN_QUARTERS:
            continue
        b = [cap_g[cq.index(q)] for q in common]
        s = [rev_g[rq.index(q)] for q in common]
        row: dict[str, Any] = {"ticker": tkr, "quarters": len(common)}
        # TWO-SIDED. Every earlier run tested only buyer->supplier, which assumes
        # the answer. The per-supplier table says the assumption is wrong for the
        # compute names: NVDA and SMCI correlate NEGATIVELY at every positive lag
        # while the optical and connector names peak at +1/+2. A supplier whose
        # revenue is recognised on shipment can easily lead the capex that shows
        # up when the building around it is finished -- so the negative side has
        # to be measured, not assumed away.
        for lag in (-4, -3, -2, -1, 0, 1, 2, 3, 4):
            xs, ys = pairs_at_lag(b, s, lag)
            row[f"r_{lag:+d}"] = corr(xs, ys)[0]
        best = [(row[f"r_{lag:+d}"], lag) for lag in range(-4, 5) if row[f"r_{lag:+d}"]]
        row["peak_lag"] = max(best)[1] if best else None
        row["peak_r"] = max(best)[0] if best else None
        rows.append(row)
    return sorted(rows, key=lambda r: (r["peak_r"] is None, r["peak_lag"] or 0))


#: The whole AI 产业链, ordered by where a layer sits relative to the buildout.
#: Software is included deliberately: if the ledger is a supply-chain claim it
#: has to cover the chain, and the layer where it should be WEAKEST is the one
#: that tests whether the method distinguishes anything at all. A method that
#: reports the same strength for switchgear and for cybersecurity SaaS is
#: measuring the macro cycle, not the chain.
CHAIN_LAYERS: dict[str, list[str]] = {
    "0 upstream tools": ["Semi-Cap/EDA"],
    "1 foundry": ["Foundry"],
    "2 compute silicon": ["Computer/GPU", "Semi-Logic/ASIC", "Analog/Power-Semi"],
    "3 memory": ["Memory/Storage"],
    "4 interconnect": ["Networking/Optical"],
    "5 systems/OEM": ["Devices/Endpoint"],
    "6 facility": ["Power/Electrical", "Cooling/Thermal", "EPC/Construction"],
    "7 generation": ["Generation/Nuclear"],
    "8 colo/REIT": ["DC-REIT/Colo"],
    # NOT a supplier layer. `Foundation-Model-Proxy` is AMZN/GOOGL/META/MSFT/NVDA
    # -- four of the five ARE the buyer leg, so this row correlates the buyers'
    # revenue against the buyers' own capex. Kept because that makes it a useful
    # within-firm control (it should show capex following revenue), and excluded
    # from the hardware-vs-software comparison because including it would let the
    # buyers vote on their own supplier relationship.
    "9 CTRL buyers-self": ["Foundation-Model-Proxy"],
    "10 data platform": ["Data-Platform"],
    "11 ai-native sw": ["AI-Native-Software"],
    "12 devtools": ["DevTools/Observability"],
    "13 saas broad": ["Software/SaaS"],
    "14 security": ["Cybersecurity"],
    "15 apps/consumer": ["AI-App/Consumer-Net"],
    "16 it services": ["IT-Services/Integration"],
    "17 applied/robotics": ["Robotics/Automation", "Healthcare-AI/LS-Tools"],
}


def chain_scan(conn, buyers: list[str], window: int | None) -> list[dict]:
    """Per-layer lag profile, summarised by the MEDIAN r across the layer's names.

    Deliberately not the median of per-ticker argmax lags. Where a correlation is
    weak its argmax is the argmax of noise, so averaging argmaxes reports a
    confident lag for a layer that has no relationship -- which is exactly how
    the power/EPC "stage" survived into the first write-up before the window
    check killed it. Taking the median r at each lag FIRST and then choosing the
    best lag lets a layer with no signal show a flat profile and a low peak,
    which is the honest output.
    """
    cap_raw = series(conn, buyers, "cash_flow", "capital_expenditures")
    cq, cap_g, _ = matched_yoy(cap_raw)
    lags = list(range(-4, 5))
    out = []
    for layer, chains in CHAIN_LAYERS.items():
        rev_raw = series(conn, chains, "income", "total_revenue")
        tickers = sorted({t for q in rev_raw for t in rev_raw[q]})
        by_lag: dict[int, list[float]] = {lag: [] for lag in lags}
        used = []
        for tkr in tickers:
            own = {q: {tkr: v[tkr]} for q, v in rev_raw.items() if tkr in v}
            rq, rev_g, _ = matched_yoy(own)
            common = sorted(set(cq) & set(rq))
            if window:
                common = common[-window:]
            if len(common) < MIN_QUARTERS:
                continue
            used.append(tkr)
            b = [cap_g[cq.index(q)] for q in common]
            s = [rev_g[rq.index(q)] for q in common]
            for lag in lags:
                r = corr(*pairs_at_lag(b, s, lag))[0]
                if r is not None:
                    by_lag[lag].append(r)
        if not used:
            continue
        med = {lag: statistics.median(v) if v else None for lag, v in by_lag.items()}
        ranked = [(v, lag) for lag, v in med.items() if v is not None]
        best_r, best_lag = max(ranked) if ranked else (None, None)
        out.append(
            {
                "layer": layer,
                "chains": chains,
                "tickers": len(used),
                "median_r_by_lag": {
                    str(k): round(v, 3) if v else None for k, v in med.items()
                },
                "best_lag": best_lag,
                "best_median_r": round(best_r, 3) if best_r is not None else None,
                "spread": round(
                    max(v for v, _ in ranked) - min(v for v, _ in ranked), 3
                )
                if ranked
                else None,
            }
        )
    return out


def main() -> int:
    window = next(
        (int(a.split("=", 1)[1]) for a in sys.argv[1:] if a.startswith("--window=")),
        None,
    )
    settings = Settings.from_env()
    results: dict[str, Any] = {}
    with psycopg.connect(settings.db_dsn()) as conn:
        for name, spec in LINKS.items():
            r = results[name] = analyse(conn, spec, window=window)
            print(f"\n=== {name} ({r['status']}) — {spec['why']}")
            if r["status"] != "ok":
                print(f"    {r}")
                continue
            print(
                f"    {r['quarters']}q  {r['span'][0]}..{r['span'][1]}  "
                f"matched buyers={r['buyers_matched_last']} "
                f"suppliers={r['suppliers_matched_last']}"
            )
            for label in ("growth_yoy", "acceleration"):
                cells = "  ".join(
                    f"L{c['lag']}={c['r']}(n{c['n']},t{c['t_naive']})" for c in r[label]
                )
                print(f"    {label:13s} {cells}")
                halves = "  ".join(
                    f"L{c['lag']}=[{c.get('r_first_half')}|{c.get('r_second_half')}]"
                    for c in r[label]
                    if "r_first_half" in c
                )
                if halves:
                    print(f"    {'  halves':13s} {halves}")

        per_tkr = per_supplier(conn, LINKS["ai_datacenter"], window)
        layers = chain_scan(conn, ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"], window)

    print("\n=== WHOLE-CHAIN LAYER SCAN vs hyperscaler+neocloud capex growth")
    print("    median r across each layer's tickers, at lags -4..+4")
    print(
        f"    {'layer':20s} {'n':>3s}  "
        + " ".join(f"{lag:+d}   " for lag in range(-4, 5))
    )
    for row in layers:
        cells = " ".join(
            f"{row['median_r_by_lag'][str(lag)] or 0:+.2f}" for lag in range(-4, 5)
        )
        print(
            f"    {row['layer']:20s} {row['tickers']:3d}  {cells}   "
            f"best {row['best_lag']:+d} @ {row['best_median_r']:+.2f}"
        )

    print("\n=== PER-SUPPLIER two-sided lag vs hyperscaler+neocloud capex growth")
    print("    negative peak lag = SUPPLIER LEADS capex; positive = supplier lags")
    tag = {t: "pure" for t in DC_PURE} | {t: "dil " for t in DC_DILUTED}
    for row in per_tkr:
        cells = " ".join(
            f"{row[f'r_{lag:+d}'] if row[f'r_{lag:+d}'] is not None else 0:+.2f}"
            for lag in range(-4, 5)
        )
        print(
            f"    {row['ticker']:6s} {tag.get(row['ticker'], '    ')} {cells}  "
            f"peak {row['peak_lag']:+d} @ {row['peak_r']:+.2f} ({row['quarters']}q)"
        )
    peaks = [r["peak_lag"] for r in per_tkr if r["peak_lag"] is not None]
    if peaks:
        dist = {lag: peaks.count(lag) for lag in sorted(set(peaks))}
        print(f"    -> peak-lag distribution across {len(peaks)} suppliers: {dist}")

    dr = dose_response(results)
    print("\n=== DOSE-RESPONSE (pure-play minus diluted)")
    if dr["status"] == "ok":
        print(f"    pure {dr['pure_span']}   diluted {dr['diluted_span']}")
        for metric in ("growth_yoy", "acceleration"):
            cells = "  ".join(
                f"L{c['lag']}={c['pure_r']}vs{c['diluted_r']}(gap {c['gap']})"
                for c in dr[metric]
            )
            print(f"    {metric:13s} {cells}")
    else:
        print(f"    {dr}")

    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"capex_matched_growth{f'_w{window}' if window else ''}"
    (OUT / f"{stem}.json").write_text(
        json.dumps(
            {
                "probe": "capex lead-lag over full history via matched-sample growth",
                "reproduce": (
                    "uv run python scripts/research/capex_matched_growth.py"
                    + (f" --window={window}" if window else "")
                ),
                "window_quarters": window,
                "caveat_t_naive": (
                    "quarterly YoY overlaps 4 quarters; reported t is inflated by "
                    "autocorrelation. Sort with it, do not test with it."
                ),
                "dc_pure_play_assertion": DC_PURE,
                "dc_diluted_assertion": DC_DILUTED,
                "links": results,
                "dose_response": dr,
                "per_supplier_ai_datacenter": per_tkr,
                "chain_layer_scan": layers,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"\nwrote {OUT / f'{stem}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
