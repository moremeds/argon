# Rates market layer design (MC3 Part A)

**Status:** specified. Preregistered before any adapter was written; the availability
measurements in §3 were taken against live publishers on 2026-08-21 and are the reason two
of this document's rulings changed shape before implementation started.

**Scope:** the three rates causal roles that resolve to nothing today — `supply`,
`positioning`, `plumbing`. `curve` and `decomposition_component` already have evidence and
are out of scope except where a rule spans them.

**Parent plan:** `docs/superpowers/plans/2026-08-12-macro-mc3-usd-gold-state.md`

---

## 0. Deviations from the plan

1. **R1 was overturned for both sources it was written for.** The plan set
   `published_at = NULL` as the default for backfilled history because deriving a release
   instant by rule is unsafe. Measurement in §3 found that both publishers expose a real
   instant, so the fallback is not used by any source in this milestone. The rule stays as
   the contract for a future publisher that offers none. §3.4 records what changed.

2. **The supply series key gained a second field.** The plan and MC2's fixture both spoke of
   the security term as the identity. Measurement in §2.1 found that a 10-Year TIPS is
   indistinguishable from a nominal 10-Year note by term and security type alone, at half the
   size. The key is `(securityTerm, type)`.

3. **Positioning state labels changed from long/short to high/low.** Measured: leveraged
   money is net short in all 205 weeks of the sample, so an absolute long/short label would
   name a side the category never takes. §4.2 has the distribution.

4. **A live lookahead defect was found in the legacy CFTC path.** Not a planned finding.
   `sources/cftc_tff.py:210` sets `release_date = obs_date + 3 days`, which over-claims
   availability by 3 days on federal-holiday weeks. §3.2 has the measurement; Task A3 fixes
   it at the source rather than building the correct path beside a known-broken one.

5. **The supply request is per instrument type, and that is not a preference.** Measured
   during Task A3's first live run: `TA_WS/securities/auctioned` caps every response at 250
   rows, and the cap is spent per request. Unfiltered, it reaches back eighteen months and
   yields **six** new issues per coupon term — one above the five the baseline rule needs.
   `type=Note` reaches 2021 (22 ten-year new issues) and `type=Bond` reaches 2012 (58
   thirty-year). The first implementation omitted the parameter; nothing failed, the history
   was simply four years shallower, which is why a test now pins the parameter reaching the
   request.

6. **The CFTC select is an explicit column list, not `:*,*`.** These bytes are kept forever.
   Over one 120-day window all 89 columns cost **12.5 MB** against **56 KB** for the fourteen
   the parser reads, for identical parsed output. The scheduled request is also a 120-day
   window rather than full history — the longest measured publication outage was ten weeks,
   so 120 days clears the worst observed backlog — and deep history is a one-off backfill
   (`scripts/backfill/macro_market_layer_backfill.py`).

7. **Date-only publisher fields resolve to Eastern midnight, not UTC midnight.**
   `sources/fred_macro._instant` uses UTC midnight for an ALFRED vintage day. For a Treasury
   announcement that would place availability at 20:00 the previous evening in Washington —
   claiming the offering size was knowable before the day it was announced on began. The
   market layer uses ET midnight. FRED is deliberately **not** changed to match:
   `available_at` is part of the observation identity (`macro_observation_content_hash`), so
   shifting it would re-mint every vintage already stored rather than correct one.

8. **The ingest is scheduled at 19:25 ET on `massive-0`, inside the macro block.** The plan
   said `uw-0`, clear of the 18:45–19:40 block. Both changed for the same reason: the macro
   evidence block already runs on `massive-0` under `_should_schedule_macro_policy_ingest`,
   these publishers cost zero UW budget, and the state compute at 19:40 is the layer's only
   consumer — scheduling after it would make every release a full day stale to the state
   that reads it.

9. **A pre-existing test fixture was carrying fabricated auction values.** Not a planned
   finding. `tests/unit/sources/test_treasury_supply.py` asserted 912810UL0 as a 30-Year at
   $25bn on 2026-05-14 (the publisher has no auction that day, and that CUSIP is a 20-Year
   first sold at $16bn) and 91282CPU9 at $16bn / 5.122% (really a TIPS at $19bn / 2.169%).
   Adding real announcement dates to invented auctions would have made the fixture more
   convincing rather than more correct, so it was replaced with four real rows — including
   the TIPS collision §2.1 describes.

## 1. What the market layer is, and what it is not

The rates domain publishes one policy state — what the committee did — plus a set of market
**sub-states** that describe conditions the committee acts into. The policy state is gated by
the three policy paths and nothing else. A sub-state describes its own slice and carries its
own confidence.

This split already exists in code and is correctly drawn. `macro/rates.py:486` records it:
the market factors "do not gate the policy state but their sub-states are unavailable." This
milestone makes them available. It does not move them into the policy state.

## 2. The three roles

| Role | Publisher | Series identity | Unit | Cadence |
|---|---|---|---|---|
| `supply` | TreasuryDirect `TA_WS/securities/auctioned` | `(securityTerm, type)` — see §2.1 | `usd_offering_amount` | quarterly refunding |
| `positioning` | CFTC TFF futures-only (Socrata `gpe5-46if`) | contract code + tenor bucket | `contracts_net` / `pct_open_interest` | weekly, Tuesday positions |
| `plumbing` | FRED | candidates in §5 | per series | daily / weekly |

### 2.1 Supply identity is the term AND the type, and reopenings are excluded

MC2 already preregistered the reopening half in
`tests/fixtures/macro/inflation_rates_golden.json` under `supply_history`, with the reason
stated: "reopenings are excluded because a reopening adds to an existing security and its
size is not comparable to a new issue's." That is adopted unchanged. A reopening's
`offeringAmount` is a marginal add to an outstanding security; comparing it against a new
issue's size makes a smaller number look like a supply reduction.

**The term alone is not an identity, and this was measured.** A 10-Year TIPS and a nominal
10-Year note both carry `securityTerm = "10-Year"` and `securityType = "Note"`. Only the
separate `type` field distinguishes them, and their sizes differ by half:

| auctionDate | securityTerm | securityType | type | offeringAmount |
|---|---|---|---|---|
| 2026-05-12 | 10-Year | Note | Note | 42,000,000,000 |
| 2026-07-23 | 10-Year | Note | **TIPS** | **21,000,000,000** |
| 2026-08-12 | 10-Year | Note | Note | 42,000,000,000 |
| 2026-02-12 | 30-Year | Bond | Bond | 25,000,000,000 |
| 2026-02-19 | 30-Year | Bond | **TIPS** | **9,000,000,000** |

A series keyed on `securityTerm` interleaves these, and the multi-quarter-high rule reads the
alternation as a supply collapse and recovery every quarter — a fabricated signal produced
entirely by a taxonomy error. This is the same shape as the argon/GICS `Energy` collision:
two vocabularies sharing one label with different meanings.

**Ruling:** the series key is `(securityTerm, type)`, and the nominal series a rates supply
sub-state describes is the one where `type == securityType`. TIPS supply is a separate series
and is not mixed into it. MC2's frozen `supply_history` block is nominal-only and stays valid;
its stated filter (`reopening == No`) simply was not sufficient on its own, and its window
happened not to contain a TIPS auction.

The engine's existing rule needs `supply_baseline_quarters + 1 = 5` observations per term
(`macro/rates.py:105`, `macro/rates_rules.py:257`), so a term with fewer than five new
issues in the window produces no supply sub-state and says so.

### 2.2 Positioning identity is the contract, not the aggregate

Dealer, asset-manager and leveraged-money nets move against each other by construction — a
leveraged short is somebody's long. Summing them to one "positioning" number destroys the
only information the report carries. Each reported category is its own factor.

## 3. Availability, measured

Every observation needs an honest `available_at`. What each publisher actually offers was
measured against the live endpoints on 2026-08-21 rather than assumed.

### 3.1 Supply — the publisher gives an announcement date

`TA_WS/securities/auctioned` returns `announcementDate` as a first-class field:

```
cusip 91282CRF0  securityTerm 10-Year  reopening No
announcementDate 2026-08-05T00:00:00
auctionDate      2026-08-12T00:00:00
issueDate        2026-08-17T00:00:00
offeringAmount   42000000000
```

The offering size is known when Treasury announces it, a week before the auction. So
`available_at = announcementDate`, and `period_end = auctionDate`. Using the auction date for
both would claim we learned the size a week later than we did — an error in the safe
direction, but still wrong, and it would misalign supply against a curve move that had
already responded to the announcement.

`sources/treasury_supply.py:TreasuryAuctionRow` does not currently carry
`announcementDate`. Task A3 adds it.

### 3.2 Positioning — the derived release date is wrong on holiday weeks

The CFTC Socrata payload has no publisher release field: 89 columns, of which the only
date-bearing ones are `report_date_as_yyyy_mm_dd` (the Tuesday positions were held) and a
report-week label. The existing client fills the gap by deriving
`release_date = obs_date + 3 days` (`sources/cftc_tff.py:210`).

Socrata does expose row system fields, and `:created_at` is the instant CFTC loaded the row.
Measured across every report date since 2026-06-01:

| report_date | rule `+3d` | actual `:created_at` | |
|---|---|---|---|
| 2026-06-02 | 2026-06-05 | 2026-06-05T19:30:56Z | same |
| 2026-06-09 | 2026-06-12 | 2026-06-12T19:30:56Z | same |
| **2026-06-16** | **2026-06-19** | **2026-06-22T19:30:53Z** | **+3d — Juneteenth** |
| 2026-06-23 | 2026-06-26 | 2026-06-26T19:30:53Z | same |
| **2026-06-30** | **2026-07-03** | **2026-07-06T19:30:52Z** | **+3d — Independence Day observed** |
| 2026-07-07 | 2026-07-10 | 2026-07-10T19:31:01Z | same |
| 2026-07-14 | 2026-07-17 | 2026-07-17T20:54:53Z | same |
| 2026-07-21 | 2026-07-24 | 2026-07-24T19:30:05Z | same |
| 2026-07-28 | 2026-07-31 | 2026-07-31T19:30:06Z | same |
| 2026-08-04 | 2026-08-07 | 2026-08-07T19:30:05Z | same |
| 2026-08-11 | 2026-08-14 | 2026-08-14T19:30:06Z | same |

Wrong in 2 of 11 weeks, and wrong in the unsafe direction each time: the rule marks a report
knowable on the Friday when it was not published until the following Monday. A replay with an
`as_of` inside that gap reads a position it could not have seen. That is lookahead, and it is
in the legacy path today.

Hardcoding the release *time* instead is no better: 2026-07-17 loaded at 20:54Z, not the
19:30Z the other ten weeks used. The schedule is not constant enough to derive at either
granularity.

**Ruling:** `available_at = :created_at`, fetched via `$select` alongside the data columns.
Task A3 also replaces the derivation in `sources/cftc_tff.py` so the legacy table stops
carrying the lookahead.

### 3.3 Plumbing — FRED vintages already answer it

FRED/ALFRED is vintage-bearing and MC2's `observations_known_on` already resolves
availability from the vintage. No new mechanism is needed. The daily-series window
constraint from MC2 Task 9 applies: `observation_start == realtime_start ==
DAILY_VINTAGE_START` for daily series, unbounded for monthly, split by the contract's own
`frequency` in `request_window()`.

### 3.4 R1, revised

The plan's R1 set `published_at = NULL` with `available_at` at our retrieval clock for
backfilled history, because a rule-derived release instant is indistinguishable in the schema
from an observed one. Measurement eliminated the case it was written for: all three
publishers expose a real instant.

R1 survives as the contract for any future source that offers none, and its reasoning is
unchanged — `published_at` is nullable under `115_macro_evidence.sql:95`, and migration 119
already allows exactly one `NULL -> value` resolution carrying `available_at` with it, so a
conservative row can be promoted later without rewriting history.

What R1 now forbids explicitly: filling `available_at` from a schedule rule when the
publisher exposes an instant. §3.2 is the worked example of why.

## 4. Sub-states

Each role publishes `state`, `direction`, `velocity`, `confidence` and its own evidence refs.
None of them changes the policy state.

| Role | State labels | Direction basis | Velocity horizon |
|---|---|---|---|
| `supply` | `ELEVATED` / `IN_RANGE` / `REDUCED` / `UNKNOWN` | latest new issue vs the prior `supply_baseline_quarters` | quarter over quarter, per term |
| `positioning` | `STRETCHED_HIGH` / `STRETCHED_LOW` / `IN_RANGE` / `UNKNOWN` — see §4.2 | net as a share of open interest vs its own trailing distribution | week over week, per category |
| `plumbing` | `AMPLE` / `TIGHTENING` / `STRESSED` / `UNKNOWN` | level and momentum of the selected series | 4-week and 13-week |

`UNKNOWN` is mandatory whenever the role's inputs are absent, stale past their own cadence,
or below the minimum row count. It is never `NEUTRAL` — absence is not a centred reading, and
rendering it as one is the defect `macro/confidence.py` was written to replace.

### 4.2 The labels are relative to the series, not to zero

Leveraged money in the 10-year note future is net **short in every week of the measured
sample**: across 205 releases from 2022-09-13 to 2026-08-11, the 10th percentile of net as a
share of open interest is -42.0% and the 90th is -21.3%. There is no long side.

So `STRETCHED_LONG` / `STRETCHED_SHORT` would be a false vocabulary — the least-short week in
four years still sits at -16% of open interest, and labelling it "long" states a position the
category has never held. The labels are `STRETCHED_HIGH` and `STRETCHED_LOW`, meaning high or
low **against the series' own trailing distribution**, and the sub-state carries the raw net
so the sign is never inferred from the label.

This generalises: a positioning series with a structural side must be scored against itself.
A threshold at zero would fire permanently for one category and never for another.

### 4.1 Confidence, and what R2 fixes

R2 stands: `POLICY_REQUIRED` does not gain a market role. `macro/rates.py:169` already
documents why widening the policy denominator is unsafe — it would let the market shadow
stand in for an absent dealer path and report full coverage.

Each sub-state computes its own confidence through the shared `compute_confidence`, over its
own `required_series`. A surface that renders a sub-state beside the policy state must render
both confidences, labelled. Rendering one number above a panel containing both is the
presentation defect this milestone must not ship.

`market_factors_absent` stays an `informational` term and should report `0` once this lands.
It is kept, not deleted, so a future regression is visible.

## 5. Plumbing series candidates

Task A2 selects; this section names the field and the decision rule, not the answer.

| Candidate | What it carries | Expected frequency |
|---|---|---|
| `SOFR` | secured overnight financing rate | daily |
| `EFFR` | effective fed funds rate | daily |
| `RRPONTSYD` | overnight reverse repo take-up | daily |
| `WRESBAL` | reserve balances at Federal Reserve banks | weekly |

Decision rule: a candidate is selected only if it exists on FRED, its frequency matches the
table above, and — for a daily series — its vintage count under `DAILY_VINTAGE_START =
2021-01-01` clears FRED's 2000-vintage cap with at least two years of headroom. A candidate
that fails any clause is rejected in the probe verdict with the measured reason, and the
plumbing sub-state reports `UNKNOWN` for the slice it would have covered rather than
substituting a neighbour.

None of the four is registered in `sources/fred_macro.py` today, which carries exactly 11
series.

**Probe result (2026-08-21): all four selected.** `docs/research/2026-08-21-rates-market-layer-probe/VERDICT.md`
carries the measurement. Two things it found that change the work:

- the three daily series sit at ~250 vintages/year against the 2000 cap, leaving 2.3–2.4
  years of headroom. That clears the rule, but only just, so
  `test_daily_vintage_start_has_not_expired` must be extended to cover them — otherwise it
  keeps passing on the original three while these start returning HTTP 400.
- a FRED title carries the publisher's release-table path as a prefix. `WRESBAL` reads
  "Liabilities and Capital: Other Factors Draining Reserve Balances: **Reserve Balances with
  Federal Reserve Banks**", and truncating it inverts the apparent concept. Match the leaf,
  not the prefix.

**And the positioning ruling got stronger.** The `obs_date + 3 days` derivation is wrong on
36 of 205 releases (17.6%) and **always early**. The large errors are not holidays: they are
two publication outages — the ION Markets incident from 2023-01-31 and the government-funding
lapse from 2025-09-30 — where the rule claims data was knowable up to 47 days before it
existed, for ten consecutive weeks. A holiday calendar cannot fix this; an outage is not on a
calendar. Nor can a fixed release time: 15:30 ET is 19:30Z or 20:30Z depending on daylight
saving, so the observed times split 120/69 across the two.

## 6. Contradictions

| Rule | Fires when | Notes |
|---|---|---|
| `supply_pressure_without_macro_confirmation` | supply at a multi-quarter high while the nominal move is not carried by inflation compensation | **already implemented** at `rates_rules.py:244` and already tested, but has never fired in production because no supply observation has ever existed. A3 makes it live for the first time. |
| `positioning_against_curve_direction` | a stretched net position on the opposite side of the realised curve move over the same window | new |
| `plumbing_stress_without_policy_change` | plumbing `STRESSED` while the policy state is unchanged | new; describes a funding event the committee has not responded to, and asserts nothing about what it will do |

A contradiction is an observation about evidence disagreeing. It never resolves into a
direction, and it never changes a state label.

## 7. Golden scenarios

Frozen in `tests/fixtures/macro/rates_market_layer_golden.json`. Every value is fetched from
the live publisher at authoring time and frozen with the instant that made it knowable. The
`expect` blocks are preregistered predictions and must not be edited to match whatever the
engines produce.

| # | id | What it pins |
|---|---|---|
| 1 | `supply_elevated_against_neutral_macro` | supply sub-state `ELEVATED`; the existing contradiction fires on real auction rows |
| 2 | `positioning_stretched_against_curve` | a stretched net opposite the realised curve move; the new contradiction fires |
| 3 | `plumbing_stress_under_unchanged_policy` | plumbing moves, policy state does not; no direction is inferred for policy |
| 4 | `cot_week_never_published` | a genuinely absent week produces `UNKNOWN`, distinguished from a parse failure |
| 5 | `holiday_shifted_release_is_not_knowable_early` | an `as_of` between the derived Friday and the real Monday `:created_at` must NOT see the row. Pins §3.2 as a test, so the lookahead cannot return |
| 6 | `positioning_stale_past_its_cadence` | plumbing fresh, positioning stale past weekly cadence; the domain's freshness takes the minimum, not the mean |
| 7 | `supply_term_below_minimum_rows` | a term with fewer than 5 new issues produces no sub-state and names the shortfall |

## 8. Exit criteria this design must satisfy

- `supply`, `positioning` and `plumbing` resolve to real observations with publisher-provided
  availability;
- no evidence row is sourced from a legacy overwrite-on-conflict table;
- the holiday-shift scenario passes, and the legacy derivation is gone;
- each sub-state publishes its own confidence; `POLICY_REQUIRED` is unchanged and a test
  fails if a market role enters it;
- `market_factors_absent` reports `0` and the term survives;
- an absent input produces `UNKNOWN`, never `NEUTRAL`.
