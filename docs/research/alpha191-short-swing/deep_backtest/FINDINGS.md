# Alpha191 momentum — deep backtest findings (SP500 + NDX100 single names)

Checked at: `2026-07-06`. Engine: `scripts/research/alpha191_deep_backtest.py`
(non-overlapping rebalance, quintile L/S, daily mark-to-market, 10 bps/unit-turnover cost).
Universe: 510 SP500+NDX100 current members with deep apex history.
Window: 1997-01-01 → 2026-07-02 (7,422 trading days). Reproduce cmd in `report.md`.

## Headline (full-sample, dollar-neutral quintile L/S, net of costs)

| config | CAGR | Sharpe | maxDD | up-years |
|---|---:|---:|---:|---:|
| buyhold_eqw (beta baseline) | +15.1% | **+0.81** | −51% | — |
| reversal_5 / 5d | +5.5% | +0.62 | −27% | 20/30 |
| reversal_5 / 10d | +4.2% | +0.50 | −26% | — |
| reversal_10 / 10d | +2.9% | +0.36 | −30% | — |
| lt_mom_12_1 / 21d | −3.1% | −0.25 | −75% | — |
| fade_10d | −3.4% | −0.36 | −67% | — |
| lt_mom_6 / 21d | −5.2% | −0.47 | −82% | — |
| lt_mom_3 / 21d | −4.8% | −0.48 | −80% | — |
| momentum_15d | −5.5% | −0.61 | −84% | — |
| baseline_mom10 / 10d | −7.3% | −0.79 | −91% | — |
| momentum_10d | −7.5% | −0.84 | −92% | — |
| **momentum_5d** | **−10.7%** | **−1.23** | −97% | 4/30 |

## What the data says (robust, survivorship-immune)

1. **Short-horizon momentum L/S loses money persistently.** `momentum_5d` is
   negative in **26 of 30 years** (Sharpe −1.23). The dominant short-horizon
   effect in liquid US names is **reversal, not momentum**. This is too large and
   too persistent to be a survivorship artifact — it is a real microstructure fact.

2. **The reversal mirror was a fat edge — then decayed to zero.** `reversal_5_5d`
   was strongly positive 1997–2011 (+29%, +37%, +25%…), went flat-to-negative from
   2012 (2022 −8%, 2023 −12%), and **OOS 2024+ Sharpe = +0.13** (≈0). Consistent
   with HFT/electronic market-making arbitraging the spread-bounce away post-2010.
   Robustness: a **1-day-skip entry** (`--skip 1`, enter t+1 not t) only drops full-
   sample Sharpe 0.62→0.49 — so ~80% of the *historical* edge is real, not close-to-
   close bid-ask bounce. Real edge, genuinely arbitraged away. (See `../deep_backtest_skip1/`.)

3. **Only market beta is alive and improving.** buyhold_eqw OOS(2024+) Sharpe 1.25
   vs IS 0.79. The dollar-neutral signals are uncorrelated with beta, so their value
   is diversification, not standalone return — and that value has faded.

## What is confounded (needs point-in-time universe to resolve)

- **Momentum sign is understated; reversal sign is overstated.** Both because the
  universe is *today's* constituents: delisted/removed losers are absent.
  Evidence: `lt_mom_12_1` wins more often than it loses (hit-rate 0.524) yet has
  negative CAGR — its short leg (past losers) is stuck with survivors that bounced.
- The full-sample reversal Sharpe (+0.62) is therefore an **upper bound**; true
  tradable reversal is weaker, and its OOS death is the real signal.

## Verdict

On the **SP500 + NDX100 large-cap universe**, no member of the Alpha191
momentum/fade/reversal family is a **live, tradable, net-of-cost edge today**.
The earlier scan's "Sharpe 1.90" was overlap inflation (daily-formed, N-day-held,
annualized as if independent); the honest engine reverses the conclusion.

## Promising next moves (priority order)

1. **Re-run with point-in-time membership** (`../universe/index_membership_changes.csv`,
   1,181 dated events) to de-confound momentum vs reversal. Highest-value correctness
   fix; uses data already built. Until then treat momentum/reversal *magnitudes* as
   untrustworthy (the *short-horizon-momentum-is-negative* direction is safe).
2. **Small-cap / R2K universe.** Both reversal and momentum survive longest where
   liquidity is thin — the large-cap death does not necessarily generalize down-cap.
   Blocked on apex R2K coverage (enrichment).
3. **ETF sector-rotation + index-timing groups.** Separate track; blocked on deeper
   ETF/index history (apex has SPY/sectors only from 2021; SPX/NDX/RUT live under the
   lake's `volatility` asset_class, not equity).

## Caveats (apply to all numbers above)

- Survivorship-biased (today's constituents on old data).
- Underlying-return only — no options PnL, no earnings/event filter.
- Close-to-close reversal may capture non-tradable bid-ask bounce; a 1-day-skip
  entry test is the standard robustness check (not yet run).
- vwap is a typical-price proxy on daily bars.
