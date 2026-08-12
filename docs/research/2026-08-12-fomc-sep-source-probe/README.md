# FOMC, SEP, dealer-path, and market-shadow source probe

This directory is the reproducible source audit for Argon's MC1 policy-path contract. It measures
four free sources without treating them as interchangeable:

| Path | Publisher and artifact | Classification | Availability rule |
|---|---|---|---|
| Actual decision | Federal Reserve FOMC statement PDF plus accessible HTML | Free official | Published statement timestamp |
| Committee projection | Federal Reserve SEP PDF plus accessible HTML | Free official | Published SEP timestamp |
| Dealer expectations | New York Fed SME XLSX plus human-readable PDF | Free official, Primary Dealer panel | Publisher timestamp when supplied; otherwise first retrieval |
| Market implied | Frenzy Capital Fed Watch HTML | Free third-party shadow | First retrieval; delay is explicitly unknown |

The Federal Reserve PDF is the stable primary evidence for FOMC and SEP releases. Accessible HTML
is retained as a separate exact artifact because it is the deterministic extraction surface and its
bytes can change after publication. For the NY Fed survey, the structured workbook is the critical
data path and the PDF is retained for human audit. The Frenzy page is retained byte-for-byte before
parsing, including every published probability bucket, but is non-load-bearing: no official job or
official path depends on it.

## Reproduce

Run the network-free contract check:

```bash
uv run python scripts/research/fomc_sep_source_probe.py --self-check
```

Refresh the live evidence artifact:

```bash
uv run python scripts/research/fomc_sep_source_probe.py
```

The command writes `probe.json` and exits nonzero if any of the three official sources is
unreachable, malformed, or empty. The optional shadow is always reported but does not control the
official gate; add `--require-shadow` when specifically auditing all four live sources. The artifact
records HTTP state, exact-byte hash and length, parser version, observed table counts, and the
semantic fields needed to catch publisher drift. `probe.json` is a retrieval-time audit, not a
promise that a third-party page is realtime.

## Interpretation rules

- SEP dots are an anonymous participant distribution. No dot is attributed to the Chair.
- The NY Fed SME `Dealer` panel is not the committee and is not the futures market.
- Market-implied probabilities are not an official forecast.
- Paths may disagree. The product exposes those contradictions instead of calculating a blended
  “Fed score.”
- A missing path remains null with a reason. Another source does not silently substitute for it.
- When a publisher provides neither a reliable publication timestamp nor a contractual delay,
  `published_at` remains null, `available_at` is first retrieval, and delay is `unknown`.

See [VERDICT.md](VERDICT.md) for the measured 2026-08-12 result and limitations.
