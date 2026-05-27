# VCG composite proxy — drawdown lead-time validation report

Generated: 2026-05-26

Spec: docs/superpowers/archive/specs/2026-05-26-vcg-composite-research-design.md

## 1. Methodology recap

Per-cell metrics computed against pre-declared:
- Benchmarks (enabled): SPX
- Drawdown defs: Fast, Medium, Major
- Periods: pre-2020, 2020-COVID, 2021-2022-rates, 2023-2026-AI

**Promotion gate aggregation** (lock-in, no author discretion):
- Primary utility + primary lead gates: computed on `(SPX, Fast)` cell only.
- Robustness FP/alarm/hit-rate gates: median across all 3 enabled benchmark x drawdown_def cells with n_events > 0.
- FP definition: an RO is NOT a false positive iff any event interval `[peak, trough]` overlaps `[ro_date, ro_date + H_def]` trading days.
- Gate metric: `FP_episode_rate` (NOT `FP_day_rate`). Both reported.

## 2. Data coverage

| Benchmark | First bar | Last bar | Bars | Used? | Drop reason |
|---|---|---|---|---|---|
| SPX | 1975-01-02 | 2026-05-21 | 12955 | YES | -- |
| NDX | -- | -- | 0 | NO | < 4000 bars or absent from vol_index_daily |
| RUT | -- | -- | 0 | NO | < 4000 bars or absent from vol_index_daily |

## 3. Per-period results matrix

### 2020-COVID -- Fast

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| HYG | single_proxy | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| JNK | single_proxy | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| LQD | single_proxy | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |

### 2020-COVID -- Major

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| HYG | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| JNK | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| LQD | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |

### 2020-COVID -- Medium

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| HYG | single_proxy | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| JNK | single_proxy | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| LQD | single_proxy | SPX | 2 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |

### 2021-2022-rates -- Fast

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.40% | 2 | 1.0 | 0.20% | nan |
| HYG | single_proxy | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.20% | 1 | 1.0 | 0.00% | nan |
| JNK | single_proxy | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.40% | 2 | 1.0 | 0.20% | nan |
| LQD | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |

### 2021-2022-rates -- Major

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.40% | 2 | 1.0 | 0.20% | nan |
| HYG | single_proxy | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.20% | 1 | 1.0 | 0.00% | nan |
| JNK | single_proxy | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.40% | 2 | 1.0 | 0.20% | nan |
| LQD | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |

### 2021-2022-rates -- Medium

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.40% | 2 | 1.0 | 0.20% | nan |
| HYG | single_proxy | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.20% | 1 | 1.0 | 0.00% | nan |
| JNK | single_proxy | SPX | 1 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.40% | 2 | 1.0 | 0.20% | nan |
| LQD | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.20% | nan |

### 2023-2026-AI -- Fast

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| HYG | single_proxy | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| JNK | single_proxy | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| LQD | single_proxy | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |

### 2023-2026-AI -- Major

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| HYG | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| JNK | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| LQD | single_proxy | SPX | 1 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |

### 2023-2026-AI -- Medium

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| HYG | single_proxy | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| JNK | single_proxy | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |
| LQD | single_proxy | SPX | 4 | nan | nan | 0.00% | nan% | nan% | nan% | nan% | 0.00% | 0.00% | 0 | nan | 0.00% | nan |

### pre-2020 -- Fast

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.10% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.07% | 2 | 1.0 | 0.14% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.10% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 33.33% | 0.00% | 0.00% | 0.10% | 3 | 1.0 | 0.10% | nan |
| HYG | single_proxy | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 25.00% | 0.00% | 0.00% | 0.13% | 4 | 1.0 | 0.00% | nan |
| JNK | single_proxy | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.07% | 2 | 1.0 | 0.14% | nan |
| LQD | single_proxy | SPX | 10 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.17% | nan |

### pre-2020 -- Major

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.10% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.07% | 2 | 1.0 | 0.14% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.10% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 33.33% | 0.00% | 0.00% | 0.10% | 3 | 1.0 | 0.10% | nan |
| HYG | single_proxy | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 25.00% | 0.00% | 0.00% | 0.13% | 4 | 1.0 | 0.00% | nan |
| JNK | single_proxy | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.07% | 2 | 1.0 | 0.14% | nan |
| LQD | single_proxy | SPX | 4 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.17% | nan |

### pre-2020 -- Medium

| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | RO eps | Med EpLen | Disagr | Utility |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| COMPOSITE_EQ3 | equal_weight_3 | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.10% | nan |
| COMPOSITE_HY_MINUS_IG | hy_minus_ig_spread | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.07% | 2 | 1.0 | 0.14% | nan |
| COMPOSITE_RP3 | risk_parity_3 | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.10% | nan |
| COMPOSITE_RP_HYJK | risk_parity_hyjk | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 33.33% | 0.00% | 0.00% | 0.10% | 3 | 1.0 | 0.10% | nan |
| HYG | single_proxy | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 25.00% | 0.00% | 0.00% | 0.13% | 4 | 1.0 | 0.00% | nan |
| JNK | single_proxy | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 50.00% | 0.00% | 0.00% | 0.07% | 2 | 1.0 | 0.14% | nan |
| LQD | single_proxy | SPX | 7 | nan | nan | 0.00% | 100.00% | 100.00% | 0.00% | 0.00% | 0.00% | 0.03% | 1 | 1.0 | 0.17% | nan |

## 4. Disagreement diagnostic

Days where each composite variant's RO signal disagrees with the HYG single-proxy baseline. Aggregated as median `disagreement_vs_hyg_rate` over all enabled cells, per variant.

| Method | Median disagreement % |
|---|---|
| equal_weight_3 | 0.05% |
| hy_minus_ig_spread | 0.07% |
| risk_parity_3 | 0.05% |
| risk_parity_hyjk | 0.05% |
| single_proxy | 0.00% |

## 5. Promotion gate verdicts

| Method | Primary util | Primary lead | Robust FP | Robust alarm | Robust hit | Regime dominance | **Overall** |
|---|---|---|---|---|---|---|---|
| risk_parity_3 | FAIL | FAIL | FAIL | PASS | PASS | FAIL | **FAIL** |
| risk_parity_hyjk | FAIL | FAIL | FAIL | PASS | PASS | FAIL | **FAIL** |
| hy_minus_ig_spread | FAIL | FAIL | FAIL | PASS | PASS | FAIL | **FAIL** |
| equal_weight_3 | FAIL | FAIL | FAIL | PASS | PASS | FAIL | **FAIL** |

## 6. Quoted numbers

### risk_parity_3
- primary_utility_wins: 0/4
- primary_lead_breaches: 0
- primary_lead_strong_wins: 0
- total_improvement_days: 0.00
- max_period_improvement_share: n/a

### risk_parity_hyjk
- primary_utility_wins: 0/4
- primary_lead_breaches: 0
- primary_lead_strong_wins: 0
- total_improvement_days: 0.00
- max_period_improvement_share: n/a

### hy_minus_ig_spread
- primary_utility_wins: 0/4
- primary_lead_breaches: 0
- primary_lead_strong_wins: 0
- total_improvement_days: 0.00
- max_period_improvement_share: n/a

### equal_weight_3
- primary_utility_wins: 0/4
- primary_lead_breaches: 0
- primary_lead_strong_wins: 0
- total_improvement_days: 0.00
- max_period_improvement_share: n/a

## 7. Run inventory + artifact appendix

| run_id | indicator | composite_version | composite_method | credit_proxy | run_scope |
|---|---|---|---|---|---|
| 9 | vcg | 1 | single_proxy | HYG | research |
| 10 | vcg | 1 | single_proxy | JNK | research |
| 11 | vcg | 1 | single_proxy | LQD | research |
| 12 | vcg | 2-candidate-rp3 | risk_parity_3 | COMPOSITE_RP3 | research |
| 13 | vcg | 2-candidate-rp-hyjk | risk_parity_hyjk | COMPOSITE_RP_HYJK | research |
| 14 | vcg | 2-candidate-hy-minus-ig | hy_minus_ig_spread | COMPOSITE_HY_MINUS_IG | research |
| 15 | vcg | 2-candidate-eq3 | equal_weight_3 | COMPOSITE_EQ3 | research |

### Query templates (for replay)

```sql
-- Production v1 HYG row (Hard Guarantee #2 default selection)
SELECT * FROM uw_scan.regime_backtest_runs
 WHERE indicator='vcg' AND run_scope='production'
   AND composite_version='1' AND credit_proxy='HYG'
   AND composite_method='single_proxy' AND completed_at IS NOT NULL
 ORDER BY created_at DESC LIMIT 1;

-- All research candidate rows (composite)
SELECT id, composite_version, composite_method, credit_proxy,
       summary->'extras'->>'weight_artifact_sha256' AS sha
  FROM uw_scan.regime_backtest_runs
 WHERE indicator='vcg' AND run_scope='research'
   AND composite_method <> 'single_proxy'
 ORDER BY created_at DESC;
```