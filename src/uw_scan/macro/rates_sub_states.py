"""The rates market sub-states: supply, positioning, plumbing.

These describe conditions the committee acts into.  None of them changes the policy
state, and none infers a policy direction -- ``macro/rates.py:169`` already documents why
widening the policy denominator is unsafe, and this module is the presentation half of
that ruling: each role computes its own confidence over its own required series, so a
surface can render a sub-state beside the policy state without either standing in for the
other.

Three calibration decisions here were measured rather than picked, and each is recorded
where it is made:

* **Supply aggregates by majority, not by "any".**  Seven coupon terms each sitting at a
  five-issue high roughly a quarter of the time makes "any term elevated" fire on ~87% of
  draws -- a label that is almost always ELEVATED says nothing.
* **Positioning is scored against its own trailing distribution.**  Leveraged money in
  the 10-year note future is net short in every week of the measured sample, so an
  absolute long/short threshold would fire permanently for one category and never for
  another.
* **Plumbing classifies on a PRICE, never on a quantity level.**  See ``_plumbing_label``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from .confidence import compute_confidence
from .contracts import (
    CausalRole,
    ConfidenceTerm,
    Direction,
    DomainObservation,
    FactorState,
    MacroSubState,
    Velocity,
    freshness_for,
)

#: Percentile bands a positioning share must clear to be called stretched.  Symmetric and
#: conventional; the calibration that matters is the WINDOW they are taken over, which is
#: the caller's (spec 4.2's sample), not a level chosen here.
STRETCHED_LOW_PERCENTILE = Decimal("0.10")
STRETCHED_HIGH_PERCENTILE = Decimal("0.90")

#: The fewest observations a percentile claim is allowed to rest on.  Ten leaves each
#: decile one observation; below that "the 10th percentile" is the minimum wearing a
#: statistical word.
MIN_POSITIONING_OBSERVATIONS = 10

#: SOFR minus EFFR, in basis points.
#:
#: TIGHTENING at the 95th percentile of the measured sample -- 1,405 business days,
#: 2021-01-04 to 2026-08-19, where the spread runs a median of -2bp and reaches +6bp at
#: p95.  That is a relative-to-own-history claim and the sample supports it.
#:
#: STRESSED is NOT taken from that sample, and the reason is the sample itself: it
#: contains no funding crisis, so its p99 (+15bp) marks the most unusual day of a calm
#: period rather than a stressed one.  Calibrating stress to it would have labelled
#: 2025-10-28 STRESSED at +19bp and left no label for 2019-09-17, when SOFR printed 5.25
#: against an effective rate of 2.30 -- **+295bp**.  So the threshold is one policy move,
#: the same 25bp ``RatesParameters.material_nominal_move_bps`` already uses for "a move
#: worth explaining": if the overnight secured rate is a full policy increment away from
#: the effective rate, the corridor is not holding.  It fires on 2 of 1,405 measured days
#: and on the real 2019 event.
PLUMBING_TIGHTENING_BPS = Decimal("6")
PLUMBING_STRESSED_BPS = Decimal("25")

_SPREAD_LEGS = ("SOFR", "EFFR")

#: Weekly, because that is the report's own cadence.  A Tuesday with no observation is
#: reported as absent rather than interpolated: an absent week is not a zero position.
_POSITIONING_PERIOD_DAYS = 7


@dataclass(frozen=True)
class SubStateInputs:
    """Everything a sub-state builder needs, resolved once by the caller."""

    observations: tuple[DomainObservation, ...]
    factors: tuple[FactorState, ...]
    as_of: datetime
    cadence_days: int
    freshness_decay_multiple: Decimal


def build_sub_states(
    observations: Sequence[DomainObservation],
    factors: Sequence[FactorState],
    *,
    as_of: datetime,
    supply_baseline_quarters: int,
    cadence_by_role: dict[CausalRole, int],
    freshness_decay_multiple: Decimal,
) -> tuple[MacroSubState, ...]:
    """One sub-state per market role, each with its own confidence.

    Roles absent from the evidence still get a sub-state -- ``UNKNOWN`` with the reason --
    because a role that simply vanishes from the output is indistinguishable from a role
    that was never declared.
    """

    def resolve(role: CausalRole) -> SubStateInputs:
        return _inputs(
            observations,
            factors,
            role,
            as_of,
            cadence_by_role[role],
            freshness_decay_multiple,
        )

    return (
        _supply(resolve("supply"), baseline=supply_baseline_quarters),
        _positioning(resolve("positioning")),
        _plumbing(resolve("plumbing")),
    )


def _inputs(
    observations: Sequence[DomainObservation],
    factors: Sequence[FactorState],
    role: CausalRole,
    as_of: datetime,
    cadence_days: int,
    freshness_decay_multiple: Decimal,
) -> SubStateInputs:
    return SubStateInputs(
        observations=tuple(
            sorted(
                (obs for obs in observations if obs.causal_role == role),
                key=lambda obs: (obs.series_id, obs.period_end),
            )
        ),
        factors=tuple(factor for factor in factors if factor.causal_role == role),
        as_of=as_of,
        cadence_days=cadence_days,
        freshness_decay_multiple=freshness_decay_multiple,
    )


# ----------------------------------------------------------------------------- supply


def _supply(inputs: SubStateInputs, *, baseline: int) -> MacroSubState:
    by_series = _group(inputs.observations)
    if not by_series:
        return _unknown(
            "supply", inputs, "no supply observation was available at as_of"
        )

    # Checked for supply exactly as for the other two roles.  An auction calendar that has
    # gone silent for a year is not a current supply condition, and classifying its last
    # print would report a 2024 refunding as today's.
    stale = _stalest(inputs)
    if stale is not None:
        return _unknown("supply", inputs, stale)

    needed = baseline + 1
    classified: dict[str, str] = {}
    short: list[str] = []
    for series_id, rows in by_series.items():
        if len(rows) < needed:
            short.append(f"{series_id} ({len(rows)}/{needed})")
            continue
        prior = [row.value for row in rows[-needed:-1]]
        latest = rows[-1].value
        classified[series_id] = (
            "ELEVATED"
            if latest > max(prior)
            else "REDUCED"
            if latest < min(prior)
            else "IN_RANGE"
        )

    if not classified:
        return _unknown(
            "supply",
            inputs,
            f"no term has the {needed} new issues a {baseline}-quarter baseline needs: "
            + ", ".join(short),
        )

    elevated = sorted(k for k, v in classified.items() if v == "ELEVATED")
    reduced = sorted(k for k, v in classified.items() if v == "REDUCED")
    # Majority, not "any".  Seven terms each at a five-issue high about a quarter of the
    # time puts "any" at ~87%, and a label that is almost always ELEVATED is not a label.
    half = Decimal(len(classified)) / 2
    if Decimal(len(elevated)) > half:
        label = "ELEVATED"
    elif Decimal(len(reduced)) > half:
        label = "REDUCED"
    else:
        label = "IN_RANGE"

    latest_rows = [rows[-1] for rows in by_series.values() if len(rows) >= 2]
    rising = sum(1 for rows in by_series.values() if _rose(rows))
    falling = sum(1 for rows in by_series.values() if _fell(rows))
    direction: Direction = (
        "RISING" if rising > falling else "FALLING" if falling > rising else "FLAT"
    )

    detail = f"{len(elevated)}/{len(classified)} terms at a {baseline}-quarter high"
    if elevated:
        detail += f": {', '.join(elevated)}"
    if short:
        detail += f"; below the minimum row count: {', '.join(short)}"
    return _assemble(
        role="supply",
        label=label,
        direction=direction,
        inputs=inputs,
        series_ids=tuple(sorted(by_series)),
        velocity=(_supply_velocity(by_series),),
        extra=(
            ConfidenceTerm(
                term="supply_terms_classified",
                value=Decimal(len(classified)),
                detail=detail,
                kind="informational",
            ),
        ),
        observed=tuple(row.period_end for row in latest_rows),
    )


def _supply_velocity(by_series: dict[str, list[DomainObservation]]) -> Velocity:
    """Gross coupon supply this issue round against the one before it.

    Summed ACROSS terms and never within one: a 2-year and a 30-year are both dollars of
    issuance, which is the quantity a supply pressure read is about, while comparing one
    term's size against another's would be comparing durations.
    """
    latest = sum(
        (rows[-1].value for rows in by_series.values() if rows), start=Decimal(0)
    )
    prior = sum(
        (rows[-2].value for rows in by_series.values() if len(rows) >= 2),
        start=Decimal(0),
    )
    covered = [rows for rows in by_series.values() if len(rows) >= 2]
    if not covered:
        return Velocity(
            metric="gross_coupon_new_issue_change",
            value=None,
            unit="usd_offering_amount",
            window_months=3,
            unavailable_reason="no term has two new issues to compare",
        )
    return Velocity(
        metric="gross_coupon_new_issue_change",
        value=latest - prior,
        unit="usd_offering_amount",
        window_months=3,
    )


def _rose(rows: list[DomainObservation]) -> bool:
    return len(rows) >= 2 and rows[-1].value > rows[-2].value


def _fell(rows: list[DomainObservation]) -> bool:
    return len(rows) >= 2 and rows[-1].value < rows[-2].value


# ------------------------------------------------------------------------ positioning


def _positioning(inputs: SubStateInputs) -> MacroSubState:
    shares = {
        series_id: rows
        for series_id, rows in _group(inputs.observations).items()
        if series_id.endswith("_net_pct_oi")
    }
    if not shares:
        return _unknown(
            "positioning", inputs, "no positioning observation was available at as_of"
        )

    stale = _stalest(inputs)
    if stale is not None:
        return _unknown("positioning", inputs, stale)

    labels: dict[str, str] = {}
    percentiles: dict[str, Decimal] = {}
    thin: list[str] = []
    for series_id, rows in shares.items():
        if len(rows) < MIN_POSITIONING_OBSERVATIONS:
            thin.append(f"{series_id} ({len(rows)}/{MIN_POSITIONING_OBSERVATIONS})")
            continue
        pct = _percentile_of_latest([row.value for row in rows])
        percentiles[series_id] = pct
        labels[series_id] = (
            "STRETCHED_LOW"
            if pct <= STRETCHED_LOW_PERCENTILE
            else "STRETCHED_HIGH"
            if pct >= STRETCHED_HIGH_PERCENTILE
            else "IN_RANGE"
        )

    if not labels:
        return _unknown(
            "positioning",
            inputs,
            "no category has the "
            f"{MIN_POSITIONING_OBSERVATIONS} weeks a percentile claim needs: "
            + ", ".join(thin),
        )

    low = sorted(k for k, v in labels.items() if v == "STRETCHED_LOW")
    high = sorted(k for k, v in labels.items() if v == "STRETCHED_HIGH")
    # Any, not majority, and deliberately unlike supply: the categories are each other's
    # counterparties, so a stretched leveraged short IS somebody's stretched long and
    # requiring a majority would ask the report to contradict its own construction.
    label = (
        "STRETCHED_LOW"
        if low and not high
        else "STRETCHED_HIGH"
        if high and not low
        else "IN_RANGE"
    )

    absent = _absent_weeks(shares)
    extra = [
        ConfidenceTerm(
            term="positioning_percentiles",
            value=Decimal(len(percentiles)),
            detail="; ".join(
                f"{series_id} at p{percentiles[series_id] * 100:.0f} ({labels[series_id]})"
                for series_id in sorted(percentiles)
            ),
            kind="informational",
        )
    ]
    if absent:
        extra.append(
            ConfidenceTerm(
                term="positioning_weeks_absent",
                value=Decimal(len(absent)),
                detail=(
                    "no observation for "
                    + ", ".join(day.isoformat() for day in absent)
                    + "; an absent week is not a zero position and not a parse failure. "
                    "CFTC shifts the report date itself on holiday weeks, so an absent "
                    "Tuesday may be covered by a neighbouring dated report"
                ),
                kind="informational",
            )
        )
    return _assemble(
        role="positioning",
        label=label,
        direction=_positioning_direction(shares),
        inputs=inputs,
        series_ids=tuple(sorted(shares)),
        velocity=tuple(
            _positioning_velocity(series_id, rows)
            for series_id, rows in sorted(shares.items())
        ),
        extra=tuple(extra),
        observed=tuple(rows[-1].period_end for rows in shares.values()),
    )


def _percentile_of_latest(values: Sequence[Decimal]) -> Decimal:
    """Where the latest reading sits in its own history, on [0, 1].

    Rank over ``n - 1`` rather than ``n`` so the minimum is exactly 0 and the maximum
    exactly 1; over ``n`` the extreme of a short series never reaches its own band.
    """
    latest = values[-1]
    below = sum(1 for value in values if value < latest)
    ties = sum(1 for value in values if value == latest)
    # Mid-rank for ties, so a series sitting at a repeated value is not credited with
    # being at the extreme of a range it shares.
    rank = Decimal(below) + (Decimal(ties) - 1) / 2
    return rank / Decimal(len(values) - 1)


def _positioning_direction(shares: dict[str, list[DomainObservation]]) -> Direction:
    rising = sum(1 for rows in shares.values() if _rose(rows))
    falling = sum(1 for rows in shares.values() if _fell(rows))
    return "RISING" if rising > falling else "FALLING" if falling > rising else "FLAT"


def _positioning_velocity(series_id: str, rows: list[DomainObservation]) -> Velocity:
    metric = f"{series_id}_change_4w"
    if len(rows) < 5:
        return Velocity(
            metric=metric,
            value=None,
            unit="pct_open_interest",
            window_months=1,
            unavailable_reason=f"{len(rows)}/5 weekly observations",
        )
    return Velocity(
        metric=metric,
        value=rows[-1].value - rows[-5].value,
        unit="pct_open_interest",
        window_months=1,
    )


def _absent_weeks(shares: dict[str, list[DomainObservation]]) -> list[date]:
    """Report dates the weekly grid expects and no observation covers."""
    seen: set[date] = {row.period_end for rows in shares.values() for row in rows}
    if not seen:
        return []
    day, last = min(seen), max(seen)
    out: list[date] = []
    while day < last:
        day = day + timedelta(days=_POSITIONING_PERIOD_DAYS)
        if day <= last and day not in seen:
            out.append(day)
    return out


# --------------------------------------------------------------------------- plumbing


def _plumbing(inputs: SubStateInputs) -> MacroSubState:
    by_series = _group(inputs.observations)
    missing = [leg for leg in _SPREAD_LEGS if leg not in by_series]
    if missing:
        return _unknown(
            "plumbing",
            inputs,
            f"the funding spread needs both legs and {', '.join(missing)} had no "
            "observation available at as_of",
        )

    stale = _stalest(inputs)
    if stale is not None:
        return _unknown("plumbing", inputs, stale)

    spread = _spread_series(by_series["SOFR"], by_series["EFFR"])
    if not spread:
        return _unknown(
            "plumbing",
            inputs,
            "SOFR and EFFR share no observation date, so no spread can be formed",
        )

    latest_day, latest_bps = spread[-1]
    label = _plumbing_label(latest_bps)
    return _assemble(
        role="plumbing",
        label=label,
        direction=_plumbing_direction(spread),
        inputs=inputs,
        series_ids=tuple(sorted(by_series)),
        velocity=(
            _spread_velocity(spread, weeks=4, window_months=1),
            _spread_velocity(spread, weeks=13, window_months=3),
        ),
        extra=(
            ConfidenceTerm(
                term="funding_spread",
                value=latest_bps,
                detail=(
                    f"SOFR less EFFR at {latest_bps:+.0f}bp on {latest_day.isoformat()}; "
                    f"tightening at {PLUMBING_TIGHTENING_BPS:+.0f}bp, stressed at "
                    f"{PLUMBING_STRESSED_BPS:+.0f}bp"
                ),
                kind="informational",
            ),
        ),
        observed=(latest_day,),
    )


def _plumbing_label(spread_bps: Decimal) -> str:
    """Classified on the PRICE, never on a quantity level.

    RRP take-up is carried as evidence and reported as a factor, and it is deliberately
    not in this decision.  Its level is regime-dependent in a way that has nothing to do
    with stress: it ran about 2bn through 2019 because the facility was structurally
    small, and about 2,300bn in 2022 because of the reserve glut.  A rule keyed on "RRP
    near zero" reads 2019 as permanently exhausted and would have MISSED the one real
    funding crisis in the record -- on 2019-09-17, the day SOFR printed 295bp over the
    effective rate, RRP stood at 1.825bn, which is unremarkable for that year.  A spread
    is a price and comparable across both regimes.
    """
    if spread_bps >= PLUMBING_STRESSED_BPS:
        return "STRESSED"
    if spread_bps >= PLUMBING_TIGHTENING_BPS:
        return "TIGHTENING"
    return "AMPLE"


def _spread_series(
    sofr: list[DomainObservation], effr: list[DomainObservation]
) -> list[tuple[date, Decimal]]:
    effr_by_day = {row.period_end: row.value for row in effr}
    return [
        (row.period_end, (row.value - effr_by_day[row.period_end]) * 100)
        for row in sofr
        if row.period_end in effr_by_day
    ]


def _plumbing_direction(spread: list[tuple[date, Decimal]]) -> Direction:
    if len(spread) < 2:
        return "UNKNOWN"
    change = spread[-1][1] - spread[0][1]
    if change > 0:
        return "RISING"
    return "FALLING" if change < 0 else "FLAT"


def _spread_velocity(
    spread: list[tuple[date, Decimal]], *, weeks: int, window_months: int
) -> Velocity:
    metric = f"sofr_effr_spread_change_{weeks}w"
    # Business days, which is what a daily rate publishes on.
    offset = weeks * 5
    if len(spread) <= offset:
        return Velocity(
            metric=metric,
            value=None,
            unit="basis_points",
            window_months=window_months,
            unavailable_reason=f"{len(spread)} spread days, {offset + 1} needed",
        )
    return Velocity(
        metric=metric,
        value=spread[-1][1] - spread[-1 - offset][1],
        unit="basis_points",
        window_months=window_months,
    )


# ---------------------------------------------------------------------------- shared


def _group(
    observations: Sequence[DomainObservation],
) -> dict[str, list[DomainObservation]]:
    out: dict[str, list[DomainObservation]] = {}
    for obs in observations:
        out.setdefault(obs.series_id, []).append(obs)
    for rows in out.values():
        rows.sort(key=lambda row: row.period_end)
    return out


def _stalest(inputs: SubStateInputs) -> str | None:
    """The reason string when this role's freshest input is past its own cadence.

    Checked before sample size so the reported reason is the dominant one: a feed that
    has gone quiet for months is a different problem from one that is simply young, and
    reporting the second hides the first.
    """
    if not inputs.observations:
        return None
    freshest = max(obs.available_at for obs in inputs.observations)
    age_days = (inputs.as_of.date() - freshest.date()).days
    if (
        freshness_for(age_days, inputs.cadence_days, inputs.freshness_decay_multiple)
        > 0
    ):
        return None
    return (
        f"the freshest observation became available {age_days}d before as_of, past a "
        f"{inputs.cadence_days}d cadence; the publisher has gone quiet and a stale "
        "reading is not a current condition"
    )


def _unknown(role: CausalRole, inputs: SubStateInputs, reason: str) -> MacroSubState:
    """UNKNOWN, never NEUTRAL.

    Absence is not a centred reading, and rendering it as one is the defect
    ``macro/confidence.py`` was written to replace.
    """
    return MacroSubState(
        role=role,
        state="UNKNOWN",
        direction="UNKNOWN",
        velocity=(),
        confidence=Decimal(0),
        confidence_reasons=(
            ConfidenceTerm(
                term=f"{role}_unavailable",
                value=Decimal(0),
                detail=reason,
                kind="informational",
            ),
        ),
        series_ids=tuple(sorted({obs.series_id for obs in inputs.observations})),
        unavailable_reason=reason,
    )


def _assemble(
    *,
    role: CausalRole,
    label: str,
    direction: Direction,
    inputs: SubStateInputs,
    series_ids: tuple[str, ...],
    velocity: tuple[Velocity, ...],
    extra: tuple[ConfidenceTerm, ...],
    observed: tuple[date, ...],
) -> MacroSubState:
    """Its own confidence, over its own required series.

    Not the policy state's: R2 keeps ``POLICY_REQUIRED`` at the three policy paths, and
    what changes is presentation -- a sub-state that borrowed the domain number would be
    exactly the substitution that ruling refuses.
    """
    confidence, reasons = compute_confidence(
        [factor for factor in inputs.factors if factor.series_id in set(series_ids)],
        required_series=series_ids,
        contradictions=(),
        contradiction_penalty_each=Decimal(0),
        contradiction_penalty_cap=Decimal(0),
    )
    return MacroSubState(
        role=role,
        state=label,
        direction=direction,
        velocity=velocity,
        confidence=confidence,
        confidence_reasons=reasons + extra,
        series_ids=series_ids,
        latest_period_end=max(observed) if observed else None,
    )
