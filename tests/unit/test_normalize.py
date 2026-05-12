"""Contract tests for normalizers against real saved UW payloads.

Each test loads docs/uw-samples/<slug>.json, runs the corresponding normalizer,
asserts the typed output. Asserts specific field values against the saved payload.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from uw_scan import normalize

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "uw-samples"


def _load(slug: str) -> dict:
    payload = json.loads((SAMPLES / f"{slug}.json").read_text())
    body = payload["body"]
    assert isinstance(body, dict), f"{slug}: body is not a dict"
    return body


# ---------------------------------------------------------------------------
# 18+ normalizer contract tests (one per slug)
# ---------------------------------------------------------------------------


def test_normalize_flow_alerts():
    body = _load("flow_alerts")
    rows = normalize.normalize_flow_alerts(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.id  # uuid string
    assert first.ticker
    assert first.type in {"call", "put"}


def test_normalize_iv_rank():
    body = _load("iv_rank")
    rows = normalize.normalize_iv_rank(body)
    assert len(rows) > 0
    latest = normalize.latest_by_date(rows)
    assert latest is not None
    assert latest.iv_rank_1y is not None
    assert isinstance(latest.iv_rank_1y, Decimal)


def test_normalize_volatility_stats():
    body = _load("volatility_stats")
    rows = normalize.normalize_volatility_stats(body)
    assert len(rows) > 0
    latest = normalize.latest_by_date(rows)
    assert latest is not None
    assert latest.ticker == "TSLA"
    assert latest.iv is not None
    assert latest.iv_rank is not None


def test_normalize_realized_volatility():
    body = _load("realized_volatility")
    rows = normalize.normalize_realized_volatility(body)
    assert len(rows) > 0
    latest = normalize.latest_by_date(rows)
    assert latest is not None
    assert latest.price is not None
    # Latest row's realized_volatility may be null (forward shift) — assert an earlier row has it.
    earlier = [r for r in rows if r.realized_volatility is not None]
    assert len(earlier) > 0


def test_normalize_term_structure():
    body = _load("term_structure")
    rows = normalize.normalize_term_structure(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.ticker == "TSLA"
    assert first.dte is not None
    assert first.volatility is not None


def test_normalize_interpolated_iv():
    body = _load("interpolated_iv")
    rows = normalize.normalize_interpolated_iv(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.days >= 1
    assert first.volatility is not None
    assert first.percentile is not None


def test_normalize_skew():
    body = _load("skew")
    rows = normalize.normalize_skew(body, expiry_hint="2026-05-15")
    assert len(rows) > 0
    first = rows[0]
    assert first.delta == 25
    assert first.expiry is not None
    assert first.risk_reversal is not None


def test_normalize_greek_exposure():
    body = _load("greek_exposure")
    rows = normalize.normalize_greek_exposure(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.expiry is not None
    assert first.strike is not None
    assert first.call_gex is not None or first.put_gex is not None


def test_normalize_spot_exposures():
    body = _load("spot_exposures")
    rows = normalize.normalize_spot_exposures(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.expiry is not None
    assert first.strike is not None
    # _oi variants are the ones we keep
    assert first.call_delta_oi is not None or first.put_delta_oi is not None


def test_normalize_greeks():
    body = _load("greeks")
    rows = normalize.normalize_greeks(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.expiry is not None
    assert first.strike is not None
    assert first.call_option_symbol is not None
    assert first.put_option_symbol is not None


def test_normalize_oi_per_strike():
    body = _load("oi_per_strike")
    rows = normalize.normalize_oi_per_strike(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.strike is not None
    assert first.call_oi is not None


def test_normalize_oi_change():
    body = _load("oi_change")
    rows = normalize.normalize_oi_change(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.underlying_symbol == "TSLA"
    assert first.option_symbol.startswith("TSLA")
    assert first.curr_oi is not None


def test_normalize_max_pain():
    body = _load("max_pain")
    rows = normalize.normalize_max_pain(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.expiry is not None
    assert first.max_pain is not None


def test_normalize_option_contracts():
    body = _load("option_contracts")
    rows = normalize.normalize_option_contracts(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.option_symbol.startswith("TSLA")
    assert first.implied_volatility is not None
    assert first.open_interest is not None


def test_normalize_option_contracts_by_symbol():
    body = _load("option_contracts_by_symbol")
    rows = normalize.normalize_option_contracts_by_symbol(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.option_symbol.startswith("TSLA")


def test_normalize_darkpool_ticker():
    body = _load("darkpool_ticker")
    rows = normalize.normalize_darkpool_ticker(body)
    assert len(rows) > 0
    first = rows[0]
    assert first.ticker == "TSLA"
    assert first.tracking_id is not None
    assert first.size is not None
    assert first.price is not None


def test_normalize_short_data():
    body = _load("short_data")
    rows = normalize.normalize_short_data(body)
    assert len(rows) > 0
    latest = normalize.latest_by_timestamp(rows)
    assert latest is not None
    assert latest.symbol == "TSLA"
    assert latest.short_shares_available is not None
    assert latest.fee_rate is not None


def test_normalize_bulk_screener_present_but_not_used():
    """The bulk_screener_stocks_sp500 sample exists from S0 research but S1 does not wire it.

    This test asserts the sample file is present so future slices can rely on it,
    without making S1 take a dependency on the bulk-screener normalizer.
    """
    path = SAMPLES / "bulk_screener_stocks_sp500.json"
    assert path.exists()
    payload = json.loads(path.read_text())
    assert "body" in payload
    assert payload["status_code"] == 200


def test_normalize_bulk_screener():
    """S2 bulk screener normalizer: returns 100 typed rows with Decimal-cast numerics."""
    body = _load("bulk_screener_stocks_sp500")
    rows = normalize.normalize_bulk_screener(body)
    assert len(rows) == 100

    by_ticker = {r.ticker: r for r in rows}
    # NVDA appears in the sample (verified via inspection).
    assert "NVDA" in by_ticker
    nvda = by_ticker["NVDA"]
    assert nvda.sector == "Technology"
    assert nvda.iv_rank is not None
    assert isinstance(nvda.iv_rank, Decimal)
    assert nvda.net_call_premium is not None
    assert isinstance(nvda.net_call_premium, Decimal)
    assert nvda.total_open_interest is not None
    assert nvda.total_open_interest > 0
    # TSLA should also be present in S&P 500 screener result.
    assert "TSLA" in by_ticker
    tsla = by_ticker["TSLA"]
    assert isinstance(tsla.iv_rank, Decimal)
    assert tsla.next_earnings_date is None or hasattr(tsla.next_earnings_date, "year")


def test_normalize_bulk_screener_missing_data_raises():
    with pytest.raises(normalize.NormalizationError):
        normalize.normalize_bulk_screener({"oops": []})


def test_normalize_bulk_screener_wrong_type_raises():
    with pytest.raises(normalize.NormalizationError):
        normalize.normalize_bulk_screener({"data": "not-a-list"})


# ---------------------------------------------------------------------------
# Negative tests: strict key access
# ---------------------------------------------------------------------------


def test_missing_data_key_raises():
    with pytest.raises(normalize.NormalizationError):
        normalize.normalize_iv_rank({"oops": []})


def test_wrong_data_type_raises():
    with pytest.raises(normalize.NormalizationError):
        normalize.normalize_iv_rank({"data": "not-a-list"})
