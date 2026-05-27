from __future__ import annotations

import math

import numpy as np
import pytest

from uw_scan.cards import vcg_scoring


def test_composite_version_is_two() -> None:
    """v2 spec section 3 item 4: COMPOSITE_VERSION must be 2."""
    assert vcg_scoring.COMPOSITE_VERSION == 2


def test_v2_constants_present_and_correct() -> None:
    """v2 spec section 6.2: four new constants with specific values.

    Values match docs/research/regime/ground-truth-labels/level1-thresholds.yaml:
    P_PANIC: 0.95, rolling_window_days: 252, percentile_tie_rule: strict_lt.
    """
    assert vcg_scoring.VIX_PCT_PANIC == 0.95
    assert vcg_scoring.VVIX_PCT_PANIC == 0.95
    assert vcg_scoring.VOL_PERCENTILE_WINDOW == 252
    assert vcg_scoring.VOL_PERCENTILE_TIE_RULE == "strict_lt"


def _make_inputs(
    n: int, *, vix_pattern: str = "constant", seed: int = 7
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Synthesize VIX/VVIX/HYG price arrays of length n for compute_vcg."""
    rng = np.random.default_rng(seed)
    if vix_pattern == "constant":
        vix = np.full(n, 18.0) + rng.normal(0.0, 0.01, size=n)
    elif vix_pattern == "monotonic":
        vix = np.linspace(10.0, 50.0, num=n)
    else:
        raise ValueError(vix_pattern)
    vvix = 90.0 + rng.normal(0.0, 0.5, size=n)
    hyg = 80.0 * np.exp(np.cumsum(rng.normal(0.0, 0.005, size=n)))
    return vix, vvix, hyg


def test_percentile_rank_arrays_align_with_vcg_array() -> None:
    """v2 spec section 7.1: percentile arrays must align with vcg."""
    n = 300
    vix, vvix, hyg = _make_inputs(n)
    model = vcg_scoring.compute_vcg(vix, vvix, hyg)
    assert len(model["vix_percentile_rank"]) == len(model["vcg"])
    assert len(model["vvix_percentile_rank"]) == len(model["vcg"])


def test_first_finite_percentile_rank_is_at_warmup_boundary() -> None:
    """v2 spec section 7.1: first finite rank is at the warmup boundary."""
    n = 300
    vix, vvix, hyg = _make_inputs(n)
    model = vcg_scoring.compute_vcg(vix, vvix, hyg)
    ranks = model["vix_percentile_rank"]

    assert np.all(np.isnan(ranks[:250])), "expected NaN for indices 0..249"
    assert not math.isnan(ranks[250]), "expected finite rank at index 250"


def test_percentile_rank_value_at_known_bar_monotonic_series() -> None:
    """v2 spec section 7.1: hand-computed expected rank on monotonic data."""
    n = 300
    vix, vvix, hyg = _make_inputs(n, vix_pattern="monotonic")
    model = vcg_scoring.compute_vcg(vix, vvix, hyg)
    ranks = model["vix_percentile_rank"]

    assert ranks[250] == pytest.approx(1.0), (
        "monotonic series should give rank=1.0 at first post-warmup bar, "
        f"got {ranks[250]}"
    )


def _make_model_for_cascade(
    *,
    pi: float = 0.5,
    sign_ok: bool = True,
    vix_percentile_rank: float = 0.5,
    vvix_percentile_rank: float = 0.5,
    vcg: float = 0.0,
    vcg_adj: float = 0.0,
    vix: float = 18.0,
    vvix: float = 90.0,
) -> tuple[dict[str, np.ndarray], int]:
    """Build a single-row model dict with all keys read by interpretation."""
    idx = 0
    return {
        "vcg": np.array([vcg]),
        "vcg_adj": np.array([vcg_adj]),
        "residuals": np.array([0.0]),
        "alpha": np.array([0.0]),
        "beta1": np.array([0.0 if sign_ok else 0.05]),
        "beta2": np.array([0.0 if sign_ok else 0.05]),
        "vix_ret": np.array([0.0]),
        "vvix_ret": np.array([0.0]),
        "credit_ret": np.array([0.0]),
        "vix_levels": np.array([vix]),
        "vvix_levels": np.array([vvix]),
        "credit_levels": np.array([80.0]),
        "pi": np.array([pi]),
        "vix_percentile_rank": np.array([vix_percentile_rank]),
        "vvix_percentile_rank": np.array([vvix_percentile_rank]),
    }, idx


def _interp(model_kwargs: dict[str, float | bool]) -> str:
    """Build model, call _interpretation_for_index, and return its label."""
    model, idx = _make_model_for_cascade(**model_kwargs)
    return str(vcg_scoring._interpretation_for_index(model, idx)["interpretation"])


def test_cascade_panic_fires_when_pi_high_even_if_sign_failed() -> None:
    """v2 cascade: PANIC fires above SUPPRESSED."""
    assert _interp({"pi": 1.5, "sign_ok": False, "vcg": 1.0}) == "PANIC"


def test_cascade_vol_extreme_overrides_sign_failure() -> None:
    """v2 cascade: vol_extreme fires above SUPPRESSED."""
    assert (
        _interp(
            {
                "pi": 0.5,
                "sign_ok": False,
                "vcg": 1.0,
                "vix_percentile_rank": 0.97,
                "vvix_percentile_rank": 0.96,
            }
        )
        == "RISK_OFF"
    )


def test_cascade_vol_extreme_only_one_side_does_not_override() -> None:
    """v2 cascade: vol_extreme requires both VIX and VVIX ranks."""
    assert (
        _interp(
            {
                "pi": 0.5,
                "sign_ok": False,
                "vcg": 1.0,
                "vix_percentile_rank": 0.97,
                "vvix_percentile_rank": 0.85,
            }
        )
        == "SUPPRESSED"
    )


def test_cascade_pi_panic_outranks_vol_extreme() -> None:
    """v2 cascade: PANIC wins when pi and vol_extreme are both true."""
    assert (
        _interp(
            {
                "pi": 1.2,
                "sign_ok": False,
                "vcg": 1.0,
                "vix_percentile_rank": 0.99,
                "vvix_percentile_rank": 0.99,
            }
        )
        == "PANIC"
    )


def test_cascade_warmup_nan_percentile_does_not_fire_override() -> None:
    """v2 cascade: NaN percentile ranks make vol_extreme false."""
    assert (
        _interp(
            {
                "pi": 0.5,
                "sign_ok": False,
                "vcg": 1.0,
                "vix_percentile_rank": float("nan"),
                "vvix_percentile_rank": float("nan"),
            }
        )
        == "SUPPRESSED"
    )


def test_cascade_insufficient_data() -> None:
    """vcg=NaN still means insufficient data."""
    assert _interp({"vcg": float("nan")}) == "INSUFFICIENT_DATA"


def test_cascade_normal_path_unchanged_from_v1() -> None:
    """All-clear inputs still produce NORMAL."""
    assert (
        _interp(
            {
                "pi": 0.3,
                "sign_ok": True,
                "vcg": 0.5,
                "vcg_adj": 1.0,
                "vix_percentile_rank": 0.5,
                "vvix_percentile_rank": 0.5,
            }
        )
        == "NORMAL"
    )


def test_payload_contains_new_percentile_rank_fields() -> None:
    """v2 payload exposes VIX and VVIX percentile ranks as top-level fields."""
    model, idx = _make_model_for_cascade(
        vix_percentile_rank=0.87, vvix_percentile_rank=0.42
    )
    payload = vcg_scoring._interpretation_for_index(model, idx)
    assert "vix_percentile_rank" in payload
    assert "vvix_percentile_rank" in payload
    assert payload["vix_percentile_rank"] == pytest.approx(0.87, abs=1e-4)
    assert payload["vvix_percentile_rank"] == pytest.approx(0.42, abs=1e-4)


def test_payload_percentile_rank_fields_are_none_when_nan() -> None:
    """NaN percentile ranks serialize as None."""
    model, idx = _make_model_for_cascade(
        vix_percentile_rank=float("nan"), vvix_percentile_rank=float("nan")
    )
    payload = vcg_scoring._interpretation_for_index(model, idx)
    assert payload["vix_percentile_rank"] is None
    assert payload["vvix_percentile_rank"] is None


@pytest.mark.parametrize(
    ("pi_val", "expected_regime"),
    [
        (-0.5, "DIVERGENCE"),
        (0.0, "DIVERGENCE"),
        (0.1, "TRANSITION"),
        (0.5, "TRANSITION"),
        (0.99, "TRANSITION"),
        (1.0, "PANIC"),
        (1.5, "PANIC"),
    ],
)
def test_regime_field_unchanged_from_v1(
    pi_val: float, expected_regime: str
) -> None:
    """v2 keeps the top-level regime field identical to v1."""
    model, idx = _make_model_for_cascade(pi=pi_val, sign_ok=True, vcg=0.0)
    payload = vcg_scoring._interpretation_for_index(model, idx)
    assert payload["regime"] == expected_regime
