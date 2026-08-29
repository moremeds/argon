# Handover: Fundamentals Industry Desk — executive summary at v0.13.0

**To:** the next session (human or agent) picking up the fundamentals lane
**From:** Claude Code, after building, releasing, deploying and verifying the desk on 2026-08-28/29
**Repository:** `/Users/chenxi/projects/argon`
**Branch:** `misc/fundamentals-desk-handover`
**Base:** `68d1fbf7` (`v0.13.0`, merged by PR #397; the desk itself is `745d52d2`, PR #396)
**Status:** shipped, deployed, and verified in production. Documentation handover only — this
document authorizes no further implementation.

## Reactivation prompt

> We are continuing the Argon fundamentals industry desk from this handover. Read this document
> first, then the cited spec, plan and research verdicts. Re-check every time-sensitive fact against
> production before acting on it — the counts below are a snapshot, not a contract. Do not treat the
> "known gaps" section as a backlog you are authorized to drain; each gap names its own gate.
> Preserve the desk's authority boundary: it **lists and measures, it never ranks, scores or sizes**.

---

## 1. Executive summary

The fundamentals industry desk is **live in production and populated**. `/fundamentals` →
`/fundamentals/ai-semi` → node deep-dive pages all render with real data, over eight read-only
endpoints that make **zero vendor calls**. The lane's P1–P3 scope is closed.

Three things a reader should take away:

1. **The desk deployed green and blank.** Migrations create the tables; nothing fills them. Four
   things had to be run by hand before any panel showed a row (§4). A fresh database repeats this
   exactly — the seed has no scheduler entry, by design.
2. **The desk's restraint is measured, not stylistic.** Four visible absences — no median on
   `valuation_percentile`, no merging of cohorts across `as_of` buckets, no arrows on the profit
   pool, no fetcher behind the capex strip — each encode a specific research verdict (§7). Someone
   "completing" the UI by adding them would be reversing a measurement, not polishing a design.
3. **The evidence substrate underneath the desk is thinner than the desk is.** `research_reports`
   holds 0 rows, `implied_move_daily` 0, `earnings_reactions` 9, and only 14 of 328 exposures carry
   a disclosed magnitude. The pages handle these absences honestly, but the desk is currently a
   well-built surface over a substrate that four unscheduled jobs are supposed to accrue (§5).

## 2. Current deployed truth, verified 2026-08-29

- `main` and `origin/main` point to `68d1fbf7`, tagged `v0.13.0`. Release workflow run
  `33233250223` completed with 4/4 jobs green (verify · publish GitHub Release · ghcr-push
  `argon-app` · ghcr-push `argon-web`).
- Watchtower deployed the floating `:latest` images within ~1 minute
  (`WATCHTOWER_POLL_INTERVAL=60`). The `api` service self-migrated on boot; migration `147`
  (`fundamentals_desk_rollup`) applied without an out-of-band run.
- `http://100.66.147.98:3001/api/health` reports `ok=true`, `db=up`, `version=0.13.0`.
- All four web routes return HTTP 200: `/fundamentals`, `/fundamentals/ai-semi`,
  `/fundamentals/ai-semi/cases`, `/fundamentals/radar`, plus a node page
  (`/fundamentals/ai-semi/Cloud/Hyperscaler`).

All eight desk endpoints return HTTP 200 with content:

| Endpoint (`/api/fundamentals/ai-semi/…`) | Result                                                                                     |
| ---------------------------------------- | ------------------------------------------------------------------------------------------ |
| `scope`                                  | 13 scope groups                                                                            |
| `cases`                                  | 2 cases                                                                                    |
| `matrix`                                 | 26 chains, 78 cells                                                                        |
| `profit-pool`                            | 26 layers                                                                                  |
| `capex`                                  | 5 filers included, 14 quarters                                                             |
| `calendar`                               | 19 forward prints, `as_of=2026-08-29`                                                      |
| `delta`                                  | 200 events since 2026-08-22                                                                |
| `limits`                                 | NI basis agree 12,220 / differ 1,335 / 1 sign-flip violation / 2 membership-evidence items |
| `node/underwriting?chain=…`              | `Cloud/Hyperscaler` 6 rows, `Computer/GPU` 7 rows                                          |

Table state in `option_wizard` on the mini:

| Table                      |   Rows | Note                                                 |
| -------------------------- | -----: | ---------------------------------------------------- |
| `research_chains`          |     48 |                                                      |
| `chain_membership`         |    367 | 39 distinct chains, 284 distinct tickers             |
| `company_exposure`         |    328 | **14 disclosed with a magnitude**, 314 asserted      |
| `research_event_classes`   |     19 | was 0 before the first `register_discovery_gate` run |
| `research_events`          |    427 | `bucket_flip` 419, `band_exit` 7, `band_entry` 1     |
| `fundamentals_desk_rollup` | 29,894 | 419 distinct tickers                                 |
| `earnings_calendar`        |    238 | **128 dated today or later**                         |
| `earnings_reactions`       |      9 | thin                                                 |
| `implied_move_daily`       |  **0** | fills at tonight's 20:45 ET job                      |
| `research_reports`         |  **0** | node pages replay stored reports; none exist yet     |

`chain_membership.evidence_class` is `mirrored` 347 / `analyst` 20 — nothing at membership level is
`disclosed`. Disclosure lives on `company_exposure`, where a magnitude requires
`status='disclosed'` and a named basis (a CHECK enforces it). **4.3% of exposures carry one.**

## 3. Scope boundary

Shipped: spec P1–P3 — the data spine (durable earnings calendar, reaction history, implied move,
change events, underwriting features, NI reconciliation, optical routing fix) and the three-route
surface (`/fundamentals` index with Radar folded in as triage, the `/fundamentals/ai-semi` routing
desk, `/fundamentals/ai-semi/<chain>` underwriting deep dives).

**Excluded on purpose:** the spec's P4 — guidance extraction from 8-Ks and agent narrative — is
labelled "direction, not commitment" in the spec and was never in the plan. Do not treat it as
unfinished work.

`/radar` and `/chains` still resolve and redirect into the desk; they are in browser histories and
in this repo's own docs. Per-chain drilldown at `/chains/[chain]` is untouched. The all-domain
chain × layer matrix component was deleted rather than left unreachable.

## 4. The deploy-green-and-blank problem — read this before any redeploy

Every health check reads green while the desk is fully inert. "Is the code there" and "did anything
call it" are different questions, and only the first is asked automatically. Four things had to be
run by hand on 2026-08-29, in this order, none of them scheduled:

1. **Taxonomy seed** — `docker exec -w /app argon-api-1 python
scripts/backfill/research_taxonomy_seed.py` → 48 chains, 367 memberships. Without it every panel
   returns `[]` at HTTP 200. This script has **no scheduler entry by design** (seeding is a curated,
   manual act), so a rebuilt database is blank until someone runs it again.
2. **`fundamentals_desk_rollup`** → 29,894 rows across 420 tickers. Fills the matrix medians.
3. **`derive_change_events`** → 427 events. Its first action is `register_discovery_gate`
   populating `research_event_classes` from **0**. That registry had no caller before PR #396; the
   delta rail was not "waiting for changes", it was structurally unable to hold one, and the nightly
   job would have raised on its first real event. The whole test suite was green throughout, because
   a fixture supplied registry state the deployment never created — **reading production's own table
   counts is the only check that catches this class of bug.**
4. **The forward calendar leg** — `fetch_calendar_listings` for `today+1..+14`, inside
   `fundamental_ingest_daily` → 128 listings, zeros landing exactly on weekends.

Step 4 answered PR #396's open question: **UW does serve forward earnings schedules.** The empty
"Next prints" panel was never a vendor limitation — the scan was backward-only. The forward leg now
ships in `fundamental_ingest_daily` (04:20 ET daily) and the ingest windows are deliberately
asymmetric: the **backward** window (`FILING_LOOKBACK_DAYS = 45`) finds statements to ingest; the
**forward** window ingests nothing and exists solely to keep `earnings_calendar` holding rows that
`next_prints` can read. Forward listings are not folded into `symbols` — a print that has not
happened has no statement, and ingesting one spends 4 UW calls per name to retrieve nothing.

## 5. Known gaps, each with its own gate

| Gap                                  | Why                                                                                                                                                                                                                   | Gate before acting                                                                                                                                       |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `implied_move_daily` = 0 rows        | `implied_move_snapshot` reads `option_surface_grid_daily WHERE market_date = as_of`; today's surface is captured at 19:00 ET. Its own 20:45 ET slot sits after that capture. Running it earlier returns honest zeros. | **None — this is not a defect.** It fills tonight. Do not "fix" a job by moving it ahead of its input.                                                   |
| `research_reports` = 0 rows          | `research_report_scaffold` / `_assemble` have no scheduler entry. Node pages REPLAY stored blocks and never re-assemble, so with no reports they render their empty state correctly.                                  | Decide a cadence (or a documented manual trigger) before scheduling. Assembly under today's data is a different answer wearing an old version number.    |
| `earnings_reactions` = 9 rows        | Accrues forward from 19:41 ET nightly; the backfill script exists but has not been run at scale.                                                                                                                      | Backfill is bounded and zero-vendor-cost, but confirm scope first.                                                                                       |
| 14 of 328 exposures disclosed (4.3%) | A magnitude requires a real disclosure and a named basis. Most memberships are `mirrored` from the watchlist chain taxonomy.                                                                                          | This is the measured yield, not a bug. Raising it means reading filings, not relaxing the CHECK.                                                         |
| Four unscheduled research jobs       | `research_events_derive`, `research_report_scaffold`/`_assemble`, `sec_filing_index_refresh`, `fundamental_publication_evidence` — all predate this branch and were out of its scope.                                 | The desk's evidence surfaces stay static until these get schedules or a documented manual cadence. Scheduling them is a separate, unauthorized decision. |

Scheduled and working (all `massive-0`, all zero UW/IB spend, each gated by its own setting):

| Job                          | Cron (ET)       |                                                                       |
| ---------------------------- | --------------- | --------------------------------------------------------------------- |
| `earnings_reactions_compute` | `41 19 * * *`   | daily; a Monday-holiday print's Tuesday close still lands on schedule |
| `implied_move_snapshot`      | `45 20 * * 0-4` | weekdays, after the 19:00/19:30 surface capture                       |
| `fundamental_change_events`  | `15 21 * * 0-4` | weekdays, after implied-move and the 18:20 `fundamental_refresh`      |
| `fundamentals_desk_rollup`   | `30 21 * * *`   | daily, not weekday-only — a restatement can land any day              |

## 6. Required reading, in order

1. `docs/superpowers/specs/2026-08-26-fundamentals-industry-desk-design.md` — the spec. P4 is
   direction, not commitment.
2. `docs/superpowers/plans/2026-08-26-fundamentals-industry-desk.md` — the plan (Tasks 1–20, all
   complete; checkboxes were never ticked because execution tracked a ledger instead).
3. `CHANGELOG.md`, the `[0.13.0]` section — the shipped surface in its own words, including why each
   absence is an absence.
4. The verdicts the UI is built on: `docs/research/2026-08-25-chain-exposure-yield/`,
   `docs/research/2026-08-25-evidence-discovery-gate/`,
   `docs/research/2026-08-25-research-report-completion/`,
   `docs/research/2026-08-12-fundamental-*/`.
5. `CLAUDE.md`, the fundamentals rows in "Where to look first" — they carry the traps that bite.

## 7. Binding findings the desk encodes

These are measurements. Reversing one in the UI is reversing a research result.

- **`valuation_percentile` carries no median.** Own-history value measured real (within-ticker
  `sales_to_ev` IC +0.0744, t 5.77) while cross-sectional value measured **inverted** in the same
  universe (`book_to_price` IC −0.0365, t −2.32). A chain aggregate over own-history percentiles is
  a claim nothing supports.
- **Cohorts straddling two `as_of` buckets never merge.** `as_of` is a cross-section _identifier_,
  not a timestamp to round; the cohort effect measured 1.9×.
- **The profit pool has no arrows, no propagation, no lead/lag copy.** The capex-demand ledger's
  cross-name relationship collapsed from +0.247 to +0.015 (p=0.44) once same-sector pairs were
  compared.
- **The capex strip has no fetcher and no model field.** Building a data path for the most widely
  circulated number in the sector would re-promote the figure the spec demoted.
- **`no_compatible_run` is not `no_coverage`.** Collapsing them turns "the job never ran" into "this
  company has no fundamentals" — a statement about a real business Argon is not entitled to make.
- **`chain_membership` is grained `(chain, layer, ticker)`.** A name in two layers appears twice, so
  every count and every mean must dedupe to distinct tickers or a numerator will exceed its
  denominator. The desk calendar shows CRDO twice on purpose — a print's place in the chain _is_ the
  row.
- **The desk lists; it never ranks.** No sort over `spot_percentile` or depth may be added.

## 8. Ordered next steps (none authorized by this document)

1. Confirm tonight's crons close the loop with no manual help: `implied_move_snapshot` 20:45 ET,
   `fundamental_change_events` 21:15 ET, `fundamentals_desk_rollup` 21:30 ET,
   `fundamental_ingest_daily` 04:20 ET. Re-read the counts in §2 tomorrow; every one should have
   moved without intervention.
2. Decide the report-assembly cadence, then schedule `research_report_scaffold`/`_assemble` — this
   is what takes node pages from "empty by design" to substantive.
3. Decide whether `sec_filing_index_refresh` and `fundamental_publication_evidence` get schedules;
   they are what keep publication evidence current.
4. Archive the completed spec and plan to `docs/superpowers/archive/{specs,plans}/`. Grep first —
   a doc path in this repo can be load-bearing inside a docstring or `CLAUDE.md`.
5. Remove `.worktrees/fundamentals-desk-pages` — its branch is merged and its remote deleted. It
   could not be removed from inside the session that was using it as a working directory.

## 9. Verification already run

- Release: PR #396 and #397 both merged CI-green (7/7 checks); tag `v0.13.0` pushed; release run
  `33233250223` 4/4 green; `/app/VERSION` on `argon-api-1` reads `0.13.0`.
- Seed: verified all four tables at **0 rows before** seeding, then re-counted after.
- Plan reference checks matched exactly: scope groups **13**, cases
  `[("datacenter", 5), ("optical", 5)]`, matrix **78 cells**, capex **14 quarters** / 5 USD filers /
  BABA excluded for CNY.
- Browser: three full-page screenshots of the live production desk at
  `output/playwright/2026-08-29-prod-ai-semi-desk-v0130*.png` in the primary checkout. `output/` is
  gitignored, so these are local artifacts, not part of this PR — they were copied out of the build
  worktree so they survive its removal.
- API: all eight endpoints and all node/web routes re-swept on 2026-08-29 for this document (§2).

## 10. Two operational traps worth carrying forward

**A `gh` exit code describes the command, never the thing it watched.** `gh pr merge` exits 1 when
the _merge succeeded_ and only its local housekeeping failed (`fatal: 'main' is already used by
worktree at …` — routine in this repo). Never retry a failed merge; query
`gh pr view N --json state,mergedAt,mergeCommit` instead. In the other direction,
`gh run watch --exit-status` exits **0** on a transient API error mid-watch, so a network blip reads
as "the run passed". Poll `gh run view --json status,conclusion` and treat "no conclusion yet" as
keep-going.

**Shipped ≠ scheduled ≠ run.** The taxonomy seed shipped in v0.12.18 and sat in the image
unexecuted, because no scheduler entry pointed at it. Nothing in any health check was capable of
noticing.
