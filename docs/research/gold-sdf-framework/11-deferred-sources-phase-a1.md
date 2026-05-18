# 11 — Deferred Sources from Phase A1 Ingestion

**Status:** Living document. Captures every Phase A1 source whose anonymous-CSV ingestion path failed during the 2026-05-17 warmup, with the concrete re-wire path so the second-round development pass can pick them up without re-discovering the failure modes.

**Scope:** Only sources that the design called for but Phase A1 could not deliver. Sources that worked (FRED, GPR, LBMA, GLD spot via massive OHLC, UW options snapshots) live in [09-data-sources-catalog.md](./09-data-sources-catalog.md).

**Why this file exists:** Five sources moved or paywalled between the design pass (April 2026) and the implementation pass (May 2026). Each was documented inline in the source file as a deferral, but operational and research context belongs here so the v2 plan can sequence them by effort × signal value rather than rediscovering each failure mode.

**2026-05-18 live-state update:** this file is now paired with [14-data-quality-remediation.md](./14-data-quality-remediation.md), which records the current local DB state. GLD daily holdings, the WGC monthly ETF corpus, WGC canonicalization, COT current-row + 400-day history ingestion, freshness missing-source status, effective-market-date targeting, and replay invalidation have landed. CB reserves and COMEX remain unresolved.

---

## D1 — WGC Central Bank reserves (monthly)

**Designed for:** Lens 1 structural — `cb_strategic_12m_sum_t`, `cb_tactical_12m_sum_t`, `cb_diversifier_12m_sum_t`, `cb_52w_pct`.

**Designed source:** World Gold Council Goldhub CSV at `https://www.gold.org/...` (anonymous).

**Phase A1 status:** **Anonymous endpoint retired 2026-05-17.** WGC moved Goldhub behind login. The fetcher in `src/uw_scan/sources/wgc_cb.py` is intact but the ingest job is a documented no-op (`gold_wgc_cb_ingest_job` logs an info line and returns).

**Re-wire options (sorted by effort):**

1. **IMF IFS direct** — central-bank gold reserves are reported through IMF International Financial Statistics. API endpoint at `https://data.imf.org/ifs` with an instant-issue key. Drops WGC's strategic/tactical/diversifier bucket classification (WGC bucket label is editorial); need to re-derive buckets or maintain a static mapping (~30 countries cover 95% of reported reserves).
2. **World Bank Open Data** — `https://data.worldbank.org/indicator/FI.RES.XGLD.OZ` returns annual not monthly. Useful for cross-validation only.
3. **Goldhub authenticated download** — register, store credentials in `.env`, change `wgc_cb.py` to send the session cookie. Lowest delta to existing code but adds a credential dependency.

**Signal value:** **High.** CB reserves are the largest non-ETF physical sink and the dominant single factor in the post-2022 regime break thesis (see [03-post-2022-regime-break.md](./03-post-2022-regime-break.md) and Codex finding #1). The Lens 1 chart loses its anchor without it.

**Recommended for v2:** IMF IFS direct. Avoids the auth-credential tax and keeps the source open-data.

**2026-05-18 verification:** `cb_gold_reserves_monthly` is still empty in the local warm store, and a live probe against the old WGC CSV returns 404. This is unresolved and remains the second highest-priority source after COT.

---

## D2 — ETF holdings (GLD / IAU / GLDM / PHYS)

**2026-05-17 partial re-wire:** UW `/api/etfs/{ticker}/in-outflow` is accessible for GLD/IAU/GLDM under the current entitlement window (~30 trading days) and can populate `gld_30d_net_flow_t`. UW `/api/etfs/GLD/holdings` returns `data: []` and `GLD/info` reports `holdings_count: 0`, so it does **not** provide absolute bullion ounces/tonnes.

**2026-05-17 GLD holdings re-wire:** SPDR's current archive endpoint is `https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en`. It returns `US_GLD_Archive_EN.xlsx` with daily `Total Ounces of Gold in the Trust`, `Tonnes of Gold`, NAV/share, premium/discount, and GLD close back to inception. This now populates `gld_holdings_t` and the Lens 1 holdings-vs-price chart on warmup/daily scheduled ingest. GLD daily holdings are therefore no longer a deferred source.

**2026-05-17 WGC Goldhub monthly re-wire:** The WGC ETF-flows page (`https://www.gold.org/goldhub/research/etf-flows`) exposes monthly `ETF_Flows_*.xlsx` downloads. Anonymous `curl` returns 403, but an authenticated Goldhub browser session can download the workbook. The workbook's monthly sheets contain ETF holdings, demand, and fund flows back to 2003. The code path now supports either `WGC_GOLDHUB_COOKIE` for scheduled authenticated downloads or `WGC_ETF_FLOWS_WORKBOOK_PATH` for a local exported workbook/directory. Local authenticated scrape loaded 78 workbooks into `wgc_etf_monthly`: 1,338,260 raw revision-preserving rows, 234 tickers, 2003-03-31 through 2026-03-31. See [12-wgc-etf-flow-corpus.md](./12-wgc-etf-flow-corpus.md). This is a monthly safety net and breadth corpus; downstream consumers must canonicalize to the latest revision per `(ticker, obs_date)` before computing factors.

**Designed for:** Lens 1 structural — `gld_holdings_t`, `gld_30d_net_flow_t`, plus the dual-axis Lens 1 chart showing oz-held vs price.

**Designed source:** Each fund manager's published holdings page (anonymous JSON / CSV).

**Phase A1 status:** **All four endpoints returned 301/404 during the 2026-05-17 warmup.**

| Ticker | Issuer | Old endpoint | Failure mode |
|---|---|---|---|
| GLD | SPDR | `…/spdrs/etf/gld/holdings.json` | 301 → `/usa/gld/` (HTML, not JSON) |
| IAU | iShares | `…/blackrock/.ajax?…` | 404 (BlackRock retired the .ajax route) |
| GLDM | SPDR | same SPDR pattern as GLD | 301 |
| PHYS | Sprott | `…/sprott/api/…` | 404 (Sprott changed API path) |

**Re-wire options:**

1. **SPDR historical archive API for GLD** — current path is `api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en`; daily XLSX archive, suitable for startup backfill and once-daily refresh. Landed for GLD on 2026-05-17.
2. **WGC Goldhub ETF-flows workbook** — authenticated monthly XLSX with GLD/IAU/GLDM/PHYS holdings in tonnes and fund-flow panels. Landed as an authenticated/export-backed parser on 2026-05-17.
3. **ETF.com / ETFDB scraping** — third-party aggregators publish daily holdings tables. Adds a dependency on a third party who can also rotate URLs.
4. **Bloomberg / Refinitiv** — paid feed, deterministic. Not justified for one factor.
5. **SEC N-PORT filings** — every '40-Act ETF files holdings monthly via N-PORT. The XML is parseable and the schedule is fixed. Lower granularity (monthly not daily) but the most durable.

**Signal value:** **Medium-high.** ETF flows are the easiest-to-observe component of the structural posture. 30d net flow is one of the inputs the dashboard surfaces most prominently; the v1 Lens 1 dual-axis chart is half-functional without GLD holdings.

**Recommended for v2:** Keep SPDR archive as canonical GLD absolute-holdings source. Use WGC Goldhub monthly files for IAU/PHYS/GLDM and global breadth while authenticated access is available; add a canonical WGC view/query before promoting WGC breadth to production fields; keep SEC N-PORT as the open-data fallback if Goldhub session ops become brittle.

---

## D3 — COMEX vault inventory

**Designed for:** Lens 1 structural — `comex_registered_oz`, `comex_20d_roc_pct`.

**Designed source:** CME Group's daily Issues & Stops report (anonymous CSV).

**Phase A1 status:** **CME returns 403 to anonymous scrapers as of 2026-05-17.** Bumping the timeout to 60s and adding a browser UA did not help. The fetcher in `src/uw_scan/sources/comex.py` is intact and logs a warning when the 403 lands.

**2026-05-18 verification:** `exchange_inventory_daily` has LBMA rows but no COMEX rows. A live probe against the CME page still returns 403. Until calibration proves COMEX is material, do not let this optional source keep Lens 1 permanently degraded.

**Re-wire options:**

1. **CME DataMine license** — paid, deterministic, supports historical replay. Justified if COMEX-stress is going to be a backtested factor. Adds operational cost.
2. **Bullion-vault Twitter accounts / blog scrapers** — third-party aggregators republish COMEX daily numbers ~6h after CME publishes. Brittle and dependent on a single human curator.
3. **Wayback Machine** — historical CME pages are cached and accessible. Useful for backfill but not for live.
4. **Headless browser** — Playwright against the CME page. Probably works because the 403 is a UA + JS-challenge wall, not a paywall. Operationally heavier than every other source in the pipeline.

**Signal value:** **Medium.** COMEX registered-oz ROC is a contributory structural signal but not load-bearing — Lens 1 still works if it's None (other factors carry the lens). Worth wiring before going to production but not blocking.

**Recommended for v2:** Playwright fallback inside the existing scrape path. If signal calibration shows it adds <2% to the structural-posture R², drop it entirely.

---

## D4 — CFTC Commitments of Traders (weekly)

**Designed for:** Lens 1 structural — `cot_mm_net_pct`, `cot_mm_4w_change_sigma` (managed-money net positioning + 4-week change z-score).

**Designed source:** `https://www.cftc.gov/dea/newcot/deacot.txt` or equivalent disaggregated commodities report.

**Phase A1 status:** **Originally pointed at the wrong file.** The Phase A1 fetcher in `src/uw_scan/sources/cftc_cot.py` referenced `FinFutWk.txt` — that's the **financial** futures weekly report, not the commodities report. So even when the fetch succeeded, it pulled rates / equities / FX positioning, not gold.

**2026-05-18 remediation:** the provider now reads the official CFTC disaggregated futures-only commodity feed at `/dea/newcot/f_disagg.txt` for the current row and the CFTC Public Reporting Environment Socrata dataset `72hh-3qpy` for history, filters gold contract market code `088691`, and the local store has 57 distinct observations from 2025-04-15 through 2026-05-12. The latest posture row writes both `cot_mm_net_pct` and `cot_mm_4w_change_sigma`.

**Re-wire options:**

1. **`com_disagg_xls_<YYYY>.zip`** — the CFTC's disaggregated commodities weekly Excel zip. Stable URL pattern, contains gold (commodity code 088691). Switch the URL and the parser to read `.xls` from the zip.
2. **Socrata API at `publicreporting.cftc.gov`** — official JSON API, supports query parameters, deterministic. Slightly more code than the zip approach but cleaner.
3. **Quandl / Nasdaq Data Link mirror** — paid, deterministic, but the CFTC publishes the original for free.

**Signal value:** **High.** Codex finding #8 explicitly called this out as the largest single factor class missing from the original design. F18/F19/F20 in `04a-quant-model-spec.md` all consume COT MM net + 4w change. The Lens 1 posture currently degrades without it because the four-way composite is missing one corner.

**Recommended remaining work:** keep the Public Reporting Environment path as the canonical backfill path; use the annual disaggregated futures-only zip files as an offline fallback.

---

## D5 — XAU spot (London PM fix)

**Designed for:** KPI strip — `spot.last` was supposed to be XAU/USD in $/oz, not GLD ETF in $/share.

**Phase A1 status:** **Substituted GLD daily close from massive OHLC** because:
- FRED's `GOLDAMGBD228NLBM` (LBMA PM fix) returns 404 since 2026 — series was retired.
- LBMA's own auction-results endpoint requires an account.
- The current KPI tile is labelled `GLD ETF · USD` not `XAU / USD` to avoid lying — GLD is ~$417 while XAU is ~$3,600 and the magnitude mismatch was the first issue surfaced during visual review.

**Re-wire options:**

1. **massive OHLC for `XAU=`** — check whether the massive feed includes the spot synthetic. If yes, drop-in replacement at the orchestrator level.
2. **LBMA registered downloads** — same auth story as WGC. Adds a credential but the data is canonical.
3. **GLD / 0.0931** — GLD holds ~1/10 of an oz per share (the GLD trust ratio drifts slowly). Derive XAU from GLD close × inverse trust ratio. Lossy (drift from trust expenses) but adequate for a KPI tile if labelled honestly.
4. **OANDA / fxcm forex feeds** — anonymous XAU/USD tickers, ~15-min cadence. Not LBMA-fix-precise but adequate for the KPI.

**Signal value:** **Display-only.** No downstream factor depends on raw XAU — GLD close is what feeds the correlation gauge, valuation overlay, and price chart. This is purely a label-honesty question for the KPI tile.

**Recommended for v2:** Try massive feed first (cheapest if it works), otherwise leave GLD as the spot tile with the honest label.

---

## Cross-cutting observations from Phase A1

1. **Anonymous CSV endpoints have a ~12-month half-life.** Of the 8 sources designed for anonymous access in `09-data-sources-catalog.md`, five (D1–D5 above) failed within 18 months of the catalog being written. GPR and LBMA survived but only because we found new endpoints during ingestion (publisher changes: GPR moved csv → xls, LBMA went from direct download to monthly-scrape-the-listing-page).
2. **Three categorical re-wire paths:**
   - **Auth credential** (WGC, LBMA, COMEX paid) — lowest delta to design intent but adds credential ops.
   - **Alternative publisher** (IMF for CB reserves, SEC N-PORT for ETF, Socrata for CFTC) — preserves anonymous-open-data principle but changes the schema slightly.
   - **Derive from what we have** (XAU from GLD) — zero new operations, lossy.
3. **The orchestrator design held up.** Every deferred source has a `None`-tolerating field in the schema and the API model; the page renders em-dashes instead of crashing. v2 can re-wire each source independently without touching the cockpit code.
4. **Operational cost vs signal value:** D4 (CFTC COT, Socrata API) is the highest signal-to-effort ratio — official JSON, well-documented, biggest single factor in the design. Should be first in the v2 sequence. D1 (CB reserves via IMF IFS) is second. D2 (ETF holdings via SPDR re-scrape) third. D3 (COMEX) and D5 (XAU spot) are non-blocking and can come after model calibration shows whether they materially move the needle.

---

## Sequencing recommendation for v2

| Order | Source | Path | Why this rank |
|---|---|---|---|
| Closed | D4 — CFTC COT | Socrata API at publicreporting.cftc.gov, commodity code 088691 | Landed with 400-day backfill and 4-week metric persistence |
| 1 | D1 — WGC CB reserves | IMF IFS API | Largest remaining unweighted contributor to Lens 1 structural posture; one credential, no scraping |
| 3 | D2 — ETF holdings/WGC canonicalization | SPDR daily GLD already landed; add canonical WGC monthly view + SEC N-PORT fallback | The raw WGC corpus is loaded but revision-heavy; production factors need canonical rows |
| 4 | D5 — XAU spot | massive `XAU=` if available, else keep GLD labelled honestly | Display-only; not blocking model work |
| 5 | D3 — COMEX | Playwright + UA spoof, or drop entirely | Only re-wire if calibration shows it moves R² >2% |
| 6 | D2 — ETF holdings (IAU/GLDM/PHYS) | SEC N-PORT monthly | Diminishing return after GLD |

This sequence keeps the **most-deferred** factors (CB reserves, COT) in front of the **most-deferred-by-choice** ones (COMEX, non-GLD ETFs), and lands all five fixes in roughly the time budget originally estimated for the corresponding chunks of `09-data-sources-catalog.md`.

---

## Document hygiene

- This file is **append-only** during the v2 development pass — each deferred source either gets a "✅ Re-wired in PR #N (YYYY-MM-DD)" line at the top of its section or stays here.
- When a source is re-wired, **move the entry** to [09-data-sources-catalog.md](./09-data-sources-catalog.md) under the appropriate cost class and **leave a one-line stub** here pointing at the new home. Don't delete history — the re-discovery cost (5 failures in 18 months) is itself the lesson.
- Cite source URLs at the time of writing, not at the time of reading. Every URL in this document was verified accessible on 2026-05-17. If you're reading this on a later date and an URL 404s, that's a new deferred source — add a new entry rather than editing the historical record.
