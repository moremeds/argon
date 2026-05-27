# Canary v2-A — Vol/Speed Separation — Design Spec

**Date**: 2026-05-27
**Status**: design — implementation plan not yet started
**Author intent**: research-only PR that produces evidence for a future production flip. PR 1 ships zero production change; PR 2 (separate) performs the flip if pre-committed acceptance criteria pass.
**Parent docs**:
- `docs/research/regime/canary-5yr-executive-summary.md` (§10 v2-A — original motivation; §13 form-sweep verdict — strengthening evidence)
- `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md` (v1 spec — the artifact this proposes to replace)
- `docs/superpowers/specs/2026-05-27-canary-form-sweep-full-design.md` (form-sweep spec — the immediately preceding research run; this spec re-uses its multi-layer invisibility pattern)
- GitHub issue #89 (v2-A)
- Related: issue #90 (v2-C — band/ordinal redesign, independent track)

---

## TL;DR

The v1 canary composite folds a discrete "speed" leg (`0 / 8 / 20` points keyed on `CONFIRMED_CANARY_ACTIVE` / `NEUTRAL` / `BUY_THE_DIP_ACTIVE` state) into the additive raw score. Two independent measurements now agree that the speed term is **net-negative for rank prediction**:

1. **PR #83 walk-forward**: `vol_only` AUC ≥ `composite` AUC at every horizon × every subset, across 6 walk-forward windows.
2. **PR #88 form-sweep** (full 15-year history): the vol-only-vs-composite gap at 60d AUC is **+0.020 to +0.027** across all four score forms — the gap is structural to the formula, not a ramp-curvature artifact.

**v2-A proposes** to remove the additive `speed.score` term from the composite formula while preserving the `apply_cap()` mechanism (which uses `speed.state`, not `speed.score`, to clamp the score during CCA events). Speed remains user-facing as a separate state field, not as a rank contributor.

This spec covers **PR 1 only** (research-only): build v2 formula behind a `composite_version >= 2` conditional in `run_analysis()`, run backfill + walk-forward + robustness at `composite_version=2` with `run_scope='research'` and `composite_version=2` snapshots, render a v1-vs-v2 comparison report, and persist pre-committed acceptance criteria for PR 2 (the eventual flip).

**Scope budget**: ~250–350 LOC new code across 1 modified source file (`canary_scoring.py` — 4-line conditional), 1 new calibration JSON, 2 modified scripts (`canary_backfill.py`, `backtest_canary.py`), 1 new renderer module (`regime_canary_v1_v2_compare.py`), 4 new test files. Plus a one-time research backfill of ~3,843 days at `composite_version=2`. ~15-25s of new test runtime.

**This PR does not** flip production. PR 2 does that, gated on AC-F1..F6 in §8.

---

## 1. Motivation

### What PR #83 and PR #88 told us about speed

PR #83 (v1 canary, ship date 2026-05-26) made the speed term part of the additive composite for honest design reasons: speed encodes a state machine (CCA → cap @49; BTD → +20 rank boost) and the original spec wanted that state to *bias* the rank, not just gate the cap.

The walk-forward result (§10 v2-A of the exec summary) immediately complicated that bet: vol-only AUC dominated composite AUC at every horizon. PR #83 deferred the question to v2 with the working hypothesis that the AUC gap was either (a) noise from the train-vs-test mismatch, or (b) a calibration-vintage artifact (the original speed weights came from priors, not optimization).

PR #88 (form-sweep, 2026-05-27) tested whether the AUC gap was a **ramp-curvature** artifact — i.e., would non-linear score forms recover the lost AUC? It tested all 4 supported forms over the full 15-year backfilled history and recorded:

| Form    | Composite 60d AUC | Vol-only gap (60d) |
|---------|------------------:|-------------------:|
| linear  |             0.619 |             +0.023 |
| convex  |             0.608 |             +0.027 |
| concave |             0.628 |             +0.020 |
| sigmoid |             0.627 |             +0.025 |

The vol-only gap survives every form. **The penalty is structural to including speed in the rank, not curvature-induced.** That falsifies hypothesis (b) and exhausts the cheap fixes.

### Why v2-A is now the strongest track

After PR #88's negative result, the project's v2 roadmap was reranked (exec summary §10 v2-A): v2-A was **promoted to the top of the queue**, v2-B (lower STRONG_BUY threshold) was held pending v2-C band semantics, and v2-C (score-form change) was **reframed** to band/ordinal redesign (issue #90).

v2-A is the only v2 lever that:
- has independent empirical support across two PRs and four score forms;
- can be tested with a small structural code change (one 4-line conditional);
- does not require redesigning band semantics (separable from v2-C);
- preserves all v1 invariants the production users currently depend on (cap mechanism, warning_state field, scoring scaffold).

### Why this PR is research-only

PR #88 established the **research-first, decide-later** pattern: build the candidate in a research-scoped surface, look at the empirical result, then decide whether to flip production. This pattern caught one wrong cheap fix (form-sweep) before it shipped. Applying the same pattern to v2-A buys us the same safety with the same overhead. The OOS gate (`test_canary_oos_gate.py`) remains the production-stability anchor; PR 2's flip will replace `LAST_KNOWN_AUC_v1_*` with `LAST_KNOWN_AUC_v2_*` constants derived from this PR's output.

---

## 2. Goals and non-goals

### Goals

- **G1.** Implement the v2 formula `raw = tactical + structural` (no additive speed) behind a `composite_version >= 2` conditional in `run_analysis()`, with the v1 path `raw = tactical + structural + speed.score` preserved unchanged for `composite_version=1`.
- **G2.** Produce a research-scoped backfill of `canary_snapshots` at `composite_version=2` over the full backfilled history (2011-02-08 → 2026-05-21, 3,843 rows).
- **G3.** Produce research-scoped walk-forward (6 windows, same as v1) and robustness runs at `composite_version=2` in `regime_backtest_runs` with `run_scope='research'`.
- **G4.** Produce a pure-function renderer that prints a v1-vs-v2 side-by-side comparison table loaded from cross-scope DB queries.
- **G5.** Lock in pre-committed acceptance criteria AC-F1..F6 (§8) that PR 2 will gate against. The spec is the *contract* for PR 2's eligibility.
- **G6.** Preserve the v1 production surface bit-identically: zero change to `CANARY_COMPOSITE_VERSION`, `load_calibration()`, `LAST_KNOWN_AUC_v1_*`, web/types.ts, or any UI component.

### Non-goals

- **NG1.** No production flip. `CANARY_COMPOSITE_VERSION` stays at 1.
- **NG2.** No band threshold changes (those are v2-C territory; issue #90).
- **NG3.** No `STRONG_BUY` threshold change (v2-B; subsumed by v2-C direction 2).
- **NG4.** No `apply_cap()` rewrite — speed.state still vetoes via the cap mechanism. Removing the cap is a separate v3 question.
- **NG5.** No UI changes, no API schema regen, no `web/lib/types.ts` regen. PR 2 owns all of that.
- **NG6.** No new score form. Form is fixed at `linear` (per form-sweep verdict).
- **NG7.** No methodology document rewrite. The exec summary §10 v2-A and this spec are sufficient documentation for PR 1. Methodology updates happen in PR 2 alongside the flip.
- **NG8.** No new `summary.is_winning_form` semantics. v2-A is not a winning-form competition; it's a binary hypothesis test (does removing speed help?).

---

## 3. Scope summary

| In scope (PR 1, this PR) | Out of scope (PR 2 or later) |
|---|---|
| `canary_scoring.py` conditional path on `composite_version` | `CANARY_COMPOSITE_VERSION = 2` constant flip |
| New `docs/research/regime/canary-calibration-v2.json` | `load_calibration()` retarget to v2.json |
| `--composite-version {1,2}` flag in `canary_backfill.py` | New `LAST_KNOWN_AUC_v2_*` OOS gate constants |
| `--v1-v2-compare` mode in `backtest_canary.py` | UI changes (CanarySubTab, CanaryValidationPanel) |
| New `regime_canary_v1_v2_compare.py` renderer | API schema regen + `web/lib/types.ts` regen |
| Research walk-forward + robustness at v2 (`run_scope='research'`) | Methodology document rewrite |
| Research backfill at `composite_version=2` (snapshots invisible to prod) | `apply_cap()` rewrite |
| Pre-committed AC-F1..F6 in §8 of this spec | Band threshold re-tuning |
| 4 new test files (unit + integration) | Capitulation scorer (v2-D, separate research thread) |

---

## 4. Schema dependencies (load-bearing invariants this PR depends on)

| # | Invariant | Where it's encoded | Why this PR depends on it |
|---|---|---|---|
| 1 | `canary_snapshots.composite_version` is a column (int) | Migration 056 / canary_snapshot_repository.py | Lets v2 rows coexist with v1 rows in the same table |
| 2 | `canary_snapshot_repository.fetch_latest(composite_version=...)` filters by that column | `src/uw_scan/storage/canary_snapshot_repository.py` | Production `fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)` (hardcoded to 1) sees no v2 rows |
| 3 | `regime_backtest_runs.run_scope` is a column with values in {'production', 'research'} | Migration 057 / regime_backtest_repository.py | Lets v2 walk-forward rows be invisible to `find_latest_run`'s production default |
| 4 | `find_latest_run(...)` defaults `run_scope='production'` (keyword-only arg) | `src/uw_scan/storage/regime_backtest_repository.py:152-153` | Production paths see only v1 runs |
| 5 | `apply_cap(raw, speed, ...)` uses `speed.state`, not `speed.score`, to decide capping | `src/uw_scan/cards/canary_scoring.py:441-462` | v2 can drop the additive speed.score term without breaking the cap mechanism |
| 6 | `Calibration.composite_version: int` field exists on the dataclass | `src/uw_scan/cards/canary_calibration.py:37` | v2 calibration JSON parses without code change to the loader |
| 7 | `RegimeBacktestRepository.delete_runs_by_batch_id` (added in PR #88) scopes to `indicator='canary' AND run_scope='research'` | `src/uw_scan/storage/regime_backtest_repository.py` | Cleanup-on-failure pattern reused by v2 backfill + walk-forward |
| 8 | `composite_version: Literal[1, 2, 3]` already exists in the API schema | `src/uw_scan/api/schemas.py:249` | v2 rows would deserialize without schema change (relevant only after PR 2) |

If any of these invariants drift before PR 2, the flip cannot proceed without spec amendment.

---

## 5. Design

### 5.1 Architecture

```
                    ┌───────────────────────────────────────────────────┐
                    │ docs/research/regime/canary-calibration-v2.json   │
                    │   - same 5 vol-scorer thresholds as v1            │
                    │   - composite_version: 2                          │
                    │   - score_form: "linear" (form-sweep verdict)     │
                    └────────────────────────┬──────────────────────────┘
                                             │
                                             ▼
                    ┌───────────────────────────────────────────────────┐
                    │ run_analysis(calibration)                         │
                    │   tactical = s_spike + s_back                     │
                    │   structural = s_vrp + s_cor + s_vvr              │
                    │   speed = derive_speed(...)                       │
                    │   if calibration.composite_version >= 2:          │
                    │       raw = tactical + structural    ← v2 formula │
                    │   else:                                           │
                    │       raw = tactical + structural + speed.score   │
                    │   raw = max(0.0, min(100.0, raw))                 │
                    │   cap = apply_cap(raw, speed, ...) ← unchanged    │
                    │   band = compute_band(cap.final_score)            │
                    └────────────────────────┬──────────────────────────┘
                                             │
                                             ▼
                    ┌───────────────────────────────────────────────────┐
                    │ canary_snapshots                                  │
                    │   - composite_version=1 rows (v1 production)     │
                    │   - composite_version=2 rows (v2 research)        │
                    └────────────────────────┬──────────────────────────┘
                                             │
                       ┌─────────────────────┴────────────────────┐
                       ▼                                          ▼
            production API path                       backtest_canary.py
            fetch_latest(version=                     --walk-forward
              CANARY_COMPOSITE_VERSION=1)             --composite-version 2
              → sees only v1 rows                     → research-scoped runs
                                                          │
                                                          ▼
                                              regime_backtest_runs
                                                run_scope='research'
                                                composite_version='2'
                                                          │
                                                          ▼
                                              backtest_canary.py
                                              --v1-v2-compare
                                                loads v1 (production)
                                                  + v2 (research)
                                                          │
                                                          ▼
                                              render_canary_v1_v2_compare
                                                side-by-side table +
                                                AC-F1..F6 evaluation +
                                                "What this run does NOT
                                                 decide" footer
                                                          │
                                          ┌───────────────┴───────────────┐
                                          ▼                               ▼
                                  ALL AC PASS                       ANY AC FAIL
                                          │                               │
                                          ▼                               ▼
                                  PR 2: flip production           STOP. v2-A is wrong.
                                  (CANARY_COMPOSITE_VERSION=2,    Record verdict in
                                   regen types, update UI,        exec summary §13.
                                   set LAST_KNOWN_AUC_v2_*)       File follow-up issue.
```

### 5.2 File layout

| File | New / Modified | LOC delta | Purpose |
|---|---|---:|---|
| `src/uw_scan/cards/canary_scoring.py` | Modified | +6 / -1 | 4-line conditional in `run_analysis()`. The v1 path is preserved by `else:` — v1 production behavior is bit-identical. |
| `docs/research/regime/canary-calibration-v2.json` | New | ~16 | Same 5 vol-scorer thresholds as v1, `composite_version: 2`, `score_form: "linear"`, `produced_at` timestamp. Not loaded by production. |
| `scripts/canary_backfill.py` | Modified | +25 | Add `--composite-version {1,2}` flag (default 1). When 2, loads `canary-calibration-v2.json` and writes `composite_version=2` rows to `canary_snapshots`. |
| `scripts/backtest_canary.py` | Modified | +60 | Add `--v1-v2-compare` mode. Loads v1 walk-forward runs from production scope + v2 walk-forward runs from research scope, passes both to renderer. Add `--composite-version {1,2}` flag for walk-forward to choose which version's snapshots to read. |
| `src/uw_scan/reports/regime_canary_v1_v2_compare.py` | New | ~180 | Pure-function renderer `render_canary_v1_v2_compare(v1_runs, v2_runs) -> str`. Side-by-side table + AC-F1..F6 evaluation lines + footer. CLI entry for re-render-without-recompute. |
| `tests/unit/test_canary_v2_formula.py` | New | ~80 | v1 calibration adds speed; v2 calibration drops speed; cap still uses `speed.state`; both paths agree on `tactical` and `structural` values. |
| `tests/unit/test_canary_v1_v2_compare_renderer.py` | New | ~200 | Canonical row ordering, missing-version guards, AC evaluation rules (one test per AC-F1..F6), footer present, none-fallback. |
| `tests/integration/regime/test_canary_v2_backfill.py` | New | ~150 | `canary_backfill --composite-version 2` writes v2 rows; production `fetch_latest(version=1)` returns no v2 rows; v2 rows have `composite_version=2`; cleanup-on-failure scopes to v2 rows only. |
| `tests/integration/regime/test_canary_v2_walk_forward.py` | New | ~250 | Walk-forward at v2 persists with `run_scope='research'`; v1 walk-forward production rows untouched; cross-scope renderer load works; `LAST_KNOWN_AUC_v1_*` OOS gate still passes; AC-F1..F6 evaluator logic. |

### 5.3 The actual code change

```python
# src/uw_scan/cards/canary_scoring.py — inside run_analysis()
# Before (current v1):
speed = derive_speed(
    confirmed_canary_active=confirmed_canary_active,
    buy_the_dip_active=buy_the_dip_active,
)
raw = tactical + structural + speed.score
raw = max(0.0, min(100.0, raw))

# After (v1 + v2 conditional):
speed = derive_speed(
    confirmed_canary_active=confirmed_canary_active,
    buy_the_dip_active=buy_the_dip_active,
)
if calibration.composite_version >= 2:
    # v2-A: speed is context only. apply_cap() still uses speed.state below.
    raw = tactical + structural
else:
    raw = tactical + structural + speed.score
raw = max(0.0, min(100.0, raw))
```

The `apply_cap(raw_score=raw, speed=speed, ...)` call on the next line is unchanged. It reads `speed.state` (an enum) to decide whether to clamp `raw` at 49.

### 5.4 Calibration JSON v2

```json
{
  "composite_version": 2,
  "train_window": {"start": "2007-01-01", "end": "2014-12-31"},
  "score_form": "linear",
  "thresholds": {
    "vix_spike_revert":     {"floor": 0.05, "ceiling": 0.30, "spike_active_at_vix": 30.0, "peak_lookback_d": 10, "max_points": 15},
    "vix_vix3m_back":       {"floor": 0.05, "ceiling": 0.20, "backwardation_extreme_at_ratio": 1.05, "peak_lookback_d": 10, "max_points": 15},
    "vrp":                  {"floor": 50.0,  "ceiling": 300.0, "rv_window_d": 20, "max_points": 21},
    "cor1m_decay":          {"floor": 0.05, "ceiling": 0.30, "peak_elevated_at": 60.0, "peak_lookback_d": 60, "max_points": 17},
    "vvix_vix_recovery":    {"floor": 3.5,  "ceiling": 5.0,  "compressed_below_ratio": 4.0, "compress_lookback_d": 60, "max_points": 12}
  },
  "band_distribution_train": null,
  "author_overrides": [],
  "produced_at": "2026-05-27T00:00:00Z",
  "produced_by": "v2-A vol/speed separation (PR for issue #89)"
}
```

**Note**: thresholds and `score_form` are identical to v1. The only changes are `composite_version` (1→2) and `produced_at` / `produced_by` provenance fields. This is deliberate: v2-A tests a **structural formula change** with the v1 calibration held fixed, so that any AUC change is attributable to the formula change, not to threshold drift.

### 5.5 CLI changes

```bash
# canary_backfill.py — new flag
uv run python scripts/canary_backfill.py --days 4000 --composite-version 2
#   loads canary-calibration-v2.json, writes composite_version=2 rows

# backtest_canary.py — new flag + mode
uv run python scripts/backtest_canary.py --walk-forward --composite-version 2
#   runs walk-forward against composite_version=2 snapshots,
#   persists with run_scope='research' and summary.composite_version='2'

uv run python scripts/backtest_canary.py --v1-v2-compare
#   loads v1 production walk-forward runs + v2 research walk-forward runs,
#   renders side-by-side table, prints AC-F1..F6 evaluation lines

# Standalone re-render (no recompute):
uv run python -m uw_scan.reports.regime_canary_v1_v2_compare
#   reads latest production v1 + latest research v2, re-renders
```

`--composite-version 2` is mutually-exclusive with `--calibrate` and `--form-sweep` and `--form-sweep-full` (the spec records calibration version explicitly). The renderer mode `--v1-v2-compare` is mutually-exclusive with all other modes.

### 5.6 Persistence model

| Table | New rows added by this PR | Coexistence with v1 | Visibility to production |
|---|---|---|---|
| `canary_snapshots` | ~3,843 rows with `composite_version=2`, `score_form='linear'` | Sits alongside ~3,843 v1 rows (`composite_version=1`) with the same `data_date` values | **Invisible** — `fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)` is hardcoded to 1; `composite_version=2` rows never returned to production queries |
| `regime_backtest_runs` | 6 walk-forward rows + 1 robustness row, all with `run_scope='research'`, `composite_version='2'`, `indicator='canary'` | Sits alongside PR #83's 6 walk-forward + 1 robustness production rows | **Invisible** — `find_latest_run(...)` defaults to `run_scope='production'`; research rows never returned to production queries |
| `regime_backtest_daily` | ~23,000 rows (6 walk-forward windows × ~3,800 days), all attached to research-scoped runs | Sits alongside PR #83's production-scoped daily rows | **Invisible via FK** — production queries join through `regime_backtest_runs` which already filters by `run_scope` |

### 5.7 Renderer (`regime_canary_v1_v2_compare.py`)

Pure function, no I/O. Mirrors the form-sweep renderer pattern:

```python
def render_canary_v1_v2_compare(v1_runs: list[dict], v2_runs: list[dict]) -> str:
    """Render v1-vs-v2 side-by-side comparison + AC-F1..F6 evaluation.

    Inputs:
      v1_runs: list of regime_backtest_runs row dicts with composite_version='1'
               and run_scope='production'. Must include at least one walk-forward run.
      v2_runs: same shape, composite_version='2', run_scope='research'.

    Output: multi-section markdown:
      - Header: window, composite versions, batch ids
      - Side-by-side AUC table (5d / 20d / 60d × composite / vol_only / speed_only)
      - Band distribution comparison
      - Per-window comparison (6 walk-forward windows)
      - AC-F1..F6 evaluation block (one line per AC: PASS / FAIL with delta)
      - Verdict: SHIP / STOP
      - Fixed footer: "What PR 2 will do iff this verdict is SHIP"

    Raises ValueError if:
      - v1_runs or v2_runs is empty
      - v1_runs contains any composite_version != 1 or run_scope != 'production'
      - v2_runs contains any composite_version != 2 or run_scope != 'research'
      - the two run sets do not cover the same walk-forward windows
    """
```

The renderer evaluates each of AC-F1..F6 inline against the input runs and prints a per-AC verdict line. The overall verdict (SHIP / STOP) is the AND of all 6 ACs.

### 5.8 Error handling (cleanup-on-failure)

Same atomic pattern as PR #88 form-sweep:

- **Backfill failure** mid-run: `canary_backfill.py` runs inside a single transaction per day; on exception, the partial day is rolled back. After all days are persisted, mark backfill complete in `canary_backfill_status`. On full-run failure, the operator runs `DELETE FROM canary_snapshots WHERE composite_version = 2` to roll back the batch. (We do not add a new repo method for this — explicit DELETE is the documented recovery, since v2 snapshots are isolatable by `composite_version` column alone.)
- **Walk-forward failure**: existing `delete_runs_by_batch_id(batch_id)` repo method from PR #88 covers this. The batch_id is a UUID4 generated per walk-forward invocation. On exception, rollback + `delete_runs_by_batch_id` runs in the same exception handler, with original exception preserved (Python last-raise-wins discipline — PR #88 §3.4).
- **Renderer failure** (e.g., missing v1 runs in DB): renderer raises `ValueError` with a specific message. No DB state to clean up — renderer is pure.

---

## 6. Multi-layer invisibility (the same 5-layer defense as PR #88)

| Layer | Mechanism for v2-A | What it prevents |
|---|---|---|
| 1. Storage (snapshots) | `canary_snapshots.composite_version=2` rows; production `fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)` is hardcoded to 1 | v2 snapshots leaking into the live API surface |
| 2. Storage (runs) | `regime_backtest_runs.run_scope='research'` | v2 walk-forward leaking into Validation panel, UI charts, OOS gate |
| 3. Constant | `CANARY_COMPOSITE_VERSION` constant unchanged at 1 | All production callers continue to read v1 |
| 4. Loader | `load_calibration()` keeps pointing at `canary-calibration-v1.json` | Production scoring still uses v1 calibration |
| 5. OOS gate | `LAST_KNOWN_AUC_v1_*` constants untouched; no v2 constants added in PR 1 | v1's production-stability contract remains the only gate |

If a future change accidentally bumps any one of these layers, the other four still keep v2 invisible. PR 2 will explicitly tear down layers 3, 4, 5 in a single coordinated commit; layers 1 and 2 stay (because v2 history needs to remain readable forever for backtesting / debugging).

---

## 7. Acceptance criteria — PR 1 (this PR's merge gate)

PR 1 is mergeable iff:

- **AC-1.** `canary_scoring.py` conditional path passes unit tests in `test_canary_v2_formula.py`: v1 calibration produces v1's exact `tactical + structural + speed.score` formula; v2 calibration produces `tactical + structural` only; both call `apply_cap()` with the same `speed.state`.
- **AC-2.** `canary-calibration-v2.json` parses into a `Calibration` dataclass with `composite_version=2` and identical thresholds to v1. (One test in `test_canary_v2_formula.py`.)
- **AC-3.** `canary_backfill.py --composite-version 2` writes 3,843 `composite_version=2` rows to `canary_snapshots` against a real test DB; production `fetch_latest(composite_version=1)` returns the v1 rows unchanged. (Integration test in `test_canary_v2_backfill.py`.)
- **AC-4.** `backtest_canary.py --walk-forward --composite-version 2` writes 6 walk-forward runs to `regime_backtest_runs` with `run_scope='research'`, `composite_version='2'`. (Integration test in `test_canary_v2_walk_forward.py`.)
- **AC-5.** Cross-scope renderer loads v1 production + v2 research walk-forward runs and renders without ValueError. (Integration test.)
- **AC-6.** `test_canary_oos_gate.py` (the 4 existing v1 OOS-gate tests) continues to pass with zero source changes. (Non-regression test.)
- **AC-7.** `uv run ruff check src/ tests/ scripts/` passes; web typecheck unchanged (no UI files modified).
- **AC-8.** Pre-commit hook passes; PR CI passes all 7 check jobs.

These ACs cover **PR 1's implementation correctness**. They do not gate the *production flip* — that's AC-F1..F6 below.

---

## 8. Acceptance criteria — PR 2 (the flip gate)

**These are pre-committed before any v2 measurement.** PR 2 may bump `CANARY_COMPOSITE_VERSION` 1→2 iff **every one** of AC-F1..F6 passes against PR 1's walk-forward + robustness output.

If any AC fails, PR 2 is not authorized. The verdict in the comparison report will be `STOP. v2-A is wrong. Record verdict in exec summary §13. File follow-up issue.`

| AC | Statement | Reasoning | Test mechanism |
|---|---|---|---|
| **AC-F1** | v2 composite **60d AUC ≥ 0.634** (v1 = 0.619; require +0.015 minimum lift) | The form-sweep showed vol-only gap of +0.020 to +0.027 across all 4 forms. Expected v2 ≈ 0.642. 0.634 = v1 + 0.015 leaves 8 bps slack for cap-mechanism difference. Below +0.015 is not a meaningful effect. | Computed by `_aucs_for_rows` over v2 walk-forward eval rows. Evaluated in renderer + integration test. |
| **AC-F2** | v2 composite **20d AUC ≥ 0.622** AND v2 composite **5d AUC ≥ 0.615** (v1 = 0.627 / 0.620; allow 0.005 noise floor) | No regression on shorter horizons. If v2 helps 60d but hurts 20d/5d, the predictive picture is mixed and v2-A is not a clean win. | Same as AC-F1. |
| **AC-F3** | The 4 historical CCA events (2011-08-08 debt downgrade, 2015-08-24 China, 2018-02-05 Volmageddon, 2020-03-09 COVID) still produce `warning_state='CONFIRMED_CANARY_ACTIVE'` in v2 | The cap mechanism still uses `speed.state`. This verifies our claim that v2-A doesn't break cap behavior. | Integration test asserts the 4 event dates appear in v2 backfill with the right warning_state. |
| **AC-F4** | For each of the 6 walk-forward windows: v2 60d AUC ≥ v1 same-window 60d AUC − 0.02 | Catches the "good on average but bad in one regime" failure mode. v1 passed 5/6 windows; v2 must stay broadly stable. | Per-window comparison rendered as a table. Renderer asserts per-window delta. |
| **AC-F5** | v2 **WATCH% ≤ 44.3%** (v1 = 39.3%; allow +5pp) | If v2 expands WATCH overfire, removing speed didn't help the user-facing concern; distribution diagnostics matter even though they're not the primary axis. | Computed in v2 backfill; compared against v1's WATCH%. |
| **AC-F6** | `tests/integration/regime/test_canary_oos_gate.py` (4 tests) continues to pass with **zero changes** to `LAST_KNOWN_AUC_v1_*` constants | v1 production is by construction unchanged; this confirms it empirically. Cheap, strong safety net. | Pre-existing test suite; non-regression check. |

### What we deliberately left out

- **v2 BUY-band AUC ≥ 0.50** — not part of v2-A's hypothesis. The within-BUY rank-inversion is v2-C territory (issue #90).
- **STRONG_BUY% > 0** — band semantics are v2-C.
- **Bootstrap-CI non-overlap** — CIs are reported in the comparison output but not load-bearing as a gate. CIs are easy to fail just from CI width; we don't have a principled threshold.

---

## 9. Test plan

### Unit tests (in `tests/unit/`)

| File | Test count | What they cover |
|---|---:|---|
| `test_canary_v2_formula.py` | 6 | v1 path bit-identical to PR #83; v2 path drops `+ speed.score`; both share `tactical`, `structural`, `apply_cap` calls; `Calibration` dataclass parses v2.json correctly; `composite_version` propagates through `run_analysis`; `composite_version=3` (future) currently routes to v2 path (`>= 2` semantic). |
| `test_canary_v1_v2_compare_renderer.py` | ~12 | Canonical column ordering; missing-version guard; mismatched windows guard; AC-F1 evaluation (PASS / FAIL); AC-F2 evaluation (both horizons); AC-F3 evaluation (4 events); AC-F4 evaluation (per-window deltas); AC-F5 evaluation (WATCH% delta); AC-F6 line present in output; verdict is AND of all ACs; footer present. |

### Integration tests (in `tests/integration/regime/`)

| File | Test count | What they cover |
|---|---:|---|
| `test_canary_v2_backfill.py` | ~5 | Backfill writes `composite_version=2` rows; production `fetch_latest(version=1)` returns v1 rows unchanged; v2 rows have `score_form='linear'`; explicit DELETE-by-composite-version rollback works; idempotent (re-running is a no-op). |
| `test_canary_v2_walk_forward.py` | ~7 | Walk-forward writes 6 research-scoped runs; v1 walk-forward production rows untouched; cross-scope renderer loads both correctly; renderer fails clearly if v2 runs missing; AC-F6 holds (v1 OOS-gate tests pass); cleanup-on-failure via `delete_runs_by_batch_id`. |

### Non-regression tests (pre-existing, must still pass)

- `tests/integration/regime/test_canary_oos_gate.py` (4 tests) — proves v1 production path unchanged.
- `tests/integration/regime/test_canary_form_sweep_full.py` (14 tests) — proves PR #88 form-sweep still works.
- `tests/integration/regime/test_canary_backtest.py` (existing v1 walk-forward + robustness tests) — proves no regression on v1 backtest harness.

Total new test count: **~30 tests** (~12 unit + ~12 integration + plus 6 in test_canary_v2_formula). New test runtime estimate: 20-30 seconds (real Postgres integration shards dominate).

---

## 10. Migration / coexistence plan

### During PR 1's lifetime

- v1 production untouched. UI reads v1. OOS gate reads v1.
- v2 lives only in `composite_version=2` snapshot rows + `run_scope='research'` backtest rows.
- Anyone curious can run `python -m uw_scan.reports.regime_canary_v1_v2_compare` to inspect the comparison; output is markdown to stdout, no DB writes.

### PR 2 (the flip, not in this PR)

In a single commit:
1. Bump `CANARY_COMPOSITE_VERSION = 2` in (wherever it's defined).
2. Retarget `load_calibration()` to `canary-calibration-v2.json`.
3. Regenerate `web/lib/types.ts` from updated OpenAPI schema.
4. Replace `LAST_KNOWN_AUC_v1_*` with `LAST_KNOWN_AUC_v2_*` constants derived from PR 1's walk-forward output (PR 2's spec will reference PR 1's run_ids).
5. Update `canary-methodology.md` to document v2 formula + the AC-F1..F6 gate that was satisfied.
6. Add a deprecation note in `canary-calibration-v1.json` (file kept for history; not deleted).
7. UI components (`CanarySubTab.tsx`, `CanaryValidationPanel.tsx`) updated to use the new `vol_resolution_score` field as the primary score, with `speed_state` as a secondary chip and `warning_cap` as a badge.

PR 2 is **small** (~80-150 LOC) by design, because PR 1 absorbs the heavy lifting.

### Long-term (v1 retirement)

After PR 2 has been on production for 1-2 months without regression:
- A small PR can delete the v1 branch of the `if calibration.composite_version >= 2` conditional in `canary_scoring.py` (removing the `else:` clause).
- `canary-calibration-v1.json` stays in the repo as historical record.
- `composite_version=1` snapshot rows stay in DB forever for backtest history readability.

---

## 11. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| v2 walk-forward AUC misses AC-F1 (i.e., the form-sweep result was an artifact and removing speed doesn't actually help) | Medium | High (entire v2-A track dies) | This is the *point* of the research-first pattern. We stop, record the verdict, move v2-A to "experimental rejected" status, and pivot to v2-C. Cost: ~10 hours of code time, no production damage. |
| v2 backfill computes different `tactical` or `structural` values than v1 due to a subtle interaction with the conditional path | Medium | High (invalidates the comparison) | Unit test in `test_canary_v2_formula.py` asserts byte-identical `tactical` and `structural` between v1 and v2 paths for a fixed input. v1's `raw` = v2's `raw` + `speed.score`. |
| `apply_cap()` interacts with the dropped speed.score in a non-obvious way (e.g., cap fires more often under v2 because raw is lower) | Low | Medium (changes cap-fire rate, but is captured in the v2 backfill data and visible in the comparison) | The renderer explicitly shows cap-fire rate per version. AC-F3 catches event-level cap regressions. |
| Backfill 3,843 days is slow (~10 min) and could fail midway | Medium | Low (idempotent — operator deletes partial v2 rows and re-runs) | Add `--resume` flag is out of scope; explicit DELETE-by-composite-version rollback is documented in §5.8. If this becomes painful in practice, add resumption in PR 2 or a follow-up. |
| AC-F1..F6 thresholds are too tight or too loose, leading to wrong PR 2 decision | Low | High (either we ship bad code or kill a good change) | Thresholds are pre-committed in this spec — they cannot be moved after seeing data without an explicit spec amendment PR. This is the "principled validation" property. If a threshold feels wrong after seeing data, the fix is a spec amendment with explicit reasoning, not silent re-baselining. |
| Schema invariants in §4 drift before PR 2 (e.g., `composite_version` column dropped) | Very Low | High (PR 2 cannot proceed) | §4 is explicit. CI would catch most drift via integration tests. Reviewer of any PR touching `canary_snapshots` schema should grep for `composite_version` references. |
| Someone runs `--composite-version 2` backfill against the production DB by mistake | Low | Very Low (just adds research rows; production path doesn't read them) | The data is isolated by `composite_version` column; production cannot see it. The only "harm" is a small DB size increase (~few MB). |

---

## 12. Reproduce / commands

### Run the v2 backfill (research-scoped)

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/canary_backfill.py --days 4000 --composite-version 2
```

Expected: ~3,843 rows inserted into `canary_snapshots` with `composite_version=2`. Idempotent — re-running is a no-op.

### Run the v2 walk-forward

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py --walk-forward --composite-version 2
```

Expected: 6 new rows in `regime_backtest_runs` with `run_scope='research'`, `composite_version='2'`, shared `params->>'batch_id'`.

### Re-render the comparison (no recompute)

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python -m uw_scan.reports.regime_canary_v1_v2_compare
```

Expected: markdown table to stdout + AC-F1..F6 evaluation + verdict line.

### Verify v1 production is untouched

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -c "
  SELECT composite_version, run_scope, COUNT(*)
  FROM uw_scan.regime_backtest_runs
  WHERE indicator='canary' AND completed_at IS NOT NULL
  GROUP BY composite_version, run_scope
  ORDER BY composite_version, run_scope;
"
```

Expected after PR 1:
```
 composite_version | run_scope  | count
-------------------+------------+-------
 1                 | production | 8-9
 2                 | research   | 7
```

### Verify calibration file untouched

```bash
md5 docs/research/regime/canary-calibration-v1.json
# Expected: 407024fadb7e7b46417f08f4d019d991 (unchanged from PR #83 + PR #88)
```

---

## 13. Open questions

(None at spec-finalization time. If new questions arise during implementation, they go in a comment thread on issue #89 and trigger a spec amendment PR if they affect ACs.)

---

## 14. Related

- **PR #83** — v1 canary indicator (the artifact this proposes to replace, partially).
- **PR #88** — full-history form-sweep (the immediately preceding research run; strengthens v2-A by exhausting form-based alternatives).
- **Issue #89** — v2-A GitHub issue (this spec is its resolution path).
- **Issue #90** — v2-C band/ordinal redesign (independent track; can run in parallel; subsumes v2-B).
- **§10 v2-A** of `docs/research/regime/canary-5yr-executive-summary.md` — original motivation, now promoted to top of v2 queue.
- **§13** of `docs/research/regime/canary-5yr-executive-summary.md` — form-sweep verdict that strengthens v2-A.

---

## Appendix A — AUC primer (for readers joining cold)

AUC ("Area Under the ROC Curve") measures rank-ordering quality:

> Pick a random "yes" day (forward return crossed the threshold) and a random "no" day. What's the probability the canary score was higher on the "yes" day?

| AUC | Meaning |
|---:|---|
| 0.50 | Coin flip — no signal |
| 0.55 | Tiny edge |
| 0.60 | Noticeable edge — real but modest |
| 0.65 | Solid signal — uncommon in finance |
| 0.70 | Strong — suspicious if sustained |
| 0.80+ | Almost always data leakage |

Finance signals live in 0.55–0.65. v1 canary composite sits at 0.619 on the primary 60d horizon. AC-F1 requires v2 to push that to **≥ 0.634** (+0.015 lift) for the flip to be authorized.

The three horizons measured:
- **AUC 5d (threshold 2%)** — does today's score predict SPX rising ≥ 2% in 5 days?
- **AUC 20d (threshold 5%)** — does today's score predict SPX rising ≥ 5% in 20 days?
- **AUC 60d (threshold 10%)** — does today's score predict SPX rising ≥ 10% in 60 days? **Primary metric; all AC-F1..F4 reference this.**
