# Macro desk — bind every board panel to live data

**Status:** EXECUTED 2026-08-29 — 47/47 board panels live
**Spec:** `docs/superpowers/specs/2026-08-27-macro-desk-board.html` (sha-pinned board artifact)
**Predecessor:** `docs/superpowers/plans/2026-08-27-macro-desk-page-port.md`
**Audit:** `docs/research/2026-08-28-macro-desk-board-conformance/VERDICT.md`
**Branch:** `feat/macro-desk-tabs-03-05`

The board binds its **design** and its **information**. The port so far has bound
both on four tabs, one of them on none, and three of them partially. This plan
closes the remainder. It adds **zero new endpoints** — every unbuilt panel's data
was verified present on the running API on 2026-08-29.

---

## 1. Measured gap

Board panel counts are from the artifact itself (`<div class="panel-h">` per
`<section id="tN">`). Tab 08 does not ship, by the board's own instruction.

| Tab          |  Board | Conforming | Kind of work | Gap                                                     |
| ------------ | -----: | ---------: | ------------ | ------------------------------------------------------- |
| t0 Overview  |     11 |          0 | **BUILD**    | nothing on this branch (see §5, collision)              |
| t1 Fed       |      8 |          0 | **RESHAPE**  | data bound; house sections, not board panels; 1 missing |
| t2 Rates     |      9 |          0 | **RESHAPE**  | data bound; 9 board panels rendered as 5 house sections |
| t3 Inflation |      4 |          4 | ✅ done      | —                                                       |
| t4 USD       |      2 |          2 | ✅ done      | —                                                       |
| t5 Gold      |      8 |          2 | **BIND**     | 3 unconsumed endpoints; 2 panels merged into 1          |
| t6 Energy    |      2 |          2 | ✅ done      | —                                                       |
| t7 Factors   |      3 |          3 | ✅ done      | —                                                       |
| t8 Design    |     11 |          — | ✅ unshipped | board says it does not ship                             |
| **Total**    | **47** |     **11** |              | **36 panels short of the board**                        |

The three kinds are genuinely different work and must not be planned as one:

- **BIND** — the data is fetched but shown below board resolution. Cheapest, highest fidelity gain.
- **RESHAPE** — the data is already on screen in house sections. No new fetches; this is the design port finishing its job.
- **BUILD** — nothing exists.

---

## 2. Endpoint reality — re-verified, and the board is stale in two places

Every endpoint in the board's §⑨ was re-probed against `127.0.0.1:8400` on
2026-08-29. All EXISTS claims hold. **Two entries have changed since the board
was captured and the plan must not inherit them:**

| Board §⑨ says                        | Actual now                                                 | Consequence                                                    |
| ------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------- |
| `/api/rates/snapshot?as_of=` MISSING | **EXISTS** — `routers/rates.py` takes `as_of` + `as_of_ts` | Q-A is closed. Desk-wide replay is no longer blocked.          |
| `/api/macro/factors?as_of=` MISSING  | still absent                                               | No blocker — t7 ships as assembly over the four domain states. |

Verification of the first, since it reverses the board's single loudest warning:

```
GET /api/rates/snapshot              → as_of 2026-08-18, computed_at 2026-08-20T02:33:48Z
GET /api/rates/snapshot?as_of=2026-06-01 → as_of 2026-05-28, computed_at 2026-05-29T22:45:00Z
```

The board's worst-case ("a live tab 02 beside a replayed tab 01/03/04/05 and
nothing on screen saying so") cannot occur. Any plan step written to work around
it is dead work.

---

## 3. Per-panel binding table

Every field below was observed in a live 200 response. Nothing here is proposed.

### t5 Gold — BIND (do this first; smallest diff, largest fidelity gain)

| Board panel                                | Source                                                         | State today                                    |
| ------------------------------------------ | -------------------------------------------------------------- | ---------------------------------------------- |
| Transmission gauge · correlation collapse  | `/api/gold/state` `.gauge`                                     | ✅ `TransmissionGaugePanel`                    |
| Three lenses · none composites             | `.structural` / `.cyclical` / `.valuation`                     | ✅ three panels                                |
| **Anchor decay · gauge corr_60d, daily**   | **`/api/gold/gauge` `.history_252d` — 261 dates, 19 valued**   | ⚠️ **60d cut unavailable; series is sparse — see below** |
| Expression cost                            | `.structural.uw_25d_skew_sigma`                                | ✅ `ExpressionCostPanel`                       |
| **Central banks · 12M net, three buckets** | `.structural.cb_{strategic,tactical,diversifier}_12m_sum_t`    | ⚠️ merged into `StructuralPanel`               |
| **Western institutional flows · L1**       | `.structural.{gld_holdings_t,gld_30d_net_flow_t,lbma_*,cot_*}` | ⚠️ merged into the same panel                  |
| L2 cyclical readings (dimmed)              | `.cyclical.*`                                                  | ✅ `CyclicalPanel`                             |
| **Input manifest**                         | `.inputs_used` (16 sources × 8 fields)                         | ⚠️ `DataAuditFooter`, not the board's manifest |

**The anchor-decay panel — corrected 2026-08-29.**
`goldTab.tsx:43` declines `/api/gold/gauge` citing §4.5 of the port plan
("recomputing 262 correlation gauges per request"). Re-measured: **50ms**
(`0.057 / 0.054 / 0.050`), against 29ms for `/api/gold/state`. The perf reason no
longer holds.

But the substitution is **not** a like-for-like downgrade, and an earlier draft of
this plan said it was. `GoldGaugeTimeSeriesPoint` is `{obs_date, corr_252d}` —
**0 of 261 points carry `corr_60d`**, and the span is 2021-08-30 → 2026-08-24, so
it is neither daily nor the 60-day cut. `CorrelationHistoryPanel`'s own note is
therefore **accurate and stays**: the producer computes at `window=252` only
(`gold_posture.py`), so the board's 60-day series does not exist to plot and no
amount of wiring creates it.

What binding actually buys — **measured on the rendered page, not assumed.** An
earlier draft of this plan said "261 points instead of 3" twice. That was wrong:
`history_252d` carries 261 **dates** of which only **19 carry a value** — a
252-day window produces nothing until it has 252 days behind it, and the sampling
is sparse thereafter. Against `correlation_history`'s 11 observations (3 + 3 + 5
across the three pairs), the gauge contributes the densest single series on the
panel — 19 points spanning five years against the largest pair's 5 — and that is
the whole of the gain.

Worth keeping the reason this was caught: the panel derives both counts at render
time, so the page printed **19 vs 11** while the plan still said 261 vs 3. The
board-value rule ("derive every such sentence at render time") exists for stale
mock figures; here it caught a stale figure of my own.

**The honest finding is a data gap, not a port gap.** The board's t5 anchor-decay
panel cannot be built as specified — not at 60 days and not at daily resolution —
because the desk neither computes nor retains that series. Recorded here so the
next pass does not re-open the endpoint hunt: the fix lives in
`reports/gold_posture.py`, not in the web layer.

**The board's §⑩ P2.2 names three unconsumed gold endpoints, not one**, and the
other two carry the desk's densest series:

| Endpoint                     | Carries                                                      | Consumed |
| ---------------------------- | ------------------------------------------------------------ | -------- |
| `/api/gold/gauge`            | `history_252d` — 261 dates, 19 valued, corr_252d, 5 yrs       | ❌ no    |
| `/api/gold/inputs/{id}`      | per-input daily series — `DFII10` **1293 pts**, `GLD_CLOSE` 344 | ❌ no  |
| `/api/gold/lenses/{id}`      | `posture` + `detail` per lens — the L1 detail t5 asks for      | ❌ no    |

`/api/gold/inputs/*` is what makes the **Input manifest** panel more than a list:
each of the 16 entries in `inputs_used` has a real series behind it. Note some are
empty (`cot_gold_weekly` → 0 pts) — a three-state row, not a hidden one.

### t2 Rates — RESHAPE (no new fetches at all)

`CurveDesk` + `sections/DecompositionSection.tsx` already consume every field.
The board wants nine named panels where the page renders five house sections.

| Board panel                           | Field (already fetched)                                                                                                                                          |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Par yield curve · current vs 1W vs 1M | `curve.points` (11), `curve.slopes` (4)                                                                                                                          |
| 10Y nominal decomposition             | `decomposition.{nominal_10y,real_10y,breakeven_10y,forward_inflation_5y5y,term_forward_compensation}`                                                            |
| Cleveland 5-term decomposition        | `decomposition.{model_real_yield_10y,expected_short_real_rate_10y,expected_short_inflation_10y,real_term_premium_10y,inflation_risk_premium_10y}` — exactly five |
| 10Y move attribution · per window     | `decomposition.attribution` (4 windows)                                                                                                                          |
| Supply SUB-STATE                      | `supply.{fiscal,supply_read,status}`                                                                                                                             |
| Positioning SUB-STATE · 10Y futures   | `positioning.{rows,details}`                                                                                                                                     |
| Funding SUB-STATE                     | `policy.plumbing` (4 rows)                                                                                                                                       |
| Auction demand · did anyone show up   | `supply.{auctions,recent_auctions}`                                                                                                                              |
| What this tab refuses                 | static                                                                                                                                                           |

Drop the house-only panels the board does not carry (`Summary`, `Mechanics`,
`Cross-Market`, `Provenance and legacy`) or fold their content into the board
panel that owns it. **The board is the spec: a panel it does not carry does not
ship on its tab.**

### t1 Fed — RESHAPE + one three-state panel

| Board panel                                  | Field                                                                                          | State                            |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------- |
| Four policy paths · who says what            | `/api/macro/policy` `.actual`/`.committee_projection`/`.dealer_expectations`/`.market_implied` | ⚠️ house `Policy Paths`          |
| **Per-meeting odds · market-implied**        | `.market_implied` — `path: null`, `missing_reason` set                                         | ❌ **absent entirely**           |
| Dealer expectations · the 3.63 dot           | `.dealer_expectations.path`                                                                    | ⚠️ house `<h3>`                  |
| Committee projections · the 3.80 dot         | `.committee_projection.path`                                                                   | ⚠️ house `<h3>`                  |
| State & confidence · the engine's own proof  | `snapshot.state`                                                                               | ⚠️ **see §4 — currently `null`** |
| Plumbing · the balance sheet behind the rate | `policy.plumbing`                                                                              | ⚠️ house `Mechanics`             |
| Next events                                  | `snapshot.events` (currently `n=0`)                                                            | ⚠️ house `Events`                |
| What this tab refuses                        | static                                                                                         | ✅                               |

`market_implied` arrives with `path: null` and a populated `missing_reason`. The
board's own invariant is three-state slots — so this panel ships **rendering the
refusal**, never omitted. An absent panel says "we don't cover this"; the field
says "we cover it and the publisher had nothing." Those are different claims.

### t0 Overview — BUILD, 11 panels, all bindable

| Board panel                               | Source                                                          |
| ----------------------------------------- | --------------------------------------------------------------- |
| State flips × confidence moves            | `/api/macro/{inflation,rates,usd,gold}` `.state` + confidence   |
| Market deltas · 1 week                    | `/api/rates/snapshot` live **and** `?as_of=` −7d (now possible) |
| Anchor letting go · gauge corr_60d        | `/api/gold/gauge` `.history_252d`                               |
| Four policy paths · who says what         | `/api/macro/policy`                                             |
| Contradiction feed · engine-reported      | domain `.contradictions`                                        |
| Cross-domain contradictions               | `/api/macro/snapshot` `.reasons` (n=2), `.domains` (n=3)        |
| Transmission health                       | gold gauge + `.correlation_history`                             |
| FOMC calendar × what the market prices    | `policy.market_implied` + `snapshot.events`                     |
| Confidence repair · what each event fixes | domain confidence terms                                         |
| Off-chain dimension · Energy              | static; links t6                                                |
| Boundary · what is NOT on this desk       | static refusal                                                  |

Note `/api/macro/snapshot` returns `domains: n=3` against four domain tabs. The
overview must render that as a three-state coverage fact, not silently show three.

---

## 4. Two decisions — TAKEN 2026-08-29 by the operator

**D1 — `rates_snapshot_state_block_enabled` defaults `False`.**
`src/uw_scan/config.py:223`. The live probe returns `state: null`, so board t1
panel 5 ("State & confidence · the engine's own proof") has no data to bind.
`page.tsx:60-66` deliberately does _not_ call `/api/macro/rates`, reasoning that
a second fetch "forks one answer into two requests that could disagree" — sound,
but it assumes the flag is on. The board names the fallback explicitly: _"if that
flag is off the same state is still reachable via `/api/macro/rates`."_
→ **DECIDED: take the board's named fallback** — cite `/api/macro/rates` beside
the snapshot. The operator's instruction was to get the board's data and
information onto the page rather than gate a panel behind a deployment flag. The
fallback binds real data on every environment with no config change, and it is
not a new pattern: tab 03 already cites the rates domain state beside its own for
the market-implied leg (`page.tsx:167-172`), settled separately so an outage in
the cited publisher costs one panel and not the tab. `page.tsx:60-66`'s
single-fetch argument holds only while the flag is on; with it off there is no
answer to fork.

**D2 — tab 00 collides with the sibling branch.**
`feat/macro-desk-tab-00` holds 2 unmerged commits and would conflict on
`web/components/macro/tabs.ts` and `web/app/macro/[tab]/page.tsx`.
→ **DECIDED: build t0 on this branch, absorbing the sibling's 2 commits.** The
board is the whole page and the desk ships it whole. The registry conflict is
resolved once, here, rather than twice.

---

## 5. Sequence

Each step is independently revertible and leaves the desk green.

| PR  | Scope                                                                                     | Panels | New endpoints                 |
| --- | ----------------------------------------------------------------------------------------- | -----: | ----------------------------- |
| 1   | t5 gold: bind `/api/gold/gauge`, split CB / western flows, input manifest                 |     +6 | 0 (`api.goldGauge()` wrapper) |
| 2   | t2 rates: nine board panels on `BoardPanel`, retire house sections                        |     +9 | 0                             |
| 3   | t1 fed: 8 board panels, `market_implied` three-state, state cited from `/api/macro/rates` |     +8 | 0                             |
| 4   | t0 overview — **here**, absorbing `feat/macro-desk-tab-00`                                |    +11 | 0                             |

PR 1 first because it is the only one that recovers information currently lost
(11 points where 19 exist, plus three unconsumed endpoints); PRs 2 and 3 move
information already on screen into the right
shape.

---

## 6. Acceptance

The board's own test, which reached neither the previous plan nor the code:

> every panel must answer at least one of Q1–Q7, or it gets deleted

- Every new panel is a `BoardPanel` with a non-empty `questions` tuple — a
  compile error otherwise.
- **A panel count test per tab**, asserting the board's number: t1=8, t2=9,
  t5=8, t0=11. This is the check that was missing; a missing panel currently
  fails nothing.
- Extend the existing e2e (`web/tests/e2e/macro-desk.spec.ts`) to assert
  presence of each board panel title per tab, not just HTTP 200.
- **The board's VALUES never bind.** Its figures froze at its capture instant.
  Every sentence carrying one is derived at render time and tested in both
  branches — as already done for `dollar-pair-read` / `gold-gauge-read`.
- `npm run typecheck`, `lint`, vitest, the posture lint, and the e2e suite green.

---

## 7. Recorded deviations from the board

| Board                                   | Here                                       | Why                                                   |
| --------------------------------------- | ------------------------------------------ | ----------------------------------------------------- |
| §⑨ `/api/rates/snapshot?as_of=` MISSING | exists                                     | Added after capture; verified live 2026-08-29         |
| §4.5 skip `/api/gold/gauge` (perf)      | bind it                                    | Re-measured 50ms, not expensive; buys 19 pts over 11  |
| t5 "corr_60d, daily"                    | plot corr_252d, labelled                   | Producer computes `window=252` only; the 60d cut does not exist |
| t8 ships as a tab                       | reachable at `/macro/notes`, off the strip | The board's own t8 says it does not ship              |
| t0 built on this branch                 | built on `feat/macro-desk-tab-00`          | Registry collision; D2                                |


---

## 8. Outcome — measured 2026-08-29

All 47 shippable board panels render on the live desk. Verified by fetching each
tab from the running dev server and matching the board's own panel titles, not by
reading the diff.

| Tab            | Board | Before | After | Commit     |
| -------------- | ----: | -----: | ----: | ---------- |
| t0 Overview    |    11 |      0 |    11 | `4fa16ccf` + `46617a7c` |
| t1 Fed         |     8 |      0 |     8 | `b4fca2c4` |
| t2 Rates       |     9 |      0 |     9 | `9b73f2f9` |
| t3 Inflation   |     4 |      4 |     4 | (already conformant) |
| t4 USD         |     2 |      2 |     2 | (already conformant) |
| t5 Gold        |     8 |      2 |     8 | `11088f1a` |
| t6 Energy      |     2 |      2 |     2 | (already conformant) |
| t7 Factors     |     3 |      3 |     3 | (already conformant) |
| **Total**      |**47** | **11** |**47** |            |

Zero new endpoints, as predicted. Three previously-unconsumed data paths are now
bound: `/api/gold/gauge`, `/api/macro/rates` `sub_states`, and `/api/macro/policy`
`market_implied`.

Gates at the final commit: typecheck clean, **984 unit tests pass**, posture lint
clean, eslint clean, all 9 routes HTTP 200.

### What is NOT done

- **`/api/gold/lenses/*` and `/api/gold/inputs/*` remain unconsumed.** The board's
  §⑩ P2.2 names three unconsumed gold routes; one is now bound. `inputs/{id}`
  carries real depth (`DFII10` 1293 points) and would turn the input manifest from
  a list into a set of inspectable series. Deferred, not forgotten.
- **The board's t5 anchor-decay panel cannot be built as specified.** Not a port
  gap — the desk neither computes nor retains a 60-day correlation series. The fix
  is in `reports/gold_posture.py`.
- **No e2e run against a production build.** Unit and route-level checks only.
- **Everything verified against `option_wizard_local`, never the mini.**

### Three corrections this plan made to itself

Recorded because each was wrong in a way that would have shipped:

1. `/api/rates/snapshot?as_of=` was called MISSING by the board and **exists**;
   any work sequenced around that blocker was dead work.
2. "261 points instead of 3" was stated twice and is **19 vs 11** — the gauge's
   261 dates carry 19 values. The page printed the right numbers while the plan
   carried the wrong ones, because the panel derives them at render time.
3. The gold perf deviation (§4.5, "262 correlation gauges per request") measured
   **50ms** on re-test. Real when written, stale when inherited.

---

## §9 The design port — 2026-08-29, second pass

§8 above closed on **panel inventory**: 47/47 board panels present, every one bound
to live data. That was the wrong finish line. The operator's words:

> "the 1 to 1 same design and data and binding as the artifact"

Binding the information and not the design is invisible to every check that was
run, which is why it survived a pass that reported 47/47. Measured rather than
argued: `web/scripts/board-pixel-compare.mjs`.

### What the second pass found

| Tab | Before | Now |
| --- | --- | --- |
| t0 Overview | house inline styles, **0** board classes, no zones, no chain rail | 4 zones, 11 `.panel`s, `.chain` rail |
| t5 Gold | 9 full-width hairline bands, house panel idiom | board grid: g2/g2/g3 + manifest, 8 `BoardPanel`s |
| t1 Fed | **0** grids — every panel full-width | 3 × `grid g2`, zone banners |
| t2 Rates | **0** grids — 7839px against the board's 3982 | `g3` + `g3` + `g2`, 6764px |
| desk-wide | no provenance key, no Q1–Q7 strip | `BoardLegend` in the layout |

`board.css` gained the half of the grammar the first port skipped — `.zone`,
`.chain`/`.node`/`.arrow`/`.edge-note`, `.contra`, `.conf`, `.meter`, `.meet`/`.pbar`,
`.chart`, `.cap`, `.lgd`, `.ghost`, `.g4`, `.dir`, `ul.tight`, `.chip`/`.mast-meta`,
`.legend-strip`/`.pmq`.

### Why the comparison is not a bitmap diff

The board's panels carry mock values frozen at its capture instant; the desk derives
its own at render time, which is a rule of this port. A pixel subtraction is therefore
dominated by digits and prose and says nothing about whether the design was ported —
two pages can differ in every pixel and share a design. The script compares grammar
coverage, computed style per selector, and full-page screenshots.

### What it caught that reading the code did not

- **The body type scale.** Board 13.5px/1.55, argon 13px/1.5, inherited by everything.
  The single largest source of drift, and invisible in any per-component review.
- **Every board table cell was rendering in mono.** `globals.css` styles bare `td` at
  mono/12px; the board declares neither and inherits sans/12.5px — and an inherited
  value always loses to a declaration however weak its specificity.
- **Tabs 01/02 had no grid at all.** The class-coverage check missed this because
  `.grid.g2` *did* render on the desk — on other tabs. Coverage must be per-tab.
- **The desk had no key.** Sixty-odd `REAL`/`COMPUTED`/`PLANNED` and `Q1`–`Q7` chips
  with nothing on the page defining them, while `BoardPanel` encodes those same
  questions as a required type.

### Result

- Grammar coverage: **40 of 41** probed board elements render.
- Computed-style diffs: **65 → 15**, all remaining traced to mock-vs-live data or to
  the two pages opening with a different first instance of a class.
- Height ratio (live ÷ board): gold 1.03, usd 1.08, overview 1.13, inflation 1.14,
  energy 1.27, fed 1.34, factors 1.43, rates 1.70. The two outliers are content the
  board's mock does not carry.

### The one element that does not render, verified

`.pbar`, the per-meeting probability bar. Not an oversight and not deferred:
`/api/macro/policy` carries `probability_distribution` on **0 of its 21 points across
all four lanes**, the market-implied lane publishes `missing_reason` instead of a path,
and `/api/rates/snapshot` has no `market_implied` block. There is no probability on
this desk to split a bar with, so t0 and t1 state the refusal in the publisher's own
words. The CSS stays so the bar's return is a markup change.

### Deliberate departures from the board's markup

Both are element choices, not visual ones, and both are recorded beside the code:
a zone label is an `<h2 class="zl">` and a rates panel is a `<section class="panel">`.
The class carries every pixel; the element carries a landmark a screen reader can jump
between.

### Reproduce

```bash
cd web && node scripts/board-pixel-compare.mjs   # needs the dev server on :3002
# report.json + 16 screenshots -> output/playwright/board-compare/
```
