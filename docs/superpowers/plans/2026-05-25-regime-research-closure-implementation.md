# Regime Research Closure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the CRI + VCG regime backtests from disk-only artifacts to Postgres-of-record, with full research-scaffolding parity (methodology doc, version tracking, academic foundations) so calibration A/B tests become SQL queries.

**Architecture:** Append-only `regime_backtest_runs` / `regime_backtest_daily` tables (indicator-tagged, JSONB summary), thin `RegimeBacktestRepository`, DB-first `/api/regime/validation` router with file fallback during transition. Backtest scripts derive `composite_version` from code constants — no CLI override. VCG ships a v1 backtest + `vcg-methodology.md`; OOS gate deferred until a defensible Y-label exists.

**Tech Stack:** Postgres 15 + psycopg 3, FastAPI + Pydantic v2, NumPy, `uv` for all Python invocations, `pytest-postgresql` for DB tests.

**Spec:** [`docs/superpowers/specs/2026-05-24-regime-research-closure-design.md`](../specs/2026-05-24-regime-research-closure-design.md). When any task here conflicts with the spec, the spec wins — fix the plan and re-run review.

---

## File Structure

**New files:**
- `src/uw_scan/storage/migrations/057_regime_backtest_results.sql` — DDL
- `src/uw_scan/storage/regime_backtest_repository.py` — `RegimeBacktestRepository` (own module per the no-extend-`repository.py` rule)
- `src/uw_scan/reports/regime_backtest_report.py` — pure renderer (run + daily → markdown)
- `scripts/backtest_vcg.py` — VCG 20y backtest (mirrors CRI script shape)
- `docs/research/regime/vcg-methodology.md` — VCG methodology doc (CRI parity)
- `docs/research/regime/closure-2026-05-24.md` — closure memo + SQL cookbook
- `tests/integration/storage/test_regime_backtest_repository.py` — repository round-trip (pytest-postgresql; `unit/` would violate the no-DB-in-unit rule)
- `tests/unit/reports/test_regime_backtest_report.py` — renderer snapshot vs current `cri-backtest.md`

**Modified files:**
- `scripts/backtest_cri.py` — write DB instead of files; remove CSV/MD/JSON output
- `src/uw_scan/api/routers/regime_validation.py` — DB-first read, file fallback
- `src/uw_scan/cards/vcg_scoring.py` — add `COMPOSITE_VERSION = 1`; extract `_interpretation_for_index` from `evaluate_signal`
- `tests/integration/regime/test_cri_oos_gate.py` — read `summary.oos.versions` from latest DB run
- `docs/research/regime/CLAUDE.md` — VCG rules, DB-as-source-of-truth, no-CSV-in-git
- `docs/research/regime/cri-methodology.md` — augment §5 with academic citations

**Files removed: DEFERRED to a follow-up PR** — `docs/research/regime/{cri-backtest.md,cri-backtest.csv,oos-summary.json}` stay in git during the primary PR to feed the router fallback. Removal happens only after the manual prod gate in spec §10.4 is verified.

---

## Task 1: Migration 057 — `regime_backtest_runs` + `regime_backtest_daily`

**Files:**
- Create: `src/uw_scan/storage/migrations/057_regime_backtest_results.sql`

- [ ] **Step 1: Re-verify slot 057 is still free**

Run: `ls src/uw_scan/storage/migrations/057_*.sql 2>/dev/null && echo "TAKEN" || echo "FREE"`
Expected: `FREE`. If `TAKEN`, renumber to the next free slot (058, 059, …) and update §14 references in the spec.

- [ ] **Step 2: Write the migration**

Create `src/uw_scan/storage/migrations/057_regime_backtest_results.sql` with the SQL verbatim from spec §6. Header `SET search_path TO uw_scan, public;`, wrap body in `BEGIN; … COMMIT;`. Two tables (`regime_backtest_runs`, `regime_backtest_daily`), three indexes, four CHECK constraints. `composite_version TEXT NOT NULL`, `window_days INT NOT NULL CHECK (window_days > 0)`, `completed_at TIMESTAMPTZ` (NULL until backtest finishes).

- [ ] **Step 3: Apply migration locally**

Run: `bash scripts/migrate.sh`
Expected: zero errors. Migration 057 in the lexical run; new tables appear in `\d uw_scan.regime_backtest_*` via psql.

- [ ] **Step 4: Verify idempotency**

Run: `bash scripts/migrate.sh` (a second time)
Expected: zero errors. Re-running is a no-op because of `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.

- [ ] **Step 5: Sanity-check table shape via psql**

Run:
```bash
psql "$DATABASE_URL" -c "\d uw_scan.regime_backtest_runs" \
  -c "\d uw_scan.regime_backtest_daily"
```
Expected: both tables exist with all columns from spec §6; constraints visible (`regime_backtest_runs_date_range`, `regime_backtest_runs_n_days_nonneg`, `regime_backtest_runs_window_pos`); FK from daily → runs with `ON DELETE CASCADE`.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/057_regime_backtest_results.sql
git commit -m "feat(migrations): add regime_backtest_runs + regime_backtest_daily (057)"
```

---

## Task 2: `RegimeBacktestRepository`

**Files:**
- Create: `src/uw_scan/storage/regime_backtest_repository.py`
- Test: `tests/integration/storage/test_regime_backtest_repository.py`

> **Why `integration/` not `unit/`:** `tests/CLAUDE.md` says "`unit/` — pure-function tests, no DB, no network." `pytest-postgresql` integration tests live under `tests/integration/`. Use the existing `seeded_db_empty_cards` fixture (yields a `Repository` against a freshly-migrated test DB) and read `repo.conn` / `repo._schema` to construct `RegimeBacktestRepository` against the same connection.

- [ ] **Step 1: Verify the integration fixture and create the test file**

Run: `grep -n "def seeded_db_empty_cards" tests/integration/conftest.py`
Expected: `seeded_db_empty_cards` is a function-scoped fixture that calls `_reset_and_migrate` (drops + re-applies migrations against the test DB) and yields a `Repository`.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/storage/test_regime_backtest_repository.py` with two tests:

```python
"""Round-trip test for RegimeBacktestRepository against pytest-postgresql.

Uses the existing seeded_db_empty_cards fixture from tests/integration/conftest.py
which applies scripts/migrate.sh (including migration 057) to the test DB.
"""

from __future__ import annotations

from datetime import date

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def test_insert_then_find_latest_round_trip(seeded_db_empty_cards) -> None:
    """insert_run -> bulk_insert_daily -> mark_run_completed -> find_latest_run."""
    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)

    run_id = rb.insert_run(
        indicator="cri",
        composite_version="3",
        start_date=date(2007, 1, 3),
        end_date=date(2026, 5, 15),
        window_days=150,
        n_days=4873,
        params={"rolling_window": 150},
        summary={
            "oos": {
                "as_of": "2026-05-25",
                "notebook": "scripts/backtest_cri.py",
                "method": "Forward-drawdown labels...",
                "labels": [{"name": "label_dd5", "definition": "..."}],
                "scores": [{"model": "CRI v3", "auc_dd5": 0.6343, "auc_dd10": 0.6329}],
                "versions": [{"label": "CRI v3", "version": 3, "auc_dd5": 0.6343}],
                "interpretation": "Test.",
            },
            "extras": {"fired_count": 47},
        },
        note="round-trip test",
    )
    assert isinstance(run_id, int) and run_id > 0

    # find_latest_run filters on completed_at IS NOT NULL — must return None
    # until mark_run_completed fires.
    assert rb.find_latest_run("cri", composite_version="3") is None, (
        "find_latest_run must NOT return rows where completed_at IS NULL — "
        "this guard prevents the deploy-order outage from the spec §10.4"
    )

    rb.bulk_insert_daily(
        run_id,
        [
            {"trade_date": date(2008, 9, 15), "score": 78.0, "level": "CRITICAL",
             "payload": {"vix": 31.7, "vvix": 110.0, "fired": True}},
            {"trade_date": date(2020, 3, 16), "score": 97.0, "level": "CRITICAL",
             "payload": {"vix": 82.69, "vvix": 195.0, "fired": True}},
        ],
    )
    rb.mark_run_completed(run_id)

    latest = rb.find_latest_run("cri", composite_version="3")
    assert latest is not None
    assert latest["id"] == run_id
    assert latest["composite_version"] == "3"
    assert latest["window_days"] == 150
    assert latest["summary"]["extras"]["fired_count"] == 47

    daily = rb.fetch_daily_for_run(run_id)
    assert len(daily) == 2
    assert daily[0]["trade_date"] == date(2008, 9, 15)
    assert daily[0]["level"] == "CRITICAL"
    assert daily[0]["payload"]["fired"] is True


def test_find_latest_run_filters_to_current_composite_version_by_default(
    seeded_db_empty_cards,
) -> None:
    """Experimental runs at non-production composite_version must NOT surface."""
    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)

    prod_id = rb.insert_run(
        indicator="cri", composite_version="3",
        start_date=date(2007, 1, 3), end_date=date(2026, 5, 15),
        window_days=150, n_days=10, params={}, summary={"oos": None, "extras": {}},
    )
    rb.bulk_insert_daily(prod_id, [
        {"trade_date": date(2026, 5, 15), "score": 12.0, "level": "LOW", "payload": {}},
    ])
    rb.mark_run_completed(prod_id)

    exp_id = rb.insert_run(
        indicator="cri", composite_version="4-candidate",
        start_date=date(2007, 1, 3), end_date=date(2026, 5, 15),
        window_days=150, n_days=10, params={}, summary={"oos": None, "extras": {}},
    )
    rb.bulk_insert_daily(exp_id, [
        {"trade_date": date(2026, 5, 15), "score": 18.0, "level": "ELEVATED", "payload": {}},
    ])
    rb.mark_run_completed(exp_id)

    # Default: filters on current production composite_version ("3").
    default = rb.find_latest_run("cri", composite_version="3")
    assert default["id"] == prod_id

    # Explicit experimental query opt-in.
    exp = rb.find_latest_run("cri", composite_version="4-candidate")
    assert exp["id"] == exp_id
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_regime_backtest_repository.py -v`
Expected: `ImportError: cannot import name 'RegimeBacktestRepository'`.

- [ ] **Step 4: Implement the repository**

Create `src/uw_scan/storage/regime_backtest_repository.py`:

```python
"""Persistence for CRI/VCG regime backtest runs.

New domain — own module per docs/research/regime/CLAUDE.md and the global
no-extend-repository.py rule. Mirrors the CriSnapshotRepository pattern:
takes a psycopg.Connection + schema string, sets search_path on init.

Two-phase atomic write:
    insert_run() -> bulk_insert_daily() -> mark_run_completed()

find_latest_run filters on completed_at IS NOT NULL so an interrupted
backtest cannot poison /api/regime/validation. It also filters on
composite_version (default = the indicator's current code constant) so
experimental calibrations are query-only via SQL.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from psycopg import Connection
from psycopg.types.json import Jsonb


class RegimeBacktestRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def insert_run(
        self,
        *,
        indicator: Literal["cri", "vcg"],
        composite_version: str,
        start_date: date,
        end_date: date,
        window_days: int,
        n_days: int,
        params: dict,
        summary: dict,
        note: str | None = None,
    ) -> int:
        sql = """
            INSERT INTO regime_backtest_runs (
                indicator, composite_version, start_date, end_date,
                window_days, n_days, params, summary, note
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    indicator,
                    composite_version,
                    start_date,
                    end_date,
                    window_days,
                    n_days,
                    Jsonb(params),
                    Jsonb(summary),
                    note,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def bulk_insert_daily(self, run_id: int, rows: list[dict]) -> None:
        if not rows:
            return
        sql = """
            INSERT INTO regime_backtest_daily (run_id, trade_date, score, level, payload)
            VALUES (%s, %s, %s, %s, %s)
        """
        params = [
            (
                run_id,
                r["trade_date"],
                r["score"],
                r.get("level"),
                Jsonb(r.get("payload", {})),
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()

    def mark_run_completed(self, run_id: int) -> None:
        """Set completed_at = NOW(). MUST be the last call in a backtest."""
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE regime_backtest_runs SET completed_at = NOW() WHERE id = %s",
                (run_id,),
            )
        self._conn.commit()

    def find_latest_run(
        self,
        indicator: Literal["cri", "vcg"],
        composite_version: str | None = None,
    ) -> dict | None:
        """Latest COMPLETED run for the indicator.

        composite_version defaults to the indicator's current code constant
        when called from the API. Callers wanting experimental rows pass an
        explicit composite_version.
        """
        if composite_version is None:
            composite_version = _current_composite_version(indicator)

        sql = """
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   created_at, completed_at
              FROM regime_backtest_runs
             WHERE indicator = %s
               AND composite_version = %s
               AND completed_at IS NOT NULL
             ORDER BY created_at DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (indicator, composite_version))
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
        if row is None:
            return None
        return dict(zip(cols, row, strict=True))

    def fetch_daily_for_run(self, run_id: int) -> list[dict]:
        sql = """
            SELECT trade_date, score, level, payload
              FROM regime_backtest_daily
             WHERE run_id = %s
             ORDER BY trade_date
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id,))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def list_runs(
        self,
        indicator: Literal["cri", "vcg"],
        limit: int = 20,
        completed_only: bool = True,
    ) -> list[dict]:
        where = "WHERE indicator = %s"
        params: list[Any] = [indicator]
        if completed_only:
            where += " AND completed_at IS NOT NULL"
        sql = f"""
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   created_at, completed_at
              FROM regime_backtest_runs
             {where}
             ORDER BY created_at DESC
             LIMIT %s
        """
        params.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in rows]


def _current_composite_version(indicator: Literal["cri", "vcg"]) -> str:
    """Resolve the indicator's current code constant to a string.

    Imported lazily to keep this module dependency-light and avoid a circular
    import (cards/* don't depend on storage/*, and we want to keep it that way).
    """
    if indicator == "cri":
        from uw_scan.cards.cri_scorers import COMPOSITE_VERSION  # noqa: PLC0415

        return str(COMPOSITE_VERSION)
    if indicator == "vcg":
        from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION  # noqa: PLC0415

        return str(COMPOSITE_VERSION)
    raise ValueError(f"unknown indicator: {indicator}")
```

- [ ] **Step 5: Run tests to verify pass**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_regime_backtest_repository.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/regime_backtest_repository.py \
        tests/integration/storage/test_regime_backtest_repository.py
git commit -m "feat(storage): add RegimeBacktestRepository for CRI/VCG backtest runs"
```

---

## Task 3: VCG — add `COMPOSITE_VERSION` + extract `_interpretation_for_index`

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py`
- Test: existing `tests/unit/test_vcg_scoring.py` (if present) — must still pass; add one new test if no extraction test exists

- [ ] **Step 1: Locate the existing VCG test file**

Run: `find tests -name "test_vcg*.py" -o -name "*vcg*test*.py"`
Expected: one or more existing test files. Record the path.

- [ ] **Step 2: Add the failing test for the extracted helper**

The helper returns **the same dict as `evaluate_signal` MINUS only `credit_5d_return_pct`**. Every other field — including the nested `attribution` block — is identical. The test asserts key-set equality (catches the breaking-change case where a future edit accidentally drops a key from the helper) plus value equality on every field.

Append to the most relevant test file (or create `tests/unit/test_vcg_interpretation_for_index.py`):

```python
"""evaluate_signal must equal _interpretation_for_index(model, idx=-1) on the
common fields. This pins the extraction so it stays semantics-preserving.

The helper's contract: returns the same dict as evaluate_signal except for
credit_5d_return_pct (which is computed from credit_prices, not the model).
Every other field — including the nested `attribution` block — matches."""

from __future__ import annotations

import numpy as np

from uw_scan.cards import vcg_scoring


def _fake_model(n: int = 100) -> dict:
    rng = np.random.default_rng(0)
    vix = 20 + rng.normal(0, 3, n).cumsum() * 0.05 + 5
    vvix = 95 + rng.normal(0, 4, n).cumsum() * 0.05
    credit = 90 + rng.normal(0, 0.4, n).cumsum() * 0.01
    return vcg_scoring.compute_vcg(vix, vvix, credit)


def test_helper_returns_same_keys_as_signal_minus_credit_5d() -> None:
    """Key-set parity. Catches the case where the extraction accidentally
    drops a field (e.g., attribution) that the script/API depends on."""
    model = _fake_model()
    credit = np.linspace(90, 92, len(model["residuals"]) + 1)
    sig_keys = set(vcg_scoring.evaluate_signal(model, credit).keys())
    helper_keys = set(vcg_scoring._interpretation_for_index(model, idx=-1).keys())
    assert sig_keys - helper_keys == {"credit_5d_return_pct"}, (
        f"helper missing keys evaluate_signal provides: "
        f"{sig_keys - helper_keys - {'credit_5d_return_pct'}}"
    )
    assert helper_keys - sig_keys == set(), (
        f"helper produced unexpected keys: {helper_keys - sig_keys}"
    )


def test_interpretation_for_index_matches_evaluate_signal_at_last_bar() -> None:
    """Value parity at idx=-1. Covers EVERY key in the helper's return,
    including nested `attribution`. Compares raw values (==) so any drift
    in rounding or computation is caught."""
    model = _fake_model()
    credit = np.linspace(90, 92, len(model["residuals"]) + 1)
    sig = vcg_scoring.evaluate_signal(model, credit)
    helper = vcg_scoring._interpretation_for_index(model, idx=-1)
    for k in helper:
        assert sig[k] == helper[k], f"{k}: signal={sig[k]!r} helper={helper[k]!r}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_vcg_interpretation_for_index.py -v` (or whatever path you used)
Expected: `AttributeError: module 'uw_scan.cards.vcg_scoring' has no attribute '_interpretation_for_index'`.

- [ ] **Step 4: Add `COMPOSITE_VERSION` constant**

Edit `src/uw_scan/cards/vcg_scoring.py` near the existing constants block (`OLS_WINDOW`, `Z_WINDOW`, …), insert after line `MIN_BARS = OLS_WINDOW + Z_WINDOW + 10`:

```python
# Composite scoring contract version.
# v1: as-ported from xenon/src/xenon/scanners/vcg.py at commit d3cbc08.
#     OLS_WINDOW=21, Z_WINDOW=63, VCG_TRIGGER=2.0, VCG_RO_TRIGGER=2.5,
#     BOUNCE_TRIGGER=-3.5, VIX_FLOOR=28, VIX_EDR=25, VIX_PANIC_LOW=40,
#     VIX_PANIC_HIGH=48, VVIX_ELEVATED=100, VVIX_EXTREME=120.
#     Calibration NOT re-derived in this repo — see vcg-methodology.md §3.
# Bump in lockstep with any threshold change above.
COMPOSITE_VERSION = 1
```

- [ ] **Step 5: Extract `_interpretation_for_index` from `evaluate_signal`**

The current `evaluate_signal` at `src/uw_scan/cards/vcg_scoring.py:223-325` computes per-index values from `idx = -1`. Refactor in place:

a. Add a new function `_interpretation_for_index(model, idx, *, vix_floor=VIX_FLOOR, vcg_trigger=VCG_RO_TRIGGER) -> dict` that returns the regime/interpretation/flags/attribution dict for an arbitrary index. Move ALL the body of `evaluate_signal` between the `idx = -1` line and the final `return { … }` into this helper, parameterised on `idx`. **The helper MUST include the `attribution` nested dict in its return** — the VCG live card surface (`run_analysis` → `signal`) depends on `attribution.vvix_pct` / `attribution.vix_pct` / etc., and after the extraction `evaluate_signal` is a thin wrapper that adds only `credit_5d_return_pct`. If `attribution` is missed, the API breaks silently.

b. `evaluate_signal` becomes a thin wrapper:

```python
def evaluate_signal(
    model: dict[str, np.ndarray],
    credit_prices: np.ndarray,
    *,
    vix_floor: float = VIX_FLOOR,
    vcg_trigger: float = VCG_RO_TRIGGER,
) -> dict[str, Any]:
    """Build the latest-bar signal payload."""
    idx = -1
    payload = _interpretation_for_index(
        model, idx, vix_floor=vix_floor, vcg_trigger=vcg_trigger
    )

    if len(credit_prices) >= 6:
        credit_5d_ret = (credit_prices[-1] / credit_prices[-6]) - 1.0
    else:
        credit_5d_ret = 0.0
    payload["credit_5d_return_pct"] = round(credit_5d_ret * 100.0, 3)
    return payload
```

c. The helper returns the same dict shape (`vcg`, `vcg_adj`, `residual`, `beta1_vvix`, `beta2_vix`, `alpha`, `vix`, `vvix`, `credit_price`, `ro`, `edr`, `tier`, `bounce`, `vvix_severity`, `sign_ok`, `sign_suppressed`, `pi_panic`, `regime`, `interpretation`, **`attribution`**) MINUS `credit_5d_return_pct` (which depends on `credit_prices`, not the model). `evaluate_signal` adds only that one field. The `test_helper_returns_same_keys_as_signal_minus_credit_5d` test in step 2 pins this contract.

d. Keep `_signal_for_index` (the existing flags helper) — `_interpretation_for_index` calls it internally for the ro/edr/tier/bounce/sign_ok flags.

- [ ] **Step 6: Run all VCG tests**

Run: `uv run pytest tests/ -k vcg -v`
Expected: all VCG tests PASS (the new helper test + all pre-existing tests that exercise `evaluate_signal`, `compute_vcg`, `run_analysis`).

- [ ] **Step 7: Commit**

```bash
# Find the actual path of the new/touched test file from Step 1 / Step 2
TEST_PATH=$(grep -rL "" tests/unit/ 2>/dev/null | xargs grep -l "test_interpretation_for_index_matches_evaluate_signal_at_last_bar" 2>/dev/null | head -1)
echo "staging: $TEST_PATH"
git add src/uw_scan/cards/vcg_scoring.py "$TEST_PATH"
git commit -m "refactor(vcg): extract _interpretation_for_index; add COMPOSITE_VERSION=1"
```

If you created `tests/unit/test_vcg_interpretation_for_index.py` (Step 2's "create" option), `$TEST_PATH` resolves to that. If you appended to an existing file (e.g. `tests/unit/test_vcg_scoring.py`), it resolves to that. Either way, the right file is staged.

---

## Task 4: Backtest renderer module

**Files:**
- Create: `src/uw_scan/reports/regime_backtest_report.py`
- Test: `tests/unit/reports/test_regime_backtest_report.py`

- [ ] **Step 1: Confirm the snapshot fixture file exists**

Run: `ls -la docs/research/regime/cri-backtest.md`
Expected: file exists and is non-empty. This is the byte-for-byte target.

- [ ] **Step 2: Write the failing snapshot test**

Create `tests/unit/reports/test_regime_backtest_report.py`:

```python
"""Snapshot test for the markdown renderer.

The renderer must reproduce docs/research/regime/cri-backtest.md byte-for-byte
when fed the same data the legacy write_report() saw. The fixture for `daily`
comes from re-parsing the checked-in CSV — the CSV is the recorded output of
the same rolling_compute() that produced the markdown.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from uw_scan.reports.regime_backtest_report import render_backtest_markdown

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MD_PATH = _REPO_ROOT / "docs" / "research" / "regime" / "cri-backtest.md"
_CSV_PATH = _REPO_ROOT / "docs" / "research" / "regime" / "cri-backtest.csv"


def _load_daily() -> list[dict]:
    daily: list[dict] = []
    with _CSV_PATH.open() as f:
        for row in csv.DictReader(f):
            daily.append(
                {
                    "trade_date": date.fromisoformat(row["date"]),
                    "score": float(row["score"]),
                    "level": row["level"],
                    "payload": {
                        "fired": row["fired"] == "True",
                        "vix": float(row["vix"]),
                        "vvix": float(row["vvix"]),
                        "cor1m": float(row["cor1m"]),
                        "spx_distance_pct": float(row["spx_distance_pct"]),
                    },
                }
            )
    return daily


def test_render_matches_existing_cri_backtest_md_byte_for_byte() -> None:
    daily = _load_daily()
    run = {
        "indicator": "cri",
        "composite_version": "3",
        # NOTE: start_date is intentionally NOT used by the renderer for the
        # "Date range" line — the renderer derives the visible window from
        # daily[0].trade_date (rolling_compute skips the first 150 sessions).
        "start_date": date(2006, 1, 1),
        "end_date": daily[-1]["trade_date"],
        "window_days": 150,
        "n_days": len(daily),
        "summary": {"oos": None, "extras": {}},
    }
    expected = _MD_PATH.read_text()
    actual = render_backtest_markdown(run, daily)
    assert actual == expected, (
        "renderer drifted from cri-backtest.md — diff intentional? "
        "If yes, regenerate the fixture in the SAME PR; if no, fix the "
        "renderer (window-start uses daily[0].trade_date, not run.start_date)."
    )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_regime_backtest_report.py -v`
Expected: `ModuleNotFoundError: No module named 'uw_scan.reports.regime_backtest_report'`.

- [ ] **Step 4: Read the existing `write_report` function**

Open `scripts/backtest_cri.py:358-393`. The function takes `(rows, path)` and writes the markdown. Port the body to a pure function that takes `(run, daily)` and returns a string. The daily rows already carry `score`, `level`, `payload.fired` — same shape as the script's `rows`.

- [ ] **Step 5: Implement the renderer**

Create `src/uw_scan/reports/regime_backtest_report.py`:

```python
"""Pure renderer: regime_backtest_runs row + daily rows -> markdown.

Extracted from scripts/backtest_cri.py's legacy write_report(). The router
calls this on each /api/regime/validation request — no I/O, no DB, no state.

Window-start contract: the "Date range" line uses daily[0].trade_date, NOT
run.start_date. The script's rolling_compute skips the first 150 sessions
(`window=150` lookback), so run.start_date predates the first emitted row
by ~7 months of trading days. Snapshot tests rely on this.
"""

from __future__ import annotations

from collections import Counter
from io import StringIO
from typing import Any

import numpy as np

# Named crash events that appear in the report. Keep in sync with
# scripts/backtest_cri.py:NAMED_CRASH_DATES — the source of truth for the
# event labels lives in the script that produces the data.
NAMED_CRASH_DATES: dict[str, str] = {
    "2008-09-15": "Lehman bankruptcy",
    "2008-10-10": "GFC bottom area",
    "2010-05-06": "Flash crash",
    "2011-08-08": "US credit downgrade",
    "2015-08-24": "Black Monday (China)",
    "2018-02-05": "Volmageddon",
    "2018-12-24": "Q4 selloff trough",
    "2020-02-28": "COVID early break",
    "2020-03-16": "COVID circuit breaker",
    "2022-06-13": "Rate-hike vol",
    "2024-08-05": "Yen-carry unwind",
}

_LEVELS = ("LOW", "ELEVATED", "HIGH", "CRITICAL")


def _summarize(scores: list[float], levels: list[str]) -> dict[str, Any]:
    arr = np.array(scores, dtype=float)
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "p25": float(np.percentile(arr, 25)),
        "p50": float(np.percentile(arr, 50)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "level_counts": dict(Counter(levels)),
    }


def render_backtest_markdown(run: dict, daily: list[dict]) -> str:
    """Reproduce the legacy cri-backtest.md format from a run row + daily rows.

    `run` is a dict from RegimeBacktestRepository.find_latest_run (or any row
    matching the regime_backtest_runs columns).
    `daily` is a list of dicts with at minimum {trade_date, score, level,
    payload}. payload may carry `fired` (CRI) and indicator-specific extras.
    """
    if not daily:
        return "# CRI Backtest\n\n_No daily rows available._\n"

    scores = [float(d["score"]) for d in daily]
    levels = [str(d["level"]) for d in daily]
    summary = _summarize(scores, levels)

    by_iso = {d["trade_date"].isoformat(): d for d in daily}

    out = StringIO()
    out.write("# CRI Backtest — 2006-2026\n\n")
    out.write(
        "Generated by `scripts/backtest_cri.py`. "
        "Re-run after any calibration change.\n\n"
    )
    out.write(f"**N days:** {summary['n']}  \n")
    out.write(
        f"**Date range:** {daily[0]['trade_date'].isoformat()} "
        f"→ {daily[-1]['trade_date'].isoformat()}\n\n"
    )

    out.write("## Score distribution\n\n")
    out.write("| Stat | Value |\n|---|---|\n")
    for k in ("mean", "min", "p25", "p50", "p75", "p90", "p95", "p99", "max"):
        out.write(f"| {k} | {summary[k]:.2f} |\n")

    out.write("\n## Level distribution\n\n")
    out.write("| Level | Count | % |\n|---|---|---|\n")
    total = summary["n"]
    for lvl in _LEVELS:
        count = summary["level_counts"].get(lvl, 0)
        out.write(f"| {lvl} | {count} | {count / total * 100:.1f}% |\n")

    out.write("\n## Named crash dates\n\n")
    out.write("| Date | Event | CRI score | Level | Trigger fired |\n")
    out.write("|---|---|---|---|---|\n")
    hits = 0
    for iso, name in NAMED_CRASH_DATES.items():
        row = by_iso.get(iso)
        if row is None:
            continue
        hits += 1
        fired = bool((row.get("payload") or {}).get("fired", False))
        out.write(
            f"| {iso} | {name} | {float(row['score']):.1f} | {row['level']} | {fired} |\n"
        )
    if hits == 0:
        out.write("| _no aligned data for any named date_ | | | | |\n")
    return out.getvalue()
```

- [ ] **Step 6: Run snapshot test**

Run: `uv run pytest tests/unit/reports/test_regime_backtest_report.py -v`
Expected: PASS (byte-for-byte match with the checked-in `cri-backtest.md`).

If FAIL: the assertion error contains the exact byte diff. Common causes:
1. Wrong window-start (using `run.start_date` instead of `daily[0].trade_date`)
2. Float formatting drift (`:.2f` vs `:.1f` on a column)
3. Level enum order drift (`_LEVELS` ordering)

Fix the renderer to match the snapshot exactly. The fixture is authoritative until step 9 of Task 5 explicitly regenerates it.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/reports/regime_backtest_report.py \
        tests/unit/reports/test_regime_backtest_report.py
git commit -m "feat(reports): add pure renderer for regime backtest markdown"
```

---

## Task 5: Modify `scripts/backtest_cri.py` to write DB

**Files:**
- Modify: `scripts/backtest_cri.py`

- [ ] **Step 1: Remove file-output CLI flags + their plumbing**

Open `scripts/backtest_cri.py`. Remove from `main()`:
- `--out-csv` argument (lines ~403)
- `--out-md` argument (lines ~404)
- `--write-oos-summary` argument (lines ~405-412)
- The `write_csv(rows, …)` call at line ~441
- The `write_report(rows, …)` call at line ~442
- The `if args.write_oos_summary: write_oos_summary(...)` block at lines ~443-444

Also remove the function bodies (no longer called):
- `write_csv` (lines ~346-355)
- `write_report` (lines ~358-393)
- `write_oos_summary` (lines ~237-326)

**KEEP module-level — these survive the removal and are still referenced by new code below:**
- `OOS_LABELS` (lines ~50-53)
- `V1_AUC_BASELINE` (line ~57; the new persistence block references it for both `summary.oos.scores` and `summary.oos.versions`)
- `NAMED_CRASH_DATES` (lines ~61-73)
- `_compute_v3_auc`, `_roc_auc`, `_forward_drawdown_labels` (still needed for the AUC payload)
- `fetch_aligned_series`, `compute_cri_for_window`, `rolling_compute`, `summarize_distribution`

Add to `main()`'s argparse:
```python
p.add_argument("--note", default=None, help="Free-text run note for SQL queries.")
```

- [ ] **Step 2: Add the DB-write path**

Add imports near the top of `scripts/backtest_cri.py`:
```python
from uw_scan.cards.cri_scorers import COMPOSITE_VERSION  # noqa: E402
from uw_scan.storage.regime_backtest_repository import (  # noqa: E402
    RegimeBacktestRepository,
)
```

Replace the tail of `main()` (after `rows = rolling_compute(…)` and the `if not rows: …` guard) with:

```python
v3_auc = _compute_v3_auc(rows)
n_obs = sum(1 for r in rows if math.isfinite(r["score"]))
level_counts = dict(Counter(r["level"] for r in rows))
named_hits = {
    d: {"score": rec["score"], "level": rec["level"], "fired": rec["fired"]}
    for d, rec in ((d, next((r for r in rows if r["date"] == d), None))
                   for d in NAMED_CRASH_DATES)
    if rec is not None
}

summary = {
    "oos": {
        "as_of": _datetime.now().date().isoformat(),
        "notebook": "scripts/backtest_cri.py",
        "method": (
            "Forward-drawdown labels: dd5 = SPX -5% within 20 sessions; "
            "dd10 = SPX -10% within 60 sessions. AUC via Mann-Whitney "
            "rank-sum on the full backtest."
        ),
        "labels": [
            {"name": "label_dd5",
             "definition": "SPX -5% drawdown within 20 trading days"},
            {"name": "label_dd10",
             "definition": "SPX -10% drawdown within 60 trading days"},
        ],
        "scores": [
            {"model": "CRI v1 (frozen baseline)",
             "auc_dd5": V1_AUC_BASELINE["dd5"],
             "auc_vix30": None,
             "auc_dd10": V1_AUC_BASELINE["dd10"]},
            {"model": f"CRI v{COMPOSITE_VERSION} (this run)",
             "auc_dd5": _round_or_none(v3_auc.get("dd5")),
             "auc_vix30": None,
             "auc_dd10": _round_or_none(v3_auc.get("dd10"))},
        ],
        "versions": [
            {"label": "CRI v1", "version": 1,
             "auc_dd5": V1_AUC_BASELINE["dd5"],
             "auc_dd10": V1_AUC_BASELINE["dd10"],
             "n_observations": n_obs,
             "notes": "Frozen baseline from cri-validation.ipynb §9 (pre-PR-58)."},
            {"label": f"CRI v{COMPOSITE_VERSION}", "version": COMPOSITE_VERSION,
             "auc_dd5": _round_or_none(v3_auc.get("dd5")),
             "auc_dd10": _round_or_none(v3_auc.get("dd10")),
             "n_observations": n_obs,
             "notes": (
                "v3: VIX floor 13, RoC denom 40, VVIX floor 80, "
                "tactical pullback sub-score (saturates at -4% from 20d high)."
             )},
        ],
        "interpretation": (
            "Current version AUC must be within BASELINE_TOLERANCE (0.02) "
            "of v1 baseline. Enforced by "
            "tests/integration/regime/test_cri_oos_gate.py."
        ),
    },
    "extras": {
        "named_crash_hits": named_hits,
        "level_distribution": level_counts,
        "fired_count": sum(1 for r in rows if r["fired"]),
        "v1_baseline_auc_dd5":  V1_AUC_BASELINE["dd5"],
        "v1_baseline_auc_dd10": V1_AUC_BASELINE["dd10"],
    },
}

# Round-trip validation: catch summary.oos drift BEFORE writing to DB.
# Two layers:
#   1. Pydantic OosSummary validates the API-modeled subset (as_of, notebook,
#      method, labels, scores, interpretation). Pydantic v2's default
#      extra="ignore" means it does NOT validate versions[] — that field is
#      sidecar data the test_cri_oos_gate reads via dict access.
#   2. Explicit checks pin the versions[] shape so a future rename or drop
#      breaks at write time, not at next-CI-run time.
from uw_scan.api.models.regime_validation import OosSummary  # noqa: PLC0415
OosSummary.model_validate(summary["oos"])
_versions = summary["oos"].get("versions")
assert isinstance(_versions, list) and len(_versions) >= 2, (
    "summary.oos.versions[] must be a list with >=2 entries (v1 baseline + current)"
)
assert all(
    isinstance(v, dict) and "version" in v
    and "auc_dd5" in v and "auc_dd10" in v
    for v in _versions
), "every entry in summary.oos.versions[] needs version/auc_dd5/auc_dd10 keys"
assert any(v.get("version") == 1 for v in _versions), (
    "v1 baseline entry missing from summary.oos.versions[]"
)
assert any(v.get("version") == COMPOSITE_VERSION for v in _versions), (
    f"current-version entry (v{COMPOSITE_VERSION}) missing from "
    "summary.oos.versions[]"
)

with psycopg.connect(settings.db_dsn()) as conn:
    rb = RegimeBacktestRepository(conn, schema=settings.db_schema)
    run_id = rb.insert_run(
        indicator="cri",
        composite_version=str(COMPOSITE_VERSION),
        start_date=_date.fromisoformat(rows[0]["date"]),
        end_date=_date.fromisoformat(rows[-1]["date"]),
        window_days=rolling_window,
        n_days=len(rows),
        params={"rolling_window": rolling_window, "start": args.start, "end": args.end},
        summary=summary,
        note=args.note,
    )
    daily_rows = [
        {
            "trade_date": _date.fromisoformat(r["date"]),
            "score": float(r["score"]),
            "level": str(r["level"]),
            "payload": {
                "fired": bool(r["fired"]),
                "vix": r["vix"], "vvix": r["vvix"], "cor1m": r["cor1m"],
                "spx_distance_pct": r["spx_distance_pct"],
                "vix_c": r["vix_c"], "vvix_c": r["vvix_c"],
                "corr_c": r["corr_c"], "trend_c": r["trend_c"],
                "pullback_20d_pct": r.get("pullback_20d_pct"),
                "vix_delta_3d": r.get("vix_delta_3d"),
            },
        }
        for r in rows
    ]
    rb.bulk_insert_daily(run_id, daily_rows)
    rb.mark_run_completed(run_id)

log.info(
    "CRI backtest persisted: run_id=%d n=%d composite_version=%s "
    "auc_dd5=%.4f auc_dd10=%.4f",
    run_id, len(rows), COMPOSITE_VERSION,
    v3_auc.get("dd5", float("nan")), v3_auc.get("dd10", float("nan")),
)

# Diagnostic: named-crash sanity check (CRI level + fired flag from scoring code).
log.info("=== CRI named-crash sanity check ===")
for d, name in NAMED_CRASH_DATES.items():
    rec = named_hits.get(d)
    if rec is None:
        log.info("%s %-30s (no aligned data)", d, name)
        continue
    log.info(
        "%s %-30s CRI=%.0f %-9s fired=%s",
        d, name, rec["score"], rec["level"], rec["fired"],
    )
return 0
```

Add a small helper at module scope (just above `def main()`):
```python
def _round_or_none(x: float | None, ndigits: int = 4) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), ndigits)
```

- [ ] **Step 3: Run the script against your local DB**

Pre-check that the DB has enough vol_index_daily history:
```bash
psql "$DATABASE_URL" -c "
  SELECT symbol, MIN(trade_date), MAX(trade_date), COUNT(*)
    FROM uw_scan.vol_index_daily
   WHERE symbol IN ('VIX','VVIX','COR1M','SPX')
   GROUP BY symbol ORDER BY symbol;
"
```
Expected: ≥4900 rows per symbol; range ≥ 2006-03-06 → today.

Run the backtest:
```bash
uv run python scripts/backtest_cri.py --note "first DB-of-record run"
```
Expected output: `aligned N trading days` (~5000), `CRI backtest persisted: run_id=… auc_dd5=0.63… auc_dd10=0.63…`, named-crash sanity table.

- [ ] **Step 4: Verify rows landed in DB**

Run:
```bash
psql "$DATABASE_URL" -c "
  SELECT id, indicator, composite_version, start_date, end_date,
         window_days, n_days,
         summary->'oos'->>'as_of' AS as_of,
         completed_at IS NOT NULL AS completed
    FROM uw_scan.regime_backtest_runs
   WHERE indicator = 'cri'
   ORDER BY created_at DESC
   LIMIT 3;
"
psql "$DATABASE_URL" -c "
  SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
    FROM uw_scan.regime_backtest_daily
   WHERE run_id = (SELECT MAX(id) FROM uw_scan.regime_backtest_runs WHERE indicator='cri');
"
```
Expected: one CRI row, `completed = t`, `composite_version = '3'`, `window_days = 150`, ≥4900 daily rows.

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_cri.py
git commit -m "feat(backtest): persist CRI backtest to Postgres; remove file outputs"
```

---

## Task 6: Modify `/api/regime/validation` to read DB

**Files:**
- Modify: `src/uw_scan/api/routers/regime_validation.py`
- Test: `tests/integration/api/test_regime_validation_endpoint.py` (existing — must still pass)

- [ ] **Step 1: Read the existing endpoint test**

Open `tests/integration/api/test_regime_validation_endpoint.py`. Note the response-shape assertions; they must remain green.

- [ ] **Step 2: Update imports and the route handler**

Edit `src/uw_scan/api/routers/regime_validation.py`. Add imports near the existing `from uw_scan.api.deps import get_repo` line:

```python
from uw_scan.cards.cri_scorers import COMPOSITE_VERSION as CRI_COMPOSITE_VERSION
from uw_scan.reports.regime_backtest_report import render_backtest_markdown
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
```

Replace `get_validation` (lines 247-256):

```python
@router.get("/validation", response_model=ValidationResponse)
def get_validation(
    repo: Annotated[Repository, Depends(get_repo)],
) -> ValidationResponse:
    """DB-first; falls back to checked-in files during the deploy transition.

    The fallback block is removed in a follow-up PR after the prod gate in
    docs/superpowers/specs/2026-05-24-regime-research-closure-design.md §10.4
    is satisfied (≥1 completed CRI run in prod at the current
    cri_scorers.COMPOSITE_VERSION).
    """
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    # No composite_version arg -> RegimeBacktestRepository defaults to
    # str(cri_scorers.COMPOSITE_VERSION). Experimental runs at other versions
    # are query-only via SQL and do NOT leak into the API surface.
    run = rb.find_latest_run("cri")
    if run is not None:
        daily = rb.fetch_daily_for_run(run["id"])
        oos_payload = (run.get("summary") or {}).get("oos")
        return ValidationResponse(
            backtest_md=render_backtest_markdown(run, daily),
            backtest_csv_rows=len(daily),
            oos=OosSummary.model_validate(oos_payload) if oos_payload else None,
        )

    # Transitional fallback — see docstring. Log LOUDLY: this path is hit
    # when code constant has advanced past the prod-DB record (calibration
    # bump without a re-run), and the data we serve is stale-by-one-version.
    # Operators should see this in the logs and re-run scripts/backtest_cri.py.
    logger.warning(
        "regime/validation falling back to on-disk files: no completed "
        "regime_backtest_runs row at composite_version=%s. Re-run "
        "scripts/backtest_cri.py to refresh the DB record.",
        CRI_COMPOSITE_VERSION,
    )
    md_path = _safe_doc_path("cri-backtest.md")
    return ValidationResponse(
        backtest_md=md_path.read_text(),
        backtest_csv_rows=_count_csv_rows("cri-backtest.csv"),
        oos=_read_oos_summary(),
    )
```

- [ ] **Step 3: Run the endpoint test**

Run: `uv run pytest tests/integration/api/test_regime_validation_endpoint.py -v`
Expected: PASS via either the DB path (if the test seeds a run) or the file fallback (if it doesn't). Response shape unchanged.

- [ ] **Step 4: Manual smoke test against the locally-running API**

```bash
bash scripts/dev.sh &  # if not already running
sleep 5
curl -s http://127.0.0.1:8400/api/regime/validation | jq '{keys: keys, csv_rows: .backtest_csv_rows, oos_keys: (.oos | keys), md_lines: (.backtest_md | split("\n") | length)}'
```
Expected: `keys == ["backtest_csv_rows", "backtest_md", "oos"]`. `csv_rows` ≈ 4900+ (matches Task 5's persisted daily count). `oos_keys` contains `as_of`, `interpretation`, `labels`, `method`, `notebook`, `scores`. `md_lines` ≥ 30. **Note:** `backtest_md` is NOT byte-equivalent to the checked-in `cri-backtest.md` once Task 5 has run against fresh data — the new run's `daily[-1].trade_date` advances past the snapshot's `2026-05-19`. The Task-4 snapshot test pins renderer correctness against the historical fixture; this smoke test only verifies shape + non-emptiness.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/routers/regime_validation.py
git commit -m "feat(api): /regime/validation reads DB run; file fallback for transition"
```

---

## Task 7: Update `test_cri_oos_gate.py` to read from DB

**Files:**
- Modify: `src/uw_scan/cards/cri_scorers.py` (add `LAST_KNOWN_AUC_*` constants)
- Modify: `tests/integration/regime/test_cri_oos_gate.py`
- Create: `tests/integration/regime/conftest.py`

> **Calibration-provenance contract — read first.** The original OOS gate read from a checked-in `oos-summary.json`. Calibration PRs had to regenerate that file (verifiable in PR review). The DB-backed gate relocates the "recorded numbers" from JSON to Python constants in `cri_scorers.py` (`LAST_KNOWN_AUC_DD5`, `LAST_KNOWN_AUC_DD10`). The seed fixture inserts a DB run whose `summary.oos.versions[]` carries those constants. The contract becomes: **bumping `COMPOSITE_VERSION` requires updating `LAST_KNOWN_AUC_DD5` / `LAST_KNOWN_AUC_DD10` in the same PR.** PR review catches misses — same gate as the original file-based design, just relocated. The gate's structural guarantee (recorded AUC ≥ v1 baseline − 0.02) is unchanged.

- [ ] **Step 1: Add `LAST_KNOWN_AUC_*` constants to `cri_scorers.py`**

Edit `src/uw_scan/cards/cri_scorers.py`, just below the existing `COMPOSITE_VERSION = 3` line (around line 30):

```python
# Last-known OOS AUC values for the current COMPOSITE_VERSION, measured by
# scripts/backtest_cri.py on the 20-year vol_index_daily history. These are
# the SOURCE OF TRUTH the OOS gate reads via the seed fixture in
# tests/integration/regime/conftest.py. Bumping COMPOSITE_VERSION REQUIRES
# updating both constants in the same diff — PR review checks that this
# update happened. The gate then verifies these recorded numbers are within
# BASELINE_TOLERANCE (0.02) of v1's published baseline (0.62 / 0.647).
#
# History:
#   v1 (frozen baseline): auc_dd5=0.620, auc_dd10=0.647 (pre-PR-58 notebook)
#   v3 (current):         auc_dd5=0.6343, auc_dd10=0.6329 (2026-05 backtest)
LAST_KNOWN_AUC_DD5: float = 0.6343
LAST_KNOWN_AUC_DD10: float = 0.6329
```

- [ ] **Step 2: Read the existing test**

Open `tests/integration/regime/test_cri_oos_gate.py`. The current shape: module-scoped `oos_summary` fixture reads `docs/research/regime/oos-summary.json` from disk, three tests read `versions[]` from it.

- [ ] **Step 3: Replace the fixture to read from DB**

Change the fixture and gate-helper functions:

```python
"""OOS gate for the CRI composite version currently in code.

Reads summary.oos.versions[] from the latest COMPLETED CRI run in
uw_scan.regime_backtest_runs. The previous on-disk
docs/research/regime/oos-summary.json source was retired in the regime
closure (2026-05); see
docs/superpowers/specs/2026-05-24-regime-research-closure-design.md.

Calibration-provenance contract:
  - The seed fixture (tests/integration/regime/conftest.py) reads
    `LAST_KNOWN_AUC_DD5` / `LAST_KNOWN_AUC_DD10` from cri_scorers.py to
    construct the v{COMPOSITE_VERSION} row.
  - Bumping COMPOSITE_VERSION REQUIRES updating both LAST_KNOWN_AUC_*
    constants in the same PR. PR review enforces this.
  - The gate then verifies recorded AUC >= v1 baseline - BASELINE_TOLERANCE.
  - If no completed run exists at the current version, the test FAILS (does
    NOT skip) — a silent skip would disable the regression gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from uw_scan.cards.cri_scorers import COMPOSITE_VERSION
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

V1_AUC_BASELINE: dict[str, float] = {"dd5": 0.620, "dd10": 0.647}
BASELINE_TOLERANCE = 0.02


@pytest.fixture
def oos_summary(seeded_db_empty_cards, seed_cri_backtest_run) -> dict[str, Any]:
    """Return summary.oos from the latest completed CRI run for the current version.

    Both fixtures are function-scoped (matching `seeded_db_empty_cards` from
    tests/integration/conftest.py — which calls _reset_and_migrate per test).
    `seed_cri_backtest_run` seeds the run; this fixture reads it back.
    """
    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    run = rb.find_latest_run("cri", composite_version=str(COMPOSITE_VERSION))
    assert run is not None, (
        f"no completed CRI run at composite_version={COMPOSITE_VERSION} "
        "in test DB — seed_cri_backtest_run fixture failed?"
    )
    oos = (run.get("summary") or {}).get("oos")
    assert oos is not None, "run.summary.oos missing — backtest produced no AUC"
    return oos


def _find(versions: list[dict], version: int) -> dict:
    matches = [v for v in versions if v.get("version") == version]
    assert matches, f"version={version} not present in summary.oos.versions"
    return matches[0]


def _current_version(versions: list[dict]) -> dict:
    non_v1 = [v for v in versions if v.get("version", 0) > 1]
    assert non_v1, "no non-v1 version in summary.oos.versions"
    return max(non_v1, key=lambda v: v["version"])


def test_v1_baseline_constants_match_summary(oos_summary) -> None:
    v1 = _find(oos_summary["versions"], 1)
    assert v1["auc_dd5"] == V1_AUC_BASELINE["dd5"]
    assert v1["auc_dd10"] == V1_AUC_BASELINE["dd10"]


def test_current_version_within_tolerance_on_dd5(oos_summary) -> None:
    current = _current_version(oos_summary["versions"])
    v1 = _find(oos_summary["versions"], 1)
    auc = current["auc_dd5"]
    assert auc is not None
    floor = v1["auc_dd5"] - BASELINE_TOLERANCE
    assert auc >= floor, (
        f"v{current['version']} dd5 AUC ({auc:.4f}) is more than "
        f"{BASELINE_TOLERANCE:.3f} below v1 baseline ({v1['auc_dd5']:.3f}). "
        "If this is an intentional calibration trade-off, update "
        "LAST_KNOWN_AUC_DD5 in cri_scorers.py AND V1_AUC_BASELINE['dd5'] in "
        "this file in the same PR."
    )


def test_current_version_within_tolerance_on_dd10(oos_summary) -> None:
    current = _current_version(oos_summary["versions"])
    v1 = _find(oos_summary["versions"], 1)
    auc = current["auc_dd10"]
    assert auc is not None
    floor = v1["auc_dd10"] - BASELINE_TOLERANCE
    assert auc >= floor, (
        f"v{current['version']} dd10 AUC ({auc:.4f}) is more than "
        f"{BASELINE_TOLERANCE:.3f} below v1 baseline ({v1['auc_dd10']:.3f}). "
        "If this is an intentional calibration trade-off, update "
        "LAST_KNOWN_AUC_DD10 in cri_scorers.py AND V1_AUC_BASELINE['dd10'] "
        "in this file in the same PR."
    )


def test_summary_documents_label_definitions(oos_summary) -> None:
    by_name = {label["name"]: label["definition"] for label in oos_summary["labels"]}
    assert "label_dd5" in by_name
    assert "label_dd10" in by_name
    assert "20 trading days" in by_name["label_dd5"]
    assert "60 trading days" in by_name["label_dd10"]
```

- [ ] **Step 4: Add the seed fixture**

Add to `tests/integration/regime/conftest.py` (create the file if it does not exist):

```python
"""Fixtures for regime integration tests.

`seed_cri_backtest_run` populates uw_scan.regime_backtest_runs with one
completed CRI run whose summary.oos.versions[] carries the LAST_KNOWN_AUC_*
constants from cri_scorers.py. The OOS gate test in test_cri_oos_gate.py
reads this run back. See the calibration-provenance contract in that file's
module docstring.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.cards.cri_scorers import (
    COMPOSITE_VERSION,
    LAST_KNOWN_AUC_DD5,
    LAST_KNOWN_AUC_DD10,
)
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


@pytest.fixture
def seed_cri_backtest_run(seeded_db_empty_cards) -> int:
    """Insert one completed CRI run + a minimal daily row into the test DB.

    Function-scoped, matching `seeded_db_empty_cards` which drops+migrates
    the schema per test. AUC numbers come from cri_scorers.py constants so
    a calibration PR's diff exposes any staleness.
    """
    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    existing = rb.find_latest_run("cri", composite_version=str(COMPOSITE_VERSION))
    if existing is not None:
        return int(existing["id"])

    run_id = rb.insert_run(
        indicator="cri",
        composite_version=str(COMPOSITE_VERSION),
        start_date=date(2007, 1, 3),
        end_date=date(2026, 5, 15),
        window_days=150,
        n_days=4873,
        params={"rolling_window": 150, "source": "seed_cri_backtest_run"},
        summary={
            "oos": {
                "as_of": "2026-05-25",
                "notebook": "scripts/backtest_cri.py",
                "method": (
                    "Forward-drawdown labels: dd5 = SPX -5% within 20 sessions; "
                    "dd10 = SPX -10% within 60 sessions."
                ),
                "labels": [
                    {"name": "label_dd5",
                     "definition": "SPX -5% drawdown within 20 trading days"},
                    {"name": "label_dd10",
                     "definition": "SPX -10% drawdown within 60 trading days"},
                ],
                "scores": [
                    {"model": "CRI v1 (frozen baseline)",
                     "auc_dd5": 0.620, "auc_vix30": None, "auc_dd10": 0.647},
                    {"model": f"CRI v{COMPOSITE_VERSION} (this run)",
                     "auc_dd5": LAST_KNOWN_AUC_DD5, "auc_vix30": None,
                     "auc_dd10": LAST_KNOWN_AUC_DD10},
                ],
                "versions": [
                    {"label": "CRI v1", "version": 1,
                     "auc_dd5": 0.620, "auc_dd10": 0.647,
                     "n_observations": 4873,
                     "notes": "Frozen baseline."},
                    {"label": f"CRI v{COMPOSITE_VERSION}",
                     "version": COMPOSITE_VERSION,
                     "auc_dd5": LAST_KNOWN_AUC_DD5,
                     "auc_dd10": LAST_KNOWN_AUC_DD10,
                     "n_observations": 4873,
                     "notes": (
                        "Recorded by scripts/backtest_cri.py against the 20y "
                        "vol_index_daily history. Bumping COMPOSITE_VERSION "
                        "in cri_scorers.py requires updating LAST_KNOWN_AUC_* "
                        "in the same diff."
                     )},
                ],
                "interpretation": (
                    "Seed reads LAST_KNOWN_AUC_* from cri_scorers.py — "
                    "calibration-provenance contract enforced in PR review."
                ),
            },
            "extras": {"named_crash_hits": {}, "fired_count": 0},
        },
        note="seed_cri_backtest_run fixture",
    )
    rb.bulk_insert_daily(
        run_id,
        [{"trade_date": date(2026, 5, 15), "score": 12.0, "level": "LOW",
          "payload": {}}],
    )
    rb.mark_run_completed(run_id)
    return run_id
```

- [ ] **Step 5: Run the gate test**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/regime/test_cri_oos_gate.py -v`
Expected: all 4 tests PASS via the seed fixture. NO skips.

- [ ] **Step 6: Verify the failure mode**

Temporarily lower the constant in `cri_scorers.py` to confirm the gate still bites:
```python
# In cri_scorers.py, change LAST_KNOWN_AUC_DD5 = 0.59 (below floor 0.62 - 0.02 = 0.60)
```
Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/regime/test_cri_oos_gate.py::test_current_version_within_tolerance_on_dd5 -v`
Expected: FAIL with the "more than 0.020 below v1 baseline" message AND the actionable hint about updating both constants.

Restore `LAST_KNOWN_AUC_DD5 = 0.6343` afterwards. **Before staging, verify the restoration:**

```bash
grep "LAST_KNOWN_AUC_DD5" src/uw_scan/cards/cri_scorers.py
# Expected: LAST_KNOWN_AUC_DD5: float = 0.6343
```

If the line still shows `0.59`, do NOT proceed to Step 7 — the failure-mode value is about to be committed.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/cards/cri_scorers.py \
        tests/integration/regime/test_cri_oos_gate.py \
        tests/integration/regime/conftest.py
git commit -m "test(regime): OOS gate reads DB with calibration-provenance constants"
```

---

## Task 8: `scripts/backtest_vcg.py`

**Files:**
- Create: `scripts/backtest_vcg.py`

- [ ] **Step 1: Confirm vol_index_daily has the credit-ETF series**

Run:
```bash
psql "$DATABASE_URL" -c "
  SELECT symbol, MIN(trade_date), MAX(trade_date), COUNT(*)
    FROM uw_scan.vol_index_daily
   WHERE symbol IN ('VIX','VVIX','HYG','JNK','LQD')
   GROUP BY symbol ORDER BY symbol;
"
```
Expected: HYG ≥ 2007-04-11, JNK ≥ 2007-12-04, LQD ≥ 2002-07-26 (but VVIX-bound to 2006-03-06).

If a credit ETF series is missing `adj_close` or the column doesn't exist on `vol_index_daily`, fall back to `close` and add an explicit warning log (see Step 3 below).

- [ ] **Step 2: Check which credit-ETF column to use**

Run: `psql "$DATABASE_URL" -c "\d uw_scan.vol_index_daily"`
Expected: columns include `close`, and possibly `adj_close`. If `adj_close` exists, use `COALESCE(adj_close, close)`. If not, use `close` only and add a `log.warning` that distribution-adjusted history is unavailable. The spec §8.2 requires adj_close for credit ETFs — if missing, this is a follow-up data-warehouse task; document it in the run's note field.

- [ ] **Step 3: Write the script**

Create `scripts/backtest_vcg.py`:

```python
#!/usr/bin/env python3
"""Backtest VCG (Volatility-Credit Gap) across the full available history.

Reads:
  - vol_index_daily for VIX, VVIX, and the credit proxy (HYG default)

Recomputes VCG for every aligned trading day. The aligned window is bounded
by the shortest series — usually the credit proxy. Uses adj_close for the
credit ETF (HYG/JNK/LQD distribute monthly; raw close would surface every
ex-dividend drop as a log-return spike).

Persists:
  - uw_scan.regime_backtest_runs (one row per invocation)
  - uw_scan.regime_backtest_daily (one row per aligned trading day post-burn-in)

Usage:
  uv run python scripts/backtest_vcg.py
  uv run python scripts/backtest_vcg.py --proxy LQD --note "LQD proxy A/B"
  uv run python scripts/backtest_vcg.py --start 2007-04-11 --end 2026-05-15
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path

import numpy as np
import psycopg

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards import vcg_scoring  # noqa: E402
from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION, MIN_BARS  # noqa: E402
from uw_scan.config import Settings  # noqa: E402
from uw_scan.storage.regime_backtest_repository import (  # noqa: E402
    RegimeBacktestRepository,
)

log = logging.getLogger("backtest_vcg")

# Same named events as the CRI backtest — symmetry across indicators.
NAMED_CRASH_DATES = {
    "2008-09-15": "Lehman bankruptcy",
    "2008-10-10": "GFC bottom area",
    "2010-05-06": "Flash crash",
    "2011-08-08": "US credit downgrade",
    "2015-08-24": "Black Monday (China)",
    "2018-02-05": "Volmageddon",
    "2018-12-24": "Q4 selloff trough",
    "2020-02-28": "COVID early break",
    "2020-03-16": "COVID circuit breaker",
    "2022-06-13": "Rate-hike vol",
    "2024-08-05": "Yen-carry unwind",
}

_VALID_PROXIES = ("HYG", "JNK", "LQD")


def _detect_adj_close(conn: psycopg.Connection, schema: str) -> bool:
    """Return True if vol_index_daily has an adj_close column."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = %s
               AND table_name = 'vol_index_daily'
               AND column_name = 'adj_close'
            """,
            (schema,),
        )
        return cur.fetchone() is not None


def fetch_aligned_series(
    conn: psycopg.Connection,
    schema: str,
    start: _date,
    end: _date,
    proxy: str,
    use_adj_close: bool,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Fetch and align VIX, VVIX, <proxy> on shared dates."""
    series: dict[str, dict[_date, float]] = {}
    with conn.cursor() as cur:
        for sym in ("VIX", "VVIX"):
            cur.execute(
                f"SELECT trade_date, close FROM {schema}.vol_index_daily "
                "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
                "AND close IS NOT NULL ORDER BY trade_date",
                (sym, start, end),
            )
            series[sym] = {r[0]: float(r[1]) for r in cur.fetchall()}

        credit_col = "COALESCE(adj_close, close)" if use_adj_close else "close"
        cur.execute(
            f"SELECT trade_date, {credit_col} FROM {schema}.vol_index_daily "
            "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
            f"AND {credit_col} IS NOT NULL ORDER BY trade_date",
            (proxy, start, end),
        )
        series[proxy] = {r[0]: float(r[1]) for r in cur.fetchall()}

    common = set(series["VIX"].keys()) & set(series["VVIX"].keys()) & set(series[proxy].keys())
    sorted_dates = sorted(common)
    aligned = {
        sym: np.array([series[sym][d] for d in sorted_dates], dtype=float)
        for sym in series
    }
    return aligned, [d.isoformat() for d in sorted_dates]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2007-01-01")
    p.add_argument("--end", default=_date.today().isoformat())
    p.add_argument("--proxy", default="HYG", choices=_VALID_PROXIES)
    p.add_argument("--note", default=None)
    args = p.parse_args()

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        use_adj_close = _detect_adj_close(conn, settings.db_schema)
        if not use_adj_close:
            log.warning(
                "vol_index_daily lacks adj_close column — falling back to raw "
                "close for %s; expect dividend-noise spikes in residuals.",
                args.proxy,
            )
        aligned, dates = fetch_aligned_series(
            conn, settings.db_schema, start, end, args.proxy, use_adj_close,
        )

    n = len(dates)
    log.info("aligned %d trading days for proxy=%s", n, args.proxy)
    if n < MIN_BARS + 10:
        log.error("not enough data: %d days, need at least %d", n, MIN_BARS + 10)
        return 1

    model = vcg_scoring.compute_vcg(
        aligned["VIX"], aligned["VVIX"], aligned[args.proxy],
    )

    # Walk every aligned bar from MIN_BARS onward; assemble daily rows.
    # Model arrays are length N-1 (log_returns drops one bar); per-day date
    # is dates[i+1] (matches run_analysis history convention at line 386).
    daily_rows: list[dict] = []
    interp_counter: Counter[str] = Counter()
    ro_count = edr_count = bounce_count = 0
    for i in range(MIN_BARS, len(model["residuals"])):
        date_idx = i + 1
        if date_idx >= len(dates):
            break
        day = vcg_scoring._interpretation_for_index(model, i)
        interp = day["interpretation"]
        interp_counter[interp] += 1
        if day["ro"]: ro_count += 1
        if day["edr"]: edr_count += 1
        if day["bounce"]: bounce_count += 1
        score = day.get("vcg_adj") or 0.0
        daily_rows.append(
            {
                "trade_date": _date.fromisoformat(dates[date_idx]),
                "score": float(score) if not math.isnan(float(score)) else 0.0,
                "level": interp,
                "payload": {
                    "vcg": day["vcg"],
                    "vcg_adj": day["vcg_adj"],
                    "residual": day["residual"],
                    "beta1_vvix": day["beta1_vvix"],
                    "beta2_vix": day["beta2_vix"],
                    "alpha": day["alpha"],
                    "vix": day["vix"],
                    "vvix": day["vvix"],
                    "credit_price": day["credit_price"],
                    "sign_ok": day["sign_ok"],
                    "ro": day["ro"], "edr": day["edr"],
                    "tier": day["tier"], "bounce": day["bounce"],
                    "pi_panic": day["pi_panic"],
                    "regime": day["regime"],
                },
            }
        )

    if not daily_rows:
        log.error("no rows after burn-in (MIN_BARS=%d)", MIN_BARS)
        return 1

    # Named-crash window: ±5 sessions around each event, with raw vcg + vcg_adj.
    iso_to_date_idx = {d: idx for idx, d in enumerate(dates)}
    named_crash_window: dict[str, list[dict]] = {}
    for iso, _name in NAMED_CRASH_DATES.items():
        if iso not in iso_to_date_idx:
            continue
        date_idx = iso_to_date_idx[iso]
        model_idx = date_idx - 1  # model arrays are length N-1
        window: list[dict] = []
        for offset in (-5, -3, -1, 0, 1, 3, 5):
            mi = model_idx + offset
            if mi < MIN_BARS or mi >= len(model["residuals"]):
                continue
            d = vcg_scoring._interpretation_for_index(model, mi)
            window.append({
                "offset_d": offset,
                "vcg": d["vcg"],
                "vcg_adj": d["vcg_adj"],
                "beta1": d["beta1_vvix"],
                "beta2": d["beta2_vix"],
                "sign_ok": d["sign_ok"],
                "interpretation": d["interpretation"],
                "vix": d["vix"],
            })
        if window:
            named_crash_window[iso] = window

    summary = {
        "oos": None,  # No defensible Y-label in V1 — see vcg-methodology.md §6.
        "extras": {
            "credit_proxy": args.proxy,
            "use_adj_close": bool(use_adj_close),
            "named_crash_window": named_crash_window,
            "interpretation_distribution": dict(interp_counter),
            "ro_count": ro_count,
            "edr_count": edr_count,
            "bounce_count": bounce_count,
        },
    }

    with psycopg.connect(settings.db_dsn()) as conn:
        rb = RegimeBacktestRepository(conn, schema=settings.db_schema)
        run_id = rb.insert_run(
            indicator="vcg",
            composite_version=str(COMPOSITE_VERSION),
            start_date=daily_rows[0]["trade_date"],
            end_date=daily_rows[-1]["trade_date"],
            window_days=vcg_scoring.OLS_WINDOW,  # OLS lookback as the "window"
            n_days=len(daily_rows),
            params={
                "proxy": args.proxy,
                "ols_window": vcg_scoring.OLS_WINDOW,
                "z_window": vcg_scoring.Z_WINDOW,
                "use_adj_close": bool(use_adj_close),
            },
            summary=summary,
            note=args.note,
        )
        rb.bulk_insert_daily(run_id, daily_rows)
        rb.mark_run_completed(run_id)

    log.info(
        "VCG backtest persisted: run_id=%d n=%d proxy=%s composite_version=%s",
        run_id, len(daily_rows), args.proxy, COMPOSITE_VERSION,
    )

    log.info("=== VCG ±5d named-crash window (proxy=%s) ===", args.proxy)
    for iso, window in named_crash_window.items():
        log.info("--- %s %s ---", iso, NAMED_CRASH_DATES[iso])
        log.info("  offset  vcg     vcg_adj  beta1   beta2   sign_ok  interp")
        for w in window:
            vcg_s = f"{w['vcg']:+.2f}" if w["vcg"] is not None else "  nan"
            adj_s = f"{w['vcg_adj']:+.2f}" if w["vcg_adj"] is not None else "  nan"
            b1_s = f"{w['beta1']:+.2f}" if w["beta1"] is not None else "  nan"
            b2_s = f"{w['beta2']:+.2f}" if w["beta2"] is not None else "  nan"
            log.info(
                "  %+d      %s    %s    %s   %s   %s    %s",
                w["offset_d"], vcg_s, adj_s, b1_s, b2_s,
                str(w["sign_ok"]).lower(), w["interpretation"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the script**

```bash
uv run python scripts/backtest_vcg.py --note "VCG v1 closure backtest"
```
Expected: `aligned ≥4500 trading days for proxy=HYG`, `VCG backtest persisted: run_id=…`, named-crash ±5d window table.

- [ ] **Step 5: Verify rows in DB**

```bash
psql "$DATABASE_URL" -c "
  SELECT id, indicator, composite_version, n_days, window_days,
         summary->'extras'->>'credit_proxy' AS proxy,
         jsonb_array_length(coalesce(summary->'extras'->'named_crash_window'->'2008-09-15', '[]'::jsonb)) AS lehman_window_n
    FROM uw_scan.regime_backtest_runs
   WHERE indicator = 'vcg'
   ORDER BY created_at DESC LIMIT 1;
"
psql "$DATABASE_URL" -c "
  SELECT level, COUNT(*)
    FROM uw_scan.regime_backtest_daily
   WHERE run_id = (SELECT MAX(id) FROM uw_scan.regime_backtest_runs WHERE indicator='vcg')
   GROUP BY level ORDER BY 2 DESC;
"
```
Expected: one VCG row, `proxy = 'HYG'`, `composite_version = '1'`, lehman_window_n ≈ 7, level distribution skewed to `NORMAL` (~70%) with `WATCH`/`EDR`/`PANIC` populated.

- [ ] **Step 6: Commit**

```bash
git add scripts/backtest_vcg.py
git commit -m "feat(backtest): add VCG v1 20-year backtest with named-crash window"
```

---

## Task 9: `docs/research/regime/vcg-methodology.md`

**Files:**
- Create: `docs/research/regime/vcg-methodology.md`

- [ ] **Step 1: Read the CRI methodology doc as the structural template**

Run: `wc -l docs/research/regime/cri-methodology.md && head -80 docs/research/regime/cri-methodology.md`
Expected: ~400 lines. Use its top-level section structure (`# What is …`, `# Mathematical specification`, `# Calibration constants`, `# Design decisions`, `# Web research summary` / `Academic primary sources`, `# Known limitations`, `# Version history`).

- [ ] **Step 2: Write the doc**

Create `docs/research/regime/vcg-methodology.md` with the 7 sections from spec §11.1. Required content per section:

1. **What VCG is** — residual-based regime indicator; orthogonalises credit-spread changes against expected vol (VVIX) and current vol (VIX); positive z = stress, negative z = capitulation.
2. **Mathematical specification** — 21-day rolling OLS `Δlog(credit) = α + β₁·Δlog(VVIX) + β₂·Δlog(VIX) + ε`; 63-day residual z-score; panic-π adjustment `π = clamp((VIX-40)/8, 0, 1)`, `vcg_adj = (1-π)·vcg`. Reference `src/uw_scan/cards/vcg_scoring.py`.
3. **Calibration constants and `COMPOSITE_VERSION = 1`** — table of every constant from `vcg_scoring.py` (`OLS_WINDOW=21`, `Z_WINDOW=63`, `VIX_PANIC_LOW=40`, `VIX_PANIC_HIGH=48`, `VIX_FLOOR=28`, `VIX_EDR=25`, `VCG_TRIGGER=2.0`, `VCG_RO_TRIGGER=2.5`, `BOUNCE_TRIGGER=-3.5`, `VVIX_EXTREME=120`, `VVIX_ELEVATED=100`). For each: stated value, "xenon-inherited; not re-derived against this DB" rationale, and the empirical frequency band derived from Task 8 Step 5's `interpretation_distribution` JSON output (e.g., `NORMAL: 3500 days (71%)`, `WATCH: 510 days (10%)`, etc.).
4. **Design decisions** — HYG as default credit proxy (most-liquid HY ETF with ≥18y history); adj_close for credit ETFs (monthly distributions); VVIX-then-VIX regression ordering; sign discipline (`β₁,β₂ ≤ 0`) gates the signal.
5. **Academic foundations** — verbatim from spec §4.2 table (Campbell-Taksler, Collin-Dufresne, Pasquariello, Park, Adrian et al.) plus §4.3's honest "does NOT justify" list.
6. **Known limitations** — single credit proxy at a time; one-tailed positive-residual asymmetry; weekend/holiday alignment sensitivity; HYG dividend noise; **and the panic-π hard limitation: when VIX ≥ 48, vcg_adj → 0 so the displayed `interpretation` is VIX-driven not residual-driven; always inspect raw `vcg` alongside the label for high-VIX regimes**.
7. **Version history** — `v1: as-ported from xenon (commit d3cbc08, 2026-04); calibration thresholds inherited verbatim; first DB-of-record backtest 2026-05-25 (this PR).` Document the v2-decision call from §11.3 here: the §8.3 diagnostic table was reviewed during execution and the verdict (defensible-as-ported / not defensible / needs work) is recorded inline.

Sub-budget: target ~500 lines. CRI's doc is ~400 lines; VCG has fewer thresholds but the academic-foundations section is larger.

- [ ] **Step 3: Commit**

```bash
git add docs/research/regime/vcg-methodology.md
git commit -m "docs(regime): add VCG methodology with academic foundations + COMPOSITE_VERSION"
```

---

## Task 10: Augment `cri-methodology.md` §5 with academic citations

**Files:**
- Modify: `docs/research/regime/cri-methodology.md`

- [ ] **Step 1: Locate §5 ("Web research summary")**

Run: `grep -n "^##\|^# " docs/research/regime/cri-methodology.md`
Expected: heading list showing §5 (or its equivalent — "Web research summary" / "Research sources").

- [ ] **Step 2: Add an "Academic primary sources" subsection**

Insert a new subsection at the end of the existing §5 with the four citations from spec §4.1 verbatim (Bollerslev-Tauchen-Zhou 2009, Park 2015, Baltussen et al. 2018, Driessen-Maenhout-Vilkov 2009). Each citation: full bibliographic info, DOI URL, one-paragraph relevance to the corresponding CRI component (VIX / VVIX / COR1M).

Cross-reference: in §2 (the CRI components walk-through), add a one-line "Academic foundation: [Author Year]" footer to each component's discussion pointing into the new §5 subsection.

- [ ] **Step 3: Commit**

```bash
git add docs/research/regime/cri-methodology.md
git commit -m "docs(regime): augment CRI methodology with academic primary sources"
```

---

## Task 11: Update `docs/research/regime/CLAUDE.md`

**Files:**
- Modify: `docs/research/regime/CLAUDE.md`

- [ ] **Step 1: Read existing rules**

Run: `cat docs/research/regime/CLAUDE.md`
Expected: a small file with CRI-only rules.

- [ ] **Step 2: Add VCG + DB-as-source-of-truth rules**

Append to the file (preserve existing rules):

```markdown
## VCG rules

- Before changing any threshold in `src/uw_scan/cards/vcg_scoring.py` (VCG_TRIGGER, VCG_RO_TRIGGER, BOUNCE_TRIGGER, VIX_FLOOR, VIX_EDR, VIX_PANIC_LOW, VIX_PANIC_HIGH, VVIX_ELEVATED, VVIX_EXTREME), update the relevant section of `vcg-methodology.md` with the new threshold and rationale in the SAME commit.
- VCG's v1 calibration is as-ported from xenon. Recalibration to v2 requires a separate spec under `docs/superpowers/specs/` — do not roll calibration changes into routine PRs.

## Backtest results live in Postgres

- After running a backtest (CRI or VCG), inspect via `SELECT * FROM uw_scan.regime_backtest_runs ORDER BY created_at DESC LIMIT 10;` — see the SQL cookbook in `closure-2026-05-24.md`.
- Do NOT commit CSV/MD/JSON output files from backtest runs. The legacy `cri-backtest.{md,csv}` and `oos-summary.json` files are scheduled for removal in the follow-up PR; the DB is the source of truth.
- `composite_version` provenance is derived from code constants (`cri_scorers.COMPOSITE_VERSION`, `vcg_scoring.COMPOSITE_VERSION`). Never override on the CLI.
```

- [ ] **Step 3: Commit**

```bash
git add docs/research/regime/CLAUDE.md
git commit -m "docs(regime): CLAUDE.md adds VCG + DB-source-of-truth rules"
```

---

## Task 12: Closure memo `docs/research/regime/closure-2026-05-24.md`

**Files:**
- Create: `docs/research/regime/closure-2026-05-24.md`

- [ ] **Step 1: Write the memo from spec §13**

Six sections per spec §13:

1. **What's done** — bullet list: both indicators have DB-of-record backtests; methodology docs with academic foundations; CLAUDE.md rules; OOS gate reads from DB with seed fixture
2. **What's queryable** — SQL cookbook with at minimum these queries:
   ```sql
   -- Latest CRI run with current code-constant composite_version
   SELECT * FROM uw_scan.regime_backtest_runs
    WHERE indicator='cri' AND completed_at IS NOT NULL
   ORDER BY created_at DESC LIMIT 1;

   -- Compare two CRI composite_versions side-by-side
   SELECT
     a.composite_version, a.summary->'oos'->'versions' AS versions_a,
     b.composite_version, b.summary->'oos'->'versions' AS versions_b
   FROM uw_scan.regime_backtest_runs a
   JOIN uw_scan.regime_backtest_runs b
     ON a.indicator='cri' AND b.indicator='cri'
    AND a.composite_version='3' AND b.composite_version='4-candidate'
    AND a.completed_at IS NOT NULL AND b.completed_at IS NOT NULL;

   -- Level distribution per calendar year for the latest CRI run
   SELECT date_trunc('year', trade_date)::date AS yr, level, COUNT(*)
     FROM uw_scan.regime_backtest_daily
    WHERE run_id = (SELECT MAX(id) FROM uw_scan.regime_backtest_runs
                     WHERE indicator='cri' AND completed_at IS NOT NULL)
    GROUP BY 1, 2 ORDER BY 1, 2;

   -- Named-crash VCG window
   SELECT id, composite_version,
          summary->'extras'->'named_crash_window'->'2020-03-16' AS covid_window
     FROM uw_scan.regime_backtest_runs
    WHERE indicator='vcg' AND completed_at IS NOT NULL
    ORDER BY created_at DESC LIMIT 1;
   ```

3. **What this enables** — sample research questions (per spec §13 item 3):
   - "Does VCG fire during regime X?" → SQL query template
   - "What does CRI v3 say about every Fed meeting day?" → SQL
   - "How would a candidate v4 calibration change CRI's 20y AUC?" → bump `COMPOSITE_VERSION` in `cri_scorers.py` on an experiment branch, re-run `scripts/backtest_cri.py --note "v4 candidate: VVIX floor 75"`, compare via the side-by-side query above

4. **What's deferred (with rationale)** — VCG v2 calibration (separate spec if owed by the diagnostic in §11.3); VCG OOS validation notebook (need Y-label); per-ticker GEX-as-regime (out of scope); Goyal-Saretto §1.5 generic schema (IPCA-specific)

5. **Open research questions** — pulled from `cri-methodology.md` §7 ("What we deliberately did not change") + any surfaced by VCG diagnostic

6. **How to extend** — for a future contributor: how to run a new calibration, where the math lives, version conventions, the no-CLI-override rule, the `completed_at IS NOT NULL` API filter

- [ ] **Step 2: Commit**

```bash
git add docs/research/regime/closure-2026-05-24.md
git commit -m "docs(regime): closure memo with SQL cookbook and deferred-work list"
```

---

## Task 13: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite**

Run: `uv run pytest -x`
Expected: all tests PASS. Watch for any drift in `tests/integration/api/test_regime_validation_endpoint.py`, `tests/integration/regime/`, `tests/integration/storage/test_regime_backtest_repository.py`, `tests/unit/reports/test_regime_backtest_report.py`.

- [ ] **Step 2: Manual API smoke**

```bash
# If the dev server is not running:
bash scripts/dev.sh &
sleep 5
curl -s http://127.0.0.1:8400/api/regime/validation > /tmp/regime_validation.json
jq '.backtest_csv_rows, (.oos.versions | length), (.oos | keys)' /tmp/regime_validation.json
```
Expected: backtest_csv_rows ≥ 4900, versions length ≥ 2, oos keys include `as_of`, `notebook`, `method`, `labels`, `scores`, `interpretation` (the Pydantic-modeled subset; `versions` is ignored by Pydantic but still in the dict on the wire).

- [ ] **Step 3: Web check (if a watchlist + dev server are running)**

Open `http://127.0.0.1:3001/regime` in a browser. The ValidationTab should render the backtest markdown table; the AUC numbers should match the DB run.

If the page is blank or shows a 500, check that `find_latest_run("cri")` returns a row — it requires `completed_at IS NOT NULL` AND `composite_version = '3'`. A common failure: the task-5 backtest was interrupted before `mark_run_completed`, leaving a NULL `completed_at`. Re-run `scripts/backtest_cri.py`.

- [ ] **Step 4: Verify the file fallback still works (defensive)**

Temporarily mask the DB run:
```bash
psql "$DATABASE_URL" -c "UPDATE uw_scan.regime_backtest_runs SET completed_at = NULL WHERE indicator='cri' AND composite_version='3';"
curl -s http://127.0.0.1:8400/api/regime/validation | jq '.backtest_csv_rows'
# Expected: still returns a non-zero count (file fallback hit).
psql "$DATABASE_URL" -c "UPDATE uw_scan.regime_backtest_runs SET completed_at = NOW() WHERE indicator='cri' AND composite_version='3' AND completed_at IS NULL;"
```

- [ ] **Step 5: Acceptance-criteria walk**

Manually walk each checkbox in spec §18 "Primary PR" section. Tick each one in the spec via a follow-up commit if all pass.

---

## Task 14: Open the PR

**Files:** none

- [ ] **Step 1: Push branch**

```bash
git status  # confirm no untracked files we want to commit
git push -u origin <branch-name>
```

(Branch name follows the `feat/` prefix per CLAUDE.md — `feat/regime-research-closure` is the natural choice.)

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(regime): close CRI + VCG research with Postgres-of-record" \
  --body "$(cat <<'EOF'
## Summary

- Persists CRI + VCG backtest results to `uw_scan.regime_backtest_runs` / `regime_backtest_daily` (migration 057)
- `/api/regime/validation` reads the DB run; falls back to the checked-in files during transition
- VCG reaches CRI parity: methodology doc, academic foundations, `COMPOSITE_VERSION` tracking, 20y backtest with named-crash window

## Why now

Standing rule violation: backtest analytical results were disk-only artifacts. This change makes calibration A/B tests SQL queries and gives VCG the research scaffolding CRI already had.

Design spec: `docs/superpowers/specs/2026-05-24-regime-research-closure-design.md`
Plan: `docs/superpowers/plans/2026-05-25-regime-research-closure-implementation.md`

## What is NOT in this PR

- Deletion of `cri-backtest.{md,csv}` and `oos-summary.json` — kept for the router file-fallback until the manual prod gate (≥1 completed CRI run in prod, see spec §10.4) is verified. A follow-up PR removes the files and the fallback block; the follow-up is mechanical and revertable.
- VCG OOS gate test — deferred until a defensible Y-label exists for the indicator.
- The `/api/regime/backtest/{indicator}/runs` listing endpoint — deferred until a UI consumer exists.

## Test plan

- [ ] `bash scripts/migrate.sh` clean-applies migration 057; second run is a no-op
- [ ] `uv run python scripts/backtest_cri.py --note "first DB-of-record run"` persists ≥4900 daily rows; `composite_version='3'`
- [ ] `uv run python scripts/backtest_vcg.py --note "VCG v1 closure backtest"` persists ≥4500 daily rows; HYG proxy; named-crash ±5d window populated
- [ ] `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_regime_backtest_repository.py tests/unit/reports/test_regime_backtest_report.py tests/integration/regime/ tests/integration/api/test_regime_validation_endpoint.py` — all pass
- [ ] `curl /api/regime/validation` returns 200 with **response keys** `{backtest_md, backtest_csv_rows, oos}` matching pre-PR (the `backtest_md` content differs because the DB run extends past the historical snapshot — that's expected)
- [ ] `/regime` page in the dev web app renders the validation tab unchanged

EOF
)"
```

- [ ] **Step 3: Wait for CI; address review comments**

If CI fails on the OOS gate: confirm the seed fixture was added to `tests/integration/regime/conftest.py` (Task 7 step 3) and that the CI test DB applies migrations via the existing conftest infrastructure.

---

## Self-Review Checklist

After all tasks above are implemented, walk this list one pass:

- [ ] **Spec coverage:** every spec §-section maps to a task above? (§4 academic foundations → Tasks 9 + 10; §6 schema → Task 1; §7 repo → Task 2; §8 scripts → Tasks 5 + 8; §9 API → Tasks 4 + 6; §10 file plan → covered in plan's "File Structure" + deferred-removal note; §11 VCG trail → Tasks 3 + 8 + 9; §12 CLAUDE.md → Tasks 10 + 11; §13 closure memo → Task 12; §14 order → matches Task 1→12 order; §18 acceptance → Task 13)
- [ ] **No placeholders:** grep your plan for `TBD`, `TODO`, `FIXME`, `XXX`, `<…>`, "fill in", "similar to" — none present
- [ ] **Type consistency:** `RegimeBacktestRepository` method signatures are identical between Task 2 (definition) and Tasks 5/6/7/8 (callers); `_interpretation_for_index` field names match between Task 3 (definition) and Task 8 (caller); `daily` rows have the same `{trade_date, score, level, payload}` shape between Tasks 2, 4, 5, 6, 7, 8
- [ ] **No drift between plan and spec:** if a number changed (e.g. tolerance, window size, AUC baseline), it's the same number in both files
- [ ] **Commit policy honored:** every commit message has no `Co-Authored-By: Claude` trailer; branch is `feat/…` not `codex/…`
- [ ] **Frequent commits:** each task ends with `git commit`; no monolithic end-of-plan commit
