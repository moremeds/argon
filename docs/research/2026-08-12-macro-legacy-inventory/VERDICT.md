# Verdict — legacy rates/gold is usable as a read model, not as the macro evidence ledger

**MC0 inventory result:** PASS for coverage and reproducibility; FAIL for direct cutover.

The local snapshot covers all 19 declared rates/gold relations in a repeatable-read transaction and
makes zero provider calls. Existing pages should remain on their legacy read paths. The new evidence
tables can receive dual writes, but none of the legacy domains yet meets publication-time, revision,
artifact-lineage, and replay parity together.

## Load-bearing findings

1. **Rates vintages are overwritten.** `rates_observations` has 3,535 rows across 31 series, but its
   primary key is `(series_id, obs_date, source)` and the writer updates value, `realtime_start`, and
   `realtime_end` in place. An updated FRED or Cleveland Fed value destroys the predecessor. This is
   the first MC1 adapter because it blocks honest historical `as_of` reconstruction.

2. **FOMC coverage is calendar-only.** `rates_policy_events` contains 24 meeting-date rows, but no
   statements, minutes, vote records, transcripts, SEP tables, or dot-plot artifacts. Its
   `(event_date, source)` identity also overwrites changed payloads. The FOMC/SEP adapter must be
   artifact-led and must preserve each official publication/correction separately. A chair's view of
   the dot plot is commentary metadata, not a reason to erase the official SEP evidence channel.

3. **The implied policy path is a shadow source.** `rates_policy_path` contains 40 rows from a free,
   delayed third-party FedWatch page. It is useful as a labeled market-expectations shadow, but it is
   neither a Federal Reserve source nor a substitute for meeting artifacts. Same-day corrections can
   overwrite because the key has day rather than publication instant/hash granularity.

4. **Gold macro data mixes source classes.** `macro_series_daily` holds 72,929 rows across 17 series
   from FRED, GPR, and Massive; `macro_series_monthly` holds CPI and M2. The tables preserve repeated
   `as_of` pulls but have no artifact hash/parser version, and nullable `release_date` means `as_of`
   cannot safely stand in for public availability.

5. **WGC lineage is large but not fully durable.** `wgc_etf_monthly` has 1,338,260 rows across 78
   workbook URLs, while its canonical view collapses to 26,460 latest rows. This is intentional
   revision preservation at the file-URL level, but the view is latest-wins rather than PIT, and a
   same-URL workbook replacement can overwrite normalized values. The observed URLs point into old
   local worktrees rather than a durable artifact store.

6. **Central-bank reserves contradict the old empty-table assumption.** The local table contains
   2,827 rows for 27 countries, all tied to one `/tmp` workbook path. The scheduled anonymous WGC
   source is still blocked, so these rows are useful research input but not durable production
   provenance. MC3 must either store the exact workbook bytes or replace it with a proven free
   official source; it must not silently call the local import "live WGC".

7. **Derived pages already carry some replay scaffolding, but not evidence IDs.** `gold_posture_daily`
   has 115 rows and `rates_snapshots` has 23. Gold pins legacy coordinates in `inputs_jsonb`; rates
   embeds values in a payload. Both remain useful read models, but neither is sufficient as an
   immutable upstream ledger.

## Adapter order and acceptance baseline

| Priority | Adapter | Required proof before read cutover |
|---|---|---|
| P0 | FRED/Cleveland rates | preserve every revised value; explicit `available_at`; row/value/unit/vintage parity |
| P0 | FOMC + SEP | exact official bytes, statement/minutes/votes/SEP taxonomy, correction history, conservative release time |
| P1 | CPI/M2 and daily macro | per-series source/cost mapping; no inference of availability from ingestion time |
| P1 | CFTC TFF and gold COT | position date distinct from publication/strategy availability; exact official artifact link |
| P1 | Treasury auctions/FiscalData | official response artifact plus normalized row parity |
| P2 | ETF holdings/flows, LBMA/COMEX | exact issuer/exchange payload; source-specific units and publication clock |
| P2 | WGC ETF/central-bank corpus | content-hashed workbook bytes; PIT revision selector; durable source identity |
| P3 | gold posture/rates snapshot | observation/evidence IDs embedded in derived output; replay and rollback parity |

For every adapter, the legacy relation stays authoritative until row identity, values/units,
publication/availability time, revision counts, source disagreement, downstream replay, and rollback
all pass. Empty/new evidence tables are not a cutover signal.

## Self-check evidence

```text
Pytest: inventory contract tests passed
self-check ok: 19 relations, read-only, deterministic, 0 provider calls
```

The inventory is intentionally local-only. A later Mac mini audit must compare relation coverage,
spans, sources, and overwrite counts; it must not replace or edit this frozen baseline.
