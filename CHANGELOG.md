# Changelog

All notable changes to Argon are documented here. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/) with semver versioning.
`VERSION` is the source of truth; `pyproject.toml` and `web/package.json`
version in lockstep (enforced by `scripts/release/version_sync_check.py`).

## [Unreleased]

### Research

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
- **Two spec claims falsified.** Segment/KPI disclosure is *not* "absent at any
  tier" — UW returns XBRL-dimensional segment and geographic revenue for 24/25
  tickers (4,330 rows), which makes the `concentration_risk` subscore buildable
  after the named-customer graph was measured as nonexistent. And foreign
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
  >= 40 quarters of UW statements, every candidate probed rather than sampled
  and extrapolated. `fundamental_signal_validation.py --wide` then ran the same
  code over it: **2q composite rank IC 0.059, t 4.84, hit rate 71.8% over 78
  quarters**, against IC 0.024, t 0.68 on the 25-name AI cohort. The single
  most defensible figure is the **0.039 (t 2.67)** measured on observations
  carrying a real `filing_date`, with no point-in-time fallback and therefore no
  look-ahead. Effect present in both halves of the sample and decaying
  (0.072 -> 0.047). Verdict, robustness table and limits:
  `docs/research/2026-08-11-fundamental-signal-validation/VERDICT.md`.
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
  `book_to_price` both margins get *stronger*. Market cap is built from **raw
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

### Fixed

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
  one bad ticker made every *subsequent* ticker fail with
  `InFailedSqlTransaction`. That second bug was latent behind the first — with
  nothing ever committing, a cascade had nothing to lose.
- **The integration test could not have caught it.** It asserted on the job's
  own still-open connection, which sees uncommitted rows, so it passed against
  a job that persisted nothing. Assertions now read through a **separately
  opened connection**, and the new coverage is a *freshness delta* rather than
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
  demonstrably exists *across* names would have been found *within* one. Absent,
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
  so the value stays as computed and the *display* layer suppresses it via
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
  `gross_margin` and `op_margin` measured *inverted* in the 2026-08-12 validation
  and `roe` is named by no rubric row, so `direction` is carried per feature in
  the API contract and is `null` for those three. It rides with the data rather
  than living in the UI, where a colour ramp could silently reassert a direction
  the research refused. No red/green scale and no bars: both encode a comparison,
  and a per-ticker card has no cross-section to compare against.
- Coverage reports "not reported" and "reported but not believed" as **separate**
  lists — different facts about a company — and the card dates itself by
  `knowledge_date`, never the `as_of` cross-section bucket.
- **Stage-2 fundamental scoring — subscores, composite, and method versioning**
  (migration `115`). `fundamental_method_versions` / `_params` / `_state` plus
  `fundamental_scores`, keyed `(ticker, as_of, engine_version, inputs_hash)`.
  New `fundamentals/scoring.py`, `storage/fundamental_scores.py`,
  `worker/jobs/fundamental_scoring.py`, `scripts/seed_fundamental_method.py`.
  Local run: **84 cross-sections, 20,552 scores, 257 names**, idempotent on
  re-run (0 inserted). Median cross-section width **249 of 257** — the
  knowledge-quarter keying holds, against the median of 23 the old
  fiscal-period bug produced.
- **All validated math moved into `src/uw_scan/fundamentals/`** — feature
  derivation, `zscore` and `composite_scores` now live in production and the
  research scripts import them, so the shipped composite *is* the validated one
  rather than a copy that can drift. Verified by re-running the wide validation
  after each move and confirming `validation_wide.json` byte-identical (three
  times).
- **"Exactly one active method version" is enforced by three mechanisms**, because
  `CHECK (singleton_id = 1)` constrains the row's *value*, not its *existence* — it
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
  Winsorizing would fix it *and* would make the shipped composite a different,
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

## [0.11.4] — 2026-08-10


### Added

- **Many-to-many industry-chain membership for the watchlist.** New table
  `uw_scan.watchlist_chain` (migration `113`) plus
  `src/uw_scan/watchlist_taxonomy.py` as the single source of truth for the
  9-layer / 38-chain taxonomy. `watchlist.sector` is unchanged and keeps its
  job — it is still the ticker's one PRIMARY tag and decides which section a
  card renders under; the join table carries the full membership set that
  FILTERING selects on. Both exist because a single column cannot express the
  taxonomy: NVDA is genuinely in `Computer/GPU`, `M7` *and*
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
