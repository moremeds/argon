# Filing dates are missing because two UW endpoints disagree about when a quarter ends

**Date:** 2026-08-23
**Question that started it:** the user proposed replacing the monthly blind statement
ingest with a daily calendar-driven one — "if a company reports today, pull it today".
Validating that proposal required measuring whether a statement is retrievable on the
day a company reports. It is. The measurement also turned up two pre-existing bugs that
are quietly stripping the one field the validated fundamental signal depends on.

**Universe:** `fundamental_universe` tier `ranked`, 450 tickers, mini prod DB
(`option_wizard`). Calendar window 2026-04-25 → 2026-08-23 (120 days).

---

## Findings

### F1 — 129 tickers have NULL filing dates because the period keys never match

`fundamental_ingest._filing_dates()` builds `{period_end: filing_date}` from
`/api/stock/{t}/fundamental-breakdown` and looks it up with the period_end that the
`income-statements` / `balance-sheets` / `cash-flows` endpoints report. **The two
endpoints use different period conventions:**

| ticker | statements say | breakdown says |
|---|---|---|
| AAPL | 2026-06-30 | **2026-06-27** |
| AAPL | 2026-03-31 | **2026-03-28** |
| AAPL | 2025-12-27 → we store | **2025-12-27** |
| NVDA | 2026-04-30 | 2026-04-26 |
| AMD  | 2026-06-30 | 2026-06-27 |

Statements normalise to a calendar month-end; breakdown reports the true fiscal period
end. For every 52/53-week filer the exact dict lookup misses on **every period, forever**.

Breakdown is not missing the dates — it dates **100%** of what it carries (AAPL 69/69,
WMT 68/68, AEP 68/68). We were asking with the wrong key.

**Recovery by match tolerance**, over the 885 NULL periods (`period_end >= 2024-01-01`)
across all 129 affected tickers:

| tolerance (days) | periods recovered | statement rows | ambiguous |
|---|---|---|---|
| 0 (today) | **0** | 0 | — |
| 3 | 452 | 1,360 | — |
| 5 | 569 | 1,716 | — |
| **7** | **592 (67%)** | **1,785** | **0** |
| 10 | 594 | 1,791 | — |
| 14 | 601 | 1,812 | — |

**Pick 7.** It takes 98.5% of everything reachable at any tolerance, the curve is flat
past it, and **zero** of the 885 periods matched two breakdown rows — quarters sit ~91
days apart, so a ±7 window cannot reach a neighbour. Fully recovered names include AAPL,
AMAT, CSCO, INTC, HD, DE, WDC, LITE, ICHR, FN.

Reproduce: `cat tolerance_probe.py | docker exec -i argon-worker-uw-0-1 python -`

### F2 — when a filing date does arrive late, the upsert throws it away

`FundamentalObsRepository.record_statements` ends:

```sql
ON CONFLICT (source, ticker, period_end, period_type, statement, content_hash)
DO UPDATE SET last_seen_at = now()
```

`filing_published_at` is not in the SET. `content_hash` covers the statement payload and
not the filing date, so a re-pull that carries a newly-published date collides on an
identical hash and updates only the timestamp. **The date is discarded and can never be
filled in.**

This is not hypothetical: breakdown's frontier trails the statement endpoints for 7 of a
random 40 names (INFY by 91 days, GFS by 181, WMT by one quarter). Those dates arrive
weeks-to-months after we first store the row, i.e. exactly into the discard path.

The 293 periods F1's tolerance does not recover are this population.

Reproduce: `frontier_probe.py`

### F3 — a statement is retrievable the day the company reports

704 report events over 412 of the 450 universe names. "Landed" = our panel holds a
period within 75 days of the report date (median observed gap is 31, p99 is 51).

| days since report | n | landed |
|---|---|---|
| 2–3 | 6 | 100% |
| 4–7 | 4 | 100% |
| 8–14 | 25 | 88% |
| 15–30 | 266 | 99.6% |
| 31–60 | 61 | 98.4% |
| 61–120 | 342 | 98.5% |

All 10 non-landed events are ≥10 days old and still non-landed, in three permanent
flavours: no statement history at all (KEEL, FRMI, SPCX), a panel that stopped advancing
(NNE, newest 2025-12-31 across two reports), and 12-week fiscal filers whose matched
period is a quarter back (AZO, COST, FEIM). **None is a timing effect.**

**Consequence: the daily design needs no retry window for data availability.** A
same-day pull gets the statements. The lookback that remains in the design is outage
insurance and nothing else.

### F4 — premarket/afterhours is the *classified* calendar, not the whole calendar

There is no market-wide earnings calendar on our tier. The spec carries exactly five
earnings paths: `premarket`, `afterhours`, `/api/earnings/{ticker}`,
`/api/stock/{ticker}/earnings`, and the 403-gated `/api/companies/{ticker}/earnings-estimates`.

A name whose `report_time` UW has not classified appears in **neither** list. Verified
against `/api/earnings/{ticker}`, which returns `report_time: "unknown"` for all four
names checked, none of which appear on their own report date's calendar:

| ticker | report date | rows on calendar that day | listed |
|---|---|---|---|
| ISRG | 2026-07-28 | 61 pre / 84 after | no |
| SONY | 2026-08-06 | 202 pre / 257 after | no |
| DJCO | 2026-08-13 | 85 pre / 97 after | no |
| POET | 2026-08-17 | 5 pre / 7 after | no |

Of the 38 universe names the calendar never showed in 120 days, 26 are ETFs and one
(JNPR) was acquired — correctly absent. The residual blind spot is ~7–11 real companies,
≈2% of the statement-bearing universe.

**Consequence: the monthly full sweep must stay** as a backstop. It also happens to be
the mechanism that delivers F2's late-arriving dates, so it earns its keep twice.

Note for the implementation: peak days exceed one page (202 and 257 rows). Paginate.

### F5 — the daily design is cheaper than the monthly one it replaces

| | UW calls |
|---|---|
| calendar, 2 slots × ~2 pages | ~6/day |
| reporters in universe, 704/120 ≈ 5.9/day × 4 calls | ~24/day |
| **daily total** | **~30/day ≈ 900/month** |
| monthly blind sweep, 450 × 4 | 1,800/month |

Against a 120k/day budget both are noise, but the daily path is half the spend and 30×
fresher. Keeping the monthly sweep as backstop puts the total at ~2,700/month.

---

## What this changes

1. Match breakdown periods with a ±7-day tolerance (F1) — recovers 1,785 rows.
2. Refresh `filing_published_at` on conflict when we hold NULL (F2) — without this,
   F1's fix only helps rows ingested after it ships, and late dates stay lost.
3. Daily calendar-driven ingest (F3, F5) — the user's proposal, validated.
4. Keep the monthly sweep (F4, F2) — blind-spot backstop and late-date delivery.

## What was NOT established

- **When** breakdown publishes a period's date. Every probe here is a single snapshot of
  UW's current state; "arrives late" is inferred from the frontier gap (F2), not observed.
  Confirming it needs two snapshots weeks apart, which the fixed upsert will produce as a
  side effect.
- Whether the ~2% calendar blind spot is stable or drifts with UW's classification.
- The 3 non-landed 12-week filers (AZO, COST, FEIM) are diagnosed from their fiscal
  calendars, not confirmed against their filings.

---

## Production outcome — 2026-08-23, v0.12.16

Both fixes deployed to the mini (all 9 containers recreated on `argon-app:latest`,
`/app/VERSION` = 0.12.16), then one monthly `fundamental_ingest` run through the
scheduler's own helpers inside `argon-worker-uw-0-1`.

```
{"tickers": 450, "inserted": 0, "touched": 89553,
 "violations": 0, "failed": 0, "filing_date_tolerance": 8520}
```

| `fundamental_statement_obs` | before | after | delta |
|---|---:|---:|---:|
| total rows | 89,758 | 89,758 | 0 |
| rows with NULL `filing_published_at` | 43,210 | 34,690 | **−8,520** |
| … as % of panel | 48.14% | 38.65% | −9.49pp |
| distinct (ticker, period_end) with NULL | 14,550 | 11,721 | **−2,829** |
| tickers holding ≥1 NULL | 418 | 418 | 0 |

**The `filing_date_tolerance` counter equals the NULL delta exactly (8,520).** Every
tolerance-path resolution filled a NULL; none landed on a row that already held a date.
That is the counter doing its job — the hit rate is measured, not assumed (open question 1,
now answered: the tolerance never fired where exact matching already worked).

`inserted: 0` on a 450-ticker full re-pull is the second thing worth reading. The panel
did not grow by a single row, which is `content_hash` correctly excluding UW's
`inserted_at`/`updated_at` — a re-pull of unchanged statements is a no-op, and the dates
arrived purely through the new `COALESCE` on the `DO UPDATE` path.

AAPL landed at 207 dated / 42 NULL — **exactly** the 42 the local single-ticker validation
predicted before deploy.

### The estimate was low by 4.8x, and the reason is cohort scoping

This section's plan predicted ~592 periods / ~1,785 rows. Actual: 2,829 periods / 8,520
rows. The probe measured the 129 tickers it sampled; production ingests 450. Nothing about
the *mechanism* was wrong — the per-ticker recovery matched AAPL to the row — but the
population was a third of the real one, so the total was a third-ish of the real total.
A recovery estimate read off a sample is a statement about the sample. Scale it by the
universe before quoting it as a total, or quote it per-ticker.

### The residual 34,690 NULLs are a vendor-history limit, not a bug

| period era | still NULL | dated | NULL % |
|---|---:|---:|---:|
| 2020 and later | 2,868 | 29,434 | **8.9%** |
| before 2020 | 31,822 | 25,634 | **55.4%** |

92% of the remaining NULLs sit before 2020, where `fundamental-breakdown` simply carries
no history to match against. The modern panel — the part any signal is measured on — is
now 91.1% dated. This is why `tickers_with_nulls` did not move: every one of the 418 has
pre-2020 rows breakdown cannot date, so no ticker goes fully clean, and that number was
never going to be the measurement. The row and period counts are.

**Reproduce:** deploy ≥ v0.12.16, then inside `argon-worker-uw-0-1`:
`/app/.venv/bin/python -c` over `fundamental_ingest(conn=…, client=…, schema=…)` built from
`uw_scan.worker.scheduler._repo/_external_api_recorder/_uw_client` — the same closure
`_fundamental_ingest` runs. Cost 1,800 UW calls, ~9 min wall clock.
