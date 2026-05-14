from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from uw_scan.api.routers.stock import _with_latest_spot
from uw_scan.models import (
    FlowSnapshot,
    MarketStructure,
    SingleStockReport,
    VolatilityProfile,
    VRPAssessment,
)
from uw_scan.storage.repository import IntradayQuoteRow


def _report() -> SingleStockReport:
    return SingleStockReport(
        run_id=1,
        ticker="TSLA",
        generated_at=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        market_structure=MarketStructure(spot=Decimal("100")),
        volatility=VolatilityProfile(),
        flow=FlowSnapshot(
            ticker="TSLA",
            flow_count=0,
            net_premium=Decimal("0"),
            bull_premium=Decimal("0"),
            bear_premium=Decimal("0"),
            ask_side_premium=Decimal("0"),
            bid_side_premium=Decimal("0"),
        ),
        vrp=VRPAssessment(vrp=None, signal="neutral", note=""),
    )


def test_with_latest_spot_prefers_newer_intraday_quote() -> None:
    repo = SimpleNamespace(
        get_watchlist_card=lambda _ticker: SimpleNamespace(
            spot=Decimal("101"),
            spot_quoted_at=datetime(2026, 5, 13, 20, 5, tzinfo=timezone.utc),
            spot_source="massive.com_intraday",
        ),
        get_intraday_quote=lambda _ticker: IntradayQuoteRow(
            ticker="TSLA",
            price=Decimal("102"),
            quoted_at=datetime(2026, 5, 13, 20, 10, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 5, 13, 20, 11, tzinfo=timezone.utc),
        ),
    )

    report = _with_latest_spot(_report(), repo)

    assert report.market_structure.spot == Decimal("102")
    assert report.spot_quoted_at == datetime(2026, 5, 13, 20, 10, tzinfo=timezone.utc)
    assert report.spot_source == "massive.com_intraday"
