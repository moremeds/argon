"""Revenue concentration from raw XBRL breakdown rows.

Ported from `scripts/research/fundamental_concentration_axis_probe.py`, which is
the verified implementation — its output is the evidence in
`docs/research/2026-08-13-fundamental-concentration-axis/VERDICT.md`. This module
must not re-derive the rules; each one is a retraction paid for once.

WHAT THIS IS NOT
----------------
It is not an edge, and nothing here may become a composite input. Measured over
401 tickers: the top share moves a median 1.20pp per quarter against
annual/quarterly basis contamination of median 2.5pp and p90 17.5pp, over a panel
8 quarters deep. The level survives that noise and is near-static — a public,
filing-lagged, highly persistent characteristic is a factor loading, not alpha.
It ships descriptive-only.

THE FOUR RULES, AND THE BUCKET EACH ONE RETIRED
-----------------------------------------------
An earlier probe reported segment 8/25 and geography 0/257 and closed the
concentration ledger on that basis. All three zeros were grouping bugs:

1. The denominator belongs to the PERIOD, taken from the untagged consolidated
   row wherever it appears — never scoped to `rev_group`. (retired `no_total`)
2. Group by the XBRL AXIS, never by `rev_group`. The provider's grouping tag is
   not the axis. (retired `no_leaves`)
3. `srt:ConsolidationItemsAxis` is a SCOPE tag, not a partition. Filtering to
   single-axis rows discarded exactly the ASC 280 segment rows.
   (retired `ambiguous_axis`)
4. One axis can carry several nesting levels. The reported level is the coarsest
   subset of members summing to the total; a tie is genuinely ambiguous and is
   refused rather than broken.

Re-measured with those fixed: segment 184/401, geography 128/401.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

#: Axes that qualify a row's SCOPE rather than splitting revenue. A row tagged
#: with one of these plus one real axis is still a leaf of that real axis.
#: Compared case-insensitively: the source probe carried an explicit lowercase
#: duplicate of the same name, and folding case states that intent once.
SCOPE_AXES = frozenset(
    {
        "srt:consolidationitemsaxis",
        "us-gaap:statementscenarioaxis",
    }
)

#: Preference order within a family. ASC 280 reportable segments are what
#: "segment concentration" means; a product cut is the fallback for a filer that
#: publishes no segment axis. This order is what resolves AVGO's known
#: 76%-vs-68% ambiguity to the reportable-segment answer.
SEGMENT_AXES = (
    "us-gaap:StatementBusinessSegmentsAxis",
    "srt:ProductOrServiceAxis",
)
GEOGRAPHY_AXES = ("srt:StatementGeographicalAxis",)

#: How far a candidate partition may miss the period total and still reconcile.
TOLERANCE = 0.02

#: Above this many members an exact subset search is not worth the time. The
#: full-set check still runs; anything else is reported unresolved rather than
#: guessed at.
MAX_SUBSET_MEMBERS = 14

#: A period total above this multiple of its NEIGHBOURS' median is an annual
#: figure mixed into a quarterly series. 89/184 segment and 52/128 geography
#: tickers do this, and the resulting share error is p90 17.5pp against a median
#: quarterly move of 1.20pp — so an undetected annual row is several times larger
#: than the signal it would corrupt.
ANNUAL_MULTIPLE = 2.5

#: Periods compared against, nearest in time, excluding the period itself.
#:
#: The baseline MUST be local. The rule as originally specified used the ticker's
#: median over its whole history, which was measured on an 8-quarter panel where
#: growth is small enough not to matter. Over NVDA's real 25-period history
#: revenue grows 26x (3.08B -> 81.6B), so a global median sits among the old small
#: quarters and recent QUARTERLY totals clear 2.5x it on growth alone. Measured on
#: the frozen fixtures, the global rule caught 3 of NVDA's 6 annual periods and
#: raised 3 false positives; the local rule catches 7 of 7 across both filers with
#: none. Four neighbours spans a year either side without reaching far enough to
#: be re-contaminated by the next annual row.
ANNUAL_NEIGHBOURS = 4

#: Bumping this re-hashes nothing, but it does invalidate any cached derivation.
DERIVATION_VERSION = "concentration-v1"


def real_axis(row: dict[str, Any]) -> tuple[str, str] | None:
    """The (axis, member) this row is a leaf of, ignoring scope qualifiers.

    `axis` and `members` are positional: axis[i] pairs with members[i]. A row
    that still carries more than one real axis after scope tags are dropped is a
    cross-tabulation, not a leaf of either, and is refused.
    """
    axes = list(row.get("axis") or [])
    members = list(row.get("members") or [])
    if len(axes) != len(members):
        return None
    pairs = [(a, m) for a, m in zip(axes, members) if str(a).lower() not in SCOPE_AXES]
    return pairs[0] if len(pairs) == 1 else None


def period_total(rows: list[dict[str, Any]]) -> float | None:
    """The untagged consolidated revenue for a period, from ANY rev_group.

    Untagged means no axis and no members — the filer's own top line. Scoping
    this to the rev_group being partitioned is bug 1: a breakdown published under
    'continent' is still denominated by the same consolidated total, which may
    have arrived under a different tag.
    """
    untagged = [
        value
        for row in rows
        if not (row.get("axis") or []) and not (row.get("members") or [])
        for value in (_as_float(row.get("value")),)
        if value is not None and value > 0
    ]
    return max(untagged) if untagged else None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        # CI Guardrail 2. An uncoercible cell is one row the filer tagged oddly,
        # not a reason to refuse the period: the remaining members still have to
        # reconcile against the total, so a dropped row shows up as a partition
        # that does not reconcile rather than as a silently wrong share.
        _ = repr(exc)
        return None


def partition(
    members: list[tuple[str, float]],
    total: float,
    *,
    allow_subset: bool = False,
) -> dict[str, Any] | None:
    """The coarsest subset of members summing to `total`, or None.

    A filer may publish two nesting levels on one axis. The reported level is the
    coarse one, so among subsets that reconcile, fewest members wins. A tie at the
    same size is genuinely ambiguous and is refused, not broken.

    `allow_subset` defaults OFF. 14% of resolutions come from the subset search
    rather than the full set reconciling, and only NVDA and AVGO were
    hand-verified. A wrong-level partition produces a *plausible* share, which is
    the exact failure mode this lane has already paid for twice — so the default
    forfeits that 14% of coverage until a hand-audit sample justifies flipping it.
    """
    # A single member equal to the total is not a breakdown: the filer disclosed
    # one line that happens to be all of revenue, and calling its share 100%
    # measures the disclosure, not the concentration. A degenerate partition
    # inflated 271 of 1920 segment computations on the probe's first run.
    if len(members) < 2 or total <= 0:
        return None

    def reconciles(subtotal: float) -> bool:
        return abs(subtotal - total) / total <= TOLERANCE

    if reconciles(sum(v for _, v in members)):
        return {"members": members, "level": "all"}
    if not allow_subset:
        return None
    n = len(members)
    if n > MAX_SUBSET_MEMBERS:
        return None
    for size in range(2, n):
        hits = [
            c for c in combinations(members, size) if reconciles(sum(v for _, v in c))
        ]
        if len(hits) == 1:
            return {"members": list(hits[0]), "level": f"subset:{size}"}
        if len(hits) > 1:
            return None
    return None


def shares_for_period(
    rows: list[dict[str, Any]], *, allow_subset: bool = False
) -> dict[str, Any]:
    """Top-member share per family for one period's raw breakdown rows."""
    total = period_total(rows)
    if total is None:
        return {"verdict": "no_total"}

    by_axis: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        hit = real_axis(row)
        if hit is None:
            continue
        value = _as_float(row.get("value"))
        if value is None:
            continue
        by_axis[hit[0]].append((hit[1], value))
    if not by_axis:
        return {"verdict": "no_leaves"}

    out: dict[str, Any] = {"verdict": "computed", "total": total, "axes": {}}
    for family, preferred in (("segment", SEGMENT_AXES), ("geography", GEOGRAPHY_AXES)):
        for axis in preferred:
            # Dedupe: the same member repeats across rev_groups.
            unique = dict(by_axis.get(axis, []))
            part = partition(
                sorted(unique.items(), key=lambda m: -m[1]),
                total,
                allow_subset=allow_subset,
            )
            if part is None:
                continue
            top_member, top_value = max(part["members"], key=lambda m: m[1])
            out["axes"][family] = {
                "axis": axis,
                "level": part["level"],
                "n_members": len(part["members"]),
                "top_member": top_member,
                "top_share": round(top_value / total, 4),
            }
            break
    return out


def is_annual_row(total: float, neighbour_median: float) -> bool:
    """Does this period's total look like an annual figure in a quarterly series?

    Compared against the median of nearby periods rather than a fixed size or the
    ticker's whole history: the question is about a filer's local consistency, and
    a grower's recent quarter beats its own lifetime median without being annual.
    """
    if neighbour_median <= 0:
        return False
    return total > ANNUAL_MULTIPLE * neighbour_median


def annual_flags(
    rows_by_period: dict[str, list[dict[str, Any]]],
) -> dict[str, bool]:
    """Per-period annual flag for one ticker, keyed the same as the input.

    Derived, never stored: the multiple and the neighbourhood are rules, and rules
    change while the observation rows do not. A period with no resolvable total is
    False — absent evidence is not evidence of an annual row.
    """
    totals = {period: period_total(rows) for period, rows in rows_by_period.items()}
    known = {p: t for p, t in totals.items() if t is not None and t > 0}
    if len(known) < 2:
        return dict.fromkeys(rows_by_period, False)

    order = sorted(known)
    index = {period: i for i, period in enumerate(order)}
    flags: dict[str, bool] = {}
    for period, total in totals.items():
        if total is None or period not in index:
            flags[period] = False
            continue
        here = index[period]
        neighbours = sorted(
            (p for p in order if p != period), key=lambda p: abs(index[p] - here)
        )[:ANNUAL_NEIGHBOURS]
        baseline = sorted(known[p] for p in neighbours)
        median = (
            baseline[len(baseline) // 2]
            if len(baseline) % 2
            else (baseline[len(baseline) // 2 - 1] + baseline[len(baseline) // 2]) / 2
        )
        flags[period] = is_annual_row(total, median)
    return flags


def build_card(
    rows_by_period: dict[str, list[dict[str, Any]]],
    *,
    allow_subset: bool = False,
) -> dict[str, Any]:
    """Everything the card renders, derived from stored rows at read time.

    Annual periods are DROPPED from the trend and listed separately rather than
    deleted. A reader comparing a 4-quarter series against the filer's own
    filings needs to see that a period existed and why it is not plotted;
    silently omitting it makes the series look complete when it is filtered.

    A family that resolves in no period is absent from the result, never zero —
    a zero share reads as "no concentration", which is a claim about the company
    rather than about our coverage.
    """
    flags = annual_flags(rows_by_period)
    resolved = {
        period: shares_for_period(rows, allow_subset=allow_subset)
        for period, rows in rows_by_period.items()
        if not flags.get(period, False)
    }

    trend = []
    for period in sorted(resolved):
        axes = resolved[period].get("axes") or {}
        trend.append(
            {
                "report_date": period,
                "segment_top_share": (axes.get("segment") or {}).get("top_share"),
                "geography_top_share": (axes.get("geography") or {}).get("top_share"),
            }
        )

    # Per family, the newest period that actually resolved — which may differ
    # between families, and carries its own date for exactly that reason. A
    # filer can publish a geography cut every quarter and a segment cut only
    # annually, and forcing both onto one as-of would date one of them wrongly.
    latest: dict[str, Any] = {}
    for family in ("segment", "geography"):
        for period in sorted(resolved, reverse=True):
            axes = resolved[period].get("axes") or {}
            if family in axes:
                latest[family] = {**axes[family], "report_date": period}
                break

    return {
        "segment": latest.get("segment"),
        "geography": latest.get("geography"),
        "trend": trend,
        "dropped_annual_periods": sorted(p for p, flag in flags.items() if flag),
        "derivation_version": DERIVATION_VERSION,
    }
