# Fundamental observation availability — operator runbook

Availability claims (`uw_scan.fundamental_obs_availability`, migration 130) record
**when each statement content version became usable**. They are _derived evidence_
about rows Argon already holds, not captured data.

## Why this table exists

`fundamental_statement_obs` is an honest immutable ledger — a restatement lands as
a new row beside the original, never over it. What it never carried is _when each
version became available_, so the panel reader answered that with `obs_id DESC`
and **no cutoff at all** — every historical question got today's panel.

The missing cutoff is the defect. The sort key is not: `obs_id` is a BIGSERIAL
assigned in the same INSERT as `first_observed_at`, so an `obs_id` ordering and a
capture-time ordering cannot disagree. Measured on production 2026-08-24: **0
disagreements over all 200 identities holding more than one content version.** The
sort key starts mattering only once `true_pit` claims exist, because a publication
date comes from a source independent of insertion order.

## The four classes

| Class             | Meaning                                                            | `available_at` |
| ----------------- | ------------------------------------------------------------------ | -------------- |
| `true_pit`        | positive publication/amendment evidence for **this exact content** | required       |
| `capture_bounded` | Argon holds this content and first saw it then; safe at or after   | required       |
| `current_vintage` | usable for today's page, no historical claim at all                | must be NULL   |
| `unknown`         | not even a usable timestamp; fails closed everywhere               | must be NULL   |

Two CHECK constraints enforce the timestamp column. An observation carrying **no
claim** already reads as unknown to every policy, so `unknown` rows are not
written.

## Expect true-PIT coverage to be zero

The backfill issues `current_vintage` and `capture_bounded` only. The tempting
promotion is `filing_published_at`, which is populated on most rows and would lift
true-PIT from nothing to nearly everything in one run — and would be wrong.
That column describes when the **original filing for the period** was published; a
later content hash is a different artifact and inherits none of its authority.
Promoting on it reintroduces the look-ahead this table removes while looking like
a coverage win.

True-PIT arrives only from a source that can point at the version's own
publication artifact. Until such an adapter exists, `TRUE_PIT_ONLY` replays are
expected to return **empty**, and that is the correct answer rather than a fault.

## Running the backfill

Zero provider calls — it reads stored rows and writes derived claims, so it is not
on the UW budget and can run at any hour.

```bash
uv run python scripts/backfill/fundamental_observation_availability.py
uv run python scripts/backfill/fundamental_observation_availability.py --tickers NVDA,MSFT
uv run python scripts/backfill/fundamental_observation_availability.py --batch-size 5000 --max-batches 4
```

Re-running is a no-op: every claim is written under a deterministic `claim_key`
with `ON CONFLICT DO NOTHING`. The walk is keyset over `obs_id`, so forward ingest
appending rows mid-run cannot cause a skip. `--max-batches` bounds one invocation
so a slice can be inspected before resuming; it changes how much is classified,
never how.

## Inspecting coverage

```bash
uv run python scripts/backfill/fundamental_observation_availability.py --counts
```

Reports rows per class plus **unclaimed observations** — the number the backfill
exists to drive to zero. An unclaimed row is invisible to every historical policy.

## Correcting a claim

You cannot. There is no update path, by design: a replay of a rule can only fail
to add a row, never revise what that rule previously concluded. A wrong rule is
fixed by writing a new rule version (`…:v2`) whose claims land **beside** the old
ones. This is what preserves the record of what Argon believed and when.

## Not a data-gap-healer dataset

`fundamental_statement_obs` **is** registered with the healer — a missing quarter
there is healed by re-fetching from UW. Its availability claims are derived from
rows already held: no provider to re-fetch from, no calendar spine to be short of.
A gap is repaired by re-running the backfill above, so this table has no
`DatasetRegistryEntry` (same reasoning as migration 113).

## Related

- Vocabulary and policies: `src/uw_scan/fundamentals/observation_time.py`
- Schema and rationale: `src/uw_scan/storage/migrations/130_fundamental_obs_availability.sql`
- Read contracts: `src/uw_scan/storage/fundamental_observation_panels.py`
