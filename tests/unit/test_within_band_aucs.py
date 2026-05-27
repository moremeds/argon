"""Unit tests for _within_band_aucs."""

import math

import pytest

from scripts import backtest_canary as canary_backtest
from uw_scan.reports.regime_canary_form_sweep_full import (
    CanaryFormSweepDeps,
)
from uw_scan.reports.regime_canary_form_sweep_full import (
    _within_band_aucs as _impl_within_band_aucs,
)


def _deps() -> CanaryFormSweepDeps:
    return CanaryFormSweepDeps(
        compute_canary_series=canary_backtest._compute_canary_series,
        aucs_for_rows=canary_backtest._aucs_for_rows,
        band_counts=canary_backtest._band_counts,
        block_bootstrap_auc_ci=canary_backtest._block_bootstrap_auc_ci,
        clean_nans=canary_backtest._clean_nans,
        entry_lagged_label=canary_backtest._entry_lagged_label,
        auc=canary_backtest._auc,
        label_specs=canary_backtest.LABEL_SPECS,
        composite_version=canary_backtest.COMPOSITE_VERSION,
    )


def _within_band_aucs(rows: list[dict]) -> dict[str, dict[str, float]]:
    return _impl_within_band_aucs(rows, _deps())


def _row(score: float, band: str, spx: float, date_str: str = "2020-01-01") -> dict:
    """Minimal row shape for the helper. Only fields actually read."""
    from datetime import date

    return {
        "score": score,
        "band": band,
        "spx": spx,
        "date": date.fromisoformat(date_str),
    }


def _date_str(offset: int) -> str:
    from datetime import date, timedelta

    return (date(2020, 1, 1) + timedelta(days=offset)).isoformat()


def test_empty_rows_returns_empty():
    out = _within_band_aucs([])
    assert out == {"NONE": {}, "WATCH": {}, "BUY": {}, "STRONG_BUY": {}}


def test_band_with_no_rows_returns_nan():
    # All rows in NONE band — WATCH/BUY/STRONG_BUY should return NaN per horizon.
    rows = [_row(10, "NONE", 100.0 + i, _date_str(i)) for i in range(80)]
    out = _within_band_aucs(rows)
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert math.isnan(out["WATCH"][h])
        assert math.isnan(out["BUY"][h])


def test_all_same_label_returns_nan():
    # Construct so forward labels are all 0 (no >2% moves) — AUC is undefined.
    rows = [_row(50, "BUY", 100.0, _date_str(i)) for i in range(80)]
    out = _within_band_aucs(rows)
    # BUY band's AUCs all NaN because positive class is empty.
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert math.isnan(out["BUY"][h])


def test_normal_case_matches_filtered_auc():
    """Normal: 3 bands populated, labels computed once over full series."""
    from scripts.backtest_canary import LABEL_SPECS, _auc, _entry_lagged_label

    rng = __import__("numpy").random.default_rng(seed=1)
    n = 100
    bands = ["NONE"] * 40 + ["WATCH"] * 40 + ["BUY"] * 20
    rng.shuffle(bands)
    spx_path = 100.0 + __import__("numpy").cumsum(rng.normal(0.001, 0.01, n))
    rows = [
        _row(
            float(i + rng.standard_normal()), bands[i], float(spx_path[i]), _date_str(i)
        )
        for i in range(n)
    ]
    out = _within_band_aucs(rows)
    # Recompute reference per-band by hand and confirm equality.
    for band in ("NONE", "WATCH", "BUY"):
        idxs = [i for i, r in enumerate(rows) if r["band"] == band]
        for name, h, thr in LABEL_SPECS:
            labels_full = _entry_lagged_label(rows, h, thr)
            band_scores = [rows[i]["score"] for i in idxs]
            band_labels = [labels_full[i] for i in idxs]
            expected = _auc(band_scores, band_labels)
            actual = out[band][name]
            if math.isnan(expected):
                assert math.isnan(actual)
            else:
                assert abs(actual - expected) < 1e-9


def test_labels_computed_once_not_per_subset():
    """The last 60 rows should not silently vanish from each band's AUC.

    If we computed labels per-subset, slicing rows[band==X] then calling
    _entry_lagged_label would drop the last 60 of THAT subset (not the
    last 60 of the full series). The helper must NOT do that.

    SPX path uses seeded RNG so forward returns straddle thresholds
    (mixed 0/1 labels) — a monotonic path would give all-1 labels and
    NaN AUCs regardless of how labels are computed.
    """
    import math as _m

    import numpy as np

    n = 200
    rng = np.random.default_rng(seed=7)
    # Deterministic sinusoidal path with slight upward drift — guarantees
    # forward returns straddle the 2%/5%/10% thresholds at all 3 horizons.
    spx_path = [100.0 + 8.0 * _m.sin(i / 7.0) + 0.05 * i for i in range(n)]
    # Half NONE, half BUY, alternating; score = i+jitter so within-band AUCs
    # are well-defined.
    rows = [
        _row(
            float(i + rng.standard_normal()),
            "NONE" if i % 2 == 0 else "BUY",
            float(spx_path[i]),
            _date_str(i),
        )
        for i in range(n)
    ]
    out = _within_band_aucs(rows)
    # Every band should have non-NaN AUCs (since labels are computed once
    # over the full 200-row series, BOTH bands have plenty of labeled rows).
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert not math.isnan(out["NONE"][h]), f"NONE[{h}] should be finite"
        assert not math.isnan(out["BUY"][h]), f"BUY[{h}] should be finite"
