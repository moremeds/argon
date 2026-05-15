from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.cards.matrix_state import MatrixInputs, build_matrix_state_from_inputs


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
