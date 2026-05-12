"""Quick live smoke test — hits the real UW API for one endpoint.

Gated by `@pytest.mark.live` AND `UW_SCAN_API_KEY` being set. CI runs this only
in a dedicated `live` job, never on PRs.
"""

from __future__ import annotations

import os

import pytest

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("UW_SCAN_API_KEY", "").strip(),
        reason="UW_SCAN_API_KEY not set",
    ),
]


def test_flow_alerts_returns_200_with_data():
    api_key = os.environ["UW_SCAN_API_KEY"]
    with UwClient(api_key=api_key) as client:
        resp, headers = client.get(
            EndpointSlug.FLOW_ALERTS,
            params={"ticker_symbol": "TSLA", "limit": 10},
        )
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, dict)
    assert "data" in payload
    assert isinstance(payload["data"], list)
    # UW-specific rate-limit headers must be present
    assert "x-uw-token-req-limit" in headers
