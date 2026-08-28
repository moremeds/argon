# Macro Desk — porting the designed board onto `/macro`

**Status:** DRAFT — awaiting operator sign-off on §10
**Date:** 2026-08-27
**Spec (binding):** the macro desk board artifact —
`https://claude.ai/code/artifact/dde15f29-728e-43e9-86d5-9ab688df4853`, frozen into this repo at
`docs/superpowers/specs/2026-08-27-macro-desk-board.html` (sha256 `b98a32de3041a348…`, 9 tab
sections `#t0`–`#t8`, 58 panels, every value REAL from the mini). The board is the spec for both
the **information** (which panels exist and what each answers) and the **design** (tokens,
layout, copy). **Where this plan and the board disagree, the board wins** — the first revision of
this plan never cited the artifact at all, which is how the divergence in §1 got through.
**Phase 1 closure:** `project_macro_phase1_closed` — MC5/MC6 killed; the engine stays descriptive.

---

## 1. Goal

Collapse `/rates`, `/macro` and `/gold` into one **Macro Analysis** desk at `/macro`,
organised as 9 sub-tabs following the chain **Fed → inflation expectations → USD →
gold**, with energy proposed but not built.

Non-goals, restated so they cannot drift:

- **No composite.** Four domains publish independently; averaging them is
  test-forbidden and hides the contradictions the desk exists to show.
- **Macro never derives equity.** Equity _consumes_ macro factors
  (`project_macro_phase2_equity_consumes_factors`); the arrow is equity → reads →
  factor, never the reverse.
- **The SPX `vrp_macro_signal` card is not part of this desk** — its "macro" means
  index-level vol. It stays on `/regime`.
- **The board binds, and it binds per tab.** _Superseded 2026-08-28: "No new analytics. Tabs
  00–05 are a presentation merge."_ That line is what turned the board's four inflation panels
  and two dollar panels into one generic state card each. The conformance audit
  (`docs/research/2026-08-28-macro-desk-board-conformance/`) measured which half of it was ever
  true: tabs **01 / 02 / 05 are a presentation merge** (their panels were already built), tabs
  **00 / 03 / 04 are a build** (0 of 6 board panels reached 03/04; 8 of 16 reached 00). What
  survives is the narrow sense only — **no new engine and no new derived quantity**: every
  number a board panel prints must already be extractable from a shipped endpoint, and a panel
  that would need a new one is deferred with its reason, never invented.
- **Every panel answers a board question.** The board's own acceptance test binds: _"The seven
  questions are the acceptance test: every panel must answer at least one, or it gets deleted."_
  A panel names its Q1–Q7 in its own source; one that names none is a deletion candidate. (The
  board's Q→panel table numbers tabs 00–04, one short of its own nine sections — re-read the
  artifact before treating a number inside it as a tab id.)
- **Tab 08 does not ship.** The board's t8 says so in its first line: _"This tab is for you (the
  operator) and does not ship on the final page."_ It is currently in the live tab bar.

---

## 2. The headline finding: this is mostly a move, not a build

**CORRECTION (2026-08-28, after the conformance audit): this heading held for the source pages
and was read as holding for the board.** It does not. Measured against the board, 26 of 47
panels on tabs t0–t5 are present, 6 partial, 15 absent or misplaced — and the absences are not
spread evenly, they are concentrated in exactly the tabs §3 bound to a single endpoint. §2's own
closing paragraph already said the panel count was not move-dominated; the audit is the number
behind it. Read this section as an inventory of what need not be rebuilt, never as a size
estimate for the remaining work.

All eight panels the board describes as "carried and built" **already exist as argon
components**. The board re-presented them; it did not invent them.

| Board panel                         | Existing argon component                                 | L   |
| ----------------------------------- | -------------------------------------------------------- | --- |
| SEP dot plot                        | `web/components/rates/SepDotPlot.tsx`                    | 296 |
| Dealer expectations                 | `web/components/rates/DealerPathChart.tsx`               | 334 |
| Par yield curve                     | `web/components/rates/RatesCurveChart.tsx`               | 233 |
| Cleveland 5-term + move attribution | `web/components/rates/sections/DecompositionSection.tsx` | 548 |
| Fed plumbing                        | `web/components/rates/sections/PolicySection.tsx`        | 104 |
| Auction demand                      | `web/components/rates/sections/SupplySection.tsx`        | 109 |
| Gold input manifest                 | `web/components/gold/DataAuditFooter.tsx`                | 94  |
| Four policy paths                   | `web/components/rates/PolicyPathComparison.tsx`          | 431 |

`SepDotPlot.tsx` already carries a **prior-median rule** — one dashed line per horizon
at the previous release's median (`SepDotPlot.tsx:224-241`, `data-testid="sep-prior-median"`),
with the move in bps in its `<title>`. It is **not** an overlay of the prior release's
dot distribution; only the median crosses over. The central-tendency band is a real
`<rect className={styles.sepBand}>` at `:191-196`; `.sepBandSwatch`
(`RatesDesk.module.css:1700-1706`) is the 16×12 **legend swatch**, not band geometry.
**The dot chart on argon was never oversized** — only the board's redraw of it was (§5).

Genuinely new work, with no existing component:

- tab 00's daily loop, contradiction feed, cross-domain contradictions, transmission health
- a **shared** confidence-arithmetic strip (today `ConfidenceStrip` is private to
  `rates/sections/StateSection.tsx:77`)
- tab 07 factor vector; tab 06 energy proposal; the refusal cards

Existing inventory (recounted 2026-08-27, after this session's gold deletions):
`components/rates/` 5 333 L (17 files) · `components/gold/` **2 067 L (34 files)** ·
`components/macro/` 469 L (4 files, zero client components).

### The eight are two populations, not one

§7 treats "reusable" as a single property. It is not, and the split is what makes §7's
component-home decision consequential:

| Population                                      | Components                                                                  | Shaped by                                              |
| ----------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------ |
| **Portable** — take a `PolicyPathSlot`          | `SepDotPlot`, `DealerPathChart`, `PolicyPathComparison`                     | `/api/macro/policy`, which every tab can call          |
| **Rates-shaped** — take `RatesSnapshotResponse` | `RatesCurveChart`, `DecompositionSection`, `PolicySection`, `SupplySection` | `components/rates/types.ts` over `/api/rates/snapshot` |
| **Neither** — gold                              | `DataAuditFooter`                                                           | `@/lib/types` directly; no rates coupling              |

And **all seven rates components import `RatesDesk.module.css`** (`:1`–`:3` in each).
So today "reusable" means "reusable inside the rates CSS Module." A tab that wants
`SepDotPlot` without `RatesDesk.module.css` does not exist yet. See §7.

### The claim, stated honestly

"Mostly a move" is true of the **source pages**, not of the **board**, and the two have
different denominators:

- Of the **39 panels on `/rates` + `/macro` + `/gold`**, ~28 carry over (8 built · 5
  available · 15 covered). Against that denominator the merge really is deduplication.
- Of the **58 panels on the board**, roughly half are new — tab 00 entirely, tab 06,
  tab 07, and tab 08's ten notes panels.

The new panels are cheap per unit (tab 08 is static prose, tabs 06/07 are proposals
with no data path) while the reused ones are expensive per unit (`DecompositionSection`
alone is 548 L). So the _effort_ is move-dominated even though the _panel count_ is not.
Do not read §2 as "half the work is already done" — read it as "no chart needs to be
designed twice."

---

## 3. Tab → endpoint binding (verified against production 2026-08-27)

Verified by direct call to the mini, not recall. Every tab that binds anything needs
**1–3 requests, except tab 00, which needs 5** — the snapshot plus all four domain
states. Tab 00 is the outlier by construction: it is the only tab whose subject is the
other tabs.

| Tab                      | Route              | Requests                                                         |
| ------------------------ | ------------------ | ---------------------------------------------------------------- |
| 00 Overview · Daily Loop | `/macro/overview`  | `/api/macro/snapshot` + 4× `/api/macro/{domain}`                 |
| 01 Fed · Policy          | `/macro/fed`       | `/api/macro/policy` + `/api/macro/rates` + `/api/rates/snapshot` |
| 02 Rates · Curve         | `/macro/rates`     | `/api/rates/snapshot` + `/api/macro/rates`                       |
| 03 Inflation             | `/macro/inflation` | `/api/macro/inflation`                                           |
| 04 US Dollar             | `/macro/usd`       | `/api/macro/usd`                                                 |
| 05 Gold                  | `/macro/gold`      | `/api/gold/state` + `/api/macro/gold`                            |
| 06 Energy · Proposal     | `/macro/energy`    | none — proposal only, no fabricated data                         |
| 07 Factor Export         | `/macro/factors`   | none yet — `/api/macro/factors` does not exist (P7)              |
| 08 Design Notes          | `/macro/notes`     | none                                                             |

**CORRECTION, made while executing P3 (2026-08-28): the `/api/macro/rates` column above is
wrong for tabs 01 and 02, and neither tab calls it.** `/rates` never called it either. The
`MacroStateSummary` that `StateSection` renders is the `state` field on
`RatesSnapshotResponse`, and `routers/rates.py:63-72` attaches it **at read time** by
calling `fetch_macro_domain_state_as_of("policy_rates", at)` — the same repository read, at
the same instant `resolve_instant` already resolved, that `/api/macro/rates` performs. So
the second request would fetch the same row twice per page view and open a window in which
the two answers disagree. `models/rates.py:253-258` states the reason the field is not
persisted into the stored snapshot, and it is the same reason one level down: _"copying it
here would fork one answer into two records that could disagree."_ Tab 01 makes **two**
requests (`/api/rates/snapshot` + `/api/macro/policy`) and tab 02 makes **one**. A later
tab that genuinely needs the domain state standalone should read `snapshot.state`, not add
the call.

**`/api/macro/policy` returns all four policy paths in one call** — verified in prod: all
four paths present, each with 2 prior vintages; SEP `participant_distribution` as
`(rate_percent, participant_count)` totalling 18 for 2026; dealer `p25/median/p75`
with `respondent_count: 26`. IQR bands are server-side; no client math.

**It is not the whole Fed tab, and the table above is the binding to trust.** Tab 01 also
carries Fed plumbing and auction demand, which are `RatesSnapshotResponse` fields
(`PolicySection`, `SupplySection` — the rates-shaped population in §2), and the
policy-rates state itself, which is `/api/macro/rates`. Three requests, not one.

### The one-endpoint bindings for 03/04 were right — §1 alone caused the divergence

Measured 2026-08-28 against a running instance: the single response each of tabs 03 and 04
already fetches **carries every board panel for that tab**. Nothing is missing from the API;
what was missing was permission to render it. Field-level map, so the build adds no endpoint:

| Board panel                             | Field on the response already fetched                                                         |
| --------------------------------------- | --------------------------------------------------------------------------------------------- |
| t3 · arithmetic of confidence           | `confidence_reasons[]` — 3 `multiplicand` + 2 `penalty` terms, each with a `detail` string    |
| t3 · realized inflation                 | `factors[]` where `causal_role='realized'` (PCEPILFE et al., with `change_over_window`)       |
| t3 · inflation expectations             | `factors[]` where `causal_role='expectations_survey'`                                         |
| t3 · falsifier window / repair table    | `contradictions[]` (`rule` + `detail`) over `evidence[]` (139 rows, each with `available_at`) |
| t4 · nominal vs real, a pair in reverse | `factors[]` = `broad_dollar` (DTWEXBGS) **and** `broad_dollar_real` (RTWEXBGS)                |
| t4 · upstream citation, chain integrity | `upstream[]` + the `upstream_policy_rates` `informational` term in `confidence_reasons[]`     |

Two traps this map carries with it:

- **The confidence arithmetic must be computed from the terms, never restated from the board.**
  The board's heading reads "why only 0.37"; the live inflation state answers 0.4177, which the
  terms reproduce exactly (1.0 × 0.5968 × 1.0, then the 0.3 contradiction penalty). The board's
  numbers are frozen at its capture instant — bind to the field, never to the board's value.
- **`notes[]` is authored copy, not a footnote.** USD's note — _"the dollar is measured against
  the Fed's H.10 nominal broad index; the real index is reported beside it and is never
  substituted for it"_ — is the nominal/real panel's own rule, written by the engine that
  produced the pair. Render it with the panel.

Engine versions differ between the local dev DB (`inflation/1`, `usd/1`) and the versions the
board names (`inflation/2 · rates/2 · usd/3 · gold/2`). Verify against the mini before binding
anything to a version string — a local-DB reading is not evidence about production.

### 3.1 Point-in-time replay

`as_of` / `as_of_ts` is accepted by **every** `/api/macro/*` route (`routers/macro.py`
`:30/:34`, `:48/:52`, `:62/:66`, `:76/:80`, `:90/:94`, `:121/:125`), all six resolving
through the shared `resolve_instant` (`routers/macro.py:272-294`).

**`/api/rates/snapshot` now accepts them too** — shipped as P1 on this branch.
`rates_snapshot` takes `as_of: date | None` and `as_of_ts: datetime | None`
(`routers/rates.py:30-36`) through the _same_ `resolve_instant`, imported rather than
re-implemented (`routers/rates.py:10`), and `fetch_latest_rates_snapshot`
(`storage/rates_repository.py:186-221`) gained a `WHERE computed_at <= %s` predicate.
The live path is byte-identical to the shipped query: the router passes `None` unless a
date was actually asked for (`routers/rates.py:51`), so a snapshot whose `computed_at`
sits a second in the future cannot 404 the page. `_mark_stale_snapshot_sources` was
re-pointed from the wall clock to the requested instant (`routers/rates.py:86-97`) —
aged against `now`, every historical replay would have force-marked every source stale
and appended a scheduler-failure risk to every past date on the desk.

> A replayed tab 01/03/04/05 beside a **live** tab 02, with nothing on screen saying
> so, is the worst failure mode a point-in-time desk has. P1 fixed it at the API.
> P4 is still what makes it true on screen.

#### Three different clocks, and they are not twins

The plan's first draft called `/api/gold/replay` "the PIT twin of `/api/gold/state`."
It is not a twin of anything else on this desk. There are **three** definitions of
"as of" in the surfaces tab 01–05 will bind, and nothing on screen distinguishes them:

| Surface               | Keys on                                     | Where                                                                                                   |
| --------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `/api/macro/*`        | an **instant**; naive timestamps → **422**  | `resolve_instant`, `routers/macro.py:272-294`                                                           |
| `/api/rates/snapshot` | **`computed_at`** — when the answer existed | `rates_repository.py:205` (`WHERE computed_at <= %s`)                                                   |
| `/api/gold/replay`    | **`obs_date`** — the market day it is about | `routers/gold.py:503-516` → `storage/gold.py:862-880`, `WHERE obs_date = %s` (exact equality, not `<=`) |

A single desk-wide date picker over these would have tab 02 answering _"what the desk
knew at T"_ and tab 05 answering _"what the market did on day T"_, with one control
above both. That is §3.1's own worst failure mode one level down — not a live tab beside
a replayed one, but two replayed tabs replaying different things.

**In scope for P4, decide one:** either give `/api/gold/replay` `computed_at` semantics
(a second parameter, or a `<=`-on-`computed_at` variant), or label the gold tab's
control an **obs-date** and not an as-of, and say on screen that it is a different
question. Do not ship the picker over all five tabs until one of those is done.

#### TAKEN in P4 (2026-08-28): the label, per §10-H — and how the ban is discharged

`/api/gold/replay` is unchanged. The label is `MacroReplayClock`
(`web/components/macro/replay.ts`), and the discharge is that it is a **required field of
every `VALID_TABS` entry with no default and no fallback** (`components/macro/tabs.ts`).
That matters more than the copy it selects:

- `ReplayControl` renders **nothing** for `replayClock: "none"` and renders _different
  prose_ for `"instant"` and `"obs_date"` — the second says outright that it is **not** a
  point-in-time replay, that it names the market day, and that it is matched exactly. A
  unit test asserts the two texts differ and that the obs-date one does not carry the
  instant one's promise.
- Tab 05 therefore cannot join the picker by omission. There is no default to inherit, so
  P6 must _write_ `replayClock: "obs_date"` — a line a reviewer sees — and the control it
  gets is the honest one. Registering a tab with no clock does not compile.

So §3.1's ban is not discharged by "we labelled it and will remember" but by making the
unlabelled case unrepresentable. **The ban's remaining half still binds P6:** a tab whose
declared clock does not match what its endpoint actually keys on is the same failure
wearing a label, and nothing in the type system can check that — it is a review item.

**One correction to the table above, found while wiring it.** `/api/macro/policy` is listed
as keying on an instant, and it does; but the response's `as_of` field is
`as_of=as_of` — **the requested instant echoed straight back**
(`macro/policy_report.py:128`). It is not an answer clock, so it cannot drive a banner. On
tab 01 the banner is driven by `RatesSnapshotResponse.computed_at` alone, and the policy
publisher's own freshness stays where it already was: the per-lane release dates inside
`PolicyPathComparison`. A future tab that fetches only `/api/macro/*` has **no `computed_at`
anywhere in its responses** and will need `state_summary`'s own clock, not this one.

---

## 4. Blockers found while verifying

### 4.1 Confidence terms were mislabelled — **FIXED on this branch (P0)**

Kept in full as the record, because the reasoning is what the shared
`ConfidenceArithmetic` component in P5 inherits.

**The bug as found.** `market_path_is_a_shadow` was built with `value=Decimal(0)` and
no `kind`, inheriting the dataclass default `kind="multiplicand"`
(`src/uw_scan/macro/contracts.py:139`). It is not in the product:

```
inflation  1 × 0.516129 × 1.0 × (1 − 0.30) = 0.36129  = reported 0.36129  ✓
rates      1 × 1        × 1.0 × (1 − 0.15) = 0.85     = reported 0.850    ✓  ← the 0 is absent
usd        1 × 1        × 1.0 × (1 − 0.00) = 1        = reported 1        ✓
gold       1 × 1        × 1.0 × (1 − 0.15) = 0.85     = reported 0.850    ✓
```

`web/components/rates/sections/StateSection.tsx:80-85` sorts the terms: `penalty`
with `value > 0` and `multiplicand` with `value < 1` go to the **"Reduced by"** strip
(`:90-102`), `informational` goes to the notes (`:86`, rendered `:109-114`). So the
live page rendered `market path is a shadow ×0.00` beside a confidence of 0.850.

**The fix was not one keyword — a second term had the identical defect.**
`policy_paths_absent` in the same file carries `Decimal(len(missing))` — a **COUNT** of
absent policy paths — and also inherited `multiplicand`. It never reached the "Reduced
by" strip only because its value is always ≥ 1, so it failed the `< 1` filter; and it
was not `informational`, so it failed the notes filter too. It rendered in **neither
list**. The visible bug and the invisible one were the same bug, and fixing only the
one an operator could see would have left a count mislabelled as a multiplier in the
component every domain is about to share.

Both are now `kind="informational"`, with the reasoning recorded at the site:
`rates.py:532` (`policy_paths_absent`) and `rates.py:549` (`market_path_is_a_shadow`).
`market_factors_absent` (`rates.py:586`) was already correct and is the shape the other
two now match.

**Scope of the class.** There are **25 `ConfidenceTerm(` construction sites across 6
files** — `macro/{rates,rates_sub_states,usd,gold_state,confidence}.py` and
`storage/macro_domain_state.py` — and `contracts.py:139` defaults **every one** of them
to `"multiplicand"`. The default is the defect surface; the audit is invariant 10 (§9).

**Test.** `tests/unit/macro/test_confidence_term_kinds.py` (+ `conftest.py`) pins both
shapes on a real state from each of the four engines: a reconciliation test that refolds
the terms using **`kind` alone** and requires the reported `confidence` back
(`:57-71`), and a range test that requires anything not `informational` to be a fraction
in [0, 1] (`:74-93`). The refold is deliberately blind to term _names_ — a test that
special-cased `market_path_is_a_shadow` by string would have passed straight through the
bug it exists to catch. `contracts.py:125-134` documents that `kind` exists precisely so
consumers need not string-match; the test holds the producer to it.

### 4.2 Never build a panel on these — permanently empty in current code

Hardcoded at the source; identical on every request. **Citations re-verified
2026-08-27** — every gold line below shifted when the producing sites were annotated
during the §10-E work, so an earlier copy of this table points at the wrong lines.

| Field                                      | Source                                 | Note                                                                              |
| ------------------------------------------ | -------------------------------------- | --------------------------------------------------------------------------------- |
| `rates.events[]`                           | `rates/snapshot.py:131`                | `RatesEventItem` has **zero producers** in `src/`; comment at `:126-130`          |
| `gold.cyclical.two_force_text`             | `routers/gold.py:345-348`              | both halves an em-dash literal; comment at `:341-344`. Render **already deleted** |
| `gold.decomposition_rows[]`                | `reports/gold_posture.py:445`          | deliberate — comment at `:435-444`                                                |
| `gold.valuation.gold_oil_ratio_percentile` | `models/gold.py:101`, never assigned   | always `null` — one hit in `src/`, the declaration itself                         |
| `gold.structural.xau_cny_premium_pct`      | `gold_posture.py:519`                  | always `null`; comment at `:515-518`                                              |
| `gold.structural.cb_52w_pct`               | `gold_posture.py:520`                  | always `null`; same comment                                                       |
| COMEX `vault_oz`                           | `gold_posture.py:280`                  | always `null`; comment at `:276-279`                                              |
| `gold_spx_ratio_percentile`                | computed from `spx_series=[]` (`:337`) | self-declared via `inputs_used`                                                   |

**Two of the dead renders are already gone.** `components/gold/lens2/TwoForceNarrative.tsx`,
`components/gold/decomposition/LensDecompositionPanel.tsx` and its
`decomposition/DecompositionBars.tsx` were deleted on this branch — the whole
`components/gold/decomposition/` directory no longer exists. §10-E's action is executed;
what remains of §10-E is the standing rule (don't delete the Pydantic fields) and the
marking at the producing sites, which the comments cited above now carry.

Misleading rather than dead — carry but keep demoted:

- `rates.cross_market` is two decomposition fields under a borrowed heading, with
  `status="partial"` a literal (`rates/snapshot.py:107-125`).
- `rates.scorecard` groups whose `source` is a promise: `"Phase 2 official macro
feeds"` / `"Phase 2 Treasury FiscalData/QRA"` / `"Phase 2 CFTC/TIC"`
  (`rates/scorecard.py:100,109,118`).

### 4.3 A code default is not deployed state

`settings.rates_snapshot_state_block_enabled` defaults **`False`** (`config.py:223`),
but production returns a fully populated `state` block — the flag is **on** on the
mini. Tab 02 must therefore read state from `/api/macro/rates`, which is
unconditional, and treat `rates_snapshot.state` as a convenience duplicate.
(`reference_code_default_is_not_deployed_state`.)

### 4.4 The yield curve carries deltas, not prior levels

`RatesCurvePoint` (`models/rates.py:31-39`) has `value` + `delta_1d/1w/1m_bps` and an
`obs_date` for the **current** observation only. Anchors are
`latest_on_or_before(as_of − 7/30 **calendar** days)` (`rates/calculations.py:55-57`)
and are then discarded. A prior level is recoverable (`value − delta_1w_bps/100`); its
date is not, and across weekends the true anchor slips by an unrecorded amount that
can differ per tenor.

Keep the board's wording: _"read the shapes, not the calendar."_ A dated multi-curve
overlay needs new backend surface — no router exposes `rates_observations`.

### 4.5 `/api/gold/gauge` is expensive

`routers/gold.py:371-401` recomputes a 5-year weekly correlation history in a Python
loop (`:381-389`) — **262** `compute_correlation_gauge` calls **per request**: the
cursor starts at `today − 1825 d` and steps 7 days while `cursor <= today`, which is
⌊1825/7⌋ + 1 = **261** iterations, plus the `current` call at `:378`.
`correlation_history` already arrives inside `/api/gold/state`; do not bind a page to
`/gauge`.

### 4.6 `/gold` bypasses `lib/api.ts` — and collapses two failures into one message

`app/gold/page.tsx:6-19` uses a raw `fetch` and re-inlines the base-URL resolution
(`:9`) that `lib/api.ts:26-40` already owns (the `const API` ternary at `:37-40`, with
the reasoning at `:26-36`). There is no `api.goldState()`. The port adds one rather
than copying the raw fetch a third time.

**The same function carries a live invariant-2 violation.** `fetchGoldState` returns
`null` for a non-2xx (`:14`) _and_ for any thrown error (`:16-18`), and `GoldPage` then
renders one message for both — `"GOLD COMPASS · Posture not yet computed. First
scheduled run lands at the next worker tick."` (`:23-41`). A dead API and a
never-computed posture are the same sight. §9 invariant 2 requires **three states**
(answered / request failed / never computed), and `app/macro/page.tsx:10-19` already
does it correctly by carrying an `error` string beside the `value`. Tab 05 must not
inherit the collapse: fix it in the PR that ships `api.goldState()`, not later.

---

## 5. Chart scale — argon already has the answer

The board's SEP dot plot renders at ~2× the rest of its page. Measured across the
board at 1440px:

| Chart               | viewBox w | rendered px | k        | label at   |
| ------------------- | --------- | ----------- | -------- | ---------- |
| Dealer expectations | 1120      | 1132        | 1.01     | 10.1px     |
| Par yield curve     | 560       | 547         | 0.98     | 9.3px      |
| **SEP dot plot**    | **560**   | **1132**    | **2.02** | **20.2px** |
| Central banks       | 520       | 329         | 0.63     | 6.3px      |

`.chart svg { width:100%; height:auto }` plus a fixed `viewBox` stretches the SVG's
_internal coordinate system_ to the container — and `font-size` lives inside it. So
effective type size is `font-size × (container_px ÷ viewBox_width)`.

**This is a solved problem in argon.** `web/components/rates/chartGeometry.ts:1-24`:

> _"these are sized by viewBox and stretched to `width:100%` … everything inside
> scales by `containerWidth/viewBoxWidth`, **TEXT INCLUDED** … The thing to hold equal
> is the **SCALE FACTOR**, not the viewBox."_

It ships `WIDE_FRAME` (1200×360, full-width) and `NARROW_FRAME` (760×300, grid cell),
each sized to its real container so k ≈ 1. `CriHistoryChart.tsx:72-82` reaches k = 1.0
the other way, with a `ResizeObserver`.

### The rule

> **Hold the scale factor at 1, not the viewBox.** Pick the frame whose width matches
> the container the chart will actually occupy, then `font-size="10"` means 10px.

**Do not invent a new primitive.** Extend `chartGeometry.ts` with a `MID_FRAME` if the
desk needs a third column width; reuse `WIDE_FRAME` / `NARROW_FRAME` otherwise.

### The rendered-px target

Argon's apparent 9-vs-11px split is mostly a scale-factor artifact. Rendered:

| Family                                     | declared | k     | **rendered** |
| ------------------------------------------ | -------- | ----- | ------------ |
| stock panel cards (400×220, height pinned) | 9        | 1.00  | **9.0px**    |
| regime strips (880×260)                    | 10       | ~1.00 | **10.0px**   |
| rates strips (1200×360, `.svgLabel` 11px)  | 11       | ~0.94 | **10.3px**   |

**All of the above are 1440px numbers.** `chartGeometry.ts:17-18` states its own frames
were measured in a **1512px** viewport — _"the full-width chart panel is ~1200px, the
curve grid cell ~760px (`.curveGrid` gives it 1.4fr of the 1440px shell)"_ — where
`WIDE_FRAME` lands at k ≈ 1.00, not 0.94. The two are consistent (a 1440px viewport
gives a ~1368px shell and a ~1132px panel); the point is that **k is a function of
viewport width and nothing in the plan said which one**. See the gate below.

So target **~9px rendered on panel cards, ~10px on full-width strips**, and leave the
rates charts' 11px alone — at their frame they already land at 10.3px.

### Standing traps

- **Never `preserveAspectRatio="none"` on a chart that draws `<text>`** — it distorts
  labels horizontally. Three existing charts do this (`MarketTideDailyChart.tsx:254`,
  `TopNetImpactChart.tsx:102`, `GexHistoryChart.tsx:168`); `GrgDivergenceChart.tsx:11`
  carries the counter-comment. Legitimate only for text-free sparklines.
- `GoldHoldingsVsPriceChart.tsx:326` uses `fontSize={6.5}` — a scale-compensation hack
  for a 1040×200 frame, **not a design token**. Do not copy it.

### Acceptance gate

A Playwright assertion that every `svg` under `/macro/*` satisfies
`getBoundingClientRect().width / viewBox.width ∈ [0.90, 1.10]`, **at a viewport pinned
in the spec itself** (`test.use({ viewport: { width: 1440, height: 900 } })`). This
converts a recurring eyeball problem into a test.

**The viewport is part of the gate, not an incidental.** k is `container_px ÷
viewBox_width`, and `container_px` moves with the viewport: the same `WIDE_FRAME` chart
is k ≈ 0.94 at 1440px and k ≈ 1.00 at 1512px (`chartGeometry.ts:17-18`). A gate that
does not pin its viewport measures whatever the runner defaulted to, and the band's
width becomes an artifact of a number nobody wrote down.

**Why the band is ±10% and not tighter, at 1440px.** A tighter `[0.95, 1.06]` would fail
the very charts being ported: at 1440px argon's rates strips declare a 1200-unit viewBox
and render at ~1132px, i.e. **k ≈ 0.94**. The band has to admit the existing, correct
charts while still catching the real defects — the board's k = 2.02 and k = 0.63 are
both far outside any sane band. Tighten it later, per-family, if the desk's frames
converge.

**The port can break the gate the port introduces.** `NARROW_FRAME`'s 760 is sized to a
`.curveGrid` cell (`RatesDesk.module.css:288`) whose width is 1.4fr of the current
shell. Moving the content under a new `app/macro/layout.tsx` that adds a tab bar — and
possibly a replay banner — changes that cell. **Re-measure both frame widths in a real
browser after the shell lands (P2), before the charts arrive (P3), and update
`chartGeometry.ts` if they moved.** Do not treat 1200/760 as constants across the port.

---

## 6. Routing and information architecture

Argon has four tab patterns. The two that matter:

- **`/regime` + `/scanner`** — `[[...tab]]` catch-all, client state + `pushState`,
  instant switching.
- **stock detail** — `[tab]` segment + `<Link>`, **genuinely per-route**; only the
  active tab's component is instantiated (`[tab]/page.tsx:46-58`), with the tab bar in
  the **layout** above it (`[ticker]/layout.tsx:42`).

**Correction to the first draft: `/regime` does NOT pre-render every tab.**
`components/regime/RegimePanel.tsx` is `"use client"` (`:1`) and renders exactly one
subtab conditionally (`:94-100`) — nothing is server-rendered for the six tabs you are
not looking at. The `ScannerPanel.tsx:86-89` citation was a **different page**, and even
there only three of four slots are pre-rendered server content (`flowContent`,
`discoverContent`, `valueContent`); the fourth is a client component handed an
`initial` prop. The comment explaining it is at `ScannerPanel.tsx:84-85`. So
"pre-rendering all nine is wasteful" was an argument against something argon does not
do, and it cannot be the reason to choose anything.

**Use the stock-detail pattern anyway**, for the reason that survives: `as_of` replay
needs a server re-fetch per tab, and nine tabs across ~20 endpoints want per-route code
splitting. But not with the stock page's prefetch setting.

**`prefetch={false}` on every tab link — this is the load-bearing detail.**
`TabBar.tsx:34` passes bare `prefetch`, which is `prefetch={true}`, and for a dynamic
route that prefetches the **full route**, not just the loading boundary. A nine-tab bar
sits entirely in the viewport, so on the stock page's setting every single page view
would fire nine full RSC prefetches, each one a `force-dynamic` server component
awaiting 1–3 API calls — **~20 backend requests per view** for the eight tabs nobody
opened. That is strictly worse than the pre-rendering the first draft rejected.

Use `prefetch={false}`. The default `'auto'` is acceptable **only** once
`app/macro/[tab]/loading.tsx` exists, because `'auto'` then prefetches to the loading
boundary rather than the full payload; ship `false` first and revisit with a measurement.

**Use the `/regime` tab-bar styling.** `.ticker-tabs` / `.ticker-tab`
(`globals.css:3199-3227`): mono, **11px**, uppercase, letter-spacing 0.05em, padding
10px 16px, `--text-muted` → `--text-primary` with a 2px active underline. The
stock `TabBar.tsx` inline style (12px, no uppercase, `:36-44`) is the outlier;
`globals.css:7226-7227` states `.scanner-tab` and `.ticker-tab` deliberately share
metrics — _"only the active colour differs here, never the scale."_

### `<Link>` + `.ticker-tab` + `as_of` do not compose. Three mechanical problems

None of these are addressed by "use `<Link>` with `.ticker-tab` classes", and all three
bite in P2:

1. **A static `href` drops the replay date.** `<Link href="/macro/rates">` does not
   carry `?as_of=`. Propagating it needs `useSearchParams()` in the tab bar, which (a)
   forces the bar to `"use client"` and (b) requires a `<Suspense>` boundary around it
   or the whole route opts out of static rendering. It also multiplies the prefetch set
   by one entry **per distinct `as_of`** — another reason `prefetch={false}` is not
   optional here.
2. **`.ticker-tab` is a `<button>` reset, not a link style.** It sets
   `background: transparent; border: none` (`globals.css:3212-3213`) and **no
   `text-decoration`**, because every current consumer is a `<button>`
   (`RegimePanel.tsx:84-92`). Put it on an `<a>` and it inherits the global anchor
   styling — underline and link colour. This is exactly why the stock `TabBar.tsx` sets
   `textDecoration: "none"` explicitly (`:43`): it uses `<Link>`. Either add
   `text-decoration: none` to `.ticker-tab` or set it on the element.
3. **`.ticker-tabs` has no `flex-wrap`.** It is `display: flex` with a bottom border and
   nothing else (`globals.css:3200-3204`). `/regime` already needs an inline
   `style={{ flexWrap: "wrap" }}` override at **seven** tabs (`RegimePanel.tsx:80`).
   Nine will overflow on narrow viewports. Decide the responsive behaviour in P2 —
   wrap, or `overflow-x: auto` like `CockpitTabs.tsx:52` — and put it in the class
   rather than as a third inline override.

### Accessibility: a nine-tab bar needs ARIA, and neither candidate pattern has it

Both patterns §6 considered ship bare elements: `RegimePanel.tsx:84-92` is a plain
`<button>` and `TabBar.tsx:31-48` a plain `<Link>` — no `role="tablist"`, no
`role="tab"`, no `aria-selected`. Nine unlabelled controls in a row is where that stops
being survivable.

Two components in this repo already do it, and are the model:

- `app/cockpit/[ticker]/CockpitTabs.tsx` — `role="tablist"` + `aria-label` (`:47-48`)
  on the container, `role="tab"` + `aria-selected` on each button (`:63-64`), and
  `overflowX: "auto"` (`:52`) for the narrow case.
- `components/stock/panels/greeks/GreekSubTabs.tsx` — `role="tablist"` (`:46`),
  `role="tab"` + `aria-selected` (`:57-58`).

**Requirement for P2:** the macro tab bar carries `role="tablist"` with an `aria-label`,
and `role="tab"` + `aria-selected` per tab, matching those two. Note honestly that
neither model implements roving `tabIndex` or arrow-key navigation — so if the desk
wants keyboard tab traversal, that is **new** work, not a copy. A link-based bar is also
not a true ARIA tablist (the panels are separate documents); if the ARIA roles fight the
`<Link>` semantics, prefer the honest markup — `<nav aria-label="Macro desk tabs">`
with `aria-current="page"` — over a tablist that lies. Decide once, in P2.

Layout:

```
web/app/macro/page.tsx              → redirect("/macro/overview")
web/app/macro/[tab]/page.tsx        → VALID_TABS, per-tab fetch, notFound() otherwise
web/app/macro/[tab]/loading.tsx     → per-tab loading boundary
web/app/macro/[tab]/error.tsx       → a dead publisher costs its tab, not the whole desk
web/app/macro/error.tsx             → catches throws from layout.tsx (the tab bar itself)
web/app/macro/layout.tsx            → <MacroTabBar/>
```

**Correction: those boundaries already exist and the port must carry them, not
invent them.** `app/gold/loading.tsx`, `app/rates/loading.tsx` and `app/rates/error.tsx`
are all present today, and the pattern being copied ships both
(`app/stock/[ticker]/[tab]/{loading,error}.tsx`). §7's move list names none of them, so
a naive re-home **deletes three live boundaries**. Add them to the move list.

**And correct the justification.** A route `error.tsx` replaces the **entire tab**, not
a card — "one dead publisher must cost one card, not the page" is what the existing
`settle()` wrappers do (`app/macro/page.tsx:8-19`, `app/rates/page.tsx:7-17`), and they
stay the primary mechanism. `error.tsx` is the backstop for a throw those wrappers do
not catch. Separately, **a segment's own `error.tsx` does not catch throws from that
segment's `layout.tsx`** — so a tab bar that throws needs `app/macro/error.tsx` one
level up, which is why it is listed above.

- **Redirects: `next.config.ts` does not exist.** The file is `web/next.config.mjs`; it
  does have `rewrites()` (`:31-40`), and `redirects()` goes beside it.
  **Next cannot emit 301.** `redirects()` emits **308** (`permanent: true`) or **307**
  (`permanent: false`); pick 308 for `/rates` and `/gold`. Good news: Next passes query
  values through to the destination automatically, so `/rates?as_of=X` →
  `/macro/rates?as_of=X` works with no extra config.
- **Trap: `/gold/replay/[date]` is kept**, so a redirect written
  `source: "/gold/:path*"` would swallow it. Only an **exact** `source: "/gold"` is
  safe. Same shape for `/rates`, which has no children today but may grow them.
- **`/gold/replay/[date]` is kept** — the only working PIT surface today, and the
  prototype for desk-wide replay (with §3.1's obs-date caveat).
- `Sidebar.tsx:28-30` lists Gold, Rates and Macro as three peers; they collapse to one
  **Macro** entry. Active state is `pathname.startsWith(href)` (`:47-48`) — already
  correct for `/macro/*`. **Unstated consequence:** with the Gold entry gone,
  `/gold/replay/[date]` matches no sidebar `href` and highlights **nothing**. Either
  accept it as a deliberately unlisted deep surface, or re-home replay under
  `/macro/gold/replay/[date]` in P4.
- Keep the `settle()` wrapper from `app/rates/page.tsx:7-17` / `app/macro/page.tsx:10-31`.
- `as_of` rides as a searchParam so it survives tab switches — see problem 1 above for
  what that costs.

---

## 7. What moves, what changes, what dies

39 distinct panels across the three source pages, each traced page component →
`api.ts` call → router → table before judging: **8 carried and built · 5 carried and
still available · 15 already covered · 8 dropped · 3 dropped as structurally dead.**

The merge is mostly **deduplication** — the three pages already share engines and tables.

Component moves:

- `components/rates/*` → `components/macro/rates/*`, `components/gold/*` →
  `components/macro/gold/*`, or keep the subtrees and re-home only the page shells.
  **Prefer the latter** — it keeps the diff reviewable and `RatesDesk.module.css`
  (1 897 L, one of only two CSS Modules in the app) mostly untouched.
- `ConfidenceStrip` (`rates/sections/StateSection.tsx:77-117`) is promoted to a shared
  `components/macro/ConfidenceArithmetic.tsx` used by all four domains — this is the
  component that makes §4.1 load-bearing.
- Add `api.goldState()` / `api.goldReplay(date)` to `lib/api.ts` (§4.6), and fix the
  two-failures-one-message collapse while you are there.
- **Move the loading/error boundaries with the pages** (§6): `app/gold/loading.tsx`,
  `app/rates/loading.tsx`, `app/rates/error.tsx` → `app/macro/[tab]/{loading,error}.tsx`
  (+ `app/macro/error.tsx`). Not listed in the first draft; re-homing without them
  silently deletes three live boundaries.

### The two bullets above contradict each other. The decision

Bullet 1 wants the subtrees left alone "so `RatesDesk.module.css` is untouched."
Bullet 2 promotes `ConfidenceStrip` out of `rates/sections/StateSection.tsx` — but
`StateSection.tsx:1` imports `../RatesDesk.module.css` and `ConfidenceStrip` consumes
**four classes from it**: `styles.confidenceStrip` (`:89`), `styles.confidenceStripLabel`
(`:92`, `:104`), `styles.confidenceDrag` (`:94`), `styles.confidenceNote` (`:110`). The
promotion touches that CSS Module either way. Same shape for `chartGeometry.ts`, which
lives in `components/rates/` while §5 wants gold, USD and inflation tabs to use it —
which makes `components/macro/*` depend on `components/rates/*`.

**Decided, once:** the subtrees stay where they are, and **shared primitives are lifted
out of `components/rates/` into `components/macro/`, taking their CSS with them.** Two
lifts, both in the PR that first needs them:

| Lift                               | To                                          | CSS                                                                                                 | In PR |
| ---------------------------------- | ------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----- |
| `ConfidenceStrip`                  | `components/macro/ConfidenceArithmetic.tsx` | move the 4 classes into a new `ConfidenceArithmetic.module.css`; delete from `RatesDesk.module.css` | P5    |
| `chartGeometry.ts` (+ `axisTicks`) | `components/macro/chartGeometry.ts`         | none — it is pure TS, no CSS Module import                                                          | P3    |

So "`RatesDesk.module.css` untouched" is **not** the promise. The promise is: no
wholesale subtree move, and each lift is a named, reviewable diff that carries its own
styles. `components/macro/*` must never import from `components/rates/*` — if a third
tab needs a rates component, lift it, do not cross-import.

### The gold posture linter breaks silently if the gold subtree moves

`web/scripts/lint-gold-copy.mjs` hard-codes its scope:
`const roots = [path.resolve("components/gold"), path.resolve("app/gold")]` (`:118`).
For a root that does not exist it **`continue`s** (`:120-125`) and the script exits **0**.
Its banned list includes `"buy"` (`:11`), `"sell"` (`:12`), `"position size"` (`:16`)
and `"predicted return"` (`:28`) — the exact vocabulary §9 invariant 7 and
`gold-page.spec.ts:38-41` exist to keep off this desk.

So **either** §7 option breaks it: moving `components/gold/` → `components/macro/gold/`
removes both roots, and re-homing only the page shell removes `app/gold` — in both cases
the build-time posture gate passes **vacuously, forever, with no output**.

**Required in the same PR that moves either root (P2 for the shell, P6 for the subtree):**

1. Update `roots` to the new locations, and extend it to `components/macro` +
   `app/macro` — the desk is one posture surface now, not a gold one.
2. Make a missing root **fail**, not `continue`. A lint whose scope can evaporate
   without a message is not a lint. Replace the `try/catch → continue` with an error
   that names the missing path and exits non-zero.

Item 2 is the load-bearing half: without it the next re-home reintroduces the same
silence.

### `RatesDesk.tsx` violates three of the desk's own invariants — **SETTLED 2026-08-27**

The plan said "move, don't rewrite." Moved unchanged, `RatesDesk.tsx` (602 L) would put
three things on the macro desk that the macro desk forbids:

| What                            | Where                                                                                                     | Which rule it breaks                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `RatesScorecard`                | `RatesDesk.tsx:560`; reads `scorecard.composite_score` at `RatesScorecard.tsx:36-38`                      | §1 "No composite"; §9 invariant 1                                                                                       |
| `SummaryStances` → `StanceCard` | `RatesDesk.tsx:440-442`, defined `:241-272` / `:215-239`; renders literal `"BUY"` / `"SELL"` (`:206-207`) | §9 invariant 7 (refusals describe, never prescribe); `gold-page.spec.ts:38-39` bans `\bbuy\b` / `\bsell\b` on this desk |
| `snapshot.synthesis`            | `RatesDesk.tsx:563-568`                                                                                   | prose generated from the composite (`rates/snapshot.py:132-135` feeds it `scorecard.composite_score`)                   |

**The resolution. Do not re-open this in review — it is decided.**

- **`RatesScorecard` — KEPT.** It is already labelled experimental legacy at the
  component (`RatesScorecard.tsx:45`, `data-testid="scorecard-legacy-banner"`) and
  already sits in the lowest tier, "Provenance and legacy" (`RatesDesk.tsx:512`,
  lede: _"the older rule score kept for comparison only"_). It is **demoted further**:
  moved inside tab 02's **"what this tab refuses"** panel and explicitly labelled a
  legacy artifact there.
  **Invariant 1 is amended accordingly (§9):** no composite in the desk's **own
  chrome**. A clearly-labelled legacy artifact quarantined inside a refusal panel is not
  chrome — it is the desk showing its work, which is the whole posture. Deleting it
  would remove the only thing an operator can compare the new state against.
- **`SummaryStances` / `StanceCard` — DROPPED.** This is prescription, and it breaks
  invariant 7 **independently of the composite rule** — a stance card would be
  forbidden even if it were computed from something the desk endorsed. `"BUY"` and
  `"SELL"` also trip the runtime ban the gold spec already enforces. Drop the two
  components and `stanceDescription` (`:195-213`) with them.
- **`snapshot.synthesis` — DROPPED.** Prose generated from the score we just demoted.
  Keeping the number quarantined and its narration in the open would be the worst of
  both. The API field stays (§10-E rule: stop rendering, do not delete).

**Test consequence.** `web/tests/e2e/macro-rates-state.spec.ts:59-82` pins the legacy
scorecard's rendered contract — the `experimental legacy` banner (`:67-69`), and
`duration-stance` → `UNKNOWN` + `scorecard-no-score` when there is no composite
(`:71-81`). It skips when the scorecard is absent (`:63-65`), so it will not fail on the
move — it will pass **vacuously** if the quarantine hides the testids. It must be
updated to assert the **quarantined** form: scorecard present, inside the refusal panel,
still banner-labelled. Budget it in P3.

---

## 8. PR slicing

### P0 and P1 are done — the graph starts one layer up

Both landed in this branch's working tree while the plan was under review, so neither is
scheduled below:

- **P0** — §4.1's two mislabelled terms now carry `kind="informational"` at their
  construction sites (`macro/rates.py:520` `policy_paths_absent`, `:538`
  `market_path_is_a_shadow`), each with its reasoning in a comment beside it. Regression
  suite: **3 tests** in `tests/unit/macro/test_confidence_term_kinds.py`, over fixtures
  in the new `tests/unit/macro/conftest.py`.
- **P1** — `/api/rates/snapshot` accepts `as_of` / `as_of_ts` through the shared
  `resolve_instant` (`routers/rates.py:30-36`, resolved at `:47`), and
  `fetch_latest_rates_snapshot` gained `WHERE computed_at <= %s`
  (`storage/rates_repository.py:205`). Tests went 6 → **13** in
  `tests/integration/api/test_rates_router.py` and 4 → **7** in
  `tests/integration/storage/test_rates_repository.py`.

They are **working-tree changes, not merged code**. They ride the first PR cut from this
branch — P2, below — and nothing here may assume they are on `main` before that merges.

**What that unblocks, plainly:**

- **P4 loses its backend dependency entirely.** Its only remaining predecessor is P3,
  because it needs tabs to put a date control above. §10-A — land replay before or after
  the merge — is answered by fact rather than preference.
- **P5 loses P0.** The shared `ConfidenceArithmetic` is now lifted against terms whose
  `kind` is already correct, so P5 depends on P3 alone.
- **Nothing else moves.** P2 never touched a confidence term; P6–P8 never touched
  `as_of`.

### The slices

| #      | PR                           | Scope                                                                                                                                                                                                                                             | Depends on |
| ------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| **P2** | `feat/macro-desk-shell`      | carries P0+P1; `app/macro/[tab]/` + `VALID_TABS`; the four loading/error boundaries (§7); the **registry-driven tab bar** (renders only registered tabs); `api.goldState()` + the three-state fix (§4.6); tab 08; the chart-scale gate            | —          |
| **P3** | `feat/macro-desk-tabs-01-02` | re-home the rates desk under tabs 01/02 and register them; the `RatesDesk.tsx` settlement (§7); lift `chartGeometry.ts`; re-measure both frames (§5); **308 `/rates` → `/macro/rates`**; re-point/rewrite the rates specs (§9)                    | P2         |
| **P4** | `feat/macro-desk-replay`     | `as_of` searchParam over the **registered** tabs, date navigation, the "you are replaying" banner driven by `computed_at`; takes §3.1's gold-clock decision (§10-H), which binds when tab 05 joins the picker in P6 — the UI that **consumes** P1 | P3         |
| **P5** | `feat/macro-desk-tab-00`     | register tab 00 and flip `app/macro/page.tsx` to `redirect("/macro/overview")`; daily loop, contradiction feed, transmission health; shared `ConfidenceArithmetic`. Scope-bounded below                                                           | P3         |
| **P6** | `feat/macro-desk-tabs-03-05` | inflation, USD, gold as tabs 03/04/05; **308 `/gold` → `/macro/gold`**; sidebar collapse; the `lint-gold-copy.mjs` fix (§7); re-point `gold-page.spec.ts`                                                                                         | P3         |
| **P7** | `feat/macro-factor-contract` | tab 07 and its backend, **shape per the spec §8 requires below**; §10-D's default is a materialised table                                                                                                                                         | P6, spec   |
| **P8** | `feat/macro-energy-p1`       | three FRED series into ingest + tab 06 surface; lights up the gold÷oil anchor (§4.2)                                                                                                                                                              | P6         |

Dependency corrections against the first draft:

- **P0 and P1 are no longer in the graph at all.** The first draft serialised the whole
  port behind them; both are now done, and P2 simply carries them.
- **P1 had no consumer.** §10-A recommended landing replay first, but no PR in the first
  draft ever read `as_of`. Recommending a capability and never scheduling its UI is how
  a backend parameter ships dead. P4 exists for exactly that.
- **Tabs 06, 07 and 08 were unscheduled.** Nine tabs, six PRs, three tabs nobody built.
  Tab 08 folds into the shell (static prose, no data path); tabs 06 and 07 attach to the
  PRs that create their data.

### No PR may ship a link to a route that does not exist

The first draft's P2 shipped the tab bar, the redirects and the sidebar collapse before
any tab existed. That is not a cosmetic ordering problem, it is a **live outage in two
directions**:

- Nine links in the bar, of which eight `notFound()` — including
  `app/macro/page.tsx`'s `redirect("/macro/overview")`, so `/macro` itself 404s until
  P5.
- Worse, the 308s send `/rates` → `/macro/rates` (P3) and `/gold` → `/macro/gold` (P6).
  Two working pages would 404 for the length of two PRs.

**The fix is a registry, not a schedule.** `VALID_TABS` is the single source of both the
route guard and the bar: `app/macro/[tab]/page.tsx` `notFound()`s on anything not in it,
and `<MacroTabBar/>` renders one link per entry. P2 seeds it with tab 08 alone; each
later PR adds its own entry in the same commit that adds its route. The bar therefore
grows from one slot to nine, and at no point links anywhere that 404s. A test asserts the
identity — every rendered tab href resolves, and every `VALID_TABS` entry is rendered.

Consequences to hold to:

- **Redirects ride their destination.** `/rates`'s 308 lands in P3, `/gold`'s in P6.
  Neither may appear in P2.
- **The sidebar collapses in P6**, the first moment both destinations exist. Until then
  Gold, Rates and Macro stay three peers, and Macro's `startsWith` match already covers
  `/macro/*` (`Sidebar.tsx:47-48`).
- **`app/macro/page.tsx` is left alone until P5.** It keeps rendering today's four
  domain cards, so `/macro` never 404s. If P6 lands before P5 those four cards are
  briefly reachable at both `/macro` and their own tabs — a duplicate, not a break; P5
  replaces the page with the redirect.
- **§7's linter parenthetical predates this re-slicing.** `lint-gold-copy.mjs`'s roots
  are `components/gold` and `app/gold` (`:118`), and neither disappears until P6 — so
  §7's two required items (re-point the roots, make a missing root fail) attach to **P6**,
  not P2. P2 may add `components/macro` + `app/macro` to `roots` early; that half is
  purely additive.
- **The chart-scale gate is vacuous in P2** — tab 08 is prose and draws no SVG. Give the
  gate a non-zero-count assertion in the same commit, or it is §7's evaporating-scope
  defect in a new file. It becomes meaningful in P3, which is also where §5 requires the
  frames re-measured.

### P3 before P5 — and the move is not mechanical

P3 lands first so tab 00 is built against the real desk rather than against the old
pages, and so every surprise the move produces surfaces before anything new is stacked on
it. **That is the reason — not that the move is easy.** It is not:

- Re-homing a component across a route boundary changes **what its server component
  fetches**. `/rates` is one page making one `settle()`-wrapped fetch
  (`app/rates/page.tsx:7-17`); tabs 01 and 02 are two routes, and the same
  `RatesSnapshotResponse` has to be fetched by each — or the split has to be decided
  deliberately, per §3's binding table.
- `RatesDesk.tsx` (602 L) **is** the page shell, so it cannot move unchanged, and §7's
  settlement already requires three behaviour changes inside it: quarantine
  `RatesScorecard`, drop `SummaryStances`/`StanceCard`/`stanceDescription`, stop
  rendering `snapshot.synthesis`.
- §5 requires both `chartGeometry.ts` frame widths re-measured in a real browser once
  the shell changes, and `chartGeometry.ts` is itself lifted in this PR.
- `RatesDesk.test.tsx` (17.3 K) breaks by construction and is rewritten, not re-pointed
  (§9).

P6 branches off P3, not P5 — the domain tabs and the overview share no code.

### Navigation order is not causal order

The tabs run Fed (01) → rates (02) → inflation (03) → USD (04) → gold (05). The engine's
own chain does not: `CAUSAL_ORDER` is `("inflation", "policy_rates", "usd", "gold")`
(`macro/snapshot.py:43`) — inflation first, policy second. §1's reading chain, "Fed →
inflation expectations → USD → gold", disagrees with it on the first two links.

**Keep the Fed-first order, and state on the desk that it is a reading order.** Three
reasons, recorded so nobody silently re-sorts the strip later:

- **Nothing consumes tab adjacency.** `CAUSAL_ORDER` is consumed by
  `macro/snapshot_assembly.py:74`, `:84` and `:126`, the last of which writes an explicit
  ordinal into the stored snapshot — and the comment at `snapshot.py:40-42` says why:
  _"the snapshot stores an explicit ordinal rather than relying on this tuple at read
  time, so a stored snapshot keeps the order it was assembled with even if the chain is
  ever reordered."_ The causal order is versioned in the store. The tab strip is not, and
  must never pretend to be a second copy of it.
- **Fed-first is how the operator arrives.** A rate decision is the event; inflation is
  the input he goes looking for afterwards. Sorting the navigation by causality would put
  inflation at 01 and the Fed at 02, optimising the strip for a chain nobody browses in.
- **The causal claim already has a home.** `/api/macro/snapshot`'s chain verdict is where
  the four are asserted to belong together, and tab 00 renders it (§9 invariant 8). That
  is asserted, tested and stored; a tab order is none of those.

So: do not reorder, and no tab's copy may imply that tab N causes tab N+1.

### What tab 00 may and may not be

Tab 00 is the one slice with no existing component (§2), which is exactly why it is the
one that can quietly become new analytics.

**Tab 00 re-presents what the other eight tabs already compute. It computes nothing of
its own.** Its data is the five requests §3 gives it — `/api/macro/snapshot` plus the four
domain states — the same responses tabs 02–05 render, arranged for a morning read. The
daily loop, contradiction feed, cross-domain contradictions and transmission-health panels
are **layouts over fields that already exist**: the snapshot's status and its
`SnapshotReason` list (`macro/snapshot.py:34`, `:47`), and each domain's `state`,
`confidence` and `confidence_reasons`.

It must never:

- average, weight, blend or score the four domains — §1's no-composite rule, §9
  invariant 1;
- derive a fifth number from the four (a "macro regime", a risk level, a dial);
- introduce an endpoint of its own — if tab 00 wants a value no tab publishes, that is a
  change to the domain that owns it, in that domain's PR, not a new aggregate here;
- re-rank the contradictions. `SnapshotStatus` is already worst-finding-wins and the
  four values are deliberately kept distinguishable (`snapshot.py:30-33`: _"'rates never
  ran' and 'rates ran but USD ignored it' call for different operator actions"_). A
  second severity ordering invented on the client is a composite wearing a list's
  clothes.

If a panel cannot be built from a field some other tab already renders, it is out of
scope for P5 and belongs in a spec.

### The factor contract is named here and specified nowhere

§1 states the direction (equity consumes macro factors, never the reverse), §3 gives tab
07 a route, the table above gives P7 a branch name, and §10-D asks how to deliver it.
None of that says **what a factor is**: not its shape (a row per
`(as_of, factor_name, value)`? a typed column set?), not its identity (which clock — the
observation's, the state's `available_at`, both?), not who writes it (a nightly job over
the four domain states, or each domain at its own settle), and not who reads it back or
on what key.

**Out of scope for this plan, explicitly.** This is a presentation port; the factor
contract is a data contract, and inventing one in a table cell is how a shape nobody
agreed to becomes the thing three consumers depend on. Verified 2026-08-27: no design
exists — `macro_factor_daily` and `/api/macro/factors` appear nowhere in `src/` or
`docs/` outside this plan, and no router serves `/factors` (the only hits under
`src/uw_scan/api/routers/` are two `factors_jsonb` field reads, `routers/macro.py:208`
and `routers/gold.py:340`).

**P7 does not open until a design spec exists** under `docs/superpowers/specs/`, carrying
at minimum: the row grain and key, which clock(s) travel with a factor, the writer, and
the first named consumer with its join. The direction it must honour is already on record
(`project_macro_phase2_equity_consumes_factors`). Until then tab 07 stays what §3 says it
is — a route with no data path — and §10-D is not answerable.

### Deploy ordering: two images, one Watchtower, no ordering guarantee

The API and the web app are separate images — `ghcr.io/moremeds/argon-app` and
`ghcr.io/moremeds/argon-web` (`docker-compose.yml:26`, `:97`), both built by the same
release tag (`.github/workflows/release.yml:184-186`) and both pulled independently by
the engine-wide Watchtower in `/opt/xenon/compose.yml`. **There is no ordering guarantee
between them.** A release can be live on one image and not the other for as long as
Watchtower's poll interval, and they can land in either order.

So the rule is: **the API change ships in a release at or before the web change that
consumes it, and every web change must still be correct against the previous API image.**

**The intermediate state, measured on the mini 2026-08-27** against the currently
deployed (pre-P1) `argon-app`:

```
GET /api/rates/snapshot?as_of=2026-01-01  → 200, as_of "2026-08-25"
GET /api/rates/snapshot                   → 200, as_of "2026-08-25"
```

Byte-identical. FastAPI ignores a query parameter the route does not declare, so an old
API image answers a replay request with the **live** snapshot and a 200 — no 404, no 422,
nothing to notice. If a web image carrying P4's date control ever deploys ahead of the
API image carrying P1, an operator who picks 2026-01-01 gets tab 02 rendering today's
curve **under a replay banner**, beside tabs 01/03/04/05 replaying correctly on
`/api/macro/*`. That is §3.1's worst failure mode manufactured by a deploy race rather
than by a missing parameter, and it is invisible.

Two things make it benign:

1. **P2 carries P0+P1 and reads neither.** The parameter is therefore live for several
   releases before P4's UI asks for it. This is the whole reason to keep them in P2
   rather than holding them for P4.
2. **P4's banner is driven by the response, not the request.** `/api/rates/snapshot`
   returns `computed_at`; a replay to instant T must see `computed_at <= T` or render
   "this publisher did not answer for that instant" instead of a curve. The check is
   free, is correct against both API images, and is the only thing that survives a
   Watchtower race.

Per PR: **P3–P6 are web-only** (the 308s are Next config, i.e. the web image), so no
ordering applies. **P7 and P8 ship API and web together** — both must be additive, and
tab 07 against an API image without `/api/macro/factors` must render §9 invariant 2's
"request failed", never an empty factor list dressed as "no factors today".

### Rollback

P2, P4, P5, P7 and P8 are ordinary reverts. **P3 and P6 are not** — each merges a 308,
and once `/rates` (P3) or `/gold` (P6) redirects, backing out needs a second deploy to
remove it. Land each on its own and let it sit a day before the next. P0/P1's API changes
revert cleanly but are additive, so there is rarely a reason to.

Decisions this section formerly hard-coded now live in §10, reconciled: A, B, C and E are
recorded there as settled with their reasons; D and F–H remain open.

---

## 9. Tests

### Existing, and what the port does to them

| Spec                                                                          | Effect                                                                                                                                                                                                                                                                 |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web/tests/e2e/macro-rates-state.spec.ts` (12.3 K, **13 tests**)              | `page.goto("/rates")` at `:18` — **breaks on the redirect.** Re-point to `/macro/rates` in P3. Its **3** replay tests (`:154` a 404 for an unanswered instant, `:166` evidence-bounded replay, `:194` stale-not-current) are the model for the desk-wide replay tests. |
| `web/tests/e2e/gold-page.spec.ts`                                             | `page.goto("/gold")` `:15` — re-point in P6. Keep the posture-language ban (`:38-41`) and the zero-console-errors assertion (`:44`).                                                                                                                                   |
| `web/tests/e2e/gold-screenshot.spec.ts`                                       | re-point; artifact-only.                                                                                                                                                                                                                                               |
| `web/tests/unit/rates/*` (5 specs + a 15.9 K shared fixture)                  | 4 of 5 survive if components stay in place (§7). **`RatesDesk.test.tsx` (17.3 K) is the exception** — `RatesDesk.tsx` (602 L) _is_ the page shell, so re-homing it in P3 breaks that spec by construction. Budget for rewriting it, not for it surviving.              |
| `web/tests/unit/macroDesk.test.tsx` + `tests/fixtures/macroDomainStates.json` | the invariant home; extend rather than replace.                                                                                                                                                                                                                        |
| `web/tests/unit/{goldCompassLayout,dataAuditFooter}.test.tsx`                 | survive.                                                                                                                                                                                                                                                               |

**Gap: no e2e spec navigates to `/macro` today** — verified by sweeping every
`page.goto(` under `web/tests/e2e/`; the closest are `/rates` and `/gold`, and only API
requests reach `/api/macro/*`. P2 adds one.

### Already shipped with P0/P1 — the Python side

Counted 2026-08-27 with `grep -c "def test_"`, not recalled:

| Spec                                                 | Tests                     | What it holds                                                                                                                                                                                                                                                                                                                                                             |
| ---------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/macro/test_confidence_term_kinds.py`     | **3** (new), 11 collected | invariant 10, over the four engines **plus a fifth rates scenario**. The four alone could not fail on the count half of the bug: each has exactly one absent policy path, and `Decimal(1)` is both a no-op multiplicand and a legal fraction. The fifth holds two absent paths so the count is 2 and both guards bite. Fixtures in the new `tests/unit/macro/conftest.py` |
| `tests/integration/api/test_rates_router.py`         | **13** (6 → 13)           | `/api/rates/snapshot` replay: the live path byte-unchanged, `computed_at` selection, and `_mark_stale_snapshot_sources` aged against the requested instant, not the wall clock                                                                                                                                                                                            |
| `tests/integration/storage/test_rates_repository.py` | **7** (4 → 7)             | the `computed_at <= %s` predicate, on a fixture where the **newer** compute carries the **earlier** market date — so a query filtering the wrong column cannot accidentally pass                                                                                                                                                                                          |

These are P4's model one layer down: the replay assertions the desk needs at the UI
already exist against the same endpoint.

### Invariants that stay test-enforced

1. No composite anywhere in the desk chrome — no score, allocation, or probability.
2. Empty slots are **three-state**: answered / request failed / never computed.
3. The four policy paths are never averaged.
4. `UNKNOWN` ≠ `NEUTRAL`.
5. SEP dots stay anonymous — the payload is `(rate_percent, participant_count)`
   (`PolicyPathParticipantPoint`, `models/macro.py:200-201`, carried at `:236`), and the
   comment at `:214-215` states why: _"an anonymous SEP dot belongs to no named
   participant."_ (The first draft cited `:215` alone, which is the reason, not the
   shape.)
6. Gold valuation keeps its **⚠ NEVER A SIZING INPUT** marking.
7. Refusals describe; they never prescribe.
8. The chain verdict is fetched **beside** the cards, never instead of them; its own
   failure renders as `macro-chain-unassembled`, never as a clean chain.
9. _(new, P2 scaffold / P3 real)_ Chart scale k ∈ [0.90, 1.10] on every `/macro/*` SVG,
   at a viewport pinned in the spec (band justified in §5). It must also assert it found
   at least one SVG — in P2 there are none, and a gate that can pass on an empty set is
   §7's evaporating-scope defect in a new file.
10. _(shipped with P0)_ A domain's reported `confidence` equals what its own
    `confidence_reasons` fold back to using **`kind` alone** —
    `tests/unit/macro/test_confidence_term_kinds.py`, 3 tests over all four engines.
    **Nothing is rendered.** This is a Python-side refold of the contract, not a browser
    assertion; the earlier wording ("the rendered confidence product") described a test
    that could not exist where the test actually lives. The web layer inherits the
    invariant through `ConfidenceArithmetic` (P5), which is why P0 had to land first even
    though it no longer appears in §8's graph.

### Two frozen artifacts, not one

Any PR here that touches an API surface — P7's `/api/macro/factors`, P8's energy fields,
and P1 already — moves **two** generated files that must never be regenerated wholesale.
The first draft named only the first.

**1. `web/lib/types.ts` — measured 2026-08-28: 15 559 lines, 492 K.** `npm run gen:types`
runs the pinned `openapi-typescript` **7.13.0** (`web/package.json:12`), which emits
_declaration_ order, while the committed file is in the older _alphabetical_ order. A
full regen reorders the whole file and buries the real change. **Hand-insert additive
schema changes in their alphabetical slot** — and write them with a shell redirect, not
the `Edit` tool, whose prettier hook reflows the 4-space generated file to 2-space.
Recorded in
`docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_backend_patterns.md:306-309`.

**2. `tests/integration/api/openapi.snapshot.json` — measured 2026-08-27: 34 054 lines,
860 K.** Same hazard, omitted by the first draft entirely. It is dumped with
`json.dumps(indent=2, ensure_ascii=True, sort_keys=True)` (same doc, `:310-313`) and
`tests/integration/api/test_openapi_snapshot.py` asserts three things against it:
the **set** of path keys (`:14`), that every recorded method still exists (`:18-22`), and
`components.schemas` by **exact equality** (`:23`). So a new route trips the first
assertion and a new response model trips the third — P7 does both.

**A hand-edit is verifiable without a running server, and P1's first one was wrong.**
Regenerate from the committed snapshot and compare order-normalized:

```bash
cd web && npx openapi-typescript ../tests/integration/api/openapi.snapshot.json -o /tmp/t.ts
diff <(sed 's/[[:space:]]\+/ /g' lib/types.ts | sort) <(sed 's/[[:space:]]\+/ /g' /tmp/t.ts | sort) | grep -c '^[<>]'
```

Sorting removes the alphabetical-vs-declaration ordering, so what survives is real
content drift. The floor is **16** — a pre-existing key-order artifact inside a JSDoc
`@example` block, present at `HEAD` before any of this work. P1's hand-edit first
measured **25**: it had inserted the two query parameters but dropped the operation's
`@description` block, so the file was not what a regen would produce. Fixed 2026-08-28;
back to 16. Run this before review on any PR that hand-edits either artifact.

**Both were exercised by P1 and both held.** The `as_of`/`as_of_ts` parameters went in by
hand: **+22 lines** in `types.ts` and **+51** in the snapshot, each in place, neither
regenerated. That is the working proof of §10-E's cost argument — the expensive thing is
the regen, not the edit. (§12's "451 KB" figure predates P1 and this session's gold
annotations; 492 K is the measured number.)

---

## 10. Decisions needed from the operator

### Still open

Each carries the plan's own default and the reason for it, so silence ships something
defensible rather than nothing.

|       | Question                                                                                                         | Default, and why                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **D** | Factor delivery: API-only, or materialise `macro_factor_daily`?                                                  | **Materialise** — the first named consumer is a backtest join, and a join wants a table, not a request per row. **But it is not answerable yet:** §8 records that no factor contract exists (no shape, no clock, no writer, no reader), and P7 is blocked on a spec that supplies them. Answer D _in_ that spec, not here.                                                                                                                                 |
| **F** | Read-only deep link from tab 00 to the `/regime` vol desk?                                                       | **Yes — one link, clearly marked as leaving the macro desk.** §1 keeps the SPX `vrp_macro_signal` card off this desk because its "macro" means index-level vol; a link is not a card, and the alternative is an operator navigating by memory. One link, no embedded value, no shared chrome.                                                                                                                                                              |
| **G** | Invest in falsifier-threshold measurement ("what CPI print flips the state")?                                    | **Defer to Phase 2.5.** Phase 1 closed with the engine deliberately descriptive (`project_macro_phase1_closed`), and a falsifier threshold is a claim about what _would_ change the answer — a new analytical surface, which §1 rules out for this port.                                                                                                                                                                                                   |
| **H** | §3.1's gold clock: give `/api/gold/replay` `computed_at` semantics, or label its control an obs-date and say so? | **Label it, do not change the API.** `fetch_gold_posture_for_obs_date` is `WHERE obs_date = %s` with exact equality (`storage/gold.py:862-880`), so `computed_at` semantics is a new query and a new index question, not a second parameter. Labelling costs one string and is honest; §3.1's ban still holds — do not ship the desk-wide picker over all five tabs until one of the two is done. Taken in P4, binding in P6 when tab 05 joins the picker. |

**I — raised by P3's execution 2026-08-28, needs an operator ruling.** §7 drops
`SummaryStances` because it "renders literal `BUY` / `SELL`", which "breaks invariant 7
**independently of the composite rule**". The same sentence is true of `RatesScorecard`,
which §7 keeps: `RatesDurationStance` is
`Literal["BUY", "SELL", "NEUTRAL", "UNKNOWN"]` (`models/rates.py:18`),
`rates/scorecard.py:225-227` returns `"BUY"` / `"SELL"` whenever the composite clears
±0.25 with coverage ≥ 0.5, and `RatesScorecard.tsx:57-59` prints it verbatim as
`{duration_stance} duration`. So the section titled **"What this tab refuses"**, whose
prose says the tab takes no stance, can print `SELL duration`. It does not today — prod's
composite is 0.11, inside the ±0.25 band — which is exactly why nobody has seen it.

Verified it is the only source: `duration_stance` is the sole producer of those two words
anywhere on the rates data path.

**P3 shipped the narrow, honest thing and did not resolve this**, because resolving it
means changing what a component renders and §7 says the scorecard question is decided and
must not be re-opened. The e2e ban is whole-body on tab 01 and scoped to _outside_
`#refuses` on tab 02, with a non-vacuity anchor proving the carve-out did not swallow the
page, and the reasoning written into the test.

The plan's own logic points one way — §7 keeps the scorecard so an operator "can compare
the new state against the old rule score", and the comparison datum is the **score**, not
the stance word, which is a derived prescription. Suppressing the word while keeping the
number would satisfy both §7's purpose and invariant 7. That is a rendered-contract change
with an e2e test pinned to `duration-stance`, so it is the operator's call, not P3's.

### Settled, with the reason recorded

|       | Question                                                                                                                 | Resolution                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ----- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A** | Desk-wide replay: land P1 before or after the presentation merge?                                                        | **SETTLED by fact 2026-08-27 — before.** P1 is done in the working tree and rides P2 (§8), so replay is live at the API several releases before P4's UI asks for it. That ordering is also what makes the Watchtower race benign (§8, deploy ordering).                                                                                                                                                                      |
| **B** | Component homes: move the `rates`/`gold` subtrees under `components/macro/`, or re-home only the page shells?            | **SETTLED 2026-08-27 in §7 — page shells only, plus two named lifts.** The first draft's "and leaves `RatesDesk.module.css` alone" was wrong and is withdrawn: `ConfidenceStrip` consumes four classes from it and `chartGeometry.ts` lives beside it. The promise is no wholesale subtree move, each lift a reviewable diff carrying its own styles, and `components/macro/*` never importing from `components/rates/*`.    |
| **C** | Energy ordering: FRED spot series (P1, usable same-day) or lake term structure (more distinctive, more expensive)?       | **SETTLED 2026-08-27 — FRED spot first**, and §8's P8 is scoped to it. Three FRED series are usable the day they land and light up the gold÷oil anchor that §4.2 records as permanently `null` today (`models/gold.py:101`). The lake term structure is a larger build for a more distinctive but unmeasured signal; it is not a prerequisite for tab 06 being honest.                                                       |
| **E** | The **eight** permanently-empty fields (§4.2): delete the fields from the API, or stop rendering them and mark the rest? | **SETTLED 2026-08-27 — stop rendering, do not delete.** Remove the two dead _renders_ (`TwoForceNarrative`, `LensDecompositionPanel`); leave every Pydantic field in place and mark all eight at their producing site. Deleting fields is a contract change costing an OpenAPI snapshot update and a `types.ts` regen that reorders 15 552 lines, for zero operator benefit — what misleads is the rendering, not the field. |

---

## 11. Reproduce

```bash
ssh macmini 'curl -s http://127.0.0.1:8400/api/macro/policy'
ssh macmini 'curl -s http://127.0.0.1:8400/api/rates/snapshot'
ssh macmini 'for d in inflation rates usd gold; do curl -s "http://127.0.0.1:8400/api/macro/$d"; done'
```

Values in §3/§4 are from 2026-08-27 07:40 UTC+8, `option_wizard/uw_scan` on the mini.
No value in this plan is invented.

---

## 12. Observed but out of scope

- `web/tests/e2e/regime-page.spec.ts:3` is titled _"three tabs and GEX default"_ and
  asserts `regime-tab-gex` is active at `:9`, but both `RegimePanel.tsx:37` and
  `app/regime/[[...tab]]/page.tsx:26` default to `"tide"`. Observed statically; the
  suite was **not run**, so this is a discrepancy, not a confirmed failure.
  **CONFIRMED 2026-08-28 by P4's full e2e run: it fails.** So do the other twelve listed
  below — and all thirteen fail identically against a build of `main` on the same database,
  so none of them is this port's doing.
- **The e2e suite has 13 pre-existing failures, baselined 2026-08-28** (P4's run: 72 passed
  / 13 failed / 1 skipped; the same 13 by name against a main-checkout build). They are
  `canary-page` (1), `magnet-view` (4), `regime-page` (3), `technicals-tab` (3) and
  `volatility-tab` (2). Not an empty-database artifact — `/api/watchlist` and
  `/api/stock/NVDA/volatility/series` both answer 200 locally. **Every macro, rates and
  gold spec passes** (29 tests, 1 skipped), the chart-scale gate included. A future slice
  should not read a red suite as its own regression; diff the failing set, not the count.
- `web/CLAUDE.md:53` states `lib/types.ts` is 47 KB; it is **492 K** (measured 2026-08-28).
- **`playwright.config.ts` sets `reuseExistingServer: true` on port 3001, which can silently
  test the wrong code.** A detached `next-server` from the MAIN checkout was holding 3001
  during P4's verification; run as-is, the suite would have exercised that build — which has
  none of this port — and reported it as this branch's result. Verified on an isolated port
  instead. Worth a `PORT`-aware config, or at least a note in `web/CLAUDE.md`, before
  another slice trusts a green run.

---

## Revision history

Drafted 2026-08-27 from a direct read of the mini and of the three source pages, then put
through three review passes before sign-off. **Self-review** re-verified every citation
against the files and rewrote §2, §5 and §6 around what it found — that `/regime` does
not pre-render its tabs, that the SEP dot plot was never oversized on argon, and that
"mostly a move" is true of the source pages but not of the board. The **codex tribunal**
found the §3 tab→endpoint contradictions, the misplaced P0 test claim, and the
unspecified factor contract, and forced §7's two contradicting component-home bullets to
a single decision. The **adversarial pass** produced **12 findings**, all applied here:
that the first draft's P2 would have 308'd two live pages to routes that did not exist
yet, that P3 was being sold as "mechanical" when it changes what every moved server
component fetches, that the two deploy images have no ordering guarantee between them,
that navigation order was being conflated with the engine's `CAUSAL_ORDER`, that tab 00
had no scope bound, and that §9's counts and both frozen artifacts had drifted. Neither
earlier pass recorded its own finding count, so none is claimed for them here.

A fourth pass, **simplicity/optimality**, ran over the shipped code rather than the
document and produced the finding that mattered most: `test_confidence_term_kinds.py`
**could not fail on half the defect it was written for**. Reverting `kind` on
`policy_paths_absent` left all nine cases green, because every shipped scenario is
missing exactly one required path and a count of 1 is invisible to both guards. A fifth
fixture with two absent paths closes it — measured green with the fix, two failures
without it. The same pass found a hand-edit of `web/lib/types.ts` that had dropped the
operation's `@description` block, two test matchers still accepting a landmark name that
no longer exists, gold fixtures asserting values production cannot emit, and a `WHERE`
clause assembled in Python where `COALESCE(…, 'infinity')` removes the branch.

**P0 and P1 shipped in the working tree during the revision** — the confidence-term
`kind` fix with its three-test regression suite, and `as_of` on `/api/rates/snapshot`
with ten new tests — along with the §10-E gold-panel cleanup. §8 was rebuilt around that
fact rather than continuing to schedule work that was already done.
