# GOAS Put-Write Delta Sweep — Design Spec

**Date:** 2026-06-23
**Branch:** `feat/goas-putwrite-delta-sweep`
**Status:** approved (design), pending implementation plan
**Type:** exploratory research backtest (not productionized)

## Goal

Find the SPY put-selling **short-put delta** (and, jointly, the **expiry tenor**) that
maximizes risk-adjusted, net-of-fee income for a Goldman Options Advisory Strategy
(GOAS)-style systematic cash-secured put-writing program over ~2006→present —
validated against GOAS's own published numbers (gross premium ≈ 7.7% annualized for
a 1-month ~15Δ SPY put; **net target 3–6% p.a.**).

The single output that matters: *which delta to sell, and is the edge robust to
volatility-skew assumptions and to historical stress regimes (2008 / 2020 / 2022)?*

## The strategy being backtested (GOAS, as described)

- Systematically sell short-dated (1–3 month) OTM index puts to collect upfront
  premium. Sell **every period regardless of vol** — the thesis is that downside
  protection is *structurally* over-bid, so the premium is persistently rich. This
  is an **always-on** short, NOT VRP-gated and NOT vol-conditioned.
- GOAS baseline ≈ "15% exercise probability" puts, strike ~4–10% OTM. (Note: "15%
  exercise probability" is the risk-neutral ITM probability N(−d2)=0.15, which is a
  *slightly* lower strike than a 0.15-delta put N(−d1)=0.15. We sweep **delta** — the
  parameter the user asked for — and calibrate skew to GOAS's published *strike +
  premium*, the observable economics, not to the prob/delta label.)
- Roll down on breach. **Captured implicitly** by re-entering at the target delta off
  the then-current (possibly lower) spot at the next cycle — economically equivalent
  to GOAS's "roll to a lower-strike new put." No separate roll state machine.
- Cash-secured / defined-risk basis (per the project's no-naked-shorts rule):
  collateral = strike × 100 per contract; max loss = (strike − credit) × 100 (assign
  and fall to zero). GOAS's 20–40% margin (leverage) version is **out of scope** here.

## The one hard constraint (data investigation result)

There is **no multi-year historical implied-vol surface / skew** available:
- Every per-strike source (`option_surface_grid_daily` mig 077, `skew_analytics_snapshot`
  mig 073, `risk_reversal_skew_history`) is **forward-accumulated and ~30 trading days
  shallow**; UW's tier 403s beyond ~30 days. The R2 lake and FMP/massive carry no
  option-level data. CBOE SKEW is not ingested.
- The only multi-year IV input is the **flat ATM constant-maturity vol index** (VIX for
  SPX/SPY) in `uw_scan.vol_index_daily`, back to 2006.

Consequence for *this* study: pricing OTM puts off flat ATM VIX **underprices** them,
and underprices **low-delta** puts *more* than high-delta (real index put skew is
steepest for deep-OTM strikes). That bias falls directly on the question being asked
("which delta is best") — it would push the apparent sweet-spot toward **higher** delta.

**Decision (user: "do as the strategy describes, see if the performance matches"):**
GOAS's published quote (1mo ~15Δ SPY put = **0.7% premium at 96.2% strike**, as of
2026-05-05) is a *real, skew-inclusive* price. To reproduce GOAS we therefore price
**with skew**: a parametric skew model calibrated to that exact quote, with **flat-vol
as the conservative floor underneath**. We run the **entire delta×tenor sweep under
both pricing modes** and report them side by side. The credible sweet-spot is the
delta that wins under *both* flat and skew pricing *and* across regimes; if they
disagree, that is flagged UNRESOLVED pending real surface data. **The historical skew
*shape* is modeled (calibrated to one recent quote), not observed — owned loudly in
every artifact.**

## Architecture

Three focused report modules + one runner, reusing the existing pure pricing
primitives. No DB schema, no worker job, no API surface (exploratory research).

```
reports/goas_putwrite_pricing.py   # skew model + delta-consistent CSP builder + calibration
reports/goas_putwrite_account.py   # GoasConfig + laddered NAV simulator + metrics + SPY benchmark
reports/goas_putwrite_sweep.py     # delta×tenor sweep harness (flat & skew, fee grid, regimes)
scripts/research/goas_putwrite_run.py  # repo/settings wiring → run sweep → write CSV traces + findings note
```

Reused as-is (pure, no I/O), from `reports/vrp_structure.py`:
`bs_price`, `bs_delta`, `strike_for_delta`, `CashSecuredPut`, `build_cash_secured_put`,
`CostModel`. From `reports/vrp_macro_drawdown.py`: `load_index_vol(repo, "SPY")` +
`INDEX_SPECS["SPY"]` (SPY spot from the equity lake with the null-date guard; VIX/100
as ATM IV; dates aligned) → the `_Loaded` series (`adj` = [(date, spot)], `rows` carry
`iv`). We use `adj` + an `iv` map only; `vrp_z` is ignored (always-on).

### Why a new account simulator (not `simulate_account`)

`vrp_macro_harvest._backtest` is entry-spaced, **one position at a time**, and the
existing `simulate_account` is VRP-z-sized and spread-structured (5 iter-4 flags).
GOAS is a **constant-size, laddered, overlapping book** (4–8 concurrent puts, 4–5 week
ramp-in) — a different accounting loop. A fresh, focused simulator is cleaner than
bending either, and stays within the module-size budget. It reuses the pure entry
builder + the model-free intrinsic settlement.

## Component 1 — pricing + skew (`goas_putwrite_pricing.py`)

**Key simplification:** a put held to expiry settles at intrinsic `max(0, K − S_T)`,
which is **vol-independent**. So skew changes (a) the strike chosen for a target delta,
(b) the entry credit, and (c) the daily mark-to-market of open positions; the **expiry
settlement and realized P&L are reused unchanged and remain intrinsic (model-free)**.

- `PutSkew(slope: float, vvix_ref: float | None = None)` — parametric downside skew.
  IV at strike K given ATM σ and spot S:
  `iv(K) = σ_atm * (1 - slope * m)` where `m = ln(K/S)` (log-moneyness, **negative**
  for OTM puts, so a positive `slope` *raises* IV as strikes fall — the observed index
  shape). Optional VVIX scaling (`slope_t = slope * vvix_t / vvix_ref`) so skew steepens
  in stress; default off (constant slope) for v1 transparency. `slope=0` ⇒ flat-vol.
- `build_csp_skew(S, atm_sigma, T, r, *, short_delta, skew: PutSkew | None) -> CashSecuredPut`
  — when `skew is None`, delegate to the existing flat-vol `build_cash_secured_put`.
  Otherwise solve the **delta-consistent** strike by bisection: find K such that
  `|bs_delta(S, K, T, r, iv(K), is_call=False)| == short_delta` (iv(K) itself depends on
  K — bisect on K over (0, S), monotone). Credit = `bs_price(S, K, T, r, iv(K),
  is_call=False)`; `max_loss = K − credit`. Return a `CashSecuredPut(K, credit, K−credit,
  (credit,))` so the downstream settlement/cost code is identical.
- `calibrate_skew(S, atm_sigma, T, r, *, target_strike_frac, target_premium_frac) -> PutSkew`
  — solve **directly on the strike+premium** (GOAS gives a strike and a premium, not a
  delta, so calibration does **not** route through the delta-targeted `build_csp_skew`).
  Fix the strike at `K* = target_strike_frac · S` (= 0.962·S) and bisect `slope` so that
  `bs_price(S, K*, T, r, iv(K*; slope), is_call=False) == target_premium_frac · S`
  (= 0.007·S) at the 2026-05-05 ATM VIX. One equation, one unknown (`slope`) — cleanly
  determined; the implied delta of `K*` falls out as a reported by-product. The
  calibrating VIX value is read once from `vol_index_daily` and **frozen as a test
  fixture** (no runtime network).

Sign/guard discipline matches `vrp_structure`: raise `ValueError` on degenerate inputs
(S/σ/T ≤ 0, delta ∉ (0, 0.5), non-converging bisection); callers skip-and-log per CI
Guardrail 2.

## Component 2 — account simulator + metrics (`goas_putwrite_account.py`)

- `GoasConfig` (frozen dataclass): `short_delta`, `dte_days` (trading-day offset),
  `cadence_days=5` (weekly), `capital=1_000_000.0`, `skew: PutSkew | None`,
  cost params (defaults from the existing `vrp_*` settings), `r` (risk-free), `multiplier=100`.
  **No management-fee field** — the fee is a deterministic downstream NAV drag (applied
  to the post-cost curve), swept over the fee grid, so the simulation runs once.
- `simulate_putwrite(loaded, cfg) -> PutWriteResult`:
  - Walk trading dates. Every `cadence_days`, open one constant-size cash-secured put at
    `cfg.short_delta`/`cfg.dte_days`, sized so each entry deploys `capital / slots`
    collateral where `slots = round(dte_days / cadence_days)`; the overlapping book
    therefore targets full deployment of `capital` at steady state. **GOAS's 4–5 week
    ramp-in is realized by natural laddered accumulation** — the book fills to `slots`
    concurrent puts over the first ~`dte_days` (≈ 4–5 weeks at 30d weekly), so there is
    no separate ramp knob. Multiple puts coexist (laddered book), matching GOAS's 4–8.
    Contracts are fractional (a research return abstraction — scale-invariant, avoids
    integer-lot lumpiness).
  - Daily NAV marks open positions at **fair value** (BS at the current ATM VIX + the
    same skew on the held strike) so theta is earned gradually and selloffs draw the
    curve down via gamma/vega — and crucially there is **no entry-day premium
    front-loading** (at entry the mark ≈ credit, so unrealized ≈ 0). The expiry
    settlement and realized P&L stay intrinsic (model-free); only the intra-life *marks*
    use the model, which is standard for an equity-curve. Falls back to intrinsic only
    when a day's IV is missing.
  - Hold each to expiry; settle at intrinsic via the existing `_settle` semantics
    (model-free) and book `net = (credit − intrinsic)·100·contracts − CostModel`.
  - Track **two ledgers** so reporting can show all three tiers: `realized_gross`
    (credit − intrinsic, no cost) and `realized_cost` (transaction costs). Build two
    daily curves: `equity_curve_gross` (pre-cost, pre-fee) and `equity_curve_costed`
    (post-cost, pre-fee). The management fee is NOT applied in the simulation — it is a
    deterministic downstream drag on the post-cost curve (`apply_fee_to_curve`, correct
    multiplicative compounding on prior-day net NAV, no day-0 charge).
  - Per-trade log (entry/expiry dates, strike, credit, iv_entry, intrinsic, net, breached, ror).
  - Returns `PutWriteResult(equity_curve_gross, equity_curve_costed, trades, span)`.
- `putwrite_metrics(result) -> dict`: from the daily NAV returns series —
  **annualized return (gross / net-of-cost / net-of-fee), annualized vol, Sharpe (rf-adj),
  max drawdown, Calmar, CVaR(5%), worst calendar month**; from trades — win rate, breach
  rate, mean credit, n trades. Both compounding (geometric on NAV) and non-compounding
  (sum of per-trade ror on fixed collateral) are reported, per the iteration-4 dual-path
  discipline.
- `spy_buy_hold(loaded) -> dict`: SPY price-return equity curve + the same metrics, as
  the benchmark. (Lake is price-only — **no dividends** — labeled as price return.)

## Component 3 — sweep harness (`goas_putwrite_sweep.py`)

- `DELTAS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)`
- `DTES = (21, 30, 42, 63)`  (≈ 1, 1.5, 2, 3 months — the GOAS 1–3 month range)
- `FEE_GRID = (0.0, 0.005, 0.010, 0.015)` (management fee p.a.; transparent grid, **not**
  an invented single number — gross is `0.0`)
- `PRICING = ("flat", "skew")`
- `run_sweep(repo, settings, *, as_of) -> SweepResult`: load SPY once; calibrate the skew
  (`calibrate_skew`); for every (delta, dte, pricing) cell run `simulate_putwrite` once
  at `mgmt_fee_annual=0`, then derive each fee level analytically from the NAV curve
  (fee is a deterministic daily NAV haircut — no re-simulation). Collect full metrics
  per cell + per-regime slices (2008, 2020-02→2020-04 COVID, 2022, and an all-calm
  aggregate). Compute the SPY buy-hold benchmark and attach the GOAS anchors (gross
  7.7% / net 3–6%). Return a structured result the runner serializes.
- **Sweet-spot selection** (reported, not auto-decided): rank cells by net Sharpe
  (primary) and Calmar (drawdown-aware); the headline pick is the delta that is top-ranked
  under **both** flat and skew pricing **and** does not catastrophically degrade in any
  single stress regime (an AC-F4-style per-regime gate). Apply iteration-4 honesty:
  de-rate, name the overfit risk, do not present a flattering corner as the answer.

## Data, window, fees

- **Underlying:** SPY only. Spot from the equity lake (`INDEX_SPECS["SPY"]`, null-date
  guard); ATM IV = VIX/100 from `vol_index_daily`. Window **2006-01-01 → present** (~20y),
  minus a 20-day RV warm-up (RV is incidental; always-on needs no vrp_z warm-up).
- **Transaction costs:** the existing `CostModel` driven by the project's standard
  `settings.vrp_cost_per_contract` / `vrp_slippage_frac` / `vrp_slippage_min` /
  `vrp_cost_round_trip` (commission scales to the 1-leg CSP; slippage = half-spread).
  These are the codebase's established cost params — cited, not invented here.
- **Management fee:** swept over `FEE_GRID`. **Gross, net-of-cost, and net-of-fee are
  reported side by side.** GOAS published no explicit fee, so we do **not** fabricate
  one: the headline simply names the fee level at which the 15Δ baseline lands inside
  GOAS's stated 3–6% net band, and shows the whole grid. If the GOAS *attachment*
  supplies a real fee schedule, it drops straight into `FEE_GRID`.

## Validation against GOAS

1. **Pricing check (frozen fixture):** the skew-calibrated 1-month put at the 2026-05-05
   VIX reproduces strike ≈ 96.2% and premium ≈ 0.7% (and, as a cross-check, ≈ 7.7%
   annualized). This is the calibration target and a unit-test assertion.
2. **Net-return check:** the backtested net result at the GOAS-like configuration
   (≈15Δ, 1-month) is compared against GOAS's 3–6% net band, with the fee grid making the
   bridge explicit. A backtest net far outside 3–6% is reported as a discrepancy to
   explain (skew assumption, cost level, or window), not silently reconciled.

## Testing

- `tests/unit/reports/test_goas_putwrite_pricing.py` — flat-vol CSP premium matches a
  hand-computed Black-Scholes value at a frozen real VIX; `strike_for_delta` round-trips
  via `bs_delta`; `build_csp_skew` is delta-consistent (recovered delta == target within
  tol); skew monotonicity (lower strike ⇒ higher IV ⇒ strictly richer credit than flat);
  `calibrate_skew` reproduces the GOAS 96.2%/0.7% quote within tolerance; `ValueError`
  on degenerate inputs.
- `tests/unit/reports/test_goas_putwrite_account.py` — on a synthetic **flat** price path
  premiums accrue and no put is breached → NAV rises by Σcredit − fees (closed form);
  a synthetic **selloff** path → realized loss is bounded by (strike − credit) per
  contract (defined risk); management-fee daily accrual matches a closed-form check;
  Sharpe / maxDD / CVaR computed on a hand-built equity curve match known values;
  full determinism (same inputs → identical output).
- Optional integration (`tests/integration/`) — `run_sweep` against the real DB, **skipped
  when `vol_index_daily` is empty** (the iteration-4 CI lesson: probe `information_schema`
  and `pytest.skip`, never hit an empty working DB).
- All fixtures use **real, frozen** values (the 2026-05-05 SPY/VIX quote; a real BS
  premium computed once) — no synthetic prices, no network at runtime.

## Artifacts (persist every trace — standing rule)

Under `docs/research/goas-putwrite/`:
- `goas-delta-dte-sweep-<date>.csv` — one row per (delta, dte, pricing, fee) cell: full
  metrics + regime slices.
- `goas-trade-log-<date>.csv` — per-trade log for the headline configuration(s).
- `goas-skew-vs-flat-<date>.csv` — the delta sweep under flat vs skew, for the ranking-flip check.
- `goas-regime-<date>.csv` — per-regime metrics for the headline cells.
- `MASTER-goas-putwrite-<date>.md` — findings note: the sweet-spot verdict, the skew
  caveat, GOAS-validation results, the exact reproduce command (`uv run python
  scripts/research/goas_putwrite_run.py` + env), and an honest de-rating.
- The runner prints the headline and writes all of the above; results land in committed
  files (exploratory-research tier of the persist-every-trace rule), not a DB table.

## Caveats owned in every artifact

- **Modeled skew shape**, calibrated to one recent quote — not observed history. The
  flat-vol run is the conservative floor; the skew run is the GOAS-faithful estimate;
  the truth is bracketed between them.
- **Constant skew slope** (VVIX scaling off by default) — skew almost certainly steepened
  in 2008/2020; a constant slope *understates* crisis put richness. Noted; VVIX-scaled
  slope is a labeled sensitivity, not the headline.
- **European cash-settle at expiry** vs GOAS's American, roll-managed book — we model the
  conservative expiry-settlement economics; early-assignment timing is not modeled.
- **Price-return SPY benchmark** (lake has no dividends) — understates buy-hold total return.
- **VIX is constant-maturity 30d** applied across 21–63d tenors — cleanest read at DTE≈30.

## Out of scope (v1)

QQQ/IWM; the 20–40% margin/leverage overlay; explicit intra-cycle roll modeling (the
re-entry already captures the economics); Monte Carlo / bootstrap robustness; any DB
table, worker job, or API/UI surface. All are clean follow-ons once the SPY delta answer
lands.

## Success criteria

1. A defensible **delta (and tenor) sweet-spot** for SPY put-writing, ranked by net
   Sharpe + Calmar, robust across **flat vs skew pricing** and across **2008/2020/2022**
   — or an explicit UNRESOLVED if the ranking flips on skew.
2. The skew model **reproduces GOAS's published 0.7%/96.2% quote** (unit-tested).
3. The net result is **placed against GOAS's 3–6%** with the fee bridge made explicit and
   no fabricated fee numbers.
4. Every result reproducible from a committed trace + the exact command (standing rule).
5. All unit tests green; `uv run ruff check` + `_lint_except.py` clean (CI parity).
