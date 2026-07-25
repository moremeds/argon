from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import (
    DarkLitPrint,
    GexLevelsRow,
    VolAnomalyRow,
    VolVrpRow,
)


def test_gex_levels_row_parses_decimals():
    r = GexLevelsRow(
        market_date=date(2026, 6, 30),
        ticker="AAPL",
        call_wall="210.5",
        put_wall="190",
        gamma_flip="200",
        gamma_magnet="205",
    )
    assert r.call_wall == Decimal("210.5")
    assert r.ticker == "AAPL"
    assert r.spot is None  # absent from the gex-levels payload


def test_vol_anomaly_row_optional_fields():
    r = VolAnomalyRow(date=date(2026, 6, 30), direction="up", score="1.2")
    assert r.score == Decimal("1.2")


def test_vol_vrp_row_ignores_extra_keys():
    # real vrp rows carry extra `ticker`/`created_at` keys -> extra="ignore"
    r = VolVrpRow(
        date=date(2026, 6, 30),
        ticker="AAPL",
        created_at="x",
        rank="0.4",
        risk_premium="0.02",
    )
    assert r.rank == Decimal("0.4")


def test_dark_lit_print_sale_cond_codes_is_list():
    r = DarkLitPrint(
        tracking_id="T1",
        ticker="AAPL",
        executed_at=datetime(2026, 6, 30, 14, tzinfo=timezone.utc),
        sale_cond_codes=["@", "F"],
    )
    assert r.sale_cond_codes == ["@", "F"]
    assert r.nbbo_bid is None
