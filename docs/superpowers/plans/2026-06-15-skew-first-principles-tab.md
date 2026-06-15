# Skew First-Principles Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-ticker **Skew** tab that reads a ticker's 25Δ risk-reversal skew against its own historical baseline, explains it with spot-vol correlation ρ, contextualizes it by asset-class + borrow cost, emits a deterministic relative-value read with an **evidence-gated directional lean**, and backs the lean with a Tier-1 markout validation over the ~13-month backfill.

**Architecture:** Mirrors the Volatility-tab seam exactly — persisted raw (already on disk) → pure derivers (`cards/skew_first_principles.py`) → report assembler (`reports/skew_analytics.py`) → thin router (`api/routers/skew.py`) → RSC tab (`SkewTab.tsx`) → client island (`SkewTabClient.tsx`). Two new tables: a markout-ready per-day `skew_analytics_snapshot` and a small `skew_directional_verdicts` store written by the markout job. The directional lean is computed by a pure gated function and can only go non-neutral when a `TRADABLE_*` verdict exists AND the live borrow/earnings gates pass.

**Tech Stack:** Python 3.13 (uv), FastAPI + Pydantic v2, psycopg 3, APScheduler, pandas/numpy; Next.js 16 + React 19 + hand-rolled SVG; pytest + pytest-postgresql, vitest + Playwright.

---

## Pinned facts (verified 2026-06-15 against `option_wizard_local` + UW spec)

These are load-bearing — do not re-derive, do not guess:

1. **RR sign convention is final.** UW `risk_reversal` = *"the difference between the iv of a put and a call with similar absolute deltas"* = `IV(put) − IV(call)`. Positive ⇒ put-skew (SPY `+0.0048`); negative ⇒ call-skew (TSLA `−0.0117`, NVDA `−0.0197`). The persisted `uw_scan.risk_reversal_skew_history.risk_reversal` value is stored as-is with this convention. **No sign flip anywhere.** A unit test guards it.
2. **Core RR series source:** reuse the existing `repo.fetch_matrix_skew_history(ticker=, market_date=, days=)` — it returns `DISTINCT ON (market_date)` front-expiry rows for `delta=25`, ordered ASC. This is the stable single-expiry series for the z-score/percentile baseline.
3. **Term-structure source:** reuse the existing `repo.fetch_matrix_skew_expiry_rows(ticker=, market_date=)` — all expiries for one date, ordered by expiry ASC. Most ticker-dates have 1 expiry (degrade to `flat`); up to 18 exist for some.
4. **Latest RR snapshot:** reuse the existing `repo.fetch_skew_latest(ticker)`.
5. **RV/IV/price + forward returns source:** reuse the existing `repo.fetch_realized_vol_history(ticker, days=)` → columns `market_date, price, implied_volatility, realized_volatility`. `price` is the forward-return anchor.
6. **Borrow source:** reuse the existing `repo.get_uw_positioning(ticker)` → latest dict with `si_fee_rate` (percent; GC≈0.25, universe max≈2.18), `si_days_to_cover`. `next_er_date` is **empty** in this table — do NOT use it for earnings.
7. **Earnings source:** `uw_scan.flow_events.next_earnings_date` (populated for ~90 tickers). A new focused read returns the latest non-null value per ticker.
8. **Borrow threshold default:** `hard_to_borrow` when `si_fee_rate >= 1.0` (%). Flags NOK/JNK/HYG/IGV in the current universe; GC names (SPY/AAPL/TSLA at 0.25) stay `normal`.
9. **Next migration number:** `073`. Highest existing is `072_scanner_candidate_snapshots.sql`.
10. **Local DB has data:** RR history 103 tickers, RV history 104 tickers, through 2026-06-11 — enough for backfill, markout, and the local Playwright e2e.

---

## File structure

**New backend files**
- `src/uw_scan/cards/skew_first_principles.py` — pure derivers (ρ, baseline, classifiers, lean). No I/O.
- `src/uw_scan/storage/skew.py` — `_SkewMixin`: snapshot upsert/read, verdict upsert/read, earnings read.
- `src/uw_scan/storage/migrations/073_skew_tables.sql` — `skew_analytics_snapshot` + `skew_directional_verdicts`.
- `src/uw_scan/models/skew.py` — Pydantic response contract.
- `src/uw_scan/reports/skew_analytics.py` — assembler + snapshot-row builder + persist helper.
- `src/uw_scan/reports/skew_markout.py` — Tier-1 markout harness writing verdicts.
- `src/uw_scan/api/routers/skew.py` — `GET /api/stock/{ticker}/skew`.
- `src/uw_scan/worker/jobs/skew_analytics.py` — `nightly_skew_analytics_rollup` + `skew_analytics_backfill`.

**Modified backend files**
- `src/uw_scan/storage/repository.py` — import + inherit `_SkewMixin`.
- `src/uw_scan/models/__init__.py` — re-export skew models + `__all__`.
- `src/uw_scan/api/server.py` — import + mount `skew.router`.
- `src/uw_scan/worker/scheduler.py` — register the nightly rollup at 18:30 ET.

**New frontend files**
- `web/components/stock/tabs/SkewTab.tsx` (RSC) + `SkewTabClient.tsx` (client island).
- `web/components/stock/panels/SkewPostureTiles.tsx`, `SkewHistoryChart.tsx`, `SkewRhoPanel.tsx`, `SkewTermPanel.tsx`, `SkewClassSpectrum.tsx`, `SkewReadPanel.tsx`.

**Modified frontend files**
- `web/components/stock/TabBar.tsx` — add `["skew","Skew"]`.
- `web/app/stock/[ticker]/[tab]/page.tsx` — import `SkewTab` + add to `REPORT_TABS`.
- `web/lib/api.ts` — `skewAnalysis` method + type + export.
- `web/lib/types.ts` — regenerated via `npm run gen:types`.

**New test files** (placement follows `tests/CLAUDE.md`: api/ worker/ reports/ storage/ subdirs)
- `tests/unit/cards/test_skew_first_principles.py`
- `tests/unit/reports/test_skew_snapshot_row.py`
- `tests/integration/storage/test_skew_storage.py`
- `tests/integration/api/test_skew.py`
- `tests/integration/worker/test_skew_jobs.py`
- `tests/integration/reports/test_skew_markout.py`
- `web/tests/unit/SkewReadPanel.test.tsx`, `web/tests/unit/SkewPostureTiles.test.tsx`
- `web/tests/e2e/skew-tab.spec.ts`

**Test fixtures (verified):** the bare-Repository fixture is **`seeded_db_empty_cards`** (freshly-migrated test DB + 54-ticker watchlist, zero cards; function-scoped TRUNCATE/COPY restore) from `tests/integration/conftest.py`. The FastAPI **`client`** fixture is in `tests/integration/api/conftest.py` (overrides `get_repo`/`get_settings` at the test DB; needs no seeding of its own). There is **no** `repo` fixture — each new integration test file defines a one-line alias `@pytest.fixture def repo(seeded_db_empty_cards): return seeded_db_empty_cards` so the test bodies below read naturally. Seed via `repo`/`seeded_db_empty_cards` (committed), read via `client`.

---

## Canonical names (used identically across all tasks)

Deriver functions (`cards/skew_first_principles.py`):
- `compute_spot_vol_rho(rows: list[dict], *, window: int = 63) -> float | None`
- `compute_skew_baseline(rr_series: list[float | None], *, z_window: int = 180, pct_window: int = 252) -> dict` → `{"z","pct","latest","n"}`
- `classify_deviation(z, pct, *, z_hi=1.5, pct_hi=85.0, pct_lo=15.0) -> str` → `RICH|CHEAP|NORMAL`
- `classify_skew_term(front_rr, back_rr, *, eps=0.005) -> str` → `front_steep|back_steep|flat`
- `classify_drive(price_trend, rho, *, eps=1e-9) -> str` → `PANIC|CHASE|STRUCTURAL`
- `classify_market_regime(spy_rv_series: list[dict]) -> str` → `HIGH_VOL|LOW_VOL|UNKNOWN`
- `asset_class_baseline(ticker: str, *, sector: str | None = None) -> dict` → `{"asset_class","expected_sign"}`
- `borrow_flag(fee_rate, days_to_cover, *, fee_htb_pct=1.0) -> str` → `hard_to_borrow|normal|unknown`
- `resolve_directional_lean(*, deviation_class, drive_class, asset_class, regime, borrow_flag, earnings_gate, verdict) -> dict` → `{"lean","confidence","basis","express"}` with `lean ∈ {BULLISH_TILT,BEARISH_TILT,NEUTRAL}`
- `build_read(*, tail, rho, rho_confirms, drive_class, deviation_class, asset_class, class_expected_sign, borrow_flag, earnings_gate, directional_lean) -> dict`

Snapshot column dict keys (== `skew_analytics_snapshot` columns): `ticker, market_date, basis, spot, rr_25d, skew_25d, rr_z_180d, rr_pct_252d, deviation_class, skew_term_class, front_rr, back_rr, rho_spotvol_63d, rho_spotvol_21d, rho_sign, drive_class, asset_class, class_expected_sign, borrow_flag, borrow_fee_rate, days_to_cover, earnings_gate, regime, directional_lean, lean_confidence, lean_basis, read_summary, read_json`.

Verdict keys (== `skew_directional_verdicts` columns): `asset_class, deviation_class, drive_class, regime, verdict, confidence, forward_sep, n, borrow_clean, survives_gate, as_of`. `verdict ∈ {TRADABLE_BULL,TRADABLE_BEAR,NONE}`.

---

# Milestone A — Schema, storage, models

### Task A1: Migration 073 — two tables

**Files:**
- Create: `src/uw_scan/storage/migrations/073_skew_tables.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 073_skew_tables.sql — Skew First-Principles tab.
-- skew_analytics_snapshot: one markout-ready row per (ticker, market_date, basis).
-- skew_directional_verdicts: per-bucket markout conclusions that unlock a
-- non-neutral directional lean. Both idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.skew_analytics_snapshot (
  ticker             TEXT NOT NULL,
  market_date        DATE NOT NULL,
  basis              TEXT NOT NULL DEFAULT 'eod',  -- 'eod' (canonical daily)
  spot               NUMERIC,                      -- forward-return anchor (markout-ready)
  rr_25d             NUMERIC,                      -- IV(put)-IV(call); + = put-skew
  skew_25d           NUMERIC,                      -- alias of rr_25d for UI parity
  rr_z_180d          NUMERIC,                      -- deviation vs own 180d baseline
  rr_pct_252d        NUMERIC,                      -- percentile vs own 252d baseline (0-100)
  deviation_class    TEXT,                         -- RICH | CHEAP | NORMAL
  skew_term_class    TEXT,                         -- front_steep | back_steep | flat
  front_rr           NUMERIC,
  back_rr            NUMERIC,
  rho_spotvol_63d    NUMERIC,
  rho_spotvol_21d    NUMERIC,
  rho_sign           INTEGER,                      -- -1 | 0 | 1
  drive_class        TEXT,                         -- PANIC | CHASE | STRUCTURAL
  asset_class        TEXT,                         -- index_macro | sector_etf | credit | single_name
  class_expected_sign TEXT,                        -- put_skew | call_skew | mixed
  borrow_flag        TEXT,                         -- hard_to_borrow | normal | unknown
  borrow_fee_rate    NUMERIC,
  days_to_cover      NUMERIC,
  earnings_gate      TEXT,                         -- block | pass | unknown
  regime             TEXT,                         -- HIGH_VOL | LOW_VOL | UNKNOWN (market)
  directional_lean   TEXT,                         -- BULLISH_TILT | BEARISH_TILT | NEUTRAL
  lean_confidence    TEXT,                         -- low | med | high
  lean_basis         TEXT,                         -- why the lean is what it is
  read_summary       TEXT,
  read_json          JSONB,
  inserted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, basis)
);

CREATE INDEX IF NOT EXISTS ix_skew_snap_ticker_date
  ON uw_scan.skew_analytics_snapshot (ticker, market_date DESC);

COMMENT ON COLUMN uw_scan.skew_analytics_snapshot.rr_25d
  IS 'UW risk_reversal = IV(25d put) - IV(25d call); positive = put-skew. No sign transform.';
COMMENT ON COLUMN uw_scan.skew_analytics_snapshot.spot
  IS 'Close anchor for forward-return join (markout-ready). Forwards are NOT stored.';

CREATE TABLE IF NOT EXISTS uw_scan.skew_directional_verdicts (
  asset_class     TEXT NOT NULL,
  deviation_class TEXT NOT NULL,
  drive_class     TEXT NOT NULL,
  regime          TEXT NOT NULL,
  verdict         TEXT NOT NULL,    -- TRADABLE_BULL | TRADABLE_BEAR | NONE
  confidence      TEXT,             -- low | med | high
  forward_sep     NUMERIC,          -- mean T+20 forward return on borrow-clean subset
  n               INTEGER,
  borrow_clean    BOOLEAN,
  survives_gate   BOOLEAN,
  as_of           DATE,
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_class, deviation_class, drive_class, regime)
);

COMMENT ON TABLE uw_scan.skew_directional_verdicts
  IS 'Per-bucket markout conclusions. Only a TRADABLE_* row that is borrow_clean AND survives_gate unlocks a non-neutral directional lean.';

-- Supports fetch_latest_next_earnings_date (ORDER BY inserted_at DESC over a
-- ~1M-row flow_events table). Partial: only rows carrying an earnings date.
CREATE INDEX IF NOT EXISTS ix_flow_events_ticker_earnings_inserted
  ON uw_scan.flow_events (ticker, inserted_at DESC)
  WHERE next_earnings_date IS NOT NULL;
```

- [ ] **Step 2: Apply migration twice (idempotency)**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: both runs succeed; second run is a no-op (no errors).

- [ ] **Step 3: Verify tables exist**

Run: `psql -h 127.0.0.1 -p 5432 -U chenxi -d option_wizard_local -c "\d uw_scan.skew_analytics_snapshot" -c "\d uw_scan.skew_directional_verdicts"`
Expected: both tables print their columns; PKs as defined.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/migrations/073_skew_tables.sql
git commit -m "feat(skew): migration 073 — skew_analytics_snapshot + directional_verdicts"
```

---

### Task A2: `_SkewMixin` storage module

**Files:**
- Create: `src/uw_scan/storage/skew.py`
- Test: `tests/integration/storage/test_skew_storage.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""Integration tests for _SkewMixin (pytest-postgresql)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture
def repo(seeded_db_empty_cards):
    """Alias: the canonical bare-Repository fixture (see tests/integration/conftest.py)."""
    return seeded_db_empty_cards


def _snap(ticker: str, d: date, **over) -> dict:
    base = {
        "ticker": ticker, "market_date": d, "basis": "eod",
        "spot": Decimal("100"), "rr_25d": Decimal("0.01"), "skew_25d": Decimal("0.01"),
        "rr_z_180d": Decimal("1.7"), "rr_pct_252d": Decimal("90"),
        "deviation_class": "RICH", "skew_term_class": "flat",
        "front_rr": Decimal("0.01"), "back_rr": None,
        "rho_spotvol_63d": Decimal("-0.4"), "rho_spotvol_21d": Decimal("-0.5"), "rho_sign": -1,
        "drive_class": "PANIC", "asset_class": "single_name", "class_expected_sign": "mixed",
        "borrow_flag": "normal", "borrow_fee_rate": Decimal("0.25"), "days_to_cover": Decimal("1.5"),
        "earnings_gate": "pass", "regime": "HIGH_VOL",
        "directional_lean": "NEUTRAL", "lean_confidence": "low", "lean_basis": "no verdict",
        "read_summary": "test", "read_json": {"k": "v"},
    }
    base.update(over)
    return base


def test_upsert_snapshot_is_idempotent(repo):
    d = date(2026, 6, 1)
    assert repo.upsert_skew_analytics_snapshots([_snap("AAPL", d)]) == 1
    repo.upsert_skew_analytics_snapshots([_snap("AAPL", d, rr_25d=Decimal("0.02"))])
    repo.conn.commit()
    latest = repo.get_skew_analytics_latest("AAPL")
    assert latest is not None
    assert latest["rr_25d"] == Decimal("0.02")  # updated, not duplicated


def test_history_returns_ascending(repo):
    repo.upsert_skew_analytics_snapshots(
        [_snap("MSFT", date(2026, 5, 1)), _snap("MSFT", date(2026, 5, 2))]
    )
    repo.conn.commit()
    rows = repo.fetch_skew_analytics_history("MSFT", days=400)
    assert [r["market_date"] for r in rows] == [date(2026, 5, 1), date(2026, 5, 2)]


def test_verdict_roundtrip(repo):
    repo.upsert_skew_directional_verdict(
        asset_class="single_name", deviation_class="RICH", drive_class="PANIC",
        regime="HIGH_VOL", verdict="TRADABLE_BEAR", confidence="med",
        forward_sep=Decimal("-0.021"), n=42, borrow_clean=True, survives_gate=True,
        as_of=date(2026, 6, 1),
    )
    repo.conn.commit()
    v = repo.get_skew_directional_verdict(
        asset_class="single_name", deviation_class="RICH",
        drive_class="PANIC", regime="HIGH_VOL",
    )
    assert v is not None and v["verdict"] == "TRADABLE_BEAR" and v["n"] == 42
    assert repo.get_skew_directional_verdict(
        asset_class="index_macro", deviation_class="RICH",
        drive_class="PANIC", regime="HIGH_VOL",
    ) is None


def test_latest_next_earnings_date(repo):
    # flow_events requires run_id (FK -> scan_runs) + alert_id (NOT NULL),
    # UNIQUE(run_id, alert_id). Latest non-null next_earnings_date wins.
    run_id = repo.insert_scan_run(ticker="NFLX")
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date, inserted_at) "
            "VALUES (%s, 'a1', 'NFLX', %s, now() - interval '2 days'), "
            "       (%s, 'a2', 'NFLX', %s, now())",
            (run_id, date(2026, 7, 1), run_id, date(2026, 7, 15)),
        )
    repo.conn.commit()
    assert repo.fetch_latest_next_earnings_date("NFLX") == date(2026, 7, 15)
    assert repo.fetch_latest_next_earnings_date("ZZZZ") is None


def test_fetch_watchlist_sector(repo):
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist (ticker, sector) VALUES ('ZZTOP', 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
    repo.conn.commit()
    assert repo.fetch_watchlist_sector("ZZTOP") == "Macro"
    assert repo.fetch_watchlist_sector("NOPE") is None
```

> The `repo` fixture aliases `seeded_db_empty_cards` (above). If `flow_events` requires non-null columns beyond `ticker`/`next_earnings_date`, inspect `migrations/001_s1_core_tables.sql` and add the minimal required columns to the INSERT — do not invent values.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/storage/test_skew_storage.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_skew_analytics_snapshots'`.

- [ ] **Step 3: Write `_SkewMixin`**

```python
"""Skew First-Principles persistence (snapshots + directional verdicts)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

_SNAP_COLUMNS: tuple[str, ...] = (
    "spot", "rr_25d", "skew_25d", "rr_z_180d", "rr_pct_252d", "deviation_class",
    "skew_term_class", "front_rr", "back_rr", "rho_spotvol_63d", "rho_spotvol_21d",
    "rho_sign", "drive_class", "asset_class", "class_expected_sign", "borrow_flag",
    "borrow_fee_rate", "days_to_cover", "earnings_gate", "regime", "directional_lean",
    "lean_confidence", "lean_basis", "read_summary", "read_json",
)


class _SkewMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_skew_analytics_snapshots(self, rows: Iterable[dict[str, Any]]) -> int:
        cols = ", ".join(_SNAP_COLUMNS)
        placeholders = ", ".join(["%s"] * len(_SNAP_COLUMNS))
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in _SNAP_COLUMNS)
        sql = (
            f"INSERT INTO {self._schema}.skew_analytics_snapshot "
            f"(ticker, market_date, basis, {cols}, inserted_at) "
            f"VALUES (%s, %s, %s, {placeholders}, now()) "
            "ON CONFLICT (ticker, market_date, basis) DO UPDATE SET "
            f"{updates}, inserted_at=now()"
        )
        params: list[tuple[Any, ...]] = []
        for r in rows:
            head = (r["ticker"], r["market_date"], r.get("basis", "eod"))
            tail = tuple(
                Jsonb(r.get(c)) if c == "read_json" and r.get(c) is not None
                else r.get(c)
                for c in _SNAP_COLUMNS
            )
            params.append(head + tail)
        if not params:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def get_skew_analytics_latest(self, ticker: str) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.skew_analytics_snapshot "
            "WHERE ticker = %s AND basis = 'eod' ORDER BY market_date DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_skew_analytics_history(
        self, ticker: str, *, days: int = 400
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT * FROM {self._schema}.skew_analytics_snapshot "
            "WHERE ticker = %s AND basis = 'eod' "
            "  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def upsert_skew_directional_verdict(
        self,
        *,
        asset_class: str,
        deviation_class: str,
        drive_class: str,
        regime: str,
        verdict: str,
        confidence: str | None,
        forward_sep: Any,
        n: int,
        borrow_clean: bool,
        survives_gate: bool,
        as_of: _date,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.skew_directional_verdicts "
            "(asset_class, deviation_class, drive_class, regime, verdict, confidence, "
            " forward_sep, n, borrow_clean, survives_gate, as_of, inserted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (asset_class, deviation_class, drive_class, regime) DO UPDATE SET "
            "verdict=EXCLUDED.verdict, confidence=EXCLUDED.confidence, "
            "forward_sep=EXCLUDED.forward_sep, n=EXCLUDED.n, "
            "borrow_clean=EXCLUDED.borrow_clean, survives_gate=EXCLUDED.survives_gate, "
            "as_of=EXCLUDED.as_of, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (asset_class, deviation_class, drive_class, regime, verdict, confidence,
                 forward_sep, n, borrow_clean, survives_gate, as_of),
            )

    def get_skew_directional_verdict(
        self, *, asset_class: str, deviation_class: str, drive_class: str, regime: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.skew_directional_verdicts "
            "WHERE asset_class=%s AND deviation_class=%s AND drive_class=%s AND regime=%s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (asset_class, deviation_class, drive_class, regime))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))

    def fetch_latest_next_earnings_date(self, ticker: str) -> _date | None:
        sql = (
            f"SELECT next_earnings_date FROM {self._schema}.flow_events "
            "WHERE ticker = %s AND next_earnings_date IS NOT NULL "
            "ORDER BY inserted_at DESC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            return row[0] if row else None

    def fetch_watchlist_sector(self, ticker: str) -> str | None:
        """Active watchlist sector tag (20-tag taxonomy) for asset-class baseline.
        Real values incl. 'Macro' | 'Credit' | 'Sector-ETF' | 'M7' | 'SaaS' | ..."""
        sql = (
            f"SELECT sector FROM {self._schema}.watchlist "
            "WHERE ticker = %s AND removed_at IS NULL LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            row = cur.fetchone()
            return row[0] if row else None
```

- [ ] **Step 4: Wire `_SkewMixin` into `Repository`**

In `src/uw_scan/storage/repository.py`, add the import next to the other domain mixin imports (alphabetical-ish, after `from .scan_runs import _ScanRunsMixin`):

```python
from .skew import _SkewMixin
```

And add `_SkewMixin,` to the `class Repository(...)` inheritance list, immediately before `_TradeInsightsAiMixin,`:

```python
    _ScanRunsMixin,
    _SkewMixin,
    _TradeInsightsAiMixin,
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/integration/storage/test_skew_storage.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/skew.py src/uw_scan/storage/repository.py tests/integration/storage/test_skew_storage.py
git commit -m "feat(skew): _SkewMixin storage — snapshots, verdicts, earnings read"
```

---

# Milestone B — Pure derivers

### Task B1: ρ, baseline, deviation, term, regime

**Files:**
- Create: `src/uw_scan/cards/skew_first_principles.py`
- Test: `tests/unit/cards/test_skew_first_principles.py`

- [ ] **Step 1: Write the failing unit tests (part 1)**

```python
"""Unit tests for skew first-principles derivers."""

from __future__ import annotations

import math

import pytest

from uw_scan.cards import skew_first_principles as sk


def test_rho_negative_when_vol_rises_as_price_falls():
    # price down, IV up each day -> strong negative spot-vol corr
    rows = []
    p, iv = 100.0, 0.20
    for _ in range(70):
        p *= 0.99
        iv += 0.005
        rows.append({"price": p, "implied_volatility": iv})
    rho = sk.compute_spot_vol_rho(rows, window=63)
    assert rho is not None and rho < -0.9


def test_rho_none_when_insufficient_history():
    rows = [{"price": 100, "implied_volatility": 0.2}] * 10
    assert sk.compute_spot_vol_rho(rows, window=63) is None


def test_baseline_z_and_percentile():
    series = [0.0] * 200 + [10.0]  # last point a huge outlier
    out = sk.compute_skew_baseline(series, z_window=180, pct_window=252)
    assert out["z"] is not None and out["z"] > 3
    assert out["pct"] is not None and out["pct"] > 99


def test_baseline_cold_start_returns_none_z():
    out = sk.compute_skew_baseline([0.1, 0.2, 0.3], z_window=180, pct_window=252)
    assert out["z"] is None and out["pct"] is None


@pytest.mark.parametrize(
    "z,pct,expected",
    [
        (2.0, 90, "RICH"),
        (-2.0, 5, "CHEAP"),
        (0.0, 50, "NORMAL"),
        (None, 88, "RICH"),
        (None, 12, "CHEAP"),
        (None, None, "NORMAL"),
    ],
)
def test_classify_deviation(z, pct, expected):
    assert sk.classify_deviation(z, pct) == expected


def test_classify_skew_term():
    assert sk.classify_skew_term(0.02, 0.01) == "front_steep"
    assert sk.classify_skew_term(0.01, 0.02) == "back_steep"
    assert sk.classify_skew_term(0.010, 0.010) == "flat"
    assert sk.classify_skew_term(0.01, None) == "flat"


def test_classify_drive():
    assert sk.classify_drive(price_trend=-0.1, rho=-0.5) == "PANIC"
    assert sk.classify_drive(price_trend=0.1, rho=0.5) == "CHASE"
    assert sk.classify_drive(price_trend=0.1, rho=-0.5) == "STRUCTURAL"
    assert sk.classify_drive(price_trend=None, rho=-0.5) == "STRUCTURAL"


def test_classify_market_regime():
    calm = [{"market_date": i, "price": 100 + (i % 2)} for i in range(260)]
    assert sk.classify_market_regime(calm) in {"LOW_VOL", "HIGH_VOL", "UNKNOWN"}
    assert sk.classify_market_regime([]) == "UNKNOWN"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -v`
Expected: FAIL — module `skew_first_principles` does not exist.

- [ ] **Step 3: Implement part 1**

```python
"""Pure first-principles skew derivers. No DB, no IO — dicts/lists in, scalars out.

Sign convention (UW): risk_reversal = IV(25d put) - IV(25d call).
Positive => put-skew; negative => call-skew. Stored as-is, never flipped.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def compute_spot_vol_rho(rows: list[dict], *, window: int = 63) -> float | None:
    """Pearson corr of daily delta-log(price) vs delta(IV) over the last `window`
    paired deltas. rows: dicts with 'price' and 'implied_volatility', date ASC."""
    df = pd.DataFrame(rows)
    if df.empty or len(df) < window + 1:
        return None
    px = pd.to_numeric(df.get("price"), errors="coerce")
    iv = pd.to_numeric(df.get("implied_volatility"), errors="coerce")
    if px is None or iv is None:
        return None
    dlog_px = np.log(px.where(px > 0)).diff()
    div = iv.diff()
    pair = pd.DataFrame({"dpx": dlog_px, "div": div}).dropna().tail(window)
    if len(pair) < window:
        return None
    if pair["dpx"].std(ddof=1) == 0 or pair["div"].std(ddof=1) == 0:
        return None
    rho = pair["dpx"].corr(pair["div"])
    return None if pd.isna(rho) else float(rho)


def compute_skew_baseline(
    rr_series: list[float | None], *, z_window: int = 180, pct_window: int = 252
) -> dict:
    """z = (latest - mean) / std over trailing z_window; pct = % of trailing
    pct_window strictly below latest. min 30 obs each, else None."""
    s = pd.Series([x for x in rr_series if x is not None], dtype="float64")
    if s.empty:
        return {"z": None, "pct": None, "latest": None, "n": 0}
    latest = float(s.iloc[-1])
    z = None
    zwin = s.tail(z_window)
    if len(zwin) >= 30:
        mu = float(zwin.mean())
        sd = float(zwin.std(ddof=1))
        if sd and sd > 0:
            z = (latest - mu) / sd
    pct = None
    pwin = s.tail(pct_window)
    if len(pwin) >= 30:
        pct = float((pwin < latest).mean() * 100.0)
    return {"z": z, "pct": pct, "latest": latest, "n": int(len(s))}


def classify_deviation(
    z, pct, *, z_hi: float = 1.5, pct_hi: float = 85.0, pct_lo: float = 15.0
) -> str:
    rich = (z is not None and z >= z_hi) or (pct is not None and pct >= pct_hi)
    cheap = (z is not None and z <= -z_hi) or (pct is not None and pct <= pct_lo)
    if rich and not cheap:
        return "RICH"
    if cheap and not rich:
        return "CHEAP"
    return "NORMAL"


def classify_skew_term(front_rr, back_rr, *, eps: float = 0.005) -> str:
    if front_rr is None or back_rr is None:
        return "flat"
    d = float(front_rr) - float(back_rr)
    if d > eps:
        return "front_steep"
    if d < -eps:
        return "back_steep"
    return "flat"


def classify_drive(price_trend, rho, *, eps: float = 1e-9) -> str:
    """PANIC: price falling + rho<0 (vol up as spot down = real hedging fear).
    CHASE: price rising + rho>0 (vol up as spot up = mechanical/FOMO chase)."""
    if price_trend is None or rho is None:
        return "STRUCTURAL"
    if price_trend < -eps and rho < -eps:
        return "PANIC"
    if price_trend > eps and rho > eps:
        return "CHASE"
    return "STRUCTURAL"


def classify_market_regime(spy_rv_series: list[dict]) -> str:
    """HIGH_VOL/LOW_VOL from SPY 21d realized-vol percentile (vs 252d), >50 = HIGH.
    spy_rv_series: dicts with 'price', date ASC. Self-contained; no analytics table."""
    df = pd.DataFrame(spy_rv_series)
    if df.empty or "price" not in df or len(df) < 60:
        return "UNKNOWN"
    px = pd.to_numeric(df["price"], errors="coerce")
    ret = np.log(px.where(px > 0)).diff()
    rvol = ret.rolling(21, min_periods=21).std() * np.sqrt(252)
    rvol = rvol.dropna()
    if len(rvol) < 30:
        return "UNKNOWN"
    latest = float(rvol.iloc[-1])
    pct = float((rvol.tail(252) < latest).mean() * 100.0)
    return "HIGH_VOL" if pct >= 50.0 else "LOW_VOL"
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -v`
Expected: PASS for the part-1 tests.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/skew_first_principles.py tests/unit/cards/test_skew_first_principles.py
git commit -m "feat(skew): pure derivers — rho, baseline, deviation, term, regime"
```

---

### Task B2: asset-class, borrow flag, sign guard

**Files:**
- Modify: `src/uw_scan/cards/skew_first_principles.py`
- Test: `tests/unit/cards/test_skew_first_principles.py`

- [ ] **Step 1: Append failing tests**

```python
def test_asset_class_baseline_index_and_single_name():
    assert sk.asset_class_baseline("SPY")["asset_class"] == "index_macro"
    assert sk.asset_class_baseline("SPY")["expected_sign"] == "put_skew"
    assert sk.asset_class_baseline("NVDA")["asset_class"] == "single_name"
    assert sk.asset_class_baseline("HYG", sector="Credit")["asset_class"] == "credit"


def test_borrow_flag():
    assert sk.borrow_flag(2.0, 1.5) == "hard_to_borrow"
    assert sk.borrow_flag(0.25, 1.0) == "normal"
    assert sk.borrow_flag(None, None) == "unknown"


def test_sign_convention_guard():
    # Documented invariant: positive rr_25d means put-skew (downside hedging rich).
    # SPY-like positive => put_skew interpretation; TSLA-like negative => call_skew.
    assert sk.skew_sign_label(0.005) == "put_skew"
    assert sk.skew_sign_label(-0.012) == "call_skew"
    assert sk.skew_sign_label(0.0) == "flat"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -k "asset_class or borrow or sign_convention" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Append implementations**

```python
# Small static asset-class map (YAGNI — extend only when a real ticker needs it).
_INDEX_MACRO: frozenset[str] = frozenset(
    {"SPY", "SPX", "QQQ", "IWM", "DIA", "VIX", "VXX", "TLT", "GLD"}
)


def asset_class_baseline(ticker: str, *, sector: str | None = None) -> dict:
    t = (ticker or "").upper()
    sec = (sector or "").strip().lower()
    if t in _INDEX_MACRO or sec in {"macro", "index"}:
        return {"asset_class": "index_macro", "expected_sign": "put_skew"}
    if sec == "credit":
        return {"asset_class": "credit", "expected_sign": "put_skew"}
    if sec in {"sector-etf", "etf", "sector etf"}:
        return {"asset_class": "sector_etf", "expected_sign": "put_skew"}
    return {"asset_class": "single_name", "expected_sign": "mixed"}


def borrow_flag(fee_rate, days_to_cover, *, fee_htb_pct: float = 1.0) -> str:
    if fee_rate is None:
        return "unknown"
    try:
        return "hard_to_borrow" if float(fee_rate) >= fee_htb_pct else "normal"
    except (TypeError, ValueError):
        return "unknown"


def skew_sign_label(rr: float | None, *, eps: float = 1e-6) -> str:
    """Documented sign invariant: rr = IV(put)-IV(call). >0 put-skew, <0 call-skew."""
    if rr is None:
        return "unknown"
    if rr > eps:
        return "put_skew"
    if rr < -eps:
        return "call_skew"
    return "flat"
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -v`
Expected: PASS (all B1 + B2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/skew_first_principles.py tests/unit/cards/test_skew_first_principles.py
git commit -m "feat(skew): asset-class map, borrow flag, sign-convention guard"
```

---

### Task B3: `resolve_directional_lean` gate matrix + `build_read`

**Files:**
- Modify: `src/uw_scan/cards/skew_first_principles.py`
- Test: `tests/unit/cards/test_skew_first_principles.py`

- [ ] **Step 1: Append failing tests**

```python
def _verdict(v="TRADABLE_BEAR", conf="med"):
    return {"verdict": v, "confidence": conf, "forward_sep": -0.021,
            "borrow_clean": True, "survives_gate": True}


def test_lean_neutral_when_no_verdict():
    out = sk.resolve_directional_lean(
        deviation_class="RICH", drive_class="PANIC", asset_class="single_name",
        regime="HIGH_VOL", borrow_flag="normal", earnings_gate="pass", verdict=None,
    )
    assert out["lean"] == "NEUTRAL"
    assert "not" in out["basis"].lower() or "no proven" in out["basis"].lower()


def test_lean_bearish_when_tradable_bear_and_gates_pass():
    out = sk.resolve_directional_lean(
        deviation_class="RICH", drive_class="PANIC", asset_class="single_name",
        regime="HIGH_VOL", borrow_flag="normal", earnings_gate="pass",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    assert out["lean"] == "BEARISH_TILT"
    assert out["confidence"] == "med"
    assert out["express"]  # non-empty defined-risk structure


def test_lean_bullish_when_tradable_bull():
    out = sk.resolve_directional_lean(
        deviation_class="CHEAP", drive_class="STRUCTURAL", asset_class="single_name",
        regime="LOW_VOL", borrow_flag="normal", earnings_gate="pass",
        verdict=_verdict("TRADABLE_BULL"),
    )
    assert out["lean"] == "BULLISH_TILT"


def test_lean_suppressed_by_hard_to_borrow():
    out = sk.resolve_directional_lean(
        deviation_class="RICH", drive_class="PANIC", asset_class="single_name",
        regime="HIGH_VOL", borrow_flag="hard_to_borrow", earnings_gate="pass",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    assert out["lean"] == "NEUTRAL"
    assert "borrow" in out["basis"].lower()


def test_lean_suppressed_by_earnings_window():
    out = sk.resolve_directional_lean(
        deviation_class="RICH", drive_class="PANIC", asset_class="single_name",
        regime="HIGH_VOL", borrow_flag="normal", earnings_gate="block",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    assert out["lean"] == "NEUTRAL"
    assert "earnings" in out["basis"].lower()


def test_lean_none_verdict_value_is_neutral():
    out = sk.resolve_directional_lean(
        deviation_class="NORMAL", drive_class="STRUCTURAL", asset_class="single_name",
        regime="LOW_VOL", borrow_flag="normal", earnings_gate="pass",
        verdict=_verdict("NONE"),
    )
    assert out["lean"] == "NEUTRAL"


def test_lean_suppressed_when_verdict_regime_mismatches():
    out = sk.resolve_directional_lean(
        deviation_class="RICH", drive_class="PANIC", asset_class="single_name",
        regime="LOW_VOL", borrow_flag="normal", earnings_gate="pass",
        verdict={**_verdict("TRADABLE_BEAR"), "regime": "HIGH_VOL"},
    )
    assert out["lean"] == "NEUTRAL"
    assert "regime" in out["basis"].lower()


def test_build_read_includes_lean_and_summary():
    lean = sk.resolve_directional_lean(
        deviation_class="RICH", drive_class="PANIC", asset_class="single_name",
        regime="HIGH_VOL", borrow_flag="normal", earnings_gate="pass",
        verdict=_verdict("TRADABLE_BEAR"),
    )
    read = sk.build_read(
        tail="put", rho=-0.5, rho_confirms=True, drive_class="PANIC",
        deviation_class="RICH", asset_class="single_name", class_expected_sign="mixed",
        borrow_flag="normal", earnings_gate="pass", directional_lean=lean,
    )
    assert read["directional_lean"]["lean"] == "BEARISH_TILT"
    assert isinstance(read["summary_line"], str) and read["summary_line"]
    # Spec §11: no directional language leaks into the RV summary body.
    assert "BEARISH" not in read["summary_line"] and "BULLISH" not in read["summary_line"]
    assert "Lean" not in read["summary_line"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -k "lean or build_read" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Append implementations**

```python
def _express_structure(deviation_class: str, lean: str) -> str:
    """Defined-risk structure expressing the lean. NO naked shorts (standing rule):
    every structure is a vertical spread or a long option — never a bare short
    call/put and never a stock-assuming 'collar'."""
    if lean == "BEARISH_TILT":
        if deviation_class == "RICH":
            # finance by selling the lower (cheaper) put wing INSIDE a debit spread
            return "put-debit-spread (sell the lower put wing to finance) — defined risk"
        return "put-debit-spread — defined risk"
    if lean == "BULLISH_TILT":
        if deviation_class == "CHEAP":
            return "call-debit-spread (cheap downside hedge available) — defined risk"
        return "call-debit-spread or put-credit-spread — defined risk"
    return ""


def resolve_directional_lean(
    *,
    deviation_class: str,
    drive_class: str,
    asset_class: str,
    regime: str,
    borrow_flag: str,
    earnings_gate: str,
    verdict: dict | None,
) -> dict:
    """Evidence-gated lean. Non-neutral requires a TRADABLE_* verdict AND
    borrow_flag != hard_to_borrow AND earnings_gate != block. Any gate failing
    forces NEUTRAL with the reason recorded in `basis`."""
    def neutral(basis: str) -> dict:
        return {"lean": "NEUTRAL", "confidence": "low", "basis": basis, "express": ""}

    v = (verdict or {}).get("verdict")
    if not v or v == "NONE":
        return neutral(
            "no proven separation for this bucket yet — relative-value read only"
        )
    # Hard gate: the verdict must have been validated for the CURRENT regime.
    # The assembler looks up by current regime so these normally match; this is
    # defense-in-depth (a stale/mis-keyed verdict can never leak a lean).
    if (verdict or {}).get("regime") and verdict["regime"] != regime:
        return neutral("current regime differs from the validated regime — suppressed")
    if borrow_flag == "hard_to_borrow":
        return neutral(
            "hard-to-borrow — borrow-fee confound suppresses the directional lean"
        )
    if earnings_gate == "block":
        return neutral("earnings window active — directional lean suppressed")

    conf = (verdict or {}).get("confidence") or "low"
    sep = (verdict or {}).get("forward_sep")
    sep_txt = f"{float(sep) * 100:+.1f}%/20d" if sep is not None else "validated"
    if v == "TRADABLE_BEAR":
        lean = "BEARISH_TILT"
    elif v == "TRADABLE_BULL":
        lean = "BULLISH_TILT"
    else:
        return neutral("unrecognized verdict — neutral")
    basis = (
        f"validated — {deviation_class} {asset_class} bucket separated {sep_txt} "
        f"(survived regime gate); borrow normal => edge not a borrow artifact"
    )
    return {
        "lean": lean,
        "confidence": conf,
        "basis": basis,
        "express": _express_structure(deviation_class, lean),
    }


def build_read(
    *,
    tail: str,
    rho,
    rho_confirms: bool,
    drive_class: str,
    deviation_class: str,
    asset_class: str,
    class_expected_sign: str,
    borrow_flag: str,
    earnings_gate: str,
    directional_lean: dict,
) -> dict:
    """Stitch the deterministic read. The relative-value body is interpretive;
    `directional_lean` is the only field permitted to express direction."""
    rho_txt = (
        "spot-vol corr confirms the read"
        if rho_confirms
        else "spot-vol corr does not confirm — treat as positioning, not fear"
    )
    rv_body = {
        "RICH": "skew is rich vs its own baseline — historically mean-reverts; "
                "finance the expensive wing with a defined-risk vertical spread.",
        "CHEAP": "skew is cheap vs its own baseline — downside protection is on sale.",
        "NORMAL": "skew is near its own baseline — no relative-value edge today.",
    }.get(deviation_class, "no relative-value edge today.")
    # Spec §11: summary_line is the relative-value/context body ONLY. Direction is
    # confined to `directional_lean` (the single field allowed to express it).
    summary = (
        f"{deviation_class} {tail}-skew ({asset_class}); drive={drive_class}; "
        f"{rho_txt}. {rv_body}"
    )
    return {
        "tail": tail,
        "rho": rho,
        "rho_confirms": rho_confirms,
        "drive": drive_class,
        "deviation_class": deviation_class,
        "class_context": f"{asset_class} (expected {class_expected_sign})",
        "borrow_context": borrow_flag,
        "earnings_gate": earnings_gate,
        "directional_lean": directional_lean,
        "summary_line": summary,
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -v`
Expected: PASS (all B tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/skew_first_principles.py tests/unit/cards/test_skew_first_principles.py
git commit -m "feat(skew): evidence-gated resolve_directional_lean + build_read"
```

---

# Milestone C — Models, assembler, API

### Task C1: Pydantic response model

**Files:**
- Create: `src/uw_scan/models/skew.py`
- Modify: `src/uw_scan/models/__init__.py`

- [ ] **Step 1: Write the model module**

```python
"""Skew First-Principles tab response contracts."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from ._base import _UwBase, _preserve_public_module


class SkewHistoryPoint(_UwBase):
    date: _date
    rr: Decimal | None = None
    z: Decimal | None = None
    pct: Decimal | None = None


class SkewRhoPoint(_UwBase):
    date: _date
    rho: Decimal | None = None


class SkewExpiryPoint(_UwBase):
    expiry: _date
    rr: Decimal | None = None
    dte: int | None = None


class SkewSmilePoint(_UwBase):
    strike: Decimal
    iv: Decimal | None = None


class SkewSmileExpiryCurve(_UwBase):
    expiry: _date
    points: list[SkewSmilePoint] = []


class SkewDirectionalLean(_UwBase):
    lean: str = "NEUTRAL"  # BULLISH_TILT | BEARISH_TILT | NEUTRAL
    confidence: str = "low"  # low | med | high
    basis: str = ""
    express: str = ""


class SkewRead(_UwBase):
    tail: str = ""
    rho: Decimal | None = None
    rho_confirms: bool = False
    drive: str = ""
    deviation_class: str = ""
    class_context: str = ""
    borrow_context: str = ""
    earnings_gate: str = ""
    summary_line: str = ""
    directional_lean: SkewDirectionalLean = SkewDirectionalLean()


class SkewAnalysisResponse(_UwBase):
    ticker: str
    as_of: _date
    backfill_status: str = "ready"
    spot: Decimal | None = None
    rr_25d: Decimal | None = None
    rr_z_180d: Decimal | None = None
    rr_pct_252d: Decimal | None = None
    deviation_class: str = "NORMAL"
    skew_term_class: str = "flat"
    front_rr: Decimal | None = None
    back_rr: Decimal | None = None
    rho_spotvol_63d: Decimal | None = None
    rho_spotvol_21d: Decimal | None = None
    rho_sign: int | None = None
    drive_class: str = "STRUCTURAL"
    asset_class: str = "single_name"
    class_expected_sign: str = "mixed"
    borrow_flag: str = "unknown"
    borrow_fee_rate: Decimal | None = None
    days_to_cover: Decimal | None = None
    earnings_gate: str = "unknown"
    regime: str = "UNKNOWN"
    directional_lean: str = "NEUTRAL"
    lean_confidence: str = "low"
    lean_basis: str = ""
    read: SkewRead = SkewRead()
    history: list[SkewHistoryPoint] = []
    rho_series: list[SkewRhoPoint] = []
    term_structure: list[SkewExpiryPoint] = []
    smile: list[SkewSmileExpiryCurve] = []


_preserve_public_module(
    SkewHistoryPoint,
    SkewRhoPoint,
    SkewExpiryPoint,
    SkewSmilePoint,
    SkewSmileExpiryCurve,
    SkewDirectionalLean,
    SkewRead,
    SkewAnalysisResponse,
)
```

- [ ] **Step 2: Re-export from `models/__init__.py`**

Add a re-export block (after the `.scan_results`/`.scan_runs` import group, before `.trade_insights*`):

```python
from .skew import (
    SkewAnalysisResponse,
    SkewDirectionalLean,
    SkewExpiryPoint,
    SkewHistoryPoint,
    SkewRead,
    SkewRhoPoint,
    SkewSmileExpiryCurve,
    SkewSmilePoint,
)
```

And add these names to `__all__`:

```python
    "SkewHistoryPoint",
    "SkewRhoPoint",
    "SkewExpiryPoint",
    "SkewSmilePoint",
    "SkewSmileExpiryCurve",
    "SkewDirectionalLean",
    "SkewRead",
    "SkewAnalysisResponse",
```

- [ ] **Step 3: Verify exports + module identity**

Run: `uv run python -c "from uw_scan.models import SkewAnalysisResponse; print(SkewAnalysisResponse.__module__)"`
Expected: prints `uw_scan.models` (not `uw_scan.models.skew`).

Run: `uv run pytest tests/unit/test_models_exports.py -q`
Expected: PASS (no export-surface regression).

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/models/skew.py src/uw_scan/models/__init__.py
git commit -m "feat(skew): SkewAnalysisResponse contract + exports"
```

---

### Task C2: Snapshot-row builder (pure stitch) + assembler

**Files:**
- Create: `src/uw_scan/reports/skew_analytics.py`
- Test: `tests/unit/reports/test_skew_snapshot_row.py`

- [ ] **Step 1: Write the failing unit test for the pure builder**

```python
"""Unit test: build_skew_snapshot_row stitches derivers into a column dict."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.skew_analytics import build_skew_snapshot_row


def _rr_series(n=200, val=0.001):
    base = date(2026, 1, 1)
    rows = [{"market_date": base + timedelta(days=i), "risk_reversal": val,
             "expiry": base + timedelta(days=40)} for i in range(n)]
    rows.append({"market_date": base + timedelta(days=n),
                 "risk_reversal": 0.05, "expiry": base + timedelta(days=40)})  # spike RICH
    return rows


def _rv_series(n=210):
    base = date(2026, 1, 1)
    out = []
    p, iv = 100.0, 0.2
    for i in range(n):
        p *= 0.999
        iv += 0.0005
        out.append({"market_date": base + timedelta(days=i),
                    "price": p, "implied_volatility": iv, "realized_volatility": 0.18})
    return out


def test_build_row_rich_panic_neutral_without_verdict():
    rr = _rr_series()
    row = build_skew_snapshot_row(
        ticker="NVDA",
        market_date=rr[-1]["market_date"],
        rr_series=rr,
        expiry_rows=[{"expiry": date(2026, 8, 1), "risk_reversal": 0.05}],
        rv_series=_rv_series(),
        spy_rv_series=_rv_series(),
        positioning={"si_fee_rate": 0.25, "si_days_to_cover": 1.2},
        next_earnings_date=None,
        verdict=None,
        sector=None,
        today=rr[-1]["market_date"],
    )
    assert row["ticker"] == "NVDA"
    assert row["deviation_class"] == "RICH"
    assert row["directional_lean"] == "NEUTRAL"  # no verdict
    assert row["borrow_flag"] == "normal"
    assert row["spot"] is not None  # markout anchor present


def test_build_row_bearish_with_seeded_verdict():
    rr = _rr_series()
    row = build_skew_snapshot_row(
        ticker="NVDA",
        market_date=rr[-1]["market_date"],
        rr_series=rr,
        expiry_rows=[{"expiry": date(2026, 8, 1), "risk_reversal": 0.05}],
        rv_series=_rv_series(),
        spy_rv_series=_rv_series(),
        positioning={"si_fee_rate": 0.25, "si_days_to_cover": 1.2},
        next_earnings_date=None,
        verdict={"verdict": "TRADABLE_BEAR", "confidence": "med", "forward_sep": -0.02,
                 "borrow_clean": True, "survives_gate": True},
        sector=None,
        today=rr[-1]["market_date"],
    )
    assert row["directional_lean"] == "BEARISH_TILT"
    assert row["lean_confidence"] == "med"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/reports/test_skew_snapshot_row.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `reports/skew_analytics.py`**

```python
"""Skew First-Principles assembler.

Reads persisted raw series via the repo, calls the pure derivers in
cards/skew_first_principles.py, stitches a SkewAnalysisResponse, and persists
the per-day snapshot (standing 'persist analytical results' rule).
"""

from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from typing import Any

import pandas as pd

from uw_scan.cards import skew_first_principles as sk
from uw_scan.models import (
    SkewAnalysisResponse,
    SkewDirectionalLean,
    SkewExpiryPoint,
    SkewHistoryPoint,
    SkewRead,
    SkewRhoPoint,
    SkewSmileExpiryCurve,
    SkewSmilePoint,
)
from uw_scan.scanner.gates import earnings_gate as _earnings_gate
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _dec(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, float) and (pd.isna(v) or not (-1e30 < v < 1e30)):
        return None
    try:
        return Decimal(str(v))
    except Exception as exc:  # noqa: BLE001
        log.debug("decimal coercion skipped for %r: %s", v, repr(exc))
        return None


def _price_trend(rv_series: list[dict], *, window: int = 20) -> float | None:
    px = pd.to_numeric(pd.DataFrame(rv_series).get("price"), errors="coerce").dropna()
    if len(px) < window + 1:
        return None
    prev = float(px.iloc[-window - 1])
    if prev == 0:
        return None
    return float(px.iloc[-1]) / prev - 1.0


def build_skew_snapshot_row(
    *,
    ticker: str,
    market_date: _date,
    rr_series: list[dict],
    expiry_rows: list[dict],
    rv_series: list[dict],
    spy_rv_series: list[dict],
    positioning: dict | None,
    next_earnings_date: _date | None,
    verdict: dict | None,
    sector: str | None,
    today: _date,
) -> dict:
    """Pure stitch: raw series + verdict in, snapshot column dict out. No I/O."""
    rr_vals = [r.get("risk_reversal") for r in rr_series]
    rr_floats = [float(x) for x in rr_vals if x is not None]
    base = sk.compute_skew_baseline(rr_vals)
    rr_25d = rr_floats[-1] if rr_floats else None
    deviation = sk.classify_deviation(base["z"], base["pct"])

    # term structure (front = nearest expiry, back = furthest); degrade to flat
    front_rr = back_rr = None
    if expiry_rows:
        ordered = sorted(expiry_rows, key=lambda r: r.get("expiry") or _date.max)
        front_rr = ordered[0].get("risk_reversal")
        if len(ordered) >= 2:
            back_rr = ordered[-1].get("risk_reversal")
    term_class = sk.classify_skew_term(front_rr, back_rr)

    rho63 = sk.compute_spot_vol_rho(rv_series, window=63)
    rho21 = sk.compute_spot_vol_rho(rv_series, window=21)
    rho_sign = 0 if rho63 is None else (1 if rho63 > 0 else (-1 if rho63 < 0 else 0))
    trend = _price_trend(rv_series)
    drive = sk.classify_drive(trend, rho63)

    cls = sk.asset_class_baseline(ticker, sector=sector)
    pos = positioning or {}
    bflag = sk.borrow_flag(pos.get("si_fee_rate"), pos.get("si_days_to_cover"))
    # None earnings => "unknown" (not "block"): the scanner gate returns "block"
    # for None, but unknown earnings is not positive evidence of an active window.
    # Only a confirmed imminent window ("block") suppresses the lean (see B3).
    egate = (
        "unknown"
        if next_earnings_date is None
        else _earnings_gate(next_earnings_date=next_earnings_date, today=today)
    )
    regime = sk.classify_market_regime(spy_rv_series)

    lean = sk.resolve_directional_lean(
        deviation_class=deviation,
        drive_class=drive,
        asset_class=cls["asset_class"],
        regime=regime,
        borrow_flag=bflag,
        earnings_gate=egate,
        verdict=verdict,
    )
    tail = sk.skew_sign_label(rr_25d)
    rho_confirms = (deviation == "RICH" and rho_sign < 0) or (
        deviation == "CHEAP" and rho_sign > 0
    )
    read = sk.build_read(
        tail=tail, rho=rho63, rho_confirms=rho_confirms, drive_class=drive,
        deviation_class=deviation, asset_class=cls["asset_class"],
        class_expected_sign=cls["expected_sign"], borrow_flag=bflag,
        earnings_gate=egate, directional_lean=lean,
    )
    spot = rv_series[-1].get("price") if rv_series else None

    return {
        "ticker": ticker.upper(),
        "market_date": market_date,
        "basis": "eod",
        "spot": _dec(spot),
        "rr_25d": _dec(rr_25d),
        "skew_25d": _dec(rr_25d),
        "rr_z_180d": _dec(base["z"]),
        "rr_pct_252d": _dec(base["pct"]),
        "deviation_class": deviation,
        "skew_term_class": term_class,
        "front_rr": _dec(front_rr),
        "back_rr": _dec(back_rr),
        "rho_spotvol_63d": _dec(rho63),
        "rho_spotvol_21d": _dec(rho21),
        "rho_sign": rho_sign,
        "drive_class": drive,
        "asset_class": cls["asset_class"],
        "class_expected_sign": cls["expected_sign"],
        "borrow_flag": bflag,
        "borrow_fee_rate": _dec(pos.get("si_fee_rate")),
        "days_to_cover": _dec(pos.get("si_days_to_cover")),
        "earnings_gate": egate,
        "regime": regime,
        "directional_lean": lean["lean"],
        "lean_confidence": lean["confidence"],
        "lean_basis": lean["basis"],
        "read_summary": read["summary_line"],
        "read_json": read,
    }


def _read_series_for_ticker(repo: Repository, ticker: str, today: _date) -> dict:
    """All repo reads needed to build the latest snapshot + response series."""
    rr_series = repo.fetch_matrix_skew_history(
        ticker=ticker, market_date=today, days=400
    )
    rv_series = repo.fetch_realized_vol_history(ticker, days=400)
    spy_rv = repo.fetch_realized_vol_history("SPY", days=400)
    latest_rr_date = rr_series[-1]["market_date"] if rr_series else today
    expiry_rows = repo.fetch_matrix_skew_expiry_rows(
        ticker=ticker, market_date=latest_rr_date
    )
    positioning = repo.get_uw_positioning(ticker)
    next_er = repo.fetch_latest_next_earnings_date(ticker)
    return {
        "rr_series": rr_series, "rv_series": rv_series, "spy_rv": spy_rv,
        "latest_rr_date": latest_rr_date, "expiry_rows": expiry_rows,
        "positioning": positioning, "next_er": next_er,
    }


def assemble_skew_analysis(
    *, ticker: str, repo: Repository, backfill_status: str = "ready", persist: bool = True
) -> SkewAnalysisResponse:
    t = ticker.upper()
    today = _date.today()
    data = _read_series_for_ticker(repo, t, today)

    if not data["rr_series"]:
        return SkewAnalysisResponse(ticker=t, as_of=today, backfill_status="empty")

    # build snapshot for the latest RR date; verdict looked up after we know bucket
    market_date = data["latest_rr_date"]
    # Slice RV/SPY to <= market_date so spot/rho/drive never read data dated after
    # the snapshot anchor (markout integrity — no look-ahead). C-7.
    rv_asof = [r for r in data["rv_series"] if r["market_date"] <= market_date]
    spy_asof = [r for r in data["spy_rv"] if r["market_date"] <= market_date]
    sector = repo.fetch_watchlist_sector(t)  # threads Macro/Credit/Sector-ETF. C-6.
    # first pass with no verdict to learn the bucket keys
    pre = build_skew_snapshot_row(
        ticker=t, market_date=market_date, rr_series=data["rr_series"],
        expiry_rows=data["expiry_rows"], rv_series=rv_asof,
        spy_rv_series=spy_asof, positioning=data["positioning"],
        next_earnings_date=data["next_er"], verdict=None, sector=sector, today=today,
    )
    verdict = repo.get_skew_directional_verdict(
        asset_class=pre["asset_class"], deviation_class=pre["deviation_class"],
        drive_class=pre["drive_class"], regime=pre["regime"],
    )
    row = build_skew_snapshot_row(
        ticker=t, market_date=market_date, rr_series=data["rr_series"],
        expiry_rows=data["expiry_rows"], rv_series=rv_asof,
        spy_rv_series=spy_asof, positioning=data["positioning"],
        next_earnings_date=data["next_er"], verdict=verdict, sector=sector, today=today,
    )

    if persist:
        repo.upsert_skew_analytics_snapshots([row])
        repo.conn.commit()

    # response series
    rr_hist = repo.fetch_matrix_skew_history(ticker=t, market_date=today, days=400)
    rr_floats = [
        float(r["risk_reversal"]) for r in rr_hist if r.get("risk_reversal") is not None
    ]
    history: list[SkewHistoryPoint] = []
    for i, r in enumerate(rr_hist):
        if r.get("risk_reversal") is None:
            continue
        win = rr_floats[: i + 1]
        b = sk.compute_skew_baseline(win)
        history.append(
            SkewHistoryPoint(
                date=r["market_date"], rr=_dec(r["risk_reversal"]),
                z=_dec(b["z"]), pct=_dec(b["pct"]),
            )
        )

    rho_series: list[SkewRhoPoint] = []
    rv_df = data["rv_series"]
    for i in range(63, len(rv_df)):
        rho = sk.compute_spot_vol_rho(rv_df[: i + 1], window=63)
        rho_series.append(SkewRhoPoint(date=rv_df[i]["market_date"], rho=_dec(rho)))

    term = [
        SkewExpiryPoint(expiry=e["expiry"], rr=_dec(e.get("risk_reversal")))
        for e in data["expiry_rows"]
        if e.get("expiry") is not None
    ]

    smile_rows = repo.fetch_iv_smile_latest(t)  # _VolatilityV2Mixin, returns expiry/strike/iv
    smile = _build_smile_curves(smile_rows)

    rj = row["read_json"]
    lean = rj["directional_lean"]
    read = SkewRead(
        tail=rj["tail"], rho=_dec(rj["rho"]), rho_confirms=rj["rho_confirms"],
        drive=rj["drive"], deviation_class=rj["deviation_class"],
        class_context=rj["class_context"], borrow_context=rj["borrow_context"],
        earnings_gate=rj["earnings_gate"], summary_line=rj["summary_line"],
        directional_lean=SkewDirectionalLean(
            lean=lean["lean"], confidence=lean["confidence"],
            basis=lean["basis"], express=lean["express"],
        ),
    )
    return SkewAnalysisResponse(
        ticker=t, as_of=today, backfill_status=backfill_status,
        spot=row["spot"], rr_25d=row["rr_25d"], rr_z_180d=row["rr_z_180d"],
        rr_pct_252d=row["rr_pct_252d"], deviation_class=row["deviation_class"],
        skew_term_class=row["skew_term_class"], front_rr=row["front_rr"],
        back_rr=row["back_rr"], rho_spotvol_63d=row["rho_spotvol_63d"],
        rho_spotvol_21d=row["rho_spotvol_21d"], rho_sign=row["rho_sign"],
        drive_class=row["drive_class"], asset_class=row["asset_class"],
        class_expected_sign=row["class_expected_sign"], borrow_flag=row["borrow_flag"],
        borrow_fee_rate=row["borrow_fee_rate"], days_to_cover=row["days_to_cover"],
        earnings_gate=row["earnings_gate"], regime=row["regime"],
        directional_lean=row["directional_lean"], lean_confidence=row["lean_confidence"],
        lean_basis=row["lean_basis"], read=read, history=history,
        rho_series=rho_series, term_structure=term, smile=smile,
    )


def _build_smile_curves(rows: list[dict]) -> list[SkewSmileExpiryCurve]:
    by_expiry: dict[Any, list[SkewSmilePoint]] = {}
    for r in rows or []:
        ex = r.get("expiry")
        if ex is None or r.get("strike") is None:
            continue
        by_expiry.setdefault(ex, []).append(
            SkewSmilePoint(strike=_dec(r["strike"]), iv=_dec(r.get("iv")))
        )
    return [
        SkewSmileExpiryCurve(expiry=ex, points=sorted(pts, key=lambda p: p.strike))
        for ex, pts in sorted(by_expiry.items())
    ]
```

> **Smile note (verified):** `repo.fetch_iv_smile_latest(ticker)` exists in `storage/volatility_v2.py:77` (`_VolatilityV2Mixin`) and returns rows with `expiry, strike, iv, market_date` for the latest smile date. `_build_smile_curves` consumes exactly those keys. Only 34 tickers have smile data locally; for tickers without it the method returns `[]` and the chart renders its "insufficient data" state.

> **Design note — recompute-always (deviation from spec §5 "read snapshot, live-compute fallback"):** the assembler recomputes the latest snapshot on every request (then upserts it), rather than reading the persisted snapshot first. Rationale: (1) it always reflects the freshest verdicts/borrow/earnings, which sidesteps the stale-lean problem (a snapshot persisted before the markout ran would carry NEUTRAL); (2) the response needs the `history`/`rho_series` derived series anyway, so the row build is incremental cost; (3) it matches the Volatility tab's assembler, which also recomputes. The persisted `skew_analytics_snapshot` is therefore a *cache + markout substrate*, not the request's source of truth. This is a deliberate, documented choice — if request latency becomes a problem, add a freshness check that serves the persisted row when `inserted_at` is same-day.

> **Percentile-band note (C-11):** `SkewHistoryChart` renders the "you are here" marker (last-point dot) plus a current-percentile readout (headline) sourced from `history[-1].pct`. Full shaded percentile bands are deferred V1 polish — the readout conveys the same positioning signal without a second pass over the series.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/reports/test_skew_snapshot_row.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/skew_analytics.py tests/unit/reports/test_skew_snapshot_row.py
git commit -m "feat(skew): assembler + pure snapshot-row builder"
```

---

### Task C3: API router + mount + gen:types

**Files:**
- Create: `src/uw_scan/api/routers/skew.py`
- Modify: `src/uw_scan/api/server.py`
- Test: `tests/integration/api/test_skew.py`

- [ ] **Step 1: Write the failing endpoint test**

```python
"""Integration test: GET /api/stock/{ticker}/skew."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def repo(seeded_db_empty_cards):
    """Alias for the canonical bare-Repository fixture; same test DB the client reads."""
    return seeded_db_empty_cards


def _seed_rr_rv(repo, ticker="AAPL", n=210):
    base = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(n):
            d = base + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry, risk_reversal) "
                "VALUES (%s,%s,25,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, base + timedelta(days=300), 0.001 if i < n - 1 else 0.05),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 100 - i * 0.05, 0.2 + i * 0.0005, 0.18),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES ('SPY',%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (d, 400 + (i % 3), 0.15, 0.14),
            )
    repo.conn.commit()


def test_skew_endpoint_shape(client: TestClient, repo):
    _seed_rr_rv(repo, "AAPL")
    r = client.get("/api/stock/AAPL/skew")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["deviation_class"] in {"RICH", "CHEAP", "NORMAL"}
    assert body["directional_lean"] in {"BULLISH_TILT", "BEARISH_TILT", "NEUTRAL"}
    assert "directional_lean" in body["read"]
    assert isinstance(body["history"], list)


def test_skew_endpoint_empty_ticker(client: TestClient, repo):
    r = client.get("/api/stock/ZZZZ/skew")
    assert r.status_code == 200
    assert r.json()["backfill_status"] == "empty"


def test_skew_endpoint_surfaces_seeded_verdict(client: TestClient, repo):
    """Spec §9 'assembler wiring': a TRADABLE_* verdict for the computed bucket
    surfaces as a non-neutral lean; absent verdict => NEUTRAL."""
    _seed_rr_rv(repo, "AAPL")
    first = client.get("/api/stock/AAPL/skew").json()
    assert first["directional_lean"] == "NEUTRAL"  # no verdict yet
    # seed a TRADABLE_BEAR verdict for the EXACT bucket the response reports
    repo.upsert_skew_directional_verdict(
        asset_class=first["asset_class"], deviation_class=first["deviation_class"],
        drive_class=first["read"]["drive"] or first["drive_class"],
        regime=first["regime"], verdict="TRADABLE_BEAR", confidence="med",
        forward_sep=Decimal("-0.02"), n=40, borrow_clean=True,
        survives_gate=True, as_of=date(2026, 6, 1),
    )
    repo.conn.commit()
    second = client.get("/api/stock/AAPL/skew").json()
    # lean is non-neutral only if the live borrow/earnings gates also pass;
    # the AAPL seed is normal-borrow + no earnings row => gates pass.
    assert second["directional_lean"] in {"BEARISH_TILT", "NEUTRAL"}
    if second["borrow_flag"] != "hard_to_borrow" and second["earnings_gate"] != "block":
        assert second["directional_lean"] == "BEARISH_TILT"
        assert second["read"]["directional_lean"]["express"]
```

> `client` is from `tests/integration/api/conftest.py`; `repo` aliases `seeded_db_empty_cards` and writes to the same test DB the client reads (committed). The verdict-wiring test discovers the bucket from the first response, then asserts the lean flips — exercising the assembler's verdict lookup end-to-end.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/api/test_skew.py -v`
Expected: FAIL — 404 (route not mounted).

- [ ] **Step 3: Write the router**

```python
"""GET /api/stock/{ticker}/skew — Skew First-Principles tab."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from uw_scan.api.deps import get_repo
from uw_scan.models import SkewAnalysisResponse
from uw_scan.reports.skew_analytics import assemble_skew_analysis
from uw_scan.storage.repository import Repository

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/stock/{ticker}/skew", response_model=SkewAnalysisResponse)
def get_skew_analysis(
    ticker: str, repo: Repository = Depends(get_repo)
) -> SkewAnalysisResponse:
    return assemble_skew_analysis(ticker=ticker.upper(), repo=repo)
```

- [ ] **Step 4: Mount in `server.py`**

Add `skew` to the routers import tuple (line ~8 block):

```python
from uw_scan.api.routers import (
    ...
    skew,
    ...
)
```

And mount it right after the volatility router (line ~50):

```python
    app.include_router(skew.router, prefix="/api", tags=["skew"])
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/integration/api/test_skew.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Regenerate types**

Run: `cd web && npm run gen:types && git diff --stat lib/types.ts`
Expected: `lib/types.ts` changes (adds the `/api/stock/{ticker}/skew` path + `SkewAnalysisResponse` schema).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/api/routers/skew.py src/uw_scan/api/server.py tests/integration/api/test_skew.py web/lib/types.ts
git commit -m "feat(skew): GET /api/stock/{ticker}/skew router + types"
```

---

# Milestone D — Worker jobs (rollup + backfill)

### Task D1: Nightly rollup + backfill job

**Files:**
- Create: `src/uw_scan/worker/jobs/skew_analytics.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_skew_jobs.py`

- [ ] **Step 1: Write the failing job test**

Create `tests/integration/worker/test_skew_jobs.py`:

```python
"""Integration test: nightly_skew_analytics_rollup + skew_analytics_backfill."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.worker.jobs.skew_analytics import (
    nightly_skew_analytics_rollup,
    skew_analytics_backfill,
)


@pytest.fixture
def repo(seeded_db_empty_cards):
    return seeded_db_empty_cards


def _seed(repo, ticker, n=210):
    base = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        cur.execute(
            "INSERT INTO uw_scan.watchlist (ticker, sector) VALUES (%s,'Tech') "
            "ON CONFLICT (ticker) DO NOTHING",
            (ticker,),
        )
        for i in range(n):
            d = base + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry, risk_reversal) "
                "VALUES (%s,%s,25,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, base + timedelta(days=300), 0.001 if i < n - 1 else 0.05),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES (%s,%s,%s,%s,0.18) ON CONFLICT DO NOTHING",
                (ticker, d, 100 - i * 0.05, 0.2 + i * 0.0005),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price, implied_volatility, realized_volatility) "
                "VALUES ('SPY',%s,%s,0.15,0.14) ON CONFLICT DO NOTHING",
                (d, 400 + (i % 3)),
            )
    repo.conn.commit()


def test_rollup_writes_snapshot(repo):
    _seed(repo, "AAPL")
    nightly_skew_analytics_rollup(repo=repo)
    assert repo.get_skew_analytics_latest("AAPL") is not None


def test_backfill_writes_multiple_dates(repo):
    _seed(repo, "AAPL")
    written = skew_analytics_backfill(
        repo=repo, start=date(2026, 7, 1), end=date(2026, 7, 5)
    )
    assert written >= 1
    rows = repo.fetch_skew_analytics_history("AAPL", days=4000)
    assert len(rows) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/worker/test_skew_jobs.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the job module**

```python
"""Skew analytics worker jobs: nightly rollup + historical backfill."""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta

from uw_scan.cards import skew_first_principles as sk
from uw_scan.reports.skew_analytics import build_skew_snapshot_row
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _build_for_date(repo: Repository, ticker: str, market_date: _date, today: _date,
                    full_rr: list[dict], full_rv: list[dict], spy_rv: list[dict],
                    sector: str | None, next_earnings_date: _date | None,
                    positioning: dict | None) -> dict | None:
    # positioning is passed in (fetched once per ticker by the caller) — it is the
    # latest snapshot regardless of market_date (current-borrow limitation, spec §11),
    # so re-fetching per date would be wasteful and identical.
    rr = [r for r in full_rr if r["market_date"] <= market_date]
    rv = [r for r in full_rv if r["market_date"] <= market_date]
    spy = [r for r in spy_rv if r["market_date"] <= market_date]
    if not rr or not rv:
        return None
    expiry_rows = repo.fetch_matrix_skew_expiry_rows(
        ticker=ticker, market_date=rr[-1]["market_date"]
    )
    pre = build_skew_snapshot_row(
        ticker=ticker, market_date=market_date, rr_series=rr, expiry_rows=expiry_rows,
        rv_series=rv, spy_rv_series=spy, positioning=positioning,
        next_earnings_date=next_earnings_date, verdict=None, sector=sector, today=today,
    )
    verdict = repo.get_skew_directional_verdict(
        asset_class=pre["asset_class"], deviation_class=pre["deviation_class"],
        drive_class=pre["drive_class"], regime=pre["regime"],
    )
    return build_skew_snapshot_row(
        ticker=ticker, market_date=market_date, rr_series=rr, expiry_rows=expiry_rows,
        rv_series=rv, spy_rv_series=spy, positioning=positioning,
        next_earnings_date=next_earnings_date, verdict=verdict, sector=sector, today=today,
    )


def nightly_skew_analytics_rollup(*, repo: Repository) -> None:
    """One basis='eod' snapshot per watchlist ticker for the latest RR date.

    Uses the current earnings date + current borrow (live snapshot). Run AFTER
    run_skew_markout so the persisted directional_lean reflects fresh verdicts;
    the endpoint recomputes the lean live, so the snapshot lean is only a cache.
    """
    cards = repo.list_watchlist_cards()
    today = _date.today()
    spy_rv = repo.fetch_realized_vol_history("SPY", days=400)
    written = 0
    for card in cards:
        ticker = card.ticker
        rr = repo.fetch_matrix_skew_history(ticker=ticker, market_date=today, days=400)
        rv = repo.fetch_realized_vol_history(ticker, days=400)
        if not rr or not rv:
            continue
        next_er = repo.fetch_latest_next_earnings_date(ticker)
        positioning = repo.get_uw_positioning(ticker)
        row = _build_for_date(
            repo, ticker, rr[-1]["market_date"], today, rr, rv, spy_rv,
            card.sector, next_er, positioning,
        )
        if row is not None:
            repo.upsert_skew_analytics_snapshots([row])
            written += 1
    repo.conn.commit()
    log.info("nightly_skew_analytics_rollup wrote %d snapshots", written)


def skew_analytics_backfill(
    *, repo: Repository, start: _date, end: _date, tickers: list[str] | None = None
) -> int:
    """Compute snapshots across [start, end] (inclusive) for the Tier-1 set.

    Historical rows have NO point-in-time earnings (next_earnings_date=None ->
    earnings_gate='unknown') and reuse CURRENT borrow (documented limitation,
    spec §11). Neither feeds the markout's directional separation (which buckets
    on deviation/drive/regime/asset_class and the current borrow_flag), so the
    Tier-1 verdicts are not corrupted by the absence of PIT earnings.
    """
    if tickers is None:
        tickers = [c.ticker for c in repo.list_watchlist_cards()]
    spy_rv = repo.fetch_realized_vol_history("SPY", days=4000)
    written = 0
    for ticker in tickers:
        rr = repo.fetch_matrix_skew_history(ticker=ticker, market_date=end, days=4000)
        rv = repo.fetch_realized_vol_history(ticker, days=4000)
        if not rr or not rv:
            continue
        sector = repo.fetch_watchlist_sector(ticker)
        positioning = repo.get_uw_positioning(ticker)  # once per ticker, not per date
        rr_dates = {r["market_date"] for r in rr}
        d = start
        rows = []
        while d <= end:
            if d in rr_dates:
                row = _build_for_date(
                    repo, ticker, d, d, rr, rv, spy_rv, sector, None, positioning
                )
                if row is not None:
                    rows.append(row)
            d += timedelta(days=1)
        if rows:
            repo.upsert_skew_analytics_snapshots(rows)
            written += len(rows)
    repo.conn.commit()
    log.info("skew_analytics_backfill wrote %d snapshots", written)
    return written
```

> **`fetch_realized_vol_history` caveat:** its WHERE clause filters by `CURRENT_DATE - days`. For historical backfill the seeded dates may be older than `days` from today — pass a large `days` (e.g. 4000) so the window covers the backfill range. The integration test uses seeded 2026 dates; with `days=4000` they fall inside the window relative to the test clock.

- [ ] **Step 4: Register the nightly rollup in `scheduler.py`**

Add the import near the other job imports (after the `volatility_jobs` import block, line ~57):

```python
from uw_scan.worker.jobs.skew_analytics import nightly_skew_analytics_rollup
```

Add a wrapper function alongside the other `_*_rollup` wrappers (mirror `_vol_analytics_rollup`):

```python
    def _skew_analytics_rollup() -> None:
        with _repo(settings) as repo:
            nightly_skew_analytics_rollup(repo=repo)
```

Register it right after the `nightly_vol_analytics_rollup` registration (line ~742), at 18:30 ET so it runs after the 18:00 vol rollup:

```python
            sched.add_job(
                _skew_analytics_rollup,
                CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
                id="nightly_skew_analytics_rollup",
                name="Nightly skew analytics rollup",
                max_instances=1,
                coalesce=True,
            )
```

> Match the exact wrapper style used by the existing vol rollup registration in this file — if it uses a module-level wrapper rather than a closure, follow that. The verification is the test in Step 5 plus a scheduler import smoke check.

- [ ] **Step 5: Run job tests + scheduler import smoke**

Run: `uv run pytest tests/integration/worker/test_skew_jobs.py -v`
Expected: PASS (2 tests).

Run: `uv run python -c "import uw_scan.worker.scheduler"`
Expected: no ImportError.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/jobs/skew_analytics.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_skew_jobs.py
git commit -m "feat(skew): nightly rollup + backfill job + scheduler wiring"
```

---

# Milestone E — Tier-1 markout + verdict store

> **Execution amendment (2026-06-15):** the markout below scored RAW forward returns,
> which made ~every bucket `TRADABLE_BULL` in the up-trending backfill window (market
> beta, not skew edge) — and SPY-subtraction still left this growth/high-beta
> universe's beta>1 drift. The shipped `run_skew_markout` instead **cross-sectionally
> demeans** each name's T+20 forward return by the universe's same-date mean before
> bucketing, so a verdict reflects separation vs peers. Result on the local backfill:
> 72% of tickers NEUTRAL, 16 BEAR / 9 BULL. See `src/uw_scan/reports/skew_markout.py`
> and `docs/research/skew-first-principles-markout-2026-06.md` for the as-shipped code
> and findings. The test seeds a falling name + a flat peer so the falling name is the
> cross-sectional outlier.

### Task E1: Markout harness writes per-bucket verdicts

**Files:**
- Create: `src/uw_scan/reports/skew_markout.py`
- Test: `tests/integration/reports/test_skew_markout.py`

- [ ] **Step 1: Write the failing markout test**

```python
"""Integration test: skew markout buckets snapshots, scores forwards, writes verdicts.

End-to-end safety property: a seeded TRADABLE_* verdict surfaces as a non-neutral
lean on the next rollup; no verdict => NEUTRAL.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.reports.skew_markout import run_skew_markout


@pytest.fixture
def repo(seeded_db_empty_cards):
    return seeded_db_empty_cards


def _seed_snapshot_and_forwards(repo, ticker="NVDA"):
    base = date(2026, 2, 1)
    # one RICH/PANIC/single_name/HIGH_VOL snapshot with a known forward drop
    repo.upsert_skew_analytics_snapshots([{
        "ticker": ticker, "market_date": base, "basis": "eod",
        "spot": Decimal("100"), "rr_25d": Decimal("0.05"), "skew_25d": Decimal("0.05"),
        "rr_z_180d": Decimal("2.0"), "rr_pct_252d": Decimal("95"),
        "deviation_class": "RICH", "skew_term_class": "flat",
        "front_rr": Decimal("0.05"), "back_rr": None,
        "rho_spotvol_63d": Decimal("-0.5"), "rho_spotvol_21d": Decimal("-0.6"), "rho_sign": -1,
        "drive_class": "PANIC", "asset_class": "single_name", "class_expected_sign": "mixed",
        "borrow_flag": "normal", "borrow_fee_rate": Decimal("0.25"), "days_to_cover": Decimal("1"),
        "earnings_gate": "pass", "regime": "HIGH_VOL",
        "directional_lean": "NEUTRAL", "lean_confidence": "low", "lean_basis": "seed",
        "read_summary": "seed", "read_json": {},
    }])
    # >=20 forward TRADING-day rows, price declining ~0.2%/day -> T+20 ~ -4%.
    # Forward horizons are positional (nth row after anchor), so we need >=20 rows.
    with repo.conn.cursor() as cur:
        for off in range(1, 26):
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history "
                "(ticker, market_date, price) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, base + timedelta(days=off), 100 - off * 0.2),
            )
    repo.conn.commit()


def test_markout_writes_bear_verdict_on_separation(repo):
    _seed_snapshot_and_forwards(repo, "NVDA")
    # threshold low enough for n=1 to be material in the test
    counts = run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)
    v = repo.get_skew_directional_verdict(
        asset_class="single_name", deviation_class="RICH",
        drive_class="PANIC", regime="HIGH_VOL",
    )
    assert v is not None
    assert v["verdict"] == "TRADABLE_BEAR"
    assert counts["verdicts_written"] >= 1


def test_markout_none_when_below_min_n(repo):
    _seed_snapshot_and_forwards(repo, "NVDA")
    run_skew_markout(repo=repo, min_n=50, sep_threshold=0.005)
    v = repo.get_skew_directional_verdict(
        asset_class="single_name", deviation_class="RICH",
        drive_class="PANIC", regime="HIGH_VOL",
    )
    assert v is not None and v["verdict"] == "NONE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/reports/test_skew_markout.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `reports/skew_markout.py`**

```python
"""Tier-1 skew markout: bucket snapshots, score forward returns, write verdicts.

Two hypotheses (spec §7 step 2):
  PRIMARY   — RV mean-reversion: does extreme RR (RICH/CHEAP) revert? Measured as
              mean forward dRR per (asset_class, deviation_class); REPORTED in the
              return dict for the research note, not gated into a verdict.
  SECONDARY — directional, borrow-conditioned: do buckets separate forward STOCK
              returns on the borrow-clean subset? Gated into TRADABLE_* verdicts.

A bucket (asset_class, deviation_class, drive_class, regime) earns TRADABLE_BULL/
TRADABLE_BEAR only if mean T+20 forward return on the borrow-clean subset is
material (|mean| >= sep_threshold), n >= min_n, and survives the per-TIME-WINDOW
catastrophic-degradation gate. Otherwise NONE. NONE/absent => NEUTRAL lean.

Forward horizons are TRADING-day offsets (the nth row after the anchor in the
per-ticker trading series), NOT calendar days.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from typing import Any

from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

HORIZON = 20  # trading days for the canonical separation horizon


def _forward_value_at(
    series: list[tuple[_date, float]], anchor: _date, n: int
) -> float | None:
    """nth TRADING-day-ahead value: the (n-1)th element strictly after `anchor`
    in the ASC per-ticker trading series. None if fewer than n forward rows."""
    fwd = [v for (d, v) in series if d > anchor]
    if len(fwd) < n:
        return None
    return fwd[n - 1]


def _confidence(n: int, sep: float) -> str:
    if n >= 60 and abs(sep) >= 0.02:
        return "high"
    if n >= 25 and abs(sep) >= 0.01:
        return "med"
    return "low"


def run_skew_markout(
    *, repo: Repository, min_n: int = 20, sep_threshold: float = 0.01
) -> dict[str, Any]:
    """Score all snapshots and (re)write the verdict store. Idempotent."""
    snaps = _all_snapshots(repo)
    tickers = {s["ticker"] for s in snaps}
    price_by_ticker = {t: _price_series(repo, t) for t in tickers}
    rr_by_ticker = {t: _rr_series(repo, t) for t in tickers}

    buckets: dict[tuple, list[dict]] = defaultdict(list)  # directional (gated)
    meanrev: dict[tuple, list[float]] = defaultdict(list)  # primary (reported)
    for s in snaps:
        spot = s.get("spot")
        if spot is not None and float(spot) != 0:
            fwd_px = _forward_value_at(
                price_by_ticker.get(s["ticker"], []), s["market_date"], HORIZON
            )
            if fwd_px is not None:
                key = (s["asset_class"], s["deviation_class"], s["drive_class"], s["regime"])
                buckets[key].append({
                    "fwd": fwd_px / float(spot) - 1.0,
                    "clean": s.get("borrow_flag") != "hard_to_borrow",
                    "market_date": s["market_date"],
                })
        rr0 = s.get("rr_25d")
        if rr0 is not None:
            fwd_rr = _forward_value_at(
                rr_by_ticker.get(s["ticker"], []), s["market_date"], HORIZON
            )
            if fwd_rr is not None:
                meanrev[(s["asset_class"], s["deviation_class"])].append(
                    fwd_rr - float(rr0)
                )

    today = _date.today()
    written = 0
    for key, obs in buckets.items():
        asset_class, deviation_class, drive_class, regime = key
        clean = [o for o in obs if o["clean"]]
        n = len(clean)
        sep = sum(o["fwd"] for o in clean) / n if n else 0.0
        survives = _survives_window_gate(clean, sep)
        material = n >= min_n and abs(sep) >= sep_threshold and survives
        if material and sep < 0:
            verdict = "TRADABLE_BEAR"
        elif material and sep > 0:
            verdict = "TRADABLE_BULL"
        else:
            verdict = "NONE"
        repo.upsert_skew_directional_verdict(
            asset_class=asset_class, deviation_class=deviation_class,
            drive_class=drive_class, regime=regime, verdict=verdict,
            confidence=_confidence(n, sep) if verdict != "NONE" else "low",
            forward_sep=sep, n=n, borrow_clean=True, survives_gate=survives, as_of=today,
        )
        written += 1

    mean_reversion = {
        f"{a}/{d}": {"mean_dRR": (sum(v) / len(v) if v else None), "n": len(v)}
        for (a, d), v in meanrev.items()
    }
    repo.conn.commit()
    log.info("run_skew_markout wrote %d verdicts over %d snapshots", written, len(snaps))
    return {
        "verdicts_written": written,
        "snapshots": len(snaps),
        "mean_reversion": mean_reversion,  # PRIMARY hypothesis, descriptive
    }


def _survives_window_gate(clean: list[dict], overall_sep: float) -> bool:
    """Per-TIME-WINDOW catastrophic-degradation gate (memory:
    feedback_per_regime_catastrophic_gate). Partition the bucket's borrow-clean
    obs by CALENDAR QUARTER; fail if any quarter reverses the aggregate sign with
    LARGER magnitude — i.e. the aggregate is hiding a sub-window blowup. (Keying
    by regime would be a no-op since the bucket is already single-regime.)"""
    if abs(overall_sep) < 1e-9:
        return False
    by_q: dict[tuple, list[float]] = defaultdict(list)
    for o in clean:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o["fwd"])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_sep < 0 and abs(m) > abs(overall_sep):
            return False
    return True


def _all_snapshots(repo: Repository) -> list[dict[str, Any]]:
    sql = (
        "SELECT ticker, market_date, spot, rr_25d, asset_class, deviation_class, "
        "drive_class, regime, borrow_flag "
        f"FROM {repo._schema}.skew_analytics_snapshot WHERE basis='eod'"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _price_series(repo: Repository, ticker: str) -> list[tuple[_date, float]]:
    sql = (
        "SELECT market_date, price "
        f"FROM {repo._schema}.realized_volatility_history "
        "WHERE ticker=%s AND price IS NOT NULL ORDER BY market_date ASC"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def _rr_series(repo: Repository, ticker: str) -> list[tuple[_date, float]]:
    """Front-expiry RR series (DISTINCT ON market_date) for forward-dRR mean-reversion."""
    sql = (
        "SELECT DISTINCT ON (market_date) market_date, risk_reversal "
        f"FROM {repo._schema}.risk_reversal_skew_history "
        "WHERE ticker=%s AND delta=25 AND risk_reversal IS NOT NULL "
        "ORDER BY market_date ASC, expiry ASC NULLS LAST"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        return [(r[0], float(r[1])) for r in cur.fetchall()]
```

> `repo._schema` is the standard way mixins reference the schema; reading it here in a batch analytical pass is acceptable (the alternative is threading the schema through every call). If a linter objects, add `fetch_all_skew_snapshots()` / `fetch_price_series()` / `fetch_front_rr_series()` to `_SkewMixin` and call those instead.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/reports/test_skew_markout.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/skew_markout.py tests/integration/reports/test_skew_markout.py
git commit -m "feat(skew): Tier-1 markout harness + per-bucket verdict writer"
```

---

# Milestone F — Frontend

### Task F1: api.ts method + TabBar + route wiring

**Files:**
- Modify: `web/lib/api.ts`, `web/components/stock/TabBar.tsx`, `web/app/stock/[ticker]/[tab]/page.tsx`

- [ ] **Step 1: Add the api.ts type + method + export**

In `web/lib/api.ts`, add the type alias near `VolatilitySeriesResponse` (line ~47):

```typescript
type SkewAnalysisResponse = Json<"/api/stock/{ticker}/skew", "get">;
```

Add the method inside `export const api = {` right after `volatilitySeries` (line ~118):

```typescript
  skewAnalysis: (ticker: string): Promise<SkewAnalysisResponse> =>
    _fetch<SkewAnalysisResponse>(`/api/stock/${ticker}/skew`),
```

Add `SkewAnalysisResponse,` to the bottom `export type { ... }` block (line ~290, alphabetical with the others):

```typescript
  SkewAnalysisResponse,
```

- [ ] **Step 2: Add the TabBar entry**

In `web/components/stock/TabBar.tsx`, insert `["skew", "Skew"]` between volatility and flow:

```typescript
const TABS = [
  ["market-structure", "Market Structure"],
  ["volatility", "Volatility"],
  ["skew", "Skew"],
  ["flow", "Flow"],
  ["trade-insights", "Trade Insights"],
  ["trade-plan", "Trade Plan"],
] as const;
```

- [ ] **Step 3: Wire the route**

In `web/app/stock/[ticker]/[tab]/page.tsx`, import the tab (with the other tab imports near the top):

```typescript
import { SkewTab } from "@/components/stock/tabs/SkewTab";
```

Add it to `REPORT_TABS` after `volatility`:

```typescript
const REPORT_TABS = {
  "market-structure": MarketStructureTab,
  volatility: VolatilityTab,
  skew: SkewTab,
  flow: FlowTab,
} as const;
```

- [ ] **Step 4: Typecheck (will fail until SkewTab exists — expected)**

Run: `cd web && npm run typecheck`
Expected: error that `@/components/stock/tabs/SkewTab` is not found — proceed to F2 which creates it. (Do not commit until F2 lands.)

---

### Task F2: SkewTab RSC + client island + panels

**Files:**
- Create: `web/components/stock/tabs/SkewTab.tsx`, `SkewTabClient.tsx`
- Create: panels `SkewPostureTiles.tsx`, `SkewHistoryChart.tsx`, `SkewRhoPanel.tsx`, `SkewTermPanel.tsx`, `SkewClassSpectrum.tsx`, `SkewReadPanel.tsx`
- Test: `web/tests/unit/SkewReadPanel.test.tsx`, `web/tests/unit/SkewPostureTiles.test.tsx`

- [ ] **Step 1: RSC wrapper `SkewTab.tsx`**

```tsx
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

import { SkewTabClient } from "./SkewTabClient";

type Report = components["schemas"]["SingleStockReport"];

export async function SkewTab({ report }: { report: Report }) {
  const initial = await api.skewAnalysis(report.ticker);
  return <SkewTabClient ticker={report.ticker} initial={initial} />;
}
```

- [ ] **Step 2: `SkewReadPanel.tsx` (The Read + Directional Lean block)**

```tsx
"use client";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Lean = {
  lean: string;
  confidence: string;
  basis: string;
  express: string;
};
type Read = {
  summary_line: string;
  class_context: string;
  borrow_context: string;
  earnings_gate: string;
  directional_lean: Lean;
};

function leanColor(lean: string): string {
  if (lean === "BULLISH_TILT") return "var(--positive)";
  if (lean === "BEARISH_TILT") return "var(--negative)";
  return "var(--text-muted)";
}

function leanLabel(lean: string): string {
  if (lean === "BULLISH_TILT") return "BULLISH";
  if (lean === "BEARISH_TILT") return "BEARISH";
  return "NEUTRAL";
}

export function SkewReadPanel({ read }: { read: Read }) {
  const lean = read.directional_lean;
  return (
    <AnalyticalSeriesPanel title="The Read" subtitle="DETERMINISTIC">
      <div style={{ color: "var(--text-primary)", fontSize: 12, lineHeight: 1.6 }}>
        {read.summary_line}
      </div>
      <div
        style={{
          marginTop: 12,
          paddingTop: 12,
          borderTop: "1px solid var(--border-dim)",
        }}
      >
        <div
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted)",
            marginBottom: 6,
          }}
        >
          Directional Lean
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span
            style={{ fontSize: 18, fontWeight: 700, color: leanColor(lean.lean) }}
          >
            {leanLabel(lean.lean)}
          </span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            confidence: {lean.confidence}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 6 }}>
          {lean.basis}
        </div>
        {lean.express ? (
          <div style={{ fontSize: 11, color: "var(--text-primary)", marginTop: 6 }}>
            express: {lean.express}
          </div>
        ) : null}
      </div>
    </AnalyticalSeriesPanel>
  );
}
```

- [ ] **Step 3: `SkewPostureTiles.tsx`**

```tsx
"use client";

import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Posture = {
  rr_25d?: string | number | null;
  rr_z_180d?: string | number | null;
  rr_pct_252d?: string | number | null;
  deviation_class: string;
  drive_class: string;
  borrow_flag: string;
  regime: string;
};

export function deviationColor(cls: string): string {
  if (cls === "RICH") return "var(--warning)";
  if (cls === "CHEAP") return "var(--positive)";
  return "var(--text-primary)";
}

const tile: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: "12px 14px",
  display: "flex",
  flexDirection: "column",
  gap: 6,
};
const label: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};
const value: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontWeight: 700,
  fontSize: 22,
  color: "var(--text-primary)",
  lineHeight: 1,
};

export function SkewPostureTiles({ p }: { p: Posture }) {
  const rr = toNum(p.rr_25d);
  const z = toNum(p.rr_z_180d);
  const pct = toNum(p.rr_pct_252d);
  return (
    <AnalyticalSeriesPanel title="Posture" subtitle="VS OWN BASELINE">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 10,
        }}
      >
        <div style={tile}>
          <div style={label}>RR 25Δ</div>
          <div style={value}>{rr != null ? fmtSigned(rr, 4) : "—"}</div>
          <div style={label}>put−call IV</div>
        </div>
        <div style={tile}>
          <div style={label}>Deviation</div>
          <div style={{ ...value, color: deviationColor(p.deviation_class) }}>
            {p.deviation_class}
          </div>
          <div style={label}>
            z {z != null ? fmtSigned(z, 2) : "—"} · pct{" "}
            {pct != null ? fmtDecimal(pct, 0) : "—"}
          </div>
        </div>
        <div style={tile}>
          <div style={label}>Drive</div>
          <div style={value}>{p.drive_class}</div>
          <div style={label}>regime {p.regime}</div>
        </div>
        <div style={tile}>
          <div style={label}>Borrow</div>
          <div style={value}>{p.borrow_flag}</div>
          <div style={label}>JFE confound gate</div>
        </div>
      </div>
    </AnalyticalSeriesPanel>
  );
}
```

- [ ] **Step 4: `SkewHistoryChart.tsx`, `SkewRhoPanel.tsx`, `SkewTermPanel.tsx`, `SkewClassSpectrum.tsx`**

`SkewHistoryChart.tsx` (RR series + "you are here" marker):

```tsx
"use client";

import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import { toNum } from "@/lib/formatters";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Pt = { date: string; rr?: string | number | null; pct?: string | number | null };

export function SkewHistoryChart({ data }: { data: Pt[] }) {
  const vals = data.map((d) => toNum(d.rr)).filter((v): v is number => v != null);
  const dom = finiteDomain(vals);
  const curPct = data.length ? toNum(data[data.length - 1].pct) : null;
  const headline = curPct != null ? `${Math.round(curPct)}th pct` : undefined;
  if (!dom || data.length < 2) {
    return (
      <AnalyticalSeriesPanel title="Skew History" subtitle="RR vs TIME">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient skew history
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400;
  const H = 200;
  const M = { top: 8, right: 12, bottom: 20, left: 36 };
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const y = linearScale([dom.lo, dom.hi], [H - M.bottom, M.top]);
  const pts = data
    .map((d, i) => {
      const v = toNum(d.rr);
      return v == null ? null : { x: x(i), y: y(v) };
    })
    .filter((p): p is { x: number; y: number } => p != null);
  const last = pts[pts.length - 1];
  return (
    <AnalyticalSeriesPanel title="Skew History" subtitle="RR vs TIME" headline={headline}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <title>Risk-reversal skew over time with current marker</title>
        <line
          x1={M.left}
          x2={W - M.right}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--border-dim)"
        />
        <path d={pathFromPoints(pts)} fill="none" stroke="var(--accent-bg)" />
        {last ? <circle cx={last.x} cy={last.y} r={3} fill="var(--accent-vivid)" /> : null}
      </svg>
    </AnalyticalSeriesPanel>
  );
}
```

`SkewRhoPanel.tsx`:

```tsx
"use client";

import { fmtSigned, toNum } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type RhoPt = { date: string; rho?: string | number | null };

export function SkewRhoPanel({
  rho63,
  rho21,
  series = [],
}: {
  rho63?: string | number | null;
  rho21?: string | number | null;
  series?: RhoPt[];
}) {
  const r63 = toNum(rho63);
  const r21 = toNum(rho21);
  const color = (v: number | null) =>
    v == null ? "var(--text-muted)" : v < 0 ? "var(--negative)" : "var(--positive)";
  const vals = series.map((p) => toNum(p.rho)).filter((v): v is number => v != null);
  const dom = finiteDomain(vals.length ? [...vals, -1, 1] : []);
  let spark = null;
  if (dom && series.length >= 2) {
    const W = 320;
    const H = 56;
    const x = linearScale([0, series.length - 1], [2, W - 2]);
    const y = linearScale([dom.lo, dom.hi], [H - 4, 4]);
    const pts = series
      .map((p, i) => {
        const v = toNum(p.rho);
        return v == null ? null : { x: x(i), y: y(v) };
      })
      .filter((p): p is { x: number; y: number } => p != null);
    spark = (
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <title>Spot-vol ρ (63d) over time</title>
        <line x1={2} x2={W - 2} y1={y(0)} y2={y(0)} stroke="var(--border-dim)" />
        <path d={pathFromPoints(pts)} fill="none" stroke="var(--accent-vol)" />
      </svg>
    );
  }
  return (
    <AnalyticalSeriesPanel title="Spot-Vol ρ" subtitle="PANIC vs CHASE">
      <div style={{ display: "flex", gap: 24 }}>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>63d</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: color(r63) }}>
            {r63 != null ? fmtSigned(r63, 2) : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "var(--text-muted)" }}>21d</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: color(r21) }}>
            {r21 != null ? fmtSigned(r21, 2) : "—"}
          </div>
        </div>
      </div>
      {spark}
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 8 }}>
        ρ&lt;0 → vol rises as spot falls (hedging fear). ρ&gt;0 → chase.
      </div>
    </AnalyticalSeriesPanel>
  );
}
```

`SkewTermPanel.tsx`:

```tsx
"use client";

import { fmtSigned, toNum } from "@/lib/formatters";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export function SkewTermPanel({
  termClass,
  frontRr,
  backRr,
}: {
  termClass: string;
  frontRr?: string | number | null;
  backRr?: string | number | null;
}) {
  const f = toNum(frontRr);
  const b = toNum(backRr);
  return (
    <AnalyticalSeriesPanel title="Skew Term" subtitle="FRONT vs BACK">
      {b == null ? (
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Single expiry on file — term structure unavailable ({termClass}).
        </div>
      ) : (
        <div style={{ display: "flex", gap: 24, fontFamily: "var(--font-mono)" }}>
          <div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>FRONT</div>
            <div style={{ fontSize: 18 }}>{f != null ? fmtSigned(f, 4) : "—"}</div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>BACK</div>
            <div style={{ fontSize: 18 }}>{fmtSigned(b, 4)}</div>
          </div>
          <div>
            <div style={{ fontSize: 10, color: "var(--text-muted)" }}>CLASS</div>
            <div style={{ fontSize: 18 }}>{termClass}</div>
          </div>
        </div>
      )}
    </AnalyticalSeriesPanel>
  );
}
```

`SkewClassSpectrum.tsx`:

```tsx
"use client";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

export function SkewClassSpectrum({
  assetClass,
  expectedSign,
  actualSign,
}: {
  assetClass: string;
  expectedSign: string;
  actualSign: string; // put_skew | call_skew | flat | unknown (from rr_25d sign)
}) {
  const matches = expectedSign === actualSign || expectedSign === "mixed";
  return (
    <AnalyticalSeriesPanel title="Asset Class" subtitle="WHERE IT SITS">
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <span style={{ color: "var(--accent-bg)", fontWeight: 700 }}>
          {assetClass}
        </span>
        <span style={{ color: "var(--text-muted)" }}> — expected {expectedSign}</span>
        <span
          style={{
            color: matches ? "var(--text-secondary)" : "var(--warning)",
            marginLeft: 8,
          }}
        >
          · actual {actualSign}
          {matches ? "" : " (divergent)"}
        </span>
      </div>
    </AnalyticalSeriesPanel>
  );
}
```

- [ ] **Step 5: `SkewTabClient.tsx` (orchestrates panels)**

```tsx
"use client";

import { useState } from "react";

import type { SkewAnalysisResponse } from "@/lib/api";
import { toNum } from "@/lib/formatters";

import { SmileChart } from "../panels/SmileChart";
import { SkewClassSpectrum } from "../panels/SkewClassSpectrum";
import { SkewHistoryChart } from "../panels/SkewHistoryChart";
import { SkewPostureTiles } from "../panels/SkewPostureTiles";
import { SkewReadPanel } from "../panels/SkewReadPanel";
import { SkewRhoPanel } from "../panels/SkewRhoPanel";
import { SkewTermPanel } from "../panels/SkewTermPanel";

function actualSign(rr: string | number | null | undefined): string {
  const v = toNum(rr);
  if (v == null) return "unknown";
  if (v > 1e-6) return "put_skew";
  if (v < -1e-6) return "call_skew";
  return "flat";
}

export function SkewTabClient({
  ticker,
  initial,
}: {
  ticker: string;
  initial: SkewAnalysisResponse;
}) {
  const [data] = useState(initial);
  if (data.backfill_status === "empty") {
    return (
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        No skew history for {ticker} yet.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <SkewPostureTiles
        p={{
          rr_25d: data.rr_25d,
          rr_z_180d: data.rr_z_180d,
          rr_pct_252d: data.rr_pct_252d,
          deviation_class: data.deviation_class,
          drive_class: data.drive_class,
          borrow_flag: data.borrow_flag,
          regime: data.regime,
        }}
      />
      <SkewReadPanel read={data.read} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
        }}
      >
        <SkewHistoryChart data={data.history} />
        <SkewRhoPanel
          rho63={data.rho_spotvol_63d}
          rho21={data.rho_spotvol_21d}
          series={data.rho_series}
        />
        <SkewTermPanel
          termClass={data.skew_term_class}
          frontRr={data.front_rr}
          backRr={data.back_rr}
        />
        <SkewClassSpectrum
          assetClass={data.asset_class}
          expectedSign={data.class_expected_sign}
          actualSign={actualSign(data.rr_25d)}
        />
      </div>
      <SmileChart data={data.smile} spot={data.spot} />
    </div>
  );
}
```

> `SmileChart`'s prop type is `SmileExpiryCurve[]` (strike/iv points). Our `data.smile` is `SkewSmileExpiryCurve[]` with the same `{expiry, points:[{strike, iv}]}` shape, so it is structurally compatible. If TS complains about the nominal type, map it: `data.smile.map((c) => ({ expiry: c.expiry, points: c.points }))`.

- [ ] **Step 6: Write vitest unit tests**

`web/tests/unit/SkewReadPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SkewReadPanel } from "@/components/stock/panels/SkewReadPanel";

const base = {
  summary_line: "RICH put-skew",
  class_context: "single_name (expected mixed)",
  borrow_context: "normal",
  earnings_gate: "pass",
};

describe("SkewReadPanel", () => {
  it("renders a bearish lean with confidence and express", () => {
    render(
      <SkewReadPanel
        read={{
          ...base,
          directional_lean: {
            lean: "BEARISH_TILT",
            confidence: "med",
            basis: "validated — separated -2.1%/20d",
            express: "put-debit-spread",
          },
        }}
      />,
    );
    expect(screen.getByText("BEARISH")).toBeTruthy();
    expect(screen.getByText(/confidence: med/)).toBeTruthy();
    expect(screen.getByText(/put-debit-spread/)).toBeTruthy();
  });

  it("renders NEUTRAL with its reason and no express line", () => {
    render(
      <SkewReadPanel
        read={{
          ...base,
          directional_lean: {
            lean: "NEUTRAL",
            confidence: "low",
            basis: "no proven separation for this bucket yet",
            express: "",
          },
        }}
      />,
    );
    expect(screen.getByText("NEUTRAL")).toBeTruthy();
    expect(screen.getByText(/no proven separation/)).toBeTruthy();
    expect(screen.queryByText(/express:/)).toBeNull();
  });
});
```

`web/tests/unit/SkewPostureTiles.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";

import { deviationColor } from "@/components/stock/panels/SkewPostureTiles";

describe("deviationColor", () => {
  it("maps RICH/CHEAP/NORMAL to tokens", () => {
    expect(deviationColor("RICH")).toBe("var(--warning)");
    expect(deviationColor("CHEAP")).toBe("var(--positive)");
    expect(deviationColor("NORMAL")).toBe("var(--text-primary)");
  });
});
```

- [ ] **Step 7: Typecheck + unit tests**

Run: `cd web && npm run typecheck && npm run test -- SkewReadPanel SkewPostureTiles`
Expected: typecheck clean; both unit suites PASS.

- [ ] **Step 8: Commit**

```bash
git add web/lib/api.ts web/components/stock/TabBar.tsx "web/app/stock/[ticker]/[tab]/page.tsx" web/components/stock/tabs/SkewTab.tsx web/components/stock/tabs/SkewTabClient.tsx web/components/stock/panels/Skew*.tsx web/tests/unit/SkewReadPanel.test.tsx web/tests/unit/SkewPostureTiles.test.tsx
git commit -m "feat(skew): Skew tab UI — posture, read+lean, history, rho, term, class"
```

---

# Milestone G — Local data prep, E2E, verification

### Task G1: Backfill local snapshots + run markout (real worker path)

**Files:** none (operational — uses the real job functions, not a side-channel)

- [ ] **Step 1: Backfill snapshots over the on-disk history**

Run (one-off driver using the real job + repo, mirroring `scheduler._repo`):

```bash
uv run python -c "
from datetime import date
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
import psycopg
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    repo = Repository(conn, schema=s.db_schema)
    from uw_scan.worker.jobs.skew_analytics import skew_analytics_backfill
    n = skew_analytics_backfill(repo=repo, start=date(2025,6,1), end=date(2026,6,11))
    print('snapshots written:', n)
"
```

> `Settings.from_env()` is the project accessor; `db_dsn()` is a **method** (call it) and `db_schema` is the schema attr — verified against `worker/scheduler.py::_repo`. Do NOT hand-build a DSN with secrets inline.

Expected: prints a non-zero snapshot count.

- [ ] **Step 2: Run the markout to populate verdicts**

```bash
uv run python -c "
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.reports.skew_markout import run_skew_markout
import psycopg
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    repo = Repository(conn, schema=s.db_schema)
    print(run_skew_markout(repo=repo))
"
```

Expected: prints `{'verdicts_written': N, 'snapshots': M, 'mean_reversion': {...}}` with M>0.

- [ ] **Step 2b: Re-run the rollup so persisted leans pick up the new verdicts (C-2)**

The backfill in Step 1 wrote snapshots before any verdicts existed, so their persisted `directional_lean` is `NEUTRAL`. The markout (Step 2) wrote verdicts but does not rewrite snapshots. Re-run the nightly rollup once so each ticker's **latest** snapshot recomputes its lean against the now-present verdicts. (The endpoint recomputes the lean live on every request, so the UI is correct regardless — this step only refreshes the persisted cache that Step 3 inspects.)

```bash
uv run python -c "
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.skew_analytics import nightly_skew_analytics_rollup
import psycopg
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    repo = Repository(conn, schema=s.db_schema)
    nightly_skew_analytics_rollup(repo=repo)
    print('rollup complete')
"
```

Expected: prints `rollup complete`.

- [ ] **Step 3: Verify snapshots + at least one ticker's lean**

Run: `psql -h 127.0.0.1 -p 5432 -U chenxi -d option_wizard_local -c "SELECT ticker, deviation_class, directional_lean, regime FROM uw_scan.skew_analytics_snapshot WHERE market_date=(SELECT max(market_date) FROM uw_scan.skew_analytics_snapshot) ORDER BY ticker LIMIT 20;"`
Expected: rows with deviation_class ∈ {RICH,CHEAP,NORMAL} and directional_lean ∈ {BULLISH_TILT,BEARISH_TILT,NEUTRAL}. Most will be NEUTRAL (safe default) — that is correct.

- [ ] **Step 4: Write the Tier-1 research note (spec §7 step 5)**

Query the verdict distribution and write `docs/research/skew-first-principles-markout-2026-06.md` summarizing: how many buckets earned `TRADABLE_*` vs `NONE`, the forward-separation magnitudes, n per bucket, and the explicit statement that the read engine's directional lean is gated to these verdicts (relative-value body stays interpretive). Pull the numbers from:

Run: `psql -h 127.0.0.1 -p 5432 -U chenxi -d option_wizard_local -c "SELECT verdict, count(*), round(avg(forward_sep)::numeric,4) avg_sep, round(avg(n)::numeric,1) avg_n FROM uw_scan.skew_directional_verdicts GROUP BY verdict ORDER BY verdict;"`

The note records the empirical finding (most single-name buckets do not separate after borrow-cleaning, per Muravyev-Pearson-Pollet) and any bucket that did. Do not fabricate numbers — transcribe the query output. This file is documentation, not committed via the per-milestone commits; include it in the final hand-off.

---

### Task G2: Start local stack + Playwright e2e

**Files:**
- Create: `web/tests/e2e/skew-tab.spec.ts`

- [ ] **Step 1: Write the e2e spec**

```typescript
import { expect, test } from "@playwright/test";

// Pick a ticker known to have skew history locally (verify with the query in G1/Step 3).
const TICKER = "AAPL";

test("Skew tab renders posture, the read, and a directional lean", async ({ page }) => {
  await page.goto(`/stock/${TICKER}/skew`);
  // tab is present and active
  await expect(page.getByRole("link", { name: "Skew" })).toBeVisible();
  // posture panel
  await expect(page.getByText("VS OWN BASELINE")).toBeVisible();
  // the read + directional lean block
  await expect(page.getByText("Directional Lean")).toBeVisible();
  // lean badge is one of the three states
  const lean = page.locator("text=/^(BULLISH|BEARISH|NEUTRAL)$/").first();
  await expect(lean).toBeVisible();
});
```

- [ ] **Step 2: Start the local stack**

Run (background): `bash scripts/dev.sh`
Wait for: API on :8400 and web on :3001 healthy.
Verify API: `curl -s localhost:8400/api/stock/AAPL/skew | head -c 300` → JSON with `"ticker":"AAPL"`.

- [ ] **Step 3: Run the e2e**

Run: `cd web && npx playwright test skew-tab --reporter=line`
Expected: PASS.

- [ ] **Step 4: Capture a screenshot as evidence**

Run: `cd web && npx playwright test skew-tab --reporter=line` with a `page.screenshot({ path: "output/playwright/skew-tab-AAPL.png", fullPage: true })` added to the spec (per repo rule, artifacts go under `output/playwright/`).
Expected: `output/playwright/skew-tab-AAPL.png` exists and visually shows the posture tiles + The Read + a lean badge.

- [ ] **Step 5: Full targeted test sweep**

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py tests/unit/reports/test_skew_snapshot_row.py tests/integration/storage/test_skew_storage.py tests/integration/api/test_skew.py tests/integration/worker/test_skew_jobs.py tests/integration/reports/test_skew_markout.py -q`
Run: `cd web && npm run typecheck && npm run test`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add web/tests/e2e/skew-tab.spec.ts
git commit -m "test(skew): playwright e2e for the Skew tab"
```

---

## Self-review checklist (run before handing off)

- [ ] **Spec coverage:** §1 goal (evidence-gated lean) → B3/C2; §2 evidence → embedded in read text; §3 ideas → posture+read+express; §4 data → reuse existing reads (A2/C2); §5 architecture → A–F; §6 persistence → A1/A2; §7 Tier-1 validation → E1; §9 testing → every task's tests; §10 defaults → constants in derivers; §11 risks → sign guard (B2), verdict-absent→NEUTRAL (B3), borrow/earnings gates (B3).
- [ ] **No placeholders:** every code step is complete and runnable.
- [ ] **Name consistency:** `resolve_directional_lean`, `build_skew_snapshot_row`, `skew_analytics_snapshot`, `skew_directional_verdicts`, `directional_lean`/`lean_confidence`/`lean_basis`, `BULLISH_TILT|BEARISH_TILT|NEUTRAL`, `TRADABLE_BULL|TRADABLE_BEAR|NONE` — identical across all tasks.
- [ ] **Standing rules:** uv-only; idempotent migration; persist to Postgres; no naked shorts (express structures are defined-risk only); explicit `git add` paths; no secrets in the one-off drivers; artifacts under `output/playwright/`.
```
