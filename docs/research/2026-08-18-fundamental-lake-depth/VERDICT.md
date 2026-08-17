# Lake price depth does NOT gate the valuation band on the production host

**Verdict:** D5 of `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` is **overturned**.
It concluded that widening the fundamental universe buys ~29 extra valuation bands because the
144 candidate names lack unadjusted daily closes, and therefore that "the real gate on the
valuable half is lake price depth, not universe membership." That was measured on the MacBook
mirror. On the mini — the host that actually computes the bands — **the gate is membership, and
the yield is up to 132, not 29.**

**Trace:** `depth_macbook.json`, `depth_mini.json` (per-ticker file presence, row count, first/last
close, and depth flags at both band thresholds, for all 401 names).
**Probe:** `scripts/research/fundamental_lake_depth_probe.py` — reproduce commands in its docstring.
**As-of:** 2026-08-18, passed explicitly as `--as-of` so re-runs are comparable.

## What was measured, and why not file existence

D5 counted `1d.parquet` presence. That is coverage, not computability — the same conflation that
produced the retracted `0/257` concentration verdict two rounds ago
(`docs/research/2026-08-13-fundamental-concentration-axis/VERDICT.md`). A band is refused unless
`MIN_HISTORY` (12) of the trailing `WINDOW_QUARTERS` (20) quarters carry **both** a statement and a
close at that quarter's own knowledge date (`src/uw_scan/fundamentals/valuation.py:146-151`). So the
probe reports depth at both thresholds and measures the statement leg separately.

## Result

| cohort | metric | MacBook mirror | **mini `/lake`** |
|---|---|---:|---:|
| 257 universe | has `1d.parquet` | 254 | **257** |
| | price depth ≥ 12q | 252 | **256** |
| | price depth ≥ 20q | 251 | **255** |
| 144 excluded | has `1d.parquet` | 29 | **141** |
| | price depth ≥ 12q | 23 | **132** |
| | price depth ≥ 20q | 21 | **120** |
| | statement depth ≥ 12q | 143 | 143 |
| | statement depth ≥ 20q | 139 | 139 |

The mirrors are not the same object: the MacBook holds **653** equity symbol directories, the mini
**14,689**. D5's 254/257 and 29/144 reproduce exactly on the MacBook, so the original measurement
was correct — it was taken on the wrong host.

**The statement leg is not the constraint** (143/144 clear 12 quarters). Price depth binds, and on
the mini it binds at 132, not 29.

## What this does to PR-1

| | D5 | measured on the mini |
|---|---|---|
| extra valuation bands | +29 | **up to +132** |
| panel | 254 → 283 (+11%) | 254 → **up to 386 (+52%)** |

D5 argued the raw +56% panel-width figure was an illusion and the real gain was ~+11%. On the
production host the raw figure was approximately right. **PR-1 is worth roughly 4.5× what the plan
credits it with.**

## The bound is an upper bound, and this is the honest limit

132 is *necessary*, not *sufficient*. The method also refuses on non-positive enterprise value,
a non-positive numerator, and a stale filing. Observed conversion on the universe cohort: 256 names
clear the 12q price gate on the mini and prod carries **254** `valuation_anchors` — 99.2%. That rate
must **not** be transferred to the 144: the universe was selected for marketcap ≥ $30B, while the
144 are the capex-chain research cohort and carry more unprofitable and negative-EV names, which is
exactly what the EV guard refuses (`valuation.py:406-413`). The true count is unmeasurable until those
statements exist in prod — which is PR-1's own ingest step, so PR-1 should carry the count as its
verification rather than assert it up front.

## Two incidental findings

**Prod is not dark.** The mini's `option_wizard` holds `fundamental_universe` 257,
`fundamental_statement_obs` 257 tickers, `fundamental_scores` 257, `valuation_anchors` 254. An
earlier record that the fundamentals lane "shipped DARK / prod unseeded" is stale. Prod ingested the
universe only — the 144 exist solely in `option_wizard_local`, from the capex research backfill.

**Three names are absent from the mini lake entirely:** `CFLT`, `CYBR`, `PSTG`. Real, liquid US
listings, so this is a livewire coverage gap rather than a probe artifact. Not chased here.

**Apex answered 200.** D5 recorded a 502 when it probed apex and left the mini depth unverified on
that basis; `http://100.66.147.98:8322/health` is up. The measurement above does not use apex —
the band reads parquet directly — but the reason D5 gave for not checking no longer holds.
