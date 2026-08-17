"""Re-measure concentration computability after fixing three probe bugs.

    UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_concentration_axis_probe.py

`fundamental_segment_computability_probe.py` returned segment 77/257 and
geography **0/257**, and that second number is what killed P4. Reading NVDA's
raw rows shows the zero is an artifact of how the probe grouped, not a fact
about the data. Its geographic breakdown is complete to the cent:

    country   country:US                              63,769,000,000
    country   country:TW                              12,006,000,000
    country   nvda:ChinaIncludingHongKongMember        4,550,000,000
    continent nvda:OtherCountriesMember                1,290,000,000
                                                    = 81,615,000,000
    product   (untagged consolidated total)            81,615,000,000

Three bugs, each mapping to one failure bucket the old probe reported:

1. **The denominator was scoped to `rev_group`** (`no_total`, 180/257 on
   geography). UW files the untagged consolidated row under ONE group —
   'product' for NVDA — so every geography group looked denominator-less. The
   total is a property of the PERIOD, not of the group.

2. **`rev_group` is not the breakdown key; the XBRL axis is** (part of
   `no_leaves`, 38). NVDA's geographic members are split across the 'country'
   and 'continent' groups while sharing one axis, `srt:StatementGeographicalAxis`.
   Grouping by `rev_group` shatters a complete partition into two partial ones.

3. **`srt:ConsolidationItemsAxis` is a scope tag, not a disaggregation**
   (`ambiguous_axis`, 37). The old probe kept only single-axis rows, which
   discards exactly the ASC 280 reportable-segment rows on every filer that
   tags them `OperatingSegmentsMember` — NVDA's real segment axis
   (ComputeAndNetworking 74.550 + Graphics 7.065 = 81.615, exact) was thrown
   away for carrying a scope qualifier.

The remaining bucket, `no_axis_sums_to_total` (86/257), is a real property of
the filings and is handled rather than excused: one axis can carry several
nesting levels at once. NVDA's ProductOrService axis holds DataCenter beside
its own children Hyperscale + AICloudsIndustrialEnterprise, so the members do
not sum to anything meaningful. LEVEL SELECTION recovers the partition — search
for a subset of members summing to the period total and take the COARSEST such
subset, which is the reported level. {DataCenter, EdgeComputing} wins over
{Hyperscale, AICloudsIndustrialEnterprise, EdgeComputing}; both sum exactly.

WHAT MAKES A TICKER COUNT. A single computable quarter is not the deliverable —
spec §6 wants a multi-year trend, so a share that resolves once and never again
carries nothing. This probe reports `periods_computable / periods_with_rows`
per ticker and gates on a minimum run of periods, which the old probe (latest
period only) never tested.

Nothing is written to Postgres. This decides whether a table should exist.
Trace: docs/research/2026-08-13-fundamental-concentration-axis/.
"""

from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from uw_scan.config import Settings  # noqa: E402

OUT = Path("docs/research/2026-08-13-fundamental-concentration-axis")

#: Axes that qualify a row's SCOPE rather than splitting revenue. A row tagged
#: on one of these plus one real axis is still a leaf of that real axis.
SCOPE_AXES = frozenset(
    {
        "srt:ConsolidationItemsAxis",
        "us-gaap:StatementScenarioAxis",
        "srt:ConsolidationItemsAxis".lower(),
    }
)

#: Preference order within a family. ASC 280 reportable segments are what
#: "segment concentration" means; a product cut is the fallback when a filer
#: publishes no segment axis.
SEGMENT_AXES = (
    "us-gaap:StatementBusinessSegmentsAxis",
    "srt:ProductOrServiceAxis",
)
GEOGRAPHY_AXES = ("srt:StatementGeographicalAxis",)

TOLERANCE = 0.02
#: Above this many members an exact subset search is not worth the time; the
#: full-set check still runs and anything else is reported ambiguous rather
#: than guessed at.
MAX_SUBSET_MEMBERS = 14
#: Periods a ticker must resolve before its share can carry a trend.
MIN_PERIODS = 6
MAX_PERIODS = 20


def fetch(client: httpx.Client, ticker: str, key: str) -> list[dict[str, Any]] | None:
    try:
        r = client.get(
            f"https://api.unusualwhales.com/api/stock/{ticker}/fundamental-breakdown",
            headers={"Authorization": f"Bearer {key}"},
            timeout=120.0,
        )
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    return (r.json().get("data") or {}).get("rev_breakdown")


def universe_tickers(settings: Settings) -> list[str]:
    import psycopg

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM uw_scan.fundamental_statement_obs ORDER BY 1"
        )
        return [r[0] for r in cur.fetchall()]


def real_axis(row: dict[str, Any]) -> tuple[str, str] | None:
    """The (axis, member) this row is a leaf of, ignoring scope qualifiers."""
    axes = list(row.get("axis") or [])
    members = list(row.get("members") or [])
    if len(axes) != len(members):
        return None
    pairs = [(a, m) for a, m in zip(axes, members) if a not in SCOPE_AXES]
    return pairs[0] if len(pairs) == 1 else None


def partition(members: list[tuple[str, float]], total: float) -> dict[str, Any] | None:
    """The coarsest subset of members summing to `total`, or None.

    A filer may publish two nesting levels on one axis. The reported level is
    the coarse one, so among subsets that reconcile, fewest members wins. A tie
    at the same size is genuinely ambiguous and is refused, not broken.
    """
    # A single member equal to the total is not a breakdown. The filer disclosed
    # one line that happens to be all of revenue, and calling its share 100%
    # measures the disclosure, not the concentration. Refuse it: a degenerate
    # partition inflated 271 of 1920 segment computations on the first run.
    if len(members) < 2:
        return None
    ok = lambda s: abs(s - total) / total <= TOLERANCE  # noqa: E731
    if ok(sum(v for _, v in members)):
        return {"members": members, "level": "all"}
    n = len(members)
    if n > MAX_SUBSET_MEMBERS:
        return None
    for size in range(2, n):
        hits = [c for c in combinations(members, size) if ok(sum(v for _, v in c))]
        if len(hits) == 1:
            return {"members": list(hits[0]), "level": f"subset:{size}"}
        if len(hits) > 1:
            return None
    return None


def period_total(rows: list[dict[str, Any]]) -> float | None:
    """The untagged consolidated revenue for a period, from ANY rev_group."""
    vals = [
        float(r["value"])
        for r in rows
        if not (r.get("axis") or []) and not (r.get("members") or [])
    ]
    vals = [v for v in vals if v > 0]
    return max(vals) if vals else None


def shares_for_period(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = period_total(rows)
    if total is None:
        return {"verdict": "no_total"}
    by_axis: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        hit = real_axis(r)
        if hit is None:
            continue
        try:
            v = float(r["value"])
        except (TypeError, ValueError):
            continue
        by_axis[hit[0]].append((hit[1], v))
    if not by_axis:
        return {"verdict": "no_leaves"}

    out: dict[str, Any] = {"verdict": "computed", "total": total, "axes": {}}
    for family, prefs in (("segment", SEGMENT_AXES), ("geography", GEOGRAPHY_AXES)):
        for axis in prefs:
            # Dedupe: the same member can repeat across rev_groups.
            uniq = dict(by_axis.get(axis, []))
            part = partition(sorted(uniq.items(), key=lambda m: -m[1]), total)
            if part is None:
                continue
            top, tv = max(part["members"], key=lambda m: m[1])
            out["axes"][family] = {
                "axis": axis,
                "level": part["level"],
                "n_members": len(part["members"]),
                "top_member": top,
                "top_share": round(tv / total, 4),
            }
            break
    return out


def verdict_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"verdict": "no_rows"}
    periods = sorted({r["report_date"] for r in rows}, reverse=True)[:MAX_PERIODS]
    per: dict[str, Any] = {}
    for p in periods:
        per[p] = shares_for_period([r for r in rows if r["report_date"] == p])

    res: dict[str, Any] = {"periods_with_rows": len(periods), "by_period": per}
    for family in ("segment", "geography"):
        hits = [
            (p, v["axes"][family])
            for p, v in per.items()
            if v.get("verdict") == "computed" and family in v.get("axes", {})
        ]
        n = len(hits)
        res[family] = {
            "periods_computable": n,
            "trend_bearing": n >= MIN_PERIODS,
            "latest_top_share": hits[0][1]["top_share"] if hits else None,
            "latest_top_member": hits[0][1]["top_member"] if hits else None,
            "axis": hits[0][1]["axis"] if hits else None,
            "trend": [h[1]["top_share"] for h in hits],
        }
    return res


def main() -> None:
    key = os.environ.get("UW_SCAN_API_KEY") or Settings.from_env().uw_api_key
    if not key:
        raise SystemExit("UW_SCAN_API_KEY required")
    tickers = universe_tickers(Settings.from_env())
    print(f"probing {len(tickers)} tickers", flush=True)

    results: dict[str, Any] = {}
    with httpx.Client(http2=False) as client:

        def one(t: str) -> tuple[str, dict[str, Any]]:
            return t, verdict_for(fetch(client, t, key) or [])

        with ThreadPoolExecutor(max_workers=6) as pool:
            for i, (t, v) in enumerate(pool.map(one, tickers), 1):
                results[t] = v
                if i % 25 == 0:
                    print(f"  {i}/{len(tickers)}", flush=True)

    summary: dict[str, Any] = {"tickers": len(tickers), "min_periods": MIN_PERIODS}
    for family in ("segment", "geography"):
        c = Counter()
        for v in results.values():
            if "no_rows" in str(v.get("verdict", "")):
                c["no_rows"] += 1
                continue
            f = v.get(family) or {}
            if f.get("trend_bearing"):
                c["trend_bearing"] += 1
            elif f.get("periods_computable"):
                c["latest_only_or_short"] += 1
            else:
                c["never_computable"] += 1
        summary[family] = dict(c)

    OUT.mkdir(parents=True, exist_ok=True)
    # ponytail: gzipped — the uncompressed trace is 1.1 MB, ~10x the largest
    # research JSON on main. `gzip -dc <file> | jq` reads it in place.
    # mtime=0 keeps re-runs byte-identical when the payload is unchanged.
    payload = json.dumps(
        {
            "probe": "concentration axis-grouped computability",
            "reproduce": (
                "uv run python scripts/research/fundamental_concentration_axis_probe.py"
            ),
            "summary": summary,
            "by_ticker": results,
        },
        indent=1,
        sort_keys=True,
    )
    (OUT / "computability.json.gz").write_bytes(
        gzip.compress(payload.encode(), mtime=0)
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
