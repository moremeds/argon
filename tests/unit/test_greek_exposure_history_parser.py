"""Pure parser tests — no DB, no network."""

from datetime import date

import pytest

from uw_scan.cards.greek_exposure_history import parse_greek_exposure_history


def test_parses_well_formed_payload() -> None:
    body = {
        "data": [
            {
                "date": "2026-05-14",
                "call_gex": "1000000000",
                "put_gex": "-500000000",
                "call_delta": "10000000",
                "put_delta": "-5000000",
            },
            {
                "date": "2026-05-15",
                "call_gex": "1100000000",
                "put_gex": "-550000000",
                "call_delta": "11000000",
                "put_delta": "-5500000",
            },
        ]
    }
    rows = parse_greek_exposure_history(body)
    assert len(rows) == 2
    assert rows[0]["date"] == date(2026, 5, 14)
    assert rows[0]["call_gex"] == pytest.approx(1e9)
    assert rows[0]["net_gex"] == pytest.approx(5e8)
    assert rows[0]["net_dex"] == pytest.approx(5e6)


def test_skips_malformed_rows() -> None:
    body = {
        "data": [
            {
                "date": "2026-05-14",
                "call_gex": "ok-string-not-number",
                "put_gex": "0",
                "call_delta": "0",
                "put_delta": "0",
            },
            {
                "date": "2026-05-15",
                "call_gex": "1",
                "put_gex": "1",
                "call_delta": "1",
                "put_delta": "1",
            },
        ]
    }
    rows = parse_greek_exposure_history(body)
    assert len(rows) == 1
    assert rows[0]["date"] == date(2026, 5, 15)


def test_handles_empty_or_missing_data() -> None:
    assert parse_greek_exposure_history({}) == []
    assert parse_greek_exposure_history({"data": None}) == []
    assert parse_greek_exposure_history({"data": []}) == []


def test_parses_real_uw_shape_call_gamma_put_gamma() -> None:
    """UW's actual /greek-exposure payload uses call_gamma/put_gamma keys
    (not call_gex/put_gex). Regression for the silent-zero bug where the
    parser defaulted to 0 because the keys never matched."""
    body = {
        "data": [
            {
                "date": "2026-05-20",
                "put_charm": "279949437.8628",
                "put_delta": "-122956330.6777",
                "put_gamma": "-3985304.2473",
                "put_vanna": "-478402822.7442",
                "call_charm": "-216807965.9165",
                "call_delta": "204991256.2086",
                "call_gamma": "3412731.7633",
                "call_vanna": "36743805.0725",
            },
        ]
    }
    rows = parse_greek_exposure_history(body)
    assert len(rows) == 1
    assert rows[0]["call_gex"] == pytest.approx(3412731.7633)
    assert rows[0]["put_gex"] == pytest.approx(-3985304.2473)
    assert rows[0]["net_gex"] == pytest.approx(-572572.4840)
    assert rows[0]["call_delta"] == pytest.approx(204991256.2086)
    assert rows[0]["put_delta"] == pytest.approx(-122956330.6777)


def test_accepts_iso_date_strings_or_date_objects() -> None:
    body = {
        "data": [
            {
                "date": "2026-05-15",
                "call_gex": "1",
                "put_gex": "1",
                "call_delta": "1",
                "put_delta": "1",
            },
            {
                "date": date(2026, 5, 16),
                "call_gex": "1",
                "put_gex": "1",
                "call_delta": "1",
                "put_delta": "1",
            },
        ]
    }
    rows = parse_greek_exposure_history(body)
    assert rows[0]["date"] == date(2026, 5, 15)
    assert rows[1]["date"] == date(2026, 5, 16)
