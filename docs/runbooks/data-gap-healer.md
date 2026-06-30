# Data gap healer — operator runbook

A resumable, budget-aware service that accounts for **every** recorded `uw_scan`
table and repairs safe coverage gaps. It is the *exact* cousin of the
`data_freshness` monitor: freshness answers "is this table fresh enough?" with a
grace window; the gap healer answers "exactly which (ticker, date) rows are
missing?" and heals them.

- Code: `reports/data_gap_healer.py` (registry + scanner), `worker/jobs/data_gap_adapters.py`
  (heal dispatch), `worker/jobs/data_gap_healer.py` (orchestration + nightly job),
  `storage/data_gap_healer_repository.py`, `migration 092`.
- CLI: `scripts/backfill/data_gap_healer.py`.
- Policy matrix (generated from the registry): `data-gap-dataset-policy.md`.
- Health: `/api/health` `gap_healer` block.

## What it does

```
audit  -> exact gap items (gaps-only) via set-difference SQL   [ZERO provider calls]
execute -> heal each gap through an EXISTING production job, then VERIFY the row
verify  -> recompute coverage for a run (read-only)
verify-all -> full audit + discovery + report artifact         [ZERO provider calls]
```

A gap is not "healed" until a strict `COUNT(*)` at the row's own `data_date`
proves coverage. A provider that returns nothing (e.g. a past date UW no longer
serves) is recorded as honest `no_data`, never a false success.

## Nightly job

Off by default. Enable with `DATA_GAP_HEALER_ENABLED=true` (then restart the
`uw-0` / `all` worker so the env is re-read at fork). Runs at **20:00 ET** — just
after the 00:00 UTC UW quota reset — so it draws on a fresh 60k UW budget.

| Env | Default | Meaning |
|---|---|---|
| `DATA_GAP_HEALER_ENABLED` | `false` | master switch |
| `DATA_GAP_HEALER_CRON_ET` | `0 20 * * 1-5` | 20:00 America/New_York, weekdays |
| `DATA_GAP_HEALER_DATASETS` | `""` (all healable) | CSV to narrow |
| `DATA_GAP_HEALER_START` | `2026-01-01` | audit/heal from here to today (as much history as possible) |
| `DATA_GAP_HEALER_MAX_UW_CALLS` | `20000` | **the only cap** — Massive/external are uncapped |

The job: audits strict gaps, heals them under the UW cap, then refreshes the
re-runnable datasets (macro/FRED/rates/gold + DB rollups), writes the report,
and refreshes `/api/health`. Single-flight via an advisory lock; it **skips if a
prior healer run is still `running`** so it never fights an in-flight backfill.

## Manual commands

```bash
# Audit only, no provider calls (safe anywhere)
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/data_gap_healer.py audit --start 2026-01-01

# CI/discovery gate — nonzero if any temporal table is unregistered
uv run python scripts/backfill/data_gap_healer.py audit --discover

# Heal DB-to-DB datasets only (no UW spend)
... execute --datasets vrp_daily,market_tide_sentiment_daily,stock_analytics_daily --confirm

# Heal UW-budgeted option surface with a hard cap
... execute --datasets option_surface_grid_daily --max-uw-calls 20000 --confirm

# Continue a partially-budget-capped run
... resume --run-id 123 --max-uw-calls 20000

# Full audit + evidence artifact (output/data-gap/<date>-gap-report.{md,json})
... verify-all --start 2026-01-01 --json
```

## Caveat lifecycle (no-data exclusions)

A caveat removes a `(ticker[, date range])` from strict denominators — e.g. SPCX
before it listed (seeded in `migration 092`). Caveats are treated as **global**
ticker exclusions (the `dataset` field is informational); this correctly handles
listing/delisting. To add one: `DataGapHealerRepository.upsert_caveat(...)`, then
re-run `audit` — the previously-flagged pairs drop with zero provider calls.

## What NOT to automate

- **Full UW option-surface history while the live stack needs budget** — the
  nightly cap reserves a third of the daily quota; a deep historical backfill
  should be a deliberate manual `execute` with its own `--max-uw-calls`, run with
  the nightly job disabled (or outside its window) so the advisory lock doesn't
  matter.
- **Datasets beyond provider retention** — old UW option/greek history settles
  to `no_data` once; the healer records the caveat rather than retrying forever.
- **market_tide / top_net_impact historical heal** — UW serves the current
  session only; these are audit-only today (heal adapter is a TODO).

## Monitoring

- `/api/health` → `gap_healer`: latest run id/status, `open_gaps`,
  `open_by_dataset`, healed/no_data/failed/skipped_budget, `last_verified_at`.
- `output/data-gap/<date>-gap-report.md` — human-readable per-run report.
- `data_gap_runs` / `data_gap_items` — the durable source of truth.
