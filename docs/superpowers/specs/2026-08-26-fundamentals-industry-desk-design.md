# Fundamentals industry desk — routing desk over underwriting nodes

**Status:** approved in conversation 2026-08-26; not yet implemented. Phasing in §8;
nothing below exists on `main` unless a path says so.

**Relationship:** this spec is the _presentation and daily-data layer_ over the
Fundamental PM Research System backend (PR #383, `feat/fundamental-pm-research-system`,
CI green, `CONFLICTING` with `main` as of 2026-08-26) and the chain-analysis-node design
(`docs/superpowers/specs/2026-08-26-chain-analysis-node-design.md`, at time of writing
an **uncommitted file in `.worktrees/fundamental-pm-research-system/`**). It consumes
that backend — taxonomy (`storage/research_taxonomy.py`, migrations 139–140),
exposure (`company_exposure`), typed events (`storage/research_events.py`), versioned
reports (`storage/research_reports.py`), the node catalogue
(`src/uw_scan/fundamentals/chain_nodes.py` + `worker/jobs/research_report_assemble.py`)
— and must not fork or re-implement any of it.

**Audience:** the operator, working as a hedge-fund-style fundamental PM. The measure of
every screen is whether that PM opens it again next week.

**Origin:** generalizes the hand-built "Optical Chain Desk" artifact (16 names, 5
layers, Q1–Q8 question ladder, frozen JSON snapshot, published 2026-08-26) into a
systematic argon surface, corrected by an adversarial PM-persona review of that
artifact's information architecture.

---

## 1. First-principles frame

A fundamental PM covering AI/semi runs four loops at different cadences:

1. **Thesis maintenance** (weekly/quarterly) — is the capex cycle intact; where in the
   chain is pricing power migrating.
2. **Expression** (episodic) — which names carry the layer exposure I want, at what
   price against their own history.
3. **Falsification watch** (daily in season) — what prints next; which number breaks
   the thesis; what did last night's print change.
4. **Coverage triage** (daily) — which of my names need attention today.

The Optical Chain Desk artifact is loop 1 for one sub-chain. The desk hierarchy exists
to serve all four.

**Routing vs underwriting.** The first design draft proposed one question ladder
rendered at two grains (chains at the industry level, names at the deep-dive level).
The PM red-team rejected it: the two levels differ in _kind_, not grain. The industry
page's job is **routing** — where is the profit pool migrating, what prints next in
read-through order, which sub-chain deserves a deep dive. The name-grain page's job is
**underwriting** — customer/program concentration, qualification status, balance-sheet
capacity, dilution. They share almost no questions, and forcing one ladder onto both
produces filler at each level; filler is what trains the operator to stop opening a
page. So: **one engine, one config contract, two page types.**

**The daily spine.** Quarterly filings rendered on a nightly page look identical for
eleven weeks out of thirteen. Without a "what changed since you last looked" rail the
desk is a report, not a desk. The delta rail (§4a) and the chain-ordered calendar (§4b)
are the two elements that change daily, and they anchor the page.

## 2. Hierarchy and routes

```
/fundamentals                      section index (thin; redirects to ai-semi while it
                                   is the only section) + Radar as the triage tab
/fundamentals/ai-semi              industry desk — ROUTING; live warm-store views
/fundamentals/ai-semi/[node]       deep dive — UNDERWRITING; latest assembled versioned
                                   node report (replayable, as-of-able) + live calendar strip
```

- **Section** = a research domain of interest. `ai-semi` is the first and only one;
  "fundamental analysis" as a concept is deliberately bigger than what argon
  instantiates. A new section is taxonomy/config rows, not code.
- **Node** = one chain analysed by the fixed component set of the chain-node design.
  `Optical-Communication` (光模块) ships first. The five datacenter chains
  (Generation/Nuclear, Power/Electrical, EPC/Construction, Cooling/Thermal,
  DC-REIT/Colo) are the measured-buildable siblings: every member is already in the
  universe and 42 of 44 carry statements (measured 2026-08-26; DC-REIT/Colo at 4/6 is
  the one gap). Standing one up costs taxonomy rows and zero incremental vendor calls.
- **Extension contract:** a new section or node = `research_chains` layer rows +
  `chain_membership` rows (+ optional `chain_segment_alias`), no new assembler and no
  new page code. This is the "fixate the flow once" requirement made testable: if a
  new node needs a code change, the contract is broken.
- The existing PR #383 routes fold in rather than multiply: Radar
  (`web/app/radar/`) becomes the triage tab under `/fundamentals`; the `/chains` pages
  and `ChainMatrix.tsx` are raw material for the industry desk; `/reports` +
  `ReportView.tsx` is the rendering substrate for `[node]`.

**Two split renders, not one merged one (will bite):** the industry desk reads _live_
warm-store views because routing wants the newest state; the node page renders a
_stored versioned report_ because underwriting wants replayable, citable claims — a
report replays by reading its stored blocks, never by re-assembling
(`storage/research_reports.py` rule). Do not "simplify" the node page into live
queries: that silently converts every historical view into today's answer wearing an
old version number.

## 3. Industry desk content (routing), in priority order

**(a) Delta rail — the daily spine, top of page.** What changed since the operator
last looked: filings landed, valuation-band entries/exits, implied-move shifts,
coverage changes, cross-section-bucket flips. Driven by the typed event ledger
(`research_events` + `worker/jobs/research_events_derive.py`) with new change-event
classes (§6-iv). Events carry both clocks (`occurred_at`, `first_known_at`); the rail
orders by `first_known_at` because "what changed" is a question about the desk's
knowledge, not the world's.

**(b) Earnings calendar sorted by chain position — the daily-open screen.** Next
prints across the whole section, ordered upstream→downstream by `layer_rank`
(semicap → foundry → chips → optical/power → hyperscaler), because chain order is
read-through order — a generic calendar cannot say that. Per row: date, session,
options-implied move, last-4 print reactions, own-history valuation percentile.
Requires the durable calendar + reactions + implied-move spine (§6); none of the
three exists on `main` today.

**(c) Chain × metric matrix.** Per chain: revenue YoY, gross-margin trajectory,
valuation-percentile dots, coverage. Rules, each one a PM red-team verdict:

- **Median + per-name dots, never revenue-weighted.** A revenue-weighted "optical"
  margin is ANET's switch margin wearing COHR's label; the weighted aggregate was
  measured as actively misleading and is banned.
- **No dollar sums over many-to-many membership.** `chain_membership` is grained
  `(chain, layer, ticker)`; a name in two layers is two rows, and membership is
  many-to-many across chains (taxonomy v1: 39 chains, 316 memberships — e.g. COHR
  sits in both Components and Modules). Any count dedupes by ticker; any dollar
  aggregate requires a
  declared primary chain or is refused outright. A double-counted layer total is
  caught by the operator in sixty seconds and poisons trust in every other number.
- **Coverage names the missing tickers.** "12/18" is decoration; "missing: COHR,
  LITE" is actionable. Never render a bare n/N.
- **Reported/awaiting cohort split.** `fundamental_scores.as_of` is a cross-section
  identifier, not a freshness stamp (chain-node design §5). When a chain's members
  straddle two buckets, render two cohorts, never a merged list; the straddle is
  reporting season and collapses on its own.
- **Hatched abstentions, never blank.** An empty cell states which of the six result
  states it is in (`models/radar.py`); `no_compatible_run` is not `no_coverage`.
- Every cell links to its node page or member list; every member links to
  `/stock/[ticker]`.

**(d) Profit-pool migration.** Is gross profit migrating between layers (chips →
power/networking) — median-based, descriptive. **No propagation or lead-lag claims:**
the hyperscaler-capex → supplier-revenue timing edge was tested and did not validate
(`docs/research/2026-08-13-ai-capex-demand-ledger/`, headline 0.59 collapsing to 0.25
matched-growth, control failed in the relevant window). The page may show layers side
by side; it may not draw arrows.

**(e) Hyperscaler capex — demoted to a context strip.** It is on every sell-side deck
(zero edge) and sign-inverted for L4/L5, where rising capex is a cost line, not
demand. The strip says so. It is not the page header the artifact made it.

**(f) Limits — computed, not prose.** Coverage integrity (NI reconciliation pass
rate with the worst offenders named, §6-vi), membership semantics (semantic vs
economic, with the exposure evidence state), and the withheld-composite sentence: the
internal cross-sectional composite correlates 0.89 with its own growth input and is
therefore not shown. Publishing the reason a number is absent is worth more trust
than any number that could be added.

**Anti-requirements (hard, test-backed where possible):**

- **No cross-sectional ranking or composite anywhere on the desk.** Measured basis:
  cross-sectional composite rank IC 0.039 (t 2.67) at full breadth but a disguised
  growth screen; cross-sectional value measured INVERTED (`book_to_price` IC −0.0365,
  t −2.32) while own-history value is the one thing that works (`sales_to_ev`
  within-ticker IC +0.0744, t 5.77). The macro desk and the scanner Value sub-tab
  already codify this discipline (no-composite comment in `MacroDesk`; ValueSubTab
  LISTS and never RANKS); the fundamentals desk inherits it.
- **Per-chain valuation percentiles are presentations of NAME facts.** The measured
  rule is within-ticker; a "chain percentile distribution" is a display of name-level
  own-history positions and must never be spoken of as a chain property.
- **Inventory divergence is name-grain only.** At chain grain it was judged harmful:
  stocking ahead of a ramp and ahead of a bust are indistinguishable in aggregate,
  and foundry WIP behaves nothing like fabless finished goods. The industry desk does
  not carry an inventory panel; the node pages do.

## 4. Deep-dive content (underwriting), per node

The artifact's Q1–Q8 ladder at name grain survives as the skeleton — demand anchor,
is-it-reaching-the-names, who-gets-paid, inventory risk, the master name table,
priced-in, what-lands-next, limits — rendered from the node's assembled report blocks
plus a live calendar strip. Additions over the artifact:

- **Name-grain inventory + DIO** (`inventory` is captured in
  `fundamental_statement_obs.raw_jsonb` today but surfaced nowhere in production —
  §6-v productionizes it).
- **Diluted share count YoY + SBC/revenue** — mandatory in a universe containing
  serial diluters; income-statement data already ingested, feature not yet derived.
- **Exposure shares with `is_member`** and the open alias questions surfaced, not
  silently corrected: APH's 61.5% rides an over-broad `communicationssolutions` alias
  on a non-member; CIEN's 1.5% is its smallest segment while the same filing
  discloses better tags (81% segment-axis, 70% product-axis). Changing an alias rule
  changes a published number — operator decision, visible on the page until made.
- **Click-through from every figure to the filed line item** — ticker, fiscal period,
  filing date, raw value. The PM trust ranking put this first: one untraceable number
  kills the page; traceability survives several wrong ones.
- **As-of replay** — the report system already versions and replays; the page exposes
  it. Trust builder #2, and the thing commercial screens get wrong.

What a node page does **not** attempt: ASP/mix, capacity, lead times, qualification
status — real underwriting inputs with no filings-derivable source; absence is stated
in the node's limits block rather than proxied.

## 5. Daily data spine — new tables and jobs

All read-time zero-vendor-call; every job accrues into the warm store on the existing
worker cadence pattern. Names below are proposals; migration numbers assigned at
implementation time (after the PR #383 chain lands, to avoid renumbering).

| #   | What                                                                                    | Today                                                                                                                                                                                                             | Change                                                                                                                                                                                                                                           |
| --- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| i   | **Durable earnings calendar** — `(ticker, report_date, session, source)` accruing daily | `sources/earnings_calendar.py` returns a transient same-day symbol set that only triggers `fundamental_ingest_daily`; nothing durable exists                                                                      | New table + daily persist step riding the existing fetch; carries the ~2% `report_time: "unknown"` names as `session = null`, never dropped                                                                                                      |
| ii  | **Earnings reaction history** — % move per print                                        | `uw_positioning.earn_reactions_positive/total` stores a win-count over the last 4, watchlist names only, no magnitude, no dates                                                                                   | Compute from calendar dates × massive daily OHLC already in the warm store; backfillable from OHLC history; persisted per print                                                                                                                  |
| iii | **Implied move** — per name with a known next print                                     | Nothing persisted; the artifact's `move_usd` came from a lost ad hoc pull                                                                                                                                         | Derive from `option_surface_grid_daily` ATM straddle (IV-based approximation); coverage labeled honestly — the surface accrues 2025-12-26→present, cohort/watchlist names only, and a missing implied move renders as "not covered", never blank |
| iv  | **Change-event classes** for the delta rail                                             | Six event classes live in `research_events`; eight killed classes refuse writes                                                                                                                                   | New classes: filing-landed, band-entry/exit, implied-move-shift, coverage-change, bucket-flip. Additions go through the same discovery gate that killed the eight                                                                                |
| v   | **Features**: inventory/DIO, diluted shares, SBC                                        | Raw fields pass through `raw_jsonb` unread; `features.py` derives neither                                                                                                                                         | Add to `fundamentals/features.py` with the standard validity/window treatment; DIO = inventory/COGS × 91.25 as in the research script, now versioned                                                                                             |
| vi  | **NI cross-statement reconciliation** as a production integrity check                   | `statements.py check_violations()` covers balance-sheet identity + one gross-profit anomaly; the income-vs-cashflow NI check (tolerance 1%) lives only in the research script (artifact measured 140 ok / 15 bad) | Productionize into the integrity path; worst offenders feed the desk limits block (§3f) by name                                                                                                                                                  |
| vii | **Optical `company_type` routing fix**                                                  | Chain-sector vocabulary routes most optical names to `power_infra`/EV-EBITDA (flagged in the research VERDICT; the percentile is valid, the label is wrong)                                                       | Correct routing via the existing `TICKER_TO_TYPE`/`SECTOR_TO_TYPE` maps in `worker/jobs/fundamental_anchors.py`; a changed method changes a published band — treat as a versioned parameter change                                               |

## 6. Data-provenance debt this spec retires

The artifact was assembled from
`docs/research/2026-08-26-optical-chain-pm-desk/` — which is **untracked** inside the
PR #383 worktree, so the "reproduce" path in its own VERDICT.md is not in git at all.
Worse, `scripts/page_data.py` imports an `alldata.json` that exists nowhere in the
repo, the worktree, or git history — it was the sole source of the calendar, implied
moves, reaction history, and part of the exposures on the published page, and it is
unreconstructable. `prod_pull.sh` also pulled `company_exposure` into a `.tsv` that
nothing ever read. This is precisely the failure mode the standing persistence rule
exists to prevent. The spine in §5 gives every one of those inputs a durable, jobs-fed
home; the research dir itself must be committed (P1) so the one-off that seeded this
design is at least archaeologically recoverable.

## 7. Phasing

- **P1 — land the foundation.** Rebase/merge PR #383 (CI green; only the conflict
  with `main` blocks it). Commit the optical research dir. Seed the five
  datacenter-chain layer rows (measured free). Fold the rewrite session's in-flight
  chain-node work into the same landing.
- **P2 — data spine.** §5 i–vii: tables, jobs, backfills (reaction history backfills
  from OHLC; calendar accrues forward-only — every unpersisted day is lost, same
  shape as the option-surface constraint).
- **P3 — pages.** The optical node page first (the report substrate already renders;
  this is presentation), then the industry desk with delta rail and chain-ordered
  calendar.
- **P4 — direction, not commitment.** Guidance extraction from 8-K press releases on
  the existing `sec_filing_index` (`sources/sec_submissions.py`, 73,994 true-PIT
  claims over 396/401 tickers) — the PM red-team's single highest-ROI ask: in semis
  the guide, not the print, drives the reaction, and unlike consensus it is
  filings-derivable. And agent-written narrative over the computed blocks (Trade
  Insights AI runner pattern: persisted rows, exact prompt + payload + resolved model),
  replacing template prose only where a stored snapshot pins what the agent described.

## 8. Open questions

1. **APH / CIEN alias rules** — both change published numbers; operator decision,
   surfaced on the node page until made (chain-node design §4).
2. **`chain_aggregate` mixes cross-sections** — restrict to the dominant bucket and
   say so, or abstain on a straddle (chain-node design open item 2).
3. **Chain shape emits no `risks` block** — a `stale_result` breach is visible on a
   company ask and silent on a chain ask (open item 1); the desk limits block
   partially compensates but does not resolve it.
4. **DC-REIT/Colo statements gap (4/6)** — accept partial coverage with named
   missing tickers, or hold that node until ingested.
5. **Does `/fundamentals` absorb the scanner Value sub-tab link** or merely
   cross-link it? (Same discipline either way; question is navigation only.)

## 9. Decision log (2026-08-26 conversation)

1. **Fully computed now; agents later.** Template prose with computed slots; no
   AI-generated narrative in the read path at this stage.
2. **Approach A — one grain-parametric desk engine — approved, then amended** by the
   PM red-team's routing/underwriting split: one engine and one extension contract,
   but level-specific question sets, not one ladder at two grains.
3. **Consume the PR #383 + chain-node backend; do not redesign it.** This spec is
   the presentation and data-spine layer, and is to be handed to the rewrite session
   as its target when its current pass completes.
4. **Phasing P1→P4 approved** (foundation merge → data spine → pages → guidance/agents).
5. Scope now: AI/semi section, optical node first, datacenter chains next — with the
   extension contract (§2) as the acceptance test that the flow is truly fixated.
