# Fundamental observation availability — coverage audit

**Status: RUN against production 2026-08-24. Self-checks passed. Results below.**

Artifact: `coverage.json` (host `100.66.147.98`, database `option_wizard`, code
`86161f1d`, completed `2026-08-24T15:01:15Z`).

## Results

| | |
|---|---|
| Observations | 89,758 across 420 tickers |
| Period span | 1998-03-31 → 2026-07-31 (29 years) |
| **Capture span** | **2026-08-16 → 2026-08-23 (8 days)** |
| Claims written | 179,516 (89,758 `current_vintage` + 89,758 `capture_bounded`) |
| `true_pit` | **0** |
| Unclaimed observations | 0 |
| Multi-version identities | 200 (405 rows, 42 tickers, periods 2006-09-30 → 2026-07-31) |
| Self-check | passed, no problems |

Backfill: 18 batches, 23.6s, zero provider spend. Re-run inserted **0** and
reported 89,758 already present — idempotency confirmed against production.

## Finding 1 — the ordering bug had ZERO measured effect on the current panel

Comparing, over all 200 multi-version identities, the version `ORDER BY obs_id
DESC` selects against the version availability ordering selects:

```
obs_id pick != availability pick:  0 / 200
```

This is not luck, and it is not a reprieve. `capture_bounded` availability IS
`first_observed_at`, and `obs_id` is a BIGSERIAL assigned at the same insert — the
two are monotonic with each other **by construction**. Capture-bounded selection
can therefore never disagree with `obs_id DESC`, on this data or any other.

The divergence the contract exists to prevent only becomes possible once
`true_pit` claims exist, because a publication date is sourced independently of
capture order. Until such an adapter lands, the as-of reader's *selection* is
order-equivalent to the old behaviour.

**The premise in the plan and handoff — that a 2023-captured restatement was
already contaminating a 2021 replay — is not what production shows.** Every row
was captured in the same 8-day window, so no such split exists. Recorded as a
correction, not a footnote.

## Finding 2 — what DID change is the refusal, and it bites hard

The old reader had no cutoff at all: it answered every historical question with
today's panel. The new one fails closed. Measured on 5 names:

| Cutoff | `capture_bounded` | `true_pit_only` |
|---|---|---|
| 2020-06-30 | **0 tickers, 0 periods** | 0 |
| 2026-08-15 | **0 tickers, 0 periods** | 0 |
| 2026-08-20 | 5 tickers, 404 periods | 0 |
| 2026-08-24 | 5 tickers, 404 periods | 0 |

At 2020-06-30 the old path would have served 404 periods of balance-sheet data.
Every one of those figures was captured in August 2026. The old answer was
fiction; the new answer is an honest refusal.

## Finding 3 — 97.8% of the score history cannot be replayed

`fundamental_scores` holds 33,283 rows spanning `as_of` 2005-12-15 → 2026-08-21.

| | rows | share |
|---|---|---|
| `as_of` **before** first capture (2026-08-16) | **32,557** | **97.8%** |
| `as_of` at or after first capture | 726 | 2.2% |

Those 32,557 rows are not wrong in the sense of using the wrong version — Finding
1 rules that out. They are *unsupported*: there is no evidence that the content
behind them was available at the date they are stamped with, because the evidence
for every version begins 2026-08-16. They remain correctly labelled
`current_vintage`, which is exactly what they are.

**This is the real state of replayable fundamental history: it starts 2026-08-16,
not 1998.** That was true before this work and invisible; it is now measured.

## What would change it

Only a source that can point at a version's own publication artifact. The
tempting shortcut is `filing_published_at`, which is populated on most rows and
would take `true_pit` from 0 to nearly 89,758 in one run — and would be wrong, for
the reason in the runbook: it describes the *original* filing for the period, not
the later content hash. That shortcut is what this table exists to make
unavailable.

## What the audit answers

Pre-Job 0 gave every statement content version an availability class. The only
question that matters afterwards is: **how much of the panel can support a
historical replay at all?** (Answer, measured: nothing before 2026-08-16.) The
artifact reports:

- rows and distinct tickers per `evidence_class` × source × statement ×
  `period_type` × period year;
- earliest and latest `available_at` within each of those cells;
- identities carrying more than one content version, and how many rows they hold
  — the only population where the two readers can disagree;
- observations carrying no claim at all;
- `true_pit` claims with no artifact reference or no instant;
- untimed claims illegally carrying an instant;
- the host, database, schema, git commit, exact command, and completion time.

## Reproduce

```bash
uv run python scripts/backfill/fundamental_observation_availability.py \
  --audit docs/research/2026-08-24-fundamental-observation-availability/coverage.json
```

Read-only: it writes the JSON file and touches no table. It exits non-zero when a
self-check fails, so it is safe to wire into a check.

Classification must have run first (see
`docs/runbooks/fundamental-observation-availability.md`), otherwise the audit
correctly reports every observation as unclaimed.

## The self-checks

`fundamentals.observation_time.audit_violations` refuses a report when:

1. per-class counts do not sum to the table's claim count;
2. a class outside the four-name vocabulary appears;
3. a `true_pit` claim carries no artifact reference or no instant — true-PIT is a
   claim about a specific publication and must point at it;
4. a `current_vintage` / `unknown` claim carries `available_at`;
5. an observation carries no claim at all;
6. an as-of selection returned a version whose `available_at` is past its cutoff.

Each is a way the classification could be quietly wrong while every count still
looked plausible. A coverage report nobody can falsify is a press release.

## Why `true_pit` is zero (predicted, then confirmed)

**`true_pit` coverage is zero.** No rule over stored rows can produce
version-level publication evidence, and the one column that looks like it could —
`filing_published_at` — describes the _original_ filing for the period, not the
later content hash. Promoting on it would lift true-PIT from nothing to nearly
everything in one run and would be wrong in exactly the way this work exists to
fix. See the runbook for the full argument.

So the expected shape is: every observation `current_vintage`, most also
`capture_bounded` at their capture instant, zero `true_pit`. Which means
**`TRUE_PIT_ONLY` replays return empty until a publication-evidence adapter
exists**, and `CAPTURE_BOUNDED` replays are bounded below by when Argon first saw
each version — not by when the market saw it.

That is a real limit on what history can currently be replayed, and naming it is
the point of the audit. It is not a defect introduced by this work; it is the
pre-existing state, now measurable.

## Related

- Runbook: `docs/runbooks/fundamental-observation-availability.md`
- Vocabulary: `src/uw_scan/fundamentals/observation_time.py`
- Schema: `src/uw_scan/storage/migrations/130_fundamental_obs_availability.sql`
- Plan: `docs/plans/2026-08-24-fundamental-observation-asof.md`
