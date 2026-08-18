"""Horizon resolution and the rules that fire when the rates evidence disagrees.

Split from ``rates.py`` because these are the parts that state what *cannot* be
concluded, and they read better as one piece: how to line two paths up at a comparable
horizon, when their disagreement is real, and which decompositions can fail at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from uw_scan.models.macro import PolicyPath, PolicyPathKind

from .contracts import Contradiction, Direction, DomainObservation, Velocity

if TYPE_CHECKING:  # pragma: no cover - import cycle exists only for type checkers
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


def horizon_years(path: PolicyPath) -> list[int]:
    years: list[int] = []
    for point in path.points:
        label = point.horizon.strip()
        if label.isdigit() and len(label) == 4:
            years.append(int(label))
        elif point.horizon_date is not None:
            years.append(point.horizon_date.year)
    return sorted(set(years))


def forward_spreads(
    by_kind: dict[PolicyPathKind, PolicyPath],
) -> tuple[int | None, dict[tuple[PolicyPathKind, PolicyPathKind], Decimal]]:
    """Pairwise forward-path spreads in bps at the nearest common calendar horizon.

    The **actual** path is excluded. It is where rates are, not where they are going;
    including it would measure the distance from spot to a projection -- curve slope
    dressed up as disagreement -- and would fire on a committee and a market that agree
    perfectly about a coming move.
    """
    forward = {
        kind: path
        for kind, path in by_kind.items()
        if kind in {"committee_projection", "dealer_expectations", "market_implied"}
    }
    if len(forward) < 2:
        return None, {}
    common = set.intersection(*(set(horizon_years(path)) for path in forward.values()))
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
    values = {
        obs.series_id: obs.value
        for obs in observations
        if obs.causal_role == "decomposition_component"
    }
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
