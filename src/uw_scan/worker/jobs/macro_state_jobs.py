"""Compute and persist point-in-time domain states from evidence already stored.

These jobs make no network call.  Ingestion is a separate job with its own failure mode,
and keeping the two apart is what makes the state reproducible: a state computed tonight
from rows persisted last week can be recomputed byte-for-byte next year, and a provider
outage degrades the *evidence*, never the arithmetic.

Each job reads back the state that preceded it and hands it to the engine, which is how
``load_bearing_input_revised_since_prior_state`` can fire at all: a revision is a changed
value for a period the previous answer already stood on, and nothing but the previous
answer can witness that.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from uw_scan.macro.contracts import DomainObservation, MacroDomainState
from uw_scan.macro.evidence_store import (
    load_usd_observations,
    load_inflation_observations,
    load_rates_observations,
)
from uw_scan.macro.inflation import compute_inflation_state
from uw_scan.macro.policy_report import build_policy_comparison
from uw_scan.macro.rates import compute_rates_state
from uw_scan.macro.usd import UpstreamState, compute_usd_state
from uw_scan.macro.rates_rules import YieldAttribution, attribute_nominal_change
from uw_scan.models.macro import PolicyComparison, PolicyPath
from uw_scan.storage.macro_domain_state import macro_domain_state_from_row
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

#: Window for the nominal-yield attribution.  One month, matching the shortest window
#: over which a real-versus-compensation split says anything: daily moves are dominated
#: by the auction and index-rebalance calendar rather than by macro.
ATTRIBUTION_WINDOW_DAYS = 30

#: How far before the window's start a print may be and still open it.  These series
#: publish every business day, so the only legitimate gaps are holidays -- a week covers
#: the longest of them.  Without a floor the search walks back as far as the loaded
#: history allows and quietly opens a "30-day" move at 45 days: the same number, over a
#: different window, under the same name.  Past the floor the leg is simply unavailable,
#: which the attribution already knows how to say.
ATTRIBUTION_START_TOLERANCE_DAYS = 7


@dataclass(frozen=True)
class MacroStateJobResult:
    domain: str
    #: ``ok`` persisted a state; ``abstained`` means the engine could name no evidence,
    #: so there was nothing a stored state could be reconstructed from; ``failed`` means
    #: the computation itself raised.
    status: str
    as_of: datetime
    state_id: int | None = None
    state: str | None = None
    direction: str | None = None
    confidence: Decimal | None = None
    evidence_count: int = 0
    contradiction_count: int = 0
    error_type: str | None = None
    error_message: str | None = None


def macro_inflation_state_job(
    repo: Repository,
    *,
    as_of: datetime | None = None,
    computed_at: datetime | None = None,
) -> MacroStateJobResult:
    instant = as_of or datetime.now(UTC)
    try:
        observations = load_inflation_observations(repo, as_of=instant)
        state = compute_inflation_state(
            observations,
            as_of=instant,
            prior_state=_prior_state(repo, "inflation", instant),
        )
    except Exception as exc:
        logger.warning("macro inflation state failed: %s", repr(exc))
        return _failed("inflation", instant, exc)
    return _persist(repo, state, computed_at=computed_at or datetime.now(UTC))


def macro_rates_state_job(
    repo: Repository,
    *,
    as_of: datetime | None = None,
    computed_at: datetime | None = None,
) -> MacroStateJobResult:
    instant = as_of or datetime.now(UTC)
    try:
        observations = load_rates_observations(repo, as_of=instant)
        comparison = build_policy_comparison(repo, as_of=instant)
        state = compute_rates_state(
            _paths(comparison),
            as_of=instant,
            observations=observations,
            attribution=_attribution(observations, as_of=instant),
            prior_state=_prior_state(repo, "policy_rates", instant),
        )
    except Exception as exc:
        logger.warning("macro rates state failed: %s", repr(exc))
        return _failed("policy_rates", instant, exc)
    return _persist(repo, state, computed_at=computed_at or datetime.now(UTC))


def macro_usd_state_job(
    repo: Repository,
    *,
    as_of: datetime | None = None,
    computed_at: datetime | None = None,
) -> MacroStateJobResult:
    """The dollar, referencing the stored rates ANSWER rather than its inputs.

    The upstream is looked up from ``macro_domain_states`` rather than recomputed, and
    that is the whole design: recomputing it here would produce a second rates opinion
    that could disagree with the published one while claiming to be it. If no rates state
    has been computed for an instant at or before ``as_of``, USD runs with no upstream --
    the dollar reading is still true, and the contradiction that needs a policy state
    simply does not fire rather than firing against a guess.
    """
    instant = as_of or datetime.now(UTC)
    try:
        observations = load_usd_observations(repo, as_of=instant)
        upstream_row = repo.fetch_macro_domain_state_as_of("policy_rates", instant)
        upstream = _upstream_states(upstream_row)
        state = compute_usd_state(
            observations,
            as_of=instant,
            upstream=tuple(item for item, _role in upstream),
            prior_state=_prior_state(repo, "usd", instant),
        )
    except Exception as exc:
        logger.warning("macro usd state failed: %s", repr(exc))
        return _failed("usd", instant, exc)
    edges = (
        [(int(upstream_row["state_id"]), role) for _item, role in upstream]
        if upstream_row is not None
        else []
    )
    return _persist(
        repo, state, computed_at=computed_at or datetime.now(UTC), upstream=edges
    )


def _upstream_states(
    row: dict[str, object] | None,
) -> list[tuple[UpstreamState, str]]:
    """The rates answer as an upstream reference, with the role it plays for USD.

    ``policy_actual``: what the committee has done is what the dollar is measured
    against. The role is named here rather than inside the engine because the same
    upstream state plays a different role for gold, and a role baked into the engine
    could not be two things at once.
    """
    if row is None:
        return []
    return [
        (
            UpstreamState(
                domain="policy_rates",
                state=str(row["state"]),
                direction=str(row["direction"]),
                inputs_hash=str(row["inputs_hash"]),
                as_of=row["as_of"],
                confidence=row["confidence"],
            ),
            "policy_actual",
        )
    ]


def _persist(
    repo: Repository,
    state: MacroDomainState,
    *,
    computed_at: datetime,
    upstream: Sequence[tuple[int, str]] = (),
) -> MacroStateJobResult:
    citable = [ref for ref in state.evidence_refs if ref.obs_id is not None]
    if not citable:
        # Not an error: with no stored evidence the engine correctly abstains.  Writing
        # the abstention anyway would create a row citing nothing, which is the one
        # thing the state table refuses -- an answer nobody can reconstruct or falsify.
        return MacroStateJobResult(
            domain=state.domain,
            status="abstained",
            as_of=state.as_of,
            state=state.state,
            direction=state.direction,
            confidence=state.confidence,
            contradiction_count=len(state.contradictions),
        )
    try:
        state_id = repo.insert_macro_domain_state(
            state, computed_at=computed_at, upstream=upstream
        )
    except Exception as exc:
        logger.warning("macro %s state persist failed: %s", state.domain, repr(exc))
        return _failed(state.domain, state.as_of, exc)
    return MacroStateJobResult(
        domain=state.domain,
        status="ok",
        as_of=state.as_of,
        state_id=state_id,
        state=state.state,
        direction=state.direction,
        confidence=state.confidence,
        evidence_count=len(state.evidence_refs),
        contradiction_count=len(state.contradictions),
    )


def _prior_state(
    repo: Repository, domain: str, as_of: datetime
) -> MacroDomainState | None:
    """The last answer given for an earlier instant, rebuilt with its lineage.

    Strictly earlier: picking up a state stored for this same instant would make a
    recompute compare the evidence against itself, and the revision term -- and so the
    confidence -- would differ between two runs over identical inputs.
    """
    row = repo.fetch_macro_domain_state_as_of(domain, as_of, strictly_before=True)
    if row is None:
        return None
    evidence = repo.fetch_macro_domain_state_evidence(int(row["state_id"]))
    return macro_domain_state_from_row(row, evidence)


def _paths(comparison: PolicyComparison) -> list[PolicyPath]:
    """The paths that actually resolved; a missing slot stays missing.

    Never substituted for one another -- an absent dealer survey is an absent dealer
    survey, not an excuse to let the market shadow speak for it.
    """
    slots = (
        comparison.actual,
        comparison.committee_projection,
        comparison.dealer_expectations,
        comparison.market_implied,
    )
    return [slot.path for slot in slots if slot.path is not None]


def _attribution(
    observations: tuple[DomainObservation, ...], *, as_of: datetime
) -> YieldAttribution | None:
    """Split the 10y move into its real and compensation legs over the window.

    Returns ``None`` when the nominal leg itself has no start and end, because an
    attribution of a move nobody can measure is not an unavailable attribution -- it is
    not an attribution at all, and the engine has its own language for absence.
    """
    start_on = as_of.date() - timedelta(days=ATTRIBUTION_WINDOW_DAYS)
    earliest = start_on - timedelta(days=ATTRIBUTION_START_TOLERANCE_DAYS)
    legs = {
        series_id: (
            _value_at(
                observations, series_id, on_or_before=start_on, not_before=earliest
            ),
            _latest_value(observations, series_id),
        )
        for series_id in ("DGS10", "DFII10", "T10YIE")
    }
    if legs["DGS10"] == (None, None):
        return None
    return attribute_nominal_change(
        nominal_start=legs["DGS10"][0],
        nominal_end=legs["DGS10"][1],
        real_start=legs["DFII10"][0],
        real_end=legs["DFII10"][1],
        breakeven_start=legs["T10YIE"][0],
        breakeven_end=legs["T10YIE"][1],
    )


def _value_at(
    observations: tuple[DomainObservation, ...],
    series_id: str,
    *,
    on_or_before: date,
    not_before: date,
) -> Decimal | None:
    candidates = [
        obs
        for obs in observations
        if obs.series_id == series_id and not_before <= obs.period_end <= on_or_before
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda obs: obs.period_end).value


def _latest_value(
    observations: tuple[DomainObservation, ...], series_id: str
) -> Decimal | None:
    candidates = [obs for obs in observations if obs.series_id == series_id]
    if not candidates:
        return None
    return max(candidates, key=lambda obs: obs.period_end).value


def _failed(domain: str, as_of: datetime, exc: Exception) -> MacroStateJobResult:
    return MacroStateJobResult(
        domain=domain,
        status="failed",
        as_of=as_of,
        error_type=f"{type(exc).__module__}.{type(exc).__name__}",
        error_message=str(exc)[:1000],
    )
