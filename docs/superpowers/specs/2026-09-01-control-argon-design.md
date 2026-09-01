# control-argon — an agent-usable verification/control entry point

Status: Step 1–2 shipped (PR #407). Step 3 shipped, with four deviations recorded below.
Date: 2026-09-01

## The constraint that shapes everything

**Converge, don't amplify.** Every subcommand must retire an existing entry point.
A subcommand that deletes nothing does not ship in v1. This is the acceptance test
for the whole thing, applied per-subcommand, not to the CLI as a whole.

The net account for v1:

| Before | After |
| --- | --- |
| 5 Playwright configs (100 lines) | 2 configs |
| 8 debug PNGs in the repo root | `output/playwright/investigations/` |
| `scripts/smoke_container_assets.sh` + reading `dev.sh` by eye | `control-argon doctor` |
| `scripts/deploy/macmini-data-promote.sh` + the `.env.local`-points-at-mini browse hack | `control-argon sync` / `sync --push` |
| ad-hoc `/tmp` Playwright scripts | `control-argon screenshot` |
| the 14-line `## Daily commands` block in `CLAUDE.md` | `control-argon --help` |

## Decisions (pre-approved, not re-litigated here)

- **Lives in `argon/`, committed normally, not gitignored.** argon is PUBLIC and
  deliberately so. Gitignoring hides nothing the app hasn't already published, while
  costing CI coverage, helium-agent readability, and version history — guaranteed drift.
- **Python**, `scripts/control_argon.py` + a `[project.scripts]` entry point, invoked
  `uv run control-argon`. The repo is Python-dominant, CI's ruff/pytest already cover
  `scripts/`, and DB work is native. Adding a Node CLI toolchain would be amplification.
  Playwright is driven by shelling out to `npx playwright`.
- **`sync` target is `option_wizard_local`, never `option_wizard_test`** — the test DB
  TRUNCATEs per test; synced data would not survive one case.
- **`sync` direction: mini `option_wizard` → MacBook `option_wizard_local`, 7 days
  default.** The mini is always on and holds the freshest data.
- **Explicitly not doing:** a Feature Map, routine `/maintain-*` commands, a helium
  `argon-shepherd`. The first two are pstack's amplification items; the third waits
  until the CLI is running and its concrete overlap with `livewire-shepherd` is visible.

## Verified before designing (do not re-test)

1. **Playwright's `webServer` is config-level and cannot be set per project.** It is
   declared on `TestConfig` (`web/node_modules/playwright/types/test.d.ts:1036`, inside
   the interface opening at 865) and is absent from `Project` (747) and `FullProject`
   (757–836).

   A second, worse trap found while checking: `projects: [...]` makes a bare
   `playwright test` run *every* project. Adding `canary`/`worktree` projects would have
   silently pointed the default run — the one nearest to CI — at dead ports 3002/3003.

   **Consequence:** Step 1 lands as the pre-approved 5→2 fallback, and it lands *without*
   `projects`. The three stray configs differed from the default only by `baseURL` and by
   not wanting a `webServer`; both are env-expressible, so
   `PW_NO_WEBSERVER=1 PLAYWRIGHT_WEB_PORT=<port>` replaces all three files with two lines.
   `playwright.technicals.config.ts` survives because it boots a genuinely different
   server stack (fixture API on 18400 + its own build), which a config-level `webServer`
   cannot express conditionally without booting it for every e2e run.

2. **`pg_dump` cannot filter rows**, so `sync` uses `psql \copy (SELECT … WHERE <date-col> >= …) TO STDOUT` per table.

3. **`_enforce_db_isolation` does not protect `sync`.** It is called exactly once, from
   `src/uw_scan/config.py:671` inside `Settings.from_env` — a Python import-time guard.
   `psql`/`pg_dump` never import `uw_scan`. **`sync` must carry its own (host, db_name)
   assertion**, reusing `_HOST_DB_RULES` rather than restating it.

## Subcommands

### `doctor`

Retires `scripts/smoke_container_assets.sh` and reading `dev.sh` by eye. Reports:

- process/port liveness for web (3001), API (8400), workers
- DB reachability and which tier is actually being addressed (host + db_name, printed,
  because a code default is not deployed state)
- **freshness:** `max(<date-col>)` on the key tables → `surface stale N days, run
  \`control-argon sync\``
- **manifest drift** (below)

### `sync [--days 7]` / `sync --push`

Per-table `\copy` over SSH, filtered on the table's date column. `--push` absorbs
`scripts/deploy/macmini-data-promote.sh` (whose writer-detection / `--confirm` / dump-archive
mechanism is reused; only the direction differs) and retires the browse hack of pointing
`.env.local` at the mini.

### `smoke <ticker>`

The end of the chain in `CLAUDE.md`'s smoke-test rule — "the user validates via the web
page" is what hard-codes the human as the bottleneck. `smoke` drives API enqueue → DB row
→ worker claim → DB result → rendered page, and reports the verdict.

### `screenshot <name>` / `snapshot`

Retires the ad-hoc `/tmp` Playwright script. Output path is **hard-coded** to
`output/playwright/` — a root-level screenshot becomes structurally impossible rather than
merely against the rules (`CLAUDE.md:161`, a rule that had been violated 8 times).

### `--help`

Retires the 14-line `## Daily commands` block in `CLAUDE.md`.

## The one design point that must not be lost

`sync`'s drift surface is the **table → date-column manifest**. Add a dated table, forget
the manifest, and the sync silently skips it: the data looks fine but is missing a slice.
That is the hardest possible failure to notice.

**Countermeasure — `doctor` queries the drift in reverse.** It reads
`information_schema.columns` for tables in schema `uw_scan` that have a `date`/`timestamp`
column and are *not* in the manifest, and WARNs on each. The manifest proves itself stale;
nobody has to remember to update it.

An explicit `IGNORED` set sits beside the manifest for tables that legitimately have a date
column and legitimately should not sync (audit logs, per-run scratch). A table must appear
in exactly one of the two sets — that is the check's teeth, and its own unit test.

## Sequencing

Step 1 (config convergence) and Step 2 (root cleanup) are pure deletion, reversible, and
independent of the CLI's design — landed first so the convergence claim is proven by a diff
before any new code is written. Step 3 follows.


---

## What actually happened (written after building it)

Four decisions in this spec did not survive contact. Recorded here rather than
quietly rewritten above.

### 1. There is no SSH layer, and no `\copy`

The mini's Postgres answers **directly over Tailscale** from the MacBook on the
same `argon_app` credentials (`psql -h 100.66.147.98 -d option_wizard` returns
rows). So `sync` is two psycopg connections in one process, streaming
`COPY … TO STDOUT` into `COPY … FROM STDIN`. `pg_dump`'s missing row filter never
came up, and nothing has to exist on the mini.

### 2. The table → date-column manifest is gone, and so is the drift check

**168 of 175 tables carry a date column.** A hand-maintained manifest at that
scale is a liability, and the reverse-drift check existed only to police it. Both
are replaced by:

- a **deny-list** (5 raw/audit tables, ~11 GB) — everything else syncs *by
  default*, so a newly added table is included without anyone remembering. The
  failure mode flips from "silently missing a slice" to "the sync got slower".
- an **auto-detected date column**, chosen from `DATE_COL_PRIORITY`, which puts
  observation dates ahead of write stamps — `inserted_at` dates the write, so a
  backfilled row reads as fresh under it.
- a **size rule instead of a dimension/fact classification**: under 64 MB, copy
  the table whole; over it, copy the date window. Size is the only reason to
  window in the first place.
- `sync` **reports any windowed table that copied 0 rows** as "likely
  slow-moving". That is the self-diagnosing property the drift check was for,
  obtained without a list to maintain.

This preserves the stated intent — the list must not be able to go stale in
silence — with less machinery. It is a deliberate departure from the approved
design, not an oversight.

### 3. Nothing is deleted, anywhere

The sync COPYs into a `TEMP` table and then `INSERT … ON CONFLICT DO NOTHING`.
Additive and idempotent (a second run inserts 0 rows), and it sidesteps the FK
pins — cited macro evidence is undeletable by design, so a delete-then-copy sync
would have hard-failed on `macro_source_artifacts`.

Two things Postgres rejects on insert had to be handled explicitly, both found by
running it rather than by reading the schema: **53 `GENERATED ALWAYS AS … STORED`
columns** (dropped from the copy, recomputed on insert) and **2 `GENERATED ALWAYS
AS IDENTITY` columns** (kept, with `OVERRIDING SYSTEM VALUE`, because that id is
what `ON CONFLICT` dedups on).

### 4. `doctor` gained the check that matters most, and `sync --push` is deferred

While testing, the local `/api/health` returned **200 while serving v0.13.0 of a
v0.13.2 checkout**, with a worker heartbeat 87.6 hours old — and 500ing on every
real endpoint. A liveness probe that only asks "did something answer" certifies
exactly that outage as healthy. `doctor` now compares the API's reported version
against `VERSION` and fails on a stale worker heartbeat.

`sync --push` (the mini-ward direction, absorbing
`scripts/deploy/macmini-data-promote.sh`) is **not built**. It writes to the
prodlike tier, and there is no way to rehearse that safely from here. The promote
script stays until there is.

### The honest convergence account

Retired: 3 Playwright configs, 8 repo-root PNGs, the `.env.local`-points-at-the-mini
browse hack, ad-hoc `/tmp` Playwright scripts, the 14-line `## Daily commands`
block (now 5 lines and a pointer), and the human standing at the end of the smoke
chain.

**Not** retired, contrary to the table at the top of this spec:
`scripts/smoke_container_assets.sh` verifies that a **built Docker image** carries
its runtime assets — a different question from "is the local stack healthy", and
one `doctor` does not answer. It stays. So does `macmini-data-promote.sh`, per
deviation 4.

The line count goes UP (one ~700-line module plus its test). What goes down is the
number of **entry points**: one command to learn instead of five scripts, one
env-var convention instead of four config files, and one place a screenshot can
land.
