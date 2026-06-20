# Option surface capture — durable full-chain IV/greeks grid (+ xenon IB canary)

Status: design approved 2026-06-19. Build order: **this spec first** (Spec A), before
the VRP markout (Spec B, `2026-06-19-vrp-harvest-markout-design.md`).

## Problem

Every per-name vol-surface experiment we might want — SVI/SSVI smile fits, the
per-strike "vol dislocation" residual (`listed_iv − fitted_iv`), smile-curvature
regime signals — needs a panel of **per-(ticker, expiry, strike) IV** with enough
historical dates to mark out forward. We do not have it, and **we cannot buy it**:

- UW returns `403 historic_data_access_missing` for per-strike greeks/IV beyond
  ~30 trading days (verified: `docs/research/six-dimension-matrix/09-backtest-plan.md`,
  `reviews/2026-05-15-uw-history-spike.md`). Only the single 25Δ risk-reversal series
  has ~1y depth.
- The one table that *does* hold a strike grid, `greeks_by_expiry_strike`, has
  `PK (run_id, …)` with `run_id REFERENCES scan_runs(run_id) ON DELETE CASCADE`
  (`migrations/001_s1_core_tables.sql:212-238`). It is run-scoped and cascade-deleted,
  so it never accumulates — it sits ~30 days deep at most.
- `iv_smile_snapshots` is a thin derived view (~5 trading days), rebuilt on demand.

This is a **one-way door**. Whatever strikes/expiries we do not capture tonight, we
can never re-acquire — there is no vendor and no price at which 2026's deep-OTM smile
is available in 2027. Under-capturing is permanently irreversible; over-capturing costs
only disk. The user chose **full chain, no bounds**.

## Goals

1. A **durable** table that accumulates a **full-chain** per-strike IV/greeks grid for
   every watchlist ticker, one snapshot per trading day, never purged.
2. A nightly job that populates it from the only feasible bulk source — UW `/greeks`.
3. A small **IB ground-truth canary**: a daily ATM IB-vs-UW IV cross-check via xenon's
   read-only query API, so we learn early if UW's computed IV drifts from the broker's.

## Non-goals (this spec)

- No smile/surface fitting (SVI/SABR/SSVI), no dislocation residual, no curvature signal
  — those are downstream experiments gated on this table accumulating months of depth.
- No table partitioning yet (documented as a future option below).
- No xenon leg-pricing / intraday / WS integration — documented as future reference only.

## Why UW is the capture source and xenon is not

xenon's read-only query API (`xenon/docs/reference/readonly-query-api.md`) is a
**single-contract scalpel**: `GET /options/greeks` returns one contract per call, each
backed by a short-lived subprocess that subscribes `reqMktData(snapshot=True)`, waits
~1–3 s for IB to compute greeks, and cancels. There is no bulk chain-greeks endpoint.

| Source | Call granularity | Calls/night for full chain | Feasible |
|---|---|---|---|
| UW `/greeks` | per (ticker, expiry) → 400+ strikes/response | **~2,100** (117 tickers × ~18 expiries) | ✅ normal nightly batch |
| xenon `/options/greeks` | per single contract | **~1.26 M** subprocess IB snapshots | ❌ IB line/pacing limits → days, not a night |

So UW is the firehose and the only viable full-chain source. xenon's value is
**IB-native ground truth on a few targeted contracts** (the canary, §3), where one call
per ticker is cheap and high-value.

## Components

### 1. Durable table `option_surface_grid_daily`

New migration. Schema (schema `uw_scan`):

| Column | Type | Notes |
|---|---|---|
| `ticker` | text | watchlist symbol |
| `market_date` | date | capture session date (ET) |
| `expiry` | date | option expiry |
| `strike` | numeric | option strike |
| `call_iv` | numeric null | UW `call_volatility` |
| `put_iv` | numeric null | UW `put_volatility` |
| `call_delta`,`put_delta` | numeric null | per-side delta |
| `call_gamma`,`put_gamma` | numeric null | per-side gamma |
| `call_vega`,`put_vega` | numeric null | per-side vega |
| `call_theta`,`put_theta` | numeric null | per-side theta |
| `call_vanna`,`put_vanna` | numeric null | per-side vanna (UW-sourced) |
| `call_charm`,`put_charm` | numeric null | per-side charm (UW-sourced) |
| `underlying_spot` | numeric null | EOD spot — from the watchlist card, **not** the `/greeks` payload |
| `source` | text | `'uw_greeks'` (canary may stamp others later) |
| `inserted_at` | timestamptz | row write time, `DEFAULT now()` |

> **`/greeks` payload reality (verified against `models/greeks.py:GreeksRow`):** the UW
> `/greeks` endpoint carries per-side IV + greeks but **no open interest and no underlying
> spot**. So there are no `*_oi` columns (OI lives in the chain/OI endpoints and is
> derivable later), and `underlying_spot` is stamped from `repo.list_watchlist_cards()`
> (`card.spot`) at capture time. Greeks are stored per-side exactly as `GreeksRow` exposes
> them (`rho` is omitted — never consumed downstream). The irreplaceable datum is `*_iv`
> (+ spot for moneyness); greeks are recomputable and kept only for convenience.

**PK `(ticker, market_date, expiry, strike)`.** **No `run_id`, no FK, no cascade** —
this is the load-bearing fix. The table is append/upsert-per-day and **never** deleted
by scan-run lifecycle. Idempotent upsert (`ON CONFLICT (ticker, market_date, expiry,
strike) DO UPDATE`).

Retention: **keep indefinitely.** (Monthly partitioning is a documented future option
under "Scaling", not built now.)

### 2. Nightly capture job `option_surface_capture`

New module `src/uw_scan/worker/jobs/option_surface_capture.py`, wired into
`worker/scheduler.py` to run post-close (after the EOD spot settles, before the nightly
vol rollup). Per watchlist ticker:

1. Enumerate **all** listed expiries (reuse the existing expiry source —
   `fetch_option_contracts` / the chains enumerator already used by
   `skew_swing_greeks.py`).
2. For each expiry, call the existing `fetch_greeks(client, repo, run_id, ticker, expiry)`
   (`sources/uw.py:335`) — returns every strike for that expiry in one response.
3. Upsert all rows into `option_surface_grid_daily` via a new storage method
   (`storage/volatility_v2.py` mixin or a dedicated `storage/option_surface.py`).

Full chain, **no strike clip, no DTE cap.** ~2,100 UW calls/night, spread across the two
UW workers and rate-limited like every other UW fetcher. The job reuses the
already-present per-expiry fetcher — no new UW surface.

**run_id is for UW call accounting only.** `fetch_greeks(…, run_id, …)` logs provider
usage against a `scan_run`, so the job opens a lightweight scan_run for accounting. The
durable grid **does not reference run_id** — that decoupling is the whole point (§1). Do
not add a `run_id` FK to `option_surface_grid_daily`.

### 3. xenon ATM IB-vs-UW validation canary

New small job `option_surface_iv_canary` (separate from §2 so a xenon/IB outage never
blocks the capture). Per watchlist ticker, for the **front 2 expiries**:

1. Pick the nearest-ATM strike from the captured grid.
2. Call xenon `GET /options/greeks?symbol&expiry&strike&right` (both C and P) →
   IB `impliedVol`.
3. Diff IB `impliedVol` against the UW `call_iv`/`put_iv` at the same contract.
4. Persist to a tiny `iv_source_validation` table (`ticker, market_date, expiry, strike,
   right, uw_iv, ib_iv, abs_diff, captured_at`).
5. Emit a **WARN** (health surface) when the median `abs_diff` across the watchlist
   exceeds a threshold (default **0.02** = 2 vol points; configurable).

~300 xenon calls/night. Auth: `X-API-Key: $XENON_QUERY_API_KEY` (localhost bypass on the
mini, where xenon runs); base URL via a new `XENON_QUERY_API_URL` env
(default `http://127.0.0.1:8421`). Off-hours xenon returns frozen last-session greeks,
which is the correct comparand for an EOD canary.

### 4. Config / env

- `OPTION_SURFACE_CAPTURE_ENABLED` — kill switch; default **true**.
- `OPTION_SURFACE_IV_CANARY_ENABLED` — canary kill switch; default **true** (degrades to
  skip, never blocks §2).
- `XENON_QUERY_API_URL` — default `http://127.0.0.1:8421`.
- `XENON_QUERY_API_KEY` — bearer for non-localhost; unused under localhost bypass.
- `OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD` — default `0.02`.

Worker env freezes at fork (project standing rule) — rotating any of these requires
restarting the capture worker.

## Data flow

```
nightly (post-close)
  ├─ option_surface_capture:  watchlist → expiries → UW /greeks (per expiry)
  │                            → upsert option_surface_grid_daily   [DURABLE]
  └─ option_surface_iv_canary: watchlist → ATM strike → xenon /options/greeks (IB)
                               → diff vs captured UW IV → iv_source_validation + health WARN
```

## Failure handling

- **Partial chain:** a per-expiry UW failure logs and continues to the next expiry; the
  day's row set may be incomplete but is never rolled back (a partial grid beats none —
  irreversible data). Capture status recorded per ticker.
- **UW rate limit / 429:** existing UW client backoff applies; the job is restart-safe
  via idempotent upsert (re-running the night is a no-op on already-captured rows).
- **xenon/IB down:** the canary skips (logs WARN "canary unavailable"); §2 is unaffected.
- **DB isolation:** writes go through the standard `Repository`; the three-tier tripwire
  applies unchanged.

## Testing

- Unit: upsert idempotency (same day twice → no dup, fields updated); schema round-trip.
- Unit: capture job with a stubbed `fetch_greeks` returning a multi-expiry fixture →
  asserts full-chain rows land, no strike clipping, partial-failure isolation.
- Unit: canary diff math + threshold WARN, with stubbed xenon responses (populated,
  `greeks: null`, IB unreachable).
- Integration (pytest-postgresql): migration applies; a two-day capture accumulates
  (proves no cascade-delete) — the explicit regression guard against the
  `greeks_by_expiry_strike` trap.
- Live (marked `live`, opt-in): one real UW ticker fetch + one real xenon canary call.

## Acceptance criteria

1. Migration creates `option_surface_grid_daily` with **no cascading FK**; a second-day
   capture leaves day-one rows intact.
2. `option_surface_capture` writes full-chain (all expiries, all strikes) for the
   watchlist in one nightly run within the UW rate budget.
3. `iv_source_validation` populates and a forced IV divergence raises the health WARN.
4. Both jobs honor their kill switches and degrade independently.

## Scaling (future, not built now)

- Monthly range partitioning of `option_surface_grid_daily` once it crosses ~tens of GB.
- A "first-N-DTE only" fast path if nightly UW budget ever tightens (explicitly rejected
  for v1 — full chain is the point).

## Future reference — xenon read-only query API

Captured here per the decision to keep xenon's API documented for later use. Source of
truth: `xenon/docs/reference/readonly-query-api.md`. Relevant surfaces:

- `GET /options/greeks?symbol&expiry&strike&right` → IB `modelGreeks`
  (`impliedVol, delta, gamma, vega, theta, undPrice`) + NBBO bid/ask for **one** contract.
  Frozen market-data type → returns last-session greeks off-hours. Used by §3.
- `GET /market-depth` → L2 snapshot; also returns the qualified option `conId`
  (which `/contract/qualify` cannot resolve for options).
- `GET /orders/quote?ticker&con_id` → single-contract live bid/ask/mid.
- `POST /ws-ticket` → realtime WS feed ticket.

**Future roles (not in scope now):** targeted IB leg-pricing for option-wizard trade
construction; intraday ATM surface snapshots; an IB-native greeks source for specific
contracts where broker fidelity matters more than chain breadth. All are scalpel uses —
never full-chain bulk, for the throughput reason in "Why UW … and xenon is not".
