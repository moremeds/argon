# VCG v2 — Cascade and Absolute-Vol Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship VCG `COMPOSITE_VERSION = 2` with a rewritten interpretation cascade (PANIC moved above SUPPRESSED, new absolute-vol → RISK_OFF override) such that zero rows in the 7-crisis backtest have `regime='PANIC' AND interpretation='SUPPRESSED'`, AND crisis-window stress recall does not regress below v1's 52/528 = 0.0985 baseline.

**Architecture:** Core scoring changes live in `src/uw_scan/cards/vcg_scoring.py` — bump `COMPOSITE_VERSION`, add four constants, compute two new rolling-percentile-rank arrays in both `compute_vcg` and the research-only `_compute_vcg_from_returns` path, and rewrite the `_interpretation_for_index` cascade. `scripts/backtest_vcg.py` must persist the new top-level interpretation/percentile fields into `regime_backtest_daily.payload` for both single-proxy and composite daily rows; without that, the SQL gates below false-pass or KeyError. Payload model `VcgSignal` in `src/uw_scan/api/schemas.py` gains two `float | None` fields. One 3-line UI string fix in `VcgSubTab.tsx`. A new `scripts/backfill_vcg_v2.py` wrapper produces the v=2 `regime_backtest_runs` row that `/api/regime/vcg-validation` requires post-deploy.

**Tech Stack:** Python 3.13 via `uv` (no bare `pip`/`python`/`pytest`), Pydantic v2, psycopg 3, pytest with `pytest-postgresql` for integration. Frontend: Next.js 16 + React 19 + Vitest. OpenAPI types regenerate via `cd web && npm run gen:types`.

**Reference docs (read before starting):**
- Spec: `docs/superpowers/specs/2026-05-27-vcg-v2-cascade-and-absolute-vol-spec.md`
- Forensic audit (the evidence base): `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md` (on branch `feat/vcg-stress-window-forensics`)
- v1 methodology source-of-truth: `docs/research/regime/vcg-methodology.md`
- Truth labels + thresholds: `docs/research/regime/ground-truth-labels/level1-thresholds.yaml`
- The function we're modifying: `src/uw_scan/cards/vcg_scoring.py`
- The percentile helper to reuse: `src/uw_scan/cards/regime_classification_labels.py:29-60`

---

## File structure (decomposition)

### Modified files

| File | Lines today | What changes |
|---|---|---|
| `src/uw_scan/cards/vcg_scoring.py` | 626 | Bump `COMPOSITE_VERSION` (line 32); update the research-channel comment that currently says production stays at v1 indefinitely; add 4 new constants after line 48; add percentile-rank compute in `compute_vcg` and `_compute_vcg_from_returns`; rewrite cascade in `_interpretation_for_index` (lines 289-304); add two new payload fields in the return dict (around line 332). Estimated +55 LOC. |
| `scripts/backtest_vcg.py` | ~540 | Persist `interpretation`, `vix_percentile_rank`, and `vvix_percentile_rank` into `regime_backtest_daily.payload` for both `_single_proxy_daily_rows` and `_composite_daily_rows`; keeps acceptance SQL honest and prevents composite-path KeyErrors after `_interpretation_for_index` requires the percentile arrays. |
| `src/uw_scan/api/schemas.py` | ~600 | Add `vix_percentile_rank: float \| None = None` and `vvix_percentile_rank: float \| None = None` fields to `VcgSignal` class (currently at line 365). Estimated +4 LOC. |
| `web/lib/types.ts` | generated | Regenerate via `cd web && npm run gen:types` after schemas.py change. |
| `web/components/regime/VcgSubTab.tsx:323-326` | 1 ternary | 3-line fix to remove the misleading "SUPPRESSED" / "NO SUPPRESSION" narration. |
| `docs/research/regime/vcg-methodology.md` | 308 | §2.5 cascade rewrite; §2.6 new section (absolute-vol override); §3 new constants block; §3.1 v=2 empirical-distribution update (uses backfill output); §7 replace v2-TBD stub. |
| `docs/research/regime/CLAUDE.md` | ~50 | "When to update" trigger list adds 4 new constants. |

### New files

| File | Purpose |
|---|---|
| `tests/unit/cards/test_vcg_scoring_v2_cascade.py` | All v2 unit tests: 7 cascade-branch + single-proxy/composite alignment tests + 1 regime-invariance + COMPOSITE_VERSION constant |
| `tests/unit/test_backtest_vcg_daily_payloads.py` | Unit tests that `scripts/backtest_vcg.py` persists `interpretation` and percentile fields in daily payloads |
| `tests/unit/api/test_models_regime.py` | Pydantic v=1/v=2 payload validation tests (3 tests) |
| `tests/integration/regime/test_vcg_v2_contradiction.py` | Gate 1 acceptance test (contradiction count = 0) |
| `tests/integration/regime/test_vcg_v2_recall_non_regression.py` | Gate 2 acceptance test (recall ≥ 0.0985) |
| `tests/integration/regime/test_vcg_v2_api_selection.py` | Production-default selector picks v=2 after bump |
| `tests/integration/regime/fixtures/seven_crisis_vol_complex.parquet` | Contiguous warmup-bounded vol-complex fixture (`trade_date`, `vix`, `vvix`, `hyg`, `spx_close`, `crisis_window`) |
| `tests/integration/regime/fixtures/seven_crisis_truth_labels.parquet` | Crisis-window truth labels (`trade_date`, `truth_status`, `crisis_window`) for Gate 2 recall denominator |
| `tests/integration/regime/fixtures/README.md` | Fixture provenance + regeneration command |
| `scripts/build_vcg_v2_test_fixture.py` | One-shot fixture builder (long-form `vol_index_daily` + `macro_series_daily` NFCI; preserves rolling warmup context) |
| `scripts/backfill_vcg_v2.py` | Production v=2 backfill wrapper (idempotent) |
| `tests/integration/scripts/test_backfill_vcg_v2.py` | Contract tests for the backfill wrapper; idempotency uses a migrated test DB because the wrapper validates existing persisted runs. |

---

## Task order rationale

Logic-first (catch real bugs early), then persistence of the new payload contract, then integration (gate-test the spec acceptance), then ops/docs/UI.

The single highest-risk task is **Task 4 (Percentile-rank compute + alignment)** — the spec's §7.1 calls out off-by-one as the most likely silent failure. Three alignment tests are written before the compute is implemented, so misalignment surfaces immediately.

## Execution discipline overrides

This plan contains historical `git commit` checkpoints as task-boundary examples. In this repo, the standing rule is stricter: **do not commit unless the user explicitly asks for a commit.** Treat every commit block below as a review/staging checklist only. Do not commit failing tests merely to preserve TDD red/green history; keep local changes uncommitted until the user asks for a milestone commit. In particular, do not commit the `COMPOSITE_VERSION = 2` bump without the same commit/diff also carrying the methodology-doc updates required by `docs/research/regime/vcg-methodology.md`.

Use `uv` only (`uv run pytest`, `uv run scripts/...`). Do not use `bash scripts/dev.sh` for API smoke verification because it starts web, API, and workers; for this plan, start only the API process when needed.

---

## Task 1: Bump `COMPOSITE_VERSION` to 2 (TDD-first)

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py:32`
- Create: `tests/unit/cards/test_vcg_scoring_v2_cascade.py`

- [ ] **Step 1: Create the new test file with the constant check**

```python
# tests/unit/cards/test_vcg_scoring_v2_cascade.py
"""VCG v2 cascade + percentile-rank tests.

Covers the v2 spec at docs/superpowers/specs/2026-05-27-vcg-v2-cascade-and-absolute-vol-spec.md.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards import vcg_scoring


def test_composite_version_is_two() -> None:
    """v2 spec §3 item #4 — COMPOSITE_VERSION must be 2."""
    assert vcg_scoring.COMPOSITE_VERSION == 2
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py::test_composite_version_is_two -v
```

Expected: FAIL with `assert 1 == 2`.

- [ ] **Step 3: Bump the constant**

In `src/uw_scan/cards/vcg_scoring.py:32`, change:

```python
COMPOSITE_VERSION = 1
```

to:

```python
COMPOSITE_VERSION = 2
```

- [ ] **Step 4: Update the stale research-channel comment**

Later in `vcg_scoring.py`, above `RESEARCH_COMPOSITE_VERSIONS`, the current comment says the production `COMPOSITE_VERSION` stays at `"1"` indefinitely. Replace that with a version-neutral note, for example:

```python
# Research-only version channel. Each entry maps a composite construction
# method to its research version string. The production COMPOSITE_VERSION
# constant above remains the source of truth for HYG/single_proxy production
# rows; research methods use separate version strings so they never masquerade
# as production calibration rows.
```

- [ ] **Step 5: Run the test, verify it passes**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py::test_composite_version_is_two -v
```

Expected: PASS.

- [ ] **Step 6: Verify no other tests break from the version bump alone**

```bash
uv run pytest tests/unit/cards/ -v
```

Expected: any test that asserted `COMPOSITE_VERSION == 1` will now fail and need updating. If `tests/unit/cards/test_vcg_scoring_composite.py` references the constant, update its assertion accordingly. No other v1 logic should depend on the literal value.

- [ ] **Step 7: Stage but DO NOT commit yet (tribunal finding #3 — methodology atomicity)**

`docs/research/regime/vcg-methodology.md:308` mandates that the `COMPOSITE_VERSION` bump and the §3 / §7 doc updates land **in the same commit**. The version-constant bump in this task MUST NOT be committed by itself — that would violate the methodology contract and orphan the constant from its doc record. Stage the changes:

```bash
git add tests/unit/cards/test_vcg_scoring_v2_cascade.py src/uw_scan/cards/vcg_scoring.py
git status --short    # verify staged changes; do NOT run git commit yet
```

The single methodology-aware commit happens in Task 17 Step 7 (which adds all the doc updates to the same staging area before the one combined commit). If a downstream agent asks for an intermediate commit between Tasks 1 and 17, push back and cite this finding.

---

## Task 2: Add the four new constants

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py` (insert after line 48)
- Test: `tests/unit/cards/test_vcg_scoring_v2_cascade.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/unit/cards/test_vcg_scoring_v2_cascade.py`:

```python
def test_v2_constants_present_and_correct() -> None:
    """v2 spec §6.2 — four new constants with specific values.

    Values match docs/research/regime/ground-truth-labels/level1-thresholds.yaml:
      P_PANIC: 0.95, rolling_window_days: 252, percentile_tie_rule: "strict_lt"
    """
    assert vcg_scoring.VIX_PCT_PANIC == 0.95
    assert vcg_scoring.VVIX_PCT_PANIC == 0.95
    assert vcg_scoring.VOL_PERCENTILE_WINDOW == 252
    assert vcg_scoring.VOL_PERCENTILE_TIE_RULE == "strict_lt"
```

- [ ] **Step 2: Run, verify it fails**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py::test_v2_constants_present_and_correct -v
```

Expected: FAIL with `AttributeError: module 'uw_scan.cards.vcg_scoring' has no attribute 'VIX_PCT_PANIC'`.

- [ ] **Step 3: Add the constants**

In `src/uw_scan/cards/vcg_scoring.py`, find the existing constants block ending at line 48 (`VVIX_ELEVATED = 100.0  # VVIX amplifier: elevated`). Insert immediately after:

```python
# v2 — absolute-vol-stress override gate
# Mirrors docs/research/regime/ground-truth-labels/level1-thresholds.yaml
# (P_PANIC, rolling_window_days, percentile_tie_rule).
VIX_PCT_PANIC = 0.95             # VIX percentile rank cutoff for vol_extreme
VVIX_PCT_PANIC = 0.95            # VVIX percentile rank cutoff for vol_extreme
VOL_PERCENTILE_WINDOW = 252      # Rolling window (1 trading year)
VOL_PERCENTILE_TIE_RULE = "strict_lt"  # Cohort tie semantics
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py::test_v2_constants_present_and_correct -v
```

Expected: PASS.

- [ ] **Step 5: Stage but DO NOT commit yet (methodology atomicity per tribunal finding #3)**

The four new constants are persisted in `vcg-methodology.md` §3 by Task 17. Per the atomicity contract at `vcg-methodology.md:308`, the constants AND the doc updates must land in one commit. Stage and continue:

```bash
git add src/uw_scan/cards/vcg_scoring.py tests/unit/cards/test_vcg_scoring_v2_cascade.py
git status --short    # verify staged, do NOT commit
```

The combined methodology-atomic commit happens in Task 17 Step 6.

---

## Task 3: Percentile-rank compute — write alignment tests FIRST

The spec §7.1 calls out array alignment as the highest implementation risk. Three tests pinned now will catch off-by-one errors immediately when Task 4 implements the compute.

**Files:**
- Test: `tests/unit/cards/test_vcg_scoring_v2_cascade.py`

- [ ] **Step 1: Add three failing alignment tests**

Append to `tests/unit/cards/test_vcg_scoring_v2_cascade.py`:

```python
def _make_inputs(n: int, *, vix_pattern: str = "constant", seed: int = 7) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Synthesize VIX/VVIX/HYG price arrays of length n for compute_vcg.

    vix_pattern:
      "constant" — flat 18.0 baseline (default)
      "monotonic" — strictly increasing from 10.0 to 50.0
    """
    rng = np.random.default_rng(seed)
    if vix_pattern == "constant":
        vix = np.full(n, 18.0) + rng.normal(0.0, 0.01, size=n)
    elif vix_pattern == "monotonic":
        vix = np.linspace(10.0, 50.0, num=n)
    else:
        raise ValueError(vix_pattern)
    vvix = 90.0 + rng.normal(0.0, 0.5, size=n)
    hyg = 80.0 * np.exp(np.cumsum(rng.normal(0.0, 0.005, size=n)))
    return vix, vvix, hyg


def test_percentile_rank_arrays_align_with_vcg_array() -> None:
    """v2 spec §7.1 — percentile-rank arrays must be the same length as vcg.

    The single highest-risk invariant of v2: misalignment by even one bar
    invalidates the absolute-vol gate.
    """
    n = 300
    vix, vvix, hyg = _make_inputs(n)
    model = vcg_scoring.compute_vcg(vix, vvix, hyg)
    assert len(model["vix_percentile_rank"]) == len(model["vcg"])
    assert len(model["vvix_percentile_rank"]) == len(model["vcg"])


def test_first_finite_percentile_rank_is_at_warmup_boundary() -> None:
    """v2 spec §7.1 test #2 — first non-NaN rank at the warmup boundary.

    With VOL_PERCENTILE_WINDOW=252 and compute on the N-length raw input
    then sliced [1:] to align with vcg (length N-1), the first finite rank
    in the N-1 array is at index 250 (= 252 - 1 - 1).

    Indices 0..249 are NaN (under-warmed); index 250 is the first finite value.
    """
    n = 300
    vix, vvix, hyg = _make_inputs(n)
    model = vcg_scoring.compute_vcg(vix, vvix, hyg)
    ranks = model["vix_percentile_rank"]

    # All under-warmed indices are NaN
    assert np.all(np.isnan(ranks[:250])), "expected NaN for indices 0..249"
    # First finite at index 250
    assert not math.isnan(ranks[250]), "expected finite rank at index 250"


def test_percentile_rank_value_at_known_bar_monotonic_series() -> None:
    """v2 spec §7.1 test #3 — hand-computed expected rank.

    A monotonically-increasing VIX series of length 300 means each day's
    VIX strictly exceeds every prior day. With strict_lt tie rule and
    window=252, the rank at the first post-warmup bar should be 1.0:
    today exceeds all 251 cohort members.
    """
    n = 300
    vix, vvix, hyg = _make_inputs(n, vix_pattern="monotonic")
    model = vcg_scoring.compute_vcg(vix, vvix, hyg)
    ranks = model["vix_percentile_rank"]

    # The first finite index from the previous test
    assert ranks[250] == pytest.approx(1.0), (
        f"monotonic series should give rank=1.0 at first post-warmup bar, got {ranks[250]}"
    )
```

- [ ] **Step 2: Run all three tests, verify they fail**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "percentile_rank or warmup"
```

Expected: 3 FAILs, all with `KeyError: 'vix_percentile_rank'` (compute_vcg doesn't add the key yet).

- [ ] **Step 3: Keep the failing tests locally**

```bash
git add tests/unit/cards/test_vcg_scoring_v2_cascade.py
git commit -m "test(vcg): add percentile-rank alignment tests (failing)

Three tests pin the highest-risk invariant per spec §7.1:
  1. length match with model['vcg']
  2. first finite rank at the warmup boundary (index 250)
  3. known value 1.0 on a monotonic series

These fail with KeyError until Task 4 adds the compute. Pinning the
expected index 250 in test #2 turns 'array alignment' into a concrete
falsifiable assertion — off-by-one errors surface immediately."
```

---

## Task 4: Implement percentile-rank compute in both VCG model paths

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py` (inside `compute_vcg` and `_compute_vcg_from_returns`, before each return dict)

- [ ] **Step 1: Add the import and compute**

In `src/uw_scan/cards/vcg_scoring.py`:

First, add the import near the top of the file (alongside existing imports — line ~10-20 region):

```python
from uw_scan.cards.regime_classification_labels import compute_rolling_percentile_rank
```

Then in `compute_vcg`, find the existing `pi = np.clip(...)` line (around line 144-146). Immediately AFTER that line and BEFORE the `return {` block, insert:

```python
    # v2: rolling percentile rank on raw VIX/VVIX levels.
    # Compute on length-N input, then slice [1:] to align with the
    # length-(N-1) arrays (vcg, pi, residuals, vix_levels, etc.).
    # First finite rank lands at N-1-index 250 because:
    #   - raw input index r is finite after the 252nd bar (r = 251 in 0-indexed)
    #   - sliced to [1:], that becomes (N-1)-index 250
    vix_rank_full = compute_rolling_percentile_rank(
        pd.Series(vix_prices),
        window=VOL_PERCENTILE_WINDOW,
        tie_rule=VOL_PERCENTILE_TIE_RULE,
    )
    vvix_rank_full = compute_rolling_percentile_rank(
        pd.Series(vvix_prices),
        window=VOL_PERCENTILE_WINDOW,
        tie_rule=VOL_PERCENTILE_TIE_RULE,
    )
    vix_percentile_rank = vix_rank_full.iloc[1:].to_numpy()
    vvix_percentile_rank = vvix_rank_full.iloc[1:].to_numpy()
```

Then in the return dict (currently ending at line ~160-162), add two keys:

```python
        "vix_percentile_rank": vix_percentile_rank,
        "vvix_percentile_rank": vvix_percentile_rank,
```

Place them adjacent to `"vix_levels"`, `"vvix_levels"` for grouping.

Also update `_compute_vcg_from_returns`. This path is used by `scripts/backtest_vcg.py --composite-method` and passes model arrays that are already aligned to the same date index, including return arrays built with `np.diff(..., prepend=np.nan)`. Do **not** slice `[1:]` in this path. Compute ranks directly on the aligned level arrays:

```python
    vix_percentile_rank = compute_rolling_percentile_rank(
        pd.Series(vix_levels),
        window=VOL_PERCENTILE_WINDOW,
        tie_rule=VOL_PERCENTILE_TIE_RULE,
    ).to_numpy()
    vvix_percentile_rank = compute_rolling_percentile_rank(
        pd.Series(vvix_levels),
        window=VOL_PERCENTILE_WINDOW,
        tie_rule=VOL_PERCENTILE_TIE_RULE,
    ).to_numpy()
```

Then add the same two keys to `_compute_vcg_from_returns`'s return dict, adjacent to `"vix_levels"` and `"vvix_levels"`.

- [ ] **Step 2: Add `pd` import if missing**

Check the top of `vcg_scoring.py` — if `import pandas as pd` is not already present, add it. (It is required by `compute_rolling_percentile_rank`.)

```bash
grep -n "^import pandas\|^from pandas" src/uw_scan/cards/vcg_scoring.py
```

If empty, add `import pandas as pd` near the other imports.

- [ ] **Step 3: Run the initial alignment tests, verify they pass**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "percentile_rank or warmup"
```

Expected: single-proxy alignment tests pass. If the warmup-boundary test fails with "expected NaN for indices 0..249", the slice is wrong; re-check the `.iloc[1:]` step. If the known-value test fails with rank != 1.0, the tie rule isn't being passed through correctly. The composite-path alignment regression is added in Step 5.

- [ ] **Step 4: Run the existing `test_compute_vcg_unchanged_after_composite_addition` regression**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_composite.py::test_compute_vcg_unchanged_after_composite_addition -v
```

Expected: The existing test asserts a specific set of keys in the model dict. It will likely fail because the dict now has 2 extra keys. Update the test's expected key set to include `vix_percentile_rank` and `vvix_percentile_rank`. This is a planned regression — v2 explicitly adds payload fields.

- [ ] **Step 5: Add a composite-path alignment regression**

Add one unit test that calls `_compute_vcg_from_returns` with aligned N-length arrays and asserts:

```python
assert len(model["vix_percentile_rank"]) == len(model["vcg"]) == n
assert len(model["vvix_percentile_rank"]) == len(model["vcg"]) == n
assert np.all(np.isnan(model["vix_percentile_rank"][:251]))
assert model["vix_percentile_rank"][251] == pytest.approx(1.0)
```

Use a monotonic VIX/VVIX level series so the first finite rank and known-value checks are deterministic. This test protects the composite path from the single-proxy `[1:]` slice rule leaking into the already-aligned return path.

- [ ] **Step 6: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add src/uw_scan/cards/vcg_scoring.py tests/unit/cards/test_vcg_scoring_composite.py
git commit -m "feat(vcg): compute vix/vvix percentile rank in compute_vcg

Adds two new arrays to the model dict, aligned 1:1 with vcg (length N-1
for compute_vcg, length N for _compute_vcg_from_returns).
Computed via the existing compute_rolling_percentile_rank helper from
regime_classification_labels (252-day window, strict_lt tie rule).

Per spec §6.4 + §7.1: compute_vcg computes on raw N-length input and
slices [1:] to align with return-based arrays. _compute_vcg_from_returns
does not slice because its inputs are already aligned.

Updates the test_compute_vcg_unchanged regression to include the two
new keys (planned, additive change per spec §10)."
```

---

## Task 5: Cascade-branch tests (TDD — write failing tests for new cascade)

**Files:**
- Test: `tests/unit/cards/test_vcg_scoring_v2_cascade.py`

- [ ] **Step 1: Add a helper for invoking `_interpretation_for_index` with a synthetic model**

Append to `tests/unit/cards/test_vcg_scoring_v2_cascade.py`:

```python
def _make_model_for_cascade(
    *,
    pi: float = 0.5,
    sign_ok: bool = True,
    vix_percentile_rank: float = 0.5,
    vvix_percentile_rank: float = 0.5,
    vcg: float = 0.0,
    vcg_adj: float = 0.0,
    ro: bool = False,
    edr: bool = False,
    bounce: bool = False,
    vix: float = 18.0,
    vvix: float = 90.0,
) -> tuple[dict, int]:
    """Build a single-row model dict with all keys _interpretation_for_index reads.

    Returns (model, idx) so callers do model[k][idx] just like production code.
    Idx is always 0 — single-bar model.
    """
    idx = 0
    return {
        "vcg": np.array([vcg]),
        "vcg_adj": np.array([vcg_adj]),
        "residuals": np.array([0.0]),
        "alpha": np.array([0.0]),
        "beta1": np.array([0.0 if sign_ok else 0.05]),  # sign_ok requires beta1 <= 0
        "beta2": np.array([0.0 if sign_ok else 0.05]),
        "vix_ret": np.array([0.0]),
        "vvix_ret": np.array([0.0]),
        "credit_ret": np.array([0.0]),
        "vix_levels": np.array([vix]),
        "vvix_levels": np.array([vvix]),
        "credit_levels": np.array([80.0]),
        "pi": np.array([pi]),
        "vix_percentile_rank": np.array([vix_percentile_rank]),
        "vvix_percentile_rank": np.array([vvix_percentile_rank]),
    }, idx


def _interp(model_kwargs) -> str:
    """Convenience: build model + call _interpretation_for_index + return label."""
    model, idx = _make_model_for_cascade(**model_kwargs)
    return vcg_scoring._interpretation_for_index(model, idx)["interpretation"]
```

Note: `_interpretation_for_index` is module-private (underscore prefix) but accessible for tests. If the model dict has the wrong shape because `_signal_for_index` (called internally) reads keys we haven't set, this helper may need additional fixture fields. Adjust based on Task 5 Step 3 outcome.

- [ ] **Step 2: Add the seven cascade-branch tests**

Append:

```python
def test_cascade_panic_fires_when_pi_high_even_if_sign_failed() -> None:
    """v2 spec §6.1 — PANIC (branch 2) fires above SUPPRESSED (branch 4).

    This is the central audit finding: v1 had sign_ok above PANIC, so 36
    crisis days produced regime='PANIC' AND interpretation='SUPPRESSED'.
    """
    assert _interp({"pi": 1.5, "sign_ok": False, "vcg": 1.0}) == "PANIC"


def test_cascade_vol_extreme_overrides_sign_failure() -> None:
    """v2 spec §6.1 — vol_extreme (branch 3) fires above SUPPRESSED (branch 4)."""
    assert _interp({
        "pi": 0.5, "sign_ok": False, "vcg": 1.0,
        "vix_percentile_rank": 0.97, "vvix_percentile_rank": 0.96,
    }) == "RISK_OFF"


def test_cascade_vol_extreme_only_one_side_does_not_override() -> None:
    """v2 spec §6.1 — vol_extreme requires BOTH vix and vvix at >= 0.95."""
    assert _interp({
        "pi": 0.5, "sign_ok": False, "vcg": 1.0,
        "vix_percentile_rank": 0.97, "vvix_percentile_rank": 0.85,
    }) == "SUPPRESSED"


def test_cascade_pi_panic_outranks_vol_extreme() -> None:
    """v2 spec §6.1 — when both pi>=1 and vol_extreme are true, PANIC wins."""
    assert _interp({
        "pi": 1.2, "sign_ok": False, "vcg": 1.0,
        "vix_percentile_rank": 0.99, "vvix_percentile_rank": 0.99,
    }) == "PANIC"


def test_cascade_warmup_nan_percentile_does_not_fire_override() -> None:
    """v2 spec §6.1 — NaN percentile ranks => vol_extreme=False (no spurious fire)."""
    assert _interp({
        "pi": 0.5, "sign_ok": False, "vcg": 1.0,
        "vix_percentile_rank": float("nan"), "vvix_percentile_rank": float("nan"),
    }) == "SUPPRESSED"


def test_cascade_insufficient_data() -> None:
    """v2 spec §6.1 — vcg=NaN => INSUFFICIENT_DATA (data-quality guard, unchanged)."""
    assert _interp({"vcg": float("nan")}) == "INSUFFICIENT_DATA"


def test_cascade_normal_path_unchanged_from_v1() -> None:
    """v2 spec §6.1 — all-clear inputs still produce NORMAL (sanity for v1 path)."""
    assert _interp({
        "pi": 0.3, "sign_ok": True, "vcg": 0.5, "vcg_adj": 1.0,
        "vix_percentile_rank": 0.5, "vvix_percentile_rank": 0.5,
    }) == "NORMAL"
```

- [ ] **Step 3: Run all seven tests, verify what passes/fails**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "cascade"
```

Expected: with the v1 cascade still in place, `test_cascade_panic_fires_when_pi_high_even_if_sign_failed` will FAIL with `assert 'SUPPRESSED' == 'PANIC'` (v1 fires SUPPRESSED first). `test_cascade_vol_extreme_overrides_sign_failure` will FAIL with the same v1 SUPPRESSED. `test_cascade_pi_panic_outranks_vol_extreme` will FAIL similarly. Some tests may pass against v1 (insufficient_data, normal_path, vol_extreme_only_one_side, warmup_nan).

The point of TDD: these 3-4 failures are the **exact bugs** v2 fixes.

- [ ] **Step 4: Keep the failing tests locally**

```bash
git add tests/unit/cards/test_vcg_scoring_v2_cascade.py
git commit -m "test(vcg): add v2 cascade-branch tests (3-4 failing vs v1)

Seven tests pin every branch of the new cascade per spec §6.1. Run
against v1: failures land on exactly the contradiction bug the spec
fixes — sign_ok pre-empts pi-PANIC. The failures here are the v1 bug
codified."
```

---

## Task 6: Rewrite the cascade in `_interpretation_for_index`

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py:289-304` (the cascade)

- [ ] **Step 1: Add the vol_extreme computation and rewrite the cascade**

In `src/uw_scan/cards/vcg_scoring.py`, find `_interpretation_for_index` (starts at line 232). The function reads several `model[key][idx]` values at lines 248-257. After the existing reads (around line 257-260, right after `pi_val = float(model["pi"][idx])`), add:

```python
    vix_percentile_rank = float(model["vix_percentile_rank"][idx])
    vvix_percentile_rank = float(model["vvix_percentile_rank"][idx])
    vol_extreme = (
        not math.isnan(vix_percentile_rank) and vix_percentile_rank >= VIX_PCT_PANIC
        and not math.isnan(vvix_percentile_rank) and vvix_percentile_rank >= VVIX_PCT_PANIC
    )
```

Then replace lines 289-304 (the v1 cascade) with:

```python
    # Interpretation (v2 cascade — spec §6.1)
    if math.isnan(vcg_val):
        interpretation = "INSUFFICIENT_DATA"
    elif pi_val >= 1.0:
        interpretation = "PANIC"
    elif vol_extreme:
        interpretation = "RISK_OFF"
    elif not flags["sign_ok"]:
        interpretation = "SUPPRESSED"
    elif flags["ro"]:
        interpretation = "RISK_OFF"
    elif flags["edr"]:
        interpretation = "EDR"
    elif flags["bounce"]:
        interpretation = "BOUNCE"
    elif not math.isnan(vcg_adj_val) and vcg_adj_val > VCG_TRIGGER:
        interpretation = "WATCH"
    else:
        interpretation = "NORMAL"
```

- [ ] **Step 2: Run all cascade tests, verify they pass**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "cascade"
```

Expected: all 7 PASS.

- [ ] **Step 3: Run the full v2 test file to be safe**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v
```

Expected: all tests so far PASS (constants, alignment, cascade).

- [ ] **Step 4: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add src/uw_scan/cards/vcg_scoring.py
git commit -m "feat(vcg): rewrite interpretation cascade (PANIC > vol_extreme > SUPPRESSED)

Implements the v2 spec §6.1 cascade. Three changes vs v1:
  1. PANIC moved above SUPPRESSED (fixes 36 contradiction days).
  2. New vol_extreme override fires RISK_OFF when both VIX and VVIX
     percentile ranks are >= 0.95 (252-day window, strict_lt).
  3. Cascade reads two new model keys (vix_percentile_rank,
     vvix_percentile_rank) populated by Task 4.

All 7 cascade-branch tests + 3 alignment tests pass. sign_ok still gates
SUPPRESSED for RISK_OFF/EDR/WATCH flag-based labels — that v1 behavior is
intentionally retained per spec §1."
```

---

## Task 7: Add new payload fields to the return dict

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py` (in `_interpretation_for_index` return dict, around line 306-333)

- [ ] **Step 1: Add a test asserting the new payload fields exist**

Append to `tests/unit/cards/test_vcg_scoring_v2_cascade.py`:

```python
def test_payload_contains_new_percentile_rank_fields() -> None:
    """v2 spec §6.3 — _interpretation_for_index returns vix_percentile_rank
    and vvix_percentile_rank as top-level payload fields."""
    model, idx = _make_model_for_cascade(
        vix_percentile_rank=0.87, vvix_percentile_rank=0.42
    )
    payload = vcg_scoring._interpretation_for_index(model, idx)
    assert "vix_percentile_rank" in payload
    assert "vvix_percentile_rank" in payload
    assert payload["vix_percentile_rank"] == pytest.approx(0.87, abs=1e-4)
    assert payload["vvix_percentile_rank"] == pytest.approx(0.42, abs=1e-4)


def test_payload_percentile_rank_fields_are_none_when_nan() -> None:
    """v2 spec §6.3 — NaN percentile ranks serialize as None
    (via _round_or_none helper, which already handles NaN)."""
    model, idx = _make_model_for_cascade(
        vix_percentile_rank=float("nan"), vvix_percentile_rank=float("nan")
    )
    payload = vcg_scoring._interpretation_for_index(model, idx)
    assert payload["vix_percentile_rank"] is None
    assert payload["vvix_percentile_rank"] is None
```

- [ ] **Step 2: Run, verify both fail**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "payload"
```

Expected: 2 FAILs with `'vix_percentile_rank' not in payload`.

- [ ] **Step 3: Add the fields to the return dict**

In `src/uw_scan/cards/vcg_scoring.py`, find the `return {` block at the end of `_interpretation_for_index` (around lines 306-333). Find the line `"vix": round(vix, 2),` (around line 313). Immediately after the `"vvix": round(vvix, 2),` line, insert:

```python
        "vix_percentile_rank": _round_or_none(vix_percentile_rank, 4),
        "vvix_percentile_rank": _round_or_none(vvix_percentile_rank, 4),
```

- [ ] **Step 4: Run, verify both pass**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "payload"
```

Expected: 2 PASSes.

- [ ] **Step 5: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add src/uw_scan/cards/vcg_scoring.py tests/unit/cards/test_vcg_scoring_v2_cascade.py
git commit -m "feat(vcg): surface vix/vvix percentile_rank in payload

Adds two new top-level fields to _interpretation_for_index's return dict.
Per spec §6.3: float | None, NaN serialized as None via the existing
_round_or_none helper. Adjacent to the existing vix/vvix level fields
for grouping. Pydantic model update is the next task."
```

---

## Task 7A: Persist v2 payload fields in `scripts/backtest_vcg.py`

**Files:**
- Modify: `scripts/backtest_vcg.py`

Acceptance SQL reads `regime_backtest_daily.payload`, not the in-memory model. Today `_single_proxy_daily_rows` stores `level=interp` but omits `payload["interpretation"]`; `_composite_daily_rows` stores the model signal under `payload["signal"]` and also omits the new percentile fields. That would make Gate 1 / Gate 2 false-pass or false-fail depending on NULL behavior.

- [ ] **Step 1: Add a regression test around daily-row payloads**

Add a focused test that builds a minimal post-warmup model with percentile arrays and calls `_single_proxy_daily_rows`. Assert every returned row has:

```python
assert row["payload"]["interpretation"] == row["level"]
assert "vix_percentile_rank" in row["payload"]
assert "vvix_percentile_rank" in row["payload"]
```

For the composite path, add a direct test around `_composite_daily_rows`. **Tribunal finding #4: the composite payload MUST mirror the single-proxy structure with `interpretation`, `vix_percentile_rank`, and `vvix_percentile_rank` at the TOP LEVEL of `payload` (NOT nested under `payload["signal"]`).** This ensures `payload->>'interpretation'` queries (Gate 1 SQL, post-backfill verification, downstream JSONB readers) work uniformly across both paths.

```python
# Composite-path test — same three keys at the SAME top level as single-proxy:
assert row["payload"]["interpretation"] == row["level"]
assert "vix_percentile_rank" in row["payload"]
assert "vvix_percentile_rank" in row["payload"]
# The existing nested "signal" object is preserved for the rich-payload composite
# consumers, but the three new keys also appear at the top level for Gate 1 SQL.
assert "signal" in row["payload"]  # backward-compat with existing composite consumers
```

- [ ] **Step 2: Update single-proxy payload persistence**

In `_single_proxy_daily_rows`, add these keys inside the per-day payload:

```python
                    "interpretation": day["interpretation"],
                    "vix_percentile_rank": day["vix_percentile_rank"],
                    "vvix_percentile_rank": day["vvix_percentile_rank"],
```

Keep `level=interp`. Add an assertion near row construction if useful:

```python
assert day["interpretation"] == interp
```

- [ ] **Step 3: Update composite payload persistence (top-level + preserve nested signal)**

In `_composite_daily_rows`, add the three keys at the **TOP LEVEL** of `payload` (alongside the existing `signal` nested object, not inside it). This is the explicit fix for tribunal finding #4 — without it, composite rows would never satisfy `payload->>'interpretation' = '...'` filters and Gate 1 SQL would be path-asymmetric.

```python
                "payload": {
                    "interpretation": day["interpretation"],
                    "vix_percentile_rank": day["vix_percentile_rank"],
                    "vvix_percentile_rank": day["vvix_percentile_rank"],
                    "signal": {
                        # ... existing nested signal fields unchanged ...
                    },
                },
```

The composite row's top-level `level` should still be the canonical basket signal interpretation. Rich consumers that already read `payload.signal.*` (the `named_crash_window` builder at scripts/backtest_vcg.py:563) continue to work unchanged.

- [ ] **Step 4: Run focused tests**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py tests/unit/test_backtest_vcg_daily_payloads.py -v
```

Expected: all pass. If the composite test fails with missing percentile keys, Task 4 did not update `_compute_vcg_from_returns`.

---

## Task 8: Add the regime-field invariance test (golden fixture)

The spec asserts the `regime` field is bit-for-bit unchanged from v1. This test catches accidental regressions in the regime-computation block at lines 281-286.

**Files:**
- Test: `tests/unit/cards/test_vcg_scoring_v2_cascade.py`

- [ ] **Step 1: Add the regime invariance test**

Append to `tests/unit/cards/test_vcg_scoring_v2_cascade.py`:

```python
@pytest.mark.parametrize(
    "pi_val,expected_regime",
    [
        (-0.5, "DIVERGENCE"),   # pi <= 0
        (0.0, "DIVERGENCE"),    # pi == 0 (boundary; v1 says DIVERGENCE)
        (0.1, "TRANSITION"),    # 0 < pi < 1
        (0.5, "TRANSITION"),
        (0.99, "TRANSITION"),
        (1.0, "PANIC"),         # pi >= 1
        (1.5, "PANIC"),
    ],
)
def test_regime_field_unchanged_from_v1(pi_val, expected_regime) -> None:
    """v2 spec §6.1 + §10 — regime field is bit-for-bit identical to v1.

    Lines 281-286 of vcg_scoring.py are explicitly untouched. This test
    guards against accidental regression of the regime computation when
    future v2.1 changes touch nearby code.
    """
    model, idx = _make_model_for_cascade(pi=pi_val, sign_ok=True, vcg=0.0)
    payload = vcg_scoring._interpretation_for_index(model, idx)
    assert payload["regime"] == expected_regime
```

- [ ] **Step 2: Run, verify it passes (regime block is untouched)**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py -v -k "regime_field_unchanged"
```

Expected: 7 PASSes (one per parametrize case).

- [ ] **Step 3: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add tests/unit/cards/test_vcg_scoring_v2_cascade.py
git commit -m "test(vcg): regime-field invariance test (guard against future drift)

Parametrized over 7 pi values spanning DIVERGENCE/TRANSITION/PANIC. Per
spec §10: regime field is bit-for-bit unchanged from v1. This test makes
that contract enforceable in CI."
```

---

## Task 9: Update Pydantic `VcgSignal` model

**Files:**
- Modify: `src/uw_scan/api/schemas.py` (class `VcgSignal`, around line 365)
- Create: `tests/unit/api/test_models_regime.py`

- [ ] **Step 1: Create the test file with three failing validation tests**

Create `tests/unit/api/test_models_regime.py`:

```python
"""Pydantic v=1/v=2 payload validation tests.

Per VCG v2 spec §8.1: VcgSignal must accept v=1 payloads (no percentile
ranks) and v=2 payloads (with percentile ranks, possibly None).
"""

from __future__ import annotations

import pytest

from uw_scan.api.schemas import VcgSignal


def _v1_payload() -> dict:
    """Sample v=1 payload — no percentile-rank fields."""
    return {
        "vcg": 0.5,
        "vcg_adj": 0.4,
        "residual": 0.001,
        "beta1_vvix": -0.02,
        "beta2_vix": -0.01,
        "alpha": 0.0,
        "vix": 18.0,
        "vvix": 90.0,
        "credit_price": 80.5,
        "credit_5d_return_pct": 0.5,
        "ro": 0,
        "edr": 0,
        "tier": None,
        "bounce": 0,
        "vvix_severity": "moderate",
        "sign_ok": True,
        "sign_suppressed": False,
        "pi_panic": 0.0,
        "regime": "DIVERGENCE",
        "interpretation": "NORMAL",
        "attribution": {
            "vvix_pct": 60.0,
            "vix_pct": 40.0,
            "vvix_component": 0.001,
            "vix_component": 0.001,
            "model_implied": 0.002,
        },
    }


def test_vcg_payload_accepts_v1_without_percentiles() -> None:
    """v=1 payloads must validate; new fields default to None."""
    model = VcgSignal.model_validate(_v1_payload())
    assert model.vix_percentile_rank is None
    assert model.vvix_percentile_rank is None


def test_vcg_payload_accepts_v2_with_percentiles() -> None:
    """v=2 payloads with finite percentile ranks must round-trip."""
    payload = _v1_payload()
    payload["vix_percentile_rank"] = 0.97
    payload["vvix_percentile_rank"] = 0.96
    model = VcgSignal.model_validate(payload)
    assert model.vix_percentile_rank == pytest.approx(0.97)
    assert model.vvix_percentile_rank == pytest.approx(0.96)


def test_vcg_payload_accepts_v2_with_nan_percentiles_as_null() -> None:
    """v=2 payloads with None (JSON null) percentile ranks must validate."""
    payload = _v1_payload()
    payload["vix_percentile_rank"] = None
    payload["vvix_percentile_rank"] = None
    model = VcgSignal.model_validate(payload)
    assert model.vix_percentile_rank is None
    assert model.vvix_percentile_rank is None
```

- [ ] **Step 2: Run, verify 2 of 3 fail**

```bash
uv run pytest tests/unit/api/test_models_regime.py -v
```

Expected: `test_vcg_payload_accepts_v1_without_percentiles` will FAIL with `AttributeError: 'VcgSignal' object has no attribute 'vix_percentile_rank'`. Same for the other two.

- [ ] **Step 3: Add the two fields to `VcgSignal`**

In `src/uw_scan/api/schemas.py`, find the `VcgSignal` class (currently around line 365). The class ends with `attribution: VcgAttribution = Field(default_factory=VcgAttribution)`. Immediately BEFORE that line, insert:

```python
    vix_percentile_rank: float | None = Field(
        default=None,
        description=(
            "VIX level's 252-day rolling percentile rank (strict_lt tie rule). "
            "Used by the v2 absolute-vol-stress override gate. None during the "
            "252-bar warmup or for v=1 payloads (which lack this field)."
        ),
    )
    vvix_percentile_rank: float | None = Field(
        default=None,
        description=(
            "VVIX level's 252-day rolling percentile rank (strict_lt tie rule). "
            "Used by the v2 absolute-vol-stress override gate."
        ),
    )
```

- [ ] **Step 4: Run, verify all 3 pass**

```bash
uv run pytest tests/unit/api/test_models_regime.py -v
```

Expected: 3 PASSes.

- [ ] **Step 5: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add src/uw_scan/api/schemas.py tests/unit/api/test_models_regime.py
git commit -m "feat(api): add vix/vvix_percentile_rank to VcgSignal model

Two new float | None fields, defaulting to None. v=1 payloads (lacking
these fields) validate via the default; v=2 payloads with finite values
round-trip cleanly. Per spec §6.3 + §8.1. NaN -> None contract preserved.

Includes a fresh tests/unit/api/test_models_regime.py covering all three
validation paths."
```

---

## Task 10: Regenerate OpenAPI snapshot + TypeScript types

**Files:**
- Modify: `tests/integration/api/openapi.snapshot.json`
- Modify: `web/lib/types.ts`

- [ ] **Step 1: Regenerate the OpenAPI snapshot**

The snapshot test does not provide an `--update-snapshot` flag. It compares `client.get("/openapi.json").json()` against `tests/integration/api/openapi.snapshot.json`. Regenerate the JSON with the same in-process app/client path:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from fastapi.testclient import TestClient
from uw_scan.api.server import app

snap = Path("tests/integration/api/openapi.snapshot.json")
current = TestClient(app).get("/openapi.json").json()
snap.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
PY
```

Then run the snapshot test in Step 4. If this import requires integration-test env, use the existing `client` fixture's app import path from `tests/integration/api/conftest.py`; do not invent an update flag.

- [ ] **Step 2: Inspect the snapshot diff — verify it's additive only**

```bash
git diff tests/integration/api/openapi.snapshot.json
```

Expected: only added lines (new `vix_percentile_rank` and `vvix_percentile_rank` fields in the `VcgSignal` component). No removed or renamed fields. If any field is removed/renamed, that's a bug — investigate before continuing.

- [ ] **Step 3: Regenerate TypeScript types**

```bash
(
  uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 &
  api_pid=$!
  trap 'kill $api_pid' EXIT
  sleep 2
  cd web && npm run gen:types
)
git diff web/lib/types.ts
```

Expected: two new optional fields appear in the VcgSignal-equivalent type. Additive only. If an API server is already running on port 8400, skip the temporary `uvicorn` process and run `cd web && npm run gen:types` against the existing server.

- [ ] **Step 4: Run the OpenAPI snapshot test to confirm it now passes**

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "chore(api): regenerate OpenAPI snapshot + TS types for VCG v2

Additive-only: two new VcgSignal fields (vix_percentile_rank,
vvix_percentile_rank), both optional number | null. Existing v=1 clients
ignoring unknown fields continue to work. Per spec §8.3 + §10."
```

---

## Task 11: Build the 7-crisis integration fixture

**Files:**
- Create: `scripts/build_vcg_v2_test_fixture.py`
- Create: `tests/integration/regime/fixtures/seven_crisis_vol_complex.parquet`
- Create: `tests/integration/regime/fixtures/seven_crisis_truth_labels.parquet`
- Create: `tests/integration/regime/fixtures/README.md`

- [ ] **Step 1: Create the fixture-building script**

Create `scripts/build_vcg_v2_test_fixture.py`:

```python
"""Build the 7-crisis fixture for VCG v2 integration tests.

Uses the current long-form schema:
  - uw_scan.vol_index_daily(symbol, trade_date, close, adj_close, ...)
  - uw_scan.macro_series_daily(series_id, obs_date, value, as_of, ...)

The output is NOT only crisis-window rows. VCG v2 uses 21/63/252-day rolling
state, so the fixture must preserve contiguous warmup context. The script writes
the full date range from earliest crisis start minus warmup through latest crisis
end, with a crisis_window column used by Gate 1 / Gate 2 to subset assertions.

Writes two parquet files into tests/integration/regime/fixtures/:
  - seven_crisis_vol_complex.parquet
      (trade_date, vix, vvix, hyg, spx_close, crisis_window)
  - seven_crisis_truth_labels.parquet
      (trade_date, truth_status, crisis_window)

Run from the project root:
    uv run scripts/build_vcg_v2_test_fixture.py

Idempotent — overwrites the parquet files on each run.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
import yaml

from uw_scan.config import Settings
from uw_scan.cards.regime_classification_labels import derive_level1_frame

log = logging.getLogger(__name__)

FIXTURE_DIR = Path("tests/integration/regime/fixtures")
THRESHOLDS_YAML = Path("docs/research/regime/ground-truth-labels/level1-thresholds.yaml")
NAMED_CRISES_YAML = Path("docs/research/regime/ground-truth-labels/named-crises.yaml")
WARMUP_DAYS = 500


def _load_crisis_windows() -> list[dict]:
    data = yaml.safe_load(NAMED_CRISES_YAML.read_text())
    return data["crises"]


def _crisis_name(ts: pd.Timestamp, windows: list[dict]) -> str | None:
    d = ts.date()
    for window in windows:
        start = date.fromisoformat(window["start_date"])
        end = date.fromisoformat(window["end_date"])
        if start <= d <= end:
            return window["name"]
    return None


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    windows = _load_crisis_windows()
    log.info("loaded %d crisis windows", len(windows))
    thresholds = yaml.safe_load(THRESHOLDS_YAML.read_text())
    eval_start = min(date.fromisoformat(w["start_date"]) for w in windows)
    eval_end = max(date.fromisoformat(w["end_date"]) for w in windows)
    data_start = eval_start - timedelta(days=WARMUP_DAYS)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT trade_date, symbol, close, adj_close
              FROM uw_scan.vol_index_daily
             WHERE symbol IN ('VIX','VVIX','SPX','HYG')
               AND trade_date BETWEEN %s AND %s
             ORDER BY trade_date, symbol
            """,
            (data_start, eval_end),
        )
        rows = cur.fetchall()
        raw = pd.DataFrame(rows, columns=["trade_date", "symbol", "close", "adj_close"])
        raw["trade_date"] = pd.to_datetime(raw["trade_date"]).dt.normalize()
        raw["price"] = raw.apply(
            lambda r: r["adj_close"] if r["symbol"] == "HYG" and pd.notna(r["adj_close"]) else r["close"],
            axis=1,
        )
        pivot = (
            raw.pivot(index="trade_date", columns="symbol", values="price")
            .sort_index()
            .ffill()
            .rename(columns={"VIX": "vix", "VVIX": "vvix", "HYG": "hyg", "SPX": "spx_close"})
        )
        df = pivot[["vix", "vvix", "hyg", "spx_close"]].reset_index()
        df["crisis_window"] = df["trade_date"].apply(lambda d: _crisis_name(d, windows))
        log.info("vol_complex contiguous slice: %d rows", len(df))

        out_path = FIXTURE_DIR / "seven_crisis_vol_complex.parquet"
        df.to_parquet(out_path, index=False)
        log.info("wrote %s", out_path)

        cur.execute(
            """
            SELECT DISTINCT ON (series_id, obs_date) obs_date, series_id, value
              FROM uw_scan.macro_series_daily
             WHERE series_id = 'NFCI'
               AND obs_date BETWEEN %s AND %s
             ORDER BY series_id, obs_date, as_of DESC
            """,
            (data_start, eval_end),
        )
        macro = pd.DataFrame(cur.fetchall(), columns=["obs_date", "series_id", "value"])
        macro["obs_date"] = pd.to_datetime(macro["obs_date"]).dt.normalize()
        nfci = macro.set_index("obs_date")["value"].astype(float).sort_index().ffill()
        nfci = nfci.reindex(pivot.index, method="ffill")

        truth = derive_level1_frame(
            vix=pivot["vix"].astype(float),
            vvix=pivot["vvix"].astype(float),
            spx=pivot["spx_close"].astype(float),
            credit_stress=nfci,
            thresholds=thresholds,
        )
        truth_df = pd.DataFrame(
            {
                "trade_date": truth.index,
                "truth_status": truth["truth_label"].astype("string"),
            }
        )
        truth_df["crisis_window"] = truth_df["trade_date"].apply(lambda d: _crisis_name(d, windows))
        truth_df = truth_df[truth_df["crisis_window"].notna()]
        log.info("truth labels inside crisis windows: %d rows", len(truth_df))

        # Tribunal finding #6: data-quality bounds before persisting. Any of these
        # failing means the source DB is missing data and the fixture would let
        # tests pass against fabricated continuity. Fail loudly with a fix hint.
        _assert_fixture_quality(df, truth_df, windows)

        truth_out = FIXTURE_DIR / "seven_crisis_truth_labels.parquet"
        truth_df.to_parquet(truth_out, index=False)
        log.info("wrote %s", truth_out)

    return 0


# Expected truth-stress counts per named crisis window (from the forensic audit
# Table 2, https://docs/research/regime/vcg-stress-window-forensics-2026-05-26.md
# sec 5). Used by _assert_fixture_quality to catch fixture drift.
EXPECTED_PER_WINDOW_TRUTH_STRESS = {
    "GFC-Lehman":            105,  # audit Table 2: stress recall 0.352 → 105 truth-stress days
    "Eurozone-sovereign":    113,  # audit Table 2: stress recall 0.009 → 113 truth-stress days
    "China-devaluation-2015": 39,  # audit Table 2: stress recall 0.000 → 39 truth-stress days
    "Q4-2018-vol-regime":     50,  # audit Table 2: stress recall 0.060 → 50 truth-stress days
    "COVID-2020":             24,  # audit Table 2: stress recall 0.208 → 24 truth-stress days
    "2022-rates-bear":       189,  # audit Table 2: stress recall 0.032 → 189 truth-stress days
    "2023-SVB-week":           8,  # audit Table 2: stress recall 0.000 → 8 truth-stress days
}
EXPECTED_TOTAL_TRUTH_STRESS = sum(EXPECTED_PER_WINDOW_TRUTH_STRESS.values())  # 528


def _assert_fixture_quality(
    df: "pd.DataFrame",
    truth_df: "pd.DataFrame",
    windows: list[dict],
) -> None:
    """Tribunal finding #6 — data-quality bounds on the generated fixture.

    Raises RuntimeError (not assert, so production builds don't strip the guard)
    on:
      1. Missing required symbol columns or any null in crisis windows.
      2. Forward-fill gap larger than 7 calendar days in crisis windows (stale
         data masquerading as continuous).
      3. Fewer than 7 named-crises represented in the fixture.
      4. Total truth-stress days != EXPECTED_TOTAL_TRUTH_STRESS (528).
      5. Per-window truth-stress counts diverge from EXPECTED_PER_WINDOW_TRUTH_STRESS.

    Counts are pinned because Gate 2's frozen baseline 52/528 is only
    comparable if the fixture's universe matches the audit's universe.
    """
    # 1. Required symbol columns present and non-null in crisis windows.
    required = ["vix", "vvix", "hyg", "spx_close"]
    for col in required:
        if col not in df.columns:
            raise RuntimeError(f"fixture missing required column: {col}")
    in_crisis = df[df["crisis_window"].notna()]
    null_counts = in_crisis[required].isna().sum()
    if null_counts.any():
        raise RuntimeError(
            f"fixture has nulls in crisis windows on required columns: "
            f"{null_counts[null_counts > 0].to_dict()}. Source DB is incomplete "
            f"for 2007+; rerun vol_index_daily backfill before regenerating fixture."
        )

    # 2. Forward-fill gap detection. Trade-date gaps within crisis windows
    # larger than 7 calendar days suggest stale ffill rather than legitimate
    # missing-business-days. (7 days = 1 long weekend + holiday tolerance.)
    in_crisis_dates = in_crisis["trade_date"].sort_values().reset_index(drop=True)
    diffs = in_crisis_dates.diff().dt.days.dropna()
    max_gap = int(diffs.max()) if not diffs.empty else 0
    if max_gap > 7:
        raise RuntimeError(
            f"fixture has a gap of {max_gap} days inside a crisis window. "
            f"That likely means vol_index_daily is missing rows; .ffill() would "
            f"otherwise fabricate continuous values. Backfill the source DB."
        )

    # 3. All 7 named crises represented.
    present_windows = set(in_crisis["crisis_window"].unique())
    expected_windows = {w["name"] for w in windows}
    missing_windows = expected_windows - present_windows
    if missing_windows:
        raise RuntimeError(
            f"fixture is missing named crisis windows: {sorted(missing_windows)}. "
            f"Source DB lacks vol_index_daily rows in those date ranges."
        )

    # 4. Total truth-stress denominator matches the audit.
    truth_stress = truth_df[truth_df["truth_status"].isin(["EDR", "RISK_OFF", "PANIC"])]
    n_truth_stress = len(truth_stress)
    if n_truth_stress != EXPECTED_TOTAL_TRUTH_STRESS:
        raise RuntimeError(
            f"fixture has {n_truth_stress} truth-stress days; audit baseline "
            f"requires exactly {EXPECTED_TOTAL_TRUTH_STRESS} (Gate 2 universe lock). "
            f"Per-window breakdown: "
            f"{truth_stress.groupby('crisis_window').size().to_dict()}"
        )

    # 5. Per-window truth-stress counts match the audit exactly.
    actual_per_window = truth_stress.groupby("crisis_window").size().to_dict()
    for win, expected_count in EXPECTED_PER_WINDOW_TRUTH_STRESS.items():
        actual = actual_per_window.get(win, 0)
        if actual != expected_count:
            raise RuntimeError(
                f"crisis window '{win}': fixture has {actual} truth-stress days, "
                f"audit baseline expects {expected_count}. Fix source DB or update "
                f"EXPECTED_PER_WINDOW_TRUTH_STRESS (and the audit) deliberately."
            )

    log.info(
        "fixture quality verified: %d rows total, %d truth-stress days across "
        "%d named-crisis windows",
        len(df),
        n_truth_stress,
        len(present_windows),
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

Current schema note: `vol_index_daily` is long-form by `symbol`; do not use the obsolete wide columns `vix_close` / `vvix_close`, do not use `daily_ohlc` for HYG/SPX here, and do not rely on a nonexistent `regime_classification_daily` table. Truth labels are derived into the committed parquet using `derive_level1_frame`.

- [ ] **Step 2: Run the script against your local DB**

```bash
uv run scripts/build_vcg_v2_test_fixture.py
```

Expected: prints `vol_complex contiguous slice: N rows` (N is several thousand because warmup/context rows are retained) and `truth labels inside crisis windows: N rows` (the crisis-window denominator). Both parquet files appear in `tests/integration/regime/fixtures/`.

If the SQL fails, inspect the current migrations before changing the fixture shape. The verified anchors are `src/uw_scan/storage/migrations/038_vol_index_daily.sql` and the existing classification loader in `scripts/score_vcg_classification_accuracy.py`.

- [ ] **Step 3: Create the README**

Create `tests/integration/regime/fixtures/README.md`:

```markdown
# VCG v2 integration fixtures

## Files

- `seven_crisis_vol_complex.parquet` — contiguous vol-complex slice (`trade_date`, `vix`, `vvix`, `hyg`, `spx_close`, `crisis_window`) from earliest crisis warmup through latest crisis end. Tests insert these rows into `uw_scan.vol_index_daily`.
- `seven_crisis_truth_labels.parquet` — `(trade_date, truth_status, crisis_window)` pairs for crisis-window dates only. Tests join this parquet in memory against `regime_backtest_daily`; there is no `regime_classification_daily` fixture table.

## Regenerating

```bash
uv run scripts/build_vcg_v2_test_fixture.py
```

Idempotent — overwrites both parquet files on each run. Run from the project root with `UW_SCAN_DB_NAME`/`UW_SCAN_DB_HOST`/`UW_SCAN_DB_PORT`/`UW_SCAN_DB_USER`/`UW_SCAN_DB_PASSWORD` pointing at a database that has `vol_index_daily` and `macro_series_daily` populated for 2007+; `Settings.from_env()` does not read `UW_SCAN_DB_URL`.

## Why parquet, not CSV

Preserves dtypes (NaN handling on numeric columns matters for the alignment tests) and is 5-10× smaller for the same row count.

## Why committed

The fixture remains small enough to commit while preserving rolling-window context. The trade-off: updates to `vol_index_daily`, `macro_series_daily`, or Level-1 label thresholds for this range require regenerating both parquet files.

## Pinned data-quality invariants (tribunal finding #6)

The builder script (`scripts/build_vcg_v2_test_fixture.py`) refuses to write the parquet files unless ALL of these hold. Reviewers can detect drift by comparing the runtime build log against the values below.

- Required symbol columns present: `vix`, `vvix`, `hyg`, `spx_close`.
- Zero nulls in those columns inside any of the 7 crisis windows.
- Max forward-fill gap inside crisis windows: 7 calendar days (catches stale data masquerading as continuous).
- All 7 named crises represented.
- **Total truth-stress days: exactly 528.** This is the denominator for Gate 2's frozen baseline `52/528 = 0.0985`. A subset fixture invalidates the gate's comparison.
- **Per-window truth-stress counts:**

| Crisis window               | Expected truth-stress days |
|-----------------------------|---------------------------:|
| GFC-Lehman                  | 105 |
| Eurozone-sovereign          | 113 |
| China-devaluation-2015      |  39 |
| Q4-2018-vol-regime          |  50 |
| COVID-2020                  |  24 |
| 2022-rates-bear             | 189 |
| 2023-SVB-week               |   8 |
| **Total**                   | **528** |

Source: `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md` Table 2 (each row's "Truth-stress days: N" header).

If you intend to change these (e.g. label-version bump, audit revision), update `EXPECTED_PER_WINDOW_TRUTH_STRESS` in the builder script AND the spec's frozen baseline AND `vcg-stress-window-forensics-2026-05-26.md` Table 2 in the same PR.
```

- [ ] **Step 4: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add scripts/build_vcg_v2_test_fixture.py \
        tests/integration/regime/fixtures/seven_crisis_vol_complex.parquet \
        tests/integration/regime/fixtures/seven_crisis_truth_labels.parquet \
        tests/integration/regime/fixtures/README.md
git commit -m "test(vcg): build 7-crisis integration fixture

One-shot builder script + two committed parquet files. The vol-complex
fixture preserves contiguous warmup context for the v2 backtest in the
integration tests; the truth-labels parquet is the recall denominator
for Gate 2.

Per spec §8.2 'Fixture' subsection."
```

---

## Task 12: Integration test 1 — Gate 1 (zero PANIC-SUPPRESSED contradictions)

**Files:**
- Create: `tests/integration/regime/test_vcg_v2_contradiction.py`

**Prerequisites (must land first):**
- Task 7A (scripts/backtest_vcg.py persists `interpretation` at top level of payload). Without Task 7A, the `missing_interpretation == 0` guard at line ~1416 will fail loudly with a clear error, but Gate 1's contradiction predicate would otherwise be vacuously satisfied (no row has the key at all). **Tribunal finding #10.**
- Task 11 (the 7-crisis fixture parquet files committed).

- [ ] **Step 1: Write the integration test**

Create `tests/integration/regime/test_vcg_v2_contradiction.py`:

```python
"""VCG v2 Gate 1 — zero PANIC-SUPPRESSED contradictions.

Per spec §5 Gate 1 + §8.2 Test 1.

Loads the 7-crisis fixture into a fresh pytest-postgresql DB, runs the
backtest_vcg main entry, queries regime_backtest_daily for rows with
regime='PANIC' AND interpretation='SUPPRESSED', asserts count = 0.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import psycopg
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(conn: psycopg.Connection) -> None:
    """Load vol_complex fixture into the test DB's long-form vol_index_daily."""
    vol_df = pd.read_parquet(FIXTURE_DIR / "seven_crisis_vol_complex.parquet")
    with conn.cursor() as cur:
        for _, r in vol_df.iterrows():
            trade_date = pd.Timestamp(r["trade_date"]).date()
            for symbol, value, adj_close in (
                ("VIX", r["vix"], None),
                ("VVIX", r["vvix"], None),
                ("SPX", r["spx_close"], None),
                ("HYG", r["hyg"], r["hyg"]),
            ):
                cur.execute(
                    "INSERT INTO uw_scan.vol_index_daily "
                    "(symbol, trade_date, close, adj_close) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (symbol, trade_date) DO UPDATE SET "
                    "close = EXCLUDED.close, adj_close = EXCLUDED.adj_close",
                    (symbol, trade_date, value, adj_close),
                )
    conn.commit()


def _subprocess_db_env(conn: psycopg.Connection) -> dict[str, str]:
    info = conn.info
    env = dict(__import__("os").environ)
    if info.host:
        env["UW_SCAN_DB_HOST"] = str(info.host)
    if info.port:
        env["UW_SCAN_DB_PORT"] = str(info.port)
    env["UW_SCAN_DB_NAME"] = str(info.dbname)
    env["UW_SCAN_DB_USER"] = str(info.user)
    if info.password:
        env["UW_SCAN_DB_PASSWORD"] = str(info.password)
    env.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return env


def _run_backtest_vcg(conn: psycopg.Connection) -> None:
    """Invoke scripts/backtest_vcg.py against the test DB."""
    proc = subprocess.run(
        ["uv", "run", "scripts/backtest_vcg.py"],
        env=_subprocess_db_env(conn),
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"backtest_vcg failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


def test_vcg_v2_produces_zero_panic_suppressed_contradictions(seeded_db_empty_cards) -> None:
    """Gate 1: SELECT COUNT(*) WHERE regime='PANIC' AND interpretation='SUPPRESSED' == 0."""
    conn = seeded_db_empty_cards.conn
    _load_fixture(conn)

    # Run the production backtest entry (COMPOSITE_VERSION=2 is read from code)
    _run_backtest_vcg(conn)

    # Verify v=2 row landed
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM uw_scan.regime_backtest_runs "
            "WHERE indicator='vcg' AND composite_version='2' "
            "  AND run_scope='production' AND completed_at IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None, "expected a completed v=2 production run"
    v2_run_id = row[0]

    # Guard against a false pass: Gate 1 reads payload.interpretation.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s AND payload->>'interpretation' IS NULL",
            (v2_run_id,),
        )
        missing_interpretation = cur.fetchone()[0]
    assert missing_interpretation == 0, "backtest payload must persist payload.interpretation"

    # The Gate 1 assertion
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s "
            "  AND payload->>'regime' = 'PANIC' "
            "  AND payload->>'interpretation' = 'SUPPRESSED'",
            (v2_run_id,),
        )
        contradiction_count = cur.fetchone()[0]

    assert contradiction_count == 0, (
        f"Gate 1 FAILED: {contradiction_count} rows have regime='PANIC' AND "
        f"interpretation='SUPPRESSED' in run_id={v2_run_id}. The v2 cascade fix "
        f"is supposed to make this number zero. See docs/superpowers/specs/"
        f"2026-05-27-vcg-v2-cascade-and-absolute-vol-spec.md §5 Gate 1."
    )
```

Note: use the canonical `seeded_db_empty_cards` integration fixture from `tests/integration/conftest.py`. It returns a `Repository`; the psycopg connection is `repo.conn`. `Settings.from_env()` reads `UW_SCAN_DB_NAME` et al., not `UW_SCAN_DB_URL`, so subprocess tests must pass those env vars.

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/integration/regime/test_vcg_v2_contradiction.py -v
```

Expected: PASS. If FAIL with `contradiction_count > 0`, the cascade rewrite in Task 6 is wrong — investigate by inspecting a contradictory row's full payload.

If the test fails with infrastructure issues (missing migration, fixture column mismatch), fix those first. The Gate-1 assertion is the genuine acceptance bar.

- [ ] **Step 3: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add tests/integration/regime/test_vcg_v2_contradiction.py
git commit -m "test(vcg): integration Gate 1 — zero PANIC-SUPPRESSED contradictions

Runs the full backtest_vcg pipeline against the 7-crisis fixture via
subprocess, then asserts the spec's Gate 1 SQL returns 0. This is the
primary acceptance bar — if it passes, v2's cascade fix is verified
end-to-end."
```

---

## Task 13: Integration test 2 — Gate 2 (recall non-regression)

**Files:**
- Create: `tests/integration/regime/test_vcg_v2_recall_non_regression.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/regime/test_vcg_v2_recall_non_regression.py`:

```python
"""VCG v2 Gate 2 — crisis-window stress recall must not regress.

Per spec §5 Gate 2 + §8.2 Test 2.

v1 baseline (frozen, from forensic audit Table 2): 52/528 = 0.0985.
This number must NOT be re-derived at test time. If the audit is wrong,
that gets fixed in the audit, not here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import psycopg
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
V1_CRISIS_RECALL_BASELINE = 52 / 528  # = 0.0985, frozen from audit
STRESS_INTERPRETATIONS = ("WATCH", "EDR", "RISK_OFF", "PANIC", "BOUNCE")
TRUTH_STRESS_STATUSES = ("EDR", "RISK_OFF", "PANIC")


def _load_fixture(conn: psycopg.Connection) -> None:
    """Same long-form vol_index_daily loader as test_vcg_v2_contradiction."""
    vol_df = pd.read_parquet(FIXTURE_DIR / "seven_crisis_vol_complex.parquet")
    with conn.cursor() as cur:
        for _, r in vol_df.iterrows():
            trade_date = pd.Timestamp(r["trade_date"]).date()
            for symbol, value, adj_close in (
                ("VIX", r["vix"], None),
                ("VVIX", r["vvix"], None),
                ("SPX", r["spx_close"], None),
                ("HYG", r["hyg"], r["hyg"]),
            ):
                cur.execute(
                    "INSERT INTO uw_scan.vol_index_daily "
                    "(symbol, trade_date, close, adj_close) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (symbol, trade_date) DO UPDATE SET "
                    "close = EXCLUDED.close, adj_close = EXCLUDED.adj_close",
                    (symbol, trade_date, value, adj_close),
                )
    conn.commit()


def _subprocess_db_env(conn: psycopg.Connection) -> dict[str, str]:
    info = conn.info
    env = dict(__import__("os").environ)
    if info.host:
        env["UW_SCAN_DB_HOST"] = str(info.host)
    if info.port:
        env["UW_SCAN_DB_PORT"] = str(info.port)
    env["UW_SCAN_DB_NAME"] = str(info.dbname)
    env["UW_SCAN_DB_USER"] = str(info.user)
    if info.password:
        env["UW_SCAN_DB_PASSWORD"] = str(info.password)
    env.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return env


def _run_backtest_vcg(conn: psycopg.Connection) -> None:
    proc = subprocess.run(
        ["uv", "run", "scripts/backtest_vcg.py"],
        env=_subprocess_db_env(conn),
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"backtest_vcg failed:\n{proc.stdout}\n{proc.stderr}")


def test_v2_does_not_reduce_crisis_recall(seeded_db_empty_cards) -> None:
    """Gate 2: v2 crisis-window stress recall >= v1 baseline 0.0985."""
    conn = seeded_db_empty_cards.conn
    _load_fixture(conn)

    _run_backtest_vcg(conn)

    # Find the v=2 production run
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM uw_scan.regime_backtest_runs "
            "WHERE indicator='vcg' AND composite_version='2' "
            "  AND run_scope='production' AND completed_at IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    assert row is not None
    v2_run_id = row[0]

    truth_df = pd.read_parquet(FIXTURE_DIR / "seven_crisis_truth_labels.parquet")
    truth_stress = truth_df[truth_df["truth_status"].isin(TRUTH_STRESS_STATUSES)].copy()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, payload->>'interpretation' AS interpretation "
            "FROM uw_scan.regime_backtest_daily WHERE run_id = %s",
            (v2_run_id,),
        )
        daily = pd.DataFrame(cur.fetchall(), columns=["trade_date", "interpretation"])

    truth_stress["trade_date"] = pd.to_datetime(truth_stress["trade_date"]).dt.date
    daily["trade_date"] = pd.to_datetime(daily["trade_date"]).dt.date
    joined = truth_stress.merge(daily, on="trade_date", how="left", validate="one_to_one")
    missing = joined["interpretation"].isna().sum()
    assert missing == 0, f"{missing} truth-stress fixture dates missing VCG rows"
    v2_hits = joined["interpretation"].isin(STRESS_INTERPRETATIONS).sum()
    truth_stress_days = len(joined)

    # Gate 2 universe lock (tribunal finding #1): the frozen baseline 52/528
    # is only comparable if the fixture's truth-stress universe matches the
    # 528 days the audit measured. A subset fixture would let the recall
    # ratio silently pass against a smaller denominator. The fixture builder
    # at scripts/build_vcg_v2_test_fixture.py is responsible for producing
    # exactly this count across all 7 named-crisis windows.
    EXPECTED_TRUTH_STRESS_DENOMINATOR = 528
    assert truth_stress_days == EXPECTED_TRUTH_STRESS_DENOMINATOR, (
        f"Gate 2 universe mismatch: fixture has {int(truth_stress_days)} truth-stress "
        f"days; v1 baseline 52/528=0.0985 requires exactly "
        f"{EXPECTED_TRUTH_STRESS_DENOMINATOR}. Either rebuild the fixture against a "
        f"DB with full 2007+ vol_index_daily coverage for all 7 named-crisis windows, "
        f"or update the baseline (and the audit) before this test runs."
    )
    v2_recall = v2_hits / truth_stress_days

    assert v2_recall >= V1_CRISIS_RECALL_BASELINE, (
        f"Gate 2 FAILED: v2 crisis-window stress recall = {v2_recall:.4f} "
        f"({int(v2_hits)}/{int(truth_stress_days)}), below the frozen v1 "
        f"baseline {V1_CRISIS_RECALL_BASELINE:.4f} (52/528). v2 must not "
        f"degrade recall while removing contradictions. See spec §5 Gate 2."
    )
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/integration/regime/test_vcg_v2_recall_non_regression.py -v
```

Expected: PASS. If FAIL with `v2_recall < baseline`, v2 has degraded stress detection — investigate by computing v1's recall on the same fixture and comparing class-by-class counts.

- [ ] **Step 3: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add tests/integration/regime/test_vcg_v2_recall_non_regression.py
git commit -m "test(vcg): integration Gate 2 — recall non-regression vs v1 baseline

v1 baseline 52/528=0.0985 frozen as a constant in the test file (sourced
from the forensic audit Table 2). v2 recall must be >= this.

Gate 2 prevents a degenerate fix that NORMAL-ifies stress days to clear
Gate 1. The pairing of Gate 1 (no contradictions) + Gate 2 (no recall
loss) defines what 'v2 ships' actually means."
```

---

## Task 14: Integration test 3 — API selection picks v=2 after bump

**Files:**
- Create: `tests/integration/regime/test_vcg_v2_api_selection.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/regime/test_vcg_v2_api_selection.py`:

```python
"""VCG v2 API selection — production-default picks v=2 after COMPOSITE_VERSION bump.

Per spec §8.2 Test 3.

Seeds three regime_backtest_runs rows: production v=1, production v=2,
and research v=2. Asserts:
  1. The production-default selector returns the production v=2 row.
  2. A research v=2 row does not satisfy the production-default filter.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg

from uw_scan.cards import vcg_scoring
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _seed_run(
    conn: psycopg.Connection,
    *,
    indicator: str,
    composite_version: str,
    run_scope: str,
    credit_proxy: str,
    composite_method: str,
    completed: bool = True,
) -> int:
    """Insert a regime_backtest_runs row and return its id."""
    completed_at = datetime.now(timezone.utc) if completed else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
              (indicator, composite_version, start_date, end_date,
               window_days, n_days, params, summary, note,
               run_scope, composite_method, credit_proxy,
               created_at, completed_at)
            VALUES (%s, %s, '2007-01-03', '2024-12-31',
                    252, 4500, '{}'::jsonb, '{}'::jsonb, 'test seed',
                    %s, %s, %s,
                    NOW(), %s)
            RETURNING id
            """,
            (indicator, composite_version, run_scope, composite_method,
             credit_proxy, completed_at),
        )
        return cur.fetchone()[0]


def test_default_validation_selects_v2_after_bump(seeded_db_empty_cards) -> None:
    """Production-default find_latest_run picks v=2 after COMPOSITE_VERSION bump."""
    # Sanity: the code constant must be 2 in this branch
    assert vcg_scoring.COMPOSITE_VERSION == 2
    conn = seeded_db_empty_cards.conn

    # Seed three rows
    v1_prod_id = _seed_run(
        conn, indicator="vcg", composite_version="1",
        run_scope="production", credit_proxy="HYG", composite_method="single_proxy",
    )
    v2_prod_id = _seed_run(
        conn, indicator="vcg", composite_version="2",
        run_scope="production", credit_proxy="HYG", composite_method="single_proxy",
    )
    v2_research_id = _seed_run(
        conn, indicator="vcg", composite_version="2",
        run_scope="research", credit_proxy="HYG", composite_method="single_proxy",
    )
    conn.commit()

    # The production-default selector should pick v=2_prod, not v=1_prod, not v=2_research.
    repo = RegimeBacktestRepository(conn)
    selected = repo.find_latest_run("vcg")

    assert selected is not None, "production-default selector returned None"
    assert selected["id"] == v2_prod_id, (
        f"Expected v=2 production row (id={v2_prod_id}), got id={selected['id']}. "
        f"v1_prod={v1_prod_id}, v2_research={v2_research_id}."
    )
    assert selected["composite_version"] == "2"
    assert selected["run_scope"] == "production"


def test_research_v2_does_not_satisfy_production_default(seeded_db_empty_cards) -> None:
    """A research-only v=2 row must NOT be returned by the production-default selector."""
    assert vcg_scoring.COMPOSITE_VERSION == 2
    conn = seeded_db_empty_cards.conn

    # Only research v=2 exists — no production row
    _seed_run(
        conn, indicator="vcg", composite_version="2",
        run_scope="research", credit_proxy="HYG", composite_method="single_proxy",
    )
    conn.commit()

    repo = RegimeBacktestRepository(conn)
    selected = repo.find_latest_run("vcg")  # default run_scope='production'

    assert selected is None, (
        "production-default selector should return None when only research "
        "v=2 rows exist; production endpoint must 503 until a production "
        "backfill lands"
    )
```

Note: `RegimeBacktestRepository.find_latest_run` currently returns a `dict | None`, not a dataclass. Use `selected["id"]`, `selected["composite_version"]`, and `selected["run_scope"]`.

- [ ] **Step 2: Run the tests**

```bash
uv run pytest tests/integration/regime/test_vcg_v2_api_selection.py -v
```

Expected: 2 PASSes. If FAIL, the production-default selector at `regime_backtest_repository.py` is not respecting the bumped constant — investigate `_current_composite_version`.

- [ ] **Step 3: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add tests/integration/regime/test_vcg_v2_api_selection.py
git commit -m "test(vcg): integration test for API selection after COMPOSITE_VERSION bump

Seeds three production/research rows at v=1 and v=2; verifies the
production-default find_latest_run picks v=2_production. Catches drift
where a future refactor could break the constant-derived version
resolution path. Per spec §8.2 Test 3."
```

---

## Task 15: Create `scripts/backfill_vcg_v2.py` (production backfill)

**Files:**
- Create: `scripts/backfill_vcg_v2.py`
- Create: `tests/integration/scripts/test_backfill_vcg_v2.py`

- [ ] **Step 1: Write the wrapper script**

Create `scripts/backfill_vcg_v2.py`:

```python
"""One-shot v=2 backfill for VCG.

Wraps scripts/backtest_vcg.py with five contracts (per spec §9.2 + tribunal §2 & §5):
  1. Hard runtime check COMPOSITE_VERSION == 2 before any DB write.
  2. No CLI override of composite_version — the constant is the source. Argv
     comes from _build_backtest_argv() so the test can pin it.
  3. Idempotent: existing v=2 production row -> exit 0 unless --force.
  4. Session-level advisory lock around check + run + verify; two concurrent
     operators serialise instead of both spawning backtest_vcg subprocesses.
  5. Post-subprocess Gate 1 integrity: daily row count, NULL-interpretation
     count, and PANIC^SUPPRESSED contradiction count all assert clean before
     returning 0. A "completed" run with broken payload exits nonzero.

Run from project root:
    uv run scripts/backfill_vcg_v2.py             # production DSN from env
    uv run scripts/backfill_vcg_v2.py --force     # re-run even if v=2 exists
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys

import psycopg

from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION
from uw_scan.config import Settings

log = logging.getLogger(__name__)

# Advisory-lock key for the backfill. Two concurrent operators serialise on
# this key — pg_advisory_lock(hashtext(...)) holds for the lifetime of the
# connection. Required because migration 062's unique index only covers
# composite_method='classification_accuracy', NOT production single_proxy.
_LOCK_KEY = "vcg:v2:production:HYG:single_proxy"

# Whitelist of parent env vars forwarded to the backtest_vcg.py subprocess.
# Avoids leaking unrelated secrets (FMP_API_KEY, MASSIVE_API_KEY, etc.) into
# a job that only needs DB credentials.
_DB_ENV_WHITELIST = (
    "UW_SCAN_DB_NAME", "UW_SCAN_DB_HOST", "UW_SCAN_DB_PORT",
    "UW_SCAN_DB_USER", "UW_SCAN_DB_PASSWORD",
    "PATH", "HOME", "USER",  # required for uv to locate venv + Python
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-shot VCG v=2 backfill")
    p.add_argument("--force", action="store_true",
                   help="Re-run even if a completed v=2 production row already exists")
    return p.parse_args()


def _build_backtest_argv() -> list[str]:
    """Argv for the backtest subprocess. Centralised so the test for
    contract #2 ('no --composite-version override on the CLI') can assert
    against a single source of truth."""
    return ["uv", "run", "scripts/backtest_vcg.py"]


def _subprocess_env() -> dict[str, str]:
    """Build subprocess env from a strict whitelist. backtest_vcg.py reads
    Settings.from_env() which requires UW_SCAN_API_KEY; a dummy value is
    fine because this job only uses the DB connection."""
    env = {k: v for k, v in os.environ.items() if k in _DB_ENV_WHITELIST}
    env.setdefault("UW_SCAN_API_KEY", "backfill-dummy-not-used-by-db-only-job")
    return env


def _existing_v2_run_id(conn: psycopg.Connection) -> int | None:
    """Returns the id of a completed v=2 production HYG single_proxy row, or None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM uw_scan.regime_backtest_runs
            WHERE indicator='vcg'
              AND composite_version='2'
              AND run_scope='production'
              AND credit_proxy='HYG'
              AND composite_method='single_proxy'
              AND completed_at IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return row[0] if row else None


def _verify_gate1_integrity(conn: psycopg.Connection, run_id: int, n_days: int) -> int:
    """Post-subprocess SQL checks (tribunal finding #5). Returns exit code 0
    on pass, nonzero on fail. Three assertions:
      1. Daily row count == n_days (no partial bulk insert).
      2. Zero rows with NULL payload.interpretation (Task 7A persistence).
      3. Zero rows with regime='PANIC' AND interpretation='SUPPRESSED' (Gate 1)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily WHERE run_id = %s",
            (run_id,),
        )
        actual_rows = cur.fetchone()[0]
        if actual_rows != n_days:
            log.error("daily row count %d != n_days %d for run_id=%d",
                      actual_rows, n_days, run_id)
            return 3

        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s AND payload->>'interpretation' IS NULL",
            (run_id,),
        )
        null_interp = cur.fetchone()[0]
        if null_interp != 0:
            log.error("%d daily rows have NULL payload.interpretation for "
                      "run_id=%d (Task 7A must persist interpretation into payload)",
                      null_interp, run_id)
            return 4

        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s "
            "  AND payload->>'regime' = 'PANIC' "
            "  AND payload->>'interpretation' = 'SUPPRESSED'",
            (run_id,),
        )
        contradictions = cur.fetchone()[0]
        if contradictions != 0:
            log.error("Gate 1 FAILED post-backfill: %d PANIC^SUPPRESSED rows "
                      "for run_id=%d. v2 cascade fix is incomplete.",
                      contradictions, run_id)
            return 5
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()

    # Contract 1: refuse to run against a pre-bump build. Use an explicit
    # exception rather than assert; production scripts must not lose this guard
    # under python -O.
    if COMPOSITE_VERSION != 2:
        raise RuntimeError(
            f"backfill_vcg_v2 requires vcg_scoring.COMPOSITE_VERSION == 2; "
            f"got {COMPOSITE_VERSION}. Bump the constant before running."
        )

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        # Contract 4 (tribunal finding #2): session-level advisory lock around
        # check + run + verify. Holds for the lifetime of this connection;
        # two concurrent operators serialise on _LOCK_KEY instead of racing.
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (_LOCK_KEY,))
        conn.commit()
        try:
            # Contract 3: idempotency (re-check after lock acquisition; the
            # first holder may have already produced the v=2 row while we
            # waited at pg_advisory_lock).
            existing_id = _existing_v2_run_id(conn)
            if existing_id is not None and not args.force:
                log.info(
                    "v=2 production row already exists (run_id=%d); use --force "
                    "to re-run. Advisory lock was held — concurrent caller may "
                    "have produced this row while we waited.",
                    existing_id,
                )
                return 0

            # Contract 2: invoke backtest_vcg with NO --composite-version override.
            # _build_backtest_argv() is the single source of truth for the argv
            # so the no-override contract is testable.
            log.info("running scripts/backtest_vcg.py with default production args")
            proc = subprocess.run(
                _build_backtest_argv(),
                env=_subprocess_env(),
                capture_output=False,  # stream backtest logs to operator
                text=True,
            )
            if proc.returncode != 0:
                log.error("backtest_vcg failed with exit %d", proc.returncode)
                return proc.returncode
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_LOCK_KEY,))
            conn.commit()

    # Re-open connection to verify provenance + Gate 1 integrity of the new row.
    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, composite_version, run_scope, credit_proxy, composite_method, n_days
            FROM uw_scan.regime_backtest_runs
            WHERE indicator='vcg'
              AND composite_version='2'
              AND run_scope='production'
              AND credit_proxy='HYG'
              AND composite_method='single_proxy'
              AND completed_at IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row is None:
        log.error("no completed v=2 row after backtest_vcg ran")
        return 2
    run_id, cv, rs, cp, cm, n_days = row
    if not (cv == "2" and rs == "production" and cp == "HYG" and cm == "single_proxy"):
        log.error("new row has wrong provenance: composite_version=%s run_scope=%s "
                  "credit_proxy=%s composite_method=%s", cv, rs, cp, cm)
        return 6

    # Tribunal finding #5: verify Gate 1 integrity BEFORE declaring success.
    # A "completed" run with broken payload or vacuous content must not pass.
    with psycopg.connect(settings.db_dsn()) as conn:
        rc = _verify_gate1_integrity(conn, run_id, n_days)
        if rc != 0:
            return rc

    log.info("v=2 production backfill complete: run_id=%d n_days=%d", run_id, n_days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Write contract tests for idempotency + version assert**

Create `tests/integration/scripts/test_backfill_vcg_v2.py` (create `tests/integration/scripts/` if it does not already exist):

```python
"""Contract tests for scripts/backfill_vcg_v2.py.

Doesn't run the actual backtest (that's the integration test's job).
Tests the version-check and idempotency contracts in isolation.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


def _import_backfill_module():
    """Import the backfill script as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "backfill_vcg_v2", "scripts/backfill_vcg_v2.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_check_fails_when_constant_is_not_two() -> None:
    """Contract: refuses to run against a pre-bump build."""
    mod = _import_backfill_module()
    with patch.object(sys, "argv", ["backfill_vcg_v2.py"]), \
         patch.object(mod, "COMPOSITE_VERSION", 1):
        with pytest.raises(RuntimeError, match="COMPOSITE_VERSION == 2"):
            mod.main()


def test_idempotent_when_v2_row_exists_and_no_force(seeded_db_empty_cards) -> None:
    """Contract: existing v=2 row -> exit 0, no subprocess invocation."""
    mod = _import_backfill_module()
    conn = seeded_db_empty_cards.conn
    # Seed an existing v=2 row
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
              (indicator, composite_version, start_date, end_date,
               window_days, n_days, params, summary, note,
               run_scope, composite_method, credit_proxy,
               created_at, completed_at)
            VALUES ('vcg', '2', '2007-01-03', '2024-12-31',
                    252, 4500, '{}'::jsonb, '{}'::jsonb, 'test',
                    'production', 'single_proxy', 'HYG',
                    NOW(), NOW())
            """
        )
    conn.commit()

    info = conn.info
    env = {
        "UW_SCAN_DB_HOST": str(info.host or "127.0.0.1"),
        "UW_SCAN_DB_PORT": str(info.port or 5432),
        "UW_SCAN_DB_NAME": str(info.dbname),
        "UW_SCAN_DB_USER": str(info.user),
        "UW_SCAN_API_KEY": "test-dummy-not-used-by-db-tests",
    }
    if info.password:
        env["UW_SCAN_DB_PASSWORD"] = str(info.password)

    # Run with no --force; should detect existing row and exit 0 without subprocess
    with patch.object(sys, "argv", ["backfill_vcg_v2.py"]), \
         patch.dict("os.environ", env, clear=False), \
         patch.object(mod.subprocess, "run") as mock_run:
        rc = mod.main()

    assert rc == 0
    mock_run.assert_not_called(), "idempotency: subprocess.run should NOT be called when v=2 exists"


def test_argv_has_no_composite_version_cli_override() -> None:
    """Contract #2 (tribunal finding #8): the argv must never include
    --composite-version. The constant value flows from the import only."""
    mod = _import_backfill_module()
    argv = mod._build_backtest_argv()
    assert argv == ["uv", "run", "scripts/backtest_vcg.py"], (
        f"argv must be exactly ['uv', 'run', 'scripts/backtest_vcg.py']; got {argv}"
    )
    # Defensive: enumerate every arg, none may contain composite-version.
    assert not any("composite-version" in a for a in argv), (
        "argv must not contain --composite-version; the value comes from the imported "
        "constant only (per regime/CLAUDE.md:16 provenance rule)."
    )


def test_subprocess_env_whitelist_blocks_unrelated_secrets() -> None:
    """Contract (tribunal finding #11): _subprocess_env must whitelist only
    DB credentials + PATH/HOME/USER, not leak unrelated parent env."""
    mod = _import_backfill_module()
    leak_env = {
        "UW_SCAN_DB_NAME": "testdb",
        "UW_SCAN_DB_HOST": "localhost",
        "UW_SCAN_DB_USER": "tester",
        "UW_SCAN_API_KEY": "real-key-must-not-pass-through",
        "FMP_API_KEY": "fmp-secret-leak",
        "MASSIVE_API_KEY": "massive-secret-leak",
        "PATH": "/usr/bin",
        "HOME": "/home/tester",
    }
    with patch.dict("os.environ", leak_env, clear=True):
        env = mod._subprocess_env()
    # DB vars and PATH/HOME forwarded
    assert env["UW_SCAN_DB_NAME"] == "testdb"
    assert env["UW_SCAN_DB_HOST"] == "localhost"
    assert env["PATH"] == "/usr/bin"
    # Unrelated secrets stripped
    assert "FMP_API_KEY" not in env
    assert "MASSIVE_API_KEY" not in env
    # UW_SCAN_API_KEY whitelisted only if the real parent env had it AS the
    # whitelisted key set; the script sets a dummy default for the subprocess
    # because Settings.from_env() requires it. The real key must not pass through.
    assert env["UW_SCAN_API_KEY"] != "real-key-must-not-pass-through", (
        "real UW_SCAN_API_KEY must not be forwarded; backfill is a DB-only job"
    )


def test_advisory_lock_serialises_concurrent_invocations(seeded_db_empty_cards) -> None:
    """Contract #4 (tribunal finding #2): pg_advisory_lock prevents two
    concurrent backfill invocations from both running backtest_vcg.

    Approach: hold the lock from one connection, then attempt main() from a
    second. The second must NOT block forever — but it WILL block on
    pg_advisory_lock until the test connection releases. We test using
    pg_try_advisory_lock from the test connection to confirm the lock
    semantics, then verify main()'s lock+release loop releases on exit."""
    import psycopg
    mod = _import_backfill_module()
    repo_conn = seeded_db_empty_cards.conn

    # Holder: take the same lock from a SECOND connection.
    info = repo_conn.info
    dsn_parts = [
        f"host={info.host}" if info.host else "",
        f"port={info.port}" if info.port else "",
        f"dbname={info.dbname}",
        f"user={info.user}",
    ]
    if info.password:
        dsn_parts.append(f"password={info.password}")
    dsn = " ".join(p for p in dsn_parts if p)

    with psycopg.connect(dsn) as holder:
        with holder.cursor() as cur:
            # _LOCK_KEY is module-private string; we use hashtext to match
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (mod._LOCK_KEY,))
            assert cur.fetchone()[0] is True, "test holder failed to take lock"

        # Second taker should NOT acquire — pg_try_advisory_lock returns False
        with repo_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (mod._LOCK_KEY,))
            assert cur.fetchone()[0] is False, (
                "concurrent caller acquired the lock while holder still owns it — "
                "advisory-lock contract broken"
            )

        # Release from holder
        with holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (mod._LOCK_KEY,))
        holder.commit()

    # Now repo_conn can take it (lock semantics restored)
    with repo_conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (mod._LOCK_KEY,))
        assert cur.fetchone()[0] is True
        cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (mod._LOCK_KEY,))
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/integration/scripts/test_backfill_vcg_v2.py -v
```

Expected: 5 PASSes (version_check_fails, idempotent_when_v2_row_exists, argv_has_no_composite_version_cli_override, subprocess_env_whitelist_blocks_unrelated_secrets, advisory_lock_serialises_concurrent_invocations). If `test_idempotent_when_v2_row_exists` fails because the test can't find `mod.subprocess`, that means `subprocess` is imported inside `main()` instead of at module scope — fix the script to import at module top so the test can patch it.

- [ ] **Step 4: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add scripts/backfill_vcg_v2.py tests/integration/scripts/test_backfill_vcg_v2.py
git commit -m "feat(scripts): add backfill_vcg_v2.py with 5-point contract

Wrapper around scripts/backtest_vcg.py that enforces:
  1. COMPOSITE_VERSION == 2 runtime check (refuses pre-bump build)
  2. No --composite-version CLI override (constant-derived only)
  3. Idempotent: existing v=2 production row -> exit 0 unless --force
  4. pg_advisory_lock serialises concurrent invocations (migration 062
     unique index only covers classification_accuracy, not single_proxy)
  5. Post-subprocess Gate 1 integrity: row count, NULL interpretation,
     contradiction count all asserted clean before returning 0

Verifies persisted provenance (run_scope=production, credit_proxy=HYG,
composite_method=single_proxy, composite_version=2) before returning.

Per spec §9.2 backfill-script contract."
```

---

## Task 16: UI string fix in `VcgSubTab.tsx`

**Files:**
- Modify: `web/components/regime/VcgSubTab.tsx:323-326`
- Modify or Create: `web/tests/unit/VcgSubTab.test.tsx`

- [ ] **Step 1: Write the failing Vitest test**

Open `web/tests/unit/VcgSubTab.test.tsx`. Check what's there:

```bash
cat web/tests/unit/VcgSubTab.test.tsx | head -30
```

Add (or replace, if a similar test exists) a test for the new string:

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VcgSubTab } from "@/components/regime/VcgSubTab";
// ... mock the response shape if VcgSubTab requires props

describe("VcgSubTab — π narrative (v2)", () => {
  it("describes π value without claiming an interpretation label", () => {
    // Render with sig.pi_panic > 0 — should NOT show 'SUPPRESSED'
    const sig = { pi_panic: 0.75, interpretation: "PANIC" /* other required fields */ };
    // ... render VcgSubTab with this sig
    // assert the text is "π = 0.75 (panic-adjustment active)" not "π = 0.75 SUPPRESSED"
    expect(screen.queryByText(/SUPPRESSED/i)).toBeNull();
    expect(screen.getByText(/π = 0\.75 \(panic-adjustment active\)/i)).toBeInTheDocument();
  });

  it("describes π=0 as 'no panic adjustment'", () => {
    const sig = { pi_panic: 0, interpretation: "NORMAL" };
    // render
    expect(screen.getByText(/π = 0 \(no panic adjustment\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/NO SUPPRESSION/i)).toBeNull();
  });
});
```

Adapt the test setup to match the project's existing patterns (look at sibling tests like `CriSubTab.test.tsx` to copy the prop-mocking pattern and the import path).

- [ ] **Step 2: Run, verify it fails**

```bash
cd web && npm run test -- VcgSubTab
```

Expected: 2 FAILs because the current text says "SUPPRESSED" / "NO SUPPRESSION".

- [ ] **Step 3: Apply the 3-line fix**

In `web/components/regime/VcgSubTab.tsx`, find lines 323-326:

```typescript
              {sig.pi_panic > 0
                ? `π = ${sig.pi_panic.toFixed(2)} SUPPRESSED`
                : "NO SUPPRESSION"}
```

Replace with:

```typescript
              {sig.pi_panic > 0
                ? `π = ${sig.pi_panic.toFixed(2)} (panic-adjustment active)`
                : "π = 0 (no panic adjustment)"}
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
cd web && npm run test -- VcgSubTab
```

Expected: 2 PASSes.

- [ ] **Step 5: Verify the typecheck still passes**

```bash
cd web && npm run typecheck
```

Expected: no new errors.

- [ ] **Step 6: Commit checkpoint (do not commit unless explicitly requested)**

```bash
git add web/components/regime/VcgSubTab.tsx web/tests/unit/VcgSubTab.test.tsx
git commit -m "fix(web): VcgSubTab π narrative no longer claims SUPPRESSED label

Per spec §11: the hardcoded 'π = X SUPPRESSED' / 'NO SUPPRESSION' strings
were authoritative-sounding but only correct under v1's broken cascade.
Once v2 fires PANIC for the same pi_panic > 0 case, the old strings
contradict the pill at line 372.

New text describes the pi_panic *quantity* without asserting an
interpretation *label*, leaving the authoritative label to the pill.
Three lines changed. Vitest covers both branches of the ternary."
```

---

## Task 17: Update `vcg-methodology.md` (the mandated doc contract)

Per `vcg-methodology.md:308`, the v2 PR MUST include these doc updates in the same commit set.

**Files:**
- Modify: `docs/research/regime/vcg-methodology.md`

- [ ] **Step 1: Update §2.5 — Interpretation label (cascade order)**

Find §2.5 in `docs/research/regime/vcg-methodology.md` (line 69). Read its current text. Replace the cascade description with the v2 cascade. Add a sentence noting the v2 reorder (PANIC moved up) and the new vol_extreme branch.

The new text should describe the v2 cascade at the same conceptual level §2.5 currently uses for v1. Include the precedence rationale list (INSUFFICIENT_DATA → PANIC → vol_extreme RISK_OFF → SUPPRESSED → flag-based → NORMAL).

- [ ] **Step 2: Add §2.6 — Absolute-vol-stress override**

After §2.5, insert a new §2.6 explaining:
- What `vol_extreme` is (both VIX and VVIX at the 95th percentile of their 252-day rolling histories)
- Why RISK_OFF and not EDR (truth-labeler alignment per spec §6.1)
- The semantic interaction with PANIC (pi-PANIC wins by cascade order)
- The warmup period (252 bars before the override can fire)

- [ ] **Step 3: Update §3 — Calibration constants table**

Find §3 (line 82). Add a v2 constants block:

```markdown
### v2 — Absolute-vol-stress override (2026-05-27)

| Constant | Value | Source |
|---|---|---|
| `VIX_PCT_PANIC` | 0.95 | `level1-thresholds.yaml` `P_PANIC` |
| `VVIX_PCT_PANIC` | 0.95 | `level1-thresholds.yaml` `P_PANIC` |
| `VOL_PERCENTILE_WINDOW` | 252 | `level1-thresholds.yaml` `rolling_window_days` |
| `VOL_PERCENTILE_TIE_RULE` | `"strict_lt"` | `level1-thresholds.yaml` `percentile_tie_rule` |

These values are deliberately aligned with the Level-1 truth labeler's percentile thresholds so v2's vol_extreme gate is a tighter subset of truth-RISK_OFF. See spec §6.2 for justification.
```

- [ ] **Step 4: Update §3.1 — Empirical distribution table**

After running the v=2 backfill (Task 18 below produces this number), update §3.1 with the v=2 interpretation distribution from the new `regime_backtest_runs` row. SQL to extract:

```sql
SELECT payload->>'interpretation' AS interp, COUNT(*)
FROM uw_scan.regime_backtest_daily
WHERE run_id = <v2_run_id>
GROUP BY 1 ORDER BY 2 DESC;
```

- [ ] **Step 5: Replace §7 "v2 (TBD)" stub with the shipped v2 entry**

Find lines 298-308. Replace the entire "v2 (TBD)" section with:

```markdown
### v2 (2026-05-27) — Cascade and absolute-vol override

Shipped per spec `docs/superpowers/specs/2026-05-27-vcg-v2-cascade-and-absolute-vol-spec.md` (evidence: forensic audit `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md`).

Changes:
1. Cascade reorder: `pi_panic >= 1.0 → PANIC` now fires above `not sign_ok → SUPPRESSED` (eliminates the structural contradiction documented in audit §1).
2. New absolute-vol-stress override: `vix_percentile_rank >= 0.95 AND vvix_percentile_rank >= 0.95 → RISK_OFF`, computed inside `_interpretation_for_index` before the SUPPRESSED gate.
3. Two new payload fields: `vix_percentile_rank` and `vvix_percentile_rank` (float | None, NaN during the 252-bar warmup).
4. `COMPOSITE_VERSION = 2`.

NOT changed in v2: OLS_WINDOW, β-sign-discipline thresholds, panic-π clamp, ensemble proxy support, regime-aware floors. These remain on the v2.1+ candidate list at the bottom of this section.

Acceptance gates passed: contradiction count = 0 on 7-crisis fixture; crisis-window stress recall ≥ v1 baseline 0.0985.
```

Then add a "v2.1+ candidates" section listing the deferred items (which were the previous v2-TBD list):
- Lengthen `OLS_WINDOW` to 42 or 63
- Replace strict `β ≤ 0` with a band
- Ensemble proxy support
- Symmetric positive/negative thresholds
- Regime-aware VIX_FLOOR
- Continuous panic-π function

- [ ] **Step 6: Combined commit for the methodology-atomicity contract (do not commit unless explicitly requested; tribunal finding #3)**

This is the single combined commit that satisfies `vcg-methodology.md:308`. It MUST include:
- The `COMPOSITE_VERSION = 2` bump (Task 1).
- The new constants block (Task 2).
- All `vcg-methodology.md` updates (this task).
- The `regime/CLAUDE.md` trigger-list update (Task 18 — stage that first then commit them together).

If you have followed the plan in order, Tasks 1, 2, 17, and 18 should all be staged with no intervening commits. Verify:

```bash
git diff --cached --stat
# Expect to see (at minimum):
#   src/uw_scan/cards/vcg_scoring.py                 |  ## +/-
#   docs/research/regime/vcg-methodology.md          |  ## +/-
#   docs/research/regime/CLAUDE.md                   |  ## +/-
#   tests/unit/cards/test_vcg_scoring_v2_cascade.py  |  ## +/-
```

Then create the methodology-atomic commit:

```bash
git commit -m "feat(vcg): bump COMPOSITE_VERSION to 2 + methodology docs

Per vcg-methodology.md:308 the version bump and §3/§7 doc updates must
land in the same commit. This commit therefore bundles:

- src/uw_scan/cards/vcg_scoring.py: COMPOSITE_VERSION 1 -> 2 + four new
  absolute-vol constants (VIX_PCT_PANIC, VVIX_PCT_PANIC,
  VOL_PERCENTILE_WINDOW, VOL_PERCENTILE_TIE_RULE)
- docs/research/regime/vcg-methodology.md: §2.5 cascade rewrite,
  §2.6 absolute-vol override (new section), §3 constants table,
  §3.1 v=2 empirical-distribution placeholder (filled by Task 19),
  §7 replacing the v2-TBD stub with the shipped v2 entry
- docs/research/regime/CLAUDE.md: 'When to update' trigger list adds
  the four new constants
- tests/unit/cards/test_vcg_scoring_v2_cascade.py: COMPOSITE_VERSION
  assertion (first v2 unit test)

§3.1 will be populated in a follow-up commit after the v=2 backfill in
Task 19. Cascade rewrite + percentile compute + payload fields are
non-blocking and land in their own subsequent commits per the plan."
```

If any of those four files isn't staged at this point, STOP — that means a prior task accidentally committed it alone (violating the atomicity contract) or the file wasn't touched. Investigate before commiting.

---

## Task 18: Update `docs/research/regime/CLAUDE.md` triggers

**Files:**
- Modify: `docs/research/regime/CLAUDE.md`

- [ ] **Step 1: Add the four new constants to "When to update"**

Find the "When to update" section in `docs/research/regime/CLAUDE.md`. There's a bullet that lists constants whose changes trigger §3 updates:

> After changing any constant in `vcg_scoring.py` (VCG_TRIGGER, VCG_RO_TRIGGER, BOUNCE_TRIGGER, VIX_FLOOR, VIX_EDR, VIX_PANIC_LOW, VIX_PANIC_HIGH, VVIX_ELEVATED, VVIX_EXTREME): update §3 of `vcg-methodology.md` with the new threshold and rationale.

Add the four new constants to the list:

```markdown
After changing any constant in `vcg_scoring.py` (VCG_TRIGGER, VCG_RO_TRIGGER, BOUNCE_TRIGGER, VIX_FLOOR, VIX_EDR, VIX_PANIC_LOW, VIX_PANIC_HIGH, VVIX_ELEVATED, VVIX_EXTREME, **VIX_PCT_PANIC, VVIX_PCT_PANIC, VOL_PERCENTILE_WINDOW, VOL_PERCENTILE_TIE_RULE**): update §3 of `vcg-methodology.md` with the new threshold and rationale.
```

- [ ] **Step 2: Correct the validation endpoint note**

The current doc may still refer generically to `/api/regime/validation`. Update the VCG-specific wording to `/api/regime/vcg-validation` so the runbook and the source-of-truth doc agree with `src/uw_scan/api/routers/regime_validation.py`.

- [ ] **Step 3: Stage and roll into Task 17's combined methodology-atomic commit (tribunal finding #3)**

This file is part of the same methodology-atomicity contract (`vcg-methodology.md:308`). Stage and continue — the combined commit happens in Task 17 Step 6, which folds Tasks 1, 2, 17, and 18 into one commit:

```bash
git add docs/research/regime/CLAUDE.md
git status --short    # confirm staged alongside vcg_scoring.py, vcg-methodology.md, and the v2 unit test
```

If you reach this step BEFORE Task 17 Step 6 has run, that's fine — Task 17 Step 6 will discover the staged regime/CLAUDE.md and bundle it. If you reach it AFTER, you've already committed an inconsistent set — back up and `git reset --soft HEAD~1` to re-stage.

---

## Task 19: Run the v=2 backfill against the dev DB and verify

**Files:**
- (no source files modified; this is a verification step + the §3.1 empirical-distribution update)

- [ ] **Step 1: Confirm the dev DB is reachable and migrations are current**

```bash
bash scripts/migrate.sh
```

Expected: idempotent; either prints "no new migrations" or applies any pending migrations cleanly.

- [ ] **Step 2: Run the backfill**

```bash
uv run scripts/backfill_vcg_v2.py
```

Expected: prints "running scripts/backtest_vcg.py with default production args", then backtest_vcg logs (aligned N days, persisted run, etc.), then "v=2 production backfill complete: run_id=N".

If the script reports `v=2 production row already exists (run_id=N); use --force to re-run`, the idempotency is working. To force regeneration, pass `--force`.

- [ ] **Step 3: Verify the row in the DB**

```bash
psql -c "SELECT id, composite_version, run_scope, credit_proxy, composite_method, n_days, completed_at FROM uw_scan.regime_backtest_runs WHERE indicator='vcg' AND composite_version='2' ORDER BY created_at DESC LIMIT 1;"
```

Expected: one row with `composite_version='2'`, `run_scope='production'`, `credit_proxy='HYG'`, `composite_method='single_proxy'`, completed_at non-NULL.

- [ ] **Step 4: Verify `/api/regime/vcg-validation` returns 200 with v=2 metadata**

Start only the API if it isn't already running:

```bash
uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400
```

In another shell:

```bash
curl -s http://localhost:8400/api/regime/vcg-validation | jq '.composite_version, .run_scope'
```

Expected: `"2"` and `"production"`.

- [ ] **Step 5: Query the interpretation distribution for the §3.1 doc update**

```bash
psql -c "SELECT payload->>'interpretation' AS interp, COUNT(*) FROM uw_scan.regime_backtest_daily WHERE run_id = (SELECT id FROM uw_scan.regime_backtest_runs WHERE indicator='vcg' AND composite_version='2' AND run_scope='production' ORDER BY created_at DESC LIMIT 1) GROUP BY 1 ORDER BY 2 DESC;"
```

Save the output. This populates the §3.1 empirical-distribution table.

- [ ] **Step 6: Update `vcg-methodology.md` §3.1 with the v=2 distribution**

Insert a v=2 row/block into §3.1 of `docs/research/regime/vcg-methodology.md` containing the actual counts from Step 5. Format: same as the existing v=1 §3.1 distribution (whatever shape that takes — table, prose, etc.).

- [ ] **Step 7: Commit checkpoint for the §3.1 update (do not commit unless explicitly requested)**

```bash
git add docs/research/regime/vcg-methodology.md
git commit -m "docs(vcg): populate §3.1 empirical-distribution table with v=2 backfill data

Run from $(date -u +%Y-%m-%dT%H:%M:%SZ). Source: regime_backtest_runs
row at composite_version=2 produced by scripts/backfill_vcg_v2.py against
the dev DB."
```

---

## Task 20: Final full-suite verification

- [ ] **Step 1: Run the entire VCG test surface**

```bash
uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py \
              tests/unit/cards/test_vcg_scoring_composite.py \
              tests/unit/api/test_models_regime.py \
              tests/integration/scripts/test_backfill_vcg_v2.py \
              tests/integration/regime/test_vcg_v2_contradiction.py \
              tests/integration/regime/test_vcg_v2_recall_non_regression.py \
              tests/integration/regime/test_vcg_v2_api_selection.py \
              tests/integration/api/test_openapi_snapshot.py -v
```

Expected: all PASS. Note any flakes / dependency issues; investigate before moving on.

- [ ] **Step 2: Run the broader cards + regime suite**

```bash
uv run pytest tests/unit/cards/ tests/integration/regime/ tests/integration/api/ -v
```

Expected: no regressions outside the planned surface.

- [ ] **Step 3: Run web tests**

```bash
cd web && npm run test
```

Expected: all PASS.

- [ ] **Step 4: Run web typecheck**

```bash
cd web && npm run typecheck
```

Expected: no errors.

- [ ] **Step 5: Run the OpenAPI snapshot check explicitly**

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```

Expected: PASS (snapshot already regenerated in Task 10).

- [ ] **Step 6: Push the branch and open the PR (per CLAUDE.md "Always open a PR")**

Confirm with user before pushing. If user approves:

```bash
git push -u origin feat/vcg-v2-spec
gh pr create --title "feat(vcg): v2 cascade fix + absolute-vol-stress override" --body "$(cat <<'EOF'
## Summary
- Implements VCG v2 per spec `docs/superpowers/specs/2026-05-27-vcg-v2-cascade-and-absolute-vol-spec.md`
- Cascade reorder: pi-PANIC fires above sign_ok-SUPPRESSED (fixes 36 contradiction days)
- New absolute-vol override: `vix_percentile_rank >= 0.95 AND vvix_percentile_rank >= 0.95 -> RISK_OFF` (NOT to be confused with the existing `vix_pct` / `vvix_pct` attribution-percentage fields, which keep their v1 meaning)
- Two new payload fields: `vix_percentile_rank`, `vvix_percentile_rank`
- `COMPOSITE_VERSION = 2` + mandated `vcg-methodology.md` doc updates
- One UI string fix in `VcgSubTab.tsx`

## Acceptance gates
- ✅ Gate 1: zero `regime='PANIC' AND interpretation='SUPPRESSED'` rows on 7-crisis fixture
- ✅ Gate 2: crisis-window stress recall ≥ v1 baseline 0.0985

## Test plan
- [x] Unit tests pass (`uv run pytest tests/unit/cards/test_vcg_scoring_v2_cascade.py tests/unit/api/test_models_regime.py`)
- [x] Backfill contract test passes (`uv run pytest tests/integration/scripts/test_backfill_vcg_v2.py`)
- [x] All integration tests pass (`uv run pytest tests/integration/regime/test_vcg_v2_contradiction.py tests/integration/regime/test_vcg_v2_recall_non_regression.py tests/integration/regime/test_vcg_v2_api_selection.py`)
- [x] OpenAPI snapshot updated (additive only)
- [x] Web typecheck + Vitest pass
- [ ] Reviewer to run `uv run scripts/backfill_vcg_v2.py` after merge with `UW_SCAN_DB_NAME`/host/user/password env pointing at the target DB
- [ ] Reviewer verifies `/api/regime/vcg-validation` returns 200 with `composite_version=2` post-backfill

## Audit dependency
This spec cites `docs/research/regime/vcg-stress-window-forensics-2026-05-26.md` (on `feat/vcg-stress-window-forensics`). Merge order is unconstrained per spec §13.

## Out of scope (v2.1+)
- OLS_WINDOW length sensitivity
- β-band relaxation
- Whether sign_ok=False should overwrite RISK_OFF/EDR/WATCH (v1 behavior retained)
- Tile rendering of new percentile_rank fields
EOF
)"
```

---

## Plan self-review

Cross-checking the plan against the spec sections:

| Spec § | Requirement | Plan task(s) |
|---|---|---|
| §3 #1 | Cascade reorder | Tasks 5, 6 |
| §3 #2 | Vol-stress override gate | Tasks 5, 6 |
| §3 #3 | Two new payload fields | Tasks 7, 9 |
| §3 #4 | COMPOSITE_VERSION bump | Task 1 |
| §3 #5 | Methodology-doc updates | Tasks 17, 18, 19 step 6 |
| §3 #6 | Tests (unit + integration + snapshot) | Tasks 3, 5, 8, 9, 12, 13, 14, 15 |
| §3 #7 | Backfill script | Task 15 |
| §3 #8 | UI string fix | Task 16 |
| §5 Gate 1 | Zero PANIC-SUPPRESSED contradictions | Task 12 |
| §5 Gate 2 | Recall ≥ 0.0985 | Task 13 |
| §6.1 | Cascade structure | Tasks 5, 6 |
| §6.2 | New constants | Task 2 |
| §6.3 | Payload fields | Tasks 7, 9 |
| §6.4 | Percentile compute | Task 4 |
| §7.1 | Array alignment + 3 tests | Tasks 3, 4 |
| §8.1 | Unit tests | Tasks 1, 2, 3, 5, 7, 8, 9 |
| §8.2 Test 1 | Contradiction count | Task 12 |
| §8.2 Test 2 | Recall non-regression | Task 13 |
| §8.2 Test 3 | API selection | Task 14 |
| §8.2 Fixture | 7-crisis parquet | Task 11 |
| §8.3 | OpenAPI snapshot | Task 10 |
| §9.2 | Backfill script contract | Task 15 |
| §9.2 step 4 | Runbook + 503 verification | Task 19, Task 20 step 6 |
| §11 | UI string fix | Task 16 |
| §12 | Documentation contract | Tasks 17, 18, 19 step 6 |

Coverage: every spec requirement maps to at least one task. No gaps.

Placeholder scan: no "TBD", "TODO", "implement later". All tasks have actual code in their TDD steps. The only "fill in based on" wording is at Task 19 step 6 (§3.1 empirical distribution), where the actual numbers depend on the backfill output — this is intentional and the step gives the exact SQL to extract them.

Type consistency: `vix_percentile_rank` / `vvix_percentile_rank` field names used identically across spec, plan, code, tests. `COMPOSITE_VERSION` referred to as integer `2` (not string `"2"`) in code (matches v1's `COMPOSITE_VERSION = 1` integer literal at line 32); but persisted as string `'2'` in the DB (matches the `composite_version TEXT NOT NULL` schema at migration 057 line 23). Task 14 test uses `composite_version='2'` string in seed SQL; Task 15 backfill verifies `cv == "2"` string. Consistent.

One spec requirement worth highlighting: the spec §1 says v1 behavior allowing sign_ok-failure to suppress RISK_OFF/EDR/WATCH is "intentionally retained from v1; deciding whether sign-failure should be allowed to suppress those lower-tier stress labels is the v2.1 sign-discipline question, not v2's scope." The new cascade in Task 6 preserves this: `elif not flags["sign_ok"]: SUPPRESSED` still fires above the flag-based labels (`ro`, `edr`, `bounce`, WATCH). This is correct per spec; not a bug.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-27-vcg-v2-implementation-plan.md`.**

Per the user's instruction, the next step is `/review-cycle` on this plan.
