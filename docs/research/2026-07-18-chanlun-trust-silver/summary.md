# Chanlun trust probe — silver (adjusted) daily bars

Tickers: 223 | Edge horizons: [1, 3, 5, 10, 20] | Markout horizons: [1, 3, 5, 10, 20, 40, 60]
Entry: confirmation (honest, point-in-time) vs extreme (hindsight ghost).
Reproduce: `uv run python scripts/research/chanlun_trust_probe.py`

Two baselines for `edge = signed_ret − baseline`, both scored ONLY on marks that eventually confirmed: **unconditional** (same-ticker mean forward return) and **state-conditioned** (mean forward return of same-ticker bars in the same trailing-20-session momentum quantile bucket). The state baseline isolates the signal's marginal value beyond the regime it fires in — a 底背离 fires after a decline, so the unconditional edge partly just captures generic post-decline drift. `ci_excludes_zero` = cluster-bootstrap 95% CI (resampled by ticker) entirely one side of 0.

Caveats: (1) the CI resamples tickers for within-ticker overlap but still assumes tickers are independent and ignores residual serial correlation — **suggestive, not a p-value**. (2) **Multiple comparisons**: ~80 cells flagged at 95% → ~4 false positives expected by chance; trust a category only where the sign is consistent ACROSS horizons and survives the state baseline + both period-halves, not single flagged cells. (3) **Economic floor**: a confirmation edge below ~0.15% round-trip cost is not capturable regardless of significance. (4) `retraction_rate` counts supersession (mark migrating to a more-extreme endpoint) as retracted. (5) NOT a strategy: no sizing; mega-cap survivorship → edge is an upper bound.

## 1. Repaint stability + confirmation lag

`retraction_rate` = confirmed-live marks that are no longer confirmed in the final series. `median_lag`/`p90_lag` = sessions from extreme to first confirmed=true — this lag is exactly the lookahead the extreme (ghost) entry illegitimately banks.

| category | n_marks | n_confirmed | retraction_rate | median_lag | p90_lag |
|---|---|---|---|---|---|
| 1B | 980 | 241 | 0.336 | 8 | 11 |
| 1S | 2708 | 649 | 0.243 | 7 | 10 |
| 2B | 864 | 58 | 0.000 | 7.0 | 11 |
| 2S | 2106 | 111 | 0.000 | 7 | 12 |
| 3B | 23453 | 1966 | 0.000 | 8.0 | 11 |
| 3S | 16151 | 1094 | 0.000 | 8.0 | 12 |
| divergence | 29329 | 4377 | 0.000 | 8 | 12 |
| vertex | 196046 | 22935 | 0.000 | 8 | 13 |

## 2. Forward-return edge — UNCONDITIONAL baseline (confirmation = honest; extreme = ghost)

| category | entry | horizon | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 |
|---|---|---|---|---|---|---|---|---|
| 1B | confirmation | 1 | 241 | 0.506 | +0.0017 | -0.0029 | +0.0057 |  |
| 1B | confirmation | 3 | 241 | 0.527 | +0.0015 | -0.0061 | +0.0084 |  |
| 1B | confirmation | 5 | 240 | 0.596 | +0.0049 | -0.0050 | +0.0139 |  |
| 1B | confirmation | 10 | 238 | 0.609 | +0.0134 | +0.0004 | +0.0271 | yes |
| 1B | confirmation | 20 | 235 | 0.630 | +0.0145 | -0.0033 | +0.0322 |  |
| 1B | extreme | 1 | 241 | 0.809 | +0.0180 | +0.0146 | +0.0212 | yes |
| 1B | extreme | 3 | 241 | 0.863 | +0.0307 | +0.0259 | +0.0359 | yes |
| 1B | extreme | 5 | 241 | 0.880 | +0.0375 | +0.0325 | +0.0430 | yes |
| 1B | extreme | 10 | 241 | 0.780 | +0.0312 | +0.0214 | +0.0400 | yes |
| 1B | extreme | 20 | 238 | 0.727 | +0.0416 | +0.0281 | +0.0555 | yes |
| 1S | confirmation | 1 | 647 | 0.461 | +0.0004 | -0.0007 | +0.0016 |  |
| 1S | confirmation | 3 | 646 | 0.449 | +0.0002 | -0.0019 | +0.0022 |  |
| 1S | confirmation | 5 | 645 | 0.474 | +0.0035 | +0.0005 | +0.0062 | yes |
| 1S | confirmation | 10 | 643 | 0.454 | +0.0041 | +0.0002 | +0.0082 | yes |
| 1S | confirmation | 20 | 634 | 0.462 | -0.0108 | -0.0565 | +0.0135 |  |
| 1S | extreme | 1 | 649 | 0.838 | +0.0126 | +0.0113 | +0.0139 | yes |
| 1S | extreme | 3 | 649 | 0.864 | +0.0212 | +0.0194 | +0.0232 | yes |
| 1S | extreme | 5 | 649 | 0.866 | +0.0257 | +0.0236 | +0.0280 | yes |
| 1S | extreme | 10 | 646 | 0.675 | +0.0235 | +0.0203 | +0.0268 | yes |
| 1S | extreme | 20 | 639 | 0.538 | +0.0068 | -0.0356 | +0.0295 |  |
| 2B | confirmation | 1 | 58 | 0.500 | +0.0014 | -0.0037 | +0.0064 |  |
| 2B | confirmation | 3 | 58 | 0.603 | +0.0057 | -0.0068 | +0.0193 |  |
| 2B | confirmation | 5 | 57 | 0.544 | +0.0073 | -0.0060 | +0.0222 |  |
| 2B | confirmation | 10 | 57 | 0.561 | -0.0036 | -0.0192 | +0.0107 |  |
| 2B | confirmation | 20 | 57 | 0.649 | +0.0063 | -0.0126 | +0.0247 |  |
| 2B | extreme | 1 | 58 | 0.914 | +0.0240 | +0.0171 | +0.0310 | yes |
| 2B | extreme | 3 | 58 | 0.948 | +0.0443 | +0.0344 | +0.0545 | yes |
| 2B | extreme | 5 | 58 | 0.966 | +0.0591 | +0.0465 | +0.0728 | yes |
| 2B | extreme | 10 | 57 | 0.842 | +0.0617 | +0.0436 | +0.0823 | yes |
| 2B | extreme | 20 | 57 | 0.754 | +0.0570 | +0.0345 | +0.0784 | yes |
| 2S | confirmation | 1 | 111 | 0.414 | -0.0012 | -0.0043 | +0.0022 |  |
| 2S | confirmation | 3 | 111 | 0.405 | +0.0004 | -0.0047 | +0.0058 |  |
| 2S | confirmation | 5 | 111 | 0.405 | -0.0010 | -0.0068 | +0.0052 |  |
| 2S | confirmation | 10 | 111 | 0.450 | +0.0052 | -0.0038 | +0.0150 |  |
| 2S | confirmation | 20 | 111 | 0.396 | +0.0017 | -0.0116 | +0.0147 |  |
| 2S | extreme | 1 | 111 | 0.811 | +0.0119 | +0.0093 | +0.0150 | yes |
| 2S | extreme | 3 | 111 | 0.928 | +0.0284 | +0.0222 | +0.0360 | yes |
| 2S | extreme | 5 | 111 | 0.919 | +0.0422 | +0.0337 | +0.0524 | yes |
| 2S | extreme | 10 | 111 | 0.811 | +0.0480 | +0.0372 | +0.0609 | yes |
| 2S | extreme | 20 | 111 | 0.712 | +0.0531 | +0.0407 | +0.0689 | yes |
| 3B | confirmation | 1 | 1966 | 0.523 | -0.0002 | -0.0012 | +0.0007 |  |
| 3B | confirmation | 3 | 1963 | 0.515 | -0.0025 | -0.0040 | -0.0008 | yes |
| 3B | confirmation | 5 | 1955 | 0.531 | -0.0025 | -0.0044 | -0.0005 | yes |
| 3B | confirmation | 10 | 1941 | 0.547 | -0.0049 | -0.0077 | -0.0019 | yes |
| 3B | confirmation | 20 | 1928 | 0.546 | -0.0087 | -0.0123 | -0.0047 | yes |
| 3B | extreme | 1 | 1966 | 0.860 | +0.0135 | +0.0125 | +0.0145 | yes |
| 3B | extreme | 3 | 1966 | 0.932 | +0.0271 | +0.0253 | +0.0292 | yes |
| 3B | extreme | 5 | 1966 | 0.947 | +0.0341 | +0.0317 | +0.0366 | yes |
| 3B | extreme | 10 | 1963 | 0.843 | +0.0423 | +0.0335 | +0.0577 | yes |
| 3B | extreme | 20 | 1941 | 0.730 | +0.0363 | +0.0269 | +0.0515 | yes |
| 3S | confirmation | 1 | 1093 | 0.481 | -0.0010 | -0.0026 | +0.0006 |  |
| 3S | confirmation | 3 | 1093 | 0.492 | +0.0049 | +0.0020 | +0.0080 | yes |
| 3S | confirmation | 5 | 1093 | 0.484 | +0.0047 | +0.0014 | +0.0081 | yes |
| 3S | confirmation | 10 | 1086 | 0.459 | +0.0016 | -0.0025 | +0.0059 |  |
| 3S | confirmation | 20 | 1084 | 0.407 | -0.0086 | -0.0137 | -0.0031 | yes |
| 3S | extreme | 1 | 1094 | 0.846 | +0.0170 | +0.0155 | +0.0186 | yes |
| 3S | extreme | 3 | 1094 | 0.915 | +0.0353 | +0.0325 | +0.0382 | yes |
| 3S | extreme | 5 | 1094 | 0.919 | +0.0437 | +0.0401 | +0.0474 | yes |
| 3S | extreme | 10 | 1093 | 0.814 | +0.0540 | +0.0488 | +0.0592 | yes |
| 3S | extreme | 20 | 1086 | 0.670 | +0.0493 | +0.0427 | +0.0558 | yes |
| divergence | confirmation | 1 | 4366 | 0.478 | -0.0005 | -0.0012 | +0.0001 |  |
| divergence | confirmation | 3 | 4363 | 0.499 | +0.0013 | +0.0003 | +0.0024 | yes |
| divergence | confirmation | 5 | 4351 | 0.508 | +0.0030 | +0.0015 | +0.0045 | yes |
| divergence | confirmation | 10 | 4324 | 0.522 | +0.0053 | +0.0032 | +0.0072 | yes |
| divergence | confirmation | 20 | 4289 | 0.519 | +0.0046 | -0.0023 | +0.0095 |  |
| divergence | extreme | 1 | 4377 | 0.821 | +0.0151 | +0.0142 | +0.0160 | yes |
| divergence | extreme | 3 | 4377 | 0.906 | +0.0304 | +0.0288 | +0.0322 | yes |
| divergence | extreme | 5 | 4377 | 0.925 | +0.0397 | +0.0377 | +0.0418 | yes |
| divergence | extreme | 10 | 4364 | 0.806 | +0.0428 | +0.0405 | +0.0451 | yes |
| divergence | extreme | 20 | 4321 | 0.714 | +0.0474 | +0.0404 | +0.0524 | yes |

## 3. Forward-return edge — STATE-CONDITIONED baseline (the honest test of marginal value)

| category | entry | horizon | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 |
|---|---|---|---|---|---|---|---|---|
| 1B | confirmation | 1 | 241 | 0.506 | +0.0015 | -0.0030 | +0.0056 |  |
| 1B | confirmation | 3 | 241 | 0.527 | +0.0010 | -0.0065 | +0.0079 |  |
| 1B | confirmation | 5 | 240 | 0.596 | +0.0042 | -0.0052 | +0.0130 |  |
| 1B | confirmation | 10 | 238 | 0.609 | +0.0120 | -0.0004 | +0.0254 |  |
| 1B | confirmation | 20 | 235 | 0.630 | +0.0131 | -0.0034 | +0.0297 |  |
| 1B | extreme | 1 | 241 | 0.809 | +0.0176 | +0.0143 | +0.0209 | yes |
| 1B | extreme | 3 | 241 | 0.863 | +0.0294 | +0.0246 | +0.0348 | yes |
| 1B | extreme | 5 | 241 | 0.880 | +0.0356 | +0.0303 | +0.0413 | yes |
| 1B | extreme | 10 | 241 | 0.780 | +0.0279 | +0.0187 | +0.0367 | yes |
| 1B | extreme | 20 | 238 | 0.727 | +0.0377 | +0.0258 | +0.0508 | yes |
| 1S | confirmation | 1 | 647 | 0.461 | +0.0004 | -0.0008 | +0.0016 |  |
| 1S | confirmation | 3 | 646 | 0.449 | -0.0001 | -0.0023 | +0.0019 |  |
| 1S | confirmation | 5 | 645 | 0.474 | +0.0029 | +0.0000 | +0.0057 | yes |
| 1S | confirmation | 10 | 643 | 0.454 | +0.0030 | -0.0009 | +0.0073 |  |
| 1S | confirmation | 20 | 634 | 0.462 | -0.0130 | -0.0569 | +0.0104 |  |
| 1S | extreme | 1 | 649 | 0.838 | +0.0124 | +0.0112 | +0.0138 | yes |
| 1S | extreme | 3 | 649 | 0.864 | +0.0206 | +0.0188 | +0.0226 | yes |
| 1S | extreme | 5 | 649 | 0.866 | +0.0247 | +0.0226 | +0.0272 | yes |
| 1S | extreme | 10 | 646 | 0.675 | +0.0217 | +0.0183 | +0.0252 | yes |
| 1S | extreme | 20 | 639 | 0.538 | +0.0025 | -0.0382 | +0.0246 |  |
| 2B | confirmation | 1 | 58 | 0.500 | +0.0016 | -0.0035 | +0.0066 |  |
| 2B | confirmation | 3 | 58 | 0.603 | +0.0062 | -0.0062 | +0.0199 |  |
| 2B | confirmation | 5 | 57 | 0.544 | +0.0084 | -0.0044 | +0.0231 |  |
| 2B | confirmation | 10 | 57 | 0.561 | -0.0018 | -0.0174 | +0.0129 |  |
| 2B | confirmation | 20 | 57 | 0.649 | +0.0098 | -0.0082 | +0.0279 |  |
| 2B | extreme | 1 | 58 | 0.914 | +0.0240 | +0.0171 | +0.0310 | yes |
| 2B | extreme | 3 | 58 | 0.948 | +0.0442 | +0.0343 | +0.0543 | yes |
| 2B | extreme | 5 | 58 | 0.966 | +0.0585 | +0.0461 | +0.0719 | yes |
| 2B | extreme | 10 | 57 | 0.842 | +0.0608 | +0.0434 | +0.0810 | yes |
| 2B | extreme | 20 | 57 | 0.754 | +0.0566 | +0.0347 | +0.0774 | yes |
| 2S | confirmation | 1 | 111 | 0.414 | -0.0013 | -0.0044 | +0.0020 |  |
| 2S | confirmation | 3 | 111 | 0.405 | +0.0006 | -0.0047 | +0.0058 |  |
| 2S | confirmation | 5 | 111 | 0.405 | -0.0007 | -0.0065 | +0.0054 |  |
| 2S | confirmation | 10 | 111 | 0.450 | +0.0064 | -0.0027 | +0.0162 |  |
| 2S | confirmation | 20 | 111 | 0.396 | +0.0049 | -0.0085 | +0.0185 |  |
| 2S | extreme | 1 | 111 | 0.811 | +0.0119 | +0.0093 | +0.0151 | yes |
| 2S | extreme | 3 | 111 | 0.928 | +0.0282 | +0.0220 | +0.0356 | yes |
| 2S | extreme | 5 | 111 | 0.919 | +0.0415 | +0.0331 | +0.0516 | yes |
| 2S | extreme | 10 | 111 | 0.811 | +0.0465 | +0.0356 | +0.0594 | yes |
| 2S | extreme | 20 | 111 | 0.712 | +0.0519 | +0.0398 | +0.0669 | yes |
| 3B | confirmation | 1 | 1966 | 0.523 | -0.0002 | -0.0011 | +0.0007 |  |
| 3B | confirmation | 3 | 1963 | 0.515 | -0.0022 | -0.0038 | -0.0006 | yes |
| 3B | confirmation | 5 | 1955 | 0.531 | -0.0022 | -0.0041 | -0.0002 | yes |
| 3B | confirmation | 10 | 1941 | 0.547 | -0.0044 | -0.0072 | -0.0014 | yes |
| 3B | confirmation | 20 | 1928 | 0.546 | -0.0077 | -0.0114 | -0.0039 | yes |
| 3B | extreme | 1 | 1966 | 0.860 | +0.0135 | +0.0125 | +0.0145 | yes |
| 3B | extreme | 3 | 1966 | 0.932 | +0.0272 | +0.0253 | +0.0292 | yes |
| 3B | extreme | 5 | 1966 | 0.947 | +0.0342 | +0.0319 | +0.0368 | yes |
| 3B | extreme | 10 | 1963 | 0.843 | +0.0428 | +0.0340 | +0.0582 | yes |
| 3B | extreme | 20 | 1941 | 0.730 | +0.0372 | +0.0280 | +0.0523 | yes |
| 3S | confirmation | 1 | 1093 | 0.481 | -0.0010 | -0.0026 | +0.0005 |  |
| 3S | confirmation | 3 | 1093 | 0.492 | +0.0049 | +0.0020 | +0.0078 | yes |
| 3S | confirmation | 5 | 1093 | 0.484 | +0.0045 | +0.0015 | +0.0078 | yes |
| 3S | confirmation | 10 | 1086 | 0.459 | +0.0016 | -0.0022 | +0.0057 |  |
| 3S | confirmation | 20 | 1084 | 0.407 | -0.0080 | -0.0128 | -0.0030 | yes |
| 3S | extreme | 1 | 1094 | 0.846 | +0.0170 | +0.0155 | +0.0186 | yes |
| 3S | extreme | 3 | 1094 | 0.915 | +0.0354 | +0.0326 | +0.0382 | yes |
| 3S | extreme | 5 | 1094 | 0.919 | +0.0439 | +0.0404 | +0.0474 | yes |
| 3S | extreme | 10 | 1093 | 0.814 | +0.0548 | +0.0499 | +0.0597 | yes |
| 3S | extreme | 20 | 1086 | 0.670 | +0.0515 | +0.0453 | +0.0576 | yes |
| divergence | confirmation | 1 | 4366 | 0.478 | -0.0005 | -0.0012 | +0.0001 |  |
| divergence | confirmation | 3 | 4363 | 0.499 | +0.0013 | +0.0001 | +0.0024 | yes |
| divergence | confirmation | 5 | 4351 | 0.508 | +0.0028 | +0.0012 | +0.0044 | yes |
| divergence | confirmation | 10 | 4324 | 0.522 | +0.0050 | +0.0028 | +0.0072 | yes |
| divergence | confirmation | 20 | 4289 | 0.519 | +0.0043 | -0.0014 | +0.0084 |  |
| divergence | extreme | 1 | 4377 | 0.821 | +0.0149 | +0.0140 | +0.0158 | yes |
| divergence | extreme | 3 | 4377 | 0.906 | +0.0297 | +0.0280 | +0.0315 | yes |
| divergence | extreme | 5 | 4377 | 0.925 | +0.0386 | +0.0365 | +0.0408 | yes |
| divergence | extreme | 10 | 4364 | 0.806 | +0.0408 | +0.0384 | +0.0434 | yes |
| divergence | extreme | 20 | 4321 | 0.714 | +0.0437 | +0.0383 | +0.0481 | yes |

## 4. Period robustness — confirmation entry, state edge, first vs second half

An edge that flips sign between a ticker's first and second half is a period artifact. `same_sign` = both halves agree.

| category | horizon | n_h1 | n_h2 | edge_h1 | edge_h2 | same_sign |
|---|---|---|---|---|---|---|
| 1B | 1 | 144 | 97 | +0.0005 | +0.0030 | yes |
| 1B | 3 | 144 | 97 | +0.0001 | +0.0023 | yes |
| 1B | 5 | 144 | 96 | +0.0032 | +0.0057 | yes |
| 1B | 10 | 144 | 94 | +0.0161 | +0.0058 | yes |
| 1B | 20 | 144 | 91 | +0.0204 | +0.0016 | yes |
| 1S | 1 | 211 | 436 | +0.0019 | -0.0004 | NO |
| 1S | 3 | 211 | 435 | +0.0037 | -0.0019 | NO |
| 1S | 5 | 211 | 434 | +0.0111 | -0.0010 | NO |
| 1S | 10 | 211 | 432 | +0.0164 | -0.0035 | NO |
| 1S | 20 | 211 | 423 | +0.0177 | -0.0284 | NO |
| 2B | 1 | 30 | 28 | +0.0037 | -0.0007 | NO |
| 2B | 3 | 30 | 28 | +0.0133 | -0.0015 | NO |
| 2B | 5 | 30 | 27 | +0.0190 | -0.0033 | NO |
| 2B | 10 | 30 | 27 | +0.0102 | -0.0153 | NO |
| 2B | 20 | 30 | 27 | +0.0185 | +0.0002 | yes |
| 2S | 1 | 41 | 70 | +0.0002 | -0.0021 | NO |
| 2S | 3 | 41 | 70 | +0.0014 | +0.0001 | yes |
| 2S | 5 | 41 | 70 | -0.0013 | -0.0003 | yes |
| 2S | 10 | 41 | 70 | +0.0121 | +0.0031 | yes |
| 2S | 20 | 41 | 70 | +0.0169 | -0.0021 | NO |
| 3B | 1 | 756 | 1210 | -0.0004 | -0.0001 | yes |
| 3B | 3 | 756 | 1207 | -0.0039 | -0.0012 | yes |
| 3B | 5 | 756 | 1199 | -0.0043 | -0.0008 | yes |
| 3B | 10 | 756 | 1185 | -0.0100 | -0.0008 | yes |
| 3B | 20 | 756 | 1172 | -0.0198 | +0.0000 | NO |
| 3S | 1 | 611 | 482 | +0.0000 | -0.0023 | NO |
| 3S | 3 | 611 | 482 | +0.0012 | +0.0096 | yes |
| 3S | 5 | 611 | 482 | +0.0013 | +0.0086 | yes |
| 3S | 10 | 611 | 475 | -0.0021 | +0.0065 | NO |
| 3S | 20 | 611 | 473 | -0.0078 | -0.0083 | yes |
| divergence | 1 | 2038 | 2328 | -0.0016 | +0.0004 | NO |
| divergence | 3 | 2038 | 2325 | +0.0002 | +0.0022 | yes |
| divergence | 5 | 2038 | 2313 | +0.0023 | +0.0032 | yes |
| divergence | 10 | 2038 | 2286 | +0.0053 | +0.0048 | yes |
| divergence | 20 | 2038 | 2251 | +0.0076 | +0.0013 | yes |

## 5. Markout + breach-survival (how long is the signal valid?)

From the confirmation bar forward: `mean_markout` = mean signed return path; `survival` = fraction whose extreme has NOT been breached by day t (bottom: price never re-broke the low; top: never re-broke the high); `breach_rate` = 1 − survival; `bounced_breach_rate` = among marks that first moved the predicted way within 5d, how often they still breached by t (the 'bounced then failed' case you asked about).

| category | horizon | n | mean_markout | survival | breach_rate | bounced_breach_rate |
|---|---|---|---|---|---|---|
| 1B | 1 | 241 | +0.0023 | 0.867 | 0.133 | 0.091 |
| 1B | 3 | 241 | +0.0033 | 0.726 | 0.274 | 0.161 |
| 1B | 5 | 240 | +0.0080 | 0.683 | 0.317 | 0.182 |
| 1B | 10 | 238 | +0.0197 | 0.588 | 0.412 | 0.220 |
| 1B | 20 | 235 | +0.0270 | 0.464 | 0.536 | 0.343 |
| 1B | 40 | 230 | +0.0409 | 0.374 | 0.626 | 0.478 |
| 1B | 60 | 226 | +0.0495 | 0.296 | 0.704 | 0.596 |
| 1S | 1 | 647 | -0.0005 | 0.794 | 0.206 | 0.147 |
| 1S | 3 | 646 | -0.0026 | 0.633 | 0.367 | 0.206 |
| 1S | 5 | 645 | -0.0011 | 0.547 | 0.453 | 0.219 |
| 1S | 10 | 643 | -0.0051 | 0.415 | 0.585 | 0.328 |
| 1S | 20 | 634 | -0.0294 | 0.301 | 0.699 | 0.508 |
| 1S | 40 | 629 | -0.0437 | 0.196 | 0.804 | 0.671 |
| 1S | 60 | 622 | -0.0325 | 0.137 | 0.863 | 0.778 |
| 2B | 1 | 58 | +0.0020 | 0.914 | 0.086 | 0.032 |
| 2B | 3 | 58 | +0.0074 | 0.828 | 0.172 | 0.032 |
| 2B | 5 | 57 | +0.0100 | 0.754 | 0.246 | 0.032 |
| 2B | 10 | 57 | +0.0019 | 0.667 | 0.333 | 0.065 |
| 2B | 20 | 57 | +0.0173 | 0.596 | 0.404 | 0.161 |
| 2B | 40 | 56 | +0.0241 | 0.464 | 0.536 | 0.367 |
| 2B | 60 | 53 | +0.0699 | 0.396 | 0.604 | 0.517 |
| 2S | 1 | 111 | -0.0021 | 0.838 | 0.162 | 0.178 |
| 2S | 3 | 111 | -0.0022 | 0.703 | 0.297 | 0.178 |
| 2S | 5 | 111 | -0.0054 | 0.649 | 0.351 | 0.178 |
| 2S | 10 | 111 | -0.0036 | 0.568 | 0.432 | 0.200 |
| 2S | 20 | 111 | -0.0160 | 0.441 | 0.559 | 0.356 |
| 2S | 40 | 110 | -0.0236 | 0.264 | 0.736 | 0.578 |
| 2S | 60 | 110 | -0.0394 | 0.227 | 0.773 | 0.622 |
| 3B | 1 | 1966 | +0.0006 | 0.885 | 0.115 | 0.087 |
| 3B | 3 | 1963 | +0.0002 | 0.788 | 0.212 | 0.111 |
| 3B | 5 | 1955 | +0.0018 | 0.731 | 0.269 | 0.115 |
| 3B | 10 | 1941 | +0.0037 | 0.620 | 0.380 | 0.184 |
| 3B | 20 | 1928 | +0.0086 | 0.506 | 0.494 | 0.314 |
| 3B | 40 | 1897 | +0.0276 | 0.394 | 0.606 | 0.450 |
| 3B | 60 | 1873 | +0.0413 | 0.341 | 0.659 | 0.522 |
| 3S | 1 | 1093 | -0.0017 | 0.870 | 0.130 | 0.113 |
| 3S | 3 | 1093 | +0.0027 | 0.782 | 0.218 | 0.138 |
| 3S | 5 | 1093 | +0.0010 | 0.701 | 0.299 | 0.146 |
| 3S | 10 | 1086 | -0.0058 | 0.578 | 0.422 | 0.236 |
| 3S | 20 | 1084 | -0.0233 | 0.436 | 0.564 | 0.381 |
| 3S | 40 | 1071 | -0.0468 | 0.244 | 0.756 | 0.646 |
| 3S | 60 | 1047 | -0.0517 | 0.192 | 0.808 | 0.719 |
| divergence | 1 | 4366 | -0.0007 | 0.881 | 0.119 | 0.080 |
| divergence | 3 | 4363 | +0.0009 | 0.786 | 0.214 | 0.105 |
| divergence | 5 | 4351 | +0.0023 | 0.715 | 0.285 | 0.110 |
| divergence | 10 | 4324 | +0.0040 | 0.605 | 0.395 | 0.175 |
| divergence | 20 | 4289 | +0.0019 | 0.503 | 0.497 | 0.291 |
| divergence | 40 | 4199 | +0.0009 | 0.384 | 0.616 | 0.445 |
| divergence | 60 | 4151 | -0.0040 | 0.316 | 0.684 | 0.533 |

### Time-to-breach (sessions until the extreme is first re-broken)

| category | n_breached | median_time_to_breach | p90_time_to_breach |
|---|---|---|---|
| 1B | 168 | 7.0 | 43 |
| 1S | 561 | 5 | 30 |
| 2B | 35 | 7 | 42 |
| 2S | 86 | 8.0 | 35 |
| 3B | 1261 | 8 | 35 |
| 3S | 878 | 9.5 | 35 |
| divergence | 2956 | 8.0 | 40 |

## 6. Conditioning experiments (Phase 1) — confirmation entry, state edge, h∈[5, 10]

Does filtering confirmed marks lift the edge? `trend` = 200-DMA agreement (bottom above / top below — the most-replicated mean-reversion filter); `depth` = fired from an extreme trailing-momentum bucket in the signal's direction (deep-oversold bottom / sharp-rally top); `trend+depth` = both. A conditioner earns its keep only if `mean_edge` rises MATERIALLY over `all`, `CI≠0`, AND `same_sign` holds across both period-halves — otherwise it is sample-slicing. Watch `n`: a great edge on n<40 is noise.

| category | horizon | filter | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 | robust |
|---|---|---|---|---|---|---|---|---|---|
| 1B | 5 | all | 240 | 0.596 | +0.0042 | -0.0052 | +0.0130 |  | yes |
| 1B | 5 | trend | 0 | nan | +nan | +nan | +nan |  |  |
| 1B | 5 | depth | 196 | 0.607 | +0.0041 | -0.0080 | +0.0144 |  | yes |
| 1B | 5 | trend+depth | 0 | nan | +nan | +nan | +nan |  |  |
| 1B | 10 | all | 238 | 0.609 | +0.0120 | -0.0004 | +0.0254 |  | yes |
| 1B | 10 | trend | 0 | nan | +nan | +nan | +nan |  |  |
| 1B | 10 | depth | 194 | 0.598 | +0.0102 | -0.0048 | +0.0240 |  | yes |
| 1B | 10 | trend+depth | 0 | nan | +nan | +nan | +nan |  |  |
| 1S | 5 | all | 645 | 0.474 | +0.0029 | +0.0000 | +0.0057 | yes |  |
| 1S | 5 | trend | 3 | 0.000 | -0.0835 | -0.1741 | -0.0079 | yes | yes |
| 1S | 5 | depth | 407 | 0.479 | +0.0018 | -0.0023 | +0.0057 |  |  |
| 1S | 5 | trend+depth | 2 | 0.000 | -0.1213 | -0.1741 | -0.0684 | yes | yes |
| 1S | 10 | all | 643 | 0.454 | +0.0030 | -0.0009 | +0.0073 |  |  |
| 1S | 10 | trend | 3 | 0.000 | -0.0566 | -0.0824 | -0.0431 | yes | yes |
| 1S | 10 | depth | 406 | 0.448 | +0.0019 | -0.0036 | +0.0078 |  |  |
| 1S | 10 | trend+depth | 2 | 0.000 | -0.0628 | -0.0824 | -0.0431 | yes | yes |
| 2B | 5 | all | 57 | 0.544 | +0.0084 | -0.0044 | +0.0231 |  |  |
| 2B | 5 | trend | 2 | 1.000 | +0.0066 | +0.0059 | +0.0073 | yes |  |
| 2B | 5 | depth | 10 | 0.500 | +0.0195 | -0.0137 | +0.0542 |  | yes |
| 2B | 5 | trend+depth | 0 | nan | +nan | +nan | +nan |  |  |
| 2B | 10 | all | 57 | 0.561 | -0.0018 | -0.0174 | +0.0129 |  |  |
| 2B | 10 | trend | 2 | 0.500 | +0.0068 | -0.0209 | +0.0345 |  |  |
| 2B | 10 | depth | 10 | 0.700 | +0.0110 | -0.0173 | +0.0414 |  |  |
| 2B | 10 | trend+depth | 0 | nan | +nan | +nan | +nan |  |  |
| 2S | 5 | all | 111 | 0.405 | -0.0007 | -0.0065 | +0.0054 |  | yes |
| 2S | 5 | trend | 7 | 0.571 | +0.0124 | -0.0126 | +0.0362 |  | yes |
| 2S | 5 | depth | 10 | 0.400 | -0.0154 | -0.0413 | +0.0084 |  | yes |
| 2S | 5 | trend+depth | 0 | nan | +nan | +nan | +nan |  |  |
| 2S | 10 | all | 111 | 0.450 | +0.0064 | -0.0027 | +0.0162 |  | yes |
| 2S | 10 | trend | 7 | 0.571 | +0.0067 | -0.0087 | +0.0214 |  | yes |
| 2S | 10 | depth | 10 | 0.400 | -0.0111 | -0.0514 | +0.0288 |  | yes |
| 2S | 10 | trend+depth | 0 | nan | +nan | +nan | +nan |  |  |
| 3B | 5 | all | 1955 | 0.531 | -0.0022 | -0.0041 | -0.0002 | yes | yes |
| 3B | 5 | trend | 1649 | 0.540 | -0.0019 | -0.0040 | +0.0001 |  | yes |
| 3B | 5 | depth | 463 | 0.529 | -0.0040 | -0.0077 | -0.0004 | yes | yes |
| 3B | 5 | trend+depth | 370 | 0.546 | -0.0042 | -0.0083 | -0.0000 | yes | yes |
| 3B | 10 | all | 1941 | 0.547 | -0.0044 | -0.0072 | -0.0014 | yes | yes |
| 3B | 10 | trend | 1637 | 0.564 | -0.0030 | -0.0061 | +0.0002 |  | yes |
| 3B | 10 | depth | 460 | 0.561 | -0.0090 | -0.0150 | -0.0035 | yes |  |
| 3B | 10 | trend+depth | 368 | 0.595 | -0.0053 | -0.0115 | +0.0004 |  |  |
| 3S | 5 | all | 1093 | 0.484 | +0.0045 | +0.0015 | +0.0078 | yes | yes |
| 3S | 5 | trend | 817 | 0.475 | +0.0034 | -0.0004 | +0.0073 |  |  |
| 3S | 5 | depth | 167 | 0.557 | +0.0088 | +0.0015 | +0.0161 | yes | yes |
| 3S | 5 | trend+depth | 123 | 0.520 | +0.0045 | -0.0041 | +0.0133 |  | yes |
| 3S | 10 | all | 1086 | 0.459 | +0.0016 | -0.0022 | +0.0057 |  |  |
| 3S | 10 | trend | 811 | 0.454 | -0.0002 | -0.0050 | +0.0046 |  |  |
| 3S | 10 | depth | 166 | 0.566 | +0.0166 | +0.0056 | +0.0274 | yes | yes |
| 3S | 10 | trend+depth | 122 | 0.516 | +0.0108 | +0.0008 | +0.0221 | yes | yes |
| divergence | 5 | all | 4351 | 0.508 | +0.0028 | +0.0012 | +0.0044 | yes | yes |
| divergence | 5 | trend | 1035 | 0.543 | +0.0030 | +0.0001 | +0.0059 | yes | yes |
| divergence | 5 | depth | 2029 | 0.493 | +0.0006 | -0.0014 | +0.0026 |  |  |
| divergence | 5 | trend+depth | 374 | 0.527 | +0.0009 | -0.0037 | +0.0057 |  | yes |
| divergence | 10 | all | 4324 | 0.522 | +0.0050 | +0.0028 | +0.0072 | yes | yes |
| divergence | 10 | trend | 1029 | 0.569 | +0.0065 | +0.0025 | +0.0105 | yes | yes |
| divergence | 10 | depth | 2012 | 0.524 | +0.0036 | +0.0009 | +0.0065 | yes | yes |
| divergence | 10 | trend+depth | 371 | 0.580 | +0.0078 | +0.0015 | +0.0149 | yes | yes |

## 7. Phase-2 GEX dealer-gamma regime gate (orthogonal data, ~2023-08→present, h∈[5, 10])

Only confirmations in the UW GEX window (~2.8y — the tier caps single-name history at ~730 trading days) get a regime, so `in-window` n is roughly HALF the pooled divergence count; the pre-2023-08 signals are dark. `net_gamma = call_gamma + put_gamma`; `pos` = net gamma ≥ 0 (dealers dampen → mean-reverting tape), `neg` = amplifying. Research says GEX is a HOLD/regime gate, not a direction call — so the test is whether the SAME divergence pays more in a positive-gamma tape (and, in §7b, holds longer). Caveat: GEX-regime signals have tested weak/confounded in this stack before — read conservatively.

### 7a. Edge by regime (divergence + points, confirmation, state edge)

| category | horizon | filter | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 |
|---|---|---|---|---|---|---|---|---|
| 1B | 5 | in-window | 119 | 0.580 | +0.0056 | -0.0028 | +0.0138 |  |
| 1B | 5 | pos-gamma | 59 | 0.542 | +0.0055 | -0.0053 | +0.0161 |  |
| 1B | 5 | neg-gamma | 60 | 0.617 | +0.0057 | -0.0074 | +0.0186 |  |
| 1B | 5 | pos+trend | 0 | nan | +nan | +nan | +nan |  |
| 1B | 10 | in-window | 117 | 0.624 | +0.0079 | -0.0053 | +0.0217 |  |
| 1B | 10 | pos-gamma | 57 | 0.596 | +0.0041 | -0.0173 | +0.0238 |  |
| 1B | 10 | neg-gamma | 60 | 0.650 | +0.0115 | -0.0069 | +0.0302 |  |
| 1B | 10 | pos+trend | 0 | nan | +nan | +nan | +nan |  |
| 1S | 5 | in-window | 490 | 0.447 | +0.0013 | -0.0020 | +0.0043 |  |
| 1S | 5 | pos-gamma | 445 | 0.445 | +0.0015 | -0.0022 | +0.0049 |  |
| 1S | 5 | neg-gamma | 45 | 0.467 | -0.0007 | -0.0083 | +0.0069 |  |
| 1S | 5 | pos+trend | 2 | 0.000 | -0.0382 | -0.0684 | -0.0079 | yes |
| 1S | 10 | in-window | 488 | 0.424 | -0.0014 | -0.0060 | +0.0034 |  |
| 1S | 10 | pos-gamma | 443 | 0.424 | -0.0007 | -0.0053 | +0.0041 |  |
| 1S | 10 | neg-gamma | 45 | 0.422 | -0.0080 | -0.0214 | +0.0046 |  |
| 1S | 10 | pos+trend | 2 | 0.000 | -0.0437 | -0.0442 | -0.0431 | yes |
| 2B | 5 | in-window | 33 | 0.424 | -0.0019 | -0.0220 | +0.0212 |  |
| 2B | 5 | pos-gamma | 24 | 0.417 | -0.0049 | -0.0306 | +0.0272 |  |
| 2B | 5 | neg-gamma | 9 | 0.444 | +0.0059 | -0.0152 | +0.0307 |  |
| 2B | 5 | pos+trend | 1 | 1.000 | +0.0073 | +nan | +nan |  |
| 2B | 10 | in-window | 33 | 0.485 | -0.0180 | -0.0379 | +0.0002 |  |
| 2B | 10 | pos-gamma | 24 | 0.417 | -0.0205 | -0.0426 | +0.0017 |  |
| 2B | 10 | neg-gamma | 9 | 0.667 | -0.0113 | -0.0610 | +0.0251 |  |
| 2B | 10 | pos+trend | 1 | 0.000 | -0.0209 | +nan | +nan |  |
| 2S | 5 | in-window | 84 | 0.405 | +0.0002 | -0.0066 | +0.0070 |  |
| 2S | 5 | pos-gamma | 60 | 0.433 | +0.0014 | -0.0074 | +0.0100 |  |
| 2S | 5 | neg-gamma | 24 | 0.333 | -0.0030 | -0.0154 | +0.0084 |  |
| 2S | 5 | pos+trend | 3 | 0.667 | +0.0178 | -0.0092 | +0.0360 |  |
| 2S | 10 | in-window | 84 | 0.405 | +0.0027 | -0.0076 | +0.0131 |  |
| 2S | 10 | pos-gamma | 60 | 0.433 | +0.0049 | -0.0072 | +0.0170 |  |
| 2S | 10 | neg-gamma | 24 | 0.333 | -0.0028 | -0.0238 | +0.0176 |  |
| 2S | 10 | pos+trend | 3 | 0.667 | +0.0135 | -0.0093 | +0.0324 |  |
| 3B | 5 | in-window | 1315 | 0.553 | -0.0005 | -0.0030 | +0.0020 |  |
| 3B | 5 | pos-gamma | 1210 | 0.555 | -0.0004 | -0.0031 | +0.0022 |  |
| 3B | 5 | neg-gamma | 105 | 0.533 | -0.0011 | -0.0081 | +0.0053 |  |
| 3B | 5 | pos+trend | 1173 | 0.553 | -0.0005 | -0.0032 | +0.0021 |  |
| 3B | 10 | in-window | 1301 | 0.573 | -0.0009 | -0.0043 | +0.0025 |  |
| 3B | 10 | pos-gamma | 1197 | 0.571 | -0.0009 | -0.0044 | +0.0025 |  |
| 3B | 10 | neg-gamma | 104 | 0.587 | -0.0006 | -0.0102 | +0.0088 |  |
| 3B | 10 | pos+trend | 1162 | 0.572 | -0.0017 | -0.0055 | +0.0020 |  |
| 3S | 5 | in-window | 567 | 0.492 | +0.0053 | +0.0011 | +0.0101 | yes |
| 3S | 5 | pos-gamma | 249 | 0.446 | -0.0010 | -0.0069 | +0.0047 |  |
| 3S | 5 | neg-gamma | 318 | 0.528 | +0.0103 | +0.0039 | +0.0173 | yes |
| 3S | 5 | pos+trend | 172 | 0.459 | +0.0002 | -0.0066 | +0.0076 |  |
| 3S | 10 | in-window | 560 | 0.464 | +0.0006 | -0.0041 | +0.0055 |  |
| 3S | 10 | pos-gamma | 245 | 0.461 | +0.0013 | -0.0058 | +0.0086 |  |
| 3S | 10 | neg-gamma | 315 | 0.467 | +0.0000 | -0.0076 | +0.0074 |  |
| 3S | 10 | pos+trend | 168 | 0.476 | +0.0027 | -0.0056 | +0.0111 |  |
| divergence | 5 | in-window | 2664 | 0.491 | +0.0027 | +0.0007 | +0.0046 | yes |
| divergence | 5 | pos-gamma | 2008 | 0.485 | +0.0020 | -0.0000 | +0.0040 |  |
| divergence | 5 | neg-gamma | 656 | 0.512 | +0.0048 | +0.0012 | +0.0085 | yes |
| divergence | 5 | pos+trend | 542 | 0.542 | +0.0018 | -0.0026 | +0.0062 |  |
| divergence | 10 | in-window | 2637 | 0.513 | +0.0042 | +0.0017 | +0.0065 | yes |
| divergence | 10 | pos-gamma | 1984 | 0.501 | +0.0027 | +0.0000 | +0.0053 | yes |
| divergence | 10 | neg-gamma | 653 | 0.550 | +0.0086 | +0.0035 | +0.0142 | yes |
| divergence | 10 | pos+trend | 537 | 0.579 | +0.0073 | +0.0014 | +0.0131 | yes |

### 7b. Survival + markout by regime (divergence, does the bounce hold longer?)

| regime | horizon | n | survival | mean_markout |
|---|---|---|---|---|
| pos | 5 | 2008 | 0.691 | +0.0008 |
| pos | 10 | 1984 | 0.571 | +0.0003 |
| pos | 20 | 1957 | 0.462 | +0.0010 |
| neg | 5 | 656 | 0.716 | +0.0051 |
| neg | 10 | 653 | 0.625 | +0.0092 |
| neg | 20 | 645 | 0.522 | +0.0120 |
