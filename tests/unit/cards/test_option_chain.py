import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from uw_scan.cards.option_chain import _parse_occ, aggregate_chain_per_strike
from uw_scan.models import OptionContractRow
from uw_scan.normalize import normalize_option_contracts

FIXTURE = Path(__file__).parents[2] / "fixtures" / "option_contracts_googl.json"


# ---------------------------------------------------------------------------
# OCC parser
# ---------------------------------------------------------------------------
def test_parse_occ_call() -> None:
    parsed = _parse_occ("GOOGL260513C00395000")
    assert parsed is not None
    expiry, opt_type, strike = parsed
    assert expiry == date(2026, 5, 13)
    assert opt_type == "C"
    assert strike == Decimal("395")


def test_parse_occ_put_fractional_strike() -> None:
    parsed = _parse_occ("AAPL260117P00187500")
    assert parsed is not None
    expiry, opt_type, strike = parsed
    assert expiry == date(2026, 1, 17)
    assert opt_type == "P"
    assert strike == Decimal("187.5")


def test_parse_occ_invalid_returns_none() -> None:
    assert _parse_occ("garbage") is None
    assert _parse_occ("AAPL261332C00100000") is None  # month 13 invalid


# ---------------------------------------------------------------------------
# Aggregator: synthetic data for pairing/grouping invariants
# (per Codex ISSUE-15 — don't rely on a 20-row captured fixture
#  containing paired calls+puts for a given strike)
# ---------------------------------------------------------------------------
def _contract(symbol: str, volume: int, oi: int) -> OptionContractRow:
    return OptionContractRow(option_symbol=symbol, volume=volume, open_interest=oi)


def test_aggregate_groups_call_and_put_at_same_strike() -> None:
    rows = aggregate_chain_per_strike(
        [
            _contract("GOOGL260619C00180000", volume=100, oi=500),
            _contract("GOOGL260619P00180000", volume=80, oi=300),
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.expiry == date(2026, 6, 19)
    assert r.strike == Decimal("180")
    assert r.call_volume == 100
    assert r.call_oi == 500
    assert r.put_volume == 80
    assert r.put_oi == 300


def test_aggregate_drops_far_otm_strikes() -> None:
    rows = aggregate_chain_per_strike(
        [
            _contract("GOOGL260619C00180000", volume=100, oi=500),
            _contract("GOOGL260619C00500000", volume=100, oi=500),  # >60% above spot
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    assert len(rows) == 1
    assert rows[0].strike == Decimal("180")


def test_aggregate_drops_far_expiries() -> None:
    rows_tight = aggregate_chain_per_strike(
        [
            _contract("GOOGL260520C00180000", volume=100, oi=500),  # 7 dte
            _contract("GOOGL270520C00180000", volume=100, oi=500),  # ~372 dte
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=30,
        today=date(2026, 5, 13),
    )
    rows_wide = aggregate_chain_per_strike(
        [
            _contract("GOOGL260520C00180000", volume=100, oi=500),
            _contract("GOOGL270520C00180000", volume=100, oi=500),
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=400,
        today=date(2026, 5, 13),
    )
    assert len(rows_tight) == 1
    assert len(rows_wide) == 2


def test_aggregate_drops_expired_contracts() -> None:
    rows = aggregate_chain_per_strike(
        [
            _contract("GOOGL260501C00180000", volume=100, oi=500),  # already expired
            _contract("GOOGL260520C00180000", volume=100, oi=500),
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    assert len(rows) == 1
    assert rows[0].expiry == date(2026, 5, 20)


def test_aggregate_skips_unparseable_symbols() -> None:
    rows = aggregate_chain_per_strike(
        [
            _contract("not-an-occ", volume=100, oi=500),
            _contract("GOOGL260520C00180000", volume=200, oi=900),
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    assert len(rows) == 1
    assert rows[0].call_volume == 200


def test_aggregate_sums_duplicates_at_same_key() -> None:
    rows = aggregate_chain_per_strike(
        [
            _contract("GOOGL260619C00180000", volume=100, oi=500),
            _contract("GOOGL260619C00180000", volume=50, oi=200),
        ],
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    assert len(rows) == 1
    assert rows[0].call_volume == 150
    assert rows[0].call_oi == 700


# ---------------------------------------------------------------------------
# Captured UW fixture: shape/normalization smoke test only
# ---------------------------------------------------------------------------
def test_aggregate_chain_per_strike_runs_on_captured_payload() -> None:
    contracts = normalize_option_contracts(json.loads(FIXTURE.read_text()))
    rows = aggregate_chain_per_strike(
        contracts,
        spot=Decimal("389.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    # No duplicate (expiry, strike) keys
    seen = {(r.expiry, r.strike) for r in rows}
    assert len(seen) == len(rows)
    # All rows respect filter window
    for r in rows:
        pct = abs(r.strike - Decimal("389.00")) / Decimal("389.00")
        assert pct <= Decimal("0.60")
    # Sorted by (expiry, strike)
    assert rows == sorted(rows, key=lambda r: (r.expiry, r.strike))
