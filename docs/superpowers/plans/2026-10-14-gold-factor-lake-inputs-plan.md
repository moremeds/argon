# Gold factor reads its price legs from the lake — plan

Status: BUILT, 2026-10-15. Part 1 shipped in livewire PR #173 (89961068), accepted by argon1 on
2026-10-14 (lake 1d equals argon's stored IB inputs on every common date). Part 2 is branch
`feat/gold-factor-lake-inputs`. Deviations from the text below: the lake root is the existing
`MARKET_WAREHOUSE_LAKE` (`/lake` in the containers) plus `bronze/asset_class={cmdty,fx_ib}`, so no new
setting or resolver entry; the session calendar is `worker/market_session.is_us_equity_market_day`.
Contract as delivered: `bronze/asset_class=fx_ib/symbol=<PAIR>/1d.parquet` and
`bronze/asset_class=cmdty/symbol=XAUUSD/1d.parquet`, columns `trade_date` date32 + `close` double,
written ~17:20 New York by launchd `com.livewire.ib-evening` (05:20/06:20 HKT; the earlier one is a
no-op in winter).

## Goal

`gold_factor_compute` (argon, 17:40 ET Sun–Thu) stops calling xenon for prices. It reads XAUUSD and the
six DXY legs (EURUSD, USDJPY, GBPUSD, USDCAD, USDSEK, USDCHF) from the livewire lake, and persists only its
results (`gold_factor_daily`, `dxy_synthetic_daily`). This follows the 2026-10-13 direction: argon reads the
lake and stores results, not raw market data. Every input must update automatically, and a missed update
must show up as a job failure, not as a quietly stale page.

## Why

- Today argon fetches 7 IB daily midpoint series from xenon every night (`worker/jobs/gold_factor.py::fetch_ib_legs`)
  and writes them into `macro_series_daily` with `source='IB'`. That is raw data in argon, and it ties the job to
  xenon uptime: prod `job_failures` shows `gold_factor_compute` failed 10-13 (ReadTimeout on all 7 legs, xenon
  outage) and has `last_success_at` NULL.
- On 2026-10-14 10:20 ET all 7 xenon legs answered in ~1 s, so this is not urgent breakage. It is a dependency
  argon should not own.

## Ground truth (checked on the mini, 2026-10-14 ~10:30 ET, read-only)

Lake root on the mini: `/Volumes/DATA_LAKE/livewire/data-lake` (mounted read-only in argon containers at `/lake`).

| Series | Lake file | Lake source | Matches xenon IB midpoint? |
|---|---|---|---|
| XAUUSD | `bronze/asset_class=cmdty/symbol=XAUUSD/1d.parquet`, 2016-05-24 → 2026-10-13, written 14 Oct 13:02 HKT (01:02 ET) | `meta.json` says `source: ib` | **Yes, exactly** (10-08..10-13 identical to xenon) |
| 6 FX legs | `bronze/asset_class=fx/symbol=<PAIR>/1d.parquet` (also 1m/5m/30m/1h), from 1996–2003, written ~01:0x ET | no `meta.json`; unknown | **No** |

FX 1d, lake vs xenon IB midpoint (xenon = 17:00 New York close; 10-14 xenon is a live partial bar):

| Date | EURUSD lake / IB | GBPUSD lake / IB | USDSEK lake / IB |
|---|---|---|---|
| 10-10 (Sat) | — / — | — / — | 9.99400 / none |
| 10-11 (Sun) | 1.120473 / none | 1.324152 / none | 9.99675 / none |
| 10-12 | 1.116022 / 1.11555 | 1.320980 / 1.3208 | 10.03645 / 10.04025 |
| 10-13 | 1.117443 / 1.11985 | 1.321615 / 1.3255 | 10.02201 / 9.9647 |

So the lake FX 1d is a different vendor or a different day boundary: it has weekend rows, already had a
10-14 row at 01:00 ET, has float32 precision, and differs by up to 0.6% (USDSEK 10-13). The lake
`symbol=DXY` files (timestamps like 04:57:22, volume 0) are not a substitute for argon's synthetic DXY either.

Other readers of the lake FX 1d: argon `fundamental_run` / `fundamental_refresh` (FX conversion for foreign
filers, via `Settings.lake_fx_root` = `/lake/bronze/asset_class=fx`, verified in the prod container). Their
meaning must not change.

## Part 1 — livewire (owner: livewire1)

1. **IB FX daily lane.** IB IDEALPRO, `whatToShow=MIDPOINT`, 1-day bars, the same bar convention as the
   XAUUSD lane (bar dated D = 17:15 NY D-1 → 17:00 NY D). Six pairs listed above.
2. **Where it lands.** Must be distinguishable from the existing FX 1d, because that file has other readers.
   livewire1 decides (e.g. a source-tagged partition or a separate symbol/file) and reports the path.
3. **History depth.** Back to at least 2016-05-24 (the XAUUSD lane start), so argon can recompute its whole
   stored history from lake inputs. IB serves long FX midpoint history; the existing argon seed used chunked
   requests because one call of 17 Y or more outruns IB.
4. **Schedule.** The bar for D exists only after 17:00 NY on D. If the lane runs at ~01:00 ET like today, argon
   at 17:40 ET reads D-1 every night. Decision for livewire1: run the XAUUSD + FX daily update after ~17:15 ET
   (and say when it is reliably done), or keep 01:00 ET and argon moves its job after that.
5. **Freshness.** The lane's own health/monitoring must flag a missed day (whatever livewire already uses).
6. **Questions to answer in the report:** source of the existing FX 1d/intraday files; whether an existing IB FX
   intraday lane already exists (then the daily could be a resample, but MIDPOINT vs TRADES and the 17:00 NY
   boundary must match); the exact path, schema, and update time of the new files.

Livewire1 reports a **data contract**: path, schema (columns, dtypes, date column), source tag, bar convention,
history start, update time. Argon work starts only after that.

## Part 2 — argon (owner: argon1, after the contract)

1. `storage/gold_factor.py::fetch_inputs` gets the 7 price legs from the lake (in memory) and DFII10/DGS10 from
   `macro_series_daily` as now. Add a `cmdty` root (and the new FX root if livewire puts it elsewhere) to
   `config/lake.py::LAKE_ROOT_FALLBACK` + `sources/lake_resolver.py`.
2. `worker/jobs/gold_factor.py`: delete `fetch_ib_legs` / `_fetch_leg` and the xenon arguments; the job no longer
   writes raw prices. Existing `source='IB'` rows in `macro_series_daily` stay (no deletion); they stop growing.
3. Staleness guard: if any leg's last lake date is older than the last completed session, the job fails with a
   clear message, so `job_failures` and `/api/health` show it.
4. Schedule moves to after livewire's update time (from step 1.4).
4b. Completed bars only. Today xenon returns the bar that is still forming, and argon stores it. Prod
   `macro_series_daily` XAUUSD shows: obs 10-13 stored at 06:26 ET 10-13 = 4181.67 (final 4161.51), and obs 10-14
   stored at 23:53 ET 10-13 = 4163.14. So the latest factor/DXY row is computed from a partial day.
   `dxy_synthetic_daily` already has obs 10-14 (computed 10-13 23:53 ET). The lake XAUUSD file has no partial
   row (at 10:20 ET 10-14 its last row was the final 10-13), and the reader must keep that rule for every leg:
   use only bars dated on or before the last completed 17:00 NY close.
5. Add `gold_factor_daily` and `dxy_synthetic_daily` to `reports/data_freshness.py::MONITORED_TABLES`
   (both are in the gap-healer registry only; the 10-12/10-13 factor gap from the xenon outage was invisible
   to the freshness block).
6. CHANGELOG via script; tests use a frozen real-value lake fixture with its as-of date.

## Acceptance

- Livewire: new FX files exist on the mini, cover 2016-05-24 → latest session, and match xenon's IB midpoints
  for a 5-day spot check (same check as the table above, expect equality like XAUUSD).
- Argon: recompute `gold_factor_daily` and `dxy_synthetic_daily` from lake inputs (read-only, in the prod
  container) and diff against the stored prod rows. Expected near-zero diff, since both sides are IB 17:00 NY
  midpoints. A real diff means the lane convention is wrong — stop.
- After deploy: two consecutive scheduled runs succeed on prod, with no xenon call in the logs, and
  `job_failures.gold_factor_compute.consecutive = 0`.
- Out of scope: the IV canary keeps using xenon (it validates IB IV against UW by design); the Gold Gate
  rewrite (`macro/gold_state.py`); SGE premium.
