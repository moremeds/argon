# Regime Port — GEX-First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Checkbox (`- [ ]`) syntax.

> **Status:** This is the **executable plan for the GEX-first iteration**. The companion file `2026-05-16-port-regime-from-xenon.md` is the long-term roadmap (CRI/VCG + IB-via-R2 + full 3-tab visual port) — it is NOT the spec to execute. Both plans share design decisions (Pydantic in `api/schemas.py`, Repository methods, `get_repo` DI, frontend base URL, `useSyncHook` port, d3 dependency). Where this plan needs detail that the roadmap already specifies precisely, this plan references it by section.

**Goal:** Ship `/regime` as a 3-tab page (CRI / VCG / GEX). GEX renders live UW data end-to-end (UW → scheduled scanner → Postgres → API → React). CRI and VCG render a small "coming soon — IB-via-R2 reader pending" placeholder card. Sidebar nav gains a Regime entry.

**Architecture (this iteration):**
- **Data flow (GEX only)**: UW client → `GexScanner.run(ticker)` (background worker, 5-min cadence) → `repo.upsert_gex_snapshot(...)` → `gex_snapshots` table → `GET /api/regime/gex` → React `GexSubTab` via `useGex` hook.
- **Data flow (CRI/VCG)**: nothing. Both endpoints return a sentinel `{status: "pending", reason: "ib_via_r2_not_wired"}` body. The frontend's `CriSubTab` / `VcgSubTab` placeholders never actually fetch.
- **No IB, no R2, no Yahoo** in this iteration. UW is the sole external data source. CLAUDE.md priority `UW → FMP → massive` is unchanged; IB stays out of this codebase entirely (the IB-reading project lives elsewhere and will eventually publish parquet to R2 — that's a future plan).
- **No MenthorQ** — Playwright dep is out of scope. GEX panel renders without MQ key levels in v1; the UI degrades gracefully (`mq: null`, `source_delta: null`).
- **d3 dependency** is added (deviation from CLAUDE.md "no chart library" — user-approved 2026-05-16 for 1:1 visual mirror). Required by `GexProfileChart`. See Task 9.

**Tech stack:** Python 3.13 / FastAPI / Pydantic v2 / psycopg 3 / APScheduler (backend) — Next.js 16 / React 19 / TypeScript / d3 + hand-rolled SVG (frontend) — pytest / vitest / playwright.

---

## File Structure

**Create:**
- `src/uw_scan/storage/migrations/037_gex_snapshots.sql`
- `src/uw_scan/api/routers/regime.py`
- `src/uw_scan/scanners/__init__.py` (if missing)
- `src/uw_scan/scanners/gex.py` — scanner port (~400-500 LOC ported from xenon `src/xenon/scanners/gex.py`, minus MQ/CLI/HTML)
- `src/uw_scan/worker/jobs/gex_scan.py` — APScheduler job wrapper
- `tests/integration/api/test_regime_router.py`
- `tests/integration/test_gex_scanner.py`
- `tests/unit/test_regime_schemas.py`
- `web/app/regime/page.tsx`
- `web/components/regime/RegimePanel.tsx`
- `web/components/regime/GexSubTab.tsx` — port of `xenon/web/components/GexPanel.tsx`
- `web/components/regime/PendingSubTab.tsx` — generic placeholder for CRI/VCG tabs
- `web/components/regime/GexProfileChart.tsx` — port (d3-using)
- `web/components/regime/ui/MetricCard.tsx` — port
- `web/components/regime/charts/ChartPanel.tsx` — port
- `web/components/regime/charts/ChartLegend.tsx` — port
- `web/components/regime/InfoTooltip.tsx` — port (skip if already present elsewhere)
- `web/lib/regime/api.ts` — typed API URL builder
- `web/lib/regime/useSyncHook.ts` — port (236 LOC)
- `web/lib/regime/useGex.ts` — port
- `web/lib/regime/useMarketHours.ts` — port (81 LOC)
- `web/lib/regime/pricesProtocol.ts` — port (207 LOC)
- `web/lib/regime/chartSystem.ts` — subset port (`chartSeriesColor` + lookup)
- `web/lib/regime/sectionTooltips.ts` — subset port (GEX keys only)
- `web/lib/regime/types.ts` — re-exports of generated openapi types
- `web/tests/unit/regime-page.test.tsx`
- `web/tests/e2e/regime-page.spec.ts`

**Modify (extend existing files):**
- `src/uw_scan/api/schemas.py` — append GEX response models + validators
- `src/uw_scan/storage/repository.py` — append `fetch_latest_gex` + `upsert_gex_snapshot` methods
- `src/uw_scan/api/server.py` — register `regime` router after the existing `trade_insights.router` line
- `src/uw_scan/worker/scheduler.py` — add GEX scan job to the APScheduler schedule
- `web/components/shared/Sidebar.tsx` — add `{ href: "/regime", label: "Regime", icon: Activity }` to `NAV`
- `web/app/globals.css` — append GEX-related styles (selector-list extraction from xenon, `@media`-aware)
- `web/package.json` — add `d3` + `@types/d3`

---

## Task 1: DB migration — `gex_snapshots` only

**File:** `src/uw_scan/storage/migrations/037_gex_snapshots.sql`

- [ ] **Step 1: Write SQL**

```sql
-- 037_gex_snapshots.sql
--
-- GEX snapshots table — mirrors xenon's src/xenon/db/schema.py:577-641
-- JSONB payload + generated columns for indexable scalars.
-- Idempotent (IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.gex_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    data_date       DATE,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload         JSONB NOT NULL,
    spot            NUMERIC(12,4) GENERATED ALWAYS AS ((payload->>'spot')::numeric) STORED,
    net_gex         NUMERIC(14,2) GENERATED ALWAYS AS ((payload->>'net_gex')::numeric) STORED,
    net_dex         NUMERIC(14,2) GENERATED ALWAYS AS ((payload->>'net_dex')::numeric) STORED,
    vol_pc          NUMERIC(8,4)  GENERATED ALWAYS AS ((payload->>'vol_pc')::numeric) STORED,
    iv_30d          NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'iv30d')::numeric) STORED,
    iv_rank         NUMERIC(6,2)  GENERATED ALWAYS AS (((payload->'iv')->>'iv_rank')::numeric) STORED,
    hv_30d          NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'hv30')::numeric) STORED,
    mq_iv_30d       NUMERIC(6,4)  GENERATED ALWAYS AS (((payload->'iv')->>'mq_iv30d')::numeric) STORED,
    level_max_magnet_strike       NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'max_magnet')->>'strike')::numeric) STORED,
    level_max_magnet_gamma        NUMERIC(14,4) GENERATED ALWAYS AS (((payload->'levels'->'max_magnet')->>'gamma')::numeric) STORED,
    level_second_magnet_strike    NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'second_magnet')->>'strike')::numeric) STORED,
    level_max_accelerator_strike  NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'max_accelerator')->>'strike')::numeric) STORED,
    level_put_wall_strike         NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'put_wall')->>'strike')::numeric) STORED,
    level_call_wall_strike        NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'call_wall')->>'strike')::numeric) STORED,
    level_gex_flip_strike         NUMERIC(12,4) GENERATED ALWAYS AS (((payload->'levels'->'gex_flip')->>'strike')::numeric) STORED
);

CREATE INDEX IF NOT EXISTS ix_gex_ticker_time ON uw_scan.gex_snapshots (ticker, scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_gex_scanned_at  ON uw_scan.gex_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_gex_data_date   ON uw_scan.gex_snapshots (data_date);

COMMIT;
```

- [ ] **Step 2: Apply migration**

```bash
bash scripts/migrate.sh
```
Expected: `Applying src/uw_scan/storage/migrations/037_gex_snapshots.sql...` followed by `COMMIT`. Re-running is a no-op.

- [ ] **Step 3: Verify**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "\d uw_scan.gex_snapshots"
```
Expected: table listed with `payload jsonb` + generated columns.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/migrations/037_gex_snapshots.sql
git commit -m "feat(regime): add gex_snapshots table"
```

---

## Task 2: GEX Pydantic schemas

**Critical conventions** (verified):
- API contract schemas live in `src/uw_scan/api/schemas.py` (existing file, docstring confirms: "Pydantic response models — over-the-wire contract for the watchlist API"). **Do NOT create `src/uw_scan/api/models/regime.py`** — that dir does not exist.
- Pydantic v2 with `field_validator(mode="before")` for the numeric-string coercion semantics xenon's `normalizeCriPayload` has on the client side.

**Files:**
- Modify: `src/uw_scan/api/schemas.py` (append GEX schemas)
- Create: `tests/unit/test_regime_schemas.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_regime_schemas.py`:

```python
from uw_scan.api.schemas import GexResponse, EMPTY_GEX_RESPONSE, RegimePendingResponse


def test_empty_gex_response_uses_profile_not_buckets():
    payload = EMPTY_GEX_RESPONSE.model_dump()
    assert "profile" in payload
    assert payload["profile"] == []
    assert payload["levels"]["max_magnet"] is None
    assert payload["bias"]["direction"] is None
    assert payload["mq"] is None


def test_gex_response_round_trip_with_full_xenon_shape():
    src = {
        "scan_time": "2026-05-16T13:15:00Z",
        "market_open": True,
        "ticker": "SPX",
        "spot": 5800.12,
        "net_gex": -2400000000.0,
        "levels": {
            "gex_flip": {"strike": 5750, "gamma": 0, "distance": -50.12, "distance_pct": -0.86},
            "max_magnet": {"strike": 5780, "gamma": 1.5e9, "distance": -20.12, "distance_pct": -0.34},
        },
        "profile": [{"strike": 5750, "call_gex": 1e8, "put_gex": -2e8, "net_gex": -1e8, "pct_from_spot": -0.86, "tag": None}],
        "bias": {"direction": "BEAR", "reasons": ["net_gex<0", "spot<flip"], "days_above_flip": 0, "flip_migration": []},
    }
    parsed = GexResponse.model_validate(src)
    assert parsed.spot == 5800.12
    assert parsed.bias.direction == "BEAR"
    assert parsed.profile[0].strike == 5750


def test_regime_pending_response_shape():
    payload = RegimePendingResponse(scanner="cri").model_dump()
    assert payload["status"] == "pending"
    assert payload["scanner"] == "cri"
    assert payload["reason"] == "ib_via_r2_not_wired"
```

- [ ] **Step 2: Run test (expect FAIL — `ImportError`)**

```bash
uv run pytest tests/unit/test_regime_schemas.py -v
```

- [ ] **Step 3: Implement — append to `src/uw_scan/api/schemas.py`**

The full schema is identical to what the roadmap plan specifies for GEX. Copy from `docs/superpowers/plans/2026-05-16-port-regime-from-xenon.md` (Task 2 Step 3, the section starting `# ── GEX ─────────────`) and append to `src/uw_scan/api/schemas.py`.

Field set (canonical, mirrors `xenon/web/lib/useGex.ts:86-121`):

- Top-level: `scan_time, market_open, ticker, spot, close, day_change, day_change_pct, data_date, net_gex, net_dex, atm_iv, vol_pc, levels, profile, expected_range, bias, history, iv, mq, source_delta`
- `GexLevel`: `{strike, gamma, distance, distance_pct}` — nullable at each level slot
- `GexLevels`: `{gex_flip, max_magnet, second_magnet, max_accelerator, put_wall, call_wall}` — each `GexLevel | None`
- `GexBucket`: `{strike, call_gex, put_gex, net_gex, pct_from_spot, tag}`
- `GexBias`: `{direction, reasons, days_above_flip, flip_migration}`
- `GexExpectedRange`: `{low, high, iv_1d}`
- `GexHistoryEntry`: `{date, net_gex, net_dex, gex_flip, spot, atm_iv, vol_pc, bias}`
- `GexIvData`: `{iv30d, iv_rank, hv30, mq_iv30d, mq_iv_rank, source}`
- `GexMqLevels`: `{source_date, spot, hvl, call_resistance_all, ..., top_gex_strikes}` (skipped in v1 — present as type only, populated null)
- `GexSourceDelta`: 5 nullable `SourceDeltaEntry` slots (skipped in v1)

Also append the pending-response sentinel:

```python
from typing import Literal as _Lit_Pending
from pydantic import BaseModel as _BM_Pending

class RegimePendingResponse(_BM_Pending):
    """Sentinel for CRI/VCG endpoints until IB-via-R2 reader lands."""
    status: _Lit_Pending["pending"] = "pending"
    scanner: _Lit_Pending["cri", "vcg"]
    reason: _Lit_Pending["ib_via_r2_not_wired"] = "ib_via_r2_not_wired"
    message: str = "Data source pending. CRI/VCG require VIX/VVIX/COR1M from the IB-via-R2 reader (separate project)."
```

(`_Lit_Pending` and `_BM_Pending` aliases avoid clashing with whatever `Literal` / `BaseModel` imports exist already in `schemas.py` — the executor can collapse them to plain `Literal` / `BaseModel` if the existing file already imports them at the top.)

- [ ] **Step 4: Run test (expect PASS)**

```bash
uv run pytest tests/unit/test_regime_schemas.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/schemas.py tests/unit/test_regime_schemas.py
git commit -m "feat(regime): GEX Pydantic schemas + RegimePendingResponse sentinel"
```

---

## Task 3: Repository methods — `fetch_latest_gex` + `upsert_gex_snapshot`

**File:** `src/uw_scan/storage/repository.py` (append methods to existing `Repository` class)

- [ ] **Step 1: Write failing test**

`tests/integration/test_gex_repository.py`:

```python
import json

from uw_scan.storage.repository import Repository


def test_upsert_and_fetch_latest_gex(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    payload = {
        "ticker": "SPX", "spot": 5800.12, "net_gex": -2_400_000_000,
        "levels": {"max_magnet": {"strike": 5780, "gamma": 1.5e9}},
        "profile": [],
    }
    repo.upsert_gex_snapshot(ticker="SPX", payload=payload)
    result = repo.fetch_latest_gex(ticker="SPX")
    assert result is not None
    assert result["spot"] == 5800.12
    assert result["levels"]["max_magnet"]["strike"] == 5780


def test_fetch_latest_gex_filters_by_ticker(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_gex_snapshot(ticker="SPX", payload={"spot": 5800})
    repo.upsert_gex_snapshot(ticker="SPY", payload={"spot": 580})
    assert repo.fetch_latest_gex(ticker="SPX")["spot"] == 5800
    assert repo.fetch_latest_gex(ticker="SPY")["spot"] == 580


def test_fetch_latest_gex_returns_none_for_unknown_ticker(seeded_db_empty_cards: Repository) -> None:
    assert seeded_db_empty_cards.fetch_latest_gex(ticker="UNKNOWN") is None
```

- [ ] **Step 2: Run test (expect FAIL — `AttributeError`)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/test_gex_repository.py -v
```

- [ ] **Step 3: Implement — append methods to `Repository` class**

Find `class Repository:` at `src/uw_scan/storage/repository.py:579`. Append inside the class body:

```python
    # ─── Regime / GEX (ported from xenon 2026-05-16) ──────────

    def fetch_latest_gex(self, *, ticker: str = "SPX") -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT payload, scanned_at, ticker FROM {self._schema}.gex_snapshots "
                f"WHERE ticker = %s ORDER BY scanned_at DESC LIMIT 1",
                (ticker,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at, t = row[0] or {}, row[1], row[2]
        out = dict(payload)
        out.setdefault("scan_time", scanned_at.isoformat() if scanned_at else "")
        out.setdefault("ticker", t)
        return out

    def upsert_gex_snapshot(self, *, ticker: str, payload: dict, data_date=None) -> int:
        """Insert a new gex_snapshots row. Returns the inserted row id."""
        import json
        with self.conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {self._schema}.gex_snapshots (ticker, data_date, payload) "
                f"VALUES (%s, %s, %s::jsonb) RETURNING id",
                (ticker.upper(), data_date, json.dumps(payload)),
            )
            row_id = cur.fetchone()[0]
        self.conn.commit()
        return row_id
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/test_gex_repository.py -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/integration/test_gex_repository.py
git commit -m "feat(regime): add fetch_latest_gex + upsert_gex_snapshot Repository methods"
```

---

## Task 4: GEX scanner port

**The big one.** Port `xenon/src/xenon/scanners/gex.py` math + UW calls. Skip MenthorQ, CLI, HTML output.

### Verified gaps in this repo's UW client (must be filled BEFORE porting the scanner)

Three concrete issues were verified against the codebase + sample payloads on 2026-05-16:

1. **Wrong endpoint mapped**: this repo's `EndpointSlug.GREEK_EXPOSURE` → `/api/stock/{ticker}/greek-exposure/strike-expiry` (per-strike-per-expiry, requires an `expiry` param). xenon's GEX scanner needs `/strike` (aggregated across expiries, no `expiry` param). Different endpoint, different shape.
2. **Aggregate `/greek-exposure` endpoint not wired** at all (used by xenon's `fetch_aggregate_gex` for net_dex calculation).
3. **No `STOCK_INFO` endpoint** in this repo's UW client — xenon's `fetch_spot_price` uses `/api/stock/{ticker}/info` as the primary spot source. We resolve this by dropping that source entirely and using only the `iv_rank.close` fallback (still functional; verified against `docs/uw-samples/iv_rank.json`).

### Verified field shapes (all match xenon's expectations — float casts handle string values)

| Source | Field | Type | Sample value | Verified |
|---|---|---|---|---|
| `iv_rank` rows | `date`, `close`, `volatility`, `iv_rank_1y` | string | `"2026-05-05"`, `"389.37"`, `"0.4096"`, `"5.1532"` | `docs/uw-samples/iv_rank.json` |
| `screener` rows | `ticker`, `put_call_ratio` | string + numeric | `"TSLA"`, present in key list | `docs/uw-samples/bulk_screener_stocks_sp500.json` |
| `greek-exposure/strike` rows | `strike`, `call_gex`, `put_gex`, `call_delta`, `put_delta` | string numerics | not yet sampled in this repo — verify in Step 1c smoke test against live UW | UW API spec doc `docs/uw-samples/unusual_whales_api.md:146` confirms endpoint exists |

xenon already casts via `float(...)` so string→float coercion is handled at port time, no plan change needed.

### Functions to port (from `xenon/src/xenon/scanners/gex.py`)

| Xenon function | Lines | Keep? | Adaptation notes |
|---|---|---|---|
| `_bucket_size_for` | 41-46 | ✅ verbatim | Pure logic |
| `fetch_strike_gex` | 63-91 | ✅ adapt | Replace `client.get_greek_exposure_by_strike(ticker)` with `uw_source.fetch_greek_exposure_by_strike(client, repo, run_id, ticker)` — new fetcher added in Step 1a below |
| `fetch_aggregate_gex` | 91-112 | ✅ adapt | Replace `client.get_greek_exposure(ticker)` with `uw_source.fetch_greek_exposure_history(client, repo, run_id, ticker)` — new fetcher added in Step 1a |
| `fetch_atm_iv` | 112-131 | ✅ adapt | Replace `client.get_iv_rank(ticker)` with `uw_source.fetch_iv_rank_raw(client, repo, run_id, ticker)` (or restructure to consume already-fetched iv_rank rows — see Step 2 for the consolidated single-call pattern) |
| `fetch_iv_rank` | 132-145 | ✅ adapt | Same source as `fetch_atm_iv` — both read from iv_rank rows; consolidate into one fetch |
| `fetch_vol_pc` | 146-164 | ✅ adapt | Replace `client.get_stock_screener(ticker=ticker)` with `uw_source.fetch_bulk_screener_ticker(client, repo, run_id, ticker)` |
| `fetch_mq_levels` | 189-265 | ❌ skip | Playwright dep — `mq: None`, `source_delta: None` always |
| `compute_source_delta` | 288-322 | ❌ skip | only meaningful w/ MQ |
| `fetch_spot_price` | 323-377 | ✅ adapt | **Drop UW stock-info source (not in this repo) and Yahoo source (banned).** Use only iv_rank `close` field. If iv_rank is empty, raise (scanner aborts via orchestration). |
| `bucket_profile` | 378-414 | ✅ verbatim | Pure logic |
| `compute_gex_flip` | 415-431 | ✅ verbatim | Pure logic |
| `find_key_levels` | 432-476 | ✅ verbatim | Pure logic |
| `tag_profile` | 477-510 | ✅ verbatim | Pure logic |
| `compute_expected_range` | 511-523 | ✅ verbatim | Pure logic |
| `compute_directional_bias` | 524-582 | ✅ verbatim | Pure logic |
| `compute_days_above_flip` | 583-611 | ✅ adapt | xenon reads file cache; here either skip for v1 (leave `bias.days_above_flip` as `None`) or add `repo.fetch_gex_history(ticker, days=20)` method (small extension). v1 default: **skip** — leave `None`. |
| `build_history_from_cache` | 612-623 | ❌ skip | replaced by future Postgres-based history reader |
| `merge_history` | 624-640 | ❌ skip | same |
| `is_market_open` | 641-667 | ❌ skip | router has `_is_market_open_now` (already specified in Task 5) |
| `build_gex_output` | 668-811 | ❌ skip (inline) | the `run()` orchestrator in Step 2 below replicates this function's behavior, simplified — see Step 2 |
| `main` | 812+ | ❌ skip | CLI entry |

### Step 1a: Add two new UW endpoint slugs

Open `src/uw_scan/api/endpoints.py`. After the existing `EndpointSlug.GREEK_EXPOSURE = "greek_exposure"` line, add:

```python
    GREEK_EXPOSURE_BY_STRIKE = "greek_exposure_by_strike"
    GREEK_EXPOSURE_HISTORY = "greek_exposure_history"
```

Then in the endpoint mapping table (search for `EndpointSlug.GREEK_EXPOSURE: Endpoint(...)`), add two new entries:

```python
    EndpointSlug.GREEK_EXPOSURE_BY_STRIKE: Endpoint(
        EndpointSlug.GREEK_EXPOSURE_BY_STRIKE,
        "/api/stock/{ticker}/greek-exposure/strike",
        (),  # no required params
    ),
    EndpointSlug.GREEK_EXPOSURE_HISTORY: Endpoint(
        EndpointSlug.GREEK_EXPOSURE_HISTORY,
        "/api/stock/{ticker}/greek-exposure",
        (),
    ),
```

### Step 1b: Add two new fetch functions to `src/uw_scan/sources/uw.py`

Append after the existing `fetch_greek_exposure` (around line 171-186 of `uw.py`):

```python
def fetch_greek_exposure_by_strike(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> dict:
    """Fetch /api/stock/{ticker}/greek-exposure/strike — aggregated per-strike GEX.

    Returns the raw body; scanner consumes ``body["data"]`` as a list of rows
    with string-valued ``strike``, ``call_gex``, ``put_gex``, ``call_delta``,
    ``put_delta`` fields (caster handles ``float()``).
    """
    return _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE_BY_STRIKE,
        ticker,
    )


def fetch_greek_exposure_history(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> dict:
    """Fetch /api/stock/{ticker}/greek-exposure — aggregate GEX over time.

    Used for net_dex computation and (eventually) historical bias trend.
    """
    return _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE_HISTORY,
        ticker,
    )
```

(Both return the raw body dict. The scanner reads `body["data"]` to get the row list. No normalizer needed in v1 — scanner does its own parsing. Add normalizers later if any other code consumes these payloads.)

### Step 1c: Smoke-test the new endpoints against live UW (requires `UW_SCAN_API_KEY`)

```bash
uv run python -c "
from uw_scan.config import Settings
from uw_scan.api.client import UwClient
import psycopg
from uw_scan.storage.repository import Repository
from uw_scan.sources import uw

s = Settings.from_env()
client = UwClient.from_settings(s)
conn = psycopg.connect(s.db_dsn())
repo = Repository(conn, schema=s.db_schema)
run_id = repo.insert_scan_run('SPX', notes='gex_endpoint_smoke')

# Per-strike
body = uw.fetch_greek_exposure_by_strike(client, repo, run_id, 'SPX')
rows = body.get('data', [])
print(f'/strike rows: {len(rows)}')
if rows:
    sample = rows[0]
    print(f'  sample keys: {sorted(sample.keys())}')
    for key in ('strike', 'call_gex', 'put_gex', 'call_delta', 'put_delta'):
        print(f'  {key} = {sample.get(key)!r}  (type {type(sample.get(key)).__name__})')

# Aggregate
body2 = uw.fetch_greek_exposure_history(client, repo, run_id, 'SPX')
rows2 = body2.get('data', [])
print(f'/greek-exposure rows: {len(rows2)}')
if rows2:
    print(f'  sample keys: {sorted(rows2[0].keys())}')

repo.finish_scan_run(run_id, status='ok')
conn.close()
"
```

Expected output (worst-case ranges):
- `/strike rows: N` where N is the strike count (typically 50-200 for SPX)
- Sample keys include at minimum: `strike`, `call_gex`, `put_gex`, `call_delta`, `put_delta` (values as strings)
- `/greek-exposure rows: M` where M is the time-series length (typically 60-90 days)

**Stop and patch the plan** if either fails or the field names differ from xenon's expectation. The scanner code in Step 2 hard-codes these field names. Diverging here costs less than diverging at execution time.

If the live call returns 403 (subscription gate), skip this smoke and rely on the Task 4 Step 6 integration test (uses monkeypatched fetchers) — defer the live verification to Task 6 Step 4 instead.

### Step 1d: Commit endpoint additions

```bash
git add src/uw_scan/api/endpoints.py src/uw_scan/sources/uw.py
git commit -m "feat(uw): add /greek-exposure/strike + /greek-exposure endpoints for GEX scanner"
```

- [ ] **Step 2: Write the scanner module shell**

The scanner now follows this repo's run_id audit pattern: `repo.insert_scan_run("SPX", notes="gex_scan")` to create an audit row, pass `run_id` to every UW fetcher, then `repo.finish_scan_run(run_id, status="ok")` (or `"error"`) at the end. Matches the existing convention used by `cockpit_daily_snapshot.py:65` and `flow_data_refresh.py:64`.

`src/uw_scan/scanners/gex.py`:

```python
"""GEX scanner — UW-driven. Ported from xenon/src/xenon/scanners/gex.py 2026-05-16.

Differences from xenon:
- No MenthorQ (Playwright dep skipped); ``mq`` and ``source_delta`` always None.
- No file cache; history is read/written via ``Repository.fetch_latest_gex`` /
  ``upsert_gex_snapshot`` against the ``gex_snapshots`` Postgres table.
- No CLI; no HTML rendering.
- This repo's UW pattern requires a ``run_id`` from ``repo.insert_scan_run(...)``
  for the per-call audit trail. xenon's stateless client doesn't have this.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from uw_scan.api.client import UwClient
from uw_scan.sources import uw as uw_source
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

INDEX_TICKERS = {"SPX", "NDX"}
BUCKET_SIZE_INDEX = 25
BUCKET_SIZE_ETF = 5
PROFILE_RANGE_PCT = 0.10
HISTORY_DAYS = 20
TRADING_DAYS_PER_YEAR = 252


def _bucket_size_for(ticker: str, spot: float) -> int:
    if ticker in INDEX_TICKERS:
        return BUCKET_SIZE_INDEX
    if ticker in ("SPY", "QQQ"):
        return BUCKET_SIZE_ETF
    return max(1, round(spot * 0.005))


# ─── Pure-logic compute functions ──────────────────────────────────
# Copy verbatim from xenon `gex.py` lines 378-582 (bucket_profile through
# compute_directional_bias). They're side-effect-free and need no adaptation.
#
# [paste these from xenon: bucket_profile, compute_gex_flip, find_key_levels,
#  tag_profile, compute_expected_range, compute_directional_bias]


# ─── UW-driven fetchers (adapted for this repo's client + run_id pattern) ──

def fetch_strike_gex(client: UwClient, repo: Repository, run_id: int, ticker: str) -> list[dict[str, Any]]:
    """Per-strike GEX rows. Aggregates the UW response into the canonical shape."""
    body = uw_source.fetch_greek_exposure_by_strike(client, repo, run_id, ticker)
    rows = body.get("data", [])
    parsed = []
    for r in rows:
        try:
            strike = float(r["strike"])
            call_gex = float(r.get("call_gex", 0))
            put_gex = float(r.get("put_gex", 0))
            call_delta = float(r.get("call_delta", 0))
            put_delta = float(r.get("put_delta", 0))
            parsed.append({
                "strike": strike,
                "call_gex": call_gex,
                "put_gex": put_gex,
                "net_gex": call_gex + put_gex,
                "call_delta": call_delta,
                "put_delta": put_delta,
                "net_delta": call_delta + put_delta,
            })
        except (KeyError, ValueError, TypeError):
            continue
    return parsed


def fetch_aggregate_gex(client: UwClient, repo: Repository, run_id: int, ticker: str) -> list[dict[str, Any]]:
    """Aggregate GEX time series (used for net_dex calculation, eventual history)."""
    body = uw_source.fetch_greek_exposure_history(client, repo, run_id, ticker)
    rows = body.get("data", [])
    parsed = []
    for r in rows:
        try:
            parsed.append({
                "date": r["date"],
                "call_gex": float(r.get("call_gex", 0)),
                "put_gex": float(r.get("put_gex", 0)),
                "call_delta": float(r.get("call_delta", 0)),
                "put_delta": float(r.get("put_delta", 0)),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return parsed


def fetch_iv_rank_rows(client: UwClient, repo: Repository, run_id: int, ticker: str) -> list[dict[str, Any]]:
    """Raw iv_rank rows — atm_iv, iv_rank, and spot all consume the same data."""
    # This repo's normalize.normalize_iv_rank returns typed Decimal rows.
    # The scanner needs the raw response so we can pick latest by date.
    # Call _fetch_json directly to bypass the normalizer:
    from uw_scan.api.endpoints import EndpointSlug
    from uw_scan.sources.uw import _fetch_json
    body = _fetch_json(client, repo, run_id, EndpointSlug.IV_RANK, ticker)
    return body.get("data", [])


def _latest_iv_rank_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=lambda r: r.get("date", ""))


def fetch_atm_iv(iv_rank_rows: list[dict[str, Any]]) -> float | None:
    """30D ATM IV from latest iv_rank row's ``volatility`` field."""
    row = _latest_iv_rank_row(iv_rank_rows)
    if row is None:
        return None
    v = row.get("volatility")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def fetch_iv_rank(iv_rank_rows: list[dict[str, Any]]) -> float | None:
    """1Y IV rank percentile from latest row's ``iv_rank_1y`` field."""
    row = _latest_iv_rank_row(iv_rank_rows)
    if row is None:
        return None
    r = row.get("iv_rank_1y")
    try:
        return float(r) if r is not None else None
    except (TypeError, ValueError):
        return None


def fetch_spot_price(iv_rank_rows: list[dict[str, Any]]) -> float | None:
    """Spot from latest iv_rank row's ``close`` field.

    xenon's primary source (UW /stock/{ticker}/info) is not wired in this repo.
    Yahoo fallback is banned per CLAUDE.md. iv_rank.close is the surviving path.
    """
    row = _latest_iv_rank_row(iv_rank_rows)
    if row is None:
        return None
    p = row.get("close")
    try:
        return float(p) if p is not None else None
    except (TypeError, ValueError):
        return None


def fetch_vol_pc(client: UwClient, repo: Repository, run_id: int, ticker: str) -> float | None:
    """Volume put/call ratio from the screener row for this ticker."""
    try:
        # fetch_bulk_screener_ticker returns typed rows; we want the raw put_call_ratio.
        # Use the lower-level _fetch_json to get the raw dict so we don't dep on
        # whatever normalizer shape the typed return uses.
        from uw_scan.api.endpoints import EndpointSlug
        from uw_scan.sources.uw import _fetch_json
        body = _fetch_json(
            client, repo, run_id, EndpointSlug.BULK_SCREENER_STOCKS, None,
            params={"ticker": ticker.upper()},
        )
        rows = body.get("data", [])
        for r in rows:
            t = r.get("ticker", r.get("symbol", ""))
            if str(t).upper() == ticker.upper():
                pc = r.get("put_call_ratio")
                return float(pc) if pc is not None else None
        return None
    except Exception as exc:
        log.warning("vol_pc_fetch_failed ticker=%s err=%s", ticker, exc)
        return None


# ─── Orchestration ─────────────────────────────────────────────────

def run(client: UwClient, repo: Repository, ticker: str = "SPX") -> int:
    """Run a full GEX scan against UW and persist to gex_snapshots.

    Returns the inserted row id. Raises if spot cannot be determined.
    """
    ticker = ticker.upper()
    run_id = repo.insert_scan_run(ticker, notes=f"gex_scan_{ticker}")
    log.info("gex_scan_start ticker=%s run_id=%d", ticker, run_id)

    try:
        # iv_rank is fetched once and shared by 3 derived helpers (atm_iv, iv_rank, spot).
        iv_rows = fetch_iv_rank_rows(client, repo, run_id, ticker)
        spot = fetch_spot_price(iv_rows)
        if spot is None:
            log.warning("gex_scan_aborted_no_spot ticker=%s run_id=%d", ticker, run_id)
            repo.finish_scan_run(run_id, status="error")
            raise RuntimeError(f"could not fetch spot for {ticker}")

        strike_rows = fetch_strike_gex(client, repo, run_id, ticker)
        aggregate_rows = fetch_aggregate_gex(client, repo, run_id, ticker)
        atm_iv = fetch_atm_iv(iv_rows)
        iv_rank = fetch_iv_rank(iv_rows)
        vol_pc = fetch_vol_pc(client, repo, run_id, ticker)

        bucket_size = _bucket_size_for(ticker, spot)
        profile = bucket_profile(strike_rows, spot, bucket_size)
        levels = find_key_levels(profile, spot)
        levels = tag_profile(profile, levels, spot)
        gex_flip_strike = compute_gex_flip(profile, spot)
        expected_range = compute_expected_range(spot, atm_iv)
        bias = compute_directional_bias(profile, spot, gex_flip_strike, vol_pc, atm_iv)

        net_gex = sum(b["net_gex"] for b in profile)
        net_dex = sum(r.get("call_delta", 0) + r.get("put_delta", 0) for r in aggregate_rows)

        payload: dict[str, Any] = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "spot": spot,
            "close": spot,  # iv_rank's close IS the prior session close
            "day_change": None,         # populated by future enhancement
            "day_change_pct": None,
            "data_date": datetime.now(timezone.utc).date().isoformat(),
            "net_gex": net_gex,
            "net_dex": net_dex,
            "atm_iv": atm_iv,
            "vol_pc": vol_pc,
            "levels": levels,
            "profile": profile,
            "expected_range": expected_range,
            "bias": bias,
            "history": [],   # v1: empty; v2 reads from gex_snapshots history
            "iv": {
                "iv30d": atm_iv,
                "iv_rank": iv_rank,
                "hv30": None,
                "mq_iv30d": None,
                "mq_iv_rank": None,
                "source": "uw" if atm_iv is not None else None,
            },
            "mq": None,           # v1: MenthorQ disabled
            "source_delta": None,
        }

        row_id = repo.upsert_gex_snapshot(ticker=ticker, payload=payload)
        repo.finish_scan_run(run_id, status="ok")
        log.info("gex_scan_done ticker=%s row_id=%d net_gex=%.2e", ticker, row_id, net_gex)
        return row_id
    except Exception:
        # finish_scan_run is idempotent — safe to call even if already finished
        repo.finish_scan_run(run_id, status="error")
        raise
```

Note: `run()` signature now takes `(client, repo, ticker)` — not `(repo, ticker)` as in an earlier draft. The UW client must be constructed at the caller (router / worker) and passed in. This matches the pattern used by `volatility.py:75-90` and the existing worker jobs.

- [ ] **Step 3: Copy the pure-logic functions verbatim from xenon**

For each of `bucket_profile`, `compute_gex_flip`, `find_key_levels`, `tag_profile`, `compute_expected_range`, `compute_directional_bias`: open the corresponding xenon range and copy the function body unchanged. These have no external deps and the math IS the contract.

Source: `/Users/chenxi/projects/xenon/src/xenon/scanners/gex.py:378-582`

- [ ] **Step 4: Write integration test (uses monkeypatched UW fetchers — no live calls)**

`tests/integration/test_gex_scanner.py`:

```python
import pytest

from uw_scan.api.client import UwClient
from uw_scan.scanners import gex as gex_scanner
from uw_scan.storage.repository import Repository


@pytest.fixture
def mock_client() -> UwClient:
    """Real UwClient instance — UW calls are monkeypatched at the scanner-fetcher level."""
    from uw_scan.config import Settings
    return UwClient.from_settings(Settings.from_env())


def test_run_persists_payload_with_full_xenon_shape(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    # Stub the scanner's UW fetchers — bypasses real network entirely.
    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", lambda c, r, rid, t: [
        {"date": "2026-05-16", "close": "5800.0", "volatility": "0.18", "iv_rank_1y": "35.0"},
    ])
    monkeypatch.setattr(gex_scanner, "fetch_strike_gex", lambda c, r, rid, t: [
        {"strike": 5750, "call_gex": 1e8, "put_gex": -3e8, "net_gex": -2e8, "call_delta": 0.4, "put_delta": -0.6, "net_delta": -0.2},
        {"strike": 5800, "call_gex": 2e8, "put_gex": -2e8, "net_gex": 0, "call_delta": 0.5, "put_delta": -0.5, "net_delta": 0},
        {"strike": 5850, "call_gex": 3e8, "put_gex": -1e8, "net_gex": 2e8, "call_delta": 0.6, "put_delta": -0.4, "net_delta": 0.2},
    ])
    monkeypatch.setattr(gex_scanner, "fetch_aggregate_gex", lambda c, r, rid, t: [
        {"date": "2026-05-16", "call_gex": 1e10, "put_gex": -1e10, "call_delta": 0.5, "put_delta": -0.5},
    ])
    monkeypatch.setattr(gex_scanner, "fetch_vol_pc", lambda c, r, rid, t: 0.85)

    row_id = gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    assert row_id > 0

    payload = seeded_db_empty_cards.fetch_latest_gex(ticker="SPX")
    assert payload["spot"] == 5800.0
    assert payload["ticker"] == "SPX"
    assert payload["mq"] is None  # v1 always
    assert "profile" in payload
    assert isinstance(payload["profile"], list)
    assert payload["iv"]["source"] == "uw"
    assert payload["iv"]["iv30d"] == 0.18
    assert payload["iv"]["iv_rank"] == 35.0
    assert payload["vol_pc"] == 0.85


def test_run_raises_when_iv_rank_empty(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", lambda c, r, rid, t: [])
    with pytest.raises(RuntimeError, match="could not fetch spot"):
        gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")


def test_run_marks_scan_run_error_when_aborted(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", lambda c, r, rid, t: [])
    with pytest.raises(RuntimeError):
        gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    # Verify finish_scan_run("error") was called — query scan_runs:
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute("SELECT status FROM uw_scan.scan_runs ORDER BY run_id DESC LIMIT 1")
        status = cur.fetchone()[0]
    assert status == "error"
```

- [ ] **Step 5: Run test**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/test_gex_scanner.py -v
```
Expected: 3 PASSED.

- [ ] **Step 6: Smoke against real UW (if `UW_SCAN_API_KEY` set)**

```bash
uv run python -c "
from uw_scan.config import Settings
from uw_scan.api.client import UwClient
import psycopg
from uw_scan.storage.repository import Repository
from uw_scan.scanners import gex
s = Settings.from_env()
client = UwClient.from_settings(s)
conn = psycopg.connect(s.db_dsn())
try:
    repo = Repository(conn, schema=s.db_schema)
    row_id = gex.run(client, repo, ticker='SPX')
    payload = repo.fetch_latest_gex(ticker='SPX')
    import json; print(json.dumps({'row_id': row_id, 'spot': payload['spot'], 'net_gex': payload['net_gex']}, indent=2))
finally:
    conn.close()
"
```
Expected: real numbers, no errors. Skip this step if no live UW key.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/scanners/ tests/integration/test_gex_scanner.py
git commit -m "feat(regime): port GEX scanner from xenon (UW-driven, no MQ)"
```

---

## Task 5: FastAPI router — `/api/regime/*`

**File:** `src/uw_scan/api/routers/regime.py`

- [ ] **Step 1: Write failing test**

`tests/integration/api/test_regime_router.py`:

```python
from fastapi.testclient import TestClient

from uw_scan.storage.repository import Repository


def test_get_gex_returns_empty_shape_when_no_data(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(Repository, "fetch_latest_gex", lambda self, *, ticker="SPX": None)
    r = client.get("/api/regime/gex")
    assert r.status_code == 200
    data = r.json()
    assert data["spot"] is None
    assert data["levels"]["max_magnet"] is None
    assert data["profile"] == []
    assert data["mq"] is None


def test_get_gex_defaults_to_spx_and_uppercases_ticker(client: TestClient, monkeypatch) -> None:
    seen = {}
    def stub(self, *, ticker="SPX"):
        seen["ticker"] = ticker
        return None
    monkeypatch.setattr(Repository, "fetch_latest_gex", stub)
    client.get("/api/regime/gex")
    assert seen["ticker"] == "SPX"
    client.get("/api/regime/gex?ticker=spy")
    assert seen["ticker"] == "SPY"


def test_get_cri_returns_pending_sentinel(client: TestClient) -> None:
    r = client.get("/api/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["scanner"] == "cri"
    assert body["reason"] == "ib_via_r2_not_wired"


def test_get_vcg_returns_pending_sentinel(client: TestClient) -> None:
    r = client.get("/api/regime/vcg")
    body = r.json()
    assert body["status"] == "pending"
    assert body["scanner"] == "vcg"


def test_post_gex_scan_runs_scanner(client: TestClient, monkeypatch) -> None:
    """The router must construct a UwClient and pass (client, repo, ticker) to scanner.run."""
    calls = []
    def _stub_run(client_arg, repo_arg, ticker="SPX"):
        calls.append(("client_passed" if client_arg is not None else "no_client", ticker))
        return 42
    monkeypatch.setattr("uw_scan.scanners.gex.run", _stub_run)
    r = client.post("/api/regime/gex/scan?ticker=spy")
    assert r.status_code == 202
    body = r.json()
    assert body["scanner"] == "gex"
    assert body["ticker"] == "SPY"
    assert body["row_id"] == 42
    assert calls == [("client_passed", "SPY")]


def test_post_cri_scan_returns_pending(client: TestClient) -> None:
    r = client.post("/api/regime/scan")
    assert r.status_code == 202
    body = r.json()
    assert body["scanner"] == "cri"
    assert "ib_via_r2_not_wired" in body["reason"]
```

- [ ] **Step 2: Run test (expect FAIL — 404)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_regime_router.py -v
```

- [ ] **Step 3: Implement router**

`src/uw_scan/api/routers/regime.py`:

```python
"""/regime — GEX live (UW-driven), CRI/VCG pending IB-via-R2 reader."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from uw_scan.api.client import UwClient
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.schemas import (
    EMPTY_GEX_RESPONSE,
    GexResponse,
    RegimePendingResponse,
)
from uw_scan.config import Settings
from uw_scan.scanners import gex as gex_scanner
from uw_scan.storage.repository import Repository

router = APIRouter(prefix="/regime")


def _is_market_open_now() -> bool:
    """Mon-Fri 09:30-16:00 ET."""
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


# ─── GEX (live) ──────────────────────────────────────────────────

@router.get("/gex", response_model=GexResponse)
def get_gex(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query("SPX"),
) -> GexResponse:
    raw = repo.fetch_latest_gex(ticker=ticker.upper())
    if raw is None:
        empty = EMPTY_GEX_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        empty.ticker = ticker.upper()
        return empty
    raw["market_open"] = _is_market_open_now()
    return GexResponse.model_validate(raw)


@router.post("/gex/scan", status_code=202)
def trigger_gex_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
    ticker: str = Query("SPX"),
) -> dict:
    """Run a GEX scan synchronously and persist. Returns scan summary."""
    uw_client = UwClient.from_settings(settings)
    row_id = gex_scanner.run(uw_client, repo, ticker=ticker.upper())
    return {
        "status": "queued",
        "scanner": "gex",
        "ticker": ticker.upper(),
        "row_id": row_id,
    }


# ─── CRI (pending) ───────────────────────────────────────────────

@router.get("", response_model=RegimePendingResponse)
def get_regime() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="cri")


@router.post("/scan", status_code=202, response_model=RegimePendingResponse)
def trigger_cri_scan() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="cri")


# ─── VCG (pending) ───────────────────────────────────────────────

@router.get("/vcg", response_model=RegimePendingResponse)
def get_vcg() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="vcg")


@router.post("/vcg/scan", status_code=202, response_model=RegimePendingResponse)
def trigger_vcg_scan() -> RegimePendingResponse:
    return RegimePendingResponse(scanner="vcg")
```

- [ ] **Step 4: Register router in `server.py`**

In `src/uw_scan/api/server.py`, add `regime` to the `from uw_scan.api.routers import (...)` block at line 8-ish, then add this line after the last `app.include_router(...)` (currently `trade_insights.router` at line 42):

```python
app.include_router(regime.router, prefix="/api", tags=["regime"])
```

- [ ] **Step 5: Run tests (expect PASS)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_regime_router.py -v
```
Expected: 6 PASSED.

- [ ] **Step 6: Smoke test — KEEP API RUNNING for Task 7**

In another terminal:
```bash
uv run uvicorn uw_scan.api.server:app --port 8400 &
sleep 2
curl -s http://localhost:8400/api/regime | python -m json.tool
curl -s http://localhost:8400/api/regime/gex | python -m json.tool | head -20
```
Expected: `/api/regime` returns pending sentinel, `/api/regime/gex` returns empty GEX shape with `"profile": []`.

**Do NOT stop the API** — Task 7 (`gen:types`) needs it.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/api/routers/regime.py src/uw_scan/api/server.py tests/integration/api/test_regime_router.py
git commit -m "feat(regime): /api/regime router (GEX live, CRI/VCG pending)"
```

---

## Task 6: APScheduler GEX scan job

**File:** `src/uw_scan/worker/scheduler.py` (modify existing scheduler)

The worker should periodically (every 5 minutes, configurable) run `gex_scanner.run(uw_client, repo, ticker="SPX")` and persist. Skip during weekends.

- [ ] **Step 1: Inspect existing scheduler**

```bash
grep -nE "add_job|scheduled_full_scan|scheduled" src/uw_scan/worker/scheduler.py | head -20
```

- [ ] **Step 2: Add the new scheduled job**

Open `src/uw_scan/worker/scheduler.py`. Find where other jobs are registered (e.g., `scheduled_full_scan`, OHLC refresh). Add:

```python
def scheduled_gex_scan(settings: Settings) -> None:
    """Run GEX scan against UW for primary index tickers."""
    if datetime.now(ZoneInfo("America/New_York")).weekday() >= 5:
        log.info("gex_scan_skipped_weekend")
        return
    import psycopg
    from uw_scan.api.client import UwClient
    from uw_scan.scanners import gex as gex_scanner
    from uw_scan.storage.repository import Repository

    tickers = ["SPX", "SPY"]  # extend as needed
    uw_client = UwClient.from_settings(settings)
    conn = psycopg.connect(settings.db_dsn())
    try:
        repo = Repository(conn, schema=settings.db_schema)
        for ticker in tickers:
            try:
                gex_scanner.run(uw_client, repo, ticker=ticker)
            except Exception as exc:
                log.warning("gex_scan_failed ticker=%s err=%s", ticker, exc)
    finally:
        conn.close()
```

Register it with the scheduler — match the pattern used by other jobs:

```python
scheduler.add_job(
    scheduled_gex_scan,
    "interval",
    minutes=settings.gex_scan_interval_minutes,
    args=[settings],
    id="regime_gex_scan",
    replace_existing=True,
    next_run_time=datetime.now() + timedelta(seconds=30),  # warm scan after startup
)
```

- [ ] **Step 3: Add settings field**

In `src/uw_scan/config.py` (or wherever `Settings` is defined), add:

```python
gex_scan_interval_minutes: int = Field(default=5, validation_alias="GEX_SCAN_INTERVAL_MINUTES")
```

- [ ] **Step 4: Manual smoke**

Start the worker (in a separate terminal):
```bash
uv run python -m uw_scan.worker
```
Watch logs for `gex_scan_start ticker=SPX` within 30 seconds. After a successful scan, verify:

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "SELECT id, ticker, scanned_at, spot, net_gex FROM uw_scan.gex_snapshots ORDER BY scanned_at DESC LIMIT 3;"
```
Expected: at least one row for SPX (and SPY if UW returns data).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/scheduler.py src/uw_scan/config.py
git commit -m "feat(regime): schedule GEX scan job (5min cadence, weekday-only)"
```

---

## Task 7: Regenerate openapi types

**Prerequisite:** API server running on port 8400 from Task 5 Step 6.

- [ ] **Step 1: Confirm API reachable**

```bash
curl -sI http://localhost:8400/openapi.json | head -1
```
Expected: `HTTP/1.1 200 OK`.

- [ ] **Step 2: Run codegen**

```bash
cd web && npm run gen:types
```
Expected: `web/lib/types.ts` updated with new `GexResponse`, `GexLevel`, `GexLevels`, `GexBucket`, `GexBias`, `GexIvData`, `GexMqLevels`, `GexSourceDelta`, `RegimePendingResponse` schemas.

- [ ] **Step 3: Verify types compile**

```bash
cd web && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Stop the API**

```bash
kill %1   # or Ctrl+C in the terminal running uvicorn
```

- [ ] **Step 5: Commit**

```bash
git add web/lib/types.ts
git commit -m "chore(regime): regenerate openapi types for /api/regime endpoints"
```

---

## Task 8: Frontend libs (GEX-only subset)

**Files** — create:
- `web/lib/regime/api.ts`
- `web/lib/regime/useSyncHook.ts` (port 236 LOC)
- `web/lib/regime/useGex.ts` (port)
- `web/lib/regime/useMarketHours.ts` (port 81 LOC)
- `web/lib/regime/pricesProtocol.ts` (port 207 LOC)
- `web/lib/regime/chartSystem.ts` (subset)
- `web/lib/regime/sectionTooltips.ts` (subset — GEX keys only)
- `web/lib/regime/types.ts` (re-exports)

- [ ] **Step 1: `web/lib/regime/api.ts`**

```typescript
const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400";

export const regimeApi = {
  cri:        () => `${API}/api/regime`,
  cri_scan:   () => `${API}/api/regime/scan`,
  vcg:        () => `${API}/api/regime/vcg`,
  vcg_scan:   () => `${API}/api/regime/vcg/scan`,
  gex:        (ticker: string) => `${API}/api/regime/gex?ticker=${encodeURIComponent(ticker)}`,
  gex_scan:   (ticker: string) => `${API}/api/regime/gex/scan?ticker=${encodeURIComponent(ticker)}`,
} as const;
```

- [ ] **Step 2: Port `useSyncHook`**

Copy `/Users/chenxi/projects/xenon/web/lib/useSyncHook.ts` → `web/lib/regime/useSyncHook.ts`. No external imports beyond React. Exports `useSyncHook<T>(config)` and type `UseSyncReturn<T>` (`{data, loading, syncing, error, lastSync, syncNow}`).

- [ ] **Step 3: Port `useGex`**

Copy `/Users/chenxi/projects/xenon/web/lib/useGex.ts` → `web/lib/regime/useGex.ts`. Adjust:
- `./useSyncHook` import stays (sibling)
- `./useMarketHours` import stays (sibling, ported in Step 4)
- Endpoint string → call `regimeApi.gex(ticker)` from `./api`
- Default `ticker` parameter → `"SPX"` (was `"SPY"` in xenon — match FastAPI default)

- [ ] **Step 4: Port `useMarketHours`**

Copy `/Users/chenxi/projects/xenon/web/lib/useMarketHours.ts` → `web/lib/regime/useMarketHours.ts`. No deps. Exports `MarketState` enum + `useMarketHours()` hook.

- [ ] **Step 5: Port `pricesProtocol`**

Copy `/Users/chenxi/projects/xenon/web/lib/pricesProtocol.ts` → `web/lib/regime/pricesProtocol.ts`. Exports `PriceData` type (kept even with empty prices map).

- [ ] **Step 6: Port `chartSystem` (subset)**

Port only `chartSeriesColor(name: string): string` from `/Users/chenxi/projects/xenon/web/lib/chartSystem.ts` and its name→CSS-var lookup map. **Function takes a string key, NOT a numeric index** — `GexProfileChart` and other callers pass tokens like `"caution"`, `"dislocation"`. Numeric-index fallback would break them.

- [ ] **Step 7: Port `sectionTooltips` (GEX-only)**

Find which keys GEX uses:
```bash
grep -hoE 'SECTION_TOOLTIPS\["[^"]+"\]' \
  /Users/chenxi/projects/xenon/web/components/GexPanel.tsx | sort -u
```

Create `web/lib/regime/sectionTooltips.ts` exporting `SECTION_TOOLTIPS` with **only those keys** (lifted verbatim from xenon's file). Do not pull CRI/VCG/positions/orders keys.

- [ ] **Step 8: `web/lib/regime/types.ts`**

```typescript
import type { components } from "@/lib/types";

export type GexData = components["schemas"]["GexResponse"];
export type GexLevel = components["schemas"]["GexLevel"] | null;
export type GexLevels = components["schemas"]["GexLevels"];
export type GexBucket = components["schemas"]["GexBucket"];
export type GexBias = components["schemas"]["GexBias"];
export type GexHistoryEntry = components["schemas"]["GexHistoryEntry"];
export type GexExpectedRange = components["schemas"]["GexExpectedRange"];
export type MqLevels = components["schemas"]["GexMqLevels"];
export type SourceDelta = components["schemas"]["GexSourceDelta"];
export type SourceDeltaEntry = components["schemas"]["GexSourceDeltaEntry"];
export type IvData = components["schemas"]["GexIvData"];

export type RegimePendingResponse = components["schemas"]["RegimePendingResponse"];
```

- [ ] **Step 9: Type-check**

```bash
cd web && npx tsc --noEmit
```
Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add web/lib/regime/
git commit -m "feat(regime): port frontend libs for GEX (useSyncHook, useGex, market hours, tooltips)"
```

---

## Task 9: GEX components + d3 install

**Files** — create:
- `web/components/regime/GexSubTab.tsx` (port from `xenon/web/components/GexPanel.tsx`)
- `web/components/regime/GexProfileChart.tsx` (port; uses d3)
- `web/components/regime/charts/ChartPanel.tsx` (69 LOC port)
- `web/components/regime/charts/ChartLegend.tsx` (27 LOC port)
- `web/components/regime/ui/MetricCard.tsx` (87 LOC port)
- `web/components/regime/InfoTooltip.tsx` (port if not present elsewhere)
- `web/components/regime/PendingSubTab.tsx` (new — placeholder for CRI/VCG)

- [ ] **Step 1: Install d3**

```bash
cd web && npm install d3 @types/d3 --save
```
Expected: `d3` under `dependencies`, `@types/d3` under `devDependencies` in `package.json`.

Document the CLAUDE.md deviation in the PR description: "d3 added 2026-05-16 — scoped to `web/components/regime/*` for 1:1 visual port of xenon's GEX profile chart. Other charts remain hand-rolled SVG."

- [ ] **Step 2: Port chart wrappers**

- Copy `/Users/chenxi/projects/xenon/web/components/charts/ChartPanel.tsx` → `web/components/regime/charts/ChartPanel.tsx`.
- Copy `/Users/chenxi/projects/xenon/web/components/charts/ChartLegend.tsx` → `web/components/regime/charts/ChartLegend.tsx`.

Adjust any `@/lib/chartSystem` → `@/lib/regime/chartSystem`.

- [ ] **Step 3: Port `GexProfileChart`**

Copy `/Users/chenxi/projects/xenon/web/components/charts/GexProfileChart.tsx` → `web/components/regime/GexProfileChart.tsx`. Adjust:
- `import * as d3 from "d3"` stays
- `./ChartPanel` → `./charts/ChartPanel` (sibling moved into `charts/` subdir)
- `@/lib/chartSystem` → `@/lib/regime/chartSystem`

- [ ] **Step 4: Port `MetricCard`**

Copy `/Users/chenxi/projects/xenon/web/components/ui/MetricCard.tsx` → `web/components/regime/ui/MetricCard.tsx`. Both `MetricCard` and `SourceBadge` named exports — required by `GexSubTab`.

- [ ] **Step 5: Port `InfoTooltip`**

If not already present in this repo:
```bash
find web/components -name "InfoTooltip.tsx" -not -path "*/regime/*"
```
- If found: re-export from sibling location or just import the existing one.
- If not found: copy `/Users/chenxi/projects/xenon/web/components/InfoTooltip.tsx` → `web/components/regime/InfoTooltip.tsx`.

- [ ] **Step 6: Port `GexPanel` as `GexSubTab`**

Copy `/Users/chenxi/projects/xenon/web/components/GexPanel.tsx` (901 LOC) → `web/components/regime/GexSubTab.tsx`. Adjust:
- `useGex` → `@/lib/regime/useGex`
- `useMarketHours` / `MarketState` → `@/lib/regime/useMarketHours`
- `MetricCard, SourceBadge` from `./ui/MetricCard` (sibling)
- `GexProfileChart` from `./GexProfileChart` (sibling)
- `InfoTooltip` from `./InfoTooltip` (sibling)
- `SECTION_TOOLTIPS` → `@/lib/regime/sectionTooltips`
- **Strip:** `ShareReportModal` import + JSX (share-to-X out of scope)
- **Keep:** `marketState` prop
- Default export name: `GexSubTab`
- Component signature: `export default function GexSubTab({ marketState }: { marketState: MarketState })`

- [ ] **Step 7: Write `PendingSubTab` placeholder**

`web/components/regime/PendingSubTab.tsx`:

```typescript
import Link from "next/link";
import { Clock } from "lucide-react";

type Props = {
  name: "CRI" | "VCG";
  description: string;
};

export default function PendingSubTab({ name, description }: Props) {
  return (
    <div className="regime-pending" data-testid={`regime-pending-${name.toLowerCase()}`}>
      <Clock size={48} strokeWidth={1.5} />
      <h2>{name} — coming soon</h2>
      <p>{description}</p>
      <p className="regime-pending-link">
        Pending IB-via-R2 reader integration. See{" "}
        <Link href="/docs/superpowers/plans/2026-05-16-port-regime-from-xenon.md">
          the long-term roadmap
        </Link>{" "}
        for the full plan.
      </p>
    </div>
  );
}
```

(The `<Link href="/docs/...">` won't render as a real link in Next.js since the docs aren't routed — leave it for now; the executor can swap to a plain text reference if `next/link` complains. Cosmetic only.)

- [ ] **Step 8: Type-check**

```bash
cd web && npx tsc --noEmit
```
Expected: clean. If `@types/d3` resolution issues, re-run `npm install`.

- [ ] **Step 9: Commit**

```bash
git add web/package.json web/package-lock.json web/components/regime/
git commit -m "feat(regime): port GEX components + d3 + chart wrappers + pending placeholder"
```

---

## Task 10: `RegimePanel` tab shell

**File:** `web/components/regime/RegimePanel.tsx`

- [ ] **Step 1: Write the shell**

```typescript
"use client";

import { useState } from "react";
import GexSubTab from "./GexSubTab";
import PendingSubTab from "./PendingSubTab";
import { useMarketHours } from "@/lib/regime/useMarketHours";

type RegimeTab = "cri" | "vcg" | "gex";

const TABS: { id: RegimeTab; label: string }[] = [
  { id: "cri", label: "CRI" },
  { id: "vcg", label: "VCG" },
  { id: "gex", label: "GEX" },
];

const CRI_DESC = "Crash Risk Indicator — composite score from VIX, VVIX, COR1M implied correlation, and SPX momentum. Renders when VIX/VVIX/COR1M data is wired.";
const VCG_DESC = "Volatility-Credit Gap — rolling OLS residual between the vol complex (VIX/VVIX) and cash credit (HYG/JNK/LQD). Renders when VIX/VVIX data is wired.";

export default function RegimePanel() {
  const [activeTab, setActiveTab] = useState<RegimeTab>("gex");  // default to the working tab
  const marketState = useMarketHours();

  return (
    <div className="regime-panel" data-testid="regime-panel">
      <div className="ticker-tabs" style={{ marginBottom: "16px" }} data-testid="regime-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`ticker-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
            data-testid={`regime-tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {activeTab === "gex" && <GexSubTab marketState={marketState} />}
      {activeTab === "cri" && <PendingSubTab name="CRI" description={CRI_DESC} />}
      {activeTab === "vcg" && <PendingSubTab name="VCG" description={VCG_DESC} />}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/regime/RegimePanel.tsx
git commit -m "feat(regime): RegimePanel tab shell (GEX default, CRI/VCG pending)"
```

---

## Task 11: Page route + Sidebar nav

**Files:**
- Create: `web/app/regime/page.tsx`
- Modify: `web/components/shared/Sidebar.tsx`

- [ ] **Step 1: Create the page route**

```typescript
// web/app/regime/page.tsx
import RegimePanel from "@/components/regime/RegimePanel";

export const metadata = {
  title: "Regime — Unusual Whales",
  description: "Market-wide regime indicators: CRI, VCG, GEX",
};

export default function RegimePage() {
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">
          Crash Risk Indicator · Vol-Curve Gauge · Gamma Exposure
        </p>
      </header>
      <RegimePanel />
    </main>
  );
}
```

- [ ] **Step 2: Add nav link**

Edit `web/components/shared/Sidebar.tsx`. Find the `NAV` array (near line 7-11):

```diff
-import { LayoutDashboard, Radar, ScanLine } from "lucide-react";
+import { LayoutDashboard, Radar, ScanLine, Activity } from "lucide-react";

 const NAV = [
   { href: "/", label: "Dashboard", icon: LayoutDashboard },
   { href: "/scanner", label: "Scanner", icon: ScanLine },
   { href: "/cockpit/SPY", label: "Cockpit", icon: Radar },
+  { href: "/regime", label: "Regime", icon: Activity },
 ];
```

- [ ] **Step 3: Smoke**

```bash
bash scripts/dev.sh
```
Navigate to `http://localhost:3001/regime`:
- Sidebar shows new Regime link
- Page renders with GEX tab selected by default
- GEX tab shows real data (if scanner has run) or empty card (if not)
- Click CRI → shows pending placeholder with description text
- Click VCG → shows pending placeholder
- No console errors

Stop dev server (Ctrl+C).

- [ ] **Step 4: Commit**

```bash
git add web/app/regime/ web/components/shared/Sidebar.tsx
git commit -m "feat(regime): /regime page route + Sidebar nav"
```

---

## Task 12: CSS extraction (GEX selectors only)

**File:** `web/app/globals.css` (append)

- [ ] **Step 1: Extract GEX-relevant rules (preserving `@media`)**

Use the brace-balanced parser from the roadmap plan (`2026-05-16-port-regime-from-xenon.md` Task 11 Step 2). Narrow the prefix list to GEX scope:

```bash
XEN=/Users/chenxi/projects/xenon/web/app/globals.css
OUT=/tmp/regime-gex-css.css

node -e '
const fs = require("fs");
const src = fs.readFileSync(process.env.XEN, "utf8");
const PREFIXES = [".regime-panel", ".regime-page", ".regime-pending",
  ".gex-", ".ticker-tab", ".section-header", ".section-title",
  ".metric-card", ".chart-panel", ".chart-legend"];
const SKIP = [".regime-strip", ".regime-relationship", ".regime-history",
  ".regime-component-", ".regime-trigger-", ".regime-hero", ".cri-", ".vcg-",
  ".share-report-modal"];

function selectorMatches(sel) {
  if (SKIP.some(p => sel.includes(p))) return false;
  return PREFIXES.some(p => sel.includes(p));
}
// [parser body identical to roadmap plan Task 11 — handles @media wrappers]
' > $OUT
```

Then append `/tmp/regime-gex-css.css` to `web/app/globals.css` under a marker:

```css
/* ─── Regime/GEX (ported from xenon 2026-05-16) ──────────────────────── */
```

Add a `.regime-pending` block manually (xenon doesn't have it):

```css
.regime-pending {
  display: flex; flex-direction: column; align-items: center;
  padding: 48px 24px; gap: 12px; color: var(--text-muted);
  text-align: center;
}
.regime-pending h2 { font-size: 1.25rem; font-weight: 500; }
.regime-pending p { max-width: 480px; font-size: 0.95rem; line-height: 1.5; }
.regime-pending-link { font-size: 0.85rem; opacity: 0.7; }
```

- [ ] **Step 2: Verify in browser**

Run `bash scripts/dev.sh`, navigate to `/regime`, eyeball the layout against `xenon`'s `/regime` (open in another tab). Note any visual gaps. Fix missing CSS vars (`--chart-live-badge-bg`, etc.) by either adding to `:root` or substituting existing tokens.

- [ ] **Step 3: Commit**

```bash
git add web/app/globals.css
git commit -m "feat(regime): port GEX-related styles + add regime-pending block"
```

---

## Task 13: Tests — vitest + playwright

**Files:**
- Create: `web/tests/unit/regime-page.test.tsx`
- Create: `web/tests/e2e/regime-page.spec.ts`

- [ ] **Step 1: Vitest component test**

```typescript
// web/tests/unit/regime-page.test.tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import RegimePanel from "@/components/regime/RegimePanel";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      scan_time: "", market_open: false, ticker: "SPX",
      spot: null, close: null, day_change: null, day_change_pct: null, data_date: null,
      net_gex: null, net_dex: null, atm_iv: null, vol_pc: null,
      levels: { gex_flip: null, max_magnet: null, second_magnet: null, max_accelerator: null, put_wall: null, call_wall: null },
      profile: [],
      expected_range: { low: null, high: null, iv_1d: null },
      bias: { direction: null, reasons: [], days_above_flip: null, flip_migration: [] },
      history: [], iv: null, mq: null, source_delta: null,
    }),
  }));
});

describe("RegimePanel", () => {
  it("renders three sub-tab buttons with GEX active by default", () => {
    render(<RegimePanel />);
    expect(screen.getByTestId("regime-tab-cri")).toHaveTextContent("CRI");
    expect(screen.getByTestId("regime-tab-vcg")).toHaveTextContent("VCG");
    expect(screen.getByTestId("regime-tab-gex")).toHaveTextContent("GEX");
    expect(screen.getByTestId("regime-tab-gex")).toHaveClass("active");
  });

  it("shows pending placeholder on CRI tab", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-cri"));
    expect(screen.getByTestId("regime-pending-cri")).toBeInTheDocument();
    expect(screen.getByText(/coming soon/i)).toBeInTheDocument();
  });

  it("shows pending placeholder on VCG tab", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-vcg"));
    expect(screen.getByTestId("regime-pending-vcg")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run Vitest**

```bash
cd web && npm run test -- regime-page
```
Expected: 3 PASSED.

- [ ] **Step 3: Playwright smoke**

```typescript
// web/tests/e2e/regime-page.spec.ts
import { test, expect } from "@playwright/test";

test("/regime renders with three tabs and GEX default", async ({ page }) => {
  await page.goto("/regime");
  await expect(page.getByRole("heading", { name: "Regime" })).toBeVisible();
  await expect(page.getByTestId("regime-tab-cri")).toBeVisible();
  await expect(page.getByTestId("regime-tab-vcg")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toHaveClass(/active/);
});

test("CRI tab shows pending placeholder", async ({ page }) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-cri").click();
  await expect(page.getByText(/coming soon/i)).toBeVisible();
});
```

- [ ] **Step 4: Run Playwright**

```bash
cd web && npx playwright test regime-page
```
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add web/tests/unit/regime-page.test.tsx web/tests/e2e/regime-page.spec.ts
git commit -m "test(regime): vitest + playwright smoke for /regime page"
```

---

## Task 14: PR

- [ ] **Step 1: Push branch + open PR**

```bash
git push -u origin worktree-regime-port-from-xenon
gh pr create --title "feat(regime): port /regime page from xenon (GEX live, CRI/VCG pending)" --body "$(cat <<'EOF'
## Summary
- New `/regime` page with 3 sub-tabs (CRI / VCG / GEX), default GEX.
- GEX renders live UW data end-to-end: UW → scheduled scanner (5min) → Postgres → API → React via d3-using `GexProfileChart`.
- CRI and VCG render a friendly "coming soon — IB-via-R2 reader pending" placeholder.
- Sidebar gains a Regime nav entry.
- Pydantic schemas + Repository methods + APScheduler job + frontend hooks + tab shell all wired.

## Out of scope (follow-up plans)
- CRI / VCG backends — pending the IB-via-R2 parquet reader (separate project, currently flaky).
- MenthorQ key levels in GEX — Playwright dep, skipped for v1.
- Postgres → R2 backup — separate DB-ops concern.
- Full CRI/VCG frontend port (RegimeStrip, RegimeRelationshipView, CriHistoryChart) — see `docs/superpowers/plans/2026-05-16-port-regime-from-xenon.md` for the long-term roadmap.

## CLAUDE.md deviations (documented)
- **d3 + @types/d3 added** to `web/package.json`. Scoped to `web/components/regime/*` for the 1:1 visual port of xenon's `GexProfileChart`. Other charts in this repo remain hand-rolled SVG per CLAUDE.md. User-approved 2026-05-16.

## Test plan
- [x] `uv run pytest tests/unit/test_regime_schemas.py tests/integration/test_gex_repository.py tests/integration/test_gex_scanner.py tests/integration/api/test_regime_router.py`
- [x] `cd web && npm run test -- regime-page`
- [x] `cd web && npx playwright test regime-page`
- [x] Manual: `/regime` route renders, GEX tab default, CRI/VCG show placeholders
- [x] Manual: APScheduler GEX job populates `gex_snapshots` table within 30s of worker start
EOF
)"
```

---

## Backfill / follow-up plans (NOT scoped here)

When the IB-via-R2 reader stabilizes, the follow-up work to enable CRI/VCG is:

1. **New data source module**: `src/uw_scan/sources/r2_ib.py` — reads VIX/VVIX/COR1M/SPY (and HYG/JNK/LQD if useful) parquet files from R2 via `boto3` with R2 endpoint URL + token auth. ~150 LOC.
2. **CRI scanner**: port `xenon/src/xenon/scanners/cri.py` math + `_fetch_uw` for SPY + `r2_ib.fetch_index_history` for VIX/VVIX/COR1M. Drop IB code entirely. ~400 LOC.
3. **VCG scanner**: same pattern but for the VCG residual model.
4. **CRI/VCG frontend port**: pull from the long-term roadmap (`2026-05-16-port-regime-from-xenon.md` Tasks 7-9 — RegimeStrip, RegimeRelationshipView, CriHistoryChart, full VcgPanel).
5. **R2 → Postgres polling job**: APScheduler reads the latest R2 parquet every 5 min, persists to `cri_series` / `vcg_series`.

That's a separate plan when you're ready. For now, this iteration ships GEX.

---

## Self-review checks

- [x] All file paths are absolute or repo-relative.
- [x] Every step that writes code shows the code.
- [x] No `# TODO` / "TBD" placeholders.
- [x] Hooks return shape matches xenon's `UseSyncReturn<T>` (the copied `GexPanel` destructures `loading` and `syncNow`).
- [x] Default ticker is `SPX` everywhere (FastAPI, hooks, scheduler tickers list).
- [x] Tests cover: empty-state shape, pending sentinel, ticker uppercasing, real scan persists.
- [x] `gen:types` sequenced AFTER the API is started, BEFORE it's stopped.
- [x] Sidebar update targets `web/components/shared/Sidebar.tsx`.
- [x] CSS extraction preserves `@media` wrappers.
- [x] d3 deviation documented in PR description.
- [x] **Verified field shapes** against `docs/uw-samples/*.json` — iv_rank has `volatility`/`iv_rank_1y`/`close`/`date`; screener has `put_call_ratio`/`ticker`. All strings; xenon's `float()` casts handle coercion.
- [x] **Missing UW endpoints identified and added in Task 4 Step 1** — `GREEK_EXPOSURE_BY_STRIKE` + `GREEK_EXPOSURE_HISTORY` slugs and fetch functions. Endpoint paths match UW spec doc (`/api/stock/{ticker}/greek-exposure/strike` + `/api/stock/{ticker}/greek-exposure`).
- [x] **Spot price source corrected** — xenon's primary `/stock/{ticker}/info` not wired in this repo; Yahoo banned. Scanner uses iv_rank's `close` field as the sole spot source. iv_rank rows fetched once and shared by 3 derived helpers (atm_iv, iv_rank percentile, spot).
- [x] **Run-id audit threaded** through every UW call — matches existing pattern in `worker/jobs/cockpit_daily_snapshot.py:65` and `worker/jobs/flow_data_refresh.py:64`. Scanner inserts a `scan_runs` row at start and marks it `ok` / `error` at finish (idempotent).
- [x] **Scanner signature** `run(client, repo, ticker)` — UW client constructed at caller (router + scheduler) and passed in. Matches `volatility.py:75-90`.

## Review history

- 2026-05-16 Round 4 (Field-name + endpoint verification — push confidence to ~95%):
  - Verified UW field shapes against `docs/uw-samples/iv_rank.json` and `docs/uw-samples/bulk_screener_stocks_sp500.json`. All match xenon's expectations (string-valued numerics; `float()` casts handle coercion).
  - Found and patched 3 concrete gaps:
    1. This repo's `EndpointSlug.GREEK_EXPOSURE` maps to `/greek-exposure/strike-expiry` (per-strike-per-expiry); xenon's GEX scanner needs `/strike` (aggregated). Added new slug `GREEK_EXPOSURE_BY_STRIKE` + fetcher.
    2. Aggregate `/greek-exposure` endpoint wasn't wired. Added new slug `GREEK_EXPOSURE_HISTORY` + fetcher.
    3. Spot-price source `/stock/{ticker}/info` not in this repo. Dropped that fallback chain; scanner now uses only iv_rank's `close` field. iv_rank fetched once, shared by 3 derived helpers.
  - Scanner orchestration updated to use this repo's run-id audit pattern (`repo.insert_scan_run(...)` + `finish_scan_run(...)`) — matches existing scanner conventions.
  - Scanner signature changed: `run(client, repo, ticker)` — UwClient passed in by caller (router uses `Depends(get_settings)` + `UwClient.from_settings(s)`; scheduler builds it once per tick).
  - Integration tests adjusted: monkeypatch the scanner's fetch_* functions (not at uw client level) — bypasses real network; covers the new `finish_scan_run("error")` path on abort.
- 2026-05-16 Initial draft (this plan, after long-term roadmap was deferred).
