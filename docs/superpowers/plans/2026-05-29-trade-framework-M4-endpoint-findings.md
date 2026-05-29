# M4 (UW positioning) — verified endpoint + field findings

> Captured 2026-05-29 during M4 Task 4.0 (the no-fabrication gate). Every field
> name below was resolved from `docs/uw-samples/unusual_whales_api_spec.yaml`
> via PyYAML (`components.schemas[...].properties`), NOT guessed. Use this as
> the source of truth when implementing the fetchers + `normalize_*` functions
> so the next session does not re-derive them (that derivation is the expensive,
> channel-fragile part).
>
> **Correction note:** an earlier revision of this file (commit 5ebf4ee) had two
> wrong claims — it said the migration must be `070` and that the institution
> `{name, inst_value}` shape was fabricated. Both were wrong; corrected below.

## Migration number

Migrations dir max is `064_trade_insights_ai_provider_metadata.sql`, so
**`065_uw_positioning.sql` is the correct next number** (matches the plan).
The M5 fundamentals migration is then `066_massive_fundamentals.sql`.

## Confirmed endpoints (paths verified present in spec)

| Purpose | Path template | Spec line | Envelope |
|---|---|---|---|
| Short interest + float (V2) | `/api/shorts/{ticker}/interest-float/v2` | 17421 | `{"data": {object}}` |
| Analyst ratings | `/api/screener/analysts?ticker=` | 15707 | `{"data": [rows]}` |
| Institutional ownership | `/api/institution/{ticker}/ownership` | 13070 | `{"data": [rows]}` |
| Insider ticker flow | `/api/insider/{ticker}/ticker-flow` | 12720 | `{"data": [rows]}` |
| Historical earnings | `/api/earnings/{ticker}` | 11963 | `{"data": [rows]}` |

The V1 `/api/shorts/{ticker}/interest-float` is **deprecated** (spec line 17384)
— use the **/v2** variant.

## Response field names (verbatim from component schemas, via PyYAML)

### V2 Short Interest and Float — `data` is a single OBJECT
`days_to_cover, fee_rate, market_date, rebate_rate, short_interest,
short_shares_available, si_float, si_float_with_synth_long_pct_of_total_shares,
symbol, total_float`
- `si_float` = **% of float shorted** (string, e.g. "0.017647058") → map to `si_pct_float`.
- `short_interest` = shares short; `total_float` = float; `days_to_cover` (string).
- FINRA-sourced, updates twice/month, can lag weeks (expected, not a bug).

### Analyst Rating — `data` is an ARRAY, one row per rating
`action, analyst_name, firm, recommendation, sector, target, ticker, timestamp`
- Aggregate: bucket `recommendation` (buy/hold/sell) → counts; `target` (string
  price) → avg/hi/lo across rows.

### Institutional Ownership — `data` is an ARRAY, one row per institutional holder
`avg_price, filing_date, first_buy, historical_units, inst_share_value,
inst_value, name, people, report_date, shares_outstanding, short_name, tags,
units, units_change, value`
- Each row is ONE institution: `name` = institution, `units` = shares held,
  `inst_value`/`value` = dollar value, `shares_outstanding` = ticker total.
- Derive: `inst_holder_count = len(data)`; `inst_total_value = sum(inst_value)`.
  Optional ownership% = `sum(units) / shares_outstanding` (use most recent
  `report_date` if mixing). The dead subagent's `{name, inst_value}` fake was a
  VALID subset of this — keep it.

### Insider Ticker Flow — `InsiderModuleTickerFlow.data` is an ARRAY
Row fields: `avg_price, buy_sell, date, has_more, premium, transactions,
uniq_insiders, volume`
- Rows are split by `buy_sell` ("buy"/"sell") per date. Derive
  `insider_buy_volume`/`insider_sell_volume` by summing `volume` per side,
  `insider_net_flow = buy_premium − sell_premium` (sum `premium` per side).

### Historical Ticker Earnings — `data` is an ARRAY, HISTORY only
`actual_eps, ending_fiscal_quarter, expected_move, expected_move_perc,
long_straddle_1d, long_straddle_1w, post_earnings_move_1d, post_earnings_move_1w,
post_earnings_move_2w, post_earnings_move_3d, pre_earnings_move_1d,
pre_earnings_move_1w, pre_earnings_move_2w, pre_earnings_move_3d, report_date,
report_time, short_straddle_1d, short_straddle_1w, source, street_mean_est`
- **History only — no forward `next_er_date`.** Per the plan, source `next_er_date`
  from the existing stock/ticker payload (`next_earnings_date` already on
  `flow_events`) and mark `na` if absent. Keep `next_er_date` nullable.
- Post-earnings reaction = **`post_earnings_move_1d`** (NOT a `reaction` field).
  Conviction factor 4 ("≥3 of last 4 positive reactions") = count positive
  `post_earnings_move_1d` over the most recent 4 rows.

## Proposed `uw_positioning` columns (all real-field-grounded)

PK `(ticker, snapshot_date)`, plus `raw_jsonb jsonb`, `fetched_at timestamptz default now()`:
`si_pct_float, si_short_interest, si_total_float, si_days_to_cover,
si_shares_available, si_fee_rate, si_rebate_rate, si_market_date,
analyst_buy, analyst_hold, analyst_sell, analyst_target_avg, analyst_target_hi,
analyst_target_lo, inst_holder_count, inst_total_value, insider_buy_volume,
insider_sell_volume, insider_net_flow, earn_reactions_positive,
earn_reactions_total, next_er_date`

## Salvageable test scaffolding (from the dead M4 subagent)

The subagent left two test files (removed from the tree to unblock collection;
full text is in the session transcript). Re-assessed against the REAL schemas:
- `tests/integration/storage/test_positioning_storage.py` — **good as-is**;
  its column set matches the proposed table above. Reinstate, align any names.
- `tests/integration/worker/test_positioning_job.py` — its canned payloads are
  **essentially correct** (short-interest `{data:{...}}`, analyst/institution/
  insider arrays). Reinstate; verify the insider fake uses `buy_sell`+`premium`
  +`volume` (it does) and that institution uses `{name, inst_value}` (valid).
