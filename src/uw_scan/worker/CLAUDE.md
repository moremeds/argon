# src/uw_scan/worker — APScheduler driver

## Files

- `scheduler.py` — `BlockingScheduler` entrypoint (`python -m uw_scan.worker.scheduler`)
- `jobs/full_scan.py` — full UW scan over the watchlist
- `jobs/ohlc_pull.py` — daily OHLC pull from massive
- `jobs/rescan_loop.py` — drains the `jobs` table for ad-hoc rescans (1s interval)
- `jobs/spot_refresh.py` — intraday spot price refresh
- `volatility_jobs.py` — `daily_spy_ohlc_refresh`, `nightly_vol_analytics_rollup` (Volatility tab v2)

## Worker roles

Set `UW_SCAN_WORKER_ROLE=uw|massive|ai|all`, `UW_SCAN_WORKER_INDEX`, and
`UW_SCAN_WORKER_COUNT` to split provider work across processes.

- `uw` workers run `full_scan`, `rescan_tick`, and `flow_data_refresh`.
- `massive` workers run `spot_refresh`, `ohlc_pull`, and primary-worker-only
  volatility OHLC/rollup jobs.
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
| `full_scan` | cron | `0 5-16 * * 0-4`; scans only missing cards or cards older than 8h |
| `ohlc_pull` | cron | `30 17 * * 0-4` |
| `rescan_tick` | interval | 1s; user-requested rescans bypass the 8h freshness guard |
| `daily_spy_ohlc_refresh` | cron | `30 16 * * 0-4` |
| `nightly_vol_analytics_rollup` | cron | `0 18 * * 0-4` |
| `vrp_markout_refresh` | cron | `50 18 * * 0-4` (massive-0; VRP harvest verdicts over vrp_daily) |
| `corporate_actions_refresh` | cron | `35 17 * * 0-4` (massive-0; split/dividend history for exact-RV adjustment) |
| `vrp_research_refresh` | cron | `10 19 * * 0-4` (massive-0; RV validation + sector/horizon/directional/ΔVRP — runs after the 19:00 fundamentals refresh) |
| `vrp_candidates_refresh` | cron | `25 19 * * 0-4` (massive-0; per-ticker iron-condor candidates, after vrp_research so the SELLABLE gate is fresh) |
| `vrp_paper_open` | cron | `30 19 * * 0-4` (massive-0; open paper positions for today's candidates) |
| `vrp_paper_mark` | cron | `40 19 * * 0-4` (massive-0; mark/close open paper positions, net of modeled cost) |
| `vrp_backtest_refresh` | cron | `0 20 * * 6` (massive-0; weekly full-universe model-repriced condor backtest) |
| `vrp_macro_signal_refresh` | cron | `45 3 * * 0-4` (massive-0; daily VRP macro short-vol signal snapshot — runs after `vol_index_lake_sync` at 03:15 so it reads the freshest EOD vol) |

Intraday spot is no longer a scheduler job — it streams from the
WebSocket consumer in `uw_scan.worker.massive_ws_consumer` (started as
its own process by `scripts/dev.sh`). Toggle via `MASSIVE_WS_ENABLED`
(massive fallback feed) and `XENON_WS_ENABLED` (xenon IB primary feed).

## Rules

- **Every job opens its own conn** via `_repo(settings)` and closes it in `finally`. No long-lived connections — APScheduler runs jobs from a thread pool.
- **MASSIVE_API_KEY can be unset.** Jobs that need it should no-op + warn (see `_spy_ohlc_refresh`). Never crash the scheduler.
- **No duplicated provider work.** If a worker role can run in more than one process, loops over watchlist tickers must either use stable shard ownership or atomically claim queued work.
- **ET timezone everywhere.** `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`. Don't use UTC for trading-hour crons.
- **APScheduler weekdays are Monday=0.** Use `0-4` for Monday-Friday crons.
- **Automatic UW scan freshness guard.** Full scan only queries tickers with no persisted card data or card data older than 8 hours. User-requested rescans always run.
- **UW flow refresh window is weekdays 5:00am-7:59pm ET.** Flow-tab refresh skips outside that window.
- **Idempotent.** A job that runs twice in a minute (e.g., after a restart) must produce the same DB state.
- **No business logic in `scheduler.py`** — it just wires triggers to functions. Heavy lifting lives in `jobs/*.py` and `volatility_jobs.py`.
- **Signals: SIGTERM/SIGINT** trigger `sched.shutdown(wait=False)` then `sys.exit(0)`. Don't introduce blocking cleanup.

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
