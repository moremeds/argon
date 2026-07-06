# LEAP Vega-Alpha Feasibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether radon's "cheap LEAP" thesis — HV20/HV60 minus a long-dated option's ATM IV is a wide positive gap ⇒ the market underprices forward vol ⇒ buying the LEAP is long-vega alpha — is a real, backtestable edge in argon's banked data, and deliver an honest verdict doc.

**Architecture:** Two-stage read-only research spike, mirroring the merged SVI spike (PR #219). Stage 1 is a cheap, falsifiable convergence gate (DB + apex bars only): does a wide entry gap predict the *same LEAP contract's* IV rising over the next 20/40 trading days? Stage 2 runs **only if Stage 1 shows signal** — it marks flagged LEAPs forward and decomposes gross P&L (`vega·ΔIV + delta·ΔS + theta·Δt`), then reports the break-even spread versus a realistic LEAP spread range. All findings persist to `docs/research/leap-vega-alpha/` as a verdict doc + full CSV traces.

**Tech Stack:** Python 3.13 via `uv`; psycopg 3 (read-only over mini `option_wizard`); numpy + scipy (`spearmanr`, already a dep from the SVI work); httpx (apex `/bars`); pytest. Reuses `scripts/research/svi_fit.py::forward_from_delta` for the ATM anchor.

## Global Constraints

- **uv only** — every command is `uv run ...`; never bare `python`/`pytest`.
- **Read-only DB** — this spike issues zero writes/DDL to `option_surface_grid_daily` or any table. It makes **zero UW/IB calls**.
- **DB isolation env** — all DB-touching commands run with `UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1` (mini, prodlike). `Settings.from_env()` requires a `UW_SCAN_API_KEY` present via `.env`/`.env.local` — copy both from the main checkout (gitignored) into the worktree before running; the key only satisfies a config presence guard (no UW calls made).
- **Persist every trace** — full result set (every config × every metric) lands as committed CSVs under `docs/research/leap-vega-alpha/`, plus the exact reproduce command in the verdict doc. stdout-only is data loss.
- **Single-regime caveat is load-bearing** — history is ~6 months / one regime (2025-12-26 → 2026-07-02, 129 dates). The verdict doc must state up front that this validates a short-horizon proxy, **not** hold-to-expiry harvest, and a Stage-1 pass is a "wait for more history" green light, not a deploy signal.
- **Methodology hygiene (primary metric is cross-sectional, not pooled)** — three traps this plan must not fall into, all consequences of 6-month/single-regime data:
  1. **Regime-drift + ticker-identity confound.** If IV generally rose over the sample, *every* contract's forward ΔIV skews positive → pooled `hit_rate > 0.5` and positive pooled `rank_ic` appear for **any** signal, including noise. **The primary metric is therefore a Fama-MacBeth cross-sectional IC**: within each (entry date, horizon) cohort, correlate gap vs forward ΔIV across names, then average across dates. The common vol move cancels within-date. But FM still does **not** neutralize *persistent ticker/asset-class identity* (a name that always carries a wide gap and whose IV always rises) — so the gate runs on a **single-name-only** panel, with a **leave-one-ticker-out** floor (`loo_min_ic_sn`, signal must survive dropping any one ticker) and ETFs reported **separately** (ETF IV/HV/VRP dynamics differ structurally). Pooled and ETF metrics are context, never the gate.
  2. **Overlapping-window autocorrelation.** 129 daily entries each with a 20/40-day forward window means consecutive observations share ~95% of their forward path and near-identical gaps → pooled `n` is inflated ~20–40×; effective sample is tiny. Mitigations: (a) the Fama-MacBeth framing treats each date as one observation; (b) report the FM t-stat over dates (autocorrelation across the overlapping dates still inflates it — state this explicitly, do not claim significance the data can't support); (c) a **non-overlapping sensitivity** run (entries spaced ≥ h apart per contract) is the honest sample-size floor.
  3. **No look-ahead.** HV is computed through the entry date's close; IV is the entry date's EOD snapshot (capture job runs 19:00 ET, after close); forward IV is entry+h EOD. All three are EOD-consistent — no future data leaks. Keep it that way.
- **The gate is exact, single-name, and non-overlap-binding** — a threshold **passes** (for a given horizon) iff, on the **single-name** panel, all four hold: `fm_ic_sn > 0`; its non-overlapping counterpart `fm_ic_sn_nonoverlap > 0` (**the binding significance** — near-independent dates; the overlapping FM t is autocorrelation-inflated and stays descriptive only); `loo_min_ic_sn > 0`; and `fm_mean_diff_harvest > 0`. **Signal** = ≥3 of the 4 thresholds pass in **each** horizon. **Stage 2** then uses the *lowest* threshold that passes in both horizons; if none, no Stage 2. Pooled hit-rate/rank-IC and the ETF panel are context, never the gate. (Newey-West/block-bootstrap over the overlapping IC series is the significance upgrade path if this ever productionizes — out of scope for a spike, where the non-overlap run is the honest floor.)
- **No observed NBBO** — the grid carries IV + greeks but no bid/ask, and no historical LEAP NBBO exists. Stage 2 cost is therefore **modeled via break-even**, never a fabricated observed spread.
- **Units decimal** — grid `call_iv`/`put_iv` are decimal (e.g. `0.177`). HV is computed decimal (`0.30` = 30%). Gap thresholds are decimal: {0.10, 0.15, 0.20, 0.25}. Report vol points = decimal × 100.
- **Greek convention** — per repo CLAUDE.md the grid stores IB-native greeks rescaled to BS convention (**vega ×100** = per 1.00 decimal-vol move; **theta ×365** = per calendar year). Stage 2 must verify this empirically against one contract before trusting the P&L decomposition (see Task 5, Step 1).
- **Module size** — target <500 lines/file; the pure library and each probe stay well under.
- **No commits to main / no PR without explicit request** — all commits land on `feat/leap-vega-alpha`. CHANGELOG entry rides this branch (Task 6).
- **Worktree** — already created at `.worktrees/leap-vega-alpha/` on `feat/leap-vega-alpha` (based on `origin/main`, includes the reusable `scripts/research/svi_fit.py`). All paths below are relative to that worktree root.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/research/leap_vega_alpha.py` (create) | Pure library: `realized_vol`, `atm_iv`, `entry_gap`, `stage1_metrics` (pooled, confounded), `cross_sectional_ic` (Fama-MacBeth, primary). No I/O. Unit-tested. |
| `tests/unit/test_leap_vega_alpha.py` (create) | Unit tests for the five pure functions. |
| `scripts/research/leap_convergence_probe.py` (create) | Stage 1 runner: DB + apex → per-(ticker,expiry,date) gap + forward ΔIV; writes traces; prints summary; makes the kill decision. |
| `scripts/research/leap_pnl_probe.py` (create, GATED) | Stage 2 runner: forward P&L decomposition + break-even spread. Only built if Stage 1 lives. |
| `docs/research/leap-vega-alpha/README.md` (create) | Stage 1 verdict (convergence gate). |
| `docs/research/leap-vega-alpha/edge-test.md` (create, GATED) | Stage 2 verdict (P&L + break-even), or a "gate failed, Stage 2 not run" stub. |
| `docs/research/leap-vega-alpha/*.csv` (create) | `gap_observations.csv`, `convergence_metrics.csv`, `pnl_metrics.csv` — durable traces. |
| `CHANGELOG.md` (modify) | `[Unreleased] Added` entry. |

---

### Task 1: Realized-vol utility

**Files:**
- Create: `scripts/research/leap_vega_alpha.py`
- Test: `tests/unit/test_leap_vega_alpha.py`

**Interfaces:**
- Produces: `realized_vol(closes: Sequence[float], window: int, ann: float = 252.0) -> float | None` — annualized sample stdev of daily log returns over the trailing `window` returns; `None` if fewer than `window + 1` closes.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_leap_vega_alpha.py
import numpy as np
import pytest
from scripts.research.leap_vega_alpha import realized_vol


def test_realized_vol_known_series():
    # 4 closes -> 3 alternating log returns; hand-computed HV.
    # rets = [ln1.02, -ln1.02, ln1.02]; sample-std * sqrt(252) = 0.363.
    hv = realized_vol([100.0, 102.0, 100.0, 102.0], window=3)
    assert hv == pytest.approx(0.363, abs=1e-3)


def test_realized_vol_flat_series_is_zero():
    assert realized_vol([50.0, 50.0, 50.0, 50.0], window=3) == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_insufficient_data_returns_none():
    assert realized_vol([100.0, 101.0], window=20) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'realized_vol'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/research/leap_vega_alpha.py
"""Pure library for the LEAP vega-alpha feasibility spike (read-only research).

realized_vol / atm_iv / entry_gap / stage1_metrics / cross_sectional_ic — no I/O,
unit-tested. Consumed by scripts/research/leap_convergence_probe.py (Stage 1) and
leap_pnl_probe.py (Stage 2). Reuses forward_from_delta from svi_fit.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def realized_vol(closes: Sequence[float], window: int, ann: float = 252.0) -> float | None:
    """Annualized sample stdev of daily log returns over the trailing `window` returns."""
    if closes is None or len(closes) < window + 1:
        return None
    tail = np.asarray(closes[-(window + 1):], dtype=float)
    rets = np.diff(np.log(tail))
    return float(np.std(rets, ddof=1) * np.sqrt(ann))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_vega_alpha.py tests/unit/test_leap_vega_alpha.py
git commit -m "feat(leap): realized-vol utility for vega-alpha spike"
```

---

### Task 2: ATM-IV extractor + entry gap

**Files:**
- Modify: `scripts/research/leap_vega_alpha.py`
- Test: `tests/unit/test_leap_vega_alpha.py`

**Interfaces:**
- Consumes: `realized_vol` (Task 1); `forward_from_delta` from `scripts.research.svi_fit`.
- Produces:
  - `atm_iv(rows: list[dict], max_delta_dist: float = 0.10) -> float | None` — IV at the money, **linearly interpolated at `call_delta == 0.5`** (consistent with the SVI `forward_from_delta` anchor — avoids strike-grid jitter on coarse LEAP chains). Falls back to the nearest-0.5-delta strike's `call_iv` only when no bracketing pair straddles 0.5, and returns `None` if that nearest delta is farther than `max_delta_dist` from 0.5. `rows` each have `strike`, `call_iv`, `call_delta`.
  - `entry_gap(hv20: float | None, hv60: float | None, atm: float | None) -> float | None` — `max(hv20, hv60) - atm`; `None` if `atm` is None or both HVs are None.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_leap_vega_alpha.py
from scripts.research.leap_vega_alpha import atm_iv, entry_gap


def test_atm_iv_interpolates_at_half_delta():
    rows = [
        {"strike": 95.0, "call_iv": 0.32, "call_delta": 0.55},
        {"strike": 105.0, "call_iv": 0.30, "call_delta": 0.45},
        {"strike": 130.0, "call_iv": 0.50, "call_delta": 0.10},
    ]
    # linear interp between (δ0.45, iv0.30) and (δ0.55, iv0.32) at δ=0.5 -> 0.31
    assert atm_iv(rows) == pytest.approx(0.31, abs=1e-6)


def test_atm_iv_rejects_far_from_half_delta():
    # no strike brackets 0.5 and the nearest (δ0.30) is >0.10 away -> None
    rows = [
        {"strike": 120.0, "call_iv": 0.40, "call_delta": 0.30},
        {"strike": 140.0, "call_iv": 0.50, "call_delta": 0.15},
    ]
    assert atm_iv(rows) is None


def test_atm_iv_none_when_no_delta():
    assert atm_iv([{"strike": 100.0, "call_iv": 0.3, "call_delta": None}]) is None


def test_entry_gap_uses_max_hv():
    # max(0.28, 0.35) - 0.20 = 0.15
    assert entry_gap(0.28, 0.35, 0.20) == pytest.approx(0.15)
    assert entry_gap(None, 0.35, 0.20) == pytest.approx(0.15)
    assert entry_gap(0.28, 0.35, None) is None
    assert entry_gap(None, None, 0.20) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -k "atm_iv or entry_gap" -v`
Expected: FAIL with `ImportError: cannot import name 'atm_iv'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/research/leap_vega_alpha.py


def atm_iv(rows: list[dict], max_delta_dist: float = 0.10) -> float | None:
    """ATM IV linearly interpolated at call_delta==0.5 (matches forward_from_delta).

    Interpolation kills the strike-grid jitter that a nearest-strike pick suffers on
    coarse LEAP chains. Falls back to the nearest-0.5-delta strike only when no pair
    brackets 0.5, and returns None if that nearest delta is > max_delta_dist away.
    """
    pts = sorted(
        (float(r["call_delta"]), float(r["call_iv"]))
        for r in rows
        if r.get("call_delta") is not None and r.get("call_iv") is not None
    )
    if not pts:
        return None
    for (d0, iv0), (d1, iv1) in zip(pts, pts[1:]):  # bracket 0.5 -> interp in delta
        if (d0 - 0.5) * (d1 - 0.5) <= 0.0 and d0 != d1:
            return iv0 + (0.5 - d0) / (d1 - d0) * (iv1 - iv0)
    d_near, iv_near = min(pts, key=lambda p: abs(p[0] - 0.5))
    return iv_near if abs(d_near - 0.5) <= max_delta_dist else None


def entry_gap(hv20: float | None, hv60: float | None, atm: float | None) -> float | None:
    """max(hv20, hv60) - atm_iv, all decimal. None if atm missing or both HVs missing."""
    if atm is None:
        return None
    hvs = [h for h in (hv20, hv60) if h is not None]
    if not hvs:
        return None
    return max(hvs) - atm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_vega_alpha.py tests/unit/test_leap_vega_alpha.py
git commit -m "feat(leap): ATM-IV extractor + entry-gap"
```

---

### Task 3: Stage-1 convergence metrics

**Files:**
- Modify: `scripts/research/leap_vega_alpha.py`
- Test: `tests/unit/test_leap_vega_alpha.py`

**Interfaces:**
- Produces: `stage1_metrics(gaps: Sequence[float], d_ivs: Sequence[float], threshold: float) -> dict` — takes aligned entry gaps and same-contract forward ΔIV (decimal). Returns
  `{"n": int, "rank_ic": float, "baseline_mean_div": float, "flagged_n": int, "flagged_mean_div": float, "hit_rate": float}` where:
  - `rank_ic` = Spearman correlation of `gaps` vs `d_ivs` (positive ⇒ wider gap predicts IV rising),
  - `baseline_mean_div` = mean ΔIV over all pairs (unconditional control),
  - flagged = subset with `gap >= threshold`,
  - `hit_rate` = fraction of flagged with `d_iv > 0`.
  NaNs where a stat is undefined (e.g. `flagged_n == 0`). **This is the confounded pooled secondary metric** — regime drift inflates `rank_ic`/`hit_rate` (see Global Constraints). Reported for context, not for the gate.
- Produces: `cross_sectional_ic(records: Sequence[dict], threshold: float) -> dict` — the **primary** Fama-MacBeth metric. `records` each have `market_date`, `gap`, `d_iv` (caller pre-filters to one horizon). Groups by `market_date`; per date computes cross-sectional Spearman(gap, d_iv) across names and the within-date differential harvest (mean `d_iv` of flagged minus that date's cross-sectional mean `d_iv`); averages across dates. Returns `{"n_dates": int, "mean_ic": float, "ic_t_stat": float, "mean_diff_harvest": float}` with `ic_t_stat = mean_ic / (std_ic / sqrt(n_dates))`. **Autocorrelation across the overlapping dates still inflates this t — the verdict doc must say so; treat |t|≥2 as necessary-not-sufficient.**

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_leap_vega_alpha.py
from scripts.research.leap_vega_alpha import stage1_metrics


def test_stage1_metrics_positive_relationship():
    # ΔIV increases monotonically with gap -> rank_ic == 1.0
    gaps = [0.05, 0.10, 0.20, 0.30]
    d_ivs = [-0.01, 0.00, 0.02, 0.05]
    m = stage1_metrics(gaps, d_ivs, threshold=0.15)
    assert m["n"] == 4
    assert m["rank_ic"] == pytest.approx(1.0)
    assert m["flagged_n"] == 2          # gaps 0.20, 0.30
    assert m["hit_rate"] == pytest.approx(1.0)   # both ΔIV > 0
    assert m["flagged_mean_div"] == pytest.approx(0.035)


def test_stage1_metrics_no_flagged():
    m = stage1_metrics([0.01, 0.02], [0.0, 0.0], threshold=0.15)
    assert m["flagged_n"] == 0
    assert np.isnan(m["hit_rate"])


def test_cross_sectional_ic_within_date():
    from scripts.research.leap_vega_alpha import cross_sectional_ic
    # Two dates; within EACH date gap-rank matches ΔIV-rank -> per-date IC=1.
    # A whole-sample positive drift would NOT change this (that's the point).
    recs = [
        {"market_date": "2026-01-05", "gap": 0.05, "d_iv": 0.00},
        {"market_date": "2026-01-05", "gap": 0.20, "d_iv": 0.03},
        {"market_date": "2026-01-05", "gap": 0.30, "d_iv": 0.05},
        {"market_date": "2026-01-06", "gap": 0.02, "d_iv": -0.01},
        {"market_date": "2026-01-06", "gap": 0.18, "d_iv": 0.02},
        {"market_date": "2026-01-06", "gap": 0.25, "d_iv": 0.04},
    ]
    m = cross_sectional_ic(recs, threshold=0.15)
    assert m["n_dates"] == 2
    assert m["mean_ic"] == pytest.approx(1.0)
    assert m["mean_diff_harvest"] > 0   # flagged names beat their same-date peers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -k stage1 -v`
Expected: FAIL with `ImportError: cannot import name 'stage1_metrics'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/research/leap_vega_alpha.py
from scipy.stats import spearmanr


def stage1_metrics(gaps, d_ivs, threshold: float) -> dict:
    """Convergence metrics: rank-IC of gap vs forward ΔIV, plus flagged-subset stats."""
    g = np.asarray(gaps, dtype=float)
    d = np.asarray(d_ivs, dtype=float)
    n = int(g.size)
    rank_ic = float(spearmanr(g, d).statistic) if n >= 2 else float("nan")
    flagged = g >= threshold
    fn = int(flagged.sum())
    return {
        "n": n,
        "rank_ic": rank_ic,
        "baseline_mean_div": float(d.mean()) if n else float("nan"),
        "flagged_n": fn,
        "flagged_mean_div": float(d[flagged].mean()) if fn else float("nan"),
        "hit_rate": float((d[flagged] > 0).mean()) if fn else float("nan"),
    }


def cross_sectional_ic(records, threshold: float) -> dict:
    """Fama-MacBeth primary metric: per-date cross-sectional IC + within-date
    differential harvest, averaged across dates. Cancels the regime-common IV move."""
    from collections import defaultdict

    by_date: dict = defaultdict(list)
    for r in records:
        by_date[r["market_date"]].append(r)
    ics, diffs = [], []
    for recs in by_date.values():
        g = np.array([x["gap"] for x in recs], dtype=float)
        d = np.array([x["d_iv"] for x in recs], dtype=float)
        if g.size >= 2 and np.std(g) > 0 and np.std(d) > 0:
            ics.append(float(spearmanr(g, d).statistic))
        flagged = g >= threshold
        if flagged.any():
            diffs.append(float(d[flagged].mean() - d.mean()))  # demeaned within date
    ic = np.array(ics, dtype=float)
    df = np.array(diffs, dtype=float)
    t = (
        float(ic.mean() / (ic.std(ddof=1) / np.sqrt(ic.size)))
        if ic.size >= 2 and ic.std(ddof=1) > 0
        else float("nan")
    )
    return {
        "n_dates": int(ic.size),
        "mean_ic": float(ic.mean()) if ic.size else float("nan"),
        "ic_t_stat": t,
        "mean_diff_harvest": float(df.mean()) if df.size else float("nan"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_vega_alpha.py tests/unit/test_leap_vega_alpha.py
git commit -m "feat(leap): Stage-1 convergence metrics (rank-IC + flagged stats)"
```

---

### Task 4: Stage-1 convergence probe (integration runner + verdict)

**Files:**
- Create: `scripts/research/leap_convergence_probe.py`
- Create: `docs/research/leap-vega-alpha/README.md`
- Create (by running): `docs/research/leap-vega-alpha/{gap_observations,convergence_metrics}.csv`

**Interfaces:**
- Consumes: everything from Tasks 1–3; `forward_from_delta` from `svi_fit`; `Settings.from_env`; apex `/bars/{ticker}`.
- Produces: `main() -> int`. Run as a module (repo root on `sys.path` for the `scripts` namespace):
  `... uv run python -m scripts.research.leap_convergence_probe`.

**Design notes (read before writing):**
- **Panel:** the LIQUID set `["SPY","QQQ","NVDA","AAPL","TSLA","MU"]` plus 4 more high-OI single names from the banked universe (query the 10 tickers with the most LEAP rows on the latest date). LEAP tenor per (ticker,date) = the expiry nearest **420 DTE** with `(expiry - market_date) >= 365`.
- **Entry dates:** all 129 banked dates that leave ≥ `h` forward grid-dates for the same contract (so ΔIV is measurable). Horizons `h ∈ {20, 40}` trading days = 20/40 grid-dates ahead for that (ticker, expiry).
- **ATM contract:** per (ticker, expiry, entry date) load grid rows, clip to `call_delta ∈ [0.05, 0.95]` (reuse the SVI delta band — kills junk deep-wing marks), pick the ATM strike via `atm_iv` and record that exact strike. Forward ΔIV = same (ticker, expiry, strike)'s `call_iv` at entry+h minus at entry.
- **HV:** fetch each ticker's daily closes once from apex `/bars/{ticker}?timeframe=1d&start=<entry_min-100d>&end=<entry_max>`; compute `realized_vol(closes_up_to_entry, 20)` and `(…, 60)` as of each entry date. apex history predates the surface window, so HV60 is available even for early entries.
- **Sanity gates that must print (fail loud, don't silently proceed):** (a) HV and IV both decimal and in a plausible band (0.05–3.0); (b) forward ΔIV distribution not degenerate (std > 0); (c) ≥ 200 aligned (entry, h) pairs or the run is under-powered — log it.
- **Kill decision:** apply the exact gate from Global Constraints ("The gate is exact, single-name, and non-overlap-binding"). One line: on the **single-name** panel a threshold passes iff `fm_ic_sn > 0 AND fm_ic_sn_nonoverlap > 0 AND loo_min_ic_sn > 0 AND fm_mean_diff_harvest > 0`; **signal** = ≥3/4 thresholds pass in **each** horizon; **Stage 2** uses the lowest threshold passing in both horizons. Pooled/ETF/hit-rate columns are printed for context only. Fail → negative README, no Stage 2.
- **Non-overlap is computed inline, not re-run:** `fm_ic_sn_nonoverlap` (single-name entries with `entry_idx % h == 0`, so no two share a forward window) is the **binding** significance number in the gate above. The overlapping single-name FM t (`fm_t_sn`) is descriptive only — autocorrelation-inflated.
- **HV data-consistency guard (codex #9):** apex `/bars` closes and the grid IV come from different vendors. Document whether apex closes are split/dividend-adjusted in the verdict, and drop any HV window containing a `|1-day log-return| > 0.35` (a likely unadjusted split artifact) — log how many entries this removes.

- [ ] **Step 1: Write the probe runner**

```python
# scripts/research/leap_convergence_probe.py
"""Stage 1 — LEAP cheap-vol convergence gate (read-only: DB + apex bars, ZERO UW/IB).

Does a wide HV-minus-LEAP-ATM-IV entry gap predict the SAME contract's IV rising
over the next 20/40 trading days? Writes traces + prints the kill decision.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

import httpx
import numpy as np
import psycopg

from scripts.research.leap_vega_alpha import (
    atm_iv,
    cross_sectional_ic,
    entry_gap,
    realized_vol,
    stage1_metrics,
)
from uw_scan.config import Settings

logger = logging.getLogger("leap_probe")
logging.basicConfig(level=logging.INFO, format="%(message)s")

LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
TARGET_DTE = 420
DTE_FLOOR = 365
HORIZONS = [20, 40]
THRESHOLDS = [0.10, 0.15, 0.20, 0.25]
DELTA_BAND = (0.05, 0.95)
# Asset-class tag for the panel split: ETF IV/HV/VRP dynamics differ structurally from
# single names, so a pooled cross-section can let asset class manufacture the IC.
ETFS = {"SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "TLT", "HYG", "GLD"}
APEX = "http://100.66.147.98:8322"
OUT = Path("docs/research/leap-vega-alpha")


def apex_closes(ticker: str, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    """Date->close from apex daily bars. Empty dict on any failure (logged)."""
    url = f"{APEX}/bars/{ticker}?timeframe=1d&start={start}&end={end}"
    try:
        r = httpx.get(url, timeout=15.0)
        r.raise_for_status()
        bars = r.json().get("bars", [])
    except Exception as exc:  # noqa: BLE001 - research probe, log and skip ticker
        logger.info("apex fail %s: %r", ticker, exc)
        return {}
    out = {}
    for b in bars:
        d = dt.date.fromisoformat(b["time"][:10])
        if b.get("close") is not None:
            out[d] = float(b["close"])
    return out


def hv_asof(closes_by_date: dict[dt.date, float], asof: dt.date, window: int) -> float | None:
    series = [c for d, c in sorted(closes_by_date.items()) if d <= asof]
    if len(series) >= window + 1:
        tail = np.asarray(series[-(window + 1):], dtype=float)
        if float(np.max(np.abs(np.diff(np.log(tail))))) > 0.35:
            return None  # likely unadjusted split in the window (codex #9 guard)
    return realized_vol(series, window)


def top_leap_tickers(cur, n: int) -> list[str]:
    cur.execute(
        "SELECT ticker, count(*) AS c FROM option_surface_grid_daily "
        "WHERE market_date=(SELECT max(market_date) FROM option_surface_grid_daily) "
        "AND (expiry-market_date) >= %s GROUP BY ticker ORDER BY c DESC LIMIT %s",
        (DTE_FLOOR, n),
    )
    return [r[0] for r in cur.fetchall()]


def leap_expiry(cur, ticker: str, mdate: dt.date) -> dt.date | None:
    cur.execute(
        "SELECT expiry FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND (expiry-market_date) >= %s "
        "ORDER BY abs((expiry-market_date) - %s) LIMIT 1",
        (ticker, mdate, DTE_FLOOR, TARGET_DTE),
    )
    row = cur.fetchone()
    return row[0] if row else None


def atm_rows(cur, ticker: str, mdate: dt.date, expiry: dt.date) -> list[dict]:
    cur.execute(
        "SELECT strike, call_iv, call_delta FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND expiry=%s ORDER BY strike",
        (ticker, mdate, expiry),
    )
    lo, hi = DELTA_BAND
    return [
        {"strike": s, "call_iv": (float(c) if c is not None else None),
         "call_delta": (float(d) if d is not None else None)}
        for s, c, d in cur.fetchall()
        if d is not None and lo <= float(d) <= hi
    ]


def iv_on(cur, ticker: str, expiry: dt.date, strike, mdate: dt.date) -> float | None:
    cur.execute(
        "SELECT call_iv FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND strike=%s AND market_date=%s",
        (ticker, expiry, strike, mdate),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    obs: list[dict] = []
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        panel = list(dict.fromkeys(LIQUID + top_leap_tickers(cur, 10)))
        logger.info("panel: %s", panel)
        cur.execute("SELECT DISTINCT market_date FROM option_surface_grid_daily ORDER BY market_date")
        all_dates = [r[0] for r in cur.fetchall()]
        dmin, dmax = all_dates[0], all_dates[-1]
        for ticker in panel:
            closes = apex_closes(ticker, dmin - dt.timedelta(days=120), dmax)
            if not closes:
                continue
            # per-ticker grid dates (index positions let us step h forward)
            cur.execute(
                "SELECT DISTINCT market_date FROM option_surface_grid_daily "
                "WHERE ticker=%s ORDER BY market_date", (ticker,))
            tdates = [r[0] for r in cur.fetchall()]
            pos = {d: i for i, d in enumerate(tdates)}
            for i, mdate in enumerate(tdates):
                expiry = leap_expiry(cur, ticker, mdate)
                if expiry is None:
                    continue
                rows = atm_rows(cur, ticker, mdate, expiry)
                atm = atm_iv(rows)                       # interpolated 50-delta -> the GAP (cheapness)
                if atm is None:
                    continue
                held = min(rows, key=lambda r: abs(r["call_delta"] - 0.5))
                if abs(held["call_delta"] - 0.5) > 0.10 or held["call_iv"] is None:
                    continue                             # coarse grid: no strike near ATM
                strike, entry_iv_fixed = held["strike"], float(held["call_iv"])
                hv20 = hv_asof(closes, mdate, 20)
                hv60 = hv_asof(closes, mdate, 60)
                gap = entry_gap(hv20, hv60, atm)
                if gap is None:
                    continue
                for h in HORIZONS:
                    j = i + h
                    if j >= len(tdates):
                        continue
                    fwd = iv_on(cur, ticker, expiry, strike, tdates[j])
                    if fwd is None:
                        continue
                    obs.append(dict(
                        ticker=ticker,
                        asset_class=("etf" if ticker in ETFS else "single_name"),
                        market_date=mdate, expiry=expiry, strike=strike,
                        dte=(expiry - mdate).days, hv20=hv20, hv60=hv60, atm_iv=atm,
                        entry_iv_fixed=entry_iv_fixed, gap=round(gap, 5), horizon=h, iv_fwd=fwd,
                        # HELD-CONTRACT mark change (tradable) on the fixed strike — NOT the
                        # interpolated-ATM convergence. As spot drifts this mixes vol repricing
                        # with moneyness migration; that's the real P&L of holding the contract.
                        d_iv=round(fwd - entry_iv_fixed, 5), entry_idx=i,
                    ))
    _write_csv(OUT / "gap_observations.csv", obs)
    _summary_and_metrics(obs)
    return 0


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.info("no rows for %s", path)
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("wrote %s (%d rows)", path, len(rows))


def _loo_min_ic(rows: list[dict], thr: float) -> float:
    """Min single-name FM mean_ic after dropping each ticker once — kills the case
    where one ticker's persistent gap/ΔIV pattern carries the whole signal."""
    tickers = sorted({o["ticker"] for o in rows})
    if len(tickers) < 3:
        return float("nan")
    vals = [
        cross_sectional_ic([o for o in rows if o["ticker"] != tk], thr)["mean_ic"]
        for tk in tickers
    ]
    vals = [v for v in vals if not np.isnan(v)]
    return float(min(vals)) if vals else float("nan")


def _summary_and_metrics(obs: list[dict]) -> None:
    metric_rows: list[dict] = []
    for h in HORIZONS:
        sub = [o for o in obs if o["horizon"] == h]
        if len(sub) < 2:
            logger.info("h=%d: under-powered (%d pairs)", h, len(sub))
            continue
        gaps = [o["gap"] for o in sub]
        d_ivs = [o["d_iv"] for o in sub]
        # sanity gates
        ivs = [o["atm_iv"] for o in sub]
        if not all(0.05 <= v <= 3.0 for v in ivs):
            logger.info("WARN h=%d: IV out of plausible band", h)
        if np.std(d_ivs) == 0:
            logger.info("WARN h=%d: degenerate ΔIV (std=0)", h)
        if len(sub) < 200:
            logger.info("WARN h=%d: only %d pairs (<200) — under-powered", h, len(sub))
        sn_all = [o for o in sub if o["asset_class"] == "single_name"]
        etf_all = [o for o in sub if o["asset_class"] == "etf"]
        for thr in THRESHOLDS:
            m = stage1_metrics(gaps, d_ivs, thr)           # confounded pooled (secondary)
            fm = cross_sectional_ic(sub, thr)              # pooled FM
            fm_sn = cross_sectional_ic(sn_all, thr)        # single-name FM = the GATED panel
            fm_etf = cross_sectional_ic(etf_all, thr)      # ETF FM (context only)
            # non-overlap on single names = the BINDING significance (near-independent dates)
            sn_nonov = [o for o in sn_all if o["entry_idx"] % h == 0]
            fm_sn_no = cross_sectional_ic(sn_nonov, thr)
            loo = _loo_min_ic(sn_all, thr)                 # drop-one-ticker robustness (min IC)
            m.update(
                horizon=h, threshold=thr,
                **{f"fm_{k}": v for k, v in fm.items()},
                fm_ic_sn=fm_sn["mean_ic"], fm_t_sn=fm_sn["ic_t_stat"],
                fm_ic_sn_nonoverlap=fm_sn_no["mean_ic"], fm_nd_sn_nonoverlap=fm_sn_no["n_dates"],
                fm_ic_etf=fm_etf["mean_ic"], loo_min_ic_sn=loo,
            )
            metric_rows.append(m)
            logger.info(
                "h=%d thr=%.2f | POOLED fm_ic=%.3f | SINGLE-NAME fm_ic=%.3f(t=%.2f) "
                "nonoverlap_ic=%.3f(nd=%d) loo_min=%.3f | ETF fm_ic=%.3f | diff_harvest=%.4f",
                h, thr, fm["mean_ic"], fm_sn["mean_ic"], fm_sn["ic_t_stat"],
                fm_sn_no["mean_ic"], fm_sn_no["n_dates"], loo, fm_etf["mean_ic"],
                fm["mean_diff_harvest"],
            )
    _write_csv(OUT / "convergence_metrics.csv", metric_rows)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe against the mini (real data)**

Run:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
```
Expected: panel printed; `wrote docs/research/leap-vega-alpha/gap_observations.csv (N rows)` with N in the thousands; a metrics block per horizon×threshold; `convergence_metrics.csv` written. Copy `.env` + `.env.local` from the main checkout into the worktree first if `Settings.from_env()` errors on a missing key.

- [ ] **Step 3: Verify the evidence critically**

Read `convergence_metrics.csv`. Confirm: (a) `fm_nd_sn_nonoverlap` ≥ 20 and pooled `n` ≥ 200 per horizon (else note under-power in the verdict); (b) IVs were in-band (no WARN); (c) ΔIV not degenerate. Then apply the exact gate on the **single-name** columns: does a threshold satisfy `fm_ic_sn > 0 AND fm_ic_sn_nonoverlap > 0 AND loo_min_ic_sn > 0 AND fm_mean_diff_harvest > 0`, and do ≥3/4 thresholds pass in **each** horizon? Pooled `hit_rate`/`rank_ic` and the ETF columns are context only — never let a regime-lifted pooled stat override a null single-name/non-overlap metric.

- [ ] **Step 4: Write the Stage-1 verdict**

Write `docs/research/leap-vega-alpha/README.md`: the falsified claim, method (panel, tenor, HV source, ATM anchor, delta band), the metrics table copied from the CSV, and the verdict (SIGNAL → proceed to Stage 2 / NO SIGNAL → stop). Lead with the single-regime caveat. Include the exact reproduce command. Mirror the tone/structure of the merged SVI `docs/research/svi-surface-fit/README.md`.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_convergence_probe.py docs/research/leap-vega-alpha/README.md \
        docs/research/leap-vega-alpha/gap_observations.csv docs/research/leap-vega-alpha/convergence_metrics.csv
git commit -m "feat(leap): Stage-1 convergence probe + verdict"
```

---

### Task 5: Stage-2 short-hold vega P&L (GATED on Stage-1 signal)

> **Gate:** Only do this task if Task 4's verdict is SIGNAL. If NO SIGNAL, skip to Task 6 and write the `edge-test.md` stub noting the gate failed and Stage 2 was intentionally not run (cite the SVI precedent: a clean negative is a valid deliverable).

**Files:**
- Create: `scripts/research/leap_pnl_probe.py`
- Create: `docs/research/leap-vega-alpha/edge-test.md`
- Create (by running): `docs/research/leap-vega-alpha/pnl_metrics.csv`

**Interfaces:**
- Consumes: `gap_observations.csv` (flagged entries) + the grid greeks (`call_vega`, `call_delta`, `call_theta`) + apex closes for ΔS.
- Produces: `main() -> int`, run as `... uv run python -m scripts.research.leap_pnl_probe`.

- [ ] **Step 1: Verify greek units empirically (before trusting P&L)**

Run this one-off check and record the result in `edge-test.md`:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
uv run python - <<'PY'
import psycopg
from uw_scan.config import Settings
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c, c.cursor() as cur:
    cur.execute("SET search_path TO uw_scan, public")
    cur.execute("SELECT ticker,expiry,strike,call_iv,call_delta,call_vega,call_theta,call_gamma "
                "FROM option_surface_grid_daily WHERE ticker='AAPL' AND (expiry-market_date)>=365 "
                "AND call_delta BETWEEN 0.45 AND 0.55 "
                "ORDER BY market_date DESC LIMIT 3")
    for r in cur.fetchall(): print(r)
PY
```
Expected: interpret vega magnitude. Under BS "vega ×100" convention a ~1yr ATM equity option's `call_vega` ≈ price move per 1.0 decimal-vol; a per-1%-vol reading is ~1/100th that. Set the P&L scale from what you observe; if the observed magnitude contradicts the CLAUDE.md note, trust the data and document the discrepancy. **Do not proceed until the unit is pinned.**

- [ ] **Step 2: Write the P&L probe**

```python
# scripts/research/leap_pnl_probe.py
"""Stage 2 — forward vega-alpha P&L on Stage-1-flagged LEAP entries (read-only).

Reads gap_observations.csv, marks each flagged entry forward h days, decomposes
gross P&L = vega·ΔIV + delta·ΔS + theta·Δt, and reports the BREAK-EVEN spread
(the entry spread in vol points that would erase the edge) — never an observed
spread, because no historical LEAP NBBO exists.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

import numpy as np
import psycopg

from scripts.research.leap_convergence_probe import apex_closes
from uw_scan.config import Settings

logger = logging.getLogger("leap_pnl")
logging.basicConfig(level=logging.INFO, format="%(message)s")

OUT = Path("docs/research/leap-vega-alpha")
# The LOWEST gap threshold that PASSED the Stage-1 gate in BOTH horizons (per the exact
# gate rule). Read it off convergence_metrics.csv — do not hardcode a guess. 0.15 is a
# placeholder to be overwritten once Stage 1 has run.
FLAG_THRESHOLD = 0.15
# $ per unit call_vega per 1.0 decimal-vol move; set from Task 5 Step 1 calibration
# (1.0 if grid vega is per-1.0-vol [BS ×100 convention]; 100.0 if per-1%-vol).
# Affects ONLY the $ vega/delta/theta attribution — NOT the verdict. The break-even
# spread is in vol points and cancels vega, so the cost verdict needs no calibration.
VEGA_SCALE = 1.0


def _greeks(cur, ticker, expiry, strike, mdate):
    cur.execute(
        "SELECT call_iv, call_delta, call_vega, call_theta FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND strike=%s AND market_date=%s",
        (ticker, expiry, strike, mdate),
    )
    r = cur.fetchone()
    if not r or any(v is None for v in r):
        return None
    return dict(iv=float(r[0]), delta=float(r[1]), vega=float(r[2]), theta=float(r[3]))


def main() -> int:
    src = OUT / "gap_observations.csv"
    if not src.exists():
        logger.info("run Stage 1 first (%s missing)", src)
        return 1
    with src.open() as f:
        flagged = [r for r in csv.DictReader(f) if float(r["gap"]) >= FLAG_THRESHOLD]
    s = Settings.from_env()
    pnl_rows: list[dict] = []
    close_cache: dict[str, dict] = {}
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        for r in flagged:
            tk, exp = r["ticker"], dt.date.fromisoformat(r["expiry"])
            strike, m0, h = r["strike"], dt.date.fromisoformat(r["market_date"]), int(r["horizon"])
            g0 = _greeks(cur, tk, exp, strike, m0)
            if g0 is None:
                continue
            cur.execute(
                "SELECT DISTINCT market_date FROM option_surface_grid_daily "
                "WHERE ticker=%s ORDER BY market_date", (tk,))
            tdates = [x[0] for x in cur.fetchall()]
            if m0 not in tdates:
                continue
            j = tdates.index(m0) + h
            if j >= len(tdates):
                continue
            m1 = tdates[j]
            g1 = _greeks(cur, tk, exp, strike, m1)
            if g1 is None:
                continue
            if tk not in close_cache:
                close_cache[tk] = apex_closes(tk, m0 - dt.timedelta(days=10), tdates[-1])
            closes = close_cache[tk]
            if m0 not in closes or m1 not in closes:
                continue
            d_iv = g1["iv"] - g0["iv"]
            d_s = closes[m1] - closes[m0]
            d_t = (m1 - m0).days / 365.0
            pnl_vega = g0["vega"] * d_iv * VEGA_SCALE   # $ attribution (units per Step 1)
            pnl_delta = g0["delta"] * d_s               # directional noise — hedged, not harvested
            pnl_theta = g0["theta"] * d_t
            gross = pnl_vega + pnl_delta + pnl_theta
            pnl_rows.append(dict(
                ticker=tk, asset_class=r.get("asset_class"),
                market_date=m0, expiry=exp, strike=strike, horizon=h,
                gap=r["gap"], d_iv=round(d_iv, 5), d_s=round(d_s, 4),
                pnl_vega=round(pnl_vega, 4), pnl_delta=round(pnl_delta, 4),
                pnl_theta=round(pnl_theta, 4), gross=round(gross, 4),
                vega=g0["vega"],
                # Vega edge in VOL POINTS (long vega -> harvest = +ΔIV). Break-even round-trip
                # spread = |harvest|; vega cancels, so this is the vega-unit-free cost verdict.
                harvest_vp=round(d_iv * 100.0, 4),
                breakeven_spread_vp=round(abs(d_iv) * 100.0, 4),
            ))
    _write(pnl_rows)
    return 0


def _write(rows: list[dict]) -> None:
    if not rows:
        logger.info("no flagged P&L rows")
        return
    with (OUT / "pnl_metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    gross = np.array([r["gross"] for r in rows])
    vega_pnl = np.array([r["pnl_vega"] for r in rows])
    logger.info("flagged=%d  mean gross $=%.3f  mean vega-P&L $=%.3f  win%%=%.1f",
                len(rows), gross.mean(), vega_pnl.mean(), 100 * (gross > 0).mean())
    harv = np.array([r["harvest_vp"] for r in rows])  # signed; the long-vega expected edge
    logger.info("mean signed vega harvest = %.2f vp | median |break-even spread| = %.2f vp",
                float(harv.mean()), float(np.median(np.abs(harv))))
    logger.info("VERDICT: harvest must clear a realistic ATM-LEAP round-trip spread of ~1-5 vp "
                "(mega-cap ~1 vp; off-the-top names 2-5 vp)")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run it against real data**

Run:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
```
Expected: `pnl_metrics.csv` written; a mean gross $, mean vega-P&L $, win %, and median break-even spread printed.

- [ ] **Step 4: Write the Stage-2 verdict**

Write `docs/research/leap-vega-alpha/edge-test.md`: the greek-unit finding (Step 1), the P&L decomposition table, and the taker verdict. The cost comparison is **mean signed vega harvest (vp) vs a realistic ATM-LEAP round-trip spread of ~1–5 vol points** (web-verified: mega-cap ATM LEAP spreads ≈ $0.10–0.50 ≈ ~1 vp; off-the-top names $1–5 ≈ 2–5 vp). Note that this headline verdict is **already derivable from Stage 1** (flagged `fm_mean_diff_harvest`×100 vs spread); Stage 2 adds the delta/theta attribution and confirms **vega, not direction, is the edge** (delta P&L is directional noise to be hedged, not harvested). **Verdict rule (codex #10):** to call it tradable the mean signed harvest must clear a **conservative 5 vp** stress; report the 1/2/5 vp sensitivity and bucket the harvest by asset class (ETF vs single-name), since spreads/liquidity differ by contract. Mirror the merged SVI `residual-edge-test.md`. Lead with the single-regime caveat.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_pnl_probe.py docs/research/leap-vega-alpha/edge-test.md \
        docs/research/leap-vega-alpha/pnl_metrics.csv
git commit -m "feat(leap): Stage-2 vega-alpha P&L + break-even verdict"
```

---

### Task 6: CHANGELOG entry + final polish

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/research/leap-vega-alpha/README.md` (cross-link to `edge-test.md` if Stage 2 ran; else note gate stopped at Stage 1)

- [ ] **Step 1: Add the `[Unreleased]` entry**

Under `## [Unreleased]` → `### Added` in `CHANGELOG.md`, add one line:
```markdown
- LEAP vega-alpha feasibility spike (`docs/research/leap-vega-alpha/`): tested radon's cheap-LEAP thesis (HV−LEAP-IV gap → long-vega alpha) on 6 months of banked surface data. Verdict: <SIGNAL / NO SIGNAL — fill from the run>. Reusable pure lib `scripts/research/leap_vega_alpha.py` + convergence/P&L probes.
```

- [ ] **Step 2: Run the full unit suite once more**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: all pass (10 tests).

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/research/leap-vega-alpha/README.md
git commit -m "docs(leap): changelog entry + verdict cross-links"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** convergence gate (Tasks 1–4), gated P&L (Task 5), verdict docs + traces (Tasks 4–6), single-regime caveat (Global Constraints + verdict steps), break-even cost model (Task 5). All design points map to a task.
- **Placeholder scan:** the only intentional fill-ins are run-output values (metrics, verdict direction, `VEGA_SCALE`/`FLAG_THRESHOLD` set from Stage-1/greek-unit findings) — these are results-from-real-runs, not design placeholders, and each is flagged at its step.
- **Type consistency:** `realized_vol`/`atm_iv`/`entry_gap`/`stage1_metrics`/`cross_sectional_ic` signatures are used identically in the probes; `atm_iv` interpolates at δ=0.5 for the *gap*, while the probe tracks the *held strike's own* IV forward for ΔIV (the two are deliberately distinct — cheapness vs tradable mark).
- **Reuse:** `forward_from_delta` available from the merged `svi_fit.py`; delta band `(0.05, 0.95)` carried over verbatim; verdict docs mirror the SVI spike structure.
- **Review-cycle hardening (2026-07-06):** primary metric is Fama-MacBeth cross-sectional IC on a single-name-only panel with a leave-one-ticker-out floor and an inline non-overlap binding-significance run; ETFs reported separately; ATM IV interpolated; held-contract ΔIV; break-even decoupled from greek units; HV split-artifact guard. Applied from Pass-1 self-review + codex tribunal.

## Reproduce (whole spike)

```bash
# Stage 1 (always):
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
# Stage 2 (only if Stage 1 shows signal):
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
uv run pytest tests/unit/test_leap_vega_alpha.py -v
```
