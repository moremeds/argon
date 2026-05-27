# Canary v2-A — Vol/Speed Separation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only PR 1 that produces evidence for the v2-A formula change (drop additive `speed.score` from canary composite when `composite_version >= 2`). Zero production-surface change in PR 1; AC-F1..F6 evidence in PR 1 gates PR 2's production flip.

**Architecture:** A 4-line conditional in `run_analysis()` keyed on `calibration.composite_version`. A new `canary-calibration-v2.json` holding identical thresholds but `composite_version=2`. Research backfill writes `composite_version=2` snapshots (invisible to production via column filter). Walk-forward + robustness write `run_scope='research'` rows (invisible via `find_latest_run`'s production default). A pure renderer evaluates pre-committed AC-F1..F6 from a `FlipGateEvidence` dataclass; the dispatcher in `backtest_canary.py --v1-v2-compare` assembles the bundle from DB.

**Tech Stack:** Python 3.13 + `uv`; pytest + pytest-postgresql for integration tests; Postgres for persistence (`canary_snapshots`, `regime_backtest_runs`, `regime_backtest_daily`); `psycopg` for DB access; dataclasses for `Calibration` and `FlipGateEvidence`.

**Spec:** `docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md` (commit `09a2ea8`, post `/review-cycle`).

---

## ⚠️ Pass-4 Critical Amendments — READ BEFORE EXECUTING

This plan went through `/review-cycle` after the first draft and revealed **20+ findings** including 5 plan-as-written-cannot-execute defects. The amendments below are load-bearing — apply them as you reach the corresponding tasks. The original task bodies below were drafted before these findings surfaced; treat the amendments as authoritative when they conflict.

### CRITICAL amendments (must apply)

**A-C1 (Task 5, 6, 10, 11): NO `subprocess.run` for integration tests.** `Settings.from_env()` reads `UW_SCAN_DB_*` env vars (not `DATABASE_URL`), so `subprocess.run(env={"DATABASE_URL": test_db_url})` would silently hit the **dev DB `option_wizard`** and could MUTATE IT. Replace every `subprocess.run(...)` in test code with **in-process invocation**: call `cmd_backfill(conn, schema=schema, args=argparse.Namespace(...))` / `cmd_walk_forward(conn, schema=schema, args=...)` / `cmd_v1_v2_compare(conn, schema=schema)` directly. Use `seeded_db_empty_cards.conn` + `_schema` (the existing form-sweep precedent in PR #88).

**A-C2 (Task 5): `canary_backfill.py` must be refactored to expose `cmd_backfill(conn, *, schema, args)`** that accepts a connection + namespace. The existing `main()` continues to work for the daily APScheduler job by building conn from `Settings.from_env()` then calling `cmd_backfill`. Estimated +25 LOC of restructuring on top of the +35 already planned. The current `--days N` data-load span (`max(800, args.days + 500)` at line 111) **does not** honor `--start-date` for dates older than ~3 years; when `--start-date` is supplied, compute the required load span from the date range so 2011 dates are actually loaded. Use `trade_date` (NOT `data_date`) when querying `vol_index_daily` (verified: `vol_index_repository.py:65`).

**A-C3 (Task 6): The current `cmd_walk_forward` DOES NOT write `batch_id` to params** (verified: `backtest_canary.py:827-840` shows only `score_form/phase/window_id/train_end`). The plan claimed otherwise — **that was wrong**. Task 6 must ADD batch_id generation: `batch_id = args.batch_id or str(uuid.uuid4())` BEFORE the per-window loop, and include `"batch_id": batch_id` in every walk-forward's params dict. Print the batch_id to stdout so Task 7's robustness can be chained with `--batch-id`.

**A-C4 (Tasks 9 + 10): EXTRACT new module `src/uw_scan/reports/regime_canary_v1_v2_compare.py`** that owns `FlipGateEvidence`, `_assemble_flip_gate_evidence`, `render_canary_v1_v2_compare`, the AC-F1..F6 helpers, and the standalone CLI `main()`. The current `scripts/backtest_canary.py` is **1,174 lines** (verified) — adding the dispatcher in-place pushes it well over the codebase's "no new methods on >1,000 LOC files without a split plan" convention. PR #88 handled the analogous problem by extracting `regime_canary_form_sweep_full.py`; mirror that pattern. `backtest_canary.py` gets only a thin ~30-LOC `cmd_v1_v2_compare(conn, *, schema)` that imports from the new module.

**A-C5 (Task 10): Full-history AUC computation cannot use `_aucs_for_rows` on `canary_snapshots` rows.** The snapshot `payload` JSONB nests scores as `tactical_vol.score`, `structural_vol.score`, `speed.score` — NOT the flat keys the plan's SQL projects. And `_aucs_for_rows` → `_entry_lagged_label` requires `r["spx"]` per row for forward-return labels, which snapshots don't carry. **Correct approach**: in `_assemble_flip_gate_evidence`, compute both `v1_full_history_aucs` and `v2_full_history_aucs` by calling `_compute_canary_series(conn, calibration, form='linear', start, end, schema)` (the form-sweep helper that already exists) with the appropriate calibration — this returns `eval_rows` with `spx` populated, then passes them to `_aucs_for_rows`. Apples-to-apples by construction.

**A-C6 (Tasks 2 ↔ 3 reorder): Capture the v1 payload-hash golden BEFORE applying the conditional path edit.** Task 3 (Conditional path) must run AFTER Task 2 (Golden capture + test). The original draft put them in the opposite order, which would let a bug in the conditional silently bless itself. The task numbering in the document has been updated, but the task BODIES below are still in the original order — when implementing, execute Task 3 (Golden) before Task 2 (Conditional) per the corrected Task Order at the top.

### IMPORTANT amendments

**A-I1 (Task 5): Idempotency by payload-hash, not just date+version.** A `SELECT 1 → continue` check silently keeps stale rows from earlier failed runs that had bugs. Compute a canonical SHA-256 of the new payload, compare with the existing row's stored hash, and FAIL LOUDLY (require `--overwrite`) on mismatch. The canary payload-hash module (`src/uw_scan/cards/canary_payload_hash.py`, verified to exist) provides the canonical hash function.

**A-I2 (Task 10): Dispatcher reload queries must include full scope/version/completion filters.** Selecting v2 walk-forward rows by `batch_id + phase` alone is insufficient — partial-row contamination or scope collision could pollute evidence. Every reload query must explicitly filter `indicator='canary' AND run_scope='research' AND composite_version='2' AND completed_at IS NOT NULL`.

**A-I3 (Task 10): Subprocess invocations in `_run_test_subprocess` must preserve parent PATH.** The dispatcher calls `uv run pytest …`, but `uv` is at `~/.cargo/bin/uv` on macOS — outside `/usr/bin:/bin`. Use `env=os.environ.copy()` (default behavior — just omit the env kwarg) rather than replacing PATH wholesale.

**A-I4 (Task 10): Integration test for `--v1-v2-compare` should mock `_run_test_subprocess`** to avoid nested pytest invocations (pytest-in-pytest is known to corrupt state). In live smoke (Task 12), the real subprocess runs cleanly because there's no outer pytest context.

**A-I5 (Task 2 — formula tests): Assert v1↔v2 raw-score deltas directly**, not absolute computed sums. `payload["tactical_vol"]["score"]` is rounded to 2 decimals, but `raw_score` rounds the sum AFTER adding unrounded components — equality can drift by 0.01.

**A-I6 (Task 12): Non-regression test paths.** `tests/integration/regime/test_canary_backtest.py` **does not exist** (verified). Replace with `tests/integration/regime/test_canary_scanner.py` + `tests/integration/regime/test_canary_oos_gate.py` + the new v2 files.

**A-I7 (Task 11): In-process mock pattern.** With A-C1 applied, the cleanup test calls `cmd_walk_forward(conn, schema=schema, args=fake_args)` directly. Use `mocker.patch.object(RegimeBacktestRepository, "bulk_insert_daily", side_effect=...)` (pytest-mock — already in the project's deps) with a `side_effect` callable that captures call count, raises on the 4th call, and otherwise delegates to the real method via `wraps`. Replace the literal `original_bulk_insert = ...` placeholder in the original Task 11 body with concrete code.

### MINOR amendments (apply if cheap)

**A-M1 (Tasks 2, 4, 9, 10):** Remove unused imports from sample code blocks: `math` in Task 2, `psycopg` in Task 4, `field`/`Mapping`/unused `args` in Task 9, unused `conn` in Task 10. Will fail `ruff` otherwise.

**A-M2 (Task 12 Step 7 → AC-7):** Replace the targeted pytest command with an explicit `uv run ruff check src/ tests/ scripts/` invocation (AC-7 of the spec is a ruff check, not a pytest run).

**A-M3 (line refs):** `insert_snapshot` is at `canary_backfill.py:173` (not "around line 176" as some passages claim). Minor — "around line N" is the convention.

---

## File Structure

| Path | New / Modified | Purpose |
|---|---|---|
| `src/uw_scan/cards/canary_scoring.py` | Modified | 4-line conditional in `run_analysis()` keyed on `calibration.composite_version` |
| `docs/research/regime/canary-calibration-v2.json` | New | Same 5 vol-scorer thresholds as v1; `composite_version: 2`; `score_form: "linear"` |
| `scripts/canary_backfill.py` | Modified | **Refactored to expose `cmd_backfill(conn, *, schema, args)`** (per A-C2). Add `--composite-version`, `--start-date`, `--end-date` flags; load v2 calibration explicitly; persist `cal.composite_version` (not module constant); idempotent re-run via payload-hash check (A-I1). Existing `main()` still wraps for the daily APScheduler job. |
| `scripts/backtest_canary.py` | Modified | **Refactor `cmd_walk_forward`/`cmd_robustness` signatures to accept `args`** for in-process testing (A-C1). **Add `batch_id` generation** in walk-forward (A-C3 — currently missing). Add thin ~30-LOC `cmd_v1_v2_compare(conn, *, schema)` that imports from the new module. Add `--composite-version` flag throughout. |
| `src/uw_scan/reports/regime_canary_v1_v2_compare.py` | **NEW MODULE (per A-C4)** | Owns `FlipGateEvidence` dataclass + `_assemble_flip_gate_evidence(conn, schema)` + `_full_history_aucs_via_compute_canary_series(conn, cal, schema)` (per A-C5) + `_band_distribution_for_version` + `render_canary_v1_v2_compare(ev) -> str` pure renderer + standalone CLI `main()`. Keeps `backtest_canary.py` under the 1,000-LOC convention. |
| `src/uw_scan/storage/regime_backtest_repository.py` | Modified | Add `delete_canary_research_runs_by_batch_id_and_phase(batch_id, phase) -> int` |
| `tests/integration/regime/_canary_v2a_fixture.py` | **NEW (Task 0, per A-I4)** | Helper functions: `seed_vol_index_full_history`, `seed_v1_walk_forward_runs`, `seed_v2_walk_forward_runs`, `seed_canary_snapshots_v2` |
| `tests/unit/test_canary_v2_formula.py` | New | ~9 unit tests covering the conditional path (deltas not absolute sums per A-I5) |
| `tests/unit/test_canary_v1_payload_hash_golden.py` | New | ~3 unit tests: golden v1 scoring hash regression (captured BEFORE Task 3 per A-C6) |
| `tests/unit/test_canary_v1_v2_compare_renderer.py` | New | ~16 unit tests for the renderer + AC-F1..F6 evaluation |
| `tests/integration/regime/test_canary_v2_backfill.py` | New | ~7 integration tests for backfill + AC-F3 evidence test. **In-process invocation via `cmd_backfill(conn, schema, args)`** (per A-C1, A-C2). |
| `tests/integration/regime/test_canary_v2_walk_forward.py` | New | ~9 integration tests for walk-forward + robustness + parity + cleanup-on-failure + cross-scope renderer load. **In-process invocation throughout** (per A-C1). |

**Net LOC**: ~400–550 new code + ~30 net additions to existing files. ~44 new tests. ~40-60s of new test runtime.

---

## Task Order

Tasks are ordered for safe dependencies. **Per-task dependency footnotes are shown in each task header.** The golden-baseline task (T2) deliberately runs BEFORE the formula-change task (T3) so the captured pre-v2A hash isn't trivially blessed by a bug in the change itself.

0. **Task 0**: Build the v2-A fixture helpers in `tests/integration/regime/_canary_v2a_fixture.py` (no production code; pure test infrastructure)
1. **Task 1**: New `canary-calibration-v2.json` + unit test that loader parses it
2. **Task 2**: **Capture v1 golden payload hash from current code (BEFORE Task 3)** + golden test
3. **Task 3**: Apply conditional path in `run_analysis()` (unit tests + minimal code edit)
4. **Task 4**: New repo method `delete_canary_research_runs_by_batch_id_and_phase`
5. **Task 5**: `canary_backfill.py` full refactor — expose `cmd_backfill(conn, *, schema, args)`, add `--composite-version` + `--start-date` / `--end-date` flags + idempotency-via-payload-hash + AC-F3 evidence
6. **Task 6**: `backtest_canary.py --walk-forward --composite-version 2` — **adds `batch_id` generation** (current code does not write one), exposes `cmd_walk_forward(conn, *, schema, args)` for in-process testing
7. **Task 7**: `backtest_canary.py --robustness --composite-version 2` + chained `--batch-id`
8. **Task 8**: Walk-forward recompute vs backfill parity test (AC-4b)
9. **Task 9**: **NEW MODULE** `src/uw_scan/reports/regime_canary_v1_v2_compare.py` owning `FlipGateEvidence` + `_assemble_flip_gate_evidence` + `render_canary_v1_v2_compare` + standalone CLI. Keeps `backtest_canary.py` from growing beyond the 1,000-LOC convention.
10. **Task 10**: Thin `--v1-v2-compare` CLI dispatcher in `backtest_canary.py` (≤30 LOC) that delegates to the Task-9 module + integration test
11. **Task 11**: Walk-forward cleanup-on-failure (in-process mock — subprocess can't catch this)
12. **Task 12**: Final smoke + live verification (with correct non-regression test paths)

---

### Task 0: Build v2-A fixture helpers (`_canary_v2a_fixture.py`)

**Files:**
- Create: `tests/integration/regime/_canary_v2a_fixture.py`
- Read for reference: `tests/integration/regime/_canary_form_sweep_fixture.py` (the PR #88 precedent)

**Rationale:** Subsequent tasks reference fixture helpers (`seed_vol_index_full_history`, `seed_v2_backfill`, `seed_v1_walk_forward_runs`, etc.) that don't exist. Build them as pure helper functions that take a connection + schema and seed deterministic test data. **No subprocess. No DB-URL plumbing. The in-process fixtures use `seeded_db_empty_cards.conn` from the existing project-wide conftest.**

- [ ] **Step 1: Create the fixture helpers**

Path: `tests/integration/regime/_canary_v2a_fixture.py`

```python
"""Test-only seed helpers for canary v2-A integration tests.

Each function takes (conn, *, schema) — operates on the per-test DB
provided by tests/integration/conftest.py's seeded_db_empty_cards fixture.
No subprocess, no env-var plumbing.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Sequence

import numpy as np


def _trading_days(start: date, n: int) -> list[date]:
    """Return n consecutive business-day-ish dates from start (skips Sat/Sun)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d = d + timedelta(days=1)
    return out


def seed_vol_index_full_history(
    conn,
    *,
    schema: str,
    start: date = date(2011, 2, 8),
    end: date = date(2026, 5, 21),
    seed: int = 42,
) -> list[date]:
    """Seed vol_index_daily with synthetic but realistic data covering [start, end].

    Returns the list of trade_dates inserted. SPX path is a sinusoidal + linear
    drift (guarantees mixed labels at all 3 forward horizons) so AUC computations
    don't degenerate.
    """
    dates = _trading_days(start, (end - start).days)
    dates = [d for d in dates if d <= end]
    n = len(dates)

    rng = np.random.default_rng(seed)
    spx = np.clip(1000.0 + 8.0 * np.sin(np.arange(n) / 7.0) + 0.05 * np.arange(n), 600.0, 6000.0)
    vix = np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 50.0)
    vvix = np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0)
    vix3m = np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0)
    cor1m = np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0)

    with conn.cursor() as cur:
        for i, d in enumerate(dates):
            for symbol, close in (
                ("SPX", spx[i]), ("VIX", vix[i]), ("VVIX", vvix[i]),
                ("VIX3M", vix3m[i]), ("COR1M", cor1m[i]),
            ):
                cur.execute(
                    f"INSERT INTO {schema}.vol_index_daily "
                    f"(symbol, trade_date, open, high, low, close, adj_close, volume) "
                    f"VALUES (%s, %s, %s, %s, %s, %s, %s, 0) "
                    f"ON CONFLICT (symbol, trade_date) DO NOTHING",
                    (symbol, d, float(close), float(close), float(close), float(close), float(close)),
                )
    conn.commit()
    return dates


def seed_v1_walk_forward_runs(conn, *, schema: str) -> list[int]:
    """Seed 6 v1 walk-forward production runs (the PR #83 baseline).

    Each row has summary.aucs.composite.{up5d_2pct,up20d_5pct,up60d_10pct}.
    Returns the list of inserted run_ids.
    """
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = RegimeBacktestRepository(conn, schema=schema)
    ids: list[int] = []
    windows = [
        ("WF-1", date(2015, 1, 2), date(2016, 12, 30), 0.642),
        ("WF-2", date(2017, 1, 3), date(2018, 12, 31), 0.610),
        ("WF-3", date(2019, 1, 2), date(2020, 9, 30), 0.655),
        ("WF-4", date(2020, 10, 1), date(2022, 12, 30), 0.628),
        ("WF-5", date(2023, 1, 3), date(2024, 12, 31), 0.601),
        ("WF-6", date(2025, 1, 2), date(2026, 5, 21), 0.633),
    ]
    for wid, sd, ed, auc60 in windows:
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="1",
            start_date=sd,
            end_date=ed,
            window_days=350,
            n_days=(ed - sd).days,
            params={
                "phase": "walk_forward",
                "score_form": "linear",
                "window_id": wid,
                "train_end": "2014-12-31",
            },
            summary={
                "aucs": {
                    "composite": {"up5d_2pct": 0.58, "up20d_5pct": 0.56, "up60d_10pct": auc60},
                    "vol_only": {"up5d_2pct": 0.57, "up20d_5pct": 0.51, "up60d_10pct": auc60 + 0.01},
                    "speed_only": {"up5d_2pct": 0.55, "up20d_5pct": 0.62, "up60d_10pct": 0.49},
                },
                "n_days": (ed - sd).days,
                "window_id": wid,
            },
            run_scope="production",
        )
        repo.mark_run_completed(run_id)
        ids.append(run_id)
    return ids


def seed_v2_walk_forward_runs(
    conn, *, schema: str, batch_id: str | None = None, per_window_60d_auc: float = 0.65
) -> tuple[str, list[int]]:
    """Seed 6 v2 walk-forward research runs + 1 v2 robustness research run,
    all sharing a batch_id. Returns (batch_id, run_ids)."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    if batch_id is None:
        batch_id = str(uuid.uuid4())
    repo = RegimeBacktestRepository(conn, schema=schema)
    ids: list[int] = []
    for i, wid in enumerate(("WF-1", "WF-2", "WF-3", "WF-4", "WF-5", "WF-6")):
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="2",
            start_date=date(2015 + 2 * i, 1, 2),
            end_date=date(2015 + 2 * i + 1, 12, 30),
            window_days=350,
            n_days=500,
            params={
                "phase": "walk_forward",
                "score_form": "linear",
                "window_id": wid,
                "batch_id": batch_id,
            },
            summary={
                "aucs": {
                    "composite": {"up5d_2pct": 0.62, "up20d_5pct": 0.64, "up60d_10pct": per_window_60d_auc},
                    "vol_only": {"up5d_2pct": 0.62, "up20d_5pct": 0.64, "up60d_10pct": per_window_60d_auc},
                    "speed_only": {"up5d_2pct": 0.50, "up20d_5pct": 0.50, "up60d_10pct": 0.50},
                },
                "n_days": 500,
                "window_id": wid,
            },
            run_scope="research",
        )
        repo.mark_run_completed(run_id)
        ids.append(run_id)
    rob_id = repo.insert_run(
        indicator="canary",
        composite_version="2",
        start_date=date(2011, 2, 8),
        end_date=date(2026, 5, 21),
        window_days=350,
        n_days=3843,
        params={"phase": "robustness", "score_form": "linear", "batch_id": batch_id},
        summary={"aucs": {"composite": {"up60d_10pct": 0.642}}},
        run_scope="research",
    )
    repo.mark_run_completed(rob_id)
    return batch_id, ids + [rob_id]


def seed_canary_snapshots_v2(
    conn, *, schema: str, dates: Sequence[date], cca_dates: Sequence[date] = (),
) -> int:
    """Seed v2 canary_snapshots for the given dates. Rows where data_date is in
    cca_dates get payload.speed.confirmed_canary_active=True to satisfy AC-F3.
    Returns row count."""
    cca_set = set(cca_dates)
    rng = np.random.default_rng(123)
    inserted = 0
    with conn.cursor() as cur:
        for d in dates:
            cca = d in cca_set
            score = float(rng.uniform(0, 70))
            band = "NONE" if score < 25 else ("WATCH" if score < 50 else ("BUY" if score < 75 else "STRONG_BUY"))
            payload = {
                "tactical_vol": {"score": round(score * 0.4, 2)},
                "structural_vol": {"score": round(score * 0.6, 2)},
                "speed": {
                    "score": 0 if cca else 8,
                    "state": "CONFIRMED_CANARY_ACTIVE" if cca else "NEUTRAL",
                    "confirmed_canary_active": cca,
                    "buy_the_dip_active": False,
                },
                "canary": {
                    "score": round(score, 2),
                    "raw_score": round(score, 2),
                    "band": band,
                    "warning_state": "CONFIRMED_CANARY_ACTIVE" if cca else "NONE",
                    "composite_version": 2,
                    "score_form": "linear",
                },
                "inputs": {"spx_close": float(1000.0 + d.toordinal() % 500)},
            }
            cur.execute(
                f"INSERT INTO {schema}.canary_snapshots "
                f"(data_date, composite_version, score, raw_score, band, "
                f" warning_state, score_form, payload) "
                f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (d, 2, score, score, band,
                 payload["canary"]["warning_state"], "linear",
                 __import__("json").dumps(payload)),
            )
            inserted += 1
    conn.commit()
    return inserted
```

- [ ] **Step 2: Run a smoke check on the helpers**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run python -c "
from tests.integration.regime._canary_v2a_fixture import (
    seed_vol_index_full_history, seed_v1_walk_forward_runs,
    seed_v2_walk_forward_runs, seed_canary_snapshots_v2,
)
print('imports OK')
"
```

Expected: `imports OK` (no syntax errors).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/regime/_canary_v2a_fixture.py
git commit -m "test(canary): v2-A integration fixture helpers (Task 0)

New _canary_v2a_fixture.py with 4 helpers used by Tasks 4-11:
- seed_vol_index_full_history (15-year synthetic vol-complex)
- seed_v1_walk_forward_runs (6 production rows, PR #83 baseline)
- seed_v2_walk_forward_runs (6 walk-forward + 1 robustness, shared batch_id)
- seed_canary_snapshots_v2 (research snapshots with optional CCA dates for AC-F3)

All helpers take (conn, *, schema) and use seeded_db_empty_cards as
the host fixture per the existing form-sweep precedent (PR #88).
No subprocess. No DB-URL plumbing.

Task-0 dep: none. Subsequent tasks call these helpers from their tests."
```

---

### Task 1: New `canary-calibration-v2.json` + loader-parses-v2 test

**Files:**
- Create: `docs/research/regime/canary-calibration-v2.json`
- Create: `tests/unit/test_canary_v2_formula.py`
- Read for reference: `docs/research/regime/canary-calibration-v1.json`, `src/uw_scan/cards/canary_calibration.py`

**Rationale:** Calibration parsing is the lowest-dependency unit. We start here so subsequent tasks (which load the v2 calibration) have a known-good artifact.

- [ ] **Step 1: Create the v2 calibration JSON**

Path: `docs/research/regime/canary-calibration-v2.json`

```json
{
  "composite_version": 2,
  "train_window": {"start": "2007-01-01", "end": "2014-12-31"},
  "score_form": "linear",
  "thresholds": {
    "vix_spike_revert":     {"floor": 0.05, "ceiling": 0.30, "spike_active_at_vix": 30.0, "peak_lookback_d": 10, "max_points": 15},
    "vix_vix3m_back":       {"floor": 0.05, "ceiling": 0.20, "backwardation_extreme_at_ratio": 1.05, "peak_lookback_d": 10, "max_points": 15},
    "vrp":                  {"floor": 50.0, "ceiling": 300.0, "rv_window_d": 20, "max_points": 21},
    "cor1m_decay":          {"floor": 0.05, "ceiling": 0.30, "peak_elevated_at": 60.0, "peak_lookback_d": 60, "max_points": 17},
    "vvix_vix_recovery":    {"floor": 3.5,  "ceiling": 5.0,  "compressed_below_ratio": 4.0, "compress_lookback_d": 60, "max_points": 12}
  },
  "band_distribution_train": null,
  "author_overrides": [],
  "produced_at": "2026-05-27T00:00:00Z",
  "produced_by": "v2-A vol/speed separation (PR for issue #89)"
}
```

Note: thresholds and `score_form` are IDENTICAL to v1. Only `composite_version` (1→2), `produced_at`, and `produced_by` change. Spec §5.4.

- [ ] **Step 2: Write the failing test**

Path: `tests/unit/test_canary_v2_formula.py`

```python
"""Unit tests for canary v2-A vol/speed separation.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.cards.canary_calibration import Calibration, load_calibration

V2_JSON = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "research"
    / "regime"
    / "canary-calibration-v2.json"
)


def test_v2_calibration_parses_with_version_2():
    """The v2 JSON parses into a Calibration with composite_version=2."""
    cal = load_calibration(path=V2_JSON)
    assert isinstance(cal, Calibration)
    assert cal.composite_version == 2
    assert cal.score_form == "linear"


def test_v2_calibration_thresholds_match_v1():
    """v2 thresholds are bit-identical to v1 (only the version field changes).

    This is deliberate: v2-A tests a structural formula change with v1
    calibration held fixed, so any AUC change is attributable to the
    formula change, not threshold drift. Spec §5.4.
    """
    v1_json = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "research"
        / "regime"
        / "canary-calibration-v1.json"
    )
    v1 = load_calibration(path=v1_json)
    v2 = load_calibration(path=V2_JSON)
    assert v1.vix_spike_revert == v2.vix_spike_revert
    assert v1.vix_vix3m_back == v2.vix_vix3m_back
    assert v1.vrp == v2.vrp
    assert v1.cor1m_decay == v2.cor1m_decay
    assert v1.vvix_vix_recovery == v2.vvix_vix_recovery
    assert v1.score_form == v2.score_form
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_canary_v2_formula.py -v
```

Expected: 2 passed.

(These tests don't depend on canary_scoring.py changes — they exercise only the calibration loader, which already handles arbitrary composite_version values per spec §4 invariant 6.)

- [ ] **Step 4: Verify no production-surface change**

```bash
md5 docs/research/regime/canary-calibration-v1.json
```

Expected: `407024fadb7e7b46417f08f4d019d991` (unchanged from PR #88).

- [ ] **Step 5: Commit**

```bash
git add docs/research/regime/canary-calibration-v2.json tests/unit/test_canary_v2_formula.py
git commit -m "feat(canary): v2-A calibration JSON + loader-parses-v2 tests

New canary-calibration-v2.json — same 5 thresholds as v1, only the
composite_version field changes (1 -> 2). The loader is reused as-is;
spec §4 invariant 6 already supported arbitrary composite_version.

This is the lowest-dependency artifact. Subsequent tasks (formula
conditional, backfill, walk-forward) load this file to compute v2
scores."
```

---

### Task 2: Conditional path in `run_analysis()`

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (around line 540, inside `run_analysis()`)
- Modify: `tests/unit/test_canary_v2_formula.py` (extend with formula tests)

**Rationale:** The structural code change. 4 lines + comment. The v1 path is preserved by `else:` — v1 production behavior is bit-identical.

- [ ] **Step 1: Write the failing tests for the formula conditional**

Append to `tests/unit/test_canary_v2_formula.py`:

```python
import math
from datetime import date as _date

import numpy as np

from uw_scan.cards import canary_scoring


def _fixed_aligned_arrays(n: int = 400, seed: int = 0) -> dict:
    """Synthetic aligned vol-complex arrays sized for the MIN_ALIGNED_BARS=350 gate.

    Deterministic per seed. Used by formula tests where we need run_analysis() to
    actually compute a payload but don't care about the exact regime label.
    """
    rng = np.random.default_rng(seed)
    return {
        "VIX": np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX": np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX": np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }


def _fixed_common_dates(n: int = 400) -> list[str]:
    """Generate n consecutive business-day-ish ISO date strings ending at a fixed date."""
    base = _date(2020, 6, 1)
    return [
        ((_date.fromordinal(base.toordinal() - (n - 1 - i)))).isoformat() for i in range(n)
    ]


def _run_for_version(version: int, *, cca=False, btd=False) -> dict:
    """Run analysis once with the v1 calibration, then mutate version on the
    Calibration object for the v2 path. Uses identical inputs."""
    cal = load_calibration()
    if cal.composite_version != version:
        cal = Calibration(
            composite_version=version,
            score_form=cal.score_form,
            vix_spike_revert=cal.vix_spike_revert,
            vix_vix3m_back=cal.vix_vix3m_back,
            vrp=cal.vrp,
            cor1m_decay=cal.cor1m_decay,
            vvix_vix_recovery=cal.vvix_vix_recovery,
        )
    aligned = _fixed_aligned_arrays(n=400, seed=42)
    dates = _fixed_common_dates(n=400)
    return canary_scoring.run_analysis(
        today=_date.fromisoformat(dates[-1]),
        aligned=aligned,
        common_dates=dates,
        sma_50_today=float(aligned["SPX"][-50:].mean()),
        sma_200_today=float(aligned["SPX"][-200:].mean()),
        spx_above_sma200_2d=True,
        vix_term_normalized=True,
        higher_closing_low=True,
        confirmed_canary_active=cca,
        buy_the_dip_active=btd,
        calibration=cal,
    )


def test_v1_path_unchanged_when_no_speed_state():
    """v1: NEUTRAL speed (no CCA, no BTD) → raw = tactical + structural + 8."""
    p1 = _run_for_version(1, cca=False, btd=False)
    canary = p1["canary"]
    tactical = p1["tactical_vol"]["score"]
    structural = p1["structural_vol"]["score"]
    speed_score = p1["speed"]["score"]
    assert speed_score == 8  # NEUTRAL contributes 8 to raw
    expected_raw = max(0.0, min(100.0, tactical + structural + speed_score))
    assert canary["raw_score"] == round(expected_raw, 2)


def test_v2_path_drops_speed_term_when_neutral():
    """v2: NEUTRAL → raw = tactical + structural (no +8)."""
    p1 = _run_for_version(1, cca=False, btd=False)
    p2 = _run_for_version(2, cca=False, btd=False)
    delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
    # v1 raw should be 8 higher than v2 raw (or less if clamping at 100).
    # The clamp guard: v1 raw clamped at 100 means delta could be < 8.
    v1_raw_pre_clamp = (
        p1["tactical_vol"]["score"] + p1["structural_vol"]["score"] + 8
    )
    if v1_raw_pre_clamp <= 100.0:
        assert abs(delta - 8.0) < 1e-6
    else:
        # Both clamped; check v2 raw is the clamped tactical + structural
        v2_expected = max(
            0.0, min(100.0, p2["tactical_vol"]["score"] + p2["structural_vol"]["score"])
        )
        assert abs(p2["canary"]["raw_score"] - round(v2_expected, 2)) < 1e-6


def test_v2_path_drops_speed_term_when_btd_active():
    """v2 BTD: raw = tactical + structural (no +20)."""
    p1 = _run_for_version(1, cca=False, btd=True)
    p2 = _run_for_version(2, cca=False, btd=True)
    # v1 has +20 from BUY_THE_DIP_ACTIVE; v2 has 0.
    # The v2 raw should equal v1 raw - 20 (modulo clamping).
    assert p1["speed"]["state"] == "BUY_THE_DIP_ACTIVE"
    assert p2["speed"]["state"] == "BUY_THE_DIP_ACTIVE"
    v1_raw_pre_clamp = (
        p1["tactical_vol"]["score"] + p1["structural_vol"]["score"] + 20
    )
    if v1_raw_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 20.0) < 1e-6


def test_v2_keeps_cap_mechanism_via_speed_state():
    """v2 CCA: cap still clamps at 49 if raw > 49 and lift conditions don't clear.

    The cap reads speed.state (enum), NOT speed.score (int). v2 dropping
    speed.score from raw does NOT change cap behavior.
    """
    p2 = _run_for_version(2, cca=True, btd=False)
    assert p2["speed"]["state"] == "CONFIRMED_CANARY_ACTIVE"
    # If our synthetic data produces raw > 49, the cap should fire (modulo lift conditions).
    # We set spx_above_sma200_2d=True in our helper, which gives cap_cleared_early=True,
    # so warning_state should be "NONE" even though speed.state is CCA.
    # This is the documented behavior: cap doesn't actually clamp when lift conditions clear.
    assert p2["canary"]["warning_state"] in ("NONE", "CONFIRMED_CANARY_ACTIVE")


def test_v3_routes_through_v2_path():
    """The `>=2` semantic intentionally auto-promotes future v3 to the v2 formula.

    This test will deliberately need updating when v3 lands with a new formula —
    that's the point: it forces the v3 implementer to make the conditional
    explicit rather than silently inheriting v2's behavior.
    """
    p2 = _run_for_version(2, cca=False, btd=False)
    p3 = _run_for_version(3, cca=False, btd=False)
    # Same inputs, same speed state → same raw_score under the >=2 branch.
    assert p2["canary"]["raw_score"] == p3["canary"]["raw_score"]


def test_both_active_ambiguous_branch():
    """When both CCA and BTD active: speed.state='BOTH_ACTIVE_AMBIGUOUS', speed.score=8.

    v1: raw += 8. v2: raw unchanged. Cap mechanism still uses speed.state.
    """
    p1 = _run_for_version(1, cca=True, btd=True)
    p2 = _run_for_version(2, cca=True, btd=True)
    assert p1["speed"]["state"] == "BOTH_ACTIVE_AMBIGUOUS"
    assert p2["speed"]["state"] == "BOTH_ACTIVE_AMBIGUOUS"
    assert p1["speed"]["score"] == 8
    # v2 raw should equal v1 raw - 8 (modulo clamping).
    v1_raw_pre_clamp = (
        p1["tactical_vol"]["score"] + p1["structural_vol"]["score"] + 8
    )
    if v1_raw_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 8.0) < 1e-6
```

- [ ] **Step 2: Run the new tests — verify they FAIL**

```bash
uv run pytest tests/unit/test_canary_v2_formula.py::test_v2_path_drops_speed_term_when_neutral -v
```

Expected: FAIL with `AssertionError: ... abs(delta - 8.0) < 1e-6 …` (current code adds speed.score for both v1 and v2 because the conditional doesn't exist yet).

- [ ] **Step 3: Apply the conditional path edit to `canary_scoring.py`**

Open `src/uw_scan/cards/canary_scoring.py`. Find the block around lines 540-545 (inside `run_analysis()`):

```python
    speed = derive_speed(
        confirmed_canary_active=confirmed_canary_active,
        buy_the_dip_active=buy_the_dip_active,
    )
    raw = tactical + structural + speed.score
    raw = max(0.0, min(100.0, raw))
```

Replace with:

```python
    speed = derive_speed(
        confirmed_canary_active=confirmed_canary_active,
        buy_the_dip_active=buy_the_dip_active,
    )
    if calibration.composite_version >= 2:
        # v2-A: speed is context only; apply_cap() below still uses speed.state.
        # See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md
        raw = tactical + structural
    else:
        raw = tactical + structural + speed.score
    raw = max(0.0, min(100.0, raw))
```

Nothing else changes. The `apply_cap(...)` call on the next line continues to read `speed.state`.

- [ ] **Step 4: Run all formula tests — verify they pass**

```bash
uv run pytest tests/unit/test_canary_v2_formula.py -v
```

Expected: All 8 tests pass (2 calibration tests from Task 1 + 6 formula tests from Task 2).

- [ ] **Step 5: Run the broader canary unit-test suite to confirm no regression**

```bash
uv run pytest tests/unit/test_canary_*.py -v
```

Expected: all green; the v1 codepath remains unaffected because v1 calibration has `composite_version=1`, taking the `else:` branch.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/test_canary_v2_formula.py
git commit -m "feat(canary): v2-A conditional path in run_analysis()

Adds a 4-line conditional in run_analysis() keyed on
calibration.composite_version. v1 path (>=2 false) is preserved by the
else clause — v1 scoring is bit-identical. v2 path drops the additive
speed.score term while leaving apply_cap() (which reads speed.state)
unchanged.

6 new formula tests:
- v1 NEUTRAL: raw == tactical + structural + 8 (speed.score)
- v2 NEUTRAL: raw == tactical + structural (no +8)
- v2 BTD: drops +20
- v2 CCA: cap mechanism still fires via speed.state
- v3 (composite_version=3): routes through v2 branch (>=2 semantic)
- BOTH_ACTIVE_AMBIGUOUS: v1/v2 delta = 8 (speed.score), cap unchanged

The >=2 semantic auto-promotes future v3 to the v2 formula — that test
will deliberately need updating when v3 lands with an explicit formula.

Spec §5.3."
```

---

### Task 3: Golden v1 payload-hash test (AC-6 — the *real* "v1 unchanged" proof)

**Files:**
- Create: `tests/unit/test_canary_v1_payload_hash_golden.py`

**Rationale:** The existing `test_canary_oos_gate.py` uses synthetic seeded rows (verified in `/review-cycle` Pass 2) — it does NOT exercise the v1 scoring path. AC-F6's claim that "v1 is unchanged" requires a golden test that runs `run_analysis` with v1 calibration on a fixed input and checks byte-identical output. This test IS that proof.

- [ ] **Step 1: Capture the v1 golden payload**

Run a small script ad-hoc to capture the v1 payload bytes (run before doing this commit):

```bash
uv run python <<'PY'
import json, hashlib
from datetime import date as _date
import numpy as np
from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.cards import canary_scoring


def fixed_aligned(n=400, seed=42):
    rng = np.random.default_rng(seed)
    return {
        "VIX": np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX": np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX": np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }


def fixed_dates(n=400):
    base = _date(2020, 6, 1)
    return [_date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)]


cal = load_calibration()  # v1 by default
aligned = fixed_aligned()
dates = fixed_dates()
payload = canary_scoring.run_analysis(
    today=_date.fromisoformat(dates[-1]),
    aligned=aligned,
    common_dates=dates,
    sma_50_today=float(aligned["SPX"][-50:].mean()),
    sma_200_today=float(aligned["SPX"][-200:].mean()),
    spx_above_sma200_2d=False,
    vix_term_normalized=False,
    higher_closing_low=False,
    confirmed_canary_active=False,
    buy_the_dip_active=False,
    calibration=cal,
)
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
print("V1_GOLDEN_HASH =", hashlib.sha256(canonical.encode()).hexdigest())
print("V1_GOLDEN_RAW_SCORE =", payload["canary"]["raw_score"])
print("V1_GOLDEN_SCORE =", payload["canary"]["score"])
print("V1_GOLDEN_BAND =", payload["canary"]["band"])
PY
```

Note the printed hash + sample fields. (Capture: ~64-char SHA-256.)

- [ ] **Step 2: Write the failing test (will pass once v1-fixture-constants are filled in)**

Path: `tests/unit/test_canary_v1_payload_hash_golden.py`

```python
"""Golden v1 payload-hash regression test (AC-6 / AC-F6).

The pre-existing tests/integration/regime/test_canary_oos_gate.py uses
synthetic seeded rows and does NOT exercise the v1 scoring path. This
test IS the v1-unchanged proof: it runs run_analysis with the v1
calibration on a fixed input fixture and asserts byte-identical
canonical JSON output to a captured pre-v2A golden.

If you intentionally change v1 behavior (extremely unlikely — v1 is
shipped), update the golden hash below with a fresh capture.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md
spec §7 AC-6 and §8 AC-F6.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date as _date

import numpy as np

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import load_calibration

# Captured 2026-05-27 against canary_scoring.py at commit <fill-in-after-task-2>.
# Run the ad-hoc script in plan §Task-3 Step-1 to recompute if needed.
V1_GOLDEN_HASH = "REPLACE_WITH_HASH_FROM_STEP_1"


def _fixed_inputs():
    rng = np.random.default_rng(42)
    n = 400
    aligned = {
        "VIX": np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX": np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX": np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }
    base = _date(2020, 6, 1)
    dates = [
        _date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)
    ]
    return aligned, dates


def test_v1_payload_hash_unchanged():
    """v1 scoring on fixed inputs MUST produce a byte-identical canonical-JSON
    payload to the captured 2026-05-27 golden. This is AC-6 / AC-F6's actual
    proof — the OOS gate test does NOT exercise the v1 scoring path."""
    cal = load_calibration()
    assert cal.composite_version == 1, "default load_calibration must be v1 in PR 1"
    aligned, dates = _fixed_inputs()
    payload = canary_scoring.run_analysis(
        today=_date.fromisoformat(dates[-1]),
        aligned=aligned,
        common_dates=dates,
        sma_50_today=float(aligned["SPX"][-50:].mean()),
        sma_200_today=float(aligned["SPX"][-200:].mean()),
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=False,
        buy_the_dip_active=False,
        calibration=cal,
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    actual = hashlib.sha256(canonical.encode()).hexdigest()
    assert actual == V1_GOLDEN_HASH, (
        f"v1 payload hash drifted!\n"
        f"  expected: {V1_GOLDEN_HASH}\n"
        f"  actual:   {actual}\n"
        f"v1 production scoring must be bit-identical to the captured golden. "
        f"If this is an intentional v1 change, re-run plan §Task-3 Step-1 to "
        f"recompute the golden."
    )


def test_v1_payload_band_unchanged():
    """Sanity backstop: the band classification on the fixed input is stable."""
    cal = load_calibration()
    aligned, dates = _fixed_inputs()
    payload = canary_scoring.run_analysis(
        today=_date.fromisoformat(dates[-1]),
        aligned=aligned,
        common_dates=dates,
        sma_50_today=float(aligned["SPX"][-50:].mean()),
        sma_200_today=float(aligned["SPX"][-200:].mean()),
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=False,
        buy_the_dip_active=False,
        calibration=cal,
    )
    assert payload["canary"]["band"] in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    assert 0.0 <= payload["canary"]["raw_score"] <= 100.0


def test_v1_calibration_loader_targets_v1_file_by_default():
    """Belt-and-braces: confirm the module COMPOSITE_VERSION stays at 1 in PR 1."""
    from uw_scan.cards.canary_calibration import COMPOSITE_VERSION

    assert COMPOSITE_VERSION == 1, (
        "PR 1 must NOT change COMPOSITE_VERSION. The flip is PR 2's job. See spec §10."
    )
```

- [ ] **Step 3: Fill in `V1_GOLDEN_HASH`**

Replace the `V1_GOLDEN_HASH = "REPLACE_WITH_HASH_FROM_STEP_1"` line with the actual hash captured in Step 1.

- [ ] **Step 4: Run the tests — verify they pass**

```bash
uv run pytest tests/unit/test_canary_v1_payload_hash_golden.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_canary_v1_payload_hash_golden.py
git commit -m "test(canary): v1 payload-hash golden test (AC-6 / AC-F6)

Captures the v1 run_analysis output as a SHA-256 hash on a fixed
synthetic input. This is the real proof that v1 production scoring is
unchanged post v2-A conditional — the pre-existing OOS gate test
(test_canary_oos_gate.py) uses synthetic seeded rows and does NOT
exercise the v1 scoring path.

Tests:
- test_v1_payload_hash_unchanged — byte-identical canonical JSON
- test_v1_payload_band_unchanged — sanity backstop on band assignment
- test_v1_calibration_loader_targets_v1_file_by_default —
  COMPOSITE_VERSION must stay at 1 in PR 1

If the v1 path is ever modified, this test fails clearly with an
actionable diff. Spec §7 AC-6, §8 AC-F6, §6 Layer 3 (COMPOSITE_VERSION
constant invisibility)."
```

---

### Task 4: New repo method `delete_canary_research_runs_by_batch_id_and_phase`

**Files:**
- Modify: `src/uw_scan/storage/regime_backtest_repository.py` (append after `delete_runs_by_batch_id`, ~line 172)
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py` (add tests for the new method, OR create a new test file — see Step 2)

**Rationale:** PR #88's `delete_runs_by_batch_id` is hard-pinned to `params->>'phase'='form_sweep_full'` (verified in `/review-cycle` Pass 4). v2 walk-forward uses `phase='walk_forward'`, so failed v2 batches would NOT be cleaned up by the existing method. We need a phase-parameterized variant.

- [ ] **Step 1: Write the failing test**

Path: `tests/integration/regime/test_canary_v2_walk_forward.py`

```python
"""Integration tests for canary v2-A walk-forward + robustness + dispatcher.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

import uuid
from datetime import date

import psycopg
import pytest

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

pytestmark = pytest.mark.integration


def _insert_research_run(
    repo: RegimeBacktestRepository,
    *,
    phase: str,
    window_id: str | None,
    batch_id: str,
    composite_version: str = "2",
) -> int:
    """Helper: insert one research-scoped canary run with the given phase."""
    params = {"phase": phase, "batch_id": batch_id, "score_form": "linear"}
    if window_id is not None:
        params["window_id"] = window_id
    return repo.insert_run(
        indicator="canary",
        composite_version=composite_version,
        start_date=date(2020, 1, 2),
        end_date=date(2020, 12, 30),
        window_days=350,
        n_days=250,
        params=params,
        summary={"is_winning_form": False, "phase": phase},
        run_scope="research",
    )


def test_delete_canary_research_runs_by_batch_id_and_phase_walk_forward(
    seeded_db_empty_cards,
):
    """Inserts 6 walk-forward + 1 robustness + 4 form-sweep research rows.
    Deletes walk-forward batch by (batch_id, phase='walk_forward').
    Assert: 6 walk-forward rows gone; robustness + form-sweep rows preserved."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)

    wf_batch = str(uuid.uuid4())
    fs_batch = str(uuid.uuid4())

    wf_ids = [
        _insert_research_run(repo, phase="walk_forward", window_id=f"WF-{i}", batch_id=wf_batch)
        for i in range(1, 7)
    ]
    robustness_id = _insert_research_run(
        repo, phase="robustness", window_id=None, batch_id=wf_batch
    )
    fs_ids = [
        _insert_research_run(
            repo, phase="form_sweep_full", window_id=None, batch_id=fs_batch,
            composite_version="1",
        )
        for _ in range(4)
    ]
    for rid in wf_ids + [robustness_id] + fs_ids:
        repo.mark_run_completed(rid)

    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        wf_batch, "walk_forward"
    )

    assert deleted == 6
    # Robustness row from same batch should remain
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {schema}.regime_backtest_runs WHERE id = %s",
            (robustness_id,),
        )
        assert cur.fetchone() is not None
    # Form-sweep rows from different batch should remain
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (fs_batch,),
        )
        assert cur.fetchone()[0] == 4


def test_delete_canary_research_runs_by_batch_id_and_phase_no_op_when_no_match(
    seeded_db_empty_cards,
):
    """If no rows match (wrong batch_id, wrong phase, wrong scope, or wrong
    indicator), delete returns 0 and writes no rows."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)

    # No matching rows at all
    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        str(uuid.uuid4()), "walk_forward"
    )
    assert deleted == 0


def test_delete_canary_research_runs_by_batch_id_and_phase_scope_correct(
    seeded_db_empty_cards,
):
    """The method must NOT delete production rows even if phase + batch_id match.

    This is a defense-in-depth check: someone with a typo could pass a
    production batch_id; the method's run_scope='research' filter must save them."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)

    same_batch = str(uuid.uuid4())
    research_id = _insert_research_run(
        repo, phase="walk_forward", window_id="WF-1", batch_id=same_batch
    )
    repo.mark_run_completed(research_id)

    # Try to insert a "production" row with the same batch_id (should require
    # explicit override; for the test we bypass the helper)
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {schema}.regime_backtest_runs "
            f"(indicator, composite_version, start_date, end_date, window_days, "
            f" n_days, params, summary, run_scope, completed_at) "
            f"VALUES ('canary', '1', '2020-01-02', '2020-12-30', 350, 250, "
            f"        %s::jsonb, '{{}}'::jsonb, 'production', now()) RETURNING id",
            (
                f'{{"phase": "walk_forward", "batch_id": "{same_batch}", '
                f'"window_id": "WF-1", "score_form": "linear"}}',
            ),
        )
        prod_id = cur.fetchone()[0]
    conn.commit()

    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        same_batch, "walk_forward"
    )

    assert deleted == 1  # only the research row, not the production row
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {schema}.regime_backtest_runs WHERE id = %s",
            (prod_id,),
        )
        assert cur.fetchone() is not None
```

- [ ] **Step 2: Run the failing test**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_delete_canary_research_runs_by_batch_id_and_phase_walk_forward -v
```

Expected: FAIL with `AttributeError: 'RegimeBacktestRepository' object has no attribute 'delete_canary_research_runs_by_batch_id_and_phase'`.

- [ ] **Step 3: Add the repo method**

Open `src/uw_scan/storage/regime_backtest_repository.py`. Find the existing `delete_runs_by_batch_id` method (around line 148). Append the new method directly after it (before `find_latest_run` at line 173):

```python
    def delete_canary_research_runs_by_batch_id_and_phase(
        self, batch_id: str, phase: str
    ) -> int:
        """Delete canary research runs scoped to a specific (batch_id, phase).

        Unlike `delete_runs_by_batch_id` (which hard-pins to
        `params.phase='form_sweep_full'` for cleanup-on-failure of PR #88's
        form-sweep), this method accepts an arbitrary phase string and is
        used by v2-A's cleanup-on-failure paths (`phase='walk_forward'`,
        `phase='robustness'`).

        Scope: `indicator='canary' AND run_scope='research' AND
        params->>'phase' = %s AND params->>'batch_id' = %s`. Production rows
        are NEVER deleted, even on a UUID4 collision.

        Daily rows are removed by ON DELETE CASCADE (migration 057).
        Returns the number of run rows deleted (0 if no match).

        Spec §5.8.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.regime_backtest_runs "
                "WHERE indicator = 'canary' "
                "  AND run_scope = 'research' "
                "  AND params->>'phase' = %s "
                "  AND params->>'batch_id' = %s",
                (phase, batch_id),
            )
            deleted = cur.rowcount
        self._conn.commit()
        return deleted
```

- [ ] **Step 4: Run all 3 new tests — verify they pass**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k delete_canary_research -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the broader form-sweep test suite to confirm no regression**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_form_sweep_full.py -v
```

Expected: all 14 existing form-sweep tests still pass (the existing `delete_runs_by_batch_id` is unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/regime_backtest_repository.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(regime): delete_canary_research_runs_by_batch_id_and_phase

PR #88's delete_runs_by_batch_id is hard-pinned to
params.phase='form_sweep_full' and cannot be reused for v2-A's
walk-forward / robustness cleanup paths. New method accepts an
arbitrary phase string and stays scoped to indicator='canary' AND
run_scope='research' to prevent production-plane pollution.

3 integration tests:
- Walk-forward batch deletion (6 rows; robustness + form-sweep rows preserved)
- No-op when no match
- Scope-correctness: production rows with same batch_id survive

Spec §5.2, §5.8, §4 invariant 7."
```

---

### Task 5: `canary_backfill.py --composite-version 2` + idempotency + AC-F3 evidence

**Files:**
- Modify: `scripts/canary_backfill.py` (parse new flags, load v2 calibration, use `cal.composite_version` for persistence)
- Create: `tests/integration/regime/test_canary_v2_backfill.py`

**Rationale:** The backfill script is the v2 evidence factory. It must:
- Parse `--composite-version` (default 1, accepts 2)
- Parse `--start-date YYYY-MM-DD` / `--end-date YYYY-MM-DD` (replacing the date-fragile `--days N` for v2)
- Load v2 calibration JSON explicitly when `--composite-version 2` is passed
- Persist `composite_version=cal.composite_version` (the loaded field, NOT the module constant)
- Be idempotent on re-run via application-layer pre-insert check

- [ ] **Step 1: Read the current canary_backfill.py to find the call sites that need plumbing**

```bash
grep -n "COMPOSITE_VERSION\|load_calibration\|args\.\|argparse\|insert_snapshot\|run_analysis" scripts/canary_backfill.py | head -40
```

Note the line numbers — we'll modify:
- argparse setup (add flags)
- the call to `load_calibration()` (parameterize path)
- the `insert_snapshot` call (parameterize composite_version)

- [ ] **Step 2: Write the failing integration tests**

Append to `tests/integration/regime/test_canary_v2_backfill.py` (create if not exists):

```python
"""Integration tests for canary v2-A backfill.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKFILL_SCRIPT = REPO_ROOT / "scripts" / "canary_backfill.py"


def _run_backfill(
    *,
    composite_version: int,
    start_date: str,
    end_date: str,
    test_db_url: str,
) -> subprocess.CompletedProcess:
    """Invoke the backfill script as a subprocess against a test DB."""
    env = {
        "DATABASE_URL": test_db_url,
        "UW_SCAN_API_KEY": "local-test",
        "PATH": "/usr/bin:/bin",  # minimal PATH
    }
    return subprocess.run(
        [
            sys.executable,
            str(BACKFILL_SCRIPT),
            "--composite-version", str(composite_version),
            "--start-date", start_date,
            "--end-date", end_date,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_v2_backfill_writes_composite_version_2_rows(seeded_db_with_vol_index):
    """--composite-version 2 writes rows tagged composite_version=2.
    Production fetch_latest(composite_version=1) returns v1 rows unchanged."""
    conn = seeded_db_with_vol_index.conn
    schema = seeded_db_with_vol_index._schema

    # First, seed v1 rows via existing v1 path (composite_version=1)
    result_v1 = _run_backfill(
        composite_version=1,
        start_date="2020-01-02",
        end_date="2020-12-30",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result_v1.returncode == 0, f"v1 backfill failed: {result_v1.stderr}"

    # Now run v2 backfill on the same date range
    result_v2 = _run_backfill(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-12-30",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result_v2.returncode == 0, f"v2 backfill failed: {result_v2.stderr}"

    # Verify v2 rows exist
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        v2_count = cur.fetchone()[0]
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=1"
        )
        v1_count = cur.fetchone()[0]
    assert v2_count > 0, "v2 backfill wrote no rows"
    assert v2_count == v1_count, "v2 row count should equal v1 row count for overlap"


def test_v2_backfill_uses_cal_composite_version_not_module_constant(
    seeded_db_with_vol_index,
):
    """v2 backfill MUST tag rows with cal.composite_version=2 (loaded field),
    NOT the module-level COMPOSITE_VERSION=1 constant. Otherwise v2 payloads
    get stored as version 1 — silent DB corruption. Spec §4 invariant 10."""
    from uw_scan.cards.canary_calibration import COMPOSITE_VERSION
    assert COMPOSITE_VERSION == 1, "PR 1 must not flip the module constant"

    conn = seeded_db_with_vol_index.conn
    schema = seeded_db_with_vol_index._schema

    result = _run_backfill(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-03-31",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT composite_version FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 LIMIT 5"
        )
        rows = cur.fetchall()
    assert len(rows) == 5
    for row in rows:
        assert row[0] == 2, "v2 rows must be tagged composite_version=2"


def test_v2_backfill_score_form_is_linear(seeded_db_with_vol_index):
    """v2 calibration mandates score_form='linear' (form-sweep verdict). Spec §5.4."""
    conn = seeded_db_with_vol_index.conn
    schema = seeded_db_with_vol_index._schema

    result = _run_backfill(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT score_form FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2"
        )
        forms = {row[0] for row in cur.fetchall()}
    assert forms == {"linear"}, f"v2 score_form must be linear, got {forms}"


def test_v2_backfill_is_idempotent(seeded_db_with_vol_index):
    """Re-running the v2 backfill on the same date range is a no-op.
    Idempotency MUST be application-layer (pre-insert SELECT 1 check),
    NOT ON CONFLICT DO NOTHING (which silently keeps stale rows).
    Spec §5.8."""
    conn = seeded_db_with_vol_index.conn
    schema = seeded_db_with_vol_index._schema

    result1 = _run_backfill(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result1.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        count_after_first = cur.fetchone()[0]

    result2 = _run_backfill(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result2.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        count_after_second = cur.fetchone()[0]

    assert count_after_first == count_after_second, "second backfill should be a no-op"


def test_v2_backfill_does_not_affect_v1_rows(seeded_db_with_vol_index):
    """Production fetch_latest(composite_version=1) returns v1 rows unchanged
    after v2 backfill. Spec §6 Layer 1."""
    from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository

    conn = seeded_db_with_vol_index.conn
    schema = seeded_db_with_vol_index._schema

    # v1 backfill first
    result_v1 = _run_backfill(
        composite_version=1,
        start_date="2020-01-02",
        end_date="2020-02-28",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result_v1.returncode == 0

    repo = CanarySnapshotRepository(conn, schema=schema)
    v1_latest_before = repo.fetch_latest(composite_version=1)
    assert v1_latest_before is not None

    # Now v2 backfill
    result_v2 = _run_backfill(
        composite_version=2,
        start_date="2020-01-02",
        end_date="2020-02-28",
        test_db_url=seeded_db_with_vol_index.url,
    )
    assert result_v2.returncode == 0

    v1_latest_after = repo.fetch_latest(composite_version=1)
    assert v1_latest_after.data_date == v1_latest_before.data_date
    assert v1_latest_after.score == v1_latest_before.score
    assert v1_latest_after.band == v1_latest_before.band


def test_v2_backfill_ac_f3_evidence_cca_events(seeded_db_full_history):
    """AC-F3: The 4 historical CCA event dates produce
    payload.speed.confirmed_canary_active=True in v2 backfill output.

    Requires a fixture with realistic vol_index_daily data covering the 4
    event dates. See spec §8 AC-F3."""
    conn = seeded_db_full_history.conn
    schema = seeded_db_full_history._schema

    result = _run_backfill(
        composite_version=2,
        start_date="2011-02-08",
        end_date="2020-04-30",
        test_db_url=seeded_db_full_history.url,
    )
    assert result.returncode == 0

    event_dates = ["2011-08-08", "2015-08-24", "2018-02-05", "2020-03-09"]
    with conn.cursor() as cur:
        for d in event_dates:
            cur.execute(
                f"SELECT payload->'speed'->>'confirmed_canary_active' "
                f"FROM {schema}.canary_snapshots "
                f"WHERE composite_version=2 AND data_date=%s",
                (d,),
            )
            row = cur.fetchone()
            assert row is not None, f"missing v2 snapshot for CCA event {d}"
            assert row[0] in ("true", "True", True), (
                f"AC-F3 evidence FAIL: {d} payload.speed.confirmed_canary_active "
                f"is {row[0]!r}, expected True. The cap mechanism is broken."
            )
```

Note the `seeded_db_full_history` fixture — this needs to exist OR the AC-F3 test gets skipped/modified to construct a synthetic full-history fixture. **Implementer choice:** either add this fixture, or convert AC-F3 to a smoke-test deferred to the live run (mark `pytest.skip` with a clear message and verify via the AC-F3 smoke command in Task 12).

- [ ] **Step 3: Run the failing tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_backfill.py -v
```

Expected: all FAIL (script doesn't accept `--composite-version 2` flag yet).

- [ ] **Step 4: Modify `canary_backfill.py` argparse + load + persistence**

Edit `scripts/canary_backfill.py`:

**4a. Add new flags to argparse:**

Find the `parser = argparse.ArgumentParser(...)` block (around line 80). Add:

```python
    parser.add_argument(
        "--composite-version",
        type=int,
        choices=(1, 2),
        default=COMPOSITE_VERSION,
        help=(
            "Composite version to use (default: 1, the module constant). "
            "Pass 2 to load canary-calibration-v2.json and write "
            "composite_version=2 rows (research-only, invisible to production)."
        ),
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="ISO date (YYYY-MM-DD) for the first day to backfill. "
             "If omitted, uses --days N from end of vol_index_daily.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="ISO date (YYYY-MM-DD) for the last day to backfill. "
             "If omitted, uses MAX(data_date) from vol_index_daily.",
    )
```

**4b. Load the right calibration based on the flag:**

Find the existing `cal = load_calibration()` call (around line 103). Replace with:

```python
    from datetime import date as _date

    if args.composite_version == 2:
        cal_path = (
            REPO_ROOT
            / "docs"
            / "research"
            / "regime"
            / "canary-calibration-v2.json"
        )
        cal = load_calibration(path=cal_path)
        assert cal.composite_version == 2, "v2 calibration JSON misconfigured"
    else:
        cal = load_calibration()  # default DEFAULT_PATH = v1
        assert cal.composite_version == 1, "v1 calibration JSON misconfigured"
```

(Add `from pathlib import Path` and a `REPO_ROOT = Path(__file__).resolve().parents[1]` near the top if not already imported.)

**4c. Replace persistence usage of `COMPOSITE_VERSION` with `cal.composite_version`:**

Find the `insert_snapshot(...)` call (around line 176). Change:

```python
    snap_repo.insert_snapshot(
        ...
        composite_version=COMPOSITE_VERSION,
        ...
    )
```

to:

```python
    snap_repo.insert_snapshot(
        ...
        composite_version=cal.composite_version,
        ...
    )
```

**4d. Add the date-range logic for --start-date / --end-date:**

In the main function, BEFORE the `for d in dates_to_backfill:` loop (around line 130), add:

```python
    # Date-range derivation: --start-date / --end-date overrides --days behaviour.
    if args.start_date is not None or args.end_date is not None:
        # If only one of start/end provided, derive the other from vol_index_daily.
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MIN(data_date), MAX(data_date) "
                f"FROM {schema}.vol_index_daily "
                f"WHERE symbol = 'SPX'"
            )
            vol_min, vol_max = cur.fetchone()
        start_d = (
            _date.fromisoformat(args.start_date) if args.start_date else vol_min
        )
        end_d = _date.fromisoformat(args.end_date) if args.end_date else vol_max
        dates_to_backfill = [d for d in all_dates if start_d <= d <= end_d]
```

**4e. Add idempotency: application-layer pre-insert check:**

Wrap the `insert_snapshot` call:

```python
    # Idempotency: skip if a row already exists for (data_date, composite_version).
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM {schema}.canary_snapshots "
            f"WHERE data_date = %s AND composite_version = %s LIMIT 1",
            (d, cal.composite_version),
        )
        if cur.fetchone() is not None:
            log.info("skip data_date=%s composite_version=%s (already exists)",
                     d, cal.composite_version)
            continue
    snap_repo.insert_snapshot(...)  # existing call
```

- [ ] **Step 5: Run all v2 backfill tests — verify they pass**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_backfill.py -v
```

Expected: 6 tests pass (5 standard + AC-F3 if fixture is available; otherwise 5 pass + 1 skip).

- [ ] **Step 6: Confirm v1 backfill is unchanged**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_backfill.py -v
```

(Or whatever the existing v1 backfill test file is — should already exist from PR #83.) Expected: all existing v1 tests still pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/canary_backfill.py tests/integration/regime/test_canary_v2_backfill.py
git commit -m "feat(canary): canary_backfill.py --composite-version + idempotency

Add --composite-version {1,2}, --start-date, --end-date flags.
When --composite-version 2, loads canary-calibration-v2.json explicitly
and writes rows tagged composite_version=cal.composite_version (the
loaded field — NOT the module-level COMPOSITE_VERSION constant, which
would silently corrupt the DB by tagging v2 payloads as version 1).

Idempotency: application-layer pre-insert SELECT 1 check on
(data_date, composite_version). NOT ON CONFLICT DO NOTHING — which
would silently keep stale rows from failed earlier runs with bugs
(caught by Codex during /review-cycle).

Tests (6 integration):
- v2 writes composite_version=2 rows
- v2 uses cal.composite_version (not module constant)
- v2 score_form is linear (form-sweep verdict)
- v2 idempotent re-run is a no-op
- v2 does not affect v1 rows
- AC-F3 evidence (4 CCA event dates fire correctly) — requires
  full-history fixture; falls through to live smoke in Task 12 if
  fixture unavailable.

Spec §5.5, §5.8."
```

---

### Task 6: `backtest_canary.py --walk-forward --composite-version 2`

**Files:**
- Modify: `scripts/backtest_canary.py` (add `--composite-version` flag to walk-forward path)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py` (extend with walk-forward tests)

**Rationale:** Walk-forward recomputes scores from `vol_index_daily` (NOT from `canary_snapshots`) using `run_analysis` and the loaded calibration. Plumbing the right calibration through is the bulk of the work.

- [ ] **Step 1: Read the existing walk-forward code to find the plumbing points**

```bash
grep -n "load_calibration\|cmd_walk_forward\|--walk-forward\|composite_version" scripts/backtest_canary.py | head -30
```

Note the function (likely `cmd_walk_forward` or similar) and the argparse setup.

- [ ] **Step 2: Write failing tests for v2 walk-forward**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKTEST_SCRIPT = REPO_ROOT / "scripts" / "backtest_canary.py"


def _run_walk_forward(
    *,
    composite_version: int,
    test_db_url: str,
) -> subprocess.CompletedProcess:
    env = {
        "DATABASE_URL": test_db_url,
        "UW_SCAN_API_KEY": "local-test",
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        [
            sys.executable,
            str(BACKTEST_SCRIPT),
            "--walk-forward",
            "--composite-version", str(composite_version),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_v2_walk_forward_writes_6_research_rows(seeded_db_with_v2_backfill):
    """--walk-forward --composite-version 2 writes 6 walk-forward runs:
    run_scope='research', composite_version='2', window_id ∈ {WF-1..WF-6},
    shared params->>'batch_id'."""
    conn = seeded_db_with_v2_backfill.conn
    schema = seeded_db_with_v2_backfill._schema

    result = _run_walk_forward(
        composite_version=2,
        test_db_url=seeded_db_with_v2_backfill.url,
    )
    assert result.returncode == 0, f"walk-forward failed: {result.stderr}"

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id', params->>'window_id', composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND params->>'phase'='walk_forward' "
            f"  AND composite_version='2' "
            f"ORDER BY params->>'window_id'"
        )
        rows = cur.fetchall()

    assert len(rows) == 6, f"expected 6 walk-forward rows, got {len(rows)}"
    batch_ids = {r[0] for r in rows}
    assert len(batch_ids) == 1, "all 6 rows must share batch_id"
    window_ids = {r[1] for r in rows}
    assert window_ids == {f"WF-{i}" for i in range(1, 7)}, (
        f"window_ids must be exactly WF-1..WF-6, got {window_ids}"
    )
    for r in rows:
        assert r[2] == "2"
        assert r[3] == "research"


def test_v2_walk_forward_preserves_v1_production_rows(seeded_db_with_v1_and_v2_backfill):
    """v1 walk-forward production rows (PR #83 ids 19-24) remain untouched
    after v2 walk-forward runs. Spec §6 Layer 2."""
    conn = seeded_db_with_v1_and_v2_backfill.conn
    schema = seeded_db_with_v1_and_v2_backfill._schema

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='production' "
            f"  AND params->>'phase'='walk_forward' AND composite_version='1'"
        )
        v1_count_before = cur.fetchone()[0]

    result = _run_walk_forward(
        composite_version=2,
        test_db_url=seeded_db_with_v1_and_v2_backfill.url,
    )
    assert result.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='production' "
            f"  AND params->>'phase'='walk_forward' AND composite_version='1'"
        )
        v1_count_after = cur.fetchone()[0]
    assert v1_count_after == v1_count_before


def test_v2_walk_forward_summary_has_composite_aucs(seeded_db_with_v2_backfill):
    """Each v2 walk-forward run's summary.aucs.composite contains the three
    horizons (up5d_2pct / up20d_5pct / up60d_10pct). Spec §8 AC-F4 reads
    these directly."""
    conn = seeded_db_with_v2_backfill.conn
    schema = seeded_db_with_v2_backfill._schema

    result = _run_walk_forward(
        composite_version=2,
        test_db_url=seeded_db_with_v2_backfill.url,
    )
    assert result.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT summary->'aucs'->'composite' "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward' LIMIT 1"
        )
        composite_aucs = cur.fetchone()[0]

    assert composite_aucs is not None
    for key in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert key in composite_aucs, f"missing AUC key {key}"
        v = composite_aucs[key]
        assert v is None or (0.0 <= v <= 1.0), f"AUC out of range: {key}={v}"
```

- [ ] **Step 3: Run the failing tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k walk_forward -v
```

Expected: FAIL (`--composite-version` flag doesn't exist on walk-forward path yet).

- [ ] **Step 4: Modify `backtest_canary.py` walk-forward path**

Edit `scripts/backtest_canary.py`:

**4a. Add `--composite-version` argument to argparse:**

Find the argparse setup. Add:

```python
    parser.add_argument(
        "--composite-version",
        type=int,
        choices=(1, 2),
        default=1,
        help=(
            "Composite version: 1 (v1, production, default) or 2 (v2-A, "
            "research-only, loads canary-calibration-v2.json and writes "
            "run_scope='research' rows). Spec §5.5."
        ),
    )
```

**4b. Inside the walk-forward dispatcher (`cmd_walk_forward` or equivalent), use the v2 calibration when requested and pass `run_scope='research'` for v2:**

Find the `load_calibration()` call inside the walk-forward function. Replace:

```python
    cal = load_calibration()
```

with:

```python
    if args.composite_version == 2:
        cal_path = (
            REPO_ROOT
            / "docs"
            / "research"
            / "regime"
            / "canary-calibration-v2.json"
        )
        cal = load_calibration(path=cal_path)
        run_scope = "research"
    else:
        cal = load_calibration()
        run_scope = "production"
```

(Add the REPO_ROOT import if not already present, and propagate `run_scope` through to every `bt_repo.insert_run(...)` call site by changing the kwarg.)

**4c. Pass `cal.composite_version` (loaded field) — NOT the module `COMPOSITE_VERSION` constant — to every persistence call:**

Find every `composite_version=str(COMPOSITE_VERSION)` or similar in the walk-forward path. Replace with `composite_version=str(cal.composite_version)`.

**4d. Ensure the `params` dict for each walk-forward run includes `window_id` and `batch_id`:**

The existing v1 code already does this (verified). For v2, the same code path is reused — no separate v2 code branch needed; the calibration's `composite_version` flows through `run_analysis` to drive the formula switch.

- [ ] **Step 5: Run the v2 walk-forward tests — verify they pass**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k walk_forward -v
```

Expected: 3 passed.

- [ ] **Step 6: Run the existing v1 walk-forward tests — confirm no regression**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_backtest.py -v
```

Expected: all v1 walk-forward tests still pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): --composite-version 2 walk-forward (research scope)

Plumbs args.composite_version through cmd_walk_forward: loads
canary-calibration-v2.json when 2, forces run_scope='research' for v2
runs, persists composite_version=str(cal.composite_version) (the loaded
field — NOT the module COMPOSITE_VERSION constant).

The v1 code path is reused as-is; only the calibration changes. The
formula switch happens inside run_analysis() via the v2-A conditional
from Task 2.

3 integration tests:
- 6 walk-forward rows with run_scope='research', composite_version='2',
  shared batch_id, window_id ∈ {WF-1..WF-6}
- v1 production walk-forward rows untouched
- summary.aucs.composite contains 5d/20d/60d AUCs (AC-F4 input)

Spec §5.5, §6 Layer 2."
```

---

### Task 7: `backtest_canary.py --robustness --composite-version 2`

**Files:**
- Modify: `scripts/backtest_canary.py` (add `--composite-version` to robustness path; share batch_id with walk-forward)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** G3 of the spec requires 7 v2 evidence rows: 6 walk-forward + 1 robustness. The robustness path needs the same `--composite-version` plumbing as walk-forward.

- [ ] **Step 1: Write failing test**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
def _run_robustness(
    *,
    composite_version: int,
    batch_id: str | None = None,
    test_db_url: str,
) -> subprocess.CompletedProcess:
    env = {
        "DATABASE_URL": test_db_url,
        "UW_SCAN_API_KEY": "local-test",
        "PATH": "/usr/bin:/bin",
    }
    cmd = [
        sys.executable,
        str(BACKTEST_SCRIPT),
        "--robustness",
        "--composite-version", str(composite_version),
    ]
    if batch_id is not None:
        cmd += ["--batch-id", batch_id]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)


def test_v2_robustness_writes_1_research_row(seeded_db_with_v2_backfill):
    """--robustness --composite-version 2 writes 1 research-scoped row
    with phase='robustness', composite_version='2'."""
    conn = seeded_db_with_v2_backfill.conn
    schema = seeded_db_with_v2_backfill._schema

    result = _run_robustness(
        composite_version=2,
        test_db_url=seeded_db_with_v2_backfill.url,
    )
    assert result.returncode == 0, f"robustness failed: {result.stderr}"

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='robustness'"
        )
        count = cur.fetchone()[0]

    assert count == 1, f"expected 1 robustness row, got {count}"


def test_v2_robustness_shares_batch_id_with_walk_forward_when_chained(
    seeded_db_with_v2_backfill,
):
    """If --walk-forward and --robustness run in sequence and the operator
    passes --batch-id, the robustness row carries the same batch_id.
    (If --batch-id is omitted, the row gets its own UUID4 — that's fine
    for ad-hoc invocations.)"""
    conn = seeded_db_with_v2_backfill.conn
    schema = seeded_db_with_v2_backfill._schema

    result_wf = _run_walk_forward(
        composite_version=2,
        test_db_url=seeded_db_with_v2_backfill.url,
    )
    assert result_wf.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT params->>'batch_id' "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward'"
        )
        wf_batch_id = cur.fetchone()[0]

    result_rb = _run_robustness(
        composite_version=2,
        batch_id=wf_batch_id,
        test_db_url=seeded_db_with_v2_backfill.url,
    )
    assert result_rb.returncode == 0

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id' FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='robustness'"
        )
        rb_batch_id = cur.fetchone()[0]

    assert rb_batch_id == wf_batch_id
```

- [ ] **Step 2: Run failing tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k robustness -v
```

Expected: FAIL.

- [ ] **Step 3: Modify robustness path in `backtest_canary.py`**

The robustness function (likely `cmd_robustness` — adapt to actual name) needs the same plumbing:

```python
    # Existing function signature: cmd_robustness(conn, schema)
    # Add args parameter and use it:
    if args.composite_version == 2:
        cal_path = REPO_ROOT / "docs/research/regime/canary-calibration-v2.json"
        cal = load_calibration(path=cal_path)
        run_scope = "research"
    else:
        cal = load_calibration()
        run_scope = "production"

    batch_id = args.batch_id or str(uuid.uuid4())

    # ... existing computation ...

    bt_repo.insert_run(
        indicator="canary",
        composite_version=str(cal.composite_version),
        ...,
        params={"phase": "robustness", "batch_id": batch_id, ...},
        run_scope=run_scope,
    )
```

Add `--batch-id` argparse arg (optional, str, default None):

```python
    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help=(
            "Optional batch_id to attach to this run. If omitted, a fresh "
            "UUID4 is generated. Useful for chaining --walk-forward + "
            "--robustness under a shared batch."
        ),
    )
```

- [ ] **Step 4: Run robustness tests — verify they pass**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k robustness -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): --composite-version 2 robustness (research scope)

Mirrors the walk-forward plumbing from Task 6: loads v2 calibration,
forces run_scope='research', persists composite_version=str(cal.composite_version).

New --batch-id flag (optional) allows chaining --walk-forward and
--robustness under the same UUID4 for downstream renderer load.

2 integration tests:
- 1 robustness row with run_scope='research', composite_version='2',
  phase='robustness'
- Shared batch_id when chained with walk-forward via --batch-id

Spec §5.5, §G3."
```

---

### Task 8: Walk-forward recompute vs backfill parity test (AC-4b)

**Files:**
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** Walk-forward recomputes scores from `vol_index_daily` (NOT from `canary_snapshots`). Spec §5.5 says these must match within floating-point tolerance for any given date. The parity test asserts this for ~30 dates per window.

- [ ] **Step 1: Write the failing parity test**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
def test_v2_walk_forward_recompute_matches_v2_backfill_snapshots(
    seeded_db_with_v2_backfill,
):
    """For ~30 sample dates across each WF window, the walk-forward's
    recomputed v2 score equals the v2 backfill snapshot score for the same
    date. Floating-point tolerance: 1e-6 on raw_score, exact on band.

    Confirms the two code paths (walk-forward recompute via vol_index_daily
    vs backfill via canary_snapshots) produce identical outputs at v2.

    Spec §5.5 (source of truth) + §7 AC-4b."""
    conn = seeded_db_with_v2_backfill.conn
    schema = seeded_db_with_v2_backfill._schema

    # 1. Run v2 walk-forward
    result = _run_walk_forward(
        composite_version=2,
        test_db_url=seeded_db_with_v2_backfill.url,
    )
    assert result.returncode == 0

    # 2. Pull walk-forward daily rows
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT d.trade_date, d.score, d.level "
            f"FROM {schema}.regime_backtest_daily d "
            f"JOIN {schema}.regime_backtest_runs r ON d.run_id = r.id "
            f"WHERE r.indicator='canary' AND r.composite_version='2' "
            f"  AND r.run_scope='research' AND r.params->>'phase'='walk_forward' "
            f"ORDER BY d.trade_date"
        )
        wf_rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # 3. Pull backfill snapshot rows for the same dates
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data_date, score, band FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 AND data_date = ANY(%s)",
            (list(wf_rows.keys()),),
        )
        bf_rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # 4. Sample ~30 dates and compare
    import random
    rng = random.Random(42)
    overlap = sorted(set(wf_rows) & set(bf_rows))
    sample = rng.sample(overlap, min(30, len(overlap)))

    assert len(sample) >= 10, f"need ≥10 overlap dates, got {len(sample)}"

    mismatches = []
    for d in sample:
        wf_score, wf_band = wf_rows[d]
        bf_score, bf_band = bf_rows[d]
        if abs(wf_score - bf_score) > 1e-6 or wf_band != bf_band:
            mismatches.append(
                f"  {d}: wf=({wf_score}, {wf_band}) bf=({bf_score}, {bf_band})"
            )

    assert not mismatches, (
        f"recompute vs backfill parity failed on {len(mismatches)} of "
        f"{len(sample)} sampled dates:\n" + "\n".join(mismatches[:10])
    )
```

- [ ] **Step 2: Run the parity test — expect PASS (no implementation needed)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v2_walk_forward_recompute_matches_v2_backfill_snapshots -v
```

Expected: PASS. (Both paths use `run_analysis()` with the same v2 calibration; outputs should match by construction.)

- [ ] **Step 3: If the test FAILS, investigate the divergence**

A failure here points to a real bug — most likely one of:
- Walk-forward uses a different code path than `run_analysis` (e.g., a separate `_compute_canary_series` with subtle differences)
- The vol_index_daily arrays passed to walk-forward differ from what canary_backfill uses
- Rounding differences in intermediate computations

Fix the underlying divergence — DO NOT loosen the tolerance.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "test(canary): v2 walk-forward recompute vs backfill parity (AC-4b)

For ~30 sampled dates per WF window, asserts that the walk-forward's
recomputed v2 score (from vol_index_daily) matches the v2 backfill
snapshot score (from canary_snapshots) within 1e-6 floating-point
tolerance, with byte-identical band.

This proves the two code paths produce identical outputs at v2 — a
divergence here would mean either: (a) walk-forward and backfill use
different code paths, (b) the same code path but with input drift, or
(c) precision loss in intermediate computation. AC-4b catches all three.

Spec §5.5 (source of truth) + §7 AC-4b."
```

---

### Task 9: `FlipGateEvidence` dataclass + `render_canary_v1_v2_compare` renderer + unit tests

**Files:**
- Create: `src/uw_scan/reports/regime_canary_v1_v2_compare.py`
- Create: `tests/unit/test_canary_v1_v2_compare_renderer.py`

**Rationale:** Pure-function renderer separated from DB access (Codex-ISSUE-1 caught this). The renderer takes a `FlipGateEvidence` dataclass; the dispatcher (Task 10) assembles it.

- [ ] **Step 1: Write the renderer module with FlipGateEvidence + render function**

Path: `src/uw_scan/reports/regime_canary_v1_v2_compare.py`

```python
"""Canary v1-vs-v2 comparison renderer + standalone CLI.

Pure function. No DB, no I/O. Takes a pre-assembled FlipGateEvidence
dataclass and renders a markdown side-by-side report including the
AC-F1..F6 evaluation block.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from io import StringIO
from typing import Mapping

import psycopg

from uw_scan.config import Settings

CANONICAL_WINDOWS = ("WF-1", "WF-2", "WF-3", "WF-4", "WF-5", "WF-6")
CCA_EVENT_DATES = ("2011-08-08", "2015-08-24", "2018-02-05", "2020-03-09")

# AC-F1..F5 thresholds, locked-in by the spec (§8). DO NOT change without
# a spec amendment per spec §15.
AC_F1_60D_BAR = 0.634
AC_F2_20D_BAR = 0.622
AC_F2_5D_BAR = 0.615
AC_F4_PER_WINDOW_TOLERANCE = -0.02
AC_F5_WATCH_PCT_BAR = 44.3


@dataclass(frozen=True)
class FlipGateEvidence:
    """Pre-assembled bundle that lets the renderer evaluate every AC-Fn locally.

    The dispatcher (--v1-v2-compare in scripts/backtest_canary.py) is
    responsible for assembling this from the DB; the renderer is pure.

    Field meanings:
      v1_runs / v2_runs: 6 walk-forward run dicts each, one per WF window.
        v1 has composite_version='1' / run_scope='production',
        v2 has composite_version='2' / run_scope='research'.
      v2_robustness_run: 1 robustness run dict, same scope/version as v2_runs.
      v1_full_history_aucs / v2_full_history_aucs: AUC computed by
        _aucs_for_rows over ALL canary_snapshots at the relevant
        composite_version. Keys: up5d_2pct, up20d_5pct, up60d_10pct.
      v1_band_distribution / v2_band_distribution: pct of full-history
        snapshots in each band. Keys: NONE, WATCH, BUY, STRONG_BUY.
      v2_cca_event_states: payload.speed.confirmed_canary_active per
        CCA event date. Keys are ISO date strings; values are bool.
      oos_gate_passed: result of running test_canary_oos_gate.py.
      v1_payload_hash_golden_passed: result of running
        test_canary_v1_payload_hash_golden.py.
    """

    v1_runs: list[dict]
    v2_runs: list[dict]
    v2_robustness_run: dict
    v1_full_history_aucs: dict[str, float]
    v2_full_history_aucs: dict[str, float]
    v1_band_distribution: dict[str, float]
    v2_band_distribution: dict[str, float]
    v2_cca_event_states: dict[str, bool]
    oos_gate_passed: bool
    v1_payload_hash_golden_passed: bool


def _validate_evidence(ev: FlipGateEvidence) -> None:
    """Raise ValueError if any structural invariant is violated."""
    if len(ev.v1_runs) != 6:
        raise ValueError(f"v1_runs must have 6 runs, got {len(ev.v1_runs)}")
    if len(ev.v2_runs) != 6:
        raise ValueError(f"v2_runs must have 6 runs, got {len(ev.v2_runs)}")
    for r in ev.v1_runs:
        if str(r.get("composite_version")) != "1":
            raise ValueError(f"v1_runs has composite_version={r.get('composite_version')!r}")
        if r.get("run_scope") != "production":
            raise ValueError(f"v1_runs has run_scope={r.get('run_scope')!r}")
    for r in ev.v2_runs:
        if str(r.get("composite_version")) != "2":
            raise ValueError(f"v2_runs has composite_version={r.get('composite_version')!r}")
        if r.get("run_scope") != "research":
            raise ValueError(f"v2_runs has run_scope={r.get('run_scope')!r}")
    v2_batch_ids = {r["params"].get("batch_id") for r in ev.v2_runs}
    if len(v2_batch_ids) != 1:
        raise ValueError(f"v2_runs must share batch_id, got {v2_batch_ids}")
    v1_window_ids = {r["params"].get("window_id") for r in ev.v1_runs}
    v2_window_ids = {r["params"].get("window_id") for r in ev.v2_runs}
    if v1_window_ids != set(CANONICAL_WINDOWS):
        raise ValueError(f"v1_runs window_ids != WF-1..WF-6, got {v1_window_ids}")
    if v2_window_ids != set(CANONICAL_WINDOWS):
        raise ValueError(f"v2_runs window_ids != WF-1..WF-6, got {v2_window_ids}")
    if str(ev.v2_robustness_run.get("composite_version")) != "2":
        raise ValueError("v2_robustness_run must be composite_version=2")
    if ev.v2_robustness_run.get("run_scope") != "research":
        raise ValueError("v2_robustness_run must be research-scoped")
    for d in CCA_EVENT_DATES:
        if d not in ev.v2_cca_event_states:
            raise ValueError(f"v2_cca_event_states missing CCA date {d}")


def _eval_ac_f1(ev: FlipGateEvidence) -> tuple[bool, str]:
    auc = ev.v2_full_history_aucs.get("up60d_10pct")
    v1_ref = ev.v1_full_history_aucs.get("up60d_10pct")
    if auc is None or v1_ref is None:
        return False, "AC-F1: v2 60d AUC unavailable"
    passed = auc >= AC_F1_60D_BAR
    delta = auc - v1_ref
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F1 [{verdict}]: v2 60d AUC = {auc:.4f} "
        f"(bar ≥ {AC_F1_60D_BAR}; v1 ref {v1_ref:.4f}, delta {delta:+.4f})"
    )


def _eval_ac_f2(ev: FlipGateEvidence) -> tuple[bool, str]:
    auc_20 = ev.v2_full_history_aucs.get("up20d_5pct")
    auc_5 = ev.v2_full_history_aucs.get("up5d_2pct")
    if auc_20 is None or auc_5 is None:
        return False, "AC-F2: v2 short-horizon AUCs unavailable"
    p20 = auc_20 >= AC_F2_20D_BAR
    p5 = auc_5 >= AC_F2_5D_BAR
    passed = p20 and p5
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F2 [{verdict}]: v2 20d AUC = {auc_20:.4f} "
        f"(bar ≥ {AC_F2_20D_BAR}, {'PASS' if p20 else 'FAIL'}), "
        f"v2 5d AUC = {auc_5:.4f} (bar ≥ {AC_F2_5D_BAR}, "
        f"{'PASS' if p5 else 'FAIL'})"
    )


def _eval_ac_f3(ev: FlipGateEvidence) -> tuple[bool, str]:
    missed = [d for d, fired in ev.v2_cca_event_states.items() if not fired]
    passed = len(missed) == 0
    verdict = "PASS" if passed else "FAIL"
    detail = f"missed: {missed}" if missed else "all 4 CCA dates fired"
    return passed, f"AC-F3 [{verdict}]: speed.confirmed_canary_active — {detail}"


def _eval_ac_f4(ev: FlipGateEvidence) -> tuple[bool, str]:
    v1_by_wid = {r["params"]["window_id"]: r for r in ev.v1_runs}
    v2_by_wid = {r["params"]["window_id"]: r for r in ev.v2_runs}
    failures = []
    for wid in CANONICAL_WINDOWS:
        v1_auc = v1_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        v2_auc = v2_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        if v1_auc is None or v2_auc is None:
            failures.append(f"{wid}: AUC missing")
            continue
        delta = v2_auc - v1_auc
        if delta < AC_F4_PER_WINDOW_TOLERANCE:
            failures.append(
                f"{wid}: v2={v2_auc:.4f} v1={v1_auc:.4f} delta={delta:+.4f}"
            )
    passed = not failures
    verdict = "PASS" if passed else "FAIL"
    detail = (
        "all 6 windows within tolerance" if passed else f"failed: {failures}"
    )
    return passed, f"AC-F4 [{verdict}]: per-window 60d AUC delta ≥ {AC_F4_PER_WINDOW_TOLERANCE} — {detail}"


def _eval_ac_f5(ev: FlipGateEvidence) -> tuple[bool, str]:
    watch = ev.v2_band_distribution.get("WATCH")
    if watch is None:
        return False, "AC-F5: v2 WATCH% unavailable"
    passed = watch <= AC_F5_WATCH_PCT_BAR
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F5 [{verdict}]: v2 WATCH% = {watch:.1f}% "
        f"(bar ≤ {AC_F5_WATCH_PCT_BAR}%)"
    )


def _eval_ac_f6(ev: FlipGateEvidence) -> tuple[bool, str]:
    passed = ev.oos_gate_passed and ev.v1_payload_hash_golden_passed
    verdict = "PASS" if passed else "FAIL"
    parts = []
    parts.append("oos_gate=" + ("PASS" if ev.oos_gate_passed else "FAIL"))
    parts.append("v1_golden=" + ("PASS" if ev.v1_payload_hash_golden_passed else "FAIL"))
    return passed, f"AC-F6 [{verdict}]: v1 unchanged — {', '.join(parts)}"


def render_canary_v1_v2_compare(ev: FlipGateEvidence) -> str:
    """Render v1-vs-v2 side-by-side comparison + AC-F1..F6 evaluation.

    Raises ValueError if FlipGateEvidence is structurally invalid (see
    _validate_evidence). Otherwise produces a complete markdown report.
    """
    _validate_evidence(ev)

    out = StringIO()
    out.write("# Canary v2-A — v1 vs v2 Comparison (PR 1 evidence package)\n\n")

    v2_batch_id = next(iter({r["params"]["batch_id"] for r in ev.v2_runs}))
    out.write(f"v2 batch_id: `{v2_batch_id}`\n")
    out.write(f"v2 robustness run id: {ev.v2_robustness_run.get('id')}\n\n")

    # AUC table
    out.write("## Full-history AUCs (composite over all snapshots)\n\n")
    out.write("| Horizon          | v1 (production) | v2 (research)   | Δ        |\n")
    out.write("|------------------|----------------:|----------------:|---------:|\n")
    for horizon in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        v1 = ev.v1_full_history_aucs.get(horizon)
        v2 = ev.v2_full_history_aucs.get(horizon)
        if v1 is None or v2 is None:
            out.write(f"| {horizon:<16} | n/a             | n/a             | n/a      |\n")
        else:
            d = v2 - v1
            out.write(f"| {horizon:<16} | {v1:>14.4f}  | {v2:>14.4f}  | {d:>+8.4f} |\n")
    out.write("\n")

    # Band distribution table
    out.write("## Band distribution (full-history snapshots)\n\n")
    out.write("| Band       |  v1 % |  v2 % |\n")
    out.write("|------------|------:|------:|\n")
    for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        v1 = ev.v1_band_distribution.get(band, 0.0)
        v2 = ev.v2_band_distribution.get(band, 0.0)
        out.write(f"| {band:<10} | {v1:>4.1f} | {v2:>4.1f} |\n")
    out.write("\n")

    # Per-window AUC table
    out.write("## Per-window 60d AUC (walk-forward)\n\n")
    out.write("| Window | v1 60d AUC | v2 60d AUC |    Δ    |\n")
    out.write("|--------|-----------:|-----------:|--------:|\n")
    v1_by_wid = {r["params"]["window_id"]: r for r in ev.v1_runs}
    v2_by_wid = {r["params"]["window_id"]: r for r in ev.v2_runs}
    for wid in CANONICAL_WINDOWS:
        v1 = v1_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        v2 = v2_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        if v1 is None or v2 is None:
            out.write(f"| {wid}    | n/a        | n/a        | n/a     |\n")
        else:
            d = v2 - v1
            out.write(f"| {wid}    | {v1:>9.4f}  | {v2:>9.4f}  | {d:>+7.4f} |\n")
    out.write("\n")

    # AC evaluation block
    out.write("## AC-F1..F6 Evaluation\n\n")
    results = [
        _eval_ac_f1(ev),
        _eval_ac_f2(ev),
        _eval_ac_f3(ev),
        _eval_ac_f4(ev),
        _eval_ac_f5(ev),
        _eval_ac_f6(ev),
    ]
    for _, line in results:
        out.write(f"- {line}\n")
    out.write("\n")

    all_pass = all(p for p, _ in results)
    verdict_line = "SHIP" if all_pass else "STOP"
    out.write(f"## Verdict: **{verdict_line}**\n\n")

    if all_pass:
        out.write(
            "All 6 AC-Fn gates passed. PR 2 may flip `COMPOSITE_VERSION = 1 → 2` "
            "in `src/uw_scan/cards/canary_calibration.py:11`. See spec §10 for the "
            "PR 2 task list.\n\n"
        )
    else:
        out.write(
            "One or more AC-Fn gates failed. **PR 2 is NOT authorized.** "
            "Record the verdict in `docs/research/regime/canary-5yr-executive-summary.md` "
            "§13, file a follow-up issue, and pivot to v2-C (issue #90).\n\n"
        )

    # Fixed footer
    out.write("## What PR 2 will do iff this verdict is SHIP\n\n")
    out.write(
        "PR 2 is a small (~80-150 LOC) commit that:\n"
        "1. Bumps `COMPOSITE_VERSION = 2` in `canary_calibration.py:11` "
        "(retargeting load_calibration() to v2.json is automatic via f-string).\n"
        "2. Regens `web/lib/types.ts` from updated OpenAPI schema.\n"
        "3. Replaces `LAST_KNOWN_AUC_v1_*` with `LAST_KNOWN_AUC_v2_*` constants "
        "derived from this report's AUC numbers.\n"
        "4. Updates `canary-methodology.md` to document v2 formula + the "
        "AC-F1..F6 gate satisfied.\n"
        "5. Adds a deprecation note in `canary-calibration-v1.json`.\n"
        "6. Updates `CanarySubTab.tsx` and `CanaryValidationPanel.tsx` to "
        "surface `vol_resolution_score` + `speed_state` + `warning_cap` "
        "separately.\n"
    )

    return out.getvalue()


def main() -> int:
    """Standalone CLI: re-render the latest v1 + v2 evidence bundle from DB.

    Use this for read-only re-rendering after the dispatcher has already
    persisted the evidence rows. For end-to-end (compute + render), use
    `scripts/backtest_canary.py --v1-v2-compare`.
    """
    p = argparse.ArgumentParser(description=__doc__)
    args = p.parse_args()

    # Lazy import to avoid circular deps in tests
    from scripts.backtest_canary import _assemble_flip_gate_evidence  # type: ignore[import]

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        ev = _assemble_flip_gate_evidence(conn, schema=settings.db_schema)

    print(render_canary_v1_v2_compare(ev))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the failing renderer unit tests**

Path: `tests/unit/test_canary_v1_v2_compare_renderer.py`

```python
"""Unit tests for render_canary_v1_v2_compare.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md §5.7.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from uw_scan.reports.regime_canary_v1_v2_compare import (
    CANONICAL_WINDOWS,
    CCA_EVENT_DATES,
    FlipGateEvidence,
    render_canary_v1_v2_compare,
)

# A minimal happy-path fixture that passes ALL six ACs.
def _mk_run(*, version: str, scope: str, window_id: str, auc_60d: float = 0.65) -> dict:
    return {
        "id": 100 + ord(window_id[-1]),
        "composite_version": version,
        "run_scope": scope,
        "params": {
            "phase": "walk_forward",
            "batch_id": "batch-v2-test" if version == "2" else "batch-v1-test",
            "window_id": window_id,
            "score_form": "linear",
        },
        "summary": {
            "aucs": {
                "composite": {
                    "up5d_2pct": 0.62,
                    "up20d_5pct": 0.63,
                    "up60d_10pct": auc_60d,
                }
            }
        },
    }


def _happy_evidence() -> FlipGateEvidence:
    return FlipGateEvidence(
        v1_runs=[_mk_run(version="1", scope="production", window_id=w) for w in CANONICAL_WINDOWS],
        v2_runs=[_mk_run(version="2", scope="research", window_id=w) for w in CANONICAL_WINDOWS],
        v2_robustness_run={
            "id": 999,
            "composite_version": "2",
            "run_scope": "research",
            "params": {"phase": "robustness", "batch_id": "batch-v2-test"},
            "summary": {},
        },
        v1_full_history_aucs={"up5d_2pct": 0.62, "up20d_5pct": 0.627, "up60d_10pct": 0.619},
        v2_full_history_aucs={"up5d_2pct": 0.625, "up20d_5pct": 0.635, "up60d_10pct": 0.640},
        v1_band_distribution={"NONE": 55.0, "WATCH": 39.3, "BUY": 5.5, "STRONG_BUY": 0.2},
        v2_band_distribution={"NONE": 60.0, "WATCH": 35.0, "BUY": 4.9, "STRONG_BUY": 0.1},
        v2_cca_event_states={d: True for d in CCA_EVENT_DATES},
        oos_gate_passed=True,
        v1_payload_hash_golden_passed=True,
    )


def test_happy_path_ship_verdict():
    """All 6 ACs passing → verdict SHIP."""
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Verdict: **SHIP**" in out
    assert "AC-F1 [PASS]" in out
    assert "AC-F2 [PASS]" in out
    assert "AC-F3 [PASS]" in out
    assert "AC-F4 [PASS]" in out
    assert "AC-F5 [PASS]" in out
    assert "AC-F6 [PASS]" in out


def test_ac_f1_fail_below_bar():
    """v2 60d AUC = 0.620 (below 0.634 bar) → AC-F1 FAIL, verdict STOP."""
    ev = _happy_evidence()
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs={"up5d_2pct": 0.625, "up20d_5pct": 0.635, "up60d_10pct": 0.620},
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution=ev.v2_band_distribution,
        v2_cca_event_states=ev.v2_cca_event_states,
        oos_gate_passed=ev.oos_gate_passed,
        v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F1 [FAIL]" in out
    assert "Verdict: **STOP**" in out


def test_ac_f2_fail_20d_horizon():
    """v2 20d AUC = 0.610 (below 0.622 bar) → AC-F2 FAIL."""
    ev = _happy_evidence()
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs={"up5d_2pct": 0.625, "up20d_5pct": 0.610, "up60d_10pct": 0.640},
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution=ev.v2_band_distribution,
        v2_cca_event_states=ev.v2_cca_event_states,
        oos_gate_passed=ev.oos_gate_passed,
        v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F2 [FAIL]" in out
    assert "Verdict: **STOP**" in out


def test_ac_f3_fail_when_cca_event_missing_fire():
    """If any CCA event date has confirmed_canary_active=False → AC-F3 FAIL."""
    ev = _happy_evidence()
    cca = dict(ev.v2_cca_event_states)
    cca["2011-08-08"] = False
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs=ev.v2_full_history_aucs,
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution=ev.v2_band_distribution,
        v2_cca_event_states=cca,
        oos_gate_passed=ev.oos_gate_passed,
        v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F3 [FAIL]" in out
    assert "2011-08-08" in out


def test_ac_f4_fail_when_window_regresses_more_than_002():
    """If any window v2−v1 60d AUC < −0.02 → AC-F4 FAIL."""
    ev = _happy_evidence()
    v2_runs = list(deepcopy(ev.v2_runs))
    # Knock WF-3 from 0.65 down to 0.60; with v1 at 0.65 this is −0.05 < −0.02.
    v2_runs[2]["summary"]["aucs"]["composite"]["up60d_10pct"] = 0.60
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs=ev.v2_full_history_aucs,
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution=ev.v2_band_distribution,
        v2_cca_event_states=ev.v2_cca_event_states,
        oos_gate_passed=ev.oos_gate_passed,
        v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F4 [FAIL]" in out
    assert "WF-3" in out


def test_ac_f5_fail_when_watch_pct_too_high():
    """v2 WATCH% = 50.0 (above 44.3 bar) → AC-F5 FAIL."""
    ev = _happy_evidence()
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs=ev.v2_full_history_aucs,
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution={"NONE": 44.5, "WATCH": 50.0, "BUY": 5.4, "STRONG_BUY": 0.1},
        v2_cca_event_states=ev.v2_cca_event_states,
        oos_gate_passed=ev.oos_gate_passed,
        v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F5 [FAIL]" in out


def test_ac_f6_fail_when_oos_gate_fails():
    ev = _happy_evidence()
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs=ev.v2_full_history_aucs,
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution=ev.v2_band_distribution,
        v2_cca_event_states=ev.v2_cca_event_states,
        oos_gate_passed=False,
        v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F6 [FAIL]" in out


def test_ac_f6_fail_when_v1_golden_fails():
    ev = _happy_evidence()
    ev = FlipGateEvidence(
        v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
        v1_full_history_aucs=ev.v1_full_history_aucs,
        v2_full_history_aucs=ev.v2_full_history_aucs,
        v1_band_distribution=ev.v1_band_distribution,
        v2_band_distribution=ev.v2_band_distribution,
        v2_cca_event_states=ev.v2_cca_event_states,
        oos_gate_passed=ev.oos_gate_passed,
        v1_payload_hash_golden_passed=False,
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F6 [FAIL]" in out


def test_invalid_v1_runs_count_raises():
    ev = _happy_evidence()
    with pytest.raises(ValueError, match="v1_runs must have 6"):
        render_canary_v1_v2_compare(
            FlipGateEvidence(
                v1_runs=ev.v1_runs[:5],  # only 5 — invalid
                v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
                v1_full_history_aucs=ev.v1_full_history_aucs,
                v2_full_history_aucs=ev.v2_full_history_aucs,
                v1_band_distribution=ev.v1_band_distribution,
                v2_band_distribution=ev.v2_band_distribution,
                v2_cca_event_states=ev.v2_cca_event_states,
                oos_gate_passed=ev.oos_gate_passed,
                v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
            )
        )


def test_invalid_v2_scope_raises():
    ev = _happy_evidence()
    bad = [deepcopy(r) for r in ev.v2_runs]
    bad[0]["run_scope"] = "production"  # invalid — v2 must be research
    with pytest.raises(ValueError, match="run_scope"):
        render_canary_v1_v2_compare(
            FlipGateEvidence(
                v1_runs=ev.v1_runs, v2_runs=bad, v2_robustness_run=ev.v2_robustness_run,
                v1_full_history_aucs=ev.v1_full_history_aucs,
                v2_full_history_aucs=ev.v2_full_history_aucs,
                v1_band_distribution=ev.v1_band_distribution,
                v2_band_distribution=ev.v2_band_distribution,
                v2_cca_event_states=ev.v2_cca_event_states,
                oos_gate_passed=ev.oos_gate_passed,
                v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
            )
        )


def test_invalid_window_id_set_raises():
    ev = _happy_evidence()
    bad = [deepcopy(r) for r in ev.v2_runs]
    bad[0]["params"]["window_id"] = "WF-99"  # invalid
    with pytest.raises(ValueError, match="window_ids"):
        render_canary_v1_v2_compare(
            FlipGateEvidence(
                v1_runs=ev.v1_runs, v2_runs=bad, v2_robustness_run=ev.v2_robustness_run,
                v1_full_history_aucs=ev.v1_full_history_aucs,
                v2_full_history_aucs=ev.v2_full_history_aucs,
                v1_band_distribution=ev.v1_band_distribution,
                v2_band_distribution=ev.v2_band_distribution,
                v2_cca_event_states=ev.v2_cca_event_states,
                oos_gate_passed=ev.oos_gate_passed,
                v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
            )
        )


def test_v2_runs_must_share_batch_id():
    ev = _happy_evidence()
    bad = [deepcopy(r) for r in ev.v2_runs]
    bad[0]["params"]["batch_id"] = "different-batch"
    with pytest.raises(ValueError, match="batch_id"):
        render_canary_v1_v2_compare(
            FlipGateEvidence(
                v1_runs=ev.v1_runs, v2_runs=bad, v2_robustness_run=ev.v2_robustness_run,
                v1_full_history_aucs=ev.v1_full_history_aucs,
                v2_full_history_aucs=ev.v2_full_history_aucs,
                v1_band_distribution=ev.v1_band_distribution,
                v2_band_distribution=ev.v2_band_distribution,
                v2_cca_event_states=ev.v2_cca_event_states,
                oos_gate_passed=ev.oos_gate_passed,
                v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
            )
        )


def test_missing_cca_event_date_raises():
    ev = _happy_evidence()
    bad_cca = {d: True for d in CCA_EVENT_DATES if d != "2020-03-09"}
    with pytest.raises(ValueError, match="2020-03-09"):
        render_canary_v1_v2_compare(
            FlipGateEvidence(
                v1_runs=ev.v1_runs, v2_runs=ev.v2_runs, v2_robustness_run=ev.v2_robustness_run,
                v1_full_history_aucs=ev.v1_full_history_aucs,
                v2_full_history_aucs=ev.v2_full_history_aucs,
                v1_band_distribution=ev.v1_band_distribution,
                v2_band_distribution=ev.v2_band_distribution,
                v2_cca_event_states=bad_cca,
                oos_gate_passed=ev.oos_gate_passed,
                v1_payload_hash_golden_passed=ev.v1_payload_hash_golden_passed,
            )
        )


def test_footer_present_in_both_verdicts():
    """The 'What PR 2 will do' footer must appear in both SHIP and STOP."""
    ev_ship = _happy_evidence()
    out_ship = render_canary_v1_v2_compare(ev_ship)
    assert "What PR 2 will do iff this verdict is SHIP" in out_ship

    ev_stop = FlipGateEvidence(
        v1_runs=ev_ship.v1_runs, v2_runs=ev_ship.v2_runs,
        v2_robustness_run=ev_ship.v2_robustness_run,
        v1_full_history_aucs=ev_ship.v1_full_history_aucs,
        v2_full_history_aucs={"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
        v1_band_distribution=ev_ship.v1_band_distribution,
        v2_band_distribution=ev_ship.v2_band_distribution,
        v2_cca_event_states=ev_ship.v2_cca_event_states,
        oos_gate_passed=ev_ship.oos_gate_passed,
        v1_payload_hash_golden_passed=ev_ship.v1_payload_hash_golden_passed,
    )
    out_stop = render_canary_v1_v2_compare(ev_stop)
    assert "What PR 2 will do iff this verdict is SHIP" in out_stop
    assert "Verdict: **STOP**" in out_stop


def test_band_distribution_table_present():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Band distribution" in out
    for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        assert band in out


def test_per_window_table_present_with_all_6_windows():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Per-window 60d AUC" in out
    for wid in CANONICAL_WINDOWS:
        assert wid in out


def test_full_history_auc_table_present_with_all_3_horizons():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Full-history AUCs" in out
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert h in out
```

- [ ] **Step 3: Run the renderer tests — verify they pass**

```bash
uv run pytest tests/unit/test_canary_v1_v2_compare_renderer.py -v
```

Expected: 16 passed.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/reports/regime_canary_v1_v2_compare.py tests/unit/test_canary_v1_v2_compare_renderer.py
git commit -m "feat(canary): render_canary_v1_v2_compare + FlipGateEvidence + 16 tests

Pure-function renderer takes a FlipGateEvidence dataclass and renders
the markdown side-by-side comparison + AC-F1..F6 evaluation block +
SHIP/STOP verdict + locked PR-2 footer.

The renderer NEVER touches the DB. All evidence (v1+v2 runs, full-history
AUCs, band distributions, CCA event states, OOS gate result, golden test
result) is pre-assembled by the dispatcher (Task 10).

This separation matters because AC-F3/F5/F6 require data outside
regime_backtest_runs — Codex caught this during /review-cycle. The original
draft signature (v1_runs, v2_runs) was insufficient.

16 unit tests:
- Happy path: all 6 ACs pass → SHIP
- One test per AC failure: F1 below bar, F2 short-horizon, F3 missed
  CCA, F4 per-window regression, F5 WATCH% expansion, F6 OOS gate fail,
  F6 v1 golden fail
- Structural guards: ValueError on wrong v1 count / wrong scope /
  wrong window_id set / mismatched batch_id / missing CCA date
- Footer present in both SHIP and STOP
- Table presence: band distribution, per-window, full-history AUC

Standalone CLI entry: python -m uw_scan.reports.regime_canary_v1_v2_compare
(uses _assemble_flip_gate_evidence from scripts.backtest_canary — Task 10).

Spec §5.2, §5.7."
```

---

### Task 10: `--v1-v2-compare` dispatcher in `backtest_canary.py` (loads + renders)

**Files:**
- Modify: `scripts/backtest_canary.py` (add `_assemble_flip_gate_evidence` + `cmd_v1_v2_compare` + `--v1-v2-compare` flag)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py` (add dispatcher integration test)

**Rationale:** The dispatcher assembles `FlipGateEvidence` from DB by running 8 SQL queries + 2 pytest invocations (OOS gate + v1 golden). Renderer is pure; assembly is impure.

- [ ] **Step 1: Write the dispatcher**

In `scripts/backtest_canary.py`, add (after existing cmd_robustness or in the dispatcher section):

```python
import subprocess
from typing import Any


def _assemble_flip_gate_evidence(conn, *, schema: str) -> Any:
    """Build a FlipGateEvidence from DB. Heavy SQL — only run in --v1-v2-compare."""
    from uw_scan.reports.regime_canary_v1_v2_compare import (
        CCA_EVENT_DATES,
        CANONICAL_WINDOWS,
        FlipGateEvidence,
    )

    with conn.cursor() as cur:
        # v1 walk-forward runs — latest completed per window_id
        cur.execute(
            f"""
            WITH ranked AS (
              SELECT id, composite_version, run_scope, params, summary,
                     ROW_NUMBER() OVER (
                       PARTITION BY params->>'window_id'
                       ORDER BY completed_at DESC
                     ) AS rn
              FROM {schema}.regime_backtest_runs
              WHERE indicator='canary' AND run_scope='production'
                AND composite_version='1'
                AND params->>'phase'='walk_forward'
                AND completed_at IS NOT NULL
            )
            SELECT id, composite_version, run_scope, params, summary
            FROM ranked WHERE rn=1 ORDER BY params->>'window_id'
            """
        )
        v1_rows = cur.fetchall()
        v1_runs = [
            {
                "id": r[0], "composite_version": r[1], "run_scope": r[2],
                "params": r[3], "summary": r[4],
            } for r in v1_rows
        ]
        if len(v1_runs) != 6:
            raise RuntimeError(
                f"v1 walk-forward query returned {len(v1_runs)} rows, expected 6 "
                f"(one per window_id WF-1..WF-6). Check PR #83 persistence."
            )

        # v2 walk-forward runs — latest complete batch (must cover WF-1..WF-6)
        cur.execute(
            f"""
            WITH batches AS (
              SELECT params->>'batch_id' AS batch_id,
                     MAX(completed_at) AS latest,
                     ARRAY_AGG(params->>'window_id' ORDER BY params->>'window_id') AS wids
              FROM {schema}.regime_backtest_runs
              WHERE indicator='canary' AND run_scope='research'
                AND composite_version='2'
                AND params->>'phase'='walk_forward'
                AND completed_at IS NOT NULL
              GROUP BY params->>'batch_id'
            )
            SELECT batch_id FROM batches
            WHERE wids = ARRAY['WF-1','WF-2','WF-3','WF-4','WF-5','WF-6']
            ORDER BY latest DESC LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                "no complete v2 walk-forward batch found. Run "
                "`backtest_canary.py --walk-forward --composite-version 2` first."
            )
        v2_batch_id = row[0]

        cur.execute(
            f"SELECT id, composite_version, run_scope, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id'=%s AND params->>'phase'='walk_forward' "
            f"ORDER BY params->>'window_id'",
            (v2_batch_id,),
        )
        v2_runs = [
            {"id": r[0], "composite_version": r[1], "run_scope": r[2],
             "params": r[3], "summary": r[4]} for r in cur.fetchall()
        ]

        # v2 robustness run (same batch_id, phase='robustness')
        cur.execute(
            f"SELECT id, composite_version, run_scope, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id'=%s AND params->>'phase'='robustness' "
            f"ORDER BY completed_at DESC LIMIT 1",
            (v2_batch_id,),
        )
        rb_row = cur.fetchone()
        if rb_row is None:
            raise RuntimeError(
                f"no v2 robustness run for batch_id={v2_batch_id}. Run "
                f"`backtest_canary.py --robustness --composite-version 2 --batch-id {v2_batch_id}`."
            )
        v2_robustness_run = {
            "id": rb_row[0], "composite_version": rb_row[1], "run_scope": rb_row[2],
            "params": rb_row[3], "summary": rb_row[4],
        }

        # Full-history AUCs — compute via _aucs_for_rows on canary_snapshots
        v1_full_history_aucs = _full_history_aucs_for_version(conn, schema=schema, version=1)
        v2_full_history_aucs = _full_history_aucs_for_version(conn, schema=schema, version=2)

        # Band distributions
        v1_band_distribution = _band_distribution_for_version(conn, schema=schema, version=1)
        v2_band_distribution = _band_distribution_for_version(conn, schema=schema, version=2)

        # CCA event states for v2
        cur.execute(
            f"SELECT data_date::text, payload->'speed'->>'confirmed_canary_active' "
            f"FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 AND data_date = ANY(%s)",
            ([d for d in CCA_EVENT_DATES],),
        )
        v2_cca_event_states = {
            d: (str(v).lower() == "true") for d, v in cur.fetchall()
        }
        # Fill missing dates with False so the renderer catches them
        for d in CCA_EVENT_DATES:
            v2_cca_event_states.setdefault(d, False)

    # Run external tests for AC-F6
    oos_gate_passed = _run_test_subprocess(
        "tests/integration/regime/test_canary_oos_gate.py"
    )
    v1_payload_hash_golden_passed = _run_test_subprocess(
        "tests/unit/test_canary_v1_payload_hash_golden.py"
    )

    return FlipGateEvidence(
        v1_runs=v1_runs,
        v2_runs=v2_runs,
        v2_robustness_run=v2_robustness_run,
        v1_full_history_aucs=v1_full_history_aucs,
        v2_full_history_aucs=v2_full_history_aucs,
        v1_band_distribution=v1_band_distribution,
        v2_band_distribution=v2_band_distribution,
        v2_cca_event_states=v2_cca_event_states,
        oos_gate_passed=oos_gate_passed,
        v1_payload_hash_golden_passed=v1_payload_hash_golden_passed,
    )


def _full_history_aucs_for_version(conn, *, schema: str, version: int) -> dict[str, float]:
    """Compute composite AUC over all canary_snapshots at composite_version=N.

    Uses _aucs_for_rows (the same function form-sweep uses)."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data_date, score, band, "
            f"  payload->>'tactical' AS tactical, payload->>'structural' AS structural, "
            f"  payload->>'speed' AS speed, payload->>'warning_state' AS warning_state "
            f"FROM {schema}.canary_snapshots "
            f"WHERE composite_version=%s ORDER BY data_date",
            (version,),
        )
        rows = [
            {
                "date": r[0],
                "score": float(r[1]),
                "band": r[2],
                "tactical": float(r[3]) if r[3] else 0.0,
                "structural": float(r[4]) if r[4] else 0.0,
                "speed": int(float(r[5])) if r[5] else 0,
                "warning_state": r[6],
            }
            for r in cur.fetchall()
        ]
    # _aucs_for_rows returns {composite: {...}, vol_only: {...}, speed_only: {...}}
    # We only need the composite slice for AC-F1/F2.
    aucs = _aucs_for_rows(rows)  # function already exists in this script
    return aucs["composite"]


def _band_distribution_for_version(conn, *, schema: str, version: int) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT band, COUNT(*) FROM {schema}.canary_snapshots "
            f"WHERE composite_version=%s GROUP BY band",
            (version,),
        )
        counts = dict(cur.fetchall())
    total = sum(counts.values())
    if total == 0:
        return {band: 0.0 for band in ("NONE", "WATCH", "BUY", "STRONG_BUY")}
    return {
        band: 100.0 * counts.get(band, 0) / total
        for band in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    }


def _run_test_subprocess(test_path: str) -> bool:
    """Run pytest on a single test file, return True if all tests passed."""
    proc = subprocess.run(
        ["uv", "run", "pytest", test_path, "-q", "--no-header"],
        capture_output=True, text=True, timeout=300,
    )
    return proc.returncode == 0


def cmd_v1_v2_compare(conn, *, schema: str) -> None:
    """--v1-v2-compare dispatcher: assemble FlipGateEvidence, render, print."""
    from uw_scan.reports.regime_canary_v1_v2_compare import (
        render_canary_v1_v2_compare,
    )

    ev = _assemble_flip_gate_evidence(conn, schema=schema)
    print(render_canary_v1_v2_compare(ev))
```

**1b. Add the `--v1-v2-compare` flag to argparse + dispatch:**

```python
    parser.add_argument(
        "--v1-v2-compare",
        action="store_true",
        help=(
            "Assemble FlipGateEvidence from DB (v1 production + v2 research walk-forward "
            "+ robustness + full-history AUCs + band distributions + CCA event states + "
            "OOS gate + v1 golden) and render the v1-vs-v2 comparison report with "
            "AC-F1..F6 evaluation. Mutually exclusive with all other modes."
        ),
    )
```

In the main dispatcher branch, add (with mutual exclusion check):

```python
    if args.v1_v2_compare:
        if any([args.walk_forward, args.robustness, args.calibrate,
                args.form_sweep, args.form_sweep_full]):
            parser.error(
                "--v1-v2-compare is mutually exclusive with all other modes"
            )
        cmd_v1_v2_compare(conn, schema=schema)
        return
```

- [ ] **Step 2: Write the integration test**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
def test_v1_v2_compare_dispatcher_renders_nonempty(
    seeded_db_with_v1_walk_forward_and_v2_evidence,
):
    """End-to-end: --v1-v2-compare assembles FlipGateEvidence and prints
    a non-empty markdown report containing the required sections.

    Fixture provides: v1 walk-forward rows (6, production), v2 walk-forward
    rows (6, research, shared batch_id), v2 robustness row, v1 + v2 snapshots."""
    conn = seeded_db_with_v1_walk_forward_and_v2_evidence.conn

    result = subprocess.run(
        [
            sys.executable,
            str(BACKTEST_SCRIPT),
            "--v1-v2-compare",
        ],
        env={
            "DATABASE_URL": seeded_db_with_v1_walk_forward_and_v2_evidence.url,
            "UW_SCAN_API_KEY": "local-test",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True, text=True, timeout=300,
    )

    assert result.returncode == 0, f"dispatcher failed: {result.stderr}"
    out = result.stdout
    # Required sections
    assert "Canary v2-A — v1 vs v2 Comparison" in out
    assert "Full-history AUCs" in out
    assert "Band distribution" in out
    assert "Per-window 60d AUC" in out
    assert "AC-F1..F6 Evaluation" in out
    assert "Verdict:" in out
    assert "What PR 2 will do" in out


def test_v1_v2_compare_fails_clearly_when_no_v2_batch(seeded_db_with_only_v1):
    """If no complete v2 walk-forward batch exists, dispatcher exits non-zero
    with an actionable error."""
    result = subprocess.run(
        [
            sys.executable,
            str(BACKTEST_SCRIPT),
            "--v1-v2-compare",
        ],
        env={
            "DATABASE_URL": seeded_db_with_only_v1.url,
            "UW_SCAN_API_KEY": "local-test",
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    assert "no complete v2 walk-forward batch" in (result.stderr + result.stdout).lower()
```

- [ ] **Step 3: Run integration tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v1_v2_compare_dispatcher_renders_nonempty \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v1_v2_compare_fails_clearly_when_no_v2_batch \
    -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): --v1-v2-compare dispatcher + FlipGateEvidence assembly

Dispatcher assembles FlipGateEvidence from DB via 8 SQL queries + 2
subprocess invocations (OOS gate test + v1 golden test), then calls
the pure renderer.

Loaders:
- v1_runs: latest completed walk-forward per window_id, production scope, v=1
- v2_runs: latest complete v2 batch covering all of WF-1..WF-6, research
  scope, v=2
- v2_robustness_run: same batch_id, phase='robustness'
- v1/v2_full_history_aucs: _aucs_for_rows over canary_snapshots at the
  given composite_version (matches PR #88 form-sweep computation)
- v1/v2_band_distribution: GROUP BY band over canary_snapshots
- v2_cca_event_states: payload.speed.confirmed_canary_active per CCA date
- oos_gate_passed: pytest subprocess on test_canary_oos_gate.py
- v1_payload_hash_golden_passed: pytest subprocess on test_canary_v1_payload_hash_golden.py

2 integration tests:
- Dispatcher renders all required sections + verdict + footer
- Dispatcher fails clearly when no complete v2 batch exists

Spec §5.5, §5.7."
```

---

### Task 11: Walk-forward cleanup-on-failure via `delete_canary_research_runs_by_batch_id_and_phase`

**Files:**
- Modify: `scripts/backtest_canary.py` (wrap walk-forward + robustness persistence in try/except with cleanup)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** When v2 walk-forward fails mid-batch (e.g., the 4th of 6 inserts errors), partial rows remain. The cleanup pattern is exactly the form-sweep pattern from PR #88 §3.4 (rollback + scoped delete + raise original).

- [ ] **Step 1: Write failing test**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
import unittest.mock as mock


def test_v2_walk_forward_cleanup_on_mid_batch_failure(seeded_db_with_v2_backfill):
    """If insert_run fails on the 4th of 6 walk-forward windows, ALL 6 partial
    rows are cleaned up (the 3 successfully-inserted + the 4th half-inserted).
    Spec §5.8."""
    conn = seeded_db_with_v2_backfill.conn
    schema = seeded_db_with_v2_backfill._schema

    # Patch bulk_insert_daily to raise on the 4th call (after 3 walk-forward
    # window runs have been persisted)
    call_count = [0]
    original_bulk_insert = ...  # capture original — implementer detail

    def flaky_bulk_insert(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 4:
            raise RuntimeError("simulated 4th-window failure")
        return original_bulk_insert(*args, **kwargs)

    # Run with the patched method
    with mock.patch(
        "uw_scan.storage.regime_backtest_repository.RegimeBacktestRepository.bulk_insert_daily",
        side_effect=flaky_bulk_insert,
    ):
        result = _run_walk_forward(
            composite_version=2,
            test_db_url=seeded_db_with_v2_backfill.url,
        )
    # Expect non-zero exit
    assert result.returncode != 0

    # Assert: zero v2 walk-forward rows remain (all cleaned up)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='walk_forward'"
        )
        count = cur.fetchone()[0]
    assert count == 0, f"expected 0 leftover walk-forward rows, got {count}"

    # And v1 production rows MUST remain untouched
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='production' "
            f"  AND composite_version='1' AND params->>'phase'='walk_forward'"
        )
        v1_count = cur.fetchone()[0]
    assert v1_count == 6, f"v1 walk-forward rows damaged: {v1_count}"
```

(Note: the subprocess-based test won't easily mock `bulk_insert_daily` from outside. The implementer may convert this to an in-process test that calls `cmd_walk_forward` directly with a `monkeypatch` fixture. Adapt as needed.)

- [ ] **Step 2: Wrap walk-forward persistence in try/except in `backtest_canary.py`**

In `cmd_walk_forward` (or wherever v2 walk-forward batches are persisted), wrap the persistence loop:

```python
    batch_id = args.batch_id or str(uuid.uuid4())
    try:
        for window_id, run_payload in windows_to_persist:
            run_id = bt_repo.insert_run(
                ...,
                params={"phase": "walk_forward", "batch_id": batch_id,
                        "window_id": window_id, ...},
                run_scope=run_scope,
            )
            bt_repo.bulk_insert_daily(run_id, run_payload["daily_rows"])
            bt_repo.mark_run_completed(run_id)
    except Exception as original:
        try:
            conn.rollback()
        except Exception as rollback_err:
            log.exception(
                "rollback failed during walk-forward cleanup: %s", rollback_err
            )
        try:
            n = bt_repo.delete_canary_research_runs_by_batch_id_and_phase(
                batch_id, "walk_forward"
            )
            log.warning(
                "Cleaned up %d partial walk-forward rows for batch_id=%s",
                n, batch_id,
            )
        except Exception as cleanup_err:
            log.exception(
                "delete_canary_research_runs_by_batch_id_and_phase(%s, walk_forward) "
                "failed during cleanup: %s",
                batch_id, cleanup_err,
            )
        raise original
```

(Apply the same pattern to robustness.)

- [ ] **Step 3: Run the cleanup test — verify it passes**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v2_walk_forward_cleanup_on_mid_batch_failure -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): v2 walk-forward cleanup-on-failure via scoped delete

Wraps the v2 walk-forward persistence loop in try/except: on any
exception, rolls back the transaction (Postgres InFailedSqlTransaction
requires it before the next query), runs the scoped DELETE via
delete_canary_research_runs_by_batch_id_and_phase, then re-raises the
original exception. Same pattern as PR #88 form-sweep §3.4.

Mirrors the same pattern for robustness (phase='robustness' in the
delete call).

1 integration test: simulated 4th-window bulk_insert failure cleans up
all partial rows (incl. the 3 successfully-persisted ones) AND leaves
v1 production rows untouched.

Spec §5.8."
```

---

### Task 12: Final smoke + live verification on real DB

**Files:** none (live commands only)

**Rationale:** Beyond unit + integration tests against pytest-postgresql, prove end-to-end against the dev DB with real `vol_index_daily` data. This is also where AC-F3's CCA-event-fires evidence comes in if the integration fixture didn't include the full historical window.

- [ ] **Step 1: Run v2 backfill against dev DB**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/canary_backfill.py \
      --composite-version 2 \
      --start-date 2011-02-08 \
      --end-date 2026-05-21
```

Expected: ~3,843 rows inserted (no errors). Re-run as no-op.

- [ ] **Step 2: Verify v2 snapshot count matches v1**

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -X -A -F'|' -c "
  SELECT composite_version, COUNT(*) FROM uw_scan.canary_snapshots
  WHERE composite_version IN (1,2)
  GROUP BY composite_version ORDER BY composite_version;
"
```

Expected: both `1` and `2` have ~3,843 rows (same count).

- [ ] **Step 3: Run v2 walk-forward**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py --walk-forward --composite-version 2
```

Expected: 6 new rows in `regime_backtest_runs` (research scope, composite_version='2').

Note the printed `batch_id` from stdout (UUID4).

- [ ] **Step 4: Run v2 robustness (chained to the same batch)**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py \
      --robustness --composite-version 2 \
      --batch-id <batch_id_from_step_3>
```

Expected: 1 new row with `phase='robustness'`, same batch_id.

- [ ] **Step 5: AC-F3 smoke check — 4 CCA event dates**

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -X -A -F'|' -c "
  SELECT data_date, payload->'speed'->>'confirmed_canary_active' AS cca_active
  FROM uw_scan.canary_snapshots
  WHERE composite_version=2
    AND data_date IN ('2011-08-08','2015-08-24','2018-02-05','2020-03-09')
  ORDER BY data_date;
"
```

Expected: all 4 dates show `cca_active = true`. (If not, AC-F3 fails — investigate, the cap mechanism is broken.)

- [ ] **Step 6: Run --v1-v2-compare to render the report**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py --v1-v2-compare
```

Expected: markdown report to stdout with:
- Full-history AUCs table (v1 + v2 columns + delta)
- Band distribution table
- Per-window 60d AUC table (6 windows)
- AC-F1..F6 evaluation block (each line PASS or FAIL)
- Verdict (SHIP or STOP)
- "What PR 2 will do" footer

- [ ] **Step 7: Run the full test suite**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/unit/test_canary_v2_formula.py \
    tests/unit/test_canary_v1_payload_hash_golden.py \
    tests/unit/test_canary_v1_v2_compare_renderer.py \
    tests/integration/regime/test_canary_v2_backfill.py \
    tests/integration/regime/test_canary_v2_walk_forward.py \
    -v
```

Expected: ~44 tests passed.

- [ ] **Step 8: Run non-regression on existing canary tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_oos_gate.py \
    tests/integration/regime/test_canary_form_sweep_full.py \
    tests/integration/regime/test_canary_backtest.py \
    -v
```

Expected: all green; nothing regressed.

- [ ] **Step 9: Verify calibration v1 file untouched**

```bash
md5 docs/research/regime/canary-calibration-v1.json
```

Expected: `407024fadb7e7b46417f08f4d019d991` (unchanged from PR #83 + PR #88).

- [ ] **Step 10: Verify production scope leakage**

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -X -A -F'|' -c "
  SELECT id, params->>'phase' AS phase, run_scope, composite_version
  FROM uw_scan.regime_backtest_runs
  WHERE indicator='canary' AND completed_at IS NOT NULL
    AND run_scope='production'
  ORDER BY created_at DESC LIMIT 10;
"
```

Expected: ZERO rows with `composite_version='2'` — production scope sees only v1.

- [ ] **Step 11: Final commit (smoke results recorded)**

If everything green:

```bash
git commit --allow-empty -m "chore(canary): v2-A PR 1 evidence ready for review

Live smoke against dev DB:
- v2 backfill: ~3,843 rows at composite_version=2 (matches v1 count)
- v2 walk-forward: 6 research-scoped runs with shared batch_id
- v2 robustness: 1 research-scoped run, same batch_id
- AC-F3 evidence: 4 CCA event dates all fire confirmed_canary_active=true
- --v1-v2-compare renders the full report with AC-F1..F6 verdict
- 44/44 new tests passing
- 18/18 pre-existing canary tests passing (no regression)
- canary-calibration-v1.json MD5 unchanged: 407024fadb7e7b46417f08f4d019d991
- Zero composite_version=2 rows visible to production-scope queries

PR 1 is ready for review. The verdict from --v1-v2-compare will determine
whether PR 2 (the production flip) is authorized per spec §8 AC-F1..F6."
```

---

## Spec Coverage Map

| Spec section / AC | Task(s) implementing it |
|---|---|
| §5.3 Conditional path code | Task 2 |
| §5.4 Calibration JSON v2 | Task 1 |
| §5.5 `canary_backfill.py --composite-version` | Task 5 |
| §5.5 `--walk-forward --composite-version 2` | Task 6 |
| §5.5 `--robustness --composite-version 2` | Task 7 |
| §5.5 `--v1-v2-compare` | Task 10 |
| §5.6 Persistence model | Tasks 5, 6, 7 (composite_version tagging) |
| §5.7 Renderer + FlipGateEvidence | Task 9 |
| §5.8 Error handling (cleanup-on-failure) | Task 11 |
| §6 Layer 1 (snapshot scope) | Task 5 |
| §6 Layer 2 (run_scope) | Tasks 6, 7 |
| §6 Layer 3 (COMPOSITE_VERSION constant) | Task 3 (test guards) + non-modification across all tasks |
| §6 Layer 4 (cal.composite_version persistence rule) | Tasks 5, 6, 7 |
| §6 Layer 5 (OOS gate untouched) | Task 12 Step 8 (non-regression) |
| §6 Layer 6 (caller-discipline) | Tasks 6, 7 (explicit run_scope=research kwarg) |
| §7 AC-1 (formula unit tests) | Task 2 |
| §7 AC-2 (v2 calibration parses) | Task 1 |
| §7 AC-3 (backfill writes v2 rows) | Task 5 |
| §7 AC-3a (CCA event evidence) | Task 5 + Task 12 Step 5 |
| §7 AC-4 (walk-forward) | Task 6 |
| §7 AC-4a (robustness) | Task 7 |
| §7 AC-4b (recompute vs backfill parity) | Task 8 |
| §7 AC-5 (dispatcher renders) | Task 10 |
| §7 AC-5a (delete_canary_research_runs_by_batch_id_and_phase) | Task 4 |
| §7 AC-6 (v1 payload-hash golden) | Task 3 |
| §7 AC-6a (OOS gate non-regression) | Task 12 Step 8 |
| §7 AC-7 (ruff) | Task 12 Step 7 |
| §7 AC-8 (CI) | Task 12 (post-push) |
| §8 AC-F1 (60d AUC ≥ 0.634) | Renderer (Task 9) + dispatcher (Task 10) |
| §8 AC-F2 (20d/5d AUC) | Renderer (Task 9) + dispatcher (Task 10) |
| §8 AC-F3 (CCA event states) | Tasks 5, 9, 10 |
| §8 AC-F4 (per-window) | Tasks 6, 9, 10 |
| §8 AC-F5 (WATCH% ≤ 44.3) | Tasks 5, 9, 10 |
| §8 AC-F6 (v1 unchanged) | Tasks 3, 9, 10 |

---

## Notes for the implementer

1. **Test fixtures**: This plan references several pytest fixtures (`seeded_db_empty_cards`, `seeded_db_with_vol_index`, `seeded_db_with_v2_backfill`, `seeded_db_with_v1_walk_forward_and_v2_evidence`, `seeded_db_full_history`, `seeded_db_with_only_v1`, `seeded_db_with_v1_and_v2_backfill`). The form-sweep PR #88 has precedents for some of these in `tests/integration/regime/conftest.py` — extend them. For tests that need a full historical window with realistic vol_index_daily data (AC-F3), it may be more pragmatic to invoke against the dev DB inside the test, OR mark `pytest.skip` with an explicit message and rely on Task 12 Step 5's manual smoke for evidence.

2. **Subprocess vs in-process testing**: Several integration tests use `subprocess.run(...)` to invoke `canary_backfill.py` / `backtest_canary.py`. This is robust but slow. An equivalent in-process invocation (`from scripts import backtest_canary; backtest_canary.main_with_args(...)`) is faster but requires refactoring the script to expose a main_with_args entry. Implementer's call — pick one and apply consistently.

3. **`_aucs_for_rows` reuse**: Task 10's dispatcher calls `_aucs_for_rows` (existing in `scripts/backtest_canary.py`) on rows it queries from `canary_snapshots`. Verify the row-dict shape `{"date", "score", "band", "tactical", "structural", "speed", "warning_state"}` matches what `_aucs_for_rows` expects. If not, either adapt the SQL projection OR add a tiny adapter — both fine.

4. **AC-F3 fixture vs smoke**: Real CCA events require historical vol_complex data. If `seeded_db_full_history` is impractical to build (it would need 15+ years of synthetic vol_complex history with the right peaks), skip the integration AC-F3 test and rely on Task 12 Step 5's manual smoke. This is a documented practical compromise — the AC is still gated, just via live evidence rather than test-DB evidence.

5. **Idempotency check granularity**: The application-layer pre-insert check (`SELECT 1 FROM canary_snapshots WHERE data_date=%s AND composite_version=%s`) adds one round-trip per day. For ~3,843 days that's ~30 seconds extra. Acceptable for a research-only one-time backfill. If profile shows this is a hot path, batch-check via `WHERE data_date = ANY(%s)`. Out of scope for PR 1.

6. **Mutual exclusion of CLI flags**: Both `canary_backfill.py` and `backtest_canary.py` should reject incompatible combinations early (before any DB writes). E.g., `--v1-v2-compare --walk-forward` should `parser.error()`. The form-sweep PR #88 already established this pattern.

7. **Standing-rule compliance**: Use `uv run python` exclusively. Persist to Postgres. Don't extend `repository.py` — `regime_backtest_repository.py` is the focused file. Never `Co-Authored-By: Claude …` trailer. Don't push or open PR until the user explicitly asks.

8. **What this PR explicitly does NOT do** (worth restating to avoid scope creep):
   - No production flip — `COMPOSITE_VERSION = 1` stays.
   - No UI changes — `web/` is untouched.
   - No OpenAPI regen — no API schema change.
   - No methodology doc rewrite.
   - No band threshold change.
   - No new `LAST_KNOWN_AUC_v2_*` constants — those are PR 2's territory.
   - The verdict from `--v1-v2-compare` is a *report*; this PR does NOT itself flip anything.
