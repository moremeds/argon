# MC2 inflation source feasibility probe

**Question:** MC2's plan names BLS and BEA as the official inflation sources. Can this desk reach
them, and can they satisfy MC2's first exit criterion — replay under `available_at <= as_of`?

**Answer: no on both counts, and the second failure is the one that matters.**

Measured 2026-08-18. Evidence: [probe.json](probe.json).

```bash
uv run python scripts/research/mc2_inflation_source_probe.py \
  --out docs/research/2026-08-18-mc2-inflation-source-probe/probe.json
```

## Result

| Source | Reachable | Serves vintages |
|---|---|---|
| `api.bls.gov` (public API v1, contact UA) | **no — HTTP 403** | no |
| `api.bls.gov` (public API v1, browser UA) | **no — HTTP 403** | no |
| `www.bls.gov` news release (browser UA) | **no — HTTP 403** | no |
| `apps.bea.gov/api` without a UserID | **no — but HTTP 200** | no |
| `www.bea.gov` release landing page | yes | no |
| **ALFRED / FRED `series/observations`** | **yes** | **yes** |

### BLS is blocked at the edge, not at the door

Every BLS host returns `403 Access Denied` with an Akamai reference id, on both the API and the
public website, with both a contact-bearing agent string and a full browser one. This is not an
authentication failure that a registered API key would fix, and not a User-Agent policy that a
politer header would satisfy — it is a network-level block on this desk's egress. **A BLS adapter
cannot be built here at all**, with or without credentials.

### BEA fails in the shape most likely to be mistaken for real data

`apps.bea.gov/api/data` without a `UserID` returns **HTTP 200, `text/plain`, zero bytes**. Not 401,
not 403, not a JSON error envelope. A client that follows the plan's own instruction to keep "zero
rows and HTTP errors distinct" will classify this as *zero rows* — a successful request that found
no data — when it is in fact a credential failure. Any BEA adapter must treat an empty 200 as a hard
error, and the probe records the flag `fails_silently_without_credential` for exactly this reason.

### ALFRED serves the point-in-time record the whole milestone is built on

Two separate measurements, both in `probe.json`:

**Vintages exist and land on the publisher's release dates.** CPI-U (`CPIAUCSL`) returned seven 2026
observations carrying seven distinct `realtime_start` values — 02-13, 03-11, 04-10, 05-12, 06-10,
07-14, 08-12. Every one is on the published CPI release calendar (FRED release 10), and the audit
asserts the set relationship rather than eyeballing it: `vintage_dates_not_on_the_release_calendar`
is empty. That is what licenses reading `realtime_start` as `available_at`.

**Superseded values survive.** Seasonally adjusted CPI is re-seasonalised each February, so a 2024
period has been restated twice. All six probed periods came back with three vintages each, on
half-open validity windows:

| period | `[realtime_start, realtime_end)` | value |
|---|---|---|
| 2024-01 | 2024-02-13 → 2025-02-11 | **309.685** |
| 2024-01 | 2025-02-12 → 2026-02-12 | 309.794 |
| 2024-01 | 2026-02-13 → 9999-12-31 | 309.698 |

A replay at `as_of = 2024-06-01` must read **309.685**. Today's value is 309.698. Reading the current
value into a historical state is precisely the backdating defect MC1 found twice in its own artifact
and observation layers — here the source itself prevents it, which is strictly better than us
policing it.

## Consequence for the MC2 plan

Task 2 as written ("Add official BLS and BEA fixtures", `sources/bls.py`, `sources/bea.py`) is not
buildable and would not have met the exit criterion if it were. **ALFRED is the primary source for
realized inflation**, using the FRED client and key the repo already holds.

The honest cost of that substitution, stated plainly: FRED is a *redistributor*, not the publisher.
MC1's evidence contract captures the publisher's exact bytes; MC2's realized-inflation leg will
capture the redistributor's bytes instead, and the provenance chain runs
`observation → FRED artifact → (BLS release, unfetchable from here)`. That is a real downgrade in
provenance and it must be recorded per observation rather than glossed. What it buys is the only
vintage record available at all, from any reachable source.

BEA's landing page is reachable and could anchor PCE release dates, but PCE index values have the
same vintage requirement and the same answer: take them from ALFRED (`PCEPI`, `PCEPILFE`).
