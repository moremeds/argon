# Skew RR Mean-Reversion → Trigger (Phase-2 increment-1)

**Date:** 2026-06-16
**Data:** `skew_analytics_snapshot` (basis='eod') on `option_wizard_local` — 16,890 snapshots,
~100 watchlist tickers, 2025-06 → 2026-06. Harness: `reports/skew_markout.run_skew_markout`
(`rv_reversion` output). RR forward series from `risk_reversal_skew_history` (delta=25, T+20
trading days).
**Status:** In-sample, single ~1yr window. The RV mean-reversion of the 25Δ risk-reversal is
now **gated into a persisted verdict** (`skew_rv_reversion_verdicts`), distinct from the
directional `skew_directional_verdicts`. **Descriptive RV axis only — no spread-P&L /
net-of-cost claim** (executable option-return replay is data-blocked; see Limitations).

## Method

Per `(asset_class, deviation_class, tail)` bucket — `tail` derived from `sign(rr_25d)`
(put_skew = rr>0, call_skew = rr<0) — collect forward ΔRR over T+20 (`rr[t+20] − rr[t]`).
A bucket earns `REVERTS` only if ALL hold:

1. **Expected sign** — CHEAP must re-richen (ΔRR > 0), RICH must flatten (ΔRR < 0).
   NORMAL makes no reversion claim (`expected_sign = 0` → always NONE).
2. **Magnitude** — `|mean ΔRR| ≥ 0.005` (full sample) and `≥ 0.003` on the holdout.
3. **Walk-forward holdout** — time-ordered: the latest 40% of obs (by `market_date`) must
   preserve the full-sample sign + meet the holdout magnitude floor. No leakage (train is
   strictly earlier than holdout).
4. **Per-quarter catastrophic-degradation gate** — no calendar quarter may reverse the
   aggregate sign with *larger* magnitude (mirrors the directional `_survives_window_gate`;
   standing rule: aggregate metrics hide sub-window blowups).

`n` = full-sample obs, `n_holdout` = holdout obs. Thresholds live in `reports/skew_markout.py`
(`RV_MIN_N=30`, `RV_HOLDOUT_FRAC=0.40`, `RV_SEP_THRESHOLD=0.005`, `RV_HOLDOUT_THRESHOLD=0.003`).

## Results (run 2026-06-16, 16,890 snapshots → 17 RV buckets, 6 REVERTS)

| bucket | verdict | mean ΔRR | holdout ΔRR | n | n_hold | walk-fwd | quarter-gate |
|---|---|---:|---:|---:|---:|:--:|:--:|
| single_name CHEAP **call_skew** | **REVERTS** | +0.1919 | +0.4463 | 1241 | 496 | ✅ | ✅ |
| single_name CHEAP **put_skew** | **REVERTS** | +0.0320 | +0.0664 | 307 | 123 | ✅ | ✅ |
| single_name RICH **put_skew** | **REVERTS** | −0.0406 | −0.1087 | 3162 | 1265 | ✅ | ✅ |
| sector_etf CHEAP **call_skew** | **REVERTS** | +0.0710 | +0.1236 | 40 | 16 | ✅ | ✅ |
| sector_etf RICH **put_skew** | **REVERTS** | −0.0103 | −0.0420 | 167 | 67 | ✅ | ✅ |
| index_macro CHEAP **call_skew** | **REVERTS** | +0.0085 | +0.0151 | 52 | 21 | ✅ | ✅ |
| single_name RICH call_skew | NONE | +0.0052 | +0.0209 | 1236 | 494 | ✗ (wrong sign) | — |
| index_macro RICH call_skew | NONE | +0.0105 | +0.0265 | 125 | 50 | ✗ | ✅ |
| index_macro RICH put_skew | NONE | −0.0020 | −0.0125 | 461 | 184 | ✗ | ✗ |
| index_macro CHEAP put_skew | NONE | −0.0049 | −0.0040 | 52 | 21 | ✗ (wrong sign) | — |
| NORMAL buckets (×5) | NONE | na | na | — | 0 | — | — |
| sector_etf CHEAP put_skew | NONE | na | na | 28 | 0 | — (n<30) | — |

## Read

- **The tail-split is load-bearing.** `single_name CHEAP` splits into a huge **call_skew**
  leg (mean +0.192, n=1241) and a modest **put_skew** leg (mean +0.032, n=307). The
  aggregate "CHEAP re-richens +0.051" from the V1 markout was inflated by extreme
  *call*-skew names (e.g. ALAB-type rr≈−0.22 that snap back hard but volatile). A
  put-skew-specific claim is now isolated and far smaller.
- **Both reversion legs confirm the textbook signature** after gating: CHEAP re-richens (+),
  RICH flattens (−), for single-names and sector ETFs.
- **The gates filter real noise.** `single_name RICH call_skew` (+0.0052, *wrong* sign for
  RICH) and `index_macro RICH put_skew` (fails the quarter gate) are correctly NONE — the
  aggregate would have looked tradeable.
- **index_macro reversion is weak/small-n** — consistent with structural hedging demand
  (the V1 finding that index skew does not mean-revert). The lone index REVERTS
  (CHEAP/call_skew, n=52) is small and should be treated with caution.

## Limitations (must stay loud)

- **In-sample, one ~1yr window.** The walk-forward holdout and train share the same regime;
  it is a sanity check against a single-window fit, **not** an out-of-sample forecast. Skew
  effects decay (Xing-Zhang-Zhao; Cremers-Weinbaum). Treat as a tilt.
- **No spread-P&L / net-of-cost.** This is reversion of the RR *shape*, not a tradeable
  return. Executable option-return replay is **data-blocked**: `option_chain_per_strike` is
  ~5 trading days deep and UW per-strike greeks history is ~30 days; only RR history is ~1yr.
  That validation is a separate contract-history data project (split out — see
  `skew-mean-reversion-trade-structures-phase2.md` § Hardening review).
- **ΔRR ≠ stock direction.** The directional axis lives in `skew_directional_verdicts` /
  `directional_lean` and can have the opposite sign (e.g. CHEAP/PANIC is `TRADABLE_BEAR`).
  Do not read these RV verdicts as a stock-direction signal.
- **Re-run** `run_skew_markout` after each backfill extension to refresh both verdict stores.

## Cross-reference

Primary directional numbers: `docs/research/skew-first-principles-markout-2026-06.md` (do not
duplicate). Trade-structure framing + scope: `docs/research/skew-mean-reversion-trade-structures-phase2.md`.
