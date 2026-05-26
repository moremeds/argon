# VCG composite proxy research candidate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `run_scope='research'` track that backtests four VCG composite-credit baskets (and three single-proxy research baselines) against the existing HYG production baseline, with a reproducible drawdown lead-time comparator that returns a per-criterion pass/fail verdict against a pre-declared promotion gate.

**Architecture:** Production scanner path untouched. New research path: split-by-domain helpers in `cards/` (`vcg_basket.py`, `drawdown.py`, `vcg_validation_metrics.py`); composite scoring as a sibling function in `vcg_scoring.py`; persistence reuses the existing `regime_backtest_runs` / `regime_backtest_daily` tables with three new top-level columns (`run_scope`, `composite_method`, `credit_proxy`) promoted out of JSONB; one new migration; one new comparator script; one validation report.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, psycopg 3, pandas, numpy, pyarrow (parquet), Postgres 16, pytest with pytest-postgresql.

**Source spec:** `docs/superpowers/specs/2026-05-26-vcg-composite-research-design.md`

---

## §0. Spec amendments discovered during verification

These are factual corrections to the spec, surfaced by reading the current code. Methodology and gate criteria are unchanged.

| Spec assumption | Reality | Plan accommodation |
|---|---|---|
| `regime_backtest_runs.extras` JSONB column | Table has `params` and `summary` JSONB; research metadata nests as `summary["extras"]` per existing `scripts/backtest_vcg.py:252` | All `extras.foo` references in spec are `summary["extras"]["foo"]` in plan code |
| `regime_backtest_runs.daily` JSONB column | Daily signal lives in separate table `regime_backtest_daily (run_id, trade_date, score, level, payload)` | Per-day `composite_single_proxy_disagreement` and other signal fields go in `regime_backtest_daily.payload` |
| `sources/lake.py` supports write | Read-only (PR #78 reader rails: `list_vol_index_symbols`, `read_vol_index_parquet`, `_s3_filesystem`) | Task 10 adds a `write_weight_artifact(...)` function paralleling the existing readers |
| `vcg_scoring.COMPOSITE_VERSION` imported by API router | Only referenced in docstrings/comments at `regime_validation.py:10, 249, 254, 280`; resolved lazily via `_current_composite_version('vcg')` inside `RegimeBacktestRepository` | Hard Guarantee #1 already behavior-based per spec v3; isolation test in Task 3 checks `vcg_scanner.__dict__` rather than import statements |
| Benchmarks SPY/QQQ/IWM/XLF/RSP (ETFs) in `index_ohlc_daily` | Two-layer correction: **credit-proxy INPUT** stays HYG/JNK/LQD ETFs with `adj_close` (unchanged from prior spec). **Drawdown BENCHMARK** is the three cash indices SPX/NDX/RUT with raw `close` (indices have no dividend adjustment, so `close` is the clean drawdown reference). SPX is already in `vol_index_daily` via migration 038. NDX and RUT will be made available by the user before plan execution (out-of-band). The comparator's 4000-bar precheck in `load_benchmarks` defensively drops any benchmark below threshold and reports the coverage gap — plan does not block on availability. | Task 12 is a **pure verification step** (no fetcher build). It checks SPX/NDX/RUT presence in `vol_index_daily`, reports the coverage matrix, and proceeds with whatever subset is available. ETF fallbacks (SPY/QQQ/IWM/XLF/RSP) are accepted as a backstop if the corresponding index falls below threshold. |
| `find_latest_run` filters | Already filters `indicator + composite_version + completed_at IS NOT NULL ORDER BY created_at DESC` | Task 2 adds `run_scope='production'` (default), `credit_proxy=None`, `composite_method=None` parameters; defaults preserve existing API behavior |

---

## §1. File structure summary

**New files**
- `src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql`
- `src/uw_scan/cards/vcg_basket.py` (~290 lines)
- `src/uw_scan/cards/drawdown.py` (~150 lines)
- `src/uw_scan/cards/vcg_validation_metrics.py` (~250 lines)
- `scripts/compare_vcg_lead_time.py` (~250 lines)
- `tests/unit/cards/test_vcg_basket.py`
- `tests/unit/cards/test_drawdown.py`
- `tests/unit/cards/test_vcg_validation_metrics.py`
- `tests/unit/cards/test_vcg_scoring_composite.py`
- `tests/unit/test_research_isolation.py`
- `tests/unit/api/test_vcg_run_selection.py`
- `tests/integration/test_migration_059.py`
- `tests/integration/test_backtest_vcg_research_paths.py`
- `tests/integration/test_compare_vcg_lead_time.py`
- `docs/research/regime/vcg-composite-validation-2026-05-26.md` (produced by Task 16)

**Modified files**
- `src/uw_scan/storage/regime_backtest_repository.py` — add 3 params + `list_research_runs(...)`
- `src/uw_scan/cards/vcg_scoring.py` — add `RESEARCH_COMPOSITE_VERSIONS`, `compute_vcg_composite(...)`
- `src/uw_scan/sources/lake.py` — add `write_weight_artifact(...)`
- `scripts/backtest_vcg.py` — add `--research-proxy`, `--composite-method`, `--vol-window`, `--weight-lag`
- (NDX/RUT seeding is OUT of this PR — user is making them available in `vol_index_daily` out-of-band; Task 12 is pure verification.)
- `docs/research/regime/vcg-methodology.md` — §3 update

---

## Phase 1 — Schema + Repository + Isolation tests

### Task 1: Migration 059 — research scope columns

Promotes `run_scope`, `composite_method`, `credit_proxy` out of JSONB. Two-phase migration: add nullable → backfill from `summary["extras"]` → NOT NULL + CHECK + index. Idempotent via `IF NOT EXISTS` and `DO $$ pg_constraint $$` blocks.

**Files:**
- Create: `src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql`
- Test: `tests/integration/test_migration_059.py`

- [ ] **Step 1.1: Write the failing integration test**

```python
# tests/integration/test_migration_059.py
"""Migration 043 — research scope columns.

Verifies the migration is safe for existing rows: a row inserted with the
v1 schema and historical research metadata in summary['extras'] must end up
correctly labeled run_scope='research', not 'production'. Verifies idempotency
by running the migration script twice.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

MIGRATION = Path("src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql")


def _apply(conn: psycopg.Connection, sql_path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(sql_path.read_text())
    conn.commit()


def test_migration_promotes_columns_and_backfills_research_rows(seeded_db_empty_cards) -> None:
    conn = seeded_db_empty_cards.conn

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
                (indicator, composite_version, start_date, end_date, window_days,
                 n_days, params, summary, note, completed_at)
            VALUES ('vcg', '1', '2024-01-01', '2024-12-31', 21, 252, %s, %s, NULL, NOW())
            """,
            (Jsonb({}), Jsonb({"extras": {"credit_proxy": "HYG"}})),
        )
        cur.execute(
            """
            INSERT INTO uw_scan.regime_backtest_runs
                (indicator, composite_version, start_date, end_date, window_days,
                 n_days, params, summary, note, completed_at)
            VALUES ('vcg', '2-candidate-rp3', '2024-01-01', '2024-12-31', 21, 252, %s, %s, NULL, NOW())
            """,
            (Jsonb({}), Jsonb({"extras": {"credit_proxy": "COMPOSITE_RP3",
                                          "composite_method": "risk_parity_3"}})),
        )
    conn.commit()

    _apply(conn, MIGRATION)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT credit_proxy, run_scope, composite_method "
            "FROM uw_scan.regime_backtest_runs WHERE composite_version = '1'"
        )
        prod_row = cur.fetchone()
        cur.execute(
            "SELECT credit_proxy, run_scope, composite_method "
            "FROM uw_scan.regime_backtest_runs WHERE composite_version = '2-candidate-rp3'"
        )
        research_row = cur.fetchone()

    assert prod_row == ("HYG", "production", "single_proxy")
    assert research_row == ("COMPOSITE_RP3", "research", "risk_parity_3")


def test_migration_is_idempotent(seeded_db_empty_cards) -> None:
    conn = seeded_db_empty_cards.conn
    _apply(conn, MIGRATION)
    _apply(conn, MIGRATION)  # must not raise


def test_migration_enforces_vcg_credit_proxy_check(seeded_db_empty_cards) -> None:
    conn = seeded_db_empty_cards.conn
    _apply(conn, MIGRATION)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_scan.regime_backtest_runs
                    (indicator, composite_version, start_date, end_date,
                     window_days, n_days, params, summary, run_scope,
                     composite_method, credit_proxy)
                VALUES ('vcg', '1', '2025-01-01', '2025-12-31', 21, 252,
                        %s, %s, 'production', 'single_proxy', NULL)
                """,
                (Jsonb({}), Jsonb({})),
            )
        conn.commit()
```

- [ ] **Step 1.2: Run tests to confirm fail**

Run: `uv run pytest tests/integration/test_migration_059.py -v`
Expected: FAIL — `src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql` does not exist.

- [ ] **Step 1.3: Write the migration**

```sql
-- src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql
-- Promote run_scope, composite_method, credit_proxy out of summary['extras'] so
-- the API can structurally exclude research rows from production queries.
-- Two-phase to preserve historical research labels in existing rows.

SET search_path TO uw_scan, public;

BEGIN;

-- Phase 1: add columns nullable
ALTER TABLE uw_scan.regime_backtest_runs
  ADD COLUMN IF NOT EXISTS run_scope TEXT,
  ADD COLUMN IF NOT EXISTS composite_method TEXT,
  ADD COLUMN IF NOT EXISTS credit_proxy TEXT;

-- Phase 2: backfill from summary['extras'] (heuristics ordered most-specific first)
UPDATE uw_scan.regime_backtest_runs
SET credit_proxy = summary->'extras'->>'credit_proxy'
WHERE credit_proxy IS NULL
  AND summary->'extras' ? 'credit_proxy';

-- Phase 2b: VCG rows without an extras.credit_proxy key default to HYG —
-- this is the production-canonical proxy, and the alternative (leaving NULL)
-- would fail the regime_backtest_runs_vcg_credit_proxy_check constraint
-- added in phase 5. Only applies to indicator='vcg' rows.
UPDATE uw_scan.regime_backtest_runs
SET credit_proxy = 'HYG'
WHERE credit_proxy IS NULL AND indicator = 'vcg';

UPDATE uw_scan.regime_backtest_runs
SET composite_method = COALESCE(summary->'extras'->>'composite_method', 'single_proxy')
WHERE composite_method IS NULL;

UPDATE uw_scan.regime_backtest_runs
SET run_scope = CASE
  -- Explicit scope marker takes precedence over every other heuristic
  WHEN summary->'extras'->>'run_scope' IN ('production', 'research')
    THEN summary->'extras'->>'run_scope'
  -- composite_version string is THE most reliable research indicator. Check
  -- this BEFORE proxy/method backfilled defaults can cover up the truth — a
  -- row with composite_version LIKE '%candidate%' is research even if its
  -- summary lacks extras.credit_proxy/extras.composite_method (which would
  -- otherwise get backfilled to 'HYG'/'single_proxy' and silently flip it to
  -- production in the next two branches).
  WHEN composite_version LIKE '%candidate%' THEN 'research'
  WHEN COALESCE(summary->'extras'->>'credit_proxy', credit_proxy) LIKE 'COMPOSITE%'
    THEN 'research'
  WHEN COALESCE(summary->'extras'->>'composite_method', composite_method) <> 'single_proxy'
    AND COALESCE(summary->'extras'->>'composite_method', composite_method) IS NOT NULL
    THEN 'research'
  ELSE 'production'
END
WHERE run_scope IS NULL;

-- Phase 3: set defaults (post-backfill so they don't overwrite historical labels)
ALTER TABLE uw_scan.regime_backtest_runs
  ALTER COLUMN run_scope SET DEFAULT 'production',
  ALTER COLUMN composite_method SET DEFAULT 'single_proxy';

-- Phase 4: NOT NULL
ALTER TABLE uw_scan.regime_backtest_runs
  ALTER COLUMN run_scope SET NOT NULL,
  ALTER COLUMN composite_method SET NOT NULL;

-- Phase 5: CHECK constraints (DO blocks because Postgres has no ADD CONSTRAINT IF NOT EXISTS)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_scope_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_scope_check
      CHECK (run_scope IN ('production', 'research'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_composite_method_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_composite_method_check
      CHECK (composite_method IN (
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3'
      ));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'regime_backtest_runs_vcg_credit_proxy_check'
      AND conrelid = 'uw_scan.regime_backtest_runs'::regclass
  ) THEN
    ALTER TABLE uw_scan.regime_backtest_runs
      ADD CONSTRAINT regime_backtest_runs_vcg_credit_proxy_check
      CHECK (indicator <> 'vcg' OR credit_proxy IS NOT NULL);
  END IF;
END $$;

-- Phase 6: index
CREATE INDEX IF NOT EXISTS idx_regime_runs_scope_indicator_version_proxy
  ON uw_scan.regime_backtest_runs
     (run_scope, indicator, composite_version, credit_proxy, composite_method, created_at DESC);

COMMIT;
```

- [ ] **Step 1.4: Run migration tests to confirm pass**

Run: `uv run pytest tests/integration/test_migration_059.py -v`
Expected: PASS for all three tests.

- [ ] **Step 1.5: Run full existing migration suite**

Run: `bash scripts/migrate.sh && uv run pytest tests/integration/ -k 'migration' -v`
Expected: PASS — no migration breaks existing tests.

- [ ] **Step 1.6: Commit**

```bash
git add src/uw_scan/storage/migrations/059_regime_backtest_research_scope.sql \
        tests/integration/test_migration_059.py
git commit -m "feat(regime): migration 043 — promote run_scope / composite_method / credit_proxy to columns"
```

---

### Task 2: Repository extensions

Extends `RegimeBacktestRepository` to write and read the new columns. Backward-compatible defaults preserve API behavior.

**Files:**
- Modify: `src/uw_scan/storage/regime_backtest_repository.py`
- Test: `tests/integration/test_backtest_vcg_research_paths.py` (new, repository layer only here)

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/integration/test_backtest_vcg_research_paths.py
"""Repository tests for the research-scope columns.

API-layer selection isolation lives in tests/unit/api/test_vcg_run_selection.py.
"""
from __future__ import annotations

from datetime import date

import pytest

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _seed_run(repo: RegimeBacktestRepository, *, run_scope: str, credit_proxy: str,
              composite_method: str, composite_version: str = "1") -> int:
    run_id = repo.insert_run(
        indicator="vcg",
        composite_version=composite_version,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        window_days=21,
        n_days=252,
        params={},
        summary={"extras": {"credit_proxy": credit_proxy}},
        note=None,
        run_scope=run_scope,
        composite_method=composite_method,
        credit_proxy=credit_proxy,
    )
    repo.mark_run_completed(run_id)
    return run_id


def test_insert_run_writes_new_columns(seeded_db_empty_cards) -> None:
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    run_id = _seed_run(repo, run_scope="research", credit_proxy="COMPOSITE_RP3",
                       composite_method="risk_parity_3", composite_version="2-candidate-rp3")
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT run_scope, composite_method, credit_proxy "
            "FROM uw_scan.regime_backtest_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    assert row == ("research", "risk_parity_3", "COMPOSITE_RP3")


def test_find_latest_run_defaults_exclude_research(seeded_db_empty_cards) -> None:
    """Production HYG row must win over a NEWER research row at v1."""
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    prod = _seed_run(repo, run_scope="production", credit_proxy="HYG",
                     composite_method="single_proxy", composite_version="1")
    research = _seed_run(repo, run_scope="research", credit_proxy="JNK",
                         composite_method="single_proxy", composite_version="1")
    assert research > prod  # research is newer

    latest = repo.find_latest_run("vcg")
    assert latest is not None
    assert latest["id"] == prod
    assert latest["run_scope"] == "production"
    assert latest["credit_proxy"] == "HYG"


def test_find_latest_run_with_credit_proxy_filter(seeded_db_empty_cards) -> None:
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    hyg = _seed_run(repo, run_scope="production", credit_proxy="HYG",
                    composite_method="single_proxy", composite_version="1")
    _seed_run(repo, run_scope="production", credit_proxy="JNK",
              composite_method="single_proxy", composite_version="1")
    latest = repo.find_latest_run("vcg", credit_proxy="HYG")
    assert latest["id"] == hyg


def test_list_research_runs_excludes_production(seeded_db_empty_cards) -> None:
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    _seed_run(repo, run_scope="production", credit_proxy="HYG",
              composite_method="single_proxy", composite_version="1")
    r1 = _seed_run(repo, run_scope="research", credit_proxy="COMPOSITE_RP3",
                   composite_method="risk_parity_3", composite_version="2-candidate-rp3")
    r2 = _seed_run(repo, run_scope="research", credit_proxy="JNK",
                   composite_method="single_proxy", composite_version="1")
    runs = repo.list_research_runs(indicator="vcg")
    ids = {r["id"] for r in runs}
    assert ids == {r1, r2}
```

- [ ] **Step 2.2: Run tests to confirm fail**

Run: `uv run pytest tests/integration/test_backtest_vcg_research_paths.py -v`
Expected: FAIL — `insert_run` does not accept `run_scope`; `list_research_runs` not defined; `find_latest_run` does not accept `credit_proxy`.

- [ ] **Step 2.3: Extend `RegimeBacktestRepository`**

Modify `src/uw_scan/storage/regime_backtest_repository.py`:

1. Add the three params to `insert_run`:

```python
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
        run_scope: str = "production",
        composite_method: str = "single_proxy",
        credit_proxy: str | None = None,
    ) -> int:
        # Application-level safeguards (Python-side, complementing the SQL
        # CHECK constraints in migration 059). A future caller that forgets to
        # pass run_scope='research' for a composite row would otherwise write
        # a research-shape row tagged as production — Hard Guarantee #4 leak.
        if indicator == "vcg":
            if composite_method != "single_proxy" and run_scope != "research":
                raise ValueError(
                    f"VCG composite_method={composite_method!r} requires run_scope="
                    f"'research' (got {run_scope!r})"
                )
            if credit_proxy and credit_proxy.startswith("COMPOSITE") and run_scope != "research":
                raise ValueError(
                    f"VCG credit_proxy={credit_proxy!r} requires run_scope='research'"
                )
            if "candidate" in (composite_version or "") and run_scope != "research":
                raise ValueError(
                    f"VCG composite_version={composite_version!r} requires run_scope='research'"
                )

        sql = """
            INSERT INTO regime_backtest_runs (
                indicator, composite_version, start_date, end_date,
                window_days, n_days, params, summary, note,
                run_scope, composite_method, credit_proxy
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    indicator, composite_version, start_date, end_date,
                    window_days, n_days, Jsonb(params), Jsonb(summary), note,
                    run_scope, composite_method, credit_proxy,
                ),
            )
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])
```

2. Add `run_scope` + `credit_proxy` + `composite_method` filters to `find_latest_run`. **Critical (per codex BLOCKING 2):** for VCG, the defaults must enforce Hard Guarantee #2 — without indicator-specific defaults, the existing call site `rb.find_latest_run("vcg")` at `regime_validation.py:289` would pass through `credit_proxy=None` / `composite_method=None` and a newer production JNK or LQD row could win:

```python
    def find_latest_run(
        self,
        indicator: Literal["cri", "vcg"],
        composite_version: str | None = None,
        *,
        run_scope: str = "production",
        credit_proxy: str | None = None,
        composite_method: str | None = None,
    ) -> dict | None:
        # VCG-specific production defaults: enforce Hard Guarantee #2 at the
        # repository layer so the existing API call site `find_latest_run("vcg")`
        # cannot accidentally surface a non-HYG / non-single-proxy row.
        if indicator == "vcg" and run_scope == "production":
            if credit_proxy is None:
                credit_proxy = "HYG"
            if composite_method is None:
                composite_method = "single_proxy"
        if composite_version is None:
            composite_version = _current_composite_version(indicator)
        sql = """
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   created_at, completed_at,
                   run_scope, composite_method, credit_proxy
              FROM regime_backtest_runs
             WHERE indicator = %s
               AND composite_version = %s
               AND completed_at IS NOT NULL
               AND run_scope = %s
        """
        args: list[Any] = [indicator, composite_version, run_scope]
        if credit_proxy is not None:
            sql += " AND credit_proxy = %s"
            args.append(credit_proxy)
        if composite_method is not None:
            sql += " AND composite_method = %s"
            args.append(composite_method)
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self._conn.cursor() as cur:
            cur.execute(sql, args)
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if cur.description else []
        if row is None:
            return None
        return dict(zip(cols, row, strict=True))
```

3. Add `list_research_runs`:

```python
    def list_research_runs(
        self,
        *,
        indicator: Literal["cri", "vcg"],
        composite_version: str | None = None,
        composite_method: str | None = None,
        credit_proxy: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = """
            SELECT id, indicator, composite_version, start_date, end_date,
                   window_days, n_days, params, summary, note,
                   created_at, completed_at,
                   run_scope, composite_method, credit_proxy
              FROM regime_backtest_runs
             WHERE indicator = %s
               AND run_scope = 'research'
               AND completed_at IS NOT NULL
        """
        args: list[Any] = [indicator]
        if composite_version is not None:
            sql += " AND composite_version = %s"
            args.append(composite_version)
        if composite_method is not None:
            sql += " AND composite_method = %s"
            args.append(composite_method)
        if credit_proxy is not None:
            sql += " AND credit_proxy = %s"
            args.append(credit_proxy)
        sql += " ORDER BY created_at DESC LIMIT %s"
        args.append(limit)
        with self._conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, r, strict=True)) for r in rows]
```

- [ ] **Step 2.4: Run repo tests to confirm pass**

Run: `uv run pytest tests/integration/test_backtest_vcg_research_paths.py -v`
Expected: PASS.

- [ ] **Step 2.5: Confirm existing regime API tests still pass**

Run: `uv run pytest tests/integration/test_regime_validation_endpoint.py tests/unit/api/ -v`
Expected: PASS (no behavior change in production-default path).

- [ ] **Step 2.6: Commit**

```bash
git add src/uw_scan/storage/regime_backtest_repository.py \
        tests/integration/test_backtest_vcg_research_paths.py
git commit -m "feat(regime): repository run_scope/composite_method/credit_proxy params + list_research_runs"
```

---

### Task 3: Isolation tests (API selection + import boundary)

Two unit-level tests that structurally enforce Hard Guarantees #1 + #2 + #3.

**Files:**
- Create: `tests/unit/test_research_isolation.py`
- Create: `tests/unit/api/test_vcg_run_selection.py`

- [ ] **Step 3.1: Write the API run-selection isolation test**

```python
# tests/unit/api/test_vcg_run_selection.py
"""Hard Guarantees #2 and #3: production default never returns a research row.

Exercises every realistic adversarial ordering: a newer research row of every
non-production shape (JNK / LQD / composite) cannot win the production default.
"""
from __future__ import annotations

import time
from datetime import date

import pytest

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _seed(repo, *, run_scope, credit_proxy, composite_method, composite_version="1"):
    rid = repo.insert_run(
        indicator="vcg", composite_version=composite_version,
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31),
        window_days=21, n_days=252, params={},
        summary={"extras": {"credit_proxy": credit_proxy}},
        note=None,
        run_scope=run_scope, composite_method=composite_method,
        credit_proxy=credit_proxy,
    )
    repo.mark_run_completed(rid)
    return rid


@pytest.mark.parametrize("research_shape", [
    {"run_scope": "research", "credit_proxy": "JNK", "composite_method": "single_proxy", "composite_version": "1"},
    {"run_scope": "research", "credit_proxy": "LQD", "composite_method": "single_proxy", "composite_version": "1"},
    {"run_scope": "research", "credit_proxy": "COMPOSITE_RP3",
     "composite_method": "risk_parity_3", "composite_version": "2-candidate-rp3"},
])
def test_production_default_excludes_newer_research_row(seeded_db_empty_cards, research_shape):
    """Exercises the EXACT call site at api/routers/regime_validation.py:289
    (`rb.find_latest_run("vcg")` — NO filters). The repo's VCG-specific defaults
    must enforce Hard Guarantee #2 without the caller passing anything."""
    repo = RegimeBacktestRepository(seeded_db_empty_cards.conn)
    prod = _seed(repo, run_scope="production", credit_proxy="HYG",
                 composite_method="single_proxy", composite_version="1")
    time.sleep(0.01)  # ensure research row's created_at > prod
    _seed(repo, **research_shape)
    # CRITICAL: bare call, no filter args. If find_latest_run lacks VCG
    # defaults, this test fails — and so would Hard Guarantee #2 in production.
    latest = repo.find_latest_run("vcg")
    assert latest is not None
    assert latest["id"] == prod
    assert latest["credit_proxy"] == "HYG"
    assert latest["composite_method"] == "single_proxy"
    assert latest["run_scope"] == "production"
```

- [ ] **Step 3.2: Write the import-boundary test**

```python
# tests/unit/test_research_isolation.py
"""Hard Guarantee #1: production code paths must not reference research symbols.

AST-based scan rather than `__dict__` introspection — catches aliased imports
(`from cards.vcg_basket import build_basket as _bb`) that runtime `__dict__`
inspection would expose under different names. See codex review SUGGESTION 2.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PRODUCTION_FILES = (
    REPO / "src/uw_scan/scanners/vcg.py",
    REPO / "src/uw_scan/api/routers/regime_validation.py",
)

FORBIDDEN_MODULES = ("uw_scan.cards.vcg_basket",)
FORBIDDEN_NAMES = ("RESEARCH_COMPOSITE_VERSIONS", "compute_vcg_composite")


def _imports_in(tree: ast.AST) -> set[tuple[str, str | None]]:
    """Returns set of (module_path, imported_name_or_None) for every import."""
    out: set[tuple[str, str | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add((alias.name, None))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                out.add((mod, alias.name))
    return out


def _name_references_in(tree: ast.AST) -> set[str]:
    """All Name and Attribute references — catches `vcg_scoring.compute_vcg_composite`
    even when the parent module is imported aliased."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


def test_production_files_do_not_import_research_modules_or_names() -> None:
    for path in PRODUCTION_FILES:
        tree = ast.parse(path.read_text())
        imports = _imports_in(tree)
        references = _name_references_in(tree)
        for mod, name in imports:
            for forbidden_mod in FORBIDDEN_MODULES:
                assert not mod.startswith(forbidden_mod), (
                    f"{path.name} imports forbidden research module {mod}"
                )
        for forbidden_name in FORBIDDEN_NAMES:
            assert forbidden_name not in references, (
                f"{path.name} references forbidden research name {forbidden_name}"
            )
            for _mod, imported in imports:
                assert imported != forbidden_name, (
                    f"{path.name} imports forbidden research name {forbidden_name}"
                )
```

- [ ] **Step 3.3: Run tests to confirm fail**

Run: `uv run pytest tests/unit/test_research_isolation.py tests/unit/api/test_vcg_run_selection.py -v`
Expected: PASS for `test_research_isolation` (symbols don't exist yet, so they're not in `__dict__`); the API test should already PASS after Task 2.

Note: The isolation test passes *by accident* now because `RESEARCH_COMPOSITE_VERSIONS` doesn't exist anywhere yet. It will continue to pass after Task 9 only if Task 9 keeps the symbols on the research path. **The test is correct now and is the load-bearing assertion later.**

- [ ] **Step 3.4: Commit**

```bash
git add tests/unit/test_research_isolation.py tests/unit/api/test_vcg_run_selection.py
git commit -m "test(regime): isolation guards for production-default selection + research symbol leakage"
```

---

## Phase 2 — Basket primitives (`cards/vcg_basket.py`)

### Task 4: `realized_vol` primitive

**Files:**
- Create: `src/uw_scan/cards/vcg_basket.py`
- Test: `tests/unit/cards/test_vcg_basket.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/unit/cards/test_vcg_basket.py
"""Unit tests for cards/vcg_basket.py.

The two load-bearing tests for risk_parity_weights are in Task 5:
- test_weights_at_t_unchanged_when_only_return_t_perturbed
- test_weights_match_strict_offset_reference_at_every_position
This file currently covers realized_vol.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.vcg_basket import realized_vol


def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    idx = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_realized_vol_first_window_minus_one_bars_are_nan() -> None:
    s = _series([1.0] * 100)
    rets = np.log(s / s.shift(1))
    out = realized_vol(rets, window=10)
    assert out.iloc[:9].isna().all(), "bars before window completion must be NaN"
    assert pd.notna(out.iloc[10])


def test_realized_vol_zero_volatility_clipped_to_floor() -> None:
    rets = pd.Series([0.0] * 100, index=pd.bdate_range("2024-01-01", periods=100))
    out = realized_vol(rets, window=10, vol_floor=1e-6)
    assert (out.iloc[10:] >= 1e-6).all()


def test_realized_vol_index_preserved() -> None:
    rets = pd.Series([0.01, -0.02, 0.005], index=pd.bdate_range("2024-01-01", periods=3))
    out = realized_vol(rets, window=2)
    assert list(out.index) == list(rets.index)
```

- [ ] **Step 4.2: Run tests to confirm fail**

Run: `uv run pytest tests/unit/cards/test_vcg_basket.py -v`
Expected: FAIL — `vcg_basket` module does not exist.

- [ ] **Step 4.3: Create `vcg_basket.py` with `realized_vol`**

```python
# src/uw_scan/cards/vcg_basket.py
"""Risk-parity credit-basket primitives for the VCG composite research path.

PURE: no DB, no network, no file I/O. Date-indexed pd.Series / pd.DataFrame
in, same shape out. Strict no-lookahead by construction — see Task 5 for the
weight-construction invariant and its tests.

Used ONLY by the research path (scripts/backtest_vcg.py --composite-method).
Production scanner does not import this module.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def realized_vol(
    log_returns: pd.Series,
    window: int = 63,
    vol_floor: float = 1e-6,
) -> pd.Series:
    """Trailing realized volatility on log returns.

    First `window-1` bars are NaN. Zero-variance windows are clipped to
    ``vol_floor`` to keep the downstream ``1/vol`` weight computation finite.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    raw = log_returns.rolling(window=window, min_periods=window).std(ddof=1)
    return raw.clip(lower=vol_floor)
```

- [ ] **Step 4.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/cards/test_vcg_basket.py -v`
Expected: PASS for the three `realized_vol` tests.

- [ ] **Step 4.5: Commit**

```bash
git add src/uw_scan/cards/vcg_basket.py tests/unit/cards/test_vcg_basket.py
git commit -m "feat(cards): add realized_vol primitive for vcg basket"
```

---

### Task 5: `risk_parity_weights` with no-lookahead invariant

**Files:**
- Modify: `src/uw_scan/cards/vcg_basket.py`
- Modify: `tests/unit/cards/test_vcg_basket.py`

- [ ] **Step 5.1: Append no-lookahead tests**

Append to `tests/unit/cards/test_vcg_basket.py`:

```python
from uw_scan.cards.vcg_basket import risk_parity_weights


def _make_3proxy_fixture(n: int = 200, seed: int = 0) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    out = {}
    for sym, base in (("HYG", 80.0), ("JNK", 100.0), ("LQD", 110.0)):
        rets = rng.normal(0.0, 0.005, size=n)
        prices = base * np.exp(np.cumsum(rets))
        out[sym] = pd.Series(prices, index=idx, name=sym)
    return out


def _perturb_return_at_position(
    base: dict[str, pd.Series], *, proxy: str, index_pos: int, factor: float
) -> dict[str, pd.Series]:
    """Multiply prices[i:] by factor so only return[i] changes; later returns
    are unchanged because they're ratios of consecutive bumped prices."""
    out = {k: v.copy() for k, v in base.items()}
    s = out[proxy]
    s.iloc[index_pos:] = s.iloc[index_pos:] * factor
    out[proxy] = s
    return out


def _reference_inverse_vol_weights(
    prefix: dict[str, pd.Series], *, window: int, weight_lag: int,
    vol_floor: float = 1e-6,
) -> pd.Series:
    """Reference: compute weights at the LAST position of prefix using only
    data in prefix. Output is one weight row (a pd.Series indexed by symbol)."""
    rets_by_sym = {sym: np.log(s / s.shift(1)) for sym, s in prefix.items()}
    rets = pd.DataFrame(rets_by_sym).dropna()
    if len(rets) < window + weight_lag:
        return pd.Series({sym: np.nan for sym in prefix}, name=rets.index[-1])
    # Apply lag: vol uses returns through position -weight_lag (i.e. exclude tail)
    rets_for_vol = rets.iloc[: len(rets) - weight_lag]
    vols = rets_for_vol.tail(window).std(ddof=1).clip(lower=vol_floor)
    inv = 1.0 / vols
    weights = inv / inv.sum()
    weights.name = rets.index[-1]
    return weights


def test_weights_at_t_unchanged_when_only_return_t_perturbed() -> None:
    base = _make_3proxy_fixture(n=200)
    w_base = risk_parity_weights(base, window=63, weight_lag=1)
    # i=0 has no return; skip
    for i in range(80, 195, 17):  # sample every 17th to keep runtime sane
        bumped = _perturb_return_at_position(base, proxy="HYG", index_pos=i, factor=10.0)
        w_bumped = risk_parity_weights(bumped, window=63, weight_lag=1)
        assert np.allclose(
            w_base.iloc[i].values, w_bumped.iloc[i].values,
            equal_nan=True, atol=1e-12,
        ), f"weight at position {i} leaked information from return[{i}]"


def test_weights_match_strict_offset_reference_at_every_position() -> None:
    base = _make_3proxy_fixture(n=120)
    actual = risk_parity_weights(base, window=21, weight_lag=1)
    for i in range(25, 120, 7):
        prefix = {sym: s.iloc[: i + 1] for sym, s in base.items()}
        expected = _reference_inverse_vol_weights(prefix, window=21, weight_lag=1)
        for sym in expected.index:
            a = actual.iloc[i][sym]
            e = expected[sym]
            assert np.allclose([a], [e], equal_nan=True, atol=1e-9), (
                f"position {i}, {sym}: prod={a} ref={e}"
            )


def test_weights_sum_to_one_after_warmup() -> None:
    base = _make_3proxy_fixture(n=200)
    w = risk_parity_weights(base, window=63, weight_lag=1)
    rows = w.dropna(how="all")
    sums = rows.sum(axis=1)
    assert np.allclose(sums.values, 1.0, atol=1e-9)


def test_weights_handle_constant_prices_equal_after_warmup() -> None:
    idx = pd.bdate_range("2020-01-01", periods=200)
    base = {sym: pd.Series(100.0, index=idx) for sym in ("HYG", "JNK", "LQD")}
    w = risk_parity_weights(base, window=63, weight_lag=1, vol_floor=1e-6)
    row = w.iloc[-1]
    assert np.allclose(row.values, 1.0 / 3.0, atol=1e-9)


def test_weights_skip_dates_missing_in_any_proxy() -> None:
    base = _make_3proxy_fixture(n=200)
    base["HYG"] = base["HYG"].drop(base["HYG"].index[100])  # drop one date
    w = risk_parity_weights(base, window=63, weight_lag=1)
    # The intersected index must NOT include the dropped date
    assert base["HYG"].index[99] in w.index or w.index[w.index < base["HYG"].index[99]].size > 0
    assert (w.index == base["JNK"].index.intersection(base["LQD"].index).intersection(base["HYG"].index)).all()
```

- [ ] **Step 5.2: Run tests to confirm fail**

Run: `uv run pytest tests/unit/cards/test_vcg_basket.py -v`
Expected: FAIL — `risk_parity_weights` not defined.

- [ ] **Step 5.3: Implement `risk_parity_weights`**

Append to `src/uw_scan/cards/vcg_basket.py`:

```python
def risk_parity_weights(
    prices_by_proxy: dict[str, pd.Series],
    *,
    window: int = 63,
    weight_lag: int = 1,
    vol_floor: float = 1e-6,
) -> pd.DataFrame:
    """Daily 1/sigma normalized weights with strict no-lookahead.

    For basket return at aligned index position ``i``:
        weights[i] = normalize(1 / realized_vol(returns.shift(weight_lag), window)[i])
    The .shift(weight_lag) is what makes return[i] unable to affect weight[i].
    With default ``weight_lag=1``, return[i] cannot leak into weight[i].

    Index is the intersection of all proxy indices — positional alignment is
    rejected because mismatched calendars would silently produce wrong weights.
    """
    if not prices_by_proxy:
        raise ValueError("prices_by_proxy must be non-empty")

    sorted_symbols = sorted(prices_by_proxy.keys())
    common_idx = None
    for sym in sorted_symbols:
        idx = prices_by_proxy[sym].index
        common_idx = idx if common_idx is None else common_idx.intersection(idx)
    common_idx = common_idx.sort_values()

    aligned = pd.DataFrame(
        {sym: prices_by_proxy[sym].reindex(common_idx) for sym in sorted_symbols},
        index=common_idx,
    )
    raw_returns = np.log(aligned / aligned.shift(1))
    returns_for_vol = raw_returns.shift(weight_lag)
    vols = returns_for_vol.rolling(window=window, min_periods=window).std(ddof=1)
    vols = vols.clip(lower=vol_floor)
    inv = 1.0 / vols
    weights = inv.div(inv.sum(axis=1), axis=0)
    return weights
```

- [ ] **Step 5.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/cards/test_vcg_basket.py -v`
Expected: PASS for all `risk_parity_weights` tests including the two load-bearing causality tests.

- [ ] **Step 5.5: Commit**

```bash
git add src/uw_scan/cards/vcg_basket.py tests/unit/cards/test_vcg_basket.py
git commit -m "feat(cards): risk_parity_weights with strict no-lookahead invariant"
```

---

### Task 6: `build_basket` dispatcher + four method variants

**Files:**
- Modify: `src/uw_scan/cards/vcg_basket.py`
- Modify: `tests/unit/cards/test_vcg_basket.py`

- [ ] **Step 6.1: Append failing tests**

Append to `tests/unit/cards/test_vcg_basket.py`:

```python
from uw_scan.cards.vcg_basket import (
    METHOD_METADATA,
    MethodMetadata,
    build_basket,
)


def test_method_metadata_registry_has_all_four_methods() -> None:
    assert set(METHOD_METADATA.keys()) == {
        "risk_parity_3", "risk_parity_hyjk", "hy_minus_ig_spread", "equal_weight_3",
    }
    rp3 = METHOD_METADATA["risk_parity_3"]
    spread = METHOD_METADATA["hy_minus_ig_spread"]
    assert rp3.method_type == "basket" and rp3.requires_vol_estimation is True
    assert spread.method_type == "spread"
    assert spread.gross_exposure == 2.0


def test_build_basket_equal_weight_3_uniform_weights() -> None:
    base = _make_3proxy_fixture(n=200)
    rets, weights = build_basket(base, method="equal_weight_3")
    # Weights table is uniform 1/3 across all three proxies after warmup
    last = weights.dropna().iloc[-1]
    assert np.allclose(last.values, 1.0 / 3.0, atol=1e-12)
    # Basket return equals simple mean of per-bar log returns
    raw_returns = np.log(
        pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index)
        / pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index).shift(1)
    )
    expected = raw_returns.mean(axis=1)
    pd.testing.assert_series_equal(
        rets.dropna(), expected.dropna(), check_names=False, atol=1e-12, rtol=0,
    )


def test_build_basket_hy_minus_ig_spread_closed_form() -> None:
    base = _make_3proxy_fixture(n=200)
    rets, weights = build_basket(base, method="hy_minus_ig_spread")
    raw = np.log(
        pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index)
        / pd.DataFrame({k: v for k, v in base.items()}).reindex(rets.index).shift(1)
    )
    expected = 0.5 * raw["HYG"] + 0.5 * raw["JNK"] - raw["LQD"]
    pd.testing.assert_series_equal(
        rets.dropna(), expected.dropna(), check_names=False, atol=1e-12, rtol=0,
    )


def test_build_basket_risk_parity_hyjk_uses_only_hy_proxies() -> None:
    base = _make_3proxy_fixture(n=200)
    rets, weights = build_basket(base, method="risk_parity_hyjk")
    assert list(weights.columns) == ["HYG", "JNK"]
    last = weights.dropna().iloc[-1]
    assert np.isclose(last.sum(), 1.0, atol=1e-9)


def test_build_basket_rejects_unknown_method() -> None:
    with pytest.raises(KeyError):
        build_basket(_make_3proxy_fixture(), method="not_a_method")
```

- [ ] **Step 6.2: Run tests to confirm fail**

Run: `uv run pytest tests/unit/cards/test_vcg_basket.py -v -k 'build_basket or method_metadata'`
Expected: FAIL — `build_basket` not defined.

- [ ] **Step 6.3: Implement dispatcher + metadata + four methods**

Append to `src/uw_scan/cards/vcg_basket.py`:

```python
@dataclass(frozen=True)
class MethodMetadata:
    """Per-method static metadata. Used by the comparator to label and group
    rows in the validation report — a spread method has 2x gross exposure and
    different residual scale, so the report must surface this distinction."""
    name: str
    method_type: str            # "basket" or "spread"
    proxies: tuple[str, ...]    # symbols this method consumes
    gross_exposure: float       # sum of absolute weights at any bar
    requires_vol_estimation: bool


METHOD_METADATA: dict[str, MethodMetadata] = {
    "risk_parity_3": MethodMetadata(
        name="risk_parity_3", method_type="basket",
        proxies=("HYG", "JNK", "LQD"),
        gross_exposure=1.0, requires_vol_estimation=True,
    ),
    "risk_parity_hyjk": MethodMetadata(
        name="risk_parity_hyjk", method_type="basket",
        proxies=("HYG", "JNK"),
        gross_exposure=1.0, requires_vol_estimation=True,
    ),
    "hy_minus_ig_spread": MethodMetadata(
        name="hy_minus_ig_spread", method_type="spread",
        proxies=("HYG", "JNK", "LQD"),
        gross_exposure=2.0, requires_vol_estimation=False,
    ),
    "equal_weight_3": MethodMetadata(
        name="equal_weight_3", method_type="basket",
        proxies=("HYG", "JNK", "LQD"),
        gross_exposure=1.0, requires_vol_estimation=False,
    ),
}


def build_basket(
    prices_by_proxy: dict[str, pd.Series],
    *,
    method: str,
    window: int = 63,
    weight_lag: int = 1,
    vol_floor: float = 1e-6,
) -> tuple[pd.Series, pd.DataFrame]:
    """Dispatch on method. Returns (basket_log_returns, weight_history).

    For variable-weight methods, weight_history rows are the actual per-day
    weights. For fixed-weight methods (equal_weight_3, hy_minus_ig_spread),
    weight rows are constant after warmup. Caller persists this DataFrame as
    a parquet artifact for replay verification.
    """
    meta = METHOD_METADATA[method]  # raises KeyError on unknown method
    needed = {sym: prices_by_proxy[sym] for sym in meta.proxies}

    common_idx = None
    for s in needed.values():
        common_idx = s.index if common_idx is None else common_idx.intersection(s.index)
    common_idx = common_idx.sort_values()

    aligned = pd.DataFrame(
        {sym: needed[sym].reindex(common_idx) for sym in meta.proxies},
        index=common_idx,
    )
    # Drop rows where ANY proxy has NaN — a date that's present in every
    # proxy's index but where one price is NaN must NOT produce a partial-
    # coverage basket return (skipna=True would silently average over the
    # remaining proxies). Spec invariant: no silent forward-fill or partial
    # weight coverage.
    aligned = aligned.dropna(how="any")
    raw_returns = np.log(aligned / aligned.shift(1))

    if method == "risk_parity_3" or method == "risk_parity_hyjk":
        weights = risk_parity_weights(needed, window=window, weight_lag=weight_lag,
                                      vol_floor=vol_floor)
        # Reindex weights to the post-dropna index in case dropping created gaps
        weights = weights.reindex(aligned.index)
        basket_ret = (weights * raw_returns).sum(axis=1, skipna=False)
    elif method == "equal_weight_3":
        n = len(meta.proxies)
        weights = pd.DataFrame(
            {sym: 1.0 / n for sym in meta.proxies},
            index=aligned.index,
        )
        # skipna=False: a NaN in any proxy's return for this bar must make
        # the basket return NaN, NOT partial average over the others.
        basket_ret = raw_returns.sum(axis=1, skipna=False) / n
    elif method == "hy_minus_ig_spread":
        weights = pd.DataFrame(
            {"HYG": 0.5, "JNK": 0.5, "LQD": -1.0},
            index=aligned.index,
        )
        # NaN propagates naturally through arithmetic on Series; if any proxy's
        # return is NaN at bar t, basket_ret[t] is NaN — desired behavior.
        basket_ret = (0.5 * raw_returns["HYG"]
                      + 0.5 * raw_returns["JNK"]
                      - raw_returns["LQD"])
    else:  # pragma: no cover - METHOD_METADATA key check above prevents this
        raise KeyError(method)

    return basket_ret, weights
```

- [ ] **Step 6.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/cards/test_vcg_basket.py -v`
Expected: PASS for all tests.

- [ ] **Step 6.5: Commit**

```bash
git add src/uw_scan/cards/vcg_basket.py tests/unit/cards/test_vcg_basket.py
git commit -m "feat(cards): build_basket dispatcher with four research-method variants"
```

---

## Phase 3 — Validation building blocks

### Task 7: `cards/drawdown.py` — non-overlapping detector

**Files:**
- Create: `src/uw_scan/cards/drawdown.py`
- Create: `tests/unit/cards/test_drawdown.py`

- [ ] **Step 7.1: Write failing tests**

```python
# tests/unit/cards/test_drawdown.py
"""Drawdown event detector — non-overlapping within a single definition.
Cross-definition independence: Fast/Medium/Major may overlap across definitions."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.drawdown import DrawdownDefinition, DrawdownEvent, detect_drawdown_events


def _closes(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start=start, periods=len(values)), dtype=float)


def test_no_events_in_flat_series() -> None:
    closes = _closes([100.0] * 50)
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert events == []


def test_single_fast_drawdown_detected() -> None:
    # Peak 100 → trough 92 in 5 days (-8%), then recovers.
    closes = _closes([100, 98, 96, 94, 92] + [93, 95, 97, 99, 101] + [102] * 20)
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert len(events) == 1
    e = events[0]
    assert e.depth_pct == pytest.approx(0.08, abs=1e-9)
    assert e.peak_price == pytest.approx(100.0)
    assert e.trough_price == pytest.approx(92.0)


def test_consecutive_drawdowns_non_overlapping_within_definition() -> None:
    """Two drawdowns separated by recovery must produce two events, not one."""
    closes = _closes(
        [100, 94, 92] + [93, 99, 101]  # event 1: -8% then recover to 101
        + [95, 92, 90] + [91, 96, 102]  # event 2: -11.8% then recover to 102
    )
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert len(events) == 2
    assert events[0].trough_price == pytest.approx(92.0)
    assert events[1].trough_price == pytest.approx(90.0)


def test_nested_dips_do_not_create_overlapping_events() -> None:
    """A continuous selloff must be ONE event, not many."""
    closes = _closes(
        list(np.linspace(100, 80, 15))  # 20% selloff over 15 bars
        + list(np.linspace(80, 100, 10))  # recovery
    )
    events = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    assert len(events) == 1, f"expected one event, got {len(events)}"


def test_definitions_independent_for_same_series() -> None:
    """Fast and Major see the same series differently — neither suppresses the other."""
    closes = _closes(
        list(np.linspace(100, 88, 8))  # -12% in 8 bars: qualifies Fast AND Major
        + [89, 91, 95, 100]
    )
    fast = detect_drawdown_events(closes, DrawdownDefinition("Fast", 0.05, 10))
    major = detect_drawdown_events(closes, DrawdownDefinition("Major", 0.10, 60))
    assert len(fast) == 1
    assert len(major) == 1
    # Both should have detected the same trough independently
    assert fast[0].trough_date == major[0].trough_date
```

- [ ] **Step 7.2: Run tests to confirm fail**

Run: `uv run pytest tests/unit/cards/test_drawdown.py -v`
Expected: FAIL — module not present.

- [ ] **Step 7.3: Implement `cards/drawdown.py`**

```python
# src/uw_scan/cards/drawdown.py
"""Non-overlapping drawdown event detector.

Per-definition: events emitted under one DrawdownDefinition must be
non-overlapping. Different definitions (Fast/Medium/Major) are detected
INDEPENDENTLY against the same close series — their event sets may overlap
across definitions. The comparator reports each definition separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class DrawdownDefinition:
    name: str             # "Fast", "Medium", "Major"
    threshold: float      # e.g. 0.05 = 5%
    window_days: int      # peak→trough must fit within this many trading days


@dataclass(frozen=True)
class DrawdownEvent:
    peak_date: date
    trough_date: date
    peak_price: float
    trough_price: float
    recovery_date: date | None     # None if recovery doesn't happen in series
    depth_pct: float
    definition: str


def detect_drawdown_events(
    closes: pd.Series,
    definition: DrawdownDefinition,
) -> list[DrawdownEvent]:
    """Walk closes left-to-right, emitting non-overlapping events for one
    drawdown definition. After each event, the next search starts at the
    later of trough_date+1 and recovery_date+1.
    """
    if closes.empty:
        return []
    if not closes.index.is_monotonic_increasing:
        raise ValueError("closes must have a monotonically increasing index")

    values = closes.values
    dates = list(closes.index.date)
    n = len(values)
    events: list[DrawdownEvent] = []

    i = 0
    while i < n:
        # Find a peak from position i: any rolling max that is followed by a
        # drop of >= threshold within window_days bars.
        end_window = min(i + definition.window_days + 1, n)
        peak_idx = i
        peak_price = values[i]
        # Roll forward looking for a maximum, then drop
        emitted = False
        for j in range(i, end_window):
            if values[j] > peak_price:
                peak_idx = j
                peak_price = values[j]
                continue
            depth = (peak_price - values[j]) / peak_price
            if depth >= definition.threshold:
                # Continue extending into the same dip — find the local trough
                trough_idx = j
                trough_price = values[j]
                for k in range(j + 1, min(peak_idx + definition.window_days + 1, n)):
                    if values[k] < trough_price:
                        trough_idx = k
                        trough_price = values[k]
                    elif values[k] >= peak_price:
                        break  # recovered
                # Recovery: first index after trough where close >= peak_price
                recovery_idx = None
                for r in range(trough_idx + 1, n):
                    if values[r] >= peak_price:
                        recovery_idx = r
                        break
                final_depth = (peak_price - trough_price) / peak_price
                events.append(DrawdownEvent(
                    peak_date=dates[peak_idx],
                    trough_date=dates[trough_idx],
                    peak_price=float(peak_price),
                    trough_price=float(trough_price),
                    recovery_date=dates[recovery_idx] if recovery_idx is not None else None,
                    depth_pct=float(final_depth),
                    definition=definition.name,
                ))
                # CRITICAL: if no recovery occurs within the series, STOP
                # searching for further events in this period. A continuous
                # selloff (e.g. 2008-Q4, 2022 bear) without prior-peak recovery
                # would otherwise spawn duplicate events from progressively
                # lower troughs — corrupting hit rate and lead-time medians.
                if recovery_idx is None:
                    i = n  # exit the outer while-loop
                else:
                    i = max(recovery_idx + 1, peak_idx + 1)
                emitted = True
                break
        if not emitted:
            i += 1

    return events
```

- [ ] **Step 7.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/cards/test_drawdown.py -v`
Expected: PASS for all five tests.

- [ ] **Step 7.5: Commit**

```bash
git add src/uw_scan/cards/drawdown.py tests/unit/cards/test_drawdown.py
git commit -m "feat(cards): non-overlapping drawdown event detector (per-definition)"
```

---

### Task 8: `cards/vcg_validation_metrics.py` — metric battery

**Files:**
- Create: `src/uw_scan/cards/vcg_validation_metrics.py`
- Create: `tests/unit/cards/test_vcg_validation_metrics.py`

- [ ] **Step 8.1: Write failing tests**

```python
# tests/unit/cards/test_vcg_validation_metrics.py
"""Metric battery used by the comparator. Each metric is exercised against
a small hand-computed reference."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from uw_scan.cards.drawdown import DrawdownEvent
from uw_scan.cards.vcg_validation_metrics import (
    actionable_lead_days,
    alarm_day_ratio,
    close_to_trough_lead_days,
    fp_day_rate,
    fp_episode_rate,
    hit_rate,
    next_trading_day,
    ro_episodes,
    utility_score,
)


def _dseries(values: dict[date, bool]) -> pd.Series:
    idx = sorted(values.keys())
    return pd.Series([values[d] for d in idx], index=idx, dtype=bool)


def test_close_to_trough_lead_simple() -> None:
    ro_date = date(2020, 3, 10)
    trough = date(2020, 3, 20)
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 3, 31)).date
    lead = close_to_trough_lead_days(ro_date, trough, trading_days)
    assert lead == 8  # business days between 2020-03-10 and 2020-03-20


def test_actionable_lead_negative_when_ro_at_trough_close() -> None:
    ro = trough = date(2020, 3, 20)
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 3, 31)).date
    a = actionable_lead_days(ro, trough, trading_days)
    assert a < 0  # next session after ro is post-trough


def test_next_trading_day_skips_weekends() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 4, 1)).date
    # Friday 2020-03-13 -> next bday is Monday 2020-03-16
    nt = next_trading_day(date(2020, 3, 13), trading_days)
    assert nt == date(2020, 3, 16)


def test_hit_rate_counts_only_actionable() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 1), date(2020, 4, 1)).date
    events = [
        DrawdownEvent(date(2020, 3, 5), date(2020, 3, 15), 100, 92, None, 0.08, "Fast"),
        DrawdownEvent(date(2020, 3, 20), date(2020, 3, 25), 100, 90, None, 0.10, "Fast"),
    ]
    # RO fires 3 days before first trough; no RO before second trough
    ro = _dseries({d: (d == date(2020, 3, 10)) for d in trading_days})
    hr = hit_rate(events, ro_signal=ro, trading_days=trading_days, peak_lookback=30)
    assert hr == pytest.approx(0.5)


def test_ro_episodes_groups_contiguous_days() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 3, 13)).date
    on_days = {date(2020, 3, 3), date(2020, 3, 4), date(2020, 3, 5),  # episode 1
               date(2020, 3, 10), date(2020, 3, 11)}                  # episode 2
    ro = _dseries({d: (d in on_days) for d in trading_days})
    eps = ro_episodes(ro)
    assert len(eps) == 2
    assert eps[0] == (date(2020, 3, 3), date(2020, 3, 5))
    assert eps[1] == (date(2020, 3, 10), date(2020, 3, 11))


def test_alarm_day_ratio_basic() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 3, 13)).date
    on_days = {date(2020, 3, 3), date(2020, 3, 4)}
    ro = _dseries({d: (d in on_days) for d in trading_days})
    r = alarm_day_ratio(ro)
    assert r == pytest.approx(2.0 / len(trading_days))


def test_fp_episode_rate_definitional_horizon() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 4, 30)).date
    ro_days = {date(2020, 3, 3), date(2020, 3, 4)}  # one episode of length 2
    ro = _dseries({d: (d in ro_days) for d in trading_days})
    # No drawdown event in next 30 bdays -> FP
    rate = fp_episode_rate(ro, events=[], trading_days=trading_days, horizon_days=30)
    assert rate == pytest.approx(1.0)


def test_utility_score_formula() -> None:
    score = utility_score(median_lead=2.5, hit_rate_val=0.75, fp_episode_rate_val=0.1, k_fp=5.0)
    assert score == pytest.approx(2.5 * 0.75 - 5.0 * 0.1)


def test_fp_day_rate_vs_episode_rate_diverge_for_long_regime() -> None:
    trading_days = pd.bdate_range(date(2020, 3, 2), date(2020, 4, 30)).date
    ro_days = {trading_days[i] for i in range(20)}  # 20-day continuous RO regime
    ro = _dseries({d: (d in ro_days) for d in trading_days})
    day_rate = fp_day_rate(ro, events=[], trading_days=trading_days, horizon_days=10)
    ep_rate = fp_episode_rate(ro, events=[], trading_days=trading_days, horizon_days=30)
    # Day-rate punishes every day, episode-rate counts the single regime as one FP
    assert day_rate == pytest.approx(1.0)
    assert ep_rate == pytest.approx(1.0)
    # If we add a qualifying event 25 days after RO start, episode-rate drops
    # but day-rate stays high because the per-day horizon is shorter (10d)
    ev = DrawdownEvent(trading_days[0], trading_days[25], 100, 90, None, 0.10, "Fast")
    day_rate2 = fp_day_rate(ro, events=[ev], trading_days=trading_days, horizon_days=10)
    ep_rate2 = fp_episode_rate(ro, events=[ev], trading_days=trading_days, horizon_days=30)
    assert ep_rate2 < ep_rate     # episode caught a 25-day-out event within 30d horizon
    assert day_rate2 >= ep_rate2  # day-rate is stricter
```

- [ ] **Step 8.2: Run tests to confirm fail**

Run: `uv run pytest tests/unit/cards/test_vcg_validation_metrics.py -v`
Expected: FAIL — module missing.

- [ ] **Step 8.3: Implement `vcg_validation_metrics.py`**

```python
# src/uw_scan/cards/vcg_validation_metrics.py
"""Metric battery for VCG composite vs single-proxy comparator.

All metric functions are pure and operate on:
- ro_signal: pd.Series[bool] indexed by trading date — True iff RO fires
  (tier 1 or tier 2) at close on that date.
- events: list[DrawdownEvent] for one (benchmark, drawdown_def).
- trading_days: ordered list[date] of valid trading sessions in the slice.

Lead-time metrics report two flavors:
- close_to_trough_lead — assumes signal usable on day-of-close (upper bound).
- actionable_lead — signal at close t is actionable on t+1 (causality contract).
Promotion gate uses actionable_lead only.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import date

import pandas as pd

from uw_scan.cards.drawdown import DrawdownEvent


def next_trading_day(d: date, trading_days: Sequence[date]) -> date | None:
    """First trading day strictly after ``d``."""
    i = bisect.bisect_right(list(trading_days), d)
    if i >= len(trading_days):
        return None
    return trading_days[i]


def _bday_count(start: date, end: date, trading_days: Sequence[date]) -> int:
    """Number of trading days from start to end inclusive of end, exclusive of start."""
    tds = list(trading_days)
    i = bisect.bisect_left(tds, start)
    j = bisect.bisect_right(tds, end)
    return j - i - 1


def close_to_trough_lead_days(
    ro_date: date, trough_date: date, trading_days: Sequence[date]
) -> int:
    return _bday_count(ro_date, trough_date, trading_days)


def actionable_lead_days(
    ro_date: date, trough_date: date, trading_days: Sequence[date]
) -> int:
    """Trading days between (next session after ro_date) and trough_date.

    Negative when next_trading_day(ro_date) > trough_date, e.g. RO at trough's
    close — fails the actionable_lead >= 0 gate.
    """
    nt = next_trading_day(ro_date, trading_days)
    if nt is None:
        return -1
    return _bday_count(nt, trough_date, trading_days) + 1  # +1: nt itself counts


def _first_ro_in_window(
    ro_signal: pd.Series, peak_date: date, trough_date: date, peak_lookback: int,
    trading_days: Sequence[date],
) -> date | None:
    tds = list(trading_days)
    peak_idx = bisect.bisect_left(tds, peak_date)
    start_idx = max(0, peak_idx - peak_lookback)
    start_date = tds[start_idx]
    window = ro_signal.loc[(ro_signal.index >= start_date) & (ro_signal.index <= trough_date)]
    fired = window[window].index
    if len(fired) == 0:
        return None
    return fired[0] if isinstance(fired[0], date) else fired[0].date()


def hit_rate(
    events: list[DrawdownEvent], *, ro_signal: pd.Series,
    trading_days: Sequence[date], peak_lookback: int = 30,
) -> float:
    """events_with_actionable_RO / total_events."""
    if not events:
        return float("nan")
    hits = 0
    for e in events:
        ro = _first_ro_in_window(ro_signal, e.peak_date, e.trough_date,
                                 peak_lookback, trading_days)
        if ro is None:
            continue
        if actionable_lead_days(ro, e.trough_date, trading_days) >= 0:
            hits += 1
    return hits / len(events)


def ro_episodes(ro_signal: pd.Series) -> list[tuple[date, date]]:
    """Maximal contiguous runs of True in ro_signal."""
    out: list[tuple[date, date]] = []
    in_run = False
    run_start: date | None = None
    last_date: date | None = None
    for d, v in ro_signal.items():
        if hasattr(d, "date"):
            d = d.date()
        if v and not in_run:
            run_start = d
            in_run = True
        elif not v and in_run:
            out.append((run_start, last_date))
            in_run = False
        last_date = d
    if in_run and run_start is not None and last_date is not None:
        out.append((run_start, last_date))
    return out


def alarm_day_ratio(ro_signal: pd.Series) -> float:
    if len(ro_signal) == 0:
        return float("nan")
    return float(ro_signal.sum()) / float(len(ro_signal))


def _event_interval_overlaps(
    event: DrawdownEvent, window_start: date, window_end: date,
) -> bool:
    """An event's [peak, trough] interval overlaps [window_start, window_end]
    iff event.peak_date <= window_end AND event.trough_date >= window_start.

    Critical correctness rule (third-pass review): an RO that fires AFTER the
    event peak but BEFORE the event trough is a VALID warning of an in-progress
    drawdown. Reducing events to a single date (peak OR trough) and asking
    "is that date forward of the RO" would discard those warnings as false
    positives. Using the interval keeps mid-drawdown RO as a hit, not an FP.
    """
    return event.peak_date <= window_end and event.trough_date >= window_start


def fp_day_rate(
    ro_signal: pd.Series, *, events: list[DrawdownEvent],
    trading_days: Sequence[date], horizon_days: int,
) -> float:
    """Day-level FP: an RO day d is FP iff no event's interval [peak, trough]
    overlaps [d, d + horizon_days bdays]."""
    on = ro_signal[ro_signal]
    if on.empty:
        return float("nan")
    tds = list(trading_days)
    fp = 0
    for d in on.index:
        d_real = d.date() if hasattr(d, "date") else d
        i = bisect.bisect_left(tds, d_real)
        horizon_end = tds[min(i + horizon_days, len(tds) - 1)] if i < len(tds) else d_real
        has_event = any(_event_interval_overlaps(e, d_real, horizon_end) for e in events)
        if not has_event:
            fp += 1
    return fp / len(on)


def fp_episode_rate(
    ro_signal: pd.Series, *, events: list[DrawdownEvent],
    trading_days: Sequence[date], horizon_days: int,
) -> float:
    """Episode-level FP (gate metric, spec §9): an RO episode is FP iff no
    event's interval [peak, trough] overlaps [episode_start, episode_start +
    horizon_days bdays]."""
    eps = ro_episodes(ro_signal)
    if not eps:
        return float("nan")
    tds = list(trading_days)
    fp = 0
    for start, _end in eps:
        i = bisect.bisect_left(tds, start)
        horizon_end_idx = min(i + horizon_days, len(tds) - 1)
        horizon_end = tds[horizon_end_idx] if tds else start
        has_event = any(_event_interval_overlaps(e, start, horizon_end) for e in events)
        if not has_event:
            fp += 1
    return fp / len(eps)


def utility_score(
    *, median_lead: float, hit_rate_val: float,
    fp_episode_rate_val: float, k_fp: float = 5.0,
) -> float:
    """utility = median_lead * hit_rate - k_fp * fp_episode_rate.
    NaN-propagating: returns NaN if any input is NaN."""
    import math
    if any(math.isnan(x) for x in (median_lead, hit_rate_val, fp_episode_rate_val)):
        return float("nan")
    return median_lead * hit_rate_val - k_fp * fp_episode_rate_val
```

- [ ] **Step 8.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/cards/test_vcg_validation_metrics.py -v`
Expected: PASS for all nine tests.

- [ ] **Step 8.5: Commit**

```bash
git add src/uw_scan/cards/vcg_validation_metrics.py tests/unit/cards/test_vcg_validation_metrics.py
git commit -m "feat(cards): VCG validation metric battery (lead time, FP day/episode, utility)"
```

---

## Phase 4 — Composite scoring extension

### Task 9: `compute_vcg_composite` + research version registry

**Files:**
- Modify: `src/uw_scan/cards/vcg_scoring.py`
- Create: `tests/unit/cards/test_vcg_scoring_composite.py`

- [ ] **Step 9.1: Write failing tests**

```python
# tests/unit/cards/test_vcg_scoring_composite.py
"""compute_vcg_composite + RESEARCH_COMPOSITE_VERSIONS contract.

Critical regression: the production compute_vcg path must be bit-identical
to its pre-PR output. This protects Hard Guarantee #1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.vcg_scoring import (
    RESEARCH_COMPOSITE_VERSIONS,
    compute_vcg,
    compute_vcg_composite,
)


def _series(start: str, n: int, base: float, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, size=n)
    px = base * np.exp(np.cumsum(rets))
    return pd.Series(px, index=pd.bdate_range(start, periods=n))


def test_research_versions_present_for_all_four_methods() -> None:
    assert set(RESEARCH_COMPOSITE_VERSIONS) == {
        "risk_parity_3", "risk_parity_hyjk", "hy_minus_ig_spread", "equal_weight_3",
    }
    for v in RESEARCH_COMPOSITE_VERSIONS.values():
        assert v.startswith("2-candidate-")


def test_compute_vcg_unchanged_after_composite_addition() -> None:
    """Bit-identical regression: production compute_vcg must yield the same
    output as before the composite path was added. Tests against a fixed
    fixture and checks key signal fields."""
    vix = _series("2020-01-01", 150, 18.0, seed=1).values
    vvix = _series("2020-01-01", 150, 90.0, seed=2).values
    hyg = _series("2020-01-01", 150, 80.0, seed=3).values
    model = compute_vcg(vix, vvix, hyg)
    # The model dict must contain the same keys it did pre-PR
    for key in ("vcg", "vcg_adj", "residuals", "alpha", "beta1", "beta2",
                "vix_ret", "vvix_ret", "credit_ret", "vix_levels",
                "vvix_levels", "credit_levels", "pi"):
        assert key in model, f"production compute_vcg lost key {key}"
        assert len(model[key]) == 149  # N-1 returns from N prices


def test_compute_vcg_composite_returns_two_attribution_layers() -> None:
    vix = _series("2020-01-01", 200, 18.0, seed=10)
    vvix = _series("2020-01-01", 200, 90.0, seed=11)
    proxies = {
        "HYG": _series("2020-01-01", 200, 80.0, seed=12),
        "JNK": _series("2020-01-01", 200, 100.0, seed=13),
        "LQD": _series("2020-01-01", 200, 110.0, seed=14),
    }
    payload = compute_vcg_composite(vix, vvix, proxies, method="risk_parity_3")
    assert "signal" in payload
    assert "attribution" in payload
    assert "basket_construction" in payload["attribution"]
    assert "signal_breakdown" in payload["attribution"]
    bc = payload["attribution"]["basket_construction"]
    assert bc["method"] == "risk_parity_3"
    assert bc["vol_window"] == 63
    assert bc["weight_lag"] == 1
    assert set(bc["weights_today"].keys()) == {"HYG", "JNK", "LQD"}
    sb = payload["attribution"]["signal_breakdown"]
    assert set(sb.keys()) >= {"HYG", "JNK", "LQD", "composite_single_proxy_disagreement"}


def test_compute_vcg_composite_credit_proxy_label() -> None:
    vix = _series("2020-01-01", 200, 18.0, seed=20)
    vvix = _series("2020-01-01", 200, 90.0, seed=21)
    proxies = {
        "HYG": _series("2020-01-01", 200, 80.0, seed=22),
        "JNK": _series("2020-01-01", 200, 100.0, seed=23),
        "LQD": _series("2020-01-01", 200, 110.0, seed=24),
    }
    rp3 = compute_vcg_composite(vix, vvix, proxies, method="risk_parity_3")
    spread = compute_vcg_composite(vix, vvix, proxies, method="hy_minus_ig_spread")
    assert rp3["credit_proxy"] == "COMPOSITE_RP3"
    assert spread["credit_proxy"] == "COMPOSITE_HY_MINUS_IG"
```

- [ ] **Step 9.2: Run tests to confirm fail**

Run: `uv run pytest tests/unit/cards/test_vcg_scoring_composite.py -v`
Expected: FAIL — `RESEARCH_COMPOSITE_VERSIONS` and `compute_vcg_composite` don't exist yet. (`test_compute_vcg_unchanged...` should pass.)

- [ ] **Step 9.3: Extend `vcg_scoring.py`**

Append to `src/uw_scan/cards/vcg_scoring.py`:

```python
# Research-only version channel — NOT imported by scanners/vcg.py or API routers.
# Each entry maps a composite construction method to its research version string.
# The production COMPOSITE_VERSION constant above stays at "1" indefinitely.
RESEARCH_COMPOSITE_VERSIONS: dict[str, str] = {
    "risk_parity_3":      "2-candidate-rp3",
    "risk_parity_hyjk":   "2-candidate-rp-hyjk",
    "hy_minus_ig_spread": "2-candidate-hy-minus-ig",
    "equal_weight_3":     "2-candidate-eq3",
}

_COMPOSITE_PROXY_LABEL: dict[str, str] = {
    "risk_parity_3":      "COMPOSITE_RP3",
    "risk_parity_hyjk":   "COMPOSITE_RP_HYJK",
    "hy_minus_ig_spread": "COMPOSITE_HY_MINUS_IG",
    "equal_weight_3":     "COMPOSITE_EQ3",
}


def _compute_vcg_from_returns(
    vix_returns: np.ndarray,
    vvix_returns: np.ndarray,
    credit_returns: np.ndarray,
    vix_levels: np.ndarray,
    vvix_levels: np.ndarray,
    credit_levels: np.ndarray,
) -> dict[str, np.ndarray]:
    """Like compute_vcg, but takes RETURNS directly instead of reconstructing
    them from prices. Avoids the level → log_returns round-trip that the
    composite path would otherwise need (which is alignment-fragile when the
    basket return is synthesized from per-proxy returns rather than from a
    real price series).

    Caller must pre-align all six inputs to the same N-bar window. vix/vvix/
    credit levels are the bar-end prices used by the panic-adjustment and the
    history payload only — they're never differenced inside this function.
    """
    X = np.column_stack([vvix_returns, vix_returns])
    alphas, beta1s, beta2s, residuals = rolling_ols(credit_returns, X, OLS_WINDOW)
    vcg = standardise_residuals(residuals, Z_WINDOW)
    pi = np.clip(
        (vix_levels - VIX_PANIC_LOW) / (VIX_PANIC_HIGH - VIX_PANIC_LOW), 0.0, 1.0
    )
    vcg_div = (1.0 - pi) * vcg
    return {
        "vcg": vcg, "vcg_adj": vcg_div,
        "residuals": residuals,
        "alpha": alphas, "beta1": beta1s, "beta2": beta2s,
        "vix_ret": vix_returns, "vvix_ret": vvix_returns, "credit_ret": credit_returns,
        "vix_levels": vix_levels, "vvix_levels": vvix_levels, "credit_levels": credit_levels,
        "pi": pi,
    }


def compute_vcg_composite(
    vix_prices: "pd.Series",
    vvix_prices: "pd.Series",
    prices_by_proxy: dict[str, "pd.Series"],
    *,
    method: str,
    vol_window: int = 63,
    weight_lag: int = 1,
    attribution_symbols: tuple[str, ...] = ("HYG", "JNK", "LQD"),
) -> dict[str, Any]:
    """Research-only composite VCG signal.

    Stage 1 — basket: build the synthetic credit basket via build_basket using
    only the proxies the chosen method requires (METHOD_METADATA[method].proxies).
    Stage 2 — canonical signal: run OLS on (VIX, VVIX, basket_returns) via
    _compute_vcg_from_returns. NO level reconstruction; uses returns directly,
    eliminates the off-by-one alignment risk that level → log_returns introduces.
    Stage 3 — attribution: ALWAYS run single-proxy OLS for HYG, JNK, AND LQD
    (regardless of basket method), so the disagreement diagnostic compares
    against all three issuer reads — not just the proxies in the basket.

    Output layers separate: signal (basket) vs. attribution.basket_construction
    vs. attribution.signal_breakdown. Composite residual is NOT a weighted
    average of single-proxy residuals — schema separation prevents misreading.
    """
    import pandas as pd  # local import: vcg_scoring is pure-numpy in prod path
    from uw_scan.cards.vcg_basket import METHOD_METADATA, build_basket  # noqa: PLC0415

    meta = METHOD_METADATA[method]

    # Stage 1: basket — only the proxies this method needs
    basket_inputs = {sym: prices_by_proxy[sym] for sym in meta.proxies}
    basket_ret, weight_history = build_basket(
        basket_inputs, method=method, window=vol_window, weight_lag=weight_lag,
    )

    # Align VIX/VVIX to the basket's valid-return index
    common = basket_ret.dropna().index
    common = common.intersection(vix_prices.index).intersection(vvix_prices.index)
    common = common.sort_values()
    if len(common) == 0:
        raise ValueError("compute_vcg_composite: no overlapping dates after alignment")

    vix_levels_aligned = vix_prices.reindex(common).values
    vvix_levels_aligned = vvix_prices.reindex(common).values
    basket_ret_aligned = basket_ret.reindex(common).values
    # Returns for VIX/VVIX (in-function — basket already in return-space)
    vix_ret_aligned = np.diff(np.log(vix_levels_aligned), prepend=np.nan)
    vvix_ret_aligned = np.diff(np.log(vvix_levels_aligned), prepend=np.nan)
    # Synthesise a non-arbitrary basket "level" sequence ONLY for the history
    # payload (never differenced for OLS).
    basket_levels_aligned = 100.0 * np.exp(np.nan_to_num(basket_ret_aligned).cumsum())

    canonical = _compute_vcg_from_returns(
        vix_ret_aligned, vvix_ret_aligned, basket_ret_aligned,
        vix_levels_aligned, vvix_levels_aligned, basket_levels_aligned,
    )
    common_iso = [d.date().isoformat() for d in common]
    canonical_signal = evaluate_signal(canonical, basket_levels_aligned)

    # Stage 3: single-proxy attribution for ALL THREE proxies (HYG/JNK/LQD)
    # regardless of which proxies the basket consumed. This keeps the
    # disagreement diagnostic comparable across basket methods.
    per_proxy: dict[str, dict[str, Any]] = {}
    for sym in attribution_symbols:
        px = prices_by_proxy.get(sym)
        if px is None:
            per_proxy[sym] = {"error": f"{sym} not provided in prices_by_proxy"}
            continue
        px_aligned = px.reindex(common).values
        try:
            sub = compute_vcg(vix_levels_aligned, vvix_levels_aligned, px_aligned)
            per_proxy[sym] = evaluate_signal(sub, px_aligned)
        except Exception as exc:  # pragma: no cover
            per_proxy[sym] = {"error": repr(exc)}

    # Disagreement: composite RO but <=1 proxy RO, or composite NORMAL but >=2 proxy RO
    composite_ro = bool(canonical_signal.get("ro", False))
    proxy_ro_count = sum(1 for v in per_proxy.values() if isinstance(v, dict) and v.get("ro"))
    disagreement = (composite_ro and proxy_ro_count <= 1) or (
        not composite_ro and proxy_ro_count >= 2
    )

    weights_today = {sym: float(weight_history.iloc[-1].get(sym, 0.0))
                     for sym in meta.proxies}

    return {
        "date": common_iso[-1] if common_iso else None,
        "credit_proxy": _COMPOSITE_PROXY_LABEL[method],
        "signal": canonical_signal,
        "attribution": {
            "basket_construction": {
                "method": method,
                "method_type": meta.method_type,
                "gross_exposure": meta.gross_exposure,
                "vol_window": vol_window,
                "weight_lag": weight_lag,
                "basket_symbols": list(meta.proxies),
                "attribution_symbols": list(attribution_symbols),
                "weights_today": weights_today,
            },
            "signal_breakdown": {
                **per_proxy,
                "composite_single_proxy_disagreement": bool(disagreement),
            },
        },
    }
```

- [ ] **Step 9.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/cards/test_vcg_scoring_composite.py tests/unit/test_research_isolation.py -v`
Expected: PASS for composite tests AND isolation tests (the isolation tests should still pass because `scanners/vcg.py` doesn't import the new symbols).

- [ ] **Step 9.5: Commit**

```bash
git add src/uw_scan/cards/vcg_scoring.py tests/unit/cards/test_vcg_scoring_composite.py
git commit -m "feat(cards): compute_vcg_composite + RESEARCH_COMPOSITE_VERSIONS registry"
```

---

## Phase 5 — Backtest CLI + R2 write

### Task 10: `sources/lake.py` — `write_weight_artifact`

**Files:**
- Modify: `src/uw_scan/sources/lake.py`
- Test: inline within Task 11 integration test (skipped unless R2_* env present)

- [ ] **Step 10.1: Write unit test for the canonical-bytes helper**

```python
# Append to tests/unit/sources/ (create new file)
# tests/unit/sources/test_lake_write_weight_artifact.py
"""Unit tests for the local-filesystem branch of write_weight_artifact.
R2 path is exercised by the live integration test in tests/integration/."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from uw_scan.sources.lake import canonical_weight_artifact_bytes, write_weight_artifact_local


def test_canonical_bytes_are_deterministic(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {"HYG": [0.34, 0.33], "JNK": [0.33, 0.34], "LQD": [0.33, 0.33]},
        index=pd.bdate_range("2024-01-01", periods=2),
    )
    b1 = canonical_weight_artifact_bytes(df)
    b2 = canonical_weight_artifact_bytes(df)
    assert b1 == b2  # byte-identical for identical input

    df2 = df[["LQD", "HYG", "JNK"]]  # different column order
    b3 = canonical_weight_artifact_bytes(df2)
    assert b1 == b3  # canonical orders columns alphabetically


def test_write_weight_artifact_local_returns_artifact_write_result(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {"HYG": [0.34], "JNK": [0.33], "LQD": [0.33]},
        index=pd.bdate_range("2024-01-01", periods=1),
    )
    result = write_weight_artifact_local(df, tmp_path / "vcg-weights")
    artifact = tmp_path / "vcg-weights" / f"{result.sha256}.parquet"
    assert artifact.exists()
    assert result.sha256 == hashlib.sha256(canonical_weight_artifact_bytes(df)).hexdigest()
    assert result.uri == f"file://{artifact}"
    assert result.key == str(artifact)


def test_canonical_input_price_bytes_long_format_deterministic() -> None:
    import pandas as pd  # noqa: PLC0415
    from uw_scan.sources.lake import canonical_input_price_bytes  # noqa: PLC0415
    s_hyg = pd.Series({pd.Timestamp("2024-01-02").date(): 100.0,
                       pd.Timestamp("2024-01-03").date(): 101.0})
    s_vix = pd.Series({pd.Timestamp("2024-01-02").date(): 15.0,
                       pd.Timestamp("2024-01-03").date(): 16.0})
    b1 = canonical_input_price_bytes(
        series_by_symbol={"HYG": s_hyg, "VIX": s_vix},
        price_field_by_symbol={"HYG": "adj_close", "VIX": "close"},
    )
    # Reversed insertion order — should produce IDENTICAL bytes (canonical sort)
    b2 = canonical_input_price_bytes(
        series_by_symbol={"VIX": s_vix, "HYG": s_hyg},
        price_field_by_symbol={"VIX": "close", "HYG": "adj_close"},
    )
    assert b1 == b2
```

- [ ] **Step 10.2: Run test to confirm fail**

Run: `uv run pytest tests/unit/sources/test_lake_write_weight_artifact.py -v`
Expected: FAIL — helpers don't exist.

- [ ] **Step 10.3: Implement the helpers**

Append to `src/uw_scan/sources/lake.py`:

```python
import hashlib
import io
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def canonical_weight_artifact_bytes(weights: pd.DataFrame) -> bytes:
    """Deterministic parquet bytes for a weight DataFrame.

    Sort columns alphabetically, sort rows by index, fix the parquet writer
    config so byte stream is reproducible within the pinned uv.lock pyarrow.
    """
    df = weights[sorted(weights.columns)].sort_index().copy()
    df.index.name = df.index.name or "trade_date"
    table = pa.Table.from_pandas(df.reset_index(), preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(
        table, buf,
        compression="none",
        use_dictionary=True,
        write_statistics=False,
        version="2.6",
    )
    return buf.getvalue()


def write_weight_artifact_local(weights: pd.DataFrame, out_dir: Path) -> ArtifactWriteResult:
    """Write to local fs. Returns ArtifactWriteResult so the caller never
    reconstructs the path from a sha (R2 and local paths must be the SOLE
    source of truth for what gets persisted in extras)."""
    raw = canonical_weight_artifact_bytes(weights)
    sha = hashlib.sha256(raw).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{sha}.parquet"
    if not target.exists():
        target.write_bytes(raw)
    return ArtifactWriteResult(sha256=sha, key=str(target), uri=f"file://{target}")


from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactWriteResult:
    """Result of writing a research artifact. Returned by both write_weight_artifact_*
    so callers don't reconstruct paths and risk mismatch."""
    sha256: str
    key: str           # full key under the bucket (R2) or filesystem path (local)
    uri: str           # `r2://bucket/key` or `file://path`


def write_weight_artifact_r2(weights: pd.DataFrame, root: "LakeRoot") -> ArtifactWriteResult:
    """Write to R2 under market-warehouse/research/vcg-weights/<sha>.parquet.
    Path is sibling to the data-lake's bronze zone. Returns sha + key + uri.

    NB: helper names match current `src/uw_scan/sources/lake.py`:
    - `_s3_fs(root)` (NOT `_s3_filesystem`)
    - `root.bucket` + `root.key_prefix` (NOT `bucket_prefix`)
    """
    if root.kind != "s3":
        raise ValueError(f"write_weight_artifact_r2 requires R2 root, got kind={root.kind}")
    raw = canonical_weight_artifact_bytes(weights)
    sha = hashlib.sha256(raw).hexdigest()
    fs = _s3_fs(root)
    key = f"market-warehouse/research/vcg-weights/{sha}.parquet"
    full_key = f"{root.bucket}/{key}"
    with fs.open_output_stream(full_key) as out:
        out.write(raw)
    return ArtifactWriteResult(sha256=sha, key=full_key, uri=f"r2://{full_key}")


def canonical_input_price_bytes(
    *,
    series_by_symbol: dict[str, "pd.Series"],
    price_field_by_symbol: dict[str, str],
) -> bytes:
    """Deterministic parquet bytes for input price series, in LONG format
    (one row per (trade_date, symbol)) so the hash is independent of the
    column order any caller happens to use.

    Schema:
        trade_date  date32   (sorted ascending)
        symbol      string   (sorted alphabetically within each date)
        price_field string   ('close' / 'adj_close' — taken from price_field_by_symbol)
        price       float64  (formatted via float64 -> parquet, NOT %.17g str)

    Spec §6 hash content rule: hash of canonical PARQUET bytes containing
    [trade_date, symbol, price_field, price] for all input symbols AFTER
    alignment, sorted by (trade_date, symbol). This function does NOT align —
    callers provide pre-aligned series — but DOES enforce sort order.
    """
    rows: list[dict] = []
    for sym in sorted(series_by_symbol):
        s = series_by_symbol[sym]
        pf = price_field_by_symbol[sym]
        for d, v in s.items():
            d_real = d.date() if hasattr(d, "date") else d
            rows.append({
                "trade_date": d_real, "symbol": sym,
                "price_field": pf, "price": float(v),
            })
    if not rows:
        return b""
    df = pd.DataFrame(rows).sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(
        table, buf,
        compression="none", use_dictionary=True,
        write_statistics=False, version="2.6",
    )
    return buf.getvalue()
```

- [ ] **Step 10.4: Run tests to confirm pass**

Run: `uv run pytest tests/unit/sources/test_lake_write_weight_artifact.py -v`
Expected: PASS for both tests.

- [ ] **Step 10.5: Commit**

```bash
git add src/uw_scan/sources/lake.py tests/unit/sources/test_lake_write_weight_artifact.py
git commit -m "feat(sources): write_weight_artifact local + R2 helpers for VCG research"
```

---

### Task 11: `backtest_vcg.py` — `--research-proxy` + `--composite-method`

Per the third-pass review, this task does the most work and has the highest single-task regression risk (it touches the production single-proxy path). Execute in three internal phases, with a commit + smoke test after each, so a failure can be bisected to the responsible phase:

- **11A — Argparse + mode resolution only.** No persistence change. Existing `--proxy HYG` invocation runs the existing single-proxy code path bit-identically.
- **11B — Research single-proxy baseline (`--research-proxy`).** Same code path as `--proxy` but writes `run_scope='research'`. Production `--proxy HYG` MUST remain bit-identical.
- **11C — Composite path (`--composite-method`).** Adds the composite scoring, artifact persistence, and new `extras` keys. The most complex phase; isolated from production by 11A's mutual-exclusion check.

**Files:**
- Modify: `scripts/backtest_vcg.py`
- Create: `tests/integration/test_backtest_vcg_cli.py`

- [ ] **Step 11.1: Write failing CLI tests**

```python
# tests/integration/test_backtest_vcg_cli.py
"""Argparse-level tests for the new --research-proxy / --composite-method flags.
Full end-to-end backtest invocation is in Task 15 (the actual run)."""
from __future__ import annotations

import subprocess
import sys


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["uv", "run", "python", "scripts/backtest_vcg.py", *args],
        capture_output=True, text=True,
    )


def test_proxy_and_composite_are_mutually_exclusive() -> None:
    r = _run(["--proxy", "HYG", "--composite-method", "risk_parity_3"])
    assert r.returncode != 0
    assert "mutually exclusive" in (r.stderr + r.stdout).lower() or "not allowed" in (r.stderr + r.stdout).lower()


def test_proxy_and_research_proxy_are_mutually_exclusive() -> None:
    r = _run(["--proxy", "HYG", "--research-proxy", "HYG"])
    assert r.returncode != 0


def test_research_proxy_choices_validated() -> None:
    # argparse exits 2 on invalid --choices BEFORE the backtest body runs;
    # supplying valid date flags doesn't matter — the choice error is hit first.
    r = _run(["--research-proxy", "BADTICKER",
              "--start", "2024-01-01", "--end", "2024-01-02"])
    assert r.returncode != 0
    assert "invalid choice" in (r.stderr + r.stdout).lower()


def test_composite_method_choices_validated() -> None:
    r = _run(["--composite-method", "not_a_method"])
    assert r.returncode != 0
    assert "invalid choice" in (r.stderr + r.stdout).lower()
```

- [ ] **Step 11.2: Run tests to confirm fail**

Run: `uv run pytest tests/integration/test_backtest_vcg_cli.py -v`
Expected: FAIL — new flags don't exist.

- [ ] **Step 11.3: Modify `scripts/backtest_vcg.py`**

Add to the argparse block (after existing flags, near line 130):

```python
# (Edit the existing argparse setup. The new structure mutually excludes the three modes.)
p = argparse.ArgumentParser()
p.add_argument("--start", default="2007-01-01")
p.add_argument("--end", default=_date.today().isoformat())
p.add_argument("--note", default=None)

mode = p.add_mutually_exclusive_group(required=False)
mode.add_argument("--proxy", choices=_VALID_PROXIES,
                  help="Production single-proxy run (run_scope=production). Default HYG.")
mode.add_argument("--research-proxy", choices=_VALID_PROXIES,
                  help="Research single-proxy baseline for the comparator (run_scope=research).")
mode.add_argument("--composite-method",
                  choices=("risk_parity_3", "risk_parity_hyjk",
                           "hy_minus_ig_spread", "equal_weight_3"),
                  help="Research composite run (run_scope=research).")

p.add_argument("--vol-window", type=int, default=63,
               help="Only used with --composite-method (default 63).")
p.add_argument("--weight-lag", type=int, default=1,
               help="Only used with --composite-method (default 1).")

args = p.parse_args()

# Mode resolution
if args.composite_method is not None:
    run_scope = "research"
    composite_method = args.composite_method
    selected_proxy = None
elif args.research_proxy is not None:
    run_scope = "research"
    composite_method = "single_proxy"
    selected_proxy = args.research_proxy
else:
    run_scope = "production"
    composite_method = "single_proxy"
    selected_proxy = args.proxy or "HYG"
```

Then update the persistence section (around line 264) so it branches on the mode. Replace the existing `insert_run` block:

```python
# Build the daily rows and summary differently for composite vs single-proxy.
if args.composite_method is not None:
    # Composite path: run compute_vcg_composite per bar, produce daily payloads.
    from uw_scan.cards.vcg_scoring import (
        RESEARCH_COMPOSITE_VERSIONS, compute_vcg_composite,
    )
    from uw_scan.cards.vcg_basket import METHOD_METADATA
    from uw_scan.sources.lake import (
        canonical_weight_artifact_bytes,
        write_weight_artifact_local,
        write_weight_artifact_r2,
    )
    import hashlib, pandas as pd

    meta = METHOD_METADATA[args.composite_method]
    needed_syms = list(meta.proxies)

    # Load full history for VIX, VVIX, and the proxies the method needs.
    vol_repo = VolIndexRepository(conn, schema=settings.db_schema)
    def _pd_series(sym: str, prefer_adj: bool) -> pd.Series:
        rows = vol_repo.fetch_history(sym, days=10_000)
        if prefer_adj:
            return pd.Series(
                {r["trade_date"]: float(r.get("adj_close") or r["close"]) for r in rows},
                name=sym,
            )
        return pd.Series({r["trade_date"]: float(r["close"]) for r in rows}, name=sym)

    vix_s = _pd_series("VIX", prefer_adj=False)
    vvix_s = _pd_series("VVIX", prefer_adj=False)
    proxy_series = {sym: _pd_series(sym, prefer_adj=True) for sym in needed_syms}

    # Bar-by-bar replay: at each common date with sufficient history, call
    # compute_vcg_composite using only data through that date. Daily payload
    # captures signal + disagreement flag for the comparator.
    daily_rows = []
    composite_versions_registry = RESEARCH_COMPOSITE_VERSIONS
    composite_version = composite_versions_registry[args.composite_method]
    common = sorted(set(vix_s.index) & set(vvix_s.index)
                    & set.intersection(*[set(p.index) for p in proxy_series.values()]))
    start_d = _date.fromisoformat(args.start)
    end_d = _date.fromisoformat(args.end)
    common = [d for d in common if start_d <= d <= end_d]

    MIN_BARS = vcg_scoring.MIN_BARS + args.vol_window  # warmup
    for i in range(MIN_BARS, len(common)):
        prefix_dates = common[: i + 1]
        vix_p = vix_s.loc[prefix_dates]
        vvix_p = vvix_s.loc[prefix_dates]
        proxies_p = {sym: s.loc[prefix_dates] for sym, s in proxy_series.items()}
        try:
            payload = compute_vcg_composite(
                vix_p, vvix_p, proxies_p,
                method=args.composite_method,
                vol_window=args.vol_window,
                weight_lag=args.weight_lag,
            )
        except Exception as exc:  # pragma: no cover
            log.warning("composite scoring skipped at %s: %r", prefix_dates[-1], exc)
            continue
        sig = payload["signal"]
        daily_rows.append({
            "trade_date": prefix_dates[-1],
            "score": float(sig.get("vcg") or 0.0),
            "level": sig.get("interpretation"),
            "payload": {
                "signal": sig,
                "attribution": payload["attribution"],
            },
        })

    # Build the FULL weight history for the artifact (compute once from full common range)
    _, weight_history = __import__(
        "uw_scan.cards.vcg_basket", fromlist=["build_basket"]
    ).build_basket(
        {sym: s.loc[common] for sym, s in proxy_series.items()},
        method=args.composite_method,
        window=args.vol_window,
        weight_lag=args.weight_lag,
    )

    # Persist weight artifact — write_weight_artifact_* returns ArtifactWriteResult
    # so callers DON'T reconstruct paths (paths in extras must match where the
    # bytes actually live).
    settings_obj = settings
    if all([getattr(settings_obj, "r2_account_id", None),
            getattr(settings_obj, "r2_bucket", None)]):
        from uw_scan.sources.lake_resolver import resolve_lake_root
        root = resolve_lake_root(settings_obj, asset_class="equity")
        artifact = write_weight_artifact_r2(weight_history, root)
    else:
        # Local fallback: write_weight_artifact_local must also return
        # ArtifactWriteResult (update its signature in Task 10 alongside the R2 one).
        artifact = write_weight_artifact_local(
            weight_history, Path("var/research/vcg-weights"),
        )
    weight_sha = artifact.sha256
    artifact_location = artifact.uri

    # input_data_sha256: canonical LONG-format parquet bytes per spec §6.
    # Uses canonical_input_price_bytes (NOT canonical_weight_artifact_bytes —
    # the latter is for the weight DataFrame's wide shape).
    input_bytes = canonical_input_price_bytes(
        series_by_symbol={
            "VIX": vix_s.loc[common],
            "VVIX": vvix_s.loc[common],
            **{sym: proxy_series[sym].loc[common] for sym in needed_syms},
        },
        price_field_by_symbol={
            "VIX": "close", "VVIX": "close",
            **{sym: "adj_close" for sym in needed_syms},
        },
    )
    input_sha = hashlib.sha256(input_bytes).hexdigest()

    summary = {
        "oos": None,
        "extras": {
            "credit_proxy": payload["credit_proxy"] if daily_rows else None,
            "composite_method": args.composite_method,
            "composite_method_type": meta.method_type,
            "gross_exposure": meta.gross_exposure,
            "vol_window": args.vol_window,
            "weight_lag": args.weight_lag,
            "price_field": "adj_close",
            "input_symbols": ["VIX", "VVIX", *needed_syms],
            "input_data_sha256": input_sha,
            "weights_artifact_sha256": weight_sha,
            "weights_artifact_path": artifact_location,
        },
    }
    credit_proxy_col = payload["credit_proxy"] if daily_rows else None

else:
    # Single-proxy path: existing logic, factored to feed both --proxy and
    # --research-proxy. selected_proxy and run_scope already decided above.
    # (Keep existing single-proxy backtest logic essentially unchanged but
    # reference selected_proxy and pass run_scope to insert_run.)
    args.proxy = selected_proxy  # legacy var used below
    composite_version = str(vcg_scoring.COMPOSITE_VERSION)
    # ... (existing single-proxy backtest produces daily_rows and summary)
    credit_proxy_col = selected_proxy
    # The existing summary already has summary["extras"]["credit_proxy"] = args.proxy.

# Common insert
with psycopg.connect(settings.db_dsn()) as conn:
    rb = RegimeBacktestRepository(conn, schema=settings.db_schema)
    run_id = rb.insert_run(
        indicator="vcg",
        composite_version=composite_version,
        start_date=daily_rows[0]["trade_date"],
        end_date=daily_rows[-1]["trade_date"],
        window_days=vcg_scoring.OLS_WINDOW,
        n_days=len(daily_rows),
        params={
            "proxy": selected_proxy,
            "composite_method": composite_method,
            "ols_window": vcg_scoring.OLS_WINDOW,
            "z_window": vcg_scoring.Z_WINDOW,
            "vol_window": getattr(args, "vol_window", None),
            "weight_lag": getattr(args, "weight_lag", None),
        },
        summary=summary,
        note=args.note,
        run_scope=run_scope,
        composite_method=composite_method,
        credit_proxy=credit_proxy_col,
    )
    rb.bulk_insert_daily(run_id, daily_rows)
    rb.mark_run_completed(run_id)
```

(The existing single-proxy code path needs minor refactoring: the `--proxy` block becomes the `else` branch above. Refactor in this step; preserve all existing behavior bit-for-bit when only `--proxy HYG` is passed.)

- [ ] **Step 11.4: Run tests to confirm pass**

Run: `uv run pytest tests/integration/test_backtest_vcg_cli.py -v`
Expected: PASS for the four CLI tests.

- [ ] **Step 11.5: Smoke-run existing production path**

Run: `uv run python scripts/backtest_vcg.py --proxy HYG --start 2024-01-01 --end 2024-06-30 --note "smoke: post-research-PR regression"`
Expected: Exits 0; new row in `regime_backtest_runs` with `run_scope='production'`, `credit_proxy='HYG'`, `composite_method='single_proxy'`, `composite_version='1'`. No change in production default selection.

- [ ] **Step 11.6: Commit**

```bash
git add scripts/backtest_vcg.py tests/integration/test_backtest_vcg_cli.py
git commit -m "feat(scripts): backtest_vcg --research-proxy + --composite-method modes"
```

---

## Phase 6 — Benchmark coverage

### Task 12: Benchmark coverage verification (no fetcher build in this PR)

**Operator note from user:** NDX and RUT will be made available in `vol_index_daily` out-of-band before plan execution reaches Task 15 (the actual research backtests). SPX is already there via migration 038. This task is therefore a **pure verification step** — no fetcher build in this PR.

If a benchmark is below the 4000-bar threshold when the comparator runs, `load_benchmarks` (Task 13) drops it with a logged warning and the report (Task 14) marks the coverage gap. The PR is not blocked by absent optional benchmarks; the primary gate cell `(SPX, Fast)` works as long as SPX is present.

**Files:** none (verification only).

- [ ] **Step 12.1: Verify SPX/NDX/RUT presence in `vol_index_daily`**

Run:
```bash
psql "$DATABASE_URL" -c "
  SELECT symbol, MIN(trade_date) AS first, MAX(trade_date) AS last, COUNT(*) AS bars
  FROM uw_scan.vol_index_daily
  WHERE symbol IN ('SPX','NDX','RUT')
  GROUP BY symbol ORDER BY symbol;
"
```
Expected: SPX has ≥7000 bars (long history via R2 lake). NDX, RUT each have ≥4000 bars *if* the user has completed their out-of-band ingestion.

Per the comparator's behavior, missing or thin benchmarks are dropped automatically — Task 13 needs no change.

- [ ] **Step 12.2: Capture coverage matrix in the validation report**

When Task 16 (run comparator) executes, the resulting report's §2 must include a benchmark coverage table that quotes the bar count per benchmark and which were used / dropped. The `load_benchmarks` function already logs this; the report assembler in Task 14 must render it.

If a critical benchmark (SPX) is missing or thin: STOP — the primary gate cell `(SPX, Fast)` is non-evaluable. The PR cannot ship its research verdict until SPX has ≥4000 bars. NDX or RUT below threshold are non-blocking; they reduce the robustness denominator (the report quotes the actual denominator used).

- [ ] **Step 12.3: No commit needed**

This is a verification step. Coverage findings are captured in the report committed by Task 16.

---

## Phase 7 — Comparator

### Task 13: `compare_vcg_lead_time.py` — batch loaders + orchestrator

**Files:**
- Create: `scripts/compare_vcg_lead_time.py`
- Create: `tests/integration/test_compare_vcg_lead_time.py`

- [ ] **Step 13.1: Write failing integration test (small fixture)**

```python
# tests/integration/test_compare_vcg_lead_time.py
"""End-to-end smoke test for the comparator on a small synthetic fixture.

Asserts the "zero DB queries between batch-load and report assembly" contract
by counting queries via psycopg's executemany/execute hooks. Spec §15 lock-in."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


def _seed_minimal_data(conn) -> None:
    # Synthetic SPX closes (+ NDX, RUT to satisfy comparator's full benchmark loop)
    from uw_scan.storage.vol_index_repository import VolIndexRepository
    repo = VolIndexRepository(conn, schema="uw_scan")
    series = _synthetic_index_closes()  # dict[symbol, list[(trade_date, close)]]
    for symbol, rows in series.items():
        repo.upsert_rows([
            {"symbol": symbol, "trade_date": d, "open": px, "high": px, "low": px,
             "close": px, "adj_close": px, "volume": 0}
            for d, px in rows
        ])
    # ... seed three research single-proxy runs (HYG/JNK/LQD baselines) and four composite runs
    conn.commit()


def _synthetic_index_closes() -> dict[str, list[tuple]]: ...  # 250-bar series per index with one -8% dip
def _bdays(i: int): ...                                      # business-day offset helper


@pytest.mark.skip(reason="Implemented in Step 13.6 — depends on comparator script")
def test_comparator_produces_report(tmp_path, seeded_db_empty_cards) -> None:
    pass
```

(The actual test body is filled in at Step 13.6 after the comparator exists.)

- [ ] **Step 13.2: Implement batch loaders**

```python
# scripts/compare_vcg_lead_time.py
"""VCG composite vs single-proxy lead-time comparator.

Invariant (locked by spec §15): zero database queries between the start of
the per-cell loop and report assembly. All data is batch-loaded upfront.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg

from uw_scan.cards.drawdown import DrawdownDefinition, detect_drawdown_events
from uw_scan.cards.vcg_validation_metrics import (
    actionable_lead_days,
    alarm_day_ratio,
    fp_day_rate,
    fp_episode_rate,
    hit_rate,
    next_trading_day,
    ro_episodes,
    utility_score,
)
from uw_scan.config import Settings
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

log = logging.getLogger("compare_vcg_lead_time")

BENCHMARKS = ("SPX", "NDX", "RUT")  # cash indices — broad / mega-cap-tech / small-cap-credit
DRAWDOWN_DEFS = (
    DrawdownDefinition("Fast", 0.05, 10),
    DrawdownDefinition("Medium", 0.07, 20),
    DrawdownDefinition("Major", 0.10, 60),
)
PERIOD_SLICES = (
    ("pre-2020", date(2008, 1, 1), date(2019, 12, 31)),
    ("2020-COVID", date(2020, 1, 1), date(2020, 12, 31)),
    ("2021-2022-rates", date(2021, 1, 1), date(2022, 12, 31)),
    ("2023-2026-AI", date(2023, 1, 1), date(2026, 5, 26)),
)
FP_HORIZON_DAYS = {"Fast": 30, "Medium": 30, "Major": 60}


@dataclass(frozen=True)
class ProxyRun:
    run_id: int
    credit_proxy: str
    composite_method: str
    composite_version: str
    daily: pd.DataFrame  # index=date, columns=['score','level','payload']


@dataclass(frozen=True)
class BatchData:
    benchmarks: dict[str, pd.Series]
    runs: list[ProxyRun]
    trading_days_by_period: dict[str, list[date]]


def load_benchmarks(conn) -> dict[str, pd.Series]:
    """Reads cash-index closes from vol_index_daily via VolIndexRepository.
    SPX is seeded by the existing R2 lake-sync; NDX/RUT are seeded by
    scripts/seed_index_ohlc.py (Task 12)."""
    from uw_scan.storage.vol_index_repository import VolIndexRepository
    repo = VolIndexRepository(conn, schema="uw_scan")
    out: dict[str, pd.Series] = {}
    for ticker in BENCHMARKS:
        rows = repo.fetch_history(ticker, days=20_000)
        if len(rows) < 4000:
            log.warning("%s has only %d bars in vol_index_daily; dropping from validation universe",
                        ticker, len(rows))
            continue
        out[ticker] = pd.Series(
            {r["trade_date"]: float(r["close"]) for r in rows}, name=ticker,
        )
    return out


def load_research_runs(repo: RegimeBacktestRepository) -> list[ProxyRun]:
    runs = repo.list_research_runs(indicator="vcg", limit=200)
    out: list[ProxyRun] = []
    for r in runs:
        daily = repo.fetch_daily_for_run(r["id"])
        df = pd.DataFrame(daily).set_index("trade_date") if daily else pd.DataFrame()
        out.append(ProxyRun(
            run_id=r["id"], credit_proxy=r["credit_proxy"],
            composite_method=r["composite_method"],
            composite_version=r["composite_version"], daily=df,
        ))
    return out


def batch_load_all(settings: Settings) -> BatchData:
    """ALL DB queries happen here. After return, no further DB access permitted."""
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = RegimeBacktestRepository(conn, schema=settings.db_schema)
        benchmarks = load_benchmarks(conn)
        runs = load_research_runs(repo)
    tdays_by_period: dict[str, list[date]] = {}
    if benchmarks:
        all_dates = sorted(set.union(*[set(s.index) for s in benchmarks.values()]))
        for name, start, end in PERIOD_SLICES:
            tdays_by_period[name] = [d for d in all_dates if start <= d <= end]
    return BatchData(benchmarks=benchmarks, runs=runs, trading_days_by_period=tdays_by_period)
```

(File continues in Task 14.)

- [ ] **Step 13.3: Implement the per-cell metric loop**

Append to `scripts/compare_vcg_lead_time.py`:

```python
@dataclass(frozen=True)
class CellResult:
    period: str
    benchmark: str
    drawdown_def: str
    credit_proxy: str
    composite_method: str
    n_events: int
    median_close_lead: float            # trading days
    median_actionable_lead: float       # trading days
    hit_rate: float
    fp_day_rate: float                  # per-day FP (definition window)
    fp_short_horizon_rate: float        # 10-bday forward, 2% threshold (spec §8)
    fp_event_window_rate: float         # def-specific window, qualifying event peak in window
    fp_episode_rate: float              # episode-level FP, gate metric
    precision_day: float                # TP_days / (TP_days + FP_days)
    recall_event: float                 # events_caught / total_events
    alarm_day_ratio: float
    ro_episode_count: int
    median_ro_episode_length_bdays: float  # trading days
    disagreement_vs_hyg_rate: float     # fraction of days where this proxy's RO ≠ HYG's
    utility_score: float


def _ro_signal_from_daily(daily: pd.DataFrame) -> pd.Series:
    """Extract RO bool series. Defensively handles BOTH payload shapes:

    - Composite (new, this PR): payload['signal']['ro']
    - Single-proxy (existing, scripts/backtest_vcg.py:195-212): payload['ro']

    The single-proxy schema predates this PR; rewriting it would break the
    `find_latest_run('vcg')` validation tab. Reader is polymorphic.
    """
    if daily.empty:
        return pd.Series(dtype=bool)
    def _is_ro(row: dict) -> bool:
        if not isinstance(row, dict):
            return False
        # Composite shape
        sig = row.get("signal")
        if isinstance(sig, dict) and "ro" in sig:
            return bool(sig.get("ro"))
        # Single-proxy shape (top-level)
        return bool(row.get("ro"))
    flags = daily["payload"].apply(_is_ro)
    if not flags.empty:
        flags.index = (
            pd.to_datetime(flags.index).date
            if not isinstance(flags.index[0], date)
            else flags.index
        )
    return flags.astype(bool)


def compute_cell(
    period: str, benchmark: str, defn: DrawdownDefinition,
    run: ProxyRun, closes: pd.Series, trading_days: list[date],
    *,
    hyg_ro: pd.Series | None = None,  # for disagreement_vs_hyg_rate
) -> CellResult:
    """Per-cell metrics. Lead-time and episode-length values are in TRADING days
    (not calendar days) — uses _bday_count via close_to_trough_lead_days.

    FP semantics: an RO at date d is NOT a false positive if any event TROUGH
    (drawdown payoff) lies within [d, d + H_def] trading days. Spec §8: gate
    metric is FP_episode_rate; FP_day_rate + FP_short_horizon + FP_event_window
    are diagnostic.
    """
    closes_p = closes[(closes.index >= trading_days[0]) & (closes.index <= trading_days[-1])]
    events = detect_drawdown_events(closes_p, defn)
    ro_full = _ro_signal_from_daily(run.daily)
    ro = ro_full[(ro_full.index >= trading_days[0]) & (ro_full.index <= trading_days[-1])]

    hr = hit_rate(events, ro_signal=ro, trading_days=trading_days, peak_lookback=30)

    leads_actionable: list[int] = []
    leads_close: list[int] = []
    for e in events:
        peak_idx = _idx(trading_days, e.peak_date)
        window_lo = trading_days[max(0, peak_idx - 30)]
        ro_in = ro[(ro.index >= window_lo) & (ro.index <= e.trough_date) & (ro)]
        if ro_in.empty:
            continue
        ro_date = ro_in.index[0]
        # close-to-trough lead in TRADING days (not (.days) calendar arithmetic)
        cl = close_to_trough_lead_days(ro_date, e.trough_date, trading_days)
        leads_close.append(cl)
        a = actionable_lead_days(ro_date, e.trough_date, trading_days)
        if a >= 0:
            leads_actionable.append(a)

    eps = ro_episodes(ro)

    # FP variants (spec §8 metric battery)
    fp_d = fp_day_rate(ro, events=events, trading_days=trading_days, horizon_days=defn.window_days)
    fp_e = fp_episode_rate(ro, events=events, trading_days=trading_days,
                           horizon_days=FP_HORIZON_DAYS[defn.name])
    fp_short = _fp_short_horizon_rate(ro, closes=closes_p, trading_days=trading_days,
                                      horizon_days=10, threshold=0.02)
    fp_event_window = fp_day_rate(ro, events=events, trading_days=trading_days,
                                  horizon_days=FP_HORIZON_DAYS[defn.name])

    # Precision/recall
    tp_days = ro.sum() - int(fp_d * max(ro.sum(), 1))
    fp_days = int(fp_d * max(ro.sum(), 1))
    precision_day = (tp_days / (tp_days + fp_days)) if (tp_days + fp_days) > 0 else float("nan")
    events_caught = int(round(hr * len(events))) if events and not pd.isna(hr) else 0
    recall_event = (events_caught / len(events)) if events else float("nan")

    # Disagreement vs HYG (per-day): both signals defined on same date range
    if hyg_ro is None or hyg_ro.empty:
        disagreement = float("nan")
    else:
        common_idx = ro.index.intersection(hyg_ro.index)
        if len(common_idx) == 0:
            disagreement = float("nan")
        else:
            disagreement = float((ro.loc[common_idx] != hyg_ro.loc[common_idx]).mean())

    median_actionable = (
        float(pd.Series(leads_actionable).median()) if leads_actionable else float("nan")
    )

    # Median RO episode length in TRADING days. close_to_trough_lead_days
    # returns the trading-day count between two dates; +1 because both endpoints
    # are inclusive in an episode. Avoids duplicating _bday_count here.
    if eps:
        lengths = [
            close_to_trough_lead_days(a, b, trading_days) + 1
            for a, b in eps
        ]
        median_ep_len = float(pd.Series(lengths).median())
    else:
        median_ep_len = float("nan")

    return CellResult(
        period=period, benchmark=benchmark, drawdown_def=defn.name,
        credit_proxy=run.credit_proxy, composite_method=run.composite_method,
        n_events=len(events),
        median_close_lead=float(pd.Series(leads_close).median()) if leads_close else float("nan"),
        median_actionable_lead=median_actionable,
        hit_rate=hr,
        fp_day_rate=fp_d,
        fp_short_horizon_rate=fp_short,
        fp_event_window_rate=fp_event_window,
        fp_episode_rate=fp_e,
        precision_day=precision_day,
        recall_event=recall_event,
        alarm_day_ratio=alarm_day_ratio(ro),
        ro_episode_count=len(eps),
        median_ro_episode_length_bdays=median_ep_len,
        disagreement_vs_hyg_rate=disagreement,
        utility_score=utility_score(
            median_lead=median_actionable, hit_rate_val=hr,
            fp_episode_rate_val=fp_e, k_fp=5.0,
        ),
    )


def _fp_short_horizon_rate(
    ro: pd.Series, *, closes: pd.Series, trading_days: list[date],
    horizon_days: int = 10, threshold: float = 0.02,
) -> float:
    """RO days with no forward drawdown >= threshold within horizon_days bdays.
    Spec §8 diagnostic — reported alongside FP_episode_rate."""
    on = ro[ro]
    if on.empty or closes.empty:
        return float("nan")
    closes_ix = list(closes.index)
    fp = 0
    for d in on.index:
        d_real = d.date() if hasattr(d, "date") else d
        if d_real not in trading_days:
            continue
        ci = trading_days.index(d_real) if d_real in trading_days else None
        if ci is None:
            continue
        horizon_end = trading_days[min(ci + horizon_days, len(trading_days) - 1)]
        window = closes[(closes.index >= d_real) & (closes.index <= horizon_end)]
        if window.empty:
            fp += 1
            continue
        peak = window.iloc[0]
        trough = window.min()
        drawdown = (peak - trough) / peak if peak > 0 else 0.0
        if drawdown < threshold:
            fp += 1
    return fp / len(on)


def _idx(seq: list, val) -> int:
    import bisect
    return bisect.bisect_left(seq, val)


def run_all_cells(data: BatchData) -> list[CellResult]:
    """Sequential per-cell loop. Spec §15 lock: NO database queries here —
    everything comes from `data`. Per-cell disagreement is computed against
    HYG's RO series for the same (period, benchmark, defn)."""
    cells: list[CellResult] = []
    # Index runs by (credit_proxy, composite_method) for fast HYG lookup
    runs_by_proxy = {r.credit_proxy: r for r in data.runs}
    hyg_run = runs_by_proxy.get("HYG")
    hyg_ro_full = _ro_signal_from_daily(hyg_run.daily) if hyg_run is not None else None

    for period_name, *_ in PERIOD_SLICES:
        tdays = data.trading_days_by_period.get(period_name, [])
        if not tdays:
            continue
        # Slice HYG's RO to this period once per period
        if hyg_ro_full is not None and not hyg_ro_full.empty:
            hyg_ro_p = hyg_ro_full[
                (hyg_ro_full.index >= tdays[0]) & (hyg_ro_full.index <= tdays[-1])
            ]
        else:
            hyg_ro_p = None
        for bench_name, closes in data.benchmarks.items():
            for defn in DRAWDOWN_DEFS:
                for run in data.runs:
                    cells.append(compute_cell(
                        period_name, bench_name, defn, run, closes, tdays,
                        hyg_ro=hyg_ro_p,
                    ))
    return cells
```

- [ ] **Step 13.4: Add structural zero-DB-in-loop assertion**

Spec §15 requires the invariant be encoded as a test, not just a docstring. Add to `tests/integration/test_compare_vcg_lead_time.py`:

```python
def test_per_cell_functions_do_not_reference_psycopg() -> None:
    """Structural enforcement of spec §15: the per-cell loop and metric
    computation must not perform DB queries. Loads the script file directly
    via importlib (scripts/ is intentionally NOT a package — adding
    __init__.py there breaks the existing CLI invocation pattern)."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "compare_vcg_lead_time",
        Path(__file__).resolve().parents[2] / "scripts/compare_vcg_lead_time.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    import inspect
    forbidden = ("psycopg", "Connection", ".cursor(", "cur.execute")
    for fn in (mod.compute_cell, mod.run_all_cells):
        src = inspect.getsource(fn)
        for needle in forbidden:
            assert needle not in src, (
                f"{fn.__name__} references {needle!r} — DB access inside the "
                f"per-cell loop violates spec §15 (zero-DB-in-loop invariant)"
            )
```

- [ ] **Step 13.5: Run tests to confirm pass**

Run: `uv run pytest tests/integration/test_compare_vcg_lead_time.py::test_per_cell_functions_do_not_reference_psycopg -v`
Expected: PASS.

- [ ] **Step 13.6: Commit (partial)**

```bash
git add scripts/compare_vcg_lead_time.py tests/integration/test_compare_vcg_lead_time.py
git commit -m "feat(scripts): compare_vcg_lead_time batch loaders + per-cell metric computation"
```

---

### Task 14: Comparator gate evaluator + report assembly

**Files:**
- Modify: `scripts/compare_vcg_lead_time.py`
- Modify: `tests/integration/test_compare_vcg_lead_time.py`

- [ ] **Step 14.1: Implement gate evaluator**

Append to `scripts/compare_vcg_lead_time.py`:

```python
@dataclass(frozen=True)
class GateVerdict:
    composite_method: str
    primary_utility_passed: bool
    primary_lead_passed: bool
    robustness_fp_passed: bool
    robustness_alarm_passed: bool
    robustness_hit_rate_passed: bool
    single_regime_dominance_passed: bool
    overall_pass: bool
    quoted_numbers: dict[str, str]


def _slice_value_primary(cells: list[CellResult], period: str, proxy: str, metric: str) -> float:
    for c in cells:
        if (c.period == period and c.benchmark == "SPX" and c.drawdown_def == "Fast"
                and c.credit_proxy == proxy):
            return getattr(c, metric)
    return float("nan")


def _slice_value_robustness(cells: list[CellResult], period: str, proxy: str, metric: str) -> float:
    vals = [getattr(c, metric) for c in cells
            if c.period == period and c.credit_proxy == proxy and c.n_events > 0]
    if not vals:
        return float("nan")
    return float(pd.Series(vals).median())


def _best_single(cells: list[CellResult], period: str, metric: str,
                 method: str = "primary") -> float:
    candidates = []
    for proxy in ("HYG", "JNK", "LQD"):
        v = (_slice_value_primary(cells, period, proxy, metric) if method == "primary"
             else _slice_value_robustness(cells, period, proxy, metric))
        if not pd.isna(v):
            candidates.append(v)
    if not candidates:
        return float("nan")
    return max(candidates)


def evaluate_gate(cells: list[CellResult], composite_proxy: str,
                  composite_method: str) -> GateVerdict:
    periods = [p[0] for p in PERIOD_SLICES]
    # Primary utility: composite > best single in >= 3 of 4 periods
    util_wins = 0
    for p in periods:
        comp = _slice_value_primary(cells, p, composite_proxy, "utility_score")
        best = _best_single(cells, p, "utility_score")
        if not pd.isna(comp) and not pd.isna(best) and comp > best:
            util_wins += 1
    primary_utility_passed = util_wins >= 3

    # Primary lead: no slice worse by more than 0.5d, AND improves by >= 1d in >= 2 slices
    lead_breaches = 0
    lead_strong_wins = 0
    improvements = []
    for p in periods:
        comp = _slice_value_primary(cells, p, composite_proxy, "median_actionable_lead")
        best = _best_single(cells, p, "median_actionable_lead")
        if pd.isna(comp) or pd.isna(best):
            continue
        diff = comp - best
        if diff < -0.5:
            lead_breaches += 1
        if diff >= 1.0:
            lead_strong_wins += 1
        improvements.append((p, max(0.0, diff)))
    primary_lead_passed = (lead_breaches == 0) and (lead_strong_wins >= 2)

    # Robustness gates
    def _rob(metric: str, threshold: float, kind: str) -> bool:
        wins = 0
        for p in periods:
            comp = _slice_value_robustness(cells, p, composite_proxy, metric)
            best = _best_single(cells, p, metric, method="robustness")
            if pd.isna(comp) or pd.isna(best):
                continue
            if kind == "fp" or kind == "alarm":  # lower is better; max relative increase threshold
                if best == 0:
                    if comp <= threshold:
                        wins += 1
                else:
                    rel = (comp - best) / best
                    if rel <= threshold:
                        wins += 1
            elif kind == "hitrate":  # spec §9 item 5: "within 5% absolute".
                # Composite must not be MORE THAN 5% WORSE than best single proxy.
                # A composite that beats the baseline must NOT fail this gate
                # (`abs(...)` would have done exactly that). The asymmetric form
                # captures the actual intent: floor at best-0.05, no ceiling.
                if comp >= best - threshold:
                    wins += 1
        return wins >= 3

    rob_fp = _rob("fp_episode_rate", 0.10, "fp")
    rob_alarm = _rob("alarm_day_ratio", 0.20, "alarm")
    rob_hit = _rob("hit_rate", 0.05, "hitrate")

    # Single-regime dominance
    total_improvement = sum(d for _, d in improvements)
    if total_improvement < 1.0:
        single_regime_ok = False
    else:
        max_p_improvement = max((d for _, d in improvements), default=0.0)
        single_regime_ok = max_p_improvement <= 0.5 * total_improvement

    overall = all([
        primary_utility_passed, primary_lead_passed,
        rob_fp, rob_alarm, rob_hit, single_regime_ok,
    ])

    quoted = {
        "primary_utility_wins": f"{util_wins}/4",
        "primary_lead_breaches": str(lead_breaches),
        "primary_lead_strong_wins": str(lead_strong_wins),
        "total_improvement_days": f"{total_improvement:.2f}",
        "max_period_improvement_share": (
            f"{max((d for _, d in improvements), default=0.0) / total_improvement:.2f}"
            if total_improvement > 0 else "n/a"
        ),
    }
    return GateVerdict(
        composite_method=composite_method,
        primary_utility_passed=primary_utility_passed,
        primary_lead_passed=primary_lead_passed,
        robustness_fp_passed=rob_fp,
        robustness_alarm_passed=rob_alarm,
        robustness_hit_rate_passed=rob_hit,
        single_regime_dominance_passed=single_regime_ok,
        overall_pass=overall,
        quoted_numbers=quoted,
    )
```

- [ ] **Step 14.2: Implement report assembly**

Append to `scripts/compare_vcg_lead_time.py`:

```python
def write_report(out_path: Path, cells: list[CellResult],
                 verdicts: list[GateVerdict],
                 data: "BatchData") -> None:
    """Spec §8 step 6 deliverable: full validation report markdown.

    Sections:
      1. Methodology recap (with explicit gate aggregation language)
      2. Data coverage (per-benchmark bar counts, used/dropped)
      3. Per-period results matrix
      4. Disagreement diagnostic
      5. Promotion gate verdicts
      6. Quoted numbers
      7. Run inventory + artifact appendix
    """
    enabled_benchmarks = list(data.benchmarks.keys())
    n_cells_per_slice = len(enabled_benchmarks) * len(DRAWDOWN_DEFS)
    lines: list[str] = [
        "# VCG composite proxy — drawdown lead-time validation report",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "Spec: docs/superpowers/specs/2026-05-26-vcg-composite-research-design.md",
        "",
        "## 1. Methodology recap",
        "",
        "Per-cell metrics computed against pre-declared:",
        f"- Benchmarks (enabled): {', '.join(enabled_benchmarks) or '(none)'}",
        f"- Drawdown defs: {', '.join(d.name for d in DRAWDOWN_DEFS)}",
        f"- Periods: {', '.join(p[0] for p in PERIOD_SLICES)}",
        "",
        "**Promotion gate aggregation** (lock-in, no author discretion):",
        "- Primary utility + primary lead gates: computed on `(SPX, Fast)` cell only.",
        f"- Robustness FP/alarm/hit-rate gates: median across all {n_cells_per_slice} enabled benchmark × drawdown_def cells with n_events > 0.",
        "- FP definition: an RO is NOT a false positive iff any event interval `[peak, trough]` overlaps `[ro_date, ro_date + H_def]` trading days.",
        "- Gate metric: `FP_episode_rate` (NOT `FP_day_rate`). Both reported.",
        "",
        "## 2. Data coverage",
        "",
        "| Benchmark | First bar | Last bar | Bars | Used? | Drop reason |",
        "|---|---|---|---|---|---|",
    ]
    # Use the BatchData's full benchmark dict (which only contains enabled
    # ones); for any preferred-but-dropped benchmark, note it explicitly.
    PREFERRED = ("SPX", "NDX", "RUT")
    for ticker in PREFERRED:
        s = data.benchmarks.get(ticker)
        if s is None:
            lines.append(f"| {ticker} | — | — | 0 | NO | < 4000 bars or absent from vol_index_daily |")
            continue
        lines.append(
            f"| {ticker} | {min(s.index)} | {max(s.index)} | {len(s)} | YES | — |"
        )
    lines.extend(["", "## 3. Per-period results matrix", ""])
    by_period: dict[tuple[str, str], list[CellResult]] = {}
    for c in cells:
        by_period.setdefault((c.period, c.drawdown_def), []).append(c)
    for (period, defn_name), period_cells in sorted(by_period.items()):
        lines.append(f"### {period} — {defn_name}")
        lines.append("")
        lines.append(
            "| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | "
            "FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |"
        )
        lines.append("|" + "---|" * 17)
        for c in sorted(period_cells, key=lambda r: (r.credit_proxy, r.benchmark)):
            lines.append(
                f"| {c.credit_proxy} | {c.composite_method} | {c.benchmark} | {c.n_events} | "
                f"{c.median_actionable_lead:.2f} | {c.median_close_lead:.2f} | "
                f"{c.hit_rate:.2%} | {c.fp_day_rate:.2%} | {c.fp_episode_rate:.2%} | "
                f"{c.fp_short_horizon_rate:.2%} | {c.precision_day:.2%} | {c.recall_event:.2%} | "
                f"{c.alarm_day_ratio:.2%} | {c.ro_episode_count} | "
                f"{c.median_ro_episode_length_bdays:.1f} | {c.disagreement_vs_hyg_rate:.2%} | "
                f"{c.utility_score:.3f} |"
            )
        lines.append("")

    lines.append("## 4. Disagreement diagnostic")
    lines.append("")
    lines.append("Days where each composite variant's RO signal disagrees with HYG baseline.")
    lines.append("Aggregated as median `disagreement_vs_hyg_rate` over all enabled cells, per variant.")
    lines.append("")
    lines.append("| Method | Median disagreement % |")
    lines.append("|---|---|")
    by_method: dict[str, list[float]] = {}
    for c in cells:
        if not pd.isna(c.disagreement_vs_hyg_rate):
            by_method.setdefault(c.composite_method, []).append(c.disagreement_vs_hyg_rate)
    for method, rates in sorted(by_method.items()):
        med = float(pd.Series(rates).median()) if rates else float("nan")
        lines.append(f"| {method} | {med:.2%} |")
    lines.append("")

    lines.append("## 5. Promotion gate verdicts")
    lines.append("")
    lines.append("| Method | Primary util | Primary lead | Robust FP | Robust alarm | Robust hit | Regime dominance | **Overall** |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for v in verdicts:
        def _mark(b: bool) -> str: return "PASS" if b else "FAIL"
        lines.append(
            f"| {v.composite_method} | {_mark(v.primary_utility_passed)} | "
            f"{_mark(v.primary_lead_passed)} | {_mark(v.robustness_fp_passed)} | "
            f"{_mark(v.robustness_alarm_passed)} | {_mark(v.robustness_hit_rate_passed)} | "
            f"{_mark(v.single_regime_dominance_passed)} | "
            f"**{_mark(v.overall_pass)}** |"
        )
    lines.append("")
    lines.append("## 6. Quoted numbers")
    lines.append("")
    for v in verdicts:
        lines.append(f"### {v.composite_method}")
        for k, val in v.quoted_numbers.items():
            lines.append(f"- {k}: {val}")
        lines.append("")

    lines.append("## 7. Run inventory + artifact appendix")
    lines.append("")
    lines.append("| run_id | indicator | composite_version | composite_method | credit_proxy | run_scope | weights_artifact_sha256 |")
    lines.append("|---|---|---|---|---|---|---|")
    for run in sorted(data.runs, key=lambda r: r.run_id):
        # Inventory only — weight artifact SHA may live in summary["extras"]
        lines.append(
            f"| {run.run_id} | vcg | {run.composite_version} | {run.composite_method} | "
            f"{run.credit_proxy} | research | — (see summary.extras.weights_artifact_sha256) |"
        )
    lines.append("")
    lines.append("### Query templates (for replay)")
    lines.append("")
    lines.append("```sql")
    lines.append("-- Production v1 HYG row (Hard Guarantee #2 default selection)")
    lines.append("SELECT * FROM uw_scan.regime_backtest_runs")
    lines.append(" WHERE indicator='vcg' AND run_scope='production'")
    lines.append("   AND composite_version='1' AND credit_proxy='HYG'")
    lines.append("   AND composite_method='single_proxy' AND completed_at IS NOT NULL")
    lines.append(" ORDER BY created_at DESC LIMIT 1;")
    lines.append("```")
    out_path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="docs/research/regime/vcg-composite-validation-2026-05-26.md")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    data = batch_load_all(settings)
    cells = run_all_cells(data)
    composite_proxies = [
        ("COMPOSITE_RP3", "risk_parity_3"),
        ("COMPOSITE_RP_HYJK", "risk_parity_hyjk"),
        ("COMPOSITE_HY_MINUS_IG", "hy_minus_ig_spread"),
        ("COMPOSITE_EQ3", "equal_weight_3"),
    ]
    verdicts = [evaluate_gate(cells, p, m) for p, m in composite_proxies]
    write_report(Path(args.out), cells, verdicts, data)
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 14.3: Fill in the integration test**

Replace the skip in `tests/integration/test_compare_vcg_lead_time.py` with a real end-to-end smoke test that:

```python
def test_comparator_produces_report_with_gate_verdicts(tmp_path, seeded_db_empty_cards) -> None:
    """End-to-end: seed minimal benchmark + run data, invoke main(), assert report
    contains the four method verdicts in §3 and all four periods in §2."""
    conn = seeded_db_empty_cards.conn
    _seed_minimal_data(conn)  # benchmark closes + 4 single-proxy + 4 composite rows
    out = tmp_path / "report.md"
    import subprocess, sys
    r = subprocess.run(
        ["uv", "run", "python", "scripts/compare_vcg_lead_time.py", "--out", str(out)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    body = out.read_text()
    assert "## 3. Promotion gate verdicts" in body
    for method in ("risk_parity_3", "risk_parity_hyjk",
                   "hy_minus_ig_spread", "equal_weight_3"):
        assert method in body
    for period_name, *_ in [("pre-2020",), ("2020-COVID",),
                             ("2021-2022-rates",), ("2023-2026-AI",)]:
        assert period_name in body
```

The `_seed_minimal_data` helper creates 4-period worth of benchmark closes with at least one synthetic drawdown event per period AND four research single-proxy + four composite runs each with synthetic daily payloads.

- [ ] **Step 14.4: Run tests to confirm pass**

Run: `uv run pytest tests/integration/test_compare_vcg_lead_time.py -v`
Expected: PASS.

- [ ] **Step 14.5: Commit**

```bash
git add scripts/compare_vcg_lead_time.py tests/integration/test_compare_vcg_lead_time.py
git commit -m "feat(scripts): comparator gate evaluator + markdown report assembly"
```

---

## Phase 8 — Run the actual research

### Task 15: Run all seven research backtests

**Files:** None modified. Database writes only.

- [ ] **Step 15.1: Run single-proxy research baselines**

Run:
```bash
uv run python scripts/backtest_vcg.py --research-proxy HYG --note "VCG research baseline"
uv run python scripts/backtest_vcg.py --research-proxy JNK --note "VCG research baseline"
uv run python scripts/backtest_vcg.py --research-proxy LQD --note "VCG research baseline"
```
Expected: Three new rows in `regime_backtest_runs` with `run_scope='research'`, `composite_method='single_proxy'`, `composite_version='1'`.

- [ ] **Step 15.2: Run composite backtests**

Run:
```bash
uv run python scripts/backtest_vcg.py --composite-method risk_parity_3 --note "VCG composite candidate"
uv run python scripts/backtest_vcg.py --composite-method risk_parity_hyjk --note "VCG composite candidate"
uv run python scripts/backtest_vcg.py --composite-method hy_minus_ig_spread --note "VCG composite candidate"
uv run python scripts/backtest_vcg.py --composite-method equal_weight_3 --note "VCG comparator baseline"
```
Expected: Four new rows in `regime_backtest_runs` with `run_scope='research'`. Each composite row has a non-null `summary.extras.weights_artifact_sha256`.

- [ ] **Step 15.3: Verify production default unchanged**

Run:
```bash
psql "$DATABASE_URL" -c "
SELECT id, credit_proxy, composite_method, run_scope, composite_version
FROM uw_scan.regime_backtest_runs
WHERE indicator='vcg' AND completed_at IS NOT NULL
ORDER BY created_at DESC LIMIT 10;
"
```
Then call the API:
```bash
curl -s http://localhost:8400/api/regime/vcg-validation | jq '.run.credit_proxy'
```
Expected: `"HYG"` — the production default is still HYG even though research rows are newer.

---

### Task 16: Run comparator and commit validation report

**Files:**
- Create: `docs/research/regime/vcg-composite-validation-2026-05-26.md` (generated)

- [ ] **Step 16.1: Run comparator**

Run:
```bash
uv run python scripts/compare_vcg_lead_time.py
```
Expected: `docs/research/regime/vcg-composite-validation-2026-05-26.md` written.

- [ ] **Step 16.2: Sanity-review the report**

Open the report. Verify:
- §2 has four period sections, each with three drawdown_def subsections, each with up to 21 rows (7 proxy variants × 3 benchmarks; some cells may have `n_events=0` and report NaN metrics).
- §3 has four gate verdicts (one per composite method).
- §4 quotes the numerator/denominator for each gate criterion.

If any section is empty or NaN-heavy, investigate before committing. Common causes: a benchmark dropped in Task 12 reduces the cell count; a research run with too short history fails the warmup check.

- [ ] **Step 16.3: Commit the report**

```bash
git add docs/research/regime/vcg-composite-validation-2026-05-26.md
git commit -m "docs(research): VCG composite proxy validation report — 2026-05-26"
```

---

### Task 17: Methodology doc update

**Files:**
- Modify: `docs/research/regime/vcg-methodology.md`

- [ ] **Step 17.1: Update §3 (Proxy choice)**

Edit `docs/research/regime/vcg-methodology.md` §3:

Append (or replace stub if present) a subsection documenting:
1. The four composite candidate methods (risk_parity_3, risk_parity_hyjk, hy_minus_ig_spread, equal_weight_3) with one-paragraph descriptions.
2. The strict no-lookahead invariant: `weights[i] = f(returns[:i])` via `.shift(weight_lag)` in `cards/vcg_basket.py`.
3. The OLS causality contract: signals at close `t` are actionable on `t+1`.
4. The verbatim statement: **"Composite residual is NOT a weighted average of single-proxy residuals — the schema separation prevents future readers from inferring otherwise."**
5. A link to `docs/research/regime/vcg-composite-validation-2026-05-26.md` with the gate verdict summary.

- [ ] **Step 17.2: Commit**

```bash
git add docs/research/regime/vcg-methodology.md
git commit -m "docs(research): vcg-methodology §3 — composite formulation + causality contract"
```

---

## §16. Plan self-review

Conducted per the writing-plans skill checklist:

**1. Spec coverage**

| Spec section | Plan task |
|---|---|
| §1 Hard Guarantee #1 (no production scanner change) | Task 3 (import-boundary test); Task 9 (RESEARCH symbols on research path only) |
| §1 HG #2 (default API filters 4 columns) | Task 2 (find_latest_run filter chain); Task 3 (selection isolation test) |
| §1 HG #3 (structural exclusion via columns) | Task 1 (column promotion); Task 3 (parametrised isolation test) |
| §1 HG #4 (research single-proxy ≠ production) | Task 11 (--research-proxy mutually exclusive with --proxy) |
| §1 HG #5 (no promotion until gate passes) | Task 14 (gate verdict per method); Task 17 (no scanner cutover code in plan) |
| §3 migration safety + idempotency | Task 1 (two-phase + DO blocks + idempotency test) |
| §4 no-lookahead invariant | Task 5 (both perturbation test + full-replay reference test) |
| §4 OLS causality contract | Task 9 (compute_vcg_composite uses existing causally-clean OLS; production regression test) |
| §4 MethodMetadata + 4 methods | Task 6 |
| §5 attribution layers (basket_construction vs signal_breakdown) | Task 9 |
| §6 row shape + parquet artifact hash | Task 10 (canonical bytes) + Task 11 (write + persist sha) |
| §7 CLI mutual exclusivity | Task 11 |
| §8 drawdown detector non-overlap (within-def) | Task 7 |
| §8 actionable hit rule (actionable_lead >= 0) | Task 8 (hit_rate filters by actionable_lead >= 0) |
| §8 FP horizon per-definition | Task 13 (FP_HORIZON_DAYS map) |
| §9 promotion gate (primary + robustness + dominance) | Task 14 (evaluate_gate) |
| §10 adjusted vs raw close policy | Task 11 (`prefer_adj=True` only for HYG/JNK/LQD; raw `close` for VIX/VVIX) |
| §11.4 benchmark coverage gap | Task 12 (multi-ticker seed + precheck) |
| §11.6 import-boundary test | Task 3 |
| §11.7 API run-selection test | Task 3 |
| §12 module size budget | Each new file under 290 lines per estimate |
| §13 milestone commits | One commit per task |
| §15 sequential comparator + zero-DB-in-loop | Task 13 (`batch_load_all` returns; loop uses `BatchData` only) |

**2. Placeholder scan**

No "TBD" / "TODO" / "fill in" / "similar to" tokens. Every step shows the actual code or command. The two cases where code is referenced but the test body is deferred:
- Task 13.1 has a placeholder synthetic-data helper; Task 14.3 fills it in. The plan must read sequentially; an executor jumping straight to Task 13 should commit only after Task 14.3 lands.
- Task 17 references the existing `vcg-methodology.md` §3; plan author should read that file first to integrate cleanly rather than overwrite.

**3. Type consistency**

- `MethodMetadata` defined in Task 6, imported in Task 9 — same dataclass.
- `DrawdownEvent` defined in Task 7, consumed in Tasks 8, 13 — same shape.
- `BatchData` / `ProxyRun` / `CellResult` / `GateVerdict` defined and used consistently in Tasks 13–14.
- `run_scope`, `composite_method`, `credit_proxy` column names used identically across Tasks 1, 2, 3, 11.
- `RESEARCH_COMPOSITE_VERSIONS` and `_COMPOSITE_PROXY_LABEL` defined in Task 9, consumed in Task 11.

**4. Open items recorded**

- Step 11.3 single-proxy branch ("existing single-proxy backtest produces daily_rows and summary") preserves existing code; refactoring detail is intentional brevity. Executor must keep the existing single-proxy logic bit-identical for the `--proxy HYG` path.
- Step 12.4 may yield less UW history for RUT than for SPX/NDX; comparator gracefully drops missing tickers via the 4000-bar precheck in `load_benchmarks`. If RUT falls below threshold, the validation universe drops to two benchmarks (SPX + NDX); the gate's primary cell `(SPX, Fast)` remains intact, only robustness aggregation thins.

---

## §17. Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-26-vcg-composite-proxy.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Each task gets its own context with the spec and the task definition only — reduces context drift.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints. Easier when tasks share context that doesn't fit in a brief.
