# UW `realized_volatility` is FORWARD RV — vrp_daily carried lookahead (2026-09-24)

**Verdict:** every `vrp_daily.rv / vrp / vrp_z_20` value before this fix used
forward-looking RV, as did the matrix-state VRP z-scores and the cockpit VRP
chart. With trailing RV the VRP-harvest "rich vol is sellable" result
**goes away** everywhere except `credit`, where n=129. Reported by signal-lab
(run `research/runs/2026-09-24-single-name-vrp-extremes`) and reproduced here.

## The vendor fact

`realized_volatility_history.realized_volatility` at `market_date = t` is the
21-return annualised RV over returns t..t+20 (the window ENDING at t+20). UW
leaves the last ~20 rows null because that future has not happened yet. It is
not a lag.

Reproduce (`rv_shift_check.py` here; local `option_wizard_local`, 2026-09-24):
trailing 21d RV from the `price` column, shifted k rows, vs UW's value (MAE):

| ticker | k=0    | k=−1   | k=−19  | **k=−20**  | k=−21  |
| ------ | ------ | ------ | ------ | ---------- | ------ |
| AAPL   | 0.0719 | 0.0703 | 0.0094 | **0.0000** | 0.0094 |
| KO     | 0.0406 | 0.0396 | 0.0061 | **0.0000** | 0.0061 |
| NVDA   | 0.0575 | 0.0559 | 0.0107 | **0.0000** | 0.0108 |
| SPY    | 0.0367 | 0.0360 | 0.0042 | **0.0000** | 0.0042 |

(The script labels these shift(+k) with k = 0, 1, 19, 20, 21. `shift(-k)` pulls
the value from k rows later.)

## Effect on the persisted verdicts (local DB, before → after)

Before: the `2026-09-19` rows synced into `option_wizard_local`. After: this
branch's rebuilt `vrp_daily`, then `vrp_markout_refresh` and
`vrp_research_refresh`, run on 2026-09-24. Full rows are in the CSVs next to this
file.

`vrp_harvest_verdicts`, RICH bucket (mean realized VRP, holdout mean, rich−cheap spread):

| asset_class | before                                     | after                                             |
| ----------- | ------------------------------------------ | ------------------------------------------------- |
| single_name | HARVEST_SELLABLE, +0.109 / +0.105 / +0.188 | NONE, +0.004 / +0.021 / −0.009, n=6700            |
| index_macro | HARVEST_SELLABLE, +0.048 / +0.053 / +0.088 | NONE, +0.019 / +0.021 / +0.003, n=568             |
| sector_etf  | HARVEST_SELLABLE, +0.075 / +0.054 / +0.134 | NONE, +0.011 / +0.007 / +0.001, n=1234            |
| credit      | HARVEST_SELLABLE, +0.039 / +0.024 / +0.043 | HARVEST_SELLABLE, +0.029 / +0.017 / +0.020, n=129 |

`vrp_harvest_by_sector`, RICH bucket: **36 of 37** sectors were sellable before
and **4 of 36** after (IT-Services/Integration n=72, Consumer n=471,
EPC/Construction n=33, Cybersecurity n=57). The small-n survivors are not a
finding: 4 passes out of 36 tests is about what multiple testing produces by chance.

Mechanism: the RICH class was `vrp_z_20` high, with `vrp = IV − RV_forward`. It
selected days where future realized vol turned out low, so it was conditioning
on the outcome the markout then measured.

Caveat: this is the dev DB. Memory records that dev-DB analyses have diverged
from prod before. Prod recomputes these tables on its own after deploy (see
below), and that run is the authoritative number.

## What changed (PR `fix/uw-rv-forward-lookahead`)

- `cards/vol_series.trailing_rv` — trailing 21d RV from `daily_ohlc` closes
  (massive, split-adjusted); UW's RV is never read, and neither is UW's `price`
  column, which is raw across some splits (KLAC reads 2411.64 the day before its
  10:1 split, CRWD drops 494 → 165) but adjusted across others. Massive-derived
  trailing RV equals UW's value shifted 20 rows to p99 ≤ 0.0007 on AAPL/KO/NVDA/SPY.
  A ticker with no `daily_ohlc` at all falls back to UW's `price`. Today that is
  only SPX (massive serves no index bars), and an index has no splits.
- `worker/volatility_jobs.nightly_vol_analytics_rollup` + `reports/volatility_series` use it.
- `storage/matrix_state.fetch_matrix_realized_vol_history` computes the same thing
  in SQL. It feeds the matrix card's `vrp_state` / `vrp_zscore_60d/252d` and both
  cockpit readers.
- `reports/single_stock` no longer falls back to UW's RV.
- `scripts/backfill_vrp_daily.py` now deletes every `vrp_daily` row and rebuilds
  ten years of history in one transaction.

## Known ceilings / not done

- `daily_ohlc` stitches different securities under a reused ticker: FIG (23.8 →
  115.5 on its 2025-07-31 IPO) and SPCX (21.98 → 160.95 on 2026-06-12). RV spikes
  for ~21 rows after each switch. This is a data-identity problem in the OHLC feed
  and is not fixed here.
- `corporate_actions` does not line up with UW's price jumps (CRWD: split recorded
  2026-07-02 4:1, UW jump 2025-07-02 ~3:1), so repairing UW's `price` from it was
  tried and dropped.
- Trailing RV is None on days with no `daily_ohlc` close yet. The 17:30 ET OHLC
  pull runs before the 18:00 ET rollup, so in prod this only affects days the pull missed.
- The markout LABEL leg (`reports/vrp_markout.py`, `skew_markout._price_series`)
  still builds forward realized vol from UW's `price` plus `apply_split_adjustment`
  over `corporate_actions`, which has no KLAC split row. So KLAC's label spikes for
  ~21 sessions after 2026-06-12, and the "after" verdicts above include that. This is
  not lookahead, but it is the same split problem this fix avoids for the feature.
- `stock_analytics_daily` realized-vol percentile still uses UW's raw `price`
  (split artifact, not lookahead). Not changed here.
- `vrp_30d_settlements.rv_subsequent` takes the first UW RV at ≥ t+30 calendar
  days. Given forward semantics, that is RV over roughly t+21..t+41 trading days,
  the wrong window. The correct label is UW's value at t+1 (window t+1..t+21).
  Nothing reads the table, so it is left as is and flagged here.
- `docs/research/2026-07-07-flow-vs-rviv-verdict.*` is **invalid**: it used
  `vrp_daily` rv−iv as a same-day factor. It needs a re-run on prod after the rebuild.
- Memory entries built on the harvest verdicts ("VRP sellable BY SECTOR") are
  superseded.

## Reproduce

```bash
uv run python docs/research/2026-09-24-uw-rv-forward-lookahead/rv_shift_check.py "<dsn>"
uv run python scripts/backfill_vrp_daily.py            # delete + rebuild vrp_daily
# then vrp_markout_refresh / vrp_research_refresh (worker jobs), and diff the CSVs
```
