"""THE GATE: zero-tolerance golden parity vs signal-lab's committed 2026-08-01 forward run.

Offline by construction: forecast.json records its 4 post-panel bars verbatim under
provenance.fresh_bars_appended, so panel.parquet + those rows reconstruct the exact
4,240-return input with no lake and no network.

Every assertion is `== 0.0`. NEVER add a tolerance. NEVER skip. This test failing means
the cone argon draws is not the model v13 validated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from uw_scan.density.cone import ewma_cone, gjr_std_boot_cone
from uw_scan.density.constants import (
    H_MAX,
    M_PATHS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    PANEL_SHA256,
    QUANTILES,
    seed_for,
)
from uw_scan.density.fit import ARMS, _fit

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
EWMA_GOLDEN = REPO / "tests" / "fixtures" / "density" / "ewma_fallback_golden.json"
PANEL = REPO / "src" / "uw_scan" / "density" / "data" / "panel.parquet"


def _joined_returns() -> tuple[np.ndarray, dict]:
    """panel + fresh_bars_appended -> the exact committed input series."""
    golden = json.loads(GOLDEN.read_text())
    assert hashlib.sha256(PANEL.read_bytes()).hexdigest() == PANEL_SHA256
    assert golden["provenance"]["panel_sha256"] == PANEL_SHA256
    panel = pd.read_parquet(PANEL).sort_values("trade_date").reset_index(drop=True)
    closes = list(panel["close"].astype(float))
    closes += [float(b["close"]) for b in golden["provenance"]["fresh_bars_appended"]]
    arr = np.asarray(closes, dtype=float)
    return arr[1:] / arr[:-1] - 1.0, golden


def test_gjr_cone_bit_identical_to_committed_run() -> None:
    r, golden = _joined_returns()
    i = len(r) - 1
    assert i == golden["anchor"]["series_index"]
    hist = r[: i + 1]
    seed = int(seed_for(i))
    assert seed == golden["model"]["cone_seed"]

    params, _attempts = _fit(ARMS["G"], hist)
    assert params is not None
    for k, v in golden["model"]["params"].items():
        assert float(params[k]) - v == 0.0, (
            f"param {k} drifted: {float(params[k])!r} vs {v!r}"
        )

    cone = gjr_std_boot_cone(
        hist,
        float(golden["anchor"]["close"]),
        pd.Timestamp(golden["anchor"]["date"]),
        H_MAX,
        params,
        M=M_PATHS,
        seed=seed,
        burn_in=OVERLAY_BURN_IN,
        min_pool=OVERLAY_MIN_POOL,
    )
    assert cone is not None
    for row in golden["forecast"]:
        got = cone.at(row["h"])
        for qi, q in enumerate(QUANTILES):
            want = row["cum_return_q"][str(q)]
            assert float(got[qi]) - want == 0.0, f"h={row['h']} q={q} drifted"


def test_ewma_fallback_bit_identical_to_signal_lab_original() -> None:
    fx = json.loads(EWMA_GOLDEN.read_text())
    r, _ = _joined_returns()
    hist = r[-int(fx["n_last_returns"]) :]
    cone = ewma_cone(
        hist,
        float(fx["anchor_close"]),
        pd.Timestamp(fx["anchor_date"]),
        5,
        lam=float(fx["lam"]),
        quantiles=QUANTILES,
        M=10000,
        seed=int(fx["seed"]),
    )
    for h in range(1, 6):
        got = cone.at(h)
        for qi, want in enumerate(fx["cum_return_q"][str(h)]):
            assert float(got[qi]) - want == 0.0, f"ewma h={h} qi={qi} drifted"


def test_short_pool_returns_none() -> None:
    """Degraded branch: residual pool < min_pool + H -> gjr_std_boot_cone refuses (None)."""
    r, golden = _joined_returns()
    # 1000 returns -> pool 1000-252=748 < 756+5=761
    assert (
        gjr_std_boot_cone(
            r[:1000],
            100.0,
            pd.Timestamp("2026-07-30"),
            H_MAX,
            golden["model"]["params"],
            M=M_PATHS,
            seed=1,
            burn_in=OVERLAY_BURN_IN,
            min_pool=OVERLAY_MIN_POOL,
        )
        is None
    )
