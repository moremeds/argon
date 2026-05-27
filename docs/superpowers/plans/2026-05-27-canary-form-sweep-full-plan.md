# Canary Full-History Form-Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--form-sweep-full` subcommand that runs all 4 score forms (`linear`, `convex`, `concave`, `sigmoid`) against the full backfilled `canary_snapshots` dataset (2011-02-08 → present), persists 4 rows tagged with `run_scope='research'` and a shared `batch_id` to `regime_backtest_runs` (with `is_winning_form=False` hardcoded + cleanup-on-failure), and prints a 4-form comparison table via a new pure-function renderer.

**Architecture:** New CLI subcommand in `scripts/backtest_canary.py`, a focused command implementation in `src/uw_scan/reports/regime_canary_form_sweep_full.py`, and a pure-function renderer in `src/uw_scan/reports/regime_canary_backtest_report.py`. `scripts/backtest_canary.py` is already >1,000 lines, so this plan intentionally does **not** add the command body there; it adds only argparse wiring plus a thin wrapper that passes existing helper functions (`_compute_canary_series`, `_aucs_for_rows`, `_band_counts`, `_block_bootstrap_auc_ci`, `_clean_nans`, `_entry_lagged_label`, `_auc`, `LABEL_SPECS`, `COMPOSITE_VERSION`) into the focused module. Adds one new repository method (`delete_runs_by_batch_id`) for cleanup-on-failure. No changes to `cmd_form_sweep`, `cmd_walk_forward`, `cmd_robustness`, the OOS gate, the calibration JSON, or any API/UI surface.

**Tech Stack:** Python 3.13 + uv (runtime), psycopg 3 (DB), pytest + pytest-postgresql (tests), Postgres 15 (uw_scan schema, migrations 057 + 059).

**Prerequisites before starting:**
1. Read the spec: `docs/superpowers/specs/2026-05-27-canary-form-sweep-full-design.md` (especially §4.2 for persistence shape, §4.4 for guardrails, §5 for ACs).
2. Set up an isolated workspace via the `superpowers:using-git-worktrees` skill — branch name suggestion: `feat/canary-form-sweep-full`.
3. Run a baseline `uv run pytest tests/unit/ tests/integration/regime/ -x` to confirm the worktree starts green. If anything fails, stop and investigate before touching code.

---

## File Structure

**Files to create:**

| Path | Responsibility |
|---|---|
| `tests/integration/regime/_canary_form_sweep_fixture.py` | Synthetic vol-complex fixture (600 days × {VIX, VVIX, VIX3M, COR1M, SPX}) seeded into `vol_index_daily` + 200 days seeded into `canary_snapshots`. Sized so `_entry_lagged_label(..., 60, ...)` yields ≥140 finite 60d AUC labels. Shared by all integration tests in this PR. |
| `tests/unit/test_within_band_aucs.py` | 5 unit tests for `_within_band_aucs` (no DB). |
| `tests/unit/test_canary_form_sweep_renderer.py` | 15 unit tests for `render_canary_form_sweep_compare` (no DB) — covers all 7 observation rules plus the `none` fallback. |
| `tests/unit/test_canary_form_sweep_cli.py` | 1 unit test for the custom `--form-sweep-full` mutual-exclusion guard (no DB). |
| `tests/integration/regime/test_canary_form_sweep_full.py` | 14 integration tests covering: repository batch delete (3 — basic / no-op / scope-correctness), wrapper persistence smoke (5 — batch_id sharing, daily-row n_days equality, summary schema, capsys stdout assertion, compute-before-persist invariant), cleanup-on-failure with transaction rollback (1), latest-complete-batch / incomplete-batch skipping (2), and OOS-gate / validation-API / calibration-file invisibility (3). |
| `src/uw_scan/reports/regime_canary_form_sweep_full.py` | Focused command implementation + `_within_band_aucs`; receives existing `scripts/backtest_canary.py` helpers through explicit dependency injection so the package module does not import the script. |
| `src/uw_scan/reports/regime_canary_backtest_report.py` | Pure-function renderer + module-private DB loader + `__main__` block. Mirrors the layout of `regime_backtest_report.py` (CRI) and `regime_vcg_backtest_report.py` (VCG). |

**Files to modify:**

| Path | What changes |
|---|---|
| `scripts/backtest_canary.py` | Add `--form-sweep-full` argparse flag, mutual-exclusion count-check at top of `main()`, dispatch branch in `main()`, and a thin `cmd_form_sweep_full` wrapper (~15 LOC) that delegates to `regime_canary_form_sweep_full.py`. No edits to existing functions. |
| `src/uw_scan/storage/regime_backtest_repository.py` | Add `delete_runs_by_batch_id(batch_id: str) -> int` method (~15 LOC). |

**Files NOT touched** (would-be drift if changed; abort task if you find yourself editing these):
- `canary-calibration-v1.json`
- `src/uw_scan/scanners/canary.py`
- `src/uw_scan/cards/canary_scoring.py`
- `src/uw_scan/cards/canary_calibration.py`
- `src/uw_scan/api/routers/regime.py`
- `tests/integration/regime/test_canary_oos_gate.py`
- `web/**` (no UI changes)
- Any migration file

---

## Task 1: Synthetic vol-complex fixture for integration tests

**Files:**
- Create: `tests/integration/regime/_canary_form_sweep_fixture.py`

This fixture seeds 600 days × 5 symbols of synthetic-but-coherent vol-complex data into `vol_index_daily` and 200 days into `canary_snapshots`. Required by every integration test in this PR.

**Sizing rationale:** the form-sweep-full computes `_entry_lagged_label(rows, 60, ...)` for the 60d AUC. With only 50 snapshots, all 60d labels collapse to `None` (no row at `i+60`), which then breaks the renderer's `:.3f` formatting. We need ≥120 evaluable canary-series rows; that requires a snapshot window ≥120 days, which in turn requires vol_index ≥ 350 (MIN_ALIGNED_BARS warm-up) + 120 = 470 days minimum. Sizing to 600 + 200 leaves comfortable headroom for 60d/20d/5d horizons (200 - 60 = 140 finite 60d labels).

Coherence rule: prices and ratios are bounded (VIX ∈ [10, 50], VVIX ∈ [70, 130], VIX3M ≈ VIX × 1.05, SPX random-walk from 1000 base, COR1M ∈ [30, 70]). No actual signal patterns — just enough to make the scoring pipeline run end-to-end without raising.

- [ ] **Step 1: Write the fixture file**

```python
# tests/integration/regime/_canary_form_sweep_fixture.py
"""Synthetic vol-complex fixture for canary form-sweep-full integration tests.

Seeds 600 trading days × 5 symbols into vol_index_daily (enough to clear the
350-bar MIN_ALIGNED_BARS warm-up with ~250 bars beyond) plus 200 days into
canary_snapshots so the MIN/MAX(data_date) window supports 60d forward labels
(60d AUC requires at least 60 buffer rows past the eval region).

Coherent but not realistic — designed to make the scoring pipeline run
without raising, NOT to produce meaningful AUC values. Tests in this PR
assert SHAPE (4 rows, batch_id present, etc.), not numeric correctness.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np


def _trading_days(start: date, n: int) -> list[date]:
    """n consecutive Mon-Fri days starting from `start` (skip Sat/Sun)."""
    out: list[date] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def seed_vol_index(conn, *, schema: str, n_days: int = 600) -> list[date]:
    """Insert n_days × {VIX, VVIX, VIX3M, COR1M, SPX} into vol_index_daily.

    Default is 600 (≥ 350 warm-up + ≥ 200 evaluable). Returns the list of
    trading dates (oldest first).
    """
    rng = np.random.default_rng(seed=42)
    dates = _trading_days(date(2010, 1, 4), n_days)

    spx = 1000.0 * np.cumprod(1 + rng.normal(0.0003, 0.01, n_days))
    vix = np.clip(15 + 5 * rng.standard_normal(n_days), 10, 50)
    vvix = np.clip(95 + 10 * rng.standard_normal(n_days), 70, 130)
    vix3m = vix * 1.05 + rng.normal(0, 0.5, n_days)
    cor1m = np.clip(50 + 8 * rng.standard_normal(n_days), 30, 70)

    rows = []
    for i, d in enumerate(dates):
        for sym, arr in (("SPX", spx), ("VIX", vix), ("VVIX", vvix),
                         ("VIX3M", vix3m), ("COR1M", cor1m)):
            rows.append((sym, d, Decimal(str(round(float(arr[i]), 4)))))

    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {schema}.vol_index_daily "
            "(symbol, trade_date, close) VALUES (%s, %s, %s) "
            "ON CONFLICT (symbol, trade_date) DO NOTHING",
            rows,
        )
    conn.commit()
    return dates


def seed_canary_snapshots(conn, *, schema: str, dates: list[date],
                          n_snapshots: int = 200) -> tuple[date, date]:
    """Insert n_snapshots synthetic canary_snapshots rows.

    Default is 200 so that the form-sweep-full's 60d AUC labels are finite
    (200 - 60 = 140 evaluable rows per band). Uses the LAST n_snapshots from
    `dates` (i.e. the most recent slice). Returns (min_date, max_date).
    """
    seed_dates = dates[-n_snapshots:]
    rows = []
    for d in seed_dates:
        rows.append((
            d,
            1,                  # composite_version
            "linear",           # score_form
            Decimal("20.0"),    # score
            Decimal("20.0"),    # raw_score
            "NONE",             # band
            Decimal("5.0"),     # tactical_score
            Decimal("10.0"),    # structural_score
            0,                  # speed_score (constraint allows 0, 8, or 20)
            "NONE",             # warning_state
            "abc123",           # payload_hash (any string)
            '{"inputs": {"spx_close": 1500.0}}',  # payload JSONB
        ))
    with conn.cursor() as cur:
        cur.executemany(
            f"INSERT INTO {schema}.canary_snapshots "
            "(data_date, composite_version, score_form, score, raw_score, "
            " band, tactical_score, structural_score, speed_score, "
            " warning_state, payload_hash, payload) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
            "ON CONFLICT (data_date, composite_version) DO NOTHING",
            rows,
        )
    conn.commit()
    return (seed_dates[0], seed_dates[-1])
```

- [ ] **Step 2: Verify import path resolves**

Run: `uv run python -c "from tests.integration.regime._canary_form_sweep_fixture import seed_vol_index, seed_canary_snapshots; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Milestone checkpoint**

```bash
git add tests/integration/regime/_canary_form_sweep_fixture.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 2: `_within_band_aucs` helper + unit tests

**Files:**
- Create/modify: `src/uw_scan/reports/regime_canary_form_sweep_full.py` (add helper near the focused command implementation)
- Create: `tests/unit/test_within_band_aucs.py`

This helper computes the within-band AUC pattern from `cmd_robustness`'s `_auc_for_indices` (line ~979) but as a reusable function. Critical invariant: labels are computed once over the full series, then filtered by band — NOT computed per-subset (the latter drops the last 60 days from every subset, which was the v1 robustness bug).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_within_band_aucs.py
"""Unit tests for _within_band_aucs."""

import math

import pytest

from scripts import backtest_canary as canary_backtest
from uw_scan.reports.regime_canary_form_sweep_full import (
    CanaryFormSweepDeps,
    _within_band_aucs as _impl_within_band_aucs,
)


def _deps() -> CanaryFormSweepDeps:
    return CanaryFormSweepDeps(
        compute_canary_series=canary_backtest._compute_canary_series,
        aucs_for_rows=canary_backtest._aucs_for_rows,
        band_counts=canary_backtest._band_counts,
        block_bootstrap_auc_ci=canary_backtest._block_bootstrap_auc_ci,
        clean_nans=canary_backtest._clean_nans,
        entry_lagged_label=canary_backtest._entry_lagged_label,
        auc=canary_backtest._auc,
        label_specs=canary_backtest.LABEL_SPECS,
        composite_version=canary_backtest.COMPOSITE_VERSION,
    )


def _within_band_aucs(rows: list[dict]) -> dict[str, dict[str, float]]:
    return _impl_within_band_aucs(rows, _deps())


def _row(score: float, band: str, spx: float, date_str: str = "2020-01-01") -> dict:
    """Minimal row shape for the helper. Only fields actually read."""
    from datetime import date
    return {"score": score, "band": band, "spx": spx, "date": date.fromisoformat(date_str)}


def _date_str(offset: int) -> str:
    from datetime import date, timedelta
    return (date(2020, 1, 1) + timedelta(days=offset)).isoformat()


def test_empty_rows_returns_empty():
    out = _within_band_aucs([])
    assert out == {"NONE": {}, "WATCH": {}, "BUY": {}, "STRONG_BUY": {}}


def test_band_with_no_rows_returns_nan():
    # All rows in NONE band — WATCH/BUY/STRONG_BUY should return NaN per horizon.
    rows = [_row(10, "NONE", 100.0 + i, _date_str(i)) for i in range(80)]
    out = _within_band_aucs(rows)
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert math.isnan(out["WATCH"][h])
        assert math.isnan(out["BUY"][h])


def test_all_same_label_returns_nan():
    # Construct so forward labels are all 0 (no >2% moves) — AUC is undefined.
    rows = [_row(50, "BUY", 100.0, _date_str(i)) for i in range(80)]
    out = _within_band_aucs(rows)
    # BUY band's AUCs all NaN because positive class is empty.
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert math.isnan(out["BUY"][h])


def test_normal_case_matches_filtered_auc():
    """Normal: 3 bands populated, labels computed once over full series."""
    from scripts.backtest_canary import _auc, _entry_lagged_label, LABEL_SPECS
    rng = __import__("numpy").random.default_rng(seed=1)
    n = 100
    bands = ["NONE"] * 40 + ["WATCH"] * 40 + ["BUY"] * 20
    rng.shuffle(bands)
    spx_path = 100.0 + __import__("numpy").cumsum(rng.normal(0.001, 0.01, n))
    rows = [_row(float(i + rng.standard_normal()), bands[i], float(spx_path[i]),
                 _date_str(i)) for i in range(n)]
    out = _within_band_aucs(rows)
    # Recompute reference per-band by hand and confirm equality.
    for band in ("NONE", "WATCH", "BUY"):
        idxs = [i for i, r in enumerate(rows) if r["band"] == band]
        for name, h, thr in LABEL_SPECS:
            labels_full = _entry_lagged_label(rows, h, thr)
            band_scores = [rows[i]["score"] for i in idxs]
            band_labels = [labels_full[i] for i in idxs]
            expected = _auc(band_scores, band_labels)
            actual = out[band][name]
            if math.isnan(expected):
                assert math.isnan(actual)
            else:
                assert abs(actual - expected) < 1e-9


def test_labels_computed_once_not_per_subset():
    """The last 60 rows should not silently vanish from each band's AUC.

    If we computed labels per-subset, slicing rows[band==X] then calling
    _entry_lagged_label would drop the last 60 of THAT subset (not the
    last 60 of the full series). The helper must NOT do that.
    """
    n = 200
    # Half NONE, half BUY, alternating.
    rows = [_row(10 + i, "NONE" if i % 2 == 0 else "BUY", 100.0 + i,
                 _date_str(i)) for i in range(n)]
    out = _within_band_aucs(rows)
    # Every band should have non-NaN AUCs (since labels are computed once
    # over the full 200-row series, BOTH bands have plenty of labeled rows).
    for h in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
        assert not math.isnan(out["NONE"][h]), f"NONE[{h}] should be finite"
        assert not math.isnan(out["BUY"][h]), f"BUY[{h}] should be finite"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_within_band_aucs.py -v`
Expected: ImportError on `_within_band_aucs` — function not yet defined.

- [ ] **Step 3: Implement `_within_band_aucs` in `regime_canary_form_sweep_full.py`**

Place this function near `run_form_sweep_full` in `src/uw_scan/reports/regime_canary_form_sweep_full.py`:

```python
def _within_band_aucs(rows: list[dict], deps: CanaryFormSweepDeps) -> dict[str, dict[str, float]]:
    """AUC of composite score vs forward labels, restricted to each band.

    Labels are computed ONCE over the full row series (so the last 60 days
    don't drop out of every band-subset), then filtered by band membership.
    Returns NaN for bands with <2 distinct labels in the subset.

    This preserves the "compute labels once, filter by index" invariant
    from cmd_robustness — see _auc_for_indices around line 979.
    """
    out: dict[str, dict[str, float]] = {b: {} for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")}
    if not rows:
        return out
    composite_scores = [r["score"] for r in rows]
    for name, h, thr in deps.label_specs:
        labels_full = deps.entry_lagged_label(rows, h, thr)
        for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
            idxs = [i for i, r in enumerate(rows) if r["band"] == band]
            band_scores = [composite_scores[i] for i in idxs]
            band_labels = [labels_full[i] for i in idxs]
            out[band][name] = deps.auc(band_scores, band_labels)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_within_band_aucs.py -v`
Expected: 5 passed.

- [ ] **Step 5: Milestone checkpoint**

```bash
git add src/uw_scan/reports/regime_canary_form_sweep_full.py tests/unit/test_within_band_aucs.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 3: `delete_runs_by_batch_id` repository method

**Files:**
- Modify: `src/uw_scan/storage/regime_backtest_repository.py`
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py` (create file with the first integration test)

Cleanup-on-failure needs a way to remove all rows tagged with a given `batch_id`. The method does a `DELETE FROM regime_backtest_runs` scoped to **exactly the rows this command writes** (`indicator='canary'`, `run_scope='research'`, `params->>'phase'='form_sweep_full'`, and the matching `batch_id`). The scoping is defense against UUID4 collisions across indicators/phases — extraordinarily unlikely, but the cost of being explicit is one extra WHERE clause and the benefit is a deletion contract you can actually reason about ("this method only deletes form_sweep_full research runs for canary"). The migration 057 schema has `ON DELETE CASCADE` for `regime_backtest_daily.run_id → regime_backtest_runs.id`, so daily rows are cleaned up automatically.

- [ ] **Step 1: Verify CASCADE behavior in migration**

Run: `grep -A2 "CONSTRAINT.*run_id\|REFERENCES.*regime_backtest_runs" $(find . -path ./node_modules -prune -o -name "057_*.sql" -print 2>/dev/null) | head -10`
Expected output contains `ON DELETE CASCADE`. If it does NOT, abort and surface to the user — the spec assumes CASCADE; without it the cleanup helper needs an explicit `DELETE FROM regime_backtest_daily WHERE run_id IN (...)` first.

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/regime/test_canary_form_sweep_full.py
"""Integration tests for canary --form-sweep-full and its renderer.

All tests use the synthetic vol-complex fixture in
_canary_form_sweep_fixture.py and the project's pytest-postgresql fixture
(real Postgres, migrations applied per tests/conftest.py).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest


def test_delete_runs_by_batch_id_removes_rows_and_cascades_daily(
    seeded_db_empty_cards,
):
    """Insert a 4-row form_sweep_full batch + daily rows, then delete
    by batch_id. All runs AND daily rows must be gone."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    batch_id = str(uuid.uuid4())

    inserted_run_ids: list[int] = []
    for form in ("linear", "convex", "concave", "sigmoid"):
        run_id = repo.insert_run(
            indicator="canary",
            composite_version="1",
            start_date=date(2011, 2, 8),
            end_date=date(2026, 5, 21),
            window_days=350,
            n_days=100,
            params={"score_form": form, "phase": "form_sweep_full",
                    "batch_id": batch_id, "purpose": "candidate_discovery_not_validation"},
            summary={"is_winning_form": False, "score_form": form,
                     "batch_id": batch_id, "phase": "form_sweep_full"},
            run_scope="research",
        )
        inserted_run_ids.append(run_id)
        repo.bulk_insert_daily(run_id, [
            {"trade_date": date(2024, 1, 2), "score": 20.0, "level": "NONE",
             "payload": {"raw_score": 20.0}},
        ])

    # Verify rows exist
    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s", (batch_id,))
        assert cur.fetchone()[0] == 4
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily "
            f"WHERE run_id = ANY(%s)", (inserted_run_ids,))
        assert cur.fetchone()[0] == 4

    # Delete by batch_id
    n_deleted = repo.delete_runs_by_batch_id(batch_id)
    assert n_deleted == 4

    # Verify rows are gone (runs AND daily via CASCADE)
    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s", (batch_id,))
        assert cur.fetchone()[0] == 0
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily "
            f"WHERE run_id = ANY(%s)", (inserted_run_ids,))
        assert cur.fetchone()[0] == 0


def test_delete_runs_by_batch_id_returns_zero_when_no_match(seeded_db_empty_cards):
    """Calling with an unknown batch_id is a no-op returning 0."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    n = repo.delete_runs_by_batch_id("00000000-0000-0000-0000-000000000000")
    assert n == 0


def test_delete_runs_by_batch_id_scoped_to_canary_research_form_sweep_full(
    seeded_db_empty_cards,
):
    """A row with the same batch_id but a DIFFERENT indicator/scope/phase
    must NOT be deleted. Defends against UUID4 collisions and accidental
    over-scoping if the method is reused without thinking."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    batch_id = str(uuid.uuid4())

    # Three "lookalike" rows that share batch_id but each violates exactly
    # one of the three scope filters — none should be deleted.
    lookalikes = [
        # Wrong indicator
        dict(indicator="vcg", composite_version="1",
             start_date=date(2011, 2, 8), end_date=date(2026, 5, 21),
             window_days=350, n_days=10,
             params={"phase": "form_sweep_full", "batch_id": batch_id},
             summary={"phase": "form_sweep_full"}, run_scope="research"),
        # Wrong run_scope
        dict(indicator="canary", composite_version="1",
             start_date=date(2011, 2, 8), end_date=date(2026, 5, 21),
             window_days=350, n_days=10,
             params={"phase": "form_sweep_full", "batch_id": batch_id},
             summary={"phase": "form_sweep_full"}, run_scope="production"),
        # Wrong phase
        dict(indicator="canary", composite_version="1",
             start_date=date(2011, 2, 8), end_date=date(2026, 5, 21),
             window_days=350, n_days=10,
             params={"phase": "calibrate", "batch_id": batch_id},
             summary={"phase": "calibrate"}, run_scope="research"),
    ]
    lookalike_ids = [repo.insert_run(**spec) for spec in lookalikes]

    # One target row that matches all three scope filters — should be deleted.
    target_id = repo.insert_run(
        indicator="canary", composite_version="1",
        start_date=date(2011, 2, 8), end_date=date(2026, 5, 21),
        window_days=350, n_days=10,
        params={"score_form": "linear", "phase": "form_sweep_full",
                "batch_id": batch_id,
                "purpose": "candidate_discovery_not_validation"},
        summary={"is_winning_form": False, "score_form": "linear",
                 "batch_id": batch_id, "phase": "form_sweep_full"},
        run_scope="research",
    )

    n_deleted = repo.delete_runs_by_batch_id(batch_id)
    assert n_deleted == 1, "only the in-scope target row should be deleted"

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {db_schema}.regime_backtest_runs "
            f"WHERE id = ANY(%s)", (lookalike_ids,))
        remaining = [r[0] for r in cur.fetchall()]
        assert sorted(remaining) == sorted(lookalike_ids), \
            "lookalike rows must remain — scoping violation"
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE id = %s", (target_id,))
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v -k delete_runs`
Expected: AttributeError on `delete_runs_by_batch_id` — method not yet defined.

- [ ] **Step 4: Implement `delete_runs_by_batch_id` in repository**

Append to `src/uw_scan/storage/regime_backtest_repository.py` (after the last existing method, e.g. after `mark_run_completed`):

```python
    def delete_runs_by_batch_id(self, batch_id: str) -> int:
        """Delete canary form_sweep_full research runs with given batch_id.

        Scoped intentionally narrow — only `indicator='canary'`,
        `run_scope='research'`, `params->>'phase'='form_sweep_full'` rows
        are affected. This is the cleanup-on-failure path for
        `cmd_form_sweep_full`; it should never touch any other indicator,
        scope, or phase even on a UUID4 collision.

        Daily rows are removed by `ON DELETE CASCADE` (migration 057).
        Returns the number of run rows deleted (0 if no match).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.regime_backtest_runs "
                "WHERE indicator = 'canary' "
                "  AND run_scope = 'research' "
                "  AND params->>'phase' = 'form_sweep_full' "
                "  AND params->>'batch_id' = %s",
                (batch_id,),
            )
            deleted = cur.rowcount
        self._conn.commit()
        return deleted
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v -k delete_runs`
Expected: 3 passed (basic delete, no-op-on-unknown, scoped-to-canary-research-form-sweep-full).

- [ ] **Step 6: Milestone checkpoint**

```bash
git add src/uw_scan/storage/regime_backtest_repository.py tests/integration/regime/test_canary_form_sweep_full.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 4: `cmd_form_sweep_full` wrapper + focused core implementation + `--form-sweep-full` CLI flag

**Files:**
- Create: `src/uw_scan/reports/regime_canary_form_sweep_full.py` (focused command implementation)
- Modify: `scripts/backtest_canary.py` (add thin `cmd_form_sweep_full` wrapper, `--form-sweep-full` argparse flag, mutual-exclusion check, dispatch branch)
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py` (add 3 happy-path tests)
- Create: `tests/unit/test_canary_form_sweep_cli.py` (custom mutual-exclusion guard test)

This is the centerpiece. The focused implementation follows the "compute all in memory first, then persist with cleanup-on-failure" pattern from spec §4.2. `scripts/backtest_canary.py` stays thin because it is already past the repo's 1,000-line split threshold.

- [ ] **Step 1: Write the failing happy-path tests**

Append to `tests/integration/regime/test_canary_form_sweep_full.py`:

```python
def test_cmd_form_sweep_full_persists_4_rows_sharing_batch_id(seeded_db_empty_cards):
    """Run the script's wrapper. Assert: 4 research rows, same batch_id, same generated_at."""
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT params->>'batch_id', summary->>'generated_at', "
            f"       params->>'score_form', summary->>'is_winning_form', run_scope "
            f"FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full' "
            f"ORDER BY params->>'score_form'")
        rows = cur.fetchall()

    assert len(rows) == 4
    batch_ids = {r[0] for r in rows}
    gen_ats = {r[1] for r in rows}
    forms = {r[2] for r in rows}
    is_winning = {r[3] for r in rows}
    run_scopes = {r[4] for r in rows}
    assert len(batch_ids) == 1, f"all 4 rows must share batch_id, got {batch_ids}"
    assert len(gen_ats) == 1, f"all 4 rows must share generated_at, got {gen_ats}"
    assert forms == {"linear", "convex", "concave", "sigmoid"}
    assert is_winning == {"false"}, f"is_winning_form must be false for all, got {is_winning}"
    assert run_scopes == {"research"}, f"run_scope must be research for all, got {run_scopes}"


def test_cmd_form_sweep_full_writes_daily_rows(seeded_db_empty_cards):
    """Each form's run has exactly `n_days` corresponding regime_backtest_daily rows.

    The looser '> 0' check would pass on a buggy implementation that writes
    one daily row per form (e.g. only the first row of each form's series).
    Asserting equality to the run's `n_days` catches that.
    """
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        # Per-form: actual daily count == the run's declared n_days. The
        # n_days value is set by run_form_sweep_full to the size of the
        # computed eval series for that form, so this asserts the persistence
        # path materialises exactly the rows it claims it computed.
        cur.execute(
            f"SELECT r.params->>'score_form', r.n_days, COUNT(d.trade_date) "
            f"FROM {db_schema}.regime_backtest_runs r "
            f"LEFT JOIN {db_schema}.regime_backtest_daily d ON d.run_id = r.id "
            f"WHERE r.params->>'phase' = 'form_sweep_full' "
            f"GROUP BY r.params->>'score_form', r.n_days")
        rows = cur.fetchall()
    assert len(rows) == 4, f"expected 4 form rows, got {len(rows)}"
    seen_forms: set[str] = set()
    for form, n_days, daily_count in rows:
        seen_forms.add(form)
        assert n_days > 0, f"{form} run.n_days must be > 0, got {n_days}"
        assert daily_count == n_days, (
            f"{form}: daily-row count {daily_count} != run.n_days {n_days} "
            f"— persistence is not writing every computed eval row"
        )
    assert seen_forms == {"linear", "convex", "concave", "sigmoid"}


def test_cmd_form_sweep_full_summary_schema(seeded_db_empty_cards):
    """summary JSONB has all the spec-required keys."""
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT summary FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full' LIMIT 1")
        summary = cur.fetchone()[0]
    # Required top-level keys
    for key in ("is_winning_form", "score_form", "phase", "source",
                "batch_id", "generated_at", "n_days", "aucs", "auc_ci95",
                "band_distribution", "within_band_aucs", "vol_only_gap"):
        assert key in summary, f"summary missing key: {key}"
    # aucs has all 3 series × 3 horizons
    for series in ("composite", "vol_only", "speed_only"):
        assert series in summary["aucs"]
        for horizon in ("up5d_2pct", "up20d_5pct", "up60d_10pct"):
            assert horizon in summary["aucs"][series], \
                f"aucs.{series}.{horizon} missing"
    # band_distribution has all 4 bands
    for band in ("NONE", "WATCH", "BUY", "STRONG_BUY"):
        assert band in summary["band_distribution"]


def test_cmd_form_sweep_full_prints_renderer_output(seeded_db_empty_cards, capsys):
    """After persistence, the command must call the renderer and print its
    output to stdout. A buggy implementation that persists correctly but
    skips the print would otherwise pass every DB-only test.

    Asserts: the canonical header row, all four form labels, the
    Observations section header, and the "What this run does NOT decide"
    footer all appear in stdout.
    """
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    cmd_form_sweep_full(db_conn, schema=db_schema)

    captured = capsys.readouterr()
    stdout = captured.out
    # Header: at least the four canonical form labels appear in stdout, in order.
    for form in ("linear", "convex", "concave", "sigmoid"):
        assert form in stdout, f"renderer output missing form row '{form}'"
    li = stdout.index("linear")
    cv = stdout.index("convex")
    cc = stdout.index("concave")
    sg = stdout.index("sigmoid")
    assert li < cv < cc < sg, (
        f"form rows must appear in canonical order, got positions "
        f"linear={li}, convex={cv}, concave={cc}, sigmoid={sg}"
    )
    # Observations + footer must both appear.
    assert "Observations" in stdout, "renderer output missing Observations section"
    assert "What this run does NOT decide" in stdout, (
        "renderer footer missing — guardrail prose against misuse"
    )


def test_cmd_form_sweep_full_does_not_persist_when_compute_fails_mid_run(
    seeded_db_empty_cards, monkeypatch,
):
    """Compute-all-before-persist invariant (spec §4.2 / AC-13).

    Patches `deps.compute_canary_series` to raise on the *third* invocation
    (= third form). Asserts: zero `form_sweep_full` rows are persisted,
    proving the implementation does not interleave compute and persist.
    """
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full
    from uw_scan.reports import regime_canary_form_sweep_full as impl_mod

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    # Patch the deps factory the wrapper uses, so the patched function rides
    # through the DI dataclass.
    real_run = impl_mod.run_form_sweep_full
    call_count = {"compute": 0}

    def make_failing_run(conn, *, schema, deps):
        real_compute = deps.compute_canary_series

        def patched_compute(*args, **kwargs):
            call_count["compute"] += 1
            if call_count["compute"] == 3:
                raise RuntimeError(
                    "synthetic failure on form 3 — compute-before-persist test"
                )
            return real_compute(*args, **kwargs)

        from dataclasses import replace
        patched_deps = replace(deps, compute_canary_series=patched_compute)
        return real_run(conn, schema=schema, deps=patched_deps)

    monkeypatch.setattr(impl_mod, "run_form_sweep_full", make_failing_run)

    with pytest.raises(RuntimeError, match="synthetic failure on form 3"):
        cmd_form_sweep_full(db_conn, schema=db_schema)

    # Zero form_sweep_full rows must remain — proves the implementation
    # finished computing forms 1 and 2 in memory but did not write them
    # to the DB before form 3's compute failed. (Cleanup also covers
    # this, so the row count alone is necessary but not sufficient; the
    # call_count below proves compute reached form 3.)
    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full'"
        )
        assert cur.fetchone()[0] == 0, (
            "compute-before-persist violated: rows for forms 1/2 leaked "
            "into the DB before form 3's compute failed"
        )
    assert call_count["compute"] == 3, (
        f"expected compute to be called 3 times before failing, got {call_count['compute']}"
    )
```

Also create `tests/unit/test_canary_form_sweep_cli.py`:

```python
"""Unit tests for canary backtest CLI guardrails."""

from __future__ import annotations

import sys

import pytest

from scripts import backtest_canary


def test_form_sweep_full_is_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["backtest_canary.py", "--form-sweep", "--form-sweep-full"],
    )
    with pytest.raises(SystemExit) as exc:
        backtest_canary.main()
    assert exc.value.code == 2
    assert "only one of --calibrate" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_canary_form_sweep_cli.py tests/integration/regime/test_canary_form_sweep_full.py -v -k form_sweep_full`
Expected: failing tests until `--form-sweep-full`, the mutual-exclusion error, and `cmd_form_sweep_full` exist.

- [ ] **Step 3: Implement focused command module + thin script wrapper**

Create `src/uw_scan/reports/regime_canary_form_sweep_full.py`. It owns the full-history implementation and `_within_band_aucs`; it must not import `scripts.backtest_canary`. Instead, define a small dependency container and receive existing helpers from the script wrapper:

```python
@dataclass(frozen=True)
class CanaryFormSweepDeps:
    compute_canary_series: Callable[..., dict]
    aucs_for_rows: Callable[[list[dict]], dict[str, dict[str, float]]]
    band_counts: Callable[[list[dict]], dict[str, int]]
    block_bootstrap_auc_ci: Callable[..., tuple[float, float]]
    clean_nans: Callable[[Any], Any]
    entry_lagged_label: Callable[[list[dict], int, float], list]
    auc: Callable[[list[float], list], float]
    label_specs: list[tuple[str, int, float]]
    composite_version: int
```

The module exposes:

```python
def _within_band_aucs(rows: list[dict], deps: CanaryFormSweepDeps) -> dict[str, dict[str, float]]:
    """AUC of composite score vs forward labels, restricted to each band.

    Labels are computed once over the full row series, then filtered by band.
    Returns NaN for bands with <2 distinct labels in the subset.
    """


def run_form_sweep_full(conn, *, schema: str, deps: CanaryFormSweepDeps) -> None:
    """Full-history score-form sweep against canary_snapshots range.

    Candidate discovery only. DO NOT:
      - declare a winning form
      - write to canary-calibration-v1.json
      - set summary.is_winning_form=True
      - read or modify the OOS gate's LAST_KNOWN_AUC_* constants
    """
```

Implementation requirements inside `run_form_sweep_full`:

- Load calibration with `load_calibration()`.
- Resolve `snap_min`, `snap_max`, and `snap_count` from `{schema}.canary_snapshots`.
- Compute all four forms in memory before persisting any row.
- Persist with `RegimeBacktestRepository.insert_run(..., run_scope="research")`; this argument is mandatory.
- Use params literals: `phase="form_sweep_full"`, `batch_id=<uuid4>`, `purpose="candidate_discovery_not_validation"`, `min_aligned_bars=350`, `window_semantics="warmup_requirement_not_eval_window"`.
- Use summary literals: `is_winning_form=False`, `phase="form_sweep_full"`, `source="form_sweep_full"`, shared `batch_id`, shared `generated_at`.
- Convert eval rows before `bulk_insert_daily`: `trade_date=r["date"]`, `score=r["score"]`, `level=r["band"]`, and payload keys `raw_score`, `tactical`, `structural`, `speed`, `warning_state`. Do not pass raw eval rows directly; `RegimeBacktestRepository.bulk_insert_daily` expects `trade_date`.
- On any exception during persistence, **preserve the original exception** and then attempt cleanup. The naive "cleanup then re-raise" pattern silently swaps the original failure for any failure that happens inside cleanup (the second `raise` shadows the first). Required shape (see Step 3 implementation block for the exact code):

  ```python
  except Exception as original:
      # Real Postgres errors leave the transaction in InFailedSqlTransaction;
      # rollback() must run BEFORE the DELETE, or the delete itself errors.
      try:
          conn.rollback()
      except Exception as rollback_err:
          # Best-effort. Log and continue so the original exception still wins.
          log.exception("rollback failed during form_sweep_full cleanup: %s", rollback_err)
      try:
          deps.repo.delete_runs_by_batch_id(batch_id)
      except Exception as cleanup_err:
          # Cleanup failure is logged but does NOT replace the original.
          log.exception(
              "delete_runs_by_batch_id(%s) failed during cleanup: %s",
              batch_id, cleanup_err,
          )
      raise original  # `raise` (bare) also preserves the original — both forms are valid.
  ```

  The intent: a partial-batch row in the DB is bad, but obscuring the root cause is worse — debugging a `ProgrammingError` from a fictional `definitely_missing_table` is much harder if you only see "delete_runs_by_batch_id failed because the transaction is aborted."
- After success, reload rows with `WHERE params->>'batch_id' = %s AND run_scope = 'research' AND completed_at IS NOT NULL`, assert exactly four rows, and print `render_canary_form_sweep_compare(run_dicts)`.

Then add only this wrapper to `scripts/backtest_canary.py` near `cmd_form_sweep`:

```python
def cmd_form_sweep_full(conn, *, schema: str) -> None:
    from uw_scan.reports.regime_canary_form_sweep_full import (
        CanaryFormSweepDeps,
        run_form_sweep_full,
    )

    deps = CanaryFormSweepDeps(
        compute_canary_series=_compute_canary_series,
        aucs_for_rows=_aucs_for_rows,
        band_counts=_band_counts,
        block_bootstrap_auc_ci=_block_bootstrap_auc_ci,
        clean_nans=_clean_nans,
        entry_lagged_label=_entry_lagged_label,
        auc=_auc,
        label_specs=LABEL_SPECS,
        composite_version=COMPOSITE_VERSION,
    )
    run_form_sweep_full(conn, schema=schema, deps=deps)
```

- [ ] **Step 4: Wire `--form-sweep-full` into argparse + main()**

Modify `scripts/backtest_canary.py` around lines 1070-1114. Find:

```python
def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--form-sweep", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="6-window expanding-train walk-forward (frozen v1 calibration)",
    )
    parser.add_argument(
        "--robustness",
        action="store_true",
        help="full-dataset robustness report (exclusion regimes, by-year, by-band)",
    )
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--form", choices=("linear", "convex", "concave", "sigmoid"))
    args = parser.parse_args()
```

Replace with:

```python
def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--form-sweep", action="store_true")
    parser.add_argument(
        "--form-sweep-full",
        action="store_true",
        help="candidate discovery: sweep all 4 forms against full canary_snapshots range",
    )
    parser.add_argument("--report", action="store_true")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="6-window expanding-train walk-forward (frozen v1 calibration)",
    )
    parser.add_argument(
        "--robustness",
        action="store_true",
        help="full-dataset robustness report (exclusion regimes, by-year, by-band)",
    )
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--form", choices=("linear", "convex", "concave", "sigmoid"))
    args = parser.parse_args()

    # CLI-level mutual exclusion (G-1) — argparse doesn't use a group here.
    mode_flags = [args.calibrate, args.form_sweep, args.form_sweep_full,
                  args.report, args.walk_forward, args.robustness]
    if sum(bool(f) for f in mode_flags) > 1:
        parser.error(
            "only one of --calibrate/--form-sweep/--form-sweep-full/--report/"
            "--walk-forward/--robustness may be specified"
        )

    if args.form_sweep_full and args.form is not None:
        log.warning("--form is ignored under --form-sweep-full (sweep iterates all 4 forms)")
```

Then add the dispatch branch to the existing `if/elif` chain in `main()` — insert AFTER the `--form-sweep` branch and BEFORE the `--report` branch:

```python
        if args.form_sweep:
            cmd_form_sweep(conn, write_summary=args.write_summary, schema=schema)
            return
        if args.form_sweep_full:
            cmd_form_sweep_full(conn, schema=schema)
            return
        if args.report:
            ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_canary_form_sweep_cli.py tests/integration/regime/test_canary_form_sweep_full.py -v -k form_sweep_full`
Expected: 6 passed (mutually_exclusive, persists_4_rows, writes_daily, summary_schema, prints_renderer_output, does_not_persist_when_compute_fails_mid_run). Plus the 3 delete tests from Task 3 still pass.

- [ ] **Step 6: Milestone checkpoint**

```bash
git add scripts/backtest_canary.py src/uw_scan/reports/regime_canary_form_sweep_full.py tests/unit/test_canary_form_sweep_cli.py tests/integration/regime/test_canary_form_sweep_full.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 5: Cleanup-on-failure test (atomicity guarantee — AC-13)

**Files:**
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py` (add atomicity test)

The command's `try/except` must clean up via `delete_runs_by_batch_id` on failure. This test asserts the invariant by monkey-patching `bulk_insert_daily` to trigger a real Postgres error on the third call, which leaves the transaction aborted unless the implementation calls `conn.rollback()` before cleanup.

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/regime/test_canary_form_sweep_full.py`:

```python
def test_form_sweep_full_cleanup_on_failure(seeded_db_empty_cards, monkeypatch):
    """Simulate a real DB failure on the 3rd form's bulk_insert_daily call.
    Assert: rollback happens and zero failed-batch rows remain afterwards."""
    from pathlib import Path
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    calib_path = Path(__file__).parents[3] / "docs/research/regime/canary-calibration-v1.json"
    before_calib_bytes = calib_path.read_bytes()
    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)

    real_bulk = RegimeBacktestRepository.bulk_insert_daily
    call_count = {"n": 0}

    def fail_on_third_call(self, run_id, rows):
        call_count["n"] += 1
        if call_count["n"] == 3:
            with self._conn.cursor() as cur:
                cur.execute("INSERT INTO definitely_missing_table VALUES (1)")
        return real_bulk(self, run_id, rows)

    monkeypatch.setattr(
        RegimeBacktestRepository, "bulk_insert_daily", fail_on_third_call
    )

    with pytest.raises(Exception):
        cmd_form_sweep_full(db_conn, schema=db_schema)

    # Assert: zero rows remain for ANY form_sweep_full batch (the only batch
    # was the failed one — cleanup must have removed it).
    with db_conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_runs "
            f"WHERE params->>'phase' = 'form_sweep_full'"
        )
        assert cur.fetchone()[0] == 0, \
            "cleanup-on-failure must remove all rows for failed batch_id"
        cur.execute(
            f"SELECT COUNT(*) FROM {db_schema}.regime_backtest_daily d "
            f"JOIN {db_schema}.regime_backtest_runs r ON d.run_id = r.id "
            f"WHERE r.params->>'phase' = 'form_sweep_full'"
        )
        assert cur.fetchone()[0] == 0, "daily rows must cascade-delete"
    assert calib_path.read_bytes() == before_calib_bytes, "calibration file changed on failure"
```

- [ ] **Step 2: Run test to verify it fails (or passes — depends on Task 4)**

Run: `uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v -k cleanup_on_failure`
Expected: PASS. If it fails with `InFailedSqlTransaction`, add `conn.rollback()` before `delete_runs_by_batch_id(batch_id)` in `run_form_sweep_full`.

- [ ] **Step 3: Milestone checkpoint**

```bash
git add tests/integration/regime/test_canary_form_sweep_full.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 6: `render_canary_form_sweep_compare` renderer + unit tests

**Files:**
- Create: `src/uw_scan/reports/regime_canary_backtest_report.py`
- Create: `tests/unit/test_canary_form_sweep_renderer.py`

Pure function. Takes 4 row dicts (each shaped like a `regime_backtest_runs` row), returns markdown string. Mirrors the layout of `regime_backtest_report.py` (CRI) and `regime_vcg_backtest_report.py` (VCG).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_canary_form_sweep_renderer.py
"""Unit tests for render_canary_form_sweep_compare."""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.reports.regime_canary_backtest_report import (
    render_canary_form_sweep_compare,
)


def _mk_run(*, run_id: int, form: str, batch_id: str = "batch-1",
            composite_60d: float = 0.620, vol_60d: float = 0.640,
            watch_pct: float = 39.3, buy_band_60d: float = 0.348,
            buy_pct: float = 5.5, strong_buy_pct: float = 0.0) -> dict:
    """Minimal row shape consumed by the renderer."""
    return {
        "id": run_id,
        "run_scope": "research",
        "start_date": date(2011, 2, 8),
        "end_date": date(2026, 5, 21),
        "composite_version": "1",
        "params": {"score_form": form, "phase": "form_sweep_full",
                   "batch_id": batch_id},
        "summary": {
            "is_winning_form": False,
            "score_form": form,
            "batch_id": batch_id,
            "n_days": 3843,
            "aucs": {
                "composite":  {"up5d_2pct": 0.620, "up20d_5pct": 0.627, "up60d_10pct": composite_60d},
                "vol_only":   {"up5d_2pct": 0.626, "up20d_5pct": 0.639, "up60d_10pct": vol_60d},
                "speed_only": {"up5d_2pct": 0.470, "up20d_5pct": 0.465, "up60d_10pct": 0.430},
            },
            "band_distribution": {
                "NONE": int(3843 * (1 - watch_pct/100 - buy_pct/100 - strong_buy_pct/100)),
                "WATCH": int(3843 * watch_pct/100),
                "BUY": int(3843 * buy_pct/100),
                "STRONG_BUY": int(3843 * strong_buy_pct/100),
            },
            "within_band_aucs": {
                "NONE":  {"up5d_2pct": 0.581, "up20d_5pct": 0.601, "up60d_10pct": 0.586},
                "WATCH": {"up5d_2pct": 0.559, "up20d_5pct": 0.633, "up60d_10pct": 0.609},
                "BUY":   {"up5d_2pct": 0.447, "up20d_5pct": 0.431, "up60d_10pct": buy_band_60d},
                "STRONG_BUY": {"up5d_2pct": None, "up20d_5pct": None, "up60d_10pct": None},
            },
            "vol_only_gap": {
                "up5d_2pct": 0.006, "up20d_5pct": 0.012,
                "up60d_10pct": vol_60d - composite_60d,
            },
        },
    }


def _full_set(batch_id: str = "batch-1") -> list[dict]:
    return [
        _mk_run(run_id=27, form="linear", batch_id=batch_id),
        _mk_run(run_id=28, form="convex", batch_id=batch_id),
        _mk_run(run_id=29, form="concave", batch_id=batch_id),
        _mk_run(run_id=30, form="sigmoid", batch_id=batch_id),
    ]


def test_canonical_form_ordering():
    """Output rows always: linear → convex → concave → sigmoid, regardless of input order."""
    runs = [_mk_run(run_id=i, form=f) for i, f in
            enumerate(("sigmoid", "concave", "linear", "convex"), start=100)]
    out = render_canary_form_sweep_compare(runs)
    li = out.index("| linear ")
    cv = out.index("| convex ")
    cc = out.index("| concave")
    sg = out.index("| sigmoid")
    assert li < cv < cc < sg, f"unexpected order: linear={li} convex={cv} concave={cc} sigmoid={sg}"


def test_missing_form_raises():
    """3 rows (sigmoid missing) — length check fires first with 'got 3'.

    The renderer validates length BEFORE form-set, so the error is the
    `need exactly 4 rows, got 3` message rather than a form-specific one.
    The form-set check (one canonical form replaced by a duplicate) is
    covered separately by `test_duplicate_form_raises`.
    """
    runs = _full_set()[:3]  # missing sigmoid
    with pytest.raises(ValueError, match=r"got 3"):
        render_canary_form_sweep_compare(runs)


def test_duplicate_form_raises():
    runs = _full_set()
    runs[1] = _mk_run(run_id=99, form="linear")  # 2 linears now
    with pytest.raises(ValueError, match="linear|duplicate"):
        render_canary_form_sweep_compare(runs)


def test_fewer_than_4_rows_raises():
    with pytest.raises(ValueError, match="4"):
        render_canary_form_sweep_compare(_full_set()[:2])


def test_mismatched_batch_id_raises():
    runs = _full_set("batch-1")
    runs[2] = _mk_run(run_id=99, form="concave", batch_id="batch-2")
    with pytest.raises(ValueError, match="batch_id"):
        render_canary_form_sweep_compare(runs)


def test_non_research_scope_raises():
    runs = _full_set()
    runs[0]["run_scope"] = "production"
    with pytest.raises(ValueError, match="research"):
        render_canary_form_sweep_compare(runs)


def test_footer_present():
    out = render_canary_form_sweep_compare(_full_set())
    assert "What this run does NOT decide" in out
    assert "candidate-discovery" in out.lower() or "candidate discovery" in out.lower()


def test_observation_watch_overfire():
    """WATCH% > 30 in linear (default fixture has 39.3) — should appear in observations."""
    out = render_canary_form_sweep_compare(_full_set())
    # Find the WATCH overfire line and verify linear is mentioned
    lines = [l for l in out.splitlines() if "WATCH% above 30%" in l]
    assert lines, "expected WATCH% above 30% observation line"
    assert "linear" in lines[0]


def test_observation_buy_band_inversion():
    """BUY-band 60d AUC < 0.50 in linear (default 0.348) — should appear."""
    out = render_canary_form_sweep_compare(_full_set())
    lines = [l for l in out.splitlines() if "BUY-band 60d AUC below 0.50" in l]
    assert lines
    assert "linear" in lines[0]


def test_observation_composite_improves_over_linear():
    """If convex 60d AUC > linear 60d by >=0.02, it should be listed."""
    runs = [
        _mk_run(run_id=27, form="linear", composite_60d=0.620),
        _mk_run(run_id=28, form="convex", composite_60d=0.650),  # +0.030
        _mk_run(run_id=29, form="concave", composite_60d=0.610),
        _mk_run(run_id=30, form="sigmoid", composite_60d=0.620),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [l for l in out.splitlines()
             if "Composite 60d AUC improves over linear" in l]
    assert lines
    assert "convex" in lines[0]
    # concave should NOT appear (it got worse)
    assert "concave" not in lines[0]


def test_observation_watch_reduce_without_auc_loss():
    """If sigmoid has WATCH%-5pp AND 60d AUC within 0.01 of linear, list it."""
    runs = [
        _mk_run(run_id=27, form="linear", watch_pct=39.3, composite_60d=0.620),
        _mk_run(run_id=28, form="convex", watch_pct=39.0, composite_60d=0.620),
        _mk_run(run_id=29, form="concave", watch_pct=39.5, composite_60d=0.620),
        _mk_run(run_id=30, form="sigmoid", watch_pct=33.0,  # -6.3pp
                composite_60d=0.615),  # -0.005 — within 0.01
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [l for l in out.splitlines()
             if "WATCH% reduced by" in l]
    assert lines
    assert "sigmoid" in lines[0]


def test_observation_vol_only_gap():
    """Vol-only gap ≥ +0.02 (= vol_only_60d - composite_60d ≥ 0.02): listed.

    Construct convex so that vol_only beats composite by >= 0.02 at the 60d
    horizon; the other three forms have neutral gap. Only `convex` should
    appear, and `none` should not be used.
    """
    runs = [
        _mk_run(run_id=27, form="linear",  composite_60d=0.620, vol_60d=0.625),
        _mk_run(run_id=28, form="convex",  composite_60d=0.620, vol_60d=0.650),  # gap +0.030
        _mk_run(run_id=29, form="concave", composite_60d=0.620, vol_60d=0.625),
        _mk_run(run_id=30, form="sigmoid", composite_60d=0.620, vol_60d=0.625),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [l for l in out.splitlines() if "Vol-only gap (60d) ≥ +0.02 in" in l]
    assert lines, "expected vol-only gap observation line"
    assert "convex" in lines[0]
    assert "linear" not in lines[0]
    assert "concave" not in lines[0]
    assert "sigmoid" not in lines[0]


def test_observation_buy_pct_zero():
    """BUY% at exactly 0 (band never fires): listed.

    Forms with `buy_pct=0` should match; forms with non-zero BUY% should not.
    Asserts the rule's truthiness AND that `linear` (buy_pct=5.5 in the
    default fixture) is NOT in the matching list.
    """
    runs = [
        _mk_run(run_id=27, form="linear",  buy_pct=5.5),
        _mk_run(run_id=28, form="convex",  buy_pct=0.0),  # band never fires
        _mk_run(run_id=29, form="concave", buy_pct=0.0),
        _mk_run(run_id=30, form="sigmoid", buy_pct=2.0),
    ]
    out = render_canary_form_sweep_compare(runs)
    lines = [l for l in out.splitlines()
             if "BUY% at exactly 0 (band never fires) in" in l]
    assert lines, "expected BUY%=0 observation line"
    assert "convex" in lines[0]
    assert "concave" in lines[0]
    assert "linear" not in lines[0]
    assert "sigmoid" not in lines[0]


def test_observation_strong_buy_pct_zero():
    """STRONG_BUY% at exactly 0: listed.

    Default fixture has STRONG_BUY%=0 for ALL forms, so the matching set
    should be all four forms (and `none` should NOT appear).
    """
    out = render_canary_form_sweep_compare(_full_set())
    lines = [l for l in out.splitlines()
             if "STRONG_BUY% at exactly 0 (band never fires) in" in l]
    assert lines, "expected STRONG_BUY%=0 observation line"
    # All four forms match because the default fixture has strong_buy_pct=0.
    for form in ("linear", "convex", "concave", "sigmoid"):
        assert form in lines[0], f"{form} missing from STRONG_BUY%=0 line"


def test_observation_none_when_no_form_matches():
    """Rule that has zero matches must print `none` (not an empty list)."""
    # All forms strictly below 30% WATCH AND above 0.50 BUY-band 60d AUC,
    # AND zero vol-only gap, AND non-zero BUY%, AND non-zero STRONG_BUY%
    # — none of the six per-form rules should trigger.
    runs = [
        _mk_run(run_id=27, form="linear",  watch_pct=25.0, buy_band_60d=0.60,
                composite_60d=0.620, vol_60d=0.620,
                buy_pct=5.0, strong_buy_pct=3.0),
        _mk_run(run_id=28, form="convex",  watch_pct=24.0, buy_band_60d=0.60,
                composite_60d=0.620, vol_60d=0.620,
                buy_pct=5.0, strong_buy_pct=3.0),
        _mk_run(run_id=29, form="concave", watch_pct=23.0, buy_band_60d=0.60,
                composite_60d=0.620, vol_60d=0.620,
                buy_pct=5.0, strong_buy_pct=3.0),
        _mk_run(run_id=30, form="sigmoid", watch_pct=22.0, buy_band_60d=0.60,
                composite_60d=0.620, vol_60d=0.620,
                buy_pct=5.0, strong_buy_pct=3.0),
    ]
    out = render_canary_form_sweep_compare(runs)
    # Every per-form rule line should end with "none".
    for label in (
        "WATCH% above 30% in",
        "BUY-band 60d AUC below 0.50 in",
        "Vol-only gap (60d) ≥ +0.02 in",
        "BUY% at exactly 0 (band never fires) in",
        "STRONG_BUY% at exactly 0 (band never fires) in",
    ):
        matching = [l for l in out.splitlines() if label in l]
        assert matching, f"missing observation line for: {label}"
        assert "none" in matching[0], (
            f"rule '{label}' should report 'none' when no form matches, "
            f"got: {matching[0]!r}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_canary_form_sweep_renderer.py -v`
Expected: ImportError — module not yet created.

- [ ] **Step 3: Implement the renderer module**

Create `src/uw_scan/reports/regime_canary_backtest_report.py`:

```python
"""Pure renderer: canary form_sweep_full runs -> markdown table.

Mirrors regime_backtest_report.py (CRI) and regime_vcg_backtest_report.py (VCG):
pure function, no I/O, no DB. The __main__ block at the bottom adds a CLI
entry point that DOES touch the DB (via a module-private loader).

This renderer's primary defense against misuse is the fixed
"What this run does NOT decide" footer — see spec
docs/superpowers/specs/2026-05-27-canary-form-sweep-full-design.md §4.3.
"""

from __future__ import annotations

import argparse
import sys
from io import StringIO
from typing import Any

import psycopg
from uw_scan.config import Settings

CANONICAL_FORMS = ("linear", "convex", "concave", "sigmoid")


def render_canary_form_sweep_compare(runs: list[dict]) -> str:
    """Render a 4-form comparison table from form_sweep_full runs.

    `runs` is a list of regime_backtest_runs row dicts, each with
    params.phase='form_sweep_full'. Caller is responsible for filtering
    and loading; this function does not touch the DB.

    Sort order in output: linear, convex, concave, sigmoid (canonical,
    not by id).

    Raises ValueError if:
      - fewer than 4 rows provided
      - any form is missing or duplicated
      - rows do not all share the same batch_id and composite_version
      - any row is not params.phase='form_sweep_full' or run_scope='research'
    """
    if len(runs) != 4:
        raise ValueError(f"need exactly 4 rows, got {len(runs)}")

    by_form: dict[str, dict] = {}
    for r in runs:
        if r.get("run_scope") != "research":
            raise ValueError(f"form_sweep_full rows must be research scoped, got {r.get('run_scope')!r}")
        if r["params"].get("phase") != "form_sweep_full":
            raise ValueError(f"expected params.phase=form_sweep_full, got {r['params'].get('phase')!r}")
        form = r["params"]["score_form"]
        if form not in CANONICAL_FORMS:
            raise ValueError(f"unknown score_form: {form}")
        if form in by_form:
            raise ValueError(f"duplicate score_form: {form}")
        by_form[form] = r

    for form in CANONICAL_FORMS:
        if form not in by_form:
            raise ValueError(f"missing score_form: {form}")

    batch_ids = {r["params"]["batch_id"] for r in runs}
    if len(batch_ids) != 1:
        raise ValueError(f"all rows must share batch_id, got {batch_ids}")
    composite_versions = {str(r["composite_version"]) for r in runs}
    if len(composite_versions) != 1:
        raise ValueError(f"all rows must share composite_version, got {composite_versions}")

    sample = by_form["linear"]
    out = StringIO()
    out.write("# Canary form-sweep — candidate discovery\n")
    out.write(f"Window: {sample['start_date'].isoformat()} → "
              f"{sample['end_date'].isoformat()} "
              f"({sample['summary']['n_days']:,} days)\n")
    out.write(f"Composite version: {sample['composite_version']}\n")
    out.write(f"Batch id: {next(iter(batch_ids))}\n")
    out.write(f"Run ids: {', '.join(str(by_form[f]['id']) for f in CANONICAL_FORMS)}\n")
    out.write("\n")

    out.write(
        "| Form    | AUC 5d | AUC 20d | AUC 60d | NONE% | WATCH% | BUY% | "
        "STRONG_BUY% | BUY-band 60d AUC | Vol-only gap (60d) |\n"
    )
    out.write(
        "|---------|-------:|--------:|--------:|------:|-------:|-----:|"
        "------------:|-----------------:|-------------------:|\n"
    )
    for form in CANONICAL_FORMS:
        s = by_form[form]["summary"]
        n = s["n_days"]
        bd = s["band_distribution"]
        pct = lambda x: 100.0 * bd[x] / n if n else 0.0  # noqa: E731
        wb = s["within_band_aucs"]["BUY"].get("up60d_10pct")
        buy_band_str = f"{wb:.3f}" if wb is not None else "  nan"
        gap = s["vol_only_gap"]["up60d_10pct"]
        gap_str = ("+" if gap >= 0 else "") + f"{gap:.3f}"
        out.write(
            f"| {form:<7} | {s['aucs']['composite']['up5d_2pct']:>6.3f} | "
            f"{s['aucs']['composite']['up20d_5pct']:>7.3f} | "
            f"{s['aucs']['composite']['up60d_10pct']:>7.3f} | "
            f"{pct('NONE'):>5.1f} | {pct('WATCH'):>6.1f} | "
            f"{pct('BUY'):>4.1f} | {pct('STRONG_BUY'):>11.1f} | "
            f"{buy_band_str:>16} | {gap_str:>18} |\n"
        )
    out.write("\n")

    out.write("## Observations\n\n")
    linear_summary = by_form["linear"]["summary"]

    def forms_where(predicate) -> str:
        matched = [f for f in CANONICAL_FORMS if predicate(by_form[f]["summary"])]
        return ", ".join(matched) if matched else "none"

    rules = [
        ("WATCH% above 30% in",
         lambda s: 100.0 * s["band_distribution"]["WATCH"] / s["n_days"] > 30.0,
         "  (over-broad WATCH band)"),
        ("BUY-band 60d AUC below 0.50 in",
         lambda s: (s["within_band_aucs"]["BUY"].get("up60d_10pct") is not None
                    and s["within_band_aucs"]["BUY"]["up60d_10pct"] < 0.50),
         "  (regression-to-mean signature)"),
        ("Vol-only gap (60d) ≥ +0.02 in",
         lambda s: s["vol_only_gap"]["up60d_10pct"] >= 0.02,
         "  (speed layer net-negative for rank)"),
        ("BUY% at exactly 0 (band never fires) in",
         lambda s: s["band_distribution"]["BUY"] == 0,
         ""),
        ("STRONG_BUY% at exactly 0 (band never fires) in",
         lambda s: s["band_distribution"]["STRONG_BUY"] == 0,
         ""),
        ("Composite 60d AUC improves over linear by ≥ +0.02 in",
         lambda s: (s["score_form"] != "linear"
                    and s["aucs"]["composite"]["up60d_10pct"]
                        - linear_summary["aucs"]["composite"]["up60d_10pct"] >= 0.02),
         "  (deserves v2-C planning)"),
        ("WATCH% reduced by ≥ 5 percentage points vs linear "
         "AND 60d AUC does not fall by more than 0.01 in",
         lambda s: (s["score_form"] != "linear"
                    and (100.0 * linear_summary["band_distribution"]["WATCH"]
                         / linear_summary["n_days"]
                         - 100.0 * s["band_distribution"]["WATCH"] / s["n_days"]) >= 5.0
                    and (linear_summary["aucs"]["composite"]["up60d_10pct"]
                         - s["aucs"]["composite"]["up60d_10pct"]) <= 0.01),
         "  (practical v2-C candidate)"),
    ]
    for label, predicate, suffix in rules:
        out.write(f"- {label}: {forms_where(predicate)}{suffix}\n")
    out.write("\n")

    out.write("## What this run does NOT decide\n\n")
    out.write(
        "This is candidate-discovery output. No form is declared "
        '"winning". Any v2 calibration change must reserve a fresh '
        "holdout window for OOS validation.\n"
    )
    return out.getvalue()


# ----------------------------------------------------------------------
# CLI entry point — DOES touch DB. Module-private loader pulls 4 rows.
# ----------------------------------------------------------------------

def _load_latest_complete_batch(conn, schema: str) -> list[dict]:
    """Load 4 rows from the most-recent complete form_sweep_full batch.

    "Complete" = exactly 4 rows AND covers all four CANONICAL_FORMS.
    Incomplete batches are skipped.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked_batches AS (
              SELECT params->>'batch_id' AS batch_id,
                     MAX(created_at) AS latest,
                     COUNT(*) AS n_rows,
                     array_agg(params->>'score_form' ORDER BY params->>'score_form')
                       AS forms
              FROM {schema}.regime_backtest_runs
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
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("no complete form_sweep_full batch found")
        batch_id = row[0]
        # Repeat the same scope filters used to select the batch. Without
        # `indicator='canary'` and `params->>'phase'='form_sweep_full'`, a
        # row from a different indicator or phase sharing this batch_id
        # (UUID4 collision) could leak in and break the renderer's
        # CANONICAL_FORMS validation in a confusing way.
        cur.execute(
            f"SELECT id, params, summary, start_date, end_date, composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE params->>'batch_id' = %s "
            f"AND indicator = 'canary' "
            f"AND run_scope = 'research' "
            f"AND completed_at IS NOT NULL "
            f"AND params->>'phase' = 'form_sweep_full' "
            f"ORDER BY params->>'score_form'",
            (batch_id,),
        )
        return [
            {"id": r[0], "params": r[1], "summary": r[2],
             "start_date": r[3], "end_date": r[4], "composite_version": r[5],
             "run_scope": r[6]}
            for r in cur.fetchall()
        ]


def _load_specific_runs(conn, schema: str, run_ids: list[int]) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, params, summary, start_date, end_date, composite_version, run_scope "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE id = ANY(%s) "
            f"AND indicator = 'canary' "
            f"AND run_scope = 'research' "
            f"AND completed_at IS NOT NULL "
            f"AND params->>'phase' = 'form_sweep_full' "
            f"ORDER BY params->>'score_form'",
            (run_ids,),
        )
        return [
            {"id": r[0], "params": r[1], "summary": r[2],
             "start_date": r[3], "end_date": r[4], "composite_version": r[5],
             "run_scope": r[6]}
            for r in cur.fetchall()
        ]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", default="form_sweep_compare",
                   choices=("form_sweep_compare",),
                   help="rendering mode (currently only form_sweep_compare)")
    p.add_argument("--runs", default=None,
                   help="comma-separated run ids; if omitted, load latest complete batch")
    args = p.parse_args()

    settings = Settings.from_env()
    schema = settings.db_schema

    with psycopg.connect(settings.db_dsn()) as conn:
        if args.runs:
            run_ids = [int(s) for s in args.runs.split(",")]
            runs = _load_specific_runs(conn, schema, run_ids)
        else:
            runs = _load_latest_complete_batch(conn, schema)
    print(render_canary_form_sweep_compare(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_canary_form_sweep_renderer.py -v`
Expected: 15 passed (canonical_form_ordering, missing_form_raises, duplicate_form_raises, fewer_than_4_rows_raises, mismatched_batch_id_raises, non_research_scope_raises, footer_present, observation_watch_overfire, observation_buy_band_inversion, observation_composite_improves_over_linear, observation_watch_reduce_without_auc_loss, observation_vol_only_gap, observation_buy_pct_zero, observation_strong_buy_pct_zero, observation_none_when_no_form_matches).

- [ ] **Step 5: Milestone checkpoint**

```bash
git add src/uw_scan/reports/regime_canary_backtest_report.py tests/unit/test_canary_form_sweep_renderer.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 7: Renderer batch loading + integration tests

**Files:**
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py`

The renderer's `_load_latest_complete_batch` was implemented in Task 6 but is untested against a real DB. Add 2 integration tests: picks-latest-complete-batch, skips-incomplete-batch.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/regime/test_canary_form_sweep_full.py`:

```python
def test_form_sweep_full_renderer_picks_latest_complete_batch(seeded_db_empty_cards):
    """Two complete batches, different created_at — loader picks the latest."""
    from uw_scan.reports.regime_canary_backtest_report import _load_latest_complete_batch
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)

    def insert_batch(batch_id: str):
        for form in ("linear", "convex", "concave", "sigmoid"):
            run_id = repo.insert_run(
                indicator="canary", composite_version="1",
                start_date=date(2011, 2, 8), end_date=date(2026, 5, 21),
                window_days=350, n_days=100,
                params={"score_form": form, "phase": "form_sweep_full",
                        "batch_id": batch_id},
                summary={"is_winning_form": False, "score_form": form,
                         "batch_id": batch_id, "phase": "form_sweep_full",
                         "n_days": 100,
                         "aucs": {"composite": {"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
                                  "vol_only":  {"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
                                  "speed_only":{"up5d_2pct": 0.5, "up20d_5pct": 0.5, "up60d_10pct": 0.5}},
                         "band_distribution": {"NONE": 60, "WATCH": 30, "BUY": 10, "STRONG_BUY": 0},
                         "within_band_aucs": {"NONE": {"up60d_10pct": 0.55},
                                              "WATCH": {"up60d_10pct": 0.55},
                                              "BUY": {"up60d_10pct": 0.45},
                                              "STRONG_BUY": {"up60d_10pct": None}},
                         "vol_only_gap": {"up5d_2pct": 0.0, "up20d_5pct": 0.0, "up60d_10pct": 0.0}},
                run_scope="research",
            )
            repo.mark_run_completed(run_id)

    # Earlier batch
    insert_batch("batch-A")
    # Later batch (later created_at by virtue of insertion order)
    insert_batch("batch-B")

    runs = _load_latest_complete_batch(db_conn, db_schema)
    assert len(runs) == 4
    batch_ids = {r["params"]["batch_id"] for r in runs}
    assert batch_ids == {"batch-B"}, f"expected batch-B, got {batch_ids}"


def test_renderer_skips_incomplete_batch(seeded_db_empty_cards):
    """Earlier complete batch + later incomplete (3 rows) batch — loader returns the earlier."""
    from uw_scan.reports.regime_canary_backtest_report import _load_latest_complete_batch
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)

    def insert_run_for(batch_id: str, form: str, *, completed: bool = True):
        run_id = repo.insert_run(
            indicator="canary", composite_version="1",
            start_date=date(2011, 2, 8), end_date=date(2026, 5, 21),
            window_days=350, n_days=100,
            params={"score_form": form, "phase": "form_sweep_full",
                    "batch_id": batch_id},
            summary={"is_winning_form": False, "score_form": form,
                     "batch_id": batch_id, "phase": "form_sweep_full",
                     "n_days": 100,
                     "aucs": {"composite": {"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
                              "vol_only":  {"up5d_2pct": 0.6, "up20d_5pct": 0.6, "up60d_10pct": 0.6},
                              "speed_only":{"up5d_2pct": 0.5, "up20d_5pct": 0.5, "up60d_10pct": 0.5}},
                     "band_distribution": {"NONE": 60, "WATCH": 30, "BUY": 10, "STRONG_BUY": 0},
                     "within_band_aucs": {"NONE": {"up60d_10pct": 0.55},
                                          "WATCH": {"up60d_10pct": 0.55},
                                          "BUY": {"up60d_10pct": 0.45},
                                          "STRONG_BUY": {"up60d_10pct": None}},
                     "vol_only_gap": {"up5d_2pct": 0.0, "up20d_5pct": 0.0, "up60d_10pct": 0.0}},
            run_scope="research",
        )
        if completed:
            repo.mark_run_completed(run_id)

    # Earlier complete batch
    for form in ("linear", "convex", "concave", "sigmoid"):
        insert_run_for("batch-complete", form)
    # Later batch but only 3 completed forms (simulated mid-run failure that didn't cleanup)
    for form in ("linear", "convex", "concave"):
        insert_run_for("batch-partial", form)

    runs = _load_latest_complete_batch(db_conn, db_schema)
    batch_ids = {r["params"]["batch_id"] for r in runs}
    assert batch_ids == {"batch-complete"}, \
        f"loader must skip incomplete batches, got {batch_ids}"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v -k "picks_latest_complete_batch or skips_incomplete_batch"`
Expected: 2 passed.

- [ ] **Step 3: Milestone checkpoint**

```bash
git add tests/integration/regime/test_canary_form_sweep_full.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 8: Downstream-invisibility tests (OOS gate, validation API, calibration file)

**Files:**
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py`

These are the spec's §4.4 G-4 guardrail tests. They prove form_sweep_full rows are invisible to v1 production surfaces.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/regime/test_canary_form_sweep_full.py`:

```python
def test_form_sweep_full_does_not_write_calibration_file(
    seeded_db_empty_cards,
):
    """canary-calibration-v1.json byte content unchanged after run."""
    import hashlib
    from pathlib import Path
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    calib_path = Path(__file__).parent.parent.parent.parent / (
        "docs/research/regime/canary-calibration-v1.json")
    assert calib_path.exists(), f"calibration file not found at {calib_path}"

    before_bytes = calib_path.read_bytes()
    before_hash = hashlib.sha256(before_bytes).hexdigest()
    before_mtime = calib_path.stat().st_mtime

    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)
    cmd_form_sweep_full(db_conn, schema=db_schema)

    after_bytes = calib_path.read_bytes()
    after_hash = hashlib.sha256(after_bytes).hexdigest()
    after_mtime = calib_path.stat().st_mtime

    assert before_bytes == after_bytes, "calibration file content changed"
    assert before_hash == after_hash, "calibration SHA-256 mismatch"
    assert before_mtime == after_mtime, "calibration mtime changed"


def test_form_sweep_full_invisible_to_oos_gate(seeded_db_empty_cards):
    """Production find_latest_run does not return any research-scoped form_sweep_full row."""
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    # Seed a pre-existing v1 winning run (mimicking what the OOS gate looks at)
    winning_run_id = repo.insert_run(
        indicator="canary", composite_version="1",
        start_date=date(2020, 1, 2), end_date=date(2026, 5, 21),
        window_days=350, n_days=1605,
        params={"score_form": "linear", "phase": "final_oos_report"},
        summary={"is_winning_form": True, "score_form": "linear"},
    )
    repo.mark_run_completed(winning_run_id)

    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)
    cmd_form_sweep_full(db_conn, schema=db_schema)

    # find_latest_run defaults to run_scope='production', so research rows are invisible.
    latest = repo.find_latest_run("canary", composite_version="1")
    assert latest is not None
    assert latest["id"] == winning_run_id, (
        f"find_latest_run returned {latest['id']}; expected pre-existing v1 run "
        f"{winning_run_id}. form_sweep_full rows must be research scoped."
    )


def test_form_sweep_full_invisible_to_validation_api(
    seeded_db_empty_cards,
):
    """The /api/regime/canary/validation router function returns the same
    row before and after a form_sweep_full run."""
    from tests.integration.regime._canary_form_sweep_fixture import (
        seed_vol_index, seed_canary_snapshots)
    from scripts.backtest_canary import cmd_form_sweep_full
    from uw_scan.api.routers.regime import get_canary_validation
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    db_conn = seeded_db_empty_cards.conn
    db_schema = seeded_db_empty_cards._schema
    repo = RegimeBacktestRepository(db_conn, schema=db_schema)
    pre_winning_id = repo.insert_run(
        indicator="canary", composite_version="1",
        start_date=date(2020, 1, 2), end_date=date(2026, 5, 21),
        window_days=350, n_days=1605,
        params={"score_form": "linear", "phase": "final_oos_report"},
        summary={"is_winning_form": True, "score_form": "linear"},
    )
    repo.mark_run_completed(pre_winning_id)

    # Capture the actual router response the API would serialize.
    before = get_canary_validation(repo=seeded_db_empty_cards).model_dump_json()
    assert f'"run_id":{pre_winning_id}' in before

    dates = seed_vol_index(db_conn, schema=db_schema, n_days=600)
    seed_canary_snapshots(db_conn, schema=db_schema, dates=dates, n_snapshots=200)
    cmd_form_sweep_full(db_conn, schema=db_schema)

    after = get_canary_validation(repo=seeded_db_empty_cards).model_dump_json()
    assert before == after, "validation API payload changed across form_sweep_full"
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v -k "does_not_write_calibration or invisible_to_oos_gate or invisible_to_validation_api"`
Expected: 3 passed.

- [ ] **Step 3: Milestone checkpoint**

```bash
git add tests/integration/regime/test_canary_form_sweep_full.py
# Commit only after the user-approved milestone trigger.
```

---

## Task 9: Final verification + live smoke

**Files:**
- No code changes. This task verifies the complete suite passes and runs a manual smoke against the real DB.

- [ ] **Step 1: Run all tests added in this PR**

```bash
uv run pytest tests/unit/test_within_band_aucs.py \
              tests/unit/test_canary_form_sweep_cli.py \
              tests/unit/test_canary_form_sweep_renderer.py \
              tests/integration/regime/test_canary_form_sweep_full.py -v
```

Expected: **35 passed total**:
- 5 unit tests in `test_within_band_aucs.py`
- 1 unit test in `test_canary_form_sweep_cli.py`
- 15 unit tests in `test_canary_form_sweep_renderer.py` (4 new observation rules: vol_only_gap, buy_pct_zero, strong_buy_pct_zero, none_when_no_form_matches)
- 14 integration tests in `test_canary_form_sweep_full.py`:
  - 3 `delete_runs_by_batch_id` (Task 3 — includes scope-correctness test)
  - 5 happy-path persistence (Task 4 — includes capsys stdout + compute-before-persist)
  - 1 cleanup-on-failure (Task 5)
  - 2 renderer picks-latest / skips-incomplete (Task 7)
  - 3 downstream invisibility (Task 8)

- [ ] **Step 2: Run the existing OOS gate test to confirm non-regression**

```bash
uv run pytest tests/integration/regime/test_canary_oos_gate.py -v
```

Expected: existing OOS gate test passes (no regressions). This is AC-11.

- [ ] **Step 3: Run the live `--form-sweep-full` against the real DB**

```bash
uv run python scripts/backtest_canary.py --form-sweep-full
```

Expected output (final paragraph of the stdout):

```
# Canary form-sweep — candidate discovery
Window: 2011-02-08 → 2026-05-21 (3,843 days)
Composite version: 1
Batch id: <uuid>
Run ids: <r1>, <r2>, <r3>, <r4>

| Form    | AUC 5d | AUC 20d | AUC 60d | NONE% | WATCH% | BUY% | STRONG_BUY% | BUY-band 60d AUC | Vol-only gap (60d) |
| linear  |  0.620 |   0.627 |   0.619 | ...   | ...    | ...  |     ...     |      ...         |      ...           |
| convex  |  ...   |   ...   |   ...   | ...   | ...    | ...  |     ...     |      ...         |      ...           |
| concave |  ...   |   ...   |   ...   | ...   | ...    | ...  |     ...     |      ...         |      ...           |
| sigmoid |  ...   |   ...   |   ...   | ...   | ...    | ...  |     ...     |      ...         |      ...           |

## Observations
- ...

## What this run does NOT decide
This is candidate-discovery output. No form is declared "winning". ...
```

Exit code: 0. 4 new rows in `regime_backtest_runs` for the new batch.

- [ ] **Step 4: Verify renderer re-render works on demand**

```bash
uv run python -m uw_scan.reports.regime_canary_backtest_report
```

Expected: identical table to Step 3's stdout (auto-loads the same batch).

- [ ] **Step 5: Run `/codex-review --diff` (AC-12)**

This is interactive — the user invokes it. Surface to the user:

> "All tests pass. Live smoke completed; 4 form_sweep_full rows persisted under batch_id=<uuid>. Recommend running `/codex-review --diff` (or `/review-cycle`) before opening PR."

- [ ] **Step 6: Stage for PR**

```bash
git log --oneline origin/main..HEAD
```

Expected: 8 commits visible (one per task above that committed code; Task 9 is verification-only and may not need its own commit).

---

## Spec Coverage Map

Verifying every spec section maps to at least one task:

| Spec section | Tasks |
|---|---|
| §1 TL;DR / motivation | Task 4 (the change itself) |
| §2 Goals G1-G3 | Task 4 (the change), Task 6 (renderer stdout) |
| §2 Goals G4 (invisibility) | Task 8 |
| §3 Architecture (two new units) | Task 4 (cmd + helper), Task 6 (renderer) |
| §4.1 CLI surface | Task 4 (argparse + dispatch) |
| §4.2 Persistence shape (params + summary) | Task 4 (Step 3 dict literals) |
| §4.2 Atomicity / cleanup-on-failure | Task 3 (repo method), Task 4 (try/except), Task 5 (assertion test) |
| §4.2 `_within_band_aucs` helper | Task 2 |
| §4.3 Renderer pure function | Task 6 |
| §4.3 Renderer CLI entry point | Task 6 (main() + __main__) |
| §4.3 Loader by batch_id | Task 6 (`_load_latest_complete_batch`), Task 7 (integration tests) |
| §4.4 G-1 mutual exclusion | Task 4 (CLI unit test + Step 4 count-check) |
| §4.4 G-2 function isolation | Task 4 (Step 3 docstring + no calibration write) |
| §4.4 G-3 persistence locks | Task 4 (Step 3 hardcoded literals) |
| §4.4 G-4 downstream invisibility | Task 8 |
| §4.4 G-5 re-run / version safety | Task 4 (Step 3 batch_id), Task 6 (loader) |
| §4.4 G-6 batch atomicity | Task 5 |
| §4.5 Unit tests | Task 2 (within_band), Task 6 (renderer) |
| §4.5 Integration tests | Tasks 3, 4, 5, 7, 8 |
| §5 Acceptance criteria AC-1..AC-13 | Task 9 (verification) |

**Gaps**: none — every spec section has at least one implementing task.

---

## Notes for the implementer

- **Branch name**: `feat/canary-form-sweep-full` (per the prerequisite section).
- **Commit style**: Conventional commits (`type(scope): subject`) when the user explicitly approves a milestone commit. Until then, task-end snippets are staging/checkpoint guidance only.
- **Never commit without explicit user request** — the user has a standing rule about this. If you encounter ambiguity about a milestone boundary, stop and ask.
- **No bare `python` / `pip` / `pytest`** — use `uv run` for all Python invocations per the project's `uv`-only rule.
- **Module size budget**: `scripts/backtest_canary.py` currently sits at ~1,120 lines. Do not add the new command body there. Keep the script change to the wrapper/argparse wiring and put the implementation in `src/uw_scan/reports/regime_canary_form_sweep_full.py`.
- **Connection autocommit**: existing repository methods commit per call. `cmd_form_sweep_full` relies on this; if you find yourself changing the repository to be non-committing, stop — that's out of scope per the spec.
- **If the migration 057 CASCADE check (Task 3 Step 1) fails**, surface immediately — do NOT silently work around it. The cleanup helper would need an explicit `DELETE FROM regime_backtest_daily ...` first.
