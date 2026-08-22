"""Horizon resolution and the rules that fire when the rates evidence disagrees.

Split from ``rates.py`` because these are the parts that state what *cannot* be
concluded, and they read better as one piece: how to line two paths up at a comparable
horizon, when their disagreement is real, and which decompositions can fail at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from uw_scan.models.macro import PolicyPath, PolicyPathKind

from .contracts import (
    Contradiction,
    Direction,
    DomainObservation,
    MacroSubState,
    Velocity,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle exists only for type checkers
    from .contracts import MacroDomainState
    from .rates import RatesParameters


@dataclass(frozen=True)
class YieldAttribution:
    """How a nominal move splits between real yields and inflation compensation.

    ``identity_residual_bps`` is an identity check on the fetch and nothing more: FRED
    derives ``T10YIE`` as ``DGS10 - DFII10``, so a non-zero residual means the three
    series were read at inconsistent dates, never that a premium appeared.
    """

    nominal_change_bps: Decimal | None
    real_change_bps: Decimal | None
    breakeven_change_bps: Decimal | None
    identity_residual_bps: Decimal | None
    attribution: Literal["real_led", "compensation_led", "mixed", "unavailable"]
    real_share_of_nominal: Decimal | None
    note: str


def attribute_nominal_change(
    *,
    nominal_start: Decimal | None,
    nominal_end: Decimal | None,
    real_start: Decimal | None,
    real_end: Decimal | None,
    breakeven_start: Decimal | None,
    breakeven_end: Decimal | None,
) -> YieldAttribution:
    nominal = _bps(nominal_start, nominal_end)
    real = _bps(real_start, real_end)
    breakeven = _bps(breakeven_start, breakeven_end)
    if nominal is None or real is None or breakeven is None:
        return YieldAttribution(
            nominal_change_bps=nominal,
            real_change_bps=real,
            breakeven_change_bps=breakeven,
            identity_residual_bps=None,
            attribution="unavailable",
            real_share_of_nominal=None,
            note="a leg of the decomposition was not published over this window",
        )
    residual = nominal - real - breakeven
    if abs(real) > abs(breakeven):
        label: Literal["real_led", "compensation_led", "mixed"] = "real_led"
    elif abs(breakeven) > abs(real):
        label = "compensation_led"
    else:
        label = "mixed"
    share = real / nominal if nominal != 0 else None
    return YieldAttribution(
        nominal_change_bps=nominal,
        real_change_bps=real,
        breakeven_change_bps=breakeven,
        identity_residual_bps=residual,
        attribution=label,
        real_share_of_nominal=share,
        note=(
            "real and compensation legs are stated separately; the split is an "
            "attribution of a traded move, not an estimate of term premium"
        ),
    )


def _bps(start: Decimal | None, end: Decimal | None) -> Decimal | None:
    if start is None or end is None:
        return None
    return (end - start) * 100


def year_end_rate(path: PolicyPath, year: int) -> Decimal | None:
    """The rate a path implies for the end of ``year``, in the path's own terms.

    Paths label horizons differently -- the SEP prints a calendar year, a market curve
    prints meeting dates -- so a common horizon has to be resolved before two paths can
    be compared at all.  Comparing a year median against a meeting rate without this
    step compares different questions and calls the difference disagreement.
    """
    labelled = [point for point in path.points if point.horizon.strip() == str(year)]
    if labelled:
        return labelled[0].rate_percent
    dated = [
        point
        for point in path.points
        if point.horizon_date is not None and point.horizon_date.year == year
    ]
    if not dated:
        return None
    return max(dated, key=lambda point: point.horizon_date).rate_percent  # type: ignore[arg-type,return-value]


def horizon_years(path: PolicyPath, *, not_before: int | None = None) -> list[int]:
    """Calendar years this path says something about, earliest first.

    ``not_before`` drops years that have already ended.  A release keeps its horizons
    after the calendar moves past them -- the December 2026 SEP still prints a 2026
    year-end dot in January 2027 -- and the nearest horizon is what both the direction
    vote and the spread comparison reach for.  Without the filter they reach for a
    year whose answer is already known, and report a lean toward a level that has
    either happened or not.
    """
    years: list[int] = []
    for point in path.points:
        label = point.horizon.strip()
        if label.isdigit() and len(label) == 4:
            years.append(int(label))
        elif point.horizon_date is not None:
            years.append(point.horizon_date.year)
    return sorted({year for year in years if not_before is None or year >= not_before})


def forward_spreads(
    by_kind: dict[PolicyPathKind, PolicyPath],
    *,
    not_before: int | None = None,
) -> tuple[int | None, dict[tuple[PolicyPathKind, PolicyPathKind], Decimal]]:
    """Pairwise forward-path spreads in bps at the nearest common FUTURE horizon.

    The **actual** path is excluded. It is where rates are, not where they are going;
    including it would measure the distance from spot to a projection -- curve slope
    dressed up as disagreement -- and would fire on a committee and a market that agree
    perfectly about a coming move.

    ``not_before`` is the year the comparison is being made in.  Without it the nearest
    common horizon can be a year that has already ended, and two forecasts of a settled
    year are not a disagreement about where rates are going.
    """
    forward = {
        kind: path
        for kind, path in by_kind.items()
        if kind in {"committee_projection", "dealer_expectations", "market_implied"}
    }
    if len(forward) < 2:
        return None, {}
    common = set.intersection(
        *(set(horizon_years(path, not_before=not_before)) for path in forward.values())
    )
    if not common:
        return None, {}
    horizon = min(common)
    kinds = sorted(forward)
    spreads: dict[tuple[PolicyPathKind, PolicyPathKind], Decimal] = {}
    for index, left in enumerate(kinds):
        for right in kinds[index + 1 :]:
            left_rate = year_end_rate(forward[left], horizon)
            right_rate = year_end_rate(forward[right], horizon)
            if left_rate is None or right_rate is None:
                continue
            spreads[(left, right)] = abs(left_rate - right_rate) * 100
    return horizon, spreads


def policy_contradictions(
    by_kind: dict[PolicyPathKind, PolicyPath],
    observations: Sequence[DomainObservation],
    *,
    spreads: dict[tuple[PolicyPathKind, PolicyPathKind], Decimal],
    state: str,
    direction: Direction,
    attribution: YieldAttribution | None,
    parameters: "RatesParameters",
) -> tuple[Contradiction, ...]:
    out: list[Contradiction] = []
    threshold = parameters.path_disagreement_bps
    for (left, right), spread in sorted(spreads.items()):
        if spread > threshold:
            out.append(
                Contradiction(
                    rule="policy_paths_disagree",
                    detail=(
                        f"{left} and {right} differ by {spread:.1f}bp at a common "
                        f"horizon, past the {threshold}bp threshold"
                    ),
                )
            )

    actual = by_kind.get("actual")
    if actual is not None and state in {"TIGHTENING", "EASING"}:
        implied = "RISING" if state == "TIGHTENING" else "FALLING"
        if direction != "UNKNOWN" and direction != implied and direction != "FLAT":
            out.append(
                Contradiction(
                    rule="path_conflicts_with_actual",
                    detail=(
                        f"the committee is {state.lower()} while the forward paths "
                        f"point {direction.lower()}"
                    ),
                )
            )

    out.extend(_supply_rules(observations, attribution, parameters))
    out.extend(_decomposition_rules(observations, parameters))
    return tuple(out)


def _supply_rules(
    observations: Sequence[DomainObservation],
    attribution: YieldAttribution | None,
    parameters: "RatesParameters",
) -> list[Contradiction]:
    """Coupon supply at a multi-quarter high while inflation compensation says nothing.

    Elevated means a strict new high against the previous four new-issue sizes rather
    than a percentage over some baseline: auction sizes step in discrete increments the
    Treasury chooses, so "higher than it has been all year" is a statement about the
    publisher's own decisions, not about a threshold we picked.
    """
    if attribution is None:
        return []
    breakeven = attribution.breakeven_change_bps
    nominal = attribution.nominal_change_bps
    if breakeven is None or nominal is None:
        return []
    if abs(breakeven) > parameters.breakeven_flat_bps:
        return []
    if abs(nominal) < parameters.material_nominal_move_bps:
        return []

    elevated = _elevated_supply(observations, parameters)
    if not elevated:
        return []
    return [
        Contradiction(
            rule="supply_pressure_without_macro_confirmation",
            detail=(
                f"{', '.join(elevated)} at a multi-quarter high while the 10y nominal "
                f"moved {nominal:+.0f}bp with inflation compensation at "
                f"{breakeven:+.0f}bp"
            ),
        )
    ]


#: Weeks the positioning-versus-curve comparison spans.  Four, matching the positioning
#: velocity window, so both legs describe the same period -- comparing a four-week
#: position change against a two-month yield move would call the mismatch a disagreement.
_POSITIONING_COMPARISON_WEEKS = 4


def market_contradictions(
    observations: Sequence[DomainObservation],
    sub_states: Sequence[MacroSubState],
    *,
    state: str,
    prior_state: "MacroDomainState | None",
    parameters: "RatesParameters",
) -> tuple[Contradiction, ...]:
    """Where the market layer disagrees with itself or with the policy state.

    A contradiction is an observation about evidence disagreeing.  It never resolves into
    a direction and never changes a state label -- the disagreement IS the output.
    """
    out: list[Contradiction] = []
    out.extend(_positioning_against_curve(observations, sub_states))
    out.extend(_plumbing_without_policy_change(sub_states, state=state))
    return tuple(out)


def _positioning_against_curve(
    observations: Sequence[DomainObservation],
    sub_states: Sequence[MacroSubState],
) -> list[Contradiction]:
    """A stretched position on the wrong side of the move that actually happened.

    A net short profits when yields rise.  If a category is at an extreme of its own
    distribution AND the realised yield move over the same weeks went the other way,
    position and outcome disagree.  Nothing is inferred about where yields go next: the
    rule reports that two pieces of evidence point opposite ways, which is the whole of
    its claim.
    """
    positioning = next(
        (item for item in sub_states if item.role == "positioning"), None
    )
    if positioning is None or not positioning.state.startswith("STRETCHED"):
        return []
    yield_change = _change_over_weeks(
        observations, "DGS10", _POSITIONING_COMPARISON_WEEKS
    )
    if yield_change is None or yield_change == 0:
        return []

    out: list[Contradiction] = []
    for series_id in positioning.series_ids:
        net_series = series_id.removesuffix("_pct_oi")
        net = _latest_value(observations, net_series)
        if net is None or net == 0:
            continue
        # Short profits from rising yields; long from falling.  Same sign on both legs
        # is agreement, opposite signs are the disagreement this rule reports.
        if (net < 0) == (yield_change < 0):
            out.append(
                Contradiction(
                    rule="positioning_against_curve_direction",
                    detail=(
                        f"{net_series} is net {'short' if net < 0 else 'long'} "
                        f"{abs(net):,.0f} contracts at an extreme of its own "
                        f"distribution while the 10y yield moved "
                        f"{yield_change:+.0f}bp over the same "
                        f"{_POSITIONING_COMPARISON_WEEKS} weeks"
                    ),
                )
            )
    return out


def _plumbing_without_policy_change(
    sub_states: Sequence[MacroSubState], *, state: str
) -> list[Contradiction]:
    """Funding stress the committee has not responded to.

    Asserts nothing about what the committee WILL do.  ``ON_HOLD`` is the published fact
    that its last action was a hold, not a forecast that the next one will be.
    """
    plumbing = next((item for item in sub_states if item.role == "plumbing"), None)
    if plumbing is None or plumbing.state != "STRESSED" or state != "ON_HOLD":
        return []
    spread = next(
        (
            reason.detail
            for reason in plumbing.confidence_reasons
            if reason.term == "funding_spread"
        ),
        "the funding spread is at its stressed threshold",
    )
    return [
        Contradiction(
            rule="plumbing_stress_without_policy_change",
            detail=f"{spread}, and the committee's last action was a hold",
        )
    ]


def _change_over_weeks(
    observations: Sequence[DomainObservation], series_id: str, weeks: int
) -> Decimal | None:
    """Basis-point change in a percent-quoted series over ``weeks`` calendar weeks."""
    rows = sorted(
        (obs for obs in observations if obs.series_id == series_id),
        key=lambda obs: obs.period_end,
    )
    if len(rows) < 2:
        return None
    cutoff = rows[-1].period_end - timedelta(weeks=weeks)
    earlier = [row for row in rows if row.period_end <= cutoff]
    start = earlier[-1] if earlier else rows[0]
    return (rows[-1].value - start.value) * 100


def _latest_value(
    observations: Sequence[DomainObservation], series_id: str
) -> Decimal | None:
    rows = [obs for obs in observations if obs.series_id == series_id]
    if not rows:
        return None
    return max(rows, key=lambda obs: obs.period_end).value


def _elevated_supply(
    observations: Sequence[DomainObservation], parameters: "RatesParameters"
) -> list[str]:
    baseline = parameters.supply_baseline_quarters
    by_series: dict[str, list[DomainObservation]] = {}
    for obs in observations:
        if obs.causal_role == "supply":
            by_series.setdefault(obs.series_id, []).append(obs)
    elevated: list[str] = []
    for series_id, rows in sorted(by_series.items()):
        rows.sort(key=lambda row: row.period_end)
        if len(rows) < baseline + 1:
            continue
        prior = rows[-(baseline + 1) : -1]
        if rows[-1].value > max(row.value for row in prior):
            elevated.append(series_id)
    return elevated


def _decomposition_rules(
    observations: Sequence[DomainObservation], parameters: "RatesParameters"
) -> list[Contradiction]:
    """Only the Cleveland model against the traded yield can fail this check.

    Two sums in this domain look like reconciliations and are identities.  FRED derives
    ``T10YIE`` as ``DGS10 - DFII10``, so nominal = real + breakeven cannot fail.  Inside
    the Cleveland model, the expected short real rate is itself derived by subtracting
    the real term premium from the modelled real yield, so adding the premium back is a
    no-op and the component sum reproduces the modelled nominal by construction.  What
    carries information is the gap between that modelled nominal and the yield the
    market actually traded.
    """
    # Selected by series id and NOT by causal role.  Both legs are named here
    # explicitly, so filtering by role buys nothing -- and it once cost the rule its
    # existence: ``RATES_EVIDENCE`` tags ``DGS10`` as ``curve``, deliberately and
    # correctly, so a ``decomposition_component`` filter dropped the traded leg on
    # every production run and the check could never fire no matter what else was
    # ingested.  The unit fixture happened to tag ``DGS10`` with the role the filter
    # wanted, so the rule read as covered while being unreachable.
    values = {obs.series_id: obs.value for obs in observations}
    traded = values.get("DGS10")
    modelled = values.get("CLEVELAND_MODEL_NOMINAL_10Y")
    if traded is None or modelled is None:
        return []
    residual = (traded - modelled) * 100
    if abs(residual) <= parameters.decomposition_tolerance_bps:
        return []
    return [
        Contradiction(
            rule="decomposition_components_do_not_reconcile",
            detail=(
                f"the Cleveland model prices the 10y at {modelled}% against a traded "
                f"{traded}%, a {residual:+.0f}bp gap"
            ),
        )
    ]


def rates_velocity(
    by_kind: dict[PolicyPathKind, PolicyPath],
    horizon: int | None,
    spreads: dict[tuple[PolicyPathKind, PolicyPathKind], Decimal],
    attribution: YieldAttribution | None,
) -> tuple[Velocity, ...]:
    out: list[Velocity] = []
    actual = by_kind.get("actual")
    for kind in ("committee_projection", "dealer_expectations", "market_implied"):
        path = by_kind.get(kind)  # type: ignore[arg-type]
        rate = None if path is None or horizon is None else year_end_rate(path, horizon)
        gap = (
            None
            if rate is None or actual is None
            else (rate - actual.points[0].rate_percent) * 100
        )
        out.append(
            Velocity(
                metric=f"{kind}_vs_actual_bps",
                value=gap,
                unit="bps",
                window_months=0,
                unavailable_reason=(
                    None
                    if gap is not None
                    else f"no {kind} rate at a horizon shared with the other paths"
                ),
            )
        )
    widest = max(spreads.values()) if spreads else None
    out.append(
        Velocity(
            metric="widest_forward_path_spread_bps",
            value=widest,
            unit="bps",
            window_months=0,
            unavailable_reason=(
                None if widest is not None else "fewer than two forward paths available"
            ),
        )
    )
    if attribution is not None:
        out.append(
            Velocity(
                metric="real_share_of_nominal_change",
                value=attribution.real_share_of_nominal,
                unit="ratio",
                window_months=0,
                unavailable_reason=(
                    None
                    if attribution.real_share_of_nominal is not None
                    else attribution.note
                ),
            )
        )
    return tuple(out)
