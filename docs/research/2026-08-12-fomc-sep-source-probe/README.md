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

The gate is **PARTIAL**. The original `probe.json` established one successful latest-release
retrieval for each source contract, but it did not prove the production worker, the historical
2020-present release set, or a persisted 4/4 API response. The measured pre-hardening worker and
historical failures are frozen in [pre-hardening-audit.json](pre-hardening-audit.json), and the exact
requirements for restoring PASS are in [VERDICT.md](VERDICT.md).

The Federal Reserve PDF remains stable primary evidence. Accessible HTML is retained separately as
the deterministic extraction surface and may have different exact bytes after publication. The NY
Fed workbook is the structured dealer data path, while its PDF supports human audit. The Frenzy page
is retained byte-for-byte but is non-load-bearing: no official job or official path depends on it.

## Reproduce the currently supported checks

Run the network-free parser contract check:

```bash
uv run python scripts/research/fomc_sep_source_probe.py --self-check
```

Run the current latest-release live probe:

```bash
uv run python scripts/research/fomc_sep_source_probe.py \
  --year 2026 \
  --output docs/research/2026-08-12-fomc-sep-source-probe/probe.json
```

Add `--require-shadow` when explicitly requiring the optional third-party path. This command records
HTTP state, exact-byte hashes and lengths, parser versions, observed table counts, and the semantic
fields needed to detect drift. At this pre-hardening milestone it selects only the newest discovered
FOMC and SEP release; it is not the required all-release audit.

Run the verdict guard:

```bash
uv run pytest tests/unit/research/test_fomc_sep_verdict.py -q
```

## Data boundary

- `probe.json` was measured at its recorded `generated_at` and is a latest-release retrieval audit.
- `pre-hardening-audit.json` was generated on 2026-08-13 from the already observed MC1 exploratory
  worker and historical parser outputs. Their original execution time and exact temporary-DB command
  were not retained; the JSON says so explicitly rather than manufacturing provenance.
- The worker counts came from an isolated temporary database that was removed after inspection; they
  do not describe `option_wizard_local` or the Mac mini data lake.
- The historical FOMC parser boundary is 2021–2026 because production discovery returned no 2020
  releases. The separate 2020 candidate count comes from the official Federal Reserve history page.
- A later hardening artifact must enumerate all discovered 2020+ releases and run the real worker →
  DB → API path before the verdict can become PASS.

## Interpretation rules

- SEP dots are an anonymous participant distribution. No dot is attributed to the Chair.
- The NY Fed SME `Dealer` panel is not the committee and is not the futures market.
- Market-implied probabilities are not an official forecast.
- Paths may disagree. The product exposes those contradictions instead of calculating a blended
  “Fed score.”
- A missing path remains null with a reason. Another source does not silently substitute for it.
- When a publisher provides neither a reliable publication timestamp nor a contractual delay,
  `published_at` remains null, `available_at` is first retrieval, and delay is `unknown`.
