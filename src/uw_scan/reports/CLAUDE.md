# src/uw_scan/reports — report assemblers

The seam between **DB rows** and **API response models**. Routers call assemblers; assemblers call the repository + cards; cards return derived numbers; the assembler stitches everything into a `Volatility…Response` / `SingleStock…Response`.

## Files

- `single_stock.py` — assembles the stock detail page payload (header, GEX, flow, vol)
- `volatility_series.py` — assembles the Volatility tab v2 payload (smile, term structure, HV/IV, RV-z, IV-of-IV, VRP, regime quadrant)
- `iv_smile_builder.py` — builds the per-expiry smile curves

## Rules

- **Only place that combines I/O and derivation.** Routers should not call `cards/*` directly.
- **Persist outputs.** Anything labeled "analytical result" (regime, VRP, vol rollups) is written back to Postgres in the same call — see the standing feedback memory. Returning data without persisting is a regression.
- **Filter expiries to `year_end = date(today.year + 1, 12, 31)`** for term structure / smile (covers the rest of this year + all of next; matches the front-end legend).
- **Cap smile points** to `±35%` of spot (`_clip_smile_to_spot_range`) before trimming flat wings — see `_build_smile`.
- **Fill RV from price** when UW's `realized-volatility` endpoint returns nulls — `_fill_rv_from_price(rv_rows, window=21)`.
- **Emit `cutoff_corr`** from `_build_regime_quadrant` so the frontend draws its divider at the classifier's actual cutoff, not a hardcoded 0.5.
