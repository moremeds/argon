# Backend N-Series + A1 Fixes Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Each task is independently shippable.

**Goal:** Address the 7 non-blocking findings (N1, N2, N5, N6, N7, N8) and the A1 addendum from `docs/reviews/2026-05-16-backend-code-review.md` that were deferred from PR #35.

**Architecture:** Six tasks, ordered low → high risk. Each lands a focused fix with tests. N1/N7 are documentation-only (no code risk). N2/N6 are localized SQL/index changes. N5 tightens a maintainability tax. N8 collapses 2 DB round trips into 1. A1 introduces a small cache table to reduce UW QPS for ETF AUM lookups.

**Tech Stack:** Python 3.13, psycopg 3, Postgres (`uw_scan` schema), idempotent SQL migrations, pytest-postgresql for integration.

## Plan revisions from `/codex-review` (Codex + Claude bilateral tribunal)

Initial draft was reviewed by Codex (gpt-5.3-codex) and Claude before any code changes. 10 issues raised, all consensus or self-verified. Revisions applied:

1. **CRITICAL — ISSUE-1:** `list_watchlist_cards()` is called by 4 worker code paths (`full_scan.py:44`, `flow_data_refresh.py:56`, `volatility_jobs.py:46`) and 2 test files. Changing its return type would break them. **Fix:** Task 5 now adds a NEW method `list_watchlist_cards_with_queue_summary()` used only by the router; original method untouched.
2. **CRITICAL — ISSUE-2:** Strict `_KNOWN_FIELDS` validation in `from_db` would break `get_watchlist_card()` (uses `SELECT * FROM watchlist_card`, different column shape). **Fix:** Task 3 splits into lenient `from_db()` (kept) and strict `from_list_row()` (new, used only by the list query).
3. **CRITICAL — ISSUE-3:** Empty watchlist + active jobs → `CROSS JOIN summary` returns zero rows → folded summary returns zeros. Regression vs. today's separate `get_rescan_queue_summary()` query. **Fix:** Task 5 empty-rows branch falls back to standalone summary query.
4. **IMPORTANT — ISSUE-4:** Cannot delete `get_rescan_queue_summary()` — a test caller exists at `test_repository_watchlist.py:191`, and the empty-rows fallback above now uses it.
5. **IMPORTANT — ISSUE-5:** Test path typo fixed: `test_watchlist.py` → `test_watchlist_endpoint.py`.
6. **IMPORTANT — ISSUE-6:** Pipeline behavior test for A1 upgraded from optional to REQUIRED.
7. **IMPORTANT — ISSUE-7:** Dead `etf_aum_stale = True; _ = etf_aum_stale` "future hook" stripped.
8. **MINOR — ISSUE-8:** Cache methods normalize `ticker.upper()` to avoid duplicate logical rows from mixed-case callers.
9. **MINOR — ISSUE-9:** Added Step 4.4b validating `pg_index.indisvalid` (interrupted CONCURRENTLY can leave invalid indexes that `IF NOT EXISTS` silently skips).
10. **MINOR — ISSUE-10:** `from_list_row()` rejects duplicate aliases (`len(set) != len(names)` check).

Plus my own self-review fixes:
- Task 1.2 clarified that BOTH `_NoOhlc()` call sites get the same comment block.
- Task 3 docstring corrected: "30 fields" → 37.

Pre-execution validation pass added two further refinements:
- **Task 5 slicing math:** switched from negative-index trick (`first[-4 + summary_idx[...]]`) to a single name-keyed `col_idx` dict and a position-list filter for card rows. Robust to a future hand that reorders summary columns inside the SELECT projection.
- **Task 6 helper extraction:** pre-check confirmed there is no non-live pipeline harness. Restructured A1 to extract `_get_or_fetch_etf_aum()` into a directly unit-testable helper, with 4 wire-up tests (cache hit / miss+success / miss+raise / miss+None aum). Pipeline.py change becomes a one-line call to the helper.

---

## Task 1 — N1 + N7: Document worker concurrency model

**Files:**
- Modify: `src/uw_scan/worker/CLAUDE.md` (add concurrency note for N× UW sharding + `_NoOhlc()` design)
- Modify: `src/uw_scan/worker/scheduler.py:248-250, 272-274` (one-line comment per call site)

**Why doc-only:** Review §65 recommends option (b) — keep the sharded speedup, document the N× concurrency math so the rate-limit budget is explicit. N7 is a behavior change with no broken behavior, just an undocumented one — a comment is the right unit.

- [ ] **Step 1.1: Add concurrency note to `worker/CLAUDE.md`**

Append a section explaining: (a) UW worker count multiplies peak QPS during nightly flow refresh; (b) `_NoOhlc()` is intentional in `_full_scan`/`_rescan` because OHLC pulls are owned by dedicated `_ohlc_pull` / `_spot_refresh` jobs.

- [ ] **Step 1.2: Add inline comment at BOTH `_NoOhlc()` call sites (scheduler.py:250 and :274)**

Add the same two-line comment immediately above each call:

```python
# _NoOhlc() is intentional: OHLC fetches are owned by _ohlc_pull / _spot_refresh.
# See worker/CLAUDE.md "Provider concurrency model".
full_scan_once(repo, uw, _NoOhlc(), ticker_filter=ticker_filter)
```

```python
# _NoOhlc() is intentional: OHLC fetches are owned by _ohlc_pull / _spot_refresh.
# See worker/CLAUDE.md "Provider concurrency model".
rescan_tick(repo, uw, _NoOhlc())
```

- [ ] **Step 1.3: Commit**

```bash
git add src/uw_scan/worker/CLAUDE.md src/uw_scan/worker/scheduler.py
git commit -m "docs(worker): document N× UW concurrency and _NoOhlc() rationale"
```

---

## Task 2 — N2: Refresh `requested_at` on rescan dedup

**Files:**
- Modify: `src/uw_scan/storage/repository.py:2789-2807` (`enqueue_rescan_job`)
- Test: `tests/integration/storage/test_repository_jobs.py` (new test alongside the claim-token tests we added in PR #35)

**Why:** When a user clicks Rescan twice on a ticker with an active job, the dedup currently bumps priority via `GREATEST(...)` but leaves the original click's `requested_at` intact. The UI's "queue position" sort uses `requested_at` to break ties — so the second click is invisible. The reviewer's suggested fix sets `requested_at = EXCLUDED.requested_at`.

- [ ] **Step 2.1: Write failing test**

In `tests/integration/storage/test_repository_jobs.py`, add:

```python
def test_enqueue_rescan_job_refreshes_requested_at_on_dedup(repo):
    """A second enqueue for the same ticker must bump requested_at so the UI
    reflects the most recent click, not the first."""
    first_id = repo.enqueue_rescan_job("AAPL", priority=0)
    first = repo.get_job(first_id)
    assert first is not None
    first_requested = first.requested_at

    # Force a measurable gap so the timestamp comparison can't be a tie.
    import time
    time.sleep(0.05)

    second_id = repo.enqueue_rescan_job("AAPL", priority=5)
    assert second_id == first_id  # dedup hit the same row
    second = repo.get_job(second_id)
    assert second is not None
    assert second.requested_at > first_requested
    assert second.priority == 5  # GREATEST behavior preserved
```

- [ ] **Step 2.2: Run test, confirm FAIL**

```bash
uv run pytest tests/integration/storage/test_repository_jobs.py::test_enqueue_rescan_job_refreshes_requested_at_on_dedup -v
```
Expected: `assert second.requested_at > first_requested` fails (they're equal).

- [ ] **Step 2.3: Update `enqueue_rescan_job` SQL**

```python
f"""
INSERT INTO {self._schema}.jobs (ticker, status, priority)
VALUES (%s, 'queued', %s)
ON CONFLICT (ticker) WHERE status IN ('queued', 'running')
DO UPDATE SET
    priority = GREATEST(
        {self._schema}.jobs.priority,
        EXCLUDED.priority
    ),
    requested_at = EXCLUDED.requested_at
RETURNING id
"""
```

- [ ] **Step 2.4: Run test, confirm PASS**

```bash
uv run pytest tests/integration/storage/test_repository_jobs.py -v
```

- [ ] **Step 2.5: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/integration/storage/test_repository_jobs.py
git commit -m "fix(jobs): refresh requested_at when rescan dedup hits"
```

---

## Task 3 — N5: Validate column set in `WatchlistCardRow.from_db`

**Files:**
- Modify: `src/uw_scan/storage/repository.py:180-200` (declare `_LIST_FIELDS` frozenset + add `from_list_row` strict constructor)
- Test: `tests/unit/storage/test_watchlist_card_row.py` (new unit file)

**Why:** Today, `__getattr__` returns `AttributeError(name)` only when an attribute is *read*, not when the row is constructed. A typo like `setup_typ` in a SELECT alias silently flows through `from_db` and only blows up at the FE when a card field appears empty. Tightening construction to fail loudly when SELECT columns ≠ declared set catches the bug at the seam.

**Approach (revised per Codex review ISSUE-2):** Keep the dict-backed shape AND keep the existing lenient `from_db()` for `get_watchlist_card()` (which does `SELECT * FROM watchlist_card` and returns a fundamentally different column set — no `sector`/`pinned`/`sort_rank` from `watchlist`, no `active_job_*` from CTE, has `updated_at`). Add a NEW strict constructor `from_list_row()` that `list_watchlist_cards` uses, validating against the 37-field `_LIST_FIELDS` frozenset. The lenient `from_db()` stays for single-row lookups.

- [ ] **Step 3.1: Read the current SELECT to enumerate column names**

From `src/uw_scan/storage/repository.py:2611-2651`, list the final SELECT projection. The aliases (ones with `AS`) and bare column names form the truth set.

- [ ] **Step 3.2: Write failing test**

```python
# tests/unit/storage/test_watchlist_card_row.py
import pytest
from uw_scan.storage.repository import WatchlistCardRow


class _StubCol:
    def __init__(self, name: str) -> None:
        self.name = name


def _desc(*names: str) -> list[_StubCol]:
    return [_StubCol(n) for n in names]


def test_from_list_row_rejects_unknown_column():
    """Catching typos in SELECT aliases is the whole point of this guard."""
    cols = list(WatchlistCardRow._LIST_FIELDS) + ["setup_typ"]  # typo extras
    with pytest.raises(ValueError, match="unknown column"):
        WatchlistCardRow.from_list_row(
            row=tuple(None for _ in cols),
            description=_desc(*cols),
        )


def test_from_list_row_rejects_missing_required_column():
    """Drift the other way: a known column dropped from SELECT should also fail."""
    cols = [c for c in WatchlistCardRow._LIST_FIELDS if c != "ticker"]
    with pytest.raises(ValueError, match="missing column"):
        WatchlistCardRow.from_list_row(
            row=tuple(None for _ in cols),
            description=_desc(*cols),
        )


def test_from_list_row_rejects_duplicate_columns():
    """Per Codex ISSUE-10: a duplicate alias would silently collapse via set()."""
    cols = list(WatchlistCardRow._LIST_FIELDS) + ["ticker"]  # dup
    with pytest.raises(ValueError, match="duplicate column"):
        WatchlistCardRow.from_list_row(
            row=tuple(None for _ in cols),
            description=_desc(*cols),
        )


def test_from_list_row_accepts_full_column_set():
    """Smoke: the canonical list_watchlist_cards SELECT must construct cleanly."""
    cols = list(WatchlistCardRow._LIST_FIELDS)
    row = tuple(None for _ in cols)
    out = WatchlistCardRow.from_list_row(row, _desc(*cols))
    assert out.ticker is None  # field present, value None — does not raise


def test_from_db_still_accepts_lenient_shape():
    """get_watchlist_card uses SELECT *, which is a different column set
    (no watchlist fields, has updated_at). The lenient from_db must keep
    working for that path."""
    cols = ["ticker", "run_id", "spot", "iv_atm", "updated_at"]
    row = ("AAPL", 1, None, None, None)
    out = WatchlistCardRow.from_db(row, _desc(*cols))
    assert out.ticker == "AAPL"
    assert out.updated_at is None  # not in _LIST_FIELDS but not rejected
```

- [ ] **Step 3.3: Run test, confirm FAIL**

```bash
uv run pytest tests/unit/storage/test_watchlist_card_row.py -v
```
Expected: `AttributeError: _LIST_FIELDS` (the frozenset doesn't exist yet) and `AttributeError: from_list_row` (the new constructor doesn't exist).

- [ ] **Step 3.4: Add `_LIST_FIELDS` + new strict `from_list_row` constructor (keep lenient `from_db` for single-row callers)**

```python
class WatchlistCardRow:
    """Variable-shaped: 37 fields in the list shape, fewer in single-row shape.

    Two constructors:
      - from_list_row(row, desc) — strict, validates against _LIST_FIELDS.
        Use this in list_watchlist_cards so SELECT-alias typos fail loudly.
      - from_db(row, desc) — lenient, accepts any column set.
        Use this in get_watchlist_card which does SELECT * FROM watchlist_card
        and returns a different column shape (no watchlist fields, has updated_at).
    """

    # Canonical column list for list_watchlist_cards.
    # Keep in sync with the SELECT projection in that method.
    _LIST_FIELDS: frozenset[str] = frozenset({
        # watchlist
        "ticker", "sector", "pinned", "sort_rank",
        # card metadata
        "run_id", "scanned_at",
        "spot", "spot_quoted_at", "spot_source",
        "iv_atm", "iv_rank",
        "setup_type", "setup_direction", "setup_score",
        "aggression_pct",
        "ret_1d", "ret_1w", "ret_30d",
        "market_cap", "aum",
        "gex_flip_distance", "gex_flip_price", "gex_per_1pct_move",
        "max_gex_strike", "gex_expiring_pct", "gex_expiring_date",
        "skew_25d_30dte",
        "call_oi_total", "put_oi_total", "pcr_oi", "pcr_vol",
        "pcr_delta_30d",
        # active job columns (LEFT JOIN — all nullable)
        "active_job_id", "active_job_status", "active_job_queue_position",
        "active_job_requested_at", "active_job_started_at",
    })

    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str):
        try:
            data = object.__getattribute__(self, "_data")
        except AttributeError as e:
            raise AttributeError(name) from e
        if name in data:
            return data[name]
        raise AttributeError(name)

    @classmethod
    def from_db(cls, row: tuple, description) -> "WatchlistCardRow":
        """Lenient: accept whatever columns the cursor returned. Used by
        get_watchlist_card (SELECT *)."""
        return cls({col.name: val for col, val in zip(description, row, strict=False)})

    @classmethod
    def from_list_row(cls, row: tuple, description) -> "WatchlistCardRow":
        """Strict: validate against _LIST_FIELDS. Use only for the
        list_watchlist_cards projection so SELECT-alias typos fail loudly."""
        names = [col.name for col in description]
        if len(set(names)) != len(names):
            raise ValueError(
                f"WatchlistCardRow.from_list_row got duplicate column(s) in description: "
                f"{names}"
            )
        seen = set(names)
        unknown = seen - cls._LIST_FIELDS
        if unknown:
            raise ValueError(
                f"WatchlistCardRow.from_list_row got unknown column(s): {sorted(unknown)}. "
                f"Add to _LIST_FIELDS if the SELECT was intentionally extended."
            )
        missing = cls._LIST_FIELDS - seen
        if missing:
            raise ValueError(
                f"WatchlistCardRow.from_list_row missing column(s): {sorted(missing)}. "
                f"Either restore them to the SELECT or remove from _LIST_FIELDS."
            )
        return cls({name: val for name, val in zip(names, row, strict=False)})

    def to_dict(self) -> dict:
        return dict(self._data)
```

Then switch the constructor in `list_watchlist_cards()` from `WatchlistCardRow.from_db(...)` to `WatchlistCardRow.from_list_row(...)` (around line 2665).

- [ ] **Step 3.5: Run new unit tests + full repo integration suite**

```bash
uv run pytest tests/unit/storage/test_watchlist_card_row.py tests/integration/storage/ -v
```
Expected: PASS. If the integration tests fail with `missing column(s)`, the SELECT in `list_watchlist_cards` and `_LIST_FIELDS` are out of sync — that's exactly the kind of drift the guard is designed to catch. Fix one or the other.

- [ ] **Step 3.6: Commit**

```bash
git add src/uw_scan/storage/repository.py tests/unit/storage/test_watchlist_card_row.py
git commit -m "fix(watchlist): validate WatchlistCardRow column set at construction"
```

---

## Task 4 — N6: Index `scan_results` for `latest_market_caps` CTE

**Files:**
- Create: `src/uw_scan/storage/migrations/028_scan_results_market_cap_index.sql`

**Why:** The `latest_market_caps` CTE does `SELECT DISTINCT ON (ticker) ticker, marketcap FROM scan_results WHERE marketcap IS NOT NULL ORDER BY ticker, run_id DESC` on every `/api/watchlist` request. As `scan_results` grows (one row per ticker per scan run), this becomes a seq scan. Migration 027 covered `scan_runs` but did NOT touch `scan_results` — N6 is still open.

- [ ] **Step 4.1: Verify baseline EXPLAIN**

```bash
set -a; source ../../../.env; set +a
psql "$DATABASE_URL" -c "EXPLAIN ANALYZE SELECT DISTINCT ON (ticker) ticker, marketcap FROM uw_scan.scan_results WHERE marketcap IS NOT NULL ORDER BY ticker, run_id DESC LIMIT 5;"
```
Record the cost + runtime.

- [ ] **Step 4.2: Write migration 028**

```sql
-- 028_scan_results_market_cap_index.sql — N6 from backend code review.
--
-- The watchlist endpoint's latest_market_caps CTE does:
--   SELECT DISTINCT ON (ticker) ticker, marketcap
--   FROM scan_results
--   WHERE marketcap IS NOT NULL
--   ORDER BY ticker, run_id DESC
-- on every /api/watchlist request. Without a supporting partial index this
-- degrades to a seq scan as scan_results grows (one row per ticker per scan).
--
-- Idempotent: CREATE INDEX CONCURRENTLY IF NOT EXISTS. CONCURRENTLY avoids
-- blocking concurrent writes; scripts/migrate.sh runs each file in autocommit
-- so CONCURRENTLY is safe here.

SET search_path TO uw_scan, public;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scan_results_ticker_run_marketcap
  ON uw_scan.scan_results (ticker, run_id DESC)
  WHERE marketcap IS NOT NULL;
```

- [ ] **Step 4.3: Apply migration**

```bash
set -a; source ../../../.env; set +a
bash scripts/migrate.sh
```

- [ ] **Step 4.4: Re-run EXPLAIN, capture delta**

Repeat the EXPLAIN ANALYZE from Step 4.1. Expect Seq Scan → Index Scan.

- [ ] **Step 4.4b: Validate the index is not in INVALID state (per Codex ISSUE-9)**

`CREATE INDEX CONCURRENTLY` can leave an INVALID index if interrupted (Ctrl-C, OOM, connection drop). `IF NOT EXISTS` then skips rebuild on rerun, so a silently-broken index would not be caught.

```bash
psql "$DSN" -c "SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE indexrelid::regclass::text = 'uw_scan.idx_scan_results_ticker_run_marketcap';"
```

Expected: `indisvalid = t`. If `f`, recover with:
```sql
DROP INDEX CONCURRENTLY uw_scan.idx_scan_results_ticker_run_marketcap;
-- then rerun the migration
```

- [ ] **Step 4.5: Commit**

```bash
git add src/uw_scan/storage/migrations/028_scan_results_market_cap_index.sql
git commit -m "perf(watchlist): index scan_results for latest_market_caps CTE"
```

---

## Task 5 — N8: Fold queue summary into watchlist query

**Files:**
- Modify: `src/uw_scan/storage/repository.py` (add NEW method `list_watchlist_cards_with_queue_summary`; leave `list_watchlist_cards` untouched)
- Modify: `src/uw_scan/api/routers/watchlist.py:89-130` (use new method, remove second `get_rescan_queue_summary` call)
- Test: `tests/integration/storage/test_repository_watchlist.py` (add test that the new method's summary matches the standalone `get_rescan_queue_summary` output)

**Why:** Today the router issues two DB queries on every `/api/watchlist` request:
1. `list_watchlist_cards()` → builds an `active_jobs` CTE filtered to `status IN ('queued','running')`
2. `get_rescan_queue_summary()` → re-scans `jobs` for the same set, derives counts + oldest timestamp

The reviewer notes these are the same set — derive the summary inside the watchlist query via a `summary` CTE over `active_jobs`, return it as repeated scalar columns on each row, and pop them off in the new method. Single round trip.

**Tradeoff:** The summary scalars are duplicated on every returned row (~4 ints × 30 rows = trivial). The alternative (psycopg pipeline mode) is more complex to wire and reason about. Chose the denormalized columns for clarity.

**Backward compatibility (revised per Codex ISSUE-1):** `list_watchlist_cards()` returns `list[WatchlistCardRow]` and has 4 other callers in src/ (`worker/jobs/full_scan.py:44`, `worker/jobs/flow_data_refresh.py:56`, `worker/volatility_jobs.py:46`) and 2 in tests/ that all expect a flat list. **Do NOT change its signature.** Instead add a NEW method `list_watchlist_cards_with_queue_summary() -> tuple[list[WatchlistCardRow], RescanQueueSummaryRow]` used only by the router. This isolates the perf change.

**Keep `get_rescan_queue_summary` (per Codex ISSUE-4):** the test at `tests/integration/storage/test_repository_watchlist.py:191` calls it. The new code path in the router supersedes it, but the method stays for the test and as a fallback (used in the empty-watchlist branch — see Step 5.4).

- [ ] **Step 5.1: Confirm `get_rescan_queue_summary` is referenced by a test (keep it)**

```bash
grep -rn "get_rescan_queue_summary" src/ tests/
```
Expect 3 hits: definition in repository.py, router call site (about to be removed), test caller in `tests/integration/storage/test_repository_watchlist.py:191`. Keep the method.

- [ ] **Step 5.2: Write failing integration test (for the NEW method)**

```python
# tests/integration/storage/test_repository_watchlist.py — append
def test_list_watchlist_cards_with_queue_summary_matches_standalone(repo):
    """The folded summary must equal what get_rescan_queue_summary returns."""
    # Need at least one watchlist row so CROSS JOIN summary returns rows.
    repo.add_watchlist_ticker(ticker="AAPL", sector="TECH")
    repo.add_watchlist_ticker(ticker="MSFT", sector="TECH")
    repo.enqueue_rescan_job("AAPL")
    repo.enqueue_rescan_job("MSFT")

    rows, summary_inline = repo.list_watchlist_cards_with_queue_summary()
    summary_standalone = repo.get_rescan_queue_summary()

    assert len(rows) == 2
    assert summary_inline.total == summary_standalone.total
    assert summary_inline.queued == summary_standalone.queued
    assert summary_inline.running == summary_standalone.running
    assert summary_inline.oldest_requested_at == summary_standalone.oldest_requested_at


def test_list_watchlist_cards_with_queue_summary_empty_watchlist_active_jobs(repo):
    """Per Codex ISSUE-3: empty watchlist + active jobs must still report
    real summary counts. CROSS JOIN drops all rows when watchlist is empty,
    so the method must fall back to get_rescan_queue_summary."""
    # No watchlist seed — empty.
    repo.enqueue_rescan_job("AAPL")
    repo.enqueue_rescan_job("MSFT")

    rows, summary = repo.list_watchlist_cards_with_queue_summary()

    assert rows == []
    assert summary.total == 2  # NOT zero
    assert summary.queued == 2
    assert summary.running == 0
    assert summary.oldest_requested_at is not None
```

- [ ] **Step 5.3: Run tests, confirm FAIL**

```bash
uv run pytest tests/integration/storage/test_repository_watchlist.py::test_list_watchlist_cards_with_queue_summary_matches_standalone tests/integration/storage/test_repository_watchlist.py::test_list_watchlist_cards_with_queue_summary_empty_watchlist_active_jobs -v
```
Expected: `AttributeError: 'Repository' object has no attribute 'list_watchlist_cards_with_queue_summary'`.

- [ ] **Step 5.4: Add `list_watchlist_cards_with_queue_summary` method**

Add a new method that wraps the existing query, adds a `summary` CTE, CROSS JOINs it onto each card row, and falls back to `get_rescan_queue_summary()` when the watchlist is empty.

Implementation outline:

```python
def list_watchlist_cards_with_queue_summary(
    self,
) -> tuple[list[WatchlistCardRow], RescanQueueSummaryRow]:
    """Variant of list_watchlist_cards that also returns queue summary in
    one round trip. Used by /api/watchlist to collapse 2 DB queries into 1.

    Edge case: when the watchlist is empty, CROSS JOIN summary returns zero
    rows, so we fall back to a standalone summary query (1 query in the
    common path, 2 in the empty-watchlist edge case)."""

    with self._conn.cursor() as cur:
        cur.execute(
            f"""
            WITH active_jobs AS (
              SELECT
                id, ticker, status, requested_at, started_at,
                row_number() OVER (
                  ORDER BY priority DESC, requested_at ASC, id ASC
                ) AS queue_position
              FROM {self._schema}.jobs
              WHERE status IN ('queued', 'running')
            ),
            summary AS (
              SELECT
                count(*)                                     AS s_total,
                count(*) FILTER (WHERE status = 'queued')    AS s_queued,
                count(*) FILTER (WHERE status = 'running')   AS s_running,
                min(requested_at)                            AS s_oldest
              FROM active_jobs
            ),
            -- ... latest_market_caps, latest_screener_sizes, latest_etf_aum
            --     copied verbatim from list_watchlist_cards ...
            SELECT
              <same 37 columns as list_watchlist_cards>,
              sm.s_total, sm.s_queued, sm.s_running, sm.s_oldest
            FROM {self._schema}.watchlist w
              LEFT JOIN {self._schema}.watchlist_card c ON w.ticker = c.ticker
              LEFT JOIN {self._schema}.scan_runs sr ON c.run_id = sr.run_id
              LEFT JOIN latest_market_caps lmc ON w.ticker = lmc.ticker
              LEFT JOIN latest_screener_sizes lss ON w.ticker = lss.ticker
              LEFT JOIN latest_etf_aum lea ON w.ticker = lea.ticker
              LEFT JOIN {self._schema}.intraday_quote q ON w.ticker = q.ticker
              LEFT JOIN active_jobs j ON w.ticker = j.ticker
              CROSS JOIN summary sm
            WHERE w.removed_at IS NULL
            ORDER BY w.pinned DESC, w.sort_rank, w.ticker
            """
        )
        all_rows = cur.fetchall()
        description = cur.description

    if not all_rows:
        # Empty watchlist: CROSS JOIN drops all rows, even if active jobs exist.
        # Fall back to standalone summary query to preserve today's behavior.
        return [], self.get_rescan_queue_summary()

    # The SELECT projects 37 card columns followed by 4 summary columns
    # (s_total, s_queued, s_running, s_oldest). Look up by name to avoid
    # positional-index typos.
    col_idx = {col.name: i for i, col in enumerate(description)}
    summary_col_names = {"s_total", "s_queued", "s_running", "s_oldest"}

    first = all_rows[0]
    summary = RescanQueueSummaryRow(
        total=first[col_idx["s_total"]] or 0,
        queued=first[col_idx["s_queued"]] or 0,
        running=first[col_idx["s_running"]] or 0,
        oldest_requested_at=first[col_idx["s_oldest"]],
    )

    # Strip summary columns before constructing the strict WatchlistCardRow.
    # Build the card description/row by filtering out the 4 summary positions.
    card_positions = [i for i, col in enumerate(description) if col.name not in summary_col_names]
    card_cols = [description[i] for i in card_positions]
    cards = [
        WatchlistCardRow.from_list_row(
            tuple(row[i] for i in card_positions),
            card_cols,
        )
        for row in all_rows
    ]
    return cards, summary
```

**Why position-list slicing instead of `row[:-4]`:** robust to a future hand that moves the summary columns to a different position in the SELECT. The lookup is by NAME, not by trailing position.

**Note:** the inner SELECT projection and joins should be copy-pasted from `list_watchlist_cards` (the 37 card columns) plus the four summary columns. Avoid factoring the query into a builder — that's a refactor beyond N8's scope.

**`_LIST_FIELDS` is NOT modified** by this task — the strict validation only applies to the card-columns slice, and `from_list_row` receives exactly that slice.

- [ ] **Step 5.5: Update router to use new method**

In `src/uw_scan/api/routers/watchlist.py:89-130`:

```python
rows, queue = repo.list_watchlist_cards_with_queue_summary()
# delete the separate repo.get_rescan_queue_summary() call (lines 127-128)
```

Leave the rest of the router untouched.

- [ ] **Step 5.6: Run integration tests + watchlist endpoint smoke**

```bash
uv run pytest tests/integration/storage/test_repository_watchlist.py tests/integration/api/test_watchlist_endpoint.py -v
```

(Per Codex ISSUE-5: the file is `test_watchlist_endpoint.py`, not `test_watchlist.py`.)

- [ ] **Step 5.7: Commit**

```bash
git add src/uw_scan/storage/repository.py src/uw_scan/api/routers/watchlist.py tests/integration/storage/test_repository_watchlist.py
git commit -m "perf(watchlist): fold queue summary into single round trip"
```

---

## Task 6 — A1: ETF AUM cache

**Files:**
- Create: `src/uw_scan/storage/migrations/029_etf_aum_cache.sql`
- Modify: `src/uw_scan/storage/repository.py` (add `get_recent_etf_aum`, `upsert_etf_aum`)
- Modify: `src/uw_scan/pipeline.py:258-267` (cache check before fetch + structured failure marker)
- Test: `tests/integration/storage/test_repository_etf_aum.py` (new)
- Test: `tests/integration/test_pipeline_etf_caching.py` (new, or extend existing pipeline tests)

**Why:** Every ETF full scan triggers an extra UW `/etf_info` call. AUM changes weekly at most. With sharded UW workers (2× concurrency baseline) doing a full scan on the ETF tail of the watchlist, this is wasted QPS. A 7-day cache eliminates ~99% of these calls.

**Design choice:** Dedicated `etf_aum_cache` table with `ticker PRIMARY KEY, aum NUMERIC, fetched_at TIMESTAMPTZ`. Simpler than re-extracting from `raw_payloads` JSONB. Tiny table (~hundreds of rows max).

- [ ] **Step 6.1: Write migration 029**

```sql
-- 029_etf_aum_cache.sql — A1 from backend code review addendum.
--
-- Caches the most recent AUM per ETF ticker so pipeline.py can skip the
-- per-scan /etf_info UW call when the cached value is fresh. AUM moves
-- weekly at most; a 7-day TTL gives ~99% cache hit rate.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.etf_aum_cache (
  ticker     TEXT PRIMARY KEY,
  aum        NUMERIC NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 6.2: Apply migration**

```bash
set -a; source ../../../.env; set +a
bash scripts/migrate.sh
```

- [ ] **Step 6.3: Add repo methods (per Codex ISSUE-8: normalize ticker case)**

```python
def get_recent_etf_aum(self, ticker: str, *, max_age: timedelta) -> Decimal | None:
    """Return cached AUM if fetched within max_age, else None.
    None means caller should fetch fresh (cache miss or stale)."""
    ticker = ticker.upper()  # normalize: cache keys are canonical UPPER
    with self._conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT aum FROM {self._schema}.etf_aum_cache
            WHERE ticker = %s AND fetched_at > NOW() - %s
            """,
            (ticker, max_age),
        )
        row = cur.fetchone()
    return row[0] if row else None

def upsert_etf_aum(self, ticker: str, aum: Decimal) -> None:
    ticker = ticker.upper()  # normalize: cache keys are canonical UPPER
    with self._conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {self._schema}.etf_aum_cache (ticker, aum, fetched_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE
              SET aum = EXCLUDED.aum, fetched_at = EXCLUDED.fetched_at
            """,
            (ticker, aum),
        )
    self._conn.commit()
```

- [ ] **Step 6.4: Write failing integration test for repo methods**

```python
# tests/integration/storage/test_repository_etf_aum.py
from datetime import timedelta
from decimal import Decimal


def test_get_recent_etf_aum_returns_none_when_no_row(repo):
    assert repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7)) is None


def test_get_recent_etf_aum_returns_value_when_fresh(repo):
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))
    cached = repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7))
    assert cached == Decimal("500000000000")


def test_get_recent_etf_aum_returns_none_when_stale(repo):
    """Manually backdate fetched_at to past the TTL."""
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))
    with repo._conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.etf_aum_cache SET fetched_at = NOW() - INTERVAL '8 days' WHERE ticker='SPY'"
        )
    repo._conn.commit()
    assert repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7)) is None


def test_etf_aum_cache_normalizes_case(repo):
    """Per Codex ISSUE-8: mixed-case input must hit the same cache row."""
    repo.upsert_etf_aum("spy", Decimal("123"))     # lowercase upsert
    cached = repo.get_recent_etf_aum("SPY", max_age=timedelta(days=7))
    assert cached == Decimal("123")
```

- [ ] **Step 6.5: Run tests, confirm PASS**

```bash
uv run pytest tests/integration/storage/test_repository_etf_aum.py -v
```

- [ ] **Step 6.6: Extract `_get_or_fetch_etf_aum` helper in `pipeline.py`**

Pre-check confirmed there is NO existing pipeline harness that invokes `run_full_scan`/`run_single_stock` without a live UW key (`test_pipeline_e2e.py` is `live`-marked, skipped on CI). To address Codex ISSUE-6 ("repo tests don't prove wire-up"), extract the cache-or-fetch logic into a small helper that is directly unit-testable.

Add to `pipeline.py` (near the top of the module, after imports):

```python
ETF_AUM_TTL = timedelta(days=7)


def _get_or_fetch_etf_aum(
    *,
    ticker: str,
    repo: Repository,
    client: UwClient,
    run_id: int,
) -> Decimal | None:
    """Cache-or-fetch ETF AUM. Returns the cached value when fresh, otherwise
    fetches from UW, upserts the result, and returns it. Returns None when both
    cache and fetch yield no value (caller treats this as 'no AUM data')."""
    cached = repo.get_recent_etf_aum(ticker, max_age=ETF_AUM_TTL)
    if cached is not None:
        return cached
    try:
        etf_info = uw_sources.fetch_etf_info(client, repo, run_id, ticker)
    except Exception as exc:  # noqa: BLE001 — card sort hint only; never break scan
        logger.warning(
            "ETF info fetch failed for %s: %s — using None aum (sort will demote)",
            ticker, repr(exc),
        )
        return None
    aum = etf_info.aum
    if aum is not None:
        repo.upsert_etf_aum(ticker, aum)
    return aum
```

Then replace pipeline.py:258-267 (the inline ETF block) with a one-line call:

```python
etf_aum = None
if (screener_row.issue_type or "").upper() == "ETF":
    etf_aum = _get_or_fetch_etf_aum(
        ticker=ticker, repo=repo, client=client, run_id=run_id,
    )
```

`★ Insight ─────────────────────────────────────`
Extracting the helper is the right shape for two reasons. (1) It turns "wire-up correctness" into a directly testable function — no need to spin up a fake UW pipeline. (2) It keeps `noqa: BLE001` localized to the helper's `except Exception`, where the surrounding context (`# card sort hint only; never break scan`) explains WHY broad-catch is correct. CI Guardrail 2's `repr(exc)` is satisfied by the `logger.warning(..., repr(exc))` line.
`─────────────────────────────────────────────────`

- [ ] **Step 6.7: Unit test the helper (REQUIRED per Codex ISSUE-6)**

```python
# tests/integration/test_pipeline_etf_caching.py (new file)
from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

# Reuse the repo fixture pattern from test_pipeline_aggregates.py
# (DROP SCHEMA + migrate.sh, returns a Repository pointed at the test DB).
from .conftest import repo  # noqa: F401 — fixture re-export

from uw_scan.pipeline import _get_or_fetch_etf_aum


class _StubClient:
    """Minimal stand-in for UwClient. _get_or_fetch_etf_aum only passes it
    through to uw_sources.fetch_etf_info, so we control behavior via
    monkeypatch on fetch_etf_info, not on the client."""


class _StubEtfInfo:
    def __init__(self, aum: Decimal | None) -> None:
        self.aum = aum


def test_get_or_fetch_etf_aum_returns_cached_value_when_fresh(repo, monkeypatch):
    """Cache hit — must NOT call UW."""
    repo.upsert_etf_aum("SPY", Decimal("500000000000"))

    def _should_not_call(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("fetch_etf_info called despite fresh cache")

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _should_not_call)

    out = _get_or_fetch_etf_aum(
        ticker="SPY", repo=repo, client=_StubClient(), run_id=1,
    )
    assert out == Decimal("500000000000")


def test_get_or_fetch_etf_aum_fetches_and_upserts_on_miss(repo, monkeypatch):
    """Cache miss — calls UW, upserts result, returns it."""
    call_count = {"n": 0}

    def _fake_fetch(*args: Any, **kwargs: Any) -> _StubEtfInfo:
        call_count["n"] += 1
        return _StubEtfInfo(aum=Decimal("123"))

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _fake_fetch)

    out = _get_or_fetch_etf_aum(
        ticker="QQQ", repo=repo, client=_StubClient(), run_id=1,
    )
    assert out == Decimal("123")
    assert call_count["n"] == 1
    # Verify upsert landed.
    from datetime import timedelta
    cached = repo.get_recent_etf_aum("QQQ", max_age=timedelta(days=7))
    assert cached == Decimal("123")


def test_get_or_fetch_etf_aum_returns_none_when_fetch_raises(repo, monkeypatch):
    """Fetch failure must NOT raise — returns None so the scan continues."""
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("UW 500")

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _boom)

    out = _get_or_fetch_etf_aum(
        ticker="ZZZ", repo=repo, client=_StubClient(), run_id=1,
    )
    assert out is None


def test_get_or_fetch_etf_aum_returns_none_when_uw_returns_none_aum(repo, monkeypatch):
    """If UW returns an ETF row with aum=None, we don't cache (would always be
    stale to the next caller) and we return None."""
    def _fake_fetch(*args: Any, **kwargs: Any) -> _StubEtfInfo:
        return _StubEtfInfo(aum=None)

    monkeypatch.setattr("uw_scan.pipeline.uw_sources.fetch_etf_info", _fake_fetch)

    out = _get_or_fetch_etf_aum(
        ticker="ZZZ", repo=repo, client=_StubClient(), run_id=1,
    )
    assert out is None
    from datetime import timedelta
    assert repo.get_recent_etf_aum("ZZZ", max_age=timedelta(days=7)) is None
```

This covers the 4 wire-up paths: cache-hit (skip fetch), cache-miss + success (fetch + upsert), cache-miss + raise (graceful None), cache-miss + None aum (no spurious cache write).

- [ ] **Step 6.8: Commit**

```bash
git add src/uw_scan/storage/migrations/029_etf_aum_cache.sql src/uw_scan/storage/repository.py src/uw_scan/pipeline.py tests/integration/storage/test_repository_etf_aum.py
git commit -m "perf(pipeline): cache ETF AUM to skip per-scan UW round trip"
```

---

## Final checks (before PR)

- [ ] **Run full test suite:** `uv run pytest`
- [ ] **Run lint guardrails:** `uv run python scripts/_lint_except.py src`
- [ ] **Regenerate types if API surface changed:** `cd web && npm run gen:types && git diff lib/types.ts` (Task 5's tuple return is internal — no schema change expected; verify.)
- [ ] **Idempotency check:** re-run `bash scripts/migrate.sh` — should be a no-op.
- [ ] **Open PR with `fix/` prefix branch:** branch is already `fix/backend-nseries-and-a1`.

## Out of scope (defer)

- §4 Nits (stylistic clarifications) — defer to a future "chore: polish" PR or roll into the modularization work
- Section §6 large-file splits — separate worktree
- Modularization §R2–R8 — separate worktree
- Performance findings P1, P3, P5 — separate "perf" worktree if needed

## Deployment notes

- **Migration 028 (N6):** safe to apply anytime. Pure index add.
- **Migration 029 (A1):** safe to apply anytime. Table starts empty; pipeline gracefully handles cache misses.
- **Task 5 (N8):** API response shape unchanged — only repo return type changes. No FE coordination needed.
- **Task 3 (N5):** if `_KNOWN_FIELDS` drifts from the SELECT post-merge, every `/api/watchlist` request fails loudly. This is the intended behavior — catches schema drift at the seam — but means a forgotten `_KNOWN_FIELDS` update during a future watchlist column add will surface immediately, not silently.
