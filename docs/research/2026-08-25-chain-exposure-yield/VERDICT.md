# Chain exposure is 1.3% disclosed — the schema is what makes that visible

**Measured 2026-08-25** on `option_wizard_local` under taxonomy
`argon-research-v1`. Artifact: `coverage.json`.

Reproduce:

```bash
uv run python scripts/backfill/research_taxonomy_seed.py
uv run python scripts/backfill/research_taxonomy_seed.py --measure
```

## The finding

| | |
|---|---|
| chains | 39 |
| memberships | 316 |
| with a role-level exposure | 316 |
| **with a DISCLOSED economic magnitude** | **4 (1.3%)** |

Argon's chain product is almost entirely **semantic placement**. Only four
company-chain pairs in the whole taxonomy carry a number that a filing actually
disclosed.

## Why the yield is this low

Measured on `revenue_breakdown_obs` (63,567 rows, 400 tickers): the dominant
XBRL business-segment tag is the **generic** `ReportableSegmentMember`, present
for 47 tickers. The chain-relevant names — `datacentermember`,
`semiconductormember`, `datacenternetworkingmember`,
`communicationssolutionssegmentmember` — appear on **one or two filers each**.

Most companies do not disclose segments whose names identify a chain. That is a
fact about US segment reporting, not a gap in the ingest, and no amount of
pattern-tuning changes it. A larger alias list would only manufacture apparent
coverage by matching loosely.

## What the schema does about it

Migration 140 carries a CHECK that permits a non-NULL `magnitude` **only** when
`status='disclosed'` AND `magnitude_basis` names an evidenced kind. The 312
rows without a disclosure physically cannot hold a number.

That constraint is the deliverable. Without it, those 312 rows would have been
filled with plausible hand-typed percentages, every chain aggregate built on top
would have inherited the fiction, and nothing downstream could have detected it —
a typed 38% renders identically to a 38% read off a segment disclosure.

A derived magnitude is auditable in **both** halves: `source_obs_id` names the
observation that produced the number, and `chain_segment_alias` names the
published rule that produced its attribution to a chain. The judgement is
recorded, not hidden inside the value.

## M5.5 extensibility proof

The optical-communication chain (5 layers, 17 members across upstream
components, DSP/switch silicon, modules, systems, and cloud customers) was added
as **rows only** — `research_chains`, `chain_membership`, and
`chain_segment_alias` entries in `scripts/backfill/research_taxonomy_seed.py`.

No new table, no new job, no scoring fork, no domain-specific orchestration. If a
special case had been needed, it would have had to appear in that script or in a
migration, and it does not.

Of its 20 seeded memberships (17 in the universe), **1 carries a disclosed
magnitude**.

## What this does NOT establish

- **No causal claim.** `layer_rank` orders layers upstream → downstream as a
  READING order. Nothing propagates along it, and the measured basis for that
  restraint is the capex-demand ledger: its cross-name relationship collapsed
  from +0.247 to +0.015 (p=0.44) once same-SECTOR pairs were compared, which is
  the finding that a chain, as membership, is a sector by another name.
- **No supplier/customer relationship.** Every seeded exposure has a NULL
  `counterparty`. A named edge needs a named source, and none was available.
- **Chain aggregates are attention routing, not chain-level alpha.** A cell's
  `priority_mean` is the mean of a `research_priority` dimension over members,
  and it inherits that ceiling exactly.
- **Cells with fewer than 3 members carrying a compatible result abstain.** A
  mean over one name is that name's number wearing a chain's label.
