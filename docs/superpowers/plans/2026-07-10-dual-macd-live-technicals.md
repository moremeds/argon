# Dual MACD + Live Technicals Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single MACD on the Quant Technicals tab with a dual (long/short-period) MACD, add live intraday coverage of all daily technicals off argon's WS spot feed, and extend every technicals series to 5 years of history.

**Architecture:** Port apex's dual-MACD math/state into argon's pure `cards/technicals.py` derivers (ATR-normalized). Dual-MACD histograms ride the existing `metrics` JSONB and its state rides the `detail` JSONB — no schema migration for Part 1. Live coverage reuses the `regime_live` splice pattern: a massive-0-pinned scheduler job splices the latest `intraday_quote` as today's provisional daily close, recomputes the fast-moving subset via a shared `live_technical_snapshot` helper, and upserts a latest-only `technical_live` cache table the page polls.

**Tech Stack:** Python 3.13 (`uv`), FastAPI + Pydantic v2, psycopg 3, APScheduler 3, pandas/numpy; Next.js 16 + React 19 + hand-rolled SVG; Vitest + pytest/pytest-postgresql.

**Spec:** `docs/superpowers/specs/2026-07-09-dual-macd-live-technicals-design.md`

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`.
- **Decimal-vs-float exception:** `cards/technicals.py` is float end-to-end by design (chart-grade z-scores/ratios, not money math) — follow that file's existing convention; do NOT introduce `Decimal` here.
- **Logging:** `log = logging.getLogger(__name__)`; every `except` calls `.exception(...)` / logs `repr(exc)` / re-raises (CI Guardrail 2).
- **Migrations are idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`). No tracking table.
- **API contract stability:** new Pydantic fields go in **alphabetical** slot; preserve `__module__` via `_preserve_public_module`; run `cd web && npm run gen:types` and commit `web/lib/types.ts` + the OpenAPI snapshot in the same PR. Add fields surgically (types.ts is alphabetically frozen — write via the gen script, not hand-editing).
- **No new external calls in the live path** — the WS consumer already writes `intraday_quote`; daily history is already in `technical_daily`.
- **CHANGELOG rides this PR** — `[Unreleased]` entry on this branch before merge.
- **Never commit without explicit user request is waived for this plan's own commit steps** (each task ends by committing its own work); do NOT open a PR or merge without an explicit request.
- **apex stays the nightly daily-bar source only** — do NOT wire apex into the live path (livewire intraday bronze is refreshed nightly at ~00:00 ET, not live).

---

## File Structure

**Part 1 — Daily dual MACD (no migration)**
- Modify `src/uw_scan/cards/technicals.py` — add `dual_macd_series`, `dual_macd_state`, `_rolling_pctile_rank`, `_num`; wire dual cols into `build_technical_series`, dual state into `build_technical_snapshot`; extend `SERIES_METRIC_COLS`.
- Modify `src/uw_scan/storage/technicals_repository.py` — extend `_METRIC_COLS`.
- Modify `src/uw_scan/worker/jobs/technical_daily_refresh.py` — add `"dual_macd"` to the detail keys.
- Modify `src/uw_scan/models/technicals.py` — add `fast_macd_hist_atr` / `slow_macd_hist_atr` to `TechnicalsSeriesRow`.
- Modify `src/uw_scan/reports/technicals.py` — add the two keys to `_METRIC_FIELDS`.
- Modify `web/components/stock/panels/TechnicalsOscillators.tsx` + `OscillatorChart.tsx` — dual histogram + state badge.

**Part 2 — Live coverage**
- Modify `src/uw_scan/cards/technicals.py` — add `live_technical_snapshot`.
- Create `src/uw_scan/storage/migrations/103_technical_live.sql`.
- Create `src/uw_scan/storage/technical_live_repository.py` — `TechnicalLiveRepository`.
- Create `src/uw_scan/worker/jobs/technical_live.py` — `technical_live_scan`.
- Modify `src/uw_scan/config.py` — 3 settings + `from_env`.
- Modify `src/uw_scan/worker/scheduler.py` — register the job.
- Modify `src/uw_scan/models/technicals.py` — `TechnicalsLiveResponse`.
- Modify `src/uw_scan/api/routers/stock.py` — `/stock/{ticker}/technicals/live`.
- Modify the Technicals tab client component — live polling + overlay/badge.

**Part 3 — 5-year history**
- Modify `src/uw_scan/storage/technicals_repository.py` — `fetch_series` default limit 504 → 1300.
- Modify `src/uw_scan/sources/apex.py` — pass `limit` to apex `/bars`.

**Cross-cutting**
- Modify `CHANGELOG.md`, `CLAUDE.md` ("Where to look first" row).

---

## Task 1: Dual MACD pure derivers (`dual_macd_series`, `dual_macd_state`)

**Files:**
- Modify: `src/uw_scan/cards/technicals.py` (add after `macd_hist`, ~line 153)
- Test: `tests/unit/cards/test_dual_macd.py` (create)

**Interfaces:**
- Produces:
  - `dual_macd_series(df: pd.DataFrame, *, slope_lookback: int = 3) -> pd.DataFrame` with columns `fast_macd_hist_atr, slow_macd_hist_atr, fast_macd_delta, slow_macd_delta, fast_macd_delta2, fast_macd_norm, slow_macd_norm` (index = `df.index`).
  - `dual_macd_state(row: Mapping[str, Any], *, eps: float = 1e-3) -> dict` returning `{fast_hist, slow_hist, fast_delta, slow_delta, trend_state, tactical_signal, momentum_balance, confidence}`.
- Consumes: existing `macd_hist(close, fast, slow, signal)`, `atr14(df)`, `z_band_label`, `_lastf` from the same module.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/cards/test_dual_macd.py
"""Dual MACD deriver + state machine (ports apex momentum/dual_macd.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from uw_scan.cards.technicals import dual_macd_series, dual_macd_state


def _ramp_df(n: int = 400, slope: float = 0.5, start: float = 100.0) -> pd.DataFrame:
    close = start + slope * np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "as_of": pd.date_range("2023-01-02", periods=n, freq="B").date,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000.0),
        }
    )


def test_series_has_all_columns_and_is_finite_at_tail():
    out = dual_macd_series(_ramp_df())
    assert list(out.columns) == [
        "fast_macd_hist_atr",
        "slow_macd_hist_atr",
        "fast_macd_delta",
        "slow_macd_delta",
        "fast_macd_delta2",
        "fast_macd_norm",
        "slow_macd_norm",
    ]
    assert np.isfinite(out["fast_macd_hist_atr"].iloc[-1])
    assert np.isfinite(out["slow_macd_hist_atr"].iloc[-1])
    # norms are 0..1 percentile ranks
    assert 0.0 <= out["fast_macd_norm"].iloc[-1] <= 1.0


def test_state_steady_uptrend_is_bullish_no_tactical():
    out = dual_macd_series(_ramp_df())
    st = dual_macd_state(out.iloc[-1])
    assert st["trend_state"] == "BULLISH"
    assert st["tactical_signal"] == "NONE"
    assert st["confidence"] == 0.0
    assert st["momentum_balance"] in {"FAST_DOMINANT", "SLOW_DOMINANT", "BALANCED"}


def test_state_dip_buy_branch():
    # Directly exercise the state truth table: bullish structure (slow>0),
    # fast dipped negative but decelerating (dh_fast>=0, |dh_fast|>|dh_slow|).
    row = {
        "slow_macd_hist_atr": 0.8,
        "fast_macd_hist_atr": -0.4,
        "slow_macd_delta": 0.01,
        "fast_macd_delta": 0.20,
        "fast_macd_delta2": 0.10,
        "slow_macd_norm": 0.6,
        "fast_macd_norm": 0.5,
    }
    st = dual_macd_state(row)
    assert st["tactical_signal"] == "DIP_BUY"
    assert 0.0 < st["confidence"] <= 1.0


def test_state_rally_sell_branch():
    row = {
        "slow_macd_hist_atr": -0.8,
        "fast_macd_hist_atr": 0.4,
        "slow_macd_delta": -0.01,
        "fast_macd_delta": -0.20,
        "fast_macd_delta2": -0.10,
        "slow_macd_norm": 0.6,
        "fast_macd_norm": 0.5,
    }
    st = dual_macd_state(row)
    assert st["tactical_signal"] == "RALLY_SELL"
    assert 0.0 < st["confidence"] <= 1.0


def test_state_freeze_zone_is_balanced():
    row = {
        "slow_macd_hist_atr": 0.05,
        "fast_macd_hist_atr": 0.02,
        "slow_macd_delta": 0.0,
        "fast_macd_delta": 0.0,
        "fast_macd_delta2": 0.0,
        "slow_macd_norm": 0.10,
        "fast_macd_norm": 0.10,
    }
    assert dual_macd_state(row)["momentum_balance"] == "BALANCED"


def test_state_handles_nan_row_without_raising():
    row = {k: float("nan") for k in (
        "slow_macd_hist_atr", "fast_macd_hist_atr", "slow_macd_delta",
        "fast_macd_delta", "fast_macd_delta2", "slow_macd_norm", "fast_macd_norm")}
    st = dual_macd_state(row)
    assert st["trend_state"] == "BEARISH"  # all-zero fallthrough
    assert st["tactical_signal"] == "NONE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/cards/test_dual_macd.py -q`
Expected: FAIL — `ImportError: cannot import name 'dual_macd_series'`.

- [ ] **Step 3: Implement the derivers**

Add to `src/uw_scan/cards/technicals.py` (after `macd_hist`, and add `from collections.abc import Mapping` + `from typing import Any` to imports if absent):

```python
def _num(v: Any) -> float:
    """Coerce to a finite float, else 0.0 (matches apex _safe_float)."""
    if v is None:
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        log.debug("dual_macd coercion skipped: %s", repr(exc))
        return 0.0
    return f if math.isfinite(f) else 0.0


def _rolling_pctile_rank(s: pd.Series, window: int = 252) -> pd.Series:
    """Causal rolling percentile rank (0-1) of each value within its trailing
    `window` (ports apex _rolling_pctile_rank; needs >=2 valid points)."""
    return s.rolling(window, min_periods=2).apply(
        lambda w: float(np.mean(w <= w[-1])), raw=True
    )


def dual_macd_series(df: pd.DataFrame, *, slope_lookback: int = 3) -> pd.DataFrame:
    """Fast (13/21/9) + slow (55/89/34) MACD histograms, each ATR(14)-normalized,
    with slopes, fast curvature, and 252d percentile-rank magnitudes. Ports
    apex momentum/dual_macd.py with argon's ATR normalization in place of the
    raw x2 multiplier."""
    close = df["close"]
    atr = atr14(df).replace(0.0, np.nan)
    fast = macd_hist(close, fast=13, slow=21, signal=9) / atr
    slow = macd_hist(close, fast=55, slow=89, signal=34) / atr
    fast_delta = fast.diff(slope_lookback)
    slow_delta = slow.diff(slope_lookback)
    return pd.DataFrame(
        {
            "fast_macd_hist_atr": fast,
            "slow_macd_hist_atr": slow,
            "fast_macd_delta": fast_delta,
            "slow_macd_delta": slow_delta,
            "fast_macd_delta2": fast_delta.diff(1),
            "fast_macd_norm": _rolling_pctile_rank(fast.abs()),
            "slow_macd_norm": _rolling_pctile_rank(slow.abs()),
        },
        index=df.index,
    )


def dual_macd_state(row: Mapping[str, Any], *, eps: float = 1e-3) -> dict:
    """Trend / tactical / balance / confidence from a dual_macd_series row.
    Direct port of apex DualMACDIndicator._get_state (override-first trend,
    countertrend-decelerating tactical, freeze-zone balance, curvature conf)."""
    h_slow = _num(row.get("slow_macd_hist_atr"))
    h_fast = _num(row.get("fast_macd_hist_atr"))
    dh_slow = _num(row.get("slow_macd_delta"))
    dh_fast = _num(row.get("fast_macd_delta"))
    ddh_fast = _num(row.get("fast_macd_delta2"))
    slow_norm = _num(row.get("slow_macd_norm"))
    fast_norm = _num(row.get("fast_macd_norm"))

    if h_slow > 0 and dh_slow < 0:
        trend = "DETERIORATING"
    elif h_slow < 0 and dh_slow > 0:
        trend = "IMPROVING"
    elif h_slow > 0:
        trend = "BULLISH"
    else:
        trend = "BEARISH"

    tactical = "NONE"
    if h_slow > 0 and h_fast < 0 and abs(dh_fast) > abs(dh_slow) and dh_fast >= 0:
        tactical = "DIP_BUY"
    elif h_slow < 0 and h_fast > 0 and abs(dh_fast) > abs(dh_slow) and dh_fast <= 0:
        tactical = "RALLY_SELL"

    if slow_norm < 0.15 and fast_norm < 0.15:
        balance = "BALANCED"
    elif fast_norm > slow_norm * 1.5:
        balance = "FAST_DOMINANT"
    elif slow_norm > fast_norm * 1.5:
        balance = "SLOW_DOMINANT"
    else:
        balance = "BALANCED"

    confidence = 0.0
    if tactical == "DIP_BUY":
        confidence = float(np.clip(ddh_fast / max(abs(h_fast), eps), 0.0, 1.0))
    elif tactical == "RALLY_SELL":
        confidence = float(np.clip(-ddh_fast / max(abs(h_fast), eps), 0.0, 1.0))

    return {
        "fast_hist": h_fast,
        "slow_hist": h_slow,
        "fast_delta": dh_fast,
        "slow_delta": dh_slow,
        "trend_state": trend,
        "tactical_signal": tactical,
        "momentum_balance": balance,
        "confidence": confidence,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/cards/test_dual_macd.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/technicals.py tests/unit/cards/test_dual_macd.py
git commit -m "feat(technicals): dual MACD derivers + state machine (ATR-normalized port of apex)"
```

---

## Task 2: Wire dual MACD into the daily series + snapshot + storage

**Files:**
- Modify: `src/uw_scan/cards/technicals.py` — `SERIES_METRIC_COLS`, `build_technical_series`, `build_technical_snapshot`
- Modify: `src/uw_scan/storage/technicals_repository.py` — `_METRIC_COLS`
- Modify: `src/uw_scan/worker/jobs/technical_daily_refresh.py` — detail keys
- Test: `tests/unit/cards/test_technicals_dual_wiring.py` (create)

**Interfaces:**
- Consumes: `dual_macd_series`, `dual_macd_state` (Task 1).
- Produces: `build_technical_series(...)` now emits the 7 dual columns; `build_technical_snapshot(...)["dual_macd"]` = the state dict; stored `metrics` JSONB carries the 7 columns.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cards/test_technicals_dual_wiring.py
from __future__ import annotations

import numpy as np
import pandas as pd

from uw_scan.cards.technicals import build_technical_series, build_technical_snapshot


def _bars(n: int = 320) -> list[dict]:
    close = 100.0 + np.cumsum(np.random.default_rng(7).normal(0.05, 1.0, n))
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    return [
        {
            "time": t.isoformat(),
            "open": float(c),
            "high": float(c) + 1.0,
            "low": float(c) - 1.0,
            "close": float(c),
            "volume": 1_000.0,
        }
        for t, c in zip(idx, close)
    ]


def test_series_carries_dual_macd_columns():
    out = build_technical_series(_bars())
    for col in ("fast_macd_hist_atr", "slow_macd_hist_atr",
                "fast_macd_delta", "slow_macd_delta", "fast_macd_delta2",
                "fast_macd_norm", "slow_macd_norm"):
        assert col in out.columns


def test_snapshot_exposes_dual_macd_state():
    snap = build_technical_snapshot(_bars())
    assert snap is not None
    dm = snap["dual_macd"]
    assert set(dm) >= {"trend_state", "tactical_signal", "momentum_balance", "confidence"}
    assert dm["tactical_signal"] in {"DIP_BUY", "RALLY_SELL", "NONE"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cards/test_technicals_dual_wiring.py -q`
Expected: FAIL — `KeyError: 'fast_macd_hist_atr'` / `KeyError: 'dual_macd'`.

- [ ] **Step 3: Implement the wiring**

In `src/uw_scan/cards/technicals.py`:

1. Extend `SERIES_METRIC_COLS` (add the 7 keys before the closing paren):

```python
SERIES_METRIC_COLS: tuple[str, ...] = (
    "rv20", "rv20_z", "vol_of_vol", "skew60", "kurt60", "jerk20",
    "rsi_z", "rsi_slope5", "macd_slope3",
    "kin_slope20", "kin_slope50", "kin_slope200", "alignment",
    "fast_macd_hist_atr", "slow_macd_hist_atr",
    "fast_macd_delta", "slow_macd_delta", "fast_macd_delta2",
    "fast_macd_norm", "slow_macd_norm",
)
```

2. In `build_technical_series`, after the `out["macd_slope3"] = ...` line, add:

```python
    _dm = dual_macd_series(df)
    for col in _dm.columns:
        out[col] = _dm[col]
```

Also add the 7 columns to the empty-frame `columns=[...]` list in `build_technical_series` (append after `"macd_hist_atr"`).

3. In `build_technical_snapshot`, after `macd_d = macd_enhanced(df)` add:

```python
    dual = dual_macd_state(dual_macd_series(df).iloc[-1])
```

and add `"dual_macd": dual,` to the returned dict (place it right after the `"macd": macd_d,` entry).

In `src/uw_scan/storage/technicals_repository.py`, extend `_METRIC_COLS` with the same 7 keys (mirror the `SERIES_METRIC_COLS` addition exactly).

In `src/uw_scan/worker/jobs/technical_daily_refresh.py`, add `"dual_macd"` to the tuple of detail keys copied into `detail` (the `for k in (...)` block):

```python
            detail = {
                k: snap[k]
                for k in (
                    "bars_n", "dist_pct", "composite", "kinematics",
                    "sigmoid", "distribution", "rsi", "macd", "dual_macd", "rs",
                )
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/cards/test_technicals_dual_wiring.py -q`
Expected: PASS.

- [ ] **Step 5: Run the broader technicals unit suite (no regressions)**

Run: `uv run pytest tests/unit/cards/ -q -k technical`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/technicals.py src/uw_scan/storage/technicals_repository.py src/uw_scan/worker/jobs/technical_daily_refresh.py tests/unit/cards/test_technicals_dual_wiring.py
git commit -m "feat(technicals): store dual MACD series in metrics JSONB + state in detail"
```

---

## Task 3: Surface dual MACD on the API contract

**Files:**
- Modify: `src/uw_scan/models/technicals.py` — `TechnicalsSeriesRow`
- Modify: `src/uw_scan/reports/technicals.py` — `_METRIC_FIELDS`
- Test: `tests/unit/test_models_exports.py` (existing — just re-run), `tests/integration/test_technicals_api.py` (extend or create)
- Regenerate: `web/lib/types.ts`, OpenAPI snapshot

**Interfaces:**
- Consumes: stored `metrics` keys (Task 2).
- Produces: `TechnicalsSeriesRow.fast_macd_hist_atr`, `.slow_macd_hist_atr`; `detail.dual_macd` already flows via the free-form `detail: dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cards/test_series_row_fields.py
from uw_scan.models import TechnicalsSeriesRow


def test_series_row_accepts_dual_macd_fields():
    row = TechnicalsSeriesRow(
        as_of="2026-07-09", close=100.0,
        fast_macd_hist_atr=-0.4, slow_macd_hist_atr=0.8,
    )
    assert row.fast_macd_hist_atr == -0.4
    assert row.slow_macd_hist_atr == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cards/test_series_row_fields.py -q`
Expected: FAIL — Pydantic ignores/rejects unknown field (assert error on attribute).

- [ ] **Step 3: Add the model fields (alphabetical) + assembler passthrough**

In `src/uw_scan/models/technicals.py`, add to `TechnicalsSeriesRow` in alphabetical position among the metric block (after `alignment`, before/around `jerk20` — keep the block's existing ordering, insert `fast_macd_*` and `slow_macd_*` in their alphabetical slots):

```python
    fast_macd_hist_atr: float | None = None
    slow_macd_hist_atr: float | None = None
```

(Only these two are charted; deltas/norms stay in the JSONB, not the typed row.)

In `src/uw_scan/reports/technicals.py`, add both keys to `_METRIC_FIELDS`:

```python
        "fast_macd_hist_atr",
        "slow_macd_hist_atr",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/cards/test_series_row_fields.py tests/unit/test_models_exports.py -q`
Expected: PASS.

- [ ] **Step 5: Regenerate types + OpenAPI snapshot**

Run:
```bash
cd web && npm run gen:types && cd ..
uv run pytest tests/unit -q -k openapi_snapshot
```
If the snapshot test fails on drift, regenerate the snapshot per its docstring (the test prints the update command), then re-run. Expected: PASS; `web/lib/types.ts` shows `fast_macd_hist_atr` / `slow_macd_hist_atr` added.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/models/technicals.py src/uw_scan/reports/technicals.py web/lib/types.ts tests/unit/cards/test_series_row_fields.py
git add -A  # OpenAPI snapshot if present
git commit -m "feat(technicals): expose dual MACD histograms on the API contract"
```

---

## Task 4: Dual MACD chart + state badge (frontend)

**Files:**
- Modify: `web/components/stock/panels/TechnicalsOscillators.tsx` — `TechnicalsMacdChart`
- Modify: `web/components/stock/panels/OscillatorChart.tsx` — add a second histogram overlay
- Test: `web/tests/unit/technicals-macd.test.tsx` (create; follow the nearest existing panel test)

**Interfaces:**
- Consumes: `data.series[].fast_macd_hist_atr`, `.slow_macd_hist_atr`; `data.detail.dual_macd.{trend_state,tactical_signal,momentum_balance,confidence}`.

- [ ] **Step 1: Read `OscillatorChart.tsx`** to learn the existing `histogram` prop shape (values array + color). The overlay mirrors it.

- [ ] **Step 2: Write the failing test**

```tsx
// web/tests/unit/technicals-macd.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TechnicalsMacdChart } from "@/components/stock/panels/TechnicalsOscillators";

const data = {
  series: [
    { as_of: "2026-07-08", fast_macd_hist_atr: -0.4, slow_macd_hist_atr: 0.8 },
    { as_of: "2026-07-09", fast_macd_hist_atr: -0.2, slow_macd_hist_atr: 0.9 },
  ],
  detail: {
    dual_macd: { trend_state: "BULLISH", tactical_signal: "DIP_BUY",
                 momentum_balance: "FAST_DOMINANT", confidence: 0.72 },
  },
} as any;

describe("TechnicalsMacdChart", () => {
  it("renders the dual-MACD title and tactical badge", () => {
    const { getByText } = render(<TechnicalsMacdChart data={data} />);
    expect(getByText(/Dual MACD/i)).toBeTruthy();
    expect(getByText(/DIP_BUY/)).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/technicals-macd.test.tsx`
Expected: FAIL — old title "MACD Histogram (8/17/9)", no DIP_BUY badge.

- [ ] **Step 4: Add the histogram overlay prop to `OscillatorChart.tsx`**

Add an optional `histogramOverlay?: { values: Array<number | null>; color: string }` prop that renders a second set of bars behind the primary `histogram` (draw the overlay first so the primary sits on top; use a lower opacity fill). Mirror the existing `histogram` rendering block exactly, swapping the values/color and adding `opacity: 0.45`.

- [ ] **Step 5: Rewrite `TechnicalsMacdChart`**

```tsx
export function TechnicalsMacdChart({ data }: { data: TechnicalsResponse }) {
  const s = data.series ?? [];
  const dm = data.detail?.dual_macd as
    | { trend_state?: string; tactical_signal?: string;
        momentum_balance?: string; confidence?: number | null }
    | undefined;
  const sig = dm?.tactical_signal && dm.tactical_signal !== "NONE"
    ? `${dm.tactical_signal} · conf ${fmtDecimal(dm.confidence ?? 0, 2)}`
    : dm?.trend_state ?? undefined;
  return (
    <OscillatorChart
      title="Dual MACD — 13/21/9 vs 55/89/34"
      subtitle="ATR-normalized · fast vs slow"
      headline={sig}
      dates={datesOf(s)}
      histogram={{ values: col(s, "fast_macd_hist_atr") }}
      histogramOverlay={{ values: col(s, "slow_macd_hist_atr"), color: "var(--accent-vol)" }}
      refLines={[{ y: 0, solid: true }]}
      explanation="Two MACD histograms on one ATR-normalized scale: the wide muted bars are the slow 55/89/34 (structural trend); the sharp bars are the fast 13/21/9 (tactical timing). When the slow trend is up but the fast bars dip below zero and start curling back up, that's a DIP_BUY (mirror = RALLY_SELL). The badge shows the current tactical signal, its confidence, and the trend/momentum-balance state."
    />
  );
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd web && npx vitest run tests/unit/technicals-macd.test.tsx && npm run typecheck`
Expected: PASS + typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add web/components/stock/panels/TechnicalsOscillators.tsx web/components/stock/panels/OscillatorChart.tsx web/tests/unit/technicals-macd.test.tsx
git commit -m "feat(web): dual MACD contrast histogram + tactical badge on Technicals tab"
```

---

## Task 5: `live_technical_snapshot` shared deriver

**Files:**
- Modify: `src/uw_scan/cards/technicals.py`
- Test: `tests/unit/cards/test_live_technical_snapshot.py` (create)

**Interfaces:**
- Consumes: `dual_macd_series`, `dual_macd_state`, `rsi_enhanced`, `ma_kinematics`, `return_distribution`, `z_vs_200dma`, `z_band_label`, `macd_hist`, `atr14`, `composite_score`, `_lastf`.
- Produces: `live_technical_snapshot(df: pd.DataFrame, spot: float, *, as_of: date | None = None) -> dict` with keys `{z, z_band, rsi14, rsi_z, dual_macd, rv20, kinematics, composite}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cards/test_live_technical_snapshot.py
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from uw_scan.cards.technicals import bars_frame, live_technical_snapshot


def _df(n: int = 320) -> pd.DataFrame:
    close = 100.0 + np.cumsum(np.random.default_rng(3).normal(0.05, 1.0, n))
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    bars = [
        {"time": t.isoformat(), "open": float(c), "high": float(c) + 1,
         "low": float(c) - 1, "close": float(c), "volume": 1_000.0}
        for t, c in zip(idx, close)
    ]
    return bars_frame(bars)


def test_live_snapshot_keys_and_splice():
    df = _df()
    prev_close = float(df["close"].iloc[-1])
    snap = live_technical_snapshot(df, prev_close + 5.0, as_of=dt.date(2026, 7, 9))
    assert set(snap) == {"z", "z_band", "rsi14", "rsi_z",
                         "dual_macd", "rv20", "kinematics", "composite"}
    assert snap["dual_macd"]["tactical_signal"] in {"DIP_BUY", "RALLY_SELL", "NONE"}
    # sigmoid / forward_returns are intentionally NOT recomputed live
    assert "sigmoid" not in snap and "forward_returns" not in snap


def test_live_snapshot_moves_with_spot():
    df = _df()
    base = float(df["close"].iloc[-1])
    up = live_technical_snapshot(df, base + 20.0, as_of=dt.date(2026, 7, 9))["z"]
    dn = live_technical_snapshot(df, base - 20.0, as_of=dt.date(2026, 7, 9))["z"]
    assert up > dn  # higher provisional close => higher z vs 200DMA
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cards/test_live_technical_snapshot.py -q`
Expected: FAIL — `ImportError: cannot import name 'live_technical_snapshot'`.

- [ ] **Step 3: Implement `live_technical_snapshot`**

Add to `src/uw_scan/cards/technicals.py` (import `date` from datetime if needed):

```python
def live_technical_snapshot(
    df: pd.DataFrame, spot: float, *, as_of: date | None = None
) -> dict:
    """Splice `spot` as today's provisional daily close onto `df` (an OHLCV
    frame from bars_frame) and recompute only the fast-moving technicals.
    Sigmoid + forward-returns are deliberately excluded (static intraday);
    callers carry them from the nightly detail. Pure — no I/O."""
    prov = pd.DataFrame(
        [{"as_of": as_of, "open": spot, "high": spot,
          "low": spot, "close": spot, "volume": 0.0}]
    )
    d = pd.concat([df, prov], ignore_index=True)
    close = d["close"]
    z = _lastf(z_vs_200dma(close))
    rsi_d = rsi_enhanced(d)
    kin = ma_kinematics(d)
    dist = return_distribution(close)
    dual = dual_macd_state(dual_macd_series(d).iloc[-1])
    macd_atr = _lastf(macd_hist(close) / atr14(d).replace(0.0, np.nan))
    return {
        "z": z,
        "z_band": z_band_label(z),
        "rsi14": rsi_d.get("rsi14"),
        "rsi_z": rsi_d.get("rsi_z"),
        "dual_macd": dual,
        "rv20": dist.get("rv20"),
        "kinematics": kin,
        "composite": composite_score(
            alignment=kin.get("alignment"),
            slope_tstat_200=(kin.get("sma200") or {}).get("tstat"),
            macd_hist_atr=macd_atr,
            rsi_z=rsi_d.get("rsi_z"),
        ),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/cards/test_live_technical_snapshot.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/technicals.py tests/unit/cards/test_live_technical_snapshot.py
git commit -m "feat(technicals): live_technical_snapshot shared splice-recompute helper"
```

---

## Task 6: `technical_live` cache table + repository

**Files:**
- Create: `src/uw_scan/storage/migrations/103_technical_live.sql`
- Create: `src/uw_scan/storage/technical_live_repository.py`
- Test: `tests/integration/storage/test_technical_live_repository.py` (create)

**Interfaces:**
- Produces: `TechnicalLiveRepository(conn, schema="uw_scan")` with `upsert(ticker, captured_at, spot, spot_source, payload: dict) -> None` and `fetch(ticker) -> dict | None` (returns `{ticker, captured_at, spot, spot_source, payload}` or None).

- [ ] **Step 1: Write the migration**

```sql
-- src/uw_scan/storage/migrations/103_technical_live.sql
-- Latest-only live-technicals cache (one row per ticker, upsert). Not a
-- (ticker, as_of) temporal table -> no data-gap registry entry needed.
CREATE TABLE IF NOT EXISTS technical_live (
    ticker       text PRIMARY KEY,
    captured_at  timestamptz NOT NULL,
    spot         double precision,
    spot_source  text,
    payload      jsonb NOT NULL,
    inserted_at  timestamptz NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/storage/test_technical_live_repository.py
from __future__ import annotations

import datetime as dt

from uw_scan.storage.technical_live_repository import TechnicalLiveRepository


def test_upsert_and_fetch(db_conn):  # db_conn = project pytest-postgresql fixture
    repo = TechnicalLiveRepository(db_conn, schema="uw_scan")
    ts = dt.datetime(2026, 7, 9, 15, 30, tzinfo=dt.timezone.utc)
    repo.upsert("NVDA", ts, 123.45, "xenon_ws", {"z": 1.2, "dual_macd": {"trend_state": "BULLISH"}})
    got = repo.fetch("NVDA")
    assert got["spot"] == 123.45
    assert got["spot_source"] == "xenon_ws"
    assert got["payload"]["dual_macd"]["trend_state"] == "BULLISH"


def test_upsert_replaces(db_conn):
    repo = TechnicalLiveRepository(db_conn, schema="uw_scan")
    t1 = dt.datetime(2026, 7, 9, 15, 0, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2026, 7, 9, 15, 5, tzinfo=dt.timezone.utc)
    repo.upsert("AAPL", t1, 100.0, "xenon_ws", {"z": 0.1})
    repo.upsert("AAPL", t2, 101.0, "massive.com_ws", {"z": 0.2})
    got = repo.fetch("AAPL")
    assert got["spot"] == 101.0 and got["captured_at"] == t2
```

(Use the repo's existing integration DB fixture name — check `tests/integration/conftest.py` for the actual fixture; replace `db_conn` accordingly.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_technical_live_repository.py -q`
Expected: FAIL — `ModuleNotFoundError: ...technical_live_repository`.

- [ ] **Step 4: Implement the repository**

```python
# src/uw_scan/storage/technical_live_repository.py
"""Standalone repository for the technical_live latest-only cache."""

from __future__ import annotations

from datetime import datetime

from psycopg import Connection
from psycopg.types.json import Jsonb


class TechnicalLiveRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert(
        self,
        ticker: str,
        captured_at: datetime,
        spot: float | None,
        spot_source: str | None,
        payload: dict,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO technical_live
                    (ticker, captured_at, spot, spot_source, payload)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    captured_at = EXCLUDED.captured_at,
                    spot        = EXCLUDED.spot,
                    spot_source = EXCLUDED.spot_source,
                    payload     = EXCLUDED.payload,
                    inserted_at = now()
                """,
                (ticker.upper(), captured_at, spot, spot_source, Jsonb(payload)),
            )
        self._conn.commit()

    def fetch(self, ticker: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticker, captured_at, spot, spot_source, payload
                FROM technical_live WHERE ticker = %s
                """,
                (ticker.upper(),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "ticker": row[0],
            "captured_at": row[1],
            "spot": row[2],
            "spot_source": row[3],
            "payload": row[4],
        }
```

- [ ] **Step 5: Apply the migration + run tests**

Run:
```bash
bash scripts/migrate.sh
uv run pytest tests/integration/storage/test_technical_live_repository.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/103_technical_live.sql src/uw_scan/storage/technical_live_repository.py tests/integration/storage/test_technical_live_repository.py
git commit -m "feat(technicals): technical_live cache table + repository"
```

---

## Task 7: `technical_live_scan` job

**Files:**
- Create: `src/uw_scan/worker/jobs/technical_live.py`
- Test: `tests/integration/worker/test_technical_live_scan.py` (create)

**Interfaces:**
- Consumes: `live_technical_snapshot` (Task 5), `TechnicalLiveRepository` (Task 6), `TechnicalsRepository.fetch_series`, `repo.get_intraday_quotes` (returns `IntradayQuoteRow(ticker, price, quoted_at, fetched_at, source)`), `repo.list_watchlist_cards()`.
- Produces: `technical_live_scan(repo, settings, *, ticker_filter=None, now=None) -> dict` summary `{ok, skipped_stale, skipped_thin, failed, tickers}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/worker/test_technical_live_scan.py
from __future__ import annotations

import datetime as dt

from uw_scan.worker.jobs.technical_live import technical_live_scan
# Use the project's real Settings + repo integration fixtures.


def test_scan_writes_cache_row(live_repo, live_settings, seed_technical_daily, seed_intraday_quote):
    # seed_technical_daily: >=210 daily rows for "NVDA"; seed_intraday_quote:
    # a fresh NVDA quote 30s old.
    now = dt.datetime(2026, 7, 9, 19, 0, tzinfo=dt.timezone.utc)
    summary = technical_live_scan(
        live_repo, live_settings, ticker_filter=["NVDA"], now=now
    )
    assert summary["ok"] == 1
    from uw_scan.storage.technical_live_repository import TechnicalLiveRepository
    got = TechnicalLiveRepository(live_repo.conn).fetch("NVDA")
    assert got is not None and "dual_macd" in got["payload"]


def test_stale_quote_skipped(live_repo, live_settings, seed_technical_daily, seed_stale_quote):
    now = dt.datetime(2026, 7, 9, 19, 0, tzinfo=dt.timezone.utc)
    summary = technical_live_scan(live_repo, live_settings, ticker_filter=["NVDA"], now=now)
    assert summary["skipped_stale"] == 1 and summary["ok"] == 0
```

(Model the fixtures on `tests/integration/worker/` neighbors that already seed `technical_daily` + `intraday_quote`; if none exist, seed inline via `TechnicalsRepository.upsert_series` + `repo.upsert_intraday_quote`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_technical_live_scan.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the job**

```python
# src/uw_scan/worker/jobs/technical_live.py
"""Live technicals coverage: splice the latest WS intraday_quote as today's
provisional daily close, recompute the fast-moving technicals, cache per
ticker. Mirrors regime_live — DB-read only, zero provider spend."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from uw_scan.cards.technicals import live_technical_snapshot
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.storage.technical_live_repository import TechnicalLiveRepository
from uw_scan.storage.technicals_repository import TechnicalsRepository

log = logging.getLogger(__name__)

_MIN_BARS = 210  # same floor as build_technical_snapshot


def technical_live_scan(
    repo: Repository,
    settings: Settings,
    *,
    ticker_filter: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    max_age = settings.technical_live_quote_max_age_seconds
    trepo = TechnicalsRepository(repo.conn, schema=settings.db_schema)
    live = TechnicalLiveRepository(repo.conn, schema=settings.db_schema)

    if ticker_filter is not None:
        tickers = [t.upper() for t in ticker_filter]
    else:
        tickers = sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})

    quotes = {q.ticker: q for q in repo.get_intraday_quotes(tickers)}
    ok = skipped_stale = skipped_thin = failed = 0
    for t in tickers:
        try:
            q = quotes.get(t)
            if q is None or (now - q.quoted_at).total_seconds() > max_age:
                skipped_stale += 1
                continue
            rows = trepo.fetch_series(t)
            if len(rows) < _MIN_BARS:
                skipped_thin += 1
                continue
            df = pd.DataFrame(
                [
                    {"as_of": r["as_of"], "open": r["close"], "high": r["close"],
                     "low": r["close"], "close": r["close"], "volume": 0.0}
                    for r in rows
                ]
            )
            # fetch_series returns newest-first; live splice needs ascending.
            df = df.sort_values("as_of").reset_index(drop=True)
            payload = live_technical_snapshot(df, float(q.price))
            live.upsert(t, q.quoted_at, float(q.price), q.source, payload)
            ok += 1
        except Exception as exc:
            failed += 1
            repo.conn.rollback()
            log.warning("technical_live_scan failed for %s: %s", t, repr(exc))
    summary = {"ok": ok, "skipped_stale": skipped_stale,
               "skipped_thin": skipped_thin, "failed": failed,
               "tickers": len(tickers)}
    log.info("technical_live_scan: %s", summary)
    return summary
```

> NOTE: `fetch_series` returns only `close` (not OHLC), so the splice frame uses `close` for O/H/L too — matching the provisional-bar convention in `live_technical_snapshot`. ATR over a close-only history slightly understates true range, acceptable for the live head (documented tradeoff).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_technical_live_scan.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/technical_live.py tests/integration/worker/test_technical_live_scan.py
git commit -m "feat(technicals): technical_live_scan job (WS-spot splice, fast-subset recompute)"
```

---

## Task 8: Config settings + scheduler registration

**Files:**
- Modify: `src/uw_scan/config.py` — 3 fields + `from_env`
- Modify: `src/uw_scan/worker/scheduler.py` — job fn + `add_job`
- Test: `tests/unit/test_config_from_env.py` (extend or create)

**Interfaces:**
- Consumes: `technical_live_scan` (Task 7), `_should_schedule_regime_live` (existing guard, reused), `IntervalTrigger`, `settings.rth_tz`.
- Produces settings: `technical_live_enabled: bool = False`, `technical_live_scan_interval_minutes: int = 5`, `technical_live_quote_max_age_seconds: int = 900`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_technical_live_config.py
import os
from uw_scan.config import Settings


def test_defaults(monkeypatch):
    for k in ("UW_SCAN_TECHNICAL_LIVE_ENABLED",
              "TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES",
              "TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env()
    assert s.technical_live_enabled is False
    assert s.technical_live_scan_interval_minutes == 5
    assert s.technical_live_quote_max_age_seconds == 900


def test_env_override(monkeypatch):
    monkeypatch.setenv("UW_SCAN_TECHNICAL_LIVE_ENABLED", "true")
    monkeypatch.setenv("TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES", "3")
    s = Settings.from_env()
    assert s.technical_live_enabled is True
    assert s.technical_live_scan_interval_minutes == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_technical_live_config.py -q`
Expected: FAIL — attribute/field missing.

- [ ] **Step 3: Add the settings**

In `src/uw_scan/config.py`, add fields near `technicals_refresh_enabled` (line ~375):

```python
    technical_live_enabled: bool = False
    technical_live_scan_interval_minutes: int = 5
    technical_live_quote_max_age_seconds: int = 900
```

In `from_env` (near the `technicals_refresh_enabled=` block, line ~847):

```python
            technical_live_enabled=_env_bool("UW_SCAN_TECHNICAL_LIVE_ENABLED", False),
            technical_live_scan_interval_minutes=int(
                os.environ.get("TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES", "5")
            ),
            technical_live_quote_max_age_seconds=int(
                os.environ.get("TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS", "900")
            ),
```

- [ ] **Step 4: Register the job in `scheduler.py`**

Add a job fn near `_regime_live_scan` (line ~997):

```python
    def _technical_live_scan() -> None:
        if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
            return
        from uw_scan.worker.jobs.technical_live import technical_live_scan

        with _repo(settings) as repo:
            summary = technical_live_scan(repo, settings)
        logger.info("technical_live_scan_tick %s", summary)
```

Add the `add_job` inside a new guard block near the `regime_live_scan` registration (line ~1619), reusing the massive-0 pin:

```python
    if settings.technical_live_enabled and _should_schedule_regime_live(settings):
        # Live technicals coverage — upsert-per-ticker cache off intraday_quote.
        sched.add_job(
            _technical_live_scan,
            IntervalTrigger(minutes=settings.technical_live_scan_interval_minutes),
            id="technical_live_scan",
            name="Live technicals coverage",
            max_instances=1,
            coalesce=True,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_technical_live_config.py -q && uv run python -c "import uw_scan.worker.scheduler"`
Expected: PASS + scheduler imports clean.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/worker/scheduler.py tests/unit/test_technical_live_config.py
git commit -m "feat(technicals): register technical_live_scan (massive-0, gated, default off)"
```

---

## Task 9: Live technicals API endpoint

**Files:**
- Modify: `src/uw_scan/models/technicals.py` — `TechnicalsLiveResponse`
- Modify: `src/uw_scan/models/__init__.py` — export it
- Modify: `src/uw_scan/api/routers/stock.py` — new route
- Regenerate: `web/lib/types.ts`, OpenAPI snapshot
- Test: `tests/integration/api/test_technicals_live_endpoint.py` (create)

**Interfaces:**
- Consumes: `TechnicalLiveRepository.fetch` (Task 6).
- Produces: `GET /stock/{ticker}/technicals/live` → `TechnicalsLiveResponse` (`available: bool`, `captured_at`, `spot`, `spot_source`, `z`, `z_band`, `rsi14`, `rsi_z`, `dual_macd`, `rv20`, `kinematics`, `composite`).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/api/test_technicals_live_endpoint.py
def test_live_endpoint_returns_cached(api_client, seed_technical_live):
    # seed_technical_live upserts a NVDA technical_live row.
    resp = api_client.get("/stock/NVDA/technicals/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["spot_source"] == "xenon_ws"
    assert body["dual_macd"]["trend_state"] in {"BULLISH", "BEARISH", "IMPROVING", "DETERIORATING"}


def test_live_endpoint_absent_is_unavailable(api_client):
    resp = api_client.get("/stock/ZZZZ/technicals/live")
    assert resp.status_code == 200
    assert resp.json()["available"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/api/test_technicals_live_endpoint.py -q`
Expected: FAIL — 404 (route missing).

- [ ] **Step 3: Add the model**

In `src/uw_scan/models/technicals.py`:

```python
class TechnicalsLiveResponse(_UwBase):
    ticker: str
    available: bool
    captured_at: datetime | None = None
    spot: float | None = None
    spot_source: str | None = None
    z: float | None = None
    z_band: str | None = None
    rsi14: float | None = None
    rsi_z: float | None = None
    dual_macd: dict[str, Any] | None = None
    rv20: float | None = None
    kinematics: dict[str, Any] | None = None
    composite: float | None = None
```

Add `from datetime import datetime` to the imports, add `TechnicalsLiveResponse` to the `_preserve_public_module(...)` call, and export it from `src/uw_scan/models/__init__.py` (`__all__` + import line, alphabetical slot).

- [ ] **Step 4: Add the route**

In `src/uw_scan/api/routers/stock.py` (after the existing `/stock/{ticker}/technicals` route, ~line 209), import `TechnicalsLiveResponse` and `TechnicalLiveRepository`, then:

```python
@router.get("/stock/{ticker}/technicals/live", response_model=TechnicalsLiveResponse)
def get_stock_technicals_live(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsLiveResponse:
    from uw_scan.storage.technical_live_repository import TechnicalLiveRepository

    t = ticker.upper()
    row = TechnicalLiveRepository(repo.conn, schema=settings.db_schema).fetch(t)
    if row is None:
        return TechnicalsLiveResponse(ticker=t, available=False)
    p = row["payload"]
    return TechnicalsLiveResponse(
        ticker=t, available=True,
        captured_at=row["captured_at"], spot=row["spot"], spot_source=row["spot_source"],
        z=p.get("z"), z_band=p.get("z_band"),
        rsi14=p.get("rsi14"), rsi_z=p.get("rsi_z"),
        dual_macd=p.get("dual_macd"), rv20=p.get("rv20"),
        kinematics=p.get("kinematics"), composite=p.get("composite"),
    )
```

(Match the existing `Depends(...)` names used by `get_stock_technicals` in this file.)

- [ ] **Step 5: Regenerate types + run tests**

Run:
```bash
cd web && npm run gen:types && cd ..
uv run pytest tests/integration/api/test_technicals_live_endpoint.py tests/unit/test_models_exports.py -q
uv run pytest tests/unit -q -k openapi_snapshot
```
Expected: PASS; `TechnicalsLiveResponse` in `web/lib/types.ts`.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/models/technicals.py src/uw_scan/models/__init__.py src/uw_scan/api/routers/stock.py web/lib/types.ts tests/integration/api/test_technicals_live_endpoint.py
git add -A  # OpenAPI snapshot
git commit -m "feat(technicals): GET /stock/{ticker}/technicals/live endpoint"
```

---

## Task 10: Live overlay + badge on the Technicals tab (frontend)

**Files:**
- Modify: the Technicals tab client component (`web/components/stock/tabs/` — find the one that renders `TechnicalsOscillators`; likely `TechnicalsTab.tsx` or similar) and `web/lib/api.ts` (add the `/technicals/live` fetch)
- Test: `web/tests/unit/technicals-live-badge.test.tsx` (create)

**Interfaces:**
- Consumes: `GET /stock/{ticker}/technicals/live` → `TechnicalsLiveResponse` (typed in `lib/types.ts` after Task 9).

- [ ] **Step 1: Read the Technicals tab component** to find where it fetches/holds data and renders the panels. Confirm it is (or can become) a client component (`"use client"`).

- [ ] **Step 2: Write the failing test** for a `LiveBadge` presentational component

```tsx
// web/tests/unit/technicals-live-badge.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveBadge } from "@/components/stock/panels/LiveBadge";

describe("LiveBadge", () => {
  it("shows LIVE + source when fresh", () => {
    const { getByText } = render(
      <LiveBadge captured_at={new Date().toISOString()} source="xenon_ws" maxAgeSec={900} />
    );
    expect(getByText(/LIVE/)).toBeTruthy();
    expect(getByText(/xenon_ws/)).toBeTruthy();
  });
  it("shows EOD when stale/absent", () => {
    const { getByText } = render(<LiveBadge captured_at={null} source={null} maxAgeSec={900} />);
    expect(getByText(/EOD/)).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/technicals-live-badge.test.tsx`
Expected: FAIL — `LiveBadge` missing.

- [ ] **Step 4: Implement `LiveBadge`** (`web/components/stock/panels/LiveBadge.tsx`)

Small presentational component: green `LIVE · HH:MM:SS · <source>` when `captured_at` is within `maxAgeSec`, grey `EOD` otherwise. Follow the mono-label style from `web/CLAUDE.md`.

- [ ] **Step 5: Wire polling into the tab**

In the tab component: add an `api.getTechnicalsLive(ticker)` call to `lib/api.ts`, poll every 25s via `useEffect` + `setInterval` (client component), store the latest `TechnicalsLiveResponse`, and:
- Render `<LiveBadge .../>` in the tab header.
- When a fresh live row exists, override the header readouts (z, composite, dual-MACD tactical badge) and append the live dual-MACD point to the chart series before passing to `TechnicalsMacdChart` (or pass a `liveHead` prop). Keep the server-rendered daily payload as the baseline when live is unavailable.

- [ ] **Step 6: Run tests + typecheck**

Run: `cd web && npx vitest run tests/unit/technicals-live-badge.test.tsx && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/components/stock/panels/LiveBadge.tsx web/components/stock/tabs/ web/lib/api.ts web/tests/unit/technicals-live-badge.test.tsx
git commit -m "feat(web): live technicals overlay + LIVE/EOD badge on the Technicals tab"
```

---

## Task 11: Extend history to 5 years

**Files:**
- Modify: `src/uw_scan/storage/technicals_repository.py` — `fetch_series` default limit
- Modify: `src/uw_scan/sources/apex.py` — pass `limit` to apex `/bars`
- Test: `tests/unit/sources/test_apex_bars_limit.py` (create) + reuse existing repo test

**Interfaces:**
- Produces: `fetch_series(ticker, *, limit=1300)`; `fetch_daily_bars` requests `limit` bars from apex.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/sources/test_apex_bars_limit.py
import httpx
from uw_scan.sources import apex


def test_fetch_daily_bars_requests_deep_history(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["params"] = params
        req = httpx.Request("GET", url)
        return httpx.Response(200, json={"bars": []}, request=req)

    monkeypatch.setattr(apex.httpx, "get", fake_get)
    apex.fetch_daily_bars("NVDA")
    assert int(seen["params"]["limit"]) >= 1300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/sources/test_apex_bars_limit.py -q`
Expected: FAIL — no `limit` param sent.

- [ ] **Step 3: Implement**

In `src/uw_scan/sources/apex.py` `fetch_daily_bars`, change the params to request deep history:

```python
        resp = httpx.get(
            url, params={"timeframe": "1d", "limit": 1300}, timeout=timeout
        )
```

In `src/uw_scan/storage/technicals_repository.py`, change `fetch_series` signature default `limit: int = 504` → `limit: int = 1300`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/sources/test_apex_bars_limit.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/apex.py src/uw_scan/storage/technicals_repository.py tests/unit/sources/test_apex_bars_limit.py
git commit -m "feat(technicals): extend history to ~5y (deep apex bar fetch + fetch_series limit)"
```

---

## Task 12: CHANGELOG + docs + full-suite gate

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `CLAUDE.md` — "Where to look first" table row

- [ ] **Step 1: Add the CHANGELOG entry** under `## [Unreleased]`:

```markdown
### Added
- **Dual MACD on the Technicals tab** — replaces the single MACD histogram with a contrasting long-period (55/89/34) + short-period (13/21/9) ATR-normalized dual MACD and apex's tactical state machine (DIP_BUY/RALLY_SELL, trend/momentum-balance, confidence).
- **Live technicals coverage** — a massive-0 scheduler job (`technical_live_scan`, gated by `TECHNICAL_LIVE_ENABLED`, default off) splices the live WS spot as today's provisional daily close and recomputes the fast-moving technicals into a `technical_live` cache; the Technicals tab polls `GET /stock/{ticker}/technicals/live` and overlays a LIVE/EOD head. Migration 103.
- **5-year technicals history** — every technicals series now retains ~1300 sessions.
```

- [ ] **Step 2: Add a CLAUDE.md "Where to look first" row**

```markdown
| Dual MACD + live technicals coverage | `cards/technicals.py` (`dual_macd_series`/`dual_macd_state`/`live_technical_snapshot`) + `worker/jobs/technical_live.py` + `storage/technical_live_repository.py` + migration `103` + `api/routers/stock.py` (`/technicals/live`, gated `TECHNICAL_LIVE_ENABLED`, massive-0) + `web/components/stock/panels/{TechnicalsOscillators,LiveBadge}.tsx`; spec `docs/superpowers/specs/2026-07-09-dual-macd-live-technicals-design.md` |
```

- [ ] **Step 3: Run the full gate**

Run:
```bash
uv run pytest -q
cd web && npm run test && npm run typecheck && npm run lint && cd ..
uv run python scripts/release/version_sync_check.py || true
```
Expected: all green. Fix any failures before committing.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md CLAUDE.md
git commit -m "docs(technicals): changelog + where-to-look row for dual MACD + live coverage"
```

---

## Manual smoke test (real worker path — before opening a PR)

1. Restart the local stack (`bash scripts/dev.sh`) so the worker loads the new job (APScheduler does not hot-reload).
2. Set `UW_SCAN_TECHNICAL_LIVE_ENABLED=true` and `XENON_WS_ENABLED=true` in the local env; confirm `intraday_quote` is being written.
3. Wait one interval (≤5 min) → verify a `technical_live` row: `SELECT ticker, captured_at, spot_source FROM uw_scan.technical_live LIMIT 5;`.
4. Open `/stock/NVDA` → Technicals tab: dual MACD contrast histogram renders, tactical badge shows, and the `LIVE · … · xenon_ws` badge is green and updates.
5. Disable the flag / stop the WS feed → badge falls back to `EOD`, chart stays on the daily baseline.

---

## Self-Review

**Spec coverage:**
- Part 1 (dual MACD replace) → Tasks 1–4. ✓
- Part 2 (live coverage, all technicals, argon WS, scheduler-cached) → Tasks 5–10. ✓
- Part 3 (5-year history) → Task 11. ✓
- `macd_hist_atr`/composite/forward-returns untouched → no task modifies them (verified: Task 2 adds alongside, does not replace). ✓
- Live `rs` carried from nightly → `live_technical_snapshot` omits `rs` (Task 5). ✓
- No migration for Part 1 → Task 2 uses JSONB only. ✓
- Migration 103 latest-only, no data-gap registry → Task 6. ✓

**Placeholder scan:** every code step shows complete code; frontend Tasks 4/10 include one explicit "read the existing file first" step because the exact SVG/tab prop shapes must follow existing patterns — the data wiring and component contracts are fully specified. No TBD/TODO.

**Type consistency:** `dual_macd_series` columns (`fast_macd_hist_atr`, …) are identical across Tasks 1, 2, 3, 5. `dual_macd_state` keys (`trend_state`/`tactical_signal`/`momentum_balance`/`confidence`) consistent across Tasks 1, 4, 9, 10. `technical_live_scan(repo, settings, *, ticker_filter, now)` matches its caller in Task 8. `TechnicalLiveRepository.upsert/fetch` signatures match across Tasks 6, 7, 9. Settings names (`technical_live_enabled`, `technical_live_scan_interval_minutes`, `technical_live_quote_max_age_seconds`) consistent across Tasks 7, 8.
