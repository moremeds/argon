# Macro Analysis Desk — pixel-exact remediation handover

> **Reactivation prompt:** Continue PR #399 from this document. Re-read repository
> `CLAUDE.md`, inspect the current worktree, and re-run the relevant gates before changing
> anything. The SHA-pinned board is the design authority, with one operator-approved product
> override: retain Argon's left sidebar and use Regime-style 32px gutters. The remediation is
> committed locally. Do not push, mutate the PR, or deploy without separate user authorization.

## Goal

Finish the nine-tab Macro Analysis desk at `/macro/*` as a live-data port of the approved
Claude board: preserve its hierarchy, panel inventory, typography, provenance, data bindings,
and replay honesty while keeping Argon's 220px sidebar. The application geometry is:

`220px sidebar + 1440px macro canvas`, with `32px` left/right gutters inside the canvas.

## Current source state

- repository: `/Users/chenxi/projects/argon`
- worktree: `/Users/chenxi/projects/argon/.worktrees/feat-macro-desk-tabs-03-05`
- branch: `feat/macro-desk-tabs-03-05`
- PR: `#399`, open, base `main`
- remote branch tip before remediation: `97262085`
- committed implementation tip before this documentation milestone: `b2f92913`
- branch state: 11 local remediation commits ahead of the remote branch; **nothing was pushed**
- approved reference:
  `docs/superpowers/specs/2026-08-27-macro-desk-board.html`
- reference SHA-256:
  `b98a32de3041a348aa8e86f5c4cc2cb9480b000752bdd6b26a2dead7b08f4029`
- remediation design:
  `docs/superpowers/specs/2026-08-29-macro-desk-pixel-exact-remediation-design.md`
- remediation plan:
  `docs/superpowers/plans/2026-08-29-macro-desk-pixel-exact-remediation.md`

The GitHub PR body predates this remediation and is stale. It still says the sidebar was
collapsed, Gold lens/input endpoints are unconsumed, 60d gauge history is unavailable, Python
has one local failure, and production E2E has not run. None of those statements is current.

The local remediation series is intentionally split into independently verified milestones:

1. `8a46f558` — shared market-implied probability bars
2. `00611675` — stable Frenzy page identity
3. `1aa1f07d` — persisted Gold gauge history
4. `892ee0bf` — isolated Xenon query settings test
5. `a61cc071` — typed replay and Gold data bindings
6. `170506b5` — full board shell and Overview loader
7. `4a9e047d` — Overview and Energy panel alignment
8. `a9abb319` — Fed and Curve board refactor
9. `c0452a67` — Gold lens detail and 60d history
10. `d9342ad9` — byte-pinned Design Notes
11. `b2f92913` — full-board visual contract and browser gates

## Closed in the remediation

### Shell and design

- Restored the normal Argon sidebar on every Macro route.
- Kept the complete 1440px board canvas to the sidebar's right instead of compressing it.
- Replaced the artifact's centered 1240px wrap with Regime-style 32px gutters, per operator
  direction; the comparator applies the same explicit override to the immutable reference.
- Added the exact masthead, provenance legend, Q1–Q7 strip, sticky nine-tab bar, replay menu,
  and footer. Design Notes is visible as tab 08.
- Rebuilt Fed and Rates into the reference panel order and grid grammar.
- Removed obsolete Rates layouts and dead CSS. The committed implementation remediation changes
  83 files with 3,370 additions and 4,856 deletions: **1,486 net lines removed** even after adding
  tests, types, and the visual comparator.
- Split the route loader and reduced the two oversized Overview zone modules to under 500 lines.

### Correctness and data binding

- Fixed Overview replay to call `/api/macro/snapshot?as_of=YYYY-MM-DD`; the former
  `as_of_ts` call was both the wrong clock and a naive value.
- Added persisted daily `history_60d` to `/api/gold/gauge`, sourced from
  `gold_posture_daily` with one active first-compute observation per market date.
- Gold and Overview now draw the requested 60d history. Overview bounds the returned history
  to the replay date, so a historical page cannot display future anchor points.
- Added typed `/api/gold/lenses/{lens_id}` access. The Input Manifest loads all three lens
  detail series only when the operator expands the disclosure; the default page makes zero
  hidden lens requests.
- `/api/gold/inputs/{series_id}` remains bound in Overview's dated market-delta panel.
- The four-path market probability bar renders the persisted Frenzy Capital Fed Watch
  `probability_distribution` when the approved shadow ingest is active; it retains
  `third_party_shadow`, `free_third_party_shadow`, and `delay_status=unknown` labels. If the
  source is unavailable, the honest refusal remains and no probability is invented.
- A live repeat exposed request-varying Cloudflare bytes in the otherwise unchanged Frenzy
  HTML. The source now gives the continuously updated page one stable `source_record_id`:
  every exact response remains an artifact, but the semantic policy upsert links cosmetic
  variants to one observation instead of inventing another market view.
- Made the option-surface settings test independent of the developer's inherited
  `XENON_QUERY_API_URL` / key values, removing the previous local false negative.

### Chart scale after the gutter change

- The wider Regime-style content area exposed three stale coordinate frames. Updated the Fed
  policy comparison, Gold correlation history, and Gold structural chart frames to their
  measured containers.
- The production browser chart-scale gate now passes across every Macro tab at the canonical
  `1660x1000` app viewport (`220 + 1440`).

## Verification evidence

Run from the worktree unless a command says `cd web`:

- `uv run pytest` → **4465 passed, 0 failed, 14 skipped**
- `cd web && npm run test` → **140 files, 1091 tests passed**
- `cd web && npm run typecheck` → passed
- `cd web && npm run lint` → passed, zero warnings
- `cd web && npm run lint:gold-copy` → passed
- exact staged snapshot: `cd web && npx next build --webpack` → Next production build passed
- isolated production Playwright, seven Macro/Gold spec files → **41 passed**
- `git diff --check` → passed
- `uv run python scripts/release/version_sync_check.py` → `OK: 0.13.0`
- `cd web && LIVE_BASE=<isolated production server> node scripts/board-pixel-compare.mjs`
  → all 9 tabs captured under `output/playwright/board-compare/`

The latest comparator report contains 3,481 raw occurrence differences: 3,016 geometry,
85 count, and 380 style. This is not a bitmap pass/fail number. It pairs same-selector elements
by index, so a live table with a different row count cascades every later y-coordinate and counts
the same data-dependent shift repeatedly. The paired screenshots were visually reviewed. Notes
is near-exact (8 raw differences); Gold is 131px taller than the frozen mock because it exposes
real lens/audit depth. Do not report the raw 3,481 as 3,481 independent design defects.

A full-repository Playwright sweep was also attempted: 84 of 104 tests passed. One failure was
an obsolete Gold five-tier assertion and is fixed in the visual-contract milestone. The other
19 failures are outside the Macro/Gold port (Chains, Regime, Technicals, Volatility, and one
stateful rescan flow) and were not changed or claimed clean by this work. The focused 41-test
production suite above is the integration gate for this remediation.

## PR size and simplification review

The local branch before this documentation milestone differs from `origin/main` by 171 files,
+27,751 / −5,617. The apparent “30k lines” is not all runtime code:

- frozen board HTML: 6,891 added lines; retain as the signed source authority;
- original implementation plan: 1,315 added lines;
- audit, handover, tests, generated OpenAPI/types, and screenshots tooling make up a large share;
- the 11 committed remediation milestones remove 4,856 lines while adding 3,370, net
  **1,486 lines deleted**.

The main simplification was `RatesDesk.module.css` and the duplicated Rates section/state/path
implementations. The largest remaining Macro runtime stylesheet is `board.css` (896 lines),
which is the shared board design system; the largest Rates stylesheet is ~716 lines. Do not delete
the frozen HTML or static Design Notes reference merely to improve the diff statistic: they are
the auditable design contract and are byte/inventory tested.

## Intentional boundaries

- No migrations, new secrets, or new environment-variable names. The existing
  `UW_SCAN_MACRO_MARKET_SHADOW_INGEST_ENABLED` switch was activated locally and on the Mac mini;
  one initial Frenzy fetch was persisted in each database and the mini's prior env file was backed
  up before the worker restart.
- No composite macro score, allocation, price target, or invented market probability.
- Energy stays a proposal, upstream of inflation; it is not promoted to a fifth domain state.
- `/gold/replay/<date>` remains available and unlisted.
- The old `/gold` and `/rates` entries redirect into the Macro desk.
- The sidebar remains; do not revert to the earlier sidebar-free shell.
- The 32px gutter is an approved override to the frozen board's centered wrap.

## Remaining work before integration

1. Refresh the GitHub PR body with the facts above only after the user authorizes PR mutation.
2. Push only the feature branch after explicit authorization, then let PR/CI verify. Never push
   directly to `main`.
3. Before claiming merge readiness, re-run the full gates above and inspect the paired Overview,
   Fed, Rates, Gold, and Notes screenshots at the canonical viewport.

Frenzy is the approved current market-implied source. Local `/macro/fed` renders all three stored
meeting distributions; the Mac mini API also serves them, but deployed `v0.13.0` predates this PR
and therefore has no `/macro/fed` route yet. The production page will consume the already-persisted
path after the PR follows the normal merge and release process. Frenzy remains a non-load-bearing
shadow with unknown delay; an outage must restore the refusal state rather than borrowing an
official or dealer path.
