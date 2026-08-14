# Official SEP HTML format families (MC1 Task 4)

**Measured:** 2026-08-14 · **Scope:** every SEP release discoverable for 2020–2026 (25 releases)
**Status:** evidence for Task 4 only. It does **not** promote `VERDICT.md`, which stays PARTIAL
until Task 9 proves the persisted worker → DB → API path.

## Why this was needed

The pre-Task-4 handover recorded "5 SEP semantic errors". That figure counted the **acquisition**
layer only (25 discovered candidates → 20 constructed bundles). Running the **semantic** parser
across every discovered release showed a far worse baseline:

| Layer | Before Task 4 | After Task 4 |
|---|---|---|
| Discovery candidates | 25 | 25 |
| Acquisition bundles | 20 | 25 |
| `parse_sep_release` success | **1 / 25** | **25 / 25** |

Only `fomcprojtabl20260617` — the single pinned fixture — parsed. Every other official release in
the 2020+ archive failed.

## Root-cause families

Each was a genuine publisher format that the parser had never seen, not publisher drift. All five
are now explicit supported families; none was fixed by relaxing a selector.

| # | Root cause | Releases | Resolution |
|---|---|---|---|
| 1 | Summary table headed `Advance release of table 1 …`, not `Table 1.` | 2020-06, 2020-09 | bounded heading family |
| 2 | Horizon count hard-coded to 4 (Table 1 width 12/13, Figure 2 width 5) | all September + all December (11) | horizon count derived from the header and checked against the publisher's own three-fold repeat |
| 3 | `_range` split on the first `-`, so any negative lower bound mis-parsed | every COVID-era negative projection | anchored numeric grammar |
| 4 | December pages declare `EDT` although December is `EST` | 2020-12, 2021-12, 2022-12, 2024-12, 2025-12 | instant resolved in `America/New_York`; label disagreement retained as audit metadata |
| 5 | Prose participant total was required, but 24 of 25 pages state none | 24 | Figure 2 dot table is the primary count source; prose is a cross-check keyed to this release's own meeting |

### Family 3 — the two dashes are not interchangeable

Range cells use **U+2013 (en dash)** and **U+002D (hyphen)** interchangeably *as separators*, while
negative bounds always use U+002D. So neither "split on `-`" nor "split on `–`" is correct:
`-0.2–1.3` (2023-03) and `-2.5--2.2` (2020-12) both defeat a dash split. Bounds are therefore
matched against `-?(?:\d+(?:\.\d+)?|\.\d+)` anchored on both sides. Validated against all 1,070
non-empty central-tendency and range cells in the archive: zero unmatched.

### Family 4 — the label is wrong, the wall clock is right

For the **same release event** on 2025-12-10 the FOMC statement declares `2:00 p.m. EST` while the
SEP declares `2:00 p.m. EDT`. EDT does not exist in December, so the SEP label is stale boilerplate
rather than a different instant. Obeying the literal label would place availability at 18:00 UTC
instead of 19:00 UTC — **an hour early**, which would leak a not-yet-published release into
point-in-time replay. The instant is therefore the published wall clock resolved in
`America/New_York`, and `declared_timezone` / `calendar_timezone` are both retained so the
disagreement stays auditable instead of being silently normalised away.

### Family 5 — blank cells are all-or-nothing

Across the archive, a variable/horizon cell group is either fully populated (535 cases) or fully
blank (25 cases — core PCE inflation has no longer-run projection). There is **no** partially blank
group. The parser therefore skips a fully blank group and fails closed on a partial one, which
would signal real layout drift.

## Verification

* Offline, per family, from exact official bytes pinned in `tests/fixtures/macro/manifest.json`:
  `uv run pytest tests/unit/sources/test_fed_sep.py -q` → 20 passed.
* Live, read-only, all 25 official releases parsed: 25/25, every instant 14:00 Eastern, and
  projection counts self-consistent at `5 variables × horizons − 1` (19 for four-horizon releases,
  24 for five-horizon).

The live all-release sweep currently has no committed runner; Task 8 builds the resumable
production audit that emits one deterministic record per discovered release.
