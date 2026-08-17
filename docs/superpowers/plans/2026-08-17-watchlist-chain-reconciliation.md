# Watchlist Chain Reconciliation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** make `uw_scan.watchlist_chain` self-maintaining, so changing a ticker's sector or adding a
new ticker can never strand a wrong tag — and stop the filter rail from offering a chain that
returns nothing.

**Architecture:** membership is derived state. Its only correct definition is "what
`uw_scan.watchlist_taxonomy` says for this ticker, plus its `watchlist.sector` as a fallback when
the module says nothing." Today three write paths each hold a _partial_ version of that rule and
none of them enforces it end-to-end. This plan makes one function own the invariant and calls it
from every path that can invalidate it.

**Tech stack:** psycopg 3 / Postgres (`uw_scan.watchlist_chain`, PK `(ticker, chain)`), FastAPI
router `api/routers/watchlist.py`, `scripts/backfill/watchlist_chain_seed.py`, React `FilterBar` +
pure `sectorGroups.ts`.

---

## Background — what actually broke

The user corrected two mis-typed tickers (`NOV` was meant to be `NVO`, `ELV` was meant to be `XLV`).
The `watchlist.sector` column was corrected, the taxonomy module was corrected and merged (#340),
and the tags were **still wrong on the dashboard**:

```
NOV  -> ['Healthcare']    should be Energy
ELV  -> ['Sector-ETF']    should be Healthcare
```

Root cause, confirmed by reading both writers:

| method                         | deletes                                | consequence                                           |
| ------------------------------ | -------------------------------------- | ----------------------------------------------------- |
| `replace_taxonomy_memberships` | only `source='taxonomy'` rows          | an inherited row it disagrees with survives           |
| `inherit_sector_memberships`   | **nothing** (`ON CONFLICT DO NOTHING`) | a row whose sector has since changed is never removed |

So each name carried a stale `source='sector'` row from the typo era that no re-seed could clear. A
re-seed would have _added_ the correct chain while leaving the wrong one — `NOV` showing as both
Energy and Healthcare. Fixed in prod by an explicit `DELETE` + re-seed (303 taxonomy / 0 inherited),
but the code that stranded them is unchanged and will strand the next one.

Two adjacent gaps found while tracing it:

- `POST /watchlist` writes **no** chain rows. A ticker added through the web UI is invisible to every
  chain filter until somebody remembers to run the seed script by hand. The seed's
  `active tickers with NO chain: N` line exists because of this.
- `PATCH /watchlist/{ticker}` can change `sector` and **never touches memberships** — this is the
  exact mutation that stranded `NOV` and `ELV`.

## Non-goals

- Not adding a scheduled re-seed job. A cron that rewrites memberships from _deployed_ code would
  silently regress the DB whenever the container lags main — which is the live situation today
  (mini runs v0.12.1, taxonomy fixes are in main). Per-ticker sync keeps the blast radius at one row
  set; a full rewrite on a timer does not.
- Not deleting membership rows for soft-removed tickers. Every read already joins `watchlist` on
  `removed_at IS NULL`, so they are invisible; deleting them would lose history for free.
- Not adding tickers to populate an empty chain — that is a UW budget decision, not a code fix.

---

## Task 1 — `inherit_sector_memberships` reconciles instead of only filling

**File:** `src/uw_scan/storage/watchlist_chain.py`

Delete `source='sector'` rows whose chain no longer matches the ticker's current `watchlist.sector`,
then insert as today. A sector-inherited row that disagrees with the sector it was inherited from is
stale by definition — that is the whole rule, and it needs no new state to express.

Scope the delete to `source='sector'` only. Taxonomy rows are owned by
`replace_taxonomy_memberships` and must not be touched here, or the two methods start fighting over
the same rows depending on call order.

**Tests** (`tests/integration/storage/test_watchlist_chain.py`, alongside the existing suite):

- ticker's sector changes → the old inherited row is gone, the new one is present
- a `source='taxonomy'` row for a _different_ chain is untouched by the reconcile
- re-running the reconcile twice is a no-op (idempotence)

## Task 2 — one per-ticker sync, called from both mutation paths

**Files:** `src/uw_scan/storage/watchlist_chain.py`, `src/uw_scan/api/routers/watchlist.py`

Add `sync_ticker_memberships(ticker, taxonomy_rows, layer_for_chain)` that enforces the invariant for
exactly one ticker.

**Corrected during implementation.** The first version wrote taxonomy rows when the module listed the
ticker and fell back to `sector` only when it did not — which quietly disagreed with the bulk path.
`replace_taxonomy_memberships` + `inherit_sector_memberships` produces **taxonomy ∪ {sector}**: a
ticker enumerated as `Consumer` whose sector is `Healthcare` ends up in both. The per-ticker version
produced only `Consumer`, so a ticker's chains would have depended on which writer last touched it.
The target set is now taxonomy ∪ {sector} in both paths, pinned by a test that runs the bulk pair and
the per-ticker sync over the same ticker and asserts they agree.

Call it from:

- `POST /watchlist` — after the insert, so a newly added ticker is filterable immediately
- `PATCH /watchlist/{ticker}` — only when `sector` is actually part of the patch, so an unrelated
  `pinned`/`hot` toggle does not pay for a membership rewrite

The router already imports `LAYERS` from the taxonomy module, so this adds no new coupling across
layers. The bulk seed script keeps using `replace_taxonomy_memberships` + `inherit_sector_memberships`
— it is the whole-table path and must stay that way to drop orphans the module no longer lists.

**Tests:**

- integration (`tests/integration/api/test_watchlist_endpoint.py`): POST a ticker the taxonomy
  enumerates → its chains exist; POST one it does not → it inherits its sector; PATCH the sector →
  memberships follow and the stale row is gone
- integration (storage): `sync_ticker_memberships` touches only the named ticker's rows

## Task 3 — WITHDRAWN: the rail already does this

Dropped after checking the code. `buildSectorGroups()` already skips zero-count chains
(`sectorGroups.ts`, `if (c.count <= 0) continue;`) and already omits a layer left with no chains —
and `web/tests/unit/filterBar.test.tsx` already asserts it, with `EPC/Construction` at `count: 0` as
the fixture and the case named _"drops chains with no members"_.

So `DevTools/Observability` renders **no rail button at all**. The earlier claim that it "filters to
nothing" was a misreading: the `empty chains: …` line comes from the **seed script**, which reports
it to the operator on purpose. That is a data observation, not a UI defect, and nothing here needs to
change.

What remains is a genuine question but not a bug — see the open item below.

## Task 4 — changelog and verification

- `CHANGELOG.md` `[Unreleased]` — Fixed entry covering the reconcile and the rail, on this branch
  before merge (CHANGELOG rides the feature PR).
- Run the repo's gates: `uv run pytest`, `cd web && npm run test`, `npm run typecheck`, `npm run lint`.
- Re-run the seed against the mini and confirm it stays at `0 inherited`, `active tickers with NO
chain: 0`, and that the four corrected names still resolve.

---

## Verification that the bug is actually dead

The regression test that would have caught the original defect, stated plainly: **add a ticker with
sector A, reconcile, change its sector to B, reconcile again — assert chain A is gone.** Today that
assertion fails. It must pass before this branch merges.

## Open item, deliberately not in scope

`DevTools/Observability` has no members (`GTLB`, `DDOG`, `FROG`, `PD`, `DT` — none held). The UI
already hides it (see withdrawn Task 3), so nothing is broken. The only open question is whether the
chain should be _populated_: `DDOG` is already in `SELECTED_ADDS` and would join it, but adding a
ticker costs roughly 240 UW calls/day and enlists it in every per-ticker job. That is a budget call
to make deliberately, not a side effect of this branch.

## Release coordination

This branch does not cut a release. The taxonomy fixes (#338, #340) are merged to main but the mini
still runs v0.12.1, so its container carries the old taxonomy. Nothing scheduled re-seeds — verified,
no worker job imports `watchlist_taxonomy` — so the prod DB is stable in the meantime. This work is
intended to ride the next patch release together with the other pending branch.
