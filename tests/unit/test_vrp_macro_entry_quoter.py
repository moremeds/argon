from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from uw_scan.reports import vrp_macro_entry as M

_ET = ZoneInfo("America/New_York")


def _et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=_ET)


@pytest.fixture
def settings():
    # quote_leg only reads the xenon url/key + the (Task 6) timeout; a config
    # stub is sufficient for a pure unit test (the fetcher itself is monkeypatched).
    return SimpleNamespace(
        xenon_query_api_url="http://127.0.0.1:8421",
        xenon_query_api_key=None,
        vrp_macro_entry_quote_timeout_s=8.0,
    )


def test_uses_ib_when_available(monkeypatch, settings):
    # xenon supplies NBBO + IV + und_spot only — NOT greeks (those are always BS-computed)
    monkeypatch.setattr(
        M,
        "fetch_ib_option_quote",
        lambda **k: {"bid": 12.0, "ask": 12.4, "iv": 0.17, "und_spot": 6000},
    )
    q = M.quote_leg(
        strike=5800,
        expiry="20260807",
        as_of=_et(2026, 6, 24, 11, 0),
        underlying_spot=6000,
        r=0.04,
        settings=settings,
    )
    assert q.source == "xenon_ib" and float(q.nbbo_bid) == 12.0
    assert q.greeks_source == "bs"  # never "ib"
    assert (
        q.delta is not None and -0.5 < float(q.delta) < 0.0
    )  # BS put delta, not echoed


def test_falls_back_to_uw_and_bs_fills_greeks(monkeypatch, settings):
    monkeypatch.setattr(M, "fetch_ib_option_quote", lambda **k: None)  # IB down
    # OptionContractRow shape: no strike/expiry/und_spot on the row itself
    uw_row = {
        "option_symbol": "SPXW260807P05800000",
        "nbbo_bid": 12.1,
        "nbbo_ask": 12.5,
        "implied_volatility": 0.17,
    }
    q = M.quote_leg(
        strike=5800,
        expiry="20260807",
        as_of=_et(2026, 6, 24, 11, 0),
        underlying_spot=6000,
        r=0.04,
        settings=settings,
        uw_row=uw_row,
    )
    assert q.source == "uw" and q.greeks_source == "bs"
    assert q.delta is not None and -0.5 < float(q.delta) < 0.0  # BS put delta


def test_iv_absent_tags_greeks_none(monkeypatch, settings):
    # xenon NBBO present but greeks object null -> iv None -> greeks_source 'none', greeks 0
    monkeypatch.setattr(
        M,
        "fetch_ib_option_quote",
        lambda **k: {"bid": 12.0, "ask": 12.4, "iv": None, "und_spot": 6000},
    )
    q = M.quote_leg(
        strike=5800,
        expiry="20260807",
        as_of=_et(2026, 6, 24, 11, 0),
        underlying_spot=6000,
        r=0.04,
        settings=settings,
    )
    assert q.source == "xenon_ib" and q.greeks_source == "none"
    assert float(q.delta) == 0.0 and float(q.gamma) == 0.0
