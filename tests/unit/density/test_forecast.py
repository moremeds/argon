"""Orchestration-level golden + the panel-index alignment rail."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import uw_scan.density.forecast as fc
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


def test_orchestrator_reproduces_committed_run_bit_identically() -> None:
    result = compute_forecast(_bars())
    assert result.as_of == date.fromisoformat(GOLDEN["anchor"]["date"])
    assert result.anchor_close == GOLDEN["anchor"]["close"]
    assert result.provenance["series_index"] == GOLDEN["anchor"]["series_index"]
    assert result.seed == GOLDEN["model"]["cone_seed"]
    assert result.fallback_used is False
    for k, v in GOLDEN["model"]["params"].items():
        assert result.params[k] - v == 0.0
    assert (
        result.params["persistence"]
        - (
            GOLDEN["model"]["params"]["alpha"]
            + GOLDEN["model"]["params"]["gamma"] / 2.0
            + GOLDEN["model"]["params"]["beta"]
        )
        == 0.0
    )
    for row, grow in zip(result.rows, GOLDEN["forecast"], strict=True):
        assert row["h"] == grow["h"]
        assert row["scored_horizon"] == grow["scored_horizon"]
        assert row["target_date"] == date.fromisoformat(grow["date"])
        for qs, col in QKEY.items():
            assert row[col] - grow["cum_return_q"][qs] == 0.0
        assert row["band80_width"] - grow["band80_width_return"] == 0.0
        assert row["width_ratio"] - grow["width_ratio_vs_baseline"] == 0.0
        # the arm-A EWMA baseline itself, not just the ratio derived from it
        assert (
            row["baseline_band80_width"] - grow["baseline_band80_width_return"] == 0.0
        )
        # golden stores the baseline as prices; reconstruct to pin every baseline quantile
        for qs, col in QKEY.items():
            want = grow["baseline_price_q"][qs] / GOLDEN["anchor"]["close"] - 1.0
            assert abs(row[f"baseline_{col}"] - want) < 1e-12


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
