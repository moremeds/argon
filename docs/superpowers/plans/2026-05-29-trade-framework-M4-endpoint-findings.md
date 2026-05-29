# M4 (UW positioning) — verified endpoint + field findings

> Captured 2026-05-29 during M4 Task 4.0 (the no-fabrication gate). All field
> names below were resolved from `docs/uw-samples/unusual_whales_api_spec.yaml`
> via PyYAML (`components.schemas`), NOT guessed. Use this as the source of
> truth when implementing the fetchers + `normalize_*` functions so the next
> session does not have to re-derive them (that derivation was the expensive,
> channel-fragile part).

## Migration number correction

The plan says `065_uw_positioning.sql`, but the migrations dir already contains
`065`–`069` (canary WF5 + `065_trade_insight_ai_provider_metadata` merged in
after the plan was written). **The positioning migration must be `070_uw_positioning.sql`.**
The fundamentals migration (M5) becomes `071_massive_fundamentals.sql`.

## Confirmed endpoints (paths verified present in spec)

| Purpose | Path template | Spec line | Envelope |
|---|---|---|---|
| Short interest + float (V2) | `/api/shorts/{ticker}/interest-float/v2` | 17421 | `{"data": {obj}}` |
| Analyst ratings | `/api/screener/analysts?ticker=` | 15707 | `{"data": [items]}` |
| Institutional ownership | `/api/institution/{ticker}/ownership` | 13070 | `{"data": [items]}` |
| Insider ticker flow | `/api/insider/{ticker}/ticker-flow` | 12720 | `{"data": [items]}` |
| Historical earnings | `/api/earnings/{ticker}` | 11963 | `{"data": [items]}` |

Note: the V1 `/api/shorts/{ticker}/interest-float` is **deprecated** (spec line
17384) — use the **/v2** variant.

## Response field names (verbatim from component schemas)

### V2 Short Interest and Float → `V2ShortInterestAndFloatData` (data is an OBJECT)
`days_to_cover, fee_rate, market_date, rebate_rate, short_interest,
short_shares_available, si_float, symbol, total_float`
- `si_float` is the **% of float shorted** (string, e.g. "0.017647058") → `si_pct_float`
- FINRA-sourced; updates twice/month and can lag several weeks (expected, not a bug).

### Analyst Rating → `AnalystRatingData` (data is an ARRAY, one row per rating)
`action, analyst_name, firm, rating, recommendation, sector, target, ticker, timestamp`
- Aggregate across items: bucket `recommendation` → buy/hold/sell counts;
  `target` (string price) → avg/hi/lo.

### Institutional Ownership → `InstitutionalOwnershipData` (data is an ARRAY, one row per report_date)
`avg_price, close, first_buy, historical_units, inst_share_value,
price_on_filing, price_on_report, report_date, shares_outstanding_pct,
units, units_change`
- **`shares_outstanding_pct` is the institutional-ownership % we want** (take the
  most recent `report_date`). `units` = shares held; `units_change` = delta.
- ⚠️ The dead M4 subagent FABRICATED a `{name, inst_value}` per-holder shape and
  a `inst_holder_count` field — **neither exists**. Do not reintroduce them. There
  is no holder-count in this endpoint.

### Insider Ticker Flow → `InsiderModuleTickerFlow` → `.data[]` → `InsiderModuleTickerFlowData`
Outer item: `{data: [...], date, has_more, page}`. Inner `InsiderModuleTickerFlowData`:
`premium, buy_premium, transactions, buy_transactions, sell_transactions,
shares, buy_shares, sell_shares, date, sector`
- Net shares = `buy_shares - sell_shares`; net premium = `2*buy_premium - premium`
  (since `premium` is total and `buy_premium` the buy portion).

### Historical Ticker Earnings → `HistoricalTickerEarningsData` (data is an ARRAY, HISTORY only)
`close, continent, country_code, country_name, ending_fiscal_quarter,
expected_move, expected_move_perc, is_s_p_500, long_straddle_1d,
pre_earnings_close, reaction, report_date, report_time, sector, street_mean_est`
- **History only — no forward `next_er_date`.** Per the plan, source `next_er_date`
  from the existing stock/ticker payload (`next_earnings_date` already on
  `flow_events`) and mark `na` if absent. Leave `next_er_date` nullable in the table.
- `reaction` (post-earnings move %) supports conviction factor 4 ("≥3 of last 4
  positive reactions") — count positive `reaction` values in the returned history.

## Proposed `uw_positioning` columns (real-field-grounded)

PK `(ticker, snapshot_date)`, plus `raw_jsonb jsonb`, `fetched_at timestamptz default now()`:
`si_pct_float, si_short_interest, si_total_float, si_days_to_cover,
si_shares_available, si_fee_rate, si_rebate_rate, si_market_date,
analyst_buy, analyst_hold, analyst_sell, analyst_target_avg,
analyst_target_hi, analyst_target_lo, inst_ownership_pct, inst_units,
inst_units_change, insider_net_shares, insider_net_premium,
earn_reactions_positive, earn_reactions_total, next_er_date`

## Salvageable test scaffolding

The dead subagent left two test files (removed from the tree to unblock
collection; full text preserved in the session transcript and at
`/tmp/stubs.txt` during that session):
- `tests/integration/storage/test_positioning_storage.py` — **good**, tests the
  DB round-trip; only needs its column set aligned to the final schema above.
- `tests/integration/worker/test_positioning_job.py` — its canned payloads use
  the FABRICATED institution shape; **rewrite the fakes** to the real schemas above.
