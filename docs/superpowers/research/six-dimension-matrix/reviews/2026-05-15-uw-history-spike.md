# UW history availability spike — result

**Run date**: 2026-05-15
**Script**: `scripts/uw_history_spike.py`
**Account**: live `UW_SCAN_API_KEY` from project `.env`
**Endpoints probed**: `/api/stock/{T}/greeks`, `/api/stock/{T}/greek-exposure/strike-expiry`, `/api/stock/{T}/spot-exposures/expiry-strike`, `/api/stock/{T}/historical-risk-reversal-skew`
**Tickers**: SPY, QQQ, IWM, SPX
**Probe dates**: 2018-06-15, 2019-06-15, …, 2024-06-15

## Top-line — the 2018-2025 backtest as designed is infeasible on this account

UW returned `403 historic_data_access_missing` on **every single probe** of the per-strike greeks, greek-exposure, and spot-exposure endpoints. Response body:

> `{"code":"historic_data_access_missing","message":"The earliest date currently available to you is 2026-04-01 (30 trading days)…"}`

The current UW subscription tier serves the **most recent 30 trading days** for the per-strike greeks/exposures endpoints — i.e., earliest 2026-04-01 as of this run. Nothing older is retrievable.

| Endpoint | Coverage on this account | Backtest implication |
|---|---|---|
| `/api/stock/{T}/greeks` (per-strike) | 30 trading days (2026-04-01 → today) | 6 weeks of vanna/charm history — insufficient for any statistically meaningful backtest |
| `/api/stock/{T}/greek-exposure/strike-expiry` | 30 trading days | Same — dealer-flow-cluster dimensions cannot be backtested at depth |
| `/api/stock/{T}/spot-exposures/expiry-strike` | 30 trading days | Same — intent-split flow signals cannot be backtested |
| `/api/stock/{T}/historical-risk-reversal-skew` | **~1 year** of trailing daily data (LEAPS expiry queries return ~251–253 rows; 2025-05-15 → 2026-05-14) | Skew dimension is backtestable for 1 year. Near-term expiries (< 6 months out) return 0 rows — likely a UW endpoint behavior, not an access tier issue. |

The skew endpoint exception is significant — that single dimension *can* be backtested with ~1 year of history, but only when querying a far-dated expiry. This explains why `risk_reversal_skew_history` has substantive content despite the per-strike greeks lockout.

## Skew endpoint behavior (verified)

| Ticker | Expiry probed | Status | Rows | Earliest | Latest |
|---|---|---|---|---|---|
| SPY | 2026-05-16 | 200 | 0 | — | — |
| SPY | 2026-06-19 | 200 | 0 | — | — |
| SPY | 2026-12-18 | 200 | **251** | 2025-05-15 | 2026-05-14 |
| QQQ | 2026-12-18 | 200 | 251 | 2025-05-15 | 2026-05-14 |
| IWM | 2026-12-18 | 200 | 251 | 2025-05-15 | 2026-05-14 |
| SPX | 2026-12-18 | 200 | **253** | 2025-05-15 | 2026-05-14 |

UW's `historical-risk-reversal-skew` requires a **far-dated expiry** to return non-empty data. The rolling window per call is approximately 251 trading days (≈ 1 year). Near-term expiries return 0 rows.

## Implications for the 6-dimension matrix backtest

| Dimension | Backtest feasibility on current account | Alternative path |
|---|---|---|
| Vanna (per-strike greeks) | ❌ 30 trading days only | Accumulate going forward via nightly `fetch_greeks` runs; ~2 years to have a backtest set |
| Charm (per-strike greeks) | ❌ 30 trading days only | Same |
| Skew (25Δ rr) | ⚠️ ~1 year, LEAPS expiry only | Sufficient for skew-isolated Phase 1 testing; not enough to test joint signals |
| Term Structure | ⚠️ depends on `term_structure` endpoint depth (not probed here — separate spike needed) | If similar, accumulate forward |
| Implied Move | depends on IV/straddle history | IV history is in `interpolated_iv` endpoint (separate probe) |
| VRP (strict) | depends on RV and IV history (similar limitations expected) | Separate probe; or accumulate forward |

## Available options (decision needed)

| Option | Cost | Time-to-backtest | Notes |
|---|---|---|---|
| **A. Upgrade UW subscription** to a tier with deeper history | Money | Same week as upgrade | Need to ask UW sales what tiers include multi-year history for `/api/stock/{T}/greeks`. Practitioner accounts at vendors like UW typically range from $50/mo (current) to $500+/mo (institutional with deep history). |
| **B. Source historical greeks externally** (ORATS, Polygon, IVolatility, CBOE LiveVol) | Money + integration work | 2–4 weeks | ORATS and CBOE LiveVol both sell historical per-strike greeks. Schema-mapping into `uw_scan.greeks_by_expiry_strike` is medium effort. |
| **C. Accumulate forward** — run the nightly worker now, get backtest data in 12–24 months | $0 (we're already running) | 12–24 months for any signal | Cheapest. Gives a *forward* backtest, not historical. Cockpit can still ship as display-only immediately. |
| **D. Skew-only Phase 1 backtest** — use the 1-year skew window to test the *skew-dimension-isolated* falsification criteria; defer multi-dimension joint tests | $0 | Now | Limited to falsification criterion 1 in `09 §1` partially, and only the skew row of §0.1. Cannot test Vanna+Charm joint condition. |
| **E. UW Data Shop one-off purchase** (`unusualwhales.com/data_shop`) | $$ per ticker × timespan | Order processing minutes-to-hours | Separate distribution channel from the live API — sells EOD per-strike option chains *with* greeks and aggressor-classified volumes. Confirmed prices below. |

## Option E — UW Data Shop pricing (verified live 2026-05-15)

The data shop is a separate UW product (`/data_shop`) that sells historical CSV/parquet/ndjson at per-ticker × per-timespan unit pricing. We have a **$40 credit on this account**. Pricing for the datasets relevant to the 6-dim matrix:

| Dataset | Per-strike? | 1d | 30d | 1y | 5y | Schema columns relevant to matrix |
|---|---|---|---|---|---|---|
| `option_chains` | ✅ | $2 | $30 | $180 | — | `implied_volatility`, `delta`, `gamma`, `theta`, `vega`, `rho`, `iv_low`, `iv_high`, `ask_volume`, `bid_volume`, `mid_volume`, `neutral_volume`, `sweep_volume`, `cross_volume`, `floor_volume`, `multi_leg_volume`, `total_bid_changes`, `total_ask_changes`, `canceled_volume`, `total_premium`, `open_interest`, `volume`, `trades` |
| `big_option_trades` | per-trade with greeks (>$25k or >150 contracts) | $2 | — | $180 | — | per-trade analog of option_chains, with `executed_at` timestamp, `nbbo_bid/ask`, `ewma_nbbo_bid/ask` |
| `gamma_exposure` | aggregate (one row/day) | — | — | $10 | — | `date`, `put_gex`, `call_gex`, `net_gex`, `put_call_gex_ratio` |
| `delta_exposure` | aggregate (one row/day) | — | — | $10 | — | `date`, `put_delta`, `call_delta`, `net_delta`, `put_call_delta_ratio` |
| `iv_rank` | aggregate (one row/day) | — | — | $10 | **$20** | `iv_rank_1y`, `iv_percentile_1y`, `iv_rank_1m`, `iv_percentile_1m`, `volatility` |
| `ohlc_daily` | n/a | — | — | $1 | — | OHLCV — but we have this via massive already |
| `oi_changes` | per-strike full market | $15/d | — | — | — | OI deltas + flow split — full-market scope, daily-only purchase |
| `market_tide` | minute, market-wide | — | $50/30d | $300 | — | `net_call_premium`, `net_put_premium`, `net_volume` |

Key observations:

1. **`option_chains` is the only data-shop product that delivers per-strike greeks history** — i.e., the dimension blocked on the live API. Other products are daily ticker-level aggregates that we can already derive (or pull via cheaper endpoints).
2. **No 5-year option for `option_chains`**, despite the info text mentioning "1 year or 5 years" for some products. Only `iv_rank` and `ohlc_daily` expose 5y. This caps the data-shop-purchasable Vanna/Charm/Skew history at 1 year per ticker.
3. **Per-trade `big_option_trades` is a superset of `option_chains` for the >$25k / >150-contract subset** — same greeks, plus timestamp and microstructure. Higher resolution for the Flow dimension specifically.

### $40 budget strategies

| Strategy | Spend | Unblocks | Leaves blocked |
|---|---|---|---|
| **E1. Validation purchase** — 1 ticker × 30d Option Chains | $30 SPY 30d | Pipeline build + schema verification + 30-day per-strike vanna/charm sample | Backtest depth (30d is too short) |
| **E2. Long-horizon IV substrate** — 2 tickers × 5y IV Rank | $40 (SPY+QQQ 5y) | 5y IV regime history for VRP/IM dimension on 2 tickers | Per-strike Vanna/Charm/Skew/Flow |
| **E3. Aggregate dealer flow** — 2 tickers × 1y (GEX + DEX) | $40 (SPY+QQQ × $10 each) | 1y aggregate dealer-exposure history on 2 tickers | Per-strike data; only ticker-aggregate |

E1 is the only spend that derisks the **eventual real purchase decision** ($720 for 4 tickers × 1y of Option Chains). It validates 4 things before committing the larger spend:

1. Does data-shop EOD `implied_volatility`/`delta`/`gamma` agree numerically with the live `/api/stock/{T}/greeks` endpoint? (Schema-seam risk between historical and forward-accumulated data.)
2. Does `ask_volume`/`bid_volume` semantics match the same fields in `uw_scan.volume_by_strike_expiry`? (Aggressor classification convention — see [`project_aggressor_classification_semantics.md`](aggressor memory))
3. Does the file load cleanly into `uw_scan.greeks_by_expiry_strike` with no derived-column gaps?
4. Is the EOD-only daily granularity enough for the consistency check in `00 §0.2`? (Likely yes — the check is daily-resolution — but worth verifying.)

E2 and E3 buy data we either already have (live API gives daily aggregates for free on the current tier) or that doesn't unblock the matrix.

## Recommendation

**Revised after data-shop pricing check (2026-05-15)**: C + D + **E1** is the lowest-friction path:

0. **(New)** Spend $30 of the $40 credit on **option_chains, single_ticker, SPY, 30d** — pure validation purchase. Confirms data-shop schema matches our live API and that the file loads into `greeks_by_expiry_strike` cleanly. Save the remaining $10 for a follow-up small purchase if a gap is found.

Then the original C+D path:

1. Ship the Cockpit as a **display + AI** tool now, with `09 §0.4` fail-state language already in place ("Cockpit ships as display only — no trading recommendation — if Phase 1 falsification answers come back negative").
2. Run the nightly worker against the 4 Cockpit tickers; `matrix_state_snapshots` accumulates from day 1.
3. Use the 1-year skew window to validate the skew-row direction mapping in §0.1 immediately (small notebook).
4. Re-evaluate Phase 1 falsification criteria after **6 months** of live `matrix_state_snapshots` (≈ 125 trading days × 4 tickers ≈ 500 observations per cohort) — enough for tier-1 statistical inference on the consistency-label edge.
5. Defer the historical backtest decision (upgrade UW vs source externally) until C/D results indicate whether the matrix shows promise at all.

If Phase 1 criteria 1 (consistent-signal tradeable edge) shows *any* signal in the 6-month forward window, option A, B, or **a scaled-up E** (4 tickers × 1y data-shop Option Chains ≈ $720) becomes worth the money. If it shows none, the question is moot — no point buying historical data to backtest a framework the forward data already says doesn't work.

The data-shop purchase scales worse than expected: there is **no 5y option for Option Chains**, so the maximum data-shop-purchasable per-strike history is 1 year per ticker. Scaling beyond that requires option A (UW subscription upgrade for `/api/stock/{T}/greeks` history) or option B (external vendor like ORATS).

## Backtest plan updates required (applied)

- `09 §3` time-period assumption (2018-01-01 → 2025-12-31) is **not feasible** on this account; flagged.
- `09 §4` Phase 0 spike result: this document.
- `09 §9` phasing now needs a "Phase 0.5" notebook for the skew-only validation that doesn't require the multi-year window.

## Followup probes (not run yet)

A second spike should verify the history depth for endpoints not covered here:

| Endpoint | Likely depth | Importance |
|---|---|---|
| `/api/stock/{T}/realized-volatility` | unknown — UW's RV products may have different limits | high — needed for strict VRP |
| `/api/stock/{T}/interpolated-iv` | unknown | high — IM deriver and proxy VRP |
| `/api/stock/{T}/volatility/term-structure` | unknown | high — term-state classifier |
| `/api/option-trades/flow-alerts` | depends on UW tier | medium — flow direction reading |

Worth a 30-min follow-up spike before finalizing the historical-vs-forward decision.
