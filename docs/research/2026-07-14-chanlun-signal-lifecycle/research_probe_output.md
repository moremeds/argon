# Chanlun prefix-replay probe raw output
Elapsed load+replay so far: 0.1s
AAPL N=1300 idents=1160; NVDA N=1300 idents=1186

### AAPL
| cat | appeared | finalConfirmed | invalid(not final-conf) | disappeared | median lagApp | p90 lagApp | max lagApp | median lagConf | p90 lagConf | max lagConf |
|---|---|---|---|---|---|---|---|---|---|---|
| vertices | 876 | 98 | 88.8% | 88.7% | 0 | 1 | 58 | 8 | 13 | 58 |
| 3BS | 156 | 11 | 92.9% | 92.9% | 0 | 0 | 2 | 8 | 12 | 14 |
| 1BS | 8 | 2 | 75.0% | 75.0% | 1 | 1 | 1 | 10 | 10 | 10 |
| 2BS | 10 | 0 | 100.0% | 100.0% | null | null | 0 | null | null | 0 |
| divergences | 110 | 18 | 83.6% | 83.6% | 0 | 0 | 1 | 8 | 16 | 17 |

**flip-flop (appear→disappear→reappear) counts, AAPL:**
- vertices: 0×876  (max flipflops=0)
- 3BS: 0×156  (max flipflops=0)
- 1BS: 0×8  (max flipflops=0)
- 2BS: 0×10  (max flipflops=0)
- divergences: 0×110  (max flipflops=0)

**Survival to final-confirmed by appearance-lag bucket (bars after marked extreme), AAPL:**
| cat | bucket | n appeared | n final-confirmed | survival % |
|---|---|---|---|---|
| vertices | 0 | 853 | 85 | 10.0% |
| vertices | 1 | 17 | 8 | 47.1% |
| vertices | 2 | 1 | 1 | 100.0% |
| vertices | 3 | 1 | 1 | 100.0% |
| vertices | ≥4 | 4 | 3 | 75.0% |
| 3BS | 0 | 152 | 10 | 6.6% |
| 3BS | 1 | 3 | 0 | 0.0% |
| 3BS | 2 | 1 | 1 | 100.0% |
| 1BS | 1 | 7 | 2 | 28.6% |
| 1BS | 3 | 1 | 0 | 0.0% |
| 2BS | 0 | 10 | 0 | 0.0% |
| divergences | 0 | 109 | 17 | 15.6% |
| divergences | 1 | 1 | 1 | 100.0% |

**Early (lagApp≤1, "pending at bar close") vs later (≥2) survival, AAPL:**
| cat | early n | early surv% | later n | later surv% |
|---|---|---|---|---|
| vertices | 870 | 10.7% | 6 | 83.3% |
| 3BS | 155 | 6.5% | 1 | 100.0% |
| 1BS | 7 | 28.6% | 1 | 0.0% |
| 2BS | 10 | 0.0% | 0 | - |
| divergences | 110 | 16.4% | 0 | - |

### NVDA
| cat | appeared | finalConfirmed | invalid(not final-conf) | disappeared | median lagApp | p90 lagApp | max lagApp | median lagConf | p90 lagConf | max lagConf |
|---|---|---|---|---|---|---|---|---|---|---|
| vertices | 851 | 104 | 87.8% | 87.5% | 0 | 1 | 55 | 8 | 13 | 55 |
| 3BS | 163 | 15 | 90.8% | 90.8% | 0 | 0 | 0 | 7 | 10 | 11 |
| 1BS | 27 | 3 | 88.9% | 88.9% | 1 | 2 | 2 | 7 | 8 | 8 |
| 2BS | 10 | 0 | 100.0% | 100.0% | null | null | 0 | null | null | 0 |
| divergences | 135 | 22 | 83.7% | 83.0% | 0 | 0 | 1 | 8 | 13 | 16 |

**flip-flop (appear→disappear→reappear) counts, NVDA:**
- vertices: 0×851  (max flipflops=0)
- 3BS: 0×163  (max flipflops=0)
- 1BS: 0×27  (max flipflops=0)
- 2BS: 0×10  (max flipflops=0)
- divergences: 0×135  (max flipflops=0)

**Survival to final-confirmed by appearance-lag bucket (bars after marked extreme), NVDA:**
| cat | bucket | n appeared | n final-confirmed | survival % |
|---|---|---|---|---|
| vertices | 0 | 828 | 92 | 11.1% |
| vertices | 1 | 17 | 8 | 47.1% |
| vertices | 2 | 2 | 1 | 50.0% |
| vertices | 3 | 1 | 0 | 0.0% |
| vertices | ≥4 | 3 | 3 | 100.0% |
| 3BS | 0 | 159 | 15 | 9.4% |
| 3BS | 1 | 3 | 0 | 0.0% |
| 3BS | 2 | 1 | 0 | 0.0% |
| 1BS | 1 | 22 | 2 | 9.1% |
| 1BS | 2 | 3 | 1 | 33.3% |
| 1BS | 3 | 1 | 0 | 0.0% |
| 1BS | ≥4 | 1 | 0 | 0.0% |
| 2BS | 0 | 10 | 0 | 0.0% |
| divergences | 0 | 133 | 21 | 15.8% |
| divergences | 1 | 2 | 1 | 50.0% |

**Early (lagApp≤1, "pending at bar close") vs later (≥2) survival, NVDA:**
| cat | early n | early surv% | later n | later surv% |
|---|---|---|---|---|
| vertices | 845 | 11.8% | 6 | 66.7% |
| 3BS | 162 | 9.3% | 1 | 0.0% |
| 1BS | 22 | 9.1% | 5 | 20.0% |
| 2BS | 10 | 0.0% | 0 | - |
| divergences | 135 | 16.3% | 0 | - |

### POOLED (AAPL+NVDA)
| cat | appeared | finalConfirmed | invalid(not final-conf) | disappeared | median lagApp | p90 lagApp | max lagApp | median lagConf | p90 lagConf | max lagConf |
|---|---|---|---|---|---|---|---|---|---|---|
| vertices | 1727 | 202 | 88.3% | 88.1% | 0 | 1 | 58 | 8 | 13 | 58 |
| 3BS | 319 | 26 | 91.8% | 91.8% | 0 | 0 | 2 | 8 | 11 | 14 |
| 1BS | 35 | 5 | 85.7% | 85.7% | 1 | 2 | 2 | 7 | 10 | 10 |
| 2BS | 20 | 0 | 100.0% | 100.0% | null | null | 0 | null | null | 0 |
| divergences | 245 | 40 | 83.7% | 83.3% | 0 | 0 | 1 | 8 | 14 | 17 |

**flip-flop (appear→disappear→reappear) counts, POOLED (AAPL+NVDA):**
- vertices: 0×1727  (max flipflops=0)
- 3BS: 0×319  (max flipflops=0)
- 1BS: 0×35  (max flipflops=0)
- 2BS: 0×20  (max flipflops=0)
- divergences: 0×245  (max flipflops=0)

**Survival to final-confirmed by appearance-lag bucket (bars after marked extreme), POOLED (AAPL+NVDA):**
| cat | bucket | n appeared | n final-confirmed | survival % |
|---|---|---|---|---|
| vertices | 0 | 1681 | 177 | 10.5% |
| vertices | 1 | 34 | 16 | 47.1% |
| vertices | 2 | 3 | 2 | 66.7% |
| vertices | 3 | 2 | 1 | 50.0% |
| vertices | ≥4 | 7 | 6 | 85.7% |
| 3BS | 0 | 311 | 25 | 8.0% |
| 3BS | 1 | 6 | 0 | 0.0% |
| 3BS | 2 | 2 | 1 | 50.0% |
| 1BS | 1 | 29 | 4 | 13.8% |
| 1BS | 2 | 3 | 1 | 33.3% |
| 1BS | 3 | 2 | 0 | 0.0% |
| 1BS | ≥4 | 1 | 0 | 0.0% |
| 2BS | 0 | 20 | 0 | 0.0% |
| divergences | 0 | 242 | 38 | 15.7% |
| divergences | 1 | 3 | 2 | 66.7% |

**Early (lagApp≤1, "pending at bar close") vs later (≥2) survival, POOLED (AAPL+NVDA):**
| cat | early n | early surv% | later n | later surv% |
|---|---|---|---|---|
| vertices | 1715 | 11.3% | 12 | 75.0% |
| 3BS | 317 | 7.9% | 2 | 50.0% |
| 1BS | 29 | 13.8% | 6 | 16.7% |
| 2BS | 20 | 0.0% | 0 | - |
| divergences | 245 | 16.3% | 0 | - |

DONE total 0.2s
