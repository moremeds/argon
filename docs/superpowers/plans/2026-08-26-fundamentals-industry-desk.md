# Fundamentals Industry Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the PR #383 research backend, build the daily data spine (durable earnings calendar, reaction history, implied move, change events, underwriting features, NI reconciliation, optical routing fix), then ship the three-route fundamentals surface: `/fundamentals` index + Radar triage, `/fundamentals/ai-semi` routing desk, `/fundamentals/ai-semi/[node]` underwriting deep dive.

**Architecture:** Presentation and daily-data layer over the Fundamental PM Research System backend (PR #383) and the chain-analysis-node design. Industry desk reads live warm-store views; node pages render stored versioned reports. Every new read path is zero-vendor-call; every job accrues into Postgres on the existing APScheduler cadence pattern.

**Tech Stack:** Python 3.13 via `uv`, FastAPI + Pydantic v2, psycopg 3, APScheduler 3, Postgres schema `uw_scan`, Next.js 16 + React 19, vitest, pytest + pytest-postgresql.

**Spec:** `docs/superpowers/specs/2026-08-26-fundamentals-industry-desk-design.md` (P1–P3 only; the spec's P4 — guidance extraction from 8-Ks and agent narrative — is explicitly "direction, not commitment" and is EXCLUDED from this plan).

## Global Constraints

Copied from the spec and the repo's standing rules; every task's requirements implicitly include these.

- **No cross-sectional ranking or composite anywhere on the desk.** No `sort` parameter over any cross-name value; lists order by recency/chain-position/alphabet only.
- **Median + per-name dots, never revenue-weighted** for any chain-level metric.
- **No dollar sums over many-to-many membership.** Any count dedupes by ticker; any dollar aggregate requires a declared primary chain or is refused outright.
- **Coverage names the missing tickers.** Never render a bare n/N.
- **Reported/awaiting cohort split.** `fundamental_scores.as_of` is a cross-section identifier; when a chain's members straddle two buckets, render two cohorts, never a merged list.
- **Per-chain valuation percentiles are presentations of NAME facts.** No median, mean, or any aggregate over own-history percentiles at chain grain — dots only, framed as name-level positions (spec §3 anti-requirement: a "chain percentile distribution" must never be spoken of as a chain property).
- **The industry desk carries no inventory panel.** Inventory divergence is name-grain only; it lives on node pages (spec §3 anti-requirement).
- **Hatched abstentions, never blank.** An empty cell states which of the six `FundamentalResultState` values it is in (`ok | stale_run | no_compatible_run | no_coverage | unsupported_capability | failed_run`, `src/uw_scan/models/radar.py`).
- **The node page renders STORED report blocks, never live re-assembly.**
- **Delta rail orders by `first_known_at`,** not `occurred_at`.
- **No propagation or lead-lag arrows** in profit-pool migration. Layers side by side only.
- **Implied-move coverage labeled "not covered", never blank.**
- **`uv` only** — `uv run pytest`, never bare `pytest`/`python`.
- **Migrations idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`); duplicate migration prefix is a CI gate — if a number is taken by the time a task runs, renumber the whole new chain, never fork a prefix.
- **Zero vendor calls on all new read paths and desk/node API endpoints.**
- **Tests use real tickers at real values, frozen.** Where a task's test needs a market value not present in this plan, the task carries an explicit AUTHORING STEP that fetches the real value once (from the warm store or the named source), hardcodes it with an as-of comment, and the test never touches the network. Do not invent prices; the no-fabrication rule outranks the no-placeholder rule.
- **Storage:** new domains get their own module under `src/uw_scan/storage/`; `repository.py` is assembly/re-export only — never add query methods there.
- **API:** read-only routers; response models in `src/uw_scan/models/` (export via `models/__init__.py`); after any API change run `cd web && npm run gen:types` and commit `web/lib/types.ts`.
- **CHANGELOG rides each feature PR** — add the `[Unreleased]` entry on the branch before merge.
- **Never push `main` directly; every merge goes through a PR with green CI.** No `Co-Authored-By` trailers.
- **Worktrees live in `.worktrees/<branch-slug>/`.** The existing `.worktrees/fundamental-pm-research-system/` belongs to the rewrite session — read-only until P1 Task 1 coordinates the handoff.
- Commit steps inside tasks execute only during plan execution, which the user triggers.

## Phase gate

**P2 and P3 tasks MUST NOT start until Task 2 (PR #383 merge) has landed on `main`.** The modules they import — `storage/research_events.py`, `storage/research_reports.py`, `storage/research_taxonomy.py`, `fundamentals/chain_nodes.py`, `fundamentals/dimensions.py`, `models/radar.py`, migrations for `sec_filing_index` / `fundamental_dimensions` / `research_*` tables — exist only on the `feat/fundamental-pm-research-system` branch today.

## Branch / PR map

| Phase          | Branch                                                   | PR                                                                                                                                                                                        |
| -------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P1 Tasks 1–2   | `feat/fundamental-pm-research-system` (existing PR #383) | merge #383                                                                                                                                                                                |
| P1 Task 3      | `feat/datacenter-chain-seed`                             | small standalone PR — justified split: it is an independent prerequisite for node pages that can land and deploy immediately after #383, while the data-spine PR is still weeks of review |
| P2 Tasks 4–11  | `feat/fundamentals-data-spine`                           | one PR                                                                                                                                                                                    |
| P3 Tasks 12–18 | `feat/fundamentals-desk-pages`                           | one PR                                                                                                                                                                                    |

---

# Phase P1 — land the foundation

### Task 1: Commit the optical research dir onto the #383 branch

Coordination task, no TDD. The dir `docs/research/2026-08-26-optical-chain-pm-desk/` is **untracked** inside `.worktrees/fundamental-pm-research-system/` (verified 2026-08-26: contains `VERDICT.md`, `dataset.json`, `scripts/{build.py,page_data.py,prod_pull.sh}`). `scripts/page_data.py` imports an `alldata.json` that exists nowhere — unreconstructable; do not try to rebuild it.

**Files:**

- Create (git-add only): `docs/research/2026-08-26-optical-chain-pm-desk/**` on branch `feat/fundamental-pm-research-system`
- Modify: `docs/research/2026-08-26-optical-chain-pm-desk/VERDICT.md` (append provenance note)

- [ ] **Step 1: Coordinate with the rewrite session.** This worktree belongs to the "Fundamental PM Research System 重写" background session. Before touching it, confirm that session's current pass is complete (the orchestrating session handles this; if you are an executor subagent and cannot confirm, STOP and report back rather than editing a live worktree).
- [ ] **Step 2: Append the provenance note** to the end of `VERDICT.md`:

```markdown
## Provenance caveat (added at commit time, 2026-08-26)

`scripts/page_data.py` imports an `alldata.json` that was never committed and is
unreconstructable — it was the sole source of the published artifact's earnings
calendar, implied moves, and reaction history. Those inputs are being given a
durable, jobs-fed home by the fundamentals data spine
(`docs/superpowers/specs/2026-08-26-fundamentals-industry-desk-design.md` §5);
this dir is committed as-is for archaeological recoverability, not as a working
pipeline. `prod_pull.sh` + `build.py` + `dataset.json` remain reproducible.
```

- [ ] **Step 3: Commit inside the worktree**

```bash
cd .worktrees/fundamental-pm-research-system
git add docs/research/2026-08-26-optical-chain-pm-desk/
git commit -m "docs(research): commit the optical chain PM desk research dir with provenance caveat"
```

### Task 2: Renumber the migration collision, rebase, and merge PR #383

Coordination task, no TDD. **Collision as executed:** `main` owns `130_macro_context_snapshots.sql` and `131_macro_evidence_invalidations.sql`. The rebase dropped the branch's earlier merge commits — which had carried a first renumber — so the branch chain came back to disk at **130–141** and collided at BOTH 130 and 131. The chain therefore shifted by **+2** to **132–143**: `132_fundamental_obs_availability.sql` … `143_research_reports.sql`.

**Files:**

- Renamed (on the branch): `130_fundamental_obs_availability.sql` → `132_…` … `141_research_reports.sql` → `143_research_reports.sql` (12 files, `git mv`)
- Modified: every file referencing the old numbers. **References were NOT uniformly offset** — commits written before the dropped merges cited 130–141, commits written after cited 131–142, so each reference was resolved by the TABLE it names, never by an offset.

- [ ] **Step 1: Rebase the branch on main**

```bash
cd .worktrees/fundamental-pm-research-system
git fetch origin && git rebase origin/main
```

Resolve conflicts as they surface. Keep main's `130_macro_context_snapshots.sql` and `131_macro_evidence_invalidations.sql`; `git mv` every branch-added migration up by two (130→132, 131→133, … 141→143), descending so no target is occupied.

- [ ] **Step 2: Fix references to the renamed numbers.** Grep for `1[34][0-9]_` and the prose forms (`migration 138`, `migrations 138–139`) across `src/`, `tests/`, `docs/`, `scripts/`, `web/`, `CHANGELOG.md`, `CLAUDE.md`. Resolve each by the table it names against the canonical map, not by an offset. Do NOT touch references to main's own 113–131 files, and note that `130`/`131` now mean main's macro migrations.
- [ ] **Step 3: Verify migrations apply clean on a fresh test DB**

Run: `uv run pytest tests/integration/storage/test_research_reports.py -v` (the per-fixture `DROP SCHEMA CASCADE` + re-migrate exercises the full renamed chain)
Expected: PASS

- [ ] **Step 4: Push and wait for CI**

```bash
git push --force-with-lease origin feat/fundamental-pm-research-system
gh pr checks 383 --watch
```

Expected: all checks green. Never merge before CI is green.

- [ ] **Step 5: Merge the PR** (squash per repo convention), then in the PRIMARY repo `git checkout main && git pull`, and remove the worktree once the rewrite session confirms it is done with it: `git worktree remove .worktrees/fundamental-pm-research-system`.

### Task 3: Seed the five datacenter chains as ChainSpecs

TDD task on new branch `feat/datacenter-chain-seed` (from post-merge `main`). A node is data, not code: this task adds `ChainSpec` rows to the catalogue and a generic seeding function; **no assembler change** (the extension contract of spec §2 — if this task needs an assembler edit, stop and report the contract broken).

Layer design (reviewable data, deliberately minimal): each datacenter chain is one real layer of the datacenter build-out; ranks follow build-out reading order, sparse per the `research_chains` convention. Intra-chain layer splits are NOT invented here — a later discovery slots in between sparse ranks.

**Files:**

- Modify: `src/uw_scan/fundamentals/chain_nodes.py` (add 5 `ChainSpec` constants + `DATACENTER_CHAINS` tuple)
- Modify: `src/uw_scan/worker/jobs/research_taxonomy_seed.py` (add `seed_chain_spec`)
- Test: `tests/integration/storage/test_datacenter_chain_seed.py`

**Interfaces:**

- Consumes: `ChainSpec`, `Layer` (`fundamentals/chain_nodes.py`); `ResearchTaxonomyRepository.define_chains(version, rows)` and `.add_membership(version, chain=, layer=, ticker=, evidence_class=, approved_by=, note=)` (`storage/research_taxonomy.py`); `TAXONOMY_V1 = "argon-research-v1"`.
- Produces: `seed_chain_spec(conn, spec: ChainSpec, *, schema="uw_scan", version=TAXONOMY_V1) -> dict[str, int]` — defines the spec's layer rows and re-homes the chain's existing mirrored memberships onto the spec's layer (returns `{"layers": n, "memberships": n}`). `DATACENTER_CHAINS: tuple[ChainSpec, ...]`.

- [ ] **Step 1: Write the failing test**

```python
"""Standing up a datacenter node is taxonomy rows, not code (spec §2 contract)."""
from uw_scan.fundamentals.chain_nodes import DATACENTER_CHAINS
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository
from uw_scan.worker.jobs.research_taxonomy_seed import (
    TAXONOMY_V1,
    mirror_watchlist_chain,
    seed_chain_spec,
)

EXPECTED = {
    "EPC/Construction": 10,
    "Generation/Nuclear": 20,
    "Power/Electrical": 30,
    "Cooling/Thermal": 40,
    "DC-REIT/Colo": 50,
}


def test_five_datacenter_chains_declared_in_buildout_order():
    assert {c.chain for c in DATACENTER_CHAINS} == set(EXPECTED)
    for spec in DATACENTER_CHAINS:
        assert len(spec.layers) == 1
        assert spec.layers[0].rank == EXPECTED[spec.chain]


def test_seed_replaces_placeholder_layer_with_real_rank(seeded_db_empty_cards):
    conn, schema = seeded_db_empty_cards.conn, seeded_db_empty_cards._schema
    mirror_watchlist_chain(conn, schema=schema)  # placeholder rail
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    for spec in DATACENTER_CHAINS:
        counters = seed_chain_spec(conn, spec, schema=schema)
        assert counters["layers"] == 1
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT chain, layer, layer_rank FROM {schema}.research_chains
                 WHERE taxonomy_version = %s AND chain = ANY(%s)""",
            (TAXONOMY_V1, list(EXPECTED)),
        )
        rows = cur.fetchall()
    ranks = {chain: rank for chain, _layer, rank in rows if rank > 0}
    assert ranks == EXPECTED
```

NOTE — the seeded-DB fixture on `main` may not create `watchlist_chain` rows for these chains; if `mirror_watchlist_chain` mirrors nothing for them, seed two real membership rows first in the test (real tickers from the measured cohort, e.g. `VRT` in Cooling/Thermal and `EQIX` in DC-REIT/Colo — both verified members of the argon universe per the chain-node design's 2026-08-26 measurement table). Adjust column names to migration `139_research_taxonomy.sql`'s actual schema (renumbered to `139_` by Task 2 — read the file, do not trust this plan's memory of it).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_datacenter_chain_seed.py -v`
Expected: FAIL with `ImportError: cannot import name 'DATACENTER_CHAINS'`

- [ ] **Step 3: Implement.** In `chain_nodes.py`, after `OPTICAL_COMMUNICATION`:

```python
#: The datacenter build-out siblings (spec §2). Every member is already in the
#: universe; 42 of 44 carry statements (measured 2026-08-26, DC-REIT/Colo 4/6).
#: One real layer per chain: the chain IS a layer of the build-out; intra-chain
#: splits wait for a discovery and slot into the sparse ranks.
DATACENTER_CHAINS: tuple[ChainSpec, ...] = (
    ChainSpec("dc_buildout", "EPC/Construction",
              (Layer("EPC-Construction", 10, "design, engineering, construction of datacenter shells"),)),
    ChainSpec("dc_buildout", "Generation/Nuclear",
              (Layer("Generation", 20, "power generation and nuclear capacity"),)),
    ChainSpec("dc_buildout", "Power/Electrical",
              (Layer("Power-Electrical", 30, "electrical distribution, switchgear, UPS"),)),
    ChainSpec("dc_buildout", "Cooling/Thermal",
              (Layer("Cooling-Thermal", 40, "liquid and air cooling, thermal management"),)),
    ChainSpec("dc_buildout", "DC-REIT/Colo",
              (Layer("DC-REIT-Colo", 50, "datacenter REITs and colocation operators"),)),
)
```

(Match `ChainSpec`'s positional/keyword signature as actually declared — it is `domain, chain, layers, aliases=()`.) In `research_taxonomy_seed.py`:

```python
def seed_chain_spec(
    conn: psycopg.Connection,
    spec: "ChainSpec",
    *,
    schema: str = "uw_scan",
    version: str = TAXONOMY_V1,
) -> dict[str, int]:
    """Give one chain its real layer set and re-home its memberships onto it.

    Standing up a node is three kinds of row and no assembler logic (chain-node
    design §3). Placeholder layers (rank 0) are superseded, not deleted: the
    new layer rows land beside them and memberships move.
    """
    repo = ResearchTaxonomyRepository(conn, schema=schema)
    repo.define_chains(
        version,
        [
            {
                "domain": spec.domain,
                "chain": spec.chain,
                "layer": layer.layer,
                "layer_rank": layer.rank,
                "description": layer.description,
            }
            for layer in spec.layers
        ],
    )
    moved = 0
    if len(spec.layers) == 1:
        # Retire-and-reinsert, never UPDATE layer in place: open membership
        # identity is the partial unique index chain_membership_open_uq
        # (taxonomy_version, chain, layer, ticker) WHERE valid_to IS NULL, and
        # the table is temporally versioned — reads filter valid_to IS NULL.
        target = spec.layers[0].layer
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker FROM {schema}.chain_membership
                     WHERE taxonomy_version = %s AND chain = %s
                       AND layer <> %s AND valid_to IS NULL""",
                (version, spec.chain, target),
            )
            tickers = [t for (t,) in cur.fetchall()]
            cur.execute(
                f"""UPDATE {schema}.chain_membership
                       SET valid_to = now()
                     WHERE taxonomy_version = %s AND chain = %s
                       AND layer <> %s AND valid_to IS NULL""",
                (version, spec.chain, target),
            )
        for ticker in tickers:
            moved += repo.add_membership(
                version,
                chain=spec.chain,
                layer=target,
                ticker=ticker,
                evidence_class="mirrored",
                approved_by="seed_chain_spec",
                note=f"re-homed from placeholder layer onto {target}",
            )
    conn.commit()
    counters = {"layers": len(spec.layers), "memberships": moved}
    log.info("seed_chain_spec %s: %s", spec.chain, counters)
    return counters
```

Adjust column names to the real `chain_membership` schema (read the renumbered migration first) and match `add_membership`'s actual keyword surface.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/storage/test_datacenter_chain_seed.py tests/integration/storage/test_research_reports.py -v`
Expected: PASS (including the untouched catalogue↔assembler binding test — proof no assembler change was needed)

- [ ] **Step 5: CHANGELOG + commit + PR**

Add under `[Unreleased]`: `- Seed the five datacenter build-out chains (EPC/Construction, Generation/Nuclear, Power/Electrical, Cooling/Thermal, DC-REIT/Colo) with real layer ranks — taxonomy rows only, zero assembler change, zero vendor calls.`

```bash
git checkout -b feat/datacenter-chain-seed
git add src/uw_scan/fundamentals/chain_nodes.py src/uw_scan/worker/jobs/research_taxonomy_seed.py tests/integration/storage/test_datacenter_chain_seed.py CHANGELOG.md
git commit -m "feat(fundamentals): seed the five datacenter chains as chain-analysis nodes"
git push -u origin feat/datacenter-chain-seed && gh pr create --fill
```

Wait for CI green, then merge.

---

# Phase P2 — data spine (branch `feat/fundamentals-data-spine`)

All tasks on one branch cut from `main` after Task 3 merges. Migration numbers assume `main` tops out at `143_research_reports.sql` after P1 — **verify with `ls src/uw_scan/storage/migrations/ | tail -3` before writing each migration and renumber the whole new chain if anything moved.**

### Task 4: Durable earnings calendar — migration 144 + storage module

Spec §5-i. Today `sources/earnings_calendar.py::fetch_calendar_symbols` returns a transient same-day `set[str]`; nothing durable exists.

**Files:**

- Create: `src/uw_scan/storage/migrations/144_earnings_calendar.sql`
- Create: `src/uw_scan/storage/earnings_calendar.py`
- Test: `tests/integration/storage/test_earnings_calendar.py`

**Interfaces:**

- Produces: `EarningsCalendarRepository(conn, schema="uw_scan")` with
  - `upsert_rows(rows: Sequence[dict]) -> int` — rows carry `ticker, report_date (date), session ('premarket'|'afterhours'|None), source (str)`; returns rows genuinely new. ON CONFLICT fills a NULL `session` via COALESCE (a column left out of the SET list is write-once — the late-known session must be recoverable) and never overwrites a known session with NULL.
  - `next_prints(*, on_or_after: date, tickers: Sequence[str] | None = None) -> list[dict]` — upcoming rows, each `{ticker, report_date, session, source}`.
  - `prints_between(start: date, end: date) -> list[dict]`

- [ ] **Step 1: Write the migration**

```sql
-- 144_earnings_calendar.sql
-- Durable earnings calendar (spec 2026-08-26-fundamentals-industry-desk §5-i).
-- Accrues forward-only from the UW classified calendar; the ~2% of names UW
-- reports as report_time "unknown" appear in NEITHER slot and land here with
-- session NULL via the statement-obs discovery path — never dropped.
CREATE TABLE IF NOT EXISTS uw_scan.earnings_calendar (
  ticker        TEXT NOT NULL,
  report_date   DATE NOT NULL,
  session       TEXT CHECK (session IN ('premarket', 'afterhours')),
  source        TEXT NOT NULL,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, report_date)
);
CREATE INDEX IF NOT EXISTS idx_earnings_calendar_date
  ON uw_scan.earnings_calendar (report_date);
```

- [ ] **Step 2: Write the failing test**

```python
"""The calendar accrues; a late-known session fills in and never regresses."""
from datetime import date

from uw_scan.storage.earnings_calendar import EarningsCalendarRepository

# Real event, frozen: NVDA reported Q2 FY2027 after the close on 2026-08-26
# (verified against the UW calendar at authoring time).
NVDA = {"ticker": "NVDA", "report_date": date(2026, 8, 26),
        "session": "afterhours", "source": "uw_calendar"}


def _repo(seeded) -> EarningsCalendarRepository:
    return EarningsCalendarRepository(seeded.conn, schema=seeded._schema)


def test_upsert_accrues_and_null_session_fills_late(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    unknown = {"ticker": "ISRG", "report_date": date(2026, 7, 16),
               "session": None, "source": "statement_obs"}
    assert repo.upsert_rows([NVDA, unknown]) == 2
    assert repo.upsert_rows([NVDA]) == 0  # touch, not insert
    # session becomes known later — must fill, and a NULL must never clobber
    assert repo.upsert_rows([dict(unknown, session="afterhours",
                                  source="uw_calendar")]) == 0
    rows = repo.prints_between(date(2026, 7, 1), date(2026, 9, 1))
    by_t = {r["ticker"]: r for r in rows}
    assert by_t["ISRG"]["session"] == "afterhours"
    # a NULL must never clobber a known session — re-read AFTER the upsert
    assert repo.upsert_rows([dict(NVDA, session=None)]) == 0
    after = {r["ticker"]: r for r in repo.prints_between(date(2026, 7, 1), date(2026, 9, 1))}
    assert after["NVDA"]["session"] == "afterhours"
    assert {r["ticker"] for r in repo.next_prints(on_or_after=date(2026, 8, 20))} == {"NVDA"}
```

AUTHORING STEP: confirm the NVDA and ISRG dates against the warm store or UW before freezing (`ISRG` 2026-07-16 is the report date named in the filing-date-recovery verdict as calendar-absent; re-verify, and substitute any real verified pair if either date is wrong).

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_earnings_calendar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.storage.earnings_calendar'`

- [ ] **Step 4: Implement the repository**

```python
"""Durable earnings calendar (spec §5-i). Forward-accruing; insert-or-touch."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg


class EarningsCalendarRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.earnings_calendar
                        (ticker, report_date, session, source)
                 VALUES (%(ticker)s, %(report_date)s, %(session)s, %(source)s)
            ON CONFLICT (ticker, report_date) DO UPDATE SET
                 -- late-known session fills in; a NULL never clobbers a value
                 session      = COALESCE(uw_scan.earnings_calendar.session,
                                         EXCLUDED.session),
                 source       = CASE WHEN uw_scan.earnings_calendar.session IS NULL
                                      AND EXCLUDED.session IS NOT NULL
                                     THEN EXCLUDED.source
                                     ELSE uw_scan.earnings_calendar.source END,
                 last_seen_at = now()
              RETURNING (xmax = 0) AS inserted
        """
        inserted = 0
        with self.conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, {**row, "ticker": row["ticker"].upper()})
                if cur.fetchone()[0]:
                    inserted += 1
        self.conn.commit()
        return inserted

    def next_prints(
        self, *, on_or_after: date, tickers: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        sql = f"""SELECT ticker, report_date, session, source
                    FROM {self._schema}.earnings_calendar
                   WHERE report_date >= %s"""
        params: list[Any] = [on_or_after]
        if tickers is not None:
            sql += " AND ticker = ANY(%s)"
            params.append([t.upper() for t in tickers])
        sql += " ORDER BY report_date, ticker"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def prints_between(self, start: date, end: date) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, report_date, session, source
                      FROM {self._schema}.earnings_calendar
                     WHERE report_date BETWEEN %s AND %s
                     ORDER BY report_date, ticker""",
                (start, end),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
```

Qualify the ON CONFLICT SET's target-table references with the schema variable — write `{self._schema}.earnings_calendar.session` (and the same for `source`), not the hardcoded `uw_scan.` shown above; the test schema is not named `uw_scan`, and a schema-qualified target reference in DO UPDATE SET is legal Postgres.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/integration/storage/test_earnings_calendar.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/144_earnings_calendar.sql src/uw_scan/storage/earnings_calendar.py tests/integration/storage/test_earnings_calendar.py
git commit -m "feat(fundamentals): durable earnings calendar table + repository"
```

### Task 5: Calendar persist rides the daily ingest

Spec §5-i, the job half. `fetch_calendar_symbols` collapses session identity; add a listings variant and persist during `fundamental_ingest_daily` (04:20 ET, uw-0). Also: when the daily ingest lands a statement for a name with no calendar row for that period (the ~2% unknowns), insert `session=NULL, source='statement_obs'`.

**Files:**

- Modify: `src/uw_scan/sources/earnings_calendar.py` (add `fetch_calendar_listings`; `fetch_calendar_symbols` delegates)
- Modify: `src/uw_scan/worker/jobs/fundamental_ingest_daily.py` (persist listings + statement-discovered rows)
- Create: `scripts/backfill/earnings_calendar_backfill.py` (committed runner — also Task 17's seeding path; no /tmp one-offs)
- Test: `tests/unit/test_earnings_calendar_source.py`, extend the existing ingest-daily test file (find it: `grep -rln fundamental_ingest_daily tests/`)

**Interfaces:**

- Produces: `fetch_calendar_listings(client, report_date, *, max_pages=MAX_PAGES) -> list[CalendarListing]` where `CalendarListing` is a frozen dataclass `(symbol: str, session: str)` with session `'premarket'|'afterhours'` mapped from the slug (`EARNINGS_PREMARKET → 'premarket'`, `EARNINGS_AFTERHOURS → 'afterhours'`).
- Consumes: `EarningsCalendarRepository.upsert_rows` (Task 4).

- [ ] **Step 1: Write the failing unit test** — mock the UW client exactly the way the existing tests for this source do (find them: `grep -rln fetch_calendar_symbols tests/`), asserting (a) listings carry the right session per slot, (b) `fetch_calendar_symbols` returns the same set it did before (contract preserved), (c) pagination behavior unchanged. Use the real symbol names from the existing test's fixture data.
- [ ] **Step 2: Run to verify failure** (`ImportError: fetch_calendar_listings`).
- [ ] **Step 3: Implement.** Refactor the loop body of `fetch_calendar_symbols` into `fetch_calendar_listings` (same pagination, same never-raise contract); `fetch_calendar_symbols` becomes `{l.symbol for l in fetch_calendar_listings(...)}`. Session mapping: `{EndpointSlug.EARNINGS_PREMARKET: "premarket", EndpointSlug.EARNINGS_AFTERHOURS: "afterhours"}`.
- [ ] **Step 4: Wire persistence into `fundamental_ingest_daily`.** Read the job first. For each date it scans (its `lookback_days` window): call `fetch_calendar_listings`, then `EarningsCalendarRepository(conn, schema=schema).upsert_rows([{"ticker": l.symbol, "report_date": d, "session": l.session, "source": "uw_calendar"} for l in listings])`. After the statement-ingest phase, for each ticker that landed a NEW statement in this run whose `filing_published_at` date has no calendar row: upsert `{"ticker": t, "report_date": published_date, "session": None, "source": "statement_obs"}`. Add the persist counts to the job's returned counters (`calendar_rows`, `calendar_unknown_rows`). One extra fetch per scanned date is already paid — the listings call replaces the symbols call, zero added UW spend.
- [ ] **Step 5: Extend the ingest-daily integration test** to assert calendar rows exist after a run (mock client serving the existing fixture payloads).
- [ ] **Step 5b: Committed runner** `scripts/backfill/earnings_calendar_backfill.py`: argparse `--start --end --execute` (dry-run default; mirror the DB/client bootstrap of an existing backfill script, e.g. `scripts/backfill/theta_harvester_backfill.py`) that calls `fetch_calendar_listings` + `EarningsCalendarRepository.upsert_rows` per date in the range. This is both the historical-calendar backfill (the endpoint takes a `date` param; verified retrievable for recent history in the filing-date-recovery verdict — the script prints per-date row counts so a range UW no longer serves is visible, not silent) and Task 17's local seeding path — never a /tmp one-off.
- [ ] **Step 6: Run the full affected set**

Run: `uv run pytest tests/unit/test_earnings_calendar_source.py tests/integration -k "ingest_daily or earnings_calendar" -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A src tests
git commit -m "feat(fundamentals): persist the earnings calendar from the daily ingest, sessions preserved"
```

### Task 6: Earnings reaction history — migration 145 + job + backfill

Spec §5-ii. Today `uw_positioning.earn_reactions_positive/total` is a win-count over the last 4, no magnitude, no dates. Compute per-print reactions from calendar × `uw_scan.daily_ohlc` (columns verified: `ticker, date, open, high, low, close NOT NULL, volume, source`).

Reaction windows (documented in the module docstring):

- `premarket` print on day D: before = last close < D; after = first close ≥ D.
- `afterhours` print on day D: before = last close ≤ D; after = first close > D.
- `session NULL`: before = last close < D; after = first close > D (spans both possible windows; the stored NULL session labels the wider basis).
- `pct_move = close_after / close_before − 1`. A row is written only when both closes exist; otherwise skipped and retried next run (the calendar row persists).

**Files:**

- Create: `src/uw_scan/storage/migrations/145_earnings_reactions.sql`
- Create: `src/uw_scan/storage/earnings_reactions.py`
- Create: `src/uw_scan/worker/jobs/earnings_reactions.py`
- Modify: `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`
- Create: `scripts/backfill/earnings_reactions_backfill.py`
- Test: `tests/integration/storage/test_earnings_reactions.py`

**Interfaces:**

- Produces: table `earnings_reactions (ticker, report_date PK pair, session, close_before_date, close_before, close_after_date, close_after, pct_move, computed_at)`; `EarningsReactionsRepository` with `upsert_rows(rows) -> int`, `last_reactions(ticker, n=4) -> list[dict]` (newest first), `reactions_for(tickers) -> dict[str, list[dict]]`; job `earnings_reactions_compute(conn, *, as_of: date, lookback_days: int = 10, schema="uw_scan") -> dict[str,int]`.
- Consumes: `EarningsCalendarRepository.prints_between` (Task 4); `daily_ohlc`.
- Config: `earnings_reactions_enabled` (env `UW_SCAN_EARNINGS_REACTIONS_ENABLED`, default True), massive-0 lane, 19:40 ET daily — copy the exact `_should_schedule_*` + registration shape of an existing massive-0 nightly (e.g. the vrp_markout registration; read `scheduler.py` and mirror it).

- [ ] **Step 1: Migration**

```sql
-- 145_earnings_reactions.sql
-- Per-print percentage reaction (spec §5-ii). Backfillable from OHLC history;
-- rows are complete facts (both closes present) — a pending print is absent,
-- not null, and the calendar row is what says it is expected.
CREATE TABLE IF NOT EXISTS uw_scan.earnings_reactions (
  ticker            TEXT NOT NULL,
  report_date       DATE NOT NULL,
  session           TEXT,
  close_before_date DATE NOT NULL,
  close_before      NUMERIC NOT NULL,
  close_after_date  DATE NOT NULL,
  close_after       NUMERIC NOT NULL,
  pct_move          NUMERIC NOT NULL,
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, report_date)
);
CREATE INDEX IF NOT EXISTS idx_earnings_reactions_ticker
  ON uw_scan.earnings_reactions (ticker, report_date DESC);
```

- [ ] **Step 2: Failing test.** AUTHORING STEP: pick one real print already in the warm store's history — e.g. NVDA's 2026-05-28 afterhours print — and freeze the two real closes around it by querying the dev DB's `daily_ohlc` (or massive) ONCE; hardcode with an as-of comment. Test seeds `daily_ohlc` with those frozen rows + the calendar row, runs `earnings_reactions_compute`, asserts one row with `pct_move == close_after/close_before - 1` (exact frozen values), asserts a print with a missing after-close writes nothing, and asserts `last_reactions("NVDA", n=4)` returns newest-first.
- [ ] **Step 3: Run to verify failure** (`ModuleNotFoundError`).
- [ ] **Step 4: Implement repository + job.** Job core:

```python
def earnings_reactions_compute(
    conn, *, as_of: date, lookback_days: int = 10, schema: str = "uw_scan"
) -> dict[str, int]:
    cal = EarningsCalendarRepository(conn, schema=schema)
    repo = EarningsReactionsRepository(conn, schema=schema)
    prints = cal.prints_between(as_of - timedelta(days=lookback_days), as_of)
    rows, skipped = [], 0
    with conn.cursor() as cur:
        for p in prints:
            d, session = p["report_date"], p["session"]
            before_op = "<" if session != "afterhours" else "<="
            after_op = ">=" if session == "premarket" else ">"
            cur.execute(
                f"""SELECT date, close FROM {schema}.daily_ohlc
                     WHERE ticker = %s AND date {before_op} %s
                     ORDER BY date DESC LIMIT 1""",
                (p["ticker"], d),
            )
            before = cur.fetchone()
            cur.execute(
                f"""SELECT date, close FROM {schema}.daily_ohlc
                     WHERE ticker = %s AND date {after_op} %s
                     ORDER BY date ASC LIMIT 1""",
                (p["ticker"], d),
            )
            after = cur.fetchone()
            if not before or not after:
                skipped += 1
                continue
            rows.append({
                "ticker": p["ticker"], "report_date": d, "session": session,
                "close_before_date": before[0], "close_before": before[1],
                "close_after_date": after[0], "close_after": after[1],
                "pct_move": float(after[1]) / float(before[1]) - 1.0,
            })
    written = repo.upsert_rows(rows)
    return {"prints": len(prints), "written": written, "skipped_incomplete": skipped}
```

Repository `upsert_rows` mirrors Task 4's insert-or-touch shape (`ON CONFLICT (ticker, report_date) DO NOTHING` — a computed reaction is a fact and never silently recomputed; recompute requires an explicit delete).

- [ ] **Step 5: Scheduler + config wiring** per the interface block. Run `uv run pytest tests/unit -k scheduler -v` if scheduler unit tests exist.
- [ ] **Step 6: Backfill script** `scripts/backfill/earnings_reactions_backfill.py`: argparse `--start --end --execute` (dry-run default, per existing backfill script conventions — read one, e.g. `scripts/backfill/theta_harvester_backfill.py`, and mirror its DB bootstrap). Date source for history predating the calendar table: distinct `(ticker, filing_published_at::date)` from `fundamental_statement_obs` where `filing_published_at IS NOT NULL` — inserted as calendar rows `source='statement_obs', session=NULL` then computed by the same `earnings_reactions_compute` core (no duplicate logic). Print a summary; persist everything before exit.
- [ ] **Step 7: Run tests, then commit**

Run: `uv run pytest tests/integration/storage/test_earnings_reactions.py -v` → PASS

```bash
git add -A src tests scripts
git commit -m "feat(fundamentals): per-print earnings reaction history, computed from calendar x OHLC"
```

### Task 7: Implied move — migration 146 + nightly snapshot job

Spec §5-iii. Derive from `option_surface_grid_daily` (PK `(ticker, market_date, expiry, strike)`, columns `call_iv, put_iv, underlying_spot` verified) for names with a known next print. Formula — documented, versioned in the module: ATM straddle ≈ `0.7979 · σ_atm · √(T)` of spot (Brenner–Subrahmanyam approximation), `σ_atm` = mean of `call_iv` and `put_iv` at the strike nearest spot on the covering expiry, `T` = calendar days from `market_date` to expiry / 365. Covering expiry = first expiry ≥ the print's reaction day (report_date for premarket, report_date+1 day for afterhours/NULL). Coverage is honest: a name with no surface rows tonight gets NO row, and the API layer renders "not covered" — never blank, never interpolated.

**Files:**

- Create: `src/uw_scan/storage/migrations/146_implied_move_daily.sql`
- Create: `src/uw_scan/storage/implied_move.py`
- Create: `src/uw_scan/worker/jobs/implied_move_snapshot.py`
- Create: `scripts/backfill/implied_move_backfill.py` (committed runner: `--start --end --execute`, dry-run default, calls `implied_move_snapshot` per `market_date` — genuinely useful backfill since the surface accrues 2025-12-26→present, and Task 17's seeding path)
- Modify: `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`
- Test: `tests/integration/storage/test_implied_move.py`

**Interfaces:**

- Produces: table `implied_move_daily (ticker, market_date) PK` + `report_date, expiry, strike, atm_iv, spot, implied_move_pct, implied_move_usd, computed_at`; `ImpliedMoveRepository.upsert_rows(rows) -> int`, `.latest_for(tickers) -> dict[str, dict]` (newest `market_date` per ticker), `.history(ticker, report_date) -> list[dict]` (per-day path into one print — the delta-rail shift events read this); job `implied_move_snapshot(conn, *, as_of: date, schema="uw_scan") -> dict[str,int]`.
- Consumes: `EarningsCalendarRepository.next_prints` (Task 4), `option_surface_grid_daily`.
- Config: `implied_move_snapshot_enabled` (env `UW_SCAN_IMPLIED_MOVE_SNAPSHOT_ENABLED`, default True), massive-0 lane, 20:45 ET weekdays (after the 19:00/19:30 surface capture jobs). Zero vendor calls.

- [ ] **Step 1: Migration** (same idempotent shape as 145; comment states the formula, its 0.7979 constant, and that absence-of-row IS the coverage statement).
- [ ] **Step 2: Failing test.** Seed `option_surface_grid_daily` with a small real frozen grid — AUTHORING STEP: pull one real ticker's real ATM vicinity (3 strikes, 1 expiry) for one `market_date` from the dev warm store ONCE and freeze it (comment the pull date; the surface accrues 2025-12-26→present, so any watchlist name works). Seed a calendar row for a print before that expiry. Assert: exactly one `implied_move_daily` row; `strike` is the grid strike nearest `underlying_spot`; `implied_move_pct == 0.7979 * atm_iv * sqrt(days/365)` computed from the frozen values; a second ticker with a calendar row but NO surface rows produces NO row.
- [ ] **Step 3: Run to verify failure.**
- [ ] **Step 4: Implement.** Job: `next_prints(on_or_after=as_of)` limited to the next 21 calendar days; for each ticker, read tonight's (`market_date = as_of`) surface rows; pick covering expiry, nearest strike, mean of non-null `call_iv`/`put_iv` (one-sided is allowed and used as-is — record which side in a `basis` text column if only one leg exists: add `iv_basis TEXT NOT NULL DEFAULT 'both'` (`'both'|'call_only'|'put_only'`) to the migration); write row. Counters: `{prints_upcoming, covered, not_covered}` — log the not-covered count (no silent caps).
- [ ] **Step 5: Scheduler + config wiring**, mirroring Task 6's massive-0 registration; write the backfill runner listed in Files (backfilling a past `market_date` passes that date as `as_of` so the covering-expiry pick replays point-in-time).
- [ ] **Step 6: Run tests to verify they pass**, then commit

```bash
git add -A src tests scripts
git commit -m "feat(fundamentals): nightly implied-move snapshot from the option surface grid"
```

### Task 8: Change-event classes for the delta rail

Spec §5-iv. Five new proposals; each goes through the same discovery gate that killed the eight (`register_discovery_gate`, `worker/jobs/research_events_derive.py`). **Deliberate deviation from the spec's list, with reason:** the spec names "filing-landed" as a new class, but `statement_published` and `sec_filing` are already LIVE classes carrying exactly that fact — registering a duplicate class would double-write the same event. The delta rail (P3) consumes the existing classes for filings; this task registers the four genuinely new ones plus `band_exit` (the spec's "band-entry/exit" is two classes because entry and exit are different facts): `band_entry`, `band_exit`, `implied_move_shift`, `coverage_change`, `bucket_flip`.

All five sources are ingested tables (valuation_anchors, implied_move_daily, fundamental_statement_obs × chain_membership, fundamental_scores) — they pass the gate's "no fabrication" bar by construction; register them with measured row counts at registration time.

Event semantics (each idempotent via `record_events`' `ON CONFLICT (event_class, ticker, occurred_at, source_ref) DO NOTHING`):

- `band_entry`: from `FundamentalAnchorsRepository.in_buy_zone(engine_version)` rows with `entered is True`; `occurred_at = as_of`, `source_ref = f"{ticker}:{as_of}:{engine_version}"`. Rows with `entered is None` (no prior band in lookback) emit NOTHING — null is not NEW.
- `band_exit`: SQL over `valuation_anchors`: tickers in-zone at the previous `as_of` for this engine and not in-zone (or refused) at the newest; same ref shape.
- `implied_move_shift`: for a `(ticker, report_date)` pair, |pct today − pct at previous `market_date`| ≥ 0.01 (1 percentage point — a parameter constant `IMPLIED_MOVE_SHIFT_PP = 0.01` in the job module); `source_ref = f"{ticker}:{report_date}:{market_date}"`.
- `coverage_change`: scoped per-ticker, because `research_events.ticker` is a ticker column and a chain-grain event would need a sentinel that lies about the ledger's grain. Emit for the TICKER whose statement coverage state changed — gained its first statement, or its newest compatible result crossed the `STALE_DAYS = 45` threshold already shared with Radar; `source_ref = f"{ticker}:{event_date}:{direction}"`. The desk aggregates per-chain at read time.
- `bucket_flip`: a ticker's newest `fundamental_scores.as_of` bucket changed — emit when a ticker first appears in a bucket newer than any it was in before; `occurred_at = as_of (the bucket id)`, `source_ref = f"{ticker}:{as_of}"`, `first_known_at = now()` (both clocks carried: the bucket is dated `as_of`, the DESK learned it tonight).

**Files:**

- Modify: `src/uw_scan/worker/jobs/research_events_derive.py` (extend `register_discovery_gate` with the five classes + measured-count SQL)
- Create: `src/uw_scan/worker/jobs/fundamental_change_events.py` (the nightly derive job, 21:15 ET, massive-0, config `fundamental_change_events_enabled` env `UW_SCAN_FUNDAMENTAL_CHANGE_EVENTS_ENABLED` default True)
- Create: `scripts/backfill/fundamental_change_events_run.py` (committed runner: `--as-of --execute`, dry-run default, calls `derive_change_events` — Task 17's seeding path; no /tmp one-offs)
- Modify: `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`
- Test: `tests/integration/storage/test_fundamental_change_events.py`

**Interfaces:**

- Consumes: `ResearchEventsRepository.record_events / live_classes / events_for` (verified signatures — rows carry `event_class, ticker, occurred_at, first_known_at, title, detail, source_kind, source_ref`); `FundamentalAnchorsRepository.in_buy_zone(engine_version)`; `ImpliedMoveRepository.history` (Task 7); `EarningsCalendarRepository`.
- Produces: `derive_change_events(conn, *, as_of: date, schema="uw_scan") -> dict[str, int]` (per-class written counts).

- [ ] **Step 1: Failing test.** Seed: a `valuation_anchors` pair of `as_of` snapshots where a real ticker (reuse the frozen NVDA figures pattern from `tests/integration/storage/test_fundamental_obs.py` for seeding statements if the anchors fixture needs them, or insert anchors rows directly with real frozen values) enters the zone; an `implied_move_daily` pair 1.5pp apart; two `fundamental_scores` buckets. Assert: one `band_entry`, one `implied_move_shift`, one `bucket_flip` event; re-running derives ZERO new rows (idempotent); an event in a class not registered raises (the gate holds).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Extend `register_discovery_gate`** — add the five `(key, sql)` count probes (count of `in_buy_zone`-eligible anchor rows, `implied_move_daily` rows, statement-bearing membership tickers, distinct `(ticker, as_of)` in `fundamental_scores`) and five `STATUS_LIVE` registration dicts with rationale strings naming the source table, mirroring the existing dict shape exactly.
- [ ] **Step 4: Implement `fundamental_change_events.py`** with one function per class + the `derive_change_events` orchestrator; wire scheduler + config; write the committed runner listed in Files.
- [ ] **Step 5: Run tests to verify they pass** (including the existing `research_events` gate tests untouched), then commit

```bash
git add -A src tests
git commit -m "feat(fundamentals): five change-event classes through the discovery gate for the delta rail"
```

### Task 9: Underwriting features — DIO, SBC/revenue, diluted-share YoY

Spec §5-v. **Decision stated (deviation-shaped, but spec-conform):** these do NOT join the scored `FEATURES` list — appending to `FEATURES` would change every cross-sectional z-score and force an engine-version bump for a descriptive display need. They land as a separate descriptive derivation in `fundamentals/features.py`.

**All three derive from the UW statement store** — including diluted-share YoY. (`massive_fundamentals.share_count_delta` already carries a YoY, but sourcing the node page from a second vendor's derivation while everything beside it is UW-derived is exactly the dual-sourcing Task 12 rejects for the desk; spec §4 says the income-statement data is already ingested, so derive it here.)

Verified raw keys: `inventory` (balance, confirmed in `prod_pull.sh` against prod `raw_jsonb`), `cost_of_revenue` (income, confirmed in `statements.py`). SBC and diluted-share keys: NOT verifiable locally — probed in Step 1.

**Files:**

- Modify: `src/uw_scan/fundamentals/features.py` (add `underwriting_features`) — **AS EXECUTED: created `src/uw_scan/fundamentals/underwriting.py` instead**, because adding to `features.py` pushed it past the 500-line module budget; `features.py` returned to 399 lines.
- Test: `tests/unit/test_underwriting_features.py`

**Interfaces:**

- Produces: `underwriting_features(uw: dict[str, Any]) -> dict[str, dict[str, dict[str, float | None]]]` — same input shape as `build_features` (per ticker: `{"income-statements": {period: row}, "balance-sheets": ..., "cash-flows": ...}`), returning per ticker per period `{"dio": float|None, "sbc_to_revenue": float|None, "share_count_yoy": float|None}` where `dio = inventory / cost_of_revenue_q * 91.25`, `sbc_to_revenue = sbc_q / total_revenue_q`, and `share_count_yoy = diluted_shares / diluted_shares_4q_ago − 1` (None when either endpoint is missing — a 4-quarter gap must yield None, never a wrong-span ratio).
- **CORRECTED AS EXECUTED — the third key's premise was false.** Step 1's probe found NO diluted-share key anywhere in the UW store: all 80 `(statement, key)` pairs were enumerated and none carries diluted shares at any tier. `share_count_yoy` as briefed is uncomputable. **Shipped instead:** `shares_outstanding_yoy`, sourced from `common_stock_shares_outstanding` (BASIC period-end shares, 420/420 ticker coverage), same 4-quarter-span rule and same None-propagation. The rename is load-bearing, not cosmetic: the figure measures net issuance/buyback, NOT dilution, so the word "diluted" must not appear on it in any model field, column header, tooltip, or caption. Every downstream reference (Tasks 13, 14, and the type-consistency review) was corrected 2026-08-28.

- [ ] **Step 1: PROBE the SBC and diluted-share key names.** On the dev DB (or mini per the documented read-only route):

```sql
SELECT DISTINCT statement, k FROM uw_scan.fundamental_statement_obs,
       LATERAL jsonb_object_keys(raw_jsonb) k
 WHERE (k ILIKE '%stock%' OR k ILIKE '%compensation%'
        OR k ILIKE '%dilut%' OR k ILIKE '%share%');
```

(Adjust the `statement` discriminator values to the table's actual vocabulary — read migration 114/`fundamental_obs.py` first.) SBC candidate: something like `stock_based_compensation` on the cash-flow payload; diluted-shares candidate: something like `diluted_average_shares` on the income payload — DO NOT assume either. **For any key the probe does not find, that feature returns None for every row and the node page's limits block states the absence** ("SBC not present in the ingested statements" / "diluted share count not present in the ingested statements") — absence is stated, never proxied and never silently substituted from another vendor (spec §4 discipline). Record the probe outcome in the module docstring either way.

- [ ] **Step 2: Failing unit test** with real frozen figures — AUTHORING STEP: freeze one real ticker's `inventory`, `cost_of_revenue`, `total_revenue` (+ SBC and diluted shares if the keys exist) for five real consecutive quarters from the warm store (five, so the 4-quarter-ago dilution endpoint exists; same pattern as `NVDA_BALANCE` in `test_fundamental_obs.py`). Assert `dio == inventory / cogs * 91.25` exactly, `share_count_yoy` matches the frozen 4-quarter ratio exactly, None-propagation when a field is absent, None when fewer than 5 quarters exist, and zero-COGS returns None (no division blowup).
- [ ] **Step 3: Run to verify failure.**
- [ ] **Step 4: Implement** using the module's existing `_f` helper and style (match `build_features`' per-period loop). No TTM smoothing, deliberately: DIO's numerator is a balance-sheet LEVEL at quarter end, so pairing it with the same quarter's COGS (× 91.25) preserves the quarter-end stocking signal the research VERDICT measured, and a TTM denominator would smooth away exactly the divergence the panel exists to show; SBC/revenue follows the same single-quarter basis so the two columns share a denominator period.
- [ ] **Step 5: Run to verify pass**, commit

```bash
git add src/uw_scan/fundamentals/features.py tests/unit/test_underwriting_features.py
git commit -m "feat(fundamentals): descriptive underwriting features - DIO and SBC/revenue"
```

### Task 10: NI cross-statement reconciliation, productionized

Spec §5-vi. The income-vs-cashflow net-income check (tolerance 1%) lives only in the research trace (artifact measured 140 ok / 15 bad). Productionize into the integrity path: a new cross-statement checker in `fundamentals/statements.py`, persisted through the EXISTING `FundamentalObsRepository.record_violations(obs_id, violations)` (`ON CONFLICT (obs_id, check_name) DO NOTHING`, verified), attached to the INCOME obs (the claim being contradicted) with the cash-flow value in `detail`.

**Files:**

- Modify: `src/uw_scan/fundamentals/statements.py` (add `check_cross_statement_violations`)
- Modify: `src/uw_scan/worker/jobs/fundamental_ingest.py` and `fundamental_ingest_daily.py` (call it where both statements for a `(ticker, period)` are in hand — read how `check_violations` is invoked at `fundamental_ingest.py:206` and mirror)
- Test: extend `tests/unit` beside the existing `check_violations` tests (find them: `grep -rln check_violations tests/`)

**Interfaces:**

- Produces: `check_cross_statement_violations(income: Mapping[str, Any], cashflow: Mapping[str, Any]) -> list[Violation]` — one check, `check_name="net_income_disagrees_across_statements"`, fires when both payloads carry a parseable net income and `abs(ni_inc - ni_cf) > 0.01 * max(abs(ni_inc), abs(ni_cf))`; `Violation.field = "net_income"`, `observed_value = str(ni_inc)`, `detail = {"cashflow_net_income": str(ni_cf)}`.
- PROBE (like Task 9): the cash-flow payload's NI key — `SELECT DISTINCT k ... WHERE statement='cash' AND k ILIKE '%net_income%'`. Candidate `net_income`; verify, never assume.
- The desk limits block (P3) reads this via a new `net_income_basis_differences_by_ticker` in `storage/fundamental_obs.py` (not `repository.py`). **AS EXECUTED this is NOT a violations read** — the name `worst_ni_offenders` and the word "offenders" were withdrawn: see the correction under Step 4.

- [ ] **Step 1: Failing unit test** — frozen real pair: AUTHORING STEP freeze one real ticker-quarter where income NI ≠ cashflow NI beyond 1% (the research trace names 15; pull one from prod via the documented route) and one agreeing pair. Assert fire/no-fire and the 1% boundary (construct the boundary case arithmetically FROM the frozen real values, e.g. scale the cashflow value to exactly 1.000 and 1.001 of the income value).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the checker with the module's existing `_dec` parsing helper; wire into both ingest jobs (income obs_id in hand + the period's cash payload when present in the same batch; when the cash statement arrives in a LATER run, the `recheck_violations` sweep re-evaluating per-obs checks will NOT catch cross-statement pairs — note this in the docstring and have the monthly full sweep call the cross-check for all complete pairs; verify the monthly job's structure in `fundamental_ingest.py` before wiring).
- [ ] **Step 4 — CORRECTED AS EXECUTED.** The check as briefed fired on **6,269 of 28,973 pairs (21.6%)**, not the ~15 the research trace implied. Measurement killed the premise: cash-flow NI is discrete-quarter (rate is flat by quarter — Q1 21.0%, Q2 22.3%, Q3 21.5%, Q4 21.8%, where a YTD convention would give ~0% then ~100%), annual mixing and sign conventions were ruled out, and the real driver is **noncontrolling interests and discontinued operations**: income-statement `net_income` is attributable-to-parent post-disc-ops, the cash-flow statement opens from consolidated NI including NCI (ASC 230 indirect). 3,153 of the 6,269 match income's own `net_income_from_continuing_operations`; VZ 2010-Q3 is the clean case (2,698M = 881M + 1,817M NCI, Vodafone's 45% of Verizon Wireless) where **both numbers are correct**. It affected 342 of 419 tickers, every REIT with OP units included. Argon stores no NCI field and so cannot attribute the difference. **Shipped instead:** the comparison is narrowed to fire only when cash-flow matches NEITHER income NI line (6,269 → 3,116) and is surfaced as a **descriptive basis difference** off the `record_violations` path, following this repo's "descriptive only" precedent; the genuine violation is a separate **sign-flip** check, **5 of 28,973 (0.017%)** — CVX 2023-Q1/Q2, GE 2022-Q3, IREN 2022-Q2, UMC 2010-Q3.
- [ ] **Step 5: Run affected tests**, commit

```bash
git add -A src tests
git commit -m "feat(fundamentals): NI cross-statement reconciliation persisted as an integrity violation"
```

### Task 11: Optical `company_type` routing fix — versioned

Spec §5-vii. **Verified surprise the executor must respect:** `SECTOR_TO_TYPE` on `main` ALREADY maps `"Networking/Optical": "chips_cyclical"`. The misrouting flagged in the research VERDICT therefore comes from the resolution path — `seed_company_types` routes on `watchlist.sector`, a SINGLE tag per name, so an optical name tagged `Power/Electrical` or `DC-Connect` routes to `power_infra` regardless of the optical map entry. The legitimate fix mechanism is `TICKER_TO_TYPE` per-name overrides (checked first; currently one entry, PYPL, with a test asserting overrides never point at an EV-denominated type FOR THE REFUSAL-ESCAPE CASE — read that test before editing; optical overrides point at `chips_cyclical`, which is EV-denominated and fine because none of these names is a financial).

**Files:**

- Modify: `src/uw_scan/worker/jobs/fundamental_anchors.py` (`TICKER_TO_TYPE` additions + version bump)
- Create: `scripts/research/optical_company_type_probe.py` (the measurement that names the misrouted tickers)
- Test: extend the existing anchors routing tests (find: `grep -rln TICKER_TO_TYPE tests/`)

- [ ] **Step 1: Probe current routing.** Script queries, for the 16 Optical-Communication members (from `chain_membership`, active taxonomy version), their `watchlist.sector` tag and currently persisted company type + method; prints a table; **persists the table to `docs/research/2026-08-26-optical-chain-pm-desk/routing_probe.md`** (research persistence rule). Reproduce command in the file header.
- [ ] **Step 2: Failing test.** For each ticker the probe found misrouted (do not hardcode the list in this plan — the probe is the source of truth), assert `TICKER_TO_TYPE[t] == "chips_cyclical"` and that `seed_company_types` routes it there (mirror the existing routing test's fixture style).
- [ ] **Step 3: Implement.** Add the probe-named tickers to `TICKER_TO_TYPE` with a comment block citing the probe file and the VERDICT ("the percentile is valid, the label is wrong").

  **Versioned parameter change — the real mechanism (verified):** there is NO version constant in `fundamental_anchors.py`; the job reads `engine = scores.active_version()` (`fundamental_anchors.py:603`) from the `fundamental_method_state` singleton, and the ONLY registration path is `FundamentalScoresRepository.register_version(engine_version, code_version, param_hash, params, note)` + `.activate(engine_version)` (`storage/fundamental_scores.py:30/62`), called from `scripts/seed_fundamental_method.py:73`. So the change is: extend `scripts/seed_fundamental_method.py` to register a NEW `engine_version` (derive its name by suffixing the current active version — read the script for the naming scheme; include a `note` naming this routing change and the probe file) and activate it. `TICKER_TO_TYPE` is code, not a stored param row, so `code_version` (the git ref the script records) is what pins it — verify how the script fills `code_version` and keep that behavior.

  **Blast radius — an executor-visible decision, decided here:** the engine version namespace is SHARED between `fundamental_scores` and `valuation_anchors`; there is no anchors-only version. Activating a new version means the nightly scoring job also starts a fresh version lineage (old rows remain replayable under the old version — that is the design: "retuning means a NEW version"). This is wider than §5-vii's minimal "a changed method changes a published band", and it is the narrowest mechanism the schema offers. Accepted, on the grounds that a version bump with unchanged scoring parameters produces identical score VALUES under a new label, and the alternative — changing routing under a live version — is precisely what the versioning rules forbid. If at execution time the seed script's registration couples anything beyond `(code_version, params)` that would CHANGE scores, stop and surface it to the user instead of activating.

- [ ] **Step 4: Run the anchors test file + the full python suite**

Run: `uv run pytest tests -x -q`
Expected: PASS

- [ ] **Step 5: CHANGELOG for the whole P2 branch + PR**

Add under `[Unreleased]` (one entry per task 4–11, one line each, following the file's existing voice). Then:

```bash
git add CHANGELOG.md && git commit -m "docs: changelog for the fundamentals data spine"
git push -u origin feat/fundamentals-data-spine && gh pr create --fill
```

Wait for CI green; merge. **Deploy note for the PR body:** new jobs are default-on and zero-vendor; the api service self-migrates on deploy, and the worker needs its normal restart to pick up the new schedules.

---

# Phase P3 — pages (branch `feat/fundamentals-desk-pages`)

Cut from `main` after the P2 PR merges. Order inside the phase: node page substrate first (spec §7: "the optical node page first — the report substrate already renders; this is presentation"), then index, then the industry desk.

### Task 12: Desk matrix rollup — migration 147 + nightly job

The chain × metric matrix (spec §3c) needs per-name revenue YoY and gross-margin trajectory at request time with zero recompute. Nothing persists raw per-name feature values today (scores are z-cross-sections; `massive_fundamentals` is a parallel vendor's derivation — dual-sourcing the desk against UW-sourced node pages would let the two disagree). Persist a nightly per-name rollup from the UW statement store.

**Files:**

- Create: `src/uw_scan/storage/migrations/147_fundamentals_desk_rollup.sql`
- Create: `src/uw_scan/storage/fundamentals_desk.py`
- Create: `src/uw_scan/worker/jobs/fundamentals_desk_rollup.py` (21:30 ET daily, massive-0, config `fundamentals_desk_rollup_enabled` env `UW_SCAN_FUNDAMENTALS_DESK_ROLLUP_ENABLED` default True)
- Create: `scripts/backfill/fundamentals_desk_rollup_run.py` (committed runner: `--execute`, dry-run default, calls the job function once — Task 17's seeding path; no /tmp one-offs)
- Modify: `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`
- Test: `tests/integration/storage/test_fundamentals_desk_rollup.py`

**Interfaces:**

- Produces: table `fundamentals_desk_rollup (ticker, period_end) PK` + `rev_yoy NUMERIC, gross_margin NUMERIC, gross_profit NUMERIC, knowledge_date DATE, computed_at` — derived via the existing `build_features` input shape from the newest-accepted-version panel: **`current_statement_panel(conn, tickers, schema=...)` in `storage/fundamental_observation_panels.py`** (verified post-#383 home; it returns EVERY period per ticker with the newest obs per `(ticker, period_end, statement)` — "today's view" means newest version, not today-only, so it covers the 8-quarter trajectory; `FundamentalObsRepository.statement_panel` is its kept compatibility alias, and new code calls the panels module directly per its docstring). Do not re-implement payload selection. `FundamentalsDeskRepository` with `upsert_rows`, `latest_per_ticker(tickers) -> dict[str, dict]`, `trajectory(ticker, quarters=8) -> list[dict]`.
- The job derives ONLY from rows whose observation passes the violations filter the card path already uses (`violated_fields` — exclude a field, not the name).

- [ ] **Step 1: Migration + failing integration test** (seed statements via the frozen-NVDA pattern from `test_fundamental_obs.py`, run the job, assert rev_yoy/gross_margin values computed from the frozen figures; assert a violated field's metric is None, not wrong).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement repository + job + scheduler/config wiring** (mirror Task 6's registration shape).
- [ ] **Step 4: Run to verify pass, commit**

```bash
git add -A src tests
git commit -m "feat(fundamentals): nightly desk rollup of per-name rev YoY and gross margin"
```

### Task 13: Desk + node API — models and router

**Files:**

- Create: `src/uw_scan/models/fundamentals_desk.py`; export via `src/uw_scan/models/__init__.py` (preserve `__all__` conventions and `_preserve_public_module` metadata like `models/radar.py` does)
- Create: `src/uw_scan/api/routers/fundamentals_desk.py`; include in `src/uw_scan/api/server.py` beside the existing routers
- Test: `tests/integration/api/test_fundamentals_desk_api.py` (mirror the existing API-test bootstrap — find it: `ls tests/integration/api/`)

**Interfaces (exact response models — P3 web tasks and `gen:types` consume these names):**

```python
class DeskCalendarRow(_UwBase):
    ticker: str
    report_date: date
    session: str | None            # 'premarket' | 'afterhours' | None = unknown
    chain: str
    layer: str
    layer_rank: int
    implied_move_pct: float | None # None = not covered (rendered as such, never blank)
    implied_move_asof: date | None
    reactions: list[float]         # last <=4 pct_move, newest first
    spot_percentile: float | None  # own-history YIELD percentile: 0.80 = CHEAP
    percentile_state: str          # FundamentalResultState when spot_percentile is None, else "ok"

class DeskCalendarResponse(_UwBase):
    section: str                   # "ai-semi"
    as_of: date
    rows: list[DeskCalendarRow]    # ordered report_date ASC, then layer_rank ASC — read-through order

class DeltaRailEvent(_UwBase):
    event_class: str
    ticker: str
    occurred_at: date
    first_known_at: datetime
    title: str
    detail: dict

class DeltaRailResponse(_UwBase):
    since: datetime
    events: list[DeltaRailEvent]   # ordered first_known_at DESC — the desk's knowledge clock

class ChainMetricCell(_UwBase):
    chain: str
    metric: str                    # 'rev_yoy' | 'gross_margin' | 'valuation_percentile'
    # Unweighted median of non-null dot values — EXCEPT metric='valuation_percentile',
    # where median is ALWAYS None: own-history percentiles are name facts and any
    # aggregate over them is the banned "chain percentile distribution" (spec §3).
    median: float | None
    dots: list["MemberDot"]        # per-name (one dot per DISTINCT ticker), NEVER weighted
    cohorts: list["CohortSlice"]   # >=2 entries iff members straddle as_of buckets
    coverage_missing: list[str]    # NAMED missing DISTINCT tickers — never a bare count
    members_total: int             # DISTINCT tickers — a name in two layers counts once

class MemberDot(_UwBase):
    ticker: str
    value: float | None
    state: str                     # FundamentalResultState

class CohortSlice(_UwBase):
    as_of: date                    # the cross-section id
    label: str                     # 'reported' | 'awaiting'
    tickers: list[str]

class DeskMatrixResponse(_UwBase):
    section: str
    chains: list[str]              # ordered by min layer_rank — never by any metric
    cells: list[ChainMetricCell]

class ProfitPoolLayer(_UwBase):
    chain: str
    layer_rank: int
    median_gross_margin: float | None
    median_rev_yoy: float | None
    dots: list[MemberDot]
    # NO field for arrows/edges/propagation exists in this model, by design.

class MembershipEvidenceCount(_UwBase):
    evidence_class: str            # 'disclosed' | 'analyst' | 'mirrored' | 'inferred'
    memberships: int

class ChainExposureCoverage(_UwBase):
    chain: str
    members: int
    with_exposure: int
    with_magnitude: int

class DeskLimitsResponse(_UwBase):
    # CORRECTED (Task 10 as-executed): the earlier field names here were
    # `ni_reconciliation_pass` / `ni_reconciliation_fail` / `ni_worst_offenders`.
    # Task 10's premise — that an income-vs-cash-flow net-income disagreement is
    # a data-integrity failure — was DISPROVED. Income-statement `net_income` is
    # attributable-to-parent post-discontinued-ops; the cash-flow statement opens
    # from consolidated NI INCLUDING NCI (ASC 230 indirect). A disagreement is
    # usually correct accounting on BOTH sides — measured on 342 of 419 tickers,
    # worked case VZ 2010-Q3 where 2,698M = 881M + 1,817M NCI. Argon stores no
    # NCI field and therefore CANNOT attribute the difference. These fields are
    # DESCRIPTIVE: never name them pass/fail/offender, and never render them as
    # an integrity error. Do not restore the old names.
    ni_basis_agree: int                              # the two statements' NI match
    ni_basis_differ: int                             # they differ — NOT an error
    ni_largest_basis_differences: list[str]          # named tickers, largest gap first
    # The one genuine integrity check on this axis — separate, and rare:
    ni_sign_flip_violations: int                     # measured 5 of 28,973 rows
    withheld_composite: str                          # the fixed sentence from spec §3f — legitimately prose
    # "computed, not prose" (spec §3f): membership semantics as NUMBERS, prose
    # only as a caption the web layer writes over them.
    membership_evidence: list[MembershipEvidenceCount]
    exposure_coverage: list[ChainExposureCoverage]   # ResearchTaxonomyRepository.exposure_coverage(version)

class NodeUnderwritingRow(_UwBase):
    ticker: str
    period_end: date
    dio: float | None
    sbc_to_revenue: float | None
    # CORRECTED (Task 9 as-executed): was `share_count_yoy` "diluted shares vs
    # 4q ago". Task 9 verified exhaustively — all 80 (statement, key) pairs in
    # the UW store — that NO diluted-share key exists at any tier. The shipped
    # feature is `shares_outstanding_yoy`, sourced from
    # `common_stock_shares_outstanding` (BASIC period-end shares, 420/420
    # coverage). Do not restore the old name, and never label this "diluted"
    # anywhere it reaches a reader: it measures issuance/buyback, not dilution.
    shares_outstanding_yoy: float | None   # basic period-end shares vs 4q ago
    # Filed-line-item provenance (spec §4 trust requirement #1): the raw values
    # and the filing date travel WITH the figure, not behind another request.
    filing_published_at: date | None
    inventory_raw: str | None        # raw_jsonb value, verbatim string
    cost_of_revenue_raw: str | None
    sbc_raw: str | None
    shares_outstanding_raw: str | None   # verbatim `common_stock_shares_outstanding`
    state: str                       # FundamentalResultState for the row's basis
```

Endpoints (all read-only, zero vendor calls, warm store only):

- `GET /fundamentals/{section}/calendar?chain=<name>` → `DeskCalendarResponse` (joins `earnings_calendar` × `chain_membership` (active version, section's domains: `ai_infrastructure` + `dc_buildout` + `optical_communication`) × `implied_move_daily` latest × `earnings_reactions` last-4 × `valuation_anchors` newest). `chain` is the ONLY optional filter: it scopes rows to that chain's members, resolved server-side from membership — there is no `tickers` param and no ordering param; response order is fixed regardless of filter.
- `GET /fundamentals/{section}/delta?since=<iso>` → `DeltaRailResponse` (default since = 7 days ago; reads `research_events` live classes: `statement_published`, `sec_filing`, `band_entry`, `band_exit`, `implied_move_shift`, `coverage_change`, `bucket_flip`, filtered to section members). **One filing, one rail entry:** `sec_filing` and `statement_published` can both fire for the same print — collapse to one `DeltaRailEvent` when `(ticker, occurred_at)` matches across the two classes, keeping `statement_published` (the richer fact) and recording the suppressed class in `detail["also"]`.
- `GET /fundamentals/{section}/matrix` → `DeskMatrixResponse` (from `fundamentals_desk_rollup` + `valuation_anchors` + `fundamental_scores` bucket ids for the cohort split; every ticker set built with `SELECT DISTINCT ticker` over `chain_membership` — one ticker in two layers is two rows, per `chain_membership_open_uq`)
- `GET /fundamentals/{section}/profit-pool` → `list[ProfitPoolLayer]`
- `GET /fundamentals/{section}/limits` → `DeskLimitsResponse` (`ni_*` from Task 10's `FundamentalObsRepository.net_income_basis_differences_by_ticker` — **as executed, Task 10's premise was disproved and this is a DESCRIPTIVE basis difference, never a violations read and never labelled as one.** Income-statement `net_income` is attributable-to-parent post-disc-ops while the cash-flow statement opens from consolidated NI including NCI (ASC 230 indirect), so a disagreement is usually correct accounting on both sides — measured on 342 of 419 tickers, worked case VZ 2010-Q3 where 2,698M = 881M + 1,817M NCI. Argon stores no NCI field and therefore CANNOT attribute the difference, which is why it must not render as an integrity failure. The genuine violation is the separate sign-flip check, 5 of 28,973 rows; `membership_evidence` from a GROUP BY `evidence_class` over open memberships in the section's domains; `exposure_coverage` from `ResearchTaxonomyRepository.exposure_coverage(version)` — verified, `storage/research_taxonomy.py:305`, returns per-chain `members` / `with_exposure` / `with_magnitude`)
- `GET /fundamentals/{section}/node/underwriting?chain=<name>` → `list[NodeUnderwritingRow]`. **CORRECTED 2026-08-28 — was `GET /fundamentals/node/{chain}/underwriting`, which cannot work.** Every real ai-semi chain name contains a slash (`Networking/Optical`, `Semi-Logic/ASIC`, `Cooling/Thermal`, `Generation/Nuclear`, `EPC/Construction`, `Power/Electrical`, `DC-REIT/Colo`, `Computer/GPU` — verified against `watchlist_chain` on the mini, 20 of 38 chains), and a `%2F`-encoded slash in a FastAPI **path** param returns **404** (verified empirically 2026-08-28: path param `%2F` → 404, query param with a raw slash → 200). `chain` therefore travels as a QUERY parameter, exactly as `/calendar?chain=` already does. Do not reintroduce a chain path segment on any endpoint. Implementation otherwise unchanged: (via `current_statement_panel` → `underwriting_features` (Task 9) — UW store only, including `shares_outstanding_yoy`; raw provenance strings copied verbatim from the panel's `raw_jsonb` + `filing_published_at`; computed per request over ≤20 names — acceptable, and the payloads are already in the warm store)

- [ ] **Step 1: Failing API tests**, including the anti-requirement tests (these are the spec's test-backed guardrails):

```python
def test_matrix_response_carries_no_ranking_surface():
    """Spec §3 anti-requirement: no cross-sectional ranking or composite."""
    from uw_scan.models.fundamentals_desk import (
        ChainMetricCell, DeskMatrixResponse, MemberDot,
    )
    banned = {"rank", "score", "composite", "percentile_rank", "sort"}
    for model in (DeskMatrixResponse, ChainMetricCell, MemberDot):
        assert not banned & set(model.model_fields), model.__name__


def test_calendar_endpoint_rejects_sort_param(desk_client):
    r = desk_client.get("/fundamentals/ai-semi/calendar", params={"sort": "implied_move_pct"})
    assert r.status_code == 422  # no sort parameter exists, by design


def test_matrix_splits_cohorts_and_names_missing(desk_client, seeded_two_buckets):
    r = desk_client.get("/fundamentals/ai-semi/matrix")
    cell = next(c for c in r.json()["cells"] if c["chain"] == seeded_two_buckets.chain)
    assert len(cell["cohorts"]) == 2                      # reported / awaiting, never merged
    assert isinstance(cell["coverage_missing"], list)     # named, never bare n/N
    assert all(isinstance(t, str) for t in cell["coverage_missing"])


def test_profit_pool_model_has_no_edge_field():
    from uw_scan.models.fundamentals_desk import ProfitPoolLayer
    banned = {"leads", "lags", "arrow", "edges", "propagation", "read_through"}
    assert not banned & set(ProfitPoolLayer.model_fields)


def test_valuation_percentile_cell_has_no_median(desk_client, seeded_desk):
    """A chain aggregate over own-history percentiles is the banned
    'chain percentile distribution' — dots only (spec §3)."""
    r = desk_client.get("/fundamentals/ai-semi/matrix")
    for cell in r.json()["cells"]:
        if cell["metric"] == "valuation_percentile":
            assert cell["median"] is None
            assert cell["dots"]  # the name facts still render


def test_median_is_unweighted_median_of_dots(desk_client, seeded_desk):
    """For metrics that keep a median: it equals the plain median of the
    non-null dot values — never weighted by anything."""
    import statistics
    r = desk_client.get("/fundamentals/ai-semi/matrix")
    cell = next(c for c in r.json()["cells"]
                if c["metric"] == "gross_margin" and c["median"] is not None)
    values = [d["value"] for d in cell["dots"] if d["value"] is not None]
    assert cell["median"] == pytest.approx(statistics.median(values))


def test_membership_counts_dedupe_by_ticker(desk_client, seeded_dual_layer):
    """chain_membership is (chain, layer, ticker)-grained — a name in two
    layers is two rows and must count ONCE (seeded_dual_layer seeds exactly
    that: one real ticker in two layers of one chain)."""
    r = desk_client.get("/fundamentals/ai-semi/matrix")
    cell = next(c for c in r.json()["cells"] if c["chain"] == seeded_dual_layer.chain)
    tickers = [d["ticker"] for d in cell["dots"]]
    assert len(tickers) == len(set(tickers))
    assert cell["members_total"] == len(set(seeded_dual_layer.tickers))


def test_rows_only_chain_reaches_both_endpoints(desk_client, conn):
    """Spec §2 extension contract, made testable: a NEW chain stood up as
    research_chains + chain_membership rows ONLY — no ChainSpec constant, no
    SECTIONS edit, no assembler or router change — must appear on the desk.
    Seed a chain in an already-registered domain (e.g. domain='dc_buildout',
    chain='Substation/Transformers', one layer, two real universe tickers)
    directly via ResearchTaxonomyRepository, then:"""
    r = desk_client.get("/fundamentals/ai-semi/matrix")
    assert "Substation/Transformers" in r.json()["chains"]
    # `chain` is a QUERY param, never a path segment — a %2F-encoded slash in a
    # FastAPI path param 404s, and 20 of 38 real chain names contain a slash.
    r2 = desk_client.get(
        "/fundamentals/ai-semi/node/underwriting",
        params={"chain": "Substation/Transformers"},
    )
    assert r2.status_code == 200
```

(A new SECTION is still one registry row — the contract tested here is that a new NODE/chain inside a registered section is zero code, which is the spec's §2 claim.)

Plus positive-path tests per endpoint over seeded frozen data (reuse the seeds built in Tasks 4–12's tests via shared fixtures/helpers — extract a `tests/integration/api/_desk_seeds.py` if duplication grows). `desk_client` / `seeded_desk` / `seeded_two_buckets` / `seeded_dual_layer`: build these fixtures in the test file following the existing API-test bootstrap you found in Step-0 reading.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement models + router.** Router pattern: copy the conventions of `api/routers/stock.py` (repository construction, response_model annotations, no mutation except none-at-all here). Registration in `server.py` beside the others. The `{section}` value is validated against a declared registry constant `SECTIONS = {"ai-semi": ("ai_infrastructure", "dc_buildout", "optical_communication")}` in the router module — a new section is a registry row, not new handlers (extension contract). NOTE for the 422 test: FastAPI ignores unknown query params by default — add a small router-level dependency that compares `request.query_params` against the endpoint's declared params and raises 422 on extras, so "no sort parameter" is enforced structurally rather than silently ignored.
- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/integration/api/test_fundamentals_desk_api.py -v`
Expected: PASS

- [ ] **Step 5: Regenerate web types and commit**

```bash
cd web && npm run gen:types && cd ..
git add -A src tests web/lib/types.ts
git commit -m "feat(fundamentals): desk and node API - calendar, delta rail, matrix, profit pool, limits, underwriting"
```

### Task 14: Node page `/fundamentals/ai-semi/[node]`

Renders the STORED versioned report (never live re-assembly) + live calendar strip + the §4 underwriting additions. The rendering substrate exists: `web/components/reports/ReportView.tsx` and the `web/app/reports/[type]/[key]/` route landed with #383 — read both before writing anything; this page COMPOSES them, it does not fork them.

**Files:**

- Create: `web/app/fundamentals/ai-semi/[...node]/page.tsx` (RSC; `export const dynamic = "force-dynamic"` like `web/app/reports/page.tsx`). **CATCH-ALL, not `[node]` — corrected 2026-08-28.** 20 of 38 real chain names contain a slash (`Networking/Optical`, `Semi-Logic/ASIC`, …), which a single dynamic segment cannot match. The catch-all receives `params.node: string[]`; rejoin with `"/"` to recover the chain name (`["Networking","Optical"]` → `"Networking/Optical"`), so the URL reads `/fundamentals/ai-semi/Networking/Optical` with no encoding anywhere. Test the rejoin explicitly — a chain whose name has no slash arrives as a one-element array and must still resolve.
- Create: `web/components/fundamentals/NodeCalendarStrip.tsx`, `web/components/fundamentals/NodeUnderwritingPanel.tsx`, `web/components/fundamentals/NodeAliasQuestions.tsx`, `web/components/fundamentals/NodeLimits.tsx`
- Modify: `web/lib/api.ts` (add typed fetchers: `deskCalendar(section, chain?)` — the server-side `?chain=` filter from Task 13, membership-resolved, no ticker list crosses the wire — and `nodeUnderwriting(chain)`; mirror the existing `api.researchReports` style)
- Test: `web/tests/unit/nodePage.test.tsx` (vitest; mirror `web/tests/unit/macroDesk.test.tsx` conventions)

Page composition, top to bottom (the artifact's Q1–Q8 skeleton via report blocks + additions):

1. Stored report blocks via `ReportView` for the chain report (`report_key` chain type + node key; the version picker the report route already has — link to it for as-of replay, trust builder #2).
2. `NodeCalendarStrip`: the section calendar scoped to the node via `deskCalendar(section, chain)` (client island) — date, session badge (`?` badge for NULL session, never hidden), implied move ("not covered" text when null), last-4 reaction dots.
3. `NodeUnderwritingPanel`: table over `NodeUnderwritingRow` — DIO trajectory, SBC/revenue (or the limits sentence when the Task-9 probe found no key), `shares_outstanding_yoy` (label it "shares outstanding", NEVER "diluted" — Task 9 proved no diluted-share key exists in UW and this is the basic period-end count); every figure's tooltip carries the FILED provenance the row now ships (spec §4 trust requirement #1): ticker, fiscal `period_end`, `filing_published_at`, and the verbatim raw values (`inventory_raw`, `cost_of_revenue_raw`, `sbc_raw`, `shares_outstanding_raw`) — the reader sees the filed line items behind the ratio without another request; the ticker links to `/stock/[ticker]` for the full statements panel.
4. `NodeAliasQuestions`: static rendering of the open APH/CIEN alias questions (spec §8-1) — surfaced, not silently corrected; content states both candidate tags and that changing a rule changes a published number. Data source: the exposure block of the stored report (`is_member` flags) — the two names are identified by `is_member == false` + the block's alias metadata, with the explanatory copy in the component.
5. `NodeLimits`: the node's own limits block (spec §4 close): the four underwriting inputs this page does NOT attempt — ASP/mix, capacity, lead times, qualification status — stated as absent rather than proxied; the Task-9 probe outcomes (SBC / diluted-shares key present or "not present in the ingested statements"); and the alias-question caveat ("two exposure magnitudes above ride open alias questions — changing a rule changes these numbers").

- [ ] **Step 1: Failing vitest** — render the page's client components with mocked fetch payloads (typed from `types.ts`): assert "not covered" renders for a null implied move; assert a NULL session renders a visible unknown badge; assert the underwriting panel renders the SBC-absence sentence when every `sbc_to_revenue` is null; assert a figure's tooltip contains `filing_published_at` and the raw filed value; assert alias questions section names APH and CIEN; assert `NodeLimits` names all four un-attempted inputs (ASP/mix, capacity, lead times, qualification status).
- [ ] **Step 2: Run to verify failure**: `cd web && npm run test -- nodePage`
- [ ] **Step 3: Implement** page + components (Argon dark theme; hand-rolled SVG only, no chart lib).
- [ ] **Step 4: Run to verify pass**, commit

```bash
git add web
git commit -m "feat(fundamentals): optical node deep-dive page over the stored report substrate"
```

### Task 15: `/fundamentals` index with Radar as triage tab

Thin index (spec §2): redirects to `/fundamentals/ai-semi` as the only section, with Radar folded in as the triage tab rather than a sibling route.

> **EXECUTION ORDER — run this task AFTER Task 16, not before (ruling 2026-08-28).** As written, Task 15 points three redirects (`/fundamentals`, `/radar`, `/chains`) at `/fundamentals/ai-semi`, a route Task 16 has not created yet — every redirect would land on a 404 for the whole interval between the two tasks. Task 15 also instructs the executor to decide `ChainMatrix.tsx`'s disposition "while building Task 16's `ChainMetricMatrix`", which is unanswerable before that component exists. Task 16 has no dependency on Task 15 in the other direction (it creates a route; it does not touch nav or any redirect), so the swap is free. Nothing else changes: keep both tasks' files, tests, and commits exactly as specified.

**Files:**

- Create: `web/app/fundamentals/page.tsx` (server redirect to `/fundamentals/ai-semi`)
- Create: `web/app/fundamentals/radar/page.tsx` (renders the existing `web/components/radar/RadarTable.tsx` — the component moved in unchanged; read `web/app/radar/page.tsx` first and lift its data wiring)
- Modify: `web/app/radar/page.tsx` → server redirect to `/fundamentals/radar` (old URL keeps working; do not delete the route)
- Modify: `web/app/chains/page.tsx` (the #383 chain index) → server redirect to `/fundamentals/ai-semi` (spec §2: the `/chains` pages fold in as raw material). The chain DETAIL pages (`/chains/[chain]` or their #383 equivalent — read the routes first) stay: they are the member-list click-through target Task 16's matrix cells link to.
- Modify: the app's nav (find it: `grep -rn "radar\|/macro" web/app/layout.tsx web/components/shared/` and edit where the macro/regime links live) — one "Fundamentals" entry replacing the bare Radar entry
- Test: `web/tests/unit/fundamentalsIndex.test.tsx`

- [ ] **Step 1: Failing vitest** asserting the index redirect target and that the radar tab page renders `RadarTable` with its expected props (mock the fetch).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** (Next `redirect()` in the RSC for all three redirects). `ChainMatrix.tsx` disposition: read it while building Task 16's `ChainMetricMatrix` and lift what serves; once the desk page ships, if nothing but the redirected index referenced `ChainMatrix.tsx`, delete it in this task's commit — superseded raw material, not a parallel surface. If a chain detail page still renders it, leave it there and say so in the commit message.
- [ ] **Step 4: Run to verify pass**, commit

```bash
git add web
git commit -m "feat(fundamentals): /fundamentals index with radar folded in as the triage tab"
```

### Task 16: Industry desk page `/fundamentals/ai-semi`

Spec §3 content in priority order: (a) delta rail on top, (b) chain-ordered calendar, (c) chain × metric matrix, (d) profit-pool layers side by side, (e) demoted capex context strip, (f) computed limits.

**Files:**

- Create: `web/app/fundamentals/ai-semi/page.tsx` (RSC shell; tabs are anchor sections, not routes)
- Create: `web/components/fundamentals/DeltaRail.tsx`, `ChainCalendar.tsx`, `ChainMetricMatrix.tsx`, `ProfitPoolStrip.tsx`, `CapexContextStrip.tsx`, `DeskLimits.tsx`
- Modify: `web/lib/api.ts` (add `deskDelta`, `deskMatrix`, `deskProfitPool`, `deskLimits`)
- Test: `web/tests/unit/industryDesk.test.tsx`

Rendering rules (each one a test):

- `DeltaRail` orders strictly by `first_known_at` DESC and renders the event's both-clocks tooltip (`occurred_at` vs `first_known_at`).
- `ChainCalendar` renders rows in the response's order (report_date, then layer_rank) and NEVER re-sorts client-side; implied-move null → "not covered"; `spot_percentile` reaches the screen only through a rank-phrase helper (0.80 = cheap — copy the `rankPhrase` semantics from `ValueSubTab`, read it first).
- `ChainMetricMatrix`: median + dots (SVG strip per cell); for `metric == "valuation_percentile"` render dots ONLY — the API sends `median: null` and the cell caption frames them as name-level own-history positions, never a chain property; when `cohorts.length > 1` render two labeled cohort groups and NO merged median (`median` still arrives from the API for the dominant cohort — display it under the `reported` cohort label only); empty cells render the hatched abstention with the `state` string, never blank; `coverage_missing` renders the ticker names.
- `ProfitPoolStrip`: layers side by side ordered by `layer_rank`; NO connecting arrows or lead/lag copy anywhere in the component (test: rendered output contains none of `→`, "leads", "lags").
- `CapexContextStrip`: **deliberately copy-only — no model field, no fetcher, no data source.** The spec demotes hyperscaler capex BECAUSE it carries zero edge (it is on every sell-side deck); spending a data path on a strip whose whole message is "this number is context, not signal" would re-promote it. The strip is fixed copy including the sign-inversion sentence ("for L4/L5 rising capex is a cost line, not demand — context, not edge") and a link to the stock pages where the filed capex lives. If a later phase wants the number itself, that is a new decision, not this task's.
- `DeskLimits`: the NI basis split (`ni_basis_agree` / `ni_basis_differ`) rendered as a DESCRIPTIVE accounting-basis difference with the named largest gaps — the caption must say a difference is usually correct on both sides (ASC 230 consolidated-incl-NCI vs attributable-to-parent) and that argon stores no NCI field to attribute it; the word "fail", "offender", "error", or "violation" must not appear over these two numbers (test it). `ni_sign_flip_violations` is the separate genuine check and IS labelled a violation. The withheld-composite sentence verbatim from the API; `membership_evidence` rendered as counts per evidence class (disclosed / analyst / mirrored / inferred) and `exposure_coverage` as per-chain members / with-exposure / with-magnitude — prose only as captions over these numbers (spec §3f: computed, not prose).

- [ ] **Step 1: Failing vitests** for each rule above (mocked typed payloads; one test per rule, including the two-cohorts-never-merged and the no-arrows assertions).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the six components + page shell.
- [ ] **Step 4: Run the full web suite**: `cd web && npm run test` → PASS.
- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat(fundamentals): ai-semi industry desk - delta rail, chain calendar, matrix, profit pool, limits"
```

### Task 17: End-to-end smoke through the real worker path

Standing rule: smoke tests run the real path — API enqueue/read → DB → web render; never a /tmp script.

- [ ] **Step 1: Boot the local stack**: `bash scripts/dev.sh` (restart it — the workers predate this branch's jobs; APScheduler doesn't hot-reload).
- [ ] **Step 2: Seed real data locally** through the committed runners (the `/jobs` router has only rescan endpoints — verified — so the runners ARE the trigger path; no /tmp one-offs):

```bash
uv run python scripts/backfill/earnings_calendar_backfill.py --start 2026-08-01 --end 2026-08-27 --execute
uv run python scripts/backfill/earnings_reactions_backfill.py --start 2026-07-01 --end 2026-08-27 --execute
uv run python scripts/backfill/implied_move_backfill.py --start 2026-08-20 --end 2026-08-27 --execute
uv run python scripts/backfill/fundamentals_desk_rollup_run.py --execute
uv run python scripts/backfill/fundamental_change_events_run.py --as-of 2026-08-27 --execute
```

(Adjust dates to the execution day; rollup before change-events so the event derive sees the fresh state.)

- [ ] **Step 3: Browser-verify** (Playwright MCP or manual): `/fundamentals` redirects; `/fundamentals/ai-semi` renders all six sections with real local data or honest abstention states; `/fundamentals/ai-semi/Networking/Optical` (the REAL chain name — verified in `watchlist_chain`; there is no chain called "Optical-Communication", that is the *domain*) renders the stored report (assemble one first via the research-reports assemble endpoint if none exists locally), calendar strip, underwriting panel, alias questions. Screenshots to `output/playwright/` with descriptive names.
- [ ] **Step 4: Record findings** in the PR description draft; fix what the smoke surfaces before Task 18.

### Task 18: CHANGELOG + PR for P3

- [ ] **Step 1:** `[Unreleased]` entries (one line per Task 12–16 deliverable, in the file's voice).
- [ ] **Step 2:** Full local gate: `uv run pytest -x -q` AND `cd web && npm run test` AND `cd web && npm run gen:types && git diff --exit-code web/lib/types.ts` (types committed and current).
- [ ] **Step 3:**

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for the fundamentals desk pages"
git push -u origin feat/fundamentals-desk-pages && gh pr create --fill
```

Wait for CI green; merge only after.

---

## Plan self-review (authoring time; re-run 2026-08-27 after the adversarial-review fixes)

- **Spec coverage:** §2 routes → Tasks 13–16, with the extension contract now TESTED (Task 13's rows-only chain test) and the `/chains`+`ChainMatrix` fold-in routed (Task 15); §3a–f → Tasks 13/16 (a: delta rail with one-filing-one-entry dedupe, b: calendar with `?chain=` scoping, c: matrix rules incl. DISTINCT-ticker counts and the no-median rule for valuation percentiles, d: profit pool, e: capex strip — deliberately copy-only, decision stated, f: limits — computed membership/exposure numbers, prose only as captions); §3 anti-requirements → Task 13 Step 1 tests + Task 16 rules + two Global Constraints bullets (percentiles-are-name-facts; no desk inventory panel); §4 node additions → Tasks 9/13/14 (DIO + SBC + UW-derived diluted-share YoY, is_member + alias questions, filed-line-item provenance with filing date + raw values on the row, as-of via report versions, NodeLimits block naming the four un-attempted inputs); §5 i–vii → Tasks 4–11 (vii rewritten to the real `register_version`/`activate`/`active_version` mechanism with the engine-wide blast radius stated as a decided, executor-visible point); §6 research-dir commit → Task 1; §7 P1 → Tasks 1–3; §8 open questions → APH/CIEN surfaced not resolved (Task 14), `chain_aggregate` straddle stays a backend open item, DC-REIT/Colo partial coverage renders through named-missing-tickers, `/fundamentals` absorbs Radar (Task 15).
- **Declared deviations (both judged faithful in review, loose ends closed):** (a) "filing-landed" maps onto the live `statement_published`/`sec_filing` classes, with the double-fire dedupe rule now on the delta endpoint; (b) underwriting features stay out of the scored `FEATURES` list, with the single-quarter (no-TTM) basis now justified, and diluted-share YoY re-sourced from the UW store to keep the node page single-vendor.
- **Placeholder scan:** the AUTHORING STEP freezes are deliberate no-fabrication gates, not placeholders — each names its exact source and query. No TBD/TODO remain.
- **Type consistency:** `EarningsCalendarRepository` (Tasks 4/5/6/7/8/17), `ImpliedMoveRepository.history` (7→8), `underwriting_features` returning `dio`/`sbc_to_revenue`/`shares_outstanding_yoy` (9→13→14; the plan's original `share_count_yoy`/diluted premise was disproved during Task 9 and every downstream reference was corrected 2026-08-28), `NodeUnderwritingRow` provenance fields (13→14), `deskCalendar(section, chain?)` (13→14), runner script names (5/6/7/8/12→17) checked for exact-name agreement.
- **Verified-against-code:** migration collision 130 and 131 (both trees listed); `daily_ohlc` (003); `option_surface_grid_daily` (077); `record_events`/`register_discovery_gate`; `in_buy_zone(engine_version)`/`band_coverage`; `record_violations`/`check_violations`; `TICKER_TO_TYPE`/`SECTOR_TO_TYPE`/`seed_company_types` (incl. the already-present optical map entry); `FundamentalScoresRepository.register_version`/`.activate`/`.active_version` + `fundamental_anchors.py:603` + sole caller `scripts/seed_fundamental_method.py:73`; `chain_membership_open_uq` partial unique index; `ResearchTaxonomyRepository.exposure_coverage` (worktree `research_taxonomy.py:305`); `current_statement_panel`/`statement_panel_as_of` in `storage/fundamental_observation_panels.py` with `statement_panel` as the kept alias; `filing_published_at` (114); `massive_fundamentals.share_count_delta` (066 — cited only as the rejected dual-source); `build_features` input shape; `fetch_calendar_symbols`; `/jobs` router has only rescan endpoints; fixture `seeded_db_empty_cards`; `ReportView.tsx`/`RadarTable.tsx`/`reports/page.tsx`; `FundamentalResultState` literals.
- **Could NOT verify (executor must, at the marked steps):** UW cash-flow SBC, diluted-shares, and cash-flow NI key names (probe steps, Tasks 9/10, with stated honest fallbacks); exact `chain_membership`/`research_chains` column names post-renumber (Task 3 reads the migration); the specific misrouted optical tickers (Task 11 probe); NVDA/ISRG calendar dates for Task 4's fixture (authoring re-verification step); existing API-test bootstrap fixture names (Task 13 reads them first); the seed script's `code_version` fill behavior (Task 11 Step 3 reads it).
