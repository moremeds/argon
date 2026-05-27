# 5% Canary — Plan Execution Log

Companion log to `docs/superpowers/plans/2026-05-26-5pct-canary-indicator.md`
(v0.5). One entry per milestone with commit SHA, summary, and the
verification command actually run.

PR: https://github.com/moremeds/unusual-whales/pull/83
Branch: `feat/5pct-canary-indicator`
Worktree: `~/projects/unusual-whales/.claude/worktrees/feat+5pct-canary-indicator/`

## Milestones

| # | SHA | Summary | Verification |
|---|---|---|---|
| Plan v0.5 | `7bcc731` | Execution-audit fixes inlined into task bodies | n/a (docs) |
| M1 | `b2d9375` | Migration 059 + `canary_snapshots` table + `CanarySnapshotRepository` (Tasks 1-2) | `bash scripts/migrate.sh` ×2 (idempotent), `uv run pytest tests/integration/regime/test_canary_db_constraints.py -v` → 6 passed |
| M2 | `e8b54a9` | Scorer module (`canary_scoring.py`), 4 score forms, 5 smooth-signal scorers, calibration JSON+loader (Tasks 3-5) | `uv run pytest tests/unit/cards/test_canary_{calibration,scoring}.py -v` → 27 passed |
| M3 | `98dea31` | State machine (primary + confirmed-canary), composite, canonical hash with pinned digest (Tasks 6-10) | `uv run pytest tests/unit/cards/test_canary_*.py tests/unit/storage/test_canary_payload_hash.py -v` → 55 passed |
| M4 | `d5e6b60` | Scanner + causality regression test (Tasks 11-12) | `uv run pytest tests/integration/regime/test_canary_scanner.py tests/unit/cards/test_canary_causality.py -v` → 9 passed |
| M5 | `1d1e96f` | Scheduler wiring (inner `_regime_canary_scan` + hourly :30 CronTrigger) (Task 13) | `uv run python -c "import uw_scan.worker.scheduler; print('ok')"` |
| M6 | `3468743` | API endpoints `/regime/canary*` + Pydantic schemas + types.ts regen (Tasks 14-16) | `uv run pytest tests/integration/api/test_canary_endpoints.py -v` → 3 passed; `cd web && npm run typecheck && npm run test` → 345 passed |
| M7 | `3afe63b` | UI: CanarySubTab + CanaryValidationPanel + ComponentBar extraction + RegimePanel wiring (Tasks 17-18) | `cd web && npm run typecheck && npm run test` → 60 files / 345 tests passed |
| M8 | `b5005ae` | regime_backtest_runs widening (migration 060) + backtest script with `--calibrate`/`--form-sweep`/`--report` (Tasks 19-21) | `bash scripts/migrate.sh` ×2 (idempotent); INSERT `'canary'` row succeeds; script `--help` renders; `--calibrate` raises documented RuntimeError on missing warm-store data |
| M9 | `c886fb3` | OOS gate (4 tests) + cap-binding determinism (2 tests) (Tasks 22-23) | `uv run pytest tests/integration/regime/test_canary_oos_gate.py tests/integration/regime/test_canary_warning_state.py -v` → 6 passed |
| M10 | (this commit) | Methodology doc + execution log (Tasks 24-25) | full canary test sweep → 81 passed in 30.10s |

## Migration evidence

```
src/uw_scan/storage/migrations/
├── 059_canary_snapshots.sql            (M1)
└── 060_regime_backtest_runs_canary.sql (M8)
```

Both applied twice against the scratch DB `option_wizard_test_canary`:

- 059 second-run NOTICEs for existing indexes; DO blocks no-op for
  existing constraints. Exit 0; "All migrations applied" final line.
- 060 second-run `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` cycle —
  idempotent by construction. Exit 0.

## Backtest evidence

The `--calibrate` / `--form-sweep` / `--report` runs against the real warm
store (with 2007+ vol-complex parquet seed) were **NOT executed** in this
implementation pass. Reason: the local scratch DB
(`option_wizard_test_canary`) does not have the historical seed loaded;
running the script there produces NaN AUCs which would pollute the
`canary-calibration-v1.json` file. The script structure was validated by
exercising `--help`, `--calibrate`, `--form-sweep`, and `--report` against
the scratch DB — `--calibrate` raises the documented RuntimeError
("no overlapping bars on or before 2014-12-31"); `--report` raises
"no eval rows produced".

The committed `canary-calibration-v1.json` carries the **v0.1 priors**
(pre-calibration) anchored on the relevant literature. The first real
`--calibrate` run is deferred to the publish PR follow-up.

`regime_backtest_runs.id` for `indicator='canary'`: none yet
(seeded only in OOS gate tests via `_seed_completed_canary_backtest_row`,
which inserts inside the test transaction and is rolled back).

## Snapshot evidence

`uw_scan.canary_snapshots` row count on the working DB: 0 (the scheduler
will populate at :30 each hour once the worker process is up; the
integration test for the scanner exercises insert/idempotent/overwrite
paths against the scratch DB only).

## Standing-rule check

| Rule | Evidence |
|---|---|
| Yahoo as data source | ❌ NEVER. Scanner reads only `vol_index_daily` (massive.com EOD + IB intraday); search confirms no `yahoo` import in any commit since branch-from-main. |
| Naked shorts in strategy code | n/a — indicator is descriptive scoring, no trade execution layer. |
| Secrets to codex subprocesses | n/a — no codex subprocess introduced. |
| In-memory-only analytical results | ❌ NEVER. Every snapshot persists to `canary_snapshots`; every backtest persists to `regime_backtest_runs`. |
| Co-Authored-By: Claude trailer | ❌ NEVER. `git log feat/5pct-canary-indicator ^main \| grep -i 'co-authored'` → empty. |
| Migration idempotent | ✅ Both 059 and 060 verified by running `scripts/migrate.sh` twice with `set -euo pipefail`; no errors. |
| Module size budget (<500 lines target) | `canary_scoring.py` = ~430 lines; `scanner/canary.py` = ~240; `backtest_canary.py` = ~600 (script, not library — allowed). |
| repository.py extended | ✅ NEVER. New persistence domain is in focused module `canary_snapshot_repository.py`. |

## Unverified assumptions

- **UI visual rendering not tested in a browser.** I cannot click the
  `5% CANARY` sub-tab from CLI. The Vitest + typecheck pass guarantees
  TypeScript correctness but does NOT prove visual output. The follow-up
  Playwright e2e milestone (M12) covers this.
- **`/canary` against a live populated DB not tested.** API endpoint tests
  cover the empty-DB 503 path only. The populated-DB path is implicitly
  validated by `test_persisted_warning_state_matches_payload` which
  exercises insert → scalar-column → JSON-payload round-trip.
- **`--calibrate` / `--form-sweep` / `--report` not run against warm
  store.** Script structure validated by exercising the failure paths.
- **OOS gate constants are LITERATURE-DERIVED placeholders.**
  `LAST_KNOWN_AUC_UP5D_2PCT=0.55`, `UP20D_5PCT=0.56`, `UP60D_10PCT=0.58`.
  These will be re-pinned to actual values after the first publish
  `--report` run; the seeded test fixture currently uses values above the
  publishable bar.
- **Scheduler not started.** I verified the job is registered via static
  inspection; I did NOT start the worker process to confirm the cron
  fires. The test infrastructure does not exercise APScheduler triggers.

## How to verify locally

```bash
# 1. Apply migrations to the working DB
bash scripts/migrate.sh

# 2. Run the full canary test sweep
export UW_SCAN_API_KEY=$(head -1 .env | cut -d= -f2)  # or a dummy
export UW_SCAN_TEST_DB_NAME=option_wizard_test_canary
uv run pytest tests/ -k canary -v

# 3. Web typecheck + unit tests
cd web && npm run typecheck && npm run test

# 4. Start the API + Web for UI smoke (no workers — keeps the data path quiet)
uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400
cd web && npm run dev
# → open http://localhost:3001/regime → click "5% CANARY" sub-tab

# 5. After populating with real data
uv run python scripts/backtest_canary.py --calibrate
uv run python scripts/backtest_canary.py --form-sweep --write-summary
uv run python scripts/backtest_canary.py --report --write-summary
uv run pytest tests/integration/regime/test_canary_oos_gate.py -v
# If OOS gate passes, update LAST_KNOWN_AUC_* constants to the actual
# values from the report summary (rounded to 2 decimals).
```
