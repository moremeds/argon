# Which composite construction should ship?

1q horizon, same panel, same metric. `equal_7` is the validated baseline and is verified identical to `V.composite_scores`.

| construction | mean IC | t | quarters |
|---|---:|---:|---:|
| equal_7 | +0.0376 | +3.09 | 79 |
| rubric | +0.0491 | +4.11 | 79 |
| no_margins | +0.0552 | +4.93 | 78 |

## Paired against the validated baseline

Same quarters, matched. Independent t-stats overstate the gap because both series are built from the same features.

| comparison | mean IC diff | paired t | quarters | win rate |
|---|---:|---:|---:|---:|
| rubric_vs_equal_7 | +0.0115 | +1.79 | 79 | 57.0% |
| no_margins_vs_equal_7 | +0.0126 | +2.52 | 78 | 57.7% |

**no_margins is POST-HOC — components were dropped after seeing their realised sign. Diagnostic only; not a shippable candidate without an out-of-sample test.**

