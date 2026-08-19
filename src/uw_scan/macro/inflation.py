"""Point-in-time inflation state.

The state basis is **core PCE**, because the FOMC's 2 percent objective is stated on
PCE.  Core CPI has run persistently above core PCE across the whole sample, so scoring
CPI against a 2 percent threshold mislabels the regime by roughly one policy move,
permanently and in one direction.  CPI is not discarded -- it lands about two weeks
earlier and corroborates -- but it is a factor and a contradiction input, never the
level being thresholded.

Every transform is computed here rather than in a source module, and only from
observations that were the published values at ``as_of``.  Design and preregistered
scenarios: ``docs/superpowers/specs/2026-08-18-inflation-rates-state-design.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from .confidence import compute_confidence
from .contracts import (
    CausalRole,
    Contradiction,
    Direction,
    DomainObservation,
    EvidenceRef,
    FactorState,
    MacroDomainState,
    Velocity,
    compute_inputs_hash,
    freshness_for,
)
from .transforms import (
    annualized_over_months,
    change_over_months,
    newest_period,
    yoy_change_over_months,
    yoy_from_index,
)

INFLATION_ENGINE_VERSION = "inflation/1"

InflationStateLabel = Literal[
    "BELOW_TARGET",
    "AT_TARGET",
    "ABOVE_TARGET",
    "WELL_ABOVE_TARGET",
    "INDETERMINATE",
]

STATE_BASIS = "PCEPILFE"
HEADLINE_PCE = "PCEPI"
CORE_CPI = "CPILFESL"
HEADLINE_CPI = "CPIAUCSL"
MEDIAN_CPI = "MEDCPIM158SFRBCLE"
TRIMMED_MEAN_CPI = "TRMMEANCPIM158SFRBCLE"
STICKY_CORE = "CORESTICKM159SFRBATL"
SURVEY_EXPECTATIONS = "MICH"

#: Series whose absence degrades the state, with the cadence freshness decays against.
#: Deliberately the engine's own table and not the source adapter's: which inputs are
#: load-bearing is a claim about this state, not about where the bytes came from.
REQUIRED: dict[str, tuple[CausalRole, int]] = {
    STATE_BASIS: ("realized", 31),
    HEADLINE_PCE: ("realized", 31),
    CORE_CPI: ("realized", 31),
    HEADLINE_CPI: ("realized", 31),
    MEDIAN_CPI: ("breadth", 31),
    TRIMMED_MEAN_CPI: ("breadth", 31),
    STICKY_CORE: ("stickiness", 31),
    SURVEY_EXPECTATIONS: ("expectations_survey", 31),
}

#: Transforms that mean "this value is an index level", so a rate must be derived from
#: it.  Anything else already IS a rate in the publisher's own units.
_INDEX_TRANSFORMS = frozenset({"index", "index_level"})


@dataclass(frozen=True)
class InflationParameters:
    """Versioned thresholds, hashed into ``inputs_hash`` rather than hidden in constants."""

    version: str = "inflation/1"
    at_target_lower: Decimal = Decimal("1.75")
    at_target_upper: Decimal = Decimal("2.25")
    above_target_upper: Decimal = Decimal("3.00")
    direction_threshold_pp: Decimal = Decimal("0.15")
    change_window_months: int = 3
    # Core CPI runs structurally above core PCE; the wedge is expected, the excess is not.
    cpi_pce_wedge_pp: Decimal = Decimal("0.30")
    cpi_pce_tolerance_pp: Decimal = Decimal("0.50")
    headline_core_divergence_pp: Decimal = Decimal("1.00")
    expectations_divergence_pp: Decimal = Decimal("0.20")
    completeness_floor: Decimal = Decimal("0.50")
    indeterminate_confidence_cap: Decimal = Decimal("0.25")
    contradiction_penalty_each: Decimal = Decimal("0.15")
    contradiction_penalty_cap: Decimal = Decimal("0.60")
    freshness_decay_multiple: Decimal = Decimal("3")

    def as_record(self) -> dict[str, Any]:
        return {
            key: (format(value, "f") if isinstance(value, Decimal) else value)
            for key, value in sorted(asdict(self).items())
        }


DEFAULT_INFLATION_PARAMETERS = InflationParameters()


def compute_inflation_state(
    observations: Iterable[DomainObservation],
    *,
    as_of: datetime,
    parameters: InflationParameters = DEFAULT_INFLATION_PARAMETERS,
    target_period: date | None = None,
    prior_state: MacroDomainState | None = None,
) -> MacroDomainState:
    """Build the inflation state that was knowable at ``as_of``.

    ``target_period`` pins the period the state must describe.  When it is given and
    that period is not published yet, the state abstains: there is no forward fill and
    no substitution of a neighbouring series, because either one manufactures a month
    the publisher never released.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    eligible = tuple(obs for obs in observations if obs.is_known_on(as_of))
    latest = _latest_vintages(eligible, ceiling=target_period)
    series = {
        series_id: {period: obs.value for period, obs in rows.items()}
        for series_id, rows in latest.items()
    }

    basis = series.get(STATE_BASIS, {})
    basis_period = target_period if target_period is not None else newest_period(basis)
    period_absent = basis_period is None or basis_period not in basis

    window = parameters.change_window_months
    core_yoy = (
        None if period_absent else yoy_from_index(basis, basis_period)  # type: ignore[arg-type]
    )
    core_change = (
        None if period_absent else yoy_change_over_months(basis, basis_period, window)  # type: ignore[arg-type]
    )

    factors = _factors(latest, series, as_of=as_of, parameters=parameters)
    direction = _direction(core_change, parameters.direction_threshold_pp)
    contradictions = _contradictions(
        series,
        factors,
        core_yoy=core_yoy,
        core_change=core_change,
        direction=direction,
        parameters=parameters,
    )
    state: InflationStateLabel = (
        "INDETERMINATE" if core_yoy is None else _label(core_yoy, parameters)
    )

    confidence, reasons = compute_confidence(
        factors,
        required_series=tuple(REQUIRED),
        contradictions=contradictions,
        contradiction_penalty_each=parameters.contradiction_penalty_each,
        contradiction_penalty_cap=parameters.contradiction_penalty_cap,
        prior_state=prior_state,
        absent_reason=(
            None
            if not period_absent
            else (
                f"no {STATE_BASIS} observation for "
                f"{target_period.isoformat() if target_period else 'any period'} was "
                "published at as_of; the state abstains rather than forward-filling"
            )
        ),
    )
    completeness = next(term.value for term in reasons if term.term == "completeness")
    if completeness < parameters.completeness_floor or period_absent:
        # The defect being fixed: a composite that renormalises over surviving weight
        # reports full conviction from one populated input.  Absence is not a view.
        state = "INDETERMINATE"
        confidence = min(confidence, parameters.indeterminate_confidence_cap)

    used = tuple(obs for rows in latest.values() for obs in rows.values())
    return MacroDomainState(
        domain="inflation",
        state=state,
        direction=direction,
        velocity=_velocity(basis, basis_period, window, period_absent=period_absent),
        confidence=confidence,
        confidence_reasons=reasons,
        contradictions=contradictions,
        factors=factors,
        evidence_refs=tuple(
            EvidenceRef(
                series_id=obs.series_id,
                period_end=obs.period_end,
                causal_role=obs.causal_role,
                available_at=obs.available_at,
                obs_id=obs.obs_id,
                artifact_id=obs.artifact_id,
            )
            for obs in sorted(used, key=lambda o: (o.series_id, o.period_end))
        ),
        engine_version=INFLATION_ENGINE_VERSION,
        inputs_hash=compute_inputs_hash(
            engine_version=INFLATION_ENGINE_VERSION,
            parameters=parameters.as_record(),
            observations=used,
        ),
        as_of=as_of,
    )


def _latest_vintages(
    observations: tuple[DomainObservation, ...], *, ceiling: date | None
) -> dict[str, dict[date, DomainObservation]]:
    """One observation per (series, period), or fail closed on overlapping vintages.

    Two eligible values for the same period means two vintage windows claim the same
    instant.  Picking either one would silently choose a number; the publisher's own
    windows do not overlap, so this is a normalisation bug and must surface as one.
    """
    out: dict[str, dict[date, DomainObservation]] = {}
    for obs in observations:
        if ceiling is not None and obs.period_end > ceiling:
            continue
        rows = out.setdefault(obs.series_id, {})
        existing = rows.get(obs.period_end)
        if existing is not None:
            raise ValueError(
                f"overlapping vintages for {obs.series_id} at {obs.period_end}: "
                f"{existing.value} available {existing.available_at.isoformat()} and "
                f"{obs.value} available {obs.available_at.isoformat()}"
            )
        rows[obs.period_end] = obs
    return out


def _label(core_yoy: Decimal, parameters: InflationParameters) -> InflationStateLabel:
    if core_yoy < parameters.at_target_lower:
        return "BELOW_TARGET"
    if core_yoy <= parameters.at_target_upper:
        return "AT_TARGET"
    if core_yoy <= parameters.above_target_upper:
        return "ABOVE_TARGET"
    return "WELL_ABOVE_TARGET"


def _direction(change: Decimal | None, threshold: Decimal) -> Direction:
    if change is None:
        return "UNKNOWN"
    if change <= -threshold:
        return "FALLING"
    if change >= threshold:
        return "RISING"
    return "FLAT"


def _factors(
    latest: dict[str, dict[date, DomainObservation]],
    series: dict[str, dict[date, Decimal]],
    *,
    as_of: datetime,
    parameters: InflationParameters,
) -> tuple[FactorState, ...]:
    out: list[FactorState] = []
    for series_id, (role, cadence_days) in REQUIRED.items():
        rows = latest.get(series_id)
        if not rows:
            continue
        period = max(rows)
        obs = rows[period]
        values = series[series_id]
        # An index level has to be turned into a rate before it can be compared; a
        # publisher-transformed series already IS a rate, so differencing it twice
        # would report the change of a change.
        change = (
            yoy_change_over_months(values, period, parameters.change_window_months)
            if obs.publisher_transform in _INDEX_TRANSFORMS
            else change_over_months(values, period, parameters.change_window_months)
        )
        age_days = (as_of.date() - obs.available_at.date()).days
        out.append(
            FactorState(
                name=f"{role}:{series_id}",
                causal_role=role,
                series_id=series_id,
                period_end=period,
                value=obs.value,
                unit=obs.unit,
                direction=_direction(change, parameters.direction_threshold_pp),
                change_over_window=change,
                available_at=obs.available_at,
                age_days=age_days,
                freshness=freshness_for(
                    age_days, cadence_days, parameters.freshness_decay_multiple
                ),
                quality_status=obs.quality_status,
                source=obs.source,
                source_kind=obs.source_kind,
            )
        )
    return tuple(out)


def _yoy_at_latest(
    series: dict[str, dict[date, Decimal]], series_id: str
) -> Decimal | None:
    values = series.get(series_id, {})
    period = newest_period(values)
    return None if period is None else yoy_from_index(values, period)


def _contradictions(
    series: dict[str, dict[date, Decimal]],
    factors: tuple[FactorState, ...],
    *,
    core_yoy: Decimal | None,
    core_change: Decimal | None,
    direction: Direction,
    parameters: InflationParameters,
) -> tuple[Contradiction, ...]:
    by_series = {factor.series_id: factor for factor in factors}
    out: list[Contradiction] = []

    core_cpi_yoy = _yoy_at_latest(series, CORE_CPI)
    if core_yoy is not None and core_cpi_yoy is not None:
        excess = core_cpi_yoy - core_yoy - parameters.cpi_pce_wedge_pp
        if abs(excess) > parameters.cpi_pce_tolerance_pp:
            out.append(
                Contradiction(
                    rule="cpi_pce_divergence",
                    detail=(
                        f"core CPI {_pp(core_cpi_yoy)} vs core PCE {_pp(core_yoy)} "
                        f"exceeds the {_pp(parameters.cpi_pce_wedge_pp)} wedge by "
                        f"{_pp(excess)}"
                    ),
                )
            )

    headline_yoy = _yoy_at_latest(series, HEADLINE_PCE)
    if core_yoy is not None and headline_yoy is not None:
        gap = headline_yoy - core_yoy
        if abs(gap) > parameters.headline_core_divergence_pp:
            out.append(
                Contradiction(
                    rule="headline_core_divergence",
                    detail=(
                        f"headline PCE {_pp(headline_yoy)} vs core {_pp(core_yoy)}, "
                        f"a {_pp(gap)} gap in level"
                    ),
                )
            )

    sticky = by_series.get(STICKY_CORE)
    if (
        direction == "FALLING"
        and sticky is not None
        and sticky.change_over_window is not None
        and sticky.change_over_window >= 0
    ):
        out.append(
            Contradiction(
                rule="stickiness_not_confirming_disinflation",
                detail=(
                    f"core PCE falling {_pp(core_change)} while sticky core moved "
                    f"{_pp(sticky.change_over_window)}"
                ),
            )
        )

    median = by_series.get(MEDIAN_CPI)
    if (
        median is not None
        and median.change_over_window is not None
        and core_change is not None
        and _opposed(median.change_over_window, core_change)
    ):
        out.append(
            Contradiction(
                rule="breadth_contradicts_core",
                detail=(
                    f"median CPI moved {_pp(median.change_over_window)} while core PCE "
                    f"moved {_pp(core_change)}"
                ),
            )
        )

    trimmed = by_series.get(TRIMMED_MEAN_CPI)
    if (
        median is not None
        and trimmed is not None
        and median.change_over_window is not None
        and trimmed.change_over_window is not None
        and _opposed(median.change_over_window, trimmed.change_over_window)
    ):
        out.append(
            Contradiction(
                rule="breadth_measures_disagree",
                detail=(
                    f"median CPI moved {_pp(median.change_over_window)} while trimmed "
                    f"mean moved {_pp(trimmed.change_over_window)} over the same window"
                ),
            )
        )

    survey = by_series.get(SURVEY_EXPECTATIONS)
    # Dormant, and the condition for waking it is exact: ``_factors`` only builds a
    # factor for a series listed in ``REQUIRED``, so a market-compensation series has
    # to be added THERE with the ``expectations_market`` role before this can fire.
    # Ingesting the series is not enough -- ``T10YIE`` is already ingested and reaches
    # the rates domain as a ``decomposition_component``, which this rule must not and
    # does not read.  Kept rather than deleted because the design separates survey
    # expectations from market compensation deliberately, and the rule is where that
    # separation is enforced once both are present.
    market = [
        factor for factor in factors if factor.causal_role == "expectations_market"
    ]
    if (
        direction == "FALLING"
        and survey is not None
        and survey.change_over_window is not None
        and survey.change_over_window >= parameters.expectations_divergence_pp
        and market
        and all(
            factor.change_over_window is not None
            and factor.change_over_window >= parameters.expectations_divergence_pp
            for factor in market
        )
    ):
        out.append(
            Contradiction(
                rule="expectations_diverge_from_realized",
                detail=(
                    f"realized falling {_pp(core_change)} while survey rose "
                    f"{_pp(survey.change_over_window)} and market compensation rose"
                ),
            )
        )
    return tuple(out)


def _opposed(left: Decimal, right: Decimal) -> bool:
    return (left > 0 > right) or (left < 0 < right)


def _pp(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}pp"


def _velocity(
    basis: Mapping[date, Decimal],
    basis_period: date | None,
    window: int,
    *,
    period_absent: bool,
) -> tuple[Velocity, ...]:
    if period_absent or basis_period is None:
        absent = "core PCE observation for the required period is absent at as_of"
        return (
            Velocity("core_pce_yoy_change_3m", None, "pp", window, absent),
            Velocity(
                "core_pce_3m_annualized", None, "percent_annual_rate", window, absent
            ),
        )
    change = yoy_change_over_months(basis, basis_period, window)
    annualized = annualized_over_months(basis, basis_period, window)
    gap = f"no core PCE observation {window} calendar months before {basis_period}"
    return (
        Velocity(
            "core_pce_yoy_change_3m",
            change,
            "pp",
            window,
            None if change is not None else gap,
        ),
        Velocity(
            "core_pce_3m_annualized",
            annualized,
            "percent_annual_rate",
            window,
            None if annualized is not None else gap,
        ),
    )
