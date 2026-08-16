# Which UW endpoints honour `?date=` — measured, not assumed

**Date measured:** 2026-08-16 · **Ticker:** AAPL · **Dates compared:** 2026-08-11 (A) vs 2026-08-13 (B) vs undated
**Reproduce:** `uv run python docs/research/_scripts/2026-08-16-probe-replay-date-matrix.py`
(needs `UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1` for the API key)

## Method — and why the obvious method is wrong

An endpoint is replay-safe **only if `sha256(body_A) != sha256(body_B)`**.

Two failure modes make the naive check useless, and both nearly fooled this
investigation:

1. **A 404 reads exactly like "the provider aged the data out."** An earlier probe
   guessed `/stock/{ticker}/...` and got 404 on everything. The correct paths carry
   an `/api` prefix. Concluding "not recoverable" there would have been wrong.
   This probe now drives every URL from `uw_scan.api.endpoints.REGISTRY` so a path
   cannot be guessed.
2. **HTTP 200 with a full row set does not mean the date was honoured.** Three
   endpoints below return 200 and plausible rows for *any* date — the same rows
   every time. Writing those under a past `market_date` would stamp today's numbers
   as history. That is fabrication, and CLAUDE.md forbids it outright, so the
   refusal is encoded in `uw_scan/pipeline_replay_policy.py` rather than left to
   reviewer discipline.

## Result

| Endpoint | A (08-11) | B (08-13) | undated | Verdict |
|---|---|---|---|---|
| `volatility/term-structure` | a65c52cd8f | 285f261aaf | 2f6ab5b124 | **HONORS** |
| `interpolated-iv` | 38684a68d4 | cb3fc0a028 | b68e04694c | **HONORS** |
| `greek-exposure/strike-expiry` | 82a1130631 | 055e1c7de0 | da0e7b0a40 | **HONORS** |
| `spot-exposures/expiry-strike` | 3dc20610ac | 9c7a69a89e | 32bd82a25c | **HONORS** |
| `greeks` | aa131ec410 | fd4fe2c357 | 36c8d196af | **HONORS** |
| `oi-per-strike` | 44fc8a2f45 | 133e5315f8 | 9a94573901 | **HONORS** |
| `oi-change` | acf463dcd7 | 59a078e495 | 54c9e41655 | **HONORS** |
| `max-pain` | cf7cc7033a | eded1e5f78 | 229dcac09f | **HONORS** |
| `option-contracts` | 7bfc904c77 | 42389e1f43 | 2a7e8faddd | **HONORS** |
| `darkpool/{ticker}` | 70b66ed61e | 48330c4f3a | 1fa7c61836 | **HONORS** |
| `volatility/stats` | cedb8670f5 | b825e4ba3f | c253cdea02 | **HONORS** |
| `iv-rank` | 2f6cfbcf8f | 891a8e34eb | 5322667924 | **HONORS** |
| `greek-exposure/expiry` | 8202c7d4f8 | bd7c9f3b77 | 5380e84753 | **HONORS** |
| `screener/stocks?ticker=` | 9421f4638e | 3931791428 | 1abaea7c44 | **HONORS** |
| `option-trades/flow-alerts` | 259ecde32b | 8fb046bc07 | 21243dd2d6 | **HONORS** |
| `shorts/{ticker}/data` | 71d58bc350 | 71d58bc350 | 71d58bc350 | **IGNORES** |
| `stock/{ticker}/options-volume` | 59d1552e57 | 59d1552e57 | 59d1552e57 | **IGNORES** |
| `shorts/{ticker}/interest-float/v2` | 9415c845e7 | 9415c845e7 | 9415c845e7 | **IGNORES** |

## Corrections to the round-1 plan

`docs/superpowers/plans/2026-08-16-historical-replay-backfill.md` was written from a
narrower probe. Two of its claims are wrong:

- It lists `fetch_flow_alerts` as **IGNORES date** and refuses it. Measured here it
  **HONORS**. This does not change any action — `flow_events` was never a gap
  (122–161 tickers present on all four outage days, captured by the independent
  uw-alpha event-log path) — but the refusal reason in the plan is not accurate.
- It does not cover `screener/stocks`, which feeds `pcr_history`. That endpoint
  **HONORS** date, so `pcr_history` is recoverable and is included in the replay.

## Not probed

`fetch_realized_volatility` and `fetch_skew` return a trailing SERIES that already
spans the outage, so they need no date param — `risk_reversal_skew_history` and
`realized_volatility_history` are both already at 170/170 for 08-11..14 and are
excluded from the replay to avoid spending budget on healthy tables.
