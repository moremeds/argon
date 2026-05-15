# src/uw_scan/worker — APScheduler driver

## Files

- `scheduler.py` — `BlockingScheduler` entrypoint (`python -m uw_scan.worker.scheduler`)
- `jobs/full_scan.py` — full UW scan over the watchlist
- `jobs/ohlc_pull.py` — daily OHLC pull from massive
- `jobs/rescan_loop.py` — drains the `jobs` table for ad-hoc rescans (1s interval)
- `jobs/spot_refresh.py` — intraday spot price refresh
- `volatility_jobs.py` — `daily_spy_ohlc_refresh`, `nightly_vol_analytics_rollup` (Volatility tab v2)

## Worker roles

Set `UW_SCAN_WORKER_ROLE=uw|massive|all`, `UW_SCAN_WORKER_INDEX`, and
`UW_SCAN_WORKER_COUNT` to split provider work across processes.

- `uw` workers run `full_scan`, `rescan_tick`, and `flow_data_refresh`.
- `massive` workers run `spot_refresh`, `ohlc_pull`, and primary-worker-only
  volatility OHLC/rollup jobs.
- `all` preserves the legacy single scheduler shape.
- Per-ticker scheduled jobs must use the scheduler-provided shard filter.
  Rescans use DB claiming (`FOR UPDATE SKIP LOCKED`) and are not sharded.

## Schedule (all ET via `CronTrigger.from_crontab`)

| Job | Trigger | Default |
|---|---|---|
| `spot_refresh` | interval | `UW_SCAN_SPOT_REFRESH_SECONDS` (default 300s) |
| `full_scan` | cron | `0 5-16 * * 1-5`; scans only missing cards or cards older than 8h |
| `ohlc_pull` | cron | `30 17 * * 1-5` |
| `rescan_tick` | interval | 1s; user-requested rescans bypass the 8h freshness guard |
| `daily_spy_ohlc_refresh` | cron | `30 16 * * 1-5` |
| `nightly_vol_analytics_rollup` | cron | `0 18 * * 1-5` |

## Rules

- **Every job opens its own conn** via `_repo(settings)` and closes it in `finally`. No long-lived connections — APScheduler runs jobs from a thread pool.
- **MASSIVE_API_KEY can be unset.** Jobs that need it should no-op + warn (see `_spy_ohlc_refresh`). Never crash the scheduler.
- **No duplicated provider work.** If a worker role can run in more than one process, loops over watchlist tickers must either use stable shard ownership or atomically claim queued work.
- **ET timezone everywhere.** `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`. Don't use UTC for trading-hour crons.
- **Automatic UW scan freshness guard.** Full scan only queries tickers with no persisted card data or card data older than 8 hours. User-requested rescans always run.
- **UW flow refresh window is weekdays 5:00am-7:59pm ET.** Flow-tab refresh skips outside that window.
- **Idempotent.** A job that runs twice in a minute (e.g., after a restart) must produce the same DB state.
- **No business logic in `scheduler.py`** — it just wires triggers to functions. Heavy lifting lives in `jobs/*.py` and `volatility_jobs.py`.
- **Signals: SIGTERM/SIGINT** trigger `sched.shutdown(wait=False)` then `sys.exit(0)`. Don't introduce blocking cleanup.
