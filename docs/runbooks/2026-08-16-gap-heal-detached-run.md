# Detached gap-heal run — 2026-08-16

Recovery card for the option-surface backfill launched 2026-08-16. Written so
the run survives losing the Claude session that started it. The **durable trace
is Postgres**, not the log file: `uw_scan.data_gap_runs` / `data_gap_items` carry
run status and per-item outcome, so a lost log costs nothing.

## The run

| | |
|---|---|
| run_id | **75** |
| dataset | `option_surface_grid_daily` |
| window | `--start 2026-02-17` — **the wrong call, see "Retention" below** |
| UW cap | 30,000 calls |
| host pid | 34950 (`nohup docker exec …`, survives SSH exit) |
| log | `/opt/argon/logs/gap-heal-surface-20260816.log` on the mini |

Launched with:

```bash
ssh macmini 'export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; \
  nohup docker exec argon-worker-uw-0-1 \
    python scripts/backfill/data_gap_healer.py execute \
      --start 2026-02-17 --datasets option_surface_grid_daily \
      --max-uw-calls 30000 --confirm \
  > /opt/argon/logs/gap-heal-surface-20260816.log 2>&1 < /dev/null & disown'
```

`setsid` does NOT exist on macOS — the first launch attempt silently failed with
`command not found` and started nothing. `nohup … < /dev/null &` is the working
form; always verify with `ps -p <pid>` rather than trusting the launch line.

## Outcome — run 75 COMPLETE

Ran 15:23:43 → 17:00:39 HKT (1h37m) and stopped on its budget cap, as designed.

| | |
|---|---|
| healed | **1,491** ticker-dates |
| no_data | 9 |
| skipped_budget | **4,206** (still open) |
| UW spent | 30,000 (exactly the cap) |
| measured rate | **20.1 calls/heal** (probe predicted 21.4) |

Verified against the table, not the healer's self-report: **914,661 rows** landed
with `inserted_at` inside the run window, spanning exactly **1,491 distinct
`(ticker, market_date)`** pairs over 2026-02-17→2026-07-31. The count matches the
claimed `healed`, and the floor confirms `--start 2026-02-17` was honored, so no
budget went to the pre-Feb-17 dates that are already past UW retention.

**Remaining: 4,206 recoverable ticker-dates ≈ 84,500 UW calls** — more than one
day's headroom. This needs several days, which is the argument for the nightly
job below rather than more hand-launched runs.

The SSH session watching this run died mid-flight (`Connection reset by peer`).
The run was unaffected — which is the whole point of detaching. Never infer run
state from the watcher's exit code; read `data_gap_runs`.

## Check status

```bash
# is it alive?
ssh macmini 'ps -o pid,etime,command -p 34950'

# progress (authoritative — survives log loss)
ssh macmini 'export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; \
  docker exec argon-worker-uw-0-1 python -c "
import psycopg
from uw_scan.config import Settings
s=Settings.from_env(); c=psycopg.connect(s.db_dsn()); cur=c.cursor()
cur.execute(\"select id,status,started_at,finished_at from uw_scan.data_gap_runs where id=75\")
print(cur.fetchone())
cur.execute(\"select status,count(*) from uw_scan.data_gap_items where run_id=75 group by 1\")
print(cur.fetchall())
"'

# UW budget burn
ssh macmini 'curl -s http://127.0.0.1:8400/api/health' | python3 -c "import json,sys;print(json.load(sys.stdin)['uw_today'])"
```

## If it dies partway

The healer is resumable by design — it re-reads unfinished items for the run:

```bash
ssh macmini 'export PATH=/opt/homebrew/bin:/usr/local/bin:$PATH; \
  docker exec argon-worker-uw-0-1 python scripts/backfill/data_gap_healer.py \
    resume --run-id 75 --max-uw-calls 30000'
```

A **Watchtower redeploy kills the container and therefore this run.** That is
safe — resume picks it up. Do not restart with `execute`, which opens a new run.

## Measured costs (probes, 2026-08-16)

Both probes were bounded at 300 UW calls and are recorded as runs 73 and 74.

| dataset | gaps | calls per heal | full-backfill cost |
|---|---:|---:|---:|
| `option_surface_grid_daily` | 7,056 | **21.4** (one call per expiry) | ~142k |
| `uw_short_pressure_daily` | 8,121 | **3.0** | ~24.6k |
| `uw_volatility_signal_daily` | 8,120 | unmeasured | ~24.6k if same shape |
| `volatility_stats_history` | 8,120 | unmeasured | ~24.6k if same shape |
| `uw_gex_levels_daily` | 8,120 | unmeasured | ~24.6k if same shape |
| `vrp_daily` + `stock_analytics_daily` | 149 | 0 (db-derived) | **done — all `no_data`, unfillable** |

Daily UW ceiling is 120,000. The surface backfill alone exceeds one full day, so
it cannot complete in a single run.

## Retention — the ~180-day cutoff is NOT a hard wall

`--start 2026-02-17` was chosen by treating CLAUDE.md's "UW's ~180-day window"
as a hard date (2026-08-16 minus 180 days). **That inference is wrong**, and run
73 disproves it: with `--start 2026-01-01` it healed **2026-01-06 (CLSK)**,
2026-01-13 (HPQ), 2026-02-02 (S) and 2026-02-13 (CSCO) — all comfortably older
than the supposed edge — while its single `no_data` fell on 2026-02-18, *inside*
the "safe" side. Availability does not fall off a cliff at 180 days.

Consequence: run 75 needlessly excluded ~1,340 healable ticker-dates. Nothing was
lost (they stay in the backlog), but do not repeat the exclusion, and do not cite
"permanently lost before <date>" as fact — no measurement supports it. Let the
healer discover unavailability by getting `no_data`.

## What these gaps are NOT

They are **not** the 2026-08-11→16 `full_scan` outage. Every gap item in the
audit ends **2026-07-31**. The jump from `open_gaps: 0` to `39,877` on 2026-08-16
was the audit WINDOW widening (runs 66–68 used `--start 2026-08-01`; runs 69–70
used `--start 2026-01-01`), not new damage surfacing.

The outage window itself audits to **zero gaps** (run 71, `--start 2026-08-11
--end 2026-08-15`) because the expected-session calendar is itself a captured
table — an outage erases the evidence of its own missing days. Rebuild that spine
before trusting any audit that covers an outage.

## The nightly healer is ALREADY ON — no hand-launched runs needed

`data_gap_healer_enabled` defaults to `False` **in code**, and reading that
default as the deployed state is a mistake. The mini's `/opt/argon/.env` carries:

```
DATA_GAP_HEALER_ENABLED=true
DATA_GAP_HEALER_MAX_UW_CALLS=12000
```

Verified on the running `worker-uw-0` container: `_should_schedule_data_gap_healer`
returns `True`, cron `0 20 * * 0-4` (20:00 ET Mon–Fri = 08:00 HKT), window from
`2026-01-01`, all healable datasets. It audits **and** heals — `_run_nightly`
calls `audit_into_run(mode="execute")` then `execute_run`.

It has been firing every weekday for weeks. A sample from `data_gap_runs`:

| run | started (HKT) | outcome |
|---|---|---|
| 57 | 2026-08-11 08:00 | healed **5,963**, no_data 339, skipped_budget 40,935 |
| 56 | 2026-08-08 08:00 | healed 1, no_data 129 |
| 55 | 2026-08-07 08:00 | healed 1, no_data 129 |

**The gap in that series is the diagnostic:** no run on 2026-08-12, 13 or 14. The
nightly healer rides the same `worker-uw-0` process as `full_scan`, so the outage
took both. It has not fired since because 08-15/16 are the weekend; the next fire
is the coming Monday 20:00 ET.

So the backlog drains on its own at up to 12,000 UW calls/night. Before proposing
to "enable" anything here, read the mini's `.env` — not the dataclass default.
