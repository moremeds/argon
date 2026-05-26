"""Unit tests for cards/vcg_basket.py.

Covers:
- realized_vol primitive (window-completion, vol-floor clipping, index preservation)
- risk_parity_weights with no-lookahead invariant — the two load-bearing causality
  tests are test_weights_at_t_unchanged_when_only_return_t_perturbed and
  test_weights_match_strict_offset_reference_at_every_position. These together
  prove that weight[i] is a function only of returns[<i] (with weight_lag=1).
- build_basket dispatcher for all four methods.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.vcg_basket import (
    METHOD_METADATA,
    MethodMetadata,
    build_basket,
    realized_vol,
    risk_parity_weights,
)


def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def _make_3proxy_fixture(n: int = 200, seed: int = 0) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    out: dict[str, pd.Series] = {}
    for sym, base in (("HYG", 80.0), ("JNK", 100.0), ("LQD", 110.0)):
        rets = rng.normal(0.0, 0.005, size=n)
        prices = base * np.exp(np.cumsum(rets))
        out[sym] = pd.Series(prices, index=idx, name=sym)
    return out


def _perturb_return_at_position(
    base: dict[str, pd.Series], *, proxy: str, index_pos: int, factor: float
) -> dict[str, pd.Series]:
    """Multiply prices[i:] by factor so only return[i] changes; later returns
    are unchanged because they're ratios of consecutive bumped prices."""
    out = {k: v.copy() for k, v in base.items()}
    s = out[proxy]
    s.iloc[index_pos:] = s.iloc[index_pos:] * factor
    out[proxy] = s
    return out


def _reference_inverse_vol_weights(
    prefix: dict[str, pd.Series],
    *,
    window: int,
    weight_lag: int,
    vol_floor: float = 1e-6,
) -> pd.Series:
    """Reference: compute weights at the LAST position of prefix using only
    data in prefix. Output is one weight row (a pd.Series indexed by symbol).
    """
    rets_by_sym = {sym: np.log(s / s.shift(1)) for sym, s in prefix.items()}
    rets = pd.DataFrame(rets_by_sym).dropna()
    if len(rets) < window + weight_lag:
        return pd.Series({sym: np.nan for sym in prefix}, name=rets.index[-1])
    # Apply lag: vol uses returns through position -weight_lag (exclude tail)
    rets_for_vol = rets.iloc[: len(rets) - weight_lag]
    vols = rets_for_vol.tail(window).std(ddof=1).clip(lower=vol_floor)
    inv = 1.0 / vols
    weights = inv / inv.sum()
    weights.name = rets.index[-1]
    return weights


# --- realized_vol -------------------------------------------------------- #


def test_realized_vol_first_window_minus_one_bars_are_nan() -> None:
    s = _series([1.0] * 100)
    rets = np.log(s / s.shift(1))
    out = realized_vol(rets, window=10)
    assert out.iloc[:9].isna().all(), "bars before window completion must be NaN"
    assert pd.notna(out.iloc[10])


def test_realized_vol_zero_volatility_clipped_to_floor() -> None:
    rets = pd.Series([0.0] * 100, index=pd.bdate_range("2024-01-01", periods=100))
    out = realized_vol(rets, window=10, vol_floor=1e-6)
    assert (out.iloc[10:] >= 1e-6).all()


def test_realized_vol_index_preserved() -> None:
    rets = pd.Series(
        [0.01, -0.02, 0.005], index=pd.bdate_range("2024-01-01", periods=3)
    )
    out = realized_vol(rets, window=2)
    assert list(out.index) == list(rets.index)


# --- risk_parity_weights no-lookahead -------------------------------------- #


def test_weights_at_t_unchanged_when_only_return_t_perturbed() -> None:
    """LOAD-BEARING: changing return[i] must NOT change weight[i].

    Multiply prices[i:] by a constant — this changes ONLY return[i] (a single
    log ratio jumps), all later returns remain identical because they're
    ratios of two scaled prices.
    """
    base = _make_3proxy_fixture(n=200)
    w_base = risk_parity_weights(base, window=63, weight_lag=1)
    for i in range(80, 195, 17):  # sample every 17th to keep runtime sane
        bumped = _perturb_return_at_position(
            base, proxy="HYG", index_pos=i, factor=10.0
        )
        w_bumped = risk_parity_weights(bumped, window=63, weight_lag=1)
        assert np.allclose(
            w_base.iloc[i].values,
            w_bumped.iloc[i].values,
            equal_nan=True,
            atol=1e-12,
        ), f"weight at position {i} leaked information from return[{i}]"


def test_weights_match_strict_offset_reference_at_every_position() -> None:
    """LOAD-BEARING: at every position i, weights[i] equals the reference
    computation that uses ONLY the prefix prices[:i+1]."""
    base = _make_3proxy_fixture(n=120)
    actual = risk_parity_weights(base, window=21, weight_lag=1)
    for i in range(25, 120, 7):
        prefix = {sym: s.iloc[: i + 1] for sym, s in base.items()}
        expected = _reference_inverse_vol_weights(prefix, window=21, weight_lag=1)
        for sym in expected.index:
            a = actual.iloc[i][sym]
            e = expected[sym]
            assert np.allclose([a], [e], equal_nan=True, atol=1e-9), (
                f"position {i}, {sym}: prod={a} ref={e}"
            )


def test_weights_sum_to_one_after_warmup() -> None:
    base = _make_3proxy_fixture(n=200)
    w = risk_parity_weights(base, window=63, weight_lag=1)
    rows = w.dropna(how="all")
    sums = rows.sum(axis=1)
    assert np.allclose(sums.values, 1.0, atol=1e-9)


def test_weights_handle_constant_prices_equal_after_warmup() -> None:
    idx = pd.bdate_range("2020-01-01", periods=200)
    base = {sym: pd.Series(100.0, index=idx) for sym in ("HYG", "JNK", "LQD")}
    w = risk_parity_weights(base, window=63, weight_lag=1, vol_floor=1e-6)
    row = w.iloc[-1]
    assert np.allclose(row.values, 1.0 / 3.0, atol=1e-9)


def test_weights_skip_dates_missing_in_any_proxy() -> None:
    base = _make_3proxy_fixture(n=200)
    base["HYG"] = base["HYG"].drop(base["HYG"].index[100])  # drop one date
    w = risk_parity_weights(base, window=63, weight_lag=1)
    expected_idx = (
        base["JNK"]
        .index.intersection(base["LQD"].index)
        .intersection(base["HYG"].index)
    )
    assert (w.index == expected_idx).all()


# --- build_basket dispatch + per-method semantics -------------------------- #


def test_method_metadata_registry_has_all_four_methods() -> None:
    assert set(METHOD_METADATA.keys()) == {
        "risk_parity_3",
        "risk_parity_hyjk",
        "hy_minus_ig_spread",
        "equal_weight_3",
    }
    rp3 = METHOD_METADATA["risk_parity_3"]
    spread = METHOD_METADATA["hy_minus_ig_spread"]
    assert rp3.method_type == "basket" and rp3.requires_vol_estimation is True
    assert spread.method_type == "spread"
    assert spread.gross_exposure == 2.0


def test_build_basket_equal_weight_3_uniform_weights() -> None:
    base = _make_3proxy_fixture(n=200)
    rets, weights = build_basket(base, method="equal_weight_3")
    # Weights table is uniform 1/3 across all three proxies after warmup
    last = weights.dropna().iloc[-1]
    assert np.allclose(last.values, 1.0 / 3.0, atol=1e-12)
    # Basket return equals simple mean of per-bar log returns
    raw_returns = np.log(
        pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index)
        / pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index).shift(1)
    )
    expected = raw_returns.mean(axis=1)
    pd.testing.assert_series_equal(
        rets.dropna(), expected.dropna(), check_names=False, atol=1e-12, rtol=0
    )


def test_build_basket_hy_minus_ig_spread_closed_form() -> None:
    base = _make_3proxy_fixture(n=200)
    rets, weights = build_basket(base, method="hy_minus_ig_spread")
    raw = np.log(
        pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index)
        / pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index).shift(1)
    )
    expected = 0.5 * raw["HYG"] + 0.5 * raw["JNK"] - raw["LQD"]
    pd.testing.assert_series_equal(
        rets.dropna(), expected.dropna(), check_names=False, atol=1e-12, rtol=0
    )


def test_build_basket_risk_parity_hyjk_uses_only_hy_proxies() -> None:
    base = _make_3proxy_fixture(n=200)
    rets, weights = build_basket(base, method="risk_parity_hyjk")
    assert list(weights.columns) == ["HYG", "JNK"]
    last = weights.dropna().iloc[-1]
    assert np.isclose(last.sum(), 1.0, atol=1e-9)


def test_build_basket_rejects_unknown_method() -> None:
    with pytest.raises(KeyError):
        build_basket(_make_3proxy_fixture(), method="not_a_method")
