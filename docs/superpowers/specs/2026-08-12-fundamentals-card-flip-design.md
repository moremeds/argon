# Fundamentals Card Flip — Design

**Status:** approved 2026-08-12, not yet implemented.

Two changes to the per-ticker Fundamentals tab: an eighth card that balances the
grid, and a click-to-flip back side that shows each feature's raw quarterly
components alongside the ratio derived from them.

Reference the user gave for the shape of the thing:
`https://unusualwhales.com/stock/NVDA/financials#free-cash-flow`.

## 1. Purpose and boundary

The seven subscore tiles state a ratio and a trajectory. They do not show the
figures the ratio came from, so a reader cannot tell whether a falling gross
margin is falling revenue, rising cost, or both. This adds that layer.

**In scope:** a new read-only statements endpoint, one new descriptive card, a
flip interaction, a hand-rolled SVG bar chart, and the per-feature map from a
card to its own components.

**Out of scope, deliberately:**

- No change to the composite, the seven scored features, or any method version.
  An eighth *scored* feature would re-open the 2026-08-12 validation, whose
  verdicts (zero gross alpha at every slice; the −0.0047 / t −0.41 quality null)
  were measured on exactly seven. The eighth card is descriptive and enters no
  score.
- No annual periods. Only `period_type = 'quarterly'` exists in
  `fundamental_statement_obs`; see §4.
- No new ingest. The endpoint reads rows already present.
- No forecast, target, or scenario grid.

## 2. The eighth card — "Revenue & earnings"

A descriptive tile appended after the seven subscores, making the grid 8.

Renders trailing-twelve-month revenue as the headline value, with TTM net income
and TTM free cash flow beneath it and a mini bar series. It carries **no
percentile chip** and its footer reads `descriptive · not scored` where a
subscore tile reads `higher better` or `no direction claimed`.

**TTM here is not the annual aggregation §4 rejects.** All three are flow items
summed over the last four quarters, which is valid regardless of where the
fiscal year falls. What §4 rules out is (a) summing *balance-sheet* items, which
are point-in-time, and (b) grouping into labelled fiscal years, which needs the
filer's own year-end. TTM does neither. The label states the four periods it
covers, and the value is suppressed when fewer than four are available rather
than silently annualizing a shorter span.

That visual difference is load-bearing, not styling. Every other tile in that
grid is a member of a scored, validated set; a tile that looks identical would
be read as an eighth feature, and the composite's measured claims do not cover
it.

Grid stays `repeat(auto-fit, minmax(260px, 1fr))`. With 8 tiles the common
desktop widths resolve to 4×2 or 2×4 with no ragged row, which is the original
complaint.

## 3. Flip interaction

**Trigger.** The tile becomes a real `<button>` — click, Enter and Space all
flip it. Escape closes. An explicit close control renders on the back.

**Expansion, not a same-size rotation.** The back holds 20 quarterly bars plus a
ratio line and cannot be read at 260px. On flip the card expands to span the
full grid row (`grid-column: 1 / -1`) and the back renders inside that width.
The other tiles reflow around it. One card is open at a time.

**Motion.** A CSS `rotateY` transition on the expanded container. Under
`prefers-reduced-motion: reduce` the rotation is dropped and the back swaps in
directly — the state change must not depend on the animation.

## 4. Period grain: 20 quarters, no derived annuals

`fundamental_statement_obs` stores `period_type = 'quarterly'` and nothing else
(verified 2026-08-12: 20,707 balance / 20,704 cash_flow / 20,723 income rows, all
quarterly). "Five years" is therefore drawn as **20 quarterly bars**, each one a
stored row.

Annual bars were considered and rejected for v1. They require summing four
*fiscal* quarters, which is valid for flow items (revenue, net income, cash
flow) and **invalid for balance-sheet items**, which are point-in-time and would
have to take the year-end value instead. NVDA's fiscal year ends 31 January, so
calendar grouping is also wrong, and the current fiscal year is partial and
would need excluding or labelling TTM. Three chances to be quietly wrong, for a
cosmetic gain. Quarterly bars need none of that: every bar is a row.

Seasonality is a side benefit — it is real information that annual bars destroy.

## 5. Per-feature component map

Each back renders that feature's own components as bars and its derived ratio as
a line.

**The map is derived from `fundamentals/features.py::build_features`, which is
the authoritative definition of every ratio.** An earlier draft of this spec
listed plausible-looking fields chosen by hand and disagreed with that function
in four places: it used `cash_and_short_term_investments` where the ratio uses
`cash_and_cash_equivalents`; it charted `cost_of_revenue` where the numerator is
`gross_profit`; it listed R&D and SG&A as inputs to `op_margin`, which they are
not; and it ignored that **each feature has its own TTM-vs-quarterly basis**.

Any of those would have produced a back whose line does not equal its own
bars — the exact "correctly computed and useless" failure this feature keeps
finding. The requirement is therefore stated as an invariant, not a table:

> **For every feature, the plotted line must equal the plotted input bars
> combined by the feature's own formula, period for period.** A test asserts
> this per feature against a real fixture.

### 5.1 Basis and components, as `build_features` computes them

`_ttm(key)` sums four consecutive quarters and yields `None` unless all four are
present. Point-in-time (PIT) values are the quarter's own balance-sheet row.

**Series keys carry their basis.** A key is the raw field name when the series is
per-quarter and `<field>_ttm` when it is a four-quarter sum. This is mechanical,
not cosmetic: `total_revenue` is quarterly under `gross_margin` and TTM under
`asset_turnover` — figures differing by roughly 4× — so one key meaning both
would be mislabelled data, and any consumer joining on it would be silently
wrong. Two derived series have no single source field and are named directly:
`rev_ttm_prev` and `fcf_ttm`.

| Card | Basis | Input component keys | Line |
|---|---|---|---|
| `rev_growth` | TTM | `total_revenue_ttm`, `rev_ttm_prev` (TTM ending 4q earlier) | `rev_ttm / rev_ttm_prev − 1` |
| `gross_margin` | **quarterly** | `gross_profit`, `total_revenue` | `gp / rev_q` |
| `op_margin` | **quarterly** | `operating_income`, `total_revenue` | `oi / rev_q` |
| `fcf_margin` | TTM | `operating_cashflow_ttm`, `capital_expenditures_ttm`, `total_revenue_ttm` | `(ocf − abs(capex)) / rev` |
| `roe` | TTM num, PIT den | `net_income_ttm`, `total_shareholder_equity` | `ni_ttm / equity` |
| `neg_net_debt_ebitda` | PIT + TTM | `short_long_term_debt_total`, `cash_and_cash_equivalents`, `ebitda_ttm` | `−((debt − cash) / ebitda_ttm)` |
| `asset_turnover` | TTM num, PIT den | `total_revenue_ttm`, `total_assets` | `rev_ttm / assets` |
| Revenue & earnings *(new)* | TTM | `total_revenue_ttm`, `net_income_ttm`, `fcf_ttm` | — |

`rev_growth` needs **eight** quarters before it yields a single value: it
compares a four-quarter window against the window ending four quarters earlier.
Any fixture or ticker with fewer produces all-null for that feature, which is
correct behaviour and must not be mistaken for a bug — or, in a test, for a
passing assertion.

Two of these mix bases within one ratio (`roe`, `asset_turnover`) and two are
quarterly where their neighbours are TTM (`gross_margin`, `op_margin`). **Each
back states its own basis in the chart subtitle** — "TTM" or "quarterly" — because
a reader comparing a quarterly margin against a TTM turnover without being told
is being misled by the layout.

### 5.2 Context series

Fields that are informative but are *not* inputs to the ratio — R&D and SG&A on
`op_margin`, `cost_of_revenue` on `gross_margin` — render as clearly separated
context: dimmer fill, own legend entry, labelled `context`. One mechanism, a
`role: "input" | "context"` flag per series, with no per-feature special-casing
in the chart.

They are excluded from the reconciliation invariant in §5, by construction —
only `role: "input"` series participate.

### 5.1 The ratio line inherits the front's direction rule

`gross_margin`, `op_margin` and `roe` carry `direction: null` in
`FundamentalSubscore` on purpose: the first two measured **inverted** and the
third is named by no rubric row. Their lines render in a neutral stroke with no
up-is-good encoding — no green, no arrow, no ordering that implies better.

The front already enforces this. The back must not undo it, and a test asserts
it rather than trusting the convention.

## 6. API surface

New endpoint on the read-only stock router:

```
GET /stock/{ticker}/fundamentals/statements?quarters=20
```

`quarters` defaults to 20 and is bounded to `1..40` — 40 is the span the card
endpoint already serves, and an unbounded parameter on a table with 83 periods
per ticker is a needless way to hand a caller a large response.

Fetched once on mount, alongside the card. A separate endpoint rather than
fattening `FundamentalCardResponse`, so the existing card's contract and its
OpenAPI snapshot stay untouched and the two payloads can evolve independently.

**Not deferred until first flip**, though an earlier draft said so. The eighth
card's headline is computed from this payload, so deferring it would leave that
card showing an em dash until the reader happened to open some *other* card —
blank on arrival, which is the opposite of what it is for. The payload is a few
hundred numbers for one ticker; the deferral bought nothing and cost the feature
its default state.

**The endpoint returns computed components, not raw statement fields.** The
server resolves each feature's inputs; the client plots what it is given and
performs no ratio math. If the UI re-derived the ratios it would hold a second
copy of `build_features`, and the two would drift — at which point the back
silently contradicts the front.

**Models** (`models/fundamentals.py`):

- `FundamentalComponentSeries` — `key` (e.g. `total_revenue_ttm`), `label`, `role`
  (`"input" | "context"`), `unit` (`"currency" | "ratio" | "turns"`),
  `values: list[float | None]`.
- `FundamentalFeatureDetail` — `feature`, `basis` (`"ttm" | "quarterly" | "mixed"`),
  `series: list[FundamentalComponentSeries]`, `ratio: list[float | None]`.
- `FundamentalStatementsResponse` — `ticker`, `period_ends: list[str]` (oldest
  first, matching every other series on the card), `reported_currency`,
  `features: list[FundamentalFeatureDetail]`.

**Compute** — a new `build_feature_details(uw, quarters)` in
`fundamentals/features.py`, beside `build_features` and sharing its `_f` and
`_ttm` helpers. Same module, same helpers, same file: that adjacency is what
keeps the two definitions from drifting, and a test asserts the detail's `ratio`
equals `build_features`' value for the same period.

**Storage** — **no new method.** `FundamentalObsRepository.statement_panel(
tickers=[t])` already returns the pivoted `{income-statements, balance-sheets,
cash-flows, filing_dates, obs_ids}` shape this needs, and is already the input
`build_features` consumes.

### 6.1 Restatements are already handled — and must stay consistent

`statement_panel` selects `DISTINCT ON (ticker, period_end, statement) ... ORDER
BY obs_id DESC`. Because the unique key includes `content_hash`, a restatement
inserts an *additional* immutable row, so the highest `obs_id` is the current
figure and is never an edit to an older one.

An earlier draft of this spec proposed a *different* rule for the new read —
`filing_published_at DESC NULLS LAST`. That would have been actively wrong here:
only 56% of rows carry a real filing date, so `NULLS LAST` can rank an older
dated row above a newer undated one, and more importantly **the scoring path uses
`obs_id DESC`**. A back side that resolved "current" differently from the front
would draw bars belonging to a filing the headline value never saw.

Reusing `statement_panel` makes that class of divergence unrepresentable rather
than merely tested for.

### 6.2 Currency is per-row and must be rendered

`reported_currency` sits in every payload. TSM files in TWD against a USD ADR
quote. Every back labels its currency explicitly.

This is not a nicety: the same unlabelled-unit failure produced TSM's negative
enterprise value and five plausible-looking price levels earlier in this project.
A TWD bar chart with a `$` axis is that bug with a different surface.

## 7. Charts

New `web/components/stock/panels/FundamentalBarChart.tsx`, hand-rolled SVG using
`lib/svgChart.ts` (`linearScale`, `finiteDomain`, `pathFromPoints`).

Not `lightweight-charts`. That library has exactly two documented exceptions in
this repo (the Technicals price pane and the SPX density cone) and neither
covers a static bar series; extending it further needs its own spec.

Grouped bars share one value axis; the ratio line gets its own right-hand axis.
`role="img"` and a `<title>` per the components convention. Missing quarters
render as a gap, never interpolated — matching how `FundamentalSparkline`
already treats a `null` in a series.

## 8. Testing

**vitest**

- each feature's back renders its own mapped fields and no others
- the three `direction: null` features get a neutral line — asserted, not assumed
- the currency label renders, and renders TWD for a TWD fixture
- flip opens and closes via click, Enter, Space and Escape
- `prefers-reduced-motion` still changes state
- the eighth card renders no percentile chip

**pytest (unit, `tests/unit/fundamentals/`)**

- **the reconciliation invariant of §5**, per feature: the returned `ratio`
  equals its `role: "input"` series combined by that feature's formula
- `build_feature_details`' `ratio` equals `build_features`' value for the same
  ticker and period — the two definitions cannot drift apart silently
- a feature whose inputs are incomplete yields `None` in `ratio`, not 0
- `_ttm`-based series are `None` for the first three periods, matching
  `build_features`

**integration (pytest-postgresql)**

- the endpoint returns 404 for a ticker with **no ingested statements**
- a period with a restated row returns the highest-`obs_id` figure — asserted at
  the endpoint, since `statement_panel` is now the shared path

That 404 condition is deliberately **not** the card endpoint's. The card 404s on
"no score row"; this one 404s on "no statements". They can disagree — a name can
have ingested statements and no score yet, or a score under a retired engine —
and in that case the honest answer is to serve the statements we hold rather than
to withhold data because a different table lags. An earlier draft claimed the two
contracts matched; they don't, and pretending otherwise would have meant adding a
universe check whose only effect is hiding real figures.

**Playwright**

- click a subscore tile on `/stock/NVDA/fundamentals`, assert the back's bars are
  on screen and the front's value is not

Fixtures use real frozen figures from `fundamental_statement_obs` (NVDA
2026-04-30: `total_revenue` 81,615,000,000 / `net_income` 58,321,000,000), per
the no-synthetic-data rule.

## 9. Branch strategy

This work depends on the Fundamentals tab, which lives on
`feat/fundamental-tier1-ingest` (PR #331) and is **not yet on main**.

PR #331 is therefore a genuine prerequisite in the sense the global rule allows:
an independent change that must merge first. The order is merge #331, then branch
from main. Branching from #331's head before it merges would stack a second PR on
an unmerged one and make both harder to review.

## 10. Open items

None blocking. Deferred by choice:

- annual / quarterly toggle (§4) — revisit once the quarterly view is proven
- segment or geography breakdown on the revenue back — blocked upstream, see
  `docs/research/2026-08-12-fundamental-segment-computability/VERDICT.md`
  (8 of 25 names have computable segment revenue, 0 of 25 geography)
