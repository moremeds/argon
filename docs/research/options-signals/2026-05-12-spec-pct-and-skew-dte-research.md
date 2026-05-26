# Research note: "Spec %" definition and Skew DTE constant

**Date:** 2026-05-12
**Context:** UW Scanner UI rework — defining card fields for the watchlist landing page before the spec was drafted. The Market Pulse reference card shows a "Spec %" gauge and a "SKEW (29d)" section. Neither is anchored to a public, canonical definition, so this note records the search and decisions.

## Question 1 — What is "Spec %"?

**Finding:** no canonical industry definition exists.

Web searches for `options analytics "spec %" speculation ratio` and `"speculation index" options flow` return:
- Generic explanations of *speculation* as a **use case** (buying calls/puts for directional bias vs. hedging) — not a quantitative metric.
- Bid/ask aggression framing: paying the ask = aggression / speculative demand; accepting the bid = passive / hedging. This is the closest standard convention.
- No reference to a published "Spec %" formula in academic or vendor docs (Fidelity, Optiver, Unusual Whales, SensaMarket, OptionAlpha, CBOE).

Market Pulse's "Spec %" gauge is therefore a **proprietary metric** of their tool. Replicating the literal number is not possible without their definition.

### Decision

Use **`aggression_pct = ask_side_premium / (ask_side_premium + bid_side_premium)`**, rendered as a circular gauge labelled **"FLOW AGGR."** (not "Spec %").

- Range: 0..1.
- Higher = more aggressive (ask-side) buying. Lower = more passive / hedging-dominated flow.
- Null when `ask_side_premium + bid_side_premium == 0` (no flow today) → gauge empty, "—".
- Uses fields already produced by `pipeline.run_single_stock` — no new UW calls, no new model changes.

The rename ("Aggression" instead of "Spec") is deliberate: the metric measures order-flow aggression on resting quotes, not speculation in any defined sense. Honest naming over visual mimicry of the reference image.

## Question 2 — Skew DTE constant

**Finding:** industry standard is **25-delta risk reversal at 30-day DTE**.

- The 25-delta risk reversal (`IV(25Δ call) − IV(25Δ put)`, or put-minus-call by convention) is the canonical OTM skew measurement. 25Δ sits in the wings of the option chain — far enough from ATM to capture directional positioning, close enough to be liquid.
- 30 days is the standard horizon (CBOE SKEW Index, VIX-related skew analytics).
- The "29d" label on the Market Pulse card is almost certainly "nearest standard monthly expiry" — monthly expiries are the 3rd Friday, typically 28–30 days out.

### Decision

Use **`skew_25d_30dte`** sourced from the existing `volatility.skew_25d` field on `SingleStockReport`. Define `SKEW_TARGET_DTE_DAYS = 30` as a constant in `uw_scan.config`. Verify the existing `volatility.skew_25d` is in fact a 25Δ RR (and at what DTE) during S0 of the implementation plan; if not, normalize there.

This removes the previously-planned pipeline extension (separate call/put IV term structure). One less change to `SingleStockReport`.

## Implications for the card spec

- `spec_pct` column → renamed `aggression_pct`.
- `pc_iv_ratio_29d` and `pc_iv_spread_29d` columns → replaced by single `skew_25d_30dte` column.
- Pipeline work surface shrinks by one item (no put/call IV term split required).

## Sources

- [Decoding Option Flow: Reading the Tape Like a Pro — SensaMarket](https://www.sensamarket.com/blogs/decoding-option-flow-reading-the-tape-like-a-pro) — ask-side aggression / bid-side passivity framing
- [Graphing the 25 Delta Risk Reversal Volatility Skew — Crypto Data Download](https://www.cryptodatadownload.com/blog/posts/bitcoin-option-risk-reversal-skew-binance-25delta/) — 25Δ RR as the standard skew measurement and rationale for 25Δ
- [What is Gamma Exposure (GEX)? — Unusual Whales](https://unusualwhales.com/faq/what-is-gamma-exposure-gex) — confirms GEX-field semantics used elsewhere in the card spec
- [How to Interpret Periscope Net Gamma Exposure — Unusual Whales](https://unusualwhales.com/information/how-to-interpret-periscope-net-gamma-exposure) — interpretation context for GEX flip / dealer hedging
