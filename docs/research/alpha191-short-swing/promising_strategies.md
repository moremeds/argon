# Promising US Short-Dated Swing Strategies

Checked at: `2026-07-02`

This note saves the two strategies that survived the first strategy-level scan.
The scan used Alpha191 only as idea inspiration and rebuilt the signals for US
stocks using Argon watchlist data and Apex daily history.

## Champion: Trend Exhaustion Fade

Strategy id: `trend_exhaustion_fade_1w`

Thesis: very sharp positive slope acceleration often exhausts over a short
window. The highest acceleration names are candidates to fade, while the lowest
acceleration names can be used as the other side of the cross-sectional test.

Target horizon: 5 trading days primary, 10 trading days secondary.

Best current evidence:

| Horizon | Mean long-short return | Hit rate | Naive Sharpe | Max drawdown |
| --- | ---: | ---: | ---: | ---: |
| 5d | 1.33% | 61.5% | 1.90 | -66.3% |
| 10d | 1.93% | 58.7% | 1.33 | -84.4% |
| 15d | 1.47% | 57.8% | 0.71 | -91.8% |

Why it is champion:

- It is the cleanest fit for the requested holding period: 1 week to 2 weeks.
- The 5d result had the strongest hit rate and naive Sharpe among tested
  strategy archetypes.
- The signal is simple enough to productionize and explain: do not chase
  extreme short-window acceleration; fade it only when option conditions allow.

Option expression:

- Preferred: put debit spreads on overextended names, 1-3 week expiry.
- Conservative use: use the signal as a no-chase or hedge trigger instead of a
  standalone bearish trade.
- Avoid naked shorts and undefined-risk option structures.

Avoid conditions:

- Earnings within the holding window.
- Fresh fundamental repricing gaps.
- High-short-interest squeeze conditions.
- Extremely wide option spreads.
- IV rank high enough that long premium has poor expected value unless using a
  spread.

## Runner-Up: Momentum Continuation

Strategy id: `momentum_continuation_2w`

Thesis: 10-day momentum confirmed by trend slope and gap participation often
continues over a 2-3 week swing window in liquid US names.

Target horizon: 10 trading days primary, 15 trading days secondary.

Best current evidence:

| Horizon | Mean long-short return | Hit rate | Naive Sharpe | Max drawdown |
| --- | ---: | ---: | ---: | ---: |
| 5d | 0.63% | 57.5% | 1.08 | -43.7% |
| 10d | 1.73% | 61.6% | 1.34 | -83.8% |
| 15d | 2.24% | 60.8% | 1.03 | -93.7% |

Why it is promising:

- The long leg was strong across 5d, 10d, and 15d windows.
- It maps well to call structures because the expected move is directional and
  time-bound.
- It can be combined with existing Argon scanner/setup context for confirmation.

Option expression:

- Preferred: call debit spreads, 2-4 week expiry.
- Use outright calls only when IV is not inflated and spread quality is strong.
- For high IV names, debit spreads or calendars are more appropriate than naked
  long calls.

Avoid conditions:

- IV already pricing the full expected move.
- One-day news spikes without trend confirmation.
- Earnings inside the planned hold.
- Poor option liquidity or wide bid/ask.

## Rejected Or Weak Strategies

| Strategy | Verdict | Reason |
| --- | --- | --- |
| `accumulation_breakout_3w` | Weak candidate | Slight positive edge only at 15d; not enough as a standalone champion. |
| `gap_follow_through_1w` | Confirmation only | Standalone long-short result was too weak. |
| `gap_snapback_fade_1w` | Reject | Negative across tested 5d, 10d, and 15d horizons. |

## Current Evidence Files

- `us_short_swing_strategy_report.md`
- `us_short_swing_strategy_backtest_summary.csv`
- `us_short_swing_strategy_backtest_trades.csv`
- `us_short_swing_strategy_shortlist.csv`

