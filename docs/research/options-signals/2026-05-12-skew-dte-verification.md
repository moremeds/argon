# Skew DTE verification — `volatility.skew_25d` is currently at nearest expiry, NOT 30 DTE

**Date:** 2026-05-12
**Context:** S2.4 of the watchlist UI rework plan. The card spec asks for a
`skew_25d_30dte` field — 25Δ risk reversal at ~30 days-to-expiry, the industry
standard skew measurement (see `2026-05-12-spec-pct-and-skew-dte-research.md`).

## What the existing pipeline does today

Traced through:

- `src/uw_scan/pipeline.py:73-82` picks `nearest_expiry` from `fetch_term_structure`
  results (sorted by expiry ascending — typically the next Friday weekly, 1–14 DTE).
- `fetch_skew(client, repo, run_id, ticker, expiry_str)` fetches the 25Δ RR chain
  at **that one** expiry only.
- `Repository.upsert_skew_rows` persists into `risk_reversal_skew_history`
  keyed by `(ticker, market_date, delta, expiry)`.
- `Repository.fetch_skew_latest(ticker)` returns the latest row filtered by
  `delta = 25`, ordered by `market_date DESC` — no DTE filter.
- `_build_volatility_profile` in `reports/single_stock.py:175` writes that
  `risk_reversal` directly to `VolatilityProfile.skew_25d`.

Net effect: `volatility.skew_25d` is the 25Δ RR at the **nearest weekly expiry**,
not at 30 DTE.

## Why we are NOT implementing the interpolation now

The plan offered an interpolation helper (`pick_skew_at_30dte`) that would
straddle target_dte between two expiries. But:

- The current pipeline only fetches **one** skew chain per run (at the nearest
  expiry). The DB has nothing to interpolate over for the next-30-DTE bracket.
- Adding a second `fetch_skew` call at a 30-DTE-target expiry is the right fix,
  but it lives at the source-fetch layer, not at the assembler layer where the
  interpolation helper would run. Implementing the helper without the fetch is
  half a solution.
- Three similar lines is better than a premature abstraction. The interpolation
  module would be dead code until S2's source-fetch layer is extended.

## What lands in the card for now

The card's `skew_25d_30dte` column will be populated with the existing
`volatility.skew_25d` value — i.e. the **nearest-expiry 25Δ RR**, not the
30-DTE 25Δ RR. The card spec is amended (in the watchlist rework spec) to
acknowledge this approximation with a tooltip:

> "25Δ RR at nearest weekly expiry (typically 1–14 DTE). 30 DTE target is
> the industry standard but not yet implemented end-to-end; tracking issue
> TBD."

## Tracking work

Future enhancement: add a second `fetch_skew(..., target_30dte_expiry)` call
in `pipeline.run_single_stock` and pick its 25Δ RR row. Defer until after the
watchlist UI ships — the approximation is acceptable for v1.
