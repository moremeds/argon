# Macro state replay: the engines work, the labels are not testable objects

**Date:** 2026-08-23 · **Status:** measured, blocking on MC4/MC5/MC6 sequencing
**Reproduce:** `docker exec argon-worker-massive-0-1 python /tmp/macro_state_replay_census.py`
(source: `scripts/research/macro_state_replay_census.py`, read-only, never persists)

## Why this ran

`docs/superpowers/plans/2026-08-12-macro-mc4-mc6-context-pm-validation.md` sequences
MC4 (context snapshot) → MC5 (PM overlay) → MC6 (empirical gate). MC6 is where the
program is supposed to earn the right to influence anything. Before building two
products on top of the four domain states, one question is worth answering: **is a
macro state label something MC6 could test?**

Production could not answer it. `macro_domain_states` holds **2 calendar days** of
history (2026-08-20, 2026-08-23) across 16 rows — the nightly compute only ever runs
"now", and it was first enabled this week. So the history was reconstructed by replay.

## The engines replay correctly

All four state jobs accept `as_of: datetime | None`. Replayed at six annual instants,
three of four domains produce a coherent, moving series:

| as_of | inflation | policy_rates | usd |
|---|---|---|---|
| 2021-06-30 | WELL_ABOVE_TARGET / RISING / 1.00 | ON_HOLD / FLAT / 0.67 | RANGEBOUND / FLAT / 1.00 |
| 2022-06-30 | WELL_ABOVE_TARGET / FALLING / 0.40 | TIGHTENING / RISING / 0.67 | STRENGTHENING / RISING / 1.00 |
| 2023-06-30 | WELL_ABOVE_TARGET / FLAT / 1.00 | ON_HOLD / RISING / 0.67 | RANGEBOUND / FLAT / 1.00 |
| 2024-06-30 | ABOVE_TARGET / FALLING / 0.85 | ON_HOLD / FALLING / 0.67 | STRENGTHENING / RISING / 1.00 |
| 2025-06-30 | ABOVE_TARGET / FALLING / 1.00 | ON_HOLD / FALLING / 0.67 | WEAKENING / FALLING / 1.00 |
| 2026-06-30 | WELL_ABOVE_TARGET / RISING / 0.85 | ON_HOLD / RISING / 0.67 | RANGEBOUND / FLAT / 1.00 |

The rates path catches the actual cycle (ZIRP → the 2022 hiking run → terminal → cuts),
inflation catches the surge and the disinflation, USD catches the 2022 wrecking ball and
the 2025 fade. **Nothing here is broken.** The evidence store carries genuine vintages:
inflation series back to period 2015-01 with ~5–8 vintages each, rates/USD daily back to
2021-01-04, policy paths back to 2020-01-29.

## The finding: n is either too small to test or too large for the wrong reason

68 monthly replays, 2021-01 through 2026-08:

| domain | state flips | direction flips | labels seen |
|---|---:|---:|---|
| inflation | **4** | 22 | BELOW_TARGET, AT_TARGET, ABOVE_TARGET, WELL_ABOVE_TARGET |
| policy_rates | **8** | 5 | ON_HOLD, TIGHTENING, EASING |
| usd | **29** | 29 | UNKNOWN, RANGEBOUND, STRENGTHENING, WEAKENING |

### inflation — 4 transitions in 68 months

```
2021-01  BELOW_TARGET        2024-02  ABOVE_TARGET
2021-05  AT_TARGET           2026-04  WELL_ABOVE_TARGET
2021-06  WELL_ABOVE_TARGET
```

WELL_ABOVE_TARGET held 32 consecutive months; ABOVE_TARGET held 26. This is correct —
inflation regimes genuinely last years — and it means **no amount of replay makes
inflation state flips testable.** n=4 does not produce a t-stat.

### policy_rates — 8 transitions, event-driven

```
2021-01 ON_HOLD    2023-08 TIGHTENING   2025-02 ON_HOLD
2022-04 TIGHTENING 2023-10 ON_HOLD      2025-10 EASING
2023-07 ON_HOLD    2024-10 EASING       2026-02 ON_HOLD
```

The 2023-07 → 08 → 10 round trip is the July 2023 hike, correctly caught. The label
moves on FOMC meetings, not on a trend, so its n is bounded by the meeting calendar.
Also note **confidence is pinned at 0.667 at every historical instant** — the dealer and
market-implied paths only exist from 2026-08-18, so the whole replayable history runs on
2 of 4 paths. That is honest, but it means any confidence-weighted historical study
reads uniformly degraded.

### usd — 29 transitions, and this is the bad news

```
2022-01 RANGEBOUND -> 02 STRENGTHENING -> 03 RANGEBOUND -> 05 STRENGTHENING
        -> 08 RANGEBOUND -> 09 STRENGTHENING -> 12 RANGEBOUND
```

2022 was a **monotone** dollar bull run (DXY ~96 → ~114 → ~103). The engine reports it
as six alternating flips. USD is the only domain with n large enough to test, and its n
is large **because the classifier chatters, not because the dollar changed regime 29
times.**

The mechanism is in `macro/usd.py`. `UsdParameters.momentum_threshold_pct = 2.0` is
calibrated on the *marginal* distribution — its own docstring records that it "leaves
53.8% of days RANGEBOUND". **A classifier whose boundary sits near the median of its own
input distribution crosses that boundary maximally often, because crossing density peaks
where the density does.** Verified: the counts above were produced with
`prior_state=None`, and `prior_state` reaches `compute_confidence` only
(`confidence.py:69`, revision detection) and never the state label — so classification is
memoryless and these are true production flip counts, not a replay artifact.

### What was tried, and what was rejected

The first hypothesis was hysteresis — a dual entry/exit band, so a state is left only on a
decisive retreat. **Measured and rejected.** Sweeping entry × exit over the same 68 months
(`scripts/research/usd_threshold_sweep.py`):

| entry | percentile | exit | flips | longest regime |
|---|---|---|---:|---:|
| 2.0% | p61 | none | 29 | 6 mo |
| 2.0% | p61 | 1.00 | 26 | 7 mo |
| 2.5% | p70 | none | 23 | 8 mo |
| **3.0%** | **p76** | **none** | **13** | **14 mo** |
| 3.0% | p76 | 2.25 | 17 | 12 mo |
| 3.0% | p76 | 1.50 | 23 | 7 mo |
| 4.0% | p85 | none | 11 | 17 mo |
| 5.0% | p93 | none | 9 | 22 mo |

At **every** entry threshold the hysteresis variant left flips flat or **raised** them. A
wider band does not remove transitions, it relocates them — the state stays directional
longer and then flips straight from STRENGTHENING to WEAKENING. The lever is *where the
boundary sits*, not *how sticky it is*.

Distribution over 12,330 momentum points: median |63-obs change| 1.45%, p75 2.91%, p90
4.57%. So 2.0% sat at the **61st** percentile — the middle of the record, which is the
worst possible place for a boundary. 3.0% sits at the **76th**: RANGEBOUND becomes the
ordinary three quarters of the record, and a directional call needs a top-quartile
quarterly move.

Corroboration from an independent source: the preregistered golden scenario
`usd_strength_against_easing_policy` (`tests/fixtures/macro/usd_gold_golden.json`), authored
before this analysis, encodes a **+6.34%** move as its example of real STRENGTHENING — far
out in the tail, not at 2.0%.

**Shipped:** `momentum_threshold_pct` 2.0 → 3.0, `USD_ENGINE_VERSION` and
`UsdParameters.version` both `usd/1` → `usd/2`. Stored `usd/1` states keep their own
semantics and stay readable. Verified through the real `compute_usd_state` with parameters
injected as a kwarg: 29 → 13 flips, longest regime 6 → 14 months, 0 `inputs_hash`
collisions between the two parameter sets.

**This does not make USD testable.** 13 transitions in 68 months is still far short of what
an MC6 gate needs. It makes the label mean what it says, which is what item 2 (render it)
requires.

## gold cannot replay at all

`GLD_CLOSE` holds 275 periods back to 2025-07-21 but `available_at` = 2026-08-23 for
every row. This is deliberate and documented (`macro/gold_ingest.py:14-24`): neither
massive nor SPDR stamps a release instant, so `available_at` is the retrieval clock —
"it never claims we could have known a price before we fetched it". The stated cost:
"history ingested today is not PIT-replayable before today." Migration 119
(`macro_artifact_instant_resolution`) is the mechanism to promote a verified instant
later; until someone does, gold is structurally excluded from every historical study.
It currently reads SUSPENDED regardless.

## Consequences

1. **MC6 cannot be run on state flips for any domain.** Not for lack of history — the
   history is there and replays fine — but because of what the labels are. Two are too
   slow (n=4, n=8), one is too noisy to mean what it says (n=29).
2. **MC4/MC5 built in plan order would ship two products before this was known.** The
   "decision surface" MC4 renders would have the chattering domain as its most active
   panel.
3. **Macro state flips should not be wired into the Stage-1 alert pipeline as-is.**
   `CLAUDE.md` names "VRP macro state flips" as one of three alert sources. Inflation
   would fire 4 times in 6 years; USD would fire every 2.3 months on threshold noise.
4. **The four domain states currently have zero UI.** `/api/macro/{inflation,rates,usd,gold}`
   all exist; `web/lib/api.ts` consumes only `/api/macro/policy`, and there is no
   `web/app/macro/`. The nightly compute writes to a table nothing renders.

## Recommended order (inverted from the plan)

1. ~~**USD hysteresis**~~ → **USD threshold recalibration**. DONE. Hysteresis was the
   hypothesis and the measurement rejected it; moving the boundary from p61 to p76 cut
   flips 29 → 13 and extended the longest regime 6 → 14 months. See "What was tried, and
   what was rejected" above.
2. **One macro page** rendering the four states + evidence drill-down. This is MC4
   Task 4 without MC4 Tasks 1–3; the snapshot DAG is not needed to show four states
   that already exist.
3. **Hold MC5 and MC6.** MC5 is a PM overlay for a signal that has not been shown to
   carry information. MC6 needs a testable object, which requires deciding whether the
   macro layer's unit is the categorical label (untestable) or the continuous features
   underneath it (1,400+ daily observations, testable).

Do NOT backfill replayed states into `macro_domain_states` to manufacture history:
those rows are immutable and undeletable (migration 125), the engine version would be
baked in permanently, and per the census above the resulting series would not be
testable anyway.

## Related

- `docs/superpowers/plans/2026-08-12-top-down-macro-context-program.md` (program source of truth)
- `docs/superpowers/plans/2026-08-12-macro-mc4-mc6-context-pm-validation.md` (the plan this reorders)
- Precedent for measuring before building: `docs/research/2026-07-28-theta-harvester-weight-sweep.md`
  (score orders, selected set does not pay) and `docs/research/2026-08-12-fundamental-*/`
  (composite orders cross-sectionally, cannot time one name).
