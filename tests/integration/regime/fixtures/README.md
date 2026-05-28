# VCG v2 integration fixtures

## Files

- `seven_crisis_vol_complex.parquet` - contiguous vol-complex slice (`trade_date`, `vix`, `vvix`, `hyg`, `spx_close`, `crisis_window`) from earliest crisis warmup through latest crisis end. Tests insert these rows into `uw_scan.vol_index_daily`.
- `seven_crisis_truth_labels.parquet` - `(trade_date, truth_status, crisis_window)` pairs for crisis-window dates only. Tests join this parquet in memory against `regime_backtest_daily`.

## Regenerating

```bash
uv run scripts/build_vcg_v2_test_fixture.py
```

Run from the project root with the `UW_SCAN_DB_*` environment variables
pointing at a database populated for `vol_index_daily` and `macro_series_daily`.
`Settings.from_env()` reads individual DB variables, not `UW_SCAN_DB_URL`.

## Pinned Data-Quality Invariants

The builder script refuses to write parquet files unless all of these hold:

- Required symbol columns are present: `vix`, `vvix`, `hyg`, `spx_close`.
- Zero nulls in those columns inside all seven crisis windows.
- Max date gap inside crisis windows is at most 7 calendar days.
- All seven named crises are represented.
- Total truth-stress days is exactly 528, the Gate 2 denominator.
- Per-window truth-stress counts match:

| Crisis window | Expected truth-stress days |
|---|---:|
| GFC-Lehman | 105 |
| Eurozone-sovereign | 113 |
| China-devaluation-2015 | 39 |
| Q4-2018-vol-regime | 50 |
| COVID-2020 | 24 |
| 2022-rates-bear | 189 |
| 2023-SVB-week | 8 |
| Total | 528 |
