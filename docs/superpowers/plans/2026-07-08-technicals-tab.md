# Quant Technicals Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Technicals` tab to `/stock/[ticker]` — dimensionless technical analytics (z-vs-200DMA, MA kinematics, sigmoid trend-maturity, return distribution, RSI/MACD enhanced, relative strength) plus the forward-return-by-z-band conditioning table, backed by apex daily bars, persisted to Postgres, served by a dedicated API endpoint.

**Architecture:** Two PRs at the backend/web seam. PR 1: pure compute in `cards/technicals.py` → `technical_daily` table (migration `101`) + standalone `TechnicalsRepository` → `GET /api/stock/{ticker}/technicals` → nightly worker job fetching apex `/bars/{T}?timeframe=1d`. PR 2: `TechnicalsTab` client island (bare `{ticker}` prop, fetches itself) + hand-rolled SVG panels, wired into `TabBar` at index 1.

**Tech Stack:** Python 3.13/uv, pandas + numpy + scipy (`curve_fit` — first scipy consumer in `src/`), psycopg 3, FastAPI/Pydantic v2, Next.js 16 + React 19, vitest.

**Spec:** `docs/superpowers/specs/2026-07-06-quant-technicals-page-design.md`

**Decisions locked here** (were open in the spec — flag to user if wrong):
1. **Forward-return storage = JSONB column** `forward_returns` on the latest `technical_daily` row (older rows NULLed on refresh). Rejected the sidecar table: the table is a recomputed-nightly per-ticker aggregate; one table, zero joins.
2. **RS benchmark = SPY only** (spec v1 default).

## Global Constraints

- `uv run` everything; never bare `python`/`pytest`/`pip`.
- Migration file is `101_technical_daily.sql` (highest today: `100_job_failures.sql`; lexical apply, no tracking table → idempotent, header `SET search_path TO uw_scan, public;`, `BEGIN/COMMIT`, `IF NOT EXISTS` everywhere — copy `087_data_freshness_snapshots.sql` style).
- New storage domain = standalone `storage/technicals_repository.py`. NEVER add methods to `storage/repository.py`.
- Public Pydantic models: subclass `_UwBase`, call `_preserve_public_module(...)` at module bottom, export via `models/__init__.py` `__all__` (OpenAPI component names must not drift).
- Every `except` block logs `repr(exc)` or re-raises (CI Guardrail 2, `scripts/_lint_except.py`).
- Crons: `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`; **weekdays are Monday=0** so `0-4` = Mon–Fri (house convention, see existing jobs).
- No Yahoo anywhere (CI-enforced). Data source: apex only (`APEX_API_URL`, default `http://100.66.147.98:8322`).
- Prices in this domain are **float** end-to-end (chart-grade data; deliberate deviation from the Decimal-at-boundaries card rule — mark with a `# ponytail:` comment in `cards/technicals.py`'s docstring). Money math elsewhere keeps Decimal.
- apex `/bars/{T}?timeframe=1d` verified live 2026-07-08: `{symbol, timeframe, bars:[{time: "2026-07-07T00:00:00+00:00", open, high, low, close, volume, vwap}], count}` — `time` is an ISO-8601 UTC string; **count is 500 today, 2000 pending apex-side change**. All compute degrades to whatever count returns; never assume 2000.
- CHANGELOG `[Unreleased]` entry rides each feature PR (before merge).
- OpenAPI snapshot (`tests/integration/api/openapi.snapshot.json`) must be regenerated with **exactly** `sort_keys=True, ensure_ascii=True, indent=2` — anything else reorders thousands of lines; if `git diff --stat` shows more than the intended additions, STOP and reconcile.
- Full local repro of the CI `lint + unit` job (run before every push):

```bash
python3 scripts/release/version_sync_check.py
uv sync --extra postgres
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_no_yahoo.py
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -v
# guardrail greps:
! grep -rE 'class _Fake(Cursor|Connection)' tests/integration/
! grep -rE '"\|".join\(' src/
! grep -rE 'from tests' src/
! grep -rE 'from uw_scan\.fixtures' src/
```

Integration locally: `uv run pytest tests/integration/ -n auto` (needs local Postgres; `UW_SCAN_TEST_DB_NAME=option_wizard_test`).

## File Map

**PR 1 — `feat/technicals-backend`:**
- Create: `src/uw_scan/cards/technicals.py` (pure compute, no DB/no I/O)
- Create: `tests/unit/test_technicals.py`
- Modify: `src/uw_scan/sources/apex.py` (add `fetch_daily_bars`)
- Create: `src/uw_scan/storage/migrations/101_technical_daily.sql`
- Create: `src/uw_scan/storage/technicals_repository.py`
- Create: `tests/integration/storage/test_technicals_repository.py`
- Create: `src/uw_scan/models/technicals.py`; Modify: `src/uw_scan/models/__init__.py`
- Create: `src/uw_scan/reports/technicals.py`
- Modify: `src/uw_scan/api/routers/stock.py` (one new route)
- Modify: `tests/integration/api/openapi.snapshot.json` (regen)
- Create: `tests/integration/api/test_technicals_endpoint.py`
- Create: `src/uw_scan/worker/jobs/technical_daily_refresh.py`
- Modify: `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`
- Create: `tests/integration/worker/test_technicals_job.py`
- Create: `scripts/backfill/technicals_refresh_backfill.py` (manual/one-off runner — the sanctioned non-/tmp path)
- Modify: `CHANGELOG.md`

**PR 2 — `feat/technicals-web`** (branch from main after PR 1 merges):
- Modify: `web/lib/types.ts` (via `npm run gen:types` — regenerate wholesale, never hand-edit)
- Modify: `web/lib/api.ts`, `web/components/stock/TabBar.tsx`, `web/app/stock/[ticker]/[tab]/page.tsx`
- Create: `web/components/stock/tabs/TechnicalsTab.tsx` (client island)
- Create: `web/components/stock/panels/TechnicalsKpiStrip.tsx`, `TechnicalsAnchorChart.tsx`, `TechnicalsZChart.tsx`, `ForwardReturnTable.tsx`, `TechnicalsDetailPanels.tsx`
- Create: `web/tests/unit/TechnicalsPanels.test.tsx`, `web/tests/e2e/technicals-tab.spec.ts`
- Modify: `CHANGELOG.md`

---

# PR 1 — backend (`feat/technicals-backend`)

Create the branch first: `git checkout -b feat/technicals-backend` (from up-to-date `main`).

### Task 1: `cards/technicals.py` — frame, indicators, z/bands, slope regime, kinematics

**Files:**
- Create: `src/uw_scan/cards/technicals.py`
- Test: `tests/unit/test_technicals.py`

**Interfaces (produces — later tasks import these exact names):**
- `bars_frame(bars: list[dict]) -> pd.DataFrame` — columns `as_of` (date), `open/high/low/close/volume` (float), sorted, deduped
- `Z_BANDS: list[tuple[float, float, str]]`, `z_band_label(z: float | None) -> str | None`
- `atr14(df) -> pd.Series`, `rsi14(close: pd.Series) -> pd.Series`, `macd_hist(close, fast=8, slow=17, signal=9) -> pd.Series`
- `z_vs_200dma(close: pd.Series, z_window: int = 252) -> pd.Series`
- `sma200_slope_ann(close: pd.Series, lookback: int = 21) -> pd.Series`
- `slope_regime(slope_ann: float | None) -> str | None`
- `ma_kinematics(df: pd.DataFrame, *, reg_window: int = 10) -> dict` — keys `sma20/sma50/sma200` (each `{slope_atr, curv_atr, tstat}`) + `alignment: int` in [-3, 3]

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_technicals.py`:

```python
"""Unit tests for uw_scan.cards.technicals — pure math, synthetic labeled series."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from uw_scan.cards.technicals import (
    bars_frame,
    ma_kinematics,
    rsi14,
    slope_regime,
    sma200_slope_ann,
    z_band_label,
    z_vs_200dma,
)


def _bar(day: int, close: float, spread: float = 1.0) -> dict:
    # Synthetic labeled bar in the verified apex shape (ISO time string).
    d = pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=day)
    return {
        "time": d.isoformat(),
        "open": close,
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": 1000,
        "vwap": None,
    }


def test_bars_frame_sorts_dedupes_and_dates():
    bars = [_bar(2, 102.0), _bar(0, 100.0), _bar(1, 101.0), _bar(2, 103.0)]
    df = bars_frame(bars)
    assert list(df["close"]) == [100.0, 101.0, 103.0]  # dedup keeps last
    assert df["as_of"].iloc[0].isoformat() == "2020-01-01"


def test_bars_frame_empty():
    assert bars_frame([]).empty


def test_z_band_label_boundaries():
    assert z_band_label(0.0) == "NEUTRAL"
    assert z_band_label(0.5) == "MILD HIGH"        # lo-inclusive
    assert z_band_label(-2.5) == "DEEPLY OVERSOLD"
    assert z_band_label(2.0) == "DEEPLY OVERBOUGHT"
    assert z_band_label(None) is None
    assert z_band_label(float("nan")) is None


def test_z_vs_200dma_flat_then_jump():
    # 400 flat closes, then a step: distance from the 200DMA is positive,
    # z is positive and finite.
    close = pd.Series([100.0] * 400 + [110.0] * 30)
    z = z_vs_200dma(close)
    assert math.isfinite(float(z.iloc[-1]))
    assert float(z.iloc[-1]) > 1.0
    assert pd.isna(z.iloc[100])  # not enough history yet


def test_sma200_slope_ann_constant_growth():
    # close grows exactly 0.05%/day => sma200 grows 0.05%/day once warm;
    # annualized = 1.0005^252 - 1.
    close = pd.Series([100.0 * (1.0005**i) for i in range(500)])
    s = sma200_slope_ann(close)
    assert float(s.iloc[-1]) == pytest.approx(1.0005**252 - 1.0, rel=1e-3)


def test_slope_regime_labels():
    assert slope_regime(0.15) == "STRONG UPTREND"
    assert slope_regime(0.05) == "UPTREND"
    assert slope_regime(0.0) == "FLAT"
    assert slope_regime(-0.05) == "DOWNTREND"
    assert slope_regime(-0.15) == "STRONG DOWNTREND"
    assert slope_regime(None) is None


def test_rsi14_all_up_saturates_high():
    close = pd.Series([100.0 + i for i in range(50)])
    r = rsi14(close)
    assert float(r.iloc[-1]) > 95.0


def test_ma_kinematics_uptrend_alignment():
    bars = [_bar(i, 100.0 * (1.001**i)) for i in range(300)]
    df = bars_frame(bars)
    kin = ma_kinematics(df)
    assert kin["alignment"] == 3  # close > sma20 > sma50 > sma200
    assert kin["sma20"]["slope_atr"] > 0
    assert kin["sma200"]["tstat"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_technicals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.cards.technicals'`

- [ ] **Step 3: Write the implementation**

Create `src/uw_scan/cards/technicals.py`:

```python
"""Pure technicals derivers for the Technicals tab. No DB access, no I/O.

Spec: docs/superpowers/specs/2026-07-06-quant-technicals-page-design.md
Everything is a z-score or ratio (dimensionless, cross-ticker comparable).

# ponytail: prices are float end-to-end here — chart-grade series, not money
# math. Decimal boundary conversion buys nothing for ±1e-9 on a z-score.
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# (lo, hi, label) — lo-inclusive, hi-exclusive.
Z_BANDS: list[tuple[float, float, str]] = [
    (-math.inf, -2.0, "DEEPLY OVERSOLD"),
    (-2.0, -1.5, "OVERSOLD"),
    (-1.5, -1.0, "STRETCHED LOW"),
    (-1.0, -0.5, "MILD LOW"),
    (-0.5, 0.5, "NEUTRAL"),
    (0.5, 1.0, "MILD HIGH"),
    (1.0, 1.5, "STRETCHED HIGH"),
    (1.5, 2.0, "OVERBOUGHT"),
    (2.0, math.inf, "DEEPLY OVERBOUGHT"),
]


def z_band_label(z: float | None) -> str | None:
    if z is None:
        return None
    try:
        zf = float(z)
    except (TypeError, ValueError) as exc:
        log.debug("z coercion skipped: %s", repr(exc))
        return None
    if not math.isfinite(zf):
        return None
    for lo, hi, label in Z_BANDS:
        if lo <= zf < hi:
            return label
    return None


def _lastf(s: pd.Series) -> float | None:
    """Last value of a series as a finite float, else None."""
    if len(s) == 0:
        return None
    v = s.iloc[-1]
    if pd.isna(v):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def bars_frame(bars: list[dict]) -> pd.DataFrame:
    """Coerce an apex /bars payload (time = ISO-8601 UTC string) into a
    sorted, deduped daily frame with an ``as_of`` date column."""
    cols = ["as_of", "open", "high", "low", "close", "volume"]
    if not bars:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(bars)
    df["as_of"] = pd.to_datetime(df["time"], utc=True).dt.date
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return (
        df[cols]
        .dropna(subset=["close"])
        .drop_duplicates(subset=["as_of"], keep="last")
        .sort_values("as_of")
        .reset_index(drop=True)
    )


def atr14(df: pd.DataFrame) -> pd.Series:
    """Wilder ATR(14)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean()


def rsi14(close: pd.Series) -> pd.Series:
    """Wilder RSI(14)."""
    delta = close.diff()
    up = delta.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = up / dn.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def macd_hist(
    close: pd.Series, fast: int = 8, slow: int = 17, signal: int = 9
) -> pd.Series:
    """MACD histogram, Shepherd's 8/17/9 default."""
    macd = (
        close.ewm(span=fast, adjust=False).mean()
        - close.ewm(span=slow, adjust=False).mean()
    )
    return macd - macd.ewm(span=signal, adjust=False).mean()


def z_vs_200dma(close: pd.Series, z_window: int = 252) -> pd.Series:
    """Price distance from the 200 DMA in σ of that distance.

    z_t = (close_t - sma200_t) / rolling_std(close - sma200, z_window).
    No mean subtraction: distance 0 == sitting on the MA, by construction.
    """
    sma200 = close.rolling(200).mean()
    dist = close - sma200
    sd = dist.rolling(z_window, min_periods=126).std()
    return dist / sd.replace(0.0, np.nan)


def sma200_slope_ann(close: pd.Series, lookback: int = 21) -> pd.Series:
    """Annualized growth rate of the 200 DMA over the last `lookback` sessions."""
    sma200 = close.rolling(200).mean()
    return (sma200 / sma200.shift(lookback)) ** (252.0 / lookback) - 1.0


def slope_regime(slope_ann: float | None) -> str | None:
    if slope_ann is None:
        return None
    try:
        s = float(slope_ann)
    except (TypeError, ValueError) as exc:
        log.debug("slope coercion skipped: %s", repr(exc))
        return None
    if not math.isfinite(s):
        return None
    if s >= 0.10:
        return "STRONG UPTREND"
    if s >= 0.02:
        return "UPTREND"
    if s > -0.02:
        return "FLAT"
    if s > -0.10:
        return "DOWNTREND"
    return "STRONG DOWNTREND"


def ma_kinematics(df: pd.DataFrame, *, reg_window: int = 10) -> dict:
    """ATR-normalized velocity/acceleration + slope t-stat per SMA, plus a
    three-pair alignment score in [-3, 3].

    slope_atr: OLS slope of the last `reg_window` SMA values / ATR(14) —
    dimensionless "ATRs per day". curv_atr: change in that slope vs the
    window ending 5 sessions earlier. tstat: slope / SE(slope) — replaces
    crossover folklore with a significance readout.
    """
    close = df["close"]
    atr = atr14(df)
    atr_now = _lastf(atr)
    out: dict[str, object] = {}
    for n in (20, 50, 200):
        key = f"sma{n}"
        sma = close.rolling(n).mean().dropna()
        if len(sma) < reg_window + 5 or atr_now is None or atr_now <= 0:
            out[key] = {"slope_atr": None, "curv_atr": None, "tstat": None}
            continue
        t = np.arange(reg_window, dtype=float)
        y = sma.tail(reg_window).to_numpy(dtype=float)
        slope, intercept = np.polyfit(t, y, 1)
        resid = y - (slope * t + intercept)
        denom = float(np.sum((t - t.mean()) ** 2))
        se = math.sqrt(float(np.sum(resid**2)) / (reg_window - 2) / denom)
        y_prev = sma.iloc[:-5].tail(reg_window).to_numpy(dtype=float)
        prev_slope = np.polyfit(t, y_prev, 1)[0] if len(y_prev) == reg_window else None
        out[key] = {
            "slope_atr": float(slope) / atr_now,
            "curv_atr": (float(slope - prev_slope) / atr_now)
            if prev_slope is not None
            else None,
            "tstat": (float(slope) / se) if se > 0 else None,
        }
    alignment = 0
    px = _lastf(close)
    sma_vals = {n: _lastf(close.rolling(n).mean()) for n in (20, 50, 200)}
    pairs = [
        (px, sma_vals[20]),
        (sma_vals[20], sma_vals[50]),
        (sma_vals[50], sma_vals[200]),
    ]
    for a, b in pairs:
        if a is not None and b is not None:
            alignment += 1 if a > b else -1
    out["alignment"] = alignment
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_technicals.py -v`
Expected: all PASS

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/uw_scan/cards/technicals.py tests/unit/test_technicals.py
uv run python scripts/_lint_except.py src
git add src/uw_scan/cards/technicals.py tests/unit/test_technicals.py
git commit -m "feat(technicals): card frame, indicators, z-vs-200DMA, bands, kinematics"
```

---

### Task 2: `cards/technicals.py` — ATR-zigzag pivot + sigmoid trend-maturity fit

**Files:**
- Modify: `src/uw_scan/cards/technicals.py` (append)
- Test: `tests/unit/test_technicals.py` (append)

**Interfaces (produces):**
- `last_pivot_index(df: pd.DataFrame, *, k: float = 3.0) -> int` — index of the most recent confirmed pivot (fallback `max(0, n-126)`)
- `fit_sigmoid(closes: np.ndarray) -> dict` — keys `valid: bool`, `phase: str | None` (`EARLY|ACCELERATING|DECELERATING|SATURATED`), `k`, `s`, `r2_sigmoid`, `r2_linear`, `n`

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_technicals.py`)

```python
import numpy as np

from uw_scan.cards.technicals import fit_sigmoid, last_pivot_index


def test_last_pivot_index_v_shape():
    # 100 up-days, 100 down-days, 100 up-days: last confirmed pivot is the
    # trough near index 199 (zigzag confirms after a k*ATR reversal).
    closes = (
        [100.0 + i for i in range(100)]
        + [199.0 - i for i in range(100)]
        + [100.0 + i for i in range(100)]
    )
    bars = [_bar(i, c) for i, c in enumerate(closes)]
    piv = last_pivot_index(bars_frame(bars))
    assert 190 <= piv <= 205


def test_fit_sigmoid_on_synthetic_s_curve():
    t = np.arange(120, dtype=float)
    closes = 100.0 + 100.0 / (1.0 + np.exp(-0.15 * (t - 60.0)))
    out = fit_sigmoid(closes)
    assert out["valid"] is True
    assert out["r2_sigmoid"] > out["r2_linear"]
    assert out["k"] == pytest.approx(0.15, abs=0.03)
    # t_now=119, t0≈60 => s = k*(119-60) ≈ 8.85 => SATURATED
    assert out["phase"] == "SATURATED"


def test_fit_sigmoid_rejects_linear_series():
    closes = np.array([100.0 + 0.5 * i for i in range(120)])
    out = fit_sigmoid(closes)
    assert out["valid"] is False  # beats-linear guard: no S-curve structure


def test_fit_sigmoid_too_short():
    assert fit_sigmoid(np.array([100.0, 101.0]))["valid"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_technicals.py -v -k "pivot or sigmoid"`
Expected: FAIL — `ImportError: cannot import name 'fit_sigmoid'`

- [ ] **Step 3: Write the implementation** (append to `src/uw_scan/cards/technicals.py`)

```python
def last_pivot_index(df: pd.DataFrame, *, k: float = 3.0) -> int:
    """Most recent confirmed ATR-zigzag pivot index.

    Pivot = a swing extreme that later reverses by >= k * ATR(14). Falls back
    to len-126 when no pivot confirms (young or drift-only series).
    """
    close = df["close"].to_numpy(dtype=float)
    atr = atr14(df).to_numpy(dtype=float)
    n = len(close)
    if n < 30:
        return 0
    pivots: list[int] = []
    direction = 1 if close[min(20, n - 1)] >= close[0] else -1
    ext_i = 0
    for i in range(1, n):
        thr = k * atr[i] if math.isfinite(atr[i]) and atr[i] > 0 else math.inf
        if direction == 1:
            if close[i] >= close[ext_i]:
                ext_i = i
            elif close[ext_i] - close[i] >= thr:
                pivots.append(ext_i)
                direction, ext_i = -1, i
        else:
            if close[i] <= close[ext_i]:
                ext_i = i
            elif close[i] - close[ext_i] >= thr:
                pivots.append(ext_i)
                direction, ext_i = 1, i
    if not pivots:
        return max(0, n - 126)
    return pivots[-1]


def fit_sigmoid(closes: np.ndarray) -> dict:
    """Fit logistic b + L/(1+e^(-k(t-t0))) to a price segment; only *valid*
    when it beats a plain linear fit (r2_sigmoid >= 0.80 AND >= r2_linear
    + 0.05 AND k > 0) — the honesty guard from the spec."""
    out: dict[str, object] = {
        "valid": False,
        "phase": None,
        "k": None,
        "s": None,
        "r2_sigmoid": None,
        "r2_linear": None,
        "n": int(len(closes)),
    }
    if len(closes) < 30 or not np.all(np.isfinite(closes)):
        return out
    from scipy.optimize import curve_fit  # first scipy consumer in src/

    t = np.arange(len(closes), dtype=float)

    def logistic(tt: np.ndarray, big_l: float, kk: float, t0: float, b: float):
        return b + big_l / (1.0 + np.exp(-np.clip(kk * (tt - t0), -500.0, 500.0)))

    ss_tot = float(np.sum((closes - closes.mean()) ** 2)) or 1.0
    lin = np.polyval(np.polyfit(t, closes, 1), t)
    r2_lin = 1.0 - float(np.sum((closes - lin) ** 2)) / ss_tot
    out["r2_linear"] = r2_lin
    span = float(closes.max() - closes.min()) or 1.0
    sign = 1.0 if closes[-1] >= closes[0] else -1.0
    p0 = [sign * span, 0.1, len(closes) / 2.0, float(closes[0])]
    try:
        popt, _ = curve_fit(logistic, t, closes, p0=p0, maxfev=10000)
    except Exception as exc:
        log.debug("sigmoid fit failed: %s", repr(exc))
        return out
    fit = logistic(t, *popt)
    r2_sig = 1.0 - float(np.sum((closes - fit) ** 2)) / ss_tot
    kk, t0 = float(popt[1]), float(popt[2])
    s = kk * (float(t[-1]) - t0)
    out.update({"r2_sigmoid": r2_sig, "k": kk, "s": s})
    if r2_sig >= 0.80 and r2_sig >= r2_lin + 0.05 and kk > 0:
        out["valid"] = True
        if s < -2.0:
            out["phase"] = "EARLY"
        elif s < 0.0:
            out["phase"] = "ACCELERATING"
        elif s <= 2.0:
            out["phase"] = "DECELERATING"
        else:
            out["phase"] = "SATURATED"
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_technicals.py -v`
Expected: all PASS. Also verify scipy imports cleanly: `uv run python -c "from uw_scan.cards.technicals import fit_sigmoid; print('scipy ok')"` → `scipy ok`

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/technicals.py tests/unit/test_technicals.py
git commit -m "feat(technicals): ATR-zigzag pivot + sigmoid trend-maturity fit with beats-linear guard"
```

---

### Task 3: `cards/technicals.py` — distribution, RSI/MACD enhanced, RS, forward-return table ⭐, composite, builders

**Files:**
- Modify: `src/uw_scan/cards/technicals.py` (append)
- Test: `tests/unit/test_technicals.py` (append)

**Interfaces (produces — Tasks 6–8 consume the builders):**
- `return_distribution(close: pd.Series) -> dict` — `{rv20, rv20_z, vol_of_vol, skew60, kurt60, jerk20}`
- `rsi_enhanced(df) -> dict` — `{rsi14, rsi_z, rsi_slope5, divergence: {type, rsi_gap} | None}`
- `macd_enhanced(df) -> dict` — `{hist_atr, hist_atr_slope3}`
- `relative_strength(df, spy_df) -> dict` — `{ratio, ma60, ma200, trend, n}`
- `forward_return_table(close: pd.Series, z: pd.Series, horizons: tuple[int, ...] = (20, 40, 60)) -> list[dict]` — rows `{band, horizon, count, mean, median, win_rate}`
- `composite_score(*, alignment, slope_tstat_200, macd_hist_atr, rsi_z) -> float | None`
- `build_technical_series(bars: list[dict], spy_bars: list[dict] | None = None) -> pd.DataFrame` — per-day columns: `as_of, close, sma20, sma50, sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime, rsi14, macd_hist_atr, rs_ratio`
- `build_technical_snapshot(bars, spy_bars=None) -> dict | None` — latest-day blob: `{as_of, bars_n, close, sma20, sma50, sma200, dist_pct, z, z_band, slope_ann, slope_regime, kinematics, sigmoid, distribution, rsi, macd, rs, composite, forward_returns}`; `None` when `< 210` bars

- [ ] **Step 1: Write the failing tests** (append — the forward-return test is the money path; every number is hand-computed)

```python
from uw_scan.cards.technicals import (
    build_technical_series,
    build_technical_snapshot,
    composite_score,
    forward_return_table,
    relative_strength,
)


def test_forward_return_table_hand_verified():
    # ⭐ Money path. 12 closes; horizon 2. Injected z assigns:
    #  - sessions 0..3  -> z=0.0  (NEUTRAL)
    #  - sessions 4..7  -> z=1.7  (OVERBOUGHT)
    #  - sessions 8..11 -> z=-1.7 (OVERSOLD)   (no forward bar at h=2 for 10,11)
    closes = pd.Series(
        [100.0, 110.0, 99.0, 105.0, 100.0, 100.0, 90.0, 95.0, 100.0, 100.0, 105.0, 95.0]
    )
    z = pd.Series([0.0] * 4 + [1.7] * 4 + [-1.7] * 4)
    rows = forward_return_table(closes, z, horizons=(2,))
    by_band = {r["band"]: r for r in rows}

    # NEUTRAL fwd 2d: 99/100-1=-0.01, 105/110-1=-0.045454..,
    #                 100/99-1=+0.010101.., 100/105-1=-0.047619..
    neutral = by_band["NEUTRAL"]
    assert neutral["count"] == 4
    assert neutral["mean"] == pytest.approx(
        (-0.01 - 0.0454545454 + 0.0101010101 - 0.0476190476) / 4, abs=1e-9
    )
    assert neutral["win_rate"] == pytest.approx(0.25)  # only +0.0101 wins

    # OVERBOUGHT fwd 2d from closes 100,100,90,95 -> 90/100-1=-0.10,
    #  95/100-1=-0.05, 100/90-1=+0.111111.., 100/95-1=+0.0526315789
    ob = by_band["OVERBOUGHT"]
    assert ob["count"] == 4
    assert ob["median"] == pytest.approx((-0.05 + 0.0526315789) / 2, abs=1e-9)
    assert ob["win_rate"] == pytest.approx(0.5)

    # OVERSOLD: sessions 8,9 have forward bars (105/100-1, 95/100-1);
    # 10,11 fall off the end and MUST be excluded (look-ahead discipline).
    osold = by_band["OVERSOLD"]
    assert osold["count"] == 2
    assert osold["mean"] == pytest.approx((0.05 - 0.05) / 2, abs=1e-12)


def test_forward_return_table_empty_bands_omitted():
    closes = pd.Series([100.0, 101.0, 102.0, 103.0])
    z = pd.Series([0.0, 0.0, 0.0, 0.0])
    rows = forward_return_table(closes, z, horizons=(1,))
    assert {r["band"] for r in rows} == {"NEUTRAL"}


def test_relative_strength_outperforming():
    bars = [_bar(i, 100.0 * (1.002**i)) for i in range(300)]
    spy = [_bar(i, 100.0 * (1.0005**i)) for i in range(300)]
    rs = relative_strength(bars_frame(bars), bars_frame(spy))
    assert rs["trend"] == "OUTPERFORMING"
    assert rs["ratio"] > rs["ma60"] > rs["ma200"]


def test_composite_score_bounded_and_none_safe():
    assert composite_score(
        alignment=3, slope_tstat_200=10.0, macd_hist_atr=5.0, rsi_z=4.0
    ) == pytest.approx(1.0, abs=0.05)
    assert composite_score(
        alignment=None, slope_tstat_200=None, macd_hist_atr=None, rsi_z=None
    ) is None


def test_build_technical_snapshot_thin_history_returns_none():
    bars = [_bar(i, 100.0 + i * 0.1) for i in range(150)]
    assert build_technical_snapshot(bars) is None


def test_build_technical_snapshot_full():
    bars = [_bar(i, 100.0 * (1.0008**i) * (1 + 0.01 * math.sin(i / 7))) for i in range(500)]
    spy = [_bar(i, 100.0 * (1.0004**i)) for i in range(500)]
    snap = build_technical_snapshot(bars, spy)
    assert snap is not None
    assert snap["bars_n"] == 500
    assert snap["z_band"] in {label for _, _, label in __import__("uw_scan.cards.technicals", fromlist=["Z_BANDS"]).Z_BANDS}
    assert isinstance(snap["forward_returns"], list) and snap["forward_returns"]
    assert {r["horizon"] for r in snap["forward_returns"]} <= {20, 40, 60}
    series = build_technical_series(bars, spy)
    assert list(series.columns) == [
        "as_of", "close", "sma20", "sma50", "sma200", "z_vs_200dma", "z_band",
        "sma200_slope_ann", "slope_regime", "rsi14", "macd_hist_atr", "rs_ratio",
    ]
    assert len(series) == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_technicals.py -v -k "forward or relative or composite or snapshot"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write the implementation** (append to `src/uw_scan/cards/technicals.py`)

```python
def return_distribution(close: pd.Series) -> dict:
    """20d realized σ z-scored vs its own 252d history, vol-of-vol,
    60d skew/kurtosis, and second-difference 'jerkiness'."""
    rets = close.pct_change()
    rv20 = rets.rolling(20).std() * math.sqrt(252)
    mu = rv20.rolling(252, min_periods=126).mean()
    sd = rv20.rolling(252, min_periods=126).std()
    return {
        "rv20": _lastf(rv20),
        "rv20_z": _lastf((rv20 - mu) / sd.replace(0.0, np.nan)),
        "vol_of_vol": _lastf(rv20.diff().rolling(60).std()),
        "skew60": _lastf(rets.rolling(60).skew()),
        "kurt60": _lastf(rets.rolling(60).kurt()),
        "jerk20": _lastf(rets.diff().rolling(20).std()),
    }


def _local_extrema_idx(
    vals: np.ndarray, *, order: int = 5, lookback: int = 120, mode: str = "max"
) -> list[int]:
    n = len(vals)
    start = max(order, n - lookback)
    idx: list[int] = []
    for i in range(start, n - order):
        win = vals[i - order : i + order + 1]
        if mode == "max" and vals[i] == win.max():
            idx.append(i)
        elif mode == "min" and vals[i] == win.min():
            idx.append(i)
    return idx


def rsi_enhanced(df: pd.DataFrame) -> dict:
    """RSI(14) z-scored vs its 252d distribution, 5d slope, and a
    pivot-based divergence detector (price HH + RSI LH => BEARISH)."""
    close = df["close"]
    r = rsi14(close)
    mu = r.rolling(252, min_periods=126).mean()
    sd = r.rolling(252, min_periods=126).std()
    divergence = None
    vals = close.to_numpy(dtype=float)
    highs = _local_extrema_idx(vals, mode="max")
    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        if vals[i2] > vals[i1] and float(r.iloc[i2]) < float(r.iloc[i1]):
            divergence = {"type": "BEARISH", "rsi_gap": float(r.iloc[i1] - r.iloc[i2])}
    if divergence is None:
        lows = _local_extrema_idx(vals, mode="min")
        if len(lows) >= 2:
            i1, i2 = lows[-2], lows[-1]
            if vals[i2] < vals[i1] and float(r.iloc[i2]) > float(r.iloc[i1]):
                divergence = {
                    "type": "BULLISH",
                    "rsi_gap": float(r.iloc[i2] - r.iloc[i1]),
                }
    return {
        "rsi14": _lastf(r),
        "rsi_z": _lastf((r - mu) / sd.replace(0.0, np.nan)),
        "rsi_slope5": _lastf(r.diff(5) / 5.0),
        "divergence": divergence,
    }


def macd_enhanced(df: pd.DataFrame) -> dict:
    """MACD(8/17/9) histogram normalized by ATR(14) + its 3d derivative.
    Cross-sectional watchlist percentile is a read-time report concern."""
    hist_atr = macd_hist(df["close"]) / atr14(df).replace(0.0, np.nan)
    return {
        "hist_atr": _lastf(hist_atr),
        "hist_atr_slope3": _lastf(hist_atr.diff(3) / 3.0),
    }


def relative_strength(df: pd.DataFrame, spy_df: pd.DataFrame) -> dict:
    """TICKER/SPY ratio + its 60/200d MAs. v1 benchmark = SPY only."""
    empty = {"ratio": None, "ma60": None, "ma200": None, "trend": None, "n": 0}
    if df.empty or spy_df.empty:
        return empty
    merged = df[["as_of", "close"]].merge(
        spy_df[["as_of", "close"]], on="as_of", suffixes=("", "_spy")
    )
    if len(merged) < 60:
        return {**empty, "n": int(len(merged))}
    ratio = merged["close"] / merged["close_spy"]
    out = {
        "ratio": _lastf(ratio),
        "ma60": _lastf(ratio.rolling(60).mean()),
        "ma200": _lastf(ratio.rolling(200).mean()),
        "trend": None,
        "n": int(len(merged)),
    }
    if out["ratio"] is not None and out["ma60"] is not None:
        out["trend"] = "OUTPERFORMING" if out["ratio"] > out["ma60"] else "UNDERPERFORMING"
    return out


def forward_return_table(
    close: pd.Series, z: pd.Series, horizons: tuple[int, ...] = (20, 40, 60)
) -> list[dict]:
    """⭐ Forward return conditioned on z-band. Look-ahead disciplined:
    the band at session t uses only data through t; the forward return uses
    only bars after t; sessions with no bar at t+h are excluded."""
    rows: list[dict] = []
    for h in horizons:
        fwd = close.shift(-h) / close - 1.0
        for lo, hi, label in Z_BANDS:
            mask = (z >= lo) & (z < hi)
            vals = fwd[mask].dropna()
            if len(vals) == 0:
                continue
            rows.append(
                {
                    "band": label,
                    "horizon": int(h),
                    "count": int(len(vals)),
                    "mean": float(vals.mean()),
                    "median": float(vals.median()),
                    "win_rate": float((vals > 0).mean()),
                }
            )
    return rows


def composite_score(
    *,
    alignment: int | None,
    slope_tstat_200: float | None,
    macd_hist_atr: float | None,
    rsi_z: float | None,
) -> float | None:
    """Trend-quality composite: mean of bounded sub-scores, each in [-1, 1].
    Sub-scores stay visible upstream — never a black box."""
    parts: list[float] = []
    if alignment is not None:
        parts.append(alignment / 3.0)
    for v, scale in ((slope_tstat_200, 2.0), (macd_hist_atr, 1.0), (rsi_z, 2.0)):
        if v is not None and math.isfinite(v):
            parts.append(math.tanh(v / scale))
    return float(np.mean(parts)) if parts else None


def build_technical_series(
    bars: list[dict], spy_bars: list[dict] | None = None
) -> pd.DataFrame:
    """Per-day storable series (one row per session) for technical_daily."""
    df = bars_frame(bars)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "as_of", "close", "sma20", "sma50", "sma200", "z_vs_200dma",
                "z_band", "sma200_slope_ann", "slope_regime", "rsi14",
                "macd_hist_atr", "rs_ratio",
            ]
        )
    close = df["close"]
    out = df[["as_of", "close"]].copy()
    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["z_vs_200dma"] = z_vs_200dma(close)
    out["z_band"] = out["z_vs_200dma"].map(z_band_label)
    out["sma200_slope_ann"] = sma200_slope_ann(close)
    out["slope_regime"] = out["sma200_slope_ann"].map(slope_regime)
    out["rsi14"] = rsi14(close)
    out["macd_hist_atr"] = macd_hist(close) / atr14(df).replace(0.0, np.nan)
    if spy_bars:
        spy = bars_frame(spy_bars)[["as_of", "close"]].rename(
            columns={"close": "close_spy"}
        )
        out = out.merge(spy, on="as_of", how="left")
        out["rs_ratio"] = out["close"] / out["close_spy"]
        out = out.drop(columns=["close_spy"])
    else:
        out["rs_ratio"] = np.nan
    return out


def build_technical_snapshot(
    bars: list[dict], spy_bars: list[dict] | None = None
) -> dict | None:
    """Latest-day rich snapshot. None when <210 bars (200 SMA + slack) —
    callers surface 'too thin' rather than a silently wrong z."""
    df = bars_frame(bars)
    if len(df) < 210:
        return None
    series = build_technical_series(bars, spy_bars)
    close = df["close"]
    kin = ma_kinematics(df)
    pivot = last_pivot_index(df)
    if len(df) - pivot < 30:
        pivot = max(0, len(df) - 126)
    sig = fit_sigmoid(close.to_numpy(dtype=float)[pivot:])
    rsi_d = rsi_enhanced(df)
    macd_d = macd_enhanced(df)
    rs = relative_strength(df, bars_frame(spy_bars)) if spy_bars else None
    last = series.iloc[-1]
    px, sma200 = _lastf(close), _lastf(series["sma200"])
    return {
        "as_of": last["as_of"],
        "bars_n": int(len(df)),
        "close": px,
        "sma20": _lastf(series["sma20"]),
        "sma50": _lastf(series["sma50"]),
        "sma200": sma200,
        "dist_pct": (px / sma200 - 1.0) if px and sma200 else None,
        "z": _lastf(series["z_vs_200dma"]),
        "z_band": last["z_band"] if pd.notna(last["z_band"]) else None,
        "slope_ann": _lastf(series["sma200_slope_ann"]),
        "slope_regime": last["slope_regime"] if pd.notna(last["slope_regime"]) else None,
        "kinematics": kin,
        "sigmoid": sig,
        "distribution": return_distribution(close),
        "rsi": rsi_d,
        "macd": macd_d,
        "rs": rs,
        "composite": composite_score(
            alignment=kin.get("alignment"),
            slope_tstat_200=(kin.get("sma200") or {}).get("tstat"),
            macd_hist_atr=macd_d.get("hist_atr"),
            rsi_z=rsi_d.get("rsi_z"),
        ),
        "forward_returns": forward_return_table(close, series["z_vs_200dma"]),
    }
```

- [ ] **Step 4: Run the full unit file**

Run: `uv run pytest tests/unit/test_technicals.py -v`
Expected: all PASS (including the hand-verified forward-return numbers — if `test_forward_return_table_hand_verified` fails, the money path is wrong; fix the code, not the test).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/ tests/
uv run python scripts/_lint_except.py src
git add src/uw_scan/cards/technicals.py tests/unit/test_technicals.py
git commit -m "feat(technicals): distribution/RSI/MACD/RS derivers, forward-return-by-z-band table, composite, builders"
```

---

### Task 4: `sources/apex.py` — daily-bars fetcher

**Files:**
- Modify: `src/uw_scan/sources/apex.py` (append one function; do not touch the existing xenon/5m code)
- Test: `tests/unit/test_apex_daily_bars.py` (create)

**Interfaces (produces):** `fetch_daily_bars(ticker: str, *, timeout: float = 20.0) -> list[dict]` — raw apex bar dicts; `[]` on any failure (never-raise, matching the module contract).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_apex_daily_bars.py`:

```python
"""fetch_daily_bars — never-raise apex daily bar fetch (httpx monkeypatched)."""

from __future__ import annotations

import httpx

from uw_scan.sources import apex


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


def test_fetch_daily_bars_happy_path(monkeypatch):
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp(
            {"symbol": "SPY", "bars": [{"time": "2026-07-07T00:00:00+00:00", "close": 747.71}]}
        )

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    bars = apex.fetch_daily_bars("spy")
    assert bars == [{"time": "2026-07-07T00:00:00+00:00", "close": 747.71}]
    assert captured["url"].endswith("/bars/SPY")
    assert captured["params"] == {"timeframe": "1d"}


def test_fetch_daily_bars_never_raises(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    assert apex.fetch_daily_bars("SPY") == []


def test_fetch_daily_bars_malformed_payload(monkeypatch):
    monkeypatch.setattr(
        apex.httpx, "get", lambda *a, **k: _Resp({"bars": "not-a-list"})
    )
    assert apex.fetch_daily_bars("SPY") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_apex_daily_bars.py -v`
Expected: FAIL — `AttributeError: module 'uw_scan.sources.apex' has no attribute 'fetch_daily_bars'`

- [ ] **Step 3: Write the implementation** (append to `src/uw_scan/sources/apex.py`)

```python
def fetch_daily_bars(ticker: str, *, timeout: float = 20.0) -> list[dict]:
    """Full default daily-bar window from apex (500 today, 2000 once apex's
    cap raise lands). Raw bar dicts; [] on any failure (never-raise)."""
    url = f"{_apex_url()}/bars/{ticker.upper()}"
    try:
        resp = httpx.get(url, params={"timeframe": "1d"}, timeout=timeout)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
    except Exception as exc:
        logger.warning("apex daily bars fetch failed %s: %s", ticker, repr(exc))
        return []
    if not isinstance(bars, list):
        logger.warning("apex daily bars malformed for %s: bars is %s", ticker, type(bars).__name__)
        return []
    return bars
```

- [ ] **Step 4: Run tests; live smoke**

Run: `uv run pytest tests/unit/test_apex_daily_bars.py -v` → all PASS
Live smoke (MacBook, Tailscale up): `uv run python -c "from uw_scan.sources.apex import fetch_daily_bars; b = fetch_daily_bars('SPY'); print(len(b), b[-1]['time'], b[-1]['close'])"`
Expected: `500 <recent ISO date> <plausible SPY close ~700s>` (or `2000 ...` once apex's cap change lands; `0` only if Tailscale/apex is down — rerun when reachable, do not proceed on 0 without noting it).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/apex.py tests/unit/test_apex_daily_bars.py
git commit -m "feat(technicals): apex fetch_daily_bars (never-raise, full default window)"
```

---

### Task 5: Migration 101 + `TechnicalsRepository`

**Files:**
- Create: `src/uw_scan/storage/migrations/101_technical_daily.sql`
- Create: `src/uw_scan/storage/technicals_repository.py`
- Test: `tests/integration/storage/test_technicals_repository.py`

**Interfaces (produces):**
- `TechnicalsRepository(conn: psycopg.Connection, schema: str = "uw_scan")`
- `.upsert_series(ticker: str, rows: list[dict]) -> int` — rows are `build_technical_series` records (`as_of` may be `datetime.date`; NaN → None handled by caller-side sanitize helper `series_records`, also defined here)
- `.set_latest_detail(ticker: str, as_of: date, *, detail: dict, forward_returns: list[dict]) -> None` — writes JSONB on the latest row, NULLs older rows' blobs
- `.fetch_series(ticker: str, *, limit: int = 504) -> list[dict]` — ascending by `as_of`
- `.fetch_latest(ticker: str) -> dict | None`
- `.fetch_latest_macd_all() -> list[dict]` — `{ticker, macd_hist_atr}` at each ticker's max `as_of`
- Module function: `series_records(df: pd.DataFrame) -> list[dict]` — DataFrame → JSON-safe dicts (NaN→None, numpy scalars→python)

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/101_technical_daily.sql`:

```sql
-- 101_technical_daily.sql
--
-- Per-(ticker, session) technicals snapshot for the /stock Technicals tab.
-- Nightly technical_daily_refresh recomputes the full series from apex daily
-- bars and upserts every row (idempotent). detail + forward_returns JSONB are
-- populated ONLY on each ticker's latest row (older rows NULLed on refresh).
-- Prices are DOUBLE PRECISION by design: chart-grade series, not money math.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.technical_daily (
    ticker            TEXT NOT NULL,
    as_of             DATE NOT NULL,
    close             DOUBLE PRECISION,
    sma20             DOUBLE PRECISION,
    sma50             DOUBLE PRECISION,
    sma200            DOUBLE PRECISION,
    z_vs_200dma       DOUBLE PRECISION,
    z_band            TEXT,
    sma200_slope_ann  DOUBLE PRECISION,
    slope_regime      TEXT,
    rsi14             DOUBLE PRECISION,
    macd_hist_atr     DOUBLE PRECISION,
    rs_ratio          DOUBLE PRECISION,
    bars_n            INTEGER,
    detail            JSONB,          -- latest row only: kinematics/sigmoid/distribution/rsi/macd/rs/composite
    forward_returns   JSONB,          -- latest row only: band x horizon conditioning table
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, as_of)
);

CREATE INDEX IF NOT EXISTS ix_technical_daily_asof
    ON uw_scan.technical_daily (as_of DESC);

COMMIT;
```

- [ ] **Step 2: Verify migration prefix + idempotency**

```bash
uv run python scripts/check_migration_prefixes.py            # expected: clean
bash scripts/migrate.sh && bash scripts/migrate.sh           # run twice: second run must be a no-op (no errors)
```

- [ ] **Step 3: Write the failing integration test**

Create `tests/integration/storage/test_technicals_repository.py`:

```python
"""Integration tests for TechnicalsRepository (real Postgres)."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.technicals_repository import TechnicalsRepository


def _row(d: date, close: float, z: float | None = None) -> dict:
    return {
        "as_of": d, "close": close, "sma20": close, "sma50": close,
        "sma200": close, "z_vs_200dma": z, "z_band": "NEUTRAL" if z is not None else None,
        "sma200_slope_ann": 0.05, "slope_regime": "UPTREND", "rsi14": 55.0,
        "macd_hist_atr": 0.1, "rs_ratio": 1.0,
    }


def test_upsert_fetch_roundtrip_and_idempotency(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    trepo = TechnicalsRepository(repo.conn)
    rows = [_row(date(2026, 7, 6), 100.0, 0.2), _row(date(2026, 7, 7), 101.0, 0.3)]
    assert trepo.upsert_series("NVDA", rows) == 2
    assert trepo.upsert_series("NVDA", rows) == 2  # idempotent re-run

    got = trepo.fetch_series("NVDA")
    assert [r["as_of"] for r in got] == [date(2026, 7, 6), date(2026, 7, 7)]
    assert got[-1]["close"] == 101.0

    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM technical_daily WHERE ticker = 'NVDA'")
        assert cur.fetchone()[0] == 2  # upsert, not duplicate insert


def test_set_latest_detail_nulls_older_rows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    trepo = TechnicalsRepository(repo.conn)
    d1, d2 = date(2026, 7, 6), date(2026, 7, 7)
    trepo.upsert_series("NVDA", [_row(d1, 100.0), _row(d2, 101.0)])
    trepo.set_latest_detail("NVDA", d1, detail={"composite": 0.5}, forward_returns=[])
    trepo.set_latest_detail(
        "NVDA", d2,
        detail={"composite": 0.6},
        forward_returns=[{"band": "NEUTRAL", "horizon": 40, "count": 10,
                          "mean": 0.01, "median": 0.008, "win_rate": 0.6}],
    )
    latest = trepo.fetch_latest("NVDA")
    assert latest["as_of"] == d2
    assert latest["detail"]["composite"] == 0.6
    assert latest["forward_returns"][0]["band"] == "NEUTRAL"
    series = trepo.fetch_series("NVDA")
    assert series[0]["detail"] is None  # older row's blob was NULLed


def test_fetch_latest_missing_ticker(seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    assert trepo.fetch_latest("ZZZZ") is None


def test_fetch_latest_macd_all(seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    trepo.upsert_series("AAA", [_row(date(2026, 7, 7), 100.0)])
    trepo.upsert_series("BBB", [_row(date(2026, 7, 6), 100.0), _row(date(2026, 7, 7), 101.0)])
    rows = trepo.fetch_latest_macd_all()
    assert {r["ticker"] for r in rows} >= {"AAA", "BBB"}
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/integration/storage/test_technicals_repository.py -v`
Expected: FAIL — `ModuleNotFoundError` (or table-missing if the module stub exists). Note: the session fixture drops/recreates the schema and applies ALL migrations, so 101 must exist (Step 1) before this passes.

- [ ] **Step 5: Write the repository**

Create `src/uw_scan/storage/technicals_repository.py` (standalone class per the never-grow-repository.py rule, modeled on `data_freshness_repository.py`):

```python
"""Standalone repository for the technical_daily domain (Technicals tab)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd
from psycopg import Connection
from psycopg.types.json import Jsonb

_SERIES_COLS = (
    "as_of", "close", "sma20", "sma50", "sma200", "z_vs_200dma", "z_band",
    "sma200_slope_ann", "slope_regime", "rsi14", "macd_hist_atr", "rs_ratio",
)


def series_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame from build_technical_series -> JSON/SQL-safe dicts
    (NaN/inf -> None, numpy scalars -> python)."""
    records: list[dict] = []
    for rec in df[list(_SERIES_COLS)].to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for k, v in rec.items():
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                clean[k] = None
            elif isinstance(v, float):
                clean[k] = float(v)
            elif hasattr(v, "item"):  # numpy scalar
                item = v.item()
                clean[k] = None if isinstance(item, float) and not math.isfinite(item) else item
            else:
                clean[k] = v
        records.append(clean)
    return records


class TechnicalsRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_series(self, ticker: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        params = [{**r, "ticker": ticker.upper()} for r in rows]
        sql = """
            INSERT INTO technical_daily
                (ticker, as_of, close, sma20, sma50, sma200, z_vs_200dma,
                 z_band, sma200_slope_ann, slope_regime, rsi14,
                 macd_hist_atr, rs_ratio)
            VALUES
                (%(ticker)s, %(as_of)s, %(close)s, %(sma20)s, %(sma50)s,
                 %(sma200)s, %(z_vs_200dma)s, %(z_band)s,
                 %(sma200_slope_ann)s, %(slope_regime)s, %(rsi14)s,
                 %(macd_hist_atr)s, %(rs_ratio)s)
            ON CONFLICT (ticker, as_of) DO UPDATE SET
                close            = EXCLUDED.close,
                sma20            = EXCLUDED.sma20,
                sma50            = EXCLUDED.sma50,
                sma200           = EXCLUDED.sma200,
                z_vs_200dma      = EXCLUDED.z_vs_200dma,
                z_band           = EXCLUDED.z_band,
                sma200_slope_ann = EXCLUDED.sma200_slope_ann,
                slope_regime     = EXCLUDED.slope_regime,
                rsi14            = EXCLUDED.rsi14,
                macd_hist_atr    = EXCLUDED.macd_hist_atr,
                rs_ratio         = EXCLUDED.rs_ratio,
                inserted_at      = now()
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def set_latest_detail(
        self, ticker: str, as_of: date, *, detail: dict, forward_returns: list[dict]
    ) -> None:
        t = ticker.upper()
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE technical_daily SET detail = NULL, forward_returns = NULL "
                "WHERE ticker = %s AND as_of <> %s AND detail IS NOT NULL",
                (t, as_of),
            )
            cur.execute(
                "UPDATE technical_daily SET detail = %s, forward_returns = %s, "
                "bars_n = %s WHERE ticker = %s AND as_of = %s",
                (Jsonb(detail), Jsonb(forward_returns), detail.get("bars_n"), t, as_of),
            )
        self._conn.commit()

    def fetch_series(self, ticker: str, *, limit: int = 504) -> list[dict]:
        sql = """
            SELECT * FROM (
                SELECT as_of, close, sma20, sma50, sma200, z_vs_200dma, z_band,
                       sma200_slope_ann, slope_regime, rsi14, macd_hist_atr,
                       rs_ratio, detail, forward_returns
                  FROM technical_daily
                 WHERE ticker = %s
                 ORDER BY as_of DESC
                 LIMIT %s
            ) t ORDER BY as_of ASC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), limit))
            cols = [c.name for c in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def fetch_latest(self, ticker: str) -> dict | None:
        sql = """
            SELECT ticker, as_of, close, sma20, sma50, sma200, z_vs_200dma,
                   z_band, sma200_slope_ann, slope_regime, rsi14,
                   macd_hist_atr, rs_ratio, bars_n, detail, forward_returns
              FROM technical_daily
             WHERE ticker = %s
             ORDER BY as_of DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description or []]
            return dict(zip(cols, row, strict=True))

    def fetch_latest_macd_all(self) -> list[dict]:
        sql = """
            SELECT DISTINCT ON (ticker) ticker, macd_hist_atr
              FROM technical_daily
             ORDER BY ticker, as_of DESC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)
            cols = [c.name for c in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
```

- [ ] **Step 6: Run integration tests**

Run: `uv run pytest tests/integration/storage/test_technicals_repository.py -v`
Expected: all PASS. Also run the migration suite to confirm nothing regressed: `uv run pytest tests/integration/storage/test_migrations.py -v` → PASS.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/migrations/101_technical_daily.sql src/uw_scan/storage/technicals_repository.py tests/integration/storage/test_technicals_repository.py
git commit -m "feat(technicals): migration 101 technical_daily + standalone TechnicalsRepository"
```

---

### Task 6: Models + report assembler + API route + OpenAPI snapshot

**Files:**
- Create: `src/uw_scan/models/technicals.py`
- Modify: `src/uw_scan/models/__init__.py` (import block + `__all__`)
- Create: `src/uw_scan/reports/technicals.py`
- Modify: `src/uw_scan/api/routers/stock.py`
- Modify: `tests/integration/api/openapi.snapshot.json` (regen)
- Test: `tests/integration/api/test_technicals_endpoint.py`

**Interfaces:**
- Consumes: `TechnicalsRepository` (Task 5), `Repository.conn` (`storage/_base.py:24`), `get_repo`/`get_settings` (`api/deps.py`)
- Produces: `GET /api/stock/{ticker}/technicals` → `TechnicalsResponse`; models `TechnicalsHeader`, `TechnicalsSeriesRow`, `ForwardReturnBandRow`, `TechnicalsResponse` importable `from uw_scan.models import ...`; `assemble_technicals(ticker: str, repo: Repository, *, schema: str) -> TechnicalsResponse`

- [ ] **Step 1: Write the failing API test**

Create `tests/integration/api/test_technicals_endpoint.py`:

```python
"""GET /api/stock/{ticker}/technicals — empty and ready paths."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.technicals_repository import TechnicalsRepository


def test_technicals_empty_when_no_rows(client, seeded_db_empty_cards):
    r = client.get("/api/stock/NVDA/technicals")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["backfill_status"] == "empty"
    assert body["series"] == []
    assert body["header"] is None


def test_technicals_ready_with_seeded_rows(client, seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    rows = [
        {
            "as_of": date(2026, 7, 6 + i), "close": 100.0 + i, "sma20": 100.0,
            "sma50": 99.0, "sma200": 95.0, "z_vs_200dma": 0.8, "z_band": "MILD HIGH",
            "sma200_slope_ann": 0.12, "slope_regime": "STRONG UPTREND",
            "rsi14": 60.0, "macd_hist_atr": 0.2, "rs_ratio": 1.05,
        }
        for i in range(2)
    ]
    trepo.upsert_series("NVDA", rows)
    trepo.set_latest_detail(
        "NVDA", date(2026, 7, 7),
        detail={
            "bars_n": 500, "composite": 0.55, "dist_pct": 0.06,
            "sigmoid": {"valid": False}, "kinematics": {"alignment": 3},
            "distribution": {}, "rsi": {}, "macd": {"hist_atr": 0.2}, "rs": {},
        },
        forward_returns=[{"band": "MILD HIGH", "horizon": 40, "count": 55,
                          "mean": 0.021, "median": 0.018, "win_rate": 0.62}],
    )

    r = client.get("/api/stock/nvda/technicals")
    assert r.status_code == 200
    body = r.json()
    assert body["backfill_status"] == "ready"
    assert body["as_of"] == "2026-07-07"
    assert body["header"]["z_band"] == "MILD HIGH"
    assert body["header"]["slope_regime"] == "STRONG UPTREND"
    assert len(body["series"]) == 2
    assert body["forward_returns"][0]["count"] == 55
    assert body["detail"]["composite"] == 0.55


def test_technicals_model_exports():
    from uw_scan.models import (  # noqa: F401
        ForwardReturnBandRow,
        TechnicalsHeader,
        TechnicalsResponse,
        TechnicalsSeriesRow,
    )

    assert TechnicalsResponse.__module__ == "uw_scan.models"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/api/test_technicals_endpoint.py -v`
Expected: FAIL — `ImportError` / 404.

- [ ] **Step 3: Write the models**

Create `src/uw_scan/models/technicals.py`:

```python
"""API contract models for the /stock Technicals tab."""

from __future__ import annotations

from datetime import date
from typing import Any

from uw_scan.models._base import _preserve_public_module, _UwBase


class TechnicalsHeader(_UwBase):
    price: float | None = None
    sma200: float | None = None
    dist_pct: float | None = None
    z: float | None = None
    z_band: str | None = None
    slope_ann: float | None = None
    slope_regime: str | None = None
    composite: float | None = None


class TechnicalsSeriesRow(_UwBase):
    as_of: date
    close: float | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    z: float | None = None
    rsi14: float | None = None
    macd_hist_atr: float | None = None
    rs_ratio: float | None = None


class ForwardReturnBandRow(_UwBase):
    band: str
    horizon: int
    count: int
    mean: float
    median: float
    win_rate: float


class TechnicalsResponse(_UwBase):
    ticker: str
    backfill_status: str  # "ready" | "empty"
    as_of: date | None = None
    bars_n: int | None = None
    header: TechnicalsHeader | None = None
    series: list[TechnicalsSeriesRow] = []
    detail: dict[str, Any] | None = None
    macd_watchlist_pctile: float | None = None
    forward_returns: list[ForwardReturnBandRow] = []


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
_preserve_public_module(
    TechnicalsHeader, TechnicalsSeriesRow, ForwardReturnBandRow, TechnicalsResponse
)
```

Then in `src/uw_scan/models/__init__.py`: add (in the import block, alongside the other domain imports)

```python
from .technicals import (
    ForwardReturnBandRow,
    TechnicalsHeader,
    TechnicalsResponse,
    TechnicalsSeriesRow,
)
```

and add `"ForwardReturnBandRow", "TechnicalsHeader", "TechnicalsResponse", "TechnicalsSeriesRow"` to `__all__` (keep the list's existing ordering convention).

- [ ] **Step 4: Write the assembler**

Create `src/uw_scan/reports/technicals.py`:

```python
"""Assemble the Technicals tab response from the warm store (read-only)."""

from __future__ import annotations

from uw_scan.models import (
    ForwardReturnBandRow,
    TechnicalsHeader,
    TechnicalsResponse,
    TechnicalsSeriesRow,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.technicals_repository import TechnicalsRepository


def assemble_technicals(
    ticker: str, repo: Repository, *, schema: str = "uw_scan"
) -> TechnicalsResponse:
    t = ticker.upper()
    trepo = TechnicalsRepository(repo.conn, schema=schema)
    latest = trepo.fetch_latest(t)
    if latest is None:
        return TechnicalsResponse(ticker=t, backfill_status="empty")
    detail = latest.get("detail") or {}
    series = [
        TechnicalsSeriesRow(
            as_of=r["as_of"],
            close=r["close"],
            sma20=r["sma20"],
            sma50=r["sma50"],
            sma200=r["sma200"],
            z=r["z_vs_200dma"],
            rsi14=r["rsi14"],
            macd_hist_atr=r["macd_hist_atr"],
            rs_ratio=r["rs_ratio"],
        )
        for r in trepo.fetch_series(t)
    ]
    header = TechnicalsHeader(
        price=latest["close"],
        sma200=latest["sma200"],
        dist_pct=detail.get("dist_pct"),
        z=latest["z_vs_200dma"],
        z_band=latest["z_band"],
        slope_ann=latest["sma200_slope_ann"],
        slope_regime=latest["slope_regime"],
        composite=detail.get("composite"),
    )
    pctile = _macd_watchlist_pctile(trepo, t, latest["macd_hist_atr"])
    return TechnicalsResponse(
        ticker=t,
        backfill_status="ready",
        as_of=latest["as_of"],
        bars_n=latest.get("bars_n"),
        header=header,
        series=series,
        detail=detail or None,
        macd_watchlist_pctile=pctile,
        forward_returns=[
            ForwardReturnBandRow(**row) for row in (latest.get("forward_returns") or [])
        ],
    )


def _macd_watchlist_pctile(
    trepo: TechnicalsRepository, ticker: str, value: float | None
) -> float | None:
    """Cross-sectional percentile of this ticker's ATR-normalized MACD
    histogram among all tickers' latest rows (read-time, cheap)."""
    if value is None:
        return None
    peers = [
        r["macd_hist_atr"]
        for r in trepo.fetch_latest_macd_all()
        if r["macd_hist_atr"] is not None
    ]
    if len(peers) < 2:
        return None
    below = sum(1 for v in peers if v <= value)
    return below / len(peers)
```

- [ ] **Step 5: Add the route** (in `src/uw_scan/api/routers/stock.py` — extend the existing router; no new router file)

Add to the imports: `from uw_scan.api.deps import get_repo, get_settings`, `from uw_scan.config import Settings`, `from uw_scan.models import TechnicalsResponse`, `from uw_scan.reports.technicals import assemble_technicals` (merge with existing import lines — don't duplicate `get_repo`). Then add:

```python
@router.get("/stock/{ticker}/technicals", response_model=TechnicalsResponse)
def get_stock_technicals(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsResponse:
    return assemble_technicals(ticker, repo, schema=settings.db_schema)
```

- [ ] **Step 6: Regenerate the OpenAPI snapshot** (exact serialization — anything else reorders thousands of lines)

```bash
uv run python -c "
import json
from pathlib import Path
from uw_scan.api.server import create_app
spec = create_app().openapi()
p = Path('tests/integration/api/openapi.snapshot.json')
p.write_text(json.dumps(spec, sort_keys=True, ensure_ascii=True, indent=2))
print('snapshot regenerated')
"
git diff --stat tests/integration/api/openapi.snapshot.json
```

Expected: ONE file changed, additions only in the technicals path + 4 new component schemas region. If the diff touches unrelated paths/schemas, STOP and reconcile (wrong serialization settings or unintended contract drift).

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/integration/api/test_technicals_endpoint.py tests/integration/api/test_openapi_snapshot.py -v
uv run pytest tests/unit/test_models_exports.py -v
```
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/models/technicals.py src/uw_scan/models/__init__.py src/uw_scan/reports/technicals.py src/uw_scan/api/routers/stock.py tests/integration/api/test_technicals_endpoint.py tests/integration/api/openapi.snapshot.json
git commit -m "feat(technicals): TechnicalsResponse models, assembler, GET /api/stock/{ticker}/technicals"
```

---

### Task 7: Worker job + scheduler + config + manual runner

**Files:**
- Create: `src/uw_scan/worker/jobs/technical_daily_refresh.py`
- Modify: `src/uw_scan/worker/scheduler.py` (import ~line 80 block; closure near the other `_xxx` closures; `add_job` inside `if "massive" in groups:` → `if _is_primary_worker(settings):`)
- Modify: `src/uw_scan/config.py` (`technicals_refresh_enabled` field + `from_env` mapping)
- Create: `scripts/backfill/technicals_refresh_backfill.py`
- Test: `tests/integration/worker/test_technicals_job.py`

**Interfaces:**
- Consumes: `fetch_daily_bars` (Task 4), `build_technical_series`/`build_technical_snapshot` (Task 3), `TechnicalsRepository`/`series_records` (Task 5), `repo.list_watchlist_cards()` (existing — each card has `.ticker`)
- Produces: `technical_daily_refresh(*, repo: Repository, settings: Settings, ticker_filter: list[str] | None = None) -> dict[str, Any]` returning `{"ok": int, "skipped_thin": int, "failed": int, "tickers": int}`

- [ ] **Step 1: Write the failing worker test**

Create `tests/integration/worker/test_technicals_job.py`:

```python
"""technical_daily_refresh — real DB, apex fetch monkeypatched."""

from __future__ import annotations

import pandas as pd

from uw_scan.storage.technicals_repository import TechnicalsRepository
from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh


def _fake_bars(n: int = 300, drift: float = 1.0008) -> list[dict]:
    out = []
    for i in range(n):
        ts = (pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(days=i)).isoformat()
        c = 100.0 * (drift**i)
        out.append({"time": ts, "open": c, "high": c + 1, "low": c - 1,
                    "close": c, "volume": 1000, "vwap": None})
    return out


def _settings():
    from tests.integration.conftest import _test_settings
    return _test_settings()


def test_refresh_writes_series_and_latest_detail(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    bars = _fake_bars(300)
    monkeypatch.setattr(
        "uw_scan.worker.jobs.technical_daily_refresh.fetch_daily_bars",
        lambda t, **kw: bars,
    )
    result = technical_daily_refresh(
        repo=repo, settings=_settings(), ticker_filter=["NVDA"]
    )
    assert result["ok"] == 2  # NVDA + SPY (benchmark always refreshed)
    trepo = TechnicalsRepository(repo.conn)
    latest = trepo.fetch_latest("NVDA")
    assert latest is not None
    assert latest["detail"] is not None
    assert latest["forward_returns"]
    assert len(trepo.fetch_series("NVDA")) == 300


def test_refresh_skips_thin_history_and_survives_fetch_failure(
    seeded_db_empty_cards, monkeypatch
):
    repo = seeded_db_empty_cards
    thin = _fake_bars(100)

    def fake_fetch(t, **kw):
        if t == "BOOM":
            raise RuntimeError("apex down")
        return thin

    monkeypatch.setattr(
        "uw_scan.worker.jobs.technical_daily_refresh.fetch_daily_bars", fake_fetch
    )
    result = technical_daily_refresh(
        repo=repo, settings=_settings(), ticker_filter=["NVDA", "BOOM"]
    )
    assert result["failed"] == 1        # BOOM logged, loop continued
    assert result["skipped_thin"] >= 1  # 100 bars < 210 floor
    assert TechnicalsRepository(repo.conn).fetch_latest("NVDA") is None
```

(If importing `_test_settings` from conftest is awkward, mirror how existing worker tests obtain `Settings` — check `tests/integration/worker/test_worker_jobs.py` and copy its idiom instead; the job only uses `settings.db_schema`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/worker/test_technicals_job.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the job**

Create `src/uw_scan/worker/jobs/technical_daily_refresh.py`:

```python
"""Nightly technicals refresh: apex daily bars -> full recomputed series +
latest-day detail/forward-return table per watchlist ticker. Idempotent."""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.cards.technicals import build_technical_series, build_technical_snapshot
from uw_scan.config import Settings
from uw_scan.sources.apex import fetch_daily_bars
from uw_scan.storage.repository import Repository
from uw_scan.storage.technicals_repository import TechnicalsRepository, series_records

log = logging.getLogger(__name__)


def technical_daily_refresh(
    *,
    repo: Repository,
    settings: Settings,
    ticker_filter: list[str] | None = None,
) -> dict[str, Any]:
    trepo = TechnicalsRepository(repo.conn, schema=settings.db_schema)
    if ticker_filter is not None:
        watch = [t.upper() for t in ticker_filter]
    else:
        watch = sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})
    tickers = sorted(set(watch) | {"SPY"})  # SPY = RS benchmark, always refreshed
    spy_bars = fetch_daily_bars("SPY")
    ok = skipped_thin = failed = 0
    for t in tickers:
        try:
            bars = spy_bars if t == "SPY" else fetch_daily_bars(t)
            bench = spy_bars if t != "SPY" else None
            snap = build_technical_snapshot(bars, bench)
            if snap is None:
                skipped_thin += 1
                log.info("technical_daily_refresh: %s thin history (%d bars), skipped", t, len(bars))
                continue
            series = build_technical_series(bars, bench)
            trepo.upsert_series(t, series_records(series))
            detail = {
                k: snap[k]
                for k in (
                    "bars_n", "dist_pct", "composite", "kinematics", "sigmoid",
                    "distribution", "rsi", "macd", "rs",
                )
            }
            trepo.set_latest_detail(
                t, snap["as_of"], detail=detail, forward_returns=snap["forward_returns"]
            )
            ok += 1
        except Exception as exc:
            failed += 1
            log.warning("technical_daily_refresh failed for %s: %s", t, repr(exc))
    summary = {"ok": ok, "skipped_thin": skipped_thin, "failed": failed, "tickers": len(tickers)}
    log.info("technical_daily_refresh: %s", summary)
    return summary
```

- [ ] **Step 4: Config flag** (`src/uw_scan/config.py`)

Add the field on `Settings` near the other `*_enabled` flags:

```python
technicals_refresh_enabled: bool = True
```

In `from_env()`, add the mapping using the **exact bool-coercion idiom the file already uses for `data_gap_healer_enabled`** (copy it verbatim, changing only the env var name `UW_SCAN_TECHNICALS_REFRESH_ENABLED` and default to enabled) — do not invent a new truthiness parser.

- [ ] **Step 5: Scheduler registration** (`src/uw_scan/worker/scheduler.py`)

Three edits, copying the `vrp_markout_refresh` precedent exactly:

1. Import (top-of-file jobs import block): `from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh`
2. Closure (near `_vrp_markout_refresh`):

```python
def _technical_daily_refresh() -> None:
    with _repo(settings) as repo:
        technical_daily_refresh(repo=repo, settings=settings)
```

3. `add_job` inside the existing `if "massive" in groups:` → `if _is_primary_worker(settings):` block (same block as `vrp_markout_refresh` at 18:50 ET; slot ours at 18:40 ET, gated on the flag):

```python
if settings.technicals_refresh_enabled:
    sched.add_job(
        _technical_daily_refresh,
        CronTrigger.from_crontab("40 18 * * 0-4", timezone=settings.rth_tz),
        id="technical_daily_refresh",
        name="Technicals daily refresh (apex bars -> technical_daily)",
        max_instances=1,
        coalesce=True,
    )
```

(18:40 ET Mon–Fri: after apex's own EOD sync and before the 18:50 vrp_markout job; apex calls cost no UW budget, so massive-0 is the right single-flight home.)

- [ ] **Step 6: Manual runner** (the sanctioned non-/tmp path for backfill/smoke — modeled on `scripts/backfill/greek_exposure_daily_refresh_backfill.py`'s structure)

Create `scripts/backfill/technicals_refresh_backfill.py`:

```python
"""One-off/manual technical_daily refresh over the watchlist (or --tickers).

Reproduce: uv run python scripts/backfill/technicals_refresh_backfill.py [--tickers NVDA,SPY]
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default=None, help="comma-separated subset")
    args = parser.parse_args()
    settings = Settings.from_env()
    ticker_filter = args.tickers.split(",") if args.tickers else None
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        summary = technical_daily_refresh(
            repo=repo, settings=settings, ticker_filter=ticker_filter
        )
    print(summary)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/integration/worker/test_technicals_job.py -v   # PASS
uv run pytest tests/integration/ -n auto                            # full integration suite PASS
```

- [ ] **Step 8: End-to-end local smoke (real worker path, MacBook local DB)**

```bash
bash scripts/migrate.sh
uv run python scripts/backfill/technicals_refresh_backfill.py --tickers NVDA
# expected stdout: {'ok': 2, 'skipped_thin': 0, 'failed': 0, 'tickers': 2}
uv run uvicorn uw_scan.api.server:app --port 8400 &   # or use the running dev.sh stack
curl -s http://127.0.0.1:8400/api/stock/NVDA/technicals | uv run python -c "
import json,sys; b=json.load(sys.stdin)
assert b['backfill_status']=='ready', b['backfill_status']
assert b['header']['z_band'] is not None
assert b['forward_returns'], 'forward table empty'
print('technicals endpoint OK:', b['as_of'], b['header']['z_band'], len(b['series']), 'series rows')
"
```

Expected: `technicals endpoint OK: <recent date> <band> <n> series rows`. Sanity-check the numbers against reality: NVDA's z/band should be plausible vs its actual chart (eyeball; if z is ±10 something is wrong).

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/worker/jobs/technical_daily_refresh.py src/uw_scan/worker/scheduler.py src/uw_scan/config.py scripts/backfill/technicals_refresh_backfill.py tests/integration/worker/test_technicals_job.py
git commit -m "feat(technicals): nightly technical_daily_refresh job (massive-0 18:40 ET) + manual backfill runner"
```

---

### Task 8: PR 1 finalization — CHANGELOG, full CI repro, push, PR

**Files:**
- Modify: `CHANGELOG.md` (`[Unreleased]` → `### Added`)

- [ ] **Step 1: CHANGELOG entry** (match the file's existing entry style)

```markdown
- Technicals backend: `technical_daily` warm store (migration 101), pure derivers in `cards/technicals.py` (z-vs-200DMA + bands, MA kinematics, sigmoid trend-maturity with beats-linear guard, return distribution, RSI/MACD enhanced, SPY relative strength, forward-return-by-z-band table), `GET /api/stock/{ticker}/technicals`, nightly `technical_daily_refresh` (apex daily bars, massive-0 18:40 ET, `UW_SCAN_TECHNICALS_REFRESH_ENABLED`).
```

- [ ] **Step 2: Full CI repro** (the complete `lint + unit` job — every step, per Global Constraints)

Run the whole block from Global Constraints. Expected: every step clean, `tests/unit/` all PASS. Then `uv run pytest tests/integration/ -n auto` → PASS.

- [ ] **Step 3: Push + PR (wait for green before merging — no exceptions)**

```bash
git add CHANGELOG.md && git commit -m "docs: changelog for technicals backend"
git push -u origin feat/technicals-backend
gh pr create --title "feat: Technicals backend — technical_daily store, derivers, API, nightly refresh" --body "Implements PR 1 of docs/superpowers/specs/2026-07-06-quant-technicals-page-design.md (plan: docs/superpowers/plans/2026-07-08-technicals-tab.md).

- cards/technicals.py: z-vs-200DMA + bands, MA kinematics (ATR-normalized, t-stat), ATR-zigzag + sigmoid trend-maturity (beats-linear guard), return distribution, RSI/MACD enhanced, SPY RS, forward-return-by-z-band table (hand-verified unit test), composite
- migration 101 technical_daily + standalone TechnicalsRepository
- GET /api/stock/{ticker}/technicals (+ OpenAPI snapshot regen)
- nightly technical_daily_refresh on massive-0 @18:40 ET + scripts/backfill runner
- apex sources: fetch_daily_bars (never-raise)

Verification: full lint+unit repro locally, integration suite green, live smoke NVDA end-to-end (backfill script -> API -> asserted payload)."
gh pr checks --watch
```

Expected: all checks green. **Do not merge on UNSTABLE/red.** Merge per repo convention (squash), then `git checkout main && git pull`.

---

# PR 2 — web (`feat/technicals-web`)

Prereq: PR 1 merged to main. Branch: `git checkout -b feat/technicals-web` from updated main. Backend must be running locally for `gen:types` (`bash scripts/dev.sh` or `uv run uvicorn uw_scan.api.server:app --port 8400`).

### Task 9: Types, api client, tab wiring, island skeleton

**Files:**
- Modify: `web/lib/types.ts` (generated), `web/lib/api.ts`, `web/components/stock/TabBar.tsx`, `web/app/stock/[ticker]/[tab]/page.tsx`
- Create: `web/components/stock/tabs/TechnicalsTab.tsx`

**Interfaces:**
- Consumes: `GET /api/stock/{ticker}/technicals` (PR 1), `_fetch` in `lib/api.ts`
- Produces: `api.technicals(ticker): Promise<TechnicalsResponse>`; `TechnicalsTab({ ticker }: { ticker: string })` client island; exported type `TechnicalsResponse` from `lib/api.ts`

- [ ] **Step 1: Regenerate types** (API must be running on :8400 with the new route)

```bash
cd web && npm run gen:types
git diff --stat lib/types.ts   # expect one file; new technicals path + 4 schemas
npm run typecheck              # PASS before proceeding
```

- [ ] **Step 2: api client** (`web/lib/api.ts`)

Add near the other `Json<...>` aliases:

```ts
type TechnicalsResponse = Json<"/api/stock/{ticker}/technicals", "get">;
```

Add in the `api` object (next to `volatilitySeries`/`skewAnalysis`):

```ts
technicals: (ticker: string): Promise<TechnicalsResponse> =>
  _fetch<TechnicalsResponse>(`/api/stock/${ticker}/technicals`),
```

Add `TechnicalsResponse` to the `export type { ... }` block.

- [ ] **Step 3: Island skeleton** — create `web/components/stock/tabs/TechnicalsTab.tsx` (bare-`{ticker}` island like `FrameworkTab`; fetch-in-effect like `VolatilityTabClient`):

```tsx
"use client";

import { useEffect, useState } from "react";
import { api, type TechnicalsResponse } from "@/lib/api";
import { TechnicalsKpiStrip } from "../panels/TechnicalsKpiStrip";
import { TechnicalsAnchorChart } from "../panels/TechnicalsAnchorChart";
import { TechnicalsZChart } from "../panels/TechnicalsZChart";
import { ForwardReturnTable } from "../panels/ForwardReturnTable";
import { TechnicalsDetailPanels } from "../panels/TechnicalsDetailPanels";

export function TechnicalsTab({ ticker }: { ticker: string }) {
  const [data, setData] = useState<TechnicalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .technicals(ticker)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  if (error) {
    return <div style={{ color: "var(--negative)", padding: 16 }}>Technicals failed to load: {error}</div>;
  }
  if (!data) {
    return <div style={{ color: "var(--text-muted)", padding: 16 }}>Loading technicals…</div>;
  }
  if (data.backfill_status === "empty") {
    return (
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        No technicals history for {ticker} yet — populated by the nightly refresh
        (or run scripts/backfill/technicals_refresh_backfill.py).
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <TechnicalsKpiStrip data={data} />
      <TechnicalsAnchorChart data={data} />
      <TechnicalsZChart data={data} />
      <ForwardReturnTable data={data} />
      <TechnicalsDetailPanels data={data} />
    </div>
  );
}
```

(Compiles only after Task 10 creates the panels — Tasks 9+10 land as one commit; the intermediate state is fine because nothing else imports these files yet. If you want a compiling checkpoint, stub each panel as `export function X({ data }: { data: TechnicalsResponse }) { return null; }` in Task 9 and fill them in Task 10.)

- [ ] **Step 4: Wire the tab**

`web/components/stock/TabBar.tsx` — insert at **index 1**:

```tsx
const TABS = [
  ["market-structure", "Market Structure"],
  ["technicals", "Technicals"],
  ["volatility", "Volatility"],
  ["skew", "Skew"],
  ["flow", "Flow"],
  ["trade-insights", "Trade Insights"],
  ["trade-plan", "Trade Plan"],
] as const;
```

`web/app/stock/[ticker]/[tab]/page.tsx` — add the import and an early-return branch **before** the `REPORT_TABS` lookup (alongside `trade-insights`/`trade-plan`), so it never touches the `SingleStockReport` fetch:

```tsx
if (tab === "technicals") {
  return <TechnicalsTab ticker={ticker} />;
}
```

---

### Task 10: Panels — KPI strip, anchor chart, z chart, forward-return table, detail panels

**Files:**
- Create: `web/components/stock/panels/TechnicalsKpiStrip.tsx`
- Create: `web/components/stock/panels/TechnicalsAnchorChart.tsx`
- Create: `web/components/stock/panels/TechnicalsZChart.tsx`
- Create: `web/components/stock/panels/ForwardReturnTable.tsx`
- Create: `web/components/stock/panels/TechnicalsDetailPanels.tsx`

House rules for all five: hand-rolled SVG via `lib/svgChart.ts` (`linearScale`, `finiteDomain`, `pathFromPoints`, `pathFromNullablePoints`, `niceTicks`); `AnalyticalSeriesPanel` as the chart frame; inline `Tile` pattern copied from `VolMetricsCard.tsx` (label 10px/1.5 letter-spacing/uppercase/muted; value 22px bold mono); colors via `var(--positive|--negative|--warning|--accent-*)`; `role="img"` on SVGs; **always** `finiteDomain` before scaling (a single null poisons min/max → NaN labels); `fmtPct`/`fmtSigned`/`fmtDecimal` from `lib/formatters.ts`.

- [ ] **Step 1: `TechnicalsKpiStrip.tsx`** — 6-tile grid (`repeat(6, minmax(0,1fr))`, gap 12), copying the `Tile` component verbatim from `VolMetricsCard.tsx`:
  - PRICE — `fmtDecimal(header.price, 2)`, sub = `as_of`
  - 200 DMA / DIST — `fmtDecimal(header.sma200, 2)`, sub = `fmtPct(header.dist_pct)` distance
  - Z-SCORE — `fmtSigned(header.z, 2)`, valueColor by sign (`--positive` z<-1 mean-revert-cheap / `--negative` z>1, else default), sub = `header.z_band`
  - 200 DMA SLOPE (ANN.) — `fmtPct(header.slope_ann)`, sub = `header.slope_regime`
  - COMPOSITE — `fmtSigned(header.composite, 2)`, sub = `n=${data.bars_n} bars` (thin-sample visibility per spec)
  - MACD PCTILE — `fmtDecimal((data.macd_watchlist_pctile ?? 0) * 100, 0)` with null guard → "—"
- [ ] **Step 2: `TechnicalsAnchorChart.tsx`** — "PRICE, MOVING AVERAGES & ±1.5σ BAND" in an `AnalyticalSeriesPanel`. From `data.series`: close (primary line, `var(--text-primary)`), sma20/50/200 (`--accent-warm`/`--accent-vol`/`--accent-vivid`), plus the ±1.5σ envelope around sma200 as a filled polygon. Envelope math per point: `half = 1.5 * (close_t - sma200_t) / z_t` when `z_t` is finite and nonzero (recovers σ from the stored z — no extra API field), else null; upper = sma200 + half, lower = sma200 − half. Build the polygon `d` by walking `pathFromNullablePoints(upper)` forward then lower reversed, `fill="var(--accent-bg)" opacity={0.08}` (rect-band precedent: `CorrelationLineChart.tsx:89-101`; no existing polygon helper — hand-roll). W=760 H=280, y-domain from `finiteDomain` over close+smas+envelope.
- [ ] **Step 3: `TechnicalsZChart.tsx`** — "Z-SCORE VS 200 DMA" history: z line via `pathFromNullablePoints`, horizontal reference lines at 0/±1/±2 (`niceTicks` labels, "σ" suffix like `DivergenceOverlay.tsx`), band shading via two low-opacity rects (|z|>1.5 warning zones), current band label in the panel `headline`.
- [ ] **Step 4: `ForwardReturnTable.tsx`** ⭐ — Section B. Group `data.forward_returns` by band (rows) × horizon (default 40d headline; 20/60d columns behind a toggle button like `MaxPainTable`'s collapse). Columns: BAND · N · MEAN · MEDIAN · WIN%. Use the `DataTable.tsx` generic with `MaxPainTable`-style right-aligned numeric cells; mean/median via `fmtPct`, win_rate ×100. **Highlight the row where `band === data.header?.z_band`** (background `var(--accent-bg)` at low opacity + left border) — that's the "conditional bet" punchline. Footer note (11px muted): "N-day forward return conditioned on z-band, full available history (n=`bars_n` bars); bands assigned ex-ante."
- [ ] **Step 5: `TechnicalsDetailPanels.tsx`** — Sections A/C/D as a 2-col grid of `AnalyticalSeriesPanel`s reading `data.detail`:
  - MA KINEMATICS — tiles per SMA20/50/200: slope_atr (fmtSigned ×100 as "ATR%/d"), t-stat, curv; alignment score tile colored by sign.
  - SIGMOID TREND MATURITY — if `detail.sigmoid.valid`: phase (headline), k, s, R² sigmoid vs linear tiles; else the honest empty state: "No S-curve structure (R²sig `x` ≤ R²lin `y` + 0.05)".
  - RETURN DISTRIBUTION — tiles: rv20 (fmtPct), rv20_z, vol-of-vol, skew60, kurt60, jerk20.
  - RSI ENHANCED — rsi14 + rsi_z + slope tiles; divergence badge (BEARISH `--negative` / BULLISH `--positive`) when present; mini RSI history line from `series[].rsi14`.
  - MACD ENHANCED — hist_atr + slope tiles + `macd_watchlist_pctile`; mini history line from `series[].macd_hist_atr`.
  - RELATIVE STRENGTH VS SPY — ratio/ma60/ma200 tiles + trend label; ratio history line from `series[].rs_ratio` (null-safe via `pathFromNullablePoints`).
  All numeric renders null-guarded to "—" (never "NaN" — the e2e asserts this).
- [ ] **Step 6: Compile + lint checkpoint**

```bash
cd web && npm run typecheck && npm run lint
```
Expected: clean.

- [ ] **Step 7: Commit (Tasks 9+10 together — first compiling state)**

```bash
git add web/lib/types.ts web/lib/api.ts web/components/stock/TabBar.tsx "web/app/stock/[ticker]/[tab]/page.tsx" web/components/stock/tabs/TechnicalsTab.tsx web/components/stock/panels/Technicals*.tsx web/components/stock/panels/ForwardReturnTable.tsx
git commit -m "feat(web): Technicals tab — client island, KPI strip, anchor/z charts, forward-return table, detail panels"
```

---

### Task 11: Web tests + full verification + smoke + PR

**Files:**
- Create: `web/tests/unit/TechnicalsPanels.test.tsx`
- Create: `web/tests/e2e/technicals-tab.spec.ts`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Vitest unit tests** — create `web/tests/unit/TechnicalsPanels.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ForwardReturnTable } from "@/components/stock/panels/ForwardReturnTable";
import { TechnicalsKpiStrip } from "@/components/stock/panels/TechnicalsKpiStrip";

const base = {
  ticker: "NVDA",
  backfill_status: "ready",
  as_of: "2026-07-07",
  bars_n: 500,
  header: {
    price: 100.5, sma200: 95.0, dist_pct: 0.0579, z: 1.2, z_band: "STRETCHED HIGH",
    slope_ann: 0.12, slope_regime: "STRONG UPTREND", composite: 0.4,
  },
  series: [],
  detail: null,
  macd_watchlist_pctile: 0.8,
  forward_returns: [
    { band: "STRETCHED HIGH", horizon: 40, count: 33, mean: 0.015, median: 0.01, win_rate: 0.61 },
    { band: "NEUTRAL", horizon: 40, count: 120, mean: 0.008, median: 0.007, win_rate: 0.55 },
  ],
} as never;

describe("TechnicalsKpiStrip", () => {
  it("renders band + regime labels without NaN", () => {
    const { container } = render(<TechnicalsKpiStrip data={base} />);
    expect(screen.getByText("STRETCHED HIGH")).toBeDefined();
    expect(screen.getByText("STRONG UPTREND")).toBeDefined();
    expect(container.textContent).not.toContain("NaN");
  });

  it("null header fields render as dashes, not NaN", () => {
    const empty = { ...base, header: { ...base.header, z: null, composite: null } } as never;
    const { container } = render(<TechnicalsKpiStrip data={empty} />);
    expect(container.textContent).not.toContain("NaN");
  });
});

describe("ForwardReturnTable", () => {
  it("highlights the current band row", () => {
    render(<ForwardReturnTable data={base} />);
    const current = screen.getByText("STRETCHED HIGH", { selector: "td, th, div, span" });
    expect(current).toBeDefined();
    // count column rendered
    expect(screen.getByText("33")).toBeDefined();
  });
});
```

(Adjust selectors to the actual markup you wrote in Task 10 — the assertions that matter: labels visible, current-band row present, zero "NaN" anywhere.)

Run: `cd web && npm run test` → PASS.

- [ ] **Step 2: e2e spec** (not in CI; for local runs) — create `web/tests/e2e/technicals-tab.spec.ts` modeled verbatim on `tests/e2e/volatility-tab.spec.ts` (same DRYRUN-seeded-ticker approach, console-error collection):

```ts
import { expect, test } from "@playwright/test";

const TICKER = "DRYRUN";

test("technicals tab renders with no NaN / no console errors", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  await page.goto(`/stock/${TICKER}/technicals`);
  // either real panels or the honest empty state — both are valid renders
  await expect(
    page.getByText(/Z-SCORE|No technicals history/i).first()
  ).toBeVisible();
  const body = (await page.textContent("body")) ?? "";
  expect(body).not.toMatch(/NaN/);
  expect(consoleErrors).toHaveLength(0);
});
```

- [ ] **Step 3: Full web verification (the complete CI web job)**

```bash
cd web && npm run typecheck && npm run test && npm run lint && npm run build
```
Expected: all clean. `next build` must succeed (it catches RSC/island boundary mistakes typecheck misses).

- [ ] **Step 4: Real-worker-path smoke (the standing rule — API → DB → worker → DB → UI)**

```bash
# from repo root, local stack:
bash scripts/migrate.sh
bash scripts/dev.sh   # web :3001 + api :8400 + workers (or confirm already running)
uv run python scripts/backfill/technicals_refresh_backfill.py --tickers NVDA,AAPL,QQQ
```

Then browse `http://localhost:3001/stock/NVDA/technicals` and verify: (1) Technicals tab appears at position 2 (right of Market Structure); (2) KPI strip shows price/z/band/slope-regime; (3) anchor chart draws close + 3 SMAs + shaded envelope; (4) forward-return table renders with the current-band row highlighted; (5) no "NaN" text anywhere; (6) sanity-check NVDA's z-band against its real chart. Screenshot to `output/playwright/technicals-tab-nvda.png` (Playwright MCP or `npx playwright screenshot`). Check an unseeded ticker shows the honest empty state, not an error.

- [ ] **Step 5: CHANGELOG + commit + PR**

`CHANGELOG.md` `[Unreleased]` → `### Added`:

```markdown
- Technicals tab on `/stock/[ticker]` (index 1, after Market Structure): KPI stat-strip, price/MA/±1.5σ anchor chart, z-vs-200DMA history, forward-return-by-z-band table with current-band highlight, MA-kinematics / sigmoid / distribution / RSI / MACD / SPY-RS panels. Client island off the SingleStockReport hot path.
```

```bash
git add web/tests CHANGELOG.md
git commit -m "test(web): technicals panels unit tests + e2e spec; changelog"
git push -u origin feat/technicals-web
gh pr create --title "feat: Technicals tab (web) — client island + panels" --body "PR 2 of docs/superpowers/specs/2026-07-06-quant-technicals-page-design.md (plan: docs/superpowers/plans/2026-07-08-technicals-tab.md). Requires the technicals backend (PR 1, merged).

- TechnicalsTab client island (bare ticker prop, fetches /api/stock/{ticker}/technicals; never touches the SingleStockReport hot path)
- KPI strip, anchor chart (+±1.5σ envelope), z history, ⭐ forward-return-by-z-band table (current band highlighted), detail panels (kinematics/sigmoid/distribution/RSI/MACD/RS)
- TabBar index 1 (Market Structure · Technicals · Volatility · …)

Verification: typecheck+vitest+lint+build clean; live smoke NVDA/AAPL/QQQ via backfill runner -> :3001 render (screenshot in output/playwright/); empty-state verified on unseeded ticker."
gh pr checks --watch
```

Expected: green. Merge only on green.

---

## Post-merge deploy notes (informational, not plan tasks)

- The mini picks up both PRs at the next release tag (`cut.sh prepare` → merge → `cut.sh tag`; Watchtower auto-deploys `:latest`).
- Until apex's 2000-bar default lands, the table holds ~500 sessions (~2 years) — the forward-return table's counts read accordingly (visible via `bars_n`). No argon change needed when apex raises the cap; the next nightly refresh widens history automatically.
- First data on the mini: either wait for the 18:40 ET job or run the backfill runner once inside the app container.

## Self-Review (done at authoring)

- **Spec coverage:** header KPI strip (T10.1), anchor chart (T10.2), z+band panel (T1/T10.3), MA kinematics (T1/T10.5), sigmoid (T2/T10.5), forward-return table (T3/T10.4), distribution (T3/T10.5), RSI (T3/T10.5), MACD + watchlist pctile (T3/T6/T10.5), RS-vs-SPY (T3/T10.5), composite (T3/T10.1), persist-everything (T5/T7), own endpoint off the hot path (T6), client island at TabBar index 1 (T9), nightly refresh + on-demand path (T7 — on-demand realized as the committed backfill runner rather than API-side compute, keeping the API read-only per house rule; deviation noted), thin-history visibility via `bars_n` (T3/T10.1). ✔
- **Placeholders:** none — every code step carries the code; the two "copy the existing idiom verbatim" pointers (config bool coercion, backfill script structure) name exact source files. ✔
- **Type consistency:** `fetch_daily_bars`/`build_technical_series`/`build_technical_snapshot`/`series_records`/`TechnicalsRepository` names match across Tasks 3–7; `TechnicalsResponse` fields match assembler (T6) and web consumption (T9–T11); `z_vs_200dma` column name consistent between series builder, migration, repo SQL, and assembler mapping. ✔
