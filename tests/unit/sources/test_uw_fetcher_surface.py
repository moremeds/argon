"""Pin sources/uw.py's public surface and the request every fetcher sends.

Both fixtures were captured from main BEFORE the fetcher-table refactor (I-57)
and must not change: the refactor is behavior-preserving.

- uw_public_surface.json: str(inspect.signature) for every public fetch_*, plus
  the non-fetch names callers import through `uw` (UwClient, EndpointSlug,
  _fetch_json).
- uw_fetch_requests.json: for each case below, the (slug, ticker, params,
  option_symbol, run_id) the client received and the memo reads/writes. This
  pins REQUEST SHAPE only; a normalizer raising on the empty test body is
  ignored here (normalization is the recorded-fixture suite's job).

Regenerate (only on purpose): UW_SURFACE_REGEN=1 uv run pytest <this file>.
"""

from __future__ import annotations

import inspect
import json
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from uw_scan.sources import uw

FIXTURES = Path(__file__).parent / "fixtures"
SURFACE = FIXTURES / "uw_public_surface.json"
REQUESTS = FIXTURES / "uw_fetch_requests.json"
REGEN = os.environ.get("UW_SURFACE_REGEN") == "1"

MD = date(2026, 9, 1)
T = "AAPL"
EXP = "2026-11-20"

# name -> list of (positional args after client/repo/run_id, kwargs)
CASES: dict[str, list[tuple[tuple, dict]]] = {
    "fetch_flow_alerts": [((T,), {}), ((T,), {"limit": 7})],
    "fetch_market_flow_alerts": [((), {}), ((), {"limit": 9})],
    "fetch_iv_rank": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_volatility_stats": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_realized_volatility": [((T,), {})],
    "fetch_term_structure": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_interpolated_iv": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_skew": [((T, EXP), {}), ((T, EXP), {"delta": 10})],
    "fetch_greek_exposure": [((T, EXP), {}), ((T, EXP), {"market_date": MD})],
    "fetch_greek_exposure_by_expiry": [
        ((T,), {}),
        ((T,), {"date": "2026-08-31"}),
        ((T,), {"market_date": MD}),
        ((T,), {"force_refresh": True}),
    ],
    "fetch_greek_exposure_by_strike": [((T,), {})],
    "fetch_greek_exposure_history": [((T,), {}), ((T,), {"timeframe": "1Y"})],
    "fetch_stock_state": [((T,), {})],
    "fetch_spot_exposures": [((T, EXP), {}), ((T, EXP), {"market_date": MD})],
    "fetch_greeks": [((T, EXP), {}), ((T, EXP), {"date": "2026-08-31"})],
    "fetch_oi_per_strike": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_oi_change": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_max_pain": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_option_contracts": [
        ((T,), {}),
        ((T,), {"limit": 50}),
        ((T,), {"market_date": MD}),
        ((T,), {"force_refresh": True}),
    ],
    "fetch_option_contracts_by_symbol": [
        ((T, ["AAPL261120C00200000", "AAPL261120P00180000"]), {})
    ],
    "fetch_option_contracts_by_expiry": [((T, EXP), {})],
    "fetch_option_contract_intraday": [(("AAPL261120C00200000", "2026-08-31"), {})],
    "fetch_options_volume_daily": [((T,), {}), ((T,), {"limit": 5})],
    "fetch_darkpool_ticker": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_short_data": [((T,), {})],
    "fetch_bulk_screener": [
        ((), {}),
        ((), {"is_s_p_500": "false", "limit": 5, "sector": "Technology"}),
    ],
    "fetch_bulk_screener_ticker": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_etf_info": [(("SPY",), {})],
    "fetch_etf_in_outflow": [
        (("SPY",), {"start_date": "2026-08-01", "end_date": "2026-08-31"})
    ],
    "fetch_short_interest_float": [((T,), {})],
    "fetch_analyst_ratings": [((T,), {})],
    "fetch_institution_ownership": [((T,), {})],
    "fetch_insider_ticker_flow": [((T,), {})],
    "fetch_earnings_history": [((T,), {})],
    "fetch_market_tide": [((), {}), ((), {"trading_date": MD})],
    "fetch_top_net_impact": [((), {}), ((), {"trading_date": MD, "limit": 10})],
    "fetch_economic_calendar": [((), {})],
    "fetch_gex_levels": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_volatility_anomaly": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_volatility_character": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_volatility_vrp": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_net_prem_ticks": [
        ((T,), {}),
        ((T,), {"market_date": MD, "limit": 20}),
    ],
    "fetch_greek_flow": [((T,), {}), ((T,), {"market_date": MD})],
    "fetch_lit_flow": [((T,), {}), ((T,), {"market_date": MD, "limit": 20})],
    "fetch_darkpool_prints": [
        ((T,), {}),
        ((T,), {"market_date": MD, "limit": 20}),
    ],
    "fetch_ftds": [((T,), {})],
    "fetch_volumes_by_exchange": [((T,), {})],
    "fetch_short_interest_history": [((T,), {})],
}

_EXTRA_NAMES = ("UwClient", "EndpointSlug", "_fetch_json")


def _public_fetchers() -> list[str]:
    return sorted(
        n for n in dir(uw) if n.startswith("fetch_") and callable(getattr(uw, n))
    )


def _surface() -> dict:
    return {
        "fetchers": {
            n: str(inspect.signature(getattr(uw, n))) for n in _public_fetchers()
        },
        "extra_names": [n for n in _EXTRA_NAMES if hasattr(uw, n)],
    }


class _Client:
    def __init__(self, log: list) -> None:
        self.log = log
        self.rate_limit = SimpleNamespace(
            daily_count=None, minute_remaining=None, minute_reset=None
        )

    def get(self, slug, *, ticker=None, params=None, run_id=None, option_symbol=None):
        self.log.append(
            {
                "call": "get",
                "slug": str(slug),
                "ticker": ticker,
                "params": params,
                "run_id": run_id,
                "option_symbol": option_symbol,
            }
        )
        return SimpleNamespace(status_code=200, json=lambda: {"data": []}), {}


class _Repo:
    _schema = "uw_scan"
    schema = "uw_scan"
    conn = object()

    def insert_audit_row(self, **_k):
        return 1

    def insert_raw_payload(self, *_a):
        return None


def _capture(monkeypatch) -> dict:
    out: dict[str, list] = {}
    for name, cases in CASES.items():
        out[name] = []
        for args, kwargs in cases:
            log: list = []

            class _Memo:
                def __init__(self, _conn, schema=None):
                    log.append({"call": "memo_init", "schema": schema})

                def get(self, ticker, label, as_of):
                    log.append({"call": "memo_get", "ticker": ticker, "label": label})
                    return None

                def put(self, ticker, label, as_of, body):
                    log.append({"call": "memo_put", "ticker": ticker, "label": label})

            monkeypatch.setattr(uw, "UwFetchMemoRepository", _Memo)
            try:
                getattr(uw, name)(_Client(log), _Repo(), 1, *args, **kwargs)
            except Exception:  # noqa: BLE001 -- request shape only, see docstring
                pass
            out[name].append(json.loads(json.dumps(log, default=str)))
    return out


def test_public_surface_unchanged():
    got = _surface()
    if REGEN:
        FIXTURES.mkdir(exist_ok=True)
        SURFACE.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    assert got == json.loads(SURFACE.read_text())


def test_every_public_fetcher_has_a_request_case():
    assert sorted(CASES) == _public_fetchers()


def test_requests_unchanged(monkeypatch):
    got = _capture(monkeypatch)
    if REGEN:
        REQUESTS.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    want = json.loads(REQUESTS.read_text())
    for name in sorted(want):
        assert got[name] == want[name], name


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_case_reaches_the_client(name, monkeypatch):
    """Non-vacuity: each case really issued a request (a raise before the
    client call would otherwise capture an empty log on both sides)."""
    got = json.loads(REQUESTS.read_text())[name]
    assert all(any(e["call"] == "get" for e in case) for case in got), name
