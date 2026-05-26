"""Risk-parity credit-basket primitives for the VCG composite research path.

PURE: no DB, no network, no file I/O. Date-indexed pd.Series / pd.DataFrame
in, same shape out. Strict no-lookahead by construction — return[i] cannot
leak into weight[i] because vol uses returns.shift(weight_lag).

Used ONLY by the research path (scripts/backtest_vcg.py --composite-method).
Production scanner does not import this module (enforced by
tests/unit/test_research_isolation.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def realized_vol(
    log_returns: pd.Series,
    window: int = 63,
    vol_floor: float = 1e-6,
) -> pd.Series:
    """Trailing realized volatility on log returns.

    First ``window-1`` bars are NaN. Zero-variance windows are clipped to
    ``vol_floor`` to keep the downstream ``1/vol`` weight computation finite.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    raw = log_returns.rolling(window=window, min_periods=window).std(ddof=1)
    return raw.clip(lower=vol_floor)


def risk_parity_weights(
    prices_by_proxy: dict[str, pd.Series],
    *,
    window: int = 63,
    weight_lag: int = 1,
    vol_floor: float = 1e-6,
) -> pd.DataFrame:
    """Daily 1/sigma normalized weights with strict no-lookahead.

    For basket return at aligned index position ``i``:

        weights[i] = normalize(1 / realized_vol(returns.shift(weight_lag), window)[i])

    The ``.shift(weight_lag)`` is what makes return[i] unable to affect
    weight[i]. With default ``weight_lag=1``, return[i] cannot leak into
    weight[i].

    Index is the intersection of all proxy indices — positional alignment is
    rejected because mismatched calendars would silently produce wrong weights.
    """
    if not prices_by_proxy:
        raise ValueError("prices_by_proxy must be non-empty")

    sorted_symbols = sorted(prices_by_proxy.keys())
    common_idx: pd.Index | None = None
    for sym in sorted_symbols:
        idx = prices_by_proxy[sym].index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)
    assert common_idx is not None
    common_idx = common_idx.sort_values()

    aligned = pd.DataFrame(
        {sym: prices_by_proxy[sym].reindex(common_idx) for sym in sorted_symbols},
        index=common_idx,
    )
    raw_returns = np.log(aligned / aligned.shift(1))
    returns_for_vol = raw_returns.shift(weight_lag)
    vols = returns_for_vol.rolling(window=window, min_periods=window).std(ddof=1)
    vols = vols.clip(lower=vol_floor)
    inv = 1.0 / vols
    weights = inv.div(inv.sum(axis=1), axis=0)
    return weights


@dataclass(frozen=True)
class MethodMetadata:
    """Per-method static metadata.

    Used by the comparator to label and group rows in the validation report
    — a spread method has 2x gross exposure and a different residual scale,
    so the report must surface this distinction.
    """

    name: str
    method_type: str  # "basket" or "spread"
    proxies: tuple[str, ...]  # symbols this method consumes
    gross_exposure: float  # sum of absolute weights at any bar
    requires_vol_estimation: bool


METHOD_METADATA: dict[str, MethodMetadata] = {
    "risk_parity_3": MethodMetadata(
        name="risk_parity_3",
        method_type="basket",
        proxies=("HYG", "JNK", "LQD"),
        gross_exposure=1.0,
        requires_vol_estimation=True,
    ),
    "risk_parity_hyjk": MethodMetadata(
        name="risk_parity_hyjk",
        method_type="basket",
        proxies=("HYG", "JNK"),
        gross_exposure=1.0,
        requires_vol_estimation=True,
    ),
    "hy_minus_ig_spread": MethodMetadata(
        name="hy_minus_ig_spread",
        method_type="spread",
        proxies=("HYG", "JNK", "LQD"),
        gross_exposure=2.0,
        requires_vol_estimation=False,
    ),
    "equal_weight_3": MethodMetadata(
        name="equal_weight_3",
        method_type="basket",
        proxies=("HYG", "JNK", "LQD"),
        gross_exposure=1.0,
        requires_vol_estimation=False,
    ),
}


def build_basket(
    prices_by_proxy: dict[str, pd.Series],
    *,
    method: str,
    window: int = 63,
    weight_lag: int = 1,
    vol_floor: float = 1e-6,
) -> tuple[pd.Series, pd.DataFrame]:
    """Dispatch on method. Returns (basket_log_returns, weight_history).

    For variable-weight methods, weight_history rows are the actual per-day
    weights. For fixed-weight methods (equal_weight_3, hy_minus_ig_spread),
    weight rows are constant after warmup. Caller persists this DataFrame as
    a parquet artifact for replay verification.

    NaN handling: rows where ANY proxy is NaN are dropped from the basket's
    valid-return index. Inside the dispatch, basket returns use
    ``skipna=False`` so a residual NaN propagates rather than silently
    averaging over the remaining proxies.
    """
    meta = METHOD_METADATA[method]  # raises KeyError on unknown method
    needed = {sym: prices_by_proxy[sym] for sym in meta.proxies}

    common_idx: pd.Index | None = None
    for s in needed.values():
        common_idx = s.index if common_idx is None else common_idx.intersection(s.index)
    assert common_idx is not None
    common_idx = common_idx.sort_values()

    aligned = pd.DataFrame(
        {sym: needed[sym].reindex(common_idx) for sym in meta.proxies},
        index=common_idx,
    )
    # Drop rows where ANY proxy has NaN. A date present in every proxy's
    # index but with a NaN price must NOT produce a partial-coverage basket
    # return — skipna=True would silently average over the remaining proxies.
    aligned = aligned.dropna(how="any")
    raw_returns = np.log(aligned / aligned.shift(1))

    if method in ("risk_parity_3", "risk_parity_hyjk"):
        weights = risk_parity_weights(
            needed, window=window, weight_lag=weight_lag, vol_floor=vol_floor
        )
        # Reindex weights to the post-dropna index in case dropping created gaps
        weights = weights.reindex(aligned.index)
        basket_ret = (weights * raw_returns).sum(axis=1, skipna=False)
    elif method == "equal_weight_3":
        n = len(meta.proxies)
        weights = pd.DataFrame(
            {sym: 1.0 / n for sym in meta.proxies},
            index=aligned.index,
        )
        # skipna=False: a NaN in any proxy's return for this bar must make the
        # basket return NaN, not partial-average over the others.
        basket_ret = raw_returns.sum(axis=1, skipna=False) / n
    elif method == "hy_minus_ig_spread":
        weights = pd.DataFrame(
            {"HYG": 0.5, "JNK": 0.5, "LQD": -1.0},
            index=aligned.index,
        )
        # NaN propagates naturally through arithmetic on Series; if any proxy's
        # return is NaN at bar t, basket_ret[t] is NaN — desired behavior.
        basket_ret = (
            0.5 * raw_returns["HYG"] + 0.5 * raw_returns["JNK"] - raw_returns["LQD"]
        )
    else:  # pragma: no cover - METHOD_METADATA key check above prevents this
        raise KeyError(method)

    return basket_ret, weights
