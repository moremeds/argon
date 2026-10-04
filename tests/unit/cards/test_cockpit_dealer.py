"""Pure cockpit dealer compute, fed hand-built rows shaped like the storage fetches.

The dealer-metric scenarios mirror tests/integration/api/test_cockpit_endpoint.py
(same seeded rows, same asserted values), minus the database.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.cards.cockpit_dealer import (
    compute_cockpit_dealer_metrics,
    flow_color_summary,
    oi_change_bias,
    vanna_conditional_reading,
)

MARKET_DATE = date(2026, 5, 15)
NO_FLOW = flow_color_summary([])


def _compute(**overrides):
    rows = {
        "greeks_rows": [],
        "exposure_rows": [],
        "chain_rows": [],
        "iv_rows": [],
        "rv_rows": [],
        "flow": NO_FLOW,
        "iv_rows_90d": [],
        "oi_change_rows": [],
    }
    rows.update(overrides)
    return compute_cockpit_dealer_metrics(market_date=MARKET_DATE, **rows)


def test_source_only_scenario_matches_endpoint_assertions() -> None:
    # Mirrors test_cockpit_tabs_use_source_date_without_state_snapshot (QQQ).
    iv_rows = [
        {"market_date": date(2026, 5, 10), "volatility": Decimal("0.30")},
        {"market_date": MARKET_DATE, "volatility": Decimal("0.20")},
    ]
    metrics = _compute(
        greeks_rows=[
            {
                "expiry": date(2026, 5, 16),
                "strike": Decimal("500"),
                "call_vanna": Decimal("1"),
                "put_vanna": Decimal("-2"),
                "call_charm": Decimal("3"),
                "put_charm": Decimal("-4"),
            }
        ],
        exposure_rows=[
            {
                "expiry": date(2026, 5, 16),
                "strike": Decimal("500"),
                "call_gex": Decimal("7"),
                "put_gex": Decimal("-2"),
                "call_vanna": Decimal("10"),
                "put_vanna": Decimal("-20"),
                "call_charm": Decimal("30"),
                "put_charm": Decimal("-40"),
            }
        ],
        chain_rows=[
            {
                "snapshot_date": MARKET_DATE,
                "expiry": date(2026, 5, 16),
                "strike": Decimal("500"),
                "call_oi": 100,
                "put_oi": 50,
            }
        ],
        iv_rows=iv_rows,
        rv_rows=[{"market_date": MARKET_DATE, "price": Decimal("500")}],
        flow=flow_color_summary(
            [
                ("put", Decimal("1000"), Decimal(0), Decimal(0)),
                ("call", Decimal("500"), Decimal(0), Decimal(0)),
            ]
        ),
        iv_rows_90d=iv_rows,
    )

    assert metrics.pin_candidate_strike == Decimal("500")
    assert metrics.pin_candidate_expiry == date(2026, 5, 16)
    assert metrics.pin_distance_sigma == Decimal("0")
    assert metrics.pin_regime_flag is True
    assert metrics.dealer_net_vanna_proxy == Decimal("20000")
    assert metrics.dealer_net_charm_proxy == Decimal("50000")
    assert metrics.flow_color_lookback_3d == "put_heavy"
    assert metrics.directional_imbalance_3d == Decimal("-500")
    assert metrics.vanna_conditional_reading == "grind_up"
    assert metrics.flow_put_premium_3d == Decimal("1000")
    assert metrics.flow_call_premium_3d == Decimal("500")
    assert metrics.iv_30d_delta_5d == Decimal("-0.10")
    assert metrics.net_gamma == Decimal("5")
    assert metrics.net_gamma_sign == "positive"
    assert metrics.gamma_regime == "long_gamma"
    assert metrics.charm_regime == "opex_vortex"
    assert metrics.charm_stress_override is False


def test_pin_uses_latest_oi_snapshot_and_marks_source_date() -> None:
    # Mirrors test_cockpit_dealer_pin_uses_latest_oi_snapshot_and_marks_source_date.
    iv_rows = [{"market_date": MARKET_DATE, "volatility": Decimal("0.20")}]
    metrics = _compute(
        greeks_rows=[
            {
                "expiry": date(2026, 5, 18),
                "strike": Decimal("500"),
                "call_vanna": Decimal("1"),
                "put_vanna": Decimal("1"),
                "call_charm": Decimal("1"),
                "put_charm": Decimal("1"),
            }
        ],
        chain_rows=[
            {
                "snapshot_date": date(2026, 5, 14),
                "expiry": date(2026, 5, 18),
                "strike": Decimal("500"),
                "call_oi": 1000,
                "put_oi": 1000,
            }
        ],
        iv_rows=iv_rows,
        rv_rows=[{"market_date": MARKET_DATE, "price": Decimal("500")}],
        iv_rows_90d=iv_rows,
    )

    assert metrics.pin_candidate_strike == Decimal("500")
    assert metrics.pin_candidate_expiry == date(2026, 5, 18)
    assert metrics.pin_source_date == date(2026, 5, 14)
    assert metrics.pin_distance_sigma == Decimal("0")
    assert metrics.pin_regime_flag is False


def test_pin_candidate_excludes_same_day_expiry() -> None:
    # Mirrors test_cockpit_dealer_excludes_same_day_pin_candidate (SPY).
    iv_rows = [{"market_date": MARKET_DATE, "volatility": Decimal("0.20")}]
    metrics = _compute(
        chain_rows=[
            {
                "snapshot_date": MARKET_DATE,
                "expiry": MARKET_DATE,
                "strike": Decimal("500"),
                "call_oi": 1000,
                "put_oi": 1000,
            }
        ],
        iv_rows=iv_rows,
        rv_rows=[{"market_date": MARKET_DATE, "price": Decimal("500")}],
        iv_rows_90d=iv_rows,
    )

    assert metrics.pin_candidate_strike is None
    assert metrics.pin_candidate_expiry is None
    assert metrics.pin_distance_sigma is None
    assert metrics.pin_regime_flag is None


def test_exposure_fallback_without_chain_oi() -> None:
    # Mirrors test_cockpit_dealer_metrics_use_exposure_fallback_without_chain_oi (IWM).
    metrics = _compute(
        greeks_rows=[
            {
                "expiry": date(2026, 5, 16),
                "strike": Decimal("200"),
                "call_vanna": Decimal("1"),
                "put_vanna": Decimal("-2"),
                "call_charm": Decimal("3"),
                "put_charm": Decimal("-4"),
            }
        ],
        exposure_rows=[
            {
                "expiry": date(2026, 5, 16),
                "strike": Decimal("200"),
                "call_gex": Decimal("5"),
                "put_gex": Decimal("-2"),
                "call_vanna": Decimal("15"),
                "put_vanna": Decimal("-5"),
                "call_charm": Decimal("8"),
                "put_charm": Decimal("7"),
            }
        ],
    )

    assert metrics.dealer_net_vanna_proxy == Decimal("10")
    assert metrics.dealer_net_charm_proxy == Decimal("15")
    assert metrics.net_gamma == Decimal("3")
    assert metrics.net_gamma_sign == "positive"


def test_no_rows_yields_empty_metrics() -> None:
    metrics = _compute()

    assert metrics.dealer_net_vanna_proxy is None
    assert metrics.flow_color_lookback_3d is None
    assert metrics.vanna_conditional_reading == "weak_noise"
    assert metrics.vanna_oi_change_bias is None
    assert metrics.charm_regime == "neutral"


# The branches below have no integration-test counterpart; the expected labels
# follow from the classifier rules themselves.


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], None),
        (
            [{"option_symbol": "SPY260516C00500000", "oi_diff_plain": 300}],
            "call_oi_build",
        ),
        (
            [
                {"option_symbol": "SPY260516C00500000", "oi_diff_plain": 100},
                {"option_symbol": "SPY260516P00500000", "oi_diff_plain": 400},
            ],
            "put_oi_build",
        ),
        (
            [
                {"option_symbol": "SPY260516C00500000", "oi_diff_plain": 200},
                {"option_symbol": "SPY260516P00500000", "oi_diff_plain": 200},
            ],
            "mixed",
        ),
    ],
)
def test_oi_change_bias(rows, expected) -> None:
    assert oi_change_bias(rows) == expected


def test_oi_change_bias_flows_into_metrics() -> None:
    metrics = _compute(
        oi_change_rows=[
            {"option_symbol": "SPY260516P00500000", "oi_diff_plain": 50},
        ]
    )

    assert metrics.vanna_oi_change_bias == "put_oi_build"


@pytest.mark.parametrize(
    ("iv_delta", "imbalance", "color", "gamma_sign", "expected"),
    [
        (None, Decimal("-1"), "put_heavy", "positive", "weak_noise"),
        (Decimal("-0.1"), Decimal("-1"), "put_heavy", None, "weak_noise"),
        (Decimal("-0.1"), None, "put_heavy", "positive", "grind_up"),
        (Decimal("-0.1"), None, "call_heavy", "positive", "reverse_selloff"),
        (Decimal("0.1"), Decimal("-1"), None, "negative", "reflexive_sell_pressure"),
        (Decimal("0.1"), Decimal("1"), "call_heavy", "negative", "weak_noise"),
    ],
)
def test_vanna_conditional_reading(
    iv_delta, imbalance, color, gamma_sign, expected
) -> None:
    assert (
        vanna_conditional_reading(
            iv_30d_delta_5d=iv_delta,
            directional_imbalance_3d=imbalance,
            flow_color=color,
            net_gamma_sign=gamma_sign,
        )
        == expected
    )
