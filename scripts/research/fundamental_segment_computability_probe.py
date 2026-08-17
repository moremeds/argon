"""Can a concentration share be computed from UW `rev_breakdown`? Measure it.

    uv run python scripts/research/fundamental_segment_computability_probe.py

Spec §6 wants `concentration_risk` = "largest reported segment share of revenue +
largest single-country share", and §896 marks it available on the strength of a
coverage probe: UW `rev_breakdown` returns rows for 24 of the 25 core names.

COVERAGE IS NOT COMPUTABILITY, and that gap is what this probe measures. The
endpoint returns one flat list per ticker mixing several disaggregations of the
same revenue along different XBRL axes, an untagged consolidated total, and — on
some names — cross-products of two axes at once. Nothing in a row marks its
level, so summing a group double-counts and picking "the largest member" returns
whichever nesting depth happens to sort first.

THE TEST APPLIED HERE is the cross-check that caught the TSM currency bug: derive
the same quantity two ways and require agreement. For each (ticker, period,
rev_group, axis) it takes the rows carrying exactly ONE member on exactly that
axis — the leaf candidates — and compares their sum against the untagged total
reported for the same period. A breakdown that is complete and non-overlapping
sums to the whole; one that mixes parent and child rows overshoots; one that is
partial undershoots. Only the agreeing case can carry a share.

Nothing is written to Postgres: this decides whether a table should exist, so it
does not create one. The trace lands in
docs/research/2026-08-12-fundamental-segment-computability/.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from uw_scan.config import Settings  # noqa: E402

OUT = Path("docs/research/2026-08-12-fundamental-segment-computability")

#: `--universe` widens the cohort to every ingested ticker and writes HERE, so
#: the committed core-25 verdict keeps reproducing byte-for-byte from the
#: no-argument command its VERDICT.md names.
WIDE_OUT = Path("docs/research/2026-08-13-fundamental-segment-computability-wide")

#: The cohort the spec's availability claim was made over.
CORE_25 = (
    "NVDA AMD AVGO MRVL TSM ASML AMAT MU MSFT GOOGL AMZN META ORCL ANET VRT "
    "ETN GEV CEG VST DELL SMCI PLTR CRWD NOW APP"
).split()

#: Fraction by which the leaf rows may miss the untagged total and still be
#: called a complete breakdown. Generous on purpose — the question is whether
#: these sum AT ALL, not whether they round well.
TOLERANCE = 0.02


def fetch(client: httpx.Client, ticker: str, key: str) -> list[dict[str, Any]] | None:
    r = client.get(
        f"https://api.unusualwhales.com/api/stock/{ticker}/fundamental-breakdown",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30.0,
    )
    if r.status_code != 200:
        return None
    return (r.json().get("data") or {}).get("rev_breakdown")


def universe_tickers(settings: Settings) -> list[str]:
    """Every ticker the statement store actually holds.

    Read from `fundamental_statement_obs` rather than `fundamental_universe`:
    membership in the universe table does not mean a filing was ever ingested,
    and a name with no statements cannot carry a concentration row either way.
    """
    import psycopg

    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM uw_scan.fundamental_statement_obs ORDER BY 1"
        )
        return [r[0] for r in cur.fetchall()]


def verdict_for(rows: list[dict[str, Any]], period: str, group: str) -> dict[str, Any]:
    """Whether ONE (period, rev_group) yields a defensible largest-share number."""
    here = [r for r in rows if r["report_date"] == period and r["rev_group"] == group]
    totals = [float(r["value"]) for r in here if not r["members"]]
    if not totals:
        return {"verdict": "no_total", "detail": "no untagged consolidated row"}
    total = max(totals)
    if total <= 0:
        return {"verdict": "no_total", "detail": "consolidated total is not positive"}

    # Leaf candidates PER AXIS. A row tagged on two axes at once is a cell of a
    # cross-tab, not a member of either breakdown, and is excluded here — AVGO
    # reports ['Subscriptions', 'Americas'] alongside ['Americas'], and counting
    # both makes the Americas share 2.4x its true value.
    by_axis: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in here:
        if len(r["members"]) == 1 and len(r["axis"]) == 1:
            by_axis[r["axis"][0]].append((r["members"][0], float(r["value"])))

    if not by_axis:
        return {"verdict": "no_leaves", "detail": "no single-member single-axis rows"}

    complete = {}
    for axis, members in by_axis.items():
        s = sum(v for _, v in members)
        if abs(s - total) / total <= TOLERANCE:
            top, tv = max(members, key=lambda m: m[1])
            complete[axis] = {
                "members": len(members),
                "largest_member": top,
                "largest_share": round(tv / total, 4),
            }

    if not complete:
        ratios = {a: round(sum(v for _, v in m) / total, 3) for a, m in by_axis.items()}
        return {
            "verdict": "no_axis_sums_to_total",
            "detail": f"leaf sums / total by axis: {ratios}",
        }
    if len(complete) > 1:
        # Both AVGO axes sum to its total: ProductOrService says 76% and
        # BusinessSegments says 68%, and neither is more "the" segment share.
        return {
            "verdict": "ambiguous_axis",
            "detail": f"{len(complete)} axes each sum to the total",
            "axes": complete,
        }
    axis, got = next(iter(complete.items()))
    return {"verdict": "computable", "axis": axis, **got}


def main() -> int:
    # SecretStr — str() on it yields "**********", which the API rejects as a
    # malformed token rather than as a wrong one. Unwrap explicitly.
    settings = Settings.from_env()
    secret = settings.api_key
    key = secret.get_secret_value() if secret else os.environ.get("UW_SCAN_API_KEY")
    if not key:
        print("UW_SCAN_API_KEY not set", file=sys.stderr)
        return 1

    wide = "--universe" in sys.argv
    cohort = universe_tickers(settings) if wide else CORE_25
    out = WIDE_OUT if wide else OUT
    print(f"cohort: {len(cohort)} tickers -> {out}")

    results: dict[str, Any] = {}
    with httpx.Client() as client:
        for t in cohort:
            rows = fetch(client, t, key)
            if not rows:
                results[t] = {"error": "no rev_breakdown rows"}
                continue
            period = max(r["report_date"] for r in rows)
            groups = sorted({r["rev_group"] for r in rows})
            results[t] = {
                "period": period,
                "groups": groups,
                "by_group": {g: verdict_for(rows, period, g) for g in groups},
            }
            print(
                f"{t:6s} {period}  "
                + "  ".join(
                    f"{g}={results[t]['by_group'][g]['verdict']}" for g in groups
                )
            )

    # A share is only reportable if SOME group yields one. Segment and geography
    # are counted separately because the spec asks for both.
    def tally(groups: tuple[str, ...]) -> Counter:
        c: Counter = Counter()
        for t, r in results.items():
            if "error" in r:
                c["no_rows"] += 1
                continue
            verdicts = [
                r["by_group"][g]["verdict"] for g in groups if g in r["by_group"]
            ]
            c[
                "computable"
                if "computable" in verdicts
                else (verdicts[0] if verdicts else "absent")
            ] += 1
        return c

    summary = {
        "tickers": len(cohort),
        "tolerance": TOLERANCE,
        "segment_like": dict(tally(("product",))),
        "geography_like": dict(tally(("country", "continent"))),
    }
    print("\nsegment:   ", summary["segment_like"])
    print("geography: ", summary["geography_like"])

    out.mkdir(parents=True, exist_ok=True)
    (out / "computability.json").write_text(
        json.dumps(
            {
                "probe": "UW /fundamental-breakdown rev_breakdown computability",
                "reproduce": (
                    "uv run python scripts/research/"
                    "fundamental_segment_computability_probe.py"
                    + (" --universe" if wide else "")
                ),
                "summary": summary,
                "by_ticker": results,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"\nwrote {out / 'computability.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
