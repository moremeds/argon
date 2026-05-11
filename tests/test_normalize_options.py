from decimal import Decimal

from uw_scan.normalize.options import normalize_oi_by_expiry, normalize_option_contract_snapshot, parse_decimal


def test_parse_decimal_preserves_nulls():
    assert parse_decimal(None) is None
    assert parse_decimal("") is None
    assert parse_decimal("123.45") == Decimal("123.45")


def test_normalize_option_contract_snapshot_maps_string_numbers():
    row = normalize_option_contract_snapshot(
        run_id="run-1",
        market_date="2026-05-11",
        fetched_at_utc="2026-05-11T14:00:00Z",
        payload={
            "option_symbol": "NVDA260619C00650000",
            "ticker": "NVDA",
            "expiry": "2026-06-19",
            "strike": "650",
            "option_type": "call",
            "implied_volatility": "0.54",
            "open_interest": "900",
            "prev_oi": "700",
            "volume": "2400",
            "premium": "1250000",
            "bid": "19.20",
            "ask": "19.80",
        },
    )
    assert row.option_symbol == "NVDA260619C00650000"
    assert row.strike == Decimal("650")
    assert row.mid == Decimal("19.50")
    assert row.open_interest == 900


def test_normalize_oi_by_expiry_maps_calls_and_puts():
    row = normalize_oi_by_expiry(
        run_id="run-1",
        ticker="NVDA",
        market_date="2026-05-11",
        fetched_at_utc="2026-05-11T14:00:00Z",
        payload={"expiry": "2026-06-19", "call_oi": "12000", "put_oi": "8000"},
    )
    assert row.call_open_interest == 12000
    assert row.put_open_interest == 8000
