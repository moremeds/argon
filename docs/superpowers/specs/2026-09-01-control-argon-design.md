# control-argon — an agent-usable verification/control entry point

Status: design approved for Step 1–2 (done, this PR); Step 3 (the CLI) not yet built.
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
