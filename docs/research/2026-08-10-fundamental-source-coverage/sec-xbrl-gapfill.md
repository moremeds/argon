# SEC XBRL gap-fill — noncontrolling interest and current debt

*Probed 2026-08-11 · REGENERATED on every run · free, keyless, authoritative*

```bash
uv run python scripts/research/sec_xbrl_gapfill_probe.py
```

Tickers are the six whose UW rows fail `assets = liabilities + equity`, plus two clean controls — without controls, an empty result and a broken probe look identical.

| Ticker | CIK | NCI concept | taxonomy | facts | quarterly? | span | current-debt concept | facts |
|---|---|---|---|---:|---|---|---|---:|
| MU | 0000723125 | `MinorityInterest` | `us-gaap` | 82 | yes | 2009-09-03 → 2020-09-03 | `DebtCurrent` | 104 |
| CEG | 0001868275 | `MinorityInterest` | `us-gaap` | 36 | yes | 2021-12-31 → 2026-06-30 | `LongTermDebtCurrent` | 12 |
| ORCL | 0001341439 | `MinorityInterest` | `us-gaap` | 134 | yes | 2009-05-31 → 2026-05-31 | `DebtCurrent` | 66 |
| TSM | 0001046179 | `NoncontrollingInterests` | `ifrs-full` | 8 | **annual only** | 2017-12-31 → 2024-12-31 | `CurrentPortionOfLongtermBorrowings` | 8 |
| DELL | 0001571996 | `MinorityInterest` | `us-gaap` | 78 | yes | 2016-01-29 → 2026-01-30 | `DebtCurrent` | 82 |
| AMD | 0000002488 | `MinorityInterest` | `us-gaap` | 6 | yes | 2008-12-27 → 2011-12-31 | `DebtCurrent` | 20 |
| **control** NVDA | 0001045810 | `—` | `—` | 0 | — | — | `DebtCurrent` | 40 |
| **control** MSFT | 0000789019 | `—` | `—` | 0 | — | — | `LongTermDebtCurrent` | 110 |
