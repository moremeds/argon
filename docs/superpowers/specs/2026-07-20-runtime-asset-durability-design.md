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
  nightly 20:00 ET). Its `REGISTRY` holds ~35 datasets across `options_chain`,
  `core_watchlist`, `derived_volatility`, `uw_volatility`, `regime_marketwide`,
  `gold_rates_macro`, `operational_provenance`. **None of `vol_index_daily`,
  `cri_snapshots`, `vcg_snapshots`, `canary_snapshots` are registered.**

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
- `OPS_ALERT_WEBHOOK_URL` is **unset** in `/opt/argon/.env`, so any job that does
  call `send_alert` is a no-op in prod

Detection worked. Logging worked. Delivery does not exist.

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
- `pyproject.toml` — **this is the booby trap in this PR.** The build backend is
  `setuptools.build_meta` and the only packaging config present is
  `[tool.setuptools.packages.find] where = ["src"]`. There is **no
  `[tool.setuptools.package-data]` and no `include-package-data`**, so
  non-`.py` files under `src/` do **not** ship in the wheel by default. Moving
  the JSON/Markdown without adding:

  ```toml
  [tool.setuptools.package-data]
  "uw_scan.cards" = ["data/*.json", "data/*.md"]
  ```

  reproduces the exact bug this PR exists to fix, one layer deeper and harder to
  see. The container smoke in §6 is what catches it if this step is missed —
  which is precisely why that test is non-optional.
- Leave a pointer in `docs/research/regime/README.md` so the research trail
  survives the move.

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

`sources/lake.py` — `_read_local` / `_list_local` raise when the configured
**root** does not exist. A missing **symbol** under a present root still returns
`[]`, since a symbol may legitimately be absent. This keeps
`tests/unit/test_lake_reader.py:90`
(`read_vol_index_parquet(tmp_path, "NONEXISTENT") == []`) valid, because
`tmp_path` exists.

Three lines, and the highest-value change in this PR: it converts this exact
failure from 13 days of drift into a crash on the first run.

**C. `scripts/check_runtime_assets.py` + CI wiring**

Fails if any module under `src/` references `Path.home()` or resolves a path
outside the package. Same shape and placement as the existing
`scripts/check_no_yahoo.py` and `scripts/check_migration_prefixes.py`; add to
`.github/workflows/ci.yml`. Catches `reports/vrp_macro_drawdown.py:71` today.

**D. `vol_index_daily` → `data_gap_healer` REGISTRY** as a `freshness_only`
entry. It cannot backfill a lake sync, but the freeze becomes a first-class
tracked item instead of a field in a JSON blob. Per the repo's temporal-table
rule, this requires the accompanying dataset-policy doc regeneration in the same
PR.

**E. `REGIME_RECOVERY_LOOKBACK_DAYS`: 7 → 30** (`worker/scheduler.py:164`).
A recovery window must exceed realistic **time-to-detect**, not typical outage
length. At 7 days, this incident's 07-08→07-13 span would never have healed even
after the mount was fixed — leaving a permanent hole in the middle of the series
while the recent tail looked correct.

**G′. Guard against silent R2 resurrection**

`resolve_lake_root` raises if it ever resolves an s3 root. R2 is retired and its
producer has been dead since 2026-05-21, so any s3 resolution is now by
definition a misconfiguration.

Explicitly **not** deleting the ~150-line s3 branch: the apex migration (§5) is
expected to delete `lake_resolver.py` and most of `lake.py` wholesale, so a
deletion now is churn on code already scheduled to die. Three lines close the
trap; the surgery happens once, later.

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
  `OPS_ALERT_WEBHOOK_URL`. Considered and deliberately declined in favour of the
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
| **Container smoke** — build the image, then inside it run `load_calibration()` and `GET /api/regime/guidance` | **the actual 07-08 failure** |

The container smoke is the only check that reproduces the real failure mode.
The CI guard script is the cheap proxy that runs on every push.

## 7. Verification

**Post-deploy, falsifiable:** `GET /api/regime/guidance` returns **HTTP 500 in
prod right now**. If it returns 200 after the PR1 deploy, PR1 worked.

Additional checks:

- `docker exec <worker> python -c "from uw_scan.cards.canary_calibration import load_calibration; load_calibration()"`
  succeeds on a **freshly pulled image** with no `docker cp`
- `uw_scan.vol_index_daily` advances on the next `vol_index_lake_sync` tick
- `/api/health` `freshness` shows no regime table frozen
- PR2: Gold page renders a stale badge on the 108-day-old WGC/CB reserves panels

## 8. Risks

- **`git mv` of the calibration JSON breaks any external reference.** Mitigated
  by the `docs/research/regime/README.md` pointer and by repointing
  `regime_canary_v1_v2_compare.py` in the same PR. `COMPOSITE_VERSION` is part
  of the canary snapshot dedup key, so a bad move surfaces immediately as
  unfilled snapshots rather than silently wrong values.
- **H (fail-loud) could crash a worker on a transient volume unmount.** Accepted:
  a crash-looping worker is strictly better than 13 days of silent staleness, and
  it is the entire point of the change.
- **E (lookback 7 → 30) increases per-tick work** for the hourly regime recovery
  scan. Bounded — it only computes for dates genuinely missing a snapshot, which
  is normally zero.
