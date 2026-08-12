# Macro Evidence Contract — Design

**Status:** MC0 implementation verified; live-source adapters and read cutover remain out of scope.

## 1. Purpose and boundary

This contract is the common point-in-time evidence substrate for inflation, policy/rates, USD, and
gold. It stores publisher artifacts and normalized observations without overwriting revisions, then
lets downstream engines replay only information that was available at a requested `as_of`.

MC0 does not change the current rates or Gold Compass read paths. It does not fetch a new provider,
compute a macro state, create a score, or write macro data into fundamental statement tables.

## 2. Time semantics

All instants are timezone-aware `TIMESTAMPTZ`; economic periods are `DATE`.

| Field | Meaning | Selection role |
|---|---|---|
| `period_end` | Economic period represented by an observation | identifies the measured period, never its knowledge time |
| `published_at` | Publisher-declared release instant, if known | provenance; may be null when the publisher supplies no reliable instant |
| `available_at` | Earliest instant the observation is allowed to enter an Argon decision | universal PIT predicate: `available_at <= as_of` |
| `first_observed_at` | First instant Argon successfully normalized this immutable observation | operational evidence; never substitutes for an earlier verified release time |
| observation `last_seen_at` | Latest instant Argon saw the identical immutable observation | idempotent sighting metadata only |
| artifact `retrieved_at` | First instant Argon retrieved the exact artifact bytes/text/JSON | immutable first-sighting audit and source-latency measurement |
| artifact `last_seen_at` | Latest instant Argon retrieved the identical payload | idempotent artifact sighting metadata only |

Examples:

- A January CPI value released on February 12 has January's economic `period_end`; its
  `available_at` is the verified February 12 release instant. A later corrected payload creates a new
  observation with its own correction `available_at` and content hash.
- A daily broad-dollar close uses that market date as `period_end`; `available_at` is the first
  defined post-close publication instant, not midnight at the start of the same date.
- A CFTC report keeps the Tuesday position date as `period_end`, Friday publication as
  `published_at`, and the strategy-safe configured lag as `available_at`. Downstream code never keys
  knowledge to Tuesday.
- An SEP projection uses the FOMC release date as the event `period_end`; `available_at` is the
  official release instant. A corrected official table becomes a new artifact and observation set.

When a publisher exposes only a release date, the adapter must apply a documented conservative time
rule and include that rule in `parser_version`. It may not guess an earlier intraday timestamp.

## 3. Immutable identities and hashes

Artifact identity is:

```text
(source, source_record_id, content_hash)
```

`source_record_id` is mandatory and stable within a publisher: release ID, accession, canonical
document URL, or another documented publisher key. Artifacts are domain-neutral because one official
release (especially an SEP) may supply observations to multiple domains. Artifact `content_hash` is
SHA-256 over the exact raw bytes; for native JSON it is over canonical UTF-8 JSON with Unicode code
point key ordering, normalized finite numbers, and no insignificant whitespace. PostgreSQL uses
`COLLATE "C"` to match Python ordering and rejects `NaN`/infinities at both function and table
boundaries. `content_length` is recomputed over the
same byte representation. A successful artifact stores exactly one of raw JSON, raw text, or raw
bytes. Binary PDF/XLSX payloads retain exact bytes.

Observation identity is:

```text
(source, series_id, period_end, available_at, content_hash)
```

Observation `content_hash` is SHA-256 over a canonical normalized record containing source identity,
series, period, frequency, unit, typed value, publication/availability time, artifact ID, and
`parser_version`. Therefore a mapper/parser change cannot silently reinterpret an old row: a changed
normalization produces a new immutable observation even when the raw artifact is unchanged.

An identical observation refresh may update only its `last_seen_at`; an identical artifact retrieval
may advance artifact `last_seen_at` while preserving the earliest `retrieved_at`. Database triggers
reject update/delete attempts against every other evidence field and recompute content identity, so
direct SQL cannot bypass repository validation.

## 4. Enumerated contracts

Domains:

```text
inflation | policy_rates | usd | gold | cross_domain
```

Source kinds:

```text
official | first_party_publisher | entitled_provider | third_party_shadow
mock | static | demo
```

`mock`, `static`, and `demo` are test-fixture identities. The database rejects them unless
`current_database()` starts with `option_wizard_test`, including isolated xdist databases. An
environment flag or caller argument cannot override this production boundary.

Quality status:

| Value | Meaning | Default PIT eligibility |
|---|---|---|
| `valid` | passed the adapter's required semantic and integrity checks | included |
| `partial` | usable subset with explicit omissions | included but confidence must reflect it |
| `invalid` | parsed but violates a required data rule | excluded |
| `quarantined` | schema/source identity is uncertain pending review | excluded |

Cost class:

```text
free_official | free_publisher | already_entitled
free_third_party_shadow | paid_authorized
```

The class records the capability used for this observation. It is not inferred from provider name.
Yahoo/yfinance is prohibited regardless of cost.

Frequency:

```text
daily | weekly | monthly | quarterly | annual | event | irregular
```

Every observation has a non-empty unit and exactly one typed value: numeric, text, or JSON.

## 5. PIT resolution and disagreement

The default usable set requires both artifact and observation quality to be `valid` or `partial`,
both `available_at` values to be no later than `as_of`, and observation availability to be no earlier
than its artifact. A `valid` observation requires a `valid` artifact; a `partial` observation may use
a `valid` or `partial` artifact. For one source and period, the latest eligible `available_at` wins.
Across sources, the caller must pass a non-empty explicit ordered source list; unlisted sources follow
after listed sources and never displace a preferred source merely because they arrived later.

Canonical selection does not delete dissent. History queries return every vintage and source. A
downstream state records the chosen observation ID plus contradictory observation IDs and their
quality/source class.

## 6. Storage and API boundary

`macro_source_artifacts` owns exact publisher payload identity and retrieval metadata.
`macro_observations` owns normalized immutable values and PIT semantics. Domain outputs reference
observations through typed foreign-key association tables added with those outputs; opaque JSON ID
arrays are not authoritative provenance.

Repository methods live in `storage/macro_context.py` and are assembled into `Repository`; no query
methods are added directly to the aggregate shim. Public Pydantic models live in `models/macro.py`
and preserve `uw_scan.models` contract identity.

## 7. Dual-read migration

Existing `rates_observations`, policy tables, macro-series tables, and Gold Compass tables remain the
authoritative read models until each adapter passes all of:

1. row-identity parity for the intended source window;
2. value/unit parity or a documented intentional correction;
3. publication/availability-time parity;
4. revision-count and source-disagreement accounting;
5. downstream replay parity;
6. explicit feature-flag cutover and rollback test.

Migration is additive. Rollback selects the legacy read path; it never deletes MC0 observations.
The local `option_wizard_local` database is permitted for read-only inventory and non-destructive
smoke. Automated integration fixtures continue to use `option_wizard_test` because they drop the
entire `uw_scan` schema.

## 8. Failure behavior and observability

- Transport failures create request-audit evidence but no successful artifact.
- Empty payload, malformed payload, and valid zero observations are distinct outcomes.
- Parser/schema drift stores the raw artifact and marks normalized output quarantined or emits no
  observation; it never becomes zero/neutral.
- Hash conflicts, invalid enums, multiple value representations, and non-production fixture sources
  fail the write.
- Required telemetry includes artifact/observation insert counts, unchanged sightings, revisions,
  quarantines, invalid rows, source disagreements, newest `available_at`, and ingestion lag.

## 9. Acceptance tests

MC0 is verified only when tests prove:

1. identical artifacts/observations remain one logical row while their `last_seen_at` advances;
2. a revision creates a second row and historical `as_of` returns the predecessor;
3. official and shadow observations coexist while explicit precedence is deterministic;
4. invalid/quarantined observations are excluded by default;
5. mock/static/demo writes fail outside a test database;
6. timestamp-aware models reject naive instants and preserve typed values/IDs;
7. migrations are idempotent and legacy tables are unchanged;
8. both new temporal tables are registered in the dataset policy.
9. artifact hash/length and observation hash are recomputed in Python and PostgreSQL;
10. a domain-neutral artifact may supply multiple typed domains, but no observation may outrun its
    artifact's availability or quality.
