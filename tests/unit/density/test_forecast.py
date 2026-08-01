"""Orchestration-level golden + the panel-index alignment rail."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import uw_scan.density.forecast as fc
from tests.unit.density._parity import Drift
from uw_scan.density.constants import seed_for
from uw_scan.density.forecast import (
    PanelMismatchError,
    compute_forecast,
    load_frozen_panel,
    result_to_db_rows,
)

REPO = Path(__file__).resolve().parents[3]
GOLDEN = json.loads(
    (
        REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
    ).read_text()
)
QKEY = {
    "0.05": "q05",
    "0.1": "q10",
    "0.25": "q25",
    "0.5": "q50",
    "0.75": "q75",
    "0.9": "q90",
    "0.95": "q95",
}


def _bars() -> list[tuple[date, float]]:
    panel = load_frozen_panel()
    bars = [
        (d.date(), float(c))
        for d, c in zip(
            pd.to_datetime(panel["trade_date"]), panel["close"], strict=True
        )
    ]
    bars += [
        (date.fromisoformat(b["date"]), float(b["close"]))
        for b in GOLDEN["provenance"]["fresh_bars_appended"]
    ]
    return bars


def test_orchestrator_reproduces_committed_run() -> None:
    """Same two-class contract as test_parity_golden (see its module docstring):
    discrete things exactly, the float chain inside REL_TOL — the golden was fitted on
    macOS/arm64 and CI runs Linux/x86-64, where the MLE converges a hair differently."""
    result = compute_forecast(_bars())
    # EXACT — dates, the index frame, the seed, the labels. These carry the drift risk
    # and are reproducible bit-for-bit anywhere.
    assert result.as_of == date.fromisoformat(GOLDEN["anchor"]["date"])
    assert result.anchor_close == GOLDEN["anchor"]["close"]  # passthrough, not computed
    assert result.provenance["series_index"] == GOLDEN["anchor"]["series_index"]
    assert result.provenance["n_returns"] == GOLDEN["anchor"]["n_returns"]
    assert result.seed == GOLDEN["model"]["cone_seed"]
    assert result.fallback_used is False

    drift = Drift()
    for k, v in GOLDEN["model"]["params"].items():
        drift.check(result.params[k], v, f"param {k}")
    drift.check(
        result.params["persistence"],
        GOLDEN["model"]["params"]["alpha"]
        + GOLDEN["model"]["params"]["gamma"] / 2.0
        + GOLDEN["model"]["params"]["beta"],
        "persistence",
    )
    for row, grow in zip(result.rows, GOLDEN["forecast"], strict=True):
        assert row["h"] == grow["h"]
        assert row["scored_horizon"] == grow["scored_horizon"]
        assert row["target_date"] == date.fromisoformat(grow["date"])
        for qs, col in QKEY.items():
            drift.check(row[col], grow["cum_return_q"][qs], f"h{row['h']} {col}")
        drift.check(row["band80_width"], grow["band80_width_return"], "band80_width")
        drift.check(row["width_ratio"], grow["width_ratio_vs_baseline"], "width_ratio")
        # the arm-A EWMA baseline itself, not just the ratio derived from it
        drift.check(
            row["baseline_band80_width"],
            grow["baseline_band80_width_return"],
            "baseline_band80_width",
        )
        # golden stores the baseline as prices; reconstruct to pin every baseline quantile
        for qs, col in QKEY.items():
            want = grow["baseline_price_q"][qs] / GOLDEN["anchor"]["close"] - 1.0
            drift.check(row[f"baseline_{col}"], want, f"h{row['h']} baseline_{col}")
    drift.report("orchestrator vs committed 2026-08-01 run")


def test_close_disagreement_refuses() -> None:
    bars = _bars()
    d0, c0 = bars[100]
    bars[100] = (d0, c0 + 0.01)  # one tick, one row, 17 years ago
    with pytest.raises(PanelMismatchError, match="close disagreement"):
        compute_forecast(bars)


def test_date_misalignment_refuses() -> None:
    bars = _bars()
    del bars[50]  # a missing session shifts every later index -> different seed
    with pytest.raises(PanelMismatchError, match="misalignment|shorter|rows"):
        compute_forecast(bars)


def test_series_shorter_than_panel_refuses() -> None:
    with pytest.raises(PanelMismatchError):
        compute_forecast(_bars()[:1000])


def test_as_of_truncation_moves_anchor_and_seed() -> None:
    bars = _bars()
    result = compute_forecast(bars, as_of=date(2026, 7, 29))
    assert result.as_of == date(2026, 7, 29)
    # one fewer return than the committed run -> seed one lower
    assert result.seed == GOLDEN["model"]["cone_seed"] - 1


def test_as_of_inside_the_panel_keeps_the_true_panel_index_seed() -> None:
    """Reconstructing a date INSIDE the frozen panel is what the backfill does, and is
    what v13's own backtest did. The seed must be that date's real panel-index seed —
    if truncation shifted the frame, every bootstrap draw would silently differ."""
    bars = _bars()
    target = bars[-400][0]  # ~400 sessions back, well inside the panel window
    result = compute_forecast(bars, as_of=target)
    assert result.as_of == target
    # index into r (returns drop row 0), computed independently of compute_forecast
    expected_i = bars.index((target, dict(bars)[target])) - 1
    assert result.provenance["series_index"] == expected_i
    assert result.seed == seed_for(expected_i)
    # and the golden anchor's own seed is unchanged by the rewind path existing
    assert seed_for(GOLDEN["anchor"]["series_index"]) == GOLDEN["model"]["cone_seed"]


def test_live_run_still_refuses_a_short_series() -> None:
    """The stale-mirror guard must survive the as_of relaxation: with as_of=None a
    series shorter than the panel is a truncated feed, not a deliberate rewind."""
    with pytest.raises(PanelMismatchError, match="rows"):
        compute_forecast(_bars()[:4000])


def test_fit_failure_is_labelled_fallback(monkeypatch) -> None:
    monkeypatch.setattr(fc, "_fit", lambda spec, hist: (None, []))
    result = compute_forecast(_bars())
    assert result.fallback_used is True
    assert result.params is None
    assert all(np.isfinite(row["q50"]) for row in result.rows)


def test_result_to_db_rows_shape() -> None:
    result = compute_forecast(_bars(), as_of=date(2026, 7, 29))
    rows = result_to_db_rows(result, origin="reconstructed")
    assert len(rows) == 5
    assert rows[0]["origin"] == "reconstructed"
    assert rows[0]["as_of"] == date(2026, 7, 29)
    assert rows[0]["provenance_jsonb"]["cone_seed"] == result.seed
