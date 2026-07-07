"""Same-day UW fetch dedupe at the fetcher boundary (issue #225).

The load-bearing budget test: two same-day callers of an identical fetch must
spend UW budget exactly ONCE (the second reads the Postgres memo). Uses a real
test DB (the memo persists to Postgres) + a call-counting fake UW client — the
external HTTP layer is mocked (expected), but the market VALUES are a realistic
frozen fixture snapshotted from docs/uw-samples, never fabricated.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources.uw import (
    fetch_greek_exposure_by_expiry,
    fetch_option_contracts,
)

# Frozen from docs/uw-samples/option_contracts.json (real TSLA row).
_FROZEN_OC_BODY: dict[str, Any] = {
    "data": [
        {
            "last_price": "2.21",
            "option_symbol": "TSLA260511C00440000",
            "volume": 179385,
            "implied_volatility": "0.748755696476749",
            "open_interest": 5497,
            "nbbo_bid": "2.20",
            "nbbo_ask": "2.24",
        }
    ]
}

_FROZEN_GEX_EXPIRY_BODY: dict[str, Any] = {
    "data": [
        {
            "date": "2026-07-07",
            "expiry": "2026-07-18",
            "dte": 11,
            "call_delta": "1.2e8",
            "put_delta": "-9.0e7",
            "call_gex": "5.5e6",
            "put_gex": "-4.1e6",
            "call_vanna": "1.0e5",
            "put_vanna": "-9e4",
            "call_charm": "2e4",
            "put_charm": "-1e4",
        }
    ]
}


class _CountingUwClient:
    """Fake UwClient that counts live HTTP GETs and returns a canned body.

    Same rate_limit shape as the real client so _persist_audit reads cleanly.
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[tuple[EndpointSlug, str | None, dict[str, Any] | None]] = []
        self.rate_limit = SimpleNamespace(
            daily_count=0, minute_remaining=110, minute_reset=None
        )

    def get(
        self,
        slug: EndpointSlug,
        ticker: str | None = None,
        params: dict[str, Any] | None = None,
        run_id: int | None = None,
        *,
        option_symbol: str | None = None,
    ) -> tuple[httpx.Response, dict[str, str]]:
        self.calls.append((slug, ticker, params))
        resp = httpx.Response(
            200,
            json=self._payload,
            request=httpx.Request("GET", "https://example/test"),
        )
        return resp, {}


def _run_id(repo) -> int:
    return repo.insert_scan_run(ticker="TSLA")


def test_option_contracts_two_same_day_callers_spend_once(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _CountingUwClient(_FROZEN_OC_BODY)
    run_id = _run_id(repo)

    first = fetch_option_contracts(client, repo, run_id, "TSLA")
    second = fetch_option_contracts(client, repo, run_id, "TSLA")

    # Live fetch happened exactly once; the second caller read the memo.
    assert len(client.calls) == 1
    # Same typed result both times (HIT re-normalizes the cached body).
    assert [r.option_symbol for r in first] == [r.option_symbol for r in second]
    assert first[0].option_symbol == "TSLA260511C00440000"


def test_force_refresh_bypasses_the_memo(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _CountingUwClient(_FROZEN_OC_BODY)
    run_id = _run_id(repo)

    fetch_option_contracts(client, repo, run_id, "TSLA")  # MISS -> spend + store
    fetch_option_contracts(client, repo, run_id, "TSLA")  # HIT -> no spend
    assert len(client.calls) == 1
    fetch_option_contracts(
        client, repo, run_id, "TSLA", force_refresh=True
    )  # forced re-fetch
    assert len(client.calls) == 2


def test_different_ticker_is_not_deduped(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _CountingUwClient(_FROZEN_OC_BODY)
    run_id = _run_id(repo)
    fetch_option_contracts(client, repo, run_id, "TSLA")
    fetch_option_contracts(client, repo, run_id, "NVDA")
    assert len(client.calls) == 2  # distinct keys -> both spend


def test_greek_exposure_by_expiry_current_day_dedupes(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _CountingUwClient(_FROZEN_GEX_EXPIRY_BODY)
    run_id = _run_id(repo)
    fetch_greek_exposure_by_expiry(client, repo, run_id, "TSLA")
    fetch_greek_exposure_by_expiry(client, repo, run_id, "TSLA")
    assert len(client.calls) == 1


def test_greek_exposure_by_expiry_historical_date_bypasses_memo(seeded_db_empty_cards):
    """An explicit historical `date` selector must never share the today memo."""
    repo = seeded_db_empty_cards
    client = _CountingUwClient(_FROZEN_GEX_EXPIRY_BODY)
    run_id = _run_id(repo)
    fetch_greek_exposure_by_expiry(client, repo, run_id, "TSLA", date="2026-06-30")
    fetch_greek_exposure_by_expiry(client, repo, run_id, "TSLA", date="2026-06-30")
    # Historical path is not memoized — both calls hit UW.
    assert len(client.calls) == 2
