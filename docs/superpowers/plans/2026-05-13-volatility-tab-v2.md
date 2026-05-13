# Volatility Tab v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the per-stock Volatility and VRP tabs into a single richer Volatility tab — header metrics card + 2×2 primary chart grid + 2×2 analytical row + full-width VRP spread panel — with all derived series persisted to Postgres.

**Architecture:** Backend gets one new migration (4 tables), four pandas-based derivers (VRP, IV-of-IV, RVOL/percentile, stock-SPY correlation), a one-shot SPY OHLC seed script, two new worker jobs, and one new FastAPI endpoint (`GET /api/stock/{ticker}/volatility/series`) that returns everything the tab needs and triggers a background backfill on first request via a `backfill_status` field. Frontend gets one shared `AnalyticalSeriesPanel.tsx` SVG-chart primitive (matching the existing hand-rolled `GexProfileChart.tsx` style — no chart library is added) plus nine focused panel components composed by a rewritten `VolatilityTab.tsx`; the `Vrp` tab is removed.

**Tech Stack:** Python 3.13 + `uv` + FastAPI + psycopg + pandas (already a transitive); Postgres `option_wizard` schema `uw_scan`; Next.js 16 + React 19 + TypeScript (server components by default, hand-rolled SVG for charts); pytest + vitest + @testing-library/react.

**Spec:** `docs/superpowers/specs/2026-05-13-volatility-tab-v2-design.md`

---

## File structure

### New backend files

| Path | Responsibility |
|---|---|
| `src/uw_scan/storage/migrations/014_volatility_v2_tables.sql` | DDL for `index_ohlc_daily`, `iv_smile_snapshots`, `vrp_daily`, `stock_analytics_daily` |
| `src/uw_scan/cards/vol_series.py` | Pure pandas math: `compute_vrp_series`, `compute_iv_of_iv`, `compute_rvol_and_percentile`, `compute_stock_spy_corr`, `classify_regime_state` |
| `src/uw_scan/reports/volatility_series.py` | Orchestrator: read raw IV/RV/SPY from repo → call deriver functions → upsert derived rows → assemble response dict |
| `src/uw_scan/api/routers/volatility.py` | `GET /api/stock/{ticker}/volatility/series` endpoint, kicks off backfill via `BackgroundTasks` |
| `scripts/seed_spy_ohlc.py` | One-shot CLI: pull ~3y SPY daily via `MassiveOhlcProvider`, upsert into `index_ohlc_daily` |

### Modified backend files

| Path | What changes |
|---|---|
| `src/uw_scan/models.py` | Add `VolatilitySeriesResponse` + sub-models (`VolHeaderBlock`, `TermStructurePoint`, `SmilePoint`, `IvHvPoint`, `VrpDailyPoint`, `RegimeQuadrantPoint`, `RegimeQuadrantLatest`, `DivergencePoint`) |
| `src/uw_scan/storage/repository.py` | Add: `upsert_index_ohlc_rows`, `fetch_index_ohlc_series`, `upsert_iv_smile_rows`, `fetch_iv_smile_latest`, `upsert_vrp_daily_rows`, `fetch_vrp_daily_series`, `upsert_stock_analytics_rows`, `fetch_stock_analytics_series`, `count_realized_vol_history`, `fetch_realized_vol_history`, `fetch_volatility_stats_history` |
| `src/uw_scan/api/server.py` | Mount the new `volatility` router |
| `src/uw_scan/worker/scheduler.py` (or current entry) | Register `daily_spy_ohlc_refresh` (16:30 ET) and `nightly_vol_analytics_rollup` (18:00 ET) jobs |
| `src/uw_scan/sources/uw.py` | No change (existing `fetch_realized_volatility` + `fetch_skew` already return history) |

### New frontend files

| Path | Responsibility |
|---|---|
| `web/components/stock/panels/AnalyticalSeriesPanel.tsx` | Shared chart shell: uppercase mono header, optional subheader, dark `--bg-panel`, headline value slot |
| `web/components/stock/panels/VolMetricsCard.tsx` | Header metrics grid (Row 1 + Row 2) + VRP badge + note |
| `web/components/stock/panels/TermStructureChart.tsx` | IV-by-DTE line chart, 4 strike lines |
| `web/components/stock/panels/SmileChart.tsx` | IV-by-strike line chart, 4 expiry lines |
| `web/components/stock/panels/HvIvChart.tsx` | Daily IV + RV time series, last 365d |
| `web/components/stock/panels/IvPercentileDistribution.tsx` | Histogram of IV with current-IV marker |
| `web/components/stock/panels/IvOfIvChart.tsx` | Dual-axis: IV (left) + IV-of-IV (right) |
| `web/components/stock/panels/RvSpyCorrChart.tsx` | Dual-axis: RV (left) + SPY-corr-21 (right) |
| `web/components/stock/panels/RegimeQuadrantChart.tsx` | 20-session scatter w/ 4 quadrant labels + state-key tiles |
| `web/components/stock/panels/DivergenceOverlay.tsx` | IV-z + RV-z 20-session lines + headline σ |
| `web/components/stock/panels/VrpSpreadPanel.tsx` | Full-width bars (raw VRP) + smoothed-line overlay + headline |
| `web/lib/svgChart.ts` | Tiny shared helpers: `linearScale`, `pathFromPoints`, `niceTicks` |
| `web/tests/components/volatility/*.test.tsx` | One file per panel, snapshot-style |

### Modified frontend files

| Path | What changes |
|---|---|
| `web/components/stock/TabBar.tsx` | Remove `["vrp", "VRP"]` |
| `web/app/stock/[ticker]/[tab]/page.tsx` | Drop `vrp` case from tab-component switch |
| `web/components/stock/tabs/VolatilityTab.tsx` | Rewritten to compose new panels |
| `web/components/stock/tabs/VrpTab.tsx` | **DELETE** |
| `web/lib/api.ts` | Add `api.volatilitySeries(ticker)` helper |
| `web/app/globals.css` | Add `--accent-vol`, `--accent-warm`, `--accent-vivid` tokens |

---

## Phase 0 — Migration & deps

### Task 0.1: Create migration `014_volatility_v2_tables.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/014_volatility_v2_tables.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 014_volatility_v2_tables.sql — added by Volatility Tab v2.
-- See docs/superpowers/specs/2026-05-13-volatility-tab-v2-design.md §4.2.

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.index_ohlc_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC NOT NULL,
    volume      BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMENT ON TABLE uw_scan.index_ohlc_daily
    IS 'Daily OHLC for benchmark tickers (SPY, sector ETFs). Seeded by scripts/seed_spy_ohlc.py.';

CREATE TABLE IF NOT EXISTS uw_scan.iv_smile_snapshots (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    expiry      DATE NOT NULL,
    strike      NUMERIC NOT NULL,
    iv          NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date, expiry, strike)
);

COMMENT ON TABLE uw_scan.iv_smile_snapshots
    IS 'Per-strike IV by expiry — source for the smile chart. Derived from greeks endpoint.';

CREATE TABLE IF NOT EXISTS uw_scan.vrp_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    iv          NUMERIC,
    rv          NUMERIC,
    vrp         NUMERIC,
    vrp_z_20    NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

CREATE TABLE IF NOT EXISTS uw_scan.stock_analytics_daily (
    ticker      TEXT NOT NULL,
    market_date DATE NOT NULL,
    rvol_21     NUMERIC,
    rvol_pctile NUMERIC,
    spy_corr_21 NUMERIC,
    iv_of_iv_20 NUMERIC,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, market_date)
);

COMMIT;
```

- [ ] **Step 2: Apply migration to dev DB**

Run: `uv run python -m uw_scan.storage.migrations.runner` (or whatever invocation the README documents; if unsure run `grep -R "migrations" scripts/ src/uw_scan/storage/ | head -20` first).

Expected: command exits 0; `psql option_wizard -c "\dt uw_scan.*" | grep -E 'index_ohlc_daily|iv_smile_snapshots|vrp_daily|stock_analytics_daily'` lists all four.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/migrations/014_volatility_v2_tables.sql
git commit -m "migration: 014 volatility v2 tables (index_ohlc_daily, iv_smile_snapshots, vrp_daily, stock_analytics_daily)"
```

---

### Task 0.2: Add `pandas` to dependencies if not present

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Check if pandas is already a direct dep**

Run: `grep -E '^\s*"?pandas' pyproject.toml`
Expected: either prints a line (skip rest of task), or empty.

- [ ] **Step 2: If missing, add `pandas>=2.2`**

Edit `pyproject.toml`'s `dependencies` list; insert `"pandas>=2.2",` alphabetically.

- [ ] **Step 3: Sync deps**

Run: `uv sync`
Expected: exit 0, lockfile updates.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add pandas for vol-series derivers"
```

(If pandas was already present, skip the commit and note "no changes".)

---

### Task 0.3: Add new CSS color tokens

**Files:**
- Modify: `web/app/globals.css`

- [ ] **Step 1: Locate the `:root` token block**

Run: `grep -n -- '--accent-bg' web/app/globals.css | head -3`
Expected: a `:root { … }` block with existing accent vars.

- [ ] **Step 2: Add three new tokens beside `--accent-bg`**

In the same `:root` rule, after the existing accent tokens, add:

```css
  --accent-vol: #8b5cf6;     /* purple — IV-of-IV */
  --accent-warm: #f59e0b;    /* orange — RV, IV-z */
  --accent-vivid: #ec4899;   /* pink — SPY-corr, RV-z */
```

- [ ] **Step 3: Commit**

```bash
git add web/app/globals.css
git commit -m "ui: add --accent-vol, --accent-warm, --accent-vivid tokens for volatility v2"
```

---

## Phase 1 — Backend models & repo helpers

### Task 1.1: Add `VolatilitySeriesResponse` Pydantic models

**Files:**
- Modify: `src/uw_scan/models.py`
- Test: `tests/test_volatility_models.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_volatility_models.py`:

```python
from datetime import date
from decimal import Decimal

from uw_scan.models import (
    DivergencePoint,
    IvHvPoint,
    RegimeQuadrantLatest,
    RegimeQuadrantPoint,
    SmileExpiryCurve,
    SmilePoint,
    TermStructureExpiryRow,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VrpDailyPoint,
)


def test_volatility_series_response_minimal():
    resp = VolatilitySeriesResponse(
        ticker="TSLA",
        as_of=date(2026, 5, 13),
        backfill_status="ready",
        header=VolHeaderBlock(
            iv=Decimal("0.53"),
            vrp_signal="BUY_VOL",
            vrp_note="IV rich vs RV",
        ),
    )
    assert resp.ticker == "TSLA"
    assert resp.backfill_status == "ready"
    # All series fields default to empty lists, not None.
    assert resp.term_structure == []
    assert resp.smile == []
    assert resp.hv_iv_history == []
    assert resp.iv_of_iv == []
    assert resp.rv_spy_corr == []
    assert resp.divergence == []
    assert resp.vrp_spread == []


def test_smile_expiry_curve():
    curve = SmileExpiryCurve(
        expiry=date(2026, 5, 15),
        points=[SmilePoint(strike=Decimal("400"), iv=Decimal("0.6"))],
    )
    assert curve.expiry == date(2026, 5, 15)
    assert len(curve.points) == 1


def test_term_structure_row_with_strike_map():
    row = TermStructureExpiryRow(
        expiry=date(2026, 5, 15),
        dte=2,
        by_strike={"ATM": Decimal("0.58"), "ATM+1": Decimal("0.54")},
    )
    assert row.by_strike["ATM"] == Decimal("0.58")


def test_iv_hv_and_vrp_and_regime_points():
    IvHvPoint(date=date(2026, 5, 13), iv=Decimal("0.5"), rv=Decimal("0.4"))
    VrpDailyPoint(date=date(2026, 5, 13), vrp=Decimal("0.1"), vrp_z_20=Decimal("0.5"))
    RegimeQuadrantPoint(
        date=date(2026, 5, 13), rvol_pctile=Decimal("45"),
        spy_corr_21=Decimal("0.3"),
    )
    RegimeQuadrantLatest(
        date=date(2026, 5, 13), rvol_pctile=Decimal("50"),
        spy_corr_21=Decimal("0.28"), state="GOLDILOCKS",
    )
    DivergencePoint(date=date(2026, 5, 13), iv_z=Decimal("0.6"), rv_z=Decimal("-0.4"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_volatility_models.py -v`
Expected: ImportError for the new model names.

- [ ] **Step 3: Implement the models**

Append to `src/uw_scan/models.py` (after `VRPAssessment`):

```python
# ---------------------------------------------------------------------------
# Volatility tab v2 — series response (see spec 2026-05-13)
# ---------------------------------------------------------------------------
class VolHeaderBlock(_UwBase):
    iv: Decimal | None = None
    rv: Decimal | None = None
    iv_rank: Decimal | None = None
    iv_rank_1y: Decimal | None = None
    iv_low_52w: Decimal | None = None
    iv_high_52w: Decimal | None = None
    rv_low_52w: Decimal | None = None
    rv_high_52w: Decimal | None = None
    iv_percentile_30d: Decimal | None = None
    implied_move_30d_perc: Decimal | None = None
    skew_25d: Decimal | None = None
    vrp: Decimal | None = None
    vrp_signal: str = ""
    vrp_note: str = ""


class TermStructureExpiryRow(_UwBase):
    expiry: _date
    dte: int | None = None
    by_strike: dict[str, Decimal] = {}  # keys: "ATM-2", "ATM-1", "ATM", "ATM+1"


class SmilePoint(_UwBase):
    strike: Decimal
    iv: Decimal | None = None


class SmileExpiryCurve(_UwBase):
    expiry: _date
    dte: int | None = None
    points: list[SmilePoint] = []


class IvHvPoint(_UwBase):
    date: _date
    iv: Decimal | None = None
    rv: Decimal | None = None


class IvHistogramBin(_UwBase):
    lo: Decimal
    hi: Decimal
    count: int


class IvPercentileDistribution(_UwBase):
    bins: list[IvHistogramBin] = []
    current_iv: Decimal | None = None
    current_pctile: Decimal | None = None


class IvOfIvPoint(_UwBase):
    date: _date
    iv: Decimal | None = None
    iv_of_iv_20: Decimal | None = None


class RvCorrPoint(_UwBase):
    date: _date
    rv: Decimal | None = None
    spy_corr_21: Decimal | None = None


class RegimeQuadrantPoint(_UwBase):
    date: _date
    rvol_pctile: Decimal | None = None
    spy_corr_21: Decimal | None = None


class RegimeQuadrantLatest(_UwBase):
    date: _date
    rvol_pctile: Decimal | None = None
    spy_corr_21: Decimal | None = None
    state: str = ""  # GOLDILOCKS | FRAGILE_CALM | STOCK_PICKER | SYSTEMIC_PANIC


class RegimeQuadrantBlock(_UwBase):
    points: list[RegimeQuadrantPoint] = []
    latest: RegimeQuadrantLatest | None = None


class DivergencePoint(_UwBase):
    date: _date
    iv_z: Decimal | None = None
    rv_z: Decimal | None = None


class VrpDailyPoint(_UwBase):
    date: _date
    vrp: Decimal | None = None
    vrp_z_20: Decimal | None = None


class VolatilitySeriesResponse(_UwBase):
    ticker: str
    as_of: _date
    backfill_status: str  # "running" | "ready" | "failed"
    header: VolHeaderBlock
    term_structure: list[TermStructureExpiryRow] = []
    smile: list[SmileExpiryCurve] = []
    hv_iv_history: list[IvHvPoint] = []
    iv_percentile_distribution: IvPercentileDistribution | None = None
    iv_of_iv: list[IvOfIvPoint] = []
    rv_spy_corr: list[RvCorrPoint] = []
    regime_quadrant: RegimeQuadrantBlock | None = None
    divergence: list[DivergencePoint] = []
    divergence_headline: str = ""
    vrp_spread: list[VrpDailyPoint] = []
    vrp_spread_headline: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_volatility_models.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/models.py tests/test_volatility_models.py
git commit -m "models: VolatilitySeriesResponse + sub-models for Volatility tab v2"
```

---

### Task 1.2: Repo helper — `upsert_index_ohlc_rows` + `fetch_index_ohlc_series`

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/test_repository_index_ohlc.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

from uw_scan.sources.ohlc import OhlcBar
from uw_scan.storage.repository import Repository


def test_upsert_and_fetch_index_ohlc(repo: Repository):
    bars = [
        OhlcBar(ticker="SPY", date=date(2026, 5, 11),
                open=Decimal("500"), high=Decimal("502"),
                low=Decimal("499"), close=Decimal("501"), volume=10_000_000),
        OhlcBar(ticker="SPY", date=date(2026, 5, 12),
                open=Decimal("501"), high=Decimal("504"),
                low=Decimal("500"), close=Decimal("503"), volume=11_000_000),
    ]
    n = repo.upsert_index_ohlc_rows(bars)
    assert n == 2

    series = repo.fetch_index_ohlc_series("SPY", start=date(2026, 5, 11),
                                          end=date(2026, 5, 12))
    assert len(series) == 2
    assert series[0]["close"] == Decimal("501")
    assert series[1]["close"] == Decimal("503")

    # Idempotent re-upsert with a new close should update.
    bars[0] = OhlcBar(ticker="SPY", date=date(2026, 5, 11),
                      open=None, high=None, low=None,
                      close=Decimal("500.50"), volume=None)
    repo.upsert_index_ohlc_rows([bars[0]])
    again = repo.fetch_index_ohlc_series("SPY", start=date(2026, 5, 11),
                                         end=date(2026, 5, 11))
    assert again[0]["close"] == Decimal("500.50")
```

The conftest `repo` fixture already exists for other repo tests — confirm by running `grep -n "def repo" tests/conftest.py`. If it doesn't, copy the fixture shape from `tests/test_repository_*.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repository_index_ohlc.py -v`
Expected: AttributeError on `upsert_index_ohlc_rows`.

- [ ] **Step 3: Add the helpers**

Append to `src/uw_scan/storage/repository.py` near the existing `upsert_daily_ohlc`:

```python
    def upsert_index_ohlc_rows(self, bars: Iterable["OhlcBar"]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.index_ohlc_daily "
            "(ticker, market_date, open, high, low, close, volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "open = EXCLUDED.open, high = EXCLUDED.high, "
            "low = EXCLUDED.low, close = EXCLUDED.close, "
            "volume = EXCLUDED.volume, inserted_at = now()"
        )
        rows = [
            (b.ticker, b.date, b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def fetch_index_ohlc_series(
        self, ticker: str, *, start: "date | None" = None,
        end: "date | None" = None,
    ) -> list[dict[str, Any]]:
        clauses = ["ticker = %s"]
        params: list[Any] = [ticker]
        if start is not None:
            clauses.append("market_date >= %s")
            params.append(start)
        if end is not None:
            clauses.append("market_date <= %s")
            params.append(end)
        sql = (
            f"SELECT market_date, open, high, low, close, volume "
            f"FROM {self._schema}.index_ohlc_daily "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

Add `from .sources.ohlc import OhlcBar` import only if not already present (use the existing import path the file uses; if it doesn't import `OhlcBar`, keep the helper's parameter as `Iterable["OhlcBar"]` and let the caller import the type).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repository_index_ohlc.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/test_repository_index_ohlc.py
git commit -m "repo: upsert_index_ohlc_rows + fetch_index_ohlc_series"
```

---

### Task 1.3: Repo helper — `upsert_iv_smile_rows` + `fetch_iv_smile_latest`

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/test_repository_iv_smile.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

from uw_scan.storage.repository import Repository


def test_upsert_and_fetch_iv_smile(repo: Repository):
    rows = [
        {"ticker": "TSLA", "market_date": date(2026, 5, 13),
         "expiry": date(2026, 5, 15), "strike": Decimal("400"),
         "iv": Decimal("0.72")},
        {"ticker": "TSLA", "market_date": date(2026, 5, 13),
         "expiry": date(2026, 5, 15), "strike": Decimal("405"),
         "iv": Decimal("0.65")},
        {"ticker": "TSLA", "market_date": date(2026, 5, 13),
         "expiry": date(2026, 5, 22), "strike": Decimal("405"),
         "iv": Decimal("0.55")},
    ]
    repo.upsert_iv_smile_rows(rows)

    latest = repo.fetch_iv_smile_latest("TSLA")
    # Returns rows grouped by expiry, sorted by strike asc.
    assert len(latest) == 3
    assert latest[0]["expiry"] == date(2026, 5, 15)
    assert latest[0]["strike"] == Decimal("400")
    assert latest[-1]["expiry"] == date(2026, 5, 22)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repository_iv_smile.py -v`
Expected: AttributeError on `upsert_iv_smile_rows`.

- [ ] **Step 3: Add the helpers**

```python
    def upsert_iv_smile_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.iv_smile_snapshots "
            "(ticker, market_date, expiry, strike, iv) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date, expiry, strike) DO UPDATE SET "
            "iv = EXCLUDED.iv, inserted_at = now()"
        )
        params = [
            (r["ticker"], r["market_date"], r["expiry"], r["strike"], r.get("iv"))
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_iv_smile_latest(self, ticker: str) -> list[dict[str, Any]]:
        """Return all (expiry, strike, iv) rows for the latest market_date the
        ticker has smile data for. Ordered by (expiry asc, strike asc)."""
        sql = (
            f"WITH latest AS ("
            f"  SELECT max(market_date) AS market_date "
            f"  FROM {self._schema}.iv_smile_snapshots WHERE ticker = %s) "
            f"SELECT s.expiry, s.strike, s.iv, s.market_date "
            f"FROM {self._schema}.iv_smile_snapshots s "
            f"JOIN latest l USING (market_date) "
            f"WHERE s.ticker = %s "
            f"ORDER BY s.expiry ASC, s.strike ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repository_iv_smile.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/test_repository_iv_smile.py
git commit -m "repo: upsert_iv_smile_rows + fetch_iv_smile_latest"
```

---

### Task 1.4: Repo helper — `upsert_vrp_daily_rows` + `fetch_vrp_daily_series`

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/test_repository_vrp_daily.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

from uw_scan.storage.repository import Repository


def test_upsert_and_fetch_vrp_daily(repo: Repository):
    rows = [
        {"ticker": "TSLA", "market_date": date(2026, 5, 11),
         "iv": Decimal("0.50"), "rv": Decimal("0.42"),
         "vrp": Decimal("0.08"), "vrp_z_20": Decimal("0.4")},
        {"ticker": "TSLA", "market_date": date(2026, 5, 12),
         "iv": Decimal("0.51"), "rv": Decimal("0.41"),
         "vrp": Decimal("0.10"), "vrp_z_20": Decimal("0.6")},
    ]
    repo.upsert_vrp_daily_rows(rows)
    series = repo.fetch_vrp_daily_series("TSLA", limit=10)
    # Newest first.
    assert series[0]["market_date"] == date(2026, 5, 12)
    assert series[0]["vrp"] == Decimal("0.10")
    assert series[1]["market_date"] == date(2026, 5, 11)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repository_vrp_daily.py -v`
Expected: AttributeError.

- [ ] **Step 3: Add the helpers**

```python
    def upsert_vrp_daily_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.vrp_daily "
            "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "iv = EXCLUDED.iv, rv = EXCLUDED.rv, "
            "vrp = EXCLUDED.vrp, vrp_z_20 = EXCLUDED.vrp_z_20, "
            "inserted_at = now()"
        )
        params = [
            (r["ticker"], r["market_date"], r.get("iv"), r.get("rv"),
             r.get("vrp"), r.get("vrp_z_20"))
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_vrp_daily_series(
        self, ticker: str, *, limit: int = 60,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, iv, rv, vrp, vrp_z_20 "
            f"FROM {self._schema}.vrp_daily "
            f"WHERE ticker = %s "
            f"ORDER BY market_date DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repository_vrp_daily.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/test_repository_vrp_daily.py
git commit -m "repo: upsert_vrp_daily_rows + fetch_vrp_daily_series"
```

---

### Task 1.5: Repo helper — `upsert_stock_analytics_rows` + `fetch_stock_analytics_series`

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/test_repository_stock_analytics.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

from uw_scan.storage.repository import Repository


def test_upsert_and_fetch_stock_analytics(repo: Repository):
    rows = [
        {"ticker": "TSLA", "market_date": date(2026, 5, 12),
         "rvol_21": Decimal("0.40"), "rvol_pctile": Decimal("50"),
         "spy_corr_21": Decimal("0.30"), "iv_of_iv_20": Decimal("0.05")},
    ]
    repo.upsert_stock_analytics_rows(rows)
    out = repo.fetch_stock_analytics_series("TSLA", limit=10)
    assert len(out) == 1
    assert out[0]["spy_corr_21"] == Decimal("0.30")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repository_stock_analytics.py -v`
Expected: AttributeError.

- [ ] **Step 3: Add the helpers**

```python
    def upsert_stock_analytics_rows(self, rows: Iterable[dict[str, Any]]) -> int:
        sql = (
            f"INSERT INTO {self._schema}.stock_analytics_daily "
            "(ticker, market_date, rvol_21, rvol_pctile, "
            "spy_corr_21, iv_of_iv_20) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, market_date) DO UPDATE SET "
            "rvol_21 = EXCLUDED.rvol_21, rvol_pctile = EXCLUDED.rvol_pctile, "
            "spy_corr_21 = EXCLUDED.spy_corr_21, "
            "iv_of_iv_20 = EXCLUDED.iv_of_iv_20, inserted_at = now()"
        )
        params = [
            (r["ticker"], r["market_date"], r.get("rvol_21"),
             r.get("rvol_pctile"), r.get("spy_corr_21"), r.get("iv_of_iv_20"))
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(params)

    def fetch_stock_analytics_series(
        self, ticker: str, *, limit: int = 60,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, rvol_21, rvol_pctile, spy_corr_21, iv_of_iv_20 "
            f"FROM {self._schema}.stock_analytics_daily "
            f"WHERE ticker = %s ORDER BY market_date DESC LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repository_stock_analytics.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/test_repository_stock_analytics.py
git commit -m "repo: upsert_stock_analytics_rows + fetch_stock_analytics_series"
```

---

### Task 1.6: Repo helpers — read-side for existing tables (`count_realized_vol_history`, `fetch_realized_vol_history`, `fetch_volatility_stats_history`)

**Files:**
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/test_repository_vol_history_reads.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

from uw_scan.models import RealizedVolRow, VolStatsRow
from uw_scan.storage.repository import Repository


def test_history_reads(repo: Repository):
    repo.insert_realized_volatility_rows("TSLA", [
        RealizedVolRow(date=date(2026, 5, 11), price=Decimal("400"),
                       implied_volatility=Decimal("0.5"),
                       realized_volatility=Decimal("0.4")),
        RealizedVolRow(date=date(2026, 5, 12), price=Decimal("402"),
                       implied_volatility=Decimal("0.51"),
                       realized_volatility=Decimal("0.41")),
    ])
    repo.insert_volatility_stats_rows([
        VolStatsRow(ticker="TSLA", date=date(2026, 5, 12),
                    iv=Decimal("0.51"), iv_low=Decimal("0.17"),
                    iv_high=Decimal("0.55"), iv_rank=Decimal("41"),
                    rv=Decimal("0.41"), rv_low=Decimal("0.09"),
                    rv_high=Decimal("0.37")),
    ])
    assert repo.count_realized_vol_history("TSLA") == 2

    rv_rows = repo.fetch_realized_vol_history("TSLA", days=365)
    assert len(rv_rows) == 2
    assert rv_rows[0]["market_date"] == date(2026, 5, 11)  # ascending

    stats = repo.fetch_volatility_stats_history("TSLA", days=365)
    assert len(stats) == 1
    assert stats[0]["iv_rank"] == Decimal("41")
```

The signatures `insert_realized_volatility_rows` and `insert_volatility_stats_rows` already exist (Task 1.x discovers them via `grep -n "def insert_" src/uw_scan/storage/repository.py`). If the existing names differ, adjust the test to use the actual names — do not invent new inserts.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repository_vol_history_reads.py -v`
Expected: AttributeError on the new fetch/count helpers.

- [ ] **Step 3: Add the helpers**

Append to `repository.py`:

```python
    def count_realized_vol_history(self, ticker: str) -> int:
        sql = (
            f"SELECT count(*) FROM {self._schema}.realized_volatility_history "
            "WHERE ticker = %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            return int(cur.fetchone()[0])

    def fetch_realized_vol_history(
        self, ticker: str, *, days: int = 365,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, price, implied_volatility, realized_volatility "
            f"FROM {self._schema}.realized_volatility_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            f"ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_volatility_stats_history(
        self, ticker: str, *, days: int = 365,
    ) -> list[dict[str, Any]]:
        sql = (
            f"SELECT market_date, iv, iv_low, iv_high, iv_rank, "
            f"rv, rv_low, rv_high "
            f"FROM {self._schema}.volatility_stats_history "
            f"WHERE ticker = %s "
            f"  AND market_date >= (CURRENT_DATE - (%s || ' days')::interval) "
            f"ORDER BY market_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repository_vol_history_reads.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/test_repository_vol_history_reads.py
git commit -m "repo: read-side helpers for realized_vol_history + volatility_stats_history"
```

---

## Phase 2 — Pure deriver functions (TDD)

### Task 2.1: `compute_vrp_series`

**Files:**
- Create: `src/uw_scan/cards/vol_series.py`
- Test: `tests/test_vol_series_vrp.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

import pandas as pd

from uw_scan.cards.vol_series import compute_vrp_series


def test_compute_vrp_series_basic():
    rv_rows = [
        {"market_date": date(2026, 1, 1),
         "implied_volatility": 0.50, "realized_volatility": 0.40},
        {"market_date": date(2026, 1, 2),
         "implied_volatility": 0.52, "realized_volatility": 0.42},
        {"market_date": date(2026, 1, 3),
         "implied_volatility": 0.55, "realized_volatility": 0.40},
    ]
    df = compute_vrp_series(rv_rows, window=2)
    assert list(df["vrp"]) == [pytest.approx(0.10), pytest.approx(0.10),
                                pytest.approx(0.15)]
    # First row has no 2-day window → z is NaN; row 2 has window=[0.10,0.10]
    # (stdev=0) → z is NaN; row 3 has window=[0.10,0.15] (mean=0.125,
    # stdev≈0.0354) → z ≈ 0.707
    assert pd.isna(df["vrp_z_20"].iloc[0])
    assert pd.isna(df["vrp_z_20"].iloc[1])
    assert float(df["vrp_z_20"].iloc[2]) == pytest.approx(0.707, abs=0.01)


def test_compute_vrp_series_handles_missing():
    rv_rows = [
        {"market_date": date(2026, 1, 1),
         "implied_volatility": None, "realized_volatility": 0.40},
        {"market_date": date(2026, 1, 2),
         "implied_volatility": 0.52, "realized_volatility": None},
    ]
    df = compute_vrp_series(rv_rows, window=2)
    # NaN inputs propagate to NaN vrp — never crash, never fabricate.
    assert pd.isna(df["vrp"].iloc[0])
    assert pd.isna(df["vrp"].iloc[1])
```

Add `import pytest` at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vol_series_vrp.py -v`
Expected: ModuleNotFoundError for `uw_scan.cards.vol_series`.

- [ ] **Step 3: Create the module**

Create `src/uw_scan/cards/vol_series.py`:

```python
"""Pure pandas-based derivers for the Volatility Tab v2 series.

Each function takes plain dict rows (whatever the repo returned) and returns a
pandas DataFrame with named columns. No DB access, no IO. The orchestrator
(`reports/volatility_series.py`) handles persistence.
"""

from __future__ import annotations

import pandas as pd


def compute_vrp_series(
    rv_rows: list[dict],
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Compute daily VRP = IV - RV and a `window`-day rolling z-score.

    Input rows must have keys: `market_date`, `implied_volatility`,
    `realized_volatility` (the shape `fetch_realized_vol_history` returns).
    Output columns: `market_date`, `iv`, `rv`, `vrp`, `vrp_z_20`.
    """
    df = pd.DataFrame(rv_rows)
    if df.empty:
        return pd.DataFrame(columns=["market_date", "iv", "rv", "vrp", "vrp_z_20"])
    df = df.rename(
        columns={
            "implied_volatility": "iv",
            "realized_volatility": "rv",
        }
    )[["market_date", "iv", "rv"]]
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df["rv"] = pd.to_numeric(df["rv"], errors="coerce")
    df["vrp"] = df["iv"] - df["rv"]
    rolling = df["vrp"].rolling(window, min_periods=window)
    mean = rolling.mean()
    std = rolling.std(ddof=0)
    df["vrp_z_20"] = (df["vrp"] - mean) / std.replace(0, float("nan"))
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vol_series_vrp.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/vol_series.py tests/test_vol_series_vrp.py
git commit -m "deriver: compute_vrp_series (VRP + rolling z-score)"
```

---

### Task 2.2: `compute_iv_of_iv`

**Files:**
- Modify: `src/uw_scan/cards/vol_series.py`
- Test: `tests/test_vol_series_iv_of_iv.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import math
from datetime import date

import pandas as pd
import pytest

from uw_scan.cards.vol_series import compute_iv_of_iv


def test_iv_of_iv_annualisation():
    rv_rows = [
        {"market_date": date(2026, 1, d), "implied_volatility": 0.50}
        for d in range(1, 22)
    ]
    # Inject one big jump on the last row so stdev is non-zero.
    rv_rows[-1]["implied_volatility"] = 0.60
    df = compute_iv_of_iv(rv_rows, window=20)
    last = float(df["iv_of_iv_20"].iloc[-1])
    # stdev(0.50 × 19 + 0.60 × 1) over 20 = sqrt(0.0045) ≈ 0.0218
    # annualised = 0.0218 × sqrt(252) ≈ 0.3462.
    assert last == pytest.approx(0.0218 * math.sqrt(252), abs=0.01)


def test_iv_of_iv_short_series_returns_nan():
    rv_rows = [
        {"market_date": date(2026, 1, d), "implied_volatility": 0.5}
        for d in range(1, 5)
    ]
    df = compute_iv_of_iv(rv_rows, window=20)
    assert pd.isna(df["iv_of_iv_20"].iloc[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vol_series_iv_of_iv.py -v`
Expected: ImportError.

- [ ] **Step 3: Add the function**

Append to `src/uw_scan/cards/vol_series.py`:

```python
import math


def compute_iv_of_iv(
    rv_rows: list[dict],
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Annualised rolling stdev of daily IV — the per-stock VVIX analogue.

    Output columns: `market_date`, `iv`, `iv_of_iv_20`.
    """
    df = pd.DataFrame(rv_rows)
    if df.empty:
        return pd.DataFrame(columns=["market_date", "iv", "iv_of_iv_20"])
    df = df.rename(columns={"implied_volatility": "iv"})[["market_date", "iv"]]
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    rolling = df["iv"].rolling(window, min_periods=window).std(ddof=0)
    df["iv_of_iv_20"] = rolling * math.sqrt(252)
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vol_series_iv_of_iv.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/vol_series.py tests/test_vol_series_iv_of_iv.py
git commit -m "deriver: compute_iv_of_iv (rolling-stdev annualised)"
```

---

### Task 2.3: `compute_rvol_and_percentile`

**Files:**
- Modify: `src/uw_scan/cards/vol_series.py`
- Test: `tests/test_vol_series_rvol.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import math
from datetime import date, timedelta

import pandas as pd
import pytest

from uw_scan.cards.vol_series import compute_rvol_and_percentile


def _make_rows(prices: list[float]) -> list[dict]:
    base = date(2026, 1, 1)
    return [{"market_date": base + timedelta(days=i), "price": p}
            for i, p in enumerate(prices)]


def test_rvol_basic():
    # 22 days of steady up-trend then one dip → non-zero rvol.
    prices = [100 + i * 0.5 for i in range(22)]
    prices[-1] = 105.0
    df = compute_rvol_and_percentile(_make_rows(prices), window=21)
    assert pd.notna(df["rvol_21"].iloc[-1])
    assert float(df["rvol_21"].iloc[-1]) > 0


def test_rvol_percentile_bounds():
    # Make a long mostly-flat series with one big move at the end. The
    # final-day rvol should be near the top percentile.
    prices = [100.0] * 250 + [100.0, 110.0]
    df = compute_rvol_and_percentile(_make_rows(prices), window=21,
                                     pctile_window=252)
    last = float(df["rvol_pctile"].iloc[-1])
    assert 50 <= last <= 100  # spike → high percentile


def test_rvol_short_series_returns_nan():
    df = compute_rvol_and_percentile(_make_rows([100, 101, 102]), window=21)
    assert pd.isna(df["rvol_21"].iloc[-1])
    assert pd.isna(df["rvol_pctile"].iloc[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vol_series_rvol.py -v`
Expected: ImportError.

- [ ] **Step 3: Add the function**

```python
def compute_rvol_and_percentile(
    price_rows: list[dict],
    *,
    window: int = 21,
    pctile_window: int = 252,
) -> pd.DataFrame:
    """Realised vol over `window` days (annualised) + trailing percentile.

    Input rows must have `market_date` and `price`.
    Output: `market_date`, `price`, `log_ret`, `rvol_21`, `rvol_pctile`.
    """
    df = pd.DataFrame(price_rows)
    if df.empty:
        return pd.DataFrame(columns=[
            "market_date", "price", "log_ret", "rvol_21", "rvol_pctile",
        ])
    df = df.sort_values("market_date").reset_index(drop=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["log_ret"] = (df["price"] / df["price"].shift(1)).apply(
        lambda x: math.log(x) if x and x > 0 else float("nan")
    )
    df["rvol_21"] = (
        df["log_ret"].rolling(window, min_periods=window).std(ddof=0)
        * math.sqrt(252)
    )

    def _pctile(s: pd.Series) -> float:
        clean = s.dropna()
        if len(clean) < 2:
            return float("nan")
        cur = clean.iloc[-1]
        rank = (clean < cur).sum() + 0.5 * (clean == cur).sum()
        return 100.0 * rank / len(clean)

    df["rvol_pctile"] = (
        df["rvol_21"]
        .rolling(pctile_window, min_periods=window)
        .apply(_pctile, raw=False)
    )
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vol_series_rvol.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/vol_series.py tests/test_vol_series_rvol.py
git commit -m "deriver: compute_rvol_and_percentile (annualised + trailing pctile)"
```

---

### Task 2.4: `compute_stock_spy_corr`

**Files:**
- Modify: `src/uw_scan/cards/vol_series.py`
- Test: `tests/test_vol_series_corr.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import math
from datetime import date, timedelta

import pandas as pd
import pytest

from uw_scan.cards.vol_series import compute_stock_spy_corr


def test_corr_perfectly_correlated():
    base = date(2026, 1, 1)
    stock = [{"market_date": base + timedelta(days=i),
              "price": 100 + i * 0.5} for i in range(30)]
    spy = [{"market_date": base + timedelta(days=i),
            "close": 500 + i * 2.5} for i in range(30)]
    df = compute_stock_spy_corr(stock, spy, window=21)
    last = float(df["spy_corr_21"].iloc[-1])
    assert last == pytest.approx(1.0, abs=0.001)


def test_corr_missing_spy_returns_nan_only_for_missing_dates():
    base = date(2026, 1, 1)
    stock = [{"market_date": base + timedelta(days=i),
              "price": 100 + i * 0.5} for i in range(25)]
    spy = [{"market_date": base + timedelta(days=i),
            "close": 500 + i * 2.5} for i in range(25)]
    # Drop one SPY row in the middle.
    spy.pop(10)
    df = compute_stock_spy_corr(stock, spy, window=21)
    # We still have enough data for at least one trailing-21 window.
    assert pd.notna(df["spy_corr_21"].iloc[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vol_series_corr.py -v`
Expected: ImportError.

- [ ] **Step 3: Add the function**

```python
def compute_stock_spy_corr(
    stock_price_rows: list[dict],
    spy_ohlc_rows: list[dict],
    *,
    window: int = 21,
) -> pd.DataFrame:
    """Pearson correlation between stock log-returns and SPY log-returns,
    rolling `window` days.

    Stock rows: `market_date`, `price` (from realized_volatility_history).
    SPY rows: `market_date`, `close` (from index_ohlc_daily).
    Output: `market_date`, `spy_corr_21`.
    """
    stock = pd.DataFrame(stock_price_rows)
    spy = pd.DataFrame(spy_ohlc_rows)
    if stock.empty or spy.empty:
        return pd.DataFrame(columns=["market_date", "spy_corr_21"])

    stock = stock.rename(columns={"price": "stock_close"})
    spy = spy.rename(columns={"close": "spy_close"})
    df = stock.merge(spy[["market_date", "spy_close"]], on="market_date", how="inner")
    df = df.sort_values("market_date").reset_index(drop=True)
    df["stock_close"] = pd.to_numeric(df["stock_close"], errors="coerce")
    df["spy_close"] = pd.to_numeric(df["spy_close"], errors="coerce")
    df["stock_ret"] = (df["stock_close"] / df["stock_close"].shift(1)).apply(
        lambda x: math.log(x) if x and x > 0 else float("nan")
    )
    df["spy_ret"] = (df["spy_close"] / df["spy_close"].shift(1)).apply(
        lambda x: math.log(x) if x and x > 0 else float("nan")
    )
    df["spy_corr_21"] = (
        df["stock_ret"].rolling(window, min_periods=window)
        .corr(df["spy_ret"])
    )
    return df[["market_date", "spy_corr_21"]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vol_series_corr.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/vol_series.py tests/test_vol_series_corr.py
git commit -m "deriver: compute_stock_spy_corr (21d rolling Pearson)"
```

---

### Task 2.5: `classify_regime_state` + `compute_iv_rv_z_overlay`

**Files:**
- Modify: `src/uw_scan/cards/vol_series.py`
- Test: `tests/test_vol_series_regime.py` (new)

- [ ] **Step 1: Write the failing test**

```python
import math
from datetime import date

import pandas as pd
import pytest

from uw_scan.cards.vol_series import (
    classify_regime_state,
    compute_iv_rv_z_overlay,
)


def test_classify_all_four_states():
    median = 0.4
    assert classify_regime_state(rvol_pctile=20, spy_corr_21=0.1,
                                 median_corr=median) == "GOLDILOCKS"
    assert classify_regime_state(rvol_pctile=20, spy_corr_21=0.7,
                                 median_corr=median) == "FRAGILE_CALM"
    assert classify_regime_state(rvol_pctile=80, spy_corr_21=0.1,
                                 median_corr=median) == "STOCK_PICKER"
    assert classify_regime_state(rvol_pctile=80, spy_corr_21=0.7,
                                 median_corr=median) == "SYSTEMIC_PANIC"


def test_classify_cold_start_falls_back_to_0_5():
    # When median is None (insufficient history), fall back to 0.5.
    assert classify_regime_state(rvol_pctile=20, spy_corr_21=0.6,
                                 median_corr=None) == "FRAGILE_CALM"
    assert classify_regime_state(rvol_pctile=20, spy_corr_21=0.4,
                                 median_corr=None) == "GOLDILOCKS"


def test_iv_rv_z_overlay():
    rv_rows = [
        {"market_date": date(2026, 1, d),
         "implied_volatility": 0.50 + (d % 3) * 0.02,
         "realized_volatility": 0.40 + (d % 3) * 0.01}
        for d in range(1, 25)
    ]
    df = compute_iv_rv_z_overlay(rv_rows, window=20)
    assert "iv_z" in df.columns and "rv_z" in df.columns
    assert pd.notna(df["iv_z"].iloc[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vol_series_regime.py -v`
Expected: ImportError.

- [ ] **Step 3: Add the functions**

```python
def classify_regime_state(
    *,
    rvol_pctile: float,
    spy_corr_21: float,
    median_corr: float | None,
) -> str:
    """Return one of the four regime labels. `median_corr=None` falls back to 0.5."""
    cutoff = 0.5 if median_corr is None else median_corr
    low_vol = rvol_pctile < 50
    low_corr = spy_corr_21 < cutoff
    if low_vol and low_corr:
        return "GOLDILOCKS"
    if low_vol and not low_corr:
        return "FRAGILE_CALM"
    if not low_vol and low_corr:
        return "STOCK_PICKER"
    return "SYSTEMIC_PANIC"


def compute_iv_rv_z_overlay(
    rv_rows: list[dict],
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Per-day z-score of IV and RV vs their own trailing `window`.

    Output: `market_date`, `iv_z`, `rv_z`.
    """
    df = pd.DataFrame(rv_rows)
    if df.empty:
        return pd.DataFrame(columns=["market_date", "iv_z", "rv_z"])
    df = df.rename(columns={
        "implied_volatility": "iv", "realized_volatility": "rv",
    })[["market_date", "iv", "rv"]]
    df["iv"] = pd.to_numeric(df["iv"], errors="coerce")
    df["rv"] = pd.to_numeric(df["rv"], errors="coerce")

    def _z(s: pd.Series) -> pd.Series:
        r = s.rolling(window, min_periods=window)
        return (s - r.mean()) / r.std(ddof=0).replace(0, float("nan"))

    df["iv_z"] = _z(df["iv"])
    df["rv_z"] = _z(df["rv"])
    return df[["market_date", "iv_z", "rv_z"]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vol_series_regime.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/vol_series.py tests/test_vol_series_regime.py
git commit -m "deriver: regime classifier + IV/RV z-overlay"
```

---

## Phase 3 — SPY OHLC seed

### Task 3.1: Seed script `scripts/seed_spy_ohlc.py`

**Files:**
- Create: `scripts/seed_spy_ohlc.py`

- [ ] **Step 1: Inspect the existing OHLC seed/runner pattern**

Run: `ls scripts/`. Look for an existing massive.com / OHLC script (likely one for the watchlist OHLC pull). Open it for shape.

- [ ] **Step 2: Write the seed script**

Create `scripts/seed_spy_ohlc.py`:

```python
"""One-shot SPY OHLC seed for Volatility Tab v2.

Pulls ~3 years of daily SPY bars from massive.com and upserts into
`uw_scan.index_ohlc_daily`. Re-runnable; idempotent.

Usage:
    uv run python scripts/seed_spy_ohlc.py [--years 3] [--ticker SPY]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("seed_spy_ohlc")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--ticker", default="SPY")
    args = parser.parse_args()

    api_key = os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        log.error("MASSIVE_API_KEY env var not set")
        return 1

    end = date.today()
    start = end - timedelta(days=args.years * 365)
    log.info("Fetching %s daily bars %s → %s", args.ticker, start, end)

    with MassiveOhlcProvider(api_key=api_key) as prov:
        bars = prov.fetch_daily(args.ticker, start=start, end=end)
    log.info("Fetched %d bars", len(bars))

    with Repository.connect() as repo:
        n = repo.upsert_index_ohlc_rows(bars)
        repo._conn.commit()
    log.info("Upserted %d rows into index_ohlc_daily", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

If `Repository.connect()` isn't the actual classmethod (run `grep -n "def connect\|Repository(" src/uw_scan/storage/repository.py | head -5`), substitute the correct construction call — do not invent one.

- [ ] **Step 3: Run the script in dev**

Run: `uv run python scripts/seed_spy_ohlc.py --years 3`
Expected: "Upserted N rows" where N ≈ 750 (3y × ~252 trading days). Verify with: `psql option_wizard -c "SELECT count(*) FROM uw_scan.index_ohlc_daily WHERE ticker='SPY'"`.

- [ ] **Step 4: Commit**

```bash
git add scripts/seed_spy_ohlc.py
git commit -m "scripts: seed_spy_ohlc.py for Volatility tab v2"
```

---

## Phase 4 — Orchestrator + endpoint

### Task 4.1: Orchestrator skeleton

**Files:**
- Create: `src/uw_scan/reports/volatility_series.py`
- Test: `tests/test_volatility_series_assemble.py` (new)

- [ ] **Step 1: Write the failing test (header-only path)**

```python
from datetime import date
from decimal import Decimal

from uw_scan.models import VolatilitySeriesResponse
from uw_scan.reports.volatility_series import (
    assemble_volatility_series,
)


def test_assemble_header_only_for_empty_history(repo, sample_run):
    # Seed the bare minimum: a single VolStatsRow + VRP from the latest run.
    # (Use whatever the existing single-stock test fixtures do.)
    resp = assemble_volatility_series(
        ticker="TSLA", repo=repo, backfill_status="ready",
    )
    assert isinstance(resp, VolatilitySeriesResponse)
    assert resp.ticker == "TSLA"
    assert resp.as_of is not None
    # Header always populated even with no series.
    assert resp.header is not None
```

Use the same conftest fixtures other backend tests use.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_volatility_series_assemble.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the orchestrator skeleton**

```python
"""Orchestrator for /api/stock/{ticker}/volatility/series.

Reads raw IV/RV/skew/term/SPY data from repo → calls deriver functions →
upserts derived rows → assembles VolatilitySeriesResponse.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd

from uw_scan.cards import vol_series
from uw_scan.models import (
    DivergencePoint,
    IvHistogramBin,
    IvHvPoint,
    IvOfIvPoint,
    IvPercentileDistribution,
    RegimeQuadrantBlock,
    RegimeQuadrantLatest,
    RegimeQuadrantPoint,
    RvCorrPoint,
    SmileExpiryCurve,
    SmilePoint,
    TermStructureExpiryRow,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VrpDailyPoint,
)
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _dec(v: Any) -> Decimal | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return Decimal(str(v))


def _build_header(repo: Repository, ticker: str) -> VolHeaderBlock:
    stats = repo.fetch_volatility_stats_latest(ticker) or {}
    rv = repo.fetch_realized_vol_latest(ticker) or {}
    skew = repo.fetch_skew_latest(ticker) or {}
    # VRP signal/note from the assembled single-stock report VRPAssessment —
    # reuse existing logic.
    from uw_scan.reports.single_stock import build_vrp_block
    iv = _dec(stats.get("iv")) or _dec(rv.get("implied_volatility"))
    rv_val = _dec(stats.get("rv")) or _dec(rv.get("realized_volatility"))
    vrp = (iv - rv_val) if (iv is not None and rv_val is not None) else None
    vrp_block = build_vrp_block(iv, rv_val)  # returns (vrp, signal, note)
    return VolHeaderBlock(
        iv=iv,
        rv=rv_val,
        iv_rank=_dec(stats.get("iv_rank")),
        # iv_rank_1y comes from the iv_rank endpoint — repo helper TBD if absent
        iv_low_52w=_dec(stats.get("iv_low")),
        iv_high_52w=_dec(stats.get("iv_high")),
        rv_low_52w=_dec(stats.get("rv_low")),
        rv_high_52w=_dec(stats.get("rv_high")),
        skew_25d=_dec(skew.get("risk_reversal")),
        vrp=vrp_block.vrp,
        vrp_signal=vrp_block.signal,
        vrp_note=vrp_block.note,
    )


def assemble_volatility_series(
    *,
    ticker: str,
    repo: Repository,
    backfill_status: str = "ready",
) -> VolatilitySeriesResponse:
    """Single read-side entry point. Pulls cached series + computes anything
    not yet persisted. Does NOT trigger UW fetches — that's the backfill job."""
    header = _build_header(repo, ticker)
    today = date.today()
    return VolatilitySeriesResponse(
        ticker=ticker,
        as_of=today,
        backfill_status=backfill_status,
        header=header,
    )
```

**Note for the implementer:** `build_vrp_block` is the canonical VRP logic — locate it via `grep -n "def build_vrp\|VRPAssessment" src/uw_scan/reports/`. If the helper has a different name or returns a different shape, adapt the call inline; do not invent a new VRP rule.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_volatility_series_assemble.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/volatility_series.py tests/test_volatility_series_assemble.py
git commit -m "reports: assemble_volatility_series skeleton (header only)"
```

---

### Task 4.2: Orchestrator — wire HV/IV history + VRP spread + IV-of-IV + regime + divergence + percentile-dist

**Files:**
- Modify: `src/uw_scan/reports/volatility_series.py`
- Test: `tests/test_volatility_series_assemble.py` (extend)

- [ ] **Step 1: Extend the test**

Append:

```python
def test_assemble_full_series_with_seeded_history(repo):
    # Seed ~30 days of synthetic realized_volatility_history + SPY OHLC + a few
    # iv_term_snapshots and iv_smile_snapshots. Verify the response has
    # populated arrays in hv_iv_history, vrp_spread, iv_of_iv, rv_spy_corr,
    # regime_quadrant.points (latest filled), divergence.
    # (Concrete seed values: 30 days of iv=0.5+noise, rv=0.4+noise; SPY going
    # up linearly. Use repo.insert_realized_volatility_rows and
    # repo.upsert_index_ohlc_rows.)
    import math
    from datetime import date, timedelta
    from decimal import Decimal
    from uw_scan.models import RealizedVolRow
    from uw_scan.sources.ohlc import OhlcBar

    base = date(2026, 1, 1)
    rv_rows = []
    spy_bars = []
    for i in range(60):
        d = base + timedelta(days=i)
        iv = 0.50 + 0.02 * math.sin(i / 3)
        rv_val = 0.40 + 0.01 * math.cos(i / 4)
        rv_rows.append(RealizedVolRow(
            date=d, price=Decimal(str(100 + i * 0.5)),
            implied_volatility=Decimal(str(iv)),
            realized_volatility=Decimal(str(rv_val)),
        ))
        spy_bars.append(OhlcBar(
            ticker="SPY", date=d, open=None, high=None, low=None,
            close=Decimal(str(500 + i * 2)), volume=None,
        ))
    repo.insert_realized_volatility_rows("TSLA", rv_rows)
    repo.upsert_index_ohlc_rows(spy_bars)

    resp = assemble_volatility_series(ticker="TSLA", repo=repo)
    assert len(resp.hv_iv_history) == 60
    assert resp.iv_percentile_distribution is not None
    assert len(resp.iv_of_iv) > 0
    assert len(resp.rv_spy_corr) > 0
    assert len(resp.vrp_spread) > 0
    assert resp.regime_quadrant is not None
    assert resp.regime_quadrant.latest is not None
    assert resp.regime_quadrant.latest.state in {
        "GOLDILOCKS", "FRAGILE_CALM", "STOCK_PICKER", "SYSTEMIC_PANIC",
    }
    assert len(resp.divergence) > 0
    assert resp.divergence_headline.endswith("σ")
    assert resp.vrp_spread_headline  # non-empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_volatility_series_assemble.py::test_assemble_full_series_with_seeded_history -v`
Expected: AssertionError on `len(resp.hv_iv_history) == 60`.

- [ ] **Step 3: Wire all series in `assemble_volatility_series`**

Replace the body of `assemble_volatility_series` with:

```python
def assemble_volatility_series(
    *,
    ticker: str,
    repo: Repository,
    backfill_status: str = "ready",
) -> VolatilitySeriesResponse:
    header = _build_header(repo, ticker)
    today = date.today()

    rv_history = repo.fetch_realized_vol_history(ticker, days=365)
    spy_history = repo.fetch_index_ohlc_series("SPY")

    hv_iv = [
        IvHvPoint(date=r["market_date"], iv=_dec(r["implied_volatility"]),
                  rv=_dec(r["realized_volatility"]))
        for r in rv_history
    ]

    # IV percentile distribution (10 bins over last-365d IV).
    iv_pctile_dist = _build_iv_percentile_distribution(rv_history, header.iv)

    vrp_df = vol_series.compute_vrp_series(rv_history)
    iv_of_iv_df = vol_series.compute_iv_of_iv(rv_history)
    rvol_df = vol_series.compute_rvol_and_percentile(
        [{"market_date": r["market_date"], "price": r["price"]} for r in rv_history]
    )
    corr_df = vol_series.compute_stock_spy_corr(
        [{"market_date": r["market_date"], "price": r["price"]} for r in rv_history],
        spy_history,
    )
    z_df = vol_series.compute_iv_rv_z_overlay(rv_history)

    # Persist derived series (per standing rule). Convert NaN → None.
    _persist_vrp_daily(repo, ticker, vrp_df)
    _persist_stock_analytics(repo, ticker, iv_of_iv_df, rvol_df, corr_df)
    repo._conn.commit()

    # Build response from the persisted+derived frames.
    vrp_spread = [
        VrpDailyPoint(date=row.market_date,
                      vrp=_dec(row.vrp), vrp_z_20=_dec(row.vrp_z_20))
        for row in vrp_df.tail(30).itertuples()
    ]
    vrp_spread_headline = _vrp_spread_headline(vrp_df)

    iv_of_iv = [
        IvOfIvPoint(date=row.market_date, iv=_dec(row.iv),
                    iv_of_iv_20=_dec(row.iv_of_iv_20))
        for row in iv_of_iv_df.tail(90).itertuples()
    ]

    # Merge RV with corr for the dual-axis chart.
    rv_corr = []
    corr_by_date = {row.market_date: row.spy_corr_21 for row in corr_df.itertuples()}
    for r in rv_history[-90:]:
        d = r["market_date"]
        rv_corr.append(RvCorrPoint(
            date=d, rv=_dec(r["realized_volatility"]),
            spy_corr_21=_dec(corr_by_date.get(d)),
        ))

    # Regime quadrant: last 20 sessions of (rvol_pctile, spy_corr_21).
    quadrant = _build_regime_quadrant(rvol_df, corr_df)

    divergence = [
        DivergencePoint(date=row.market_date,
                        iv_z=_dec(row.iv_z), rv_z=_dec(row.rv_z))
        for row in z_df.tail(20).itertuples()
    ]
    divergence_headline = _divergence_headline(z_df)

    return VolatilitySeriesResponse(
        ticker=ticker, as_of=today, backfill_status=backfill_status,
        header=header,
        term_structure=_build_term_structure(repo, ticker),
        smile=_build_smile(repo, ticker),
        hv_iv_history=hv_iv,
        iv_percentile_distribution=iv_pctile_dist,
        iv_of_iv=iv_of_iv,
        rv_spy_corr=rv_corr,
        regime_quadrant=quadrant,
        divergence=divergence,
        divergence_headline=divergence_headline,
        vrp_spread=vrp_spread,
        vrp_spread_headline=vrp_spread_headline,
    )


def _build_iv_percentile_distribution(
    rv_history: list[dict], current_iv: Decimal | None,
) -> IvPercentileDistribution:
    ivs = [float(r["implied_volatility"]) for r in rv_history
           if r["implied_volatility"] is not None]
    if not ivs:
        return IvPercentileDistribution()
    lo, hi = min(ivs), max(ivs)
    if lo == hi:
        return IvPercentileDistribution(
            bins=[IvHistogramBin(lo=_dec(lo), hi=_dec(hi), count=len(ivs))],
            current_iv=current_iv,
            current_pctile=Decimal("50"),
        )
    n_bins = 20
    step = (hi - lo) / n_bins
    bins = []
    for i in range(n_bins):
        b_lo = lo + step * i
        b_hi = lo + step * (i + 1)
        count = sum(1 for v in ivs if b_lo <= v < b_hi or (i == n_bins - 1 and v == b_hi))
        bins.append(IvHistogramBin(lo=_dec(b_lo), hi=_dec(b_hi), count=count))
    pctile = None
    if current_iv is not None:
        cv = float(current_iv)
        rank = sum(1 for v in ivs if v < cv)
        pctile = Decimal(str(round(100 * rank / len(ivs), 1)))
    return IvPercentileDistribution(
        bins=bins, current_iv=current_iv, current_pctile=pctile,
    )


def _persist_vrp_daily(repo: Repository, ticker: str, df: pd.DataFrame) -> None:
    rows = [
        {"ticker": ticker, "market_date": r.market_date,
         "iv": _dec(r.iv), "rv": _dec(r.rv),
         "vrp": _dec(r.vrp), "vrp_z_20": _dec(r.vrp_z_20)}
        for r in df.itertuples() if not pd.isna(r.vrp)
    ]
    if rows:
        repo.upsert_vrp_daily_rows(rows)


def _persist_stock_analytics(
    repo: Repository, ticker: str,
    iv_of_iv_df: pd.DataFrame,
    rvol_df: pd.DataFrame,
    corr_df: pd.DataFrame,
) -> None:
    by_date: dict[date, dict] = {}
    for r in iv_of_iv_df.itertuples():
        by_date.setdefault(r.market_date, {})["iv_of_iv_20"] = _dec(r.iv_of_iv_20)
    for r in rvol_df.itertuples():
        d = by_date.setdefault(r.market_date, {})
        d["rvol_21"] = _dec(r.rvol_21)
        d["rvol_pctile"] = _dec(r.rvol_pctile)
    for r in corr_df.itertuples():
        by_date.setdefault(r.market_date, {})["spy_corr_21"] = _dec(r.spy_corr_21)
    rows = [
        {"ticker": ticker, "market_date": d, **vals}
        for d, vals in by_date.items()
        if any(v is not None for v in vals.values())
    ]
    if rows:
        repo.upsert_stock_analytics_rows(rows)


def _build_regime_quadrant(
    rvol_df: pd.DataFrame, corr_df: pd.DataFrame,
) -> RegimeQuadrantBlock:
    merged = rvol_df.merge(corr_df, on="market_date", how="inner").dropna(
        subset=["rvol_pctile", "spy_corr_21"]
    )
    if merged.empty:
        return RegimeQuadrantBlock()
    points = [
        RegimeQuadrantPoint(date=r.market_date,
                            rvol_pctile=_dec(r.rvol_pctile),
                            spy_corr_21=_dec(r.spy_corr_21))
        for r in merged.tail(20).itertuples()
    ]
    last = merged.iloc[-1]
    # Trailing 252-day median of spy_corr_21 — or None if not enough history.
    median = (
        float(merged["spy_corr_21"].tail(252).median())
        if len(merged) >= 30 else None
    )
    state = vol_series.classify_regime_state(
        rvol_pctile=float(last["rvol_pctile"]),
        spy_corr_21=float(last["spy_corr_21"]),
        median_corr=median,
    )
    return RegimeQuadrantBlock(
        points=points,
        latest=RegimeQuadrantLatest(
            date=last["market_date"],
            rvol_pctile=_dec(last["rvol_pctile"]),
            spy_corr_21=_dec(last["spy_corr_21"]),
            state=state,
        ),
    )


def _vrp_spread_headline(df: pd.DataFrame) -> str:
    tail = df.tail(2)
    if len(tail) < 2:
        return ""
    curr = tail["vrp"].iloc[-1]
    prev = tail["vrp"].iloc[-2]
    if pd.isna(curr) or pd.isna(prev):
        return ""
    delta = curr - prev
    direction = "compressing" if abs(curr) < abs(prev) else "widening"
    return f"{curr:+.2f} pts | {direction} {delta:+.2f} pts"


def _divergence_headline(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    iv_z = df["iv_z"].iloc[-1]
    rv_z = df["rv_z"].iloc[-1]
    if pd.isna(iv_z) or pd.isna(rv_z):
        return ""
    return f"{(iv_z - rv_z):+.2f}σ"


def _build_term_structure(
    repo: Repository, ticker: str,
) -> list[TermStructureExpiryRow]:
    run_id = repo.latest_run_id(ticker)
    if run_id == 0:
        return []
    rows = repo.fetch_iv_term_rows(run_id, ticker)
    # For now expose ATM only — Task 4.3 wires per-strike ladder once
    # iv_smile_snapshots populated.
    return [
        TermStructureExpiryRow(
            expiry=r["expiry"], dte=r.get("dte"),
            by_strike={"ATM": _dec(r.get("volatility"))} if r.get("volatility") else {},
        )
        for r in rows
    ]


def _build_smile(repo: Repository, ticker: str) -> list[SmileExpiryCurve]:
    rows = repo.fetch_iv_smile_latest(ticker)
    if not rows:
        return []
    by_expiry: dict[date, list[SmilePoint]] = {}
    for r in rows:
        by_expiry.setdefault(r["expiry"], []).append(
            SmilePoint(strike=r["strike"], iv=_dec(r["iv"]))
        )
    return [SmileExpiryCurve(expiry=ex, points=pts)
            for ex, pts in sorted(by_expiry.items())]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_volatility_series_assemble.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/volatility_series.py tests/test_volatility_series_assemble.py
git commit -m "reports: assemble full volatility series (HV/IV, VRP, regime, divergence)"
```

---

### Task 4.3: Smile snapshot builder — pivot from `greeks_by_expiry_strike`

**Files:**
- Create: `src/uw_scan/reports/iv_smile_builder.py`
- Test: `tests/test_iv_smile_builder.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from decimal import Decimal

from uw_scan.reports.iv_smile_builder import build_iv_smile_snapshot_rows


def test_pivots_call_put_iv_into_smile_rows():
    greeks = [
        {"expiry": date(2026, 5, 15), "strike": Decimal("400"),
         "call_volatility": Decimal("0.70"), "put_volatility": Decimal("0.74")},
        {"expiry": date(2026, 5, 15), "strike": Decimal("405"),
         "call_volatility": Decimal("0.66"), "put_volatility": None},
        {"expiry": date(2026, 5, 22), "strike": Decimal("400"),
         "call_volatility": None, "put_volatility": Decimal("0.50")},
    ]
    rows = build_iv_smile_snapshot_rows(
        ticker="TSLA", market_date=date(2026, 5, 13), greeks_rows=greeks,
    )
    assert len(rows) == 3
    assert rows[0]["iv"] == Decimal("0.72")  # avg of 0.70 + 0.74
    assert rows[1]["iv"] == Decimal("0.66")  # call-only fallback
    assert rows[2]["iv"] == Decimal("0.50")  # put-only fallback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_iv_smile_builder.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

```python
"""Pivot greeks_by_expiry_strike rows into iv_smile_snapshots rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal


def build_iv_smile_snapshot_rows(
    *,
    ticker: str,
    market_date: date,
    greeks_rows: list[dict],
) -> list[dict]:
    out = []
    for r in greeks_rows:
        c = r.get("call_volatility")
        p = r.get("put_volatility")
        if c is not None and p is not None:
            iv = (Decimal(str(c)) + Decimal(str(p))) / Decimal("2")
        elif c is not None:
            iv = Decimal(str(c))
        elif p is not None:
            iv = Decimal(str(p))
        else:
            continue
        out.append({
            "ticker": ticker,
            "market_date": market_date,
            "expiry": r["expiry"],
            "strike": Decimal(str(r["strike"])),
            "iv": iv,
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_iv_smile_builder.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/iv_smile_builder.py tests/test_iv_smile_builder.py
git commit -m "reports: iv_smile_builder pivots greeks rows into smile snapshots"
```

---

### Task 4.4: Backfill orchestrator — `run_volatility_backfill`

**Files:**
- Modify: `src/uw_scan/reports/volatility_series.py`
- Test: `tests/test_volatility_backfill.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock

from uw_scan.reports.volatility_series import run_volatility_backfill


def test_backfill_invokes_uw_fetchers_and_smile_builder(repo, monkeypatch):
    fake_client = MagicMock()
    calls: list[str] = []

    def _fake_realized(client, repo_, run_id, ticker):
        calls.append(f"realized:{ticker}")
        return []
    def _fake_skew(client, repo_, run_id, ticker, expiry, delta=25):
        calls.append(f"skew:{ticker}:{expiry}:{delta}")
        return []
    def _fake_greeks(client, repo_, run_id, ticker, expiry):
        calls.append(f"greeks:{ticker}:{expiry}")
        return []

    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.fetch_realized_volatility",
        _fake_realized,
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.fetch_skew", _fake_skew,
    )
    monkeypatch.setattr(
        "uw_scan.reports.volatility_series.fetch_greeks", _fake_greeks,
    )

    status = run_volatility_backfill(
        client=fake_client, repo=repo, run_id=1, ticker="TSLA",
        nearest_expiries=["2026-05-15", "2026-05-22"],
    )
    assert status == "ready"
    assert "realized:TSLA" in calls
    assert any(c.startswith("skew:TSLA:") for c in calls)
    assert "greeks:TSLA:2026-05-15" in calls
    assert "greeks:TSLA:2026-05-22" in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_volatility_backfill.py -v`
Expected: ImportError on `run_volatility_backfill`.

- [ ] **Step 3: Add the backfill function**

Append to `src/uw_scan/reports/volatility_series.py`:

```python
from uw_scan.api.client import UwClient
from uw_scan.reports.iv_smile_builder import build_iv_smile_snapshot_rows
from uw_scan.sources.uw import (
    fetch_greeks,
    fetch_realized_volatility,
    fetch_skew,
)


def run_volatility_backfill(
    *,
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    nearest_expiries: list[str],
) -> str:
    """Pull historical UW data and (re)derive cached series. Returns final
    backfill_status ("ready" or "failed").

    Safe to re-run — every write is idempotent.
    """
    try:
        # 1. Realised vol history (single call, returns whole series).
        fetch_realized_volatility(client, repo, run_id, ticker)

        # 2. Skew for each nearest expiry (small loop).
        for ex in nearest_expiries[:2]:
            fetch_skew(client, repo, run_id, ticker, expiry=ex, delta=25)

        # 3. Greeks for each of the 4 nearest expiries → pivot → smile rows.
        from datetime import date as _date
        smile_rows = []
        for ex in nearest_expiries[:4]:
            grs = fetch_greeks(client, repo, run_id, ticker, expiry=ex)
            greeks_dicts = [g.model_dump() for g in grs]
            smile_rows.extend(build_iv_smile_snapshot_rows(
                ticker=ticker, market_date=_date.today(),
                greeks_rows=greeks_dicts,
            ))
        if smile_rows:
            repo.upsert_iv_smile_rows(smile_rows)

        # 4. Re-derive VRP/analytics from the freshly-persisted IV/RV.
        #    (The next assemble_volatility_series call will do this lazily;
        #    we don't need to recompute here, but committing the transaction
        #    is essential so the next read sees the new rows.)
        repo._conn.commit()
        return "ready"
    except Exception:
        log.exception("volatility backfill failed for %s", ticker)
        return "failed"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_volatility_backfill.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/volatility_series.py tests/test_volatility_backfill.py
git commit -m "reports: run_volatility_backfill (realized + skew + greeks → smile)"
```

---

### Task 4.5: FastAPI router `/api/stock/{ticker}/volatility/series`

**Files:**
- Create: `src/uw_scan/api/routers/volatility.py`
- Modify: `src/uw_scan/api/server.py`
- Test: `tests/test_volatility_endpoint.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from uw_scan.api.server import build_app


def test_volatility_series_endpoint_returns_ready_when_history_present(
    repo, seeded_realized_vol_history_and_spy,
):
    app = build_app(repo=repo)
    client = TestClient(app)
    r = client.get("/api/stock/TSLA/volatility/series")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "TSLA"
    assert body["backfill_status"] in {"ready", "running"}
    assert "header" in body
    assert "hv_iv_history" in body


def test_volatility_series_endpoint_kicks_off_backfill_when_history_thin(
    repo,
):
    app = build_app(repo=repo)
    client = TestClient(app)
    r = client.get("/api/stock/UNSEEDED/volatility/series")
    assert r.status_code == 200
    body = r.json()
    assert body["backfill_status"] == "running"
```

(Adjust the fixture name to whatever already exists; reuse the watchlist endpoint test fixtures as a model.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_volatility_endpoint.py -v`
Expected: 404 or import error.

- [ ] **Step 3: Implement the router**

Create `src/uw_scan/api/routers/volatility.py`:

```python
"""/api/stock/{ticker}/volatility/series — see spec 2026-05-13 §5.1."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends

from uw_scan.api.deps import get_repo
from uw_scan.api.client import UwClient
from uw_scan.config import load_config
from uw_scan.models import VolatilitySeriesResponse
from uw_scan.reports.volatility_series import (
    assemble_volatility_series,
    run_volatility_backfill,
)
from uw_scan.storage.repository import Repository

router = APIRouter()
log = logging.getLogger(__name__)

# Threshold below which we trigger a backfill (matches spec §4.4).
HISTORY_THRESHOLD_DAYS = 90


def _kick_backfill(ticker: str) -> None:
    """Run the UW backfill out-of-band. Owns its own repo + client."""
    try:
        cfg = load_config()
        with Repository.connect() as repo, UwClient(api_key=cfg.uw_api_key) as client:
            run_id = repo.latest_run_id(ticker) or repo.create_run(
                kind="volatility_backfill",
            )
            # Pull the 4 nearest expiries from the latest market structure
            # snapshot. If we have none, skip greeks and only pull realised.
            expiries = repo.fetch_nearest_expiries(ticker, limit=4) or []
            run_volatility_backfill(
                client=client, repo=repo, run_id=run_id, ticker=ticker,
                nearest_expiries=[e.isoformat() for e in expiries],
            )
    except Exception:
        log.exception("background backfill failed for %s", ticker)


@router.get(
    "/stock/{ticker}/volatility/series",
    response_model=VolatilitySeriesResponse,
)
def get_volatility_series(
    ticker: str,
    background_tasks: BackgroundTasks,
    repo: Repository = Depends(get_repo),
) -> VolatilitySeriesResponse:
    t = ticker.upper()
    history_rows = repo.count_realized_vol_history(t)
    status = "ready"
    if history_rows < HISTORY_THRESHOLD_DAYS:
        status = "running"
        background_tasks.add_task(_kick_backfill, t)
    return assemble_volatility_series(
        ticker=t, repo=repo, backfill_status=status,
    )
```

If `repo.create_run` or `repo.fetch_nearest_expiries` don't exist, locate equivalents via `grep -n "def create_run\|def fetch_nearest_expiries\|def insert_scan_run" src/uw_scan/storage/repository.py` and use the actual names; do not invent new repo methods.

- [ ] **Step 4: Mount the router**

Edit `src/uw_scan/api/server.py` — add:

```python
from uw_scan.api.routers import volatility
app.include_router(volatility.router, prefix="/api", tags=["volatility"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_volatility_endpoint.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/api/routers/volatility.py src/uw_scan/api/server.py tests/test_volatility_endpoint.py
git commit -m "api: GET /api/stock/{ticker}/volatility/series + background backfill"
```

---

### Task 4.6: Manually smoke-test the endpoint

- [ ] **Step 1: Start the API**

Run: `uv run uvicorn uw_scan.api.server:app --port 8400 --reload` (in a background terminal).

- [ ] **Step 2: Hit the endpoint for a ticker that has history**

Run: `curl -s http://127.0.0.1:8400/api/stock/TSLA/volatility/series | jq '.ticker, .backfill_status, (.hv_iv_history | length), (.vrp_spread | length), .regime_quadrant.latest.state'`

Expected: ticker matches; `backfill_status` is `"ready"`; lengths > 0.

- [ ] **Step 3: Hit it for a fresh ticker**

Run: `curl -s http://127.0.0.1:8400/api/stock/AMD/volatility/series | jq '.backfill_status'`
Expected: `"running"` on first hit, `"ready"` within ~30s.

- [ ] **Step 4: No commit** (manual verification only).

---

### Task 4.7: Regenerate frontend types

**Files:**
- Modify: `web/lib/types.ts` (auto-generated)

- [ ] **Step 1: Regenerate types**

With the API still running, in `web/`:

Run: `npm run gen:types`
Expected: file rewritten; diff shows the new `/api/stock/{ticker}/volatility/series` path.

- [ ] **Step 2: Commit**

```bash
git add web/lib/types.ts
git commit -m "types: regen openapi types for volatility series endpoint"
```

---

## Phase 5 — Frontend chart primitives

### Task 5.1: SVG chart helpers `web/lib/svgChart.ts`

**Files:**
- Create: `web/lib/svgChart.ts`
- Test: `web/tests/lib/svgChart.test.ts` (new)

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { linearScale, pathFromPoints, niceTicks } from "@/lib/svgChart";

describe("svgChart helpers", () => {
  it("linearScale maps domain to range", () => {
    const s = linearScale([0, 100], [0, 200]);
    expect(s(0)).toBe(0);
    expect(s(50)).toBe(100);
    expect(s(100)).toBe(200);
  });

  it("pathFromPoints emits M/L commands", () => {
    expect(pathFromPoints([[0, 0], [10, 10]])).toBe("M0,0 L10,10");
  });

  it("pathFromPoints returns empty for no points", () => {
    expect(pathFromPoints([])).toBe("");
  });

  it("niceTicks returns ~5 round numbers", () => {
    const ticks = niceTicks(0, 100, 5);
    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks[0]).toBeLessThanOrEqual(0);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(100);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- svgChart`
Expected: module not found.

- [ ] **Step 3: Implement the helpers**

```ts
// web/lib/svgChart.ts
export type Point = [number, number];

export function linearScale(
  domain: [number, number],
  range: [number, number],
): (v: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

export function pathFromPoints(points: Point[]): string {
  if (points.length === 0) return "";
  return points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`)
    .join(" ");
}

export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!isFinite(min) || !isFinite(max) || min === max) return [min];
  const span = max - min;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const err = (count * step) / span;
  const adjusted = err >= 0.15 ? step * 10 : err >= 0.35 ? step * 5 : err >= 0.75 ? step * 2 : step;
  const start = Math.floor(min / adjusted) * adjusted;
  const end = Math.ceil(max / adjusted) * adjusted;
  const out: number[] = [];
  for (let v = start; v <= end + 1e-9; v += adjusted) out.push(v);
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test -- svgChart`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add web/lib/svgChart.ts web/tests/lib/svgChart.test.ts
git commit -m "ui: svgChart helpers (linearScale, pathFromPoints, niceTicks)"
```

---

### Task 5.2: `AnalyticalSeriesPanel` chart shell

**Files:**
- Create: `web/components/stock/panels/AnalyticalSeriesPanel.tsx`
- Test: `web/tests/components/volatility/AnalyticalSeriesPanel.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { AnalyticalSeriesPanel } from "@/components/stock/panels/AnalyticalSeriesPanel";

describe("AnalyticalSeriesPanel", () => {
  it("renders header, subheader, and headline", () => {
    render(
      <AnalyticalSeriesPanel
        title="VIX / VVIX"
        subtitle="Analytical time series"
        headline="+0.83σ"
      >
        <svg data-testid="chart" />
      </AnalyticalSeriesPanel>,
    );
    expect(screen.getByText("VIX / VVIX")).toBeInTheDocument();
    expect(screen.getByText("Analytical time series")).toBeInTheDocument();
    expect(screen.getByText("+0.83σ")).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toBeInTheDocument();
  });

  it("renders without subtitle/headline", () => {
    render(
      <AnalyticalSeriesPanel title="Plain">
        <span>body</span>
      </AnalyticalSeriesPanel>,
    );
    expect(screen.getByText("Plain")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- AnalyticalSeriesPanel`
Expected: module not found.

- [ ] **Step 3: Implement the panel**

```tsx
import type { ReactNode } from "react";

export function AnalyticalSeriesPanel({
  title,
  subtitle,
  headline,
  children,
}: {
  title: string;
  subtitle?: string;
  headline?: string;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 16,
        fontFamily: "var(--font-mono)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: subtitle || headline ? 4 : 12,
        }}
      >
        <div>
          {subtitle && (
            <div
              style={{
                fontSize: 9,
                letterSpacing: 1,
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {subtitle}
            </div>
          )}
          <div
            style={{
              fontSize: 11,
              letterSpacing: 1,
              textTransform: "uppercase",
              color: "var(--text-secondary)",
            }}
          >
            {title}
          </div>
        </div>
        {headline && (
          <div
            style={{
              fontSize: 16,
              color: "var(--accent-bg)",
              fontWeight: 600,
            }}
          >
            {headline}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test -- AnalyticalSeriesPanel`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/AnalyticalSeriesPanel.tsx web/tests/components/volatility/AnalyticalSeriesPanel.test.tsx
git commit -m "ui: AnalyticalSeriesPanel — shared chart shell (matches image 18/19 style)"
```

---

## Phase 6 — Frontend panels (one task per panel)

> All panel components are server components by default. They accept their slice of the `VolatilitySeriesResponse` and render a single SVG (or a histogram of divs). Width is `100%` of the container; the parent `VolatilityTab` sets the grid. Use `400` width × `260` height internally for the SVG viewBox — keeps math consistent across panels.

### Task 6.1: `VolMetricsCard`

**Files:**
- Create: `web/components/stock/panels/VolMetricsCard.tsx`
- Test: `web/tests/components/volatility/VolMetricsCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { VolMetricsCard } from "@/components/stock/panels/VolMetricsCard";

describe("VolMetricsCard", () => {
  it("renders all metric labels and VRP badge", () => {
    render(
      <VolMetricsCard
        header={{
          iv: "0.53",
          rv: "0.41",
          iv_rank: "21",
          iv_rank_1y: "41",
          iv_low_52w: "0.17",
          iv_high_52w: "0.34",
          rv_low_52w: "0.09",
          rv_high_52w: "0.37",
          iv_percentile_30d: "52",
          implied_move_30d_perc: "0.046",
          skew_25d: "-0.0079",
          vrp: "0.42",
          vrp_signal: "BUY_VOL",
          vrp_note: "IV rich vs RV — favors short premium",
        }}
      />,
    );
    expect(screen.getByText("IV (ATM)")).toBeInTheDocument();
    expect(screen.getByText("IV Rank 1y")).toBeInTheDocument();
    expect(screen.getByText(/BUY[_ ]VOL/)).toBeInTheDocument();
    expect(screen.getByText(/IV rich vs RV/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- VolMetricsCard`
Expected: module not found.

- [ ] **Step 3: Implement the card**

```tsx
import { MetricGrid, Metric } from "./MetricGrid";
import { fmtPct, fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";
import type { components } from "@/lib/types";

type Header = components["schemas"]["VolHeaderBlock"];

export function VolMetricsCard({ header }: { header: Header }) {
  const v = header.vrp != null ? toNum(header.vrp) ?? 0 : 0;
  const badgeColor =
    v > 0 ? "var(--positive)" : v < 0 ? "var(--negative)" : "var(--text-muted)";
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <h3
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-secondary)",
            letterSpacing: 1,
            textTransform: "uppercase",
            margin: 0,
          }}
        >
          Volatility
        </h3>
        {header.vrp_signal && (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              padding: "2px 8px",
              border: `1px solid ${badgeColor}`,
              borderRadius: 2,
              color: badgeColor,
              letterSpacing: 1,
            }}
          >
            VRP {fmtSigned(toNum(header.vrp), 2)} {header.vrp_signal}
          </span>
        )}
      </div>
      <MetricGrid cols={4}>
        <Metric label="IV (ATM)" value={fmtPct(toNum(header.iv), 1)} />
        <Metric label="RV" value={fmtPct(toNum(header.rv), 1)} />
        <Metric label="IV Rank" value={fmtDecimal(toNum(header.iv_rank), 0)} />
        <Metric label="IV Rank 1y" value={fmtDecimal(toNum(header.iv_rank_1y), 0)} />
        <Metric label="IV 52w Low" value={fmtPct(toNum(header.iv_low_52w), 1)} />
        <Metric label="IV 52w High" value={fmtPct(toNum(header.iv_high_52w), 1)} />
        <Metric label="RV 52w Low" value={fmtPct(toNum(header.rv_low_52w), 1)} />
        <Metric label="RV 52w High" value={fmtPct(toNum(header.rv_high_52w), 1)} />
        <Metric label="IV %ile 30d" value={fmtDecimal(toNum(header.iv_percentile_30d), 0)} />
        <Metric label="Implied Move 30d" value={fmtPct(toNum(header.implied_move_30d_perc), 1)} />
        <Metric label="Skew 25Δ" value={fmtSigned(toNum(header.skew_25d), 4)} />
      </MetricGrid>
      {header.vrp_note && (
        <div
          style={{
            marginTop: 12,
            padding: 10,
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            background: "var(--bg-panel)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-secondary)",
            whiteSpace: "pre-wrap",
          }}
        >
          {header.vrp_note}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test -- VolMetricsCard`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/VolMetricsCard.tsx web/tests/components/volatility/VolMetricsCard.test.tsx
git commit -m "ui: VolMetricsCard (merged Volatility + VRP header)"
```

---

### Task 6.2 – 6.10: Chart panels

Tasks 6.2 → 6.10 are structurally identical: a small SVG line/area chart inside an `AnalyticalSeriesPanel`. For each:

1. Write a vitest snapshot test that renders the component with a tiny fixed dataset (3-5 points) and asserts that an `<svg>` exists and the legend labels are present.
2. Implement the component with the colors and axes specified below.
3. Run the test, commit.

Each panel has its own props type derived from `components["schemas"]["VolatilitySeriesResponse"]`.

| Task | Component | Props slice | Axes / colors |
|---|---|---|---|
| 6.2 | `TermStructureChart` | `term_structure` | X = DTE (linear), Y = IV %; 4 strike lines using `--accent-bg`, `--accent-vol`, `--accent-warm`, `--accent-vivid` |
| 6.3 | `SmileChart` | `smile` | X = strike, Y = IV %; one line per expiry, same 4 colors; legend = expiry dates |
| 6.4 | `HvIvChart` | `hv_iv_history` | X = date, Y = vol %; IV in `--accent-bg`, RV in `--accent-warm` |
| 6.5 | `IvPercentileDistribution` | `iv_percentile_distribution` | Histogram bars in `--accent-bg`; current-IV vertical line in `--warning`; headline = `Nth %ile` |
| 6.6 | `IvOfIvChart` | `iv_of_iv` | Dual Y axis; IV (left, `--accent-bg`) + IV-of-IV (right, `--accent-vol`) |
| 6.7 | `RvSpyCorrChart` | `rv_spy_corr` | Dual Y axis; RV (left, `--accent-warm`) + SPY-corr (right, `--accent-vivid`) |
| 6.8 | `RegimeQuadrantChart` | `regime_quadrant` | Scatter; X = RVOL %ile (0–100), Y = SPY corr (-1..1); 4 quadrant labels in corners; latest dot bigger; state-key tile row below highlighting the active label in `--accent-bg` |
| 6.9 | `DivergenceOverlay` | `divergence`, `divergence_headline` | Dual line; IV-z in `--accent-warm`, RV-z in `--accent-vivid`; horizontal zero line; headline rendered in panel slot |
| 6.10 | `VrpSpreadPanel` | `vrp_spread`, `vrp_spread_headline` | Bars (positive teal, negative `--negative`) + smoothed-line overlay in `--accent-bg`; full width; headline in panel slot |

For each task:

- [ ] **Step 1: Write the failing test** (template — substitute the component name)

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { HvIvChart } from "@/components/stock/panels/HvIvChart";

describe("HvIvChart", () => {
  it("renders SVG with legend when data is present", () => {
    render(
      <HvIvChart
        data={[
          { date: "2026-05-11", iv: "0.50", rv: "0.40" },
          { date: "2026-05-12", iv: "0.52", rv: "0.41" },
          { date: "2026-05-13", iv: "0.51", rv: "0.42" },
        ]}
      />,
    );
    expect(screen.getByRole("img", { hidden: true })).toBeInTheDocument(); // svg
    expect(screen.getByText("IV")).toBeInTheDocument();
    expect(screen.getByText("RV")).toBeInTheDocument();
  });

  it("renders empty state when no data", () => {
    render(<HvIvChart data={[]} />);
    expect(screen.getByText(/insufficient/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test, confirm fail.**

Run: `cd web && npm test -- <ComponentName>`

- [ ] **Step 3: Implement** the SVG chart using `svgChart.ts` helpers and `AnalyticalSeriesPanel`. Width = `100%`, internal viewBox `0 0 400 260`, margin `{top:8, right:48, bottom:24, left:48}` (left+right=48 for dual-axis charts).

**Reference implementation for line-chart panels** — copy & adapt this skeleton for each:

```tsx
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";
import { linearScale, pathFromPoints } from "@/lib/svgChart";
import { toNum } from "@/lib/formatters";

export function HvIvChart({
  data,
}: {
  data: { date: string; iv: string | number | null; rv: string | number | null }[];
}) {
  if (data.length < 2) {
    return (
      <AnalyticalSeriesPanel title="HV / IV" subtitle="Analytical time series">
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Insufficient history (need ≥2d, have {data.length}d)
        </div>
      </AnalyticalSeriesPanel>
    );
  }
  const W = 400, H = 260, M = { top: 8, right: 16, bottom: 24, left: 36 };
  const ivs = data.map((d) => toNum(d.iv) ?? NaN);
  const rvs = data.map((d) => toNum(d.rv) ?? NaN);
  const lo = Math.min(...ivs, ...rvs);
  const hi = Math.max(...ivs, ...rvs);
  const x = linearScale([0, data.length - 1], [M.left, W - M.right]);
  const y = linearScale([lo, hi], [H - M.bottom, M.top]);
  const ivPath = pathFromPoints(
    ivs.map((v, i) => [x(i), y(v)] as [number, number]).filter(([, v]) => isFinite(v)),
  );
  const rvPath = pathFromPoints(
    rvs.map((v, i) => [x(i), y(v)] as [number, number]).filter(([, v]) => isFinite(v)),
  );
  return (
    <AnalyticalSeriesPanel title="HV / IV" subtitle="Analytical time series">
      <div style={{ display: "flex", gap: 12, fontSize: 10, marginBottom: 4 }}>
        <span style={{ color: "var(--accent-bg)" }}>— IV</span>
        <span style={{ color: "var(--accent-warm)" }}>— RV</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={260} role="img">
        <path d={ivPath} stroke="var(--accent-bg)" fill="none" strokeWidth={1.5} />
        <path d={rvPath} stroke="var(--accent-warm)" fill="none" strokeWidth={1.5} />
        {/* Y-axis labels (bottom & top) */}
        <text x={M.left - 4} y={H - M.bottom} fontSize={9} textAnchor="end" fill="var(--text-muted)">
          {(lo * 100).toFixed(1)}%
        </text>
        <text x={M.left - 4} y={M.top + 8} fontSize={9} textAnchor="end" fill="var(--text-muted)">
          {(hi * 100).toFixed(1)}%
        </text>
        {/* X-axis: first & last dates */}
        <text x={M.left} y={H - 4} fontSize={9} fill="var(--text-muted)">
          {data[0].date}
        </text>
        <text x={W - M.right} y={H - 4} fontSize={9} textAnchor="end" fill="var(--text-muted)">
          {data[data.length - 1].date}
        </text>
      </svg>
    </AnalyticalSeriesPanel>
  );
}
```

For `RegimeQuadrantChart` use `<circle>` per data point; for `VrpSpreadPanel` use `<rect>` for bars + `<path>` for line. For dual-axis charts (`IvOfIvChart`, `RvSpyCorrChart`) compute two independent Y scales (`yL`, `yR`) and emit a left-axis label on the left and a right-axis label on the right.

- [ ] **Step 4: Run test, confirm pass.**

- [ ] **Step 5: Commit.**

```bash
git add web/components/stock/panels/<Component>.tsx web/tests/components/volatility/<Component>.test.tsx
git commit -m "ui: <Component> for Volatility tab v2"
```

Repeat steps 1-5 for each of the nine panels in the table above. **Do not batch the commits** — one panel = one commit.

---

## Phase 7 — Compose the tab, remove VRP

### Task 7.1: Add `api.volatilitySeries` helper

**Files:**
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Add the helper**

Inside the `export const api = { … }` object, after `stockHistory`:

```ts
  volatilitySeries: (ticker: string) =>
    _fetch<Json<"/api/stock/{ticker}/volatility/series", "get">>(
      `/api/stock/${ticker}/volatility/series`,
    ),
```

Add a `VolatilitySeriesResponse` type alias near the existing ones:

```ts
type VolatilitySeriesResponse = Json<
  "/api/stock/{ticker}/volatility/series", "get"
>;
```

And re-export it from the bottom export list.

- [ ] **Step 2: Verify typecheck**

Run: `cd web && npm run typecheck`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add web/lib/api.ts
git commit -m "api: volatilitySeries client helper"
```

---

### Task 7.2: Rewrite `VolatilityTab.tsx`

**Files:**
- Modify: `web/components/stock/tabs/VolatilityTab.tsx`

- [ ] **Step 1: Replace the file contents**

```tsx
import { api } from "@/lib/api";
import type { components } from "@/lib/types";
import { VolMetricsCard } from "../panels/VolMetricsCard";
import { TermStructureChart } from "../panels/TermStructureChart";
import { SmileChart } from "../panels/SmileChart";
import { HvIvChart } from "../panels/HvIvChart";
import { IvPercentileDistribution } from "../panels/IvPercentileDistribution";
import { IvOfIvChart } from "../panels/IvOfIvChart";
import { RvSpyCorrChart } from "../panels/RvSpyCorrChart";
import { RegimeQuadrantChart } from "../panels/RegimeQuadrantChart";
import { DivergenceOverlay } from "../panels/DivergenceOverlay";
import { VrpSpreadPanel } from "../panels/VrpSpreadPanel";

type Report = components["schemas"]["SingleStockReport"];

export async function VolatilityTab({ report }: { report: Report }) {
  const series = await api.volatilitySeries(report.ticker);
  const buildingMsg =
    series.backfill_status === "running"
      ? "Building 1-year history… (≤30s)"
      : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <VolMetricsCard header={series.header} />

      {buildingMsg && (
        <div
          style={{
            padding: 8,
            background: "var(--bg-panel)",
            border: "1px dashed var(--warning)",
            borderRadius: 4,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--warning)",
          }}
        >
          {buildingMsg}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <TermStructureChart data={series.term_structure} />
        <SmileChart data={series.smile} />
        <HvIvChart data={series.hv_iv_history} />
        <IvPercentileDistribution data={series.iv_percentile_distribution} />
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          letterSpacing: 1,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginTop: 4,
        }}
      >
        Analytical time series
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <IvOfIvChart data={series.iv_of_iv} />
        <RvSpyCorrChart data={series.rv_spy_corr} />
        <RegimeQuadrantChart data={series.regime_quadrant} />
        <DivergenceOverlay
          data={series.divergence}
          headline={series.divergence_headline}
        />
      </div>

      <VrpSpreadPanel
        data={series.vrp_spread}
        headline={series.vrp_spread_headline}
      />
    </div>
  );
}
```

If the tab page passes `report` as a prop but doesn't yet `await` async server components, confirm by reading `web/app/stock/[ticker]/[tab]/page.tsx`. The watchlist rework already supports async server components for the Market Structure tab; the same pattern works here.

- [ ] **Step 2: Verify typecheck**

Run: `cd web && npm run typecheck`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add web/components/stock/tabs/VolatilityTab.tsx
git commit -m "ui: rewrite VolatilityTab composing new panels"
```

---

### Task 7.3: Remove `VrpTab` and its tab entry

**Files:**
- Delete: `web/components/stock/tabs/VrpTab.tsx`
- Modify: `web/components/stock/TabBar.tsx`
- Modify: `web/app/stock/[ticker]/[tab]/page.tsx`

- [ ] **Step 1: Delete `VrpTab.tsx`**

Run: `rm web/components/stock/tabs/VrpTab.tsx`

- [ ] **Step 2: Remove `["vrp", "VRP"]` from `TabBar.tsx`**

Edit `web/components/stock/TabBar.tsx`'s `TABS` array — drop the line `["vrp", "VRP"],`.

- [ ] **Step 3: Remove the `vrp` case from the tab-component switch**

Open `web/app/stock/[ticker]/[tab]/page.tsx` and remove anything referencing `VrpTab` / `case "vrp"`.

- [ ] **Step 4: Typecheck**

Run: `cd web && npm run typecheck`
Expected: exit 0 — no dangling imports.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/TabBar.tsx web/app/stock/[ticker]/[tab]/page.tsx
git rm web/components/stock/tabs/VrpTab.tsx
git commit -m "ui: remove VrpTab; merged into Volatility tab"
```

---

### Task 7.4: Manual browser smoke test

- [ ] **Step 1: Start dev stack**

Run (in the project root): `web/scripts/dev.sh` or `cd web && npm run dev` plus the API and worker per the watchlist rework's docs.

- [ ] **Step 2: Open `/stock/TSLA/volatility`**

Expected: header card with VRP badge; 2×2 grid of term/smile/hv-iv/distribution; 2×2 grid of analytical panels; full-width VRP spread bar+line at the bottom. No console errors.

- [ ] **Step 3: Open `/stock/<fresh-ticker>/volatility`**

Expected: yellow "Building 1-year history…" notice; partial data renders; reload after ~30s shows fully populated charts.

- [ ] **Step 4: Verify `/stock/TSLA/vrp` is gone**

Expected: 404 from Next.js, no stale tab on the tab bar.

- [ ] **Step 5: No commit** (manual verification).

---

## Phase 8 — Worker jobs

### Task 8.1: Daily SPY OHLC refresh

**Files:**
- Modify: `src/uw_scan/worker/<scheduler entry>` (locate via `grep -rn "BackgroundScheduler\|scheduler.add_job\|APScheduler" src/uw_scan/worker/`)
- Test: `tests/test_worker_volatility_jobs.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from uw_scan.worker.volatility_jobs import daily_spy_ohlc_refresh


def test_daily_spy_ohlc_refresh_writes_today(repo, monkeypatch):
    fake_prov = MagicMock()
    today = date.today()
    fake_prov.fetch_daily.return_value = [
        type("OhlcBar", (), {
            "ticker": "SPY", "date": today, "open": None, "high": None,
            "low": None, "close": Decimal("500"), "volume": None,
        })(),
    ]
    monkeypatch.setattr(
        "uw_scan.worker.volatility_jobs.MassiveOhlcProvider",
        lambda **_: fake_prov,
    )
    daily_spy_ohlc_refresh(repo=repo, api_key="dummy")
    rows = repo.fetch_index_ohlc_series("SPY", start=today, end=today)
    assert len(rows) == 1
    assert rows[0]["close"] == Decimal("500")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_worker_volatility_jobs.py -v`
Expected: ImportError.

- [ ] **Step 3: Create the jobs module**

Create `src/uw_scan/worker/volatility_jobs.py`:

```python
"""Volatility tab v2 worker jobs.

Two daily jobs:
- daily_spy_ohlc_refresh: pull yesterday+today SPY rows, upsert.
- nightly_vol_analytics_rollup: re-derive vrp_daily + stock_analytics_daily
  for watchlist tickers.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from uw_scan.cards import vol_series
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def daily_spy_ohlc_refresh(*, repo: Repository, api_key: str) -> None:
    today = date.today()
    start = today - timedelta(days=2)
    with MassiveOhlcProvider(api_key=api_key) as prov:
        bars = prov.fetch_daily("SPY", start=start, end=today)
    repo.upsert_index_ohlc_rows(bars)
    repo._conn.commit()
    log.info("daily_spy_ohlc_refresh: upserted %d rows", len(bars))


def nightly_vol_analytics_rollup(*, repo: Repository) -> None:
    tickers = repo.fetch_watchlist_tickers()  # use existing helper
    spy_history = repo.fetch_index_ohlc_series("SPY")
    for ticker in tickers:
        rv_history = repo.fetch_realized_vol_history(ticker, days=365)
        if not rv_history:
            continue
        vrp_df = vol_series.compute_vrp_series(rv_history)
        iv_of_iv_df = vol_series.compute_iv_of_iv(rv_history)
        rvol_df = vol_series.compute_rvol_and_percentile(
            [{"market_date": r["market_date"], "price": r["price"]}
             for r in rv_history]
        )
        corr_df = vol_series.compute_stock_spy_corr(
            [{"market_date": r["market_date"], "price": r["price"]}
             for r in rv_history],
            spy_history,
        )
        # Reuse the orchestrator's persist helpers — import inline to avoid
        # circular imports at module load.
        from uw_scan.reports.volatility_series import (
            _persist_stock_analytics,
            _persist_vrp_daily,
        )
        _persist_vrp_daily(repo, ticker, vrp_df)
        _persist_stock_analytics(repo, ticker, iv_of_iv_df, rvol_df, corr_df)
    repo._conn.commit()
    log.info("nightly_vol_analytics_rollup complete for %d tickers", len(tickers))
```

If `repo.fetch_watchlist_tickers` doesn't exist, find the actual helper that returns watchlist ticker strings (via `grep -n "watchlist" src/uw_scan/storage/repository.py | head -10`) and use that name.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_worker_volatility_jobs.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/volatility_jobs.py tests/test_worker_volatility_jobs.py
git commit -m "worker: daily SPY OHLC refresh + nightly vol analytics rollup"
```

---

### Task 8.2: Wire jobs into the APScheduler runner

**Files:**
- Modify: the scheduler entry file (locate it first)

- [ ] **Step 1: Locate the scheduler entry**

Run: `grep -rn "BackgroundScheduler\|add_job\|scheduler" src/uw_scan/worker/ | head -10`

- [ ] **Step 2: Add the two new jobs**

In the scheduler entry, alongside the existing scheduled jobs, append:

```python
from uw_scan.worker.volatility_jobs import (
    daily_spy_ohlc_refresh,
    nightly_vol_analytics_rollup,
)

scheduler.add_job(
    func=lambda: daily_spy_ohlc_refresh(repo=repo, api_key=cfg.massive_api_key),
    trigger="cron",
    hour=20, minute=30,  # 16:30 ET ≈ 20:30 UTC
    timezone="UTC",
    id="daily_spy_ohlc_refresh",
    replace_existing=True,
)
scheduler.add_job(
    func=lambda: nightly_vol_analytics_rollup(repo=repo),
    trigger="cron",
    hour=22, minute=0,  # 18:00 ET ≈ 22:00 UTC
    timezone="UTC",
    id="nightly_vol_analytics_rollup",
    replace_existing=True,
)
```

The exact `repo` and `cfg` references should match what the existing jobs use. If those jobs construct `repo` per-call, mirror that pattern instead of capturing it in a closure.

- [ ] **Step 3: Manually verify**

Start the worker (`uv run python -m uw_scan.worker.<entry>`) and confirm logs show the two new job IDs at scheduler startup.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/worker/<scheduler-entry>.py
git commit -m "worker: schedule SPY OHLC + vol analytics rollup jobs"
```

---

## Phase 9 — Final integration & QA

### Task 9.1: Manual QA matrix

- [ ] **Step 1: Open the tab on a high-vol ticker**

Open `/stock/TSLA/volatility` in the dev frontend. Verify:
- VRP badge color matches sign of VRP value
- Term Structure shows a downward curve (front-end IV > back-end IV is typical)
- Smile shows the characteristic U-shape
- HV/IV chart spans ~1 year
- IV %ile histogram shows current IV marked
- IV-of-IV / RV-SPY-corr panels: both lines render, dual axis
- Regime quadrant: 20 dots, latest dot bigger, state-key tile highlighted
- Divergence overlay: zero line, two lines, headline σ in top-right
- VRP spread: bars + line, headline shows e.g. `-5.2 pts | compressing -0.8 pts`

- [ ] **Step 2: Repeat for AAPL, NVDA, PG**

PG has historically low vol — confirm the empty-state branches fire when the rolling windows can't fill (e.g., very flat IV → divergence has small σ).

- [ ] **Step 3: Open the browser dev console**

Expected: zero React `key` warnings, zero `NaN`/`undefined` text leaks, zero network errors.

- [ ] **Step 4: No commit** (manual verification).

---

### Task 9.2: Full test sweep

- [ ] **Step 1: Run the full Python test suite**

Run: `uv run pytest -q`
Expected: exit 0, all tests pass.

- [ ] **Step 2: Run the frontend test suite**

Run: `cd web && npm test`
Expected: exit 0, all tests pass.

- [ ] **Step 3: Run typecheck and lint**

Run: `cd web && npm run typecheck && npm run lint`
Expected: exit 0.

- [ ] **Step 4: Commit any stragglers**

If any of the above produced changes (e.g., type regen, formatting), commit them as `chore: post-implementation cleanup`.

---

### Task 9.3: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin <branch>
```

- [ ] **Step 2: Create PR via `gh`**

```bash
gh pr create --title "Volatility tab v2 — merge VRP, add chart grid + analytical row" --body "$(cat <<'EOF'
## Summary
- Merges Volatility + VRP tabs into a single Volatility tab.
- Adds 9 charts: term structure, smile, HV/IV, IV %ile distribution, IV/IV-of-IV, RV/SPY-corr, regime quadrant, divergence overlay, full-width VRP spread bar+line.
- Persists derived series (vrp_daily, stock_analytics_daily, iv_smile_snapshots) and benchmark OHLC (index_ohlc_daily).
- New worker jobs: daily SPY OHLC refresh, nightly vol analytics rollup.

Spec: docs/superpowers/specs/2026-05-13-volatility-tab-v2-design.md
Plan: docs/superpowers/plans/2026-05-13-volatility-tab-v2.md

## Test plan
- [ ] `uv run pytest` passes
- [ ] `npm test` in `web/` passes
- [ ] `/stock/TSLA/volatility` renders all panels, no console errors
- [ ] `/stock/<fresh-ticker>/volatility` shows "Building 1-year history" notice, populates after ≤30s
- [ ] `/stock/TSLA/vrp` returns 404 (route removed)
EOF
)"
```

- [ ] **Step 3: No further commit** — the PR description is the deliverable.

---

## Self-review (post-write)

I walked the spec section-by-section against this plan:

- §1 Goals (1–7): all covered. Merge = §7.3; chart grid = §6.2–6.10; analytical row = §6.6–6.9; VRP spread bottom = §6.10; backfill = §4.4–4.5; persistence = §1.2–1.5 + §4.2; SPY ingest = §3.1.
- §2 Non-goals: nothing in plan exceeds those bounds.
- §3 Layout: matches `VolatilityTab.tsx` rewrite (Task 7.2).
- §4 Persistence: migration 014 in Task 0.1; repo helpers in Phase 1.
- §5.1 API shape: covered by Task 1.1 models + Task 4.5 router. `backfill_status` set per `count_realized_vol_history(t) < 90`.
- §6 Computation details: each has a deriver task (§6.1 = 2.1, §6.2 = 2.2, §6.3 = 2.4, §6.4 = 2.3, §6.5 = 2.5, §6.6 = 2.5). All have unit tests.
- §7 Frontend file plan: matches Phase 6 + 7.
- §8 Worker jobs: Task 8.1–8.2.
- §9 Testing: covered by per-task tests + Task 9.2 sweep.
- §10 Migration: Task 0.1 (migration) → Task 3.1 (SPY seed) → backend rollout (Phases 1–4) → frontend rollout (Phases 5–7) → worker (Phase 8).
- §11 Open questions: each one resolved inline in tasks (earnings markers deferred, smile interpolation in `iv_smile_builder` falls back to call-only / put-only, regime cold-start in `classify_regime_state(median_corr=None)` falls back to 0.5).

Type / name consistency: I cross-checked `VolHeaderBlock`, `TermStructureExpiryRow`, `SmileExpiryCurve`, `IvHvPoint`, `VrpDailyPoint`, `RegimeQuadrantPoint`, `RegimeQuadrantLatest`, `RegimeQuadrantBlock`, `DivergencePoint`, `IvOfIvPoint`, `RvCorrPoint`, `IvPercentileDistribution`, `IvHistogramBin`, `VolatilitySeriesResponse` — every name introduced in Phase 1 is consumed downstream with the same name. Repo helper names (`upsert_index_ohlc_rows`, `fetch_index_ohlc_series`, `upsert_iv_smile_rows`, `fetch_iv_smile_latest`, `upsert_vrp_daily_rows`, `fetch_vrp_daily_series`, `upsert_stock_analytics_rows`, `fetch_stock_analytics_series`, `count_realized_vol_history`, `fetch_realized_vol_history`, `fetch_volatility_stats_history`) are referenced consistently across Phase 4 and Phase 8.

Placeholder scan: a few tasks read "locate the X via grep …" — these are deliberate hand-offs because the existing codebase has names I have not pinned down (e.g., the APScheduler entry file, the watchlist-tickers helper, `Repository.connect()`'s actual call form). The plan is explicit that the implementer must look up the real name and not invent one. Otherwise, every step has concrete code, exact commands, and named files.

End of plan.
