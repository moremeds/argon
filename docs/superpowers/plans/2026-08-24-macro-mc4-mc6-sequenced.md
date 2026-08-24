# MC4–MC6, sequenced against what was actually measured

**Supersedes the sequencing of** `2026-08-12-macro-mc4-mc6-context-pm-validation.md`. That plan's
task decomposition for MC4 is still good; its ORDER, its migration numbers, and its assumption that
MC6 can validate state flips are not. Read this file for order and gates, that one for task detail.

**Status:** planned. No implementation authorized by this document.

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
P0  F5 gold schedule ─────────> (independent; blocked on a question, see below)
P0  MC6 preflight  ───────────> DONE 2026-08-24: descriptive_only
                                 └─> MC5/MC6 closed; MC4 unaffected
NEXT  MC4 snapshot ───────────> (authority already set: risk-monitoring)
LATER F2 invalidation ────────> designed; zero production instances; retrofit is cheap
```

Revised 2026-08-24. F2 was ordered before MC4 on the assumption that snapshots bake in evidence
lineage. They do not, once the overlay is point-in-time — see P0-b.

## P0-a — F5: gold reads a gauge produced on a later schedule

```text
19:30 ET  macro gold evidence ingest
19:40 ET  all four macro domain states     (daily)
21:00 ET  legacy gold posture compute      (Sun-Thu only)
```

Gold state calls `fetch_gold_posture_as_of(as_of.date())`, so the same day's posture cannot exist at
19:40. `gauge_age_days` reports the lag honestly, but the schedule guarantees it.

**This cannot be specified until one question is answered:** which market close does each posture row
cover? The cron is `0 21 * * 0-4`, so Friday evening never runs. Until the covered-close mapping is
stated, "rerun gold after posture" only relocates an undefined lag. Answer that first, in the spec.

**Exit:** a scheduler-order test, a stated and tested intended lag, and a real persisted smoke
comparing state `as_of`, gauge observation date, and the allowed lag.

## P0-b — F2: additive evidence invalidation

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

**Exit (when built):** raw bytes survive, current readers exclude and the audit view does not,
the reason is auditable, migration replay is idempotent, and a test asserts BOTH directions of the
belief rule — returned by a replay before `invalidated_at`, absent after.

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

1. contract + migration `130` + repository — **DONE 2026-08-24**, PR pending
2. assembler + worker job + API (current and `?as_of_ts=` replay)
3. UI reads one snapshot; replay / delta / lazy evidence drawer
4. real persisted verification: worker → DB → API → browser

**Exit:** a partial domain failure can never render as a coherent fresh chain; a later evidence
revision does not change an old snapshot hash; the page no longer fetches four latest states.

## MC5 — held, and now without an empirical basis

Not started, not authorized. It required the preflight above to produce something other than
`descriptive_only`. It did not. Nothing measured justifies putting macro into the Fundamental PM
surface, so the hold is no longer procedural — it is the finding. If it ever proceeds, it stays removable and must
prove byte-invariance of every fundamental fact, score, valuation anchor, and hash with macro on and
off.

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
