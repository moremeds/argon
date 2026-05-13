# Flow Tab Merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge the per-stock `Flow` and `Tables` tabs into one `Flow` tab with a self-explaining snapshot grid, two daily timelines (volume + OI with P/C overlays), two strike-profile charts (volume + OI per expiry-strike), and two upgraded drill-down tables (Top Alerts + OI Movers with ASK% + FLAG).

**Architecture:** Eight focused commits within branch `feat/flow-tab-merge`, single PR to `main`. Backend lands first (schema → fetchers → model extensions → report wiring → worker), then frontend integrates without further backend changes. Both strike profiles share a single new table `uw_scan.option_chain_per_strike` (volume + OI per `(expiry, strike)`), sourced from an aggregation of UW's `option-contracts` payload.

**Tech Stack:** Python 3.13 (uv), FastAPI, Pydantic v2, psycopg 3, APScheduler 3, Postgres `option_wizard` DB schema `uw_scan`; Next.js 16 + React 19 + TypeScript with hand-rolled SVG; vitest + Playwright on the web side; pytest + pytest-postgresql on the python side.

**Spec:** `docs/superpowers/specs/2026-05-13-flow-tab-merge-design.md`

---

## File structure

### Backend (`src/uw_scan/`)

```
api/
└── endpoints.py                            MOD — add EndpointSlug.OPTIONS_VOLUME_DAILY + REGISTRY entry

models.py                                   MOD — add OptionsDailyRow + OptionChainPerStrikeRow;
                                                  extend OiChangeRow with prev_* aggressor fields;
                                                  extend SingleStockReport with options_timeline +
                                                  option_chain_per_strike

normalize.py                                MOD — add normalize_options_volume_daily

sources/uw.py                               MOD — add fetch_options_volume_daily;
                                                  bump fetch_option_contracts default limit

cards/option_chain.py                       NEW — aggregate raw option-contracts rows into
                                                  OptionChainPerStrikeRow grouped by (expiry,strike)

storage/repository.py                       MOD — upsert_options_volume_daily,
                                                  upsert_option_chain_per_strike,
                                                  extend oi_change insert with prev_* columns,
                                                  get_options_timeline,
                                                  get_option_chain_per_strike

storage/migrations/015_flow_tab_merge.sql   NEW — options_volume_daily + option_chain_per_strike
                                                  CREATE TABLEs, oi_change_events ALTERs

reports/single_stock.py                     MOD — fetch new rows from repo, attach to
                                                  SingleStockReport

worker/scheduler.py                         MOD — add daily flow_data_refresh job
worker/jobs/flow_data_refresh.py            NEW — fetch + persist per ticker

tests/unit/normalize/test_options_volume.py NEW
tests/unit/cards/test_option_chain.py       NEW
tests/integration/storage/test_flow_tab.py  NEW
tests/live/test_flow_tab_live.py            NEW — marked `live`, opt-in
```

### Frontend (`web/`)

```
lib/
├── types.ts                                MOD — regenerated via npm run gen:types
├── occ.ts                                  NEW — pure OCC option-symbol parser
└── uw-alert-rules.ts                       NEW — rule slug → human-readable map

components/stock/
├── TabBar.tsx                              MOD — remove "tables" entry
├── tabs/
│   ├── FlowTab.tsx                         REWRITE — thin client orchestrator
│   └── TablesTab.tsx                       DELETE
└── panels/
    ├── FlowSnapshotGrid.tsx                NEW — snapshot tiles + (i) tooltips
    ├── snapshotTooltips.ts                 NEW — static label → tooltip copy map
    ├── FlowTimelinePanel.tsx               NEW — dual-axis SVG line panel (volume OR OI variant)
    ├── StrikeProfilePanel.tsx              NEW — split bars + ITM/OTM bucket table
    │                                              (volume OR OI variant)
    ├── TopAlertsTable.tsx                  NEW — extracted from current FlowTab,
    │                                              adds rule-glossary tooltip on RULE header
    └── OiMoversTable.tsx                   NEW — upgraded columns (decoded symbol,
                                                  ASK%, FLAG, NOTIONAL)

app/stock/[ticker]/flow/page.tsx            MOD — route already exists; wire new FlowTab
app/stock/[ticker]/tables/                  DELETE the directory

tests/unit/occ.test.ts                      NEW
tests/unit/OiMoversTable.test.tsx           NEW
tests/unit/StrikeProfilePanel.test.tsx      NEW
tests/unit/FlowSnapshotGrid.test.tsx        NEW
tests/e2e/flow-tab.spec.ts                  NEW
```

---

## Task 1 — DB migration (Commit 1)

**Goal:** Land the two new tables and the `oi_change_events` ALTERs in one idempotent migration. After this, `bash scripts/migrate.sh` re-runs cleanly.

**Files:**
- Create: `src/uw_scan/storage/migrations/015_flow_tab_merge.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 015_flow_tab_merge.sql
-- Adds the two new tables that back the merged Flow tab + extends oi_change_events
-- with the aggressor/premium breakdown UW provides on the oi-change payload.

BEGIN;

-- ---------------------------------------------------------------------------
-- options_volume_daily: 180-day daily series of total options volume + OI,
-- ask/bid aggressor splits, bullish/bearish premium, built-in 3/7/30-day averages.
-- Source: UW /api/stock/{ticker}/options-volume
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.options_volume_daily (
    ticker                  TEXT         NOT NULL,
    trade_date              DATE         NOT NULL,
    call_volume             BIGINT,
    put_volume              BIGINT,
    call_volume_ask_side    BIGINT,
    call_volume_bid_side    BIGINT,
    put_volume_ask_side     BIGINT,
    put_volume_bid_side     BIGINT,
    call_premium            NUMERIC(20, 4),
    put_premium             NUMERIC(20, 4),
    net_call_premium        NUMERIC(20, 4),
    net_put_premium         NUMERIC(20, 4),
    bullish_premium         NUMERIC(20, 4),
    bearish_premium         NUMERIC(20, 4),
    call_open_interest      BIGINT,
    put_open_interest       BIGINT,
    avg_3_day_call_volume   NUMERIC(14, 4),
    avg_3_day_put_volume    NUMERIC(14, 4),
    avg_7_day_call_volume   NUMERIC(14, 4),
    avg_7_day_put_volume    NUMERIC(14, 4),
    avg_30_day_call_volume  NUMERIC(14, 4),
    avg_30_day_put_volume   NUMERIC(14, 4),
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, trade_date)
);
CREATE INDEX IF NOT EXISTS idx_ovd_ticker_date
    ON uw_scan.options_volume_daily(ticker, trade_date DESC);

-- ---------------------------------------------------------------------------
-- option_chain_per_strike: per-(expiry, strike) volume + OI snapshot.
-- Source: aggregation of UW /api/stock/{ticker}/option-contracts payload
-- (existing oi_by_strike has no expiry column and cannot feed the per-expiry
--  profile chart; this new table backs BOTH the volume and OI strike profiles).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS uw_scan.option_chain_per_strike (
    ticker        TEXT      NOT NULL,
    snapshot_date DATE      NOT NULL,
    expiry        DATE      NOT NULL,
    strike        NUMERIC(14, 4) NOT NULL,
    call_volume   BIGINT,
    put_volume    BIGINT,
    call_oi       BIGINT,
    put_oi        BIGINT,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, snapshot_date, expiry, strike)
);
CREATE INDEX IF NOT EXISTS idx_ocps_ticker_snap
    ON uw_scan.option_chain_per_strike(ticker, snapshot_date DESC);

-- ---------------------------------------------------------------------------
-- oi_change_events: add aggressor / premium breakdown UW returns on oi-change.
-- These columns describe the CURRENT row's volume split (UW names them prev_*
-- for legacy reasons — keep the UW naming for audit clarity).
-- ALTER TABLE … ADD COLUMN … NULL is a Postgres metadata-only op; safe on the
-- populated oi_change_events table.
-- ---------------------------------------------------------------------------
ALTER TABLE uw_scan.oi_change_events
    ADD COLUMN IF NOT EXISTS prev_ask_volume             BIGINT,
    ADD COLUMN IF NOT EXISTS prev_bid_volume             BIGINT,
    ADD COLUMN IF NOT EXISTS prev_mid_volume             BIGINT,
    ADD COLUMN IF NOT EXISTS prev_neutral_volume         BIGINT,
    ADD COLUMN IF NOT EXISTS prev_multi_leg_volume       BIGINT,
    ADD COLUMN IF NOT EXISTS prev_stock_multi_leg_volume BIGINT,
    ADD COLUMN IF NOT EXISTS prev_total_premium          NUMERIC(20, 4),
    ADD COLUMN IF NOT EXISTS last_ask                    NUMERIC(14, 4),
    ADD COLUMN IF NOT EXISTS last_bid                    NUMERIC(14, 4);

COMMIT;
```

- [ ] **Step 2: Apply migration locally**

Run: `bash scripts/migrate.sh`
Expected: prints the migration filename, exits 0. Tables visible via:
`psql "$DATABASE_URL" -c "\dt uw_scan.options_volume_daily"`
`psql "$DATABASE_URL" -c "\dt uw_scan.option_chain_per_strike"`

- [ ] **Step 3: Verify idempotency**

Run: `bash scripts/migrate.sh` (second time)
Expected: exits 0, no errors. Re-running produces no schema diff.

- [ ] **Step 4: Verify oi_change_events columns landed**

Run:
```bash
psql "$DATABASE_URL" -c "\d uw_scan.oi_change_events" | grep -E "prev_|last_"
```
Expected: 9 new columns listed.

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/flow-tab-merge
git add src/uw_scan/storage/migrations/015_flow_tab_merge.sql
git commit -m "db: add options_volume_daily + option_chain_per_strike, extend oi_change_events"
```

---

## Task 2 — Backend: wire UW options-volume + option-chain aggregation (Commit 2)

**Goal:** Add the `options-volume` fetcher, raise `option-contracts` limit, build the chain aggregator. End state: given a ticker, the worker can produce both `OptionsDailyRow[]` and `OptionChainPerStrikeRow[]` rows and persist them.

**Files:**
- Modify: `src/uw_scan/api/endpoints.py` (add slug + registry entry)
- Modify: `src/uw_scan/models.py` (add `OptionsDailyRow`, `OptionChainPerStrikeRow`)
- Modify: `src/uw_scan/normalize.py` (add `normalize_options_volume_daily`)
- Modify: `src/uw_scan/sources/uw.py` (add `fetch_options_volume_daily`, bump `fetch_option_contracts` limit)
- Create: `src/uw_scan/cards/option_chain.py` (aggregator)
- Modify: `src/uw_scan/storage/repository.py` (`upsert_options_volume_daily`, `upsert_option_chain_per_strike`)
- Create: `tests/unit/normalize/test_options_volume.py`
- Create: `tests/unit/cards/test_option_chain.py`
- Create: `tests/integration/storage/test_flow_tab.py`
- Create: `tests/live/test_flow_tab_live.py`
- Create: `tests/fixtures/options_volume_googl.json` (captured UW payload — small slice, 5 rows)
- Create: `tests/fixtures/option_contracts_googl.json` (captured UW payload — small slice, 20 contracts)

### 2a. EndpointSlug + REGISTRY entry

- [ ] **Step 1: Add the slug**

In `src/uw_scan/api/endpoints.py`, add to the `EndpointSlug` enum (after `BULK_SCREENER_STOCKS`):

```python
    OPTIONS_VOLUME_DAILY = "options_volume_daily"
```

And add to `REGISTRY`:

```python
    EndpointSlug.OPTIONS_VOLUME_DAILY: Endpoint(
        EndpointSlug.OPTIONS_VOLUME_DAILY,
        "/api/stock/{ticker}/options-volume",
        (),
    ),
```

- [ ] **Step 2: Confirm via build_path**

```bash
uv run python -c "from uw_scan.api.endpoints import EndpointSlug, build_path; print(build_path(EndpointSlug.OPTIONS_VOLUME_DAILY, ticker='GOOGL'))"
```
Expected: `/api/stock/GOOGL/options-volume`

### 2b. Models

- [ ] **Step 3: Add `OptionsDailyRow` to `models.py`**

After the existing `OptionContractRow` class:

```python
class OptionsDailyRow(_UwBase):
    """One row per trading day from UW /options-volume.

    `bullish_premium` here is whole-tape (UW), distinct from the
    alert-scoped `FlowSnapshot.bullish_premium`. Do not cross-plot.
    """

    date: _date
    call_volume: int | None = None
    put_volume: int | None = None
    call_volume_ask_side: int | None = None
    call_volume_bid_side: int | None = None
    put_volume_ask_side: int | None = None
    put_volume_bid_side: int | None = None
    call_premium: Decimal | None = None
    put_premium: Decimal | None = None
    net_call_premium: Decimal | None = None
    net_put_premium: Decimal | None = None
    bullish_premium: Decimal | None = None
    bearish_premium: Decimal | None = None
    call_open_interest: int | None = None
    put_open_interest: int | None = None
    avg_3_day_call_volume: Decimal | None = None
    avg_3_day_put_volume: Decimal | None = None
    avg_7_day_call_volume: Decimal | None = None
    avg_7_day_put_volume: Decimal | None = None
    avg_30_day_call_volume: Decimal | None = None
    avg_30_day_put_volume: Decimal | None = None
```

- [ ] **Step 4: Add `OptionChainPerStrikeRow` to `models.py`**

```python
class OptionChainPerStrikeRow(_UwBase):
    """Aggregated (expiry, strike) snapshot — both volume and OI in one row.

    Backs both strike-profile charts (Volume and OI variants).
    """

    expiry: _date
    strike: Decimal
    call_volume: int | None = None
    put_volume: int | None = None
    call_oi: int | None = None
    put_oi: int | None = None
```

### 2c. Normalizer + unit test (TDD)

- [ ] **Step 5: Capture a small UW fixture**

```bash
uv run python -c "
import json, os, httpx
key = os.environ['UW_SCAN_API_KEY']
r = httpx.get('https://api.unusualwhales.com/api/stock/GOOGL/options-volume?limit=5',
              headers={'Authorization': f'Bearer {key}'})
print(json.dumps(r.json(), indent=2))" > tests/fixtures/options_volume_googl.json
```
Expected: file contains `{ "data": [ { "date": "...", "call_volume": ..., ... } x5 ] }`.

- [ ] **Step 6: Write the failing normalizer test**

In `tests/unit/normalize/test_options_volume.py`:

```python
import json
from decimal import Decimal
from pathlib import Path

from uw_scan.normalize import normalize_options_volume_daily

FIXTURE = Path(__file__).parents[2] / "fixtures" / "options_volume_googl.json"


def test_normalize_options_volume_happy_path() -> None:
    payload = json.loads(FIXTURE.read_text())
    rows = normalize_options_volume_daily(payload)

    assert len(rows) == 5
    first = rows[0]
    assert first.call_volume is not None
    assert first.put_volume is not None
    assert isinstance(first.bullish_premium, Decimal) or first.bullish_premium is None
    # 30-day average present per UW contract
    assert first.avg_30_day_call_volume is not None


def test_normalize_options_volume_missing_data_key() -> None:
    rows = normalize_options_volume_daily({"data": []})
    assert rows == []
```

- [ ] **Step 7: Run the test — confirm it fails**

```bash
uv run pytest tests/unit/normalize/test_options_volume.py -v
```
Expected: ImportError on `normalize_options_volume_daily`.

- [ ] **Step 8: Implement the normalizer**

In `src/uw_scan/normalize.py`, add (and add `OptionsDailyRow` to the imports at top). Use the existing `_data_list` helper so a missing `data` key raises `NormalizationError` rather than silently returning an empty chart (matches the pattern at line 127 for `normalize_oi_change`).

```python
def normalize_options_volume_daily(payload: dict) -> list[OptionsDailyRow]:
    rows = _data_list(payload)
    return [OptionsDailyRow(**r) for r in rows]
```

And update the missing-data-key test in Step 6 from `{"data": []}` (which is a valid empty response) to a payload that omits `data` entirely — the test should now expect `NormalizationError`:

```python
def test_normalize_options_volume_missing_data_key() -> None:
    import pytest
    from uw_scan.normalize import NormalizationError
    with pytest.raises(NormalizationError):
        normalize_options_volume_daily({})


def test_normalize_options_volume_empty_data_is_ok() -> None:
    rows = normalize_options_volume_daily({"data": []})
    assert rows == []
```

- [ ] **Step 9: Run the test — confirm it passes**

```bash
uv run pytest tests/unit/normalize/test_options_volume.py -v
```
Expected: 2 passed.

### 2d. Fetcher + limit bump

- [ ] **Step 10: Add `fetch_options_volume_daily` in `sources/uw.py`**

Add the import `OptionsDailyRow` at the top of the file, then add (placed alongside the other fetchers, e.g. after `fetch_option_contracts_by_symbol`):

```python
def fetch_options_volume_daily(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    limit: int = 200,
) -> list[OptionsDailyRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTIONS_VOLUME_DAILY,
        ticker,
        params={"limit": limit},
    )
    return normalize.normalize_options_volume_daily(body)
```

- [ ] **Step 11: Bump `fetch_option_contracts` default limit to UW's cap**

Change the existing signature in `src/uw_scan/sources/uw.py:244` from `limit: int = 50` to `limit: int = 500`. **Pre-flight probe (2026-05-13) confirmed UW caps `option-contracts` at 500 rows per response regardless of the requested `limit`** — requesting more is harmless but won't return more rows. Leave the call shape unchanged.

- [ ] **Step 12: Payload coverage verified (probe already run)**

Probe results from 2026-05-13 pre-flight (verified before locking the plan):

```
SPY     rows=500  status=200
QQQ     rows=500  status=200
NVDA    rows=500  status=200
TSLA    rows=500  status=200
AAPL    rows=500  status=200
GOOGL   rows=500  status=200
```

Every active ticker returns exactly 500 contracts. UW orders by activity (sample SPY row shows `volume=563k` near a deep-OTM strike — active contracts cluster across the strike spectrum). The aggregator's `±60% × spot` filter (`MAX_PCT_FROM_SPOT`) will drop deep-OTM noise, so the 500-row payload is sufficient for the strike-profile use case.

**If a v1.1 follow-up needs the full chain** (e.g., for tail-risk panels), use UW's `/api/stock/{ticker}/option/expirations` to drive per-expiry sub-fetches. Out of scope for v1 — record the probe outcome in the commit message and move on.

### 2e. Aggregator + unit test (TDD)

- [ ] **Step 13: Capture an `option-contracts` fixture**

```bash
uv run python -c "
import json, os, httpx
key = os.environ['UW_SCAN_API_KEY']
r = httpx.get('https://api.unusualwhales.com/api/stock/GOOGL/option-contracts?limit=20',
              headers={'Authorization': f'Bearer {key}'})
print(json.dumps(r.json(), indent=2))" > tests/fixtures/option_contracts_googl.json
```
Expected: 20 contracts in `data`.

- [ ] **Step 14: Write the failing aggregator test**

In `tests/unit/cards/test_option_chain.py`:

```python
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from uw_scan.cards.option_chain import aggregate_chain_per_strike
from uw_scan.normalize import normalize_option_contracts

FIXTURE = Path(__file__).parents[2] / "fixtures" / "option_contracts_googl.json"


def test_aggregate_chain_per_strike_groups_by_expiry_strike() -> None:
    contracts = normalize_option_contracts(json.loads(FIXTURE.read_text()))
    rows = aggregate_chain_per_strike(
        contracts,
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )

    # No duplicate (expiry, strike) keys
    seen = {(r.expiry, r.strike) for r in rows}
    assert len(seen) == len(rows)

    # All rows respect filter window
    spot = Decimal("180.00")
    for r in rows:
        pct = abs(r.strike - spot) / spot
        assert pct <= Decimal("0.60")

    # At least one row has both call and put data on the same strike when
    # the fixture contains paired calls/puts
    paired = [r for r in rows if r.call_volume is not None and r.put_volume is not None]
    assert paired, "expected at least one (expiry, strike) with both call and put"


def test_aggregate_chain_per_strike_filters_far_expiries() -> None:
    contracts = normalize_option_contracts(json.loads(FIXTURE.read_text()))
    rows = aggregate_chain_per_strike(
        contracts,
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=30,  # tight window
        today=date(2026, 5, 13),
    )
    # Tight window should produce a strict subset
    rows_wide = aggregate_chain_per_strike(
        contracts,
        spot=Decimal("180.00"),
        max_pct_from_spot=Decimal("0.60"),
        max_dte_days=365,
        today=date(2026, 5, 13),
    )
    assert len(rows) <= len(rows_wide)
```

- [ ] **Step 15: Run the test — confirm it fails**

```bash
uv run pytest tests/unit/cards/test_option_chain.py -v
```
Expected: ImportError on `uw_scan.cards.option_chain`.

- [ ] **Step 16: Implement the aggregator**

Create `src/uw_scan/cards/option_chain.py`:

```python
"""Aggregate UW option-contracts rows into per-(expiry, strike) snapshots
that back the Flow tab's Volume + OI strike-profile charts."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable

from uw_scan.models import OptionChainPerStrikeRow, OptionContractRow

logger = logging.getLogger(__name__)

# OCC 21-char: ROOT (≤6, left-justified) | YYMMDD | C/P | STRIKE * 1000 (8 digits)
_OCC_RE = re.compile(r"^(?P<root>.{1,6}?)\s*(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<type>[CP])(?P<strike>\d{8})$")


def _parse_occ(symbol: str) -> tuple[date, str, Decimal] | None:
    m = _OCC_RE.match(symbol)
    if not m:
        return None
    yy = int(m["yy"])
    year = 2000 + yy if yy < 80 else 1900 + yy
    try:
        expiry = date(year, int(m["mm"]), int(m["dd"]))
    except ValueError:
        return None
    strike = Decimal(m["strike"]) / Decimal(1000)
    return expiry, m["type"], strike


def aggregate_chain_per_strike(
    contracts: Iterable[OptionContractRow],
    *,
    spot: Decimal,
    max_pct_from_spot: Decimal,
    max_dte_days: int,
    today: date,
) -> list[OptionChainPerStrikeRow]:
    """Group contracts by (expiry, strike), summing call/put volume and OI.

    Filters out strikes more than `max_pct_from_spot` from spot and expiries
    further than `max_dte_days` from `today`. Contracts whose OCC symbol fails
    to parse are dropped with a debug log — callers see those as "no data" at
    that strike.
    """

    grouped: dict[tuple[date, Decimal], dict[str, int]] = defaultdict(
        lambda: {"call_volume": 0, "put_volume": 0, "call_oi": 0, "put_oi": 0}
    )

    for c in contracts:
        parsed = _parse_occ(c.option_symbol)
        if parsed is None:
            logger.debug("unparseable OCC symbol skipped: %s", c.option_symbol)
            continue
        expiry, opt_type, strike = parsed
        dte = (expiry - today).days
        if dte < 0 or dte > max_dte_days:
            continue
        pct = abs(strike - spot) / spot if spot > 0 else Decimal(0)
        if pct > max_pct_from_spot:
            continue
        slot = grouped[(expiry, strike)]
        if opt_type == "C":
            slot["call_volume"] += c.volume or 0
            slot["call_oi"] += c.open_interest or 0
        else:
            slot["put_volume"] += c.volume or 0
            slot["put_oi"] += c.open_interest or 0

    rows = [
        OptionChainPerStrikeRow(
            expiry=expiry,
            strike=strike,
            call_volume=vals["call_volume"] or None,
            put_volume=vals["put_volume"] or None,
            call_oi=vals["call_oi"] or None,
            put_oi=vals["put_oi"] or None,
        )
        for (expiry, strike), vals in sorted(grouped.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    ]
    return rows
```

Also add a `cards/__init__.py` re-export if `cards/` is missing `option_chain` in `__init__.py`. Verify by:
```bash
ls src/uw_scan/cards/ && grep -l option_chain src/uw_scan/cards/__init__.py 2>/dev/null
```

- [ ] **Step 17: Run the test — confirm it passes**

```bash
uv run pytest tests/unit/cards/test_option_chain.py -v
```
Expected: 2 passed.

### 2f. Repository persistence + integration test

- [ ] **Step 18: Add upsert methods to `storage/repository.py`**

After `upsert_oi_per_strike_rows`:

```python
    def upsert_options_volume_daily(
        self, ticker: str, rows: Iterable[models.OptionsDailyRow]
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.options_volume_daily "
            "(ticker, trade_date, call_volume, put_volume, "
            " call_volume_ask_side, call_volume_bid_side, "
            " put_volume_ask_side, put_volume_bid_side, "
            " call_premium, put_premium, net_call_premium, net_put_premium, "
            " bullish_premium, bearish_premium, "
            " call_open_interest, put_open_interest, "
            " avg_3_day_call_volume, avg_3_day_put_volume, "
            " avg_7_day_call_volume, avg_7_day_put_volume, "
            " avg_30_day_call_volume, avg_30_day_put_volume) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, trade_date) DO UPDATE SET "
            "call_volume=EXCLUDED.call_volume, put_volume=EXCLUDED.put_volume, "
            "call_volume_ask_side=EXCLUDED.call_volume_ask_side, "
            "call_volume_bid_side=EXCLUDED.call_volume_bid_side, "
            "put_volume_ask_side=EXCLUDED.put_volume_ask_side, "
            "put_volume_bid_side=EXCLUDED.put_volume_bid_side, "
            "call_premium=EXCLUDED.call_premium, put_premium=EXCLUDED.put_premium, "
            "net_call_premium=EXCLUDED.net_call_premium, "
            "net_put_premium=EXCLUDED.net_put_premium, "
            "bullish_premium=EXCLUDED.bullish_premium, "
            "bearish_premium=EXCLUDED.bearish_premium, "
            "call_open_interest=EXCLUDED.call_open_interest, "
            "put_open_interest=EXCLUDED.put_open_interest, "
            "avg_3_day_call_volume=EXCLUDED.avg_3_day_call_volume, "
            "avg_3_day_put_volume=EXCLUDED.avg_3_day_put_volume, "
            "avg_7_day_call_volume=EXCLUDED.avg_7_day_call_volume, "
            "avg_7_day_put_volume=EXCLUDED.avg_7_day_put_volume, "
            "avg_30_day_call_volume=EXCLUDED.avg_30_day_call_volume, "
            "avg_30_day_put_volume=EXCLUDED.avg_30_day_put_volume"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker, r.date, r.call_volume, r.put_volume,
                        r.call_volume_ask_side, r.call_volume_bid_side,
                        r.put_volume_ask_side, r.put_volume_bid_side,
                        r.call_premium, r.put_premium,
                        r.net_call_premium, r.net_put_premium,
                        r.bullish_premium, r.bearish_premium,
                        r.call_open_interest, r.put_open_interest,
                        r.avg_3_day_call_volume, r.avg_3_day_put_volume,
                        r.avg_7_day_call_volume, r.avg_7_day_put_volume,
                        r.avg_30_day_call_volume, r.avg_30_day_put_volume,
                    ),
                )
        return len(rows)

    def upsert_option_chain_per_strike(
        self,
        ticker: str,
        snapshot_date: _date,
        rows: Iterable[models.OptionChainPerStrikeRow],
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.option_chain_per_strike "
            "(ticker, snapshot_date, expiry, strike, "
            " call_volume, put_volume, call_oi, put_oi) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, snapshot_date, expiry, strike) DO UPDATE SET "
            "call_volume=EXCLUDED.call_volume, put_volume=EXCLUDED.put_volume, "
            "call_oi=EXCLUDED.call_oi, put_oi=EXCLUDED.put_oi"
        )
        with self._conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    sql,
                    (
                        ticker, snapshot_date, r.expiry, r.strike,
                        r.call_volume, r.put_volume, r.call_oi, r.put_oi,
                    ),
                )
        return len(rows)

    def get_options_timeline(
        self, ticker: str, lookback_days: int = 180
    ) -> list[models.OptionsDailyRow]:
        sql = (
            f"SELECT trade_date, call_volume, put_volume, "
            f"call_volume_ask_side, call_volume_bid_side, "
            f"put_volume_ask_side, put_volume_bid_side, "
            f"call_premium, put_premium, net_call_premium, net_put_premium, "
            f"bullish_premium, bearish_premium, "
            f"call_open_interest, put_open_interest, "
            f"avg_3_day_call_volume, avg_3_day_put_volume, "
            f"avg_7_day_call_volume, avg_7_day_put_volume, "
            f"avg_30_day_call_volume, avg_30_day_put_volume "
            f"FROM {self._schema}.options_volume_daily "
            f"WHERE ticker = %s AND trade_date >= (CURRENT_DATE - %s::int) "
            f"ORDER BY trade_date ASC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, lookback_days))
            cols = [c.name for c in cur.description]
            return [
                models.OptionsDailyRow(**dict(zip(cols, row, strict=True),
                                              date=row[0]))
                for row in cur.fetchall()
            ]

    def get_option_chain_per_strike(
        self, ticker: str
    ) -> list[models.OptionChainPerStrikeRow]:
        sql = (
            f"SELECT expiry, strike, call_volume, put_volume, call_oi, put_oi "
            f"FROM {self._schema}.option_chain_per_strike "
            f"WHERE ticker = %s AND snapshot_date = ("
            f"  SELECT MAX(snapshot_date) FROM {self._schema}.option_chain_per_strike "
            f"  WHERE ticker = %s) "
            f"ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, ticker))
            cols = [c.name for c in cur.description]
            return [
                models.OptionChainPerStrikeRow(**dict(zip(cols, row, strict=True)))
                for row in cur.fetchall()
            ]
```

The `_date` import alias is already used in repository.py — check the imports at the top; if missing, add `from datetime import date as _date`.

- [ ] **Step 19: Write the integration test (pytest-postgresql)**

In `tests/integration/storage/test_flow_tab.py`:

```python
from datetime import date
from decimal import Decimal

from uw_scan.models import OptionChainPerStrikeRow, OptionsDailyRow
from uw_scan.storage.repository import Repository


def test_options_volume_daily_round_trip(pg_repo: Repository) -> None:
    pg_repo.upsert_options_volume_daily(
        "GOOGL",
        [
            OptionsDailyRow(
                date=date(2026, 5, 12),
                call_volume=1_000,
                put_volume=400,
                avg_30_day_call_volume=Decimal("950.5"),
            )
        ],
    )
    rows = pg_repo.get_options_timeline("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 1_000
    assert rows[0].avg_30_day_call_volume == Decimal("950.5")


def test_options_volume_daily_idempotent(pg_repo: Repository) -> None:
    sample = OptionsDailyRow(date=date(2026, 5, 12), call_volume=1_000)
    pg_repo.upsert_options_volume_daily("GOOGL", [sample])
    pg_repo.upsert_options_volume_daily(
        "GOOGL", [OptionsDailyRow(date=date(2026, 5, 12), call_volume=2_222)]
    )
    rows = pg_repo.get_options_timeline("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 2_222


def test_option_chain_per_strike_round_trip(pg_repo: Repository) -> None:
    snap = date(2026, 5, 13)
    pg_repo.upsert_option_chain_per_strike(
        "GOOGL",
        snap,
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 6, 19),
                strike=Decimal("180"),
                call_volume=500,
                put_volume=300,
                call_oi=10_000,
                put_oi=8_000,
            )
        ],
    )
    rows = pg_repo.get_option_chain_per_strike("GOOGL")
    assert len(rows) == 1
    assert rows[0].call_volume == 500
    assert rows[0].put_oi == 8_000
```

(`pg_repo` fixture is the existing repo fixture used in other integration tests — re-use it; check `tests/integration/storage/conftest.py` for its name and import path. If named differently in this repo, substitute.)

- [ ] **Step 20: Run the integration tests**

```bash
uv run pytest tests/integration/storage/test_flow_tab.py -v
```
Expected: 3 passed.

### 2g. Live test (opt-in)

- [ ] **Step 21: Write the live test (marked `live`)**

In `tests/live/test_flow_tab_live.py`:

```python
import os
import pytest

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.uw import fetch_options_volume_daily, fetch_option_contracts


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("UW_SCAN_API_KEY"), reason="UW_SCAN_API_KEY required")
def test_fetch_options_volume_daily_live(pg_repo) -> None:
    settings = Settings()
    client = UwClient(settings)
    rows = fetch_options_volume_daily(client, pg_repo, run_id=0, ticker="GOOGL", limit=20)
    assert len(rows) > 0
    first = rows[0]
    assert first.call_volume is not None
    assert first.avg_30_day_call_volume is not None  # contract regression


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("UW_SCAN_API_KEY"), reason="UW_SCAN_API_KEY required")
def test_fetch_option_contracts_returns_full_cap(pg_repo) -> None:
    settings = Settings()
    client = UwClient(settings)
    # Need a real scan_runs row so the audit-row FK is valid (api_request_audit.run_id
    # references scan_runs.run_id; passing run_id=0 would silently insert NULL
    # since the column is nullable, but using a real run keeps the audit trail clean).
    run_id = pg_repo.insert_scan_run("SPY", notes="live test")
    rows = fetch_option_contracts(client, pg_repo, run_id=run_id, ticker="SPY", limit=500)
    pg_repo.finish_scan_run(run_id)
    # Confirms the limit bump landed — SPY chain hits UW's 500-row cap.
    assert len(rows) == 500
```

- [ ] **Step 22: Confirm `live` marker is excluded by default**

```bash
uv run pytest tests/live/test_flow_tab_live.py -v
```
Expected: 2 deselected (no `--run-live` or similar). To run live: `uv run pytest -m live` (must have `UW_SCAN_API_KEY` set).

### 2h. Regenerate types + commit

- [ ] **Step 23: Run full unit + integration suite**

```bash
uv run pytest tests/unit tests/integration -v
```
Expected: all green.

- [ ] **Step 24: Commit**

```bash
git add src/uw_scan/api/endpoints.py src/uw_scan/models.py src/uw_scan/normalize.py \
        src/uw_scan/sources/uw.py src/uw_scan/cards/option_chain.py \
        src/uw_scan/storage/repository.py \
        tests/unit/normalize/test_options_volume.py \
        tests/unit/cards/test_option_chain.py \
        tests/integration/storage/test_flow_tab.py \
        tests/live/test_flow_tab_live.py \
        tests/fixtures/options_volume_googl.json \
        tests/fixtures/option_contracts_googl.json
git commit -m "backend: wire UW options-volume + option-chain aggregation"
```

The commit message body must include the SPY/QQQ/NVDA/TSLA/AAPL row-count probe output from Step 12. Example body line: `Probe: SPY=1500 (truncated→paginate?), QQQ=812, NVDA=945, TSLA=1100, AAPL=987` — adjust to actual numbers.

---

## Task 3 — Backend: extend OiChangeRow with prev_* aggressor fields (Commit 3)

**Goal:** UW's `oi-change` payload already carries the ask/bid/mid/neutral breakdown + premium + top-of-book at print. Surface them on the model + persist them. The frontend ASK% derivation in Task 6 depends on this.

**Files:**
- Modify: `src/uw_scan/models.py` (extend `OiChangeRow`)
- Modify: `src/uw_scan/normalize.py` (the existing `normalize_oi_change` should already kwargs-spread; verify)
- Modify: `src/uw_scan/storage/repository.py` (extend the `oi_change_events` INSERT)
- Create: `tests/fixtures/oi_change_googl.json` (captured payload, 5 rows)
- Modify: `tests/unit/normalize/test_*.py` (add `oi-change` aggressor field test) — or create `tests/unit/normalize/test_oi_change.py` if no equivalent exists.

- [ ] **Step 1: Capture the oi-change fixture**

```bash
uv run python -c "
import json, os, httpx
key = os.environ['UW_SCAN_API_KEY']
r = httpx.get('https://api.unusualwhales.com/api/stock/GOOGL/oi-change?limit=5',
              headers={'Authorization': f'Bearer {key}'})
print(json.dumps(r.json(), indent=2))" > tests/fixtures/oi_change_googl.json
```
Expected: rows include `prev_ask_volume`, `prev_bid_volume`, `prev_mid_volume`, `prev_neutral_volume`, `prev_total_premium`, `last_ask`, `last_bid`.

- [ ] **Step 2: Write the failing test**

In `tests/unit/normalize/test_oi_change.py`:

```python
import json
from decimal import Decimal
from pathlib import Path

from uw_scan.normalize import normalize_oi_change

FIXTURE = Path(__file__).parents[2] / "fixtures" / "oi_change_googl.json"


def test_oi_change_has_aggressor_fields() -> None:
    payload = json.loads(FIXTURE.read_text())
    rows = normalize_oi_change(payload)

    assert rows, "fixture should contain at least one row"
    assert all(hasattr(r, "prev_ask_volume") for r in rows)
    assert all(hasattr(r, "prev_bid_volume") for r in rows)
    assert all(hasattr(r, "prev_total_premium") for r in rows)
    assert all(hasattr(r, "last_ask") for r in rows)

    populated = [r for r in rows if r.prev_ask_volume is not None]
    assert populated, "at least one row should carry an aggressor breakdown"
    sample = populated[0]
    assert isinstance(sample.prev_ask_volume, int)
    assert isinstance(sample.prev_total_premium, Decimal) or sample.prev_total_premium is None
```

- [ ] **Step 3: Run the test — confirm it fails**

```bash
uv run pytest tests/unit/normalize/test_oi_change.py -v
```
Expected: `AttributeError: 'OiChangeRow' object has no attribute 'prev_ask_volume'` (Pydantic will drop unknown kwargs depending on config; if `model_config` has `extra="ignore"` it'll silently drop — the test still fails because the attr is missing).

- [ ] **Step 4: Extend `OiChangeRow` in `models.py`**

Add the new fields at the end of the class body (preserve existing fields). After `rnk: int | None = None`:

```python
    # Aggressor / premium breakdown — populated from UW oi-change payload.
    # See spec 2026-05-13-flow-tab-merge-design.md §4 for ASK% derivation.
    prev_ask_volume: int | None = None
    prev_bid_volume: int | None = None
    prev_mid_volume: int | None = None
    prev_neutral_volume: int | None = None
    prev_multi_leg_volume: int | None = None
    prev_stock_multi_leg_volume: int | None = None
    prev_total_premium: Decimal | None = None
    last_ask: Decimal | None = None
    last_bid: Decimal | None = None
```

- [ ] **Step 5: Verify normalizer kwargs-spreads (no code change expected)**

```bash
grep -n "normalize_oi_change" src/uw_scan/normalize.py
```
Expected: existing `normalize_oi_change` constructs `OiChangeRow(**r)` — the new fields will populate automatically. If it manually maps fields, expand it.

- [ ] **Step 6: Run the test — confirm it passes**

```bash
uv run pytest tests/unit/normalize/test_oi_change.py -v
```
Expected: 1 passed.

- [ ] **Step 7: Extend the repository INSERT**

In `src/uw_scan/storage/repository.py:537` (`insert_oi_change_rows`), update the column list, placeholders, and tuple. Replace the existing `INSERT INTO {schema}.oi_change_events (...) VALUES (...)` block with:

```python
        sql = (
            f"INSERT INTO {self._schema}.oi_change_events "
            "(run_id, underlying_symbol, option_symbol, curr_date, last_date, "
            " curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            " avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            " percentage_of_total, rnk, "
            " prev_ask_volume, prev_bid_volume, prev_mid_volume, prev_neutral_volume, "
            " prev_multi_leg_volume, prev_stock_multi_leg_volume, "
            " prev_total_premium, last_ask, last_bid) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, option_symbol) DO NOTHING"
        )
```

And the value tuple — after `r.rnk` append:

```python
                        r.prev_ask_volume,
                        r.prev_bid_volume,
                        r.prev_mid_volume,
                        r.prev_neutral_volume,
                        r.prev_multi_leg_volume,
                        r.prev_stock_multi_leg_volume,
                        r.prev_total_premium,
                        r.last_ask,
                        r.last_bid,
```

- [ ] **Step 7b: Extend the READ side too (`fetch_oi_change_top` SELECT)**

Without this, the frontend ASK% column will render `—` even after the migration + INSERT extension lands. In `src/uw_scan/storage/repository.py:941`, replace `fetch_oi_change_top`:

```python
    def fetch_oi_change_top(
        self, run_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return a candidate set wider than the UI's top-N so the frontend
        can re-sort by notional (volume * avg_price * 100) without losing
        high-notional rows that sit outside the rank-ordered first 10."""

        sql = (
            f"SELECT underlying_symbol, option_symbol, curr_date, last_date, "
            "curr_oi, last_oi, oi_diff_plain, oi_change, volume, trades, "
            "avg_price, last_fill, days_of_oi_increases, days_of_vol_greater_than_oi, "
            "percentage_of_total, rnk, "
            "prev_ask_volume, prev_bid_volume, prev_mid_volume, prev_neutral_volume, "
            "prev_multi_leg_volume, prev_stock_multi_leg_volume, "
            "prev_total_premium, last_ask, last_bid "
            f"FROM {self._schema}.oi_change_events "
            "WHERE run_id = %s "
            "ORDER BY (COALESCE(volume, 0) * COALESCE(avg_price, 0)) DESC NULLS LAST, rnk ASC "
            "LIMIT %s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, limit))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

The new ORDER BY is the server's best-notional approximation (we don't multiply by 100 — it's just a sort key). `limit=50` gives the UI enough candidates to re-sort cleanly to top 10; bump if the watchlist routinely has more high-notional outliers. Verify any caller that relied on `limit=10` default — `grep -n "fetch_oi_change_top" src/uw_scan/` — and update to `limit=50` to match the new default semantics, or pass explicit limits.

- [ ] **Step 8: Run repository integration tests to confirm no regression**

```bash
uv run pytest tests/integration/storage -v
```
Expected: all green (existing tests pass with the wider INSERT + SELECT).

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/models.py src/uw_scan/storage/repository.py \
        tests/unit/normalize/test_oi_change.py \
        tests/fixtures/oi_change_googl.json
git commit -m "backend: extend OiChangeRow with prev_* aggressor fields"
```

---

## Task 4 — Backend: include timeline + chain-per-strike in SingleStockReport (Commit 4)

**Goal:** Stitch the new repo getters into the report assembler, expose them on `SingleStockReport`, regenerate the openapi → `web/lib/types.ts` diff.

**Files:**
- Modify: `src/uw_scan/models.py` (extend `SingleStockReport`)
- Modify: `src/uw_scan/reports/single_stock.py` (call new repo methods, populate fields)
- Modify: `web/lib/types.ts` (regenerated; committed)
- Create: `tests/integration/reports/test_single_stock_flow.py`

- [ ] **Step 1: Extend `SingleStockReport`**

In `src/uw_scan/models.py:535`, add after `market_structure_levels`:

```python
    options_timeline: list[OptionsDailyRow] = []
    option_chain_per_strike: list[OptionChainPerStrikeRow] = []
    next_earnings_date: _date | None = None  # Promoted from FlowAlert.next_earnings_date for the Volume timeline marker
```

The `next_earnings_date` field already exists on `FlowAlert` (`models.py:50`) but is buried under each alert row. Promoting it to the top of `SingleStockReport` makes the timeline panel's marker wire-up trivial. `_date` is already imported in `models.py`.

- [ ] **Step 2: Wire the assembler**

In `src/uw_scan/reports/single_stock.py` (around line 419, the `SingleStockReport(...)` return), call the new getters before the return and pass them in. The actual assembler function name in this file may be `assemble_single_stock_report`, `build_report`, or similar — verify with `grep -n "^def " src/uw_scan/reports/single_stock.py` first, then edit accordingly. Locate the block that fetches existing data (look for `repo.fetch_oi_change_rows(...)` or similar) — add alongside:

```python
    options_timeline = repo.get_options_timeline(ticker, lookback_days=180)
    option_chain_per_strike = repo.get_option_chain_per_strike(ticker)

    # Promote next_earnings_date from FlowAlert payload (UW returns it per alert,
    # but they all share the underlying ticker's earnings date).
    next_earnings_date = next(
        (a.next_earnings_date for a in flow.top_alerts if a.next_earnings_date is not None),
        None,
    )
```

Then extend the `SingleStockReport(...)` constructor call to pass these three:

```python
    return SingleStockReport(
        # ... existing kwargs ...
        options_timeline=options_timeline,
        option_chain_per_strike=option_chain_per_strike,
        next_earnings_date=next_earnings_date,
    )
```

- [ ] **Step 3: Write the integration test**

In `tests/integration/reports/test_single_stock_flow.py`:

```python
from datetime import date
from decimal import Decimal

from uw_scan.models import OptionChainPerStrikeRow, OptionsDailyRow
from uw_scan.reports.single_stock import assemble_single_stock_report


def test_report_carries_options_timeline(pg_repo, seeded_run_id) -> None:
    pg_repo.upsert_options_volume_daily(
        "GOOGL",
        [
            OptionsDailyRow(date=date(2026, 5, 11), call_volume=900, put_volume=300),
            OptionsDailyRow(date=date(2026, 5, 12), call_volume=1_000, put_volume=400),
        ],
    )
    pg_repo.upsert_option_chain_per_strike(
        "GOOGL",
        date(2026, 5, 13),
        [
            OptionChainPerStrikeRow(
                expiry=date(2026, 6, 19),
                strike=Decimal("180"),
                call_volume=500,
                put_volume=300,
                call_oi=10_000,
                put_oi=8_000,
            )
        ],
    )

    report = assemble_single_stock_report(pg_repo, ticker="GOOGL", run_id=seeded_run_id)

    assert len(report.options_timeline) == 2
    assert report.options_timeline[-1].call_volume == 1_000
    assert len(report.option_chain_per_strike) == 1
    assert report.option_chain_per_strike[0].call_oi == 10_000
```

(`seeded_run_id` is a placeholder — match whatever existing fixture seeds `runs` with a run_id; check `tests/integration/conftest.py`.)

- [ ] **Step 4: Run the integration test**

```bash
uv run pytest tests/integration/reports/test_single_stock_flow.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Regenerate frontend types**

```bash
# Start API in another terminal/background:
uv run uvicorn uw_scan.api.server:app --port 8400 &
sleep 2
cd web && npm run gen:types
```
Expected: `web/lib/types.ts` diff includes `options_timeline` and `option_chain_per_strike` keys on the `SingleStockReport` interface. Kill the background API after.

- [ ] **Step 6: Run web typecheck**

```bash
cd web && npm run typecheck
```
Expected: passes. (No consumers of the new fields exist yet — the addition is type-only.)

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/models.py src/uw_scan/reports/single_stock.py \
        web/lib/types.ts \
        tests/integration/reports/test_single_stock_flow.py
git commit -m "backend: include options_timeline + option_chain_per_strike in SingleStockReport"
```

---

## Task 5 — Worker: nightly flow data refresh (Commit 5)

**Goal:** Schedule a daily job that calls both new fetchers + the chain aggregator and writes results to the new tables, per ticker on the watchlist.

**Files:**
- Create: `src/uw_scan/worker/jobs/flow_data_refresh.py`
- Modify: `src/uw_scan/worker/scheduler.py` (register the job)

- [ ] **Step 1: Create the job**

Verified existing-API anchors used below (read 2026-05-13):
- Watchlist: `repo.list_watchlist_cards() -> list[WatchlistCardRow]`, each card has `.ticker` and `.spot` (`storage/repository.py:1316`, `:1307`). No `scan_universe.load_watchlist_tickers` exists — that module is a hardcoded `S2_UNIVERSE` tuple with zero functions.
- Advisory lock: not yet wrapped on `Repository`. Inline `pg_try_advisory_lock` SQL pattern is the precedent (`api/routers/volatility.py:39`). We wrap it on `Repository` in Step 0 below.
- Scan run lifecycle (verified): `repo.insert_scan_run(ticker: str, notes: str = "") -> int` returns the new run_id (`repository.py:131-141`); `repo.finish_scan_run(run_id: int, status: str = "ok") -> None` finalizes it (`:143-149`). Methods require a ticker per run — so we allocate **one scan run per ticker** in the worker loop, not one per job. `api_request_audit.run_id` is nullable but using a real run keeps the audit trail clean (Codex C1).
- Market date: host could be HKT/UTC; settings carries `rth_tz` (verified in `worker/scheduler.py:150`). Use ET, not `date.today()` (Codex C7).
- Commits: psycopg connections aren't autocommit. The job must `repo.conn.commit()` after each ticker, and `repo.conn.rollback()` on per-ticker failure (Codex C2 / C13).

- [ ] **Step 0: Add a `try_advisory_lock` / `release_advisory_lock` helper pair on `Repository`**

In `src/uw_scan/storage/repository.py`, add (placed near other infra helpers; not behind any existing method):

```python
    def try_advisory_lock(self, key: int) -> bool:
        """Session-scoped pg_try_advisory_lock; returns True if the lock was acquired.

        Matches the pattern used by api/routers/volatility.py for single-flight
        guarded by an integer key. Always pair with release_advisory_lock(key)
        in a finally block.
        """

        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (key,))
            row = cur.fetchone()
            return bool(row and row[0])

    def release_advisory_lock(self, key: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (key,))
```

- [ ] **Step 1: Create the job**

In `src/uw_scan/worker/jobs/flow_data_refresh.py`:

```python
"""Nightly refresh of the Flow tab's data sources: ~180-day options-volume series
and the per-(expiry, strike) volume + OI snapshot for both strike-profile charts."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.cards.option_chain import aggregate_chain_per_strike
from uw_scan.config import Settings
from uw_scan.sources.uw import fetch_option_contracts, fetch_options_volume_daily
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

FLOW_REFRESH_LOCK = 91501   # mnemonic: migration 015 + 01
MAX_PCT_FROM_SPOT = Decimal("0.60")
MAX_DTE_DAYS = 365
OPTIONS_VOLUME_LOOKBACK = 200


def flow_data_refresh(*, repo: Repository, client: UwClient, settings: Settings) -> None:
    """Refresh the Flow-tab tables for every watchlist ticker. Single-flight via
    pg_try_advisory_lock; exits cleanly if the lock is held."""

    if not repo.try_advisory_lock(FLOW_REFRESH_LOCK):
        logger.info("flow_data_refresh: lock held; skipping this tick")
        return

    try:
        # Use ET market-date, NOT host date — host may be HKT/UTC.
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()

        cards = repo.list_watchlist_cards()
        for card in cards:
            ticker = card.ticker
            run_id = repo.insert_scan_run(ticker, notes="flow_data_refresh")
            try:
                vol_rows = fetch_options_volume_daily(
                    client, repo, run_id, ticker, limit=OPTIONS_VOLUME_LOOKBACK
                )
                n = repo.upsert_options_volume_daily(ticker, vol_rows)
                logger.info("flow_data_refresh: %s options_volume_daily rows=%d", ticker, n)

                spot = card.spot
                if spot is None or float(spot) <= 0:
                    logger.warning("flow_data_refresh: %s missing spot, skipping chain", ticker)
                    repo.finish_scan_run(run_id, status="ok")
                    repo.conn.commit()
                    continue

                contracts = fetch_option_contracts(client, repo, run_id, ticker, limit=500)
                chain_rows = aggregate_chain_per_strike(
                    contracts,
                    spot=Decimal(str(spot)),
                    max_pct_from_spot=MAX_PCT_FROM_SPOT,
                    max_dte_days=MAX_DTE_DAYS,
                    today=market_date,
                )
                # Full-snapshot semantics: delete any existing rows for the day
                # before re-inserting, so a shrinking chain doesn't leave stale strikes.
                repo.delete_option_chain_per_strike(ticker, market_date)
                m = repo.upsert_option_chain_per_strike(ticker, market_date, chain_rows)
                logger.info("flow_data_refresh: %s option_chain_per_strike rows=%d", ticker, m)
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
            except Exception as exc:  # noqa: BLE001
                # Abort the per-ticker transaction so the next ticker isn't stuck
                # in an aborted-transaction state. The scan run is left unfinished
                # (status remains in-progress) so failures are visible in the table.
                repo.conn.rollback()
                logger.exception("flow_data_refresh: %s failed: %r", ticker, exc)
    finally:
        repo.release_advisory_lock(FLOW_REFRESH_LOCK)
```

The scan-run helpers `insert_scan_run` and `finish_scan_run` are verified at `repository.py:131-149`. `delete_option_chain_per_strike` is new — add it next to `upsert_option_chain_per_strike` in Task 2 Step 18 (move it there rather than scattering across tasks):

```python
    def delete_option_chain_per_strike(self, ticker: str, snapshot_date: _date) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._schema}.option_chain_per_strike "
                f"WHERE ticker = %s AND snapshot_date = %s",
                (ticker, snapshot_date),
            )
            return cur.rowcount or 0
```

- [ ] **Step 2: Register the job in `scheduler.py`**

In `src/uw_scan/worker/scheduler.py`, near the existing nightly `_vol_analytics_rollup` block (around line 175), add (matching the existing import + private-function pattern):

```python
from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh as _flow_data_refresh_impl

# ... later in setup (alongside _vol_analytics_rollup):

def _flow_data_refresh() -> None:
    settings = build_settings()
    with _new_repo(settings) as repo:
        with _new_client(settings) as client:
            _flow_data_refresh_impl(repo=repo, client=client, settings=settings)

# ... and the registration, after _vol_analytics_rollup:

    sched.add_job(
        _flow_data_refresh,
        CronTrigger.from_crontab("15 18 * * 1-5", timezone=settings.rth_tz),
        id="nightly_flow_data_refresh",
        name="Nightly Flow tab data refresh",
    )
```

(Mirror the precise local-helper pattern used by `_vol_analytics_rollup`; `build_settings` / `_new_repo` / `_new_client` are placeholder names — use the actual helpers already in `scheduler.py`. The job receives `settings` rather than `run_id`; the job allocates its own scan run via `repo.start_scan_run`.)

- [ ] **Step 3: Smoke-test the job module**

```bash
uv run python -c "from uw_scan.worker.jobs.flow_data_refresh import flow_data_refresh; print(flow_data_refresh.__doc__)"
```
Expected: prints the docstring.

- [ ] **Step 4: Start the worker and confirm the job is scheduled**

```bash
uv run python -m uw_scan.worker.scheduler &
sleep 3
# Check the worker log:
tail -n 50 ~/.uw_scan/worker.log | grep flow_data_refresh
# Kill:
pkill -f uw_scan.worker.scheduler
```
Expected: a log line listing `nightly_flow_data_refresh` among scheduled jobs.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/flow_data_refresh.py \
        src/uw_scan/worker/scheduler.py
git commit -m "worker: nightly refresh for options-volume + option-chain-per-strike"
```

---

## Task 6 — Frontend: merged tab — snapshot + tables + OCC parser (Commit 6)

**Goal:** Delete `TablesTab`, rewrite `FlowTab` as a thin orchestrator, build the new snapshot grid, the rebuilt OI Movers table, the extracted Top Alerts table, and the supporting libs.

**Files:**
- Modify: `web/components/stock/TabBar.tsx` (remove `tables` entry)
- Delete: `web/components/stock/tabs/TablesTab.tsx` + `web/app/stock/[ticker]/tables/` (page route)
- Rewrite: `web/components/stock/tabs/FlowTab.tsx`
- Create: `web/components/stock/panels/FlowSnapshotGrid.tsx`
- Create: `web/components/stock/panels/snapshotTooltips.ts`
- Create: `web/components/stock/panels/TopAlertsTable.tsx`
- Create: `web/components/stock/panels/OiMoversTable.tsx`
- Create: `web/lib/occ.ts`
- Create: `web/lib/uw-alert-rules.ts`
- Create: `web/tests/unit/occ.test.ts`
- Create: `web/tests/unit/OiMoversTable.test.tsx`
- Create: `web/tests/unit/FlowSnapshotGrid.test.tsx`

### 6a. OCC parser (TDD)

- [ ] **Step 1: Write the failing test**

In `web/tests/unit/occ.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseOccSymbol } from "@/lib/occ";

describe("parseOccSymbol", () => {
  it("parses a standard put", () => {
    expect(parseOccSymbol("GOOGL260612P00335000")).toEqual({
      root: "GOOGL",
      expiry: "2026-06-12",
      type: "P",
      strike: 335,
    });
  });

  it("parses a standard call with fractional strike", () => {
    expect(parseOccSymbol("AAPL260117C00187500")).toEqual({
      root: "AAPL",
      expiry: "2026-01-17",
      type: "C",
      strike: 187.5,
    });
  });

  it("returns null for malformed input", () => {
    expect(parseOccSymbol("NOT-A-SYMBOL")).toBeNull();
    expect(parseOccSymbol("")).toBeNull();
    expect(parseOccSymbol("GOOGL260612X00335000")).toBeNull(); // X is invalid type
  });

  it("returns null for short root padding (defensive)", () => {
    // Trailing space padding is valid OCC; bare malformed is not.
    expect(parseOccSymbol("F   260612C00012500")).toEqual({
      root: "F",
      expiry: "2026-06-12",
      type: "C",
      strike: 12.5,
    });
  });
});
```

- [ ] **Step 2: Run the test — confirm it fails**

```bash
cd web && npx vitest run tests/unit/occ.test.ts
```
Expected: fails — file `lib/occ.ts` does not exist.

- [ ] **Step 3: Implement the parser**

In `web/lib/occ.ts`:

```ts
export type OccSymbol = {
  root: string;
  expiry: string;   // YYYY-MM-DD
  type: "C" | "P";
  strike: number;   // dollars
};

const OCC_RE = /^([A-Z.]{1,6})\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/;

export function parseOccSymbol(symbol: string): OccSymbol | null {
  const m = OCC_RE.exec(symbol);
  if (!m) return null;
  const [, root, yy, mm, dd, type, strikeStr] = m;
  const year = Number(yy) < 80 ? 2000 + Number(yy) : 1900 + Number(yy);
  const month = Number(mm);
  const day = Number(dd);
  // Strict round-trip check rejects impossible dates like Feb 30 (which
  // JavaScript Date silently normalizes to early March).
  const d = new Date(Date.UTC(year, month - 1, day));
  if (
    d.getUTCFullYear() !== year ||
    d.getUTCMonth() !== month - 1 ||
    d.getUTCDate() !== day
  ) {
    return null;
  }
  return {
    root,
    expiry: `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
    type: type as "C" | "P",
    strike: Number(strikeStr) / 1000,
  };
}
```

- [ ] **Step 4: Run the test — confirm it passes**

```bash
cd web && npx vitest run tests/unit/occ.test.ts
```
Expected: 4 passed.

### 6b. UW alert rules map

- [ ] **Step 5: Create the rules glossary**

In `web/lib/uw-alert-rules.ts`:

```ts
/** UW flow-alert rule slug → human-readable description.
 *
 * Source: UW alert rule taxonomy as observed in the flow-alerts payload.
 * Falls back to the raw slug for unknown rules — extend this map as new
 * rule slugs appear in production. */
export const UW_ALERT_RULES: Record<string, string> = {
  RepeatedHits:
    "Same strike hit repeatedly throughout the day — suggests a single buyer accumulating with multiple child orders.",
  RepeatedHitsDescendingFill:
    "Repeated hits with each fill priced lower than the previous — price-sensitive accumulator.",
  RepeatedHitsAscendingFill:
    "Repeated hits with each fill priced higher than the previous — buyer chasing, urgency signal.",
  AskSideAccumulation:
    "Sustained ask-side aggressor flow on the same strike — directional buyer pressure.",
  BidSideAccumulation:
    "Sustained bid-side aggressor flow — overwriter or yield-seeker side, opposite directional read.",
  LowHistoricVolume:
    "Today's volume far exceeds the contract's historical norm — fresh attention on a previously inactive strike.",
  VolumeGreaterThanOpenInterest:
    "Day's volume > prior open interest — by definition, opening positioning rather than churn.",
  // Extend as new rules appear; the UI falls back to the raw slug for keys not listed.
};

export function describeAlertRule(slug: string): string {
  return UW_ALERT_RULES[slug] ?? slug;
}
```

- [ ] **Step 6: Smoke-check imports**

```bash
cd web && npx tsc --noEmit
```
Expected: passes.

### 6c. Snapshot grid

- [ ] **Step 7: Create `snapshotTooltips.ts`**

In `web/components/stock/panels/snapshotTooltips.ts`:

```ts
export type TooltipCopy = {
  definition: string;
  benchmark: string;
};

export const SNAPSHOT_TOOLTIPS: Record<string, TooltipCopy> = {
  alerts: {
    definition:
      "Number of UW flow alerts fired today. Each alert is a rule-based pattern flagged by UW (repeated hits, ask-side accumulation, etc.).",
    benchmark: "Median active ticker: 15–40. >100 = elevated.",
  },
  netPremium: {
    definition:
      "Sum of bull-premium minus bear-premium across today's flow alerts. Positive = aggregate alert flow is bullish.",
    benchmark: "Sign and bull/bear ratio matter more than absolute magnitude.",
  },
  bullPremium: {
    definition:
      "Premium spent on alerts UW labels bullish (calls bought at ask, puts sold at bid).",
    benchmark: "Compare to BEAR PREMIUM; >2× = directional buyer bias.",
  },
  bearPremium: {
    definition:
      "Premium on alerts UW labels bearish (puts bought at ask, calls sold at bid).",
    benchmark: "Compare to BULL PREMIUM.",
  },
  askPremium: {
    definition:
      "Premium where the trade was filled at the ask — aggressive buyer side. Higher than BID PREMIUM = real demand.",
    benchmark: "ASK > BID by >20% = informed buying signal.",
  },
  bidPremium: {
    definition:
      "Premium filled at the bid — seller-aggressor side. Often dealer overwriting or institutional yield-seeking.",
    benchmark: "ASK < BID = dealer / overwriter dominance.",
  },
  darkPoolPrints: {
    definition:
      "Number of off-exchange (ATS) trades today. Dark-pool prints don't move the lit tape but cluster around institutional accumulation levels.",
    benchmark: "Spikes vs 5-day median are more meaningful than absolute count.",
  },
  darkPoolNotional: {
    definition:
      "Total dollar value of off-exchange prints. Compare to today's lit-tape dollar volume on the same name.",
    benchmark: "Dark / lit ratio > 30% = unusually heavy off-exchange activity.",
  },
  sharesAvail: {
    definition:
      "Hard-to-borrow availability. Falling availability + rising fee rate is the classic short-squeeze setup.",
    benchmark: "<100k shares for a mid-cap is tight.",
  },
  feeRate: {
    definition: "Borrow fee for shorting this stock (% annualized).",
    benchmark: ">5% is meaningfully expensive; >20% is acute squeeze territory.",
  },
  rebateRate: {
    definition: "Rebate paid to long holders lending out shares. Inverse signal to fee rate.",
    benchmark: "High rebate = high borrow demand.",
  },
};
```

- [ ] **Step 8: Write the snapshot grid component**

In `web/components/stock/panels/FlowSnapshotGrid.tsx`:

```tsx
import type { components } from "@/lib/types";
import { fmtDecimal, fmtSigned } from "@/lib/formatters";
import { SNAPSHOT_TOOLTIPS, type TooltipCopy } from "./snapshotTooltips";

type Report = components["schemas"]["SingleStockReport"];
type ShortData = NonNullable<Report["short_data"]>;

type Props = {
  flow: Report["flow"];
  darkPool: { prints: number; notional: Report["dark_pool_notional"] };
  shortData: ShortData | null;
};

export function FlowSnapshotGrid({ flow, darkPool, shortData }: Props) {
  return (
    <div
      role="region"
      aria-label="Flow snapshot"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
        gap: 12,
        padding: 16,
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
      }}
    >
      <Tile label="ALERTS" tip="alerts" value={fmtDecimal(flow.flow_count, 0)} />
      <Tile label="NET PREMIUM" tip="netPremium" value={fmtSigned(flow.net_premium)} />
      <Tile label="BULL PREMIUM" tip="bullPremium" value={fmtDecimal(flow.bull_premium, 0)} />

      <Tile label="BEAR PREMIUM" tip="bearPremium" value={fmtDecimal(flow.bear_premium, 0)} />
      <Tile label="ASK PREMIUM" tip="askPremium" value={fmtDecimal(flow.ask_side_premium, 0)} />
      <Tile label="BID PREMIUM" tip="bidPremium" value={fmtDecimal(flow.bid_side_premium, 0)} />

      <Tile label="DARK POOL PRINTS" tip="darkPoolPrints" value={fmtDecimal(darkPool.prints, 0)} />
      <Tile label="DARK POOL NOTIONAL" tip="darkPoolNotional" value={fmtDecimal(darkPool.notional, 0)} />
      <div /> {/* asymmetric tail OK; not padding with a placeholder tile */}

      <Tile label="SHARES AVAIL" tip="sharesAvail" value={fmtDecimal(shortData?.shares_available, 0)} />
      <Tile label="FEE RATE" tip="feeRate" value={fmtDecimal(shortData?.fee, 4)} />
      <Tile label="REBATE RATE" tip="rebateRate" value={fmtDecimal(shortData?.rebate, 4)} />
    </div>
  );
}

function Tile({ label, tip, value }: { label: string; tip: keyof typeof SNAPSHOT_TOOLTIPS; value: string }) {
  const t: TooltipCopy = SNAPSHOT_TOOLTIPS[tip];
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
        }}>
          {label}
        </span>
        <details style={{ display: "inline-block" }}>
          <summary
            aria-label={`${label} explanation`}
            style={{
              listStyle: "none",
              cursor: "help",
              fontSize: 10,
              color: "var(--text-muted)",
              border: "1px solid var(--border-dim)",
              borderRadius: "50%",
              width: 12,
              height: 12,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            i
          </summary>
          <div style={{
            position: "absolute",
            zIndex: 10,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            padding: 8,
            maxWidth: 280,
            fontSize: 11,
            color: "var(--text-primary)",
          }}>
            <p style={{ margin: 0 }}>{t.definition}</p>
            <p style={{ margin: "4px 0 0 0", color: "var(--text-secondary)" }}>{t.benchmark}</p>
          </div>
        </details>
      </div>
      <div style={{
        fontFamily: "var(--font-mono)",
        fontSize: 22,
        fontWeight: 700,
        color: "var(--text-primary)",
      }}>
        {value}
      </div>
    </div>
  );
}
```

Field names referenced (`flow.alert_count`, `flow.bullish_premium`, etc.) must match the generated types in `lib/types.ts` — substitute the actual field names if different.

- [ ] **Step 9: Write the snapshot test**

In `web/tests/unit/FlowSnapshotGrid.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlowSnapshotGrid } from "@/components/stock/panels/FlowSnapshotGrid";

const FIXTURE_FLOW = {
  ticker: "GOOGL",
  flow_count: 100,
  net_premium: "62000000",
  bull_premium: "66000000",
  bear_premium: "4000000",
  ask_side_premium: "30000000",
  bid_side_premium: "35000000",
  top_alerts: [],
} as unknown as Parameters<typeof FlowSnapshotGrid>[0]["flow"];

describe("FlowSnapshotGrid", () => {
  it("renders all 11 snapshot tiles with labels", () => {
    render(
      <FlowSnapshotGrid
        flow={FIXTURE_FLOW}
        darkPool={{ prints: 481, notional: "115000000" }}
        shortData={{ shares_available: 10_000_000, fee: "0.25", rebate: "3.38" } as never}
      />
    );

    for (const label of [
      "ALERTS", "NET PREMIUM", "BULL PREMIUM", "BEAR PREMIUM",
      "ASK PREMIUM", "BID PREMIUM",
      "DARK POOL PRINTS", "DARK POOL NOTIONAL",
      "SHARES AVAIL", "FEE RATE", "REBATE RATE",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows tooltip definition + benchmark on details expand", () => {
    render(
      <FlowSnapshotGrid
        flow={FIXTURE_FLOW}
        darkPool={{ prints: 0, notional: null }}
        shortData={null}
      />
    );
    expect(screen.getByText(/UW flow alerts/)).toBeInTheDocument();   // alerts definition
    expect(screen.getByText(/Median active ticker/)).toBeInTheDocument(); // alerts benchmark
  });
});
```

- [ ] **Step 10: Run snapshot grid tests**

```bash
cd web && npx vitest run tests/unit/FlowSnapshotGrid.test.tsx
```
Expected: 2 passed.

### 6d. OI Movers table

- [ ] **Step 11: Write the failing test**

In `web/tests/unit/OiMoversTable.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OiMoversTable } from "@/components/stock/panels/OiMoversTable";

// Normalize today to UTC midnight (matches dteDays() implementation).
const TODAY = new Date("2026-05-13T00:00:00Z");

const ROWS = [
  {
    option_symbol: "GOOGL260612P00170000",
    volume: 5_000,
    avg_price: "2.40",
    oi_diff_plain: -3_200,
    prev_ask_volume: 1_000,
    prev_bid_volume: 3_500,
    prev_mid_volume: 500,
    prev_neutral_volume: 0,
  },
  {
    option_symbol: "GOOGL260515C00180000",
    volume: 12_000,
    avg_price: "1.20",
    oi_diff_plain: 11_000,
    prev_ask_volume: 9_000,
    prev_bid_volume: 800,
    prev_mid_volume: 200,
    prev_neutral_volume: 0,
  },
];

describe("OiMoversTable", () => {
  it("decodes OCC symbols into TYPE / EXPIRY / STRIKE columns", () => {
    render(<OiMoversTable rows={ROWS as never} spot={180} today={TODAY} />);
    expect(screen.getByText("P")).toBeInTheDocument();
    expect(screen.getByText("C")).toBeInTheDocument();
    expect(screen.getByText("2026-06-12")).toBeInTheDocument();
    expect(screen.getByText("2026-05-15")).toBeInTheDocument();
    expect(screen.getByText("$170.00")).toBeInTheDocument();
  });

  it("flags 0DTE on a same-day expiry", () => {
    const row = {
      option_symbol: "GOOGL260513C00180000",
      volume: 100, avg_price: "0.10", oi_diff_plain: 50,
      prev_ask_volume: 0, prev_bid_volume: 0, prev_mid_volume: 0, prev_neutral_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("0DTE LOTTO")).toBeInTheDocument();
  });

  it("computes ASK% from prev_* aggressor split", () => {
    render(<OiMoversTable rows={ROWS as never} spot={180} today={TODAY} />);
    // Second row: ask=9000 / (9000+800+200+0) = 90.0%
    expect(screen.getByText("90.0%")).toBeInTheDocument();
    // First row: 1000 / 5000 = 20.0%
    expect(screen.getByText("20.0%")).toBeInTheDocument();
  });

  it("renders em-dash when aggressor denominator is zero", () => {
    const row = {
      option_symbol: "GOOGL260612C00180000",
      volume: 10, avg_price: "0.10", oi_diff_plain: 1,
      prev_ask_volume: 0, prev_bid_volume: 0, prev_mid_volume: 0, prev_neutral_volume: 0,
    };
    render(<OiMoversTable rows={[row] as never} spot={180} today={TODAY} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
```

- [ ] **Step 12: Run the test — confirm it fails**

```bash
cd web && npx vitest run tests/unit/OiMoversTable.test.tsx
```
Expected: ImportError.

- [ ] **Step 13: Implement `OiMoversTable`**

In `web/components/stock/panels/OiMoversTable.tsx`:

```tsx
import type { components } from "@/lib/types";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";
import { parseOccSymbol } from "@/lib/occ";

type OiRow = components["schemas"]["OiChangeRow"];

type Props = {
  rows: OiRow[];
  spot: number;
  today?: Date;
};

function dteDays(expiryIso: string, today: Date): number {
  // Both dates anchored at UTC midnight; integer day count, no time-of-day drift.
  const e = new Date(`${expiryIso}T00:00:00Z`);
  const todayMid = new Date(Date.UTC(
    today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate(),
  ));
  return Math.floor((e.getTime() - todayMid.getTime()) / 86_400_000);
}

function fmtUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

function volOiColor(ratio: number | null): string {
  if (ratio == null) return "var(--text-muted)";
  if (ratio < 0.8) return "var(--text-muted)";
  if (ratio <= 1.5) return "var(--positive)";
  if (ratio <= 5) return "var(--text-primary)";
  return "var(--warning)";
}

function flagsFor(opts: {
  type: "C" | "P";
  dte: number;
  volOi: number | null;
  askPct: number | null;
  oiDiff: number;
}): string[] {
  const f: string[] = [];
  if (opts.dte === 0) f.push("0DTE LOTTO");
  if (opts.dte > 365) f.push("LEAPS");
  if (opts.volOi != null && opts.volOi > 5) f.push("CHURN");
  // OPENING means new positioning — requires positive ΔOI AND aggressive ask-side flow.
  // Negative ΔOI rows in the clean-opening band are closing positions, not opening.
  // ask_pct must be known (drop the prior "or unknown" fallback — see spec §4 fix).
  if (
    opts.volOi != null && opts.volOi >= 0.8 && opts.volOi <= 1.5 &&
    opts.oiDiff > 0 &&
    opts.askPct != null && opts.askPct > 60
  ) {
    const arrow = opts.type === "C" ? "↑" : "↓";
    f.push(`OPENING ${arrow}`);
  }
  return f;
}

export function OiMoversTable({ rows, spot, today = new Date() }: Props) {
  const sorted = rows
    .map((r) => {
      const occ = parseOccSymbol(r.option_symbol);
      const askDenom =
        (r.prev_ask_volume ?? 0) +
        (r.prev_bid_volume ?? 0) +
        (r.prev_mid_volume ?? 0) +
        (r.prev_neutral_volume ?? 0);
      const askPct = askDenom > 0 ? ((r.prev_ask_volume ?? 0) / askDenom) * 100 : null;
      const vol = r.volume ?? 0;
      const oiDiff = r.oi_diff_plain ?? 0;
      const volOi = oiDiff !== 0 ? Math.abs(vol / oiDiff) : null;
      const avgPrice = toNum(r.avg_price) ?? 0;
      const notional = vol * avgPrice * 100;
      // occ === null → render the raw symbol with blank decoded fields (spec §4
      // fallback). Don't drop the row — it'd hide adjusted/special symbols.
      return {
        r, occ, askPct, volOi,
        dte: occ ? dteDays(occ.expiry, today) : null,
        pctSpot: occ ? ((occ.strike - spot) / spot) * 100 : null,
        notional,
      };
    })
    .sort((a, b) => b.notional - a.notional)
    .slice(0, 10);

  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: 12 }}>
      <thead>
        <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
          <th>TYPE</th><th>EXPIRY</th><th>STRIKE</th><th>DTE</th><th>%SPOT</th>
          <th>ΔOI</th><th>VOL/|ΔOI|</th><th>NOTIONAL</th><th>ASK%</th><th>FLAG</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(({ r, occ, askPct, volOi, dte, pctSpot, notional }) => {
          const flags = occ
            ? flagsFor({
                type: occ.type,
                dte: dte ?? -1,
                volOi,
                askPct,
                oiDiff: r.oi_diff_plain ?? 0,
              })
            : [];
          return (
            <tr key={r.option_symbol} style={{ borderTop: "1px solid var(--border-dim)" }}>
              <td>{occ?.type ?? r.option_symbol}</td>
              <td>{occ?.expiry ?? "—"}</td>
              <td>{occ ? `$${occ.strike.toFixed(2)}` : "—"}</td>
              <td>{dte ?? "—"}</td>
              <td
                style={{
                  color: pctSpot == null ? undefined : pctSpot >= 0 ? "var(--positive)" : "var(--negative)",
                }}
              >
                {pctSpot == null ? "—" : `${fmtSigned(pctSpot, 2)}%`}
              </td>
              <td>{fmtDecimal(r.oi_diff_plain, 0)}</td>
              <td style={{ color: volOiColor(volOi) }}>
                {volOi == null ? "—" : volOi.toFixed(2)}
              </td>
              <td>{fmtUsd(notional)}</td>
              <td>{askPct == null ? "—" : `${askPct.toFixed(1)}%`}</td>
              <td>{flags.join(" · ")}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 14: Run the test — confirm it passes**

```bash
cd web && npx vitest run tests/unit/OiMoversTable.test.tsx
```
Expected: 4 passed.

### 6e. Top Alerts table

- [ ] **Step 15: Extract `TopAlertsTable` from the current FlowTab**

In `web/components/stock/panels/TopAlertsTable.tsx`:

```tsx
import type { components } from "@/lib/types";
import { fmtDecimal } from "@/lib/formatters";
import { describeAlertRule, UW_ALERT_RULES } from "@/lib/uw-alert-rules";

type Alert = components["schemas"]["FlowAlert"];

export function TopAlertsTable({ alerts }: { alerts: Alert[] }) {
  const rows = [...alerts]
    .sort((a, b) => Number(b.total_premium ?? 0) - Number(a.total_premium ?? 0))
    .slice(0, 10);

  return (
    <div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <thead>
          <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
            <th>ID</th>
            <th>
              RULE
              <details style={{ display: "inline-block", marginLeft: 4 }}>
                <summary aria-label="Rule glossary" style={{ listStyle: "none", cursor: "help" }}>(i)</summary>
                <div style={{
                  position: "absolute", zIndex: 10,
                  background: "var(--bg-panel)", border: "1px solid var(--border-dim)",
                  padding: 8, maxWidth: 360, fontSize: 11,
                }}>
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {Object.entries(UW_ALERT_RULES).map(([slug, desc]) => (
                      <li key={slug}><strong>{slug}</strong>: {desc}</li>
                    ))}
                  </ul>
                </div>
              </details>
            </th>
            <th>PREMIUM</th>
            <th>VOL/OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id} style={{ borderTop: "1px solid var(--border-dim)" }}>
              <td>{a.id?.slice(0, 8)}</td>
              <td title={describeAlertRule(a.alert_rule ?? "")}>{a.alert_rule}</td>
              <td>{fmtDecimal(a.total_premium, 0)}</td>
              <td>{fmtDecimal(a.volume_oi_ratio, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

(Field names verified against `src/uw_scan/models.py:24` — `FlowAlert` has `id`, `alert_rule`, `total_premium`, `volume_oi_ratio`. After `gen:types` these are surfaced as `components["schemas"]["FlowAlert"]`.)

### 6f. Rewrite FlowTab + TabBar + delete TablesTab

- [ ] **Step 16: Rewrite `FlowTab.tsx`**

Replace the entire file `web/components/stock/tabs/FlowTab.tsx`:

```tsx
"use client";
import type { components } from "@/lib/types";
import { FlowSnapshotGrid } from "@/components/stock/panels/FlowSnapshotGrid";
import { OiMoversTable } from "@/components/stock/panels/OiMoversTable";
import { TopAlertsTable } from "@/components/stock/panels/TopAlertsTable";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

type Props = {
  report: Report;
};

export function FlowTab({ report }: Props) {
  // Read spot from the report itself — keeps FlowTab's signature single-prop
  // (matches MarketStructureTab/VolatilityTab) so app/stock/[ticker]/[tab]/page.tsx
  // dispatcher needs no changes when wiring this tab.
  const spot = toNum(report.market_structure?.spot) ?? 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, padding: 16 }}>
      <FlowSnapshotGrid
        flow={report.flow}
        darkPool={{
          prints: report.dark_pool_print_count,
          notional: report.dark_pool_notional,
        }}
        shortData={report.short_data ?? null}
      />

      {/* Section: Timelines + Strike profiles — added in Tasks 7 + 8 */}

      <section>
        <h3 style={{
          fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: 1.5,
          textTransform: "uppercase", color: "var(--text-muted)", margin: "8px 0",
        }}>
          Top Alerts
        </h3>
        <TopAlertsTable alerts={report.flow.top_alerts ?? []} />
      </section>

      <section>
        <h3 style={{
          fontFamily: "var(--font-mono)", fontSize: 12, letterSpacing: 1.5,
          textTransform: "uppercase", color: "var(--text-muted)", margin: "8px 0",
        }}>
          OI Change — Top Movers
        </h3>
        <OiMoversTable rows={report.oi_change_top ?? []} spot={spot} />
      </section>
    </div>
  );
}
```

- [ ] **Step 17: Remove `tables` from `TabBar.tsx`**

In `web/components/stock/TabBar.tsx`, delete the line:

```tsx
  ["tables", "Tables"],
```

- [ ] **Step 18: Delete `TablesTab.tsx` and remove from the dispatcher**

```bash
rm web/components/stock/tabs/TablesTab.tsx
```

The tab routes are dispatched dynamically by `web/app/stock/[ticker]/[tab]/page.tsx` (single page, switch on `tab` slug — no per-tab directory). Remove both the import and the `tables: TablesTab` entry from the `TABS` map in that file:

```tsx
// In web/app/stock/[ticker]/[tab]/page.tsx
// Delete the import line:
import { TablesTab } from "@/components/stock/tabs/TablesTab";
// And the TABS map entry:
  tables: TablesTab,
```

After the deletion, `/stock/<TICKER>/tables` will 404 via `notFound()` — that's the intended UX once the tab no longer exists in the TabBar.

- [ ] **Step 19: Run typecheck + unit tests**

```bash
cd web && npm run typecheck && npm run test -- --run
```
Expected: green. Resolve any type mismatches against `lib/types.ts` field names inline.

- [ ] **Step 20: Verify in browser**

```bash
bash scripts/dev.sh &
# Wait ~5s for all three processes:
sleep 6
open "http://127.0.0.1:3001/stock/GOOGL/flow"
```
Expected:
- New snapshot grid renders with `(i)` tooltips that open on click.
- Tables tab is gone from the TabBar.
- OI Movers shows decoded Type/Expiry/Strike + DTE + %SPOT + Vol/|ΔOI| + Notional + ASK% + FLAG columns. ASK% shows real values, not em-dash.
- Top Alerts header has a clickable `(i)` glossary.

Kill the dev processes after eyeballing.

- [ ] **Step 21: Commit**

```bash
git add web/components/stock/TabBar.tsx \
        web/app/stock/\[ticker\]/\[tab\]/page.tsx \
        web/components/stock/tabs/FlowTab.tsx \
        web/components/stock/panels/FlowSnapshotGrid.tsx \
        web/components/stock/panels/snapshotTooltips.ts \
        web/components/stock/panels/TopAlertsTable.tsx \
        web/components/stock/panels/OiMoversTable.tsx \
        web/lib/occ.ts web/lib/uw-alert-rules.ts \
        web/tests/unit/occ.test.ts \
        web/tests/unit/OiMoversTable.test.tsx \
        web/tests/unit/FlowSnapshotGrid.test.tsx
git rm web/components/stock/tabs/TablesTab.tsx
git commit -m "web: merge Flow + Tables tab — snapshot grid, OCC parser, upgraded tables"
```

---

## Task 7 — Frontend: Volume + OI timeline panels (Commit 7)

**Goal:** Two stacked dual-axis line charts in the Flow tab. Series A on the left axis (volume / OI), Series B on the right axis (put/call ratio). Volume timeline gets earnings markers.

**Files:**
- Create: `web/components/stock/panels/FlowTimelinePanel.tsx`
- Modify: `web/components/stock/tabs/FlowTab.tsx` (mount the two panels)
- Create: `web/tests/unit/FlowTimelinePanel.test.tsx`

- [ ] **Step 1: Confirm `report.next_earnings_date` is present**

```bash
grep -E "next_earnings_date" /Users/chenxi/projects/unusual-whales/web/lib/types.ts | head -5
```
Expected: `next_earnings_date: string | null` on `SingleStockReport` (added in Task 4 Step 1). The Volume timeline wraps it as a singleton-or-empty list for the `markers` prop.

- [ ] **Step 2: Write the failing test**

In `web/tests/unit/FlowTimelinePanel.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlowTimelinePanel } from "@/components/stock/panels/FlowTimelinePanel";

describe("FlowTimelinePanel", () => {
  const dates = ["2026-05-09", "2026-05-10", "2026-05-11", "2026-05-12"];

  it("renders both series paths in SVG", () => {
    const { container } = render(
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{ label: "Volume", values: [1000, 1500, 2000, 1200], color: "var(--accent-bg)" }}
        secondary={{ label: "P/C", values: [0.6, 0.8, 0.9, 0.7], color: "var(--accent-warm)" }}
        dates={dates}
      />,
    );
    const paths = container.querySelectorAll("svg path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });

  it("renders earnings marker lines when supplied", () => {
    const { container } = render(
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{ label: "Volume", values: [1000, 1500, 2000, 1200], color: "var(--accent-bg)" }}
        secondary={{ label: "P/C", values: [0.6, 0.8, 0.9, 0.7], color: "var(--accent-warm)" }}
        dates={dates}
        markers={["2026-05-10"]}
      />,
    );
    const markerLines = container.querySelectorAll("[data-testid='earnings-marker']");
    expect(markerLines.length).toBe(1);
  });

  it("drops series points where value is null", () => {
    const { container } = render(
      <FlowTimelinePanel
        title="OI"
        primary={{ label: "OI", values: [1000, null as never, 2000], color: "var(--accent-bg)" }}
        secondary={{ label: "P/C OI", values: [0.6, 0.8, 0.7], color: "var(--accent-warm)" }}
        dates={["2026-05-09", "2026-05-10", "2026-05-11"]}
      />,
    );
    // Path should still render; nulls are gaps, not zeroes.
    expect(container.querySelector("svg")).not.toBeNull();
  });
});
```

- [ ] **Step 3: Run the test — confirm it fails**

```bash
cd web && npx vitest run tests/unit/FlowTimelinePanel.test.tsx
```
Expected: ImportError.

- [ ] **Step 4: Implement `FlowTimelinePanel`**

In `web/components/stock/panels/FlowTimelinePanel.tsx`:

```tsx
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Series = {
  label: string;
  values: Array<number | null>;
  color: string;
};

type Props = {
  title: string;
  primary: Series;
  secondary: Series;
  dates: string[];
  markers?: string[];
};

const WIDTH = 560;
const HEIGHT = 220;
const PAD = { top: 16, right: 36, bottom: 26, left: 40 };

export function FlowTimelinePanel({ title, primary, secondary, dates, markers = [] }: Props) {
  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;

  // finiteDomain returns {lo, hi, count} | null — destructure carefully and
  // bail out when either series has <2 finite values (svgChart contract).
  const primaryDom = finiteDomain(primary.values);
  const secondaryDom = finiteDomain(secondary.values);
  if (!primaryDom || !secondaryDom) {
    return (
      <AnalyticalSeriesPanel title={title} subtitle="NO DATA">
        <div style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)", fontSize: 11 }}>
          NO DATA
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  const x = linearScale([0, Math.max(dates.length - 1, 1)], [PAD.left, PAD.left + innerW]);
  const yLeft = linearScale([primaryDom.lo, primaryDom.hi], [PAD.top + innerH, PAD.top]);
  const yRight = linearScale([secondaryDom.lo, secondaryDom.hi], [PAD.top + innerH, PAD.top]);

  const primaryPath = pathFromPoints(
    primary.values
      .map((v, i) => (v == null ? null : ([x(i), yLeft(v)] as [number, number])))
      .filter((p): p is [number, number] => p !== null),
  );
  const secondaryPath = pathFromPoints(
    secondary.values
      .map((v, i) => (v == null ? null : ([x(i), yRight(v)] as [number, number])))
      .filter((p): p is [number, number] => p !== null),
  );

  const dateIndex = new Map(dates.map((d, i) => [d, i]));

  return (
    <AnalyticalSeriesPanel title={title} subtitle={`${primary.label} · ${secondary.label} (right)`}>
      <svg
        role="img"
        aria-label={`${title} timeline`}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        style={{ width: "100%", height: "auto" }}
      >
        <title>{`${title}: ${primary.label} (left axis), ${secondary.label} (right axis)`}</title>

        {markers.map((m) => {
          const i = dateIndex.get(m);
          if (i == null) return null;
          return (
            <line
              key={m}
              data-testid="earnings-marker"
              x1={x(i)} x2={x(i)} y1={PAD.top} y2={PAD.top + innerH}
              stroke="var(--warning)" strokeDasharray="3 3" strokeOpacity={0.6}
            />
          );
        })}

        <path d={primaryPath} fill="none" stroke={primary.color} strokeWidth={1.5} />
        <path d={secondaryPath} fill="none" stroke={secondary.color} strokeWidth={1.5} />
      </svg>
    </AnalyticalSeriesPanel>
  );
}
```

(`AnalyticalSeriesPanel` is the existing wrapper — check the actual import path / props signature in `web/components/stock/panels/AnalyticalSeriesPanel.tsx` and align.)

- [ ] **Step 5: Run the test — confirm it passes**

```bash
cd web && npx vitest run tests/unit/FlowTimelinePanel.test.tsx
```
Expected: 3 passed.

- [ ] **Step 6: Mount the panels in `FlowTab.tsx`**

Insert above the Top Alerts `<section>`:

```tsx
{(() => {
  const t = report.options_timeline ?? [];
  const dates = t.map((r) => r.date);
  const totalVol = t.map((r) =>
    r.call_volume == null || r.put_volume == null ? null : r.call_volume + r.put_volume,
  );
  // P/C ratio: only the DENOMINATOR (call_volume) must be non-zero. A real
  // put_volume of 0 should chart as 0, not get filtered out as "missing".
  const pcVol = t.map((r) =>
    r.call_volume != null && r.call_volume !== 0 && r.put_volume != null
      ? r.put_volume / r.call_volume
      : null,
  );
  const totalOi = t.map((r) =>
    r.call_open_interest == null || r.put_open_interest == null
      ? null
      : r.call_open_interest + r.put_open_interest,
  );
  const pcOi = t.map((r) =>
    r.call_open_interest != null && r.call_open_interest !== 0 && r.put_open_interest != null
      ? r.put_open_interest / r.call_open_interest
      : null,
  );
  const earnings = report.next_earnings_date ? [report.next_earnings_date] : [];

  if (t.length === 0) {
    return <div style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>NO TIMELINE DATA</div>;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{ label: "Volume", values: totalVol, color: "var(--accent-bg)" }}
        secondary={{ label: "P/C Vol", values: pcVol, color: "var(--accent-warm)" }}
        dates={dates}
        markers={earnings}
      />
      <FlowTimelinePanel
        title="OPEN INTEREST"
        primary={{ label: "OI", values: totalOi, color: "var(--accent-bg)" }}
        secondary={{ label: "P/C OI", values: pcOi, color: "var(--accent-warm)" }}
        dates={dates}
      />
    </div>
  );
})()}
```

Import the panel at the top of `FlowTab.tsx`:
```tsx
import { FlowTimelinePanel } from "@/components/stock/panels/FlowTimelinePanel";
```

- [ ] **Step 7: Typecheck + unit + dev-server eyeball**

```bash
cd web && npm run typecheck && npm run test -- --run
bash scripts/dev.sh &
sleep 6
open "http://127.0.0.1:3001/stock/GOOGL/flow"
```
Expected: two side-by-side line charts above the tables. Vertical earnings markers visible on the Volume panel.

- [ ] **Step 8: Commit**

```bash
git add web/components/stock/panels/FlowTimelinePanel.tsx \
        web/components/stock/tabs/FlowTab.tsx \
        web/tests/unit/FlowTimelinePanel.test.tsx
git commit -m "web: Volume + OI timeline panels with earnings markers"
```

---

## Task 8 — Frontend: Volume + OI strike-profile panels (Commit 8)

**Goal:** Two stacked profile charts that share a single expiry-picker + strike-range control on the parent tab. Bars above zero = calls (green); below zero = puts (red). Bucket table below each chart shows ITM/OTM sums.

**Files:**
- Create: `web/components/stock/panels/StrikeProfilePanel.tsx`
- Modify: `web/components/stock/tabs/FlowTab.tsx` (add state + mount)
- Create: `web/tests/unit/StrikeProfilePanel.test.tsx`
- Create: `web/tests/e2e/flow-tab.spec.ts`

- [ ] **Step 1: Write the failing unit test**

In `web/tests/unit/StrikeProfilePanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StrikeProfilePanel } from "@/components/stock/panels/StrikeProfilePanel";

const ROWS = [
  { expiry: "2026-06-19", strike: "170", call_volume: 100, put_volume: 200, call_oi: 1000, put_oi: 2000 },
  { expiry: "2026-06-19", strike: "180", call_volume: 500, put_volume: 100, call_oi: 5000, put_oi: 1000 },
  { expiry: "2026-06-19", strike: "190", call_volume: 300, put_volume: 50,  call_oi: 3000, put_oi: 500 },
  { expiry: "2026-09-18", strike: "180", call_volume: 200, put_volume: 50,  call_oi: 2000, put_oi: 500 },
];

describe("StrikeProfilePanel", () => {
  it("computes ITM/OTM bucket sums for calls and puts (volume variant)", () => {
    render(
      <StrikeProfilePanel
        title="VOLUME BY STRIKE"
        metric="volume"
        rows={ROWS as never}
        selectedExpiries={["2026-06-19"]}
        strikeRangePct={0.3}
        spot={180}
      />
    );
    // Calls: ITM (strike < spot) = 170 → 100; OTM (≥180) = 500 + 300 = 800
    expect(screen.getByText("100")).toBeInTheDocument();   // ITM calls
    expect(screen.getByText("800")).toBeInTheDocument();   // OTM calls
    // Puts: ITM (strike > spot) = 190 → 50; OTM (≤180) = 200 + 100 = 300
    expect(screen.getByText("50")).toBeInTheDocument();    // ITM puts
    expect(screen.getByText("300")).toBeInTheDocument();   // OTM puts
  });

  it("uses oi columns when metric='oi'", () => {
    render(
      <StrikeProfilePanel
        title="OI BY STRIKE"
        metric="oi"
        rows={ROWS as never}
        selectedExpiries={["2026-06-19"]}
        strikeRangePct={0.3}
        spot={180}
      />
    );
    // OTM calls OI = 5000 + 3000 = 8000
    expect(screen.getByText("8000")).toBeInTheDocument();
  });

  it("filters by selected expiries", () => {
    const { rerender } = render(
      <StrikeProfilePanel
        title="VOLUME BY STRIKE"
        metric="volume"
        rows={ROWS as never}
        selectedExpiries={["2026-09-18"]}
        strikeRangePct={0.3}
        spot={180}
      />
    );
    // Only 1 row matches; OTM calls vol = 200 (strike 180 is OTM call boundary: strike ≥ spot)
    expect(screen.getByText("200")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test — confirm it fails**

```bash
cd web && npx vitest run tests/unit/StrikeProfilePanel.test.tsx
```
Expected: ImportError.

- [ ] **Step 3: Implement the panel**

In `web/components/stock/panels/StrikeProfilePanel.tsx`:

```tsx
import type { components } from "@/lib/types";
import { linearScale } from "@/lib/svgChart";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type ChainRow = components["schemas"]["OptionChainPerStrikeRow"];

type Props = {
  title: string;
  metric: "volume" | "oi";
  rows: ChainRow[];
  selectedExpiries: string[];   // ISO YYYY-MM-DD
  strikeRangePct: number;        // e.g. 0.30 = ±30%
  spot: number;
};

const WIDTH = 560;
const HEIGHT = 240;
const PAD = { top: 16, right: 16, bottom: 26, left: 40 };

export function StrikeProfilePanel({ title, metric, rows, selectedExpiries, strikeRangePct, spot }: Props) {
  const minStrike = spot * (1 - strikeRangePct);
  const maxStrike = spot * (1 + strikeRangePct);
  const callKey = metric === "volume" ? "call_volume" : "call_oi";
  const putKey = metric === "volume" ? "put_volume" : "put_oi";

  const selected = new Set(selectedExpiries);

  // Aggregate by strike across selected expiries
  const byStrike = new Map<number, { call: number; put: number }>();
  for (const r of rows) {
    if (!selected.has(r.expiry)) continue;
    const s = Number(r.strike);
    if (s < minStrike || s > maxStrike) continue;
    const slot = byStrike.get(s) ?? { call: 0, put: 0 };
    slot.call += Number(r[callKey] ?? 0);
    slot.put += Number(r[putKey] ?? 0);
    byStrike.set(s, slot);
  }

  const sorted = [...byStrike.entries()].sort(([a], [b]) => a - b);
  const maxBar = Math.max(1, ...sorted.flatMap(([, v]) => [v.call, v.put]));

  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const x = linearScale([minStrike, maxStrike], [PAD.left, PAD.left + innerW]);
  const yCall = linearScale([0, maxBar], [HEIGHT / 2, PAD.top]);                  // up
  const yPut  = linearScale([0, maxBar], [HEIGHT / 2, HEIGHT - PAD.bottom]);      // down
  const barW = Math.max(2, innerW / Math.max(sorted.length, 1) - 2);

  // ITM/OTM bucket math
  let itmCall = 0, otmCall = 0, itmPut = 0, otmPut = 0;
  for (const [strike, v] of sorted) {
    if (strike < spot) { itmCall += v.call; otmPut += v.put; }
    else { otmCall += v.call; itmPut += v.put; }
  }

  return (
    <AnalyticalSeriesPanel title={title} subtitle={`${selectedExpiries.length} expirie(s) · ±${(strikeRangePct * 100).toFixed(0)}% spot`}>
      <svg role="img" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: "100%", height: "auto" }}>
        <title>{title}: calls (green, above 0) / puts (red, below 0)</title>
        {/* zero line */}
        <line x1={PAD.left} x2={PAD.left + innerW} y1={HEIGHT / 2} y2={HEIGHT / 2} stroke="var(--border-dim)" />
        {/* spot marker */}
        <line x1={x(spot)} x2={x(spot)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="var(--text-muted)" strokeDasharray="3 3" />
        {sorted.map(([strike, v]) => (
          <g key={strike}>
            <rect
              x={x(strike) - barW / 2}
              y={yCall(v.call)}
              width={barW}
              height={HEIGHT / 2 - yCall(v.call)}
              fill="var(--positive)"
            />
            <rect
              x={x(strike) - barW / 2}
              y={HEIGHT / 2}
              width={barW}
              height={yPut(v.put) - HEIGHT / 2}
              fill="var(--negative)"
            />
          </g>
        ))}
      </svg>

      <table style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 11, marginTop: 8 }}>
        <thead>
          <tr style={{ color: "var(--text-muted)" }}>
            <th></th><th>Total</th><th>ITM</th><th>OTM</th>
          </tr>
        </thead>
        <tbody>
          <tr><td>Calls</td><td>{itmCall + otmCall}</td><td>{itmCall}</td><td>{otmCall}</td></tr>
          <tr><td>Puts</td><td>{itmPut + otmPut}</td><td>{itmPut}</td><td>{otmPut}</td></tr>
          <tr><td>Total</td>
              <td>{itmCall + otmCall + itmPut + otmPut}</td>
              <td>{itmCall + itmPut}</td>
              <td>{otmCall + otmPut}</td>
          </tr>
        </tbody>
      </table>
    </AnalyticalSeriesPanel>
  );
}
```

- [ ] **Step 4: Run the test — confirm it passes**

```bash
cd web && npx vitest run tests/unit/StrikeProfilePanel.test.tsx
```
Expected: 3 passed.

- [ ] **Step 5: Wire state + controls into `FlowTab.tsx`**

At the top of `FlowTab`, add hooks (the component already has `"use client"`):

```tsx
import { useMemo, useState } from "react";
import { StrikeProfilePanel } from "@/components/stock/panels/StrikeProfilePanel";

// ...

export function FlowTab({ report }: Props) {
  const spot = toNum(report.market_structure?.spot) ?? 0;
  const chain = report.option_chain_per_strike ?? [];

  // Unique expiries, sorted; default = nearest 4
  const expiries = useMemo(
    () => Array.from(new Set(chain.map((r) => r.expiry))).sort(),
    [chain],
  );
  const today = new Date().toISOString().slice(0, 10);
  const futureExpiries = expiries.filter((e) => e >= today);
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>(() => futureExpiries.slice(0, 4));
  const [strikeRangePct, setStrikeRangePct] = useState<number>(0.30);   // default ±30%
```

Then add the controls + two profile panels into the JSX after the timelines block and before the Top Alerts section:

```tsx
{chain.length > 0 ? (
  <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
    <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 1.5, color: "var(--text-muted)" }}>
        EXPIRIES:
      </span>
      {futureExpiries.map((e) => {
        const active = selectedExpiries.includes(e);
        return (
          <button
            key={e}
            onClick={() =>
              setSelectedExpiries((prev) =>
                prev.includes(e) ? prev.filter((x) => x !== e) : [...prev, e],
              )
            }
            style={{
              fontFamily: "var(--font-mono)", fontSize: 11,
              padding: "2px 8px",
              border: active ? "1px solid var(--accent-bg)" : "1px solid var(--border-dim)",
              background: active ? "var(--accent-bg)" : "transparent",
              color: active ? "var(--bg-panel)" : "var(--text-primary)",
              cursor: "pointer",
            }}
          >
            {e}
          </button>
        );
      })}
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: 1.5, color: "var(--text-muted)", marginLeft: 16 }}>
        STRIKE RANGE:
      </span>
      <select
        value={strikeRangePct}
        onChange={(e) => setStrikeRangePct(Number(e.target.value))}
        style={{
          fontFamily: "var(--font-mono)", fontSize: 11,
          background: "var(--bg-panel)", color: "var(--text-primary)",
          border: "1px solid var(--border-dim)", padding: "2px 8px",
        }}
      >
        <option value={0.15}>±15%</option>
        <option value={0.30}>±30%</option>
        <option value={0.60}>±60%</option>
        <option value={9.99}>All</option>
      </select>
    </div>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <StrikeProfilePanel
        title="VOLUME BY STRIKE"
        metric="volume"
        rows={chain}
        selectedExpiries={selectedExpiries}
        strikeRangePct={strikeRangePct}
        spot={spot}
      />
      <StrikeProfilePanel
        title="OI BY STRIKE"
        metric="oi"
        rows={chain}
        selectedExpiries={selectedExpiries}
        strikeRangePct={strikeRangePct}
        spot={spot}
      />
    </div>
  </section>
) : (
  <div style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>NO CHAIN DATA</div>
)}
```

- [ ] **Step 6: Write the Playwright e2e**

In `web/tests/e2e/flow-tab.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.describe("Flow tab", () => {
  test("loads, expands a tooltip, changes strike range, toggles an expiry", async ({ page }) => {
    await page.goto("/stock/GOOGL/flow");

    // Snapshot grid renders
    await expect(page.getByText("ALERTS")).toBeVisible();
    await expect(page.getByText("DARK POOL PRINTS")).toBeVisible();

    // Open the Alerts tooltip
    await page.getByLabel("ALERTS explanation").click();
    await expect(page.getByText(/UW flow alerts/)).toBeVisible();

    // Change strike range
    await page.getByRole("combobox").selectOption("0.15");

    // Toggle an expiry chip off and back on (the first one)
    const firstExpiry = page.locator('section button[style*="cursor: pointer"]').first();
    const expiryLabel = await firstExpiry.textContent();
    await firstExpiry.click();      // off
    await firstExpiry.click();      // on
    expect(expiryLabel).toBeTruthy();

    // Tables still render
    await expect(page.getByText("Top Alerts")).toBeVisible();
    await expect(page.getByText("OI Change — Top Movers")).toBeVisible();
  });

  test("Tables tab is removed from the TabBar", async ({ page }) => {
    await page.goto("/stock/GOOGL/flow");
    await expect(page.getByRole("link", { name: "Tables" })).toHaveCount(0);
  });
});
```

- [ ] **Step 7: Typecheck + unit + e2e**

```bash
cd web && npm run typecheck && npm run test -- --run
# Bring up the stack for e2e
bash ../scripts/dev.sh &
sleep 8
cd web && npm run test:e2e -- tests/e2e/flow-tab.spec.ts
```
Expected: typecheck clean, all unit + e2e green.

Kill the dev stack:
```bash
pkill -f "uw_scan|next dev"
```

- [ ] **Step 8: Lint**

```bash
cd web && npm run lint
```
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add web/components/stock/panels/StrikeProfilePanel.tsx \
        web/components/stock/tabs/FlowTab.tsx \
        web/tests/unit/StrikeProfilePanel.test.tsx \
        web/tests/e2e/flow-tab.spec.ts
git commit -m "web: Volume + OI strike-profile panels with shared expiry + range controls"
```

---

## Task 9 — Open the PR

- [ ] **Step 1: Push branch**

```bash
git push -u origin feat/flow-tab-merge
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "Flow tab: merge Flow + Tables with timelines, profiles, upgraded tables" --body "$(cat <<'EOF'
## Summary
- Merges per-stock Flow + Tables tabs into one Flow tab with a self-explaining snapshot grid (info tooltips with definitions + benchmarks).
- Adds 180-day daily Volume + OI timelines with put/call ratio overlays; Volume gets earnings markers.
- Adds Volume + OI by-strike profile panels with shared multi-expiry picker + strike-range trim and an ITM/OTM bucket table per profile.
- Upgrades OI Movers with decoded OCC symbol (Type/Expiry/Strike), DTE, %Spot, Vol/|ΔOI|, Notional, ASK%, FLAG chips driven by Pan & Poteshman / SpotGamma framing.
- Backend: new `options_volume_daily` + `option_chain_per_strike` tables, extended `oi_change_events`, new nightly worker job.

Spec: `docs/superpowers/specs/2026-05-13-flow-tab-merge-design.md`

## Test plan
- [ ] `uv run pytest` — all green (unit + integration)
- [ ] `uv run pytest -m live` (with `UW_SCAN_API_KEY`) — confirms UW payload contracts still hold
- [ ] `cd web && npm run typecheck && npm run lint && npm run test`
- [ ] `cd web && npm run test:e2e -- tests/e2e/flow-tab.spec.ts`
- [ ] Manual: visit `/stock/GOOGL/flow`, expand a snapshot tooltip, toggle an expiry chip, change ±range, confirm both profiles update in sync; confirm Tables tab is gone from the TabBar.
EOF
)"
```

- [ ] **Step 3: Wait for CI**

```bash
gh pr checks
```
Expected: all green. If anything fails, fix and push a new commit (do not amend).

- [ ] **Step 4: Hand off for review**

After CI green, request a reviewer. Do NOT merge yourself — per global policy, the PR goes through review then merge to `main`.

---

## Self-review against spec

### Spec coverage

| Spec section | Plan task |
|---|---|
| §Architecture (frontend file tree) | Task 6 (FlowTab rewrite + new panels + lib files), Task 7 (timeline panel), Task 8 (profile panel) |
| §Architecture (backend file tree) | Tasks 1–5 (migration → endpoint → models → normalizer → fetcher → aggregator → repo → report → worker) |
| §1 Snapshot Grid (11 tiles + tooltip copy) | Task 6 — `FlowSnapshotGrid.tsx` + `snapshotTooltips.ts` |
| §1 `<details>` a11y pattern | Task 6 Step 8 (`<details>` + `aria-label`) — locked in over the hover-only alternative |
| §2 Volume + OI timelines | Task 7 — `FlowTimelinePanel.tsx`, mounted twice in Task 7 Step 6 |
| §2 Earnings markers | Task 7 Step 1 (locate field), Step 6 (`markers={earnings}`) |
| §2 UW `options-volume` endpoint slug + fetcher | Task 2 |
| §2 `OptionsDailyRow` model | Task 2 Step 3 |
| §2 `options_volume_daily` storage | Task 1 (table) + Task 2 (upsert) |
| §3 Strike profile (shared controls + bucket table) | Task 8 Steps 3 + 5 |
| §3 `OptionChainPerStrikeRow` + aggregator | Task 2 — `cards/option_chain.py` + aggregator |
| §3 `option_chain_per_strike` storage | Task 1 (table) + Task 2 (upsert) |
| §4 OI Movers upgraded columns (decoded OCC, FLAG, ASK%, NOTIONAL) | Task 6 Step 13 |
| §4 `OiChangeRow` `prev_*` extension | Task 3 |
| §4 `web/lib/uw-alert-rules.ts` + Top Alerts glossary | Task 6 Steps 5 + 15 |
| §4 `web/lib/occ.ts` parser | Task 6 Steps 1–4 |
| §Phasing (8 commits, single PR) | Tasks 1–8 (commits) + Task 9 (PR) |
| §Testing — unit + integration + live + e2e | Tasks 2, 3, 4, 6, 7, 8 (unit/integration), Task 2 (live), Task 8 (e2e) |
| §Open Item #3 v1.1 (snapshot percentile) | Not implemented in v1 per spec — deferred. Not a gap. |
| §Open Item #5 (volume-per-strike storage cost) | Handled via filter window in Task 2 (±60% spot, ≤1y) — sized by the empirical probe at Task 2 Step 12 |

### Placeholder scan

Searched the plan for the standard red-flag phrases — no "TBD", "TODO", "implement later", "Add appropriate error handling", "Similar to Task N" without code, or unattached references. A handful of intentional "if the actual field name differs in `lib/types.ts`, substitute" notes remain — these are unavoidable without running `gen:types` at plan-write time. The first such note is in Task 6 Step 8; subsequent panels follow the same pattern.

### Type consistency

- `OptionsDailyRow` / `OptionChainPerStrikeRow` / `OiChangeRow` names match between Python (Tasks 2–4) and the regenerated `lib/types.ts` (Task 4).
- `parseOccSymbol` signature consistent across Task 6 (definition), 6 (used in `OiMoversTable`), and 8 (not used directly — strike comes from `option_chain_per_strike.strike` numeric field).
- `aggregate_chain_per_strike` parameter names (`spot`, `max_pct_from_spot`, `max_dte_days`, `today`) match between the unit test (Task 2 Step 14), the implementation (Task 2 Step 16), and the worker call (Task 5 Step 1).
- `FlowTimelinePanel` props (`title`, `primary`, `secondary`, `dates`, `markers`) consistent between definition (Task 7 Step 4) and call sites (Task 7 Step 6).
- `StrikeProfilePanel` props (`title`, `metric`, `rows`, `selectedExpiries`, `strikeRangePct`, `spot`) consistent across the unit test (Task 8 Step 1), implementation (Task 8 Step 3), and parent wire-up (Task 8 Step 5).

No drift found.
