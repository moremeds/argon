# UW fundamentals — coverage, integrity, and head-to-head vs massive `/vX`

*Probed 2026-08-11 · REGENERATED on every run · spec `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`*

```bash
UW_SCAN_API_KEY=... MASSIVE_API_KEY=... uv run python scripts/research/uw_fundamentals_probe.py
```

Routes (PLURAL — the singular forms 404, which reads as 'no coverage'):

- `/api/stock/{ticker}/income-statements`
- `/api/stock/{ticker}/balance-sheets`
- `/api/stock/{ticker}/cash-flows`

## 1. Coverage

| Ticker | Quarterly rows | Span | Currency | BS rows | CF rows |
|---|---:|---|---|---:|---:|
| NVDA | 82 | 2006-01-31 → 2026-04-30 | USD | 82 | 82 |
| AMD | 83 | 2005-12-31 → 2026-06-30 | USD | 83 | 83 |
| AVGO | 78 | 2007-01-31 → 2026-04-30 | USD | 73 | 75 |
| MRVL | 82 | 2006-01-31 → 2026-04-30 | USD | 82 | 82 |
| TSM | 83 | 2005-12-31 → 2026-06-30 | TWD | 83 | 83 |
| ASML | 83 | 2005-12-31 → 2026-06-30 | EUR | 83 | 83 |
| AMAT | 82 | 2006-01-31 → 2026-04-30 | USD | 82 | 82 |
| MU | 83 | 2005-11-30 → 2026-05-31 | USD | 83 | 83 |
| MSFT | 83 | 2005-12-31 → 2026-06-30 | USD | 83 | 83 |
| GOOGL | 83 | 2005-12-31 → 2026-06-30 | USD | 83 | 83 |
| AMZN | 83 | 2005-12-31 → 2026-06-30 | None,USD | 83 | 83 |
| META | 66 | 2010-03-31 → 2026-06-30 | USD | 63 | 66 |
| ORCL | 83 | 2005-11-30 → 2026-05-31 | USD | 83 | 83 |
| ANET | 55 | 2012-12-31 → 2026-06-30 | USD | 55 | 55 |
| VRT | 35 | 2017-12-31 → 2026-06-30 | USD | 38 | 36 |
| ETN | 83 | 2005-12-31 → 2026-06-30 | USD | 83 | 83 |
| GEV | 14 | 2023-03-31 → 2026-06-30 | USD | 14 | 14 |
| CEG | 55 | 2012-09-30 → 2026-03-31 | USD | 55 | 55 |
| VST | 83 | 2005-09-30 → 2026-06-30 | None,USD | 83 | 83 |
| DELL | 53 | 2012-10-31 → 2026-04-30 | USD | 53 | 53 |
| SMCI | 82 | 2005-12-31 → 2026-03-31 | USD | 82 | 82 |
| PLTR | 30 | 2019-03-31 → 2026-06-30 | USD | 30 | 30 |
| CRWD | 34 | 2018-01-31 → 2026-04-30 | USD | 34 | 34 |
| NOW | 64 | 2010-09-30 → 2026-06-30 | USD | 64 | 62 |
| APP | 31 | 2018-12-31 → 2026-06-30 | USD | 31 | 31 |

## 2. Critical fields massive `/vX` does not emit at all

| Statement | Field | Cohort coverage |
|---|---|---:|
| `income-statements` | `ebitda` | 1.0 |
| `income-statements` | `ebit` | 1.0 |
| `income-statements` | `depreciation_and_amortization` | 1.0 |
| `income-statements` | `interest_expense` | 1.0 |
| `balance-sheets` | `cash_and_cash_equivalents` | 1.0 |
| `balance-sheets` | `short_long_term_debt_total` | 1.0 |
| `balance-sheets` | `current_debt` | None |
| `balance-sheets` | `long_term_debt` | 1.0 |
| `balance-sheets` | `goodwill` | 0.96 |
| `balance-sheets` | `common_stock_shares_outstanding` | 1.0 |
| `cash-flows` | `capital_expenditures` | 1.0 |
| `cash-flows` | `stock_based_compensation` | 1.0 |
| `cash-flows` | `dividend_payout` | 0.96 |

## 3. Integrity — same checks massive was judged by

1668 quarterly balance-sheet rows.

`unexplained_balance_gap` is **not** a defect count. It tests `assets = liabilities + shareholder_equity`, which holds only for filers with no noncontrolling interest; UW exposes no NCI field, so consolidating filers break it by construction. The gap is one-directional (`L+E < A`) and concentrates in MU/CEG/ORCL/TSM/DELL/AMD. Read it as **the size of the missing-NCI problem**, not as bad data.

| Check | Hits | Rate |
|---|---:|---:|
| `negative_liabilities` | 4/1668 | 0.2% |
| `negative_assets` | 0/1668 | 0.0% |
| `implausible_share_count` | 0/1668 | 0.0% |
| `unexplained_balance_gap` | 237/1668 | 14.2% |

### `negative_liabilities` (4)

| Row | Value |
|---|---:|
| DELL@2015-04-30 | -2,904,000,000 |
| DELL@2014-04-30 | -4,014,000,000 |
| PLTR@2020-03-31 | -146,589,000 |
| PLTR@2019-03-31 | -508,295,000 |

### `unexplained_balance_gap` (237)

| Row | Value |
|---|---:|
| AMD@2009-12-31 | -1,076,000,000 |
| AMD@2009-09-30 | -1,077,000,000 |
| AMD@2009-06-30 | -1,085,000,000 |
| AMD@2009-03-31 | -1,089,000,000 |
| AMD@2008-12-31 | -169,000,000 |
| AMD@2008-09-30 | -175,000,000 |
| AMD@2008-06-30 | -189,000,000 |
| AMD@2008-03-31 | -189,000,000 |
| AMD@2007-12-31 | -265,000,000 |
| AMD@2007-09-30 | -308,000,000 |
| AMD@2007-06-30 | -292,000,000 |
| AMD@2007-03-31 | -303,000,000 |
| AMD@2006-12-31 | -290,000,000 |
| AMD@2006-09-30 | -272,116,000 |
| AMD@2006-06-30 | -267,095,000 |
| AMD@2006-03-31 | -244,672,000 |
| AMD@2005-12-31 | -234,988,000 |
| AVGO@2018-01-31 | -3,180,000,000 |
| AVGO@2017-10-31 | -2,907,000,000 |
| AVGO@2017-07-31 | -2,902,000,000 |
| AVGO@2017-04-30 | -2,918,000,000 |
| AVGO@2017-01-31 | -2,977,000,000 |
| AVGO@2016-10-31 | -2,984,000,000 |
| AVGO@2016-07-31 | -3,031,000,000 |
| AVGO@2016-04-30 | -3,060,000,000 |
| TSM@2025-12-31 | -41,082,957,000 |
| TSM@2025-09-30 | -37,270,830,000 |
| TSM@2025-06-30 | -35,557,875,000 |
| TSM@2025-03-31 | -37,461,877,000 |
| TSM@2024-12-31 | -35,031,000,000 |
| TSM@2024-03-31 | -29,984,324,000 |
| TSM@2011-06-30 | -4,412,944,000 |
| TSM@2011-03-31 | -4,718,076,000 |
| TSM@2010-12-31 | -4,559,500,000 |
| TSM@2010-09-30 | -4,380,445,000 |
| TSM@2010-06-30 | -4,188,353,000 |
| TSM@2010-03-31 | -4,166,986,000 |
| TSM@2009-12-31 | -3,965,800,000 |
| TSM@2009-09-30 | -3,741,373,000 |
| TSM@2009-06-30 | -3,592,000,000 |

## 4. UW vs massive `/vX`, most recent common quarter

| Ticker | Period | exact | within_tol | DISAGREE | missing one side |
|---|---|---:|---:|---:|---:|
| NVDA | 2023-04-30 | 16 | 0 | **0** | 0 |
| AMD | 2023-09-30 | 15 | 0 | **1** | 0 |
| AVGO | 2023-04-30 | 16 | 0 | **0** | 0 |
| MRVL | 2026-01-31 | 13 | 0 | **3** | 0 |
| TSM | — | — | — | — | no common period |
| ASML | — | — | — | — | no common period |
| AMAT | 2023-04-30 | 16 | 0 | **0** | 0 |
| MU | 2024-02-29 | 16 | 0 | **0** | 0 |
| MSFT | 2026-06-30 | 16 | 0 | **0** | 0 |
| GOOGL | 2026-06-30 | 13 | 0 | **0** | 3 |
| AMZN | 2026-06-30 | 15 | 0 | **0** | 1 |
| META | 2026-06-30 | 12 | 0 | **0** | 4 |
| ORCL | 2026-05-31 | 9 | 2 | **2** | 3 |
| ANET | 2026-06-30 | 15 | 0 | **1** | 0 |
| VRT | 2026-06-30 | 15 | 0 | **0** | 1 |
| ETN | 2026-06-30 | 13 | 2 | **1** | 0 |
| GEV | 2026-06-30 | 10 | 4 | **2** | 0 |
| CEG | 2026-03-31 | 11 | 0 | **2** | 3 |
| VST | 2026-03-31 | 9 | 1 | **2** | 4 |
| DELL | 2025-01-31 | 7 | 2 | **3** | 4 |
| SMCI | 2026-03-31 | 14 | 2 | **0** | 0 |
| PLTR | 2026-06-30 | 12 | 2 | **1** | 1 |
| CRWD | 2026-04-30 | 13 | 0 | **2** | 1 |
| NOW | 2026-06-30 | 15 | 0 | **0** | 1 |
| APP | 2026-06-30 | 15 | 0 | **0** | 1 |
