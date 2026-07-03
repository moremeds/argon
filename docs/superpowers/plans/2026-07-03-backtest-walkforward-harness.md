# Backtest Walk-Forward Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One unified backtest harness (`src/uw_scan/backtest/`) — replay engine, splitters, OOS gates, metrics, sweep runner, Postgres persistence — that current strategies migrate onto and future strategies plug into for parameter search.

**Architecture:** Radon's `scripts/backtest/engine.py` is the reference shape (signal replay where the entry rule sees only history ≤ origin and P&L is the forward return keyed at the origin — that keying is the no-lookahead guarantee), extended with argon's proven pieces: the holdout+quarter OOS gates currently duplicated in `skew_markout.py`/`vrp_markout_core.py`, the monthly-ROR Sharpe conventions from `scripts/_vrp_macro_param_sweep.py`, and persist-every-trace sweep storage. The engine stays scalar return-space; multi-leg options structures are priced by strategy code into forward returns.

**Tech Stack:** Python 3.13, stdlib `statistics`/`math` only (no numpy/pandas in the harness), psycopg 3, pytest + pytest-postgresql.

## Global Constraints

- **uv only**: `uv run pytest`, `uv run ruff check`, never bare `python`/`pip`.
- **No new dependencies.** The harness is stdlib + psycopg (already present).
- **Migration number is `095`** (`095_backtest_harness.sql`) — 093/094 are taken. Idempotent (`IF NOT EXISTS`), header `SET search_path TO uw_scan, public;`.
- **Population std (`statistics.pstdev`, ddof=0) everywhere** — matches both radon's convention and `_sharpe_maxdd` in `scripts/_vrp_macro_param_sweep.py`, whose saved trace (`docs/research/vrp/`) is the reproduction target.
- **Float math** in the harness (research layer; matches `vrp_markout_core.py`). No `Decimal` here.
- **`storage/repository.py` untouched.** New persistence is a standalone class in `storage/backtest_repository.py` (pattern: `storage/data_freshness_repository.py`).
- **Exception logging uses `repr(exc)`** (CI Guardrail 2, enforced by `scripts/_lint_except.py`).
- **No fake cursors/connections in `tests/integration/`** (Guardrail 5). Unit tests may stub freely.
- **Module size**: every new file well under 500 lines.
- **Behavior-preserving migration**: `reports/skew_markout.py` and `reports/vrp_markout_core.py` call sites must produce byte-identical outputs; their existing tests pass unchanged.
- **CHANGELOG `[Unreleased]` entry in this same PR** (standing memory: changelog belongs in the feature PR).
- **No `Co-Authored-By` trailers** on commits.
- **Branch/worktree**: already created — `feat/backtest-walkforward-harness` at `.worktrees/backtest-walkforward-harness/`. All work happens there.

## File Structure

```
Create: src/uw_scan/backtest/__init__.py          # public exports, grows per task
Create: src/uw_scan/backtest/metrics.py           # Task 1
Create: src/uw_scan/backtest/splitters.py         # Task 2
Create: src/uw_scan/backtest/gates.py             # Task 3
Create: src/uw_scan/backtest/engine.py            # Task 4
Create: src/uw_scan/storage/migrations/095_backtest_harness.sql   # Task 5
Create: src/uw_scan/storage/backtest_repository.py                # Task 5
Create: src/uw_scan/backtest/sweep.py             # Task 6
Modify: src/uw_scan/reports/skew_markout.py       # Task 7 (lines 52-108)
Modify: src/uw_scan/reports/vrp_markout_core.py   # Task 8 (lines 109-185)
Modify: scripts/_vrp_macro_param_sweep.py         # Task 9
Modify: CHANGELOG.md, CLAUDE.md                   # Task 10
Create: tests/unit/backtest/{__init__,test_metrics,test_splitters,test_gates,test_engine,test_sweep}.py
Create: tests/integration/storage/test_backtest_repository.py
Create: tests/integration/storage/test_backtest_sweep.py
```

Out of scope (later PRs): migrating `scripts/backtest_canary.py` (needs a `fixed_windows` splitter) and `scripts/backtest_cri.py` (needs `rolling`). The splitter interface leaves room; do NOT build those splitters now (YAGNI).

---

### Task 1: metrics.py — performance primitives

**Files:**
- Create: `src/uw_scan/backtest/__init__.py`
- Create: `src/uw_scan/backtest/metrics.py`
- Test: `tests/unit/backtest/__init__.py` (empty), `tests/unit/backtest/test_metrics.py`

**Interfaces:**
- Produces: `annualized_sharpe(returns: Sequence[float], *, periods_per_year: int) -> float`, `additive_max_drawdown(returns) -> float`, `hit_rate(returns) -> float`, `zero_filled_monthly(monthly: Mapping[tuple[int, int], float]) -> list[float]`, `monthly_summary(monthly) -> dict` (keys `sharpe`, `maxdd`, `annror`). Tasks 4 and 9 consume these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/backtest/test_metrics.py
from __future__ import annotations

import math

from uw_scan.backtest.metrics import (
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
    monthly_summary,
    zero_filled_monthly,
)


def test_sharpe_hand_derived():
    # mean 0.02, pstdev 0.01 -> 2 * sqrt(12)
    assert abs(annualized_sharpe([0.03, 0.01], periods_per_year=12) - 2 * math.sqrt(12)) < 1e-12


def test_sharpe_zero_mean_is_zero():
    assert annualized_sharpe([0.01, -0.01], periods_per_year=12) == 0.0


def test_sharpe_degenerate_inputs_are_nan():
    assert math.isnan(annualized_sharpe([], periods_per_year=12))
    assert math.isnan(annualized_sharpe([0.02, 0.02], periods_per_year=12))  # zero dispersion


def test_additive_max_drawdown():
    # cum: .05, .03, .00, .04 ; peak .05 -> worst -.05
    assert additive_max_drawdown([0.05, -0.02, -0.03, 0.04]) == -0.05
    assert additive_max_drawdown([]) == 0.0
    assert additive_max_drawdown([0.01, 0.02]) == 0.0  # monotone up


def test_hit_rate():
    assert hit_rate([0.01, -0.02, 0.03]) == 2 / 3
    assert math.isnan(hit_rate([]))


def test_zero_filled_monthly_spans_year_boundary():
    monthly = {(2025, 11): 0.01, (2026, 2): 0.04}
    assert zero_filled_monthly(monthly) == [0.01, 0.0, 0.0, 0.04]
    assert zero_filled_monthly({}) == []


def test_monthly_summary_matches_legacy_sharpe_maxdd_semantics():
    # exact port of scripts/_vrp_macro_param_sweep.py::_sharpe_maxdd
    monthly = {(2026, 1): 0.03, (2026, 3): 0.01}  # gap month zero-filled
    s = monthly_summary(monthly)
    series = [0.03, 0.0, 0.01]
    mean = sum(series) / 3
    var = sum((x - mean) ** 2 for x in series) / 3  # population
    assert abs(s["sharpe"] - mean / math.sqrt(var) * math.sqrt(12)) < 1e-12
    assert s["maxdd"] == 0.0  # cum .03,.03,.04 is monotone non-decreasing — no drawdown
    assert abs(s["annror"] - mean * 12) < 1e-12


def test_monthly_summary_empty():
    s = monthly_summary({})
    assert math.isnan(s["sharpe"]) and s["maxdd"] == 0.0 and s["annror"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .worktrees/backtest-walkforward-harness && uv run pytest tests/unit/backtest/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.backtest'`

- [ ] **Step 3: Implement**

```python
# src/uw_scan/backtest/metrics.py
"""Performance-metric primitives for the backtest harness.

Pure functions over per-period SIMPLE returns (0.01 == +1%). Population std
(ddof=0) everywhere — matches scripts/_vrp_macro_param_sweep.py::_sharpe_maxdd,
whose saved trace (docs/research/vrp/) is the reproduction target. Degenerate
inputs return nan/0.0 rather than raising so sweep summaries stay serializable.
Drawdown is on the ADDITIVE cumulative curve (ROR units), not compounded —
same convention as the legacy sweep.
"""

from __future__ import annotations

from math import sqrt
from statistics import fmean, pstdev
from typing import Mapping, Sequence


def annualized_sharpe(returns: Sequence[float], *, periods_per_year: int) -> float:
    """mean/pstdev * sqrt(periods_per_year). nan for empty or zero-dispersion."""
    if not returns:
        return float("nan")
    sd = pstdev(returns)
    if sd == 0:
        return float("nan")
    return fmean(returns) / sd * sqrt(periods_per_year)


def additive_max_drawdown(returns: Sequence[float]) -> float:
    """Worst peak-to-trough of the additive cumulative curve. <= 0."""
    cum = peak = mdd = 0.0
    for x in returns:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def hit_rate(returns: Sequence[float]) -> float:
    if not returns:
        return float("nan")
    return sum(1 for r in returns if r > 0) / len(returns)


def zero_filled_monthly(monthly: Mapping[tuple[int, int], float]) -> list[float]:
    """Contiguous (year, month)-keyed span, missing months as 0.0 — exact port
    of the span logic in _sharpe_maxdd (a month with no exits is a flat month,
    not a skipped one; skipping would overstate Sharpe)."""
    if not monthly:
        return []
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    series: list[float] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        series.append(monthly.get((y, m), 0.0))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return series


def monthly_summary(monthly: Mapping[tuple[int, int], float]) -> dict:
    """Drop-in replacement for _vrp_macro_param_sweep._sharpe_maxdd.
    Returns {'sharpe', 'maxdd', 'annror'} over the zero-filled monthly series."""
    series = zero_filled_monthly(monthly)
    if not series:
        return {"sharpe": float("nan"), "maxdd": 0.0, "annror": 0.0}
    return {
        "sharpe": annualized_sharpe(series, periods_per_year=12),
        "maxdd": additive_max_drawdown(series),
        "annror": fmean(series) * 12,
    }
```

```python
# src/uw_scan/backtest/__init__.py
"""Unified backtest harness: engine, splitters, gates, metrics, sweep runner.

Design: docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md
"""

from uw_scan.backtest.metrics import (
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
    monthly_summary,
    zero_filled_monthly,
)

__all__ = [
    "additive_max_drawdown",
    "annualized_sharpe",
    "hit_rate",
    "monthly_summary",
    "zero_filled_monthly",
]
```

Also create empty `tests/unit/backtest/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/backtest/test_metrics.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/backtest/ tests/unit/backtest/
git commit -m "feat(backtest): metrics primitives (legacy _sharpe_maxdd conventions)"
```

---

### Task 2: splitters.py — time-ordered holdout

**Files:**
- Create: `src/uw_scan/backtest/splitters.py`
- Modify: `src/uw_scan/backtest/__init__.py` (add export)
- Test: `tests/unit/backtest/test_splitters.py`

**Interfaces:**
- Produces: `time_ordered_holdout(items, *, key, frac) -> tuple[list, list]` returning `(ordered_full, holdout_tail)`. Task 3 consumes it. The `int(round(n * (1 - frac)))` cut is load-bearing — both legacy gate implementations use exactly it, and the byte-identical guarantee depends on it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/backtest/test_splitters.py
from __future__ import annotations

from datetime import date

from uw_scan.backtest.splitters import time_ordered_holdout


def _obs(n: int) -> list[dict]:
    return [{"market_date": date(2026, 1, 1 + i % 27), "i": i} for i in range(n)]


def test_cut_boundary_matches_legacy_int_round():
    items = [{"market_date": date(2026, 1, d)} for d in range(1, 31)]  # n=30
    ordered, holdout = time_ordered_holdout(items, key=lambda o: o["market_date"], frac=0.40)
    assert len(ordered) == 30 and len(holdout) == 12  # cut = int(round(18.0)) = 18

    items5 = [{"market_date": date(2026, 1, d)} for d in range(1, 6)]  # n=5
    _, hold5 = time_ordered_holdout(items5, key=lambda o: o["market_date"], frac=0.40)
    assert len(hold5) == 2  # cut = int(round(3.0)) = 3


def test_sorts_by_key_ascending():
    items = [{"market_date": date(2026, 1, d)} for d in (5, 1, 3)]
    ordered, holdout = time_ordered_holdout(items, key=lambda o: o["market_date"], frac=0.40)
    assert [o["market_date"].day for o in ordered] == [1, 3, 5]
    assert [o["market_date"].day for o in holdout] == [5]  # cut = int(round(1.8)) = 2


def test_empty():
    assert time_ordered_holdout([], key=lambda o: o, frac=0.40) == ([], [])
```

- [ ] **Step 2: Run to verify FAIL** — `uv run pytest tests/unit/backtest/test_splitters.py -v` → `ModuleNotFoundError` / `ImportError`.

- [ ] **Step 3: Implement**

```python
# src/uw_scan/backtest/splitters.py
"""Time-ordered train/test window generators.

Only the holdout splitter exists today. fixed_windows (backtest_canary's
WF-1..WF-5) and rolling (backtest_cri) are added when those scripts migrate —
not before (YAGNI).
"""

from __future__ import annotations

from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


def time_ordered_holdout(
    items: Iterable[T], *, key: Callable[[T], object], frac: float
) -> tuple[list[T], list[T]]:
    """Sort ascending by key; return (ordered, holdout) where holdout is the
    latest tail. Cut index is int(round(n * (1 - frac))) — the EXACT boundary
    of the two legacy gate implementations (skew_markout, vrp_markout_core);
    do not change the rounding."""
    ordered = sorted(items, key=key)
    cut = int(round(len(ordered) * (1.0 - frac)))
    return ordered, ordered[cut:]
```

Add `time_ordered_holdout` to `__init__.py` imports and `__all__`.

- [ ] **Step 4: Run to verify PASS** — `uv run pytest tests/unit/backtest/test_splitters.py -v` → 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/backtest/ tests/unit/backtest/test_splitters.py
git commit -m "feat(backtest): time-ordered holdout splitter (legacy cut boundary preserved)"
```

---

### Task 3: gates.py — unified walk-forward + quarter gates

**Files:**
- Create: `src/uw_scan/backtest/gates.py`
- Modify: `src/uw_scan/backtest/__init__.py` (add exports)
- Test: `tests/unit/backtest/test_gates.py`

**Interfaces:**
- Consumes: `time_ordered_holdout` from Task 2.
- Produces:
  - `quarter_gate(obs: list[dict], overall_mean: float, value_key: str) -> bool`
  - `walkforward_gate(obs, *, value_key, min_n, threshold, holdout_threshold, holdout_frac=0.40, expected_sign: int | None = None) -> dict` with keys `mean, mean_holdout, n, n_holdout, survives_walkforward, survives_window_gate`.
  - Semantics: `expected_sign=+1/-1` → one-sided (both means must have that sign; magnitudes gated on `abs`); `None` → two-sided (full/holdout signs must agree; magnitudes on `abs`). Below `min_n`: descriptive means, both gates `False`. Tasks 7 and 8 consume this.

The two legacy sources being unified (read them before implementing):
- `src/uw_scan/reports/vrp_markout_core.py:109-185` (`survives_quarter_gate`, `walkforward` — `positive_only=True` maps to `expected_sign=1`; `False` maps to `None`)
- `src/uw_scan/reports/skew_markout.py:52-108` (`_rv_survives_window_gate`, `_rv_walkforward` — `expected_sign=±1` maps directly)

Known-safe equivalence note: legacy vrp `positive_only=True` gates magnitude on the SIGNED mean (`mean_full >= threshold`); the unified gate uses `abs(mean_full) >= threshold`. With positive thresholds these agree everywhere the sign check passes, and when the sign check fails the conjunction is False either way — identical `survives_walkforward` for all real inputs. The test below pins this with a legacy replica.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/backtest/test_gates.py
from __future__ import annotations

from datetime import date, timedelta

from uw_scan.backtest.gates import quarter_gate, walkforward_gate

# --- verbatim legacy replica (vrp_markout_core.walkforward before migration) ---
HOLDOUT_FRAC = 0.40


def _legacy_vrp_walkforward(obs, *, min_n, threshold, holdout_threshold,
                            value_key="value", positive_only=True):
    n = len(obs)
    base = {"mean": None, "mean_holdout": None, "n": 0, "n_holdout": 0,
            "survives_walkforward": False, "survives_window_gate": False}
    if n == 0:
        return base
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o[value_key] for o in ordered) / n
    mean_hold = sum(o[value_key] for o in holdout) / len(holdout) if holdout else None
    if n < min_n:
        return {**base, "mean": mean_full, "mean_holdout": mean_hold,
                "n": n, "n_holdout": len(holdout)}
    if positive_only:
        sign_ok = mean_full > 0 and mean_hold is not None and mean_hold > 0
        mag_ok = mean_full >= threshold and (mean_hold is not None and mean_hold >= holdout_threshold)
    else:
        sign_ok = mean_hold is not None and (mean_full * mean_hold > 0)
        mag_ok = abs(mean_full) >= threshold and (mean_hold is not None and abs(mean_hold) >= holdout_threshold)
    survives_wf = bool(sign_ok and mag_ok)
    survives_window = _legacy_quarter(ordered, mean_full, value_key)
    return {"mean": mean_full, "mean_holdout": mean_hold, "n": n,
            "n_holdout": len(holdout), "survives_walkforward": survives_wf,
            "survives_window_gate": survives_window}


def _legacy_quarter(obs, overall_mean, value_key):
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict = {}
    for o in obs:
        d = o["market_date"]
        by_q.setdefault((d.year, (d.month - 1) // 3), []).append(o[value_key])
    for vals in by_q.values():
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def _obs(values, start=date(2025, 1, 6), step_days=7):
    return [{"market_date": start + timedelta(days=i * step_days), "value": v}
            for i, v in enumerate(values)]


CASES = [
    _obs([0.02] * 30),                          # clean one-sided pass
    _obs([0.02] * 18 + [-0.02] * 12),           # holdout flips sign
    _obs([0.02] * 18 + [0.004] * 12),           # holdout mean 0.004 < 0.005 floor
    _obs([-0.02] * 30),                         # wrong sign for positive_only
    _obs([0.02] * 5),                           # sub-min_n, descriptive only
    _obs([]),                                   # empty
    _obs([0.05] * 10 + [-0.30] * 3 + [0.05] * 17),  # Q1 blowup (see direct test)
]


def test_walkforward_gate_matches_legacy_positive_only():
    for obs in CASES:
        old = _legacy_vrp_walkforward(obs, min_n=20, threshold=0.01,
                                      holdout_threshold=0.005, positive_only=True)
        new = walkforward_gate(obs, value_key="value", min_n=20, threshold=0.01,
                               holdout_threshold=0.005, expected_sign=1)
        assert new == old, obs[:2]


def test_walkforward_gate_matches_legacy_two_sided():
    for obs in CASES + [_obs([-0.02] * 30)]:
        old = _legacy_vrp_walkforward(obs, min_n=20, threshold=0.01,
                                      holdout_threshold=0.005, positive_only=False)
        new = walkforward_gate(obs, value_key="value", min_n=20, threshold=0.01,
                               holdout_threshold=0.005, expected_sign=None)
        assert new == old


def test_negative_expected_sign_passes_on_negative_means():
    obs = _obs([-0.02] * 30)
    out = walkforward_gate(obs, value_key="value", min_n=20, threshold=0.01,
                           holdout_threshold=0.005, expected_sign=-1)
    assert out["survives_walkforward"] is True


def test_quarter_gate_direct():
    # weekly dates from 2025-01-06: i=0..12 land in Q1. Q1 mean = (10*.05 - 3*.30)/13
    # ≈ -0.031 — reverses the aggregate (+0.015) with larger magnitude -> gate fails.
    obs = _obs([0.05] * 10 + [-0.30] * 3 + [0.05] * 17)
    mean = sum(o["value"] for o in obs) / len(obs)
    assert abs(mean - 0.015) < 1e-12
    assert quarter_gate(obs, mean, "value") is False
    clean = _obs([0.02] * 30)
    assert quarter_gate(clean, 0.02, "value") is True
    assert quarter_gate(clean, 0.0, "value") is False  # near-zero aggregate auto-fails
```

- [ ] **Step 2: Run to verify FAIL** — `uv run pytest tests/unit/backtest/test_gates.py -v` → ImportError.

- [ ] **Step 3: Implement**

```python
# src/uw_scan/backtest/gates.py
"""OOS discipline gates — the single home for logic previously duplicated in
reports/skew_markout.py (_rv_walkforward/_rv_survives_window_gate) and
reports/vrp_markout_core.py (walkforward/survives_quarter_gate).

quarter_gate is the standing per-window catastrophic-degradation rule
(feedback_per_regime_catastrophic_gate): an aggregate that hides a sub-window
blowup does not survive.
"""

from __future__ import annotations

from collections import defaultdict

from uw_scan.backtest.splitters import time_ordered_holdout


def quarter_gate(obs: list[dict], overall_mean: float, value_key: str) -> bool:
    """Fail if ANY calendar quarter reverses the aggregate sign with LARGER
    magnitude. Near-zero aggregate auto-fails. obs need 'market_date' + value_key."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple[int, int], list[float]] = defaultdict(list)
    for o in obs:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o[value_key])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def walkforward_gate(
    obs: list[dict],
    *,
    value_key: str,
    min_n: int,
    threshold: float,
    holdout_threshold: float,
    holdout_frac: float = 0.40,
    expected_sign: int | None = None,
) -> dict:
    """Holdout gate on the mean of obs[value_key]. Holdout = latest holdout_frac
    by market_date (time-ordered, no leak). expected_sign=+1/-1: one-sided —
    both means must carry that sign, magnitudes gated on abs. None: two-sided —
    full/holdout signs must agree. Below min_n the means stay descriptive and
    both gates are False. Thresholds are positive floors."""
    n = len(obs)
    base = {
        "mean": None,
        "mean_holdout": None,
        "n": 0,
        "n_holdout": 0,
        "survives_walkforward": False,
        "survives_window_gate": False,
    }
    if n == 0:
        return base
    ordered, holdout = time_ordered_holdout(
        obs, key=lambda o: o["market_date"], frac=holdout_frac
    )
    mean_full = sum(o[value_key] for o in ordered) / n
    mean_hold = sum(o[value_key] for o in holdout) / len(holdout) if holdout else None
    if n < min_n:
        return {
            **base,
            "mean": mean_full,
            "mean_holdout": mean_hold,
            "n": n,
            "n_holdout": len(holdout),
        }
    if expected_sign is not None:
        sign_ok = (mean_full * expected_sign > 0) and (
            mean_hold is not None and mean_hold * expected_sign > 0
        )
    else:
        sign_ok = mean_hold is not None and (mean_full * mean_hold > 0)
    mag_ok = abs(mean_full) >= threshold and (
        mean_hold is not None and abs(mean_hold) >= holdout_threshold
    )
    return {
        "mean": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": bool(sign_ok and mag_ok),
        "survives_window_gate": quarter_gate(ordered, mean_full, value_key),
    }
```

Add `quarter_gate`, `walkforward_gate` to `__init__.py`.

- [ ] **Step 4: Run to verify PASS** — `uv run pytest tests/unit/backtest/test_gates.py -v` → 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/backtest/ tests/unit/backtest/test_gates.py
git commit -m "feat(backtest): unified walkforward + quarter gates (legacy-equivalence pinned)"
```

---

### Task 4: engine.py — no-lookahead replay core

**Files:**
- Create: `src/uw_scan/backtest/engine.py`
- Modify: `src/uw_scan/backtest/__init__.py` (add exports)
- Test: `tests/unit/backtest/test_engine.py`

**Interfaces:**
- Consumes: `annualized_sharpe`, `additive_max_drawdown`, `hit_rate` from Task 1.
- Produces: `SignalPoint(date: date, signal: Mapping[str, Any])` (frozen dataclass), `walk_forward_backtest(series, forward_returns: Mapping[date, float], entry_rule, *, cost_fraction=0.0, periods_per_year=252) -> dict` with keys `trades` (list of dicts: `date, position, gross_return, net_return`), `n_trades`, `skipped_no_forward`, `sharpe`, `max_drawdown`, `hit_rate`.
- Contract: `entry_rule(history, point) -> float` sees ONLY `ordered[: i + 1]`; the position is marked against `forward_returns[point.date]` — the return realized AFTER the decision. Radon-shaped, with real `date` keys and a `skipped_no_forward` counter (silent drops hide coverage gaps).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/backtest/test_engine.py
from __future__ import annotations

from datetime import date, timedelta

from uw_scan.backtest.engine import SignalPoint, walk_forward_backtest


def _series(n, start=date(2026, 1, 5)):
    return [SignalPoint(date=start + timedelta(days=i), signal={"i": i}) for i in range(n)]


def test_entry_rule_never_sees_the_future():
    pts = _series(10)
    fwd = {p.date: 0.01 for p in pts}
    seen = []

    def rule(history, point):
        assert history[-1] is point
        assert all(h.date <= point.date for h in history)
        seen.append(len(history))
        return 1.0

    walk_forward_backtest(pts, fwd, rule)
    assert seen == list(range(1, 11))  # history strictly grows, one origin at a time


def test_forward_keying_and_costs():
    pts = _series(2)
    fwd = {pts[0].date: 0.10}  # second origin has no forward return yet
    out = walk_forward_backtest(pts, fwd, lambda h, p: -1.0, cost_fraction=0.01)
    assert out["n_trades"] == 1
    assert out["skipped_no_forward"] == 1
    t = out["trades"][0]
    assert t["gross_return"] == -0.10          # short * +10% move
    assert abs(t["net_return"] - (-0.11)) < 1e-12  # cost scales with |position|


def test_flat_position_skips_without_counting():
    pts = _series(3)
    fwd = {p.date: 0.01 for p in pts}
    out = walk_forward_backtest(pts, fwd, lambda h, p: 0.0)
    assert out["n_trades"] == 0 and out["skipped_no_forward"] == 0


def test_unsorted_input_is_sorted_defensively():
    pts = _series(5)
    fwd = {p.date: 0.01 for p in pts}
    out = walk_forward_backtest(list(reversed(pts)), fwd, lambda h, p: 1.0)
    assert [t["date"] for t in out["trades"]] == [p.date for p in pts]
```

- [ ] **Step 2: Run to verify FAIL** — `uv run pytest tests/unit/backtest/test_engine.py -v` → ImportError.

- [ ] **Step 3: Implement**

```python
# src/uw_scan/backtest/engine.py
"""Walk-forward replay engine — look-ahead-free by construction.

Replays a chronologically ordered signal series. At each origin t the entry
rule sees the history of points dated <= t (and only those) and returns a
signed position weight. A non-flat position is marked against the FORWARD
return keyed at t — the return realized over the window that starts after the
decision. That keying is the whole no-lookahead guarantee.

The engine is scalar return-space on purpose: multi-leg options structures
(condors, spreads) are priced by strategy code into forward_returns; the trade
record carries the origin's signal payload for the trace. Pure logic — no DB,
no network, no numpy. Reference shape: radon scripts/backtest/engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from uw_scan.backtest.metrics import (
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
)

EntryRule = Callable[[Sequence["SignalPoint"], "SignalPoint"], float]


@dataclass(frozen=True)
class SignalPoint:
    """One dated row of a replayed signal series. The engine never inspects
    `signal` — only the strategy's entry rule does."""

    date: date
    signal: Mapping[str, Any]


def walk_forward_backtest(
    series: Sequence[SignalPoint],
    forward_returns: Mapping[date, float],
    entry_rule: EntryRule,
    *,
    cost_fraction: float = 0.0,
    periods_per_year: int = 252,
) -> dict:
    """Replay `series` in date order. entry_rule sees ONLY series[: i + 1] at
    origin i. cost_fraction is a round-trip cost as a fraction of notional,
    scaled by |position|. Origins with no forward return are counted in
    skipped_no_forward, never silently dropped."""
    ordered = sorted(series, key=lambda p: p.date)
    trades: list[dict] = []
    skipped_no_forward = 0
    for i, point in enumerate(ordered):
        history = ordered[: i + 1]
        position = float(entry_rule(history, point))
        if position == 0.0:
            continue
        if point.date not in forward_returns:
            skipped_no_forward += 1
            continue
        gross = position * forward_returns[point.date]
        net = gross - cost_fraction * abs(position)
        trades.append(
            {
                "date": point.date,
                "position": position,
                "gross_return": gross,
                "net_return": net,
            }
        )
    returns = [t["net_return"] for t in trades]
    return {
        "trades": trades,
        "n_trades": len(trades),
        "skipped_no_forward": skipped_no_forward,
        "sharpe": annualized_sharpe(returns, periods_per_year=periods_per_year),
        "max_drawdown": additive_max_drawdown(returns),
        "hit_rate": hit_rate(returns),
    }
```

Add `SignalPoint`, `walk_forward_backtest` to `__init__.py`.

- [ ] **Step 4: Run to verify PASS** — `uv run pytest tests/unit/backtest/test_engine.py -v` → 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/backtest/ tests/unit/backtest/test_engine.py
git commit -m "feat(backtest): no-lookahead walk-forward replay engine"
```

---

### Task 5: migration 095 + BacktestRepository

**Files:**
- Create: `src/uw_scan/storage/migrations/095_backtest_harness.sql`
- Create: `src/uw_scan/storage/backtest_repository.py`
- Test: `tests/integration/storage/test_backtest_repository.py`

**Interfaces:**
- Produces: `BacktestRepository(conn, schema="uw_scan")` with:
  - `create_run(*, strategy: str, reproduce_cmd: str, params_grid: dict | None = None, git_sha: str | None = None, data_start: date | None = None, data_end: date | None = None, notes: str | None = None) -> int`
  - `insert_result(run_id: int, *, config: dict, metrics: dict | None = None, gates: dict | None = None, n_trades: int | None = None, status: str = "ok", error: str | None = None) -> int`
  - `complete_run(run_id: int, *, status: str = "completed", error: str | None = None) -> None`
  - `fetch_run_results(run_id: int) -> list[dict]` (ordered by id)
  - Every write commits immediately (persist-as-you-go: a crash at config 80/100 loses nothing). Task 6 consumes this.

- [ ] **Step 1: Write the migration**

```sql
-- src/uw_scan/storage/migrations/095_backtest_harness.sql
-- Backtest harness persistence: one run per sweep, one row per grid config.
-- Standing rule: every research/backtest trace persists in full, with the
-- exact reproduce command (reproduce_cmd is NOT NULL by design).
SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS backtest_sweep_runs (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy      TEXT NOT NULL,
    git_sha       TEXT,
    reproduce_cmd TEXT NOT NULL,
    params_grid   JSONB,
    data_start    DATE,
    data_end      DATE,
    status        TEXT NOT NULL DEFAULT 'running',
    error         TEXT,
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS backtest_sweep_results (
    id         BIGSERIAL PRIMARY KEY,
    run_id     BIGINT NOT NULL REFERENCES backtest_sweep_runs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    config     JSONB NOT NULL,
    metrics    JSONB,
    gates      JSONB,
    n_trades   INTEGER,
    status     TEXT NOT NULL DEFAULT 'ok',
    error      TEXT
);

CREATE INDEX IF NOT EXISTS idx_backtest_sweep_results_run
    ON backtest_sweep_results (run_id);
```

- [ ] **Step 2: Write the failing integration test**

The `seeded_db_empty_cards` fixture (tests/integration/conftest.py) yields a migrated `Repository`; construct the standalone repo from its `.conn` (same pattern as the other storage tests).

```python
# tests/integration/storage/test_backtest_repository.py
from __future__ import annotations

from datetime import date

from uw_scan.storage.backtest_repository import BacktestRepository


def test_run_and_results_roundtrip(seeded_db_empty_cards) -> None:
    repo = BacktestRepository(seeded_db_empty_cards.conn)
    run_id = repo.create_run(
        strategy="vrp_macro_sweep",
        reproduce_cmd="uv run python scripts/_vrp_macro_param_sweep.py",
        params_grid={"short_delta": [0.25, 0.30]},
        data_start=date(2006, 1, 3),
        data_end=date(2026, 6, 30),
        notes="test",
    )
    assert isinstance(run_id, int)
    rid1 = repo.insert_result(
        run_id,
        config={"short_delta": 0.25, "hold_days": 30, "sizing": "ramp+"},
        metrics={"sharpe": 1.65, "maxdd": -0.12},
        gates={"survives_walkforward": True},
        n_trades=210,
    )
    rid2 = repo.insert_result(
        run_id,
        config={"short_delta": 0.30},
        status="error",
        error="ValueError('no solution')",
    )
    assert rid2 > rid1
    repo.complete_run(run_id)
    rows = repo.fetch_run_results(run_id)
    assert len(rows) == 2
    assert rows[0]["config"]["sizing"] == "ramp+"
    assert float(rows[0]["metrics"]["sharpe"]) == 1.65
    assert rows[1]["status"] == "error" and rows[1]["metrics"] is None


def test_complete_run_sets_status(seeded_db_empty_cards) -> None:
    repo = BacktestRepository(seeded_db_empty_cards.conn)
    run_id = repo.create_run(strategy="s", reproduce_cmd="cmd")
    repo.complete_run(run_id, status="error", error="all configs failed")
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT status, error FROM backtest_sweep_runs WHERE id = %s", (run_id,)
        )
        status, error = cur.fetchone()
    assert status == "error" and error == "all configs failed"
```

- [ ] **Step 3: Run to verify FAIL** — `uv run pytest tests/integration/storage/test_backtest_repository.py -v` → ImportError (module doesn't exist). Note: the session-scoped migration fixture runs `scripts/migrate.sh`, which picks up 095 lexically — no fixture changes needed.

- [ ] **Step 4: Implement**

```python
# src/uw_scan/storage/backtest_repository.py
"""Persistence for backtest harness sweep runs/results (migration 095). New
domain — own file (never appended to repository.py)."""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class BacktestRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def create_run(
        self,
        *,
        strategy: str,
        reproduce_cmd: str,
        params_grid: dict | None = None,
        git_sha: str | None = None,
        data_start: date | None = None,
        data_end: date | None = None,
        notes: str | None = None,
    ) -> int:
        sql = """
            INSERT INTO backtest_sweep_runs
                (strategy, reproduce_cmd, params_grid, git_sha,
                 data_start, data_end, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    strategy,
                    reproduce_cmd,
                    Jsonb(params_grid) if params_grid is not None else None,
                    git_sha,
                    data_start,
                    data_end,
                    notes,
                ),
            )
            run_id = cur.fetchone()[0]
        self._conn.commit()
        return int(run_id)

    def insert_result(
        self,
        run_id: int,
        *,
        config: dict,
        metrics: dict | None = None,
        gates: dict | None = None,
        n_trades: int | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> int:
        sql = """
            INSERT INTO backtest_sweep_results
                (run_id, config, metrics, gates, n_trades, status, error)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    run_id,
                    Jsonb(config),
                    Jsonb(metrics) if metrics is not None else None,
                    Jsonb(gates) if gates is not None else None,
                    n_trades,
                    status,
                    error,
                ),
            )
            rid = cur.fetchone()[0]
        self._conn.commit()
        return int(rid)

    def complete_run(
        self, run_id: int, *, status: str = "completed", error: str | None = None
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE backtest_sweep_runs SET status = %s, error = %s WHERE id = %s",
                (status, error, run_id),
            )
        self._conn.commit()

    def fetch_run_results(self, run_id: int) -> list[dict]:
        sql = """
            SELECT id, created_at, config, metrics, gates, n_trades, status, error
              FROM backtest_sweep_results
             WHERE run_id = %s
             ORDER BY id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
```

- [ ] **Step 5: Verify migration idempotence + tests pass**

Run: `uv run pytest tests/integration/storage/test_backtest_repository.py -v` → 2 PASS.
Then idempotence (repo standing rule — re-run must be a no-op): apply the migration twice against the local dev DB:
```bash
bash scripts/migrate.sh && bash scripts/migrate.sh
```
Expected: second run completes without error.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/095_backtest_harness.sql src/uw_scan/storage/backtest_repository.py tests/integration/storage/test_backtest_repository.py
git commit -m "feat(backtest): sweep persistence — migration 095 + BacktestRepository"
```

---

### Task 6: sweep.py — grid runner with persist-as-you-go

**Files:**
- Create: `src/uw_scan/backtest/sweep.py`
- Modify: `src/uw_scan/backtest/__init__.py` (add exports)
- Test: `tests/unit/backtest/test_sweep.py` (stub repo — allowed in unit), `tests/integration/storage/test_backtest_sweep.py` (real DB)

**Interfaces:**
- Consumes: `BacktestRepository` protocol from Task 5 (`create_run`, `insert_result`, `complete_run`).
- Produces:
  - `json_safe(value) -> value` — recursively replaces non-finite floats (nan/inf) with `None`. REQUIRED because `json.dumps(nan)` emits `NaN`, which Postgres jsonb REJECTS — a sweep whose zero-dispersion config yields `sharpe=nan` must persist `null`, not crash the run.
  - `run_sweep(configs, run_one, *, repo, strategy, reproduce_cmd, params_grid=None, git_sha=None, data_start=None, data_end=None, notes=None) -> dict` with keys `run_id, n_ok, n_error, results`. `run_one(config) -> dict` returns at least `{"metrics": dict}`, optionally `gates`, `n_trades`. One config failing logs `repr(exc)`, persists an error row, and continues. Task 9 consumes this.

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/backtest/test_sweep.py
from __future__ import annotations

import math

from uw_scan.backtest.sweep import json_safe, run_sweep


class _StubRepo:
    def __init__(self):
        self.results = []
        self.completed = None

    def create_run(self, **kw):
        self.run_kw = kw
        return 7

    def insert_result(self, run_id, **kw):
        self.results.append((run_id, kw))
        return len(self.results)

    def complete_run(self, run_id, *, status="completed", error=None):
        self.completed = (run_id, status, error)


def test_json_safe_replaces_non_finite():
    assert json_safe({"a": float("nan"), "b": [1.0, float("inf")], "c": "x"}) == {
        "a": None,
        "b": [1.0, None],
        "c": "x",
    }


def test_run_sweep_persists_each_config_and_survives_failures():
    repo = _StubRepo()

    def run_one(cfg):
        if cfg["x"] == 2:
            raise ValueError("boom")
        return {"metrics": {"sharpe": float("nan") if cfg["x"] == 3 else 1.0},
                "n_trades": cfg["x"]}

    out = run_sweep(
        [{"x": 1}, {"x": 2}, {"x": 3}],
        run_one,
        repo=repo,
        strategy="s",
        reproduce_cmd="cmd",
    )
    assert out["run_id"] == 7 and out["n_ok"] == 2 and out["n_error"] == 1
    assert len(repo.results) == 3
    assert repo.results[1][1]["status"] == "error"
    assert "ValueError" in repo.results[1][1]["error"]
    assert repo.results[2][1]["metrics"]["sharpe"] is None  # nan sanitized
    assert repo.completed == (7, "completed", None)
    assert len(out["results"]) == 2  # only ok configs returned for in-process use


def test_run_sweep_all_failed_marks_run_error():
    repo = _StubRepo()
    out = run_sweep([{"x": 1}], lambda c: 1 / 0, repo=repo, strategy="s", reproduce_cmd="c")
    assert repo.completed[1] == "error" and out["n_ok"] == 0
```

- [ ] **Step 2: Run to verify FAIL** — `uv run pytest tests/unit/backtest/test_sweep.py -v` → ImportError.

- [ ] **Step 3: Implement**

```python
# src/uw_scan/backtest/sweep.py
"""Parameter-sweep runner: run every config, persist every row as it completes.

Standing rule (CLAUDE.md): a sweep's FULL result set persists — every config,
every metric, plus the exact reproduce command. stdout-only is data loss.
Persist-as-you-go: a crash at config 80/100 keeps the first 79 rows.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with None. json.dumps(nan) emits
    'NaN', which Postgres jsonb rejects — a zero-dispersion config's nan Sharpe
    must persist as null, not kill the run."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def run_sweep(
    configs: Iterable[dict],
    run_one: Callable[[dict], dict],
    *,
    repo,
    strategy: str,
    reproduce_cmd: str,
    params_grid: dict | None = None,
    git_sha: str | None = None,
    data_start=None,
    data_end=None,
    notes: str | None = None,
) -> dict:
    """run_one(config) -> {'metrics': dict, 'gates': dict | None,
    'n_trades': int | None, ...}. A config that raises is logged, persisted as
    an error row, and the sweep continues. Returns
    {'run_id', 'n_ok', 'n_error', 'results'} — results carries only ok configs
    (each as {'config': ..., **run_one_output}) for in-process ranking."""
    run_id = repo.create_run(
        strategy=strategy,
        reproduce_cmd=reproduce_cmd,
        params_grid=params_grid,
        git_sha=git_sha,
        data_start=data_start,
        data_end=data_end,
        notes=notes,
    )
    n_ok = n_error = 0
    results: list[dict] = []
    for config in configs:
        try:
            out = run_one(config)
        except Exception as exc:
            log.error("sweep config %s failed: %r", config, exc)
            repo.insert_result(
                run_id, config=json_safe(config), status="error", error=repr(exc)
            )
            n_error += 1
            continue
        repo.insert_result(
            run_id,
            config=json_safe(config),
            metrics=json_safe(out.get("metrics")),
            gates=json_safe(out.get("gates")),
            n_trades=out.get("n_trades"),
        )
        n_ok += 1
        results.append({"config": config, **out})
    repo.complete_run(
        run_id,
        status="completed" if n_ok else "error",
        error=None if n_ok else "all configs failed",
    )
    return {"run_id": run_id, "n_ok": n_ok, "n_error": n_error, "results": results}
```

Add `json_safe`, `run_sweep` to `__init__.py`.

- [ ] **Step 4: Run to verify PASS** — `uv run pytest tests/unit/backtest/test_sweep.py -v` → 3 PASS.

- [ ] **Step 5: Write + run the integration test (real DB, real jsonb nan path)**

```python
# tests/integration/storage/test_backtest_sweep.py
from __future__ import annotations

from uw_scan.backtest.sweep import run_sweep
from uw_scan.storage.backtest_repository import BacktestRepository


def test_run_sweep_end_to_end_with_nan_and_failure(seeded_db_empty_cards) -> None:
    repo = BacktestRepository(seeded_db_empty_cards.conn)

    def run_one(cfg):
        if cfg["hold_days"] == 14:
            raise RuntimeError("no data")
        sharpe = float("nan") if cfg["hold_days"] == 7 else 1.2
        return {"metrics": {"sharpe": sharpe, "maxdd": -0.1}, "n_trades": 5}

    out = run_sweep(
        [{"hold_days": 7}, {"hold_days": 14}, {"hold_days": 30}],
        run_one,
        repo=repo,
        strategy="itest",
        reproduce_cmd="uv run pytest tests/integration/storage/test_backtest_sweep.py",
        params_grid={"hold_days": [7, 14, 30]},
    )
    rows = repo.fetch_run_results(out["run_id"])
    assert [r["status"] for r in rows] == ["ok", "error", "ok"]
    assert rows[0]["metrics"]["sharpe"] is None      # nan persisted as null, jsonb accepted it
    assert rows[2]["metrics"]["sharpe"] == 1.2
    assert "RuntimeError" in rows[1]["error"]
```

Run: `uv run pytest tests/integration/storage/test_backtest_sweep.py -v` → 1 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/backtest/ tests/unit/backtest/test_sweep.py tests/integration/storage/test_backtest_sweep.py
git commit -m "feat(backtest): sweep runner — persist-as-you-go, nan-safe jsonb"
```

---

### Task 7: migrate skew_markout.py onto gates

**Files:**
- Modify: `src/uw_scan/reports/skew_markout.py` (delete `_rv_survives_window_gate` lines 52-69; rewrite `_rv_walkforward` body lines 72-108)
- Test: existing `tests/integration/reports/test_skew_markout.py` + `tests/integration/reports/test_skew_rv_markout.py` MUST pass unchanged — they are the regression pin. No new tests.

**Interfaces:**
- Consumes: `walkforward_gate` from Task 3.
- Produces: `_rv_walkforward(obs, expected_sign) -> dict` — same signature, byte-identical output dict (keys `verdict, mean_drr, mean_drr_holdout, n, n_holdout, survives_walkforward, survives_window_gate`).

- [ ] **Step 1: Rewrite the two functions**

Delete `_rv_survives_window_gate` entirely. Replace `_rv_walkforward` with:

```python
from uw_scan.backtest.gates import walkforward_gate


def _rv_walkforward(obs: list[dict], expected_sign: int) -> dict:
    """obs: [{'drr': float, 'market_date': date}], any order. Returns the verdict dict.
    REVERTS requires expected sign + magnitude (full & holdout) AND the quarterly
    catastrophic-degradation gate. Delegates to uw_scan.backtest.gates; this
    adapter only maps key names and the verdict string."""
    n = len(obs)
    if n < RV_MIN_N or expected_sign == 0:
        return {
            "verdict": "NONE",
            "mean_drr": None,
            "mean_drr_holdout": None,
            "n": n,
            "n_holdout": 0,
            "survives_walkforward": False,
            "survives_window_gate": False,
        }
    wf = walkforward_gate(
        obs,
        value_key="drr",
        min_n=RV_MIN_N,
        threshold=RV_SEP_THRESHOLD,
        holdout_threshold=RV_HOLDOUT_THRESHOLD,
        holdout_frac=RV_HOLDOUT_FRAC,
        expected_sign=expected_sign,
    )
    reverts = wf["survives_walkforward"] and wf["survives_window_gate"]
    return {
        "verdict": "REVERTS" if reverts else "NONE",
        "mean_drr": wf["mean"],
        "mean_drr_holdout": wf["mean_holdout"],
        "n": wf["n"],
        "n_holdout": wf["n_holdout"],
        "survives_walkforward": wf["survives_walkforward"],
        "survives_window_gate": wf["survives_window_gate"],
    }
```

Also remove the now-unused `defaultdict` import IF nothing else in the module uses it (check first — the module has other uses; only remove if actually unused). Keep the module constants (`RV_HOLDOUT_FRAC` etc.) — they are this call site's policy, not the harness's.

Reachability note (why byte-identical holds): the legacy code returned `mean_drr_holdout=0.0` when the holdout was empty, the gate returns `None` — but with `n >= RV_MIN_N = 30` and `frac = 0.40`, `cut = 18 < 30`, so the holdout is never empty on any reachable path.

- [ ] **Step 2: Run the regression net**

Run: `uv run pytest tests/integration/reports/test_skew_markout.py tests/integration/reports/test_skew_rv_markout.py tests/unit -k skew -v`
Expected: ALL PASS, zero test-file changes.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/reports/skew_markout.py
git commit -m "refactor(skew): delegate walkforward/quarter gates to uw_scan.backtest"
```

---

### Task 8: migrate vrp_markout_core.py onto gates

**Files:**
- Modify: `src/uw_scan/reports/vrp_markout_core.py` (rewrite `survives_quarter_gate` lines 109-125 and `walkforward` lines 128-185 as delegations)
- Test: existing `tests/unit/test_vrp_markout_core.py`, `tests/unit/test_vrp_markout_gates.py`, `tests/integration/reports/test_vrp_markout*.py`, `tests/integration/reports/test_vrp_backtest.py` MUST pass unchanged. No new tests.

**Interfaces:**
- Consumes: `quarter_gate`, `walkforward_gate` from Task 3.
- Produces: `survives_quarter_gate(obs, overall_mean, value_key) -> bool` and `walkforward(obs, *, min_n=MIN_N, threshold, holdout_threshold, value_key="value", positive_only=True) -> dict` — SAME public signatures (8 modules call `walkforward`: vrp_markout, vrp_directional, vrp_backtest, vrp_macro_harvest, vrp_harvest_axes, vrp_candidates, vrp_rv_validation, worker/jobs/vrp_trading_jobs). `apply_split_adjustment` and `forward_realized_vol` stay untouched — they are measurement, not gating.

- [ ] **Step 1: Rewrite the two functions as delegations**

```python
from uw_scan.backtest.gates import quarter_gate, walkforward_gate


def survives_quarter_gate(obs: list[dict], overall_mean: float, value_key: str) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (standing rule).
    Canonical implementation: uw_scan.backtest.gates.quarter_gate."""
    return quarter_gate(obs, overall_mean, value_key)


def walkforward(
    obs: list[dict],
    *,
    min_n: int = MIN_N,
    threshold: float,
    holdout_threshold: float,
    value_key: str = "value",
    positive_only: bool = True,
) -> dict:
    """Walk-forward holdout on the mean of obs[value_key]. positive_only=True
    for one-sided claims (harvest > 0); False for two-sided. Delegates to
    uw_scan.backtest.gates.walkforward_gate (expected_sign=+1 / None)."""
    return walkforward_gate(
        obs,
        value_key=value_key,
        min_n=min_n,
        threshold=threshold,
        holdout_threshold=holdout_threshold,
        holdout_frac=HOLDOUT_FRAC,
        expected_sign=1 if positive_only else None,
    )
```

Remove the now-unused `defaultdict` import if nothing else in the module uses it (check — `apply_split_adjustment`/`forward_realized_vol` don't). Keep `ANNUALIZATION`, `HOLDOUT_FRAC`, `MIN_N` constants.

- [ ] **Step 2: Run the regression net**

Run: `uv run pytest tests/unit/test_vrp_markout_core.py tests/unit/test_vrp_markout_gates.py tests/integration/reports -k vrp -v`
Expected: ALL PASS unchanged.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/reports/vrp_markout_core.py
git commit -m "refactor(vrp): delegate walkforward/quarter gates to uw_scan.backtest"
```

---

### Task 9: acceptance — VRP macro sweep through the harness

**Files:**
- Modify: `scripts/_vrp_macro_param_sweep.py`

Goal: the sweep computes its metrics through `uw_scan.backtest.metrics` and persists its synthesis grid through `run_sweep` — and its printed numbers are IDENTICAL to the pre-refactor script's output. This is the "current strategies run smoothly" proof and empirically re-validates the metric conventions against the saved Sharpe ≈ 1.65 trace.

- [ ] **Step 1: Capture the pre-refactor baseline output**

BEFORE touching the script (verify `git status` clean for it), run the CURRENT script against the local dev DB and save the output:

```bash
cd .worktrees/backtest-walkforward-harness
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=chenxi UW_SCAN_API_KEY=x \
uv run python scripts/_vrp_macro_param_sweep.py | tee "$SCRATCHPAD/vrp_sweep_baseline.txt"
```

(`$SCRATCHPAD` = the session scratchpad dir; any path outside the repo is fine.)
Expected: the three printed tables (delta×DTE, synthesis grid, QQQ/IWM extension). If the local DB lacks the SPX/QQQ/IWM vol history (empty tables → the script prints headers with no rows or errors), STOP and report the blocker — do NOT proceed to compare against fabricated numbers.

- [ ] **Step 2: Refactor the script**

Changes, keeping everything else (especially `run_cfg`'s trade loop and all printing formats) byte-identical:

1. Replace the imports block additions:
```python
from uw_scan.backtest.metrics import monthly_summary
from uw_scan.backtest.sweep import run_sweep
from uw_scan.storage.backtest_repository import BacktestRepository
```
2. Delete `_sharpe_maxdd` (lines 50-70) and remove the now-unused `fmean, pstdev, sqrt` imports (keep any still used).
3. In `run_cfg`, replace
```python
    sh, dd, ar = _sharpe_maxdd(monthly)
```
with
```python
    s = monthly_summary(monthly)
    sh, dd, ar = s["sharpe"], s["maxdd"], s["annror"]
```
4. In the portfolio section (`main`, near the end), replace `sh, dd, ar = _sharpe_maxdd(port)` the same way.
5. Rewrite section 2 (the synthesis grid, currently the `for sd in (0.25, 0.30, 0.35): ...` triple loop) to run through the harness:

```python
    # 2) synthesis grid (weekly ladder x vrp-z sizing) — the lever, persisted (migration 095)
    print("\n=== synthesis: weekly ladder x vrp-z sizing (SPX, full history) ===")
    print(
        f"{'Δ':>5} {'DTE':>4} {'sizing':>7} {'n':>5} {'SHARPE':>7} {'maxDD':>7} {'Calmar':>7}"
    )
    configs = [
        {"short_delta": sd, "hold_days": hd, "sizing": sizing}
        for sd in (0.25, 0.30, 0.35)
        for hd in (20, 30)
        for sizing in ("always", "gate0", "ramp", "ramp+")
    ]

    def run_one(cfg):
        o = run_cfg(
            spx,
            short_delta=cfg["short_delta"],
            hold_days=cfg["hold_days"],
            cadence=5,
            sizing=cfg["sizing"],
        )
        return {
            "metrics": {k: o[k] for k in ("sharpe", "maxdd", "annror", "calmar")},
            "n_trades": o["n"],
            "_o": o,
        }

    bt_repo = BacktestRepository(conn, schema=settings.db_schema)
    sweep_out = run_sweep(
        configs,
        run_one,
        repo=bt_repo,
        strategy="vrp_macro_bull_put_spread",
        reproduce_cmd=(
            "UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local "
            "UW_SCAN_DB_USER=chenxi UW_SCAN_API_KEY=x "
            "uv run python scripts/_vrp_macro_param_sweep.py"
        ),
        params_grid={
            "short_delta": [0.25, 0.30, 0.35],
            "hold_days": [20, 30],
            "sizing": ["always", "gate0", "ramp", "ramp+"],
        },
        data_start=spx[0][0][0],
        data_end=spx[0][-1][0],
        notes="section-2 synthesis grid; sections 1/3 remain print-only",
    )
    grid = []
    for r in sweep_out["results"]:
        cfg, o = r["config"], r["_o"]
        grid.append((cfg["short_delta"], cfg["hold_days"], cfg["sizing"], o))
        print(
            f"{cfg['short_delta']:>5.2f} {cfg['hold_days']:>4} {cfg['sizing']:>7} "
            f"{o['n']:>5} {o['sharpe']:>7.2f} {o['maxdd']:>7.2f} {o['calmar']:>7.2f}"
        )
    print(f"(persisted run_id={sweep_out['run_id']} -> uw_scan.backtest_sweep_results)")
    grid.sort(
        key=lambda x: x[3]["sharpe"] if x[3]["sharpe"] == x[3]["sharpe"] else -9,
        reverse=True,
    )
    bsd, bhd, bsizing, _ = grid[0]
    print(f"\nwinner: Δ{bsd:.2f} DTE{bhd} {bsizing}")
```

Also update the module docstring's last paragraph with one line noting the synthesis grid now persists via migration 095. `calmar` may be `inf` — `json_safe` in the sweep runner nulls it in the DB; the printed value is unchanged.

- [ ] **Step 3: Apply the migration locally, run, and diff**

```bash
bash scripts/migrate.sh   # picks up 095 on option_wizard_local
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=chenxi UW_SCAN_API_KEY=x \
uv run python scripts/_vrp_macro_param_sweep.py | tee "$SCRATCHPAD/vrp_sweep_after.txt"
diff <(grep -v "persisted run_id" "$SCRATCHPAD/vrp_sweep_after.txt") "$SCRATCHPAD/vrp_sweep_baseline.txt"
```

Expected: empty diff (the only new line, `persisted run_id=…`, is filtered). Every Sharpe/maxDD/Calmar number identical to baseline — including the headline winner (per the saved trace: weekly + ramp+ + DTE≈30 → SPX Sharpe ~1.65 on the full-history window).

- [ ] **Step 4: Verify the persisted trace**

```bash
psql -h 127.0.0.1 -U chenxi -d option_wizard_local \
  -c "SELECT count(*), count(*) FILTER (WHERE status='ok') FROM uw_scan.backtest_sweep_results r
      JOIN uw_scan.backtest_sweep_runs u ON u.id = r.run_id
      WHERE u.strategy = 'vrp_macro_bull_put_spread'"
```
Expected: 24 rows (3 deltas × 2 DTEs × 4 sizings), all `ok`.

- [ ] **Step 5: Commit**

```bash
git add scripts/_vrp_macro_param_sweep.py
git commit -m "refactor(vrp): run macro param sweep through the backtest harness (persisted trace)"
```

---

### Task 10: docs, changelog, full local CI reproduction

**Files:**
- Modify: `CHANGELOG.md` (`[Unreleased]` → `### Added`)
- Modify: `CLAUDE.md` ("Where to look first" table)
- Modify: `AGENTS.md` only if it mirrors the same table (check; sync rule applies to policy changes)

- [ ] **Step 1: CHANGELOG entry**

Add under `[Unreleased]` / `### Added` (match the file's existing entry style):

```markdown
- Unified backtest harness `src/uw_scan/backtest/` (no-lookahead replay engine,
  time-ordered holdout splitter, walkforward+quarter OOS gates, legacy-convention
  metrics, persist-as-you-go sweep runner) + migration 095
  (`backtest_sweep_runs`/`backtest_sweep_results`). `skew_markout` and
  `vrp_markout_core` gate logic deduplicated onto it (behavior-identical);
  `scripts/_vrp_macro_param_sweep.py` synthesis grid now persists its full trace.
```

- [ ] **Step 2: CLAUDE.md row**

Add to the "Where to look first" table:

```markdown
| Backtest harness (engine/gates/metrics/sweep) | `src/uw_scan/backtest/` + `storage/backtest_repository.py` + migration `095`; consumers: `reports/{skew_markout,vrp_markout_core}.py`, `scripts/_vrp_macro_param_sweep.py`; plan `docs/superpowers/plans/2026-07-03-backtest-walkforward-harness.md` |
```

- [ ] **Step 3: Reproduce the FULL lint+unit CI job locally** (standing memory: it runs more than ruff+pytest)

```bash
cd .worktrees/backtest-walkforward-harness
python3 scripts/release/version_sync_check.py
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -v
```
Expected: all clean. Then the integration suite:
```bash
uv run pytest tests/integration/ -q
```
Expected: PASS (pre-existing failures, if any, must be shown to the user, not absorbed).

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md CLAUDE.md
git commit -m "docs: backtest harness changelog + CLAUDE.md pointer"
```

The branch already carries `docs/research/2026-07-03-radon-feature-probe.md` + the research README row (uncommitted) — include them in this commit if still unstaged:
```bash
git add docs/research/2026-07-03-radon-feature-probe.md docs/research/README.md
git commit --amend --no-edit
```

---

## Completion

After Task 10: push the branch and open the PR (title: `feat(backtest): unified walk-forward backtest harness`), body summarizing: harness modules, byte-identical gate migration (regression evidence), sweep persistence (migration 095), and the Task 9 baseline-vs-after diff result as the acceptance evidence. Wait for CI green before any merge (standing rule). Do not merge without explicit user request.
