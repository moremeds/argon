# C12 — DevOps: Docker cutover + ops-hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the argon prod stack off launchd onto Docker (Colima + engine-wide Watchtower, xenon/apex house pattern) and land the ops-hardening detection+alerting layer that makes Watchtower's no-rollback tradeoff safe.

**Architecture:** Two tracks in one job. **Track A (ops-hardening, ships first, pre-cutover):** job-failure streaks on `/api/health`, per-job UW budget attribution, and one webhook alert sink wired to the existing failure conditions. **Track B (Docker cutover):** 2 images built by `release.yml` → GHCR → the existing xenon Watchtower auto-deploys; launchd app agents retire; host Postgres and backup agents stay put. Track A must be live in prod before Track B cutover, because Watchtower has no health-gated rollback — the alert sink becomes the primary detection layer.

**Tech Stack:** Python 3.13 / uv, FastAPI + Pydantic v2, psycopg 3, APScheduler 3 (`BlockingScheduler`), Docker + docker-compose (mini brew v5.1.3, hyphenated), Colima, Watchtower, GitHub Actions (`ubuntu-24.04-arm`), GHCR, httpx (alert sink).

**Scope note (R2 removed):** The R2 lake-staleness health surface (ops-hardening spec §3) is **deliberately out of scope** — dropped per user decision 2026-07-07. Not built here. The R2 lake itself is untouched (still canonical EOD per the 2026-05-25 rule); only the monitoring feature is cut.

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`/`pip`/`python`.
- **Migrations idempotent** — `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`; no tracking table; next free prefix is **100** (`src/uw_scan/storage/migrations/`, latest is `099_uw_fetch_memo.sql`).
- **Persist analytical/ops results to Postgres** — no in-memory-only state.
- **Module size budget** — target <500 lines/file; propose a split before pushing a file past 1000.
- **API contract identity preserved** — new Pydantic response fields go in alphabetical slot; regen `web/lib/types.ts` via `cd web && npm run gen:types` (script-write, not the Edit tool — the prettier hook reflows). OpenAPI snapshot uses `sort_keys` + `ensure_ascii`.
- **No secrets to Codex subprocesses**; alert-sink token read from worker/API env only, never echoed in error strings.
- **CHANGELOG rides the feature PR** — add the `[Unreleased]` entry on-branch before merge.
- **Three-tier DB tripwire** (`config.py` `_enforce_db_isolation`) refuses `(host, db_name)` mismatch — the Docker prep PR must legalize `host.docker.internal`.
- **Never `git push origin main`** — branch → PR → green CI → merge.
- **Source specs (authoritative detail, file:line-verified):** `docs/superpowers/specs/2026-07-06-candidate-ops-hardening.md` (Track A) and `docs/superpowers/specs/2026-07-06-docker-migration-design.md` (Track B). This plan is the execution ordering; the specs hold the exact compose topology / env-remap tables — do not re-derive them. (Spec §3, R2 staleness, is intentionally skipped.)

---

## File Structure

**Track A — ops-hardening (code):**
- `src/uw_scan/storage/migrations/100_job_failures.sql` — new `job_failures` streak table.
- `src/uw_scan/storage/ops_health.py` — new module: `JobFailuresRepository` + module-scope `_ops_conn` factory. New domain → own module (never append to `repository.py`).
- `src/uw_scan/worker/scheduler.py:536` — register one `EVENT_JOB_ERROR`/`EVENT_JOB_EXECUTED` listener after `sched` is built.
- `src/uw_scan/api/routers/health.py` — add `job_failures` block to `HealthResponse` (alphabetical slot).
- `src/uw_scan/storage/external_api.py:240` — add `"job_name"` to the breakdown allow-list.
- `src/uw_scan/api/routers/provider_usage.py` — add `/provider-usage/jobs` route.
- `src/uw_scan/alerts.py` — new module: one `send_alert(title, message)` webhook POST (~25 lines, ponytail).
- `src/uw_scan/config.py` — add `ops_alert_webhook_url` setting.
- Tests (real layout — DB tests are `integration`, pure tests are `unit`; DB tests depend on the `seeded_db_empty_cards` fixture → `Repository`, and use `repo.conn`, NOT a `db_conn` fixture): `tests/integration/storage/test_ops_health.py`, `tests/integration/worker/test_scheduler_failure_listener.py`, `tests/integration/api/test_health_ops_blocks.py`, `tests/integration/storage/test_external_api_job_breakdown.py`, `tests/unit/test_alerts.py`.

> **Test layout is package-style** — dirs carry `__init__.py` (e.g. `tests/integration/worker/__init__.py`). `tests/integration/{storage,worker,api}/` already exist; if `tests/unit/config/` doesn't, create it with an empty `__init__.py` so collection works.

**Track B — Docker (infra):**
- `docker/app.Dockerfile`, `docker/web.Dockerfile` — new.
- `docker-compose.yml` (repo root, dev/build template) — new; mini's real file is `/opt/argon/compose.yml`.
- `web/next.config.mjs` — add `output: 'standalone'`.
- `src/uw_scan/config.py:71-73` — legalize `host.docker.internal` for `option_wizard` / `option_wizard_local`.
- `.github/workflows/release.yml` — add `ghcr-push` matrix job.
- `docs/runbooks/docker-deploy.md` — new; mark launchd sections of `docs/runbooks/release.md` superseded.
- Test: `tests/unit/config/test_db_isolation_docker_host.py` (pure, no DB).

---

# TRACK A — Ops-hardening (ships and deploys before Track B cutover)

### Task 1: `job_failures` table + repository + `_ops_conn`

**Files:**
- Create: `src/uw_scan/storage/migrations/100_job_failures.sql`
- Create: `src/uw_scan/storage/ops_health.py`
- Test: `tests/integration/storage/test_ops_health.py`

**Interfaces:**
- Produces: module-scope `_ops_conn() -> Connection` (short-lived conn factory; APScheduler workers freeze env at fork). `JobFailuresRepository(conn)` with `record_failure(job_name: str, error: str) -> None` (upsert: `consecutive += 1`, `last_error`, `last_failed_at=now()`), `record_success(job_name: str) -> None` (reset streak to 0), `list_streaks(min_streak: int = 1) -> list[JobFailureRow]`. `JobFailureRow` = dataclass `(job_name: str, consecutive: int, last_error: str, last_failed_at: datetime)`.

- [ ] **Step 1: Write the migration**

```sql
-- 100_job_failures.sql — per-job consecutive-failure streaks (ops-hardening #4)
CREATE TABLE IF NOT EXISTS uw_scan.job_failures (
    job_name        text PRIMARY KEY,
    consecutive     integer     NOT NULL DEFAULT 0,
    last_error      text,
    last_failed_at  timestamptz,
    last_success_at timestamptz,
    updated_at      timestamptz NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/storage/test_ops_health.py
import pytest

from uw_scan.storage.ops_health import JobFailuresRepository
from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_streak_increments_then_resets(repo):
    jf = JobFailuresRepository(repo.conn)
    jf.record_failure("full_scan", "boom")
    jf.record_failure("full_scan", "boom again")
    repo.conn.commit()
    rows = {r.job_name: r for r in jf.list_streaks()}
    assert rows["full_scan"].consecutive == 2
    assert rows["full_scan"].last_error == "boom again"

    jf.record_success("full_scan")
    repo.conn.commit()
    assert jf.list_streaks(min_streak=1) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_ops_health.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.storage.ops_health`

- [ ] **Step 4: Implement `ops_health.py`**

```python
# src/uw_scan/storage/ops_health.py
"""Ops-hardening health state: job-failure streaks.

New domain module (see CLAUDE.md 'Never extend repository.py'). Assembled into
Repository only for re-export compatibility, never with query methods added here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

_SCHEMA = "uw_scan"


def _ops_conn() -> Connection:
    """Short-lived conn for ops telemetry writes from the (env-frozen) worker.

    Matches the house factory: workers/migrate_runner/provider_usage all do
    `psycopg.connect(settings.db_dsn(), autocommit=True)`. There is NO
    `storage.connection.connect` helper — verified 2026-07-07.
    """
    import psycopg

    from uw_scan.config import Settings

    return psycopg.connect(Settings().db_dsn(), autocommit=True)


@dataclass(frozen=True)
class JobFailureRow:
    job_name: str
    consecutive: int
    last_error: str
    last_failed_at: datetime


class JobFailuresRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_failure(self, job_name: str, error: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.job_failures
                    (job_name, consecutive, last_error, last_failed_at, updated_at)
                VALUES (%s, 1, %s, now(), now())
                ON CONFLICT (job_name) DO UPDATE SET
                    consecutive = {_SCHEMA}.job_failures.consecutive + 1,
                    last_error = EXCLUDED.last_error,
                    last_failed_at = now(),
                    updated_at = now()
                """,
                (job_name, error[:2000]),
            )

    def record_success(self, job_name: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.job_failures
                    (job_name, consecutive, last_success_at, updated_at)
                VALUES (%s, 0, now(), now())
                ON CONFLICT (job_name) DO UPDATE SET
                    consecutive = 0,
                    last_success_at = now(),
                    updated_at = now()
                """,
                (job_name,),
            )

    def list_streaks(self, min_streak: int = 1) -> list[JobFailureRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_name, consecutive, last_error, last_failed_at
                FROM {_SCHEMA}.job_failures
                WHERE consecutive >= %s
                ORDER BY consecutive DESC
                """,
                (min_streak,),
            )
            return [
                JobFailureRow(job_name=r[0], consecutive=r[1], last_error=r[2] or "", last_failed_at=r[3])
                for r in cur.fetchall()
            ]
```

> Conn factory resolved: `psycopg.connect(Settings().db_dsn(), autocommit=True)` (house pattern, verified at `worker/massive_ws_consumer.py:663`, `storage/migrate_runner.py:182`, `storage/provider_usage.py:50`). `db_dsn()` is a `Settings` method (`config.py:886`).

- [ ] **Step 5: Apply migration + run the test**

Run: `bash scripts/migrate.sh && uv run pytest tests/integration/storage/test_ops_health.py -v`
Expected: PASS (the `seeded_db_empty_cards` fixture already runs migrations; migration 100 must be applied for the fixture's DB — confirm it's picked up).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/100_job_failures.sql src/uw_scan/storage/ops_health.py tests/integration/storage/test_ops_health.py
git commit -m "feat(ops): job_failures streak table + repository"
```

---

### Task 2: Wire `EVENT_JOB_ERROR` / `EVENT_JOB_EXECUTED` listeners into the scheduler

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py:536` (right after `sched = BlockingScheduler(...)`)
- Test: `tests/integration/worker/test_scheduler_failure_listener.py` (integration — it writes to the DB via the real repo)

**Interfaces:**
- Consumes: `JobFailuresRepository`, `_ops_conn` from Task 1.
- Produces: `_handle_job_event(event)` that, on `EVENT_JOB_ERROR`, calls `record_failure(event.job_id, str(event.exception))`; on `EVENT_JOB_EXECUTED`, calls `record_success(event.job_id)`.

- [ ] **Step 1: Write the failing test** (drive the handler directly with a fake event — no live scheduler)

```python
# tests/integration/worker/test_scheduler_failure_listener.py
from types import SimpleNamespace

import pytest

from uw_scan.storage.ops_health import JobFailuresRepository
from uw_scan.storage.repository import Repository
from uw_scan.worker import scheduler


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_error_event_records_streak(repo, monkeypatch):
    # _handle_job_event opens `with _ops_conn() as conn:` — hand it the test conn.
    # psycopg3 `with conn:` commits on exit and does NOT close, so reusing repo.conn is safe.
    monkeypatch.setattr(scheduler, "_ops_conn", lambda: repo.conn)
    scheduler._handle_job_event(SimpleNamespace(job_id="full_scan", exception=RuntimeError("boom")))
    assert JobFailuresRepository(repo.conn).list_streaks()[0].job_name == "full_scan"
```

> `monkeypatch.setattr(scheduler, "_ops_conn", ...)` works because Task 3's import pulls `_ops_conn` into the `scheduler` namespace (`from uw_scan.storage.ops_health import _ops_conn`). Patch the name where it's *looked up* (scheduler), not where it's defined.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_scheduler_failure_listener.py -v`
Expected: FAIL — `AttributeError: module 'uw_scan.worker.scheduler' has no attribute '_handle_job_event'`

- [ ] **Step 3: Implement the listener** — add near the top of `scheduler.py`, register after `sched` is built (line 536).

```python
# add imports at top of scheduler.py
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from uw_scan.storage.ops_health import _ops_conn


def _handle_job_event(event) -> None:
    from uw_scan.storage.ops_health import JobFailuresRepository
    try:
        with _ops_conn() as conn:
            repo = JobFailuresRepository(conn)
            if getattr(event, "exception", None) is not None:
                repo.record_failure(event.job_id, str(event.exception))
            else:
                repo.record_success(event.job_id)
            conn.commit()
    except Exception:  # ops telemetry must never crash the scheduler
        logger.warning("job-failure listener could not record event for %s", getattr(event, "job_id", "?"), exc_info=True)
```

Register right after `sched = BlockingScheduler(timezone=settings.rth_tz)` (line 536):

```python
    sched.add_listener(_handle_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
```

> ponytail: APScheduler runs listeners synchronously in the scheduler thread, so `_handle_job_event` opens one short-lived conn per job completion. At argon's cron cadence (minutes apart, not per-second) that's negligible — do NOT add a pooled/background writer. Upgrade path only if a high-frequency sub-minute job is ever added: batch success-resets or reuse a module-level conn.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_scheduler_failure_listener.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/scheduler.py tests/integration/worker/test_scheduler_failure_listener.py
git commit -m "feat(ops): EVENT_JOB_ERROR listener records failure streaks"
```

---

### Task 3: `job_failures` streak on `/api/health`

**Files:**
- Modify: `src/uw_scan/api/routers/health.py` (add `job_failures` block, alphabetical)
- Test: `tests/integration/api/test_health_ops_blocks.py`

**Interfaces:**
- Consumes: `JobFailuresRepository.list_streaks` (Task 1).
- Produces: `HealthResponse.job_failures: list[JobFailureStreak]` where `JobFailureStreak = {job_name: str, consecutive: int, last_error: str, last_failed_at: datetime}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/api/test_health_ops_blocks.py
# `client` and `seeded_db_empty_cards` share the migrated DB (both keyed off
# _migrated_settings). Write + commit via the repo conn; the app reads its own
# conn and sees the committed row. No _ops_conn monkeypatch needed — the health
# route reads via its request-scoped conn, not _ops_conn.
def test_health_reports_job_failure_streak(client, seeded_db_empty_cards):
    from uw_scan.storage.ops_health import JobFailuresRepository

    repo = seeded_db_empty_cards
    JobFailuresRepository(repo.conn).record_failure("full_scan", "boom")
    repo.conn.commit()
    body = client.get("/api/health").json()
    assert any(f["job_name"] == "full_scan" for f in body["job_failures"])
```

> Confirm the `client` fixture (`tests/integration/api/conftest.py:34`) is built against the same `_migrated_settings` DB the `seeded_db_empty_cards` fixture seeds — the rest of the integration/api suite already relies on this, so it holds; the assertion just makes the dependency explicit.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/api/test_health_ops_blocks.py -v`
Expected: FAIL — `KeyError: 'job_failures'`

- [ ] **Step 3: Populate the block in `health.py`** (alphabetical, near the existing `gap_healer` block ~line 405):

```python
from uw_scan.storage.ops_health import JobFailuresRepository

_streaks = JobFailuresRepository(conn).list_streaks(min_streak=1)
job_failures = [
    JobFailureStreak(
        job_name=s.job_name, consecutive=s.consecutive,
        last_error=s.last_error, last_failed_at=s.last_failed_at,
    )
    for s in _streaks
]
```

Add the `JobFailureStreak` model (follow the `HealthGapHealer` precedent in the same module) and `job_failures: list[JobFailureStreak] = Field(default_factory=list)` on `HealthResponse`.

- [ ] **Step 4: Run + regen types**

Run: `uv run pytest tests/integration/api/test_health_ops_blocks.py -v && cd web && npm run gen:types && cd ..`
Expected: PASS; `web/lib/types.ts` gains `job_failures` in its alphabetical slot.

> **Two generated artifacts, two mechanisms** (verified 2026-07-07): (a) `web/lib/types.ts` is regenerated by `npm run gen:types` (needs the API running on `:8400`). (b) The OpenAPI contract snapshot lives at **`tests/integration/api/openapi.snapshot.json`** (NOT `web/lib/`) and is checked by an integration snapshot test — adding a response field will fail that test until the snapshot is regenerated (its update path uses `sort_keys` + `ensure_ascii`; add the field in its alphabetical slot). Run the api snapshot test after gen:types and update the snapshot the way the existing snapshot test documents.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/routers/health.py web/lib/types.ts tests/integration/api/openapi.snapshot.json tests/integration/api/test_health_ops_blocks.py
git commit -m "feat(ops): surface job-failure streaks on /api/health"
```

---

### Task 4: Per-job UW budget attribution

**Files:**
- Modify: `src/uw_scan/storage/external_api.py:240` (allow `"job_name"`)
- Modify: `src/uw_scan/api/routers/provider_usage.py` (add `/provider-usage/jobs`)
- Test: `tests/integration/storage/test_external_api_job_breakdown.py`

**Interfaces:**
- Consumes: existing `_list_external_api_breakdown(column, ...)` and `list_external_api_endpoint_usage` shape.
- Produces: `list_external_api_job_usage(provider, start, end) -> list[ExternalApiBreakdownRow]` (on `_ExternalApiMixin`, alongside `list_external_api_ticker_usage`) + `GET /provider-usage/jobs?provider=` (provider-day window, no `window` param).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/storage/test_external_api_job_breakdown.py
from datetime import UTC, datetime, timedelta

import pytest

from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_job_breakdown_groups_by_job_name(repo):
    now = datetime(2026, 5, 14, 14, 0, tzinfo=UTC)
    for job in ("full_scan", "cockpit_daily_snapshot"):
        repo.insert_external_api_request(
            provider="uw", endpoint_key="iv_rank", method="GET",
            path_template="/api/stock/{ticker}/iv-rank", path="/api/stock/TSLA/iv-rank",
            ticker="TSLA", params={}, status_code=200, status_family="2xx",
            started_at=now, finished_at=now, latency_ms=42,
            official_daily_count=10, official_daily_limit=1000, job_name=job,
        )
    repo.conn.commit()
    # positional (provider, start, end) — mirrors list_external_api_ticker_usage
    rows = repo.list_external_api_job_usage("uw", now - timedelta(days=1), now + timedelta(days=1))
    assert {r.key for r in rows} >= {"full_scan", "cockpit_daily_snapshot"}
```

> Seed inline via `repo.insert_external_api_request(..., job_name=...)` — the real integration pattern (`tests/integration/storage/test_provider_usage_repository.py`), NOT a `seed_external_api_rows` fixture (does not exist). The `job_name` param exists on `insert_external_api_request` (`external_api.py:41`); the column is at `:53,77`.
> **Verify at execution:** the breakdown-row group field is asserted as `r.key` — confirm `ExternalApiBreakdownRow`'s field name (it's the same row type `list_external_api_ticker_usage` returns; grep the dataclass). If it's not `key`, the fail-first run will show the real attribute.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/storage/test_external_api_job_breakdown.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'list_external_api_job_usage'`

- [ ] **Step 3: Allow the column + add the method** — at `external_api.py:240`:

```python
        if column not in {"endpoint_key", "ticker", "job_name"}:
            raise ValueError(f"unsupported external API breakdown: {column}")
```

Add next to `list_external_api_ticker_usage`:

```python
    def list_external_api_job_usage(
        self, provider: str | None, start: datetime, end: datetime
    ) -> list[ExternalApiBreakdownRow]:
        return self._list_external_api_breakdown(
            "job_name", provider=provider, start=start, end=end
        )
```

- [ ] **Step 4: Add the router endpoint** — mirror the real `/provider-usage/tickers` route verbatim (`provider_usage.py:126-137`). Note the house pattern (verified 2026-07-07): `provider: ProviderParam = "all"` + `_provider_filter`, the window is the fixed provider-day via `provider_day_bounds()` (NO `window=` param, NO `_resolve_window`), `repo: Repository = Depends(get_repo)` (NOT `deps=`), and rows are wrapped in `ProviderUsageBreakdownResponse` (NOT `list[...]`):

```python
@router.get(
    "/provider-usage/jobs",
    response_model=ProviderUsageBreakdownResponse,
)
def provider_usage_jobs(
    provider: ProviderParam = "all",
    repo: Repository = Depends(get_repo),
) -> ProviderUsageBreakdownResponse:
    start, end = provider_day_bounds()
    rows = repo.list_external_api_job_usage(_provider_filter(provider), start, end)
    return ProviderUsageBreakdownResponse(
        provider_day_start=start,
        provider_day_end=end,
        rows=[ProviderUsageBreakdownRow(**row.__dict__) for row in rows],
    )
```

> Positional `(_provider_filter(provider), start, end)` — the sibling `list_external_api_ticker_usage` is called positionally, so `list_external_api_job_usage` must accept the same `(provider, start, end)` positional shape. No new response model, no new imports beyond what the router already has.

- [ ] **Step 5: Run + regen types**

Run: `uv run pytest tests/integration/storage/test_external_api_job_breakdown.py -v && cd web && npm run gen:types && cd ..`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/external_api.py src/uw_scan/api/routers/provider_usage.py web/lib/types.ts tests/integration/api/openapi.snapshot.json tests/integration/storage/test_external_api_job_breakdown.py
git commit -m "feat(ops): per-job UW budget attribution endpoint"
```

---

### Task 5: Alert sink (one webhook) + wiring

**Files:**
- Create: `src/uw_scan/alerts.py`
- Modify: `src/uw_scan/worker/scheduler.py` (fire on failure-streak in `_handle_job_event`), `src/uw_scan/sources/uw_budget.py` (fire on budget wall)
- Modify: `src/uw_scan/config.py` (`ops_alert_webhook_url`)
- Test: `tests/unit/test_alerts.py` (pure — stubs httpx, no DB)

**Interfaces:**
- Produces: `send_alert(title: str, message: str) -> bool` — POSTs to `settings.ops_alert_webhook_url` if set, returns `True` on 2xx, `False`/no-op if unset. Never raises.

- [ ] **Step 1: Write the failing test** (no network — stub httpx)

```python
# tests/unit/test_alerts.py
def test_send_alert_noop_without_url(monkeypatch):
    from uw_scan import alerts
    monkeypatch.setattr(alerts, "_webhook_url", lambda: "")
    assert alerts.send_alert("t", "m") is False


def test_send_alert_posts_when_configured(monkeypatch):
    from uw_scan import alerts
    posted = {}
    monkeypatch.setattr(alerts, "_webhook_url", lambda: "https://example.test/hook")

    class _Resp:
        status_code = 200

    def _fake_post(url, json, timeout):
        posted["url"] = url
        return _Resp()

    monkeypatch.setattr(alerts.httpx, "post", _fake_post)
    assert alerts.send_alert("worker died", "full_scan streak=3") is True
    assert posted["url"] == "https://example.test/hook"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_alerts.py -v`
Expected: FAIL — `ModuleNotFoundError: uw_scan.alerts`

- [ ] **Step 3: Implement — ponytail: one function, no framework**

```python
# src/uw_scan/alerts.py
"""One-webhook ops alert sink (Discord/Pushover-compatible JSON POST).

ponytail: single POST, no notification framework. Add per-channel routing only
if a second sink is ever genuinely needed.
"""
from __future__ import annotations

import logging

import httpx

from uw_scan.config import Settings

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    # NOTE: `get_settings()` lives in `api.deps`, not `config` — a worker-layer
    # module must not import the API layer. Read Settings directly.
    return (Settings().ops_alert_webhook_url or "").strip()


def send_alert(title: str, message: str) -> bool:
    url = _webhook_url()
    if not url:
        return False
    try:
        resp = httpx.post(url, json={"content": f"**[argon] {title}**\n{message}"}, timeout=5.0)
        return 200 <= resp.status_code < 300
    except Exception:  # alerting must never take down the caller
        logger.warning("ops alert POST failed", exc_info=True)
        return False
```

Add `ops_alert_webhook_url: str = ""` to `Settings`.

- [ ] **Step 4: Wire the triggers** — in Task 2's `_handle_job_event`, after recording a failure:

```python
            if event.exception is not None:
                streak = next((s for s in repo.list_streaks() if s.job_name == event.job_id), None)
                if streak and streak.consecutive in (3, 10):  # fire at 3, then once more at 10
                    from uw_scan.alerts import send_alert
                    send_alert(f"job {event.job_id} failing", f"{streak.consecutive} consecutive; last: {streak.last_error[:200]}")
```

Also fire once on the budget wall — inside `sources/uw_budget.py` `may_spend` (`:64`) at the point it returns `False` on the account-wide guard (the `total_guard` field on `BudgetLimits`, `:41`). One line, guarded by an in-process `_alerted_today` date flag (ponytail: in-process dedupe is fine; a duplicate alert after a worker restart is harmless). `may_spend` is pure/DB-free today — the alert call is the one impure edge; keep it a fire-and-forget `send_alert` (already never-raises) so the function stays effectively pure for its callers. Do not build an alert-router.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_alerts.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/alerts.py src/uw_scan/worker/scheduler.py src/uw_scan/sources/uw_budget.py src/uw_scan/config.py tests/unit/test_alerts.py
git commit -m "feat(ops): webhook alert sink wired to failure streaks + budget wall"
```

---

### Task 6: Track A — full lint/test gate + CHANGELOG + PR

- [ ] **Step 1: Add CHANGELOG entry** under `[Unreleased]`:

```markdown
### Added
- Ops-hardening: job-failure streaks on `/api/health`, per-job UW budget attribution (`/provider-usage/jobs`), and a webhook alert sink wired to failure streaks and the budget wall.
```

- [ ] **Step 2: Reproduce the FULL CI gate locally** — the exact step list from `.github/workflows/ci.yml` (verified 2026-07-07). The `lint + unit` job (`python-static-unit`) runs MORE than ruff+pytest; `check_migration_prefixes.py` is load-bearing here because Task 1 adds migration **100**. Run in order:

```bash
# --- job: lint + unit (python-static-unit) ---
python3 scripts/release/version_sync_check.py
uv sync --extra postgres
uv run ruff check src/ tests/ scripts/          # NOT `.` — CI scopes to these three
uv run python scripts/_lint_except.py src        # note the `src` positional arg
uv run python scripts/check_no_yahoo.py
uv run python scripts/check_migration_prefixes.py   # validates the new 100_ prefix
uv run pytest tests/unit/ -v                      # this job runs UNIT only
# --- job: integration (run separately in CI, sharded; run whole locally) ---
uv run pytest tests/integration/ -v
# --- job: web ---
cd web && npm ci && npm run typecheck && npm run test && npm run lint && npm run build && cd ..
```
Expected: all green. (Guardrail 5 grep — "no fake cursor/connection in integration tests" — is satisfied because our integration tests use the real `seeded_db_empty_cards` conn, not a stub.)

- [ ] **Step 3: Push branch + open PR**

```bash
git push -u origin feat/c12-ops-hardening
gh pr create --title "feat(ops): C12 ops-hardening (detection + alerting)" --body "Track A of C12. Job-failure streaks on /api/health, per-job budget attribution, webhook alert sink. Detection layer that makes the Watchtower no-rollback cutover (Track B) safe. R2-staleness monitoring intentionally out of scope (user decision)."
```

- [ ] **Step 4: Merge only after CI green**, then deploy to the mini (release tag or current launchd deploy path — Track A must be LIVE in prod before Track B cutover).

---

# TRACK B — Docker cutover (after Track A is live in prod)

> The exact compose topology (12 services), the env-remap table, the healthcheck commands, and the mini quirks are **fully specified** in `docs/superpowers/specs/2026-07-06-docker-migration-design.md`. Tasks below are the execution wrapper; copy values verbatim from that spec — do not re-derive.

### Task 7: DB-isolation tripwire legalizes `host.docker.internal`

**Files:**
- Modify: `src/uw_scan/config.py:71-73` — the host→allowed-DB-names frozenset map (`{"127.0.0.1": frozenset({...}), "localhost": frozenset({...}), ...}`); the `_enforce_db_isolation` function that reads it is at `:77`. Add a new key `"host.docker.internal": frozenset({"option_wizard", "option_wizard_local"})` (must allow BOTH: the mini's containers hit prod `option_wizard`, MacBook containers hit `option_wizard_local`).
- Test: `tests/unit/config/test_db_isolation_docker_host.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/config/test_db_isolation_docker_host.py
import pytest
from uw_scan.config import _enforce_db_isolation


def test_docker_host_allows_prod_db():
    _enforce_db_isolation("host.docker.internal", "option_wizard")  # no raise
    _enforce_db_isolation("host.docker.internal", "option_wizard_local")  # no raise


def test_docker_host_still_rejects_mismatch():
    with pytest.raises(RuntimeError):
        _enforce_db_isolation("host.docker.internal", "option_wizard_test_wrong")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/config/test_db_isolation_docker_host.py -v`
Expected: FAIL — the tripwire refuses `host.docker.internal`.

- [ ] **Step 3: Add a new `"host.docker.internal"` key** to the frozenset map at `config.py:71-73`, value `frozenset({"option_wizard", "option_wizard_local"})` — a new host entry, not a change to the existing `127.0.0.1`/`localhost`/mini rows. Do not add `option_wizard_test` to it (containers never run the test DB).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/config/test_db_isolation_docker_host.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/config.py tests/unit/config/test_db_isolation_docker_host.py
git commit -m "feat(docker): legalize host.docker.internal for prod/local DBs"
```

---

### Task 8: Two Dockerfiles + standalone Next.js + repo compose template

**Files:**
- Create: `docker/app.Dockerfile`, `docker/web.Dockerfile`
- Create: `docker-compose.yml` (repo root — dev/build template)
- Modify: `web/next.config.mjs` (`output: 'standalone'`)

- [ ] **Step 1:** Write `docker/app.Dockerfile` — multi-stage `python:3.13-slim`, `COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/`, `uv sync --frozen --no-dev --extra postgres` in builder; runtime copies `.venv`+`src`+`scripts`+migrations, installs `libpq5 ca-certificates curl tini`, `tini` as PID 1, no default CMD (compose sets `command:`). Copy the exact recipe from the Docker spec § "Images".

- [ ] **Step 2:** Write `docker/web.Dockerfile` — `node:22-alpine` multi-stage, Next.js standalone, `CMD ["node","server.js"]`.

- [ ] **Step 3:** Add `output: 'standalone'` to `web/next.config.mjs`.

- [ ] **Step 4:** Write repo-root `docker-compose.yml` from the spec's "Compose topology" table (12 services, `env_file`, `extra_hosts: ["host.docker.internal:host-gateway"]`, watchtower labels, healthchecks — api `curl -f http://localhost:8400/api/health`, web `wget --spider -q http://127.0.0.1:3001/` explicit IPv4).

- [ ] **Step 5: Local build smoke** (MacBook):

Run:
```bash
docker build -f docker/app.Dockerfile -t argon-app:test .
docker build -f docker/web.Dockerfile -t argon-web:test web
```
Expected: both images build clean.

- [ ] **Step 6: Local compose smoke against `option_wizard_local`** — `.env` points `UW_SCAN_DB_HOST=host.docker.internal`, `UW_SCAN_DB_NAME=option_wizard_local`. This proves the two things that must survive the cutover: **(a) web→api wiring** and **(b) a containerized process can WRITE to host Postgres over `host.docker.internal`**:

Run:
```bash
docker-compose --profile migrate run --rm migrator
docker-compose up -d api web
curl -fsS http://127.0.0.1:8400/api/health | jq -e '.ok == true'
curl -fsS http://127.0.0.1:3001/ >/dev/null && echo "web ok (web→api via NEXT_INTERNAL_API_BASE=http://api:8400)"

# (b) DB-WRITE INTEGRITY: a worker container writes+reads a row through host.docker.internal.
# Reuses Task 1's own _ops_conn (reads Settings().db_dsn() → host.docker.internal in-container)
# and the job_failures table as a self-cleaning write probe.
docker-compose run --rm worker-uw-0 uv run python -c "
from uw_scan.storage.ops_health import JobFailuresRepository, _ops_conn
c = _ops_conn(); r = JobFailuresRepository(c)
r.record_failure('__docker_write_smoke__', 'ping'); c.commit()
assert any(s.job_name == '__docker_write_smoke__' for s in r.list_streaks()), 'write not visible'
r.record_success('__docker_write_smoke__'); c.commit()
print('DB write OK through host.docker.internal')
"
docker-compose down
```
Expected: `.ok == true`, web serves, tripwire allows the container host (proves Task 7), and **`DB write OK through host.docker.internal`** prints (proves a container can write to host Postgres — the DSN resolves the host, the write commits, the read sees it).

> **Scope of the local smoke:** it proves DB-write + web→api + tripwire. It does NOT prove live market-data source connectivity — xenon (`:8765`/`:8321`) and apex (`:8322`) generally aren't running on the MacBook. **Full source-reconnection is verified at the mini cutover (Task 11)**, where those services actually run. massive WS is external and can be spot-checked locally if desired, but it's not load-bearing here.

- [ ] **Step 7: Commit**

```bash
git add docker/ docker-compose.yml web/next.config.mjs
git commit -m "feat(docker): app+web Dockerfiles, standalone Next.js, compose template"
```

---

### Task 9: `release.yml` GHCR push job

**Files:**
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1:** Add a `ghcr-push` job after `publish`, matrix × 2 images (`argon-app`, `argon-web`), runner `ubuntu-24.04-arm` (native arm64, no QEMU), `docker/login-action` to GHCR, `docker/build-push-action` tags `:X.Y.Z` + `:latest`, **prerelease tags excluded from `:latest`** (mirror apex).

- [ ] **Step 2:** Verify the workflow parses (push to a throwaway branch, let CI lint the YAML, or `act -l` if installed).
Expected: no syntax error; job graph shows `ghcr-push` after `publish`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat(docker): push argon-app+argon-web images to GHCR on release"
```

---

### Task 10: Runbook + CHANGELOG + Track B PR

**Files:**
- Create: `docs/runbooks/docker-deploy.md`
- Modify: `docs/runbooks/release.md` (mark launchd sections superseded), `CHANGELOG.md`

- [ ] **Step 1:** Write `docs/runbooks/docker-deploy.md` — Colima sizing (`colima start --cpu 6 --memory 8`), GHCR login, `/opt/argon/{compose.yml,.env}` layout, cutover + rollback (verbatim from the Docker spec's "Cutover plan" and "Rollback" sections).

- [ ] **Step 2:** Mark the launchd deploy sections of `docs/runbooks/release.md` superseded (keep for rollback reference — xenon precedent).

- [ ] **Step 3:** CHANGELOG `[Unreleased]`:

```markdown
### Changed
- Prod stack containerized (Colima + engine-wide Watchtower). Images `argon-app`/`argon-web` built by release.yml → GHCR. launchd app agents retire; host Postgres and backup agents unchanged. AI Codex/Claude workers off in phase 1 (DeepSeek survives).
```

- [ ] **Step 4:** Full local CI gate (as Task 6 Step 2) + push + PR:

```bash
git push -u origin feat/c12-docker-cutover
gh pr create --title "feat(docker): C12 Docker cutover (prep PR)" --body "Track B prep. Dockerfiles, standalone web, GHCR push, tripwire legalizes host.docker.internal, runbook. Cutover on the mini is a manual runbook step post-merge (Docker spec phases 1-3). Ops-hardening detection (Track A) already live."
```

- [ ] **Step 5:** Merge only after CI green.

---

### Task 11: Mini cutover (manual runbook — not code)

> Operational step run on the mini after Task 10 merges and a release tag builds the images. Follows the Docker spec "Cutover plan" phases 0-3. Not a test cycle — a checklist.

- [ ] **Phase 1 setup:** `colima stop && colima start --cpu 6 --memory 8`; GHCR `docker login`; create `/opt/argon/{compose.yml,.env}` (env-remap table from spec); `docker-compose --profile migrate run --rm migrator` (idempotent against live DB); do **not** start app services yet.
- [ ] **Phase 1 `.env` completeness gate (prevents silent source degradation):** the env-remap table only lists *changed* (host-remapped) vars. The `/opt/argon/.env` must ALSO carry every *unchanged* source secret from the current launchd env, or the corresponding source silently no-ops (argon's source clients never raise). Diff the current live env against the new `.env` and confirm ALL of these are present:
  - `XENON_QUERY_API_KEY` — **without it the IB greeks path silently falls back to `source='uw'`** (CLAUDE.md); copy the value from xenon's `/opt/xenon/.env`.
  - `UW_SCAN_API_KEY` (UW — the primary scan/flow source), `FMP` key, any massive key, `DEEPSEEK_API_KEY` (the one AI provider that survives).
  - Remapped hosts present and pointing at `host.docker.internal`: `UW_SCAN_DB_HOST`, `XENON_WS_URL`, `XENON_QUERY_API_URL`, `APEX_API_URL`; `XENON_WS_PORT_FILE=""` (empty — the host-local port file is invisible in-container; xenon publishes 8765 fixed).
  - Quick check: `docker-compose run --rm worker-uw-0 env | grep -E 'XENON_QUERY_API_KEY|UW_SCAN_API_KEY|DEEPSEEK_API_KEY' | sed 's/=.*/=<set>/'` — every one must show `<set>`.
- [ ] **Phase 2 cutover (double-writer moment):** `launchctl bootout` ALL `com.argon.*` app agents (api, web, massive-ws, 10 workers, deploy-poller) — fully stopped before compose starts (running both double-writes + double-burns UW budget). Then `docker-compose up -d`.
- [ ] **Phase 2 verify — market-data source reconnection + DB-write integrity matrix.** Each row proves a `host.docker.internal` hop by the SOURCE TAG on a freshly-written row, not just liveness (argon clients degrade silently — liveness alone hides a dead source):

  | What must survive | How to prove it (container is live) | Pass condition |
  |---|---|---|
  | **Postgres WRITE** (host-native, `:5432`) | `/api/health` `.ok == true`; one full-scan cycle lands NEW rows; freshness monitor green next morning | new `scan_runs`/card rows dated post-cutover; `freshness` block all-green |
  | **xenon WS spot** (`:8765`) | `/api/health` `ws_consumer.active_source == "xenon_ws"` | `== "xenon_ws"`, and `watchlist_card.spot_source == 'xenon_ws'` on fresh rows |
  | **xenon WS failover** | kill the xenon relay → `active_source` flips to `massive.com_ws`; restore → flips back | flips both ways (proves the fallback path, not just primary) |
  | **xenon query API** (IB greeks, `:8321`) | surface IV canary writes `iv_source_validation` rows | `source == 'ib'` (NOT `'uw'` — `'uw'` means the key/host is wrong and it silently fell back) |
  | **massive WS** (external, delayed) | consumer `last_flush_at` advancing; no proxy-env leak | `last_flush_at` fresh; connects with `proxy=None` |
  | **UW REST** (external) | full-scan + `/provider-usage` shows UW requests post-cutover | 2xx UW requests in `/provider-usage/summary` |
  | **apex** (`:8322`, web-layer, C10 — only if built) | web bar panels render | N/A until C10 ships; `APEX_API_URL=http://host.docker.internal:8322` set now |
  | **DeepSeek AI** (survives) | enqueue analysis via web → worker claims → result renders | DeepSeek row produced end-to-end |
  | **Track A ops** | `/api/health` `job_failures == []` | no job erroring post-cutover |

  **Expected-not-a-failure:** `ai-codex`/`ai-claude` produce nothing — off in phase 1 (#240). If `iv_source_validation.source == 'uw'` (not `'ib'`) → the `XENON_QUERY_API_KEY`/`XENON_QUERY_API_URL` env is wrong; fix `/opt/argon/.env` and kickstart the worker (env frozen at fork). Spot updates visible on `:3001`.
- [ ] **Phase 3 retire:** after ~3 clean days, remove app plists from `~/Library/LaunchAgents` (keep the two backup plists). Update `config/services.list`.
- [ ] **Rollback at any point:** `docker-compose down` → `launchctl bootstrap` the plists back → old stack resumes from the same DB (never moved).

---

## Post-cutover verification sign-off (run AFTER Task 11 completes)

> Do not call the cutover done until all three pass. These consolidate the checks embedded in Tasks 8 & 11 so nothing is skipped. Record the actual command output next to each box.

- [ ] **1. DB-write integrity** — a containerized process writes to host Postgres over `host.docker.internal` and reads it back.
  - Local (Task 8 Step 6): `worker-uw-0` prints `DB write OK through host.docker.internal`.
  - Mini (Task 11 Phase 2): a full-scan cycle lands NEW `scan_runs`/card rows dated post-cutover; `/api/health` `freshness` block all-green next morning.
- [ ] **2. `.env` secret completeness** — no source silently degraded (argon clients never raise).
  - `docker-compose run --rm worker-uw-0 env | grep -E 'XENON_QUERY_API_KEY|UW_SCAN_API_KEY|DEEPSEEK_API_KEY'` → every one `<set>`.
  - Decisive tell: `iv_source_validation.source == 'ib'` (NOT `'uw'`). `'uw'` ⇒ `XENON_QUERY_API_KEY`/`_URL` wrong → fix `/opt/argon/.env`, kickstart the worker (env frozen at fork).
- [ ] **3. Per-source reconnection** — each source proven by the SOURCE TAG on a freshly-written row, not liveness:
  - xenon WS: `/api/health` `ws_consumer.active_source == "xenon_ws"` + `watchlist_card.spot_source == 'xenon_ws'`.
  - xenon WS failover: kill relay → flips to `massive.com_ws` → restore → flips back.
  - xenon query: `iv_source_validation.source == 'ib'`.
  - massive WS: `last_flush_at` advancing, no proxy leak. UW REST: 2xx in `/provider-usage/summary`. DeepSeek: analysis end-to-end. apex: N/A until C10.
  - Expected-not-a-failure: `ai-codex`/`ai-claude` produce nothing (#240).

---

## Self-Review

**Spec coverage (Track A / ops-hardening spec):** #1 deploy-gate already DONE (#222) — not re-done. #2 alert sink → Task 5. **#3 R2 staleness → intentionally out of scope (user decision 2026-07-07), not built.** #4 job-failure aggregation → Tasks 1-3. #5 per-job budget attribution → Task 4. ✅

**Spec coverage (Track B / Docker spec):** tripwire → Task 7; Dockerfiles+standalone+compose → Task 8; release.yml GHCR → Task 9; runbook+supersede → Task 10; cutover phases 0-3 → Task 11. Backup agents / AI-worker retirement / Colima sizing → Task 10 runbook + Task 11 checklist. ✅

**Overlap resolved:** old C8.1 (launchd health-gate, #222) is superseded by Watchtower; Track A's alert sink replaces its detection role. C7's conn-pool is out of scope here (belongs to C7) — noted so no one double-builds it.

**Connectivity + DB-write integrity (explicit, per user requirement 2026-07-07):** every host-loopback hop that breaks in a container is remapped to `host.docker.internal` (DB `:5432`, xenon WS `:8765`, xenon query `:8321`, apex `:8322`; web→api via `NEXT_INTERNAL_API_BASE=http://api:8400`; port-file disabled) — the Docker spec's env-remap table is design-complete, verified against `config.py` (`:180,384,467`) and `sources/xenon_ws.py:172` (port-file consulted only for localhost). The PLAN adds what the spec left implicit: (1) a container→host-Postgres **write** proof in Task 8 Step 6, (2) a `.env` secret-completeness gate in Task 11 Phase 1 (unchanged source keys, esp. `XENON_QUERY_API_KEY`, or the source silently degrades), (3) a per-source reconnection matrix in Task 11 Phase 2 that proves each source by the **source tag on written rows** (`active_source='xenon_ws'`, `iv_source_validation.source='ib'`), because argon's never-raise clients hide a dead source behind a green `/api/health`. massive/UW/FMP are external HTTPS and are unaffected by the container boundary.

**Resolved during review (2026-07-07 grounding sweep — no longer guesses):**
- Conn factory → `psycopg.connect(Settings().db_dsn(), autocommit=True)` (no `storage.connection.connect` exists). `db_dsn()` at `config.py:886`.
- Task 4 test class → `Repository(db_conn)` (breakdown methods live on `_ExternalApiMixin` at `external_api.py:20`, reached via `Repository`; `ExternalApiRepository` does not exist).
- Task 4 route → mirrors `/provider-usage/tickers` exactly: `ProviderParam`+`_provider_filter`, `provider_day_bounds()` (no `window` param, no `_resolve_window` — that helper does not exist), `repo: Repository = Depends(get_repo)`, wrap in `ProviderUsageBreakdownResponse`.
- `get_settings` is in `api.deps` not `config` → alerts.py reads `Settings()` directly (avoids worker→API layering).
- Return type `ExternalApiBreakdownRow` ✅ confirmed exported (`repository.py:52,86`).

**Remaining thin spots (follow precedent at execution, low risk):**
- Exact `Settings` field add point for `ops_alert_webhook_url` — append near the other URL settings (`config.py:115-384` block); no ordering constraint.
- `JobFailureStreak` health-model placement — follow the `HealthGapHealer` precedent (`health.py:102`); `HealthResponse` at `:32`, add field in alphabetical slot (after `gap_healer`, before `freshness`... actually `job_failures` sorts after both — place per the alphabetical rule).

**Accepted caveat (tracked in #240, not a blocker):** Track B phase 1 turns the `ai-codex` / `ai-claude` workers OFF (Docker spec decision — they depend on host-side Codex/Claude CLI auth the container lacks). DeepSeek survives (in-process HTTP, env key). This is intentional and acknowledged by the user; **issue #240** tracks re-enabling Codex/Claude under Docker in phase 2. Do NOT treat their absence post-cutover as a regression — `trade_insight_ai_analyses` codex/claude rows will queue unclaimed by design.
