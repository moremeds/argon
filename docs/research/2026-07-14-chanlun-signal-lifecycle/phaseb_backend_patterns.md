# argon backend conventions inventory — for chanlun signal-lifecycle engine plan

Target feature: new worker job + new Postgres table (signal-event log keyed by
ticker+timestamp) + new read API endpoint + config flags. All paths absolute
from repo root `/Users/chenxi/projects/argon`.

---

## 1. Migrations

- **Directory**: `src/uw_scan/storage/migrations/` (NOT a top-level `migrations/` dir — that path doesn't exist).
- **Highest existing migration**: `106_technical_vwap_anchor.sql` (117 files total in the dir, including a `README.md`). **Next migration number: `107_<name>.sql`.**
  ```
  $ ls src/uw_scan/storage/migrations/ | sort -V | tail -5
  103_vrp_macro_entry_grid_strike_ivs.sql
  104_technical_live.sql
  105_technical_daily_ohlcv.sql
  106_technical_vwap_anchor.sql
  README.md
  ```
- **No `schema_migrations` tracking table.** `src/uw_scan/storage/migrations/README.md:1-13`:
  > "Migrations are plain `.sql` files applied lexically by `scripts/migrate.sh`... There is no `schema_migrations` tracking table. Every file MUST be idempotent: use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `ON CONFLICT DO NOTHING` for seeds. Re-running the runner on an already-migrated DB must be a no-op."
  > "Each file starts with `SET search_path TO uw_scan, public;`"
- **Prefix uniqueness is CI-enforced.** `scripts/check_migration_prefixes.py` fails CI if two files share a 3-digit numeric prefix (except an explicit grandfathered set: `037-042,047,052-055,059,060`). Don't reuse `106`.
- **Header convention** — real example, `src/uw_scan/storage/migrations/104_technical_live.sql` (full file, 12 lines):
  ```sql
  -- Latest-only live-technicals cache (one row per ticker, upsert). Not a
  -- (ticker, as_of) temporal table -> no data-gap registry entry needed.
  SET search_path TO uw_scan, public;

  CREATE TABLE IF NOT EXISTS technical_live (
      ticker       text PRIMARY KEY,
      captured_at  timestamptz NOT NULL,
      spot         double precision,
      spot_source  text,
      payload      jsonb NOT NULL,
      inserted_at  timestamptz NOT NULL DEFAULT now()
  );
  ```
- **Append-only event-log precedent** (closest analog to a signal-event log keyed by ticker+timestamp) — `src/uw_scan/storage/migrations/093_watchlist_ticker_events.sql` (full file):
  ```sql
  -- 093_watchlist_ticker_events.sql
  -- Append-only watchlist lifecycle log for the data gap healer. One row per
  -- add/remove event so a ticker's history survives a remove->re-add cycle...
  SET search_path TO uw_scan, public;
  BEGIN;
  CREATE TABLE IF NOT EXISTS uw_scan.watchlist_ticker_events (
      id         BIGSERIAL PRIMARY KEY,
      ticker     TEXT NOT NULL,
      event      TEXT NOT NULL CHECK (event IN ('added', 'removed')),
      event_date DATE NOT NULL,
      note       TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS ix_watchlist_ticker_events_latest
      ON uw_scan.watchlist_ticker_events (ticker, id DESC);
  COMMIT;
  ```
  For an event log keyed by `(ticker, timestamp)`, model the new table the same way: `BIGSERIAL PRIMARY KEY` + `ticker TEXT NOT NULL` + an event timestamp column + a `CREATE INDEX IF NOT EXISTS ix_<table>_ticker_ts ON <table> (ticker, <ts_col> DESC)` (or `(ticker, id DESC)` for latest-N reads, following 093's pattern).
- **`scripts/migrate.sh`** (full file, `/Users/chenxi/projects/argon/scripts/migrate.sh`):
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  cd "$(dirname "$0")/.."
  exec uv run python -m uw_scan.storage.migrate_runner
  ```
  It delegates entirely to `src/uw_scan/storage/migrate_runner.py`, which discovers every `*.sql` under the migrations dir sorted lexically (`discover_migrations`, `migrate_runner.py:31-33`) and applies each via one psycopg connection with `autocommit = True` (required because migrations `026/027/035` use `CREATE INDEX CONCURRENTLY`, forbidden inside a transaction block — `migrate_runner.py:9-14`). Statements are split and sent individually (`split_sql_statements`).
- Idempotency is also enforced by the test suite: `tests/integration/conftest.py` migrates the schema exactly once per pytest session (`_migrated_settings` fixture, drops+recreates `uw_scan` schema, calls `apply_migrations`) — a broken idempotent migration fails the whole session, not just one test.

---

## 2. Worker job pattern

Read both `src/uw_scan/worker/jobs/technical_live.py` (technical_live_scan) and `src/uw_scan/worker/jobs/regime_live.py` (regime_live_scan_once). Common shape:

- **Plain function, not a class.** Signature `fn(repo: Repository, settings: Settings, *, ticker_filter=None, now: datetime | None = None) -> dict[str, Any]` — `technical_live.py:93-99`. `regime_live_scan_once(repo, settings, *, now=None) -> dict` — `regime_live.py:28-30`.
- **`now` is an injectable clock parameter** (defaults to `datetime.now(timezone.utc)`), so tests can freeze time — see `technical_live.py:100`.
- **Repository/Settings come in as parameters**, not constructed inside the job — the scheduler wires them via `_repo(settings)` context manager (see §3). Domain-specific standalone repositories are constructed *inside* the job from `repo.conn` + `settings.db_schema`, e.g. `technical_live.py:103-104`:
  ```python
  trepo = TechnicalsRepository(repo.conn, schema=settings.db_schema)
  live = TechnicalLiveRepository(repo.conn, schema=settings.db_schema)
  ```
- **Per-item try/except inside a loop, never a bare crash-the-job.** `technical_live.py:114-186` loops over tickers; each iteration is wrapped `try/except Exception as exc: failed += 1; repo.conn.rollback(); log.warning(...)`. `regime_live.py` isolates each sub-computation (CRI, VCG, VRP) in its own try/except with `repo.conn.rollback()` on failure so one leg's exception never blocks the others (`regime_live.py:43-59`, `106-109`, comment: "Isolated: a vol-data gap here never blocks cri/vcg").
- **Outcomes are recorded as an in-process summary dict, logged, and returned** — not written to `scan_runs`. Example, `technical_live.py:191-200`:
  ```python
  summary = {
      "ok": ok, "skipped_stale": skipped_stale, "skipped_thin": skipped_thin,
      "failed": failed, "healed": healed, "tickers": len(tickers),
  }
  log.info("technical_live_scan: %s", summary)
  return summary
  ```
  `regime_live_scan_once` returns a status dict (`{"status": "ok", "live_symbols": ..., "cri": bool, "vcg": bool, "vrp": status}` — `regime_live.py:111-117`) or `{"status": "skipped_no_fresh_quotes"}` when there's nothing to do.
- **Job-level failure tracking is NOT the job's job** — it's automatic. See §3: the scheduler installs one global APScheduler event listener that records every job's success/exception into `job_failures` regardless of what the job function does internally.
- **Never-raise / defensive external calls.** `technical_live.py._massive_today_ohlc` (lines 65-90) wraps the massive REST call in `try/except Exception as exc: log.debug(...); return None` with the comment "never-raise — a massive hiccup must not fail the live update".
- **Module docstring explains the job's role and data flow** at the top of the file (both examples have a 5-8 line docstring).
- **`logger = logging.getLogger(__name__)`** per `src/uw_scan/CLAUDE.md` convention (`technical_live.py` uses `log`, `regime_live.py` uses `logger` — both fine, just pick one and be consistent).

---

## 3. Scheduler registration — `src/uw_scan/worker/scheduler.py`

Two parts: (a) an inner closure wrapping the job call with weekday/settings gating, (b) an `if <gate>: sched.add_job(...)` block.

- **Ownership-pinning helper functions** decide which worker role/index may register the job, to avoid duplicate writes from a multi-process/multi-shard stack. Exact text, `scheduler.py:407-417`:
  ```python
  def _should_schedule_regime_live(settings: Settings) -> bool:
      """Exactly one process owns the 5-min live snapshot writes.
      ... Pin to massive-0 (market-data role) following the rates-FRED precedent.
      """
      role = settings.worker_role.lower()
      return role == "all" or (role == "massive" and settings.worker_index == 0)
  ```
  `technical_live_scan` reuses this same helper rather than defining its own (comment at registration site, `scheduler.py:1652-1655`: "Reuses the regime-live single-owner pin (massive-0)").
- **Inner closures**, `scheduler.py:997-1017`:
  ```python
  def _regime_live_scan() -> None:
      if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
          return
      from uw_scan.worker.jobs.regime_live import regime_live_scan_once
      with _repo(settings) as repo:
          summary = regime_live_scan_once(repo, settings)
      logger.info("regime_live_scan_tick %s", summary)

  def _technical_live_scan() -> None:
      if datetime.now(ZoneInfo(settings.rth_tz)).weekday() >= 5:
          return
      from uw_scan.worker.jobs.technical_live import technical_live_scan
      with _repo(settings) as repo:
          summary = technical_live_scan(repo, settings)
      logger.info("technical_live_scan_tick %s", summary)
  ```
  Note the **local `import`** inside the closure (not top-of-file) — this is the repo-wide pattern for job modules in scheduler.py (keeps scheduler.py's own import surface small / avoids heavy job-module imports at scheduler startup).
- **`with _repo(settings) as repo:`** — every job opens its own connection and it's closed via the context manager (`worker/CLAUDE.md`: "Every job opens its own conn via `_repo(settings)` and closes it in `finally`. No long-lived connections.").
- **Registration block**, `scheduler.py:1630-1663`:
  ```python
  if _should_schedule_regime_live(settings):
      sched.add_job(
          _regime_live_scan,
          IntervalTrigger(minutes=settings.regime_live_scan_interval_minutes),
          id="regime_live_scan",
          name="Regime live CRI/VCG snapshot",
          max_instances=1,
          coalesce=True,
      )
      sched.add_job(
          _regime_live_validation,
          CronTrigger(hour=3, minute=40, timezone=settings.rth_tz),
          id="regime_live_validation",
          name="Regime live close vs lake validation",
          max_instances=1,
          coalesce=True,
      )

  if settings.technical_live_enabled and _should_schedule_regime_live(settings):
      sched.add_job(
          _technical_live_scan,
          IntervalTrigger(minutes=settings.technical_live_scan_interval_minutes),
          id="technical_live_scan",
          name="Live technicals coverage",
          max_instances=1,
          coalesce=True,
      )
  ```
  `technical_live_scan`'s registration is gated by **both** the ownership pin AND its own settings kill-switch (`settings.technical_live_enabled`) — `regime_live_scan` has no separate kill-switch (always on when the role pin matches). For a new job, follow whichever fits: a kill-switch flag is standard practice for a new user-facing feature.
- **`max_instances=1, coalesce=True`** appears on essentially every job registration in the file — copy it.
- **Job outcome / failure tracking is automatic and global** — a single APScheduler listener, `scheduler.py:537-564` + registration at `scheduler.py:573`:
  ```python
  def _handle_job_event(event) -> None:
      from uw_scan.storage.ops_health import JobFailuresRepository
      try:
          with _ops_conn() as conn:
              repo = JobFailuresRepository(conn)
              if getattr(event, "exception", None) is not None:
                  repo.record_failure(event.job_id, str(event.exception))
                  streak = next((s for s in repo.list_streaks() if s.job_name == event.job_id), None)
                  if streak and streak.consecutive in (3, 10):
                      from uw_scan.alerts import send_alert
                      send_alert(f"job {event.job_id} failing", ...)
              else:
                  repo.record_success(event.job_id)
              conn.commit()
      except Exception as exc:
          logger.warning("job-failure listener could not record event for %s: %s", ...)

  sched.add_job(...)  # ... later:
  sched.add_listener(_handle_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
  ```
  This fires for **every** `sched.add_job(id=...)` registration automatically, keyed on the job's `id=` string. A new signal-lifecycle job needs no bespoke failure-tracking code — just register it with `sched.add_job(..., id="chanlun_signal_scan")` and it's covered. `job_failures` table itself is registered in the gap-healer REGISTRY as `audit_mode="excluded"` (see §8) with the reason "live per-job failure-streak state; scheduler-maintained, nothing to backfill/heal".
- **Worker-role table** (`src/uw_scan/worker/CLAUDE.md`): `uw` workers run UW-budgeted jobs, `massive` workers run market-data/OHLC jobs, `ai` workers run only Trade Insights AI. `regime_live`/`technical_live` are both pinned to `massive-0` because they're pure DB-read/compute (no provider spend) and must have exactly one writer for append-only snapshot rows. A chanlun engine reading `technical_daily`/`intraday_quote` (pure DB-read, no new provider calls) is the same shape — pin it to `massive-0` via a `_should_schedule_<name>` helper (or reuse `_should_schedule_regime_live` if the timing/ownership rationale matches exactly).
- **APScheduler weekdays are Monday=0** — use `0-4` for Mon-Fri crons (`worker/CLAUDE.md`).

---

## 4. Storage repository pattern

**Standing rule (from `src/uw_scan/storage/CLAUDE.md`, verbatim):**
> "Adding a new domain → prefer a **standalone** `storage/<domain>_repository.py` class from method one (standing feedback rule — **never grow `repository.py`**). Only add a `_<Domain>Mixin` when existing `Repository` callers genuinely need the methods on the shared instance; then add it to `repository.py`'s import block and inheritance list (above `_BaseMixin`)."

This is corroborated by user memory `feedback_repository_split_threshold`: "new persistence domains get their own `storage/<domain>_repository.py` from method one" and the CLAUDE.md file note "`repository.py` reached 5000+ lines because the line was never drawn — don't repeat."

- **Reference module**: `src/uw_scan/storage/technical_live_repository.py` (full file, 62 lines) — a clean example of the "never touch repository.py" shape:
  ```python
  """Standalone repository for the technical_live latest-only cache."""
  from __future__ import annotations
  from datetime import datetime
  from psycopg import Connection
  from psycopg.types.json import Jsonb

  class TechnicalLiveRepository:
      def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
          self._conn = conn
          self._schema = schema
          with conn.cursor() as cur:
              cur.execute(f"SET search_path TO {schema}, public")

      def upsert(self, ticker, captured_at, spot, spot_source, payload) -> None:
          with self._conn.cursor() as cur:
              cur.execute(
                  """
                  INSERT INTO technical_live
                      (ticker, captured_at, spot, spot_source, payload)
                  VALUES (%s, %s, %s, %s, %s)
                  ON CONFLICT (ticker) DO UPDATE SET
                      captured_at = EXCLUDED.captured_at, spot = EXCLUDED.spot,
                      spot_source = EXCLUDED.spot_source, payload = EXCLUDED.payload,
                      inserted_at = now()
                  """,
                  (ticker.upper(), captured_at, spot, spot_source, Jsonb(payload)),
              )
          self._conn.commit()

      def fetch(self, ticker: str) -> dict | None:
          ...  # SELECT + manual dict construction from cur.fetchone()
  ```
  Key mechanics: **not** an ORM — raw cursor + parameterized SQL. `Jsonb(payload)` wrapper required for jsonb columns (psycopg won't auto-encode dicts — `storage/CLAUDE.md`). `self._conn.commit()` is called explicitly at the end of each write method (this repo does NOT rely on the caller to commit for this class — contrast with `regime_live.py:104` where the caller (`repo.upsert_vrp_macro_signal`) does NOT self-commit and the *job* commits explicitly — check per-repository convention, don't assume).
- **`Repository` (repository.py) is NOT touched** for `technical_live` — grep confirms `TechnicalLiveRepository` is never imported into `repository.py`; it's instantiated ad hoc inside the job (`technical_live.py:104`) and inside the API router (`stock.py:222,225`) each time it's needed. For an **append-only event-log** table (closer to `watchlist_ticker_events`), the precedent instead lives as new methods on an *existing* standalone repository (`DataGapHealerRepository` in `src/uw_scan/storage/data_gap_healer_repository.py:481-528` — `record_ticker_events`, `current_ticker_status`, `list_ticker_events`). For the chanlun signal-event log, create a fresh `storage/chanlun_signal_repository.py` (or similar name) — do not bolt it onto an unrelated repository.
- **`Repository` class assembly** (for context — confirms `repository.py` is purely composition), `repository.py:8-50`:
  ```python
  from ._base import _BaseMixin
  ...
  from ._helpers import provider_day_bounds, redact_params, status_family_for
  from .audit import _AuditMixin
  from .cockpit import _CockpitMixin
  ... (~30 domain mixins) ...
  from .rows import (...)
  ```
  `_BaseMixin` (in `_base.py`) MUST be last in the MRO — it owns `__init__` and the `conn` property. **Do not add anything here for the new feature** unless an existing `Repository` caller genuinely needs the methods on the shared instance.

---

## 5. API router pattern

- **Router file**: `src/uw_scan/api/routers/stock.py`. Endpoint (full body), `stock.py:216-243ish`:
  ```python
  @router.get("/stock/{ticker}/technicals/live", response_model=TechnicalsLiveResponse)
  def get_stock_technicals_live(
      ticker: str,
      repo: Repository = Depends(get_repo),
      settings: Settings = Depends(get_settings),
  ) -> TechnicalsLiveResponse:
      from uw_scan.storage.technical_live_repository import TechnicalLiveRepository

      t = ticker.upper()
      row = TechnicalLiveRepository(repo.conn, schema=settings.db_schema).fetch(t)
      if row is None:
          return TechnicalsLiveResponse(ticker=t, available=False)
      p = row["payload"]
      return TechnicalsLiveResponse(
          ticker=t, available=True, captured_at=row["captured_at"],
          spot=row["spot"], spot_source=row["spot_source"],
          forming_ohlc=p.get("forming_ohlc"), z=p.get("z"), z_band=p.get("z_band"),
          rsi14=p.get("rsi14"), rsi_z=p.get("rsi_z"), ...
      )
  ```
  Note the **local import inside the endpoint function** for the standalone repository (same pattern as the scheduler closures in §3) — synchronous `def` (not `async def`), `Depends(get_repo)` / `Depends(get_settings)` from `src/uw_scan/api/deps.py`, `response_model=` set on the decorator matching the return type annotation.
- **Router wiring** — `src/uw_scan/api/server.py:75-93` (`include_router` block; excerpt):
  ```python
  app.include_router(health.router, prefix="/api", tags=["health"])
  ...
  app.include_router(stock.router, prefix="/api", tags=["stock"])
  ...
  app.include_router(regime.router, prefix="/api", tags=["regime"])
  ...
  ```
  `src/uw_scan/api/CLAUDE.md` says server.py mounts "17 routers" but the live file has more (`positioning`, `positions`, `vrp` also present at `server.py:83,86,92-93`) — treat the CLAUDE.md count as stale prose and `server.py`'s actual `include_router` block as authoritative (per its own words: "the `include_router` block in `server.py` is authoritative"). A new `/api/chanlun-signals` (or similar) router needs its own file under `routers/`, its own `router = APIRouter()`, and one new `app.include_router(chanlun.router, prefix="/api", tags=["chanlun"])` line.
  **Routers are read-only.** Per `src/uw_scan/api/CLAUDE.md`: "Long-running work... goes through `routers/jobs.py` and the worker." and "No business logic in routers — call into `reports/*` or `cards/*`."
- **Response model** — `src/uw_scan/models/technicals.py:111-129` (`TechnicalsLiveResponse`, `_UwBase` subclass — Pydantic v2):
  ```python
  class TechnicalsLiveResponse(_UwBase):
      """Latest-only live technicals head... `available` is False when no fresh
      cache row exists — the client then falls back to the EOD daily payload."""
      ticker: str
      available: bool
      captured_at: datetime | None = None
      spot: float | None = None
      ...
  # Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
  _preserve_public_module(
      TechnicalsHeader, TechnicalsSeriesRow, ..., TechnicalsLiveResponse,
  )
  ```
  Every model calls `_preserve_public_module(...)` on itself so OpenAPI component names stay `uw_scan.models.X` regardless of which domain submodule it physically lives in (needed since `models/__init__.py` is export-only). Then re-exported: `src/uw_scan/models/__init__.py:146` (import) and `:328` (`__all__` entry).
- **openapi → web types flow**:
  1. `cd web && npm run gen:types` runs `openapi-typescript http://127.0.0.1:8400/openapi.json -o lib/types.ts` (`web/package.json:12`) — requires the FastAPI dev server running locally on :8400.
  2. **`web/lib/types.ts` is alphabetically frozen — do NOT run a full `gen:types` regen for a small addition.** User memory `reference_generated_files_alphabetically_frozen` (verbatim):
     > "`web/lib/types.ts` — committed in 4-space indent, alphabetical path & property order (older openapi-typescript default). The pinned `openapi-typescript` (7.13.0) now emits declaration order, so `npm run gen:types` reorders the whole ~9.6k-line file and buries the real change. Add the field in its **alphabetical slot** instead."
     > "For `types.ts`, edit via a **bash/script write, not the Edit tool** — the Edit PostToolUse prettier hook reflows the 4-space generated file to 2-space (it's a no-op on already-prettier `.tsx`)."
     > "A field with a Pydantic default is NOT in the schema `required` list but openapi-typescript still renders it non-optional (`defaultNonNullable`)."
  3. `tests/integration/api/openapi.snapshot.json` is a second frozen artifact, dumped with `json.dumps(indent=2, ensure_ascii=True, sort_keys=True)` and compared by `test_openapi_snapshot.py` against `components.schemas`. Same memory gives the minimal-diff recipe:
     ```python
     snap["components"]["schemas"]["X"] = create_app().openapi()["components"]["schemas"]["X"]
     sp.write_text(json.dumps(snap, indent=2, ensure_ascii=True, sort_keys=True) + "\n")
     ```
  **Practical implication for the plan**: add the new response model's fields to `types.ts` by hand (script-write, alphabetical slot, 4-space), and patch `openapi.snapshot.json`'s one schema key surgically — don't run the naive full regen command for either file.

---

## 6. Config flags — `src/uw_scan/config.py`

- **`Settings` is a plain `pydantic.BaseModel`** (not `BaseSettings`) — `config.py:112-113`: `class Settings(BaseModel): """Strongly-typed configuration. Raises on missing required fields."""`. It has one truly required field, `api_key: SecretStr = Field(...)` (`config.py:115`) — everything else has a default, but **the only supported construction path is `Settings.from_env()`**.
- **Bare `Settings()` is env-blind / will raise** (confirmed: `api_key` has no default, `Field(...)` means required) — user memory `reference_bare_settings_is_env_blind`: "only `from_env()` loads config; bare `Settings()` raises." A new job/router/test must always go through `Settings.from_env()`.
- **`from_env()`** (`config.py:463-...`): loads `.env.local` then `.env` from repo root via a hand-rolled `_load_dotenv` (deliberately not python-dotenv; only sets keys not already in `os.environ`, so shell-exported env always wins), validates `UW_SCAN_API_KEY` is set (raises `RuntimeError` if not), enforces `_enforce_db_isolation(db_host, db_name)`, then constructs `Settings(...)` field-by-field reading each `os.environ.get(...)`.
- **Adding a bool feature flag + numeric settings** — exact precedent, `technical_live_enabled`:
  - Field declaration, `config.py:374-379`:
    ```python
    # Live technicals coverage (WS-spot splice -> technical_live cache, massive-0).
    technical_live_enabled: bool = False
    technical_live_scan_interval_minutes: int = 5
    technical_live_quote_max_age_seconds: int = 900
    ```
  - `from_env()` wiring, `config.py:854-860`:
    ```python
    technical_live_enabled=_env_bool("UW_SCAN_TECHNICAL_LIVE_ENABLED", False),
    technical_live_scan_interval_minutes=int(
        os.environ.get("TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES", "5")
    ),
    technical_live_quote_max_age_seconds=int(
        os.environ.get("TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS", "900")
    ),
    ```
  - `_env_bool` helper (`config.py:15-19`) — accepts `"1"/"true"/"yes"/"on"` (case-insensitive) as true, everything else false.
  - Naming convention: the bool kill-switch env var is prefixed `UW_SCAN_` (`UW_SCAN_TECHNICAL_LIVE_ENABLED`), but the two numeric tuning knobs are NOT prefixed (`TECHNICAL_LIVE_SCAN_INTERVAL_MINUTES`, `TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS`) — this inconsistency exists in the codebase today; follow it as-is (don't "fix" it silently in an unrelated PR) or flag the choice explicitly in the plan.
  - Default posture for a brand-new gated feature: **default `False`/off** (`technical_live_enabled: bool = False`) — matches `option_surface_capture_enabled` pattern being `True` only because it's an established always-on job; a brand-new feature should ship gated off.

---

## 7. `/api/health` integration

- File: `src/uw_scan/api/routers/health.py`. Two existing precedents for "how a job's status surfaces on health":
  1. **Freshness block** (`health.py:375-413`) — built from `DataFreshnessRepository(repo.conn, schema=...).latest_snapshot()` plus a lookup against `_REGISTRY_BY_NAME` from `reports/data_freshness.py`, assembled into a `HealthFreshness` Pydantic model (`tables`, `frozen`, `autoheal_circuit_broken`) that is threaded into **every** return path of the `health()` endpoint (`health.py:669-670, 695-696, 711-712, 725-726`) — the comment at `health.py:375-378` explains why: "built once here... so the operator surface never disappears exactly when health is already degraded."
  2. **Gap-healer block** (`health.py:415-424`):
     ```python
     from uw_scan.storage.data_gap_healer_repository import DataGapHealerRepository
     _gh = DataGapHealerRepository(repo.conn, schema=settings.db_schema).gap_healer_health()
     _gh_counts = _gh["counts"]
     gap_healer = HealthGapHealer(
         latest_run_id=_gh["latest_run_id"],
         latest_run_status=_gh["latest_run_status"],
         ...
     )
     ```
  Both blocks: (a) instantiate the domain's standalone repository inline, (b) call one summary method that returns a dict, (c) wrap it in a typed sub-model (`HealthFreshness`/`HealthGapHealer` — declared near the top of `health.py`, e.g. `ws_consumer: "WsConsumerHealth | None" = None` at `health.py:67`, `freshness: "HealthFreshness | None" = None` at `:69`, `gap_healer: "HealthGapHealer | None" = None` at `:70`), (d) thread the built object into every branch/return of `health()`.
- For a new chanlun-engine health surface (optional, only if the plan wants worker liveness on `/api/health`): the simplest existing precedent is `ws_consumer` (`health.py:521-533`, `repo.get_ws_consumer_state()` → `WsConsumerHealth`), or — if per-job liveness suffices — the automatic `job_failures` streak tracking (§3) already covers "is this job failing repeatedly" without any bespoke code; only add a dedicated health block if the feature needs a domain-specific summary (e.g. "how many signal events fired today", "last signal timestamp").

---

## 8. Dataset-registry CI gates (data-gap healer)

**Confirmed: YES, a new `(ticker, timestamp)` event-log table MUST get a `DatasetRegistryEntry` + regenerated policy doc, in the same feature PR.** This is enforced by two CI tests (per user memory `reference_new_temporal_table_gates`, corroborated by the registry/detection code read directly):

1. `tests/integration/worker/test_data_gap_full_coverage.py::test_zero_unregistered_after_full_registry` — fails if any table matching the temporal-column heuristic has no `DatasetRegistryEntry`. Detection SQL, `src/uw_scan/storage/data_gap_healer_repository.py:22-33` (`_TEMPORAL_HAVING`):
   ```sql
   bool_or(
       data_type IN ('date', 'timestamp with time zone', 'timestamp without time zone')
       OR lower(column_name) LIKE '%%date%%'
       OR lower(column_name) LIKE '%%time%%'
       OR lower(column_name) LIKE '%%\_at'
   )
   ```
   A signal-event table with a timestamp column will trip this — no way around it.
2. `tests/unit/reports/test_data_gap_dataset_policy.py::test_committed_policy_doc_is_in_sync_with_registry` — fails if `docs/runbooks/data-gap-dataset-policy.md` is stale vs `REGISTRY`. Regenerate with:
   ```bash
   uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
   ```

**Registry lives at**: `src/uw_scan/reports/data_gap_healer.py`, `REGISTRY: list[DatasetRegistryEntry] = [...]` starting at line 146 (plus several `REGISTRY.extend(...)` blocks further down).

**Correct classification for an append-only signal-event log** (mirrors `watchlist_ticker_events`, `data_gap_healer.py:352-357`):
```python
DatasetRegistryEntry(
    "watchlist_ticker_events",
    "operational_provenance",
    "provenance",
    expected_frequency="none",
),
```
`audit_mode="provenance"` is defined (`data_gap_healer.py:31`) as: `"provenance",  # raw/audit/event log; never rewritten or backfilled`. This is the right bucket for a signal-event log — it's append-only, never backfilled, no exact-coverage denominator makes sense for it. (Contrast with `"freshness_only"`, used for latest-only *caches* like `technical_live`/`technical_daily` where a missing row self-heals on the next full recompute — `data_gap_healer.py:197-205, 237-248` — not applicable here since a signal event either fired or it didn't; there's nothing to "recompute".)

`DatasetRegistryEntry` dataclass shape (frozen, `data_gap_healer.py:70-88`):
```python
@dataclass(frozen=True)
class DatasetRegistryEntry:
    table_name: str
    dataset_group: str
    audit_mode: AuditMode
    date_col: str | None = None
    ticker_col: str | None = None
    expected_frequency: str = "equity_session"
    provider: Provider = "none"
    granularity: Granularity = "none"
    healer_adapter: str | None = None
    source_system: str | None = None
    retention_days: int | None = None
    enabled: bool = True
    reason: str | None = None
```

---

## 9. Python test conventions

- **pytest-postgresql fixtures** live in `tests/integration/conftest.py`. Mechanism (not literally pytest-postgresql the package, but a hand-rolled equivalent over a real Postgres):
  - `_migrated_settings` (session-scoped, `conftest.py:87-105`): `DROP SCHEMA IF EXISTS uw_scan CASCADE`, `CREATE SCHEMA uw_scan`, then `apply_migrations(conn, ...)` — **once per pytest session** (per xdist worker, each of which gets its own physical DB, `_gw0`/`_gw1`/...).
  - `_baseline_snapshot` (session-scoped, `conftest.py:108-144`): after migration, `COPY ... TO STDOUT` every table + capture sequence positions — a byte-for-byte post-migration snapshot.
  - `seeded_db_empty_cards` (function-scoped, `conftest.py:180-193`): per test, `_reset_to_baseline` — `TRUNCATE ... CASCADE` + `COPY ... FROM STDIN` restore + `setval` sequences — this is the **"DROP SCHEMA CASCADE per fixture"** behavior referenced in the root CLAUDE.md three-tier DB table, though the literal `DROP SCHEMA CASCADE` only happens once per session; per-test isolation is the cheaper truncate+restore.
  - Requires `UW_SCAN_TEST_DB_NAME` env var; **refuses to run against the working DB** (`_test_settings()`, `conftest.py:75-84`, `pytest.fail(...)` if unset).
- **Test tree layout** (`tests/CLAUDE.md`): `tests/unit/` (pure functions, no DB/network), `tests/integration/{api,worker,storage,reports,...}` (real Postgres), `tests/live/` (hits real UW API, excluded by default, needs `UW_SCAN_API_KEY` + `@pytest.mark.live`).
- **Worker job integration test example**: `tests/integration/worker/test_technical_live_scan.py` — full pattern:
  ```python
  def test_scan_writes_cache_row(seeded_db_empty_cards):
      repo = seeded_db_empty_cards
      last_close = _seed_daily(repo, "NVDA")
      now = dt.datetime(2026, 7, 9, 19, 0, tzinfo=dt.timezone.utc)
      repo.upsert_intraday_quote(
          "NVDA", Decimal(str(round(last_close + 3.0, 2))),
          now - dt.timedelta(seconds=30), source="xenon_ws",
      )
      summary = technical_live_scan(
          repo, Settings.from_env(), ticker_filter=["NVDA"], now=now
      )
      assert summary["ok"] == 1
      got = TechnicalLiveRepository(repo.conn, schema=repo._schema).fetch("NVDA")
      assert got is not None
      assert got["spot_source"] == "xenon_ws"
  ```
  Pattern: seed via the `Repository`/domain-repository directly (no fixtures files, no mocked cursors — `tests/CLAUDE.md`: "No mocked DB / fake cursors... policy explicitly bans `unittest.mock` of cursors"), call the job function with an injected `now`, assert on the returned summary dict AND on rows read back via the domain repository.
- **Run with `uv run pytest`** — never bare `pytest` (root CLAUDE.md + `tests/CLAUDE.md`).
- **CI Guardrail 2**: every `except` block must call `.exception(...)`, use `repr(exc)`, `traceback`, or `raise` — a scanned lint gate, not just style.

---

## 10. HTTP client pattern for internal services (template for an apex REST client)

Reference: `src/uw_scan/sources/xenon_query.py` (full file read, 131 lines) — a **read-only request/response client** for a sibling service's REST API, the closest existing template for a new apex client.

- **Plain functions, not a class.** `fetch_ib_option_iv(...)` / `fetch_ib_option_quote(...)`, both keyword-only args after `*`.
- **`httpx.Client`, optionally injected.** `client: httpx.Client | None = None` param; if not given, one is created locally and closed in `finally` (`own = client is None`; `c = client or httpx.Client(timeout=timeout_s)`; `finally: if own: c.close()`) — lets callers reuse a pooled client across many calls or let the function manage its own.
- **Never-raise semantics** — every exception path returns `None` (or an empty/partial dict), never propagates:
  ```python
  try:
      resp = c.get(f"{base_url}/options/greeks", params=params, headers=headers)
      resp.raise_for_status()
      body = resp.json()
      if not isinstance(body, dict):
          return None
      ...
      return Decimal(str(greeks["impliedVol"]))
  except (httpx.HTTPError, ValueError, KeyError, InvalidOperation) as exc:
      log.warning("xenon canary fetch failed for %s %s %s%s: %s", symbol, expiry, strike, right, repr(exc))
      return None
  finally:
      if own:
          c.close()
  ```
  Module docstring states the caller contract explicitly: "the canary must never raise into the job" (`xenon_query.py:31-33`) and the second function's docstring: "Returns `None` only on transport failure — mirrors `fetch_ib_option_iv`'s never-raise contract so the snapshot job falls back to UW instead of crashing." (`xenon_query.py:88-89`).
- **Auth header pattern**: `headers = {"X-API-Key": api_key} if api_key else {}` — API key passed in as a plain string param (caller resolves it from `Settings`), not read from env inside the client.
- **Config precedent** (`src/uw_scan/sources/CLAUDE.md` + root `CLAUDE.md` "Xenon read-only query API" section): base URL and API key are `Settings` fields with env vars `XENON_QUERY_API_URL` (default `http://127.0.0.1:8321`) and `XENON_QUERY_API_KEY` (**required** even on localhost — 401 without it), with a MacBook-dev Tailscale override (`http://100.66.147.98:8321`). A new apex client should follow the identical shape: `APEX_API_URL` (localhost default / Tailscale override for MacBook dev) + no-key-required-or-required per apex's actual auth story (apex today is described in the top-level CLAUDE.md as accessed via `apex/CLAUDE.md`'s REST/WS API on `:8322`, no key mentioned in this repo — verify apex's auth requirement before assuming none, ***UNVERIFIED*** in this inventory since apex's own server code wasn't read).
- **Env rotation gotcha (applies to any XENON_*/new APEX_* var)**: worker processes freeze env at fork — rotating the URL/key requires restarting the worker process(es) that use it (root CLAUDE.md "Live spot WS feed" section: "The worker process freezes env at fork — rotating any `XENON_*` value requires restarting the spot-WS consumer process"; same stated for `XENON_QUERY_API_KEY`/`_URL` in the "Xenon read-only query API" section: "The worker freezes env at fork — rotating `XENON_QUERY_API_KEY`/`_URL` needs a worker restart (kickstart).").
- **Budget/rate discipline documented inline**: `xenon_query.py:1-6` module docstring warns "never for bulk chain capture, because the endpoint is per-contract (one IB snapshot subprocess per call)" and root CLAUDE.md: "**never bulk-poll**; quote serially with a per-mark budget." If the new apex client is a bulk/bar-data fetch (not per-contract), this specific IB-line-budget constraint doesn't apply — but the never-raise + injectable-client + explicit-timeout shape should still be followed.

---

## Summary of file/line references for the plan author

| Topic | File | Lines |
|---|---|---|
| Migrations dir + highest number | `src/uw_scan/storage/migrations/` | `106_technical_vwap_anchor.sql` highest; next=`107_*` |
| Migration idempotency doc | `src/uw_scan/storage/migrations/README.md` | 1-13 |
| Migration prefix CI gate | `scripts/check_migration_prefixes.py` | 1-49 |
| Event-log migration precedent | `src/uw_scan/storage/migrations/093_watchlist_ticker_events.sql` | full file |
| Migration runner | `src/uw_scan/storage/migrate_runner.py` | 1-33 |
| Apply script | `scripts/migrate.sh` | full file |
| Worker job example (live cache) | `src/uw_scan/worker/jobs/technical_live.py` | 93-200 |
| Worker job example (multi-leg) | `src/uw_scan/worker/jobs/regime_live.py` | 28-118 |
| Scheduler ownership pin | `src/uw_scan/worker/scheduler.py` | 407-417 |
| Scheduler closures | `src/uw_scan/worker/scheduler.py` | 997-1017 |
| Scheduler registration | `src/uw_scan/worker/scheduler.py` | 1630-1663 |
| Job failure listener (automatic) | `src/uw_scan/worker/scheduler.py` | 537-564, 573 |
| Standalone repository example | `src/uw_scan/storage/technical_live_repository.py` | full file (62 lines) |
| Repository "never grow" rule | `src/uw_scan/storage/CLAUDE.md` | "Adding a new domain" section |
| Append-only event-log repo methods | `src/uw_scan/storage/data_gap_healer_repository.py` | 481-528 |
| API endpoint example | `src/uw_scan/api/routers/stock.py` | 216-243 |
| Router wiring | `src/uw_scan/api/server.py` | 75-93 |
| Response model example | `src/uw_scan/models/technicals.py` | 111-143 |
| Model export | `src/uw_scan/models/__init__.py` | 146, 328 |
| types.ts / openapi snapshot frozen-format rule | memory `reference_generated_files_alphabetically_frozen` | n/a (user memory) |
| Config flag precedent | `src/uw_scan/config.py` | 374-379 (fields), 854-860 (`from_env`) |
| Settings raises without from_env | `src/uw_scan/config.py` | 112-115 |
| Health freshness block | `src/uw_scan/api/routers/health.py` | 375-413 |
| Health gap-healer block | `src/uw_scan/api/routers/health.py` | 415-424 |
| Dataset registry | `src/uw_scan/reports/data_gap_healer.py` | 70-88 (dataclass), 146+ (REGISTRY), 352-357 (event-log precedent) |
| Temporal-table CI detection | `src/uw_scan/storage/data_gap_healer_repository.py` | 22-33 |
| Policy doc regen command | `docs/runbooks/data-gap-dataset-policy.md` | header, 1-9 |
| pytest-postgresql fixtures | `tests/integration/conftest.py` | 87-193 |
| Worker job test example | `tests/integration/worker/test_technical_live_scan.py` | 41-58 |
| Internal HTTP client template | `src/uw_scan/sources/xenon_query.py` | full file (131 lines) |
