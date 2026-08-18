# Wide bands: instability, or a one-way re-rating?

246 routed names with a usable window; 13 exceed the 4x width limit.

`rho` is `valuation.yield_drift` — the rank correlation of a name's own yield against time, over the same trailing window the band is built from. |rho| >= 0.7 is a one-way walk; near 0 swings both ways. **Yield is the inverse of a multiple**, so a falling yield (negative rho) means the name got more expensive.

- monotone (|rho| >= 0.7) among the 13 refused on width: **5**
- monotone among the 233 that pass: **83**

## Every name refused on width

| ticker | method | width | rho | 1st-half yield | 2nd-half yield | shape | current | last period |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| GE | sales_to_ev | 6.3x | -0.96 | 0.7441 | 0.1797 | re-rated UP | interior | 2026-06-30 |
| MSTR | sales_to_ev | 47.4x | -0.83 | 0.0709 | 0.0094 | re-rated UP | interior | 2026-06-30 |
| ABEO | sales_to_ev | 5.0x | -0.73 | 0.1674 | 0.0258 | re-rated UP | interior | 2026-03-31 |
| APP | sales_to_ev | 5.0x | -0.72 | 0.2176 | 0.0577 | re-rated UP | interior | 2026-06-30 |
| WFC | sales_to_ev | 11.6x | -0.68 | 0.4344 | 0.3312 | swings | interior | 2026-06-30 |
| NBIS | sales_to_ev | 72.3x | -0.67 | 0.6274 | 0.0152 | swings | interior | 2026-03-31 |
| ABUS | sales_to_ev | 5.2x | -0.40 | 0.0703 | 0.0410 | swings | cheapest | 2026-03-31 |
| RIOT | sales_to_ev | 4.3x | -0.32 | 0.3145 | 0.1129 | swings | interior | 2026-03-31 |
| APLD | sales_to_ev | 17.3x | -0.25 | 0.1030 | 0.0835 | swings | interior | 2026-05-31 |
| ACRE | sales_to_ev | 5.3x | -0.07 | 0.0486 | 0.0266 | swings | interior | 2026-06-30 |
| NFLX | fcf_yield | 5.4x | +0.66 | 0.0117 | 0.0226 | swings | interior | 2026-06-30 |
| ABR | sales_to_ev | 4.7x | +0.67 | 0.0534 | 0.0777 | swings | interior | 2026-06-30 |
| DIS | fcf_yield | 7.0x | +0.81 | 0.0125 | 0.0464 | de-rated | interior | 2026-06-30 |
