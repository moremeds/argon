# Cost and turnover — does the 245-name ranking survive being traded?

Quarterly rebalance, 63-day holds, equal-weighted, benchmarked against the equal-weighted panel. Cost per rebalance = turnover x round-trip bps.

Panel IC check (1q): **+0.0376**, t +3.09, 79 quarters — the panel reproduces the validated signal.

| slice | quarters | gross q-alpha | t | hit | ann. turnover | break-even bps |
|---|---:|---:|---:|---:|---:|---:|
| top_10pct | 79 | -0.0007 | -0.09 | 46.8% | 1.31x | -21 |
| bottom_10pct | 79 | +0.0154 | +1.05 | 46.8% | 1.27x | 486 |
| top_20pct | 79 | +0.0007 | +0.15 | 53.2% | 1.08x | 27 |
| bottom_20pct | 79 | +0.0091 | +1.06 | 44.3% | 0.96x | 379 |
| top_33pct | 79 | +0.0006 | +0.16 | 57.0% | 0.81x | 32 |
| bottom_33pct | 79 | +0.0010 | +0.21 | 43.0% | 0.80x | 48 |
| spread_10pct | 79 | -0.0161 | -0.86 | 59.5% | — | na |
| spread_20pct | 79 | -0.0084 | -0.70 | 53.2% | — | na |
| spread_33pct | 79 | -0.0003 | -0.04 | 57.0% | — | na |

## Decile profile — why a positive IC earns nothing

0 = worst composite, 9 = best. `return-rank` is what the IC measures;
`mean` is what an equal-weighted book earns.

| decile | mean return | median return | mean return-rank | n |
|---:|---:|---:|---:|---:|
| 0 | +0.0601 | +0.0149 | 0.475 | 1,916 |
| 1 | +0.0495 | +0.0219 | 0.485 | 1,891 |
| 2 | +0.0373 | +0.0241 | 0.489 | 1,887 |
| 3 | +0.0333 | +0.0260 | 0.489 | 1,879 |
| 4 | +0.0410 | +0.0312 | 0.500 | 1,875 |
| 5 | +0.0479 | +0.0333 | 0.513 | 1,902 |
| 6 | +0.0384 | +0.0331 | 0.510 | 1,886 |
| 7 | +0.0491 | +0.0409 | 0.526 | 1,880 |
| 8 | +0.0511 | +0.0366 | 0.522 | 1,898 |
| 9 | +0.0470 | +0.0247 | 0.493 | 1,845 |

## Net annualized alpha by round-trip cost

| slice | 0 bps | 5 bps | 10 bps | 20 bps | 50 bps |
|---|---:|---:|---:|---:|---:|
| top_10pct | -0.27% | -0.34% | -0.40% | -0.53% | -0.93% |
| bottom_10pct | +6.16% | +6.09% | +6.03% | +5.90% | +5.52% |
| top_20pct | +0.29% | +0.23% | +0.18% | +0.07% | -0.25% |
| bottom_20pct | +3.64% | +3.59% | +3.54% | +3.45% | +3.16% |
| top_33pct | +0.26% | +0.22% | +0.18% | +0.10% | -0.15% |
| bottom_33pct | +0.38% | +0.34% | +0.30% | +0.22% | -0.02% |
