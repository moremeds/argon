# FOMC, SEP, dealer-path, and market-shadow source probe

This directory is the reproducible source audit for Argon's MC1 policy-path contract. It keeps four
free sources separate:

| Path | Publisher and artifact | Classification | Availability rule |
|---|---|---|---|
| Actual decision | Federal Reserve FOMC statement PDF plus accessible HTML | Free official | Published statement timestamp |
| Committee projection | Federal Reserve SEP PDF plus accessible HTML | Free official | Published SEP timestamp |
| Dealer expectations | New York Fed SME XLSX plus human-readable PDF | Free official, Primary Dealer panel | Publisher timestamp when supplied; otherwise first retrieval |
| Market implied | Frenzy Capital Fed Watch HTML | Free third-party shadow | First retrieval; delay is explicitly unknown |

## Current gate status

The gate is **PASS**, on two committed evidence files measured 2026-08-18:
[probe.json](probe.json) (55/55 FOMC statements and 25/25 SEP releases parse across 2020–2026, zero
failures) and [smoke-4x4.json](smoke-4x4.json) (worker → DB → API returns 4/4 paths from persisted
rows, 8/8 assertions, 80/80 releases `ok`). The pre-hardening baseline that produced the earlier
PARTIAL is preserved unchanged in [pre-hardening-audit.json](pre-hardening-audit.json); the gate
history and what the hardening changed are in [VERDICT.md](VERDICT.md).

The Federal Reserve PDF is stable primary evidence. Two fetches of the same PDF one second apart are
**byte-identical**; two fetches of the same HTML have identical content-length and a different
SHA-256, with a differing `__CF$cv$params` token — the per-request Cloudflare script carrying a
unique ray id. Both comparisons are recorded under `source_byte_stability.measured` in
`smoke-4x4.json`. Across the archive: **82 stable records** (everything whose media type is not
`text/html` — the Fed PDFs plus the NY Fed workbook) were unchanged across a rerun, while **81 HTML
records became 162**, each gaining exactly one revision. That churn is transport, not publisher: the facts are unchanged,
so a re-fetched page is preserved as exact evidence and linked as another witness of the same
observation rather than becoming a second fact. The NY Fed workbook is the structured dealer data
path, while its PDF supports human audit. The Frenzy page is retained byte-for-byte but is
non-load-bearing: no official job or official path depends on it.

## Reproduce the currently supported checks

Run the network-free parser contract check:

```bash
uv run python scripts/research/fomc_sep_source_probe.py --self-check
```

Run the all-release live probe over the durable window:

```bash
uv run python scripts/research/fomc_sep_source_probe.py --start-year 2020
```

Add `--require-shadow` when explicitly requiring the optional third-party path. This command records
HTTP state, exact-byte hashes and lengths, parser versions, observed table counts, and the semantic
fields needed to detect drift — for **every** discovered release, not the newest one. Selecting
`max(meeting_date)` made the observable failure rate structurally zero: one release was read, and a
source with 24 broken siblings still reported `ok`. The SEP parser sat at 1-of-25 under exactly that
blind spot.

Each source reports `releases_discovered` / `releases_succeeded` / `releases_failed` plus a
per-release array carrying its `release_key`, `event_date`, `event_class`, `state`, artifact hashes
by media type, and any bounded error. A source's state is the worst state among its releases, and a
source that discovered nothing is `empty`, never `ok`.

Backfill the same window into Postgres through the production worker entry points:

```bash
uv run python scripts/backfill/macro_policy_history.py --start-year 2020 --resume
uv run python scripts/backfill/macro_policy_history.py --verify
```

`--resume` reads `macro_release_ingest_status` and skips a **past** year whose every discovered
release already reached `ok`. The current year is never skipped: the Fed has not finished publishing
into it, so "complete" cannot be true of it. Both commands exit non-zero if any release in the window
is not `ok`, and if the window produced no releases at all — a vacuous pass would hide a discovery
outage.

Run the verdict guard, which checks the PASS claim against both evidence files rather than trusting
the sentence:

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py -q
```

Run the deterministic end-to-end smoke (fixture bytes, real worker/DB/API):

```bash
uv run pytest tests/integration/worker/test_macro_policy_4x4_smoke.py -q
```

Run the strict live 4/4 smoke against a database you created for the run:

```bash
createdb option_wizard_test_mc1_smoke -O argon_app
UW_SCAN_DB_NAME=option_wizard_test_mc1_smoke UW_SCAN_ALLOW_DB_MISMATCH=1 bash scripts/migrate.sh
UW_SCAN_TEST_DB_NAME=option_wizard_test_mc1_smoke \
  uv run python scripts/research/macro_policy_4x4_smoke.py --require-shadow
dropdb option_wizard_test_mc1_smoke
```

## Data boundary

- `probe.json` was measured at its recorded `generated_at` and is an all-release audit of the years
  it names in `years`. The 2026-08-18 run reports 55/55 FOMC statements and 25/25 SEP releases
  parsing across 2020–2026, zero failures. Six dissents were checked by hand against published
  history: Mester (2020-03-15, 9-1), Kaplan and Kashkari (2020-09-16, 8-2), Bullard (2022-03-16,
  8-1), George (2022-06-15, 10-1), Bowman (2024-09-18, 11-1), Hammack (2024-12-18, 11-1). That is
  six of the fourteen dissent-bearing releases, not all of them — and the review that noticed the
  gap also found the one release in the unchecked remainder that was wrong (2025-10-29, recorded
  10-1 for a real 10-2; see VERDICT.md). `roster_total` now travels with each release so the same
  anomaly is visible without recomputing it.
- `pre-hardening-audit.json` was generated on 2026-08-13 from the already observed MC1 exploratory
  worker and historical parser outputs. Their original execution time and exact temporary-DB command
  were not retained; the JSON says so explicitly rather than manufacturing provenance.
- The worker counts came from an isolated temporary database that was removed after inspection; they
  do not describe `option_wizard_local` or the Mac mini data lake.
- The historical FOMC parser boundary was 2021–2026 in the pre-hardening audit because production
  discovery returned no 2020 releases. That is closed: discovery now returns both 2020 unscheduled
  meetings (2020-03-03 and 2020-03-15) and all 55 statements parse.
- `smoke-4x4.json` records the command, UTC start and finish, database class (never credentials),
  both parser-version families, source URLs, four worker results, table counts around the idempotent
  rerun, the four API slots with their observation and artifact ids, and the correction/PIT and
  offline assertions. Its database was created for that run and dropped afterwards.

## Interpretation rules

- SEP dots are an anonymous participant distribution. No dot is attributed to the Chair.
- An empty `voted_against` means "no dissenter was named", which is only the same as "no dissenter"
  when `voter_names_stated` is true. Two of the 55 statements publish a tally alone, and one of them
  is a 9-3 vote: reading its empty roster as unanimous would contradict its own tally.
- The NY Fed SME `Dealer` panel is not the committee and is not the futures market.
- Market-implied probabilities are not an official forecast.
- Paths may disagree. The product exposes those contradictions instead of calculating a blended
  “Fed score.”
- A missing path remains null with a reason. Another source does not silently substitute for it.
- When a publisher provides neither a reliable publication timestamp nor a contractual delay,
  `published_at` remains null, `available_at` is first retrieval, and delay is `unknown`.
