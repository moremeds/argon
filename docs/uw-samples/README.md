# UW Endpoint Sample Payloads

Captured on 2026-05-12 by `scripts/s0_probe_endpoint.py` against the live UW API.
These payloads serve as the contract tests for normalizers: every normalizer in
`src/uw_scan/normalize.py` is unit-tested against the corresponding sample here.

If UW changes a response shape, the affected sample is re-captured, the failing
normalizer test is inspected, and the normalizer is updated.

## Test ticker

TSLA — selected because it has populated values in every field of the
Single-Stock Card example in the spec.

## Per-endpoint shape summary

(see _shape-summary.md for the mechanical jq output; supplement here with surprises only)

## Bulk net-premium screener research

BULK_FOUND: `/api/screener/stocks` returns 100 tickers per call with full per-ticker
net premium fields (net_call_premium, net_put_premium, bullish_premium, bearish_premium,
call_premium, put_premium, iv_rank, implied_move, next_earnings_date, et al.). Each row
carries 70 numeric/string fields. The S2 full scan can use a single bulk call (with
filters such as `is_s_p_500=true` or a custom liquidity/marketcap filter) instead of
fanning out per ticker. The `/api/market/movers` endpoint requires Advanced API tier
(403 on this token) so it is not used.

## Auth + rate limit observations

- Header used: `Authorization: Bearer <token>`
- Rate-limit headers observed (UW-specific, present on every response — including 403):
  - `x-uw-token-req-limit` — daily request budget for the token (observed value: `20000`).
  - `x-uw-daily-req-count` — cumulative requests already used today (observed: `766` mid-probe; this grows monotonically across the run).
  - `x-uw-req-per-minute-remaining` — requests remaining in the current minute window (observed: `117`–`118`, implying a per-minute budget of `120`).
  - `x-uw-minute-req-counter` — requests already used in the current minute window.
  - `x-uw-req-per-minute-reset` — appears to be time-to-reset for the per-minute window (observed: `44469`–`51395`; unit not labelled but consistent with milliseconds remaining inside a 60s window). **Open question for S1: confirm unit.**
- 429 behavior: not observed during this probe (17 + 2 = 19 requests, well under both the 120/min and 20000/day budgets).

## Open questions for S1

- `x-uw-req-per-minute-reset` unit (ms? Unix ms? something else?). Easy to validate in S1 by hammering 120 requests and watching the value cross 0 → reset.
- `option_contracts` returns a list of contract metadata only. Snapshot pricing (mid, IV, OI, volume) appears to come from the broader `/api/stock/{ticker}/option-contracts` shape — confirmed: `option_contracts_by_symbol` with real OCC strings returns 2 items with full snapshot fields. S1's trade plan economics can rely on this.
- `skew` requires both `expiry` and `delta` query params (UW OpenAPI requires both). The probe sends `delta=25`; S1 normalizer should accept skew rows for any delta and not hardcode 25 in the schema.

### bulk_market_movers
- Path: `/api/market/movers`
- Status: 403
- Params: `{}`
- Body type: object
- Top-level keys: code, message
- Pagination hints: []
- Surprises: 403 — requires Advanced API tier (`code: advanced_tier_required`). Skipped for V1. Rate-limit headers still returned on 403.

### bulk_screener_stocks_sp500
- Path: `/api/screener/stocks`
- Status: 200
- Params: `{"is_s_p_500":"true","limit":100}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Returned 100 S&P 500 tickers each with 70 fields including net_call_premium, net_put_premium, bullish_premium, bearish_premium, iv_rank, implied_move, next_earnings_date, sector, marketcap. This single call replaces 100 per-ticker fanout calls for S2's scan.

### darkpool_ticker
- Path: `/api/darkpool/TSLA`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 500 prints per call. Each print has timestamp, market_center, size, price, NBBO context (nbbo_bid/ask + quantities), ext_hour_sold_codes. No notional field — multiply size × price in normalizer.

### flow_alerts
- Path: `/api/option-trades/flow-alerts`
- Status: 200
- Params: `{"limit":100}`
- Body type: object
- Top-level keys: data, newer_than, older_than
- Pagination hints: []
- Surprises: Cursor-based pagination via `newer_than` / `older_than` keys, not `next_page`/`has_more` (was checked for in shape summary). 100 rows per call. Each row has 30+ fields including price ladder, strike, OI before/after.

### greek_exposure
- Path: `/api/stock/TSLA/greek-exposure/strike-expiry`
- Status: 200
- Params: `{"expiry":"2026-05-15"}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Per-(date, expiry, dte) row with call_/put_ prefixed gex/dex/vanna/charm fields. The S1 Card's GEX-by-strike-expiry section needs both this AND `spot_exposures` (which is per-strike).

### greeks
- Path: `/api/stock/TSLA/greeks`
- Status: 200
- Params: `{"expiry":"2026-05-15"}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 188-row per-contract greeks (one row per strike, with call_* and put_* columns). Heavy payload — S1 should select expiry + relevant strikes only.

### interpolated_iv
- Path: `/api/stock/TSLA/interpolated-iv`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 9-row array, one per standard tenor (days = 1, 7, 14, 30, etc.) with `percentile` and `volatility`. Use this for 'IV percentile @ 30d' style readouts, NOT iv_rank.

### iv_rank
- Path: `/api/stock/TSLA/iv-rank`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Returns a daily time series (multiple rows, one per recent trading day), not a single current value. Use the most recent `date` for the Card's current IV-rank value; keep the series for history.

### max_pain
- Path: `/api/stock/TSLA/max-pain`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data, date
- Pagination hints: []
- Surprises: Per-expiry max pain object with `max_pain`, `close`, `open`, `next_upper_strike`, `next_lower_strike`. Wrapped in a `data` array but typically one row per expiry.

### oi_change
- Path: `/api/stock/TSLA/oi-change`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 50-row top movers by OI delta. Fields include `curr_oi`, `last_date`, `avg_price`, `days_of_oi_increases`, `days_of_vol_greater_than_oi`. Direct fit for the OI Changes table in the Card.

### oi_per_strike
- Path: `/api/stock/TSLA/oi-per-strike`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 209 rows of (date, strike, call_oi, put_oi). Compact and easy to normalize. Latest `date` is current OI.

### option_contracts_by_symbol
- Path: `/api/stock/TSLA/option-contracts`
- Status: 200
- Params: `{"option_symbol[]":["TSLA260511C00440000","TSLA260511C00425000"]}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Same endpoint as `option_contracts` but filtered by `option_symbol[]` (multi-value param). Returns full snapshot for exact OCC symbols supplied. Used for trade-plan strike pricing in S1.

### option_contracts
- Path: `/api/stock/TSLA/option-contracts`
- Status: 200
- Params: `{"limit":50}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 50 contracts per call with full snapshot fields: ask_volume, bid_volume, implied_volatility, last_price, mid_volume, multi_leg_volume, floor_volume. Adequate for trade plan economics.

### realized_volatility
- Path: `/api/stock/TSLA/volatility/realized`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 251-row trailing time series of (date, price, implied_volatility, realized_volatility, unshifted_rv_date). Use latest row for the Card's RV value; keep history for VRP charting.

### short_data
- Path: `/api/shorts/TSLA/data`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Array of intraday snapshots (multiple rows per day with `timestamp`). Fields are `short_shares_available`, `fee_rate`, `rebate_rate` — no short interest % / days-to-cover / utilization here. The 'Short Int' field in the Card may need a different source or a derivation.

### skew
- Path: `/api/stock/TSLA/historical-risk-reversal-skew`
- Status: 200
- Params: `{"expiry":"2026-05-15","delta":25}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Time series (223 rows for delta=25 on a single expiry). The `risk_reversal` value is a string. Both `expiry` and `delta` query params are required by the API.

### spot_exposures
- Path: `/api/stock/TSLA/spot-exposures/expiry-strike`
- Status: 200
- Params: `{"expirations[]":["2026-05-15"]}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: Per-strike rows with separate _ask, _bid, _oi, _vol variants for each greek (call_delta_ask, call_delta_bid, call_delta_oi, call_delta_vol; same pattern for gamma/theta/vega/rho/vanna/charm). Many columns; selective projection in normalizer is essential.

### term_structure
- Path: `/api/stock/TSLA/volatility/term-structure`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: 25-row array, one per expiry up the term curve (dte 0 to multi-month). All values returned as strings (volatility, implied_move).

### volatility_stats
- Path: `/api/stock/TSLA/volatility/stats`
- Status: 200
- Params: `{}`
- Body type: object
- Top-level keys: data
- Pagination hints: []
- Surprises: One row per `date` with `iv_high`/`iv_low`/`iv_rank` and `rv_high`/`rv_low`. The 52-week range fields in the Card map to `iv_low`..`iv_high` and `rv_low`..`rv_high` per row, but `volatility_stats` is a time series — pick the latest row.

