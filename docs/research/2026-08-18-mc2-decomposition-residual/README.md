# Which rates decomposition can actually fail (MC2)

**Measured 2026-08-18.** Reproduce:

```bash
FRED_API_KEY=... uv run python scripts/research/mc2_decomposition_residual_probe.py \
    --out docs/research/2026-08-18-mc2-decomposition-residual
```

Raw per-month rows: [`residuals.json`](residuals.json) (332 months, 1999-01 → 2026-08).

## Why this exists

The MC2 plan asks for a test over "decompositions whose components do not add within
tolerance". Two of the three candidate decompositions in this domain **cannot fail**,
and building tolerance tests over them would assert identities against themselves.

| decomposition | can it fail? | measured |
|---|---|---|
| `DGS10 = DFII10 + T10YIE` | **No** — FRED *derives* `T10YIE` as `DGS10 − DFII10` | 0.0bp residual in both probed yield episodes |
| Cleveland components → Cleveland modelled nominal | **No** — the expected short real rate is *defined* as modelled real yield minus real term premium, so adding the premium back is a no-op | **max abs residual 0.0bp across all 332 months** |
| Cleveland modelled nominal vs **traded** `DGS10` | **Yes** | see below |

Only the third compares two independently produced numbers, so it is the only one the
engine raises `decomposition_components_do_not_reconcile` over.

## What the surviving residual actually looks like

| window | median | p75 | p90 | max |
|---|---|---|---|---|
| 1999-01 → 2026-08 (n=332) | 41.1bp | 63.4bp | 76.7bp | 127.9bp |
| 2016-01 → 2026-08 | 63.3bp | 77.0bp | 84.4bp | 127.9bp |

**The model and the market normally disagree by half a percentage point.** That is the
resting state, not an anomaly. A tolerance anywhere near zero is therefore useless:

| tolerance | share of months that would fire |
|---|---|
| 25bp | **66.9%** |
| 50bp | 40.1% |
| 85bp | 3.3% |

A 25bp tolerance — the value the engine carried before this was measured — would have
fired on two months in three and carried no information at all.

## The tolerance the engine uses, and why

**85bp**, roughly the p90 of the post-2016 residual. It fires on 11 of 332 months, and
those 11 are not scattered: **every one of them falls in 2022**, the tightening shock,
when the traded yield repriced faster than a monthly model could follow. The rule
therefore says something specific — "the market has moved somewhere the model has not
yet reached" — rather than reporting the model's permanent offset as news.

Anchors used in `tests/unit/macro/test_rates_state.py`, all real:

| month | traded | modelled | residual | fires |
|---|---|---|---|---|
| 2022-04 | 2.39 | 3.669 | −127.9bp | yes |
| 2025-01 | 4.57 | 5.004 | −43.4bp | no |
| 2023-07 | 3.86 | 3.674 | +18.6bp | no |

## What this residual is not

It is **not** a term premium estimate, and it is not evidence about one. It is the gap
between one model's output and one traded price. The only term-premium figure in this
domain is the Cleveland model's own `real_risk_premium_10y`, which carries its own
vintage and its own uncertainty.
