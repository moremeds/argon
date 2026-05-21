# 13 — Backtest design (L1 cross-sectional + L2 per-signal)

**Goal anchor:** doc 00. This document specifies the backtesting infrastructure that lets us *verify* the four guardrails on our own data — not replicate the paper.

## Why two levels

There are two fundamentally different questions a backtester can answer; both matter and they share infrastructure.

| Level | Method | Question it answers | Guardrails it informs |
|---|---|---|---|
| **L1 — Cross-sectional signal validation** | Monthly cross-sections → decile sort on signal → forward-return spread → residualize against RV−IV → apply TC | "Does signal X earn anything *beyond* RV−IV after costs?" | 1 (redundancy), 3 (firm-level gap), 4 (TC on signals) |
| **L2 — Per-signal trade backtest** | Every signal trigger → simulate the trade-plan's actual recommended strategy (debit spread, iron condor, etc.) → mark to realized chain or synthetic price → apply spread cost at entry+exit | "Does our actual *product* recommendation make money?" | 2 (signals on product surface), 4 (TC on product surface) |

L1 is the paper's experiment. L2 is our product-correctness check. L1 ships first because it earns the right to make pruning decisions. L2 follows because it audits whether what we ship to users survives realistic frictions.

## L1 — Cross-sectional backtester

### 1.1 Module layout

```
src/uw_scan/research/backtest/
  ├── __init__.py
  ├── universe.py        # share-code-10/11 + ≥6mo history (shared with notebook)
  ├── returns.py         # forward-return providers (stock + synthetic straddle)
  ├── portfolios.py      # decile sort + long-short construction
  ├── tc.py              # quoted-spread → ESPR cost overlay
  ├── runner.py          # orchestrator: (signal, dates, universe, return-engine, tc) → results
  └── persistence.py     # writes to backtest_* tables (uses backtest_repository)
```

All files target the project module-size budget (<500 lines). `runner.py` is expected to be the largest and should split if it grows past 400.

### 1.2 Forward-return providers (the coarse-to-faithful ladder)

Two implementations of a single `ForwardReturnProvider` protocol:

```python
class ForwardReturnProvider(Protocol):
    def forward_return(
        self,
        ticker: str,
        t_start: date,
        t_end: date,
    ) -> Decimal:
        """Return realized return over [t_start, t_end]."""
```

#### A. `StockReturnProvider`

- Reads `daily_ohlc` for close-to-close return
- Skips the holding period if the ticker has a dividend ex-date or split in `[t_start, t_end]` (paper's filter)
- Fast, simple, no model dependency
- **Use for:** the V1 notebook + first L1 runs to deliver Guardrail 1 verdict

#### B. `SyntheticStraddleProvider`

- At `t_start`: price an ATM straddle using `daily_ohlc.close[t_start]` (spot) and `vrp_daily.iv[t_start]` (30d ATM IV) via Black-Scholes
- At `t_end`: re-price the same contract (now T-(t_end - t_start) to expiry) using `vrp_daily.iv[t_end]` and `daily_ohlc.close[t_end]`
- Return = `(price_end - price_start) / price_start`
- **Delta-hedged variant** (recommended): subtract `(N(d1)_start * (spot_end - spot_start)) / price_start` from the raw return to remove the directional leg
- **No chain needed** — sidesteps the 5-day `option_chain_per_strike` depth wall
- **Use for:** the high-fidelity L1 runs once the V1 notebook gives a verdict; lets us re-do Guardrails 1, 3, 4 with a vol-sensitive dependent variable

**Why this proxy is honest:**

| Paper's dep var | Our proxy | Fidelity loss |
|---|---|---|
| Delta-hedged call return | Delta-hedged ATM straddle return | Skew exposure differs (call ≠ straddle), but vol exposure agrees |
| OptionMetrics chain bid-ask midpoint | BS-priced from `vrp_daily.iv` | Microstructure noise removed; level matches when IV is well-calibrated |
| Daily delta rebalancing | Closed-form delta at `t_start` | Path-dependent P&L lost; correct in expectation for ATM |

Paper's higher-order moment characteristics (MFskew, MFkurt, Rkurt) don't survive MHT anyway — exactly where the proxy's fidelity loss lives. This is the **right** approximation for the **right** experiment.

#### Why not real chain prices for older periods

We have `option_chain_per_strike` only 5 days deep. UW's API is "current snapshot + recent flow," not a historical chain corpus. Going further back requires OptionMetrics (academic) or vendors we don't have. The synthetic straddle is the structurally correct answer to this constraint.

### 1.3 Decile portfolios

Standard cross-sectional sort:

```
For each month_end t:
    Pull (ticker, signal_value) panel from data_access.get_<signal>_panel([t], universe)
    Drop tickers with NaN signal value
    Rank within cross-section; assign deciles 1..10
    For each decile d: equal-weighted forward return over [t, t + 21 trading days]
    Long-short return = decile_10_return - decile_1_return
        (sign flipped if signal direction is "sell when high")
```

**Sign-direction convention:**
- RV−IV: high → long (paper's finding: gamma is cheap when realized > implied)
- IV-slope: high → short (steep negative-skew premium is priced)
- Most other paper signals: documented in `03-methodology.md` Appendix A

**Holding period:** 21 trading days (≈ 1 month). Matches paper's monthly cross-section cadence.

### 1.4 Transaction-cost overlay

**Non-negotiable from day 1.** All L1 outputs report gross and net columns side-by-side.

```python
class TcOverlay:
    def cost(
        self,
        ticker: str,
        t: date,
        leg: Literal["stock", "atm_straddle"],
        notional: Decimal,
        ratio: float,  # paper's 30% baseline
    ) -> Decimal:
        ...
```

**For stock leg:** `cost = notional * 0.0001` (1 bp/side, basically free).

**For ATM-straddle leg:** quoted spread is estimated from a calibrated curve `qspread = κ(IV, dte, spot)`. We have ~5 days × 103 tickers of `option_chain_per_strike` — enough for a one-shot regression that gives a usable QSPR-vs-IV curve. Then:

```
cost = ratio * qspread(ATM, 30d, spot_t) * notional
```

Applied at **both entry and exit** (round-trip). Default `ratio = 0.30` per paper; reports also generated at 0.50 and 1.00 for sensitivity.

### 1.5 Persistence (per project rules — analytical results land in DB)

Migration: `storage/migrations/051_backtest.sql`.

```sql
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id        UUID PRIMARY KEY,
    universe_spec JSONB NOT NULL,   -- {watchlist_version, ≥126_days_threshold, type='CS'}
    date_range    DATERANGE NOT NULL,
    signal_list   TEXT[] NOT NULL,
    tc_params     JSONB NOT NULL,   -- {ratio, kappa_calibration_date}
    return_engine TEXT NOT NULL,    -- 'stock' | 'synthetic_straddle' | 'synthetic_straddle_delta_hedged'
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backtest_portfolios (
    run_id          UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    signal          TEXT NOT NULL,
    month_end       DATE NOT NULL,
    decile          SMALLINT NOT NULL CHECK (decile BETWEEN 1 AND 10),
    n_constituents  INTEGER NOT NULL,
    ret_gross       NUMERIC(18, 8) NOT NULL,
    ret_net         NUMERIC(18, 8) NOT NULL,
    PRIMARY KEY (run_id, signal, month_end, decile)
);

CREATE TABLE IF NOT EXISTS backtest_summary (
    run_id          UUID NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    signal          TEXT NOT NULL,
    alpha_gross     NUMERIC(18, 8) NOT NULL,
    alpha_net       NUMERIC(18, 8) NOT NULL,
    alpha_resid     NUMERIC(18, 8),    -- alpha after RV−IV residualization
    t_stat_net      NUMERIC(18, 6),
    sharpe_net      NUMERIC(18, 6),
    n_months        SMALLINT NOT NULL,
    PRIMARY KEY (run_id, signal)
);
```

New repository file: `src/uw_scan/storage/backtest_repository.py` (per the [feedback_repository_split_threshold](.) rule — never extend `repository.py`).

### 1.6 What an L1 run produces

For each scanner signal vs a chosen `return_engine`:

| Column | Meaning | Decision it informs |
|---|---|---|
| `alpha_gross` | Long-short monthly return, no TC | Baseline magnitude |
| `alpha_net` | After 30% ESPR/QSPR per round-trip | Survives realistic frictions? |
| `alpha_resid` | After regressing on RV−IV first (predictor = residual signal) | RV−IV duplicate? (Guardrail 1) |
| `t_stat_net` | Newey-West HAC t-stat, 3 lags | Statistical confidence (wide CIs given 12-month sample) |
| `sharpe_net` | Annualized | Risk-adjusted return |

**Decision rule (Guardrail 1):**
- `alpha_resid ≈ 0` AND `alpha_gross > 0` → signal is an RV−IV duplicate. **Drop or replace.**
- `alpha_net <= 0` → signal does not survive realistic TC. **Drop or document as research-only.**
- `alpha_resid > 0` AND `alpha_net > 0` → signal survives both filters. **Keep.**

## L2 — Per-signal trade backtester

L2 is gated by L1 + Phase 2 (matrix-state backfill). Sketch only here; full design in a future doc once L1 produces a verdict.

### 2.1 Concept

```
For each (signal, ticker, trigger_time t) in historical scanner output:
    Pull the trade-plan that the scanner / Trade Insights AI would have recommended at t
    (debit spread, iron condor, calendar, etc.)
    Simulate trade entry: pay 0.30 * quoted_spread per leg
    Mark P&L over the trade-plan's holding period using:
        - real chain prices if t > 2026-05-13 (chain corpus exists from this date forward)
        - synthetic prices (BS + vrp_daily.iv path) otherwise
    Apply exit transaction cost
    Persist to backtest_trades
```

### 2.2 Why this is harder than L1

- Requires `scanner` output to be persisted historically — `signal_hits` currently has only 3 days. Either backfill by replay or accept go-forward-only.
- Trade plans are tree-structured (legs, strikes, expirations) — not just a scalar signal value. Persistence schema is more complex.
- For pre-2026-05-13 trades, we are using a synthetic chain. The fidelity loss compounds across the multi-leg structure.

### 2.3 What L2 will eventually answer

| Guardrail | L2 contribution |
|---|---|
| 2 (which 2 of 46 survive MHT) | Audit current Trade Insights AI / scanner ranking weights — are RV−IV and IV-slope first-class? |
| 4 (TC on product surface) | Show realized trade P&L net of realistic spread — the only number worth showing in a UI |

## Universe and look-ahead rules (shared with L1 and the notebook)

These conventions apply to every backtest output. They live in `universe.py`.

### Universe

```python
def get_universe(month_end: date) -> list[str]:
    """Return list of tickers eligible at this month-end."""
    return [
        t for t in watchlist
        if massive_ticker_type(t) == 'CS'           # share-code-10/11 equivalent
        and vrp_daily_history_length(t, month_end) >= 126  # ≥ 6 trading months
    ]
```

Drops ETFs (SPY, QQQ, IWM), indices (SPX), and ADRs. The drop list is logged in the run's `notes`.

### Month-end

Last trading day of each calendar month per NYSE calendar. If a ticker has no `vrp_daily` row that day, fall back to the most recent prior day within a 3-trading-day window; otherwise drop that (ticker, month).

### Sign-flip view (Step 0 prerequisite)

```sql
-- storage/migrations/049_v_rv_iv_paper_sign.sql
CREATE OR REPLACE VIEW v_rv_iv_paper_sign AS
SELECT ticker, market_date, rv, iv, (rv - iv) AS rv_minus_iv
FROM vrp_daily;
```

All L1/L2 code reads `v_rv_iv_paper_sign.rv_minus_iv`, never `vrp_daily.vrp`.

### Look-ahead bias

- Every signal value at month-end `t` is computed using **only data available on or before `t`**.
- Forward returns are over `[t, t + 21 trading days]`, all data referenced is on or after `t`.
- For firm characteristics from `/v2`/`/vX` (Phase 3), filter `WHERE filed_date <= t`, NOT `period_end <= t` — this is the most common source of look-ahead in firm-data backtests.

### Survivorship bias

The watchlist is curated (current names). Tickers removed from the watchlist over the 12-month window vanish from the panel. With 12 months and a stable watchlist, this is small but real. **Flag every L1 output** with `n_tickers_at_t_start vs n_tickers_at_t_end` in the run notes.

## Critical-path execution plan

The full sequence from current state to L1 verdict on Guardrail 1:

| Step | Output | Effort |
|---|---|---|
| 0. Migration `049_v_rv_iv_paper_sign.sql` (sign-flip view) | 1 SQL file | 10 min |
| 1. `data_access.py` Phase 1 — interface from doc 10 | 1 Python file | 2-3 hr |
| 2. `backtest/universe.py` + `tc.py` + minimal QSPR calibration | 3 files | 2 hr |
| 3. `backtest/returns.py` — StockReturnProvider only | 1 file | 1 hr |
| 4. `backtest/portfolios.py` + `runner.py` | 2 files | 2 hr |
| 5. Migration `051_backtest.sql` + `backtest_repository.py` | 2 files | 1 hr |
| 6. Notebook V1: A/B diagnostics + L1 backtest run (StockReturn engine) | 1 .ipynb | 2-3 hr |
| 7. Write `08-redundancy-audit-results.md` from notebook output | 1 doc | 1 hr |
| **Total to first verdict** | | **~13 hr** |

The synthetic-straddle engine (Step 8), Phase 2/3 (which gate Guardrails 3/4 on novel signals), and L2 follow if the V1 verdict is decision-worthy.

## Tradeoffs and explicit non-claims

- **12-month window = one regime.** All Guardrail 1 conclusions are conditional on the 2025-05 → 2026-04 vol environment. We document this in every output.
- **Newey-West t-stats with 12 monthly observations are wide.** We report them honestly; we do not apply the paper's BH-FDR 5% MHT cutoff (which assumes 27 years of data).
- **Synthetic straddle ≠ delta-hedged call.** Skew exposure differs. We document the proxy in every L1 output.
- **103-ticker universe ≠ 2,000-ticker universe.** Confidence intervals on alpha are wider; sector-level results are not robust.
- **No claim of statistical significance** that exceeds what 12 cross-sections support. The output is **directional** ("this signal looks redundant"), not **conclusive** ("this signal has zero alpha at 95% confidence").

## What this design explicitly does *not* try to do

- Reproduce paper's IPCA estimator (Pruitt EM)
- Reproduce paper's Bootstrap Wald test (B = 1000)
- Apply BH 5% FDR MHT
- Build the 46-characteristic panel
- Produce publishable academic numbers

The deliverable is **decision input** for the unusual-whales signal stack, not a publishable academic study.
