"""The evidence set an engine declares it reads, and the windows it reads it over.

Both are assembled from the source contracts rather than restated, so what these tests
guard is the assembly: a role that enters ``RATES_EVIDENCE`` without a history window
would read a series' entire history into every ``inputs_hash``, and a non-FRED series
that reaches the FRED ingest's default list produces a failure nothing can explain.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

import pytest

from uw_scan.macro.evidence_store import (
    INFLATION_EVIDENCE,
    POSITIONING_HISTORY_DAYS,
    RATES_EVIDENCE,
    SUPPLY_HISTORY_DAYS,
    EvidenceContractError,
    SeriesEvidenceContract,
    _window_start,
)
from uw_scan.macro.rates_market import MARKET_SERIES_CONTRACT
from uw_scan.sources.fred_macro import SERIES_CONTRACT
from uw_scan.worker.jobs.macro_series_ingest import DEFAULT_SERIES, FRED_SOURCE

AS_OF = datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_every_rates_role_resolves_to_evidence() -> None:
    """The five market roles the engine has enumerated since MC0, all now populated.

    ``supply``, ``positioning`` and ``plumbing`` resolved to nothing for two milestones,
    and the engine correctly reported them absent rather than inventing them.
    """
    roles = Counter(contract.causal_role for contract in RATES_EVIDENCE)
    assert roles == {
        "curve": 1,
        "decomposition_component": 2,
        "plumbing": 3,
        "supply": 7,
        "positioning": 7,
    }


def test_the_fred_ingest_is_never_asked_for_a_publisher_it_cannot_serve() -> None:
    """``RATES_EVIDENCE`` is what an engine READS, not what one publisher serves.

    MC3 put Treasury and CFTC series into it. Without the source filter the nightly FRED
    job asks ALFRED for ``10-Year|Note`` and reports a failure whose cause is invisible
    from the error.
    """
    assert all(series_id in SERIES_CONTRACT for series_id in DEFAULT_SERIES)
    assert {contract.source for contract in RATES_EVIDENCE} == {
        FRED_SOURCE,
        "treasurydirect",
        "cftc",
    }
    non_fred = {c.series_id for c in RATES_EVIDENCE if c.source != FRED_SOURCE}
    assert non_fred and not (non_fred & set(DEFAULT_SERIES))


def test_every_rates_contract_declares_its_own_window() -> None:
    """One window for the domain would starve one role or bloat another.

    A curve attribution reads a month. A supply baseline reads five quarterly
    refundings — two years. A positioning percentile reads the four-year sample its
    thresholds were calibrated on. Reading all three over the longest would drag two
    years of daily curve prints into every state's identity.
    """
    windows = {c.series_id: c.history_days for c in RATES_EVIDENCE}
    assert all(days is not None for days in windows.values())
    assert windows["10-Year|Note"] == SUPPLY_HISTORY_DAYS
    assert windows["043602|lev_money_net_pct_oi"] == POSITIONING_HISTORY_DAYS
    assert windows["DGS10"] < windows["10-Year|Note"] < windows["043602|open_interest"]


def test_inflation_contracts_carry_no_window_because_its_caller_supplies_one() -> None:
    """Its series are all monthly and its window is month-ALIGNED.

    A day count cannot express that, so a number here would be a value nothing reads --
    and a value nothing reads is the one that silently becomes wrong.
    """
    assert all(contract.history_days is None for contract in INFLATION_EVIDENCE)


def test_a_contract_with_no_window_and_no_caller_window_is_refused() -> None:
    """Refused rather than defaulted: an unbounded read is the expensive silent case."""
    unbounded = SeriesEvidenceContract(
        series_id="PCEPILFE",
        causal_role="realized",
        unit="index_2017_100_sa",
        publisher_transform="index_level",
        source=FRED_SOURCE,
        history_days=None,
    )
    with pytest.raises(EvidenceContractError, match="whole history"):
        _window_start(unbounded, AS_OF, None)


def test_market_units_come_from_the_market_contract_not_a_restatement() -> None:
    """A share and a contract count are not commensurable, so the unit must not drift."""
    for contract in RATES_EVIDENCE:
        if contract.source == FRED_SOURCE:
            continue
        assert contract.unit == MARKET_SERIES_CONTRACT[contract.series_id].unit


def test_reserve_balances_stay_unregistered_until_its_unit_is_a_vintage_property() -> (
    None
):
    """WRESBAL fails a clause the probe did not originally have, so it is named here.

    A ``SeriesEvidenceContract`` declares ONE unit per series. FRED republished WRESBAL's
    entire history on 2025-11-13 with every value multiplied by a thousand -- period
    2025-06-04 reads 3294.381 under the vintage in force until 2025-11-12 and 3294381.0
    under the one after, and the ratio is exactly 1000.0 across all 566 multi-vintage
    periods. The unit is therefore a property of the vintage, which this contract cannot
    express and which ``series/observations`` does not report.

    Registering it anyway costs nothing in live use, where every readable vintage is
    post-rebasing, and silently breaks every replay before that date by a factor of a
    thousand -- which is the case this whole milestone exists to make trustworthy. The
    reserve-balances slice reports UNKNOWN instead of borrowing a neighbour.
    """
    assert "WRESBAL" not in SERIES_CONTRACT
    assert "WRESBAL" not in {contract.series_id for contract in RATES_EVIDENCE}
