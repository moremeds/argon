# SEC publication evidence — replayable fundamental history goes from 8 days to 22 years

**Measured 2026-08-25** on `option_wizard_local` (87,177 statement observations,
401 tickers in the `ranked` tier). Artifact: `coverage.json`.

Reproduce:

```bash
uv run python scripts/backfill/sec_publication_evidence.py --index --only-missing
uv run python scripts/backfill/sec_publication_evidence.py --evidence
uv run python scripts/backfill/sec_publication_evidence.py --measure
```

## The finding

`true_pit` went from **0 to 73,994 claims** across **396 of 401 tickers**,
spanning period ends 2003-12-31 → 2026-07-31 with publication dates 2004-06-18 →
2026-08-22.

Before this work, every leak-free (`TRUE_PIT_ONLY`) replay returned **empty at
every cutoff**, and `CAPTURE_BOUNDED` returned empty before 2026-08-16 — because
the entire statement table was captured in one 8-day backfill and the only
availability evidence Argon held was "when we fetched it".

## Yield and refusals

| | count | share |
|---|---|---|
| identities examined | 86,951 | |
| **matched** | **73,769** | **84.8%** |
| `no_filing` | 10,335 | 11.9% |
| `amended` | 2,210 | 2.5% |
| `no_index` | 633 | 0.7% |
| `ambiguous` | 3 | — |
| `multi_version` | 1 | — |
| `filed_before_period` | 0 | — |

`no_filing` dominates the refusals and is mostly **structural, not a matching
bug**: 20-F annual filers have no quarterly filing for a quarterly period to
match against. `amended` is the rule working as intended — UW serves *current*
data, so for an amended period the single version Argon holds may be the restated
content, and dating it at the original filing would be look-ahead wearing SEC's
authority.

Per-ticker `true_pit` coverage: **240 tickers ≥90%**, 107 at 50–90%, 49 below
50%, and **5 with none**.

## The replay actually deepens

Scoring under `TRUE_PIT_ONLY` at three historical cutoffs, engine
`fundamentals-v2:77aea364`:

| cutoff | buckets | scored | `excluded_no_evidence` |
|---|---|---|---|
| 2015-06-30 | 38 | 9,592 | 19,464 |
| 2020-06-30 | 58 | 15,626 | 13,369 |
| 2024-06-30 | 74 | 21,175 | 7,772 |

`excluded_no_evidence` shrinking monotonically as the cutoff advances is the
signature of an honest as-of reader. A leaking one returns today's panel at every
date, so its exclusions would be flat.

Single-name check (NVDA balance sheets admitted under `TRUE_PIT_ONLY`):
11 periods at a 2010 cutoff, 31 at 2015, 51 at 2020, 63 at 2023, 75 at 2026.

## What this does NOT establish

- **It does not validate any signal.** It makes a leak-free measurement
  *possible*; every existing fundamental verdict was computed on `filing_date`
  and still carries whatever restatement contamination it always did.
- **It does not cover 100%.** 13,182 identities (15.2%) keep only
  `capture_bounded`, and a `TRUE_PIT_ONLY` replay correctly refuses them.
- **`available_at` is end-of-day UTC on the filing date.** SEC publishes a date,
  not a timestamp, so a same-day cutoff admits the filing and an earlier one does
  not. Intraday precision is not claimed.
- **An amended period is refused, not approximated.** Argon holds one content
  version and cannot tell whether it is the original or the restatement.
