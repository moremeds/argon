# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

### Added
- **The macro ledger can now say "we accepted this and were wrong"** — additive, point-in-time
  evidence invalidation (migration `131`, `macro_evidence_invalidations`). F2, the last open item
  in the macro program.
  - **The gap it closes.** `macro_observations` is immutable — migration 115's guard rejects every
    `DELETE` and every `UPDATE` touching anything but `last_seen_at` — so `quality_status` can never
    be moved to `quarantined` after the fact. The ledger could say *we never accepted this*; it had
    no way to say *we accepted this and were wrong*. The guard is correct and is untouched; this is
    an overlay beside it, not a mutation of it.
  - **One predicate produces both required behaviours.** The invalidation carries its own
    point-in-time clock — `invalidated_at <= as_of`, deliberately the same shape as the
    `available_at <= as_of` that already governs every macro read. A replay of 2021 does not yet
    know about a 2026 discovery and returns the row Argon genuinely stood on; a read today knows and
    excludes it. There is no "current versus replay" branch for a caller to get wrong.
  - **`invalidated_at` is when WE DISCOVERED the problem, never when the publisher made it.** Keying
    it on the publisher's error date would silently rewrite history: every replay between the two
    dates would stop returning a row Argon believed for those months.
  - **Four of the five readers take the predicate; `fetch_macro_observation_history` must not.** It
    is the audit view, and filtering it would answer *what did we discard and why* with a view that
    had already discarded it. It joins and MARKS instead — the row, the discovery instant, the
    reason and the reviewer, side by side.
  - **`vintage_*` bounds the publication, `period_*` bounds the reading**, and the pair is not
    interchangeable: one says which readings are bad, the other which publications of them are. The
    FRED rebasing needs exactly that separation — every period, but only the vintages before the
    republish. A test asserts both directions, because swapping them in the predicate flips both.
  - **Range columns are `period_from`/`period_to`, never `period_start`/`period_end`.**
    `macro_observations.period_end` already exists and the join predicate references both tables, so
    reusing the name would produce a filter that silently compares a row to itself.
  - **The tests were rewritten once, and the reason is recorded in the plan.** The first version
    passed 10 of 13 *with the feature not yet built*: it invalidated the pre-rebasing vintage and
    asserted the post value came back, but the post row already wins on `available_at DESC`. The fix
    was a second period held only at its pre-rebasing vintage, where exclusion is the difference
    between a value and `None`. Every test now names the production change that breaks it.
  - Verified against the frozen FRED rebasing (`WRESBAL` period 2025-06-04 carrying `3294.381` at
    vintage 2025-06-05 and `3294381.0` at 2025-11-13, both labelled `millions_usd`), **not** against
    production — production holds zero known-bad macro observations out of 28,941, so there is
    nothing there to exclude.
  - **It does not repair a series.** Invalidation removes evidence from consideration; it never
    rewrites a value. A per-vintage `publisher_transform` is the recovery path and is a different
    mechanism with its own measurement burden.
  - Enrolled in the gap-healer registry as unhealable (153 → **154 datasets**). An invented
    invalidation is the rare fabrication that SUBTRACTS — it would remove real observations from
    every point-in-time read after its instant.

### Changed
- **Phase 1 of the top-down macro program is closed**, scored against the eight completion criteria
  it wrote for itself on 2026-08-12 (`2026-08-12-top-down-macro-context-program.md` §10). Six are met,
  two are not, and the two are recorded as *answered* rather than *outstanding*. Documentation only.
  - **What ships:** a replayable, evidence-cited, refusal-capable description of inflation →
    policy/rates → USD → gold. Every output replays from exact observations at their exact vintages,
    the desk refuses as a chain rather than rendering four fresh-looking cards, and no macro number
    reaches a score, a ranking, a size, or the Fundamental PM surface.
  - **What does not ship, and why it is not a backlog item:** criteria 6 and 7 — attach and detach a
    versioned company/chain exposure overlay on a PM report — were gated on MC6, and MC6's preflight
    returned `descriptive_only`, one of its own three designated verdicts. The criterion reached its
    exit and the exit said do not build it. Filing that as "incomplete" would misread a measurement
    as unfinished work.
  - **The Fundamental PM surface is byte-identical to what it was before this program started**, by
    construction rather than by feature flag: nothing downstream consumes macro state.
  - The only named path that could reopen MC5/MC6 is the release-**event** preflight — a different
    unit of analysis from the monthly state label that both the flip census and the preflight
    rejected. It is unauthorized and unstarted.
- **The macro program's plans and specs moved to `docs/superpowers/archive/{plans,specs}/`** — seven
  plans (MC0–MC6 plus the program registry) and six specs, per the archive README: active directories
  hold work in progress, completed work moves. Every reference was rewritten and verified rather than
  assumed — a repo-wide scan now resolves every `docs/superpowers/{plans,specs}/*.md` path that any
  tracked file mentions.
  - The specs are cited from **production docstrings** (`macro/{inflation,rates,usd,gold,gold_state}.py`),
    from four generator/probe scripts, from three frozen golden fixtures' `spec` provenance field, and
    from `tests/unit/research/test_fomc_sep_verdict.py`, which resolves the durability spec as a real
    `Path` and reads it. Generators and their fixtures moved together, so regenerating a golden is
    still a no-op.
  - Two dangling references inside the archived plans are **left as they are**: MC2's plan says to
    create `2026-08-12-inflation-rates-state-design.md` (it shipped as `2026-08-18-`), and MC5's plan
    names a `company-macro-exposure-design.md` that was never written because MC5 was killed. Both
    predate this change. Repointing them at what actually happened would falsify what the plan said —
    the same reason F2 annotates evidence instead of rewriting it.
- **MC5 and MC6 are closed, and the macro program's authority boundary is now a measured finding.**
  Operator decision 2026-08-26; plan status updated in `2026-08-12-top-down-macro-context-program.md`
  and `2026-08-24-macro-mc4-mc6-sequenced.md`. Documentation only — no code, schema or behaviour changes.
  - **MC6 reached its own designated exit rather than stalling short of it.** `descriptive_only` is one
    of the three verdicts its Task 12 was written to publish. The preflight that produced it was not in
    the original plan; it asked a question that plan never asked — is there enough sample to test
    ANYTHING — and answered it before the expensive walk-forward harness of Task 11 was built.
  - **Information and sample size run in opposite directions in this panel**, which is why no harness
    could have been trusted to pick its own target: the three features with the largest effective
    sample are all two-valued *was the publisher on time* binaries scoring `eff_n` ~294–298, high
    precisely because they are noisy. Every economically meaningful feature lands at `eff_n` 0.9–27
    over 5.6 years.
  - **MC5's closure is a different decision from its verdict, and the distinction is recorded.**
    `descriptive_only` says *retain MC4/MC5*, written assuming MC5 would already be built when MC6 ran.
    It never was, so the live question was whether to BUILD it — which that taxonomy does not answer.
    It is closed for want of a positive reason, not because the verdict forbade it.
  - Reopening either requires a release-**event** preflight (FOMC 55 observations across 55 distinct
    `available_at`, SEP 25/25, CPI family 145 release instants) AND a fresh authority decision. That
    preflight is unauthorized and unstarted; surprise definition, baseline and horizon are all unspecified.

### Fixed
- **`CLAUDE.md` said schema changes apply out-of-band via the profile-gated migrator. They do not.**
  The `api` service self-migrates before serving (`python -m uw_scan.storage.migrate_runner && exec
  uvicorn`, `docker-compose.yml`), so a Watchtower deploy carries its migrations with it; the
  `migrator` service exists for explicit out-of-band applies, not for the normal path. The runbook
  (`docs/runbooks/docker-deploy.md`) had this right — only the master policy file was stale, which is
  the copy an agent reads first. A schema change that must land *before* its code still needs the
  out-of-band run, and that caveat is now stated where the wrong claim used to be.
- **The F5 gold-schedule exit was recorded as blocked by a dev-database artifact.** The plan said the
  persisted smoke "cannot run until a gold domain state exists (none has ever been computed)". That was
  measured against `option_wizard_local`. **Production has held gold states since 2026-08-23**, and they
  carry the defect and its fix directly: state 30 (Mon 2026-08-24 19:40 ET) read a gauge computed for
  2026-08-21 — three days stale, because the old schedule ran the posture at 21:00, 80 minutes *after*
  the state that consumes it — and state 34 (Tue 2026-08-25 19:40 ET, first run under the new schedule)
  reads `obs_date` 2026-08-25, age **0**. The blocker also conflated two claims: the MC6 preflight found
  gold cannot **replay**, which says nothing about computing tonight's state.

- **Statement versions now record WHEN they became usable, and historical scoring
  must name the evidence it stood on.** `fundamental_statement_obs` was already an
  honest immutable ledger — a restatement lands beside the original, never over
  it — but it carried no availability information at all, so `statement_panel()`
  answered "which version applies at time T" with `ORDER BY obs_id DESC` **and no
  cutoff**: every historical question got today's panel, and the scoring job built
  its knowledge-quarter cross-sections on exactly that. Measured against
  production: over all 200 identities holding more than one content version, the
  `obs_id` pick and the availability pick disagree **0 times** — and cannot
  disagree while availability is capture time, because `first_observed_at` and the
  BIGSERIAL are assigned in the same INSERT. What bit was the missing cutoff, not
  the ordering; the ordering becomes load-bearing only once a publication date
  arrives from a source independent of insertion order.

  New append-only `fundamental_obs_availability` (migration 130) holds one claim
  per (observation, rule) in four classes — `true_pit` (positive publication
  evidence), `capture_bounded` (Argon holds this content and first saw it then),
  `current_vintage` (today's page only), `unknown` — with CHECK constraints
  binding the timestamp to the classes that earn one. Evidence _strengthens_ over
  time, so a stronger claim INSERTs beside its predecessor rather than updating
  it; there is no update path in the repository at all.

  The reader split in two: `current_statement_panel` (unchanged newest-version
  semantics, what the card and anchors use) and `statement_panel_as_of(as_of,
evidence_policy)`, which fails closed — an observation with no claim never
  enters a replay. `fundamental_scoring` takes an `evidence_policy` argument with
  no historical default; a replay buckets each row by when ITS version became
  available rather than by the period's original filing date, and persists the
  policy, cutoff and selected claims (migration 131). Existing score rows are
  untouched and correctly labelled `current_vintage`.

  `filing_published_at` does **not** promote anything to `true_pit`: it describes
  the _original_ filing for the period, and a later content hash is a different
  artifact. Promoting on it would take true-PIT coverage from nothing to nearly
  everything in one run while reintroducing the exact look-ahead this removes.
  Expect `TRUE_PIT_ONLY` replays to return empty until a publication-evidence
  adapter exists — that is the correct answer, not a fault.

  Backfill: `scripts/backfill/fundamental_observation_availability.py` (zero
  provider spend, resumable by keyset, `--audit` writes a self-checking coverage
  artifact). Runbook `docs/runbooks/fundamental-observation-availability.md`.

## [0.12.17] — 2026-08-25

### Fixed

- **The gold domain state read yesterday's gauge every single night.** `gold_posture_compute`
  ran at 21:00 ET; the macro state compute that consumes its row runs at 19:40. The posture
  row for day D is stamped with the latest `GLD_CLOSE` date, so an evening run on D writes
  `obs_date = D` — which did not exist yet when the state asked for it 80 minutes earlier.
  Not a failure mode on a bad night: the schedule guaranteed it on every good one, while
  `gauge_age_days` honestly reported the lag the schedule itself was creating.
  - GPR ingest moved 20:00 → **18:35**, posture compute 21:00 → **19:10**, both still Mon–Fri.
    The whole rest of the daily cascade already finished by 18:30.
  - **Moving GPR earlier was measured, not assumed.** Its publisher file is a static academic
    `.xls` already running 2–3 days behind the fetch — an ingest at 19:00 ET on 2026-08-19
    returned an observation dated 2026-08-17. The fetch clock was never the binding constraint.
  - The test locks the **order**, not the clock: posture after every ingest it reads, before the
    state that consumes it. Moving the block stays free; inverting it does not.
  - Two claims made earlier in this work were wrong and are corrected in the plan doc: `0-4` is
    Mon–Fri (verified against APScheduler 3.11.2), not Sun–Thu, so "Friday never runs" was false;
    and the blocking question "which close does a posture row cover" was already answered in code
    by `_latest_gold_market_date`.

### Added

- **The macro desk reads one snapshot, and renders its refusal.** Slices 3 and 4 of MC4,
  which completes it.
  - **Option A, deliberately: the banner reports, it does not withhold.** A broken chain
    shows the verdict AND keeps all four cards. The authority boundary for this layer is
    risk-monitoring — it may say the chain is broken and where, and it may not decide for
    the reader that the individual answers have stopped being worth seeing.
  - The offending domain is flagged on its own card as well as in the banner, prefixed
    with the domain name: the flag sits between two cards, and without a name it reads as
    belonging to the one above it.
  - **A missing snapshot renders as "chain never assembled", never as a clean chain.**
    Absence of a check is not a passed check, and the four cards below it are then four
    independent reads with nothing having compared them.
  - **Verified against real stored data, and it caught a real incompatibility.** In the
    local store, USD state 22 cites `policy_rates` state **21** while the latest rates
    answer is state **23** — states 20/21/22 came from one pass at 00:45:14 and state 23
    from a rates-only rerun at 01:15:44 with no matching USD recompute. Every one of those
    rows is individually current and individually honest; the four-request page reads 22
    and 23 side by side as a chain and nothing about a timestamp gives it away. Path
    exercised end to end: job → `macro_context_snapshots` → `GET /api/macro/snapshot`
    (`status: incompatible`) → `/macro` rendering the banner, both flags and all four
    cards. Screenshot: `output/playwright/macro-chain-incompatible-2026-08-25.png`
    (gitignored by policy).
  - Caveat recorded rather than buried: that instance is from `option_wizard_local`, where
    a single-domain rerun is exactly what ad-hoc dev work produces. Whether production
    carries the same shape is **unverified** — the point it proves is that the detector
    works on real stored edges, not that production is broken.
  - `web/lib/types.ts` regenerated. Generated from the live unsorted spec, not from
    `openapi.snapshot.json`: the snapshot is stored `sort_keys=True`, and generating from
    it reorders every schema — a 5,005-line diff carrying the same 156 lines of content.

- **The macro context snapshot — assembler, nightly job and `/api/macro/snapshot`.**
  Second of four slices; the snapshot is now assembled, persisted and served, and the
  page still reads four independent states until slice 3.
  - **The defect it closes is invisible from any single row.** Every timestamp in a
    partially-failed chain is honest and nothing is late. What is wrong is which upstream
    ANSWER a downstream stood on — so the verdict is decided by dependency-edge
    **identity** (does the `state_id` USD actually cited equal the one this snapshot
    holds for rates), never by comparing clocks. A test pins exactly that: four
    candidates sharing one `as_of`, one of them citing last night's rates, and the
    assembler refusing to call it `complete`.
  - **It never substitutes a fresher upstream to make the chain look coherent.** In the
    incompatible case the fresher rates state is right there and visible; the snapshot
    stores what USD cited anyway and names the incompatibility. Substitution is how a
    monitoring layer becomes a fabrication layer, and it is the one property that must
    not be traded for a tidier page.
  - `incompatible` outranks `partial` when both apply. *"Rates never ran"* sends an
    operator to the scheduler and *"rates ran but USD ignored it"* sends them to the
    data; reporting the milder one would point them at the wrong place.
  - **`status` is part of `inputs_hash`.** The same four state ids with a different
    coherence verdict are two different answers, and one identity could only store one
    of them.
  - The job reads the stored dependency edges rather than anything the nightly pass holds
    in memory, so tonight's assembly and a replay of any past instant run identical code.
    A live-only path would be a second implementation to keep in step.
  - It runs LAST in the nightly pass and under the **same** `as_of` as the four domains.
    Every domain job catches its own exception, so the loop reaches the assembler after a
    partial failure — which is precisely the case the snapshot exists to name.
  - `GET /api/macro/snapshot` (with `as_of` / `as_of_ts` replay) **404s rather than
    inventing an empty snapshot** for an instant nobody assembled one for, matching the
    domain-state routes: "nothing was recorded" and "we recorded a refusal" are different
    answers and a reader must be able to tell them apart.
  - A `complete` status asserts only that the chain is internally coherent. It is not a
    claim that the macro picture is right — the states remain descriptive, per the
    2026-08-24 preflight.
  - `web/lib/types.ts` is regenerated in slice 3, where the UI first consumes the route;
    the API contract itself is gated by the updated `openapi.snapshot.json`.

- **The macro context snapshot — contract, schema and storage** (migration `130`). First of
  four slices; this one is persistence only, and nothing assembles or reads a snapshot yet.
  - **What was missing.** The four domain states are each individually honest: they record what
    they stood on, and `macro_domain_state_dependencies` (migration 128) already records
    state → state edges. No table said the four belong *together*. So `/macro` composes four
    independent latest reads, and the nightly worker — which does use one `as_of` and the right
    causal order — catches each domain's exception and continues. **A failed rates job lets USD
    read the previous rates state** (still satisfying `available_at <= as_of`), persist a new USD
    state citing it, and gold consume the mixture. Four cards render fresh and nothing can tell.
  - **The snapshot exists to refuse, never to repair.** It may not substitute a fresher upstream
    to make a chain look coherent. Substitution is how a monitoring layer becomes a fabrication
    layer, and it is the one property that must not be traded for a tidier page.
  - Status will be decided by **dependency-edge identity** — does the upstream `state_id` a
    downstream actually cited equal the one this snapshot holds for that domain — never by
    timestamp proximity. Migration 128 already stores those edges, so the check reads them
    rather than inferring anything from clocks.
  - Four statuses stay distinguishable on purpose: `complete`, `partial`, `incompatible`,
    `stale`. *"Rates never ran"* and *"rates ran but USD ignored it"* are both refusals and call
    for different operator actions, so collapsing them to one "degraded" would destroy the only
    thing the status is for.
  - **Absence is the lack of a row, never a row carrying a null** — `state_id` is `NOT NULL`. A
    nullable one would make every reader decide again what a null meant, and one of them would
    decide it meant zero.
  - `inputs_hash` covers the domain state **identities** plus the assembler's parameters, so a
    nightly rerun over unchanged states is a no-op rather than a second opinion, and a later
    evidence revision cannot change a stored snapshot's hash — a revision produces a new state
    rather than editing one.
  - `fetch_macro_context_snapshot_as_of` returns `None` before any snapshot existed rather than
    an empty snapshot: an invented *"we knew nothing"* row is a claim Argon never made, and a
    reader cannot tell one from a real refusal.
  - Both tables are enrolled in the gap-healer registry as unhealable (151 → **153 datasets**).
    A healer that invented a missing snapshot would be asserting that four domains once agreed,
    which is precisely the claim this table exists to be able to refuse.

### Added

- **Fundamental run ledger — the engine's control plane (M2.4).** Migration `135` +
  `storage/fundamental_runs.py` + `worker/jobs/fundamental_run.py`.
  - `fundamental_scores` records an ANSWER; nothing recorded the QUESTION. A run that produced
    nothing left no trace, so "the panel was empty" and "the job never ran" were
    indistinguishable afterwards. A run row carries scope, as-of, evidence policy, engine version,
    mode, per-stage state and counters.
  - **Idempotency is a request hash, not a timestamp.** `request_hash` covers scope + as_of +
    evidence policy + engine, and deliberately excludes the clock: a run one second later asking
    the same question is the same question. `mode='reuse'` matches on it EXACTLY — a "close
    enough" match would answer the operator's question with someone else's.
  - Stages are rows, not a status column: "failed at anchors after scoring succeeded" is the
    difference between re-running everything and re-running one stage. A retry gets a new attempt.
  - A partial unique index enforces at most one active run per request; `cancel_stale()` clears
    heartbeat-dead runs, which otherwise block that question forever through the same index.
  - Verified end to end on a leak-free run: `TRUE_PIT_ONLY` at as_of 2024-06-30 over 25 names
    chained routing → scoring (1,535 scored, 74 buckets) → anchors (25 written), and a reuse
    request returned the same run rather than recomputing.

- **Independent research-priority dimensions, each carrying its own permission (M2.3).**
  `fundamentals/dimensions.py` + migration `136` + `storage/fundamental_dimensions.py`.
  - Seven dimensions persisted separately, because `authority` is per DIMENSION, not per result.
    A column layout would force one authority per row — which is exactly how a contradicted sign
    rides along inside a validated composite.
  - **Two dimensions are capped at `descriptive` and both caps are load-bearing.**
    `operating_quality`'s inputs measured INVERTED (high-margin names underperformed, 2026-08-12),
    and `valuation`'s own-history finding was computed by a script pairing raw closes with shares
    UW restates to today's split basis, never rerun. Neither may enter the priority aggregate.
  - `investment_ranking` is refused by CHECK constraint, not merely unused — it needs the GX gate
    this program does not provide.
  - Renormalization is explicit: a missing dimension is dropped, the aggregate names which were
    used and which were missing, and it REFUSES below two present rather than calling one
    dimension a priority. Treating a missing dimension as 0 would pull every incomplete name
    toward the middle of the ranking — an artifact of absence that looks like a measurement.
  - `evidence_quality` is measured against the claims table, not the run's `availability_ids`: a
    current-vintage run never populates those, so deriving coverage from them reported "this run
    did not look" as "the evidence is not there". NVDA reads 1.0 (3/3 true_pit), not 0.0.

### Changed

- **`fundamentals/valuation.py` split by domain seam (M2.1).** 987 lines → `valuation.py` (623,
  `build_anchors` + refusal), `valuation_policy.py` (197, routing and thresholds),
  `valuation_math.py` (261, arithmetic). Every name is re-exported, so no import site changed.
  - `anchor_inputs_hash` now reads the rule constants THROUGH the policy module rather than
    through names bound at import. `from X import CONST` binds once, which makes "changing a rule
    changes the band identity" unprovable — the exact property a test asserts.

- **SEC publication evidence — replayable fundamental history goes from 8 days to 22 years (M1-A).**
  `sources/sec_submissions.py` + `fundamentals/publication_evidence.py` +
  `storage/sec_filing_index.py` + migration `132` + `worker/jobs/{sec_filing_index_refresh,
  fundamental_publication_evidence}.py` + `scripts/backfill/sec_publication_evidence.py`.
  Verdict: `docs/research/2026-08-25-sec-publication-evidence/`.
  - `true_pit` went from **0 to 73,994 claims** over **396 of 401 tickers**, period ends
    2003-12-31 → 2026-07-31. Before this, every `TRUE_PIT_ONLY` replay was empty at every cutoff
    and `CAPTURE_BOUNDED` was empty before 2026-08-16, because the whole statement table came from
    one 8-day backfill and the only availability evidence was "when we fetched it".
  - **Yield 84.8%** (73,769 of 86,951 identities). Refusals: `no_filing` 10,335 — mostly
    structural, a 20-F annual filer has no quarterly filing for a quarterly period to match;
    `amended` 2,210; `no_index` 633; `ambiguous` 3; `multi_version` 1.
  - **An amendment refuses the whole period, deliberately.** UW serves *current* data, so for an
    amended period the single version Argon holds may be the restated content. Dating it at the
    original filing is `filing_published_at`'s trap wearing SEC's authority.
  - Three things that will bite: `filings.recent` is a WINDOW, and following `filings.files[]`
    archives is what turns NVDA's 3-year panel into 111 filings over 2006→2026; the macOS system
    proxy kills `www.sec.gov` with `SSL_ERROR_SYSCALL`, so the client hard-codes
    `trust_env=False` (same class as `MassiveWsClient`'s `proxy=None`); and SEC's `reportDate`
    is not `period_end` — a ±7-day tolerance reusing the existing exact-first rule matched 93.9%
    of NVDA's quarters against 13.4% exact.
  - Zero provider budget. SEC is free and keyless and never enters the UW governor.

- **Recorded integrity violations now gate the math, not only the card (M1.1).**
  `fundamentals/validity.py` + `fundamentals-v2` engine version + `worker/jobs/fundamental_scoring.py`.
  - `violated_fields`' docstring said it plainly: "the raw feature stays as computed and the
    DISPLAY layer suppresses it". A gross margin of exactly 1.0, known to be a provider echo,
    still contributed a z-score that moved every other name's rank.
  - Measured on 28,800 paired rows: **2,386 feature values withheld** across 1,067 periods.
    Only 1,058 rows (3.7%) directly lost a value, but **94.5% of composites changed** — a z-score
    is relative to its cross-section's mean and sd, so withholding one name re-centres everyone.
    Pearson v1 vs v2 = 0.978; individual names move multiple sd (CLDX 2007: −0.05 → −3.33).
  - **`fundamentals-v1` replays byte-identically** — a v1 rerun after v2 inserts zero rows,
    because none of the exclusion code runs for it. v2 is registered but NOT activated; switching
    the default is a measured decision, not a deploy side effect (`--activate-v2`).
  - The validity policy is read from the ENGINE VERSION, never passed in, so a row cannot claim a
    method it did not run. An unregistered code version raises rather than inheriting v1's.
  - Exclusion propagates through the TTM window: a bad `total_revenue` contaminates four
    quarters, and `rev_growth` reaches eight. Excluding only the violated quarter would leave
    most of the damage in the math while reporting the field handled.

- **Evidence invalidation, designed** —
  `docs/superpowers/archive/specs/2026-08-24-macro-evidence-invalidation-design.md`. Not implemented, and
  deliberately deprioritized behind MC4; see below.
  - `macro_observations` is immutable — migration 115's guard rejects every `DELETE` and every
    `UPDATE` touching anything but `last_seen_at` — so `quality_status` cannot be moved to
    `quarantined` after the fact. The ledger can say *we never accepted this*; it cannot say
    *we accepted this and were wrong*. That gap is real and the guard is correct; the fix has to
    be an additive overlay.
  - **The belief-preserving decision collapses the design to one predicate.** Making the
    invalidation itself point-in-time — apply only invalidations whose `invalidated_at <= as_of` —
    produces both required behaviours from a single rule: a 2021 replay still returns a row a 2026
    invalidation condemns (which is what Argon believed in 2021), and a read today excludes it. No
    current-vs-replay branch for a caller to get wrong, and the same shape as the existing
    `available_at <= as_of`.
  - Four of the five readers take the predicate. `fetch_macro_observation_history` must **not** —
    it is the audit view, and filtering it would answer *what did we discard and why* with a view
    that had already discarded it.

### Changed

- **Measured: production holds no known-bad macro evidence.** The handover's "the *local* evidence
  store holds 1,173 WRESBAL rows" is exact and the word *local* is load-bearing.
  `option_wizard_local` holds 1,173 rows (607 periods, 604 vintages, 566 pre-rebase);
  **`option_wizard` holds 0**, against 28,941 total macro observations. The bad data lives only in
  a dev database production never reads.
  - The plan's exit criterion — "WRESBAL remains physically present, current readers exclude it" —
    is unsatisfiable against production, and implementation must verify against the frozen FRED
    rebasing fixture instead.
  - **F2's ordering ahead of MC4 dissolves.** It assumed snapshots bake evidence lineage into
    immutable rows. Under a point-in-time overlay nothing is baked in: the filter applies at read
    time from the reader's own `as_of`, and an immutable snapshot keeps citing exactly what it
    stood on — the correct belief-preserving answer. MC4 fixes a live defect; this has zero
    production instances, so MC4 goes first.

### Added

- **MC6 preflight — verdict `descriptive_only`.**
  `docs/research/2026-08-24-macro-continuous-feature-preflight/` plus
  `scripts/research/macro_continuous_feature_preflight.py`. Read-only; it replays the engines at
  historical instants and never touches `macro_domain_states`.
  - The 2026-08-23 flip census replayed monthly and got 68 points. That clock was a choice — the
    engines take weekly without complaint (**294/294 instants, three domains, zero errors**). It
    did not help.
  - **Information and sample size run in opposite directions here.** The features with the largest
    effective sample carry none: `usd term.freshness` scores `eff_n` 298 on **two** distinct
    values, because a high effective sample comes from being noisy rather than informative. Any
    harness ranking candidates by sample size would select exactly these.
  - Every economically meaningful feature lands between `eff_n` 0.9 and 27 after the AR(1)
    correction. `change.DTWEXBGS` — the momentum the entire USD engine rests on, whose threshold
    PR #377 moved — is **12.8** over 5.6 years. A non-overlapping cross-check independent of the
    AR(1) model gives ≈22, the same order.
  - **Longer history does not rescue it and faster sampling is what the correction measures.**
    Reaching a merely modest `eff_n` of 100 needs 21–57 years for the best features and centuries
    for the rate levels. The constraint is that these variables move slower than any window a desk
    will hold, not that our store is short.
  - 14 of 71 features are constant across all 294 instants, including `term.quality` and
    `term.revision_penalty` in **every** domain — an independent corroboration of PR #380, since a
    term that never varied in 5.6 years cannot fail a test that only exercises it.
  - **One candidate survives and is not endorsed:** release events replay point-in-time —
    `federal_reserve_fomc` 55 observations across **55** distinct `available_at`, SEP 25/25, CPI
    family 145 release instants from 2015. Discrete non-overlapping releases escape the overlap
    death. n≈55–145 is small, surprise/baseline/horizon are unspecified, and it gets its own
    preflight or it gets dropped.
  - Gold remains structurally excluded: `GLD_CLOSE` holds 275 periods across **3** availability
    instants, `GLD_HOLDINGS_OZ` 274 across **1**.

### Changed

- **MC6 over state features is closed, and MC5's hold is now a finding rather than a procedure.**
  Do not build the walk-forward harness for this panel; the preregistered sample gate fails before
  a target is even chosen, which is the right place to stop. The risk-monitoring authority boundary
  is not the conservative option — it is the only one the measurement supports. MC4 proceeds
  unchanged, which is why the preflight ran in parallel with it rather than after.

### Fixed

- **Macro confidence now explains the set it actually measured.** `compute_confidence`
  drew its terms from two different sets and called all of them *load-bearing*, so USD
  and Gold each shipped `2/1 load-bearing inputs present` to production — a ratio above
  its own denominator, because the value counted requirements while the sentence beside
  it counted every factor consumed. Both states carry one required anchor and one
  optional input.
  - **The `revision_penalty` divisor was the real defect, not the sentence.** Its
    numerator is filtered to the required set by `revised_series`; its divisor counted
    every factor. A revised USD anchor beside one optional factor therefore scored
    `1/2` — the term that exists to punish a revision punished it half as hard, and the
    optional input doing the halving contributes nothing to the state being revised. It
    read `0` across all four domains only because no series had been revised yet, which
    is also why no caller-level test could have caught it.
  - `freshness` and `quality` keep averaging over everything the engine consumed — an
    optional input the engine read does bear on how reliable the answer is — so what
    changed there is the claim, not the arithmetic. The quality detail now names the
    count it averaged and says how many were optional.
  - **All four engine versions bump** — `inflation/2`, `rates/2`, `usd/3`, `gold/2`.
    The state *labels* are untouched, but confidence is published on the state record,
    and a reader comparing it across this change would be comparing two arithmetics.
    `engine_version` is the selector that keeps them apart; stored states under the old
    versions stay readable and keep their own semantics.
  - No current production confidence *value* changes: every affected term is either a
    sentence or currently `0`.
  - Two integration tests pinned `"inflation/1"` / `"rates/1"` as literals, which turns
    a deliberate bump into a failure that reads like a regression. They now assert
    against the engine constants, which is the thing worth proving — that the API
    round-trips the engine's identity.

### Changed

- **The macro program plan agrees with the repository again.** It mapped MC1 to PR #359
  (it was #348), still labelled MC3 `in_progress` after four merged PRs, omitted `usd/2`
  and `/macro` entirely, and — with its MC4–MC6 child — reserved migrations `117`/`118`,
  both of which the Fundamental lane had already taken. The tail is `129`, so MC4 starts
  at `130`. `/macro` is now labelled **MC3.5, a descriptive chain viewer**, not a
  completed MC4: it composes four independent latest responses and is not an atomic
  snapshot. MC6's blocked status and the replay census that caused it are recorded
  inline, so the next reader does not have to rediscover why the sequencing changed.

### Added

- **`docs/superpowers/archive/plans/2026-08-24-macro-mc4-mc6-sequenced.md`** — MC4–MC6 re-ordered
  against what was actually measured, and the two decisions that were open in the handover, now
  settled: **historical replay preserves what Argon believed at the instant** (invalidation affects
  current reads; a corrected-history read is a reserved opt-in), and **the authority boundary is
  risk-monitoring** (report freshness, contradictions, missing domains and dependency
  incompatibility; never rank, size, recommend, or alter Fundamental PM output).
  - The MC6 preflight moves earlier and runs **in parallel** with MC4 rather than after it. It reads
    the evidence store and state records only, so it never needed the snapshot — and it is the item
    that decides whether MC5/MC6 happen at all. Building MC4 first and then discovering there is
    nothing to validate is the wrong order.
  - MC4 is specified as a **refusal layer**: status comes from dependency-edge identity, not
    timestamp proximity, and a snapshot may never repair an incompatible chain by substituting a
    fresher upstream. Substitution is how a monitoring layer becomes a fabrication layer.
  - The older MC4–MC6 plan keeps its task decomposition and carries a banner saying its sequencing
    is superseded.

- **`docs/handover/2026-08-24-macro-executive-summary-claude-handover.md`** — the
  reviewed executive status of the macro program: deployed truth, seven binding
  findings, the delivery sequence, and the completion gates. It was written against
  `v0.12.16` and had never been committed.
## [0.12.16] — 2026-08-23

### Added

- **A macro desk at `/macro`.** The four point-in-time domain states — inflation →
  policy & rates → USD transmission → gold gate — rendered in **causal order** rather
  than as four peer scorecards, each with its direction, confidence, freshness, velocity,
  contradictions, upstream answers consumed, cited-evidence count, and a collapsible
  "what this stood on" listing the load-bearing series and every confidence term.
  - They were previously invisible. `/api/macro/{inflation,rates,usd,gold}` have all
    existed and been computed nightly, and `web/lib/api.ts` consumed only
    `/api/macro/policy` — the states landed in a table nothing rendered.
  - **There is deliberately no composite, and there will not be one.** Averaging four
    differently-grounded answers into a single number would hide exactly the
    disagreements the contradiction lists exist to show. A test asserts the desk's own
    chrome carries no master score, allocation, or probability, and that exactly four
    states render with no fifth aggregate.
  - Each domain is fetched and settled independently: four engines, four schedules, so
    one dead publisher costs its own card rather than the page. The empty slot is
    three-state — an answer, a failed request, or "the engine has not run", which is not
    the same thing and must not render as the same thing.
  - Test fixture is real: `web/tests/fixtures/macroDomainStates.json` freezes the actual
    production responses (2026-08-23), evidence truncated to 2 rows per domain with the
    real length recorded — those lists run 139 to 1091 items, which is why the card shows
    a count and a drill-down rather than the rows.

- **A test that every macro domain's engine version and parameter version move together.**
  `tests/unit/macro/test_engine_versions.py`. Splitting them lets a recalibrated engine keep
  publishing under the old engine identity, so a reader asking for one semantics silently
  gets two. Not hypothetical: the USD recalibration above bumped the parameter version,
  left the engine version behind, and nothing failed.

- **Statement ingest is now calendar-driven and daily.** `fundamental_ingest_daily`
  (04:20 ET, uw-0, `UW_SCAN_FUNDAMENTAL_INGEST_DAILY_ENABLED`) reads UW's earnings
  calendar for the last 4 days, intersects it with the `ranked` universe, and pulls only
  the names that actually reported — about 6 a day against the monthly sweep's 450.
  Measured: a statement is retrievable the day the company reports (100% of reports 2–7
  days old, 98.5% across 704 report events over 120 days), so the monthly cadence's
  up-to-30-day staleness bought nothing and cost twice as much (~900 UW calls/month
  against 1,800). The lookback is outage insurance, not a wait for UW to publish.
  - The monthly sweep stays registered as a backstop, for two independent reasons.
    `premarket`/`afterhours` are the _classified_ calendar — a name UW reports as
    `report_time: "unknown"` appears in neither, verified for ISRG, SONY, DJCO and POET,
    ≈2% of the statement-bearing universe — and only a late full re-pull can collect a
    filing date UW published after we first stored the row.
  - New `sources/earnings_calendar.py` paginates both slots; the busiest day observed
    returned 257 rows, so a single-page fetch would have dropped the tail on exactly the
    days that matter.

### Changed

- **The USD state's boundary moved out of the middle of its own distribution.**
  `momentum_threshold_pct` 2.0% → 3.0%; `USD_ENGINE_VERSION` and `UsdParameters.version`
  both `usd/1` → `usd/2`. The retired 2.0% sat at the **61st percentile** of the broad
  dollar's own 63-observation moves, and a classifier whose boundary sits near the median
  of its inputs crosses that boundary maximally often — crossing density peaks where the
  density does. Replaying the state monthly over the stored evidence (2021-01..2026-08,
  68 instants) it flipped **29 times with a longest regime of 6 months**, alternating
  RANGEBOUND↔STRENGTHENING six times through 2022 alone — a year in which the dollar ran
  monotonically from ~96 to ~114. That is threshold proximity being reported as regime
  change.
  - At 3.0% (the **76th** percentile) the state flips **13 times with a longest regime of
    14 months**. RANGEBOUND is now the ordinary three quarters of the record and a
    directional call needs a top-quartile quarterly move. Distribution over 12,330
    momentum points: median 1.45%, p75 2.91%, p90 4.57%.
  - **Hysteresis was the first hypothesis and the measurement rejected it.** A dual
    entry/exit band left flips flat or raised them at _every_ entry threshold (at 3.0%:
    none 13, exit 2.25% → 17, exit 1.50% → 23), because a wider band relocates transitions
    rather than removing them. The lever is where the boundary sits, not how sticky it is.
  - Stored `usd/1` states keep their own semantics and stay readable — states are keyed
    `(domain, as_of, engine_version, inputs_hash)` and a reader filtering on
    `engine_version` gets one engine's semantics. Verified through the real
    `compute_usd_state`: 0 `inputs_hash` collisions between the two parameter sets.
  - This does **not** make the USD state testable: 13 transitions in 68 months is still
    far short of an MC6-grade gate. It makes the label mean what it says.
  - Sweep `scripts/research/usd_threshold_sweep.py`, replay census
    `scripts/research/macro_state_replay_census.py`, verdict
    `docs/research/2026-08-23-macro-state-replay-flip-census.md`.

- **`sources/apex.py` migrated to apex's `/v1/{asset_class}/{symbol}/bars`.** The flat
  `/bars/{ticker}` alias emits `Deprecation`/`Sunset: Wed, 31 Dec 2026` and resolves
  every symbol under `asset_class=equity`, so `GET /bars/SPX` was a
  `404 unknown_symbol` — the vol complex was unreachable from argon.
  - `fetch_bars` and `fetch_daily_bars` take `asset_class` (default `equity`); pass
    `volatility` for SPX/VIX/VVIX/COR1M. Verified live: SPX 1d closes 7674.37 on
    2026-08-21, VVIX 4183 bars from 2010.
  - `price_mode=adjusted` is now REQUESTED rather than inherited from apex's
    server-side `effective_price_mode`, so a config flip on the mini can no longer
    re-base argon's price series mid-stream. Sent for `equity` only — no other class
    has a Silver tree, and asking for one is a `400 adjusted_not_supported`.
  - `_iso()` emits offset-aware ISO-8601. apex `/v1` answers `500 internal_error` for
    a bare `YYYY-MM-DD` start and for a naive ISO datetime; only an explicit UTC
    offset parses. The flat alias accepted the bare date, so every caller passing a
    `date` — all of them — would have broken on the migration. Mocked transports
    cannot catch this; it took a live probe against 0.1.4.
  - apex's typed `error.code` (`adjusted_unavailable`, `unknown_symbol`, …) now reaches
    the log line. Every path here still collapses to `[]`, so the code is the only
    thing separating "apex refused" from "this symbol genuinely has no bars".

### Fixed

- **Three watchlist names' technicals were dead and nothing said so.** apex 0.1.4
  turned a missing livewire Silver artifact from a bare 500 into
  `503 adjusted_unavailable`; `fetch_daily_bars` never raises, so it collapsed to
  `[]`, the ~60-session `daily_ohlc` overlay alone fell under the 210-bar snapshot
  floor, and `technical_daily_refresh` charged the ticker to `skipped_thin` with an
  INFO line. Measured on the mini 2026-08-23 against the 171-name active watchlist:
  MSTR's `technical_daily` frozen at 2026-07-15 (26 sessions), APLD and CCJ holding
  zero rows. A name with 2006 rows of history does not have "thin history" — it has
  no source, and the two now count and log separately (`source_unavailable`, WARNING).
  - `technical_daily` enrolled in `reports/data_freshness.MONITORED_TABLES` with
    `date_col_override="as_of"` (absent from `_DATE_COL_PREFERENCE`; without it the
    row renders `date_col='?'` and measures nothing). It was already in the gap-healer
    REGISTRY — a separate list — which is why it looked covered.
  - **Ceiling, stated rather than papered over:** 3 missing of 171 is 98.2% coverage,
    so this row does not trip `LOW_COVERAGE_PCT` (50%). It makes the shortfall
    countable on `/api/health` and catches a TOTAL freeze; the per-ticker alarm is the
    job's new `source_unavailable` WARNING, which fires the morning it starts.
  - New CI gate: every `MONITORED_TABLES` entry must resolve a real data-date column,
    the freshness-monitor twin of the existing strict-registry gate.
  - DELL, SMH and XLE also serve a silently stale adjusted tail (200, last bar
    2026-07-13/14). The 60-session overlay still covers those gaps, so their series
    are current — they become the same failure once the gap outgrows the window.
    apex's `/health` reports `silver_last_trade_date` for the whole tree, so
    per-symbol Silver staleness is invisible there.
- **129 tickers had no filing dates because the two UW endpoints disagree about when a
  quarter ends.** The statement endpoints normalise a period to a calendar month-end;
  `fundamental-breakdown` reports the true fiscal period end. AAPL's June quarter is
  `2026-06-30` in one and `2026-06-27` in the other, so `_filing_dates`' exact dict
  lookup missed on every period of every 52/53-week filer, permanently — **0 of 885 NULL
  periods matched at tolerance 0**. Breakdown was never missing the data; it dates 100%
  of what it carries (AAPL 69/69).
  - Matching now falls back to the nearest breakdown period within 7 days, exact first.
    Read off the recovery curve rather than chosen: 7 days recovers 592 periods / 1,785
    statement rows, 98.5% of everything reachable at any tolerance, with **zero** of the
    885 periods matching two breakdown rows — quarters sit ~91 days apart, so the window
    cannot reach a neighbour. AAPL, AMAT, CSCO, INTC, HD, DE, WDC, LITE, ICHR and FN are
    recovered in full. The run reports a `filing_date_tolerance` counter so the hit rate
    stays observable instead of assumed.
- **A filing date that arrived after first ingest was discarded permanently.**
  `record_statements` ended `ON CONFLICT … DO UPDATE SET last_seen_at = now()`, and
  `content_hash` excludes the filing date by design — so the later re-pull carrying a
  newly-published date collided on an identical hash and updated only the timestamp.
  Live, not hypothetical: breakdown's frontier trails the statement endpoints for 7 of a
  random 40 names (INFY by 91 days, GFS by 181). The clause now fills a NULL via
  `COALESCE` and still never revises a date already recorded.

Method, probes and the full tolerance curve:
`docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md`.
Plan: `docs/superpowers/plans/2026-08-23-fundamental-calendar-ingest-and-filing-dates.md`.

## [0.12.15] — 2026-08-23

### Fixed

- **The gold ingest re-inserted its whole price history every run.** `macro_gold_ingest`
  hashed massive's OHLC response bytes verbatim, and massive stamps a fresh
  `request_id` — a 32-hex-character UUID — on every response. Same length every call, so
  `content_length` matched and only `content_hash` moved: the artifact dedupe missed, and
  all 275 `GLD_CLOSE` observations hanging off it re-inserted as a new vintage. Measured
  on the mini the night the job was enabled: a second run over an unchanged 400-day
  window took the series to 550 rows across 275 distinct periods under 2 artifacts. The
  SPDR tonnage leg was never affected — its archive carries no per-request stamp.
  - `macro/gold_ingest.py` now drops `VOLATILE_PRICE_ENVELOPE_FIELDS` from the payload
    and stores it as `raw_json`, so identity is the DATA rather than the envelope. Parsed
    JSON rather than edited bytes on purpose: `MacroSourceArtifact` and
    `storage/macro_context` re-derive the hash through the same canonical serializer, so
    normalising in one place and hashing in another cannot drift. The stored payload is
    no longer byte-identical to the wire — acceptable for a query result, and
    `source_url` plus `retrieved_at` still record what was asked and when.
  - `worker/jobs/macro_gold_ingest.py` forwards whichever raw representation the artifact
    chose instead of assuming bytes. The two feeds now differ deliberately: the price
    payload is JSON, the SPDR archive stays raw because it arrives as CSV or XLSX.
  - **Why the existing idempotency test was green through all of this:** the price stub
    returned byte-identical payloads, so it proved that identical bytes deduplicate —
    never that an unchanged READ does. The stub now varies its `request_id` per call, and
    a second test asserts row counts directly rather than trusting the job's own tallies,
    which reported `created=275` while reporting success.

  Existing duplicate rows are left in place; they carry identical values and the
  newest-vintage read picks correctly, so this is cleanup rather than a correction.

## [0.12.14] — 2026-08-23

### Fixed

- **A composite score dated three weeks in the future froze the Fundamentals card for 363
  names.** `as_of` is the cross-section's _latest_ knowledge date — the earliest moment
  the ranking could legitimately have been computed. When a filer's real filing date is
  still unknown, that date is estimated as `period_end + 45d`, and for a fresh quarter the
  estimate has not arrived yet. Two such names (AMAT and CSCO, `period_end` 2026-07-31)
  carried an estimate of 2026-09-14, and because `as_of` is the bucket **maximum**, their
  estimate stamped all 371 rows in the quarter — every 2026Q3 score the table holds. The
  read path orders `as_of DESC`, so nothing computed later can overtake it: the card
  serves the 2026-08-16 compute, and each correct recompute for the rest of the quarter
  carries a lower (because arrived) `as_of`, so it would land in the table and stay
  invisible until the calendar reached September 14. `_build_buckets` now withholds any
  period whose knowledge date has not arrived, which also removes the quieter half of the
  defect — an unpublished name was contributing to every other name's z-score using
  figures the market had not seen. The cutoff is a parameter defaulting to today, so a
  replay names its own as-of and tests do not read the wall clock; withheld periods are
  counted in the job's returned totals rather than dropped silently. Migration `129`
  evicts the rows already written, which is safe because scores are fully derived and
  every bucket is rebuilt from the statement panel on each run.

## [0.12.13] — 2026-08-23

### Added

- **The gold domain state — MC3 Part B's last deferred step, on the condition its own
  spec named.** Deviation 7 of the USD/gold design deferred
  `MacroDomainState(domain="gold")` because gold's inputs lived in warm-store tables that
  carry no `obs_id`, and the store refuses a state whose evidence cannot be pointed at.
  It also wrote its own overturn condition: _"an ingest that lands the gold sources as
  `macro_observations`."_ `worker/jobs/macro_gold_ingest.py` is that ingest. No migration
  was required — migration 115 has accepted `domain = 'gold'` since it was written, and so
  have 125 and 128; the schema was never the blocker, only the ingest.
  - `macro/gold_state.py` publishes **the gate** — whether the gold/real-yield
    relationship Lens 2 rests on is currently in force — reading the correlation gauge
    `cards/regime_gauge.py` already computes rather than recomputing it. The three lenses
    publish beside it as sub-states with their own confidence, and there is deliberately
    no precedence rule between them.
  - `GET /api/macro/gold`, with replay and evidence drill-down, completing
    inflation → rates → USD → gold. The router previously carried a comment explaining why
    this endpoint deliberately did not exist; that comment is now the docstring explaining
    what changed.
  - Nightly `macro_gold_ingest` at 19:30 ET (massive-0, gated
    `UW_SCAN_MACRO_GOLD_INGEST_ENABLED`, default **off**), and gold appended to the 19:40
    state chain **last** — it is the terminal node and reads all three upstreams, so
    running it earlier would record zero dependency edges every night while looking
    healthy.
  - Both preregistered gold scenarios in `tests/fixtures/macro/usd_gold_golden.json` now
    execute against the engine. They were frozen from live publishers before any of this
    code existed, and they changed the design twice: the upstream refusal had to invert
    from causal-role to series-id (gold's own anchor shares `decomposition_component` with
    two upstream series, so a role-based refusal rejects it), and the measurement window
    had to become calendar-based (over the fixture's own quarter `GLD_CLOSE` has 64 prints
    where `DFII10` has 62, so an observation-count window silently mutes the
    post-2022 contradiction on the shorter leg).

### Fixed

- **The Gold Compass lens-decomposition panel had never rendered a row.**
  `reports/gold_posture._decomposition_rows_from_lenses` read ten `*_z` attributes off the
  three lens dataclasses; nine exist nowhere in the tree and the tenth only as a database
  column, so it returned `[]` on every run since it was written. Deleted rather than
  repaired: the lenses report native units (tonnes, ounces, percent, basis points) and
  percentiles, never z-scores, and no model has ever fitted weights over them — summing
  them into one "contribution" column and sorting by magnitude would rank a reserves flow
  above a valuation percentile because tonnes are numerically larger than a probability.
  The API field and the database column are unchanged (`[]` before, `[]` after), so this
  is not a contract change. A test now fails if any lens grows a real z-score, which is
  the moment to decide deliberately whether the panel should exist.

## [0.12.12] — 2026-08-23

### Fixed

- **The scheduler discarded every write from a job that reads before it writes.**
  `worker/scheduler._repo` opened a connection and closed it in a `finally`, and closing a
  psycopg connection does not commit — it discards. That is invisible for the many
  repository methods that call `self._conn.commit()` themselves, and silently fatal for the
  ones built on `self._conn.transaction()`: that block only emits `COMMIT` when it opened
  the transaction, and every macro domain-state job loads its observations and its own prior
  answer _before_ it writes, so the connection was already mid-transaction and the write
  degraded to a savepoint that nothing ever committed. Measured on the mini before the fix:
  `macro_domain_states` at **8 rows inserted, 2 alive, 0 deleted**, with the nightly job
  logging `ok` on every run — two nights of inflation and policy-rates states computed
  correctly and thrown away. The helper is now a `with psycopg.connect(...)` block, which
  commits on the way out and still rolls back on an exception.

- **Why no test caught it, and what now would.** Every existing test drives its jobs through
  `with psycopg.connect(...)`, which commits — none of them used the production helper, so a
  green suite and a silently empty table were compatible. The regression test runs the
  inflation state job through `scheduler._repo` itself and asserts from a **new** connection;
  it fails against the old helper. A second case raises inside the block and asserts nothing
  persisted, because committing on the way out must not become committing on the way down.

## [0.12.11] — 2026-08-23

### Added

- **A USD transmission state that consumes upstream answers and refuses to guess.** The
  Fed's H.10 nominal broad dollar (`DTWEXBGS`) is the required anchor; with no vintage of
  it at `as_of` the state is `UNKNOWN`. The CPI-deflated sibling `RTWEXBGS` is reported
  beside it and is **never substituted** — the golden scenario freezes an `as_of` where
  the sibling has 59 observations and the anchor has zero, because the substitute being
  available is exactly what makes the refusal a decision rather than an absence of
  options. A nominal index moving while the real one does not is an inflation
  differential, and swapping them would report that as a dollar move. Relative policy,
  funding and positioning are USD factors too, and every one is owned upstream: USD reads
  the stored **answer** through `UpstreamState`, and passing it an upstream-owned
  observation raises. `GET /api/macro/usd` serves it with its lineage.

- **`DTWEXBGS` carries a weekly cadence for a series FRED labels daily, and that is the
  load-bearing detail.** The H.10 goes out weekly carrying the week's daily observations
  together — 52.2 vintages a year against ~250 for SOFR. A cadence of 1 would mark the
  _required_ anchor stale Monday through Thursday of an ordinary week, and an abstaining
  state is not a degraded reading, it is no reading at all. The same measurement gives
  32.7 years of headroom under FRED's 2000-vintage cap, against EFFR's 2.3.

- **Cross-domain lineage (migration 128).** `macro_domain_state_dependencies` records the
  typed edge from a state to the upstream **answers** it stood on, carrying the upstream's
  own state and confidence so the edge is traversable rather than merely present. Inside
  `inputs_hash` alone the dependency is in the identity and invisible in the record: you
  could tell a USD state changed when rates did and never ask what rates said. An upstream
  answering for an instant _after_ the downstream's `as_of` is refused as lookahead.

- **A BIS cross-check that cannot become evidence.** `sources/bis_eer.py` returns a
  dataclass with no `available_at`, no vintage and no artifact, because a BIS SDMX data
  message carries no real-time dimension: it can corroborate today's level and can never
  say what the level was believed to be on a past date. Two measured traps are tested
  against the publisher's own bytes — a bare request **succeeds** with HTTP 200 and
  `application/xml`, so a client that omits the `Accept` header hands SDMX-ML to a JSON
  parser and `raise_for_status` passes it through; and `NaN` on a non-trading day is an
  absence that must never become a zero.

### Fixed

- **Gold Compass named four of its sixteen inputs and read as a complete audit trail.**
  `reports/gold_posture.py` pinned a four-entry `inputs_used` manifest — `DFII10`,
  `GLD_CLOSE`, `T5YIFR`, `CPIAUCSL` — while the orchestrator read fourteen sources and
  passed two more to the lens functions as deliberately empty lists. The manifest was not written
  wrong; it went stale as reads were added beside it, so the reads and the manifest are
  now generated from **one** declaration (`macro/gold.py::GOLD_INPUTS`) and an entry that
  is neither read nor explained cannot be constructed. An input with no rows carries a
  reason; `fx` and `spx` are recorded as declared-and-not-read, because an empty list
  reaching a lens is indistinguishable in the output from a factor that did not move. The
  `/gold` audit footer reports how many of the declared inputs were read, with each
  omission and its reason. Every read is also bounded on the retrieval clock now
  (`as_of_max`), not just the observation period: the readers select the newest vintage
  by `as_of DESC`, so recomputing a past date used to read restatements that did not
  exist yet — the orchestrator's own test fixture was relying on exactly that.
  The first thing this surfaced was real: COMEX inventory (`exchange_inventory_daily`)
  last observed 2026-06-01 in production against a 60-day read window, so Lens 1's
  inventory leg has been silently empty — invisible under the old manifest.

- **The gold API dropped any provenance entry without an `obs_date`.** An explicit
  omission would have been discarded between the store and the client, rebuilding the
  partial manifest one layer up. `GoldInputProvenance` now carries the omission and the
  router keeps the record.

- **`compute_confidence` counted factors instead of matched requirements.**
  `len(factors) / len(required_series)` is correct only while every caller pre-filters its
  factors down to the required set — which rates does by an explicit filter and inflation
  does by iterating `REQUIRED`, so the two shipped domains made those numbers identical by
  accident. A caller passing a factor it merely _reports_ got **1/1 complete on a state
  whose one required input was absent**: full confidence in a reading built entirely from
  a substitute. Now counts the intersection; both existing domains are unchanged.

- **Supply, positioning and plumbing now publish their own sub-states, each with its own
  confidence.** The rates policy state answers what the committee did and is gated by
  three policy paths; a positioning read is gated by whether CFTC published. Sharing one
  confidence number would let either stand in for the other, so each role computes its
  own over its own required series and the `/rates` state block renders them side by side
  and labelled. `market_factors_absent` now reports **0** and — deliberately — is still
  emitted at zero: a term that disappears when healthy gives a reader nothing to notice
  when it comes back.

- **Plumbing is classified on a price, never on a quantity level, and that choice was
  forced by testing it.** The first rule combined a wide SOFR–EFFR spread with exhausted
  RRP take-up. It fails on the only funding crisis in the record: on 2019-09-17, when
  SOFR printed 5.25 against an effective rate of 2.30 — 295bp — RRP stood at 1.825bn,
  which is unremarkable for a year when the facility was structurally small. RRP ran
  ~2bn in 2019 and ~2,300bn in 2022 for reasons that have nothing to do with stress, so
  its level cannot carry a stress claim. The spread is a price and comparable across both
  regimes. `STRESSED` is set at one policy move (25bp), not at the measured sample's p99
  (15bp): the 2021–2026 sample contains no crisis, so its p99 marks the calmest kind of
  unusual, and calibrating to it would have called a 19bp day stressed while leaving no
  label for 295bp.

- **Two contradiction rules that report disagreement without resolving it.**
  `positioning_against_curve_direction` fires when a category at an extreme of its own
  distribution sits on the opposite side of the realised yield move over the same four
  weeks — a net short profits when yields rise, so a stretched short into falling yields
  is evidence pointing two ways. `plumbing_stress_without_policy_change` reports funding
  stress the committee has not responded to. Neither infers a direction and neither
  changes a state label.

- **A cost worth stating: a rates state now cites 1,923 observations.** Four years of
  weekly positioning and two years of quarterly refundings are genuinely what a percentile
  and a multi-quarter-high stand on, so the evidence rows are correct rather than
  excessive — but at one state a day that is roughly 700k lineage rows a year.

### Fixed

- **The rates positioning table has been claiming CFTC data was knowable before it was
  published.** `sources/cftc_tff.py` derived each report's release date as `report_date +
3 days`. Measured against Socrata's own `:created_at` over 205 releases, that rule is
  wrong on 36 of them (17.6%) and **always early** — not one error is conservative. The
  large ones are not holidays: they are two publication outages, the ION Markets incident
  from 2023-01-31 and the government-funding lapse from 2025-09-30, where the rule claims
  data was knowable up to **47 days** before it existed, for ten consecutive weeks each.
  A holiday calendar cannot fix that, because an outage is not on a calendar; nor can a
  fixed release time, because 15:30 ET is 19:30Z or 20:30Z depending on daylight saving
  and the observed instants split 120/69 across the two. The derivation is gone and the
  publisher's own load instant takes its place. Anything that backtested
  `rates_cftc_tff_weekly` positioned on reports that had not been published, and the error
  was largest exactly when positioning data matters most.

- **A unit-test fixture was asserting auction values the publisher never printed.**
  `tests/unit/sources/test_treasury_supply.py` claimed 912810UL0 was a 30-Year at $25bn
  auctioned 2026-05-14 — Treasury held no auction that day and that CUSIP is a 20-Year
  first sold at $16bn — and 91282CPU9 at $16bn / 5.122%, really a TIPS at $19bn / 2.169%.
  Replaced with four real rows fetched from TreasuryDirect and frozen with their as-of
  date.

- **Positioning was being given a 120-day freshness cadence for a weekly report.** Every
  market factor inherited the policy-path cadence, so a COT report four months past its
  release read as perfectly fresh — seventeen weeks inside a seventeen-week window. A
  freshness term that cannot detect a publisher going quiet is decoration. Each role now
  carries its publisher's own cadence, and supply gained the staleness gate it never had:
  a 2024 refunding is not today's supply condition.

- **The three market roles the rates engine has enumerated since MC0 now resolve to
  evidence.** `supply`, `positioning` and `plumbing` reported absent for two milestones;
  `RATES_EVIDENCE` now carries seven nominal coupon terms, the 10-year note future's
  three trader-category nets with their open-interest shares, and three funding series
  (`SOFR`, `EFFR`, `RRPONTSYD`). Each role reads over its own history window rather than
  one for the domain — a curve attribution needs a month, a supply baseline needs five
  quarterly refundings, and a positioning percentile needs the four-year sample its
  thresholds were calibrated on. One window would starve the first or drag two years of
  daily curve prints into every state's identity.

- **Reserve balances are deliberately NOT registered, and that is a finding.** FRED
  republished `WRESBAL`'s entire history on 2025-11-13 with every value multiplied by a
  thousand: period 2025-06-04 reads 3294.381 under the vintage in force until 2025-11-12
  and 3294381.0 under the one after, and the ratio is exactly 1000.0 across all 566
  multi-vintage periods. FRED today declares the units as millions, so every earlier
  vintage is billions wearing a millions label. A series contract declares one unit for
  all vintages and the observations endpoint reports no per-vintage unit, so live reads
  are fine — every vintage in a 120-day window is post-rebasing — while any replay before
  that date is wrong by a factor of a thousand, silently and plausibly. That is the exact
  case this milestone exists to make trustworthy, so the reserve-balances slice reports
  UNKNOWN rather than borrowing a neighbour. The same scan over all eleven previously
  registered FRED series found no other instance.

- **The rates engine can finally see supply and positioning.** It has enumerated
  `supply`, `positioning` and `plumbing` as its own market factors since MC0 and reported
  all three absent ever since — not because nothing publishes them, but because the tables
  they land in key on `as_of` and update on conflict, so a value read back may already have
  been overwritten. Promoting one to an immutable observation would launder a mutated
  number into the evidence store. Both are now fetched from their publishers directly and
  written as point-in-time evidence, carrying the publisher's own availability: a Treasury
  auction becomes knowable on its **announcement** date, about a week before it is sold,
  and a CFTC report becomes knowable when CFTC loaded it. The legacy tables stay read
  models for the existing `/rates` surface. Gated by
  `UW_SCAN_MACRO_MARKET_LAYER_INGEST_ENABLED`, default off; deep history via
  `scripts/backfill/macro_market_layer_backfill.py`.

- **A supply series is keyed by the term AND the type, because the term alone is not an
  identity.** A 10-Year TIPS carries `securityTerm="10-Year"` and `securityType="Note"`
  exactly like a nominal 10-year note, and is half the size — $21bn against $42bn. Keyed on
  the term, the two interleave, and the engine's multi-quarter-high rule reads the
  alternation as a supply collapse and recovery every quarter: a signal produced entirely
  by a taxonomy error. Reopenings are excluded for a related reason — a reopening adds to
  an outstanding security, so its size is a marginal add and comparing it against a new
  issue reads as a supply cut.

- **Sixteen years of CFTC history that honestly says it was loaded, not published.** Every
  report from 2006-06-13 to 2022-09-06 shares one Socrata `:created_at` — a bulk load, not
  a release. Recording that as a publication would assert that sixteen years of weekly
  reports all became knowable on the same afternoon. Those 31,458 observations carry
  `published_at = NULL` with availability at the load instant, so a 2019 replay sees
  nothing; the 9,653 rows after it each carry their own release. The distinction is
  detected from the data — one instant spanning more than one report date is a load — not
  hardcoded, and migration 119 already allows exactly one `NULL -> value` promotion if a
  real instant is ever verified.

- **The valuation band was priced against the wrong share basis, and it put a
  dozen names on the buy list that do not belong there — while refusing seven
  that do.** `valuation_anchors` builds each band from 20 quarters of
  `fundamental / shares ÷ price`, and the two legs disagreed: UW restates
  historical share counts onto today's post-split basis, while bronze stores
  closes unadjusted. So the numerator already sat in today's units and the price
  did not, and every quarter before a split yielded a number wrong by the split
  factor. BKNG's 1-for-25 set its `buy_below` at $4,702.64 against a $208.25
  spot — the name read as cheap. On 2026-08-18, 26 of 335 bands were built
  across a split inside their own window and 12 of those were showing in the buy
  zone. The error also ran the other way: a split made a name's own yield history
  look like it spanned two regimes, so the 4x width gate refused it. NVDA, which
  split 4-for-1 in 2021 and 10-for-1 in 2024, was refused for an "own 20-quarter
  valuation range spans 16.9x" that was the splits, not its valuation — it and
  AVGO, LRCX, ORLY, DECK, SMCI and BKSY all get real bands now.

  Prices now come from livewire's **silver** tier, which publishes fully
  back-adjusted daily bars, rather than being adjusted here. Silver's close is
  adjusted for splits AND dividends, so it is divided by
  `price_adjustment_factor * split_volume_factor` to undo the dividend half:
  a cash dividend genuinely lowers market cap and nothing restates a share count
  for it, so leaving it in understates every historical market cap on a payer
  and biases the whole band cheap. `ANCHOR_RULES_REV` goes to 4 so the corrected
  rows are actually written — the hashed inputs (`fundamental`, `net_debt`,
  `shares`, `history_n`) are all unchanged by this fix, so without the bump every
  correction would collide on `(ticker, as_of, engine_version, inputs_hash)` and
  `DO NOTHING` would keep the wrong band for the rest of the day.

  The file's own `WHY UNADJUSTED CLOSES` note argued the opposite for a sound
  reason resting on a premise nobody had checked; it now carries the three
  measurements that disprove it. Verified against production writing nothing:
  `docs/research/2026-08-21-lake-price-basis-split-contamination/VERDICT.md`.

- **Bronze's 2021-06-11 basis seam, and the 18 names livewire refuses to
  adjust at all.** Bronze rows before that date were back-adjusted by a legacy
  backfill and rows from it forward are raw, concatenated without reconciling
  (TSLA steps 203.37 → 609.89 that day, WMT 46.63 → 140.75). An earlier fix here
  clamped every series to that date — but it is livewire's boundary for the
  _ambiguous_ symbols only, and applying it globally cost KLAC, whose bronze
  basis is clean throughout, forty years of history. Silver carries the
  per-symbol truth: TSLA/WMT/CTAS start exactly 2021-06-11, KLAC starts 1980.

  Where livewire cannot establish a basis at all (`price_basis='unknown'` on
  bronze) it publishes no silver series — 18 of 450 universe names on
  2026-08-21, including HON, CMCSA and MSTR. Those fall back to raw bronze,
  which is provably equivalent when no split falls inside the window being
  priced, and are **refused** when one does: CXAI's 50-for-1 on 2026-08-18 had
  left `buy_below` at $0.107 against a $4.59 spot, and TRI's buyback
  consolidations put it on the buy list 24% below a band it had not earned. The
  new `unadjustable_prices` counter tracks them, and falls to zero as livewire
  resolves those symbols upstream.

  That fallback is only sound while "no split on record" means the ingest looked
  and found none, and on 2026-08-22 it did not: `corporate_actions` covered 137
  of the universe's 450 names, so 15 of those 18 — AIG, CMCSA, ECL, HON among
  them — had zero rows for the plain reason that nobody had asked, and every one
  was banded off an unverified basis. CMCSA was sitting in the buy zone on it.
  The guard now requires positive evidence that a name was ingested (any split
  or dividend row) and refuses otherwise, and the ingest itself widened to the
  full scoring universe so that evidence exists. Refusals rise from 4 to 10 on
  the 2026-08-22 store and fall back to 4 after one ingest run (verified by
  staging that run's splits _and_ dividends against production). Three names
  (CFLT, CYBR, PSTG) have no split and no dividend at massive at all, so they
  can never satisfy the rule; none of the three carries a band today, so the
  measured coverage cost is zero, but the ceiling is real — an event table
  cannot record a non-event.

  A missing silver tier is now a hard failure rather than a silent one. The
  whole directory absent is a mount or path error, never a data gap, and it was
  the one fault that would have put all 450 names back on unadjusted bronze —
  quietly reinstating the bug above. The job refuses to run instead, leaving the
  previous day's bands standing.

- **Twelve foreign filers were refused a valuation band for want of an FX series
  the lake was carrying the whole time.** Two independent faults. `lake_fx_root`
  was added after the container migration and never got a case in
  `Settings.from_env`, so it fell back to a `$HOME` path — `/root/market-warehouse/…`
  inside the container — that has never existed in production. Every lake root
  now falls back under `market_warehouse_lake_root` instead of `$HOME`, so the
  next one added is correct by default and no `.env` edit is needed.

  Underneath that, `fx_symbol` looked only for `USD<CCY>`, and the mirrors
  disagree: the mini's lake publishes `EURUSD` (1.16973 on 2026-08-21, USD per
  EUR) and no `USDEUR`, while the MacBook's publishes `USDEUR` (0.8586) and no
  `EURUSD`. Both are livewire artifacts and neither is wrong. `load_fx` now reads
  whichever orientation exists and inverts `<CCY>USD` on read, so `convert`'s
  single convention holds downstream — rather than keeping a table of which
  currencies are quoted which way in sync with two mirrors. Verified against real
  filings: ASML Q2-2026 €9.33B → $10.87B, TSM NT$1,270.38B → $40.45B.

  `no_fx` falls 12 → 1 and ASML, ASX, BABA, CCEP, CCJ, NOK, SONY, SPOT, TSM, UMC
  and WIT get bands. NVO stays refused and should: it reports DKK and the lake
  carries no DKK series in either orientation. That is an upstream ask, not
  something to paper over with an unconverted band.

- **The split store covered 137 of the fundamental universe's 450 names.**
  `corporate_actions_refresh` ingested the watchlist and the VRP panel only, so
  the guard above had no evidence for most of the names that need it. The job now
  covers the fundamental universe as well, at 17:35 ET — 45 minutes before
  `fundamental_refresh`, so the guard is armed on the first day after a deploy.

## [0.12.10] — 2026-08-20

### Added

- **A dozen dealer surveys instead of one, and both policy-path charts now show
  movement.** The NY Fed publishes every Survey of Market Expectations it still hosts
  on one page and the nightly job took `[-1]`, so the desk held a single release and
  could not show how dealer expectations had CHANGED. All twelve (2025-01 → 2026-06)
  are backfilled through the real ingest job, and the dealer path plots the latest
  survey over the two before it while the SEP dot plot carries the previous release's
  median as a dashed line. Both label their series by real release date, and earlier
  releases stay separate dated releases — never merged into the current one, the same
  rule that keeps the four publishers apart. The survey runs on the FOMC cycle (~8x a
  year), so the comparison offered is "previous survey", never "one week ago": there
  are months with no survey at all.

- **The dealer chart is plotted against meeting DATE, not survey row order.** Each
  survey asks about the meetings ahead of itself, so a March release and a June release
  do not share a horizon; against row index the overlay would have drawn March's first
  meeting on top of June's and called the difference a revision.

- **The SEP and the dealer survey are plotted, not listed.** Both releases publish a
  distribution and both were rendered as a column of medians, which is the one view
  that hides what each release is for. The committee's projections are now the dot plot
  the FOMC actually publishes — every participant's dot placed on an axis, so a median
  of 3.60% no longer reads identically whether the dots sit on it or span 2.875 to
  4.375 — and the dealer survey is a path with its own interquartile band, which shows
  the quartiles opening months before the median moves. Each is a separate block on its
  own axes: overlaying them would draw a comparison this desk refuses to make
  numerically. Dots stay anonymous in the plot as in the release, including in every
  per-dot tooltip; a lane with no readable release prints the sentence saying so rather
  than an empty axis, because a bare axis reads as a flat path and that is a claim.

- **Point-in-time inflation and rates states — what regime we are in, which way it
  is moving, how fast, and how much of that we actually know.** Two pure engines over
  vintage-stamped evidence, replacing a score that could look confident while standing
  on one populated input. `state` and `direction` are separate fields: "above target
  and falling" and "above target and rising" are the same level and opposite
  situations. Confidence is a function of coverage, freshness, quality, revisions and
  contradictions — never of signal magnitude, so a reading does not gain authority by
  getting extreme.
- **The inflation state is scored on core PCE, not CPI.** The FOMC's 2 percent
  objective is stated on PCE and core CPI runs structurally above it, so thresholding
  CPI against 2 percent mislabels the regime by roughly one policy move, permanently
  and in one direction. CPI lands about two weeks earlier and enters as a corroborator
  and a contradiction input.
- **ALFRED-backed realized-inflation adapter with true vintage replay.** A replay at
  2024-06-01 returns January 2024 CPI as 309.685 — the value published then — not the
  309.698 it reads today. Built on FRED rather than BLS/BEA for measured reasons: BLS
  returns HTTP 403 to this desk on every host, BEA answers a missing credential with
  HTTP 200 and zero bytes, and neither publishes vintages at all
  (`docs/research/2026-08-18-mc2-inflation-source-probe/`).
- **Treasury supply, positioning and plumbing are separate factors with their own
  freshness**, so a blended technicals score can no longer hide which one is stale.
- **Domain states are persisted with the exact observations they stood on**
  (migration `125`, `macro_domain_states` + `macro_domain_state_evidence`). Evidence
  rows carry real `obs_id` foreign keys, and the database refuses any evidence that
  became available after the state's `as_of` — lookahead is rejected below the
  application, not merely avoided by it. A state is identified by its method
  (`domain`, `as_of`, `engine_version`, `inputs_hash`, where the hash covers the
  thresholds as well as the data), so recomputing an unchanged state is a no-op and
  the same inputs producing a different answer raises instead of appending a second
  equally-authoritative row. Stored answers are immutable: an engine later found
  wrong can be quarantined out of service, never edited.
- **The states are computed by a worker and served for replay, never recomputed at
  read time.** `GET /api/macro/inflation` and `/api/macro/rates` return the stored
  answer that was in force at the requested instant, with every observation it stood
  on; an instant nobody computed a state for is a 404 rather than a state assembled on
  the spot. Recomputing a 2024 replay with today's engine would report what we _would_
  have said, and an audit trail you can regenerate to taste is not an audit trail. The
  reply carries `requested_as_of` and `as_of` separately, so a day-old answer cannot
  present itself as a live one.
- **Vintage-bearing series ingest, separate from state computation** (`fred_series`
  job, `macro_series_ingest.py`). Two things about it are load-bearing. The request
  spans ALFRED's unbounded vintage window: asking with `realtime_start = realtime_end
= today` makes FRED clamp every returned window to the query and report today as the
  vintage of the 1947 CPI — an artifact of asking, not a fact about publishing, and it
  destroys the one field replay is built on. And a series observation is identified by
  its vintage — `(source, series_id, period_end, available_at)` — not by the payload
  carrying it, because one request returns the whole history: under an identity that
  includes `artifact_id`, a single new monthly print would re-write every unchanged
  month beside it.
- **Migration `126` splits the availability bound in two.** An artifact that _is_ a
  release (an FOMC statement) still cannot carry an observation older than itself. An
  artifact that _reports_ a publication history (an ALFRED response) may: its whole
  product is telling us today that January 2024 CPI was first published on 2024-02-13,
  and the single rule would have stamped the fetch date on every historical vintage.
  The forward direction is untouched — a vintage may still never postdate the fetch
  reporting it, which is what a lookahead would need.
- **A rates state cites the policy release its answer turned on.** `state` is read off
  the FOMC's own target range, but `evidence_refs` carried only market series — so a
  rates state with no DGS10 was unpersistable, and one with DGS10 named everything
  except the release that decided it.
- **The `/api/rates/snapshot` state block (flag `UW_SCAN_RATES_SNAPSHOT_STATE_BLOCK_ENABLED`,
  default off).** Compact by design — state, direction, confidence with its terms,
  contradictions — plus `detail_path` to the full evidence, so the short block can
  never become the only view of the answer. Read fresh per request rather than baked
  into the stored snapshot: the two are computed by different jobs on different clocks,
  and a state copied into last night's payload would keep asserting itself after the
  state had been quarantined. Absent means the flag is off or nothing was computed —
  never that the desk is neutral.
- **`/rates` leads with the state, and the four policy paths get four lanes.** State,
  direction, velocity, the confidence terms and any contradictions come first; the
  legacy rule composite and its BUY/SELL/NEUTRAL stances sit below it behind an
  explicit "experimental legacy" label for as long as dual-read runs. The paths —
  FOMC actual, SEP projection, dealer survey, market-implied — each render in their
  own lane with their own publisher and release date and are **never averaged**: a
  blended path is a rate no committee voted on, no dealer forecast and no market
  traded. SEP dots render as anonymous counts, never attached to a named participant.
- **A path whose source is not a publisher is refused at the display layer.** `mock`,
  `static` and `demo` source kinds are representable in the contract, so the lane
  withholds their numbers and says why rather than trusting that upstream never emits
  one. A market-implied lane additionally carries its third-party-shadow label and its
  delay status.

### Changed

- **The rates header stopped shouting.** It had grown a bespoke 26px/700 lockup with
  a 0.18em wide-tracked subtitle and a bold 13px nav, so `/rates` announced itself
  about twice as loudly as every other page in the sidebar. It now follows the house
  pattern (`.regime-page-header`): mono, 18px, 600, uppercase, with an 11px mono
  subtitle and a light mono nav.

- **A charted lane shows its headline, not every horizon.** The SEP and dealer lanes
  listed all of their horizons — sixteen rows for the dealer survey — directly above
  the chart that draws exactly those numbers on an axis. The lane keeps what a lane is
  for (which publisher, which release, is it healthy) plus the near-term number, and
  links to the plot for the rest.

- **A lane that legitimately trails the last FOMC decision now says so.** Seeing
  "released 2026-06-17" on the SEP lane when the committee last met on 2026-07-29
  reads as a stalled feed; it is not, because the FOMC publishes projections at four
  of its eight annual meetings and the dealer survey runs per survey round. The note
  is derived from the two release dates already on the page — not a hardcoded meeting
  calendar — and disappears the moment the lane catches up.

- **The rates desk is grouped, not listed.** Fifteen sections at one visual weight
  behind a flat fifteen-item nav is a list, not a hierarchy: the verdict, the
  publishers feeding it, the market's own pricing and the experimental legacy
  scorecard all shouted equally. They now sit under five named tiers — the answer, who
  says what, what the market prices, mechanics, provenance and legacy — and the nav is
  grouped to match and wraps rather than scrolling behind a hidden scrollbar. The two
  policy-path plots moved inside the policy-paths section, because they ARE two of
  those four lanes; still two blocks with two sets of axes.

- **Two headers stopped repeating themselves.** The state block printed "Policy /
  rates state · rates/1" one line under a section heading reading "Policy / Rates
  State", and the policy-paths eyebrow was a truncation of the sentence directly below
  it. The engine version — the only part that was not a repeat — moved to the meta row.

- **Confidence explains itself in a line instead of a sub-card.** The card listed all
  six terms at equal weight, and most are neutral most of the time: three multiplicands
  at 1.00 and two penalties at 0.00 is "nothing reduced it", spelled as five rows a
  reader had to decode. It now names only the terms that actually dragged, says so
  plainly when none did, and keeps informational terms — which are not in the product
  at all — visually apart, so `market_factors_absent` at 3 no longer reads as a term
  that tripled the number it only annotates.

- **The rates duration stance can no longer be confident on incomplete evidence.**
  `RatesScorecard` gains `coverage` and `duration_stance` gains `UNKNOWN`. Three of
  six scorecard groups are hard-coded as missing until the Phase 2 feeds land, so the
  desk has been printing a `BUY`/`SELL`/`NEUTRAL` built on **45%** of its own weight;
  it now prints `UNKNOWN` with the coverage stated. `_duration_stance(None)` returned
  `NEUTRAL`, rendering absence as a considered view — it returns `UNKNOWN` now, and the
  synthesis sentence beneath the card stops narrating a lean the stance has refused.
- **Curve slope is no longer described as a term premium.** A slope is the difference
  between two traded yields; a term premium is a model output. The only term-premium
  figure on the rates desk is the Cleveland Fed's, in the decomposition section with
  its own vintage.
- **The decomposition reconciliation tolerance is calibrated, not picked: 25bp → 85bp.**
  Measured over 332 months, the Cleveland modelled 10y and the traded `DGS10` normally
  differ by 41bp (63bp since 2016), so 25bp would have fired on **66.9%** of months and
  carried no information. 85bp is the post-2016 p90 and fires on 11 of 332 months, all
  of them in the 2022 repricing. The two other candidate decompositions cannot fail at
  all — FRED derives `T10YIE` from `DGS10 - DFII10`, and the Cleveland model's expected
  short real rate is defined as its real yield minus its term premium, measured at
  exactly 0.0bp residual across all 332 months
  (`docs/research/2026-08-18-mc2-decomposition-residual/`).

### Fixed

- **Four rates clients inherited ambient proxy config, freezing the entire lane on any
  macOS host.** `FredProvider` and the Cleveland Fed, CFTC and Treasury clients all
  built `httpx.Client()` without `trust_env=False`, unlike every macro source added
  alongside them (`fomc_statement`, `fed_sep_provider`, `fomc_calendar`, `nyfed_sme`
  all pass it). `trust_env` falls through to `urllib.request.getproxies()`, which on
  macOS reads the system network pane — so unsetting `HTTPS_PROXY` does not disable it
  — and the TLS handshake to `api.stlouisfed.org` died with
  `SSL: UNEXPECTED_EOF_WHILE_READING`. The job then correctly refused to publish a
  snapshot without a Treasury curve, so every table behind `/rates` stopped advancing
  at once: observations, auctions and CFTC positioning last moved 2026-06-09 to 06-15
  while the header honestly reported a two-month-old `as_of` that nothing flagged.

  **The deployed stack was never affected and its data has no gap** — the mini's
  workers run in Linux containers, where `getproxies()` reads environment variables
  only and the container has none, so `rates_observations` carries all 31 series for
  every month from May through August. What the bug hit was every _native_ macOS run:
  the whole dev loop, and any out-of-band `uv run` script on the mini itself, where
  `getproxies()` does return the host's proxy. Measured on the local database, the run
  goes from 11 required series failing to `failed_series=[]`, 4712 observations, and
  the snapshot advances 2026-06-12 → 2026-08-18.

- **A lane reported "0/0 releases parsed" over twelve parsed surveys.** The
  per-release catalog models FOMC statements and SEPs only — the dealer survey and the
  market shadow carry `release_type=None` deliberately — so their counters are
  structurally zero. The ratio is now printed only where the catalog models it; a
  number that does not apply is not a neutral one, it reads as a broken feed.

- **Six of twelve dealer surveys were unreadable, and neither reason was a broken
  publisher.** The XLSX parser demanded probability distributions sum to 99–101, but
  the NY Fed publishes each bucket already rounded, so a correct 10-bucket
  distribution can be up to 5 off by arithmetic alone; measured across all twelve
  surveys the totals run 98–102 and the ±1 band was rejecting real data by
  construction. The tolerance is now derived from the bucket count — the tightest
  bound that cannot reject a correctly-rounded release — and a dropped bucket, the
  parse error the guard exists to catch, still moves a 10-bucket total by ~10. The
  parser also required the workbook's release date to fall in the month its filename
  names; two of twelve publish in the PRIOR month (may-2025 released 2025-04-23,
  dec-2025 released 2025-11-25), so equality rejected releases for following the
  publisher's own calendar. Both failures named the probability sub-table while what
  they actually cost was the policy path.

- **"Latest observation" meant "most recently downloaded".** `fetch_latest_macro_-
observation_as_of` ordered by `available_at` before `period_end`, which is a fact
  about our fetch schedule rather than the publisher's: backfilling an archive out of
  order made the last file downloaded the current release — the April 2026 dealer
  survey outranked June's — and a revision to a two-year-old period would outrank this
  month's reading. Period first, vintage second; `available_at DESC` still picks the
  newest vintage OF that period, which is the part that must stay point-in-time.

- **A policy path could not say which release it was.** `release_date` is now carried
  on the path itself. `published_at` is null for publishers that state a date rather
  than an instant (the dealer survey does), so the UI fell through to `available_at` —
  our fetch time — and labelled all twelve backfilled surveys with the day of the
  backfill.

- **Confidence terms lost their kind on the way to storage.** The persistence layer
  hand-listed the fields it wrote, so a term's `kind` was dropped on write and never
  read back. A value alone cannot say whether it drags — 1.00 is neutral for a
  multiplicand and total for a penalty — which is why the desk reported "reduced by
  revision penalty ×0.00" on a state nothing had reduced.

- **The three rates charts each magnified their own labels by a different factor.**
  They are `viewBox`-sized SVGs stretched to `width: 100%`, so the viewBox is the type
  scale and everything inside it scales, text included. The two policy paths sat full
  width at 780×400 and the curve in a ~760px cell at 760×320, so an 11px stylesheet
  rule arrived at ~17px on one chart and ~11px on another, and no container width could
  line them up. Each chart now uses a frame sized to the container it is actually
  rendered into, giving all three a scale near 1 and one shared type size. A
  `min-height: 420px` floor on top of a 1.95 aspect was also stretching the SVG box
  past its own ratio, and the empty band above the dot plot was `preserveAspectRatio`
  centring the drawing inside it — not padding.

- **Every daily FRED series had been silently failing to ingest, taking the rates
  domain's whole market layer with it.** The ingest asked ALFRED for the unbounded
  vintage window on the sound principle that a narrower one gets clamped onto the
  returned rows and destroys each value's true first-publication day. That is right for
  a monthly series and impossible for a daily one: FRED refuses any JSON request
  spanning more than 2000 vintage dates, and a daily series mints one on every
  publication day, so `DGS10`, `DFII10` and `T10YIE` returned HTTP 400 on every run
  while the eight monthly series succeeded — a per-series failure that read as a
  degraded batch rather than as a dead feed. Daily series now request a bounded window
  whose observations start on the same day its vintages do, which is what makes the
  bound safe: an observation cannot be published before the day it describes, so
  nothing returned has a vintage outside the window and nothing is clamped. Verified
  against the live API — the 2021-01-04 ten-year is stamped published 2021-01-05, its
  real T+1 lag. `policy_rates` now resolves its curve and decomposition factors instead
  of reporting them permanently absent. The bound is a dated asset, not a constant: the
  2000-vintage cap is on window _width_, so it buys about eight years, and
  `test_daily_vintage_start_has_not_expired` turns red a year before FRED does.

- **The rates scorecard could manufacture a confident verdict out of entirely missing
  data.** The web component recomputed the composite itself, renormalising over
  surviving group weight; with every group missing the denominator was zero, the
  fallback was `0`, and `0` rendered as "NEUTRAL duration" — a stance on rates
  assembled from no evidence at all. The client-side recompute is gone: the server
  already decides both the composite and whether coverage permits a stance, and the
  card now prints `n/a` and "No duration stance is taken" when it does not. An absent
  scorecard likewise defaults to `UNKNOWN` rather than `NEUTRAL`, because the absence
  of a view is not a neutral view.

- **Vintage replay lost a full day at every changeover.** FRED's `realtime_end` is the
  last day a value _was_ current, inclusive; treating it as exclusive erased each
  vintage for its final day, so a replay landing on 2025-02-11 returned no CPI at all.

## [0.12.9] — 2026-08-20

### Added

- **Vendor sector fill for `company_type` routing** (`company_sector`, migration
  123; job `company_sector_refresh`, 04:40 ET **daily**, uw-0, gated
  `UW_SCAN_COMPANY_SECTOR_REFRESH_ENABLED` default **on**). Of the 450 universe
  names, 185 carry an argon chain sector and 4 more are reachable through
  `research_universe`; **265 carry none** — including AXP, COF and FLG, three of
  the financials above, so no chain rule can reach them. One UW call per ticker,
  once per ticker — the whole universe on the first run, not only the sectorless
  names, because the chain map is prefix-matched and a name carrying a sector it
  has no rule for (`Consumer`, `Healthcare`) still falls through to the vendor
  pass. A vendor reply with no sector is stored as NULL so it is never re-asked.
  Daily rather than monthly like its uw-0 siblings, because this fills a cache
  instead of accruing a series: it asks only names with no row, so the first run
  costs one call per universe ticker and **every run after it costs zero**. The
  cadence therefore buys the table being populated the morning after deploy
  rather than up to 31 days later, a newly-admitted name being routed the next
  night, and a provider failure retrying tomorrow instead of next month.
  Deliberately NOT fetched inside `fundamental_refresh`, whose documented
  property is that the whole nightly chain costs zero provider spend.
  The vendor vocabulary gets its **own** map: it collides with argon's chain
  taxonomy on `Energy`, which means power generation in one (routing to
  `power_infra`/EV-EBITDA) and oil and gas in the other.

- **`valuation_anchors` rejects a methodless row that carries a price**
  (`valuation_anchors_methodless_is_refusal`, migration 124). Making `method`
  nullable opened a state nothing else checked: `method` NULL with a real
  `buy_below` clears the `buy_below IS NOT NULL` filter in `GET
/api/scanner/value`, reaches a non-nullable model field, and fails response
  validation — 500-ing the endpoint for **every** name in the list, not just the
  malformed one. In the schema rather than in `build_anchors`, on the same
  argument migration 118 gives for `valuation_anchors_band_ascends`: the builder
  is one writer among the backfills still to come.

- **Scanner gains a `Value` sub-tab — every name currently sitting at or below
  its own `buy_below` level.** `valuation_anchors` had exactly one read path
  (`latest_for_ticker`), so the one fundamental signal in the stack that
  measured — `sales_to_ev` against a name's OWN history, market-neutral 2q IC
  +0.0744 (t 5.77) — could only be seen by a reader who already suspected the
  name. On 2026-08-17, 98 of 336 banded names were inside their own buy zone and
  no screen in the product showed them. `GET /api/scanner/value` reads the warm
  store only: zero UW calls, zero IB calls.
  **The list is unranked by construction and says so on screen.** Ranking names
  against each other on value measured _inverted_ in this universe
  (`book_to_price` 2q IC -0.0365, t -2.32), so ordering by cheapness would point
  at the half of the panel that then underperforms. Rows are ordered
  newly-entered first, then alphabetically, and the endpoint takes no `sort`
  parameter. `entered` is three-state: a name with no prior band inside the
  30-day lookback reads `null` (unknown), never `true` — on 2026-08-17 that was
  29 names, all of them present because the panel widened from 256 to 414 three
  days earlier rather than because a price moved.

### Fixed

- **Deposit-funded financials were handed an arbitrary valuation band instead of
  an honest refusal.** `company_type` routing had no rule for banks, so all 11
  financials in the panel fell through to the pooled-universe default
  (`sales_to_ev`). Every yield there is denominated in enterprise value, and
  `EV = market cap + net debt` treats net debt as a claim on operating assets —
  for a bank, broker or lender the funding IS the business, and the vendor `debt`
  field does not carry deposits at all. The result was not a wrong number but an
  arbitrary one: measured 2026-08-17, **AXP, BLK, COF, MS and SOFI were rendering
  a `medium`-confidence band** (AXP "buy below 268.92") while **BAC, GS, JPM,
  WFC, HOOD and FLG refused** — the same business model reaching both outcomes
  depending on which side of a numeric guard it landed on. `net_debt/market_cap`
  over those 11 ran -0.07 (COF) to 1.73 (GS) against a non-financial
  distribution of p50 0.05 / max 21.61, so no threshold could have separated
  them: one catching GS/BAC/WFC/JPM also catches EIX, EXC, AES, BXP and ARE,
  whose EV yields are legitimate. They now route to a `financials` type that has
  no yield **by design** and persists a refusal saying so. Method and
  measurement: `docs/research/2026-08-19-valuation-refusal-anatomy/`.
- **A refusal is now persisted rather than the ticker being skipped.** An
  unrouted ticker wrote no row, and the card's no-row branch reads "it has no
  `company_type`, so no valuation method is routed to it — a gap in our
  coverage, not a judgement about the company". For a bank every clause of that
  is false. `valuation_anchors.method` becomes nullable (migration 124) to carry
  the state migration 118 could not express: refused because NO method applies,
  rather than refused under one. A sentinel string was rejected — it would read
  like a method in `METHOD_LABEL` lookups and in the card header.
- **PYPL keeps its band, through a market-cap method rather than an exemption.**
  Its chain sector is `Fintech` and its vendor sector `Financial Services`, so
  both routing passes independently sent it to the refusal — correctly, about its
  balance sheet: PayPal holds custodial customer balances and runs a BNPL credit
  book. But every method that breaks for a financial is EV-denominated, and
  `fcf_yield` divides by market cap and never reads `net_debt`, so the
  contamination cannot reach that band at all. A one-entry `TICKER_TO_TYPE`
  override, checked ahead of both sector passes, routes it to `platform_scale`.
  Measured on the mini against the deployed engine: **0 of the trailing 20
  quarters carry non-positive TTM free cash flow**, and the band lands at
  `confidence: high` with no caveats (buy below 79.40, spot 60.43) against
  `medium` plus a "no sector on file" caveat under the pooled default it had.
  The override writes `seeded`, so a DB-level `manual` assignment still overrules
  it. A test pins that every override routes to a market-cap method — an entry
  pointing at an EV-denominated type would look deliberate while its entire
  justification had evaporated.
- **`valuation_anchors.as_of` is the SPOT date, not the compute date** — two
  comments (`worker/jobs/fundamental_refresh.py`, `worker/scheduler.py`) said
  otherwise and contradicted the authoritative docstring in
  `worker/jobs/fundamental_anchors.py`. The mislabel already cost one debugging
  session that read a healthy job's date spread as a broken feed: the lake is an
  EOD store landing a session near midnight New York, so a healthy 18:20 ET
  Monday run correctly writes `as_of` = Friday, and `max(as_of) >= today` is
  unsatisfiable by construction.

### Verified

- **The universe widening delivered +109 usable valuation bands (227 → 336,
  +48%)** between `as_of` 2026-08-14 and 2026-08-17, against the +132 upper
  bound the plan projected. Counted by rows rather than by usable bands the same
  widening reads +62% (256 → 414); a REFUSED band is a row with every level
  null, so a coverage number has to name which it counts. Reproduce with
  `scripts/research/valuation_band_coverage_check.py`, which calls the same
  repository methods the endpoint serves from.
- **`spot_percentile` moves between sessions** — 78 of 226 paired names (34.5%)
  changed across those two dates, largest move 0.15. The rest are quantised, not
  frozen: the percentile is a rank over `history_quarters` observations, so a
  20-quarter name can only step by 0.05. BAX read 0.80 on both dates while its
  spot went 26.73 → 25.91 and crossed its own `buy_below` of 26.54 — which is
  why the new tab keys membership on the band and not on the percentile.

## [0.12.8] — 2026-08-19

### Fixed

- **A UW budget day that closed above the account guard silently disabled the
  entire next day.** UW's `official_daily_count` resets a beat _after_ 00:00 UTC,
  so the first requests of a new budget day still carry the previous day's tail —
  on 2026-08-18 twelve rows recorded 110204..110214 before the counter dropped to
  1 at `00:00:04.227Z`. `read_snapshot` took `MAX(official_daily_count)` over the
  UTC day, which pinned 110214 for the next 24 hours, and `may_spend` halts
  **every** pool once the account counter reaches `total_guard` (105000). The
  result was a full-day outage that looked like ordinary budget pressure:
  `full_scan` made **zero** UW calls all of 08-18, `regime_gex_scan` logged
  "research UW budget exhausted" from open to close, and `/api/health` reported
  `ok: false` with "16 expected full scans missed". It also self-obscured — the
  starved day then closed far below the guard, so the following day recovered on
  its own and the fault read as intermittent rather than as a stuck gate. The
  account counter is now the **latest** reading rather than the day's maximum:
  it is monotone within a budget day, so the newest row is the only maximum that
  means anything, and it cannot inherit the carry-over. A stale-low read costs at
  most one extra call before the next snapshot, where the old behaviour cost a
  trading day.

## [0.12.7] — 2026-08-19

### Fixed

- **The SPX density cone now fills its own outage holes instead of losing the
  session forever.** The nightly job only ever anchors the freshest bar and
  self-gates on `latest_as_of() == anchor`, so any session whose 03:30 run never
  fired became unreachable the moment a later cone landed — there was no path
  back to it. Two ways in, both hit at once over 2026-08-11..14: the stack was
  down, and the job's `tue-sat` cron puts the only chance to issue Friday's
  anchor on a Saturday. `2026-08-14` was silently absent while `08-13` and
  `08-17` were both present, and the chart read "1 session behind the tape".
  `spx_density_forecast` now carries a `spx_density_reconstruct` healer adapter
  (zero provider cost, same shape as the CRI/VCG/canary recoverers), so the
  nightly gap healer fills these holes with the rest — one gap mechanism, one
  report, and a window that spans the whole audit range instead of a bespoke
  lookback. The registry entry moves from `research_artifact`/no-adapter to
  `freshness_only`/`run_once_lookback`: healing the gap was always legitimate,
  it is _relabelling a forward-issued row_ that is not. Bounded so it stays a
  gap-filler rather than a seeder — the freshest bar belongs to the issue pass
  prospectively, and nothing older than the earliest cone on record is touched,
  since an unseeded log is `scripts/backfill/spx_density_backfill.py`'s job. The
  `select_sessions` integrity guard now lives with the cone and is shared by
  both callers, so a prospective row can never be relabelled `reconstructed`
  (which would move an out-of-sample cone into the in-sample tally and inflate
  the only honest hit-rate number on the page).

### Changed

- **The gap healer now runs Saturday nights too, and spends far harder on the
  nights that cost nothing.** The UW budget day runs 20:00 ET → 20:00 ET and the
  healer fires _at_ 20:00, so a run bills the day that **follows** it. Friday's
  and Saturday's runs therefore bill Saturday and Sunday — no session, so the
  live pool needs nothing. The cron extends from `0 20 * * 0-4` (Mon–Fri) to
  `0 20 * * 0-5` (Mon–Sat), and those two runs take a separate
  `DATA_GAP_HEALER_MAX_UW_CALLS_WEEKEND` (default 90000) instead of the weekday
  cap. Sunday stays deliberately unscheduled: that run would bill **Monday**, a
  full trading day, and the intuitive "Saturday and Sunday are the weekend"
  reading would hand it a 90k head start against a 105k account guard. Measured
  on UW's own counter over 2026-08: weekday burn 64k–82k, weekends ~1k.

## [0.12.6] — 2026-08-18

### Added

- **Revenue concentration on the Fundamentals tab — where a company's revenue
  actually comes from, by reportable segment and by geography.** NVDA reads 91.3%
  Compute & Networking and 78.1% United States; the share, the member name and
  the multi-year trend all come from the filer's own XBRL disaggregation. The
  block is **descriptive and says so on screen**: no rank, no percentile against
  other names, no score, and no contribution to the composite. Measured over 401
  tickers the top share moves a median 1.20pp per quarter against basis
  contamination of median 2.5pp and p90 17.5pp — the level survives that noise
  and is near-static, which makes it a factor loading rather than alpha. The
  spec's 0.10 composite weight for `concentration_risk` is withdrawn, and its
  `✅ 24/25` coverage claim corrected to the measured 184/401 by segment and
  128/401 by geography — the earlier figure counted tickers for which the
  endpoint returned rows, which is presence, not computability.
- **Member names render exactly as filed** — `country:US`, `nvda:ChinaIncludingHongKongMember`.
  Mapping those to flags or country names would mean inventing a taxonomy the
  filer did not use. An absent family renders `na`, never 0: a zero share reads
  as "no concentration risk", which is a claim about the company rather than
  about our coverage.
- **Annual figures are detected and excluded from the trend, and named rather
  than hidden.** Filers mix an annual total into a quarterly breakdown series,
  and an undetected one moves the share by several times its own quarterly step.
  Detection compares a period against its four nearest neighbours rather than
  against the ticker's lifetime median — over NVDA's 25-period history revenue
  grows 26×, so a recent _quarterly_ total clears 2.5× a lifetime median on
  growth alone. On the frozen fixtures the local rule flags 7 of 7 annual periods
  with no false positives, against 3 of 6 with 3 false positives for the global
  one, and the periods it drops land exactly on each filer's fiscal year-end.
- **New monthly capture job** `fundamental_concentration_capture` (04:10 ET on
  the 3rd, uw-0, `UW_SCAN_FUNDAMENTAL_CONCENTRATION_CAPTURE_ENABLED`, default on)
  writing `revenue_breakdown_obs` (migration 122). Raw rows are stored, never the
  derived share: the derivation rules are new and one has already been corrected
  once against real data, so re-deriving from stored rows must stay possible
  while re-fetching a rolled-off quarter may not be. Identity is content-hash,
  matching migration 114 — an unchanged recapture bumps `last_seen_at` and writes
  no fact, a restatement lands beside its predecessor. First run: 63,567 rows
  over 400 names spanning 2019-09-30 to 2026-07-05.

### Fixed

- **A refused valuation band no longer reports itself as having no data.**
  `_no_anchor` hardcoded `history_quarters: 0`, so NVDA's card read `0q` beside a
  refusal caused by twenty quarters of FCF yield spanning 17x — the data is there
  and its spread _is_ the finding, but the header sent readers hunting a data gap
  that does not exist. A refusal now carries the window it was taken on, and
  stays 0 only for the three gates that fire before any history is read (unknown
  company type, suppressed or non-positive numerator). `ANCHOR_RULES_REV` goes
  2 → 3 with it: no threshold moved, but what a refusal row _says_ did, and the
  identity key is `ON CONFLICT DO NOTHING`.
- **The refusal reason leads the panel instead of sitting under an explainer for
  a band that was never drawn.** The header paragraph teaches how to read five
  levels and a spot marker; on a refusal none of them are on screen, and it
  pushed the one sentence that answers "where is the band?" below three lines of
  prose. It is now omitted on a refusal.
- **A marginal width refusal no longer contradicts itself.** AVGO spans 4.04x
  against a 4.0x limit and `:.0f` rendered "spans 4x". Precision now follows the
  number — the coarsest that still reads above the limit — and the message names
  the window it actually measured rather than interpolating `WINDOW_QUARTERS`
  regardless.
- **"too unstable to anchor a price to" is withdrawn from the width refusal**,
  because the gate never measured instability. A band spans 17x either because
  the yield swings — genuinely unsettled — or because it walks one way and stays
  there, which is a window straddling two valuation regimes and the _opposite_ of
  unstable. The refusal now reports the measured shape: `valuation.yield_drift`,
  the rank correlation of a name's own yield against time over the band's own
  window. Of 13 names refused on width, 7 are one-way walks (GE −0.96, AVGO
  −0.90, LRCX −0.85, MSTR −0.83 as the multiple expanded; DIS +0.81, NVDA +0.68,
  NFLX +0.66 as the fundamental outgrew the price) and only RIOT, APLD and ACRE
  swing. **The 4x threshold is unchanged** — the same probe shows shape does not
  separate wide bands from narrow ones as a population (monotone share 38% vs
  36%, Mann-Whitney on rho p=0.16), so it licenses a better sentence, not a
  looser gate. Probe: `scripts/research/valuation_band_width_anatomy.py`.
- **Full-watchlist survey behind all four** (`docs/research/2026-08-18-valuation-band-refusal/`,
  reproduce with `scripts/research/valuation_band_survey.py`): of 145 operating
  companies on the watchlist, 54 render a band, 17 are scored and refused, and
  **74 have no statements ingested at all** — the dominant gap is coverage, not
  the band. Those 74 are pending rather than broken: the universe widening
  shipped in v0.12.5 and `fundamental_ingest` is monthly on the 2nd, so it does
  not execute until 2026-09-02 unless the seed and backfill are run by hand.
  AMZN's refusal is verified true — TTM operating cashflow 161.4B against 173.0B
  of capex at 2026-06-30, free cash flow of −11.6B.

- **`valuation_anchors.as_of` is the spot date, not the compute date**, and the
  docstring that said otherwise is corrected. The job is healthy — 2 of 2
  scheduled runs since the v0.12.0 deploy wrote rows, the last at its exact 18:20
  ET slot — but a health check of the form `max(as_of) >= today` is unsatisfiable
  by construction: `as_of` is the last bar in the ticker's price series, and the
  lake lands a session's close around midnight New York, hours after the run.
  Check `max(computed_at)` for liveness and compare `max(as_of)` against the
  lake's own last close for correctness.

## [0.12.5] — 2026-08-18

### Added

- **The fundamental panel now widens to every name this desk researches, and it
  stays fresh on its own.** Two gaps closed together. The universe seeder gained
  a third source — industry-chain membership — taking production's `ranked` tier
  from 257 to 450 names. Keying admission on "already has statements" instead,
  as originally planned, is circular: `fundamental_ingest` draws its ticker list
  from the universe, so a name outside it never gets statements and could never
  qualify. That rule reads correct on a laptop, where a research backfill run
  during the mini outage left 144 extra statement-bearing names, and is a silent
  no-op in production, where it admits zero. Admission is strictly additive —
  a name already carrying validation backing is excluded from the new source
  rather than re-seeded, since `seed_universe` upserts `reason` and would
  otherwise downgrade its provenance. The three provenances stay separable in
  that column.
- **`fundamental_ingest` is now scheduled** (monthly, 03:40 ET on the 2nd, uw-0,
  `UW_SCAN_FUNDAMENTAL_INGEST_ENABLED`, cron overridable via
  `UW_SCAN_FUNDAMENTAL_INGEST_CRON`). The nightly `fundamental_refresh`
  deliberately does not pull filings, so until now the entire lane recomputed
  every night over a panel that stopped advancing the moment nobody ran the
  backfill script by hand — healthy-looking and stale. Monthly rather than daily
  because statements are quarterly but filings arrive spread across the
  calendar; ~1,800 UW calls per month at the widened universe, against a
  120k/day budget. Pinned to uw-0 rather than every role's index-0: the job has
  no advisory lock, so a per-role pin would multiply UW spend and race the
  insert-or-touch.
- **Durable point-in-time FOMC and SEP policy paths, 2020 to present.** Four independent policy
  paths — the committee's actual decision, its anonymous SEP projection, the NY Fed dealer survey,
  and an optional third-party market shadow — now persist through the production worker and serve
  from stored rows. They stay separately keyed and are never averaged into a synthetic Fed path, and
  an anonymous SEP dot is never attributed to the Chair. Measured live: 55/55 FOMC statements and
  25/25 SEP releases parse across 2020–2026 with zero failures, and every release with more than
  one dissenter — the case where the clause grammar can actually go wrong — is verified name by
  name against the published statement. `GET /api/macro/policy` gains per-source release
  coverage (`releases_discovered` / `releases_succeeded` / `releases_failed` plus named failures),
  an exact `as_of_ts` replay instant beside the existing date-level `as_of`, and the full vote on
  each path point — `vote_status`, `vote_split`, `voted_for`, `voted_against`, and
  `voter_names_stated`, so a tally printed without a roster stays distinct from a unanimous
  committee. Evidence:
  `docs/research/2026-08-12-fomc-sep-source-probe/{probe.json,smoke-4x4.json,VERDICT.md}`.
- **Per-release ingest catalog** (`macro_release_ingest_status`) and **observation lineage**
  (`macro_observation_artifacts`), migration 121. One release's outcome no longer hides behind a
  source-level status, and every fact can name the exact artifacts that witness it.
- **Resumable 2020+ policy backfill** — `scripts/backfill/macro_policy_history.py`, driving the
  production worker entry points year by year and resuming off the release catalog. A window that
  produced no releases exits non-zero; a vacuous pass would hide a discovery outage.

### Fixed

- **A two-sided FOMC dissent no longer loses a dissenter.** The voting-against block was split on
  `;`, but when dissenters want opposite things the Fed joins their clauses with `, and` instead.
  2025-10-29 — Miran wanting a deeper cut, Schmid wanting none — therefore parsed as a single
  clause: everything after the first `, who` was discarded as rationale, taking Schmid with it. The
  tally is derived from the surviving names, so the release recorded **10-1 instead of 10-2** and
  still reported `ok` — the drop decremented the very count that would have exposed it. Both
  separators are now read, and a clause grammar we cannot parse fails the release closed rather
  than returning the dissenters it happened to understand.
- **Every release with bytes but no fact is now counted as a hole.** `GET /api/macro/policy` counted
  only `failed`, so an `artifact_only` release — the parse produced nothing but the evidence landed —
  showed up as neither a success nor a failure. "20 discovered / 17 succeeded / 0 failed" read
  exactly like a healthy source while three releases carried no fact. The counts must now account
  for every release discovered, which makes that limbo unconstructible rather than merely unfixed.
- **One unreadable stored row no longer takes the other three paths down.** A shape-drifted
  observation raised through the whole comparison and returned a 500 for all four slots. Each path
  now degrades on its own, the read-side twin of the per-release write transaction below.
- **A backfill window with a silent hole no longer exits zero.** The exit code read the catalog rows
  that existed, but a year whose discovery failed writes no rows at all — so it dropped out of the
  check that was supposed to catch it. The requested window is now the denominator, and any past
  source-year with no releases fails the run by name.
- **A corrected policy release is no longer backdated to the original release instant.** Both the
  artifact and observation layers took the publisher's declared release time verbatim, so a reissue
  retrieved months later claimed to have been public on the original afternoon — a look-ahead leak
  in the dangerous direction, where a replay reads a number nobody had. A later revision now takes
  the instant those exact bytes could first be observed, and a fact can never predate its evidence.
- **One unreadable release no longer discards its siblings.** Policy ingest committed the whole
  fetch as a single transaction, so a single malformed statement rolled back the batch — a real run
  persisted 10 statement artifacts and zero facts. Each release now commits independently; the bad
  one is recorded as failed by name and the rest survive.
- **The source probe no longer samples one release per year.** It parsed `max(meeting_date)`, which
  makes the observable failure rate structurally zero — the SEP parser sat at 1-of-25 while the
  probe reported healthy. It now parses every discovered release and takes the source state as the
  worst among them.

## [0.12.4] — 2026-08-18

### Fixed

- **A finished or killed heal run no longer wedges the nightly healer forever.**
  The nightly job skips itself while another `execute` run is `running`, and
  nothing ever cleared that flag. Two ways in: a run whose process died (SSH
  drop, Watchtower container recreate, OOM) never reached `finish_run`; and
  `resume_run` — the ordinary way an operator drains a backfill — never called
  it _at all_, so even a fully successful resume left the row `running`. Either
  way every subsequent night returned `{"skipped": "run_active"}` silently. Four
  such runs disabled the healer for a week in 2026-08 while the enable flag,
  cron, adapters and migrations were all correct. `resume_run` now closes its
  run, and the nightly job reaps rows whose process is gone — cancelling them
  and requeuing the items they stranded in `running`, a status
  `claim_next_items` skips and which were therefore unhealable. Both fixes in
  one atomic statement each, so a crash mid-reap cannot orphan items in a run
  the reaper no longer matches.
- **Manual heals now take the healer's single-flight lock.** `execute_into_run`
  and `resume_run` hold `pg_try_advisory_lock(92010)` — the lock the nightly job
  and the freshness autoheal already used — and raise `HealerBusy` (CLI exit 2)
  rather than racing. A Postgres session lock is released when the process dies,
  which is exactly the liveness guarantee a `status='running'` row does not
  give; without it the new reaper could cancel a _live_ manual heal, and the
  nightly would then re-audit the same still-missing gaps into a fresh run and
  heal them alongside it, double-charging the provider budget. Staleness is
  measured by progress (last item driven to a verdict) rather than age, so the
  heuristic stays conservative even if that ordering is ever loosened.

## [0.12.3] — 2026-08-17

### Fixed

- **Chain memberships no longer strand a tag the data has moved on from.**
  Inheriting a ticker's chain from `watchlist.sector` only ever _filled gaps_ —
  it never retracted — so correcting a ticker's sector left the old chain
  asserted forever, and no re-seed could clear it. That is why `NOV` kept
  answering the `Healthcare` filter after it was corrected to `Energy`: a
  re-seed added `Energy` and left `Healthcare` in place, showing the name under
  both. `inherit_sector_memberships` now retracts inherited rows the sector no
  longer justifies before filling, scoped to `source='sector'` so taxonomy rows
  keep their own owner.
- **Adding a ticker, or changing its sector, now updates its chains.**
  `POST /watchlist` wrote no membership rows at all, so a ticker added through
  the web UI was invisible to every chain filter until somebody ran the seed
  script by hand; `PATCH /watchlist/{ticker}` could change `sector` without
  touching memberships, which is the mutation that stranded `NOV` and `ELV`.
  Both paths now sync that one ticker's rows. Deliberately per-ticker rather
  than a whole-table re-seed: memberships are rebuilt from the taxonomy the
  _running container_ shipped with, so between a merge and a release a
  full rewrite triggered by an unrelated edit would quietly restore the old
  taxonomy.

## [0.12.2] — 2026-08-17

### Added

- **The healer can replay a past trading session, so deep-scan gaps now self-heal.**
  `pipeline.run_single_stock(market_date=...)` re-fetches every date-honouring UW
  endpoint at its true date, and the new `pipeline_replay` heal adapter wires it
  into the gap healer. Nine datasets moved from `freshness_only` (a dated refusal)
  to `strict_ticker_date` (a real audit with a real repair): `oi_by_strike`,
  `oi_change_events`, `greeks_by_expiry_strike`, `exposures_by_expiry_strike`,
  `exposures_summary`, `iv_term_snapshots`, `interpolated_iv_snapshots`,
  `max_pain_by_expiry`, `pcr_history`. On production this turned an audit reporting
  `total_gaps = 0` into one reporting **6,542** — the loss was always there; the
  healer simply had no way to express it.
  One `run_single_stock` call writes all nine tables, so the adapter fans in per
  `(ticker, date)`: nine sibling items cost one UW replay, not nine.
- **Refusal to replay an undatable dataset is enforced in code**
  (`uw_scan.pipeline_replay_policy`). Three UW endpoints —
  `/shorts/{ticker}/data`, `/stock/{ticker}/options-volume`,
  `/shorts/{ticker}/interest-float/v2` — answer HTTP 200 with a full, plausible
  row set for _any_ date and return a byte-identical body every time. Only a
  response-hash differential separates "served me that session" from "served me
  today again", so `options_volume_daily`, `short_interest_snapshots` and
  `uw_positioning` raise rather than back-date today's numbers. Every refusal
  records the date it was measured. Matrix and method:
  `docs/research/2026-08-16-replay-endpoint-matrix.md`.

- **Every one of the 143 registered datasets now carries a decision.** 45 daily
  tables refused to heal on one copy-pasted sentence nobody had probed, and 13
  liveness entries had empty reason strings. 15 adapters are now wired over
  entrypoints that were _already_ date-aware (market tide, top-net-impact,
  CRI/VCG/canary recovery, technicals, corporate actions, fundamentals, both
  lake syncs, both UW event logs, fundamental scores/anchors); the rest carry
  `reason_verified_on` — the date the refusal was actually measured. CI fails on
  an undated refusal or an undispositioned dataset.
- **Heal adapters can no longer be silently dead.** `per_ticker_*` adapters are
  dispatched only from gap items, which only `strict_*` audit modes produce, so
  wiring one to a `freshness_only` dataset does nothing while the policy doc
  shows it as covered. A test now rejects that pairing outright; the review
  tripped over it three times.
- **One dataset's backlog no longer starves every other.**
  `data_gap_healer_dataset_share` (0.4) caps any single dataset's share of a
  night's UW budget — a 4,206-item surface backlog needed ~84k calls against a
  12k cap and blocked every other dataset for a week. And after three
  consecutive `provider_no_data` verdicts the scope is auto-caveated, ending the
  nightly re-attempt of dates the provider will never serve. The auto-caveat
  fires only on the provider's answer, never on our own `no_adapter` /
  `unsupported_granularity` bugs.

### Changed

- **The chain taxonomy now names every layer's members instead of half of them
  inheriting from `watchlist.sector`.** `IDX`, `THM` and `DEF` previously held
  empty tuples and seeded from the legacy `sector` column, which capped those 63
  tickers at **exactly one chain each** — `sector` is a single column — and so
  quietly excluded them from the many-to-many the join table was built for. Two
  concrete cases it was hiding: MARA/RIOT are bitcoin miners that pivoted to AI
  datacenters exactly like the six peers already tagged `AI-Cloud/NeoCloud`, but
  could only be `Crypto`; and SPCX could not be both `M7` and `Space`. Both now
  hold both. Sector ETFs (SMH/SOXX/SOXL/IGV/MAGS) are deliberately _not_
  cross-listed into the company chains they track — a chain answers "which
  companies are in this value chain", and a fund tracking it is a different
  question. `inherit_sector_memberships` still runs as the safety net for a
  ticker the module never names; it simply has nothing left to do here.

### Fixed

- **Two pairs of lookalike tickers had been given each other's tags.** `NOV` is
  National Oilwell Varco — oil drilling equipment, UW sector Energy — but was
  carrying `Healthcare`, the tag meant for `NVO` (Novo Nordisk). `ELV` is
  Elevance Health, a common stock, but was carrying `Sector-ETF`, the tag meant
  for the `XLV` ETF. All four names are now held, each with its own tag: NOV →
  `Energy`, NVO → `Healthcare`, ELV → `Healthcare`, XLV → `Sector-ETF`. NVO is
  the only addition (~263 UW calls/day); NOV and ELV keep their accumulated
  history. A test asserts the two pairs never share a chain, which is what the
  mix-up looked like. `SPCX` keeps `M7` by operator decision and additionally
  gains `Space`.
- **`ISRG` was the last active ticker whose membership came from sector
  inheritance rather than the taxonomy.** Now enumerated in both
  `DEF/Healthcare` and `L4/Robotics/Automation` — surgical robotics is
  genuinely both — so no active ticker depends on the fallback path.

- **A same-day fetch memo would have poisoned the replay in both directions.**
  `fetch_option_contracts` and `fetch_greek_exposure_by_expiry` memoize on
  `(ticker, endpoint, ET-today)`. Under a historical replay a memo _hit_ returns
  today's payload to be stamped with a past date, and a memo _miss_ stores the
  historical payload under today's key and corrupts the live nightly path for the
  rest of the day. Replay now bypasses the memo entirely; the live path keeps it.

- **The gap healer could not see the outage that mattered most.** Its
  trading-day spine read `market_tide_sentiment_daily` alone — a _captured_
  table, so an outage that stopped capture also deleted the dates from the
  expected-session list and every dataset then audited as 100% covered for
  exactly the days that were lost (measured: 1,276 gaps reported against 8,080
  real). The spine now unions SPY's massive `daily_ohlc`: a different provider,
  so a UW outage cannot blind it, and session-only bars, so it cannot invent a
  weekend (confirmed on 60 days of production data — zero weekend rows). The
  audit CLI prints a banner naming the sessions the reference lost, because the
  union fixes that audit but not the other reports reading the reference
  directly.
- **A partial heal made the freshness monitor blinder, not sharper.**
  `coverage_pct` counts tickers within `grace_days` of the table's _own_ newest
  row, so two healed tickers on the newest date pulled `max_data_date` forward
  and the 4-day window then reached back over the hole. New `sessions_missing`
  counts expected sessions that are genuinely under-covered. Measured on
  production the day it shipped: **11 tables reporting `coverage_pct = 1.000`
  and `frozen = false` while holding zero rows on three or more of the last five
  sessions**, with the audit reporting `total_gaps = 0`. `coverage_pct` is
  unchanged — its grace window is deliberate, and `/api/health` and the autoheal
  circuit breaker both read it.
- **`greek_exposure_daily` heals the 11 tickers it most needs to.** The adapter
  delegated to a nightly job that skips `gex_scan_tickers` (AAPL, AMZN, GOOGL,
  META, MSFT, NVDA, TSLA, SPY, QQQ, IWM, TLT) to avoid double-fetching with the
  regime scan — so healing those selected the ticker, skipped it, returned 0,
  and recorded `no_data`. It now writes its own rows from UW's full ~250-row
  series, one call per ticker instead of one per missing date.
- **GRG historical snapshots are computed, not restamped.** `grg.run(as_of=)`
  truncates all three data inputs — the 1Y gamma series, spot/flip from
  `gex_snapshots`, and SPY closes. Truncating only the obvious one would stamp a
  past date on a row built from future data, which is what produced four
  byte-identical `vrp_macro_signal_daily` rows during round 1.

## [0.12.1] — 2026-08-17

### Fixed

- **The watchlist dashboard issued one HTTP request per ticker card on load.**
  Every `TickerCard` fetched its own sparkline in a mount effect, so request
  count equalled watchlist size. Measured on the deployed dashboard at 170
  tickers: 170 requests carrying 178 KB total — ~1 KB each — averaging 5.4 s
  apiece and spanning 7.5–9.2 s of wall clock, because the browser runs only
  ~6 connections at a time. `cache: "no-store"` replayed the whole fan-out on
  every return to the dashboard. Only ~4 cards are on screen at once, so the
  vast majority of that work was for sparklines nobody was looking at. The
  fetch is now gated on an `IntersectionObserver` bound to the scrolling
  ancestor, and the card links opt out of Next's speculative RSC prefetch.
  Verified in Chrome against a production build of a 114-ticker grid: initial
  load drops from 114 requests to 8 and RSC prefetches from 23 to 0, while a
  continuous scroll still fetches all 114 exactly once — no duplicates, none
  starved. Environments without `IntersectionObserver` (jsdom, older browsers)
  keep the previous fetch-on-mount path.

  Two things worth recording for whoever touches this next. First, the
  observer's `root` must be the scrolling ancestor: AppShell scrolls an inner
  `<main overflow-y:auto>`, and `rootMargin` expands only the _root's_ bounds,
  never ancestor clip rects — with `root: null` the 600 px preload is silently
  a no-op (a card 300 px below the fold reports `isIntersecting: false`), so
  cards would load only once already on screen. Second, this change is
  justified by the request reduction, not by a measured page-open speedup: a
  controlled production A/B at 114 tickers under Slow 4G throttling found
  click-to-content statistically unchanged (no gate 931 ms, gate 918 ms, gate
  with prefetch left on 947 ms). The 9.2 s fan-out is real and measured on the
  deployment; that it is what makes opening a stock page feel slow remains a
  plausible mechanism, not a demonstrated one.

## [0.12.0] — 2026-08-16

### Added

- **Fundamental cards flip to the figures behind them.** Clicking any card on the
  Fundamentals tab expands it to a 20-quarter chart of the components its ratio
  was computed from — `gross_profit` against `total_revenue` for gross margin,
  operating cash flow against capex for FCF margin, and so on — served by a new
  `GET /stock/{ticker}/fundamentals/statements`. Clicking the expanded card flips
  it back; there is no separate close control. The components are resolved
  server-side in `build_feature_details`, beside `build_features` and sharing its
  helpers, so the back cannot drift from the front; a test asserts the plotted
  line equals the plotted input bars for every feature. Each back states its own
  **basis** (`gross_margin` and `op_margin` are quarterly where the rest are TTM,
  and three ratios divide a TTM flow by a point-in-time balance) and its
  **reported currency**, since TSM files TWD against a USD quote. The three
  features with no validated direction keep a neutral line — the front's rule
  holds on the back.
- **An eighth, descriptive card: revenue & earnings.** TTM revenue, net income and
  free cash flow. It enters no composite and carries no percentile, and says
  `descriptive · not scored` where a subscore tile states its direction — the
  seven around it are a validated set and a tile that looked identical would be
  read as an eighth measured feature. It also squares the grid to 8.
- **The fundamental lane now runs on a schedule.** `fundamental_refresh`
  (`worker/jobs/fundamental_refresh.py`, nightly 18:20 ET, massive-0, gated
  `UW_SCAN_FUNDAMENTAL_REFRESH_ENABLED`, default on) chains routing → subscores
  → anchor bands. Until this existed **nothing called `fundamental_scoring` or
  `fundamental_anchors` outside tests** — the card showed whatever a hand-run had
  last written and would have gone quietly stale. Zero UW/IB spend: Postgres plus
  the local parquet mirror only. It deliberately does not ingest statements;
  `scripts/backfill/fundamental_ingest_backfill.py` remains the manual path for
  new filings.
- **Immutable point-in-time macro evidence contract and top-down program plan.** New
  `macro_source_artifacts` and `macro_observations` tables preserve exact source payloads,
  revisions, source disagreement, publication/availability semantics, quality, and cost class
  without changing the existing rates or Gold Compass read paths. Python and PostgreSQL recompute
  artifact/observation content identities, enforce artifact time/quality bounds, and reject direct
  historical rewrites, ambiguous timestamps, empty source precedence, and mock/static/demo sources
  outside test databases. A read-only `option_wizard_local` inventory covers all 19 legacy
  rates/gold relations and records the adapter sequence for inflation → policy/rates → USD → gold,
  including future evidence-first Rates, Gold, unified Macro, and Fundamental PM context surfaces.
- **Free policy-evidence ingestion with four paths that never get averaged together.** Official
  Federal Reserve statements preserve decisions, target ranges, dissent, and vote splits; official
  SEP releases preserve anonymous participant distributions and published medians without inferring
  a Chair-specific dot; and the New York Fed Survey of Market Expectations preserves its Primary
  Dealer path and distributions from the structured workbook. `GET /api/macro/policy` returns
  actual, committee-projection, dealer-expectations, and market-implied paths independently with
  evidence references, release/availability times, missing reasons, freshness, and contradictions.
  The free Frenzy Capital futures view is retained byte-for-byte as an optional third-party shadow:
  it is disabled by default, cannot satisfy an official path, and reports `delay_status=unknown`
  because its publisher supplies neither a publication timestamp nor a delay contract.

### Changed

- **Valuation bands reach 233 of 257 names, up from 43.** Routing previously
  seeded only from `watchlist.sector`, and the gap was never a mapping one:
  **174 of the 257 ranked names carry no sector anywhere in the database**
  (`watchlist` is the only source; `flow_events` adds no name it lacks,
  `research_universe` shares none), and the five-type taxonomy is an
  AI-supply-chain one with no honest bucket for a bank or a hospital even where
  a sector is known. Unrouted names now take an explicit `unclassified` route to
  `sales_to_ev` — the pooled-universe result the probe actually measured (+0.0744
  over all 247 scored tickers, the strongest of the five yields) — capped at
  `confidence: medium` and stating on the card that the method was not chosen for
  the business. No name is forced into one of the five real types on a guess.
- **`spot_percentile` is stated as a rank, not a percentage.** It is a count over
  `history_quarters` observations, so on the shipped 20-quarter window it takes
  21 values with 5-point steps; "cheaper than 100%" read as a bound rather than
  as "at or past the cheapest reading in the window". Now "Cheaper than 16 of its
  last 20 quarters", with words at both ends.

### Fixed

- **The valuation band's labels did not line up with its own scale.** The rail
  placed ticks by VALUE while the five level labels underneath were an evenly
  spaced grid, so the two disagreed on **all 233 live bands** — median 20,
  maximum 80 percentage points of panel width. AAPL printed "buy below 247.1"
  under a position the rail read as ~253. Labels now sit at their own value,
  staggered across two rows (measured: all five in one row leaves 90 of 233
  with neighbours under 7pp apart; staggering lifts the median gap from 8.6pp
  to 24.3pp and leaves 3 under 4pp), and the duplicate grid is gone. The gaps
  between levels now carry information — AAPL's three cheap levels bunch at
  247/256/263 with a gap before 299.5/305.3, which the even grid hid.
- **A band with a missing END is refused instead of drawn** — the hole in the
  2026-08-12 width guard, which read `if lo and hi` and so skipped the check
  entirely when a level did not invert. JPM rendered `observe_mid` at **11.3
  against a spot of 297.8** with `buy_below` blank: a bank's funding sits in
  `short_long_term_debt_total`, so net debt exceeds the enterprise value its own
  cheapest multiple implies. An interior gap is unreachable (price is monotone in
  the target yield, so any failure takes an end first), and the now-dead
  "levels not invertible" branch was removed rather than left as apparent
  coverage.
- **Anchor rows were hashing the wrong thing entirely.** They reused
  `scoring.inputs_hash`, which reads the seven scoring FEATURES _by name_ — a
  band has none of them — so every row reduced to a function of `company_type`
  and `engine` and its actual inputs were never in its identity. Measured: a run
  computed 233 bands and wrote **0**, keeping the wrong JPM row alive under
  `ON CONFLICT DO NOTHING`. New `valuation.anchor_inputs_hash` covers the band's
  own inputs, its routing, the thresholds, and an `ANCHOR_RULES_REV` — so a rule
  change appends the correction instead of colliding with what it corrects. The
  job now also WARNs when it computes rows and writes none.
- **Four `_self_check()` functions in `uw_scan/fundamentals/` were never run by CI** (`fx`, `scoring`, `statements`, `valuation`) — they executed only when a human typed the module. `valuation`'s carries the only assertions that an `unclassified` name bands at `medium` on the pooled default and that `anchor_inputs_hash` responds to each of its six inputs, so the coverage for two of the fixes above was itself unenforced. `tests/unit/fundamentals/test_self_checks_run.py` discovers them by introspection and runs each, so a fifth is covered the day it lands.
- `docs/research/2026-08-12-fundamental-valuation-timeseries/results.md`
  regenerated `na` for every signal: the window sweep changed the result keys to
  `<signal>|w<window>|<outcome>` and the table's lookup was not updated, so a doc
  that regenerates on every run had silently lost its own result set while
  `VERDICT.md` quoted the numbers from the JSON. The headline window is now
  labelled explicitly.

### Research

- **The concentration ledger (spec §6 `concentration_risk`) is blocked on data
  structure, and nothing was built.** Verdict + reproducible probe:
  `docs/research/2026-08-12-fundamental-segment-computability/`,
  `scripts/research/fundamental_segment_computability_probe.py`. §896 marked it
  available on a coverage check — rows come back for 24/25 — but **coverage is
  not computability**. Requiring a breakdown's single-member rows to sum to its
  own consolidated total (the same two-derivations cross-check that caught the
  TSM currency bug) yields **8 of 25 on segment and 0 of 25 on geography**.
  UW's `rev_breakdown` is one flat list per ticker mixing several XBRL axes with
  no level marker: NVDA files `DataCenter` 75.25e9 alongside its own children
  `Hyperscale` + `AIClouds` = exactly 75.25e9 on the same axis, so "largest
  segment share" is 92% or 46% depending on nesting depth; AVGO has two axes that
  each sum correctly and disagree (76% vs 68%); 23 of 25 have no total at all
  inside `country`/`continent`, and MSFT's "countries" are a US/non-US pair
  leaving 48% unallocated. The values also alternate quarterly/annual by filing
  form with no `formtype` on the row. Unblocking needs SEC XBRL presentation
  hierarchy or a curated per-ticker axis pin; there is no accrual pressure, since
  the data is filing-derived back to 2020.

- **Fundamental source contract measured; the planned backbone was the wrong
  one.** Four reproducible probes under `scripts/research/`
  (`fundamental_source_coverage.py`, `fundamental_field_contract.py`,
  `uw_fundamentals_probe.py`, `sec_xbrl_gapfill_probe.py`) with artifacts in
  `docs/research/2026-08-10-fundamental-source-coverage/`. **Unusual Whales —
  already paid for and already integrated — beats massive on eight of nine
  measured axes**: 25/25 tickers vs 23, 1,673 ticker-quarters vs 1,092, history
  from 2005 vs 2009/2010, 0.0% vs 15.1% impossible share counts, and 100%
  cohort coverage of capex/EBITDA/D&A/cash/total-debt/interest, none of which
  massive `/vX` emits at all. It was never checked because an old note that UW's
  `companies/*` family 403s had been generalized to the `stock/*` statement
  routes, which are 200. massive stays as tier 2 for the one axis it wins —
  `filing_date` on 74.5% of rows against UW's 45.2% — and as a drift
  cross-check.
- **massive `/vX` emits values that cannot be true, on current data**: GOOGL
  2026-03-31 carries a **−478,746,000,000** liability, NVDA 2026-01-25 a
  **−28,000,000** share count; 5.1% negative liabilities and 15.1% impossible
  share counts across 272 recent rows. The design gained an INGEST validation
  gate and a `fundamental_obs_violations` table in response.
- **Two spec claims falsified.** Segment/KPI disclosure is _not_ "absent at any
  tier" — UW returns XBRL-dimensional segment and geographic revenue for 24/25
  tickers (4,330 rows), after the named-customer graph was measured as
  nonexistent. **Superseded on the product claim**: those rows exist but do not
  yield a share for most of the cohort — 8/25 on segment, 0/25 on geography — so
  `concentration_risk` is not buildable from them. See the computability verdict
  under Research above. And foreign
  issuers no longer need a blanket `na`: TSM/ASML have 83 quarterly rows each
  from UW, FX dailies were already in the livewire lake, and SEC XBRL supplies
  the missing noncontrolling interest (`us-gaap` for domestic filers,
  `ifrs-full` for 20-F). Only TSM's equity-denominated ratios remain `na`, for
  the stated reason that no quarterly NCI exists at any source.
- Handoff for the data lake:
  `docs/masterplan/2026-08-11-fundamental-data-brief-for-livewire.md`. Method
  spec rewritten to revision 3 against the measured source set, then to
  **revision 4** against the validation result: §13's "the method has never been
  validated" closed, the `profitability` direction claim withdrawn, the composite
  barred from ordering any core-25 surface (invariant I5 tightened, S2's cell
  ramp included), the harness entry gate rewritten from a test that could not
  fail, and acceptance tests T25–T27 added. Mac mini down as of 2026-08-11 —
  §13 records what that blocks (P1b ingest, real-worker smoke tests) and what it
  does not (research on the wide universe, field maps, the method appendix).
- **The fundamental composite orders forward returns at 245 names and is
  indistinguishable from noise at 25.** Method tested before P1b built any
  ingest. `scripts/research/fundamental_universe_breadth_probe.py` measured the
  achievable universe — 245 names carrying both deep lake price history and
  > = 40 quarters of UW statements, every candidate probed rather than sampled
  > and extrapolated. `fundamental_signal_validation.py --wide` then ran the same
  > code over it: **2q composite rank IC 0.059, t 4.84, hit rate 71.8% over 78
  > quarters**, against IC 0.024, t 0.68 on the 25-name AI cohort. The single
  > most defensible figure is the **0.039 (t 2.67)** measured on observations
  > carrying a real `filing_date`, with no point-in-time fallback and therefore no
  > look-ahead. Effect present in both halves of the sample and decaying
  > (0.072 -> 0.047). Verdict, robustness table and limits:
  > `docs/research/2026-08-11-fundamental-signal-validation/VERDICT.md`.
- **Consequence for the product: do not put a sortable composite score on a
  25-name page.** The ordering is validated on a universe argon does not have;
  at watchlist width the cross-section is too thin to measure at any history
  length. The descriptive card stands, now for a measured reason. This is not
  claimed as alpha — profitability, low investment and low leverage are the
  documented quality factors, so recovering them evidences a correct pipeline,
  not an edge. Survivorship is unfixable from these sources: ATVI/XLNX/TWTR/
  SIVB/FRC/VMW are absent from the lake and return HTTP 200 with an empty array
  from UW.

- **Valuation control: the margin inversion is not expensiveness in disguise.**
  Rev 4 withdrew the `profitability` direction on a hypothesis — high-margin
  firms are usually richly priced, so a margin ranking might be a valuation
  ranking. `scripts/research/fundamental_valuation_control.py` tested it and
  **rejected it**: `op_margin`'s partial rank IC against three price ratios is
  −0.0231 / −0.0306 / −0.0298 versus −0.0270 uncontrolled, and against
  `book_to_price` both margins get _stronger_. Market cap is built from **raw
  `close` × as-reported shares** — `adj_close` is retroactively split-adjusted
  and would mix reference frames across every split. Ratios are yields
  (fundamental/price), so ranking stays monotone through zero earnings.
- **The incidental finding is the bigger one: value is inverted over this
  window.** `book_to_price` IC −0.0365 (t −2.32), `earnings_yield` −0.0194;
  only `fcf_yield` works (+0.0285, t 2.84). That is the documented post-GFC
  value drawdown, and it means the signals that worked are one regime's profile.
  **The earlier two-halves robustness check is therefore weaker evidence than it
  read — both halves sit inside the same quality-led regime.** Nothing is
  retracted; the claim's coverage is bounded, and "measured in one regime" is
  now risk 1's third standing limit alongside survivorship and uncosted returns.
  §5.2's `valuation_position` prior ("cheaper better") is flagged as
  contradicted for B/P and E/P.

### Fixed (research tooling)

- **The validation panel was keyed on `fiscal_date_ending`, which silently
  discarded ~90% of every cross-section.** Filers do not share a fiscal calendar
  (NVDA ends 01-31, MSFT 12-31, AAPL 12-28), so period-end keying shattered one
  economic cross-section into many thin ones, each then dropped by
  `MIN_CROSS_SECTION` without a word: 268 "periods" at a **median width of 23**
  out of 245 available names. Re-keyed on the **knowledge-date quarter** — the
  correct construction regardless, since a rank IC is only meaningful among
  names whose information was public at the same time — the same data gives 97
  buckets at a median width of **241**. The bug did not error; it returned a
  confident, well-formatted, wrong number, and it had already produced one
  published finding (cohort `asset_turnover` at t −4.30, which falls to t −0.49
  once corrected) complete with a plausible economic story. A one-line guard now
  warns when the realised median width falls under half the universe.

### Added

- **Valuation anchor band on the fundamental card (stage 3).** Migration `118`
  adds `valuation_anchors` + `fundamental_company_type`;
  `fundamentals/valuation.py` is the pure compute,
  `storage/fundamental_anchors.py` the persistence,
  `worker/jobs/fundamental_anchors.py` the job (plus sector-driven company-type
  seeding), and `web/.../FundamentalAnchorBand.tsx` the surface. Each level is
  the **price at which this company's valuation yield would sit at a stated
  percentile of its own past** — `buy_below` at the 80th, `risk_above` at the
  20th — with spot marked against it. 51 of 257 names band today; the rest are
  unrouted, which the card states as a coverage gap rather than a verdict.
- **`company_type` selects which yield, and nothing else.** A deliberate
  narrowing of spec §5.3, which describes richer per-type methods
  (peak/trough margin normalization, Rule-of-40 banding) written before any of
  it was measured. What is measured is the plain own-history percentile of a
  plain yield, so the routing keeps §5.3's anchor-basis column
  (`chips_cyclical`/`software_growth`/`high_risk_growth` → `sales_to_ev`,
  `platform_scale` → `fcf_yield`, `power_infra` → `ebitda_to_ev`) and drops the
  modelling layer on top. §7's base/bear/bull × 1y/3y grid is **not built**: it
  needs a validated growth model and there is none.
- **The band ascends in price, enforced in Postgres.** A `CHECK` constraint, not
  just a builder invariant — an out-of-order band is not a bad number, it is an
  inverted recommendation, so it is unrepresentable rather than merely
  unproduced. NULL levels compare to NULL and pass: an absent level is unknown,
  not disordered, and renders as a dash rather than a boundary at zero.

### Fixed

- **A currency mismatch produced a confident, plausible, wrong valuation band.**
  Enterprise value adds a market cap to a balance-sheet figure, and for a
  foreign issuer those are in different currencies: TSM files in TWD while its
  ADR trades in USD, so on 2026-08-12 it carried revenue 4.45e12 (NT$) against a
  2.10e12 (US$) market cap and an enterprise value of **−5.5e10** — while
  printing five levels that looked like ordinary share prices ($443–574).
  Nothing on screen would have said so. `build_anchors` now refuses any
  EV-denominated band whose enterprise value is non-positive at the current
  price, which catches any unit or currency mismatch without needing an FX table
  or a list of foreign filers, and states the reason on the card. Caught by an
  invariant, not by inspection: TSM was the only banded name whose spot
  placement came back null, because that path was guarded and the band was not.
  Both are guarded now, and the invariant — a band implies a spot placement —
  holds across all 51.
- **The band's price levels were unreachable, and the fix is a measured trailing
  window.** Shipped on the expanding window the verdict measured, ASML's
  `buy_below` landed at **255.7 against a spot of 1518** — a sixth of the price,
  a level it would not see in a 2008-scale crisis. Two unrelated causes:
  **non-stationarity** (ASML's `sales_to_ev` median fell 5.5x from its oldest
  quarter-quartile to its newest, NVDA's `fcf_yield` 2.8x, so a full-history
  percentile is a price from a regime that has gone) and **sign-crossing**
  (TSLA's free cash flow was negative in 36 of 65 quarters, so most percentiles
  of its `fcf_yield` sit at or below zero and have no price inversion — its band
  rendered 2 of 5 levels). The underlying error was interpretive: the IC
  validated an ORDERING, and the band inverted it into absolute PRICE levels,
  which no rank statistic licenses. Re-running the probe across (expanding, 40q,
  20q, 12q) keeps the effect at every width — `sales_to_ev` 0.0744 (t 5.77) /
  0.0642 / **0.0604 (t 5.45)** / 0.0639 — so the expanding window was never
  load-bearing. **20 quarters ships**: TSLA's negative-FCF quarters fall out
  entirely (0 of 20) and every band lands within reach of spot. Trace and the
  full revision: `docs/research/2026-08-12-fundamental-valuation-timeseries/VERDICT.md`.
- **A band whose ends are far apart is now refused, with its width stated.**
  The trailing window fixed the systematic case and left a tail it could not:
  NBIS still spanned **72x** between `buy_below` and `risk_above`, MSTR 47x,
  APLD 17x. Those are names whose own five-year range straddles a business
  transformation, so the honest answer is that their history cannot anchor a
  price — not a band with 72x between its ends. `MAX_BAND_WIDTH = 4.0` sits in
  the empty part of the measured distribution (median width **1.73x**; the
  refused tail is 5x and above), and refuses 10 of 53 attempted bands. Widest
  surviving band: 3.02x. The job warns when the refusal share passes 30%, which
  would mean the window is wrong rather than the names being unusual.
- **The first version of that guard could not fail on the case that motivated
  it.** Keying on spot-versus-midpoint looked reasonable and passed ASML's broken
  band silently: 1518.3 / 699.8 is 2.17x, inside any sane bound. What was wrong
  was the 4.35x between the band's own ends. Recorded as a test, because a metric
  that cannot fire on its motivating example is not a guard.
- **The quiet half of the same bug: three filers banded from unconverted
  foreign-currency statements.** The EV guard above only catches the
  catastrophic case. ASML's ~16% EUR gap produced a full band at
  `confidence: high` — indistinguishable on screen from a correct one — and NOK
  the same. Nor is the error a constant that cancels inside a percentile: USDEUR
  ran 0.747→0.859 over 2005–2026, so an unconverted history is distorted by a
  factor that _moves_, reshaping the distribution the band's percentiles are
  drawn from rather than sliding it. New `fundamentals/fx.py` translates each
  figure at its own statement's rate under the **two-rate rule** (flows at the
  window average, stocks at the close), sourcing dailies from the lake's
  `asset_class=fx`. ASML's `buy_below` moves 293.15 → 255.71. A filer whose
  statements cannot be translated is now **refused**, never banded unconverted.
- **Reporting currency is per STATEMENT, not per filer.** Measured on NBIS
  2026-03-31: income and balance report USD while the cash-flow statement
  reports RUB, in the same quarter. A per-ticker model reads whichever statement
  comes first and applies it to figures never denominated in it. Blocking is
  scoped to the statements a method actually reads, so NBIS's RUB cash-flow
  statement does not cost it a `sales_to_ev` band it can be priced from
  correctly.
- **UW serializes a missing currency as the literal string `"None"`**, not as
  JSON null — measured on AMZN, APLD, OXY, VST, WDC. A newest-first currency walk
  stops on that sentinel, which had reclassified NBIS (genuinely RUB on its real
  rows) as a domestic filer. Sentinels are skipped rather than accepted.
- **`fx` registered as a lake asset class** (`lake_fx_root` setting +
  `lake_resolver._ASSET_CLASS_TO_LOCAL_ATTR`/`_ASSET_CLASS_CANARY`), closing R10
  from the livewire brief. The FX root is now configured rather than derived by
  string surgery on the equity root. Canary is `USDEUR`, not `USDTWD`: it is the
  pair present in every mirror measured so far, and a canary that only exists on
  the mini would report a healthy lake as broken everywhere else.
- **TSM's refusal is a thin dev mirror, not a missing source.** The mini's lake
  already carries `USDTWD` (5,395 rows from 2004-03-24, current to 2026-08-10 —
  §3.6 of the livewire brief); the MacBook mirror has only `USDEUR`, which is why
  it refuses locally. No FRED dependency and no livewire ask: TSM bands wherever
  the full mirror is present, and where it is not, the card names the missing
  series instead of showing a number.

- **`fundamentals_refresh` has never persisted a row — it silently rolled back
  every night.** `_repo()` (`worker/scheduler.py`) opens a psycopg connection
  with the default `autocommit=False` and closes it in `finally` without
  committing, and neither `worker/jobs/fundamentals_jobs.py` nor
  `storage/fundamentals.py` called `.commit()` — so every upsert was discarded
  on close while the job logged `"fundamentals_refresh refreshed %d tickers"`
  and reported success. The sibling `positioning_refresh_once` survives only
  because `insert_scan_run` / `finish_scan_run` commit internally on the same
  connection; fundamentals had no such accident. Live on the mini,
  `massive_fundamentals` holds 669 rows across 86 tickers with a latest
  `fetched_at` of **2026-06-01** — those arrived through some other historical
  path, and the scheduled job has contributed nothing since migration `066`.
  The job now commits **per successful ticker**, and rolls back on failure:
  Postgres aborts the entire transaction on any error, so without the rollback
  one bad ticker made every _subsequent_ ticker fail with
  `InFailedSqlTransaction`. That second bug was latent behind the first — with
  nothing ever committing, a cascade had nothing to lose.
- **The integration test could not have caught it.** It asserted on the job's
  own still-open connection, which sees uncommitted rows, so it passed against
  a job that persisted nothing. Assertions now read through a **separately
  opened connection**, and the new coverage is a _freshness delta_ rather than
  a row count — a count gate would have passed on production's pre-existing 669
  rows without the bug being fixed. Both halves of the fix are verified
  load-bearing: removing the commit fails the fresh-connection test, and
  removing the rollback fails the cascade test with `InFailedSqlTransaction`.

### Research

- **The 245-name ranking earns nothing, and transaction costs are not why.**
  `scripts/research/fundamental_cost_turnover.py` forms the actual quarterly
  portfolio. Gross quarterly alpha before any cost: top 10% **−0.0007** (t −0.09),
  top 20% +0.0007 (t +0.15), top 33% +0.0006 (t +0.16); every |t| ≤ 1.06 and the
  top-minus-bottom spread is **negative** at all three widths. The break-even-cost
  column is arithmetic on a zero numerator and must not be quoted. Verdict:
  `docs/research/2026-08-12-fundamental-cost-turnover/VERDICT.md`.
- **Why a t = 3.09 ordering pays zero — the decile profile reconciles it.** Mean
  return-rank climbs 0.475 → 0.526 across deciles 0–8 and median return climbs
  with it (+0.0145 → +0.0409), but mean return does not: the **worst**-ranked
  decile carries the **highest** mean (+0.0601) with the **lowest** median
  (+0.0145). Severe right-tail skew sits exactly where the composite ranks worst.
  A rank IC measures the typical name; an equal-weighted book earns the mean.
  This also kills the obvious salvage — "avoid the bottom decile" discards the
  biggest winners with the worst losers.
- **The decile-9 reversal is recorded, not acted on.** Deciles 7–8 carry the best
  return-rank and decile 9 falls back; picking them after seeing ten deciles is
  data snooping, so it is flagged as needing a pre-committed test with a stated
  mechanism rather than turned into a recommendation.
- **Consequence (spec §4.3 rev 6): the ranked screen ships as a triage surface,
  never a strategy.** No sizing, no expected-return language, no turnover budget,
  not a portfolio-construction input.
- `composite_scores` extracted from `fundamental_signal_validation` so the cost
  study scores names with the **same** implementation the IC was produced with;
  verified behaviour-preserving by re-running the wide validation and confirming
  `validation_wide.json` is byte-identical.
- **A name's own fundamental deterioration does NOT precede its own drawdown —
  a powered null, and it closes the question the card is built on.**
  `scripts/research/fundamental_timeseries_test.py`, 250 tickers, 16,857
  within-ticker observations read from the new `fundamental_statement_obs` panel.
  Market-neutral within-ticker IC is ~0.00 (`change|ret_2q_dm`: **−0.0000,
  t −0.00**). All 16 hypotheses carry Benjamini-Hochberg and Bonferroni
  corrections computed in the script and persisted in the artifact; **every
  market-neutral test fails, and every survivor is a raw, market-contaminated
  one**. `level|dd_1q_dm` (t 2.34) is precisely the ~1 false positive 16 tests
  are expected to produce and does not survive. Verdict:
  `docs/research/2026-08-12-fundamental-timeseries-test/VERDICT.md`.
- **The null is powered, which is what makes it usable.** All eight
  market-neutral detection floors sit at 0.018–0.023 against the **0.039** the
  same composite produces cross-sectionally — so an effect of the size that
  demonstrably exists _across_ names would have been found _within_ one. Absent,
  not unproven. (Revision 1 of the cross-sectional verdict declared a null
  without asking what its test could detect and was wrong; this does not repeat
  it.)
- **The raw result that looks like a finding is the market.** `level|ret_2q`
  reads IC −0.0396, t −3.41 and survives Bonferroni — then collapses to −0.0047,
  t −0.41 once the knowledge-quarter mean is removed. An 88% reduction: the whole
  effect is panel-wide late-cycle fundamentals, nothing that distinguishes one
  name from another. Its t-stat is also not trustworthy on its own terms, since
  250 tickers exposed to one macro path are not 250 independent observations.
- **Product consequence (spec §7 rev 6): subscore trends are descriptive, never
  predictive.** "Gross margin has fallen four quarters running" stays as a
  citable fact; no price consequence may be drawn from it, and the stage-5 schema
  must forbid the claim with the deterministic auditor failing it — a model handed
  falling subscores reaches for "and so the stock should underperform" unprompted.
  §8's ranked screen is untouched: **the composite ranks names against each other
  and does not time one against itself.**
- **A name's own VALUATION does time that name, where its own quality does not —
  and it survives the control that should have killed it.**
  `scripts/research/fundamental_valuation_timeseries.py`, 247 tickers, 17,005
  observations through the same harness that returned the null above. All five
  own-history valuation yields carry a positive market-neutral IC at 2q;
  `sales_to_ev` leads at **+0.0744 (t 5.77)**, hit rate 0.683 — the basis three
  of the five §5.3 company types already route through. Verdict:
  `docs/research/2026-08-12-fundamental-valuation-timeseries/VERDICT.md`.
- **The reversal control failed to explain it, in three separate ways.** Every
  signal is fundamental/price with a quarterly numerator over a daily
  denominator, so most within-ticker variation in a "valuation" score is price
  variation — short-horizon reversal was the default explanation, not a remote
  risk. A pure negated-trailing-return signal pushed through the identical
  pipeline earns a real but smaller **+0.0353 (t 2.60)**; holding it constant
  makes every valuation signal **stronger** (`sales_to_ev` → +0.0826, t 7.28;
  `book_to_price` → +0.0551 from +0.0356); and reversal does not predict drawdown
  at all (**+0.0014, t 0.10**) while every valuation signal does. Two signals
  that were the same thing relabelled would not diverge on a second outcome.
- **Product consequence: the anchor band may be prescriptive, the subscores may
  not.** `buy_below` has measured support at the horizon the card speaks to, so
  the five §5.3 levels keep their prescriptive names — but the band is an
  **own-history percentile, never a cross-sectional one**. The cross-sectional
  value inversion (`book_to_price` IC −0.0365) still stands; the same word names
  two different quantities with opposite signs. Standing limits carried:
  survivorship (delisted names absent by construction, biasing "cheap precedes
  strength" upward), ticker-level t-stats optimistic, uncosted, and not a
  strategy — this licenses a band on a card, not a rule with sizing behind it.

### Fixed

- **The card would have rendered a false 100% gross margin.** UW echoes
  `total_revenue` into `gross_profit` on some rows while still reporting a
  positive `cost_of_revenue` — CEG 2026-06-30 serves revenue 7,506m, cost 6,276m
  and gross_profit 7,506m, where the prior quarter is internally consistent
  (11,122 − 6,352 = 4,770). Measured: **580 rows across 46 tickers**, ~2.8% of
  income rows, concentrated in insurers and utilities (AFL 70, AIG 62). New
  `gross_profit_equals_revenue_despite_costs` check; 574 recorded (the 6-row gap
  is `revenue == 0` rows, degenerate rather than inconsistent).
- **The raw feature is deliberately NOT nulled.** Editing `features.py` would
  change the validated math and break reproducibility of every published result,
  so the value stays as computed and the _display_ layer suppresses it via
  `violated_fields()`, joined through `fundamental_scores.source_obs_ids`.
  Verified end to end: CEG renders `na`, NVDA still renders 74.9%.
- `recheck_violations()` replays checks over stored immutable payloads, because a
  check added after rows land otherwise only ever sees future ingests.
- **`record_violations` was overstating what it wrote** — it returned
  `len(violations)` while its SQL is `ON CONFLICT DO NOTHING`, so a replay
  reported writes it never made. Now counts `RETURNING` rows. Caught by the
  idempotence test written for the replay path; a backfill would otherwise have
  reported healthy progress while writing nothing.

### Added

- **The card plots, and every series is a claim with evidence under it.** Each of
  the seven features gets its own trajectory (40 quarters by default, `?quarters=`
  1–120) plus its percentile in the knowledge-quarter panel; the composite gets a
  larger chart of the same window. New `series_for_ticker` / `cross_section` /
  `violations_by_obs` reads, `build_history` / `build_percentiles` compute, and a
  hand-rolled `FundamentalSparkline` (no chart library — repo rule).
  All 257 names carry ≥8 quarters and 256 carry ≥20, so this needed no new ingest.
- **Every trajectory carries its own date axis**, not just the composite. The
  axis moved inside `FundamentalSparkline` so all eight charts share one
  implementation and cannot drift apart, and it labels the ends of the plotted
  WINDOW rather than of each feature's drawn line — a series whose opening
  quarters are suppressed starts inboard of the left edge and still reads on the
  same window as its siblings.
- **A quarter we do not believe is drawn as a GAP, never bridged.** A flagged
  input becomes `null` _in place_ — the line breaks and a dashed rule marks it —
  because dropping the point would shift every later quarter left and misdate the
  series, and interpolating across it would produce a smooth, confident, wrong
  chart. CEG's `gross_margin` breaks at exactly the echoed quarter (1 null of 40)
  while its `op_margin` is intact.
- **Disbelieved values are removed from the comparison panel, not just from the
  subject.** Otherwise every name would be ranked against the ~46 tickers whose
  `gross_margin` reads exactly 1.0 for the reason the card refuses to display.
  A suppressed subject therefore has no percentile at all, and `n` is stated per
  feature because it differs (NVDA: 253 / 239 / 252) — a percentile whose
  denominator is unnamed is not a fact.
- **Deliberately NOT copied from the reference financials browser: the
  "Fundamentals Checklist" of QoQ/YoY arrows.** Scoring "6 positive / 1 negative"
  requires a direction for every line item, and our own validation measured
  `gross_margin` and `op_margin` **inverted** while `roe` is named by no rubric
  row. The most copyable element on that page is the one we are forbidden to
  copy. Same reason there is no red/green ramp on any chart here.
- **Fundamental card — the deterministic blocks of spec §7, on a new stock tab.**
  `GET /api/stock/{ticker}/fundamentals` + `models/fundamentals.py` +
  `fundamentals/card.py` (pure assembly) + `web/components/stock/tabs/FundamentalsTab.tsx`.
  Three of §7's nine blocks have backing data at stage 2 — subscores/composite,
  coverage, and provenance — and the other six are **absent from the contract
  rather than served empty**, since an empty block reads as "no data for this
  name" instead of "not built yet". Anchors, narrative and audit verdicts need
  stages 3-5.
- **A flagged provider field now suppresses exactly the derived features that
  consume it**, via a new `FEATURE_INPUTS` map and `violated_fields()` joined
  through `fundamental_scores.source_obs_ids`. CEG's `gross_margin` renders `na`
  while its `op_margin` survives intact — blanking the whole income statement
  over one bad field would be as wrong as showing it. The stored feature value is
  **never edited**: changing `features.py` would change validated math and break
  the reproducibility of every published result, so suppression happens at the
  read and the raw value stays as computed.
- **The card claims no direction for three of the seven features.**
  `gross_margin` and `op_margin` measured _inverted_ in the 2026-08-12 validation
  and `roe` is named by no rubric row, so `direction` is carried per feature in
  the API contract and is `null` for those three. It rides with the data rather
  than living in the UI, where a colour ramp could silently reassert a direction
  the research refused. No red/green scale and no bars: both encode a comparison,
  and a per-ticker card has no cross-section to compare against.
- Coverage reports "not reported" and "reported but not believed" as **separate**
  lists — different facts about a company — and the card dates itself by
  `knowledge_date`, never the `as_of` cross-section bucket.
- **Stage-2 fundamental scoring — subscores, composite, and method versioning**
  (migration `117`). `fundamental_method_versions` / `_params` / `_state` plus
  `fundamental_scores`, keyed `(ticker, as_of, engine_version, inputs_hash)`.
  New `fundamentals/scoring.py`, `storage/fundamental_scores.py`,
  `worker/jobs/fundamental_scoring.py`, `scripts/seed_fundamental_method.py`.
  Local run: **84 cross-sections, 20,552 scores, 257 names**, idempotent on
  re-run (0 inserted). Median cross-section width **249 of 257** — the
  knowledge-quarter keying holds, against the median of 23 the old
  fiscal-period bug produced.
- **All validated math moved into `src/uw_scan/fundamentals/`** — feature
  derivation, `zscore` and `composite_scores` now live in production and the
  research scripts import them, so the shipped composite _is_ the validated one
  rather than a copy that can drift. Verified by re-running the wide validation
  after each move and confirming `validation_wide.json` byte-identical (three
  times).
- **"Exactly one active method version" is enforced by three mechanisms**, because
  `CHECK (singleton_id = 1)` constrains the row's _value_, not its _existence_ — it
  permits `DELETE`, which would leave every computation method-less. A NOT NULL FK
  removes the null case, the CHECK pins identity, and a `BEFORE DELETE` trigger
  removes the empty case. Verified live: the delete raises.
- `inputs_hash` covers `company_type` and the engine version, not just the
  financial figures — otherwise a type flip yields new scores under an unchanged
  hash and the stale row survives, indistinguishable from the fresh one. It also
  distinguishes a missing input from a reported zero.
- **Observed, not fixed: the composite's extremes are denominator artifacts.**
  The ranking's ends are dominated by small biotechs and REITs (ALGN +4.25,
  CLDX −5.22) where a tiny EBITDA or asset base makes a ratio explode. This is
  the likely mechanism behind "extremes sort volatility, not quality".
  Winsorizing would fix it _and_ would make the shipped composite a different,
  unvalidated one — so it is documented rather than silently changed.

- **Fundamental tier-1 ingest — immutable point-in-time statement observations**
  (migration `114`). New `uw_scan.fundamentals` pure-compute package
  (`statements.py`: normalization, `content_hash`, integrity checks), storage
  domain `storage/fundamental_obs.py`, job `worker/jobs/fundamental_ingest.py`,
  seeder `scripts/seed_fundamental_universe.py`, runner
  `scripts/backfill/fundamental_ingest_backfill.py`, and four UW statement
  endpoints registered in `api/endpoints.py`. An unchanged refetch bumps
  `last_seen_at` and writes no fact; a restatement lands beside the original and
  never overwrites it. Verified against the live API: a second run of the same
  three tickers reported **0 inserted / 744 unchanged**.
- **`content_hash` excludes provider ingest timestamps, and this is load-bearing.**
  Every UW statement row carries `inserted_at` / `updated_at`, both of which move
  on provider re-ingest with no reported figure changing. Hashing them would turn
  every refresh into a phantom restatement — 60,292 rows of them per pass.
  Replayed over the full cached corpus: 60,292 rows, **zero identity collisions**.
- **Two-tier fundamental universe, so the ranked composite ships rather than being
  dropped** (spec §4.3 rev 5). `core` (25 names) sizes the hand-verified valuation
  and narrative stages; `ranked` (257) sizes statement ingest and scoring — the
  width at which rev 4 measured the composite (IC 0.039 leak-free, t 2.67). Rev 4
  concluded the product should drop the ranking; the measurement actually named a
  threshold argon can meet, so the ordering is **scoped** to the wide tier instead.
  Tier keys deliberately carry no count: the 245 came from local lake price depth,
  which statement ingest never reads.
- `core ⊂ ranked` is verified rather than assumed, and the check paid off — **12 of
  25 core names are absent from the validated panel** (AMD, ANET, APP, AVGO, CEG,
  CRWD, DELL, GEV, NOW, PLTR, VRT, VST). None were rejected on fundamentals: the
  lake mirror starts late for them (AMD 2015-01-02, AVGO 2016-02-02) against a
  `first_bar <= 2013-01-01` gate, though AMD has traded since 1972. Seeded, and
  flagged per row as outside the validated panel.

### Fixed (spec accuracy)

- **The violation rates in spec §4.4 were massive's, not UW's.** §3.3 measured
  ~5% negative liabilities and ~15% impossible share counts against massive
  `/vX`; the backbone then moved to UW, where §3.2's own probe records 0.0% on
  that axis, but the table description kept the old numbers. Replayed over 20,093
  real UW balance rows: both fire on **zero**. What actually fires is
  `implausible_share_count` (83 rows) and `accounting_identity_reversed` (61).
- **Registering the zero-rate checks anyway paid off on the first live run.**
  `negative_total_liabilities` measured 0.0% on the validated panel, was kept as
  a tripwire, and then caught four rows the panel could not have shown: DELL
  2014/2015 (−4.01bn, −2.90bn) and PLTR 2019/2020 (−508m, −147m) — all **pre-IPO
  periods** for names outside the panel (DELL private from 2013, PLTR listed
  2020). The panel measurement was scoped, not wrong; a check retired for
  measuring zero would have passed these silently.
- **`assets > liabilities + equity` is deliberately not a check**, documented
  because it looks like one. It fires on 14.4% of rows, but 2,815 of 2,876
  failures run in that single direction and cluster per filer — 121 of 245
  tickers fail on nearly every row and 124 on none, led by DIS, AES, CMI, BXP.
  That is UW reporting equity parent-only, excluding non-controlling interest.
  A check there would mark half the universe broken while its data is fine.

### Fixed

- **Dead duplicate method on `Repository`.** `_VrpTradingMixin` carried its own
  copy of `fetch_distinct_vrp_tickers`, but `_CorporateActionsMixin` sits at MRO
  position 3 versus 31, so all 11 callers resolved to the corporate-actions
  version and the trading copy never ran. Both bodies issued identical SQL, so
  nothing was broken — but any future edit to the losing copy would have been a
  silent no-op. Removed the dead copy and added
  `tests/unit/storage/test_repository_mixin_collisions.py`, which fails if any
  two of the ~34 mixins ever define the same name again.

### Changed

- **Stock-history rollup builder deduplicated** into
  `src/uw_scan/reports/stock_history.py`. `api/routers/stock.py` and
  `api/routers/trade_insights.py` each carried a byte-identical `_build_curve`
  plus history-row loop, which meant the `net_dex=None` placeholder had to be
  fixed in two places. Both routers now call one
  `build_stock_history_response()`; responses are unchanged. Also corrects the
  stale `stock.py:75` file/line citation in
  `docs/research/six-dimension-matrix/08-implementation-gaps.md` (that line has
  been the report cache since well before this change).

## [0.11.4] — 2026-08-10

### Added

- **Many-to-many industry-chain membership for the watchlist.** New table
  `uw_scan.watchlist_chain` (migration `113`) plus
  `src/uw_scan/watchlist_taxonomy.py` as the single source of truth for the
  9-layer / 38-chain taxonomy. `watchlist.sector` is unchanged and keeps its
  job — it is still the ticker's one PRIMARY tag and decides which section a
  card renders under; the join table carries the full membership set that
  FILTERING selects on. Both exist because a single column cannot express the
  taxonomy: NVDA is genuinely in `Computer/GPU`, `M7` _and_
  `Foundation-Model-Proxy`, ARM is in three L1 chains, IBM is in both
  `Cloud/Hyperscaler` and `Quantum`. The visible symptom was
  `Foundation-Model-Proxy` reading as **empty** on the dashboard while all five
  of its members sat on the page tagged `M7` — the whole Model & Tooling layer
  was unreachable. Keeping `sector` as the display tag is what stops a naive
  many-to-many render from drawing NVDA's card three times and ARM's three
  times (~114 tickers becoming ~150 cards for the same names).
- **`GET /api/watchlist/chains`** — every chain with its layer and live member
  count. `GET /api/watchlist` gains a `chain=` filter that selects on
  membership, so a ticker in several chains matches each of them, and
  `WatchlistCard` gains a `chains: list[str]` field.
- **59 tickers added to the watchlist**, screened market-wide by option
  liquidity rather than hand-listed. This is what surfaced `FRMI` (968k OI) and
  `KEEL` (1,076k OI) for `DC-REIT/Colo`, a chain that had read as empty only
  because the hand-authored list was EQIX/DLR/IRM/AMT.

### Changed

- **The watchlist filter rail is served, not hardcoded.** `sectorGroups.ts` now
  holds only rail ordering and short labels and builds itself from
  `/api/watchlist/chains`; copying 38 chain names into TypeScript would have
  recreated exactly the drift the taxonomy module exists to remove. Chains with
  zero members are dropped — a rail button that filters to an empty grid is
  worse than one that is not there. Filtering moved from `?sector=` to
  `?chain=`.
- **UW pool ceilings rebalanced** (mini `.env`): live `80000` → `60000`,
  research `30000` → `45000`. The two now sum to `UW_TOTAL_DAILY_GUARD`
  (105000), so the account-wide guard stays the binding constraint instead of
  the pools being able to over-allocate against it. Measured weekday burn
  before the adds was live ~38.4k / research ~24.9k, i.e. research sat at 83% of
  its ceiling while live used 48% of its own.

## [0.11.3] — 2026-08-09

### Added

- **Preserved three research traces that existed only on one disk (research).**
  No runtime change — docs and standalone scripts, nothing in `uw_scan` imports
  them.
  **GARCH as the VRP realized-vol leg — tested, REJECTED.** GARCH beats `rv21` on
  QLIKE/RMSE but carries a **+2.46 vol-point structural level bias** whose sign
  tracks the regime (corr with annual realized vol **−0.85**). Since
  `vrp = iv − rv` that bias lands on the traded quantity and inverts the timing:
  over the IV window SPX's true realized premium was **+3.14** vol points, `rv21`
  measured **+2.87**, and GARCH would have measured **+0.14** — "no premium, do
  not sell" across a period that paid 3.1 points, shutting off the SPX bull put
  spread that currently works. EWMA(0.94) is the one shippable alternative
  (MAE −7.4%) and is **not** shipped here.
  **Regime flip-rate probe** — measures whether CRI/VCG states chatter enough to
  justify a debouncer _before_ building one. EOD is quiet (CRI 3.5 flips/mo, VCG
  2.2); live intraday is not (VCG 45.3 flips/mo, 22% whipsaw).
  **Adaptive-EMA catalog** — 7 causal smoothers transcribed from a source article
  that claimed 17; the unimplemented 10 are listed by name under
  `NOT_IMPLEMENTED` rather than invented. Three of the source's own snippets used
  full-sample or backfilled statistics while asserting causality, so every filter
  here is re-derived strictly causal.
  Also preserves the **sector-crowding panel plan**, whose blocking prerequisite
  (mixed-unit `aum` normalization, wrong by 1e9 for the 12 SPDR sector ETFs) is
  recorded so it is not rediscovered.
- **Industry-chain taxonomy candidate screen (research).**
  `scripts/research/watchlist_chain_candidates.py` +
  `docs/research/2026-08-09-watchlist-industry-chains/` map the AI industrial
  chain onto 5 layers / 25 chains and screen candidates against the UW stock
  screener (`/api/screener/stocks`) rather than from recall — which killed four
  names that would otherwise have been recommended. Selection keys on **option
  activity, not market cap**: cap is a $2B junk floor only, because a $10B floor
  would delete most of AI-Cloud/NeoCloud and all of AI-Native-Software, the
  chains the taxonomy exists to reach. Membership is deliberately many-to-many
  (ARM sits in three chains); UW bills per distinct ticker, so extra memberships
  cost nothing. Result: 110 memberships over 96 distinct tickers, of which 45 are
  new (**+10.8k UW calls/day**, research pool ~27.0k/30k). **Research artifact —
  no watchlist rows are added by this PR.**

### Changed

- **Watchlist filter bar rebuilt as a two-row layer rail (web).** The old bar
  rendered one chip row per sector group, so its height grew with the tag count —
  20 tags already cost 5 rows, and the industry-chain taxonomy above would push
  it to ~10. It is now a fixed **two rows at any tag count**: a group rail
  (`ALL │ INDEX M7 │ CHIP CLOUD DC APP │ THEMATIC DEFENSIVE`) over a contextual
  chain row. Rail order leads with Index & Macro and M7 — the top-of-session read
  — before drilling into a chain. Colour and underline are independent channels:
  colour marks the group holding the active filter, the underline marks the chain
  row on screen, so you can browse one layer while filtered on another. Clicking a
  layer opens its chains **without** applying a filter; `M7` is a leaf and filters
  directly. `Setup` moved into row 2's right side, which keeps that row non-empty
  so the bar never changes height and the grid below never jumps.
  `SECTOR_ROWS` became `SECTOR_GROUPS` (`SECTOR_ROWS` is still derived), so
  `AddTickerDialog` picks up the finer grouping with no change. No API, schema, or
  contract change — `?sector=` still carries a single tag.
  The **Model & Tooling** layer is deliberately absent from the rail: its
  best-covered chain (`Foundation-Model-Proxy`) is 5/5 already on the watchlist
  but tagged `M7`, and `watchlist.sector` is a single column, so the button would
  filter to an empty grid despite the data being present. It lands with the chain
  migration.

## [0.11.2] — 2026-08-09

### Added

- **SVI residual net-of-cost verdict — the trade dies _before_ the cost line, not at
  it (research).** `residual-edge-test.md` (#219) closed the surface-mispricing question
  with "~\$0.18/contract, smaller than one commission" — a **100× unit error**: a
  per-share vega multiplied by a vol-point edge, then compared against a _per-contract_
  commission. Correct figure is **\$18.08**. Confirmed both by reproducing their
  arithmetic and by reading the grid's actual `call_vega` for the same SPY contract
  (0.8372). The verdict was right by accident, which is worth nothing — it would have
  flipped the moment anyone re-ran the sum.
  `scripts/research/svi_residual_net_of_cost.py` builds the position the original test
  never built: a defined-risk vertical, two hedge-selection variants, **43,261 trades**
  over 6 liquid names, 2025-12-26 → 2026-08-07, zero UW/IB calls. The faithful
  "fade-the-mispricing" structure is **negative gross in 8 of 9 configs at zero assumed
  spread** (hit rate 0.41–0.45) — no cost assumption clears it. The residual-paired
  variant looks profitable (+\$52.49/spread) but its **vol-only component is −\$50.76**;
  the profit is delta, harvested from median-width-20 spreads over a rising tape.
  Restricted to _credit_ spreads where theta is a tailwind it is still −\$15.30
  (n=13,056), so it is convergence failing, not decay. Verdict **unchanged — do not build
  the residual→signal layer** — but its reasoning is replaced: costs were never the
  binding constraint.
  `scripts/research/svi_residual_spread_anchor.py` measures the real spread from banked
  IB NBBO (`vrp_macro_entry_quote`): SPX median **0.072 vol pts**, near-money 0.066 —
  confirming the original test's 0.06 vp figure. Its vol-point work was sound; only the
  dollar paragraph was wrong. Historical per-strike spreads are otherwise unrecoverable
  (the grid carries no bid/ask, UW 403s past ~30 days), which is why the deliverable is a
  break-even curve rather than a point Sharpe.
  `CONTRACT_MULTIPLIER = 100` is now a named constant pinned by test, alongside a
  regression test for the capital-normalization bug found mid-build (normalizing by
  `max_loss` let a cents-sized debit spread post a four-figure return and invert Sharpe
  against its own dollar P&L). Audited for blast radius: the shipped VRP modules
  (`vrp_capital_account.py`, `vrp_robustness.py`) already apply the multiplier correctly
  — the error never left the research doc. Docs:
  `docs/research/svi-surface-fit/net-of-cost-verdict.md`, with correction annotations on
  `residual-edge-test.md` and `README.md`.

- **Technicals "Magnet View" sub-tab** — reference-style chart with ZigZag pivots,
  five magnet levels, and an options-implied cone at 5/10/21d whose bands are
  labelled with measured (not nominal) confidence **and its 95% interval**. The
  0.618 extension renders as unlabelled geometry: it was tested against a matched
  null at five ZigZag thresholds (938 legs at the loosest) and showed no edge, so
  nothing on the view asserts price will reach it. Three deliberate deviations from
  the reference: pivot markers are filled arrows (lightweight-charts v5 has no
  hollow-triangle shape), the decorative scenario fan is replaced by the cone
  rather than drawn alongside it, and the right-edge divider therefore reads
  `history ← | → options-implied` rather than naming scenarios that are not drawn.
  Research: `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md`.
- **`dots` render mode for the volume profile** (`lib/lwc/volumeProfile.ts`) — the
  magnet view's jittered dot cloud, with the last 15 sessions in gold. `VpBin`
  gains a `recent` field for that subset. The mode defaults to `"bars"`, so the
  Price view's profile is unchanged. The cloud matches the reference's geometry:
  it sits in the **right-edge projection zone** beside the cone (translucent, so
  both read), every row grows **rightward from a flat left base** so the tips fan
  right, and the ★ POC label sits just past the longest tip. `anchor` therefore
  chooses only WHERE the band sits, never which way the dots run.
  A new `edgeGutterPx` (default 0) holds space clear at the anchor edge; the
  magnet view sets 150 because lightweight-charts pins `createPriceLine({title})`
  labels INSIDE the pane at its right edge, and without the gutter the tips and
  the ★ chip render underneath `RESISTANCE`/`SUPPORT` and vanish outright.
  `widthFrac` is 0.085 for this view — the reference's own proportion; at the
  previous 0.16 the gutter-shifted band reached back over a month of candles.
  Jitter is a deterministic sin-hash of (bin, dot) — never `Math.random`, so the
  cloud does not shimmer on pan or re-render.
- **Per-tile charts under the magnet view** — VOLUME (direction-coloured bars over
  a dashed 20d MA), RSI 14 (line over fixed 0–100 with the 30/70 regime zones),
  MOMENTUM (fast MACD histogram as a signed area to zero, slow 55/89/34 dashed
  behind it, with a `v %/d · a %/d²` kinematics caption — spec §1.1 layer 6,
  descriptive only: no ACCEL/DECEL verdict is printed because that would need
  thresholds the reference never validated), and ATM IV (filled level chart).
  Hand-rolled SVG; math extracted to `lib/magnetTiles.ts` and unit-tested for the
  degenerate cases that render as _nothing_ rather than throwing (NaN in an SVG
  `d`, zero-width domain, `Math.pow` of a negative base).
- **`MagnetsResponse.atm_iv_30d_series`** — ATM 30d IV per captured session, from
  the same `atm_iv_at_horizon(curve, 30)` that produces the headline `atm_iv_30d`,
  so the tile's line and its number cannot disagree. The route now loads 90 grid
  sessions instead of 6; measured on the dev DB (NVDA) that is 14.2 ms vs 7.0 ms —
  the chain scan dominates, not the VALUES join the old comment feared. Sessions
  with no captured surface are **omitted**, never carried forward: a flat segment
  across a capture gap would read as "IV held steady".

### Changed

- **Magnet view adopts the house panel chrome** — the chart, levels table, and THE
  READ now sit in `AnalyticalSeriesPanel` frames matching the Price view, with a
  crosshair OHLC readout in the same format. Candles moved to the shared
  `--positive`/`--negative` tokens; the five **level** colours stay on the
  reference palette per spec §5.1, where hue identifies a level's role. The panel
  subtitle now names the source table and date (`daily_ohlc · YYYY-MM-DD`), which
  is a stronger disclosure than the bare date it replaces — this sub-tab reads
  `daily_ohlc` while the rest of the tab reads `technical_daily`, and the two
  diverge.

### Fixed

- **`history ← | → options-implied` divider now lands on the last bar.** It was a
  single centred string, so the split fell on the string's midpoint rather than the
  `|` glyph — 33 px left of the bar, because `history ← ` is 10 characters and
  ` → options-implied` is 18. It is now a zero-width marker with a caption hung off
  each edge, so the gap itself is what `timeToCoordinate` positions.

- **Corporate-action and calendar-gap guards for `daily_ohlc`-derived research**
  (`reports/magnet_data.py`). Unadjusted splits (CRWD 4:1, KORU 20:1) and a ticker
  reuse (SPCX) were inflating `std(z)` to 1.116 with excess kurtosis 361.

## [0.11.1] — 2026-08-02

### Fixed

- **Gamma flip is now distance-guarded, not drawn unconditionally** — `gamma_levels.py`
  exempted `gamma_flip` from the side-guard on purpose (it legitimately sits either side
  of spot), which left it with _no_ guard. Probing UW's `/gex-levels` for SPX over eight
  sessions on 2026-08-02 returned `gamma_flip` null on six and 8109.8 / 8156.26 on the
  other two — both ~8–9% above a ~7450–7490 spot, both non-round where every sibling
  field is a listed strike, and both contradicting UW's own positive-gamma ("dampening")
  regime badge on the same screen. `apply_flip_guard` now drops a flip further than
  `FLIP_MAX_DISTANCE_PCT` (5%, a judgement call — see the constant) from spot and names
  it in `dropped`. A flip that was never offered is not reported as dropped. The chart's
  disclosure note changes from "wrong side of spot" to the cause-agnostic "implausible vs
  spot", since two different guards now feed `dropped`.

- **SPX dealer levels on the density cone were fabricated by argon, not sourced from
  UW** — `gex_levels_capture` swept only the active watchlist, and SPX is deliberately
  _not_ a watchlist ticker (a slot there costs a full per-ticker UW burn). So
  `uw_gex_levels_daily` held 114 tickers / 79k rows / **zero SPX**, `fetch_uw_gamma_levels`
  returned None, and `resolve_levels` fell through to the `gex_snapshots` fallback —
  argon's own unconstrained argmax, which `reports/gamma_levels.py` documents as
  untrustworthy. Measured 2026-08-02 at spot 7489.72: the chart drew put wall **7000**
  and γ flip **7475** where UW reports **7485** and **8156.26**. Two of the three overlay
  lines were wrong. The capture now sweeps the watchlist ∪ `settings.gex_scan_tickers`
  (the index scope the intraday GEX scanner already maintains), which adds exactly one
  name — SPX — for +1 UW call/night. The other four alpha captures stay watchlist-only.
  Nothing flagged this because `/api/health` freshness scopes coverage to the _active_
  watchlist, so an off-watchlist ticker reads as 100% covered; that blind spot is
  unchanged and is worth a separate look.

### Changed

- **SPX density cone readability pass (Regime → Market Compass)** — six display-only
  tweaks, no change to the model, the API, or any persisted value:
  - the recon strip now sits in a `.section` container with its own header, matching
    the Gamma Exposure panel chrome instead of floating on the page background;
  - the next-session density silhouette is anchored flush to the right price axis and
    grows leftward (volume-profile idiom) rather than hanging off the h=1 date;
  - the 1–5 day fan renders at the same price-range-per-pixel as the next-session
    view by growing its pane (capped at 620 px), so the shared candles are the same
    size in both — previously the fan squashed them into the same 360 px;
  - the fan's `rightOffset` drops 2 → 0, closing the dead gap at the right axis;
  - the next-session view gains dashed PROJ HIGH / PROJ LOW levels with axis labels
    and a dot on the anchor close;
  - the cone bands move off `--accent-vol` purple onto `--positive` teal (chart,
    legend swatches, and mini-cone strip).

## [0.11.0] — 2026-08-02

### Added

- **SPX 1–5 day conditional density cone on Regime → Market Compass** — signal-lab's
  v13 GJR-GARCH(1,1,1) short-horizon density model (run
  `2026-08-01-spx-density-v13`, verdict **PASS**) ported into argon as a
  **display-only** fan chart plus a prospective shadow log. The numeric core
  (~370 lines: constants, the standardised-residual block-bootstrap cone, the v8
  multi-start estimator, the arm registry) is vendored **byte-identical** from
  signal-lab @ `0f893513` into `src/uw_scan/density/`; `arch` is pinned to exactly
  `8.0.0` and `ruff format` is `force-exclude`d from those three modules so no
  tool can rewrite a vendored line. Fidelity is enforced by a **golden parity
  test** in CI (`tests/unit/density/test_parity_golden.py`): it replays the
  committed 2026-07-30 forward run offline — `panel.parquet` plus the four
  post-panel bars recorded in the artifact reconstruct the exact 4,240-return
  input. The panel index, the seed derived from it, the digest, and every date and
  label are asserted **exactly**; the float chain is bounded at 1e-6 relative.
  That split is deliberate: the fitted parameters reproduce bit-identically on the
  platform the research ran on (macOS/arm64) but not across architectures — on
  Linux/x86-64 the iterative maximum-likelihood fit converges to a marginally
  different stationary point (1.1e-7 relative on `omega`; 1 ULP on the analytic
  EWMA path). The bound sits six-plus orders of magnitude below any structural
  port error, and each run prints the worst observed delta so creep is visible.
  The EWMA fallback branch is
  pinned against a fixture generated from signal-lab's _unvendored_ source, so a
  vendoring error cannot self-certify.
- Nightly two-pass job at **03:30 ET Tue–Sat on massive-0** (after
  `vol_index_lake_sync` at 03:15): pass 1 settles any row whose H-th subsequent
  trading day has closed, pass 2 issues today's cone — settle-first, so an issue
  failure never blocks outcome recording. Zero UW/IB spend; reads
  `vol_index_daily` only. Gated `UW_SCAN_SPX_DENSITY_ENABLED`, **default off**.
- New table `uw_scan.spx_density_forecast` (migration `111`), enrolled in both the
  freshness monitor and the gap-healer registry. Read-only routes
  `GET /api/regime/spx-density` and `/spx-density/issued`, rendering a headline
  cone plus a 5-up strip of previously issued cones with IN/OUT badges and
  80%-band hit-rate tallies split prospective vs reconstructed (the latter is
  in-sample by construction and is labelled as such).
- **The panel-index alignment rail** — `seed_for(i)` is arithmetic on the frozen
  panel's index, and argon's SPX history starts in 1975 versus the panel's
  2009-09-18, so feeding the full series would silently change every seed and
  every bootstrap draw with no error. `compute_forecast` anchors at
  `PANEL_FIRST_DATE` and requires positional **date** equality _and_ exact close
  equality across the whole panel window before it will publish; either failing
  raises `PanelMismatchError` and the job records `error: panel_mismatch` rather
  than drawing a cone.
- Committed research trace `docs/research/spx-density-cone/refit_staleness.json`
  (reproduce: `uv run python scripts/research/spx_density_refit_staleness.py`):
  63-day-old parameters move the 80% band by at most **0.77 bp** on a 240–510 bp
  band, so the daily refit is a cheap convenience rather than a requirement.
- Backfill `scripts/backfill/spx_density_backfill.py --sessions N` seeds
  `origin='reconstructed'` history through the same `compute_forecast` path. The
  rail validates over the overlap rather than demanding the full panel window, so
  an `as_of` _inside_ the panel is a legitimate rewind — the prefix still starts at
  panel row 0, so the index (and therefore the seed) is unchanged. The
  "shorter than the panel" refusal is scoped to live runs, where a short series
  means a stale mirror rather than a deliberate rewind.
- **The cone renders on lightweight-charts, with candles and two views.** The
  hand-rolled SVG is replaced by `components/regime/DensityConeChart.tsx` — the
  second documented exception to the no-chart-library rule (after the Technicals
  price pane), taken because the panel needs a real dated x-axis, OHLC
  candlesticks, and price-line overlays that `lib/svgChart.ts` does not provide.
  It reuses the vendored `lib/lwc/bandsIndicator.ts` for the cone and adds
  `lib/lwc/densityProfile.ts`, a small primitive that draws the simulated
  distribution as a filled silhouette. **1–5 day fan** (default) shows the
  widening cone against the EWMA baseline; **Next session** shows the incoming
  session alone as nested probability blocks plus its density. The frame is fixed
  — scroll and zoom are off — so the window is a composition rather than
  something to navigate. Legend labels quote the **actual** persisted spans
  (90% = q05–q95, 80% = q10–q90, 50% = q25–q75) and are deliberately not
  relabelled to the more familiar 95/68/50 of a Gaussian chart, which would claim
  coverage v13 never validated.
- **Per-horizon simulated density is now persisted** (migration `112`,
  `spx_density_forecast.density_bins_jsonb`): a 64-bin histogram of the same
  10,000 Monte-Carlo draws the quantiles come from, taken straight off
  `Cone.samples`, which the vendored code already carried for signal-lab's own
  CRPS/PIT metrics. Purely additive read-out — it cannot move a quantile, and the
  parity gate is untouched. A test integrates the histogram up to each published
  quantile and asserts the mass landing there matches that quantile's
  probability, so a future refactor cannot quietly histogram a _different_
  simulation. Nullable: cones issued before `112` render bands only.
  `spx_density_backfill.py --force` repopulates existing rows.
- **Dealer levels on the chart, with a side-guard** — call wall, put wall and
  gamma flip drawn as price lines, resolved by `reports/gamma_levels.py` from
  `uw_gex_levels_daily` (UW's own, primary) falling back to `gex_snapshots`.
  Argon's own wall computation (`cards/gex.py`) takes a plain argmax over all
  strikes with **no constraint that the call wall sit above spot**; on SPX
  2026-07-23…07-28 that produced `call_wall == put_wall == 7000` against a 7,383
  spot. A "resistance" line below spot is a false statement, not a weak one, so a
  wall on the wrong side of spot is dropped and named in `dropped` rather than
  drawn. Gamma flip is exempt — it legitimately sits either side. The root cause
  in `cards/gex.py` is left alone here on purpose: it feeds the GEX tab, the
  cockpit, `dealer_regime` and the AI prompt payloads, so changing its numbers is
  a far wider blast radius than a chart overlay.
- `GET /api/regime/spx-density` now returns OHLC on `recent_path` (nullable —
  `vol_index_daily` carries close-only rows, and those sessions are dropped from
  the candle series rather than having a bar manufactured from the close), plus
  `gamma_levels` and per-horizon `density`.
- **Four bounds the review pass added, each closing a way the panel could state
  something it had not checked.** (1) `vol_index_daily.close` is nullable, and a
  NULL arrives as NaN — which would sail straight _through_ the alignment rail,
  because the max disagreement becomes NaN and `NaN > 0` is `False`. A series
  with a hole in it would have passed the "exact agreement" check that a
  one-cent error fails, then been fitted under the same index and seed as a
  different model. Non-finite closes are now rejected before the rail runs.
  (2) Dealer levels carry `LEVELS_MAX_AGE_DAYS = 7` and the side-guard now
  measures against the price the chart is actually drawn at, not the level row's
  own spot — an unbounded `market_date <= as_of` lookback would happily draw
  walls from a session months old, and the guard would not catch them because
  they are consistent with _that_ session's spot. (3) The backfill refuses to
  touch any session the nightly job issued prospectively, even under `--force`:
  `upsert_rows` updates `origin` on conflict, so a recompute would relabel a
  genuinely out-of-sample cone as reconstructed and quietly inflate the only
  honest hit-rate number on the page. (4) Cone horizons at or before the last
  real bar are dropped rather than drawn over sessions whose outcome is already
  known, which also removes the duplicate `target_date` the settle pass can
  produce when a holiday falls inside the window — lightweight-charts asserts
  strictly ascending times only in its _development_ bundle, so in production a
  duplicate renders a degenerate series instead of failing loudly.

### Changed

- **Regime tab `Market Tide` renamed `Market Compass`**, and the density cone now
  leads the tab ahead of the tide charts. The tab id stays `tide`, so
  `/regime/tide` deep links keep working. The cone also moved out of the market
  tide section body: it had been nested inside that section's loading branch, so
  an unrelated slow tide fetch blanked it, and the "Market Tide" heading claimed
  a panel that is not market tide. It now carries its own
  `.section` / `.section-header` / `.section-body` chrome, matching the Gamma
  Exposure tab — the body padding is repeated on the panel rather than inherited
  because `.section-body` ships `padding: 0` and each panel opts in.

## [0.10.18] — 2026-07-29

### Added

- **`option_surface_research_catchup` — the cohort's history fills itself** —
  new job at **03:20 ET weekdays on uw-0**. The 19:10 capture only writes
  _tonight_; a freshly-seeded cohort therefore starts with an empty past while
  UW's ~180-day window decays out from under it at a day per day. This walks that
  window and fills what is missing, ≤`OPTION_SURFACE_RESEARCH_CATCHUP_MAX_CALLS`
  (default 1500) per night — ~6 nights for the 37-name cohort — then finds no
  gaps and spends nothing forever after. Resumable by construction: it recomputes
  the missing set each run, so stopping early is free. Runs post-20:00-ET reset
  against a fresh counter and **is** gated on `_research_budget_ok`, unlike the
  durable evening captures: a deferred catch-up batch is still fetchable
  tomorrow, an uncaptured night never is. Gated
  `OPTION_SURFACE_RESEARCH_CATCHUP_ENABLED` (default on; self-gates on an empty
  cohort). `scripts/research/option_surface_research_backfill.py` now shares the
  same core (`weekly_sessions` / `missing_pairs` / `fill_pairs`) rather than
  keeping its own copy, so the manual and scheduled paths cannot drift.

  **Why not just add the cohort to the watchlist,** which would get the existing
  data-gap healer to backfill it with no new code: the healer's denominator is
  "watchlist tickers × sessions" and it fetches the **full chain every session**
  (~17 calls/ticker-session), against this job's weekly ≤60-DTE sample (~8.6) —
  **~78,600 calls versus ~7,950**. Watchlist membership would also enlist all 37
  names in every per-ticker job permanently, ~+32% daily burn on a ~114-name
  watchlist, to buy a one-time fill. The healer is right to be exhaustive; that
  is its job. The cohort table exists so research sampling cannot silently
  promote itself to production completeness.

- **Research ticker cohorts + nightly capture for them** — migration `110` adds
  `uw_scan.research_universe` (cohort / ticker / sector / marketcap / option_oi,
  point-in-time tagged). Deliberately **not** the watchlist: watchlist membership
  enlists a ticker in every per-ticker job and permanently raises daily UW burn,
  whereas a research cohort only needs to be iterable by its own capture and
  groupable by its tags in analysis SQL. New job
  `option_surface_research_capture` runs **19:10 ET weekdays on uw-0**, between
  the watchlist capture (19:00) and the IV canary (19:30) — sequential because
  both loops are UW `/greeks`-bound against a shared per-minute ceiling. Full
  chain, no DTE cap: `option_surface_grid_daily` accrues **forward only** and UW
  serves ~180 days, so an expiry not captured tonight is unrecoverable. ~680
  calls/night (~0.6% of the 120k budget). Gated
  `OPTION_SURFACE_RESEARCH_CAPTURE_ENABLED` (default on — the job **self-gates on
  the cohort being seeded**, so an un-seeded deployment spends nothing) and
  `OPTION_SURFACE_RESEARCH_COHORT`. Also adds an optional `max_dte` to
  `_build_ticker_rows` (default `None` = unchanged behaviour).
- **`liquid_sector_balanced_v1` cohort + historical backfill** —
  `scripts/research/option_surface_research_backfill.py` seeds 37 names across 10
  sectors and backfills them weekly over UW's ~180-day window (~7,950 calls;
  weekly because 30-day holds make consecutive daily entries ~95% overlapping).
  Selection required **both** marketcap ≥ $30B **and** option OI ≥ 200k: ranking
  by market cap alone produced untradeable chains (EQIX 18k OI vs a 657k
  watchlist median), while ranking by OI alone returned retail/meme names. Exists
  to answer a bias found in the loss-anatomy study — the watchlist is AI/semi
  heavy, and 79% of the measured strangle loss came from 31% of trades all
  expressing that one theme, with the remaining 54% of trades flat.
- **Theta Harvester short-strangle scanner** (radon port) as a third `/scanner`
  sub-tab, alongside the existing detector flow — which becomes the **Flow
  Signals** tab, with **Discover** split out as its own tab. Ranks 16-delta
  short strangles off the persisted warm store (`option_surface_grid_daily` +
  `greeks_by_expiry_strike` + OHLC) at **zero UW cost**; IB quoting is
  view-only, capped at 8 contracts, and advisory-locked. Migration `109` adds
  `theta_harvester_candidates` + `theta_harvester_markouts` (both registered
  with the gap healer + freshness monitor). Nightly scan 19:45 ET and markout
  19:55 ET on uw-0, gated `UW_SCAN_THETA_HARVESTER_ENABLED` (default on — the
  job only reads the warm store and writes its own two tables). API:
  `GET /scanner/theta-harvester`, `POST …/rescan`, `POST …/quote`.
- **Backfill + weight sweep tooling** —
  `scripts/backfill/theta_harvester_backfill.py` (145 sessions,
  2025-12-26 → 2026-07-27: 16,134 candidates / 23,721 marks) and
  `scripts/research/theta_harvester_weight_sweep.py` (291 configs, cross-
  sectional IC as the primary metric, plus an unconditional control arm).

  **The verdict is negative and the UI says so.** The score _orders_
  (IC +0.075, t 6.35) but the set it selects does not pay, and the control arm
  — every candidate, no score — lost money too (monthly mean −0.8%,
  Sharpe −1.67). This ships as a **research artifact, not a trade surface**:
  the structure is a naked short strangle, which violates Argon's
  defined-risk-only rule, and the sub-tab carries a permanent banner saying
  both. Full method and tables:
  `docs/research/2026-07-28-theta-harvester-weight-sweep.md`.

- **Loss anatomy + a matched condor-vs-strangle sweep** —
  `docs/research/2026-07-29-theta-harvester-loss-anatomy.md` and
  `scripts/research/theta_harvester_condor_sweep.py` /
  `docs/research/2026-07-29-theta-harvester-condor-vs-strangle.md`. Together
  they replace the aggregate "it lost money" verdict with a mechanism: the
  entire loss sits in the `>+30%` underlying-move bucket, it is the **call leg
  alone**, and 79% of it comes from the AI/semi complex (31% of trades) while
  the remaining 54% of trades are flat. On the standing-rule conflict, the
  condor sweep prices the fix rather than asserting it — matched samples at
  three wing widths with real wing costs from the grid put the cost of
  defined-risk compliance at **6–15 bp of spot per trade**; the verdict is
  _don't adopt the condor for P&L, do adopt it for defined risk_. The sweep
  script enforces four anti-trap rules in code (matched samples, Sharpe carries
  its standard error, the sample window is a reported metric, small predeclared
  grid) so radon's "Sharpe 2.23 over 3 months with a negative IC" trap cannot
  recur silently, and aborts if its recomputed P&L disagrees with the stored
  markout by more than 0.01.

### Fixed

- **Session spot resolution when `option_surface_grid_daily.underlying_spot` is
  NULL** — the column is unpopulated before 2026-06 (0% Dec–May, 13.8% June,
  97.3% July), and two loaders depended on it, so five of the seven backfilled
  months silently produced zero candidates. Spot now falls back to the OHLC
  close and ATM IV is selected against the resolved spot rather than the NULL
  column.
- **Corporate-action scale breaks between the back-adjusted `daily_ohlc` and
  the as-traded surface grid** now drop the affected rows instead of pricing
  against a mismatched scale — a 20-for-1 split put one ticker's adjusted close
  at ~$21 while its strikes still spanned 125–1900. Guarded at entry (strike-
  range containment) and at settlement (`MAX_SETTLEMENT_MOVE`).

## [0.10.17] — 2026-07-29

### Added

- **Calm-core band on the VCG z-score history chart** — `|z| < 0.75` shaded
  behind the bars. The chart previously drew only the ±2.0 / ±2.5 arming rules,
  which is the _weaker_ end of the evidence: the tails carry no directional
  signal (max |t| vs rest = 1.10 over 30 cells) and their forward-vol lift is
  crisis-driven, with a median of just +2.1pt. The calm core is the half that
  survived walk-forward, so the chart was loudest exactly where the evidence is
  thinnest and silent where it is strongest. Drawn as a band, not a rule — it
  is a standing condition, not an event — and labelled as a short-vol
  _permission condition on ~20-day holds_, not an entry trigger, because it
  reverses on 0.25Δ/30d. Regression-tested for presence, zero-centring, and
  being narrower than the ±2.0 rules; the test was confirmed to fail with the
  band removed.

### Changed

- **The VCG signal tooltip now states what the signal does _not_ do.** State
  names like `RISK-OFF` are positioning vocabulary and read as an instruction to
  cut equity; tested over 2007–2026 (n=4,758) armed days match baseline SPX
  returns. The tooltip now says the states describe coincident vol/credit stress
  and do not predict direction, while noting that elevated |z| does associate
  with higher forward realised vol. Copy only — no change to the cascade, the
  stored `interpretation` values, or the API.

### Removed

- **`spot_refresh_heartbeat_lag_seconds`** dropped from `/api/health`. The
  `spot_refresh` job was deleted in Phase 7 — the WS consumer became the sole
  intraday spot writer — but the health endpoint kept reading its heartbeat, so
  the field reported time-since-the-retired-job-last-ran: ~68 days and climbing
  by 2026-07. The `HealthPanel` "Massive Worker" fallback row it fed is gone
  too; that branch only renders when there are zero worker rows, so in any real
  deploy `workerGroupStatus(massiveWorkers)` was already the live signal. Live
  spot health remains `spot_quote_lag_seconds` + the `ws_consumer` block, both
  sub-second on the mini. **API contract change** — `types.ts` and the OpenAPI
  snapshot updated surgically alongside.

### Research

- **Is the VCG calm gate just a VIX filter?**
  (`docs/research/2026-07-29-vcg-vs-vix-walkforward.md`,
  `scripts/research/vrp_vcg_vs_vix_walkforward.py`) — **no**, and the reason is
  structural: `vcg` is already an OLS residual of credit on the vol complex, so
  it is near-orthogonal to the VIX level by construction (**ρ = −0.030**;
  per-fold OLS slope −0.002…−0.004). Regressing VIX out changes the result by
  0.01 Sharpe.
  - A trailing-252 VIX-percentile filter **does** work (beats `gate0` 3/4) but
    is beaten by the calm gate **4/4** — and wins its Sharpe by abstaining:
    76 trades vs 126, annual ROR **0.83 vs 1.31**. Sharpe rewards not losing,
    and not trading is the cheapest way not to lose.
  - Same harness, same folds, same universe across arms; VIX percentile ranked
    strictly _prior_ to each entry date so the cheap rival gets no look-ahead.

- **Walk-forward validation of the VCG calm gate**
  (`docs/research/2026-07-29-vrp-vcg-calm-gate-walkforward.md`,
  `scripts/research/vrp_vcg_calm_gate_walkforward.py`) — clears the bar the
  in-sample probe set for itself: the |z| threshold is re-fit from scratch on
  each expanding training window, then scored on the year that follows. Over
  14 OOS folds (2013–2026) the refit gate beats always-on **4/4** and `gate0`
  **3/4**, cutting maxDD by a mean 1.73× max-loss. It **reverses on 0.25Δ/30d**
  (1.07 vs 1.39), so the structural config is load-bearing and it is still not
  wired in.
  - Every one of the 14 windows independently picked |z| < 0.75 — a value the
    earlier probe never tested. That **supersedes the in-sample "the threshold
    is unstable" finding**, which was an artifact of comparing two hand-cut
    eras; the older doc now carries a note to that effect.
  - The per-window catastrophic-degradation gate fails **0/4 for every arm,
    including ungated always-on**, so on this book it is describing short vol
    as an asset class (2018Q1, 2020Q1) rather than indicting the candidate.
    Recorded rather than reported as a gate failure.
- **`docs/research/2026-07-29-vcg-spx-forward-returns.md`** — VCG z vs forward
  SPX over 4,758 sessions. Direction is dead: across 30 rule×horizon cells the
  largest |t vs rest| is 1.10, and armed days track baseline in both era halves.
  Forward _volatility_ does separate, most robustly in the calm core
  (|z| < 1, n=3,486, t = −2.72 vs rest). Repro:
  `scripts/research/vcg_spx_forward_returns.py`.
- **`docs/research/2026-07-29-vrp-vcg-calm-gate.md`** — does the calm core
  improve the VRP macro short-vol book? Reuses the committed sweep's P&L
  machinery, varying only the sizing function. `gate0_and_calm` beats `gate0`
  in 4/4 grid cells and cuts maxDD by ~1.5× max-loss, but beats plain always-on
  by only +0.03…+0.39 Sharpe and _loses_ outright in the 2007–2016 half; VCG
  alone is not a gate, and the |z| threshold's ranking flips between eras.
  **Verdict: promising, not proven — not wired in.** Deployment would require
  the walk-forward harness with the threshold re-fit per training window. Repro:
  `scripts/research/vrp_vcg_calm_gate_probe.py`.

## [0.10.16] — 2026-07-29

### Added

- **VCG z-score history chart** on `/regime` → VCG — signed bars plus a monotone
  curve over the trailing window, with 1M/3M/6M/1Y range buttons and the
  ±2.0 / ±2.5 arming thresholds drawn as rules. It plots `vcg` directly, which
  _is already_ the trailing 63-session z-score of the model residual, so the
  panel labels that definition rather than re-normalising an already-normalised
  series.
- **`pathFromPointsSmooth`** (`web/lib/svgChart.ts`) — Fritsch–Carlson monotone
  cubic interpolation. Deliberately not Catmull–Rom: on `[0, 0, 2, 0, 0]` a
  Catmull–Rom spline dips below zero either side of the spike, drawing a sign
  flip that is not in the data. On a signed regime chart that is a fabricated
  reading; the monotone limiter clamps tangents to the neighbouring samples'
  range at no visual cost.
- **`scripts/backfill/vcg_snapshot_backfill.py`** — scores `vcg_snapshots`
  (`basis='eod'`) across the full aligned lake history. VCG needs no external
  API (VIX/VVIX/credit-proxy all come from `vol_index_daily`), so the whole
  history backfills at zero UW cost. Depth is bounded by the shortest input:
  HYG starts 2007-04-11 and scoring needs 94 aligned bars of warmup.

### Fixed

- **`VolIndexRepository.fetch_history` now caps `as_of` in SQL** instead of
  filtering after the fact, and **all three scanners that consume it — VCG, CRI,
  and canary — are fixed together.** Each selected the most-recent `days` (or
  `days * 2`) rows and only then dropped everything after `as_of`, which anchors
  the fetch window to _today_ while anchoring the filter to _`as_of`_. Once
  `as_of` is further back than the window, every row is filtered out and the
  caller gets an empty series rather than an error: the scan reports "thin data"
  and skips, so a deep historical backfill runs to completion and writes
  nothing. This is what capped VCG backfills at ~600 sessions. CRI and canary
  had the identical copy-pasted bug — dormant only because their sole `as_of`
  caller (`recover_recent_gaps`) stays inside the `days * 2` fudge buffer.
  Regression tests cover all three and fail against the old code.

## [0.10.15] — 2026-07-28

### Changed

- **GEX profile is now a curvature field** on `/regime` → GEX. The horizontal
  divergent bar list is replaced by a strike-on-x line/area chart, filled and
  split at zero (teal above = stabilizing, magenta below = destabilizing), with
  spot and GEX-flip vertical rules and triangle markers for PUT/CALL WALL,
  ACCEL, and MAGNET strikes. A hover crosshair drives a
  `STRIKE / NET GEX / CURVATURE` readout that defaults to the strike nearest
  spot. **The stock Market Structure tab keeps its existing bar profile** — the
  bar form reads better per-ticker, where the question is "which strikes carry
  gamma" rather than "what shape is the field".
- **New signal — curvature** (`curvatureField`): the discrete second derivative
  of net GEX with respect to strike, computed client-side on the non-uniform
  strike grid (`2(h₂f₋₁ − (h₁+h₂)f₀ + h₁f₊₁)/(h₁h₂(h₁+h₂))`) and scaled by
  `h̄²/max|f|` so it is dimensionless and comparable across tickers. It reads
  where the gamma field bends — how fast dealer hedging pressure changes per
  point of spot.
- **Chart moved to `web/components/shared/GexCurvatureChart.tsx`** (git-moved
  from `components/regime/`, so history is preserved). The dead
  `uwGexRowsToBuckets` helper it carried — zero callers since the UW Analyze
  page it was extracted for — is deleted.

## [0.10.14] — 2026-07-26

### Changed

- **Technicals price pane, SMA mode:** the `±1.5σ around SMA200` envelope is
  replaced by a Keltner-style **ATR band** (`SMA20 ± 2·ATR14`, Wilder ATR
  computed client-side from OHLC). The old band was a slow-moving cloud price
  rarely interacted with; the ATR band tracks the tradable range. Toggle relabeled
  `SMA·σ` → `SMA·ATR`. EMA·BB mode is unchanged.
- **Price-band rendering now breaks on real data gaps** (`web/lib/lwc/bandsIndicator.ts`)
  instead of drawing a straight line across a warm-up window or a bar with
  missing OHLC — the custom canvas primitive previously connected every point
  in its array unconditionally. Applies to both SMA·ATR and EMA·BB bands.

## [0.10.13] — 2026-07-25

### Added

- **UW historical-alpha datasets** (`uw_gex_levels_daily`,
  `uw_volatility_signal_daily`, `uw_short_pressure_daily`,
  `uw_intraday_option_flow_bars`, `uw_dark_lit_flow_prints`) now have the full
  Argon lifecycle: fetchers + normalizers + storage, **recurring nightly capture**
  (5 jobs on uw-0 at 18:35–18:55 ET, gated by `UW_SCAN_UW_ALPHA_CAPTURE_ENABLED`,
  default off), **`data_gap_healer` self-healing** for the 3 daily tables +
  **freshness monitoring** for all 5, and a **resumable catch-up CLI**
  (`scripts/backfill/uw_alpha_catchup.py`) plus a one-shot runner
  (`scripts/backfill/uw_alpha_capture_once.py`). Migration 108. The four
  gex/volatility endpoints (`gex-levels`, `volatility/{anomaly,character,
variance-risk-premium}`) are real but were absent from the curated UW docs;
  their `?date=` as-of behaviour was verified empirically before wiring.
- The event logs key each print on `(source, tracking_id, executed_at, price,
size, volume)`: UW's `tracking_id` is an **order** id shared by distinct child
  fills, so a `tracking_id`-only key silently collapsed ~95% of lit prints and
  ~7% of darkpool prints. `volume` (cumulative session volume) is the discriminator.

## [0.10.12] — 2026-07-22

### Fixed

- **QQQ/IWM macro short-vol signal no longer skips every run.**
  `vrp_macro_drawdown._lake_spot` pointed pyarrow's directory-dataset reader
  at the whole `symbol=<TICKER>` lake directory instead of the explicit
  `1d.parquet` file. Sibling files in that directory (`1d.parquet.lock` and
  the 30m/5m timeframe parquets + their own `.lock` markers) made pyarrow
  choke on a zero-byte lock file with `ArrowInvalid`, silently starving
  QQQ since 2026-06-24 and IWM since 2026-07-08 (SPX was unaffected — its
  vol/spot both come from `vol_index_daily`, not this code path). Now reads
  the explicit `1d.parquet`, matching the already-correct sibling pattern in
  `_volatility_lake_close`.

## [0.10.11] — 2026-07-22

### Fixed

- **Runtime assets now ship inside the Python package.** `docker/app.Dockerfile`
  never copied `docs/`, so `canary-calibration-v1.json` and `guidance.md`
  vanished in the container after the 2026-07-08 Docker cutover: every canary
  run raised `FileNotFoundError` and `GET /api/regime/guidance` returned HTTP
  500 for 12 days. Both files moved to `uw_scan.cards.data` and are loaded via
  `importlib.resources`, with a `[tool.setuptools.package-data]` declaration so
  they also ship in release wheels.
- **`GET /api/regime/guidance` no longer degrades to an empty rule list** when
  `guidance.md` cannot be read — a missing runtime asset is now a loud failure.
- **A missing parquet-lake root now raises instead of returning `[]`.** The
  containers had no lake mount, so `resolve_lake_root` fell through to a
  Cloudflare R2 bucket whose producer died 2026-05-21. `vol_index_lake_sync`
  read the frozen bucket, inserted nothing, and logged nothing — freezing
  `vol_index_daily` and all EOD CRI/VCG/canary snapshots at 2026-07-07 for 13
  days while `basis='live'` rows stayed current and masked it. A mounted-but-
  empty lake now raises too.
- **`docker-compose.yml` mounts the lake** at `/lake` (the real
  `/Volumes/DATA_LAKE/...` path — `~/market-warehouse/data-lake` is a symlink
  and colima does not mount `$HOME`), parameterized via `ARGON_LAKE_HOST_PATH`.
- **The worker refuses to boot when retired R2 settings are present**, so a
  stale bucket can never silently take over again.
- **`vrp_macro_drawdown` reads its lake root from `Settings`** instead of a bare
  `os.environ` lookup with a home-dir fallback, consolidating path defaults into
  `config.py`.
- **Test isolation: dotenv no longer leaks across tests.**
  `Settings.from_env()` writes `.env`/`.env.local` keys into `os.environ` with a
  raw assignment (not `monkeypatch`), so the first test to call it leaked a
  developer's local dotenv into every later test — e.g. a `.env` pointing
  `XENON_QUERY_API_URL` at the mini made `test_settings_option_surface` pass in
  isolation but fail in a full local run. An autouse `tests/conftest.py` fixture
  now snapshots and restores `os.environ` per test. CI was never affected (no
  `.env` in CI).

### Added

- `scripts/check_runtime_assets.py` CI guard: no `Path.home()` outside
  `config.py`, no runtime `docs/` path construction in `src/`, and no named
  runtime asset reached through a `docs/` path in `src/` or the image-shipped
  `scripts/`.
- `scripts/smoke_container_assets.sh`: verifies the built image can load both
  runtime assets — the only check that reproduces the cutover failure.

### Changed

- `REGIME_RECOVERY_LOOKBACK_DAYS` 7 → 30 (calendar days). A recovery window must
  exceed time-to-detect, not typical outage length.

## [0.10.10] — 2026-07-20

### Added

- Volume profile on the Technicals price chart, behind a `VP` toggle beside
  `Zen` (localStorage-persisted, candle-mode only). Renders against the right
  edge of the price pane: horizontal bars per price bin, buy volume (bars that
  closed up) hugging the axis and sell volume stacked outside, length scaled to
  the busiest bin. Value-area bins (70%) draw at full opacity, tails dim; an
  amber line marks the POC. Binning math is pure and unit-tested
  (`web/lib/volumeProfile.ts` — volume conservation, contiguous bins, minimal
  value area, determinism, against the frozen real SPY OHLCV fixture); painting
  is a lightweight-charts series primitive (`web/lib/lwc/volumeProfile.ts`) in
  the mold of `chanlunZhongshu.ts`, drawn in the **background** layer so it
  never buries the newest candles. Each bar spreads its volume evenly across its
  own high–low (daily OHLCV is all we have) — where-it-traded context, not an
  order book, and explicitly not a signal.
- **Fixed 360-session profile window**, not the visible range. Shipped as VRVP
  first and that was wrong: panning between ~150 and ~600 visible bars moved the
  POC by a median of **11.6 ATR** across six names, so the levels were largely a
  function of the viewport. The window is now counted back from the newest bar
  and fed from the unwindowed series, so pan, zoom and the 3M/1Y/FULL selector
  all leave the levels untouched. 360 is measured, not inherited: stability keeps
  improving out to 5 years, but by then the POC sits 35–92% below spot — steady
  because it describes a market that no longer exists. Study:
  `docs/research/2026-07-20-volume-profile-window-study.md`, reproduce with
  `npx tsx scripts/research/volume_profile_window_study.mts`.
- Volume-profile S/R matrix on the same `VP` toggle: high-volume nodes become
  support/resistance bands (greedy peak-picking with proportional separation,
  per-side caps and a strength floor), labelled with strength as a % of the POC
  and a distinct-retest count; low-volume nodes render as labelled
  (`LVN <price>`) long-dashed lines, styled to read distinctly from the chart's
  own dotted grid rather than as furniture. A
  stats readout (`VolumeProfileStatsPanel`) shows POC/VAH/VAL, nearest S/R with
  zone counts, and value-area bias; its numbers are pushed up from the chart
  primitive rather than recomputed, so they always describe the bars actually
  binned. Zones are descriptive only — the same study found **no forward-return
  edge on either side** (resistance correct in 2–3 of 6 names at every window
  tested; support's apparent edge did not survive a distance-matched placebo).

- Fair value gaps behind a separate `FVG` toggle (default off): unfilled
  three-bar imbalances drawn as amber boxes extending to the right edge, via
  `web/lib/fvg.ts` (O(n) back-to-front fill test). Deliberately stricter than
  the Pine original — a gap closes as soon as any later bar _enters_ the band,
  not only when price traverses it completely, since a partially-traded band is
  no longer untraded. Painting reuses the existing zhongshu rectangle primitive
  rather than cloning it.
- The fast pair's own MACD and signal lines in the dual-MACD sub-pane, drawn
  over its histogram on the same ATR-normalized scale (the histogram is exactly
  their difference, asserted in `tests/unit/cards/test_dual_macd.py`). The
  histogram alone shows how wide the gap between the lines is but not where the
  crossing sits relative to zero — the difference between a momentum turn inside
  a trend and an outright trend flip. Two new series fields,
  `fast_macd_line_atr` / `fast_macd_signal_atr`, computed in
  `dual_macd_series` and carried in the `technical_daily` metrics JSONB. The
  slow 55/89/34 pair stays histogram-only: it is structural background, and four
  lines in a 150px pane is noise. **Existing rows need a technicals recompute**
  before the lines appear — the new keys are absent from already-stored JSONB.

### Removed

- VP BUY/SELL/touch/reject marks, before they ever shipped in a release. They
  redrew 21% of mark history per day at a 360-bar window and essentially all of
  it on the worst 10% of days, and the levels underneath them carry no measured
  edge. An arrow labelled BUY that moves tomorrow and predicts nothing implies a
  signal the data does not support. The profile, POC, value area and zones stay
  as descriptive structure.

## [0.10.9] — 2026-07-20

### Added

- Dispersion context readout on the CRI regime subtab (`/regime/cri`): a
  descriptive tile row (COR1M 20yr percentile, VIX/COR1M ratio, trailing-252
  ratio z-score). New read-only endpoint `GET /api/regime/dispersion`
  (`VolIndexRepository.fetch_dispersion_context` — 20yr percentile computed
  server-side, so no 20yr series ships to the browser) feeds
  `web/components/regime/DispersionTiles.tsx` via a local-typed
  `useDispersion` hook. A **two-tailed rule-based color highlighter** marks
  regime state — amber = dispersion (low correlation / high single-stock vol),
  red = herding (high correlation, crash-adjacent) — with a legend; it
  deliberately does NOT paint low correlation as a warning. Still explicitly
  regime **context, not a signal**. Backed by the directional evaluation in
  `docs/research/2026-07-19-dispersion-signals-eval.md`, which **rejected** the
  "low correlation (VIXEQ/VIX high) = warning" claim (low correlation is the
  calmest forward regime — shallowest drawdowns; high correlation is the crash
  marker already in the CRI trigger) and found the "deleverage high-beta on
  high VIX/COR1M" claim directionally sound but statistically underpowered
  (~5yr SPHB/SPLV). No new subtab, no new trading signal.

## [0.10.8] — 2026-07-19

### Added

- Chanlun overlay trust-styling on the Technicals price chart: divergence
  markers now reflect the trust-probe findings
  (`docs/research/2026-07-18-chanlun-trust-silver`). Trend-aligned 顶/底背离
  (底 above / 顶 below the chart's 200-DMA — the higher-conviction subset)
  render at full amber; counter-trend or pre-200-DMA-warmup 背离 dim to
  ~35%/~60%; repaint-prone base 1B/1S arrows (24–34% repaint) dim to ~40%,
  while 2B/3B and segment-level markers are unchanged. A pure
  `divergenceTrend` helper in `web/lib/chanlun.ts` (reusing the shared
  `lib/indicators` `sma`) computes the tier from a 200-SMA of the chart's own
  closes; the marker builder in
  `TechnicalsPriceChart.tsx` applies per-tier alpha via the existing
  `cssVar`-suffix idiom. Client-side only — no backend, API, worker, or
  type-gen change; no new chart primitive or toggle. A legend line explains
  the emphasis and discloses that the 200-DMA is corporate-action-unadjusted
  (so the trend split is unreliable for ~200 sessions after a split — the
  known livewire `adj_close` limitation, verified 0/23 NVDA + 0/17 TSLA tier
  flips against the plotted `SMA200` line).

### Fixed

- Technicals price charts now reserve ten bar-widths between the newest bar
  and the right price axis on initial load and after Reset. The chart's
  `fixRightEdge` setting had silently clamped the configured offset back to
  zero; regression coverage now protects both short- and long-history views.

## [0.10.7] — 2026-07-15

### Added

- Chanlun Phase B: sub-level (区间套) fast-confirm signal lifecycle engine,
  backend-only (no UI, no alert emission). Ports the web `chanlun.ts`/
  `chanlunSeg.ts` compute to Python (`src/uw_scan/chanlun/`: types, stroke
  core, segments, points/divergence/resonance, `compute_chanlun_full`) with
  frozen-fixture golden parity against the TS implementation plus 12
  regression tests for JS→Python porting traps (float/date/sort/None-vs-NaN
  semantics). A new `sources/apex.fetch_bars` client reads 1d and 30m bars
  from apex with an explicit `start` (apex's default-limit window silently
  truncates history otherwise) and never raises. Migration 107 adds
  `chanlun_signal_events` — an append-mostly per-`(ticker, category, kind,
extreme_date, extreme_price)` event log (`storage/chanlun_signal_repository.py`,
  standalone, not folded into `Repository`) driving a pure lifecycle state
  machine (`chanlun/lifecycle.py`): pending → confirmed*sublevel (S1: a
  confirmed same-side 30m vertex lands exactly at the daily extreme, no
  later-arriving 30m vertex beats it) → confirmed_native, with breach,
  20-session staleness, and `|ln(open_d/close*{d-1})| > ln(1.5)`split-boundary invalidation guards (S2 divergence-based sub-level confirm
  is stubbed as an unused flag for a future iteration). A nightly`chanlun_lifecycle_scan`job (03:10 ET Tue–Sat, massive-0, gated off by
  default via`UW_SCAN_CHANLUN_LIFECYCLE_ENABLED`) walks the watchlist and
  a new read-only `GET /api/stock/{ticker}/chanlun/lifecycle` endpoint
  exposes current per-mark state.

  The walk-forward validation probe that was to gate which categories get
  promoted past `confirmed_sublevel` (`scripts/research/chanlun_sublevel_probe.py`,
  10 tickers × ~5.1y of daily+30m bars, committed trace under
  `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/`) came
  back **negative**: all four candidate categories — vertex, divergence,
  3B, 3S — failed the ≥70% survival gate in both ticker-halves (actual
  7.5–17.3% survival), with the dominant failure mode being supersession by
  a more-extreme same-side point, ~70% of the time within the very next
  session. The shipped `chanlun_promotable_categories` default is therefore
  **empty** — every mark records its lifecycle transitions (useful as a
  durable event log and for the next rule-revision attempt) but none is
  currently eligible for sub-level promotion; the S1 fast-confirm path
  stays inert until a future rule revision clears the gates.

- Chanlun v2 on the technicals price chart: 线段 (chan.py feature-sequence
  port, both termination cases), 段级中枢 + 段级买卖点, pragmatic 中枢升级
  (consecutive overlapping zones merge to level-2 envelopes), and weekly×daily
  区间套 resonance (★ on confirmed daily 买卖点 with a confirmed weekly
  witness). Compute stays client-side (`web/lib/chanlunSeg.ts`,
  `computeChanlunFull`); the 中枢 primitive is reused unmodified.

- Fix: 买卖点 now actually fire on real data — `markPoints` assumed the
  中枢 exit leg was the breakout leg, but `buildPivots`' "first leg fully
  outside" is structurally always the counter-direction pullback, so every
  1B/1S/2B/2S/3B/3S gate was unsatisfiable (zero marks on AAPL/NVDA; the
  old oracles passed only on geometrically impossible fixtures). 3B/3S now
  mark the exit leg's own end vertex; 1B/1S compare breakout legs
  (`exitLeg − 1`). Also adds 顶背离/底背离 amber-dot annotations (a 笔
  extending past the prior same-direction 笔's extreme on weaker MACD
  area). New realistic-geometry oracles + real-data non-vacuity tests;
  post-fix write-up in §6e of the chanlun research doc.

- Fix: `/api/health`'s freshness block now anchors `consecutive_frozen_nights`
  on the snapshot's own newest `run_date` instead of the DB wall clock —
  `latest_snapshot()` was the last bare `consecutive_frozen_counts()` caller
  left behind by the autoheal-circuit-breaker fix, and its `CURRENT_DATE`
  anchor made the reported streak (and `autoheal_circuit_broken`) shrink as
  the clock advanced past the seeded nights (surfaced as the
  `test_health_autoheal_circuit_broken_includes_eligible_tripped_table`
  date-bomb in CI).

- Technicals price chart gains a 缠论 (Chanlun) overlay behind a header toggle
  (next to the SMA·σ/EMA·BB segmented control, localStorage-persisted):
  笔 stroke polylines (solid confirmed / dashed provisional tail), 中枢 pivot
  rectangles [ZD, ZG] (dashed border while extending), and 三类买卖点 markers
  (1B/2B/3B green, 1S/2S/3S red, "?" suffix on provisional points), all drawn
  on the lightweight-charts price pane. Structure is computed client-side in
  `web/lib/chanlun.ts` (包含处理 → 分型 → 新笔-style 笔 → bi-level 中枢 →
  buy/sell points gated by MACD-area 背驰; 线段 deliberately deferred),
  matching the EMA/Bollinger client-side-indicator precedent. 中枢 rectangles
  render via a new custom series primitive (`web/lib/lwc/chanlunZhongshu.ts`).
  Research + v1 design: `docs/research/2026-07-14-chanlun-tv-view-research.md`;
  unit tests run against a frozen real AAPL daily fixture (2026-01-02→07-10).

- Fix: the data-freshness autoheal circuit breaker now counts frozen-night
  streaks anchored on the job's injected `today` instead of the DB wall clock
  (`consecutive_frozen_counts(as_of=...)`). The `CURRENT_DATE` anchor silently
  shrank the counted streak whenever the caller's day differed from the wall
  clock — surfaced as a date-rolling CI time bomb in
  `test_autoheal_circuit_breaker_stops_retriggering` (green until 2026-07-13,
  deterministic failure after). `/api/health`'s streak enrichment keeps the
  wall-clock default.

- Docs: `docs/masterplan/` — cross-stack vision & blockers review plus the
  per-component master plan (goal ladder Stage 1–4, gaps, open decisions
  D-A..D-E, Stage-1 attack order) for the livewire/signal-lab/apex/argon/xenon
  desk. `CLAUDE.md` gains a condensed "Mission" section (stack role, ladder,
  Stage-1 minimal deliverable = signal→alert pipeline, invariants) with the
  verified option-surface history facts (grid spans 2025-12-26→present under
  UW's ~180-day window).

## [0.10.6] — 2026-07-12

- Technicals Dual MACD is now a native lightweight-charts sub-pane of the price
  chart (pane index 1) instead of a standalone hand-rolled SVG oscillator. It
  shares the price chart's single time scale and right-gutter, so the histogram
  bars are pixel-aligned under the candles and scroll/zoom is locked to price by
  construction (no cross-chart sync). The slow 55/89/34 renders as the muted
  structural background with the fast 13/21/9 tactical bars (green up / red down)
  layered on top. The pane's directional signal badge is now colored across the
  full `trend_state` vocabulary: clean BULLISH / DIP_BUY → green, BEARISH /
  RALLY_SELL → red, and the two transitional states color by structure sign at a
  dimmed shade — DETERIORATING (bull cooling) → dim green, IMPROVING (bear
  recovering) → dim red — so "in transition" reads distinctly from a clean trend
  rather than falling through to neutral grey. A faint dotted zero line marks the
  MACD crossing, and the pane keeps the interpretive caption (structural-vs-
  tactical, DIP_BUY / RALLY_SELL) that the old oscillator carried. MACD is no
  longer a reorderable row in the oscillator stack (it's pinned to the price
  chart); the retired `TechnicalsMacdChart` SVG component and its render test are
  replaced by unit tests on the `macdSignal` classifier and the `MacdLegend` row.

## [0.10.5] — 2026-07-12

- Technicals price pane: MarketSmith volume treatment (previous-close coloring,
  volume MA50 line, HVE/HV1 peak labels, volume buzz readout) and a small
  SMA·σ ⇄ EMA·BB overlay toggle (SMA20/50/200 + ±1.5σ band ⇄ EMA5/20/50 +
  Bollinger 20,2), computed client-side over the full series. Each volume bar's
  opacity is U-shaped in its buzz (volume ÷ MA50) to highlight the extremes:
  bars in line with their MA recede to a muted baseline while both tails — an
  extreme-high blowoff and an extreme-low dry-up — saturate to full opacity so
  they pop (the low tail is steeper so quiet, easy-to-miss bars especially stand
  out). Hue always stays the bar's up/down red/green — never grayed. The per-bar
  low-vol −% labels are hidden by default and reveal one-at-a-time on hover in a
  high-contrast color (they overlapped illegibly when all shown at once, and the
  muted color was invisible on the dark pane); revealing a label does not
  rescale or lift the volume bars. The volume band is taller and its
  bars are anchored to the pane floor (baseline pinned to 0 so they sit on the
  axis instead of floating). Bars keep a readable minimum width: short ranges fit
  the pane edge-to-edge, but a long range (e.g. FULL/5Y) no longer squishes to
  1px — it opens at the latest bars at full width and scrolls horizontally into
  history, with a Reset button in the header to snap back to fit-and-latest.
  Frontend-only.

## [0.10.4] — 2026-07-11

- Technicals price pane migrated to lightweight-charts: candlesticks + volume overlay + filled ±1.5σ band + click-to-anchor VWAP persisted per ticker. `technical_daily` now stores OHLCV (rides the nightly full-recompute; per-ticker auto-fill on first page open), new `technical_vwap_anchor` table, `POST/DELETE /api/stock/{ticker}/vwap-anchor`. The pane is taller (460px), the SMA lines are bolder, and the anchored VWAP now draws in a high-contrast sky blue (`--accent-cool`) at 3px so it reads clearly against the candles/SMAs. The header date follows the newest bar actually plotted, so the live head's forming bar drives it to today rather than pinning to the previous-business-day apex EOD date. Today's forming bar is now a **real intraday candle**: the live technicals job accumulates the session's open/high/low/close from the WS spot it already consumes (open = first fresh print of the ET session, high/low = running extremes, close = latest spot) and serves it as `forming_ohlc` on `/technicals/live`, so today draws as a genuine candle that fills in as the session runs and settles into the EOD bar at close — instead of the zero-range doji that hid on the price line. Every value is a real observed print (no fabricated open); at a frozen/closed market the bar is correctly flat. To guard against an unstable primary (xenon) feed, the live job cross-checks the forming candle against massive's ~15-min-delayed today bar every 15 minutes and heals a divergent read to massive (`source='massive.com'`, `stale=true`) — a **range-containment** test (a delayed close must sit inside the live `[low, high]`), which is robust to the 15-min lag where a naive close-vs-close check would false-positive on normal drift. The live oscillators (ATR-normalized MACD, kinematics) now recompute against the stored OHLC rather than close-only bars, so they line up with the settled daily series. (#256)

## [0.10.3] — 2026-07-10

### Changed

- **Technicals tab UI refinements** — the chart timeframe now defaults to **1Y**
  (was FULL/5Y); the reorderable stack now defaults to **dual MACD first,
  MA-Kinematics second** (the saved-order localStorage key is bumped to `:v2` so
  the new default supersedes any order saved under the original key); and the
  MA-Kinematics chart now tints the **below-zero region as a downtrend zone**
  (a subtle red band from the y=0 line to the plot floor via a new
  `shadeBelowZero` prop on `OscillatorChart`) so any moving-average slope dipping
  under zero reads as falling at a glance — line colors and t-stat weighting
  unchanged. The MA-Kinematics **alignment badge** now names the direction and
  colors by sign — `BULL ALIGN n/3` (green), `BEAR ALIGN n/3` (red), or
  `MIXED ALIGN 0/3` (muted) — instead of a sign-agnostic `ALIGN ±n/3`, so a
  bearish stack reads red at a glance (`OscillatorChart`'s `headline` widened to
  `ReactNode` to carry the colored label).

## [0.10.2] — 2026-07-10

### Added

- **Dual MACD on the Technicals tab** — replaces the single MACD histogram with a
  contrasting long-period (55/89/34) + short-period (13/21/9) ATR-normalized dual
  MACD and apex's tactical state machine (DIP_BUY/RALLY_SELL, trend/momentum-balance,
  confidence). The two histograms ride the existing `metrics` JSONB; the state rides
  the `detail` JSONB (no schema change).
- **Live technicals coverage** — a massive-0 scheduler job (`technical_live_scan`,
  gated by `UW_SCAN_TECHNICAL_LIVE_ENABLED`, default off) splices the live WS spot as
  today's provisional daily close and recomputes the fast-moving technicals (z, RSI,
  dual MACD, RV, kinematics, composite — sigmoid/forward-returns excluded) into a
  latest-only `technical_live` cache (migration 104). The Technicals tab polls
  `GET /stock/{ticker}/technicals/live` every 25s and overlays a LIVE/EOD head across
  every oscillator; stale/absent falls back to the EOD daily payload.
- **5-year technicals history** — the daily-bar fetch and warm-store read now retain
  ~1300 sessions across every technicals series.
- **On-demand technicals compute** — an unavailable ticker's Technicals tab now shows
  a "Compute now" button instead of a dead-end message. It POSTs
  `/stock/{ticker}/technicals/refresh`, which runs the nightly refresh job scoped to
  that one ticker (apex bars → EOD series) and returns the fresh payload so the tab
  renders in place; for a watchlist ticker this also makes it eligible for the 5-min
  live overlay on the next tick. Compute-only (no watchlist mutation); thin history /
  apex-unreachable leaves the tab empty with a note.
- **Technicals tab refinements** — the z-score chart now fills the full 5-year window
  (fetch a warmup buffer so `z_vs_200dma`'s ~324-bar warmup falls off the front); the
  dual-MACD chart gains a SLOW/FAST legend and draws the fast bars narrower than the
  slow overlay; the MA-Kinematics chart is weighted by each slope's t-stat (reliable
  trends bold, noise faded) and carries an ALIGN badge; the forward-return table
  defaults to all horizons with per-column aligned headers; a new return-distribution
  histogram (last 60d returns vs a normal, tails flagged) visualizes skew/kurtosis;
  and the live spot now flows into the price-card header with a LIVE/EOD marker.
  Follow-ups: the LIVE/EOD marker lives only in the price tile now (the duplicate
  page-level badge is gone); the standalone Trend-Reliability panel is dropped (its
  t-stats already live in the MA-Kinematics chart), which now also prints a
  plain-English reading of the current slopes; the forward-return table gains a
  "how to read" guide; the Sigmoid panel charts the fitted logistic against actual
  price (the fit's `actual`/`fit` arrays are surfaced only when the fit is valid,
  else the panel stays blank); and the chart stack is reorderable by drag-and-drop,
  with the order persisted per-browser in `localStorage`. The reorder handle is
  gone — the whole chart row is the drag source, so the charts stay flush-left
  with the KPI strip instead of being nudged over by a handle gutter. The Sigmoid
  panel's rejection message now names the clause that actually failed (fit too
  weak vs. no better than a straight line vs. curve pointing the wrong way)
  instead of a fixed formula that could read as the false "0.31 ≤ 0.05 + 0.05",
  and gains a how-to-read guide explaining the S-curve, phases, and k/s/R². The
  anchor price chart is now pinned at the top of the stack (out of the reorderable
  set — it's the date-axis alignment reference) and carries a theme-styled
  timeframe selector next to its date badge: FULL (5Y) / 1Y / YTD / 3M windows
  every date-axis chart below at once (a pure client-side slice of the series
  already in the payload — no extra fetch). The return-distribution panel keeps
  its own fixed 60d sample (it's a shape, not a date-axis graph the window pans).

## [0.10.1] — 2026-07-09

### Fixed

- **Schema-bearing releases now auto-migrate on deploy.** The engine-wide
  Watchtower deploys new _images_ but never ran the profile-gated `migrator`, so
  a release that added a table shipped code against an un-migrated DB until a
  human remembered to apply migrations (v0.10.0's `technical_daily` was missing
  for ~7h — api stayed green while the Technicals tab 500'd). The `api` service
  now self-migrates (`migrate_runner && exec uvicorn`) before serving: it is the
  single migration owner (no racing DDL across the sharded workers), never serves
  against an un-migrated schema, and crash-loops loudly on a bad migration instead
  of silently partial-serving. Idempotent + ~1s, so re-running every boot is free.
  Activation is a one-time `/opt/argon/compose.yml` mirror + `up -d api` (Watchtower
  does not deploy compose changes); future image-only releases self-migrate.
- **VRP macro entry-capture legs now snap to real Δ0.25/Δ0.125, not flat-vol
  strikes.** `resolve_entry_contracts` selected strikes off a single ATM/VIX vol,
  so SPX put skew made the recorded legs systematically too shallow (Δ~0.28 short
  / ~0.17 wing instead of 0.25 / 0.125) — the tracked strikes sat well above the
  legs you'd actually trade. Selection is now skew-aware: it brackets each target
  in delta-space using each strike's _own_ IV. The nightly
  `vrp_macro_entry_grid_refresh` caches the per-strike IV map alongside the strike
  grid (`vrp_macro_entry_grid.strike_ivs` JSONB, migration 103) so both the RTH
  auto-birth and the Capture button stay zero-extra-UW; a legacy grid without the
  IV map falls back to the old flat-vol path. To re-capture today on the corrected
  strikes, refresh the grid first (populates the IV map), then click Capture.

## [0.10.0] — 2026-07-09

### Added

- Technicals tab on `/stock/[ticker]` (index 1, after Market Structure): KPI stat-strip, price/MA/±1.5σ anchor chart, z-vs-200DMA history, forward-return-by-z-band table with current-band highlight, MA-kinematics / sigmoid / distribution / RSI / MACD / SPY-RS panels. Client island off the SingleStockReport hot path.
- Technicals metric history persisted per session (`technical_daily.metrics` JSONB, migration 102): return-distribution moments, RSI z/slope, MACD slope, MA-kinematics slopes, alignment.
- Technicals tab reorganized into an aligned stacked-panel layout (trader-terminal style): price/MA/±1.5σ anchor on top, then Z-score, RSI(14), MACD histogram, realized-vol, MA-kinematics, and relative-strength as full-width sub-charts sharing one date axis and left gutter (columns line up with price), each with a y-axis, reference lines/zones, and a plain-English explanation. Scalar-only diagnostics (MA-slope t-stats, alignment, sigmoid maturity, distribution shape) render as explained readouts. Sigmoid stays latest-only (per-request curve fit).
- Technicals backend: `technical_daily` warm store (migration 101), pure derivers in `cards/technicals.py` (z-vs-200DMA + bands, MA kinematics, sigmoid trend-maturity with beats-linear guard, return distribution, RSI/MACD enhanced, SPY relative strength, forward-return-by-z-band table), `GET /api/stock/{ticker}/technicals`, nightly `technical_daily_refresh` (apex daily bars, massive-0 18:40 ET, `UW_SCAN_TECHNICALS_REFRESH_ENABLED`).

### Changed

- **`/stock/{ticker}` performance package — three compounding fixes on the app's
  busiest read path.** (1) Killed an N+1: `_build_intraday_profiles` issued one
  `option_intraday_buckets` query per top-10 OI mover (10 serial round-trips per
  page load); new `OptionIntradayBucketRepository.fetch_buckets_batch` collapses
  them to a single `unnest`-join query. (2) Added a per-`(ticker, run_id)` TTL
  response cache in front of `assemble_single_stock_report` (default 20s, set
  `SINGLE_STOCK_REPORT_CACHE_TTL_S=0` to disable) so revisits and the 2.5s
  watchlist-spot poll don't re-derive the whole report; callers get a deep copy so
  the header's live-spot mutation can't corrupt the cache. (3) Replaced the
  connect-per-request path in `api/deps.py` with a process-wide
  `psycopg_pool.ConnectionPool` (`UW_SCAN_DB_POOL_MIN`/`_MAX`, default 2/10) —
  removes per-request TCP+auth+`SET search_path`, which matters more now that the
  api container reaches Postgres across the Docker VM boundary. Added `psycopg`'s
  `pool` extra.
- **Request-timing monitor for our own endpoints.** New log-only ASGI middleware
  tags every response with `X-Response-Time-ms` and logs a WARN when a request
  exceeds `API_SLOW_REQUEST_MS` (default 500; 0 silences). Distinct from the
  existing outbound-UW `latency_p95_ms`. Cache hit/miss counters exposed via
  `report_cache_stats()`.

- **Docker migration — cutover complete (Phase 2) + launchd retired (Phase 3).**
  argon now runs in Docker on the mini (`/opt/argon/compose.yml`); the 14 launchd
  app plists are moved to `/opt/argon/retired-launchd-plists/` (only
  `com.argon.backup` stays host-native), and deploys flow through the engine-wide
  Watchtower instead of the launchd `deploy-poller`/`macmini-prod.sh` path. Updated
  `docs/runbooks/docker-deploy.md` (status → complete, rollback path) and the
  CLAUDE.md release procedure. Rollback restores the plists from the retired dir.

### Fixed

- **Docker web healthcheck triggered a recurring `transformAlgorithm` error.**
  The compose web healthcheck used `wget --spider` (a HEAD request); a HEAD against
  the streaming SSR landing page makes Next.js 16 on Node 22 wire a response
  `TransformStream` with no body, logging a caught, non-fatal
  `controller[kState].transformAlgorithm is not a function` every 30s. Switched the
  healthcheck to a full GET (`wget -qO /dev/null`), which drains the body → zero
  such errors (verified live). Real user GETs were never affected. Also corrected
  the compose header container count (12 → 10).

## [0.9.1] — 2026-07-08

### Fixed

- **Docker web image: client-side `/api/*` rewrite baked the wrong target.**
  `next.config.mjs` `rewrites()` is evaluated at _build_ time, so the CI-built
  `argon-web` image froze the `localhost:8400` fallback into its standalone
  server — every browser `/api/*` call 500'd in-container (SSR was unaffected,
  masking it). `docker/web.Dockerfile` now sets `ARG NEXT_INTERNAL_API_BASE=`
  `http://api:8400` before `next build` so the rewrite bakes the compose
  service name; the launchd (non-Docker) build still bakes its correct
  co-located `localhost` default. Runbook Phase 2 gains an explicit
  web→api rewrite check (SSR page codes pass even when this path is broken).

## [0.9.0] — 2026-07-08

### Added

- **Docker migration — prep (artifacts only; no cutover yet).** Ships the pieces
  to move the mini prod stack off launchd into Docker (xenon/apex house pattern:
  Colima, `host.docker.internal`, host-native Postgres, GHCR images, the shared
  engine-wide Watchtower): `docker/app.Dockerfile` + `docker/web.Dockerfile`,
  root `docker-compose.yml` (10 services), `.dockerignore`, and a `ghcr-push`
  matrix job in `release.yml` (builds/pushes `argon-app` + `argon-web` to GHCR on
  every tag; `:latest` floats only for final releases). `config._HOST_DB_RULES`
  gains a `host.docker.internal` rule so containers pass the DB-isolation
  tripwire without the blanket override. Web SSR fetch sites now read the runtime
  `NEXT_INTERNAL_API_BASE` (not the build-inlined `NEXT_PUBLIC_API_BASE*`) so a
  containerized web renders against the `api` service, not itself; `next.config`
  emits `output: 'standalone'` with `outputFileTracingRoot` pinned to `web/`.
  **The launchd stack remains the live prod path** — cutover is phased and
  user-driven (`docs/runbooks/docker-deploy.md`,
  `docs/superpowers/specs/2026-07-06-docker-migration-design.md`). AI Codex/Claude
  workers are retired in phase 1 (issue #248); DeepSeek survives.

## [0.8.1] — 2026-07-08

### Changed

- **Mac mini Postgres backups now target the DATA_LAKE volume, atomically, on
  pg17.** `com.argon.backup` (and the R2 uploader) write to
  `${ARGON_BACKUP_DIR:-/Volumes/DATA_LAKE/argon/postgres-backups}` instead of the
  repo's `data/backups/`, dump via `postgresql@17` (matching the mini's server),
  and write to a `.part` file renamed into place only on success so a crashed
  `pg_dump` never leaves a truncated-but-plausible dump. `macmini-bootstrap.sh`
  now scaffolds the mini `.env` for same-host Postgres (`UW_SCAN_DB_HOST=127.0.0.1`
  - `UW_SCAN_ALLOW_DB_MISMATCH=1`) rather than routing over Tailscale. Runbook
    documents the macOS TCC `RemovableVolumes` requirement (background launchd jobs
    cannot write removable volumes without it) plus a shape-test probe to verify it
    after OS upgrades. Config/ops only — no application code paths change.

### Fixed

- **Deploy health-gate no longer deadlocks on benign budget-throttled scans.**
  The v0.7.2 change gated deploy success (and rollback verify) on `/api/health`
  `.ok == true`. But `.ok` folds in "expected full scans missed", which is
  routinely false for a _benign_ reason — UW daily-budget exhaustion legitimately
  **skips** full scans for most of the trading day, so the whole health reports
  `ok=false`. With `.ok == true` required on _both_ the forward gate and the
  rollback verify, a deploy launched during a budget-throttled window can pass
  neither: it burns its retry budget, rolls back, the rollback verify also fails,
  and the outer `gtimeout` kills `macmini-prod.sh` (rc=124). This is exactly how
  the v0.8.0 deploy failed and stranded the mini on v0.7.2. The gate now asserts
  **serving liveness** — `.db == "up" and .version == "<VERSION>"` (DB reachable +
  the newly-deployed code is the process actually answering) — and the rollback
  verify asserts `.db == "up"`. Worker/scan health stays monitored separately
  (C12 job-failure streaks + heartbeats); it is no longer conflated with whether a
  build deployed correctly.

## [0.8.0] — 2026-07-08

### Added

- **Ops-hardening: detection + alerting layer (C12 Track A).** Three pieces that
  make the ops surface observable before the Docker/Watchtower cutover (Track B).
  (1) **Job-failure streaks** — a new `job_failures` table (migration `100`) plus
  an APScheduler `EVENT_JOB_ERROR`/`EVENT_JOB_EXECUTED` listener records per-job
  consecutive-failure streaks (reset on success); surfaced on `GET /api/health`
  as `job_failures`. (2) **Per-job UW budget attribution** — the external-API
  breakdown now groups by `job_name` too, exposed at `GET /provider-usage/jobs`.
  (3) **Webhook alert sink** — a single never-raising `send_alert(title, message)`
  (`src/uw_scan/alerts.py`) fires on a failure streak reaching 3 (then 10) and
  once/day at the account-wide UW budget wall. **Set `UW_SCAN_OPS_ALERT_WEBHOOK_URL`
  in the mini `.env` to enable alerts** (Discord/Pushover-compatible JSON POST);
  unset = no-op by design. Alerting is fire-and-forget and can never crash the scheduler or
  the budget governor. R2 lake-staleness monitoring (ops-hardening spec §3) is
  intentionally out of scope.

## [0.7.2] — 2026-07-07

### Added

- **UW same-day fetch dedupe memo (issue #225).** The shared UW daily budget is
  exhausted by ~08:00 ET partly because 6+ jobs (option*surface_capture,
  cockpit_daily_snapshot, flow_data_refresh, skew_swing_greeks, vrp_macro_entry,
  full_scan pipeline) independently re-fetch identical slow-moving per-ticker data
  every day. The budget governor gates \_spend* but does not _dedupe_. New
  Postgres-backed memo (`uw_fetch_memo`, migration `099`; `storage/uw_fetch_memo.py`)
  keyed `(ticker, endpoint, as_of_date)` is consulted in `sources/uw.py` BEFORE the
  live call: the first same-day caller of `fetch_option_contracts` /
  `fetch_greek_exposure_by_expiry` spends budget and stores the raw payload; every
  same-day caller after reads it back (a budget SAVE, recorded on the row's
  `hit_count` + `last_hit_at`). TTL = same trading day (a row for today is a hit;
  stale dates are ignored and prunable). DB-backed rather than in-process because the
  jobs run in separate worker processes. Only the two slow-moving endpoints are
  wrapped — intraday/live feeds (spot, flow alerts) stay fresh — and both fetchers
  take a `force_refresh=True` kwarg to bypass. The historical-`date` path of
  `fetch_greek_exposure_by_expiry` is never memoized.

### Fixed

- **Market Tide tab froze mid-session when the shared UW account hit its guard.**
  `_regime_market_tide_scan` was budget-gated via `_research_budget_ok`, which
  returns False once the account-wide `official_daily_count` crosses
  `uw_total_daily_guard` (105k) — a threshold the shared UW key crosses most days
  by mid-morning (co-tenant + always-on stack). So the 5-min tide capture stopped
  appending bars (frozen at the prior session) even though it costs just **1 UW
  call/tick (~78/day)** — spot comes from the WS DB table, not UW. Dropped the gate
  to match its identical-cost sibling `regime_top_net_impact_scan` (never gated).
  Expensive intraday research (`regime_gex_scan`, ~4k calls/day) stays gated.

- **Deploy health-gate now checks `ok`, not just reachability.**
  `scripts/deploy/macmini-prod.sh` gated deploy success (and auto-rollback) on
  `curl -fsS` against `/api/health` — but that endpoint returns HTTP 200 in every
  branch, including `ok=false` (db down, missed scans, record-coverage collapse), so
  a broken release passed the gate clean and rollback never fired. `check_url` now
  takes an optional jq filter; the api gate and the post-rollback verify both require
  `.ok == true`. (jq already a deploy dep via `macmini-deploy-poller.sh`.)

### Added

- **Flow vs RV−IV falsification — do UW-native flow signals survive residualization? (#227, research spike).**
  `scripts/research/flow_vs_rviv_verdict.py` — residualizes a 3-day aggressor
  premium-imbalance signal (+ dealer net vanna / net charm) cross-sectionally against
  RV−IV, then decile-sorts forward 1d/5d stock returns on the RESIDUAL vs a
  matched-window RV−IV benchmark, gross and net of cost. **Verdict: NEGATIVE
  (coverage-limited but directionally clean).** On the fair matched-day benchmark, plain
  RV−IV does as well (1d: ~122 vs ~128 bps, a tie) or dwarfs the flow residual (5d: ~826
  vs ~340 bps); scattered |t|~2–3 cells are sign-inconsistent across horizons/signals and
  of implausible magnitude — small-sample noise on ~11–21 non-contiguous days, not a
  distinct tradable axis. Goyal–Saretto's collapse-to-RV−IV extends to aggressor flow and
  vanna/charm. Local `option_wizard_local` window: flow_events 114 tickers × 31 days
  (2026-05-12..07-07, two multi-day gaps); exposures_summary 115 × 22 days. Full trace in
  `docs/research/2026-07-07-flow-vs-rviv-verdict.{result.md,summary.json,daily_ls.csv}`.
  Re-run on the mini's fuller history before over-trusting the tie at 1d. Read-only, no
  migration.
- **Positioning intelligence — surface `uw_positioning` (card + screener).**
  The daily-banked `uw_positioning` snapshot (short interest / %float / days-to-cover /
  borrow fee, analyst counts + targets, institutional counts/value, insider net flow,
  earnings-reaction base rate, next ER date) previously had exactly one reader (the
  trade-blast LLM prompt) and no endpoint, panel, or screener. Now exposed read-only:
  `GET /api/positioning/{ticker}` (full snapshot + derived signals) and
  `GET /api/positioning/screener` (one row per watchlist ticker, sorted by squeeze
  risk). Derived signals (computed at read time in `reports/positioning.py`): squeeze
  score/label (si*pct_float × days-to-cover × borrow-fee tiers), insider net-flow tilt,
  analyst implied upside vs spot, analyst rating skew, pre-ER positive-reaction base
  rate, days-to-next-ER. Web: a Positioning card on the stock page's Market Structure
  tab + a `/positioning` screener table (new sidebar entry). **Zero new UW fetch** —
  everything reads the existing warm store. Storage read queries live in
  `storage/positioning.py` (`list_uw_positioning_latest`); models in
  `models/positioning.py`. Follow-ups deferred: parsing the discarded 13F/insider
  `raw_jsonb` detail, a borrow-fee \_spike*-vs-baseline signal (needs a rolling read),
  and any cross-sectional alpha signal (this is a surfacing task, not an alpha probe).
- **Trade-lifecycle layer: VRP-macro entry-capture cohorts read back as a portfolio (#223).**
  The validated VRP-macro edge captures entries into `vrp_macro_entry` (8 marks/day ×
  30 cal-days per cohort) but nothing read them back. New `/api/positions` (list) and
  `/api/positions/{entry_id}` (per-cohort P&L curve) endpoints surface every cohort
  (auto + button, open + expired) with its entry credit, latest mark, running unrealized
  P&L, return-on-risk, and DTE/expiry status — all modeled from the persisted
  short_above/wing_above bull-put mids (a missing NBBO side yields a null credit, never a
  fabricated number). New web **Positions** page (`/positions`, sidebar entry) renders the
  portfolio table with an expandable hand-rolled-SVG P&L curve per cohort. Pure read: two
  new storage queries on `storage/vrp_macro_entry.py`, a pure `reports/vrp_lifecycle.py`
  assembler, and `models/vrp_lifecycle.py` contract models — no new tables/migration.
  Reproduce/verify: `UW_SCAN_DB_USER=<superuser> UW_SCAN_DB_HOST=127.0.0.1
UW_SCAN_TEST_DB_NAME=option_wizard_test_wt1 UW_SCAN_ALLOW_DB_MISMATCH=1 uv run pytest
tests/unit/test_vrp_lifecycle_report.py tests/integration/storage/test_vrp_macro_entry_lifecycle.py
tests/integration/api/test_positions_api.py` + `cd web && npx vitest run tests/unit/PositionsPanel.test.tsx`.
- **Implied-correlation / dispersion richness gate — falsified (research spike, #226).**
  `scripts/research/implied_corr_gate.py` tests whether implied-correlation richness is a
  second, near-orthogonal axis on top of the validated VRP-macro short-vol edge. Uses the
  real CBOE **COR1M** implied-correlation index (`vol_index_daily`, 2007–2026, n=244
  non-overlapping SPX bull-put-spread trades) and reuses the validated
  `build_bull_put_spread` P&L + `backtest.metrics` machinery — no reinvented backtest math.
  Verdict in `docs/research/2026-07-07-implied-corr-gate.md`: **NEGATIVE, do not build**
  (MED). Short-vol P&L is **not monotone** in COR-z (inverted-U, top bucket reverts,
  Spearman p=0.29); COR-z is **~80% collinear with VIX-z** and insignificant (t=1.45) on
  independent trades once vrp-z/VIX-z are controlled; a COR-z gate gives no Sharpe gain
  (0.732→0.748) and halves return. The issue's equal-weight top-10 dispersion proxy tracks
  COR1M at pearson 0.91, validating COR1M as the measure. Read-only; no schema change.
- **SVI surface-fit feasibility + residual edge test (research spike).**
  `scripts/research/svi_fit.py` — pure raw-SVI (Gatheral) smile fit + butterfly/calendar
  no-arb diagnostics + delta-forward anchor, unit-tested (`tests/unit/test_svi_fit.py`) —
  plus two read-only probes over `option_surface_grid_daily`. Verdict in
  `docs/research/svi-surface-fit/`: raw-SVI fits liquid smiles to <0.5 vol-pt residual,
  arb-free, but the fitted-vs-marked residual — while a genuine mean-reverting signal
  (autocorr 0.56) — carries **no taker edge** (~\$0.18/contract, below one option
  commission). Do not build the signal layer. Adds `scipy` (main dep, needed by the tested
  fit); figs use matplotlib from the existing `research` dep-group. Also surfaced: the
  mini's IB canary (`iv_source_validation`) had captured no IB IV (0/1026 rows) through
  07-02 — a stale pre-key env frozen at worker fork, not a missing key (the mini's argon
  `.env` has `XENON_QUERY_API_KEY`); the Jul 4 worker restart already picked up the key,
  so the canary should self-heal on its next weekday run.
- **LEAP vega-alpha feasibility (research spike).** Tested radon's "cheap LEAP" thesis
  (HV20/HV60 − LEAP ATM IV wide ⇒ long-vega alpha) on 6 months of banked
  `option_surface_grid_daily` + apex daily bars. `scripts/research/leap_vega_alpha.py` —
  pure lib (realized vol, interpolated-δ ATM IV, entry gap, pooled + Fama-MacBeth
  cross-sectional metrics), unit-tested (`tests/unit/test_leap_vega_alpha.py`, 10 tests) —
  plus two read-only probes (convergence + P&L). Verdict in `docs/research/leap-vega-alpha/`:
  **NO tradable vega edge.** Stage 1 shows a real cross-sectional relationship (single-name
  FM IC 0.34/0.43), but Stage 2 decomposes the flagged "cheap LEAP" P&L as **82–88% delta**
  (a directional bet on high-vol names in an up-market); the delta-hedged, theta-net vega
  edge is **0.6–0.7 vol points — below the 1–5 vp ATM-LEAP round-trip spread**. Greek units
  calibrated empirically (grid `call_vega` is per-1%-vol, `call_theta` per-day — the
  CLAUDE.md "vega ×100" note is wrong for this table). Matches argon's prior: single-name
  surface geometry carries no taker edge (cf. skew #208, SVI #219). Zero UW/IB calls.

## [0.7.1] — 2026-07-04

### Fixed

- **HealthPanel "API OFFLINE" flicker.** The sidebar rapidly toggled `API
OFFLINE` / everything `UNKNOWN` even while the API was up. Root cause: the
  `/api/health` record-coverage ("Query Coverage") scan costs ~15–20s cold but
  its cache TTL was only 15s, so a fresh 20s query fired on nearly every 5s
  poll, stacking on one DB and blowing the browser fetch timeout. Two changes:
  (1) `_RECORD_HEALTH_CACHE_TTL_SECONDS` 15→120 so the expensive scan runs at
  most once every 2 min; (2) the poll now caps each request at an 8s timeout and
  keeps the last-good snapshot on a transient miss, only showing `OFFLINE` after
  3 consecutive failures (a real outage) instead of flickering on one slow poll.
  Polls are serialized (next scheduled only after the current settles) so an 8s
  timeout under a 5s interval can't overlap and let a stale timed-out poll
  corrupt the consecutive-failure count.
- **HealthPanel "Query Coverage" permanently ALERT.** The record-coverage check
  auto-discovered every ticker+timestamp table and expected ~90% watchlist
  coverage in an 8h window, with no market-calendar awareness — so it flashed
  ALERT every weekend/holiday/overnight (no scans run → 0 rows) and, during RTH,
  for sparse/research tables that structurally never reach 90% coverage. Now:
  (1) the check is market-calendar aware — when no full-scan cron was due in the
  window it reads healthy and skips the per-table scan (mirrors the WS-consumer
  relaxation); (2) the structurally-sparse candidate / research / unusual-activity
  tables (`signal_hits`, `scanner_candidate_snapshots`, `vrp_trade_candidates`,
  `vrp_paper_positions`, `vrp_backtest_trades`, `vrp_macro_sweep_results`,
  `corporate_actions`, `iv_source_validation`, `short_interest_snapshots`,
  `flow_events`, `dark_pool_events`, `oi_change_events`) are excluded — the
  event tables insert nothing for a ticker with no events, so they never reach
  90% coverage (but `signal_gates` is kept — it is written once per scanned
  ticker, so its coverage is a real scanner-persistence signal); (3) the nightly
  `option_surface_grid_daily` / `flow_alerts_daily_rollup` tables use the 24h
  window instead of 8h.

## [0.7.0] — 2026-07-04

### Added

- **UW daily-budget governor + RTH cadence scale-up** (targets ~70k live / ~25k
  research under the shared 120k account cap). New `sources/uw_budget.py` reads
  today's UW spend from `external_api_requests`, splits jobs into a `live` pool
  (`full_scan`, `full_scan_hot`, `rescan_tick`) and a `research` pool (everything
  else incl. `*_backfill`), and enforces per-pool ceilings plus an account-wide
  total guard (from the `official_daily_count` header, which also sees
  un-instrumented consumers). Under budget pressure `full_scan` scans hot-first
  and drops the cold tail (`max_tickers` cap) instead of 429-storming; research
  jobs yield first. Env: `UW_BUDGET_GOVERNOR_ENABLED`, `UW_LIVE_DAILY_CEILING`
  (80000), `UW_RESEARCH_DAILY_CEILING` (30000), `UW_TOTAL_DAILY_GUARD` (105000),
  `UW_DAILY_LIMIT` (120000).
- **Hot-subset fast lane** — a per-ticker `hot` flag (migration 096, UI toggle
  mirroring the pin: `HotButton` + watchlist hot-slots meter). Hot tickers get a
  tight-freshness intraday `full_scan` (`full_scan_hot` job, `*/5 9-16` ET,
  primary-uw-only, governor-capped). Env: `FULL_SCAN_HOT_ENABLED`,
  `FULL_SCAN_HOT_CRON`, `FULL_SCAN_HOT_STALE_MINUTES`, `FULL_SCAN_HOT_MAX_TICKERS`.
- **Intraday GEX research series** — `regime_gex_scan` expanded from the
  SPX/SPY/TLT core to the index family + M7 and moved to a split RTH-fast
  (`*/2`) / off-hours-slow (`*/15`) weekday cadence, building the append-only
  intraday GEX/DEX series UW only serves at EOD. Env:
  `GEX_SCAN_RTH_INTERVAL_MINUTES`, `GEX_SCAN_OFFHOURS_INTERVAL_MINUTES`,
  `GEX_SCAN_TICKERS`.

- Unified backtest harness `src/uw_scan/backtest/` (no-lookahead replay engine,
  time-ordered holdout splitter, walkforward+quarter OOS gates, legacy-convention
  metrics, persist-as-you-go sweep runner) + migration 095
  (`backtest_sweep_runs`/`backtest_sweep_results`). `skew_markout`, `vrp_markout`,
  `vrp_markout_core`, and `vrp_backtest` gate/holdout logic is now fully
  deduplicated onto it (behavior-identical) — no private copies remain;
  `scripts/_vrp_macro_param_sweep.py` synthesis grid now persists its full trace.

### Changed

- `full_scan_stale_after_hours` is now a float defaulting to **0.33** (~20-min
  watchlist freshness, was int `1`). `UW_SCAN_FULL_SCAN_STALE_HOURS` accepts
  fractional hours. The health "expected full scans missed" liveness alarm is
  now decoupled from card freshness onto its own grace knob
  (`health_full_scan_missed_grace_hours`, default 1.0h) so a transient
  governor-driven skip no longer false-alarms; sustained live-budget starvation
  (>1h) still alarms, as it should. The benchmark coverage gate
  (`benchmark/collector.py`, same `>=2` missed-scan threshold) shares the knob so
  the two "missed scans" signals stay consistent.
- Backfill scripts (`market_tide`, `greek_exposure_daily_refresh`,
  `intraday_buckets`, `option_surface`) now route UW calls through
  `ExternalApiRequestRecorder`, so their spend is attributed to the research
  pool and visible to the governor (Phase 0).
- **CLAUDE.md refresh + AGENTS.md deduplication.** All 14 in-repo CLAUDE.md
  files audited against the current tree and de-staled (api routers 6→17,
  cards/reports rewritten as domain-group maps, worker's dead
  `jobs/spot_refresh.py` entry removed, web stock `[tab]/` router + `/rates`
  `/vrp` routes documented, tests layout corrected). Four standing rules
  promoted from session memory (CHANGELOG-rides-the-feature-PR, smoke tests via
  the real worker path, R2-primary for EOD/backfill, workers-don't-hot-reload).
  `AGENTS.md` is now a symlink to `CLAUDE.md` (its two unique lines — worktree
  location rule, `unusual_whales_api_spec.yaml` pointer — were merged in first).

## [0.6.0] — 2026-07-02

### Added

- **Gold/rates tables added to the daily freshness monitor.** `etf_flows_daily`,
  `wgc_etf_monthly`, `cb_gold_reserves_monthly`, and `exchange_inventory_daily`
  join `MONITORED_TABLES` (`/api/health` `freshness` block, nightly
  `data_freshness_monitor`) — none were previously monitored, which is why
  `etf_flows_daily`'s ~7-week silent staleness (fixed in v0.5.1) required a
  manual investigation to catch instead of surfacing automatically.
  `_DATE_COL_PREFERENCE` now recognizes `obs_date`/`obs_month` (the gold/rates
  convention, distinct from the options-chain `market_date`/`trade_date`).
  `MonitoredTable` gains a per-table `grace_days` override so monthly-cadence
  sources (WGC releases monthly; COMEX/LBMA vault data is effectively monthly)
  don't cry wolf under the 4-day default meant for daily options data.
  `wgc_etf_monthly` / `cb_gold_reserves_monthly` / `exchange_inventory_daily`
  will show `frozen=true` until someone provisions a `WGC_GOLDHUB_COOKIE` or a
  licensed COMEX data source — that's accurate, not noise.
- **Freshness monitor coverage expanded from 12 to 48 tables.** A follow-up
  audit of the full 118-table data-gap registry found ~40 more genuinely
  continuous tables with zero prior `/api/health` visibility: the durable
  option-surface IV grid, the options-chain pipeline (greeks/IV term/skew/max
  pain/exposures), regime scanner outputs (GEX/CRI/VCG/GRG/canary), and the
  remaining FRED/rates/gold sources not already known to be blocked.
  `_DATE_COL_PREFERENCE` now also recognizes `data_date` and `snapshot_date`.
  `MonitoredTable` gains a `date_col_override` for the handful of tables with
  a one-off column name (`auction_date`, `record_date`, `event_date`) rather
  than growing the shared preference list with names that could collide on a
  future table. Deliberately **not** added: `dark_pool_events`, `flow_events`,
  `option_contract_snapshots`, `massive_fundamentals`, `short_interest_snapshots`
  (no DATE-typed column, only TIMESTAMPTZ event/insert timestamps —
  `compute_freshness` only handles DATE columns today) and `corporate_actions`
  (has both a date and ticker column, but is genuinely event-sparse per ticker;
  watchlist-scope coverage would produce a permanent false LOW COVERAGE
  warning, not a real signal).
- **Freshness grace periods derived from each table's real cadence, not hand
  guesses.** `MonitoredTable.grace_days` now defaults to a lookup on the
  gap-healer registry's `expected_frequency` (`_FREQUENCY_GRACE_DAYS`:
  equity_session/daily → 4, weekly → 10, monthly/event → 45) instead of each
  table separately guessing its own number — the exact class of manual
  judgment that caused 4 real scoping bugs earlier in this same pass (see
  "correct scope for 4 index/regime-only tables" below). Also fixes the
  registry itself: `wgc_etf_monthly`, `cb_gold_reserves_monthly`,
  `exchange_inventory_daily`, `rates_cftc_tff_weekly`, and
  `rates_treasury_auctions` were defaulted to `expected_frequency=
"equity_session"` despite being monthly/weekly; `rates_policy_events`
  becomes `"event"` (FOMC-driven, no fixed periodic SLA).
- **Freshness-autoheal: a same-night retry with a circuit breaker.** A frozen
  table with a gap-healer adapter gets one scoped retrigger the same night
  (`DATA_FRESHNESS_AUTOHEAL_ENABLED`, off by default) — a second chance for a
  table the 20:00 ET gap-healer left frozen from budget exhaustion or a
  transient failure, not a substitute for that nightly job. A circuit breaker
  (`DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS`, default 3 consecutive
  frozen nights) stops retriggering a genuinely unfixable source (missing
  credential, licensed data feed) instead of burning budget on it forever;
  tripped tables surface on `/api/health` (`freshness.autoheal_circuit_broken`)
  so a human knows to step in. Verified against a dry-run on real prod data:
  of today's 3 frozen tables, 2 have no adapter at all and the third would
  already have its circuit breaker tripped — autoheal correctly does nothing
  for any of today's known-broken sources.

### Removed

- **Dropped 4 permanently-empty legacy tables and their dead code paths**
  (migration `094`): `option_surface_snapshots` (S1 placeholder superseded by
  `option_surface_grid_daily`), `scan_universe` + `scan_results` (S2 full-scan
  persistence for a since-deleted Streamlit prototype — only reachable from
  an integration test, never from a scheduler job or the live Scanner page),
  and `structure_ideas` (a trade-structure stub whose writer had zero
  callers). Removed the now-dead `pipeline.run_full_scan`, `reports/scan.py`,
  `scan_universe.py`, five `_ScanResultsMixin` methods, `insert_structure_idea`,
  a dead marketcap-fallback join in `storage/watchlist.py`, and the
  corresponding registry/test entries. The live Scanner page is unaffected —
  it reads `scanner_candidate_snapshots` / `signal_hits` / `signal_gates` /
  `signal_context_flags`, none of which touch these tables.

## [0.5.1] — 2026-07-02

### Fixed

- **`gold_etf_holdings_ingest_job` used the host's local clock instead of ET.**
  `date.today()` picked up the mini's system-local date (ahead of US Eastern by
  ~12h) to compute the UW `/etfs/{ticker}/in-outflow` date range, so on a host
  whose local day has already rolled past midnight ET, `end_date` became a
  "future EST date" and UW rejected every call with HTTP 422 — silently, since
  the fetch is wrapped in a per-ticker `try/except: logger.warning`. `GLD` /
  `IAU` / `GLDM` in/outflow data (`etf_flows_daily`) stopped refreshing as a
  result. Now computes "today" via `datetime.now(ZoneInfo(rth_tz))`, matching
  the ET-aware pattern already used by `flow_data_refresh`, `regime_live`,
  `vrp_macro_signal`, and others.
- **xdist sharding blind spot** — `_reset_to_baseline` in `tests/integration/conftest.py`
  now drops any tables the test under execution created that are not in the
  post-migration baseline snapshot, before the `TRUNCATE … CASCADE` restore.
  Previously, an ad-hoc `CREATE TABLE` inside a test survived across tests within
  the same xdist worker and was only exposed by the unsharded release-verify gate
  (which runs the full suite serially in a single DB). The fix kills the whole
  class: drop extras → truncate baseline → copy baseline back.
- **`macmini-prod.sh` npm ci flakiness** — `rm -rf web/node_modules` is now run
  before `npm ci` so a partially-written `node_modules` (e.g. the `ENOTEMPTY:
rmdir lucide-react/dist/esm` error that blocked the first v0.5.0 deploy attempt)
  cannot stall the build step and leave the deploy script mid-way through
  `set -euo pipefail`.

## [0.5.0] — 2026-06-30

### Added

- **Data gap healer — full-coverage audit + heal + nightly backfill.** A
  resumable, budget-aware service that accounts for **every** recorded `uw_scan`
  table (118 datasets) and repairs safe coverage gaps. New `data_gap_*` domain
  (`migration 092`): a dataset registry (one source of truth in
  `reports/data_gap_healer.py`, projected to `data_gap_dataset_registry`),
  gaps-only `data_gap_items`, resumable `data_gap_runs`, and no-data
  `data_gap_caveats`. The exact scanner finds per-ticker/date misses by
  set-difference SQL (zero provider calls); the heal dispatch maps each healable
  dataset to an existing production job via one of four strategies
  (`run_once` / `run_once_lookback` / `per_ticker_range` / `per_ticker_date`).
  CLI `scripts/backfill/data_gap_healer.py` exposes `audit` / `execute` /
  `resume` / `verify` / `verify-all`; every run writes a Markdown+JSON report
  under `output/data-gap/`. **Full coverage includes macro/FRED/rates/gold**
  (healed by re-running their idempotent ingest jobs over a lookback window).
  A nightly job (`DATA_GAP_HEALER_ENABLED`, default off) runs at 20:00 ET — just
  after the UW quota reset — under an advisory lock, capping **only** UW spend
  (`DATA_GAP_HEALER_MAX_UW_CALLS`, default 20000); Massive/external are
  uncapped. `/api/health` gains a `gap_healer` block. Policy matrix:
  `docs/runbooks/data-gap-dataset-policy.md`; runbook:
  `docs/runbooks/data-gap-healer.md`.
- **YTD historical backfill from UW (`/volatility/stats`, `/volatility/realized`).**
  `realized_volatility_history` + `volatility_stats_history` are UW-sourced, not
  derived — repointed off the rollup adapter (which only writes
  `vrp_daily`/`stock_analytics_daily`) to dedicated heal adapters:
  `realized_volatility` (full ~1y series, 1 call/ticker) and `volatility_stats`
  (one row per ticker/date via `?date=`, the YTD `vol_stats` backfill — that
  table only accumulated forward from its 2026-05-11 inception because the
  fetcher was current-snapshot-only). `fetch_volatility_stats` gains an optional
  `market_date` selector (current-snapshot default preserved).
- **Watchlist ticker lifecycle log** (`migration 093`,
  `watchlist_ticker_events`). `reconcile_watchlist_lifecycle` (run nightly + CLI
  `reconcile`) diffs the live watchlist vs the last-known state: **added/re-added**
  tickers are logged and backfilled by the same run's audit; **removed** tickers
  are logged with their rows left intact (no exclusion code needed — the
  denominator is the live watchlist, so they already drop out). Append-only, so a
  remove→re-add cycle keeps the full history.
- **Benchmark snapshots persist through a heartbeat clock race.**
  `scheduler_heartbeat_lag_seconds` is clamped to `max(0, …)` in
  `benchmark/collector.py` so a heartbeat landing a hair after `now_utc` no
  longer violates the `058` `>= 0` CHECK and drops the snapshot
  (`pipeline_benchmark_snapshots` was stuck at 0 rows).

### Fixed

- **Gap-healer trading-day calendar (kills weekend/holiday phantom gaps).**
  `_calendar_dates` unioned the dataset's own dates with the `market_tide`
  reference, so a stray weekend/holiday price-bar in a dataset leaked that
  non-trading day into its own expected calendar — manufacturing a full-watchlist
  phantom gap for every ticker missing that bar. The reference
  (`market_tide_sentiment_daily`) is a clean trading-day spine (0 weekend/holiday
  rows), so it is now the sole calendar. On real prod data this cut the gap count
  25,814 → 15,021; `vrp_daily`/`realized_volatility_history`/`stock_analytics_daily`
  collapsed from ~3,000–3,800 phantom gaps each to the 2 genuine misses each.
- **Resume recovers items orphaned by a killed run.** A timed-out/killed run left
  items stuck `running`, which `claim_next_items` skips; `resume` now requeues
  them to `planned` first (heals are idempotent, so a blanket requeue is safe),
  so a backfill actually continues where it left off.

## [0.4.1] — 2026-06-30

### Changed

- **Market Tide spot overlay uses xenon IB bars as the primary source** (Apex
  REST is the automatic fallback). `sources/apex.py` now tries
  `POST /historical/bars` against xenon's query API (`XENON_QUERY_API_URL` /
  `XENON_QUERY_API_KEY`) before falling back to the Apex lake endpoint. Requires
  xenon ≥ v0.7.3 (moremeds/xenon#169 — fixes `_bar_date_to_iso` truncating
  intraday timestamps to date-only).

## [0.4.0] — 2026-06-30

### Added

- **Market Tide tab — Top Net Impact chart with per-update rank change.** New
  panel beside the daily tide (UW `/market/top-net-impact`): horizontal diverging
  bars of market-wide net option premium (`net_call − net_put`) per ticker,
  bullish/bearish split. Each capture carries `prev_rank` into the next so the
  chart shows ▲/▼/• rank movement between updates. Captured every 15 min RTH
  (`regime_top_net_impact_scan`, uw-0, kill switch `TOP_NET_IMPACT_CAPTURE_ENABLED`);
  migration `090`; storage `top_net_impact_repository.py`; endpoint
  `/api/regime/top-net-impact`.
- **Tide slope/sentiment ("TIDE SENTIMENT").** Quantifies the UW Daily Market
  Tide guide: spread `S = NCP − NPP`, its session + 30-min slope, divergence
  (`trend_strength = |net displacement| / range`), driver (call/put buying/selling),
  momentum, and net-volume confirmation. Surfaced live on `/api/regime/market-tide`
  (`sentiment` block) + a banner in the tab. EOD-persisted per session for
  backtesting (`market_tide_sentiment_daily`, migration `091`; nightly
  `market_tide_sentiment_eod` @16:25 ET). `reports/market_tide_sentiment.py`.
  `macmini-prod.sh` seeds the full stored-bar history once at deploy time
  (`market_tide_sentiment_backfill.py --if-empty`, best-effort, no UW budget),
  so the backtest dataset is complete the moment the feature ships; later
  deploys skip it (seeds only when the table is empty).
  Forward-return probe (`scripts/research/tide_slope_backtest.py`,
  `docs/research/tide-slope/`) finds it **descriptive, not predictive** at the
  daily horizon (n=120 YTD: ~50% hit, |corr| below the significance bar).
- **Apex SPY-spot overlay for the tide chart.** `sources/apex.py` reads SPY 5-min
  closes from the Apex bars API; `scripts/backfill/market_tide_spot_backfill.py`
  joins them onto `market_tide_snapshots.spot` by UTC instant so the historical
  SPY gold line renders (UW tide carries no price).

### Changed

- **Market Tide tab redesigned + default regime tab.** Daily chart now follows
  the UW layout — compact stats line (`SPY · Vol · NPP · NCP`), `Net Premiums` /
  `Net Volume` band labels, SPY on the left axis, premium + baseline-0 volume on
  the right, date-first time axis — wrapped (with Top Net Impact) in a single
  titled container carrying the UW guide tooltip. Clicking **Regime** now defaults
  to **Market Tide** (was Gamma Exposure).
- **`market-tide` / `top-net-impact` fetchers treat UW 422 (future EST date) as
  no-data**, like 400 — so a backfill walking from "today" (still future in ET)
  skips cleanly instead of crashing.
- **VRP macro entry-capture now stores IB's native option greeks as the primary
  source.** `xenon_query.fetch_ib_option_quote` previously discarded the
  delta/gamma/vega/theta in the `/options/greeks` response and `quote_leg` always
  BS-computed greeks from the marked IV. The IB-native greeks (which reflect IB's
  live surface) are now consumed as primary, rescaled to argon's BS column
  convention — vega ×100 (IB per-1% vol → per-100%) and theta ×365 (IB per-day →
  per-year); delta/gamma already match. BS-from-IV remains the backup when IB
  returns no greek set (UW-fallback legs, or IB without greeks). Adds `'ib'` to
  the `greeks_source` tag (`VrpMacroEntryLeg.greeks_source` contract widened to
  `ib | bs | none`).

## [0.3.6] — 2026-06-25

### Fixed

- **Macro short-vol "Tracked entry" showed fabricated strikes/mids.** Pre-birth
  (no cohort captured today), the entry preview fell back to `_bs_indicative_legs`
  — a synthetic 5-pt SPX strike grid (e.g. 7095/7090, which aren't listed strikes)
  priced with flat-vol Black-Scholes, rendered in the card as if they were market
  quotes. A fake number is worse than none. Removed the synthetic path entirely:
  the `/vrp-macro-signal/entry/preview` endpoint now serves persisted-cohort legs
  (real strikes + NBBO) or **empty legs** with no fabricated ETD — the card shows
  "No entry preview yet" / "ETD —" until a real cohort exists. Pairs with the
  grid-cache fix below, which is what lets a real cohort actually get born.

- **VRP macro entry-capture never persisted** — the daily SPX auto-birth
  (`_birth_auto`) enumerated the listed strike grid via two live UW calls inside
  the 10:00–15:00 ET birth crons, but the UW daily quota is reliably exhausted by
  ~08:00 ET, so every birth 429'd and aborted (`vrp_macro_entry` /
  `vrp_macro_entry_quote` stayed empty; the preview card silently fell back to the
  BS-`modeled` indicative legs). Added a nightly `vrp_macro_entry_grid_refresh`
  job (03:50 ET, massive-0, when the UW budget is fresh) that caches the real
  UW-listed expiry + put strikes into a new `vrp_macro_entry_grid` table
  (migration 088). The unattended auto-birth now reads that cache and makes **zero
  UW calls**, so an exhausted daily quota can no longer abort it; the on-demand
  Capture button reads the same cache (UW-free whenever the cache is warm, i.e.
  after the first nightly refresh — a cold-cache click still falls back to a live
  UW lookup). The cache read reuses the most-recent prior day's real grid (within
  a 4-day staleness bound, chosen expiry still open) if a nightly refresh is
  missed, rather than skipping birth. As part of this, `_uw_chain_strikes` now
  closes its `scan_runs` row as `failed` on a UW error instead of leaving it stuck
  in `running` (the visible side-symptom of the original bug).

## [0.3.5] — 2026-06-25

### Fixed

- **#180 — `option_intraday_buckets` covered only ~half the watchlist.** The
  intraday OI-mover refresh is registered on the primary UW worker only, but it
  still passed the per-worker crc32 shard filter — so ~55 shard-1 tickers
  (TSLA/NVDA/MSFT/GOOGL/META/AVGO …) were fetched by nobody and their stock-page
  TAPE column stayed permanently blank. The job now covers the full watchlist
  (`ticker_filter=None`; single-flight is already enforced by its advisory
  lock), and emits per-outcome counters (`skipped_no_run`, `skipped_no_movers`,
  `contracts_empty`, `contracts_error`) so a future coverage gap self-reports.
  One-shot backfill: `scripts/backfill/intraday_buckets_backfill.py`
  (budget-gated) — `--missing` auto-targets the blank set, and `--since` sweeps
  the full per-session history (`backfill_intraday_history`, distinct advisory
  lock) bounded by our recorded `oi_change_events` sessions, not just the latest
  run. Roughly doubles this job's daily UW calls; `UwClient` throttle/retry
  absorbs transient 429s.
- **#179 — single-name `greek_exposure_daily` froze at 2026-05-20.** It is
  index-only by design (the regime GEX scan only covers `gex_scan_tickers`); the
  100 single-name rows were a one-off backfill tail with no recurring writer. A
  new nightly job (`greek_exposure_daily_refresh`, 18:30 ET, uw-0) fetches UW's
  aggregate `/greek-exposure` history per single-name ticker — the SAME
  authoritative basis the indices use. (A DB→DB per-strike sum was tried first
  but validation showed it 20–134% off the aggregate — a partial-chain proxy —
  so it was dropped.) Backfill:
  `scripts/backfill/greek_exposure_daily_refresh_backfill.py` (UW, `--confirm`).

### Added

- **Data-date freshness monitor (prevention).** A nightly job
  (`data_freshness_monitor`, 21:00 ET) records, per curated per-ticker table,
  the newest **data date** + scope-aware active-watchlist coverage into
  `data_freshness_snapshots`, flags freezes, WARN-logs, and surfaces a
  `freshness` block on `/api/health` (all DB-up returns). Complements
  `list_record_health`, which keys on write-timestamps and skips no-timestamp
  tables (e.g. `greek_exposure_daily`) — the blind spot that let the vrp/greek
  freezes slip for five weeks. Migration `087`.

## [0.3.4] — 2026-06-25

### Fixed

- **`vrp_daily` silently froze for ~90% of the watchlist** (2026-05-22 onward).
  UW's realized-volatility endpoint began returning `null` for the
  `realized_volatility` column while `price` + `implied_volatility` stayed fresh;
  the nightly `nightly_vol_analytics_rollup` fed the raw null RV into
  `compute_vrp_series`, so `vrp = iv − rv` was `NaN` and `persist_vrp_daily`
  wrote nothing (the same loop's RV-independent `stock_analytics_daily` kept
  updating, masking the gap). The rollup now applies `_fill_rv_from_price` —
  deriving RV from the fresh price column, the same convention the stock-page
  read path already used — before computing VRP. Added
  `scripts/backfill_vrp_daily.py` (pure DB→DB, zero UW calls, idempotent) to
  recover the historical gap; one run restored `vrp_daily` from 9 → 104/104
  active tickers fresh. Regression test added in
  `tests/integration/worker/test_volatility_jobs.py`.

## [0.3.3] — 2026-06-24

### Added

- Per-stock **Short-Vol card** on the stock page's Market Structure tab — the
  single-name sibling of the SPX Macro Short-Vol card, placed third on the
  Directional-Bias row. A TRADE/SKIP sell-premium readout derived at read time from
  the latest persisted `vrp_daily` row (no new endpoint, job, or migration): TRADE
  only when vol is rich (`vrp_z_20 ≥ 1.0`), the ticker's sector is in the sellable
  set (`vrp_gate`), and a known next-earnings date is clear of the ~45-day hold
  window; otherwise SKIP with a reason (`vol not rich` / `sector vol not sellable` /
  `earnings inside hold window` / `earnings date unavailable`). On TRADE it models the
  same flat-vol bull put spread (0.25Δ short / 0.125Δ wing, ~30-day hold) as the macro
  signal, reusing `size_weight` + `build_bull_put_spread`; macro/ETF classes skip the
  earnings gate (they don't report), mirroring `vrp_gate`'s asset-class split.
  Non-finite `vrp_z_20` (short-history NaN) is normalized away, and the build is
  wrapped so the card can never take down the stock page. New
  `reports/stock_short_vol.py`, `StockShortVol` model + `SingleStockReport.short_vol`,
  and `web/components/stock/panels/ShortVolPanel.tsx`. EOD basis (modeled off the
  EOD-close spot). Plan `docs/superpowers/plans/2026-06-24-stock-short-vol-card.md`.

## [0.3.2] — 2026-06-24

### Added

- VRP macro **forward entry-capture & markout recorder**: records the real forward
  NBBO + greeks of the SPX bull-put-spread the Macro Short-Vol signal would place,
  tracked daily to expiry. A daily-born `auto` cohort (the 4 put contracts bracketing
  the 0.25Δ short / 0.125Δ wing at ~43-cal-DTE) is snapshotted **8×/day** (10:00–15:00
  ET hourly + 15:55 EOD + 16:10 post-close), tapering to EOD-only after 30 calendar
  days. Each leg quotes **xenon/IB-primary** (true NBBO + IV) → **UW fallback** →
  **greeks always BS-computed** from the marked IV (one-model: IB theta is per-day, BS
  per-year — never mixed). New table pair (`vrp_macro_entry` + `vrp_macro_entry_quote`,
  migration `085`), `reports/vrp_macro_entry.py`, `worker/jobs/vrp_macro_entry.py`
  (massive-0, gated by `vrp_macro_entry_capture_enabled`), and
  `GET/POST /api/regime/vrp-macro-signal/entry/{preview,capture}`. The Macro Short-Vol
  regime card gains a strike/ETD preview panel (served from the persisted snapshot —
  zero IB, zero new UW) + a one-click Capture button; the "(gate at 0)" / "stand aside"
  copy is dropped. Live-verified against prod IB (3/4 legs `source=xenon_ib`). Also
  fixes the stale `xenon_query_api_url` default (`:8421`, which was dead → silently
  no-op'd the surface IV canary too) to the mini's authenticated `:8321`; deploy must
  set `XENON_QUERY_API_KEY` in the mini's argon `.env` or the IB path falls back to UW.
  Plan `docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`.
- GOAS put-write delta sweep (research): a self-contained study finding the short-put
  **delta + tenor sweet spot** for the Goldman Options Advisory Strategy (systematic
  always-on OTM index put-writing). Three new `reports/` modules —
  `goas_putwrite_pricing.py` (a parametric downside-skew layer `iv(K)=atm·(1−slope·ln(K/S))`
  calibrated to GOAS's one published quote: 2026-05-05 SPY 96.2%-strike / 0.700%-premium →
  slope 2.693, with flat-vol as the conservative floor), `goas_putwrite_account.py` (a
  laddered, defined-risk **cash-secured** put-write NAV book — held to expiry, intrinsic
  settlement, fair-value daily marks, collateral earning the risk-free per CBOE PUT-index
  convention — plus `curve_metrics`/`putwrite_metrics` and a SPY buy-hold benchmark), and
  `goas_putwrite_sweep.py` (delta×tenor×pricing×fee sweep with regime slices and a
  per-regime catastrophe-gated ranking; management fee modeled as a downstream NAV drag,
  copying GOAS's own fee framing). Runner `scripts/research/goas_putwrite_run.py` reads SPY+VIX
  daily closes directly from the market-warehouse lake (2006→, ~20.4y, no Postgres/network)
  and writes five full-trace artifacts + a master findings note under
  `docs/research/goas-putwrite/`. Headlines: gross Sharpe rises monotonically with delta but
  short (21d) weekly writing fails catastrophically in fast crashes (COVID Sharpe −1.6) — the
  binding constraint is **tenor, not delta**; net-of-1%-fee gated sweet spot is **0.30Δ/63d**
  (Sharpe 0.147), conservative pick **0.15Δ/63d** (Sharpe 0.108, maxDD −14%, 95% win-rate).
  Every unlevered cash-secured cell trails SPY buy-hold risk-adjusted (best 0.15 vs 0.34) but
  at 2–4× smaller drawdown — the premium harvest above cash is only ~0.5–1.4%/yr, so GOAS's
  3–6% net target requires the 20–40% leverage this defined-risk study excludes. Reproduce:
  `uv run python scripts/research/goas_putwrite_run.py`.

## [0.3.1] — 2026-06-23

### Added

- VRP backtest iteration 4 (research): robustness suite on the SPX macro short-vol
  WINNER — `reports/vrp_robustness.py` (min viable capital, SPY buy-and-hold benchmark,
  geometric compounding metrics, weekday sweep, bear-start study, and a seeded
  Monte-Carlo suite: entry-timing jitter, stationary block bootstrap, randomized
  start incl. a GFC-windowed variant, config perturbation) plus six backward-compatible
  flags on the `vrp_capital_account` ledger (compounding, entry-weekday, entry-jitter,
  staggered extra tranche) that reconcile byte-for-byte to the iteration-3 path when off.
  Runner `scripts/research/vrp_robustness_run.py` writes seven `iter4-*.csv` full traces
  (per-config + per-trial Monte-Carlo + long-form bear-start equity path); findings in
  `docs/research/vrp/vrp-backtest-iteration-4-findings.ipynb` + an Iteration-4 section of
  the master report. Every experiment benchmarked against the iteration-3 SPX base case
  and SPY buy-and-hold. Headlines: the staggered extra tranche marginally beats the base
  (Sharpe 1.71 vs 1.68) while the contract overlay is exposure-not-edge; entry weekday
  matters modestly (1.33–1.53, all below the 1.65 stride); starting at a bear top still
  earns +150–180% over 36m; and config-perturbation p5 Sharpe 1.05 shows the result is
  not a knife-edge overfit. SPX vol-selling is six-figure-capital (one spread's max-loss
  rises ~15× to ~$28k by 2026).
- VRP capital-utilisation backtest (research): new `reports/vrp_capital_account.py`
  — a single shared **$50k cash-account ledger** (`CapitalConfig`,
  `desired_contracts`, `simulate_account`, `account_metrics`) that _reuses_ the
  validated macro short-vol `WINNER` engine to measure annualised return, capital
  utilisation, skip/fill rates, Sharpe and max-drawdown on a real dollar account
  (integer contracts floored to a risk-% of capital, capital-capped with logged
  skips). Reconciles exactly with `backtest_laddered` (Δ Sharpe 0.000). Adds SPY
  to macro `INDEX_SPECS`, a sweep runner (`scripts/research/vrp_capital_sweep.py`)
  with full-trace CSVs, and an executed findings notebook + verdict/master report
  under `docs/research/vrp/` (single-name SPX beats the 3-name blend; the overlay
  is leverage not edge; compounding sweet spot ≈ stop at 4–8×). New `research`
  dependency group (matplotlib/nbconvert/ipykernel) for the notebook only.
- Option-surface historical backfill: `option_surface_backfill` function and
  `scripts/option_surface_backfill.py` runner seed `option_surface_grid_daily`
  for up to 30 past trading days in one shot. UW `/greek-exposure/expiry` and
  `/greeks` both accept an optional `date=` param (now forwarded by the fetchers);
  dates already in the table are skipped. Run promptly after first deploy — UW
  403s beyond ~30 trading days.

### Fixed

- `reports/vrp_macro_drawdown._lake_spot` now skips lake rows with a null
  `trade_date`. SPY's equity-lake parquet carries ~73% null-date rows (an
  alternate-schema partition); without the guard `load_index_vol("SPY")` raised
  `TypeError` on the `d >= start` comparison. No-op for symbols with clean dates
  (QQQ/IWM).

## [0.3.0] — 2026-06-23

### Added

- Option-surface capture: a nightly, forward-accumulating per-strike IV/greeks
  grid for every watchlist ticker (`option_surface_grid_daily`, migration 077),
  plus an ATM IB-vs-UW IV canary (`iv_source_validation`, migration 078). New
  `option_surface_capture` job (19:00 ET) and `option_surface_iv_canary` job
  (19:30 ET) on the uw-0 worker, Mon–Fri. Enumerates the full term structure via
  `greek-exposure/expiry` — not `/option-contracts`, which UW silently caps at
  500 contracts by volume and so drops long-dated expiries (measured: SPX 28/53
  missing). One `/greeks` call per expiry, idempotent upsert, per-ticker failure
  isolation. The surface only accrues forward: UW returns 403 for per-strike
  history beyond ~30 trading days, so every uncaptured night is permanently lost.

## [0.2.3] — 2026-06-22

### Fixed

- Release pipeline no longer wedges the mac-mini auto-deploy on `uv.lock` drift.
  `cut.sh prepare` now re-locks `uv.lock` so its editable self-version tracks the
  version bump and commits it with the release, and `version_sync_check` (run via
  system `python3` before `uv sync` in CI, so a stale committed lock can't be
  auto-repaired and hidden) fails the build if the lock self-version ever drifts
  from `VERSION` again. Previously the committed lock lagged the bump; the first
  `uv run` on any host rewrote that one line, dirtied the tree, and the deploy
  poller refused every deploy — silently pinning prod to the last-deployed
  release (the mini sat on v0.1.2 for 4 days while v0.2.0–v0.2.2 published).

## [0.2.2] — 2026-06-22

### Added

- VRP macro signal deploy slice: nightly persistence + read API for the promoted bull-put-spread signal shipped in 0.2.1. New `vrp_macro_signal_daily` table (migration 083), `vrp_macro_signal_refresh` job (03:45 ET, Mon–Fri, primary worker — runs SPX/QQQ/IWM weekly readout + `backtest_laddered` headline and persists one row per name per snapshot date, with per-name failure isolation), and `GET /api/regime/vrp-macro-signal` returning the latest signal per name. Closes the persist-every-research-trace gap for the VRP macro engine.

## [0.2.1] — 2026-06-22

### Added

- VRP macro signal engine (`reports/vrp_macro_signal.py`): promoted bull-put-spread winner config (Δ0.25 short, ramp+ vrp-z sizing, 30 trd-day hold) into first-class engine code with `WINNER` constant, `backtest_laddered` (SPX Sharpe 1.65 / QQQ OOS 1.00), and `current_macro_signal` weekly readout (TRADE/SKIP + modeled strikes/credit/max-loss)
- VRP macro research expansion (`reports/vrp_{candidates,backtest,directional,harvest_axes,gate,rv_validation}.py`): corrected-measurement engine, sector/horizon/directional/ΔVRP sweep axes, per-ticker iron-condor candidates, paper ledger, model-repriced weekly backtest
- Corporate actions refresh job (nightly 17:35 ET) for exact-RV split/dividend adjustment

## [0.2.0] — 2026-06-21

### Added

- VRP harvest markout (`reports/vrp_markout.py`, migration `079_vrp_harvest_verdicts`,
  `GET /api/regime/vrp-harvest`): scores whether selling rich vol (`vrp_z ≥ +1`) earns a
  reliable, positive premium per `(asset_class, deviation_class)` bucket. Reuses the skew
  engine's out-of-sample discipline — time-ordered walk-forward holdout plus a per-quarter
  catastrophic-degradation gate — over the existing `vrp_daily` panel, and excludes any
  forward window spanning a (flow-event-reconstructed) earnings date. Verdicts
  (`HARVEST_SELLABLE` / `NONE`) persist nightly at 18:50 ET (massive-0 worker) to
  `vrp_harvest_verdicts`; the RICH−CHEAP spread is recorded so a flat (no-edge) result
  stays legible.

## [0.1.2] — 2026-06-18

### Fixed

- Stock detail pages (Flow / Market Structure / GEX) no longer render empty
  during US off-hours. `Repository.latest_run_id` selected the newest scan_run
  via a hand-maintained `notes` denylist; the skew engine's `skew_swing_greeks`
  side-channel runs were not on it and — having higher run_ids and no aggregates
  — shadowed the real `full_scan`, blanking every ticker's detail page after
  ~17:30 ET each day. The selector (and the `get_scan_duration_summary` health
  metric) now key on the property the report actually needs —
  `status='ok' AND aggregates IS NOT NULL` — so no future side-channel job can
  re-break it. No data was lost; the fix is read-path only.

## [0.1.1] — 2026-06-17

### Added

- Health sidebar now shows deployed backend version in the collapsed header,
  sourced from the running process via the existing `/api/health` poll.

## [0.1.0] — 2026-06-17

### Added

- Baseline release. Per-ticker options analytics: Next.js web (`web/`, :3001),
  FastAPI read API (`src/uw_scan/api/`, :8400), and the APScheduler worker, over
  a single Postgres (`uw_scan` schema). Scanner, regime (CRI/GEX/VCG), skew,
  Gold Compass, cockpit, and Trade Insights AI (Codex/Claude/DeepSeek) ship in
  this baseline. First release cut through the tag-driven `release.yml` pipeline.
