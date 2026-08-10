# `/vX` field contract — inventory, overlap, hash rule

*Probed 2026-08-11 · REGENERATED on every run; narrative belongs in `fx-and-corporate-actions.md` · spec `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`*

```bash
MASSIVE_API_KEY=... uv run python scripts/research/fundamental_field_contract.py
```

## 1. Field inventory

Every `financials.<group>.<field>` massive `/vX` emitted across the 23 covered tickers (most recent 4 quarters each).

| Field | Present | Coverage | Unit | Missing for |
|---|---:|---:|---|---|
| `balance_sheet.accounts_payable` | 21/23 | 0.913 | USD | GEV, MU |
| `balance_sheet.accounts_receivable` | 3/23 | 0.13 | USD | AMAT, AMD, AMZN, ANET, APP, AVGO (+14) |
| `balance_sheet.assets` | 23/23 | 1.0 | USD | — |
| `balance_sheet.cash` | 2/23 | 0.087 | USD | AMAT, AMD, AMZN, ANET, APP, AVGO (+15) |
| `balance_sheet.commitments_and_contingencies` | 1/23 | 0.043 | USD | AMAT, AMD, AMZN, ANET, APP, AVGO (+16) |
| `balance_sheet.current_assets` | 23/23 | 1.0 | USD | — |
| `balance_sheet.current_liabilities` | 23/23 | 1.0 | USD | — |
| `balance_sheet.equity` | 23/23 | 1.0 | USD | — |
| `balance_sheet.equity_attributable_to_noncontrolling_interest` | 23/23 | 1.0 | USD | — |
| `balance_sheet.equity_attributable_to_parent` | 23/23 | 1.0 | USD | — |
| `balance_sheet.fixed_assets` | 18/23 | 0.783 | USD | APP, GEV, GOOGL, META, MU |
| `balance_sheet.intangible_assets` | 15/23 | 0.652 | USD | ANET, APP, CEG, CRWD, MSFT, ORCL (+2) |
| `balance_sheet.inventory` | 18/23 | 0.783 | USD | APP, CRWD, META, NOW, PLTR |
| `balance_sheet.liabilities` | 23/23 | 1.0 | USD | — |
| `balance_sheet.liabilities_and_equity` | 23/23 | 1.0 | USD | — |
| `balance_sheet.long_term_debt` | 15/23 | 0.652 | USD | AMAT, AMD, ANET, CRWD, GEV, ORCL (+2) |
| `balance_sheet.noncurrent_assets` | 23/23 | 1.0 | USD | — |
| `balance_sheet.noncurrent_liabilities` | 23/23 | 1.0 | USD | — |
| `balance_sheet.noncurrent_prepaid_expenses` | 1/23 | 0.043 | USD | AMAT, AMD, AMZN, ANET, APP, AVGO (+16) |
| `balance_sheet.other_current_assets` | 19/23 | 0.826 | USD | APP, META, NOW, PLTR |
| `balance_sheet.other_current_liabilities` | 23/23 | 1.0 | USD | — |
| `balance_sheet.other_noncurrent_assets` | 22/23 | 0.957 | USD | APP |
| `balance_sheet.other_noncurrent_liabilities` | 15/23 | 0.652 | USD | AMAT, AMD, ANET, CRWD, GEV, ORCL (+2) |
| `balance_sheet.prepaid_expenses` | 3/23 | 0.13 | USD | AMAT, AMD, AMZN, ANET, APP, CEG (+14) |
| `balance_sheet.wages` | 18/23 | 0.783 | USD | ANET, APP, CEG, DELL, VST |
| `cash_flow_statement.exchange_gains_losses` | 11/23 | 0.478 | USD | AMAT, AMD, AMZN, AVGO, CEG, DELL (+6) |
| `cash_flow_statement.net_cash_flow` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_continuing` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_discontinued` | 1/23 | 0.043 | USD | AMAT, AMZN, ANET, APP, AVGO, CEG (+16) |
| `cash_flow_statement.net_cash_flow_from_financing_activities` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_from_financing_activities_continuing` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_from_investing_activities` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_from_investing_activities_continuing` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_from_investing_activities_discontinued` | 1/23 | 0.043 | USD | AMAT, AMZN, ANET, APP, AVGO, CEG (+16) |
| `cash_flow_statement.net_cash_flow_from_operating_activities` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_from_operating_activities_continuing` | 23/23 | 1.0 | USD | — |
| `cash_flow_statement.net_cash_flow_from_operating_activities_discontinued` | 1/23 | 0.043 | USD | AMAT, AMZN, ANET, APP, AVGO, CEG (+16) |
| `comprehensive_income.comprehensive_income_loss` | 23/23 | 1.0 | USD | — |
| `comprehensive_income.comprehensive_income_loss_attributable_to_noncontrolling_interest` | 23/23 | 1.0 | USD | — |
| `comprehensive_income.comprehensive_income_loss_attributable_to_parent` | 23/23 | 1.0 | USD | — |
| `comprehensive_income.other_comprehensive_income_loss` | 23/23 | 1.0 | USD | — |
| `comprehensive_income.other_comprehensive_income_loss_attributable_to_parent` | 13/23 | 0.565 | USD | AMD, AMZN, AVGO, CEG, CRWD, GEV (+4) |
| `income_statement.basic_average_shares` | 23/23 | 1.0 | shares | — |
| `income_statement.basic_earnings_per_share` | 23/23 | 1.0 | USD / shares | — |
| `income_statement.benefits_costs_expenses` | 23/23 | 1.0 | USD | — |
| `income_statement.common_stock_dividends` | 5/23 | 0.217 | USD / shares | AMAT, AMD, AMZN, ANET, APP, CEG (+12) |
| `income_statement.cost_of_revenue` | 20/23 | 0.87 | USD | CEG, ORCL, VST |
| `income_statement.costs_and_expenses` | 23/23 | 1.0 | USD | — |
| `income_statement.depreciation_and_amortization` | 1/23 | 0.043 | USD | AMD, AMZN, ANET, APP, AVGO, CEG (+16) |
| `income_statement.diluted_average_shares` | 23/23 | 1.0 | shares | — |
| `income_statement.diluted_earnings_per_share` | 23/23 | 1.0 | USD / shares | — |
| `income_statement.gross_profit` | 20/23 | 0.87 | USD | CEG, ORCL, VST |
| `income_statement.income_loss_before_equity_method_investments` | 6/23 | 0.261 | USD | AMAT, ANET, APP, AVGO, CRWD, DELL (+11) |
| `income_statement.income_loss_from_continuing_operations_after_tax` | 23/23 | 1.0 | USD | — |
| `income_statement.income_loss_from_continuing_operations_before_tax` | 23/23 | 1.0 | USD | — |
| `income_statement.income_loss_from_discontinued_operations_net_of_tax` | 3/23 | 0.13 | USD | AMAT, AMZN, ANET, CEG, CRWD, DELL (+14) |
| `income_statement.income_loss_from_equity_method_investments` | 6/23 | 0.261 | USD | AMAT, ANET, APP, AVGO, CRWD, DELL (+11) |
| `income_statement.income_tax_expense_benefit` | 23/23 | 1.0 | USD | — |
| `income_statement.income_tax_expense_benefit_deferred` | 8/23 | 0.348 | USD | AMAT, AMD, APP, AVGO, CEG, DELL (+9) |
| `income_statement.interest_expense_operating` | 4/23 | 0.174 | USD | AMAT, AMZN, ANET, APP, CEG, CRWD (+13) |
| `income_statement.net_income_loss` | 23/23 | 1.0 | USD | — |
| `income_statement.net_income_loss_attributable_to_noncontrolling_interest` | 23/23 | 1.0 | USD | — |
| `income_statement.net_income_loss_attributable_to_parent` | 23/23 | 1.0 | USD | — |
| `income_statement.net_income_loss_available_to_common_stockholders_basic` | 23/23 | 1.0 | USD | — |
| `income_statement.nonoperating_income_loss` | 11/23 | 0.478 | USD | AMAT, AMD, AVGO, CRWD, ETN, GEV (+6) |
| `income_statement.operating_expenses` | 23/23 | 1.0 | USD | — |
| `income_statement.operating_income_loss` | 23/23 | 1.0 | USD | — |
| `income_statement.other_operating_expenses` | 19/23 | 0.826 | USD | AMZN, CEG, DELL, NVDA |
| `income_statement.participating_securities_distributed_and_undistributed_earnings_loss_basic` | 23/23 | 1.0 | USD | — |
| `income_statement.preferred_stock_dividends_and_other_adjustments` | 23/23 | 1.0 | USD | — |
| `income_statement.research_and_development` | 19/23 | 0.826 | USD | AMZN, CEG, VRT, VST |
| `income_statement.revenues` | 23/23 | 1.0 | USD | — |
| `income_statement.selling_general_and_administrative_expenses` | 11/23 | 0.478 | USD | AMZN, ANET, APP, CEG, CRWD, GOOGL (+6) |

## 2. Overlap reconciliation (`/vX` ∩ `/v2`)

Most recent common period per ticker; `within_tol` is rel-diff ≤ 0.005.

| Ticker | Period | Common periods | exact | within_tol | DISAGREE | missing one side |
|---|---|---:|---:|---:|---:|---:|
| NVDA | 2020-01-26 | 37 | 22 | 1 | **7** | 0 |
| AMD | 2020-03-28 | 39 | 26 | 0 | **2** | 2 |
| MSFT | 2020-03-31 | 41 | 26 | 0 | **2** | 2 |
| AMZN | 2020-03-31 | 43 | 21 | 0 | **6** | 3 |
| ETN | 2020-03-31 | 43 | 22 | 1 | **6** | 1 |

### Disagreements

| Ticker | Field | `/vX` | `/v2` | rel diff |
|---|---|---:|---:|---:|
| NVDA | `pretax_income` | 3,105,000,000 | 1,016,000,000 | 0.6728 |
| NVDA | `eps_basic` | 2 | 2 | 0.0064 |
| NVDA | `diluted_shares` | 1,000,000 | 621,000,000 | 0.9984 |
| NVDA | `basic_shares` | 0 | 609,000,000 | 1.0000 |
| NVDA | `long_term_debt` | 1,991,000,000 | 2,552,000,000 | 0.2198 |
| NVDA | `fixed_assets` | 1,674,000,000 | 2,292,000,000 | 0.2696 |
| NVDA | `intangible_assets` | 49,000,000 | 667,000,000 | 0.9265 |
| AMD | `accounts_payable` | 653,000,000 | 840,000,000 | 0.2226 |
| AMD | `fixed_assets` | 540,000,000 | 761,000,000 | 0.2904 |
| MSFT | `long_term_debt` | 66,610,000,000 | 70,110,000,000 | 0.0499 |
| MSFT | `fixed_assets` | 41,221,000,000 | 49,669,000,000 | 0.1701 |
| AMZN | `operating_expenses` | 71,463,000,000 | 27,206,000,000 | 0.6193 |
| AMZN | `pretax_income` | 3,383,000,000 | 3,279,000,000 | 0.0307 |
| AMZN | `total_liabilities` | -65,272,000,000 | 155,966,000,000 | 1.4185 |
| AMZN | `noncurrent_liabilities` | 0 | 76,255,000,000 | 1.0000 |
| AMZN | `long_term_debt` | 24,849,000,000 | 63,737,000,000 | 0.6101 |
| AMZN | `fixed_assets` | 77,779,000,000 | 104,058,000,000 | 0.2525 |
| ETN | `operating_income` | 621,000,000 | 469,000,000 | 0.2448 |
| ETN | `operating_expenses` | 866,000,000 | 1,018,000,000 | 0.1493 |
| ETN | `total_liabilities` | -14,288,000,000 | 16,557,000,000 | 1.8630 |
| ETN | `fixed_assets` | 2,939,000,000 | 3,373,000,000 | 0.1287 |
| ETN | `intangible_assets` | 4,319,000,000 | 16,716,000,000 | 0.7416 |
| ETN | `net_cash_flow` | -130,000,000 | -131,000,000 | 0.0076 |

## 3. `content_hash` exclusion list

Two identical `/vX` calls, diffed. These keys vary between calls and must be excluded from the hash, or every refresh reads as a restatement (spec §4.4).

```
[
  "request_id"
]
```

Result rows byte-identical across the two calls: **True**.

## 4. Fields the method needs that `/vX` does not emit

`/v2` has these but is frozen at 2020-Q1, so current values must come from UW, SEC XBRL, or derivation — never a silent `None`.

| Canonical | `/v2` key |
|---|---|
| `capital_expenditure` | `capitalExpenditure` |
| `free_cash_flow` | `freeCashFlow` |
| `total_debt` | `debt` |
| `current_debt` | `debtCurrent` |
| `cash_and_equivalents` | `cashAndEquivalents` |
| `depreciation_amortization` | `depreciationAmortizationAndAccretion` |
| `share_based_compensation` | `shareBasedCompensation` |
| `ebitda` | `earningsBeforeInterestTaxesDepreciationAmortization` |
| `deferred_revenue` | `deferredRevenue` |
| `interest_expense` | `interestExpense` |

## 5. ADR ratio / FX evidence (`/v2`)

`shareFactor` ≠ 1 marks an ADR whose per-share figures need restating. Values are as of the `/v2` freeze — a starting value to re-verify, not a live feed.

| Ticker | As of | shareFactor | FX rate | revenues (local) | revenuesUSD |
|---|---|---:|---:|---:|---:|
| TSM | 2019-12-31 | 0.2 | 30.2 | 1069985400000 | 35429980133 |
| ASML | 2019-12-31 | 1 | 0.89 | 11820000000 | 13280898876 |

## 6. Impossible values on CURRENT data

272 rows — every covered ticker's most recent 12 quarters. These are values that cannot be true of any company, in data a card would render today.

| Check | Hits | Rate |
|---|---:|---:|
| `negative_liabilities` | 14/272 | 5.1% |
| `negative_assets` | 0/272 | 0.0% |
| `implausible_share_count` | 41/272 | 15.1% |
| `identity_break` | 11/272 | 4.0% |

### `negative_liabilities` (14)

| Row | Value |
|---|---:|
| GOOGL@2026-03-31 | -478,746,000,000 |
| AMZN@2026-03-31 | -441,914,000,000 |
| AMZN@2025-06-30 | -333,775,000,000 |
| AMZN@2025-03-31 | -305,867,000,000 |
| AMZN@2024-06-30 | -236,447,000,000 |
| AMZN@2024-03-31 | -216,661,000,000 |
| META@2026-03-31 | -243,681,000,000 |
| VRT@2024-06-30 | -1,537,500,000 |
| ETN@2026-03-31 | -19,765,000,000 |
| ETN@2025-06-30 | -18,647,000,000 |
| ETN@2025-03-31 | -18,547,000,000 |
| ETN@2024-06-30 | -19,254,000,000 |
| ETN@2024-03-31 | -19,326,000,000 |
| ETN@2023-06-30 | -17,988,000,000 |

### `implausible_share_count` (41)

| Row | Value |
|---|---:|
| NVDA@2026-01-25 | -28,000,000 |
| NVDA@2024-01-28 | 0 |
| AMD@2024-12-28 | -1,000,000 |
| AMD@2023-12-30 | 0 |
| AVGO@2023-10-29 | 0 |
| MRVL@2026-01-31 | -200,000 |
| MRVL@2023-01-28 | 900,000 |
| AMAT@2025-10-26 | -3,000,000 |
| AMAT@2024-10-27 | -1,000,000 |
| AMAT@2023-10-29 | -1,000,000 |
| MSFT@2026-06-30 | -4,000,000 |
| MSFT@2025-06-30 | -1,000,000 |
| MSFT@2023-06-30 | -2,000,000 |
| GOOGL@2026-03-31 | -35,000,000 |
| GOOGL@2025-12-31 | 0 |
| GOOGL@2024-12-31 | -33,000,000 |
| AMZN@2026-03-31 | -14,000,000 |
| META@2026-03-31 | -1,000,000 |
| META@2025-12-31 | -4,000,000 |
| META@2024-12-31 | -1,000,000 |
| ORCL@2026-05-31 | 0 |
| ANET@2025-12-31 | 0 |
| ANET@2023-12-31 | 571,000 |
| VRT@2025-12-31 | 394,922 |
| VRT@2024-12-31 | 218,829 |
| ETN@2025-12-31 | -500,000 |
| ETN@2023-12-31 | 200,000 |
| GEV@2025-12-31 | -1,000,000 |
| CEG@2025-12-31 | 0 |
| CEG@2024-12-31 | -1,000,000 |
| CEG@2023-12-31 | -1,000,000 |
| VST@2025-12-31 | -647,550 |
| VST@2024-12-31 | -1,238,877 |
| VST@2023-12-31 | -3,909,248 |
| DELL@2024-02-02 | -2,000,000 |
| SMCI@2023-06-30 | 174,000 |
| CRWD@2026-01-31 | 671,000 |
| NOW@2024-12-31 | 419,000 |
| NOW@2023-12-31 | 397,000 |
| APP@2025-12-31 | -698,000 |
| APP@2023-12-31 | -5,670,267 |

### `identity_break` (11)

| Row | Value |
|---|---:|
| AMZN@2025-06-30 | -682,170,000,000 |
| AMZN@2025-03-31 | -643,256,000,000 |
| AMZN@2024-06-30 | -554,818,000,000 |
| AMZN@2024-03-31 | -530,969,000,000 |
| ETN@2026-03-31 | -55,085,000,000 |
| ETN@2025-06-30 | -40,507,000,000 |
| ETN@2025-03-31 | -39,206,000,000 |
| ETN@2024-06-30 | -39,381,000,000 |
| ETN@2024-03-31 | -38,535,000,000 |
| ETN@2023-06-30 | -36,772,000,000 |
| VST@2024-09-30 | -3,198,000,000 |
