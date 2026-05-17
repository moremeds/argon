"""WGC monthly CB reserves parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.cards.cb_buckets import classify_bucket
from uw_scan.sources.wgc_cb import WgcCbProvider

SAMPLE = """Country,Month,Tonnes,Reported,Estimated
China,2026-04,2235.0,true,false
India,2026-04,876.4,true,false
Russia,2026-04,2330.5,false,true
Poland,2026-04,420.3,true,false
"""


def _fake_response() -> httpx.Response:
    return httpx.Response(
        200,
        text=SAMPLE,
        request=httpx.Request("GET", WgcCbProvider.URL),
    )


def test_wgc_parses_monthly_csv():
    with patch.object(WgcCbProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with WgcCbProvider() as p:
            rows = p.fetch_monthly(start=date(2026, 4, 1))
    by_country = {r.country_iso3: r for r in rows}
    assert by_country["CHN"].reserves_t == Decimal("2235.0")
    assert by_country["CHN"].obs_month == date(2026, 4, 1)
    assert by_country["RUS"].is_reported is False
    assert by_country["RUS"].is_estimated is True
    assert by_country["POL"].bucket == "reserve_diversifier"
    assert by_country["CHN"].bucket == "strategic_accumulator"


def test_classify_bucket_defaults():
    assert classify_bucket("CHN") == "strategic_accumulator"
    assert classify_bucket("EGY") == "tactical_defender"
    assert classify_bucket("POL") == "reserve_diversifier"
    assert classify_bucket("USA") == "reserve_diversifier"  # safe default
