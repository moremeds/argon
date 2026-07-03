# UW Long Weekend History Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Backfill all accessible high-value Unusual Whales historical data through the current entitlement window while preserving resumability, coverage evidence, and normal Argon persistence semantics.

**Architecture:** Add date-aware ingestion where the current code only fetches latest snapshots, then run resumable operator backfills on the macmini against existing production tables. Use current Argon tables wherever possible; add only narrow compatibility changes for historical OI-change upserts and reusable coverage reporting.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, existing Argon `UwClient`/repository patterns, macmini Postgres `option_wizard`, UW REST API.

---

## Current State

- Active YTD alpha run on macmini is still running:
  - PID file: `/tmp/uw_historical_alpha_full_backfill.pid`
  - Log: `/tmp/uw_historical_alpha_full_backfill.log`
  - Output: `/tmp/uw-historical-alpha-full`
- Live probe evidence:
  - UW token limit is `120000` calls/day.
  - Many historical-selector endpoints reject pre-`2023-08-03` with `historic_data_access_missing`; this is the current 730-trading-day entitlement floor.
  - `/api/stock/{ticker}/oi-change?date=YYYY-MM-DD` works for historical dates; AAPL returned usable data around `2025-07-03`.
- DB state:
  - `oi_change_events`: `1,334,450` rows, `curr_date=2026-05-11..2026-07-02`.
  - `oi_by_strike`: `540,994` rows, `market_date=2026-05-11..2026-07-02`.
  - `oi_by_expiry`: exists but empty.
  - `market_tide_snapshots`, `top_net_impact_snapshots`, `uw_gex_levels_daily`, `uw_intraday_option_flow_bars`, `uw_dark_lit_flow_prints` already exist.

## Target Backfill Order

1. Finish active YTD full run.
2. Backfill market-wide and dealer-wall data from `2023-08-03` to `2025-12-31`:
   - `market_tide_snapshots`
   - `top_net_impact_snapshots`
   - `uw_gex_levels_daily`
3. Backfill OI build history:
   - `oi_change_events` from approximately `2025-07-03` to `2026-05-10`
   - `oi_by_strike` from approximately `2025-01-02` to `2026-05-10`
4. Backfill older flow bars:
   - `uw_intraday_option_flow_bars` from `2023-08-03` or effective endpoint start to `2025-12-31`
5. Backfill older dark/lit tape:
   - `uw_dark_lit_flow_prints` from `2023-08-03` to `2025-12-31`

## Request Budget Estimate

Assumptions:
- Watchlist: 103 active tickers.
- Trading sessions from `2023-08-03` to `2025-12-31`: roughly 600-610 sessions.
- YTD active run consumes its own calls first; recheck live headers before launching each phase.

Estimated calls:
- Market tide + top net impact, 2023-08-03..2025-12-31: about `1.2k`.
- GEX levels, 103 tickers x ~605 sessions: about `62k`.
- OI change, 103 tickers x ~125 sessions from 2025-07-03..2026-05-10 if AAPL-like coverage starts mid-2025: about `13k`.
- OI per strike, 103 tickers x ~340 sessions from 2025-01-02..2026-05-10: about `35k`.
- Net premium + greek flow bars, 103 tickers x ~605 sessions x 2: about `125k`.
- Darkpool + lit flow, 103 tickers x ~605 sessions x 2: about `125k`.

Daily allocation:
- Day 1 after YTD run: market tide + top net impact + GEX + OI change + part of OI per strike.
- Day 2: finish OI per strike and run net premium / greek flow.
- Day 3: darkpool / lit flow.
- Extra budget: retry no-data cells, historical coverage verification, or short-pressure/volatility gap repair.

## Task 1: Add Date-Aware OI Fetcher

**Files:**
- Modify: `src/uw_scan/sources/uw.py`
- Test: `tests/sources/test_uw_date_params.py`

**Step 1: Write the failing test**

Add a unit test that monkeypatches `_fetch_json` and verifies `fetch_oi_change(..., market_date=date(2025, 7, 3))` passes `params={"date": "2025-07-03"}`.

**Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/sources/test_uw_date_params.py -q
```

Expected: fail because `fetch_oi_change` does not accept `market_date`.

**Step 3: Implement minimal code**

Change:

```python
def fetch_oi_change(client: UwClient, repo: Repository, run_id: int, ticker: str) -> list[models.OiChangeRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.OI_CHANGE, ticker)
    return normalize.normalize_oi_change(body)
```

To:

```python
def fetch_oi_change(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[models.OiChangeRow]:
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.OI_CHANGE, ticker, params=params)
    return normalize.normalize_oi_change(body)
```

**Step 4: Run focused tests**

```bash
uv run pytest tests/sources/test_uw_date_params.py -q
```

Expected: pass.

## Task 2: Add Historical OI Change Replace Path

**Files:**
- Modify: `src/uw_scan/storage/options.py`
- Add migration: `src/uw_scan/storage/migrations/096_oi_change_historical_key.sql`
- Test: `tests/storage/test_oi_change_historical_upsert.py`

**Reason:** `oi_change_events` currently conflicts on `(run_id, option_symbol)`, which is correct for scan-run audit rows. A live production audit found many existing duplicate `(underlying_symbol, curr_date, option_symbol)` rows across scan runs, so a unique historical key is not safe. Historical backfill instead replaces only the target `(underlying_symbol, curr_date)` slice before inserting one clean backfill run.

**Step 1: Add non-unique lookup migration**

```sql
SET search_path TO uw_scan, public;

CREATE INDEX IF NOT EXISTS ix_oi_change_events_underlying_curr_date
    ON oi_change_events (underlying_symbol, curr_date DESC);
```

**Step 2: Add repository method**

Add `replace_oi_change_rows_for_date(run_id, rows)` that:

1. Groups incoming rows by `(underlying_symbol, curr_date)`.
2. Deletes existing rows for those exact ticker/date slices.
3. Inserts the same columns as `insert_oi_change_rows` using the existing run-keyed conflict target:

```sql
DELETE FROM oi_change_events
 WHERE underlying_symbol = %s AND curr_date = %s;

INSERT INTO oi_change_events (...)
VALUES (...)
ON CONFLICT (run_id, option_symbol) DO NOTHING;
```

**Step 3: Test replace behavior**

Run:

```bash
uv run pytest tests/storage/test_oi_change_historical_upsert.py -q
```

Expected: second upsert for the same `(underlying, curr_date, option_symbol)` updates one row rather than inserting a duplicate.
Expected: method deletes the target ticker/date slice before inserting, and uses the existing `(run_id, option_symbol)` conflict target.

## Task 3: Add Historical Weekend Backfill CLI

**Files:**
- Create: `scripts/backfill/uw_long_weekend_history_backfill.py`
- Reuse:
  - `src/uw_scan/worker/market_session.py:is_market_day`
  - `src/uw_scan/sources/uw.py`
  - `src/uw_scan/storage/*repository.py`
  - direct upserts from `scripts/backfill/uw_historical_alpha_backfill.py` for the five new alpha tables

**CLI commands:**

```bash
uv run python scripts/backfill/uw_long_weekend_history_backfill.py plan \
  --datasets market_tide,top_net_impact,gex_levels,oi_change,oi_by_strike,flow_bars,dark_lit \
  --start 2023-08-03 --end 2025-12-31

uv run python scripts/backfill/uw_long_weekend_history_backfill.py execute \
  --datasets market_tide,top_net_impact,gex_levels \
  --start 2023-08-03 --end 2025-12-31 \
  --max-uw-calls 118000 --confirm \
  --output-dir /tmp/uw-long-weekend-history/day1

uv run python scripts/backfill/uw_long_weekend_history_backfill.py verify \
  --datasets market_tide,top_net_impact,gex_levels,oi_change,oi_by_strike,flow_bars,dark_lit \
  --start 2023-08-03 --end 2025-12-31
```

**Implementation requirements:**
- Generate sessions with `is_market_day(day)`.
- Do not call UW for cells already covered unless `--force` is passed.
- Commit per ticker-date or per market-wide date.
- Record:
  - `request-plan.json`
  - `execute-report.json`
  - `coverage-report.json`
- Read and enforce UW headers:
  - `x-uw-daily-req-count`
  - `x-uw-token-req-limit`
- Stop cleanly before `daily_count >= max_uw_calls`.

## Task 4: Backfill Phase A - Market-Wide + GEX

**Files:**
- Use: `scripts/backfill/uw_long_weekend_history_backfill.py`

**Macmini command:**

```bash
ssh moremeds@100.66.147.98 '
  cd ~/projects/argon &&
  set -a; source .env; set +a;
  PYTHONPATH=src .venv/bin/python /tmp/uw_long_weekend_history_backfill.py execute \
    --datasets market_tide,top_net_impact,gex_levels \
    --start 2023-08-03 --end 2025-12-31 \
    --max-uw-calls 118000 --confirm \
    --output-dir /tmp/uw-long-weekend-history/phase-a
'
```

**Verification SQL:**

```sql
SELECT min(data_date), max(data_date), count(DISTINCT data_date)
FROM uw_scan.market_tide_snapshots;

SELECT min(data_date), max(data_date), count(DISTINCT data_date)
FROM uw_scan.top_net_impact_snapshots;

SELECT min(market_date), max(market_date), count(DISTINCT (ticker, market_date))
FROM uw_scan.uw_gex_levels_daily;
```

Expected:
- `market_tide_snapshots` and `top_net_impact_snapshots` reach `2023-08-03` where UW has data.
- `uw_gex_levels_daily` reaches `2023-08-03` for active tickers where UW returns rows.

## Task 5: Backfill Phase B - OI Change + OI Per Strike

**Files:**
- Use: `scripts/backfill/uw_long_weekend_history_backfill.py`

**Macmini command:**

```bash
ssh moremeds@100.66.147.98 '
  cd ~/projects/argon &&
  set -a; source .env; set +a;
  PYTHONPATH=src .venv/bin/python /tmp/uw_long_weekend_history_backfill.py execute \
    --datasets oi_change,oi_by_strike \
    --start 2025-01-02 --end 2026-05-10 \
    --max-uw-calls 118000 --confirm \
    --output-dir /tmp/uw-long-weekend-history/phase-b
'
```

**Verification SQL:**

```sql
SELECT min(curr_date), max(curr_date), count(DISTINCT (underlying_symbol, curr_date)), count(*)
FROM uw_scan.oi_change_events;

SELECT min(market_date), max(market_date), count(DISTINCT (ticker, market_date)), count(*)
FROM uw_scan.oi_by_strike;
```

Expected:
- `oi_by_strike` reaches approximately `2025-01-02`.
- `oi_change_events` reaches approximately `2025-07-03` if current UW behavior matches probe.
- Dates before endpoint population should be logged as no-data, not failures.

## Task 6: Backfill Phase C - Net Premium + Greek Flow Bars

**Files:**
- Use: `scripts/backfill/uw_long_weekend_history_backfill.py`

**Macmini command:**

```bash
ssh moremeds@100.66.147.98 '
  cd ~/projects/argon &&
  set -a; source .env; set +a;
  PYTHONPATH=src .venv/bin/python /tmp/uw_long_weekend_history_backfill.py execute \
    --datasets flow_bars \
    --start 2023-08-03 --end 2025-12-31 \
    --max-uw-calls 118000 --confirm \
    --output-dir /tmp/uw-long-weekend-history/phase-c
'
```

Expected:
- One day of quota may not finish the full range.
- Resume with the same command next day; skip-existing must avoid re-calling covered ticker-date cells.

## Task 7: Backfill Phase D - Dark/Lit

**Files:**
- Use: `scripts/backfill/uw_long_weekend_history_backfill.py`

**Macmini command:**

```bash
ssh moremeds@100.66.147.98 '
  cd ~/projects/argon &&
  set -a; source .env; set +a;
  PYTHONPATH=src .venv/bin/python /tmp/uw_long_weekend_history_backfill.py execute \
    --datasets dark_lit \
    --start 2023-08-03 --end 2025-12-31 \
    --max-uw-calls 118000 --confirm \
    --output-dir /tmp/uw-long-weekend-history/phase-d
'
```

Expected:
- One day of quota may not finish the full range.
- Coverage report must distinguish no-data cells from unattempted cells.

## Task 8: Final Verification Evidence

**Files:**
- Write: `docs/research/uw-historical-alpha-scan/long-weekend-backfill-results.md`

**Evidence to capture:**
- Exact command run for each phase.
- UW daily count before and after each phase.
- `execute-report.json` path for each phase.
- Coverage table for every dataset:
  - expected ticker-date or date cells
  - covered cells
  - rows
  - min date
  - max date
  - no-data count
  - error count
- DB SQL outputs for:
  - `market_tide_snapshots`
  - `top_net_impact_snapshots`
  - `uw_gex_levels_daily`
  - `oi_change_events`
  - `oi_by_strike`
  - `uw_intraday_option_flow_bars`
  - `uw_dark_lit_flow_prints`

**Final acceptance criteria:**
- No active backfill process is left running unless intentionally queued.
- Each phase has a saved report under `/tmp/uw-long-weekend-history/...`.
- Postgres coverage confirms row persistence.
- UW quota was not exceeded.
- Known endpoint retention gaps are documented as caveats rather than counted as silent failures.
