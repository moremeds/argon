# VERDICT — P4 was killed by a broken probe, not by the data

**Reproduce:** `UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_concentration_axis_probe.py`
**Trace:** `computability.json` (401 tickers × up to 20 periods, per-period axis/level/share)
**Supersedes:** `docs/research/2026-08-12-fundamental-segment-computability/VERDICT.md` and the
unwritten wide probe at `docs/research/2026-08-13-fundamental-segment-computability-wide/`.

## The number that killed P4 was an artifact

The prior probe returned **geography 0/257** and segment 77/257, and that zero is what closed
the concentration ledger. It is wrong. NVDA's geographic breakdown reconciles to the cent:

```
 country    country:US                            63,769,000,000
 country    country:TW                            12,006,000,000
 country    nvda:ChinaIncludingHongKongMember      4,550,000,000
 continent  nvda:OtherCountriesMember              1,290,000,000
                                                = 81,615,000,000
 product    (untagged consolidated total)          81,615,000,000   exact
```

The old probe reported this as `no_total`.

## Three bugs, each explaining one failure bucket

| Old bucket | n/257 | What was actually wrong |
|---|---:|---|
| geography `no_total` | 180 | **The denominator was scoped to `rev_group`.** UW files the untagged consolidated row under exactly one group — `product` for NVDA — so every geography group looked denominator-less. The total is a property of the *period*, not of the group. |
| segment `no_leaves` | 38 | **`rev_group` is not the breakdown key; the XBRL axis is.** NVDA's geographic members are split across the `country` and `continent` groups while sharing one axis, `srt:StatementGeographicalAxis`. Grouping by `rev_group` shatters one complete partition into two partial ones. |
| segment `ambiguous_axis` | 37 | **`srt:ConsolidationItemsAxis` is a scope tag, not a disaggregation.** Keeping only single-axis rows discards precisely the ASC 280 reportable-segment rows on every filer that tags them `OperatingSegmentsMember`. NVDA's real segment axis — ComputeAndNetworking 74.550 + Graphics 7.065 = 81.615, exact — was thrown away for carrying a qualifier. |
| segment `no_axis_sums_to_total` | 86 | **Real**, and handled rather than excused. One axis can carry several nesting levels at once: NVDA's `ProductOrServiceAxis` holds DataCenter beside its own children (Hyperscale 37.869 + AICloudsIndustrialEnterprise 37.377 = 75.246 = DataCenter, exactly). Level selection recovers the partition — search for the subset of members summing to the period total, take the **coarsest** such subset. |

The three fixes are mechanical. The fourth is a method: among subsets that reconcile, fewest
members wins (the reported level), and a tie at the same size is **refused, not broken**.

Where two families both reconcile, the ASC 280 segment axis beats a product cut. AVGO is the
check that matters here: the earlier probe recorded its two axes disagreeing (76% vs 68%) and
called it ambiguous. The preference rule resolves it to `SemiconductorSolutions 67.65%` across
2 members — AVGO's actual reportable-segment structure.

## Measured, on a stricter test than the one it replaces

401 tickers (every name with ingested statements, not the old 257), up to 20 periods each,
and a **≥6 computable periods** gate the old probe never applied — it read the latest quarter
only, and a share that resolves once carries no trend, which is what spec §6 actually asks for.

| | segment | geography |
|---|---:|---:|
| **trend-bearing (≥6 periods)** | **184 (45.9%)** | **128 (31.9%)** |
| latest-only or short run | 91 | 77 |
| never computable | 102 | 172 |
| no breakdown rows at all | 24 | 24 |
| *prior probe, latest quarter only, n=257* | *77 (30.0%)* | ***0 (0.0%)*** |

The trend-bearing sets are current, not scattered across two decades: **181 of 184** segment
names and **124 of 128** geography names are computable in ≥6 of their **last 8** periods.

**86% of segment computations and 83% of geography come from the full member set reconciling**
(`level: all`) — the least error-prone path. The subset search supplies the rest, dominated by
`subset:2`, and that minority is where a false positive would hide.

## What this does and does not license

**P4 revives as a descriptive ledger. It does NOT revive as a composite input.**

- As a **scored input at weight 0.10** (spec §896): 46% / 32% coverage is disqualifying. Half
  the names would carry a hole in the composite, so composites stop being comparable across
  names — and the composite has already been measured not to pay. Adding a half-covered input
  to it is negative work.
- As a **card block** with filing citation and trend: partial coverage is what the spec already
  designed for. §964 requires an absent share to render `na`, never 0, because "a zero would
  read as no concentration risk, which is a fabricated fact." 184 names with six-plus quarters
  of segment share is a real ledger under exactly that rule.

## Limits, stated

1. **"Multi-year" overstates what exists.** The trend-length distribution clusters at 6–8
   quarters, because UW's `rev_breakdown` history is shallow for most names; only ~20 tickers
   reach 15–20 periods. What ships is **~2 years of quarters** for the bulk.
2. **Counts carry ±few of network noise.** A failed fetch is indistinguishable from no rows in
   this probe; between two runs `no_rows` moved 25 → 24 and geography 125 → 128.
3. **The subset path is unproven at scale.** NVDA and AVGO were hand-verified; the other 14%
   of `subset:*` resolutions were not. A wrong-level partition yields a plausible share, and a
   plausible number is indistinguishable from a right one — so before any of this ships, the
   subset path needs either a hand-audit sample or a rule that refuses it outright (which would
   cost roughly 14% of coverage and is the conservative option).
4. **A degenerate case was found in this probe's own first run** and is now refused: 271 of
   1920 segment "partitions" had a single member, making the share 100% by construction. Those
   measured the disclosure, not the concentration. The headline numbers above are post-fix.
5. **Annual and quarterly totals are still mixed, and this fix does not address it.**
   The prior probe flagged that `rev_breakdown` alternates a 10-K annual figure among 10-Q
   quarterlies with no `formtype` on the row (NVDA: 46.7 / 57.0 / **158.9** / 81.6e9). That is
   unchanged and it is not rare: **89 of 184** segment trend-bearing tickers and **52 of 128**
   geography ones carry a total exceeding 2.5× their own median.

   It is milder than the prior memory claimed ("kills the multi-year trend"), because a *share*
   is scale-free and both numerator and denominator come from the same filing — NVDA's annual
   share 0.8904 sits squarely among its quarterly neighbours 0.8842 / 0.8930 / 0.9134. But it
   is not benign: measured across 110 annual points, the gap between the annual share and the
   ticker's own quarterly median is **median 2.5pp, p75 8.9pp, p90 17.5pp, max 56pp**, and
   **35.5% exceed 5pp**. One point in ten would put a 17-point spike on the trend chart for a
   basis change rather than a business change.

   **Requirement, not a caveat:** annual rows must be detected (a total >2.5× the ticker's own
   median separates them cleanly) and either dropped or labelled before any trend renders.

6. **Geography's members are not a clean country list.** Filers mix `country:US` with custom
   members like `nvda:ChinaIncludingHongKongMember` and continent aggregates. The share is
   defensible; the *label* needs the raw member string shown, not a prettified country name.

## Decision rule, and the fact that it did not fit

Registered before the run: ≥60% both → ship as designed; one family ≥60% → ship that family
only; both <40% → stays dead. The result (45.9% / 31.9%) fell in the gap between branches two
and three. Recording that rather than picking the favourable branch after the fact: the rule
was underspecified, and the call above is a judgement made on the split between *descriptive*
and *scored* use, which the rule never distinguished.
