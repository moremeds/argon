# src/uw_scan/sources — external data clients

The only place that talks to the outside world.

## Per-ticker sources (UW + OHLC)

- `uw.py` — Unusual Whales fetchers. Every fetcher: call UW → write audit row → persist raw compressed payload → normalize → return typed model.
- `ohlc.py` — `MassiveOhlcProvider` (Polygon-shaped REST). Daily bars only after Phase 7 — the `fetch_intraday_quote` REST path was removed; intraday spot now streams via `massive_ws.py`.
- `massive_ws.py` — Async WebSocket client for `wss://delayed.massive.com/stocks`. Per-second `A.*` aggregates (Polygon-parity grammar). Pure I/O (no DB writes, no buffering, no business logic) — buffering + persistence live in `worker/ws_tick_buffer.py` + `worker/ws_db_writer.py`. The long-lived consumer process is `worker/massive_ws_consumer.py`. Replaces the old per-ticker REST polling: massive.com's `A.*` feed delivers ~1 frame/sec/ticker during the 04:00-20:00 ET window (pre-market + RTH + after-hours).
- `lake.py` — Parquet reader for the market-warehouse data lake. Backend is either the local mirror (`~/market-warehouse/data-lake/`) or Cloudflare R2 (`market-data/market-warehouse/data-lake/`) — selection is config-driven via `lake_resolver.resolve_lake_root(settings, asset_class=...)`. Resolver prefers R2 (the canonical archive per the 2026-05-25 rule) **unless the local mirror is strictly ahead of R2's canary symbol**, in which case it falls back to local with a WARN log — defense added 2026-06-07 after a 16-day silent stall when the external producer→R2 push died. Pure I/O, no business logic.
- `lake_resolver.py` — `LakeRoot` dataclass + `resolve_lake_root()` config-to-root mapping with freshness override. R2 → S3 protocol via `pyarrow.fs.S3FileSystem` with the account-scoped endpoint override. Canary symbol per asset class: `VIX` (volatility) / `SPY` (equity); add an entry to `_ASSET_CLASS_CANARY` for any new asset class.

## Gold complex (Phase A1 + v2 corpus)

Feeds the `/gold` GOLD COMPASS cockpit (`web/app/gold/`, `api/routers/gold.py`). The three-lens model (structural-flow / cyclical / valuation overlay) is documented in [`docs/research/gold-sdf-framework/`](../../../docs/research/gold-sdf-framework/) — read its CLAUDE.md before touching gold ingestion.

| Source file | What it pulls | Status |
|---|---|---|
| `fred.py` | FRED CSV provider for daily + monthly macro series (reference pattern for the other A1 sources). Persists to `macro_series_daily`. | Live |
| `gpr.py` | Caldara-Iacoviello Geopolitical Risk Index (GPRD) from matteoiacoviello.com. Publisher switched daily file from CSV → `.xls` (BIFF8) in 2024 — the old `/gpr_files/gpr_daily_recent.csv` path 404s. | Live |
| `lbma.py` | LBMA monthly loco-London vault holdings. LBMA moved from a stable .csv URL to monthly-named .xlsx at `cdn.lbma.org.uk/downloads/LBMA-London-Vault-Holdings-Data-<Month-Year>.xlsx` — we scrape the listing page each run to discover the current URL. Gold column is in thousand troy oz; we multiply by 1000 to keep `vault_oz` in oz (consistent with COMEX). | Live |
| `comex.py` | COMEX daily gold-stocks scraper from `cmegroup.com/markets/metals/precious/gold-stocks.html`. URL is subject to CME publishing changes — sanity-check before deploy. | Live |
| `etf_holdings.py` | Per-fund daily holdings for GLD (SPDR), IAU (BlackRock), GLDM (SPDR), PHYS (Sprott). Each fund has its own endpoint and payload shape; normalised to `EtfHoldingRow`. | Live |
| `uw_gold_options.py` | Gold-options snapshot for GLD/GDX/IAU. Composes existing UW fetchers (`interpolated_iv`, `oi_per_strike`, `option_contracts`, `skew`) into one snapshot row per (ticker, obs_date). | Live (A1 persists; A2 will consume) |
| `cftc_cot.py` | CFTC Commitments of Traders disaggregated weekly report (commodity code `088691`). Managed-money + commercials longs/shorts/net, OI. `obs_date` = Tuesday position date, `release_date` = Friday publication. **Backtests must lag to release+3 trading days, never to obs_date.** | Live |
| `wgc_etf.py` | World Gold Council monthly gold-ETF holdings workbook (Goldhub `Gold_ETF_flows_*.xlsx`). Per-fund holdings, demand, fund-flow with source-workbook lineage preserved. See `migrations/046_wgc_etf_monthly.sql` and `docs/research/gold-sdf-framework/12-wgc-etf-flow-corpus.md`. | Live (PR #42) |
| `wgc_cb.py` | World Gold Council monthly central-bank gold reserves. | **Deferred** — WGC retired the anonymous CSV; downloads now sit behind a Goldhub login (verified 2026-05-17). Structural-lens CB tiles stay null and `cb_gold_reserves_monthly` stays empty until re-wired. See `docs/research/gold-sdf-framework/11-deferred-sources-phase-a1.md`. |

Related migrations: `storage/migrations/041_gold_cot.sql` (COT), `046_wgc_etf_monthly.sql` (WGC ETF corpus). Repository: `storage/gold_etf.py`. Scheduler jobs: `worker/jobs/gold_jobs.py` (`gold_fred_ingest_job`, `gold_gpr_ingest_job`, `gold_lbma_vault_ingest_job`, `gold_comex_vault_ingest_job`, `gold_etf_holdings_ingest_job`, `gold_spot_ingest_job`, `gold_uw_options_ingest_job`, `gold_cftc_cot_ingest_job`, `gold_wgc_cb_ingest_job`, `gold_posture_compute_job`).

## US rates

Feeds `/rates` through `worker/jobs/rates_jobs.py` and
`storage/migrations/052_rates_tables.sql` / `053_rates_policy_sources.sql`.

| Source file | What it pulls | Status |
|---|---|---|
| `fred.py` | FRED observations for nominal Treasury curve, TIPS real yields, breakevens, EFFR, SOFR, target range, and Fed plumbing. Requires `FRED_API_KEY`. | Live |
| `cleveland_fed.py` | Cleveland Fed inflation-expectations model CSVs for the four-component 10Y decomposition. | Live |
| `fomc_calendar.py` | Federal Reserve FOMC calendar page for meeting metadata. | Live |
| `fed_funds_futures_path.py` | Frenzy Capital Fed Watch SSR data, a free/delayed fed-funds-futures move-probability source used as an alternative to the paid CME FedWatch API. Override with `RATES_POLICY_PATH_URL` if we later host our own scraped/derived page. | Live |
| `cftc_tff.py` | CFTC Traders in Financial Futures futures-only API (`gpe5-46if`) for U.S. Treasury futures positioning by dealer/intermediary, asset manager, leveraged funds, and other reportables. | Live |
| `treasury_supply.py` | TreasuryDirect auction results plus FiscalData debt-to-the-penny for the rates Supply panel. | Live |

## Rules

- **Audit-first.** Persist the raw payload + audit row BEFORE returning. Crashes mid-pipeline must still leave a trace.
- **Raise `NormalizationError`** on malformed payloads. Never silently skip rows — the scanner depends on knowing if UW changed shape.
- **One fetcher per endpoint.** No generic "call this slug" helper — explicit functions surface signature drift at import time.
- **Massive can be absent.** If `MASSIVE_API_KEY` is missing the worker uses `_NoOhlc` (null object). Don't crash the scheduler on a missing key.
- **No retry logic here.** Backoff/retry lives in `api/client.py` (UW) — sources stay thin.
- **Never add a Yahoo Finance source.** Project-wide rule — yfinance is for radon/other projects, not this one.
- **Telemetry hook.** Gold sources accept a `record_request` callable that emits `ExternalApiRequestEvent` rows via `ExternalApiRequestRecorder` (production wiring) — keep it injectable for tests.
- **Backtest lag rule for COT.** Always lag inputs to CFTC `release_date + 3 trading days`. Using `obs_date` (Tuesday position date) leaks look-ahead because the report is published Friday.
