# Canary Full-History Form-Sweep — Design Spec

**Date**: 2026-05-27
**Status**: design — implementation plan not yet started
**Author intent**: candidate discovery for v2 score-form, not selection of a new production form
**Parent docs**:
- `docs/research/regime/canary-next-steps-2026-05-27.md` (Phase A, item #1)
- `docs/research/regime/canary-5yr-executive-summary.md` (§10 — v2-A/B/C/D motivation)
- `docs/research/regime/canary-methodology.md` (composite math + calibration discipline)
- `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md` (v1 spec; this is its first measurement-only follow-up)

---

## TL;DR

The v1 canary form (`linear`) was picked by `cmd_form_sweep` running against `VALID_START=2015-01-01..VALID_END=2019-12-31` (5 years, mild vol regime). We now have 3,843 rows across 15+ years in `canary_snapshots`. Re-running the form-sweep against the full backfilled dataset can identify whether non-linear forms deserve v2 candidate work — at near-zero cost, since `_compute_canary_series` already recomputes from `vol_index_daily` and `_aucs_for_rows` already produces composite/speed-only/vol-only AUCs. (The full dataset cannot "confirm" the production form: any v2 form change still requires a fresh holdout window for OOS validation.)

This spec adds a new CLI subcommand `--form-sweep-full` that runs that measurement. It produces 4 rows in `regime_backtest_runs` (one per form), each tagged `run_scope='research'` (the keystone invisibility lock — same mechanism VCG already uses), `phase='form_sweep_full'`, `is_winning_form=False`, and a shared `batch_id` (UUID per invocation) so re-runs and partial failures cannot be confused with each other. Six guardrails — CLI-level mutual exclusion, function isolation, persistence locks anchored on `run_scope='research'`, downstream-invisibility, batch-atomicity (cleanup-on-failure), and re-run/version safety — prevent the output from accidentally being treated as a production form selection.

A new focused implementation module in `src/uw_scan/reports/regime_canary_form_sweep_full.py` runs the measurement, while `scripts/backtest_canary.py` stays as a thin CLI dispatcher. A new pure-function renderer in `src/uw_scan/reports/regime_canary_backtest_report.py` prints a 4-row comparison table to stdout, with a fixed "What this run does NOT decide" footer.

**Scope budget**: ~300-360 LOC new code across 3 source files (thin `scripts/backtest_canary.py` wrapper + new `src/uw_scan/reports/regime_canary_form_sweep_full.py` + new `src/uw_scan/reports/regime_canary_backtest_report.py`) + 1 new repository method (`RegimeBacktestRepository.delete_runs_by_batch_id`) + 4 test files (11 integration tests + 17 unit tests). ~20-30s of new test runtime.

---

## 1. Motivation

### What v1 left unresolved

After PR #83 (v1 canary indicator) merged, three findings in `canary-5yr-executive-summary.md` §9 demanded follow-up:

- **WATCH band overfires**: 31-39% of all days vs. design intent of ~25%
- **Within-BUY band is anti-predictive**: AUC 0.35-0.45 across all horizons (regression-to-mean signature)
- **Vol-only beats composite by 0.01-0.04 AUC** at every horizon × every subset

The roadmap memo (`canary-next-steps-2026-05-27.md`) rank-ordered the follow-ups. Phase A item #1 — re-run `--form-sweep` against the full 2011-2026 dataset — is the highest-information, smallest-code change available. If a non-`linear` form compresses middle scores into NONE (which `convex` or `sigmoid` could do mechanically), the WATCH-overfire problem may have a candidate fix, pending v2 holdout validation.

### Why this is "discovery, not validation"

The full 2011-2026 dataset is the **same data** the v1 walk-forward judged against (run ids 19-24). Picking a winning form from it and then re-evaluating against any subset of it would be circular — the walk-forward result is the empirical anchor we just bought. Any v2 calibration change requires a reserved holdout window that this run cannot supply.

Therefore: this run **discovers candidates**. Any candidate must be re-validated under its own spec, with a reserved holdout, before it can change `canary-calibration-v1.json`.

---

## 2. Goals and non-goals

### Goals

- G1. Evaluate all 4 supported score forms (`linear`, `convex`, `concave`, `sigmoid`) against the full backfilled `canary_snapshots` range.
- G2. Persist diagnostic AUC + band-distribution + within-band-rank + vol-only-gap metrics in `regime_backtest_runs.summary` so the result is re-renderable from DB.
- G3. Print a 4-row comparison table to stdout at end of run, with mechanical "Observations" flags on surprising patterns and a fixed "this is not a decision" footer.
- G4. Make it **impossible** for the run to silently change v1 production behavior (validation panel, OOS gate, calibration JSON).

### Non-goals

- NG1. Selecting or declaring a winning form.
- NG2. Updating `canary-calibration-v1.json`.
- NG3. Bumping `COMPOSITE_VERSION`.
- NG4. Changing band thresholds (NONE/WATCH/BUY/STRONG_BUY).
- NG5. Adding a UI surface for the result (validation panel changes are out of scope).
- NG6. Modifying `cmd_form_sweep` (the existing 2015-2019 selection-mode function) — it remains untouched so any historical re-runs reproduce.
- NG7. Adding new API endpoints.

---

## 3. Architecture overview

```
                      ┌──────────────────────────────┐
   scripts/           │  --form-sweep-full           │
   backtest_canary.py │  thin wrapper + argparse     │
                      └──────────────┬───────────────┘
                                     │ delegates
                                     ▼
                      ┌──────────────────────────────┐
                      │ src/uw_scan/reports/         │
                      │ regime_canary_form_sweep_    │
                      │ full.py                      │
                      └──────────────────────────────┘
                              │
                              │ reads (read-only)
                              ▼
              ┌─────────────────────────────────┐
              │ uw_scan.vol_index_daily         │
              │ uw_scan.canary_snapshots (MIN/  │
              │   MAX(data_date) for window)    │
              └─────────────────────────────────┘
                              │
                              │ 4× recompute via _compute_canary_series
                              ▼
                      ┌──────────────────────────────┐
                      │ For each form:               │
                      │   linear / convex /          │
                      │   concave / sigmoid          │
                      │                              │
                      │ → aucs (composite/speed/vol) │
                      │ → band_distribution          │
                      │ → within_band_aucs           │
                      │ → vol_only_gap               │
                      │ → auc_ci95 (block-bootstrap) │
                      └──────────────────────────────┘
                              │
                              │ INSERT (×4 rows + daily)
                              ▼
              ┌─────────────────────────────────┐
              │ uw_scan.regime_backtest_runs    │
	              │   run_scope='research'          │
	              │   params.phase='form_sweep_full'│
	              │   summary.is_winning_form=False │
              │ uw_scan.regime_backtest_daily   │
              └─────────────────────────────────┘
                              │
                              │ stdout (immediate) + on-demand re-render
                              ▼
                      ┌──────────────────────────────┐
                      │ src/uw_scan/reports/         │
                      │ regime_canary_backtest_      │
                      │ report.py (new)              │
                      │                              │
                      │ render_canary_form_sweep_    │
                      │ compare(runs) -> str         │
                      └──────────────────────────────┘
```

Three new or changed code units. All stay narrow:
- `scripts/backtest_canary.py` only adds the `--form-sweep-full` flag, mutual-exclusion check, and a small `cmd_form_sweep_full` wrapper that delegates to `regime_canary_form_sweep_full.py`. This satisfies the repo's module-size rule: `scripts/backtest_canary.py` is already >1,000 lines, so the new command body is not added there.
- `regime_canary_form_sweep_full.py` owns the new command body and `_within_band_aucs`. Existing helpers — `_compute_canary_series`, `_aucs_for_rows`, `_band_counts`, `_block_bootstrap_auc_ci`, `_clean_nans`, `_entry_lagged_label`, `_auc`, `LABEL_SPECS`, `COMPOSITE_VERSION` — are passed in from the script wrapper as explicit dependencies, so the package module does not import the script.
- `regime_canary_backtest_report.py` is a new module, sibling to `regime_backtest_report.py` (CRI) and `regime_vcg_backtest_report.py` (VCG), matching the project's "one renderer per indicator" convention.

---

## 4. Detailed design

### 4.1 CLI surface

Single boolean flag — no overrides:

```bash
uv run python scripts/backtest_canary.py --form-sweep-full
```

**Window resolution** (computed at run time, not hardcoded):
- `start = MIN(canary_snapshots.data_date)`
- `end = MAX(canary_snapshots.data_date)`
- Logged at run start: `INFO form-sweep-full window: 2011-02-08 → 2026-05-21 (3,843 days)`

**Argparse**:
- `--form-sweep-full` is added as a new boolean alongside the existing top-level mode flags (`--calibrate`, `--form-sweep`, `--report`, `--walk-forward`, `--robustness`). The existing argparse setup at `scripts/backtest_canary.py:1072-1088` does NOT use `add_mutually_exclusive_group` — it uses an `if/elif/return` chain in `main()`. Mutual exclusion is therefore enforced by an explicit count-check at the top of `main()`: if more than one top-level mode flag is True, call `parser.error("only one of --calibrate/--form-sweep/--form-sweep-full/--report/--walk-forward/--robustness may be specified")` and exit with code 2.
- `--form linear|convex|concave|sigmoid` (existing per-form override) has no effect when `--form-sweep-full` is set (the sweep iterates all four forms regardless). If `--form` is passed alongside `--form-sweep-full`, a warning is logged at run start (`WARNING --form is ignored under --form-sweep-full`) so the user knows their flag had no effect.

**Exit codes**:
- `0` on success: all 4 form rows persisted + comparison logged.
- `1` on failure: snapshot table empty, any form computation errors, OR any of the 4 inserts fails. Fail loud — no partial-state runs.

**End-of-run output**: the script calls `render_canary_form_sweep_compare(runs)` after persisting and prints to stdout. The user sees the table without a separate command.

### 4.2 Persistence shape

Each of the 4 runs writes **one row to `regime_backtest_runs`** and **~3,843 daily rows to `regime_backtest_daily`**.

#### `regime_backtest_runs` row (×4, all sharing the same `batch_id`)

| Column | Value |
|---|---|
| `indicator` | `"canary"` |
| `composite_version` | `"1"` (mirrors `cmd_form_sweep` convention; varying `score_form` does not bump the version) |
| `run_scope` | **`"research"`** (keystone invisibility lock — see §4.4 G-3. `find_latest_run` filters `WHERE run_scope=%s` defaulting to `'production'`, so research-scoped rows are invisible to the OOS gate and `/api/regime/canary/validation`. Convention matches VCG research runs at `scripts/backtest_vcg.py:434, 438`.) |
| `start_date` | `MIN(canary_snapshots.data_date)` |
| `end_date` | `MAX(canary_snapshots.data_date)` |
| `window_days` | `350` (kept for column consistency with other canary runs; semantic meaning clarified in `params` below) |
| `n_days` | length of eval_rows |
| `params` | see schema below |
| `summary` | JSONB — schema below |

#### `params` JSONB schema

```json
{
  "score_form": "<linear|convex|concave|sigmoid>",
  "phase": "form_sweep_full",
  "batch_id": "<uuid4 — same value across all 4 rows from one invocation>",
  "purpose": "candidate_discovery_not_validation",
  "min_aligned_bars": 350,
  "window_semantics": "warmup_requirement_not_eval_window"
}
```

The `batch_id` is generated **once** at run start via `uuid.uuid4()` and reused for all 4 form rows in that invocation. It is the primary grouping key the renderer uses to fetch a coherent set; `start_date`/`end_date`/`composite_version` are informational columns kept consistent with other run types but are NOT used as the renderer's grouping key (see §4.3).

`purpose` is a fixed string that future SQL queries can filter on (`params->>'purpose' = 'candidate_discovery_not_validation'`) to distinguish these rows from any future production-selection runs at a glance.

`min_aligned_bars` and `window_semantics` make the `window_days=350` column readable without grepping the script — they spell out that 350 is the warm-up gate, not an evaluation length.

#### `summary` JSONB schema

```json
{
  "is_winning_form": false,
  "score_form": "<linear|convex|concave|sigmoid>",
  "phase": "form_sweep_full",
  "source": "form_sweep_full",
  "batch_id": "<same uuid4 as in params.batch_id>",
  "generated_at": "<ISO-8601 UTC timestamp at run start, shared across all 4 rows>",
  "n_days": 3843,
  "aucs": {
    "composite":  {"up5d_2pct": 0.620, "up20d_5pct": 0.627, "up60d_10pct": 0.619},
    "vol_only":   {"up5d_2pct": 0.626, "up20d_5pct": 0.639, "up60d_10pct": 0.642},
    "speed_only": {"up5d_2pct": 0.470, "up20d_5pct": 0.465, "up60d_10pct": 0.430}
  },
  "auc_ci95": {
    "up5d_2pct":   [lo, hi],
    "up20d_5pct":  [lo, hi],
    "up60d_10pct": [lo, hi]
  },
  "band_distribution": {"NONE": 2121, "WATCH": 1511, "BUY": 211, "STRONG_BUY": 0},
  "within_band_aucs": {
    "NONE":  {"up5d_2pct": 0.581, "up20d_5pct": 0.601, "up60d_10pct": 0.586},
    "WATCH": {"up5d_2pct": 0.559, "up20d_5pct": 0.633, "up60d_10pct": 0.609},
    "BUY":   {"up5d_2pct": 0.447, "up20d_5pct": 0.431, "up60d_10pct": 0.348}
  },
  "vol_only_gap": {
    "up5d_2pct": 0.006, "up20d_5pct": 0.012, "up60d_10pct": 0.023
  }
}
```

Notes:
- `is_winning_form: false` is **hardcoded in the dict literal** — not computed, not conditional. The form-selection logic from `cmd_form_sweep` (lines 473-487) is **not** copied into the new function.
- `auc_ci95` uses `_block_bootstrap_auc_ci(block_size=20, iters=1000)` against composite scores only (matches `cmd_walk_forward` convention).
- `within_band_aucs` is computed by a new `_within_band_aucs` helper (~25 LOC, placed near `_aucs_for_rows`). NaN AUCs (e.g. STRONG_BUY band with zero observations) cleaned to `null` via existing `_clean_nans`.
- `vol_only_gap` is derived (`vol_only - composite` per horizon). Stored explicitly so renderer doesn't recompute. Positive = vol-only better than composite at that horizon.
- `phase: "form_sweep_full"` is duplicated into the summary for ad-hoc SQL filtering (`summary->>'phase' = 'form_sweep_full'`) without a JSON-path into params.

#### `regime_backtest_daily` rows (×4 sets)

Same shape as existing `cmd_form_sweep` daily writes at `scripts/backtest_canary.py:453-470`:

```json
{
  "trade_date": "2011-02-08",
  "score": 18.43,
  "level": "NONE",
  "payload": {
    "raw_score": 18.43,
    "tactical": 5.12,
    "structural": 11.31,
    "speed": 2.0,
    "warning_state": "NONE"
  }
}
```

Volume: 4 forms × ~3,843 rows = ~15,372 daily rows. Lets us drill down later without re-running.

#### Persistence atomicity (cleanup-on-failure)

`RegimeBacktestRepository.insert_run`, `bulk_insert_daily`, and `mark_run_completed` each call `self._conn.commit()` internally (verified at `src/uw_scan/storage/regime_backtest_repository.py:115, 137, 146`). A single-transaction wrap of all 4 form persistences (Option A) would require refactoring the repository to accept a non-committing mode — out of this spec's scope.

Therefore the script uses **Option B: cleanup-on-failure**, with `batch_id` as the cleanup key:

```python
import uuid

def cmd_form_sweep_full(conn, *, schema: str) -> None:
    batch_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc).isoformat()
    bt_repo = RegimeBacktestRepository(conn, schema=schema)

    # Phase 1 (in-memory): compute all 4 form series + summaries.
    # Any failure here is pre-persistence — no rows yet exist, so no cleanup needed.
    per_form: dict[str, dict] = {}
    for form in ("linear", "convex", "concave", "sigmoid"):
        series = _compute_canary_series(conn, cal, form=form, start=..., end=..., schema=schema)
        per_form[form] = _build_summary_dict(series, form, batch_id, generated_at)

    # Phase 2 (persistence): insert all 4 runs + daily rows. On ANY failure,
    # cleanup all rows tagged with this batch_id and re-raise so the
    # process exits non-zero.
    try:
        for form, payload in per_form.items():
            run_id = bt_repo.insert_run(..., run_scope="research")  # commits
            bt_repo.bulk_insert_daily(run_id, payload["daily"])  # commits
            bt_repo.mark_run_completed(run_id)  # commits
    except Exception:
        log.exception("form_sweep_full persistence failed; cleaning up batch_id=%s", batch_id)
        conn.rollback()  # required if the failed DB statement left the transaction aborted
        _cleanup_batch(conn, schema=schema, batch_id=batch_id)
        raise
```

The `_cleanup_batch` helper is a new method on `RegimeBacktestRepository`:

```python
def delete_runs_by_batch_id(self, batch_id: str) -> int:
    """Delete all regime_backtest_runs (and CASCADE to daily) tagged with batch_id.

    Returns the number of run rows deleted. Used by form_sweep_full's
    cleanup-on-failure path.
    """
```

The migration that creates `regime_backtest_daily` already has `ON DELETE CASCADE` for `run_id` (per the closure memo's cookbook); the cleanup is a single `DELETE FROM regime_backtest_runs WHERE params->>'batch_id' = %s`. If the FK does not cascade in the current schema, the implementation plan must verify and add an explicit daily-delete first.

**Invariant**: after `cmd_form_sweep_full` returns (whether success or failure), the DB contains either exactly 0 rows OR exactly 4 rows for the script's `batch_id`. Never 1, 2, or 3.

#### New helper

```python
def _within_band_aucs(rows: list[dict]) -> dict[str, dict[str, float]]:
    """AUC of composite score vs forward labels, restricted to each band.

    Labels are computed once over the full row series (so the last 60 days
    don't drop out of every band-subset), then filtered by band membership.
    Returns NaN for bands with <2 distinct labels in the subset.

    This preserves the "compute labels once, filter by index" fix from the
    v1 robustness work — see scripts/backtest_canary.py:_auc_for_indices.
    """
```

Placed in `regime_canary_form_sweep_full.py`. ~25 LOC. Reuses `_entry_lagged_label` + `_auc` through explicit dependency injection from the script wrapper.

### 4.3 Renderer

New module: `src/uw_scan/reports/regime_canary_backtest_report.py`.

Pure function, no I/O:

```python
def render_canary_form_sweep_compare(runs: list[dict]) -> str:
    """Render a 4-form comparison table from form_sweep_full runs.

    `runs` is a list of regime_backtest_runs row dicts, each with
    params.phase='form_sweep_full'. Caller is responsible for filtering
    and loading; this function does not touch the DB.

    Sort order in output: linear, convex, concave, sigmoid (canonical,
    not by id).

    Raises ValueError if:
      - fewer than 4 rows provided
      - any form appears more than once
      - any required score_form is missing
    """
```

#### Output format

```markdown
# Canary form-sweep — candidate discovery
Window: 2011-02-08 → 2026-05-21 (3,843 days)
Composite version: 1
Run ids: 27, 28, 29, 30

| Form    | AUC 5d | AUC 20d | AUC 60d | NONE% | WATCH% | BUY% | STRONG_BUY% | BUY-band 60d AUC | Vol-only gap (60d) |
|---------|-------:|--------:|--------:|------:|-------:|-----:|------------:|-----------------:|-------------------:|
| linear  |  0.620 |   0.627 |   0.619 |  55.2 |   39.3 |  5.5 |         0.0 |            0.348 |             +0.023 |
| convex  |  ...   |   ...   |   ...   |  ...  |   ...  |  ... |         ... |            ...   |             ...    |
| concave |  ...   |   ...   |   ...   |  ...  |   ...  |  ... |         ... |            ...   |             ...    |
| sigmoid |  ...   |   ...   |   ...   |  ...  |   ...  |  ... |         ... |            ...   |             ...    |

## Observations

- WATCH% above 30% in: <list of forms>
- BUY-band 60d AUC below 0.50 in: <list of forms>  (regression-to-mean signature)
- Vol-only gap (60d) ≥ +0.02 in: <list of forms>  (speed layer net-negative for rank)
- BUY% at exactly 0 (band never fires) in: <list of forms>
- STRONG_BUY% at exactly 0 (band never fires) in: <list of forms>
- Composite 60d AUC improves over linear by ≥ +0.02 in: <list of forms>  (deserves v2-C planning)
- WATCH% reduced by ≥ 5 percentage points vs linear AND 60d AUC does not fall by more than 0.01 in: <list of forms>  (practical v2-C candidate)

## What this run does NOT decide

This is candidate-discovery output. No form is declared "winning". Any v2
calibration change must reserve a fresh holdout window for OOS validation.
```

The **Observations** block is mechanical — it lists forms that match each rule. It never names a winner. The `<list of forms>` slots in the example above are render-time substitutions; the renderer fills them with comma-joined form names (e.g. "convex, sigmoid") or "none" when no form matches the rule.

The **What this run does NOT decide** footer is a fixed string in the renderer source, defending against the human-cognitive bias to read a table and conclude "highest number wins."

#### CLI entry point

`__main__` block in the renderer module. `--mode` defaults to `form_sweep_compare` (currently the only supported mode); `--runs` is optional.

```bash
# Default — implicit --mode form_sweep_compare, auto-loads latest 4 rows
uv run python -m uw_scan.reports.regime_canary_backtest_report

# Explicit mode + specific row ids
uv run python -m uw_scan.reports.regime_canary_backtest_report \
    --mode form_sweep_compare --runs 27,28,29,30
```

Without `--runs`: loads the **latest complete `batch_id`** — defined as the most-recent `params->>'batch_id'` whose row-count for `params->>'phase' = 'form_sweep_full'` equals exactly 4 AND covers all four score forms. The "latest" is determined by `MAX(created_at)` among rows in that batch.

Concretely the loader's logic:

```sql
-- Identify the latest fully-complete research batch.
-- All filters are necessary: an in-progress batch with completed_at IS NULL,
-- or a stray production-scoped row with the same batch_id, would otherwise
-- be selectable and break the renderer's all-four-forms contract.
WITH ranked_batches AS (
  SELECT params->>'batch_id' AS batch_id,
         MAX(created_at) AS latest,
         COUNT(*) AS n_rows,
         array_agg(params->>'score_form' ORDER BY params->>'score_form') AS forms
  FROM uw_scan.regime_backtest_runs
  WHERE indicator = 'canary'
    AND run_scope = 'research'
    AND completed_at IS NOT NULL
    AND params->>'phase' = 'form_sweep_full'
  GROUP BY params->>'batch_id'
)
SELECT batch_id FROM ranked_batches
WHERE n_rows = 4
  AND forms = ARRAY['concave','convex','linear','sigmoid']
ORDER BY latest DESC
LIMIT 1;
```

Incomplete batches (n_rows < 4 OR missing forms — i.e. an in-progress run, or a failed run whose cleanup somehow didn't complete) are **skipped, not rendered**. The loader falls through to the next-latest complete batch. If no complete batch exists, the renderer raises `ValueError("no complete form_sweep_full batch found")` — never renders partial state.

With `--runs <id>,<id>,<id>,<id>`: load exactly those four rows (use case: render an **explicit, non-latest batch** — e.g., re-render an older batch for documentation, or render a specific batch_id when multiple completed batches exist on the same day). Renderer still validates: all 4 rows must share the same `batch_id`, the same `composite_version`, and cover all four `score_form` values; otherwise raises.

`--runs` does **not** support cross-batch or cross-version comparison. Comparing v1 vs v2 candidate forms, or comparing two distinct batches over time, requires a separate comparison mode (out of scope for this design; would be a `form_sweep_cross_batch` follow-up).

Errors if fewer than 4 rows match, any form is missing, any form appears more than once, or rows span multiple `batch_id` / `composite_version` values. No partial-state rendering.

#### Where the renderer is called

1. **End of `cmd_form_sweep_full`**: after the 4 inserts, calls `render_canary_form_sweep_compare(runs)` and prints to stdout.
2. **Later, on demand**: via the `python -m` entry point.

#### What this renderer is NOT

- Not used by `/api/regime/canary/validation`. That endpoint calls `find_latest_run(..., run_scope='production')` and then post-filters in Python on `summary.is_winning_form` (`src/uw_scan/api/routers/regime.py:407-435`, line 420). Because `cmd_form_sweep_full` writes with `run_scope='research'`, those rows are filtered out at the SQL layer by `find_latest_run` — they never reach the Python post-filter. `run_scope='research'` is the **keystone**; `is_winning_form=false` is defense-in-depth only.
- Not a generalization of the existing CRI / VCG renderers.
- Not coupled to `canary_snapshots` — works purely off `regime_backtest_runs` rows.

### 4.4 Guardrails

Five categories enforcing "candidate discovery, not selection" in code.

#### G-1. CLI-level mutual exclusion

The existing argparse setup does NOT use `add_mutually_exclusive_group`; it uses an `if/elif/return` chain in `main()` (`scripts/backtest_canary.py:1092-1114`). Exclusion is enforced by an explicit count-check at the top of `main()`:

```python
mode_flags = [args.calibrate, args.form_sweep, args.form_sweep_full,
              args.report, args.walk_forward, args.robustness]
if sum(bool(f) for f in mode_flags) > 1:
    parser.error("only one of --calibrate/--form-sweep/--form-sweep-full/"
                 "--report/--walk-forward/--robustness may be specified")
```

`--form X` has no effect under `--form-sweep-full` (the sweep iterates all four forms by design). If `--form` is passed alongside, a warning is logged at run start so the user knows the flag had no effect.

#### G-2. Function-level isolation

`cmd_form_sweep_full` is a thin wrapper, and the full-history implementation lives outside `cmd_form_sweep`. They share read-only helpers through explicit dependencies; **zero shared mutable state**.

`cmd_form_sweep_full` is forbidden — by absence-of-code, reviewable in diff — from:
- Calling `CALIB_PATH.write_text(...)` (the way `cmd_form_sweep` rewrites the calibration JSON at lines 489-491)
- Computing or storing a "winner"
- Setting `summary["is_winning_form"] = True` under any condition

A header docstring on the wrapper and implementation entry point makes this explicit:

```python
def cmd_form_sweep_full(conn, *, schema: str) -> None:
    """Full-history score-form sweep against canary_snapshots range.

    Candidate discovery only. DO NOT:
      - declare a winning form
      - write to canary-calibration-v1.json
      - set summary.is_winning_form=True
      - read or modify the OOS gate's LAST_KNOWN_AUC_* constants

    Any v2 calibration change requires a new spec and a reserved holdout
    window — not the data this run evaluates against.
    """
```

#### G-3. Persistence-level locks

The **keystone invisibility lock** is the dedicated `regime_backtest_runs.run_scope` column introduced in migration 059 (the same mechanism VCG already uses for its research runs):

- `run_scope: "research"` — hardcoded literal in the `insert_run(...)` call. `RegimeBacktestRepository.find_latest_run` (`src/uw_scan/storage/regime_backtest_repository.py:148-211`) filters `WHERE run_scope = %s` defaulting to `"production"`, so research-scoped rows are invisible to the OOS gate and `/api/regime/canary/validation` by construction. This is THE mechanism that prevents form_sweep_full output from being mistaken for a production form selection.

Additional persistence locks (defense in depth, none of which are the keystone — `run_scope` is):

- `summary.is_winning_form: False` is a hardcoded literal. Not a visibility filter, but a renderer/SQL-introspection convenience: any future query that asks "which run is the production form?" can also filter on this for redundancy.
- `params["phase"]: "form_sweep_full"` is a hardcoded literal.
- `composite_version` is `str(COMPOSITE_VERSION)` (imported constant; no CLI override).

#### G-4. Downstream-effect isolation

Three integration tests prove form_sweep_full rows do NOT bleed into v1 production surfaces. The mechanism is `run_scope='research'` (see G-3) — `find_latest_run` defaults to `run_scope='production'`, so research-scoped rows are filtered out at the SQL level, not at the Python level.

| Test | Asserts |
|---|---|
| `test_form_sweep_full_invisible_to_oos_gate` | `RegimeBacktestRepository.find_latest_run("canary", composite_version="1")` does not return a form_sweep_full row |
| `test_form_sweep_full_invisible_to_validation_api` | `GET /api/regime/canary/validation` payload unchanged before/after `cmd_form_sweep_full` |
| `test_form_sweep_full_does_not_write_calibration_file` | `canary-calibration-v1.json` mtime + SHA-256 unchanged after the run |

#### G-5. Re-run + version safety

Each invocation generates a fresh `batch_id` (UUID4) and appends 4 new rows tagged with it. No idempotent overwrite. Old batches remain available for cross-run comparison; cleanup happens via the cross-roadmap `archived_at` migration (out of scope here).

Renderer groups by `batch_id` (see §4.3). A future `COMPOSITE_VERSION` bump produces a new batch whose rows have a different `composite_version` column value; the loader's "latest complete batch" logic will naturally pick the v2 batch once it exists, and the `--runs` override lets users explicitly load a v1 batch for historical comparison.

Startup log surfaces existing batches so re-running isn't silent:

```text
INFO existing form_sweep_full batches: 1 (most recent batch=<uuid>, 4 rows, completed 2026-05-27 14:32 UTC)
INFO this invocation will create a new batch_id=<uuid>
```

#### G-6. Batch atomicity (cleanup-on-failure)

Per §4.2 ("Persistence atomicity"), if any persistence step fails partway through the 4 form inserts, all rows tagged with the script's `batch_id` are explicitly deleted before the script exits non-zero. The DB-level invariant is:

> After `cmd_form_sweep_full` returns or raises, the count of `regime_backtest_runs` rows with `params->>'batch_id' = <script's batch_id>` is either exactly 0 or exactly 4. Never any other value.

This is enforced by:

1. The script's `try/except` wrapper around the Phase 2 (persistence) loop in `cmd_form_sweep_full` — calls `_cleanup_batch` on any exception and re-raises.
2. The renderer's "load latest complete batch" logic (§4.3) — even if cleanup were to fail (e.g. DB outage between insert and cleanup), the renderer would skip the incomplete batch and load the previous complete one. Defense in depth.
3. An integration test that simulates a mid-run failure and asserts row-count = 0 for the failed `batch_id` (see §4.5).

### 4.5 Testing strategy

Five test buckets, total ~20-30s of runtime added.

#### Unit (no DB)

| File | Cases |
|---|---|
| `tests/unit/test_within_band_aucs.py` | 5 cases for `_within_band_aucs` (empty rows, empty band, all-same-label, normal, label-once-filter-by-index invariant) |
| `tests/unit/test_canary_form_sweep_cli.py` | 1 case proving the custom `--form-sweep-full` mutual-exclusion guard exits before DB/config loading |
| `tests/unit/test_canary_form_sweep_renderer.py` | 11 cases for `render_canary_form_sweep_compare` (canonical form ordering; missing form raises; duplicate form raises; <4 rows raises; mismatched `batch_id` across rows raises; non-research `run_scope` raises; footer present; **all 7 observations flag correctly** including the two new rules — composite-improves-over-linear, WATCH-reduce-without-AUC-loss) |

String-contains assertions on renderer output; no full-string snapshot (numbers will drift).

#### Integration (real Postgres via pytest-postgresql)

All in `tests/integration/regime/test_canary_form_sweep_full.py`:

| Test | Asserts |
|---|---|
| `test_delete_runs_by_batch_id_removes_rows_and_cascades_daily` | Repository cleanup deletes all runs for a `batch_id` and cascades `regime_backtest_daily` rows |
| `test_delete_runs_by_batch_id_returns_zero_when_no_match` | Repository cleanup is a no-op returning 0 for an unknown `batch_id` |
| `test_cmd_form_sweep_full_persists_4_rows_sharing_batch_id` | 4 research rows persisted, all forms present, all share one `batch_id` and `generated_at`, all `is_winning_form=false` |
| `test_cmd_form_sweep_full_writes_daily_rows` | Each form's run has at least one `regime_backtest_daily` row |
| `test_cmd_form_sweep_full_summary_schema` | `summary` JSONB has all required top-level keys and AUC/band subkeys |
| `test_form_sweep_full_cleanup_on_failure` | Monkey-patch `RegimeBacktestRepository.bulk_insert_daily` to trigger a real database error on the 3rd form's call, proving `conn.rollback()` happens before cleanup. After `cmd_form_sweep_full` raises, assert: zero rows with the failed `batch_id` in both `regime_backtest_runs` and `regime_backtest_daily`. Calibration JSON also unchanged. |
| `test_form_sweep_full_renderer_picks_latest_complete_batch` | Inject batch A (4 rows complete) + batch B (4 rows complete, later created_at); loader returns batch B's 4 rows |
| `test_renderer_skips_incomplete_batch` | Inject batch A (4 rows complete, earlier) + batch B (3 rows only — simulated mid-run-failure-without-cleanup, later created_at); loader returns batch A's 4 rows, NOT batch B |
| `test_form_sweep_full_does_not_write_calibration_file` | Calibration JSON mtime + SHA-256 unchanged |
| `test_form_sweep_full_invisible_to_oos_gate` | Find-latest-winning returns the pre-existing v1 row, not a form_sweep_full row |
| `test_form_sweep_full_invisible_to_validation_api` | Validation API payload unchanged |

Synthetic vol-complex fixture (400 days × 5 symbols) lives at `tests/integration/regime/_canary_form_sweep_fixture.py` per the colocation rule.

#### Explicitly skipped

| Skipped | Why |
|---|---|
| Generic argparse parsing | Upstream `argparse` behavior is not retested; the custom mutual-exclusion guard is covered by `tests/unit/test_canary_form_sweep_cli.py` |
| Frontend tests | No UI change; validation panel invisibility covered by §G-4 |
| OpenAPI / API contract tests | No new API endpoint |
| Performance / load | Runs once per investigation, not in hot path |
| Block-bootstrap reproducibility | `_block_bootstrap_auc_ci` already uses `seed=42`; covered by existing tests |
| Mocked-DB tests | Project policy bans mocked DB (`tests/CLAUDE.md`) |
| Explicit "OOS gate still passes" non-regression | §G-4 invisibility test already proves the gate cannot see form_sweep_full rows; redundant |

---

## 5. Acceptance criteria

The change is shippable when ALL of the following hold:

| # | Criterion |
|---|---|
| AC-1 | `uv run python scripts/backtest_canary.py --form-sweep-full` runs to completion without errors against the production-shaped DB |
| AC-2 | 4 new rows present in `regime_backtest_runs` with `params->>'phase' = 'form_sweep_full'`, one per `score_form` value, all sharing the **same `params->>'batch_id'`** (UUID, non-null) and the same `summary->>'generated_at'` |
| AC-3 | Each new row's `summary` matches the §4.2 schema (all fields present, no NaN tokens in JSONB) |
| AC-4 | `run_scope = 'research'` and `summary->>'is_winning_form' = 'false'` for all 4 new rows |
| AC-5 | `canary-calibration-v1.json` mtime + SHA-256 are unchanged after the run |
| AC-6 | `RegimeBacktestRepository.find_latest_run("canary", composite_version="1")` returns the pre-existing v1 winning row (run id 18 or equivalent), not a form_sweep_full row |
| AC-7 | `GET /api/regime/canary/validation` payload is byte-identical before and after the run |
| AC-8 | Stdout shows the 4-form comparison table + "Observations" block + "What this run does NOT decide" footer |
| AC-9 | `uv run python -m uw_scan.reports.regime_canary_backtest_report` (no additional args; `--mode` defaults to `form_sweep_compare`) reproduces the same table by loading the latest complete `batch_id` |
| AC-10 | All 11 integration tests + 3 unit test files pass (`uv run pytest tests/unit/test_within_band_aucs.py tests/unit/test_canary_form_sweep_cli.py tests/unit/test_canary_form_sweep_renderer.py tests/integration/regime/test_canary_form_sweep_full.py`) |
| AC-11 | Existing OOS gate test (`tests/integration/regime/test_canary_oos_gate.py`) continues to pass |
| AC-12 | `/review-cycle` runs cleanly on the final change (multi-pass review per the project's review discipline; wraps `/codex-review` plus adversarial + assumption-verification passes) |
| AC-13 | **Atomicity invariant**: after `cmd_form_sweep_full` returns or raises, the count of `regime_backtest_runs` rows with `params->>'batch_id' = <script's batch_id>` is either exactly 0 (failure path with successful cleanup) or exactly 4 (success path). Asserted by `test_form_sweep_full_cleanup_on_failure` for the failure path and by `test_cmd_form_sweep_full_persists_4_rows_sharing_batch_id` for the success path. |

---

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Output is read as "X is the winner" and someone manually edits the calibration JSON | G-2 (function isolation), G-3 (hardcoded `is_winning_form=false`), G-4 (downstream-invisibility tests), renderer footer "What this run does NOT decide" |
| Future contributor refactors `cmd_form_sweep` and the changes bleed into `cmd_form_sweep_full` | Separate functions, separate test files. Any shared-helper change has to pass both test suites. |
| `COMPOSITE_VERSION` bumps later and form_sweep_full rows from v1 silently mix into v2 comparisons | G-5: each invocation generates a fresh `batch_id` at a single `COMPOSITE_VERSION`, so cross-version mixing inside a single batch is structurally impossible. The renderer's "latest complete batch" loader picks the v2 batch once it exists. `--runs` override is required to explicitly compare a v1 batch vs a v2 batch. |
| Mid-run failure leaves partial rows that contaminate later loads | G-6: cleanup-on-failure via `_cleanup_batch(batch_id)`. Renderer "skip incomplete batches" provides defense in depth. Tested by `test_form_sweep_full_cleanup_on_failure` + `test_renderer_skips_incomplete_batch`. |
| Re-running creates DB bloat | Each run = 4 rows + ~15K daily rows. Modest. `archived_at` migration (cross-roadmap) provides cleanup once it lands. |
| Block-bootstrap CI on 3,843-day series is slow | `iters=1000, block_size=20` — same parameters used by walk-forward (run id ranges 19-24 each completed in <1 min). 4 forms × 3 horizons = 12 CIs total. Total ~30s additional. |
| Synthetic vol-complex fixture for end-to-end test is coherent enough to run but unrealistic enough to mislead | The end-to-end test only verifies **shape** (4 rows, correct fields, no errors), not specific AUC values. AUC correctness is covered separately by `_aucs_for_rows` tests (existing) and `_within_band_aucs` unit tests. |
| Renderer's "Observations" rules calcify and become misleading later | Rules are hardcoded thresholds (30%, 0.50, +0.02) — easy to read and change in one file. Each rule has a comment explaining the threshold's basis. |

---

## 7. Out of scope (deferred to future specs)

- v2-A architecture change (drop speed from composite, expose `vol_resolution_score` / `speed_state` / `display_score` separately)
- v2-B band threshold changes (lower STRONG_BUY)
- v2-C calibration retune (depends on this run's output)
- v2-D capitulation scorer
- UI window picker on validation panel
- `regime_backtest_runs.archived_at` migration (cross-roadmap with VCG)
- Form-sweep against indicators other than canary

Any of these may eventually consume this spec's output, but none are part of this implementation.

---

## 8. Open questions

None blocking implementation. Two non-blocking questions to revisit when the run output is in:

- Should the renderer's "Observations" rules become tunable (config file) once a v2 calibration is shipped? Today they're hardcoded; that's correct for v1's frozen-baseline posture.
- Should there be a sibling sweep against the **walk-forward windows** (WF-1..WF-6 from `canary-5yr-executive-summary.md` §8) rather than the full dataset? Likely a separate follow-up spec if the form_sweep_full result is ambiguous.

---

## 9. References

- v1 design spec: `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md`
- v1 executive summary: `docs/research/regime/canary-5yr-executive-summary.md`
- Roadmap: `docs/research/regime/canary-next-steps-2026-05-27.md`
- Methodology: `docs/research/regime/canary-methodology.md`
- Existing form-sweep: `scripts/backtest_canary.py:408-493`
- Existing canary series compute: `scripts/backtest_canary.py:175-279`
- Existing AUC helpers: `scripts/backtest_canary.py:662-719`
- Existing CRI renderer (pattern): `src/uw_scan/reports/regime_backtest_report.py`
- Existing VCG renderer (pattern): `src/uw_scan/reports/regime_vcg_backtest_report.py`
- Test conventions: `tests/CLAUDE.md`
- Research workspace conventions: `docs/research/regime/CLAUDE.md`
