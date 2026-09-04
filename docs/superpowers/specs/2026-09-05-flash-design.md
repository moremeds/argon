# Flash — the option-wizard daily brief as a page in argon

Status: Tasks 1–11 shipped on `feat/flash`. Not yet deployed to the mini.
Date: 2026-09-05
Plan: `docs/superpowers/plans/2026-09-05-flash.md` · Mock: `docs/superpowers/plans/2026-09-05-flash-mock.html`

## 1. What Flash is, and is not

Flash is a **read surface over structured agent runs**. helium, on the Mac mini,
produces the option-wizard daily options brief; it POSTs the run to argon, and
argon renders it as a page under the sidebar entry **Flash** (subtitle
*agent news flash*), grouped by trading week.

It exists because three email designs were rejected on looks, and the root
cause was email: Gmail's 102 KB clip, table-cell charts, forced dark-mode
inversion. A page in argon removes all of that and gives history for free.

It is **not** an editor, not an order ticket, not a re-run button, not mobile,
not email. It shows no quantities, no position sizes and no account state
anywhere — only per-contract economics. There is no comment box and no
per-candidate history view: nothing on this page writes.

## 2. Three layers, and where a second tenant plugs in

Only the top layer knows what a flash is.

| Layer | Files | Knows |
| --- | --- | --- |
| 1. Storage | `storage/migrations/148_agent_runs.sql`, `storage/agent_runs.py` | rows: `(tenant, kind, run_day, version_no)`, idempotent on `(tenant, run_id)`; `view_jsonb` opaque |
| 2. Transport | `models/agent_runs.py`, `api/routers/agent_runs.py` | one POST behind a bearer token, four reads, every one parameterised by `tenant` |
| 3. Flash | `web/app/flash/**`, `web/components/flash/**`, `web/lib/flash/**` | tenant `option-wizard`; kinds `premarket \| intraday \| close \| weekly \| frank` |

`kind` is an opaque, writer-chosen label. Nothing below layer 3 switches on its
value, enumerates the legal set, or interprets the document.
`tests/unit/test_agent_runs_neutrality.py` fails the build if a tenant word
(`flash`, `premarket`, `strike`, …) appears in layers 1–2 outside a docstring.

**A second tenant is a new view and nothing else** — a `web/app/<tenant>/**`
tree plus its own `kinds.ts`. It touches no migration, no repository method, no
model, no route, and no auth. The one thing it would add below layer 3, the day
tenants stop all running inside helium, is an `agent_runs.written_by` column —
not a second auth scheme.

## 3. Information architecture

```
week  →  5 trading days  +  1 weekly summary & outlook
day   →  premarket (THE report)  +  intraday, close (supplements)
week  →  Frank 复盘 (an external weekly review — supplements the WEEKLY, not a day)
```

- **`/flash`** is a doorway. It resolves the newest recorded week and redirects,
  so there is exactly one week view and no second "current week" route to
  disagree with it.
- **`/flash/[week]`** is the weekly summary: five one-liner rows with per-day
  run counts, then `Outlook · week ahead` and `Frank 复盘` side by side.
- **`/flash/[week]/[day]?phase=`** is one day, one phase.

**Day is a segment, phase is a search param.** The week strip and the tab strip
both live on the day page and read the same week index; a phase segment would
make every tab click a different route with its own loading state for data it
already has. The day is a different document; the phase is a view of the same
fetch.

**Week-scoped runs are found through the index, never by date arithmetic.**
helium sends `week_key` explicitly and files each run under its own `run_day` —
a Frank 复盘 for W36 carries `run_day = 2026-09-07`, the Monday *after* the week
it reviews. The week route therefore reads `/api/agent-runs/week/{week_key}`,
picks the newest `weekly` and `frank` rows out of that index, and fetches each
by its own `(kind, run_day)`. Asking for `(frank, friday)` finds nothing and
renders "No review attached" over a review that exists.

## 4. The data contract

`schema_version` is a column, not a comment. `asBriefView(run)` returns `null`
when `run.schema_version !== SUPPORTED_SCHEMA_VERSION`, and the caller then
**says which version arrived and which this build renders** — a silently blank
page is the one outcome a versioned document exists to prevent.

Argon does **not** validate the view's shape at ingest. Only the envelope is
validated (`models/agent_runs.py`): identity and the fields the store's CHECK
constraints also enforce. Validating the document would couple the transport to
one tenant, and a helium deploy adding a field would fail at argon's door
instead of rendering one section short.

**`web/components/flash/view.ts` is hand-written on purpose.** The two repos
deploy independently. A generated binding would turn every helium field rename
into an argon *build* failure on helium's release schedule; a hand-written
mirror turns it into a rendered gap argon can fix within the hour. Every field
is optional except `date`.

## 5. Layout

Desktop wide, argon dark tokens (`web/app/globals.css`, recipes in `DESIGN.md`).
Inter for prose, IBM Plex Mono for every label, id, timestamp and number.
`flash.module.css` declares six locals on `.flash` (`--rail`, `--warn`,
`--chart-grid`, two signed fills) and takes everything else from globals.

- **Grid** — `minmax(0,1fr) var(--rail)`, `--rail: 420px`, → 360px at ≤1440px,
  → one column at ≤1240px. Supplements use `minmax(0,1fr) minmax(0,440px)`.
- **Panel** is the only container; `<h3>` plus an optional right-aligned `tail`.
- **Tile** — label / value / change, uniform in every phase, at most 7 per row
  and rows balanced (8 items go 4+4, never 7+1). **The change slot is always
  rendered**: no change → an em dash with `aria-label="no change recorded"`,
  never back-filled from another phase. Sign is read off the string the tenant
  wrote (`/^[-−]/`), never re-derived. Provenance goes on `title` and into one
  muted sources line under the row.
- **Week strip** — five day cards plus a dashed weekly card; three pips `P I C`
  per day, lit only for recorded kinds. Prev/next walk the **recorded** weeks,
  not the calendar, and a disabled arrow says so in its `title`.
- **Tab strip** — a `Link` per recorded phase, a disabled `<button>` per absent
  one. Never a hidden tab: a phase that silently vanishes is indistinguishable
  from one that was never scheduled.
- **Motion** — the only transitions are the 120 ms card hovers, and
  `prefers-reduced-motion` kills them. The rule is scoped `.flash, .flash *`,
  not a bare `*`: a CSS module rejects a selector with no local class as impure,
  and it fails at *render* time, not at typecheck or vitest.

Semantic colour appears on numbers only. No panel is ever filled green or red.

## 6. Charts — hand-rolled SVG, both of them

No recharts, no d3, no visx; `lightweight-charts` has two documented exemptions
elsewhere and Flash is not one.

**Payoff** (`lib/flash/payoff.ts`, `PayoffChart.tsx`). Argon re-derives the
curve from **legs and net only** — never a model-written price.

```
pnl(S)      = 100 * ( Σ_legs sign * ratio * intrinsic(right, K, S) − net )
domain      = [lo − 0.18*(hi−lo), hi + 0.18*(hi−lo)]  over {strikes} ∪ {spot, breakeven}
breakpoints = sort(unique([domainLo, …strikes strictly inside, breakeven, domainHi]))
```

The view already carries `pnlAt` points, but they are five percentage offsets
around spot — enough for a smooth curve, not enough to place the kinks. A
payoff is piecewise linear with corners exactly at the strikes, so evaluating
*at* the strikes gives the true shape in five points where sampling needs a
hundred and still puts a corner a pixel off the strike it is labelled with.

Each segment is split at its sign change and filled down to the zero line.
Breakeven and spot are dashed lines **plus** text labels — never colour alone.
`role="img"` with an `aria-label` that names the ticker, the structure, the max
gain, the breakeven and the max loss in words, with its prepositions derived
from the curve's own slope (a put debit spread gains *below* its breakeven).

The chart renders **nothing** when the structure is unpriced, when either bound
is unbounded, or when spot or breakeven is missing. An unbounded loss has no
y-domain, and inventing one draws a floor the position does not have.

**Gamma bars** (`GammaBars.tsx`) — diverging horizontal bars, bar band from
x=132, width 176, zero axis at its centre. Duplicate `(strike, label)` rows
arrive from argon's own GEX tables (one level under two roles) and are
collapsed, first occurrence wins: a repeated bar reads as twice the exposure.
A caption says *− short gamma · 0 · long gamma +* in words.

## 7. Empty and degraded states

Four different nothings, and they must not render alike.

| State | Renders |
| --- | --- |
| No run, future day | "…has not been recorded yet", + skeleton |
| No run, past day | "No option-wizard `<phase>` run was recorded for `<date>`. The layout below is the empty shell, not a rendered flash.", + skeleton |
| Run exists, `view.empty` | one line: "This run completed but recorded no content" — and **no** decision block |
| Version unrenderable | an amber `PlaceholderBand` naming the version that arrived and the version this build draws, saying the run is stored and the fix is a deploy |

Every empty state carries an audit line — `helium audit — 0 runs for tenant
option-wizard, phase premarket, date 2026-08-31`. "Nothing here" and "we looked
and found nothing" are different claims and only the second is checkable.

**An absent section and an empty one are different claims.** `OvernightPanel`
with nothing flagged renders *"Nothing was flagged overnight."* and is never
omitted — a missing panel would read as a run that never looked.

The weekly Outlook empty state reads **`Generated Sunday morning`**, not the
mock's "Friday after close": helium's `weekly` phase fires Sunday 08:00 ET and
stays there.

## 8. Rules that are not style

- **No quantities, position sizes or account state**, anywhere. The premarket
  body closes on the line that says so. (The e2e asserts the negative over the
  candidate cards, not the page — the footer legitimately contains the words.)
- **Derived numbers come from the tenant's gated arithmetic.** Argon re-derives
  exactly one thing, the payoff curve, and only from legs and net.
- **`DecisionBlock` renders the reviewer's rows in the reviewer's order** —
  every key filled, no key not, nothing reordered. It is the only part of a
  flash that says what to DO; a row invented here is argon's opinion wearing the
  reviewer's name.
- **`PolicyPathPanel` prints the source verbatim and never writes "CME
  FedWatch".** The recorded path is Frenzy futures-implied; relabelling it is a
  data-integrity fault, not a copy choice.
- **`CoveragePanel` renders the body `pre-wrap` and does not parse it.** Its
  shape belongs to the tenant, and a parser breaks silently — showing a tidy,
  wrong table — the first time that shape changes.
- **A supplement stays subordinate.** Intraday and close open with a band that
  says *"Supplement to the premarket report of `<day>`…"* and links back; with
  no premarket row in the index the band says the supplement stands alone —
  never a dead link, never silence.
- **`GexDeltaTable` renders only when both runs are in hand.** A delta against a
  missing side is not a small delta, and drawing "0.00" would assert the level
  held.
- **Argon never explains away a defect in data it received.** The mock's
  cross-run note (one candidate id meaning two structures across phases) is
  deliberately not ported: that is fixed at the source in helium.
- **No fabricated numbers, fixtures included.** Every number in the tests and in
  `tests/fixtures/flash/2026-09-03-premarket.json` comes from the recorded
  option-wizard run of 2026-09-03. Where the run's own tape (QQQ 717.47) and its
  candidate object (spot 717.29) disagree, both are kept as recorded —
  reconciling them here would be argon inventing a price.

## 9. What is deliberately absent

No editing, no comments, no re-run button, no per-candidate history, no version
picker. The table keeps every version and the API accepts `?version=`, but
nothing re-renders a past day today, so a picker would be a control that never
changes anything. Storage keeps the option open at zero cost.

The ingest token is shared, not per-tenant: the realistic threat is a
misconfigured laptop, not a hostile Tailnet peer.

## 10. Open decisions carried forward

1. **Deploy needs one manual step** — `UW_SCAN_AGENT_INGEST_TOKEN` must be added
   to `/opt/argon/.env` on the mini and the services brought up with
   `docker-compose up -d api web`. Watchtower does not re-read `env_file`.
   Migration 148 applies itself (the `api` service self-migrates on boot).
2. **Two deploy commands are unverified in this repo** — running `psql` inside
   the `api` image, and the GHCR retag for rollback. Confirm with the operator;
   do not guess.
3. **helium merges second.** This PR must merge and deploy first: helium's
   delivery channel POSTs to an endpoint that has to already exist.
4. **Frank's `run_day`** is helium's to choose. Argon reads it off the week
   index and makes no assumption about which day it lands on (§3).
