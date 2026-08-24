# MC6 preflight — the continuous panel is `descriptive_only`; the event path survives

**Date:** 2026-08-24
**Reproduce:** `docker exec argon-worker-massive-0-1 python /tmp/macro_continuous_feature_preflight.py`
(source: `scripts/research/macro_continuous_feature_preflight.py`; copy in with `docker cp`)
**Full trace:** `census.json` (71 features, 74 series), `features.md` (same, rendered)
**Window:** 2021-01-04 → 2026-08-18, weekly, 294 instants
**Writes:** none. `macro_domain_states` was not touched.

## Verdict

**`descriptive_only` for every continuous state feature sampled as a panel.** No window that
Argon can obtain makes them testable, and sampling faster does not help — it is the thing the
correction measures.

**Not a blanket verdict on macro.** Release-event samples have a different structure and are
NOT killed by this measurement. They need their own preflight before anyone concludes anything
about them.

## What was measured

The 2026-08-23 flip census replayed monthly and got 68 points. That clock was a choice. The
evidence store's availability structure permits weekly, and the engines take it: **294/294
instants computed for all three replayable domains, zero errors.** The machinery is fine.

Two numbers per feature. The second decides:

- `points` — how many PIT instants produced a value
- `eff_n` — `points × (1−ρ)/(1+ρ)`, the AR(1) correction

A slow-moving level read weekly is not one independent observation per read. Reporting `points`
alone would restate the overlapping-window error the flip census avoided only by accident of
having chosen a coarse clock.

## The finding: information and sample size are inversely related here

The features with the **largest** effective sample carry **no economic content**:

| feature | distinct values | eff_n |
|---|---:|---:|
| `usd term.freshness` | 2 | 298.1 |
| `policy_rates term.sub_state_confidence:plumbing` | 2 | 294.0 |
| `usd term.completeness` | 2 | 294.0 |

These are binaries — *was the publisher on time*. Their effective sample is high **because they
are noisy**, not because they are informative. Any harness ranking candidates by sample size
would select exactly these and learn nothing.

Every economically meaningful feature sits between `eff_n` 0.9 and 27:

| feature | distinct | ρ | eff_n | window for eff_n = 100 |
|---|---:|---:|---:|---:|
| `inflation change.MEDCPIM158SFRBCLE` | 68 | 0.833 | **26.9** | 21.1 years |
| `inflation change.TRMMEANCPIM158SFRBCLE` | 68 | 0.839 | 25.7 | 22.0 years |
| `policy_rates level.T10YIE` | 69 | 0.896 | 16.2 | 34.9 years |
| `usd change.DTWEXBGS` | 247 | 0.913 | **12.8** | 42.1 years |
| `inflation level.MEDCPIM158SFRBCLE` | 68 | 0.935 | 9.9 | 57.2 years |
| `policy_rates level.DGS10` | 169 | 0.984 | 2.3 | 248 years |
| `policy_rates level.SOFR` | 90 | 0.994 | 0.9 | 645 years |

`change.DTWEXBGS` is the momentum the entire USD engine is built on — the quantity whose
threshold PR #377 moved from p61 to p76. Its effective sample over 5.6 years is **12.8**.

**Cross-check, independent of the AR(1) model:** that feature is a 63-daily-observation change,
≈13 weeks. Non-overlapping weekly sampling would give 294/13 ≈ **22** points. Same order as
`eff_n` 12.8, so the correction is not an artefact of assuming AR(1).

**Longer history does not rescue it.** The column above is `100 × (1+ρ)/(1−ρ)` weeks. Reaching a
merely modest `eff_n` of 100 needs 21–57 years for the best features and centuries for the rate
levels. The daily series begin 2021 and the CPI family 2015. The constraint is not our store —
it is that these variables move slower than any window a desk will ever hold.

## 14 of 71 features are constant across all 294 instants

Zero information, including `term.quality` and `term.revision_penalty` in **every** domain.

`revision_penalty` reading 0 across the entire replayed history is a direct, independent
corroboration of PR #380: its divisor was drawn from the wrong set and nothing caught it,
because in 294 weekly replays spanning 5.6 years **no series was ever revised in a way the term
could see**. A term that is structurally constant cannot fail a test that only exercises it.

## What survives: release events are PIT and not autocorrelation-bound

Measured, not assumed:

| event source | observations | distinct `available_at` | span |
|---|---:|---:|---|
| `federal_reserve_fomc` | 55 | **55** | 2020-01-30 → 2026-07-30 |
| `federal_reserve_sep` | 25 | **25** | 2020-06-11 → 2026-06-18 |
| CPI family (`CPIAUCSL`/`CPILFESL`) | — | **145** | from 2015-01-01 |

One observation per distinct instant means each release carries its own true publication time —
these replay point-in-time, unlike gold. Discrete non-overlapping releases do not suffer the
overlap death above: n≈55 (FOMC) to 145 (CPI) is small, but it is a *sample*, not a rolling read
of one slow number.

This is the only surviving candidate unit. It is **not** endorsed here — surprise definition,
baseline, and horizon are all unspecified, and a 55-event study has its own power problem. It
gets its own preflight or it gets dropped.

## Gold is still structurally excluded

`GLD_CLOSE` holds 275 periods across **3** distinct `available_at`; `GLD_HOLDINGS_OZ` holds 274
periods across **1**. Every historical vintage carries the retrieval clock, so gold cannot be
replayed before 2026-08-23 by any method. Unchanged from the 2026-08-23 census; migration 119 is
still the unused promotion mechanism.

## Consequences

1. **MC6 as "empirical promotion research" over state features is closed.** Do not build the
   walk-forward harness for this panel. The preregistered sample gate fails before a target is
   even chosen, which is the correct place to stop.
2. **MC5 has no empirical basis.** Nothing here justifies putting macro into the Fundamental PM
   surface. Keep it held.
3. **The risk-monitoring boundary is not the conservative option — it is the only supported
   one.** These features describe state. Measured over 5.6 years, they cannot carry a forward
   claim, and MC4's job of refusing to render an incoherent chain is exactly the right use.
4. **MC4 proceeds unchanged.** It never depended on this result, which is why the preflight was
   run in parallel.

## What would overturn this

A feature with `eff_n ≥ 100` measured the same way, or a demonstration that the AR(1) correction
materially understates the independent content of one of these series. Raw `points` is not an
answer to this file.
