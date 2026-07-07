"""Pure P&L math for the VRP-macro trade-lifecycle assembler (#223)."""

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.reports.vrp_lifecycle import (
    build_position_detail,
    build_positions_response,
)


def _header(**over):
    kw = dict(
        entry_id=1,
        name="SPX",
        origin="auto",
        birth_date=date(2026, 6, 24),
        born_at=datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc),
        expiry=date(2026, 8, 7),
        hold_days=30,
        action_at_birth="TRADE",
        vrp_z_at_birth=Decimal("0.6"),
        weight_at_birth=Decimal("1.0"),
        spot_at_birth=Decimal("6000"),
        short_strike_above=Decimal("5800"),
        short_strike_below=Decimal("5790"),
        wing_strike_above=Decimal("5600"),
        wing_strike_below=Decimal("5590"),
        # first mark: credit = 12.2 - 4.2 = 8.0
        entry_short_mid=Decimal("12.2"),
        entry_wing_mid=Decimal("4.2"),
        first_as_of=datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc),
        # last mark: value = 6.0 - 2.0 = 4.0 -> pnl = 8.0 - 4.0 = 4.0
        last_short_mid=Decimal("6.0"),
        last_wing_mid=Decimal("2.0"),
        last_as_of=datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc),
        last_spot=Decimal("6050"),
        n_marks=12,
    )
    kw.update(over)
    return kw


def test_open_position_pnl_and_ror():
    today = date(2026, 7, 5)
    resp = build_positions_response([_header()], today=today)
    assert resp.open_count == 1
    p = resp.positions[0]
    assert p.status == "open"
    assert p.dte == (date(2026, 8, 7) - today).days == 33
    assert p.days_held == 11
    assert p.width == Decimal("200")  # 5800 - 5600
    assert p.entry_credit == Decimal("8.0")
    assert p.current_value == Decimal("4.0")
    assert p.unrealized_pnl == Decimal("4.0")
    assert p.max_loss == Decimal("192.0")  # width 200 - credit 8
    # ror = 4 / 192
    assert p.return_on_risk == Decimal("4.0") / Decimal("192.0")
    assert resp.total_unrealized_pnl == Decimal("4.0")


def test_expired_status_and_excluded_from_open_total():
    today = date(2026, 8, 10)  # past expiry 2026-08-07
    resp = build_positions_response([_header()], today=today)
    assert resp.open_count == 0
    assert resp.positions[0].status == "expired"
    assert resp.positions[0].dte < 0
    # no open positions -> None total (not a misleading 0)
    assert resp.total_unrealized_pnl is None


def test_missing_nbbo_side_yields_none_credit_not_fabricated():
    # wing bid/ask absent at capture -> mid None -> credit/pnl None
    resp = build_positions_response(
        [_header(entry_wing_mid=None, last_wing_mid=None)], today=date(2026, 7, 5)
    )
    p = resp.positions[0]
    assert p.entry_credit is None
    assert p.unrealized_pnl is None
    assert p.return_on_risk is None


def test_detail_pnl_series_running_curve():
    series = [
        {
            "as_of": datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc),
            "short_mid": Decimal("12.2"),
            "wing_mid": Decimal("4.2"),
            "und_spot": Decimal("6000"),
            "session": "rth",
        },
        {
            "as_of": datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc),
            "short_mid": Decimal("6.0"),
            "wing_mid": Decimal("2.0"),
            "und_spot": Decimal("6050"),
            "session": "eod",
        },
    ]
    detail = build_position_detail(_header(), series, today=date(2026, 7, 5))
    assert len(detail.pnl_series) == 2
    # at birth: value == credit -> pnl 0
    assert detail.pnl_series[0].current_value == Decimal("8.0")
    assert detail.pnl_series[0].unrealized_pnl == Decimal("0.0")
    # later: value 4.0 -> pnl 4.0
    assert detail.pnl_series[1].unrealized_pnl == Decimal("4.0")
