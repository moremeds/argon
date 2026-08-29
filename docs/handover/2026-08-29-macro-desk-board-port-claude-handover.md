# Macro Analysis Desk — board port — Claude Code Executive Handover

> **Reactivation prompt:** Continue Argon's Macro Analysis desk from this handoff. Read repository
> `CLAUDE.md`, the board spec (`docs/superpowers/specs/2026-08-27-macro-desk-board.html`), the port
> plan and the binding plan before editing code. Reverify Git and test state; do not rely on chat
> history. The board is the spec — where the plan and the board disagree, the board wins. Stop
> before commit/push/PR or production mutation unless the user separately authorizes it.

## 1. Executive summary

Argon had three separate macro surfaces — `/gold`, `/rates`, `/macro` — each with its own idiom,
its own replay story, and its own answer to "what did you know, and when". This branch merges them
into **one nine-tab Macro Analysis desk at `/macro`**, built against a design board the operator
supplied as the binding spec.

- repository: `/Users/chenxi/projects/argon`
- worktree: `/Users/chenxi/projects/argon/.worktrees/feat-macro-desk-tabs-03-05`
- branch: `feat/macro-desk-tabs-03-05`
- rebased onto: `68d1fbf7` (`release: v0.13.0`, 2026-08-29)
- 45 commits, 141 files, +26.4k / −2.9k

**Zero new endpoints.** Every panel on the desk is a layout over a field the API already
published. Three data paths that existed but nothing consumed are now bound: `/api/gold/gauge`,
`/api/macro/rates` `sub_states`, and `/api/macro/policy` `market_implied`.

The backend diff is 8 files, +111 / −25 — `?as_of=` / `?as_of_ts=` on `/api/rates/snapshot`, a
confidence-term `kind` correction in `macro/rates.py`, and three small additive fields. Everything
else is the web tier.

## 2. Read these documents in order

1. `docs/superpowers/specs/2026-08-27-macro-desk-board.html` — **the spec**, sha256-pinned in the
   repo. Nine tabs, 47 shippable panels, seven PM questions, its own class grammar.
2. `docs/superpowers/plans/2026-08-27-macro-desk-page-port.md` — the port plan (P1–P6). Its
   superseded "No new analytics / presentation merge" line is what shipped tabs 03/04 as one
   generic card each; §10 records the corrections.
3. `docs/research/2026-08-28-macro-desk-board-conformance/VERDICT.md` — the audit that measured the
   gap before any of it was closed: 47 panels, 26 present, 6 partial, 15 absent or misplaced.
4. `docs/superpowers/plans/2026-08-29-macro-desk-board-full-binding.md` — the binding plan.
   **§8 closes the information port; §9 closes the design port.** Read both; §8 alone is the
   mistake this branch made once already.

## 3. What shipped

### The nine tabs

| Tab                      | Route                       | Panels | Replay clock  | Origin                       |
| ------------------------ | --------------------------- | -----: | ------------- | ---------------------------- |
| 00 Overview · Daily Loop | `/macro/overview`, `/macro` |     11 | `as_of`       | net new                      |
| 01 Fed · Policy          | `/macro/fed`                |      8 | `computed_at` | from `/rates`                |
| 02 Rates · Curve         | `/macro/rates`              |      9 | `computed_at` | from `/rates`                |
| 03 Inflation             | `/macro/inflation`          |      4 | `as_of`       | from `/macro`                |
| 04 US Dollar             | `/macro/usd`                |      2 | `as_of`       | from `/macro`                |
| 05 Gold                  | `/macro/gold`               |      8 | `obs_date`    | from `/gold`                 |
| 06 Energy · Proposal     | `/macro/energy`             |      2 | —             | net new                      |
| 07 Factor Export         | `/macro/factors`            |      3 | —             | net new                      |
| 08 Design Notes          | `/macro/notes`              |      — | —             | operator-only, off the strip |

`/gold` and `/rates` are permanent 308s into the desk. `/gold/replay/<date>` is deliberately kept
and deliberately unlisted. The sidebar carries one Macro entry where it carried three.

### Three registries that cannot drift

- **`web/components/macro/tabs.ts` is a REGISTRY, not a schedule.** One array feeds both the route
  guard (`notFound()` on an unregistered slug) and the tab bar, so the bar cannot link to a route
  that 404s and the route cannot answer a slug the bar does not show. Adding a tab without adding
  its content to `TAB_CONTENT` is a compile error.
- **`replayClock` has no default.** It must name what the tab's endpoint _actually_ keys on:
  `/api/macro/*` selects on `as_of`, `/api/rates/snapshot` on `computed_at`, `/api/gold/replay` on
  `obs_date` with exact equality. Three verdict functions in `replay.ts`, two copy families in
  `ReplayStatus`. Nothing type-checks the declaration against the router — this is the one place a
  wrong answer is silent.
- **`BoardPanel.questions` is a non-empty tuple.** The board's own acceptance test says every panel
  must answer at least one of Q1–Q7 or it gets deleted. A panel that answers none does not compile.

### The design port (§9) — why the second pass existed

The first pass reported **47/47 panels bound** and was still wrong. It matched panel _inventory_;
it did not match _design_. Tab 00 rendered zero board classes. Tabs 01 and 02 used no grid at all.
The desk printed sixty-odd `REAL`/`Q4` chips and never defined them anywhere.

The fix was to stop arguing about design from source and measure it:
`web/scripts/board-pixel-compare.mjs`. **It is not a bitmap diff** — the board's numbers are mock
values frozen at its capture instant while the desk derives its own at render time, so a pixel
subtraction is dominated by digits and says nothing. It compares grammar coverage, computed style
per selector, and full-page screenshots.

Four findings that code review had not produced:

1. **The body type scale** — board 13.5px/1.55 against argon's 13px/1.5, inherited by everything.
   The largest single source of drift, invisible in any per-component read.
2. **Every board table cell rendered in mono.** `globals.css` styles bare `td`; the board declares
   neither face nor size and _inherits_ sans/12.5px — and an inherited value always loses to a
   declaration, however weak its specificity.
3. **Tabs 01/02 had no grid.** The class-coverage probe missed it because `.grid.g2` _did_ render —
   on other tabs. Coverage must be per-tab or it hides exactly this.
4. **The desk had no key.** `BoardLegend` now renders the provenance key and the Q1–Q7 strip once
   in the layout, which is the nine-route equivalent of the board's "once, above the tabs".

## 4. Evidence

Every claim below is reproducible from the branch tip.

| Claim                                 | Evidence                                                  | Re-verify                                                        |
| ------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| 47/47 board panels present and bound  | plan §8 table, per tab                                    | fetch each tab, match the board's panel titles                   |
| 40 of 41 probed board elements render | `board-pixel-compare` grammar probe                       | `cd web && node scripts/board-pixel-compare.mjs`                 |
| Computed-style diffs 65 → 15          | `output/playwright/board-compare/report.json`             | same command                                                     |
| All 9 routes + gold replay + API 200  | curl sweep, 2026-08-29 post-rebase                        | `curl -o /dev/null -w '%{http_code}' localhost:3002/macro/<tab>` |
| Types                                 | clean                                                     | `cd web && npm run typecheck`                                    |
| Web unit tests                        | **138 files / 1077 tests pass**                           | `cd web && npm run test`                                         |
| eslint                                | clean, zero warnings                                      | `cd web && npm run lint`                                         |
| Posture lint                          | clean                                                     | `cd web && node scripts/lint-gold-copy.mjs`                      |
| Python                                | **4463 passed, 14 skipped, 1 pre-existing local failure** | `uv run pytest`                                                  |
| Version sync                          | `OK: 0.13.0`                                              | `uv run python scripts/release/version_sync_check.py`            |

**The one Python failure is not this branch and will not appear in CI.**
`tests/unit/test_settings_option_surface.py::test_settings_reads_option_surface_flags` asserts the
_default_ `xenon_query_api_url`; this worktree's `.env` sets it to the mini. `tests/conftest.py`
documents this failure by name as "a purely local false negative — CI has no `.env`, so it never
sees this". Reproduced deterministically with one variable:

```bash
XENON_QUERY_API_URL=http://100.66.147.98:8321 uv run pytest tests/unit/test_settings_option_surface.py
```

Passes in isolation; passes across `tests/unit` (2690 tests, no `.env` leak in that path).

## 5. What is NOT done

- **`.pbar` — the per-meeting probability bar — does not render, and cannot.** Verified, not
  assumed: `/api/macro/policy` carries `probability_distribution` on **0 of its 21 points across
  all four lanes**, the market-implied lane publishes `missing_reason` instead of a path, and
  `/api/rates/snapshot` has no `market_implied` block. Tabs 00 and 01 state the refusal in the
  publisher's own words. The CSS stays, so the bar's return is a markup change.
- **`/api/gold/lenses/*` and `/api/gold/inputs/*` remain unconsumed.** `inputs/{id}` carries real
  depth (`DFII10`, 1293 points) and would turn the input manifest from a list into inspectable
  series.
- **The board's t5 anchor-decay panel cannot be built as specified.** Not a port gap — the desk
  neither computes nor retains a 60-day correlation series; the producer computes 252d only. The
  fix is in `reports/gold_posture.py`, not in the web tier.
- **15 residual computed-style diffs**, each checked rather than filtered: all are mock-vs-live
  data, or the two pages opening on a different first instance of a class.
- **t2 (1.70×) and t7 (1.43×) are taller than the board** because they carry content its mock does
  not.
- **No e2e run against a production build.** Unit and route-level checks only; the Playwright specs
  exist (`web/tests/e2e/macro-*.spec.ts`) but have not been run against `next build`.
- **Everything verified against `option_wizard_local`, never the mini.**

## 6. Traps for whoever continues

- **A design spec binds its design, not only its information.** This branch shipped 47/47 panels
  bound to live data and still looked nothing like the board. Any check that counts panels will
  pass over that gap silently.
- **`.tag` is not one thing.** `.tag.real` is teal, `.tag.q` violet. A bare `querySelector(".tag")`
  reports a colour difference that is really "the two pages open with a different kind of tag".
- **`fullPage: true` measures document scroll height.** `AppShell` scrolls an inner `<main>`, so
  full-page capture returns viewport-height images. Grow the viewport to the desk's own height
  instead — and take the max bottom edge across _all_ `.board` elements, because `BoardLegend`
  carries the class too.
- **The board's values are frozen at its capture instant and must never be restated.** Its t4 title
  says the dollar pair moves "in reverse" and both legs are currently positive. Every such sentence
  is derived at render time (`dollar-pair-read`, `gold-gauge-read`) and tested in both branches.
- **The posture lint walks the filesystem, not the import graph.** It scans `components/{gold,macro}`
  - `app/{gold,macro}` and bans `long`/`short`/`trade`/`enter`/`buy`/`sell` in **comments as well as
    prose**. `components/rates` is out of scope on purpose.
- **No composite, ever.** Averaging four differently-grounded domain answers hides the
  contradictions the cards exist to show. A test asserts the desk's own chrome carries no
  score/allocation/probability — and it had to be widened, because the board's own standfirst says
  "There is not, and will never be, a composite score". Ban the thing _presented_, not the word.
- **The changelog trap, which bit this branch.** Rebasing onto a release moves `## [Unreleased]`
  and puts a dated header in its old position. Git auto-merges cleanly and files your entries under
  the **released** section. Check `## [Unreleased]` is non-empty after any rebase over a release.

## 7. Deploy notes

- **No migrations.** Nothing to apply out of band.
- **No new environment variables**, no new secrets, no new vendor spend. The desk's every read is
  an endpoint that already existed.
- `/gold` and `/rates` become permanent (308) redirects. Bookmarks and browser history keep
  working; the sidebar stops offering three doors to one room.
- `/gold/replay/<date>` is kept and unlisted — the desk's gold tab carries the same replay through
  `?as_of=`.

## 8. Reproduce every gate

```bash
cd /Users/chenxi/projects/argon/.worktrees/feat-macro-desk-tabs-03-05

uv run pytest                                    # 4463 pass (1 local .env false negative)
uv run python scripts/release/version_sync_check.py

cd web
npm run typecheck
npm run test                                     # 138 files / 1077 tests
npm run lint
node scripts/lint-gold-copy.mjs                  # posture lint

# design conformance — needs the dev server on :3002
node scripts/board-pixel-compare.mjs
# -> output/playwright/board-compare/report.json + 16 screenshots
```
