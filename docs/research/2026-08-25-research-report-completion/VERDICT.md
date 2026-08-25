# Program completion test — the north-star question, answered end to end

**Date:** 2026-08-25
**Spec:** `docs/superpowers/specs/2026-08-24-fundamental-pm-research-system-design.md` §20
**Artifact:** `completion.json` (every check, its evidence, and its verdict)
**Reproduce:**

```bash
uv run python scripts/research/research_report_completion_test.py \
  --chain Optical-Communication --as-of 2026-08-25 \
  --out docs/research/2026-08-25-research-report-completion/completion.json
```

## The question

> Research a company, compare a group of companies, or map a narrow industry
> chain as of a stated date. Show the operating evidence, valuation, research-
> priority dimensions, catalysts, risks, chain exposures, disagreements, missing
> data, and what would invalidate the thesis. Preserve the answer as a versioned
> report that can later explain what changed.

Asked as: a US optical-communication chain research report as of 2026-08-25.

## Verdict: 10 of 10 checks pass

| Check | Result | The number that carries it |
|---|---|---|
| deterministic | PASS | two dry assemblies hash `0aa3559f96fcd68d…` |
| scope_frozen | PASS | manifest carries engine, taxonomy, evidence policy, as-of, assembler |
| coverage_disclosed | PASS | 17 members, 17 with exposure, **1 with a magnitude**, 16 with a result |
| unsupported_declared | PASS | 8 killed event classes + 3 descriptive-only dimensions, at ordinal 1 |
| within_claim_permission | PASS | ceiling `research_priority`; no block above it |
| provenance_preserved | PASS | 6 of 6 blocks name evidence or a derivation |
| versioned_with_delta | PASS | v2 published, v1 superseded, delta names 4 moves |
| old_version_replays | PASS | v1 rehashes to `4dd820509a338d39…` from stored blocks |
| reproducible_without_models | PASS | no model, HTTP, or subprocess import in the assembly path |
| no_trade_decision | PASS | 0 hits across 11 trade words in every string the report emits |

## What the report actually says about optical communication

**17 companies, 20 placements** across 5 layers (Upstream-Components,
Semi-DSP-Switch, Module-Transceiver, Systems-Networking, Customer-Cloud). Three
names sit in two layers each, which is why the placement count and the company
count are printed as separate fields rather than left to be discovered by
subtraction — see the defect below.

**Exposure is asserted for 17 of 17 and quantified for 1.** APH discloses 61.5%
via `segment_share`; CIEN 1.5%. Sixteen memberships carry a role and no number.
That ratio — 1 in 17 — is the report's most load-bearing sentence, and it is
printed in the coverage block rather than inferred from an empty column.

**The aggregate abstains below three members and does not here:** priority mean
0.141 over 16 companies, one vote each. It orders attention, and the block's
`authority` field says `research_priority` — the strongest permission this
program earned, and one the store cannot exceed because a CHECK constraint makes
`investment_ranking` unrepresentable.

**What it cannot answer is a section, not a footnote.** Eight event classes are
killed and named in the report itself: `backlog`, `capex_guidance`,
`customer_concentration`, `debt_maturity`, `management_guidance`,
`supplier_relationship` (all live in SEC document TEXT, which Argon does not
fetch), `product_regulatory` (needs a licensed news source), and `restatement`
(killed at n=1 — a class that fires once is an anecdote). Three dimensions are
capped at descriptive: `operating_quality`, `revenue_concentration`,
`evidence_quality`.

For a supply-chain report, that list is the honest headline. A reader of a
chain map with no supplier relationships in it is told the reason is Argon's
ingest, not the industry's structure.

## The defect this test found

The first assembly published **`with_compatible_result` 19 against `members`
17** — a numerator larger than its own denominator, printed as fact.

`chain_membership` is grained `(chain, layer, ticker)`. `exposure_coverage`
collapses to distinct tickers; the assembler counted rows. A company placed in
two layers therefore inflated the numerator and **voted twice in the aggregate
priority mean**. Both are now taken over distinct tickers, with placements
reported as their own field.

The fix is itself the clearest demonstration of why versions exist: v1 still
holds 20/19, v2 holds 17/16, and the delta names every field that moved. A
dashboard would have silently started showing 17 with no trace it ever said 20.

Regression test: `tests/integration/storage/test_research_reports.py::
test_a_chain_report_counts_companies_not_placements` — AVGO in two layers,
asserting `with_compatible_result <= members`.

## What this does NOT establish

- **Nothing here is a measured edge.** Every check is about honesty of
  construction — determinism, denominators, provenance, permission. The
  underlying claims keep the standing their own verdicts gave them: the
  composite orders names cross-sectionally (rank IC 0.039, t 2.67) and cannot
  time one name against itself; own-history valuation times a name
  (`sales_to_ev` +0.0744, t 5.77); chain membership has demonstrated no causal
  edge at all (capex-demand ledger: +0.247 → +0.015, p=0.44 among same-sector
  pairs).
- **`evidence_policy` is `current_vintage`,** not `true_pit_only`. The chain
  report answers today's question with today's panel. A leak-free historical
  replay is available (M1 built it; 73,994 `true_pit` claims over 396 tickers)
  but is not what this report requested.
- **One quantified exposure out of 17 is not a chain map**, it is a membership
  list with one measurement in it. The report says so; it does not pretend the
  other 16 roles carry economics.
