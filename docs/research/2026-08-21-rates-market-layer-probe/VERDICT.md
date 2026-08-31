# VERDICT — rates market-layer sources

Probed 2026-08-20 against live endpoints. Spec: `docs/superpowers/archive/specs/2026-08-21-rates-market-layer-design.md`.

## Plumbing — all four selected

| Series | Frequency | Units | Vintages | Per year | Headroom | Verdict |
|---|---|---|---|---|---|---|
| `SOFR` | daily | % | 1404 | 249.4 | 2.4y | **SELECT** |
| `EFFR` | daily | % | 1411 | 250.7 | 2.3y | **SELECT** |
| `RRPONTSYD` | daily | Bil. of US $ | 1400 | 248.7 | 2.4y | **SELECT** |
| `WRESBAL` | weekly | Mil. of U.S. $ | 1143 | 48.3 | 17.7y | **SELECT** |

All four resolve at the frequency the spec assumed, and none is clamped: every series'
earliest observation carries a true vintage later than the window edge, which is the
condition a bounded daily window rests on.

**The headroom is tight and that is the finding.** The three daily series sit at
~250 vintages/year against a 2000 cap, leaving 2.3–2.4 years. That clears the spec's
2-year rule, but only just, and it means `DAILY_VINTAGE_START` renewal comes due on these
series at roughly the same time as the existing three. `test_daily_vintage_start_has_not_expired`
must cover the new series or it will keep passing on the old ones while these start
returning HTTP 400.

`WRESBAL` is weekly, so it takes the unbounded branch and still returns
1143 vintages — under the cap with
17.7y of room. Its title is
"Liabilities and Capital: Other Factors Draining Reserve Balances: **Reserve Balances with
Federal Reserve Banks**". The prefix is FRED's H.4.1 table path, not the concept; the leaf
is the series we want. A truncated title reads as the opposite of what it is.

## Supply — the publisher gives an instant, but the term is not an identity

`announcementDate` is a first-class field, leading the auction by
7 days. The offering size is knowable when Treasury announces
it, so `available_at = announcementDate` and `period_end = auctionDate`.

**The date parameters do not work.** startDate/endDate are accepted and ignored; the endpoint returns the same 250-row cap of most-recent auctions. The window must be applied client-side.

**The security term collides across nominal and inflation-linked issues:**

| Term | securityType | by `type` |
|---|---|---|
| 10-Year | Note | `Note` n=6 median $42bn · `TIPS` n=3 median $21bn |
| 30-Year | Bond | `Bond` n=6 median $25bn · `TIPS` n=1 median $9bn |

A 10-Year TIPS and a nominal 10-Year note are both `securityTerm='10-Year'`,
`securityType='Note'`, and the TIPS is half the size. Keyed on the term alone, the
multi-quarter-high rule reads the alternation as a supply collapse and recovery every
quarter. The key is `(securityTerm, type)`.

## Positioning — the derived release date is a systematic lookahead

The payload has 89 columns and
**no publisher release field**. The
existing client fills the gap with `obs_date + 3 days (sources/cftc_tff.py:210)`.

Socrata's `:created_at` is the real load instant. Measured against it across
205 incremental releases:

- **wrong 36 times (17.6%)**
- **always early** — every mismatch over-claims availability; not one is conservative
- delays run from 1 to 47 days

### It is worst exactly when it matters most

17 of the mismatches exceed 5 days, and they are not scattered — they are two
publication outages, each with a converging backlog:

| Report date | Rule claims knowable | Actually published | Error |
|---|---|---|---|
| 2023-01-31 | 2023-02-03 | 2023-02-24 | **+21d** |
| 2023-02-07 | 2023-02-10 | 2023-03-03 | **+21d** |
| 2023-02-14 | 2023-02-17 | 2023-03-08 | **+19d** |
| 2023-02-21 | 2023-02-24 | 2023-03-10 | **+14d** |
| 2023-02-28 | 2023-03-03 | 2023-03-14 | **+11d** |
| 2023-03-07 | 2023-03-10 | 2023-03-16 | **+6d** |
| 2025-09-30 | 2025-10-03 | 2025-11-19 | **+47d** |
| 2025-10-07 | 2025-10-10 | 2025-11-21 | **+42d** |
| 2025-10-14 | 2025-10-17 | 2025-11-25 | **+39d** |
| 2025-10-21 | 2025-10-24 | 2025-12-02 | **+39d** |
| 2025-10-28 | 2025-10-31 | 2025-12-05 | **+35d** |
| 2025-11-04 | 2025-11-07 | 2025-12-09 | **+32d** |
| 2025-11-10 | 2025-11-13 | 2025-12-10 | **+27d** |
| 2025-11-18 | 2025-11-21 | 2025-12-12 | **+21d** |
| 2025-11-25 | 2025-11-28 | 2025-12-15 | **+17d** |
| 2025-12-02 | 2025-12-05 | 2025-12-17 | **+12d** |
| 2025-12-09 | 2025-12-12 | 2025-12-19 | **+7d** |

The first cluster (6 weeks from 2023-01-31) is the ION Markets incident; the
second (11 weeks from 2025-09-30) is the government-funding lapse. In both, the
legacy rule asserts the data was knowable up to
47 days before it existed — for ten consecutive
weeks during a major disruption. A backtest reading `rates_cftc_tff_weekly` would have
positioned on reports that had not been published, and the error is largest precisely when
positioning data is most valuable.

This is why the rule cannot be repaired by adding a holiday calendar. An outage is not on
a calendar.

### Nor by hardcoding the release time

Release times in UTC: `19:30` ×120 · `20:30` ×69 · `19:31` ×7 · `20:31` ×6 · `20:12` ×1. The 19:30/20:30 split is US daylight saving — 15:30 ET is
19:30Z under EDT and 20:30Z under EST — so a fixed UTC constant is wrong for half the
year, and a fixed ET time still misses all 36 shifted dates.

### The bulk-load boundary

848 rows share `:created_at` `2022-09-13T14:16:09.004Z`, spanning
report dates 2006-06-13 to 2022-09-06.
That is a Socrata load event, not a release. The 205 rows after it
(2022-09-13 to 2026-08-11) each
carry a unique timestamp.

So the boundary is detectable from the data rather than hardcoded: **a `:created_at`
covering more than one distinct `report_date` is a load event.** Stated per report date and
not per row on purpose — one real release covers every contract in the file, so "shared by
many rows" would flag genuine releases too.

Pre-load rows have no knowable publication instant, so they take R1's treatment:
`published_at = NULL`, `available_at` = the load instant. Conservative, never over-claiming,
and promotable later through migration 119's single `NULL -> value` resolution.

## Rulings

| # | Ruling |
|---|---|
| 1 | Select `SOFR`, `EFFR`, `RRPONTSYD`, `WRESBAL` for `plumbing`; extend the `DAILY_VINTAGE_START` expiry test to cover the three new daily series |
| 2 | `supply` series key is `(securityTerm, type)`; `available_at = announcementDate`; apply the auction window client-side |
| 3 | `positioning` `available_at = :created_at`; replace the `obs_date + 3 days` derivation in `sources/cftc_tff.py` rather than building the correct path beside it |
| 4 | Pre-bulk-load positioning history gets `published_at = NULL` and the load instant as `available_at`, detected by the shared-timestamp rule, not a hardcoded date |

---

## Task A4 verification — the new daily series churn nothing monthly (2026-08-21)

MC2 Task 9's regression model: a new daily series must not re-mint a monthly one. FRED
returns a series' whole history in one payload, so if the request window for a monthly
series moved, every month in it would re-hash and read as a revision.

Run against `option_wizard_local` with all fifteen registered series after adding SOFR,
EFFR, RRPONTSYD and WRESBAL. Per-series observation counts before and after:

| series | frequency | before | after | |
|---|---|---|---|---|
| PCEPILFE | monthly | 1092 | 1092 | unchanged |
| PCEPI | monthly | 1097 | 1097 | unchanged |
| CPILFESL | monthly | 676 | 676 | unchanged |
| CPIAUCSL | monthly | 680 | 680 | unchanged |
| MEDCPIM158SFRBCLE | monthly | 1029 | 1029 | unchanged |
| TRMMEANCPIM158SFRBCLE | monthly | 1152 | 1152 | unchanged |
| CORESTICKM159SFRBATL | monthly | 858 | 858 | unchanged |
| MICH | monthly | 142 | 142 | unchanged |
| DGS10 | daily | 1408 | 1410 | +2 real vintages since 2026-08-17 |
| DFII10 | daily | 1406 | 1408 | +2 |
| T10YIE | daily | 1409 | 1411 | +2 |
| **SOFR** | daily | 0 | **1405** | new |
| **EFFR** | daily | 0 | **1413** | new |
| **RRPONTSYD** | daily | 0 | **1406** | new |
| ~~WRESBAL~~ | weekly | 0 | ~~1173~~ | **rejected — see below** |

`created=5403 unchanged=10949 failed=()`. Eight of eight monthly series created nothing;
the three existing daily series gained exactly the vintages published since the previous
local ingest.

The structural guarantee behind this is `request_window()` splitting on the contract's own
`frequency`, which `tests/unit/worker/test_macro_series_window.py` parametrizes over
`DEFAULT_SERIES` — so the monthly assertion now covers every registered series
automatically, and the daily assertion picked up SOFR/EFFR/RRPONTSYD without being edited.

**One constant moved.** `VINTAGES_PER_YEAR` in that test was 248, measured on
DGS10/DFII10/T10YIE. EFFR mints **250.7** a year, so it hits FRED's 2000-vintage cap
first, at 2.3 years of headroom. The alarm now keys on 251 — the fastest series, not the
mean, because a mean would put the red build after the date EFFR starts returning HTTP 400.

Reproduce: `uv run python scripts/research/rates_market_layer_probe.py`

### WRESBAL is rejected: its unit is a property of the vintage

Found while picking a window for the plumbing golden scenario, not by looking for it. The
series returned two values for the same period:

```
period 2025-06-04, straight from ALFRED
  {realtime_start: 2025-06-05, realtime_end: 2025-11-12, value: "3294.381"}
  {realtime_start: 2025-11-13, realtime_end: 9999-12-31, value: "3294381.0"}
```

FRED republished the whole history on 2025-11-13 with every value multiplied by a thousand.
Measured across every multi-vintage period in the store: **566 periods, ratio exactly
1000.0 in all of them.** `fred/series` today declares `units='Millions of U.S. Dollars'`, so
every vintage before that date is billions carrying a millions label.

The same scan over all eleven previously registered FRED series found no other case. The one
other period flagged at >10x — `TRMMEANCPIM158SFRBCLE` for 2020-04 — is a genuine revision of
a small annualised rate (0.279 → 0.658 → 0.380 → 0.109 → −0.042 → 0.099, six vintages, all
the same order of magnitude); the ratio is large only because one vintage sits near zero.

Why this disqualifies the series rather than being a detail: a `SeriesEvidenceContract`
declares **one unit per series**, and the ingest stamps that unit on every observation it
writes. So `_observation`'s unit check cannot catch a publisher rebasing — it compares our
claim against our claim. Live reads are unaffected, because every vintage inside a 120-day
window is post-rebasing. A replay with `as_of` before 2025-11-13 reads billions labelled
millions, and a level threshold calibrated in millions would pass it without complaint.

`SOFR`, `EFFR` and `RRPONTSYD` have no multi-vintage periods at all — those three publishers
do not revise — so they carry no equivalent risk and stay selected.

**Recovery path, not taken here.** A per-vintage `publisher_transform` (`rebased_x1000`
before 2025-11-13) would restore the series. It needs its own measurement across the full
history first — the 566-period ratio was measured on what this desk has stored since 2015,
not on every vintage FRED holds — and it means writing a number the publisher never
published into an immutable store, which is a contract change rather than a fix.

Reproduce the scan:

```sql
SELECT series_id, count(*) FROM (
  SELECT series_id, period_end, min(abs(value_numeric)) lo, max(abs(value_numeric)) hi
  FROM uw_scan.macro_observations WHERE source='fred' AND value_numeric <> 0
  GROUP BY 1,2 HAVING count(*) > 1
) t WHERE hi/lo > 10 GROUP BY 1;
```
