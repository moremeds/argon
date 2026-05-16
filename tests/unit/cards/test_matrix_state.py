from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from uw_scan.cards.matrix_state import (
    MatrixInputs,
    _implied_move_expected_abs,
    _joined_vrp_series,
    _latest_rv_30d,
    _latest_spot,
    _nearest_high_oi_strike,
    _term_metrics,
    _vrp_values,
    build_matrix_state_from_inputs,
)

BASE_DAY = date(2026, 5, 15)


@pytest.mark.parametrize(
    ("name", "inputs", "expected_tier", "expected_cluster", "expected_vrp"),
    [
        (
            "example_1_happy_path_strict",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="vol_down",
                charm_state="vol_down",
                skew_state="vol_down",
                term_state="vol_down",
                vrp_state="vol_down",
                skew_25d_zscore_180d=Decimal("1.4"),
                vrp_zscore_60d=Decimal("0.7"),
                vrp_sign_flip_status=False,
                vrp_sign_flip_aligned_days=30,
            ),
            "strict",
            True,
            "vol_down",
        ),
        (
            "example_2_empty_greeks_day",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="stale",
                charm_state="stale",
                skew_state="neutral",
                term_state="vol_down",
                vrp_state="vol_down",
                vrp_sign_flip_status=False,
                vrp_sign_flip_aligned_days=30,
            ),
            "insufficient_data",
            False,
            "vol_down",
        ),
        (
            "example_3_vrp_sign_flip_downgrades_strong_to_weak",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="vol_down",
                charm_state="vol_down",
                skew_state="vol_down",
                term_state="vol_down",
                vrp_state="neutral",
                vrp_zscore_60d=Decimal("0.2"),
                vrp_sign_flip_status=True,
                vrp_sign_flip_aligned_days=30,
            ),
            "weak",
            True,
            "vol_up",
        ),
        (
            "example_4_vrp_sign_flip_insufficient_history",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="vol_down",
                charm_state="vol_down",
                skew_state="vol_down",
                term_state="vol_down",
                vrp_state="neutral",
                vrp_zscore_60d=Decimal("0.2"),
                vrp_sign_flip_status="insufficient_history",
                vrp_sign_flip_aligned_days=25,
            ),
            "strong",
            True,
            "neutral",
        ),
        (
            "example_5_skew_term_stale",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="neutral",
                charm_state="vol_down",
                skew_state="stale",
                term_state="stale",
                vrp_state="vol_down",
                vrp_sign_flip_status=False,
                vrp_sign_flip_aligned_days=30,
            ),
            "insufficient_data",
            True,
            "vol_down",
        ),
        (
            "example_6a_im_only_stale_wins",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="vol_down",
                charm_state="vol_down",
                skew_state="vol_down",
                term_state="vol_down",
                vrp_state="vol_down",
                im_state="neutral",
                flow_state="stale",
                vrp_sign_flip_status=False,
                vrp_sign_flip_aligned_days=30,
            ),
            "strict",
            True,
            "vol_down",
        ),
        (
            "example_6b_im_only_relax_to_fresh_side",
            MatrixInputs(
                ticker="SPY",
                market_date=BASE_DAY,
                vanna_state="vol_down",
                charm_state="vol_down",
                skew_state="vol_down",
                term_state="vol_down",
                vrp_state="vol_down",
                im_state="neutral",
                flow_state="stale",
                dim5_stale_wins=False,
                vrp_sign_flip_status=False,
                vrp_sign_flip_aligned_days=30,
            ),
            "strong",
            True,
            "vol_down",
        ),
    ],
)
def test_golden_examples(
    name: str,
    inputs: MatrixInputs,
    expected_tier: str,
    expected_cluster: bool,
    expected_vrp: str,
) -> None:
    state = build_matrix_state_from_inputs(inputs)

    assert state.consistency_tier == expected_tier, name
    assert state.cluster_coverage_ok is expected_cluster
    assert state.vrp_state == expected_vrp


def test_cluster_coverage_overrides_content_tier() -> None:
    state = build_matrix_state_from_inputs(
        MatrixInputs(
            ticker="SPY",
            market_date=BASE_DAY,
            vanna_state="neutral",
            charm_state="neutral",
            skew_state="vol_down",
            term_state="vol_down",
            vrp_state="vol_down",
            vrp_sign_flip_status=False,
            vrp_sign_flip_aligned_days=30,
        )
    )

    assert state.cluster_coverage_ok is False
    assert state.consistency_tier == "no_trade"


def test_stale_dims_are_excluded_from_denominator() -> None:
    state = build_matrix_state_from_inputs(
        MatrixInputs(
            ticker="SPY",
            market_date=BASE_DAY,
            vanna_state="vol_down",
            charm_state="vol_down",
            skew_state="stale",
            term_state="vol_down",
            vrp_state="vol_down",
            vrp_sign_flip_status=False,
            vrp_sign_flip_aligned_days=30,
        )
    )

    assert state.consistency_tier == "strict"


def test_expected_abs_move_fallback_applies_factor_once() -> None:
    value = _implied_move_expected_abs(
        [{"dte": 7, "implied_move_perc": Decimal("0.08")}],
        atm_straddle_mid=None,
        spot=Decimal("100"),
    )

    assert value == Decimal("0.063832")


def test_term_metrics_materialize_front_back_spread() -> None:
    metrics = _term_metrics(
        [
            {"dte": 7, "volatility": Decimal("0.24")},
            {"dte": 30, "volatility": Decimal("0.30")},
        ]
    )

    assert metrics["front_back_spread"] == Decimal("0.06")


# ---------------------------------------------------------------------------
# Deriver tolerance for UW's staggered freshness:
# realized_volatility lags by ~3 days; interpolated_iv_snapshots is sparse.
# These tests guard the walk-back / fallback semantics added in this branch.
# ---------------------------------------------------------------------------

_RV_ROWS_LATEST_NULL = [
    {
        "market_date": date(2026, 5, 11),
        "price": Decimal("738"),
        "realized_volatility": Decimal("0.10"),
        "implied_volatility": Decimal("0.15"),
    },
    {
        "market_date": date(2026, 5, 12),
        "price": Decimal("740"),
        "realized_volatility": Decimal("0.11"),
        "implied_volatility": Decimal("0.15"),
    },
    {
        "market_date": date(2026, 5, 13),
        "price": Decimal("742"),
        "realized_volatility": None,
        "implied_volatility": Decimal("0.15"),
    },
    {
        "market_date": date(2026, 5, 14),
        "price": Decimal("748"),
        "realized_volatility": None,
        "implied_volatility": Decimal("0.15"),
    },
    {
        "market_date": date(2026, 5, 15),
        "price": Decimal("740"),
        "realized_volatility": None,
        "implied_volatility": Decimal("0.15"),
    },
]


def test_latest_rv_30d_walks_back_when_recent_rv_is_null() -> None:
    # UW returns null RV for the latest ~3 days; deriver must fall back to
    # the most recent non-null at or before market_date.
    assert _latest_rv_30d(_RV_ROWS_LATEST_NULL, date(2026, 5, 15)) == Decimal("0.11")


def test_latest_rv_30d_returns_none_when_all_rows_are_after_market_date() -> None:
    rows = [
        {"market_date": date(2026, 5, 16), "realized_volatility": Decimal("0.12")},
    ]
    assert _latest_rv_30d(rows, date(2026, 5, 15)) is None


def test_latest_spot_walks_back_when_latest_price_missing() -> None:
    rows = [
        {"market_date": date(2026, 5, 13), "price": Decimal("742")},
        {"market_date": date(2026, 5, 14), "price": None},
        {"market_date": date(2026, 5, 15), "price": None},
    ]
    assert _latest_spot(rows, date(2026, 5, 15)) == Decimal("742")


def test_joined_vrp_series_falls_back_to_rv_rows_implied_volatility() -> None:
    # interpolated_iv_snapshots only carries the latest 4 dates; for older
    # dates the deriver must use realized_volatility_history.implied_volatility.
    iv_rows = [
        {"market_date": date(2026, 5, 14), "volatility": Decimal("0.18")},
        {"market_date": date(2026, 5, 15), "volatility": Decimal("0.18")},
    ]
    rv_rows = [
        {
            "market_date": date(2026, 5, 11),
            "realized_volatility": Decimal("0.10"),
            "implied_volatility": Decimal("0.16"),
        },
        {
            "market_date": date(2026, 5, 12),
            "realized_volatility": Decimal("0.11"),
            "implied_volatility": Decimal("0.17"),
        },
        {
            "market_date": date(2026, 5, 14),
            "realized_volatility": Decimal("0.12"),
            "implied_volatility": Decimal("0.17"),
        },
    ]
    series = _joined_vrp_series(iv_rows, rv_rows)
    by_day = dict(series)
    # Older dates: IV from rv_rows (0.16, 0.17). Newer date with both sources
    # present: prefer interpolated (0.18) over rv_rows (0.17).
    assert by_day[date(2026, 5, 11)] == Decimal("0.06")
    assert by_day[date(2026, 5, 12)] == Decimal("0.06")
    assert by_day[date(2026, 5, 14)] == Decimal("0.06")  # 0.18 - 0.12


def test_vrp_values_returns_latest_at_or_before_market_date() -> None:
    # No row exists for market_date itself (RV null today); deriver must use
    # the most recent computable VRP point, not give up.
    iv_rows = [
        {"market_date": date(2026, 5, 13), "volatility": Decimal("0.18")},
    ]
    rv_rows = [
        {
            "market_date": date(2026, 5, 11),
            "realized_volatility": Decimal("0.10"),
            "implied_volatility": Decimal("0.15"),
        },
        {
            "market_date": date(2026, 5, 12),
            "realized_volatility": Decimal("0.11"),
            "implied_volatility": Decimal("0.16"),
        },
        {
            "market_date": date(2026, 5, 13),
            "realized_volatility": Decimal("0.12"),
            "implied_volatility": Decimal("0.17"),
        },
        {
            "market_date": date(2026, 5, 14),
            "realized_volatility": None,
            "implied_volatility": Decimal("0.18"),
        },
        {
            "market_date": date(2026, 5, 15),
            "realized_volatility": None,
            "implied_volatility": Decimal("0.18"),
        },
    ]
    current, _zscore = _vrp_values(iv_rows, rv_rows, date(2026, 5, 15), window=60)
    assert current == Decimal("0.06")  # 2026-05-13: 0.18 - 0.12 (interpolated wins)


def test_nearest_high_oi_strike_skips_zero_dte() -> None:
    # 0-DTE makes pin_distance_sigma_v1 degenerate; the candidate finder must
    # skip same-day expiry so the next-day expiry gets picked instead.
    rows = [
        {
            "expiry": date(2026, 5, 15),
            "strike": Decimal("740"),
            "call_oi": 5000,
            "put_oi": 5000,
        },
        {
            "expiry": date(2026, 5, 18),
            "strike": Decimal("742"),
            "call_oi": 1000,
            "put_oi": 1000,
        },
    ]
    result = _nearest_high_oi_strike(
        rows, spot=Decimal("740"), market_date=date(2026, 5, 15)
    )
    assert result is not None
    assert result == (date(2026, 5, 18), Decimal("742"))
