# src/uw_scan/reports — report assemblers

The seam between **DB rows** and **API response models**. Routers call assemblers; assemblers call the repository + cards; cards return derived numbers; the assembler stitches everything into a `Volatility…Response` / `SingleStock…Response`.

## Domains (~40 modules — `ls` the directory; the groups below are the map)

- **Stock page** — `single_stock.py` (detail-page payload: header, GEX, flow, vol), `volatility_series.py` (Volatility tab v2: smile, term structure, HV/IV, RV-z, IV-of-IV, VRP, regime quadrant), `iv_smile_builder.py`, `stock_short_vol.py`
- **VRP family** — `vrp_backtest, vrp_candidates, vrp_capital_account, vrp_directional, vrp_gate, vrp_harvest_axes, vrp_macro_signal, vrp_macro_entry, vrp_markout(_core), vrp_robustness, vrp_rv_validation, vrp_structure`
- **Skew** — `skew_analytics.py`, `skew_markout.py`
- **Regime backtests** — `regime_backtest_report, regime_canary_*, regime_classification_report, regime_vcg_backtest_report`
- **Data health** — `data_freshness.py`, `data_gap_healer.py`, `data_gap_evidence.py`
- **Other** — `gold_posture`, `goas_putwrite_*`, `put_calendar`, `market_tide_sentiment`, plus subpackages `trade_blast/`, `trade_insights_ai/`, `_shared_validation/`

## Rules

- **Only place that combines I/O and derivation.** Routers should not call `cards/*` directly.
- **Persist outputs.** Anything labeled "analytical result" (regime, VRP, vol rollups) is written back to Postgres in the same call — see the standing feedback memory. Returning data without persisting is a regression.
- **Filter expiries to `year_end = date(today.year + 1, 12, 31)`** for term structure / smile (covers the rest of this year + all of next; matches the front-end legend).
- **Cap smile points** to `±35%` of spot (`_clip_smile_to_spot_range`) before trimming flat wings — see `_build_smile`.
- **Fill RV from price** when UW's `realized-volatility` endpoint returns nulls — `_fill_rv_from_price(rv_rows, window=21)`.
- **Emit `cutoff_corr`** from `_build_regime_quadrant` so the frontend draws its divider at the classifier's actual cutoff, not a hardcoded 0.5.
