"""Live smoke tests for Flow Tab Merge fetchers (spec 2026-05-13).

Gated by ``@pytest.mark.live`` AND ``UW_SCAN_API_KEY``. Don't run on PRs.
"""

from __future__ import annotations

import os

import pytest

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.normalize import normalize_options_volume_daily

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("UW_SCAN_API_KEY", "").strip(),
        reason="UW_SCAN_API_KEY not set",
    ),
]


def test_options_volume_daily_returns_typed_rows() -> None:
    api_key = os.environ["UW_SCAN_API_KEY"]
    with UwClient(api_key=api_key) as client:
        resp, _ = client.get(
            EndpointSlug.OPTIONS_VOLUME_DAILY,
            ticker="GOOGL",
            params={"limit": 20},
        )
    assert resp.status_code == 200
    rows = normalize_options_volume_daily(resp.json())
    assert len(rows) > 0
    first = rows[0]
    assert first.call_volume is not None
    # 30-day average present per UW contract.
    assert first.avg_30_day_call_volume is not None


def test_option_contracts_returns_full_cap() -> None:
    """Pre-flight probe confirmed UW caps option-contracts at 500 rows. Lock that in."""
    api_key = os.environ["UW_SCAN_API_KEY"]
    with UwClient(api_key=api_key) as client:
        resp, _ = client.get(
            EndpointSlug.OPTION_CONTRACTS,
            ticker="SPY",
            params={"limit": 500},
        )
    assert resp.status_code == 200
    data = resp.json().get("data", [])
    assert len(data) == 500
