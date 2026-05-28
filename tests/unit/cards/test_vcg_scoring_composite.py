"""compute_vcg_composite + RESEARCH_COMPOSITE_VERSIONS contract.

Critical regression: the production compute_vcg path must be unchanged in
shape after the composite path was added. This protects Hard Guarantee #1.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.vcg_scoring import (
    RESEARCH_COMPOSITE_VERSIONS,
    _compute_vcg_from_returns,
    compute_vcg,
    compute_vcg_composite,
)


def _series(start: str, n: int, base: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, size=n)
    px = base * np.exp(np.cumsum(rets))
    return pd.Series(px, index=pd.bdate_range(start, periods=n))


def test_research_versions_present_for_all_four_methods() -> None:
    assert set(RESEARCH_COMPOSITE_VERSIONS) == {
        "risk_parity_3",
        "risk_parity_hyjk",
        "hy_minus_ig_spread",
        "equal_weight_3",
    }
    for v in RESEARCH_COMPOSITE_VERSIONS.values():
        assert v.startswith("2-candidate-")


def test_compute_vcg_unchanged_after_composite_addition() -> None:
    """Bit-identical regression: production compute_vcg must yield the same
    output shape as before the composite path was added."""
    vix = _series("2020-01-01", 150, 18.0, seed=1).values
    vvix = _series("2020-01-01", 150, 90.0, seed=2).values
    hyg = _series("2020-01-01", 150, 80.0, seed=3).values
    model = compute_vcg(vix, vvix, hyg)
    for key in (
        "vcg",
        "vcg_adj",
        "residuals",
        "alpha",
        "beta1",
        "beta2",
        "vix_ret",
        "vvix_ret",
        "credit_ret",
        "vix_levels",
        "vvix_levels",
        "credit_levels",
        "pi",
    ):
        assert key in model, f"production compute_vcg lost key {key}"
        assert len(model[key]) == 149  # N-1 returns from N prices


def test_compute_vcg_from_returns_percentile_ranks_are_already_aligned() -> None:
    """Composite path uses aligned N-length return/level arrays without slicing."""
    n = 300
    rng = np.random.default_rng(101)
    vix_levels = np.linspace(10.0, 50.0, num=n)
    vvix_levels = np.linspace(70.0, 150.0, num=n)
    credit_levels = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.005, size=n)))
    vix_returns = np.diff(np.log(vix_levels), prepend=np.nan)
    vvix_returns = np.diff(np.log(vvix_levels), prepend=np.nan)
    credit_returns = np.diff(np.log(credit_levels), prepend=np.nan)

    model = _compute_vcg_from_returns(
        vix_returns,
        vvix_returns,
        credit_returns,
        vix_levels,
        vvix_levels,
        credit_levels,
    )

    assert len(model["vix_percentile_rank"]) == len(model["vcg"]) == n
    assert len(model["vvix_percentile_rank"]) == len(model["vcg"]) == n
    assert np.all(np.isnan(model["vix_percentile_rank"][:251]))
    assert model["vix_percentile_rank"][251] == pytest.approx(1.0)


def test_compute_vcg_composite_returns_two_attribution_layers() -> None:
    vix = _series("2020-01-01", 200, 18.0, seed=10)
    vvix = _series("2020-01-01", 200, 90.0, seed=11)
    proxies = {
        "HYG": _series("2020-01-01", 200, 80.0, seed=12),
        "JNK": _series("2020-01-01", 200, 100.0, seed=13),
        "LQD": _series("2020-01-01", 200, 110.0, seed=14),
    }
    payload = compute_vcg_composite(vix, vvix, proxies, method="risk_parity_3")
    assert "signal" in payload
    assert "attribution" in payload
    assert "basket_construction" in payload["attribution"]
    assert "signal_breakdown" in payload["attribution"]
    bc = payload["attribution"]["basket_construction"]
    assert bc["method"] == "risk_parity_3"
    assert bc["vol_window"] == 63
    assert bc["weight_lag"] == 1
    assert set(bc["weights_today"].keys()) == {"HYG", "JNK", "LQD"}
    sb = payload["attribution"]["signal_breakdown"]
    # Attribution always covers all 3 proxies regardless of basket method
    assert set(sb.keys()) >= {
        "HYG",
        "JNK",
        "LQD",
        "composite_single_proxy_disagreement",
    }


def test_compute_vcg_composite_credit_proxy_label() -> None:
    vix = _series("2020-01-01", 200, 18.0, seed=20)
    vvix = _series("2020-01-01", 200, 90.0, seed=21)
    proxies = {
        "HYG": _series("2020-01-01", 200, 80.0, seed=22),
        "JNK": _series("2020-01-01", 200, 100.0, seed=23),
        "LQD": _series("2020-01-01", 200, 110.0, seed=24),
    }
    rp3 = compute_vcg_composite(vix, vvix, proxies, method="risk_parity_3")
    spread = compute_vcg_composite(vix, vvix, proxies, method="hy_minus_ig_spread")
    assert rp3["credit_proxy"] == "COMPOSITE_RP3"
    assert spread["credit_proxy"] == "COMPOSITE_HY_MINUS_IG"


def test_hyjk_basket_still_reports_lqd_attribution() -> None:
    """REGRESSION GUARD (third-pass review item 6): even when the basket
    method only consumes HYG+JNK, the signal_breakdown must include LQD so
    the disagreement diagnostic compares against all three issuer reads."""
    vix = _series("2020-01-01", 200, 18.0, seed=30)
    vvix = _series("2020-01-01", 200, 90.0, seed=31)
    proxies = {
        "HYG": _series("2020-01-01", 200, 80.0, seed=32),
        "JNK": _series("2020-01-01", 200, 100.0, seed=33),
        "LQD": _series("2020-01-01", 200, 110.0, seed=34),
    }
    payload = compute_vcg_composite(vix, vvix, proxies, method="risk_parity_hyjk")
    sb = payload["attribution"]["signal_breakdown"]
    # Basket symbols are only HYG+JNK
    bc = payload["attribution"]["basket_construction"]
    assert bc["basket_symbols"] == ["HYG", "JNK"]
    # But attribution still covers LQD
    assert "LQD" in sb
    assert bc["attribution_symbols"] == ["HYG", "JNK", "LQD"]
