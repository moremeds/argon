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
P0  F5 gold schedule ────┐
P0  F2 invalidation  ────┼──> MC4 snapshot ──> (authority already set: risk-monitoring)
                         │
P0  MC6 preflight  ──────┘    (parallel; gates MC5/MC6, not MC4)
```

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

**Exit:** WRESBAL stays physically present, current readers exclude it, the reason is auditable,
migration replay is idempotent, and belief-preserving replay is covered by a test that would fail if
a historical `as_of` started excluding it.

## P0-c — MC6 preflight (parallel; does not touch MC4)

Reads the evidence store and state records only. Persists the full census before exit.

- which continuous features exist across the four domains — factor values, confidence terms,
  contradiction counts, transmission residuals
- each one's PIT availability and history depth under `available_at <= as_of`
- gold is structurally excluded until migration 119 promotes a verified instant for `GLD_CLOSE`
- **preregister before any fitting:** target, horizon, lag, baseline, minimum-sample gate, kill rule

**Exit:** either a defensible PIT panel with a precise target, or a committed `descriptive_only`
verdict. Do not fit if the preregistered sample gate fails. Do not backfill replayed states into
`macro_domain_states` to manufacture sample size — those rows are immutable and would bake in
today's engine version.

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

1. contract + migration `130` + repository
2. assembler + worker job + API (current and `?as_of_ts=` replay)
3. UI reads one snapshot; replay / delta / lazy evidence drawer
4. real persisted verification: worker → DB → API → browser

**Exit:** a partial domain failure can never render as a coherent fresh chain; a later evidence
revision does not change an old snapshot hash; the page no longer fetches four latest states.

## MC5 — held

Not started, not authorized. Requires the preflight above to produce something other than
`descriptive_only`, plus a fresh authority decision. If it ever proceeds, it stays removable and must
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
