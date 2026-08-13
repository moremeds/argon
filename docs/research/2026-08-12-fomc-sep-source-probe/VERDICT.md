# MC1 policy-source verdict

**Verdict:** PARTIAL

The original latest-release source probe passed, but a real 2026 worker run and a broader official
release audit disproved the stronger MC1 claim. The latest-release check did not establish that the
production worker could persist all four paths, and it did not exercise the historical policy formats
needed for the COVID response and the 2022 hiking cycle. Parser or unit-test success alone cannot
restore PASS.

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

The current FOMC provider found 45 releases for 2021–2026: **45 discovered / 17 parsed / 28 failed**.
All eight 2021 releases failed because action and target range were not recognized. The
remaining 20 failures could not parse the published target range. Exact release keys and bounded
errors are recorded in [pre-hardening-audit.json](pre-hardening-audit.json).

The [official 2020 FOMC history page](https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm)
contains 10 Statement candidates and 3 SEP candidates. The production discovery misses 2020, leaving
all 13 currently unparsed. This includes the March 3, March 15, and March 23 unscheduled policy
statements as well as the June, September, and December SEP releases.

## Gates required to restore PASS

MC1 remains PARTIAL until one committed evidence run proves all of the following:

1. every one of **all discovered 2020+ releases** has an explicit outcome and every complete
   official FOMC/SEP release parses with zero unexplained failures;
2. a real **worker → DB → API** smoke returns 4/4 independent paths from persisted rows, rather than
   calling parser functions directly;
3. one failed release cannot erase successful observations from the same source run;
4. an unchanged rerun is idempotent, a changed artifact is retained as a new revision, and the prior
   revision remains replayable; and
5. persisted policy paths remain readable with the source network disabled.

The market shadow remains non-load-bearing. Its absence may degrade the optional fourth path but can
never be filled by relabeling an official committee or dealer observation.

## Evidence boundary and reproduction

The exact pre-hardening counts, failed keys, source URLs, and provenance limitations are frozen in
[pre-hardening-audit.json](pre-hardening-audit.json). The supported commands available at this
milestone are:

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py -q
uv run python scripts/research/fomc_sep_source_probe.py --self-check
uv run python scripts/research/fomc_sep_source_probe.py --year 2026 --require-shadow
```

The live probe command still selects only the newest FOMC and SEP release. It is useful for detecting
latest-page drift but is not the all-release gate above. The hardening milestone must replace it with
an all-release durable audit and a reproducible worker-to-API command before this document can say
PASS.

## Product and PM-agent contract

The FoundMetal PM agent may consume only the separately keyed actual, committee, dealer, and market
paths together with their evidence and coverage status. It must not average paths, attribute an SEP
dot to the Chair, or turn a failed/missing path into a neutral score. This milestone still adds no UI;
it repairs the durable evidence layer for the later top-down rates, dollar, and gold surface.
