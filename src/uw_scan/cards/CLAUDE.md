# src/uw_scan/cards — per-ticker analytical derivers

Pure(ish) functions that take typed rows / DataFrames and return derived metrics. Consumed by `reports/*` to assemble the stock detail page.

## Domains (~34 modules — `ls` the directory; the groups below are the map)

- **Core scan cards** — `aggression.py` (flow aggression), `derive.py` (shared derivers), `gex.py` (GEX profile/flip/walls), `pcr.py`, `returns.py` (log-returns for RV / SPY-corr), `vol_series.py` (VRP, IV-of-IV, RV percentile, regime quadrant — the heavy one)
- **Regime scoring** — `cri_scorers.py`/`cri_scoring.py`, `vcg_scoring.py`/`vcg_basket.py`/`vcg_validation_metrics.py`, `canary_scoring.py`/`canary_calibration.py`/`canary_payload_hash.py`, `grg_scoring.py`, `regime_classification_scoring.py`/`regime_classification_labels.py`, `regime_gauge.py`, `regime_forward_returns.py`, `dealer_regime.py` — thresholds are governed by `docs/research/regime/CLAUDE.md`; read it before changing any constant
- **Structure / flow analytics** — `skew_first_principles.py`, `structural_flow.py`, `exposures.py`, `option_chain.py`, `greek_exposure_history.py`, `intraday_profile.py`, `framework_tape.py`, `matrix_state.py`
- **Gold** — `valuation.py`, `cyclical_zones.py`, `cb_buckets.py`, `mean_reversion.py`, `drawdown.py`

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
