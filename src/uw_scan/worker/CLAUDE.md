# src/uw_scan/worker — APScheduler driver

## Files

- `scheduler.py` — `BlockingScheduler` entrypoint (`python -m uw_scan.worker.scheduler`). **The authoritative job wiring** — `jobs/` has ~38 modules; read `scheduler.py` for what actually runs, when, and on which worker role.
- `jobs/full_scan.py` / `jobs/ohlc_pull.py` / `jobs/rescan_loop.py` — the core scan/OHLC/rescan trio; the rest of `jobs/` is per-feature (gold, rates, regime, skew, vrp_*, option_surface_*, data_freshness/gap, trade_insights_ai*, …)
- `volatility_jobs.py` — `daily_spy_ohlc_refresh`, `nightly_vol_analytics_rollup` (Volatility tab v2)
- `massive_ws_consumer.py` + `ws_tick_buffer.py` + `ws_db_writer.py` — the standalone spot WS consumer process (see below)
- `market_session.py`, `schedule_expectations.py`, `gold_warmup.py` — session-window helpers, health-panel schedule expectations, gold cache warmup

## Worker roles

Set `UW_SCAN_WORKER_ROLE=uw|massive|ai|all`, `UW_SCAN_WORKER_INDEX`, and
`UW_SCAN_WORKER_COUNT` to split provider work across processes.

- `uw` workers run `full_scan`, `rescan_tick`, and `flow_data_refresh`.
- `massive` workers run `ohlc_pull` and primary-worker-only volatility
  OHLC/rollup jobs. (`spot_refresh` was deleted in Phase 7 — the WS consumer
  is the sole intraday spot writer.)
- `ai` workers run only `trade_insights_ai_tick` (gated on
  `TRADE_INSIGHTS_AI_ENABLED=true`). The tick claims rows via
  `FOR UPDATE SKIP LOCKED`, so multiple `ai` workers safely process distinct
  tickers in parallel — `UW_SCAN_WORKER_COUNT=2` doubles throughput when the
  analysis queue has multiple tickers. Without an `ai` (or `all`) worker,
  Trade Insights AI rows stay `queued` forever. Also export
  `UW_SCAN_AI_WORKER_COUNT=N` to the API process so the health panel can
  enumerate the AI worker heartbeats.
- `massive_ws` is a separate long-lived process (`python -m
  uw_scan.worker.massive_ws_consumer`; module name retained for plist/dev.sh
  compat), not an APScheduler worker — the **spot WS consumer** for both
  feeds. It holds one WebSocket connection — to xenon's IB realtime server
  (`XENON_WS_ENABLED=true`, primary; streams 24h whenever IB Gateway is up)
  or to `wss://delayed.massive.com/stocks` (fallback) — subscribes to the
  active watchlist (xenon: stocks via `symbols`, SPX/VIX/… via `indexes`
  with exchange CBOE; massive: `A.<TICKER>` per-second aggregates), and is
  the **sole writer** for `intraday_quote.price` and `watchlist_card.spot`/
  `spot_quoted_at`/`spot_source` plus the intraday return triple. Per-second
  flush window bounds the watchlist-wide quoted_at smear to ≤1s.
  **Failover:** a xenon connect failure / connect-time IB outage / in-session
  quiet period (`XENON_WS_QUIET_FAILOVER_SECONDS`, armed only inside the
  massive feed window mon-fri 04:00-20:00 ET) blocks xenon for
  `XENON_WS_RETRY_PRIMARY_SECONDS` and runs massive sessions; each fallback
  session races a xenon probe and switches back when xenon recovers. There
  is no REST fallback — if this process dies, spot data is stale until it
  reconnects. Liveness signal: `/api/health` `ws_consumer.healthy`; the
  active feed is `ws_consumer.active_source` (`xenon_ws` | `massive.com_ws`).
  Gated by `MASSIVE_WS_ENABLED` / `XENON_WS_ENABLED`; at least one must also
  be exported to the API and every scheduler worker so `full_scan` /
  `rescan_tick` skip the spot fields in their `ON CONFLICT DO UPDATE`
  clause (Phase 6 `preserve_spot`, now keyed off `Settings.ws_spot_enabled`).
- `all` preserves the legacy single scheduler shape.
- Per-ticker scheduled jobs must use the scheduler-provided shard filter.
  Rescans use DB claiming (`FOR UPDATE SKIP LOCKED`) and are not sharded.

## Schedule (all ET via `CronTrigger.from_crontab`)

| Job | Trigger | Default |
|---|---|---|
| `full_scan` | cron | `full_scan_crons` (premarket+open+RTH :00/:30+close); scans stale cards only, `full_scan_stale_after_hours` (0.33≈20min), **budget-governor `max_tickers` cap, hot-first** |
| `full_scan_hot` | cron | `*/5 9-16 * * 0-4` (uw-0; tight-freshness refresh of UI-flagged `hot` tickers; live budget pool, governor-capped) |
| `ohlc_pull` | cron | `30 17 * * 0-4` |
| `rescan_tick` | interval | 1s; user-requested rescans bypass the 8h freshness guard |
| `daily_spy_ohlc_refresh` | cron | `30 16 * * 0-4` |
| `nightly_vol_analytics_rollup` | cron | `0 18 * * 0-4` |
| `option_surface_capture` | cron | `0 19 * * 0-4` (uw-0; full-chain UW /greeks → durable grid) |
| `option_surface_research_capture` | cron | `10 19 * * 0-4` (uw-0; full-chain capture for the `research_universe` cohort — NOT the watchlist. Sequential with the 19:00 capture: both are UW `/greeks`-bound on a shared per-minute ceiling. Self-gates to a no-op on an empty cohort) |
| `option_surface_research_catchup` | cron | `20 3 * * 0-4` (uw-0; fills the cohort's *history* — the 19:10 capture only writes tonight. Weekly sample, ≤60 DTE, ≤`OPTION_SURFACE_RESEARCH_CATCHUP_MAX_CALLS` (1500) per night, resumable. Runs post-20:00-ET-reset against a fresh budget and **is** gated on `_research_budget_ok` — unlike the durable evening captures, a deferred batch is still fetchable tomorrow. Self-terminating: no gaps → spends nothing) |
| `option_surface_iv_canary` | cron | `30 19 * * 0-4` (uw-0; ATM IB-vs-UW IV diff, WARN on drift) |
| `vrp_markout_refresh` | cron | `50 18 * * 0-4` (massive-0; VRP harvest verdicts over vrp_daily) |
| `corporate_actions_refresh` | cron | `35 17 * * 0-4` (massive-0; split/dividend history for exact-RV adjustment) |
| `vrp_research_refresh` | cron | `10 19 * * 0-4` (massive-0; RV validation + sector/horizon/directional/ΔVRP — runs after the 19:00 fundamentals refresh) |
| `vrp_candidates_refresh` | cron | `25 19 * * 0-4` (massive-0; per-ticker iron-condor candidates, after vrp_research so the SELLABLE gate is fresh) |
| `vrp_paper_open` | cron | `30 19 * * 0-4` (massive-0; open paper positions for today's candidates) |
| `vrp_paper_mark` | cron | `40 19 * * 0-4` (massive-0; mark/close open paper positions, net of modeled cost) |
| `vrp_backtest_refresh` | cron | `0 20 * * 6` (massive-0; weekly full-universe model-repriced condor backtest) |
| `vrp_macro_signal_refresh` | cron | `45 3 * * 0-4` (massive-0; daily VRP macro short-vol signal snapshot — runs after `vol_index_lake_sync` at 03:15 so it reads the freshest EOD vol) |
| `greek_exposure_daily_refresh` | cron | `30 18 * * 0-4` (uw-0; single-name daily GEX/DEX from UW aggregate `/greek-exposure`, ~1 call/ticker, #179) |
| `data_freshness_monitor` | cron | `0 21 * * 0-4` (uw-0; DB-only per-table data-date freshness audit → `data_freshness_snapshots` + `/api/health`) |
| `macro_market_layer_ingest` | cron | `25 19 * * *` (massive-0, gated `UW_SCAN_MACRO_MARKET_LAYER_INGEST_ENABLED` default **off**; TreasuryDirect auctions + CFTC TFF → `macro_observations` as point-in-time evidence. Inside the macro block on purpose — `macro_state_compute` at 19:40 is the only consumer, so scheduling after it would make every release a day stale to the state that reads it. Zero UW spend. Asks CFTC for 120 days; deep history is `scripts/backfill/macro_market_layer_backfill.py`) |
| `vrp_macro_entry_grid_refresh` | cron | `50 3 * * 0-4` (massive-0; caches SPX's real UW-listed ~43-DTE strike grid into `vrp_macro_entry_grid` so the RTH entry-capture birth makes zero UW calls — runs after `vrp_macro_signal_refresh` at 03:45, in the fresh-UW-budget window) |
| `earnings_reactions_compute` | cron | `41 19 * * *` (massive-0, `UW_SCAN_EARNINGS_REACTIONS_ENABLED` default **on**; DAILY not weekday-only, so a Monday-holiday print's Tuesday close is still picked up. Pure warm-store read (`earnings_calendar` x `daily_ohlc`); zero UW/IB spend. Excludes `source='statement_obs'` calendar rows) |
| `implied_move_snapshot` | cron | `45 20 * * 0-4` (massive-0, `UW_SCAN_IMPLIED_MOVE_SNAPSHOT_ENABLED` default **on**; runs after the 19:00/19:30 surface-capture jobs so tonight's `option_surface_grid_daily` is already written. Pure warm-store read (`earnings_calendar` x surface grid); zero UW/IB spend. Excludes `source='statement_obs'` calendar rows) |
| `fundamental_change_events` | cron | `15 21 * * 0-4` (massive-0, `UW_SCAN_FUNDAMENTAL_CHANGE_EVENTS_ENABLED` default **on**; runs after `implied_move_snapshot` and the 18:20 `fundamental_refresh` so `band_entry`/`band_exit`/`bucket_flip`/`implied_move_shift` all read tonight's freshest state) |

Intraday spot is no longer a scheduler job — it streams from the
WebSocket consumer in `uw_scan.worker.massive_ws_consumer` (started as
its own process by `scripts/dev.sh`). Toggle via `MASSIVE_WS_ENABLED`
(massive fallback feed) and `XENON_WS_ENABLED` (xenon IB primary feed).

## Rules

- **Every job opens its own conn** via `_repo(settings)`, which is a `with psycopg.connect(...)` block — it **commits** on clean exit and rolls back on an exception. Never go back to `connect()` plus `close()` in a `finally`: closing a psycopg connection discards the transaction. That is invisible for the repository methods that call `self._conn.commit()` themselves and silently fatal for the ones built on `self._conn.transaction()`, which only emits `COMMIT` when it opened the transaction — so any job that reads before it writes leaves the connection mid-transaction and its write block degrades to a savepoint nothing commits. That shape threw away every macro domain state for two nights while the job logged `ok`. No long-lived connections — APScheduler runs jobs from a thread pool.
- **MASSIVE_API_KEY can be unset.** Jobs that need it should no-op + warn (see `_spy_ohlc_refresh`). Never crash the scheduler.
- **No duplicated provider work.** If a worker role can run in more than one process, loops over watchlist tickers must either use stable shard ownership or atomically claim queued work.
- **ET timezone everywhere.** `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`. Don't use UTC for trading-hour crons.
- **APScheduler weekdays are Monday=0.** Use `0-4` for Monday-Friday crons.
- **Automatic UW scan freshness guard.** Full scan only queries tickers with no persisted card data or card data older than 8 hours. User-requested rescans always run.
- **UW flow refresh window is weekdays 5:00am-7:59pm ET.** Flow-tab refresh skips outside that window.
- **UW daily-budget governor.** The shared 120k account counter (resets 20:00 ET / 00:00 UTC) is split into a `live` pool (`full_scan`, `full_scan_hot`, `rescan_tick`) and a `research` pool (everything else incl. `*_backfill`). `_live_max_tickers` caps `full_scan`/`full_scan_hot` at the remaining live budget (hot-first, ÷worker_count for shards); `_research_budget_ok` gates research jobs. The account-wide `official_daily_count` header is the hard `total_guard`. Tune via `UW_{LIVE,RESEARCH}_DAILY_CEILING` / `UW_TOTAL_DAILY_GUARD`; disable with `UW_BUDGET_GOVERNOR_ENABLED=false`. See `sources/uw_budget.py`.
- **Idempotent.** A job that runs twice in a minute (e.g., after a restart) must produce the same DB state.
- **No business logic in `scheduler.py`** — it just wires triggers to functions. Heavy lifting lives in `jobs/*.py` and `volatility_jobs.py`.
- **Signals: SIGTERM/SIGINT** trigger `sched.shutdown(wait=False)` then `sys.exit(0)`. Don't introduce blocking cleanup.
- **Workers don't hot-reload.** uvicorn `--reload` refreshes only the API process; APScheduler workers keep running the module they imported at fork. If an edit "doesn't take effect", first run `/bin/ps -axww -o pid,etime,command | grep uw_scan` and compare `etime` to your edit time — restart the `concurrently` parent (`bash scripts/dev.sh`), not individual workers. Also check for duplicate `concurrently` parents (two = two competing dev stacks). Same applies to env rotation (`DEEPSEEK_API_KEY`, `XENON_*`, …): env is frozen at fork.

## Provider concurrency model

The sharded worker design (`c6544cb`) splits ticker work across N UW workers,
each holding its own per-worker advisory lock (`lock_key=91501 + worker_index`).
This is intentional and preserves single-worker semantics within each shard —
but it has two implications operators should know:

1. **UW request rate scales with `UW_SCAN_WORKER_COUNT`.** During the nightly
   flow refresh window (weekdays 5:00am–7:59pm ET), peak UW QPS is `N × baseline`
   where `N = UW_SCAN_WORKER_COUNT`. Budget UW rate limits accordingly. If you
   start hitting 429s, lower the worker count or stagger the cron triggers
   rather than converting back to a global lock — the speedup is the point.

2. **OHLC pulls are owned by dedicated jobs, not by `full_scan`/`rescan`.**
   `_full_scan` and `_rescan` in `scheduler.py` pass `_NoOhlc()` (a no-op
   provider) to `full_scan_once` / `rescan_tick`. Daily OHLC fetches happen
   only in `_ohlc_pull` (massive REST). Intraday spot now flows through
   the standalone `massive_ws_consumer` process — not the scheduler at all.
   If "massive provider reachability" health signals look quiet from a UW
   worker, that is by design — check the massive-role worker or the
   `ws_consumer` block in `/api/health` instead.
