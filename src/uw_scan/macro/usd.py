"""Point-in-time USD transmission state.

USD is a **transmission** domain: it does not re-answer what inflation is doing or what
the committee did.  MC2 and Part A answer those, and their answers arrive here as
upstream state ids rather than as re-read series.  The rule, stated once:
**one publisher payload, one owner, many readers.**

Two refusals shape the module.

**The anchor is required, and the real index is not a fallback.**  With no ``DTWEXBGS``
vintage at ``as_of`` the state is ``UNKNOWN``.  ``RTWEXBGS`` is frequently available at
exactly the moments the nominal anchor is not, reports the same units, and answers a
different question -- a nominal index moving while the real one does not is an inflation
differential, and substituting one for the other would report that differential as a
dollar move.  The temptation is real, which is why the refusal is a rule and not a
comment: golden scenario ``usd_anchor_absent_state_abstains`` freezes an ``as_of`` where
the sibling has 59 observations and the anchor has zero.

**Revisions are load-bearing here in a way they are not upstream.**  The Fed restates
this index on 1,265 periods against zero for SOFR, EFFR and RRPONTSYD, so
``compute_confidence``'s revision penalty fires on USD in normal operation.  A USD state
carrying revision drag is correct rather than broken and must not be tuned away.

Design: ``docs/superpowers/specs/2026-08-12-usd-gold-state-design.md``.
Sources: ``docs/research/2026-08-12-usd-source-probe/VERDICT.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from .confidence import compute_confidence
from .contracts import (
    CausalRole,
    ConfidenceTerm,
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

USD_ENGINE_VERSION = "usd/1"

UsdStateLabel = Literal["STRENGTHENING", "WEAKENING", "RANGEBOUND", "UNKNOWN"]

#: The nominal broad dollar.  Required: with it absent the state abstains.
ANCHOR_SERIES = "DTWEXBGS"
#: The CPI-deflated sibling.  Reported, never substituted for the anchor.
REAL_SERIES = "RTWEXBGS"

#: Everything USD reads and does not own.  Listed by role rather than by series id
#: because that is how the double-count prohibition is actually stated: USD may consult
#: an upstream role's answer, and may not re-derive it from that role's inputs.
UPSTREAM_ROLES: tuple[CausalRole, ...] = ("policy_actual", "plumbing", "positioning")


@dataclass(frozen=True)
class UpstreamState:
    """One upstream domain's ANSWER, which is all USD is allowed to consume.

    Deliberately carries no observations.  A reference that shipped the upstream rows
    would let USD recompute the upstream conclusion from them and then disagree with it
    silently, which is the failure the state-id indirection exists to prevent.
    """

    domain: str
    state: str
    direction: Direction
    #: The stored state's identity, so a replay can point at what it stood on.
    inputs_hash: str
    as_of: datetime
    confidence: Decimal | None = None


@dataclass(frozen=True)
class UsdParameters:
    """Versioned thresholds, hashed with the evidence rather than hidden in constants."""

    version: str = "usd/1"
    #: Observations, not calendar days.  The H.10 releases weekly carrying the week's
    #: daily values, so 63 observations is about a calendar quarter of prints.
    momentum_window_obs: int = 63
    #: Percent change over that window at which the dollar is doing something.
    #: Calibrated rather than picked: across 5,169 observations from 2006-01-02 to
    #: 2026-08-14 the MEDIAN absolute 63-observation change is 1.81% and this threshold
    #: leaves 53.8% of days RANGEBOUND -- so "rangebound" means the quieter half of the
    #: record by construction, not a number that felt small. p90 is 4.82%.
    #: Reproduce: uv run python scripts/research/usd_source_probe.py
    momentum_threshold_pct: Decimal = Decimal("2.0")
    #: The real index is MONTHLY, so the anchor's 63 observations would be 63 months on
    #: it -- five and a quarter years reported under a label that says three months, and
    #: the two "changes" beside each other would not be comparable at all. Three
    #: observations is the same calendar quarter the anchor's window covers. A window
    #: expressed in observations is only a window once you say whose observations.
    real_momentum_window_obs: int = 3
    contradiction_penalty_each: Decimal = Decimal("0.15")
    contradiction_penalty_cap: Decimal = Decimal("0.60")
    freshness_decay_multiple: Decimal = Decimal("3")
    #: The H.10 goes out WEEKLY carrying the week's daily observations together. A
    #: cadence of 1 -- the obvious reading of a series FRED labels daily -- would mark
    #: the REQUIRED anchor stale Monday through Thursday of an ordinary week, and an
    #: abstaining state is not a degraded reading, it is no reading at all.
    anchor_cadence_days: int = 7
    real_index_cadence_days: int = 31

    def as_record(self) -> dict[str, Any]:
        return {
            key: (format(value, "f") if isinstance(value, Decimal) else value)
            for key, value in sorted(asdict(self).items())
        }


DEFAULT_USD_PARAMETERS = UsdParameters()


@dataclass(frozen=True)
class _SeriesWindow:
    """One series' observations at ``as_of``, newest last."""

    series_id: str
    rows: tuple[DomainObservation, ...] = field(default_factory=tuple)

    @property
    def latest(self) -> DomainObservation | None:
        return self.rows[-1] if self.rows else None

    def change_pct(self, window_obs: int) -> Decimal | None:
        """Percent change from ``window_obs`` observations back, or None if too short.

        None rather than a change measured over whatever history happened to exist: a
        6-observation "quarterly" move is a different statistic wearing the same label.
        """
        if len(self.rows) <= window_obs:
            return None
        start = self.rows[-(window_obs + 1)].value
        if start == 0:
            return None
        return (self.latest.value - start) / start * Decimal(100)


def compute_usd_state(
    observations: Iterable[DomainObservation],
    *,
    as_of: datetime,
    upstream: Sequence[UpstreamState] = (),
    parameters: UsdParameters = DEFAULT_USD_PARAMETERS,
    prior_state: MacroDomainState | None = None,
) -> MacroDomainState:
    """Assemble the USD transmission state from the dollar and upstream answers."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")

    eligible = tuple(
        sorted(
            (obs for obs in observations if obs.is_known_on(as_of)),
            key=lambda obs: (obs.series_id, obs.period_end, obs.available_at),
        )
    )
    owned = tuple(
        obs for obs in eligible if obs.series_id in (ANCHOR_SERIES, REAL_SERIES)
    )
    _refuse_upstream_series(eligible)

    anchor = _window(owned, ANCHOR_SERIES)
    real = _window(owned, REAL_SERIES)
    factors = tuple(
        factor
        for factor in (
            _factor(
                anchor,
                "broad_dollar",
                "curve",
                as_of,
                parameters.anchor_cadence_days,
                parameters,
                parameters.momentum_window_obs,
            ),
            _factor(
                real,
                "broad_dollar_real",
                "decomposition_component",
                as_of,
                parameters.real_index_cadence_days,
                parameters,
                parameters.real_momentum_window_obs,
            ),
        )
        if factor is not None
    )

    momentum = anchor.change_pct(parameters.momentum_window_obs)
    state = _state(momentum, parameters)
    direction = _direction(momentum, parameters)
    contradictions = _contradictions(state, direction, upstream)

    confidence, reasons = compute_confidence(
        factors,
        required_series=(ANCHOR_SERIES,),
        contradictions=contradictions,
        contradiction_penalty_each=parameters.contradiction_penalty_each,
        contradiction_penalty_cap=parameters.contradiction_penalty_cap,
        prior_state=prior_state,
        absent_reason=_absent_reason(anchor, real),
    )
    reasons = reasons + _substitution_note(anchor, real) + _upstream_notes(upstream)

    return MacroDomainState(
        domain="usd",
        state=state,
        direction=direction,
        velocity=_velocity(anchor, real, parameters),
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
            for obs in owned
        ),
        engine_version=USD_ENGINE_VERSION,
        inputs_hash=compute_inputs_hash(
            engine_version=USD_ENGINE_VERSION,
            parameters={
                **parameters.as_record(),
                # The upstream states are inputs, so they are hashed. By identity, not
                # by value: a rates state that changed its mind must change this hash
                # even when every dollar observation is identical.
                "upstream": sorted(
                    f"{item.domain}:{item.inputs_hash}" for item in upstream
                ),
            },
            observations=owned,
        ),
        as_of=as_of,
        notes=(
            "the dollar is measured against the Fed's H.10 nominal broad index; the "
            "real index is reported beside it and is never substituted for it",
        ),
    )


def _refuse_upstream_series(observations: Sequence[DomainObservation]) -> None:
    """Fail loudly if an upstream-owned row was passed in as USD evidence.

    The prohibition is easy to violate by accident: ``load_domain_observations`` will
    happily return EFFR rows if somebody widens ``USD_EVIDENCE``, and the state would
    then read fine while quietly owning a second copy of the rates domain's inputs.
    Raising here makes that a failed test rather than a slow divergence.
    """
    intruders = sorted(
        {obs.series_id for obs in observations if obs.causal_role in UPSTREAM_ROLES}
    )
    if intruders:
        raise ValueError(
            f"{intruders} carry upstream causal roles and were passed to the USD "
            "engine as evidence. USD consumes upstream ANSWERS through UpstreamState, "
            "never their inputs -- see the double-count prohibition in the design spec."
        )


def _window(observations: Sequence[DomainObservation], series_id: str) -> _SeriesWindow:
    return _SeriesWindow(
        series_id=series_id,
        rows=tuple(obs for obs in observations if obs.series_id == series_id),
    )


def _factor(
    window: _SeriesWindow,
    name: str,
    role: CausalRole,
    as_of: datetime,
    cadence_days: int,
    parameters: UsdParameters,
    window_obs: int,
) -> FactorState | None:
    latest = window.latest
    if latest is None:
        return None
    age_days = max((as_of - latest.available_at).days, 0)
    return FactorState(
        name=name,
        causal_role=role,
        series_id=window.series_id,
        period_end=latest.period_end,
        value=latest.value,
        unit=latest.unit,
        direction=_direction(window.change_pct(window_obs), parameters),
        change_over_window=window.change_pct(window_obs),
        available_at=latest.available_at,
        age_days=age_days,
        freshness=freshness_for(
            age_days, cadence_days, parameters.freshness_decay_multiple
        ),
        quality_status=latest.quality_status,
        source=latest.source,
        source_kind=latest.source_kind,
    )


def _state(momentum: Decimal | None, parameters: UsdParameters) -> UsdStateLabel:
    if momentum is None:
        return "UNKNOWN"
    if momentum >= parameters.momentum_threshold_pct:
        return "STRENGTHENING"
    if momentum <= -parameters.momentum_threshold_pct:
        return "WEAKENING"
    return "RANGEBOUND"


def _direction(momentum: Decimal | None, parameters: UsdParameters) -> Direction:
    if momentum is None:
        return "UNKNOWN"
    if momentum >= parameters.momentum_threshold_pct:
        return "RISING"
    if momentum <= -parameters.momentum_threshold_pct:
        return "FALLING"
    return "FLAT"


def _contradictions(
    state: UsdStateLabel,
    direction: Direction,
    upstream: Sequence[UpstreamState],
) -> tuple[Contradiction, ...]:
    """Where the dollar disagrees with what upstream policy implies.

    A contradiction reports that evidence disagrees. It never resolves into a direction
    and never changes a state label -- ``state`` above is already fixed by the time this
    is called, and nothing here feeds back into it.
    """
    rates = next((item for item in upstream if item.domain == "policy_rates"), None)
    if rates is None or state in ("UNKNOWN", "RANGEBOUND"):
        return ()
    # Easing is supposed to weaken a currency and tightening to strengthen it. Only the
    # disagreements are reported; agreement is unremarkable and says nothing.
    implied = {"EASING": "WEAKENING", "TIGHTENING": "STRENGTHENING"}.get(rates.state)
    if implied is None or implied == state:
        return ()
    return (
        Contradiction(
            rule="usd_against_relative_policy",
            detail=(
                f"the dollar is {state} while the policy state is {rates.state}, which "
                f"implies {implied}. NOTE the rule name says 'relative' and only the US "
                "leg is observed: this desk ingests no foreign policy path, so what is "
                "measured is disagreement with US policy alone, not a measured rate "
                "differential. No direction is inferred for either side -- the "
                "disagreement is the whole output."
            ),
        ),
    )


def _velocity(
    anchor: _SeriesWindow, real: _SeriesWindow, parameters: UsdParameters
) -> tuple[Velocity, ...]:
    """Both legs over the same CALENDAR window, which is not the same observation count.

    ``window_months`` is reported per metric and both come out at 3, so the two changes
    sitting beside each other are comparable. Reusing the anchor's 63 observations for a
    monthly series would have measured 63 months and labelled it 3 -- a velocity that is
    wrong by a factor of twenty-one while looking entirely ordinary.
    """
    out = []
    for window, metric, window_obs in (
        (anchor, "broad_dollar_change", parameters.momentum_window_obs),
        (real, "real_dollar_change", parameters.real_momentum_window_obs),
    ):
        change = window.change_pct(window_obs)
        out.append(
            Velocity(
                metric=metric,
                value=change,
                unit="percent",
                window_months=3,
                unavailable_reason=(
                    None
                    if change is not None
                    else f"fewer than {window_obs + 1} observations of "
                    f"{window.series_id} at as_of; a change measured over a shorter "
                    "window is a different statistic under the same label"
                ),
            )
        )
    return tuple(out)


def _absent_reason(anchor: _SeriesWindow, real: _SeriesWindow) -> str | None:
    if anchor.latest is not None:
        return None
    if real.latest is not None:
        return (
            f"no {ANCHOR_SERIES} vintage was available at as_of. {REAL_SERIES} WAS "
            f"available ({len(real.rows)} observations) and was NOT substituted: a "
            "nominal index and a CPI-deflated one answer different questions, and "
            "swapping them would report an inflation differential as a dollar move"
        )
    return (
        f"no {ANCHOR_SERIES} vintage was available at as_of; the USD state abstains "
        "rather than inferring a level from any other index"
    )


def _substitution_note(
    anchor: _SeriesWindow, real: _SeriesWindow
) -> tuple[ConfidenceTerm, ...]:
    """Record the refusal as its own term, even though it costs no confidence.

    An absent anchor already zeroes completeness. This term exists so the reason reads
    as a decision an operator can audit rather than as a coverage gap -- the substitute
    was present and was declined.
    """
    if anchor.latest is not None or real.latest is None:
        return ()
    return (
        ConfidenceTerm(
            term="real_index_not_substituted",
            value=Decimal(len(real.rows)),
            detail=(
                f"{REAL_SERIES} had {len(real.rows)} observations at as_of and was not "
                f"promoted to anchor in place of the absent {ANCHOR_SERIES}"
            ),
            kind="informational",
        ),
    )


def _upstream_notes(upstream: Sequence[UpstreamState]) -> tuple[ConfidenceTerm, ...]:
    """Each upstream answer beside the USD number, never folded into it.

    Informational for the same reason Part A's sub-state terms are: the rates state's
    confidence describes what the committee did, and rendering it inside this domain's
    product would let one stand in for the other.
    """
    return tuple(
        ConfidenceTerm(
            term=f"upstream_{item.domain}",
            value=item.confidence if item.confidence is not None else Decimal(0),
            detail=(
                f"{item.domain} is {item.state} ({item.direction}) as of "
                f"{item.as_of.date().isoformat()}, referenced by state identity "
                f"{item.inputs_hash[:12]} rather than recomputed from its inputs"
            ),
            kind="informational",
        )
        for item in sorted(upstream, key=lambda item: item.domain)
    )
