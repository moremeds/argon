# MC1 policy-source verdict — PASS with a non-load-bearing market shadow

**Measured at 2026-08-12 14:58:22 UTC.** All four free-source contracts returned HTTP 200, parsed
non-empty data, and retained exact artifact identities. The three policy-evidence pillars needed for
the official view are available directly from official publishers. Frenzy is usable only as an
optional market-pricing shadow because it publishes neither a reliable source timestamp nor a delay
contract.

## Measured result

| Source | State | Observed content | Exact primary artifact |
|---|---|---|---|
| Federal Reserve FOMC | PASS | 2026-07-29 hold, 3.50–3.75%, vote 9–3; 5 statement releases discovered | PDF, 171,262 bytes, SHA-256 `825cfed5e095…` |
| Federal Reserve SEP | PASS | 2026-06-17; 4 federal-funds-rate horizons, 19 projection rows | PDF, 1,216,132 bytes, SHA-256 `a51788762352…` |
| New York Fed SME | PASS | June 2026 Dealer panel; 16 path points, 5 probability distributions | XLSX, 253,265 bytes, SHA-256 `d0cf390537a6…` |
| Frenzy Capital Fed Watch | PASS as shadow | 3 meetings from 2026-09-16 through 2026-12-09; exactly five probability buckets per meeting, each bounded to 0–100%, and every distribution sums to 100% | HTML, 105,270 bytes, SHA-256 `1f2d0ee5af9f…` |

The SEP audit preserves the published medians and the anonymous distribution independently:
2026 has 18 participants / median 3.8%; 2027 has 18 / 3.6%; 2028 has 17 / 3.4%; longer run has 18 /
3.1%. This supports committee-distribution analysis but does not support assigning any dot to the
Chair or another participant.

## Decision

MC1's data-source gate passes for the evidence and API layer:

1. actual decisions and votes can replay from official release time;
2. committee projections retain the full anonymous distribution and published median;
3. Primary Dealer expectations stay a separately named survey population;
4. market pricing stays a separately named, optional shadow;
5. exact bytes are committed before normalization, so parser drift leaves evidence to audit;
6. one source failure degrades one path and cannot be concealed by another path.

The market shadow is deliberately **not** promoted to an official or realtime source. Its artifact
has `published_at=null`, `available_at=<first retrieval>`, `delay_status=unknown`, and
`delay_minutes=null`. The scheduler flag is default-off, and its outage does not fail the official
source gate unless the probe is run with `--require-shadow`. A future free OIS/futures source can replace
or corroborate it only after passing the same exact-artifact, timestamp, distribution-completeness,
and point-in-time tests.

## Product and PM-agent contract

The FoundMetal PM agent should consume the four keyed paths, their evidence references, freshness,
and contradiction records. It must not average them or convert a missing path into a neutral score.
Useful PM conclusions are comparative: what the committee projects, what dealers expect, what the
market prices, and how those differ from the latest actual target. Every statement should remain
traceable to the underlying release artifact and the as-of cutoff.

## Limitations

- This is one live retrieval, not a historical uptime study.
- Federal Reserve HTML bytes can change after publication; the stable PDF remains primary evidence.
- The NY Fed SME landing material did not supply a reliable results-publication timestamp for the
  selected workbook, so first retrieval is the honest point-in-time boundary.
- Frenzy is third-party and does not disclose page time or delay. `unknown` is not equivalent to
  zero delay, delayed by a known number, or realtime.
- This milestone does not add the visual comparison UI. It completes the immutable data, worker,
  replay, and API contract that the next UI slice can render.
- Validation used the isolated local test database. Production scheduling remains opt-in and still
  requires the normal deployment/data-health gate.

Machine-readable evidence and full hashes are in [probe.json](probe.json).
