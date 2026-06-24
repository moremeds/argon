# Data-Quality Coverage & Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two confirmed warm-store coverage bugs (#180 intraday-buckets mega-cap gap, #179 single-name greek_exposure_daily freeze) and add a recurring data-date freshness monitor so the *next* silent freeze is caught the morning it starts, not five weeks later — all in one PR off `feat/data-quality-coverage`.

**Architecture:** Three independent workstreams that share one migration batch and one CHANGELOG entry. (A) A one-line scheduler fix removes a shard filter wrongly applied to a primary-only singleton job, plus per-outcome counters that make the job self-report coverage. (B) A pure DB→DB re-derive sums the already-captured per-strike exposures into the daily GEX/DEX table, with a validation step that proves the re-derived basis matches UW's stored aggregate before any history is trusted. (C) A nightly monitor records, per curated table, the newest **data date** and active-watchlist coverage into a snapshot table, flagging freezes — covering the exact gap that the existing `list_record_health` (write-timestamp coverage only) structurally cannot see.

**Tech Stack:** Python 3.13 via `uv`, FastAPI + Pydantic v2, psycopg 3, APScheduler 3, Postgres schema `uw_scan`, pytest + pytest-postgresql.

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`/`python`/`pip`. Verified on the test DB; integration tests need a forced-local DB env on MacBook (`UW_SCAN_DB_HOST=127.0.0.1`, test DB `option_wizard_test`).
- **Migrations are idempotent** — `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ON CONFLICT DO NOTHING`. Header every file with `SET search_path TO uw_scan, public;`. New file = next lexical number; **do not renumber existing files**. Re-running a migrated DB is a no-op.
- **New persistence domains get their own `storage/<domain>_repository.py`** — never appended to `repository.py`. Module size target <500 lines.
- **Never extend `repository.py`** with query methods; it stays a thin assembly/re-export shell.
- **Persist analytical/research output to Postgres** — the re-derive and the freshness audit both land in tables, never in-memory-only.
- **Data source priority** IB → UW → FMP → massive; **Yahoo banned**. Workstreams B and C make **zero** external calls (pure DB→DB). Workstream A's backfill is UW-bound and must be budget-gated.
- **No secrets** to Codex subprocesses; never print the UW API key or DB password.
- **ET timezone** for all crons via `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`; APScheduler weekdays are Monday=0 → `0-4` is Mon–Fri.
- **Every job opens its own conn** via `_repo(settings)` and closes it in `finally`. Idempotent: running twice in a minute produces the same DB state.
- **Branch:** `feat/data-quality-coverage` (worktree `.worktrees/data-quality-coverage`, off `main` at v0.3.4). **One PR.** Do not `git push origin main`. **Do not commit until the user asks** — the per-task `git commit` steps below are drafted for `/execute-plan`; honor the user's commit gate.
- **CHANGELOG `[Unreleased]` entry lands in this branch** before merge (feature-PR rule), not in a follow-up.

---

## Approved Design & Decisions (review-cycle checks the plan against this)

Three locked decisions from brainstorming (2026-06-24/25):

### Decision 1 — #179 `greek_exposure_daily`: re-derive DB→DB (zero UW)

**Root cause (confirmed):** `greek_exposure_daily` is **index-only by design**. Its only writer is `scanners/gex.py` (`GreekExposureDailyRepository.upsert_rows`) driven by `settings.gex_scan_tickers = ["SPX","SPY","TLT"]`. The ~100 single-name rows frozen at 2026-05-20 are the tail of a one-off historical population that was never repeated — there is no recurring single-name job and no committed backfill. PR #160 writes `option_surface_grid_daily`, **not** this table.

**Fix:** If single-name daily net GEX/DEX is wanted (it is — the stock page's GEX history chart consumes it), re-derive it purely from the fresh per-strike table `exposures_by_expiry_strike` (119 tickers, current). Sum `call_gex/put_gex/call_delta/put_delta` per `(ticker, market_date)` and upsert into `greek_exposure_daily` via the existing writer; `net_gex/net_dex` are `GENERATED ALWAYS AS (... ) STORED`, so they recompute automatically. **No UW calls.**

**Correctness guards (load-bearing):**
1. **Canonical run per date.** `exposures_by_expiry_strike` is keyed `(run_id, ticker, expiry, strike)`. A ticker can have **multiple `scan_runs` per `market_date`** (full_scan + rescans). A naive `SUM ... GROUP BY (ticker, market_date)` double-counts. The re-derive MUST first pick one canonical run per `(ticker, market_date)` — the latest run that is `status='ok' AND aggregates IS NOT NULL` (the same renderable-run semantics `latest_run_id` encodes), applied per historical date.
2. **Basis validation.** The stored SPX/SPY/TLT rows come from UW's **aggregate** `/greek-exposure` history endpoint, *not* from summing per-strike. The per-strike sum may be a **partial-chain proxy** (if the pipeline captured a strike subset) rather than the full-chain aggregate. So for SPX/SPY/TLT — fresh in *both* sources on overlapping dates — compare re-derived `net_gex` vs stored `net_gex` and **persist the diff** to `greek_rederive_validation`. **User's lean (accepted):** if the divergence is a clean scale/sign factor, apply the transform and proceed; otherwise persist the diff and surface it (WARN) — never silently ship a wrong-basis number. The validation row makes the basis auditable either way.

**Deliverables:** recurring nightly job (all active watchlist names) + one-shot historical backfill (all dates) + validation table & WARN.

### Decision 2 — #180 `option_intraday_buckets`: resilience + telemetry, fix in-branch

**Root cause (confirmed in code):** The intraday job `refresh_intraday_for_top_oi_movers` is registered **only on the primary worker** (`scheduler.py`, inside `if _is_primary_worker(settings)`), yet the wrapper `_intraday_oi_refresh` passes `ticker_filter=ticker_filter` where `ticker_filter = _ticker_shard_filter(settings)` = `crc32(ticker) % worker_count == worker_index`. With `worker_count=2`, the single primary worker (index 0) processes only shard-0 tickers (49); shard-1 tickers — **TSLA, NVDA, MSFT, GOOGL, META, AVGO** (~55 total) — are processed by **nobody**. Proof: all 49 covered tickers hash to shard 0; 59/61 absent hash to shard 1; the 2 shard-0 absentees (KORU/SOXL) were added 2026-06-24 with no history yet. The sibling sharded job at the same call site (`_flow_data_refresh`, line ~538) passing the same filter is **correct** because it runs on every uw worker with a per-worker lock (`91501 + worker_index`); the intraday job is the **sole** primary-only singleton that wrongly inherits the filter — so this is a one-line fix, not a bug class needing a shared helper.

**Fix:** `_intraday_oi_refresh` passes `ticker_filter=None`. The job already single-flights via `pg_try_advisory_lock(91502)`, so the one primary worker safely covers the full watchlist with no double-spend.

**Defense-in-depth:** enrich the job's summary dict with per-outcome counters (`skipped_no_run`, `skipped_no_movers`, `contracts_empty`, `contracts_error`) and log them, so a future coverage gap self-reports in the worker log instead of going silent for weeks.

**Backfill:** one-shot, budget-gated script that fetches intraday for the missed tickers' recent OI movers within UW's intraday retention window (~22 calendar days). Forward-only; run when UW budget allows.

**Operational note (UW footprint):** correcting the gap roughly **doubles this job's daily UW calls** — from ~49 tickers (shard 0) to the full ~104, each up to `top_n=10` contracts, in one 9 ET pass. UW's daily budget is tight (see memory `project_alpha_probe_uw_budget`). Mitigations already in place: `UwClient` throttles to `max_requests_per_minute` and retries 429 with backoff, so a transient quota brush self-throttles rather than crashing; a *sustained* daily-quota exhaustion degrades gracefully via the per-ticker `try/except` and surfaces in the new `contracts_error` counter. The one-shot backfill stays `--confirm`-gated so it never competes with the daily pass unattended. If 429s become routine at 9 ET, lower `top_n` rather than re-introducing a shard filter (which silently drops tickers — the very bug being fixed).

### Decision 3 — prevention: general data-date freshness monitor (all curated tables)

**Why the existing check misses freezes:** `storage/health.py` `list_record_health` discovers tables by a **write-timestamp** column (`_RECORD_HEALTH_TIMESTAMP_COLUMNS = ("updated_at","inserted_at")`) and measures *rows written within a recent window* vs watchlist. It therefore (a) **skips any table with no write-timestamp column** — `greek_exposure_daily` has neither, so it is invisible to health; and (b) measures *was-anything-written-lately*, never *is the newest **data date** advancing*. The two **freeze-class** failures this PR fixes — `vrp_daily` and `greek_exposure_daily` (newest data date stops advancing for the whole universe) — slipped through exactly this blind spot, and the monitor closes it.

**What the monitor does and does NOT catch (honest scope):** The monitor catches the **freeze class** — a table whose newest **data date** stops advancing, and (where the table has a ticker column) a **coverage drop** vs the active watchlist. It does **not** catch the #180 class: `option_intraday_buckets` has no ticker/underlying column (only `option_symbol`), so per-ticker coverage is not measurable there, and #180 was *not* a data-date freeze — the 49 covered tickers kept `max(trade_date)` advancing while a per-ticker subset silently dropped out. **The #180-recurrence guard is the Workstream-A per-outcome counters, not this monitor.** The monitor still tracks `option_intraday_buckets` data-date freshness (it would catch a *total* intraday-consumer death), but the per-ticker gap is A's job. Stating this split prevents the monitor from being mistaken for assurance it cannot provide.

**Monitor:** a nightly job that, for a **curated, scope-aware allow-list** of per-ticker tables, records into `data_freshness_snapshots`: the newest **data date** (`max(date_col)`), active-watchlist coverage (distinct tickers with a recent date ÷ expected scope), `days_stale`, and a `frozen` flag (`days_stale > grace`). Daily rows give a human-readable trend; the `frozen`/low-coverage flags drive a WARN log and a `freshness` block on `/api/health`. **Scope-aware** so by-design-partial tables (iv_rank_history index-only, etc.) don't cry wolf — the exact false-positive the original audit tripped over.

**Non-goals (YAGNI):** no time-series regression on the snapshots (a staleness threshold catches both hard stops and slow bleeds); no auto-remediation (the monitor alerts, humans/jobs fix); no per-ticker alerting (table-level is enough to catch a frozen shard or a dead rollup).

---

## File Structure

**Workstream A — #180 intraday coverage**
- Modify `src/uw_scan/worker/scheduler.py` (`_intraday_oi_refresh`, ~line 558) — `ticker_filter=None`.
- Modify `src/uw_scan/worker/jobs/option_intraday_jobs.py` — add per-outcome counters to the summary dict + log line.
- Create `scripts/backfill/intraday_buckets_backfill.py` — one-shot, budget-gated.
- Test `tests/integration/worker/test_intraday_oi_refresh.py` — full-watchlist coverage + counter assertions.

**Workstream B — #179 greek re-derive**
- Create `src/uw_scan/storage/migrations/086_greek_rederive_validation.sql` — validation table.
- Modify `src/uw_scan/storage/greek_exposure_repository.py` — `select_rederived_rows`, `compare_to_stored`, `insert_validation_rows`.
- Create `src/uw_scan/worker/jobs/greek_exposure_rederive.py` — recurring job.
- Modify `src/uw_scan/worker/scheduler.py` — register `greek_exposure_rederive` (primary-only, nightly).
- Create `scripts/backfill/greek_exposure_rederive_backfill.py` — one-shot all-history.
- Test `tests/integration/storage/test_greek_rederive.py` — canonical-run-per-date, sum correctness, validation diff.

**Workstream C — freshness monitor**
- Create `src/uw_scan/storage/migrations/087_data_freshness_snapshots.sql` — snapshot table.
- Create `src/uw_scan/reports/data_freshness.py` — monitored-table config + pure compute.
- Create `src/uw_scan/storage/data_freshness_repository.py` — own domain (per rules).
- Create `src/uw_scan/worker/jobs/data_freshness_monitor.py` — recurring job.
- Modify `src/uw_scan/worker/scheduler.py` — register `data_freshness_monitor` (primary-only, nightly).
- Modify `src/uw_scan/api/routers/health.py` (or the health assembler) — add a `freshness` block reading the latest snapshot.
- Test `tests/integration/reports/test_data_freshness.py` — frozen flagged, fresh clean, scope-aware coverage.

**Shared**
- Modify `CHANGELOG.md` — `[Unreleased]` entry.
- Modify `CLAUDE.md` + `src/uw_scan/worker/CLAUDE.md` — "Where to look" rows + schedule table.

---

## Workstream A — #180 intraday-buckets mega-cap coverage

### Task A1: Remove the shard filter from the primary-only intraday job + add per-outcome counters

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py` (`_intraday_oi_refresh`, ~line 542-560)
- Modify: `src/uw_scan/worker/jobs/option_intraday_jobs.py` (`refresh_intraday_for_top_oi_movers`)
- Test: `tests/integration/worker/test_intraday_oi_refresh.py`

**Interfaces:**
- Consumes: `repo.list_watchlist_cards()` (active cards, `.ticker`); `repo.latest_run_id(ticker)`; `repo.fetch_oi_change_top(run_id, limit)`; `repo.insert_scan_run`, `repo.finish_scan_run`; `OptionIntradayBucketRepository.upsert_buckets`; `fetch_option_contract_intraday(client, repo, run_id, option_symbol, date)`.
- Produces: `refresh_intraday_for_top_oi_movers(*, repo, client, settings, ticker_filter=None, top_n=DEFAULT_TOP_N, lock_key=INTRADAY_REFRESH_LOCK) -> dict[str, int]` now returns keys `tickers, contracts, buckets, skipped_no_run, skipped_no_movers, contracts_empty, contracts_error`.

- [ ] **Step 1: Write the failing test — full-watchlist coverage when unfiltered**

Create `tests/integration/worker/test_intraday_oi_refresh.py`. The test uses a fake UW client (no network) and seeds two tickers whose names land in **different** crc32 shards under `count=2`, proving the job covers both when `ticker_filter=None`. It also asserts the new counter keys exist.

```python
from __future__ import annotations

import zlib
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from uw_scan.models import MarketAggregates
from uw_scan.worker.jobs.option_intraday_jobs import refresh_intraday_for_top_oi_movers


def _shard(ticker: str, count: int = 2) -> int:
    return zlib.crc32(ticker.strip().upper().encode("utf-8")) % count


class _FakeUw:
    """Stand-in UW client; the job calls fetch_option_contract_intraday which
    we monkeypatch, so this only needs to exist as a placeholder handle."""


def _seed_ticker_with_movers(repo, ticker: str, trade_date: date) -> None:
    run_id = repo.insert_scan_run(ticker=ticker)
    repo.set_aggregates(run_id, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30")))
    repo.finish_scan_run(run_id, status="ok")
    repo.upsert_watchlist_card(
        ticker=ticker,
        run_id=run_id,
        scanned_at=datetime.now(timezone.utc),
        spot=Decimal("100.00"),
        iv_atm=Decimal("0.50"),
        iv_rank=Decimal("40.0"),
    )
    # One OI mover so fetch_oi_change_top returns a row to fetch. The source
    # table is oi_change_events (NOT "oi_change_top" — that is the method name,
    # not a table); its ticker column is underlying_symbol; PK (run_id,
    # option_symbol). fetch_oi_change_top reads e.option_symbol + e.curr_date,
    # which the job consumes as row["option_symbol"]/row["curr_date"].
    occ = f"{ticker}260710C00100000"
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.oi_change_events
                (run_id, underlying_symbol, option_symbol, curr_date, rnk, volume, avg_price)
            VALUES (%s, %s, %s, %s, 1, 500, 1.25)
            """,
            (run_id, ticker, occ, trade_date),
        )
    repo.conn.commit()


def test_unfiltered_job_covers_both_shards(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    td = date(2026, 6, 23)
    # Pick two real watchlist tickers on opposite shards (count=2).
    a, b = "AAPL", "TSLA"
    assert _shard(a) != _shard(b), "fixture assumption: opposite shards"
    _seed_ticker_with_movers(repo, a, td)
    _seed_ticker_with_movers(repo, b, td)

    attempted: list[str] = []

    def _fake_fetch(client, r, run_id, option_symbol, date_str):
        attempted.append(option_symbol)
        return []  # no buckets; we only care that the fetch was attempted

    monkeypatch.setattr(
        "uw_scan.worker.jobs.option_intraday_jobs.fetch_option_contract_intraday",
        _fake_fetch,
    )

    # Settings is a plain BaseModel with a REQUIRED api_key (no default), so
    # bare Settings() raises ValidationError. The job only reads
    # settings.db_schema, so a SimpleNamespace stub keyed to the test schema is
    # the correct, dependency-free double (mirrors the _FakeSettings pattern in
    # test_option_surface_iv_canary.py).
    from types import SimpleNamespace

    settings = SimpleNamespace(db_schema=repo._schema)
    summary = refresh_intraday_for_top_oi_movers(
        repo=repo, client=_FakeUw(), settings=settings, ticker_filter=None
    )

    # Both shards' contracts were attempted — the #180 regression guard.
    assert any(s.startswith("AAPL") for s in attempted)
    assert any(s.startswith("TSLA") for s in attempted)
    # New counter surface exists.
    for key in (
        "tickers", "contracts", "buckets",
        "skipped_no_run", "skipped_no_movers", "contracts_empty", "contracts_error",
    ):
        assert key in summary
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_intraday_oi_refresh.py -v`
Expected: FAIL — `KeyError`/assert on the missing counter keys (`skipped_no_run`, etc.).

> Seed table/columns verified against migration `001_s1_core_tables.sql`: `oi_change_events(run_id, underlying_symbol, option_symbol, curr_date, …, rnk, volume, avg_price)`, PK `(run_id, option_symbol)`.

- [ ] **Step 3: Add the per-outcome counters in the job**

In `src/uw_scan/worker/jobs/option_intraday_jobs.py`, extend the counters and the summary. Replace the counter init block and the loop's `continue` sites and the inner contract loop:

```python
    intraday_repo = OptionIntradayBucketRepository(repo.conn, schema=settings.db_schema)
    tickers_seen = 0
    contracts_done = 0
    buckets_written = 0
    skipped_no_run = 0
    skipped_no_movers = 0
    contracts_empty = 0
    contracts_error = 0
```

At the "no completed run yet" branch:

```python
            if not latest_run:
                logger.debug("intraday_refresh: %s has no completed run yet", ticker)
                skipped_no_run += 1
                continue
```

At the "no OI movers" branch:

```python
            top_rows = repo.fetch_oi_change_top(latest_run, limit=top_n)
            if not top_rows:
                logger.debug("intraday_refresh: %s no OI movers in latest run", ticker)
                skipped_no_movers += 1
                continue
```

Inside the per-contract loop, count empty fetches (a fetch that returned no buckets is a silent gap signal):

```python
                    n = intraday_repo.upsert_buckets(option_symbol, trade_date, buckets)
                    contracts_done += 1
                    buckets_written += n
                    if n == 0:
                        contracts_empty += 1
                    logger.info(
                        "intraday_refresh: %s %s %s buckets=%d",
                        ticker, option_symbol, trade_date, n,
                    )
```

In the per-ticker `except` (the rollback path), count the error:

```python
            except Exception as exc:
                repo.conn.rollback()
                contracts_error += 1
                logger.exception("intraday_refresh: %s failed: %s", ticker, repr(exc))
```

Replace the summary + final log:

```python
    summary = {
        "tickers": tickers_seen,
        "contracts": contracts_done,
        "buckets": buckets_written,
        "skipped_no_run": skipped_no_run,
        "skipped_no_movers": skipped_no_movers,
        "contracts_empty": contracts_empty,
        "contracts_error": contracts_error,
    }
    logger.info(
        "intraday_refresh complete tickers=%d contracts=%d buckets=%d "
        "skipped_no_run=%d skipped_no_movers=%d contracts_empty=%d contracts_error=%d",
        summary["tickers"], summary["contracts"], summary["buckets"],
        summary["skipped_no_run"], summary["skipped_no_movers"],
        summary["contracts_empty"], summary["contracts_error"],
    )
    return summary
```

- [ ] **Step 4: Apply the one-line scheduler fix**

In `src/uw_scan/worker/scheduler.py`, `_intraday_oi_refresh` (~line 558), change the filter and add an explanatory comment so nobody re-introduces the shard filter:

```python
                with _repo(settings) as repo:
                    # This job is registered ONLY on the primary worker (see the
                    # _is_primary_worker guard at its add_job). A primary-only
                    # singleton must NOT shard-filter: ticker_filter would drop
                    # every ticker outside shard 0, so half the watchlist
                    # (TSLA/NVDA/MSFT/GOOGL/META/AVGO ...) would be fetched by
                    # nobody. Single-flight is already enforced by the advisory
                    # lock inside the job — issue #180.
                    refresh_intraday_for_top_oi_movers(
                        repo=repo,
                        client=uw,
                        settings=settings,
                        ticker_filter=None,
                    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_intraday_oi_refresh.py -v`
Expected: PASS — both AAPL and TSLA contracts attempted; all counter keys present.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/scheduler.py src/uw_scan/worker/jobs/option_intraday_jobs.py tests/integration/worker/test_intraday_oi_refresh.py
git commit -m "fix(intraday): cover full watchlist on primary-only OI-mover refresh (#180)"
```

### Task A2: One-shot backfill for the tickers missed by the shard bug

**Files:**
- Create: `scripts/backfill/intraday_buckets_backfill.py`
- Test: (manual reproduce only — backfill scripts are UW-bound one-shots, gated by an explicit flag; no integration test)

**Interfaces:**
- Consumes: `refresh_intraday_for_top_oi_movers` (reused with `ticker_filter` set to *exactly* the missed tickers); `Settings`; `_repo`-equivalent connection.
- Produces: a CLI `uv run python scripts/backfill/intraday_buckets_backfill.py --confirm [--tickers T1,T2]` that fetches recent intraday for the missed set within UW's retention window.

- [ ] **Step 1: Write the backfill script**

```python
"""One-shot backfill for option_intraday_buckets tickers missed by the #180
shard bug (primary-only job wrongly shard-filtered). UW-bound — gated behind
--confirm so it never runs by accident, and bounded by UW's ~22-calendar-day
intraday retention (older sessions return empty buckets, not an error).

option_intraday_buckets has no ticker/underlying column (only option_symbol),
so the "already-covered" set cannot be computed from the table without OCC
parsing — we don't guess. Instead the operator passes the known-missed set
explicitly (the 6 mega-caps + any others), or --all to re-run the full
watchlist (idempotent, but costs more UW). The job's advisory lock + upsert
make every path safe to re-run.

Reproduce (missed set):
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/backfill/intraday_buckets_backfill.py \
      --tickers TSLA,NVDA,MSFT,GOOGL,META,AVGO --confirm
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_intraday_jobs import refresh_intraday_for_top_oi_movers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("intraday_backfill")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument("--tickers", default="", help="comma list of underlyings to backfill")
    ap.add_argument("--all", action="store_true", help="backfill the full active watchlist")
    args = ap.parse_args()

    settings = Settings.from_env()  # plain BaseModel: bare Settings() lacks required api_key
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    try:
        if args.all:
            target = {c.ticker.upper() for c in repo.list_watchlist_cards()}
        else:
            target = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        if not target:
            logger.error("no tickers: pass --tickers T1,T2 or --all")
            return 2
        if not args.confirm:
            logger.info("DRY RUN — would backfill %d tickers: %s", len(target), sorted(target))
            return 0

        client = UwClient(
            api_key=settings.api_key.get_secret_value(),  # UwClient takes api_key str, NOT settings
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            job_name="intraday_buckets_backfill",
        )
        summary = refresh_intraday_for_top_oi_movers(
            repo=repo,
            client=client,
            settings=settings,
            ticker_filter=lambda t: t.strip().upper() in target,
        )
        logger.info("backfill complete: %s", summary)
        return 0
    finally:
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

> **Note on the selector:** the backfill reuses the production job with a ticker allow-list so the persistence path and idempotent upsert are identical to the nightly run — re-running is safe (already-covered tickers re-upsert the same rows). It does **not** invent a side-channel write path. Older-than-retention sessions return empty buckets (counted as `contracts_empty`), not errors.

- [ ] **Step 2: Verify the dry run (no UW calls)**

Run: `UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/backfill/intraday_buckets_backfill.py --tickers TSLA,NVDA`
Expected: logs `DRY RUN — would backfill 2 tickers: ['NVDA', 'TSLA']` and exits 0 with no UW calls. (With no `--tickers`/`--all`: exits 2 with the "no tickers" error.)

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill/intraday_buckets_backfill.py
git commit -m "feat(intraday): one-shot backfill for #180-missed tickers (budget-gated)"
```

---

## Workstream B — #179 single-name `greek_exposure_daily` re-derive

### Task B1: Validation table migration + re-derive/validate repository methods

**Files:**
- Create: `src/uw_scan/storage/migrations/086_greek_rederive_validation.sql`
- Modify: `src/uw_scan/storage/greek_exposure_repository.py`
- Test: `tests/integration/storage/test_greek_rederive.py`

**Interfaces:**
- Consumes: `exposures_by_expiry_strike(run_id, ticker, market_date, call_gex, put_gex, call_delta, put_delta)`; `scan_runs(run_id, ticker, status, aggregates)`; existing `GreekExposureDailyRepository.upsert_rows`, `.fetch_history`.
- Produces:
  - `GreekExposureDailyRepository.select_rederived_rows(ticker: str | None = None, since: date | None = None) -> list[dict]` — keys `ticker, trade_date, call_gex, put_gex, call_delta, put_delta`, one row per `(ticker, market_date)` using the canonical run.
  - `GreekExposureDailyRepository.compare_to_stored(rederived: list[dict]) -> list[dict]` — keys `ticker, trade_date, rederived_net_gex, stored_net_gex, abs_diff, pct_diff` (only dates present in *both*).
  - `GreekExposureDailyRepository.insert_validation_rows(run_date: date, diffs: list[dict]) -> int`.

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/086_greek_rederive_validation.sql`:

```sql
-- 086_greek_rederive_validation.sql
--
-- Audit trail for the DB->DB re-derive of greek_exposure_daily from the
-- per-strike exposures_by_expiry_strike table (#179). Each row records, for a
-- ticker/date where BOTH the re-derived sum and the stored UW aggregate exist,
-- how far apart they are — proving the per-strike sum matches UW's full-chain
-- aggregate (or quantifying the gap). Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.greek_rederive_validation (
    run_date          DATE NOT NULL,
    ticker            TEXT NOT NULL,
    trade_date        DATE NOT NULL,
    rederived_net_gex NUMERIC(20,4),
    stored_net_gex    NUMERIC(20,4),
    abs_diff          NUMERIC(20,4),
    pct_diff          DOUBLE PRECISION,
    PRIMARY KEY (run_date, ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_greek_rederive_validation_ticker_date
    ON uw_scan.greek_rederive_validation (ticker, trade_date DESC);

COMMIT;
```

- [ ] **Step 2: Write the failing test**

Create `tests/integration/storage/test_greek_rederive.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from uw_scan.models import MarketAggregates
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository


def _insert_strike(repo, run_id, ticker, market_date, expiry, strike, cg, pg, cd, pd):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike, dte,
                 call_delta, put_delta, call_gex, put_gex)
            VALUES (%s,%s,%s,%s,%s,30,%s,%s,%s,%s)
            ON CONFLICT (run_id, ticker, expiry, strike) DO NOTHING
            """,
            (run_id, ticker, market_date, expiry, strike, cd, pd, cg, pg),
        )
    repo.conn.commit()


def _ok_run(repo, ticker):
    run_id = repo.insert_scan_run(ticker=ticker)
    repo.set_aggregates(run_id, MarketAggregates(call_oi_total=1, iv30d=None))
    repo.finish_scan_run(run_id, status="ok")
    return run_id


def test_rederive_sums_strikes_per_canonical_run(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 21)

    # Two runs for the SAME (ticker, market_date) — naive SUM would double-count.
    stale = _ok_run(repo, "NVDA")  # earlier, smaller capture
    _insert_strike(repo, stale, "NVDA", md, date(2026, 6, 20), 900, 1.0, -0.5, 10, -5)
    canon = _ok_run(repo, "NVDA")  # later, canonical
    _insert_strike(repo, canon, "NVDA", md, date(2026, 6, 20), 900, 2.0, -1.0, 20, -8)
    _insert_strike(repo, canon, "NVDA", md, date(2026, 6, 20), 950, 3.0, -1.5, 30, -9)

    rows = g.select_rederived_rows(ticker="NVDA")
    assert len(rows) == 1
    r = rows[0]
    assert r["trade_date"] == md
    # Only the canonical (later) run's strikes summed: 2+3, -1-1.5, 20+30, -8-9
    assert r["call_gex"] == pytest.approx(5.0)
    assert r["put_gex"] == pytest.approx(-2.5)
    assert r["call_delta"] == pytest.approx(50.0)
    assert r["put_delta"] == pytest.approx(-17.0)


def test_rederive_skips_non_ok_runs(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 22)
    bad = repo.insert_scan_run(ticker="AMD")  # no aggregates, not finished ok
    _insert_strike(repo, bad, "AMD", md, date(2026, 6, 20), 100, 9.0, -9.0, 9, -9)
    assert g.select_rederived_rows(ticker="AMD") == []


def test_compare_to_stored_and_persist(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 23)
    # Stored aggregate (as if UW-fed): net_gex = 10 + (-4) = 6
    g.upsert_rows("SPY", [{
        "trade_date": md, "call_gex": 10.0, "put_gex": -4.0,
        "call_delta": 1.0, "put_delta": -1.0, "payload": {},
    }])
    # Re-derived rows that net to 5 (abs_diff 1, pct ~16.7%)
    diffs = g.compare_to_stored([{
        "ticker": "SPY", "trade_date": md,
        "call_gex": 7.0, "put_gex": -2.0, "call_delta": 0.0, "put_delta": 0.0,
    }])
    assert len(diffs) == 1
    d = diffs[0]
    assert d["rederived_net_gex"] == pytest.approx(5.0)
    assert d["stored_net_gex"] == pytest.approx(6.0)
    assert d["abs_diff"] == pytest.approx(1.0)
    n = g.insert_validation_rows(date(2026, 5, 24), diffs)
    assert n == 1


def test_compare_to_stored_skips_null_sums(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    md = date(2026, 5, 25)
    g.upsert_rows("SPY", [{
        "trade_date": md, "call_gex": 1.0, "put_gex": -1.0,
        "call_delta": 0.0, "put_delta": 0.0, "payload": {},
    }])
    # All-NULL-strike day -> SUM(call_gex)/SUM(put_gex) come back None. Must NOT
    # crash on float(None); the row is simply skipped (nothing to compare).
    diffs = g.compare_to_stored([
        {"ticker": "SPY", "trade_date": md, "call_gex": None, "put_gex": None,
         "call_delta": None, "put_delta": None},
    ])
    assert diffs == []
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_greek_rederive.py -v`
Expected: FAIL — `AttributeError: 'GreekExposureDailyRepository' object has no attribute 'select_rederived_rows'`.

> Migrations run automatically in the test session (`apply_migrations` in conftest). If `greek_rederive_validation` is missing, confirm the migration file is the next lexical number and re-run.

- [ ] **Step 4: Implement the three methods**

Append to `src/uw_scan/storage/greek_exposure_repository.py` (inside the class). Add `from datetime import date` and `from typing import Any` imports at the top if absent.

```python
    def select_rederived_rows(
        self, ticker: str | None = None, since: "date | None" = None
    ) -> list[dict]:
        """Sum per-strike GEX/DEX into daily totals, one row per (ticker,
        market_date) using the canonical run.

        Canonical run = the latest run_id for that (ticker, market_date) that is
        status='ok' AND aggregates IS NOT NULL — the same renderable-run rule
        latest_run_id uses, applied per historical date. Because one scan_run
        captures exactly one market_date, MAX(run_id) per (ticker, market_date)
        picks the most recent renderable capture and avoids double-counting
        across full_scan + rescans.
        """
        sql = """
            WITH canonical AS (
                SELECT e.ticker, e.market_date, MAX(e.run_id) AS run_id
                  FROM exposures_by_expiry_strike e
                  JOIN scan_runs r ON r.run_id = e.run_id
                 WHERE r.status = 'ok'
                   AND r.aggregates IS NOT NULL
                   AND r.aggregates::text NOT IN ('{}', 'null')
                   AND (%(ticker)s IS NULL OR e.ticker = %(ticker)s)
                   AND (%(since)s IS NULL OR e.market_date >= %(since)s)
                 GROUP BY e.ticker, e.market_date
            )
            SELECT e.ticker,
                   e.market_date AS trade_date,
                   SUM(e.call_gex)::float8   AS call_gex,
                   SUM(e.put_gex)::float8    AS put_gex,
                   SUM(e.call_delta)::float8 AS call_delta,
                   SUM(e.put_delta)::float8  AS put_delta
              FROM exposures_by_expiry_strike e
              JOIN canonical c
                ON c.run_id = e.run_id
               AND c.ticker = e.ticker
               AND c.market_date = e.market_date
             GROUP BY e.ticker, e.market_date
             ORDER BY e.ticker, e.market_date
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, {"ticker": ticker, "since": since})
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def compare_to_stored(self, rederived: list[dict]) -> list[dict]:
        """For each re-derived row whose (ticker, trade_date) ALSO has a stored
        row, return the net_gex diff. Dates present in only one source are
        skipped (nothing to compare)."""
        if not rederived:
            return []
        out: list[dict] = []
        with self._conn.cursor() as cur:
            for r in rederived:
                # SUM(call_gex)/SUM(put_gex) are NULL when every contributing
                # strike was NULL — float(None) would crash the job. Nothing to
                # compare, so skip.
                if r.get("call_gex") is None or r.get("put_gex") is None:
                    continue
                cur.execute(
                    """
                    SELECT net_gex::float8 FROM greek_exposure_daily
                     WHERE ticker = %s AND trade_date = %s
                    """,
                    (r["ticker"], r["trade_date"]),
                )
                hit = cur.fetchone()
                if hit is None or hit[0] is None:
                    continue
                stored = float(hit[0])
                rederived_net = float(r["call_gex"]) + float(r["put_gex"])
                abs_diff = abs(rederived_net - stored)
                pct = abs_diff / abs(stored) if stored else None
                out.append({
                    "ticker": r["ticker"],
                    "trade_date": r["trade_date"],
                    "rederived_net_gex": rederived_net,
                    "stored_net_gex": stored,
                    "abs_diff": abs_diff,
                    "pct_diff": pct,
                })
        return out

    def insert_validation_rows(self, run_date: "date", diffs: list[dict]) -> int:
        if not diffs:
            return 0
        sql = """
            INSERT INTO greek_rederive_validation
                (run_date, ticker, trade_date, rederived_net_gex,
                 stored_net_gex, abs_diff, pct_diff)
            VALUES (%(run_date)s, %(ticker)s, %(trade_date)s,
                    %(rederived_net_gex)s, %(stored_net_gex)s,
                    %(abs_diff)s, %(pct_diff)s)
            ON CONFLICT (run_date, ticker, trade_date) DO UPDATE SET
                rederived_net_gex = EXCLUDED.rederived_net_gex,
                stored_net_gex    = EXCLUDED.stored_net_gex,
                abs_diff          = EXCLUDED.abs_diff,
                pct_diff          = EXCLUDED.pct_diff
        """
        params = [{"run_date": run_date, **d} for d in diffs]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_greek_rederive.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/086_greek_rederive_validation.sql src/uw_scan/storage/greek_exposure_repository.py tests/integration/storage/test_greek_rederive.py
git commit -m "feat(gex): re-derive + validate single-name greek_exposure_daily from per-strike (#179)"
```

### Task B2: Recurring re-derive job + scheduler registration

**Files:**
- Create: `src/uw_scan/worker/jobs/greek_exposure_rederive.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_greek_exposure_rederive_job.py`

**Interfaces:**
- Consumes: `GreekExposureDailyRepository.select_rederived_rows/.upsert_rows/.compare_to_stored/.insert_validation_rows`; `repo.list_watchlist_cards()`; `Settings.gex_scan_tickers`.
- Produces: `greek_exposure_rederive(*, repo, settings, run_date, since=None, validate_tickers=None) -> dict[str, int]` (keys `tickers, rows, validated, warn`).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/worker/test_greek_exposure_rederive_job.py`:

```python
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from uw_scan.models import MarketAggregates
from uw_scan.worker.jobs.greek_exposure_rederive import greek_exposure_rederive


def _ok_run(repo, ticker):
    rid = repo.insert_scan_run(ticker=ticker)
    repo.set_aggregates(rid, MarketAggregates(call_oi_total=1, iv30d=None))
    repo.finish_scan_run(rid, status="ok")
    return rid


def _strike(repo, rid, ticker, md, cg, pg):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id,ticker,market_date,expiry,strike,dte,call_delta,put_delta,call_gex,put_gex)
                VALUES (%s,%s,%s,%s,100,30,1,-1,%s,%s)
                ON CONFLICT DO NOTHING""",
            (rid, ticker, md, date(2026, 6, 20), cg, pg),
        )
    repo.conn.commit()


def test_rederive_job_populates_daily(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    md = date(2026, 5, 21)
    rid = _ok_run(repo, "NVDA")
    _strike(repo, rid, "NVDA", md, 4.0, -1.0)

    # Stub settings — the job reads only db_schema + gex_scan_tickers.
    settings = SimpleNamespace(db_schema=repo._schema, gex_scan_tickers=["SPX", "SPY", "TLT"])
    summary = greek_exposure_rederive(
        repo=repo, settings=settings, run_date=date(2026, 5, 22)
    )
    assert summary["rows"] >= 1

    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    hist = g.fetch_history("NVDA", days=10)
    assert hist and hist[-1]["net_gex"] == pytest.approx(3.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_greek_exposure_rederive_job.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.worker.jobs.greek_exposure_rederive`.

- [ ] **Step 3: Write the job**

Create `src/uw_scan/worker/jobs/greek_exposure_rederive.py`:

```python
"""Nightly DB->DB re-derive of single-name greek_exposure_daily from the
per-strike exposures_by_expiry_strike table (#179). Zero UW calls.

For each active watchlist ticker: sum the canonical run's per-strike GEX/DEX
per market_date and upsert into greek_exposure_daily (net_gex/net_dex are
generated columns). For the index tickers that ALSO have a UW-fed stored
series (gex_scan_tickers, default SPX/SPY/TLT), compare re-derived vs stored
net_gex and persist the diff to greek_rederive_validation; WARN on material
divergence so a basis mismatch is never shipped silently.
"""

from __future__ import annotations

import logging
from datetime import date

from uw_scan.config import Settings
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

# ponytail: 1% net_gex divergence is the WARN line; tighten if validation
# shows the per-strike sum tracks UW's aggregate more closely than that.
VALIDATION_WARN_PCT = 0.01


def greek_exposure_rederive(
    *,
    repo: Repository,
    settings: Settings,
    run_date: date,
    since: date | None = None,
    validate_tickers: list[str] | None = None,
) -> dict[str, int]:
    g = GreekExposureDailyRepository(repo.conn, schema=settings.db_schema)
    validate = {
        t.upper() for t in (validate_tickers or settings.gex_scan_tickers)
    }

    tickers_done = 0
    rows_written = 0
    validated = 0
    warns = 0
    validate_had_rows = False  # did any index ticker even have per-strike rows?

    for card in repo.list_watchlist_cards():
        ticker = card.ticker
        rows = g.select_rederived_rows(ticker=ticker, since=since)
        if not rows:
            continue
        # Index tickers already have an authoritative UW-fed series; do NOT
        # overwrite it with the per-strike proxy. Re-derive single names only,
        # but still validate the indices' proxy against their stored truth.
        if ticker.upper() not in validate:
            g.upsert_rows(ticker, [
                {**r, "payload": {"source": "rederive_from_strikes"}} for r in rows
            ])
            rows_written += len(rows)
        else:
            validate_had_rows = True
            diffs = g.compare_to_stored(rows)
            validated += g.insert_validation_rows(run_date, diffs)
            for d in diffs:
                if d["pct_diff"] is not None and d["pct_diff"] > VALIDATION_WARN_PCT:
                    warns += 1
                    logger.warning(
                        "greek_rederive validation: %s %s rederived=%.2f stored=%.2f "
                        "pct=%.4f exceeds %.4f — per-strike basis differs from UW aggregate",
                        d["ticker"], d["trade_date"], d["rederived_net_gex"],
                        d["stored_net_gex"], d["pct_diff"], VALIDATION_WARN_PCT,
                    )

        tickers_done += 1

    # The basis check is load-bearing (Decision-1): if the index tickers had
    # per-strike rows but produced ZERO comparable dates (no overlapping stored
    # rows), validation silently did nothing. Surface that as a WARN so "no
    # warnings" never gets misread as "basis confirmed".
    if validate_had_rows and validated == 0:
        logger.warning(
            "greek_rederive: validation produced 0 comparable rows for %s — "
            "basis check did NOT run (no overlapping per-strike + stored dates)",
            sorted(validate),
        )

    summary = {"tickers": tickers_done, "rows": rows_written, "validated": validated, "warn": warns}
    logger.info(
        "greek_exposure_rederive complete tickers=%d rows=%d validated=%d warn=%d",
        summary["tickers"], summary["rows"], summary["validated"], summary["warn"],
    )
    return summary
```

> **Design note (basis safety):** index tickers (SPX/SPY/TLT) keep their authoritative UW-fed rows — the job only *validates* the per-strike proxy against them. Single names get the re-derived proxy because no authoritative source exists for them. If validation WARNs persistently (proxy ≠ aggregate), that is the signal to apply a scale/sign transform in `select_rederived_rows` before trusting single-name values — per the approved Decision-1 lean.
>
> **Validation-overlap caveat (Pass-2 finding):** the two sources are written by *different* pipelines — `greek_exposure_daily` by the GEX scanner over `gex_scan_tickers`, `exposures_by_expiry_strike` by watchlist **full scans**. A *pure index* like SPX may have no full-scan per-strike rows, so it cannot be validated; the check effectively covers whichever of SPX/SPY/TLT are also full-scan names (the SPY/TLT ETFs, in practice). The `validate_had_rows && validated == 0` WARN added above is the backstop: it fires loudly if **none** of the validator tickers produced a comparable date, so "no warnings" can never be misread as "basis confirmed" when the check simply never ran.

- [ ] **Step 4: Register the job in the scheduler**

In `src/uw_scan/worker/scheduler.py`, add the wrapper near the other primary-only nightly jobs, and register inside the existing `if _is_primary_worker(settings):` block (the same block that holds `_intraday_oi_refresh`):

```python
    def _greek_exposure_rederive() -> None:
        from uw_scan.worker.jobs.greek_exposure_rederive import greek_exposure_rederive

        # ET-anchored (repo convention) — never host-local date.today(), which
        # can pick the wrong month boundary / run_date on a non-ET host.
        et_today = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            greek_exposure_rederive(
                repo=repo,
                settings=settings,
                run_date=et_today,
                since=et_today.replace(day=1),  # current-month forward each night
            )
```

```python
            sched.add_job(
                _greek_exposure_rederive,
                CronTrigger.from_crontab("30 18 * * 0-4", timezone=settings.rth_tz),
                id="greek_exposure_rederive",
                name="Single-name greek_exposure_daily re-derive (#179)",
                max_instances=1,
                coalesce=True,
            )
```

> Cron `30 18` runs after `nightly_vol_analytics_rollup` (18:00) and before the 19:00 surface jobs, when the day's `exposures_by_expiry_strike` rows are present. It reads only the DB, so it never competes for the UW budget.

- [ ] **Step 5: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_greek_exposure_rederive_job.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/jobs/greek_exposure_rederive.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_greek_exposure_rederive_job.py
git commit -m "feat(gex): nightly single-name greek_exposure_daily re-derive job (#179)"
```

### Task B3: One-shot historical backfill

**Files:**
- Create: `scripts/backfill/greek_exposure_rederive_backfill.py`

**Interfaces:**
- Consumes: `greek_exposure_rederive` (reused with `since=None` → all history).
- Produces: CLI `uv run python scripts/backfill/greek_exposure_rederive_backfill.py` (no `--confirm` needed — zero UW, DB→DB only; idempotent).

- [ ] **Step 1: Write the backfill script**

```python
"""One-shot historical backfill of single-name greek_exposure_daily from
exposures_by_expiry_strike (#179). Pure DB->DB, zero UW, idempotent — safe to
re-run. Walks ALL available per-strike history (since=None).

Reproduce:
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/backfill/greek_exposure_rederive_backfill.py
"""

from __future__ import annotations

import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.greek_exposure_rederive import greek_exposure_rederive

logging.basicConfig(level=logging.INFO)


def main() -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    settings = Settings.from_env()  # plain BaseModel: bare Settings() lacks required api_key
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    try:
        summary = greek_exposure_rederive(
            repo=repo,
            settings=settings,
            run_date=datetime.now(ZoneInfo(settings.rth_tz)).date(),  # ET-anchored
            since=None,  # all history
        )
        logging.getLogger("gex_backfill").info("backfill complete: %s", summary)
        return 0
    finally:
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

> **Limitation (basis seam):** the backfill re-derives wherever `exposures_by_expiry_strike` has history. Any single-name `greek_exposure_daily` rows that *predate* per-strike capture remain on their original (one-off UW-aggregate) basis, so a chart could show a small seam at the per-strike coverage boundary. This is cosmetic and bounded (single-name rows were frozen at 2026-05-20 anyway); re-deriving forward from per-strike data makes the live series internally consistent. No action needed unless a seam is observed.

- [ ] **Step 2: Verify it imports and dry-reasons (no DB write on an empty test schema is fine)**

Run: `uv run python -c "import scripts.backfill.greek_exposure_rederive_backfill as m; print(m.main.__doc__ or 'ok')"`
Expected: prints `ok` (import succeeds; no syntax/import errors).

- [ ] **Step 3: Commit**

```bash
git add scripts/backfill/greek_exposure_rederive_backfill.py
git commit -m "feat(gex): one-shot all-history greek_exposure_daily re-derive backfill (#179)"
```

---

## Workstream C — data-date freshness monitor

### Task C1: Snapshot table migration + monitored-table config + pure compute

**Files:**
- Create: `src/uw_scan/storage/migrations/087_data_freshness_snapshots.sql`
- Create: `src/uw_scan/reports/data_freshness.py`
- Test: `tests/integration/reports/test_data_freshness.py`

**Interfaces:**
- Consumes: a psycopg connection + schema; `repo.list_watchlist_cards()` for active tickers.
- Produces:
  - `MONITORED_TABLES: list[MonitoredTable]` — curated allow-list.
  - `compute_freshness(conn, schema, monitored, active_tickers, today, grace_days=4) -> list[FreshnessRow]`.
  - `MonitoredTable(name: str, scope: str, expected_tickers: frozenset[str] | None)` and `FreshnessRow` dataclasses.

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/087_data_freshness_snapshots.sql`:

```sql
-- 087_data_freshness_snapshots.sql
--
-- Nightly per-table data-DATE freshness audit (#prevention). Complements
-- list_record_health, which keys on WRITE-timestamp columns and skips tables
-- with none (e.g. greek_exposure_daily). This records the newest DATA date and
-- active-watchlist coverage so a silent freeze is caught the morning it starts.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.data_freshness_snapshots (
    run_date        DATE NOT NULL,
    table_name      TEXT NOT NULL,
    date_col        TEXT NOT NULL,
    scope           TEXT NOT NULL,          -- 'watchlist' | 'subset'
    expected_count  INTEGER NOT NULL,       -- denominator for coverage
    covered_count   INTEGER NOT NULL,       -- distinct tickers with a recent date
    coverage_pct    DOUBLE PRECISION,
    max_data_date   DATE,
    days_stale      INTEGER,
    frozen          BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_date, table_name)
);

CREATE INDEX IF NOT EXISTS ix_data_freshness_snapshots_table
    ON uw_scan.data_freshness_snapshots (table_name, run_date DESC);

COMMIT;
```

- [ ] **Step 2: Write the failing test**

Create `tests/integration/reports/test_data_freshness.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.reports.data_freshness import MonitoredTable, compute_freshness


def _seed_greek_daily(repo, ticker, trade_date):
    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    g.upsert_rows(ticker, [{
        "trade_date": trade_date, "call_gex": 1.0, "put_gex": -1.0,
        "call_delta": 1.0, "put_delta": -1.0, "payload": {},
    }])


def test_frozen_table_flagged(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    # Newest data is 5 weeks old -> frozen.
    _seed_greek_daily(repo, "NVDA", date(2026, 5, 20))
    monitored = [MonitoredTable(name="greek_exposure_daily", scope="watchlist", expected_tickers=None)]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["NVDA", "AMD"], today=today
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.date_col == "trade_date"
    assert r.max_data_date == date(2026, 5, 20)
    assert r.days_stale == (today - date(2026, 5, 20)).days
    assert r.frozen is True


def test_fresh_table_not_frozen(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    _seed_greek_daily(repo, "NVDA", date(2026, 6, 24))  # yesterday
    monitored = [MonitoredTable(name="greek_exposure_daily", scope="watchlist", expected_tickers=None)]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["NVDA"], today=today
    )
    assert rows[0].frozen is False
    assert rows[0].coverage_pct == pytest.approx(1.0)


def test_subset_scope_uses_named_denominator(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    _seed_greek_daily(repo, "SPY", date(2026, 6, 24))
    monitored = [MonitoredTable(
        name="greek_exposure_daily", scope="subset",
        expected_tickers=frozenset({"SPX", "SPY", "TLT"}),
    )]
    rows = compute_freshness(
        repo.conn, repo._schema, monitored, active_tickers=["AAPL"], today=today
    )
    # Coverage measured vs the 3-name subset, not the 1-name active list.
    assert rows[0].expected_count == 3
    assert rows[0].covered_count == 1
    assert rows[0].coverage_pct == pytest.approx(1 / 3)


def test_ticker_less_table_is_freshness_only(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    today = date(2026, 6, 25)
    # option_intraday_buckets has no ticker/underlying column (only
    # option_symbol). The monitor must still compute data-date freshness, with
    # coverage fields null.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.option_intraday_buckets
                (option_symbol, trade_date, start_time, close)
            VALUES ('TSLA260710C00410000', %s, %s, 1.0)
            """,
            (date(2026, 5, 20), "2026-05-20T14:30:00+00:00"),
        )
    repo.conn.commit()
    monitored = [MonitoredTable("option_intraday_buckets", "watchlist", None)]
    rows = compute_freshness(repo.conn, repo._schema, monitored, active_tickers=["TSLA"], today=today)
    r = rows[0]
    assert r.date_col == "trade_date"
    assert r.max_data_date == date(2026, 5, 20)
    assert r.frozen is True            # 5-weeks stale -> frozen flagged
    assert r.coverage_pct is None      # no ticker column -> no coverage
    assert r.expected_count == 0
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/reports/test_data_freshness.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.reports.data_freshness`.

- [ ] **Step 4: Write the compute module**

Create `src/uw_scan/reports/data_freshness.py`:

```python
"""Per-table data-DATE freshness audit (prevention layer for silent freezes).

Complements storage.health.list_record_health: that check discovers tables by a
WRITE-timestamp column (updated_at/inserted_at) and measures rows-written-lately
vs the watchlist. It is structurally blind to (a) tables with no write-timestamp
column (greek_exposure_daily) and (b) a frozen DATA date behind fresh writes.
This module measures the newest DATA date and scope-aware coverage instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from psycopg import Connection, sql as psql

# Preference order for the data-date column, most specific first. The monitor
# auto-detects which one a table actually has (avoids hardcoding a wrong name).
_DATE_COL_PREFERENCE = (
    "market_date", "trade_date", "session_date", "curr_date", "as_of_date", "date",
)


@dataclass(frozen=True)
class MonitoredTable:
    name: str
    scope: str  # 'watchlist' (denominator = active watchlist) | 'subset' (named set)
    expected_tickers: frozenset[str] | None  # required when scope == 'subset'


@dataclass(frozen=True)
class FreshnessRow:
    table_name: str
    date_col: str
    scope: str
    expected_count: int
    covered_count: int
    coverage_pct: float | None
    max_data_date: date | None
    days_stale: int | None
    frozen: bool


# Curated allow-list. Scope marks by-design-partial tables so they don't cry
# wolf (the false-positive the original audit itself tripped over). Extend as
# new per-ticker tables ship; unknown date columns are skipped with a row.
MONITORED_TABLES: list[MonitoredTable] = [
    MonitoredTable("options_volume_daily", "watchlist", None),
    MonitoredTable("daily_ohlc", "watchlist", None),
    MonitoredTable("vrp_daily", "watchlist", None),
    MonitoredTable("exposures_by_expiry_strike", "watchlist", None),
    MonitoredTable("oi_by_strike", "watchlist", None),
    # Ticker-less (keyed by option_symbol) -> freshness-only; per-ticker
    # coverage for this table is guarded by the intraday job's counters (#180).
    MonitoredTable("option_intraday_buckets", "watchlist", None),
    MonitoredTable("greek_exposure_daily", "watchlist", None),  # watchlist-wide post-#179
    MonitoredTable(
        "iv_rank_history", "subset",
        frozenset({"SPX", "SPY", "QQQ", "IWM"}),  # cockpit-only by design
    ),
]


def _detect_date_col(conn: Connection, schema: str, table: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
            """,
            (schema, table),
        )
        cols = {r[0] for r in cur.fetchall()}
    if not cols:
        return None
    for pref in _DATE_COL_PREFERENCE:
        if pref in cols:
            return pref
    return None


def _ticker_col(conn: Connection, schema: str, table: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = %s AND table_name = %s
               AND column_name IN ('ticker', 'symbol', 'underlying')
             ORDER BY array_position(ARRAY['ticker','symbol','underlying'], column_name)
             LIMIT 1
            """,
            (schema, table),
        )
        row = cur.fetchone()
    return row[0] if row else None


def compute_freshness(
    conn: Connection,
    schema: str,
    monitored: list[MonitoredTable],
    active_tickers: list[str],
    today: date,
    grace_days: int = 4,  # ponytail: covers a weekend + a holiday; raise per-table later if noisy
) -> list[FreshnessRow]:
    out: list[FreshnessRow] = []
    active = {t.upper() for t in active_tickers}
    for mt in monitored:
        date_col = _detect_date_col(conn, schema, mt.name)
        tcol = _ticker_col(conn, schema, mt.name)
        if date_col is None:
            # No data-date column at all -> nothing this monitor can measure.
            out.append(FreshnessRow(mt.name, "?", mt.scope, 0, 0, None, None, None, False))
            continue

        # Data-date freshness needs only the date column — works even for
        # ticker-less tables (e.g. option_intraday_buckets, keyed by
        # option_symbol). A TOTAL freeze of such a table is still caught here;
        # per-ticker COVERAGE (the #180 class) needs a ticker column and is
        # guarded separately by the intraday job's per-outcome counters.
        with conn.cursor() as cur:
            # ponytail: plain MAX — a seq scan on tables without a lone date
            # index (e.g. exposures_by_expiry_strike). Fine for one nightly run;
            # add a date index only if this monitor ever shows up as slow.
            cur.execute(
                psql.SQL("SELECT MAX({dcol}) FROM {tbl}").format(
                    dcol=psql.Identifier(date_col),
                    tbl=psql.Identifier(schema, mt.name),
                )
            )
            max_date = cur.fetchone()[0]
        days_stale = (today - max_date).days if max_date else None
        frozen = days_stale is not None and days_stale > grace_days

        if tcol is None:
            # Freshness-only: no per-ticker coverage possible.
            out.append(FreshnessRow(
                mt.name, date_col, mt.scope, 0, 0, None, max_date, days_stale, frozen,
            ))
            continue

        if mt.scope == "subset" and mt.expected_tickers:
            expected = {t.upper() for t in mt.expected_tickers}
        else:
            expected = active
        expected_count = len(expected)

        # Covered = expected-scope tickers with a row within grace_days of the
        # table's own newest date, so a table legitimately lagging one session
        # still counts those tickers covered.
        covered = 0
        if max_date is not None and expected:
            covq = psql.SQL(
                "SELECT COUNT(DISTINCT {tcol})::int FROM {tbl} "
                "WHERE {dcol} >= %s - %s::int AND UPPER({tcol}) = ANY(%s)"
            ).format(
                dcol=psql.Identifier(date_col),
                tcol=psql.Identifier(tcol),
                tbl=psql.Identifier(schema, mt.name),
            )
            with conn.cursor() as cur:
                cur.execute(covq, (max_date, grace_days, list(expected)))
                covered = cur.fetchone()[0]

        coverage_pct = (covered / expected_count) if expected_count else None
        out.append(FreshnessRow(
            mt.name, date_col, mt.scope, expected_count, covered,
            coverage_pct, max_date, days_stale, frozen,
        ))
    return out
```

> **Note:** if `daily_ohlc` / `options_volume_daily` / `option_intraday_buckets` use a date column outside `_DATE_COL_PREFERENCE`, the autodetect returns `None` and the monitor emits a "?" row rather than a wrong number — verify each with `\d uw_scan.<table>` during execution and extend `_DATE_COL_PREFERENCE` if needed. **Do not hardcode a column you haven't confirmed.**

- [ ] **Step 5: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/reports/test_data_freshness.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/087_data_freshness_snapshots.sql src/uw_scan/reports/data_freshness.py tests/integration/reports/test_data_freshness.py
git commit -m "feat(monitor): data-date freshness compute + curated table allow-list"
```

### Task C2: Freshness snapshot repository (own domain)

**Files:**
- Create: `src/uw_scan/storage/data_freshness_repository.py`
- Test: `tests/integration/storage/test_data_freshness_repository.py`

**Interfaces:**
- Consumes: `FreshnessRow` from `reports/data_freshness.py`.
- Produces:
  - `DataFreshnessRepository(conn, schema).upsert_snapshot(run_date, rows: list[FreshnessRow]) -> int`
  - `DataFreshnessRepository(conn, schema).latest_snapshot() -> list[dict]` (most recent `run_date`'s rows).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/storage/test_data_freshness_repository.py`:

```python
from __future__ import annotations

from datetime import date

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository


def test_upsert_and_latest(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    fr = DataFreshnessRepository(repo.conn, schema=repo._schema)
    rows = [
        FreshnessRow("vrp_daily", "market_date", "watchlist", 100, 9, 0.09,
                     date(2026, 5, 22), 34, True),
        FreshnessRow("daily_ohlc", "market_date", "watchlist", 100, 100, 1.0,
                     date(2026, 6, 24), 1, False),
    ]
    assert fr.upsert_snapshot(date(2026, 6, 25), rows) == 2
    latest = fr.latest_snapshot()
    by_name = {r["table_name"]: r for r in latest}
    assert by_name["vrp_daily"]["frozen"] is True
    assert by_name["daily_ohlc"]["frozen"] is False
    assert by_name["vrp_daily"]["coverage_pct"] == 0.09
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_data_freshness_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.storage.data_freshness_repository`.

- [ ] **Step 3: Write the repository**

Create `src/uw_scan/storage/data_freshness_repository.py`:

```python
"""Persistence for data-date freshness snapshots (prevention layer). New
domain — own file (never appended to repository.py)."""

from __future__ import annotations

from datetime import date

from psycopg import Connection

from uw_scan.reports.data_freshness import FreshnessRow


class DataFreshnessRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_snapshot(self, run_date: date, rows: list[FreshnessRow]) -> int:
        if not rows:
            return 0
        params = [
            {
                "run_date": run_date,
                "table_name": r.table_name,
                "date_col": r.date_col,
                "scope": r.scope,
                "expected_count": r.expected_count,
                "covered_count": r.covered_count,
                "coverage_pct": r.coverage_pct,
                "max_data_date": r.max_data_date,
                "days_stale": r.days_stale,
                "frozen": r.frozen,
            }
            for r in rows
        ]
        sql = """
            INSERT INTO data_freshness_snapshots
                (run_date, table_name, date_col, scope, expected_count,
                 covered_count, coverage_pct, max_data_date, days_stale, frozen)
            VALUES
                (%(run_date)s, %(table_name)s, %(date_col)s, %(scope)s,
                 %(expected_count)s, %(covered_count)s, %(coverage_pct)s,
                 %(max_data_date)s, %(days_stale)s, %(frozen)s)
            ON CONFLICT (run_date, table_name) DO UPDATE SET
                date_col       = EXCLUDED.date_col,
                scope          = EXCLUDED.scope,
                expected_count = EXCLUDED.expected_count,
                covered_count  = EXCLUDED.covered_count,
                coverage_pct   = EXCLUDED.coverage_pct,
                max_data_date  = EXCLUDED.max_data_date,
                days_stale     = EXCLUDED.days_stale,
                frozen         = EXCLUDED.frozen
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def latest_snapshot(self) -> list[dict]:
        sql = """
            SELECT table_name, date_col, scope, expected_count, covered_count,
                   coverage_pct, max_data_date, days_stale, frozen
              FROM data_freshness_snapshots
             WHERE run_date = (SELECT MAX(run_date) FROM data_freshness_snapshots)
             ORDER BY frozen DESC, coverage_pct ASC NULLS FIRST, table_name
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_data_freshness_repository.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/data_freshness_repository.py tests/integration/storage/test_data_freshness_repository.py
git commit -m "feat(monitor): data_freshness_snapshots repository"
```

### Task C3: Freshness monitor job + scheduler registration

**Files:**
- Create: `src/uw_scan/worker/jobs/data_freshness_monitor.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/worker/test_data_freshness_monitor_job.py`

**Interfaces:**
- Consumes: `compute_freshness`, `MONITORED_TABLES`, `DataFreshnessRepository`, `repo.list_watchlist_cards()`.
- Produces: `data_freshness_monitor(*, repo, settings, today) -> dict[str, int]` (keys `tables, frozen, persisted`).

- [ ] **Step 1: Write the failing test**

Create `tests/integration/worker/test_data_freshness_monitor_job.py`:

```python
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor


def test_monitor_persists_and_flags_frozen(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    g.upsert_rows("NVDA", [{
        "trade_date": date(2026, 5, 20), "call_gex": 1.0, "put_gex": -1.0,
        "call_delta": 1.0, "put_delta": -1.0, "payload": {},
    }])
    # Stub settings — the job reads only db_schema.
    settings = SimpleNamespace(db_schema=repo._schema)
    summary = data_freshness_monitor(repo=repo, settings=settings, today=date(2026, 6, 25))
    assert summary["persisted"] >= 1
    latest = DataFreshnessRepository(repo.conn, schema=repo._schema).latest_snapshot()
    g_row = next(r for r in latest if r["table_name"] == "greek_exposure_daily")
    assert g_row["frozen"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_freshness_monitor_job.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.worker.jobs.data_freshness_monitor`.

- [ ] **Step 3: Write the job**

Create `src/uw_scan/worker/jobs/data_freshness_monitor.py`:

```python
"""Nightly data-date freshness monitor (prevention layer for silent freezes).

Computes per-table data-date staleness + scope-aware coverage, persists a daily
snapshot, and WARN-logs any frozen / low-coverage table so the next silent
freeze surfaces the morning it starts.
"""

from __future__ import annotations

import logging
from datetime import date

from uw_scan.config import Settings
from uw_scan.reports.data_freshness import MONITORED_TABLES, compute_freshness
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

LOW_COVERAGE_PCT = 0.5  # ponytail: half the expected scope missing = alert-worthy


def data_freshness_monitor(*, repo: Repository, settings: Settings, today: date) -> dict[str, int]:
    active = [c.ticker for c in repo.list_watchlist_cards()]
    rows = compute_freshness(repo.conn, settings.db_schema, MONITORED_TABLES, active, today)

    frozen = 0
    for r in rows:
        if r.frozen:
            frozen += 1
            logger.warning(
                "data_freshness: %s FROZEN — newest data %s is %s days stale (cov %.0f%%)",
                r.table_name, r.max_data_date, r.days_stale,
                (r.coverage_pct or 0) * 100,
            )
        elif r.coverage_pct is not None and r.coverage_pct < LOW_COVERAGE_PCT:
            logger.warning(
                "data_freshness: %s LOW COVERAGE — %d/%d tickers (%.0f%%) at newest date %s",
                r.table_name, r.covered_count, r.expected_count,
                r.coverage_pct * 100, r.max_data_date,
            )

    persisted = DataFreshnessRepository(repo.conn, schema=settings.db_schema).upsert_snapshot(today, rows)
    summary = {"tables": len(rows), "frozen": frozen, "persisted": persisted}
    logger.info(
        "data_freshness_monitor complete tables=%d frozen=%d persisted=%d",
        summary["tables"], summary["frozen"], summary["persisted"],
    )
    return summary
```

- [ ] **Step 4: Register the job in the scheduler**

In `src/uw_scan/worker/scheduler.py`, inside the `if _is_primary_worker(settings):` block:

```python
    def _data_freshness_monitor() -> None:
        from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor

        with _repo(settings) as repo:
            data_freshness_monitor(
                repo=repo,
                settings=settings,
                today=datetime.now(ZoneInfo(settings.rth_tz)).date(),
            )
```

```python
            sched.add_job(
                _data_freshness_monitor,
                CronTrigger.from_crontab("0 21 * * 0-4", timezone=settings.rth_tz),
                id="data_freshness_monitor",
                name="Data-date freshness monitor (prevention)",
                max_instances=1,
                coalesce=True,
            )
```

> Cron `0 21` (after all nightly writers — vol rollup, surface capture, vrp, greek re-derive — have run) so the audit sees the freshest data each day.

- [ ] **Step 5: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_data_freshness_monitor_job.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/jobs/data_freshness_monitor.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_data_freshness_monitor_job.py
git commit -m "feat(monitor): nightly data-date freshness monitor job"
```

### Task C4: Surface freshness on `/api/health`

**Files:**
- Modify: `src/uw_scan/api/routers/health.py` (the `HealthResponse` model + the `health()` handler both live here)
- Test: `tests/integration/api/test_health_freshness.py`

**Interfaces:**
- Consumes: `DataFreshnessRepository.latest_snapshot()`.
- Produces: `HealthResponse` gains an optional `freshness: HealthFreshness | None = None` field; the `/api/health` JSON gains `freshness: {"as_of": <run_date|null>, "frozen": [table_name,...], "tables": [<rows>]}`.

- [ ] **Step 1: Confirm the health response shape (verified)**

`HealthResponse` is a Pydantic model defined **in** `src/uw_scan/api/routers/health.py` (line ~32), and `@router.get("/health", response_model=HealthResponse)` `def health(...) -> HealthResponse`. The handler has several `return HealthResponse(...)` sites: an early db-down/error return (~282) and the main healthy return (later, ~485). The `freshness` field is **optional with a default of `None`**, so only the healthy return must populate it; the error returns inherit the default. Do **not** mutate a dict — there is no dict.

- [ ] **Step 2: Write the failing test**

Create `tests/integration/api/test_health_freshness.py`. Match the existing health API test style (FastAPI `TestClient` over the app with the test DB). If the repo already has an `api` test fixture/client, reuse it; otherwise model it on the nearest existing `tests/integration/api/test_health*.py`.

```python
from __future__ import annotations

from datetime import date

from uw_scan.reports.data_freshness import FreshnessRow
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository


def test_health_exposes_freshness(api_client, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    DataFreshnessRepository(repo.conn, schema=repo._schema).upsert_snapshot(
        date(2026, 6, 25),
        [FreshnessRow("vrp_daily", "market_date", "watchlist", 100, 9, 0.09,
                      date(2026, 5, 22), 34, True)],
    )
    resp = api_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "freshness" in body
    assert "vrp_daily" in body["freshness"]["frozen"]
```

> If the test suite has no ready `api_client` fixture wired to the seeded DB, fall back to a direct unit test of the assembler function that builds the `freshness` block from a `DataFreshnessRepository`, and skip the HTTP layer. The behavior under test is "frozen tables appear in the health payload."

- [ ] **Step 3: Run the test to verify it fails**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_health_freshness.py -v`
Expected: FAIL — `KeyError: 'freshness'` (or fixture error to resolve in Step 2).

- [ ] **Step 4: Add the `freshness` field to the model + populate the healthy return**

In `src/uw_scan/api/routers/health.py`, near the `HealthResponse` definition, add two small models and the optional field. Ensure `from datetime import date` is imported (the file already imports `datetime`).

```python
class HealthFreshnessRow(BaseModel):
    table_name: str
    date_col: str
    scope: str
    expected_count: int
    covered_count: int
    coverage_pct: float | None = None
    max_data_date: date | None = None
    days_stale: int | None = None
    frozen: bool


class HealthFreshness(BaseModel):
    as_of: date | None = None
    frozen: list[str] = []
    tables: list[HealthFreshnessRow] = []
```

Add the field to `HealthResponse` (additive, optional — every existing return path keeps working):

```python
class HealthResponse(BaseModel):
    # ... existing fields ...
    freshness: HealthFreshness | None = None
```

**Build the block ONCE after the DB-up check, then pass it to EVERY DB-up return.** `health()` has four `HealthResponse(...)` returns while the DB is up — "no successful full scan yet" (~485), "N expected full scans missed" (~504), "record coverage below expected" (~517), and the final healthy one (~529). Freshness is an operator surface; it must **not** vanish when health is already degraded. Build it right after the `SELECT 1` DB-up check succeeds (just before the sidebar fields are assembled, ~line 292), then add `freshness=freshness` to **all four** of those returns (the early `db_status == "down"` return at ~282 leaves it defaulted to `None`):

```python
    # --- freshness block (built once; passed to every DB-up return) ---
    from uw_scan.storage.data_freshness_repository import DataFreshnessRepository

    _fr_rows = DataFreshnessRepository(repo.conn, schema=settings.db_schema).latest_snapshot()
    _as_of = None
    with repo.conn.cursor() as _cur:
        _cur.execute(
            f"SELECT MAX(run_date) FROM {settings.db_schema}.data_freshness_snapshots"
        )
        _row = _cur.fetchone()
        _as_of = _row[0] if _row else None
    # latest_snapshot() rows carry exactly the 9 HealthFreshnessRow keys, so
    # HealthFreshnessRow(**r) maps 1:1.
    freshness = HealthFreshness(
        as_of=_as_of,
        frozen=[r["table_name"] for r in _fr_rows if r["frozen"]],
        tables=[HealthFreshnessRow(**r) for r in _fr_rows],
    )
```

Then add `freshness=freshness,` to each of the four DB-up `HealthResponse(...)` constructors (485, 504, 517, 529).

> The new field is additive and surfaces in `web/lib/types.ts` after `npm run gen:types`. The OpenAPI snapshot test will need regeneration — see the project's "generated files are alphabetically frozen" note: add surgically, regenerate the snapshot with the repo's tooling, don't hand-reorder.

- [ ] **Step 5: Run the test to verify it passes**

Run: `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_health_freshness.py -v`
Expected: PASS.

- [ ] **Step 6: Regenerate types if the health response is typed, then commit**

```bash
cd web && npm run gen:types && cd ..   # only if the health model changed
git add src/uw_scan/api/routers/health.py tests/integration/api/test_health_freshness.py web/lib/types.ts
git commit -m "feat(monitor): expose data freshness on /api/health"
```

---

## Workstream D — finalize

### Task D1: CHANGELOG + docs

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `CLAUDE.md`, `src/uw_scan/worker/CLAUDE.md`

- [ ] **Step 1: Add the `[Unreleased]` CHANGELOG entry**

Open `CHANGELOG.md`, find the `## [Unreleased]` section (create it above the latest version heading if absent), and add:

```markdown
### Fixed
- **#180 intraday-buckets coverage** — the primary-only OI-mover intraday refresh
  wrongly inherited the per-worker shard filter, so ~half the watchlist
  (TSLA/NVDA/MSFT/GOOGL/META/AVGO …) was never fetched and its TAPE column stayed
  blank. The job now covers the full watchlist; per-outcome counters self-report
  future gaps. One-shot backfill: `scripts/backfill/intraday_buckets_backfill.py`.
- **#179 single-name greek_exposure_daily freeze** — single-name daily GEX/DEX
  had no recurring writer (index-only by design) and froze at 2026-05-20. A new
  nightly DB→DB job re-derives it from `exposures_by_expiry_strike` (zero UW),
  validated against the UW-fed SPX/SPY/TLT aggregate. Backfill:
  `scripts/backfill/greek_exposure_rederive_backfill.py`.

### Added
- **Data-date freshness monitor** — nightly job records per-table newest data
  date + scope-aware watchlist coverage into `data_freshness_snapshots`, flags
  freezes, WARN-logs, and surfaces a `freshness` block on `/api/health`.
  Complements `list_record_health` (which only sees write-recency and skips
  no-timestamp tables).
```

- [ ] **Step 2: Add "Where to look" rows**

In `CLAUDE.md`'s "Where to look first" table, add:

```markdown
| Single-name greek_exposure_daily re-derive (#179) | `storage/greek_exposure_repository.py` (`select_rederived_rows`/`compare_to_stored`) + `worker/jobs/greek_exposure_rederive.py` + migration `086`; nightly 18:30 ET (primary). DB→DB, zero UW |
| Data-date freshness monitor (prevention) | `reports/data_freshness.py` (`MONITORED_TABLES`, `compute_freshness`) + `storage/data_freshness_repository.py` + `worker/jobs/data_freshness_monitor.py` + migration `087`; nightly 21:00 ET (primary); `/api/health` `freshness` block |
| Intraday OI-mover refresh (#180) | `worker/jobs/option_intraday_jobs.py` + scheduler `_intraday_oi_refresh` (primary-only, `ticker_filter=None`); backfill `scripts/backfill/intraday_buckets_backfill.py` |
```

In `src/uw_scan/worker/CLAUDE.md`'s schedule table, add:

```markdown
| `greek_exposure_rederive` | cron | `30 18 * * 0-4` (primary; DB→DB single-name GEX/DEX re-derive, zero UW) |
| `data_freshness_monitor` | cron | `0 21 * * 0-4` (primary; per-table data-date freshness audit) |
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md CLAUDE.md src/uw_scan/worker/CLAUDE.md
git commit -m "docs: changelog + where-to-look for data-quality coverage PR"
```

---

## Final verification (before opening the PR)

- [ ] **Full test run** — `UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_greek_rederive.py tests/integration/storage/test_data_freshness_repository.py tests/integration/reports/test_data_freshness.py tests/integration/worker/test_intraday_oi_refresh.py tests/integration/worker/test_greek_exposure_rederive_job.py tests/integration/worker/test_data_freshness_monitor_job.py tests/integration/api/test_health_freshness.py -v`
- [ ] **Migration idempotency** — run `bash scripts/migrate.sh` twice against the local DB; second run is a no-op (no errors).
- [ ] **Reproduce the full `lint + unit` CI job locally** — not just ruff+pytest: also Guardrail 2 (`_lint_except.py`), `version_sync_check`, the guardrail greps, and the migration-prefix check. The `lint + unit` job runs more than ruff+pytest; reproduce the **whole** job before relying on green (see memory: "Check CI green before merging").
- [ ] **Confirm no UW calls in B/C** — grep the two new jobs + the rederive backfill for any `UwClient`/`fetch_`/`client.` usage; there must be none (DB→DB only).
- [ ] **Module size** — confirm no new file exceeds the 500-line target; none should.

---

## Self-Review (completed)

**Spec coverage:** Decision-1 (#179) → B1–B3. Decision-2 (#180) → A1–A2. Decision-3 (prevention) → C1–C4. CHANGELOG/docs (feature-PR rule) → D1. Validation/basis-safety guard (Decision-1) → B1 `compare_to_stored` + B2 WARN. Canonical-run-per-date (double-count guard) → B1 `select_rederived_rows` CTE + `test_rederive_sums_strikes_per_canonical_run`. Scope-aware coverage (no-cry-wolf) → C1 `MonitoredTable.scope` + `test_subset_scope_uses_named_denominator`. health.py blind-spot rationale → embedded in Decision-3 and the C1 module docstring.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". Every table/column the plan seeds or queries was verified against migrations during review-cycle Pass 1: `oi_change_events(run_id, underlying_symbol, option_symbol, curr_date, rnk, volume, avg_price)` (mig 001), `exposures_by_expiry_strike` (mig 001), `greek_exposure_daily` GENERATED nets (mig 039), `scan_runs.aggregates` JSONB (mig 007), `option_intraday_buckets` (mig 049, ticker-less). `HealthResponse` confirmed a Pydantic model in `health.py:32`. The only remaining *adapt-on-read* instructions are non-fabricating: the exact healthy-return line in `health()` (~485) and the presence of an `api_client` integration fixture (C4 Step 2 gives a unit-test fallback if absent). The C1 date-column autodetect is robust by construction — an unknown column yields a `"?"` row, never a wrong number.

**Type consistency:** `refresh_intraday_for_top_oi_movers` summary keys match between A1 impl and test. `select_rederived_rows`/`compare_to_stored`/`insert_validation_rows` signatures match between B1 impl, B2 job, and tests. `FreshnessRow`/`MonitoredTable` fields match across C1/C2/C3/C4. Cron times are mutually ordered (vol rollup 18:00 → greek re-derive 18:30 → surface 19:00 → freshness monitor 21:00) so each reads fresh upstream data.
