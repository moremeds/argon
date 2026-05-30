"""Unit tests for the M6 framework payload sections in analysis_input.

Asserts the bounded sections (positioning, fundamentals, macro, flow_series,
tape) are present and na-tolerant: absent inputs produce {"available": False}
(not omitted, not fabricated); present inputs surface typed fields + freshness.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.reports.trade_blast.analysis_input import (
    build_trade_insights_ai_analysis_input,
)


def _base_kwargs() -> dict:
    return dict(
        ticker="NVDA",
        run_id=1,
        trade_insights_input_hash="hash",
        trade_insights_payload={},
        stock_report_payload={},
        stock_history_payload={"rows": []},
        volatility_series_payload={},
    )


def test_sections_present_and_na_when_inputs_absent():
    payload = build_trade_insights_ai_analysis_input(**_base_kwargs())
    for key in ("positioning", "fundamentals", "macro", "flow_series", "tape"):
        assert key in payload, f"{key} section missing"
    assert payload["positioning"] == {"available": False}
    assert payload["fundamentals"] == {"available": False}
    assert payload["macro"] == {"available": False}
    assert payload["flow_series"] == {"available": False}
    # tape is always present (derived), but with no rows it's unavailable
    assert payload["tape"]["available"] is False
    assert payload["tape"]["bars"] == 0


def test_positioning_section_surfaces_fields_and_freshness():
    today = datetime.now(timezone.utc).date()
    positioning = {
        "snapshot_date": today,
        "si_pct_float": Decimal("0.07"),
        "analyst_buy": 12,
        "analyst_hold": 3,
        "analyst_sell": 1,
        "inst_total_value": Decimal("1000"),
        "insider_net_flow": Decimal("500"),
        "earn_reactions_positive": 3,
        "earn_reactions_total": 4,
        "next_er_date": today + timedelta(days=20),
        "raw_jsonb": {"big": "blob"},  # must NOT leak into the section
    }
    payload = build_trade_insights_ai_analysis_input(
        **_base_kwargs(), positioning_payload=positioning
    )
    sec = payload["positioning"]
    assert sec["available"] is True
    assert sec["stale"] is False
    assert sec["age_days"] == 0
    assert sec["si_pct_float"] == Decimal("0.07")
    assert sec["analyst_buy"] == 12
    assert "raw_jsonb" not in sec  # selected fields only


def test_positioning_marked_stale_when_old():
    old = datetime.now(timezone.utc).date() - timedelta(days=30)
    payload = build_trade_insights_ai_analysis_input(
        **_base_kwargs(), positioning_payload={"snapshot_date": old}
    )
    assert payload["positioning"]["stale"] is True
    assert payload["positioning"]["age_days"] == 30


def test_fundamentals_section_and_stale_ttl():
    recent = datetime.now(timezone.utc).date() - timedelta(days=10)
    payload = build_trade_insights_ai_analysis_input(
        **_base_kwargs(),
        fundamentals_payload={
            "period_end": recent,
            "revenue": Decimal("500"),
            "gross_margin": Decimal("0.6"),
            "fcf": Decimal("110"),
        },
    )
    sec = payload["fundamentals"]
    assert sec["available"] is True
    assert sec["stale"] is False  # 10d < 100d
    assert sec["revenue"] == Decimal("500")

    very_old = datetime.now(timezone.utc).date() - timedelta(days=200)
    payload2 = build_trade_insights_ai_analysis_input(
        **_base_kwargs(), fundamentals_payload={"period_end": very_old}
    )
    assert payload2["fundamentals"]["stale"] is True


def test_tape_section_derived_from_ohlcv_rows():
    rows = [
        {
            "date": date(2026, 1, 1),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
        },
        {
            "date": date(2026, 1, 2),
            "open": 10,
            "high": 12,
            "low": 10,
            "close": 11,
            "volume": 100,
        },
        {
            "date": date(2026, 1, 3),
            "open": 11,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 100,
        },
    ]
    payload = build_trade_insights_ai_analysis_input(**_base_kwargs(), ohlcv_rows=rows)
    tape = payload["tape"]
    assert tape["available"] is True
    assert tape["latest_close"] == Decimal("12")
    assert tape["trend_3close"] == "up"


def test_next_er_date_falls_back_to_positioning():
    rows = [
        {
            "date": date(2026, 1, 1),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 100,
        },
        {
            "date": date(2026, 1, 2),
            "open": 10,
            "high": 12,
            "low": 10,
            "close": 11,
            "volume": 100,
        },
        {
            "date": date(2026, 1, 3),
            "open": 11,
            "high": 13,
            "low": 11,
            "close": 12,
            "volume": 100,
        },
    ]
    payload = build_trade_insights_ai_analysis_input(
        **_base_kwargs(),
        ohlcv_rows=rows,
        positioning_payload={
            "snapshot_date": date(2026, 1, 3),
            "next_er_date": date(2026, 1, 13),
        },
    )
    # latest bar 2026-01-03 → earnings 2026-01-13 = 10 days
    assert payload["tape"]["days_to_earnings"] == 10


def test_macro_and_flow_series_passthrough():
    today = datetime.now(timezone.utc).date()
    payload = build_trade_insights_ai_analysis_input(
        **_base_kwargs(),
        macro_payload={"as_of": today, "vix": Decimal("18.5")},
        flow_series_payload={"net_call_premium_3d": Decimal("1000"), "persistence": 3},
    )
    assert payload["macro"]["available"] is True
    assert payload["macro"]["vix"] == Decimal("18.5")
    assert payload["macro"]["stale"] is False
    assert payload["flow_series"]["available"] is True
    assert payload["flow_series"]["persistence"] == 3
