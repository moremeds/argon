# 14 — Gold Data Quality Remediation

Date: 2026-05-18 HKG

## Purpose

This note is the systematic closure plan for the live data issues observed after
Phase A1. It reconciles the research docs with the current local warm-store
state and separates confirmed gaps, root causes, user-visible impact, exact
resolution order, and verification gates.

## Current Warm-Store Snapshot

Observed from the configured local Postgres store on 2026-05-18 HKG.

| Dataset | Current state | Latest observation | Issue |
|---|---:|---|---|
| `macro_series_daily` | 18,681 rows | GLD_CLOSE 2026-05-15; DFII10 2026-05-14; GPRD 2026-05-11 | Mixed clocks; latest posture can be computed on a non-trading date |
| `macro_series_monthly` | 182 rows | CPIAUCSL 2026-04-01; M2SL 2026-03-01 | Expected monthly lag |
| `etf_holdings_daily` | 1,073 rows | GLD 2026-05-14 | GLD daily path works; non-GLD daily paths are WGC monthly only |
| `etf_flows_daily` | 93 rows | GLD/IAU/GLDM 2026-05-15 | UW entitlement window only, about 30 trading days |
| `wgc_etf_monthly` | 1,338,260 rows | 2026-03-31 | Historical workbook revisions create many rows per fund-month |
| `exchange_inventory_daily` | 36 rows | LBMA 2026-04-01 | COMEX has zero rows |
| `cot_gold_weekly` | 57 distinct obs dates | 2026-05-12 | Current + 400-day CFTC gold history populated from official CFTC sources |
| `cb_gold_reserves_monthly` | 2,827 rows | 2026-03-31 | WGC/IFS quarterly workbook, 27 mapped bucket countries |
| `uw_gold_options_daily` | 12 rows | 2026-05-17 | Snapshot-only; dealer gamma null |
| `gold_posture_daily` | 15 rows | active latest 2026-05-15 | Bad/non-market and pre-CB rows invalidated and retained for audit |

Post-remediation latest active posture row: `obs_date=2026-05-15`,
`gauge_state=partial`, `row_status=active`, `cot_mm_4w_change_sigma=0.1988`.
Data freshness now includes explicit `status` for missing sources, and after the
WGC CB load and level-sum invalidation the local posture store has `active=2`,
`invalidated=13` rows.

## Implementation Status

As of the 2026-05-18 remediation pass:

| Issue | Status | Code / data outcome |
|---|---|---|
| G1 non-trading posture | Closed for scheduled jobs | `gold_posture_compute_job()` defaults to latest `GLD_CLOSE`; non-market posture rows after latest GLD close are invalidated |
| G2 COT empty/history incomplete | Closed | Provider reads CFTC current disaggregated futures-only `f_disagg.txt`; 400-day history reads official CFTC Public Reporting Environment dataset `72hh-3qpy`, filters gold contract `088691`, and local `cot_gold_weekly` has 57 distinct observations |
| G3 CB reserves empty | Closed | WGC Goldhub authenticated quarterly workbook parser and ingest path wired; local `cb_gold_reserves_monthly` has 2,827 rows for 27 mapped bucket countries |
| G4 COMEX empty | Open / decision needed | CME anonymous scrape remains 403; calibrate before paying scrape/licensed-data cost |
| G5 freshness hides missing | Partially closed | Freshness rows now include `status=ok/missing`; obs-date/cadence details are still a follow-up |
| G6 WGC canonicalization | Closed | `wgc_etf_monthly_canonical` view reduces GLD from 16,362 raw rows to 257 canonical months |
| G7 bad replay rows | Closed | `row_status` / `superseded_reason` added; normal state/replay skip invalidated rows |
| G8 UW options semantics | Open | History accumulation continues; dealer gamma source/deriver still unidentified |

## Issues And Resolution Plan

### G1 — Latest posture can be a non-trading-day composite

**Evidence:** latest `gold_posture_daily.obs_date` was 2026-05-17, a Sunday,
while source observations ended on different prior business dates.

**Impact:** the page looks current but mixes GLD 2026-05-15, DFII10 2026-05-14,
GPRD 2026-05-11, DXY 2026-05-08, and monthly CPI/M2.

**Resolution:**

1. Determine `effective_obs_date` as the latest date for which required daily
   market sources have closed, not blindly `date.today()`.
2. Persist both `obs_date` and `computed_at`; show source observation dates in
   freshness.
3. Only compute weekend/holiday posture if explicitly requested for replay.

**Verification:** latest `/api/gold/state.obs_date` should be the latest valid
market date, and the data-audit footer should show each source's `obs_date` or
`obs_month`, not only ingest `as_of`.

### G2 — COT current row was empty and history was not backfilled

**Original evidence:** `cot_gold_weekly` had zero rows. A live provider probe
returned zero rows for the last 400 days.

**Root cause:** `src/uw_scan/sources/cftc_cot.py` pointed at `FinFutWk.txt`,
the financial futures report, not the disaggregated commodities gold report.

**Resolution:**

1. Use the official CFTC disaggregated futures-only commodity feed
   (`/dea/newcot/f_disagg.txt`) for current-row fallback and filter gold
   contract market code `088691`.
2. Use the official CFTC Public Reporting Environment Socrata dataset
   `72hh-3qpy` for 400-day history.
3. Preserve the existing `CotRow` shape.
4. Persist Tuesday observation date and Friday release date; all posture/backtest
   consumption must use release date.
5. Compute and persist `cot_mm_net_pct` and `cot_mm_4w_change_sigma`.

**Verification:** `cot_gold_weekly` has 57 distinct gold observations from
2025-04-15 through 2026-05-12; parser fixtures reject non-gold contracts; latest
`gold_posture_daily` writes `cot_mm_net_pct=0.246` and
`cot_mm_4w_change_sigma=0.1988`.

### G3 — Central-bank reserves were empty

**Evidence:** `cb_gold_reserves_monthly` had zero rows. A live probe against the
old WGC CSV returned HTTP 404.

**Root cause:** WGC retired the anonymous central-bank CSV path. The replacement
Goldhub files are authenticated XLSX downloads.

**Resolution:**

1. Wire `src/uw_scan/sources/wgc_cb.py` to parse the authenticated WGC
   quarterly reserves workbook.
2. Let `gold_wgc_cb_ingest_job` read `WGC_CB_RESERVES_WORKBOOK_PATH` for local
   exports or `WGC_GOLDHUB_COOKIE` for authenticated downloads.
3. Populate `cb_gold_reserves_monthly` with WGC/IFS country-level reserve
   levels, mapped to the existing bucket taxonomy.
4. Fix structural posture to compute 12m bucket net changes from reserve levels
   instead of summing repeated level observations.

**Verification:** local `cb_gold_reserves_monthly` now has 2,827 rows for 27
mapped bucket countries from 2000-03-31 through 2026-03-31. Latest posture for
2026-05-15 writes `cb_strategic_12m_sum_t=-79.3125`,
`cb_tactical_12m_sum_t=48.4098`, `cb_diversifier_12m_sum_t=116.3423`, and
bad level-sum replay rows are invalidated by migration 048.

**Operator note — do not rediscover this source:** WGC's
`gold-demand-by-country` page is useful for aggregate demand/supply and consumer
country demand, but it is not the CB holdings source. The holdings source is:

- Page: `https://www.gold.org/goldhub/data/gold-reserves-by-country`
- Workbook: `Quarterly_gold_and_FX_Reserves_Q1_2026.xlsx`
- Sheet consumed: `Gold (Tonnes)`
- Local table: `uw_scan.cb_gold_reserves_monthly`

Fast health check:

```bash
set -a; source /Users/chenxi/projects/unusual-whales/.env; set +a
uv run python scripts/gold_cb_reserves_status.py
uv run python scripts/gold_cb_reserves_status.py --country CHN
```

Equivalent SQL:

```sql
SELECT count(*) AS rows,
       count(DISTINCT country_iso3) AS countries,
       min(obs_month) AS first_month,
       max(obs_month) AS latest_month
FROM uw_scan.cb_gold_reserves_monthly;

SELECT country_iso3, count(*) AS rows, min(obs_month), max(obs_month)
FROM uw_scan.cb_gold_reserves_monthly
GROUP BY country_iso3
ORDER BY country_iso3;
```

Refresh options:

1. Manual export path: download the latest WGC quarterly workbook from the
   logged-in Goldhub page, then run the ingest with
   `WGC_CB_RESERVES_WORKBOOK_PATH=/path/to/Quarterly_gold_and_FX_Reserves_*.xlsx`.
2. Scheduled authenticated path: set `WGC_GOLDHUB_COOKIE` in the worker
   environment. `gold_wgc_cb_ingest_job` will discover the latest quarterly XLSX
   link from the Goldhub page and ingest it.
3. Warmup/backfill path: `gold_warmup.py` passes `lookback_days=None` for this
   source, so a local workbook refresh reloads the full quarterly history rather
   than just the latest 400-day posture window.

### G4 — COMEX is empty

**Evidence:** no `COMEX` rows exist in `exchange_inventory_daily`; a live probe
against CME returned HTTP 403.

**Root cause:** the CME page blocks the current anonymous `httpx` scrape.

**Resolution:**

1. First run a Lens 1 calibration with COMEX omitted.
2. If COMEX improves explanatory fit materially, add a Playwright scrape or
   licensed CME/DataMine path.
3. If it does not, remove COMEX from the required Lens 1 data gate and keep it
   as an optional stress overlay.

**Verification:** either `comex_registered_oz` populates reliably, or
`structural_posture_chip` no longer degrades solely because COMEX is absent.

### G5 — Freshness hides missing sources and source staleness

**Evidence:** latest `data_freshness_jsonb` lists only FRED, GPR, and ETF. COMEX,
COT, and WGC are absent rather than explicitly reported missing. Freshness uses
ingest `as_of`, not latest source observation date.

**Resolution:** store freshness rows for every expected source:

- `id`
- `status`: `ready`, `missing`, `deferred`, `stale`
- latest `obs_date` or `obs_month`
- latest `as_of`
- expected cadence
- lag seconds/days against cadence
- source-specific note

**Verification:** the latest state should include explicit COMEX/COT/WGC rows
even while they are unresolved.

**2026-05-18 implementation note:** `data_freshness_jsonb` now includes every
expected source with `status=ok` or `status=missing`; source observation-date
and cadence-aware lag fields are still pending.

### G6 — WGC ETF corpus preserves revisions but consumers need canonical rows

**Evidence:** `wgc_etf_monthly` has 1,338,260 rows. Core GLD has 16,362 rows for
257 distinct months across 78 source workbooks; some months have 76 GLD rows.

**Root cause:** the table intentionally keys by `(ticker, obs_date, source_url)`
to preserve workbook revisions. That is correct for lineage, but consumers must
use a canonical latest-revision view per `(ticker, obs_date)`.

**Resolution:**

1. Keep raw revision-preserving storage.
2. Add a repository query or SQL view for canonical WGC monthly rows: latest
   revision per `(ticker, obs_date)` by `as_of` / source label date.
3. Build global/regional ETF breadth metrics only from the canonical view.
4. Document row counts in both raw and canonical terms.

**Verification:** the canonical GLD month count is 257, not 16,362; downstream
research uses canonical counts.

**2026-05-18 implementation note:** migration `046_wgc_etf_monthly.sql` now
creates `uw_scan.wgc_etf_monthly_canonical`, and repository reads use that view.

### G7 — Replay preserves early bad posture rows

**Evidence:** `gold_posture_daily` has 9 rows for 2026-05-17. Early rows have
`gld_history_jsonb` values around `30,644,793.74` ounces; later rows correctly
show tonnes around `953.16`. `fetch_gold_posture_for_obs_date()` returns the
first row by design.

**Resolution:**

1. Add a `status` or `superseded_reason` field for posture rows, or a side-table
   recording invalidated `(obs_date, computed_at)` rows.
2. Make normal replay return the first non-invalidated row.
3. Keep an audit/debug mode that can still fetch invalidated rows.
4. Backfill-invalidate the bad 2026-05-17 GLD-unit rows.

**Verification:** replay for 2026-05-17 returns the first corrected row, while
audit mode can still inspect the original bad rows.

**2026-05-18 implementation note:** migration `047_gold_posture_row_status.sql`
adds `row_status` and `superseded_reason`, invalidates known-bad GLD-history
rows, invalidates posture rows after the latest GLD close, and normal latest /
replay queries filter to `row_status='active'`.

### G8 — UW options is snapshot-only and dealer gamma is null

**Evidence:** `uw_gold_options_daily` has 12 rows, all on 2026-05-17. All
`dealer_gamma_est` values are null.

**Impact:** `uw_25d_skew_sigma` is really latest raw skew, not a sigma-calibrated
history metric.

**Resolution:**

1. Continue daily persistence to accumulate history.
2. Rename or relabel current field semantics if needed: raw 25-delta skew until
   enough history exists for sigma calibration.
3. Add dealer-gamma only after a reliable UW source/deriver is identified.

**Verification:** docs/UI do not call the field "sigma" unless it is actually
standardized against history.

## Execution Order

| Order | Workstream | Why |
|---:|---|---|
| 0 | Add source-status/freshness rows for missing/deferred sources | Done for ok/missing status; cadence details remain |
| 1 | CFTC COT via official commodity dataset | Done for current weekly row |
| 2 | IMF IFS central-bank reserves | Restores the structural anchor |
| 3 | WGC canonical ETF monthly view + global/regional breadth fields | Canonical view done; breadth fields remain |
| 4 | Posture replay invalidation for known-bad rows | Done |
| 5 | Effective market-date policy | Done for scheduled posture compute |
| 6 | UW options semantics/history accumulation | Avoids overclaiming current snapshot fields |
| 7 | COMEX decision: calibrate, then wire or drop | Avoids paying operational cost before signal value is proven |
| 8 | XAU spot upgrade | Display-only; keep GLD label honest until solved |

## Definition Of Done

The gold data-quality pass is complete when:

1. Latest posture is computed for a valid effective market date.
2. Freshness reports every expected source with ready/missing/deferred/stale
   status and source observation date.
3. COT and CB reserve fields are non-null in `/api/gold/state`.
4. WGC ETF consumers use a canonical latest-revision view.
5. Replay excludes invalidated bad rows by default.
6. Structural posture does not degrade solely because optional COMEX is absent.
7. UW options labels match the actual amount of persisted history.

## Cross-References

- Deferred-source history: [11-deferred-sources-phase-a1.md](./11-deferred-sources-phase-a1.md)
- WGC raw corpus contract: [12-wgc-etf-flow-corpus.md](./12-wgc-etf-flow-corpus.md)
- WGC ETF factor research: [13-wgc-etf-flow-mining.md](./13-wgc-etf-flow-mining.md)
- Data-source catalog: [09-data-sources-catalog.md](./09-data-sources-catalog.md)
