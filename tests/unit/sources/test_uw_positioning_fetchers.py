"""Unit tests for the M4 UW positioning normalizers + fetchers.

No sample JSON exists under docs/uw-samples/ for these five endpoints, so the
payloads below are SPEC-DERIVED synthetic fixtures: every field name + value
shape is taken from docs/uw-samples/unusual_whales_api_spec.yaml (enums:
recommendation=buy|hold|sell, buy_sell=buy|sell; premiums/moves are decimal
strings; short-interest `data` is an object). They are not recorded responses.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.normalize import (
    NormalizationError,
    normalize_analyst_ratings,
    normalize_earnings_history,
    normalize_insider_ticker_flow,
    normalize_institution_ownership,
    normalize_short_interest_float,
)
from uw_scan.sources.uw import (
    fetch_analyst_ratings,
    fetch_short_interest_float,
)

# --------------------------------------------------------------------------- #
# Spec-derived synthetic payloads
# --------------------------------------------------------------------------- #
SHORT_INTEREST = {
    "data": [
        {
            "si_float": "0.0734",
            "short_interest": 175611155,
            "total_float": 2392000000,
            "days_to_cover": "1.205",
            "short_shares_available": 12000000,
            "fee_rate": "0.51",
            "rebate_rate": "4.25",
            "market_date": "2026-05-15",
            "symbol": "NVDA",
        },
        {
            # older snapshot — must be ignored; latest-first ordering
            "si_float": "0.0500",
            "short_interest": 100000000,
            "total_float": 2392000000,
            "days_to_cover": "0.800",
            "short_shares_available": 12000000,
            "fee_rate": "0.30",
            "rebate_rate": "4.00",
            "market_date": "2026-04-30",
            "symbol": "NVDA",
        },
    ]
}

ANALYST = {
    "data": [
        {"recommendation": "buy", "target": "420.0", "firm": "Citi"},
        {"recommendation": "Buy", "target": "440.0", "firm": "MS"},
        {"recommendation": "hold", "target": "300.0", "firm": "BofA"},
        {"recommendation": "sell", "target": "200.0", "firm": "X"},
    ]
}

INSTITUTION = {
    "data": [
        {"name": "VANGUARD GROUP INC", "inst_value": "1095205923.0", "units": 8000000},
        {"name": "BLACKROCK INC", "inst_value": "900000000.0", "units": 7000000},
    ]
}

INSIDER = {
    "data": [
        {
            "buy_sell": "buy",
            "premium": "664386",
            "volume": 244331,
            "date": "2024-12-12",
        },
        {
            "buy_sell": "sell",
            "premium": "100000",
            "volume": 50000,
            "date": "2024-12-12",
        },
    ]
}

EARNINGS = {
    "data": [
        {"report_date": "2024-11-10", "post_earnings_move_1d": "0.0724"},
        {"report_date": "2024-08-02", "post_earnings_move_1d": "-0.02"},
        {"report_date": "2024-05-01", "post_earnings_move_1d": "0.05"},
        {"report_date": "2024-02-01", "post_earnings_move_1d": "0.03"},
        {"report_date": "2023-11-01", "post_earnings_move_1d": "-0.10"},
    ]
}


# --------------------------------------------------------------------------- #
# Normalizers
# --------------------------------------------------------------------------- #
def test_normalize_short_interest_float():
    out = normalize_short_interest_float(SHORT_INTEREST)
    assert out["si_pct_float"] == Decimal("0.0734")
    assert out["si_short_interest"] == Decimal("175611155")
    assert out["si_total_float"] == Decimal("2392000000")
    assert out["si_days_to_cover"] == Decimal("1.205")
    assert out["si_shares_available"] == Decimal("12000000")
    assert out["si_fee_rate"] == Decimal("0.51")
    assert out["si_rebate_rate"] == Decimal("4.25")
    assert out["si_market_date"] == date(2026, 5, 15)


def test_normalize_analyst_ratings_buckets_and_targets():
    out = normalize_analyst_ratings(ANALYST)
    assert out["analyst_buy"] == 2  # "buy" + "Buy" (case-insensitive)
    assert out["analyst_hold"] == 1
    assert out["analyst_sell"] == 1
    assert out["analyst_target_avg"] == Decimal("340")  # (420+440+300+200)/4
    assert out["analyst_target_hi"] == Decimal("440.0")
    assert out["analyst_target_lo"] == Decimal("200.0")


def test_normalize_institution_ownership_count_and_total():
    out = normalize_institution_ownership(INSTITUTION)
    assert out["inst_holder_count"] == 2
    assert out["inst_total_value"] == Decimal("1995205923.0")


def test_normalize_insider_ticker_flow_volume_and_net():
    out = normalize_insider_ticker_flow(INSIDER)
    assert out["insider_buy_volume"] == Decimal("244331")
    assert out["insider_sell_volume"] == Decimal("50000")
    assert out["insider_net_flow"] == Decimal("564386")  # 664386 - 100000


def test_normalize_earnings_history_recent_four():
    out = normalize_earnings_history(EARNINGS)
    # most recent 4 reports: +0.0724, -0.02, +0.05, +0.03 → 3 positive of 4
    assert out["earn_reactions_positive"] == 3
    assert out["earn_reactions_total"] == 4


def test_normalize_empty_arrays_return_na():
    assert normalize_institution_ownership({"data": []})["inst_holder_count"] is None
    assert normalize_insider_ticker_flow({"data": []})["insider_net_flow"] is None
    assert normalize_earnings_history({"data": []})["earn_reactions_total"] is None


def test_normalize_raises_on_missing_data_key():
    with pytest.raises(NormalizationError):
        normalize_analyst_ratings({"oops": []})
    with pytest.raises(NormalizationError):
        normalize_short_interest_float({"oops": {}})


def test_normalize_short_interest_takes_latest_from_list():
    """UW returns a list of historical snapshots ordered most-recent-first;
    the normalizer must take the first entry, not raise."""
    out = normalize_short_interest_float(SHORT_INTEREST)
    # market_date from the FIRST list entry; second entry's 2026-04-30 is ignored
    assert out["si_market_date"] == date(2026, 5, 15)
    assert out["si_pct_float"] == Decimal("0.0734")


def test_normalize_short_interest_empty_list_yields_nones():
    out = normalize_short_interest_float({"data": []})
    assert out["si_pct_float"] is None
    assert out["si_market_date"] is None


def test_normalize_short_interest_rejects_non_dict_first_element():
    """A malformed payload like `{data: [1, 2, 3]}` must raise rather than
    AttributeError out on `int.get(...)`."""
    with pytest.raises(NormalizationError):
        normalize_short_interest_float({"data": [1, 2, 3]})


def test_insights_assembler_rejects_blast_only_kwargs():
    """Locks the PR's TypeError claim: passing blast-only kwargs to the
    insights-lane assembler MUST raise — the conditional `extra_kwargs`
    gate in trade_insights.py:339 is load-bearing, not aesthetic."""
    from uw_scan.reports.trade_insights_ai import (
        build_trade_insights_ai_analysis_input as insights_build,
    )

    minimal_kwargs = dict(
        ticker="TSLA",
        run_id=1,
        trade_insights_input_hash="x",
        trade_insights_payload={},
        stock_report_payload={},
        stock_history_payload={},
        volatility_series_payload={},
    )
    with pytest.raises(TypeError):
        insights_build(**minimal_kwargs, ohlcv_rows=[])  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# Fetchers — audit-first contract (mirror test_market_flow_alerts.py)
# --------------------------------------------------------------------------- #
class _FakeUwClient:
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
            200, json=self._payload, request=httpx.Request("GET", "https://example/x")
        )
        return resp, {}


class _RecordingRepo:
    def __init__(self) -> None:
        self.audits: list[dict[str, Any]] = []
        self.payloads: list[dict[str, Any]] = []

    def insert_audit_row(
        self,
        *,
        run_id: int,
        endpoint_slug: str,
        endpoint_path: str,
        params: dict[str, Any],
        status_code: int,
        started_at: Any,
        finished_at: Any,
        daily_req_count: int | None = None,
        minute_req_remaining: int | None = None,
        minute_req_reset: Any = None,
        error_message: str | None = None,
    ) -> int:
        self.audits.append({"slug": endpoint_slug, "status_code": status_code})
        return len(self.audits)

    def insert_raw_payload(self, audit_id: int, payload: Any) -> None:
        self.payloads.append({"audit_id": audit_id, "payload": payload})


def test_fetch_short_interest_float_audit_first_and_typed():
    client = _FakeUwClient(SHORT_INTEREST)
    repo = _RecordingRepo()
    out = fetch_short_interest_float(client, repo, run_id=9, ticker="NVDA")
    assert out["si_pct_float"] == Decimal("0.0734")
    assert client.calls[0][0] == EndpointSlug.SHORT_INTEREST_FLOAT
    assert client.calls[0][1] == "NVDA"
    assert len(repo.audits) == 1 and repo.audits[0]["status_code"] == 200
    assert len(repo.payloads) == 1


def test_fetch_analyst_ratings_passes_ticker_as_query_param():
    client = _FakeUwClient(ANALYST)
    repo = _RecordingRepo()
    fetch_analyst_ratings(client, repo, run_id=3, ticker="TSLA")
    slug, ticker, params = client.calls[0]
    assert slug == EndpointSlug.ANALYST_RATINGS
    assert ticker is None  # screener endpoint — ticker rides in params
    assert params == {"ticker": "TSLA"}
