# Sector RS breadth probe — VERDICT

**Verdict: FAIL** (primary variant `breadth_1m`, gate of spec 2026-09-26 §6).

- Source: `uw_scan.sector_rs_daily` gics rows on host.docker.internal/option_wizard (76813 rows read).
- Reproduce: `uv run python scripts/research/sector_rs_breadth_probe.py --run-date 2026-10-02 --boot 5000`
- Grid: every 21th session per group; tercile expanding over past daily breadth (min 63); bootstrap B=5000, seed 20260926; holdout 2019-01-01.
- The pooled bootstrap resamples pairs across groups and ignores group clustering.
- Breadth uses TODAY's S&P 500 membership over every session, and delisted names have no adjusted bars, so former members are absent: survivorship-biased by construction.

## Effective sample start per group

First non-degraded row from which every 252-session window is >= 95% non-degraded; earlier rows are excluded.

| group | first row | effective start | rows excluded | note |
|---|---|---|---|---|
| Basic Materials | 1998-12-22 | 2019-11-01 | 5247 | OOS-only (no in-sample) |
| Communication Services | 1998-12-22 | 2021-12-09 | 5777 | OOS-only (no in-sample) |
| Consumer Cyclical | 1998-12-22 | 2012-11-20 | 3498 |  |
| Consumer Defensive | 1998-12-22 | 2016-06-15 | 4395 |  |
| Energy | 1998-12-22 | 2013-04-16 | 3597 |  |
| Financial Services | 1998-12-22 | 2011-07-14 | 3157 |  |
| Healthcare | 1998-12-22 | 2013-12-10 | 3763 |  |
| Industrials | 1998-12-22 | 2019-09-11 | 5210 | OOS-only (no in-sample) |
| Real Estate | 1998-12-22 | 2016-10-07 | 4475 |  |
| Technology | 1998-12-22 | 2017-09-21 | 4715 |  |
| Utilities | 1998-12-22 | 2019-01-03 | 5037 | OOS-only (no in-sample) |

## `breadth_1m` — gate FAIL

- pooled OOS diff -0.003, CI [-0.179, +0.166] does not exclude zero on the positive side
- Communication Services: OOS diff -0.463 below −half-width 0.130
- Real Estate: OOS diff -0.587 below −half-width 0.098

| split | group | n | n_C | p_C | p_base | diff | CI 95% |
|---|---|---|---|---|---|---|---|
| all | Basic Materials | 79 | 0 | — | +0.468 | — | [—, —] |
| all | Communication Services | 54 | 2 | +0.000 | +0.463 | -0.463 | [-0.593, -0.333] |
| all | Consumer Cyclical | 162 | 26 | +0.654 | +0.488 | +0.166 | [-0.008, +0.337] |
| all | Consumer Defensive | 120 | 0 | — | +0.633 | — | [—, —] |
| all | Energy | 158 | 0 | — | +0.544 | — | [—, —] |
| all | Financial Services | 179 | 2 | +0.500 | +0.475 | +0.025 | [-0.520, +0.564] |
| all | Healthcare | 150 | 3 | +0.333 | +0.520 | -0.187 | [-0.580, +0.493] |
| all | Industrials | 81 | 1 | +1.000 | +0.543 | +0.457 | [+0.346, +0.556] |
| all | Real Estate | 116 | 1 | +0.000 | +0.586 | -0.586 | [-0.672, -0.500] |
| all | Technology | 104 | 11 | +0.545 | +0.423 | +0.122 | [-0.170, +0.413] |
| all | Utilities | 89 | 0 | — | +0.584 | — | [—, —] |
| all | POOLED | 1292 | 46 | +0.565 | +0.522 | +0.044 | [-0.100, +0.188] |
| in_sample | Basic Materials | 0 | 0 | — | — | — | [—, —] |
| in_sample | Communication Services | 0 | 0 | — | — | — | [—, —] |
| in_sample | Consumer Cyclical | 71 | 11 | +0.636 | +0.437 | +0.200 | [-0.089, +0.472] |
| in_sample | Consumer Defensive | 28 | 0 | — | +0.536 | — | [—, —] |
| in_sample | Energy | 66 | 0 | — | +0.576 | — | [—, —] |
| in_sample | Financial Services | 87 | 0 | — | +0.448 | — | [—, —] |
| in_sample | Healthcare | 58 | 0 | — | +0.483 | — | [—, —] |
| in_sample | Industrials | 0 | 0 | — | — | — | [—, —] |
| in_sample | Real Estate | 24 | 0 | — | +0.583 | — | [—, —] |
| in_sample | Technology | 13 | 3 | +0.667 | +0.308 | +0.359 | [-0.231, +0.846] |
| in_sample | Utilities | 0 | 0 | — | — | — | [—, —] |
| in_sample | POOLED | 347 | 14 | +0.643 | +0.487 | +0.156 | [-0.113, +0.404] |
| oos | Basic Materials | 79 | 0 | — | +0.468 | — | [—, —] |
| oos | Communication Services | 54 | 2 | +0.000 | +0.463 | -0.463 | [-0.593, -0.333] |
| oos | Consumer Cyclical | 91 | 15 | +0.667 | +0.527 | +0.139 | [-0.095, +0.363] |
| oos | Consumer Defensive | 92 | 0 | — | +0.663 | — | [—, —] |
| oos | Energy | 92 | 0 | — | +0.522 | — | [—, —] |
| oos | Financial Services | 92 | 2 | +0.500 | +0.500 | +0.000 | [-0.565, +0.565] |
| oos | Healthcare | 92 | 3 | +0.333 | +0.543 | -0.210 | [-0.609, +0.478] |
| oos | Industrials | 81 | 1 | +1.000 | +0.543 | +0.457 | [+0.346, +0.556] |
| oos | Real Estate | 92 | 1 | +0.000 | +0.587 | -0.587 | [-0.685, -0.489] |
| oos | Technology | 91 | 8 | +0.500 | +0.440 | +0.060 | [-0.294, +0.416] |
| oos | Utilities | 89 | 0 | — | +0.584 | — | [—, —] |
| oos | POOLED | 945 | 32 | +0.531 | +0.534 | -0.003 | [-0.179, +0.166] |

## `breadth_3m` — gate FAIL (pre-registered secondary; does not change the verdict)

- pooled OOS diff +0.040, CI [-0.045, +0.124] does not exclude zero on the positive side

| split | group | n | n_C | p_C | p_base | diff | CI 95% |
|---|---|---|---|---|---|---|---|
| all | Basic Materials | 79 | 10 | +0.500 | +0.468 | +0.032 | [-0.288, +0.335] |
| all | Communication Services | 54 | 5 | +0.800 | +0.463 | +0.337 | [-0.111, +0.630] |
| all | Consumer Cyclical | 162 | 35 | +0.514 | +0.488 | +0.027 | [-0.120, +0.174] |
| all | Consumer Defensive | 120 | 5 | +0.800 | +0.633 | +0.167 | [-0.283, +0.425] |
| all | Energy | 158 | 12 | +0.500 | +0.544 | -0.044 | [-0.326, +0.236] |
| all | Financial Services | 179 | 19 | +0.737 | +0.475 | +0.262 | [+0.064, +0.448] |
| all | Healthcare | 150 | 24 | +0.417 | +0.520 | -0.103 | [-0.284, +0.082] |
| all | Industrials | 81 | 7 | +0.571 | +0.543 | +0.028 | [-0.381, +0.432] |
| all | Real Estate | 116 | 7 | +0.571 | +0.586 | -0.015 | [-0.412, +0.397] |
| all | Technology | 104 | 23 | +0.435 | +0.423 | +0.012 | [-0.170, +0.194] |
| all | Utilities | 89 | 8 | +0.750 | +0.584 | +0.166 | [-0.173, +0.449] |
| all | POOLED | 1292 | 155 | +0.548 | +0.522 | +0.027 | [-0.043, +0.101] |
| in_sample | Basic Materials | 0 | 0 | — | — | — | [—, —] |
| in_sample | Communication Services | 0 | 0 | — | — | — | [—, —] |
| in_sample | Consumer Cyclical | 71 | 14 | +0.357 | +0.437 | -0.079 | [-0.308, +0.164] |
| in_sample | Consumer Defensive | 28 | 0 | — | +0.536 | — | [—, —] |
| in_sample | Energy | 66 | 2 | +1.000 | +0.576 | +0.424 | [+0.303, +0.545] |
| in_sample | Financial Services | 87 | 10 | +0.800 | +0.448 | +0.352 | [+0.086, +0.586] |
| in_sample | Healthcare | 58 | 8 | +0.250 | +0.483 | -0.233 | [-0.517, +0.106] |
| in_sample | Industrials | 0 | 0 | — | — | — | [—, —] |
| in_sample | Real Estate | 24 | 0 | — | +0.583 | — | [—, —] |
| in_sample | Technology | 13 | 6 | +0.333 | +0.308 | +0.026 | [-0.308, +0.359] |
| in_sample | Utilities | 0 | 0 | — | — | — | [—, —] |
| in_sample | POOLED | 347 | 40 | +0.475 | +0.487 | -0.012 | [-0.156, +0.136] |
| oos | Basic Materials | 79 | 10 | +0.500 | +0.468 | +0.032 | [-0.288, +0.335] |
| oos | Communication Services | 54 | 5 | +0.800 | +0.463 | +0.337 | [-0.111, +0.630] |
| oos | Consumer Cyclical | 91 | 21 | +0.619 | +0.527 | +0.092 | [-0.095, +0.288] |
| oos | Consumer Defensive | 92 | 5 | +0.800 | +0.663 | +0.137 | [-0.330, +0.402] |
| oos | Energy | 92 | 10 | +0.400 | +0.522 | -0.122 | [-0.420, +0.191] |
| oos | Financial Services | 92 | 9 | +0.667 | +0.500 | +0.167 | [-0.158, +0.489] |
| oos | Healthcare | 92 | 16 | +0.500 | +0.543 | -0.043 | [-0.273, +0.188] |
| oos | Industrials | 81 | 7 | +0.571 | +0.543 | +0.028 | [-0.381, +0.432] |
| oos | Real Estate | 92 | 7 | +0.571 | +0.587 | -0.016 | [-0.430, +0.380] |
| oos | Technology | 91 | 17 | +0.471 | +0.440 | +0.031 | [-0.187, +0.254] |
| oos | Utilities | 89 | 8 | +0.750 | +0.584 | +0.166 | [-0.173, +0.449] |
| oos | POOLED | 945 | 115 | +0.574 | +0.534 | +0.040 | [-0.045, +0.124] |

