# 14 — Massive.com endpoint probe log

**Probed:** 2026-05-20T04:56Z (UTC), re-run for authoritative record after the conversation summary.
**Base URL:** `https://api.massive.com`
**Auth:** `Authorization: Bearer ${MASSIVE_API_KEY}` (same key already used by `src/uw_scan/sources/ohlc.py`)
**Tooling:** `httpx 0.x` via `uv run --with httpx --with python-dotenv python scripts/probe_massive.py`
**Scripts (persisted in workspace):** `scripts/probe_massive.py` + `scripts/probe_vx_deep.py`
**Raw output (ephemeral, /tmp):** `/tmp/probe_massive_out.json` (26 KB, 17 endpoints) + `/tmp/probe_vx_deep_out.json` (deep /vX field count). Re-run the scripts to regenerate.

This document is the **single source of truth** for what works on our massive tier and what does not. Doc 09 summarizes; this doc keeps the raw probe record so a future session can audit our claims without re-running.

## Summary

| Outcome | Count |
|---|---:|
| Endpoints returning 200 with usable data | 13 |
| Endpoints returning 404 (confirmed gaps) | 4 |
| Total probes | 17 |

All 13 successful endpoints returned in 720–1410 ms (warm latency from local). No rate-limit headers observed; no `Retry-After`. We did not run a saturating burst test (open item Q1 in doc 09).

## Confirmed working endpoints

### Fundamentals — `/v2/reference/financials/{ticker}` (LEGACY)

**Path:** `GET /v2/reference/financials/AAPL?limit=100&type=Q`
**Status:** 200, 1407 ms

- **Top-level shape:** `{status, results: [...]}`
- **Result count returned for AAPL quarterly:** 90 rows
- **Date range (calendarDate):** **1997-09-30 → 2020-03-31** (frozen)
- **Field count per row:** **103 atomic fields** (raw Compustat-style + pre-computed ratios)
- **Annual variant (`type=Y`):** 23 rows, **1997-12-31 → 2019-12-31**, **111 fields** (annual exclusives: `assetTurnover`, `assetsAverage`, `averageEquity`, `investedCapitalAverage`, `returnOnAverageAssets`, `returnOnAverageEquity`, `returnOnInvestedCapital`, `returnOnSales` — i.e., ratios requiring a 4-quarter average)

**Verdict:** Frozen at Q1 2020 for AAPL. Use for 1997–2008 history; from 2009 onward, `/vX` is canonical.

**Full quarterly field list (alphabetised, 103 fields):**

```
EBITDAMargin, accumulatedOtherComprehensiveIncome, accumulatedRetainedEarningsDeficit,
assets, assetsCurrent, assetsNonCurrent, bookValuePerShare, calendarDate,
capitalExpenditure, cashAndEquivalents, cashAndEquivalentsUSD, consolidatedIncome,
costOfRevenue, currentLiabilities, currentRatio, dateKey, debt, debtCurrent,
debtNonCurrent, debtToEquityRatio, debtUSD, deferredRevenue, deposits,
depreciationAmortizationAndAccretion, dividendYield, dividendsPerBasicCommonShare,
earningBeforeInterestTaxes, earningBeforeInterestTaxesUSD,
earningsBeforeInterestTaxesDepreciationAmortization,
earningsBeforeInterestTaxesDepreciationAmortizationUSD, earningsBeforeTax,
earningsPerBasicShare, earningsPerBasicShareUSD, earningsPerDilutedShare,
effectOfExchangeRateChangesOnCash, enterpriseValue, enterpriseValueOverEBIT,
enterpriseValueOverEBITDA, foreignCurrencyUSDExchangeRate, freeCashFlow,
freeCashFlowPerShare, goodwillAndIntangibleAssets, grossMargin, grossProfit,
incomeTaxExpense, interestExpense, inventory, investedCapital, investments,
investmentsCurrent, investmentsNonCurrent, issuanceDebtSecurities,
issuanceEquityShares, liabilitiesNonCurrent, marketCapitalization, netCashFlow,
netCashFlowBusinessAcquisitionsDisposals, netCashFlowFromFinancing,
netCashFlowFromInvesting, netCashFlowFromOperations,
netCashFlowInvestmentAcquisitionsDisposals, netIncome, netIncomeCommonStock,
netIncomeCommonStockUSD, netIncomeToNonControllingInterests,
netLossIncomeFromDiscontinuedOperations, operatingExpenses, operatingIncome,
paymentDividendsOtherCashDistributions, payoutRatio, period,
preferredDividendsIncomeStatementImpact, priceEarnings, priceSales,
priceToBookValue, priceToEarningsRatio, priceToSalesRatio, profitMargin,
propertyPlantEquipmentNet, reportPeriod, researchAndDevelopmentExpense,
revenues, revenuesUSD, salesPerShare, sellingGeneralAndAdministrativeExpense,
shareBasedCompensation, shareFactor, sharePriceAdjustedClose, shareholdersEquity,
shareholdersEquityUSD, shares, tangibleAssetValue, tangibleAssetsBookValuePerShare,
taxAssets, taxLiabilities, ticker, totalLiabilities, tradeAndNonTradePayables,
tradeAndNonTradeReceivables, updated, weightedAverageShares,
weightedAverageSharesDiluted, workingCapital
```

### Fundamentals — `/vX/reference/financials` (CURRENT)

**Path:** `GET /vX/reference/financials?ticker=AAPL&limit=100&timeframe=quarterly`
**Status:** 200, 988 ms

- **Top-level shape:** `{status, request_id, results: [...], next_url?}`
- **Result count for AAPL quarterly:** 68 rows
- **Date range (filing_date):** **2009-07-22 → 2026-05-01** (live)
- **Outer row keys (14):** `acceptance_datetime, cik, company_name, end_date, filing_date, financials, fiscal_period, fiscal_year, sic, source_filing_file_url, source_filing_url, start_date, tickers, timeframe`
- **Real financial fields are nested under `row.financials.{income_statement, balance_sheet, comprehensive_income, cash_flow_statement}`.**

#### Nested field count (drilled into `results[0].financials`):

| Group | Field count | Fields |
|---|---:|---|
| **balance_sheet** | 19 | `accounts_payable, assets, current_assets, current_liabilities, equity, equity_attributable_to_noncontrolling_interest, equity_attributable_to_parent, fixed_assets, intangible_assets, inventory, liabilities, liabilities_and_equity, long_term_debt, noncurrent_assets, noncurrent_liabilities, other_current_assets, other_current_liabilities, other_noncurrent_assets, other_noncurrent_liabilities` |
| **income_statement** | 23 | `basic_average_shares, basic_earnings_per_share, benefits_costs_expenses, cost_of_revenue, costs_and_expenses, diluted_average_shares, diluted_earnings_per_share, gross_profit, income_loss_from_continuing_operations_after_tax, income_loss_from_continuing_operations_before_tax, income_tax_expense_benefit, net_income_loss, net_income_loss_attributable_to_noncontrolling_interest, net_income_loss_attributable_to_parent, net_income_loss_available_to_common_stockholders_basic, nonoperating_income_loss, operating_expenses, operating_income_loss, participating_securities_distributed_and_undistributed_earnings_loss_basic, preferred_stock_dividends_and_other_adjustments, research_and_development, revenues, selling_general_and_administrative_expenses` |
| **cash_flow_statement** | 8 | `net_cash_flow, net_cash_flow_continuing, net_cash_flow_from_financing_activities, net_cash_flow_from_financing_activities_continuing, net_cash_flow_from_investing_activities, net_cash_flow_from_investing_activities_continuing, net_cash_flow_from_operating_activities, net_cash_flow_from_operating_activities_continuing` |
| **comprehensive_income** | 5 | `comprehensive_income_loss, comprehensive_income_loss_attributable_to_noncontrolling_interest, comprehensive_income_loss_attributable_to_parent, other_comprehensive_income_loss, other_comprehensive_income_loss_attributable_to_parent` |
| **Total atomic fields** | **55** | (sum) |

**Per-field payload shape:** every leaf is `{value: float, unit: "USD", label: str, order: int}`. The `value` is the raw figure; `label` is human-readable; `order` is a stable position for UI rendering.

**This is an XBRL-shaped surface**, not the older flat-row /v2 surface. It is missing the pre-computed ratios in /v2 (`profitMargin`, `priceToBookValue`, etc.) — we compute these from raw inputs in `cards/firm_characteristics.py` (Phase 3).

**Sample latest row** (AAPL Q2 2026):
- `fiscal_period`: Q2
- `fiscal_year`: 2026
- `start_date`: 2025-12-28
- `end_date`: 2026-03-28
- `filing_date`: 2026-05-01

**Annual variant** (`timeframe=annual`): 17 rows, **2009-10-27 → 2025-10-31** filing dates.

### Newer-IPO coverage check — RBLX

**Path:** `GET /vX/reference/financials?ticker=RBLX&limit=30&timeframe=quarterly`
**Status:** 200, 783 ms

- 20 quarterly results, filing dates 2021-05-13 → 2025-10-30
- RBLX listed 2021-03 — so coverage starts at first publicly-filed quarter post-IPO, as expected
- This invalidates CashFlowVar (paper requires 60 monthly observations of FCF/MktCap) for RBLX until ~2026-Q1

**Implication:** Phase 3's `firm_characteristics.py` must compute `available_from_quarter` per (ticker, characteristic) and drop tickers from the cross-section when the rolling-window characteristic is undefined.

### Mid-cap parity check — TSLA

**Path:** `GET /vX/reference/financials?ticker=TSLA&limit=30&timeframe=quarterly`
**Status:** 200, 917 ms

- 30 quarterly results, filing dates 2019-04-29 → 2026-04-23
- Response includes `next_url` — pagination works for tickers with >30 quarters of history
- Confirms `/vX` is the live endpoint for mid-cap names through current quarter

### Short interest — `/stocks/v1/short-interest`

**Path:** `GET /stocks/v1/short-interest?ticker=AAPL&limit=500`
**Status:** 200, 770 ms

- **Result count:** 201 rows
- **Date range (settlement_date):** 2017-12-29 → 2026-04-30
- **Cadence:** biweekly FINRA settlements
- **Per-row fields (5):** `avg_daily_volume, days_to_cover, settlement_date, short_interest, ticker`

`days_to_cover` is pre-computed (`short_interest / avg_daily_volume`) which is exactly the paper's RSI definition. No derivation needed.

### Ticker reference — `/v3/reference/tickers/{ticker}` and `/v3/reference/tickers`

**Single-ticker:** `GET /v3/reference/tickers/AAPL` → 200, 743 ms

Rich response including `type: "CS"` (common stock), `cik`, `sic_code`, `primary_exchange`, `market_cap`, `share_class_shares_outstanding`, `weighted_shares_outstanding`, `list_date`, `total_employees`. The `type` field is the share-code-10/11 equivalent we need for universe filtering.

**Listing endpoint with type filter:** `GET /v3/reference/tickers?market=stocks&active=true&limit=5&type=CS` → 200, 919 ms

- Returns 5 results with `type=CS` (filter honored)
- Top-level includes `count` and `next_url` for pagination
- Per-row fields (12): `active, cik, composite_figi, currency_name, last_updated_utc, locale, market, name, primary_exchange, share_class_figi, ticker, type`

**Verdict:** `?type=CS` is the canonical universe filter. Use it.

### Corporate actions — dividends and splits

**Dividends:** `GET /v3/reference/dividends?ticker=AAPL&limit=50` → 200, 731 ms

- 50 rows, ex-div dates 2014-02-06 → 2026-05-11
- Per-row (10 fields): `cash_amount, currency, declaration_date, dividend_type, ex_dividend_date, frequency, id, pay_date, record_date, ticker`
- `next_url` present — full history available via pagination

**Splits:** `GET /v3/reference/splits?ticker=AAPL&limit=50` → 200, 758 ms

- 5 rows, execution dates 1987-06-16 → 2020-08-31
- Covers AAPL's 4-for-1 split (2020-08-31), 7-for-1 (2014-06-09), and pre-1990 splits
- Per-row (5 fields): `execution_date, id, split_from, split_to, ticker`

### Live data — snapshot and market status

**Snapshot:** `GET /v2/snapshot/locale/us/markets/stocks/tickers/AAPL` → 200, 758 ms

Returns nested `day`, `min`, `prevDay` OHLCV plus `todaysChange`, `todaysChangePerc`, `updated`. Useful for live spot fetch but not load-bearing for this research workspace (we use `daily_ohlc` for historical and `market-warehouse` lake for backfills).

**Market status:** `GET /v1/marketstatus/now` → 200, 737 ms

Returns `{afterHours, currencies, earlyHours, exchanges, indicesGroups, market, serverTime}` — calendar utility, useful for trading-day math.

## Confirmed gaps (probed, 404)

All four return `404 page not found` with body length consistent with massive's standard 404 response.

| Path | Maps to paper | Probed | Notes |
|---|---|---|---|
| `/rest/stocks/filings/13-f-filings?ticker=AAPL` | InstOwn (A.5.3) | 404, 726 ms | Docs-URL slug; not an actual API path. |
| `/vX/reference/13-f?ticker=AAPL` | InstOwn | 404, 726 ms | Polygon-style guess; not implemented on our tier. |
| `/rest/partners/benzinga/earnings?ticker=AAPL` | AnalystDisp (A.5.11) | 404, 729 ms | Docs-URL slug. |
| `/rest/partners/benzinga/analyst-ratings?ticker=AAPL` | AnalystDisp | 404, 722 ms | Docs-URL slug. |

**Implication for the paper:** these two characteristics rank lowest in Table 5 importance (InstOwn ρ=0.06, p=0.14; AnalystDisp ρ=0.06, p=0.42 — bottom of the 17 firm-level chars). Their absence does not materially compromise the F2/F3 firm-fundamentals story.

**Implication for product:** if a future research goal requires either of these, contact massive sales — both are documented as real endpoints in their `llms.txt` index but appear partner-gated. Open item Q4 in doc 09.

## Endpoints to probe next (not in this run)

| Endpoint | Why we'd care | Priority |
|---|---|---|
| `/v3/reference/tickers/types` | Confirm `CS` semantics + see ETF/ADR codes | High — needed before universe filter ships |
| `/stocks/v1/short-volume` | Daily short-volume (vs biweekly short-interest) | Low — short-interest is the paper's variable |
| `/v3/reference/ipos` | IPO dates for survivorship-bias auditing | Medium — informs universe entry/exit |
| `/v3/reference/ticker-events` | Symbol changes, M&A, delistings | Medium — corporate-action sanity |
| `/v2/aggs/...` with extended history | OHLC depth vs `market-warehouse` lake | Already in use via `sources/ohlc.py` — no re-probe needed |

## Reproducibility

To reproduce this probe (from the workspace dir `docs/research/goyal-saretto-ipca-options/`):

```bash
uv run --with httpx --with python-dotenv python scripts/probe_massive.py > /tmp/probe_massive_out.json
uv run --with httpx --with python-dotenv python scripts/probe_vx_deep.py > /tmp/probe_vx_deep_out.json
```

The two scripts are self-contained, read `MASSIVE_API_KEY` from `/Users/chenxi/projects/unusual-whales/.env` (absolute path hard-coded — change if you move the repo), and produce JSON output the probe-log doc was generated from. Both scripts are throwaway-safe (no persistence, no side effects).

## What this probe does *not* establish

- **Field-parity between `/v2` and `/vX` in the 2009–2020 overlap zone.** We confirmed both endpoints return data for AAPL in that window; we did *not* confirm e.g. `/v2.assets[2015-03-31] == /vX.balance_sheet.assets[2015-03-31]`. Step 5 in doc 13's revised plan is a 30-line script that does this field-by-field — must run before the Phase 3 fetcher ships.
- **Coverage across our 103-ticker watchlist.** We sampled AAPL, RBLX, TSLA. Step in doc 13 must batch-probe the full watchlist for `/vX` coverage before backfill commits to a tier.
- **Rate limits.** No burst test. Doc 09 open item Q1.
- **Pagination semantics.** We saw `next_url` on TSLA quarterly and AAPL dividends but did not follow the pages. The fetcher in `sources/massive_fundamentals.py` (Phase 3) must implement pagination, not assume `limit` is sufficient.

## One thing we got wrong in doc 09 before this probe

Doc 09 stated `/vX` returns "~50 fields" or "~55 fields" — that count was **the outer + inner combined heuristically**. The authoritative answer is:

- **14 outer keys** (metadata: filing_date, fiscal_period, source URLs, etc.)
- **55 atomic financial fields** nested under `financials.{balance_sheet (19), income_statement (23), cash_flow_statement (8), comprehensive_income (5)}`
- Total atomic fields per row, counting the metadata as fields: **14 + 55 − 1 (the `financials` key itself) = 68 referenceable atoms**

Doc 09 has been updated (separately) to reflect this. For all forward work, treat **55** as the count of real financial fields and **`(outer.{field_name})`** vs **`(inner.financials.{group}.{field_name}.value)`** as the two access paths.
