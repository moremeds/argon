# Macro desk — board conformance audit

**Date:** 2026-08-28
**Board (the spec):** artifact `dde15f29-728e-43e9-86d5-9ab688df4853` — "Argon Macro Desk", updated 2026-08-27
**Shipped:** `feat/macro-desk-tab-00` (tab 00) and `feat/macro-desk-tabs-03-05` (tabs 01–05) — both merged since (v0.13.1)
**Question:** which of the board's designed panels actually reached the desk

## Why this exists

The port plan (`docs/superpowers/archive/plans/2026-08-27-macro-desk-page-port.md`) §1 declares a
non-goal — _"**No new analytics.** Tabs 00–05 are a presentation merge"_ — and §3 binds tab
03 to one request (`/api/macro/inflation`) and tab 04 to one (`/api/macro/usd`). One state
endpoint renders one generic state card. The board's tab 03 specifies four distinct panels.
The plan and the board disagree, and the plan won by default because it was the document
being executed.

This audit measures the size of that disagreement before anything is rebuilt.

## Method

- **Board panels** counted as `<h3>` elements inside each `section[role="tabpanel"]`
  (`#t0`–`#t5`) of the saved artifact HTML. This is a **proxy**: a board panel without an
  h3 is undercounted. Treat the counts as ±1, not exact.
- **Shipped panels** read two ways: headings scraped from the live dev instance
  (`http://127.0.0.1:3002`, local DB, 2026-08-28), and component composition read from
  source. Tabs 01–05 were rendered; tab 00 was read from source only — it lives on the
  sibling branch and was not running.
- Status is `present` (the board's panel exists and answers the same question),
  `partial` (the data is on the tab but not as the designed panel, or a different cut of
  it), `absent`, or `misplaced` (present on a different tab than the board assigns).

## Conformance

| Board tab                | Panels | present | partial | absent / misplaced |
| ------------------------ | -----: | ------: | ------: | -----------------: |
| t0 Overview · Daily Loop |     16 |       8 |       1 |                  7 |
| t1 Fed · Policy          |      8 |       7 |       0 |                  1 |
| t2 Rates · Curve         |      9 |       6 |       1 |        2 misplaced |
| **t3 Inflation**         |  **4** |   **0** |   **1** |              **3** |
| **t4 US Dollar**         |  **2** |   **0** |   **0** |              **2** |
| t5 Gold                  |      8 |       5 |       3 |                  0 |
| **total**                | **47** |  **26** |   **6** |             **15** |

### t3 Inflation — 0 of 4

Board: _arithmetic of confidence · falsifier window/repair table · realized inflation ·
inflation expectations_. Shipped: one `DomainStateTab` card (`WELL_ABOVE_TARGET · FLAT ·
CONFIDENCE 42%`, two metric rows, two contradiction lines, evidence-count disclosure) plus
a refusal panel. The card's metric rows carry realized-inflation _numbers_, which is why
this scores one partial — but a two-row strip is not the board's realized-inflation panel,
and there is no expectations panel, no confidence arithmetic, no repair table.

`ConfidenceArithmetic` **exists** and was lifted out of the rates subtree in P5 — it renders
on tab 00, not here, where the board puts it ("The arithmetic of confidence · why only 0.37"
is a t3 heading).

### t4 US Dollar — 0 of 2

Board: _nominal vs real, a dollar pair in reverse · upstream citation, chain integrity_.
Shipped: the same generic card plus a refusal panel. Neither designed panel exists. This is
the smallest board tab and the only one at zero with nothing partial.

### t5 Gold — content largely present, arrangement not

Five board panels are genuinely there (three lenses, CB 12M net in three buckets
STRATEGIC/TACTICAL/DIVERSIFIER, western institutional L1 detail, L2 cyclical, input
manifest via `DataAuditFooter`). Three are partial:

- **Transmission gauge · correlation collapse** — exists as one tile in the KPI strip
  (`GAUGE REGIME · SUSPENDED`), not as the panel the board opens the tab with.
- **Anchor decay · gauge corr_60d, daily** — shipped renders `CORRELATION HISTORY · 252D
ROLLING`. Different window, different cut.
- **Expression cost · what the option market charges** — exists as the `UW 25Δ SKEW` card
  inside lens 1, not as a first-class panel.

So gold's divergence is **framing**, not absence: the board leads with the transmission
question and organizes around it; the shipped tab is the Gold Compass page moved intact and
organized by lens.

### t1 / t2 — near-complete, two structural slips

Both tabs carry almost everything the board specifies, plus extras the board does not
(`Provenance and legacy`, `Source Freshness`). Two real deviations:

- **`/macro/fed` has no refusal panel.** The board gives t1 a "What this tab refuses"; the
  shipped fed tab has none (measured: 0 occurrences; `/macro/rates` has it, as do 03 and 04).
- **Supply and auction demand are on the wrong tab.** The board puts `Supply SUB-STATE` and
  `Auction demand · did anyone show up` on t2 (Rates · Curve). Shipped renders `Supply /
Recent auctions / Issuance & fiscal` on `/macro/fed`.

### t0 Overview — 8 of 16

Present: the four chain-node state cards, contradiction feed, cross-domain contradictions,
transmission health, and the daily loop. Absent: market deltas (1 week), anchor letting go
(corr_60d), four policy paths repeated at desk level, FOMC calendar × market pricing,
confidence repair table, and both energy blocks. `Boundary · what is NOT on this desk` is
partial via `ChainRefusal`.

## Two findings outside the panel count

1. **The Q1–Q7 acceptance test did not survive the port.** The board's design notes state
   the rule plainly: _"The seven questions are the acceptance test: every panel must answer
   at least one, or it gets deleted."_ Neither the plan nor the code carries it. Nothing
   maps a shipped panel to a question, so nothing can fail the test.
2. **Tab 08 ships against the board's instruction.** The board's t8 says _"This tab is for
   you (the operator) and does not ship on the final page."_ The plan registered it as tab
   08 and `DESIGN NOTES` is in the live tab bar.

## What I did not verify

- Panel **content** correctness — this audit matches panels by question answered, not by
  whether each renders the right numbers. A panel counted `present` may still be wrong
  inside.
- Tab 00 was read **from source**, not rendered. Its eight present panels are inferred from
  component composition, one confidence level below the rendered tabs.
- Board panels lacking an `<h3>` are not counted; the board's own claim is 58 panels across
  9 tabs, against the 47 this method finds across 6 tabs — the remainder is mostly t6/t7/t8,
  but some part of the gap may be uncounted panels inside t0–t5.
- The board's **visual** design (palette, spacing, type scale) was not compared at all.
  Only panel presence.

## Reproduce

```bash
# 1. run the desk (API + web only, no workers)
uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src &
cd web && NEXT_INTERNAL_API_BASE=http://127.0.0.1:8400 npx next dev --port 3002 --webpack &

# 2. shipped headings per tab
node /path/to/audit.mjs        # scratchpad script; renders 01-05, dumps h1-h4

# 3. board panels per tab
#    read the artifact, then count h3 inside each section[role="tabpanel"]
```

Artifact read via `Artifact action:"read" url:".../dde15f29-728e-43e9-86d5-9ab688df4853"`.

---

## Closure — what the build changed (same day)

The audit above is the measurement; this section records what was done about it and what
was deliberately not. Commits `bee947cd`…`c886b55d` on `feat/macro-desk-tabs-03-05`.

| Audit finding                      | Disposition                                                                              |
| ---------------------------------- | ---------------------------------------------------------------------------------------- |
| t3 Inflation, 0 of 4               | **Built.** All four render; verified live at `/macro/inflation`.                         |
| t4 US Dollar, 0 of 2               | **Built.** Both render; verified live at `/macro/usd`.                                   |
| t1 missing its refusal panel       | **Built.** Four invariants that existed only as code comments and test assertions.       |
| t2 missing Supply / Auction demand | **Moved** from tab 01. One `SupplySection` covers both board panels.                     |
| t5 framing                         | **Reordered** to the board's sequence: gauge opens the tab, expression cost gets a band. |
| Tab 08 ships against the board     | **Unlisted.** Registered and reachable at `/macro/notes`, absent from the strip.         |
| Q1–Q7 acceptance test absent       | **Enforced.** Non-empty tuple on `BoardPanel`, `data-questions` on gold, e2e over both.  |
| t0 Overview, 8 of 16               | **Not done here** — see below.                                                           |

### The one thing deliberately left

**Tab 00 is not on this branch.** It lives on the sibling `feat/macro-desk-tab-00`
(2 commits, unmerged), and `VALID_TABS` here has no overview entry at all. Building its
panels in this worktree would duplicate that branch and collide on `tabs.ts` and
`app/macro/[tab]/page.tsx` at merge. Of its 7 absences, 3 are buildable against data that
already exists — the repeated policy paths, the anchor-letting-go read, and the confidence
repair table — and the third is now a shared component (`ConfidenceRepairPanel`) that tab
00 can consume when the branches meet. The other 4 need data the desk does not ingest
(FOMC calendar, GVZ/VIX/HY-OAS deltas, both energy blocks, which the board itself marks as
proposals).

### Two deferrals, stated on the page rather than dropped

- **Gold's anchor-decay chart** wants the gauge's 60-day correlation daily; the producer
  computes that history at `window=252` only (`reports/gold_posture.py`). The heading names
  the window it has and a note names the one that was asked for.
- **`T5YIFR`** (the board's 5y5y forward row) is carried by no published domain state. The
  expectations panel names it as missing rather than sourcing it from somewhere uncited.

### Verification

`npm run typecheck` · `npm run lint` · `node scripts/lint-gold-copy.mjs` all clean.
940 vitest tests pass (up from 930). 37 Playwright specs across
`macro-desk`/`macro-replay`/`macro-rates-state`/`macro-chart-scale`/`gold-page`/
`gold-redirect`/`rates-redirect` pass against the running instance.

Screenshots of the final state: `output/playwright/macro-tab-{fed,rates,inflation,usd,gold}.png`.
