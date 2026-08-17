# The demand side is already in the store — buyer capex vs NVDA revenue

*2026-08-13 · exploratory · reproduce with the SQL below against `option_wizard_local`*

## Why this exists

P4 (concentration ledger) asked *"how much of this company's revenue comes from
one place?"* and failed twice: named-customer edges do not exist in filings
(§3.4, `"NVIDIA accounted for"` → 0 EDGAR hits), and the segment/geography
substitute is computable for 77 of 257 names on segment and **0 of 257** on
geography (`2026-08-13-fundamental-segment-computability-wide/`).

This probe asks the same question **from the buyer's side instead of the
seller's**, and that side has none of the blockers: capex is a top-level line in
the buyer's own cash-flow statement. No counterparty needs to be named, no
XBRL parent/child hierarchy has to be recovered, no denominator is missing.

## Method

Seven disclosed AI-infrastructure buyers held in `fundamental_statement_obs`:
**MSFT, AMZN, GOOGL, META, ORCL** (hyperscalers) and **NBIS, APLD** (neoclouds).
Their quarterly `capital_expenditures` is summed and set against NVDA's quarterly
`total_revenue`.

Fiscal calendars differ (NVDA's quarters end Apr 30 / Jul 31 / Oct 31 / Jan 31;
MSFT's fiscal year ends in June), so each period is bucketed by the calendar
quarter it mostly covers: `date_trunc('quarter', period_end - interval '1 month')`.
A period-end of Apr 30 covers Feb–Apr and buckets to Q1; Jun 30 covers Apr–Jun
and buckets to Q2. Where a bucket holds more than one filing for a ticker, the
latest `period_end` wins.

## Result

All seven buyers present in every quarter shown (`buyers` column = 7).

| quarter | buyer capex ($bn) | NVDA revenue ($bn) | NVDA rev as % of buyer capex |
|---|---:|---:|---:|
| 2026 Q1 | 151.6 | 81.6 | 53.8 |
| 2025 Q4 | 133.3 | 68.1 | 51.1 |
| 2025 Q3 | 107.0 | 57.0 | 53.3 |
| 2025 Q2 |  98.0 | 46.7 | 47.7 |
| 2025 Q1 |  78.4 | 44.1 | 56.2 |
| 2024 Q4 |  76.9 | 39.3 | 51.1 |
| 2024 Q3 |  61.4 | 35.1 | 57.1 |
| 2024 Q2 |  55.7 | 30.0 | 53.9 |
| 2024 Q1 |  46.6 | 26.0 | 55.9 |
| 2023 Q4 |  44.6 | 22.1 | 49.6 |
| 2023 Q3 |  38.6 | 18.1 | 46.9 |
| 2023 Q2 |  35.7 | 13.5 | 37.8 |
| 2023 Q1 |  36.7 |  7.2 | 19.6 |

**The ratio re-based once and has been flat since.** It runs 19.6% → 37.8% →
46.9% across the first three quarters of 2023, then sits in a **46.9–57.1% band
for eleven consecutive quarters** while both legs grow ~4x. Buyer capex more than
quadruples (36.7 → 151.6) and NVDA revenue grows 11x (7.2 → 81.6), yet the ratio
does not trend.

## What this is NOT

**It is not a measured edge, and must never be rendered as one.** Every caveat
below is load-bearing:

1. **Capex is not GPU spend.** These buyers' capex includes land, shells, power,
   networking, storage and non-AI servers. A stable ~50% ratio does **not** mean
   half their capex goes to NVDA.
2. **NVDA sells far beyond these seven.** The denominator is a chosen subset, not
   NVDA's customer base. Both legs are partial in different directions.
3. **Co-movement is partly mechanical.** Both series are inside the same
   AI-capex expansion, so correlation is expected and carries less information
   than it appears to.
4. **CoreWeave (CRWV) is absent from the store** — the purest GPU buyer of the
   set, and its omission biases the buyer leg downward.
5. **Quarter alignment is approximate**, per the bucketing rule above.

Under spec §6's trust tiers this is `asc280_inferred` at best, and it would
require a stated `identity_inference` basis. It is a **co-movement ledger**, not
a customer-concentration measurement.

## Why it is still the better question

The stable band is the finding, and a **break** in it is the tradable event: if
buyer capex growth rolls over while NVDA revenue keeps climbing, or the ratio
leaves the band in either direction, that divergence is precisely the thing that
would prove the AI-infrastructure thesis wrong. Segment concentration, even if
the XBRL hierarchy were built, would only tell you NVDA's data-center share is
~92% — a fact that has been true and unchanging throughout.

## Reproduce

```sql
-- psql -h 127.0.0.1 -U chenxi -d option_wizard_local -f this
with q as (
  select date_trunc('quarter', period_end - interval '1 month')::date as cq,
         ticker, statement, raw_jsonb,
         row_number() over (partition by ticker, statement,
           date_trunc('quarter', period_end - interval '1 month')
           order by period_end desc) rn
  from uw_scan.fundamental_statement_obs where period_type='quarterly'
),
capex as (
  select cq, sum(abs((raw_jsonb->>'capital_expenditures')::numeric)) v, count(*) n
  from q where statement='cash_flow' and rn=1
    and ticker in ('MSFT','AMZN','GOOGL','META','ORCL','NBIS','APLD')
    and raw_jsonb->>'capital_expenditures' is not null
  group by 1
),
nv as (
  select cq, (raw_jsonb->>'total_revenue')::numeric v
  from q where ticker='NVDA' and statement='income' and rn=1
)
select c.cq, c.n as buyers, round(c.v/1e9,1) buyer_capex_bn,
       round(n.v/1e9,1) nvda_rev_bn,
       round(100*n.v/nullif(c.v,0),1) as nvda_rev_pct_of_capex
from capex c join nv n using(cq) where c.cq >= '2023-01-01' order by c.cq desc;
```
