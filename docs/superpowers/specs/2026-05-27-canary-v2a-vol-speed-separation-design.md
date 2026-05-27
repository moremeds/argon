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

This spec covers **PR 1 only** (research-only). The work persists into two independent storage scopes whose visibility rules are *complementary, not the same*:

- `canary_snapshots`: v2 backfill writes rows with the column `composite_version=2`. Production reads filter by this column (hardcoded `CANARY_COMPOSITE_VERSION=1`), so v2 snapshot rows are invisible.
- `regime_backtest_runs`: v2 walk-forward + robustness write rows with the column `run_scope='research'`. Production reads filter by this column (default `run_scope='production'`), so v2 backtest rows are invisible.

Both scopings combine with a `composite_version>=2` conditional inside `run_analysis()` to produce a side-by-side v1-vs-v2 comparison report and a pre-committed AC bundle (§8) that PR 2 must satisfy to flip production.

**Scope budget**: ~400–550 LOC new code across 2 modified source files (`canary_scoring.py` — 4-line conditional; `regime_backtest_repository.py` — new scoped delete method), 1 new calibration JSON, 2 modified scripts (`canary_backfill.py`, `backtest_canary.py`), 1 new renderer module (`regime_canary_v1_v2_compare.py`), 5 new test files (3 unit + 2 integration). Plus a one-time research backfill at `composite_version=2` covering the same date range as v1. ~40-60s of new test runtime.

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
- **G3.** Produce research-scoped walk-forward (6 windows, same `window_id`s as v1: `WF-1..WF-6`) AND one robustness run at `composite_version=2` in `regime_backtest_runs` with `run_scope='research'`. The 7 rows together — 6 walk-forward + 1 robustness — comprise the v2 evidence package.
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
| 5 new test files (3 unit + 2 integration) | Capitulation scorer (v2-D, separate research thread) |

---

## 4. Schema dependencies (load-bearing invariants this PR depends on)

| # | Invariant | Where it's encoded | Why this PR depends on it |
|---|---|---|---|
| 1 | `canary_snapshots.composite_version` is a column (int) | `src/uw_scan/storage/canary_snapshot_repository.py` schema + backing migration | Lets v2 rows coexist with v1 rows in the same table |
| 2 | `canary_snapshot_repository.fetch_latest(composite_version=...)` filters by that column | `src/uw_scan/storage/canary_snapshot_repository.py` | Production `fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)` (hardcoded to 1) sees no v2 rows |
| 3 | `regime_backtest_runs.run_scope` is a column with values in {'production', 'research'} | `src/uw_scan/storage/regime_backtest_repository.py` schema | Lets v2 walk-forward rows be invisible to `find_latest_run`'s production default |
| 4 | `find_latest_run(...)` defaults `run_scope='production'` (keyword-only arg) | `src/uw_scan/storage/regime_backtest_repository.py:173-178` | Production paths see only v1 runs |
| 5 | `apply_cap(raw, speed, ...)` uses `speed.state`, not `speed.score`, to decide capping | `src/uw_scan/cards/canary_scoring.py:441-462` | v2 can drop the additive speed.score term without breaking the cap mechanism |
| 6 | `Calibration.composite_version: int` field exists on the dataclass and the loader reads it from JSON | `src/uw_scan/cards/canary_calibration.py:37` + loader at `:60` | v2 calibration JSON parses without code change to the loader |
| 7 | `delete_runs_by_batch_id(batch_id)` (PR #88) is **HARD-PINNED to `params->>'phase'='form_sweep_full'`** | `src/uw_scan/storage/regime_backtest_repository.py:148-171` | Existing method **WILL NOT** clean up v2 walk-forward (phase='walk_forward') failures — see §5.8 fix |
| 8 | `CanaryLatestResponse.composite_version: int` is the canary-side type — NOT `src/uw_scan/api/schemas.py:249` (that's CRI's `CriBlock`) | `src/uw_scan/api/models/canary.py:25` | v2 rows deserialize without schema change (relevant only after PR 2) |
| 9 | `RegimeBacktestRepository.insert_run` enforces research-scope guards for **VCG only** (composite_method / credit_proxy) — there is **NO canary-side guard** | `src/uw_scan/storage/regime_backtest_repository.py:64-90` | A missed `run_scope='research'` kwarg on any canary v2 path writes a production-scoped row. PR 1 either adds a canary guard or treats explicit-kwarg discipline as a Hard Convention. See §6 layer 6. |
| 10 | `COMPOSITE_VERSION` is a module-level constant in `canary_calibration.py:11` used for the calibration-file f-string AND as a persistence default; loaded `Calibration.composite_version` is *separate* | `src/uw_scan/cards/canary_calibration.py:11, 60` | v2 persistence must use the loaded `cal.composite_version` (the field), NOT the module constant — otherwise v2 rows get tagged `composite_version=1` |

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
| `scripts/canary_backfill.py` | Modified | +35 | Add `--composite-version {1,2}` flag (default 1) and `--start-date` / `--end-date` (to derive v2 date range from v1's, see §5.5). When 2, explicitly calls `load_calibration(path=v2_path)` and writes snapshots tagged with `cal.composite_version` (NOT the module constant `COMPOSITE_VERSION`). |
| `scripts/backtest_canary.py` | Modified | +90 | Add `--v1-v2-compare` mode. Walk-forward (`--walk-forward --composite-version 2`) AND robustness (`--robustness --composite-version 2`) modes write `run_scope='research'`. The `--v1-v2-compare` dispatcher loads the FlipGateEvidence bundle (see §5.7) and calls the renderer. Walk-forward recomputes scores from `vol_index_daily` (same path as form-sweep + v1) — does NOT re-read `canary_snapshots`; a parity test cross-checks v2 recompute rows vs v2 snapshot rows for the same dates. |
| `src/uw_scan/reports/regime_canary_v1_v2_compare.py` | New | ~220 | Pure-function renderer `render_canary_v1_v2_compare(ev: FlipGateEvidence) -> str` (signature in §5.7). Side-by-side table + AC-F1..F6 evaluation lines + verdict + footer. CLI entry for re-render-without-recompute. |
| `src/uw_scan/storage/regime_backtest_repository.py` | Modified | +30 | Add `delete_canary_research_runs_by_batch_id_and_phase(batch_id: str, phase: str) -> int`. Scoped to `indicator='canary' AND run_scope='research' AND params->>'phase'=%s AND params->>'batch_id'=%s`. The existing `delete_runs_by_batch_id` is hard-pinned to `form_sweep_full` (intentional — see PR #88) and cannot be reused. |
| `tests/unit/test_canary_v2_formula.py` | New | ~120 | v1 calibration adds speed; v2 calibration drops speed; cap still uses `speed.state`; both paths agree on `tactical` and `structural` values for fixed inputs; v3 routes through v2 path (`>=2` semantic); BOTH_ACTIVE_AMBIGUOUS branch covered (raw delta v1→v2 + cap result unchanged). |
| `tests/unit/test_canary_v1_v2_compare_renderer.py` | New | ~250 | Canonical row ordering, missing-version guards, AC-F1..F6 evaluation rules (one test per AC), footer present, none-fallback, missing-FlipGateEvidence-field raises ValueError. |
| `tests/integration/regime/test_canary_v2_backfill.py` | New | ~200 | `canary_backfill --composite-version 2` writes v2 rows tagged with `cal.composite_version=2`; production `fetch_latest(version=1)` returns no v2 rows; v2 rows have `score_form='linear'`; idempotent re-run is a no-op (uses application-layer (data_date, composite_version) check at insert); explicit DELETE rollback works; **AC-F3 evidence test**: 4 CCA event dates (2011-08-08 / 2015-08-24 / 2018-02-05 / 2020-03-09) produce `payload.speed.confirmed_canary_active=True` in v2 rows. |
| `tests/integration/regime/test_canary_v2_walk_forward.py` | New | ~300 | Walk-forward + robustness at v2 persist with `run_scope='research'`; v1 walk-forward production rows untouched; cross-scope FlipGateEvidence loads correctly; renderer fails clearly if v2 batch incomplete; `delete_canary_research_runs_by_batch_id_and_phase` rolls back v2 walk-forward batch on failure; walk-forward recompute vs v2 backfill parity test for a small date subset. |
| `tests/unit/test_canary_v1_payload_hash_golden.py` | New | ~60 | **Golden payload-hash test**: run `run_analysis` with the v1 calibration on a fixed input fixture (captured pre-v2A) and assert byte-identical output. AC-F6 currently relies on the OOS-gate test which seeds synthetic rows — that's not a v1-scoring proof. This test IS the v1-scoring proof. |

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
# canary_backfill.py — new flags
uv run python scripts/canary_backfill.py \
    --composite-version 2 \
    --start-date 2011-02-08 \
    --end-date 2026-05-21
#   loads canary-calibration-v2.json explicitly (NOT via the module COMPOSITE_VERSION constant),
#   writes rows tagged with cal.composite_version=2 (the loaded field, NOT the module constant),
#   idempotent: re-running skips dates that already have a (data_date, composite_version=2) row,
#   inherits MIN_ALIGNED_BARS=350 warmup gate from canary_backfill's existing logic.

# Date range is now explicit — DO NOT use --days against live data, which advances daily.
# The required date range is the v1 backfill's date range, derived programmatically:
#   v2_start_date := MIN(data_date FROM canary_snapshots WHERE composite_version=1)
#   v2_end_date   := MAX(data_date FROM canary_snapshots WHERE composite_version=1)
# An assertion in the backfill script verifies v2 row count == v1 row count for the
# overlapping date range (i.e., n_v2 == n_v1 over [v2_start_date, v2_end_date]).

# backtest_canary.py — walk-forward at v2
uv run python scripts/backtest_canary.py --walk-forward --composite-version 2
#   runs walk-forward at v2; recomputes scores from vol_index_daily (same code path as
#   form-sweep + v1 walk-forward); persists 6 runs with run_scope='research' and
#   summary.composite_version='2'; shared params->>'batch_id' (UUID4 per invocation).
#   Window definitions match v1's WF-1..WF-6 exactly.

# backtest_canary.py — robustness at v2 (G3 — 7th evidence row)
uv run python scripts/backtest_canary.py --robustness --composite-version 2
#   persists 1 row with run_scope='research', composite_version='2', phase='robustness',
#   shared batch_id with the walk-forward batch.

# Comparison report
uv run python scripts/backtest_canary.py --v1-v2-compare
#   loads FlipGateEvidence (§5.7) from DB — v1 production walk-forward (latest complete
#   WF-1..WF-6) + v2 research walk-forward (latest complete batch_id) + v1/v2 backfill
#   distributions + v2 snapshot states on the 4 CCA event dates + OOS-gate test result,
#   renders side-by-side table + AC-F1..F6 verdict + verdict line + footer.

# Standalone re-render (no recompute):
uv run python -m uw_scan.reports.regime_canary_v1_v2_compare
#   reads the FlipGateEvidence bundle from DB, re-renders.
```

**Mutual exclusion**: `--composite-version 2` is mutually-exclusive with `--calibrate` (calibration produces a JSON, not consumes one). `--v1-v2-compare` is mutually-exclusive with all other modes (it's a renderer, not a backtest run).

**Source of truth for walk-forward**: walk-forward recomputes scores from `vol_index_daily` — it does NOT re-read `canary_snapshots`. This matches the form-sweep + v1 walk-forward code path. A parity integration test cross-checks v2 recompute scores against v2 backfill snapshot scores for a small date subset (~30 days from each walk-forward window) to confirm the two paths produce identical results.

**Composite-version source of truth**: every persistence call (snapshot insert, backtest run insert, daily row insert, payload composite_version field) MUST use `cal.composite_version` (the loaded field), NEVER the module-level `COMPOSITE_VERSION` constant. The module constant stays at 1 throughout PR 1; PR 2 changes it.

### 5.6 Persistence model

| Table | New rows added by this PR | Coexistence with v1 | Visibility to production |
|---|---|---|---|
| `canary_snapshots` | ~3,843 rows with `composite_version=2`, `score_form='linear'` | Sits alongside ~3,843 v1 rows (`composite_version=1`) with the same `data_date` values | **Invisible** — `fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)` is hardcoded to 1; `composite_version=2` rows never returned to production queries |
| `regime_backtest_runs` | 6 walk-forward rows + 1 robustness row, all with `run_scope='research'`, `composite_version='2'`, `indicator='canary'` | Sits alongside PR #83's 6 walk-forward + 1 robustness production rows | **Invisible** — `find_latest_run(...)` defaults to `run_scope='production'`; research rows never returned to production queries |
| `regime_backtest_daily` | ~23,000 rows (6 walk-forward windows × ~3,800 days), all attached to research-scoped runs | Sits alongside PR #83's production-scoped daily rows | **Invisible via FK** — production queries join through `regime_backtest_runs` which already filters by `run_scope` |

### 5.7 Renderer (`regime_canary_v1_v2_compare.py`)

The renderer is **pure** (no DB, no I/O). It takes a pre-assembled `FlipGateEvidence` dataclass that bundles everything any of AC-F1..F6 might need to evaluate. Loading is the dispatcher's job (in `backtest_canary.py`'s `--v1-v2-compare` mode); the renderer never touches the DB.

This separation matters: AC-F1/F2 read AUCs from walk-forward runs, AC-F3 reads snapshot event-date states, AC-F5 reads v1/v2 backfill band distributions, AC-F6 reads an external test-suite result. None of these are derivable from `regime_backtest_runs` rows alone, which is why the original draft renderer signature `(v1_runs, v2_runs)` was insufficient.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FlipGateEvidence:
    """Pre-assembled bundle that lets the renderer evaluate every AC-Fn locally.
    The dispatcher (--v1-v2-compare) is responsible for assembling this from DB."""
    v1_runs: list[dict]                    # 6 walk-forward runs, composite_version='1', run_scope='production'
    v2_runs: list[dict]                    # 6 walk-forward runs, composite_version='2', run_scope='research'
    v2_robustness_run: dict                # 1 robustness run, composite_version='2', run_scope='research'
    v1_full_history_aucs: dict[str, float] # full-history snapshot AUC over composite_version=1 (matches PR #88 form-sweep run id 27)
    v2_full_history_aucs: dict[str, float] # same code path, over composite_version=2 (the canonical AC-F1/F2 measurement)
    v1_per_window_aucs: dict[str, dict[str, float]]  # {WF-1: {up5d_2pct, up20d_5pct, up60d_10pct}, ...} from runs 19..24
    v2_per_window_aucs: dict[str, dict[str, float]]  # same shape from v2 walk-forward runs (AC-F4 input)
    v1_band_distribution: dict[str, float] # {"NONE": pct, "WATCH": pct, "BUY": pct, "STRONG_BUY": pct}
    v2_band_distribution: dict[str, float] # same for v2
    v2_cca_event_states: dict[str, bool]   # {"2011-08-08": True, "2015-08-24": True, ...} — payload.speed.confirmed_canary_active per event date
    oos_gate_passed: bool                  # result of running tests/integration/regime/test_canary_oos_gate.py
    v1_payload_hash_golden_passed: bool    # result of running tests/unit/test_canary_v1_payload_hash_golden.py


def render_canary_v1_v2_compare(ev: FlipGateEvidence) -> str:
    """Render v1-vs-v2 side-by-side comparison + AC-F1..F6 evaluation.

    Output: multi-section markdown:
      - Header: window, composite versions, batch ids
      - Side-by-side AUC table (5d / 20d / 60d × composite / vol_only / speed_only)
      - Band distribution comparison (NONE/WATCH/BUY/STRONG_BUY)
      - Per-window comparison (WF-1..WF-6 matched by params->>'window_id')
      - AC-F1..F6 evaluation block (one line per AC: PASS / FAIL with delta)
      - Verdict: SHIP iff all six AC pass, else STOP
      - Fixed footer: "What PR 2 will do iff this verdict is SHIP"

    Raises ValueError if:
      - v1_runs has != 6 runs or any composite_version != '1' or run_scope != 'production'
      - v2_runs has != 6 runs or any composite_version != '2' or run_scope != 'research'
      - v2_runs do not all share the same params->>'batch_id'
      - v1_runs.window_id and v2_runs.window_id sets are not exactly {WF-1..WF-6}
      - v2_robustness_run is missing or wrong scope/version
      - v2_cca_event_states is missing any of the 4 canonical dates
      - any AUC field is None / NaN at expected-finite positions
    """
```

**Dispatcher loader logic** (in `backtest_canary.py`'s `--v1-v2-compare` mode, NOT in the renderer):
- **v1_runs**: query `regime_backtest_runs` for `indicator='canary' AND run_scope='production' AND composite_version='1' AND params->>'phase'='walk_forward'`, group by `params->>'window_id'`, take the most-recent `completed_at` per window. Validate the set is exactly `{WF-1, WF-2, WF-3, WF-4, WF-5, WF-6}`; reject if duplicates or missing windows.
- **v2_runs**: query for `composite_version='2' AND run_scope='research' AND params->>'phase'='walk_forward'`, group by `params->>'batch_id'`, take the most-recent fully-complete batch (exactly 6 rows covering `{WF-1..WF-6}`). If no complete batch exists, fail with `RuntimeError`.
- **v2_robustness_run**: same scope, `phase='robustness'`, same `batch_id` as v2_runs.
- **v1_full_history_aucs**: AUC computed by `_aucs_for_rows` over all `canary_snapshots` at `composite_version=1` (full backfilled history). Should match PR #88 form-sweep run id 27's `summary.aucs.composite` (linear form) by construction. The dispatcher SHOULD compute this on-the-fly (not read from form-sweep run) to keep the comparison self-contained.
- **v2_full_history_aucs**: same computation, `composite_version=2`. This is the load-bearing AC-F1/F2 measurement.
- **v1_per_window_aucs / v2_per_window_aucs**: read directly from `regime_backtest_runs.summary->'aucs'->'composite'` for each walk-forward run (v1: ids 19..24; v2: the latest complete v2 walk-forward batch). Join by `params->>'window_id'`. AC-F4 input.
- **v1_band_distribution / v2_band_distribution**: aggregated band counts from `canary_snapshots` filtered by `composite_version`.
- **v2_cca_event_states**: `SELECT data_date, payload->'speed'->>'confirmed_canary_active' FROM canary_snapshots WHERE composite_version=2 AND data_date IN ('2011-08-08','2015-08-24','2018-02-05','2020-03-09')`.
- **oos_gate_passed**: invoke `uv run pytest tests/integration/regime/test_canary_oos_gate.py -q` and parse exit code.
- **v1_payload_hash_golden_passed**: same for `test_canary_v1_payload_hash_golden.py`.

The dispatcher prints the renderer's output to stdout. AC evaluation logic lives inside the renderer (it's pure: given `FlipGateEvidence`, every AC has a deterministic verdict).

### 5.8 Error handling (cleanup-on-failure)

Same atomic pattern as PR #88 form-sweep, with three corrections to the original draft:

- **Backfill failure mid-run**: `canary_backfill.py` runs each day inside its own transaction; on exception, the partial day is rolled back. **There is no `canary_backfill_status` table** (the prior draft of this spec incorrectly referenced one). The script tracks progress in stdout/logs only. On full-run failure, the operator runs `DELETE FROM canary_snapshots WHERE composite_version = 2 AND data_date > '<last-good-date>'` to roll back partial v2 rows. Idempotency on re-run is achieved via an application-layer pre-insert check (`SELECT 1 FROM canary_snapshots WHERE data_date=%s AND composite_version=2`), NOT via `ON CONFLICT DO NOTHING` — because `ON CONFLICT DO NOTHING` would silently keep stale rows from earlier failed/changed runs (Codex caught this — see Risk #X in §11). If the v2 scoring formula or thresholds change mid-development, the operator must `DELETE` v2 rows first, then re-run.
- **Walk-forward / robustness failure**: PR #88's `delete_runs_by_batch_id` is **hard-pinned to `params->>'phase'='form_sweep_full'`** (verified — see §4 invariant 7) and **cannot be reused**. PR 1 adds a new repo method:
  ```python
  def delete_canary_research_runs_by_batch_id_and_phase(
      self, batch_id: str, phase: str
  ) -> int:
      """Scoped DELETE: indicator='canary' AND run_scope='research'
         AND params->>'phase' = phase AND params->>'batch_id' = batch_id.
         Daily rows cascade via FK. Returns row count."""
  ```
  Called with `phase='walk_forward'` for walk-forward batches and `phase='robustness'` for robustness runs. On exception, `conn.rollback()` runs first (Postgres `InFailedSqlTransaction` requires it before any further query), then the scoped delete. Original exception preserved via `raise original` (Python last-raise-wins discipline — PR #88 §3.4).
- **Renderer failure** (e.g., incomplete v2 batch, missing CCA event states): renderer raises `ValueError` with a specific message. No DB state to clean up — renderer is pure (operates on the pre-assembled `FlipGateEvidence` dataclass).

---

## 6. Multi-layer invisibility (the same 5-layer defense as PR #88)

| Layer | Mechanism for v2-A | What it prevents |
|---|---|---|
| 1. Storage (snapshots) | `canary_snapshots.composite_version=2` rows; production `fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)` is hardcoded to 1 | v2 snapshots leaking into the live API surface |
| 2. Storage (runs) | `regime_backtest_runs.run_scope='research'` | v2 walk-forward leaking into Validation panel, UI charts, OOS gate |
| 3. Constant | `COMPOSITE_VERSION = 1` (module constant in `canary_calibration.py:11`) unchanged | All callers of `load_calibration()` with no path arg continue to load v1.json; daily scheduled `canary_backfill.py` continues to write v1 rows |
| 4. Persistence-vs-loaded discipline | v2 persistence always uses `cal.composite_version` (loaded field), never the module `COMPOSITE_VERSION` constant | A bug that mixes the two would persist v2 payloads tagged as version 1 — silently corrupting the DB |
| 5. OOS gate | `LAST_KNOWN_AUC_v1_*` constants untouched; no v2 constants added in PR 1 | v1's production-stability contract remains the only gate |
| 6. Caller discipline (research-scope kwarg) | All v2 `insert_run` call sites in PR 1 pass `run_scope='research'` explicitly. There is **no canary-side guard in `insert_run`** (verified — see §4 invariant 9; VCG has guards, canary does not) — discipline is the load-bearing mechanism here. A defensive guard for canary (`composite_version != module_constant → require run_scope='research'`) is a stretch goal for PR 2 (not PR 1). | A missed `run_scope='research'` kwarg from a future contributor silently writes a v2 row as production-scoped, polluting the production query plane |

If a future change accidentally bumps any one of these layers, the other five still keep v2 invisible. PR 2 will explicitly tear down layers 3 (constant bump), 4 (persistence rule becomes `cal.composite_version=2` everywhere — same field reference, different value), and 5 (new `LAST_KNOWN_AUC_v2_*` constants from PR 1's output) in a single coordinated commit; layers 1, 2, and 6 stay (v2 history readable forever; research-scope discipline still applies to *future* research vintages).

---

## 7. Acceptance criteria — PR 1 (this PR's merge gate)

PR 1 is mergeable iff:

- **AC-1.** `canary_scoring.py` conditional path passes unit tests in `test_canary_v2_formula.py`: v1 calibration produces v1's exact `tactical + structural + speed.score` formula; v2 calibration produces `tactical + structural` only; both call `apply_cap()` with the same `speed.state`; v3 (`composite_version=3`) routes through the v2 path (the `>=2` semantic is intentional); BOTH_ACTIVE_AMBIGUOUS branch covered.
- **AC-2.** `canary-calibration-v2.json` parses into a `Calibration` dataclass with `composite_version=2` and identical thresholds to v1. (One test in `test_canary_v2_formula.py`.)
- **AC-3.** `canary_backfill.py --composite-version 2 --start-date X --end-date Y` writes one row per business day in `[X, Y]` with `composite_version=2` (NOT the module constant) against a real test DB. The v2 row count equals the v1 row count for the same date range. Production `fetch_latest(composite_version=1)` returns the v1 rows unchanged. Re-running the backfill is a no-op (idempotent). (Integration test in `test_canary_v2_backfill.py`.)
- **AC-3a.** AC-F3 evidence sub-test: the 4 CCA event dates produce `payload.speed.confirmed_canary_active = True` in v2 backfill output. (Integration test in `test_canary_v2_backfill.py`.)
- **AC-4.** `backtest_canary.py --walk-forward --composite-version 2` writes 6 walk-forward runs to `regime_backtest_runs` with `run_scope='research'`, `composite_version='2'`, shared `params->>'batch_id'`, `window_id` ∈ {WF-1..WF-6}. (Integration test in `test_canary_v2_walk_forward.py`.)
- **AC-4a.** `backtest_canary.py --robustness --composite-version 2` writes 1 robustness run with `run_scope='research'`, `composite_version='2'`, `phase='robustness'`, same `batch_id` as walk-forward. (Integration test.)
- **AC-4b.** Walk-forward recompute vs v2 backfill parity test: for ~30 dates from each WF window, scores from `--walk-forward --composite-version 2` (which recomputes from `vol_index_daily`) match scores from `--composite-version 2` backfill (which writes snapshots) to within floating-point tolerance. (Integration test.)
- **AC-5.** `--v1-v2-compare` dispatcher assembles `FlipGateEvidence` from DB without error and renderer produces non-empty output. (Integration test.)
- **AC-5a.** `delete_canary_research_runs_by_batch_id_and_phase(batch_id, 'walk_forward')` deletes exactly the 6 v2 walk-forward rows of the given batch and cascades daily rows; v1 production rows unchanged. (Integration test.)
- **AC-6.** `test_canary_v1_payload_hash_golden.py` passes: `run_analysis` with the v1 calibration on a fixed input fixture produces a byte-identical output to a captured pre-v2A golden. This is the *real* proof that v1 scoring is unchanged. (New unit test in `tests/unit/`.)
- **AC-6a.** `test_canary_oos_gate.py` (4 existing v1 OOS-gate tests) continues to pass with zero source changes. Important note: these tests use synthetic seeded rows (verified — see Codex ISSUE-12) and do NOT exercise the v1 scoring path; AC-6 above is the proof of unchanged scoring. AC-6a is a weaker non-regression of the gate-test infrastructure.
- **AC-7.** `uv run ruff check src/ tests/ scripts/` passes; web typecheck unchanged (no UI files modified).
- **AC-8.** Pre-commit hook passes; PR CI passes all 7 check jobs.

These ACs cover **PR 1's implementation correctness**. They do not gate the *production flip* — that's AC-F1..F6 below.

---

## 8. Acceptance criteria — PR 2 (the flip gate)

**These are pre-committed before any v2 measurement.** PR 2 may bump `CANARY_COMPOSITE_VERSION` 1→2 iff **every one** of AC-F1..F6 passes against PR 1's walk-forward + robustness output.

If any AC fails, PR 2 is not authorized. The verdict in the comparison report will be `STOP. v2-A is wrong. Record verdict in exec summary §13. File follow-up issue.`

**Canonical AUC aggregation** (load-bearing — referenced by AC-F1, AC-F2, AC-F4):

- **AC-F1, AC-F2 (primary "full-history" AUCs)**: AUC computed by `_aucs_for_rows` over **all `canary_snapshots` rows at the relevant `composite_version`**. This matches how PR #88's form-sweep computed v1's 0.619 reference number (over 3,843 v1 snapshots, run id 27 / linear form). For v2, the dispatcher runs the same computation over `composite_version=2` snapshots. This is the load-bearing comparison for "does v2 lift the predictive AUC?" — same data set, same code path, only the formula differs.
- **AC-F4 (per-window stability)**: AUC values are pre-computed and persisted in each walk-forward run's `summary.aucs.composite.up60d_10pct` (verified — see WF-1 example below). v2 walk-forward stores its number the same way. Per-window deltas are computed by joining v1 runs (id 19..24) with v2 runs (matched by `params->>'window_id'`).

Concrete persistence shape (verified empirically against run id 19, WF-1):
```json
{ "aucs": { "composite": { "up5d_2pct": 0.581, "up20d_5pct": 0.564, "up60d_10pct": 0.642 },
            "vol_only":  { ... }, "speed_only": { ... } },
  "window_id": "WF-1", "n_days": 504, "auc_ci95": {...} }
```
Walk-forward pooled AUC ≠ full-history snapshot AUC because the walk-forward windows skip the pre-2015 warmup period. The full-history snapshot AUC is the canonical "v1 = 0.619" reference.

| AC | Statement | Reasoning | Test mechanism |
|---|---|---|---|
| **AC-F1** | v2 composite **full-history 60d AUC ≥ 0.634** (v1 full-history = 0.619; require +0.015 minimum lift) | The form-sweep showed vol-only gap of +0.020 to +0.027 across all 4 forms. Expected v2 ≈ 0.642 (note: v1's vol-only AUC was computed on `tactical + structural` pre-cap; v2's composite AUC is computed post-cap — but cap only fires ~1.3% of days, so the difference is small; 0.634 = v1 + 0.015 leaves 8 bps slack for this cap-mechanism difference). Below +0.015 is not a meaningful effect. | Computed by `_aucs_for_rows` over **all v2 canary_snapshots** (full-history backfill, 3,843 rows). v1 reference value is from PR #88 form-sweep run id 27 (linear form), `summary.aucs.composite.up60d_10pct = 0.619`. Evaluated in renderer + integration test. |
| **AC-F2** | v2 composite **full-history 20d AUC ≥ 0.622** AND v2 composite **full-history 5d AUC ≥ 0.615** (v1 full-history = 0.627 / 0.620; allow 0.005 noise floor) | No regression on shorter horizons. If v2 helps 60d but hurts 20d/5d, the predictive picture is mixed and v2-A is not a clean win. | Same as AC-F1, full-history snapshot aggregation. v1 reference values from same form-sweep run id 27. |
| **AC-F3** | The 4 historical Black-Monday-class events still produce `payload.speed.confirmed_canary_active = True` in v2 canary_snapshots (NOT `warning_state` — that field is post-cap-lift and can be 'NONE' even when speed.state is CCA): **2011-08-08** (post-debt-downgrade crash, downgrade was 08-05), **2015-08-24** (post-yuan-devaluation crash, devaluation was 08-11 to 08-14), **2018-02-05** (Volmageddon — XIV ETN crash), **2020-03-09** (COVID Black Monday I, S&P circuit breaker) | The cap mechanism uses `speed.state` (set whenever CCA active), not `speed.score`. AC-F3 verifies the SPEED-STATE assignment, not the cap-clamp action. v2's cap will fire less often (lower raw → fewer raw>49 cases) but `speed.state` is set whenever CCA is detected — this is the intended behavior. | Integration test (AC-3a above) asserts `payload.speed.confirmed_canary_active=True` for these 4 dates in v2 backfill. Source of event dates: web-verified (see Appendix B). |
| **AC-F4** | For each of the 6 walk-forward windows: v2 60d AUC ≥ v1 same-window 60d AUC − 0.02 | Catches the "good on average but bad in one regime" failure mode. v1 passed 5/6 windows; v2 must stay broadly stable. | Read v1 windows' `summary.aucs.composite.up60d_10pct` from `regime_backtest_runs` (ids 19..24). Read v2 windows' same field from v2 walk-forward runs. Join by `params->>'window_id'`. Verdict per window; aggregate verdict is AND. |
| **AC-F5** | v2 **WATCH% ≤ 44.3%** (v1 = 39.3%; allow +5pp) | If v2 expands WATCH overfire, removing speed didn't help the user-facing concern; distribution diagnostics matter even though they're not the primary axis. Note: v2 typically *reduces* total raw scores (no +speed term), shifting MORE days into NONE, which can make WATCH% trivially decrease. The bar catches the surprise expansion, not improvement. | Computed in v2 backfill summary; compared against v1's WATCH% from the equivalent v1 backfill summary. |
| **AC-F6** | `test_canary_v1_payload_hash_golden.py` passes — `run_analysis` with v1 calibration on a fixed input fixture is byte-identical pre/post v2-A | v1 production is by construction unchanged; the *real* proof is comparing actual scoring output. Note: PR 1 AC-6 (above) IS this golden test; AC-F6 here is the *flip-gate restatement* — the gate must still hold at PR 2 merge time. The pre-existing `test_canary_oos_gate.py` (4 tests) is a weaker non-regression of the gate-test infrastructure (uses synthetic seeded rows — see Codex ISSUE-12). | Pre-existing test (`test_canary_v1_payload_hash_golden.py`) re-run by the dispatcher; result in `FlipGateEvidence.v1_payload_hash_golden_passed`. |

### What we deliberately left out

- **v2 BUY-band AUC ≥ 0.50** — not part of v2-A's hypothesis. The within-BUY rank-inversion is v2-C territory (issue #90).
- **STRONG_BUY% > 0** — band semantics are v2-C.
- **Bootstrap-CI non-overlap** — CIs are reported in the comparison output but not load-bearing as a gate. CIs are easy to fail just from CI width; we don't have a principled threshold.

---

## 9. Test plan

### Unit tests (in `tests/unit/`)

| File | Test count | What they cover |
|---|---:|---|
| `test_canary_v2_formula.py` | ~9 | v1 path bit-identical to PR #83 (fixed-input regression); v2 path drops `+ speed.score`; both share `tactical`, `structural`, `apply_cap` calls; `Calibration` dataclass parses v2.json correctly; `composite_version` propagates through `run_analysis`; `composite_version=3` (future) currently routes to v2 path (`>= 2` semantic — test will deliberately fail on real v3 to force explicit handling); BOTH_ACTIVE_AMBIGUOUS branch (raw delta v1→v2 + cap result unchanged); v1's `tactical + structural` equals v2's `raw` for all 4 speed states. |
| `test_canary_v1_v2_compare_renderer.py` | ~16 | Canonical column ordering; missing-version guard; missing FlipGateEvidence field guard; mismatched windows guard; AC-F1 evaluation (PASS / FAIL with pooled-AUC fixture); AC-F2 evaluation (both horizons); AC-F3 evaluation (4 events, payload.speed.confirmed_canary_active=True); AC-F3 fails when payload.speed.confirmed_canary_active=False; AC-F4 evaluation (per-window deltas, including the -0.02 boundary case); AC-F5 evaluation (WATCH% delta — passes/fails at +5pp); AC-F6 evaluation (passes when v1_payload_hash_golden_passed=True); verdict is AND of all ACs; verdict=SHIP only when all 6 pass; verdict=STOP when any one fails; footer present in both verdicts. |
| `test_canary_v1_payload_hash_golden.py` | ~3 | Golden payload-hash test: `run_analysis` with v1 calibration on a fixed input fixture produces byte-identical output to a captured pre-v2A golden (the *real* AC-F6 proof). Test fails clearly if the v1 path is ever modified. |

### Integration tests (in `tests/integration/regime/`)

| File | Test count | What they cover |
|---|---:|---|
| `test_canary_v2_backfill.py` | ~7 | Backfill writes `composite_version=2` rows using `cal.composite_version` (not the module constant); production `fetch_latest(version=1)` returns v1 rows unchanged; v2 rows have `score_form='linear'`; explicit DELETE-by-composite-version rollback works; idempotent (re-running skips already-inserted dates via application-layer pre-check, not `ON CONFLICT DO NOTHING`); v2 row count equals v1 row count for the overlapping date range; **AC-F3 evidence sub-test**: 4 CCA event dates produce `payload.speed.confirmed_canary_active=True` in v2 rows. |
| `test_canary_v2_walk_forward.py` | ~9 | Walk-forward writes 6 research-scoped runs with shared batch_id + window_id ∈ {WF-1..WF-6}; robustness writes 1 row with same batch_id + phase='robustness'; v1 walk-forward production rows untouched; `delete_canary_research_runs_by_batch_id_and_phase('walk_forward')` deletes only the 6 walk-forward rows of given batch; cascade deletes daily rows; cross-scope `FlipGateEvidence` loader assembles correctly; renderer fails clearly if v2 batch incomplete (< 6 windows); recompute-vs-snapshot parity for 30-day subset across each WF window (AC-4b). |

### Non-regression tests (pre-existing, must still pass)

- `tests/integration/regime/test_canary_oos_gate.py` (4 tests) — passes; note that these tests use synthetic seeded rows (verified — Codex ISSUE-12) and do NOT exercise the v1 scoring path. The real v1-unchanged proof is `test_canary_v1_payload_hash_golden.py` (AC-6).
- `tests/integration/regime/test_canary_form_sweep_full.py` (14 tests) — proves PR #88 form-sweep still works.
- `tests/integration/regime/test_canary_backtest.py` (existing v1 walk-forward + robustness tests) — proves no regression on v1 backtest harness.

Total new test count: **~44 tests** (~28 unit + ~16 integration). New test runtime estimate: ~40-60 seconds (real Postgres integration shards dominate).

---

## 10. Migration / coexistence plan

### During PR 1's lifetime

- v1 production untouched. UI reads v1. OOS gate reads v1.
- v2 lives only in `composite_version=2` snapshot rows + `run_scope='research'` backtest rows.
- Anyone curious can run `python -m uw_scan.reports.regime_canary_v1_v2_compare` to inspect the comparison; output is markdown to stdout, no DB writes.

### PR 2 (the flip, not in this PR)

In a single commit:
1. **Bump `COMPOSITE_VERSION = 1 → 2` in `src/uw_scan/cards/canary_calibration.py:11`** (NOT a separate `CANARY_COMPOSITE_VERSION` — that's the imported name in `regime.py`; the canonical definition is in `canary_calibration.py`).
2. **The `load_calibration()` retarget is automatic** — `DEFAULT_PATH = f".../canary-calibration-v{COMPOSITE_VERSION}.json"` is f-string-interpolated from the module constant. No code change needed beyond step 1; the file load automatically switches to v2.json (this corrects the original draft of this spec which had retargeting as a separate manual step).
3. Regenerate `web/lib/types.ts` from updated OpenAPI schema.
4. Replace `LAST_KNOWN_AUC_v1_*` with `LAST_KNOWN_AUC_v2_*` constants derived from PR 1's walk-forward output (PR 2's spec will reference PR 1's run_ids and the pooled-AUC computation per §8 canonical aggregation).
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
| Walk-forward source-of-truth divergence: backfill writes snapshots, walk-forward recomputes from `vol_index_daily` — these can drift if either path has a bug | Medium | High (v2 metrics in walk-forward don't match v2 snapshots) | Explicit parity integration test (AC-4b): for ~30 dates per WF window, compare `--walk-forward --composite-version 2` scores against `--composite-version 2` backfill scores. Must match to floating-point tolerance. |
| `apply_cap()` interacts with the dropped speed.score in a non-obvious way (e.g., cap fires LESS often under v2 because raw is lower, so v2's effective post-cap distribution drifts) | Low | Medium (changes cap-fire rate, but is captured in v2 backfill data and visible in renderer output) | The renderer explicitly shows cap-fire rate per version. AC-F3 catches event-level cap regressions. |
| v1 vol-only AUC (0.642 reference) was computed on `tactical + structural` (pre-cap), while v2 composite AUC is computed post-cap. The cap fires ~1.3% of days (CCA states), so the post-cap v2 AUC may be a few bps below the pre-cap v1-vol-only number | Low | Low (already accounted for) | AC-F1's 0.634 bar leaves 8 bps slack for this. Renderer surfaces "v2 cap-fire rate" alongside the AUC. |
| `>=2` semantic on the v2 conditional auto-promotes a future v3 with a different formula into v2's path | Low (future v3 not yet planned) | High (silent behavior change when v3 lands) | Unit test in `test_canary_v2_formula.py` asserts `composite_version=3` currently routes through the v2 path — this test will deliberately fail when v3 lands, forcing the implementer to update the conditional with explicit v3 logic. Documented in §2 NG. |
| Backfill ~3,843 days is slow (~10 min) and could fail midway | Medium | Low (idempotent — operator runs explicit DELETE then re-runs; application-layer pre-insert check skips already-inserted days) | Idempotency is application-layer (NOT `ON CONFLICT DO NOTHING`, which would silently keep stale rows from earlier failed runs with bugs — Codex caught this). Explicit DELETE rollback documented in §5.8. |
| Concurrent `canary_backfill --composite-version 2` runs from two operators | Low | Low (duplicate rows would be inserted; `canary_snapshots` has no UNIQUE constraint on (data_date, composite_version), only PK on id) | Application-layer pre-insert check + the runtime convention "only one operator runs research backfill at a time". The form-sweep PR #88 made the same assumption successfully. Long-term: add `UNIQUE(data_date, composite_version)` to `canary_snapshots` as a separate migration (out of v2-A scope). |
| Caller discipline failure: a future canary path forgets `run_scope='research'` kwarg, writing v2 row as production | Low | High (silent production-plane pollution) | There is no `insert_run` canary-side guard (verified — VCG has guards, canary does not — §4 invariant 9). PR 1 enforces the discipline via review + tests; a defensive guard is a stretch goal for PR 2 (§6 layer 6). |
| AC-F1..F6 thresholds are too tight or too loose, leading to wrong PR 2 decision | Low | High (either we ship bad code or kill a good change) | Thresholds are pre-committed in this spec — they cannot be moved after seeing data without an explicit spec amendment PR. This is the "principled validation" property. If a threshold feels wrong after seeing data, the fix is a spec amendment with explicit reasoning, not silent re-baselining. See §15 for amendment process. |
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

Expected after PR 1 (note: PR #88 already added 4 form-sweep research rows, which the original draft of this spec forgot — corrected below):
```
 composite_version | run_scope  | count
-------------------+------------+-------
 1                 | production | 8-9   (PR #83 walk-forward + robustness + final OOS report)
 1                 | research   | 4     (PR #88 form-sweep batch — 4 forms)
 2                 | research   | 7     (PR 1 — 6 walk-forward + 1 robustness)
```

### Verify calibration file untouched

```bash
md5 docs/research/regime/canary-calibration-v1.json
# Expected: 407024fadb7e7b46417f08f4d019d991 (unchanged from PR #83 + PR #88)
```

---

## 13. Open questions

(None at spec-finalization time. New questions during implementation follow the spec-amendment process — see §15.)

---

## 14. Related

- **PR #83** — v1 canary indicator (the artifact this proposes to replace, partially).
- **PR #88** — full-history form-sweep (the immediately preceding research run; strengthens v2-A by exhausting form-based alternatives).
- **Issue #89** — v2-A GitHub issue (this spec is its resolution path).
- **Issue #90** — v2-C band/ordinal redesign (independent track; can run in parallel; subsumes v2-B).
- **§10 v2-A** of `docs/research/regime/canary-5yr-executive-summary.md` — original motivation, now promoted to top of v2 queue.
- **§13** of `docs/research/regime/canary-5yr-executive-summary.md` — form-sweep verdict that strengthens v2-A.

---

## 15. Spec amendment process

This spec's acceptance criteria (especially AC-F1..F6) are load-bearing — they are the *contract* PR 2 must satisfy. Once committed, they cannot be changed silently.

**Required steps to amend any AC threshold or to widen/narrow scope:**
1. Open a PR titled `docs(canary-v2a): spec amendment — <one-line reason>` that edits this file only.
2. The amendment commit message must include: (a) the AC being changed, (b) the empirical evidence motivating the change (with run_ids or git SHAs cited), (c) explicit acknowledgment that the new threshold was NOT derived from the data we're about to evaluate against (this prevents goalpost-moving).
3. The amendment PR requires user sign-off — same approval flow as any spec change.
4. Re-run `/review-cycle` against the amended spec; the new tribunal output is attached as a PR comment.

**Without all four steps, PR 2 may NOT use the amended thresholds**. If an amendment lands without `/review-cycle`, PR 2's reviewer must block.

This is the "principled validation" property: pre-commit before measuring is what made v1 trustworthy. v2 deserves the same discipline.

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

---

## Appendix B — Web-validation summary (Pass 2 /review-cycle, 2026-05-27)

The 2026-05-27 `/review-cycle` pass on this spec included WebSearch-based fact-checking of empirical claims, alongside the LLM tribunal (Codex + Gemini + Claude). Findings:

### Verified empirical claims

| Spec claim | Verdict | Source |
|---|---|---|
| **2018-02-05 Volmageddon** as a canonical CCA event date | ✅ Confirmed | XIV ETN crashed −90% in one day; VIX surged +115.6% (from 17.31 to 37.32). [CFA Institute: Volmageddon and the Failure of Short Volatility Products](https://rpc.cfainstitute.org/research/financial-analysts-journal/2021/volmageddon-failure-short-volatility-products) |
| **2020-03-09 COVID** as a CCA event date | ✅ Confirmed | "Black Monday I" — S&P 500 fell 7%, triggered the first-since-2013 circuit breaker. Dow −7.79%. [Wikipedia: 2020 stock market crash](https://en.wikipedia.org/wiki/2020_stock_market_crash) |
| **2011-08-08 "debt downgrade"** | ⚠️ Label corrected | The actual downgrade was **2011-08-05** (Friday); the crash was **2011-08-08** (Monday, "Black Monday 2011"). Spec date is correct (the crash, which is when CCA fires); label is now "post-debt-downgrade crash, downgrade was 08-05". [Wikipedia: Black Monday 2011](https://en.wikipedia.org/wiki/Black_Monday_(2011)) |
| **2015-08-24 "China devaluation"** | ⚠️ Label corrected | Yuan devaluation was **2015-08-11–14**; the crash was **2015-08-24** (Dow dropped 1,089 points intraday — largest at the time). Spec date is correct; label is now "post-yuan-devaluation crash, devaluation was 08-11 to 08-14". [Wikipedia: 2015–2016 stock market selloff](https://en.wikipedia.org/wiki/2015%E2%80%932016_stock_market_selloff) |

### Verified methodology choices

| Methodology | Verdict | Source |
|---|---|---|
| **Moving-block bootstrap for time-series AUC confidence intervals** (used in `_block_bootstrap_auc_ci`) | ✅ Validated | Standard methodology for autocorrelated time series, introduced by Kunsch (1989) and Liu & Singh (1992). Block size `l ≈ n^(1/3)` is the rule of thumb. [MetricGate: Block Bootstrap for Time Series](https://metricgate.com/docs/block-bootstrap-time-series/) |
| **Research-first + pre-committed AC gate** (PR 1 → PR 2 pattern) | ✅ Strongly validated | Textbook "shadow mode deployment + release gates" pattern for ML model rollout. Matches AWS SageMaker, MLOps best practices, and academic literature. [DYCORA: Shadow Mode Testing](https://www.dycora.com/deployment-and-shadow-mode-testing-validating-a-new-model-on-live-traffic-without-user-impact/), [TianPan.co: Shadow Mode, Canary Deployments, and A/B Testing for LLMs (2026)](https://tianpan.co/blog/2026-04-09-llm-gradual-rollout-shadow-canary-ab-testing) |

### Sources

- [CFA Institute: Volmageddon and the Failure of Short Volatility Products](https://rpc.cfainstitute.org/research/financial-analysts-journal/2021/volmageddon-failure-short-volatility-products)
- [Wikipedia: Black Monday 2011](https://en.wikipedia.org/wiki/Black_Monday_(2011))
- [Wikipedia: 2015–2016 stock market selloff](https://en.wikipedia.org/wiki/2015%E2%80%932016_stock_market_selloff)
- [Wikipedia: 2020 stock market crash](https://en.wikipedia.org/wiki/2020_stock_market_crash)
- [MetricGate: Block Bootstrap for Time Series](https://metricgate.com/docs/block-bootstrap-time-series/)
- [DYCORA: Deployment and Shadow Mode Testing](https://www.dycora.com/deployment-and-shadow-mode-testing-validating-a-new-model-on-live-traffic-without-user-impact/)
- [TianPan.co: Releasing AI Features Without Breaking Production (2026-04-09)](https://tianpan.co/blog/2026-04-09-llm-gradual-rollout-shadow-canary-ab-testing)
- [Wikipedia: 2015–2016 Chinese stock market turbulence](https://en.wikipedia.org/wiki/2015%E2%80%932016_Chinese_stock_market_turbulence)
