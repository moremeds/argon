# VCG Regime-Classification Accuracy Implementation Plan (v0.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score VCG v1 on regime-classification accuracy against a pre-declared Level-1 taxonomy and produce an immutable baseline report with three-state verdict + quantitative failure-mode classification. Phase B1 of the post-PR-#81 roadmap.

**Architecture:** Pure-function label-derivation + scoring modules driven by a frozen YAML label contract. Persistence reuses `regime_backtest_runs/daily` with classification payload in `payload` JSONB. Migration 061 extends `composite_method` CHECK; Migration 062 adds a partial unique index preventing concurrent-run races. The entry script supports `--render-run-id` replay returning persisted markdown bytes for true byte-identical reproduction.

**Tech Stack:** Python 3.13 (uv-managed), pandas, psycopg 3.3+, PyYAML, pytest + pytest-postgresql.

**Spec:** `docs/superpowers/specs/2026-05-26-vcg-regime-classification-design.md` v0.2.

**Patch history:**
- v0.1: Initial plan derived from spec v0.2.
- v0.2: 15 patches (8 blocking + 5 should-fix + 3 clarifications).
- v0.3: 24 tribunal patches (Codex + Claude bilateral; Gemini unavailable). See `docs/reviews/2026-05-26-vcg-classification-plan-tribunal-review.md`.

**v0.3 changes** (24 fixes — see §Self-Review traceability table at end of plan):
CR-1 byte-identical replay via persisted report_md | CR-2 migration 062 unique index |
CO-1 multi-vintage macro DISTINCT ON | CO-2 NaN→None JSONB sanitizer |
CO-3 percentile tie rule in YAML | CO-4 NORMAL band widened to exhaustive |
CO-5 migration verifies existing methods | CO-6 E2E seed includes as_of/source |
CO-7 confusion matrix aligns by index | CO-8 label_mismatch guard against empty cm |
CO-9 window semantics documented | CO-10 eval_end honored |
CL-1 benchmark_coverage deferred (documented) | CL-2 underpowered_test mode |
CL-3 NFCI raw value snapshot | CL-4 verify_integrity on set_index |
CL-5 E2E proper DSN | CL-6 vintages section in report |
CL-7 explicit non-None assertions | CL-8 atomic insert→bulk→mark transaction |
CL-9 _normalize_date_index consistent | CL-10 pd.isna explicit |
CL-11 error message remediation hint | CL-12 BEGIN/COMMIT migration wrap.

**NEW Phase 0.5**: FRED NFCI/ANFCI/USREC ingestion (separate prereq PR; `sources/fred.py` doesn't currently fetch these — discovered during tribunal probe).

---

## File Structure

**Create:**
- `docs/research/regime/ground-truth-labels/level1-thresholds.yaml`
- `docs/research/regime/ground-truth-labels/named-crises.yaml`
- `docs/research/regime/ground-truth-labels/vcg-source.yaml`
- `docs/research/regime/ground-truth-labels/label-version.yaml`
- `src/uw_scan/storage/migrations/061_classification_accuracy_composite_method.sql`
- `src/uw_scan/storage/migrations/062_classification_unique_index.sql`
- `src/uw_scan/cards/regime_classification_labels.py`
- `src/uw_scan/cards/regime_classification_scoring.py`
- `src/uw_scan/storage/regime_classification_repository.py`
- `src/uw_scan/reports/regime_classification_report.py`
- `scripts/score_vcg_classification_accuracy.py`
- `tests/unit/cards/test_regime_classification_labels.py`
- `tests/unit/cards/test_regime_classification_scoring.py`
- `tests/unit/storage/test_regime_classification_repository.py`
- `tests/unit/reports/test_regime_classification_report.py`
- `tests/integration/test_score_vcg_classification_accuracy.py`
- `tests/integration/test_regime_classification_e2e.py`

**Modify:**
- `src/uw_scan/storage/repository.py` — re-export only

---

## Phase 0: Preflight verification (no code)

### Task 0.1: Verify Phase A1 (Migration 060 `archived_at`) is merged

- [ ] **Step 1**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT 1 FROM information_schema.columns
                   WHERE table_schema='uw_scan' AND table_name='regime_backtest_runs'
                     AND column_name='archived_at' ''')
    assert cur.fetchone(), 'Phase A1 not merged — STOP'
print('A1 archived_at present')
"
```

Expected: `A1 archived_at present`. If failure, merge Phase A1 first.

### Task 0.2: Identify canonical VCG v1 run

- [ ] **Step 1**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT id, composite_version, credit_proxy, n_days, created_at
                   FROM uw_scan.regime_backtest_runs
                   WHERE indicator='vcg' AND run_scope='production' AND completed_at IS NOT NULL
                   ORDER BY n_days DESC, created_at DESC LIMIT 1''')
    print(cur.fetchone())
"
```

Record the `(id, composite_version, credit_proxy, n_days, created_at)` tuple. The `id` becomes `vcg-source.yaml.vcg_source.run_id` in Task 1.3.

### Task 0.3: Multi-vintage macro tables schema probe (UPDATED v0.3 / CO-1 + CO-6)

- [ ] **Step 1: Probe columns**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT column_name, data_type, is_nullable
                   FROM information_schema.columns
                   WHERE table_schema='uw_scan' AND table_name='macro_series_daily'
                   ORDER BY ordinal_position''')
    for row in cur.fetchall():
        print(row)
"
```

**Expected** (per migration 037): columns include `series_id`, `obs_date`, `value`, `as_of`, `release_date`, `source`, `source_url`. PK `(series_id, obs_date, as_of)`. `as_of` and `source` are NOT NULL — Phase 9 E2E seeds must include them.

- [ ] **Step 2: Probe NFCI/ANFCI/USREC data coverage**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT series_id, MIN(obs_date), MAX(obs_date), COUNT(*)
                   FROM uw_scan.macro_series_daily
                   WHERE series_id IN ('NFCI', 'ANFCI', 'USREC')
                   GROUP BY series_id ORDER BY series_id''')
    rows = cur.fetchall()
    for r in rows: print(r)
    if not rows:
        print('NO NFCI/ANFCI/USREC DATA — Phase 0.5 ingestion task required first')
"
```

If empty → STOP; go to Phase 0.5.

### Task 0.4: Probe `composite_method` CHECK constraint

- [ ] **Step 1**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT con.conname, pg_get_constraintdef(con.oid)
                   FROM pg_constraint con
                   JOIN pg_class rel ON rel.oid=con.conrelid
                   JOIN pg_namespace nsp ON nsp.oid=rel.relnamespace
                   WHERE nsp.nspname='uw_scan' AND rel.relname='regime_backtest_runs'
                     AND con.contype='c' ''')
    for row in cur.fetchall(): print(row)
"
```

### Task 0.5: Probe `composite_method` distinct observed values (NEW v0.3 / CO-5)

- [ ] **Step 1**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT DISTINCT composite_method FROM uw_scan.regime_backtest_runs
                   WHERE composite_method IS NOT NULL ORDER BY composite_method''')
    methods = [row[0] for row in cur.fetchall()]
    print('Observed composite_methods:', methods)
    expected = {'single_proxy','risk_parity_3','risk_parity_hyjk','hy_minus_ig_spread','equal_weight_3','classification_accuracy'}
    missing = set(methods) - expected
    if missing:
        print(f'WARN: observed methods not in Migration 061 allow-list: {missing}')
        print('Migration 061 must be extended to include these — DO NOT proceed.')
"
```

If `missing` is non-empty, STOP and extend Migration 061's allow-list before applying.

---

## Phase 0.5: NFCI / USREC FRED ingestion (separate prereq PR)

**Critical discovery from tribunal**: `src/uw_scan/sources/fred.py` does NOT currently fetch NFCI, ANFCI, or USREC.

**Action**: implement in a separate PR, mirroring the gold-related FRED pattern at `src/uw_scan/worker/jobs/gold_jobs.py::gold_fred_ingest_job`. Specifically:

1. Add series registry entries for `NFCI`, `ANFCI`, `USREC` in `src/uw_scan/sources/fred.py`.
2. Add scheduler job `regime_fred_ingest_job` pulling weekly into `macro_series_daily`.
3. Backfill historical: `uv run python -m uw_scan.worker.backfill --series NFCI ANFCI USREC --start 2007-01-01`.
4. Task 0.3 must return rows after this lands.

**This plan's Phase 3+ cannot execute until Phase 0.5 is merged AND data is backfilled.** Task 0.3 catches the gap at runtime if Phase 0.5 isn't merged.

---

## Phase 1: Label contract YAMLs

### Task 1.1: Author `level1-thresholds.yaml`

**Files:** Create `docs/research/regime/ground-truth-labels/level1-thresholds.yaml`

- [ ] **Step 1**

```yaml
# Level-1 ground-truth thresholds. SOURCE OF TRUTH — replays use exactly these.
# Bump label_version in label-version.yaml and start a new file to revise.

label_version: 1
contract_committed_at: "2026-05-26"

# Rolling-window definitions
# rolling_window_days N: the window includes today (1 slot) + N-1 prior days (cohort).
# So percentile rank with rolling_window_days=252 ranks today against the 251 prior days.
# (v0.3 / CO-9 explicit semantics documentation.)
rolling_window_days: 252
realized_vol_window_days: 21

# Percentile tie semantics (v0.3 / CO-3)
# strict_lt: count cohort strictly less than today; ties resolve to 0
percentile_tie_rule: "strict_lt"

# Class-membership percentile cutoffs
P_SUPP: 0.30
P_RO: 0.80
P_PANIC: 0.95
DD_EDR: 0.07
N_BOUNCE: 10

# NORMAL band — v0.3 / CO-4 widened to be exhaustive between SUPPRESSED (<0.30)
# and stress (>=0.80). Previous [0.25, 0.75] left a silent fall-through gap.
NORMAL_LOW: 0.30
NORMAL_HIGH: 0.80
NORMAL_DD: 0.05

# Verdict gates
N_MIN_CLASS_DAYS: 30
K_MIN_CORE_ELIGIBLE: 4
MACRO_F1_PASS: 0.50

# Failure-mode triggers
PANIC_SUPPRESSION_RATIO: 0.20
SPARSITY_RATIO: 0.25
MISMATCH_CONCENTRATION: 0.60
BENCH_RANGE: 0.15

# FRED series pinning
fred_series:
  credit_stress_primary: "NFCI"
  credit_stress_sensitivity: "ANFCI"
  recession_dating: "USREC"

# Eval window — eval_end can be "auto" (latest data) or ISO date for replay
eval_start: "2007-01-03"
eval_end: "auto"

# Period buckets (matches PR #81 comparator)
period_buckets:
  - {name: "pre-2020",        start: "2007-01-03", end: "2019-12-31"}
  - {name: "2020-COVID",      start: "2020-01-02", end: "2020-12-31"}
  - {name: "2021-2022-rates", start: "2021-01-04", end: "2022-12-30"}
  - {name: "2023-2026-AI",    start: "2023-01-03", end: "auto"}
```

### Task 1.2: Author `named-crises.yaml`

**Files:** Create `docs/research/regime/ground-truth-labels/named-crises.yaml`

- [ ] **Step 1**

```yaml
# Level-2 named-crisis windows for sanity overlay only.
# use_for_headline is ALWAYS false. These do not gate the verdict;
# Phase 8 entry script computes per-window VCG/truth label distributions
# and the report renders them in a separate sanity-overlay section.

label_version: 1
crises:
  - name: "GFC-Lehman"
    start_date: "2008-09-15"
    end_date: "2009-03-09"
    provenance: "Bear Stearns sale 2008-03-16 / Lehman bankruptcy 2008-09-15 / SPX trough 2009-03-09"
    use_for_headline: false
  - name: "Eurozone-sovereign"
    start_date: "2011-08-01"
    end_date: "2012-09-06"
    provenance: "S&P US downgrade Aug 2011 / Draghi 2012-07-26 / OMT 2012-09-06"
    use_for_headline: false
  - name: "China-devaluation-2015"
    start_date: "2015-08-10"
    end_date: "2015-10-02"
    provenance: "PBoC CNY devaluation 2015-08-11 / SPX flash crash 2015-08-24"
    use_for_headline: false
  - name: "Q4-2018-vol-regime"
    start_date: "2018-10-03"
    end_date: "2018-12-26"
    provenance: "Powell 'long way from neutral' 2018-10-03 / Christmas Eve trough 2018-12-24"
    use_for_headline: false
  - name: "COVID-2020"
    start_date: "2020-02-19"
    end_date: "2020-03-23"
    provenance: "SPX ATH 2020-02-19 / SPX trough 2020-03-23 (-33.9%)"
    use_for_headline: false
  - name: "2022-rates-bear"
    start_date: "2022-01-03"
    end_date: "2022-10-13"
    provenance: "SPX ATH 2022-01-03 / CPI shock 2022-09-13 / trough 2022-10-13"
    use_for_headline: false
  - name: "2023-SVB-week"
    start_date: "2023-03-08"
    end_date: "2023-03-17"
    provenance: "SVB run 2023-03-09 / SVB+Signature seized 2023-03-10/12"
    use_for_headline: false
```

### Task 1.3: Author `vcg-source.yaml`

**Files:** Create `docs/research/regime/ground-truth-labels/vcg-source.yaml`

- [ ] **Step 1: Pin the canonical VCG v1 run from Task 0.2**

```yaml
# Pinned VCG source. NEVER resolved at runtime via find_latest_run.
# Replays MUST reference exactly this run.

label_version: 1
vcg_source:
  run_id: <REPLACE WITH ID FROM TASK 0.2>
  indicator: "vcg"
  composite_version: "1"
  run_scope: "production"
  credit_proxy: "<from Task 0.2 — likely HYG>"
  pinned_at: "2026-05-26"
  pinned_because: "Canonical production VCG v1 backtest, longest-coverage completed run."
```

### Task 1.4: Author `label-version.yaml`

**Files:** Create `docs/research/regime/ground-truth-labels/label-version.yaml`

- [ ] **Step 1**

```yaml
version: 1
committed_at: "2026-05-26"
notes: "Initial label contract. 24 v0.3 patches applied across 3 review rounds. See spec at docs/superpowers/specs/2026-05-26-vcg-regime-classification-design.md."
```

### Task 1.5: Commit Phase 1

- [ ] **Step 1: Verify YAML validity**

```bash
uv run python -c "
import yaml
for p in [
    'docs/research/regime/ground-truth-labels/level1-thresholds.yaml',
    'docs/research/regime/ground-truth-labels/named-crises.yaml',
    'docs/research/regime/ground-truth-labels/vcg-source.yaml',
    'docs/research/regime/ground-truth-labels/label-version.yaml',
]:
    with open(p) as f: yaml.safe_load(f)
    print(f'OK: {p}')
"
```

Expected: 4 OK lines.

- [ ] **Step 2: Commit**

```bash
git add docs/research/regime/ground-truth-labels/
git commit -m "docs(regime): commit Level-1 label contract YAMLs v1

v0.3 patches:
- CO-3: explicit percentile_tie_rule
- CO-4: widened NORMAL band [0.30, 0.80] for exhaustive coverage
- CO-9: window semantics documented inline

Spec: docs/superpowers/specs/2026-05-26-vcg-regime-classification-design.md"
```

---

## Phase 2: Migrations 061 + 062

### Task 2.1: Migration 061 — extended CHECK with regression check

**Files:** Create `src/uw_scan/storage/migrations/061_classification_accuracy_composite_method.sql`

- [ ] **Step 1**

```sql
-- 061_classification_accuracy_composite_method.sql
-- Extend regime_backtest_runs.composite_method CHECK to allow 'classification_accuracy'.
--
-- v0.3 patches:
--   CO-5: verify existing distinct composite_method values are all in the new
--         allow-list before drop; raise otherwise.
--   CL-12: wrap in explicit BEGIN/COMMIT (migrate.sh uses psql autocommit
--          per-statement; without BEGIN, table briefly has no constraint).

SET search_path = uw_scan, public;

BEGIN;

DO $$
DECLARE
    observed TEXT;
    allowed TEXT[] := ARRAY[
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3',
        'classification_accuracy'
    ];
    constraint_name TEXT;
BEGIN
    -- CO-5: assert every observed value is in the allow-list
    FOR observed IN
        SELECT DISTINCT composite_method FROM uw_scan.regime_backtest_runs
        WHERE composite_method IS NOT NULL
    LOOP
        IF NOT (observed = ANY(allowed)) THEN
            RAISE EXCEPTION
                'Migration 061 would regress composite_method %; not in allow-list',
                observed;
        END IF;
    END LOOP;

    -- Drop any pre-existing composite_method CHECK constraints
    FOR constraint_name IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'uw_scan'
          AND rel.relname = 'regime_backtest_runs'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) LIKE '%composite_method%'
    LOOP
        EXECUTE format(
            'ALTER TABLE uw_scan.regime_backtest_runs DROP CONSTRAINT IF EXISTS %I',
            constraint_name
        );
    END LOOP;
END $$;

ALTER TABLE uw_scan.regime_backtest_runs
    ADD CONSTRAINT regime_backtest_runs_composite_method_check
    CHECK (composite_method IN (
        'single_proxy',
        'risk_parity_3',
        'risk_parity_hyjk',
        'hy_minus_ig_spread',
        'equal_weight_3',
        'classification_accuracy'
    ));

COMMIT;

DO $$ BEGIN
    RAISE NOTICE 'Migration 061: composite_method now accepts classification_accuracy';
END $$;
```

### Task 2.2: Migration 062 — partial unique index (CR-2)

**Files:** Create `src/uw_scan/storage/migrations/062_classification_unique_index.sql`

- [ ] **Step 1**

```sql
-- 062_classification_unique_index.sql
-- Partial unique index preventing concurrent classification_accuracy runs from
-- creating duplicate completed rows for the same (vcg_source_run_id, label_version).
-- v0.3 / CR-2: closes the find-then-insert race in score_vcg_classification_accuracy.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS regime_classification_completed_uniq
  ON uw_scan.regime_backtest_runs (
    indicator,
    composite_method,
    run_scope,
    ((params->>'vcg_source_run_id')::int),
    ((params->>'label_version')::int)
  )
  WHERE composite_method = 'classification_accuracy'
    AND completed_at IS NOT NULL
    AND archived_at IS NULL;

COMMIT;
```

### Task 2.3: Apply both migrations + verify idempotency

- [ ] **Step 1**

```bash
bash scripts/migrate.sh
bash scripts/migrate.sh  # second run — must succeed (idempotent)
```

Expected: both runs succeed.

- [ ] **Step 2: Verify**

```bash
uv run python -c "
import os
from psycopg import connect
with connect(os.environ['UW_SCAN_DB_URL']) as conn, conn.cursor() as cur:
    cur.execute('''SELECT pg_get_constraintdef(con.oid) FROM pg_constraint con
                   JOIN pg_class rel ON rel.oid=con.conrelid
                   JOIN pg_namespace nsp ON nsp.oid=rel.relnamespace
                   WHERE nsp.nspname='uw_scan' AND rel.relname='regime_backtest_runs'
                     AND con.conname='regime_backtest_runs_composite_method_check' ''')
    assert 'classification_accuracy' in cur.fetchone()[0]
    cur.execute('''SELECT 1 FROM pg_indexes WHERE schemaname='uw_scan'
                   AND tablename='regime_backtest_runs'
                   AND indexname='regime_classification_completed_uniq' ''')
    assert cur.fetchone()
print('Migrations 061+062 verified')
"
```

### Task 2.4: Commit Phase 2

- [ ] **Step 1**

```bash
git add src/uw_scan/storage/migrations/061_classification_accuracy_composite_method.sql \
        src/uw_scan/storage/migrations/062_classification_unique_index.sql
git commit -m "feat(migrations): 061 composite_method + 062 classification unique index

061 — extends regime_backtest_runs.composite_method CHECK to allow
'classification_accuracy'. CO-5: verifies observed values fit allow-list.
CL-12: wrapped in BEGIN/COMMIT.

062 — partial unique index preventing concurrent classification runs from
creating duplicate completed rows for same (vcg_source_run_id, label_version).
v0.3 / CR-2."
```

---

## Phase 3: Level-1 label derivation (pure functions, TDD)

### Task 3.1: Realized vol + trailing drawdown

**Files:**
- Create: `src/uw_scan/cards/regime_classification_labels.py`
- Create: `tests/unit/cards/test_regime_classification_labels.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/cards/test_regime_classification_labels.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.regime_classification_labels import (
    compute_realized_vol,
    compute_trailing_drawdown,
)


def test_realized_vol_constant_returns_is_zero():
    """Constant +1% daily growth: log returns are constant → realized vol = 0."""
    close = pd.Series([100.0 * (1.01 ** i) for i in range(30)])
    rv = compute_realized_vol(close, window=21)
    assert rv.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_realized_vol_alternating_returns_matches_pandas_std():
    """Alternating ±1% returns over 21d → known std of log returns."""
    returns = pd.Series([0.01, -0.01] * 30)
    close = 100.0 * np.exp(returns.cumsum())
    rv = compute_realized_vol(close, window=21)
    log_returns = np.log(close / close.shift(1))
    expected = log_returns.iloc[-21:].std(ddof=1) * np.sqrt(252)
    assert rv.iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_trailing_drawdown_from_rolling_peak():
    close = pd.Series([100.0, 110.0, 120.0, 100.0, 90.0, 95.0, 110.0])
    dd = compute_trailing_drawdown(close, window=252)
    expected = pd.Series([0.0, 0.0, 0.0, -20 / 120, -30 / 120, -25 / 120, 0.0])
    pd.testing.assert_series_equal(dd, expected, check_exact=False, rtol=1e-9)
```

- [ ] **Step 2: Run, expect fail**

```bash
uv run pytest tests/unit/cards/test_regime_classification_labels.py -v
```

- [ ] **Step 3: Implement**

```python
# src/uw_scan/cards/regime_classification_labels.py
"""Level-1 ground-truth label derivation for VCG regime-classification accuracy.

All functions pure (no DB, no I/O). derive_level1_frame returns a DataFrame
with label_components for audit/replay payload persistence (v0.3 / CL-3).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252

CANONICAL_CLASSES = ("NORMAL", "SUPPRESSED", "EDR", "RISK_OFF", "PANIC", "BOUNCE")


def compute_realized_vol(close: pd.Series, *, window: int) -> pd.Series:
    """Annualized close-to-close realized volatility on a `window`-day window."""
    returns = np.log(close / close.shift(1))
    return returns.rolling(window).std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)


def compute_trailing_drawdown(close: pd.Series, *, window: int) -> pd.Series:
    """Drawdown from the rolling `window`-day peak. Always ≤ 0."""
    rolling_peak = close.rolling(window, min_periods=1).max()
    return close / rolling_peak - 1.0
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/cards/test_regime_classification_labels.py -v
```

### Task 3.2: Percentile rank with explicit tie semantics (v0.3 / CO-3)

- [ ] **Step 1: Write the failing tests**

Append to test file:

```python
from uw_scan.cards.regime_classification_labels import compute_rolling_percentile_rank


def test_percentile_rank_uses_prior_window_no_lookahead():
    s = pd.Series(range(1, 11), dtype=float)
    pr = compute_rolling_percentile_rank(s, window=5, tie_rule="strict_lt")
    assert pr.iloc[:4].isna().all()
    assert pr.iloc[4] == pytest.approx(1.0)
    assert pr.iloc[9] == pytest.approx(1.0)


def test_percentile_rank_constant_series_strict_lt_gives_zero():
    """v0.3 / CO-3: explicit tie semantics. strict_lt: ties → 0."""
    s = pd.Series([5.0] * 10)
    pr = compute_rolling_percentile_rank(s, window=5, tie_rule="strict_lt")
    assert pr.iloc[:4].isna().all()
    assert pr.iloc[4:].eq(0.0).all()


def test_percentile_rank_constant_series_le_gives_one():
    s = pd.Series([5.0] * 10)
    pr = compute_rolling_percentile_rank(s, window=5, tie_rule="le")
    assert pr.iloc[:4].isna().all()
    assert pr.iloc[4:].eq(1.0).all()


def test_percentile_rank_unknown_tie_rule_raises():
    s = pd.Series(range(10), dtype=float)
    with pytest.raises(ValueError, match="tie_rule"):
        compute_rolling_percentile_rank(s, window=5, tie_rule="bogus")
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append:

```python
def compute_rolling_percentile_rank(
    series: pd.Series, *, window: int, tie_rule: str = "strict_lt"
) -> pd.Series:
    """Percentile rank of current day vs prior (window-1) days.

    tie_rule (v0.3 / CO-3 — must be set explicitly to choose semantics):
        "strict_lt"     — (cohort < today).sum() / (window-1); ties → 0
        "le"            — (cohort <= today).sum() / (window-1); ties → 1
        "average_rank"  — mean of the above; ties → ~0.5
    """
    if window < 2:
        raise ValueError("window must be ≥ 2")
    if tie_rule not in ("strict_lt", "le", "average_rank"):
        raise ValueError(
            f"tie_rule must be 'strict_lt'/'le'/'average_rank', got {tie_rule!r}"
        )

    def _rank(arr: np.ndarray) -> float:
        today = arr[-1]
        cohort = arr[:-1]
        if np.isnan(today) or np.isnan(cohort).any():
            return np.nan
        n = float(len(cohort))
        if tie_rule == "strict_lt":
            return float((cohort < today).sum()) / n
        if tie_rule == "le":
            return float((cohort <= today).sum()) / n
        return (float((cohort < today).sum()) + float((cohort <= today).sum())) / (2 * n)

    return series.rolling(window).apply(_rank, raw=True)
```

- [ ] **Step 4: Run, expect pass**

### Task 3.3: Instantaneous classifier (excluding BOUNCE) — widened NORMAL band

- [ ] **Step 1: Write the failing tests**

Append:

```python
from uw_scan.cards.regime_classification_labels import classify_level1_instantaneous


THRESHOLDS_DEFAULT = {
    "P_SUPP": 0.30, "P_RO": 0.80, "P_PANIC": 0.95,
    "DD_EDR": 0.07,
    "NORMAL_LOW": 0.30, "NORMAL_HIGH": 0.80,  # v0.3 / CO-4 widened
    "NORMAL_DD": 0.05,
}


def _row(vix_pct, vvix_pct, rv_pct, credit_pct, dd):
    return dict(vix_pct=vix_pct, vvix_pct=vvix_pct, rv_pct=rv_pct,
                credit_pct=credit_pct, dd=dd)


def test_classify_normal_when_everything_mid_range():
    assert classify_level1_instantaneous(_row(0.5, 0.5, 0.5, 0.5, -0.02),
                                         thresholds=THRESHOLDS_DEFAULT) == "NORMAL"


def test_classify_suppressed_requires_all_below_p_supp():
    assert classify_level1_instantaneous(_row(0.25, 0.20, 0.20, 0.15, -0.01),
                                         thresholds=THRESHOLDS_DEFAULT) == "SUPPRESSED"


def test_classify_edr_when_drawdown_exceeds_threshold():
    assert classify_level1_instantaneous(_row(0.6, 0.5, 0.5, 0.4, -0.10),
                                         thresholds=THRESHOLDS_DEFAULT) == "EDR"


def test_classify_risk_off_via_credit_path():
    assert classify_level1_instantaneous(_row(0.5, 0.5, 0.5, 0.85, -0.02),
                                         thresholds=THRESHOLDS_DEFAULT) == "RISK_OFF"


def test_classify_risk_off_via_vol_path():
    assert classify_level1_instantaneous(_row(0.85, 0.82, 0.5, 0.3, -0.02),
                                         thresholds=THRESHOLDS_DEFAULT) == "RISK_OFF"


def test_classify_panic_requires_vix_and_rv_extreme():
    assert classify_level1_instantaneous(_row(0.97, 0.85, 0.96, 0.85, -0.20),
                                         thresholds=THRESHOLDS_DEFAULT) == "PANIC"


def test_class_precedence_panic_above_risk_off():
    assert classify_level1_instantaneous(_row(0.98, 0.95, 0.99, 0.90, -0.05),
                                         thresholds=THRESHOLDS_DEFAULT) == "PANIC"


def test_normal_band_widened_v0_3():
    """v0.3 / CO-4: NORMAL band [0.30, 0.80] eliminates the silent fall-through
    gap that existed in v0.2 with [0.25, 0.75]."""
    # Row with vix_pct=0.32 in mid-range — now squarely NORMAL.
    row = _row(0.32, 0.50, 0.50, 0.50, -0.02)
    assert classify_level1_instantaneous(row, thresholds=THRESHOLDS_DEFAULT) == "NORMAL"
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append:

```python
def classify_level1_instantaneous(row: dict, *, thresholds: dict) -> str:
    """Single-day classification — no BOUNCE/transition history.

    Precedence: PANIC > RISK_OFF > EDR > SUPPRESSED > NORMAL.
    BOUNCE is layered on by apply_bounce_state_machine using spec §6.5 rules.
    """
    vix_pct = row["vix_pct"]; vvix_pct = row["vvix_pct"]; rv_pct = row["rv_pct"]
    credit_pct = row["credit_pct"]; dd = row["dd"]
    p_supp = thresholds["P_SUPP"]; p_ro = thresholds["P_RO"]; p_panic = thresholds["P_PANIC"]
    dd_edr = thresholds["DD_EDR"]; n_low = thresholds["NORMAL_LOW"]; n_high = thresholds["NORMAL_HIGH"]
    n_dd = thresholds["NORMAL_DD"]

    if vix_pct >= p_panic and rv_pct >= p_panic:
        return "PANIC"
    if credit_pct >= p_ro or (vix_pct >= p_ro and vvix_pct >= p_ro):
        return "RISK_OFF"
    if -dd >= dd_edr:
        return "EDR"
    if vix_pct < p_supp and rv_pct < p_supp and credit_pct < p_supp:
        return "SUPPRESSED"
    if (n_low <= vix_pct <= n_high and n_low <= vvix_pct <= n_high
        and n_low <= rv_pct <= n_high and n_low <= credit_pct <= n_high
        and -dd < n_dd):
        return "NORMAL"
    # Fall-through: with widened NORMAL band (v0.3 / CO-4), this branch
    # should be very rare in production data — but keep it as NORMAL for
    # any residual edge case.
    return "NORMAL"
```

- [ ] **Step 4: Run, expect pass**

### Task 3.4: BOUNCE state machine

- [ ] **Step 1: Write the failing tests**

Append:

```python
from uw_scan.cards.regime_classification_labels import apply_bounce_state_machine


def test_bounce_opens_after_risk_off_ends():
    instant = ["NORMAL", "RISK_OFF", "RISK_OFF", "NORMAL", "NORMAL", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=3)
    assert out == ["NORMAL", "RISK_OFF", "RISK_OFF", "BOUNCE", "BOUNCE", "BOUNCE"]


def test_bounce_terminates_on_reactivation():
    instant = ["RISK_OFF", "NORMAL", "NORMAL", "RISK_OFF", "NORMAL", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=10)
    assert out == ["RISK_OFF", "BOUNCE", "BOUNCE", "RISK_OFF", "BOUNCE", "BOUNCE"]


def test_bounce_precedence_above_edr():
    instant = ["RISK_OFF", "EDR", "EDR", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=2)
    assert out == ["RISK_OFF", "BOUNCE", "BOUNCE", "NORMAL"]


def test_bounce_window_one_day():
    instant = ["PANIC", "NORMAL", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=1)
    assert out == ["PANIC", "BOUNCE", "NORMAL"]
```

- [ ] **Step 2: Run, expect 4 fails**

- [ ] **Step 3: Implement**

Append:

```python
def apply_bounce_state_machine(
    instant_labels: list[str], *, n_bounce: int
) -> list[str]:
    """Layer BOUNCE on top of instantaneous labels per spec §6.5.

    Trigger: first non-stress day after PANIC or RISK_OFF.
    Duration: n_bounce trading days.
    Termination: PANIC/RISK_OFF reactivation closes window.
    Precedence: BOUNCE > EDR > SUPPRESSED > NORMAL during active window.
    """
    out: list[str] = []
    bounce_remaining = 0

    for i, label in enumerate(instant_labels):
        if label in ("PANIC", "RISK_OFF"):
            bounce_remaining = 0
            out.append(label)
            continue

        prior_was_stress = (i > 0 and instant_labels[i - 1] in ("PANIC", "RISK_OFF"))
        if prior_was_stress:
            bounce_remaining = n_bounce

        if bounce_remaining > 0:
            out.append("BOUNCE")
            bounce_remaining -= 1
        else:
            out.append(label)

    return out
```

- [ ] **Step 4: Run, expect 4 passes**

### Task 3.5: `derive_level1_frame` with raw NFCI snapshot (v0.3 / CL-3)

- [ ] **Step 1: Write the failing test**

Append:

```python
from uw_scan.cards.regime_classification_labels import derive_level1_frame


def test_derive_level1_frame_returns_components():
    history_pad = pd.date_range("2018-01-01", periods=260, freq="B")
    eval_dates = pd.date_range("2020-01-01", periods=30, freq="B")
    all_dates = history_pad.append(eval_dates)

    vix = pd.Series([15.0] * len(all_dates), index=all_dates)
    vvix = pd.Series([80.0] * len(all_dates), index=all_dates)
    spx = pd.Series([100.0] * len(all_dates), index=all_dates)
    credit = pd.Series([-1.0] * len(all_dates), index=all_dates)
    vix.loc["2020-01-15":"2020-01-17"] = 60.0
    vvix.loc["2020-01-15":"2020-01-17"] = 150.0

    thresholds = {
        "P_SUPP": 0.30, "P_RO": 0.80, "P_PANIC": 0.95,
        "DD_EDR": 0.07, "NORMAL_LOW": 0.30, "NORMAL_HIGH": 0.80,
        "NORMAL_DD": 0.05, "N_BOUNCE": 3,
        "rolling_window_days": 252, "realized_vol_window_days": 21,
        "percentile_tie_rule": "strict_lt",
    }
    frame = derive_level1_frame(
        vix=vix, vvix=vvix, spx=spx, credit_stress=credit, thresholds=thresholds,
    )
    # v0.3 frame columns: includes NFCI_value (raw input snapshot for replay)
    assert set(["truth_label", "instant_label", "vix_pct", "vvix_pct",
                "rv_pct", "credit_pct", "dd", "NFCI_value"]).issubset(frame.columns)
    eval_frame = frame.loc[eval_dates]
    assert "RISK_OFF" in eval_frame["truth_label"].values
    assert "BOUNCE" in eval_frame["truth_label"].values


def test_derive_level1_frame_persists_raw_nfci_value():
    """v0.3 / CL-3: raw NFCI value must be in the frame for replay determinism."""
    history_pad = pd.date_range("2018-01-01", periods=260, freq="B")
    vix = pd.Series([15.0] * len(history_pad), index=history_pad)
    vvix = pd.Series([80.0] * len(history_pad), index=history_pad)
    spx = pd.Series([100.0] * len(history_pad), index=history_pad)
    credit = pd.Series([-0.5] * len(history_pad), index=history_pad)
    credit.iloc[-1] = -0.3  # last day NFCI different

    thresholds = {
        "P_SUPP": 0.30, "P_RO": 0.80, "P_PANIC": 0.95, "DD_EDR": 0.07,
        "NORMAL_LOW": 0.30, "NORMAL_HIGH": 0.80, "NORMAL_DD": 0.05,
        "N_BOUNCE": 3, "rolling_window_days": 252,
        "realized_vol_window_days": 21, "percentile_tie_rule": "strict_lt",
    }
    frame = derive_level1_frame(
        vix=vix, vvix=vvix, spx=spx, credit_stress=credit, thresholds=thresholds,
    )
    assert frame["NFCI_value"].iloc[-1] == pytest.approx(-0.3)
    assert frame["NFCI_value"].iloc[-2] == pytest.approx(-0.5)
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append:

```python
def derive_level1_frame(
    *,
    vix: pd.Series,
    vvix: pd.Series,
    spx: pd.Series,
    credit_stress: pd.Series,
    thresholds: dict,
) -> pd.DataFrame:
    """Compose Level-1 labels + components + raw NFCI value (v0.3 / CL-3).

    Returns DataFrame indexed by trade_date with columns:
        truth_label   — final post-BOUNCE label
        instant_label — pre-BOUNCE instantaneous classification
        vix_pct, vvix_pct, rv_pct, credit_pct, dd — derived components
        NFCI_value    — raw NFCI input (for replay determinism — v0.3 / CL-3)
    """
    window = int(thresholds["rolling_window_days"])
    rv_window = int(thresholds["realized_vol_window_days"])
    tie_rule = thresholds.get("percentile_tie_rule", "strict_lt")

    vix_pct = compute_rolling_percentile_rank(vix, window=window, tie_rule=tie_rule)
    vvix_pct = compute_rolling_percentile_rank(vvix, window=window, tie_rule=tie_rule)
    realized = compute_realized_vol(spx, window=rv_window)
    rv_pct = compute_rolling_percentile_rank(realized, window=window, tie_rule=tie_rule)
    credit_pct = compute_rolling_percentile_rank(credit_stress, window=window, tie_rule=tie_rule)
    dd = compute_trailing_drawdown(spx, window=window)

    components = pd.DataFrame({
        "vix_pct": vix_pct, "vvix_pct": vvix_pct, "rv_pct": rv_pct,
        "credit_pct": credit_pct, "dd": dd,
        "NFCI_value": credit_stress,  # v0.3 / CL-3
    })

    instant: list[str] = []
    valid_mask: list[bool] = []
    for _, row in components.iterrows():
        check_row = row.drop("NFCI_value")  # NFCI_value is data, not signal
        if check_row.isna().any():
            instant.append("")
            valid_mask.append(False)
            continue
        instant.append(classify_level1_instantaneous(
            check_row.to_dict(), thresholds=thresholds,
        ))
        valid_mask.append(True)

    n_bounce = int(thresholds["N_BOUNCE"])
    with_bounce = apply_bounce_state_machine(instant, n_bounce=n_bounce)

    frame = components.copy()
    frame["instant_label"] = instant
    frame["truth_label"] = with_bounce
    mask = pd.Series(valid_mask, index=frame.index)
    frame.loc[~mask, "instant_label"] = pd.NA
    frame.loc[~mask, "truth_label"] = pd.NA
    return frame
```

- [ ] **Step 4: Run, expect pass**

```bash
uv run pytest tests/unit/cards/test_regime_classification_labels.py -v
```

### Task 3.6: Commit Phase 3

- [ ] **Step 1: Verify module size**

```bash
wc -l src/uw_scan/cards/regime_classification_labels.py
```

Expected: < 500 lines.

- [ ] **Step 2: Commit**

```bash
git add src/uw_scan/cards/regime_classification_labels.py tests/unit/cards/test_regime_classification_labels.py
git commit -m "feat(regime): Level-1 label derivation with v0.3 tribunal fixes

CO-3: explicit percentile_tie_rule parameter
CO-4: widened NORMAL band [0.30, 0.80] for exhaustive coverage
CL-3: derive_level1_frame includes raw NFCI value for replay determinism"
```

---

## Phase 4: Scoring (pure functions)

### Task 4.1: `build_confusion_matrix` aligns by index (v0.3 / CO-7)

**Files:**
- Create: `src/uw_scan/cards/regime_classification_scoring.py`
- Create: `tests/unit/cards/test_regime_classification_scoring.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/cards/test_regime_classification_scoring.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.regime_classification_scoring import (
    build_confusion_matrix, normalize_vcg_label,
)


CLASSES = ["NORMAL", "SUPPRESSED", "EDR", "RISK_OFF", "PANIC", "BOUNCE"]


def test_normalize_vcg_label_canonical_pass_through():
    for c in CLASSES:
        assert normalize_vcg_label(c) == c


def test_normalize_vcg_label_handles_common_variants():
    assert normalize_vcg_label("risk_off") == "RISK_OFF"
    assert normalize_vcg_label("normal") == "NORMAL"
    assert normalize_vcg_label("EDR ") == "EDR"
    assert normalize_vcg_label(" PANIC") == "PANIC"


def test_normalize_vcg_label_raises_on_unknown_with_remediation_hint():
    """v0.3 / CL-11: error must tell future maintainer where to extend the map."""
    with pytest.raises(ValueError, match="_VCG_LABEL_ALIASES"):
        normalize_vcg_label("RO_TIER_1")


def test_confusion_matrix_perfect_agreement_is_diagonal():
    truth = pd.Series(["NORMAL", "RISK_OFF", "EDR", "NORMAL"])
    pred = pd.Series(["NORMAL", "RISK_OFF", "EDR", "NORMAL"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)
    assert cm.loc["NORMAL", "NORMAL"] == 2
    assert cm.loc["RISK_OFF", "RISK_OFF"] == 1
    assert cm.loc["EDR", "EDR"] == 1


def test_confusion_matrix_raises_on_unknown_label():
    truth = pd.Series(["NORMAL", "RO_TIER_1"])
    pred = pd.Series(["NORMAL", "RISK_OFF"])
    with pytest.raises(ValueError, match="unknown"):
        build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)


def test_confusion_matrix_aligns_by_index_not_position():
    """v0.3 / CO-7: pure function MUST align by index, not by .values position."""
    truth = pd.Series(["NORMAL", "RISK_OFF", "EDR"],
                     index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]))
    pred = pd.Series(["EDR", "RISK_OFF", "NORMAL"],
                    index=pd.to_datetime(["2020-01-03", "2020-01-02", "2020-01-01"]))
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)
    # Correct alignment by index: all 3 diagonal entries.
    assert cm.loc["NORMAL", "NORMAL"] == 1
    assert cm.loc["RISK_OFF", "RISK_OFF"] == 1
    assert cm.loc["EDR", "EDR"] == 1
    assert cm.values.sum() == 3


def test_confusion_matrix_partial_overlap_drops_unaligned_dates():
    truth = pd.Series(["NORMAL", "RISK_OFF"],
                     index=pd.to_datetime(["2020-01-01", "2020-01-02"]))
    pred = pd.Series(["NORMAL", "EDR"],
                    index=pd.to_datetime(["2020-01-01", "2020-01-03"]))
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=CLASSES)
    # Only 2020-01-01 aligns.
    assert cm.values.sum() == 1
    assert cm.loc["NORMAL", "NORMAL"] == 1
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/cards/regime_classification_scoring.py
"""Scoring + verdict + failure-mode classification for VCG regime accuracy.

All functions pure (no DB). Strict label normalization — unknown labels raise
ValueError rather than silently being dropped (spec §12).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


_VCG_LABEL_ALIASES = {
    "NORMAL": "NORMAL", "normal": "NORMAL", "Normal": "NORMAL",
    "SUPPRESSED": "SUPPRESSED", "suppressed": "SUPPRESSED", "Suppressed": "SUPPRESSED",
    "EDR": "EDR", "edr": "EDR",
    "RISK_OFF": "RISK_OFF", "risk_off": "RISK_OFF", "RISKOFF": "RISK_OFF",
    "risk-off": "RISK_OFF", "RO": "RISK_OFF",
    "PANIC": "PANIC", "panic": "PANIC", "Panic": "PANIC",
    "BOUNCE": "BOUNCE", "bounce": "BOUNCE", "Bounce": "BOUNCE",
}


def normalize_vcg_label(raw: str) -> str:
    """Canonicalize a VCG label string. Raises on unknown (v0.3 / CL-11)."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        raise ValueError(f"VCG label is null/NaN: {raw!r}")
    s = str(raw).strip()
    if s in _VCG_LABEL_ALIASES:
        return _VCG_LABEL_ALIASES[s]
    raise ValueError(
        f"unknown VCG label: {raw!r}. "
        f"If VCG emits new labels, extend _VCG_LABEL_ALIASES in "
        f"src/uw_scan/cards/regime_classification_scoring.py"
    )


def build_confusion_matrix(
    *, truth: pd.Series, pred: pd.Series, classes: list[str]
) -> pd.DataFrame:
    """Confusion matrix: rows = truth, cols = pred.

    v0.3 / CO-7: aligns by INDEX (pd.concat axis=1), not by .values position.
    Raises on unknown labels (no silent drops).
    """
    df = pd.concat([
        truth.rename("truth"), pred.rename("pred"),
    ], axis=1).dropna()
    classes_set = set(classes)
    unknown_truth = set(df["truth"].unique()) - classes_set
    unknown_pred = set(df["pred"].unique()) - classes_set
    if unknown_truth or unknown_pred:
        raise ValueError(
            f"build_confusion_matrix: unknown labels — "
            f"truth={sorted(unknown_truth)} pred={sorted(unknown_pred)}"
        )
    cm = pd.DataFrame(0, index=classes, columns=classes, dtype=int)
    for _, row in df.iterrows():
        cm.loc[row["truth"], row["pred"]] += 1
    return cm
```

- [ ] **Step 4: Run, expect pass**

### Task 4.2: Per-class P/R/F1 with F1=0 semantics on truth>0+pred=0

- [ ] **Step 1: Write the failing tests**

Append:

```python
from uw_scan.cards.regime_classification_scoring import per_class_prf


def test_per_class_prf_simple_case():
    truth = pd.Series(["A", "A", "B", "B", "A"])
    pred  = pd.Series(["A", "B", "B", "B", "A"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    out = per_class_prf(cm)
    # Class A: tp=2, fp=0, fn=1 → P=1.0, R=2/3, F1=0.8
    assert out["A"]["precision"] == pytest.approx(1.0)
    assert out["A"]["recall"] == pytest.approx(2/3)
    assert out["A"]["f1"] == pytest.approx(0.8, abs=1e-6)


def test_per_class_prf_f1_zero_when_truth_exists_but_pred_empty():
    """Class with n_truth > 0 but n_pred = 0 must yield F1 = 0, NOT NaN."""
    truth = pd.Series(["A", "A", "B", "B"])
    pred  = pd.Series(["A", "A", "A", "A"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    out = per_class_prf(cm)
    assert out["B"]["n_truth"] == 2
    assert out["B"]["n_pred"] == 0
    assert out["B"]["precision"] == pytest.approx(0.0)
    assert out["B"]["recall"] == pytest.approx(0.0)
    assert out["B"]["f1"] == pytest.approx(0.0)


def test_per_class_prf_nan_only_when_truth_is_zero():
    truth = pd.Series(["A", "B"])
    pred  = pd.Series(["A", "B"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B", "C"])
    out = per_class_prf(cm)
    assert np.isnan(out["C"]["f1"])
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append:

```python
def per_class_prf(cm: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-class precision, recall, F1 from a confusion matrix.

    Semantics:
        n_truth == 0          → F1 = NaN (class fundamentally absent)
        n_truth > 0, n_pred=0 → F1 = 0.0 (real miss, not undefined)
        otherwise             → standard P/R/F1
    """
    out: dict[str, dict[str, float]] = {}
    for c in cm.index:
        tp = float(cm.loc[c, c])
        fp = float(cm.loc[:, c].sum() - tp)
        fn = float(cm.loc[c, :].sum() - tp)
        n_truth = tp + fn
        n_pred = tp + fp

        if n_truth == 0:
            precision = float("nan"); recall = float("nan"); f1 = float("nan")
        elif n_pred == 0:
            precision = 0.0; recall = 0.0; f1 = 0.0
        else:
            precision = tp / n_pred
            recall = tp / n_truth
            f1 = (
                2 * precision * recall / (precision + recall)
                if (precision + recall) > 0 else 0.0
            )

        out[str(c)] = {
            "precision": precision, "recall": recall, "f1": f1,
            "n_truth": int(n_truth), "n_pred": int(n_pred),
        }
    return out
```

- [ ] **Step 4: Run, expect pass**

### Task 4.3: Macro-F1 / Weighted-F1 / Cohen's κ

- [ ] **Step 1: Write the failing tests**

Append:

```python
from uw_scan.cards.regime_classification_scoring import (
    macro_f1_over_eligible, weighted_f1_over_eligible, cohens_kappa,
)


def test_macro_f1_skips_inconclusive_classes():
    per_class = {
        "A": {"f1": 0.6, "n_truth": 100, "n_pred": 80, "precision": 0.75, "recall": 0.6},
        "B": {"f1": 0.8, "n_truth": 50,  "n_pred": 40, "precision": 1.0, "recall": 0.8},
        "C": {"f1": float("nan"), "n_truth": 5, "n_pred": 0, "precision": float("nan"), "recall": float("nan")},
    }
    result = macro_f1_over_eligible(per_class, n_min_class_days=30)
    assert result["macro_f1"] == pytest.approx(0.7)
    assert sorted(result["eligible_classes"]) == ["A", "B"]
    assert result["ineligible_classes"] == ["C"]


def test_weighted_f1_requires_explicit_eligible_classes():
    """v0.3 / patch §10: caller passes eligible_classes; do not let it guess."""
    per_class = {
        "A": {"f1": 0.6, "n_truth": 100, "n_pred": 80, "precision": 0.75, "recall": 0.6},
        "B": {"f1": 0.8, "n_truth": 50, "n_pred": 40, "precision": 1.0, "recall": 0.8},
        "C": {"f1": 0.0, "n_truth": 5, "n_pred": 0, "precision": 0.0, "recall": 0.0},
    }
    wf1 = weighted_f1_over_eligible(per_class, eligible_classes=["A", "B"])
    # (0.6 * 100 + 0.8 * 50) / 150 = 100/150 = 0.6667
    assert wf1 == pytest.approx(100/150)


def test_cohens_kappa_perfect_agreement_is_one():
    truth = pd.Series(["A", "A", "B", "B"])
    pred  = pd.Series(["A", "A", "B", "B"])
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    assert cohens_kappa(cm) == pytest.approx(1.0)


def test_cohens_kappa_random_chance_is_zero():
    truth = pd.Series(["A"] * 100 + ["B"] * 100)
    pred = pd.Series(["A"] * 50 + ["B"] * 50 + ["A"] * 50 + ["B"] * 50)
    cm = build_confusion_matrix(truth=truth, pred=pred, classes=["A", "B"])
    assert abs(cohens_kappa(cm)) < 0.01
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append:

```python
def macro_f1_over_eligible(
    per_class: dict[str, dict[str, float]], *, n_min_class_days: int
) -> dict:
    """Macro-F1 across classes with n_truth ≥ n_min_class_days and non-NaN F1."""
    eligible: list[str] = []
    ineligible: list[str] = []
    for c, m in per_class.items():
        if m["n_truth"] >= n_min_class_days and not np.isnan(m["f1"]):
            eligible.append(c)
        else:
            ineligible.append(c)
    if not eligible:
        return {"macro_f1": float("nan"), "eligible_classes": [], "ineligible_classes": ineligible}
    macro = float(np.mean([per_class[c]["f1"] for c in eligible]))
    return {"macro_f1": macro, "eligible_classes": eligible, "ineligible_classes": ineligible}


def weighted_f1_over_eligible(
    per_class: dict[str, dict[str, float]], *, eligible_classes: list[str]
) -> float:
    """F1 weighted by truth prevalence — over explicit class set (no guessing)."""
    total_n = sum(per_class[c]["n_truth"] for c in eligible_classes)
    if total_n == 0:
        return float("nan")
    weighted = sum(
        per_class[c]["f1"] * per_class[c]["n_truth"]
        for c in eligible_classes
        if not np.isnan(per_class[c]["f1"])
    )
    return float(weighted / total_n)


def cohens_kappa(cm: pd.DataFrame) -> float:
    """Cohen's κ — chance-adjusted multi-class agreement."""
    n = float(cm.values.sum())
    if n == 0:
        return float("nan")
    p_o = float(np.diag(cm.values).sum()) / n
    row_marg = cm.sum(axis=1).values / n
    col_marg = cm.sum(axis=0).values / n
    p_e = float(np.sum(row_marg * col_marg))
    if abs(1.0 - p_e) < 1e-12:
        return float("nan")
    return (p_o - p_e) / (1.0 - p_e)
```

- [ ] **Step 4: Run, expect pass**

### Task 4.4: JSON sanitizer (v0.3 / CO-2)

- [ ] **Step 1: Write the failing test**

Append:

```python
from uw_scan.cards.regime_classification_scoring import sanitize_for_json


def test_sanitize_for_json_replaces_nan_with_none():
    """v0.3 / CO-2: PostgreSQL JSONB doesn't accept NaN/inf tokens."""
    payload = {
        "f1": float("nan"),
        "precision": float("inf"),
        "nested": {"recall": -float("inf"), "ok": 0.5},
        "list": [float("nan"), 1.0, float("nan")],
        "string": "PANIC",
        "int": 42,
    }
    cleaned = sanitize_for_json(payload)
    assert cleaned["f1"] is None
    assert cleaned["precision"] is None
    assert cleaned["nested"]["recall"] is None
    assert cleaned["nested"]["ok"] == 0.5
    assert cleaned["list"] == [None, 1.0, None]
    assert cleaned["string"] == "PANIC"
    assert cleaned["int"] == 42
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement**

Append:

```python
def sanitize_for_json(value):
    """Recursively replace NaN / ±inf with None for JSONB compatibility (CO-2)."""
    if isinstance(value, float):
        if np.isnan(value) or np.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_for_json(v) for v in value]
    return value
```

- [ ] **Step 4: Run, expect pass**

### Task 4.5: Commit Phase 4 (intermediate)

```bash
git add src/uw_scan/cards/regime_classification_scoring.py tests/unit/cards/test_regime_classification_scoring.py
git commit -m "feat(regime): scoring with v0.3 tribunal fixes

CO-7: build_confusion_matrix aligns by index (pd.concat axis=1)
CO-2: sanitize_for_json converts NaN/inf to None for JSONB writes
CL-11: normalize_vcg_label error includes remediation hint

Verdict + failure-mode classifiers follow in Phase 5."
```

---

## Phase 5: Verdict + failure-mode (v0.3 updates)

### Task 5.1: Three-state verdict (K=4 all-core-required model)

- [ ] **Step 1: Write the failing tests**

Append to `test_regime_classification_scoring.py`:

```python
from uw_scan.cards.regime_classification_scoring import compute_verdict


CORE = ["NORMAL", "SUPPRESSED", "EDR", "RISK_OFF"]


def _pc(f1, n_truth, n_pred=None):
    return {
        "f1": f1, "n_truth": n_truth, "n_pred": n_pred if n_pred is not None else n_truth,
        "precision": float("nan"), "recall": float("nan"),
    }


def test_verdict_inconclusive_when_any_core_class_under_min():
    per_class = {
        "NORMAL": _pc(0.7, 500), "SUPPRESSED": _pc(0.6, 100),
        "EDR": _pc(0.5, 20),   # < 30 → inconclusive
        "RISK_OFF": _pc(0.5, 50),
        "PANIC": _pc(0.0, 5), "BOUNCE": _pc(0.0, 5),
    }
    v = compute_verdict(per_class, core_classes=CORE,
                        n_min_class_days=30, k_min_core_eligible=4,
                        macro_f1_pass=0.50)
    assert v["overall"] == "INCONCLUSIVE"
    assert "EDR" in v["inconclusive_core_classes"]


def test_verdict_pass_when_all_core_eligible_and_macro_above_threshold():
    per_class = {
        "NORMAL": _pc(0.7, 500), "SUPPRESSED": _pc(0.6, 100),
        "EDR": _pc(0.5, 50), "RISK_OFF": _pc(0.5, 50),
        "PANIC": _pc(float("nan"), 5), "BOUNCE": _pc(float("nan"), 5),
    }
    v = compute_verdict(per_class, core_classes=CORE,
                        n_min_class_days=30, k_min_core_eligible=4,
                        macro_f1_pass=0.50)
    assert v["overall"] == "PASS"


def test_verdict_fail_when_macro_below_threshold():
    per_class = {
        "NORMAL": _pc(0.4, 500), "SUPPRESSED": _pc(0.3, 100),
        "EDR": _pc(0.3, 50), "RISK_OFF": _pc(0.3, 50),
        "PANIC": _pc(float("nan"), 5), "BOUNCE": _pc(float("nan"), 5),
    }
    v = compute_verdict(per_class, core_classes=CORE,
                        n_min_class_days=30, k_min_core_eligible=4,
                        macro_f1_pass=0.50)
    assert v["overall"] == "FAIL"


def test_rare_class_under_power_does_not_invalidate_headline():
    per_class = {
        "NORMAL": _pc(0.7, 500), "SUPPRESSED": _pc(0.6, 100),
        "EDR": _pc(0.5, 50), "RISK_OFF": _pc(0.5, 50),
        "PANIC": _pc(float("nan"), 5), "BOUNCE": _pc(float("nan"), 5),
    }
    v = compute_verdict(per_class, core_classes=CORE,
                        n_min_class_days=30, k_min_core_eligible=4,
                        macro_f1_pass=0.50)
    assert v["overall"] == "PASS"
    assert "PANIC" in v["rare_inconclusive"]
    assert "BOUNCE" in v["rare_inconclusive"]
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append to `regime_classification_scoring.py`:

```python
def compute_verdict(
    per_class: dict[str, dict[str, float]],
    *,
    core_classes: list[str],
    n_min_class_days: int,
    k_min_core_eligible: int,
    macro_f1_pass: float,
) -> dict:
    """Three-state verdict per spec §8 (eligible/core-class model)."""
    inconclusive_core: list[str] = []
    eligible_core: list[str] = []
    rare_inconclusive: list[str] = []

    for c, m in per_class.items():
        is_eligible = m["n_truth"] >= n_min_class_days and not np.isnan(m["f1"])
        if c in core_classes:
            if is_eligible:
                eligible_core.append(c)
            else:
                inconclusive_core.append(c)
        else:
            if not is_eligible:
                rare_inconclusive.append(c)

    if inconclusive_core or len(eligible_core) < k_min_core_eligible:
        return {
            "overall": "INCONCLUSIVE",
            "reason": ("core_class_under_min" if inconclusive_core
                       else "fewer_than_k_core_eligible"),
            "inconclusive_core_classes": inconclusive_core,
            "eligible_core_classes": eligible_core,
            "rare_inconclusive": rare_inconclusive,
            "macro_f1": None,
        }

    all_eligible = list(eligible_core)
    for c in per_class:
        if c not in core_classes and c not in rare_inconclusive:
            all_eligible.append(c)
    macro = float(np.mean([per_class[c]["f1"] for c in all_eligible]))

    return {
        "overall": "PASS" if macro >= macro_f1_pass else "FAIL",
        "reason": None,
        "inconclusive_core_classes": inconclusive_core,
        "eligible_core_classes": eligible_core,
        "rare_inconclusive": rare_inconclusive,
        "macro_f1": macro,
        "all_eligible_classes": all_eligible,
    }
```

- [ ] **Step 4: Run, expect pass**

### Task 5.2: Failure-mode classifier with `underpowered_test` + guarded `label_mismatch`

- [ ] **Step 1: Write the failing tests**

Append:

```python
from uw_scan.cards.regime_classification_scoring import classify_failure_mode


FAILURE_THRESHOLDS = {
    "PANIC_SUPPRESSION_RATIO": 0.2, "SPARSITY_RATIO": 0.25,
    "MISMATCH_CONCENTRATION": 0.6, "BENCH_RANGE": 0.15,
    "N_MIN_CLASS_DAYS": 30, "MACRO_F1_PASS": 0.5,
}


def test_failure_mode_adequate_v1_when_pass():
    verdict = {"overall": "PASS", "macro_f1": 0.7}
    per_class = {
        "PANIC": _pc(0.5, 50, n_pred=45),
        "NORMAL": _pc(0.7, 500, n_pred=500),
        "EDR": _pc(0.6, 100, n_pred=90),
        "RISK_OFF": _pc(0.6, 100, n_pred=95),
    }
    out = classify_failure_mode(verdict, per_class, cm=pd.DataFrame(),
                                thresholds=FAILURE_THRESHOLDS,
                                per_universe_macro_f1=None)
    assert out["primary"] == "adequate_v1"


def test_failure_mode_panic_suppression():
    verdict = {"overall": "FAIL", "macro_f1": 0.3}
    per_class = {
        "PANIC": _pc(0.0, 50, n_pred=2),
        "NORMAL": _pc(0.4, 500, n_pred=500),
        "EDR": _pc(0.3, 100, n_pred=90),
        "RISK_OFF": _pc(0.3, 100, n_pred=95),
    }
    out = classify_failure_mode(verdict, per_class, cm=pd.DataFrame(),
                                thresholds=FAILURE_THRESHOLDS,
                                per_universe_macro_f1=None)
    assert out["primary"] == "panic_suppression"


def test_failure_mode_underpowered_test_for_inconclusive():
    """v0.3 / CL-2: INCONCLUSIVE must emit a meaningful primary mode."""
    verdict = {"overall": "INCONCLUSIVE", "macro_f1": None,
               "reason": "core_class_under_min"}
    per_class = {
        "NORMAL": _pc(0.5, 500, n_pred=400),
        "SUPPRESSED": _pc(0.5, 100, n_pred=80),
        "EDR": _pc(float("nan"), 10),  # under N_MIN
        "RISK_OFF": _pc(0.5, 50, n_pred=45),
    }
    out = classify_failure_mode(verdict, per_class, cm=pd.DataFrame(),
                                thresholds=FAILURE_THRESHOLDS,
                                per_universe_macro_f1=None)
    assert out["primary"] == "underpowered_test"


def test_failure_mode_label_mismatch_not_triggered_on_empty_cm():
    """v0.3 / CO-8: label_mismatch must NOT trigger on empty cm."""
    verdict = {"overall": "FAIL", "macro_f1": 0.4}
    per_class = {
        "PANIC": _pc(0.5, 50, n_pred=45),
        "NORMAL": _pc(0.4, 500, n_pred=480),
        "EDR": _pc(0.4, 100, n_pred=95),
        "RISK_OFF": _pc(0.4, 100, n_pred=98),
    }
    out = classify_failure_mode(verdict, per_class, cm=pd.DataFrame(),
                                thresholds=FAILURE_THRESHOLDS,
                                per_universe_macro_f1=None)
    assert "label_mismatch" not in out["secondary_modes"]
    assert out["primary"] != "label_mismatch"


def test_failure_mode_benchmark_coverage_not_evaluable_when_no_universe_data():
    verdict = {"overall": "FAIL", "macro_f1": 0.4}
    per_class = {
        "PANIC": _pc(0.5, 50, n_pred=45),
        "NORMAL": _pc(0.4, 500, n_pred=480),
        "EDR": _pc(0.4, 100, n_pred=95),
        "RISK_OFF": _pc(0.4, 100, n_pred=98),
    }
    out = classify_failure_mode(verdict, per_class, cm=pd.DataFrame(),
                                thresholds=FAILURE_THRESHOLDS,
                                per_universe_macro_f1=None)
    assert "benchmark_coverage" in out["not_evaluable"]
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

Append:

```python
CORE_CLASSES = ("NORMAL", "SUPPRESSED", "EDR", "RISK_OFF")


def classify_failure_mode(
    verdict: dict, per_class: dict[str, dict[str, float]],
    *, cm: pd.DataFrame, thresholds: dict, per_universe_macro_f1: dict | None,
) -> dict:
    """v0.3 failure-mode classifier per spec §9.

    Modes (precedence order):
        panic_suppression > signal_sparsity > underpowered_test >
        label_mismatch > benchmark_coverage > adequate_v1

    v0.3 additions:
    - underpowered_test (CL-2): INCONCLUSIVE → meaningful mode
    - label_mismatch (CO-8): guarded against empty cm / zero disagreement
    - benchmark_coverage (CL-1): always not_evaluable until per-universe
      scoring lands in follow-up PR
    """
    triggered: list[str] = []
    not_evaluable: list[str] = []

    panic_suppression_ratio = thresholds["PANIC_SUPPRESSION_RATIO"]
    sparsity_ratio = thresholds["SPARSITY_RATIO"]
    bench_range = thresholds["BENCH_RANGE"]
    n_min = thresholds["N_MIN_CLASS_DAYS"]
    mismatch_conc = thresholds["MISMATCH_CONCENTRATION"]

    # panic_suppression
    panic = per_class.get("PANIC")
    if panic is not None and panic["n_truth"] >= n_min:
        if panic["n_pred"] < panic_suppression_ratio * panic["n_truth"]:
            triggered.append("panic_suppression")

    # signal_sparsity
    for c in CORE_CLASSES:
        m = per_class.get(c)
        if m is None or m["n_truth"] < n_min:
            continue
        if m["n_pred"] < sparsity_ratio * m["n_truth"]:
            triggered.append("signal_sparsity")
            break

    # underpowered_test — v0.3 / CL-2
    if verdict["overall"] == "INCONCLUSIVE":
        triggered.append("underpowered_test")

    # label_mismatch — v0.3 / CO-8: only on non-empty cm with disagreement
    if (
        verdict["overall"] == "FAIL"
        and "signal_sparsity" not in triggered
        and not cm.empty
    ):
        all_dense = all(
            per_class[c]["n_pred"] >= sparsity_ratio * per_class[c]["n_truth"]
            for c in CORE_CLASSES
            if per_class.get(c) and per_class[c]["n_truth"] >= n_min
        )
        if all_dense:
            off_diag: list[tuple[float, str, str]] = []
            for i in cm.index:
                for j in cm.columns:
                    if i != j:
                        off_diag.append((float(cm.loc[i, j]), str(i), str(j)))
            off_diag.sort(reverse=True)
            total = sum(v for v, _, _ in off_diag)
            if total > 0:
                top2 = sum(v for v, _, _ in off_diag[:2])
                if top2 / total >= mismatch_conc:
                    triggered.append("label_mismatch")

    # benchmark_coverage — v0.3 / CL-1: deferred; always not_evaluable
    if per_universe_macro_f1 is None:
        not_evaluable.append("benchmark_coverage")
    elif len(per_universe_macro_f1) >= 2:
        values = list(per_universe_macro_f1.values())
        if max(values) - min(values) > bench_range:
            triggered.append("benchmark_coverage")

    precedence = [
        "panic_suppression", "signal_sparsity",
        "underpowered_test", "label_mismatch", "benchmark_coverage",
    ]
    primary = next((m for m in precedence if m in triggered), None)
    if primary is None and verdict["overall"] == "PASS":
        primary = "adequate_v1"
    if primary is None:
        primary = "unknown"
    secondary = [m for m in triggered if m != primary]

    return {"primary": primary, "secondary_modes": secondary, "not_evaluable": not_evaluable}
```

- [ ] **Step 4: Run, expect pass**

### Task 5.3: Commit Phase 5

```bash
git add src/uw_scan/cards/regime_classification_scoring.py tests/unit/cards/test_regime_classification_scoring.py
git commit -m "feat(regime): verdict + failure-mode classifier with v0.3 fixes

CL-2: underpowered_test mode for INCONCLUSIVE verdict (covers spec §9)
CO-8: label_mismatch guarded against empty cm / zero disagreement
CL-1: benchmark_coverage explicitly not_evaluable; per-universe scoring
      deferred to follow-up PR"
```

---

## Phase 6: Repository module (atomic + race-aware)

### Task 6.1: `RegimeClassificationRepository` with `insert_complete_run` atomic API

**Files:**
- Create: `src/uw_scan/storage/regime_classification_repository.py`
- Create: `tests/unit/storage/test_regime_classification_repository.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/storage/test_regime_classification_repository.py
from __future__ import annotations

from datetime import date

import pytest

from uw_scan.storage.regime_classification_repository import (
    RegimeClassificationRepository, ClassificationRunAlreadyExists,
)


def test_insert_classification_run_uses_credit_proxy_sentinel(seeded_db_empty_cards):
    """classification runs: credit_proxy='CLASSIFICATION', composite_method='classification_accuracy'."""
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    run_id = rcr.insert_classification_run(
        vcg_source_run_id=42, composite_version="1",
        eval_start=date(2007, 1, 3), eval_end=date(2026, 5, 26),
        label_version=1, n_days=4545,
        summary={"placeholder": True}, note="smoke test",
    )
    assert run_id > 0
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT run_scope, composite_method, indicator, credit_proxy, window_days, params "
            f"FROM {repo._schema}.regime_backtest_runs WHERE id=%s", (run_id,),
        )
        row = cur.fetchone()
    assert row[0] == "research"
    assert row[1] == "classification_accuracy"
    assert row[2] == "vcg"
    assert row[3] == "CLASSIFICATION"
    assert row[4] == 1
    assert row[5]["label_version"] == 1
    assert row[5]["vcg_source_run_id"] == 42


def test_bulk_insert_daily_classifications_stores_full_components(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    run_id = rcr.insert_classification_run(
        vcg_source_run_id=42, composite_version="1",
        eval_start=date(2007, 1, 3), eval_end=date(2026, 5, 26),
        label_version=1, n_days=1, summary={}, note="smoke",
    )
    rcr.bulk_insert_daily_classifications(run_id, [
        {
            "trade_date": date(2020, 3, 23),
            "vcg_label": "RISK_OFF", "truth_label": "PANIC", "match": False,
            "label_components": {
                "vix_pct": 0.99, "vvix_pct": 0.98, "rv_pct": 0.97,
                "credit_pct": 0.94, "dd": -0.30, "NFCI_value": 0.85,
                "instant_label": "PANIC",
            },
            "label_version": 1,
        },
    ])
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT level, payload FROM {repo._schema}.regime_backtest_daily WHERE run_id=%s",
            (run_id,),
        )
        row = cur.fetchone()
    assert row[0] == "RISK_OFF"
    assert row[1]["truth_label"] == "PANIC"
    assert row[1]["label_components"]["NFCI_value"] == 0.85  # v0.3 / CL-3


def test_insert_complete_run_is_atomic(seeded_db_empty_cards):
    """v0.3 / CL-8: insert + bulk + mark in one transaction."""
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    run_id = rcr.insert_complete_run(
        vcg_source_run_id=42, composite_version="1",
        eval_start=date(2007, 1, 3), eval_end=date(2026, 5, 26),
        label_version=1, summary={"placeholder": True}, note="atomic test",
        daily_rows=[
            {"trade_date": date(2020, 3, 23), "vcg_label": "RISK_OFF",
             "truth_label": "PANIC", "match": False, "label_components": {},
             "label_version": 1},
        ],
    )
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT completed_at FROM {repo._schema}.regime_backtest_runs WHERE id=%s",
            (run_id,),
        )
        assert cur.fetchone()[0] is not None


def test_insert_complete_run_catches_unique_violation(seeded_db_empty_cards):
    """v0.3 / CR-2: migration 062's unique index → raises typed exception."""
    repo = seeded_db_empty_cards
    rcr = RegimeClassificationRepository(repo.conn, schema=repo._schema)
    args = dict(
        vcg_source_run_id=42, composite_version="1",
        eval_start=date(2007, 1, 3), eval_end=date(2026, 5, 26),
        label_version=1, summary={}, note="dup test",
        daily_rows=[
            {"trade_date": date(2020, 3, 23), "vcg_label": "NORMAL",
             "truth_label": "NORMAL", "match": True, "label_components": {},
             "label_version": 1},
        ],
    )
    run_id = rcr.insert_complete_run(**args)
    assert run_id > 0
    with pytest.raises(ClassificationRunAlreadyExists):
        rcr.insert_complete_run(**args)
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/storage/regime_classification_repository.py
"""Persistence for VCG regime-classification accuracy reports.

Composes RegimeBacktestRepository. Tags rows with:
    indicator='vcg', composite_method='classification_accuracy',
    credit_proxy='CLASSIFICATION', window_days=1 (placeholder),
    run_scope='research' (Hard Guarantee #2 default-deny gate).

All classification-specific per-day data goes in regime_backtest_daily.payload
JSONB. No new daily columns. Migration 062 unique index prevents concurrent
duplicate inserts (v0.3 / CR-2).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from psycopg import Connection
from psycopg.errors import UniqueViolation

from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


class ClassificationRunAlreadyExists(Exception):
    """Raised when migration 062's unique index rejects a duplicate insert."""


class RegimeClassificationRepository:
    INDICATOR = "vcg"
    COMPOSITE_METHOD = "classification_accuracy"
    RUN_SCOPE = "research"
    CREDIT_PROXY_SENTINEL = "CLASSIFICATION"
    WINDOW_DAYS_PLACEHOLDER = 1

    def __init__(self, conn: Connection, *, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        self._inner = RegimeBacktestRepository(conn, schema=schema)

    def insert_classification_run(
        self, *,
        vcg_source_run_id: int, composite_version: str,
        eval_start: date, eval_end: date,
        label_version: int, n_days: int,
        summary: dict[str, Any], note: str = "",
    ) -> int:
        return self._inner.insert_run(
            indicator=self.INDICATOR,
            composite_version=composite_version,
            start_date=eval_start, end_date=eval_end,
            window_days=self.WINDOW_DAYS_PLACEHOLDER,
            n_days=n_days,
            params={
                "vcg_source_run_id": vcg_source_run_id,
                "label_version": label_version,
                "window_days_semantics": "not_applicable_for_classification",
            },
            summary=summary,
            note=note or f"classification baseline label_version={label_version}",
            run_scope=self.RUN_SCOPE,
            composite_method=self.COMPOSITE_METHOD,
            credit_proxy=self.CREDIT_PROXY_SENTINEL,
        )

    def bulk_insert_daily_classifications(
        self, run_id: int, rows: list[dict[str, Any]]
    ) -> None:
        prepared = [
            {
                "trade_date": r["trade_date"],
                "score": float(r.get("score", 0.0)),
                "level": r.get("vcg_label"),
                "payload": {
                    "vcg_label": r["vcg_label"],
                    "truth_label": r["truth_label"],
                    "match": bool(r["match"]),
                    "label_components": r.get("label_components", {}),
                    "label_version": r["label_version"],
                },
            }
            for r in rows
        ]
        self._inner.bulk_insert_daily(run_id, prepared)

    def mark_run_completed(self, run_id: int) -> None:
        self._inner.mark_run_completed(run_id)

    def update_run_summary(self, run_id: int, summary: dict[str, Any]) -> None:
        """Update summary mid-transaction (used by persist_and_render to embed report_md)."""
        from psycopg.types.json import Jsonb
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE {self._schema}.regime_backtest_runs SET summary = %s WHERE id = %s",
                (Jsonb(summary), run_id),
            )

    def insert_complete_run(
        self, *,
        vcg_source_run_id: int, composite_version: str,
        eval_start: date, eval_end: date,
        label_version: int, summary: dict[str, Any], note: str = "",
        daily_rows: list[dict[str, Any]],
    ) -> int:
        """v0.3 / CL-8: atomic insert_run → bulk_insert → mark_completed.

        v0.3 / CR-2: catches UniqueViolation from migration 062's partial index;
        raises typed ClassificationRunAlreadyExists with replay hint.
        """
        n_days = len(daily_rows)
        try:
            with self._conn.transaction():
                run_id = self.insert_classification_run(
                    vcg_source_run_id=vcg_source_run_id,
                    composite_version=composite_version,
                    eval_start=eval_start, eval_end=eval_end,
                    label_version=label_version, n_days=n_days,
                    summary=summary, note=note,
                )
                self.bulk_insert_daily_classifications(run_id, daily_rows)
                self.mark_run_completed(run_id)
            return run_id
        except UniqueViolation as exc:
            raise ClassificationRunAlreadyExists(
                f"Run for (vcg_source_run_id={vcg_source_run_id}, "
                f"label_version={label_version}) already completed; "
                f"use --render-run-id to replay"
            ) from exc

    def find_completed_classification_run(
        self, *, vcg_source_run_id: int, label_version: int
    ) -> int | None:
        sql = f"""
            SELECT id FROM {self._schema}.regime_backtest_runs
            WHERE indicator = %s
              AND composite_method = %s
              AND run_scope = %s
              AND completed_at IS NOT NULL
              AND archived_at IS NULL
              AND (params->>'vcg_source_run_id')::int = %s
              AND (params->>'label_version')::int = %s
            ORDER BY id DESC LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (
                self.INDICATOR, self.COMPOSITE_METHOD, self.RUN_SCOPE,
                vcg_source_run_id, label_version,
            ))
            row = cur.fetchone()
        return int(row[0]) if row else None

    def load_run_for_render(self, run_id: int) -> dict:
        """Reload everything needed for replay (v0.3 / CR-1)."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT params, summary, start_date, end_date, n_days "
                f"FROM {self._schema}.regime_backtest_runs WHERE id=%s", (run_id,),
            )
            params, summary, start_date, end_date, n_days = cur.fetchone()
            cur.execute(
                f"SELECT trade_date, level, payload "
                f"FROM {self._schema}.regime_backtest_daily WHERE run_id=%s ORDER BY trade_date",
                (run_id,),
            )
            daily = cur.fetchall()
        return {
            "params": params, "summary": summary,
            "start_date": start_date, "end_date": end_date, "n_days": n_days,
            "daily": daily,
        }
```

- [ ] **Step 4: Run, expect pass**

### Task 6.2: Re-export shim

- [ ] **Step 1: Add re-export to `src/uw_scan/storage/repository.py`**

Locate the top-level re-exports section and add:

```python
from uw_scan.storage.regime_classification_repository import (  # noqa: F401
    RegimeClassificationRepository, ClassificationRunAlreadyExists,
)
```

- [ ] **Step 2: Verify**

```bash
uv run python -c "from uw_scan.storage.repository import RegimeClassificationRepository, ClassificationRunAlreadyExists; print('ok')"
```

### Task 6.3: Commit Phase 6

```bash
git add src/uw_scan/storage/regime_classification_repository.py src/uw_scan/storage/repository.py tests/unit/storage/test_regime_classification_repository.py
git commit -m "feat(regime): repository with atomic + race-aware classification

CL-8: insert_complete_run wraps insert+bulk+mark in one transaction
CR-2: catches UniqueViolation from migration 062 → typed exception
Tags: credit_proxy='CLASSIFICATION', composite_method='classification_accuracy',
window_days=1 placeholder, label_version in params (clarification §2)"
```

---

## Phase 7: Report renderer (deterministic + vintages section)

### Task 7.1: Renderer with construct-validity + vintages

**Files:**
- Create: `src/uw_scan/reports/regime_classification_report.py`
- Create: `tests/unit/reports/test_regime_classification_report.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/reports/test_regime_classification_report.py
from __future__ import annotations

import pandas as pd

from uw_scan.reports.regime_classification_report import render_report


def _basic_args(**overrides):
    args = dict(
        run_id=42, label_version=1, eval_start="2007-01-03", eval_end="2026-05-26",
        n_days=4545,
        verdict={"overall": "PASS", "macro_f1": 0.6, "eligible_core_classes": [],
                 "inconclusive_core_classes": [], "rare_inconclusive": [], "reason": None},
        failure_mode={"primary": "adequate_v1", "secondary_modes": [], "not_evaluable": []},
        per_class={}, cm_overall=pd.DataFrame(), cm_by_period={},
        weighted_f1=0.65, kappa=0.50, named_crisis_overlay=[],
        vcg_source={"run_id": 6, "composite_version": "1", "credit_proxy": "HYG"},
        data_vintages=None,
    )
    args.update(overrides)
    return args


def test_report_contains_construct_validity_paragraph():
    report = render_report(**_basic_args())
    expected = (
        "This classification score measures descriptive agreement with an "
        "externally defined market-state taxonomy. It is not an alpha test"
    )
    assert expected in report


def test_report_renders_data_vintages_section_when_provided():
    """v0.3 / CL-6: post-hoc components disclosed via Data vintages."""
    report = render_report(**_basic_args(data_vintages=[
        {"component": "NFCI", "vintage": "as_of latest",
         "lag": "3-5 days release lag",
         "interpretation": "post-hoc; non-tradable signal"},
    ]))
    assert "Data vintages" in report
    assert "NFCI" in report
    assert "non-tradable signal" in report


def test_report_deterministic_same_inputs_same_bytes():
    args = _basic_args()
    assert render_report(**args) == render_report(**args)


def test_report_no_wall_clock_timestamp_in_body():
    report = render_report(**_basic_args())
    assert "Generated at" not in report
    assert "Run timestamp" not in report
```

- [ ] **Step 2: Run, expect fails**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/reports/regime_classification_report.py
"""Deterministic Markdown renderer for VCG regime-classification reports.

Same inputs → byte-identical output. No wall-clock timestamps in body.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

CONSTRUCT_VALIDITY = (
    "This classification score measures descriptive agreement with an "
    "externally defined market-state taxonomy. It is not an alpha test, a "
    "return-prediction test, or a trading-signal validation. Because VCG and "
    "the Level-1 taxonomy both use volatility/credit information, the report "
    "MUST frame the result as construct validity, not independent predictive "
    "evidence."
)


def render_report(
    *,
    run_id: int, label_version: int,
    eval_start: str, eval_end: str, n_days: int,
    verdict: dict, failure_mode: dict,
    per_class: dict[str, dict[str, float]],
    cm_overall: pd.DataFrame, cm_by_period: dict[str, pd.DataFrame],
    weighted_f1: float, kappa: float,
    named_crisis_overlay: list[dict],
    vcg_source: dict,
    data_vintages: list[dict] | None = None,
) -> str:
    """Render the classification baseline report as deterministic Markdown."""
    lines: list[str] = []
    lines.append(f"# VCG v1 Regime-Classification Baseline — run_id={run_id}")
    lines.append("")
    lines.append("## Executive summary — construct validity framing")
    lines.append("")
    lines.append(f"> {CONSTRUCT_VALIDITY}")
    lines.append("")
    lines.append(f"**Verdict:** {verdict['overall']}")
    if verdict.get("macro_f1") is not None:
        lines.append(f"**Macro-F1 (eligible classes):** {verdict['macro_f1']:.4f}")
    lines.append(f"**Cohen's κ:** {kappa:.4f}")
    lines.append(f"**Weighted-F1:** {weighted_f1:.4f}")
    lines.append(f"**Primary failure mode:** `{failure_mode['primary']}`")
    if failure_mode["secondary_modes"]:
        lines.append(f"**Secondary modes:** `{', '.join(failure_mode['secondary_modes'])}`")
    if failure_mode["not_evaluable"]:
        lines.append(f"**Not-evaluable modes:** `{', '.join(failure_mode['not_evaluable'])}`")
    lines.append("")

    lines.append("## Methodology")
    lines.append("")
    lines.append(f"- Eval window: {eval_start} → {eval_end} ({n_days} trading days)")
    lines.append(f"- Label contract version: {label_version}")
    lines.append(f"- VCG source: run_id={vcg_source['run_id']}, composite_version={vcg_source['composite_version']}, credit_proxy={vcg_source.get('credit_proxy', '')}")
    lines.append("- No train/test split is claimed. Descriptive agreement only.")
    lines.append("")

    # v0.3 / CL-6: Data vintages disclosure
    if data_vintages:
        lines.append("### Data vintages")
        lines.append("")
        lines.append("| Component | Vintage | Lag | Interpretation |")
        lines.append("|---|---|---|---|")
        for v in data_vintages:
            lines.append(
                f"| {v['component']} | {v['vintage']} | {v['lag']} | {v['interpretation']} |"
            )
        lines.append("")

    lines.append("## Verdict details")
    lines.append("")
    lines.append(f"- Reason: `{verdict.get('reason') or 'n/a'}`")
    lines.append(f"- Eligible core classes: `{verdict.get('eligible_core_classes', [])}`")
    lines.append(f"- Inconclusive core classes: `{verdict.get('inconclusive_core_classes', [])}`")
    lines.append(f"- Rare classes inconclusive: `{verdict.get('rare_inconclusive', [])}`")
    lines.append("")

    if per_class:
        lines.append("## Per-class metrics")
        lines.append("")
        lines.append("| Class | n_truth | n_pred | precision | recall | F1 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for c in sorted(per_class):
            m = per_class[c]
            lines.append(
                f"| {c} | {m['n_truth']} | {m['n_pred']} | "
                f"{m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} |"
            )
        lines.append("")

    if not cm_overall.empty:
        lines.append("## Confusion matrix (overall)")
        lines.append("")
        lines.append("Rows = ground-truth, columns = VCG prediction.")
        lines.append("")
        lines.append(cm_overall.to_markdown())
        lines.append("")

    if cm_by_period:
        lines.append("## Confusion matrix by period")
        lines.append("")
        for period in sorted(cm_by_period):
            lines.append(f"### {period}")
            lines.append("")
            lines.append(cm_by_period[period].to_markdown())
            lines.append("")

    if named_crisis_overlay:
        lines.append("## Named-crisis sanity overlay (use_for_headline: false)")
        lines.append("")
        lines.append("| Crisis | Window | n_days | VCG distribution | Truth distribution |")
        lines.append("|---|---|---:|---|---|")
        for entry in named_crisis_overlay:
            vcg_dist = ", ".join(f"{k}={v}" for k, v in sorted(entry["vcg_distribution"].items()))
            truth_dist = ", ".join(f"{k}={v}" for k, v in sorted(entry["truth_distribution"].items()))
            lines.append(
                f"| {entry['name']} | {entry['start']}→{entry['end']} | "
                f"{entry['n_days']} | {vcg_dist} | {truth_dist} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("Reproducibility: replay via `--render-run-id <N>` reads persisted markdown bytes from summary.extras.classification.report_md (v0.3 / CR-1).")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run, expect pass**

### Task 7.2: Commit Phase 7

```bash
git add src/uw_scan/reports/regime_classification_report.py tests/unit/reports/test_regime_classification_report.py
git commit -m "feat(regime): report renderer with data-vintages + replay-ready

CL-6: Data vintages section discloses post-hoc components (NFCI 3-5d lag)
CR-1 prep: report bytes deterministic for same inputs; entry script
      persists the rendered bytes for byte-identical replay"
```

---

## Phase 8: Entry script (the orchestrator, with v0.3 fixes)

### Task 8.1: Implement `scripts/score_vcg_classification_accuracy.py`

**Files:**
- Create: `scripts/score_vcg_classification_accuracy.py`
- Create: `tests/integration/test_score_vcg_classification_accuracy.py`

- [ ] **Step 1: Write structural + AST-guard tests (no DB)**

```python
# tests/integration/test_score_vcg_classification_accuracy.py
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path


def _load_script_module():
    name = "score_vcg_classification_accuracy"
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parents[2] / "scripts/score_vcg_classification_accuracy.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exports_expected_functions():
    mod = _load_script_module()
    for name in (
        "load_label_contract", "load_input_series", "load_vcg_daily",
        "derive_truth_frame", "score_against_vcg", "compute_named_crisis_overlay",
        "persist_and_render", "render_replay", "main",
    ):
        assert hasattr(mod, name), f"script missing export: {name}"


def test_zero_db_in_loop_guard():
    """Spec §12: classification scoring loop has zero DB queries."""
    mod = _load_script_module()
    forbidden = ("psycopg.connect", "cur.execute", ".cursor(")
    for fn_name in ("derive_truth_frame", "score_against_vcg",
                    "compute_named_crisis_overlay"):
        fn = getattr(mod, fn_name)
        src = inspect.getsource(fn)
        for needle in forbidden:
            assert needle not in src, (
                f"{fn_name} references {needle!r} — DB access in per-cell loop "
                f"violates spec §12 zero-DB-in-loop invariant"
            )
```

- [ ] **Step 2: Run, expect fail**

- [ ] **Step 3: Implement script**

```python
# scripts/score_vcg_classification_accuracy.py
"""Score VCG v1 on regime-classification accuracy against Level-1 ground truth.

Phase B1 entry point. v0.3 incorporates 24 tribunal fixes.

Modes:
    default                        — score, persist, render (idempotent reuse)
    --force-new-run                — bypass idempotent reuse
    --render-run-id <N>            — replay-render via persisted report_md
    --dry-run                      — score without persistence
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from psycopg import connect

from uw_scan.cards.regime_classification_labels import (
    CANONICAL_CLASSES, derive_level1_frame,
)
from uw_scan.cards.regime_classification_scoring import (
    build_confusion_matrix, classify_failure_mode, cohens_kappa,
    compute_verdict, normalize_vcg_label, per_class_prf,
    sanitize_for_json, weighted_f1_over_eligible,
)
from uw_scan.reports.regime_classification_report import render_report
from uw_scan.storage.regime_classification_repository import (
    RegimeClassificationRepository, ClassificationRunAlreadyExists,
)

LABEL_DIR_DEFAULT = Path("docs/research/regime/ground-truth-labels")
CLASSES = list(CANONICAL_CLASSES)
CORE = ["NORMAL", "SUPPRESSED", "EDR", "RISK_OFF"]


@dataclass(frozen=True)
class LabelContract:
    thresholds: dict[str, Any]
    crises: list[dict[str, Any]]
    vcg_source: dict[str, Any]
    label_version: int


def load_label_contract(label_dir: Path = LABEL_DIR_DEFAULT) -> LabelContract:
    """Load 4 frozen YAML files."""
    with (label_dir / "level1-thresholds.yaml").open() as f:
        thresholds = yaml.safe_load(f)
    with (label_dir / "named-crises.yaml").open() as f:
        crises = yaml.safe_load(f)["crises"]
    with (label_dir / "vcg-source.yaml").open() as f:
        vcg_source = yaml.safe_load(f)["vcg_source"]
    with (label_dir / "label-version.yaml").open() as f:
        version_meta = yaml.safe_load(f)
    label_version = int(version_meta["version"])
    if int(thresholds["label_version"]) != label_version:
        raise ValueError(
            f"label_version mismatch: thresholds={thresholds['label_version']} "
            f"vs version_meta={label_version}"
        )
    return LabelContract(
        thresholds=thresholds, crises=crises, vcg_source=vcg_source,
        label_version=label_version,
    )


def _normalize_date_index(s):
    """v0.3 / CL-9: normalize date index consistently."""
    s = s.copy()
    s.index = pd.to_datetime(s.index).normalize()
    return s


def load_input_series(
    conn, *, eval_start: date, warmup_days: int = 400,
    as_of_cutoff: datetime | None = None,
) -> dict[str, pd.Series]:
    """v0.3 fixes:
    - CO-1: DISTINCT ON (series_id, obs_date) ORDER BY as_of DESC
    - CL-7: explicit non-None assertions on required series
    - CL-9: normalized date index across all returned series
    - patch §13: 400-day warmup lookback
    """
    data_start = eval_start - timedelta(days=warmup_days)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, symbol, close FROM uw_scan.vol_index_daily "
            "WHERE symbol IN ('VIX','VVIX','SPX') AND trade_date >= %s "
            "ORDER BY trade_date",
            (data_start,),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["trade_date", "symbol", "close"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).normalize()
    pivot = df.pivot(index="trade_date", columns="symbol", values="close")

    # CO-1: multi-vintage-aware macro query
    if as_of_cutoff is not None:
        macro_sql = """
            SELECT DISTINCT ON (series_id, obs_date)
                obs_date, series_id, value
            FROM uw_scan.macro_series_daily
            WHERE series_id IN ('NFCI','ANFCI','USREC')
              AND obs_date >= %s
              AND as_of <= %s
            ORDER BY series_id, obs_date, as_of DESC
        """
        macro_params = (data_start, as_of_cutoff)
    else:
        macro_sql = """
            SELECT DISTINCT ON (series_id, obs_date)
                obs_date, series_id, value
            FROM uw_scan.macro_series_daily
            WHERE series_id IN ('NFCI','ANFCI','USREC')
              AND obs_date >= %s
            ORDER BY series_id, obs_date, as_of DESC
        """
        macro_params = (data_start,)

    with conn.cursor() as cur:
        cur.execute(macro_sql, macro_params)
        macro_rows = cur.fetchall()
    macro = pd.DataFrame(macro_rows, columns=["obs_date", "series_id", "value"])
    macro["obs_date"] = pd.to_datetime(macro["obs_date"]).normalize()
    macro_pivot = macro.pivot(index="obs_date", columns="series_id", values="value")
    macro_aligned = macro_pivot.reindex(pivot.index, method="ffill")

    out = {
        "VIX": pivot.get("VIX"), "VVIX": pivot.get("VVIX"), "SPX": pivot.get("SPX"),
        "NFCI": macro_aligned.get("NFCI"),
        "ANFCI": macro_aligned.get("ANFCI"),
        "USREC": macro_aligned.get("USREC"),
    }

    # CL-7: explicit assertions
    required = ["VIX", "VVIX", "SPX", "NFCI"]
    for k in required:
        if out[k] is None or out[k].empty:
            raise ValueError(
                f"Required series {k!r} is missing or empty. "
                f"For VIX/VVIX/SPX check vol_index_daily; "
                f"for NFCI check macro_series_daily ingestion (Phase 0.5 prereq)."
            )

    # CL-9: normalize indexes
    for k in list(out):
        if out[k] is not None:
            out[k] = _normalize_date_index(out[k])
    return out


def load_vcg_daily(conn, *, run_id: int) -> pd.Series:
    """v0.3:
    - CL-4: verify_integrity=True
    - CL-9: explicit _normalize_date_index call
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trade_date, level FROM uw_scan.regime_backtest_daily "
            "WHERE run_id = %s ORDER BY trade_date", (run_id,),
        )
        rows = cur.fetchall()
    if not rows:
        raise ValueError(f"VCG source run_id={run_id} has no daily rows")
    df = pd.DataFrame(rows, columns=["trade_date", "level"])
    df["trade_date"] = pd.to_datetime(df["trade_date"]).normalize()
    df["level"] = df["level"].apply(normalize_vcg_label)
    s = df.set_index("trade_date", verify_integrity=True)["level"]
    return _normalize_date_index(s)


def derive_truth_frame(series, *, thresholds):
    """Pure: returns DataFrame with truth_label, components, NFCI_value."""
    return derive_level1_frame(
        vix=series["VIX"], vvix=series["VVIX"], spx=series["SPX"],
        credit_stress=series["NFCI"], thresholds=thresholds,
    )


def score_against_vcg(
    *, vcg_labels: pd.Series, truth_frame: pd.DataFrame,
    period_buckets: list[dict],
    eval_start_ts: pd.Timestamp, eval_end_ts: pd.Timestamp | None,
):
    """v0.3 / CO-10: honor eval_end_ts when not None."""
    aligned = pd.concat([
        vcg_labels.rename("vcg"),
        truth_frame["truth_label"].rename("truth"),
    ], axis=1).dropna()
    aligned = aligned[aligned.index >= eval_start_ts]
    if eval_end_ts is not None:
        aligned = aligned[aligned.index <= eval_end_ts]

    cm_overall = build_confusion_matrix(
        truth=aligned["truth"], pred=aligned["vcg"], classes=CLASSES,
    )
    per_class = per_class_prf(cm_overall)
    k = cohens_kappa(cm_overall)

    cm_by_period: dict[str, pd.DataFrame] = {}
    for bucket in period_buckets:
        start = pd.Timestamp(bucket["start"]).normalize()
        end = (
            pd.Timestamp(bucket["end"]).normalize() if bucket["end"] != "auto"
            else aligned.index.max()
        )
        subset = aligned[(aligned.index >= start) & (aligned.index <= end)]
        if not subset.empty:
            cm_by_period[bucket["name"]] = build_confusion_matrix(
                truth=subset["truth"], pred=subset["vcg"], classes=CLASSES,
            )

    return {
        "cm_overall": cm_overall, "cm_by_period": cm_by_period,
        "per_class": per_class, "kappa": k, "aligned": aligned,
    }


def compute_named_crisis_overlay(*, vcg_labels, truth_frame, crises):
    """Pure: per-crisis label distributions."""
    out: list[dict] = []
    aligned = pd.concat([
        vcg_labels.rename("vcg"),
        truth_frame["truth_label"].rename("truth"),
    ], axis=1).dropna()
    for crisis in crises:
        start = pd.Timestamp(crisis["start_date"]).normalize()
        end = pd.Timestamp(crisis["end_date"]).normalize()
        subset = aligned[(aligned.index >= start) & (aligned.index <= end)]
        if subset.empty:
            continue
        vcg_dist = subset["vcg"].value_counts().to_dict()
        truth_dist = subset["truth"].value_counts().to_dict()
        out.append({
            "name": crisis["name"],
            "start": str(start.date()), "end": str(end.date()),
            "n_days": int(len(subset)),
            "vcg_distribution": {k: int(v) for k, v in vcg_dist.items()},
            "truth_distribution": {k: int(v) for k, v in truth_dist.items()},
        })
    return out


def _float_or_none(x) -> float | None:
    """v0.3 / CL-10: explicit pd.isna instead of `or None`."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def persist_and_render(
    conn, *, contract, scoring, verdict, failure_mode, weighted_f1_val,
    named_crisis_overlay, eval_start, eval_end, truth_frame, out_path,
    data_vintages,
):
    """v0.3:
    - CL-8: atomic via repository's insert_complete_run
    - CR-1: persists rendered report_md in summary for byte-identical replay
    - CO-2: sanitize_for_json applied to summary
    - CL-3: payload includes NFCI_value per day
    - CL-10: components use pd.isna-based _float_or_none
    """
    rcr = RegimeClassificationRepository(conn)

    daily_rows = []
    for idx, row in scoring["aligned"].iterrows():
        components_row = truth_frame.loc[idx]
        instant = components_row.get("instant_label")
        instant_str = None if pd.isna(instant) else str(instant)
        daily_rows.append({
            "trade_date": idx.date(),
            "vcg_label": row["vcg"], "truth_label": row["truth"],
            "match": row["vcg"] == row["truth"],
            "label_components": {
                "vix_pct": _float_or_none(components_row.get("vix_pct")),
                "vvix_pct": _float_or_none(components_row.get("vvix_pct")),
                "rv_pct": _float_or_none(components_row.get("rv_pct")),
                "credit_pct": _float_or_none(components_row.get("credit_pct")),
                "dd": _float_or_none(components_row.get("dd")),
                "NFCI_value": _float_or_none(components_row.get("NFCI_value")),
                "instant_label": instant_str,
            },
            "label_version": contract.label_version,
        })

    # Two-phase insert in one transaction:
    #   1. insert_run (gets run_id) with placeholder summary
    #   2. render report with real run_id
    #   3. update summary to include report_md (CR-1)
    #   4. bulk_insert_daily
    #   5. mark_completed
    with conn.transaction():
        run_id = rcr.insert_classification_run(
            vcg_source_run_id=int(contract.vcg_source["run_id"]),
            composite_version=str(contract.vcg_source["composite_version"]),
            eval_start=eval_start, eval_end=eval_end,
            label_version=contract.label_version,
            n_days=len(scoring["aligned"]),
            summary={"extras": {"classification": {"placeholder": True}}},
        )

        report = render_report(
            run_id=run_id, label_version=contract.label_version,
            eval_start=str(eval_start), eval_end=str(eval_end),
            n_days=len(scoring["aligned"]),
            verdict=verdict, failure_mode=failure_mode,
            per_class=scoring["per_class"],
            cm_overall=scoring["cm_overall"], cm_by_period=scoring["cm_by_period"],
            weighted_f1=weighted_f1_val, kappa=scoring["kappa"],
            named_crisis_overlay=named_crisis_overlay,
            vcg_source=contract.vcg_source, data_vintages=data_vintages,
        )

        # CO-2: sanitize; CR-1: persist report_md
        full_summary = {
            "extras": {
                "classification": sanitize_for_json({
                    "verdict": verdict, "failure_mode": failure_mode,
                    "weighted_f1": weighted_f1_val,
                    "kappa": scoring["kappa"],
                    "per_class": scoring["per_class"],
                    "report_md": report,
                })
            }
        }
        rcr.update_run_summary(run_id, full_summary)
        rcr.bulk_insert_daily_classifications(run_id, daily_rows)
        rcr.mark_run_completed(run_id)

    out_path.write_text(report)
    return run_id


def render_replay(conn, *, run_id: int, out_path: Path) -> int:
    """v0.3 / CR-1: read persisted markdown verbatim — byte-identical."""
    rcr = RegimeClassificationRepository(conn)
    data = rcr.load_run_for_render(run_id)
    extras = (data["summary"] or {}).get("extras", {}).get("classification", {})
    report_md = extras.get("report_md")
    if report_md:
        out_path.write_text(report_md)
        return run_id
    raise ValueError(
        f"run_id={run_id} has no persisted report_md; pre-v0.3 run cannot be "
        f"byte-replayed. Re-run with --force-new-run."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-new-run", action="store_true")
    parser.add_argument("--render-run-id", type=int, default=None)
    parser.add_argument("--label-dir", type=Path, default=LABEL_DIR_DEFAULT)
    parser.add_argument("--out", default="docs/research/regime/vcg-classification-baseline-2026-05-26.md")
    args = parser.parse_args(argv)

    db_url = os.environ["UW_SCAN_DB_URL"]

    if args.render_run_id is not None:
        with connect(db_url) as conn:
            run_id = render_replay(conn, run_id=args.render_run_id, out_path=Path(args.out))
        print(f"Re-rendered run_id={run_id}; report at {args.out}")
        return 0

    contract = load_label_contract(args.label_dir)
    eval_start = date.fromisoformat(contract.thresholds["eval_start"])
    eval_start_ts = pd.Timestamp(eval_start).normalize()

    # v0.3 / CO-10
    eval_end_raw = contract.thresholds.get("eval_end", "auto")
    eval_end_ts = (
        None if eval_end_raw == "auto"
        else pd.Timestamp(eval_end_raw).normalize()
    )

    # v0.3 / CL-6
    data_vintages = [
        {"component": "VIX", "vintage": "real-time", "lag": "0 days",
         "interpretation": "tradable signal"},
        {"component": "VVIX", "vintage": "real-time", "lag": "0 days",
         "interpretation": "tradable signal"},
        {"component": "SPX", "vintage": "real-time", "lag": "0 days",
         "interpretation": "tradable signal"},
        {"component": "NFCI", "vintage": "as_of latest", "lag": "3-5 days release lag",
         "interpretation": "post-hoc; non-tradable signal"},
    ]

    with connect(db_url) as conn:
        if not args.force_new_run:
            rcr = RegimeClassificationRepository(conn)
            existing = rcr.find_completed_classification_run(
                vcg_source_run_id=int(contract.vcg_source["run_id"]),
                label_version=contract.label_version,
            )
            if existing is not None:
                print(f"Existing run id={existing}; re-rendering.")
                render_replay(conn, run_id=existing, out_path=Path(args.out))
                return 0

        series = load_input_series(conn, eval_start=eval_start)
        vcg_labels = load_vcg_daily(conn, run_id=int(contract.vcg_source["run_id"]))
        truth_frame = derive_truth_frame(series, thresholds=contract.thresholds)
        scoring = score_against_vcg(
            vcg_labels=vcg_labels, truth_frame=truth_frame,
            period_buckets=contract.thresholds["period_buckets"],
            eval_start_ts=eval_start_ts, eval_end_ts=eval_end_ts,
        )
        verdict = compute_verdict(
            scoring["per_class"], core_classes=CORE,
            n_min_class_days=contract.thresholds["N_MIN_CLASS_DAYS"],
            k_min_core_eligible=contract.thresholds["K_MIN_CORE_ELIGIBLE"],
            macro_f1_pass=contract.thresholds["MACRO_F1_PASS"],
        )
        failure_mode = classify_failure_mode(
            verdict, scoring["per_class"], cm=scoring["cm_overall"],
            thresholds=contract.thresholds, per_universe_macro_f1=None,
        )
        eligible_for_weighting = (
            verdict.get("all_eligible_classes")
            or verdict.get("eligible_core_classes", [])
        )
        weighted_f1_val = weighted_f1_over_eligible(
            scoring["per_class"], eligible_classes=eligible_for_weighting,
        )
        named_overlay = compute_named_crisis_overlay(
            vcg_labels=vcg_labels, truth_frame=truth_frame, crises=contract.crises,
        )

        if args.dry_run:
            print(f"DRY RUN — verdict: {verdict['overall']}, mode: {failure_mode['primary']}, "
                  f"macro_f1: {verdict.get('macro_f1')}, κ: {scoring['kappa']:.4f}")
            return 0

        eval_end_resolved = eval_end_ts.date() if eval_end_ts else scoring["aligned"].index.max().date()

        try:
            run_id = persist_and_render(
                conn, contract=contract, scoring=scoring,
                verdict=verdict, failure_mode=failure_mode,
                weighted_f1_val=weighted_f1_val,
                named_crisis_overlay=named_overlay,
                eval_start=eval_start, eval_end=eval_end_resolved,
                truth_frame=truth_frame, out_path=Path(args.out),
                data_vintages=data_vintages,
            )
        except ClassificationRunAlreadyExists as exc:
            print(f"Concurrent run detected: {exc}")
            return 1

        print(f"Persisted classification run_id={run_id}; report at {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run, expect pass**

### Task 8.2: Commit Phase 8

```bash
git add scripts/score_vcg_classification_accuracy.py tests/integration/test_score_vcg_classification_accuracy.py
git commit -m "feat(regime): entry script v0.3 — all tribunal fixes applied

CO-1 macro DISTINCT ON  CO-2 sanitize_for_json     CO-10 eval_end honored
CL-3 NFCI snapshot      CL-4 verify_integrity      CL-6 vintages
CL-7 explicit asserts   CL-8 atomic transaction    CL-9 date normalize
CL-10 pd.isna           CR-1 replay reads report_md (byte-identical)
CR-2 raises ClassificationRunAlreadyExists on race"
```

---

## Phase 9: Real synthetic E2E

### Task 9.1: Small-window E2E with proper schema + DSN

**Files:**
- Create: `tests/integration/test_regime_classification_e2e.py`

- [ ] **Step 1: Write the E2E test**

```python
# tests/integration/test_regime_classification_e2e.py
"""End-to-end test using a small-window label contract.
v0.3 — real test, no pytest.skip; CO-6 schema fix; CL-5 proper DSN."""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
import yaml


def _load_script():
    name = "score_vcg_classification_accuracy"
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parents[2] / "scripts/score_vcg_classification_accuracy.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def small_window_label_dir(tmp_path):
    """Temporary label contract with rolling_window=5 (no real warmup needed)."""
    label_dir = tmp_path / "labels"
    label_dir.mkdir()
    (label_dir / "level1-thresholds.yaml").write_text(yaml.safe_dump({
        "label_version": 1, "contract_committed_at": "2026-05-26",
        "rolling_window_days": 5, "realized_vol_window_days": 3,
        "percentile_tie_rule": "strict_lt",
        "P_SUPP": 0.30, "P_RO": 0.80, "P_PANIC": 0.95,
        "DD_EDR": 0.07, "N_BOUNCE": 2,
        "NORMAL_LOW": 0.30, "NORMAL_HIGH": 0.80, "NORMAL_DD": 0.05,
        "N_MIN_CLASS_DAYS": 1, "K_MIN_CORE_ELIGIBLE": 4, "MACRO_F1_PASS": 0.30,
        "PANIC_SUPPRESSION_RATIO": 0.20, "SPARSITY_RATIO": 0.25,
        "MISMATCH_CONCENTRATION": 0.60, "BENCH_RANGE": 0.15,
        "fred_series": {"credit_stress_primary": "NFCI",
                         "credit_stress_sensitivity": "ANFCI",
                         "recession_dating": "USREC"},
        "eval_start": "2024-01-15", "eval_end": "auto",
        "period_buckets": [{"name": "all", "start": "2024-01-15", "end": "auto"}],
    }))
    (label_dir / "named-crises.yaml").write_text(yaml.safe_dump({
        "label_version": 1, "crises": [],
    }))
    (label_dir / "vcg-source.yaml").write_text(yaml.safe_dump({
        "label_version": 1,
        "vcg_source": {
            "run_id": 0, "indicator": "vcg", "composite_version": "1",
            "run_scope": "production", "credit_proxy": "HYG",
            "pinned_at": "2026-05-26", "pinned_because": "e2e",
        },
    }))
    (label_dir / "label-version.yaml").write_text(yaml.safe_dump({
        "version": 1, "committed_at": "2026-05-26", "notes": "e2e",
    }))
    return label_dir


def _seed_market_data(conn, schema: str, start: date, n_days: int = 60):
    """v0.3 / CO-6: macro_series_daily requires as_of + source NOT NULL."""
    dates = pd.bdate_range(start, periods=n_days)
    as_of_ts = datetime(2026, 5, 26, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        for d in dates:
            for symbol, close in (("VIX", 18.0), ("VVIX", 85.0), ("SPX", 4500.0)):
                cur.execute(
                    f"INSERT INTO {schema}.vol_index_daily (trade_date, symbol, close) "
                    f"VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (d.date(), symbol, close),
                )
            # Spike vol on middle day → triggers RISK_OFF (post-warmup days only)
            if d == dates[len(dates) // 2]:
                cur.execute(
                    f"UPDATE {schema}.vol_index_daily SET close=60.0 "
                    f"WHERE trade_date=%s AND symbol='VIX'", (d.date(),),
                )
                cur.execute(
                    f"UPDATE {schema}.vol_index_daily SET close=150.0 "
                    f"WHERE trade_date=%s AND symbol='VVIX'", (d.date(),),
                )
            for series_id, value in (("NFCI", -0.5), ("USREC", 0.0)):
                cur.execute(
                    f"INSERT INTO {schema}.macro_series_daily "
                    f"(obs_date, series_id, value, as_of, source) "
                    f"VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (d.date(), series_id, value, as_of_ts, "test"),
                )
    conn.commit()


def _seed_vcg_run(conn, schema: str, start: date, n_days: int = 60) -> int:
    """Insert synthetic VCG production run."""
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
    rb = RegimeBacktestRepository(conn, schema=schema)
    dates = list(pd.bdate_range(start, periods=n_days))
    run_id = rb.insert_run(
        indicator="vcg", composite_version="1",
        start_date=dates[0].date(), end_date=dates[-1].date(),
        window_days=21, n_days=len(dates),
        params={}, summary={}, note="e2e vcg",
        run_scope="production", composite_method="single_proxy", credit_proxy="HYG",
    )
    rows = []
    for i, d in enumerate(dates):
        label = "RISK_OFF" if i == len(dates) // 2 else "NORMAL"
        rows.append({"trade_date": d.date(), "score": 0.0, "level": label, "payload": {}})
    rb.bulk_insert_daily(run_id, rows)
    rb.mark_run_completed(run_id)
    return run_id


def test_e2e_classification_full_pipeline(
    seeded_db_empty_cards, small_window_label_dir, tmp_path, monkeypatch,
):
    """v0.3 fixes verified end-to-end."""
    repo = seeded_db_empty_cards
    schema = repo._schema
    eval_start = date(2024, 1, 15)
    data_start = eval_start - timedelta(days=30)
    _seed_market_data(repo.conn, schema, data_start, n_days=60)
    vcg_run_id = _seed_vcg_run(repo.conn, schema, data_start, n_days=60)

    src_yaml = small_window_label_dir / "vcg-source.yaml"
    src = yaml.safe_load(src_yaml.read_text())
    src["vcg_source"]["run_id"] = vcg_run_id
    src_yaml.write_text(yaml.safe_dump(src))

    # v0.3 / CL-5: construct DSN with credentials from psycopg .info components.
    # pytest-postgresql typically uses trust auth in tests → no password needed.
    cinfo = repo.conn.info
    db_url = f"postgresql://{cinfo.user}@{cinfo.host}:{cinfo.port}/{cinfo.dbname}"
    monkeypatch.setenv("UW_SCAN_DB_URL", db_url)

    report_path = tmp_path / "report.md"
    mod = _load_script()
    rc = mod.main([
        "--label-dir", str(small_window_label_dir),
        "--out", str(report_path),
    ])
    assert rc == 0

    # Verify classification run inserted with correct tags
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT id, run_scope, composite_method, credit_proxy, params, summary "
            f"FROM {schema}.regime_backtest_runs "
            f"WHERE composite_method='classification_accuracy' ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
    classification_run_id = row[0]
    assert row[1] == "research"
    assert row[2] == "classification_accuracy"
    assert row[3] == "CLASSIFICATION"
    # v0.3 / CR-1: report_md persisted
    assert "report_md" in row[5]["extras"]["classification"]

    # v0.3 / CL-3: daily payload includes NFCI_value
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT payload FROM {schema}.regime_backtest_daily WHERE run_id=%s LIMIT 1",
            (classification_run_id,),
        )
        payload = cur.fetchone()[0]
    assert "label_components" in payload
    assert "NFCI_value" in payload["label_components"]

    # v0.3 / CL-6: report contains Data vintages section
    text = report_path.read_text()
    assert "Data vintages" in text
    assert "NFCI" in text
    assert "This classification score measures descriptive agreement" in text

    # v0.3 / CR-1: BYTE-IDENTICAL replay
    replay_path = tmp_path / "replay.md"
    rc3 = mod.main(["--render-run-id", str(classification_run_id), "--out", str(replay_path)])
    assert rc3 == 0
    assert report_path.read_bytes() == replay_path.read_bytes(), "replay not byte-identical"

    # v0.3 / CR-2: --force-new-run on existing race → exit 1
    rc4 = mod.main([
        "--label-dir", str(small_window_label_dir),
        "--out", str(tmp_path / "force.md"),
        "--force-new-run",
    ])
    assert rc4 == 1
```

- [ ] **Step 2: Run E2E**

```bash
uv run pytest tests/integration/test_regime_classification_e2e.py -v
```

Expected: passes (or fails with clear diagnostic if `pytest-postgresql` uses different fixture pattern; adjust DSN construction).

### Task 9.2: Commit Phase 9

```bash
git add tests/integration/test_regime_classification_e2e.py
git commit -m "test(regime): full synthetic E2E v0.3

CO-6: macro_series_daily seed includes as_of + source columns
CL-5: DSN constructed from psycopg .info components (not sanitized .dsn)
CR-1: read_bytes() == read_bytes() — true byte-identical replay
CR-2: --force-new-run on existing classification returns exit 1"
```

---

## Phase 10: Live baseline against real DB

### Task 10.1: Preflight verification

- [ ] **Step 1: Confirm A1, Migration 061, Migration 062, and NFCI data**

```bash
uv run python -c "
import os
from psycopg import connect
url = os.environ['UW_SCAN_DB_URL']
with connect(url) as conn, conn.cursor() as cur:
    # A1
    cur.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name=%s',
                ('uw_scan', 'regime_backtest_runs', 'archived_at'))
    assert cur.fetchone(), 'A1 not merged'
    # 061
    cur.execute('''SELECT pg_get_constraintdef(con.oid)
                   FROM pg_constraint con
                   JOIN pg_class rel ON rel.oid=con.conrelid
                   JOIN pg_namespace nsp ON nsp.oid=rel.relnamespace
                   WHERE nsp.nspname='uw_scan' AND rel.relname='regime_backtest_runs'
                     AND con.conname='regime_backtest_runs_composite_method_check' ''')
    cd = cur.fetchone()
    assert cd and 'classification_accuracy' in cd[0], '061 not applied'
    # 062
    cur.execute('SELECT 1 FROM pg_indexes WHERE schemaname=%s AND indexname=%s',
                ('uw_scan', 'regime_classification_completed_uniq'))
    assert cur.fetchone(), '062 not applied'
    # NFCI
    cur.execute('SELECT COUNT(*) FROM uw_scan.macro_series_daily WHERE series_id=%s', ('NFCI',))
    n = cur.fetchone()[0]
    assert n > 0, 'NFCI not ingested — Phase 0.5 prereq missing'
print('Phase 10 preflight: A1 + 061 + 062 + NFCI all OK')
"
```

### Task 10.2: Dry-run

```bash
uv run python scripts/score_vcg_classification_accuracy.py --dry-run
```

Expected: `DRY RUN — verdict: <PASS|FAIL|INCONCLUSIVE>, mode: <primary>, macro_f1: <val>, κ: <val>`.

### Task 10.3: Live run

```bash
uv run python scripts/score_vcg_classification_accuracy.py --force-new-run
```

Expected: `Persisted classification run_id=<N>; report at docs/research/regime/vcg-classification-baseline-2026-05-26.md`.

### Task 10.4: Verify byte-identical replay

```bash
RUN_ID=<from Task 10.3>
uv run python scripts/score_vcg_classification_accuracy.py \
  --render-run-id $RUN_ID --out /tmp/replay.md
diff docs/research/regime/vcg-classification-baseline-2026-05-26.md /tmp/replay.md
```

Expected: zero-byte diff (`diff` exit code 0).

### Task 10.5: Commit baseline

```bash
git add docs/research/regime/vcg-classification-baseline-2026-05-26.md
git commit -m "docs(regime): VCG v1 classification baseline report v0.3

First immutable baseline with v0.3 contract. Replay via
\`scripts/score_vcg_classification_accuracy.py --render-run-id <N>\`
produces byte-identical bytes via persisted report_md (v0.3 / CR-1)."
```

---

## Phase 11: PR

### Task 11.1: Full test sweep + ruff

```bash
uv run pytest \
  tests/unit/cards/test_regime_classification_labels.py \
  tests/unit/cards/test_regime_classification_scoring.py \
  tests/unit/storage/test_regime_classification_repository.py \
  tests/unit/reports/test_regime_classification_report.py \
  tests/integration/test_score_vcg_classification_accuracy.py \
  tests/integration/test_regime_classification_e2e.py -v

uv run ruff check \
  src/uw_scan/cards/regime_classification_labels.py \
  src/uw_scan/cards/regime_classification_scoring.py \
  src/uw_scan/storage/regime_classification_repository.py \
  src/uw_scan/reports/regime_classification_report.py \
  scripts/score_vcg_classification_accuracy.py
```

Expected: all green, zero ruff errors.

### Task 11.2: Push + open PR

```bash
git push -u origin feat/regime-classification-accuracy

gh pr create --title "feat(regime): VCG v1 regime-classification accuracy baseline (Phase B1)" --body "$(cat <<'EOF'
## Summary

Phase B1 deliverable. Scores VCG v1 on its documented job (regime classification) and produces an immutable baseline with three-state verdict + quantitative failure-mode classification.

v0.3 incorporates 24 tribunal-review patches (Codex + Claude bilateral). See \`docs/reviews/2026-05-26-vcg-classification-plan-tribunal-review.md\` for full review.

### Key v0.3 capabilities
- Migration 061 (CHECK extension) + 062 (partial unique index — prevents concurrent-run race)
- DISTINCT ON multi-vintage macro query
- JSON sanitizer for NaN/inf metrics
- Index-aligned confusion matrix
- underpowered_test failure mode for INCONCLUSIVE verdicts (covers spec §9)
- Atomic insert → bulk → mark transaction
- True byte-identical replay via persisted report_md
- NFCI raw value snapshot per day in payload (protects against FRED vintage drift)

### Prerequisites
- Phase A1 (Migration 060 archived_at) — separate PR, must be merged first
- Phase 0.5 (FRED NFCI/USREC ingestion) — separate PR; \`sources/fred.py\` doesn't currently fetch these (discovered during tribunal probe)

### Test plan
- [ ] All unit + integration + e2e tests pass
- [ ] Migration 061/062 idempotent (re-run = no-op)
- [ ] Live baseline run produces a real classification report
- [ ] \`--render-run-id\` produces byte-identical bytes (\`diff\` exit 0)
- [ ] \`grep -r "classification_accuracy" web/ src/uw_scan/api/\` empty (research isolation)
EOF
)"
```

---

## Self-Review (v0.3 — 24 tribunal fixes traceability)

| # | Fix ID | Description | Phase | Task | Verified by |
|---|---|---|---|---|---|
| 1 | CR-1 | Byte-identical replay via `report_md` | 8 | 8.1 `render_replay` reads `summary.extras.classification.report_md` | E2E `assert read_bytes() == read_bytes()` |
| 2 | CR-2 | Concurrent race → partial unique index | 2 | 2.2 Migration 062 | E2E `assert rc4 == 1` |
| 3 | CO-1 | Multi-vintage macro `DISTINCT ON` | 8 | 8.1 `load_input_series` | Task 0.3 probe |
| 4 | CO-2 | NaN in JSONB → sanitizer | 4 | 4.4 `sanitize_for_json` | Task 4.4 unit test |
| 5 | CO-3 | Percentile tie rule | 1, 3 | 1.1 YAML + 3.2 explicit param | Task 3.2 constant-series test |
| 6 | CO-4 | NORMAL fall-through gap | 1, 3 | 1.1 widened band | Task 3.3 test |
| 7 | CO-5 | Migration list regression | 2 | 2.1 verify observed values | Task 0.5 probe |
| 8 | CO-6 | E2E schema mismatch | 9 | 9.1 seed `as_of`, `source` | E2E execution |
| 9 | CO-7 | CM index alignment | 4 | 4.1 `pd.concat axis=1` | Task 4.1 reversed-index test |
| 10 | CO-8 | `label_mismatch` empty-cm guard | 5 | 5.2 `not cm.empty and total > 0` | Task 5.2 test |
| 11 | CO-9 | Window semantics docs | 1 | 1.1 YAML comment | Documentation |
| 12 | CO-10 | `eval_end` honored | 8 | 8.1 `score_against_vcg` filter | Argument passed through |
| 13 | CL-1 | `benchmark_coverage` deferred | 5 | 5.2 always `not_evaluable` + comment | Inline doc |
| 14 | CL-2 | `underpowered_test` mode | 5 | 5.2 precedence chain | Task 5.2 test |
| 15 | CL-3 | NFCI raw snapshot | 3, 8 | 3.5 frame includes `NFCI_value`; 8.1 payload | E2E `assert "NFCI_value" in payload` |
| 16 | CL-4 | `verify_integrity=True` | 8 | 8.1 `load_vcg_daily` | Inline |
| 17 | CL-5 | E2E DSN | 9 | 9.1 manual `postgresql://...` construction | E2E execution |
| 18 | CL-6 | Vintages section | 7 | 7.1 `data_vintages` param + render | Task 7.1 test |
| 19 | CL-7 | Explicit assertions | 8 | 8.1 `load_input_series` raises with hint | Inline |
| 20 | CL-8 | Atomic transaction | 6 | 6.1 `insert_complete_run` | Task 6.1 test |
| 21 | CL-9 | `_normalize_date_index` consistent | 8 | 8.1 called in both loaders | Inline |
| 22 | CL-10 | `pd.isna` explicit | 8 | 8.1 `_float_or_none` | Inline |
| 23 | CL-11 | Error remediation hint | 4 | 4.1 `normalize_vcg_label` message | Task 4.1 test |
| 24 | CL-12 | Migration transaction | 2 | 2.1, 2.2 explicit BEGIN/COMMIT | Inline SQL |

**Plus NEW Phase 0.5**: FRED NFCI/ANFCI/USREC ingestion separate prereq PR (discovered during tribunal — `sources/fred.py` doesn't currently fetch these).

### Placeholder scan
No TBDs, no `similar to X`, no `pytest.skip`, no "TODO" markers. Every code task contains the actual code.

### Standing-rule check
- ✅ `uv` only
- ✅ No Yahoo / naked shorts / Codex secrets / in-memory analytics
- ✅ No repository.py extension (re-export only)
- ✅ No production scanner code change
- ✅ No Co-Authored-By trailers
- ✅ Idempotent migrations (BEGIN/COMMIT + IF NOT EXISTS)
- ✅ Milestone commits per phase
- ✅ Module size budget (<500 lines)

### Type consistency
- `verdict` dict shape consistent: Task 5.1 (creation), 5.2 (consumption), 7.1 (consumption), 8.1 (orchestration)
- `per_class` dict shape (`f1`, `n_truth`, `n_pred`, `precision`, `recall`) consistent across 4.2, 4.3, 5.1, 5.2, 7.1
- `truth_frame` DataFrame columns consistent: 3.5 (creation), 8.1 (consumption)

### Open assumptions still requiring runtime verification
1. Phase A1 (Migration 060) merged — Task 0.1 catches
2. Phase 0.5 (NFCI ingestion) merged + data backfilled — Task 0.3 catches
3. `scripts/migrate.sh` per-statement transaction semantics — defended via explicit BEGIN/COMMIT
4. `pytest_postgresql` DSN format → Task 9.1 may need adjustment if password auth in use

These four are the only deferrals. Everything else is closed by code or test.
