# Magnet View — Phase 1 Research Implementation Plan (Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer the three gates in `docs/superpowers/specs/2026-08-08-technicals-magnet-view-design.md` §3.6 — is the ATM-IV cone calibratable, does the 0.618 measured-move target beat a matched null, and does the shrink factor need to be per-ticker — so Plan B can be written against measured facts.

**Architecture:** Pure analytical functions live in `src/uw_scan/reports/` where they are importable and unit-testable; `scripts/research/` holds thin runners that load data, call them, and persist every result. Two independent experiments (E1 cone calibration, E2 first-passage) share one data-loading module. E2's sweep goes through the existing `backtest.sweep.run_sweep` into `backtest_sweep_runs`/`backtest_sweep_results`; E1's full trace goes to `docs/research/`.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, pandas, numpy, scipy, pytest. Existing helpers: `uw_scan.backtest.{sweep,splitters}`, `uw_scan.storage.backtest_repository.BacktestRepository`, `uw_scan.cards.technicals.atr14`.

## Global Constraints

- **`uv` only.** Every command is `uv run …`. Never bare `python`/`pytest`/`pip`.
- **Never read `iv_rank_history`.** It holds ~4 tickers per session. On 2026-07-24, of 114 grid tickers, 3 had same-day IV, 85 were stale by >1 week, 26 were never captured. ATM IV comes from `option_surface_grid_daily` only.
- **Two price scales, never mixed.** `uw_scan.daily_ohlc` is **back-adjusted**; `option_surface_grid_daily` is **as-traded**. Returns come from `daily_ohlc` on both endpoints. Strike selection uses an as-traded spot. Pairing them wrongly is what put KORU's $21 close against strikes spanning 125–1900.
- **`option_surface_grid_daily.underlying_spot` is NULL before 2026-06** (0% Dec–May, 13.8% June, 97.3% July, measured on `option_wizard` 2026-07-29). Any query ordering by it silently returns nothing for those months.
- **Fit scale, never drift.** `mean(z)` is a published diagnostic and is never used to shift the cone. Annualised drift SE over 161 days at 40% vol is ≈50% — larger than any drift being estimated.
- **Coverage nominals: `|z| < 1` → 68.3%, `|z| < 1.96` → 95.0%.** 95.4% is the `|z| < 2` figure; pairing it with 1.96 manufactures a 0.4pt miscalibration.
- **p-values and CIs come from block bootstrap only.** Coverage and `k` point estimates use the full overlapping sample; no p-value computed on overlapping data may appear in any output.
- **Horizons are 5d and 10d.** 21d is withheld — 6 non-overlapping windows per ticker.
- **Persist before exit.** Every config × every metric lands in a durable artifact with the exact reproduce command. stdout-only is data loss.
- **No commits to `main`.** Work continues on `feat/technicals-magnet-view`.
- **No `Co-Authored-By` trailers.**

---

## File Structure

| File | Responsibility |
|---|---|
| `src/uw_scan/reports/magnet_data.py` | Loaders: adjusted close series, as-traded spot with strike-range guard, term-interpolated ATM IV |
| `src/uw_scan/reports/magnet_calibration.py` | E1 math: standardised residual, coverage, PIT, scale estimators, moving-block bootstrap |
| `src/uw_scan/reports/magnet_passage.py` | E2 math: first-passage outcome, block-bootstrap null |
| `src/uw_scan/cards/magnets.py` | `all_pivots` — shared with Plan B |
| `src/uw_scan/cards/technicals.py` | `last_pivot_index` becomes a wrapper (modify) |
| `scripts/research/magnet_cone_calibration.py` | E1 runner |
| `scripts/research/magnet_first_passage.py` | E2 runner |
| `tests/unit/test_magnet_data.py` | Loader tests |
| `tests/unit/test_magnet_calibration.py` | E1 math tests |
| `tests/unit/test_magnet_passage.py` | E2 math tests |
| `tests/unit/test_magnets_pivots.py` | `all_pivots` tests + `last_pivot_index` regression |
| `docs/research/2026-08-08-magnet-cone-calibration/` | Verdict note + CSV traces |

---

## Task 1: Data loaders

**Files:**
- Create: `src/uw_scan/reports/magnet_data.py`
- Test: `tests/unit/test_magnet_data.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `interp_atm_iv(near_iv: float, near_dte: int, far_iv: float, far_dte: int, target_dte: int) -> float`
  - `normalize_iv(raw: float) -> float`
  - `load_adjusted_closes(conn, ticker: str, schema: str) -> pd.DataFrame` — columns `date, open, high, low, close, volume`
  - `load_as_traded_spot(conn, ticker: str, as_of: date, schema: str) -> float | None`
  - `load_atm_iv_at_horizon(conn, ticker: str, as_of: date, target_dte: int, spot: float, schema: str) -> float | None`

- [ ] **Step 1: Write the failing tests for the pure functions**

```python
# tests/unit/test_magnet_data.py
import math

import pytest

from uw_scan.reports.magnet_data import interp_atm_iv, normalize_iv


def test_normalize_iv_passes_decimal_through():
    assert normalize_iv(0.42) == pytest.approx(0.42)


def test_normalize_iv_converts_percent():
    # The grid stores some sessions as percent. load_atm_iv uses the same >3.0 rule.
    assert normalize_iv(42.0) == pytest.approx(0.42)


def test_interp_atm_iv_is_linear_in_total_variance():
    # w = sigma^2 * dte.  near: 0.40^2*7 = 1.12   far: 0.30^2*28 = 2.52
    # target 14 sits 1/3 of the way from 7 to 28 -> w = 1.12 + (2.52-1.12)/3 = 1.5867
    # sigma = sqrt(1.5867/14) = 0.33667
    got = interp_atm_iv(0.40, 7, 0.30, 28, 14)
    assert got == pytest.approx(math.sqrt((1.12 + (2.52 - 1.12) / 3.0) / 14.0), rel=1e-9)


def test_interp_atm_iv_returns_endpoint_when_target_equals_near():
    assert interp_atm_iv(0.40, 7, 0.30, 28, 7) == pytest.approx(0.40)


def test_interp_atm_iv_rejects_non_positive_target():
    with pytest.raises(ValueError):
        interp_atm_iv(0.40, 7, 0.30, 28, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_magnet_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.magnet_data'`

- [ ] **Step 3: Implement the module**

```python
# src/uw_scan/reports/magnet_data.py
"""Data loaders for the magnet-view research (spec 2026-08-08 §3.1).

Two price scales exist and must never be mixed:

    uw_scan.daily_ohlc              back-adjusted  -> use for RETURNS
    option_surface_grid_daily       as-traded      -> use for STRIKE selection

A ticker that split mid-window has a rescaled OHLC history against unrescaled
strikes; KORU's 20-for-1 put its close at ~$21 while its strikes still spanned
125..1900. load_as_traded_spot carries the strike-range guard that catches the
seam regardless of which source supplied the spot.

ATM IV comes from option_surface_grid_daily ONLY. iv_rank_history holds ~4
tickers per session and its obvious `market_date <= as_of ORDER BY DESC LIMIT 1`
lookup silently returns months-old readings.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

# Grid sessions store IV as either a decimal or a percent. Same threshold as
# theta_harvester_repository.load_atm_iv — keep them identical.
_PERCENT_THRESHOLD = 3.0


def normalize_iv(raw: float) -> float:
    """Grid IV to decimal. Mirrors theta_harvester_repository.load_atm_iv."""
    iv = float(raw)
    return iv / 100.0 if iv > _PERCENT_THRESHOLD else iv


def interp_atm_iv(
    near_iv: float, near_dte: int, far_iv: float, far_dte: int, target_dte: int
) -> float:
    """ATM IV at target_dte, interpolated linearly in TOTAL VARIANCE (sigma^2 * t).

    Not linear in vol: the term structure is steep at short DTE, and a 3-day IV
    read as a 7-day IV biases the calibrated shrink factor systematically. Total
    variance is the standard interpolation space because variance is additive in
    time under the model the cone assumes.
    """
    if target_dte <= 0:
        raise ValueError(f"target_dte must be positive, got {target_dte}")
    if near_dte == far_dte:
        return float(near_iv)
    w_near = near_iv**2 * near_dte
    w_far = far_iv**2 * far_dte
    frac = (target_dte - near_dte) / (far_dte - near_dte)
    w = w_near + frac * (w_far - w_near)
    if w <= 0:
        raise ValueError(f"interpolated total variance non-positive: {w}")
    return math.sqrt(w / target_dte)


def load_adjusted_closes(conn, ticker: str, schema: str = "uw_scan") -> pd.DataFrame:
    """Full back-adjusted OHLCV history, ascending by date.

    Back-adjusted is correct for RETURNS (the adjustment factor cancels in a
    ratio) and for ATR. It is wrong for anything compared against option strikes.
    """
    sql = f"""
        SELECT date, open, high, low, close, volume
          FROM {schema}.daily_ohlc
         WHERE ticker = %s AND close > 0
         ORDER BY date ASC
    """
    rows = conn.execute(sql, (ticker,)).fetchall()
    df = pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "volume"]
    )
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_as_traded_spot(
    conn, ticker: str, as_of: date, schema: str = "uw_scan"
) -> float | None:
    """Session spot on the SAME scale as the chain's strikes, or None.

    Grid `underlying_spot` first, `daily_ohlc.close` second — the column is NULL
    for every session before 2026-06, so without the fallback five of seven
    months return nothing, which reads as "no data" rather than "no column".

    A spot outside the session's own strike range is REJECTED, not returned. A
    scale-mismatched spot is not a worse datapoint, it is a fabricated one.
    """
    sql = f"""
        WITH k AS (
            SELECT MIN(strike) AS lo, MAX(strike) AS hi,
                   MAX(underlying_spot) AS grid_spot
              FROM {schema}.option_surface_grid_daily
             WHERE ticker = %(t)s AND market_date = %(d)s
        )
        SELECT COALESCE(
                   k.grid_spot,
                   (SELECT close FROM {schema}.daily_ohlc
                     WHERE ticker = %(t)s AND date = %(d)s AND close > 0
                     LIMIT 1)
               ) AS spot,
               k.lo, k.hi
          FROM k
    """
    row = conn.execute(sql, {"t": ticker, "d": as_of}).fetchone()
    if not row or row[0] is None or row[1] is None or row[2] is None:
        return None
    spot, lo, hi = float(row[0]), float(row[1]), float(row[2])
    if not (lo <= spot <= hi):
        return None
    return spot


def load_atm_iv_at_horizon(
    conn,
    ticker: str,
    as_of: date,
    target_dte: int,
    spot: float,
    schema: str = "uw_scan",
) -> float | None:
    """ATM IV at target_dte, term-interpolated across the straddling expiries.

    Picks the nearest ATM strike within each expiry (grid spacing is $1 on liquid
    names, well inside any tolerance that matters here), then interpolates in
    total variance. Falls back to the single nearest expiry when only one side
    exists, and returns None when the nearest usable expiry is more than 2x
    target_dte away — extrapolating a 5-day cone off a 90-day expiry is not a
    measurement.
    """
    sql = f"""
        SELECT DISTINCT ON (expiry)
               expiry, (call_iv + put_iv) / 2.0 AS iv
          FROM {schema}.option_surface_grid_daily
         WHERE ticker = %(t)s AND market_date = %(d)s
           AND call_iv IS NOT NULL AND put_iv IS NOT NULL
           AND expiry > %(d)s
         ORDER BY expiry, abs(strike - %(s)s)
    """
    rows = conn.execute(sql, {"t": ticker, "d": as_of, "s": spot}).fetchall()
    if not rows:
        return None
    pts = [(int((r[0] - as_of).days), normalize_iv(r[1])) for r in rows if r[1] is not None]
    pts = [(d, iv) for d, iv in pts if d > 0 and iv > 0]
    if not pts:
        return None
    pts.sort()

    below = [p for p in pts if p[0] <= target_dte]
    above = [p for p in pts if p[0] >= target_dte]
    if below and above:
        near_dte, near_iv = below[-1]
        far_dte, far_iv = above[0]
        if near_dte == far_dte:
            return near_iv
        return interp_atm_iv(near_iv, near_dte, far_iv, far_dte, target_dte)

    only_dte, only_iv = (below[-1] if below else above[0])
    if only_dte > 2 * target_dte or only_dte * 2 < target_dte:
        return None
    return only_iv
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_magnet_data.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/magnet_data.py tests/unit/test_magnet_data.py
git commit -m "feat(research): magnet-view data loaders with scale and IV-source guards"
```

---

## Task 2: Cone calibration math

**Files:**
- Create: `src/uw_scan/reports/magnet_calibration.py`
- Test: `tests/unit/test_magnet_calibration.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `standardized_residual(log_return: float, sigma: float, horizon_days: int, trading_days: int = 252) -> float`
  - `pit(z: np.ndarray) -> np.ndarray`
  - `coverage(z: np.ndarray, level: float) -> float`
  - `NOMINAL_COVERAGE: dict[float, float]` — `{1.0: 0.6827, 1.96: 0.9500}`
  - `scale_estimates(z: np.ndarray) -> dict` — keys `std`, `mad`, `mean`, `n`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_magnet_calibration.py
import math

import numpy as np
import pytest

from uw_scan.reports.magnet_calibration import (
    NOMINAL_COVERAGE,
    coverage,
    pit,
    scale_estimates,
    standardized_residual,
)


def test_nominal_coverage_pairs_196_with_95_not_954():
    # 95.4% is the |z|<2 figure. Pairing it with 1.96 invents a 0.4pt miscalibration.
    assert NOMINAL_COVERAGE[1.96] == pytest.approx(0.9500, abs=5e-5)
    assert NOMINAL_COVERAGE[1.0] == pytest.approx(0.6827, abs=5e-5)


def test_standardized_residual_zero_at_risk_neutral_median():
    # Median log return under the model is -sigma^2 T / 2, which standardises to 0.
    sigma, h = 0.40, 5
    t = h / 252
    log_ret = -0.5 * sigma**2 * t
    assert standardized_residual(log_ret, sigma, h) == pytest.approx(0.0, abs=1e-12)


def test_standardized_residual_one_sigma_move():
    sigma, h = 0.40, 5
    t = h / 252
    log_ret = -0.5 * sigma**2 * t + sigma * math.sqrt(t)
    assert standardized_residual(log_ret, sigma, h) == pytest.approx(1.0, abs=1e-12)


def test_pit_of_zero_is_half():
    assert pit(np.array([0.0]))[0] == pytest.approx(0.5, abs=1e-12)


def test_coverage_counts_strictly_inside():
    z = np.array([-2.0, -0.5, 0.0, 0.5, 2.0])
    assert coverage(z, 1.0) == pytest.approx(3 / 5)


def test_scale_estimates_recover_unit_scale_on_standard_normal():
    rng = np.random.default_rng(20260808)
    z = rng.standard_normal(200_000)
    out = scale_estimates(z)
    assert out["std"] == pytest.approx(1.0, abs=0.01)
    assert out["mad"] == pytest.approx(1.0, abs=0.01)
    assert out["mean"] == pytest.approx(0.0, abs=0.01)
    assert out["n"] == 200_000


def test_scale_estimates_mad_ignores_fat_tail_that_moves_std():
    rng = np.random.default_rng(20260808)
    z = rng.standard_normal(100_000)
    z[:50] = 40.0  # 0.05% contamination
    out = scale_estimates(z)
    assert out["std"] > 1.05          # std is dragged
    assert out["mad"] == pytest.approx(1.0, abs=0.02)  # mad is not


def test_standardized_residual_rejects_non_positive_sigma():
    with pytest.raises(ValueError):
        standardized_residual(0.01, 0.0, 5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_magnet_calibration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.magnet_calibration'`

- [ ] **Step 3: Implement**

```python
# src/uw_scan/reports/magnet_calibration.py
"""E1 — is the ATM-IV cone calibrated against realised moves? (spec §3.2)

Under Black-Scholes with r = q = 0, ln(S_T/S_0) ~ N(-sigma^2 T/2, sigma^2 T),
so the standardised residual

    z = [ ln(S_{t+h}/S_t) + sigma^2 T/2 ] / ( sigma * sqrt(T) )

is N(0,1) if the cone is right. It will not be: the cone is a RISK-NEUTRAL
density tested against PHYSICAL realisations, so z is biased on two axes — the
equity risk premium shifts its mean, the variance risk premium shrinks its
spread.

Only the second is correctable. Estimating drift from 161 trading days is
hopeless (annualised SE ~= 0.40/sqrt(161/252) ~= 50%, larger than any drift being
estimated); variance converges in days, drift needs decades. So the calibration
fits SCALE only and publishes mean(z) as a diagnostic that is never applied.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.stats import norm

# |z| < 1 -> 68.27%,  |z| < 1.96 -> 95.00%.
# 95.4% belongs to |z| < 2. Pairing 95.4% with 1.96 fabricates a 0.4pt miss.
NOMINAL_COVERAGE: dict[float, float] = {
    1.0: float(norm.cdf(1.0) - norm.cdf(-1.0)),
    1.96: float(norm.cdf(1.96) - norm.cdf(-1.96)),
}

# MAD -> sigma consistency constant for a normal, 1/Phi^-1(0.75).
_MAD_TO_SIGMA = 1.4826


def standardized_residual(
    log_return: float, sigma: float, horizon_days: int, trading_days: int = 252
) -> float:
    """z-score of a realised log return against its risk-neutral cone."""
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")
    t = horizon_days / trading_days
    return (log_return + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))


def pit(z: np.ndarray) -> np.ndarray:
    """Probability integral transform. Uniform(0,1) iff the cone is calibrated."""
    return norm.cdf(np.asarray(z, dtype=float))


def coverage(z: np.ndarray, level: float) -> float:
    """Share of residuals strictly inside +/- level."""
    arr = np.asarray(z, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.mean(np.abs(arr) < level))


def scale_estimates(z: np.ndarray) -> dict:
    """Scale (two estimators) and location (diagnostic only) of the residuals.

    `std` is the maximum-likelihood scale under normality and is the headline
    shrink factor k. `mad` is the robust companion: a plain standard deviation
    over fat-tailed equity returns is precisely the estimator not to trust alone,
    and a large std/mad gap is itself the finding.

    `mean` is the equity-risk-premium diagnostic. It is REPORTED, never applied.
    """
    arr = np.asarray(z, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return {"std": float("nan"), "mad": float("nan"), "mean": float("nan"), "n": int(arr.size)}
    med = float(np.median(arr))
    return {
        "std": float(np.std(arr, ddof=1)),
        "mad": float(np.median(np.abs(arr - med)) * _MAD_TO_SIGMA),
        "mean": float(np.mean(arr)),
        "n": int(arr.size),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_magnet_calibration.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/magnet_calibration.py tests/unit/test_magnet_calibration.py
git commit -m "feat(research): cone calibration math with scale-only fit"
```

---

## Task 3: Moving-block bootstrap for overlapping samples

**Files:**
- Modify: `src/uw_scan/reports/magnet_calibration.py`
- Test: `tests/unit/test_magnet_calibration.py`

**Interfaces:**
- Consumes: `scale_estimates`, `coverage` from Task 2.
- Produces:
  - `moving_block_bootstrap(values: np.ndarray, statistic: Callable[[np.ndarray], float], *, block: int, n_boot: int, seed: int) -> dict` — keys `point`, `lo`, `hi`, `n_boot`, `block`
  - `nonoverlapping_subsample(values: np.ndarray, step: int, offset: int = 0) -> np.ndarray`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_magnet_calibration.py
import numpy as np
import pytest

from uw_scan.reports.magnet_calibration import (
    moving_block_bootstrap,
    nonoverlapping_subsample,
)


def test_nonoverlapping_subsample_takes_every_step():
    v = np.arange(10.0)
    assert nonoverlapping_subsample(v, 5).tolist() == [0.0, 5.0]
    assert nonoverlapping_subsample(v, 5, offset=2).tolist() == [2.0, 7.0]


def test_bootstrap_ci_brackets_the_point_estimate():
    rng = np.random.default_rng(1)
    v = rng.standard_normal(2000)
    out = moving_block_bootstrap(v, np.mean, block=5, n_boot=400, seed=7)
    assert out["lo"] < out["point"] < out["hi"]
    assert out["n_boot"] == 400
    assert out["block"] == 5


def test_bootstrap_is_deterministic_under_a_fixed_seed():
    rng = np.random.default_rng(2)
    v = rng.standard_normal(500)
    a = moving_block_bootstrap(v, np.mean, block=5, n_boot=200, seed=42)
    b = moving_block_bootstrap(v, np.mean, block=5, n_boot=200, seed=42)
    assert a == b


def test_bootstrap_ci_is_wider_for_longer_blocks():
    # Overlap-induced dependence: longer blocks retain more of it, so the CI
    # must not shrink. This is the whole reason the plain CI is banned.
    rng = np.random.default_rng(3)
    v = np.convolve(rng.standard_normal(4000), np.ones(5) / 5, mode="same")
    narrow = moving_block_bootstrap(v, np.mean, block=1, n_boot=400, seed=11)
    wide = moving_block_bootstrap(v, np.mean, block=20, n_boot=400, seed=11)
    assert (wide["hi"] - wide["lo"]) > (narrow["hi"] - narrow["lo"])


def test_bootstrap_rejects_block_longer_than_sample():
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.arange(5.0), np.mean, block=10, n_boot=10, seed=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_magnet_calibration.py -k bootstrap -v`
Expected: FAIL — `ImportError: cannot import name 'moving_block_bootstrap'`

- [ ] **Step 3: Implement**

```python
# append to src/uw_scan/reports/magnet_calibration.py
from collections.abc import Callable


def nonoverlapping_subsample(
    values: np.ndarray, step: int, offset: int = 0
) -> np.ndarray:
    """Every `step`-th observation from `offset` — independent under an h-day
    overlap when step >= h."""
    if step <= 0:
        raise ValueError(f"step must be positive, got {step}")
    return np.asarray(values, dtype=float)[offset::step]


def moving_block_bootstrap(
    values: np.ndarray,
    statistic: Callable[[np.ndarray], float],
    *,
    block: int,
    n_boot: int,
    seed: int,
) -> dict:
    """Percentile CI for `statistic` under h-day overlap.

    At h = 5 with daily sampling, consecutive residuals share 4 of 5 days.
    Overlap does not bias point estimates but destroys the independence every
    closed-form CI and p-value assumes. Resampling contiguous blocks preserves
    the dependence the naive bootstrap would throw away.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if block <= 0:
        raise ValueError(f"block must be positive, got {block}")
    if n < block:
        raise ValueError(f"sample of {n} shorter than block {block}")
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(n / block))
    starts_hi = n - block + 1
    stats = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        starts = rng.integers(0, starts_hi, size=n_blocks)
        sample = np.concatenate([arr[s : s + block] for s in starts])[:n]
        stats[i] = float(statistic(sample))
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return {
        "point": float(statistic(arr)),
        "lo": float(lo),
        "hi": float(hi),
        "n_boot": int(n_boot),
        "block": int(block),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_magnet_calibration.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/magnet_calibration.py tests/unit/test_magnet_calibration.py
git commit -m "feat(research): moving-block bootstrap for overlapping-sample CIs"
```

---

## Task 4: E1 runner

**Files:**
- Create: `scripts/research/magnet_cone_calibration.py`
- Create: `docs/research/2026-08-08-magnet-cone-calibration/` (output dir, created by the script)

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `docs/research/2026-08-08-magnet-cone-calibration/per_obs.csv`, `by_ticker.csv`, `summary.json`.

- [ ] **Step 1: Write the runner**

```python
#!/usr/bin/env python3
"""E1 — calibrate the ATM-IV cone against realised moves (spec §3.2).

Reproduce:
    uv run python scripts/research/magnet_cone_calibration.py \
        --dsn "dbname=option_wizard_local" \
        --out docs/research/2026-08-08-magnet-cone-calibration

POWER WARNING
    The option surface spans 2025-12-26 -> present, about 161 trading days. At
    h=5 that is 156 overlapping observations per ticker but only 31 independent
    ones; at h=10, 15. The 21d horizon (6 independent windows) is NOT run — see
    spec §3.3. Pooling ~114 tickers does not multiply power by 114: they share a
    volatility factor and the watchlist is concentrated in AI/semis, so the
    effective sample is materially below nominal. Read the bootstrap CIs, not
    the point estimates.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from uw_scan.backtest.splitters import time_ordered_holdout
from uw_scan.reports.magnet_calibration import (
    NOMINAL_COVERAGE,
    coverage,
    moving_block_bootstrap,
    pit,
    scale_estimates,
)
from uw_scan.reports.magnet_data import (
    load_adjusted_closes,
    load_as_traded_spot,
    load_atm_iv_at_horizon,
)

HORIZONS = (5, 10)          # 21 withheld: 6 independent windows, no power
MIN_OBS = 100               # spec §3.2 — below this, k is noise carrying full weight
TRADING_DAYS = 252
CAL_PER_TRADING_DAY = 7 / 5  # trading-day horizon -> calendar DTE target


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "unknown"


def grid_tickers(conn, schema: str) -> list[str]:
    sql = f"SELECT DISTINCT ticker FROM {schema}.option_surface_grid_daily ORDER BY ticker"
    return [r[0] for r in conn.execute(sql).fetchall()]


def observations(conn, ticker: str, schema: str) -> list[dict]:
    """One row per (session, horizon) with a usable IV and a forward close."""
    px = load_adjusted_closes(conn, ticker, schema)
    if px.empty:
        return []
    px = px.reset_index(drop=True)
    close = px["close"].to_numpy(dtype=float)
    dates = list(px["date"])
    idx_of = {d: i for i, d in enumerate(dates)}

    sessions = [
        r[0]
        for r in conn.execute(
            f"""SELECT DISTINCT market_date
                  FROM {schema}.option_surface_grid_daily
                 WHERE ticker = %s ORDER BY market_date""",
            (ticker,),
        ).fetchall()
    ]

    out: list[dict] = []
    for as_of in sessions:
        i = idx_of.get(as_of)
        if i is None:
            continue
        spot = load_as_traded_spot(conn, ticker, as_of, schema)
        if spot is None:          # split seam or no strike range — reject, never guess
            continue
        for h in HORIZONS:
            j = i + h
            if j >= len(close):
                continue
            target_dte = max(1, round(h * CAL_PER_TRADING_DAY))
            sigma = load_atm_iv_at_horizon(conn, ticker, as_of, target_dte, spot, schema)
            if sigma is None or sigma <= 0:
                continue
            # Returns from the BACK-ADJUSTED series on both endpoints.
            log_ret = float(np.log(close[j] / close[i]))
            t = h / TRADING_DAYS
            z = (log_ret + 0.5 * sigma**2 * t) / (sigma * np.sqrt(t))
            out.append(
                {
                    "ticker": ticker,
                    "as_of": as_of,
                    "horizon": h,
                    "sigma": sigma,
                    "log_ret": log_ret,
                    "z": float(z),
                }
            )
    return out


def summarise(z: np.ndarray, horizon: int, label: str) -> dict:
    est = scale_estimates(z)
    row = {"scope": label, "horizon": horizon, **est}
    for level, nominal in NOMINAL_COVERAGE.items():
        row[f"cov_{level}"] = coverage(z, level)
        row[f"cov_{level}_nominal"] = nominal
    if z.size >= max(MIN_OBS, horizon * 2):
        # Block = horizon: the exact span two consecutive observations share.
        boot = moving_block_bootstrap(
            z, lambda a: float(np.std(a, ddof=1)), block=horizon, n_boot=1000, seed=20260808
        )
        row["k_ci_lo"], row["k_ci_hi"] = boot["lo"], boot["hi"]
    else:
        row["k_ci_lo"] = row["k_ci_hi"] = float("nan")
    return row


def oos_calibration(sub: pd.DataFrame, horizon: int, holdout_frac: float = 0.4) -> dict:
    """G2 — fit k on the front window, validate coverage on the held-out tail.

    An in-sample k trivially reproduces nominal coverage in-sample; that is not
    evidence of anything. The gate is whether shrinking by a k the tail never saw
    lands the tail's coverage on nominal.
    """
    rows = sub.sort_values("as_of").to_dict("records")
    if len(rows) < 2 * MIN_OBS:
        return {"status": "insufficient", "n": len(rows)}
    ordered, holdout = time_ordered_holdout(rows, key=lambda r: r["as_of"], frac=holdout_frac)
    train = ordered[: len(ordered) - len(holdout)]
    if len(train) < MIN_OBS or len(holdout) < MIN_OBS:
        return {"status": "insufficient", "n_train": len(train), "n_test": len(holdout)}

    k_train = scale_estimates(np.array([r["z"] for r in train]))["std"]
    if not np.isfinite(k_train) or k_train <= 0:
        return {"status": "bad_k", "k_train": k_train}

    z_test = np.array([r["z"] for r in holdout])
    out = {
        "status": "ok",
        "k_train": float(k_train),
        "n_train": len(train),
        "n_test": len(holdout),
        "train_end": str(train[-1]["as_of"]),
    }
    for level, nominal in NOMINAL_COVERAGE.items():
        raw = coverage(z_test, level)
        cal = coverage(z_test / k_train, level)
        out[f"oos_cov_{level}_raw"] = raw
        out[f"oos_cov_{level}_calibrated"] = cal
        out[f"oos_cov_{level}_nominal"] = nominal
        # Calibration must move coverage TOWARD nominal, not merely change it.
        out[f"oos_cov_{level}_improved"] = bool(abs(cal - nominal) < abs(raw - nominal))
    out["g2_pass"] = bool(
        out["oos_cov_1.0_improved"] and out["oos_cov_1.96_improved"]
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="dbname=option_wizard_local")
    ap.add_argument("--schema", default="uw_scan")
    ap.add_argument("--out", default="docs/research/2026-08-08-magnet-cone-calibration")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    with psycopg.connect(args.dsn) as conn:
        for t in grid_tickers(conn, args.schema):
            rows.extend(observations(conn, t, args.schema))

    if not rows:
        raise SystemExit("no observations — check --dsn and grid coverage")

    per_obs = pd.DataFrame(rows)
    per_obs.to_csv(out_dir / "per_obs.csv", index=False)

    summaries: list[dict] = []
    for h in HORIZONS:
        sub = per_obs[per_obs["horizon"] == h]
        summaries.append(summarise(sub["z"].to_numpy(dtype=float), h, "pooled"))
        for tkr, grp in sub.groupby("ticker"):
            if len(grp) < MIN_OBS:
                continue
            summaries.append(summarise(grp["z"].to_numpy(dtype=float), h, f"ticker:{tkr}"))

    by_ticker = pd.DataFrame(summaries)
    by_ticker.to_csv(out_dir / "by_ticker.csv", index=False)

    excluded = sorted(
        {
            f"{t}@{h}"
            for h in HORIZONS
            for t, g in per_obs[per_obs["horizon"] == h].groupby("ticker")
            if len(g) < MIN_OBS
        }
    )

    # G3: does per-ticker k dispersion exceed OOS error?
    g3: dict = {}
    for h in HORIZONS:
        per_t = by_ticker[
            (by_ticker["horizon"] == h) & (by_ticker["scope"].str.startswith("ticker:"))
        ]
        pooled = by_ticker[(by_ticker["horizon"] == h) & (by_ticker["scope"] == "pooled")]
        if per_t.empty or pooled.empty:
            continue
        ci_width = float(pooled["k_ci_hi"].iloc[0] - pooled["k_ci_lo"].iloc[0])
        g3[str(h)] = {
            "per_ticker_k_std": float(per_t["std"].std(ddof=1)),
            "pooled_k_ci_width": ci_width,
            "per_ticker_table_justified": bool(
                float(per_t["std"].std(ddof=1)) > ci_width
            ),
        }

    # G2: does a k the holdout never saw pull the holdout's coverage to nominal?
    g2 = {
        str(h): oos_calibration(per_obs[per_obs["horizon"] == h], h)
        for h in HORIZONS
    }

    summary = {
        "spec": "docs/superpowers/specs/2026-08-08-technicals-magnet-view-design.md",
        "git_sha": git_sha(),
        "reproduce_cmd": (
            "uv run python scripts/research/magnet_cone_calibration.py "
            f"--dsn '{args.dsn}' --out {args.out}"
        ),
        "generated_for_date": str(date.today()),
        "horizons": list(HORIZONS),
        "horizons_withheld": {"21": "6 independent windows per ticker — no power"},
        "min_obs": MIN_OBS,
        "excluded_ticker_horizons": excluded,
        "n_obs": int(len(per_obs)),
        "g2_oos_calibration": g2,
        "g3_per_ticker_dispersion": g3,
        "note": (
            "mean(z) is an equity-risk-premium diagnostic and is NEVER applied. "
            "CIs are moving-block bootstrap; no closed-form p-value is valid here. "
            "Per-SECTOR pooling from spec §3.2 is omitted: no verified sector "
            "column was confirmed on the grid or watchlist tables, and inventing "
            "one would be fabrication. G3 needs only per-ticker vs pooled. Add "
            "sector pooling only after confirming a real sector source exists."
        ),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it runs and writes all three artifacts**

Run:
```bash
uv run python scripts/research/magnet_cone_calibration.py \
  --dsn "dbname=option_wizard_local" \
  --out docs/research/2026-08-08-magnet-cone-calibration
ls -la docs/research/2026-08-08-magnet-cone-calibration/
```
Expected: `per_obs.csv`, `by_ticker.csv`, `summary.json` all present; `summary.json` reports `n_obs > 0`.

**If `n_obs` is 0:** do not "fix" it by relaxing the guards. Check in order — (a) does `option_surface_grid_daily` have rows for this DSN, (b) is `load_as_traded_spot` rejecting everything because `underlying_spot` is NULL pre-2026-06 *and* `daily_ohlc` has no matching date, (c) is `load_atm_iv_at_horizon` returning None because the nearest expiry exceeds `2 × target_dte`. Report which, don't loosen the guard.

- [ ] **Step 3: Commit**

```bash
git add scripts/research/magnet_cone_calibration.py \
        docs/research/2026-08-08-magnet-cone-calibration/
git commit -m "feat(research): E1 cone calibration runner with full trace persistence"
```

---

## Task 5: `all_pivots` and the `last_pivot_index` refactor

**Files:**
- Create: `src/uw_scan/cards/magnets.py`
- Modify: `src/uw_scan/cards/technicals.py:528-556` (`last_pivot_index`)
- Test: `tests/unit/test_magnets_pivots.py`

**Interfaces:**
- Consumes: `uw_scan.cards.technicals.atr14`.
- Produces:
  - `Pivot` — `NamedTuple(index: int, kind: str, price: float)`, `kind` in `{"top", "bottom"}`
  - `all_pivots(df: pd.DataFrame, k: float = 3.0) -> list[Pivot]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_magnets_pivots.py
import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.magnets import Pivot, all_pivots
from uw_scan.cards.technicals import last_pivot_index


def _frame(closes: list[float]) -> pd.DataFrame:
    """OHLC frame from a close path; high/low straddle close so ATR is non-zero."""
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": c, "high": c * 1.01, "low": c * 0.99, "close": c}
    )


def _zigzag(n_legs: int, amplitude: float, leg_len: int) -> list[float]:
    out: list[float] = [100.0]
    up = True
    for _ in range(n_legs):
        target = out[-1] * (1 + amplitude) if up else out[-1] * (1 - amplitude)
        out.extend(np.linspace(out[-1], target, leg_len)[1:].tolist())
        up = not up
    return out


def test_pivots_alternate_top_and_bottom():
    df = _frame(_zigzag(6, 0.30, 12))
    pivots = all_pivots(df, k=3.0)
    assert len(pivots) >= 2
    kinds = [p.kind for p in pivots]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))


def test_pivot_price_matches_the_close_at_its_index():
    df = _frame(_zigzag(6, 0.30, 12))
    for p in all_pivots(df, k=3.0):
        assert p.price == pytest.approx(float(df["close"].iloc[p.index]))


def test_higher_threshold_yields_no_more_pivots():
    df = _frame(_zigzag(8, 0.25, 10))
    assert len(all_pivots(df, k=5.0)) <= len(all_pivots(df, k=2.0))


def test_monotonic_series_confirms_no_pivots():
    df = _frame(np.linspace(100.0, 300.0, 200).tolist())
    assert all_pivots(df, k=3.0) == []


def test_short_series_returns_empty():
    assert all_pivots(_frame([100.0] * 10), k=3.0) == []


def test_last_pivot_index_is_unchanged_by_the_refactor():
    """Regression guard: the wrapper must reproduce the legacy contract exactly,
    including the len-126 fallback when nothing confirms."""
    df = _frame(_zigzag(6, 0.30, 12))
    pivots = all_pivots(df, k=3.0)
    assert last_pivot_index(df) == pivots[-1].index

    flat = _frame(np.linspace(100.0, 300.0, 200).tolist())
    assert last_pivot_index(flat) == max(0, len(flat) - 126)

    tiny = _frame([100.0] * 10)
    assert last_pivot_index(tiny) == 0


def test_pivot_is_a_named_tuple_with_stable_field_order():
    p = Pivot(3, "top", 101.5)
    assert (p.index, p.kind, p.price) == (3, "top", 101.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_magnets_pivots.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.cards.magnets'`

- [ ] **Step 3: Implement `all_pivots`**

```python
# src/uw_scan/cards/magnets.py
"""Magnet-view geometry (spec 2026-08-08 §4).

Plan A ships `all_pivots` only — E2 needs it. `magnet_levels`, `cone` and
`build_read` arrive in Plan B, after the research gates resolve.

The ZigZag threshold is in ATR(14) units rather than a fixed percentage, which
is why this is worth keeping over the reference's own detector: an ATR threshold
adapts to each ticker's volatility instead of applying one percentage to a $20
stock and a $900 one.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pandas as pd

from uw_scan.cards.technicals import atr14


class Pivot(NamedTuple):
    index: int
    kind: str    # "top" | "bottom"
    price: float


def all_pivots(df: pd.DataFrame, k: float = 3.0) -> list[Pivot]:
    """Every confirmed ATR-zigzag pivot, oldest first.

    A pivot is a swing extreme that LATER reverses by >= k * ATR(14). Confirmation
    is retrospective by construction, so the newest extreme is never a pivot until
    price has moved away from it — that lag is the price of not repainting.
    """
    if len(df) < 30:
        return []
    close = df["close"].to_numpy(dtype=float)
    atr = atr14(df).to_numpy(dtype=float)
    n = len(close)
    pivots: list[Pivot] = []
    direction = 1 if close[min(20, n - 1)] >= close[0] else -1
    ext_i = 0
    for i in range(1, n):
        thr = k * atr[i] if math.isfinite(atr[i]) and atr[i] > 0 else math.inf
        if direction == 1:
            if close[i] >= close[ext_i]:
                ext_i = i
            elif close[ext_i] - close[i] >= thr:
                pivots.append(Pivot(ext_i, "top", float(close[ext_i])))
                direction, ext_i = -1, i
        else:
            if close[i] <= close[ext_i]:
                ext_i = i
            elif close[i] - close[ext_i] >= thr:
                pivots.append(Pivot(ext_i, "bottom", float(close[ext_i])))
                direction, ext_i = 1, i
    return pivots
```

- [ ] **Step 4: Replace `last_pivot_index` body with the wrapper**

In `src/uw_scan/cards/technicals.py`, replace the entire body of `last_pivot_index` (currently lines 528–556) below its docstring with:

```python
def last_pivot_index(df: pd.DataFrame, *, k: float = 3.0) -> int:
    """Most recent confirmed ATR-zigzag pivot index.

    Pivot = a swing extreme that later reverses by >= k * ATR(14). Falls back
    to len-126 when no pivot confirms (young or drift-only series).

    Thin wrapper over cards.magnets.all_pivots — the detection loop lives there
    because the magnet view needs the whole pivot list, not just the last index.
    Behaviour is unchanged; tests/unit/test_magnets_pivots.py guards that.
    """
    from uw_scan.cards.magnets import all_pivots  # local: magnets imports atr14

    if len(df) < 30:
        return 0
    pivots = all_pivots(df, k=k)
    if not pivots:
        return max(0, len(df) - 126)
    return pivots[-1].index
```

The import is function-local to avoid a circular import: `cards.magnets` imports `atr14` from `cards.technicals` at module level.

- [ ] **Step 5: Run the new tests and the full technicals suite**

Run:
```bash
uv run pytest tests/unit/test_magnets_pivots.py -v
uv run pytest tests/ -k technical -v
```
Expected: new file 7 passed; existing technicals tests unchanged and passing.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/magnets.py src/uw_scan/cards/technicals.py \
        tests/unit/test_magnets_pivots.py
git commit -m "feat: extract all_pivots, last_pivot_index becomes a wrapper"
```

---

## Task 6: First-passage and the block-bootstrap null

**Files:**
- Create: `src/uw_scan/reports/magnet_passage.py`
- Test: `tests/unit/test_magnet_passage.py`

**Interfaces:**
- Consumes: `uw_scan.cards.magnets.Pivot`.
- Produces:
  - `measured_move(resistance: float, support: float, ratio: float = 0.618) -> tuple[float, float]` → `(stretch, down)`
  - `first_passage(highs, lows, up: float, down: float, max_bars: int) -> str` → `"hit" | "stop" | "ambiguous" | "neither"`
  - `bootstrap_null_hit_rate(returns, start_price, up, down, max_bars, *, block: int, n_paths: int, seed: int) -> dict` — keys `hit`, `stop`, `ambiguous`, `neither`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_magnet_passage.py
import numpy as np
import pytest

from uw_scan.reports.magnet_passage import (
    bootstrap_null_hit_rate,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_magnet_passage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.magnet_passage'`

- [ ] **Step 3: Implement**

```python
# src/uw_scan/reports/magnet_passage.py
"""E2 — does the 0.618 measured-move target beat a matched null? (spec §3.4)

A rising leg has upward drift baked into its own definition, so a high raw hit
rate is exactly what "no edge" looks like. The comparison is therefore against a
BLOCK-BOOTSTRAP null built from the ticker's own returns: it preserves drift,
volatility, fat tails and autocorrelation without estimating any of them, which
sidesteps the drift-estimation problem that makes a parametric GBM null
unusable over 161 days.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def measured_move(
    resistance: float, support: float, ratio: float = 0.618
) -> tuple[float, float]:
    """(stretch, down) = R + ratio*leg, S - ratio*leg where leg = R - S."""
    if resistance <= support:
        raise ValueError(f"resistance {resistance} must exceed support {support}")
    leg = resistance - support
    return resistance + ratio * leg, support - ratio * leg


def first_passage(
    highs: Sequence[float],
    lows: Sequence[float],
    up: float,
    down: float,
    max_bars: int,
) -> str:
    """Which barrier price touches first: "hit" | "stop" | "ambiguous" | "neither".

    Uses high/low rather than close because a target is touched intrabar. When a
    single bar spans BOTH barriers the intrabar order is unknowable from daily
    data — that returns "ambiguous" and is reported as its own bucket. Assigning
    it to either side would silently bias the hit rate in whichever direction was
    guessed.
    """
    for i in range(min(max_bars, len(highs), len(lows))):
        touched_up = highs[i] >= up
        touched_down = lows[i] <= down
        if touched_up and touched_down:
            return "ambiguous"
        if touched_up:
            return "hit"
        if touched_down:
            return "stop"
    return "neither"


def bootstrap_null_hit_rate(
    returns: Sequence[float],
    start_price: float,
    up: float,
    down: float,
    max_bars: int,
    *,
    block: int,
    n_paths: int,
    seed: int,
) -> dict:
    """Outcome shares under paths resampled from the ticker's own log returns.

    Synthetic paths carry no intrabar range, so both barriers are tested against
    the same synthetic close. That makes "ambiguous" impossible in the null and
    is why the observed sample reports it separately rather than folding it in.
    """
    rets = np.asarray(returns, dtype=float)
    rets = rets[np.isfinite(rets)]
    if rets.size < block:
        raise ValueError(f"sample of {rets.size} shorter than block {block}")
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(max_bars / block))
    starts_hi = rets.size - block + 1
    counts = {"hit": 0, "stop": 0, "ambiguous": 0, "neither": 0}
    for _ in range(n_paths):
        starts = rng.integers(0, starts_hi, size=n_blocks)
        path_rets = np.concatenate([rets[s : s + block] for s in starts])[:max_bars]
        path = start_price * np.exp(np.cumsum(path_rets))
        counts[first_passage(path, path, up, down, max_bars)] += 1
    return {kind: n / n_paths for kind, n in counts.items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_magnet_passage.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/magnet_passage.py tests/unit/test_magnet_passage.py
git commit -m "feat(research): 0.618 first-passage with block-bootstrap null"
```

---

## Task 7: E2 sweep runner

**Files:**
- Create: `scripts/research/magnet_first_passage.py`

**Interfaces:**
- Consumes: Tasks 1, 5, 6; `uw_scan.backtest.sweep.run_sweep`; `uw_scan.storage.backtest_repository.BacktestRepository`.
- Produces: rows in `backtest_sweep_runs` / `backtest_sweep_results` under `strategy='magnet_first_passage'`, plus `docs/research/2026-08-08-magnet-cone-calibration/first_passage_legs.csv`.

- [ ] **Step 1: Write the runner**

```python
#!/usr/bin/env python3
"""E2 — does R + 0.618*leg get touched before S? (spec §3.4)

Sweeps the ATR-zigzag threshold and scores each setting against a block-bootstrap
null built from each ticker's own returns.

Reproduce:
    uv run python scripts/research/magnet_first_passage.py \
        --dsn "dbname=option_wizard_local" \
        --out docs/research/2026-08-08-magnet-cone-calibration

GATE G1
    If no k_atr shows an OOS hit rate materially above its null, STRETCH/DOWN
    ship as unlabelled geometry and the "+30.7% target" framing is dropped
    entirely. G1 failing does NOT cancel the view.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from uw_scan.backtest.splitters import time_ordered_holdout
from uw_scan.backtest.sweep import run_sweep
from uw_scan.cards.magnets import all_pivots
from uw_scan.reports.magnet_data import load_adjusted_closes
from uw_scan.reports.magnet_passage import bootstrap_null_hit_rate, first_passage, measured_move
from uw_scan.storage.backtest_repository import BacktestRepository

K_GRID = (2.0, 2.5, 3.0, 3.5, 4.0)
MAX_BARS = 60
HOLDOUT_FRAC = 0.4
N_NULL_PATHS = 400
NULL_BLOCK = 5


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def rising_legs(df: pd.DataFrame, k: float) -> list[dict]:
    """One row per rising leg: the state the reference calls ON THE WAY UP.

    A leg is defined by (top pivot A, bottom pivot B) where B is the LATER of the
    two and price is measured forward from B's confirmation. Only pairs where
    R > S produce a measured move.
    """
    pivots = all_pivots(df, k=k)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    out: list[dict] = []
    for a, b in zip(pivots, pivots[1:]):
        if not (a.kind == "top" and b.kind == "bottom"):
            continue
        if a.price <= b.price:
            continue
        stretch, down_level = measured_move(a.price, b.price)
        # Entry is the bar AFTER the bottom pivot confirms, never the pivot bar
        # itself — the pivot is only knowable in hindsight.
        entry = b.index + 1
        if entry >= len(df):
            continue
        outcome = first_passage(
            high[entry:], low[entry:], up=stretch, down=b.price, max_bars=MAX_BARS
        )
        out.append(
            {
                "entry_index": entry,
                "entry_date": df["date"].iloc[entry],
                "resistance": a.price,
                "support": b.price,
                "stretch": stretch,
                "down": down_level,
                "outcome": outcome,
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="dbname=option_wizard_local")
    ap.add_argument("--schema", default="uw_scan")
    ap.add_argument("--out", default="docs/research/2026-08-08-magnet-cone-calibration")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.dsn) as conn:
        tickers = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT ticker FROM {args.schema}.option_surface_grid_daily ORDER BY ticker"
            ).fetchall()
        ]
        prices = {t: load_adjusted_closes(conn, t, args.schema) for t in tickers}
        prices = {t: df for t, df in prices.items() if len(df) >= 200}

        all_rows: list[dict] = []

        def run_one(config: dict) -> dict:
            k = config["k_atr"]
            legs: list[dict] = []
            null_hits: list[float] = []
            for t, df in prices.items():
                tl = rising_legs(df, k)
                for row in tl:
                    row["ticker"] = t
                    row["k_atr"] = k
                legs.extend(tl)
                if tl:
                    rets = np.diff(np.log(df["close"].to_numpy(dtype=float)))
                    for row in tl:
                        null = bootstrap_null_hit_rate(
                            rets,
                            float(df["close"].iloc[row["entry_index"]]),
                            up=row["stretch"],
                            down=row["support"],
                            max_bars=MAX_BARS,
                            block=NULL_BLOCK,
                            n_paths=N_NULL_PATHS,
                            seed=20260808,
                        )
                        null_hits.append(null["hit"])
            all_rows.extend(legs)
            if not legs:
                return {"metrics": {"n_legs": 0}, "gates": {"g1_beats_null": False}, "n_trades": 0}

            _, holdout = time_ordered_holdout(
                legs, key=lambda r: r["entry_date"], frac=HOLDOUT_FRAC
            )
            def share(rows: list[dict], kind: str) -> float:
                return sum(1 for r in rows if r["outcome"] == kind) / len(rows) if rows else float("nan")

            metrics = {
                "n_legs": len(legs),
                "hit": share(legs, "hit"),
                "stop": share(legs, "stop"),
                "ambiguous": share(legs, "ambiguous"),
                "neither": share(legs, "neither"),
                "null_hit_mean": float(np.mean(null_hits)) if null_hits else float("nan"),
                "edge_vs_null": (
                    share(legs, "hit") - float(np.mean(null_hits)) if null_hits else float("nan")
                ),
                "oos_n_legs": len(holdout),
                "oos_hit": share(holdout, "hit"),
                "oos_edge_vs_null": (
                    share(holdout, "hit") - float(np.mean(null_hits))
                    if null_hits and holdout
                    else float("nan")
                ),
            }
            gates = {
                "g1_beats_null": bool(
                    metrics["oos_edge_vs_null"] == metrics["oos_edge_vs_null"]  # not NaN
                    and metrics["oos_edge_vs_null"] > 0.0
                )
            }
            return {"metrics": metrics, "gates": gates, "n_trades": len(legs)}

        repo = BacktestRepository(conn, schema=args.schema)
        result = run_sweep(
            [{"k_atr": k} for k in K_GRID],
            run_one,
            repo=repo,
            strategy="magnet_first_passage",
            reproduce_cmd=(
                "uv run python scripts/research/magnet_first_passage.py "
                f"--dsn '{args.dsn}' --out {args.out}"
            ),
            params_grid={
                "k_atr": list(K_GRID),
                "max_bars": MAX_BARS,
                "holdout_frac": HOLDOUT_FRAC,
                "n_null_paths": N_NULL_PATHS,
                "null_block": NULL_BLOCK,
            },
            git_sha=git_sha(),
            notes=(
                "E2 spec 2026-08-08 §3.4. Null is a block bootstrap of each "
                "ticker's own returns; 'ambiguous' = both barriers inside one bar "
                "and is NOT folded into hit or stop."
            ),
        )

    if all_rows:
        pd.DataFrame(all_rows).to_csv(out_dir / "first_passage_legs.csv", index=False)
    print(json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2, default=str))
    for r in result["results"]:
        print(json.dumps(r, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and confirm both the DB rows and the CSV land**

Run:
```bash
uv run python scripts/research/magnet_first_passage.py \
  --dsn "dbname=option_wizard_local" \
  --out docs/research/2026-08-08-magnet-cone-calibration

uv run python -c "
import psycopg
with psycopg.connect('dbname=option_wizard_local') as c:
    print(c.execute(\"SELECT id, strategy, n_error FROM uw_scan.backtest_sweep_runs WHERE strategy='magnet_first_passage' ORDER BY id DESC LIMIT 1\").fetchone())
    print(c.execute('SELECT count(*) FROM uw_scan.backtest_sweep_results').fetchone())
"
ls -la docs/research/2026-08-08-magnet-cone-calibration/first_passage_legs.csv
```
Expected: one run row, 5 result rows (one per `k_atr`), `n_error = 0`, CSV present.

- [ ] **Step 3: Commit**

```bash
git add scripts/research/magnet_first_passage.py \
        docs/research/2026-08-08-magnet-cone-calibration/
git commit -m "feat(research): E2 first-passage sweep persisted to backtest_sweep_*"
```

---

## Task 8: Verdict note and gate evaluation

**Files:**
- Create: `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md`

**Interfaces:**
- Consumes: `summary.json`, `by_ticker.csv`, `first_passage_legs.csv`, `backtest_sweep_results`.
- Produces: a written G1/G2/G3 ruling that Plan B is written against.

- [ ] **Step 1: Write the verdict note from the measured numbers**

Create `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md` with this exact structure, filling every `<>` from the artifacts — no rounding beyond 4 significant figures, no numbers typed from memory:

```markdown
# Magnet view — Phase 1 research verdict

**Date run:** <YYYY-MM-DD>
**Spec:** docs/superpowers/specs/2026-08-08-technicals-magnet-view-design.md
**Git SHA:** <from summary.json>

## Reproduce

    uv run python scripts/research/magnet_cone_calibration.py --dsn <dsn> --out <dir>
    uv run python scripts/research/magnet_first_passage.py    --dsn <dsn> --out <dir>

## Sample

| Horizon | Observations | Tickers included | Tickers excluded (<100 obs) |
|---|---|---|---|
| 5d | <n> | <n> | <n> |
| 10d | <n> | <n> | <n> |

21d withheld — 6 independent windows per ticker, no power. Revisit once the
surface accrues; it is forward-only and cannot be backfilled.

## E1 — cone calibration

| Horizon | cov@1σ (nominal 68.3%) | cov@1.96σ (nominal 95.0%) | k (std) | k (MAD) | k 95% CI (block bootstrap) | mean(z) diagnostic |
|---|---|---|---|---|---|---|
| 5d | <> | <> | <> | <> | <> | <> |
| 10d | <> | <> | <> | <> | <> | <> |

## E2 — 0.618 first passage

| k_atr | n legs | hit | stop | ambiguous | neither | null hit | edge vs null | OOS edge |
|---|---|---|---|---|---|---|---|---|
| 2.0 | | | | | | | | |
| 2.5 | | | | | | | | |
| 3.0 | | | | | | | | |
| 3.5 | | | | | | | | |
| 4.0 | | | | | | | | |

## Gate rulings

- **G1 — some k_atr beats the drift-matched null OOS:** PASS / FAIL — <one line>
  - If FAIL: STRETCH/DOWN ship as unlabelled geometry, role text becomes
    "0.618 extension (no measured edge)", the read drops its target sentences,
    and the "+30.7%" headline framing is dropped.
- **G2 — calibrated cone reaches nominal coverage OOS:** 5d PASS/FAIL, 10d PASS/FAIL
  - Any FAIL: that horizon is withheld from the view.
- **G3 — per-ticker k dispersion exceeds pooled OOS error:** PASS / FAIL
  - If FAIL: one pooled constant k = <value> ships. No table, no refit job.

## Chosen production parameters

- `k_atr` = <value or "n/a, G1 failed">
- `k_shrink` = <pooled value, or "per-ticker table" if G3 passed>
- Horizons shipped: <5d / 10d / both / none>

## What this does NOT establish

- Whether 0.618 specifically is load-bearing. Alternatives (0.5, 1.0, 1.618)
  were not tested; that is out of scope.
- Any earnings conditioning. ATM IV widens into a print and the cone widens with
  it; no earnings flag is surfaced.
- Regime stability of k. It is fit once and frozen, with no staleness monitor.
```

- [ ] **Step 2: Verify every placeholder is filled**

Run: `grep -n '<' docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md`
Expected: no output. Any remaining `<>` is an unfilled placeholder and a plan failure.

- [ ] **Step 3: Run the full test suite before declaring Phase 1 done**

Run:
```bash
uv run pytest tests/unit/test_magnet_data.py tests/unit/test_magnet_calibration.py \
              tests/unit/test_magnet_passage.py tests/unit/test_magnets_pivots.py -v
uv run pytest tests/ -q
uv run ruff check src/ scripts/ tests/
```
Expected: all pass, ruff clean. Report actual output — do not claim green without it.

- [ ] **Step 4: Commit**

```bash
git add docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md
git commit -m "docs(research): Phase 1 verdict — G1/G2/G3 rulings for magnet view"
```

---

## Done criteria

Phase 1 is complete when `VERDICT.md` contains no unfilled placeholders and states an explicit PASS/FAIL for G1, G2 and G3 with the chosen production parameters. Plan B is written against that file, not against this plan's assumptions.
