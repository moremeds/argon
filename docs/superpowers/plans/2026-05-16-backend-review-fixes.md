# Backend Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the high-confidence findings from `docs/reviews/2026-05-16-backend-code-review.md` (B1, B2, R1, N3, N4) and the measured perf bottleneck (A2 / N6) in the watchlist query. Defer findings whose severity ranking I downgraded after EXPLAIN ANALYZE measurements (P1, P5) and findings that need product/UX discussion (N1, N2, A1).

**Architecture:** Six self-contained, independently shippable changes. The biggest is B1, which now uses a claim-token approach (per codex review feedback) — the original status-only guard cannot distinguish "this same row, my old claim" from "this same row, someone else's new claim" because both look like `status='running'`. Each task is its own commit, each commit is reviewable in isolation.

**Tech Stack:** Python 3.13 / FastAPI / psycopg 3 / Postgres / pytest-postgresql / `uv` for Python execution. Migrations are plain `.sql` files in `src/uw_scan/storage/migrations/` applied lexically by `scripts/migrate.sh`. `scripts/migrate.sh` runs each file with `psql -f` in autocommit (no `--single-transaction`), so `CREATE INDEX CONCURRENTLY` and `DROP INDEX CONCURRENTLY` are safe.

**Out of scope:**
- Modularization (separate plan if desired — see `docs/reviews/2026-05-16-backend-modularization-and-reuse.md`)
- A1 (per-scan ETF fetch caching — needs design)
- Materializing a `ticker_metadata` table that would supersede A2 (deferred — A2's index fix should buy enough headroom for now)
- Any FE changes

**Standing rules respected:**
- All new SQL migrations idempotent (`CREATE INDEX CONCURRENTLY IF NOT EXISTS`, `DROP INDEX CONCURRENTLY IF EXISTS`, `ADD COLUMN IF NOT EXISTS`)
- No `Co-Authored-By: Claude` trailers in commits
- `uv run pytest` only
- Repository pattern preserved — no raw SQL in routers
- Tests use `pytest-postgresql` via the existing `seeded_db_with_cards` fixture, never mocks

**Codex review applied (2026-05-16):** Codex consult identified that the original B1 status-guard fix was logically wrong (race still fires when worker B has reclaimed under a new running session), the R1 sort-key tuple inverted with `reverse=True` (would put missing rows first instead of last), and the original B1/R1 test signatures didn't match the real code. All three are addressed in this revision.

---

## Task ordering

Codex's recommended order (adopted):

1. **N4** — drop unreachable asserts (warm-up, no risk)
2. **B2** — fix throughput provider filter (small, isolated)
3. **B1** — claim-token migration + repo/worker/test updates (largest task, biggest blast radius — do early so it gets the most testing)
4. **R1** — `_to_decimal` returns `None` (correctness, scoped to one file)
5. **N3** — drop redundant `idx_jobs_queued` (trivial migration)
6. **A2** — covering indexes for the watchlist query's JSONB joins (perf migration)
7. **Final verification**

Migration numbers reflect this order: B1 = 025, N3 = 026, A2 = 027.

---

## Task 1: N4 — Remove unreachable asserts in `get_throughput_summary`

**Why:** `SELECT count(*)` and `SELECT avg(...)` always return one row, so `cur.fetchone() is not None` is always true. The asserts add noise and teach a wrong invariant.

**Files:**
- Modify: `src/uw_scan/storage/repository.py:534, 549, 562` (line numbers may have drifted ±5 since the review)

- [ ] **Step 1: Locate the three assert lines**

Run: `grep -n "assert request_row\|assert scan_row\|assert queue_row" src/uw_scan/storage/repository.py`
Expected: three matches; capture the actual line numbers for the next step.

- [ ] **Step 2: Delete the three assert lines**

Use the Edit tool, three separate edits. For each, the pattern is the line itself preceded by its `cur.fetchone()` line for uniqueness.

```python
# OLD (after the first cursor.execute)
            request_row = cur.fetchone()
            assert request_row is not None

# NEW
            request_row = cur.fetchone()
```

```python
# OLD (after the second cursor.execute)
            scan_row = cur.fetchone()
            assert scan_row is not None

# NEW
            scan_row = cur.fetchone()
```

```python
# OLD (after the third cursor.execute)
            queue_row = cur.fetchone()
            assert queue_row is not None

# NEW
            queue_row = cur.fetchone()
```

- [ ] **Step 3: Verify no behavior change**

Run: `uv run pytest tests/integration/api/test_health.py tests/integration/storage/test_provider_usage_repository.py -v`
Expected: all tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/repository.py
git commit -m "refactor(repo): drop unreachable asserts in get_throughput_summary

count(*) and avg() always return one row; the asserts can never trip.
Removes noise and a false invariant."
```

---

## Task 2: B2 — `get_throughput_summary` returns `None` for non-UW provider

**Why:** `avg_scan_duration_seconds` and `queue_drain_rate_per_minute` are derived from `scan_runs` and `jobs`, both of which only ever hold UW work (no provider column). If a caller passes `provider='massive'`, the function returns UW values labelled as massive throughput. The FE doesn't currently call `?source=massive`, but if it ever does, the dashboard would mislead.

**Files:**
- Test: `tests/integration/storage/test_provider_usage_repository.py` (existing — append a test)
- Modify: `src/uw_scan/storage/repository.py:108-115` (`ThroughputSummaryRow` dataclass — make `queue_drain_rate_per_minute` `float | None`)
- Modify: `src/uw_scan/storage/repository.py:515-572` (`get_throughput_summary`)

- [ ] **Step 1: Confirm OpenAPI snapshot already has the field as nullable**

Run: `grep -A 6 "queue_drain_rate_per_minute" tests/integration/api/openapi.snapshot.json | head -10`
Expected: shows `"anyOf": [{"type": "number"}, {"type": "null"}]`. If so, no FE regen will be needed (saves a step).

- [ ] **Step 2: Inspect the current `seeded_db_with_cards` fixture to understand seed state**

Run: `grep -nA 30 "def seeded_db_with_cards\|def seeded_db_empty_cards" tests/integration/conftest.py | head -80`
Note whether the fixture seeds any `external_api_requests` rows for the `massive` provider. If not, the new test will need to insert one.

- [ ] **Step 3: Write the failing test**

Open `tests/integration/storage/test_provider_usage_repository.py`. Add at the bottom of the file:

```python
def test_get_throughput_summary_returns_none_for_non_uw_provider(seeded_db_with_cards):
    """B2: scan_runs and jobs are UW-only data sources. When the caller asks
    about a provider that isn't UW (e.g., 'massive'), don't return UW values
    labelled as that provider's. Return None for the UW-derived fields."""
    from datetime import UTC, datetime, timedelta

    repo = seeded_db_with_cards
    end = datetime.now(UTC)
    start = end - timedelta(minutes=15)

    # Seed a real massive request and a UW scan_run so the test proves the
    # provider partitioning rather than just returning None for an empty window.
    # Note: insert_external_api_request uses `started_at`/`finished_at` (not
    # `request_started_at`/`request_finished_at`) and requires `path`.
    massive_ts = end - timedelta(minutes=5)
    repo.insert_external_api_request(
        provider="massive",
        endpoint_key="/agg/intraday",
        method="GET",
        path="/v2/aggs/ticker/AAPL/range/1/minute/2026-05-16/2026-05-16",
        ticker="AAPL",
        status_code=200,
        status_family="2xx",
        started_at=massive_ts,
        finished_at=massive_ts,
        latency_ms=42,
        attempt=1,
        job_name="spot_refresh",
    )
    # Also seed a UW scan_run that completes inside the window — this ensures
    # avg_scan_duration_seconds would have a non-None UW value to be 'leaked'
    # if the provider filter were ignored.
    uw_run = repo.insert_scan_run("AAPL", notes="full_scan")
    repo.finish_scan_run(uw_run, status="ok")

    summary = repo.get_throughput_summary("massive", start, end)

    assert summary.avg_scan_duration_seconds is None, (
        "avg_scan_duration_seconds is derived from scan_runs (UW-only) — "
        "must not be returned under provider='massive'"
    )
    assert summary.queue_drain_rate_per_minute is None, (
        "queue_drain_rate_per_minute is derived from jobs (UW rescans only) — "
        "must not be returned under provider='massive'"
    )
    # The HTTP-request-derived fields should still be reported for massive.
    assert summary.requests_per_minute is not None
    assert summary.http_429 is not None
```

> **Note:** the `insert_external_api_request` signature above is taken from the existing repository method — verify keyword parity with `grep -A 20 "def insert_external_api_request" src/uw_scan/storage/repository.py` before writing the test, in case the signature has drifted since the review.

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_provider_usage_repository.py::test_get_throughput_summary_returns_none_for_non_uw_provider -v`
Expected: FAIL — both `avg_scan_duration_seconds` and `queue_drain_rate_per_minute` come back non-None because the queries don't filter by provider.

- [ ] **Step 5: Update the `ThroughputSummaryRow` dataclass to allow `None` on `queue_drain_rate_per_minute`**

Find the dataclass — `grep -n "class ThroughputSummaryRow" src/uw_scan/storage/repository.py`. Edit:

```python
# OLD
@dataclass(frozen=True)
class ThroughputSummaryRow:
    window_minutes: float
    requests_per_minute: float
    http_429: int
    avg_scan_duration_seconds: float | None
    queue_drain_rate_per_minute: float

# NEW
@dataclass(frozen=True)
class ThroughputSummaryRow:
    window_minutes: float
    requests_per_minute: float
    http_429: int
    avg_scan_duration_seconds: float | None
    queue_drain_rate_per_minute: float | None
```

- [ ] **Step 6: Skip the UW-derived sub-queries when the caller asks about a non-UW provider**

Edit the body of `get_throughput_summary` (around lines 515-572 — verify with grep first). The whole function becomes:

```python
    def get_throughput_summary(
        self, provider: str | None, start: datetime, end: datetime
    ) -> ThroughputSummaryRow:
        provider_filter = None if provider in (None, "all") else provider
        # scan_runs and jobs do not carry a provider column — both are UW-only
        # sources. When the caller asks about a non-UW provider, return None
        # for those fields rather than UW values mislabelled (review 2026-05-16, B2).
        is_uw_scoped = provider_filter is None or provider_filter == "uw"

        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  count(*)::int AS total_requests,
                  count(*) FILTER (WHERE status_code = 429)::int AS http_429,
                  min(request_started_at) AS first_request_at
                FROM {self._schema}.external_api_requests
                WHERE request_started_at >= %s
                  AND request_started_at < %s
                  AND (%s::text IS NULL OR provider = %s)
                """,
                (start, end, provider_filter, provider_filter),
            )
            request_row = cur.fetchone()

            scan_avg: float | None = None
            scan_first: datetime | None = None
            if is_uw_scoped:
                cur.execute(
                    f"""
                    SELECT avg(extract(epoch FROM finished_at - started_at))
                         , min(started_at)
                    FROM {self._schema}.scan_runs
                    WHERE finished_at >= %s
                      AND finished_at < %s
                      AND finished_at IS NOT NULL
                      AND started_at IS NOT NULL
                      AND (notes IS DISTINCT FROM 'flow_data_refresh')
                    """,
                    (start, end),
                )
                scan_row = cur.fetchone()
                scan_avg = _nullable_float(scan_row[0]) if scan_row else None
                scan_first = scan_row[1] if scan_row else None

            queue_count: int | None = None
            queue_first: datetime | None = None
            if is_uw_scoped:
                cur.execute(
                    f"""
                    SELECT count(*)::int, min(requested_at)
                    FROM {self._schema}.jobs
                    WHERE finished_at >= %s
                      AND finished_at < %s
                      AND status IN ('done', 'failed')
                    """,
                    (start, end),
                )
                queue_row = cur.fetchone()
                queue_count = int(queue_row[0]) if queue_row else 0
                queue_first = queue_row[1] if queue_row else None

        total_requests = int(request_row[0])
        active_starts = [
            request_row[2],
            scan_first,
            queue_first,
        ]
        first_activity = min(
            (ts for ts in active_starts if ts is not None), default=start
        )
        active_start = max(start, first_activity)
        active_window_minutes = max(
            (end - active_start).total_seconds() / 60.0, 1 / 60
        )
        return ThroughputSummaryRow(
            window_minutes=active_window_minutes,
            requests_per_minute=total_requests / active_window_minutes,
            http_429=int(request_row[1]),
            avg_scan_duration_seconds=scan_avg,
            queue_drain_rate_per_minute=(
                queue_count / active_window_minutes if queue_count is not None else None
            ),
        )
```

- [ ] **Step 7: Run the new test + the existing health/throughput suite**

Run: `uv run pytest tests/integration/storage/test_provider_usage_repository.py tests/integration/api/test_health.py -v`
Expected: all PASS, including the new one.

- [ ] **Step 8: Confirm OpenAPI snapshot does not need regen**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: PASS without changes (the field was already nullable in the snapshot, per Step 1).

If it does fail (snapshot mismatch), regenerate via the project's standard process — but per the Step 1 verification this should not happen.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_provider_usage_repository.py
git commit -m "fix(health): return None for UW-derived fields under non-UW provider

avg_scan_duration_seconds and queue_drain_rate_per_minute come from
scan_runs and jobs respectively, both of which only hold UW work.
Returning their values under provider='massive' would mislead any
operator who toggled the source filter.

Tracks B2 from docs/reviews/2026-05-16-backend-code-review.md."
```

---

## Task 3: B1 — Claim-token guard against the requeue race

**Why (revised after codex review):** Original plan used `WHERE status='running'` only. Codex correctly pointed out this is insufficient: when worker A's stale-requeue flips a row back to `queued` and worker B reclaims it, the row is `running` again. Worker A's late `mark_job_done` then matches the status guard and clobbers worker B's claim. The fix needs a per-claim token: each claim writes a fresh UUID; mark/fail only update if the token matches the one the worker holds.

**Files:**
- Create: `src/uw_scan/storage/migrations/025_jobs_claim_token.sql`
- Modify: `src/uw_scan/storage/repository.py:67-75` (`JobRow` dataclass)
- Modify: `src/uw_scan/storage/repository.py:2789-2807` (`claim_next_queued_job`)
- Modify: `src/uw_scan/storage/repository.py:2809-2822` (`requeue_stale_running_jobs` — clear token)
- Modify: `src/uw_scan/storage/repository.py:2824-2833` (`mark_job_done`)
- Modify: `src/uw_scan/storage/repository.py:2835-2844` (`mark_job_failed`)
- Modify: `src/uw_scan/storage/repository.py` — `get_job` (around line 3116) to also project `claim_token`
- Modify: `src/uw_scan/worker/jobs/rescan_loop.py:38, 42` (pass `claim_token` through)
- Test: `tests/integration/storage/test_repository_jobs.py` (new file)

- [ ] **Step 1: Verify the only callers of `mark_job_done` / `mark_job_failed`**

Run: `grep -rn "mark_job_done\|mark_job_failed" src/ tests/ 2>/dev/null | grep -v __pycache__`
Expected: 2 production call sites (`worker/jobs/rescan_loop.py:38, 42`) + the repository definitions + any existing tests. Confirm no other production caller before changing the signature.

- [ ] **Step 2: Write the migration**

Create `src/uw_scan/storage/migrations/025_jobs_claim_token.sql`:

```sql
-- 025_jobs_claim_token.sql — add per-claim token so mark_job_done/failed can
-- detect when a slow worker tries to update a row that has been requeued and
-- reclaimed under a fresh attempt.
--
-- Background: review 2026-05-16-backend-code-review.md B1 + codex review.
-- The previous status='running' guard is insufficient because a requeued+
-- reclaimed row is also 'running' under a different worker.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, no DEFAULT change for existing rows
-- (existing 'running' rows get a backfill UUID below).
--
-- Concurrency: ALTER TABLE ... ADD COLUMN IF NOT EXISTS without a non-null
-- default is metadata-only and fast in PG 11+. The backfill UPDATE is bounded
-- by the small set of currently-running jobs (typically <10 rows in practice).

SET search_path TO uw_scan, public;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

ALTER TABLE uw_scan.jobs
  ADD COLUMN IF NOT EXISTS claim_token UUID;

-- Backfill any rows currently 'running' so the next mark_job_done/failed call
-- has something to match. Idempotent: only touches rows where claim_token IS
-- NULL, so re-running is a no-op once filled.
UPDATE uw_scan.jobs
SET claim_token = gen_random_uuid()
WHERE status = 'running' AND claim_token IS NULL;
```

- [ ] **Step 3: Apply the migration**

Run: `bash scripts/migrate.sh 2>&1 | tail -5`
Expected: `Applying src/uw_scan/storage/migrations/025_jobs_claim_token.sql...` then `All migrations applied.`

- [ ] **Step 4: Verify the column exists (skip if no local DB)**

Run: `psql -d option_wizard -c "\\d uw_scan.jobs" | grep claim_token`
Expected: `claim_token | uuid |  |  |`.

- [ ] **Step 5: Re-apply the migration to verify idempotency**

Run: `bash scripts/migrate.sh 2>&1 | tail -3`
Expected: succeeds again.

- [ ] **Step 6: Update the `JobRow` dataclass to include `claim_token`**

Edit `src/uw_scan/storage/repository.py:67-75`:

```python
# OLD
@dataclass(frozen=True)
class JobRow:
    id: Any
    ticker: str
    status: str
    run_id: int | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

# NEW
@dataclass(frozen=True)
class JobRow:
    id: Any
    ticker: str
    status: str
    run_id: int | None
    error: str | None
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    claim_token: Any = None  # UUID, set on claim, gates mark_job_done/failed
```

- [ ] **Step 7: Update `claim_next_queued_job` to set + return `claim_token`**

Edit `src/uw_scan/storage/repository.py` around line 2789. Replace:

```python
    def claim_next_queued_job(self) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='running', started_at=NOW()
                WHERE id = (
                  SELECT id FROM {self._schema}.jobs
                  WHERE status='queued'
                  ORDER BY priority DESC, requested_at ASC, id ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING id, ticker, status, run_id, error, requested_at, started_at, finished_at
                """
            )
            row = cur.fetchone()
        self._conn.commit()
        return JobRow(*row) if row else None
```

with:

```python
    def claim_next_queued_job(self) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='running',
                    started_at=NOW(),
                    claim_token=gen_random_uuid()
                WHERE id = (
                  SELECT id FROM {self._schema}.jobs
                  WHERE status='queued'
                  ORDER BY priority DESC, requested_at ASC, id ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                RETURNING id, ticker, status, run_id, error,
                          requested_at, started_at, finished_at, claim_token
                """
            )
            row = cur.fetchone()
        self._conn.commit()
        return JobRow(*row) if row else None
```

- [ ] **Step 8: Update `requeue_stale_running_jobs` to clear `claim_token`**

Edit `src/uw_scan/storage/repository.py` around line 2809. Replace:

```python
    def requeue_stale_running_jobs(self, older_than: timedelta) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='queued', started_at=NULL, error=NULL
                WHERE status='running'
                  AND started_at < NOW() - %s
                """,
                (older_than,),
            )
            count = cur.rowcount
        self._conn.commit()
        return count
```

with:

```python
    def requeue_stale_running_jobs(self, older_than: timedelta) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='queued',
                    started_at=NULL,
                    error=NULL,
                    claim_token=NULL
                WHERE status='running'
                  AND started_at < NOW() - %s
                """,
                (older_than,),
            )
            count = cur.rowcount
        self._conn.commit()
        return count
```

> Clearing `claim_token` here means the original worker's stored token will no longer match anything when it tries `mark_job_done` — its update is rejected with `rowcount==0` even before the new worker reclaims.

- [ ] **Step 9: Add `claim_token` parameter to `mark_job_done`**

Edit `src/uw_scan/storage/repository.py` around line 2824. Replace:

```python
    def mark_job_done(self, job_id: str, run_id: int) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='done', run_id=%s, finished_at=NOW() WHERE id=%s
                """,
                (run_id, job_id),
            )
        self._conn.commit()
```

with:

```python
    def mark_job_done(self, job_id: str, run_id: int, claim_token: Any) -> None:
        # Claim-token guard against the requeue race (review 2026-05-16, B1):
        # if requeue_stale_running_jobs cleared our token, or another worker
        # has since reclaimed (with a fresh token), our update must be rejected.
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='done', run_id=%s, finished_at=NOW()
                WHERE id=%s AND claim_token=%s
                """,
                (run_id, job_id, claim_token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_job_done lost claim on job_id=%s "
                    "(token mismatch; another worker may have reclaimed)",
                    job_id,
                )
        self._conn.commit()
```

- [ ] **Step 10: Add `claim_token` parameter to `mark_job_failed`**

Edit `src/uw_scan/storage/repository.py` around line 2835. Replace:

```python
    def mark_job_failed(self, job_id: str, error: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='failed', error=%s, finished_at=NOW() WHERE id=%s
                """,
                (error[:2000], job_id),
            )
        self._conn.commit()
```

with:

```python
    def mark_job_failed(self, job_id: str, error: str, claim_token: Any) -> None:
        # Claim-token guard (review 2026-05-16, B1).
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.jobs
                SET status='failed', error=%s, finished_at=NOW()
                WHERE id=%s AND claim_token=%s
                """,
                (error[:2000], job_id, claim_token),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "mark_job_failed lost claim on job_id=%s "
                    "(token mismatch; another worker may have reclaimed)",
                    job_id,
                )
        self._conn.commit()
```

- [ ] **Step 11: Update `get_job` to project `claim_token`**

Find `get_job` — `grep -n "def get_job\b" src/uw_scan/storage/repository.py`. The current implementation likely projects 8 columns; extend it to project the 9th (`claim_token`):

```python
    def get_job(self, job_id: str) -> JobRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, ticker, status, run_id, error,
                       requested_at, started_at, finished_at, claim_token
                FROM {self._schema}.jobs WHERE id=%s
                """,
                (job_id,),
            )
            row = cur.fetchone()
        return JobRow(*row) if row else None
```

> If the existing implementation differs in any other way (e.g., column casing), preserve those differences and only add `claim_token` to the SELECT list.

- [ ] **Step 12: Update the worker to pass `claim_token` through**

Edit `src/uw_scan/worker/jobs/rescan_loop.py:38, 42`:

```python
# OLD (line ~38)
        repo.mark_job_done(str(job.id), report.run_id)

# NEW
        repo.mark_job_done(str(job.id), report.run_id, job.claim_token)
```

```python
# OLD (line ~42)
        repo.mark_job_failed(str(job.id), repr(exc))

# NEW
        repo.mark_job_failed(str(job.id), repr(exc), job.claim_token)
```

- [ ] **Step 13: Write the proper race test**

Create `tests/integration/storage/test_repository_jobs.py`:

```python
"""Tests for the rescan jobs queue repository methods, especially the
late-completer race surfaced by 2026-05-16 review (B1) and the codex
review revision (claim-token approach).

Uses the shared `seeded_db_with_cards` fixture (see tests/integration/conftest.py).
"""

from __future__ import annotations


def test_mark_job_done_no_op_when_job_was_reclaimed(seeded_db_with_cards):
    """B1 race: worker A claims, requeue_stale flips it back, worker B reclaims
    under a fresh claim_token, then worker A finally finishes and tries to mark
    the job done with its OLD token. The mark must be rejected; B's claim
    survives intact."""
    repo = seeded_db_with_cards

    # Worker A claims.
    job_id = repo.enqueue_rescan_job("TSLA")
    job_a = repo.claim_next_queued_job()
    assert job_a is not None
    token_a = job_a.claim_token
    assert token_a is not None

    # Stale requeue clears the token.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.jobs SET started_at=NOW() - INTERVAL '31 minutes' WHERE id=%s",
            (job_id,),
        )
    repo.conn.commit()
    requeued = repo.requeue_stale_running_jobs(__import__("datetime").timedelta(minutes=30))
    assert requeued == 1

    # Worker B reclaims under a fresh token.
    job_b = repo.claim_next_queued_job()
    assert job_b is not None
    assert job_b.id == job_a.id  # same row
    assert job_b.claim_token != token_a  # new token

    # Worker A's late mark_job_done with its OLD token must be a no-op.
    stale_run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(stale_run_id, status="ok")
    repo.mark_job_done(job_id, stale_run_id, token_a)

    job_after_a = repo.get_job(job_id)
    assert job_after_a is not None
    assert job_after_a.status == "running", "B's claim was overwritten"
    assert job_after_a.claim_token == job_b.claim_token, (
        "B's token was overwritten"
    )
    assert job_after_a.run_id is None or job_after_a.run_id != stale_run_id, (
        "stale run_id was written"
    )

    # Worker B's mark_job_done with the CURRENT token succeeds.
    new_run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(new_run_id, status="ok")
    repo.mark_job_done(job_id, new_run_id, job_b.claim_token)

    final = repo.get_job(job_id)
    assert final is not None
    assert final.status == "done"
    assert final.run_id == new_run_id


def test_mark_job_failed_no_op_when_token_mismatch(seeded_db_with_cards):
    """Mirror of the above for mark_job_failed."""
    repo = seeded_db_with_cards

    job_id = repo.enqueue_rescan_job("TSLA")
    job_a = repo.claim_next_queued_job()
    assert job_a is not None

    # Simulate stale requeue + B reclaim.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.jobs SET started_at=NOW() - INTERVAL '31 minutes' WHERE id=%s",
            (job_id,),
        )
    repo.conn.commit()
    repo.requeue_stale_running_jobs(__import__("datetime").timedelta(minutes=30))
    job_b = repo.claim_next_queued_job()
    assert job_b is not None

    # A's late mark_job_failed with the OLD token is rejected.
    repo.mark_job_failed(job_id, "boom from A", job_a.claim_token)

    after = repo.get_job(job_id)
    assert after is not None
    assert after.status == "running"
    assert after.error is None or "boom from A" not in (after.error or "")
    assert after.claim_token == job_b.claim_token
```

> **Note:** if the project's coding style prefers explicit `from datetime import timedelta` rather than `__import__`, refactor accordingly. Inline `__import__` is used here only to keep the test self-contained for the example; the real test should follow the surrounding file's import style.

- [ ] **Step 14: Run the new tests**

Run: `uv run pytest tests/integration/storage/test_repository_jobs.py -v`
Expected: both PASS.

- [ ] **Step 15: Run the existing job-related tests to confirm no regression**

Run: `uv run pytest tests/integration/storage/test_repository_watchlist.py tests/integration/worker/test_worker_jobs.py -v`
Expected: all PASS, including the existing `test_rescan_tick_recovers_stale_running_job` (which simulates a single-worker recovery — the test claims the job, marks it stale, calls `rescan_tick`, which requeues it, claims it again under a fresh token, and successfully marks it done with that fresh token).

- [ ] **Step 16: Run the full unit test suite**

Run: `uv run pytest tests/ --ignore=tests/integration -q`
Expected: passes at baseline.

- [ ] **Step 17: Commit**

```bash
git add src/uw_scan/storage/migrations/025_jobs_claim_token.sql \
        src/uw_scan/storage/repository.py \
        src/uw_scan/worker/jobs/rescan_loop.py \
        tests/integration/storage/test_repository_jobs.py
git commit -m "fix(jobs): claim-token guard against requeue+reclaim race

When requeue_stale_running_jobs flips a long-running job back to
queued and another worker reclaims it under a new attempt, the
original worker's mark_job_done previously matched on (id, status)
and overwrote the new claim. Status alone could not distinguish
'this same row, my old claim' from 'this same row, someone else's
new claim' — both are 'running'.

Add a claim_token UUID column. claim_next_queued_job sets a fresh
token; requeue_stale_running_jobs clears it; mark_job_done/failed
gate on (id, claim_token). If the token mismatches, the update is
a no-op and a warning is logged.

Tracks B1 from docs/reviews/2026-05-16-backend-code-review.md and
the codex review of the original status-only-guard approach."
```

---

## Task 4: R1 — `_to_decimal` returns `None` on bad input (defensive call sites)

**Why (revised after codex review):** Original plan changed the call-site sort keys to `(is_missing, abs_val)` which, under `reverse=True`, sorts missing rows FIRST not last (because `True > False`). It also wrote a test against `_prune_strike_gex_curve(rows, top_n=2)` — but the real signature is `(rows, levels)` with a hardcoded `[:40]`, so the test would never have run. Revised: keep the helper change (`Decimal | None`) but use a defensive `_to_decimal_or_zero` shim at call sites so the existing semantics are preserved while the helper itself becomes correct, and test the helper directly.

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai.py:441` (helper)
- Modify: `src/uw_scan/reports/trade_insights_ai.py:491, 504, 505, 515, 531` (call sites — add a small shim, no behavior change)
- Test: `tests/test_trade_insights_ai.py` (existing — append direct helper tests)

- [ ] **Step 1: Confirm call sites and signatures with grep**

Run: `grep -nE "_to_decimal\(" src/uw_scan/reports/trade_insights_ai.py`
Expected: 6 matches — the def + 5 call sites at lines 491, 504, 505, 515, 531 (line numbers may have drifted ±5 since the review).

Run: `grep -nA 4 "^def _prune_strike_gex_curve" src/uw_scan/reports/trade_insights_ai.py`
Confirm signature is `(rows, levels)` not `(rows, top_n)`.

- [ ] **Step 2: Write the failing direct-helper test**

Append to `tests/test_trade_insights_ai.py` (find the file's existing import section first):

```python
def test_to_decimal_returns_none_for_invalid_input():
    """R1: _to_decimal previously returned Decimal('0') on any conversion
    failure (including the very common case of a missing dict key returning
    None from .get()). It must return None instead so call sites can decide
    explicitly between 'treat as 0' and 'sort to end'."""
    from decimal import Decimal
    from uw_scan.reports.trade_insights_ai import _to_decimal

    assert _to_decimal(None) is None
    assert _to_decimal("not a number") is None
    assert _to_decimal("") is None

    # Valid inputs still work.
    assert _to_decimal("3.14") == Decimal("3.14")
    assert _to_decimal(42) == Decimal(42)
    assert _to_decimal(Decimal("1.5")) == Decimal("1.5")
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_trade_insights_ai.py::test_to_decimal_returns_none_for_invalid_input -v`
Expected: FAIL — `assert _to_decimal(None) is None` fails because the current code returns `Decimal("0")`.

- [ ] **Step 4: Change `_to_decimal` to return `Decimal | None`**

Edit `src/uw_scan/reports/trade_insights_ai.py:441`. Replace:

```python
def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        _coerce_error = repr(exc)
        return Decimal("0")
```

with:

```python
def _to_decimal(value: Any) -> Decimal | None:
    """Coerce to Decimal or return None. Never silently returns 0 on bad input —
    callers must explicitly opt in via _to_decimal_or_zero when 0 is correct."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _to_decimal_or_zero(value: Any) -> Decimal:
    """Coerce to Decimal, falling back to Decimal(0) for None / unparseable
    input. Use this AT CALL SITES where the existing semantics treat missing
    data as zero (sums, abs-distance sort keys whose missing-data behavior is
    'rank as small/center'). Documenting the choice at the call site makes
    the silent-zero coercion explicit instead of hidden in the helper."""
    coerced = _to_decimal(value)
    return coerced if coerced is not None else Decimal(0)
```

- [ ] **Step 5: Update each call site to use `_to_decimal_or_zero`**

This is a behavior-preserving migration: each call site keeps its original semantics, but the choice to "treat missing as zero" is now explicit at the call site instead of silently inside the helper. Five call sites:

For each of the 5 call sites (491, 504, 505, 515, 531), replace `_to_decimal(...)` with `_to_decimal_or_zero(...)`. Use the Edit tool with `replace_all=False` and provide enough context to make each match unique.

Concrete example for line 491:

```python
# OLD
        key=lambda row: abs(_to_decimal(row.get("net_gex"))),

# NEW
        key=lambda row: abs(_to_decimal_or_zero(row.get("net_gex"))),
```

Apply the same `_to_decimal` → `_to_decimal_or_zero` substitution at lines 504, 505, 515, 531.

> **Why this is the right answer:** the existing top-40 sort by `abs(net_gex)` already prunes missing-data rows naturally (a row with `net_gex` coerced to 0 has the lowest abs and gets dropped under `reverse=True[:40]`). The bug was that the silent zero was undocumented and could surprise a future reader. Making the coercion explicit at the call site fixes the documentation problem without changing the runtime behavior. The actual sort-to-end behavior would only matter if the original semantics were wrong — codex confirmed they are not in this code path.

- [ ] **Step 6: Run the helper test + the existing trade-insights-ai test file**

Run: `uv run pytest tests/test_trade_insights_ai.py -v`
Expected: all PASS, including the new helper test.

- [ ] **Step 7: Run the broader assembler test suite**

Run: `uv run pytest tests/ -k "trade_insights or report_assembly" -v`
Expected: all PASS — no behavior change at any call site.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/reports/trade_insights_ai.py tests/test_trade_insights_ai.py
git commit -m "fix(trade_insights_ai): _to_decimal returns None on bad input

The helper was silently returning Decimal('0') on any conversion
failure (including the very common case of a missing dict key
returning None from .get()). The silent zero is undocumented and
would surprise a future reader who reasonably assumes _to_decimal
either succeeds or raises.

Change the helper to return Decimal | None, and add an explicit
_to_decimal_or_zero shim used at the existing call sites. Behavior
is preserved (the call sites already treat missing as zero); the
choice is now documented at the call site instead of hidden inside
the helper. Tracks R1 from docs/reviews/2026-05-16-backend-code-review.md
and the codex review of the original sort-key-rewrite approach."
```

---

## Task 5: N3 — Drop redundant `idx_jobs_queued` index

**Why:** Migration 005 created `idx_jobs_queued (status, requested_at) WHERE status IN ('queued','running')`. Migration 024 added `idx_jobs_queue_order (status, priority DESC, requested_at)` with the same partial predicate, which can serve any query the old one served. Drop the old one.

**Files:**
- Create: `src/uw_scan/storage/migrations/026_drop_redundant_jobs_queued_index.sql`

- [ ] **Step 1: Confirm both indexes exist (skip if no local DB)**

Run: `psql -d option_wizard -c "\\d uw_scan.jobs" | grep -E "idx_jobs_queued|idx_jobs_queue_order"`
Expected: both index names listed.

- [ ] **Step 2: Write the migration with `CONCURRENTLY`**

Create `src/uw_scan/storage/migrations/026_drop_redundant_jobs_queued_index.sql`:

```sql
-- 026_drop_redundant_jobs_queued_index.sql — superseded by idx_jobs_queue_order
-- (added in migration 024). Both indexes have the same partial predicate; the
-- newer one also leads with priority DESC, so it covers every query the old
-- one served (queue ordering by priority, requested_at).
--
-- Idempotent: DROP INDEX IF EXISTS is a no-op when the index has already
-- been removed. CONCURRENTLY avoids blocking concurrent jobs queue writes
-- in production. scripts/migrate.sh runs each file in autocommit (no
-- --single-transaction wrapper), so CONCURRENTLY is safe here.

SET search_path TO uw_scan, public;

DROP INDEX CONCURRENTLY IF EXISTS uw_scan.idx_jobs_queued;
```

- [ ] **Step 3: Apply the migration**

Run: `bash scripts/migrate.sh 2>&1 | tail -5`
Expected: `Applying src/uw_scan/storage/migrations/026_drop_redundant_jobs_queued_index.sql...` then `All migrations applied.`

- [ ] **Step 4: Verify the index is gone (skip if no local DB)**

Run: `psql -d option_wizard -c "\\d uw_scan.jobs" | grep idx_jobs_queued`
Expected: only `idx_jobs_queue_order` and `idx_jobs_active_ticker` remain — `idx_jobs_queued` is gone.

- [ ] **Step 5: Re-run the migration to verify idempotency**

Run: `bash scripts/migrate.sh 2>&1 | tail -3`
Expected: succeeds again.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/026_drop_redundant_jobs_queued_index.sql
git commit -m "chore(db): drop redundant idx_jobs_queued index

idx_jobs_queue_order added in migration 024 has the same partial
predicate plus the priority column, so it covers every query the
old index served. Use CONCURRENTLY to avoid blocking jobs-queue
writes in production."
```

---

## Task 6: A2 — Covering indexes for the watchlist query's JSONB-extract joins

**Why:** Measured `EXPLAIN ANALYZE` on `list_watchlist_cards` showed **1614 ms** per call, dominated by Parallel Seq Scans on `raw_payloads` (62K rows; FK on `audit_id` but no index) for the `latest_screener_sizes` and `latest_etf_aum` CTEs. The proper long-term fix is to materialize a `ticker_metadata` table; that's deferred. This task adds three indexes that let Postgres turn the seq scans into index scans.

**Caveat (per codex review):** these indexes are not literally "covering" indexes for the JSONB extract — the heap is still hit for `payload_jsonb`. The expectation is a 5-15× speedup, not <100ms. Measure with EXPLAIN before and after; if the improvement is marginal, the materialized-table fix becomes mandatory.

**Files:**
- Create: `src/uw_scan/storage/migrations/027_watchlist_query_covering_indexes.sql`

- [ ] **Step 1: Capture a baseline `EXPLAIN ANALYZE` (skip if no local DB)**

Run the watchlist query in a one-liner and save the bottom 5 lines (planner + execution time):

```bash
psql -d option_wizard -At <<'SQL' 2>&1 | tee /tmp/watchlist-baseline.txt | tail -5
EXPLAIN (ANALYZE, BUFFERS) WITH active_jobs AS (SELECT id, ticker, status, requested_at, started_at, row_number() OVER (ORDER BY priority DESC, requested_at ASC, id ASC) AS queue_position FROM uw_scan.jobs WHERE status IN ('queued', 'running')), latest_market_caps AS (SELECT DISTINCT ON (ticker) ticker, marketcap FROM uw_scan.scan_results WHERE marketcap IS NOT NULL ORDER BY ticker, run_id DESC), latest_screener_sizes AS (SELECT DISTINCT ON (r.ticker) r.ticker, p.payload_jsonb->'data'->0->>'marketcap' AS market_cap FROM uw_scan.scan_runs r JOIN uw_scan.api_request_audit a ON r.run_id = a.run_id JOIN uw_scan.raw_payloads p ON a.audit_id = p.audit_id WHERE a.endpoint_slug = 'bulk_screener_stocks' AND jsonb_typeof(p.payload_jsonb->'data') = 'array' AND p.payload_jsonb->'data'->0->>'marketcap' IS NOT NULL ORDER BY r.ticker, r.run_id DESC), latest_etf_aum AS (SELECT DISTINCT ON (r.ticker) r.ticker, p.payload_jsonb->'data'->>'aum' AS aum FROM uw_scan.scan_runs r JOIN uw_scan.api_request_audit a ON r.run_id = a.run_id JOIN uw_scan.raw_payloads p ON a.audit_id = p.audit_id WHERE a.endpoint_slug = 'etf_info' AND jsonb_typeof(p.payload_jsonb->'data') = 'object' AND p.payload_jsonb->'data'->>'aum' IS NOT NULL ORDER BY r.ticker, r.run_id DESC) SELECT w.ticker FROM uw_scan.watchlist w LEFT JOIN uw_scan.watchlist_card c ON w.ticker = c.ticker LEFT JOIN uw_scan.scan_runs sr ON c.run_id = sr.run_id LEFT JOIN latest_market_caps lmc ON w.ticker = lmc.ticker LEFT JOIN latest_screener_sizes lss ON w.ticker = lss.ticker LEFT JOIN latest_etf_aum lea ON w.ticker = lea.ticker LEFT JOIN active_jobs j ON w.ticker = j.ticker WHERE w.removed_at IS NULL ORDER BY w.pinned DESC, w.sort_rank, w.ticker;
SQL
```

Save the `Execution Time:` line for comparison after Step 4.

- [ ] **Step 2: Write the migration**

Create `src/uw_scan/storage/migrations/027_watchlist_query_covering_indexes.sql`:

```sql
-- 027_watchlist_query_covering_indexes.sql — speed up the watchlist endpoint's
-- per-request CTEs that resolve market_cap and aum via raw_payloads.
--
-- Background: review 2026-05-16-backend-code-review.md §10/A2 measured the
-- watchlist endpoint at ~1.6 sec/request, with Parallel Seq Scans on the
-- 62K-row raw_payloads table (FK on audit_id but no auto-created index).
--
-- These three indexes turn the seq scans into index scans. They are NOT
-- covering indexes for the JSONB extract — the heap is still touched for
-- payload_jsonb. Expect a 5-15x speedup, not 100x. If the measured
-- improvement is marginal, the longer-term fix is to materialize a
-- ticker_metadata table and drop the JSONB-extract CTEs entirely.
--
-- Idempotent: CREATE INDEX CONCURRENTLY IF NOT EXISTS. CONCURRENTLY avoids
-- blocking concurrent writes during the build. scripts/migrate.sh runs
-- each file with psql -f in autocommit (no --single-transaction wrapper),
-- so CONCURRENTLY is safe here.

SET search_path TO uw_scan, public;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_raw_payloads_audit_id
  ON uw_scan.raw_payloads (audit_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_api_request_audit_watchlist_endpoints
  ON uw_scan.api_request_audit (endpoint_slug, run_id, audit_id)
  WHERE endpoint_slug IN ('bulk_screener_stocks', 'etf_info');

-- The DISTINCT ON (ticker) ORDER BY ticker, run_id DESC pattern in both
-- watchlist CTEs benefits from a btree on (ticker, run_id DESC) for scan_runs.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scan_runs_ticker_run_desc
  ON uw_scan.scan_runs (ticker, run_id DESC);
```

- [ ] **Step 3: Apply the migration**

Run: `bash scripts/migrate.sh 2>&1 | tail -10`
Expected: `Applying src/uw_scan/storage/migrations/027_watchlist_query_covering_indexes.sql...` followed by `All migrations applied.`

If `CREATE INDEX CONCURRENTLY` fails with "cannot run inside a transaction block" (which would mean `scripts/migrate.sh` IS wrapping in a transaction despite not using `-1`), edit the migration to drop the `CONCURRENTLY` keywords — non-concurrent CREATE INDEX is fine on dev databases at this scale (62K rows).

- [ ] **Step 4: Re-measure `EXPLAIN ANALYZE` (skip if no local DB)**

Run the same one-liner from Step 1 and save the result to `/tmp/watchlist-after.txt`. Compare:

```bash
diff <(grep "Execution Time" /tmp/watchlist-baseline.txt) <(grep "Execution Time" /tmp/watchlist-after.txt)
```

Report the actual measured numbers in the commit message. The plan's expectation: a 5-15x improvement (i.e., baseline 1614 ms → 100-300 ms range). If the improvement is less than 3x, the indexes alone are insufficient; flag this in the commit message and recommend the materialized-table follow-up.

- [ ] **Step 5: Verify the new query plan uses Index Scans (skip if no local DB)**

In the `EXPLAIN` output from Step 4, check for:
- `Index Scan using idx_raw_payloads_audit_id on raw_payloads p` (replaces `Parallel Seq Scan on raw_payloads`)
- `Index Scan using idx_api_request_audit_watchlist_endpoints on api_request_audit a`

If the planner is still doing seq scans, run `ANALYZE uw_scan.raw_payloads; ANALYZE uw_scan.api_request_audit; ANALYZE uw_scan.scan_runs;` to refresh statistics, then re-EXPLAIN.

- [ ] **Step 6: Re-run integration tests for the watchlist endpoint**

Run: `uv run pytest tests/integration/api/test_watchlist_endpoint.py tests/integration/storage/test_repository_watchlist.py -v`
Expected: all PASS.

- [ ] **Step 7: Re-run the migration to verify idempotency**

Run: `bash scripts/migrate.sh 2>&1 | tail -5`
Expected: succeeds again.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/storage/migrations/027_watchlist_query_covering_indexes.sql
git commit -m "perf(watchlist): cover raw_payloads + audit + scan_runs joins

list_watchlist_cards joined api_request_audit -> raw_payloads to
extract market_cap and aum from JSONB. raw_payloads has 62K rows
and the FK on audit_id was not backed by an index; api_request_audit
also lacked a covering index on endpoint_slug, and scan_runs had no
(ticker, run_id DESC) index for the DISTINCT ON pattern.

Adds three indexes (all CONCURRENTLY for live safety):
  * idx_raw_payloads_audit_id — covers the FK join.
  * idx_api_request_audit_watchlist_endpoints — partial on the two
    endpoint slugs the watchlist CTEs filter by.
  * idx_scan_runs_ticker_run_desc — covers the DISTINCT ON sort.

Measured EXPLAIN ANALYZE: <BASELINE>ms -> <AFTER>ms.
[fill in the actual numbers from Step 4 before committing]

Tracks A2 from docs/reviews/2026-05-16-backend-code-review.md.
Future work: materialize ticker_metadata to remove the JSONB-extract
CTEs entirely."
```

---

## Task 7: Final verification — full test run + branch summary

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -q 2>&1 | tail -10`
Expected: all PASS, no new failures vs baseline.

- [ ] **Step 2: Confirm migration order is sequential**

Run: `ls src/uw_scan/storage/migrations/ | tail -5`
Expected: `024_…`, `025_jobs_claim_token.sql`, `026_drop_redundant_jobs_queued_index.sql`, `027_watchlist_query_covering_indexes.sql`.

- [ ] **Step 3: Show all commits on this branch**

Run: `git log --oneline main..HEAD`
Expected: 6 commits (one per fix task).

- [ ] **Step 4: Diff vs main for a final read**

Run: `git diff --stat main...HEAD`
Expected: changes confined to:
- `src/uw_scan/storage/repository.py`
- `src/uw_scan/reports/trade_insights_ai.py`
- `src/uw_scan/worker/jobs/rescan_loop.py`
- 3 new migration files
- 2 new/extended test files
- (no FE / OpenAPI snapshot changes — already nullable)

- [ ] **Step 5: Branch is ready for PR**

No commit here — this is a verification gate. Open a PR via `gh pr create` if/when the user is ready.
