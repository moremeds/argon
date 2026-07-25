# UW Historical Alpha — Recurring Capture + Self-Healing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give five UW-derived alpha tables (`uw_gex_levels_daily`, `uw_volatility_signal_daily`, `uw_short_pressure_daily`, `uw_intraday_option_flow_bars`, `uw_dark_lit_flow_prints`) the standard Argon lifecycle — migration → fetcher → normalizer → storage → recurring worker capture → `data_gap_healer` self-healing — and catch up the 2026-07-02→go-live gap.

**Architecture:** Follow the existing `greek_exposure_daily` precedent end-to-end. The three `(ticker, market_date)` daily tables become `strict_ticker_date` healer datasets with a per-ticker-date capture function shared by the nightly job *and* the heal adapter. The two append-only event-log tables become `freshness_only` (monitored, not gap-healed), with their own nightly capture. All five are freshness-monitored. Catch-up for the three strict tables IS the healer (`data_gap_healer.py execute`); the two event-log tables get a thin date-loop backfill on the same capture functions.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, Pydantic v2, APScheduler, FastAPI. Postgres schema `uw_scan`. Tests: pytest + pytest-postgresql (no mocked DB).

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`.
- **No synthetic data** — every test fixture is a REAL frozen UW *endpoint envelope*, captured via a controlled one-time live fetch (Task 1.1). The mini's table `raw_jsonb` is NOT a faithful fixture: the branch backfill stripped the `data` envelope, merged the 3 volatility sub-responses into one object, and bypassed `raw_payloads` (bare httpx) — so no true envelope was ever stored (codex tribunal #6). No invented values; credentials come from the environment, never a literal in a committed file.
- **Endpoint truth is empirical, not the curated docs.** Four source endpoints (`gex-levels`, `volatility/{anomaly,character,variance-risk-premium}`) are absent from `docs/uw-samples/` and the UW MCP but are REAL (75k+ live rows on the mini, `gex-levels` history to 2023). Authoritative paths come from `scripts/backfill/uw_historical_alpha_backfill.py` (branch `cda8717`) + live re-probe. See spec §12/§13.
- **Non-standard payload shapes** — `gex-levels` → single `data` object; `anomaly`/`character` → `data:{history,latest}`. `normalize._data_list` (assumes `data` is a list) does NOT apply to these; write custom normalizers.
- **Storage:** new domain → standalone `storage/uw_historical_alpha_repository.py`. NEVER add to `repository.py`; NEVER a `Repository` mixin.
- **Models:** subclass `_UwBase`; end each module with `_preserve_public_module(...)`; re-export surgically from `models/__init__.py` import block + `__all__`; run `cd web && npm run gen:types` after.
- **Migrations:** idempotent (`CREATE TABLE IF NOT EXISTS`), header `SET search_path TO uw_scan, public;`. Next number is **108** (main is at 107; the branch's `095`/`096` collide with main's and must be renumbered).
- **Worker env freezes at fork** — flipping a flag needs a worker restart (APScheduler does not hot-reload).
- **Nightly captures are NOT budget-gated** — follow the greek/surface precedent; do NOT call `_research_budget_ok` (they run near the 20:00 ET reset; gating starves durable data). The account-wide guard in `may_spend` still catches runaway.
- **Commit policy:** milestone commit per phase after its verification passes. PR before merge to main; CI green before merge; no `Co-Authored-By` trailer; `[Unreleased]` CHANGELOG entry rides this branch.
- **Config-flag:** ONE master flag `UW_SCAN_UW_ALPHA_CAPTURE_ENABLED` (default `False`, promotable-off) gates all five capture jobs.

---

## Phase 0 — Branch hygiene (rebase, drop riders, renumber)

**Deliverable:** the resumed branch on top of current main, oi_change + long-weekend riders removed, migration renumbered, baseline tests green. No feature code yet.

### Task 0.1: Worktree + rebase

**Files:** none (git mechanics).

- [ ] **Step 1: Create the worktree on the existing branch**

```bash
cd /Users/chenxi/projects/argon
git worktree add .worktrees/uw-historical-alpha-scan misc/uw-historical-alpha-scan
cd .worktrees/uw-historical-alpha-scan
```

- [ ] **Step 2: Real dependency install in the worktree** (Turbopack panics on symlinked node_modules, but there are no web changes here — Python only)

```bash
uv sync --extra postgres
```

- [ ] **Step 3: Rebase onto main**

```bash
git rebase main
```

Expected conflict: `src/uw_scan/sources/uw.py` (the branch removes #225's memo). **Resolution: take main's version entirely** — `git checkout --theirs src/uw_scan/sources/uw.py && git add src/uw_scan/sources/uw.py`. The branch's `market_date` param on `fetch_oi_change` is already on main via #225; the memo must survive.

- [ ] **Step 4: Verify the memo survived the rebase**

```bash
grep -c "_memoized_fetch_json" src/uw_scan/sources/uw.py
```

Expected: `≥ 3` (definition + call sites). If `0`, the rebase clobbered the memo — redo Step 3.

### Task 0.2: Drop the superseded oi_change + long-weekend riders

**Files:**
- Delete: `src/uw_scan/storage/migrations/096_oi_change_historical_key.sql`
- Delete: `scripts/backfill/uw_long_weekend_history_backfill.py`, `scripts/backfill/uw_long_weekend_chain_watcher.sh`
- Delete: `tests/unit/test_oi_change_historical_upsert.py`, `tests/unit/test_uw_sources_oi_change_date.py`, `tests/unit/test_uw_long_weekend_history_backfill.py`
- Delete: `docs/plans/2026-07-03-uw-long-weekend-history-backfill.md`
- Modify: `src/uw_scan/storage/options.py` (remove `replace_oi_change_rows_for_date`)

- [ ] **Step 1: Remove the oi_change historical upsert method** from `src/uw_scan/storage/options.py` — delete the `replace_oi_change_rows_for_date` method (the +46-line block added by the branch; `git show cda8717 -- src/uw_scan/storage/options.py` shows the exact span). Nothing on main calls it.

- [ ] **Step 2: Delete the rider files**

```bash
git rm src/uw_scan/storage/migrations/096_oi_change_historical_key.sql \
       scripts/backfill/uw_long_weekend_history_backfill.py \
       scripts/backfill/uw_long_weekend_chain_watcher.sh \
       tests/unit/test_oi_change_historical_upsert.py \
       tests/unit/test_uw_sources_oi_change_date.py \
       tests/unit/test_uw_long_weekend_history_backfill.py \
       docs/plans/2026-07-03-uw-long-weekend-history-backfill.md
```

- [ ] **Step 3: Renumber the tables migration**

```bash
git mv src/uw_scan/storage/migrations/095_uw_historical_alpha_tables.sql \
       src/uw_scan/storage/migrations/108_uw_historical_alpha_tables.sql
```

- [ ] **Step 4: Apply migrations on local + run baseline tests**

```bash
bash scripts/migrate.sh
uv run pytest -q
```

Expected: migrations apply clean (108 creates the 5 tables on `option_wizard_local`); the full suite is GREEN (the 3 deleted tests are gone; nothing references them). If a test imports `replace_oi_change_rows_for_date`, you missed a caller — grep and fix.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(uw-alpha): rebase branch, drop superseded oi_change/long-weekend riders, renumber migration to 108"
```

---

## Phase 1 — Migration data, models, endpoints, normalizers

**Deliverable:** the 5 EndpointSlugs, typed row models, and custom normalizers, each proven against a REAL frozen payload. No network at test time.

### Task 1.1: Capture real fixtures from the mini

**Files:**
- Create: `tests/fixtures/uw/gex_levels_aapl.json`, `volatility_anomaly_aapl.json`, `volatility_character_aapl.json`, `volatility_vrp_aapl.json`, `net_prem_ticks_aapl.json`, `greek_flow_aapl.json`, `lit_flow_aapl.json`, `darkpool_aapl.json`, `interest_float_aapl.json`, `ftds_aapl.json`, `volumes_by_exchange_aapl.json`

- [ ] **Step 1: Capture each real endpoint envelope via a controlled one-time live fetch.** The mini's `raw_jsonb` is NOT usable (stripped/merged; `raw_payloads` bypassed — codex #6). Capture the true envelopes once, straight from UW. Auth is `Authorization: Bearer <key>` (verified `api/client.py:111`); read the key from the environment — **no literal secret in any committed file**:

```bash
# scratch capture (do NOT commit this snippet) — ~11 UW calls total, trivial spend
uv run python - <<'PY'
import json, pathlib, httpx
from uw_scan.config import Settings
s = Settings.from_env()
key = s.api_key.get_secret_value()
cli = httpx.Client(base_url=s.base_url, headers={"Authorization": f"Bearer {key}"}, timeout=30)
out = pathlib.Path("tests/fixtures/uw"); out.mkdir(parents=True, exist_ok=True)
D = {"date": "2026-06-30"}
calls = {
    "gex_levels_aapl.json": ("/api/stock/AAPL/gex-levels", D),
    "volatility_anomaly_aapl.json": ("/api/stock/AAPL/volatility/anomaly", D),
    "volatility_character_aapl.json": ("/api/stock/AAPL/volatility/character", D),
    "volatility_vrp_aapl.json": ("/api/stock/AAPL/volatility/variance-risk-premium", D),
    "net_prem_ticks_aapl.json": ("/api/stock/AAPL/net-prem-ticks", {**D, "limit": 500}),
    "greek_flow_aapl.json": ("/api/stock/AAPL/greek-flow", D),
    "lit_flow_aapl.json": ("/api/lit-flow/AAPL", {**D, "limit": 500}),
    "darkpool_aapl.json": ("/api/darkpool/AAPL", {**D, "limit": 500}),
    "interest_float_aapl.json": ("/api/shorts/AAPL/interest-float/v2", None),
    "ftds_aapl.json": ("/api/shorts/AAPL/ftds", None),
    "volumes_by_exchange_aapl.json": ("/api/shorts/AAPL/volumes-by-exchange", None),
}
for fname, (path, params) in calls.items():
    r = cli.get(path, params=params or {})
    r.raise_for_status()
    (out / fname).write_text(json.dumps(r.json(), indent=2))
    print(fname, r.status_code, "top-keys=", list(r.json())[:5])
PY
```

Each file is the exact envelope UW returns (e.g. `{"data": {...}}` for gex-levels, `{"data": {"history": [...], "latest": {...}}}` for anomaly/character) — the shape the normalizers must parse. **Never hand-author these.**

- [ ] **Step 2: Eyeball each fixture** confirms the documented shape: `gex_levels_aapl.json` has top-level `data` = object with `call_wall`/`put_wall`/`gamma_flip`/`gamma_magnet`; `volatility_anomaly_aapl.json` has `data.history[]` + `data.latest`. Record the actual key names — the models in 1.3 must match them exactly.

- [ ] **Step 3: Commit the fixtures**

```bash
git add tests/fixtures/uw/
git commit -m "test(uw-alpha): freeze real UW payloads for the 5 alpha datasets"
```

### Task 1.2: Add the 9 new EndpointSlugs

**Files:**
- Modify: `src/uw_scan/api/endpoints.py` (`EndpointSlug` enum + `REGISTRY`)
- Test: `tests/unit/test_endpoints.py` (or the existing endpoints test module)

**Interfaces produced:** `EndpointSlug.GEX_LEVELS`, `VOLATILITY_ANOMALY`, `VOLATILITY_CHARACTER`, `VOLATILITY_VRP`, `NET_PREM_TICKS`, `GREEK_FLOW`, `LIT_FLOW`, `FTDS`, `VOLUMES_BY_EXCHANGE` and their `build_path(...)` templates.

- [ ] **Step 1: Write the failing test** (`tests/unit/test_endpoints.py`)

```python
import pytest
from uw_scan.api.endpoints import EndpointSlug, build_path

@pytest.mark.parametrize("slug,expected", [
    (EndpointSlug.GEX_LEVELS, "/api/stock/AAPL/gex-levels"),
    (EndpointSlug.VOLATILITY_ANOMALY, "/api/stock/AAPL/volatility/anomaly"),
    (EndpointSlug.VOLATILITY_CHARACTER, "/api/stock/AAPL/volatility/character"),
    (EndpointSlug.VOLATILITY_VRP, "/api/stock/AAPL/volatility/variance-risk-premium"),
    (EndpointSlug.NET_PREM_TICKS, "/api/stock/AAPL/net-prem-ticks"),
    (EndpointSlug.GREEK_FLOW, "/api/stock/AAPL/greek-flow"),
    (EndpointSlug.LIT_FLOW, "/api/lit-flow/AAPL"),
    (EndpointSlug.FTDS, "/api/shorts/AAPL/ftds"),
    (EndpointSlug.VOLUMES_BY_EXCHANGE, "/api/shorts/AAPL/volumes-by-exchange"),
])
def test_new_alpha_endpoint_paths(slug, expected):
    assert build_path(slug, "AAPL") == expected
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/unit/test_endpoints.py -k alpha_endpoint -v` → FAIL (`AttributeError: GEX_LEVELS`).

- [ ] **Step 3: Add the enum members** (append to `EndpointSlug`, `src/uw_scan/api/endpoints.py`)

```python
    GEX_LEVELS = "gex_levels"
    VOLATILITY_ANOMALY = "volatility_anomaly"
    VOLATILITY_CHARACTER = "volatility_character"
    VOLATILITY_VRP = "volatility_vrp"
    NET_PREM_TICKS = "net_prem_ticks"
    GREEK_FLOW = "greek_flow"
    LIT_FLOW = "lit_flow"
    FTDS = "ftds"
    VOLUMES_BY_EXCHANGE = "volumes_by_exchange"
```

- [ ] **Step 4: Add the REGISTRY path templates** (in the `REGISTRY` dict, matching the existing `Endpoint(slug, path_template, required_params)` dataclass shape). Note `LIT_FLOW` is top-level, not under `/stock/`; `date`/`limit` are optional → `required_params=()`:

```python
    EndpointSlug.GEX_LEVELS: Endpoint(EndpointSlug.GEX_LEVELS, "/api/stock/{ticker}/gex-levels", ()),
    EndpointSlug.VOLATILITY_ANOMALY: Endpoint(EndpointSlug.VOLATILITY_ANOMALY, "/api/stock/{ticker}/volatility/anomaly", ()),
    EndpointSlug.VOLATILITY_CHARACTER: Endpoint(EndpointSlug.VOLATILITY_CHARACTER, "/api/stock/{ticker}/volatility/character", ()),
    EndpointSlug.VOLATILITY_VRP: Endpoint(EndpointSlug.VOLATILITY_VRP, "/api/stock/{ticker}/volatility/variance-risk-premium", ()),
    EndpointSlug.NET_PREM_TICKS: Endpoint(EndpointSlug.NET_PREM_TICKS, "/api/stock/{ticker}/net-prem-ticks", ()),
    EndpointSlug.GREEK_FLOW: Endpoint(EndpointSlug.GREEK_FLOW, "/api/stock/{ticker}/greek-flow", ()),
    EndpointSlug.LIT_FLOW: Endpoint(EndpointSlug.LIT_FLOW, "/api/lit-flow/{ticker}", ()),
    EndpointSlug.FTDS: Endpoint(EndpointSlug.FTDS, "/api/shorts/{ticker}/ftds", ()),
    EndpointSlug.VOLUMES_BY_EXCHANGE: Endpoint(EndpointSlug.VOLUMES_BY_EXCHANGE, "/api/shorts/{ticker}/volumes-by-exchange", ()),
```

- [ ] **Step 5: Run to verify it passes** — `uv run pytest tests/unit/test_endpoints.py -k alpha_endpoint -v` → PASS.

- [ ] **Step 6: Commit** — `git commit -am "feat(uw-alpha): add 9 EndpointSlugs for the alpha datasets"`

### Task 1.3: Row models

**Files:**
- Create: `src/uw_scan/models/uw_alpha.py`
- Modify: `src/uw_scan/models/__init__.py` (import block + `__all__`)
- Test: `tests/unit/test_models_uw_alpha.py`

**Interfaces produced:** `GexLevelsRow`, `VolAnomalyRow`, `VolCharacterRow`, `VolVrpRow`, `NetPremTickRow`, `GreekFlowRow`, `DarkLitPrint`, `FtdRow`, `VolumesByExchangeRow`.

**Two corrections from the codex tribunal:**
- Short-pressure's interest-float leg **reuses the existing `fetch_short_interest_float` (returns a dict)** — no new model/normalizer for it. Do NOT add a `normalize_short_interest_float`; the name already exists (`normalize.py:94`, returns a `dict`, consumed by `positioning_jobs.py`) and a redefinition would clobber it and break its tests (codex #3).
- `DarkLitPrint` serves BOTH `source='darkpool'` and `source='lit_flow'`. Do NOT reuse the existing `DarkPoolPrint` model — its `sale_cond_codes` is a scalar `str`, but the `uw_dark_lit_flow_prints.sale_cond_codes` column is `TEXT[]` (codex #8).

- [ ] **Step 1: Write the failing test** (fields taken from the backfill parse keys, `cda8717`; adjust to the real fixture keys observed in 1.1):

```python
from decimal import Decimal
from datetime import date
from uw_scan.models import GexLevelsRow, VolAnomalyRow, VolVrpRow

def test_gex_levels_row_parses_decimals():
    r = GexLevelsRow(market_date=date(2026, 6, 30), ticker="AAPL",
                     call_wall="210.5", put_wall="190", gamma_flip="200", gamma_magnet="205", spot="201.3")
    assert r.call_wall == Decimal("210.5") and r.ticker == "AAPL"

def test_vol_anomaly_row_optional_fields():
    r = VolAnomalyRow(date=date(2026, 6, 30), direction="up", score="1.2")
    assert r.score == Decimal("1.2")
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/unit/test_models_uw_alpha.py -v` → FAIL (import error).

- [ ] **Step 3: Write the models** (`src/uw_scan/models/uw_alpha.py`). Field names must match the frozen fixtures from 1.1. `ticker`/`market_date` are query params, not body fields → carried on the model so storage can key by them (annotate in the normalizer, Task 1.4):

```python
"""UW historical-alpha row contracts (gex-levels, volatility signals, short
pressure, intraday flow bars, dark/lit prints). Endpoints are real but absent
from the curated UW reference — see docs/superpowers/specs/2026-07-24-*.md §12."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase


class GexLevelsRow(_UwBase):
    ticker: str
    market_date: _date
    call_wall: Decimal | None = None
    put_wall: Decimal | None = None
    gamma_flip: Decimal | None = None
    gamma_magnet: Decimal | None = None
    spot: Decimal | None = None


class VolAnomalyRow(_UwBase):
    date: _date
    direction: str | None = None
    score: Decimal | None = None


class VolCharacterRow(_UwBase):
    date: _date
    character: str | None = None
    half_life_days: Decimal | None = None
    hurst_rv: Decimal | None = None


class VolVrpRow(_UwBase):
    date: _date
    rank: Decimal | None = None
    risk_premium: Decimal | None = None


class NetPremTickRow(_UwBase):
    ts: datetime
    net_call_premium: Decimal | None = None
    net_put_premium: Decimal | None = None
    net_delta: Decimal | None = None
    call_volume: int | None = None
    put_volume: int | None = None


class GreekFlowRow(_UwBase):
    ts: datetime
    dir_delta_flow: Decimal | None = None
    dir_vega_flow: Decimal | None = None
    otm_dir_delta_flow: Decimal | None = None
    otm_dir_vega_flow: Decimal | None = None
    transactions: int | None = None
    volume: int | None = None


class DarkLitPrint(_UwBase):
    # ONE model for both source='darkpool' and source='lit_flow'. NOT the existing
    # DarkPoolPrint — its sale_cond_codes is a scalar str, but this table's column
    # is TEXT[] (codex #8). All migration-108 columns are modeled (no silent loss).
    tracking_id: str
    ticker: str
    executed_at: datetime
    price: Decimal | None = None
    size: int | None = None
    premium: Decimal | None = None
    market_center: str | None = None
    nbbo_bid: Decimal | None = None
    nbbo_ask: Decimal | None = None
    nbbo_bid_quantity: int | None = None
    nbbo_ask_quantity: int | None = None
    sale_cond_codes: list[str] | None = None
    trade_code: str | None = None

# (ShortInterestFloatRow dropped — the short-pressure interest-float leg reuses the
#  existing dict-returning fetch_short_interest_float; see Task 1.4 note, codex #3.)
# NetPremTickRow/GreekFlowRow carry no `expiry`: the base net-prem-ticks/greek-flow
# endpoints are not per-expiry, so the storage insert writes the migration default
# sentinel '0001-01-01' for the PK's expiry column (per-expiry greek-flow is out of scope).


class FtdRow(_UwBase):
    date: _date
    price: Decimal | None = None
    quantity: Decimal | None = None


class VolumesByExchangeRow(_UwBase):
    date: _date
    short_volume: Decimal | None = None
    total_volume: Decimal | None = None
    short_volume_ratio: Decimal | None = None


_preserve_public_module(
    GexLevelsRow, VolAnomalyRow, VolCharacterRow, VolVrpRow,
    NetPremTickRow, GreekFlowRow, DarkLitPrint,
    FtdRow, VolumesByExchangeRow,
)
```

- [ ] **Step 4: Re-export from `models/__init__.py`** — add an import block and the names to `__all__` (surgically; generated-file diffing rule):

```python
from .uw_alpha import (
    DarkLitPrint,
    FtdRow,
    GexLevelsRow,
    GreekFlowRow,
    NetPremTickRow,
    VolAnomalyRow,
    VolCharacterRow,
    VolumesByExchangeRow,
    VolVrpRow,
)
```

Add the same nine names into the `__all__` tuple.

- [ ] **Step 5: Run to verify it passes** — `uv run pytest tests/unit/test_models_uw_alpha.py -v` → PASS.

- [ ] **Step 6: Model-export + OpenAPI checks** — `uv run pytest tests/unit/test_models_exports.py -q` → PASS (confirms `__all__`/`__module__` surface intact).

- [ ] **Step 7: Regenerate types + commit** — `cd web && npm run gen:types && cd ..` (surface new models to `web/lib/types.ts`), then `git commit -am "feat(uw-alpha): row models for the 5 alpha datasets"`.

### Task 1.4: Custom normalizers

**Files:**
- Modify: `src/uw_scan/normalize.py`
- Test: `tests/unit/test_normalize_uw_alpha.py`

**Interfaces produced:** `normalize_gex_levels(payload, ticker, market_date) -> GexLevelsRow | None`; `normalize_vol_anomaly(payload) -> list[VolAnomalyRow]`; `normalize_vol_character(payload) -> list[VolCharacterRow]`; `normalize_vol_vrp(payload) -> list[VolVrpRow]`; `normalize_net_prem_ticks(payload) -> list[NetPremTickRow]`; `normalize_greek_flow(payload) -> list[GreekFlowRow]`; `normalize_dark_lit(payload, source) -> list[DarkLitPrint]` (serves both darkpool + lit_flow, tags `source`); `normalize_ftds(payload) -> list[FtdRow]`; `normalize_volumes_by_exchange(payload) -> list[VolumesByExchangeRow]`. (No interest-float normalizer — the short-pressure capture reuses the existing dict-returning `fetch_short_interest_float`, codex #3.)

- [ ] **Step 1: Write the failing test** using the REAL frozen fixtures from 1.1:

```python
import json
from datetime import date
from pathlib import Path
from uw_scan import normalize

FIX = Path("tests/fixtures/uw")

def _load(name):
    return json.loads((FIX / name).read_text())

def test_normalize_gex_levels_single_object():
    row = normalize.normalize_gex_levels(_load("gex_levels_aapl.json"), "AAPL", date(2026, 6, 30))
    assert row is not None and row.ticker == "AAPL" and row.market_date == date(2026, 6, 30)
    assert row.call_wall is not None

def test_normalize_vol_anomaly_history_wrapper():
    rows = normalize.normalize_vol_anomaly(_load("volatility_anomaly_aapl.json"))
    assert rows and all(r.date is not None for r in rows)

def test_normalize_gex_levels_empty_returns_none():
    assert normalize.normalize_gex_levels({"data": None}, "AAPL", date(2026, 6, 30)) is None
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/unit/test_normalize_uw_alpha.py -v` → FAIL.

- [ ] **Step 3: Write the normalizers** (`src/uw_scan/normalize.py`; add the 9 models to the top-of-file `from .models import (...)` block first). These match the ACTUAL shapes — `gex-levels` is a single `data` object (not a list); `anomaly`/`character` are `data:{history[], latest}`; `vrp` and the event-log endpoints are plain `data:[...]` lists (modeled on backfill `cda8717` lines 312–345, 369–393):

```python
def normalize_gex_levels(payload: dict, ticker: str, market_date: date) -> GexLevelsRow | None:
    data = payload.get("data", payload)
    if not isinstance(data, dict) or not data:
        return None
    return GexLevelsRow(
        ticker=ticker.upper(),
        market_date=market_date,
        call_wall=data.get("call_wall"),
        put_wall=data.get("put_wall"),
        gamma_flip=data.get("gamma_flip"),
        gamma_magnet=data.get("gamma_magnet"),
        spot=data.get("spot") or data.get("price"),
    )


def _history_rows(payload: dict) -> list[dict]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return []
    rows = list(data.get("history") or [])
    latest = data.get("latest")
    if isinstance(latest, dict) and latest.get("date"):
        if not any(r.get("date") == latest["date"] for r in rows):
            rows.append(latest)
    return rows


def normalize_vol_anomaly(payload: dict) -> list[VolAnomalyRow]:
    return [VolAnomalyRow(**r) for r in _history_rows(payload) if r.get("date")]


def normalize_vol_character(payload: dict) -> list[VolCharacterRow]:
    return [VolCharacterRow(**r) for r in _history_rows(payload) if r.get("date")]


def normalize_vol_vrp(payload: dict) -> list[VolVrpRow]:
    # VRP is a plain `data:[...]` trailing series, NOT the {history,latest}
    # wrapper (confirmed against the branch backfill cda8717:330 in review).
    return [VolVrpRow(**r) for r in _data_list(payload) if r.get("date")]
```

**VRP shape (Finding 1.3, confirmed by codex #5):** VRP returns a plain `data:[...]` trailing series, NOT the `{history,latest}` wrapper used by anomaly/character — so `normalize_vol_vrp` uses `_data_list`, not `_history_rows` (which returns `[]` for a list payload and would silently drop every VRP row). The Task-1.4 test asserts non-empty output against the real frozen fixture, so any residual shape surprise fails loudly.

For `net_prem_ticks`/`greek_flow`/`lit_flow`/`ftds`/`volumes_by_exchange`/`short_interest_float`: these return the standard `data:[...]` list — use `_data_list` and splat, mapping the timestamp key the fixture actually uses (`tape_time`/`timestamp` → `ts`, `executed_at`/`id`→`tracking_id`). **The `ts` field is non-optional in the model, so this key-mapping is mandatory — a raw `tape_time` key would make Pydantic raise.** Example:

```python
def normalize_dark_lit(payload: dict, source: str) -> list[DarkLitPrint]:
    # Serves both source='darkpool' and source='lit_flow' (fetcher passes source).
    # sale_cond_codes stays a list (TEXT[] column) — do not stringify it.
    out: list[DarkLitPrint] = []
    for r in _data_list(payload):
        row = dict(r)
        row.setdefault("tracking_id", str(row.get("tracking_id") or row.get("id")))
        out.append(DarkLitPrint(**row))
    return out
```

Raise `NormalizationError` (from `_data_list`) on malformed list payloads; return `None`/`[]` on legitimately empty ones (the fetcher/capture treats empty as no-data, not an error).

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/unit/test_normalize_uw_alpha.py -v` → PASS on the real fixtures.

- [ ] **Step 5: Commit** — `git commit -am "feat(uw-alpha): custom normalizers for non-standard alpha payload shapes"`

---

## Phase 2 — Fetchers + storage

**Deliverable:** 5 UW fetchers + a standalone storage repo (3 keyed upserts, 2 insert-ignore), proven by pytest-postgresql writes.

### Task 2.1: Fetchers

**Files:**
- Modify: `src/uw_scan/sources/uw.py` (add the 9 models to the imports block; add fetchers)
- Test: `tests/unit/test_uw_fetchers_alpha.py` (mock the `UwClient.get`, assert path+params+normalized return — the standard fetcher unit test)

**Interfaces produced:** `fetch_gex_levels(client, repo, run_id, ticker, market_date)`, `fetch_volatility_anomaly/character/vrp(...)`, `fetch_net_prem_ticks(...)`, `fetch_greek_flow(...)`, `fetch_lit_flow(...)`, `fetch_darkpool_prints(client, repo, run_id, ticker, market_date, limit=500)`, `fetch_ftds(...)`, `fetch_volumes_by_exchange(...)`. All take `market_date: date | None = None` and use the historical-selector idiom (`params={"date": market_date.isoformat()}`) via plain `_fetch_json` (NOT memoized — past-date history isn't a slow-moving same-day snapshot; follow `fetch_volatility_stats`, uw.py:201–215).

**`fetch_darkpool_prints` is a NEW fetcher (codex #4)** — the existing `fetch_darkpool_ticker` (uw.py:561) sends neither `date` nor `limit`, so it can't backfill history. Do NOT modify it; add the new one on the same `EndpointSlug.DARKPOOL_TICKER` slug with `params={"date": market_date.isoformat(), "limit": limit}`. The short-pressure interest-float leg **reuses the existing `fetch_short_interest_float`** (codex #3) — not added here.

- [ ] **Step 1: Write the failing test** (one representative; replicate per fetcher):

```python
from datetime import date
from unittest.mock import MagicMock
import json
from pathlib import Path
from uw_scan.sources import uw
from uw_scan.api.endpoints import EndpointSlug

def test_fetch_gex_levels_calls_path_and_normalizes(monkeypatch):
    payload = json.loads(Path("tests/fixtures/uw/gex_levels_aapl.json").read_text())
    captured = {}
    def fake_fetch_json(client, repo, run_id, slug, ticker, params=None, **kw):
        captured.update(slug=slug, ticker=ticker, params=params)
        return payload
    monkeypatch.setattr(uw, "_fetch_json", fake_fetch_json)
    row = uw.fetch_gex_levels(MagicMock(), MagicMock(), 1, "AAPL", date(2026, 6, 30))
    assert captured["slug"] == EndpointSlug.GEX_LEVELS
    assert captured["params"] == {"date": "2026-06-30"}
    assert row.ticker == "AAPL"
```

- [ ] **Step 2: Run to verify it fails** — FAIL (`fetch_gex_levels` undefined).

- [ ] **Step 3: Write the fetchers** (`src/uw_scan/sources/uw.py`):

```python
def fetch_gex_levels(
    client: UwClient, repo: Repository, run_id: int, ticker: str,
    market_date: date | None = None,
) -> GexLevelsRow | None:
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.GEX_LEVELS, ticker, params=params)
    md = market_date or datetime.now(_ET).date()
    return normalize.normalize_gex_levels(body, ticker, md)


def fetch_volatility_anomaly(
    client: UwClient, repo: Repository, run_id: int, ticker: str,
    market_date: date | None = None,
) -> list[VolAnomalyRow]:
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.VOLATILITY_ANOMALY, ticker, params=params)
    return normalize.normalize_vol_anomaly(body)
```

`fetch_volatility_character`, `fetch_volatility_vrp`, `fetch_net_prem_ticks`, `fetch_greek_flow`, `fetch_lit_flow`, `fetch_ftds`, `fetch_volumes_by_exchange` follow the same two-line shape with their own slug + normalizer. `fetch_ftds`/`fetch_volumes_by_exchange` pass no `date` param (full-history endpoints).

**Pagination ceiling (ponytail):** `fetch_lit_flow` / `fetch_darkpool` / `fetch_net_prem_ticks` pass `params={"date": …, "limit": 500}` (matching the branch backfill) and do **not** cursor-paginate. A high-volume day can exceed 500 prints/ticker and truncate. That is acceptable for these two `freshness_only` event-log tables (approximate capture, not exact coverage) — but the capture job **must `log()` when a response row-count hits the limit** so the truncation is visible, never silent. Add cursor pagination only if a downstream consumer ever needs complete daily prints.

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/unit/test_uw_fetchers_alpha.py -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(uw-alpha): UW fetchers for the 5 alpha datasets"`

### Task 2.2: Storage repository

**Files:**
- Create: `src/uw_scan/storage/uw_historical_alpha_repository.py`
- Test: `tests/integration/storage/test_uw_historical_alpha_repository.py`

**Interfaces produced:** `UwHistoricalAlphaRepository(conn, schema)` with `upsert_gex_levels(rows) -> int`, `upsert_volatility_signal(rows) -> int`, `upsert_short_pressure(rows) -> int` (all `ON CONFLICT (ticker, market_date) DO UPDATE`), `insert_dark_lit_prints(rows) -> int`, `insert_intraday_flow_bars(rows) -> int` (both `ON CONFLICT DO NOTHING`).

- [ ] **Step 1: Write the failing integration test** (pytest-postgresql — real DB, migration 108 applied by the fixture):

```python
from datetime import date, datetime, timezone
from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository

def test_upsert_gex_levels_idempotent(db_conn):  # db_conn = migrated pytest-postgresql conn
    r = UwHistoricalAlphaRepository(db_conn, schema="uw_scan")
    row = {"ticker": "AAPL", "market_date": date(2026, 6, 30), "call_wall": "210.5",
           "put_wall": "190", "gamma_flip": "200", "gamma_magnet": "205", "spot": "201",
           "raw_jsonb": {"call_wall": "210.5"}}
    assert r.upsert_gex_levels([row]) == 1
    assert r.upsert_gex_levels([{**row, "call_wall": "211"}]) == 1  # upsert, no dup
    with db_conn.cursor() as cur:
        cur.execute("SELECT call_wall FROM uw_scan.uw_gex_levels_daily WHERE ticker='AAPL'")
        assert cur.fetchone()[0] is not None

def test_insert_dark_lit_prints_ignores_dupe(db_conn):
    r = UwHistoricalAlphaRepository(db_conn, schema="uw_scan")
    p = {"source": "darkpool", "tracking_id": "T1", "ticker": "AAPL",
         "executed_at": datetime(2026, 6, 30, 14, tzinfo=timezone.utc),
         "market_date": date(2026, 6, 30), "price": "201", "size": 100, "raw_jsonb": {}}
    assert r.insert_dark_lit_prints([p]) == 1
    assert r.insert_dark_lit_prints([p]) == 1  # returns len(rows); ON CONFLICT DO NOTHING
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.uw_dark_lit_flow_prints")
        assert cur.fetchone()[0] == 1  # only one physical row
```

- [ ] **Step 2: Run to verify it fails** — FAIL (module undefined).

- [ ] **Step 3: Write the repository** (`src/uw_scan/storage/uw_historical_alpha_repository.py`) modeled on `GreekExposureDailyRepository` (standalone, `SET search_path` in `__init__`, `Jsonb` for raw). Full `upsert_gex_levels` shown; the other two upserts mirror it with their columns; the two inserts use `ON CONFLICT DO NOTHING` (no commit inside — caller commits, matching `_FlowMixin.insert_flow_events`):

```python
"""Persistence for the UW historical-alpha datasets. New domain — own file."""

from __future__ import annotations

from collections.abc import Iterable

from psycopg import Connection
from psycopg.types.json import Jsonb


class UwHistoricalAlphaRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_gex_levels(self, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        params = [
            {"ticker": r["ticker"].upper(), "market_date": r["market_date"],
             "call_wall": r.get("call_wall"), "put_wall": r.get("put_wall"),
             "gamma_flip": r.get("gamma_flip"), "gamma_magnet": r.get("gamma_magnet"),
             "spot": r.get("spot"), "raw_jsonb": Jsonb(r.get("raw_jsonb") or {})}
            for r in rows
        ]
        sql = """
            INSERT INTO uw_gex_levels_daily
                (ticker, market_date, call_wall, put_wall, gamma_flip, gamma_magnet, spot, raw_jsonb)
            VALUES (%(ticker)s, %(market_date)s, %(call_wall)s, %(put_wall)s,
                    %(gamma_flip)s, %(gamma_magnet)s, %(spot)s, %(raw_jsonb)s)
            ON CONFLICT (ticker, market_date) DO UPDATE SET
                call_wall=EXCLUDED.call_wall, put_wall=EXCLUDED.put_wall,
                gamma_flip=EXCLUDED.gamma_flip, gamma_magnet=EXCLUDED.gamma_magnet,
                spot=EXCLUDED.spot, raw_jsonb=EXCLUDED.raw_jsonb, fetched_at=now()
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def insert_dark_lit_prints(self, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = """
            INSERT INTO uw_dark_lit_flow_prints
                (source, tracking_id, ticker, executed_at, market_date, price, size,
                 premium, market_center, nbbo_bid, nbbo_ask, nbbo_bid_quantity,
                 nbbo_ask_quantity, sale_cond_codes, trade_code, raw_jsonb)
            VALUES (%(source)s, %(tracking_id)s, %(ticker)s, %(executed_at)s, %(market_date)s,
                    %(price)s, %(size)s, %(premium)s, %(market_center)s, %(nbbo_bid)s,
                    %(nbbo_ask)s, %(nbbo_bid_quantity)s, %(nbbo_ask_quantity)s,
                    %(sale_cond_codes)s, %(trade_code)s, %(raw_jsonb)s)
            ON CONFLICT (source, tracking_id) DO NOTHING
        """
        # psycopg adapts a Python list -> TEXT[] natively (sale_cond_codes).
        cols = ("source", "ticker", "executed_at", "market_date", "price", "size",
                "premium", "market_center", "nbbo_bid", "nbbo_ask", "nbbo_bid_quantity",
                "nbbo_ask_quantity", "sale_cond_codes", "trade_code")
        params = [{"tracking_id": p["tracking_id"],
                   **{k: p.get(k) for k in cols},
                   "ticker": p["ticker"].upper(),
                   "raw_jsonb": Jsonb(p.get("raw_jsonb") or {})}
                  for p in rows]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)
```

(`upsert_volatility_signal`, `upsert_short_pressure`, `insert_intraday_flow_bars` follow the same two shapes with their table's columns from migration 108. `insert_intraday_flow_bars` keys `ON CONFLICT (ticker, market_date, ts, source, expiry) DO NOTHING`.)

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/integration/storage/test_uw_historical_alpha_repository.py -v` → PASS.

- [ ] **Step 5: Commit** — `git commit -am "feat(uw-alpha): standalone storage repo (3 upserts, 2 insert-ignore)"`

---

## Phase 3 — Recurring capture jobs + scheduler + config

**Deliverable:** five nightly capture jobs writing REAL rows to `option_wizard_local`, verified through the real worker path (enable flag → restart worker → job runs → rows land). NOT a `/tmp` side script.

### Task 3.1: Config flag

**Files:**
- Modify: `src/uw_scan/config.py` (Settings field + `from_env`)
- Test: `tests/unit/test_config.py`

**Interfaces produced:** `settings.uw_alpha_capture_enabled: bool` (env `UW_SCAN_UW_ALPHA_CAPTURE_ENABLED`, default `False`).

- [ ] **Step 1: Write the failing test**

```python
import os
from uw_scan.config import Settings

def test_uw_alpha_capture_flag_default_off(monkeypatch):
    monkeypatch.delenv("UW_SCAN_UW_ALPHA_CAPTURE_ENABLED", raising=False)
    monkeypatch.setenv("UW_SCAN_API_KEY", "x")
    assert Settings.from_env().uw_alpha_capture_enabled is False
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Add the field** (`config.py`, near `chanlun_lifecycle_enabled`): `uw_alpha_capture_enabled: bool = False`. In `from_env`: `uw_alpha_capture_enabled=_env_bool("UW_SCAN_UW_ALPHA_CAPTURE_ENABLED", False),`.

- [ ] **Step 4: Run → PASS. Commit** — `git commit -am "feat(uw-alpha): UW_SCAN_UW_ALPHA_CAPTURE_ENABLED flag (default off)"`

### Task 3.2: Capture functions + shared per-ticker-date core

**Files:**
- Create: `src/uw_scan/worker/jobs/uw_alpha_capture.py`
- Test: `tests/integration/worker/test_uw_alpha_capture.py`

**Interfaces produced (consumed by scheduler AND heal adapters in Phase 4):**
- `capture_gex_levels_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int` — takes `run_id` because the fetchers require it for the audit + raw-payload row; the caller (nightly wrapper or heal adapter) creates the `run_id` via `insert_scan_run`.
- `capture_volatility_signal_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int` (makes 3 sub-fetches: anomaly + character + vrp)
- `capture_short_pressure_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int`
- `capture_intraday_flow_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int`
- `capture_dark_lit_for(client, repo, alpha_repo, run_id, ticker, market_date) -> int`
- Nightly wrappers: `gex_levels_capture(*, repo, client, settings, ticker_filter=None) -> dict[str,int]` (and one per table), each advisory-locked, iterating `repo.list_watchlist_cards()`, per-ticker `insert_scan_run(ticker, notes="<name>")`/commit/rollback, returning the outcome-counter dict.

- [ ] **Step 1: Write the failing integration test** (real DB; mock only the UW client's `.get` to return the frozen fixture):

```python
from datetime import date
from uw_scan.worker.jobs.uw_alpha_capture import capture_gex_levels_for
from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository
# fake_uw_client returns gex_levels_aapl.json from resp.json()

def test_capture_gex_levels_writes_real_row(db_conn, fake_uw_client, seeded_repo):
    alpha = UwHistoricalAlphaRepository(db_conn, schema="uw_scan")
    run_id = seeded_repo.insert_scan_run("AAPL", notes="uw_alpha_gex_capture")
    n = capture_gex_levels_for(fake_uw_client, seeded_repo, alpha, run_id, "AAPL", date(2026, 6, 30))
    assert n == 1
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.uw_gex_levels_daily WHERE ticker='AAPL' AND market_date='2026-06-30'")
        assert cur.fetchone()[0] == 1
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Write the capture core + nightly wrappers** (`uw_alpha_capture.py`). Per-table capture fn fetches → assembles the merged row → upserts/inserts. **`raw_jsonb` source (codex #7):** the public fetchers return normalized models, not the raw body — but `_fetch_json` already persists the TRUE raw endpoint envelope to `raw_payloads` (the audit trail). So the table's `raw_jsonb` column stores the assembled row's `model_dump(mode="json")` (a faithful normalized snapshot), NOT the endpoint body — the byte-exact raw lives in `raw_payloads`. `capture_volatility_signal_for` makes 3 sub-fetches (anomaly+character+vrp), extracts the row matching `market_date` (or `latest`), merges into one `(ticker, market_date)` upsert. `capture_short_pressure_for` combines the existing `fetch_short_interest_float` (dict) + `fetch_ftds` + `fetch_volumes_by_exchange`. The intraday/dark-lit captures set `source` and, for intraday bars, the migration-default `expiry='0001-01-01'` sentinel. Nightly wrapper shape (modeled verbatim on `greek_exposure_daily_refresh`, jobs/greek_exposure_daily_refresh.py:32–110):

```python
GEX_LEVELS_CAPTURE_LOCK = 10801  # migration 108 + slot 01

def gex_levels_capture(*, repo, client, settings, ticker_filter=None,
                       lock_key: int = GEX_LEVELS_CAPTURE_LOCK) -> dict[str, int]:
    if not repo.try_advisory_lock(lock_key):
        return {"tickers": 0, "rows": 0, "errors": 0}
    alpha = UwHistoricalAlphaRepository(repo.conn, schema=settings.db_schema)
    market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
    tickers_done = rows_written = errors = 0
    try:
        for card in repo.list_watchlist_cards():
            ticker = card.ticker.upper()
            if ticker_filter is not None and not ticker_filter(ticker):
                continue
            run_id = repo.insert_scan_run(ticker, notes="uw_alpha_gex_capture")
            try:
                n = capture_gex_levels_for(client, repo, alpha, run_id, ticker, market_date)
                repo.finish_scan_run(run_id, status="ok")
                repo.conn.commit()
                rows_written += n
                tickers_done += 1
            except Exception as exc:  # noqa: BLE001
                repo.conn.rollback()
                errors += 1
                logger.warning("uw_alpha_gex_capture %s failed: %s", ticker, repr(exc))
    finally:
        repo.release_advisory_lock(lock_key)
    return {"tickers": tickers_done, "rows": rows_written, "errors": errors}
```

The other four wrappers are identical with their capture fn, `notes=` tag, and lock key `10802`–`10805`.

- [ ] **Step 4: Run → PASS.** Commit — `git commit -am "feat(uw-alpha): recurring capture functions + nightly wrappers"`

### Task 3.3: Scheduler wiring

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`

- [ ] **Step 1: Add a uw-0 pin helper** (next to `_should_schedule_option_surface_capture`, scheduler.py:286–294):

```python
def _should_schedule_uw_alpha_capture(settings: Settings) -> bool:
    if not settings.uw_alpha_capture_enabled:
        return False
    role = settings.worker_role.lower()
    return role == "all" or (role == "uw" and settings.worker_index == 0)
```

- [ ] **Step 2: Add the five job closures** (inside the scheduler build fn, near `_greek_exposure_daily_refresh`), each using the `_external_api_recorder → _uw_client(job_name=…) → _repo` stack:

```python
    def _uw_alpha_gex_capture() -> None:
        from uw_scan.worker.jobs.uw_alpha_capture import gex_levels_capture
        with _external_api_recorder(settings) as rec:
            with _uw_client(settings, telemetry_recorder=rec, job_name="uw_alpha_gex_capture") as uw:
                with _repo(settings) as repo:
                    gex_levels_capture(repo=repo, client=uw, settings=settings)
```

(Four more: `_uw_alpha_volatility_capture`, `_uw_alpha_short_pressure_capture`, `_uw_alpha_intraday_flow_capture`, `_uw_alpha_dark_lit_capture` — same shape, their wrapper + `job_name`.)

- [ ] **Step 3: Register under `if "uw" in groups:` gated by the pin** (near the `_greek_exposure_daily_refresh` add_job, ~scheduler.py:1496). Times staggered after close, before the 20:00 healer + 21:00 freshness monitor:

```python
            if _should_schedule_uw_alpha_capture(settings):
                for job, hhmm, jid in [
                    (_uw_alpha_gex_capture, "35 18", "uw_alpha_gex_capture"),
                    (_uw_alpha_volatility_capture, "40 18", "uw_alpha_volatility_capture"),
                    (_uw_alpha_short_pressure_capture, "45 18", "uw_alpha_short_pressure_capture"),
                    (_uw_alpha_intraday_flow_capture, "50 18", "uw_alpha_intraday_flow_capture"),
                    (_uw_alpha_dark_lit_capture, "55 18", "uw_alpha_dark_lit_capture"),
                ]:
                    sched.add_job(
                        job, CronTrigger.from_crontab(f"{hhmm} * * 0-4", timezone=settings.rth_tz),
                        id=jid, name=f"UW alpha capture: {jid}", max_instances=1, coalesce=True,
                    )
```

- [ ] **Step 4: Add a thin one-shot runner** `scripts/backfill/uw_alpha_capture_once.py` — the exact analog of `scripts/backfill/greek_exposure_daily_refresh_backfill.py` (the verified thin "re-run the real job" pattern): `Settings.from_env()`, `--confirm` dry-run gate, `--dataset <one of the 5>` + optional `--tickers` comma list → `ticker_filter`, builds the `_external_api_recorder`/`UwClient(job_name=…)`/`Repository` stack and calls the SAME nightly wrapper fn the scheduler calls (`gex_levels_capture(...)` etc.). No reimplementation of capture logic. (This removes the forward dependency on the Phase-5 catch-up CLI and covers the "run one capture now" need.)

- [ ] **Step 5: SMOKE VERIFICATION — the real worker path on `option_wizard_local`.** Load-bearing for the phase:

```bash
export UW_SCAN_UW_ALPHA_CAPTURE_ENABLED=1
# run the real production job fn once — the identical wrapper APScheduler calls at 18:35 ET:
uv run python scripts/backfill/uw_alpha_capture_once.py --dataset uw_gex_levels_daily --tickers AAPL --confirm
# verify a REAL row landed:
PGPASSWORD=… psql -h 127.0.0.1 -U argon_app -d option_wizard_local -c \
  "SELECT ticker, market_date, call_wall FROM uw_scan.uw_gex_levels_daily WHERE ticker='AAPL' ORDER BY market_date DESC LIMIT 1;"
```

Expected: one fresh row for today with a non-null `call_wall`. This exercises the real job fn end-to-end. To additionally prove the *scheduler* wiring (not just the fn), restart the local stack (`bash scripts/dev.sh`) and confirm the 5 job ids appear in the APScheduler job list / startup logs — APScheduler does NOT hot-reload, so a stale worker won't show them.

- [ ] **Step 6: Commit** — `git commit -am "feat(uw-alpha): schedule 5 nightly capture jobs (uw-0, gated by flag) + one-shot runner"`

---

## Phase 4 — Healer registration + adapters + freshness monitor

**Deliverable:** the 3 daily tables self-heal a synthetically-deleted `(ticker, date)` gap through the real `execute_run` path; all 5 appear in the `/api/health` freshness block; the 3 CI gates pass.

### Task 4.1: Heal adapters

**Files:**
- Modify: `src/uw_scan/worker/jobs/data_gap_adapters.py` (3 adapters + 3 `HEAL_SPECS` entries)
- Test: `tests/integration/worker/test_uw_alpha_heal_adapters.py`

**Interfaces produced:** `HEAL_SPECS["gex_levels"]`, `["volatility_signal"]`, `["short_pressure"]`, each `HealSpec(adapter, "uw", "per_ticker_date", _run_…, est_per_item=N)`.

- [ ] **Step 1: Write the adapters** (contract confirmed from `_run_greek_exposure`, data_gap_adapters.py:148–162 — signature `(ctx, ticker, market_date) -> int`; DB via `ctx.repo`, client via `ctx.uw_client()`, do NOT touch `ctx.budget`):

```python
def _run_gex_levels(ctx: HealContext, ticker: str, market_date: date) -> int:
    from uw_scan.worker.jobs.uw_alpha_capture import capture_gex_levels_for
    from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository
    alpha = UwHistoricalAlphaRepository(ctx.repo.conn, schema=ctx.schema)
    run_id = ctx.repo.insert_scan_run(ticker, notes="data_gap_healer:gex_levels")
    n = capture_gex_levels_for(ctx.uw_client(), ctx.repo, alpha, run_id, ticker, market_date)
    ctx.repo.finish_scan_run(run_id, status="ok")
    ctx.repo.conn.commit()
    return n
```

`_run_volatility_signal` (est 3 UW calls) and `_run_short_pressure` (est 3) mirror it with their capture fn.

- [ ] **Step 2: Register the specs** (append to `HEAL_SPECS`, data_gap_adapters.py:262):

```python
    "gex_levels": HealSpec("gex_levels", "uw", "per_ticker_date", _run_gex_levels, est_per_item=1),
    "volatility_signal": HealSpec("volatility_signal", "uw", "per_ticker_date", _run_volatility_signal, est_per_item=3),
    "short_pressure": HealSpec("short_pressure", "uw", "per_ticker_date", _run_short_pressure, est_per_item=3),
```

- [ ] **Step 3: Write the failing heal integration test** (the load-bearing verification — real `execute_run`, synthetic gap):

```python
from datetime import date
from uw_scan.reports.data_gap_healer import REGISTRY
from uw_scan.worker.jobs.data_gap_adapters import HealContext, RequestBudget, execute_run
# helpers: seed a watchlist + a market_tide_sentiment_daily calendar row for 2026-06-30,
# insert a real gex row, then DELETE it to create the gap.

def test_gex_levels_heal_closes_a_deleted_gap(db_conn, seeded_repo, gap_repo, fake_uw_client):
    # arrange: one calendar session, one watchlist ticker, no gex row for it
    run_id, _, items = audit_into_run(seeded_repo, gap_repo, "uw_scan",
        start=date(2026,6,30), end=date(2026,6,30),
        datasets=["uw_gex_levels_daily"], mode="execute")
    assert any(i["ticker"] == "AAPL" for i in items)  # the gap was detected
    ctx = HealContext(repo=seeded_repo, gap=gap_repo, schema="uw_scan",
        today=date(2026,6,30), budget=RequestBudget(100), settings=..., _uw=fake_uw_client)
    outcome = execute_run(ctx, run_id, datasets=["uw_gex_levels_daily"])
    assert outcome.get("healed", 0) >= 1
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.uw_gex_levels_daily WHERE ticker='AAPL' AND market_date='2026-06-30'")
        assert cur.fetchone()[0] == 1  # the gap is closed
```

- [ ] **Step 4: Run → PASS** (`uv run pytest tests/integration/worker/test_uw_alpha_heal_adapters.py -v`). This proves the heal path end-to-end: audit detects the gap → `execute_run` dispatches `_run_gex_levels` → `_verify_covered` re-queries and marks `healed`.

- [ ] **Step 5: Commit** — `git commit -am "feat(uw-alpha): heal adapters + HealSpecs for the 3 daily tables"`

### Task 4.2: Registry entries + event-log freshness

**Files:**
- Modify: `src/uw_scan/reports/data_gap_healer.py`
- Test: `tests/unit/reports/test_data_gap_healer_specs.py` (existing gates) + a new assertion

- [ ] **Step 1: Add the 3 strict entries** to `REGISTRY` (template = the `greek_exposure_daily` entry, data_gap_healer.py:159–170). `gex_levels` serves deep history → `retention_days=None`; the two volatility/short tables cap to the source window:

```python
    DatasetRegistryEntry("uw_gex_levels_daily", "options_chain", "strict_ticker_date",
        ticker_col="ticker", provider="uw", granularity="per_ticker_date",
        healer_adapter="gex_levels", source_system="uw", retention_days=None),
    DatasetRegistryEntry("uw_volatility_signal_daily", "options_chain", "strict_ticker_date",
        ticker_col="ticker", provider="uw", granularity="per_ticker_date",
        healer_adapter="volatility_signal", source_system="uw", retention_days=None,
        reason="VRP serves full YTD; anomaly/character ~16 recent sessions -> old dates fill VRP only"),
    DatasetRegistryEntry("uw_short_pressure_daily", "options_chain", "strict_ticker_date",
        ticker_col="ticker", provider="uw", granularity="per_ticker_date",
        healer_adapter="short_pressure", source_system="uw", retention_days=None,
        reason="interest-float is current-snapshot; ftds/volumes carry history"),
```

**`retention_days` is descriptive-only — the scanner never reads it** (verified during review; see spec §4a). Set `retention_days=None` for all three; do NOT rely on it to bound the denominator. There is no phantom-gap storm because: the scanner keys on **row existence**, not column-nullness (a VRP-only row counts as covered); the audit window is bounded by `data_gap_healer_start`; coverage is dense post-catch-up; and heal spend is capped by `DATA_GAP_HEALER_MAX_UW_CALLS`. A genuinely-missing, permanently-unhealable old `(ticker, date)` is re-attempted each nightly run (existing behavior, also true for `greek_exposure_daily`) — if it ever proves noisy, add a `Caveat`, not a `retention_days`.

- [ ] **Step 2: Add the 2 event-log tables** to the `freshness_only` `_entries([...], "options_chain", ...)` block (data_gap_healer.py:474–507) — add `"uw_dark_lit_flow_prints"` and `"uw_intraday_option_flow_bars"` to the list literal. They inherit `audit_mode="freshness_only"`, no adapter.

- [ ] **Step 3: Run the spec gates** — `uv run pytest tests/unit/reports/test_data_gap_healer_specs.py -v`. Expected PASS: `test_every_healable_entry_has_a_wired_spec` (the 3 adapters exist in `HEAL_SPECS`), `test_healable_entries_name_an_adapter_others_do_not_dispatch`, `test_registry_table_names_are_unique`.

- [ ] **Step 4: Commit** — `git commit -am "feat(uw-alpha): register 5 tables in data_gap_healer (3 strict, 2 freshness)"`

### Task 4.3: Freshness monitoring + policy doc

**Files:**
- Modify: `src/uw_scan/reports/data_freshness.py` (`MONITORED_TABLES`)
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerated)
- Test: `tests/unit/reports/test_data_gap_dataset_policy.py`, `tests/integration/worker/test_data_gap_full_coverage.py`

**CRITICAL:** registering in the healer REGISTRY does NOT enroll a table in the freshness alert — `MONITORED_TABLES` is a separate list (confirmed: `data_freshness_monitor` passes `MONITORED_TABLES`, not the REGISTRY, into `compute_freshness`).

- [ ] **Step 1: Add 5 `MonitoredTable` rows** (`data_freshness.py`, `MONITORED_TABLES`):

```python
    MonitoredTable("uw_gex_levels_daily", "watchlist", None),
    MonitoredTable("uw_volatility_signal_daily", "watchlist", None),
    MonitoredTable("uw_short_pressure_daily", "watchlist", None),
    MonitoredTable("uw_dark_lit_flow_prints", "watchlist", None),
    MonitoredTable("uw_intraday_option_flow_bars", "watchlist", None),
```

- [ ] **Step 2: Regenerate the policy doc** (byte-match gate):

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
```

- [ ] **Step 3: Add the freshness-enrollment test (codex #9).** The three existing gates only check the healer `REGISTRY` — none asserts `MONITORED_TABLES` membership, so a table registered in the healer but forgotten in `MONITORED_TABLES` would pass CI while its freshness alert never fires. Add `tests/unit/reports/test_uw_alpha_freshness_enrolled.py`:

```python
from uw_scan.reports.data_freshness import MONITORED_TABLES

def test_uw_alpha_tables_are_freshness_monitored():
    names = {m.name for m in MONITORED_TABLES}
    for t in ("uw_gex_levels_daily", "uw_volatility_signal_daily", "uw_short_pressure_daily",
              "uw_dark_lit_flow_prints", "uw_intraday_option_flow_bars"):
        assert t in names, f"{t} missing from MONITORED_TABLES (freshness alert won't fire)"
```

- [ ] **Step 4: Run the enrollment test + the three existing CI gates**

```bash
uv run pytest tests/unit/reports/test_uw_alpha_freshness_enrolled.py \
  tests/unit/reports/test_data_gap_dataset_policy.py \
  tests/integration/worker/test_data_gap_full_coverage.py -v
```

Expected PASS: the enrollment test; `test_zero_unregistered_after_full_registry` (all 5 new temporal tables now have registry entries → `unreg == []`); `test_committed_policy_doc_is_in_sync_with_registry` (doc regenerated); `test_policy_render_covers_every_registry_row`.

- [ ] **Step 5: FRESHNESS SMOKE.** `/api/health` reads the LAST PERSISTED `data_freshness_snapshots` — it does NOT recompute live (codex #10; `health.py:382`). So run the real monitor job first, then read the block, filtering on the actual field key `table_name` (NOT `table`):

```bash
# run the real freshness-monitor job path so a fresh snapshot lands:
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor
from datetime import datetime
from zoneinfo import ZoneInfo
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    repo = Repository(c, schema=s.db_schema)
    data_freshness_monitor(repo=repo, settings=s, today=datetime.now(ZoneInfo(s.rth_tz)).date())
"
curl -s localhost:8400/api/health | python -c "import sys,json; f=json.load(sys.stdin)['freshness']; print([r for r in f['tables'] if r['table_name'].startswith('uw_')])"
```

Expected: 5 rows present (FROZEN until Phase 5 catch-up fills them — correct, abandoned since 2026-07-01).

- [ ] **Step 6: Commit** — `git commit -am "feat(uw-alpha): freshness-monitor the 5 tables + enrollment test + regenerate policy doc"`

---

## Phase 5 — Catch-up (2026-07-02 → go-live)

**Deliverable:** the 2026-07-02→today gap closed and verified; the coverage trace persisted with a reproduce command. The three strict tables catch up VIA THE HEALER (its audit→heal→verify IS the backfill); the two event-log tables via a thin date-loop on the same capture fns.

### Task 5.1: Catch-up CLI for the event-log tables (backfill-eventlog + coverage)

**Files:**
- Create: `scripts/backfill/uw_alpha_catchup.py`
- Test: `tests/unit/test_uw_alpha_catchup.py` (argparse surface + dry-run gate)

**Interfaces produced:** subcommands `backfill-eventlog` (loop `capture_intraday_flow_for`/`capture_dark_lit_for` over a date range, `--max-uw-calls` capped, resumable by skipping `(ticker, date)` already present) and `coverage` (read-only per-dataset expected/covered/missing trace). ("Run one capture now" is already covered by `scripts/backfill/uw_alpha_capture_once.py` from Phase 3 — do not duplicate it here.)

- [ ] **Step 1: Write the failing test** — assert `backfill-eventlog`/`coverage` parse and that `backfill-eventlog` without `--confirm` is a dry-run returning 0 (mirrors `data_gap_healer.py cmd_execute`).

- [ ] **Step 2: Write the CLI** — `Settings.from_env()`, `--confirm` gate, `--max-uw-calls` (default `20000`, matching `DATA_GAP_HEALER_MAX_UW_CALLS`), reads UW budget headers automatically via the recorder (do NOT parse headers — the recorder + `read_snapshot` handle it). `backfill-eventlog` iterates the `market_tide_sentiment_daily` session spine 2026-07-02→end, skipping `(ticker, date)` already present, calling the capture fn per ticker/date, stopping at the cap. **`coverage` writes a committed Markdown trace** under `docs/research/uw-historical-alpha-scan/` (consumed by Task 5.2) — NOT a DB row; there is no migration for it (codex #12). This matches the standing rule for exploratory research traces (durable committed artifact, exact reproduce command).

- [ ] **Step 3: Run → PASS. Commit** — `git commit -am "feat(uw-alpha): resumable catch-up CLI (event-log backfill + coverage)"`

### Task 5.2: Run the catch-up on the mini

**Files:** none (operational) + `docs/research/uw-historical-alpha-scan/catchup-YYYY-MM-DD.md` (persisted trace).

- [ ] **Step 1: Strict tables — heal the gap** (audit → heal → verify, all built-in). Point at the mini (`UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1`), datasets = the 3 strict tables, window 2026-07-02→today:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python scripts/backfill/data_gap_healer.py execute \
  --datasets uw_gex_levels_daily,uw_volatility_signal_daily,uw_short_pressure_daily \
  --start 2026-07-02 --end $(date +%F) --max-uw-calls 40000 --confirm
```

- [ ] **Step 2: Event-log tables — date-loop backfill**

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python scripts/backfill/uw_alpha_catchup.py backfill-eventlog \
  --datasets uw_intraday_option_flow_bars,uw_dark_lit_flow_prints \
  --start 2026-07-02 --end $(date +%F) --max-uw-calls 40000 --confirm
```

(May need multiple runs / a second day's budget — the event-log tables are the heavy ones. Resume by re-running; present dates are skipped.)

- [ ] **Step 3: VERIFY coverage before/after** — run `data_gap_healer.py verify-all` (read-only) for the 3 strict tables and a `coverage` read for the 2 event-log tables; confirm the 2026-07-02→today window is now covered (0 open gaps for the strict tables; event-log tables have rows on every session).

- [ ] **Step 4: PERSIST the trace** — write `docs/research/uw-historical-alpha-scan/catchup-<today>.md` with the per-dataset expected/covered/missing counts, the UW spend, and the exact reproduce commands (Steps 1–2). Commit — `git commit -am "docs(uw-alpha): persist catch-up coverage trace + reproduce commands"`.

- [ ] **Step 5: RE-CHECK freshness** — `curl localhost:8400/api/health` (or the mini's) → the 5 `uw_*` tables now report FRESH (max_date = today), not FROZEN.

---

## Phase 6 — CHANGELOG + PR

**Deliverable:** the feature merged behind a green CI PR.

### Task 6.1: CHANGELOG + full suite

- [ ] **Step 1: Add the `[Unreleased]` entry** to `CHANGELOG.md`:

```markdown
### Added
- UW historical-alpha datasets (`uw_gex_levels_daily`, `uw_volatility_signal_daily`,
  `uw_short_pressure_daily`, `uw_intraday_option_flow_bars`, `uw_dark_lit_flow_prints`):
  recurring nightly capture (gated by `UW_SCAN_UW_ALPHA_CAPTURE_ENABLED`, default off),
  `data_gap_healer` self-healing for the 3 daily tables + freshness monitoring for all 5,
  and a resumable catch-up CLI. Migration 108.
```

- [ ] **Step 2: Run the FULL local gate** (reproduce the CI `lint + unit` job, not just ruff+pytest):

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
python scripts/check_no_yahoo.py
```

Expected: all green. Fix anything red before proceeding.

- [ ] **Step 3: Commit** — `git commit -am "docs(uw-alpha): CHANGELOG [Unreleased] entry"`

### Task 6.2: PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin misc/uw-historical-alpha-scan
```

- [ ] **Step 2: Open the PR** — `gh pr create` with a body summarizing: 5 tables wired into capture+heal, the endpoint-reality verification (spec §12), the dropped oi_change/long-weekend riders, migration 108, catch-up done on the mini. NO `Co-Authored-By` trailer.

- [ ] **Step 3: Wait for CI green, then merge.** Never merge before all checks pass. Remove the worktree when done: `git worktree remove .worktrees/uw-historical-alpha-scan`.

### Task 6.3: Post-deploy production rollout (codex #13)

**Deliverable:** the recurring writers actually turned ON in prod. Without this, `UW_SCAN_UW_ALPHA_CAPTURE_ENABLED` defaults `False` and the five capture jobs never run — the PR would ship with all writers permanently disabled. The recurring jobs live inside the mini's worker (deployed image), so this happens AFTER the merge + Watchtower deploy, not before.

- [ ] **Step 1:** After the PR merges and the new `argon-app` image auto-deploys to the mini, set `UW_SCAN_UW_ALPHA_CAPTURE_ENABLED=1` in the mini's `/opt/argon/.env` (persists across deploys).
- [ ] **Step 2:** Restart / kickstart the `uw-0` worker so it re-reads the flag (worker env freezes at fork — no hot-reload).
- [ ] **Step 3:** Confirm the 5 job ids (`uw_alpha_gex_capture` … `uw_alpha_dark_lit_capture`) appear in the scheduler startup logs.
- [ ] **Step 4:** Next ET evening, verify a fresh row landed in each of the 5 tables (max `market_date` = today) and that `data_freshness_monitor` flips them FRESH. Record the verification (the "capture is live" evidence for goal-ladder Stage 1).

---

## Self-Review Notes

- **Spec coverage:** §1 goal → all phases; §2 branch audit → Phase 0; §3 shapes → migration 108 (Phase 0/1); §4 healer mapping → Phase 4; §5 plumbing → Phases 1–3; §6 config → Task 3.1; §7 catch-up → Phase 5; §8 rebase mechanics → Phase 0; §9 testing → woven per task; §10 deliverables → phase commits + Phase 6; §12/§13 endpoint reality → Task 1.1–1.2 (fixtures + slugs). No spec section is unimplemented.
- **Verification is first-class** (per user emphasis): unit tests on real frozen fixtures (1.1, 1.3, 1.4), integration writes (2.2, 3.2), real-worker smoke (3.3 Step 4), synthetic-gap heal proof (4.1 Step 3–4), freshness-block smoke (4.3 Step 4), before/after coverage trace (5.2 Step 3–4). No `/tmp` side scripts — captures run through the real job fns.
- **Open probes** (resolve at implementation, flagged inline): `retention_days` for volatility/short (Task 4.2 Step 1); `volumes-by-exchange` `?date=` support (spec §13); exact fixture key names (Task 1.1 Step 2 drives 1.3/1.4).
