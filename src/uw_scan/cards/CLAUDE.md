# src/uw_scan/cards — per-ticker analytical derivers

Pure(ish) functions that take typed rows / DataFrames and return derived metrics. Consumed by `reports/*` to assemble the stock detail page.

## Files

- `aggression.py` — flow aggression score (buy/sell pressure)
- `derive.py` — generic derivers used across cards
- `gex.py` — gamma exposure profile, flip point, walls
- `pcr.py` — put/call ratio
- `returns.py` — log-returns from OHLC for RV / SPY-corr
- `vol_series.py` — VRP, IV-of-IV, RV percentile, regime quadrant inputs (the heavy one)

## Conventions

- **Decimal in, Decimal out.** No float arithmetic for price-shaped data.
- **No DB access here.** Cards receive rows from the repository and return derived series. The assembler in `reports/` does the I/O.
- **Logging on coercion failures:** the AST guardrail in CI requires every `except` block to call `.exception(...)`, `repr(exc)`, `traceback`, or `raise`. The standing pattern in `vol_series.py` is:
  ```python
  except (TypeError, ValueError) as exc:
      log.debug("coercion skipped: %s", repr(exc))
      return None
  ```
- **`pandas` is allowed** here for rolling windows and quantiles — but the output crossing the function boundary is back to typed models / Decimals.
- **Determinism matters** — derived series feed nightly rollups; don't depend on `datetime.now()` inside a deriver, pass `as_of` in.
