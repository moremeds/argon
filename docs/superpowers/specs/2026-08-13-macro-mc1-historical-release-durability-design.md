# Macro MC1 Historical Release Durability — Design

**Status:** Approved for implementation on 2026-08-13.

## 1. Goal and acceptance boundary

MC1 must turn official FOMC decisions and Summary of Economic Projections (SEP) releases into a
durable, point-in-time policy record from **2020-01-01 through the present**. The window deliberately
includes the COVID emergency-policy regime and the 2022 tightening cycle. It covers:

- every regular FOMC policy statement discovered from the Federal Reserve's official calendars;
- every unscheduled-meeting or notation-vote policy statement discovered from official 2020+
  history pages;
- every official SEP release in that window;
- the latest official New York Fed Survey of Market Expectations dealer path; and
- the free third-party market-implied shadow, kept visibly separate from official evidence.

The batch does not combine the four paths into a score and does not add a rates/gold UI. It hardens
the evidence foundation that a later top-down UI and the Foundmetal PM agent will consume.

MC1 remains **PARTIAL** until the all-release source audit has zero unexplained parser failures and a
real worker-to-database-to-API run returns all four independent paths. A green unit suite alone is not
a market-data verdict.

## 2. Observed failures that drive the design

The first real 2026 worker run retained artifacts but produced only two of four paths:

| Source | Artifacts | Observations | Result |
|---|---:|---:|---|
| FOMC statements | 10 | 0 | one unsupported Unicode target-range form rolled back the batch |
| SEP | 4 | 0 | March omitted the prose participant-count declaration expected by the parser |
| NY Fed SME | 2 | 1 | usable dealer path |
| market shadow | 1 | 1 | usable delayed market path |

A broader FOMC audit discovered 45 releases for 2021–2026 but parsed only 17. It discovered no 2020
releases because the provider reads only the current calendar surface. The failures cluster around
historical phrase families and non-ASCII fractions/hyphens, not absent official decisions. SEP
historical discovery can also abort while constructing a bundle when a publisher timezone label does
not match the library's New York daylight-saving expectation.

These are evidence-contract failures: a valid old publication format must not disappear, and one bad
release must not erase successful releases from the same run.

## 3. Approaches considered

### A. Patch the two 2026 strings

Add one Unicode replacement and special-case the March SEP page. This is small, but it leaves 2020
undiscovered, most of 2021–2025 unverified, and batch-wide rollback intact. Rejected.

### B. Persist only the latest successfully parsed snapshot

This would make the current API look healthy but would discard the COVID and hiking-cycle record,
hide corrections, and prevent point-in-time replay. Rejected.

### C. Full official-release ledger with format-family parsers

Discover every official 2020+ release, retain exact bytes before normalization, parse documented
historical format families, isolate each release transactionally, and keep immutable artifact and
observation revisions. This is the selected approach.

## 4. Discovery and stable release identity

The current FOMC calendar and the bounded historical-year URL for each requested past year are
discovery surfaces. The historical URL is always attempted, but the Federal Reserve currently
serves the 2020 page while some later year URLs return 404. Discovery therefore returns immutable
page-level outcomes (`ok`, `not_found`, or `error`) alongside candidates; it never fabricates an
archive page and never hides a failed attempt in mutable provider state. A failed historical page is
non-fatal only when the current calendar supplies same-year, same-release-type coverage. Otherwise
the result is explicitly coverage-incomplete and provider acquisition refuses to report empty
success. Task 8 may persist these page outcomes as operational audit state.

Discovery must follow only Federal Reserve links and must de-duplicate releases using stable keys:

```text
fomc-statement:<publisher-document-id>
fed-sep:<publisher-document-id>
```

For example, the March 15 emergency decision is
`fomc-statement:monetary20200315a`, and the June SEP is
`fed-sep:fomcprojtabl20200610`. The event/meeting date is stored separately. This avoids assuming
that a calendar date can never contain more than one official document.

The one bounded SEP HTML spelling alias `fomcprojtableYYYYMMDD.htm` is accepted and canonicalized
to the publisher identity `fomcprojtablYYYYMMDD`; PDF identity remains the canonical stem. Host and
date coherence remain strict, and no other stem approximation is allowed.

Statement discovery records the official index's event class: `scheduled_meeting`,
`unscheduled_meeting`, or `notation_vote`. This is an auditable publisher classification;
subjective labels such as `COVID era` or `hiking era` are downstream analysis and are not written
into immutable official facts.

Every statement candidate has a non-null official event class. SEP candidates have no statement
event class and therefore store null. The candidate validator and database constraint both enforce
this release-type/event-class invariant so incomplete or contradictory classifications cannot enter
the operational ledger.

Discovery is complete only when the current calendar and every requested past-year URL have explicit
page outcomes, every requested year has candidate coverage for the requested release type, and each
candidate has an explicit per-release outcome. Compatible current/history candidates merge by
release key and complementary HTML/PDF URLs; incompatible identity, classification, or competing
non-null URLs fail explicitly. Missing HTML or PDF pairs are release failures, not silently filtered
rows. The ledger may retain a release even when fetching or parsing it fails.

## 5. Raw evidence and revision semantics

Existing `macro_source_artifacts` and `macro_observations` remain the authoritative immutable
evidence ledger:

- exact HTML and PDF bytes are stored before the semantic parser runs;
- `(source, source_record_id, content_hash)` identifies one publisher artifact revision;
- an unchanged rerun advances only sighting metadata and creates no duplicate fact;
- changed bytes under the same stable release key create a new artifact revision;
- normalized output always references the exact artifact revision from which it was derived;
- a changed normalized meaning or safe availability time creates a new observation and never
  overwrites the predecessor;
- a raw-byte-only HTML change that parses to identical facts does not manufacture a new policy
  observation, but the new raw artifact and its parse outcome remain auditable.

Acquisition/canonicalization version and semantic parser version are separate contracts. An exact
HTML/PDF artifact keeps the acquisition version that describes how its bytes were captured; a
normalized observation carries the semantic parser version that interpreted those bytes. Upgrading a
semantic parser must therefore be able to reprocess an unchanged artifact without attempting to
mutate immutable artifact metadata. A parser-version-only change does not alter what the publisher
knew at release time, so `available_at` remains unchanged while `first_observed_at` records when
Argon produced the reprocessed vintage. Because the FOMC and SEP parsers read accessible HTML, their
observations reference the HTML artifact; the sibling PDF remains preserved corroborating evidence,
not a false claim that the PDF supplied the parsed fields.

Federal Reserve HTML contains request-varying delivery/footer bytes. Exact-byte identity is retained,
but semantic policy-observation identity is computed from normalized facts, source release key, time
semantics, and semantic parser version—not from the artifact surrogate ID. Before assigning a later
safe availability time, the worker compares the normalized fact payload with the prior release
observation. Identical facts attach lineage to the existing observation; changed facts create a new
observation available no earlier than the correction timestamp or first retrieval. A typed
observation-artifact lineage association records every exact raw revision that reproduced that
observation. This prevents both false policy revisions and loss of raw provenance. If an HTML
revision changes semantic output, it necessarily creates a new observation at a safe revision
availability time.

If the publisher explicitly timestamps a correction, that time becomes the new revision's
`available_at`. If bytes at an existing URL change without a declared correction time, the new
revision is not backdated: its safe availability is the first retrieval time. Historical backfill can
use an official archived release's declared publication time for the first recovered revision, while
`retrieved_at` and `first_observed_at` disclose that it is a retrospective reconstruction rather than
a contemporaneous capture. It can prove only the exact current archived artifact retrieved during
the backfill; it must not invent an unobserved pre-correction revision. Any later different hash is
available no earlier than an explicit correction time or Argon's first retrieval of that hash.

A new mutable operational table, `macro_release_ingest_status`, catalogs every discovered release
and its latest outcome. It contains the source, release key/type, event date, official event class,
discovery URL, last artifact revision, parser version, attempt/success times, and bounded error
details. This table is health/coverage state, not publisher evidence. It makes failed releases
queryable without weakening the immutable artifact/observation contract.

## 6. Text normalization and historical parser families

Normalization operates on a derived extraction string only; exact raw bytes and hashes never
change. The common normalizer will:

- apply Unicode compatibility normalization;
- convert non-breaking spaces to ordinary spaces;
- map Unicode hyphen/minus variants to ASCII `-`;
- convert vulgar fractions and the Unicode fraction slash to parseable ASCII fractions; and
- collapse extraction-only whitespace.

The numeric parser accepts integers, decimals, simple fractions, and mixed numbers such as `3-1/2`.
It rejects ambiguous or non-finite values.

FOMC parsing supports explicit historical wording families for maintaining/keeping, raising, and
lowering the target range. The result is still strict: action, lower bound, upper bound, vote status,
and release timestamp are validated; lower bound must not exceed upper bound; and the action must
agree with the statement's explicit verb.

The March 23, 2020 notation-vote statement explicitly says `Voting (by notation) for the monetary
policy action were ...` and lists ten voters. Its bounded monetary-policy voting clause parses as
`vote_status="stated"` and `vote_split="10-0"`. Every semicolon-delimited entry must be a valid named
voter; malformed or missing list content fails normalization. The parser must not fall through to
the later `Committee voted unanimously to authorize and direct` paragraph, which records a related
operational authorization rather than the monetary-policy vote. A mutation that removes the
notation-vote clause while leaving that later paragraph therefore fails as missing vote evidence.

An official release with no published monetary-policy voting clause may still use
`vote_status=not_stated` and `vote_split=null`, but only after the supported regular and notation-vote
wording families have both been ruled out. The parser never invents a vote or infers action from
market data, an adjacent action, or a later meeting.

## 7. SEP March wording and timestamp handling

The 2026 March SEP is valid even though it lacks the prose sentence declaring the number of
participants. Participant counts are extracted from the official Figure 2 dot table itself. The
parser must consume every recognized rate row and every horizon cell, reject unknown cell content,
require nonnegative integer counts and a positive total for each published horizon, and bind each
distribution to the matching Table 1 horizon. A prose participant declaration, when present, is an
additional cross-check; it is not the sole source of truth.

Publication timestamp parsing moves out of the fetcher's fail-fast boundary. Exact artifacts are
constructible and persistable even when timestamp normalization fails. `EST` and `EDT` labels are
interpreted as the publisher-declared fixed offsets and retained in parser audit metadata; a
daylight-saving disagreement is reported but does not make exact bytes disappear. Missing or
ambiguous release time still prevents a normalized point-in-time observation until resolved.

## 8. Per-release failure isolation

Each provider run has three levels:

1. discovery/fetch records every release candidate and persists any retrieved exact artifacts;
2. each release parses and writes observations in its own transaction/savepoint;
3. the source summary is `ok` only if all discovered releases succeed, otherwise `degraded` with
   successful release observations preserved.

One release failure therefore cannot roll back another release. The result reports discovered,
artifact, succeeded, failed, and observation counts plus the failed release keys. Error text is
bounded for operational storage. A source-level transport failure remains distinct from a
release-level parse failure.

The API continues to serve the latest eligible valid observation for each path. A degraded source
does not null a valid older/current path; it exposes degraded freshness and release failures beside
the data. It never substitutes one path kind for another.

## 9. Backfill, incremental operation, and replay

A resumable one-time backfill requests 2020 through the current year and builds the durable ledger.
The daily scheduled worker fetches the current year only; it does not redownload the whole archive.
An explicit all-history audit/revision command can be run periodically or after a parser/publisher
change. Every path is idempotent over unchanged hashes. The source adapters remain deterministic
over exact bytes so a future semantic parser version can reprocess persisted artifacts without
network access.

The API supports both:

- latest canonical valid evidence; and
- historical date-level `as_of` replay using the existing query; and
- precise `as_of_ts` replay using `available_at <= as_of_ts` for intraday releases/corrections.

Supplying both replay parameters is rejected. The timestamp parameter is timezone-aware and is the
one used by correction-boundary and same-day pre/post-release tests.

Once acquired, the 2020+ official record must remain readable when the Federal Reserve site or the
network is unavailable. Offline replay is an explicit acceptance test.

## 10. Verification gates

### All-release live probe

The source probe must enumerate and parse every discovered 2020+ FOMC statement and SEP release,
not just `max(release_date)`. Its durable JSON contains the discovered keys, content hashes, parser
versions, per-release status, error class/message, and coverage counts. Official pass/fail is
independent of the optional market shadow, though strict 4/4 validation explicitly requires the
shadow.

### Real 4/4 smoke

Against a dedicated test database, run the production worker entry points for FOMC, SEP, SME, and
market-implied evidence, then read `GET /api/macro/policy` through the application. The gate requires:

- `actual`, `committee_projection`, `dealer_expectations`, and `market_implied` all non-null;
- every returned evidence reference resolves to the persisted artifact and observation;
- zero failed official releases in the requested 2020+ window;
- a second identical run creates no duplicate facts;
- a synthetic correction preserves the predecessor and changes `as_of` selection only at the safe
  revision time; and
- after network providers are disabled, DB/API replay still returns the persisted paths.

`docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md` is downgraded to **PARTIAL** before fixes
land. It may return to **PASS** only after both the all-release live probe and real 4/4 smoke produce
committed, reproducible evidence.

## 11. Downstream contract

The Foundmetal PM agent and later top-down macro UI consume four independent, evidence-referenced
paths. They may compare or explain disagreements but must not relabel dealer or market-implied data
as the Fed's view. The durable 2020+ ledger supplies regime history for later inflation → rates → USD
→ gold research without embedding a subjective regime score in ingestion.
