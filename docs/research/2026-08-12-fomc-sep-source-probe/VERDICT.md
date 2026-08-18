# MC1 policy-source verdict

**Verdict:** PASS

Four independent policy paths are durable end to end: every discovered 2020+ FOMC statement and SEP
release parses, the production worker persists them through the real evidence contract, and the real
API serves all four slots back from stored rows with the source network unused.

Two committed evidence files carry the claim, both measured 2026-08-18:

| Evidence | What it proves | Result |
|---|---|---|
| [probe.json](probe.json) | every discovered 2020+ release parses | **55/55** statements, **25/25** SEP, 0 failed |
| [smoke-4x4.json](smoke-4x4.json) | worker → DB → API, idempotency, PIT, offline | **PASS**, 8/8 assertions, 80/80 releases `ok` |

The pre-hardening baseline that produced the earlier PARTIAL is preserved unchanged in
[pre-hardening-audit.json](pre-hardening-audit.json).

## Pre-hardening worker result

The worker was run against an isolated temporary PostgreSQL database and followed the production
artifact-before-observation path. The database was removed after inspection. The exploratory command
itself was not retained, so these counts are a frozen baseline rather than a reproducible end-to-end
artifact; replacing that evidence gap with a committed smoke runner is a PASS requirement.

| Source | Artifacts | Observations | Result |
|---|---:|---:|---|
| FOMC statements | 10 | 0 | DEGRADED — one unsupported statement rolled back the batch |
| SEP | 4 | 0 | DEGRADED — March lacked the prose participant-count declaration expected by the parser |
| NY Fed SME | 2 | 1 | usable dealer path |
| Frenzy shadow | 1 | 1 | usable third-party market shadow |

The artifact rows survived, but FOMC and SEP produced no normalized observations. That is not a 4/4
policy-path result.

## Historical coverage result

The pre-hardening FOMC provider found 45 releases for 2021–2026:
45 discovered / 17 parsed / 28 failed. All eight 2021 releases failed because action and target range were not recognized. The
remaining 20 failures could not parse the published target range. Exact release keys and bounded
errors are recorded in [pre-hardening-audit.json](pre-hardening-audit.json).

The [official 2020 FOMC history page](https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm)
contains 10 Statement candidates and 3 SEP candidates. The pre-hardening production discovery misses
2020, leaving all 13 currently unparsed. This includes the March 3 and March 15 unscheduled
statements and the March 23 notation-vote statement, as well as the June, September, and December SEP
releases.

## Gates required to restore PASS

MC1 remained PARTIAL until one committed evidence run proved all of the following. Each is now met:

1. every one of **all discovered 2020+ releases** has an explicit outcome and every complete
   official FOMC/SEP release parses with zero unexplained failures — **met**: `probe.json` reports
   55 discovered / 55 succeeded / 0 failed for FOMC and 25 / 25 / 0 for SEP across 2020–2026, and
   `smoke-4x4.json` records 80 catalog rows all `ok`. Discovery now returns both 2020 unscheduled
   meetings;
2. a real **worker → DB → API** smoke returns 4/4 independent paths from persisted rows, rather than
   calling parser functions directly — **met**: `four_paths_present` and
   `every_evidence_ref_resolves`, through the four production job entry points, a migrated Postgres,
   and the real FastAPI app;
3. one failed release cannot erase successful observations from the same source run — **met**:
   per-release transactions, covered by `test_one_bad_release_does_not_erase_the_good_ones` and
   `test_a_malformed_release_degrades_only_its_own_source`;
4. an unchanged rerun is idempotent, a changed artifact is retained as a new revision, and the prior
   revision remains replayable — **met**: `rerun_adds_no_official_fact`,
   `rerun_adds_no_release_outcome`, `stable_evidence_does_not_churn`, and
   `no_observation_predates_its_evidence`, with the correction semantics covered end to end by
   `test_a_correction_is_never_backdated_to_the_original_release` and, at the layer each defect
   actually lives in, by `test_a_correction_takes_its_own_retrieval_instant_not_the_first_release`
   (artifact) and `test_artifact_bounds_observation_availability_and_quality` (observation). The
   artifact test was checked by mutation: restoring the pre-fix expression fails it and nothing
   else; and
5. persisted policy paths remain readable with the source network disabled — **met**:
   `offline_read_returns_paths`, which patches `socket.connect` to reject every non-loopback
   address for the duration of the read. The earlier version asserted that no provider object was
   constructed, which proves nothing: a provider is not the only way to open a connection.

The market shadow remains non-load-bearing. Its absence may degrade the optional fourth path but can
never be filled by relabeling an official committee or dealer observation.

## What the hardening changed

Two backdating defects were found by the 4/4 smoke and fixed before this verdict was written. Both
leaked in the dangerous direction — availability that is too **early**, which a replay reads as
knowledge nobody had:

- The **artifact** layer set `available_at = published_at or retrieved_at`, so a reissue retrieved
  months later inherited the original release instant. A later revision can only justify
  `retrieved_at`, and now takes it.
- The **observation** layer set `available_at = release.published_at` outright, discarding the
  artifact's availability entirely. It now takes the later of the two, so a fact can never predate
  the bytes it was read from. The database guard `observation available_at precedes artifact
  available_at` is what exposed this second defect after the first was fixed.

A third defect was found by independent review, in the parse itself rather than in the timing:

- **A two-sided dissent lost a dissenter.** The voting-against block was split on `;`, but when
  dissenters want opposite things the Fed joins their clauses with `, and`. 2025-10-29 — Miran
  wanting a deeper cut, Schmid wanting none — parsed as one clause, and everything after the first
  `, who` was discarded as rationale, taking Schmid with it. Because `vote_split` is derived from
  the surviving names, the release recorded **10-1 instead of 10-2** and still reported `ok`: the
  drop decremented the very count that would have exposed it. Every fixture in the suite used the
  `;` form, so no test could have caught it. Both separators are now read, an unparsable clause
  grammar fails the release closed, and the real 2025-10-29 page is frozen as a fixture.

  This is the one defect the "55/55, zero failures" headline could never have surfaced, and it is
  why the section above states plainly what a live sweep does not protect.

## Measured source properties

- **Federal Reserve HTML is not byte-stable; the PDF is.** Two fetches of one release, one second
  apart, are recorded under `source_byte_stability.measured` in
  [smoke-4x4.json](smoke-4x4.json): the HTML returns **identical content-length and a different
  SHA-256**, with a `__CF$cv$params` token that differs between the two — the per-request Cloudflare
  script carrying a unique ray id. The PDF at the same instant is **byte-identical**, which is why
  it is the primary artifact.

  Across the archive this shows up as: **82 stable records** (every artifact whose media type is not
  `text/html` — the Fed PDFs plus the NY Fed workbook) **unchanged across the idempotent rerun**,
  against **81 HTML records that become 162** — each one gaining exactly one revision. Re-fetched
  HTML is preserved as exact evidence and linked as another witness of the same observation; it
  never creates a second fact. Idempotency is therefore asserted on facts, release outcomes, and
  stable evidence — never on a byte count the transport controls.
- **The market shadow cannot be idempotent and is not asserted to be.** It is a live probability
  snapshot, so a fresh reading is a genuinely new fact each time. Official releases are dated events
  and must be idempotent; the smoke separates the two.
- **Two of 55 statements publish a vote tally with no roster** — 2026-06-17 (12-0) and 2026-07-29
  (**9-3**). The 9-3 is the case that matters: three dissenters exist and the publisher named none.
  An empty `voted_against` means "no dissenter was named", which equals "no dissenter" only when
  `voter_names_stated` is true. All three fields now reach `GET /api/macro/policy`; previously only
  `vote_status` and `vote_split` did, so a consumer could see the tally but never learn whether the
  roster was knowable.
- **A dissent roster is the only self-check this data has, and it is weak.** `vote_split` is derived
  from the parsed names in the regular format family, so the tally cannot corroborate the roster —
  they fail together. The independent quantity is the roster TOTAL; `probe.json` now records
  `voted_for_count` and `roster_total` per release so the anomaly that exposed the 2025-10-29 defect
  is visible in the evidence rather than only to a reviewer who thinks to add the columns up.
- **`roster_total` below twelve has three causes, and we can only distinguish two of them.** A short
  roster means a Board vacancy (2020–2022 sit at 9–11 for this reason), a declared absence, or a
  dropped voter — the defect. The parser does not read the absence sentence: 2025-07-30 ends
  "Absent and not voting was Adriana D. Kugler", which is why that release totals 11, and **no
  fixture in the suite contains that sentence**. Nothing stored for it is wrong — 9 voting for, 2
  against, both dissenters named — but the member is silently dropped, which is the one place this
  milestone's "never silently skip a voter" rule is not yet honored, and it leaves the roster signal
  ambiguous in exactly the direction that hid the 10-1. Capturing absences is tracked as follow-up
  work; until then the roster total is a prompt to go read the statement, not a check that passes.

## What the live sweep does and does not protect

Both evidence files are a **single day's run against live publishers**. They establish that this
code read what federalreserve.gov, newyorkfed.org, and the shadow served that day, and that the
result survived worker → DB → API. They are not a regression surface: neither command runs in CI,
because both need the network and Fed HTML is not byte-stable. **The durable, CI-enforced coverage
is the frozen fixture set — 11 statements and 7 SEP releases chosen by format family — not the
55/25.** Read "55/55" as a measurement taken on a date, not as a property held under test.

Nor does the sweep check the parse against an independent record: `vote_split` is derived from the
names the parser found, so a dropped dissenter decrements the very tally that would expose it. The
2025-10-29 defect below was caught by a roster-sum anomaly noticed during review, not by any gate
here — and the fix was confirmed against the published statement, not against our own output.
`probe.json` now records `roster_total` per release so that anomaly is at least visible in the
evidence; it remains a signal to investigate, not a gate, because the seated committee legitimately
changes with vacancies.

## Evidence boundary and reproduction

The exact pre-hardening counts, failed keys, source URLs, and provenance limitations are frozen in
[pre-hardening-audit.json](pre-hardening-audit.json). The supported commands are:

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py -q
uv run python scripts/research/fomc_sep_source_probe.py --self-check
uv run python scripts/research/fomc_sep_source_probe.py --start-year 2020
uv run pytest tests/integration/worker/test_macro_policy_4x4_smoke.py -q
```

The live 4/4 smoke needs a database you created for the run:

```bash
createdb option_wizard_test_mc1_smoke -O argon_app
UW_SCAN_DB_NAME=option_wizard_test_mc1_smoke UW_SCAN_ALLOW_DB_MISMATCH=1 bash scripts/migrate.sh
UW_SCAN_TEST_DB_NAME=option_wizard_test_mc1_smoke \
  uv run python scripts/research/macro_policy_4x4_smoke.py --require-shadow
dropdb option_wizard_test_mc1_smoke
```

`smoke-4x4.json` records the command, UTC start and finish, the database class (never credentials),
both parser-version families, source URLs, four worker results, table counts before and after the
idempotent rerun, the four API slots with their observation and artifact ids, zero failed official
releases, and the correction/PIT and offline assertions.

## Product and PM-agent contract

The FoundMetal PM agent may consume only the separately keyed actual, committee, dealer, and market
paths together with their evidence and coverage status. It must not average paths, attribute an SEP
dot to the Chair, or turn a failed/missing path into a neutral score. This milestone still adds no UI;
it repairs the durable evidence layer for the later top-down rates, dollar, and gold surface.
