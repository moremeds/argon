# Runtime Asset Durability + Data Freshness Visibility — Design

- **Date:** 2026-07-20
- **Status:** design approved, pending implementation
- **Trigger:** 13-day silent regime-data outage, 2026-07-08 → 2026-07-20

## 1. Incident summary

The Docker cutover on 2026-07-08 (`201307e`, `39250c8`) silently severed argon's
access to the parquet data lake. EOD regime analytics froze at **2026-07-07** and
nobody was told for 13 days.

Measured at 2026-07-20, before remediation:

```
uw_scan.vol_index_daily   max(trade_date) = 2026-07-07   (all 18 symbols, uniform)
cri_snapshots   basis=eod  max = 2026-07-07     basis=live max = 2026-07-20
vcg_snapshots   basis=eod  max = 2026-07-07     basis=live max = 2026-07-20
canary_snapshots           max = 2026-07-07
```

The `basis='live'` rows stayed current — they ride the WS quote path, which is a
separate feed. Any freshness check on `max(data_date)` that does not group by
`basis` reports green. That is why the page looked alive.

### 1.1 Root cause

Two independent violations of a single invariant, both introduced by
containerization:

**(a) `docs/` is not in the image.** `docker/app.Dockerfile` copies
`pyproject.toml`, `uv.lock`, `README.md`, `VERSION`, `src/`, `scripts/`, and the
built `.venv`. It does not copy `docs/`. Two runtime code paths read from there:

| Path | Consumer | Symptom |
|---|---|---|
| `docs/research/regime/canary-calibration-v1.json` | `cards/canary_calibration.py::load_calibration` | `FileNotFoundError` on every canary run |
| `docs/research/regime/guidance.md` | `api/routers/regime_validation.py::_parse_guidance_md` | `GET /api/regime/guidance` → HTTP 500 |

`/api/regime/validation` and `/vcg-validation` survived containerization
untouched because they had already been migrated to Postgres
(`regime_validation.py:250`: *"Source of truth is `uw_scan.regime_backtest_runs`.
The previous file fallback … was removed"*). The surviving-vs-broken split across
those three sibling endpoints is the design precedent this spec follows.

**(b) An absent lake root returns `[]` instead of raising.** The containers have
no lake mount, so `resolve_lake_root` fell through to R2 — whose producer push
has been dead since **2026-05-21** (`lake_resolver.py:9-17` documents that exact
outage). The freshness override written to catch precisely this
(*prefer local when local is strictly ahead*) could not fire, because there was
no local mirror inside the container to compare against.

```
$ docker exec argon-worker-massive-0-1 python -c "resolve_lake_root(...)"
kind= s3   local= None
VIX rows= 9190   max= 2026-05-21

$ docker exec argon-worker-massive-0-1 ls /root/market-warehouse
ls: cannot access '/root/market-warehouse': No such file or directory
```

`vol_index_lake_sync` then read a frozen bucket, found no new rows, inserted
nothing, and logged nothing. `sources/lake.py::_read_local` and `_list_local`
both return `[]` when the root does not exist — a missing mount is
indistinguishable from "no new data".

### 1.2 Why the self-heal did not fire

Two separate mechanisms, neither of which could have caught this:

- **`data_gap_healer`** — enabled in prod (`DATA_GAP_HEALER_ENABLED=true`,
  nightly 20:00 ET). All four tables **are** registered (`vol_index_daily` at
  `data_gap_healer.py:501`; `cri/vcg/canary_snapshots` in the following
  `_entries` block), but every one of them is `audit_mode="freshness_only"` —
  a mode that tracks age and **never heals**. `vol_index_daily` is additionally
  mis-grouped under `options_chain` with the reason string *"UW-retention/
  event-log shaped"*, which is wrong: it is lake-sourced, not UW-sourced.

  So the healer was never going to fix this. Registration was not the gap;
  `freshness_only` is correct for a lake-sourced table (there is no fetch to
  retry) and the classification error is cosmetic. **There is no healer change
  worth making here** — see §5.

- **`scanners/{cri,vcg,canary}.recover_recent_gaps`** — does cover these tables,
  runs hourly, and filled nothing for 13 days. It enumerates candidate dates
  **from `vol_index_daily` itself**:

  ```python
  aligned_days = sorted(set.intersection(*dates_by_sym.values()))
  missing = [d for d in window if d not in existing]
  ```

  With the input frozen there were no missing dates, so it reported healthy. It
  healed correctly against a frozen ruler. `REGIME_RECOVERY_LOOKBACK_DAYS = 7`
  and canary's `FileNotFoundError` were both moot — it never got that far.

> **A gap-filler keyed on its own input cannot detect a frozen input.** Only
> freshness monitoring can, and it did.

### 1.3 Why nobody was told

`data_freshness_monitor` **detected this on night one** and carried
`consecutive_frozen_nights: 5` in `/api/health` throughout. It never reached a
human:

- `worker/jobs/data_freshness_monitor.py` only calls `logger.warning` — it never
  calls `alerts.send_alert`
- `src/uw_scan/alerts.py` (webhook sink) exists and is unused by it
- `UW_SCAN_OPS_ALERT_WEBHOOK_URL` is **unset** in `/opt/argon/.env`, so `send_alert`
  returns `False` without posting (`alerts.py`: `if not url: return False`)

Detection worked. Logging worked. Delivery did not.

**Precise, because it bears on §4.1 H:** a delivery path *does* exist and is
already wired — `scheduler.py:556-562` escalates to `send_alert` at 3 and 10
consecutive failures of any job, and `/api/health` exposes `job_failures[]`
streaks. It is one unset env var from working. But it fires on **job
failures**, and a frozen lake produced no job failure — the sync "succeeded"
against an empty read. Nothing in the freshness path was ever connected to it.

This is recorded as fact, not as a reopening of the PR2 decision: the inline
badge remains the chosen delivery mechanism (no secret to manage). Setting
`UW_SCAN_OPS_ALERT_WEBHOOK_URL` would additionally light up the existing job-failure
escalation, which item H now feeds. That remains the operator's call.

### 1.4 Environment facts that made this non-obvious

- `~/market-warehouse/data-lake` is a **symlink** to
  `/Volumes/DATA_LAKE/livewire/data-lake` (an external volume). Mounting the
  symlink path yields an empty directory in the container.
- The container runtime is **colima**, not Docker Desktop. `~/.colima/default/colima.yaml`
  mounts **only** `/Volumes/DATA_LAKE/livewire/data-lake`. **`$HOME` is not
  mounted.** Any container path assuming a home-dir layout on this host is dead
  on arrival.

## 2. Remediation already applied (2026-07-20)

Applied directly to the mini to restore service. **PR1 must mirror the config
half into the repo, or the next sync reverts it.**

| Change | Where | Durable? |
|---|---|---|
| `volumes: /Volumes/DATA_LAKE/livewire/data-lake:/lake:ro` on `x-common` | `/opt/argon/compose.yml` | ❌ repo copy lacks it |
| `LAKE_VOL_INDEX_ROOT`, `LAKE_CREDIT_ETF_ROOT` → `/lake/...` | `/opt/argon/.env` | ❌ not in `.env.example` |
| `R2_*` (5 keys) commented out — retired bucket | `/opt/argon/.env` | ❌ |
| `canary-calibration-v1.json` copied into container | `docker cp` | ❌ **ephemeral — next Watchtower deploy wipes it** |
| Backfill: 144 lake rows, 8 cri + 8 vcg + 8 canary snapshots | Postgres | ✅ persisted |

Backups: `/opt/argon/compose.yml.bak-20260720`, `/opt/argon/.env.bak-20260720`.

### 2.1 Still broken in prod as of this writing

The mount fixed the two lake roots that flow through `Settings`
(`LAKE_VOL_INDEX_ROOT`, `LAKE_CREDIT_ETF_ROOT`). It did **not** fix
`reports/vrp_macro_drawdown.py::_default_lake_root`, which reads a *different*
env var and falls back to a home-dir path:

```
$ docker exec argon-worker-massive-0-1 sh -c 'echo MARKET_WAREHOUSE_LAKE=$MARKET_WAREHOUSE_LAKE; ls /root/market-warehouse'
MARKET_WAREHOUSE_LAKE=
ls: cannot access '/root/market-warehouse': No such file or directory
```

`load_index_vol` is imported by `worker/jobs/vrp_macro_signal.py` — a **scheduled
job**, not research-only — which is the source of the recurring
`vrp_macro_signal QQQ: skipped — FileNotFoundError(...)` warnings. Setting
`MARKET_WAREHOUSE_LAKE=/lake` in `/opt/argon/.env` plus a worker restart clears
it; PR1 item B carries the same var into `.env.example` so it is not lost again.

This is a live degradation, independent of the regime tables, and is the
strongest single argument for item C: **two env vars, two default paths, one of
them broken for 12 days without anyone noticing.**

Post-backfill state verified: every trading day 2026-07-08 → 2026-07-17 has 1
cri + 1 vcg + 1 canary snapshot and 18 `vol_index_daily` symbols; the freshness
monitor drops from 6 frozen tables to 4 (the remaining 4 are pre-existing
gold/macro freezes, out of scope here).

## 3. The invariant

> **Anything the app reads at runtime either ships inside the Python package,
> comes from Postgres, or comes from an explicitly-mounted path — and a
> configured-but-absent source raises, never returns empty.**

Both root causes are violations of this one rule. Fixing the instances without
fixing the rule relocates the next outage.

## 4. Scope

Two PRs. The split is deliberate and justified under the repo's
one-change-one-PR rule by its own carve-out (*an independent prerequisite that
must merge — and deploy — before the rest*): **PR1 has a clock on it**, because
the canary calibration currently exists only as a `docker cp` into a running
container and is one Watchtower deploy from vanishing. PR2 has no deadline and
touches a disjoint file set.

### 4.1 PR1 — durability (backend + CI)

**A. Runtime assets into the package**

```
git mv docs/research/regime/canary-calibration-v1.json  src/uw_scan/cards/data/
git mv docs/research/regime/canary-calibration-v2.json  src/uw_scan/cards/data/
git mv docs/research/regime/guidance.md                 src/uw_scan/cards/data/
```

- `cards/canary_calibration.py` — `DEFAULT_PATH` becomes
  `importlib.resources.files("uw_scan.cards") / "data" / f"canary-calibration-v{COMPOSITE_VERSION}.json"`.
  `load_calibration(path=...)` keeps its parameter for tests.
- `api/routers/regime_validation.py` — `_parse_guidance_md` reads package data;
  **delete `_safe_doc_path` and `_DOCS_REGIME`**. Those four path-traversal
  guards exist to serve one hardcoded filename (`_safe_doc_path("guidance.md")`
  is the only call site) and become dead once the file is package data.
- `reports/regime_canary_v1_v2_compare.py` — repoint `V1_CAL_PATH` / `V2_CAL_PATH`.
- `pyproject.toml` — add, for wheel correctness:

  ```toml
  [tool.setuptools.package-data]
  "uw_scan.cards" = ["data/*.json", "data/*.md"]
  ```

  **Scoped honestly:** this is *not* load-bearing for prod. `app.Dockerfile`
  does `COPY src/ ./src/` and `uv sync`, which produces an **editable** install
  pointing at `/app/src` — the container imports from the copied tree, never
  from a built wheel. The existing proof is `src/uw_scan/storage/migrations/`:
  117 `.sql` files under `src/`, loaded at runtime, working in prod today with
  no `package-data` declaration. The moved assets would reach the container
  with or without this block.

  It is still worth two lines, because `uv build --wheel` (release artifact,
  and any future non-editable install) *would* drop them. Task 1's wheel
  inspection is what verifies it. **The container smoke does not** — it would
  pass either way, since the container reads `/app/src` directly.
- Leave a pointer in `docs/research/regime/README.md` so the research trail
  survives the move (three stale references: lines ~15-16, ~41, ~116).

Rationale for package data over a `COPY docs/` line: a `COPY` enshrines "`docs/`
is runtime-critical", so the next person tidying a docs file takes down prod.
Package data cannot be forgotten by a `COPY` line because there is no `COPY` line
to forget, and it works identically in tests, CI, wheels, and containers.

**B. Compose + env mirrored into the repo**

- `docker-compose.yml` — add the `volumes:` mount to `x-common`, with a comment
  naming the symlink and the colima `$HOME` constraint.
- `.env.example` — document `LAKE_VOL_INDEX_ROOT`, `LAKE_CREDIT_ETF_ROOT`, and
  `MARKET_WAREHOUSE_LAKE` (the last is read by
  `reports/vrp_macro_drawdown.py::_default_lake_root`, which still defaults to
  `~/market-warehouse/data-lake` and is therefore broken in-container today).

**H. Fail loud on an absent lake root**

Two changes, at two boundaries:

1. `sources/lake.py` — `_read_local` / `_list_local` raise when the configured
   **root** does not exist. A missing **symbol** under a present root still
   returns `[]`, since a symbol may legitimately be absent. This keeps
   `tests/unit/test_lake_reader.py:90`
   (`read_vol_index_parquet(tmp_path, "NONEXISTENT") == []`) valid, because
   `tmp_path` exists.
2. `worker/jobs/vol_index_lake_sync.py` — **zero symbols is a failure, not a
   success.** `root.exists()` cannot catch a *mounted-but-empty* lake, and
   Docker auto-creates a missing bind-mount source, so that state is reachable
   whenever the external `/Volumes/DATA_LAKE` is unmounted. Today the job
   returns `{"symbols": 0, …}` and is recorded as a success — the precise shape
   of the original bug. It now raises.

   `credit_etf_lake_sync` is deliberately left alone: HYG/JNK/LQD are
   individually optional and its per-symbol skip-with-warning is correct there.

Three lines, and the highest-value change in this PR. **What it actually does —
not a crash.** APScheduler catches job exceptions, so the raise becomes:

```
_require_root raises
  → APScheduler EVENT_JOB_ERROR
  → JobFailuresRepository.record_failure("vol_index_lake_sync")   [persisted]
  → /api/health job_failures[] shows a consecutive-failure streak  [visible]
  → send_alert() at streak 3 and 10                     [wired; no-op today]
```

That is the real improvement: today the same condition produces
`logger.info("vol_index_lake_sync: no symbols at …")` and a **success**
recorded against the job. After the change it produces a recorded *failure*
with a growing streak on the health endpoint. The worker keeps running; nothing
crash-loops.

Verification therefore keys on `job_failures`, not on a container restart —
see §7.

**C. `scripts/check_runtime_assets.py` + CI wiring**

Fails if any module under `src/` references `Path.home()` or resolves a path
outside the package. Same shape and placement as the existing
`scripts/check_no_yahoo.py` and `scripts/check_migration_prefixes.py`; add to
`.github/workflows/ci.yml`. Catches `reports/vrp_macro_drawdown.py:71` today.

**D. ~~`vol_index_daily` → `data_gap_healer` REGISTRY~~ — DROPPED.**

Written on the false premise that the table was unregistered. It is already
there (`data_gap_healer.py:501`, `freshness_only`), so adding it would create a
duplicate `table_name` and fail the existing
`test_registry_table_names_are_unique`. Registering an already-registered table
buys no detection: `freshness_only` never heals, and `data_freshness.
MONITORED_TABLES` — which *is* what caught the freeze — already covers it.

The one real defect is cosmetic: the entry sits in the `options_chain` group
with the reason *"UW-retention/event-log shaped"*, but `vol_index_daily` is
lake-sourced. Not worth a registry reshuffle plus a policy-doc regeneration in
a PR with a deploy clock on it. Recorded here so the next reader does not
rediscover it as a bug.

**E. `REGIME_RECOVERY_LOOKBACK_DAYS`: 7 → 30** (`worker/scheduler.py:164`).
A recovery window must exceed realistic **time-to-detect**, not typical outage
length. At 7 days, this incident's 07-08→07-13 span would never have healed even
after the mount was fixed — leaving a permanent hole in the middle of the series
while the recent tail looked correct.

**G′. Guard against silent R2 resurrection — at worker startup**

R2 is retired and its producer has been dead since 2026-05-21, so an `.env`
carrying `R2_*` is by definition a misconfiguration — and one that silently
reroutes every lake read to a bucket frozen at that date.

**Revised after review.** The first draft put the raise inside
`resolve_lake_root`. That is wrong: `tests/unit/sources/test_lake_resolver.py`
holds 15 tests, **8 of which assert that R2 config resolves to an s3 root**, plus
two integration suites (`test_lake_r2.py`, `test_lake_sync_r2.py`) and three
docs. The "three-line guard" was really three lines plus retiring ten tests plus
rewriting three docs, inside the PR that has a deploy clock on it.

The check belongs at **boot**, not on every read — R2 config is a *deployment*
mistake. `worker/scheduler.py::_validate_worker_settings` already exists for
exactly this, has no tests to disturb, and runs before any job is scheduled.
`resolve_lake_root` and its suite stay untouched and green, and get deleted
wholesale by the apex migration as originally intended.

Explicitly **not** deleting the ~150-line s3 branch, for the same reason as
before: churn on code already scheduled to die.

### 4.2 PR2 — visibility (frontend only)

Staleness indication renders **inline on each panel**, on the data it describes,
rather than as a global banner.

Coverage: **regime + gold/macro**. This is the incident surface plus the surface
that is provably wrong right now — as of 2026-07-20 the Gold page serves
`wgc_etf_monthly` and `cb_gold_reserves_monthly` data that is **108 days stale**,
with no indication.

`/api/health` already returns the per-table freshness block and it is already
typed at `web/lib/types.ts:3974`; `web/app/admin/page.tsx` already consumes
`/api/health`. **This PR therefore requires zero backend, zero API, and zero
`types.ts` changes** — which matters, because those generated files are
alphabetically frozen and must never be fully regenerated.

- `web/lib/useFreshness.ts` — fetch `/api/health` once per page; expose
  `{table_name → {max_data_date, days_stale, frozen}}`.
- `web/components/ui/StaleBadge.tsx` — patterned on the existing
  `web/components/regime/ui/RegimePill.tsx`. Renders only when `frozen` or
  `days_stale >= 2`. Shows the as-of date and the staleness.
- Wired into `CriSubTab`, `VcgSubTab`, `CanarySubTab`, and the gold/macro panels,
  keyed by table name.

Known ceiling, to carry a `ponytail:` comment rather than be hidden: the
freshness monitor runs nightly at 21:00 ET, so the badge can lag reality by up to
24h. Upgrade path is computing freshness live if that ever matters. For "this
data is 10 days old" the lag is immaterial.

## 5. Non-goals

**apex as the bar-data source (target architecture, not this plan).** The
standing directive is to read price/bar data through the apex REST API rather
than reading the lake directly. That is the correct end state and would delete
argon's lake mount entirely. It is blocked today:

```
GET /bars/HYG?timeframe=1d  → 200  (through 2026-07-17)
GET /bars/VIX?timeframe=1d  → 500
apex log: AdjustedDataUnavailable: Silver daily artifact is missing for VIX
```

apex serves **adjusted** bars from the lake's `silver/` layer, which contains
only `asset_class=equity`. The vol complex exists only in
`bronze/asset_class=volatility`. Note that vol indices have no splits or
dividends, so an "adjusted VIX" is definitionally raw VIX — the silver layer for
them is a passthrough, making this cheap to fix in principle.

Two caveats recorded so the migration is not oversold when it happens:

1. **It does not remove the freeze risk, it moves it.** apex reads silver, silver
   derives from bronze. A stalled bronze feed — which is exactly what happened
   here — leaves apex serving stale bars just as happily. PR2's badge remains
   necessary, arguably more so with an extra hop.
2. **It does not remove the equity mount on its own.** `vrp_macro_signal` and
   `vrp_macro_drawdown` read QQQ/IWM/SPY from `asset_class=equity` directly.
   Migrating only the credit ETFs would keep the mount *and* create a second bar
   path — worse than either end state.

Owner: apex-side work is the operator's, tracked separately.

**Also out of scope:**

- livewire `intraday_catchup`, failing every run since 2026-07-14 (IB Gateway
  preflight, cron pinned to a `.worktrees/silver-rehearsal` checkout, and a
  broken `send-alert --error-summary` invocation). Different repo. Intraday vol
  bars remain frozen at 2026-07-13; CRI/VCG/canary need only dailies, so the
  regime surface is unaffected.
- Wiring `data_freshness_monitor` to `alerts.send_alert` / setting
  `UW_SCAN_OPS_ALERT_WEBHOOK_URL`. Considered and deliberately declined in favour of the
  inline badge — no secret to manage. Documented in §1.3 so the gap is known
  rather than forgotten.
- Deleting the R2/s3 branch (see G′).

## 6. Testing

The central trap: **a unit test run from the repo checkout cannot catch any of
this**, because `docs/` exists in a checkout. The failure only appears in the
built artifact. Tests must target the artifact, not the source tree.

| Test | Catches |
|---|---|
| `test_calibration_loads_from_package` — asserts resolution via `importlib.resources`, not a repo-relative path | A (regression) |
| `test_guidance_loads_from_package` | A (regression) |
| `test_lake_root_missing_raises` — absent root raises; absent symbol under a present root still `[]` | H |
| `scripts/check_runtime_assets.py` self-check | C |
| **Wheel inspection** — `uv build --wheel`, assert `cards/data/*` is in the archive | a missing `package-data` block |
| **Container smoke** — build the image, then inside it run `load_calibration()` and `_parse_guidance_md()` | **the actual 07-08 failure** |

Two different checks for two different failures — do not conflate them:

- The **container smoke** reproduces the real 07-08 failure (asset absent from
  the image). Because the image installs `/app/src` editable, it passes with or
  without the `package-data` block.
- The **wheel inspection** is the only thing that catches a missing
  `package-data` block, which breaks release wheels, not the container.

The CI guard script is the cheap proxy for both that runs on every push.

## 7. Verification

**Post-deploy, falsifiable:** `GET /api/regime/guidance` returns **HTTP 500 in
prod right now**. If it returns 200 after the PR1 deploy, PR1 worked.

Additional checks:

- `docker exec <worker> python -c "from uw_scan.cards.canary_calibration import load_calibration; load_calibration()"`
  succeeds on a **freshly pulled image** with no `docker cp`
- `uw_scan.vol_index_daily` advances on the next `vol_index_lake_sync` tick
  (03:15 ET) — this is the business outcome, not a proxy for it
- `/api/health` `job_failures[]` contains **no** `vol_index_lake_sync` entry.
  This is the falsifiable test for item H: a streak appearing there means the
  mount is wrong and H is doing its job; the pre-change code would have shown
  the job as *succeeding*
- `/api/health` `freshness` shows no regime table frozen
- PR2: Gold page renders a stale badge on the 108-day-old WGC/CB reserves panels

## 8. Risks

- **`git mv` of the calibration JSON breaks any external reference.** Mitigated
  by the `docs/research/regime/README.md` pointer and by repointing
  `regime_canary_v1_v2_compare.py` in the same PR. `COMPOSITE_VERSION` is part
  of the canary snapshot dedup key, so a bad move surfaces immediately as
  unfilled snapshots rather than silently wrong values.
- **H (fail-loud) turns a transient volume unmount into a nightly job failure.**
  `/Volumes/DATA_LAKE` is an *external* volume; if it is ever unmounted, Docker
  will happily bind-mount an auto-created empty directory at that path, so
  `/lake` exists but is empty. The configured roots are
  `/lake/bronze/asset_class=…`, which do **not** exist under an empty `/lake`,
  so `_require_root` still fires correctly — the check is load-bearing precisely
  because it tests the *asset-class subpath*, not `/lake` itself. Consequence is
  a recorded job failure and a health-endpoint streak, not a crash loop.
  Accepted; that is the entire point of the change.
- **Rollback:** every item is independently revertable, and H is the only one
  with a behavioural blast radius. If it proves too noisy, revert the
  `_require_root` calls alone (two lines) — the asset moves, compose mount, and
  CI guard are inert with respect to it.
- **E (lookback 7 → 30) increases per-tick work** for the hourly regime recovery
  scan. Bounded — it only computes for dates genuinely missing a snapshot, which
  is normally zero.
