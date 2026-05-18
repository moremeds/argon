# 09 — Data Sources Catalog

Consolidated reference for every data series the three-layer architecture relies on. Each entry includes the canonical source, cost, update cadence, lag, ingestion path, and which factors/layers consume it.

---

## Cost summary

| Cost class | Sources |
|---|---|
| **Free, no auth** | FRED CSV endpoint, GPR daily, LBMA monthly, SPDR GLD historical archive, CFTC COT reports via the official commodity dataset, BIS FX series |
| **Free, requires instant-issue key** | FRED JSON API |
| **Already paid in this repo** | UW (options on GLD/GDX/IAU), massive.com (OHLC for GLD/GDX/IAU/SPX/futures) |
| **Free but requires alternate/open-data re-wire** | IMF IFS for central-bank reserves, SEC N-PORT for non-GLD ETF fallback |
| **Free but Chinese-language scraping** | Shanghai Gold Exchange (deferred to v2) |
| **Free but currently blocked by scrape/access path** | CME COMEX vault reports |
| **Free but Goldhub-authenticated/export-backed** | WGC ETF monthly workbook corpus |
| **Discontinued** | LBMA GOFO (discontinued 2015; use COMEX/LBMA/SGE proxies instead) |
| **Paid** | None required |

**Total new external data cost for v1: $0.**

---

## Layer 1 — Structural-flow sources

### Per-country central bank reserves

| Field | Value |
|---|---|
| **Series** | Quarterly per-country gold reserves (tonnes), used to derive 12m bucket net changes |
| **Source** | WGC Goldhub authenticated workbook, sourced from IMF IFS plus WGC adjustments |
| **URL** | https://www.gold.org/goldhub/data/gold-reserves-by-country |
| **Format** | XLSX: `Quarterly_gold_and_FX_Reserves_Q1_2026.xlsx`; old anonymous CSV path returns 404 |
| **Cost** | Free |
| **Auth** | Goldhub session cookie or manually exported local workbook |
| **Cadence** | Quarterly |
| **Lag** | ~1 month after quarter-end |
| **Coverage** | Local warm store: 27 mapped bucket countries from Q1 2000 through Q1 2026 |
| **Caveats** | Russia stopped reporting late 2022; China reports infrequently and is widely believed to under-report (industry estimates 2-3× reported figures) |
| **Consumed by** | Layer 1 / structural posture |

**Current implementation status (2026-05-18):** wired and locally populated from
the authenticated WGC Goldhub workbook. `cb_gold_reserves_monthly` contains
2,827 rows for 27 mapped bucket countries from 2000-03-31 through 2026-03-31.
`gold_wgc_cb_ingest_job` accepts `WGC_CB_RESERVES_WORKBOOK_PATH` or
`WGC_GOLDHUB_COOKIE`. See [14-data-quality-remediation.md](./14-data-quality-remediation.md)
G3.

### ETF holdings

| ETF | Sponsor | Series | URL | Cadence | Lag |
|---|---|---|---|---|---|
| **GLD** (SPDR Gold Shares) | State Street | Daily holdings (tonnes), NAV, shares outstanding | https://www.spdrgoldshares.com/usa/historical-data/ | Daily | T+0 (end of day) |
| **IAU** (iShares Gold Trust) | BlackRock | Daily holdings | iShares.com investor relations | Daily | T+0 |
| **GLDM** (SPDR Gold MiniShares) | State Street | Daily holdings | spdrgoldshares.com | Daily | T+0 |
| **PHYS** (Sprott Physical Gold) | Sprott | Daily NAV, premium/discount | sprott.com | Daily | T+0 |
| **Aggregate** | WGC | Monthly cross-fund holdings, demand, flow | gold.org/goldhub | Monthly | T+~5 days |

GLD daily holdings are wired through the SPDR historical archive API. WGC ETF
monthly files are authenticated/export-backed and revision-preserving; use a
canonical latest-revision view before computing factors. Non-GLD daily issuer
paths should be treated as deferred until SEC N-PORT or new issuer APIs are
wired. Consumed by Layer 1 / ETF flow regime gauge.

### COMEX vault stocks

| Field | Value |
|---|---|
| **Series** | Daily gold vault stocks: registered + eligible (oz) |
| **Source** | CME Group daily metals depository report |
| **URL** | https://www.cmegroup.com/markets/metals/precious/gold-stocks.html |
| **Format** | HTML/JSON, but the current anonymous scrape is blocked |
| **Cost** | Free |
| **Auth** | none documented, but current scrape returns 403 |
| **Cadence** | Daily, end of NY business |
| **Lag** | T+0 |
| **Consumed by** | Layer 1 / inventory regime quadrant |

**Current implementation status (2026-05-18):** unresolved. `COMEX` has zero
rows in `exchange_inventory_daily`; decide whether to wire Playwright/licensed
access or drop COMEX from the required Lens 1 gate after calibration.

### LBMA loco London

| Field | Value |
|---|---|
| **Series** | Monthly precious metals vault stocks (loco London, tonnes) |
| **Source** | LBMA monthly vault report |
| **URL** | https://www.lbma.org.uk/prices-and-data/vault-holdings-data |
| **Format** | CSV / XLSX |
| **Cost** | Free |
| **Auth** | None |
| **Cadence** | Monthly |
| **Lag** | ~1 month |
| **Consumed by** | Layer 1 / inventory regime quadrant |

### CFTC Commitment of Traders (COT) — gold futures positioning

| Field | Value |
|---|---|
| **Series** | Weekly position breakdown for gold futures (GC), legacy + disaggregated reports |
| **Source** | CFTC public reports |
| **URL** | https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm + API/export at https://www.cftc.gov/es/node/128971 |
| **Format** | CSV (historical) / API (current) |
| **Cost** | Free |
| **Auth** | None |
| **Cadence** | Weekly (Friday release of Tuesday data) |
| **Lag** | ~3 trading days (data is Tuesday's positions; published Friday afternoon) |
| **Coverage** | Long history (1986+ for legacy; 2006+ for disaggregated) |
| **Caveats** | Categories are coarse (managed-money / commercial / non-reportable); crowded spec longs can be trend-following rather than contrarian; release delay must be modeled |
| **Consumed by** | Lens 1 / F18 (managed-money net percentile), F19 (commercials net percentile), F20 (managed-money 4-week change) |

This is the **single largest factor-class omission** flagged by the Codex review. Adding COT is high-priority for the data-quality remediation pass.

**Current implementation status (2026-05-18):** unresolved. The existing provider
points at the financial futures report and returns zero gold rows. Re-wire to
Socrata or the commodity disaggregated zip before using this field.

### UW options stress (GLD / GDX / IAU)

| Field | Value |
|---|---|
| **Series** | Options chain snapshots, IV by strike/expiry, dealer-gamma proxies, large-trade flow events |
| **Source** | UW endpoints (already integrated for other tickers in this repo) |
| **Format** | UW JSON; already in the existing UW client |
| **Cost** | Already paid in this repo |
| **Auth** | UW_SCAN_API_KEY |
| **Cadence** | Daily snapshots |
| **Lag** | T+0 |
| **Persistence policy** | **Persist from v1 even if not used as model input** — backtest history accumulates from day one, model promotion in v2 then has data to work with |
| **Consumed by** | v1: surfaced as a dashboard "options stress" panel under Lens 1. v2: F21 (GLD 25Δ put-call IV spread) as model input. Future: dealer-gamma / large-trade-flow as additional features. |

### Gold lease rate / GOFO

| Field | Value |
|---|---|
| **Status** | **GOFO (Gold Forward Offered Rate) was discontinued by LBMA in January 2015.** Direct GOFO is not available as a current daily feed. |
| **Source for the concept** | https://www.lbma.org.uk/articles/discontinuation-of-gofo-wef-30-january-2015 |
| **Proxies for v1** | COMEX/LBMA inventory dynamics (already in scope); futures basis/backwardation if `massive.com` supports gold-futures-curve data; SGE Shanghai-London premium when SGE scraping is added |
| **Decision** | Do **not** include a "GOFO factor" in v1 (the data does not exist). Add a v2 research item to construct lease-rate proxies from the available substitutes above. |

### Shanghai Gold Exchange (deferred v2)

| Field | Value |
|---|---|
| **Series** | Physical OTC delivery, daily inventory |
| **Source** | SGE Chinese-language website |
| **Format** | Chinese-language HTML; requires scraping or paid Wind/Bloomberg feed |
| **Cost** | Free, scraping cost |
| **Decision** | Defer to v2; partially captured by per-country CB reserves and XAU/CNY |

### Local-currency gold FX series

| Series | Source | URL | Notes |
|---|---|---|---|
| CNY/USD | FRED `DEXCHUS` | fred.stlouisfed.org | Daily, free, no auth |
| INR/USD | FRED `DEXINUS` | fred.stlouisfed.org | Daily, free |
| JPY/USD | FRED `DEXJPUS` | fred.stlouisfed.org | Daily, free |
| TRY/USD | BIS or TCMB | bis.org / tcmb.gov.tr | Not in FRED; small additional fetch |

XAU/local computed in-app: `(USD gold price) / (USD per local-currency unit)`.

---

## Layer 2 — Cyclical sources

### FRED macro series (all free)

| FRED ID | Series description | Daily/Monthly | Used by |
|---|---|---|---|
| `DFII10` | 10-Year Treasury Inflation-Indexed Security | Daily | Two-force, regime gauge, F10 input |
| `DGS10` | 10-Year nominal Treasury | Daily | F10 cross-check, decomposition |
| `T10YIE` | 10-Year Breakeven Inflation | Daily | F4 |
| `T5YIFR` | 5y5y Forward Inflation Expectation | Daily | Regime classifier (anchoring) |
| `CPIAUCSL` | CPI All Urban Consumers, SA | Monthly | Regime classifier (level) |
| `DTWEXBGS` | Trade-Weighted Dollar Index: Broad | Daily | F1, F11 |
| `BAMLH0A0HYM2` | HY OAS (option-adjusted spread) | Daily | Two-force / hedge-demand |
| `VIXCLS` | CBOE Volatility Index | Daily | Two-force / hedge-demand |
| `GVZCLS` | CBOE Gold ETF Volatility Index | Daily | F6, F14 |
| `M2SL` | M2 Money Supply | Weekly | Layer 3 / gold-M2 ratio |
| `CBBTCUSD` | Coinbase Bitcoin price | Daily | Four-asset board (BTC leg) |
| `DEXCHUS` | China / US FX | Daily | XAU/CNY |
| `DEXINUS` | India / US FX | Daily | XAU/INR |
| `DEXJPUS` | Japan / US FX | Daily | XAU/JPY |

**FRED endpoint options:**
- **CSV (recommended for daily worker):** `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>` — no auth, no key, no rate limit issue for daily polling
- **JSON API:** `https://api.stlouisfed.org/fred/` — requires free API key (instant issue), 120 req/min default rate limit, more metadata (revisions, release dates)

Recommendation: CSV for v1 worker, JSON only if we need point-in-time / vintage data for backtesting.

### Geopolitical Risk Index (Caldara-Iacoviello)

| Field | Value |
|---|---|
| **Series** | GPRD (daily) and GPR (monthly) geopolitical risk indices |
| **Source** | Caldara & Iacoviello (Fed economists), authoritative academic series |
| **URL** | https://www.matteoiacoviello.com/gpr.htm |
| **Format** | CSV download |
| **Cost** | Free |
| **Auth** | None |
| **Cadence** | Daily (GPRD), monthly (GPR) |
| **Lag** | ~1 day (GPRD), ~1 month (GPR) |
| **Coverage** | Daily from 1985; historical (GPRH) from 1900 |
| **Citation** | Caldara & Iacoviello (2022), *American Economic Review* 112(4), 1194-1225 |
| **Consumed by** | F5 (Layer 2) |

### Gold and miners OHLC

| Symbol | Description | Source | Status |
|---|---|---|---|
| **GLD** | SPDR Gold Shares ETF | massive.com | Already wired |
| **GDX** | VanEck Gold Miners ETF | massive.com | Already wired |
| **IAU** | iShares Gold Trust | massive.com | Already wired (alternative) |
| **GC=F** | COMEX gold futures front month | massive.com (if supported) | Verify; alternative for purer spot signal |

Consumed by F13 (Gold-GDX Divergence), gold price reference for Layer 3 valuation overlay.

### UW options data on the gold complex (cross-reference)

| Underlying | Series | Source | Status |
|---|---|---|---|
| GLD, GDX, IAU | Options chain, dealer gamma, vol skew, large trades | UW endpoint | Already wired; **v1 persistence required even before model use** |

Full details under Lens 1 (above): UW options data is persisted to Postgres from v1 to accumulate backtest history. v2 promotes the 25Δ put-call IV spread to F21 in the cyclical / structural feature set. Also see [10-open-research-questions.md](./10-open-research-questions.md) Q9.

---

## Layer 3 — Valuation overlay sources

### Real price of gold (primary anchor)

| Component | Source |
|---|---|
| USD gold price | LBMA AM Fix (preferred academic) or massive.com GLD (substitute) |
| Deflator | FRED `CPIAUCSL`, indexed to base year |
| Pre-1971 historical context | Officer & Williamson "The Price of Gold, 1257-Present" — free academic series, hand-curated; only needed for long-horizon percentile baseline |

### Gold / M2 ratio (alternative anchor)

| Component | Source |
|---|---|
| USD gold price | as above |
| M2 money supply | FRED `M2SL` |

### Gold / SPX ratio (alternative anchor)

| Component | Source |
|---|---|
| USD gold price | as above |
| SPX level | massive.com `^SPX` or SPY ETF |

---

## Regime gauge inputs

| Input | Source | Cadence |
|---|---|---|
| Gold daily return | massive.com GLD or LBMA fix | Daily |
| DFII10 daily change | FRED | Daily |
| 252-day rolling Pearson correlation | Computed in-app | Daily |

---

## Ingestion cost summary

| New source module | LOC estimate | New tables in `uw_scan` schema |
|---|---|---|
| FRED client (CSV-based) | ~150-250 | `macro_series_daily`, `macro_series_monthly` |
| GPR CSV ingestor | ~80-120 | reuses `macro_series_daily` |
| ETF holdings (4 funds, similar pattern) | ~200-300 | `etf_holdings_daily` |
| COMEX vault (parser) | ~100-150 | `exchange_inventory_daily` |
| LBMA vault (CSV) | ~50-80 | reuses `exchange_inventory_daily` (monthly partition) |
| WGC CB reserves (CSV) | ~80-120 | `cb_gold_reserves_monthly` |
| FX series (extend FRED client) | ~30-50 | reuses `macro_series_daily` |
| TRY FX (BIS or TCMB) | ~50-80 | reuses `macro_series_daily` |
| **CFTC COT ingestor** | **~120-180** | **`cot_gold_weekly`** |
| **UW options snapshots persistence (gold complex)** | **~80-120** | **`uw_gold_options_daily`** |
| **Total Lens 1 + 2 v1 plumbing** | **~950-1450 LOC** | **6-7 new tables** |

Plus repository methods (one per query, per existing repo convention), API router (one new file under `src/uw_scan/api/routers/gold.py`), worker job (extend `scheduler.py`).

Engineering estimate: **6-10 days** for the data plumbing, **2-3 days** for the regime classifier + position-sizing logic, **1 day** for API surface. **~10-15 days total for the v1 endpoint** before any dashboard work.

---

## Data quality and reliability notes

### Most reliable (use without hesitation)

FRED macro series, SPDR GLD historical archive, LBMA vault reports, Caldara-Iacoviello GPR. All are published by institutions with strong reputational stakes and have working ingestion paths in the current stack.

### Caveat-required

- **WGC/IMF CB reserves**: currently not populated. Once re-wired, Russia post-2022 estimated and China under-reports. Surface tooltips when these countries are highlighted.
- **CFTC COT**: current weekly gold row is populated from the official disaggregated futures-only commodity feed; historical backfill is still needed before 4-week-change metrics are reliable. Release lag must be modeled.
- **COMEX vault**: currently not populated because CME returns 403 to the current scrape. Treat as optional until calibrated.
- **WGC ETF monthly corpus**: raw table preserves workbook revisions; consumers must use a canonical latest-revision view.
- **PHYS NAV**: Sprott reports daily but premium/discount calculation has occasional methodology updates.
- **TRY FX**: Turkish lira has had unconventional intervention episodes; FX rates from TCMB occasionally diverge from market rates during stress periods.

### Lag-sensitive

- **CPIAUCSL**: ~2-week publication lag; if the regime classifier triggers based on CPI, ensure backtests use point-in-time CPI vintages (FRED ALFRED) not current-revised values. See [10-open-research-questions.md](./10-open-research-questions.md) Q11.
- **WGC CB reserves**: 1-month lag; structural-posture statements should clearly date-stamp the data window.
- **CFTC COT**: weekly cadence with ~3-trading-day publication delay (Tuesday positions, Friday release). Backtests must lag COT inputs to actual release date, not observation date.
- **LBMA vault**: ~1-month lag for monthly snapshots.
- **Non-synchronous close**: FRED daily series, GLD close, futures settlement, ETF holdings disclosures, and UW options snapshots do not share a single clock. The backtest harness must record an as-of timestamp per input and consume only observations with as-of strictly earlier than the decision time. See [04a-quant-model-spec.md](./04a-quant-model-spec.md) "Mandatory features" section.

---

## Source verification status

All URLs cited in this catalog were checked accessible during the cross-validation work (2026-05-16). Sources that returned 403 in automated checks but are known-good for browser access: FRED CSV/JSON APIs (automated WebFetch can be flaky against fred.stlouisfed.org; the actual endpoints work with standard HTTP clients).
