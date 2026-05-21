# 09 — Massive.com fundamentals coverage audit

**Probed 2026-05-20 against `api.massive.com` with our existing `MASSIVE_API_KEY`.** Massive's REST surface is Polygon-shaped — the docs at `https://massive.com/docs/rest/stocks/...` reference an *llms.txt* index that lists endpoints by category, but the **actual API paths are Polygon-style** (`/v3/reference/tickers/...`, `/v2/reference/financials/...`). The docs-URL paths return 404; the Polygon-style paths return 200.

**Raw probe log:** doc 14 has the authoritative endpoint-by-endpoint record (status, latency, field lists, date ranges). This doc summarizes the coverage verdict and per-characteristic mapping.

## Bottom line

**Massive natively supplies 15 of the 17 firm-level characteristics in Goyal-Saretto Appendix A.5.** The two gaps (InstOwn, AnalystDisp) are the same two characteristics that rank lowest in importance in the paper's Table 5 (InstOwn ρ=0.06, p=0.14; AnalystDisp ρ=0.06, p=0.42). **No FMP integration needed** — massive replaces it entirely for this experiment.

## Endpoints confirmed working on our tier

| Endpoint | Returns | Why we need it |
|---|---|---|
| `GET /v2/reference/financials/{ticker}` | **103 raw Compustat-style fields per quarter**: `assets`, `debt`, `shareholdersEquity`, `marketCapitalization`, `freeCashFlow`, `issuanceEquityShares`, `issuanceDebtSecurities`, `revenues`, `grossProfit`, `cashAndEquivalents`, `weightedAverageShares`, `profitMargin`, `priceToBookValue`, `debtToEquityRatio`, `workingCapital`, `netIncome`, … | Everything in A.5 except InstOwn and AnalystDisp. **AAPL has 90 quarters back to 1997-09-30** — matches the paper's 1996-2022 sample period. |
| `GET /vX/reference/financials?ticker={t}` | Modern Polygon endpoint, structured under `financials.{balance_sheet (19 fields), income_statement (23 fields), cash_flow_statement (8 fields), comprehensive_income (5 fields)}` = **55 atomic financial fields** per row + 14 metadata keys (`filing_date`, `fiscal_period`, `source_filing_url`, etc.). Each leaf is `{value, unit, label, order}`. Quarterly / annual / **TTM** timeframes. | Complements `/v2` for post-2020 data — `/v2` is frozen ~2020-03-31, `/vX` continues. We need both for full-history backfill. **Authoritative field list in doc 14.** |
| `GET /stocks/v1/short-interest?ticker={t}` | Biweekly FINRA-reported short-interest settlements. 201 rows for AAPL, **2017-12-29 → 2026-04-30**. | Goyal-Saretto's RSI (A.5.5) — short-interest ratio. |
| `GET /v3/reference/tickers/{ticker}` | CIK, SIC, exchange, currency, active flag, company name. | Universe filtering — drop ADRs, restricted to CRSP share codes 10/11 equivalent. |
| `GET /v3/reference/tickers?limit=N` | Full ticker list (pageable). | Universe expansion beyond watchlist. |
| `GET /v3/reference/dividends?ticker={t}` | ex-div / record / pay dates + amounts + adjustment factors. | Apply the paper's "no underlying-stock dividend during holding period" filter. |
| `GET /v3/reference/splits?ticker={t}` | Execution date + ratio. | Adjust historical shares-outstanding when computing 1yr/5yr NewIss. |
| `GET /v2/reference/news?ticker={t}` | News with sentiment. | Optional — for any future news-impact signal. |
| `GET /v2/snapshot/locale/us/markets/stocks/tickers/{t}` | Current quote snapshot, today's change, day OHLC. | Live spot for stock-price column. |
| `GET /v1/marketstatus/now` | Market open/close state. | Calendar utility for monthly cross-section dates. |
| `GET /v1/marketstatus/upcoming` | Holiday calendar. | Same. |
| `GET /v1/related-companies/{ticker}` | Related-ticker graph from news / returns analysis. | Optional — sector / peer-set construction. |
| `GET /v3/reference/conditions` | Trade condition codes. | Not needed for this experiment but reference data. |

## Endpoints we couldn't access (probed all reasonable paths, all 404)

| Endpoint | Maps to paper | Status |
|---|---|---|
| 13-F filings | InstOwn (A.5.3) | Not accessible on current tier. Documented in massive's llms.txt as `/rest/stocks/filings/13-f-filings` but that path 404s; Polygon-style `/vX/reference/13-f` and 4 other guesses all 404. **Tier-gated or partner-only.** |
| Benzinga earnings / analyst-ratings | AnalystDisp (A.5.11) | Same. Docs list `/rest/partners/benzinga/earnings` and `/rest/partners/benzinga/analyst-ratings` but 5 guessed paths all 404. **Tier-gated partner data.** |

## Per-characteristic mapping (paper → massive)

| Paper var (A.5) | Computation from massive | Endpoint |
|---|---|---|
| BM | `shareholdersEquity / marketCapitalization` (or `1 / priceToBookValue` pre-computed) | `/v2/reference/financials` |
| Profitability | `grossProfit / assets` (or `profitMargin` pre-computed) | `/v2/reference/financials` |
| InstOwn | — | 🔴 **gap** |
| MarketCap | `marketCapitalization` | `/v2/reference/financials` |
| RSI | `short_interest / shares_outstanding` | `/stocks/v1/short-interest` + financials |
| Assets | `assets` | `/v2/reference/financials` |
| Debt | `debt` (incl. current + non-current) | `/v2/reference/financials` |
| Leverage | `debt / assets` (or `debtToEquityRatio` pre-computed) | `/v2/reference/financials` |
| CashFlowVar | rolling 60-month variance of `freeCashFlow / marketCapitalization` | `/v2/reference/financials` — **needs ≥60 months of history per ticker** |
| Cash to asset | `cashAndEquivalents / assets` | `/v2/reference/financials` |
| AnalystDisp | — | 🔴 **gap** |
| 1yr NewIss | `(weightedAverageShares_t / weightedAverageShares_{t-12mo}) - 1` | `/v2/reference/financials` + `/v3/reference/splits` for adjustment |
| 5yr NewIss | same, 60mo horizon | same |
| Profit margin | `profitMargin` (pre-computed) or `operatingIncome / revenues` | `/v2/reference/financials` |
| Stock price | log(close-of-month) | `/v2/aggs/...` (already have) |
| ROE | `netIncome / shareholdersEquity` | `/v2/reference/financials` |
| ExternalFin | `(issuanceEquityShares + issuanceDebtSecurities) / assets` | `/v2/reference/financials` |
| Z-score | Dichev (1998) composite: `1.2·WC/A + 1.4·RE/A + 3.3·EBIT/A + 0.6·MV/TL + Sales/A` — all components are in the 103 fields | `/v2/reference/financials` |

## History depth findings (confirmed by direct probe)

| Endpoint | Quarterly start | Quarterly end | Annual start | Annual end | Status |
|---|---|---|---|---|---|
| `/v2/reference/financials` AAPL | **1997-09-30** | **2020-03-31** | 1997-12-31 | 2019-12-31 | **Frozen ~2020-Q1** — legacy endpoint, no longer updated |
| `/vX/reference/financials` AAPL | **2009-06-27** | **2026-03-28** | 2009-09-26 | 2025-09-27 | **Current** — live updates, this is the production endpoint |

**Combined coverage: 1997 → present** with a 2009–2020 overlap zone for cross-validation.

This is the standard Polygon-clone pattern: a pre-computed-ratios endpoint (`/v2`) was frozen, and a raw-SEC-fields endpoint (`/vX`) became the going-forward standard. Both remain queryable; we use both.

**Per use case:**

- **Current-watchlist redundancy audit (Phase 1 of the 3-phase plan):** `/vX` alone is sufficient — covers 2009-present, watchlist is current names. No need to touch `/v2`.
- **Full Goyal-Saretto sample replication (1996.01–2022.12):** combine both — `/v2` for 1997-2008 (pre-vX), `/vX` for 2009-2022. Overlap zone validates field-name parity.
- **Forward-only research (2026+):** `/vX` only.

The smaller `/vX` count (55 atomic financial fields vs `/v2`'s 103 flat fields) is not a real loss: the "extra" ~50 fields on `/v2` were pre-computed ratios (`priceToBookValue`, `debtToEquityRatio`, `EBITDAMargin`, `returnOnAverageEquity`, etc.) that we compute ourselves in `cards/firm_characteristics.py` from the raw inputs that both endpoints expose. The `/vX` design is XBRL-shaped (every leaf has `{value, unit, label, order}`); the `/v2` design is flat-row Compustat-shaped. We persist the `/vX` shape in `fundamentals_quarterly`.

## Coverage breadth (small spot-check)

| Ticker | `/v2/reference/financials` records returned | Field count |
|---|---:|---:|
| AAPL | 90 quarterly + 23 annual | 103 |
| RBLX (newer, mid-cap) | ≥5 quarterly | 103 |

Need a fuller breadth check across the 103 watchlist tickers before any backfill — particularly for:
- Newer IPOs (history shorter than 60mo invalidates CashFlowVar)
- ADRs (the paper restricts to CRSP share codes 10/11)
- ETFs that may sneak into the watchlist (no fundamentals)

## Backfill economics

- Per-ticker, 1 call to `/v2/reference/financials` (limit=100) covers 25 years of quarterly data in one request.
- Per-ticker, 1 call to `/v3/reference/dividends` and 1 to `/v3/reference/splits` for adjustments.
- Per-ticker, ~3 calls to `/stocks/v1/short-interest` (limit=500) covers 8+ years of biweekly data.
- For the 103-ticker watchlist: ≈ **103 × 5 ≈ 515 requests** to backfill all firm-level + short-interest history. At massive's default rate limits (Polygon-shaped, generally 5 req/s on free → 100 req/min on basic), this completes in **5-20 minutes**.

## Implication for the 3-phase plan

**Replace "Phase 3 — FMP fundamentals" with "Phase 3 — Massive fundamentals."** Same module structure, no new API key needed, broader historical depth (1997 vs FMP's typical 2009-only-on-free-tier).

The new file layout:
- `src/uw_scan/sources/massive_fundamentals.py` — REST client for `/v2/reference/financials`, `/vX/reference/financials`, `/stocks/v1/short-interest`, `/v3/reference/dividends`, `/v3/reference/splits`. Sibling to existing `sources/ohlc.py` (same `MassiveOhlcProvider` Polygon-shaped pattern).
- `src/uw_scan/storage/fundamentals_repository.py` — new repository per [feedback_repository_split_threshold](.). Tables `fundamentals_quarterly`, `short_interest_history`, `splits_history`, `dividends_history`.
- `src/uw_scan/storage/migrations/050_massive_fundamentals.sql` (next free slot).
- `src/uw_scan/cards/firm_characteristics.py` — pure parser/derivers (BM, Profitability, ExternalFin, Z-score, NewIss, …). Goes in `cards/` per [feedback_share_util_split_api](.).
- `src/uw_scan/worker/jobs/massive_fundamentals_jobs.py` — quarterly backfill + nightly refresh.
- One new env var: none needed — reuses `MASSIVE_API_KEY` + `MASSIVE_BASE_URL`.

## Open verification items

1. **What's the actual rate limit on our massive tier?** Check `Retry-After` / `X-RateLimit-*` headers on a saturating-request burst before deciding backfill batch size.
2. **Does `/vX/reference/financials` return >2020 data for *all* tickers?** Spot-check 5 mid-caps and 5 small-caps before committing the migration.
3. **Does `/v3/reference/tickers` expose a `type` filter for "common stock only"?** Need it to filter out ADRs/preferreds, equivalent to CRSP share-code 10/11.
4. **What is the 13-F access tier on massive?** Documented in llms.txt as a real endpoint — if we can pay a one-time uplift fee to unlock InstOwn, that closes the gap. Worth a sales-side question.
5. **Does massive have a `prev_close` / `aggregate` for end-of-month equity returns?** Goyal-Saretto compute stock returns at month-end; we have intraday quote and daily bars in `daily_ohlc` already, but if massive has a pre-computed month-end series it saves a derive step.
