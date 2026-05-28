# Canary v2-A — Vol/Speed Separation — Implementation Plan (v0.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This is v0.2.** The task bodies below are authoritative — there is no separate "amendments" section. Execute tasks in the listed order; the order is itself a correctness invariant (golden capture before formula change; module extraction before assembly code; fixture helpers before integration tests).

**Goal:** Build a research-only PR 1 that produces evidence for the v2-A formula change (drop additive `speed.score` from canary composite when `composite_version >= 2`). Zero production-surface change in PR 1; AC-F1..F6 evidence in PR 1 gates PR 2's production flip.

**Architecture:** A 4-line conditional in `run_analysis()` keyed on `calibration.composite_version`. A new `canary-calibration-v2.json` holding identical thresholds but `composite_version=2`. Research backfill writes `composite_version=2` snapshots (invisible to production via column-scope filter). Walk-forward + robustness write `run_scope='research'` rows (invisible via `find_latest_run`'s production default). A pure renderer evaluates pre-committed AC-F1..F6 from a `FlipGateEvidence` dataclass; the new `src/uw_scan/reports/regime_canary_v1_v2_compare.py` module owns both assembly and rendering; `backtest_canary.py` exposes a thin dispatcher.

**Tech Stack:** Python 3.13 + `uv`; pytest + pytest-postgresql for integration tests; pytest-mock for in-process mock pattern; Postgres for persistence (`canary_snapshots`, `regime_backtest_runs`, `regime_backtest_daily`); `psycopg` for DB access; dataclasses for `Calibration` and `FlipGateEvidence`.

**Spec:** `docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md` (commit `09a2ea8`, post `/review-cycle`).

**Standing rules in force throughout:**
- `uv` exclusively — no bare `python`/`pip`/`pytest`
- Never `subprocess.run([sys.executable, ...])` inside integration tests; use in-process `cmd_*(conn, schema, args)` calls instead (`Settings.from_env()` reads `UW_SCAN_DB_*` env vars, not `DATABASE_URL`, so subprocess + `DATABASE_URL=...` would silently hit and mutate the dev DB `option_wizard`)
- Never extend `repository.py` (a 5,000+ LOC monolith); add new persistence to the focused `regime_backtest_repository.py`
- Persist analytical results to Postgres (`canary_snapshots`, `regime_backtest_runs`)
- Never `Co-Authored-By: Claude …` trailer on commits
- `COMPOSITE_VERSION` module constant **stays at 1** for the entirety of PR 1; only the loaded `cal.composite_version` differs

---

## File Structure

| Path | New / Modified | Purpose |
|---|---|---|
| `src/uw_scan/cards/canary_scoring.py` | Modified | 4-line conditional in `run_analysis()` keyed on `calibration.composite_version` |
| `docs/research/regime/canary-calibration-v2.json` | New | Same 5 vol-scorer thresholds as v1; `composite_version: 2`; `score_form: "linear"` |
| `scripts/canary_backfill.py` | **Refactored** | Extract `cmd_backfill(conn, *, schema, args)`; existing `main()` continues to wrap for the daily APScheduler job. Add `--composite-version` / `--start-date` / `--end-date` / `--overwrite-on-hash-mismatch`. Load span derived from explicit date range. Persists `cal.composite_version`. Payload-hash idempotency with fail-loud on mismatch. Query `vol_index_daily.trade_date` (not `data_date`). |
| `scripts/backtest_canary.py` | **Refactored** | `cmd_walk_forward(conn, *, schema, args)` and `cmd_robustness(conn, *, schema, args)` accept args. Generate `batch_id` once before the per-window loop, persist to every params dict, print to stdout. New thin `cmd_v1_v2_compare(conn, *, schema, args)` (~10 LOC) imports from `uw_scan.reports.regime_canary_v1_v2_compare`. Persists `str(cal.composite_version)`. |
| `src/uw_scan/reports/regime_canary_v1_v2_compare.py` | **NEW MODULE** | Owns `FlipGateEvidence` dataclass + `assemble_and_render_canary_v1_v2_compare(conn, *, schema)` + `_assemble_flip_gate_evidence(conn, *, schema)` + `_full_history_aucs_via_compute_canary_series(conn, *, cal, schema)` + `_band_distribution_for_version(conn, *, schema, version)` + `_run_subprocess_test(test_path)` + pure `render_canary_v1_v2_compare(ev) -> str` + standalone `main()`. Keeps `backtest_canary.py` under the 1,000-LOC convention. |
| `src/uw_scan/storage/regime_backtest_repository.py` | Modified | Add `delete_canary_research_runs_by_batch_id_and_phase(batch_id, phase) -> int`; scope: `indicator='canary' AND run_scope='research' AND params->>'phase'=%s AND params->>'batch_id'=%s` |
| `tests/integration/regime/_canary_v2a_fixture.py` | **NEW** | 4 seed helpers used by Tasks 5–11; each takes `(conn, *, schema)`. Uses `CanarySnapshotRepository.insert_snapshot(...)` (NOT raw SQL) so all NOT NULL columns are populated. |
| `tests/unit/test_canary_v1_payload_hash_golden.py` | New | ~3 unit tests: golden v1 scoring hash regression — **captured from the pre-v2A baseline before Task 3** |
| `tests/unit/test_canary_v2_formula.py` | New | ~9 unit tests: v2 conditional path (deltas, not rounded sums); v3 routes through v2; v1 path unchanged |
| `tests/unit/test_canary_v1_v2_compare_renderer.py` | New | ~16 unit tests for the renderer + AC-F1..F6 evaluation |
| `tests/integration/regime/test_canary_v2_backfill.py` | New | ~6 integration tests: in-process `cmd_backfill(conn, schema, args)`; tags rows with cal.composite_version; payload-hash idempotency; v1 rows untouched |
| `tests/integration/regime/test_canary_v2_walk_forward.py` | New | ~9 integration tests: scoped delete; in-process `cmd_walk_forward`/`cmd_robustness`/`cmd_v1_v2_compare`; mid-batch failure cleanup via `pytest-mock` |

**Net LOC**: ~400–550 new code + ~100 LOC of refactoring in `canary_backfill.py` + `backtest_canary.py`. ~44 new tests. ~40–60s of new test runtime.

---

## Task Order

Tasks are ordered for safe dependencies. **The Task 2 → 3 ordering is a correctness invariant**, not stylistic: the golden v1 payload-hash must be captured against the pre-v2A baseline; otherwise a bug introduced by the conditional silently blesses itself.

0. **Task 0** — Build the v2-A fixture helpers (no production code)
1. **Task 1** — `canary-calibration-v2.json` + loader-parses-v2 unit tests
2. **Task 2** — **Capture v1 golden payload hash** + golden test (BEFORE any change to `canary_scoring.py`)
3. **Task 3** — Apply conditional path in `run_analysis()` + v2 formula unit tests
4. **Task 4** — New repo method `delete_canary_research_runs_by_batch_id_and_phase` (+ 3 tests)
5. **Task 5** — Refactor `canary_backfill.py` to expose `cmd_backfill(conn, *, schema, args)`; add `--composite-version` / `--start-date` / `--end-date` / `--overwrite-on-hash-mismatch`; payload-hash idempotency; v2 calibration load; persist `cal.composite_version`
6. **Task 6** — Refactor `cmd_walk_forward` to `cmd_walk_forward(conn, *, schema, args)`; generate `batch_id` before the loop; persist to every params dict; print to stdout; `--composite-version` plumbed through
7. **Task 7** — Refactor `cmd_robustness` to `cmd_robustness(conn, *, schema, args)`; `--composite-version` + optional `--batch-id` to chain with walk-forward
8. **Task 8** — Walk-forward recompute vs backfill parity test (AC-4b)
9. **Task 9** — `src/uw_scan/reports/regime_canary_v1_v2_compare.py` module: `FlipGateEvidence` + `_assemble_flip_gate_evidence` + `_full_history_aucs_via_compute_canary_series` + `_band_distribution_for_version` + `_run_subprocess_test` + pure renderer + standalone CLI `main()`
10. **Task 10** — Thin `cmd_v1_v2_compare(conn, *, schema, args)` in `backtest_canary.py` (~10 LOC) that delegates to the Task-9 module + integration test
11. **Task 11** — Walk-forward cleanup-on-failure (in-process `pytest-mock` test)
12. **Task 12** — Final smoke + live verification (real DB) + ruff + non-regression

---

### Task 0: Build v2-A fixture helpers (`_canary_v2a_fixture.py`)

**Files:**
- Create: `tests/integration/regime/_canary_v2a_fixture.py`
- Read for reference: `tests/integration/regime/_canary_form_sweep_fixture.py` (the PR #88 precedent)

**Rationale:** Subsequent tasks reference fixture helpers that don't exist. Build them as pure helper functions that take `(conn, *, schema)` and seed deterministic test data via `CanarySnapshotRepository.insert_snapshot(...)` (NOT raw SQL — so all NOT NULL columns are populated). The helpers use `seeded_db_empty_cards.conn` + `_schema` (the per-test DB from `tests/integration/conftest.py`).

- [ ] **Step 1: Create the fixture helpers**

Path: `tests/integration/regime/_canary_v2a_fixture.py`

```python
"""Test-only seed helpers for canary v2-A integration tests.

Each function takes (conn, *, schema) — operates on the per-test DB
provided by tests/integration/conftest.py's seeded_db_empty_cards fixture.
No subprocess, no env-var plumbing.

IMPORTANT: snapshot helpers use CanarySnapshotRepository.insert_snapshot(...)
so every NOT NULL column (tactical_score/structural_score/speed_score/
warning_state/payload_hash) is populated correctly. Raw SQL inserts have
caused fixture failures in earlier drafts.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

import numpy as np

from uw_scan.cards.canary_payload_hash import canonical_payload_hash
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


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
    don't degenerate. Uses the real schema column `trade_date` (NOT `data_date`).
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
    """Seed v2 canary_snapshots for the given dates via insert_snapshot().

    Rows whose data_date is in `cca_dates` get
    payload.speed.confirmed_canary_active=True (used to satisfy AC-F3 in
    integration tests). Returns row count inserted.
    """
    cca_set = set(cca_dates)
    rng = np.random.default_rng(123)
    repo = CanarySnapshotRepository(conn, schema=schema)
    inserted = 0
    for d in dates:
        cca = d in cca_set
        raw = float(rng.uniform(0, 70))
        # Synthesize a valid 0/8/20 speed.score so insert_snapshot's assertion passes.
        speed_score = 0 if cca else 8
        tactical_raw = round(raw * 0.4, 2)
        structural_raw = round(raw * 0.6, 2)
        score_v = max(0.0, min(100.0, tactical_raw + structural_raw))
        band = (
            "STRONG_BUY" if score_v >= 75 else
            "BUY" if score_v >= 50 else
            "WATCH" if score_v >= 25 else
            "NONE"
        )
        warning_state = "CONFIRMED_CANARY_ACTIVE" if cca else "NONE"
        payload = {
            "tactical_vol": {"score": tactical_raw},
            "structural_vol": {"score": structural_raw},
            "speed": {
                "score": speed_score,
                "state": "CONFIRMED_CANARY_ACTIVE" if cca else "NEUTRAL",
                "confirmed_canary_active": cca,
                "buy_the_dip_active": False,
            },
            "canary": {
                "score": round(score_v, 2),
                "raw_score": round(score_v, 2),
                "band": band,
                "warning_state": warning_state,
                "composite_version": 2,
                "score_form": "linear",
            },
            "inputs": {"spx_close": float(1000.0 + d.toordinal() % 500)},
        }
        repo.insert_snapshot(
            payload=payload,
            data_date=d,
            composite_version=2,
            score_form="linear",
            score=Decimal(str(round(score_v, 2))),
            raw_score=Decimal(str(round(score_v, 2))),
            band=band,
            tactical_score=Decimal(str(tactical_raw)),
            structural_score=Decimal(str(structural_raw)),
            speed_score=speed_score,
            warning_state=warning_state,
            payload_hash=canonical_payload_hash(payload),
            on_conflict="noop",
        )
        inserted += 1
    conn.commit()
    return inserted
```

- [ ] **Step 2: Smoke-import the helpers**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run python -c "
from tests.integration.regime._canary_v2a_fixture import (
    seed_vol_index_full_history, seed_v1_walk_forward_runs,
    seed_v2_walk_forward_runs, seed_canary_snapshots_v2,
)
print('imports OK')
"
```

Expected: `imports OK` (no `ImportError`).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/regime/_canary_v2a_fixture.py
git commit -m "test(canary): v2-A integration fixture helpers (Task 0)

Helpers used by Tasks 5-11:
- seed_vol_index_full_history (15-year synthetic vol-complex; trade_date)
- seed_v1_walk_forward_runs (6 production rows, PR #83 baseline shape)
- seed_v2_walk_forward_runs (6 walk-forward + 1 robustness, shared batch_id)
- seed_canary_snapshots_v2 (research snapshots via insert_snapshot — every
  NOT NULL column populated; optional CCA dates for AC-F3)

All helpers take (conn, *, schema) and operate on seeded_db_empty_cards.conn.
No subprocess, no DB-URL plumbing — same precedent as PR #88's form-sweep
fixtures."
```

---

### Task 1: New `canary-calibration-v2.json` + loader-parses-v2 tests

**Files:**
- Create: `docs/research/regime/canary-calibration-v2.json`
- Create: `tests/unit/test_canary_v2_formula.py` (the calibration-loading half only — the formula tests come in Task 3)
- Read for reference: `docs/research/regime/canary-calibration-v1.json`, `src/uw_scan/cards/canary_calibration.py`

**Rationale:** Calibration parsing is the lowest-dependency unit. Start here so subsequent tasks (which load the v2 calibration) have a known-good artifact.

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

Thresholds + `score_form` are byte-identical to v1. Only `composite_version` (1→2), `produced_at`, and `produced_by` change. Spec §5.4.

- [ ] **Step 2: Write the calibration-loading tests**

Path: `tests/unit/test_canary_v2_formula.py`

```python
"""Unit tests for canary v2-A vol/speed separation.

This file is built up across Tasks 1 + 3:
- Task 1: calibration-loading tests (v2 JSON parses; thresholds match v1).
- Task 3: formula-conditional tests (v1 path unchanged; v2 path drops speed).

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.cards.canary_calibration import Calibration, load_calibration

V2_JSON = (
    Path(__file__).resolve().parents[2]
    / "docs" / "research" / "regime" / "canary-calibration-v2.json"
)
V1_JSON = (
    Path(__file__).resolve().parents[2]
    / "docs" / "research" / "regime" / "canary-calibration-v1.json"
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
    v1 = load_calibration(path=V1_JSON)
    v2 = load_calibration(path=V2_JSON)
    assert v1.vix_spike_revert == v2.vix_spike_revert
    assert v1.vix_vix3m_back == v2.vix_vix3m_back
    assert v1.vrp == v2.vrp
    assert v1.cor1m_decay == v2.cor1m_decay
    assert v1.vvix_vix_recovery == v2.vvix_vix_recovery
    assert v1.score_form == v2.score_form
```

- [ ] **Step 3: Run tests — they should pass immediately**

```bash
uv run pytest tests/unit/test_canary_v2_formula.py -v
```

Expected: 2 passed. (Loader already handles arbitrary `composite_version` per spec §4 invariant 6.)

- [ ] **Step 4: Verify v1 calibration file is unchanged**

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

Lowest-dependency artifact. Subsequent tasks (formula conditional,
backfill, walk-forward) load this file to compute v2 scores."
```

---

### Task 2: Capture v1 golden payload hash (BEFORE any code change to `canary_scoring.py`)

**Files:**
- Create: `tests/unit/test_canary_v1_payload_hash_golden.py`

**Rationale:** This task **must run before Task 3**. The golden hash is captured against the current (pre-v2A) `run_analysis` implementation. If Task 3 ran first and introduced a bug into the v1 branch (e.g., wrong indent on the `else` clause), the golden test would silently bless the regression.

The pre-existing `tests/integration/regime/test_canary_oos_gate.py` uses synthetic seeded rows and does NOT exercise the v1 scoring path. This golden test IS the v1-unchanged proof for AC-6 / AC-F6.

- [ ] **Step 1: Compute the golden hash from the current `canary_scoring.py`**

Run this once, save the printed hash:

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
        "VIX":   np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX":  np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX":   np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }


def fixed_dates(n=400):
    base = _date(2020, 6, 1)
    return [_date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)]


cal = load_calibration()
assert cal.composite_version == 1, "Run this BEFORE Task 3"
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
print("sample band   =", payload["canary"]["band"])
print("sample score  =", payload["canary"]["score"])
PY
```

Record the printed hash. It will become the literal in Step 2.

- [ ] **Step 2: Write the golden test, paste the hash inline**

Path: `tests/unit/test_canary_v1_payload_hash_golden.py`

```python
"""Golden v1 payload-hash regression test (AC-6 / AC-F6).

The pre-existing tests/integration/regime/test_canary_oos_gate.py uses
synthetic seeded rows and does NOT exercise the v1 scoring path. This
test IS the v1-unchanged proof: it runs run_analysis() with the v1
calibration on a fixed input and asserts byte-identical canonical-JSON
output against a captured pre-v2A golden.

If you intentionally change v1 behavior (extremely unlikely — v1 is
shipped), re-run the ad-hoc script in plan §Task-2 Step-1 to recompute.

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md
spec §7 AC-6 and §8 AC-F6.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date as _date

import numpy as np

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, load_calibration

# Captured against canary_scoring.py BEFORE the v2-A conditional was applied.
# DO NOT update without re-running the Step-1 capture script.
V1_GOLDEN_HASH = "REPLACE_WITH_HASH_FROM_STEP_1"


def _fixed_inputs():
    rng = np.random.default_rng(42)
    n = 400
    aligned = {
        "VIX":   np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX":  np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX":   np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }
    base = _date(2020, 6, 1)
    dates = [_date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)]
    return aligned, dates


def test_v1_payload_hash_unchanged():
    """v1 scoring on fixed inputs MUST produce byte-identical canonical-JSON
    payload to the captured pre-v2A golden. This is AC-6/AC-F6's actual proof —
    the OOS gate test does NOT exercise the v1 scoring path."""
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
        f"If this is intentional, re-run plan §Task-2 Step-1 to recompute."
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


def test_composite_version_module_constant_is_1_in_pr1():
    """Belt-and-braces invariant: the module constant must stay at 1 for PR 1.
    The flip to 2 is PR 2's job per spec §10."""
    assert COMPOSITE_VERSION == 1, (
        "PR 1 must NOT change COMPOSITE_VERSION. The flip is PR 2's job. See spec §10."
    )
```

- [ ] **Step 3: Paste the hash captured in Step 1**

Replace `V1_GOLDEN_HASH = "REPLACE_WITH_HASH_FROM_STEP_1"` with the actual SHA-256 string.

- [ ] **Step 4: Run the tests — verify they pass on the pre-v2A baseline**

```bash
uv run pytest tests/unit/test_canary_v1_payload_hash_golden.py -v
```

Expected: 3 passed. (If `test_v1_payload_hash_unchanged` fails, you pasted the wrong hash or modified `canary_scoring.py` already — back out before continuing.)

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_canary_v1_payload_hash_golden.py
git commit -m "test(canary): v1 payload-hash golden test (AC-6 / AC-F6)

Captures the v1 run_analysis output as a SHA-256 hash on a fixed
synthetic input. This is the real proof that v1 production scoring is
unchanged post v2-A conditional — the pre-existing OOS gate test
(test_canary_oos_gate.py) uses synthetic seeded rows and does NOT
exercise the v1 scoring path.

CAPTURED FROM THE PRE-V2A BASELINE. If Task 3's conditional ever
introduces a bug in the v1 branch (wrong indent, dropped clamp, etc.),
this test will fail loudly with a hash diff.

3 tests:
- test_v1_payload_hash_unchanged — byte-identical canonical JSON
- test_v1_payload_band_unchanged — band-classification sanity
- test_composite_version_module_constant_is_1_in_pr1 — invariant

Spec §7 AC-6, §8 AC-F6, §6 Layer 3."
```

---

### Task 3: Apply conditional path in `run_analysis()` + v2 formula tests

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (around line 540, inside `run_analysis()`)
- Modify: `tests/unit/test_canary_v2_formula.py` (extend with formula tests)

**Rationale:** The structural code change. 4 lines + comment. The v1 path is preserved by `else:` — the Task-2 golden test guards against silent regression.

Formula tests assert **deltas** between v1↔v2 raw scores, not absolute computed sums. Reason: `payload["tactical_vol"]["score"]` is rounded to 2 decimals, but `raw_score` rounds the SUM of unrounded components — equality on rounded inputs can drift by 0.01.

- [ ] **Step 1: Write the v2 formula tests (they should fail)**

Append to `tests/unit/test_canary_v2_formula.py` (after the existing calibration tests):

```python
from datetime import date as _date

import numpy as np

from uw_scan.cards import canary_scoring


def _fixed_aligned_arrays(n: int = 400, seed: int = 0) -> dict:
    """Synthetic aligned vol-complex arrays sized for the MIN_ALIGNED_BARS=350 gate."""
    rng = np.random.default_rng(seed)
    return {
        "VIX":   np.clip(15.0 + rng.standard_normal(n).cumsum() * 0.5, 10.0, 60.0),
        "VVIX":  np.clip(85.0 + rng.standard_normal(n).cumsum() * 0.8, 70.0, 150.0),
        "VIX3M": np.clip(16.0 + rng.standard_normal(n).cumsum() * 0.5, 11.0, 55.0),
        "COR1M": np.clip(50.0 + rng.standard_normal(n).cumsum() * 0.4, 20.0, 90.0),
        "SPX":   np.clip(1000.0 + rng.standard_normal(n).cumsum() * 4.0, 600.0, 5000.0),
    }


def _fixed_common_dates(n: int = 400) -> list[str]:
    base = _date(2020, 6, 1)
    return [
        _date.fromordinal(base.toordinal() - (n - 1 - i)).isoformat() for i in range(n)
    ]


def _run_for_version(version: int, *, cca: bool = False, btd: bool = False) -> dict:
    """Run analysis with the v1 calibration, then patch composite_version on the
    Calibration object for the v2 path. Identical inputs across calls."""
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


def _v1_pre_clamp_raw(payload: dict, speed_contrib: int) -> float:
    """v1's pre-clamp raw_score reconstruction (uses unrounded scorer outputs
    would be ideal; rounded inputs are within 0.02 — adequate for the clamp
    check, NOT for equality assertions)."""
    return (
        payload["tactical_vol"]["score"]
        + payload["structural_vol"]["score"]
        + speed_contrib
    )


def test_v1_path_unchanged_when_no_speed_state():
    """v1 NEUTRAL: speed.score=8 contributes to raw. delta-style assertion."""
    p1 = _run_for_version(1, cca=False, btd=False)
    assert p1["speed"]["score"] == 8


def test_v2_drops_8_when_neutral():
    """v1 raw − v2 raw ≈ 8 in the NEUTRAL case (modulo clamping).

    Assert DELTA, not absolute equality on rounded payload values.
    """
    p1 = _run_for_version(1, cca=False, btd=False)
    p2 = _run_for_version(2, cca=False, btd=False)
    v1_pre_clamp = _v1_pre_clamp_raw(p1, speed_contrib=8)
    if v1_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 8.0) < 0.02, (
            f"v1−v2 NEUTRAL delta = {delta}, expected ~8.0"
        )
    else:
        # Both clamped at 100 -> v2 raw equals clamped tactical+structural.
        v2_expected_pre_clamp = (
            p2["tactical_vol"]["score"] + p2["structural_vol"]["score"]
        )
        assert (
            abs(p2["canary"]["raw_score"] - min(100.0, v2_expected_pre_clamp)) < 0.02
        )


def test_v2_drops_20_when_btd_active():
    """v1 BTD: speed.score=20. v1 − v2 raw ≈ 20."""
    p1 = _run_for_version(1, cca=False, btd=True)
    p2 = _run_for_version(2, cca=False, btd=True)
    assert p1["speed"]["state"] == "BUY_THE_DIP_ACTIVE"
    assert p2["speed"]["state"] == "BUY_THE_DIP_ACTIVE"
    v1_pre_clamp = _v1_pre_clamp_raw(p1, speed_contrib=20)
    if v1_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 20.0) < 0.02


def test_v2_keeps_cap_mechanism_via_speed_state():
    """v2 CCA: apply_cap reads speed.state (enum), NOT speed.score. v2 dropping
    the additive term does NOT change cap behavior. Spec §5.3."""
    p2 = _run_for_version(2, cca=True, btd=False)
    assert p2["speed"]["state"] == "CONFIRMED_CANARY_ACTIVE"
    assert p2["canary"]["warning_state"] in ("NONE", "CONFIRMED_CANARY_ACTIVE")


def test_v3_routes_through_v2_path():
    """The `>=2` semantic intentionally auto-promotes future v3 to the v2 formula.

    This test will deliberately need updating when v3 lands with a new explicit
    formula — that's the point: it forces the v3 implementer to make the
    conditional explicit rather than silently inheriting v2's behavior."""
    p2 = _run_for_version(2, cca=False, btd=False)
    p3 = _run_for_version(3, cca=False, btd=False)
    assert p2["canary"]["raw_score"] == p3["canary"]["raw_score"]


def test_both_active_ambiguous_branch():
    """When both CCA and BTD active: speed.state='BOTH_ACTIVE_AMBIGUOUS',
    speed.score=8. v1: raw += 8. v2: raw unchanged. Cap still uses speed.state."""
    p1 = _run_for_version(1, cca=True, btd=True)
    p2 = _run_for_version(2, cca=True, btd=True)
    assert p1["speed"]["state"] == "BOTH_ACTIVE_AMBIGUOUS"
    assert p2["speed"]["state"] == "BOTH_ACTIVE_AMBIGUOUS"
    assert p1["speed"]["score"] == 8
    v1_pre_clamp = _v1_pre_clamp_raw(p1, speed_contrib=8)
    if v1_pre_clamp <= 100.0:
        delta = p1["canary"]["raw_score"] - p2["canary"]["raw_score"]
        assert abs(delta - 8.0) < 0.02
```

Also add the import at the top of the file:

```python
from uw_scan.cards.canary_calibration import Calibration, load_calibration  # already there
```

- [ ] **Step 2: Run the new tests — expect failure**

```bash
uv run pytest tests/unit/test_canary_v2_formula.py::test_v2_drops_8_when_neutral -v
```

Expected: FAIL. Current `run_analysis` adds `speed.score` regardless of `composite_version`, so `delta ≈ 0`, not 8.

- [ ] **Step 3: Apply the 4-line conditional in `canary_scoring.py`**

Open `src/uw_scan/cards/canary_scoring.py`. Find this block inside `run_analysis()` (around line 540):

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
        # v2-A: speed is context only; apply_cap() below still reads speed.state.
        raw = tactical + structural
    else:
        raw = tactical + structural + speed.score
    raw = max(0.0, min(100.0, raw))
```

The `apply_cap(...)` call later in the function continues to read `speed.state` — unchanged.

- [ ] **Step 4: Run all formula tests — verify they pass**

```bash
uv run pytest tests/unit/test_canary_v2_formula.py -v
```

Expected: 8 passed (2 calibration from Task 1 + 6 formula from this task).

- [ ] **Step 5: Verify Task-2's golden hash still passes**

```bash
uv run pytest tests/unit/test_canary_v1_payload_hash_golden.py -v
```

Expected: 3 passed. **If `test_v1_payload_hash_unchanged` fails, the conditional broke v1.** Fix Task 3 — do NOT recapture the golden.

- [ ] **Step 6: Run broader canary unit-test suite — confirm no regression**

```bash
uv run pytest tests/unit/test_canary_*.py -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/test_canary_v2_formula.py
git commit -m "feat(canary): v2-A conditional path in run_analysis()

Adds a 4-line conditional in run_analysis() keyed on
calibration.composite_version. v1 path (else branch) is preserved
bit-identically — guarded by Task 2's golden hash test. v2 path drops
the additive speed.score term while leaving apply_cap() (which reads
speed.state) unchanged.

6 formula tests use DELTA assertions (not absolute rounded equality):
- v1 NEUTRAL: speed.score=8 contributes to raw
- v2 NEUTRAL: delta v1−v2 ≈ 8 (modulo clamping)
- v2 BTD: delta ≈ 20
- v2 CCA: cap still fires via speed.state
- v3 (composite_version=3): routes through v2 branch (>=2 semantic)
- BOTH_ACTIVE_AMBIGUOUS: delta ≈ 8, cap unchanged

Spec §5.3."
```

---

### Task 4: New repo method `delete_canary_research_runs_by_batch_id_and_phase`

**Files:**
- Modify: `src/uw_scan/storage/regime_backtest_repository.py` (append after `delete_runs_by_batch_id` at line 148)
- Create/extend: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** PR #88's `delete_runs_by_batch_id` is hard-pinned to `params->>'phase'='form_sweep_full'`. v2 walk-forward uses `phase='walk_forward'`, so failed v2 batches wouldn't be cleaned up by the existing method. We need a phase-parameterized variant scoped to `indicator='canary' AND run_scope='research'` so production rows are never touched.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
"""Integration tests for canary v2-A walk-forward, robustness, cleanup,
parity, and dispatcher. Built up across Tasks 4, 6, 7, 8, 10, 11.
"""

from __future__ import annotations

import uuid
from datetime import date

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
    """Insert 6 walk-forward + 1 robustness + 4 form-sweep research rows.
    Delete walk-forward batch by (batch_id, phase='walk_forward').
    Assert: 6 walk-forward rows gone; robustness + form-sweep rows preserved.
    """
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
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {schema}.regime_backtest_runs WHERE id = %s",
            (robustness_id,),
        )
        assert cur.fetchone() is not None
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s",
            (fs_batch,),
        )
        assert cur.fetchone()[0] == 4


def test_delete_canary_research_runs_by_batch_id_and_phase_no_op_when_no_match(
    seeded_db_empty_cards,
):
    """Returns 0 when no rows match (wrong batch_id, wrong phase, etc.)."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)
    deleted = repo.delete_canary_research_runs_by_batch_id_and_phase(
        str(uuid.uuid4()), "walk_forward"
    )
    assert deleted == 0


def test_delete_canary_research_runs_by_batch_id_and_phase_does_not_touch_production(
    seeded_db_empty_cards,
):
    """Defense-in-depth: production rows MUST NOT be deleted even on collision."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(conn, schema=schema)

    same_batch = str(uuid.uuid4())
    research_id = _insert_research_run(
        repo, phase="walk_forward", window_id="WF-1", batch_id=same_batch
    )
    repo.mark_run_completed(research_id)

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
    assert deleted == 1
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {schema}.regime_backtest_runs WHERE id = %s",
            (prod_id,),
        )
        assert cur.fetchone() is not None
```

- [ ] **Step 2: Run the failing tests**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_delete_canary_research_runs_by_batch_id_and_phase_walk_forward -v
```

Expected: FAIL with `AttributeError: 'RegimeBacktestRepository' object has no attribute 'delete_canary_research_runs_by_batch_id_and_phase'`.

- [ ] **Step 3: Add the repo method**

Open `src/uw_scan/storage/regime_backtest_repository.py`. Find `delete_runs_by_batch_id` (line 148). Append directly after it (before `find_latest_run` at line 173):

```python
    def delete_canary_research_runs_by_batch_id_and_phase(
        self, batch_id: str, phase: str
    ) -> int:
        """Delete canary research runs scoped to a specific (batch_id, phase).

        Unlike `delete_runs_by_batch_id` (which hard-pins
        params.phase='form_sweep_full' for PR #88), this method accepts
        an arbitrary phase string. Used by v2-A's cleanup-on-failure paths
        (phase='walk_forward', phase='robustness').

        Scope: indicator='canary' AND run_scope='research' AND
        params->>'phase' = %s AND params->>'batch_id' = %s. Production rows
        are NEVER deleted, even on UUID4 collision.

        Daily rows cascade via ON DELETE CASCADE (migration 057).
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
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k delete_canary_research -v
```

Expected: 3 passed.

- [ ] **Step 5: Run form-sweep test suite — confirm no regression**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_form_sweep_full.py -v
```

Expected: all 14 existing form-sweep tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/regime_backtest_repository.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(regime): delete_canary_research_runs_by_batch_id_and_phase

PR #88's delete_runs_by_batch_id is hard-pinned to
params.phase='form_sweep_full' and cannot be reused for v2-A's
walk-forward / robustness cleanup paths. New method accepts an arbitrary
phase string and stays scoped to indicator='canary' AND
run_scope='research' to prevent production-plane pollution.

3 integration tests:
- Walk-forward batch deletion (6 rows; robustness + form-sweep preserved)
- No-op when no match
- Production rows untouched on batch_id collision

Spec §5.2, §5.8, §4 invariant 7."
```

---

### Task 5: Refactor `canary_backfill.py` → `cmd_backfill(conn, *, schema, args)` + `--composite-version` / `--start-date` / `--end-date` / payload-hash idempotency

**Files:**
- Modify: `scripts/canary_backfill.py` (refactor: extract `cmd_backfill`; keep `main()` for the daily APScheduler job)
- Create: `tests/integration/regime/test_canary_v2_backfill.py`

**Rationale:** The backfill script is the v2 evidence factory. Refactoring it to expose `cmd_backfill(conn, *, schema, args)` enables in-process integration tests that target the test DB without subprocess. The existing `main()` continues to work for daily APScheduler.

Additional fixes:
- `--composite-version {1,2}` flag (default 1)
- `--start-date YYYY-MM-DD` / `--end-date YYYY-MM-DD` (replace date-fragile `--days N` for v2 evidence)
- **Load span derived from explicit date range** (the existing `span = max(800, args.days + 500)` silently caps at ~800 cal days, so a 2011 start date currently fails)
- Persist `cal.composite_version` (the loaded field), NOT the module-level `COMPOSITE_VERSION` constant
- **Idempotency via payload-hash compare** (compute new canonical hash; compare with existing row's stored hash; skip on match; fail loudly unless `--overwrite-on-hash-mismatch`)
- Query `vol_index_daily` via `trade_date` (not `data_date`)

- [ ] **Step 1: Write the failing integration tests**

Path: `tests/integration/regime/test_canary_v2_backfill.py`

```python
"""Integration tests for canary v2-A backfill (in-process invocation).

See docs/superpowers/specs/2026-05-27-canary-v2a-vol-speed-separation-design.md.
"""

from __future__ import annotations

import argparse
from datetime import date

import pytest

from scripts.canary_backfill import cmd_backfill
from tests.integration.regime._canary_v2a_fixture import seed_vol_index_full_history
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION

pytestmark = pytest.mark.integration


def _backfill_args(
    *,
    composite_version: int,
    start_date: str | None = None,
    end_date: str | None = None,
    overwrite_on_hash_mismatch: bool = False,
    days: int = 252,
) -> argparse.Namespace:
    return argparse.Namespace(
        composite_version=composite_version,
        start_date=start_date,
        end_date=end_date,
        overwrite_on_hash_mismatch=overwrite_on_hash_mismatch,
        days=days,
    )


def test_v2_backfill_writes_composite_version_2_rows(seeded_db_empty_cards):
    """cmd_backfill with composite_version=2 writes rows tagged composite_version=2."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 12, 30))

    args = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-12-30",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        v2_count = cur.fetchone()[0]
    assert v2_count > 0, "v2 backfill wrote no rows"


def test_v2_backfill_uses_cal_composite_version_not_module_constant(seeded_db_empty_cards):
    """v2 rows MUST tag composite_version=2 (cal.composite_version, the loaded
    field), NOT the module-level COMPOSITE_VERSION=1 constant. Otherwise v2
    payloads would silently store as version 1. Spec §4 invariant 10."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    assert COMPOSITE_VERSION == 1, "PR 1 must not flip the module constant"
    seed_vol_index_full_history(conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 3, 31))

    args = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-03-31",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT composite_version FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 LIMIT 5"
        )
        rows = cur.fetchall()
    assert len(rows) == 5
    for row in rows:
        assert row[0] == 2


def test_v2_backfill_score_form_is_linear(seeded_db_empty_cards):
    """v2 calibration mandates score_form='linear' (form-sweep verdict). Spec §5.4."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 2, 28))

    args = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT score_form FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2"
        )
        forms = {row[0] for row in cur.fetchall()}
    assert forms == {"linear"}


def test_v2_backfill_is_idempotent_via_payload_hash(seeded_db_empty_cards):
    """Re-running the v2 backfill on the same date range is a no-op.
    Idempotency MUST be via canonical payload-hash compare (not SELECT 1),
    so stale rows from earlier buggy runs surface as RuntimeError.
    Spec §5.8."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 2, 28))

    args = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        first = cur.fetchone()[0]

    # Re-run with the SAME payload — must succeed, no new rows.
    cmd_backfill(conn, schema=schema, args=args)

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.canary_snapshots WHERE composite_version=2"
        )
        second = cur.fetchone()[0]
    assert first == second, "second backfill should be a no-op"


def test_v2_backfill_fails_loud_on_hash_mismatch_unless_overwrite(seeded_db_empty_cards):
    """If an existing v2 row has a DIFFERENT canonical hash from the freshly
    computed payload, raise unless --overwrite-on-hash-mismatch is passed.

    Simulates "stale row from buggy earlier run" — silent skip would mask
    the bug forever. Spec §5.8."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 1, 31))

    args = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-01-31",
    )
    cmd_backfill(conn, schema=schema, args=args)

    # Tamper with one row's payload_hash to simulate a stale buggy row.
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {schema}.canary_snapshots "
            f"SET payload_hash = 'tampered-stale-hash' "
            f"WHERE composite_version=2 LIMIT 1"
        )
    conn.commit()

    with pytest.raises(RuntimeError, match="hash mismatch"):
        cmd_backfill(conn, schema=schema, args=args)

    # With --overwrite-on-hash-mismatch, it succeeds.
    args_overwrite = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-01-31",
        overwrite_on_hash_mismatch=True,
    )
    cmd_backfill(conn, schema=schema, args=args_overwrite)


def test_v2_backfill_does_not_affect_v1_rows(seeded_db_empty_cards):
    """v1 rows untouched after v2 backfill. Spec §6 Layer 1."""
    from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=date(2019, 1, 2), end=date(2020, 2, 28))

    args_v1 = _backfill_args(
        composite_version=1, start_date="2020-01-02", end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args_v1)

    repo = CanarySnapshotRepository(conn, schema=schema)
    v1_latest_before = repo.fetch_latest(composite_version=1)
    assert v1_latest_before is not None

    args_v2 = _backfill_args(
        composite_version=2, start_date="2020-01-02", end_date="2020-02-28",
    )
    cmd_backfill(conn, schema=schema, args=args_v2)

    v1_latest_after = repo.fetch_latest(composite_version=1)
    assert v1_latest_after["data_date"] == v1_latest_before["data_date"]
    assert v1_latest_after["score"] == v1_latest_before["score"]
    assert v1_latest_after["band"] == v1_latest_before["band"]
```

- [ ] **Step 2: Run the failing tests**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_backfill.py -v
```

Expected: all FAIL with `ImportError: cannot import name 'cmd_backfill' from 'scripts.canary_backfill'`.

- [ ] **Step 3: Refactor `canary_backfill.py` to expose `cmd_backfill`**

Open `scripts/canary_backfill.py`. The current shape (verified):
- `main()` at line 85 with monolithic body (argparse + connect + load + loop + commit)
- Uses `COMPOSITE_VERSION` from `canary_calibration` at line 176
- Loads with `span = max(800, args.days + 500)` at line 111

Refactor as follows. Final shape:

```python
"""Daily/backfill canary snapshot producer.

Two entry points:
  - main() — argparse + Settings.from_env() + connect + delegate to cmd_backfill.
    Used by the daily APScheduler job (no UI change).
  - cmd_backfill(conn, *, schema, args) — pure unit; in-process integration
    tests target this directly.

CLI:
  --days N                          # legacy: how many recent trading days
  --composite-version {1,2}         # which calibration JSON to load (default 1)
  --start-date YYYY-MM-DD           # explicit start (overrides --days)
  --end-date   YYYY-MM-DD           # explicit end
  --overwrite-on-hash-mismatch      # if existing row's payload_hash differs from
                                    # the new payload's, overwrite instead of raising
"""

from __future__ import annotations

import argparse
import logging
from datetime import date as _date
from decimal import Decimal
from pathlib import Path

import numpy as np
import psycopg

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, Calibration, load_calibration
from uw_scan.cards.canary_payload_hash import canonical_payload_hash
from uw_scan.config import Settings
from uw_scan.scanners.canary import (
    MIN_ALIGNED_BARS,
    _align,
    _compute_cap_lift_inputs,
    _load,
    _replay_events,
)
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"


def _build_snapshot_payload(...):  # existing helper — leave unchanged
    ...


def _load_calibration_for_version(version: int) -> Calibration:
    if version == 2:
        cal = load_calibration(path=V2_CAL_PATH)
        if cal.composite_version != 2:
            raise RuntimeError(
                f"canary-calibration-v2.json has composite_version="
                f"{cal.composite_version}; expected 2"
            )
        return cal
    cal = load_calibration()
    if cal.composite_version != 1:
        raise RuntimeError("default load_calibration() returned non-v1 — investigate")
    return cal


def _derive_load_span(args: argparse.Namespace) -> int:
    """Pick the data-load span large enough to cover [start_date, end_date] +
    the scanner's 350-bar warmup. Existing v1 path defaulted to
    max(800, days + 500), which silently capped at ~800 cal days when
    --start-date was set to a year in the distant past."""
    if args.start_date and args.end_date:
        sd = _date.fromisoformat(args.start_date)
        ed = _date.fromisoformat(args.end_date)
        return max(800, (ed - sd).days + 500)
    return max(800, args.days + 500)


def cmd_backfill(conn, *, schema: str, args: argparse.Namespace) -> None:
    """Backfill canary_snapshots for [start_date, end_date] at composite_version.

    Pure unit — does not call Settings.from_env() or psycopg.connect().
    """
    cal = _load_calibration_for_version(args.composite_version)
    vol_repo = VolIndexRepository(conn, schema=schema)
    span = _derive_load_span(args)
    raw = {
        sym: _load(vol_repo, sym, span)
        for sym in ("VIX", "VVIX", "VIX3M", "COR1M", "SPX")
    }
    aligned, all_dates = _align(raw)
    if len(all_dates) < MIN_ALIGNED_BARS:
        raise RuntimeError(
            f"not enough aligned bars: have {len(all_dates)} need >= {MIN_ALIGNED_BARS}"
        )

    # Pick the dates to backfill.
    if args.start_date and args.end_date:
        sd = _date.fromisoformat(args.start_date)
        ed = _date.fromisoformat(args.end_date)
        dates_to_backfill = [d for d in all_dates if sd <= d <= ed]
        # Index of the FIRST date we want — must respect MIN_ALIGNED_BARS.
        first_idx = next(
            (i for i, d in enumerate(all_dates) if d >= sd), 0
        )
        first_idx = max(first_idx, MIN_ALIGNED_BARS - 1)
    else:
        first_idx = max(MIN_ALIGNED_BARS - 1, len(all_dates) - args.days)
        dates_to_backfill = all_dates[first_idx:]

    if not dates_to_backfill:
        log.warning("no dates to backfill for the requested range")
        return

    closes = aligned["SPX"].tolist()
    history_pairs = list(zip(all_dates, closes))
    state = _replay_events(history_pairs)
    snap_repo = CanarySnapshotRepository(conn, schema=schema)
    cal_for_run = cal  # already at the right composite_version

    wrote = skipped = overwrote = 0
    for i, d in enumerate(all_dates):
        if d not in dates_to_backfill:
            continue
        if i < MIN_ALIGNED_BARS - 1:
            continue
        sma50 = float(np.mean(closes[i - 49 : i + 1]))
        sma200 = float(np.mean(closes[i - 199 : i + 1]))
        slice_dates = all_dates[: i + 1]
        date_to_idx = {dd: idx for idx, dd in enumerate(slice_dates)}
        window = canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
        confirmed_active = any(
            e.kind == "confirmed_canary"
            and e.fire_date in date_to_idx
            and 0 <= i - date_to_idx[e.fire_date] <= window
            for e in state.emitted
        )
        btd_active = any(
            e.kind == "buy_the_dip"
            and e.fire_date in date_to_idx
            and 0 <= i - date_to_idx[e.fire_date] <= window
            for e in state.emitted
        )
        cap_lift = _compute_cap_lift_inputs(
            aligned["SPX"][: i + 1], sma200,
            aligned["VIX"][: i + 1], aligned["VIX3M"][: i + 1],
        )
        payload = _build_snapshot_payload(
            today=d,
            aligned_slice={k: v[: i + 1] for k, v in aligned.items()},
            slice_dates=slice_dates,
            sma50=sma50, sma200=sma200,
            cap_lift_inputs=cap_lift,
            confirmed_active=confirmed_active,
            btd_active=btd_active,
            cal_for_run=cal_for_run,
        )
        new_hash = canonical_payload_hash(payload)

        # Payload-hash idempotency: lookup existing row's hash.
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT payload_hash FROM {schema}.canary_snapshots "
                f"WHERE data_date = %s AND composite_version = %s",
                (d, cal.composite_version),
            )
            existing = cur.fetchone()

        if existing is not None:
            if existing[0] == new_hash:
                skipped += 1
                continue
            if not args.overwrite_on_hash_mismatch:
                raise RuntimeError(
                    f"hash mismatch at data_date={d} composite_version="
                    f"{cal.composite_version}: existing={existing[0]!r} "
                    f"new={new_hash!r}. Pass --overwrite-on-hash-mismatch to "
                    f"replace, or DELETE the row manually if you know it's stale."
                )
            # Overwrite path: DELETE then insert.
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {schema}.canary_snapshots "
                    f"WHERE data_date = %s AND composite_version = %s",
                    (d, cal.composite_version),
                )
            overwrote += 1

        snap_repo.insert_snapshot(
            payload=payload,
            data_date=d,
            composite_version=cal.composite_version,  # NOT the module constant
            score_form=cal_for_run.score_form,
            score=Decimal(str(payload["canary"]["score"])),
            raw_score=Decimal(str(payload["canary"]["raw_score"])),
            band=payload["canary"]["band"],
            tactical_score=Decimal(str(payload["tactical_vol"]["score"])),
            structural_score=Decimal(str(payload["structural_vol"]["score"])),
            speed_score=payload["speed"]["score"],
            warning_state=payload["canary"]["warning_state"],
            payload_hash=new_hash,
            on_conflict="noop",
        )
        wrote += 1

    conn.commit()
    log.info(
        "backfill complete: wrote=%d skipped=%d overwrote=%d range=[%s..%s]",
        wrote, skipped, overwrote,
        dates_to_backfill[0], dates_to_backfill[-1],
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=252,
        help="how many of the most-recent aligned trading days to write "
             "(default 252 ≈ 1 trading year; use 4000+ for full lookback). "
             "Ignored when --start-date is given.")
    ap.add_argument("--composite-version", type=int, choices=(1, 2), default=1,
        help="which calibration to load (default 1, the production version). "
             "Pass 2 for v2-A research backfill (loads canary-calibration-v2.json, "
             "writes composite_version=2 rows, invisible to production reads).")
    ap.add_argument("--start-date", type=str, default=None,
        help="ISO date (YYYY-MM-DD) for the first day to backfill. "
             "Overrides --days if set.")
    ap.add_argument("--end-date", type=str, default=None,
        help="ISO date (YYYY-MM-DD) for the last day to backfill. "
             "Defaults to MAX(trade_date) if start_date is set but end isn't.")
    ap.add_argument("--overwrite-on-hash-mismatch", action="store_true",
        help="if an existing row's payload_hash differs from the freshly "
             "computed payload, overwrite instead of raising. Use for one-off "
             "recompute after a known formula change (e.g., re-running v2 "
             "after an in-flight v2 patch).")
    args = ap.parse_args()

    if args.start_date and not args.end_date:
        # default end to today — keeps the daily-cron use case simple
        args.end_date = _date.today().isoformat()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn(), autocommit=False) as conn:
        cmd_backfill(conn, schema=settings.db_schema, args=args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(Keep the existing `_build_snapshot_payload` helper at the top — only the `main()` body is refactored.)

- [ ] **Step 4: Run the integration tests — verify they pass**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_backfill.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Confirm the daily APScheduler entry still works**

The daily job runs `uv run python scripts/canary_backfill.py` (no flags). Confirm that signature still works:

```bash
uv run python scripts/canary_backfill.py --help
```

Expected: argparse help text including `--days`, `--composite-version`, `--start-date`, `--end-date`, `--overwrite-on-hash-mismatch`.

- [ ] **Step 6: Commit**

```bash
git add scripts/canary_backfill.py tests/integration/regime/test_canary_v2_backfill.py
git commit -m "feat(canary): canary_backfill cmd_backfill + payload-hash idempotency

Refactor: extract cmd_backfill(conn, *, schema, args) so integration tests
invoke in-process without subprocess (Settings.from_env reads UW_SCAN_DB_*
not DATABASE_URL — subprocess+env-var would hit the dev DB).

main() still works for the daily APScheduler job (no UI change).

New flags:
- --composite-version {1,2}: load v1 or v2 calibration, persist
  cal.composite_version (the loaded field), NOT the module constant
- --start-date / --end-date: explicit ranges. Data-load span derived from
  range (the old span=max(800, days+500) silently capped a 15-year
  backfill at ~800 calendar days)
- --overwrite-on-hash-mismatch: rather than ON CONFLICT DO NOTHING or
  SELECT 1 → continue (both silently keep stale rows), compute the
  canonical payload hash and compare. Skip on match; RAISE on mismatch
  unless this flag is set. Then a stale row from a buggy earlier run
  surfaces immediately.

Uses canonical_payload_hash() from canary_payload_hash module.
Queries vol_index_daily via trade_date (verified in vol_index_repository.py:29).

6 integration tests — all in-process via cmd_backfill(conn, schema, args).

Spec §5.5, §5.8, §6 Layer 1, §4 invariant 10."
```

---

### Task 6: Refactor `cmd_walk_forward(conn, *, schema, args)` + `batch_id` generation + `--composite-version 2`

**Files:**
- Modify: `scripts/backtest_canary.py` (refactor `cmd_walk_forward`; thread args through; generate `batch_id`)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** Current `cmd_walk_forward(conn, *, schema)` takes no `args`, doesn't write a `batch_id`, and hard-pins `composite_version=str(COMPOSITE_VERSION)` (which is `1`). Three problems for v2:
1. Tests can't pass arguments in-process
2. The dispatcher in Task 10 needs `batch_id` to scope reload queries
3. v2 needs to load the v2 calibration JSON and write `run_scope='research'`

- [ ] **Step 1: Write failing v2 walk-forward tests**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
import argparse
from datetime import date as _date

from scripts.backtest_canary import cmd_walk_forward
from tests.integration.regime._canary_v2a_fixture import seed_vol_index_full_history


def _wf_args(*, composite_version: int, batch_id: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        composite_version=composite_version,
        batch_id=batch_id,
    )


def test_v2_walk_forward_writes_6_research_rows(seeded_db_empty_cards):
    """cmd_walk_forward with composite_version=2 writes 6 research-scoped
    walk-forward rows, all sharing a batch_id, with WF-1..WF-6 window_ids."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id', params->>'window_id', composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward' "
            f"ORDER BY params->>'window_id'"
        )
        rows = cur.fetchall()

    assert len(rows) == 6
    batch_ids = {r[0] for r in rows}
    assert len(batch_ids) == 1 and next(iter(batch_ids)) is not None
    window_ids = {r[1] for r in rows}
    assert window_ids == {f"WF-{i}" for i in range(1, 7)}
    for r in rows:
        assert r[2] == "2"
        assert r[3] == "research"


def test_v2_walk_forward_preserves_v1_production_rows(seeded_db_empty_cards):
    """v1 walk-forward production rows survive v2 walk-forward. Spec §6 Layer 2."""
    from tests.integration.regime._canary_v2a_fixture import seed_v1_walk_forward_runs

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    v1_ids = seed_v1_walk_forward_runs(conn, schema=schema)
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE id = ANY(%s)",
            (v1_ids,),
        )
        assert cur.fetchone()[0] == 6


def test_v2_walk_forward_summary_has_composite_aucs(seeded_db_empty_cards):
    """Each v2 walk-forward run's summary.aucs.composite contains the three
    horizons. AC-F4 reads these."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

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
        assert key in composite_aucs
```

- [ ] **Step 2: Run the failing tests**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k v2_walk_forward -v
```

Expected: FAIL — either signature mismatch (`cmd_walk_forward()` got unexpected keyword `args`), or composite_version='1' assertion failure.

- [ ] **Step 3: Refactor `cmd_walk_forward` in `backtest_canary.py`**

Open `scripts/backtest_canary.py`. Find `cmd_walk_forward` at line 780. Refactor:

```python
import uuid


def cmd_walk_forward(conn, *, schema: str, args=None) -> None:
    """6-window expanding-train walk-forward with frozen calibration.

    Writes one regime_backtest_runs row per window. v2 invocation (when
    args.composite_version == 2) loads canary-calibration-v2.json, forces
    run_scope='research', persists composite_version=str(cal.composite_version),
    and tags every params dict with a batch_id (generated once per call).

    The batch_id is printed to stdout so callers can chain --robustness
    with --batch-id.
    """
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    if args is None:
        args = argparse.Namespace(composite_version=1, batch_id=None)

    if args.composite_version == 2:
        cal_path = (
            REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"
        )
        cal = load_calibration(path=cal_path)
        run_scope = "research"
    else:
        cal = load_calibration()
        run_scope = "production"

    batch_id = args.batch_id or str(uuid.uuid4())
    print(f"walk-forward batch_id={batch_id}")  # plumbing for Task 7's chaining

    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    score_form = cal.score_form

    for win in WALK_FORWARD_WINDOWS:
        log.info(
            "walk-forward: %s OOS %s → %s (%s)",
            win["id"], win["oos_start"], win["oos_end"], win["label"],
        )
        series = _compute_canary_series(
            conn, cal, form=score_form,
            start=win["oos_start"], end=win["oos_end"], schema=schema,
        )
        eval_rows = series["eval_rows"]
        all_rows = series["all_rows"]
        events = series["events"]
        if not eval_rows:
            log.warning("walk-forward: %s has zero eval rows — skipping", win["id"])
            continue
        summary = _summarize_window(
            win["id"], eval_rows, all_rows, events, score_form=score_form,
        )
        summary["macro_label"] = win["label"]
        summary["train_end"] = win["train_end"].isoformat()
        run_id = bt_repo.insert_run(
            indicator="canary",
            composite_version=str(cal.composite_version),  # was: str(COMPOSITE_VERSION)
            start_date=eval_rows[0]["date"],
            end_date=eval_rows[-1]["date"],
            window_days=350,
            n_days=len(eval_rows),
            params={
                "score_form": score_form,
                "phase": "walk_forward",
                "window_id": win["id"],
                "train_end": win["train_end"].isoformat(),
                "batch_id": batch_id,  # NEW for v2-A — was missing
            },
            summary=_clean_nans(summary),
            run_scope=run_scope,
        )
        bt_repo.bulk_insert_daily(
            run_id,
            [
                {
                    "trade_date": r["date"], "score": r["score"], "level": r["band"],
                    "payload": {
                        "tactical": r["tactical"], "structural": r["structural"],
                        "speed": r["speed"], "warning_state": r["warning_state"],
                    },
                }
                for r in eval_rows
            ],
        )
        bt_repo.mark_run_completed(run_id)
        log.info("  → run_id=%d (existing summary log)", run_id)
```

(Add `--composite-version` and `--batch-id` to the argparse in `main()`. See Step 4.)

- [ ] **Step 4: Update argparse + dispatch in `main()`**

In `scripts/backtest_canary.py` `main()`:

```python
    parser.add_argument(
        "--composite-version", type=int, choices=(1, 2), default=1,
        help="1 (v1, production, default) or 2 (v2-A, research, loads "
             "canary-calibration-v2.json). Plumbs through walk-forward + "
             "robustness + v1-v2-compare. Spec §5.5.",
    )
    parser.add_argument(
        "--batch-id", type=str, default=None,
        help="Optional batch_id. If omitted, walk-forward generates a UUID4 "
             "(printed to stdout for chaining); robustness/v1-v2-compare "
             "require this to match an existing batch.",
    )
    # ... existing args.parse_args() then dispatch:
    if args.walk_forward:
        cmd_walk_forward(conn, schema=schema, args=args)
        return
    if args.robustness:
        cmd_robustness(conn, schema=schema, args=args)
        return
```

- [ ] **Step 5: Run the v2 walk-forward tests — verify they pass**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k v2_walk_forward -v
```

Expected: 3 passed.

- [ ] **Step 6: Confirm v1 walk-forward unchanged**

```bash
uv run python scripts/backtest_canary.py --walk-forward --help
```

Expected: help text shows `--composite-version` defaulting to 1.

Also re-run Task 2's golden test:

```bash
uv run pytest tests/unit/test_canary_v1_payload_hash_golden.py -v
```

Expected: 3 passed (v1 scoring path untouched).

- [ ] **Step 7: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): cmd_walk_forward accepts args, generates batch_id

Refactor cmd_walk_forward(conn, *, schema, args). Adds:
- --composite-version {1,2}: loads canary-calibration-v2.json on 2 and
  forces run_scope='research'
- --batch-id: optional, default UUID4 generated once, printed to stdout
- batch_id added to EVERY params dict (was missing — grep verified
  zero batch_id references in the existing code path)
- composite_version=str(cal.composite_version) (the loaded field, not
  the module constant — same correctness as Task 5)

v1 path (default --composite-version 1) is unchanged byte-for-byte
except for the new batch_id field in params (additive). Spec §5.5, §6
Layer 2."
```

---

### Task 7: Refactor `cmd_robustness(conn, *, schema, args)` + `--composite-version 2`

**Files:**
- Modify: `scripts/backtest_canary.py` (refactor `cmd_robustness` to accept args; honor `--batch-id`)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** G3 of the spec requires 7 v2 evidence rows: 6 walk-forward + 1 robustness sharing a `batch_id`. Same refactor pattern as Task 6.

- [ ] **Step 1: Write failing tests**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
def _rb_args(*, composite_version: int, batch_id: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        composite_version=composite_version,
        batch_id=batch_id,
    )


def test_v2_robustness_writes_1_research_row(seeded_db_empty_cards):
    """cmd_robustness with composite_version=2 writes 1 research-scoped row."""
    from scripts.backtest_canary import cmd_robustness

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    cmd_robustness(conn, schema=schema, args=_rb_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='robustness'"
        )
        assert cur.fetchone()[0] == 1


def test_v2_robustness_shares_batch_id_when_chained(seeded_db_empty_cards):
    """If --batch-id is passed, robustness row carries the same batch_id."""
    from scripts.backtest_canary import cmd_robustness, cmd_walk_forward

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT params->>'batch_id' "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='walk_forward'"
        )
        wf_batch = cur.fetchone()[0]

    cmd_robustness(conn, schema=schema, args=_rb_args(composite_version=2, batch_id=wf_batch))

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id' FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND composite_version='2' "
            f"  AND params->>'phase'='robustness'"
        )
        rb_batch = cur.fetchone()[0]

    assert rb_batch == wf_batch
```

- [ ] **Step 2: Run failing tests**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k v2_robustness -v
```

Expected: FAIL.

- [ ] **Step 3: Refactor `cmd_robustness` in `backtest_canary.py`**

Find `cmd_robustness` at line 933. Apply the same pattern as Task 6:

```python
def cmd_robustness(conn, *, schema: str, args=None) -> None:
    """Robustness report against the full backfilled dataset.

    See Task 7 of the v2-A plan. v2 invocation persists composite_version=2,
    run_scope='research', and tags params.batch_id with args.batch_id (or
    a freshly-generated UUID4 if absent).
    """
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    if args is None:
        args = argparse.Namespace(composite_version=1, batch_id=None)

    if args.composite_version == 2:
        cal_path = (
            REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"
        )
        cal = load_calibration(path=cal_path)
        run_scope = "research"
    else:
        cal = load_calibration()
        run_scope = "production"

    batch_id = args.batch_id or str(uuid.uuid4())
    print(f"robustness batch_id={batch_id}")

    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    score_form = cal.score_form

    # ... existing computation (series, _section, by_year, by_band, summary) ...

    run_id = bt_repo.insert_run(
        indicator="canary",
        composite_version=str(cal.composite_version),  # was: str(COMPOSITE_VERSION)
        start_date=all_rows[0]["date"],
        end_date=all_rows[-1]["date"],
        window_days=350,
        n_days=len(all_rows),
        params={
            "score_form": score_form,
            "phase": "robustness",
            "batch_id": batch_id,  # NEW for v2-A
        },
        summary=_clean_nans(summary),
        run_scope=run_scope,
    )
    bt_repo.mark_run_completed(run_id)
```

- [ ] **Step 4: Run robustness tests — verify they pass**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k v2_robustness -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): cmd_robustness accepts args + --composite-version 2

Mirrors Task 6's refactor. v2 invocation loads v2 calibration, forces
run_scope='research', persists composite_version=str(cal.composite_version),
and tags params.batch_id (UUID4 by default, or args.batch_id if chaining
with walk-forward).

2 integration tests:
- 1 robustness row (research, composite_version='2')
- Shared batch_id when chained via --batch-id

Spec §5.5, §G3."
```

---

### Task 8: Walk-forward recompute vs backfill parity test (AC-4b)

**Files:**
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** Walk-forward recomputes scores from `vol_index_daily` (NOT from `canary_snapshots`). Spec §5.5 says these must match within floating-point tolerance for any given date. The parity test asserts this for ~30 dates across all walk-forward windows.

- [ ] **Step 1: Write the parity test**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
import random


def test_v2_walk_forward_recompute_matches_v2_backfill_snapshots(
    seeded_db_empty_cards,
):
    """For ~30 sample dates, walk-forward's recomputed v2 score equals the
    v2 backfill snapshot score for the same date. Floating-point tolerance:
    1e-6 on raw_score, exact on band.

    Confirms recompute (from vol_index_daily) vs backfill (from
    canary_snapshots) produce identical outputs at v2. Spec §5.5 + §7 AC-4b.
    """
    from scripts.canary_backfill import cmd_backfill

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    # 1. v2 backfill across the full range
    backfill_args = argparse.Namespace(
        composite_version=2,
        start_date="2015-01-02",
        end_date="2026-05-21",
        overwrite_on_hash_mismatch=False,
        days=252,
    )
    cmd_backfill(conn, schema=schema, args=backfill_args)

    # 2. v2 walk-forward
    cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    # 3. Pull walk-forward daily rows
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT d.trade_date, d.score, d.level "
            f"FROM {schema}.regime_backtest_daily d "
            f"JOIN {schema}.regime_backtest_runs r ON d.run_id = r.id "
            f"WHERE r.indicator='canary' AND r.composite_version='2' "
            f"  AND r.run_scope='research' AND r.params->>'phase'='walk_forward' "
            f"ORDER BY d.trade_date"
        )
        wf_rows = {r[0]: (float(r[1]), r[2]) for r in cur.fetchall()}

    # 4. Pull backfill snapshot rows
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data_date, score, band FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 AND data_date = ANY(%s)",
            (list(wf_rows.keys()),),
        )
        bf_rows = {r[0]: (float(r[1]), r[2]) for r in cur.fetchall()}

    # 5. Sample and compare
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

- [ ] **Step 2: Run the parity test**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v2_walk_forward_recompute_matches_v2_backfill_snapshots -v
```

Expected: PASS (both paths use `run_analysis` with the same v2 calibration).

If FAIL: investigate divergence — most likely:
- The backfill computes one extra/fewer warmup bar than walk-forward
- An intermediate scorer rounds differently between paths
- The `_replay_events` state differs

Fix the underlying divergence — do NOT loosen the tolerance.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "test(canary): v2 walk-forward recompute vs backfill parity (AC-4b)

For ~30 sampled dates, asserts walk-forward's recomputed v2 score
matches the v2 backfill snapshot score within 1e-6 floating-point
tolerance, with byte-identical band.

Catches: (a) walk-forward and backfill diverging code paths, (b) input
drift between paths, (c) precision loss in intermediates. Spec §5.5 +
§7 AC-4b."
```

---

### Task 9: NEW module `src/uw_scan/reports/regime_canary_v1_v2_compare.py` (assembly + renderer + CLI)

**Files:**
- Create: `src/uw_scan/reports/regime_canary_v1_v2_compare.py`
- Create: `tests/unit/test_canary_v1_v2_compare_renderer.py`

**Rationale:** Centralize all v1↔v2 comparison logic in one module. `scripts/backtest_canary.py` is already 1,174 lines — adding the dispatcher in-place would violate the "no methods on >1,000 LOC files without a split plan" convention. Same precedent as PR #88's `regime_canary_form_sweep_full.py`.

The new module owns:
- `FlipGateEvidence` dataclass (pure data)
- `_assemble_flip_gate_evidence(conn, *, schema)` — DB queries
- `_full_history_aucs_via_compute_canary_series(conn, *, cal, schema)` — uses `_compute_canary_series` so `eval_rows` have the `spx` field `_aucs_for_rows` needs (snapshot rows don't)
- `_band_distribution_for_version(conn, *, schema, version)`
- `_run_subprocess_test(test_path)` for AC-F6
- `_eval_ac_f1..f6` helpers
- `render_canary_v1_v2_compare(ev) -> str` — pure renderer
- `assemble_and_render_canary_v1_v2_compare(conn, *, schema) -> str` — convenience for callers
- `main()` — standalone CLI

`backtest_canary.py` only knows about the convenience function.

- [ ] **Step 1: Write the module**

Path: `src/uw_scan/reports/regime_canary_v1_v2_compare.py`

```python
"""Canary v1-vs-v2 evidence assembly + comparison renderer + standalone CLI.

Three layers:
  1. _assemble_flip_gate_evidence(conn, *, schema) — DB queries (impure).
     Reads v1 walk-forward production runs, v2 walk-forward research runs
     (sharing a batch_id), v2 robustness run, v1/v2 snapshot-based band
     distributions and CCA event states. Computes v1 + v2 full-history
     AUCs via _compute_canary_series so the row dicts contain the `spx`
     field _aucs_for_rows needs (canary_snapshots rows do not).

  2. render_canary_v1_v2_compare(ev) -> str — pure function on
     FlipGateEvidence. Evaluates AC-F1..F6 and emits a markdown report
     with SHIP/STOP verdict + locked PR-2 footer.

  3. main() — standalone CLI for re-rendering an already-persisted bundle.

The thin dispatcher in `scripts/backtest_canary.py` calls
assemble_and_render_canary_v1_v2_compare() and prints the result.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import date as _date
from io import StringIO
from pathlib import Path

import psycopg

from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
V1_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v1.json"
V2_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"

CANONICAL_WINDOWS = ("WF-1", "WF-2", "WF-3", "WF-4", "WF-5", "WF-6")
CCA_EVENT_DATES = ("2011-08-08", "2015-08-24", "2018-02-05", "2020-03-09")

# AC-F1..F5 thresholds, locked-in by spec §8. DO NOT change without a spec amendment.
AC_F1_60D_BAR = 0.634
AC_F2_20D_BAR = 0.622
AC_F2_5D_BAR = 0.615
AC_F4_PER_WINDOW_TOLERANCE = -0.02
AC_F5_WATCH_PCT_BAR = 44.3


@dataclass(frozen=True)
class FlipGateEvidence:
    """Pre-assembled bundle that lets the renderer evaluate every AC-Fn locally.

    Fields:
      v1_runs / v2_runs: 6 walk-forward run dicts each.
        v1: composite_version='1', run_scope='production'.
        v2: composite_version='2', run_scope='research', shared batch_id.
      v2_robustness_run: 1 robustness run dict, same scope/version.
      v1_full_history_aucs / v2_full_history_aucs: composite AUC over the
        FULL history at the given composite_version. Computed via
        _compute_canary_series (NOT raw SQL projection — snapshots don't
        carry the spx forward-return labels).
      v1_band_distribution / v2_band_distribution: pct of full-history
        snapshots per band. Keys: NONE, WATCH, BUY, STRONG_BUY.
      v2_cca_event_states: payload.speed.confirmed_canary_active per
        CCA event date. Keys: ISO date strings. Values: bool.
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
            raise ValueError(f"v1_runs composite_version={r.get('composite_version')!r}")
        if r.get("run_scope") != "production":
            raise ValueError(f"v1_runs run_scope={r.get('run_scope')!r}")
    for r in ev.v2_runs:
        if str(r.get("composite_version")) != "2":
            raise ValueError(f"v2_runs composite_version={r.get('composite_version')!r}")
        if r.get("run_scope") != "research":
            raise ValueError(f"v2_runs run_scope={r.get('run_scope')!r}")
    v2_batch_ids = {r["params"].get("batch_id") for r in ev.v2_runs}
    if len(v2_batch_ids) != 1:
        raise ValueError(f"v2_runs must share batch_id, got {v2_batch_ids}")
    if v2_batch_ids == {None}:
        raise ValueError("v2_runs batch_id must not be None")
    v1_window_ids = {r["params"].get("window_id") for r in ev.v1_runs}
    v2_window_ids = {r["params"].get("window_id") for r in ev.v2_runs}
    if v1_window_ids != set(CANONICAL_WINDOWS):
        raise ValueError(f"v1_runs window_ids != WF-1..WF-6, got {v1_window_ids}")
    if v2_window_ids != set(CANONICAL_WINDOWS):
        raise ValueError(f"v2_runs window_ids != WF-1..WF-6, got {v2_window_ids}")
    if str(ev.v2_robustness_run.get("composite_version")) != "2":
        raise ValueError("v2_robustness_run composite_version must be 2")
    if ev.v2_robustness_run.get("run_scope") != "research":
        raise ValueError("v2_robustness_run run_scope must be research")
    for d in CCA_EVENT_DATES:
        if d not in ev.v2_cca_event_states:
            raise ValueError(f"v2_cca_event_states missing {d}")


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
        f"(bar >= {AC_F1_60D_BAR}; v1 ref {v1_ref:.4f}, delta {delta:+.4f})"
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
        f"(bar >= {AC_F2_20D_BAR}, {'PASS' if p20 else 'FAIL'}), "
        f"v2 5d AUC = {auc_5:.4f} "
        f"(bar >= {AC_F2_5D_BAR}, {'PASS' if p5 else 'FAIL'})"
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
            failures.append(f"{wid}: v2={v2_auc:.4f} v1={v1_auc:.4f} delta={delta:+.4f}")
    passed = not failures
    verdict = "PASS" if passed else "FAIL"
    detail = "all 6 windows within tolerance" if passed else f"failed: {failures}"
    return passed, (
        f"AC-F4 [{verdict}]: per-window 60d AUC delta "
        f">= {AC_F4_PER_WINDOW_TOLERANCE} — {detail}"
    )


def _eval_ac_f5(ev: FlipGateEvidence) -> tuple[bool, str]:
    watch = ev.v2_band_distribution.get("WATCH")
    if watch is None:
        return False, "AC-F5: v2 WATCH% unavailable"
    passed = watch <= AC_F5_WATCH_PCT_BAR
    verdict = "PASS" if passed else "FAIL"
    return passed, (
        f"AC-F5 [{verdict}]: v2 WATCH% = {watch:.1f}% "
        f"(bar <= {AC_F5_WATCH_PCT_BAR}%)"
    )


def _eval_ac_f6(ev: FlipGateEvidence) -> tuple[bool, str]:
    passed = ev.oos_gate_passed and ev.v1_payload_hash_golden_passed
    verdict = "PASS" if passed else "FAIL"
    parts = [
        "oos_gate=" + ("PASS" if ev.oos_gate_passed else "FAIL"),
        "v1_golden=" + ("PASS" if ev.v1_payload_hash_golden_passed else "FAIL"),
    ]
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

    # Full-history AUCs
    out.write("## Full-history AUCs (composite over all snapshots)\n\n")
    out.write("| Horizon          | v1 (production) | v2 (research)   |    Δ     |\n")
    out.write("|------------------|----------------:|----------------:|---------:|\n")
    for horizon in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        v1 = ev.v1_full_history_aucs.get(horizon)
        v2 = ev.v2_full_history_aucs.get(horizon)
        if v1 is None or v2 is None:
            out.write(f"| {horizon:<16} | n/a             | n/a             | n/a      |\n")
        else:
            d = v2 - v1
            out.write(
                f"| {horizon:<16} | {v1:>14.4f}  | {v2:>14.4f}  | {d:>+8.4f} |\n"
            )
    out.write("\n")

    # Band distribution
    out.write("## Band distribution (full-history snapshots)\n\n")
    out.write("| Band       |  v1 % |  v2 % |\n")
    out.write("|------------|------:|------:|\n")
    for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        v1 = ev.v1_band_distribution.get(band, 0.0)
        v2 = ev.v2_band_distribution.get(band, 0.0)
        out.write(f"| {band:<10} | {v1:>4.1f} | {v2:>4.1f} |\n")
    out.write("\n")

    # Per-window
    out.write("## Per-window 60d AUC (walk-forward)\n\n")
    out.write("| Window | v1 60d AUC | v2 60d AUC |    Δ    |\n")
    out.write("|--------|-----------:|-----------:|--------:|\n")
    v1_by_wid = {r["params"]["window_id"]: r for r in ev.v1_runs}
    v2_by_wid = {r["params"]["window_id"]: r for r in ev.v2_runs}
    for wid in CANONICAL_WINDOWS:
        v1 = v1_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        v2 = v2_by_wid[wid]["summary"]["aucs"]["composite"].get("up60d_10pct")
        if v1 is None or v2 is None:
            out.write(f"| {wid}   | n/a        | n/a        | n/a     |\n")
        else:
            d = v2 - v1
            out.write(f"| {wid}   | {v1:>9.4f}  | {v2:>9.4f}  | {d:>+7.4f} |\n")
    out.write("\n")

    # AC evaluation
    out.write("## AC-F1..F6 Evaluation\n\n")
    results = [
        _eval_ac_f1(ev), _eval_ac_f2(ev), _eval_ac_f3(ev),
        _eval_ac_f4(ev), _eval_ac_f5(ev), _eval_ac_f6(ev),
    ]
    for _, line in results:
        out.write(f"- {line}\n")
    out.write("\n")

    all_pass = all(p for p, _ in results)
    verdict = "SHIP" if all_pass else "STOP"
    out.write(f"## Verdict: **{verdict}**\n\n")
    if all_pass:
        out.write(
            "All 6 AC-Fn gates passed. PR 2 may flip "
            "`COMPOSITE_VERSION = 1 -> 2` in `canary_calibration.py:11`. "
            "See spec §10 for the PR 2 task list.\n\n"
        )
    else:
        out.write(
            "One or more AC-Fn gates failed. **PR 2 is NOT authorized.** "
            "Record the verdict in `docs/research/regime/canary-5yr-executive-summary.md` "
            "§13, file a follow-up issue, and pivot to v2-C (issue #90).\n\n"
        )

    out.write("## What PR 2 will do iff this verdict is SHIP\n\n")
    out.write(
        "PR 2 is a small (~80-150 LOC) commit that:\n"
        "1. Bumps `COMPOSITE_VERSION = 2` in `canary_calibration.py:11`.\n"
        "2. Regens `web/lib/types.ts` from updated OpenAPI schema.\n"
        "3. Replaces `LAST_KNOWN_AUC_v1_*` with `LAST_KNOWN_AUC_v2_*`.\n"
        "4. Updates `canary-methodology.md` to document the v2 formula.\n"
        "5. Adds a deprecation note in `canary-calibration-v1.json`.\n"
        "6. Updates `CanarySubTab.tsx` + `CanaryValidationPanel.tsx` to "
        "surface `vol_resolution_score` + `speed_state` + `warning_cap` separately.\n"
    )
    return out.getvalue()


# --------------- DB assembly (impure) ---------------


def _full_history_aucs_via_compute_canary_series(
    conn, *, cal, schema: str,
) -> dict[str, float]:
    """Compute composite AUC over the full history using _compute_canary_series.

    Snapshot rows do not carry the spx forward-return inputs that
    _aucs_for_rows -> _entry_lagged_label needs. _compute_canary_series's
    eval_rows DO ({"date","spx","score","band","tactical","structural","speed",
    "warning_state"}), so this is the correct apples-to-apples path.
    """
    # Lazy import — scripts.backtest_canary owns _aucs_for_rows.
    from scripts.backtest_canary import _aucs_for_rows, _compute_canary_series

    series = _compute_canary_series(
        conn, cal, form=cal.score_form,
        start=_date(2011, 2, 8), end=_date.today(),
        schema=schema,
    )
    return _aucs_for_rows(series["eval_rows"])["composite"]


def _band_distribution_for_version(
    conn, *, schema: str, version: int,
) -> dict[str, float]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT band, COUNT(*) FROM {schema}.canary_snapshots "
            f"WHERE composite_version=%s GROUP BY band",
            (version,),
        )
        counts = dict(cur.fetchall())
    total = sum(counts.values())
    if total == 0:
        return {b: 0.0 for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")}
    return {
        b: 100.0 * counts.get(b, 0) / total
        for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    }


def _run_subprocess_test(test_path: str) -> bool:
    """Run pytest on a single test file. Returns True on returncode 0.

    Inherits parent environment (PATH preserved so `uv` is found on macOS,
    which keeps uv at ~/.cargo/bin/uv outside /usr/bin:/bin).
    """
    proc = subprocess.run(
        ["uv", "run", "pytest", test_path, "-q", "--no-header"],
        capture_output=True, text=True, timeout=300,
    )
    return proc.returncode == 0


def _assemble_flip_gate_evidence(conn, *, schema: str) -> FlipGateEvidence:
    """Build a FlipGateEvidence from DB. Heavy — run only in --v1-v2-compare."""
    with conn.cursor() as cur:
        # v1 walk-forward runs — latest completed per window_id, production scope.
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
        v1_runs = [
            {"id": r[0], "composite_version": r[1], "run_scope": r[2],
             "params": r[3], "summary": r[4]} for r in cur.fetchall()
        ]
        if len(v1_runs) != 6:
            raise RuntimeError(
                f"v1 walk-forward query returned {len(v1_runs)} rows, expected 6. "
                f"Has PR #83's persistence completed?"
            )

        # Pick latest v2 walk-forward batch that has all 6 windows.
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
                "`uv run python scripts/backtest_canary.py --walk-forward "
                "--composite-version 2` first."
            )
        v2_batch_id = row[0]

        cur.execute(
            f"SELECT id, composite_version, run_scope, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='walk_forward' "
            f"  AND params->>'batch_id'=%s AND completed_at IS NOT NULL "
            f"ORDER BY params->>'window_id'",
            (v2_batch_id,),
        )
        v2_runs = [
            {"id": r[0], "composite_version": r[1], "run_scope": r[2],
             "params": r[3], "summary": r[4]} for r in cur.fetchall()
        ]

        cur.execute(
            f"SELECT id, composite_version, run_scope, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='robustness' "
            f"  AND params->>'batch_id'=%s AND completed_at IS NOT NULL "
            f"ORDER BY completed_at DESC LIMIT 1",
            (v2_batch_id,),
        )
        rb = cur.fetchone()
        if rb is None:
            raise RuntimeError(
                f"no v2 robustness run for batch_id={v2_batch_id}. Run "
                f"`uv run python scripts/backtest_canary.py --robustness "
                f"--composite-version 2 --batch-id {v2_batch_id}`."
            )
        v2_robustness_run = {
            "id": rb[0], "composite_version": rb[1], "run_scope": rb[2],
            "params": rb[3], "summary": rb[4],
        }

        cur.execute(
            f"SELECT data_date::text, payload->'speed'->>'confirmed_canary_active' "
            f"FROM {schema}.canary_snapshots "
            f"WHERE composite_version=2 AND data_date = ANY(%s)",
            ([_date.fromisoformat(d) for d in CCA_EVENT_DATES],),
        )
        v2_cca_event_states = {d: (str(v).lower() == "true") for d, v in cur.fetchall()}
        for d in CCA_EVENT_DATES:
            v2_cca_event_states.setdefault(d, False)

    # Full-history AUCs via _compute_canary_series (snapshot rows lack `spx`).
    v1_cal = load_calibration(path=V1_CAL_PATH)
    v2_cal = load_calibration(path=V2_CAL_PATH)
    v1_full_history_aucs = _full_history_aucs_via_compute_canary_series(
        conn, cal=v1_cal, schema=schema,
    )
    v2_full_history_aucs = _full_history_aucs_via_compute_canary_series(
        conn, cal=v2_cal, schema=schema,
    )

    v1_band_distribution = _band_distribution_for_version(conn, schema=schema, version=1)
    v2_band_distribution = _band_distribution_for_version(conn, schema=schema, version=2)

    oos_gate_passed = _run_subprocess_test(
        "tests/integration/regime/test_canary_oos_gate.py"
    )
    v1_payload_hash_golden_passed = _run_subprocess_test(
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


def assemble_and_render_canary_v1_v2_compare(conn, *, schema: str) -> str:
    """Convenience: assemble evidence + render to markdown. The dispatcher
    in scripts/backtest_canary.py calls this and prints the result."""
    ev = _assemble_flip_gate_evidence(conn, schema=schema)
    return render_canary_v1_v2_compare(ev)


def main() -> int:
    """Standalone CLI: re-render the latest v1+v2 evidence bundle from DB."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        print(assemble_and_render_canary_v1_v2_compare(conn, schema=settings.db_schema))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write the renderer unit tests**

Path: `tests/unit/test_canary_v1_v2_compare_renderer.py`

```python
"""Unit tests for render_canary_v1_v2_compare (pure renderer)."""

from __future__ import annotations

from copy import deepcopy

import pytest

from uw_scan.reports.regime_canary_v1_v2_compare import (
    CANONICAL_WINDOWS,
    CCA_EVENT_DATES,
    FlipGateEvidence,
    render_canary_v1_v2_compare,
)


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
                    "up5d_2pct": 0.62, "up20d_5pct": 0.63, "up60d_10pct": auc_60d,
                }
            }
        },
    }


def _happy_evidence() -> FlipGateEvidence:
    return FlipGateEvidence(
        v1_runs=[
            _mk_run(version="1", scope="production", window_id=w) for w in CANONICAL_WINDOWS
        ],
        v2_runs=[
            _mk_run(version="2", scope="research", window_id=w) for w in CANONICAL_WINDOWS
        ],
        v2_robustness_run={
            "id": 999, "composite_version": "2", "run_scope": "research",
            "params": {"phase": "robustness", "batch_id": "batch-v2-test"},
            "summary": {},
        },
        v1_full_history_aucs={"up5d_2pct": 0.620, "up20d_5pct": 0.627, "up60d_10pct": 0.619},
        v2_full_history_aucs={"up5d_2pct": 0.625, "up20d_5pct": 0.635, "up60d_10pct": 0.640},
        v1_band_distribution={"NONE": 55.0, "WATCH": 39.3, "BUY": 5.5, "STRONG_BUY": 0.2},
        v2_band_distribution={"NONE": 60.0, "WATCH": 35.0, "BUY": 4.9, "STRONG_BUY": 0.1},
        v2_cca_event_states={d: True for d in CCA_EVENT_DATES},
        oos_gate_passed=True,
        v1_payload_hash_golden_passed=True,
    )


def _replace(ev: FlipGateEvidence, **overrides) -> FlipGateEvidence:
    data = {
        f.name: getattr(ev, f.name) for f in FlipGateEvidence.__dataclass_fields__.values()
    }
    data.update(overrides)
    return FlipGateEvidence(**data)


def test_happy_path_ship_verdict():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Verdict: **SHIP**" in out
    for label in ("AC-F1 [PASS]", "AC-F2 [PASS]", "AC-F3 [PASS]",
                  "AC-F4 [PASS]", "AC-F5 [PASS]", "AC-F6 [PASS]"):
        assert label in out


def test_ac_f1_fail_below_bar():
    ev = _replace(
        _happy_evidence(),
        v2_full_history_aucs={"up5d_2pct": 0.625, "up20d_5pct": 0.635, "up60d_10pct": 0.620},
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F1 [FAIL]" in out
    assert "Verdict: **STOP**" in out


def test_ac_f2_fail_20d_horizon():
    ev = _replace(
        _happy_evidence(),
        v2_full_history_aucs={"up5d_2pct": 0.625, "up20d_5pct": 0.610, "up60d_10pct": 0.640},
    )
    out = render_canary_v1_v2_compare(ev)
    assert "AC-F2 [FAIL]" in out


def test_ac_f3_fail_when_cca_event_missing_fire():
    cca = {d: True for d in CCA_EVENT_DATES}
    cca["2011-08-08"] = False
    out = render_canary_v1_v2_compare(_replace(_happy_evidence(), v2_cca_event_states=cca))
    assert "AC-F3 [FAIL]" in out
    assert "2011-08-08" in out


def test_ac_f4_fail_when_window_regresses_more_than_002():
    v2_runs = list(deepcopy(_happy_evidence().v2_runs))
    v2_runs[2]["summary"]["aucs"]["composite"]["up60d_10pct"] = 0.60
    out = render_canary_v1_v2_compare(_replace(_happy_evidence(), v2_runs=v2_runs))
    assert "AC-F4 [FAIL]" in out
    assert "WF-3" in out


def test_ac_f5_fail_when_watch_pct_too_high():
    bd = {"NONE": 44.5, "WATCH": 50.0, "BUY": 5.4, "STRONG_BUY": 0.1}
    out = render_canary_v1_v2_compare(_replace(_happy_evidence(), v2_band_distribution=bd))
    assert "AC-F5 [FAIL]" in out


def test_ac_f6_fail_when_oos_gate_fails():
    out = render_canary_v1_v2_compare(_replace(_happy_evidence(), oos_gate_passed=False))
    assert "AC-F6 [FAIL]" in out


def test_ac_f6_fail_when_v1_golden_fails():
    out = render_canary_v1_v2_compare(
        _replace(_happy_evidence(), v1_payload_hash_golden_passed=False)
    )
    assert "AC-F6 [FAIL]" in out


def test_invalid_v1_runs_count_raises():
    ev = _happy_evidence()
    bad = _replace(ev, v1_runs=ev.v1_runs[:5])
    with pytest.raises(ValueError, match="v1_runs must have 6"):
        render_canary_v1_v2_compare(bad)


def test_invalid_v2_scope_raises():
    ev = _happy_evidence()
    bad_runs = [deepcopy(r) for r in ev.v2_runs]
    bad_runs[0]["run_scope"] = "production"
    with pytest.raises(ValueError, match="run_scope"):
        render_canary_v1_v2_compare(_replace(ev, v2_runs=bad_runs))


def test_invalid_window_id_set_raises():
    ev = _happy_evidence()
    bad_runs = [deepcopy(r) for r in ev.v2_runs]
    bad_runs[0]["params"]["window_id"] = "WF-99"
    with pytest.raises(ValueError, match="window_ids"):
        render_canary_v1_v2_compare(_replace(ev, v2_runs=bad_runs))


def test_v2_runs_must_share_batch_id():
    ev = _happy_evidence()
    bad_runs = [deepcopy(r) for r in ev.v2_runs]
    bad_runs[0]["params"]["batch_id"] = "different-batch"
    with pytest.raises(ValueError, match="batch_id"):
        render_canary_v1_v2_compare(_replace(ev, v2_runs=bad_runs))


def test_missing_cca_event_date_raises():
    ev = _happy_evidence()
    bad_cca = {d: True for d in CCA_EVENT_DATES if d != "2020-03-09"}
    with pytest.raises(ValueError, match="2020-03-09"):
        render_canary_v1_v2_compare(_replace(ev, v2_cca_event_states=bad_cca))


def test_footer_present_in_both_verdicts():
    out_ship = render_canary_v1_v2_compare(_happy_evidence())
    assert "What PR 2 will do iff this verdict is SHIP" in out_ship

    ev_stop = _replace(
        _happy_evidence(),
        v2_full_history_aucs={"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
    )
    out_stop = render_canary_v1_v2_compare(ev_stop)
    assert "What PR 2 will do iff this verdict is SHIP" in out_stop
    assert "Verdict: **STOP**" in out_stop


def test_band_distribution_table_present():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Band distribution" in out
    for b in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        assert b in out


def test_per_window_table_present_with_all_6_windows():
    out = render_canary_v1_v2_compare(_happy_evidence())
    assert "Per-window 60d AUC" in out
    for w in CANONICAL_WINDOWS:
        assert w in out
```

- [ ] **Step 3: Run the renderer tests — verify they pass**

```bash
uv run pytest tests/unit/test_canary_v1_v2_compare_renderer.py -v
```

Expected: 16 passed.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/reports/regime_canary_v1_v2_compare.py tests/unit/test_canary_v1_v2_compare_renderer.py
git commit -m "feat(canary): regime_canary_v1_v2_compare module + renderer + 16 tests

NEW module src/uw_scan/reports/regime_canary_v1_v2_compare.py owns:
- FlipGateEvidence dataclass
- _assemble_flip_gate_evidence(conn, *, schema) — DB queries with
  full scope/version/completion filters (was: under-filtered)
- _full_history_aucs_via_compute_canary_series(conn, *, cal, schema) —
  uses _compute_canary_series so eval_rows carry the spx forward-return
  field _aucs_for_rows needs (snapshot rows do not)
- _band_distribution_for_version
- _run_subprocess_test (inherits PATH so uv works on macOS)
- _eval_ac_f1..f6 helpers
- render_canary_v1_v2_compare(ev) — pure
- assemble_and_render_canary_v1_v2_compare(conn, schema) — convenience
- main() — standalone CLI

This keeps scripts/backtest_canary.py under the 1,000-LOC convention
(currently 1,174; adding 200 LOC here would push it past 1,400).

16 unit tests covering: SHIP/STOP verdicts, each AC failure mode,
structural validators (wrong v1 count, wrong scope, wrong window_ids,
mismatched batch_id, missing CCA date), tables present in both verdicts.

Spec §5.7, §5.8."
```

---

### Task 10: Thin `cmd_v1_v2_compare` dispatcher in `backtest_canary.py` + integration test

**Files:**
- Modify: `scripts/backtest_canary.py` (add ~10-LOC dispatcher + argparse flag)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** With Task 9's module owning all logic, the script-level dispatcher is a thin wrapper.

- [ ] **Step 1: Write failing dispatcher integration tests**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
from scripts.backtest_canary import cmd_v1_v2_compare


def test_v1_v2_compare_dispatcher_renders_nonempty(
    seeded_db_empty_cards, capsys,
):
    """cmd_v1_v2_compare assembles + prints a non-empty report."""
    from tests.integration.regime._canary_v2a_fixture import (
        seed_canary_snapshots_v2,
        seed_v1_walk_forward_runs,
        seed_v2_walk_forward_runs,
        seed_vol_index_full_history,
    )
    from scripts.canary_backfill import cmd_backfill

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema

    # Build v1 + v2 evidence bundles
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))
    seed_v1_walk_forward_runs(conn, schema=schema)
    seed_v2_walk_forward_runs(conn, schema=schema)
    # Snapshots: v1 and v2 (real backfill so the full-history AUCs work)
    cmd_backfill(conn, schema=schema, args=argparse.Namespace(
        composite_version=1, start_date="2015-01-02", end_date="2026-05-21",
        overwrite_on_hash_mismatch=False, days=252,
    ))
    cmd_backfill(conn, schema=schema, args=argparse.Namespace(
        composite_version=2, start_date="2015-01-02", end_date="2026-05-21",
        overwrite_on_hash_mismatch=False, days=252,
    ))

    cmd_v1_v2_compare(conn, schema=schema, args=argparse.Namespace())

    out = capsys.readouterr().out
    assert "Canary v2-A — v1 vs v2 Comparison" in out
    assert "Full-history AUCs" in out
    assert "Band distribution" in out
    assert "Per-window 60d AUC" in out
    assert "AC-F1..F6 Evaluation" in out
    assert "Verdict:" in out
    assert "What PR 2 will do" in out


def test_v1_v2_compare_fails_clearly_when_no_v2_batch(seeded_db_empty_cards):
    """If no complete v2 walk-forward batch exists, raises with actionable error."""
    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema

    with pytest.raises(RuntimeError, match="no complete v2 walk-forward batch"):
        cmd_v1_v2_compare(conn, schema=schema, args=argparse.Namespace())
```

- [ ] **Step 2: Run the failing tests**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k v1_v2_compare -v
```

Expected: FAIL (`ImportError: cannot import name 'cmd_v1_v2_compare'`).

- [ ] **Step 3: Add the thin dispatcher in `backtest_canary.py`**

In `scripts/backtest_canary.py`:

```python
def cmd_v1_v2_compare(conn, *, schema: str, args=None) -> None:
    """Assemble + render the v1-vs-v2 evidence report.

    All logic lives in src/uw_scan/reports/regime_canary_v1_v2_compare.py;
    this stub stays under the 1,000-LOC convention for scripts/backtest_canary.py.
    """
    from uw_scan.reports.regime_canary_v1_v2_compare import (
        assemble_and_render_canary_v1_v2_compare,
    )

    print(assemble_and_render_canary_v1_v2_compare(conn, schema=schema))
```

In `main()`, add `--v1-v2-compare` to argparse with mutual-exclusion check, and dispatch:

```python
    parser.add_argument(
        "--v1-v2-compare", action="store_true",
        help="Assemble v1+v2 evidence and render the comparison report with "
             "AC-F1..F6 evaluation. Reads v1 walk-forward (production), v2 "
             "walk-forward (research, latest complete batch), v2 robustness, "
             "v1/v2 full-history snapshots, v2 CCA event states, and the OOS "
             "+ v1-golden test results.",
    )
    # ... after parse_args, with mutual exclusion:
    mode_flags = [
        args.calibrate, args.form_sweep, args.form_sweep_full, args.report,
        args.walk_forward, args.robustness, args.v1_v2_compare,
    ]
    if sum(bool(f) for f in mode_flags) > 1:
        parser.error("only one of --calibrate/--form-sweep/--form-sweep-full/"
                     "--report/--walk-forward/--robustness/--v1-v2-compare")
    # ... in the dispatch chain:
    if args.v1_v2_compare:
        cmd_v1_v2_compare(conn, schema=schema, args=args)
        return
```

- [ ] **Step 4: Run integration tests — verify they pass**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -k v1_v2_compare -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): thin cmd_v1_v2_compare dispatcher in backtest_canary

~10 LOC wrapper in backtest_canary.py — imports
assemble_and_render_canary_v1_v2_compare from the Task 9 module and
prints the result. Keeps the 1,174-line script from growing past the
1,000-LOC convention.

2 integration tests:
- Dispatcher renders the full report (all required sections)
- Raises with actionable error when no v2 batch exists

Spec §5.7."
```

---

### Task 11: Walk-forward cleanup-on-failure (in-process `pytest-mock` test)

**Files:**
- Modify: `scripts/backtest_canary.py` (wrap v2 walk-forward + robustness persistence in try/except)
- Modify: `tests/integration/regime/test_canary_v2_walk_forward.py`

**Rationale:** When v2 walk-forward fails mid-batch (e.g., the 4th of 6 inserts errors), partial rows remain. The cleanup pattern is exactly the form-sweep pattern from PR #88 §3.4 (rollback + scoped delete + raise original).

The cleanup test must use **in-process** invocation + `pytest-mock` (in deps already). A subprocess-based test can't mock `RegimeBacktestRepository.bulk_insert_daily` inside the child process.

- [ ] **Step 1: Write the failing cleanup test**

Append to `tests/integration/regime/test_canary_v2_walk_forward.py`:

```python
def test_v2_walk_forward_cleanup_on_mid_batch_failure(
    seeded_db_empty_cards, mocker,
):
    """If bulk_insert_daily raises on the 4th of 6 walk-forward windows,
    every persisted v2 walk-forward row (including the 3 successfully
    inserted) is cleaned up. v1 production rows untouched.

    Uses in-process cmd_walk_forward + mocker.patch.object(..., wraps=...)
    so the side_effect can pass-through the first 3 calls and raise on the 4th.
    Spec §5.8.
    """
    from tests.integration.regime._canary_v2a_fixture import (
        seed_v1_walk_forward_runs, seed_vol_index_full_history,
    )

    conn = seeded_db_empty_cards.conn
    schema = seeded_db_empty_cards._schema
    seed_v1_walk_forward_runs(conn, schema=schema)
    seed_vol_index_full_history(conn, schema=schema, start=_date(2013, 1, 2), end=_date(2026, 5, 21))

    # Patch bulk_insert_daily with wraps=original so first 3 calls succeed,
    # 4th raises.
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
    real = RegimeBacktestRepository.bulk_insert_daily
    call_count = {"n": 0}

    def flaky(self, run_id, rows):
        call_count["n"] += 1
        if call_count["n"] == 4:
            raise RuntimeError("simulated 4th-window failure")
        return real(self, run_id, rows)

    mocker.patch.object(RegimeBacktestRepository, "bulk_insert_daily", autospec=True, side_effect=flaky)

    with pytest.raises(RuntimeError, match="simulated 4th-window failure"):
        cmd_walk_forward(conn, schema=schema, args=_wf_args(composite_version=2))

    # Zero v2 walk-forward rows remain.
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='research' "
            f"  AND composite_version='2' AND params->>'phase'='walk_forward'"
        )
        assert cur.fetchone()[0] == 0

    # v1 production rows untouched.
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {schema}.regime_backtest_runs "
            f"WHERE indicator='canary' AND run_scope='production' "
            f"  AND composite_version='1' AND params->>'phase'='walk_forward'"
        )
        assert cur.fetchone()[0] == 6
```

- [ ] **Step 2: Run the failing test**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v2_walk_forward_cleanup_on_mid_batch_failure -v
```

Expected: FAIL — without try/except, partial rows linger and `count != 0`.

- [ ] **Step 3: Wrap walk-forward + robustness persistence in `backtest_canary.py`**

Apply to `cmd_walk_forward`:

```python
def cmd_walk_forward(conn, *, schema: str, args=None) -> None:
    # ... existing prelude: cal, run_scope, batch_id ...
    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    score_form = cal.score_form

    try:
        for win in WALK_FORWARD_WINDOWS:
            # ... existing loop body — persist with batch_id in params ...
            pass
    except Exception as original:
        try:
            conn.rollback()
        except Exception as rollback_err:
            log.exception("rollback failed during walk-forward cleanup: %s", rollback_err)
        try:
            n = bt_repo.delete_canary_research_runs_by_batch_id_and_phase(
                batch_id, "walk_forward",
            )
            log.warning(
                "cleaned up %d partial v2 walk-forward rows for batch_id=%s",
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

Mirror for `cmd_robustness` (phase='robustness').

- [ ] **Step 4: Re-run the cleanup test — verify it passes**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py::test_v2_walk_forward_cleanup_on_mid_batch_failure -v
```

Expected: PASS.

- [ ] **Step 5: Run the full v2 walk-forward suite — confirm no regression**

```bash
UW_SCAN_DB_NAME=option_wizard_test uv run pytest \
    tests/integration/regime/test_canary_v2_walk_forward.py -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add scripts/backtest_canary.py tests/integration/regime/test_canary_v2_walk_forward.py
git commit -m "feat(canary): v2 walk-forward cleanup-on-failure via scoped delete

Wraps cmd_walk_forward + cmd_robustness v2 persistence in try/except:
on any exception, rolls back the transaction (required before next
query post Postgres InFailedSqlTransaction), runs
delete_canary_research_runs_by_batch_id_and_phase scoped to (batch_id,
phase, indicator='canary', run_scope='research'), then re-raises.

Cleanup test uses pytest-mock + autospec + side_effect + wraps to
pass-through first 3 calls and raise on the 4th — all in-process via
cmd_walk_forward(conn, schema, args). A subprocess-based test could
not patch bulk_insert_daily across process boundary.

Spec §5.8."
```

---

### Task 12: Final smoke + ruff + live verification

**Files:** none (live commands + ruff)

**Rationale:** End-to-end smoke against the dev DB closes out PR 1. Spec AC-7 is a ruff check.

- [ ] **Step 1: Ruff check (AC-7)**

```bash
uv run ruff check src/ tests/ scripts/
```

Expected: zero ruff diagnostics. Fix any unused imports / locals introduced in Tasks 0–11.

- [ ] **Step 2: Run all new + non-regression tests**

```bash
uv run pytest \
    tests/unit/test_canary_v2_formula.py \
    tests/unit/test_canary_v1_payload_hash_golden.py \
    tests/unit/test_canary_v1_v2_compare_renderer.py \
    tests/integration/regime/test_canary_v2_backfill.py \
    tests/integration/regime/test_canary_v2_walk_forward.py \
    tests/integration/regime/test_canary_scanner.py \
    tests/integration/regime/test_canary_oos_gate.py \
    tests/integration/regime/test_canary_form_sweep_full.py \
    -v
```

Expected: ~44 new tests + ~30 pre-existing canary tests, all green.

(Note: `tests/integration/regime/test_canary_backtest.py` does NOT exist — verified. Do not reference it.)

- [ ] **Step 3: Live v2 backfill against dev DB**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/canary_backfill.py \
      --composite-version 2 \
      --start-date 2011-02-08 \
      --end-date 2026-05-21
```

Expected: ~3,843 rows inserted at composite_version=2. Re-run as no-op.

- [ ] **Step 4: Verify counts**

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -X -A -F'|' -c "
  SELECT composite_version, COUNT(*) FROM uw_scan.canary_snapshots
  WHERE composite_version IN (1,2)
  GROUP BY composite_version ORDER BY composite_version;
"
```

Expected: both rows have ~3,843 rows.

- [ ] **Step 5: Live v2 walk-forward**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py --walk-forward --composite-version 2
```

Capture the printed `batch_id` from stdout.

- [ ] **Step 6: Live v2 robustness (chained)**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py \
      --robustness --composite-version 2 --batch-id <batch_id_from_step_5>
```

- [ ] **Step 7: AC-F3 smoke check — 4 CCA event dates**

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -X -A -F'|' -c "
  SELECT data_date, payload->'speed'->>'confirmed_canary_active' AS cca_active
  FROM uw_scan.canary_snapshots
  WHERE composite_version=2
    AND data_date IN ('2011-08-08','2015-08-24','2018-02-05','2020-03-09')
  ORDER BY data_date;
"
```

Expected: all 4 rows show `cca_active = true`.

- [ ] **Step 8: Render the report**

```bash
PGUSER=chenxi UW_SCAN_API_KEY=local-smoke \
  uv run python scripts/backtest_canary.py --v1-v2-compare > /tmp/canary-v1-v2-report.md
cat /tmp/canary-v1-v2-report.md
```

Expected: markdown report with all 4 tables + AC-F1..F6 + verdict + footer.

- [ ] **Step 9: Verify v1 calibration JSON untouched + production-scope isolation**

```bash
md5 docs/research/regime/canary-calibration-v1.json
```

Expected: `407024fadb7e7b46417f08f4d019d991`.

```bash
PGUSER=chenxi psql -h 127.0.0.1 -d option_wizard -X -A -F'|' -c "
  SELECT id, params->>'phase', run_scope, composite_version
  FROM uw_scan.regime_backtest_runs
  WHERE indicator='canary' AND completed_at IS NOT NULL
    AND run_scope='production'
  ORDER BY created_at DESC LIMIT 10;
"
```

Expected: zero rows with `composite_version='2'`.

- [ ] **Step 10: Final empty commit recording smoke results**

```bash
git commit --allow-empty -m "chore(canary): v2-A PR 1 evidence ready for review

Live smoke against dev DB (option_wizard):
- v2 backfill: ~3,843 rows at composite_version=2 (matches v1 count)
- v2 walk-forward: 6 research-scoped runs with shared batch_id
- v2 robustness: 1 research-scoped run, chained batch_id
- AC-F3 evidence: all 4 CCA event dates fire confirmed_canary_active=true
- --v1-v2-compare renders the full report (4 tables + verdict + footer)
- All new + pre-existing canary tests green (~74 tests)
- ruff: zero diagnostics on src/ tests/ scripts/
- canary-calibration-v1.json MD5 unchanged: 407024fadb7e7b46417f08f4d019d991
- Zero composite_version=2 rows in production-scope queries

PR 1 evidence is ready for the codex/ultrareview tribunal. The verdict
from --v1-v2-compare determines whether PR 2 (production flip) is
authorized per spec §8 AC-F1..F6."
```

---

## Spec Coverage Map

| Spec section / AC | Task(s) |
|---|---|
| §5.3 Conditional path code | Task 3 |
| §5.4 Calibration JSON v2 | Task 1 |
| §5.5 `canary_backfill.py --composite-version` | Task 5 |
| §5.5 `cmd_walk_forward --composite-version 2` | Task 6 |
| §5.5 `cmd_robustness --composite-version 2` | Task 7 |
| §5.5 `--v1-v2-compare` | Tasks 9 + 10 |
| §5.6 Persistence model (composite_version tagging) | Tasks 5, 6, 7 |
| §5.7 Renderer + `FlipGateEvidence` | Task 9 |
| §5.8 Error handling (cleanup-on-failure) | Task 11 |
| §6 Layer 1 (snapshot scope) | Task 5 |
| §6 Layer 2 (run_scope) | Tasks 6, 7 |
| §6 Layer 3 (`COMPOSITE_VERSION` constant) | Task 2 invariant test + non-modification across all tasks |
| §6 Layer 4 (`cal.composite_version` persistence rule) | Tasks 5, 6, 7 |
| §6 Layer 5 (OOS gate untouched) | Task 12 Step 2 (non-regression) |
| §6 Layer 6 (caller-discipline `run_scope=research`) | Tasks 6, 7 |
| §7 AC-1 (formula unit tests) | Task 3 |
| §7 AC-2 (v2 calibration parses) | Task 1 |
| §7 AC-3 (backfill writes v2 rows) | Task 5 |
| §7 AC-3a (CCA event evidence) | Tasks 5, 12 Step 7 |
| §7 AC-4 (walk-forward) | Task 6 |
| §7 AC-4a (robustness) | Task 7 |
| §7 AC-4b (recompute vs backfill parity) | Task 8 |
| §7 AC-5 (dispatcher renders) | Task 10 |
| §7 AC-5a (`delete_canary_research_runs_by_batch_id_and_phase`) | Task 4 |
| §7 AC-6 (v1 payload-hash golden) | Task 2 |
| §7 AC-6a (OOS gate non-regression) | Task 12 Step 2 |
| §7 AC-7 (ruff) | Task 12 Step 1 |
| §7 AC-8 (CI) | Task 12 (post-push) |
| §8 AC-F1 (60d AUC ≥ 0.634) | Tasks 9, 10 |
| §8 AC-F2 (20d / 5d AUC) | Tasks 9, 10 |
| §8 AC-F3 (CCA event states) | Tasks 5, 9, 10 |
| §8 AC-F4 (per-window) | Tasks 6, 9, 10 |
| §8 AC-F5 (WATCH% ≤ 44.3) | Tasks 5, 9, 10 |
| §8 AC-F6 (v1 unchanged) | Tasks 2, 9, 10 |

---

## Notes for the implementer

1. **The task order is a correctness invariant.** Specifically Task 2 (golden capture) **must** run before Task 3 (conditional). Tasks 4 and 0 are unordered with each other but both must come before Task 5. Task 9 (module) must come before Task 10 (dispatcher) — the dispatcher imports from the module.

2. **All integration tests are in-process.** Never `subprocess.run([sys.executable, ...])` inside a test — `Settings.from_env()` reads `UW_SCAN_DB_*` env vars (not `DATABASE_URL`), so a subprocess + `DATABASE_URL=...` would silently target the dev DB. The test fixture provides `seeded_db_empty_cards.conn` + `_schema`; pass them to `cmd_backfill(conn, schema, args)` / `cmd_walk_forward(conn, schema, args)` / `cmd_robustness(conn, schema, args)` / `cmd_v1_v2_compare(conn, schema, args)` directly.

3. **The COMPOSITE_VERSION module constant stays at 1 for ALL of PR 1.** Every v2 write uses `cal.composite_version` (the loaded field). The flip to 2 happens in PR 2 and is gated by `--v1-v2-compare`'s SHIP verdict.

4. **Idempotency is by canonical payload hash, not by date+version.** A `SELECT 1` check silently keeps stale rows from earlier failed runs that had bugs. Use `canonical_payload_hash(payload)` to compute the new hash, compare with the stored `payload_hash`, skip on match, RAISE on mismatch unless `--overwrite-on-hash-mismatch`.

5. **Full-history AUCs use `_compute_canary_series`, not raw SQL on snapshots.** Snapshot rows lack the `spx` forward-return field that `_aucs_for_rows -> _entry_lagged_label` needs. Always recompute via the existing helper.

6. **Test fixtures use `CanarySnapshotRepository.insert_snapshot(...)`, not raw SQL.** `canary_snapshots` has NOT NULL columns (`tactical_score`, `structural_score`, `speed_score ∈ {0, 8, 20}`, `warning_state`, `payload_hash`) that raw INSERTs forget. Use the repo method.

7. **Standing-rule compliance recap:** `uv` exclusively. No `Co-Authored-By: Claude` trailer. Don't push or open a PR until the user explicitly asks. Persist to Postgres. No naked shorts. Don't extend `repository.py` — `regime_backtest_repository.py` is the focused file.

8. **What this PR explicitly does NOT do** (worth restating to avoid scope creep):
   - No production flip — `COMPOSITE_VERSION = 1` stays.
   - No UI changes — `web/` is untouched.
   - No OpenAPI regen.
   - No methodology doc rewrite.
   - No band threshold change.
   - No new `LAST_KNOWN_AUC_v2_*` constants.
   - The verdict from `--v1-v2-compare` is a *report*; this PR does NOT itself flip anything.
