# VERDICT — the concentration ledger is blocked on data structure, not on access

*2026-08-12 · numbers in `computability.json` · reproduce:*

```bash
uv run python scripts/research/fundamental_segment_computability_probe.py
```

25 core tickers · UW `GET /api/stock/{ticker}/fundamental-breakdown` · latest
reported period per name.

## The headline

**Geography: 0 of 25. Segment: 8 of 25.** The spec's `concentration_risk`
(§6, weight 0.10) asks for "largest reported segment share of revenue + largest
single-country share". Neither half is computable for most of the cohort, and the
geographic half is computable for none of it.

| | computable | leaves overlap the total | two axes, two answers | no leaf rows | no rows / absent |
|---|---:|---:|---:|---:|---:|
| segment (`product`) | **8** | 10 | 3 | 2 | 2 |
| geography (`country`/`continent`) | **0** | — | — | — | 25 lack a total |

## Why the availability probe said yes and this says no

§896 marks the feature ✅ on "UW `rev_breakdown`, 24/25 — TSM is the sole `na`".
That probe asked *do rows come back*. They do. It did not ask whether a share can
be derived from them, and that is where it fails.

`rev_breakdown` is **one flat list per ticker** holding several disaggregations of
the same revenue along different XBRL axes, an untagged consolidated total, and
on some names cross-products of two axes at once. No row carries its level, so
nothing distinguishes a parent from its children.

**NVDA, 2026-04-26, `rev_group='product'`, all on `srt:ProductOrServiceAxis`:**

```
DataCenter                    75.25e9
Hyperscale                    37.87e9   \  37.87 + 37.38 = 75.25
AICloudsIndustrialEnterprise  37.38e9   /  — these ARE DataCenter
EdgeComputing                  6.37e9
                     total    81.62e9   (untagged row)
```

Summing the members gives 156.9e9 against a total of 81.6e9. "Largest segment
share" is 92% or 46% depending on which nesting depth you happen to keep, and
both render identically on a card.

**AVGO, 2026-05-03** — two axes each sum to the total *correctly*, and disagree:
`ProductOrServiceAxis` says Product 76%, `StatementBusinessSegmentsAxis` says
SemiconductorSolutions 68%. Neither is more "the" segment share. Three names sit
here.

**Geography fails earlier, for a duller reason:** 23 of 25 have no untagged total
inside the `country`/`continent` group, so there is no denominator. Where rows do
exist they are frequently not countries — MSFT reports a US / non-US pair, leaving
48% of revenue unallocated, and AVGO files `srt:AmericasMember` (a continent)
under `rev_group='country'` alongside cross-tab cells
`['Subscriptions','Americas']` and `['Product','Americas']` that sum to it.

**Secondary finding — the basis alternates by filing form.** NVDA's untagged
totals run 46.7e9 / 57.0e9 / **158.9e9** / 81.6e9 across consecutive
`report_date`s: the third is the 10-K's annual figure among 10-Q quarterlies. The
rows carry no `formtype`. A within-period share is unaffected (both legs come
from the same filing) but a multi-year TREND of shares silently splices annual
and quarterly points, which is the other half of what §6 asks for.

## What was NOT built, and why not

No table, no fetcher, no ingest job, no card block. Building the ingest is easy —
one migration and ~150 lines — and it would have produced a
correctly-typed, confidently-rendered, wrong number for 17 of 25 names with
nothing on screen to say which 17.

That is the same failure this branch has now hit four times: ASML's unreachable
band, TSM's currency-mixed enterprise value, JPM's band with no bottom, and the
anchor hash that silently kept a wrong row. Every one of them was arithmetically
correct output. **The pattern is that a plausible number is indistinguishable
from a right one, so the guard has to exist before the feature does.**

There is also no accrual pressure. Unlike `option_surface_grid_daily`, this data
is filing-derived and reaches back to 2020 — nothing is lost by not capturing it
tonight.

## What would unblock it

The probe's own test is the design. For each `(ticker, period, rev_group, axis)`:
take the rows with exactly one member on exactly that axis, and require their sum
to match the untagged consolidated total within tolerance. That is the same
two-independent-derivations cross-check that caught the TSM currency bug, and it
self-refuses instead of guessing.

On that rule the honest product is a ledger that covers **8 names on segment and
none on geography**, with the other 17 stating why. Whether a 10-name block earns
its place on the card is a product call, not a data one.

Widening it needs one of:

1. **XBRL dimension hierarchy** — SEC's presentation linkbase says Hyperscale is
   a child of DataCenter. The spec already contemplates an SEC XBRL leg (§A4) for
   the statement gap-fill; this would extend it. Resolves the 10 overlap failures
   and makes the 3 ambiguous ones a labelled choice rather than a coin flip.
2. **A per-ticker axis pin** — a small curated table naming which axis is the
   reportable segmentation for each name, the same shape as
   `fundamental_company_type`. Cheap, hand-maintained, and honest as long as the
   sum check still gates it.

Geography needs the denominator question answered first: either UW starts
returning a group total, or the share is taken against income-statement revenue
for the matching period, which then needs its own completeness gate for the
MSFT-style partial splits.

## Limits of this probe

Latest reported period only, one snapshot per name. A name that fails today may
have filed a clean breakdown in an earlier period, so 8/25 is a floor for
"ever computable", not a ceiling. It is the right number for a card that shows
the current concentration, which is what §6 specifies.
