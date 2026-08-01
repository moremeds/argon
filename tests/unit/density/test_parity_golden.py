"""THE GATE: golden parity vs signal-lab's committed 2026-08-01 forward run.

Offline by construction: forecast.json records its 4 post-panel bars verbatim under
provenance.fresh_bars_appended, so panel.parquet + those rows reconstruct the exact
4,240-return input with no lake and no network.

NEVER skip this test. It failing means the cone argon draws is not the model v13
validated.

Two classes of assertion, deliberately different:

* **Exact (`==`)** for everything discrete: the panel index, the derived seed, the panel
  digest. This is where the silent-drift trap lives — a shifted index frame changes every
  bootstrap draw while still producing a plausible cone — and it is exactly reproducible
  on any machine, so it gets no tolerance ever.
* **Tightly bounded** for the float chain. The original intent was `== 0.0` throughout,
  and that holds on the platform the golden was produced on (macOS/arm64, Accelerate BLAS)
  — but NOT across architectures. Measured 2026-08-01 on Linux/x86-64 (OpenBLAS): fitted
  `omega` differed by 4.4e-9 absolute / 1.1e-7 relative, and the analytic EWMA path by a
  single ULP. The GJR fit is an iterative maximum-likelihood optimisation, so a different
  BLAS lands on a marginally different stationary point; that is convergence noise, not a
  different model.

  REL_TOL is set six-plus orders of magnitude below any *structural* error: a genuine
  vendoring mistake (wrong variance lag, percent-vs-log confusion, a different quantile
  method, a mis-derived seed) moves results by 1e-3 or more, which this bound still fails
  loudly on. The tests print the worst observed relative delta so silent creep toward the
  bound is visible in CI output rather than only at the moment it breaks.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tests.unit.density._parity import Drift
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


def test_gjr_cone_matches_committed_run() -> None:
    r, golden = _joined_returns()
    i = len(r) - 1
    # EXACT: the index frame and the seed derived from it. No tolerance, ever — this is
    # the silent-drift trap, and it is bit-reproducible on every platform.
    assert i == golden["anchor"]["series_index"]
    hist = r[: i + 1]
    seed = int(seed_for(i))
    assert seed == golden["model"]["cone_seed"]
    assert hist.size == golden["anchor"]["n_returns"]

    drift = Drift()
    params, _attempts = _fit(ARMS["G"], hist)
    assert params is not None
    for k, v in golden["model"]["params"].items():
        drift.check(params[k], v, f"param {k}")

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
        assert len(got) == len(QUANTILES)  # EXACT: shape/ordering of the quantile row
        for qi, q in enumerate(QUANTILES):
            drift.check(got[qi], row["cum_return_q"][str(q)], f"h={row['h']} q={q}")
    drift.report("GJR arm G vs committed 2026-08-01 run")


def test_ewma_fallback_matches_signal_lab_original() -> None:
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
    drift = Drift()
    for h in range(1, 6):
        got = cone.at(h)
        for qi, want in enumerate(fx["cum_return_q"][str(h)]):
            drift.check(got[qi], want, f"ewma h={h} qi={qi}")
    drift.report("EWMA fallback vs signal-lab original")


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
