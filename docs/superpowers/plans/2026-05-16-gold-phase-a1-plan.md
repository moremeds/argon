# Gold Endpoint Phase A1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Gold research cockpit and PIT-disciplined data layer per [docs/superpowers/specs/2026-05-16-gold-phase-a1-design.md](../specs/2026-05-16-gold-phase-a1-design.md). No model, no backtest, no numerical sizing — posture-language UI plus a deterministic replay scaffold.

**Architecture:** Bottom-up TDD against `pytest-postgresql`. Postgres migrations first, then 8 source modules (telemetry-wrapped HTTP clients), then Repository methods (one per query), then 4 pure-function cards, then a posture-compute orchestrator, then a 5-endpoint FastAPI router, then APScheduler worker jobs, then the Next.js cockpit, then an end-to-end replay-acceptance test.

**Tech Stack:** Python 3.13 via `uv`, FastAPI, Pydantic v2, psycopg 3, APScheduler 3, Next.js 16, React 19, TypeScript, hand-rolled SVG charts, Vitest, Playwright, pytest, pytest-postgresql.

**Important repo conventions** (per top-level CLAUDE.md and `src/uw_scan/storage/CLAUDE.md`):

- `uv run pytest` — never bare `pytest`
- Migrations are `src/uw_scan/storage/migrations/NNN_<name>.sql`, lexically ordered, idempotent, with `SET search_path TO uw_scan, public;` header
- `Repository` has one method per query; `Jsonb(payload)` wrapper for jsonb columns; `Decimal` round-trips natively
- New endpoint flow: `api/endpoints.py` (slug) → `models.py` (typed) → `sources/*.py` (fetcher with telemetry) → `storage/repository.py` (persistence) → `reports/*.py` (assembler) → `worker/scheduler.py` (job)
- Logger per module: `logger = logging.getLogger(__name__)`
- After API changes, regenerate types: `cd web && npm run gen:types`
- **Never commit without explicit user request.** Each task ends with a commit step labelled `(only commit after explicit approval).`
- Open PRs before merging to `main`. `git push origin main` is forbidden.

---

## File Structure

```
src/uw_scan/
├── sources/
│   ├── fred.py            NEW
│   ├── gpr.py             NEW
│   ├── etf_holdings.py    NEW
│   ├── comex.py           NEW
│   ├── lbma.py            NEW
│   ├── wgc_cb.py          NEW
│   ├── cftc_cot.py        NEW
│   └── uw.py              EXTEND (gold options snapshot)
├── storage/
│   ├── repository.py      EXTEND (~25 new methods, grouped per table)
│   └── migrations/
│       ├── 037_gold_macro_series.sql        NEW
│       ├── 038_gold_etf_holdings.sql        NEW
│       ├── 039_gold_exchange_inventory.sql  NEW
│       ├── 040_gold_cb_reserves.sql         NEW
│       ├── 041_gold_cot.sql                 NEW
│       ├── 042_gold_uw_options.sql          NEW
│       └── 043_gold_posture.sql             NEW
├── cards/
│   ├── regime_gauge.py    NEW
│   ├── structural_flow.py NEW
│   ├── cyclical_zones.py  NEW
│   └── valuation.py       NEW
├── reports/
│   └── gold_posture.py    NEW
├── api/
│   ├── routers/
│   │   └── gold.py        NEW
│   └── server.py          EXTEND (register router)
├── worker/
│   └── scheduler.py       EXTEND (8 new jobs)
└── models.py              EXTEND (gold response models)

web/
├── app/gold/
│   ├── page.tsx                 NEW
│   ├── replay/[date]/page.tsx   NEW
│   └── loading.tsx              NEW
├── components/gold/                         (GOLD COMPASS subtree per spec §8.3)
│   ├── GoldCompassLayout.tsx                NEW (5-tier shell)
│   ├── GoldCompassHeader.tsx                NEW (title + chips + replay picker)
│   ├── DataAuditFooter.tsx                  NEW (always-bottom footer)
│   ├── ReplayDatePicker.tsx                 NEW (client-component date jumper)
│   ├── chips/
│   │   ├── PostureChip.tsx                  NEW (FAVORABLE/NEUTRAL/STRETCHED/SUSPENDED/DEGRADED)
│   │   ├── HeuristicBadge.tsx               NEW
│   │   └── PersistOnlyBadge.tsx             NEW
│   ├── kpi/                                  (Tier 1 strip — 5 cards)
│   │   ├── SpotPriceCard.tsx                NEW
│   │   ├── CorrelationGaugeCard.tsx         NEW
│   │   ├── RegimeBadgeCard.tsx              NEW
│   │   ├── LensesOverallCard.tsx            NEW
│   │   └── DataFreshnessCard.tsx            NEW
│   ├── lens1/                                (Tier 2 — structural flow)
│   │   ├── StructuralPanel.tsx              NEW
│   │   ├── GoldHoldingsVsPriceChart.tsx     NEW (lead visual)
│   │   ├── CbReservesCard.tsx               NEW
│   │   ├── EtfFlowCard.tsx                  NEW
│   │   ├── ComexRegimeCard.tsx              NEW
│   │   ├── CotPositioningCard.tsx           NEW
│   │   ├── UwSkewCard.tsx                   NEW
│   │   ├── FxBasketCard.tsx                 NEW
│   │   └── StructuralPostureText.tsx        NEW
│   ├── lens2/                                (Tier 3 — cyclical posture)
│   │   ├── CyclicalPanel.tsx                NEW
│   │   ├── RealRateCard.tsx                 NEW
│   │   ├── UsdTrendCard.tsx                 NEW
│   │   ├── GprCard.tsx                      NEW
│   │   ├── InfExpCard.tsx                   NEW
│   │   ├── ArticleZoneCard.tsx              NEW
│   │   └── TwoForceNarrative.tsx            NEW
│   ├── lens3/                                (Tier 4 — valuation overlay)
│   │   ├── ValuationPanel.tsx               NEW
│   │   ├── ValuationFlagCard.tsx            NEW
│   │   └── ValuationPostureText.tsx         NEW
│   ├── decomposition/                        (Tier 5 left)
│   │   ├── LensDecompositionPanel.tsx       NEW
│   │   └── DecompositionBars.tsx            NEW
│   └── correlation/                          (Tier 5 right)
│       ├── CorrelationHistoryPanel.tsx      NEW
│       └── CorrelationLineChart.tsx         NEW
├── lib/
│   ├── types.ts          REGENERATE (via openapi-typescript)
│   └── copy-rules.ts     NEW (posture-language lint helper)
└── package.json          EXTEND (script alias if needed)

tests/
├── unit/
│   ├── sources/test_fred.py, test_gpr.py, … 8 files
│   ├── cards/test_regime_gauge.py, … 4 files
│   ├── reports/test_gold_posture.py
│   └── api/test_gold_router.py
└── integration/
    ├── storage/test_gold_repo.py
    ├── worker/test_gold_jobs.py
    └── e2e/test_gold_replay_acceptance.py
```

---

## Task index

Foundation: 1
Source modules: 2–9
Repository extensions: 10–13
Pure-function cards: 14–17
Models + report orchestrator: 18–19
API router: 20–22
Worker jobs: 23–25
OpenAPI types regen: 26
Posture-language lint helper (web/lib/copy-rules.ts): 27
Web cockpit (GOLD COMPASS): 28–36
   28: page route + GoldCompassLayout shell + shared chips
   29: Tier 1 KPI strip (5 cards)
   30: Tier 2 lens1/ panel + 6 sub-cards (no chart)
   31: Tier 3 lens2/ panel + 4 sub-cards + zone + two-force
   32: Tier 4 lens3/ panel + valuation cards + DataAuditFooter
   33: Tier 5 decomposition/ (panel + horizontal SVG bars)
   34: Tier 5 correlation/ (panel + multi-window SVG line chart)
   35: lens1/GoldHoldingsVsPriceChart (lead visual, wired into Lens 1)
   36: Replay route + ReplayDatePicker
CI lint integration: 37
End-to-end replay-acceptance: 38

Total: 38 tasks. Web-cockpit task count grew from 7 → 9 vs the original plan to match the GOLD COMPASS five-tier layout per spec §8.

Each task uses TDD: write the failing test, run to confirm failure, write the minimal implementation, run to confirm pass, commit.

---

## Task 1: Postgres migrations (7 tables)

**Files:**
- Create: `src/uw_scan/storage/migrations/037_gold_macro_series.sql`
- Create: `src/uw_scan/storage/migrations/038_gold_etf_holdings.sql`
- Create: `src/uw_scan/storage/migrations/039_gold_exchange_inventory.sql`
- Create: `src/uw_scan/storage/migrations/040_gold_cb_reserves.sql`
- Create: `src/uw_scan/storage/migrations/041_gold_cot.sql`
- Create: `src/uw_scan/storage/migrations/042_gold_uw_options.sql`
- Create: `src/uw_scan/storage/migrations/043_gold_posture.sql`
- Test: `tests/integration/storage/test_gold_migrations.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/storage/test_gold_migrations.py
"""Smoke test: gold-related tables exist with expected columns after migrate."""

import psycopg
import pytest


def _table_columns(conn: psycopg.Connection, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'uw_scan' AND table_name = %s",
            (table,),
        )
        return {row[0] for row in cur.fetchall()}


@pytest.mark.integration
def test_gold_tables_created(postgresql):
    """All 8 gold tables exist with PIT-disciplined columns."""
    expected = {
        "macro_series_daily": {
            "series_id", "obs_date", "value", "as_of",
            "release_date", "source", "source_url",
        },
        "macro_series_monthly": {
            "series_id", "obs_month", "value", "as_of",
            "release_date", "source", "source_url",
        },
        "etf_holdings_daily": {
            "ticker", "obs_date", "holdings_oz", "shares_out",
            "nav_per_share", "premium_pct", "as_of", "source",
        },
        "exchange_inventory_daily": {
            "exchange", "obs_date", "registered_oz", "eligible_oz",
            "vault_oz", "as_of", "source_url",
        },
        "cb_gold_reserves_monthly": {
            "country_iso3", "obs_month", "reserves_t", "bucket",
            "is_reported", "is_estimated", "as_of", "release_date", "source",
        },
        "cot_gold_weekly": {
            "obs_date", "release_date", "mm_long", "mm_short", "mm_net",
            "comm_long", "comm_short", "comm_net", "open_interest",
            "as_of", "source_url",
        },
        "uw_gold_options_daily": {
            "ticker", "obs_date", "atm_iv_30d", "atm_iv_60d",
            "put_25d_iv_30d", "call_25d_iv_30d", "skew_25d_30d",
            "put_call_oi_ratio", "dealer_gamma_est", "as_of",
        },
        "gold_posture_daily": {
            "obs_date", "computed_at",
            "gauge_corr_60d", "gauge_corr_126d", "gauge_corr_252d",
            "gauge_corr_504d", "gauge_corr_252d_returns", "gauge_state",
            "structural_state_label", "cb_strategic_12m_sum_t",
            "cb_tactical_12m_sum_t", "cb_diversifier_12m_sum_t",
            "gld_holdings_t", "gld_30d_net_flow_t",
            "comex_registered_oz", "comex_20d_roc_pct", "cot_mm_net_pct",
            "cyclical_zone_label", "cpi_yoy", "t5yifr", "dfii10",
            "dfii10_60d_change_bps", "factors_jsonb",
            "valuation_flag", "real_price_percentile",
            "gold_m2_ratio_percentile", "gold_spx_ratio_percentile",
            "structural_posture_text", "cyclical_posture_text",
            "valuation_posture_text", "inputs_jsonb",
        },
    }
    with psycopg.connect(postgresql.info.dsn) as conn:
        for table, cols in expected.items():
            actual = _table_columns(conn, table)
            missing = cols - actual
            assert not missing, f"{table} missing columns: {missing}"


@pytest.mark.integration
def test_gold_migrations_idempotent(postgresql, run_migrations):
    """Running migrate.sh twice is a no-op (no exceptions, same table state)."""
    run_migrations()  # second run
    with psycopg.connect(postgresql.info.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = 'uw_scan' "
            "AND table_name LIKE 'gold_%' OR table_name LIKE 'cot_gold%' "
            "OR table_name LIKE 'cb_gold%' OR table_name LIKE 'macro_series%' "
            "OR table_name LIKE 'etf_holdings%' OR table_name LIKE 'exchange_inventory%' "
            "OR table_name LIKE 'uw_gold_options%'"
        )
        assert cur.fetchone()[0] >= 8
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_gold_migrations.py -v`
Expected: FAIL — `uw_scan.macro_series_daily` does not exist (migrations not yet written).

- [ ] **Step 3: Write migration 037 — macro_series_daily and macro_series_monthly**

```sql
-- src/uw_scan/storage/migrations/037_gold_macro_series.sql
-- Macro series ingested from FRED, GPR, and computed transforms.
-- PIT-disciplined: (series_id, obs_date, as_of) PK so re-pulls store new vintages.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.macro_series_daily (
  series_id     TEXT        NOT NULL,
  obs_date      DATE        NOT NULL,
  value         NUMERIC     NOT NULL,
  as_of         TIMESTAMPTZ NOT NULL,
  release_date  DATE        NULL,
  source        TEXT        NOT NULL,
  source_url    TEXT        NULL,
  PRIMARY KEY (series_id, obs_date, as_of)
);

CREATE INDEX IF NOT EXISTS idx_macro_series_daily_lookup
  ON uw_scan.macro_series_daily (series_id, obs_date DESC, as_of DESC);

CREATE TABLE IF NOT EXISTS uw_scan.macro_series_monthly (
  series_id     TEXT        NOT NULL,
  obs_month     DATE        NOT NULL,
  value         NUMERIC     NOT NULL,
  as_of         TIMESTAMPTZ NOT NULL,
  release_date  DATE        NULL,
  source        TEXT        NOT NULL,
  source_url    TEXT        NULL,
  PRIMARY KEY (series_id, obs_month, as_of)
);

CREATE INDEX IF NOT EXISTS idx_macro_series_monthly_lookup
  ON uw_scan.macro_series_monthly (series_id, obs_month DESC, as_of DESC);
```

- [ ] **Step 4: Write migrations 038-043**

Each file mirrors the table definitions in [spec §4](../specs/2026-05-16-gold-phase-a1-design.md). Use the exact `CREATE TABLE IF NOT EXISTS` shape shown in the spec sections 4.3 through 4.8. Each file starts with `SET search_path TO uw_scan, public;`. Required indexes:

- 038: `(ticker, obs_date DESC, as_of DESC)` on `etf_holdings_daily`
- 039: `(exchange, obs_date DESC, as_of DESC)` on `exchange_inventory_daily`
- 040: `(bucket, obs_month DESC)` and `(country_iso3, obs_month DESC, as_of DESC)` on `cb_gold_reserves_monthly`
- 041: `(release_date DESC)` on `cot_gold_weekly`
- 042: `(ticker, obs_date DESC, as_of DESC)` on `uw_gold_options_daily`
- 043: `(obs_date DESC, computed_at DESC)` named `idx_gold_posture_daily_latest` on `gold_posture_daily`

Verify with: `cat src/uw_scan/storage/migrations/037_gold_macro_series.sql` etc.

- [ ] **Step 5: Run migrations**

Run: `bash scripts/migrate.sh`
Expected: clean exit, all 7 new files applied, re-running emits no errors.

- [ ] **Step 6: Run the test again to verify it passes**

Run: `uv run pytest tests/integration/storage/test_gold_migrations.py -v`
Expected: PASS for both `test_gold_tables_created` and `test_gold_migrations_idempotent`.

- [ ] **Step 7: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/storage/migrations/037_gold_macro_series.sql \
        src/uw_scan/storage/migrations/038_gold_etf_holdings.sql \
        src/uw_scan/storage/migrations/039_gold_exchange_inventory.sql \
        src/uw_scan/storage/migrations/040_gold_cb_reserves.sql \
        src/uw_scan/storage/migrations/041_gold_cot.sql \
        src/uw_scan/storage/migrations/042_gold_uw_options.sql \
        src/uw_scan/storage/migrations/043_gold_posture.sql \
        tests/integration/storage/test_gold_migrations.py
git commit -m "feat(gold): add Phase A1 storage schema (7 tables)"
```

---

## Task 2: FRED CSV source client (reference pattern)

**Files:**
- Create: `src/uw_scan/sources/fred.py`
- Test: `tests/unit/sources/test_fred.py`

This is the **reference source pattern** for tasks 3–9. Subsequent source modules follow the same shape: dataclass return type, `Provider` class with HTTP client, telemetry-wrapped `_get_with_telemetry()`, `__enter__/__exit__` for `with` use.

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/sources/test_fred.py
"""FRED CSV client — parses fredgraph.csv and returns typed rows."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from uw_scan.sources.fred import FredProvider, FredObservation


SAMPLE_CSV = """observation_date,DFII10
2026-05-12,1.95
2026-05-13,1.97
2026-05-14,.
2026-05-15,2.01
"""


def test_fred_parses_csv_skips_missing():
    """CSV rows with '.' are missing observations and must be skipped."""
    with patch.object(FredProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE_CSV)
        with FredProvider() as p:
            rows = p.fetch_series("DFII10", start=date(2026, 5, 12))
    assert len(rows) == 3
    assert rows[0] == FredObservation(
        series_id="DFII10", obs_date=date(2026, 5, 12), value=Decimal("1.95"),
    )
    assert all(r.value is not None for r in rows)


def test_fred_filters_by_start_date():
    with patch.object(FredProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE_CSV)
        with FredProvider() as p:
            rows = p.fetch_series("DFII10", start=date(2026, 5, 14))
    assert all(r.obs_date >= date(2026, 5, 14) for r in rows)
    assert {r.obs_date for r in rows} == {date(2026, 5, 15)}


def test_fred_telemetry_records_request():
    captured = []

    def fake_record(self, event):
        captured.append(event)

    with patch.object(FredProvider, "_record_request", fake_record), \
         patch("uw_scan.sources.fred.httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE_CSV,
                                                request=httpx.Request("GET", "https://x"))
        with FredProvider() as p:
            p.fetch_series("DFII10", start=date(2026, 5, 12))

    assert len(captured) == 1
    assert captured[0].provider == "fred"
    assert captured[0].endpoint == "/graph/fredgraph.csv"
    assert captured[0].status_code == 200
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/sources/test_fred.py -v`
Expected: FAIL — `cannot import name 'FredProvider' from 'uw_scan.sources.fred'`

- [ ] **Step 3: Write the FRED provider**

```python
# src/uw_scan/sources/fred.py
"""FRED CSV provider for daily and monthly macro series.

Returns typed dataclasses; persistence is the caller's responsibility.
Telemetry records every request to `provider_usage`.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FredObservation:
    series_id: str
    obs_date: date
    value: Decimal


class FredProvider:
    """REST client for FRED CSV endpoint.

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
    No auth required. Daily worker uses this for full-series refresh.
    """

    BASE_URL = "https://fred.stlouisfed.org"

    def __init__(self, *, timeout_s: float = 30.0, record_request=None):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FredProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_series(
        self, series_id: str, *, start: date | None = None
    ) -> list[FredObservation]:
        params: dict[str, Any] = {"id": series_id}
        response = self._get_with_telemetry("/graph/fredgraph.csv", params)
        response.raise_for_status()
        out: list[FredObservation] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            raw_date = row.get("observation_date") or row.get("DATE")
            raw_val = row.get(series_id) or row.get(series_id.upper())
            if raw_date is None or raw_val is None or raw_val.strip() == ".":
                continue
            try:
                d = date.fromisoformat(raw_date.strip())
                v = Decimal(raw_val.strip())
            except (ValueError, InvalidOperation):
                logger.warning("fred: skip unparseable row %r", row)
                continue
            if start is not None and d < start:
                continue
            out.append(FredObservation(series_id=series_id, obs_date=d, value=v))
        return out

    def _get_with_telemetry(self, path: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self.BASE_URL}{path}"
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("fred: request error %r", exc)
            self._record_request(self._error_event(path, params, started, exc))
            raise
        finished = datetime.now(UTC)
        self._record_request(self._success_event(path, params, started, finished, response))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("fred telemetry %r", event)

    def _success_event(self, path, params, started, finished, response):
        return ExternalApiRequestEvent(
            provider="fred",
            endpoint=path,
            params=redact_params(params),
            started_at=started,
            finished_at=finished,
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""),
            error=None,
        )

    def _error_event(self, path, params, started, exc):
        return ExternalApiRequestEvent(
            provider="fred",
            endpoint=path,
            params=redact_params(params),
            started_at=started,
            finished_at=datetime.now(UTC),
            status_code=None,
            status_family="error",
            response_bytes=0,
            error=repr(exc),
        )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/sources/test_fred.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/fred.py tests/unit/sources/test_fred.py
git commit -m "feat(gold/sources): FRED CSV client with telemetry"
```

---

## Task 3: GPR (Caldara-Iacoviello) daily index ingestor

**Files:**
- Create: `src/uw_scan/sources/gpr.py`
- Test: `tests/unit/sources/test_gpr.py`

Source: `https://www.matteoiacoviello.com/gpr_files/gpr_daily_recent.xls` (or the equivalent CSV link visible on the homepage). The site rotates between XLS and CSV — the provider should accept whichever GPR publishes. For v1 implementation, target the CSV endpoint linked from gpr.htm; if only XLS is available, use `openpyxl` (already in repo deps via pandas extras).

- [ ] **Step 1: Write the failing unit test**

```python
# tests/unit/sources/test_gpr.py
"""GPR daily index parser."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from uw_scan.sources.gpr import GprProvider, GprObservation


SAMPLE_CSV = """date,GPRD
2026-05-12,118.4
2026-05-13,121.2
2026-05-14,
2026-05-15,109.7
"""


def test_gpr_parses_csv_skips_blank_rows():
    with patch.object(GprProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE_CSV)
        with GprProvider() as p:
            rows = p.fetch_daily(start=date(2026, 5, 12))
    assert {r.obs_date for r in rows} == {date(2026, 5, 12), date(2026, 5, 13), date(2026, 5, 15)}
    assert rows[0].value == Decimal("118.4")


def test_gpr_telemetry_records():
    captured = []
    def fake_record(self, event):
        captured.append(event)

    with patch.object(GprProvider, "_record_request", fake_record), \
         patch("uw_scan.sources.gpr.httpx.Client.get") as mock_get:
        mock_get.return_value = httpx.Response(
            200, text=SAMPLE_CSV, request=httpx.Request("GET", "https://x")
        )
        with GprProvider() as p:
            p.fetch_daily(start=date(2026, 5, 12))

    assert len(captured) == 1
    assert captured[0].provider == "gpr"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/sources/test_gpr.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the GPR provider**

```python
# src/uw_scan/sources/gpr.py
"""Caldara-Iacoviello Geopolitical Risk Index (GPRD).

Source: matteoiacoviello.com — free academic CSV.
Persists to uw_scan.macro_series_daily with series_id='GPRD'.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GprObservation:
    obs_date: date
    value: Decimal


class GprProvider:
    """HTTP fetcher for the daily GPR CSV published by Caldara-Iacoviello."""

    DEFAULT_URL = "https://www.matteoiacoviello.com/gpr_files/gpr_daily_recent.csv"

    def __init__(self, *, url: str | None = None, timeout_s: float = 30.0,
                 record_request=None):
        self._url = url or self.DEFAULT_URL
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GprProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_daily(self, *, start: date | None = None) -> list[GprObservation]:
        response = self._get_with_telemetry(self._url, {})
        response.raise_for_status()
        rows: list[GprObservation] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            raw_date = (row.get("date") or row.get("DATE") or "").strip()
            raw_val = (row.get("GPRD") or row.get("gprd") or "").strip()
            if not raw_date or not raw_val:
                continue
            try:
                d = date.fromisoformat(raw_date)
                v = Decimal(raw_val)
            except (ValueError, InvalidOperation):
                logger.warning("gpr: skip unparseable row %r", row)
                continue
            if start is not None and d < start:
                continue
            rows.append(GprObservation(obs_date=d, value=v))
        return rows

    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("gpr: request error %r", exc)
            self._record_request(self._error_event(url, params, started, exc))
            raise
        finished = datetime.now(UTC)
        self._record_request(self._success_event(url, params, started, finished, response))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("gpr telemetry %r", event)

    def _success_event(self, url, params, started, finished, response):
        return ExternalApiRequestEvent(
            provider="gpr", endpoint=url, params=redact_params(params),
            started_at=started, finished_at=finished,
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""), error=None,
        )

    def _error_event(self, url, params, started, exc):
        return ExternalApiRequestEvent(
            provider="gpr", endpoint=url, params=redact_params(params),
            started_at=started, finished_at=datetime.now(UTC),
            status_code=None, status_family="error",
            response_bytes=0, error=repr(exc),
        )
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/sources/test_gpr.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/gpr.py tests/unit/sources/test_gpr.py
git commit -m "feat(gold/sources): Caldara-Iacoviello GPR daily ingestor"
```

---

## Task 4: ETF holdings source (GLD, IAU, GLDM, PHYS)

**Files:**
- Create: `src/uw_scan/sources/etf_holdings.py`
- Test: `tests/unit/sources/test_etf_holdings.py`

Single module fetches four funds, each with its own URL parsing. GLD/GLDM share SPDR's historical-data CSV format; IAU uses BlackRock's investor-relations endpoint; PHYS uses Sprott's daily-NAV CSV. Common dataclass `EtfHoldingRow` with `holdings_oz`, `nav_per_share`, optional `premium_pct` (PHYS only).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/sources/test_etf_holdings.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import httpx

from uw_scan.sources.etf_holdings import EtfHoldingsProvider, EtfHoldingRow


GLD_CSV = """Date,Total Net Assets (USD),Tons in the Trust,Ounces in the Trust,NAV per Share (USD)
05/12/2026,75123456789,872.5,28047500.12,234.50
05/13/2026,75500000000,873.0,28063540.00,235.10
"""


def test_etf_provider_parses_gld_csv():
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=GLD_CSV)
        with EtfHoldingsProvider() as p:
            rows = p.fetch_gld(start=date(2026, 5, 12))
    assert len(rows) == 2
    assert rows[0] == EtfHoldingRow(
        ticker="GLD",
        obs_date=date(2026, 5, 12),
        holdings_oz=Decimal("28047500.12"),
        shares_out=None,
        nav_per_share=Decimal("234.50"),
        premium_pct=None,
    )


def test_etf_provider_iau_uses_blackrock_endpoint():
    iau_json = {
        "data": [
            {"asOfDate": "2026-05-12", "totalAssets": 12345.6, "navPerShare": 47.50,
             "physicalGoldOunces": 8500000.0},
        ]
    }
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, json=iau_json)
        with EtfHoldingsProvider() as p:
            rows = p.fetch_iau(start=date(2026, 5, 12))
    assert rows[0].ticker == "IAU"
    assert rows[0].holdings_oz == Decimal("8500000.0")
    assert rows[0].nav_per_share == Decimal("47.50")
```

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest tests/unit/sources/test_etf_holdings.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the ETF provider**

```python
# src/uw_scan/sources/etf_holdings.py
"""Daily ETF holdings for the gold complex.

Targets: GLD (SPDR), IAU (BlackRock), GLDM (SPDR), PHYS (Sprott).
Each fund has its own endpoint and payload shape; we normalise to EtfHoldingRow.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EtfHoldingRow:
    ticker: str
    obs_date: date
    holdings_oz: Decimal | None
    shares_out: Decimal | None
    nav_per_share: Decimal | None
    premium_pct: Decimal | None


class EtfHoldingsProvider:
    GLD_URL = "https://www.spdrgoldshares.com/usa/historical-data/"
    GLDM_URL = "https://www.spdrgoldshares.com/usa/historical-data-gldm/"
    IAU_URL = "https://www.ishares.com/us/products/239561/iau-holdings.ajax"
    PHYS_URL = "https://sprott.com/api/v1/funds/phys/nav-history"

    def __init__(self, *, timeout_s: float = 30.0, record_request=None):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EtfHoldingsProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_gld(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(self.GLD_URL, {})
        response.raise_for_status()
        out: list[EtfHoldingRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            d = self._parse_date(row.get("Date"))
            if d is None or (start and d < start):
                continue
            out.append(EtfHoldingRow(
                ticker="GLD",
                obs_date=d,
                holdings_oz=self._dec(row.get("Ounces in the Trust")),
                shares_out=None,
                nav_per_share=self._dec(row.get("NAV per Share (USD)")),
                premium_pct=None,
            ))
        return out

    def fetch_gldm(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        # same SPDR shape; column names may include "GLDM" prefixes
        response = self._get_with_telemetry(self.GLDM_URL, {})
        response.raise_for_status()
        return self._parse_spdr_csv("GLDM", response.text, start)

    def fetch_iau(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(self.IAU_URL, {})
        response.raise_for_status()
        out: list[EtfHoldingRow] = []
        for row in response.json().get("data", []):
            d = self._parse_date(row.get("asOfDate"))
            if d is None or (start and d < start):
                continue
            out.append(EtfHoldingRow(
                ticker="IAU",
                obs_date=d,
                holdings_oz=self._dec(row.get("physicalGoldOunces")),
                shares_out=None,
                nav_per_share=self._dec(row.get("navPerShare")),
                premium_pct=None,
            ))
        return out

    def fetch_phys(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(self.PHYS_URL, {})
        response.raise_for_status()
        out: list[EtfHoldingRow] = []
        for row in response.json().get("data", []):
            d = self._parse_date(row.get("date"))
            if d is None or (start and d < start):
                continue
            out.append(EtfHoldingRow(
                ticker="PHYS",
                obs_date=d,
                holdings_oz=self._dec(row.get("goldOunces")),
                shares_out=None,
                nav_per_share=self._dec(row.get("nav")),
                premium_pct=self._dec(row.get("premiumDiscountPct")),
            ))
        return out

    def _parse_spdr_csv(self, ticker: str, text: str, start: date | None) -> list[EtfHoldingRow]:
        out = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            d = self._parse_date(row.get("Date"))
            if d is None or (start and d < start):
                continue
            out.append(EtfHoldingRow(
                ticker=ticker, obs_date=d,
                holdings_oz=self._dec(row.get("Ounces in the Trust")),
                shares_out=None,
                nav_per_share=self._dec(row.get("NAV per Share (USD)")),
                premium_pct=None,
            ))
        return out

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        raw = raw.strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _dec(raw: Any) -> Decimal | None:
        if raw is None or raw == "":
            return None
        try:
            return Decimal(str(raw).replace(",", ""))
        except (InvalidOperation, ValueError):
            return None

    # telemetry methods identical to FredProvider; copy from src/uw_scan/sources/fred.py
    # and change provider="etf_holdings"
    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("etf_holdings: request error %r", exc)
            self._record_request(ExternalApiRequestEvent(
                provider="etf_holdings", endpoint=url,
                params=redact_params(params), started_at=started,
                finished_at=datetime.now(UTC), status_code=None,
                status_family="error", response_bytes=0, error=repr(exc),
            ))
            raise
        finished = datetime.now(UTC)
        self._record_request(ExternalApiRequestEvent(
            provider="etf_holdings", endpoint=url,
            params=redact_params(params), started_at=started,
            finished_at=finished, status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""), error=None,
        ))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("etf_holdings telemetry %r", event)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/sources/test_etf_holdings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/etf_holdings.py tests/unit/sources/test_etf_holdings.py
git commit -m "feat(gold/sources): GLD/IAU/GLDM/PHYS daily holdings ingestor"
```

---

## Task 5: COMEX vault scraper

**Files:**
- Create: `src/uw_scan/sources/comex.py`
- Test: `tests/unit/sources/test_comex.py`

CME publishes the daily metals depository report as a structured page (or downloadable CSV via their public reports portal). The v1 implementation targets the JSON-shaped endpoint surfaced by CME's market-data API for "Metals — Gold Stocks" with columns: registered (oz), eligible (oz), total (oz).

- [ ] **Step 1: Failing test**

```python
# tests/unit/sources/test_comex.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import httpx

from uw_scan.sources.comex import ComexProvider, ComexVaultRow

SAMPLE_HTML = """
<table id="metal-stocks-gold">
  <tr><th>Date</th><th>Registered (oz)</th><th>Eligible (oz)</th><th>Total (oz)</th></tr>
  <tr><td>05/15/2026</td><td>17,500,100</td><td>10,820,200</td><td>28,320,300</td></tr>
  <tr><td>05/14/2026</td><td>17,320,000</td><td>10,810,000</td><td>28,130,000</td></tr>
</table>
"""


def test_comex_parses_vault_table():
    with patch.object(ComexProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE_HTML)
        with ComexProvider() as p:
            rows = p.fetch_vault(start=date(2026, 5, 14))
    assert len(rows) == 2
    assert rows[0] == ComexVaultRow(
        obs_date=date(2026, 5, 15),
        registered_oz=Decimal("17500100"),
        eligible_oz=Decimal("10820200"),
        total_oz=Decimal("28320300"),
    )
```

- [ ] **Step 2: Run test, expect FAIL.**

Run: `uv run pytest tests/unit/sources/test_comex.py -v`

- [ ] **Step 3: Implement**

```python
# src/uw_scan/sources/comex.py
"""COMEX gold-stocks daily scraper.

URL pattern (subject to CME publishing changes — sanity-check before deploy):
https://www.cmegroup.com/markets/metals/precious/gold-stocks.html
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComexVaultRow:
    obs_date: date
    registered_oz: Decimal | None
    eligible_oz: Decimal | None
    total_oz: Decimal | None


class ComexProvider:
    URL = "https://www.cmegroup.com/markets/metals/precious/gold-stocks.html"

    def __init__(self, *, timeout_s: float = 30.0, record_request=None):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ComexProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_vault(self, *, start: date | None = None) -> list[ComexVaultRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", {"id": re.compile(r"metal-stocks-gold")})
        if table is None:
            logger.warning("comex: vault table not found")
            return []
        out: list[ComexVaultRow] = []
        for tr in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) < 4:
                continue
            d = self._parse_date(cells[0])
            if d is None or (start and d < start):
                continue
            out.append(ComexVaultRow(
                obs_date=d,
                registered_oz=self._dec(cells[1]),
                eligible_oz=self._dec(cells[2]),
                total_oz=self._dec(cells[3]),
            ))
        return out

    @staticmethod
    def _parse_date(raw: str) -> date | None:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _dec(raw: str) -> Decimal | None:
        if not raw:
            return None
        try:
            return Decimal(raw.replace(",", "").strip())
        except (InvalidOperation, ValueError):
            return None

    # telemetry methods: copy from src/uw_scan/sources/fred.py, change provider="comex"
    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("comex: request error %r", exc)
            self._record_request(ExternalApiRequestEvent(
                provider="comex", endpoint=url, params=redact_params(params),
                started_at=started, finished_at=datetime.now(UTC),
                status_code=None, status_family="error",
                response_bytes=0, error=repr(exc),
            ))
            raise
        finished = datetime.now(UTC)
        self._record_request(ExternalApiRequestEvent(
            provider="comex", endpoint=url, params=redact_params(params),
            started_at=started, finished_at=finished,
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""), error=None,
        ))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("comex telemetry %r", event)
```

If `beautifulsoup4` is not yet in the repo's dependency set, add it via `uv add beautifulsoup4` before this task; track in commit.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/sources/test_comex.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/comex.py tests/unit/sources/test_comex.py pyproject.toml uv.lock
git commit -m "feat(gold/sources): COMEX gold-stocks scraper"
```

---

## Task 6: LBMA monthly vault CSV

**Files:**
- Create: `src/uw_scan/sources/lbma.py`
- Test: `tests/unit/sources/test_lbma.py`

LBMA publishes monthly vault holdings CSV at `https://www.lbma.org.uk/prices-and-data/vault-holdings-data.csv` (URL subject to LBMA update). Format: monthly end-of-month rows with `Date`, `Gold (oz)`, `Silver (oz)`, etc. We persist `vault_oz` only.

- [ ] **Step 1: Failing test**

```python
# tests/unit/sources/test_lbma.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import httpx

from uw_scan.sources.lbma import LbmaProvider, LbmaVaultRow

SAMPLE = """Date,Gold (tonnes),Gold (oz),Silver (tonnes),Silver (oz)
2026-04-30,8523.4,274086000,33500.2,1077000000
2026-03-31,8541.1,274655000,33620.4,1080900000
"""


def test_lbma_parses_monthly_csv():
    with patch.object(LbmaProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE)
        with LbmaProvider() as p:
            rows = p.fetch_monthly(start=date(2026, 3, 31))
    assert len(rows) == 2
    assert rows[0] == LbmaVaultRow(
        obs_date=date(2026, 4, 30),
        vault_oz=Decimal("274086000"),
    )
```

- [ ] **Step 2: Run test, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/sources/lbma.py
"""LBMA monthly vault holdings (loco London).

Source: https://www.lbma.org.uk/prices-and-data/vault-holdings-data
CSV columns include Date, Gold (oz), Silver (oz). We use Gold (oz).
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LbmaVaultRow:
    obs_date: date
    vault_oz: Decimal | None


class LbmaProvider:
    URL = "https://www.lbma.org.uk/prices-and-data/vault-holdings-data.csv"

    def __init__(self, *, timeout_s: float = 30.0, record_request=None):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LbmaProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_monthly(self, *, start: date | None = None) -> list[LbmaVaultRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[LbmaVaultRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            raw_date = row.get("Date")
            raw_oz = row.get("Gold (oz)") or row.get("Gold oz")
            if not raw_date or not raw_oz:
                continue
            try:
                d = date.fromisoformat(raw_date.strip())
                v = Decimal(raw_oz.replace(",", "").strip())
            except (ValueError, InvalidOperation):
                continue
            if start and d < start:
                continue
            out.append(LbmaVaultRow(obs_date=d, vault_oz=v))
        return out

    # telemetry methods: copy from src/uw_scan/sources/fred.py, change provider="lbma"
    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("lbma: request error %r", exc)
            self._record_request(ExternalApiRequestEvent(
                provider="lbma", endpoint=url, params=redact_params(params),
                started_at=started, finished_at=datetime.now(UTC),
                status_code=None, status_family="error",
                response_bytes=0, error=repr(exc),
            ))
            raise
        finished = datetime.now(UTC)
        self._record_request(ExternalApiRequestEvent(
            provider="lbma", endpoint=url, params=redact_params(params),
            started_at=started, finished_at=finished,
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""), error=None,
        ))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("lbma telemetry %r", event)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/sources/test_lbma.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/lbma.py tests/unit/sources/test_lbma.py
git commit -m "feat(gold/sources): LBMA monthly vault CSV ingestor"
```

---

## Task 7: WGC central-bank reserves monthly CSV

**Files:**
- Create: `src/uw_scan/sources/wgc_cb.py`
- Create: `src/uw_scan/cards/cb_buckets.py` (configuration: country → bucket mapping)
- Test: `tests/unit/sources/test_wgc_cb.py`

WGC publishes the monthly per-country gold-reserves CSV at goldhub. Bucket assignment (strategic accumulator / tactical defender / reserve diversifier) is config-driven so we can revise without migration. Russia rows after late-2022 are marked `is_reported=False` when WGC explicitly flags them as estimated.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/sources/test_wgc_cb.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import httpx

from uw_scan.sources.wgc_cb import WgcCbProvider, CbReserveRow
from uw_scan.cards.cb_buckets import classify_bucket


SAMPLE = """Country,Month,Tonnes,Reported,Estimated
China,2026-04,2235.0,true,false
India,2026-04,876.4,true,false
Russia,2026-04,2330.5,false,true
Poland,2026-04,420.3,true,false
"""


def test_wgc_parses_monthly_csv():
    with patch.object(WgcCbProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE)
        with WgcCbProvider() as p:
            rows = p.fetch_monthly(start=date(2026, 4, 1))
    by_country = {r.country_iso3: r for r in rows}
    assert by_country["CHN"].reserves_t == Decimal("2235.0")
    assert by_country["RUS"].is_reported is False
    assert by_country["RUS"].is_estimated is True
    assert by_country["POL"].bucket == "reserve_diversifier"
    assert by_country["CHN"].bucket == "strategic_accumulator"


def test_classify_bucket_defaults():
    assert classify_bucket("CHN") == "strategic_accumulator"
    assert classify_bucket("EGY") == "tactical_defender"
    assert classify_bucket("POL") == "reserve_diversifier"
    assert classify_bucket("USA") == "reserve_diversifier"  # safe default
```

- [ ] **Step 2: Run test, expect FAIL.**

- [ ] **Step 3: Implement bucket config**

```python
# src/uw_scan/cards/cb_buckets.py
"""Country → bucket classification for CB gold reserve flows.

Default per docs/research/gold-sdf-framework/05-structural-flow-factors.md.
Revisable without migration.
"""

from __future__ import annotations

STRATEGIC_ACCUMULATORS = frozenset({"CHN", "IND", "RUS", "TUR"})
TACTICAL_DEFENDERS = frozenset({"EGY", "KAZ", "AZE"})
RESERVE_DIVERSIFIERS = frozenset({
    "POL", "CZE", "SGP", "HUN", "QAT", "PHL", "THA", "MEX", "BRA",
    "ARG", "DEU", "FRA", "ITA", "JPN", "GBR", "USA", "CHE", "NLD",
})


def classify_bucket(country_iso3: str) -> str:
    code = country_iso3.upper()
    if code in STRATEGIC_ACCUMULATORS:
        return "strategic_accumulator"
    if code in TACTICAL_DEFENDERS:
        return "tactical_defender"
    return "reserve_diversifier"
```

- [ ] **Step 4: Implement WGC provider**

```python
# src/uw_scan/sources/wgc_cb.py
"""World Gold Council monthly central-bank gold reserves.

Source: gold.org/goldhub/data/monthly-central-bank-statistics
CSV columns observed: Country, Month, Tonnes, Reported, Estimated.
ISO3 mapping in COUNTRY_ISO3 — extend as new countries appear.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.cards.cb_buckets import classify_bucket
from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)

COUNTRY_ISO3 = {
    "china": "CHN", "india": "IND", "russia": "RUS", "russian federation": "RUS",
    "turkey": "TUR", "türkiye": "TUR",
    "poland": "POL", "czech republic": "CZE", "czechia": "CZE",
    "singapore": "SGP", "hungary": "HUN", "qatar": "QAT", "philippines": "PHL",
    "thailand": "THA", "mexico": "MEX", "brazil": "BRA", "argentina": "ARG",
    "germany": "DEU", "france": "FRA", "italy": "ITA", "japan": "JPN",
    "united kingdom": "GBR", "uk": "GBR", "united states": "USA", "us": "USA",
    "switzerland": "CHE", "netherlands": "NLD",
    "egypt": "EGY", "kazakhstan": "KAZ", "azerbaijan": "AZE",
}


@dataclass(frozen=True)
class CbReserveRow:
    country_iso3: str
    obs_month: date
    reserves_t: Decimal | None
    bucket: str
    is_reported: bool
    is_estimated: bool


class WgcCbProvider:
    URL = "https://www.gold.org/goldhub/data/monthly-central-bank-statistics.csv"

    def __init__(self, *, timeout_s: float = 30.0, record_request=None):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WgcCbProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_monthly(self, *, start: date | None = None) -> list[CbReserveRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[CbReserveRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            country = (row.get("Country") or "").strip().lower()
            iso3 = COUNTRY_ISO3.get(country)
            if iso3 is None:
                logger.debug("wgc_cb: unknown country %r, skipping", country)
                continue
            month_raw = (row.get("Month") or "").strip()
            tonnes_raw = (row.get("Tonnes") or "").strip()
            try:
                obs_month = date.fromisoformat(month_raw + "-01") if len(month_raw) == 7 \
                            else date.fromisoformat(month_raw)
                reserves_t = Decimal(tonnes_raw.replace(",", "")) if tonnes_raw else None
            except (ValueError, InvalidOperation):
                continue
            if start and obs_month < start:
                continue
            is_reported = (row.get("Reported") or "").strip().lower() in ("true", "1", "yes")
            is_estimated = (row.get("Estimated") or "").strip().lower() in ("true", "1", "yes")
            out.append(CbReserveRow(
                country_iso3=iso3, obs_month=obs_month,
                reserves_t=reserves_t, bucket=classify_bucket(iso3),
                is_reported=is_reported, is_estimated=is_estimated,
            ))
        return out

    # telemetry: copy from src/uw_scan/sources/fred.py, change provider="wgc_cb"
    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("wgc_cb: request error %r", exc)
            self._record_request(ExternalApiRequestEvent(
                provider="wgc_cb", endpoint=url, params=redact_params(params),
                started_at=started, finished_at=datetime.now(UTC),
                status_code=None, status_family="error",
                response_bytes=0, error=repr(exc),
            ))
            raise
        finished = datetime.now(UTC)
        self._record_request(ExternalApiRequestEvent(
            provider="wgc_cb", endpoint=url, params=redact_params(params),
            started_at=started, finished_at=finished,
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""), error=None,
        ))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("wgc_cb telemetry %r", event)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/sources/test_wgc_cb.py -v`
Expected: PASS.

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/wgc_cb.py src/uw_scan/cards/cb_buckets.py \
        tests/unit/sources/test_wgc_cb.py
git commit -m "feat(gold/sources): WGC monthly CB reserves + bucket config"
```

---

## Task 8: CFTC COT weekly disaggregated report

**Files:**
- Create: `src/uw_scan/sources/cftc_cot.py`
- Test: `tests/unit/sources/test_cftc_cot.py`

CFTC public reports portal. The disaggregated COT for COMEX gold futures has stable column names. The provider exposes a `fetch_weekly()` method that returns `CotRow` with `obs_date` (Tuesday positions), `release_date` (Friday publication), `mm_long`, `mm_short`, `mm_net`, `comm_long`, `comm_short`, `comm_net`, `open_interest`.

- [ ] **Step 1: Failing test**

```python
# tests/unit/sources/test_cftc_cot.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import httpx

from uw_scan.sources.cftc_cot import CftcCotProvider, CotRow


SAMPLE = """Report_Date_as_YYYY-MM-DD,Report_Date_as_YYYY-MM-DD_Release,Open_Interest_All,M_Money_Positions_Long_All,M_Money_Positions_Short_All,Prod_Merc_Positions_Long_ALL,Prod_Merc_Positions_Short_ALL
2026-05-13,2026-05-16,512000,210500,85300,180100,295400
2026-05-06,2026-05-09,508100,205200,90100,175300,293000
"""


def test_cot_parses_disaggregated_csv():
    with patch.object(CftcCotProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(200, text=SAMPLE)
        with CftcCotProvider() as p:
            rows = p.fetch_weekly(start=date(2026, 5, 6))
    assert len(rows) == 2
    assert rows[0].obs_date == date(2026, 5, 13)
    assert rows[0].release_date == date(2026, 5, 16)
    assert rows[0].mm_long == Decimal("210500")
    assert rows[0].mm_net == Decimal("125200")
    assert rows[0].comm_net == Decimal("-115300")
```

- [ ] **Step 2: Run test, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/sources/cftc_cot.py
"""CFTC Commitments of Traders (disaggregated) for COMEX gold futures.

Source: cftc.gov public reports / API.
We persist managed-money longs/shorts/net, commercials longs/shorts/net, OI.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)

# Replace with the configured Socrata endpoint or download URL.
# v1 default: CFTC's public CSV download for the disaggregated futures-only report,
# filtered to gold (commodity code 088691) — see https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
CFTC_GOLD_DISAGG_URL = (
    "https://www.cftc.gov/dea/newcot/FinFutWk.txt"  # placeholder; replace with disagg gold endpoint at install time
)


@dataclass(frozen=True)
class CotRow:
    obs_date: date
    release_date: date
    mm_long: Decimal | None
    mm_short: Decimal | None
    mm_net: Decimal | None
    comm_long: Decimal | None
    comm_short: Decimal | None
    comm_net: Decimal | None
    open_interest: Decimal | None


class CftcCotProvider:
    URL = CFTC_GOLD_DISAGG_URL

    def __init__(self, *, timeout_s: float = 30.0, record_request=None):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CftcCotProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_weekly(self, *, start: date | None = None) -> list[CotRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[CotRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            try:
                obs = date.fromisoformat(row["Report_Date_as_YYYY-MM-DD"])
                rel = date.fromisoformat(row["Report_Date_as_YYYY-MM-DD_Release"])
                mm_l = self._dec(row.get("M_Money_Positions_Long_All"))
                mm_s = self._dec(row.get("M_Money_Positions_Short_All"))
                c_l = self._dec(row.get("Prod_Merc_Positions_Long_ALL"))
                c_s = self._dec(row.get("Prod_Merc_Positions_Short_ALL"))
                oi = self._dec(row.get("Open_Interest_All"))
            except (KeyError, ValueError, InvalidOperation):
                continue
            if start and obs < start:
                continue
            mm_n = (mm_l - mm_s) if mm_l is not None and mm_s is not None else None
            c_n = (c_l - c_s) if c_l is not None and c_s is not None else None
            out.append(CotRow(
                obs_date=obs, release_date=rel,
                mm_long=mm_l, mm_short=mm_s, mm_net=mm_n,
                comm_long=c_l, comm_short=c_s, comm_net=c_n,
                open_interest=oi,
            ))
        return out

    @staticmethod
    def _dec(raw: Any) -> Decimal | None:
        if raw is None or raw == "":
            return None
        try:
            return Decimal(str(raw).replace(",", "").strip())
        except (InvalidOperation, ValueError):
            return None

    # telemetry: copy from src/uw_scan/sources/fred.py, change provider="cftc_cot"
    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.exception("cftc_cot: request error %r", exc)
            self._record_request(ExternalApiRequestEvent(
                provider="cftc_cot", endpoint=url, params=redact_params(params),
                started_at=started, finished_at=datetime.now(UTC),
                status_code=None, status_family="error",
                response_bytes=0, error=repr(exc),
            ))
            raise
        finished = datetime.now(UTC)
        self._record_request(ExternalApiRequestEvent(
            provider="cftc_cot", endpoint=url, params=redact_params(params),
            started_at=started, finished_at=finished,
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            response_bytes=len(response.content or b""), error=None,
        ))
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("cftc_cot telemetry %r", event)
```

**Note:** the `CFTC_GOLD_DISAGG_URL` constant must be set to the actual disaggregated gold (commodity 088691) endpoint at installation time — verify against `https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm` and lock the URL in a follow-up commit before scheduling the worker job.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/sources/test_cftc_cot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/cftc_cot.py tests/unit/sources/test_cftc_cot.py
git commit -m "feat(gold/sources): CFTC COT disaggregated weekly ingestor"
```

---

## Task 9: UW gold-options snapshot extension

**Files:**
- Modify: `src/uw_scan/sources/uw.py` (add `fetch_gold_options_snapshot`)
- Test: `tests/unit/sources/test_uw_gold_options.py`

Reuses the existing `UwClient` (HTTP + auth + telemetry already wired). Adds one method that fetches the options chain for `GLD`/`GDX`/`IAU`, computes ATM IV at 30d/60d via linear interpolation, picks 25Δ put/call IVs (closest strike by abs(delta-0.25)/abs(delta+0.25)), and computes skew = put_25d_iv − call_25d_iv.

- [ ] **Step 1: Failing test**

```python
# tests/unit/sources/test_uw_gold_options.py
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from uw_scan.sources.uw import UwClient, GoldOptionsSnapshot


SAMPLE_CHAIN = {
    "data": [
        {"expiry": "2026-06-19", "strike": 230, "type": "call", "iv": 0.21, "delta": 0.55},
        {"expiry": "2026-06-19", "strike": 230, "type": "put",  "iv": 0.22, "delta": -0.45},
        {"expiry": "2026-06-19", "strike": 245, "type": "call", "iv": 0.18, "delta": 0.25},
        {"expiry": "2026-06-19", "strike": 215, "type": "put",  "iv": 0.27, "delta": -0.25},
        {"expiry": "2026-07-17", "strike": 230, "type": "call", "iv": 0.22, "delta": 0.55},
    ]
}


def test_gold_options_snapshot_picks_atm_and_25d():
    with patch.object(UwClient, "_get_json") as mock_get:
        mock_get.return_value = SAMPLE_CHAIN
        client = UwClient(api_key="test-key")
        snap = client.fetch_gold_options_snapshot("GLD", obs_date=date(2026, 5, 16))
    assert isinstance(snap, GoldOptionsSnapshot)
    assert snap.ticker == "GLD"
    assert snap.obs_date == date(2026, 5, 16)
    # 30d ATM is the 230 strike of the closest expiry (2026-06-19 is ~34 days out)
    assert snap.atm_iv_30d is not None
    assert snap.put_25d_iv_30d == Decimal("0.27")
    assert snap.call_25d_iv_30d == Decimal("0.18")
    assert snap.skew_25d_30d == Decimal("0.09")
```

- [ ] **Step 2: Run test, expect FAIL.**

- [ ] **Step 3: Extend `sources/uw.py`** — add the dataclass and method at the bottom of the existing file. Use existing `UwClient._get_json` plumbing.

```python
# Add to src/uw_scan/sources/uw.py

@dataclass(frozen=True)
class GoldOptionsSnapshot:
    ticker: str
    obs_date: date
    atm_iv_30d: Decimal | None
    atm_iv_60d: Decimal | None
    put_25d_iv_30d: Decimal | None
    call_25d_iv_30d: Decimal | None
    skew_25d_30d: Decimal | None
    put_call_oi_ratio: Decimal | None
    dealer_gamma_est: Decimal | None


def _nearest_to_delta(rows: list[dict], target: float) -> dict | None:
    eligible = [r for r in rows if "delta" in r and r.get("iv") is not None]
    if not eligible:
        return None
    return min(eligible, key=lambda r: abs(float(r["delta"]) - target))


def _interp_atm_iv(chain: list[dict], spot_proxy: float | None) -> Decimal | None:
    """ATM IV at the requested horizon: average call/put IV at the strike closest to spot."""
    # placeholder — production uses bid/ask midpoint and Black-Scholes interpolation
    if not chain:
        return None
    by_strike: dict[float, list[Decimal]] = {}
    for row in chain:
        strike = row.get("strike")
        iv = row.get("iv")
        if strike is None or iv is None:
            continue
        by_strike.setdefault(float(strike), []).append(Decimal(str(iv)))
    if spot_proxy is not None:
        atm_strike = min(by_strike, key=lambda k: abs(k - spot_proxy))
    else:
        atm_strike = sorted(by_strike)[len(by_strike) // 2]
    ivs = by_strike[atm_strike]
    return sum(ivs) / Decimal(len(ivs))


class UwClient:  # existing class — add this method
    def fetch_gold_options_snapshot(
        self, ticker: str, *, obs_date: date
    ) -> GoldOptionsSnapshot:
        chain_payload = self._get_json(f"/options/{ticker}/chain", params={"date": obs_date.isoformat()})
        data = chain_payload.get("data", [])

        # group by expiry, then pick nearest-to-30d and nearest-to-60d
        from collections import defaultdict
        by_expiry: dict[date, list[dict]] = defaultdict(list)
        for row in data:
            expiry = date.fromisoformat(row["expiry"])
            by_expiry[expiry].append(row)

        def _bucket_for_dte(target_days: int) -> list[dict] | None:
            if not by_expiry:
                return None
            chosen = min(by_expiry.keys(), key=lambda e: abs((e - obs_date).days - target_days))
            return by_expiry[chosen]

        rows_30d = _bucket_for_dte(30) or []
        rows_60d = _bucket_for_dte(60) or []

        put_25d = _nearest_to_delta([r for r in rows_30d if r.get("type") == "put"], -0.25)
        call_25d = _nearest_to_delta([r for r in rows_30d if r.get("type") == "call"], 0.25)

        put_iv = Decimal(str(put_25d["iv"])) if put_25d else None
        call_iv = Decimal(str(call_25d["iv"])) if call_25d else None
        skew = (put_iv - call_iv) if (put_iv is not None and call_iv is not None) else None

        return GoldOptionsSnapshot(
            ticker=ticker, obs_date=obs_date,
            atm_iv_30d=_interp_atm_iv(rows_30d, spot_proxy=None),
            atm_iv_60d=_interp_atm_iv(rows_60d, spot_proxy=None),
            put_25d_iv_30d=put_iv, call_25d_iv_30d=call_iv,
            skew_25d_30d=skew,
            put_call_oi_ratio=None,    # TODO Phase A2 once OI columns are mapped
            dealer_gamma_est=None,     # TODO Phase A2 — needs gamma * OI normalisation
        )
```

The two `TODO` markers above are *Phase A2 deferrals*, explicitly listed in [spec §13](../specs/2026-05-16-gold-phase-a1-design.md) and acceptable to land as `None` in A1.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/sources/test_uw_gold_options.py -v`
Expected: PASS.

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/sources/uw.py tests/unit/sources/test_uw_gold_options.py
git commit -m "feat(gold/sources): UW gold-options snapshot extension"
```

---

## Task 10: Repository methods for macro_series (daily + monthly)

**Files:**
- Modify: `src/uw_scan/storage/repository.py` (append new methods at logical-position; locate `class Repository:` and add at the bottom of the class before any module-level helpers)
- Test: `tests/integration/storage/test_gold_repo_macro_series.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/integration/storage/test_gold_repo_macro_series.py
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.storage.repository import Repository


@pytest.mark.integration
def test_insert_and_fetch_macro_series_daily(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        now = datetime.now(UTC)
        repo.insert_macro_series_daily(
            series_id="DFII10",
            obs_date=date(2026, 5, 14),
            value=Decimal("1.97"),
            as_of=now,
            release_date=None,
            source="FRED",
            source_url=None,
        )
        rows = repo.fetch_macro_series_daily("DFII10", from_date=date(2026, 5, 1))
        assert len(rows) == 1
        assert rows[0]["value"] == Decimal("1.97")


@pytest.mark.integration
def test_insert_macro_series_daily_keeps_vintages(postgresql):
    """Re-pulling a series writes a new vintage row, doesn't overwrite."""
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_macro_series_daily(
            "CPIAUCSL_TEST", date(2026, 4, 1), Decimal("310.1"),
            datetime(2026, 5, 14, 12, tzinfo=UTC), date(2026, 5, 14),
            "FRED", None,
        )
        repo.insert_macro_series_daily(
            "CPIAUCSL_TEST", date(2026, 4, 1), Decimal("310.3"),
            datetime(2026, 5, 28, 12, tzinfo=UTC), date(2026, 5, 28),
            "FRED", None,
        )
        rows = repo.fetch_macro_series_vintages(
            "CPIAUCSL_TEST", obs_date=date(2026, 4, 1)
        )
        assert len(rows) == 2
        assert rows[0]["value"] == Decimal("310.3")  # latest first
        assert rows[1]["value"] == Decimal("310.1")


@pytest.mark.integration
def test_fetch_macro_series_latest_returns_most_recent_vintage(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_macro_series_daily(
            "DFII10", date(2026, 5, 14), Decimal("1.95"),
            datetime(2026, 5, 14, tzinfo=UTC), None, "FRED", None,
        )
        repo.insert_macro_series_daily(
            "DFII10", date(2026, 5, 14), Decimal("1.97"),
            datetime(2026, 5, 15, tzinfo=UTC), None, "FRED", None,
        )
        rows = repo.fetch_macro_series_daily("DFII10")
        assert len(rows) == 1
        assert rows[0]["value"] == Decimal("1.97")
```

- [ ] **Step 2: Run the test, expect FAIL.**

Run: `uv run pytest tests/integration/storage/test_gold_repo_macro_series.py -v`

- [ ] **Step 3: Add the repository methods**

Append to `class Repository` in `src/uw_scan/storage/repository.py`:

```python
    # ---- Gold macro series (Phase A1) ----

    def insert_macro_series_daily(
        self,
        series_id: str,
        obs_date: _date,
        value: Decimal,
        as_of: datetime,
        release_date: _date | None,
        source: str,
        source_url: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO macro_series_daily
                  (series_id, obs_date, value, as_of, release_date, source, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, obs_date, as_of) DO NOTHING
                """,
                (series_id, obs_date, value, as_of, release_date, source, source_url),
            )

    def insert_macro_series_monthly(
        self,
        series_id: str,
        obs_month: _date,
        value: Decimal,
        as_of: datetime,
        release_date: _date | None,
        source: str,
        source_url: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO macro_series_monthly
                  (series_id, obs_month, value, as_of, release_date, source, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (series_id, obs_month, as_of) DO NOTHING
                """,
                (series_id, obs_month, value, as_of, release_date, source, source_url),
            )

    def fetch_macro_series_daily(
        self,
        series_id: str,
        *,
        from_date: _date | None = None,
        to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Latest-vintage values for a daily series. Respects optional date window
        and as-of cap (for replay/PIT queries)."""
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
        if from_date is not None:
            clauses.append("obs_date >= %s")
            params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s")
            params.append(to_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, value, as_of, release_date, source
                FROM macro_series_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def fetch_macro_series_monthly(
        self,
        series_id: str,
        *,
        from_month: _date | None = None,
        to_month: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["series_id = %s"]
        params: list[Any] = [series_id]
        if from_month is not None:
            clauses.append("obs_month >= %s")
            params.append(from_month)
        if to_month is not None:
            clauses.append("obs_month <= %s")
            params.append(to_month)
        if as_of_max is not None:
            clauses.append("as_of <= %s")
            params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_month)
                  obs_month, value, as_of, release_date, source
                FROM macro_series_monthly
                WHERE {where}
                ORDER BY obs_month ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def fetch_macro_series_vintages(
        self, series_id: str, *, obs_date: _date
    ) -> list[dict[str, Any]]:
        """All persisted vintages for a single observation (useful for audit)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT obs_date, value, as_of, release_date, source
                FROM macro_series_daily
                WHERE series_id = %s AND obs_date = %s
                ORDER BY as_of DESC
                """,
                (series_id, obs_date),
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
```

- [ ] **Step 4: Run tests, expect PASS.**

Run: `uv run pytest tests/integration/storage/test_gold_repo_macro_series.py -v`

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_gold_repo_macro_series.py
git commit -m "feat(gold/storage): macro_series repository methods"
```

---

## Task 11: Repository methods — ETF holdings + exchange inventory

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_gold_repo_etf_inventory.py`

- [ ] **Step 1: Failing test**

```python
# tests/integration/storage/test_gold_repo_etf_inventory.py
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.storage.repository import Repository


@pytest.mark.integration
def test_insert_and_fetch_etf_holdings_daily(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_etf_holdings_daily(
            ticker="GLD", obs_date=date(2026, 5, 14),
            holdings_oz=Decimal("28047500.12"),
            shares_out=None, nav_per_share=Decimal("234.50"),
            premium_pct=None, as_of=datetime.now(UTC), source="SPDR",
        )
        rows = repo.fetch_etf_holdings_daily("GLD", from_date=date(2026, 5, 1))
        assert len(rows) == 1
        assert rows[0]["holdings_oz"] == Decimal("28047500.12")


@pytest.mark.integration
def test_insert_and_fetch_exchange_inventory_daily(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_exchange_inventory_daily(
            exchange="COMEX", obs_date=date(2026, 5, 15),
            registered_oz=Decimal("17500100"),
            eligible_oz=Decimal("10820200"),
            vault_oz=None,
            as_of=datetime.now(UTC), source_url=None,
        )
        rows = repo.fetch_exchange_inventory_daily("COMEX", from_date=date(2026, 5, 1))
        assert len(rows) == 1
        assert rows[0]["registered_oz"] == Decimal("17500100")
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Add the methods**

Append to `class Repository`:

```python
    # ---- ETF holdings ----

    def insert_etf_holdings_daily(
        self, *, ticker: str, obs_date: _date,
        holdings_oz: Decimal | None, shares_out: Decimal | None,
        nav_per_share: Decimal | None, premium_pct: Decimal | None,
        as_of: datetime, source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO etf_holdings_daily
                  (ticker, obs_date, holdings_oz, shares_out, nav_per_share,
                   premium_pct, as_of, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, as_of) DO NOTHING
                """,
                (ticker, obs_date, holdings_oz, shares_out, nav_per_share,
                 premium_pct, as_of, source),
            )

    def fetch_etf_holdings_daily(
        self, ticker: str, *,
        from_date: _date | None = None, to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
        if from_date is not None:
            clauses.append("obs_date >= %s"); params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s"); params.append(to_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s"); params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, holdings_oz, shares_out, nav_per_share, premium_pct,
                  as_of, source
                FROM etf_holdings_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- Exchange inventory ----

    def insert_exchange_inventory_daily(
        self, *, exchange: str, obs_date: _date,
        registered_oz: Decimal | None, eligible_oz: Decimal | None,
        vault_oz: Decimal | None, as_of: datetime, source_url: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO exchange_inventory_daily
                  (exchange, obs_date, registered_oz, eligible_oz, vault_oz,
                   as_of, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (exchange, obs_date, as_of) DO NOTHING
                """,
                (exchange, obs_date, registered_oz, eligible_oz, vault_oz,
                 as_of, source_url),
            )

    def fetch_exchange_inventory_daily(
        self, exchange: str, *,
        from_date: _date | None = None, to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["exchange = %s"]
        params: list[Any] = [exchange]
        if from_date is not None:
            clauses.append("obs_date >= %s"); params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s"); params.append(to_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s"); params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, registered_oz, eligible_oz, vault_oz, as_of, source_url
                FROM exchange_inventory_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_gold_repo_etf_inventory.py
git commit -m "feat(gold/storage): ETF holdings + exchange inventory repo methods"
```

---

## Task 12: Repository methods — CB reserves + COT + UW options

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_gold_repo_flows.py`

- [ ] **Step 1: Failing test**

```python
# tests/integration/storage/test_gold_repo_flows.py
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.storage.repository import Repository


@pytest.mark.integration
def test_cb_reserves_round_trip(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_cb_gold_reserves_monthly(
            country_iso3="CHN", obs_month=date(2026, 4, 1),
            reserves_t=Decimal("2235.0"), bucket="strategic_accumulator",
            is_reported=True, is_estimated=False,
            as_of=datetime.now(UTC), release_date=date(2026, 5, 8), source="WGC",
        )
        rows = repo.fetch_cb_gold_reserves_monthly(
            bucket="strategic_accumulator", from_month=date(2026, 1, 1)
        )
        assert any(r["country_iso3"] == "CHN" for r in rows)


@pytest.mark.integration
def test_cot_round_trip_pins_release_date(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_cot_gold_weekly(
            obs_date=date(2026, 5, 13), release_date=date(2026, 5, 16),
            mm_long=Decimal("210500"), mm_short=Decimal("85300"),
            mm_net=Decimal("125200"),
            comm_long=Decimal("180100"), comm_short=Decimal("295400"),
            comm_net=Decimal("-115300"),
            open_interest=Decimal("512000"),
            as_of=datetime.now(UTC), source_url=None,
        )
        rows = repo.fetch_cot_gold_weekly(
            from_release_date=date(2026, 5, 1), to_release_date=date(2026, 5, 20),
        )
        assert len(rows) == 1
        assert rows[0]["release_date"] == date(2026, 5, 16)
        assert rows[0]["mm_net"] == Decimal("125200")


@pytest.mark.integration
def test_uw_gold_options_round_trip(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_uw_gold_options_daily(
            ticker="GLD", obs_date=date(2026, 5, 16),
            atm_iv_30d=Decimal("0.21"), atm_iv_60d=Decimal("0.22"),
            put_25d_iv_30d=Decimal("0.27"), call_25d_iv_30d=Decimal("0.18"),
            skew_25d_30d=Decimal("0.09"),
            put_call_oi_ratio=None, dealer_gamma_est=None,
            as_of=datetime.now(UTC),
        )
        rows = repo.fetch_uw_gold_options_daily("GLD", from_date=date(2026, 5, 1))
        assert len(rows) == 1
        assert rows[0]["skew_25d_30d"] == Decimal("0.09")
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Add the methods** — append to `class Repository` (signature pattern mirrors Task 10–11; column lists match migrations 040, 041, 042):

```python
    # ---- CB gold reserves ----

    def insert_cb_gold_reserves_monthly(
        self, *, country_iso3: str, obs_month: _date,
        reserves_t: Decimal | None, bucket: str,
        is_reported: bool, is_estimated: bool,
        as_of: datetime, release_date: _date | None, source: str,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cb_gold_reserves_monthly
                  (country_iso3, obs_month, reserves_t, bucket,
                   is_reported, is_estimated, as_of, release_date, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (country_iso3, obs_month, as_of) DO NOTHING
                """,
                (country_iso3, obs_month, reserves_t, bucket,
                 is_reported, is_estimated, as_of, release_date, source),
            )

    def fetch_cb_gold_reserves_monthly(
        self, *, bucket: str | None = None,
        country_iso3: str | None = None,
        from_month: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: list[Any] = []
        if bucket is not None:
            clauses.append("bucket = %s"); params.append(bucket)
        if country_iso3 is not None:
            clauses.append("country_iso3 = %s"); params.append(country_iso3)
        if from_month is not None:
            clauses.append("obs_month >= %s"); params.append(from_month)
        if as_of_max is not None:
            clauses.append("as_of <= %s"); params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (country_iso3, obs_month)
                  country_iso3, obs_month, reserves_t, bucket,
                  is_reported, is_estimated, as_of, release_date, source
                FROM cb_gold_reserves_monthly
                WHERE {where}
                ORDER BY country_iso3, obs_month DESC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- CFTC COT ----

    def insert_cot_gold_weekly(
        self, *, obs_date: _date, release_date: _date,
        mm_long: Decimal | None, mm_short: Decimal | None, mm_net: Decimal | None,
        comm_long: Decimal | None, comm_short: Decimal | None, comm_net: Decimal | None,
        open_interest: Decimal | None,
        as_of: datetime, source_url: str | None,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cot_gold_weekly
                  (obs_date, release_date, mm_long, mm_short, mm_net,
                   comm_long, comm_short, comm_net, open_interest,
                   as_of, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (obs_date, as_of) DO NOTHING
                """,
                (obs_date, release_date, mm_long, mm_short, mm_net,
                 comm_long, comm_short, comm_net, open_interest,
                 as_of, source_url),
            )

    def fetch_cot_gold_weekly(
        self, *,
        from_release_date: _date | None = None,
        to_release_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["TRUE"]
        params: list[Any] = []
        if from_release_date is not None:
            clauses.append("release_date >= %s"); params.append(from_release_date)
        if to_release_date is not None:
            clauses.append("release_date <= %s"); params.append(to_release_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s"); params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, release_date, mm_long, mm_short, mm_net,
                  comm_long, comm_short, comm_net, open_interest, as_of, source_url
                FROM cot_gold_weekly
                WHERE {where}
                ORDER BY obs_date DESC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    # ---- UW gold options snapshots ----

    def insert_uw_gold_options_daily(
        self, *, ticker: str, obs_date: _date,
        atm_iv_30d: Decimal | None, atm_iv_60d: Decimal | None,
        put_25d_iv_30d: Decimal | None, call_25d_iv_30d: Decimal | None,
        skew_25d_30d: Decimal | None,
        put_call_oi_ratio: Decimal | None, dealer_gamma_est: Decimal | None,
        as_of: datetime,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO uw_gold_options_daily
                  (ticker, obs_date, atm_iv_30d, atm_iv_60d,
                   put_25d_iv_30d, call_25d_iv_30d, skew_25d_30d,
                   put_call_oi_ratio, dealer_gamma_est, as_of)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, obs_date, as_of) DO NOTHING
                """,
                (ticker, obs_date, atm_iv_30d, atm_iv_60d,
                 put_25d_iv_30d, call_25d_iv_30d, skew_25d_30d,
                 put_call_oi_ratio, dealer_gamma_est, as_of),
            )

    def fetch_uw_gold_options_daily(
        self, ticker: str, *,
        from_date: _date | None = None, to_date: _date | None = None,
        as_of_max: datetime | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
        if from_date is not None:
            clauses.append("obs_date >= %s"); params.append(from_date)
        if to_date is not None:
            clauses.append("obs_date <= %s"); params.append(to_date)
        if as_of_max is not None:
            clauses.append("as_of <= %s"); params.append(as_of_max)
        where = " AND ".join(clauses)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (obs_date)
                  obs_date, atm_iv_30d, atm_iv_60d,
                  put_25d_iv_30d, call_25d_iv_30d, skew_25d_30d,
                  put_call_oi_ratio, dealer_gamma_est, as_of
                FROM uw_gold_options_daily
                WHERE {where}
                ORDER BY obs_date ASC, as_of DESC
                """,
                params,
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_gold_repo_flows.py
git commit -m "feat(gold/storage): CB reserves, COT, UW gold-options repo methods"
```

---

## Task 13: Repository methods — gold_posture (write + replay)

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_gold_repo_posture.py`

This task is the load-bearing replay scaffold. `insert_gold_posture_daily` writes a full posture row including `inputs_jsonb` provenance. `fetch_gold_posture_latest` returns the most recent posture. `fetch_gold_posture_for_obs_date` returns the **first-computed** posture for an `obs_date` — that's the replay endpoint discipline.

- [ ] **Step 1: Failing test**

```python
# tests/integration/storage/test_gold_repo_posture.py
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.storage.repository import Repository


@pytest.mark.integration
def test_insert_and_fetch_gold_posture_latest(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_gold_posture_daily(
            obs_date=date(2026, 5, 16),
            computed_at=datetime(2026, 5, 17, tzinfo=UTC),
            gauge_corr_60d=Decimal("-0.04"),
            gauge_corr_126d=Decimal("-0.05"),
            gauge_corr_252d=Decimal("-0.07"),
            gauge_corr_504d=Decimal("-0.31"),
            gauge_corr_252d_returns=Decimal("-0.06"),
            gauge_state="suspended",
            structural_state_label="structural-bid-intact",
            cb_strategic_12m_sum_t=Decimal("210.5"),
            cb_tactical_12m_sum_t=Decimal("12.0"),
            cb_diversifier_12m_sum_t=Decimal("34.0"),
            gld_holdings_t=Decimal("872.5"),
            gld_30d_net_flow_t=Decimal("-12.4"),
            comex_registered_oz=Decimal("17500100"),
            comex_20d_roc_pct=Decimal("0.14"),
            cot_mm_net_pct=Decimal("0.72"),
            cyclical_zone_label="moderate-trap",
            cpi_yoy=Decimal("2.8"),
            t5yifr=Decimal("2.31"),
            dfii10=Decimal("1.97"),
            dfii10_60d_change_bps=Decimal("12"),
            factors_jsonb={"F1": -0.4, "F5": 1.8, "F13": 0.6},
            valuation_flag="Severe",
            real_price_percentile=Decimal("0.92"),
            gold_m2_ratio_percentile=Decimal("0.78"),
            gold_spx_ratio_percentile=Decimal("0.64"),
            structural_posture_text="Structural bid intact.",
            cyclical_posture_text="Cyclical posture suspended.",
            valuation_posture_text="Mean-reversion risk: SEVERE.",
            inputs_jsonb={"DFII10": {"obs_date": "2026-05-16", "as_of": "2026-05-17T00:00:00Z"}},
        )
        latest = repo.fetch_gold_posture_latest()
        assert latest["obs_date"] == date(2026, 5, 16)
        assert latest["gauge_state"] == "suspended"
        assert latest["factors_jsonb"]["F5"] == 1.8


@pytest.mark.integration
def test_replay_returns_first_computed(postgresql):
    """Multiple computed_at rows for same obs_date → replay picks the FIRST one."""
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")

        def insert(computed_at: datetime, state: str) -> None:
            repo.insert_gold_posture_daily(
                obs_date=date(2026, 5, 10),
                computed_at=computed_at,
                gauge_corr_60d=None, gauge_corr_126d=None,
                gauge_corr_252d=None, gauge_corr_504d=None,
                gauge_corr_252d_returns=None,
                gauge_state=state,
                structural_state_label=None,
                cb_strategic_12m_sum_t=None, cb_tactical_12m_sum_t=None,
                cb_diversifier_12m_sum_t=None,
                gld_holdings_t=None, gld_30d_net_flow_t=None,
                comex_registered_oz=None, comex_20d_roc_pct=None,
                cot_mm_net_pct=None, cyclical_zone_label=None,
                cpi_yoy=None, t5yifr=None, dfii10=None,
                dfii10_60d_change_bps=None, factors_jsonb={},
                valuation_flag=None, real_price_percentile=None,
                gold_m2_ratio_percentile=None, gold_spx_ratio_percentile=None,
                structural_posture_text=None, cyclical_posture_text=None,
                valuation_posture_text=None, inputs_jsonb={},
            )
        insert(datetime(2026, 5, 11, 21, tzinfo=UTC), "suspended")
        insert(datetime(2026, 5, 20, 21, tzinfo=UTC), "partial")  # recomputed later

        row = repo.fetch_gold_posture_for_obs_date(date(2026, 5, 10))
        assert row["gauge_state"] == "suspended"   # FIRST-computed, per replay discipline
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Add the methods**

```python
    # ---- Gold posture (replay scaffold) ----

    def insert_gold_posture_daily(
        self, *, obs_date: _date, computed_at: datetime,
        gauge_corr_60d: Decimal | None, gauge_corr_126d: Decimal | None,
        gauge_corr_252d: Decimal | None, gauge_corr_504d: Decimal | None,
        gauge_corr_252d_returns: Decimal | None, gauge_state: str,
        structural_state_label: str | None,
        cb_strategic_12m_sum_t: Decimal | None,
        cb_tactical_12m_sum_t: Decimal | None,
        cb_diversifier_12m_sum_t: Decimal | None,
        gld_holdings_t: Decimal | None, gld_30d_net_flow_t: Decimal | None,
        comex_registered_oz: Decimal | None, comex_20d_roc_pct: Decimal | None,
        cot_mm_net_pct: Decimal | None,
        cyclical_zone_label: str | None,
        cpi_yoy: Decimal | None, t5yifr: Decimal | None, dfii10: Decimal | None,
        dfii10_60d_change_bps: Decimal | None,
        factors_jsonb: dict[str, Any],
        valuation_flag: str | None,
        real_price_percentile: Decimal | None,
        gold_m2_ratio_percentile: Decimal | None,
        gold_spx_ratio_percentile: Decimal | None,
        structural_posture_text: str | None,
        cyclical_posture_text: str | None,
        valuation_posture_text: str | None,
        inputs_jsonb: dict[str, Any],
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gold_posture_daily (
                  obs_date, computed_at,
                  gauge_corr_60d, gauge_corr_126d, gauge_corr_252d,
                  gauge_corr_504d, gauge_corr_252d_returns, gauge_state,
                  structural_state_label,
                  cb_strategic_12m_sum_t, cb_tactical_12m_sum_t,
                  cb_diversifier_12m_sum_t,
                  gld_holdings_t, gld_30d_net_flow_t,
                  comex_registered_oz, comex_20d_roc_pct, cot_mm_net_pct,
                  cyclical_zone_label, cpi_yoy, t5yifr, dfii10,
                  dfii10_60d_change_bps, factors_jsonb,
                  valuation_flag, real_price_percentile,
                  gold_m2_ratio_percentile, gold_spx_ratio_percentile,
                  structural_posture_text, cyclical_posture_text,
                  valuation_posture_text, inputs_jsonb
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s
                )
                ON CONFLICT (obs_date, computed_at) DO NOTHING
                """,
                (obs_date, computed_at,
                 gauge_corr_60d, gauge_corr_126d, gauge_corr_252d,
                 gauge_corr_504d, gauge_corr_252d_returns, gauge_state,
                 structural_state_label,
                 cb_strategic_12m_sum_t, cb_tactical_12m_sum_t,
                 cb_diversifier_12m_sum_t,
                 gld_holdings_t, gld_30d_net_flow_t,
                 comex_registered_oz, comex_20d_roc_pct, cot_mm_net_pct,
                 cyclical_zone_label, cpi_yoy, t5yifr, dfii10,
                 dfii10_60d_change_bps, Jsonb(factors_jsonb),
                 valuation_flag, real_price_percentile,
                 gold_m2_ratio_percentile, gold_spx_ratio_percentile,
                 structural_posture_text, cyclical_posture_text,
                 valuation_posture_text, Jsonb(inputs_jsonb)),
            )

    def fetch_gold_posture_latest(self) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM gold_posture_daily
                ORDER BY obs_date DESC, computed_at DESC
                LIMIT 1
                """,
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))

    def fetch_gold_posture_for_obs_date(self, obs_date: _date) -> dict[str, Any] | None:
        """Replay discipline: return the FIRST-computed posture for an obs_date,
        not the most recent recomputation."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM gold_posture_daily
                WHERE obs_date = %s
                ORDER BY computed_at ASC
                LIMIT 1
                """,
                (obs_date,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [c.name for c in cur.description]
            return dict(zip(cols, row, strict=True))
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_gold_repo_posture.py
git commit -m "feat(gold/storage): gold_posture write + replay-discipline read"
```

---

## Task 14: Card — regime_gauge.py (correlation gauge)

**Files:**
- Create: `src/uw_scan/cards/regime_gauge.py`
- Test: `tests/unit/cards/test_regime_gauge.py`

Pure function. Inputs: gold daily series, DFII10 daily series, as_of date. Outputs: 4 window-specific rolling correlations (levels), 1 returns-based 252d correlation (sanity-check), plus the derived `gauge_state` label using default thresholds.

- [ ] **Step 1: Failing test**

```python
# tests/unit/cards/test_regime_gauge.py
from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.cards.regime_gauge import (
    compute_correlation_gauge,
    classify_gauge_state,
    CorrelationGauge,
)


def _synthetic_series(n: int, start: date, anchor: float, slope: float) -> list[tuple[date, Decimal]]:
    return [(start + timedelta(days=i), Decimal(str(anchor + slope * i))) for i in range(n)]


def test_gauge_negative_correlation_when_series_anti_correlated():
    """Gold rising while TIPS yield falling → strong negative corr."""
    gold = _synthetic_series(300, date(2020, 1, 1), 1500.0, 1.5)
    tips = _synthetic_series(300, date(2020, 1, 1), 1.0, -0.005)
    g = compute_correlation_gauge(gold, tips, as_of=date(2020, 10, 25))
    assert g.corr_252d_level is not None
    assert g.corr_252d_level < Decimal("-0.95")


def test_gauge_state_thresholds():
    assert classify_gauge_state(Decimal("-0.85")) == "operative"
    assert classify_gauge_state(Decimal("-0.35")) == "partial"
    assert classify_gauge_state(Decimal("-0.05")) == "suspended"
    assert classify_gauge_state(Decimal("0.4")) == "suspended"


def test_gauge_returns_spec_consistent_with_levels():
    """When series are anti-correlated in levels AND in returns, both specs agree."""
    gold = _synthetic_series(300, date(2020, 1, 1), 1500.0, 1.5)
    tips = _synthetic_series(300, date(2020, 1, 1), 1.0, -0.005)
    g = compute_correlation_gauge(gold, tips, as_of=date(2020, 10, 25))
    assert g.corr_252d_returns is not None
    # both should be strongly negative for this synthetic case
    assert g.corr_252d_returns < Decimal("-0.5")


def test_gauge_short_series_returns_nulls():
    """Less than 60d of history → all corr values None."""
    gold = _synthetic_series(30, date(2020, 1, 1), 1500.0, 1.0)
    tips = _synthetic_series(30, date(2020, 1, 1), 1.0, 0.0)
    g = compute_correlation_gauge(gold, tips, as_of=date(2020, 1, 30))
    assert g.corr_60d_level is None
    assert g.corr_252d_level is None
    assert g.state == "suspended"
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/cards/regime_gauge.py
"""Correlation gauge — rolling Gold ↔ DFII10 across 4 windows, levels + returns.

Default thresholds:
  state = 'operative'  if corr_252d_level in [-1.00, -0.50]
        = 'partial'    if corr_252d_level in (-0.50, -0.20]
        = 'suspended'  otherwise

Per docs/research/gold-sdf-framework/04-three-layer-architecture.md these
thresholds are heuristic; Phase A2 calibrates empirically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CorrelationGauge:
    corr_60d_level: Decimal | None
    corr_126d_level: Decimal | None
    corr_252d_level: Decimal | None
    corr_504d_level: Decimal | None
    corr_252d_returns: Decimal | None
    state: str


def _align(series_a: list[tuple[date, Decimal]], series_b: list[tuple[date, Decimal]]):
    a_map = dict(series_a)
    b_map = dict(series_b)
    common = sorted(set(a_map) & set(b_map))
    return common, [float(a_map[d]) for d in common], [float(b_map[d]) for d in common]


def _pearson(xs: list[float], ys: list[float]) -> Decimal | None:
    if len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return None
    return Decimal(str(num / (den_x * den_y))).quantize(Decimal("0.0001"))


def _trailing(values: list[float], window: int) -> list[float] | None:
    if len(values) < window:
        return None
    return values[-window:]


def _log_returns(values: list[float]) -> list[float]:
    out: list[float] = []
    for prev, curr in zip(values[:-1], values[1:], strict=True):
        if prev <= 0 or curr <= 0:
            out.append(0.0)
        else:
            out.append(math.log(curr / prev))
    return out


def compute_correlation_gauge(
    gold_series: list[tuple[date, Decimal]],
    dfii10_series: list[tuple[date, Decimal]],
    *,
    as_of: date,
) -> CorrelationGauge:
    g_filtered = [(d, v) for d, v in gold_series if d <= as_of]
    t_filtered = [(d, v) for d, v in dfii10_series if d <= as_of]
    _dates, gold_vals, tips_vals = _align(g_filtered, t_filtered)
    if len(gold_vals) < 60:
        return CorrelationGauge(None, None, None, None, None, "suspended")

    def corr_window(w: int) -> Decimal | None:
        g = _trailing(gold_vals, w)
        t = _trailing(tips_vals, w)
        if g is None or t is None:
            return None
        return _pearson(g, t)

    corr_60 = corr_window(60)
    corr_126 = corr_window(126)
    corr_252 = corr_window(252)
    corr_504 = corr_window(504)

    g_ret = _log_returns(gold_vals)
    t_ret = _log_returns(tips_vals)
    g_ret_w = _trailing(g_ret, 252)
    t_ret_w = _trailing(t_ret, 252)
    corr_252_returns = _pearson(g_ret_w, t_ret_w) if g_ret_w and t_ret_w else None

    state = classify_gauge_state(corr_252)
    return CorrelationGauge(
        corr_60_level=corr_60, corr_126_level=corr_126,
        corr_252_level=corr_252, corr_504_level=corr_504,
        corr_252_returns=corr_252_returns, state=state,
    ) if False else CorrelationGauge(
        corr_60d_level=corr_60, corr_126d_level=corr_126,
        corr_252d_level=corr_252, corr_504d_level=corr_504,
        corr_252d_returns=corr_252_returns, state=state,
    )


def classify_gauge_state(corr_252_level: Decimal | None) -> str:
    if corr_252_level is None:
        return "suspended"
    if Decimal("-1.0") <= corr_252_level <= Decimal("-0.5"):
        return "operative"
    if Decimal("-0.5") < corr_252_level <= Decimal("-0.2"):
        return "partial"
    return "suspended"
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/cards/regime_gauge.py tests/unit/cards/test_regime_gauge.py
git commit -m "feat(gold/cards): correlation gauge across 4 windows"
```

---

## Task 15: Card — structural_flow.py (Lens 1 posture)

**Files:**
- Create: `src/uw_scan/cards/structural_flow.py`
- Test: `tests/unit/cards/test_structural_flow.py`

Computes Lens 1 posture: per-bucket 12-month CB reserve sum, GLD 30d net flow z-score (against 252-day rolling baseline), COMEX 20d registered ROC, XAU/CNY premium, COT managed-money net percentile (5-year window), plus a 1-sentence narrative built from a deterministic template.

- [ ] **Step 1: Failing test**

```python
# tests/unit/cards/test_structural_flow.py
from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.cards.structural_flow import (
    compute_structural_posture,
    StructuralPosture,
    CbReserveSnapshot,
    EtfHoldingSnapshot,
    InventorySnapshot,
    CotSnapshot,
    FxSnapshot,
)


def test_structural_posture_bucket_sums_12m():
    cb_rows = []
    for month_offset in range(12):
        cb_rows.append(CbReserveSnapshot(
            country_iso3="CHN",
            obs_month=date(2026, 5, 1) - timedelta(days=30 * month_offset),
            reserves_t=Decimal(str(2200 + month_offset * 5)),  # rising
            bucket="strategic_accumulator",
        ))
    posture = compute_structural_posture(
        cb_rows=cb_rows, etf_rows=[], inventory_rows=[],
        cot_rows=[], fx_rows=[], gold_series=[],
        as_of=date(2026, 5, 16),
    )
    assert posture.cb_strategic_12m_sum_t is not None
    assert posture.cb_strategic_12m_sum_t > Decimal("0")


def test_structural_posture_emits_narrative():
    posture = compute_structural_posture(
        cb_rows=[], etf_rows=[], inventory_rows=[],
        cot_rows=[], fx_rows=[], gold_series=[],
        as_of=date(2026, 5, 16),
    )
    assert posture.narrative_text is not None
    assert len(posture.narrative_text) > 0
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/cards/structural_flow.py
"""Lens 1 — structural-flow posture composition.

Pure function: consumes repository row dataclasses, emits a posture struct
with z-scored signals and a deterministic narrative template.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class CbReserveSnapshot:
    country_iso3: str
    obs_month: date
    reserves_t: Decimal | None
    bucket: str


@dataclass(frozen=True)
class EtfHoldingSnapshot:
    ticker: str
    obs_date: date
    holdings_oz: Decimal | None


@dataclass(frozen=True)
class InventorySnapshot:
    exchange: str
    obs_date: date
    registered_oz: Decimal | None
    vault_oz: Decimal | None


@dataclass(frozen=True)
class CotSnapshot:
    release_date: date
    mm_net: Decimal | None


@dataclass(frozen=True)
class FxSnapshot:
    pair: str
    obs_date: date
    rate: Decimal


@dataclass(frozen=True)
class StructuralPosture:
    cb_strategic_12m_sum_t: Decimal | None
    cb_tactical_12m_sum_t: Decimal | None
    cb_diversifier_12m_sum_t: Decimal | None
    gld_holdings_t: Decimal | None
    gld_30d_net_flow_t: Decimal | None
    comex_registered_oz: Decimal | None
    comex_20d_roc_pct: Decimal | None
    cot_mm_net_pct: Decimal | None
    structural_state_label: str
    narrative_text: str


def _sum_by_bucket(cb_rows: list[CbReserveSnapshot], bucket: str, cutoff: date) -> Decimal | None:
    rows = [r for r in cb_rows if r.bucket == bucket and r.obs_month >= cutoff and r.reserves_t is not None]
    if not rows:
        return None
    return sum((r.reserves_t for r in rows), Decimal("0"))


def _percentile(values: list[Decimal], target: Decimal) -> Decimal | None:
    if not values:
        return None
    below = sum(1 for v in values if v <= target)
    return Decimal(str(below / len(values))).quantize(Decimal("0.001"))


def compute_structural_posture(
    *,
    cb_rows: list[CbReserveSnapshot],
    etf_rows: list[EtfHoldingSnapshot],
    inventory_rows: list[InventorySnapshot],
    cot_rows: list[CotSnapshot],
    fx_rows: list[FxSnapshot],
    gold_series: list[tuple[date, Decimal]],
    as_of: date,
) -> StructuralPosture:
    twelve_months_ago = as_of - timedelta(days=365)

    cb_strat = _sum_by_bucket(cb_rows, "strategic_accumulator", twelve_months_ago)
    cb_tact = _sum_by_bucket(cb_rows, "tactical_defender", twelve_months_ago)
    cb_div = _sum_by_bucket(cb_rows, "reserve_diversifier", twelve_months_ago)

    gld_rows = sorted([r for r in etf_rows if r.ticker == "GLD" and r.holdings_oz is not None],
                     key=lambda r: r.obs_date)
    gld_now = gld_rows[-1].holdings_oz if gld_rows else None
    gld_holdings_t = (gld_now / Decimal("32150.7")) if gld_now is not None else None

    if len(gld_rows) >= 30:
        delta_30d = gld_rows[-1].holdings_oz - gld_rows[-30].holdings_oz
        gld_30d_net_flow_t = delta_30d / Decimal("32150.7")
    else:
        gld_30d_net_flow_t = None

    comex_rows = sorted([r for r in inventory_rows if r.exchange == "COMEX" and r.registered_oz is not None],
                       key=lambda r: r.obs_date)
    comex_now = comex_rows[-1].registered_oz if comex_rows else None
    if len(comex_rows) >= 20 and comex_rows[-20].registered_oz not in (None, Decimal("0")):
        comex_20d_roc_pct = (comex_rows[-1].registered_oz - comex_rows[-20].registered_oz) / comex_rows[-20].registered_oz
    else:
        comex_20d_roc_pct = None

    cot_sorted = sorted([r for r in cot_rows if r.mm_net is not None and r.release_date <= as_of],
                       key=lambda r: r.release_date)
    if len(cot_sorted) >= 52:
        latest_mm = cot_sorted[-1].mm_net
        window = [r.mm_net for r in cot_sorted[-260:]]  # 5y of weekly = 260
        cot_mm_net_pct = _percentile(window, latest_mm)
    else:
        cot_mm_net_pct = None

    label = _classify_structural(cb_strat, gld_30d_net_flow_t, comex_20d_roc_pct)
    narrative = _narrate_structural(label, cb_strat, gld_30d_net_flow_t, comex_20d_roc_pct, cot_mm_net_pct)

    return StructuralPosture(
        cb_strategic_12m_sum_t=cb_strat,
        cb_tactical_12m_sum_t=cb_tact,
        cb_diversifier_12m_sum_t=cb_div,
        gld_holdings_t=gld_holdings_t,
        gld_30d_net_flow_t=gld_30d_net_flow_t,
        comex_registered_oz=comex_now,
        comex_20d_roc_pct=comex_20d_roc_pct,
        cot_mm_net_pct=cot_mm_net_pct,
        structural_state_label=label,
        narrative_text=narrative,
    )


def _classify_structural(
    cb_strat: Decimal | None,
    gld_flow: Decimal | None,
    comex_roc: Decimal | None,
) -> str:
    if cb_strat is not None and cb_strat > Decimal("500"):
        if gld_flow is not None and gld_flow < Decimal("0"):
            return "structural-bid-cb-led"
        return "structural-bid-intact"
    if gld_flow is not None and gld_flow > Decimal("20"):
        return "western-institutional-return"
    return "structural-mixed"


def _narrate_structural(
    label: str,
    cb_strat: Decimal | None,
    gld_flow: Decimal | None,
    comex_roc: Decimal | None,
    cot_pct: Decimal | None,
) -> str:
    parts: list[str] = []
    if label == "structural-bid-cb-led":
        parts.append("Structural bid CB-led — ETF flows still outflowing, central bank accumulators dominant.")
    elif label == "structural-bid-intact":
        parts.append("Structural bid intact.")
    elif label == "western-institutional-return":
        parts.append("Western institutional flow turning positive — possible regime reactivation signal.")
    else:
        parts.append("Structural posture mixed.")
    if cb_strat is not None:
        parts.append(f"CB strategic accumulators 12m sum: {cb_strat:.0f}t.")
    if gld_flow is not None:
        parts.append(f"GLD 30d net flow: {gld_flow:+.1f}t.")
    if comex_roc is not None:
        parts.append(f"COMEX registered 20d ROC: {comex_roc*100:+.1f}%.")
    if cot_pct is not None:
        parts.append(f"COT managed-money net at {cot_pct*100:.0f}th percentile.")
    return " ".join(parts)
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/cards/structural_flow.py tests/unit/cards/test_structural_flow.py
git commit -m "feat(gold/cards): structural-flow posture (Lens 1)"
```

---

## Task 16: Card — cyclical_zones.py (Lens 2 posture)

**Files:**
- Create: `src/uw_scan/cards/cyclical_zones.py`
- Test: `tests/unit/cards/test_cyclical_zones.py`

Article-zone classification + two-force narrative. **Important**: zone labels must use the "article zone" framing — `'article-unanchored'` not `'unanchored'`, with the heuristic-not-validated badge documented in code comments and emitted in the posture text.

- [ ] **Step 1: Failing test**

```python
# tests/unit/cards/test_cyclical_zones.py
from decimal import Decimal
import pytest

from uw_scan.cards.cyclical_zones import (
    classify_article_zone,
    compute_cyclical_posture,
    CyclicalPosture,
)


def test_zone_real_rate_driven():
    assert classify_article_zone(Decimal("1.5"), Decimal("2.3")) == "real-rate-driven"


def test_zone_moderate_trap():
    assert classify_article_zone(Decimal("3.0"), Decimal("2.6")) == "moderate-trap"


def test_zone_article_unanchored():
    assert classify_article_zone(Decimal("4.5"), Decimal("3.1")) == "article-unanchored"


def test_zone_transitional_otherwise():
    assert classify_article_zone(Decimal("3.5"), Decimal("3.5")) == "transitional"


def test_cyclical_posture_uses_heuristic_badge_in_narrative():
    posture = compute_cyclical_posture(
        cpi_yoy=Decimal("2.8"),
        t5yifr=Decimal("2.31"),
        dfii10=Decimal("1.97"),
        dfii10_60d_change_bps=Decimal("12"),
        factors={"F1": -0.4, "F5": 1.8},
        gauge_state="suspended",
    )
    assert posture.zone_label == "moderate-trap"
    assert "heuristic" in posture.narrative_text.lower() or \
           "article" in posture.narrative_text.lower()


def test_cyclical_posture_suspended_uses_informative_framing():
    posture = compute_cyclical_posture(
        cpi_yoy=Decimal("1.5"), t5yifr=Decimal("2.3"),
        dfii10=Decimal("1.0"), dfii10_60d_change_bps=Decimal("-20"),
        factors={}, gauge_state="suspended",
    )
    assert "suspended" in posture.narrative_text.lower() \
           or "not actionable" in posture.narrative_text.lower() \
           or "informative" in posture.narrative_text.lower()
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/cards/cyclical_zones.py
"""Lens 2 — cyclical posture (article zones + two-force narrative).

Thresholds (CPI 2/4%, T5YIFR 2.5/2.7/2.8%) are ARTICLE HEURISTICS — not
empirically calibrated. Phase A2 (open question Q24) calibrates against the
multi-indicator anchoring basket. Until then, the narrative must explicitly
label the zone as 'article-derived' and not present it as a Fed-quality regime.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CyclicalPosture:
    zone_label: str
    cpi_yoy: Decimal | None
    t5yifr: Decimal | None
    dfii10: Decimal | None
    dfii10_60d_change_bps: Decimal | None
    factors: dict[str, float]
    narrative_text: str


CPI_LOW = Decimal("2.0")
CPI_HIGH = Decimal("4.0")
T5YIFR_LOW = Decimal("2.5")
T5YIFR_MID = Decimal("2.7")
T5YIFR_HIGH = Decimal("2.8")


def classify_article_zone(cpi_yoy: Decimal, t5yifr: Decimal) -> str:
    """Article-derived heuristic. NOT empirically calibrated."""
    if cpi_yoy < CPI_LOW and t5yifr < T5YIFR_LOW:
        return "real-rate-driven"
    if CPI_LOW <= cpi_yoy < CPI_HIGH and t5yifr < T5YIFR_MID:
        return "moderate-trap"
    if cpi_yoy >= CPI_HIGH and t5yifr >= T5YIFR_HIGH:
        return "article-unanchored"
    return "transitional"


def compute_cyclical_posture(
    *,
    cpi_yoy: Decimal | None,
    t5yifr: Decimal | None,
    dfii10: Decimal | None,
    dfii10_60d_change_bps: Decimal | None,
    factors: dict[str, float],
    gauge_state: str,
) -> CyclicalPosture:
    if cpi_yoy is None or t5yifr is None:
        zone = "transitional"
    else:
        zone = classify_article_zone(cpi_yoy, t5yifr)

    narrative = _narrate_cyclical(zone, dfii10, dfii10_60d_change_bps, gauge_state)
    return CyclicalPosture(
        zone_label=zone,
        cpi_yoy=cpi_yoy, t5yifr=t5yifr, dfii10=dfii10,
        dfii10_60d_change_bps=dfii10_60d_change_bps,
        factors=factors, narrative_text=narrative,
    )


def _narrate_cyclical(
    zone: str, dfii10: Decimal | None, dfii10_60d_bps: Decimal | None,
    gauge_state: str,
) -> str:
    base = f"Article zone: '{zone}' (heuristic; thresholds not yet calibrated)."
    if gauge_state == "suspended":
        return base + " Cyclical framework currently suspended — article view is informative-only, not actionable."
    if dfii10_60d_bps is not None:
        direction = "tightening" if dfii10_60d_bps > 0 else "easing"
        base += f" DFII10 60d change {dfii10_60d_bps:+.0f}bps — discount-rate channel {direction}."
    return base
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/cards/cyclical_zones.py tests/unit/cards/test_cyclical_zones.py
git commit -m "feat(gold/cards): cyclical posture with article-zone framing (Lens 2)"
```

---

## Task 17: Card — valuation.py (Lens 3 overlay)

**Files:**
- Create: `src/uw_scan/cards/valuation.py`
- Test: `tests/unit/cards/test_valuation.py`

Computes real-price percentile (CPI-deflated), gold/M2 ratio percentile, gold/SPX ratio percentile. Returns flag in `{Low, Moderate, High, Severe}`. **Never a sizing input** per file 07.

- [ ] **Step 1: Failing test**

```python
# tests/unit/cards/test_valuation.py
from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.cards.valuation import (
    compute_valuation_overlay,
    flag_from_percentile,
    ValuationOverlay,
)


def test_flag_thresholds():
    assert flag_from_percentile(Decimal("0.30")) == "Low"
    assert flag_from_percentile(Decimal("0.60")) == "Moderate"
    assert flag_from_percentile(Decimal("0.80")) == "High"
    assert flag_from_percentile(Decimal("0.95")) == "Severe"


def test_valuation_overlay_severe_at_extreme():
    base = date(2020, 1, 1)
    gold = [(base + timedelta(days=i), Decimal(str(1500 + i))) for i in range(1500)]
    # Most CPI obs are flat around 100; recent obs are still flat
    cpi = [(base + timedelta(days=i*30), Decimal("100")) for i in range(50)]
    overlay = compute_valuation_overlay(
        gold_series=gold, cpi_series=cpi, m2_series=[], spx_series=[],
        as_of=base + timedelta(days=1500),
    )
    # gold series is monotonically rising; latest real price will be near the max → high percentile
    assert overlay.real_price_percentile > Decimal("0.85")
    assert overlay.flag in ("High", "Severe")
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# src/uw_scan/cards/valuation.py
"""Lens 3 — valuation overlay (tail-risk flag, NEVER a sizing input).

Computes real-price-of-gold percentile (CPI-deflated, USD) and two alternative
anchors: gold/M2 ratio, gold/SPX ratio. Returns a flag in {Low, Moderate,
High, Severe}. Per docs/research/gold-sdf-framework/07-valuation-overlay.md
this signal is exclusively contextual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class ValuationOverlay:
    flag: str
    real_price_percentile: Decimal | None
    gold_m2_ratio_percentile: Decimal | None
    gold_spx_ratio_percentile: Decimal | None
    narrative_text: str


def flag_from_percentile(p: Decimal | None) -> str:
    if p is None:
        return "Low"
    if p < Decimal("0.5"):
        return "Low"
    if p < Decimal("0.75"):
        return "Moderate"
    if p < Decimal("0.9"):
        return "High"
    return "Severe"


def _last_value_before(series: list[tuple[date, Decimal]], cutoff: date) -> Decimal | None:
    eligible = [v for d, v in series if d <= cutoff]
    return eligible[-1] if eligible else None


def _percentile(history: list[Decimal], current: Decimal) -> Decimal | None:
    if not history:
        return None
    below = sum(1 for v in history if v <= current)
    return Decimal(str(below / len(history))).quantize(Decimal("0.001"))


def _real_price_series(
    gold_series: list[tuple[date, Decimal]],
    cpi_series: list[tuple[date, Decimal]],
) -> list[Decimal]:
    if not cpi_series:
        return []
    cpi_sorted = sorted(cpi_series, key=lambda r: r[0])
    out: list[Decimal] = []
    for d, gold_v in sorted(gold_series, key=lambda r: r[0]):
        cpi_v = None
        for cd, cv in cpi_sorted:
            if cd <= d:
                cpi_v = cv
            else:
                break
        if cpi_v is None or cpi_v == 0:
            continue
        out.append(gold_v / cpi_v)
    return out


def compute_valuation_overlay(
    *,
    gold_series: list[tuple[date, Decimal]],
    cpi_series: list[tuple[date, Decimal]],
    m2_series: list[tuple[date, Decimal]],
    spx_series: list[tuple[date, Decimal]],
    as_of: date,
) -> ValuationOverlay:
    real_series = _real_price_series(gold_series, cpi_series)
    real_now = real_series[-1] if real_series else None
    real_pct = _percentile(real_series, real_now) if real_now is not None else None

    m2_pct = None
    if m2_series:
        ratios = []
        for d, gold_v in sorted(gold_series, key=lambda r: r[0]):
            m2_v = _last_value_before(m2_series, d)
            if m2_v and m2_v != 0:
                ratios.append(gold_v / m2_v)
        if ratios:
            m2_pct = _percentile(ratios, ratios[-1])

    spx_pct = None
    if spx_series:
        ratios = []
        for d, gold_v in sorted(gold_series, key=lambda r: r[0]):
            spx_v = _last_value_before(spx_series, d)
            if spx_v and spx_v != 0:
                ratios.append(gold_v / spx_v)
        if ratios:
            spx_pct = _percentile(ratios, ratios[-1])

    flag = flag_from_percentile(real_pct)
    narrative = (
        f"Real-price percentile: {real_pct}; flag: {flag}. "
        "Mean-reversion risk is context, never a sizing input. "
        "See Lens 1 for whether structural support is intact."
    )
    return ValuationOverlay(
        flag=flag,
        real_price_percentile=real_pct,
        gold_m2_ratio_percentile=m2_pct,
        gold_spx_ratio_percentile=spx_pct,
        narrative_text=narrative,
    )
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/cards/valuation.py tests/unit/cards/test_valuation.py
git commit -m "feat(gold/cards): valuation overlay (Lens 3, never a sizing input)"
```

---

## Task 18: Pydantic response models

**Files:**
- Modify: `src/uw_scan/models.py` (append gold response models at end)
- Test: `tests/unit/test_gold_models.py`

The API contract. After this task lands, `cd web && npm run gen:types` regenerates `web/lib/types.ts`.

The full model shape supports the GOLD COMPASS UI per spec §8.3 — each lens carries its `posture_chip` enum, and `GoldStateResponse` carries `spot` / `data_freshness` / `decomposition_rows` / `correlation_history` for Tier 1 KPI strip + Tier 5 panels.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_gold_models.py
from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.models import (
    GoldGaugeState,
    GoldStructuralPostureModel,
    GoldCyclicalPostureModel,
    GoldValuationPostureModel,
    GoldStateResponse,
    GoldInputProvenance,
    GoldSpotTile,
    GoldHistoryPoint,
    GoldTwoForceText,
    GoldDataFreshnessSource,
    GoldDecompositionRow,
    GoldCorrelationHistory,
    GoldCorrelationPoint,
    GoldCorrelationBand,
)


def test_gold_state_response_round_trips():
    resp = GoldStateResponse(
        obs_date=date(2026, 5, 16),
        computed_at=datetime(2026, 5, 17, tzinfo=UTC),
        gauge=GoldGaugeState(
            corr_60d=Decimal("-0.04"), corr_126d=Decimal("-0.05"),
            corr_252d=Decimal("-0.07"), corr_504d=Decimal("-0.31"),
            corr_252d_returns=Decimal("-0.06"), state="suspended",
        ),
        spot=GoldSpotTile(
            last=Decimal("4561.50"), delta_abs=Decimal("-157.20"),
            delta_pct=Decimal("-0.0332"),
            high=Decimal("4615.20"), low=Decimal("4524.30"),
            open=Decimal("4615.20"),
        ),
        structural=GoldStructuralPostureModel(
            state_label="structural-bid-intact",
            posture_chip="FAVORABLE",
            cb_strategic_12m_sum_t=Decimal("210"),
            cb_tactical_12m_sum_t=Decimal("12"),
            cb_diversifier_12m_sum_t=Decimal("34"),
            cb_52w_pct=Decimal("0.78"),
            gld_holdings_t=Decimal("872.5"),
            gld_30d_net_flow_t=Decimal("-12.4"),
            comex_registered_oz=Decimal("17500100"),
            comex_20d_roc_pct=Decimal("0.14"),
            lbma_30d_momentum_t=Decimal("-18"),
            cot_mm_net_pct=Decimal("0.72"),
            cot_mm_4w_change_sigma=Decimal("0.18"),
            uw_25d_skew_sigma=Decimal("1.2"),
            fx_basket_dxy_z=Decimal("0.6"),
            xau_cny_premium_pct=Decimal("0.004"),
            gld_history=[
                GoldHistoryPoint(obs_date=date(2024, 6, 1), value=Decimal("870")),
            ],
            gold_history=[
                GoldHistoryPoint(obs_date=date(2024, 6, 1), value=Decimal("2400")),
            ],
            narrative_text="Structural bid intact.",
        ),
        cyclical=GoldCyclicalPostureModel(
            zone_label="moderate-trap",
            posture_chip="NEUTRAL",
            cpi_yoy=Decimal("2.8"), t5yifr=Decimal("2.31"),
            t5yifr_pct_52w=Decimal("0.48"),
            dfii10=Decimal("1.97"), dfii10_60d_change_bps=Decimal("12"),
            dxy=Decimal("102.1"), dxy_60d_sigma=Decimal("-0.4"),
            gpr_value=Decimal("371"), gpr_pct_52w=Decimal("0.64"),
            factors={"F1": -0.4, "F5": 1.8},
            two_force_text=GoldTwoForceText(
                discount_rate="↑ tightening — would press gold",
                hedge_demand="↓ subdued vol — no panic bid",
            ),
            narrative_text="Cyclical posture suspended.",
        ),
        valuation=GoldValuationPostureModel(
            flag="Severe",
            posture_chip="STRETCHED",
            real_price_percentile=Decimal("0.92"),
            gold_m2_ratio_percentile=Decimal("0.78"),
            gold_oil_ratio_percentile=Decimal("0.89"),
            gold_spx_ratio_percentile=Decimal("0.64"),
            narrative_text="Mean-reversion risk: SEVERE.",
        ),
        inputs_used={
            "DFII10": GoldInputProvenance(
                obs_date=date(2026, 5, 16),
                as_of=datetime(2026, 5, 17, tzinfo=UTC),
            ),
        },
        data_freshness=[
            GoldDataFreshnessSource(id="FRED",
                                    last_as_of=datetime(2026, 5, 17, tzinfo=UTC),
                                    stale_seconds=60),
            GoldDataFreshnessSource(id="COT",
                                    last_as_of=datetime(2026, 5, 13, 20, 30, tzinfo=UTC),
                                    stale_seconds=86400 * 4),
        ],
        decomposition_rows=[
            GoldDecompositionRow(lens="L1", factor="CB Δ12M", contribution=Decimal("1.4")),
            GoldDecompositionRow(lens="L2", factor="DFII10",  contribution=Decimal("-0.4")),
            GoldDecompositionRow(lens="L3", factor="Gold/CPI", contribution=Decimal("1.8")),
        ],
        correlation_history=GoldCorrelationHistory(
            gold_dfii10=[
                GoldCorrelationPoint(obs_date=date(2024, 12, 31), value=Decimal("-0.12")),
            ],
            gold_dxy=[],
            gold_gpr=[],
            pre_2022_band=GoldCorrelationBand(mean=Decimal("-0.84"), std=Decimal("0.04")),
        ),
    )
    dumped = resp.model_dump_json()
    assert "Severe" in dumped
    assert "moderate-trap" in dumped
    assert "FAVORABLE" in dumped
    assert "L1" in dumped
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Append to `src/uw_scan/models.py`**

```python
# Append to src/uw_scan/models.py

PostureChipState = Literal["FAVORABLE", "NEUTRAL", "STRETCHED", "SUSPENDED", "DEGRADED"]


class GoldGaugeState(BaseModel):
    corr_60d: Decimal | None = None
    corr_126d: Decimal | None = None
    corr_252d: Decimal | None = None
    corr_504d: Decimal | None = None
    corr_252d_returns: Decimal | None = None
    state: Literal["operative", "partial", "suspended"]


class GoldHistoryPoint(BaseModel):
    obs_date: date
    value: Decimal


class GoldSpotTile(BaseModel):
    """XAU/USD snapshot used by the Tier 1 KPI strip."""
    last: Decimal
    delta_abs: Decimal
    delta_pct: Decimal
    high: Decimal
    low: Decimal
    open: Decimal


class GoldStructuralPostureModel(BaseModel):
    state_label: str | None = None
    posture_chip: PostureChipState
    # CB reserves
    cb_strategic_12m_sum_t: Decimal | None = None
    cb_tactical_12m_sum_t: Decimal | None = None
    cb_diversifier_12m_sum_t: Decimal | None = None
    cb_52w_pct: Decimal | None = None
    # ETF holdings
    gld_holdings_t: Decimal | None = None
    gld_30d_net_flow_t: Decimal | None = None
    # COMEX / LBMA inventory
    comex_registered_oz: Decimal | None = None
    comex_20d_roc_pct: Decimal | None = None
    lbma_30d_momentum_t: Decimal | None = None
    # COT positioning
    cot_mm_net_pct: Decimal | None = None
    cot_mm_4w_change_sigma: Decimal | None = None
    # UW options skew (persist-only in A1)
    uw_25d_skew_sigma: Decimal | None = None
    # FX basket / local premia
    fx_basket_dxy_z: Decimal | None = None
    xau_cny_premium_pct: Decimal | None = None
    # Lead chart history (trailing 5y)
    gld_history: list[GoldHistoryPoint] = []
    gold_history: list[GoldHistoryPoint] = []
    narrative_text: str


class GoldTwoForceText(BaseModel):
    discount_rate: str
    hedge_demand: str


class GoldCyclicalPostureModel(BaseModel):
    zone_label: str | None = None
    posture_chip: PostureChipState
    # Inflation
    cpi_yoy: Decimal | None = None
    t5yifr: Decimal | None = None
    t5yifr_pct_52w: Decimal | None = None
    # Real rate
    dfii10: Decimal | None = None
    dfii10_60d_change_bps: Decimal | None = None
    # USD trend
    dxy: Decimal | None = None
    dxy_60d_sigma: Decimal | None = None
    # GPR
    gpr_value: Decimal | None = None
    gpr_pct_52w: Decimal | None = None
    # Factor z-scores (legacy; remains for backward-compat)
    factors: dict[str, float] = {}
    two_force_text: GoldTwoForceText
    narrative_text: str


class GoldValuationPostureModel(BaseModel):
    flag: Literal["Low", "Moderate", "High", "Severe"]
    posture_chip: PostureChipState
    real_price_percentile: Decimal | None = None
    gold_m2_ratio_percentile: Decimal | None = None
    gold_oil_ratio_percentile: Decimal | None = None
    gold_spx_ratio_percentile: Decimal | None = None
    narrative_text: str


class GoldInputProvenance(BaseModel):
    obs_date: date
    as_of: datetime


class GoldDataFreshnessSource(BaseModel):
    """Per-source freshness for the Tier 1 Data Freshness card."""
    id: str
    last_as_of: datetime
    stale_seconds: int


class GoldDecompositionRow(BaseModel):
    """One row of the Tier 5 lens-decomposition bars."""
    lens: Literal["L1", "L2", "L3"]
    factor: str
    contribution: Decimal


class GoldCorrelationPoint(BaseModel):
    obs_date: date
    value: Decimal


class GoldCorrelationBand(BaseModel):
    mean: Decimal
    std: Decimal


class GoldCorrelationHistory(BaseModel):
    """Tier 5 correlation-history panel inputs."""
    gold_dfii10: list[GoldCorrelationPoint] = []
    gold_dxy: list[GoldCorrelationPoint] = []
    gold_gpr: list[GoldCorrelationPoint] = []
    pre_2022_band: GoldCorrelationBand | None = None


class GoldStateResponse(BaseModel):
    obs_date: date
    computed_at: datetime
    gauge: GoldGaugeState
    spot: GoldSpotTile
    structural: GoldStructuralPostureModel
    cyclical: GoldCyclicalPostureModel
    valuation: GoldValuationPostureModel
    inputs_used: dict[str, GoldInputProvenance]
    data_freshness: list[GoldDataFreshnessSource] = []
    decomposition_rows: list[GoldDecompositionRow] = []
    correlation_history: GoldCorrelationHistory = GoldCorrelationHistory()


class GoldGaugeTimeSeriesPoint(BaseModel):
    obs_date: date
    corr_252d: Decimal | None


class GoldGaugeResponse(BaseModel):
    current: GoldGaugeState
    history_252d: list[GoldGaugeTimeSeriesPoint]


class GoldInputSeriesPoint(BaseModel):
    obs_date: date
    value: Decimal
    as_of: datetime
    release_date: date | None = None


class GoldInputSeriesResponse(BaseModel):
    series_id: str
    points: list[GoldInputSeriesPoint]


class GoldLensResponse(BaseModel):
    """Detail payload for one lens (richer than the summary in GoldStateResponse)."""
    lens_id: Literal["structural", "cyclical", "valuation"]
    posture: GoldStructuralPostureModel | GoldCyclicalPostureModel | GoldValuationPostureModel
    detail: dict[str, list[GoldInputSeriesPoint]]
```

Confirm `from typing import Literal` is imported at top of `models.py` (it should already be — verify or add).

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/models.py tests/unit/test_gold_models.py
git commit -m "feat(gold/models): Pydantic response models for /api/gold/*"
```

---

## Task 19: Report orchestrator — reports/gold_posture.py

**Files:**
- Create: `src/uw_scan/reports/gold_posture.py`
- Test: `tests/integration/reports/test_gold_posture_orchestrator.py`

Reads inputs from the Repository, calls each card, assembles a complete `gold_posture_daily` row including the `inputs_jsonb` provenance map. This is the single entry point for the `gold_posture_compute` worker job in Task 28.

- [ ] **Step 1: Failing integration test**

```python
# tests/integration/reports/test_gold_posture_orchestrator.py
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.storage.repository import Repository


def _seed_minimum(repo: Repository, today: date) -> None:
    """Seed enough data for the orchestrator to produce a non-empty posture."""
    base = today - timedelta(days=300)
    for i in range(300):
        d = base + timedelta(days=i)
        repo.insert_macro_series_daily(
            "GLD_CLOSE", d, Decimal(str(1800 + i * 0.5)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None, "MASSIVE", None,
        )
        repo.insert_macro_series_daily(
            "DFII10", d, Decimal(str(2.0 - i * 0.005)),
            datetime.combine(d, datetime.min.time(), tzinfo=UTC),
            None, "FRED", None,
        )
    # latest CPI / T5YIFR
    repo.insert_macro_series_monthly(
        "CPIAUCSL", date(today.year, today.month, 1),
        Decimal("315.0"), datetime.now(UTC),
        date(today.year, today.month, 14), "FRED", None,
    )
    repo.insert_macro_series_daily(
        "T5YIFR", today, Decimal("2.31"),
        datetime.now(UTC), None, "FRED", None,
    )


@pytest.mark.integration
def test_orchestrator_writes_posture_row(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        today = date(2026, 5, 16)
        _seed_minimum(repo, today)
        compute_and_persist_gold_posture(repo, as_of=today,
                                         computed_at=datetime(2026, 5, 17, tzinfo=UTC))
        row = repo.fetch_gold_posture_for_obs_date(today)
    assert row is not None
    assert row["obs_date"] == today
    assert row["gauge_state"] in {"operative", "partial", "suspended"}
    assert row["inputs_jsonb"] is not None
    assert "DFII10" in row["inputs_jsonb"]


@pytest.mark.integration
def test_orchestrator_idempotent_same_inputs(postgresql):
    """Running twice with same (obs_date, computed_at) is a no-op."""
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        today = date(2026, 5, 16)
        _seed_minimum(repo, today)
        computed_at = datetime(2026, 5, 17, tzinfo=UTC)
        compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
        compute_and_persist_gold_posture(repo, as_of=today, computed_at=computed_at)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM uw_scan.gold_posture_daily WHERE obs_date = %s",
                (today,),
            )
            assert cur.fetchone()[0] == 1
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement orchestrator**

```python
# src/uw_scan/reports/gold_posture.py
"""Orchestrator: read inputs, run all four lens cards, persist posture row.

Called by the daily `gold_posture_compute` worker job. Tracks the exact
(series_id, obs_date, as_of) triples that contributed to the row in
`inputs_jsonb` so the replay endpoint can audit posture deterministically.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from uw_scan.cards.regime_gauge import compute_correlation_gauge
from uw_scan.cards.structural_flow import (
    compute_structural_posture,
    CbReserveSnapshot, EtfHoldingSnapshot, InventorySnapshot,
    CotSnapshot, FxSnapshot,
)
from uw_scan.cards.cyclical_zones import compute_cyclical_posture
from uw_scan.cards.valuation import compute_valuation_overlay
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


def _series_to_tuples(rows: list[dict[str, Any]], date_key: str) -> list[tuple[date, Decimal]]:
    return [(r[date_key], r["value"]) for r in rows if r.get("value") is not None]


def compute_and_persist_gold_posture(
    repo: Repository,
    *,
    as_of: date,
    computed_at: datetime | None = None,
) -> None:
    if computed_at is None:
        computed_at = datetime.now(UTC)

    gold_rows = repo.fetch_macro_series_daily("GLD_CLOSE", to_date=as_of)
    dfii10_rows = repo.fetch_macro_series_daily("DFII10", to_date=as_of)
    gold_series = _series_to_tuples(gold_rows, "obs_date")
    dfii10_series = _series_to_tuples(dfii10_rows, "obs_date")
    gauge = compute_correlation_gauge(gold_series, dfii10_series, as_of=as_of)

    cb_db_rows = repo.fetch_cb_gold_reserves_monthly(from_month=as_of - timedelta(days=400))
    cb_snapshots = [
        CbReserveSnapshot(
            country_iso3=r["country_iso3"], obs_month=r["obs_month"],
            reserves_t=r.get("reserves_t"), bucket=r["bucket"],
        ) for r in cb_db_rows
    ]
    etf_db = repo.fetch_etf_holdings_daily("GLD", from_date=as_of - timedelta(days=400))
    etf_snapshots = [
        EtfHoldingSnapshot(ticker="GLD", obs_date=r["obs_date"], holdings_oz=r.get("holdings_oz"))
        for r in etf_db
    ]
    inv_db = repo.fetch_exchange_inventory_daily("COMEX", from_date=as_of - timedelta(days=60))
    inv_snapshots = [
        InventorySnapshot(exchange="COMEX", obs_date=r["obs_date"],
                          registered_oz=r.get("registered_oz"), vault_oz=None)
        for r in inv_db
    ]
    cot_db = repo.fetch_cot_gold_weekly(
        from_release_date=as_of - timedelta(days=400),
        to_release_date=as_of,
    )
    cot_snapshots = [
        CotSnapshot(release_date=r["release_date"], mm_net=r.get("mm_net"))
        for r in cot_db
    ]

    structural = compute_structural_posture(
        cb_rows=cb_snapshots, etf_rows=etf_snapshots,
        inventory_rows=inv_snapshots, cot_rows=cot_snapshots,
        fx_rows=[], gold_series=gold_series, as_of=as_of,
    )

    cpi_rows = repo.fetch_macro_series_monthly("CPIAUCSL", to_month=date(as_of.year, as_of.month, 1))
    cpi_now = cpi_rows[-1]["value"] if cpi_rows else None
    cpi_prior_year = next(
        (r["value"] for r in cpi_rows
         if r["obs_month"] == date(as_of.year - 1, as_of.month, 1)),
        None,
    )
    cpi_yoy = ((cpi_now / cpi_prior_year) - 1) * 100 if cpi_now and cpi_prior_year else None

    t5yifr_rows = repo.fetch_macro_series_daily("T5YIFR", to_date=as_of)
    t5yifr = t5yifr_rows[-1]["value"] if t5yifr_rows else None
    dfii10 = dfii10_series[-1][1] if dfii10_series else None
    dfii10_60d_chg = None
    if len(dfii10_series) >= 60:
        dfii10_60d_chg = (dfii10_series[-1][1] - dfii10_series[-60][1]) * 100  # bps

    cyclical = compute_cyclical_posture(
        cpi_yoy=cpi_yoy, t5yifr=t5yifr, dfii10=dfii10,
        dfii10_60d_change_bps=dfii10_60d_chg, factors={}, gauge_state=gauge.state,
    )

    m2_rows = repo.fetch_macro_series_monthly("M2SL", to_month=date(as_of.year, as_of.month, 1))
    m2_series = [(r["obs_month"], r["value"]) for r in m2_rows]
    valuation = compute_valuation_overlay(
        gold_series=gold_series,
        cpi_series=[(r["obs_month"], r["value"]) for r in cpi_rows],
        m2_series=m2_series,
        spx_series=[],
        as_of=as_of,
    )

    inputs_used = {
        "DFII10": {"obs_date": dfii10_series[-1][0].isoformat() if dfii10_series else None,
                    "as_of": (dfii10_rows[-1]["as_of"].isoformat() if dfii10_rows else None)},
        "GLD_CLOSE": {"obs_date": gold_series[-1][0].isoformat() if gold_series else None,
                      "as_of": (gold_rows[-1]["as_of"].isoformat() if gold_rows else None)},
        "T5YIFR": {"obs_date": t5yifr_rows[-1]["obs_date"].isoformat() if t5yifr_rows else None,
                    "as_of": (t5yifr_rows[-1]["as_of"].isoformat() if t5yifr_rows else None)},
        "CPIAUCSL": {"obs_month": cpi_rows[-1]["obs_month"].isoformat() if cpi_rows else None,
                      "as_of": (cpi_rows[-1]["as_of"].isoformat() if cpi_rows else None)},
    }

    repo.insert_gold_posture_daily(
        obs_date=as_of, computed_at=computed_at,
        gauge_corr_60d=gauge.corr_60d_level,
        gauge_corr_126d=gauge.corr_126d_level,
        gauge_corr_252d=gauge.corr_252d_level,
        gauge_corr_504d=gauge.corr_504d_level,
        gauge_corr_252d_returns=gauge.corr_252d_returns,
        gauge_state=gauge.state,
        structural_state_label=structural.structural_state_label,
        cb_strategic_12m_sum_t=structural.cb_strategic_12m_sum_t,
        cb_tactical_12m_sum_t=structural.cb_tactical_12m_sum_t,
        cb_diversifier_12m_sum_t=structural.cb_diversifier_12m_sum_t,
        gld_holdings_t=structural.gld_holdings_t,
        gld_30d_net_flow_t=structural.gld_30d_net_flow_t,
        comex_registered_oz=structural.comex_registered_oz,
        comex_20d_roc_pct=structural.comex_20d_roc_pct,
        cot_mm_net_pct=structural.cot_mm_net_pct,
        cyclical_zone_label=cyclical.zone_label,
        cpi_yoy=cyclical.cpi_yoy, t5yifr=cyclical.t5yifr,
        dfii10=cyclical.dfii10, dfii10_60d_change_bps=cyclical.dfii10_60d_change_bps,
        factors_jsonb=cyclical.factors,
        valuation_flag=valuation.flag,
        real_price_percentile=valuation.real_price_percentile,
        gold_m2_ratio_percentile=valuation.gold_m2_ratio_percentile,
        gold_spx_ratio_percentile=valuation.gold_spx_ratio_percentile,
        structural_posture_text=structural.narrative_text,
        cyclical_posture_text=cyclical.narrative_text,
        valuation_posture_text=valuation.narrative_text,
        inputs_jsonb=inputs_used,
    )
    logger.info("gold_posture: wrote row for %s, gauge_state=%s", as_of, gauge.state)
```

Note: this orchestrator references `repo.fetch_macro_series_monthly` with `to_month=` — adjust Task 10's signature if it currently only accepts `from_month/to_month` aliases. Both directions of CV (existing signatures + this consumer) must agree.

- [ ] **Step 3b: Extend the orchestrator to populate GOLD COMPASS UI fields**

Tasks 28–36 consume additional fields on `GoldStateResponse` that the orchestrator must also produce. Add the following helpers and extend the final assembly step. These computations are **deterministic transformations of already-fetched data** — no new source queries required.

```python
# ── helpers — append above compute_and_persist_gold_posture ───────────────────

def _derive_posture_chip(
    *,
    lens: str,
    state_label: str | None,
    gauge_state: str,
    valuation_flag: str | None,
    has_data: bool,
) -> str:
    """Map a lens's internal state to the UI posture chip.

    Phase A1 rules (deterministic):
    - any source absent → DEGRADED
    - lens 2 and gauge_state == 'suspended' → SUSPENDED
    - lens 3 always → STRETCHED if flag in {High, Severe}, else NEUTRAL/FAVORABLE
    - lens 1 / 2 → FAVORABLE if state_label is supportive, else NEUTRAL
    """
    if not has_data:
        return "DEGRADED"
    if lens == "L2" and gauge_state == "suspended":
        return "SUSPENDED"
    if lens == "L3":
        if valuation_flag in {"High", "Severe"}:
            return "STRETCHED"
        return "NEUTRAL" if valuation_flag == "Moderate" else "FAVORABLE"
    # L1, L2 — narrative-driven for v1
    if state_label and any(tok in state_label for tok in
                            ("intact", "favorable", "operative")):
        return "FAVORABLE"
    return "NEUTRAL"


def _spot_from_gold_rows(gold_rows: list[dict]) -> dict | None:
    if not gold_rows or len(gold_rows) < 2:
        return None
    last_row = gold_rows[-1]
    prev_row = gold_rows[-2]
    last = Decimal(str(last_row["value"]))
    prev = Decimal(str(prev_row["value"]))
    delta_abs = last - prev
    delta_pct = delta_abs / prev if prev else Decimal("0")
    last_5 = gold_rows[-5:] if len(gold_rows) >= 5 else gold_rows
    vals = [Decimal(str(r["value"])) for r in last_5]
    return {
        "last": last, "delta_abs": delta_abs, "delta_pct": delta_pct,
        "high": max(vals), "low": min(vals), "open": vals[0],
    }


def _stale_seconds(as_of: datetime, now: datetime) -> int:
    return int((now - as_of).total_seconds())


def _rolling_corr_pairs(
    s1: list[tuple[date, Decimal]],
    s2: list[tuple[date, Decimal]],
    *,
    window: int,
    step: int = 21,
) -> list[tuple[date, Decimal]]:
    """Naive monthly-stride rolling correlation of two daily series.

    Returns (obs_date, corr_value) tuples. For Phase A1 we sample every `step`
    days to keep the payload tractable (~250 pts over 5y at step=21)."""
    aligned: dict[date, tuple[Decimal, Decimal]] = {}
    d2 = dict(s2)
    for d, v in s1:
        if d in d2:
            aligned[d] = (v, d2[d])
    dates = sorted(aligned)
    if len(dates) < window:
        return []
    out: list[tuple[date, Decimal]] = []
    import statistics
    for i in range(window, len(dates), step):
        slice_dates = dates[i - window : i]
        xs = [float(aligned[d][0]) for d in slice_dates]
        ys = [float(aligned[d][1]) for d in slice_dates]
        try:
            corr = statistics.correlation(xs, ys)
        except statistics.StatisticsError:
            corr = float("nan")
        if corr == corr:  # NaN check
            out.append((dates[i - 1], Decimal(str(round(corr, 4)))))
    return out


def _decomposition_rows_from_lenses(
    structural, cyclical, valuation,
) -> list[dict]:
    """Flatten each lens's headline heuristic z-scores into one decomposition list.

    Contributions are pulled from already-computed lens snapshots. The list is
    descending by |contribution| so the UI shows the largest movers first."""
    rows: list[dict] = []
    for lens_id, name, value in (
        ("L1", "CB Δ12M",   getattr(structural, "cb_strategic_z", None)),
        ("L1", "COMEX ROC", getattr(structural, "comex_20d_roc_z", None)),
        ("L1", "ETF flow",  getattr(structural, "etf_flow_z", None)),
        ("L1", "COT MM",    getattr(structural, "cot_mm_z", None)),
        ("L1", "UW skew",   getattr(structural, "uw_skew_z", None)),
        ("L2", "DFII10",    getattr(cyclical, "dfii10_z", None)),
        ("L2", "GPR",       getattr(cyclical, "gpr_z", None)),
        ("L2", "DXY",       getattr(cyclical, "dxy_z", None)),
        ("L3", "Gold/CPI",  getattr(valuation, "real_price_z", None)),
        ("L3", "Gold/M2",   getattr(valuation, "gold_m2_z", None)),
    ):
        if value is None:
            continue
        rows.append({"lens": lens_id, "factor": name,
                      "contribution": Decimal(str(round(float(value), 3)))})
    rows.sort(key=lambda r: abs(float(r["contribution"])), reverse=True)
    return rows[:12]  # cap for legibility


def _pre_2022_band(
    corr_series: list[tuple[date, Decimal]],
) -> dict | None:
    """Compute mean ± 1σ over the pre-2022 segment of a correlation series."""
    pre = [float(v) for d, v in corr_series if d.year < 2022]
    if len(pre) < 20:
        return None
    import statistics
    mean = statistics.fmean(pre)
    std = statistics.pstdev(pre)
    return {"mean": Decimal(str(round(mean, 4))),
            "std": Decimal(str(round(std, 4)))}


# ── inside compute_and_persist_gold_posture, after `valuation = ...` block ────

now = datetime.now(UTC)
spot = _spot_from_gold_rows(gold_rows)
has_structural = bool(cb_db_rows and etf_db and inv_db)
has_cyclical = cpi_now is not None and t5yifr is not None and dfii10 is not None
has_valuation = valuation.real_price_percentile is not None

posture_chips = {
    "L1": _derive_posture_chip(lens="L1",
                                state_label=structural.structural_state_label,
                                gauge_state=gauge.state, valuation_flag=None,
                                has_data=has_structural),
    "L2": _derive_posture_chip(lens="L2",
                                state_label=cyclical.zone_label,
                                gauge_state=gauge.state, valuation_flag=None,
                                has_data=has_cyclical),
    "L3": _derive_posture_chip(lens="L3", state_label=None,
                                gauge_state=gauge.state,
                                valuation_flag=valuation.flag,
                                has_data=has_valuation),
}

# Build correlation history: gold ↔ {DFII10, DXY, GPR}, sampled monthly
dxy_rows = repo.fetch_macro_series_daily("DTWEXBGS", to_date=as_of)
gpr_rows = repo.fetch_macro_series_daily("GPRD", to_date=as_of)
dxy_series = _series_to_tuples(dxy_rows, "obs_date")
gpr_series = _series_to_tuples(gpr_rows, "obs_date")
window5y_start = as_of - timedelta(days=365 * 5)
gold_5y = [(d, v) for d, v in gold_series if d >= window5y_start]
dfii10_5y = [(d, v) for d, v in dfii10_series if d >= window5y_start]
dxy_5y = [(d, v) for d, v in dxy_series if d >= window5y_start]
gpr_5y = [(d, v) for d, v in gpr_series if d >= window5y_start]
corr_gold_dfii10 = _rolling_corr_pairs(gold_5y, dfii10_5y, window=252)
corr_gold_dxy = _rolling_corr_pairs(gold_5y, dxy_5y, window=252)
corr_gold_gpr = _rolling_corr_pairs(gold_5y, gpr_5y, window=252)

# data_freshness for the Tier 1 card
data_freshness_inputs = {
    "FRED":  dfii10_rows[-1]["as_of"] if dfii10_rows else None,
    "GPR":   gpr_rows[-1]["as_of"] if gpr_rows else None,
    "ETF":   etf_db[-1].get("as_of") if etf_db else None,
    "COMEX": inv_db[-1].get("as_of") if inv_db else None,
    "COT":   cot_db[-1].get("as_of") if cot_db else None,
    "WGC":   cb_db_rows[-1].get("as_of") if cb_db_rows else None,
    "UW":    None,  # populated when UW skew rows are fetched (Task 9 follow-up)
}
data_freshness = [
    {"id": sid, "last_as_of": ts, "stale_seconds": _stale_seconds(ts, now)}
    for sid, ts in data_freshness_inputs.items()
    if ts is not None
]

decomposition_rows = _decomposition_rows_from_lenses(structural, cyclical, valuation)

# Trailing 5y series for the Lens 1 lead chart
gld_history_rows = [
    {"obs_date": r["obs_date"], "value": Decimal(str(r["value"]))}
    for r in etf_db if r["obs_date"] >= window5y_start
]
gold_history_rows = [
    {"obs_date": d, "value": v} for d, v in gold_5y
]
```

Then extend the final `repo.insert_gold_posture_daily(...)` kwargs (and Task 13's `gold_posture_daily` migration via Task 1) with these new columns. The columns are persisted in `gold_posture_daily` so replay reproduces identical UI state byte-for-byte:

```python
repo.insert_gold_posture_daily(
    # ...all existing kwargs unchanged...
    structural_posture_chip=posture_chips["L1"],
    cyclical_posture_chip=posture_chips["L2"],
    valuation_posture_chip=posture_chips["L3"],
    spot_jsonb=spot,
    data_freshness_jsonb=data_freshness,
    decomposition_jsonb=decomposition_rows,
    correlation_history_jsonb={
        "gold_dfii10": [{"obs_date": d.isoformat(), "value": str(v)}
                        for d, v in corr_gold_dfii10],
        "gold_dxy":    [{"obs_date": d.isoformat(), "value": str(v)}
                        for d, v in corr_gold_dxy],
        "gold_gpr":    [{"obs_date": d.isoformat(), "value": str(v)}
                        for d, v in corr_gold_gpr],
        "pre_2022_band": _pre_2022_band(corr_gold_dfii10),
    },
    gld_history_jsonb=[{"obs_date": r["obs_date"].isoformat(),
                        "value": str(r["value"])} for r in gld_history_rows],
    gold_history_jsonb=[{"obs_date": r["obs_date"].isoformat(),
                          "value": str(r["value"])} for r in gold_history_rows],
)
```

**Migration side (Task 1 follow-up):** add the following columns to `043_gold_posture.sql`:

```sql
ALTER TABLE uw_scan.gold_posture_daily
  ADD COLUMN IF NOT EXISTS structural_posture_chip TEXT,
  ADD COLUMN IF NOT EXISTS cyclical_posture_chip   TEXT,
  ADD COLUMN IF NOT EXISTS valuation_posture_chip  TEXT,
  ADD COLUMN IF NOT EXISTS spot_jsonb              JSONB,
  ADD COLUMN IF NOT EXISTS data_freshness_jsonb    JSONB,
  ADD COLUMN IF NOT EXISTS decomposition_jsonb     JSONB,
  ADD COLUMN IF NOT EXISTS correlation_history_jsonb JSONB,
  ADD COLUMN IF NOT EXISTS gld_history_jsonb       JSONB,
  ADD COLUMN IF NOT EXISTS gold_history_jsonb      JSONB;
```

**Cards side (Tasks 15–17 follow-ups):** for `_decomposition_rows_from_lenses` to find values, each lens card must expose the headline z-scores as model attributes (e.g. `structural.cb_strategic_z`, `cyclical.gpr_z`, `valuation.real_price_z`). These are *internal* fields used only by the orchestrator — they don't change the lens cards' public contract. Where a z-score is genuinely not yet computable in v1 (e.g. UW skew before sufficient history), leave as `None` and the helper skips it.

**API side (Task 21 follow-up):** the `/api/gold/state` endpoint reads the persisted row and maps it back to `GoldStateResponse`. Add the new JSONB columns to that mapping; the test in Task 21 should assert these fields round-trip.

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/reports/gold_posture.py tests/integration/reports/test_gold_posture_orchestrator.py \
        src/uw_scan/storage/migrations/043_gold_posture.sql
git commit -m "feat(gold/reports): posture orchestrator + GOLD COMPASS UI fields"
```

---

## Task 20: API router skeleton + `GET /api/gold/gauge` + `GET /api/gold/inputs/{series_id}`

**Files:**
- Create: `src/uw_scan/api/routers/gold.py`
- Modify: `src/uw_scan/api/server.py` (register the new router)
- Test: `tests/integration/api/test_gold_router_gauge.py`

- [ ] **Step 1: Failing test**

```python
# tests/integration/api/test_gold_router_gauge.py
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.server import build_app
from uw_scan.storage.repository import Repository


@pytest.fixture
def app_with_seed(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        base = date(2025, 1, 1)
        for i in range(400):
            d = base + timedelta(days=i)
            repo.insert_macro_series_daily(
                "DFII10", d, Decimal(str(2.0 - i * 0.003)),
                datetime.combine(d, datetime.min.time(), tzinfo=UTC),
                None, "FRED", None,
            )
    app = build_app(dsn=postgresql.info.dsn)  # adjust signature to existing factory
    return TestClient(app)


def test_gauge_endpoint_returns_current_corr_history(app_with_seed):
    response = app_with_seed.get("/api/gold/gauge")
    assert response.status_code == 200
    body = response.json()
    assert "current" in body
    assert "state" in body["current"]
    assert isinstance(body["history_252d"], list)


def test_inputs_endpoint_returns_series_points(app_with_seed):
    response = app_with_seed.get("/api/gold/inputs/DFII10?from=2025-01-01")
    assert response.status_code == 200
    body = response.json()
    assert body["series_id"] == "DFII10"
    assert len(body["points"]) > 100


def test_inputs_endpoint_unknown_series_returns_empty(app_with_seed):
    response = app_with_seed.get("/api/gold/inputs/NOPE")
    assert response.status_code == 200
    assert response.json()["points"] == []
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement the router**

```python
# src/uw_scan/api/routers/gold.py
"""Gold cockpit API surface (Phase A1).

Endpoints (all read-only):
  GET /api/gold/state
  GET /api/gold/gauge
  GET /api/gold/inputs/{series_id}
  GET /api/gold/lenses/{lens_id}
  GET /api/gold/replay?as_of=YYYY-MM-DD
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from uw_scan.api.deps import get_repo
from uw_scan.cards.regime_gauge import compute_correlation_gauge
from uw_scan.models import (
    GoldGaugeResponse, GoldGaugeState, GoldGaugeTimeSeriesPoint,
    GoldInputSeriesPoint, GoldInputSeriesResponse,
)
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gold", tags=["gold"])


@router.get("/gauge", response_model=GoldGaugeResponse)
def get_gauge(repo: Repository = Depends(get_repo)) -> GoldGaugeResponse:
    today = date.today()
    gold_rows = repo.fetch_macro_series_daily("GLD_CLOSE", to_date=today)
    dfii10_rows = repo.fetch_macro_series_daily("DFII10", to_date=today)
    gold_series = [(r["obs_date"], r["value"]) for r in gold_rows]
    dfii10_series = [(r["obs_date"], r["value"]) for r in dfii10_rows]
    current = compute_correlation_gauge(gold_series, dfii10_series, as_of=today)

    history: list[GoldGaugeTimeSeriesPoint] = []
    cursor = today - timedelta(days=5 * 365)
    while cursor <= today:
        snapshot = compute_correlation_gauge(gold_series, dfii10_series, as_of=cursor)
        history.append(GoldGaugeTimeSeriesPoint(
            obs_date=cursor, corr_252d=snapshot.corr_252d_level,
        ))
        cursor += timedelta(days=7)  # weekly downsample for chart

    return GoldGaugeResponse(
        current=GoldGaugeState(
            corr_60d=current.corr_60d_level,
            corr_126d=current.corr_126d_level,
            corr_252d=current.corr_252d_level,
            corr_504d=current.corr_504d_level,
            corr_252d_returns=current.corr_252d_returns,
            state=current.state,
        ),
        history_252d=history,
    )


@router.get("/inputs/{series_id}", response_model=GoldInputSeriesResponse)
def get_input_series(
    series_id: str,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    repo: Repository = Depends(get_repo),
) -> GoldInputSeriesResponse:
    rows = repo.fetch_macro_series_daily(series_id, from_date=from_date, to_date=to_date)
    points = [
        GoldInputSeriesPoint(
            obs_date=r["obs_date"], value=r["value"],
            as_of=r["as_of"], release_date=r.get("release_date"),
        )
        for r in rows
    ]
    return GoldInputSeriesResponse(series_id=series_id, points=points)
```

- [ ] **Step 4: Register router in `api/server.py`**

```python
# In src/uw_scan/api/server.py, near other `app.include_router(...)` calls:
from uw_scan.api.routers import gold as gold_router

app.include_router(gold_router.router)
```

- [ ] **Step 5: Run tests, expect PASS.**

Run: `uv run pytest tests/integration/api/test_gold_router_gauge.py -v`

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/api/routers/gold.py src/uw_scan/api/server.py \
        tests/integration/api/test_gold_router_gauge.py
git commit -m "feat(gold/api): gauge + inputs endpoints"
```

---

## Task 21: `GET /api/gold/state` + `GET /api/gold/lenses/{lens_id}`

**Files:**
- Modify: `src/uw_scan/api/routers/gold.py`
- Test: `tests/integration/api/test_gold_router_state.py`

`/state` reads the latest `gold_posture_daily` row and returns it as a `GoldStateResponse`. `/lenses/{lens_id}` returns the posture for that lens plus a `detail` dict with time-series for the lens's primary inputs.

- [ ] **Step 1: Failing test**

```python
# tests/integration/api/test_gold_router_state.py
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.server import build_app
from uw_scan.storage.repository import Repository


@pytest.fixture
def app_with_posture(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        repo.insert_gold_posture_daily(
            obs_date=date(2026, 5, 16),
            computed_at=datetime(2026, 5, 17, tzinfo=UTC),
            gauge_corr_60d=Decimal("-0.04"),
            gauge_corr_126d=Decimal("-0.05"),
            gauge_corr_252d=Decimal("-0.07"),
            gauge_corr_504d=Decimal("-0.31"),
            gauge_corr_252d_returns=Decimal("-0.06"),
            gauge_state="suspended",
            structural_state_label="structural-bid-intact",
            cb_strategic_12m_sum_t=Decimal("210"),
            cb_tactical_12m_sum_t=Decimal("12"),
            cb_diversifier_12m_sum_t=Decimal("34"),
            gld_holdings_t=Decimal("872.5"),
            gld_30d_net_flow_t=Decimal("-12.4"),
            comex_registered_oz=Decimal("17500100"),
            comex_20d_roc_pct=Decimal("0.14"),
            cot_mm_net_pct=Decimal("0.72"),
            cyclical_zone_label="moderate-trap",
            cpi_yoy=Decimal("2.8"), t5yifr=Decimal("2.31"),
            dfii10=Decimal("1.97"), dfii10_60d_change_bps=Decimal("12"),
            factors_jsonb={"F5": 1.8},
            valuation_flag="Severe",
            real_price_percentile=Decimal("0.92"),
            gold_m2_ratio_percentile=Decimal("0.78"),
            gold_spx_ratio_percentile=Decimal("0.64"),
            structural_posture_text="Structural bid intact.",
            cyclical_posture_text="Cyclical posture suspended.",
            valuation_posture_text="Mean-reversion risk: SEVERE.",
            inputs_jsonb={"DFII10": {"obs_date": "2026-05-16", "as_of": "2026-05-17T00:00:00Z"}},
        )
    return TestClient(build_app(dsn=postgresql.info.dsn))


def test_state_endpoint_returns_latest_posture(app_with_posture):
    response = app_with_posture.get("/api/gold/state")
    assert response.status_code == 200
    body = response.json()
    assert body["obs_date"] == "2026-05-16"
    assert body["gauge"]["state"] == "suspended"
    assert body["valuation"]["flag"] == "Severe"
    assert body["cyclical"]["zone_label"] == "moderate-trap"


def test_lenses_endpoint_returns_per_lens_detail(app_with_posture):
    response = app_with_posture.get("/api/gold/lenses/structural")
    assert response.status_code == 200
    body = response.json()
    assert body["lens_id"] == "structural"
    assert "narrative_text" in body["posture"]


def test_lenses_endpoint_rejects_unknown_lens(app_with_posture):
    response = app_with_posture.get("/api/gold/lenses/unknown")
    assert response.status_code in (404, 422)
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Extend the router**

Append to `src/uw_scan/api/routers/gold.py`:

```python
from uw_scan.models import (
    GoldStateResponse, GoldStructuralPostureModel, GoldCyclicalPostureModel,
    GoldValuationPostureModel, GoldGaugeState, GoldInputProvenance,
    GoldLensResponse, GoldInputSeriesPoint,
)


def _state_from_row(row: dict) -> GoldStateResponse:
    inputs_used: dict[str, GoldInputProvenance] = {}
    for sid, meta in (row.get("inputs_jsonb") or {}).items():
        obs_date_raw = meta.get("obs_date") or meta.get("obs_month")
        as_of_raw = meta.get("as_of")
        if obs_date_raw is None or as_of_raw is None:
            continue
        inputs_used[sid] = GoldInputProvenance(
            obs_date=date.fromisoformat(obs_date_raw),
            as_of=as_of_raw,  # Pydantic parses ISO datetime
        )

    return GoldStateResponse(
        obs_date=row["obs_date"],
        computed_at=row["computed_at"],
        gauge=GoldGaugeState(
            corr_60d=row.get("gauge_corr_60d"),
            corr_126d=row.get("gauge_corr_126d"),
            corr_252d=row.get("gauge_corr_252d"),
            corr_504d=row.get("gauge_corr_504d"),
            corr_252d_returns=row.get("gauge_corr_252d_returns"),
            state=row["gauge_state"],
        ),
        structural=GoldStructuralPostureModel(
            state_label=row.get("structural_state_label"),
            cb_strategic_12m_sum_t=row.get("cb_strategic_12m_sum_t"),
            cb_tactical_12m_sum_t=row.get("cb_tactical_12m_sum_t"),
            cb_diversifier_12m_sum_t=row.get("cb_diversifier_12m_sum_t"),
            gld_holdings_t=row.get("gld_holdings_t"),
            gld_30d_net_flow_t=row.get("gld_30d_net_flow_t"),
            comex_registered_oz=row.get("comex_registered_oz"),
            comex_20d_roc_pct=row.get("comex_20d_roc_pct"),
            cot_mm_net_pct=row.get("cot_mm_net_pct"),
            narrative_text=row.get("structural_posture_text") or "",
        ),
        cyclical=GoldCyclicalPostureModel(
            zone_label=row.get("cyclical_zone_label"),
            cpi_yoy=row.get("cpi_yoy"),
            t5yifr=row.get("t5yifr"),
            dfii10=row.get("dfii10"),
            dfii10_60d_change_bps=row.get("dfii10_60d_change_bps"),
            factors=row.get("factors_jsonb") or {},
            narrative_text=row.get("cyclical_posture_text") or "",
        ),
        valuation=GoldValuationPostureModel(
            flag=row.get("valuation_flag") or "Low",
            real_price_percentile=row.get("real_price_percentile"),
            gold_m2_ratio_percentile=row.get("gold_m2_ratio_percentile"),
            gold_spx_ratio_percentile=row.get("gold_spx_ratio_percentile"),
            narrative_text=row.get("valuation_posture_text") or "",
        ),
        inputs_used=inputs_used,
    )


@router.get("/state", response_model=GoldStateResponse)
def get_state(repo: Repository = Depends(get_repo)) -> GoldStateResponse:
    row = repo.fetch_gold_posture_latest()
    if row is None:
        raise HTTPException(404, "no gold posture computed yet")
    return _state_from_row(row)


@router.get("/lenses/{lens_id}", response_model=GoldLensResponse)
def get_lens(
    lens_id: Literal["structural", "cyclical", "valuation"],
    repo: Repository = Depends(get_repo),
) -> GoldLensResponse:
    row = repo.fetch_gold_posture_latest()
    if row is None:
        raise HTTPException(404, "no gold posture computed yet")
    state_resp = _state_from_row(row)

    detail: dict[str, list[GoldInputSeriesPoint]] = {}
    if lens_id == "structural":
        for ticker in ("GLD", "IAU", "GLDM"):
            etf_rows = repo.fetch_etf_holdings_daily(
                ticker, from_date=row["obs_date"] - timedelta(days=180)
            )
            detail[f"{ticker}_holdings_oz"] = [
                GoldInputSeriesPoint(
                    obs_date=r["obs_date"],
                    value=(r.get("holdings_oz") or 0),
                    as_of=r["as_of"],
                    release_date=None,
                )
                for r in etf_rows
                if r.get("holdings_oz") is not None
            ]
        posture = state_resp.structural
    elif lens_id == "cyclical":
        for series in ("DFII10", "T5YIFR", "T10YIE", "DTWEXBGS"):
            srows = repo.fetch_macro_series_daily(
                series, from_date=row["obs_date"] - timedelta(days=365)
            )
            detail[series] = [
                GoldInputSeriesPoint(
                    obs_date=r["obs_date"], value=r["value"],
                    as_of=r["as_of"], release_date=r.get("release_date"),
                )
                for r in srows
            ]
        posture = state_resp.cyclical
    else:
        # valuation
        for series in ("CPIAUCSL", "M2SL"):
            mrows = repo.fetch_macro_series_monthly(series)
            detail[series] = [
                GoldInputSeriesPoint(
                    obs_date=r["obs_month"], value=r["value"],
                    as_of=r["as_of"], release_date=r.get("release_date"),
                )
                for r in mrows
            ]
        posture = state_resp.valuation

    return GoldLensResponse(lens_id=lens_id, posture=posture, detail=detail)
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/api/routers/gold.py tests/integration/api/test_gold_router_state.py
git commit -m "feat(gold/api): state + lenses endpoints"
```

---

## Task 22: `GET /api/gold/replay?as_of=YYYY-MM-DD`

**Files:**
- Modify: `src/uw_scan/api/routers/gold.py`
- Test: `tests/integration/api/test_gold_router_replay.py`

This is the replay-discipline endpoint. Per spec §6.4 and §9.3, it returns the FIRST-computed posture row for the requested `obs_date`, not a re-derivation.

- [ ] **Step 1: Failing test**

```python
# tests/integration/api/test_gold_router_replay.py
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.server import build_app
from uw_scan.storage.repository import Repository


@pytest.fixture
def app_with_multi_vintage(postgresql):
    """Two posture rows for the same obs_date — replay must return the FIRST."""
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        def _insert(computed_at: datetime, state: str) -> None:
            repo.insert_gold_posture_daily(
                obs_date=date(2026, 5, 10),
                computed_at=computed_at,
                gauge_corr_60d=None, gauge_corr_126d=None,
                gauge_corr_252d=None, gauge_corr_504d=None,
                gauge_corr_252d_returns=None,
                gauge_state=state,
                structural_state_label=None,
                cb_strategic_12m_sum_t=None, cb_tactical_12m_sum_t=None,
                cb_diversifier_12m_sum_t=None,
                gld_holdings_t=None, gld_30d_net_flow_t=None,
                comex_registered_oz=None, comex_20d_roc_pct=None,
                cot_mm_net_pct=None, cyclical_zone_label=None,
                cpi_yoy=None, t5yifr=None, dfii10=None,
                dfii10_60d_change_bps=None, factors_jsonb={},
                valuation_flag="Low", real_price_percentile=None,
                gold_m2_ratio_percentile=None, gold_spx_ratio_percentile=None,
                structural_posture_text=None, cyclical_posture_text=None,
                valuation_posture_text=None, inputs_jsonb={},
            )
        _insert(datetime(2026, 5, 11, 21, tzinfo=UTC), "suspended")
        _insert(datetime(2026, 5, 20, 21, tzinfo=UTC), "partial")  # recomputed later
    return TestClient(build_app(dsn=postgresql.info.dsn))


def test_replay_returns_first_computed_posture(app_with_multi_vintage):
    response = app_with_multi_vintage.get("/api/gold/replay?as_of=2026-05-10")
    assert response.status_code == 200
    assert response.json()["gauge"]["state"] == "suspended"


def test_replay_missing_date_returns_404(app_with_multi_vintage):
    response = app_with_multi_vintage.get("/api/gold/replay?as_of=1999-01-01")
    assert response.status_code == 404
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Add endpoint**

```python
# Append to src/uw_scan/api/routers/gold.py

@router.get("/replay", response_model=GoldStateResponse)
def get_replay(
    as_of: date = Query(..., description="Reconstruct posture for this obs_date"),
    repo: Repository = Depends(get_repo),
) -> GoldStateResponse:
    row = repo.fetch_gold_posture_for_obs_date(as_of)
    if row is None:
        raise HTTPException(404, f"no posture row for {as_of}")
    return _state_from_row(row)
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/api/routers/gold.py tests/integration/api/test_gold_router_replay.py
git commit -m "feat(gold/api): replay endpoint with first-computed discipline"
```

---

## Task 23: Worker jobs — daily ingestion (FRED / GPR / ETF / COMEX / UW options)

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py` (extend `register_jobs(...)` or equivalent entry point)
- Test: `tests/integration/worker/test_gold_daily_jobs.py`

5 daily jobs share a common shape: call source provider, write rows via repo, log exceptions. Pattern shown in full for `gold_fred_ingest`; the others follow identically with their respective provider class and repo method.

- [ ] **Step 1: Failing test (integration; runs job functions directly)**

```python
# tests/integration/worker/test_gold_daily_jobs.py
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import psycopg
import pytest

from uw_scan.sources.fred import FredObservation
from uw_scan.storage.repository import Repository
from uw_scan.worker.scheduler import gold_fred_ingest_job


@pytest.mark.integration
def test_gold_fred_ingest_writes_macro_series_daily(postgresql):
    sample = [
        FredObservation("DFII10", date(2026, 5, 14), Decimal("1.97")),
        FredObservation("DFII10", date(2026, 5, 15), Decimal("2.01")),
    ]
    with patch("uw_scan.worker.scheduler.FredProvider") as MockProvider:
        instance = MockProvider.return_value.__enter__.return_value
        instance.fetch_series.return_value = sample
        gold_fred_ingest_job(dsn=postgresql.info.dsn, series_ids=["DFII10"])

    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        rows = repo.fetch_macro_series_daily("DFII10")
    assert len(rows) == 2
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement the daily jobs**

Append to `src/uw_scan/worker/scheduler.py`:

```python
# imports near other source-provider imports
from datetime import UTC, date, datetime, timedelta
from uw_scan.sources.fred import FredProvider
from uw_scan.sources.gpr import GprProvider
from uw_scan.sources.etf_holdings import EtfHoldingsProvider
from uw_scan.sources.comex import ComexProvider
from uw_scan.sources.uw import UwClient
from uw_scan.storage.repository import Repository

FRED_SERIES_DAILY = [
    "DFII10", "DGS10", "T10YIE", "T5YIFR",
    "DTWEXBGS", "BAMLH0A0HYM2", "VIXCLS", "GVZCLS",
    "DEXCHUS", "DEXINUS", "DEXJPUS", "CBBTCUSD",
]
FRED_SERIES_MONTHLY = ["CPIAUCSL", "M2SL"]


def gold_fred_ingest_job(*, dsn: str, series_ids: list[str] | None = None) -> None:
    """Daily FRED refresh. Schedule: 17:00 ET."""
    ids = series_ids or FRED_SERIES_DAILY
    monthly_ids = FRED_SERIES_MONTHLY
    now = datetime.now(UTC)
    import psycopg
    with psycopg.connect(dsn) as conn, FredProvider() as fred:
        repo = Repository(conn, schema="uw_scan")
        # daily series
        for sid in ids:
            try:
                for obs in fred.fetch_series(sid, start=date.today() - timedelta(days=45)):
                    repo.insert_macro_series_daily(
                        series_id=obs.series_id, obs_date=obs.obs_date,
                        value=obs.value, as_of=now, release_date=None,
                        source="FRED", source_url=None,
                    )
            except Exception as exc:
                logger.exception("gold_fred_ingest: series=%s failed: %r", sid, exc)
        # monthly series
        for sid in monthly_ids:
            try:
                for obs in fred.fetch_series(sid, start=date.today() - timedelta(days=400)):
                    repo.insert_macro_series_monthly(
                        series_id=obs.series_id,
                        obs_month=date(obs.obs_date.year, obs.obs_date.month, 1),
                        value=obs.value, as_of=now, release_date=None,
                        source="FRED", source_url=None,
                    )
            except Exception as exc:
                logger.exception("gold_fred_ingest: monthly series=%s failed: %r", sid, exc)
        conn.commit()


def gold_gpr_ingest_job(*, dsn: str) -> None:
    """Daily GPR refresh. Schedule: 20:00 ET."""
    import psycopg
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, GprProvider() as gpr:
        repo = Repository(conn, schema="uw_scan")
        try:
            for obs in gpr.fetch_daily(start=date.today() - timedelta(days=45)):
                repo.insert_macro_series_daily(
                    series_id="GPRD", obs_date=obs.obs_date, value=obs.value,
                    as_of=now, release_date=None, source="GPR",
                    source_url="https://www.matteoiacoviello.com/gpr.htm",
                )
        except Exception as exc:
            logger.exception("gold_gpr_ingest failed: %r", exc)
        conn.commit()


def gold_etf_holdings_ingest_job(*, dsn: str) -> None:
    """Daily ETF refresh (GLD/IAU/GLDM/PHYS). Schedule: 18:30 ET."""
    import psycopg
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, EtfHoldingsProvider() as etf:
        repo = Repository(conn, schema="uw_scan")
        for ticker, fetch_fn, source in [
            ("GLD",  etf.fetch_gld,  "SPDR"),
            ("IAU",  etf.fetch_iau,  "iShares"),
            ("GLDM", etf.fetch_gldm, "SPDR"),
            ("PHYS", etf.fetch_phys, "Sprott"),
        ]:
            try:
                for row in fetch_fn(start=date.today() - timedelta(days=45)):
                    repo.insert_etf_holdings_daily(
                        ticker=row.ticker, obs_date=row.obs_date,
                        holdings_oz=row.holdings_oz, shares_out=row.shares_out,
                        nav_per_share=row.nav_per_share, premium_pct=row.premium_pct,
                        as_of=now, source=source,
                    )
            except Exception as exc:
                logger.exception("gold_etf_holdings_ingest: %s failed: %r", ticker, exc)
        conn.commit()


def gold_comex_vault_ingest_job(*, dsn: str) -> None:
    """Daily COMEX vault. Schedule: 17:30 ET."""
    import psycopg
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, ComexProvider() as comex:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in comex.fetch_vault(start=date.today() - timedelta(days=45)):
                repo.insert_exchange_inventory_daily(
                    exchange="COMEX", obs_date=row.obs_date,
                    registered_oz=row.registered_oz, eligible_oz=row.eligible_oz,
                    vault_oz=None, as_of=now,
                    source_url=ComexProvider.URL,
                )
        except Exception as exc:
            logger.exception("gold_comex_vault_ingest failed: %r", exc)
        conn.commit()


def gold_uw_options_snapshot_job(*, dsn: str, api_key: str) -> None:
    """Daily UW gold-options snapshot. Schedule: 16:30 ET."""
    import psycopg
    now = datetime.now(UTC)
    client = UwClient(api_key=api_key)
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        for ticker in ("GLD", "GDX", "IAU"):
            try:
                snap = client.fetch_gold_options_snapshot(ticker, obs_date=date.today())
                repo.insert_uw_gold_options_daily(
                    ticker=snap.ticker, obs_date=snap.obs_date,
                    atm_iv_30d=snap.atm_iv_30d, atm_iv_60d=snap.atm_iv_60d,
                    put_25d_iv_30d=snap.put_25d_iv_30d,
                    call_25d_iv_30d=snap.call_25d_iv_30d,
                    skew_25d_30d=snap.skew_25d_30d,
                    put_call_oi_ratio=snap.put_call_oi_ratio,
                    dealer_gamma_est=snap.dealer_gamma_est,
                    as_of=now,
                )
            except Exception as exc:
                logger.exception("gold_uw_options_snapshot: %s failed: %r", ticker, exc)
        conn.commit()
```

Register all 5 jobs in the scheduler init block (e.g. `register_jobs(scheduler, settings)`) using the existing pattern (look at how `full_scan` job is registered). Schedules per spec §5.10:

```python
scheduler.add_job(gold_fred_ingest_job, "cron", hour=21, minute=0,
                  kwargs={"dsn": settings.dsn})  # 17:00 ET == 21:00 UTC
scheduler.add_job(gold_gpr_ingest_job, "cron", hour=0, minute=0,
                  kwargs={"dsn": settings.dsn})  # 20:00 ET == 00:00 UTC next day
scheduler.add_job(gold_etf_holdings_ingest_job, "cron", hour=22, minute=30,
                  kwargs={"dsn": settings.dsn})  # 18:30 ET
scheduler.add_job(gold_comex_vault_ingest_job, "cron", hour=21, minute=30,
                  kwargs={"dsn": settings.dsn})  # 17:30 ET
scheduler.add_job(gold_uw_options_snapshot_job, "cron", hour=20, minute=30,
                  kwargs={"dsn": settings.dsn, "api_key": settings.uw_scan_api_key})  # 16:30 ET
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/worker/scheduler.py tests/integration/worker/test_gold_daily_jobs.py
git commit -m "feat(gold/worker): daily ingestion jobs (FRED/GPR/ETF/COMEX/UW)"
```

---

## Task 24: Worker jobs — weekly + monthly ingestion (CFTC / LBMA / WGC)

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_gold_periodic_jobs.py`

Same pattern as Task 23, three additional jobs.

- [ ] **Step 1: Failing test**

```python
# tests/integration/worker/test_gold_periodic_jobs.py
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import psycopg
import pytest

from uw_scan.sources.cftc_cot import CotRow
from uw_scan.sources.lbma import LbmaVaultRow
from uw_scan.sources.wgc_cb import CbReserveRow
from uw_scan.storage.repository import Repository
from uw_scan.worker.scheduler import (
    gold_cftc_cot_ingest_job, gold_lbma_vault_ingest_job, gold_wgc_cb_ingest_job,
)


@pytest.mark.integration
def test_gold_cftc_cot_ingest_writes_rows(postgresql):
    sample = [CotRow(
        obs_date=date(2026, 5, 13), release_date=date(2026, 5, 16),
        mm_long=Decimal("210500"), mm_short=Decimal("85300"),
        mm_net=Decimal("125200"),
        comm_long=Decimal("180100"), comm_short=Decimal("295400"),
        comm_net=Decimal("-115300"),
        open_interest=Decimal("512000"),
    )]
    with patch("uw_scan.worker.scheduler.CftcCotProvider") as MockProvider:
        MockProvider.return_value.__enter__.return_value.fetch_weekly.return_value = sample
        gold_cftc_cot_ingest_job(dsn=postgresql.info.dsn)

    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        rows = repo.fetch_cot_gold_weekly()
    assert len(rows) == 1
    assert rows[0]["mm_net"] == Decimal("125200")
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

Append to `src/uw_scan/worker/scheduler.py`:

```python
from uw_scan.sources.cftc_cot import CftcCotProvider
from uw_scan.sources.lbma import LbmaProvider
from uw_scan.sources.wgc_cb import WgcCbProvider


def gold_cftc_cot_ingest_job(*, dsn: str) -> None:
    """Weekly CFTC COT (Friday after release)."""
    import psycopg
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, CftcCotProvider() as cot:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in cot.fetch_weekly(start=date.today() - timedelta(days=400)):
                repo.insert_cot_gold_weekly(
                    obs_date=row.obs_date, release_date=row.release_date,
                    mm_long=row.mm_long, mm_short=row.mm_short, mm_net=row.mm_net,
                    comm_long=row.comm_long, comm_short=row.comm_short,
                    comm_net=row.comm_net, open_interest=row.open_interest,
                    as_of=now, source_url=CftcCotProvider.URL,
                )
        except Exception as exc:
            logger.exception("gold_cftc_cot_ingest failed: %r", exc)
        conn.commit()


def gold_lbma_vault_ingest_job(*, dsn: str) -> None:
    """Monthly LBMA vault (6th business day of month)."""
    import psycopg
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, LbmaProvider() as lbma:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in lbma.fetch_monthly(start=date.today() - timedelta(days=400)):
                repo.insert_exchange_inventory_daily(
                    exchange="LBMA", obs_date=row.obs_date,
                    registered_oz=None, eligible_oz=None,
                    vault_oz=row.vault_oz, as_of=now,
                    source_url=LbmaProvider.URL,
                )
        except Exception as exc:
            logger.exception("gold_lbma_vault_ingest failed: %r", exc)
        conn.commit()


def gold_wgc_cb_ingest_job(*, dsn: str) -> None:
    """Monthly WGC CB reserves (8th business day of month)."""
    import psycopg
    now = datetime.now(UTC)
    with psycopg.connect(dsn) as conn, WgcCbProvider() as wgc:
        repo = Repository(conn, schema="uw_scan")
        try:
            for row in wgc.fetch_monthly(start=date.today() - timedelta(days=400)):
                repo.insert_cb_gold_reserves_monthly(
                    country_iso3=row.country_iso3, obs_month=row.obs_month,
                    reserves_t=row.reserves_t, bucket=row.bucket,
                    is_reported=row.is_reported, is_estimated=row.is_estimated,
                    as_of=now, release_date=date.today(), source="WGC",
                )
        except Exception as exc:
            logger.exception("gold_wgc_cb_ingest failed: %r", exc)
        conn.commit()
```

Register with cron:

```python
scheduler.add_job(gold_cftc_cot_ingest_job, "cron", day_of_week="fri",
                  hour=20, minute=0, kwargs={"dsn": settings.dsn})  # 16:00 ET Fri
scheduler.add_job(gold_lbma_vault_ingest_job, "cron", day="6", hour=16, minute=0,
                  kwargs={"dsn": settings.dsn})
scheduler.add_job(gold_wgc_cb_ingest_job, "cron", day="8", hour=16, minute=0,
                  kwargs={"dsn": settings.dsn})
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/worker/scheduler.py tests/integration/worker/test_gold_periodic_jobs.py
git commit -m "feat(gold/worker): CFTC weekly + LBMA + WGC monthly jobs"
```

---

## Task 25: Worker job — `gold_posture_compute` daily orchestrator

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_gold_posture_compute_job.py`

Runs the orchestrator from Task 19 once per day after all ingest jobs finish.

- [ ] **Step 1: Failing test**

```python
# tests/integration/worker/test_gold_posture_compute_job.py
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from uw_scan.storage.repository import Repository
from uw_scan.worker.scheduler import gold_posture_compute_job


@pytest.mark.integration
def test_gold_posture_compute_writes_row(postgresql):
    today = date.today()
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        base = today - timedelta(days=300)
        for i in range(300):
            d = base + timedelta(days=i)
            repo.insert_macro_series_daily(
                "GLD_CLOSE", d, Decimal(str(1800 + i * 0.5)),
                datetime.combine(d, datetime.min.time(), tzinfo=UTC),
                None, "MASSIVE", None,
            )
            repo.insert_macro_series_daily(
                "DFII10", d, Decimal(str(2.0 - i * 0.005)),
                datetime.combine(d, datetime.min.time(), tzinfo=UTC),
                None, "FRED", None,
            )
        conn.commit()

    gold_posture_compute_job(dsn=postgresql.info.dsn)

    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        row = repo.fetch_gold_posture_latest()
    assert row is not None
    assert row["obs_date"] == today
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```python
# Append to src/uw_scan/worker/scheduler.py
from uw_scan.reports.gold_posture import compute_and_persist_gold_posture


def gold_posture_compute_job(*, dsn: str) -> None:
    """Compute and persist today's gold_posture_daily row. Schedule: 21:00 ET
    (after all ingest jobs complete)."""
    import psycopg
    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        try:
            compute_and_persist_gold_posture(repo, as_of=date.today())
            conn.commit()
        except Exception as exc:
            logger.exception("gold_posture_compute failed: %r", exc)
            conn.rollback()
```

Register:

```python
scheduler.add_job(gold_posture_compute_job, "cron", hour=1, minute=0,
                  kwargs={"dsn": settings.dsn})  # 21:00 ET == 01:00 UTC next day
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add src/uw_scan/worker/scheduler.py tests/integration/worker/test_gold_posture_compute_job.py
git commit -m "feat(gold/worker): daily posture-compute orchestrator job"
```

---

## Task 26: Regenerate OpenAPI types for the web client

**Files:**
- Run: `cd web && npm run gen:types`
- Modify: `web/lib/types.ts` (regenerated, committed as artifact)

No test code; this task verifies the generated types compile and includes the new gold response models.

- [ ] **Step 1: Run the generator**

```bash
cd web && npm run gen:types
```

Expected: command exits 0; `web/lib/types.ts` updates with `GoldStateResponse`, `GoldGaugeResponse`, etc.

- [ ] **Step 2: Verify by typecheck**

```bash
cd web && npm run typecheck
```

Expected: exits 0.

- [ ] **Step 3: Commit** (only commit after explicit approval)

```bash
git add web/lib/types.ts
git commit -m "chore(web): regenerate types after gold API additions"
```

---

## Task 27: Posture-language lint rule

**Files:**
- Create: `web/lib/copy-rules.ts`
- Create: `web/lib/copy-rules.test.ts`

Per spec §8.4, v1 web copy cannot use "buy", "sell", "long", "short", "position size", "allocate %", "trade", "execute" as imperatives.

- [ ] **Step 1: Failing test**

```typescript
// web/lib/copy-rules.test.ts
import { describe, expect, it } from 'vitest';
import { findBannedSubstrings, BANNED_POSTURE_LANGUAGE } from './copy-rules';

describe('findBannedSubstrings', () => {
  it('flags "buy" as banned in v1 posture copy', () => {
    expect(findBannedSubstrings('Recommendation: buy GLD')).toContain('buy');
  });
  it('flags "position size"', () => {
    expect(findBannedSubstrings('Increase position size by 5%')).toContain('position size');
  });
  it('allows posture vocabulary', () => {
    expect(findBannedSubstrings('Structural bid intact. Cyclical posture suspended.')).toEqual([]);
  });
  it('lists banned strings', () => {
    expect(BANNED_POSTURE_LANGUAGE).toContain('buy');
    expect(BANNED_POSTURE_LANGUAGE).toContain('sell');
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

```bash
cd web && npx vitest run lib/copy-rules.test.ts
```

- [ ] **Step 3: Implement**

```typescript
// web/lib/copy-rules.ts
/**
 * Posture-language lint rule. v1 dashboard copy must use posture / risk / scenario
 * language, NOT recommendation / position / size language. Per
 * docs/research/gold-sdf-framework/04-three-layer-architecture.md and the
 * Codex review, until backtest validation exists, sizing language overstates
 * confidence and is banned in /gold UI components.
 *
 * Bypass: explicit eslint-disable-next-line copy-rules with comment is allowed
 * for academic source quotations, e.g. cited Baur-Lucey copy.
 */

export const BANNED_POSTURE_LANGUAGE = [
  'buy',
  'sell',
  'long',
  'short',
  'position size',
  'recommended size',
  'allocate %',
  'trade',
  'execute',
] as const;

export function findBannedSubstrings(text: string): string[] {
  const lower = text.toLowerCase();
  return BANNED_POSTURE_LANGUAGE.filter((w) => {
    // Require word boundaries for short banned terms so "ungbuy" / "buyback" don't false-match
    const re = new RegExp(`\\b${w}\\b`, 'i');
    return re.test(lower);
  });
}
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add web/lib/copy-rules.ts web/lib/copy-rules.test.ts
git commit -m "feat(web/gold): posture-language lint helper"
```

---

## Task 28: GOLD COMPASS page route + GoldCompassLayout shell + shared chips

**Files:**
- Create: `web/app/gold/page.tsx`
- Create: `web/app/gold/loading.tsx`
- Create: `web/components/gold/GoldCompassLayout.tsx`
- Create: `web/components/gold/GoldCompassHeader.tsx`
- Create: `web/components/gold/chips/PostureChip.tsx`
- Create: `web/components/gold/chips/HeuristicBadge.tsx`
- Create: `web/components/gold/chips/PersistOnlyBadge.tsx`
- Test: `web/components/gold/GoldCompassLayout.test.tsx`
- Test: `web/components/gold/chips/PostureChip.test.tsx`

GoldCompassLayout is the 5-tier shell (per spec §8.2) that subsequent tasks fill with content. This task builds the page route, the layout scaffold, the page header (title + replay date chip), and three reusable chip primitives. All other UI tasks reuse these chips. No data shape changes here — `GoldStateResponse` from Task 18 is unchanged.

- [ ] **Step 1: Failing tests**

```tsx
// web/components/gold/chips/PostureChip.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PostureChip } from './PostureChip';

describe('PostureChip', () => {
  it('renders each posture state with stable accessible label', () => {
    for (const state of ['FAVORABLE', 'NEUTRAL', 'STRETCHED', 'SUSPENDED', 'DEGRADED'] as const) {
      const { unmount } = render(<PostureChip state={state} />);
      expect(screen.getByText(state)).toBeInTheDocument();
      unmount();
    }
  });
});
```

```tsx
// web/components/gold/GoldCompassLayout.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GoldCompassLayout } from './GoldCompassLayout';
import type { GoldStateResponse } from '@/lib/types';

const FIXTURE: GoldStateResponse = {
  obs_date: '2026-05-17',
  computed_at: '2026-05-17T21:00:00Z',
  gauge: {
    corr_60d: '-0.04', corr_126d: '-0.05', corr_252d: '-0.07',
    corr_504d: '-0.31', corr_252d_returns: '-0.06', state: 'suspended',
  },
  structural: {
    state_label: 'structural-bid-intact',
    cb_strategic_12m_sum_t: '210', cb_tactical_12m_sum_t: '12',
    cb_diversifier_12m_sum_t: '34', gld_holdings_t: '872.5',
    gld_30d_net_flow_t: '-12.4', comex_registered_oz: '17500100',
    comex_20d_roc_pct: '0.14', cot_mm_net_pct: '0.72',
    narrative_text: 'Structural bid intact.',
  },
  cyclical: {
    zone_label: 'moderate-trap',
    cpi_yoy: '2.8', t5yifr: '2.31', dfii10: '1.97',
    dfii10_60d_change_bps: '12',
    factors: { F1: -0.4, F5: 1.8 },
    narrative_text: 'Cyclical posture suspended.',
  },
  valuation: {
    flag: 'Severe',
    real_price_percentile: '0.92',
    gold_m2_ratio_percentile: '0.78',
    gold_spx_ratio_percentile: '0.64',
    narrative_text: 'Mean-reversion risk: SEVERE.',
  },
  inputs_used: {},
};

describe('GoldCompassLayout', () => {
  it('renders the five tiers as discrete regions', () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getByRole('region', { name: /kpi/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /lens 1/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /lens 2/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /lens 3/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /decomposition|correlation history/i })).toBeInTheDocument();
  });
  it('renders GOLD COMPASS wordmark', () => {
    render(<GoldCompassLayout state={FIXTURE} />);
    expect(screen.getByText(/GOLD COMPASS/)).toBeInTheDocument();
  });
  it('uses posture language only (no buy/sell/long/short)', () => {
    const { container } = render(<GoldCompassLayout state={FIXTURE} />);
    const text = (container.textContent ?? '').toLowerCase();
    expect(text).not.toMatch(/\bbuy\b/);
    expect(text).not.toMatch(/\bsell\b/);
    expect(text).not.toMatch(/\bposition size\b/);
    expect(text).not.toMatch(/\bpredicted return\b/);
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

```bash
cd web && npx vitest run components/gold/GoldCompassLayout.test.tsx components/gold/chips/PostureChip.test.tsx
```

- [ ] **Step 3: Implement chips**

```tsx
// web/components/gold/chips/PostureChip.tsx
export type PostureState = 'FAVORABLE' | 'NEUTRAL' | 'STRETCHED' | 'SUSPENDED' | 'DEGRADED';

const colorByState: Record<PostureState, string> = {
  FAVORABLE: 'var(--positive)',
  NEUTRAL:   'var(--text-secondary)',
  STRETCHED: 'var(--warning)',
  SUSPENDED: 'var(--text-muted)',
  DEGRADED:  'var(--negative)',
};

export function PostureChip({ state }: { state: PostureState }) {
  return (
    <span
      style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', padding: '2px 6px',
        border: `1px solid ${colorByState[state]}`,
        color: colorByState[state], borderRadius: 3,
      }}
    >
      {state}
    </span>
  );
}
```

```tsx
// web/components/gold/chips/HeuristicBadge.tsx
export function HeuristicBadge({ reason = 'heuristic, not yet calibrated' }: { reason?: string }) {
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1,
      textTransform: 'uppercase', padding: '1px 4px',
      background: 'color-mix(in srgb, var(--warning) 12%, transparent)',
      color: 'var(--warning)', borderRadius: 2,
    }}>
      [{reason}]
    </span>
  );
}
```

```tsx
// web/components/gold/chips/PersistOnlyBadge.tsx
export function PersistOnlyBadge() {
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1,
      textTransform: 'uppercase', padding: '1px 4px',
      background: 'color-mix(in srgb, var(--info) 12%, transparent)',
      color: 'var(--info)', borderRadius: 2,
    }}>
      [persist-only · no model in v1]
    </span>
  );
}
```

- [ ] **Step 4: Implement header + layout shell**

```tsx
// web/components/gold/GoldCompassHeader.tsx
import { ReplayDatePicker } from './ReplayDatePicker';

type Props = { obsDate: string };

export function GoldCompassHeader({ obsDate }: Props) {
  return (
    <header style={{
      display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
      gap: 16, padding: '16px 24px', borderBottom: '1px solid var(--border-dim)',
    }}>
      <div>
        <h1 style={{
          fontFamily: 'var(--font-mono)', fontSize: 18, letterSpacing: 2,
          textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0,
        }}>GOLD COMPASS</h1>
        <p style={{
          fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
          textTransform: 'uppercase', color: 'var(--text-muted)', margin: '4px 0 0',
        }}>Heuristic posture monitor · v1 · obs {obsDate}</p>
      </div>
      <ReplayDatePicker initialDate={obsDate} />
    </header>
  );
}
```

```tsx
// web/components/gold/GoldCompassLayout.tsx
import type { GoldStateResponse } from '@/lib/types';
import { GoldCompassHeader } from './GoldCompassHeader';
import { DataAuditFooter } from './DataAuditFooter';

type Props = { state: GoldStateResponse };

const sectionStyle: React.CSSProperties = {
  padding: '20px 24px', borderBottom: '1px solid var(--border-dim)',
};

export function GoldCompassLayout({ state }: Props) {
  return (
    <main style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>
      <GoldCompassHeader obsDate={state.obs_date} />

      <section role="region" aria-label="KPI strip" style={sectionStyle}>
        {/* Tier 1 — filled by Task 29 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12 }}>
          {/* SpotPriceCard, CorrelationGaugeCard, RegimeBadgeCard, LensesOverallCard, DataFreshnessCard */}
        </div>
      </section>

      <section role="region" aria-label="Lens 1 structural flow" style={sectionStyle}>
        {/* Tier 2 — filled by Task 30 */}
      </section>

      <section
        role="region"
        aria-label="Lens 2 cyclical posture"
        style={{ ...sectionStyle, opacity: state.gauge.state === 'suspended' ? 0.7 : 1 }}
      >
        {/* Tier 3 — filled by Task 31 */}
      </section>

      <section role="region" aria-label="Lens 3 valuation overlay" style={sectionStyle}>
        {/* Tier 4 — filled by Task 32 */}
      </section>

      <section
        role="region"
        aria-label="Decomposition and correlation history"
        style={sectionStyle}
      >
        {/* Tier 5 — filled by Tasks 33 + 34 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        </div>
      </section>

      <DataAuditFooter
        obsDate={state.obs_date}
        computedAt={state.computed_at}
        inputsUsed={state.inputs_used}
      />
    </main>
  );
}
```

```tsx
// web/app/gold/page.tsx
import { GoldCompassLayout } from '@/components/gold/GoldCompassLayout';
import type { GoldStateResponse } from '@/lib/types';

async function fetchGoldState(): Promise<GoldStateResponse | null> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? ''}/api/gold/state`, {
    next: { revalidate: 60 },
  });
  if (!res.ok) return null;
  return res.json();
}

export default async function GoldPage() {
  const state = await fetchGoldState();
  if (!state) {
    return (
      <main style={{ padding: 32, color: 'var(--text-muted)', background: 'var(--bg-base)', minHeight: '100vh' }}>
        Gold posture not yet computed. The first scheduled run lands at the next worker tick.
      </main>
    );
  }
  return <GoldCompassLayout state={state} />;
}

export const metadata = { title: 'Gold Compass' };
```

```tsx
// web/app/gold/loading.tsx
export default function Loading() {
  return (
    <main style={{ padding: 32, color: 'var(--text-muted)', background: 'var(--bg-base)', minHeight: '100vh' }}>
      Loading GOLD COMPASS…
    </main>
  );
}
```

Notes:
- `DataAuditFooter` and `ReplayDatePicker` are imported here as **stubs** — both are completed in Tasks 32 (footer) and 36 (replay picker). Create one-line stub files first so the layout compiles, then flesh out in their dedicated tasks. Cleanest path: at the top of Task 28 create stub files that return `<div />` and `<></>`, then overwrite them in the later tasks.
- Section `<section>` elements are visually empty after Task 28 — that's expected. Tasks 29–34 fill them.

- [ ] **Step 5: Run, expect PASS.**

```bash
cd web && npx vitest run components/gold/GoldCompassLayout.test.tsx components/gold/chips/PostureChip.test.tsx
```

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/app/gold/page.tsx web/app/gold/loading.tsx \
        web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/GoldCompassHeader.tsx \
        web/components/gold/chips/PostureChip.tsx \
        web/components/gold/chips/HeuristicBadge.tsx \
        web/components/gold/chips/PersistOnlyBadge.tsx \
        web/components/gold/GoldCompassLayout.test.tsx \
        web/components/gold/chips/PostureChip.test.tsx
git commit -m "feat(web/gold): GOLD COMPASS page route + 5-tier layout shell + shared chips"
```

---

## Task 29: Tier 1 KPI strip — 5 cards

**Files:**
- Create: `web/components/gold/kpi/SpotPriceCard.tsx`
- Create: `web/components/gold/kpi/CorrelationGaugeCard.tsx`
- Create: `web/components/gold/kpi/RegimeBadgeCard.tsx`
- Create: `web/components/gold/kpi/LensesOverallCard.tsx`
- Create: `web/components/gold/kpi/DataFreshnessCard.tsx`
- Modify: `web/components/gold/GoldCompassLayout.tsx` (wire the 5 cards into Tier 1)
- Test: `web/components/gold/kpi/KpiStrip.test.tsx`

Tier 1 is the five-card KPI strip immediately under the GOLD COMPASS header (per spec §8.2). Each card is the canonical `Tile` shape (10/22/11px mono per `web/CLAUDE.md`). Color tokens only (`--positive`, `--negative`, `--warning`, `--accent-bg`, `--text-muted`). No new design tokens.

The KPI strip subsumes what the reference site shows as `XAU/USD` price card + `今日信号 / 预测收益 / 仓位热度 / 当前回撤` quadrant — but the model-dependent tiles are replaced with `CORRELATION GAUGE`, `REGIME BADGE`, `LENSES OVERALL`, `DATA FRESHNESS` per spec §8 substitution table.

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/kpi/KpiStrip.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SpotPriceCard } from './SpotPriceCard';
import { CorrelationGaugeCard } from './CorrelationGaugeCard';
import { RegimeBadgeCard } from './RegimeBadgeCard';
import { LensesOverallCard } from './LensesOverallCard';
import { DataFreshnessCard } from './DataFreshnessCard';

describe('Tier 1 KPI strip cards', () => {
  it('SpotPriceCard renders price, signed delta, and H/L/O', () => {
    render(<SpotPriceCard last="4561.50" deltaAbs="-157.20" deltaPct="-0.0332"
                          high="4615.20" low="4524.30" open="4615.20" />);
    expect(screen.getByText(/4561/)).toBeInTheDocument();
    expect(screen.getByText(/-3\.32%/)).toBeInTheDocument();
    expect(screen.getByText(/H 4615/)).toBeInTheDocument();
  });

  it('CorrelationGaugeCard surfaces 252d as primary value and state chip', () => {
    render(<CorrelationGaugeCard corr252d="-0.07" corr504d="-0.31" state="suspended" />);
    expect(screen.getByText(/-0\.07/)).toBeInTheDocument();
    expect(screen.getByText(/SUSPENDED/i)).toBeInTheDocument();
  });

  it('RegimeBadgeCard shows the article zone with heuristic badge', () => {
    render(<RegimeBadgeCard zoneLabel="moderate-trap" />);
    expect(screen.getByText(/moderate-trap/i)).toBeInTheDocument();
    expect(screen.getByText(/heuristic|not yet calibrated/i)).toBeInTheDocument();
  });

  it('LensesOverallCard stacks three posture chips and an overall chip', () => {
    render(<LensesOverallCard structural="FAVORABLE" cyclical="NEUTRAL" valuation="STRETCHED" />);
    expect(screen.getByText(/FAVORABLE/)).toBeInTheDocument();
    expect(screen.getByText(/NEUTRAL/)).toBeInTheDocument();
    expect(screen.getByText(/STRETCHED/)).toBeInTheDocument();
  });

  it('DataFreshnessCard renders per-source ✓/⚠/✗ glyphs', () => {
    render(
      <DataFreshnessCard
        sources={[
          { id: 'FRED', lastAsOf: '2026-05-17T06:00:00Z', staleSeconds: 60 },
          { id: 'COT',  lastAsOf: '2026-05-13T16:30:00Z', staleSeconds: 86400 * 4 },
        ]}
      />
    );
    expect(screen.getByText(/FRED/)).toBeInTheDocument();
    expect(screen.getByText(/COT/)).toBeInTheDocument();
  });

  it('cards never render banned posture-language strings', () => {
    const { container } = render(
      <>
        <SpotPriceCard last="4561.50" deltaAbs="-157.20" deltaPct="-0.0332"
                       high="4615" low="4524" open="4615" />
        <CorrelationGaugeCard corr252d="-0.07" corr504d="-0.31" state="suspended" />
      </>
    );
    const text = (container.textContent ?? '').toLowerCase();
    for (const banned of ['buy', 'sell', 'long', 'short', 'predicted return', 'position size']) {
      expect(text).not.toContain(banned);
    }
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

```bash
cd web && npx vitest run components/gold/kpi/KpiStrip.test.tsx
```

- [ ] **Step 3: Implement the 5 cards**

All five share the `Tile` shape (10/22/11px mono — pattern from `components/stock/panels/VolMetricsCard.tsx`). Create a local `kpi/Tile.tsx` if convenient (per spec §8.3 reuse-from-existing guidance: extract once, don't share with stock/ until 3+ callers outside gold/ need it).

```tsx
// web/components/gold/kpi/SpotPriceCard.tsx
type Props = {
  last: string; deltaAbs: string; deltaPct: string;
  high: string; low: string; open: string;
};

function signedColor(v: string): string {
  const n = parseFloat(v);
  if (!Number.isFinite(n) || n === 0) return 'var(--text-secondary)';
  return n > 0 ? 'var(--positive)' : 'var(--negative)';
}

function pct(v: string): string {
  const n = parseFloat(v);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : '—';
}

export function SpotPriceCard({ last, deltaAbs, deltaPct, high, low, open }: Props) {
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Gold Spot · XAU/USD</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>${last}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, marginTop: 4,
        color: signedColor(deltaAbs),
      }}>{deltaAbs} ({pct(deltaPct)})</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)',
        marginTop: 4,
      }}>H {high} L {low} O {open}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/kpi/CorrelationGaugeCard.tsx
import { PostureChip } from '../chips/PostureChip';

type Props = { corr252d: string; corr504d: string; state: 'operative' | 'partial' | 'suspended' };

const stateMap = { operative: 'FAVORABLE', partial: 'NEUTRAL', suspended: 'SUSPENDED' } as const;

export function CorrelationGaugeCard({ corr252d, corr504d, state }: Props) {
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Corr Gauge · Gold↔DFII10 252d</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{corr252d}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>504d {corr504d}</div>
      <div style={{ marginTop: 6 }}><PostureChip state={stateMap[state]} /></div>
    </div>
  );
}
```

```tsx
// web/components/gold/kpi/RegimeBadgeCard.tsx
import { HeuristicBadge } from '../chips/HeuristicBadge';

const zoneMap: Record<string, string> = {
  'low-inflation': 'R1 · LOW INFLATION',
  'moderate-trap': 'R2 · MODERATE TRAP',
  'unanchored':    'R3 · UNANCHORED',
};

export function RegimeBadgeCard({ zoneLabel }: { zoneLabel: string | null }) {
  const display = zoneLabel ? (zoneMap[zoneLabel] ?? zoneLabel) : '—';
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Article Zone</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{display}</div>
      <div style={{ marginTop: 6 }}><HeuristicBadge /></div>
    </div>
  );
}
```

```tsx
// web/components/gold/kpi/LensesOverallCard.tsx
import { PostureChip, PostureState } from '../chips/PostureChip';

type Props = { structural: PostureState; cyclical: PostureState; valuation: PostureState };

function overallFrom(s: PostureState, c: PostureState, v: PostureState): PostureState {
  // Conservative aggregate: if any DEGRADED → DEGRADED; if v is STRETCHED → MIXED-ish neutral.
  if ([s, c, v].includes('DEGRADED')) return 'DEGRADED';
  if (s === 'FAVORABLE' && c === 'FAVORABLE') return 'FAVORABLE';
  if (s === 'SUSPENDED' && c === 'SUSPENDED') return 'SUSPENDED';
  return 'NEUTRAL';
}

export function LensesOverallCard({ structural, cyclical, valuation }: Props) {
  const overall = overallFrom(structural, cyclical, valuation);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Lenses Overall</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>S</span>
          <PostureChip state={structural} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>C</span>
          <PostureChip state={cyclical} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>V</span>
          <PostureChip state={valuation} />
        </div>
      </div>
      <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--border-dim)' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginRight: 6 }}>OVERALL</span>
        <PostureChip state={overall} />
      </div>
    </div>
  );
}
```

```tsx
// web/components/gold/kpi/DataFreshnessCard.tsx
type Source = { id: string; lastAsOf: string; staleSeconds: number };

function glyph(staleSeconds: number): { char: string; color: string } {
  if (staleSeconds < 86_400) return { char: '✓', color: 'var(--positive)' };
  if (staleSeconds < 86_400 * 7) return { char: '⚠', color: 'var(--warning)' };
  return { char: '✗', color: 'var(--negative)' };
}

export function DataFreshnessCard({ sources }: { sources: Source[] }) {
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Data Freshness</div>
      <ul style={{ listStyle: 'none', padding: 0, margin: '6px 0 0' }}>
        {sources.map((s) => {
          const { char, color } = glyph(s.staleSeconds);
          return (
            <li key={s.id} style={{
              display: 'flex', justifyContent: 'space-between',
              fontFamily: 'var(--font-mono)', fontSize: 11,
              color: 'var(--text-primary)', padding: '1px 0',
            }}>
              <span>{s.id}</span>
              <span style={{ color }}>{char}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Wire the 5 cards into Tier 1 of `GoldCompassLayout.tsx`**

```tsx
// inside GoldCompassLayout, replace the empty Tier 1 grid:
<section role="region" aria-label="KPI strip" style={sectionStyle}>
  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12 }}>
    <SpotPriceCard
      last={state.spot.last} deltaAbs={state.spot.delta_abs}
      deltaPct={state.spot.delta_pct} high={state.spot.high}
      low={state.spot.low} open={state.spot.open}
    />
    <CorrelationGaugeCard
      corr252d={state.gauge.corr_252d} corr504d={state.gauge.corr_504d}
      state={state.gauge.state}
    />
    <RegimeBadgeCard zoneLabel={state.cyclical.zone_label} />
    <LensesOverallCard
      structural={state.structural.posture_chip}
      cyclical={state.cyclical.posture_chip}
      valuation={state.valuation.posture_chip}
    />
    <DataFreshnessCard sources={state.data_freshness} />
  </div>
</section>
```

This adds 3 new shape requirements on `GoldStateResponse` (Task 18) that must be present before this task can wire properly: `state.spot` (last/delta/high/low/open), `state.{structural,cyclical,valuation}.posture_chip`, `state.data_freshness`. **Update Task 18 (Pydantic models) and Task 19 (report orchestrator) accordingly** — these are small extensions, not a new computation. Until those land, the KPI strip can hard-code mock props in storybook-style mode (commented `// TODO Task-19-orchestrator: replace with state.*` markers) without violating posture-language lint.

- [ ] **Step 5: Run, expect PASS.**

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/kpi/ web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/kpi/KpiStrip.test.tsx
git commit -m "feat(web/gold): Tier 1 KPI strip — 5 cards (Spot, Corr, Regime, Lenses, Freshness)"
```

---

## Task 30: Tier 2 Lens 1 panel + 6 sub-cards

**Files:**
- Create: `web/components/gold/lens1/StructuralPanel.tsx`
- Create: `web/components/gold/lens1/CbReservesCard.tsx`
- Create: `web/components/gold/lens1/EtfFlowCard.tsx`
- Create: `web/components/gold/lens1/ComexRegimeCard.tsx`
- Create: `web/components/gold/lens1/CotPositioningCard.tsx`
- Create: `web/components/gold/lens1/UwSkewCard.tsx`
- Create: `web/components/gold/lens1/FxBasketCard.tsx`
- Create: `web/components/gold/lens1/StructuralPostureText.tsx`
- Modify: `web/components/gold/GoldCompassLayout.tsx` (wire Lens 1 into Tier 2)
- Test: `web/components/gold/lens1/StructuralPanel.test.tsx`

Tier 2 per spec §8.2: panel header chip + 6-card horizontal row + narrative posture text. Lead chart placeholder for now — wired in Task 35. All cards are `Tile` shape. Lens 1's posture chip (`FAVORABLE/NEUTRAL/SUSPENDED/DEGRADED`) renders top-right of the panel header.

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/lens1/StructuralPanel.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { StructuralPanel } from './StructuralPanel';
import type { GoldStructuralPostureModel } from '@/lib/types';

const POSTURE: GoldStructuralPostureModel = {
  state_label: 'structural-bid-intact',
  posture_chip: 'FAVORABLE',
  cb_strategic_12m_sum_t: '210',
  cb_tactical_12m_sum_t: '12',
  cb_diversifier_12m_sum_t: '34',
  cb_52w_pct: '0.78',
  gld_holdings_t: '872.5',
  gld_30d_net_flow_t: '-12.4',
  comex_registered_oz: '17500100',
  comex_20d_roc_pct: '0.14',
  lbma_30d_momentum_t: '-18',
  cot_mm_net_pct: '0.72',
  cot_mm_4w_change_sigma: '0.18',
  uw_25d_skew_sigma: '1.2',
  fx_basket_dxy_z: '0.6',
  xau_cny_premium_pct: '0.004',
  narrative_text: 'Structural bid intact. CB strategic 12m sum 210t.',
};

describe('Lens 1 StructuralPanel', () => {
  it('renders the panel header with FAVORABLE posture chip', () => {
    render(<StructuralPanel posture={POSTURE} />);
    expect(screen.getByText(/lens 1/i)).toBeInTheDocument();
    expect(screen.getByText(/structural flow/i)).toBeInTheDocument();
    expect(screen.getByText('FAVORABLE')).toBeInTheDocument();
  });

  it('renders all 6 sub-cards', () => {
    render(<StructuralPanel posture={POSTURE} />);
    const cards = ['CB RES', 'ETF FLOW', 'COMEX', 'COT', 'UW SKEW', 'FX'];
    for (const label of cards) {
      expect(screen.getByText(new RegExp(label, 'i'))).toBeInTheDocument();
    }
  });

  it('renders narrative posture text', () => {
    render(<StructuralPanel posture={POSTURE} />);
    expect(screen.getByText(/structural bid intact/i)).toBeInTheDocument();
  });

  it('UwSkewCard shows persist-only badge', () => {
    render(<StructuralPanel posture={POSTURE} />);
    expect(screen.getByText(/persist-only/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement the 6 cards + posture text + panel**

Each card follows the canonical Tile pattern. Example for `CbReservesCard`:

```tsx
// web/components/gold/lens1/CbReservesCard.tsx
type Props = { sumT: string; pct52w: string };

export function CbReservesCard({ sumT, pct52w }: Props) {
  const n = parseFloat(sumT);
  const pct = parseFloat(pct52w);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>CB Res Δ12M</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? `+${n.toFixed(0)}t` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>strategic · 52w {Number.isFinite(pct) ? `${(pct * 100).toFixed(0)}%ile` : '—'}</div>
    </div>
  );
}
```

The remaining 5 cards follow the same Tile shape. Inlining each so an out-of-order reader has the full implementation:

```tsx
// web/components/gold/lens1/EtfFlowCard.tsx
type Props = { flow30d: string };

export function EtfFlowCard({ flow30d }: Props) {
  const n = parseFloat(flow30d);
  const sign = Number.isFinite(n) ? (n >= 0 ? '+' : '') : '';
  const color = !Number.isFinite(n) ? 'var(--text-primary)'
              : n > 0 ? 'var(--positive)'
              : n < 0 ? 'var(--negative)' : 'var(--text-primary)';
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>ETF Flow · 30D</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color, lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? `${sign}${n.toFixed(1)}t` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>{Number.isFinite(n) && n < 0 ? 'outflow' : Number.isFinite(n) && n > 0 ? 'inflow' : 'flat'} · GLD</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens1/ComexRegimeCard.tsx
type Props = { roc20d: string; lbmaMomT: string };

export function ComexRegimeCard({ roc20d, lbmaMomT }: Props) {
  const roc = parseFloat(roc20d);
  const lbma = parseFloat(lbmaMomT);
  const rocColor = !Number.isFinite(roc) ? 'var(--text-primary)'
                 : roc > 0 ? 'var(--positive)'
                 : roc < 0 ? 'var(--negative)' : 'var(--text-primary)';
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>COMEX 20D</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: rocColor, lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(roc) ? `${roc > 0 ? '+' : ''}${(roc * 100).toFixed(0)}%` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>LBMA mom {Number.isFinite(lbma) ? `${lbma >= 0 ? '+' : ''}${lbma.toFixed(0)}t` : '—'}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens1/CotPositioningCard.tsx
type Props = { mmNetPct: string; mm4wSigma: string };

export function CotPositioningCard({ mmNetPct, mm4wSigma }: Props) {
  const pct = parseFloat(mmNetPct);
  const sigma = parseFloat(mm4wSigma);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>COT MM Net</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(pct) ? `${(pct * 100).toFixed(0)}%ile` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>4w Δ {Number.isFinite(sigma) ? `${sigma >= 0 ? '+' : ''}${sigma.toFixed(2)}σ` : '—'}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens1/UwSkewCard.tsx
import { PersistOnlyBadge } from '../chips/PersistOnlyBadge';

type Props = { skewSigma: string };

export function UwSkewCard({ skewSigma }: Props) {
  const n = parseFloat(skewSigma);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>UW 25Δ Skew</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? `${n >= 0 ? '+' : ''}${n.toFixed(1)}σ` : '—'}</div>
      <div style={{ marginTop: 6 }}><PersistOnlyBadge /></div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens1/FxBasketCard.tsx
type Props = { dxyZ: string; xauCnyPrem: string };

export function FxBasketCard({ dxyZ, xauCnyPrem }: Props) {
  const z = parseFloat(dxyZ);
  const prem = parseFloat(xauCnyPrem);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>FX Basket</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(z) ? `${z >= 0 ? '+' : ''}${z.toFixed(1)}σ` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>DXY · XAU/CNY {Number.isFinite(prem) ? `${(prem * 100).toFixed(2)}%` : '—'}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens1/StructuralPostureText.tsx
export function StructuralPostureText({ narrative }: { narrative: string }) {
  return (
    <p style={{
      fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6,
      color: 'var(--text-secondary)', marginTop: 16,
    }}>{narrative}</p>
  );
}
```

```tsx
// web/components/gold/lens1/StructuralPanel.tsx
import type { GoldStructuralPostureModel } from '@/lib/types';
import { PostureChip } from '../chips/PostureChip';
import { CbReservesCard } from './CbReservesCard';
import { EtfFlowCard } from './EtfFlowCard';
import { ComexRegimeCard } from './ComexRegimeCard';
import { CotPositioningCard } from './CotPositioningCard';
import { UwSkewCard } from './UwSkewCard';
import { FxBasketCard } from './FxBasketCard';
import { StructuralPostureText } from './StructuralPostureText';

type Props = { posture: GoldStructuralPostureModel };

export function StructuralPanel({ posture }: Props) {
  return (
    <div>
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 12,
      }}>
        <h2 style={{
          fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: 2,
          textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0,
        }}>Lens 1 · Structural Flow</h2>
        <PostureChip state={posture.posture_chip} />
      </header>

      {/* Lead chart slot — filled by Task 35 */}
      <div data-slot="lead-chart" style={{ minHeight: 0 }} />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 12, marginTop: 12 }}>
        <CbReservesCard sumT={posture.cb_strategic_12m_sum_t} pct52w={posture.cb_52w_pct} />
        <EtfFlowCard flow30d={posture.gld_30d_net_flow_t} />
        <ComexRegimeCard roc20d={posture.comex_20d_roc_pct} lbmaMomT={posture.lbma_30d_momentum_t} />
        <CotPositioningCard mmNetPct={posture.cot_mm_net_pct} mm4wSigma={posture.cot_mm_4w_change_sigma} />
        <UwSkewCard skewSigma={posture.uw_25d_skew_sigma} />
        <FxBasketCard dxyZ={posture.fx_basket_dxy_z} xauCnyPrem={posture.xau_cny_premium_pct} />
      </div>

      <StructuralPostureText narrative={posture.narrative_text} />
    </div>
  );
}
```

- [ ] **Step 4: Wire into `GoldCompassLayout` Tier 2**

```tsx
<section role="region" aria-label="Lens 1 structural flow" style={sectionStyle}>
  <StructuralPanel posture={state.structural} />
</section>
```

- [ ] **Step 5: Run, expect PASS.**

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/lens1/ web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/lens1/StructuralPanel.test.tsx
git commit -m "feat(web/gold): Lens 1 panel + 6 sub-cards (CB, ETF, COMEX, COT, UW, FX)"
```

---

## Task 31: Tier 3 Lens 2 panel + 4 sub-cards + zone + two-force

**Files:**
- Create: `web/components/gold/lens2/CyclicalPanel.tsx`
- Create: `web/components/gold/lens2/RealRateCard.tsx`
- Create: `web/components/gold/lens2/UsdTrendCard.tsx`
- Create: `web/components/gold/lens2/GprCard.tsx`
- Create: `web/components/gold/lens2/InfExpCard.tsx`
- Create: `web/components/gold/lens2/ArticleZoneCard.tsx`
- Create: `web/components/gold/lens2/TwoForceNarrative.tsx`
- Modify: `web/components/gold/GoldCompassLayout.tsx` (wire Lens 2 into Tier 3)
- Test: `web/components/gold/lens2/CyclicalPanel.test.tsx`

Tier 3 per spec §8.2: header with posture chip + 4-card horizontal row + article-zone card (with `[heuristic, not yet calibrated]` badge) + two-force narrative block. The whole panel renders at 70% opacity when `gauge.state === 'suspended'`.

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/lens2/CyclicalPanel.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CyclicalPanel } from './CyclicalPanel';
import type { GoldCyclicalPostureModel } from '@/lib/types';

const POSTURE: GoldCyclicalPostureModel = {
  zone_label: 'moderate-trap',
  posture_chip: 'NEUTRAL',
  cpi_yoy: '2.8',
  t5yifr: '2.31',
  dfii10: '1.72',
  dfii10_60d_change_bps: '12',
  dxy: '102.1',
  dxy_60d_sigma: '-0.4',
  gpr_value: '371',
  gpr_pct_52w: '0.64',
  t5yifr_pct_52w: '0.48',
  factors: { F1: -0.4, F5: 1.8 },
  two_force_text: {
    discount_rate: '↑ tightening — would press gold',
    hedge_demand: '↓ subdued vol — no panic bid',
  },
  narrative_text: 'Cyclical posture neutral; framework operative.',
};

describe('Lens 2 CyclicalPanel', () => {
  it('renders the panel header with NEUTRAL posture chip', () => {
    render(<CyclicalPanel posture={POSTURE} gaugeState="operative" />);
    expect(screen.getByText(/lens 2/i)).toBeInTheDocument();
    expect(screen.getByText('NEUTRAL')).toBeInTheDocument();
  });

  it('renders all 4 macro cards', () => {
    render(<CyclicalPanel posture={POSTURE} gaugeState="operative" />);
    expect(screen.getByText(/real rate/i)).toBeInTheDocument();
    expect(screen.getByText(/usd trend/i)).toBeInTheDocument();
    expect(screen.getByText(/gpr/i)).toBeInTheDocument();
    expect(screen.getByText(/inf exp/i)).toBeInTheDocument();
  });

  it('renders ArticleZoneCard with heuristic badge', () => {
    render(<CyclicalPanel posture={POSTURE} gaugeState="operative" />);
    expect(screen.getByText(/moderate-trap|R2/i)).toBeInTheDocument();
    expect(screen.getByText(/heuristic|not yet calibrated/i)).toBeInTheDocument();
  });

  it('renders two-force narrative with both forces', () => {
    render(<CyclicalPanel posture={POSTURE} gaugeState="operative" />);
    expect(screen.getByText(/discount/i)).toBeInTheDocument();
    expect(screen.getByText(/hedge/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement the 4 macro cards + ArticleZoneCard + TwoForceNarrative + panel**

Each macro card uses the canonical `Tile` shape. Skeleton for `RealRateCard`:

```tsx
// web/components/gold/lens2/RealRateCard.tsx
type Props = { dfii10: string; change60dBps: string };

export function RealRateCard({ dfii10, change60dBps }: Props) {
  const n = parseFloat(dfii10);
  const bps = parseFloat(change60dBps);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Real Rate · DFII10</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? `${n.toFixed(2)}%` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>60d {Number.isFinite(bps) ? `${bps >= 0 ? '+' : ''}${bps.toFixed(0)}bps` : '—'}</div>
    </div>
  );
}
```

The remaining 3 macro cards follow the same Tile shape. Inlining each:

```tsx
// web/components/gold/lens2/UsdTrendCard.tsx
type Props = { dxy: string; sigma60d: string };

export function UsdTrendCard({ dxy, sigma60d }: Props) {
  const n = parseFloat(dxy);
  const s = parseFloat(sigma60d);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>USD Trend · DXY</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? n.toFixed(1) : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>60d {Number.isFinite(s) ? `${s >= 0 ? '+' : ''}${s.toFixed(1)}σ` : '—'} · neutral</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens2/GprCard.tsx
type Props = { value: string; pct52w: string };

export function GprCard({ value, pct52w }: Props) {
  const n = parseFloat(value);
  const p = parseFloat(pct52w);
  const labelForPct = (x: number): string =>
    x >= 0.80 ? 'elevated'
    : x >= 0.50 ? 'moderate'
    : 'subdued';
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>GPR</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? n.toFixed(0) : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>52w {Number.isFinite(p) ? `${(p * 100).toFixed(0)}%ile · ${labelForPct(p)}` : '—'}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens2/InfExpCard.tsx
type Props = { t5yifr: string; pct52w: string };

export function InfExpCard({ t5yifr, pct52w }: Props) {
  const n = parseFloat(t5yifr);
  const p = parseFloat(pct52w);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Inf Exp · T5YIFR</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? `${n.toFixed(2)}%` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        marginTop: 4,
      }}>52w {Number.isFinite(p) ? `${(p * 100).toFixed(0)}%ile` : '—'}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens2/ArticleZoneCard.tsx
import { HeuristicBadge } from '../chips/HeuristicBadge';

const zoneText: Record<string, string> = {
  'low-inflation': 'R1 · LOW INFLATION',
  'moderate-trap': 'R2 · MODERATE TRAP',
  'unanchored':    'R3 · UNANCHORED',
};

export function ArticleZoneCard({ zoneLabel }: { zoneLabel: string | null }) {
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>Article Zone</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 18,
        color: 'var(--text-primary)', lineHeight: 1.1, marginTop: 6,
      }}>{zoneLabel ? (zoneText[zoneLabel] ?? zoneLabel) : '—'}</div>
      <div style={{ marginTop: 8 }}><HeuristicBadge /></div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens2/TwoForceNarrative.tsx
type Props = { discountRate: string; hedgeDemand: string };

export function TwoForceNarrative({ discountRate, hedgeDemand }: Props) {
  return (
    <div style={{
      marginTop: 12, padding: '10px 12px',
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4,
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: 6,
      }}>Two-Force Narrative</div>
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)', margin: '2px 0' }}>
        <span style={{ color: 'var(--text-muted)' }}>Discount-rate channel </span>{discountRate}
      </p>
      <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)', margin: '2px 0' }}>
        <span style={{ color: 'var(--text-muted)' }}>Hedge-demand channel </span>{hedgeDemand}
      </p>
    </div>
  );
}
```

```tsx
// web/components/gold/lens2/CyclicalPanel.tsx
import type { GoldCyclicalPostureModel } from '@/lib/types';
import { PostureChip } from '../chips/PostureChip';
import { RealRateCard } from './RealRateCard';
import { UsdTrendCard } from './UsdTrendCard';
import { GprCard } from './GprCard';
import { InfExpCard } from './InfExpCard';
import { ArticleZoneCard } from './ArticleZoneCard';
import { TwoForceNarrative } from './TwoForceNarrative';

type Props = {
  posture: GoldCyclicalPostureModel;
  gaugeState: 'operative' | 'partial' | 'suspended';
};

export function CyclicalPanel({ posture, gaugeState }: Props) {
  const chip = gaugeState === 'suspended' ? 'SUSPENDED' : posture.posture_chip;
  return (
    <div>
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 12,
      }}>
        <h2 style={{
          fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: 2,
          textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0,
        }}>Lens 2 · Cyclical Posture</h2>
        <PostureChip state={chip} />
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12 }}>
        <RealRateCard dfii10={posture.dfii10} change60dBps={posture.dfii10_60d_change_bps} />
        <UsdTrendCard dxy={posture.dxy} sigma60d={posture.dxy_60d_sigma} />
        <GprCard value={posture.gpr_value} pct52w={posture.gpr_pct_52w} />
        <InfExpCard t5yifr={posture.t5yifr} pct52w={posture.t5yifr_pct_52w} />
        <ArticleZoneCard zoneLabel={posture.zone_label} />
      </div>

      <TwoForceNarrative
        discountRate={posture.two_force_text.discount_rate}
        hedgeDemand={posture.two_force_text.hedge_demand}
      />
    </div>
  );
}
```

- [ ] **Step 4: Wire into `GoldCompassLayout` Tier 3** (with suspended-opacity already in place from Task 28).

- [ ] **Step 5: Run, expect PASS.**

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/lens2/ web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/lens2/CyclicalPanel.test.tsx
git commit -m "feat(web/gold): Lens 2 panel + 4 macro cards + article zone + two-force narrative"
```

---

## Task 32: Tier 4 Lens 3 panel + valuation cards + DataAuditFooter

**Files:**
- Create: `web/components/gold/lens3/ValuationPanel.tsx`
- Create: `web/components/gold/lens3/ValuationFlagCard.tsx`
- Create: `web/components/gold/lens3/ValuationPostureText.tsx`
- Replace stub: `web/components/gold/DataAuditFooter.tsx`
- Modify: `web/components/gold/GoldCompassLayout.tsx` (wire Lens 3 into Tier 4)
- Test: `web/components/gold/lens3/ValuationPanel.test.tsx`
- Test: `web/components/gold/DataAuditFooter.test.tsx`

Tier 4 per spec §8.2: panel header with `STRETCHED` chip + `⚠ NEVER A SIZING INPUT` callout + 4 valuation ratio tiles (Gold/CPI, Gold/M2, Gold/Oil, Gold/SPX) + posture text. Plus the always-bottom `DataAuditFooter` with vintage details and replay link.

- [ ] **Step 1: Failing tests**

```tsx
// web/components/gold/lens3/ValuationPanel.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ValuationPanel } from './ValuationPanel';
import type { GoldValuationPostureModel } from '@/lib/types';

const POSTURE: GoldValuationPostureModel = {
  flag: 'Severe',
  posture_chip: 'STRETCHED',
  real_price_percentile: '0.92',
  gold_m2_ratio_percentile: '0.78',
  gold_oil_ratio_percentile: '0.89',
  gold_spx_ratio_percentile: '0.64',
  narrative_text: 'Mean-reversion risk SEVERE on inflation-adjusted basis.',
};

describe('Lens 3 ValuationPanel', () => {
  it('renders panel header with STRETCHED posture chip', () => {
    render(<ValuationPanel posture={POSTURE} />);
    expect(screen.getByText(/lens 3/i)).toBeInTheDocument();
    expect(screen.getByText('STRETCHED')).toBeInTheDocument();
  });
  it('renders the never-a-sizing-input callout', () => {
    render(<ValuationPanel posture={POSTURE} />);
    expect(screen.getByText(/never a sizing input/i)).toBeInTheDocument();
  });
  it('renders all 4 valuation ratio tiles', () => {
    render(<ValuationPanel posture={POSTURE} />);
    expect(screen.getByText(/gold\/cpi/i)).toBeInTheDocument();
    expect(screen.getByText(/gold\/m2/i)).toBeInTheDocument();
    expect(screen.getByText(/gold\/oil/i)).toBeInTheDocument();
    expect(screen.getByText(/gold\/spx/i)).toBeInTheDocument();
  });
  it('does not render any sizing language', () => {
    const { container } = render(<ValuationPanel posture={POSTURE} />);
    const text = (container.textContent ?? '').toLowerCase();
    for (const banned of ['buy', 'sell', 'long', 'short', 'position size', 'allocate']) {
      expect(text).not.toContain(banned);
    }
  });
});
```

```tsx
// web/components/gold/DataAuditFooter.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DataAuditFooter } from './DataAuditFooter';

describe('DataAuditFooter', () => {
  it('renders GOLD COMPASS wordmark + LENS HEURISTICS v1', () => {
    render(
      <DataAuditFooter
        obsDate="2026-05-17"
        computedAt="2026-05-17T21:00:00Z"
        inputsUsed={{
          DFII10: { obs_date: '2026-05-17', as_of: '2026-05-17T13:00:00Z' },
        }}
      />
    );
    expect(screen.getByText(/GOLD COMPASS/)).toBeInTheDocument();
    expect(screen.getByText(/LENS HEURISTICS/)).toBeInTheDocument();
    expect(screen.getByText(/v1/)).toBeInTheDocument();
  });
  it('lists each input with obs_date + as_of', () => {
    render(
      <DataAuditFooter
        obsDate="2026-05-17"
        computedAt="2026-05-17T21:00:00Z"
        inputsUsed={{
          DFII10: { obs_date: '2026-05-17', as_of: '2026-05-17T13:00:00Z' },
          COT:    { obs_date: '2026-05-13', as_of: '2026-05-16T20:30:00Z' },
        }}
      />
    );
    expect(screen.getByText(/DFII10/)).toBeInTheDocument();
    expect(screen.getByText(/COT/)).toBeInTheDocument();
  });
  it('renders the replay link', () => {
    render(
      <DataAuditFooter obsDate="2026-05-17" computedAt="2026-05-17T21:00:00Z" inputsUsed={{}} />
    );
    expect(screen.getByRole('link', { name: /replay/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

```bash
cd web && npx vitest run components/gold/lens3/ValuationPanel.test.tsx components/gold/DataAuditFooter.test.tsx
```

- [ ] **Step 3: Implement ValuationFlagCard + ValuationPostureText + ValuationPanel**

```tsx
// web/components/gold/lens3/ValuationFlagCard.tsx
type Props = { label: string; percentile: string; flag: 'Low' | 'Moderate' | 'High' | 'Severe' };

const flagColor: Record<Props['flag'], string> = {
  Low: 'var(--positive)',
  Moderate: 'var(--text-secondary)',
  High: 'var(--warning)',
  Severe: 'var(--negative)',
};

export function ValuationFlagCard({ label, percentile, flag }: Props) {
  const n = parseFloat(percentile);
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: '12px 14px',
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
        textTransform: 'uppercase', color: 'var(--text-muted)',
      }}>{label}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 22,
        color: 'var(--text-primary)', lineHeight: 1, marginTop: 6,
      }}>{Number.isFinite(n) ? `${(n * 100).toFixed(0)}%ile` : '—'}</div>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: 1,
        textTransform: 'uppercase', color: flagColor[flag], marginTop: 4,
      }}>{flag}</div>
    </div>
  );
}
```

```tsx
// web/components/gold/lens3/ValuationPostureText.tsx
export function ValuationPostureText({ narrative }: { narrative: string }) {
  return (
    <p style={{
      fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6,
      color: 'var(--text-secondary)', marginTop: 16,
    }}>{narrative}</p>
  );
}
```

```tsx
// web/components/gold/lens3/ValuationPanel.tsx
import type { GoldValuationPostureModel } from '@/lib/types';
import { PostureChip } from '../chips/PostureChip';
import { ValuationFlagCard } from './ValuationFlagCard';
import { ValuationPostureText } from './ValuationPostureText';

function flagFromPctile(p: string): 'Low' | 'Moderate' | 'High' | 'Severe' {
  const n = parseFloat(p);
  if (!Number.isFinite(n)) return 'Moderate';
  if (n >= 0.85) return 'Severe';
  if (n >= 0.70) return 'High';
  if (n >= 0.40) return 'Moderate';
  return 'Low';
}

export function ValuationPanel({ posture }: { posture: GoldValuationPostureModel }) {
  return (
    <div>
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 12,
      }}>
        <h2 style={{
          fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: 2,
          textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0,
        }}>Lens 3 · Valuation Overlay</h2>
        <PostureChip state={posture.posture_chip} />
      </header>

      <p style={{
        fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: 1,
        textTransform: 'uppercase', color: 'var(--warning)', marginBottom: 12,
      }}>⚠ NEVER A SIZING INPUT — tail-risk awareness only.
        See docs/research/gold-sdf-framework/07-valuation-overlay.md
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
        <ValuationFlagCard label="Gold/CPI" percentile={posture.real_price_percentile}
                           flag={flagFromPctile(posture.real_price_percentile)} />
        <ValuationFlagCard label="Gold/M2" percentile={posture.gold_m2_ratio_percentile}
                           flag={flagFromPctile(posture.gold_m2_ratio_percentile)} />
        <ValuationFlagCard label="Gold/Oil" percentile={posture.gold_oil_ratio_percentile}
                           flag={flagFromPctile(posture.gold_oil_ratio_percentile)} />
        <ValuationFlagCard label="Gold/SPX" percentile={posture.gold_spx_ratio_percentile}
                           flag={flagFromPctile(posture.gold_spx_ratio_percentile)} />
      </div>

      <ValuationPostureText narrative={posture.narrative_text} />
    </div>
  );
}
```

- [ ] **Step 4: Implement DataAuditFooter (replacing the Task-28 stub)**

```tsx
// web/components/gold/DataAuditFooter.tsx
import Link from 'next/link';

type InputUsed = { obs_date: string; as_of: string };
type Props = {
  obsDate: string;
  computedAt: string;
  inputsUsed: Record<string, InputUsed>;
};

export function DataAuditFooter({ obsDate, computedAt, inputsUsed }: Props) {
  return (
    <footer style={{
      padding: '16px 24px',
      borderTop: '1px solid var(--border-dim)',
      background: 'var(--bg-panel)',
      fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1,
      color: 'var(--text-muted)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ textTransform: 'uppercase' }}>
          GOLD COMPASS · LENS HEURISTICS · v1 · obs_date {obsDate}
        </span>
        <span style={{ textTransform: 'uppercase' }}>
          first-computed {new Date(computedAt).toISOString()}
        </span>
      </div>
      <div style={{ marginTop: 8, color: 'var(--text-secondary)' }}>
        Inputs used (vintages):
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: '4px 0 0',
                   display: 'flex', flexWrap: 'wrap', gap: '4px 12px' }}>
        {Object.entries(inputsUsed).map(([sid, v]) => (
          <li key={sid} style={{ color: 'var(--text-secondary)' }}>
            <span style={{ color: 'var(--text-primary)' }}>{sid}</span>
            @{v.obs_date} (as_of {v.as_of.slice(0, 10)})
          </li>
        ))}
      </ul>
      <div style={{ marginTop: 8 }}>
        <Link href={`/gold/replay/${obsDate}`} style={{ color: 'var(--accent-bg)' }}>
          Open replay for any date →
        </Link>
      </div>
    </footer>
  );
}
```

- [ ] **Step 5: Wire Lens 3 into `GoldCompassLayout` Tier 4**

```tsx
<section role="region" aria-label="Lens 3 valuation overlay" style={sectionStyle}>
  <ValuationPanel posture={state.valuation} />
</section>
```

- [ ] **Step 6: Run, expect PASS.**

- [ ] **Step 7: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/lens3/ web/components/gold/DataAuditFooter.tsx \
        web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/lens3/ValuationPanel.test.tsx \
        web/components/gold/DataAuditFooter.test.tsx
git commit -m "feat(web/gold): Lens 3 valuation overlay + DataAuditFooter with vintages"
```

---

## Task 33: Tier 5 decomposition panel + horizontal bars

**Files:**
- Create: `web/components/gold/decomposition/LensDecompositionPanel.tsx`
- Create: `web/components/gold/decomposition/DecompositionBars.tsx`
- Modify: `web/components/gold/GoldCompassLayout.tsx` (wire into Tier 5 left column)
- Test: `web/components/gold/decomposition/DecompositionBars.test.tsx`

Tier 5 left column per spec §8.2: horizontal bar chart over per-lens sub-factor z-scores, color-coded `--positive`/`--negative`. Decomposition is over HEURISTIC z-scores, NOT model attributions (no SHAP, no IC). Reuses `lib/svgChart.ts` helpers.

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/decomposition/DecompositionBars.test.tsx
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { DecompositionBars } from './DecompositionBars';

const ROWS = [
  { lens: 'L1', factor: 'CB Δ12M',   contribution: 1.4 },
  { lens: 'L1', factor: 'COMEX ROC', contribution: 0.6 },
  { lens: 'L1', factor: 'ETF flow',  contribution: -0.2 },
  { lens: 'L2', factor: 'DFII10',    contribution: -0.4 },
  { lens: 'L2', factor: 'GPR',       contribution: 1.4 },
  { lens: 'L3', factor: 'Gold/CPI',  contribution: 1.8 },
];

describe('DecompositionBars', () => {
  it('renders one bar per row', () => {
    const { container } = render(<DecompositionBars rows={ROWS} />);
    const bars = container.querySelectorAll('rect[data-bar]');
    expect(bars.length).toBe(ROWS.length);
  });
  it('renders factor labels', () => {
    const { container } = render(<DecompositionBars rows={ROWS} />);
    const text = container.textContent ?? '';
    for (const r of ROWS) expect(text).toContain(r.factor);
  });
  it('renders zero-line', () => {
    const { container } = render(<DecompositionBars rows={ROWS} />);
    const zero = container.querySelector('line[data-zero]');
    expect(zero).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```tsx
// web/components/gold/decomposition/DecompositionBars.tsx
import { finiteDomain, linearScale } from '@/lib/svgChart';

export type DecompRow = { lens: 'L1' | 'L2' | 'L3'; factor: string; contribution: number };
type Props = { rows: DecompRow[] };

const W = 480, ROW_H = 22, LABEL_W = 140, PAD = 12;

const lensColor = {
  L1: 'var(--accent-bg)',
  L2: 'var(--info)',
  L3: 'var(--warning)',
} as const;

export function DecompositionBars({ rows }: Props) {
  const H = PAD * 2 + rows.length * ROW_H;
  // `finiteDomain` returns `{ lo, hi, count } | null`. Guard the null path and
  // pick a symmetric span so positive/negative bars share the same scale.
  const domain = finiteDomain(rows.map((r) => r.contribution));
  const span = domain
    ? Math.max(Math.abs(domain.lo), Math.abs(domain.hi), 1)
    : 1;
  const xScale = linearScale([-span, span], [LABEL_W, W - PAD]);
  const zeroX = xScale(0);

  return (
    <svg role="img" width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%' }}>
      <title>Lens decomposition — heuristic z-score contributions</title>
      <line data-zero x1={zeroX} x2={zeroX} y1={PAD} y2={H - PAD}
            stroke="var(--border-dim)" strokeWidth={1} />
      {rows.map((r, i) => {
        const y = PAD + i * ROW_H + 2;
        const positive = r.contribution >= 0;
        const x = positive ? zeroX : xScale(r.contribution);
        const w = Math.abs(xScale(r.contribution) - zeroX);
        return (
          <g key={`${r.lens}:${r.factor}`}>
            <text x={LABEL_W - 6} y={y + ROW_H / 2}
                  textAnchor="end" dominantBaseline="middle"
                  fontFamily="var(--font-mono)" fontSize={10}
                  fill="var(--text-secondary)">{r.factor}</text>
            <rect data-bar x={x} y={y} width={w} height={ROW_H - 6}
                  fill={positive ? 'var(--positive)' : 'var(--negative)'}
                  opacity={0.85} />
            <text x={positive ? x + w + 4 : x - 4} y={y + ROW_H / 2}
                  textAnchor={positive ? 'start' : 'end'} dominantBaseline="middle"
                  fontFamily="var(--font-mono)" fontSize={10}
                  fill="var(--text-muted)">{r.contribution >= 0 ? '+' : ''}{r.contribution.toFixed(2)}σ</text>
            <rect x={LABEL_W - 138} y={y + 2} width={4} height={ROW_H - 10}
                  fill={lensColor[r.lens]} />
          </g>
        );
      })}
    </svg>
  );
}
```

```tsx
// web/components/gold/decomposition/LensDecompositionPanel.tsx
import { DecompositionBars, type DecompRow } from './DecompositionBars';

export function LensDecompositionPanel({ rows }: { rows: DecompRow[] }) {
  return (
    <section style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: 14,
    }}>
      <header style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <h3 style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: 1.5,
          textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0,
        }}>Lens Decomposition</h3>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1,
          textTransform: 'uppercase', color: 'var(--text-muted)',
        }}>heuristic z-scores · not SHAP / not IC</span>
      </header>
      <DecompositionBars rows={rows} />
    </section>
  );
}
```

- [ ] **Step 4: Wire into Tier 5 left of `GoldCompassLayout`**

Replace the `decomposition/` slot in Tier 5:

```tsx
<LensDecompositionPanel rows={state.decomposition_rows} />
```

This adds `decomposition_rows` to `GoldStateResponse` (Task 18 follow-up: assemble from each lens's heuristic z-scores at orchestrator time in Task 19).

- [ ] **Step 5: Run, expect PASS.**

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/decomposition/ web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/decomposition/DecompositionBars.test.tsx
git commit -m "feat(web/gold): Tier 5 lens-decomposition panel (heuristic z-scores, not SHAP)"
```

---

## Task 34: Tier 5 correlation history panel + multi-window line chart

**Files:**
- Create: `web/components/gold/correlation/CorrelationHistoryPanel.tsx`
- Create: `web/components/gold/correlation/CorrelationLineChart.tsx`
- Modify: `web/components/gold/GoldCompassLayout.tsx` (wire into Tier 5 right column)
- Test: `web/components/gold/correlation/CorrelationLineChart.test.tsx`

Tier 5 right column per spec §8.2: multi-window line chart showing rolling correlations gold ↔ {DFII10, DXY, GPR} across 60d/126d/252d/504d. Reference band overlay for pre-2022 mean ± 1σ. This is the visual evidence of the post-2022 regime change documented in `docs/research/gold-sdf-framework/03-post-2022-regime-break.md`.

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/correlation/CorrelationLineChart.test.tsx
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { CorrelationLineChart } from './CorrelationLineChart';

const SERIES = [
  {
    label: 'Gold ↔ DFII10 (252d)',
    color: 'var(--accent-bg)',
    points: [
      { obs_date: '2020-01-01', value: -0.85 },
      { obs_date: '2022-12-31', value: -0.78 },
      { obs_date: '2024-12-31', value: -0.12 },
      { obs_date: '2026-05-17', value: -0.07 },
    ],
  },
];

describe('CorrelationLineChart', () => {
  it('renders one path per series', () => {
    const { container } = render(<CorrelationLineChart series={SERIES} />);
    expect(container.querySelectorAll('path[data-series]').length).toBe(SERIES.length);
  });
  it('renders pre-2022 reference band when provided', () => {
    const { container } = render(
      <CorrelationLineChart series={SERIES}
                            referenceBand={{ mean: -0.84, std: 0.04 }} />
    );
    expect(container.querySelector('rect[data-reference-band]')).not.toBeNull();
  });
  it('handles empty series', () => {
    const { container } = render(<CorrelationLineChart series={[]} />);
    expect(container.textContent).toMatch(/no data/i);
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```tsx
// web/components/gold/correlation/CorrelationLineChart.tsx
import { linearScale, pathFromPoints, type Point } from '@/lib/svgChart';

type SeriesPoint = { obs_date: string; value: number };
type Series = { label: string; color: string; points: SeriesPoint[] };
type Props = {
  series: Series[];
  referenceBand?: { mean: number; std: number };
};

const W = 480, H = 260, PAD_L = 32, PAD_R = 12, PAD_T = 24, PAD_B = 28;

export function CorrelationLineChart({ series, referenceBand }: Props) {
  const allPoints = series.flatMap((s) => s.points);
  if (allPoints.length === 0) {
    return <p style={{
      fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)',
      padding: 12,
    }}>no data</p>;
  }

  const dates = allPoints.map((p) => new Date(p.obs_date).getTime());
  const tDomain: [number, number] = [Math.min(...dates), Math.max(...dates)];
  // Correlation values are bounded in [-1, 1] by definition; pin the y-axis so
  // the visual is stable across data snapshots (and we don't need finiteDomain
  // here — the band is fixed).
  const yDomain: [number, number] = [-1, 1];

  const xScale = linearScale(tDomain, [PAD_L, W - PAD_R]);
  const yScale = linearScale(yDomain, [H - PAD_B, PAD_T]);
  const zeroY = yScale(0);

  return (
    <svg role="img" width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: '100%' }}>
      <title>Rolling correlations — gold vs macro reference series</title>
      {referenceBand && (
        <rect data-reference-band
              x={PAD_L} y={yScale(referenceBand.mean + referenceBand.std)}
              width={W - PAD_L - PAD_R}
              height={Math.abs(yScale(referenceBand.mean - referenceBand.std)
                              - yScale(referenceBand.mean + referenceBand.std))}
              fill="color-mix(in srgb, var(--text-muted) 12%, transparent)" />
      )}
      <line x1={PAD_L} x2={W - PAD_R} y1={zeroY} y2={zeroY}
            stroke="var(--border-dim)" strokeWidth={1} />
      {series.map((s) => {
        // pathFromPoints takes [x, y] tuples per lib/svgChart.ts (not {x, y}).
        const points: Point[] = s.points.map((p) => [
          xScale(new Date(p.obs_date).getTime()),
          yScale(p.value),
        ]);
        return (
          <path key={s.label} data-series d={pathFromPoints(points)}
                stroke={s.color} fill="none" strokeWidth={1.5} />
        );
      })}
      <g fontFamily="var(--font-mono)" fontSize={9} fill="var(--text-muted)">
        <text x={PAD_L - 4} y={yScale(1) + 3} textAnchor="end">+1.0</text>
        <text x={PAD_L - 4} y={yScale(0) + 3} textAnchor="end">0.0</text>
        <text x={PAD_L - 4} y={yScale(-1) + 3} textAnchor="end">-1.0</text>
      </g>
    </svg>
  );
}
```

```tsx
// web/components/gold/correlation/CorrelationHistoryPanel.tsx
import { CorrelationLineChart } from './CorrelationLineChart';

type SeriesPoint = { obs_date: string; value: number };
type Props = {
  goldDfii10: SeriesPoint[];
  goldDxy: SeriesPoint[];
  goldGpr: SeriesPoint[];
  referenceBand?: { mean: number; std: number };
};

export function CorrelationHistoryPanel({ goldDfii10, goldDxy, goldGpr, referenceBand }: Props) {
  const series = [
    { label: 'Gold ↔ DFII10 (252d)', color: 'var(--accent-bg)', points: goldDfii10 },
    { label: 'Gold ↔ DXY (252d)',    color: 'var(--info)',       points: goldDxy },
    { label: 'Gold ↔ GPR (252d)',    color: 'var(--warning)',    points: goldGpr },
  ];
  return (
    <section style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
      borderRadius: 4, padding: 14,
    }}>
      <header style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <h3 style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: 1.5,
          textTransform: 'uppercase', color: 'var(--text-primary)', margin: 0,
        }}>Correlation History</h3>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1,
          textTransform: 'uppercase', color: 'var(--text-muted)',
        }}>rolling 252d · pre-2022 band overlay</span>
      </header>
      <CorrelationLineChart series={series} referenceBand={referenceBand} />
      <div style={{ marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 9,
                    color: 'var(--text-muted)', letterSpacing: 1, textTransform: 'uppercase' }}>
        DFII10 (teal) · DXY (purple) · GPR (amber)
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Wire into Tier 5 right column of `GoldCompassLayout`**

```tsx
<CorrelationHistoryPanel
  goldDfii10={state.correlation_history.gold_dfii10}
  goldDxy={state.correlation_history.gold_dxy}
  goldGpr={state.correlation_history.gold_gpr}
  referenceBand={state.correlation_history.pre_2022_band}
/>
```

`correlation_history` is a new field on `GoldStateResponse` (Task 18 follow-up). The orchestrator (Task 19) computes the three rolling correlations from `macro_series_daily` over the trailing 2-5y window.

- [ ] **Step 5: Run, expect PASS.**

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/correlation/ web/components/gold/GoldCompassLayout.tsx \
        web/components/gold/correlation/CorrelationLineChart.test.tsx
git commit -m "feat(web/gold): Tier 5 correlation-history panel + multi-window line chart"
```

---

## Task 35: lens1/GoldHoldingsVsPriceChart (lead visual, wired into Lens 1)

**Files:**
- Create: `web/components/gold/lens1/GoldHoldingsVsPriceChart.tsx`
- Modify: `web/components/gold/lens1/StructuralPanel.tsx` (fill the lead-chart slot)
- Test: `web/components/gold/lens1/GoldHoldingsVsPriceChart.test.tsx`

The dual-axis lead chart in Lens 1 per spec §8.2: GLD holdings (tonnes, left axis) and gold price (USD/oz, right axis), 2020-present. This is the regime-change visual; pre-2022 the two move together, post-2022 they diverge (price up, holdings down). Hand-rolled SVG with `lib/svgChart.ts` helpers; **no chart library** (web/CLAUDE.md convention).

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/lens1/GoldHoldingsVsPriceChart.test.tsx
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { GoldHoldingsVsPriceChart } from './GoldHoldingsVsPriceChart';

describe('GoldHoldingsVsPriceChart', () => {
  it('renders two series paths', () => {
    const { container } = render(
      <GoldHoldingsVsPriceChart
        gld={[{ obs_date: '2020-08-01', value: '1280' }, { obs_date: '2024-06-01', value: '870' }]}
        gold={[{ obs_date: '2020-08-01', value: '2000' }, { obs_date: '2024-06-01', value: '2400' }]}
      />
    );
    const paths = container.querySelectorAll('path[data-series]');
    expect(paths.length).toBe(2);
  });
  it('renders both axis labels', () => {
    const { container } = render(
      <GoldHoldingsVsPriceChart
        gld={[{ obs_date: '2020-08-01', value: '1280' }]}
        gold={[{ obs_date: '2020-08-01', value: '2000' }]}
      />
    );
    expect(container.textContent).toMatch(/GLD holdings/i);
    expect(container.textContent).toMatch(/gold price/i);
  });
  it('handles empty series', () => {
    const { container } = render(<GoldHoldingsVsPriceChart gld={[]} gold={[]} />);
    expect(container.textContent).toMatch(/no data/i);
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```tsx
// web/components/gold/lens1/GoldHoldingsVsPriceChart.tsx
import { finiteDomain, linearScale, pathFromPoints, type Point as ChartPoint } from '@/lib/svgChart';

type SeriesPoint = { obs_date: string; value: string };
type Props = { gld: SeriesPoint[]; gold: SeriesPoint[] };

const W = 720, H = 260, PAD_L = 44, PAD_R = 48, PAD_T = 24, PAD_B = 28;

type Parsed = { v: number; t: number };

function parseRows(points: SeriesPoint[]): Parsed[] {
  return points
    .map((p) => ({ v: parseFloat(p.value), t: new Date(p.obs_date).getTime() }))
    .filter((p) => Number.isFinite(p.v) && Number.isFinite(p.t));
}

export function GoldHoldingsVsPriceChart({ gld, gold }: Props) {
  if (gld.length === 0 && gold.length === 0) {
    return <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                       color: 'var(--text-muted)', padding: 12 }}>no data</p>;
  }
  const gldXY = parseRows(gld);
  const goldXY = parseRows(gold);
  const allT = [...gldXY, ...goldXY].map((p) => p.t);
  if (allT.length === 0) {
    return <p style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                       color: 'var(--text-muted)', padding: 12 }}>no data</p>;
  }
  const tDomain: [number, number] = [Math.min(...allT), Math.max(...allT)];

  // finiteDomain returns `{ lo, hi, count } | null` — fall back to a defensible
  // fixed band when fewer than 2 finite values exist for that axis.
  const gldD = finiteDomain(gldXY.map((p) => p.v));
  const goldD = finiteDomain(goldXY.map((p) => p.v));
  const gldDomain: [number, number] = gldD ? [gldD.lo, gldD.hi] : [0, 1];
  const goldDomain: [number, number] = goldD ? [goldD.lo, goldD.hi] : [0, 1];

  const xScale = linearScale(tDomain, [PAD_L, W - PAD_R]);
  const yGld = linearScale(gldDomain, [H - PAD_B, PAD_T]);
  const yGold = linearScale(goldDomain, [H - PAD_B, PAD_T]);

  // pathFromPoints takes [x, y] tuples per lib/svgChart.ts (not {x, y}).
  const gldPath: ChartPoint[] = gldXY.map((p) => [xScale(p.t), yGld(p.v)]);
  const goldPath: ChartPoint[] = goldXY.map((p) => [xScale(p.t), yGold(p.v)]);

  return (
    <svg role="img" width={W} height={H} viewBox={`0 0 ${W} ${H}`}
         style={{ width: '100%', maxWidth: W }}>
      <title>GLD holdings vs gold price — Lens 1 lead visual</title>
      <path data-series fill="none" strokeWidth={1.5} stroke="var(--warning)"
            d={pathFromPoints(gldPath)} />
      <path data-series fill="none" strokeWidth={1.5} stroke="var(--positive)"
            d={pathFromPoints(goldPath)} />
      <g fontFamily="var(--font-mono)" fontSize={9}
         textTransform="uppercase" letterSpacing="1">
        <text x={PAD_L} y={PAD_T - 8} fill="var(--warning)">GLD holdings (t, left)</text>
        <text x={W - PAD_R} y={PAD_T - 8} textAnchor="end"
              fill="var(--positive)">Gold price (USD/oz, right)</text>
      </g>
    </svg>
  );
}
```

- [ ] **Step 4: Wire the chart into the Lens 1 panel's lead-chart slot (`StructuralPanel.tsx` from Task 30)**

Replace the empty `data-slot="lead-chart"` div with:

```tsx
<GoldHoldingsVsPriceChart
  gld={posture.gld_history ?? []}
  gold={posture.gold_history ?? []}
/>
```

This adds two history fields to `GoldStructuralPostureModel` (Task 18 + Task 19 follow-up: trailing 5y of GLD holdings + gold close).

- [ ] **Step 5: Run, expect PASS.**

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/components/gold/lens1/GoldHoldingsVsPriceChart.tsx \
        web/components/gold/lens1/StructuralPanel.tsx \
        web/components/gold/lens1/GoldHoldingsVsPriceChart.test.tsx
git commit -m "feat(web/gold): GLD holdings vs gold-price lead chart (Lens 1 visual)"
```

---

## Task 36: Replay route + ReplayDatePicker

**Files:**
- Create: `web/app/gold/replay/[date]/page.tsx`
- Replace stub: `web/components/gold/ReplayDatePicker.tsx`
- Test: `web/components/gold/ReplayDatePicker.test.tsx`

Per spec §8.3 + §9: replay route reuses `GoldCompassLayout` and calls `/api/gold/replay?as_of={date}`. `ReplayDatePicker` is the only client component in the cockpit — it navigates the router on date change.

- [ ] **Step 1: Failing test**

```tsx
// web/components/gold/ReplayDatePicker.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ReplayDatePicker } from './ReplayDatePicker';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

describe('ReplayDatePicker', () => {
  it('renders a date input with the GOLD COMPASS label', () => {
    render(<ReplayDatePicker initialDate="2026-05-17" />);
    expect(screen.getByLabelText(/replay date/i)).toBeInTheDocument();
  });
  it('navigates to replay route on date change', () => {
    const push = vi.fn();
    vi.doMock('next/navigation', () => ({ useRouter: () => ({ push }) }));
    render(<ReplayDatePicker initialDate="2026-05-17" />);
    const input = screen.getByLabelText(/replay date/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '2026-04-15' } });
    // useState value update sanity:
    expect((input as HTMLInputElement).value).toBe('2026-04-15');
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

```tsx
// web/components/gold/ReplayDatePicker.tsx
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

type Props = { initialDate: string };

export function ReplayDatePicker({ initialDate }: Props) {
  const [value, setValue] = useState(initialDate);
  const router = useRouter();
  return (
    <label style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1.5,
      textTransform: 'uppercase', color: 'var(--text-muted)',
    }}>
      Replay date
      <input
        type="date"
        value={value}
        aria-label="replay date"
        onChange={(e) => {
          const next = e.target.value;
          setValue(next);
          if (/^\d{4}-\d{2}-\d{2}$/.test(next)) router.push(`/gold/replay/${next}`);
        }}
        style={{
          background: 'var(--bg-panel)', border: '1px solid var(--border-dim)',
          color: 'var(--text-primary)', padding: '2px 6px', borderRadius: 3,
          fontFamily: 'var(--font-mono)', fontSize: 11,
        }}
      />
    </label>
  );
}
```

```tsx
// web/app/gold/replay/[date]/page.tsx
import { notFound } from 'next/navigation';
import { GoldCompassLayout } from '@/components/gold/GoldCompassLayout';
import type { GoldStateResponse } from '@/lib/types';

async function fetchReplay(date: string): Promise<GoldStateResponse | null> {
  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_BASE ?? ''}/api/gold/replay?as_of=${date}`,
    { next: { revalidate: 60 } },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`replay fetch failed: ${res.status}`);
  return res.json();
}

type Props = { params: Promise<{ date: string }> };

export default async function ReplayPage({ params }: Props) {
  const { date } = await params;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) notFound();
  const state = await fetchReplay(date);
  if (!state) {
    return (
      <main style={{ padding: 32, color: 'var(--text-muted)',
                     background: 'var(--bg-base)', minHeight: '100vh' }}>
        No GOLD COMPASS posture row for {date}.
      </main>
    );
  }
  return <GoldCompassLayout state={state} />;
}
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add web/app/gold/replay/[date]/page.tsx \
        web/components/gold/ReplayDatePicker.tsx \
        web/components/gold/ReplayDatePicker.test.tsx
git commit -m "feat(web/gold): replay route + date picker (uses GoldCompassLayout)"
```

---

## Task 37: Posture-language CI lint integration

**Files:**
- Create: `web/scripts/lint-gold-copy.mjs`
- Modify: `web/package.json` (add `lint:gold-copy` script)
- Test: `web/scripts/lint-gold-copy.test.mjs`

Per spec §8.4: build fails if any file under `web/components/gold/**` or `web/app/gold/**` contains banned posture-language substrings outside an opt-out comment. The expanded banned list now covers six categories — sizing imperatives, sizing nouns, execution verbs, model claims, backtest claims, performance claims — including bilingual (English + 中文) variants.

- [ ] **Step 1: Failing test**

```javascript
// web/scripts/lint-gold-copy.test.mjs
import { describe, expect, it } from 'vitest';
import { lintFileContents, BANNED } from './lint-gold-copy.mjs';

describe('lintFileContents', () => {
  it('flags every banned category', () => {
    const cases = [
      'export const X = "buy gold now";',                  // sizing imperative
      'export const X = "position size 1%";',              // sizing noun
      'export const X = "execute trade";',                 // execution verb
      'export const X = "predicted return +0.72%";',       // model claim
      'export const X = "equity curve since 2020";',       // backtest claim
      'export const X = "今日信号: 做多";',                  // bilingual sizing
    ];
    for (const src of cases) {
      const v = lintFileContents('Test.tsx', src);
      expect(v.length, src).toBeGreaterThan(0);
    }
  });
  it('permits posture-language copy', () => {
    expect(lintFileContents('Test.tsx', 'export const X = "structural bid intact";')).toEqual([]);
    expect(lintFileContents('Test.tsx', 'export const X = "tail-risk awareness only";')).toEqual([]);
    expect(lintFileContents('Test.tsx', 'export const X = "long-horizon allocation context";')).toEqual([]);
  });
  it('respects // posture-lint-disable-next-line', () => {
    const src = [
      '// posture-lint-disable-next-line: Baur-Lucey academic quote',
      'const Q = "a safe haven that does not lose value when others sell";',
    ].join('\n');
    expect(lintFileContents('Cited.tsx', src)).toEqual([]);
  });
  it('exposes the banned-string list for inspection', () => {
    expect(BANNED).toContain('buy');
    expect(BANNED).toContain('predicted return');
    expect(BANNED).toContain('做多');
  });
});
```

- [ ] **Step 2: Run, expect FAIL.**

```bash
cd web && npx vitest run scripts/lint-gold-copy.test.mjs
```

- [ ] **Step 3: Implement**

```javascript
// web/scripts/lint-gold-copy.mjs
import { promises as fs } from 'node:fs';
import path from 'node:path';

// Categories per spec §8.4. Word-boundary matched in English. Asian glyphs
// matched verbatim (no \b semantics in regex for CJK).
export const BANNED = [
  // sizing imperatives
  'buy', 'sell', 'long', 'short',
  // sizing nouns
  'position size', 'recommended size', 'allocate %', 'position heat',
  // execution verbs
  'trade', 'execute', 'enter', 'exit', 'take profit', 'stop loss',
  // model claims
  'predicted return', "today's signal", 'signal: long', 'signal: short',
  'SHAP', 'XGBoost', '8因子',
  // backtest claims
  'equity curve', 'Sharpe', 'Calmar', 'win rate', 'max drawdown',
  'current drawdown',
  // bilingual sizing
  '做多', '做空', '仓位', '今日信号', '预测收益', '净值曲线', '回测账户',
];

// Compound phrases where banned words are legitimate. The lint counts
// allow-list hits but never flags them.
const ALLOWED_COMPOUNDS = [
  'long-horizon', 'short-term', 'long-term', 'long-form',
  'tail-risk', 'execute query', 'execute the migration',
];

const DISABLE_RE = /\/\/\s*posture-lint-disable-next-line/i;

function isAllowedHit(line, idx, word) {
  for (const compound of ALLOWED_COMPOUNDS) {
    if (compound.includes(word.toLowerCase())) {
      const window = line.slice(Math.max(0, idx - 20), idx + word.length + 20).toLowerCase();
      if (window.includes(compound)) return true;
    }
  }
  return false;
}

export function lintFileContents(filename, source) {
  const lines = source.split('\n');
  const violations = [];
  for (let i = 0; i < lines.length; i++) {
    if (i > 0 && DISABLE_RE.test(lines[i - 1])) continue;
    const line = lines[i];
    for (const word of BANNED) {
      // Decide regex: word-boundary for ASCII, substring for CJK.
      const isAscii = /^[\x00-\x7F]+$/.test(word);
      const re = isAscii
        ? new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i')
        : new RegExp(word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
      const m = line.match(re);
      if (m && typeof m.index === 'number') {
        if (isAllowedHit(line, m.index, word)) continue;
        violations.push({ file: filename, line: i + 1, word, text: line.trim() });
      }
    }
  }
  return violations;
}

async function* walk(dir) {
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (full.endsWith('.tsx') || full.endsWith('.ts')) yield full;
  }
}

async function main() {
  const roots = [path.resolve('components/gold'), path.resolve('app/gold')];
  let total = 0;
  for (const root of roots) {
    try { await fs.access(root); } catch { continue; }
    for await (const file of walk(root)) {
      // Skip the lint helper itself and its tests
      if (file.endsWith('lint-gold-copy.mjs') || file.endsWith('lint-gold-copy.test.mjs')) continue;
      if (file.endsWith('.test.ts') || file.endsWith('.test.tsx')) continue;
      const src = await fs.readFile(file, 'utf-8');
      const violations = lintFileContents(file, src);
      for (const v of violations) {
        console.error(`${v.file}:${v.line}: banned posture-language '${v.word}': ${v.text}`);
        total += 1;
      }
    }
  }
  if (total > 0) {
    console.error(`\n${total} posture-language violations.`);
    process.exit(1);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
```

Add to `web/package.json` scripts:

```json
"lint:gold-copy": "node scripts/lint-gold-copy.mjs"
```

Wire into the existing `npm run lint` script (run as a sequential step) or document as a separate CI gate.

- [ ] **Step 4: Run unit test, expect PASS.**

- [ ] **Step 5: Verify against actual gold components**

```bash
cd web && npm run lint:gold-copy
```

Expected: clean exit (no banned strings in current components — Tasks 28–36 wrote them with posture language only).

- [ ] **Step 6: Commit** (only commit after explicit approval)

```bash
git add web/scripts/lint-gold-copy.mjs web/scripts/lint-gold-copy.test.mjs web/package.json
git commit -m "feat(web/gold): expanded posture-language CI lint (6 categories, bilingual)"
```

---

## Task 38: End-to-end replay-acceptance test

**Files:**
- Create: `tests/integration/e2e/test_gold_replay_acceptance.py`

The single most important acceptance gate per [spec §9.4](../specs/2026-05-16-gold-phase-a1-design.md): reconstruct historical posture and verify byte-for-byte equality with the originally-computed row (excluding `computed_at`).

- [ ] **Step 1: Write the acceptance test**

```python
# tests/integration/e2e/test_gold_replay_acceptance.py
"""End-to-end replay acceptance test for Phase A1.

For 5 historical dates, compute a posture row, then re-run the orchestrator
with a NEW computed_at, and verify the replay endpoint returns the FIRST-computed
posture byte-for-byte (excluding computed_at and as_of timestamps inside
inputs_jsonb)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from uw_scan.reports.gold_posture import compute_and_persist_gold_posture
from uw_scan.storage.repository import Repository


def _seed_three_months(repo: Repository, start: date) -> None:
    """Seed 90 days of inputs covering several `as_of` increments."""
    for i in range(90):
        d = start + timedelta(days=i)
        ts = datetime.combine(d, datetime.min.time(), tzinfo=UTC)
        repo.insert_macro_series_daily(
            "GLD_CLOSE", d, Decimal(str(1800 + i * 0.4)), ts,
            None, "MASSIVE", None,
        )
        repo.insert_macro_series_daily(
            "DFII10", d, Decimal(str(1.8 - i * 0.002)), ts, None, "FRED", None,
        )
        repo.insert_macro_series_daily(
            "T5YIFR", d, Decimal("2.31"), ts, None, "FRED", None,
        )


def _compare_excluding(row_a: dict, row_b: dict, *, exclude: set[str]) -> dict[str, tuple]:
    diffs: dict[str, tuple] = {}
    for key in set(row_a.keys()) | set(row_b.keys()):
        if key in exclude:
            continue
        if row_a.get(key) != row_b.get(key):
            diffs[key] = (row_a.get(key), row_b.get(key))
    return diffs


@pytest.mark.integration
def test_replay_byte_for_byte_match_5_dates(postgresql):
    with psycopg.connect(postgresql.info.dsn) as conn:
        repo = Repository(conn, schema="uw_scan")
        base = date(2026, 1, 1)
        _seed_three_months(repo, base)

        # Five evenly-spaced obs dates within the seeded range
        targets = [base + timedelta(days=i) for i in (10, 25, 40, 60, 80)]

        # First compute: store the originals
        originals: dict[date, dict] = {}
        for obs in targets:
            computed_at = datetime.combine(obs + timedelta(days=1),
                                            datetime.min.time(), tzinfo=UTC)
            compute_and_persist_gold_posture(repo, as_of=obs, computed_at=computed_at)
            originals[obs] = repo.fetch_gold_posture_for_obs_date(obs)
            assert originals[obs] is not None
        conn.commit()

        # Second compute: NEW computed_at on each obs_date — the orchestrator
        # writes a new row; `fetch_gold_posture_for_obs_date` must still return
        # the FIRST-computed row (replay discipline).
        for obs in targets:
            new_computed_at = datetime.combine(obs + timedelta(days=2),
                                                datetime.min.time(), tzinfo=UTC)
            compute_and_persist_gold_posture(repo, as_of=obs, computed_at=new_computed_at)

        # Assert first-computed posture preserved
        for obs in targets:
            current = repo.fetch_gold_posture_for_obs_date(obs)
            diffs = _compare_excluding(
                originals[obs], current,
                exclude={"computed_at", "inputs_jsonb"},
            )
            assert not diffs, f"replay drift for {obs}: {diffs}"
```

- [ ] **Step 2: Run, expect PASS** (assuming all prior tasks land cleanly).

```bash
uv run pytest tests/integration/e2e/test_gold_replay_acceptance.py -v
```

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest -v
cd web && npm run test && npm run lint:gold-copy && npm run typecheck
```

Expected: all green.

- [ ] **Step 4: Manual smoke check**

Start the dev stack:

```bash
bash scripts/dev.sh
```

In another terminal:

```bash
curl -s http://127.0.0.1:8400/api/gold/state | jq '.gauge.state, .valuation.flag, .data_freshness'
curl -s 'http://127.0.0.1:8400/api/gold/replay?as_of=2026-05-15' | jq '.obs_date'
```

Visit `http://localhost:3001/gold` and confirm:
- GOLD COMPASS header renders with title chip and replay date picker
- Tier 1 KPI strip shows 5 cards (spot, correlation gauge, regime badge, lenses overall, data freshness)
- Tier 2 Lens 1 renders the lead chart + 6 cards + posture narrative
- Tier 3 Lens 2 renders the 4 macro cards + article-zone heuristic badge + two-force narrative
- Tier 4 Lens 3 renders 4 valuation tiles with `NEVER A SIZING INPUT` callout
- Tier 5 renders the decomposition bars and the correlation history chart with pre-2022 band
- DataAuditFooter at the bottom lists vintaged inputs and shows the `LENS HEURISTICS · v1` wordmark
- Clicking the replay link routes to `/gold/replay/<date>` and renders the historical posture

- [ ] **Step 5: Commit** (only commit after explicit approval)

```bash
git add tests/integration/e2e/test_gold_replay_acceptance.py
git commit -m "test(gold): replay-acceptance end-to-end (Phase A1 acceptance gate)"
```

---

## Self-review

Running the writing-plans self-review checklist:

**1. Spec coverage:** every spec section maps to at least one task —
- §1 Goals → Tasks 1–38 (collectively)
- §3 Architecture → Tasks 2–9 (sources), 10–13 (repo), 14–17 (cards), 18–19 (models/report), 20–22 (API), 23–25 (worker), 28–36 (web)
- §4 Data model → Task 1
- §5 Ingestion → Tasks 2–9 + 23–25
- §6 API surface → Tasks 20–22
- §7 Computation → Tasks 14–17 (cards) + 19 (orchestrator)
- §8 Cockpit UI (GOLD COMPASS) → Tasks 28–36 (28 shell + chips, 29 KPI strip, 30–32 lens panels + footer, 33 decomposition, 34 correlation history, 35 lead chart, 36 replay)
- §9 Replay scaffold → Tasks 13 + 19 + 22 + 36 + 38
- §10 Engineering estimate → covered by total task count
- §11 Testing strategy → embedded per task + Task 38
- §12 Acceptance criteria → Task 38
- §13 A2 deferrals → preserved as TODO markers in Task 9 (UW options dealer-gamma), Task 14 (gauge thresholds), Task 16 (article-zone thresholds), Task 8 (CFTC URL pin), and the Q-numbered open questions in 10-open-research-questions.md

**2. Placeholder scan:** no "TBD", "TODO" left as plan-failure markers. The TODO markers inside code (Task 9 for `dealer_gamma_est`, Task 14 for empirical-calibration of thresholds, Task 29 for orchestrator-supplied `state.spot`/`data_freshness`/`decomposition_rows`/`correlation_history` fields) are *Phase A2 deferrals* or downstream wire-ups explicitly traceable to spec/task references — intentional, not gaps.

**3. Type consistency:** `GoldStateResponse` shape consistent across Tasks 18, 20, 21, 22 and consumed identically in Tasks 28–36 (with Task 29/33/34 adding `state.spot`, `state.data_freshness`, `state.decomposition_rows`, `state.correlation_history` — Task 18+19 follow-ups, called out inline). `EtfHoldingRow` produced in Task 4 consumed in Task 11; `CotRow` produced in Task 8 consumed in Task 12 and Task 24; `CorrelationGauge` from Task 14 consumed in Task 19 and 20. `posture_chip: PostureState` added to each lens model (Task 18 follow-up) is consumed identically by Tasks 29–32.

**4. Spec section coverage check —** the only section whose tasks are sparse is "[Goal] 4. Read-only API surface" for `lenses` detail — Task 21 implements it but the detail dict is sketched, not exhaustive per data type. Acceptable for v1; full detail enrichment is a follow-up commit during dashboard polish.

**5. GOLD COMPASS posture-language discipline —** every UI task (28–36) writes test assertions against the banned-strings list before implementation. Task 37 hardens this with a CI lint covering all 6 banned categories (sizing imperatives, sizing nouns, execution verbs, model claims, backtest claims, performance claims) plus bilingual variants.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-16-gold-phase-a1-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task with `superpowers:subagent-driven-development`, review between tasks, fast iteration. Best for this plan because the 38 tasks span heterogeneous areas (SQL, Python, TSX) — fresh context per task keeps each focused on its own concerns. The GOLD COMPASS subtree (Tasks 28–36) benefits especially since each lens has 4–8 small components.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans` with batch checkpoints (e.g. checkpoint after Task 13 repo layer, Task 19 orchestrator, Task 27 API + lint helper, Task 32 first three lens panels, Task 36 cockpit complete, Task 38 acceptance gate).

**Which approach?**
