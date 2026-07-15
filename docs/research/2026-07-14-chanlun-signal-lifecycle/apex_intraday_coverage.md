# Apex intraday bar coverage — feasibility check for Chanlun v2 (Phase B)

Read-only research note. Sources: apex repo code + CLAUDE.md, livewire repo code + CLAUDE.md/CHANGELOG,
and a direct DuckDB-less inspection of this MacBook's local `~/market-warehouse` bronze mirror.

## 1. Does apex's bars API support intraday intervals?

Yes, at the route level. `GET /bars/{ticker}?timeframe=` (`/Users/chenxi/projects/apex/src/api/routes/chart.py:69-91`)
accepts a `timeframe` query param validated against
`SUPPORTED_TIMEFRAMES = ("1m", "5m", "30m", "1h", "1d")`
(`/Users/chenxi/projects/apex/src/infrastructure/adapters/livewire/paths.py:17`). So 30m and 1h are both
legal values today — no route change needed. There is no static OpenAPI YAML/JSON in the repo; the contract
is the FastAPI route + Pydantic-free dict payload in `src/api/payload/chart.py` (validated on egress against
`config/verification/schemas/` per the route docstring), not a separate spec file.

## 2. Underlying data source and real historical depth

Apex does **not** own the data — `GET /bars` is compute-on-read against `LivewireOhlcProvider`
(`/Users/chenxi/projects/apex/src/infrastructure/adapters/livewire/ohlc_provider.py:73-152`), which runs
DuckDB directly over the livewire bronze Parquet lake (local filesystem, `APEX_LIVEWIRE_ROOT`) at
`bronze/asset_class=equity/symbol=<ticker>/{1m,5m,30m,1h,1d}.parquet`. Apex CLAUDE.md confirms: "Historical
bars come from the livewire bronze lake — a local-filesystem Parquet tree read on demand via DuckDB."

In livewire, equity intraday is sourced from **Massive's whole-market SIP minute flat files**, not IB:
"`MassiveFlatfileClient` is the only equity-intraday provider path... not used for equity intraday" refers
to `MassiveClient` (REST, daily-only); the intraday-specific client downloads S3 SIP minute aggregates
(`/Users/chenxi/projects/livewire/CLAUDE.md:95-96`, `:324-343`). Canonical granularity is `1m`; `5m`/`30m`/`1h`
are derived locally by lossless OHLCV aggregation, once, from the complete `1m` history
(`docs/plans/2026-06-06-massive-flatfile-full-market-design.md:162-177`).

**Retention model**: NOT a UW-style rolling window. The `flatfile-ingest backfill` job "discovers the actual
entitled range" by probing backward month-by-month against Massive's S3 objects until it hits
`not_entitled_or_before_history`, then publishes each ticker's "complete entitled `1m` history" once
(design doc §"Available-History Discovery" and §"Bronze Publish Stage"). Forward accrual is then
`daily-backfill`/`flatfile-ingest catch-up`, default 7-day lookback (`MDW_DAILY_BACKFILL_INTRADAY_DAYS`).
So *by design* it should behave like an accrue-forward-from-max-entitled-history model, not a shrinking
window — but I could not pin down Massive's actual entitled minute-bar lookback in years from the docs read
(not stated as a fixed number; discovered dynamically per symbol).

**Gap — cannot confirm this has actually run to completion.** This whole pipeline (`flatfile-ingest`,
whole-market discovery, 5m/30m/1h derivation) is still filed under `## [Unreleased]` in
`/Users/chenxi/projects/livewire/CHANGELOG.md:8-20` as of the last entry I read (after `[0.2.1] - 2026-06-03`).
Direct inspection of this MacBook's local bronze mirror (`~/market-warehouse/data-lake/bronze/asset_class=equity/`)
found:
- `30m.parquet`: 0 tickers
- `1m.parquet`: 0 tickers
- `5m.parquet`: 3 tickers (AAPL, TSLA, SPY)
- `1h.parquet`: 17 tickers (AAPL, TSLA, SPY + 14 others, no clear watchlist pattern)
- `1d.parquet`: 653 tickers (looks like the normal daily universe)

File mtimes on AAPL's `1h.parquet`/`5m.parquet` are **7 Apr 2026** — before the flatfile-ingest pipeline's
own commits (`e03c5b1 refactor: replace equity intraday with flat files`, `5cf40a6 test: validate full-market
flat-file pipeline`, both after the 6 Jun 2026 design doc). These look like leftover files from an earlier,
now-replaced IB/REST-based intraday test path, not output of the current pipeline. **I could not verify
from local files whether the full-universe historical `flatfile-ingest backfill` has ever actually been run
to completion** (on the mini, or synced to R2). This local Mac mirror is explicitly a secondary copy per
argon's own conventions (R2 is primary; local mirror can be stale) — so absence of data here is not proof
of absence upstream, but it is also not evidence of presence. Someone with mini/R2 access needs to run
`flatfile-ingest discover`/inspect the mini's bronze tree or R2 bucket directly to get a real answer.

## 3. Universe scope

By design, universe-wide, not watchlist-scoped. `flatfile-ingest` "operates on every symbol in each selected
whole-market file; ticker and preset filters are unsupported" (`/Users/chenxi/projects/livewire/CLAUDE.md:342-343`).
So once/if the backfill runs, mega-caps are covered automatically along with the rest of the SIP universe —
there's no separate step needed to add specific tickers.

## 4. Nearby alternative sources if apex/livewire intraday is insufficient

- **livewire IS the source apex already reads** — not a separate fallback, it's the same pipeline described
  above. R2 is livewire's canonical published store (local `~/market-warehouse` is a mirror that can lag);
  per argon's own CLAUDE.md/memory, new backtest/backfill code should prefer R2 reads over the local mirror.
- `market-data-warehouse` is listed in `~/projects/CLAUDE.md` as a separate "Supporting Project," but livewire's
  own CLAUDE.md says it was "Rebranded 2026-05-17 from 'market-data-warehouse'" — same repo, same on-disk tree
  (`~/market-warehouse/`). The root `~/projects/CLAUDE.md` listing both `livewire/` and `market-data-warehouse/`
  as distinct projects looks like stale documentation, not two live systems (unverified — did not check whether
  a separate `market-data-warehouse` directory still exists with independent content).
  Note: I did not find a `market-data-warehouse` sibling directory during this check, only `livewire/`.
- **xenon direct IB** is explicitly NOT used for equity intraday history in livewire ("not used for equity
  intraday" applies to IB too — livewire's IB path is reserved for daily bars, non-equity intraday, and
  volatility indices). IB direct pull would be a genuinely separate build, not something already wired up.

## Bottom line

The API contract and derivation logic for 30m/1h bars exist end-to-end (apex route → livewire bronze →
Massive SIP minute flat files, universe-wide, accrue-forward from max entitled history). What is **not
verified** is whether the historical backfill has actually populated 1-2 years of 30m/1h bars for mega-caps
anywhere in the stack today — local evidence points the other way (near-empty local mirror with stale
pre-pipeline files), but the local mirror is not authoritative. Recommend checking the mini's bronze tree or
R2 bucket directly, or running `flatfile-ingest discover`, before committing to Phase B's data assumption.

---

## 2026-07-14 follow-up — verified against the Mac mini's local bronze tree (R2 not checked, per correction)

Read-only investigation. Scope note: the coordinator corrected this pass mid-run — **R2/S3 is retired**;
argon's CLAUDE.md line "R2 lake is primary for EOD/backfill reads" is stale documentation and was
explicitly *not* exercised here. The Mac mini's local filesystem is the sole source of truth checked in
this pass. No writes, no code changes; this is purely inspection.

### Access path

- `~/.ssh/config` on this MacBook has a working alias: `Host macmini` → `100.66.147.98`, `User moremeds`
  (Tailscale hostname `macmini.tail20094b.ts.net` also defined). `ssh -o BatchMode=yes macmini echo ok`
  succeeded — key-based auth is already set up, no credentials were guessed.
- Confirmed the mini's bronze root: `/Users/moremeds/market-warehouse/data-lake/bronze/asset_class=equity/`
  — **13,109** `symbol=<TICKER>` directories present (`ls | wc -l`), i.e. universe-wide, not watchlist-scoped,
  consistent with the flatfile-ingest design doc's claim.
- System Python on the mini has no `pyarrow`. Found it in `livewire`'s own project venv:
  `/Users/moremeds/projects/livewire/.venv/bin/python3` → `pyarrow==24.0.0`. Used that interpreter over SSH
  (heredoc, no files copied off the mini) to read Parquet metadata + `bar_timestamp` min/max only — never
  dumped full file contents.

### Per-ticker results (AAPL, NVDA, SPY — 30m and 1h)

Schema for all six files: `['bar_timestamp', 'symbol_id', 'open', 'high', 'low', 'close', 'volume']`.

| Ticker | Timeframe | Exists | Row count | min(bar_timestamp) | max(bar_timestamp) | Span (days) |
|---|---|---|---|---|---|---|
| AAPL | 30m | Y | 32,878 | 2021-06-11 08:00:00+00:00 | 2026-07-10 23:30:00+00:00 | 1,855 |
| AAPL | 1h  | Y | 17,995 | 2021-05-21 14:00:00+00:00 | 2026-07-10 23:00:00+00:00 | 1,876 |
| NVDA | 30m | Y | 32,818 | 2021-06-11 08:00:00+00:00 | 2026-07-10 23:30:00+00:00 | 1,855 |
| NVDA | 1h  | Y | 17,926 | 2021-06-04 14:00:00+00:00 | 2026-07-10 23:00:00+00:00 | 1,862 |
| SPY  | 30m | Y | 32,900 | 2021-06-11 08:00:00+00:00 | 2026-07-10 23:30:00+00:00 | 1,855 |
| SPY  | 1h  | Y | 16,463 | 2021-06-11 08:00:00+00:00 | 2026-07-10 23:00:00+00:00 | 1,855 |

All numbers above are read directly from the mini's live Parquet files via `pyarrow.parquet.ParquetFile`
metadata (`num_rows`) and `pyarrow.compute.min/max` over the `bar_timestamp` column — nothing estimated or
inferred. Storage tier: **mini-local** (`/Users/moremeds/market-warehouse/data-lake/bronze/...`); R2 was not
queried in this pass per the correction above, so R2's state (in sync, ahead, behind, or unused) is still
unverified.

Directory listing (`ls -la`) also showed `1d.parquet`, `1m.parquet`, and `5m.parquet` present for all three
tickers with plausible non-trivial sizes (e.g. AAPL `1m.parquet` = 14.1 MB), and `*.meta.json` sidecar files
per timeframe — consistent with the flatfile-ingest pipeline having actually run and accrued forward,
contrary to this note's §2 finding from the MacBook's stale local mirror.

### Revised bottom line

The prior finding — "could not verify whether the historical backfill has actually populated 1-2 years of
30m/1h bars for mega-caps anywhere in the stack" — is now **resolved for the mini-local tier**: it has. AAPL,
NVDA, and SPY each carry ~5.1 years of continuous 30m and 1h bars (2021-05/06 → 2026-07-10, 4 calendar days
behind today's 2026-07-14, consistent with forward-only daily accrual rather than a live feed), across a
13,109-symbol universe-wide tree. This MacBook's local `~/market-warehouse` mirror (near-empty, pre-pipeline
files per §2 above) is confirmed stale/divergent from the mini's tree and should not be used as a proxy for
data availability — any Phase B work should read from the mini (directly, or via whatever the mini-hosted
apex/argon services already point at) rather than this MacBook's local mirror. R2's status remains
unverified and out of scope for this pass — a future check should confirm whether R2 is in fact retired
(per the coordinator's correction) or still holds an independent, possibly divergent copy, since argon's
own `lake_resolver.py` code still contains live R2-vs-local comparison logic (`_probe_max_trade_date`,
"local mirror ahead of R2" warning) that would only make sense if R2 were still a live target somewhere in
the stack.
