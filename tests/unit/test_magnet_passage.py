# tests/unit/test_magnet_passage.py
import numpy as np
import pytest

from uw_scan.reports.magnet_passage import (
    bootstrap_null_hit_rate,
    clustered_bootstrap_edge,
    first_passage,
    measured_move,
)


def test_measured_move_reproduces_the_reference_exactly_for_mu():
    # MU: R 990.21, S 739.00, leg 251.21, 0.618*leg = 155.24778
    stretch, down = measured_move(990.21, 739.00)
    assert stretch == pytest.approx(1145.46, abs=0.005)
    assert down == pytest.approx(583.75, abs=0.005)


def test_measured_move_reproduces_the_reference_exactly_for_tsla():
    # TSLA: R 407.76, S 298.32, leg 109.44, 0.618*leg = 67.63392
    stretch, down = measured_move(407.76, 298.32)
    assert stretch == pytest.approx(475.39, abs=0.005)
    assert down == pytest.approx(230.69, abs=0.005)


def test_measured_move_rejects_inverted_levels():
    with pytest.raises(ValueError):
        measured_move(100.0, 200.0)


def test_first_passage_detects_an_up_touch():
    highs = [100.0, 105.0, 112.0]
    lows = [99.0, 101.0, 108.0]
    assert first_passage(highs, lows, up=110.0, down=90.0, max_bars=10) == "hit"


def test_first_passage_detects_a_down_touch():
    highs = [100.0, 99.0, 95.0]
    lows = [99.0, 94.0, 88.0]
    assert first_passage(highs, lows, up=110.0, down=90.0, max_bars=10) == "stop"


def test_first_passage_flags_same_bar_double_touch_as_ambiguous():
    # Both barriers inside one bar: intrabar order is unknowable from daily data.
    # Guessing would silently bias the hit rate — say ambiguous instead.
    highs = [100.0, 115.0]
    lows = [99.0, 85.0]
    assert first_passage(highs, lows, up=110.0, down=90.0, max_bars=10) == "ambiguous"


def test_first_passage_returns_neither_when_the_window_expires():
    highs = [100.0] * 5
    lows = [99.0] * 5
    assert first_passage(highs, lows, up=110.0, down=90.0, max_bars=5) == "neither"


def test_first_passage_respects_max_bars():
    highs = [100.0, 100.0, 120.0]
    lows = [99.0, 99.0, 119.0]
    assert first_passage(highs, lows, up=110.0, down=90.0, max_bars=2) == "neither"


def test_bootstrap_null_outcomes_sum_to_one():
    rng = np.random.default_rng(5)
    rets = rng.normal(0.0005, 0.02, 500)
    out = bootstrap_null_hit_rate(
        rets, 100.0, up=110.0, down=90.0, max_bars=60, block=5, n_paths=300, seed=9
    )
    assert sum(out.values()) == pytest.approx(1.0)


def test_bootstrap_null_is_deterministic_under_a_fixed_seed():
    rng = np.random.default_rng(6)
    rets = rng.normal(0.0005, 0.02, 500)
    kw = dict(up=110.0, down=90.0, max_bars=60, block=5, n_paths=200, seed=3)
    assert bootstrap_null_hit_rate(rets, 100.0, **kw) == bootstrap_null_hit_rate(
        rets, 100.0, **kw
    )


def test_bootstrap_null_hits_more_often_with_positive_drift():
    rng = np.random.default_rng(7)
    flat = rng.normal(0.0, 0.02, 1000)
    drift = flat + 0.004
    kw = dict(up=110.0, down=90.0, max_bars=60, block=5, n_paths=600, seed=4)
    assert (
        bootstrap_null_hit_rate(drift, 100.0, **kw)["hit"]
        > bootstrap_null_hit_rate(flat, 100.0, **kw)["hit"]
    )


def _legs(n_tickers: int, per_ticker: int, edge: float, seed: int) -> list[dict]:
    """Legs whose outcome-minus-null has mean `edge`, correlated WITHIN a ticker.

    Ticker biases are CENTRED before use. Drawing 40 biases from N(0, 0.25) and
    calling the result "no edge" is wrong: their sample mean has SE ~= 0.04, so a
    typical seed yields a real edge of a couple of points and a correct CI will
    rightly exclude zero. Centring makes the fixture's edge exactly `edge`, so a
    coverage test measures the estimator rather than the draw.
    """
    rng = np.random.default_rng(seed)
    biases = rng.normal(0.0, 0.25, n_tickers)
    biases = biases - biases.mean()
    out = []
    for t in range(n_tickers):
        for _ in range(per_ticker):
            p = min(max(0.5 + edge + float(biases[t]), 0.01), 0.99)
            hit = rng.random() < p
            out.append(
                {
                    "ticker": f"T{t}",
                    "outcome": "hit" if hit else "stop",
                    "null_hit": 0.5,
                }
            )
    return out


def test_clustered_edge_drops_ambiguous_and_null_less_legs():
    legs = [
        {"ticker": "A", "outcome": "hit", "null_hit": 0.4},
        {"ticker": "A", "outcome": "ambiguous", "null_hit": 0.4},
        {"ticker": "B", "outcome": "stop", "null_hit": float("nan")},
        {"ticker": "B", "outcome": "stop", "null_hit": 0.4},
    ]
    out = clustered_bootstrap_edge(legs, n_boot=200, seed=1, alpha=0.05)
    assert out["n"] == 2  # ambiguous and NaN-null legs excluded
    assert out["n_clusters"] == 2


def test_clustered_ci_covers_zero_when_there_is_no_edge():
    out = clustered_bootstrap_edge(
        _legs(40, 20, edge=0.0, seed=3), n_boot=800, seed=5, alpha=0.01
    )
    assert out["lo"] < 0.0 < out["hi"]


def test_clustered_ci_is_wider_than_ignoring_ticker_clusters():
    """The G1 guard. Legs within a ticker overlap and share a common shift;
    resampling legs instead of tickers would shrink this interval by ~sqrt(n)."""
    legs = _legs(40, 20, edge=0.0, seed=3)
    clustered = clustered_bootstrap_edge(legs, n_boot=800, seed=5, alpha=0.05)

    vals = np.array(
        [(1.0 if r["outcome"] == "hit" else 0.0) - r["null_hit"] for r in legs]
    )
    rng = np.random.default_rng(5)
    naive = np.array(
        [float(np.mean(rng.choice(vals, size=vals.size, replace=True))) for _ in range(800)]
    )
    naive_w = float(np.percentile(naive, 97.5) - np.percentile(naive, 2.5))
    assert (clustered["hi"] - clustered["lo"]) > 1.5 * naive_w


def test_clustered_edge_returns_nan_when_every_leg_is_ambiguous():
    legs = [{"ticker": "A", "outcome": "ambiguous", "null_hit": 0.5}]
    out = clustered_bootstrap_edge(legs, n_boot=100, seed=1, alpha=0.05)
    assert out["n"] == 0
    assert out["point"] != out["point"]  # NaN, so G1 cannot silently pass
