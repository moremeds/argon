# Macro legacy inventory — MC0 baseline

This directory is the measured dual-read baseline for migrating Argon's existing rates and gold
data into the immutable macro evidence contract. It is an inventory of the local development warm
store, not a claim about the Mac mini production database.

## Scope and safety

- Database: `option_wizard_local`
- Schema: `uw_scan`
- Access: one repeatable-read, read-only transaction
- External provider calls: zero
- Relations: 18 tables plus the `wgc_etf_monthly_canonical` view
- Snapshot date: generated on 2026-08-12 from the local database state

The script refuses any database name other than `option_wizard_local`. Automated tests remain on
`option_wizard_test`; the inventory never runs migrations or writes application rows.

## Reproduce

```bash
uv run python scripts/research/macro_legacy_inventory.py --self-check
uv run python scripts/research/macro_legacy_inventory.py
```

The first command proves required-relation coverage, deterministic JSON ordering inside one database
snapshot, read-only mode, and zero external calls. The second regenerates `inventory.json`.

## Artifact map

- `inventory.json` — machine-readable row counts, primary keys, date spans, per-series spans,
  observed dimensions, time/revision semantics, consumers, risks, and adapter actions.
- `VERDICT.md` — migration judgment and the ordered acceptance baseline for MC1–MC3.

## Interpretation boundary

Row counts and observed source/series values are current local facts and will drift. Contract fields
are reviewed repository semantics. A non-empty table proves only that local rows exist; it does not
prove that its source is currently reachable, official, durable, or point-in-time safe.
