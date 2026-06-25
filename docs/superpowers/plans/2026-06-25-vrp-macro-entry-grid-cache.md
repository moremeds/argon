# VRP Macro Entry-Capture — Strike-Grid Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the daily SPX entry-capture birth from crashing on UW's exhausted daily quota by moving the listed-strike enumeration to a nightly fresh-budget job and having the RTH birth read a cached, real-strike grid (zero UW at birth time).

**Architecture:** Birth needs two things that are never fresh at the same hour — UW budget (fresh only before ~08:00 ET, after the 00:00 UTC reset) and live WS quotes (fresh only during RTH). We decouple them: a new nightly job `vrp_macro_entry_grid_refresh` (03:50 ET, when the UW budget is fresh) calls the existing `_uw_chain_strikes` and caches the **real** UW-listed expiry + put strikes into a new `vrp_macro_entry_grid` table. The RTH birth (`_birth_auto`) and the on-demand button (`capture_entry_now`) read that cache instead of calling UW inline. The cache read falls back to the most-recent prior day whose chosen expiry is still in the future, so a single missed nightly refresh reuses yesterday's real grid rather than skipping birth. No synthetic strikes — the grid is always UW-sourced listed strikes.

**Tech Stack:** Python 3.13 (`uv`), psycopg 3, APScheduler 3, pytest + pytest-postgresql. SQL migrations are idempotent, applied lexically by `scripts/migrate.sh`.

## Global Constraints

- **uv only** — run tests with `uv run pytest`, never bare `pytest`.
- **No synthetic / fabricated market data** — the cached grid must be real UW-listed strikes. Never persist a synthetic strike grid into the capture path (the synthetic 5-pt grid in `_bs_indicative_legs` is for the throwaway *preview* display only, never persisted).
- **Migrations idempotent** — `CREATE TABLE IF NOT EXISTS`, `ON CONFLICT DO NOTHING/DO UPDATE`. No tracking table; re-running is a no-op. Header every migration with `SET search_path TO uw_scan, public;`.
- **Persist analytical results to Postgres** — the grid cache is a Postgres table.
- **New persistence methods go in the domain mixin** (`storage/vrp_macro_entry.py` → `_VrpMacroEntryMixin`), never appended to `repository.py`.
- **Module size budget** — keep `worker/jobs/vrp_macro_entry.py` under 500 lines (it is 447 today; this plan adds the grid-refresh job + the `_uw_chain_strikes` failure-closure, landing ~490 — under budget but near it. If a reviewer wants headroom, the grid-refresh job is the clean extract candidate; not required now).
- **ET timezone for crons** — `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`. APScheduler weekday `0-4` = Mon–Fri.
- **Worker-role single-flight** — the new nightly job is gated by the existing `_should_schedule_vrp_macro_entry` (massive-0 or `all`, and `vrp_macro_entry_capture_enabled`).
- **Migration number 088** — `086`/`087` are reserved by the in-flight `data-quality-coverage` branch; use `088` to avoid a lexical collision regardless of merge order.
- **Decimal round-trips natively** — psycopg returns `NUMERIC[]` as `list[Decimal]`; cast to `float` at the resolve boundary.
- **Never commit without explicit user request** is the repo default, BUT this plan is executed under subagent-driven/executing-plans where each task ends in a commit — those per-task commits ARE the requested commits for this task. Do not push or open the PR until the user asks.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/uw_scan/storage/migrations/088_vrp_macro_entry_grid.sql` | The `vrp_macro_entry_grid` cache table | Create |
| `src/uw_scan/storage/vrp_macro_entry.py` | `_VrpMacroEntryMixin` — add `upsert_vrp_macro_entry_grid` + `fetch_vrp_macro_entry_grid` | Modify |
| `src/uw_scan/worker/jobs/vrp_macro_entry.py` | Add `vrp_macro_entry_grid_refresh` job; add `run_notes` + failure-closure to `_uw_chain_strikes`; refactor `_birth_auto` + `capture_entry_now` to read the cache | Modify |
| `src/uw_scan/worker/scheduler.py` | Register the nightly grid-refresh job at 03:50 ET | Modify |
| `tests/integration/test_vrp_macro_entry_storage.py` | Grid round-trip + stale-fallback + staleness-bound + empty-CHECK tests | Modify |
| `tests/integration/test_vrp_macro_entry_job.py` | Seed cache before birth; cold-cache skip, grid-refresh, zero-UW-birth provenance, button-cache, scan-run-closure tests | Modify |
| `tests/unit/worker/test_vrp_macro_entry_schedule.py` | Assert registration/gating + the 03:50 cron timing | Modify |
| `CHANGELOG.md` | `[Unreleased]` entry | Modify |
| `CLAUDE.md` + `src/uw_scan/worker/CLAUDE.md` | Where-to-look pointer + schedule table row | Modify |

---

### Task 1: Grid-cache table + storage read/write

**Files:**
- Create: `src/uw_scan/storage/migrations/088_vrp_macro_entry_grid.sql`
- Modify: `src/uw_scan/storage/vrp_macro_entry.py` (add two methods to `_VrpMacroEntryMixin`)
- Test: `tests/integration/test_vrp_macro_entry_storage.py`

**Interfaces:**
- Produces:
  - `Repository.upsert_vrp_macro_entry_grid(*, name: str, for_date: date, chosen_expiry: date, strikes: list[float]) -> None`
  - `Repository.fetch_vrp_macro_entry_grid(name: str, for_date: date) -> dict[str, Any] | None` — returns `{"for_date", "chosen_expiry", "strikes", "fetched_at"}` for the most-recent row with `for_date <= given` AND `chosen_expiry > given`, else `None`. `strikes` is `list[Decimal]`.

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/088_vrp_macro_entry_grid.sql`:

```sql
-- 088_vrp_macro_entry_grid.sql
-- Nightly cache of SPX's listed-strike grid (real UW strikes) for the ~43-DTE
-- expiry, so the RTH entry-capture birth reads it instead of calling UW (whose
-- daily budget is reliably exhausted by ~08:00 ET, before the 10:00 birth cron).
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_entry_grid (
    name          TEXT        NOT NULL DEFAULT 'SPX',
    for_date      DATE        NOT NULL,
    chosen_expiry DATE        NOT NULL,
    strikes       NUMERIC[]   NOT NULL,   -- real UW-listed put strikes, sorted asc
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (name, for_date),
    -- An empty grid is useless (birth can't bracket a delta target) and would
    -- shadow the stale-fallback. Reject it at the DB so no caller can persist {}.
    CONSTRAINT vrp_macro_entry_grid_nonempty CHECK (cardinality(strikes) > 0)
);

COMMIT;
```

- [ ] **Step 2: Apply the migration locally and confirm idempotency**

Run:
```bash
bash scripts/migrate.sh && bash scripts/migrate.sh
```
Expected: both runs succeed, no error on the second run (idempotent).

- [ ] **Step 3: Write the failing storage test**

Append to `tests/integration/test_vrp_macro_entry_storage.py`:

```python
def test_grid_cache_upsert_and_fetch(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 24),
        chosen_expiry=date(2026, 8, 6),
        strikes=[6865.0, 6870.0, 7085.0, 7090.0],
    )
    # same (name, for_date) overwrites
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 24),
        chosen_expiry=date(2026, 8, 6),
        strikes=[6860.0, 6865.0, 7085.0, 7090.0, 7095.0],
    )
    got = repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 24))
    assert got is not None
    assert got["chosen_expiry"] == date(2026, 8, 6)
    assert [float(s) for s in got["strikes"]] == [6860.0, 6865.0, 7085.0, 7090.0, 7095.0]


def test_grid_cache_stale_fallback_and_expiry_guard(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    # a grid cached two days earlier, expiry still open
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 22),
        chosen_expiry=date(2026, 8, 4),
        strikes=[6865.0, 7090.0],
    )
    # asking 2 days later (within the 4-day staleness window) reuses the prior grid
    got = repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 24))
    assert got is not None and got["for_date"] == date(2026, 6, 22)
    # but a grid older than the staleness bound is NOT reused (would birth too-near
    # an expiry vs the intended ~43 DTE) → skip, don't persist an off-strategy cohort
    assert repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 27)) is None
    # never reuse a grid whose chosen expiry has already passed
    assert repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 8, 5)) is None
    # cold cache for an unknown name → None
    assert repo.fetch_vrp_macro_entry_grid("QQQ", date(2026, 6, 24)) is None


def test_grid_cache_rejects_empty_strikes(seeded_db_empty_cards: Repository):
    import psycopg

    repo = seeded_db_empty_cards
    # the DB CHECK forbids an empty grid (a useless row that would shadow the
    # stale-fallback and break birth's leg resolution)
    try:
        repo.upsert_vrp_macro_entry_grid(
            name="SPX", for_date=date(2026, 6, 24),
            chosen_expiry=date(2026, 8, 6), strikes=[],
        )
        raised = False
    except psycopg.errors.CheckViolation:
        repo.conn.rollback()
        raised = True
    assert raised
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_vrp_macro_entry_storage.py::test_grid_cache_upsert_and_fetch -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'upsert_vrp_macro_entry_grid'`.

- [ ] **Step 5: Implement the two storage methods**

In `src/uw_scan/storage/vrp_macro_entry.py`, first extend the datetime import at the top of the file from `from datetime import date as _date` to:

```python
from datetime import date as _date, timedelta
```

Then add these two methods inside the `_VrpMacroEntryMixin` class (e.g. after `insert_vrp_macro_entry_quotes`). Note `Any` is already imported at the top of the file.

```python
    def upsert_vrp_macro_entry_grid(
        self,
        *,
        name: str,
        for_date: _date,
        chosen_expiry: _date,
        strikes: list[float],
    ) -> None:
        """Cache the day's real UW-listed strike grid for the ~43-DTE expiry.

        The RTH birth path reads this instead of calling UW, which 429s once the
        daily budget is spent (reliably before the 10:00 ET birth cron). Idempotent
        upsert on (name, for_date) — a restart re-fetch overwrites in place."""
        sql = (
            f"INSERT INTO {self._schema}.vrp_macro_entry_grid "
            "(name, for_date, chosen_expiry, strikes) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (name, for_date) DO UPDATE SET "
            "chosen_expiry = EXCLUDED.chosen_expiry, strikes = EXCLUDED.strikes, "
            "fetched_at = now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (name, for_date, chosen_expiry, list(strikes)))

    def fetch_vrp_macro_entry_grid(
        self, name: str, for_date: _date, *, max_staleness_days: int = 4
    ) -> dict[str, Any] | None:
        """Most-recent cached grid in the window [for_date - max_staleness_days,
        for_date] whose chosen expiry is still in the future. Returns
        {for_date, chosen_expiry, strikes, fetched_at} (strikes = list[Decimal])
        or None if the cache is cold / only holds too-old or expired grids.

        Why the staleness bound: the strategy births at ~43 calendar DTE. A single
        missed nightly refresh should reuse yesterday's REAL grid (its chosen expiry
        is only ~1 day nearer — fine), but a grid many days old would birth a
        materially-nearer-DTE cohort (e.g. a 43-DTE grid reused at 5 DTE). Beyond
        the bound we'd rather skip birth (logged) than persist an off-strategy
        cohort. ``chosen_expiry > for_date`` additionally rejects an already-expired
        cached expiry within the window."""
        sql = (
            "SELECT for_date, chosen_expiry, strikes, fetched_at "
            f"FROM {self._schema}.vrp_macro_entry_grid "
            "WHERE name = %s AND for_date BETWEEN %s AND %s AND chosen_expiry > %s "
            "ORDER BY for_date DESC LIMIT 1"
        )
        oldest = for_date - timedelta(days=max_staleness_days)
        with self._conn.cursor() as cur:
            cur.execute(sql, (name, oldest, for_date, for_date))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))
```

- [ ] **Step 6: Run the storage tests to verify they pass**

Run: `uv run pytest tests/integration/test_vrp_macro_entry_storage.py -v`
Expected: PASS (all tests, including the two new ones).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/migrations/088_vrp_macro_entry_grid.sql src/uw_scan/storage/vrp_macro_entry.py tests/integration/test_vrp_macro_entry_storage.py
git commit -m "feat(vrp-entry): grid cache table + storage read/write"
```

---

### Task 2: Grid-refresh job + birth/button read from cache

**Files:**
- Modify: `src/uw_scan/worker/jobs/vrp_macro_entry.py`
- Test: `tests/integration/test_vrp_macro_entry_job.py`

**Interfaces:**
- Consumes (from Task 1): `repo.upsert_vrp_macro_entry_grid(...)`, `repo.fetch_vrp_macro_entry_grid(name, for_date)`.
- Produces:
  - `vrp_macro_entry_grid_refresh(repo: Repository, settings: Settings, *, now: datetime | None = None) -> dict` — fetches SPX's listed grid via the existing `_uw_chain_strikes`, upserts it, returns `{"chosen_expiry": date, "strikes": int}`.
  - `_birth_auto` now reads the cache; cold cache → logs `reason=no_cached_grid` and returns `0` (no crash, no UW call).
  - `capture_entry_now` reads the cache first; only falls back to inline `_uw_chain_strikes` on a cold cache.

- [ ] **Step 1: Update the existing job test to seed the cache (it will fail first)**

The refactor makes `_birth_auto` read the grid cache instead of calling `_uw_chain_strikes`. The existing `test_birth_then_snapshot` stubs `_uw_chain_strikes`, so after the refactor birth would find a cold cache and skip. Update the test to seed the cache and add new tests.

First, update the `_fake_chain` stub to accept the new `run_notes` keyword (the grid-refresh job passes it):

```python
def _fake_chain(repo, settings, symbol, on_date, **_kw):
    return _EXPIRY, _STRIKES
```

In `tests/integration/test_vrp_macro_entry_job.py`, edit `test_birth_then_snapshot` to seed the grid cache right after the intraday-quote upsert (before the first `vrp_macro_entry_snapshot_once` call):

```python
    repo.conn.commit()
    _stub_uw(monkeypatch)
    repo.upsert_vrp_macro_entry_grid(
        name="SPX", for_date=_NOW.astimezone(_ET).date(),
        chosen_expiry=_EXPIRY, strikes=_STRIKES,
    )
    repo.conn.commit()
    settings = _settings()
```

Then append two new tests to the same file:

```python
def test_birth_skipped_when_grid_cache_cold(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.conn.commit()
    _stub_uw(monkeypatch)  # _uw_chain_strikes stubbed, but birth must NOT call it
    settings = _settings()

    # fresh quotes but no cached grid → birth skips cleanly, no cohort, no crash
    out = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=True, now=_NOW
    )
    assert out["births"] == 0
    on_date = _NOW.astimezone(_ET).date()
    assert repo.fetch_open_vrp_macro_entries("SPX", on_date) == []


def test_grid_refresh_caches_listed_strikes(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    monkeypatch.setattr(J, "_uw_chain_strikes", _fake_chain)
    settings = _settings()

    out = J.vrp_macro_entry_grid_refresh(repo, settings, now=_NOW)
    assert out["chosen_expiry"] == _EXPIRY and out["strikes"] == len(_STRIKES)

    # rollback first: proves the JOB committed (a scheduled _repo conn would close
    # and discard an uncommitted row, leaving the 10:00 birth cold). The row must
    # survive a rollback on this same connection.
    repo.conn.rollback()
    on_date = _NOW.astimezone(_ET).date()
    got = repo.fetch_vrp_macro_entry_grid("SPX", on_date)
    assert got is not None and got["chosen_expiry"] == _EXPIRY
    assert len(got["strikes"]) == len(_STRIKES)


def test_birth_succeeds_when_uw_would_429(seeded_db_empty_cards, monkeypatch):
    """The regression test for the bug: with a warm grid cache, birth must NOT
    touch UW — so even if the UW chain enumeration would raise (429), birth still
    persists the cohort."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.upsert_vrp_macro_entry_grid(
        name="SPX", for_date=_NOW.astimezone(_ET).date(),
        chosen_expiry=_EXPIRY, strikes=_STRIKES,
    )
    repo.conn.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("UW HTTP 429 daily_request_limit_hit")

    monkeypatch.setattr(J, "_uw_chain_strikes", _boom)
    monkeypatch.setattr(J, "_uw_leg_nbbo", lambda *a, **k: {})
    monkeypatch.setattr(J, "quote_leg", _fake_quote_leg)
    settings = _settings()

    out = J.vrp_macro_entry_snapshot_once(
        repo, settings, session="rth", birth=True, now=_NOW
    )
    assert out["births"] == 1 and out["cohorts"] == 1 and out["quotes"] == 4

    # provenance: the persisted cohort must use the REAL cached grid — its expiry
    # and all four leg strikes are drawn from the seeded grid, never synthesised.
    on_date = _NOW.astimezone(_ET).date()
    cohort = repo.fetch_open_vrp_macro_entries("SPX", on_date)[0]
    assert cohort["expiry"] == _EXPIRY
    listed = set(_STRIKES)
    assert all(float(cohort[leg]) in listed for leg in J._LEG_FIELDS)
    # and they bracket sensibly: wings strictly below the shorts (OTM puts)
    assert float(cohort["wing_above"]) < float(cohort["short_above"])
    assert float(cohort["wing_below"]) < float(cohort["short_below"])


def test_capture_button_uses_grid_cache(seeded_db_empty_cards, monkeypatch):
    """The on-demand Capture button reads the cache too (so it works mid-RTH when
    UW is exhausted): with a warm cache it persists a one-shot 'button' cohort + 4
    legs without calling the UW chain enumeration."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), _QUOTED, "xenon_ws"),
            ("VIX", Decimal("25.5"), _QUOTED, "xenon_ws"),
        ]
    )
    repo.upsert_vrp_macro_entry_grid(
        name="SPX", for_date=_NOW.astimezone(_ET).date(),
        chosen_expiry=_EXPIRY, strikes=_STRIKES,
    )
    repo.conn.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("UW HTTP 429 — button must not hit UW when cache warm")

    monkeypatch.setattr(J, "_uw_chain_strikes", _boom)
    monkeypatch.setattr(J, "_uw_leg_nbbo", lambda *a, **k: {})
    monkeypatch.setattr(J, "quote_leg", _fake_quote_leg)
    settings = _settings()

    entry_id = J.capture_entry_now(repo, settings, now=_NOW)
    header = repo.fetch_vrp_macro_entry(entry_id)
    assert header is not None and header["origin"] == "button"
    quotes = repo.fetch_vrp_macro_entry_quotes(entry_id)
    assert len(quotes) == 4 and {q["leg"] for q in quotes} == set(J._LEG_FIELDS)


def test_uw_chain_strikes_closes_run_on_failure(seeded_db_empty_cards, monkeypatch):
    """A UW failure inside _uw_chain_strikes must not leave a stuck 'running'
    scan_run (the original-bug symptom). insert_scan_run commits the row up front,
    so the failure path has to close it."""
    import pytest

    monkeypatch.setenv("UW_SCAN_API_KEY", "test-key")  # UwClient ctor reads it
    repo = seeded_db_empty_cards
    settings = _settings()

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def close(self):
            pass

    def _boom(*_a, **_k):
        raise RuntimeError("UW 5xx during expiry enumeration")

    monkeypatch.setattr(J, "UwClient", _FakeClient)
    monkeypatch.setattr(J, "fetch_greek_exposure_by_expiry", _boom)

    with pytest.raises(RuntimeError):
        J._uw_chain_strikes(
            repo, settings, "SPX", date(2026, 6, 24),
            run_notes="vrp_macro_entry_grid_refresh",
        )
    repo.conn.rollback()  # the test's own view; the committed failed-run survives
    rows = repo.conn.execute(
        "SELECT status FROM uw_scan.scan_runs "
        "WHERE notes = 'vrp_macro_entry_grid_refresh'"
    ).fetchall()
    # invariant: the run is terminal (closed-failed), never left 'running'
    assert rows and all(r[0] != "running" for r in rows)
```

- [ ] **Step 2: Run the job tests to verify the new ones fail**

Run: `uv run pytest tests/integration/test_vrp_macro_entry_job.py -v`
Expected (pre-refactor failures that the Task-2 code makes pass):
- `test_grid_refresh_caches_listed_strikes` → FAIL `AttributeError: module 'uw_scan.worker.jobs.vrp_macro_entry' has no attribute 'vrp_macro_entry_grid_refresh'`.
- `test_birth_succeeds_when_uw_would_429` → FAIL: old `_birth_auto` calls `_uw_chain_strikes` (stubbed to raise), the outer try/except logs `birth_failed`, so `births == 0` ≠ 1.
- `test_capture_button_uses_grid_cache` → ERROR: old `capture_entry_now` calls `_uw_chain_strikes` (stubbed to raise) with no guard, so the RuntimeError propagates.
- `test_uw_chain_strikes_closes_run_on_failure` → FAIL: the un-hardened `_uw_chain_strikes` leaves the committed scan_run in `running`, so `all(r[0] != "running")` is false. Step 3a's failure-closure makes it pass.
- `test_birth_skipped_when_grid_cache_cold` and the edited `test_birth_then_snapshot` may already pass (old birth ignores the cache); they lock the post-refactor contract.

- [ ] **Step 3a: Parametrize `_uw_chain_strikes`'s label + close its run on failure**

Two changes to `_uw_chain_strikes` in `src/uw_scan/worker/jobs/vrp_macro_entry.py`:

1. **`run_notes` param** — the nightly refresh reuses this function; without a distinct label its audit rows would masquerade as births (and the deploy cleanup for stuck births could match a refresh). Default preserves the birth label for the button cold-cache fallback.
2. **Close the scan_run on failure** — `insert_scan_run` commits the row immediately, so any later UW error (a 03:50 blip) currently leaves a stuck `running` row — the exact symptom of the original bug. Wrap the body to mark the run `failed` on error, then re-raise (callers still see the exception).

Replace the whole function with:

```python
def _uw_chain_strikes(
    repo: Repository,
    settings: Settings,
    symbol: str,
    on_date: _date,
    *,
    run_notes: str = "vrp_macro_entry_birth",
) -> tuple[_date, list[float]]:
    """(chosen_expiry, sorted listed PUT strikes) for the listed expiry nearest
    ``on_date + ~43cal``. Enumerates expiries via greek-exposure/expiry, then
    pulls the chosen expiry's contracts (strikes parsed from each OCC symbol).
    Audit-first UW calls under their own scan_run; the run is closed (failed) on
    error so a UW blip can't leave a stuck 'running' row (the original-bug symptom)."""
    client = UwClient(
        api_key=settings.api_key.get_secret_value(), job_name="vrp_macro_entry"
    )
    run_id: int | None = None
    try:
        run_id = repo.insert_scan_run(symbol, notes=run_notes)
        gex = fetch_greek_exposure_by_expiry(client, repo, run_id, symbol)
        expiries = sorted({r.expiry for r in gex if r.expiry > on_date})
        if not expiries:
            raise ValueError(f"{symbol}: no listed expiry after {on_date}")
        target = on_date + timedelta(days=_TARGET_CAL_DAYS)
        chosen = min(expiries, key=lambda e: abs((e - target).days))
        contracts = fetch_option_contracts_by_expiry(
            client, repo, run_id, symbol, chosen.isoformat()
        )
        strikes: set[float] = set()
        for c in contracts:
            parsed = _parse_occ(c.option_symbol)
            if parsed is None:
                continue
            exp, opt_type, strike = parsed
            if opt_type == "P" and exp == chosen:
                strikes.add(float(strike))
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        return chosen, sorted(strikes)
    except Exception as exc:
        # Roll back the aborted tx, then close the (already-committed) run so it
        # can't dangle in 'running'. Re-raise so callers see the original failure.
        repo.conn.rollback()
        if run_id is not None:
            try:
                repo.finish_scan_run(run_id, status=f"failed: {exc!r}"[:400])
                repo.conn.commit()
            except Exception as close_exc:  # never mask the original error
                logger.debug("scan_run close failed: %s", repr(close_exc))
                repo.conn.rollback()
        raise
    finally:
        client.close()
```

This expands the originally-minimal `run_notes`-only change because Pass-3 adversarial review found the 03:50 refresh would otherwise reintroduce stuck `running` rows on a UW blip. Both `except` blocks satisfy CI Guardrail 2 (`raise` / `repr(close_exc)`).

- [ ] **Step 3b: Add the grid-refresh job function**

In `src/uw_scan/worker/jobs/vrp_macro_entry.py`, add this function after `_uw_chain_strikes`:

```python
def vrp_macro_entry_grid_refresh(
    repo: Repository, settings: Settings, *, now: datetime | None = None
) -> dict:
    """Nightly fresh-UW-budget job: enumerate SPX's listed-strike grid for the
    ~43-DTE expiry and cache it, so the RTH birth path needs ZERO UW.

    Runs at 03:50 ET — after the 00:00 UTC daily-quota reset and well before the
    always-on stack exhausts the budget (~08:00 ET) and the 10:00 ET birth crons.
    Idempotent: upserts on (name, for_date)."""
    now = now or datetime.now(_ET)
    on_date = now.astimezone(_ET).date()
    chosen_expiry, strikes = _uw_chain_strikes(
        repo, settings, "SPX", on_date, run_notes="vrp_macro_entry_grid_refresh"
    )
    if not strikes:
        # Never overwrite a good cached grid with an empty one — leave the prior
        # day's real grid in place for the stale-fallback to reuse.
        logger.warning(
            "vrp_macro_entry_grid_refresh_skipped reason=empty_grid expiry=%s",
            chosen_expiry,
        )
        return {"chosen_expiry": chosen_expiry, "strikes": 0}
    repo.upsert_vrp_macro_entry_grid(
        name="SPX", for_date=on_date, chosen_expiry=chosen_expiry, strikes=strikes
    )
    repo.conn.commit()
    logger.info(
        "vrp_macro_entry_grid_refresh name=SPX expiry=%s strikes=%d",
        chosen_expiry,
        len(strikes),
    )
    return {"chosen_expiry": chosen_expiry, "strikes": len(strikes)}
```

- [ ] **Step 4: Refactor `_birth_auto` to read the cache**

In `src/uw_scan/worker/jobs/vrp_macro_entry.py`, replace the body of `_birth_auto` (the inline `_uw_chain_strikes` call) so it reads the cache. The new full function:

```python
def _birth_auto(repo: Repository, settings: Settings, *, on_date, now, rfr) -> int:
    """Birth today's auto cohort iff fresh SPX+VIX quotes resolve the live signal
    AND a cached strike grid exists. No EOD fallback for birth (codex ISSUE-3): a
    holiday/WS-gap day would birth off a stale close and pollute the daily stride.
    The grid comes from the nightly vrp_macro_entry_grid_refresh cache — birth makes
    ZERO UW calls, so an exhausted daily budget can no longer abort it."""
    quotes = load_live_quotes(
        repo,
        ["SPX", "VIX"],
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
        now=now,
    )
    spx, vix = quotes.get("SPX"), quotes.get("VIX")
    if spx is None or vix is None:
        logger.info("vrp_macro_entry_birth_skipped reason=no_fresh_quote")
        return 0
    grid = repo.fetch_vrp_macro_entry_grid("SPX", on_date)
    if grid is None:
        logger.warning("vrp_macro_entry_birth_skipped reason=no_cached_grid")
        return 0
    sig = current_macro_signal_live(
        repo,
        settings,
        "SPX",
        WINNER,
        live_spot=float(spx.price),
        live_iv=float(vix.price) / 100.0,
    )
    chosen_expiry = grid["chosen_expiry"]
    strikes = [float(s) for s in grid["strikes"]]
    ec = _resolve_legs(
        sig, on_date=on_date, chosen_expiry=chosen_expiry, strikes=strikes, rfr=rfr
    )
    _insert_cohort(
        repo,
        sig,
        origin="auto",
        on_date=on_date,
        now=now,
        chosen_expiry=chosen_expiry,
        ec=ec,
    )
    repo.conn.commit()
    logger.info(
        "vrp_macro_entry_birth name=SPX expiry=%s action=%s", chosen_expiry, sig.action
    )
    return 1
```

- [ ] **Step 5: Refactor `capture_entry_now` to prefer the cache**

In `src/uw_scan/worker/jobs/vrp_macro_entry.py`, inside `capture_entry_now`, replace the single line:

```python
    chosen_expiry, strikes = _uw_chain_strikes(repo, settings, "SPX", on_date)
```

with a cache-first read (the button is a deliberate user action, so an inline UW call on a cold cache is acceptable):

```python
    grid = repo.fetch_vrp_macro_entry_grid("SPX", on_date)
    if grid is not None:
        chosen_expiry = grid["chosen_expiry"]
        strikes = [float(s) for s in grid["strikes"]]
    else:
        # cold cache (e.g. day-1 post-deploy) — button is a user action, so a live
        # UW enumeration here is acceptable (unlike the unattended auto birth).
        chosen_expiry, strikes = _uw_chain_strikes(repo, settings, "SPX", on_date)
```

- [ ] **Step 6: Run the full job test file to verify all pass**

Run: `uv run pytest tests/integration/test_vrp_macro_entry_job.py -v`
Expected: PASS — all of: `test_birth_then_snapshot` (now seeds the cache), `test_birth_skipped_when_grid_cache_cold`, `test_grid_refresh_caches_listed_strikes`, `test_birth_succeeds_when_uw_would_429`, `test_capture_button_uses_grid_cache`, `test_uw_chain_strikes_closes_run_on_failure`, `test_aged_cohort_eod_only`.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/worker/jobs/vrp_macro_entry.py tests/integration/test_vrp_macro_entry_job.py
git commit -m "feat(vrp-entry): nightly grid-refresh job; birth+button read cached grid (zero UW at birth)"
```

---

### Task 3: Register the nightly grid-refresh cron

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/unit/worker/test_vrp_macro_entry_schedule.py`

**Interfaces:**
- Consumes (from Task 2): `vrp_macro_entry_grid_refresh(repo, settings)`.
- Produces: an APScheduler job `id="vrp_macro_entry_grid_refresh"` at `50 3 * * 0-4` ET, gated by `_should_schedule_vrp_macro_entry`, `max_instances=1`, `coalesce=True`.

- [ ] **Step 1: Update the schedule unit test (failing)**

In `tests/unit/worker/test_vrp_macro_entry_schedule.py`:

(a) Add the new id to the `_ENTRY_IDS` set so the existing `test_jobs_registered_on_massive_zero` and `test_jobs_absent_when_disabled` cover registration + gating:

```python
_ENTRY_IDS = {
    "vrp_macro_entry_rth",
    "vrp_macro_entry_eod",
    "vrp_macro_entry_postclose",
    "vrp_macro_entry_grid_refresh",
}
```

(b) The fake scheduler currently drops the (positional) trigger. Capture it so we can assert cron timing. In `_registered_jobs`, change the `add_job` body from `jobs[kwargs["id"]] = kwargs` to also stash the trigger (additive — existing `jobs[jid]["max_instances"]` reads still work):

```python
        def add_job(self, *_a, **kwargs) -> None:
            if kwargs.get("id"):
                entry = dict(kwargs)
                entry["_trigger"] = _a[1] if len(_a) > 1 else None
                jobs[kwargs["id"]] = entry
```

(c) Add a timing test — the whole point of the fix is that this job fires in the fresh-UW-budget window (03:50 ET), NOT during RTH:

```python
def test_grid_refresh_fires_pre_market(monkeypatch):
    jobs = _registered_jobs(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    trig = str(jobs["vrp_macro_entry_grid_refresh"]["_trigger"])
    # CronTrigger repr looks like: cron[minute='50', hour='3', ...]
    assert "hour='3'" in trig and "minute='50'" in trig
```

- [ ] **Step 2: Run the schedule test to verify it fails**

Run: `uv run pytest tests/unit/worker/test_vrp_macro_entry_schedule.py -v`
Expected: `test_jobs_registered_on_massive_zero` and `test_grid_refresh_fires_pre_market` FAIL — `vrp_macro_entry_grid_refresh` not yet registered (`KeyError` / `_ENTRY_IDS <= set(jobs)` fails).

- [ ] **Step 3: Import the job function**

In `src/uw_scan/worker/scheduler.py`, update the existing import (currently `from uw_scan.worker.jobs.vrp_macro_entry import vrp_macro_entry_snapshot_once`) to also import the refresh job:

```python
from uw_scan.worker.jobs.vrp_macro_entry import (
    vrp_macro_entry_grid_refresh,
    vrp_macro_entry_snapshot_once,
)
```

- [ ] **Step 4: Add the job closure**

In `src/uw_scan/worker/scheduler.py`, next to the other `_vrp_macro_entry_*` closures (after `_vrp_macro_entry_postclose`), add:

```python
    def _vrp_macro_entry_grid_refresh() -> None:
        with _repo(settings) as repo:
            vrp_macro_entry_grid_refresh(repo, settings)
```

- [ ] **Step 5: Register the cron**

In `src/uw_scan/worker/scheduler.py`, inside the existing `if _should_schedule_vrp_macro_entry(settings):` block (after the `vrp_macro_entry_postclose` `add_job`), add:

```python
        # Nightly strike-grid cache @ 03:50 ET — fresh UW budget (after the 00:00
        # UTC reset, before the always-on stack exhausts it ~08:00 ET). Enumerates
        # SPX's listed strikes for the ~43-DTE expiry so the RTH birth reads the
        # cache and makes ZERO UW calls. Sits right after vrp_macro_signal_refresh
        # (03:45) in the nightly regime cluster.
        sched.add_job(
            _vrp_macro_entry_grid_refresh,
            CronTrigger.from_crontab("50 3 * * 0-4", timezone=settings.rth_tz),
            id="vrp_macro_entry_grid_refresh",
            name="VRP macro entry-capture (nightly strike-grid cache)",
            max_instances=1,
            coalesce=True,
        )
```

- [ ] **Step 6: Run the schedule tests to verify they pass**

Run: `uv run pytest tests/unit/worker/test_vrp_macro_entry_schedule.py -v`
Expected: PASS (all four tests).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/worker/scheduler.py tests/unit/worker/test_vrp_macro_entry_schedule.py
git commit -m "feat(vrp-entry): schedule nightly grid-refresh at 03:50 ET (massive-0)"
```

---

### Task 4: Docs + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `src/uw_scan/worker/CLAUDE.md` (schedule table)
- Modify: `CLAUDE.md` (where-to-look pointer for the entry-capture row)

- [ ] **Step 1: Add the CHANGELOG entry**

In `CHANGELOG.md`, under the `[Unreleased]` heading (create the section if absent, above the latest version), add:

```markdown
### Fixed

- **VRP macro entry-capture never persisted** — the daily SPX auto-birth
  (`_birth_auto`) enumerated the listed strike grid via two live UW calls inside
  the 10:00–15:00 ET birth crons, but the UW daily quota is reliably exhausted by
  ~08:00 ET, so every birth 429'd and aborted (`vrp_macro_entry` /
  `vrp_macro_entry_quote` stayed empty; the preview card silently fell back to the
  BS-`modeled` indicative legs). Added a nightly `vrp_macro_entry_grid_refresh`
  job (03:50 ET, massive-0, when the UW budget is fresh) that caches the real
  UW-listed expiry + put strikes into a new `vrp_macro_entry_grid` table
  (migration 088). The unattended auto-birth now reads that cache and makes **zero
  UW calls**, so an exhausted daily quota can no longer abort it; the on-demand
  Capture button reads the same cache (UW-free whenever the cache is warm, i.e.
  after the first nightly refresh — a cold-cache click still falls back to a live
  UW lookup). The cache read reuses the most-recent prior day's real grid (within
  a 4-day staleness bound, chosen expiry still open) if a nightly refresh is
  missed, rather than skipping birth. As part of this, `_uw_chain_strikes` now
  closes its `scan_runs` row as `failed` on a UW error instead of leaving it stuck
  in `running` (the visible side-symptom of the original bug).
```

- [ ] **Step 2: Add the schedule-table row**

In `src/uw_scan/worker/CLAUDE.md`, in the "Schedule" table, add a row after the `vrp_macro_signal_refresh` row:

```markdown
| `vrp_macro_entry_grid_refresh` | cron | `50 3 * * 0-4` (massive-0; caches SPX's real UW-listed ~43-DTE strike grid so the RTH entry-capture birth makes zero UW calls — runs after `vrp_macro_signal_refresh` at 03:45, in the fresh-UW-budget window) |
```

- [ ] **Step 3: Update the where-to-look pointer**

In `CLAUDE.md`, in the "VRP macro entry-capture (forward markout)" row of the "Where to look first" table, append after `migration 085`:

```
 + `storage/vrp_macro_entry.py` grid cache (`vrp_macro_entry_grid`, migration 088) — nightly `vrp_macro_entry_grid_refresh` @03:50 ET caches real UW-listed strikes so the RTH birth reads the cache and makes zero UW calls (the inline-UW birth 429'd daily and never persisted)
```

- [ ] **Step 4: Keep AGENTS.md in sync if the policy text changed**

The AGENTS.md root file mirrors CLAUDE.md standing rules; this change touches only the where-to-look table and schedule, not standing rules, so AGENTS.md needs no edit. Verify:

Run: `grep -n "vrp_macro_entry_grid" AGENTS.md || echo "no AGENTS.md change needed"`
Expected: `no AGENTS.md change needed`.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md src/uw_scan/worker/CLAUDE.md CLAUDE.md
git commit -m "docs(vrp-entry): changelog + schedule/where-to-look for grid cache"
```

---

### Task 5: Full-suite gate + deploy notes

**Files:** none (verification + operator notes).

- [ ] **Step 1: Run the affected test surface**

Run:
```bash
uv run pytest tests/integration/test_vrp_macro_entry_storage.py tests/integration/test_vrp_macro_entry_job.py tests/unit/worker/test_vrp_macro_entry_schedule.py -v
```
Expected: all PASS.

- [ ] **Step 2: Run ruff (the lint+unit CI job runs more than pytest)**

Run:
```bash
uv run ruff check src/uw_scan/storage/vrp_macro_entry.py src/uw_scan/worker/jobs/vrp_macro_entry.py src/uw_scan/worker/scheduler.py
```
Expected: no findings. (Guardrail 2 scans `except` blocks — this change adds none, but run it to be safe.)

- [ ] **Step 3: Record the deploy notes in the PR description (not code)**

The following are operator steps for after this merges and a release tag deploys to the mini — capture them in the PR body:

1. **Warm the cache for day-1.** The first nightly refresh runs at 03:50 ET the morning after deploy; until then the cache is cold and auto-birth skips. To capture same-day, run the refresh once manually on the mini against prod (fresh-budget window only, i.e. before ~08:00 ET or after ~20:00 ET). This mirrors the exact connection construction in `scheduler._repo` (`settings.db_dsn()` method + `settings.db_schema`):
   ```bash
   # on the mini, in the argon venv, with prod .env loaded:
   uv run python -c "import psycopg; from uw_scan.config import Settings; from uw_scan.storage.repository import Repository; from uw_scan.worker.jobs.vrp_macro_entry import vrp_macro_entry_grid_refresh as g; s=Settings.from_env(); c=psycopg.connect(s.db_dsn()); r=Repository(c, schema=s.db_schema); print(g(r, s)); c.commit(); c.close()"
   ```

2. **Close the two stuck `running` scan_runs** left by the old crashing births (cosmetic — they will never finish). Bound by date so this can never touch a future row (the nightly refresh is now labeled `vrp_macro_entry_grid_refresh`, not `_birth`, but the date bound is belt-and-suspenders):
   ```sql
   UPDATE uw_scan.scan_runs
   SET status = 'failed: superseded by grid-cache fix', finished_at = now()
   WHERE notes = 'vrp_macro_entry_birth'
     AND finished_at IS NULL
     AND started_at < DATE '2026-06-25';
   ```

3. **Verify after the first post-deploy RTH session:** `SELECT count(*) FROM uw_scan.vrp_macro_entry;` should be ≥ 1, and `/api/regime/vrp-macro-signal/entry/preview` should return legs with `source` of `xenon_ib`/`uw` (not `modeled`) and `as_of` non-null.

4. **Button caveat (honest scope):** the auto-birth is now fully UW-free. The Capture button is UW-free **whenever the cache is warm** — i.e. always after the first nightly refresh. On a cold cache (day-1 pre-warm) a Capture click still attempts a live `_uw_chain_strikes` and can 429 during exhausted-budget RTH (there is no other source of real listed strikes). Warming the cache (step 1) removes this window; do not advertise the button as unconditionally UW-free.

- [ ] **Step 4: Final commit (if any doc tweaks from review) — otherwise stop here and hand off to the user for PR.**

No code change in this task. Do NOT push or open the PR until the user explicitly asks (repo rule). When they do: push the branch and `gh pr create` per the global PR policy.

---

## Self-Review

**Spec coverage:**
- Root cause (birth 429s on exhausted UW budget during RTH) → Task 2 removes UW from the birth path. ✓
- Real (non-synthetic) strikes → Task 1 caches UW-listed strikes; Task 2 reads them; no synthetic grid enters persistence. ✓
- Decouple UW-budget need from live-quote need → Task 2/3 nightly job (UW, no quotes) + RTH birth (quotes, cached grid). ✓
- Single missed refresh resilience → Task 1 `for_date <=` + `chosen_expiry >` fallback. ✓
- Button path also fixed → Task 2 Step 5 + `test_capture_button_uses_grid_cache`. ✓
- Regression encoded → `test_birth_succeeds_when_uw_would_429` (warm cache → birth persists even when UW enumeration raises 429). ✓
- Empty-grid poisoning guarded → `vrp_macro_entry_grid_refresh` skips the upsert on an empty strike list, preserving the prior real grid for the stale-fallback. ✓
- Worker-role single-flight + capture-flag gate → Task 3 reuses `_should_schedule_vrp_macro_entry` (massive-0 / `all`, gated by `vrp_macro_entry_capture_enabled`); confirmed distinct from `_is_primary_worker` which `vrp_macro_signal_refresh` uses. ✓
- Cold-start / day-1 warming + stuck-run cleanup → Task 5 deploy notes. ✓

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — all code blocks are complete. The deploy one-liner mirrors `scheduler._repo` exactly (`settings.db_dsn()` + `settings.db_schema`), verified against the source.

**Type consistency:**
- `upsert_vrp_macro_entry_grid(*, name, for_date, chosen_expiry, strikes)` — same kwargs in Task 1 def, Task 2 job call, and all test seeds. ✓
- `fetch_vrp_macro_entry_grid(name, for_date, *, max_staleness_days=4)` returns `{"for_date","chosen_expiry","strikes","fetched_at"}` — consumers in Task 2 read `grid["chosen_expiry"]` and `grid["strikes"]` (cast `float(s)`). ✓
- `vrp_macro_entry_grid_refresh(repo, settings, *, now=None) -> {"chosen_expiry","strikes"}` — same signature in def (Task 2), scheduler closure (Task 3), and test (Task 2). ✓
- `_uw_chain_strikes(repo, settings, symbol, on_date, *, run_notes="vrp_macro_entry_birth") -> (date, list[float])` — the only change is the additive keyword-only `run_notes`; the refresh passes `"vrp_macro_entry_grid_refresh"`, the button keeps the default. The test stub `_fake_chain(..., **_kw)` absorbs it. ✓

**Pass-2 hardening (codex tribunal):**
- Stale-fallback bounded to ≤4 days + `chosen_expiry > for_date` (no off-strategy near-expiry births). ✓
- DB `CHECK (cardinality(strikes) > 0)` — empty grids impossible at any caller. ✓
- Regression test asserts provenance (persisted expiry + 4 strikes ∈ cached grid), not just counts. ✓
- Grid-refresh test rollback-checks the commit. ✓
- Schedule test asserts the cron fires 03:50 (fresh-budget window), not just registration. ✓
- Refresh tags its own scan-run label; deploy cleanup SQL date-bounded. ✓

**Pass-3 hardening (adversarial):**
- A UW blip during the 03:50 refresh would otherwise reintroduce stuck `running` scan_runs (since `insert_scan_run` commits up front). `_uw_chain_strikes` now closes its run as `failed` on error and re-raises — fixes the symptom for the new job AND the existing button path. Covered by `test_uw_chain_strikes_closes_run_on_failure`. ✓
- SQL, idempotency, the 4-day staleness window, the empty-grid CHECK, and the `list[float]`→`NUMERIC[]`→`list[Decimal]` round-trip were all empirically validated against the local DB during review (not just reasoned). ✓
