# VRP Research Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the VRP harvest markout (PR #147) into a unified, measurement-corrected research engine that sweeps three analytical axes (conditioning granularity, horizon, target definition), persists every result to Postgres, and surfaces it through a Chinese research note + a Jupyter notebook.

**Architecture:** The shipped v1 scored **one cell** of a 3-axis cube (`asset_class × deviation_class`, single horizon T+20, single target = harvest) using a *possibly-mismeasured* forward RV. This plan first **corrects the measurement layer** shared by everything — exact corporate-action-adjusted forward RV (item 1) + a historical earnings calendar (item 3) — then **generalizes the markout into a parameterized core** and **sweeps three axes** on top of that corrected floor: conditioning granularity (item 2: `asset_class → asset_class×sector`), horizon (item 4: `h ∈ {5,20,60}`), and target definition (item 5: harvest → directional → ΔVRP-reversion). Output is DB tables + note + notebook.

**Tech Stack:** Python 3.13 (`uv` only), psycopg 3, pytest + pytest-postgresql, APScheduler, massive.com REST (`massive_fundamentals.py`), Jupyter/matplotlib/pandas (via `uv run --with`, not added to project deps).

## The inner link (the backbone — why these 5 items are one project)

The five "research expansion" items are **not** five isolated workstreams. They are two layers of the *same* generalized markout:

```
                  ┌─────────────────────────────────────────────────────┐
                  │   MEASUREMENT LAYER  (the floor under everything)     │
   item 1  ──────▶│   exact forward RV(t,t+h) from corp-action-adjusted   │
   item 3  ──────▶│   prices  +  historical earnings exclusion calendar   │
                  └─────────────────────────────────────────────────────┘
                                        ▲
            shared by all axes ─────────┘
                  ┌──────────────┬───────────────┬─────────────────────┐
   AXIS A (item 2)│ conditioning │ AXIS B (item 4)│ AXIS C (item 5)      │
   asset_class →  │ granularity  │ horizon        │ target definition    │
   asset_class×   │              │ h ∈ {5,20,60}  │ harvest→directional  │
   sector         │              │                │ →ΔVRP-reversion      │
                  └──────────────┴───────────────┴─────────────────────┘
```

- **Items 1 & 3 are the measurement floor.** If `RV(t+h)` is biased (a split looks like a −75% crash) or earnings leak into the `(t,t+h]` window, **every axis reports a biased number**. That is why — even though the items run "in parallel" (no serial gating) — they all consume the *same corrected core*.
- **Scope of the correction (ISSUE-1, honest framing).** Item 1's adjusted-price exact RV corrects the **forward-RV TARGET** that the harvest and directional/return axes measure. It does **not** re-derive the `vrp_z_20` *signal* (which defines RICH/CHEAP bucket membership) or the ΔVRP target — those keep using the canonical UW-sourced `vrp_daily` columns, because `vrp_daily.rv` is UW-computed (independently, and only gap-filled from unadjusted argon price when UW is null) and re-deriving an argon-adjusted z-score would diverge from the published VRP the rest of the app shows. **Task 7's validation quantifies the UW-RV-approximation-vs-adjusted-exact gap** — if that gap is large, it also bounds how much the signal could be biased, and the note says so. Re-deriving the signal from adjusted prices is explicitly out of scope for this expansion.
- **Items 2, 4, 5 are three orthogonal axes** of the cube the harvest target lives in. The notebook visualizes the cube: horizon-decay curves (Axis B) faceted by sector (Axis A) for each target (Axis C).
- **Consequence for execution:** build the measurement layer + core engine once; each axis is then a thin configured run, not a copy-pasted markout loop. This is the inner link made concrete.

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`. (CLAUDE.md)
- **Persist all analytical results to Postgres** — every verdict/diagnostic lands in a table; the notebook is a *read-only presentation* of those tables, never the source of truth. (standing rule `feedback_persist_results_to_db`)
- **Migrations idempotent** — `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ON CONFLICT DO NOTHING`; header `SET search_path TO uw_scan, public;`. No tracking table — re-run is a no-op.
- **Next migration number is `080`** (highest existing is `079_vrp_harvest_verdicts.sql`).
- **Module size budget** — target <500 lines/file; split by domain seam. New persistence domains get their own `storage/<domain>.py` mixin, **never appended to `repository.py`** (`feedback_repository_split_threshold`). Add the mixin to `repository.py`'s inheritance list above `_BaseMixin` only for assembly.
- **No new query methods in `repository.py`** — it stays a thin assembly/re-export shell.
- **MASSIVE_API_KEY can be unset** — ingestion jobs no-op + warn (null-object), never crash the scheduler. (worker/CLAUDE.md)
- **ET timezone for crons** — `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`; weekdays `0-4` (Mon=0).
- **OOS hygiene is load-bearing** — every verdict reuses the walk-forward holdout + per-quarter catastrophic-degradation gate; confidence caps at `"med"` (single-backtest framework). (`feedback_per_regime_catastrophic_gate`, `feedback_spec_review_oos_hygiene`)
- **No fabricated numbers** — the research note's tables come from an actual run; mark any unrun cell as such.
- **Branch** `feat/vrp-research-expansion`; never `git push origin main`; milestone-commit each task.
- **Decimal at the DB boundary** — pass/receive `Decimal`; coerce to `float` only inside the math.

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/uw_scan/storage/migrations/080_vrp_research_expansion.sql` | Create | All 6 expansion tables (idempotent) |
| `src/uw_scan/storage/corporate_actions.py` | Create | `_CorporateActionsMixin` — upsert/fetch split & dividend events |
| `src/uw_scan/storage/vrp_research.py` | Create | `_VrpResearchMixin` — earnings calendar query + upsert/fetch for the 5 result tables |
| `src/uw_scan/storage/repository.py` | Modify | Add 2 mixins to inheritance list + re-exports (assembly only) |
| `src/uw_scan/reports/vrp_markout_core.py` | Create | Shared engine: adjusted prices, exact forward RV, earnings exclusion, walk-forward + quarter gate, generalized observation builder |
| `src/uw_scan/reports/vrp_markout.py` | Modify | Re-point the shipped harvest run at the core (preserve `vrp_harvest_verdicts` contract) |
| `src/uw_scan/reports/vrp_rv_validation.py` | Create | Item 1 diagnostic: approximation-vs-exact RV deviation → `vrp_rv_validation` |
| `src/uw_scan/reports/vrp_harvest_axes.py` | Create | Items 2+4: sector sub-bucketing + multi-horizon → `vrp_harvest_by_sector`, `vrp_harvest_multihorizon` |
| `src/uw_scan/reports/vrp_directional.py` | Create | Item 5: directional VRP + ΔVRP-reversion → `vrp_directional_verdicts`, `vrp_dvrp_reversion` |
| `src/uw_scan/worker/jobs/corporate_actions_jobs.py` | Create | `corporate_actions_refresh_once(repo, provider)` — ingest split/dividend history |
| `src/uw_scan/worker/jobs/vrp_research_jobs.py` | Create | `vrp_research_refresh(repo)` — orchestrate validation + axes + directional |
| `src/uw_scan/worker/scheduler.py` | Modify | Register the 2 new jobs (massive group) |
| `scripts/research/vrp_expansion_prerun.py` | Create | Read-only/local pre-run that computes + prints every result table (the "show me the output" demo) |
| `docs/notes/2026-06-22-vrp-research-expansion-研究笔记.md` | Create | Chinese research note with the actual result tables inline |
| `docs/research/vrp/vrp-research-expansion.ipynb` | Create | Notebook: cube viz (decay curves, sector heatmap, RV-deviation hist, directional scatter, ΔVRP-reversion) |
| `tests/integration/storage/test_corporate_actions.py` | Create | Mixin round-trip |
| `tests/integration/storage/test_vrp_research.py` | Create | Earnings-calendar union + result-table round-trips |
| `tests/unit/test_vrp_markout_core.py` | Create | Split adjustment, exact forward RV, exclusion math |
| `tests/integration/reports/test_vrp_rv_validation.py` | Create | Deviation diagnostic on a synthetic panel |
| `tests/integration/reports/test_vrp_harvest_axes.py` | Create | Sector + multi-horizon runs |
| `tests/integration/reports/test_vrp_directional.py` | Create | Directional + ΔVRP runs |
| `tests/integration/worker/test_corporate_actions_jobs.py` | Create | Ingestion job with a fake provider |

**Integration-test DB recipe (MacBook — `.env.local` points at the prod mini, so override):**
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi \
UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
uv run pytest <path> -v
```

---

## PHASE 0 — Measurement layer (items 1 + 3): the shared floor

### Task 1: Migration — expansion tables

**Files:**
- Create: `src/uw_scan/storage/migrations/080_vrp_research_expansion.sql`

**Interfaces:**
- Produces tables: `corporate_actions`, `vrp_rv_validation`, `vrp_harvest_by_sector`, `vrp_harvest_multihorizon`, `vrp_directional_verdicts`, `vrp_dvrp_reversion`.

- [ ] **Step 1: Write the migration**

```sql
-- 080_vrp_research_expansion.sql
-- VRP research expansion: corp-action history, exact-RV validation, and the
-- three markout axes (sector, multi-horizon, directional/ΔVRP). Idempotent.
SET search_path TO uw_scan, public;

BEGIN;

-- item 1: full corporate-action event history (massive_fundamentals keeps only
-- the LATEST split/dividend; split-adjusting a 13-month series needs all events).
CREATE TABLE IF NOT EXISTS uw_scan.corporate_actions (
    ticker        TEXT NOT NULL,
    event_type    TEXT NOT NULL,            -- 'split' | 'dividend'
    event_date    DATE NOT NULL,            -- split execution_date | dividend ex_dividend_date
    split_ratio   NUMERIC,                  -- split_to/split_from (splits only)
    cash_amount   NUMERIC,                  -- dividend cash (dividends only)
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, event_type, event_date)
);

-- item 1 diagnostic: per-ticker approximation-vs-exact forward-RV deviation.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_rv_validation (
    ticker            TEXT NOT NULL,
    horizon           INTEGER NOT NULL,
    n                 INTEGER NOT NULL DEFAULT 0,
    mean_abs_dev      NUMERIC,              -- mean |approx_rv - exact_rv| (vol points)
    mean_signed_dev   NUMERIC,             -- mean (approx_rv - exact_rv); sign of bias
    p95_abs_dev       NUMERIC,
    corr              NUMERIC,              -- pearson(approx, exact)
    as_of             DATE,
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, horizon)
);

-- item 2: single-name harvest re-cut by sector (asset_class fixed = single_name).
CREATE TABLE IF NOT EXISTS uw_scan.vrp_harvest_by_sector (
    sector                TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    verdict               TEXT NOT NULL,
    mean_realized_vrp     NUMERIC,
    mean_holdout          NUMERIC,
    rich_cheap_spread     NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (sector, deviation_class)
);

-- item 4: harvest at multiple horizons (decay curve).
CREATE TABLE IF NOT EXISTS uw_scan.vrp_harvest_multihorizon (
    asset_class           TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    horizon               INTEGER NOT NULL,
    verdict               TEXT NOT NULL,
    mean_realized_vrp     NUMERIC,
    mean_holdout          NUMERIC,
    rich_cheap_spread     NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, deviation_class, horizon)
);

-- item 5a (Pass-2 redesign): does the RICH cohort OUT-RETURN the CHEAP cohort?
-- Long-short (RICH − CHEAP) forward-return DIFFERENTIAL per asset_class, with OOS
-- run on the per-date differential series itself (Bollerslev: high VRP → high
-- return; NOT cross-sectionally demeaned). Keyed (asset_class, horizon) because
-- the differential collapses deviation_class into one long-short series.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_directional_verdicts (
    asset_class           TEXT NOT NULL,
    horizon               INTEGER NOT NULL,
    verdict               TEXT NOT NULL,    -- BULLISH_TILT | BEARISH_TILT | NEUTRAL
    mean_differential     NUMERIC,          -- mean over dates of [meanRet(RICH) − meanRet(CHEAP)]
    mean_holdout          NUMERIC,          -- same on the latest-40% holdout
    mean_rich_return      NUMERIC,          -- descriptive: RICH cohort mean fwd return
    mean_cheap_return     NUMERIC,          -- descriptive: CHEAP cohort mean fwd return
    n                     INTEGER NOT NULL DEFAULT 0,   -- # of differential dates
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, horizon)
);

-- item 5b: does VRP mean-revert? forward ΔVRP conditioned on the z-score.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_dvrp_reversion (
    asset_class           TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    horizon               INTEGER NOT NULL,
    verdict               TEXT NOT NULL,    -- REVERTS | PERSISTS | NEUTRAL
    mean_fwd_dvrp         NUMERIC,          -- mean (vrp(t+h) - vrp(t))
    mean_holdout          NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, deviation_class, horizon)
);

COMMIT;
```

- [ ] **Step 2: Apply + verify idempotency**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: both runs succeed; second is a no-op (no errors).

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/migrations/080_vrp_research_expansion.sql
git commit -m "feat(vrp): migration 080 — research-expansion tables"
```

---

### Task 2: Corporate-actions storage mixin

**Files:**
- Create: `src/uw_scan/storage/corporate_actions.py`
- Modify: `src/uw_scan/storage/repository.py` (add mixin to inheritance + re-export)
- Test: `tests/integration/storage/test_corporate_actions.py`

**Interfaces:**
- Produces: `Repository.upsert_corporate_action(*, ticker, event_type, event_date, split_ratio=None, cash_amount=None) -> None`; `Repository.fetch_corporate_actions(ticker: str) -> list[dict]` (keys: `event_type, event_date, split_ratio, cash_amount`, ordered by `event_date ASC`); `Repository.fetch_distinct_vrp_tickers() -> list[str]` (`SELECT DISTINCT ticker FROM vrp_daily ORDER BY ticker` — the scoring universe; lives here so the Task-3 ingestion job is self-contained, no forward dependency on Task 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/storage/test_corporate_actions.py
from datetime import date
from decimal import Decimal

def test_corporate_action_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards  # verified fixture: returns a migrated Repository
    repo.upsert_corporate_action(
        ticker="NVDA", event_type="split", event_date=date(2024, 6, 10),
        split_ratio=Decimal("10"),
    )
    repo.upsert_corporate_action(
        ticker="NVDA", event_type="dividend", event_date=date(2024, 9, 12),
        cash_amount=Decimal("0.01"),
    )
    repo.conn.commit()
    rows = repo.fetch_corporate_actions("NVDA")
    assert [r["event_type"] for r in rows] == ["split", "dividend"]
    assert rows[0]["split_ratio"] == Decimal("10")
    assert rows[1]["cash_amount"] == Decimal("0.01")
```

- [ ] **Step 2: Run to verify it fails**

Run: (recipe above) `... uv run pytest tests/integration/storage/test_corporate_actions.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_corporate_action'`.

- [ ] **Step 3: Write the mixin**

```python
# src/uw_scan/storage/corporate_actions.py
from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any

import psycopg


class _CorporateActionsMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_corporate_action(
        self,
        *,
        ticker: str,
        event_type: str,
        event_date: _date,
        split_ratio: Decimal | None = None,
        cash_amount: Decimal | None = None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.corporate_actions "
            "(ticker, event_type, event_date, split_ratio, cash_amount) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, event_type, event_date) DO UPDATE SET "
            "split_ratio = EXCLUDED.split_ratio, cash_amount = EXCLUDED.cash_amount"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql, (ticker.upper(), event_type, event_date, split_ratio, cash_amount)
            )

    def fetch_corporate_actions(self, ticker: str) -> list[dict[str, Any]]:
        sql = (
            "SELECT event_type, event_date, split_ratio, cash_amount "
            f"FROM {self._schema}.corporate_actions WHERE ticker = %s "
            "ORDER BY event_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

- [ ] **Step 4: Wire into `repository.py`** — add `from .corporate_actions import _CorporateActionsMixin` to the import block and insert `_CorporateActionsMixin,` into the `Repository(...)` inheritance list between `_CockpitMixin` and `_ExternalApiMixin` (verified: inheritance list is `_AuditMixin, _CockpitMixin, _ExternalApiMixin, …, _BaseMixin` — new mixin goes anywhere above `_BaseMixin`).

- [ ] **Step 5: Run test to verify it passes**

Run: `... uv run pytest tests/integration/storage/test_corporate_actions.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/corporate_actions.py src/uw_scan/storage/repository.py tests/integration/storage/test_corporate_actions.py
git commit -m "feat(vrp): corporate_actions storage mixin"
```

---

### Task 3: Corporate-actions ingestion job

**Files:**
- Create: `src/uw_scan/worker/jobs/corporate_actions_jobs.py`
- Test: `tests/integration/worker/test_corporate_actions_jobs.py`

**Interfaces:**
- Consumes: `MassiveFundamentalsProvider.fetch_splits(ticker, limit)` → `[{execution_date, split_from, split_to}]`; `.fetch_dividends(ticker, limit)` → `[{ex_dividend_date, cash_amount}]`; `Repository.list_active_watchlist()`; `Repository.upsert_corporate_action(...)`.
- Produces: `corporate_actions_refresh_once(repo, provider, *, ticker_filter=None, split_limit=12, dividend_limit=24) -> int` (count of tickers ingested). `provider is None` → no-op + warn, return 0.
- **Universe (ISSUE-9):** the scoring universe is `SELECT DISTINCT ticker FROM vrp_daily`, which can exceed `list_active_watchlist()` (dropped/legacy names). Iterate the **union** of active-watchlist tickers and `repo.fetch_distinct_vrp_tickers()` (new method, Task 5) so every scored ticker gets corp-action + filing coverage — otherwise the "corrected" engine is only corrected for the active subset. The orchestrator/pre-run reports coverage (how many scored tickers had ≥1 corp action and ≥1 earnings date).

- [ ] **Step 1: Write the failing test** (fake provider; verifies split+dividend rows land, null-provider no-ops)

```python
# tests/integration/worker/test_corporate_actions_jobs.py
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from uw_scan.worker.jobs.corporate_actions_jobs import corporate_actions_refresh_once


class _FakeProvider:
    def fetch_splits(self, ticker, *, limit=12):
        return [{"execution_date": date(2024, 6, 10),
                 "split_from": Decimal("1"), "split_to": Decimal("10")}]

    def fetch_dividends(self, ticker, *, limit=24):
        return [{"ex_dividend_date": date(2024, 9, 12), "cash_amount": Decimal("0.01")}]


def test_ingest_writes_events(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    monkeypatch.setattr(repo, "list_active_watchlist",
                        lambda: [SimpleNamespace(ticker="NVDA")])
    n = corporate_actions_refresh_once(repo, _FakeProvider())
    repo.conn.commit()
    assert n == 1
    rows = repo.fetch_corporate_actions("NVDA")
    assert {r["event_type"] for r in rows} == {"split", "dividend"}


def test_null_provider_noops(seeded_db_empty_cards):
    assert corporate_actions_refresh_once(seeded_db_empty_cards, None) == 0
```

- [ ] **Step 2: Run to verify it fails** — `ModuleNotFoundError` for the job.

- [ ] **Step 3: Write the job** (mirrors `fundamentals_jobs.py` shape: shard filter, null-object guard, per-ticker try/except with `.exception`)

```python
# src/uw_scan/worker/jobs/corporate_actions_jobs.py
"""Ingest full split/dividend history into corporate_actions (item 1 support).

massive_fundamentals keeps only the LATEST split/dividend; split-adjusting a
13-month price series needs every event, so this pulls deeper history into a
dedicated event table. Null-object safe (no MASSIVE_API_KEY → no-op + warn).
Mirrors jobs/fundamentals_jobs.py.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

logger = logging.getLogger(__name__)


def _split_ratio(split: dict) -> Decimal | None:
    to, frm = split.get("split_to"), split.get("split_from")
    if to is None or frm is None or frm == 0:
        return None
    return to / frm


def corporate_actions_refresh_once(
    repo,
    provider,
    *,
    ticker_filter: Callable[[str], bool] | None = None,
    split_limit: int = 12,
    dividend_limit: int = 24,
) -> int:
    if provider is None:
        logger.warning(
            "corporate_actions_refresh: no massive provider (MASSIVE_API_KEY unset); "
            "skipping"
        )
        return 0
    completed = 0
    # ISSUE-9: cover the SCORING universe, not just the active watchlist.
    watch = {w.ticker for w in repo.list_active_watchlist()}
    tickers = sorted(watch | set(repo.fetch_distinct_vrp_tickers()))
    for ticker in tickers:
        if ticker_filter is not None and not ticker_filter(ticker):
            continue
        try:
            for s in provider.fetch_splits(ticker, limit=split_limit):
                if s.get("execution_date") is None:
                    continue
                repo.upsert_corporate_action(
                    ticker=ticker, event_type="split",
                    event_date=s["execution_date"], split_ratio=_split_ratio(s),
                )
            for d in provider.fetch_dividends(ticker, limit=dividend_limit):
                if d.get("ex_dividend_date") is None:
                    continue
                repo.upsert_corporate_action(
                    ticker=ticker, event_type="dividend",
                    event_date=d["ex_dividend_date"], cash_amount=d.get("cash_amount"),
                )
            completed += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "corporate_actions_refresh failed for %s: %s", ticker, repr(exc)
            )
    return completed
```

- [ ] **Step 4: Run test to verify it passes.**
- [ ] **Step 5: Commit** — `feat(vrp): corporate-actions ingestion job`.

---

### Task 4: Core engine — adjusted prices + exact forward RV + exclusion

**Files:**
- Create: `src/uw_scan/reports/vrp_markout_core.py`
- Test: `tests/unit/test_vrp_markout_core.py`

**Interfaces:**
- Consumes: corporate-action rows (`[{event_type, event_date, split_ratio, cash_amount}]`); raw price series `[(date, float)]`.
- Produces:
  - `apply_split_adjustment(prices: list[tuple[date, float]], actions: list[dict], *, adjust_dividends: bool = False) -> list[tuple[date, float]]` — **splits are mandatory** (the big spurious gap that breaks RV); **dividends default OFF** (ISSUE-7: a quarterly ex-div is a ~0.5% gap, second-order for RV, and turning it on silently converts the directional study into a *total-return* study). When dividends are enabled, the reference price is the **last close strictly before the ex-date** (ISSUE-6), not the ex-date close.
  - `forward_realized_vol(prices: list[tuple[date, float]], i: int, horizon: int) -> float | None` — annualized stdev of daily log returns over the **positional** window `[i, i+horizon]` (None if not enough forward rows or any non-positive price). **Convention parity (Pass-1 verified):** `reports/volatility_series.py::_fill_rv_from_price` computes RV as pandas `Series.rolling(window).std()` (ddof=1, sample, mean-subtracted) × `√252` — so the √252 sample-stdev in the code below **matches the formula** `vrp_daily` already uses. The only intentional difference: the exact forward RV uses `horizon` log returns over the **holding window** `[t, t+horizon]` (e.g. 20 returns for T+20), whereas the v1 approximation read the *trailing-21d* RV at `t+horizon` (21 returns). That gap is precisely what Task 7 quantifies — it is the point of item 1, not an inconsistency.
  - `WALKFORWARD`, `QUARTER_GATE` reusable helpers (`walkforward(obs, *, min_n, threshold, holdout_threshold, value_key="value", positive_only=True)` and `survives_quarter_gate(obs, overall_mean, value_key)`), generalized from `vrp_markout.py` so harvest/directional/ΔVRP all share them.
  - `HOLDOUT_FRAC = 0.40`, `MIN_N = 20`.

- [ ] **Step 1: Write failing tests** (split adjustment removes the fake gap; exact RV is finite over a clean window; reversion to None on short tail)

```python
# tests/unit/test_vrp_markout_core.py
import math
from datetime import date, timedelta
from decimal import Decimal

from uw_scan.reports.vrp_markout_core import (
    apply_split_adjustment, forward_realized_vol, walkforward, survives_quarter_gate,
)


def _series(vals):
    d0 = date(2024, 1, 1)
    return [(d0 + timedelta(days=i), v) for i, v in enumerate(vals)]


def test_split_adjustment_removes_fake_gap():
    # 100,101,102 then a 10:1 split → raw 10.3,10.4. Back-adjust scales pre-split.
    prices = _series([100.0, 101.0, 102.0, 10.3, 10.4])
    actions = [{"event_type": "split", "event_date": date(2024, 1, 4),
                "split_ratio": Decimal("10"), "cash_amount": None}]
    adj = apply_split_adjustment(prices, actions)
    vals = [round(v, 4) for _, v in adj]
    # pre-split values divided by 10 → continuous with post-split prices
    assert vals == [10.0, 10.1, 10.2, 10.3, 10.4]


def test_forward_realized_vol_finite_on_clean_window():
    prices = _series([100, 101, 100, 102, 101, 103, 102, 104])
    rv = forward_realized_vol(prices, 0, 5)
    assert rv is not None and rv > 0 and math.isfinite(rv)


def test_forward_realized_vol_none_on_short_tail():
    prices = _series([100, 101, 102])
    assert forward_realized_vol(prices, 1, 5) is None


def test_walkforward_positive_harvest_passes_gates():
    obs = [{"market_date": date(2025, 1, 1), "value": 0.05}] * 30
    res = walkforward(obs, min_n=20, threshold=0.02, holdout_threshold=0.01)
    assert res["survives_walkforward"] is True
    assert survives_quarter_gate(obs, res["mean"], "value") is True
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the core** (split back-adjustment, log-return RV, generalized walk-forward/quarter-gate lifted from `vrp_markout.py`). Annualization factor `sqrt(252)`.

```python
# src/uw_scan/reports/vrp_markout_core.py
"""Shared VRP markout engine (the measurement floor + reusable OOS hygiene).

All axis runs (harvest, sector, multi-horizon, directional, ΔVRP-reversion)
build observations through these primitives so they sit on ONE corrected
measurement layer: corporate-action-adjusted prices + exact forward realized
vol + the standing walk-forward/quarter-gate OOS discipline.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date as _date

ANNUALIZATION = math.sqrt(252.0)
HOLDOUT_FRAC = 0.40
MIN_N = 20


def apply_split_adjustment(
    prices: list[tuple[_date, float]],
    actions: list[dict],
    *,
    adjust_dividends: bool = False,
) -> list[tuple[_date, float]]:
    """Back-adjust a raw close series for splits (always) and dividends (opt-in)
    so a corporate-action day is not a spurious log return. Splits: every bar
    STRICTLY BEFORE execution_date is divided by the split ratio. Dividends
    (default OFF — ISSUE-7): scale bars strictly before the ex-date by
    (1 - cash / last_close_before_ex) — the reference is the last cum-dividend
    close, NOT the ex-date close (ISSUE-6). Multiplicative factors compound, so
    multiple actions combine correctly regardless of order."""
    if not prices:
        return []
    ordered = sorted(prices, key=lambda p: p[0])
    factor = [1.0] * len(ordered)
    splits = [a for a in actions if a["event_type"] == "split" and a.get("split_ratio")]
    for a in splits:
        ratio = float(a["split_ratio"])
        if ratio <= 0:
            continue
        for idx, (d, _v) in enumerate(ordered):
            if d < a["event_date"]:
                factor[idx] /= ratio
    if adjust_dividends:
        divs = [
            a for a in actions
            if a["event_type"] == "dividend" and a.get("cash_amount")
        ]
        for a in divs:
            ex = a["event_date"]
            # reference = last close STRICTLY BEFORE ex (the cum-dividend close)
            ref = None
            for d, v in ordered:
                if d < ex:
                    ref = v
                else:
                    break
            if ref is None or ref <= 0:
                continue
            mult = 1.0 - float(a["cash_amount"]) / ref
            if not (0.0 < mult <= 1.0):
                continue
            for idx, (d, _v) in enumerate(ordered):
                if d < ex:
                    factor[idx] *= mult
    return [(d, v * factor[idx]) for idx, (d, v) in enumerate(ordered)]


def forward_realized_vol(
    prices: list[tuple[_date, float]],
    i: int,
    horizon: int,
    *,
    max_abs_logret: float = 0.5,
) -> float | None:
    """Annualized realized vol over the POSITIONAL window [i, i+horizon] from a
    (already-adjusted) price series — stdev of daily log returns × sqrt(252).
    None if the window runs past the tail or any price is non-positive.

    ADVERSARIAL GUARD (Pass-3): if any single-day |log return| exceeds
    max_abs_logret (default 0.5 ≈ a 65% one-day move), return None — for our
    large-cap/ETF universe that is almost certainly an UNADJUSTED split that the
    corporate-actions coverage missed, not a real move; scoring it would inject a
    huge fake RV. Dropping the observation is the safe failure (the pre-run
    coverage line surfaces low corp-action coverage so these are visible)."""
    j = i + horizon
    if i < 0 or j >= len(prices):
        return None
    window = prices[i : j + 1]
    rets: list[float] = []
    for k in range(1, len(window)):
        p0, p1 = window[k - 1][1], window[k][1]
        if p0 <= 0 or p1 <= 0:
            return None
        r = math.log(p1 / p0)
        if abs(r) > max_abs_logret:
            return None  # unadjusted split leaked through → don't trust this window
        rets.append(r)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * ANNUALIZATION


def survives_quarter_gate(obs: list[dict], overall_mean: float, value_key: str) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (standing rule). Fail if
    ANY quarter reverses the aggregate sign with LARGER magnitude. Near-zero
    aggregate auto-fails. Generalized over value_key so every target reuses it."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple[int, int], list[float]] = defaultdict(list)
    for o in obs:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o[value_key])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def walkforward(
    obs: list[dict],
    *,
    min_n: int = MIN_N,
    threshold: float,
    holdout_threshold: float,
    value_key: str = "value",
    positive_only: bool = True,
) -> dict:
    """Walk-forward holdout on the mean of obs[value_key]. positive_only=True for
    one-sided claims (harvest > 0); False for two-sided (directional tilt, ΔVRP)
    where the magnitude floor applies to |mean|. Holdout = latest HOLDOUT_FRAC by
    market_date (no leak). Means are descriptive for any n>=1; gates need min_n."""
    n = len(obs)
    base = {
        "mean": None, "mean_holdout": None, "n": 0, "n_holdout": 0,
        "survives_walkforward": False, "survives_window_gate": False,
    }
    if n == 0:
        return base
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o[value_key] for o in ordered) / n
    mean_hold = (
        sum(o[value_key] for o in holdout) / len(holdout) if holdout else None
    )
    if n < min_n:
        return {**base, "mean": mean_full, "mean_holdout": mean_hold,
                "n": n, "n_holdout": len(holdout)}
    if positive_only:
        sign_ok = mean_full > 0 and mean_hold is not None and mean_hold > 0
        mag_ok = mean_full >= threshold and (
            mean_hold is not None and mean_hold >= holdout_threshold
        )
    else:
        sign_ok = mean_hold is not None and (mean_full * mean_hold > 0)
        mag_ok = abs(mean_full) >= threshold and (
            mean_hold is not None and abs(mean_hold) >= holdout_threshold
        )
    survives_wf = bool(sign_ok and mag_ok)
    survives_window = survives_quarter_gate(ordered, mean_full, value_key)
    return {
        "mean": mean_full, "mean_holdout": mean_hold, "n": n,
        "n_holdout": len(holdout), "survives_walkforward": survives_wf,
        "survives_window_gate": survives_window,
    }
```

- [ ] **Step 4: Run tests to verify they pass.**
- [ ] **Step 5: Commit** — `feat(vrp): markout core — adjusted prices, exact forward RV, OOS helpers`.

---

### Task 5: Earnings-calendar query + result-table storage mixin

**Files:**
- Create: `src/uw_scan/storage/vrp_research.py`
- Modify: `src/uw_scan/storage/repository.py` (add mixin)
- Test: `tests/integration/storage/test_vrp_research.py`

**Interfaces:**
- Produces on `Repository`:
  - `fetch_historical_earnings_dates(ticker) -> set[date]` — **union** of `massive_fundamentals.filing_date` and `flow_events.next_earnings_date` (item 3: strictly ⊇ the old flow-events-only set, so past earnings inside a backtest window stop leaking). Used by the `single_name`-no-earnings skip guard (truthiness check only).
  - `fetch_earnings_events(ticker) -> list[tuple[date, int]]` — **validation-driven (filing-lag buffer).** Each event = `(event_date, back_buffer_days)`. `flow_events.next_earnings_date` → buffer `0` (already the announcement date). `massive_fundamentals.filing_date` → buffer `15` (calendar days): web-validated that the 8-K earnings press release — the actual price-gap day — precedes the 10-Q filing by 0–14 days, so the exclusion must cover `[filing_date − 15d, filing_date]`, not just the filing day. This is the method the markout exclusion consumes.
  - `fetch_adjusted_price_series(ticker) -> list[tuple[date, float]]` — `realized_volatility_history.price` ordered, `float`.
  - upsert/fetch for each result table: `upsert_vrp_rv_validation(...)`, `upsert_vrp_harvest_by_sector(...)`, `upsert_vrp_harvest_multihorizon(...)`, `upsert_vrp_directional_verdict(...)`, `upsert_vrp_dvrp_reversion(...)` and matching `fetch_*` returning `list[dict]`.
  - **Full-rewrite (ISSUE-5):** each result table needs `clear_<table>()` (a `DELETE FROM <table>`), because — unlike a fixed bucket set — sectors, horizons, and tickers can drop out across runs and an `ON CONFLICT DO UPDATE` upsert would leave stale rows polluting the note/notebook. Every runner (Tasks 7/8/9) must `clear_*` then re-insert **in one transaction** (single commit at the end), mirroring `run_vrp_markout`'s `DELETE ... ; INSERT ...; commit()`.
  - `fetch_adjusted_price_series` returns `float` to match the existing `skew_markout._price_series` precedent (`storage/CLAUDE.md` prefers `Decimal` at the boundary, but the established price-series helper already casts to `float`; stay consistent with it — ISSUE-10, minor).

- [ ] **Step 1: Write failing tests** — the earnings union is the load-bearing one:

```python
# tests/integration/storage/test_vrp_research.py
from datetime import date


def test_earnings_calendar_includes_massive_filing_date(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    # massive_fundamentals.filing_date is the NEW earnings leg (item 3). All other
    # upsert_massive_fundamentals kwargs are optional → omit them.
    repo.upsert_massive_fundamentals(
        ticker="AAPL", period_end=date(2024, 12, 28),
        fiscal_period="Q1", filing_date=date(2025, 1, 30),
    )
    repo.conn.commit()
    assert date(2025, 1, 30) in repo.fetch_historical_earnings_dates("AAPL")
    # fetch_earnings_events tags the filing-sourced date with the 15-day buffer.
    assert (date(2025, 1, 30), 15) in repo.fetch_earnings_events("AAPL")


def test_earnings_calendar_includes_flow_events(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("AAPL", notes="test")  # verify sig in scan_runs.py
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date) VALUES (%s, %s, %s, %s)",
            (run_id, "a1", "AAPL", date(2025, 2, 1)),
        )
    repo.conn.commit()
    assert date(2025, 2, 1) in repo.fetch_historical_earnings_dates("AAPL")
    assert (date(2025, 2, 1), 0) in repo.fetch_earnings_events("AAPL")  # flow → buffer 0
```

> **Implementer note (Pass-1 verified):** `flow_events` requires `run_id` (FK → `scan_runs`) and `alert_id` NOT NULL (migration 001) — so the flow leg of the test must `insert_scan_run` first, then INSERT the event row, as shown. `upsert_massive_fundamentals` lives in `storage/fundamentals.py` (`_FundamentalsMixin`, already in `repository.py`); the `massive_fundamentals` table is migration 066. Confirm `insert_scan_run(ticker, *, notes=...)` returns the new `run_id` against `storage/scan_runs.py` before writing.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement the mixin.** Earnings union query:

```python
def fetch_historical_earnings_dates(self, ticker: str) -> set[_date]:
    """Item 3: historical earnings calendar = filing_date (massive_fundamentals,
    historical) ∪ next_earnings_date (flow_events, as-known-forward). Strictly a
    superset of the old flow-only set, so PAST earnings inside a (t,t+h] backtest
    window are no longer silently missed. filing_date is a documented PROXY for
    the announcement date (SEC filing often lags the call by 0-a few days) — the
    validation note quantifies the drift; union keeps it conservative."""
    sql = (
        f"SELECT next_earnings_date AS d FROM {self._schema}.flow_events "
        "WHERE ticker = %s AND next_earnings_date IS NOT NULL "
        "UNION "
        f"SELECT filing_date AS d FROM {self._schema}.massive_fundamentals "
        "WHERE ticker = %s AND filing_date IS NOT NULL"
    )
    with self._conn.cursor() as cur:
        cur.execute(sql, (ticker.upper(), ticker.upper()))
        return {row[0] for row in cur.fetchall()}
```

Plus `fetch_adjusted_price_series` (reads `realized_volatility_history.price`) and the five upsert/fetch pairs (each a straightforward `INSERT ... ON CONFLICT ... DO UPDATE` over the PK from migration 080, mirroring `storage/vrp_markout.py::upsert_vrp_harvest_verdict`). Keep this file <500 lines; if it approaches the budget, split `vrp_research_results.py` out.

- [ ] **Step 4: Wire mixin into `repository.py`** — insert `_VrpResearchMixin,` between `_VrpMarkoutMixin` and `_WatchlistMixin` in the inheritance list (+ import).
- [ ] **Step 5: Run tests to verify pass.**
- [ ] **Step 6: Commit** — `feat(vrp): research storage mixin — earnings union + result tables`.

---

## PHASE 1 — Re-point the shipped harvest at the corrected core

### Task 6: Harvest run uses exact forward RV + historical earnings (no contract change)

**Files:**
- Modify: `src/uw_scan/reports/vrp_markout.py`
- Test: `tests/integration/reports/test_vrp_markout.py` (existing — extend, don't break)
- **Regression — preserve helper contracts (ISSUE-8, verified):** `tests/unit/test_vrp_markout_helpers.py` + `tests/unit/test_vrp_markout_gates.py` (`from uw_scan.reports import vrp_markout as vm`) pin the EXACT current signatures of `vm._deviation_class`, `vm._earnings_in_window(t, end, earnings: set[date])` (left-open/right-closed), `vm._harvest_obs(rows, *, earnings: set[date])` (reads `rv` from rows; exact-positional t+20; null guards; min-n boundary), `vm._walkforward_harvest(obs)` (returns `mean_realized_vrp`/`survives_walkforward`…), and `vm._survives_quarter_gate(obs, overall)` (**2-arg**). The core's generalized versions are 3-arg / `mean`-keyed. So Task 6 must keep all five names in `vrp_markout.py` with their current signatures as thin wrappers over core (`_survives_quarter_gate(obs, overall)` → `core.survives_quarter_gate(obs, overall, "realized_vrp")`; `_walkforward_harvest(obs)` → adapt `mean`→`mean_realized_vrp`). To enable exact-RV in production WITHOUT breaking `_harvest_obs`'s read-`rv`-from-rows tests, give `_harvest_obs` an optional injected `forward_rv_fn=None` (default → old behavior: `iv − rv`) and optional buffered `events=None` (default → the `_earnings_in_window` set path); `run_vrp_markout` passes a `forward_rv_fn` that computes exact RV from adjusted prices + the buffered `fetch_earnings_events`. Existing unit tests exercise the defaults and stay green.

**Interfaces:**
- Consumes: `vrp_markout_core.{forward_realized_vol, apply_split_adjustment, walkforward, survives_quarter_gate}`, `Repository.{fetch_historical_earnings_dates, fetch_adjusted_price_series, fetch_corporate_actions}`.
- Produces: unchanged — `run_vrp_markout(*, repo, min_n=20) -> {"buckets_written": int, "tickers": int}`; `vrp_harvest_verdicts` schema/semantics unchanged. **This is a measurement upgrade, not a contract change.**

**Design:** `_harvest_obs` currently reads `rv(t+20)` from `vrp_daily`. Change it to compute `realized_VRP(t) = iv(t) − forward_realized_vol(adjusted_prices, price_idx, HORIZON)`. **Alignment robustness (Pass-3):** do NOT assume `vrp_daily` and `realized_volatility_history` share positional indices — build a `{market_date → index}` map over the adjusted price series, look up each anchor's date, and **skip the anchor if its date is absent from the price series** (coverage can differ between the two tables; a positional assumption would silently read the wrong forward day). Compute the forward window on the price series' own indices. Keep the gate thresholds identical.

**Earnings exclusion (validation-driven — filing-lag buffer):** switch from `fetch_known_earnings_dates` to `fetch_earnings_events` (Task 5) and generalize `_earnings_in_window`: an anchor `t` with forward end-date `end` is excluded if ANY event interval `[e − back_buffer_days, e]` overlaps `(t, end]`, i.e. `e > t and (e − timedelta(days=buffer)) <= end`. flow events (buffer 0) reduce to the current `t < e <= end`; filing events (buffer 15) also catch a gap up to two weeks before the filing. The `single_name`-no-earnings skip guard still uses `fetch_historical_earnings_dates` truthiness.

- [ ] **Step 1: Add a test asserting the harvest now uses exact RV** — seed `realized_volatility_history.price` with a known series, seed `vrp_daily.iv`, leave `vrp_daily.rv` deliberately *wrong* (e.g. all 0), and assert the verdict's `mean_realized_vrp` reflects the price-derived RV, not the stale `rv` column.

```python
def test_harvest_uses_exact_rv_not_vrp_daily_rv(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    # ... seed 60 trading days: prices random-walk, iv=0.30 const, vrp_daily.rv=0 (wrong)
    # run_vrp_markout → RICH/NORMAL bucket mean_realized_vrp must be ~0.30 - exact_rv,
    # provably != 0.30 - 0. (full seeding code in the test; see fixture builder.)
    ...
```

- [ ] **Step 2: Run to verify failure** (current code reads `vrp_daily.rv=0` → harvest = iv).
- [ ] **Step 3: Refactor `_harvest_obs` + `run_vrp_markout`** to consume the core (exact RV via positional alignment on `market_date`; `fetch_historical_earnings_dates`; reuse `walkforward`/`survives_quarter_gate` from core, deleting the now-duplicated private copies). Preserve the `single_name` + no-earnings skip guard (now keyed on the *union* calendar). Keep `upsert_vrp_harvest_verdict` writes identical.
- [ ] **Step 4: Run ALL existing VRP tests** to verify no contract/helper regression. Run: `... uv run pytest tests/integration/reports/test_vrp_markout.py tests/integration/worker/test_vrp_markout_job.py tests/unit/test_vrp_markout_helpers.py tests/unit/test_vrp_markout_gates.py -v`. Expected: PASS.
- [ ] **Step 5: Commit** — `feat(vrp): harvest run on corrected core (exact RV + historical earnings)`.

---

### Task 7: Item 1 — RV approximation-vs-exact validation diagnostic

**Files:**
- Create: `src/uw_scan/reports/vrp_rv_validation.py`
- Test: `tests/integration/reports/test_vrp_rv_validation.py`

**Interfaces:**
- Produces: `run_vrp_rv_validation(*, repo, horizons=(5, 20, 60)) -> {"rows_written": int}`. Per (ticker, horizon): pair the **approximation** (`vrp_daily.rv` read at positional `i+horizon` — what v1 used) with the **exact** (`forward_realized_vol(adjusted_prices, i, horizon)`); persist `mean_abs_dev`, `mean_signed_dev`, `p95_abs_dev`, `corr`, `n` to `vrp_rv_validation`. This is the "is the trailing-21d shortcut loose?" answer, quantified.

- [ ] **Step 1: Write failing test** — synthetic ticker where approximation ≠ exact by a known margin; assert `mean_abs_dev` ≈ expected and a `corr` in `[-1, 1]`.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — load `vrp_daily` (for the approximation `rv` column) joined positionally with the adjusted price series; compute paired deviations per horizon; persist. Handle `n < 2` (corr undefined → `None`).
- [ ] **Step 4: Run test to verify pass.**
- [ ] **Step 5: Commit** — `feat(vrp): item 1 — forward-RV approximation validation`.

---

## PHASE 2 — Axis A (sector, item 2) + Axis B (horizon, item 4)

### Task 8: Sector + multi-horizon harvest runs

**Files:**
- Create: `src/uw_scan/reports/vrp_harvest_axes.py`
- Test: `tests/integration/reports/test_vrp_harvest_axes.py`

**Interfaces:**
- Consumes: the core + `Repository.fetch_watchlist_sector`, `asset_class_baseline`.
- Produces:
  - `run_vrp_harvest_by_sector(*, repo, horizon=20, min_n=20) -> {"buckets_written": int}` — like the harvest run but **bucket key = (sector, deviation_class)** restricted to `asset_class == "single_name"` (the bucket v1 judged NONE). Answers item 2's "WHERE is single-name vol unstable?" Persist to `vrp_harvest_by_sector`.
  - `run_vrp_harvest_multihorizon(*, repo, horizons=(5, 20, 60), min_n=20) -> {"buckets_written": int}` — harvest at each horizon, key `(asset_class, deviation_class, horizon)`. The decay curve. Persist to `vrp_harvest_multihorizon`.

**Design:** Both reuse a single private `_score_buckets(repo, *, key_fn, horizon, target_fn, ...)` helper in this module so sector and multi-horizon don't duplicate the load/observe/walkforward loop. `key_fn(ticker, asset_class, sector) -> bucket_key | None` (returns None to drop a ticker, e.g. non-single-name for the sector run). Same OOS thresholds as harvest (`threshold=0.02`, `holdout_threshold=0.01`, `positive_only=True`).

- [ ] **Step 1: Write failing tests** — (a) sector run buckets only single-names and computes per-sector RICH means; (b) multi-horizon writes one row per (ac, dev, h) for h in {5,20,60}; spot-check that a shorter horizon yields a different (typically smaller-magnitude) mean than T+20 on the synthetic panel.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** `_score_buckets` + both runners; persist via the Task-5 upserts.
- [ ] **Step 4: Run tests to verify pass.**
- [ ] **Step 5: Commit** — `feat(vrp): items 2+4 — sector drilldown + multi-horizon decay`.

---

## PHASE 3 — Axis C (item 5): directional VRP + ΔVRP-reversion

### Task 9: Directional + ΔVRP-reversion targets

**Files:**
- Create: `src/uw_scan/reports/vrp_directional.py`
- Test: `tests/integration/reports/test_vrp_directional.py`

**Interfaces:**
- Produces:
  - `run_vrp_directional(*, repo, horizons=(5, 20, 60), min_n=20) -> {"buckets_written": int}` — **Pass-2 redesign (Bollerslev/Zhou + OOS-on-the-claim).** The documented effect is *time-series/level*: high VRP predicts *high* forward returns; cross-sectional demeaning would strip exactly that, so do NOT demean. Build a **per-date long-short differential series** per `asset_class`: for each `market_date` with ≥1 RICH and ≥1 CHEAP name, `d(date) = mean[ret(t,t+h) | RICH] − mean[ret(t,t+h) | CHEAP]` where `ret = adj_price(t+h)/adj_price(t) − 1` (split-adjusted, dividends OFF — see Task 4). Run `walkforward` (`positive_only=False`) + `survives_quarter_gate` **on the `d(date)` series itself** (this is the actual claim — a long-short return series — not per-bucket means differenced after the fact). `BULLISH_TILT` if mean `d > 0` and both gates pass; `BEARISH_TILT` if mean `d < 0` and gates pass; else `NEUTRAL`. Persist one row per `(asset_class, horizon)` to `vrp_directional_verdicts` (`mean_differential`, `mean_holdout`, descriptive `mean_rich_return`/`mean_cheap_return`, `n` = # differential dates). Note: `index_macro`/`credit` have few names → sparse cohorts → expect low-n/NEUTRAL there; that's honest, not a bug.
  - `run_vrp_dvrp_reversion(*, repo, horizons=(5, 20, 60), min_n=20) -> {"buckets_written": int}` — target = forward ΔVRP `vrp(t+h) − vrp(t)` (raw VRP from `vrp_daily.vrp`). RICH should revert **down** (negative ΔVRP). Verdict `REVERTS` (mean ΔVRP opposes the deviation sign, gates pass) / `PERSISTS` / `NEUTRAL`. Persist `vrp_dvrp_reversion`.

**Design:** Two different shapes.
- **Directional** (per-date long-short differential): pass 1 collect per-`(ticker, date)` the forward return + that day's `deviation_class` (from `vrp_daily.vrp_z_20`); pass 2 group by `(asset_class, date)` and form `d(date) = mean(RICH rets) − mean(CHEAP rets)` **only for dates where BOTH cohorts have ≥2 names** (Pass-6: a one-name cohort is idiosyncratic noise, not a long-short signal — `MIN_COHORT = 2`); pass 3 run `walkforward`(`positive_only=False`) + `survives_quarter_gate` on the `d` series (`value_key="d"`), and require `n` (# qualifying differential dates) `≥ min_n` for a non-NEUTRAL verdict. This is a genuine cross-ticker barrier (need all names' returns per date before differencing) — structure it as the 3 passes, not a streaming loop. `mean_rich_return`/`mean_cheap_return` are descriptive aggregates over all RICH/CHEAP obs. Few-name asset_classes (`index_macro`/`credit`) will rarely clear `MIN_COHORT` on both sides → mostly NEUTRAL, which is the honest result.
- **ΔVRP-reversion** (per-bucket, like harvest): reuse the harvest load/observe loop with `target = vrp(t+h) − vrp(t)` (from `vrp_daily.vrp`, positional `i`/`i+h`); **skip any obs where `vrp(t)` or `vrp(t+h)` is NULL** (Pass-3: `vrp_daily.vrp` is nullable — an unguarded `None − float` would crash the run). Score each `(asset_class, deviation_class, horizon)` bucket with `walkforward`(`positive_only=False`) + quarter gate; verdict keys on the RICH bucket's own mean sign (RICH should revert *down* → negative `mean_fwd_dvrp` ⇒ `REVERTS`).
- **Floors** are unit-specific — returns ≈ 0.01–0.03, ΔVRP ≈ 0.02 vol points; document each inline (validated against the Bollerslev/term-structure literature in Task 12).

- [ ] **Step 1: Write failing tests** — (a) directional: a synthetic panel where RICH-bucket names out-return CHEAP-bucket names → `BULLISH_TILT`; adding a uniform +X drift to every ticker does NOT change the verdict (the RICH−CHEAP differential cancels it); (b) ΔVRP: a panel where high-z names revert down → `REVERTS`.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** both runners: directional via the 3-pass per-date long-short differential series keyed `(asset_class, horizon)` (full-rewrite the table first — ISSUE-5); ΔVRP-reversion via the harvest load/observe loop with `target = vrp(t+h) − vrp(t)` keyed `(asset_class, deviation_class, horizon)` (full-rewrite first). Both reuse core `walkforward`/`survives_quarter_gate`.
- [ ] **Step 4: Run tests to verify pass.**
- [ ] **Step 5: Commit** — `feat(vrp): item 5 — directional VRP + ΔVRP-reversion`.

---

## PHASE 4 — Orchestration + output

### Task 10: Orchestrator job + scheduler wiring

**Files:**
- Create: `src/uw_scan/worker/jobs/vrp_research_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_vrp_research_jobs.py`

**Interfaces:**
- Produces: `vrp_research_refresh(*, repo) -> dict[str, Any]` — calls `run_vrp_rv_validation`, `run_vrp_harvest_by_sector`, `run_vrp_harvest_multihorizon`, `run_vrp_directional`, `run_vrp_dvrp_reversion`; returns each count. Pure compute over the warm store; idempotent.

- [ ] **Step 1: Write failing test** — on a seeded panel, `vrp_research_refresh` returns non-zero counts and populates all five tables.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the orchestrator (each sub-run in its own try/except + `.exception` so one axis failing doesn't sink the rest).
- [ ] **Step 4: Wire scheduler (ordering — ISSUE-4)** — `fundamentals_refresh` runs at `0 19 * * 0-4` (verified `config.py:135`) and is the `filing_date` source for the earnings calendar. So register `corporate_actions_refresh` at `35 17 * * 0-4` (massive-0, after the 17:30 OHLC, before consumers) and `vrp_research_refresh` at `10 19 * * 0-4` (**after** fundamentals, so the filing-date leg is fresh). Follow the existing `add_job(..., max_instances=1, coalesce=True, timezone=settings.rth_tz)` + `_is_primary_worker` pattern; add `_corporate_actions_refresh` / `_vrp_research_refresh` wrappers like `_vrp_markout_refresh`. Note: the *shipped* `vrp_markout_refresh` (18:50) now also reads `filing_date` and thus runs one night stale — acceptable because filing dates are historical (prior quarters) and a same-day filing is picked up the next night; do NOT move the shipped job. Document this one-line caveat in `worker/CLAUDE.md`.
- [ ] **Step 5: Run test + a scheduler import smoke test** (`uv run python -c "import uw_scan.worker.scheduler"`).
- [ ] **Step 6: Update `worker/CLAUDE.md` schedule table** with the two new jobs.
- [ ] **Step 7: Commit** — `feat(vrp): orchestrator job + nightly scheduler wiring`.

---

### Task 11: Read-only pre-run script (the "show me the output" demo)

**Files:**
- Create: `scripts/research/vrp_expansion_prerun.py`

**Interfaces:**
- A standalone script that opens a repo against the configured DB, (when a provider + `MASSIVE_API_KEY` are present) refreshes **fundamentals first** (filing_date leg) then **corporate-actions** ingestion, then runs all research runs, and **prints every result table** as an aligned ASCII table (mirroring the original VRP note's §3 pre-run output). Honors `UW_SCAN_ALLOW_DB_MISMATCH=1` for one-off mini browsing.

- [ ] **Step 1: Implement** the script — argparse `--horizons`, `--skip-ingest`; when ingesting, call `fundamentals_refresh_once` then `corporate_actions_refresh_once` before the research runs (ISSUE-4 ordering); for each table fetch + pretty-print; print a **coverage line** (ISSUE-9: of the `fetch_distinct_vrp_tickers()` scoring universe, how many have ≥1 corporate action and ≥1 earnings date); end with a one-line "what cleared which gate" summary per axis.
- [ ] **Step 2: Dry-run locally** against `option_wizard_local` (or the test DB with a seeded panel) to confirm it prints without error. Capture the output for the note.
- [ ] **Step 3: Commit** — `feat(vrp): read-only pre-run reporter for the research expansion`.

---

### Task 12: Self-validate methodology with internet research

**(This gate was run during plan authoring 2026-06-22; corrections are ALREADY folded into Tasks 4/5/6/9. The executor's job is to record the citations in the note's methodology section and re-confirm nothing changed.)**

Validated findings (record verbatim in the note, with the source links):
- **RV convention** — annualized = stdev of daily log returns × √252 is the standard; the variance-swap payoff convention uses ÷n sum-of-squared-log-returns (no mean). → Task 4 aligns to argon's `_fill_rv_from_price` for internal consistency. (en.wikipedia.org/wiki/Volatility_(finance); analystprep.com FRM volatility notes)
- **filing_date lag** — the 8-K earnings press release (the price-gap day) precedes the 10-Q filing by 0–14 days (10-K up to ~2 weeks). → Task 5/6 apply a 15-calendar-day backward buffer to filing-sourced earnings dates. (knowntrends.com 2023 earnings-vs-filing timing; calcbench.com timing blog)
- **VRP horizon decay** — variance-risk pricing is concentrated at short maturities; term structure of variance risk premia is downward-sloping. → sets the Axis-B (multi-horizon) narrative expectation; no code change. (NY Fed SR 736 "Term Structure of the Price of Variance Risk")
- **Directional VRP** — Bollerslev–Tauchen–Zhou: high VRP predicts *high* future returns (time-series/level), strongest ~quarterly. → Task 9 reframed off cross-sectional demeaning to the RICH−CHEAP differential. (public.econ.duke.edu/~boller rfs_09.pdf; SSRN 1315328)

- [ ] **Step 1:** Re-fetch the above sources; if any contradicts a threshold/method in Tasks 4/5/6/9 as implemented, fix code + tests inline and note it. Otherwise record the citations.
- [ ] **Step 2: Commit** — `docs(vrp): methodology validation citations`.

---

### Task 13: Research note + Jupyter notebook

**Files:**
- Create: `docs/notes/2026-06-22-vrp-research-expansion-研究笔记.md`
- Create: `docs/research/vrp/vrp-research-expansion.ipynb`

- [ ] **Step 1: Write the Chinese research note** mirroring `2026-06-21-vrp-harvest-markout-研究笔记.md`: background, the inner-link framing, methodology (with Task-12 citations), the actual result tables from the Task-11 pre-run, per-axis findings (does the exact RV move the harvest verdicts? where does single-name vol stabilize by sector? the horizon-decay curve; directional & ΔVRP conclusions), engineering decisions, how-to-deploy, and a one-line bottom line. **Numbers come from the real pre-run — mark any unrun cell explicitly.**
- [ ] **Step 2: Build the notebook** (`docs/research/vrp/vrp-research-expansion.ipynb`) **READ-ONLY (Pass-3): only `SELECT` + plot — never call a `run_*`/`upsert_*`/ingestion function** (executing it via nbconvert must not mutate the DB). Read the six tables via psycopg + pandas, rendering: (1) RV approximation-vs-exact deviation histogram + scatter; (2) horizon-decay curves per asset_class (Axis B) faceted by deviation_class; (3) single-name sector heatmap of RICH harvest (Axis A); (4) directional RICH−CHEAP differential bar chart by asset_class; (5) ΔVRP-reversion by bucket. Markdown cells narrate the cube.
- [ ] **Step 3: Execute the notebook headless** to confirm it runs end-to-end:
  `uv run --with jupyter,matplotlib,pandas,psycopg[binary] jupyter nbconvert --to notebook --execute --inplace docs/research/vrp/vrp-research-expansion.ipynb`
  Expected: no cell errors. (Jupyter/matplotlib are NOT added to project deps — research-only via `--with`.)
- [ ] **Step 4: Commit** — `docs(vrp): research-expansion note + notebook`.

---

## Self-Review (run after the plan, before execution)

**1. Spec coverage** — each of the 5 items maps to tasks:
- Item 1 (exact forward RV + validation): Tasks 4, 6, 7. ✓
- Item 2 (single-name sector drilldown): Task 8 (`run_vrp_harvest_by_sector`). ✓
- Item 3 (stricter earnings exclusion from massive): Task 5 (`fetch_historical_earnings_dates`) + Task 6 (harvest consumes it). ✓
- Item 4 (multi-horizon T+5/T+60): Task 8 (`run_vrp_harvest_multihorizon`). ✓
- Item 5 (directional + ΔVRP): Task 9. ✓
- Corp-action data (your massive hint): Tasks 1-3 (table + ingestion) feeding Task 4 adjustment. ✓
- Output (DB + note + notebook): Tasks 1/5 (tables), 11 (pre-run), 13 (note + notebook). ✓
- Inner link: Phase 0/1 (shared measurement core) consumed by Phases 2/3 axes. ✓

**2. Placeholder scan** — Task 6 Step 1 and Task 8/9 tests describe seeding rather than inlining the full ~60-row synthetic panel; the panel builder is mechanical (random-walk prices + constant IV). Acceptable as the only "describe not show" — flag for the implementer to write the fixture first. No TBD/TODO elsewhere.

**3. Type consistency** — `walkforward` returns `mean` (not `mean_realized_vrp`); callers map `mean → mean_realized_vrp` (harvest/sector/multihorizon) / `mean_differential` (directional) / `mean_fwd_dvrp` (ΔVRP) per table. `forward_realized_vol(prices, i, horizon)` signature consistent across Tasks 4/6/7/8/9. Earnings: `fetch_earnings_events` (buffered list) is the exclusion source for Tasks 6/8; `fetch_historical_earnings_dates` (set) is the single-name skip-guard. Verdict enums distinct per table (HARVEST_SELLABLE / BULLISH_TILT / REVERTS). Directional table keyed `(asset_class, horizon)`; all others keyed with `deviation_class`.

**Open risk to confirm in review-cycle:** massive `filing_date` coverage for the full `vrp_daily` ticker set (active-watchlist-only nightly refresh may leave dropped tickers stale) — Task 12 web-validation + a coverage count in the pre-run quantify it; the union with `flow_events` is the mitigation.
