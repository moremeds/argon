# US Short-Dated Swing Strategy Shortlist

Checked at: `2026-07-02T04:32:01.462942+00:00`

## Scope

- Universe: active Argon watchlist, `103` tickers.
- OHLCV source: Apex REST primary; DB fallback.
- Date range loaded: `2023-01-03` to `2026-07-01`.
- Backtest start: `2025-07-01`.
- Holding horizons: `5, 10, 15` trading days.
- Portfolio test: top `5` and bottom `5` names by strategy score, equal-weighted.

## Caveats

- This is a stock-return backtest of strategy archetypes, not an options PnL backtest.
- Returns overlap because the strategy forms a new portfolio each trading day.
- No option spread, liquidity, IV crush, earnings, commissions, or fill quality is modeled.
- Alpha191 is idea inspiration only; formulas here are US-stock-native.

## 5 Strategy Shortlist

| strategy | horizon_days | mean_return | hit_rate | sharpe_overlap_naive | max_drawdown_overlap_naive | thesis | option_expression |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trend_exhaustion_fade_1w | 5 | 0.0133 | 0.6154 | 1.9002 | -0.6630 | Very sharp positive slope acceleration tends to mean-revert; short-dated puts or put spreads can express a 1-week fade. | Put debit spreads or small long puts, 1-3 week expiry; spreads preferred when IV is high. |
| momentum_continuation_2w | 10 | 0.0173 | 0.6157 | 1.3355 | -0.8375 | When 10-day momentum is confirmed by trend slope and gap follow-through, short-dated calls or call spreads can capture continuation over 1-3 weeks. | Long calls or call debit spreads, 2-4 week expiry; use spreads when IV rank is elevated. |
| accumulation_breakout_3w | 15 | 0.0066 | 0.5274 | 0.4497 | -0.6181 | Persistent close-near-high accumulation with volume and range pressure can precede 2-3 week breakouts. | Call debit spreads, 3-5 week expiry, or defined-risk call calendars when IV term structure supports it. |
| gap_follow_through_1w | 5 | 0.0011 | 0.4939 | 0.2032 | -0.3760 | Gaps with volume participation can keep moving for several sessions in US single names. | Directional calls/puts aligned with the gap, usually 1-2 week expiry; define risk with debit spreads. |
| gap_snapback_fade_1w | 10 | -0.0103 | 0.4463 | -0.7883 | -0.9765 | Overnight gaps away from typical price often snap back over the next week when not confirmed by follow-through. | Contrarian calls after down gaps or puts after up gaps; prefer spreads because timing decay is harsh. |

## Full Long-Short Summary

| strategy | horizon_days | mean_return | median_return | hit_rate | sharpe_overlap_naive | max_drawdown_overlap_naive |
| --- | --- | --- | --- | --- | --- | --- |
| trend_exhaustion_fade_1w | 5 | 0.0133 | 0.0105 | 0.6154 | 1.9002 | -0.6630 |
| momentum_continuation_2w | 10 | 0.0173 | 0.0210 | 0.6157 | 1.3355 | -0.8375 |
| trend_exhaustion_fade_1w | 10 | 0.0193 | 0.0136 | 0.5868 | 1.3347 | -0.8444 |
| momentum_continuation_2w | 5 | 0.0063 | 0.0080 | 0.5749 | 1.0846 | -0.4369 |
| momentum_continuation_2w | 15 | 0.0224 | 0.0239 | 0.6076 | 1.0341 | -0.9367 |
| trend_exhaustion_fade_1w | 15 | 0.0147 | 0.0174 | 0.5781 | 0.7118 | -0.9178 |
| accumulation_breakout_3w | 15 | 0.0066 | 0.0039 | 0.5274 | 0.4497 | -0.6181 |
| accumulation_breakout_3w | 10 | 0.0036 | 0.0035 | 0.5289 | 0.3485 | -0.5236 |
| gap_follow_through_1w | 5 | 0.0011 | -0.0003 | 0.4939 | 0.2032 | -0.3760 |
| accumulation_breakout_3w | 5 | -0.0004 | -0.0021 | 0.4818 | -0.0936 | -0.6521 |
| gap_follow_through_1w | 15 | -0.0019 | -0.0040 | 0.4641 | -0.1059 | -0.8649 |
| gap_follow_through_1w | 10 | -0.0021 | -0.0016 | 0.4959 | -0.1833 | -0.7806 |
| gap_snapback_fade_1w | 10 | -0.0103 | -0.0096 | 0.4463 | -0.7883 | -0.9765 |
| gap_snapback_fade_1w | 5 | -0.0049 | -0.0075 | 0.4413 | -0.8031 | -0.8556 |
| gap_snapback_fade_1w | 15 | -0.0178 | -0.0186 | 0.4304 | -0.8325 | -0.9953 |

## Output Files

- `/Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/docs/research/alpha191-short-swing/us_short_swing_strategy_backtest_summary.csv`
- `/Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/docs/research/alpha191-short-swing/us_short_swing_strategy_backtest_trades.csv`
- `/Users/chenxi/projects/argon/.worktrees/alpha191-short-swing-scan/docs/research/alpha191-short-swing/us_short_swing_strategy_shortlist.csv`
