"""The gold domain state: whether the relationship Lens 2 rests on is in force.

Gold keeps its three lenses and this module does not change what they say.  What it adds
is the one fact belonging to no single lens -- **the gate**: is the gold/real-yield
relationship the cyclical lens rests on currently holding?  Spec 3.1, verbatim: "The gate
is the domain's state."

The measurement already exists.  ``cards/regime_gauge.py`` computes rolling correlations
between the gold price and the 10-year real yield and publishes ``operative`` / ``partial``
/ ``suspended``.  This module gives that verdict a point-in-time identity, an upstream
lineage, per-lens sub-states and a confidence.  It does not recompute it.

**An unrecognised gauge label maps to UNKNOWN, never to OPERATIVE.**  Defaulting there
would assert the pre-2022 relationship holds, which is the single claim the gate exists to
withhold.

**Gold READS upstream-owned series; it does not OWN them.**  Lens 2 is defined on the real
yield and the broad dollar, so refusing them -- the way USD refuses ``EFFR`` -- would not
protect an invariant, it would delete the lens.  The double-count prohibition is "one
publisher payload, one owner, many readers", and pointing at the same ``obs_id`` the rates
state points at IS the many-readers case.  What gold must never do is re-derive the
upstream's CONCLUSION, which is why ``required_series`` for the confidence denominator is
gold-owned only: a borrowed series going quiet degrades a lens, it does not make gold less
sure of its own gate.

Contradictions report that evidence disagrees.  They never resolve into a direction and
never change a state label (spec 4), and there is deliberately no precedence rule between
Lens 1 and Lens 2 -- collapsing them would throw away the only information the
disagreement carries.

Design: ``docs/superpowers/specs/2026-08-12-usd-gold-state-design.md`` sections 3, 3.1, 4.
Golden scenarios: ``tests/fixtures/macro/usd_gold_golden.json``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from .confidence import compute_confidence
from .contracts import (
    ConfidenceTerm,
    Contradiction,
    Direction,
    DomainObservation,
    EvidenceRef,
    FactorState,
    MacroDomainState,
    MacroSubState,
    Velocity,
    compute_inputs_hash,
    freshness_for,
)
from .evidence_store import INFLATION_EVIDENCE, RATES_EVIDENCE, USD_EVIDENCE
from .usd import UpstreamState

GOLD_ENGINE_VERSION = "gold/1"

#: The gate's vocabulary IS the gauge's, uppercased.  Inventing a second set of words for
#: the same measurement would leave two vocabularies to keep in step, and the one that
#: drifted would be the one nobody reads.
GoldStateLabel = Literal["OPERATIVE", "PARTIAL", "SUSPENDED", "UNKNOWN"]

#: Gold decoupled from real yields after 2022.  A Lens 2 fitted across the break averages
#: a negative relationship with a broken one and describes neither side, so the break is a
#: calendar fact this engine gates on -- distinct from ``gauge_state``, which is the
#: MEASURED correlation.  Both are load-bearing and they are not the same thing.
REGIME_BREAK_YEAR = 2022

#: Gold's own anchor.  REQUIRED: with it absent the state abstains.
ANCHOR_SERIES = "GLD_CLOSE"
#: Lens 1's flow leg, gold-owned.  Counted in ounces, so a rise is real accumulation into
#: the trust rather than a price effect.
FLOW_SERIES = "GLD_HOLDINGS_OZ"
#: Lens 2's two legs, both BORROWED from upstream domains.
REAL_YIELD_SERIES = "DFII10"
DOLLAR_SERIES = "DTWEXBGS"

_GAUGE_TO_STATE: dict[str, GoldStateLabel] = {
    "operative": "OPERATIVE",
    "partial": "PARTIAL",
    "suspended": "SUSPENDED",
}


def _series_owner_map() -> dict[str, str]:
    """Which domain owns each series, DERIVED from the evidence contracts.

    Derived rather than restated so widening ``RATES_EVIDENCE`` re-tags gold's borrowed
    rows on the same commit.  A hand-maintained copy would keep calling a series gold-owned
    after somebody else claimed it, and the confidence denominator would silently start
    counting a series gold does not own.
    """
    out: dict[str, str] = {}
    for domain, contracts in (
        ("inflation", INFLATION_EVIDENCE),
        ("policy_rates", RATES_EVIDENCE),
        ("usd", USD_EVIDENCE),
    ):
        for contract in contracts:
            out.setdefault(contract.series_id, domain)
    return out


SERIES_OWNER: dict[str, str] = _series_owner_map()

#: Everything gold owns outright.  The confidence denominator is drawn from here alone.
GOLD_OWNED_SERIES: tuple[str, ...] = (ANCHOR_SERIES, FLOW_SERIES)

#: Per-lens vocabularies. Deliberately three separate Literals and not one shared enum:
#: STRONG is about tonnage into a trust and ADVERSE is about a macro backdrop, and a
#: common type would invite exactly the cross-lens comparison the no-precedence rule
#: exists to refuse. Every one includes UNKNOWN and none includes NEUTRAL-as-absence.
GoldFlowLabel = Literal["STRONG", "NEUTRAL", "WEAK", "UNKNOWN"]
GoldCyclicalLabel = Literal["SUPPORTIVE", "ADVERSE", "MIXED", "SUSPENDED", "UNKNOWN"]
GoldValuationLabel = Literal["FAVORABLE", "NEUTRAL", "STRETCHED", "UNKNOWN"]


@dataclass(frozen=True)
class GoldLensResult:
    """The persisted deterministic gauge this state reads, and nothing more.

    Built from a stored ``gold_posture_daily`` row by the job, never recomputed here and
    never fetched from a provider.  Carrying the row's own ``obs_date`` rather than
    inheriting the state's ``as_of`` is the point: the orchestrator runs on its own
    schedule, and a state that assumed the two instants matched would report a stale gauge
    as current.
    """

    obs_date: date | None
    gauge_state: str | None
    corr_252d_level: Decimal | None = None
    corr_60d_level: Decimal | None = None
    #: Lens 3's flag, carried through as a sub-state.  A warning, never a size.
    valuation_flag: str | None = None


@dataclass(frozen=True)
class GoldParameters:
    """Versioned thresholds, hashed with the evidence rather than hidden in constants."""

    version: str = "gold/1"
    #: CALENDAR days, not observation counts, and that distinction is load-bearing.
    #: This engine reads four series off three publication calendars -- GLD trades NYSE
    #: sessions, FRED skips its own holidays, SPDR posts business days -- and over one
    #: quarter of the golden fixture ``GLD_CLOSE`` has 64 prints where ``DFII10`` has 62.
    #: A window of "63 observations" is therefore a different span on every series, and
    #: on the shorter one it silently returns None and mutes the contradiction the window
    #: exists to detect. Anchoring on the calendar makes the legs comparable.
    #:
    #: 63 days -- nine weeks -- is set by the golden fixture rather than chosen. Measured
    #: across its two preregistered scenarios: at 91 days the real-yield leg INVERTS
    #: (2024-07-24 2.00 -> 2024-10-23 1.93, -7bp) and the dollar leg falls inside its
    #: threshold, so the preregistered ADVERSE reading reads UNKNOWN; and the ETF flow
    #: series carries only 65 days of history, so nothing longer is measurable at all.
    #: The admissible band is roughly 45-65 days and 63 sits inside it rather than on its
    #: edge. One window for all four series: the fixture gives no reason for two, and a
    #: second parameter nothing distinguishes is the one that silently becomes wrong.
    window_days: int = 63
    momentum_threshold_pct: Decimal = Decimal("5.0")
    #: Percent change in ounces held at which accumulation is STRONG rather than drift.
    flow_strong_pct: Decimal = Decimal("2.0")
    #: Lens 2's legs. A real yield move in basis points and a dollar move in percent --
    #: two units, two thresholds, never one number applied to both.
    real_yield_move_bps: Decimal = Decimal("10")
    dollar_move_pct: Decimal = Decimal("1.0")
    contradiction_penalty_each: Decimal = Decimal("0.15")
    contradiction_penalty_cap: Decimal = Decimal("0.60")
    freshness_decay_multiple: Decimal = Decimal("3")
    anchor_cadence_days: int = 1
    #: SPDR publishes holdings each business day.
    flow_cadence_days: int = 1

    def as_record(self) -> dict[str, Any]:
        return {
            key: (format(value, "f") if isinstance(value, Decimal) else value)
            for key, value in sorted(asdict(self).items())
        }


DEFAULT_GOLD_PARAMETERS = GoldParameters()


def compute_gold_state(
    observations: Iterable[DomainObservation],
    *,
    as_of: datetime,
    lens: GoldLensResult | None = None,
    upstream: Sequence[UpstreamState] = (),
    parameters: GoldParameters = DEFAULT_GOLD_PARAMETERS,
    prior_state: MacroDomainState | None = None,
) -> MacroDomainState:
    """Assemble the gold gate, its three lens sub-states, and their disagreements."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    _refuse_future_upstream(upstream, as_of)

    eligible = tuple(
        sorted(
            (obs for obs in observations if obs.is_known_on(as_of)),
            key=lambda obs: (obs.series_id, obs.period_end, obs.available_at),
        )
    )
    price = _rows(eligible, ANCHOR_SERIES)
    flow = _rows(eligible, FLOW_SERIES)
    real_yield = _rows(eligible, REAL_YIELD_SERIES)
    dollar = _rows(eligible, DOLLAR_SERIES)

    # The confidence denominator counts what gold OWNS.  A borrowed series going quiet
    # degrades the lens that reads it -- reported in that sub-state's own confidence --
    # and does not make gold less certain about its own gate.
    factors = tuple(
        factor
        for factor in (
            _factor(
                price, "gold_price", as_of, parameters.anchor_cadence_days, parameters
            ),
            _factor(
                flow, "gld_holdings", as_of, parameters.flow_cadence_days, parameters
            ),
        )
        if factor is not None
    )

    state = _state(lens)
    price_change = _change_pct(price, parameters.window_days)
    direction = _direction(price_change, parameters)

    sub_states = (
        _flow_sub_state(flow, as_of, parameters),
        _cyclical_sub_state(real_yield, dollar, state, as_of, parameters),
        _valuation_sub_state(lens),
    )
    contradictions = _contradictions(
        price=price,
        real_yield=real_yield,
        sub_states=sub_states,
        as_of=as_of,
        parameters=parameters,
    )

    confidence, reasons = compute_confidence(
        factors,
        required_series=(ANCHOR_SERIES,),
        contradictions=contradictions,
        contradiction_penalty_each=parameters.contradiction_penalty_each,
        contradiction_penalty_cap=parameters.contradiction_penalty_cap,
        prior_state=prior_state,
        absent_reason=_absent_reason(price, lens),
    )
    reasons = (
        reasons
        + _anchor_period_note(price, as_of)
        + _lens_note(lens, as_of)
        + _borrowed_note(eligible)
        + _upstream_note(upstream)
    )

    return MacroDomainState(
        domain="gold",
        state=state,
        direction=direction,
        velocity=_velocity(price_change, lens, parameters),
        confidence=confidence,
        confidence_reasons=reasons,
        contradictions=contradictions,
        factors=factors,
        # Every row the state stood on, borrowed rows included, each pointing at the ONE
        # stored observation its owner also points at.  That shared obs_id is the
        # many-readers mechanism, not a second copy.
        evidence_refs=tuple(
            EvidenceRef(
                series_id=obs.series_id,
                period_end=obs.period_end,
                causal_role=obs.causal_role,
                available_at=obs.available_at,
                obs_id=obs.obs_id,
                artifact_id=obs.artifact_id,
            )
            for obs in eligible
        ),
        engine_version=GOLD_ENGINE_VERSION,
        inputs_hash=compute_inputs_hash(
            engine_version=GOLD_ENGINE_VERSION,
            parameters={
                **parameters.as_record(),
                # The gauge is an input, so it is hashed: an orchestrator that re-ran and
                # changed its mind must change this identity even when every observation
                # is byte-identical.
                "lens": (
                    None
                    if lens is None
                    else f"{lens.obs_date}:{lens.gauge_state}:{lens.corr_252d_level}"
                ),
                "upstream": sorted(
                    f"{item.domain}:{item.inputs_hash}" for item in upstream
                ),
            },
            observations=eligible,
        ),
        as_of=as_of,
        sub_states=sub_states,
        notes=(
            "the domain state is the GATE -- whether the gold/real-yield relationship "
            "Lens 2 rests on is in force -- and not a view on gold. the three lenses "
            "publish beside it as sub-states with their own confidence, and there is no "
            "precedence rule between them",
            "the valuation lens is a warning: it never becomes a price target, an "
            "allocation, or a size",
        ),
    )


# --------------------------------------------------------------------------- the gate


def _state(lens: GoldLensResult | None) -> GoldStateLabel:
    """The gauge verdict, with every unrecognised label falling to UNKNOWN.

    Spec 3.1: an unrecognised gauge label maps to UNKNOWN, never to ``operative``.
    Raising instead would be defensible for a typo and wrong for the case that matters --
    a gauge that grows a fourth label mid-deploy would take the state job down rather than
    reporting that it no longer understands the gate.
    """
    if lens is None or lens.gauge_state is None:
        return "UNKNOWN"
    return _GAUGE_TO_STATE.get(lens.gauge_state, "UNKNOWN")


# ------------------------------------------------------------------------- sub-states
#
# The three lenses publish BESIDE the gate, each with its own coverage (spec 3.1). Their
# own coverage is the point: Part A's R2 says a domain's confidence may never stand in
# for a sub-state's, and the inverse holds too -- the gate can be certain while Lens 2
# has no legs to read, and Lens 1 can be fully covered while the gate reads UNKNOWN.


def _flow_sub_state(
    flow: Sequence[DomainObservation], as_of: datetime, parameters: GoldParameters
) -> MacroSubState:
    """Lens 1 -- structural flow, read off ETF tonnage in ounces.

    Ounces, not dollars: holdings counted in ounces rise only when metal actually enters
    the trust, so a rally cannot masquerade as accumulation.
    """
    change = _change_pct(flow, parameters.window_days)
    label: GoldFlowLabel
    if change is None:
        label = "UNKNOWN"
    elif change >= parameters.flow_strong_pct:
        label = "STRONG"
    elif change <= -parameters.flow_strong_pct:
        label = "WEAK"
    else:
        label = "NEUTRAL"
    return MacroSubState(
        role="positioning",
        state=label,
        direction=_sign_direction(change, parameters.flow_strong_pct),
        velocity=(
            Velocity(
                metric="gld_holdings_change",
                value=change,
                unit="percent",
                window_months=2,
                unavailable_reason=(
                    None
                    if change is not None
                    else (
                        f"{FLOW_SERIES} history does not reach "
                        f"{parameters.window_days} calendar days before its latest print"
                    )
                ),
            ),
        ),
        confidence=_coverage_confidence(
            flow, as_of, parameters.flow_cadence_days, parameters
        ),
        confidence_reasons=(),
        series_ids=(FLOW_SERIES,),
        latest_period_end=flow[-1].period_end if flow else None,
        unavailable_reason=(
            None if flow else f"no {FLOW_SERIES} observation available at as_of"
        ),
    )


def _cyclical_sub_state(
    real_yield: Sequence[DomainObservation],
    dollar: Sequence[DomainObservation],
    gate: GoldStateLabel,
    as_of: datetime,
    parameters: GoldParameters,
) -> MacroSubState:
    """Lens 2 -- the regime-gated cyclical read, on two BORROWED legs.

    Gated on the gate: with the relationship measured suspended, a cyclical reading drawn
    from it describes a correlation that is not currently holding. Reporting SUSPENDED is
    not degradation, it is the honest answer.
    """
    if gate == "SUSPENDED":
        return MacroSubState(
            role="decomposition_component",
            state="SUSPENDED",
            direction="UNKNOWN",
            velocity=(),
            confidence=Decimal(0),
            confidence_reasons=(),
            series_ids=(REAL_YIELD_SERIES, DOLLAR_SERIES),
            latest_period_end=real_yield[-1].period_end if real_yield else None,
            unavailable_reason=(
                "the gold/real-yield relationship reads suspended at as_of, so a "
                "cyclical view drawn from it would describe a correlation that is not "
                "currently in force"
            ),
        )

    yield_move = _change_abs(real_yield, parameters.window_days)
    dollar_move = _change_pct(dollar, parameters.window_days)
    # Adverse for gold: a higher real yield raises the carrying cost of a zero-coupon
    # asset, and a stronger dollar lowers the price of a dollar-denominated one.
    legs = [
        _leg_adverse(yield_move, parameters.real_yield_move_bps / Decimal(100)),
        _leg_adverse(dollar_move, parameters.dollar_move_pct),
    ]
    known = [leg for leg in legs if leg is not None]
    label: GoldCyclicalLabel
    if not known:
        label = "UNKNOWN"
    elif all(leg is True for leg in known):
        label = "ADVERSE"
    elif all(leg is False for leg in known):
        label = "SUPPORTIVE"
    else:
        label = "MIXED"
    return MacroSubState(
        role="decomposition_component",
        state=label,
        # Deliberately UNKNOWN and never derived from the legs. The golden scenario
        # preregisters ``lens2_direction_inferred: null``: an adverse backdrop is a
        # statement about the environment, not a forecast of which way gold goes.
        direction="UNKNOWN",
        velocity=(
            Velocity(
                metric="real_yield_change",
                value=yield_move,
                unit="percent",
                window_months=2,
                unavailable_reason=(
                    None if yield_move is not None else f"no {REAL_YIELD_SERIES} window"
                ),
            ),
            Velocity(
                metric="broad_dollar_change",
                value=dollar_move,
                unit="percent",
                window_months=2,
                unavailable_reason=(
                    None if dollar_move is not None else f"no {DOLLAR_SERIES} window"
                ),
            ),
        ),
        confidence=_coverage_confidence(real_yield, as_of, 1, parameters),
        confidence_reasons=(),
        series_ids=(REAL_YIELD_SERIES, DOLLAR_SERIES),
        latest_period_end=real_yield[-1].period_end if real_yield else None,
        unavailable_reason=(
            None
            if known
            else "neither cyclical leg had enough history at as_of to measure a move"
        ),
    )


def _valuation_sub_state(lens: GoldLensResult | None) -> MacroSubState:
    """Lens 3 -- the valuation overlay. A warning, never a size."""
    flag = None if lens is None else lens.valuation_flag
    label: GoldValuationLabel
    if flag in {"High", "Severe"}:
        label = "STRETCHED"
    elif flag == "Moderate":
        label = "NEUTRAL"
    elif flag == "Low":
        label = "FAVORABLE"
    else:
        label = "UNKNOWN"
    return MacroSubState(
        role="realized",
        state=label,
        direction="UNKNOWN",
        velocity=(),
        confidence=Decimal(1) if label != "UNKNOWN" else Decimal(0),
        confidence_reasons=(
            ConfidenceTerm(
                term="valuation_is_a_warning",
                value=Decimal(0),
                detail=(
                    "long-run anchors say where the price sits in its own history; they "
                    "never become a price target, an allocation or a size"
                ),
                kind="informational",
            ),
        ),
        series_ids=(),
        latest_period_end=None if lens is None else lens.obs_date,
        unavailable_reason=(
            None if label != "UNKNOWN" else "no stored valuation flag at as_of"
        ),
    )


# ---------------------------------------------------------------------- contradictions


def _contradictions(
    *,
    price: Sequence[DomainObservation],
    real_yield: Sequence[DomainObservation],
    sub_states: Sequence[MacroSubState],
    as_of: datetime,
    parameters: GoldParameters,
) -> tuple[Contradiction, ...]:
    """Spec 4's two gold rules. Neither resolves into a direction or moves a label."""
    out: list[Contradiction] = []

    gold_move = _change_pct(price, parameters.window_days)
    yield_move = _change_abs(real_yield, parameters.window_days)
    # The WINDOW's start year, not ``as_of``'s. A window straddling the break is exactly
    # what the gate exists to refuse -- calling it post-2022 because the run happened in
    # January would let one leg of the comparison come from the regime the other says no
    # longer applies.
    window = _endpoints(price, parameters.window_days)
    window_starts_post_break = (
        window is not None and window[0].period_end.year >= REGIME_BREAK_YEAR
    )
    if (
        window_starts_post_break
        and gold_move is not None
        and yield_move is not None
        and gold_move != 0
        and yield_move != 0
        and (gold_move > 0) == (yield_move > 0)
    ):
        out.append(
            Contradiction(
                rule="gold_against_real_yields_post_2022",
                detail=(
                    f"gold {gold_move:+.2f}% and the 10y real yield {yield_move:+.2f}pp "
                    "moved together over the same window; the pre-2022 relationship is "
                    "that they oppose, because a higher real rate is a higher carrying "
                    "cost for a zero-coupon asset. reported, not resolved -- the gate "
                    "exists so a Lens 2 fitted across the break cannot average a "
                    "negative relationship with a broken one and describe neither"
                ),
            )
        )

    flow = next((s for s in sub_states if s.role == "positioning"), None)
    cyclical = next(
        (s for s in sub_states if s.role == "decomposition_component"), None
    )
    if flow is not None and cyclical is not None:
        if flow.state == "STRONG" and cyclical.state == "ADVERSE":
            out.append(
                Contradiction(
                    rule="gold_flow_against_cyclical",
                    detail=(
                        "structural flows read STRONG while the cyclical backdrop reads "
                        "ADVERSE. both are reported as findings and neither overwrites "
                        "the other: there is no precedence rule, because collapsing them "
                        "would throw away the only information the disagreement carries"
                    ),
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------- helpers


def _rows(
    observations: Sequence[DomainObservation], series_id: str
) -> tuple[DomainObservation, ...]:
    """This series' point-in-time view: one row per period, newest vintage, oldest first.

    ``is_known_on`` already drops vintages superseded before ``as_of``, but it cannot drop
    one whose replacement is still in the future -- both are legitimately "known", and the
    fixture's broad-dollar series carries two vintages for all 205 of its periods. Keeping
    both would put the same period into the window twice and let a restatement land at an
    endpoint, so the newest vintage in force wins per period.
    """
    by_period: dict[date, DomainObservation] = {}
    for obs in observations:
        if obs.series_id != series_id:
            continue
        held = by_period.get(obs.period_end)
        if held is None or obs.available_at >= held.available_at:
            by_period[obs.period_end] = obs
    return tuple(by_period[period] for period in sorted(by_period))


def _endpoints(
    rows: Sequence[DomainObservation], window_days: int
) -> tuple[DomainObservation, DomainObservation] | None:
    """The newest row and the newest row at least ``window_days`` before it.

    None when the history does not reach back that far, rather than a change measured
    over whatever happened to exist: a three-week move reported under a quarterly label
    is a different statistic wearing the same name.
    """
    if not rows:
        return None
    latest = rows[-1]
    cutoff = latest.period_end - timedelta(days=window_days)
    earlier = [row for row in rows if row.period_end <= cutoff]
    if not earlier:
        return None
    return earlier[-1], latest


def _change_pct(rows: Sequence[DomainObservation], window_days: int) -> Decimal | None:
    """Percent change over the calendar window, or None if history is short."""
    pair = _endpoints(rows, window_days)
    if pair is None:
        return None
    start, end = pair
    if start.value == 0:
        return None
    return (end.value - start.value) / start.value * Decimal(100)


def _change_abs(rows: Sequence[DomainObservation], window_days: int) -> Decimal | None:
    """Absolute change, for a series already quoted in percent.

    A yield's percent CHANGE is meaningless -- 1.77 to 1.93 is "+9%" and nobody in rates
    says that. The move is 16 basis points, and that is what the threshold is stated in.
    """
    pair = _endpoints(rows, window_days)
    if pair is None:
        return None
    start, end = pair
    return end.value - start.value


def _leg_adverse(move: Decimal | None, threshold: Decimal) -> bool | None:
    """True if this leg is adverse for gold, False if supportive, None if unreadable.

    A move inside the threshold is NOT adverse and not supportive -- returning False for
    it would let two quiet legs read SUPPORTIVE, which is absence rendered as a view.
    """
    if move is None:
        return None
    if move >= threshold:
        return True
    if move <= -threshold:
        return False
    return None


def _factor(
    rows: Sequence[DomainObservation],
    name: str,
    as_of: datetime,
    cadence_days: int,
    parameters: GoldParameters,
) -> FactorState | None:
    if not rows:
        return None
    latest = rows[-1]
    age_days = max(0, (as_of - latest.available_at).days)
    change = _change_pct(rows, parameters.window_days)
    return FactorState(
        name=name,
        causal_role=latest.causal_role,
        series_id=latest.series_id,
        period_end=latest.period_end,
        value=latest.value,
        unit=latest.unit,
        direction=_sign_direction(change, parameters.momentum_threshold_pct),
        change_over_window=change,
        available_at=latest.available_at,
        age_days=age_days,
        freshness=freshness_for(
            age_days, cadence_days, parameters.freshness_decay_multiple
        ),
        quality_status=latest.quality_status,
        source=latest.source,
        source_kind=latest.source_kind,
    )


def _coverage_confidence(
    rows: Sequence[DomainObservation],
    as_of: datetime,
    cadence_days: int,
    parameters: GoldParameters,
) -> Decimal:
    """A sub-state's own confidence: does its series exist and is it on schedule.

    Its OWN, per spec 3.1 and Part A's R2 -- the domain's gate confidence never stands in
    for a lens's coverage, and a lens's coverage never stands in for the gate's.
    """
    if not rows:
        return Decimal(0)
    age_days = max(0, (as_of - rows[-1].available_at).days)
    return freshness_for(age_days, cadence_days, parameters.freshness_decay_multiple)


def _direction(change: Decimal | None, parameters: GoldParameters) -> Direction:
    return _sign_direction(change, parameters.momentum_threshold_pct)


def _sign_direction(change: Decimal | None, threshold: Decimal) -> Direction:
    if change is None:
        return "UNKNOWN"
    if change >= threshold:
        return "RISING"
    if change <= -threshold:
        return "FALLING"
    return "FLAT"


def _velocity(
    price_change: Decimal | None,
    lens: GoldLensResult | None,
    parameters: GoldParameters,
) -> tuple[Velocity, ...]:
    corr = None if lens is None else lens.corr_252d_level
    return (
        Velocity(
            metric="gold_price_change",
            value=price_change,
            unit="percent",
            window_months=3,
            unavailable_reason=(
                None
                if price_change is not None
                else (
                    f"{ANCHOR_SERIES} history does not reach "
                    f"{parameters.window_days} calendar days before its latest print"
                )
            ),
        ),
        Velocity(
            metric="gold_real_yield_corr_252d",
            value=corr,
            unit="correlation",
            window_months=12,
            unavailable_reason=(
                None if corr is not None else "no gauge correlation stored at as_of"
            ),
        ),
    )


def _absent_reason(
    price: Sequence[DomainObservation], lens: GoldLensResult | None
) -> str | None:
    if not price:
        return (
            f"no {ANCHOR_SERIES} observation available at as_of; the state abstains "
            "rather than reporting a gate with no gold price under it"
        )
    if lens is None or lens.gauge_state is None:
        return (
            "no stored gauge verdict at as_of, so the gate reads UNKNOWN; defaulting it "
            "to operative would assert the pre-2022 relationship holds, which is the "
            "one claim the gate exists to withhold"
        )
    return None


def _anchor_period_note(
    price: Sequence[DomainObservation], as_of: datetime
) -> tuple[ConfidenceTerm, ...]:
    """How old the newest gold PRICE is, which freshness deliberately does not measure.

    ``freshness_for`` reads ``available_at`` -- when we learned a value -- and that is the
    right denominator for detecting a publisher that has gone quiet. It is the wrong one
    for answering "is this price current", and the two come apart hard on this lane: a
    backfill stamps 400 days of history with today's retrieval clock, so every one of
    those prints reads perfectly fresh while the newest is over a year old.

    Reported as its own informational term rather than folded into the confidence, for
    the same reason the rest of them are: a number that silently absorbed two different
    kinds of staleness could not be argued with.
    """
    if not price:
        return ()
    age_days = max(0, (as_of.date() - price[-1].period_end).days)
    return (
        ConfidenceTerm(
            term="anchor_period_age_days",
            value=Decimal(age_days),
            detail=(
                f"the newest {ANCHOR_SERIES} print is for {price[-1].period_end} "
                f"({age_days}d before as_of). freshness measures when we LEARNED a "
                "value, not how old the value is, so a backfilled history reads fresh "
                "and this term is the only thing that says otherwise"
            ),
            kind="informational",
        ),
    )


def _lens_note(
    lens: GoldLensResult | None, as_of: datetime
) -> tuple[ConfidenceTerm, ...]:
    """The gauge's own age, which is not the price's age.

    The orchestrator runs nightly on its own schedule. A state computed the morning after
    a failed orchestrator run stands on a two-day-old gauge, and nothing else in
    ``confidence_reasons`` would say so -- the price factor would be fresh.
    """
    if lens is None or lens.obs_date is None:
        return ()
    age_days = max(0, (as_of.date() - lens.obs_date).days)
    return (
        ConfidenceTerm(
            term="gauge_age_days",
            value=Decimal(age_days),
            detail=(
                f"the gauge this gate reads was computed for {lens.obs_date} "
                f"({age_days}d before as_of); the orchestrator runs on its own schedule "
                "and its age is not the gold price's age"
            ),
            kind="informational",
        ),
    )


def _borrowed_note(
    observations: Sequence[DomainObservation],
) -> tuple[ConfidenceTerm, ...]:
    """Name the rows gold READ but does not OWN, so the lineage is legible.

    Without this the evidence list looks like sixteen gold-owned series. The distinction
    is what keeps ``required_series`` honest: a borrowed series going quiet degrades the
    lens that reads it, and must never move the gate's own confidence.
    """
    borrowed = sorted(
        {
            f"{obs.series_id}({SERIES_OWNER[obs.series_id]})"
            for obs in observations
            if obs.series_id in SERIES_OWNER
        }
    )
    if not borrowed:
        return ()
    return (
        ConfidenceTerm(
            term="borrowed_evidence",
            value=Decimal(len(borrowed)),
            detail=(
                f"read but not owned: {', '.join(borrowed)}. these point at the same "
                "stored observations their owning domain points at -- one payload, one "
                "owner, many readers -- and are excluded from this state's required "
                "series so a quiet upstream degrades a lens, not the gate"
            ),
            kind="informational",
        ),
    )


def _upstream_note(
    upstream: Sequence[UpstreamState],
) -> tuple[ConfidenceTerm, ...]:
    if not upstream:
        return ()
    named = ", ".join(
        f"{item.domain}={item.state}/{item.direction}"
        for item in sorted(upstream, key=lambda item: item.domain)
    )
    return (
        ConfidenceTerm(
            term="upstream_consumed",
            value=Decimal(len(upstream)),
            detail=f"consumed {len(upstream)} upstream state(s) by state id: {named}",
            kind="informational",
        ),
    )


def _refuse_future_upstream(upstream: Sequence[UpstreamState], as_of: datetime) -> None:
    """An upstream answering for a later instant could not have been known."""
    domains = [item.domain for item in upstream]
    duplicated = sorted({d for d in domains if domains.count(d) > 1})
    if duplicated:
        raise ValueError(
            f"upstream lists {duplicated} more than once; a domain has one answer per "
            "as_of, and picking the first would make the result depend on argument order"
        )
    ahead = [item for item in upstream if item.as_of > as_of]
    if ahead:
        named = ", ".join(
            f"{item.domain}@{item.as_of.isoformat()}"
            for item in sorted(ahead, key=lambda item: item.domain)
        )
        raise ValueError(
            f"upstream {named} answers for an instant after as_of {as_of.isoformat()}; "
            "consuming it would be lookahead, and the fact that the future answer is "
            "about another domain does not make it knowable"
        )


__all__ = [
    "ANCHOR_SERIES",
    "DOLLAR_SERIES",
    "FLOW_SERIES",
    "GOLD_ENGINE_VERSION",
    "GOLD_OWNED_SERIES",
    "REAL_YIELD_SERIES",
    "REGIME_BREAK_YEAR",
    "SERIES_OWNER",
    "DEFAULT_GOLD_PARAMETERS",
    "GoldLensResult",
    "GoldParameters",
    "compute_gold_state",
]
