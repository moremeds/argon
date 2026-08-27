"""Independent research-priority dimensions and their permission. Pure compute.

WHY DIMENSIONS AND NOT JUST THE COMPOSITE
-----------------------------------------
The validated composite is one number that orders names (rank IC 0.039, t 2.67
leak-free). It cannot answer "why is this name near the top", and a surface that
shows only a rank invites the reader to supply their own reason. Dimensions are
the same seven measured features grouped by what they are ABOUT, persisted
separately so the ordering can be explained by the thing that produced it.

Grouping does not create information. Every dimension here is a mean of z-scores
Argon already computes; none is a new claim.

THE PERMISSION IS PART OF THE DATA
----------------------------------
Each dimension carries an `authority` from spec §6.4's ladder. This is stored,
not documented, because a permission that lives only in prose is a permission a
UI can exceed by accident. Two are load-bearing:

- `operating_quality` is `descriptive` — NOT research_priority. Its two inputs
  (`gross_margin`, `op_margin`) measured INVERTED in the 2026-08-12 validation:
  high-margin names underperformed. Argon is entitled to SHOW the margin and not
  to claim a direction for it, and pretending otherwise would smuggle a
  contradicted sign into the aggregate.
- `valuation` is `directional_monitor` as of 2026-08-25, raised by MEASUREMENT
  and not by decision. The own-history finding was recomputed on a
  split-consistent price basis (the 2026-08-25 rerun) and survived unchanged:
  `sales_to_ev` within-ticker 2q IC +0.0709 (t 5.55), and +0.0772 (t 6.74) with
  pure reversal held constant. Among the 121 split-EXPOSED names it was the only
  one of five signals the correction did not move, while `book_to_price` and
  `earnings_yield` lost significance outright.

  That licenses a WITHIN-NAME direction and nothing wider. It does NOT enter the
  priority aggregate, because the aggregate orders names against EACH OTHER and
  cross-sectional value measured INVERTED in this same universe
  (`book_to_price` IC -0.0365, t -2.32). A stronger authority is not a wider one.

The default program authority stops at `research_priority`. Nothing here may
return `investment_ranking`, and a test asserts it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum


class Authority(StrEnum):
    """Spec §6.4's ladder. Ordered weakest to strongest."""

    DESCRIPTIVE = "descriptive"
    RESEARCH_PRIORITY = "research_priority"
    DIRECTIONAL_MONITOR = "directional_monitor"
    INVESTMENT_RANKING = "investment_ranking"


AUTHORITY_ORDER = (
    Authority.DESCRIPTIVE,
    Authority.RESEARCH_PRIORITY,
    Authority.DIRECTIONAL_MONITOR,
    Authority.INVESTMENT_RANKING,
)

#: The ceiling this program may reach. Anything above it needs the GX gate:
#: active-plus-delisted PIT, out-of-sample, regime and cost evidence, and an
#: explicit operator decision — none of which this milestone provides.
PROGRAM_CEILING = Authority.RESEARCH_PRIORITY

#: dimension -> the z-scored features it averages. Sign conventions are already
#: baked into the features (`neg_net_debt_ebitda` is negated so higher is better),
#: so no dimension flips one here.
DIMENSION_FEATURES: dict[str, tuple[str, ...]] = {
    "growth": ("rev_growth",),
    "operating_quality": ("gross_margin", "op_margin"),
    "balance_sheet": ("neg_net_debt_ebitda",),
    "cash_conversion": ("fcf_margin",),
    "capital_efficiency": ("roe", "asset_turnover"),
}

#: Dimensions computed from something other than the feature z-scores.
DERIVED_DIMENSIONS = ("valuation", "evidence_quality")

DIMENSIONS = tuple(DIMENSION_FEATURES) + DERIVED_DIMENSIONS

#: What each dimension is allowed to do. See the module docstring for why
#: `operating_quality` and `valuation` are capped at descriptive.
DIMENSION_AUTHORITY: dict[str, Authority] = {
    "growth": Authority.RESEARCH_PRIORITY,
    "operating_quality": Authority.DESCRIPTIVE,
    "balance_sheet": Authority.RESEARCH_PRIORITY,
    "cash_conversion": Authority.RESEARCH_PRIORITY,
    "capital_efficiency": Authority.RESEARCH_PRIORITY,
    # Within-name direction only — see the module docstring.
    "valuation": Authority.DIRECTIONAL_MONITOR,
    "evidence_quality": Authority.DESCRIPTIVE,
}

#: Dimensions the priority aggregate orders names by. Exactly
#: `research_priority`, and the equality is deliberate in BOTH directions:
#:
#: - a WEAKER dimension is excluded because including a contradicted sign would
#:   move the ordering while the label still said no sign was claimed;
#: - a STRONGER one is excluded too. `valuation` is `directional_monitor`, which
#:   is a license for a WITHIN-NAME direction. The aggregate orders names against
#:   EACH OTHER, and cross-sectional value measured INVERTED in this universe.
#:   A stronger authority is not a wider one.
AGGREGATE_DIMENSIONS = tuple(
    d for d in DIMENSIONS if DIMENSION_AUTHORITY[d] is Authority.RESEARCH_PRIORITY
)


def dimension_values(
    z: Mapping[str, float | None],
) -> dict[str, dict[str, object]]:
    """Feature z-scores -> {dimension: {value, present, expected, authority}}.

    A dimension with no present input returns `value=None` rather than 0.0. Zero
    is the cross-section MEAN — a name with no balance-sheet data would be
    scored as exactly average on it, which is a fabricated observation, not a
    missing one.
    """
    out: dict[str, dict[str, object]] = {}
    for dim, feats in DIMENSION_FEATURES.items():
        vals = [z[f] for f in feats if z.get(f) is not None]
        out[dim] = {
            "value": (sum(vals) / len(vals)) if vals else None,
            "present": len(vals),
            "expected": len(feats),
            "authority": DIMENSION_AUTHORITY[dim].value,
        }
    return out


def evidence_quality(
    *,
    true_pit: int,
    total: int,
    excluded_values: int,
) -> dict[str, object]:
    """How well-evidenced this name's inputs are. Descriptive by construction.

    Not a quality score for the COMPANY — a quality score for what Argon knows
    about it. Conflating the two would let a name with thin filings read as a
    worse business.
    """
    coverage = (true_pit / total) if total else None
    return {
        "value": coverage,
        "present": 1 if total else 0,
        "expected": 1,
        "authority": Authority.DESCRIPTIVE.value,
        "true_pit": true_pit,
        "observations": total,
        "excluded_values": excluded_values,
    }


def priority_aggregate(
    dims: Mapping[str, Mapping[str, object]],
    *,
    min_present: int = 2,
) -> dict[str, object]:
    """Mean of the research-priority dimensions that are present.

    RENORMALIZATION IS EXPLICIT. A missing dimension is dropped and the mean is
    taken over what remains, and the response names both which were used and
    which were missing. The alternative — treating a missing dimension as 0 —
    would pull every incomplete name toward the middle of the ranking, which
    looks like a measurement and is an artifact of absence.

    `min_present` refuses rather than averaging one dimension into a "priority".
    A single dimension is that dimension, and calling it an aggregate would give
    it authority it did not earn.
    """
    used: list[str] = []
    missing: list[str] = []
    vals: list[float] = []
    for dim in AGGREGATE_DIMENSIONS:
        v = dims.get(dim, {}).get("value")
        if v is None:
            missing.append(dim)
        else:
            used.append(dim)
            vals.append(float(v))

    if len(used) < min_present:
        return {
            "value": None,
            "authority": Authority.DESCRIPTIVE.value,
            "present": len(used),
            "expected": len(AGGREGATE_DIMENSIONS),
            "used": used,
            "missing": missing,
            "refusal": (
                f"only {len(used)} of {len(AGGREGATE_DIMENSIONS)} priority "
                f"dimensions present; {min_present} required"
            ),
        }
    return {
        "value": sum(vals) / len(vals),
        # The aggregate can never be stronger than the program ceiling, and never
        # stronger than its weakest contributing dimension.
        "authority": PROGRAM_CEILING.value,
        "present": len(used),
        "expected": len(AGGREGATE_DIMENSIONS),
        "used": used,
        "missing": missing,
        "refusal": None,
    }


def max_authority(levels: Sequence[Authority | str]) -> Authority:
    """The strongest of `levels`, capped at the program ceiling."""
    if not levels:
        return Authority.DESCRIPTIVE
    strongest = max(
        (Authority(level) for level in levels), key=AUTHORITY_ORDER.index
    )
    if AUTHORITY_ORDER.index(strongest) > AUTHORITY_ORDER.index(PROGRAM_CEILING):
        return PROGRAM_CEILING
    return strongest
