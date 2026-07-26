# Can argon source NTM P/E for sector ETFs?

**Date:** 2026-07-26 · **Method:** live entitlement probe against UW, massive.com
and FMP · **Verdict: the NTM level, yes. The NTM history, no.**

> **Superseded on the level, same day.** This probe checks *endpoint* access and
> concluded the NTM level was buildable. Actually building it
> (`scripts/research/ntm_pe_feasibility.py`, results in
> `2026-07-26-ntm-pe-feasibility.json`) showed it is not: FMP entitles
> `/analyst-estimates` **per symbol**, so 26 of 30 SOXX constituents are 402 and only
> 26.59% of fund weight resolves — and the blocked names are systematically the
> high-multiple semis cohort, biasing the aggregate downward. Estimates also arrive in
> issuer reporting currency with **no currency field** (TSM: TWD EPS 323.34 against a
> USD ADR → P/E 0.65). Everything below about *history* stands unchanged; read the
> "level is buildable" conclusion as refuted. Single-name NTM P/E for a whitelisted
> ticker does work.

**Reproduce:**

```bash
uv run --with pyyaml python scripts/research/ntm_pe_sourcing_probe.py
```

Read-only. Section H spends ~7 calls of FMP's 250/day quota and self-skips if the
apex secrets file is absent.

## Question

```
ValuationHeat = z(PE_level) + z(PE_expansion_3m) − z(NTM_EPS_revision_3m)
```

on **NTM** P/E. No vendor publishes NTM P/E for an ETF, so it must be built
bottom-up:

```
NTM_PE(etf) = Σ wᵢ·Pᵢ / Σ wᵢ·NTM_EPSᵢ
```

Three independent inputs: holdings weights, per-constituent forward EPS covering
twelve months, and point-in-time history of both.

## Result

| Input | Source | Status |
|---|---|---|
| ETF holdings weights | UW `/api/etfs/{t}/holdings` | ✅ `ticker` + `weight` |
| Constituent prices | massive grouped-daily | ✅ 12,410 tickers in **one** call |
| **Forward EPS curve (FY1…FY5)** | **FMP `/stable/analyst-estimates`** | ✅ **200 — epsAvg/High/Low + analyst count** |
| Forward EPS, quarterly | FMP `period=quarter` | ❌ 402 premium |
| Forward EPS, Q+1 only | UW `/api/stock/{t}/earnings` | ✅ 1 quarter, ~30y of reports |
| Forward EPS curve | UW `/api/companies/{t}/earnings-estimates` | ❌ 403 advanced tier |
| Forward EPS curve | massive `/benzinga/v1/*` (5 paths) | ❌ 403 not entitled |
| ETF holdings (SMH/MAGS gap) | FMP `/stable/etf/holdings` | ❌ 402 restricted |
| Constituent trailing EPS | massive `/vX/reference/financials` | ✅ 64 quarters to 2010, `filing_date` |
| **Historical estimate snapshots** | **all three** | ❌ **none — see below** |

FMP's curve is the piece that was missing:

```
FY2028 (ends 2028-01-25)  epsAvg=12.75249  31 analysts
FY2029                    epsAvg=15.2316   16 analysts
FY2030                    epsAvg=12.29     12 analysts
FY2031                    epsAvg=20        13 analysts
```

With FY1 and FY2 in hand, NTM is the standard calendar interpolation between them
— `w·FY1 + (1−w)·FY2`, `w` = fraction of the next 12 months falling in FY1. That
is how vendors compute forward P/E, and it is now reproducible in-house.

## Three traps in the FMP path

**1. Pagination runs backwards from the far future.** `limit` truncates from the
*furthest-out* year, not the nearest:

```
limit=3   200  n=3   2029-01-25..2031-01-25   <- omits FY1 AND FY2. Useless for NTM.
limit=10  200  n=10  2022-01-25..2031-01-25   <- smallest that reaches the near years
limit=20  402  Premium Query Parameter
```

A `limit=3` request looks like a sensible economy and returns a well-formed 200
containing exactly the years NTM does not need. **Always request `limit=10`.**

**2. Annual only.** `period=quarter` is 402, so NTM must be interpolated from
fiscal-year figures rather than summed from four quarterly ones. Interpolation adds
error around fiscal-year boundaries and assumes earnings accrue evenly within a
year — wrong for seasonal sectors (XLY, XLP).

**3. Legacy endpoints are dead.** `/api/v3/*` and `/api/v4/*` return
403 "Legacy Endpoint … only available for legacy users who have valid subscriptions
prior August 31, 2025." Everything must go through `/stable/`. Note the two failure
codes are not interchangeable: **403 = retired legacy, 402 = your plan lacks it.**

## The wall that stands: no historical estimate series

FMP returns **one row per fiscal year — the current estimate for it**. It does not
return the FY2027 consensus as it stood on 2024-03-15. Neither does UW: its
`/stock/{t}/earnings` archive shows all 109 NVDA quarters `inserted_at 2026-03-10`
and `updated_at 2026-07-25`, split-adjusted retroactively — a restated bulk load,
not contemporaneous capture. massive has no estimates surface at all.

That kills two of the three factor terms as *historical* series:

- `PE_level` needs a 5–10y percentile of NTM P/E. Unavailable, and unpurchasable at
  this tier — point-in-time consensus history is an I/B/E/S / Refinitiv / FactSet /
  Compustat product.
- `EPS_revision_3m` needs the estimate's own path. All three vendors overwrite in
  place.

`PE_expansion_3m` is partially recoverable — prices are known historically, so the
price half of `Δlog(PE) = Δlog(P) − Δlog(EPS)` is exact — but the EPS half inherits
the same restated-archive problem.

## Budget

FMP's quota is **250 requests/day** against **599 distinct constituents**. Cost per
ticker is 1 call (`limit=10`). Coverage math from live weights:

```
 80% of aggregate weight ->  241 tickers -> 1 day per full refresh
 90% of aggregate weight ->  338 tickers -> 2 days
100% of aggregate weight ->  599 tickers -> 3 days
```

Two workable shapes: an 80%-weight daily refresh (241 calls, 9 spare — no headroom
for retries), or a **3-day rotation over the full 599** at ~200/day. Estimates
revise on analyst action, not daily, so 3-day staleness is defensible and the
rotation leaves quota free. Renormalising weights over a covered subset introduces a
bias toward large caps, but a roughly constant bias largely cancels in a
percentile-of-own-history measure.

Prices cost 1 massive call/day for the entire universe. Weights cost 1 UW call per
ETF per day. Neither is a constraint.

## Holdings coverage — unchanged, and still blocking two tickers

`weight_sum` is the honest completeness check; HTTP is 200 in every case:

```
XLB 100.02%  XLC 102.06%  XLE  99.92%  XLF 100.63%  XLI  99.59%  XLK  99.84%
XLP  99.66%  XLRE 100.42% XLU 100.33%  XLV 100.19%  XLY 100.26%  SOXX 100.02%
IGV  99.98%
SMH    0.00%  rows=0  — /info declares holdings_count: 26
MAGS   0.00%  rows=0  — declared 0
SPY   91.25%  rows=250 — truncated at a 250-row page cap
```

**SMH serves `{"data": []}` at HTTP 200 while its own `/info` reports 26 holdings** —
the same silent-empty signature as the `in-outflow` outage behind the SOXX/SMH
divergence. FMP's `/stable/etf/holdings` is 402, so it is not a fallback. Bottom-up
anything remains impossible for SMH and MAGS until holdings come from the issuers
directly, the way `sources/etf_holdings.py` already scrapes the gold complex.

## Recommendation

**The NTM level is buildable now** — FMP curve + UW weights + massive prices, on a
3-day rotation, for 13 of the 15 ETFs. That is a genuine new capability: the desk
currently cannot answer "what is SOXX trading at on forward earnings."

**The factor as specified is still not buildable**, because two of its three terms
are z-scores against history that does not exist. Shipping it would mean fitting
`PE_level` percentiles to a restated archive we cannot audit, and dropping
`EPS_revision` entirely.

**Do not wire any of it into the crowding score.** The composite it would join has
one leg empirically shown to predict nothing stable
(`2026-07-26-sector-crowding-lifecycle.md`) and an aggregator with no support.

**Do start capturing the FMP curve daily.** This is the highest-value, lowest-cost
item the probe found, and it inverts the usual accrual complaint:

- It is the *only* way `EPS_revision` will ever exist — every vendor overwrites, so
  the series has to be ours.
- Unlike `PE_level`, a revision needs **no long percentile history to be meaningful**.
  It is a change, not a level: usable in one quarter, not five years.
- It costs ~200 FMP calls/day inside an existing quota, plus one narrow table.
- It is immune to the provenance problem — we record what we observed, with our own
  timestamp.

Let it accrue, then test the revision term as a standalone series against forward
returns before it touches a panel. The level terms can be added later from the same
capture if revision proves to carry signal, and dropped if it does not.
