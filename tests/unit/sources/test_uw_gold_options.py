"""Gold-options snapshot composition — reduces UW row lists to one snapshot row."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from uw_scan.models import InterpolatedIvRow, OiPerStrikeRow, OptionContractRow, SkewRow
from uw_scan.sources.uw_gold_options import fetch_gold_options_snapshot


def _iv(days: int, vol: str) -> InterpolatedIvRow:
    return InterpolatedIvRow(date=date(2026, 5, 17), days=days, volatility=Decimal(vol))


def _oi(call: int | None, put: int | None, strike: str) -> OiPerStrikeRow:
    return OiPerStrikeRow(
        date=date(2026, 5, 17),
        strike=Decimal(strike),
        call_oi=call,
        put_oi=put,
    )


def _skew(delta: int, rr: str) -> SkewRow:
    return SkewRow(
        ticker="GLD",
        date=date(2026, 5, 17),
        delta=delta,
        risk_reversal=Decimal(rr),
        expiry=date(2026, 6, 17),
    )


def _contract(symbol: str) -> OptionContractRow:
    return OptionContractRow(option_symbol=symbol)


def test_snapshot_picks_atm_iv_at_nearest_target_dte() -> None:
    interp = [_iv(7, "0.50"), _iv(30, "0.20"), _iv(60, "0.18")]
    with (
        patch(
            "uw_scan.sources.uw_gold_options.fetch_interpolated_iv", return_value=interp
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_oi_per_strike", return_value=[]),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_option_contracts", return_value=[]
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_skew", return_value=[]),
    ):
        snap = fetch_gold_options_snapshot(
            client=None,
            repo=None,
            run_id=1,
            ticker="GLD",
            obs_date=date(2026, 5, 17),
        )
    assert snap.atm_iv_30d == Decimal("0.20")
    assert snap.atm_iv_60d == Decimal("0.18")


def test_snapshot_returns_none_when_iv_far_from_target() -> None:
    interp = [_iv(7, "0.50"), _iv(90, "0.18")]
    with (
        patch(
            "uw_scan.sources.uw_gold_options.fetch_interpolated_iv", return_value=interp
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_oi_per_strike", return_value=[]),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_option_contracts", return_value=[]
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_skew", return_value=[]),
    ):
        snap = fetch_gold_options_snapshot(
            client=None,
            repo=None,
            run_id=1,
            ticker="GLD",
            obs_date=date(2026, 5, 17),
        )
    assert snap.atm_iv_30d is None
    assert snap.atm_iv_60d is None


def test_put_call_oi_ratio_aggregates_across_strikes() -> None:
    oi = [_oi(call=100, put=200, strike="200"), _oi(call=50, put=100, strike="210")]
    with (
        patch("uw_scan.sources.uw_gold_options.fetch_interpolated_iv", return_value=[]),
        patch("uw_scan.sources.uw_gold_options.fetch_oi_per_strike", return_value=oi),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_option_contracts", return_value=[]
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_skew", return_value=[]),
    ):
        snap = fetch_gold_options_snapshot(
            client=None,
            repo=None,
            run_id=1,
            ticker="GLD",
            obs_date=date(2026, 5, 17),
        )
    assert snap.put_call_oi_ratio == Decimal(2)


def test_put_call_oi_ratio_none_when_no_calls() -> None:
    oi = [_oi(call=0, put=200, strike="200")]
    with (
        patch("uw_scan.sources.uw_gold_options.fetch_interpolated_iv", return_value=[]),
        patch("uw_scan.sources.uw_gold_options.fetch_oi_per_strike", return_value=oi),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_option_contracts", return_value=[]
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_skew", return_value=[]),
    ):
        snap = fetch_gold_options_snapshot(
            client=None,
            repo=None,
            run_id=1,
            ticker="GLD",
            obs_date=date(2026, 5, 17),
        )
    assert snap.put_call_oi_ratio is None


def test_skew_uses_nearest_30d_expiry_via_option_contracts() -> None:
    # OCC 21-char: ROOT(<=6) | YYMMDD | C/P | STRIKE*1000 (8 digits)
    contracts = [_contract("GLD   260619C00200000"), _contract("GLD   260918C00210000")]
    skew_rows = [_skew(25, "-0.012"), _skew(10, "-0.030")]
    with (
        patch("uw_scan.sources.uw_gold_options.fetch_interpolated_iv", return_value=[]),
        patch("uw_scan.sources.uw_gold_options.fetch_oi_per_strike", return_value=[]),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_option_contracts",
            return_value=contracts,
        ),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_skew", return_value=skew_rows
        ) as skew_patch,
    ):
        snap = fetch_gold_options_snapshot(
            client=None,
            repo=None,
            run_id=1,
            ticker="GLD",
            obs_date=date(2026, 5, 17),
        )
    # Picked the 2026-06-19 expiry (33 DTE) over 2026-09-18 (124 DTE).
    skew_patch.assert_called_once()
    assert skew_patch.call_args.args[4] == "2026-06-19"
    assert snap.skew_25d_30d == Decimal("-0.012")


def test_deferred_fields_are_none() -> None:
    with (
        patch("uw_scan.sources.uw_gold_options.fetch_interpolated_iv", return_value=[]),
        patch("uw_scan.sources.uw_gold_options.fetch_oi_per_strike", return_value=[]),
        patch(
            "uw_scan.sources.uw_gold_options.fetch_option_contracts", return_value=[]
        ),
        patch("uw_scan.sources.uw_gold_options.fetch_skew", return_value=[]),
    ):
        snap = fetch_gold_options_snapshot(
            client=None,
            repo=None,
            run_id=1,
            ticker="GLD",
            obs_date=date(2026, 5, 17),
        )
    assert snap.put_25d_iv_30d is None
    assert snap.call_25d_iv_30d is None
    assert snap.dealer_gamma_est is None
