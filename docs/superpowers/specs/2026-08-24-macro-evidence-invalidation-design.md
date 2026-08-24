# Macro evidence invalidation — an additive, point-in-time overlay

**Status:** design. Not implemented. Read §7 before scheduling the work — the finding that
motivated this spec is not where the handover said it was.

## 1. The gap

`macro_observations` rows are immutable. Migration 115's `macro_observation_write_guard`
rejects every `DELETE`, and every `UPDATE` that changes any column but `last_seen_at`:

```sql
IF (to_jsonb(NEW) - 'last_seen_at') IS DISTINCT FROM (to_jsonb(OLD) - 'last_seen_at') ...
  RAISE EXCEPTION 'macro observations are immutable'
```

That is correct and must stay. Its consequence is that `quality_status` cannot be moved to
`'quarantined'` after the fact, so there is **no way at all** to record that an accepted
observation was later discovered to be bad. The ledger can say "we never accepted this"; it
cannot say "we accepted this and were wrong."

## 2. The semantics, settled

The operator's decision on 2026-08-24: **historical replay preserves what Argon believed at
the instant.** Corrected-history is a reserved opt-in, built only when something consumes it.

This collapses the design to **one predicate**, because it makes the invalidation itself
point-in-time:

> When answering for `as_of = T`, apply only invalidations whose `invalidated_at <= T`.

Both required behaviours fall out of that single rule:

- replaying 2021 today → a 2026 invalidation is not yet known → the bad row is returned, which
  is exactly what Argon believed in 2021;
- reading now → the invalidation is known → the row is excluded.

No second code path, no "current vs replay" branch for a caller to get wrong. It is the same
shape as `available_at <= as_of`, which is already the universal predicate — the overlay simply
gives the *discovery* its own clock alongside the *publication* clock.

**A corrected-history read** is then the deliberate violation of that rule: ignore
`invalidated_at` and exclude everything ever invalidated. Reserve the parameter; do not build it.

## 3. Schema

Migration number: **read the tail at implementation time.** The tail was `129` on 2026-08-24 and
`docs/superpowers/plans/2026-08-24-macro-mc4-mc6-sequenced.md` assigns `130` to MC4's snapshot;
whichever lands first takes `130`.

```sql
CREATE TABLE IF NOT EXISTS uw_scan.macro_evidence_invalidations (
  invalidation_id  BIGSERIAL   PRIMARY KEY,
  target_kind      TEXT        NOT NULL
    CHECK (target_kind IN ('artifact', 'observation', 'series_range')),
  artifact_id      BIGINT      NULL REFERENCES uw_scan.macro_source_artifacts (artifact_id),
  obs_id           BIGINT      NULL REFERENCES uw_scan.macro_observations (obs_id),
  series_id        TEXT        NULL,
  period_from      DATE        NULL,
  period_to        DATE        NULL,
  vintage_from     TIMESTAMPTZ NULL,
  vintage_to       TIMESTAMPTZ NULL,
  -- When we DISCOVERED the problem. This is the overlay's own PIT clock and the whole
  -- point of §2; it is NOT when the publisher made the error.
  invalidated_at   TIMESTAMPTZ NOT NULL,
  reason           TEXT        NOT NULL CHECK (btrim(reason) <> ''),
  evidence_url     TEXT        NULL,
  reviewer         TEXT        NOT NULL CHECK (btrim(reviewer) <> ''),
  overlay_version  TEXT        NOT NULL CHECK (btrim(overlay_version) <> ''),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Exactly one target shape, fully specified.
  CHECK (
    (target_kind = 'artifact'     AND artifact_id IS NOT NULL AND obs_id IS NULL AND series_id IS NULL)
 OR (target_kind = 'observation'  AND obs_id IS NOT NULL AND artifact_id IS NULL AND series_id IS NULL)
 OR (target_kind = 'series_range' AND series_id IS NOT NULL AND obs_id IS NULL AND artifact_id IS NULL)
  ),
  CHECK (period_from IS NULL OR period_to IS NULL OR period_from <= period_to),
  CHECK (vintage_from IS NULL OR vintage_to IS NULL OR vintage_from <= vintage_to)
);
```

`period_*` and `vintage_*` are NULL-open on each side, so a `series_range` can say "every vintage
of this series before 2025-11-13" without inventing a lower bound.

**The range columns are named `period_from`/`period_to`, not `period_start`/`period_end`.**
`macro_observations.period_end` already exists and the join predicate references both tables;
reusing the name produces a filter that silently compares a row to itself.

The table is append-only by policy. It needs no immutability trigger of its own: a mistaken
invalidation is corrected by a *later* row that supersedes it, which keeps the audit trail intact.
If supersession is ever needed, add `supersedes_id BIGINT NULL` — do not `UPDATE`.

## 4. The read predicate

`macro_context.py` already carries a shared fragment (`_ARTIFACT_AVAILABLE`); add a sibling
rather than five copies:

```python
_NOT_INVALIDATED = """NOT EXISTS (
  SELECT 1 FROM {schema}.macro_evidence_invalidations v
  WHERE v.invalidated_at <= %s
    AND ( v.obs_id = o.obs_id
       OR v.artifact_id = o.artifact_id
       OR ( v.series_id = o.series_id
        AND (v.period_from  IS NULL OR o.period_end   >= v.period_from)
        AND (v.period_to    IS NULL OR o.period_end   <= v.period_to)
        AND (v.vintage_from IS NULL OR o.available_at >= v.vintage_from)
        AND (v.vintage_to   IS NULL OR o.available_at <= v.vintage_to) ) )
)"""
```

**Four of the five readers take it; the fifth must not.**

| reader | takes the predicate | why |
|---|---|---|
| `fetch_macro_observation_as_of` | yes | feeds a state |
| `fetch_macro_series_as_of` | yes | feeds a state |
| `fetch_latest_macro_observation_as_of` | yes | feeds a state |
| `fetch_recent_macro_observations_as_of` | yes | feeds a state |
| `fetch_macro_observation_history` | **no** | it is the audit view |

`fetch_macro_observation_history` takes no `as_of` and applies no quality filter today — it
exists to show every vintage of a period. Filtering it would make the invalidation itself
unauditable: the operator asking "what did we throw away and why" would be answered by a view
that had already thrown it away. It should instead **join and mark** the rows, so the audit view
shows the row, the reason, and the reviewer.

## 5. What must be tested

1. A row invalidated at `T` is returned by a replay at `T − 1d` and absent at `T + 1d`. This is
   §2; if only one direction is asserted the belief-preserving half can rot silently.
2. A `series_range` with an open lower bound and a `vintage_to` excludes only the pre-rebasing
   vintages and leaves the post-rebasing ones.
3. `period_from`/`period_to` bound on the observation's `period_end`, and `vintage_*` on its
   `available_at` — a test that swaps them must fail.
4. The audit view still returns invalidated rows.
5. Migration replay is idempotent.
6. Raw bytes survive: the artifact row and its payload are byte-identical after invalidation.

The fixture is the real FRED rebasing, frozen from
`docs/research/2026-08-21-rates-market-layer-probe/VERDICT.md`: `WRESBAL` period `2025-06-04`
carrying `3294.381` at vintage `2025-06-05` and `3294381.0` at vintage `2025-11-13`, both
labelled `millions_usd`. Ratio exactly 1000.0 across 566 periods.

## 6. What this does NOT do

It does not repair a series. A per-vintage `publisher_transform` (`rebased_x1000` before
2025-11-13) is the recovery path named in the rates-market-layer verdict, and it is a different
mechanism with its own measurement burden. Invalidation removes evidence from consideration; it
never rewrites a value. Anything that rewrites a value is not this spec.

## 7. Measured 2026-08-24: production holds no known-bad evidence

The handover cited "the local evidence store currently holds 1,173 WRESBAL rows, all 1,173 marked
`valid`". The word *local* is load-bearing and easy to read past:

| database | WRESBAL rows | periods | vintages | pre-rebase rows |
|---|---:|---:|---:|---:|
| `option_wizard_local` (MacBook dev) | 1,173 | 607 | 604 | **566** |
| `option_wizard` (production) | **0** | 0 | 0 | 0 |

Production holds 28,941 macro observations and **not one WRESBAL row**. The bad data exists only
in a dev database that production never reads and that is owned by dev.

Two consequences, and the second matters more:

1. **The plan's exit criterion is unsatisfiable as written.** "WRESBAL remains physically present,
   current readers exclude it" cannot be demonstrated against production, because there is nothing
   there to exclude. Implementation must be verified against the frozen fixture in §5 instead.

2. **The reason this had to precede MC4 dissolves under §2.** The sequenced plan argued that
   snapshots pin evidence lineage, so adding invalidation afterwards would force a decision about
   whether an old snapshot's lineage mutates. Under a point-in-time overlay nothing is baked in:
   the filter is applied at read time from the reader's own `as_of`, and an immutable snapshot
   keeps citing exactly what it stood on, which is the correct belief-preserving answer. The
   retrofit is cheap at any point.

**Recommendation: implement MC4 first.** MC4 addresses a defect that is live — four independent
latest fetches that can render a partially-failed chain as four fresh cards. This addresses a
defect with zero production instances. Build the mechanism when something needs it, or when MC4
is done, whichever comes first; the design above is what should be built either way, and
recording it now is what stops someone later building the expensive baked-in version.
