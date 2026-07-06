# Candidate: dealer charm/vanna per-strike positioning signal

**Date:** 2026-07-06 · **Status:** UNVALIDATED HYPOTHESIS · **Effort:** M
**Basis:** [INFERRED] from a data-in-hand audit. Confidence MED. Not yet tested.

## The gap (verified)

`uw_scan.option_surface_grid_daily` captures `call_vanna, put_vanna, call_charm, put_charm` (plus gamma/delta) **per strike per expiry, nightly, whole chain, no clip** — written by `worker/jobs/option_surface_capture.py` since ~2026-06-23. Confirmed: `storage/option_surface.py` only ever reads the ATM strike's `call_iv/put_iv` for the IB-vs-UW canary. The vanna and charm columns are **read by nothing** except row-count freshness checks. Every consumer of vanna/charm elsewhere pulls the UW *aggregate* greek-exposure endpoint — never this durable per-strike grid.

## Hypothesis

GEX is gamma-only. Two dealer-hedging channels go unmeasured:
- **Charm** (∂delta/∂time): aggregate signed dealer charm across the chain predicts mechanical delta-rehedging drift into expiry — strongest OPEX week, high-OI single names.
- **Vanna** (∂delta/∂vol): net vanna predicts direction/magnitude of dealer hedging when IV moves — the vol-spot feedback that amplifies or dampens moves.

## Cheap validation

For each (ticker, market_date): sum OI-or-gamma-weighted net charm and net vanna per near expiry. Regress next-day and cumulative-into-expiry underlying drift on net charm; regress IV-conditional drift on net vanna. Cross-sectional across the whole watchlist gives N fast even on short history.

## Urgency (why this can't wait)

Only ~9 sessions banked so far, and **per-strike history is unrecoverable from UW** — you cannot backfill it. The derivation/persistence job should start accruing a durable daily rollup **now**, even though statistical power for validation accrues forward over weeks. Design the signal now; test it in a month.

## Bundled second signal (same grid, ~free)

Durable ATM **term-structure slope** — reconstruct ATM-IV(dte) per (ticker, date) from the grid, 30d–90d slope + curvature. The dedicated `iv_term_snapshots`/`interpolated_iv_snapshots` tables are run_id-ephemeral (CASCADE), so this grid is the *only* place term-structure history survives. Explicitly NOT the SVI cross-strike smile fit (parked-negative) and NOT skew direction (closed-negative) — this is the along-expiry slope.

## Reproduce

Derivation script TBD → `scripts/research/charm_vanna_positioning.py` (read `option_surface_grid_daily`, write rollup + markout to a durable artifact under `docs/research/`).
