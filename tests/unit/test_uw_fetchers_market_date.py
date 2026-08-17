"""`market_date` must reach UW as `date=`, and must never touch the same-day memo.

These assert on the REQUEST the fetcher builds, not on market values — the UW
transport is stubbed, which is a test double for an external service, not
fabricated data.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from uw_scan.sources import uw

# (fetcher, positional args after ticker)
DATE_HONOURING = [
    ("fetch_term_structure", ()),
    ("fetch_interpolated_iv", ()),
    ("fetch_oi_per_strike", ()),
    ("fetch_oi_change", ()),
    ("fetch_max_pain", ()),
    ("fetch_darkpool_ticker", ()),
    ("fetch_iv_rank", ()),
    ("fetch_greek_exposure", ("2026-09-18",)),
    ("fetch_spot_exposures", ("2026-09-18",)),
]


@pytest.fixture
def captured(monkeypatch):
    seen: dict = {}

    def fake_fetch_json(client, repo, run_id, slug, ticker, params=None, **kw):
        seen["slug"], seen["params"] = slug, params
        return {"data": []}

    monkeypatch.setattr(uw, "_fetch_json", fake_fetch_json)
    return seen


@pytest.mark.parametrize("fn_name,extra", DATE_HONOURING)
def test_market_date_is_sent_as_date_param(captured, fn_name, extra):
    getattr(uw, fn_name)(
        MagicMock(), MagicMock(), 1, "AAPL", *extra, market_date=date(2026, 8, 12)
    )
    assert captured["params"]["date"] == "2026-08-12"


@pytest.mark.parametrize("fn_name,extra", DATE_HONOURING)
def test_omitting_market_date_leaves_params_unchanged(captured, fn_name, extra):
    """Live path must stay byte-identical: no `date` key at all when replaying is off."""
    getattr(uw, fn_name)(MagicMock(), MagicMock(), 1, "AAPL", *extra)
    assert "date" not in (captured["params"] or {})


def test_bulk_screener_ticker_sends_date(captured):
    uw.fetch_bulk_screener_ticker(
        MagicMock(), MagicMock(), 1, "AAPL", market_date=date(2026, 8, 12)
    )
    assert captured["params"]["date"] == "2026-08-12"
    assert captured["params"]["ticker"] == "AAPL"


def test_memoized_fetcher_bypasses_the_memo_under_replay(monkeypatch):
    """The same-day memo keys on ET-today. Under replay a HIT would return TODAY's
    payload to be stamped with a past date, and a MISS would store the HISTORICAL
    payload under today's key — poisoning the live nightly path. Both are
    fabrication, so replay must not read or write the memo at all."""
    memo_used = False

    def fake_memoized(*a, **kw):
        nonlocal memo_used
        memo_used = True
        return {"data": []}

    seen: dict = {}

    def fake_fetch_json(client, repo, run_id, slug, ticker, params=None, **kw):
        seen["params"] = params
        return {"data": []}

    monkeypatch.setattr(uw, "_memoized_fetch_json", fake_memoized)
    monkeypatch.setattr(uw, "_fetch_json", fake_fetch_json)

    uw.fetch_option_contracts(
        MagicMock(), MagicMock(), 1, "AAPL", market_date=date(2026, 8, 12)
    )
    assert not memo_used, "replay must bypass the same-day memo"
    assert seen["params"]["date"] == "2026-08-12"

    uw.fetch_greek_exposure_by_expiry(
        MagicMock(), MagicMock(), 1, "AAPL", market_date=date(2026, 8, 12)
    )
    assert not memo_used, "replay must bypass the same-day memo"


def test_memoized_fetcher_still_uses_the_memo_on_the_live_path(monkeypatch):
    memo_used = False

    def fake_memoized(*a, **kw):
        nonlocal memo_used
        memo_used = True
        return {"data": []}

    monkeypatch.setattr(uw, "_memoized_fetch_json", fake_memoized)
    uw.fetch_option_contracts(MagicMock(), MagicMock(), 1, "AAPL")
    assert memo_used, "live path must keep its budget-saving memo"
