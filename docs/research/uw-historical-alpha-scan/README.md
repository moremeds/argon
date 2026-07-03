# UW Historical Alpha Scan

Checked at: `2026-07-02`

Scope: scan Argon's repo, `docs/uw-samples`, and the live UW API docs for
historical data that can be persisted and used for US-stock short-dated swing
alpha. The target holding period is 1-3 weeks with defined-risk option
expressions.

## Evidence Gathered

- Worktree: `.worktrees/uw-historical-alpha-scan`
- Baseline check: `uv run python -c "import uw_scan; print('uw_scan import ok')"`
- Local docs scanned:
  - `docs/uw-samples/unusual_whales_api.md`
  - `docs/uw-samples/unusual_whales_api_spec.yaml`
  - `docs/uw-samples/uw_api_capability_audit.md`
  - `docs/uw-samples/*.json`
- Repo integration scanned:
  - `src/uw_scan/api/endpoints.py`
  - `src/uw_scan/sources/uw.py`
  - `src/uw_scan/storage/migrations/*`
  - `docs/runbooks/data-gap-healer.md`
- Live docs checked:
  - `https://api.unusualwhales.com/docs`
  - `https://api.unusualwhales.com/api/openapi`

## Live Docs Delta

The live OpenAPI surface currently has `190` paths vs `177` in the checked-in
repo spec. New paths worth noting:

| Path | Status from probe | Notes |
| --- | --- | --- |
| `/api/stock/{ticker}/volatility/anomaly` | Accessible | Returns `{latest, history}` with `direction` and `score`. |
| `/api/stock/{ticker}/volatility/character` | Accessible | Returns `{latest, history}` with `character`, `half_life_days`, `hurst_rv`. |
| `/api/stock/{ticker}/volatility/variance-risk-premium` | Accessible | Returned 231 daily AAPL rows in probe. |
| `/api/stock/{ticker}/gex-levels` | Accessible | Returns `call_wall`, `put_wall`, `gamma_flip`, `gamma_magnet`. |
| `/api/options-pulse/*` | Gated | Requires Nasdaq Options Pulse data add-on under current token. |
| `/api/volatility/vix-term-structure` | Gated | Requires volatility add-on under current token. |
| `/api/option-trades/exchange-breakdown/{date}` | Not probed | New path, likely useful for flow quality/exchange routing. |

Probe command used 8 low-cost authenticated requests and did not print secrets.
Observed status: options-pulse 403, VIX term structure 403, ticker volatility
analytics and GEX levels 200.

## 5 Strategy Shortlist

### 1. Volatility Anomaly / VRP Reversion

Thesis: UW now exposes ticker-level volatility anomaly, volatility character,
and variance risk premium directly. Short-dated swing candidates should be
ranked by where realized/implicit volatility looks statistically displaced and
where the vol process has a favorable half-life.

Data:

- `/api/stock/{ticker}/volatility/anomaly`
- `/api/stock/{ticker}/volatility/character`
- `/api/stock/{ticker}/volatility/variance-risk-premium`
- existing Argon `vrp_daily`, `volatility_stats_history`,
  `realized_volatility_history`

Alpha shape:

- Fade extreme `short_vol` or `long_vol` anomaly only when price setup agrees.
- Use `character` and `half_life_days` to separate fast mean-reverting vol from
  persistent regime shifts.
- Combine with Alpha191-style volatility compression / expansion and trend
  slope filters.

Option expression:

- Defined-risk calendars, debit spreads, or iron flies/condors depending on IV
  level and expected direction.
- No naked short-vol structures.

Priority: **highest**. This is accessible now and directly overlaps Argon's VRP
work.

### 2. Dealer Gamma Wall Pin / Breakout

Thesis: new `gex-levels` gives a compact daily dealer map: call wall, put wall,
gamma flip, and gamma magnet. For 1-3 week swings, the alpha is either pin/fade
inside the walls or directional breakout after a clean gamma-flip breach.

Data:

- `/api/stock/{ticker}/gex-levels`
- existing `/api/stock/{ticker}/greek-exposure/*`
- existing `option_surface_grid_daily`
- existing spot/ohlc history from Apex/Massive

Alpha shape:

- Pin/fade: when price is near gamma magnet and walls are tight.
- Breakout: when price crosses gamma flip with rising call/put delta flow.
- Avoid if walls are stale or the chain has poor OI quality.

Option expression:

- Pin/fade: defined-risk butterflies or tight debit/credit spreads.
- Breakout: call or put debit spreads 1-3 weeks out.

Priority: **high**. New endpoint reduces compute effort and creates a stable
daily table.

### 3. Net Premium / Greek Flow Continuation

Thesis: 1-minute net premium, delta flow, and vega flow can provide a stronger
flow-confirmation layer than daily options volume alone. For short-dated swings,
the useful signal is persistent directional flow over multiple intraday windows,
not one-off prints.

Data:

- `/api/stock/{ticker}/net-prem-ticks`
- `/api/stock/{ticker}/greek-flow`
- `/api/stock/{ticker}/greek-flow/{expiry}`
- `/api/market/top-net-impact`
- `/api/market/market-tide`
- `/api/market/{sector}/sector-tide`

Alpha shape:

- Follow persistent positive net call premium / delta flow if price trend and
  volume confirmation agree.
- Fade flow only when it fails to move price and dealer walls resist.
- Use sector tide to avoid fighting broad sector flow.

Option expression:

- Directional call/put debit spreads, 1-3 week expiry.
- Add event and IV filters before trading.

Priority: **high**, but 1-minute tables can grow quickly.

### 4. Dark/Lit Block Accumulation Confirmation

Thesis: dark pool and lit flow prints with NBBO context can identify silent
accumulation/distribution. This is closest to an Alpha191 price-volume
interaction extension for US stocks: large off-exchange premium plus price
absorption can precede 1-3 week drift.

Data:

- `/api/darkpool/{ticker}`
- `/api/darkpool/recent`
- `/api/lit-flow/{ticker}`
- `/api/lit-flow/recent`
- Apex/Massive OHLCV

Alpha shape:

- Accumulation: repeated large premium near/above ask-side context with price
  holding or rising.
- Distribution: repeated large premium with failed price progress.
- Confirm with 5-10 day momentum and relative volume.

Option expression:

- Call/put debit spreads after confirmation.
- Avoid pure block-following without price confirmation.

Priority: **medium-high**. Data is useful but storage volume and normalization
need care.

### 5. Short-Squeeze Convexity Filter

Thesis: short interest, borrow fee, FTDs, and short-volume exchange data can
identify names where bullish flow/momentum has convex upside. This is not a
standalone buy signal; it is a leverage filter for call spreads.

Data:

- `/api/shorts/{ticker}/interest-float/v2`
- `/api/shorts/{ticker}/ftds`
- `/api/shorts/{ticker}/volumes-by-exchange`
- `/api/short_screener`
- existing `uw_positioning`

Alpha shape:

- Candidate when SI/float, days-to-cover, fee rate, FTD pressure, and call-flow
  confirmation all point in the same direction.
- Reject if earnings/event risk dominates or the chain is too wide.

Option expression:

- Defined-risk call debit spreads, 2-4 week expiry.
- Outright calls only when IV/spread quality is unusually favorable.

Priority: **medium-high**. Useful as a convexity overlay on momentum and flow
strategies.

## 5 Data Tables To Persist

### 1. `uw_volatility_signal_daily`

Purpose: durable daily ticker-level volatility analytics.

Endpoints:

- `/api/stock/{ticker}/volatility/anomaly`
- `/api/stock/{ticker}/volatility/character`
- `/api/stock/{ticker}/volatility/variance-risk-premium`

Suggested key:

- `(ticker, market_date)`

Suggested columns:

- `ticker`
- `market_date`
- `anomaly_direction`
- `anomaly_score`
- `vol_character`
- `half_life_days`
- `hurst_rv`
- `vrp_rank`
- `risk_premium`
- `raw_jsonb`
- `fetched_at`

Why save:

- Accessible now.
- Directly useful for 1-3 week option structure choice.
- Complements existing `vrp_daily` instead of replacing it.

### 2. `uw_gex_levels_daily`

Purpose: compact daily dealer-wall map.

Endpoint:

- `/api/stock/{ticker}/gex-levels`

Suggested key:

- `(ticker, market_date)`

Suggested columns:

- `ticker`
- `market_date`
- `call_wall`
- `put_wall`
- `gamma_flip`
- `gamma_magnet`
- `spot`
- `raw_jsonb`
- `fetched_at`

Why save:

- New live endpoint, accessible now.
- Much cheaper than reconstructing these levels from the full surface every
  time.
- Useful for pin/fade/breakout strategy tests.

### 3. `uw_intraday_option_flow_bars`

Purpose: one-minute option flow features for 1-3 week entry timing.

Endpoints:

- `/api/stock/{ticker}/net-prem-ticks`
- `/api/stock/{ticker}/greek-flow`
- `/api/stock/{ticker}/greek-flow/{expiry}`
- optionally market/sector tide for context

Suggested key:

- `(ticker, market_date, ts, expiry)`

Suggested columns:

- `ticker`
- `market_date`
- `ts`
- `expiry`
- `net_call_premium`
- `net_put_premium`
- `net_delta`
- `dir_delta_flow`
- `dir_vega_flow`
- `otm_dir_delta_flow`
- `otm_dir_vega_flow`
- `transactions`
- `volume`
- `raw_jsonb`
- `fetched_at`

Why save:

- Historical selector endpoints have limited lookback; missed sessions are lost.
- Enables flow persistence / failed-flow / flow-confirmed momentum tests.

### 4. `uw_dark_lit_flow_prints`

Purpose: historical off-exchange and exchange block-flow evidence.

Endpoints:

- `/api/darkpool/{ticker}`
- `/api/darkpool/recent`
- `/api/lit-flow/{ticker}`
- `/api/lit-flow/recent`

Suggested key:

- `(source, tracking_id)` where source is `darkpool` or `lit_flow`.

Suggested columns:

- `source`
- `tracking_id`
- `ticker`
- `executed_at`
- `market_date`
- `price`
- `size`
- `premium`
- `market_center`
- `nbbo_bid`
- `nbbo_ask`
- `nbbo_bid_quantity`
- `nbbo_ask_quantity`
- `sale_cond_codes`
- `trade_code`
- `raw_jsonb`
- `fetched_at`

Why save:

- Useful for accumulation/distribution alpha.
- Current repo has `dark_pool_events` tied to scan runs; this should be a
  durable feed table independent of scan-run cascade semantics.

### 5. `uw_short_pressure_daily`

Purpose: short-squeeze and borrow-pressure feature store.

Endpoints:

- `/api/shorts/{ticker}/interest-float/v2`
- `/api/shorts/{ticker}/ftds`
- `/api/shorts/{ticker}/volumes-by-exchange`
- `/api/short_screener`

Suggested key:

- `(ticker, market_date)`

Suggested columns:

- `ticker`
- `market_date`
- `short_interest`
- `si_float`
- `si_float_with_synth_long_pct_of_total_shares`
- `days_to_cover`
- `fee_rate`
- `rebate_rate`
- `short_shares_available`
- `total_float`
- `ftd_quantity`
- `short_volume`
- `total_volume`
- `short_volume_ratio`
- `raw_jsonb`
- `fetched_at`

Why save:

- Existing `uw_positioning` stores a daily aggregate snapshot, but not the full
  daily feature history needed for robust squeeze backtests.
- Good overlay for momentum/flow strategies.

## Gated But Valuable

### `uw_options_pulse_daily`

Endpoints:

- `/api/options-pulse/total`
- `/api/options-pulse/top`
- `/api/options-pulse/sectors`
- `/api/stock/{ticker}/options-pulse`

Probe result:

- Current token returned 403 `options_pulse_scope_required`.

Recommendation:

- Do not implement now unless the add-on is purchased.
- If access is upgraded, make this a top-3 table immediately because it is a
  high-level options activity signal with date selectors.

### `uw_vix_term_structure_daily`

Endpoint:

- `/api/volatility/vix-term-structure`

Probe result:

- Current token returned 403 `volatility_scope_required`.

Recommendation:

- Useful for market-regime overlay, but lower priority than ticker-level
  volatility analytics because Argon already has VIX/VIX3M sources.

## Validation Plan

1. Add fetchers and raw payload persistence for the two accessible new endpoint
   families first:
   - ticker volatility analytics
   - gex levels
2. Backfill all available history for active watchlist tickers.
3. Join with Apex/Massive close-to-close forward returns at 5d, 10d, and 15d.
4. Test each strategy as:
   - long-only
   - short-only
   - sector-neutral long-short
   - filtered by liquidity and IV rank
5. Only after stock-alpha validation, add options-chain simulation:
   - entry at ask, exit at bid
   - defined-risk debit spreads/calendars/flies only
   - exclude earnings inside hold window unless testing an event strategy

## Immediate Build Recommendation

Start with two tables:

1. `uw_volatility_signal_daily`
2. `uw_gex_levels_daily`

Reason: both are accessible now, low row-count, directly tied to 1-3 week
options strategies, and fill gaps in the current repo without huge storage
growth.

