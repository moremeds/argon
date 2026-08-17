# MC1 policy-source verdict

**Verdict:** PASS

Four independent policy paths are durable end to end: every discovered 2020+ FOMC statement and SEP
release parses, the production worker persists them through the real evidence contract, and the real
API serves all four slots back from stored rows with the source network unused.

Two committed evidence files carry the claim, both measured 2026-08-17:

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
   `no_observation_predates_its_evidence`, with the correction semantics covered by
   `test_a_correction_is_never_backdated_to_the_original_release`; and
5. persisted policy paths remain readable with the source network disabled — **met**:
   `offline_read_returns_paths`.

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

## Measured source properties

- **Federal Reserve HTML is not byte-stable.** It is served through Cloudflare, which injects a
  per-request `__CF$cv$params` script carrying a unique ray id and timestamp. Two fetches of the same
  release return identical-length, different-byte payloads. Measured over the full archive: 81 PDF
  records with **0** multi-revision records, 82 HTML records with **80**. The PDF carries no
  injection, which is why it is the primary artifact. Re-fetched HTML is preserved as exact evidence
  and linked as another witness of the same observation; it never creates a second fact. Idempotency
  is therefore asserted on facts, release outcomes, and stable evidence — never on a byte count the
  transport controls.
- **The market shadow cannot be idempotent and is not asserted to be.** It is a live probability
  snapshot, so a fresh reading is a genuinely new fact each time. Official releases are dated events
  and must be idempotent; the smoke separates the two.
- **Two of 55 statements publish a vote tally with no roster**, one of them a 9-3 vote. An empty
  `voted_against` means "no dissenter was named", which equals "no dissenter" only when
  `voter_names_stated` is true.

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
