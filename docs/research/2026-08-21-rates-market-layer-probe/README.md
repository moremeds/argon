# Rates market-layer source probe — 2026-08-21

Probes the three publishers behind the rates causal roles that resolve to nothing today:
`supply`, `positioning`, `plumbing`.

**Reproduce:** `uv run python scripts/research/rates_market_layer_probe.py`

Writes `probe.json`. Every number in `VERDICT.md` comes from that file.

## What it asks

| Role | Publisher | Question |
|---|---|---|
| `plumbing` | FRED | Do the four candidates exist at the assumed frequency, and does each clear FRED's 2000-vintage ceiling under the window `request_window()` actually builds for it? |
| `supply` | TreasuryDirect `TA_WS/securities/auctioned` | Is there a publication instant? Do the date parameters work? Is the security term a sufficient series identity? |
| `positioning` | CFTC TFF futures-only (Socrata `gpe5-46if`) | Is there a release field? Is Socrata's `:created_at` a real release instant? How wrong is the `obs_date + 3 days` rule the existing client uses? |

## Why the vintage question is not a formality

`request_window()` splits on the contract's own `frequency`: a daily series gets
`observation_start == realtime_start == DAILY_VINTAGE_START`, anything else gets the
unbounded vintage window. FRED rejects a request whose window spans more than 2000
vintage dates with an HTTP 400 and no rows — the failure MC2 Task 9 was written to fix.
So a candidate's frequency is not cosmetic: get it wrong and the series silently receives
the wrong window.

The probe therefore builds the window the ingest would build and requests it, rather than
asking for metadata and assuming.

## Files

- `probe.json` — full machine-readable result
- `VERDICT.md` — the rulings and what they change
