# MC4–MC6, sequenced against what was actually measured

**Supersedes the sequencing of** `2026-08-12-macro-mc4-mc6-context-pm-validation.md`. That plan's
task decomposition for MC4 is still good; its ORDER, its migration numbers, and its assumption that
MC6 can validate state flips are not. Read this file for order and gates, that one for task detail.

**Status:** COMPLETE 2026-08-26. Everything this document sequenced is shipped (F5, MC4, F2) or
formally closed (MC5, MC6). Nothing here is open.

## Decisions on the record

Both were open in the 2026-08-24 handover and are now settled by the operator:

1. **Historical replay preserves what Argon believed at the instant.** When an accepted observation is
   later discovered to be bad, replaying a past `as_of` still returns the state as it stood — bad
   evidence included. That is what point-in-time means: the state genuinely was computed from that
   evidence, and rewriting it would make the record a fiction. Invalidation affects **current** reads.
   A corrected-history read is an explicit opt-in parameter, built only when something consumes it.

2. **The authority boundary is risk-monitoring.** The macro layer may report freshness,
   contradictions, missing domains, dependency incompatibility, and measured transmission breakdowns.
   It may not rank, size, recommend, or alter any Fundamental PM output. MC4 as specified below sits
   exactly on this line. MC5 stays held.

## Why the order changed

`docs/research/2026-08-23-macro-state-replay-flip-census.md` replayed 68 monthly instants
(2021-01..2026-08). The categorical state label is not a viable validation unit: inflation flips 4
times, rates 8, `usd/2` 13 after the boundary move, and gold cannot replay at all before its
retrieval-clock evidence began. The original plan assumed MC6 would validate state transitions. It
cannot. So MC6 is gated on a preflight that the original plan did not contain, and that preflight
does not depend on MC4 — which is why it moves earlier and runs in parallel.

```text
P0  F5 gold schedule ─────────> SHIPPED 2026-08-25, PR #388, v0.12.17
                                 └─> verified in prod 2026-08-26: gauge age 3d -> 0d
P0  MC6 preflight  ───────────> DONE 2026-08-24: descriptive_only
                                 └─> MC6 CLOSED 2026-08-26 (its own designated verdict)
                                 └─> MC5 CLOSED 2026-08-26 (no positive reason to build)
NEXT  MC4 snapshot ───────────> SHIPPED, PRs #384/#386/#387, v0.12.17
                                 └─> first prod snapshot id 1, complete, 2026-08-25 19:40 ET
LATER F2 invalidation ────────> SHIPPED 2026-08-26, migration 131
                                 └─> zero production instances; verified on the frozen fixture
```

Revised 2026-08-24. F2 was ordered before MC4 on the assumption that snapshots bake in evidence
lineage. They do not, once the overlay is point-in-time — see P0-b.

## P0-a — F5: gold read a gauge produced on a later schedule — **FIXED 2026-08-25**

Before:

```text
18:30 ET  gold etf holdings ingest          (Mon-Fri)  <- last daily posture input but GPR
19:30 ET  macro gold evidence ingest        (daily)
19:40 ET  all four macro domain states      (daily)     <- reads the posture
20:00 ET  gold GPR ingest                   (Mon-Fri)
21:00 ET  legacy gold posture compute       (Mon-Fri)   <- writes the posture
```

Gold state calls `fetch_gold_posture_as_of(as_of.date())` and `gold_posture_compute` stamps its row
with the latest `GLD_CLOSE` date, so an evening run on day D writes `obs_date = D`. At 21:00 that row
did not exist when the 19:40 state asked for it. Gold stood on the PREVIOUS day's gauge **every
night**, structurally. `gauge_age_days` reported the lag honestly while the schedule created it.

Two corrections to this item as originally written:

- **`0-4` is Mon–Fri, not Sun–Thu.** Verified empirically against APScheduler 3.11.2. "Friday evening
  never runs" was wrong; Saturday and Sunday are the skipped days, and there is no gold close then.
- **The blocking question was already answered in code.** `gold_posture_compute_job` sets
  `target = as_of or _latest_gold_market_date(repo)`, so a row covers the latest `GLD_CLOSE` in the
  store and is self-describing. Nothing needed specifying.

After — GPR to 18:35, posture to 19:10:

```text
18:30 ET  gold etf holdings ingest          (Mon-Fri)
18:35 ET  gold GPR ingest                   (Mon-Fri)
19:10 ET  legacy gold posture compute       (Mon-Fri)   <- writes the posture
19:30 ET  macro gold evidence ingest        (daily)
19:40 ET  all four macro domain states      (daily)     <- reads TODAY's posture
```

Moving GPR up costs nothing, and that was measured rather than assumed: the publisher's file is a
static academic `.xls` already running 2–3 days behind the fetch — an ingest at 19:00 ET on
2026-08-19 returned an observation dated **2026-08-17**. The fetch clock was never the binding
constraint.

Mon–Fri is kept on both. The Saturday and Sunday states legitimately read Friday's gauge and say so.

**Exit — MET 2026-08-26.** `tests/unit/worker/test_gold_state_reads_todays_gauge.py` locks the ORDER
rather than the clock times — posture after its whole ingest cascade, before the state that consumes
it — so moving the block stays free and inverting it does not.

**Correction: the persisted smoke was never blocked.** This section previously said it could not run
because "no gold domain state has ever been computed". That was measured against `option_wizard_local`,
a dev database. **Production has held gold states since 2026-08-23**, and they carry the defect and its
fix directly (`gauge_age_days` term on `macro_domain_states.confidence_reasons_jsonb`, prod
`option_wizard`, read 2026-08-26):

| state | `as_of` (ET) | engine | gauge age | gauge `obs_date` |
|---:|---|---|---:|---|
| 18 | 2026-08-23 Sun 03:41 | `gold/1` | 2 | 2026-08-21 |
| 22 | 2026-08-23 Sun 04:43 | `gold/1` | 2 | 2026-08-21 |
| 26 | 2026-08-23 Sun 19:40 | `gold/1` | 2 | 2026-08-21 |
| 30 | 2026-08-24 Mon 19:40 | `gold/1` | **3** | 2026-08-21 |
| 34 | 2026-08-25 Tue 19:40 | `gold/2` | **0** | **2026-08-25** |

State 30 is the defect stated in production data rather than inferred from cron strings: a Monday
19:40 state reading Friday's gauge, because Monday's posture did not run until 21:00 — 80 minutes
after the state that consumes it. State 34 is the first run under the new schedule: Tuesday 19:10
wrote the gauge, Tuesday 19:40 read it, age 0.

The gold-state blocker cited here confused two different claims. The MC6 preflight's finding is that
gold cannot **replay** (`GLD_CLOSE` holds 275 periods across 3 availability instants). Computing
**tonight's** state needs no such history and was never blocked.

## P0-b — F2: additive evidence invalidation — **SHIPPED 2026-08-26**

WRESBAL was rejected because FRED republished its history 1,000x on 2025-11-13 while the contract
still labels every vintage `millions_usd`. The store holds 1,173 WRESBAL rows, all `valid`; period
2025-06-04 carries both `3294.381` and `3294381.0`, both `millions_usd`, both `valid`. Current
contracts exclude the series, so nothing consumes it today. The defect is that the ledger has no way
to say an accepted artifact was later found bad.

**Design first, in its own spec and PR.** Never mutate or delete raw evidence.

- targets: artifact, observation, and bounded series/vintage ranges
- fields: `invalidated_at`, reason, evidence, reviewer, version
- current reads exclude invalidated evidence; **replay does not** (decision 1)
- a `corrected=true` opt-in on replay is contract-reserved, not implemented

**DESIGNED 2026-08-24, not implemented, and DEPRIORITIZED behind MC4.**
`docs/superpowers/specs/2026-08-24-macro-evidence-invalidation-design.md`

Two things were measured that change this item:

**Production holds no WRESBAL at all.** The handover's "the *local* evidence store holds 1,173
WRESBAL rows" is exact, and the word *local* is load-bearing. `option_wizard_local` holds 1,173
rows (607 periods, 604 vintages, 566 pre-rebase); `option_wizard` holds **0** against 28,941 total
macro observations. The bad data lives only in a dev database production never reads. The exit
criterion below is therefore unsatisfiable as written and must be met against the frozen fixture
in the spec instead.

**The reason this had to precede MC4 dissolves.** That ordering assumed invalidation would be
baked into snapshot lineage. Under the belief-preserving semantics the operator chose, the overlay
is point-in-time — `invalidated_at <= as_of`, the same shape as `available_at <= as_of` — so it is
a read-time filter and nothing is baked in. An immutable snapshot keeps citing exactly what it
stood on, which is the correct answer. The retrofit is cheap at any point.

**Do MC4 first.** MC4 fixes a live defect; this one has zero production instances.

**Exit — MET 2026-08-26.** Migration `131` + `macro_context.py`; 16 integration tests over the
frozen WRESBAL rebasing. Raw bytes survive (the artifact row is byte-identical after invalidation
and the observation keeps `quality_status = 'valid'`), the four state-feeding readers exclude and
`fetch_macro_observation_history` does not — it joins and MARKS, so the audit view shows the row,
the discovery instant, the reason and the reviewer side by side. Both directions of the belief rule
are asserted, one second apart.

**The tests had to be rewritten once, and that is the part worth reading.** The first version
passed 10 of 13 with the feature not yet built. It invalidated the PRE-rebasing vintage and then
asserted the POST value came back — but the post row already wins on `available_at DESC`, so the
assertion held whether or not anything was excluded. The fix was a second period held ONLY at its
pre-rebasing vintage (566 periods were rebased; nothing guarantees a post row for each), where
exclusion is the difference between a value and `None`. Every test now names the production change
that breaks it.

**Enrolled as unhealable** (154 datasets). An invented invalidation is the rare fabrication that
SUBTRACTS: it would silently remove real observations from every point-in-time read after its
instant.

## P0-c — MC6 preflight (parallel; does not touch MC4)

Reads the evidence store and state records only. Persists the full census before exit.

- which continuous features exist across the four domains — factor values, confidence terms,
  contradiction counts, transmission residuals
- each one's PIT availability and history depth under `available_at <= as_of`
- gold is structurally excluded until migration 119 promotes a verified instant for `GLD_CLOSE`
- **preregister before any fitting:** target, horizon, lag, baseline, minimum-sample gate, kill rule

**DONE 2026-08-24 — verdict `descriptive_only`.**
`docs/research/2026-08-24-macro-continuous-feature-preflight/VERDICT.md`

The engines replay weekly without complaint (294/294 instants, three domains, zero errors), so the
flip census's monthly clock was a choice rather than a limit. It did not help. Every economically
meaningful feature lands between `eff_n` 0.9 and 27 after the AR(1) correction, and the features
with the LARGEST effective sample are binaries carrying no economic content — `usd term.freshness`
scores 298 on two distinct values, because high effective sample comes from being noisy, not from
being informative. `change.DTWEXBGS`, the momentum the whole USD engine rests on, is `eff_n` **12.8**
over 5.6 years; reaching a merely modest 100 would take 42 years. Longer history does not rescue
this and neither does faster sampling — that is what the correction measures.

14 of 71 features are constant across all 294 instants, including `term.quality` and
`term.revision_penalty` in every domain. The latter independently corroborates PR #380: no series
was revised in a way the term could see across 5.6 years, which is why its broken divisor survived.

**MC6 over state features is closed. Do not build the walk-forward harness for this panel.**
**Formally closed by the operator 2026-08-26.** Note what happened procedurally: `descriptive_only`
is one of the three verdicts MC6's own Task 12 was designed to publish, so MC6 reached its designated
exit — it did not stall short of it. The preflight was not in the original plan; it asked a question
that plan never asked (is there enough sample to test ANYTHING?) and answered it before the expensive
Task 11 harness was built.

**One candidate survives and is NOT endorsed:** release events replay point-in-time —
`federal_reserve_fomc` has 55 observations across 55 distinct `available_at` (2020-01-30 onward),
SEP 25/25, the CPI family 145 release instants from 2015. Discrete non-overlapping releases do not
suffer the overlap death. n≈55–145 is small and has its own power problem, and surprise definition,
baseline and horizon are all unspecified. It gets its own preflight or it gets dropped.

## MC4 — the snapshot is a refusal layer

Today the page runs four independent latest requests. The nightly worker uses one `as_of` and the
correct causal order, but each domain job catches its own exception and the loop continues. If rates
fails, USD still runs, reads the PREVIOUS rates state (which still satisfies `available_at <= as_of`),
and persists a new USD state citing it; gold then consumes a mixture. Four cards all render fresh.

Production was coherent when checked on 2026-08-24 — all four states at
`2026-08-24T07:40:00.001360+08:00`, USD citing the current rates state, gold citing all three. Nothing
enforces or detects that.

**Migration `130`.** The tail is `129`; the reservations of `117`/`118` in the older plan are void.

Status is decided by **dependency-edge identity**, never by timestamp proximity:

| status | meaning |
|---|---|
| `complete` | four domains present, and every downstream's cited upstream state id equals this snapshot's |
| `partial` | a domain is absent — its job failed or never ran |
| `incompatible` | a domain is present but cites an upstream that is not this snapshot's |
| `stale` | the newest snapshot is older than the expected cadence |

**The one constraint that must not break: a snapshot may never repair an incompatible chain by
substituting a fresher upstream.** Its job is to name the incompatibility. Substitution is how a
monitoring layer becomes a fabrication layer.

`inputs_hash` covers the four state identities plus snapshot parameters, so re-assembly is idempotent
and a later evidence revision cannot change an old snapshot's hash.

Four independently reviewable PRs:

1. contract + migration `130` + repository — **DONE 2026-08-24**, PR #384
2. assembler + worker job + API (current and `?as_of_ts=` replay) — **DONE 2026-08-25**, PR #386
3. UI reads one snapshot and renders its refusal — **DONE 2026-08-25**
4. real persisted verification: worker → DB → API → browser — **DONE 2026-08-25**

Slices 3 and 4 shipped together: the verification exists to prove the UI, so splitting them
would have opened a PR whose only content was evidence for the previous one. The operator
chose **option A** for a broken chain — banner plus all four cards, never withholding.

The verification caught a real incompatibility rather than a constructed one: USD state 22
cites `policy_rates` 21 while the latest rates answer is 23, because a rates-only rerun at
01:15:44 followed a full pass at 00:45:14 with no matching USD recompute. Local store, so
production is unverified — what it proves is that the detector fires on real stored edges.

**MC4 is complete.** F5 and F2, open when this was written, both shipped (2026-08-25 / 2026-08-26).

**Exit:** a partial domain failure can never render as a coherent fresh chain; a later evidence
revision does not change an old snapshot hash; the page no longer fetches four latest states.

## MC5 — CLOSED by the operator 2026-08-26

Never started, never authorized, and now closed rather than held. It required the preflight above to
produce something other than `descriptive_only`. It did not. Nothing measured justifies putting macro
into the Fundamental PM surface, so the hold stopped being procedural — it is the finding.

**What "closed" means here, precisely.** MC6's own verdict taxonomy defines `descriptive_only` as
*"retain MC4/MC5; no score/ranking/sizing authority"* — written on the assumption that MC5 would
already be BUILT by the time MC6 ran, so the sentence means *do not tear out what exists*. MC5 was
never built, so the live question was **whether to build it**, which that taxonomy does not answer.
The operator answered it: no. `descriptive_only` does not by itself forbid a context-only MC5 block
(that block was designed with no scoring authority — the byte-invariance test exists for exactly
that reason); what closes it is the absence of any positive reason to build it.

If it is ever reopened it stays removable and must prove byte-invariance of every fundamental fact,
score, valuation anchor, and hash with macro on and off. Its reserved migration `118` is void — the
Fundamental lane took that number long ago.

## Gates that survive all of the above

1. Known-bad evidence is invalidated additively; raw evidence is never deleted.
2. Confidence reasons and confidence arithmetic refer to the same set. *(closed by PR #380)*
3. Gold state/gauge timing is deliberate, tested, and exposed.
4. One persisted snapshot owns the four-domain composition and its exact lineage.
5. Missing, stale, failed or incompatible domains produce refusal, never a coherent-looking chain.
6. Replay uses only evidence available by the selected instant, and preserves belief.
7. MC6 uses a preregistered, sufficiently sampled target and persists its full trace before exit.
8. No alert, PM overlay, ranking, sizing, or allocation authority is inferred from a descriptive state.
9. Real smoke follows worker → DB → API → browser. A direct function script does not satisfy it.
10. CHANGELOG, docs, code, tests and verification evidence ride the same feature PR.
