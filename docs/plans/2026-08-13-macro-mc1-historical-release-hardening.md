# Macro MC1 Historical Release Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and verify a durable 2020-present official FOMC/SEP release ledger whose four policy paths survive format drift, individual release failures, reruns, corrections, and network outages.

**Architecture:** Extend official discovery to current and historical Federal Reserve pages, preserve exact HTML/PDF revisions in the existing MC0 evidence tables, and catalog each release's latest operational outcome in a new release-status table. Parse historical format families over normalized extraction text, isolate each release write in its own transaction, expose coverage failures beside still-valid paths, and require an all-release live audit plus a real worker→Postgres→FastAPI 4/4 smoke before restoring PASS.

**Tech Stack:** Python 3.13 via `uv`, httpx, BeautifulSoup, Pydantic v2, psycopg 3/PostgreSQL, FastAPI/TestClient, pytest, TypeScript generation.

---

## Global execution rules

- Work only in `/Users/chenxi/projects/argon/.worktrees/macro-fomc-sep-policy-paths` on `feat/macro-fomc-sep-policy-paths`.
- Use `uv run pytest`; never bare `pytest`.
- Use official Federal Reserve/NY Fed sources and the existing free Frenzy shadow; never Yahoo.
- Do not mutate exact downloaded bytes to make parsers pass. Normalize only a derived extraction string.
- Run live probes only after fixture and integration tests pass.
- Use a dedicated `option_wizard_test*` database for destructive migration/smoke runs; never reset `option_wizard_local`.
- Keep `VERDICT.md` at PARTIAL until every final gate in Task 9 passes with committed evidence.
- After every task, run `git diff --check` before its scoped milestone commit.

### Task 1: Record the current PARTIAL verdict before fixing anything

**Files:**
- Modify: `docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md`
- Modify: `docs/research/2026-08-12-fomc-sep-source-probe/README.md`
- Create: `docs/research/2026-08-12-fomc-sep-source-probe/pre-hardening-audit.json`

**Step 1: Add a failing verdict regression test**

Create `tests/unit/research/test_fomc_sep_verdict.py` with a test that reads `VERDICT.md` and asserts
the status is `PARTIAL`, contains the measured 2026 worker counts, and explicitly names both hard
gates:

```python
def test_verdict_stays_partial_until_all_release_and_4x4_gates_pass() -> None:
    text = VERDICT.read_text()
    assert "**Verdict:** PARTIAL" in text
    assert "FOMC statements | 10 | 0" in text
    assert "SEP | 4 | 0" in text
    assert "all discovered 2020+ releases" in text
    assert "worker → DB → API" in text
```

**Step 2: Prove the current document fails the regression**

Run:

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py -q
```

Expected: FAIL because the committed verdict says PASS.

**Step 3: Persist the pre-hardening evidence and downgrade the verdict**

Write the already observed baseline into `pre-hardening-audit.json` with:

- UTC generation time and reproduce command;
- 2026 worker results: FOMC `10/0`, SEP `4/0`, SME `2/1`, shadow `1/1`;
- FOMC 2021–2026 coverage `45 discovered / 17 parsed / 28 failed`;
- the official 2020 history page's 10 statement/3 SEP candidates, all 13 currently unparsed by the
  production providers;
- the fact that production discovery currently misses 2020 entirely;
- exact failed release keys and bounded error messages; and
- `schema_version: 1`.

Change `VERDICT.md` to PARTIAL and state that parser/unit success cannot restore PASS.

**Step 4: Verify and commit**

Run:

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py -q
git diff --check
git add docs/research/2026-08-12-fomc-sep-source-probe tests/unit/research/test_fomc_sep_verdict.py
git commit -m "docs(macro): mark policy source gate partial"
```

Expected: PASS; one scoped documentation/evidence commit.

### Task 2: Normalize Unicode policy-rate text and cover historical FOMC wording

**Files:**
- Modify: `src/uw_scan/sources/fomc_calendar.py`
- Modify: `src/uw_scan/sources/fomc_statement.py`
- Modify: `src/uw_scan/worker/jobs/macro_policy_jobs.py`
- Modify: `tests/unit/sources/test_fomc_calendar.py`
- Modify: `tests/unit/sources/test_fomc_statement.py`
- Create: `tests/fixtures/macro/fomc_statement_2020_03_23.html`
- Create: `tests/fixtures/macro/fomc_statement_2021_01.html`
- Create: `tests/fixtures/macro/fomc_statement_2022_03.html`
- Create: `tests/fixtures/macro/fomc_statement_2026_03.html`

**Step 1: Pin failing format-family tests**

Use exact official statement HTML snippets/fixtures and assert:

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0 to ¼ percent", (Decimal("0"), Decimal("0.25"))),
        ("3‑1/2 to 3‑3/4 percent", (Decimal("3.5"), Decimal("3.75"))),
        ("4–1/4 to 4–1/2 percent", (Decimal("4.25"), Decimal("4.5"))),
    ],
)
def test_target_range_normalizes_unicode_fraction_and_hyphen(raw, expected):
    assert _infer_target_range(raw) == expected
```

Add full-release tests for the March 23, 2020 notation-vote statement, 2021 maintain/keep wording, the
first 2022 increase, and 2026 Unicode mixed numbers. Assert action, both bounds, vote status/split,
and timestamp. March 23 must return `vote_status="not_stated"` and `vote_split=None`; any release
that contains a voting paragraph must either parse its exact split or fail.

**Step 2: Run the focused tests and record the expected failures**

```bash
uv run pytest tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fomc_statement.py -q
```

Expected: new Unicode and historical wording cases FAIL.

**Step 3: Implement one extraction-only normalizer**

Add a private helper used by all FOMC text inference. Apply compatibility normalization before the
translation maps and include the normalized one-character forms in the maps:

```python
_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
_FRACTIONS = str.maketrans({"¼": "1/4", "½": "1/2", "¾": "3/4", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⁄": "/"})

def _normalize_policy_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_HYPHENS).translate(_FRACTIONS)
    return " ".join(value.replace("\u00a0", " ").split())
```

Parse a numeric token as a decimal, fraction, or mixed number and reject denominator zero,
non-finite results, and malformed tokens. Extend `_infer_action` to explicit maintain/keep, raise,
and lower wording families; do not infer from adjacent meetings.

Separate the stable artifact acquisition version from the semantic FOMC parser version. Keep exact
artifact metadata compatible with already persisted bytes; carry the incremented semantic parser
version on `FomcStatementRelease` and later on its normalized observation. Persist `vote_status`
beside the nullable split in the actual-path JSON so `not_stated` is not confused with parser loss.

**Step 4: Verify representative and existing parser behavior**

```bash
uv run pytest tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fomc_statement.py -q
git diff --check
```

Expected: PASS.

**Step 5: Commit**

```bash
git add src/uw_scan/sources/fomc_calendar.py src/uw_scan/sources/fomc_statement.py src/uw_scan/worker/jobs/macro_policy_jobs.py tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fomc_statement.py tests/fixtures/macro/fomc_statement_*.html
git commit -m "fix(macro): parse historical FOMC rate wording"
```

### Task 3: Discover every official 2020+ statement and SEP release

**Files:**
- Modify: `src/uw_scan/sources/fomc_calendar.py`
- Modify: `src/uw_scan/sources/fomc_statement.py`
- Modify: `src/uw_scan/sources/fed_sep.py`
- Modify: `tests/unit/sources/test_fomc_calendar.py`
- Modify: `tests/unit/sources/test_fomc_statement.py`
- Modify: `tests/unit/sources/test_fed_sep.py`
- Create: `tests/fixtures/macro/fomc_calendar_current.html`
- Create: `tests/fixtures/macro/fomc_historical_2020.html`

**Step 1: Write failing discovery tests**

Pin exact official calendar/index HTML that includes regular meeting statements, 2020 unscheduled
meeting statements, notation-vote statements, and SEP links. Assert the candidate list contains
stable keys and classifications:

```python
assert candidates["fomc-statement:monetary20200303a"].event_class == "unscheduled_meeting"
assert candidates["fomc-statement:monetary20200315a"].event_class == "unscheduled_meeting"
assert candidates["fomc-statement:monetary20200323a"].event_class == "notation_vote"
assert candidates["fomc-statement:monetary20200429a"].event_class == "scheduled_meeting"
assert "fed-sep:fomcprojtabl20200610" in candidates
assert len({item.release_key for item in candidates.values()}) == len(candidates)
```

The frozen 2020 official index should yield 10 links labeled `Statement` (including the March 3 and
March 15 unscheduled meeting statements and the March 23 notation-vote statement) and three SEP
meetings (June, September, December). Treat those as a historical golden coverage count, not a guess
from current-calendar markup.

Also assert missing HTML/PDF counterparts remain explicit candidates with a discovery error instead
of disappearing at set intersection.

**Step 2: Verify tests fail**

```bash
uv run pytest tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fomc_statement.py tests/unit/sources/test_fed_sep.py -q
```

Expected: FAIL because providers only parse the current page and silently intersect pairs.

**Step 3: Add typed discovery candidates and archive traversal**

Introduce one frozen candidate contract shared by statement and SEP providers:

```python
@dataclass(frozen=True)
class FomcReleaseCandidate:
    release_key: str
    release_type: Literal["statement", "sep"]
    event_date: date
    event_class: Literal["scheduled_meeting", "unscheduled_meeting", "notation_vote"] | None
    discovery_url: str
    html_url: str | None
    pdf_url: str | None
    discovery_error: str | None = None
```

Derive `release_key` from the canonical publisher document stem, not only the event date; keep the
date as a separate typed field so two official documents on one date cannot collide.

This key change occurs before MC1 is merged or production scheduling is enabled. Do not rewrite or
delete any already persisted local artifact rows; a clean test database proves the final identity
scheme, and any legacy local test rows remain historical evidence rather than being mutated.

Fetch the current calendar plus official historical pages for every requested past year. Restrict
URLs to the configured Federal Reserve host, de-duplicate by release key, sort deterministically,
and retain incomplete candidates. A historical statement index may link only its HTML page; after
fetching that page, discover and validate the same-date official PDF link before declaring the pair
incomplete. Historical pages sometimes identify an SEP through the official
`SEP: Individual Projections` link without linking the accessible projection table. Use that
meeting-scoped official marker to derive the Federal Reserve's canonical
`fomcprojtablYYYYMMDD.{htm,pdf}` URLs, require both URLs to return official content, and never discover
dates by unbounded URL guessing.

**Step 4: Make providers return per-candidate fetch outcomes**

A transport failure for one candidate must not abort discovery of later candidates. Return a typed
outcome containing the candidate, any exact artifacts obtained, and a bounded fetch error. Preserve
the existing single-bundle helper for fixture compatibility if useful, but the production worker
must consume outcomes.

**Step 5: Verify and commit**

```bash
uv run pytest tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fomc_statement.py tests/unit/sources/test_fed_sep.py -q
git diff --check
git add src/uw_scan/sources/fomc_calendar.py src/uw_scan/sources/fomc_statement.py src/uw_scan/sources/fed_sep.py tests/unit/sources tests/fixtures/macro/fomc_calendar_current.html tests/fixtures/macro/fomc_historical_2020.html
git commit -m "feat(macro): discover full 2020 FOMC history"
```

### Task 4: Parse SEP March wording and historical release timestamps

**Files:**
- Modify: `src/uw_scan/sources/fed_sep.py`
- Modify: `tests/unit/sources/test_fed_sep.py`
- Create: `tests/fixtures/macro/fed_sep_2020_06.html`
- Create: `tests/fixtures/macro/fed_sep_2020_09.html`
- Create: `tests/fixtures/macro/fed_sep_2020_12.html`
- Create: `tests/fixtures/macro/fed_sep_2026_03.html`
- Create: `tests/fixtures/macro/fed_sep_historical_timezone.html`

**Step 1: Write failing March and timezone tests**

From the exact official March HTML, assert every published federal-funds-rate horizon parses, each
dot-table total is positive, and the absence of a prose participant declaration is accepted. Add a
mutation test that inserts an unknown non-empty dot cell and must raise `NormalizationError`.

Pin all three 2020 official SEP HTML pages. Assert their historical table families produce the
published policy horizons, medians, anonymous dot counts, and declared release instants. The current
baseline is 0/3: June and September report `Table 1 table is missing`, while December fails the
timezone-label check. These cases must become explicit supported format families, not broad relaxed
selectors.

Add timestamp tests proving publisher-declared `EST`/`EDT` converts with its stated fixed offset and
that a timezone-label/calendar disagreement appears in audit metadata rather than aborting bundle
construction. Missing date/time must still block normalized observations.

**Step 2: Verify tests fail**

```bash
uv run pytest tests/unit/sources/test_fed_sep.py -q
```

Expected: FAIL on missing participant declaration and historical timezone construction.

**Step 3: Separate artifact construction from semantic timestamp parsing**

Allow exact artifacts to be built with `published_at=None` and `available_at=retrieved_at` when the
publication instant is not yet normalized. Move the required PIT timestamp check into
`parse_sep_release`. Preserve the publisher label and any disagreement as parser audit data.

**Step 4: Derive and validate participant totals from Figure 2**

Treat the dot table as the primary count source. Require recognized horizons, integer nonnegative
counts, no ignored non-empty cells, a positive total per horizon, and exact agreement with prose
totals when prose is present. Separate the stable artifact acquisition version from the semantic SEP
parser version. Carry the incremented semantic version on `SepRelease` and its observation; do not
change immutable metadata for an already stored identical artifact.

**Step 5: Verify and commit**

```bash
uv run pytest tests/unit/sources/test_fed_sep.py -q
git diff --check
git add src/uw_scan/sources/fed_sep.py tests/unit/sources/test_fed_sep.py tests/fixtures/macro/fed_sep_2020_*.html tests/fixtures/macro/fed_sep_2026_03.html tests/fixtures/macro/fed_sep_historical_timezone.html
git commit -m "fix(macro): parse SEP table totals and timestamps"
```

### Task 5: Persist a per-release operational catalog

**Files:**
- Create: `src/uw_scan/storage/migrations/117_macro_release_ingest_status.sql`
- Modify: `src/uw_scan/storage/macro_context.py`
- Modify: `docs/runbooks/data-gap-dataset-policy.md`
- Modify: `tests/integration/storage/test_macro_context_repository.py`
- Modify: `tests/integration/test_migrations.py`

**Step 1: Write failing repository tests**

Test that a release can move `failed → ok → failed` while retaining `last_success_at` and
`last_success_artifact_id`; errors are bounded; invalid state combinations fail; and two releases
for one source remain independent. Reapply migrations and assert idempotency.

Add an evidence-identity regression: two exact HTML artifacts with different byte hashes but the
same normalized facts/time/parser version resolve to one policy observation with two lineage links.
A semantic change produces a second observation. Existing non-policy macro series retain their MC0
identity and remain readable.

Add mixed-case/non-ASCII JSON-key parity and non-finite numeric tests for the new semantic hash,
mirroring MC0's Python/PostgreSQL canonicalization regressions.

**Step 2: Verify tests fail**

```bash
uv run pytest tests/integration/storage/test_macro_context_repository.py tests/integration/test_migrations.py -q
```

Expected: FAIL because the table and repository methods do not exist.

**Step 3: Add the migration**

Create `uw_scan.macro_release_ingest_status` with:

```sql
PRIMARY KEY (source, release_key),
release_type TEXT CHECK (release_type IN ('statement', 'sep')),
status TEXT CHECK (status IN ('discovered', 'artifact_only', 'ok', 'failed')),
event_date DATE NOT NULL,
event_class TEXT NULL CHECK (
  event_class IN ('scheduled_meeting', 'unscheduled_meeting', 'notation_vote')
),
discovery_url TEXT NOT NULL,
artifact_source_record_id TEXT NULL,
latest_artifact_id BIGINT NULL,
last_success_artifact_id BIGINT NULL,
parser_version TEXT NOT NULL,
last_attempt_at TIMESTAMPTZ NOT NULL,
last_success_at TIMESTAMPTZ NULL,
error_type TEXT NULL,
error_message TEXT NULL
```

Also add `uw_scan.macro_observation_artifacts(obs_id, artifact_id, relation)` with an immutable,
idempotent composite key and `relation IN ('parsed_from', 'corroborates')`. Add a policy-observation
semantic hash helper and nullable `macro_observations.semantic_hash` column in migration 117. The
hash omits the volatile artifact surrogate ID but includes source, stable release key, normalized
value, publisher release time, and semantic parser version. A partial unique index makes a
policy semantic identity idempotent. A PostgreSQL trigger recomputes the same canonical hash so
direct SQL cannot assert a false identity. Preserve migration 115 and the existing general MC0 hash
helper unchanged for other macro series.

When a new raw hash arrives, compare its parsed value to the prior observation for that release
before setting a later observation availability. Equal facts link to the existing observation;
changed facts create a new observation whose `available_at` is the publisher correction time or,
when absent, first retrieval of the changed semantic payload.

Use composite foreign keys `(artifact_id, source, artifact_source_record_id)` against the existing
artifact uniqueness contract so a release status cannot point at another source's artifact. Add
constraints tying `ok` to a success artifact/time and `failed` to an error type. Make the migration
idempotent and register the table as `operational_state`/`liveness`, explicitly not a substitute for
immutable release evidence.

**Step 4: Add repository methods**

Implement `upsert_macro_release_status`, `fetch_macro_release_status`, and
`fetch_macro_release_statuses`. Validate aware timestamps and allowed transitions in Python as well
as SQL. Bound error type to 200 characters and message to 1000.

**Step 5: Verify and commit**

```bash
uv run pytest tests/integration/storage/test_macro_context_repository.py tests/integration/test_migrations.py -q
git diff --check
git add src/uw_scan/storage/migrations/117_macro_release_ingest_status.sql src/uw_scan/storage/macro_context.py docs/runbooks/data-gap-dataset-policy.md tests/integration/storage/test_macro_context_repository.py tests/integration/test_migrations.py
git commit -m "feat(macro): catalog policy release outcomes"
```

### Task 6: Isolate worker persistence per release

**Files:**
- Modify: `src/uw_scan/worker/jobs/macro_policy_jobs.py`
- Modify: `tests/unit/worker/test_macro_policy_jobs.py`
- Modify: `tests/integration/worker/test_macro_policy_jobs.py`

**Step 1: Write failing isolation and result-contract tests**

Use three fixture bundles: valid, malformed, valid. Assert:

```python
assert result.status == "degraded"
assert result.releases_discovered == 3
assert result.releases_succeeded == 2
assert result.releases_failed == 1
assert result.failed_release_keys == ("fomc-statement:monetary20220316a",)
assert repo.count_macro_observations("POLICY_PATH_ACTUAL") == 2
```

Assert every fetched artifact is committed before its parser runs; a fetch-only candidate produces
`artifact_only`/`failed` status; rerun is idempotent; and failure of one official source does not
affect another job. Assert the normalized observation references the accessible HTML artifact that
the parser actually read, while the PDF remains a sibling artifact. Assert an unchanged artifact can
be reprocessed by a newer semantic parser version without an artifact identity collision.

Fetch the same official HTML twice with request-varying footer bytes in a regression fixture. Assert
two exact artifacts, one normalized policy observation, and two `parsed_from` lineage rows. Then
change a policy field and assert a second observation appears.

Add a correction-safety test: after one hash exists for a release key, a newly observed different
hash at the same URL must use no earlier than its first retrieval as `available_at` unless the
publisher supplies an explicit later correction timestamp. The correction must never be backdated
to the original release.

**Step 2: Verify the tests fail under batch rollback**

```bash
uv run pytest tests/unit/worker/test_macro_policy_jobs.py tests/integration/worker/test_macro_policy_jobs.py -q
```

Expected: FAIL because one parse exception currently rolls back all observation rows.

**Step 3: Refactor to release-scoped persistence**

Extend `MacroPolicyIngestResult` with discovered/succeeded/failed counts and failed keys. For every
candidate:

1. upsert discovery status;
2. insert and commit exact artifacts;
3. parse the release and select the exact HTML artifact the parser consumed;
4. insert its hashed observation with the release's semantic parser version and update release
   status in one release-scoped transaction;
5. on error, roll back only that release and persist its failed status in a fresh transaction.

Set source status `degraded` if any release failed, but preserve successful observations and
`last_success_at`. Use a stable aggregate error such as `MacroReleaseFailures` plus bounded keys.

**Step 4: Verify and commit**

```bash
uv run pytest tests/unit/worker/test_macro_policy_jobs.py tests/integration/worker/test_macro_policy_jobs.py -q
git diff --check
git add src/uw_scan/worker/jobs/macro_policy_jobs.py tests/unit/worker/test_macro_policy_jobs.py tests/integration/worker/test_macro_policy_jobs.py
git commit -m "fix(macro): isolate policy releases during ingest"
```

### Task 7: Expose release coverage beside valid API paths

**Files:**
- Modify: `src/uw_scan/models/macro.py`
- Modify: `src/uw_scan/models/__init__.py`
- Modify: `src/uw_scan/macro/policy_report.py`
- Modify: `tests/integration/api/test_macro_policy_router.py`
- Modify: `tests/unit/test_models_exports.py`
- Create: `tests/unit/test_macro_model_contract.py`
- Modify: `tests/integration/api/test_openapi_snapshot.py`
- Modify: `tests/integration/api/openapi.snapshot.json`
- Modify: `web/lib/types.ts` via generation

**Step 1: Write failing API tests**

Seed one current valid actual path plus one failed older FOMC release. Assert the path remains non-null
while freshness reports `releases_discovered=2`, `releases_succeeded=1`,
`releases_failed=1`, and a bounded failure containing release key/date/error. Assert a historical
`as_of` does not leak a later operational attempt.

Add a timezone-aware `as_of_ts` query parameter while preserving the existing date-level `as_of`.
Reject requests that supply both. Test the instant immediately before and at an official release and
the correction boundary; date-only end-of-day replay cannot prove those timing semantics.

**Step 2: Verify tests fail**

```bash
uv run pytest tests/integration/api/test_macro_policy_router.py tests/unit/test_models_exports.py tests/unit/test_macro_model_contract.py tests/integration/api/test_openapi_snapshot.py -q
```

Expected: FAIL because freshness has no release coverage contract.

**Step 3: Add typed coverage models and report assembly**

Add `PolicyReleaseFailure` and fields on `PolicySourceFreshness`:

```python
releases_discovered: int = 0
releases_succeeded: int = 0
releases_failed: int = 0
release_failures: list[PolicyReleaseFailure] = Field(default_factory=list)
```

Add `PolicyPathPoint.vote_status: Literal["stated", "not_stated"] | None` so the public API preserves
the distinction already written into actual-path JSON. Regenerate OpenAPI and TypeScript contracts.

Validate counts and cap exposed failure details. Fetch current per-release states in
`build_policy_comparison`; keep the existing `last_attempt_at <= as_of` guard so current operational
metadata does not contaminate older replay.

**Step 4: Regenerate and verify contracts**

```bash
cd web && npm run gen:types
cd ..
uv run pytest tests/integration/api/test_macro_policy_router.py tests/unit/test_models_exports.py tests/unit/test_macro_model_contract.py tests/integration/api/test_openapi_snapshot.py -q
git diff --check
```

Expected: PASS; generated TypeScript includes the new required coverage fields.

**Step 5: Commit**

```bash
git add src/uw_scan/models src/uw_scan/macro/policy_report.py tests/integration/api/test_macro_policy_router.py tests/integration/api/test_openapi_snapshot.py tests/integration/api/openapi.snapshot.json tests/unit/test_models_exports.py tests/unit/test_macro_model_contract.py web/lib/types.ts
git commit -m "feat(macro): expose policy release coverage"
```

### Task 8: Add resumable historical backfill and audit every discovered 2020+ release

**Files:**
- Create: `scripts/backfill/macro_policy_history.py`
- Modify: `scripts/research/fomc_sep_source_probe.py`
- Create: `tests/unit/scripts/test_macro_policy_history.py`
- Modify: `tests/unit/research/test_fomc_sep_source_probe.py`
- Modify: `docs/research/2026-08-12-fomc-sep-source-probe/README.md`

**Step 1: Write failing probe aggregation tests**

Give the probe three discovered releases with one parse failure. Assert it emits all three release
records, `state=parse_error`, exact coverage totals, hashes for obtained artifacts, and a nonzero
official exit code. Assert `--require-shadow` controls shadow load-bearing behavior independently.

**Step 2: Verify tests fail**

```bash
uv run pytest tests/unit/research/test_fomc_sep_source_probe.py -q
```

Expected: FAIL because `_probe_statement` and `_probe_sep` select only `max(...)`.

**Step 3: Implement a production-path historical backfill**

Add `scripts/backfill/macro_policy_history.py --start-year 2020 --end-year <year>
--resume --verify`. It calls the production FOMC/SEP worker entry points, uses
`macro_release_ingest_status` for resumability, persists exact evidence before parsing, and exits
nonzero if any requested release is not `ok`. It never writes a temporary JSON-only substitute for
the database ledger. Daily scheduler defaults remain current-year only; the whole archive is not
downloaded every night.

Unit-test year validation, resume selection, and nonzero failure exit with fixture providers.

**Step 4: Implement all-release audit output**

Default `--start-year 2020`; audit through the current year. Emit deterministic per-source arrays:

```json
{
  "release_key": "fomc-statement:monetary20200315a",
  "event_date": "2020-03-15",
  "event_class": "unscheduled_meeting",
  "state": "ok",
  "artifact_hashes": {"html": "...", "pdf": "..."},
  "parser_version": "...",
  "error_type": null,
  "error_message": null
}
```

Compute source state from all discovered releases. Any missing outcome, fetch error, parse error, or
empty normalized release makes that official source non-ok.

**Step 5: Verify self-check and commit code/docs, not yet a PASS verdict**

```bash
uv run pytest tests/unit/scripts/test_macro_policy_history.py tests/unit/research/test_fomc_sep_source_probe.py -q
uv run python scripts/research/fomc_sep_source_probe.py --self-check
git diff --check
git add scripts/backfill/macro_policy_history.py scripts/research/fomc_sep_source_probe.py tests/unit/scripts/test_macro_policy_history.py tests/unit/research/test_fomc_sep_source_probe.py docs/research/2026-08-12-fomc-sep-source-probe/README.md
git commit -m "test(macro): audit every official policy release"
```

Expected: fixture/self-check PASS; verdict remains PARTIAL.

### Task 9: Prove worker→DB→API 4/4, idempotency, correction history, and offline replay

**Files:**
- Create: `scripts/research/macro_policy_4x4_smoke.py`
- Create: `tests/integration/worker/test_macro_policy_4x4_smoke.py`
- Modify: `docs/research/2026-08-12-fomc-sep-source-probe/probe.json`
- Create: `docs/research/2026-08-12-fomc-sep-source-probe/smoke-4x4.json`
- Modify: `docs/research/2026-08-12-fomc-sep-source-probe/VERDICT.md`
- Modify: `CHANGELOG.md`

**Step 1: Add a deterministic production-path integration smoke**

Use fixture-backed provider factories but the real four worker job entry points, real migrated
Postgres, the real repository, and the FastAPI test client. Assert all four API slots are non-null,
every evidence reference resolves, release counts are correct, and a malformed release degrades only
its source while valid paths survive.

**Step 2: Add rerun, correction, and offline assertions**

Run the identical jobs twice and compare artifact/observation counts. Then change one HTML artifact
under the same release key with a later safe `available_at`; assert both revisions remain, both
observations reference the exact HTML revisions they parsed, and API `as_of` selects the predecessor
before the correction and successor after it. Finally disable providers and assert DB/API reads still
return all persisted paths.

**Step 3: Verify the deterministic smoke**

```bash
uv run pytest tests/integration/worker/test_macro_policy_4x4_smoke.py -q
```

Expected: PASS against a dedicated pytest database.

**Step 4: Run the all-release live probe**

```bash
uv run python scripts/research/fomc_sep_source_probe.py --start-year 2020
```

Expected: every discovered 2020+ FOMC/SEP release has `state=ok`; official exit code 0. If any release
fails, persist the actual result, keep PARTIAL, fix through a new failing fixture test, and repeat.

**Step 5: Run the strict live 4/4 smoke on a dedicated database**

Create an isolated database whose name starts with `option_wizard_test`, apply migrations, then run:

```bash
uv run python scripts/research/macro_policy_4x4_smoke.py --require-shadow
```

The committed `smoke-4x4.json` must record:

- exact command, UTC timestamp, database class (never credentials), parser versions, and source URLs;
- four worker results and table counts before/after the idempotent rerun;
- four non-null API slots and their observation/artifact IDs;
- zero failed official releases;
- correction/PIT and offline-read assertions; and
- overall `PASS` only if all assertions pass.

Drop only the explicitly created test database after the evidence file is safely written.

**Step 6: Run the complete focused verification**

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py tests/unit/research/test_fomc_sep_source_probe.py tests/unit/scripts/test_macro_policy_history.py tests/unit/sources/test_fomc_calendar.py tests/unit/sources/test_fomc_statement.py tests/unit/sources/test_fed_sep.py tests/unit/worker/test_macro_policy_jobs.py tests/integration/storage/test_macro_context_repository.py tests/integration/worker/test_macro_policy_jobs.py tests/integration/worker/test_macro_policy_4x4_smoke.py tests/integration/api/test_macro_policy_router.py tests/unit/test_models_exports.py tests/unit/test_macro_model_contract.py tests/integration/api/test_openapi_snapshot.py -q
cd web && npm run test
cd ..
uv run python scripts/research/fomc_sep_source_probe.py --self-check
git diff --check
```

Expected: all tests PASS and generated artifacts match their renderers.

**Step 7: Promote the verdict only when both evidence files pass**

If and only if `probe.json` has zero official 2020+ release failures and `smoke-4x4.json` is PASS,
change `VERDICT.md` to PASS with exact counts and artifact hashes. Otherwise leave it PARTIAL and
document the remaining release keys.

**Step 8: Request independent review and close findings**

Use `superpowers:requesting-code-review`. Review data integrity, PIT timing, exact-byte revision
semantics, all-release coverage, and the claim/evidence match in `VERDICT.md`. Add regression tests
for every accepted finding and rerun Step 6.

**Step 9: Commit the verified milestone**

```bash
git add scripts/research/macro_policy_4x4_smoke.py tests/integration/worker/test_macro_policy_4x4_smoke.py docs/research/2026-08-12-fomc-sep-source-probe CHANGELOG.md
git commit -m "test(macro): verify durable policy paths end to end"
```

Expected: clean worktree with a review-backed evidence commit. Do not push or merge until explicitly
requested; when requested, open a PR first and follow the repository release workflow.
