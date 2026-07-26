# Sector crowding (板块拥挤度) — executive summary

**Date:** 2026-07-26 · **Branch:** `feat/sector-crowding` (7 commits, 30 files,
+5,997/−18) · **State: shipped to the branch, not pushed, no PR. Do not merge as-is
— see Open defects.**

---

## 1. What it is

A per-sector-ETF crowding read on the regime page's **Market Tide** tab. Fourteen
ETFs scored against SPY on three legs, reduced to one badge.

Adapted from [bitfool1, 2026-07-21](https://x.com/bitfool1/status/2079479920162734401).
The framework's claim is **conjunctive** — 三者同时出现，才算真正拥挤 (all three must
appear together to count as genuinely crowded) — so the state is the **weakest**
present leg's band, not the mean. `score` stays the mean, used only to sort rows
inside a band. `binding_leg` names the leg holding the state down.

| Leg | Measures | Definition |
|---|---|---|
| `price` | Is the sector extended? | 63-session return minus SPY's, expressed as that ETF's **own trailing percentile** |
| `flow` | Is money chasing it? | 21-session net premium flow ÷ AUM, scored on the source's published 2% / 5% / 10% bands |
| `premium` | Is the crowd paying up? | `iv_rank` minus SPY's `iv_rank` |

The percentile on the price leg is load-bearing. Raw spread is not comparable across
the universe — trailing SD of the 3M spread runs from 3.1 (XLY) to 16.5 (XLE), so
ranking on raw spread ranks volatility, not crowding. XLF at +3.14% is its 99th
percentile; SMH at +17.88% is its 46th.

**The `premium` leg is a substitute, not the original design.** The source framework's
third indicator is **NTM (forward) P/E**. That was replaced with IV-rank spread
because forward EPS was believed unavailable. §5 revisits that and finds it was only
partly true.

---

## 2. Data provenance — what comes from where

Every input is persisted before the score reads it. The score itself has **no table**
— it is read-time compute, because nothing in it is the only copy of anything.

| Leg / field | Warm-store table | Column | Fetched from | Vendor |
|---|---|---|---|---|
| `price` — ETF close | `etf_flows_daily` | `close` | `/api/etfs/{t}/in-outflow` | **UW** |
| `price` — SPY close | `etf_flows_daily` | `close` | `/api/etfs/SPY/in-outflow` | **UW** |
| `flow` — net premium | `etf_flows_daily` | `premium_change_usd` | `/api/etfs/{t}/in-outflow` | **UW** |
| `flow` — AUM divisor | `etf_aum_cache` | `aum` | `/api/etfs/{t}/info` | **UW** |
| `premium` — ETF IV rank | `watchlist_card` | `iv_rank` | UW iv-rank fetcher | **UW** |
| `premium` — SPY IV rank | `watchlist_card` | `iv_rank` | UW iv-rank fetcher | **UW** |

**Single-vendor by construction: all six inputs are UW.** That is the root of the
defect in §3 — there is no cross-check anywhere in the chain, and one endpoint's
outage propagates into two legs at once.

Sources used in the *research* around the panel, but not by the panel itself:

| Purpose | Source | Vendor |
|---|---|---|
| Corrected price leg (§3 fix) | `daily_ohlc.close` | **massive.com** |
| 5-year backtest bars | `/bars/{ticker}` (apex REST, `:8322`) | **apex** (livewire lake) |
| Constituent holdings/weights | `/api/etfs/{t}/holdings` | **UW** |
| Constituent trailing EPS | `/vX/reference/financials` | **massive.com** |
| Constituent forward EPS curve | `/stable/analyst-estimates` | **FMP** |

### Capture and serving

- **Job** — `sector_crowding_capture`, nightly **18:45 ET**. One `in-outflow` + one
  `info` call per ticker × 15 = ~30 UW calls/night against a 120k/day budget.
  45-day re-fetch tail absorbs UW revising recent figures. `as_of` is stamped with
  the market **date** (not wall clock) so a same-day re-run collides on
  `(ticker, obs_date, as_of)` and no-ops — idempotent by construction.
- **API** — `GET /regime/sector-crowding`
- **UI** — `SectorCrowdingPanel.tsx` + `SectorCrowdingCharts.tsx` (hand-rolled SVG)
- **Universe** — 14 tickers. **ARKK deliberately absent**: UW's `in-outflow` returns
  0 rows for it (verified 2026-07-24).

---

## 3. The headline finding: a flow outage was read as a price outage

**Symptom.** SOXX printed **CROWDED** while SMH printed **NORMAL**, despite holding
substantially the same semiconductor complex — the two should track closely.

**Root cause.** UW's `/api/etfs/{t}/in-outflow` silently stopped serving **SOXX, IGV
and IAU on 2026-05-15**. SOXX and IGV resumed **2026-07-01**; IAU never did.
Confirmed three independent ways: a live UW probe, a backfill attempt, and
production's own IAU rows ending exactly 2026-05-15 while GLD/GLDM run to 2026-07-23.

**Why it corrupted the score.** The price leg reads `close` off the **flow** endpoint
(§2, row 1). Both windows are **row-indexed, not calendar-anchored**, so a 47-day
hole doesn't shorten the series — it stretches it:

| | Clean SPDRs | SOXX / IGV |
|---|---|---|
| 63-row return window spans | 92 calendar days | **135 calendar days** |
| 21-row flow window spans | 29 calendar days | **73 calendar days** |

Today's observation and the reference distribution it is ranked against were measured
on different horizons. The percentile was arithmetically valid and semantically
meaningless.

**Corrected result.** `daily_ohlc` (massive.com) has **all 16 tickers with zero gaps**
(266–321 rows) and contains exactly the 30 rows SOXX was missing. Repointing the
price leg and re-running against production:

| | Before (UW flow close) | After (massive `daily_ohlc`) |
|---|---|---|
| Window span | SOXX 135d, others 92d | **92d for all 15** |
| SOXX relative return | — | **+15.20% → 41st pct → NORMAL** |
| SMH relative return | — | **+12.16% → 29th pct → NORMAL** |
| Gap between them | ~36 percentile points | **3 points** |

**SOXX is NORMAL, not CROWDED.** The two semis ETFs do line up, as expected.

`★ The generalizable lesson` — the failure was never a wrong number, it was a
**well-formed HTTP 200 with missing rows**. Nothing raised, nothing logged, the
percentile computed cleanly. Row-indexed windows are the amplifier: they convert a
data gap into a silent redefinition of the statistic. Calendar-anchor any window
whose output is compared against its own history.

---

## 4. Empirical verdict: no tradable threshold exists

16,706 sector-days, 15 ETFs, 2021-06-22 → 2026-07-24, forward returns SPY-relative,
point-in-time expanding percentiles (no lookahead), t-stats on non-overlapping
windows.

**Percentile level separates nothing.** Every bucket effect lands inside ±0.7% with
hit rates in a 44–55% band. ~84 cells examined; two cleared |t|=2 — exactly what
chance supplies.

**The one coherent story flips sign between halves.** Splitting the top decile by
recent momentum produced a textbook crowding picture — extended-and-fading bad,
extended-and-rising fine. Then:

| `CLIMAX` (pct ≥ 90, mom ≤ 0) | mean | hit | t |
|---|---|---|---|
| 2021–23 | **+1.16** | **63%** | +2.3 |
| 2024–26 | **−1.94** | **29%** | −1.8 |

A buy signal in the first half, a sell signal in the second. The full-sample −0.52 is
their average.

**The positive entry bucket is one trade.** `SMH +3.97`, `SOXX +2.16`, `MAGS +2.87`,
`XLK +1.41` against `XLU −0.76`, `XLY −1.03`, `XLV −0.74`. "Extended and accelerating
works" means "semiconductors went up in 2024–26."

**Flow and premium legs were deliberately not tested** — underpowered by construction.
fwd21 SD is 4.91%, so minimum detectable effect at |t|=2:

| Leg | History | Non-overlapping n | Detects |
|---|---|---|---|
| price | 5y (apex bars) | ~1,100 | **0.30%** |
| flow | ~250d (`etf_flows_daily`) | ~170 | 0.75% |
| premium | 140d (`watchlist_card`, from 2026-01-02) | ~85 | 1.06% |

The best-powered leg resolves to 0.30% and found nothing stable. Asking a leg that
cannot see below 1.06% to confirm is not a test.

**Conclusion: the panel is a descriptive surface, not a timing one.** Consistent with
two prior findings in this repo — VCG forward-returns (descriptive, not predictive)
and GEX regime-persistence (weak, confounded, not built). Do not calibrate thresholds
to this data; any "sweet spot" fit here is the 2024–26 semis run.

---

## 5. Can the original NTM P/E leg be restored?

The framework's third indicator is NTM P/E. No vendor publishes it for an ETF, so it
needs bottom-up assembly: `Σwᵢ·Pᵢ / Σwᵢ·NTM_EPSᵢ`. Probed all three vendors live.

| Input | Source | Status |
|---|---|---|
| Holdings weights | UW `/api/etfs/{t}/holdings` | ✅ `ticker` + `weight` |
| Constituent prices | massive grouped-daily | ✅ 12,410 tickers in **one** call |
| **Forward EPS curve (FY1…FY5)** | **FMP `/stable/analyst-estimates`** | ⚠️ **200 — epsAvg/High/Low + analyst count, but entitled per-symbol: 26/30 SOXX names are 402** |
| Forward EPS, quarterly | FMP `period=quarter` | ❌ 402 premium |
| Forward EPS, Q+1 only | UW `/api/stock/{t}/earnings` | ✅ 1 quarter, ~30y of reports |
| Forward EPS curve | UW `/api/companies/{t}/earnings-estimates` | ❌ 403 advanced tier |
| Forward EPS curve | massive `/benzinga/v1/*` (5 paths) | ❌ 403 not entitled |
| ETF holdings fallback | FMP `/stable/etf/holdings` | ❌ 402 restricted |
| **Historical estimate snapshots** | **all three** | ❌ **none** |

**Endpoint access is not the same as data access.** FMP serves the curve, so on paper
the level is buildable: interpolate NTM from FY1/FY2, 1 call per ticker against a
**250/day** quota vs 599 constituents (a 3-day rotation at ~200/day, since estimates
revise on analyst action rather than daily). Building it end-to-end for SOXX proved
otherwise — two blockers invisible to endpoint-level probing:

**① `analyst-estimates` is entitled per *symbol*, not per plan.** 26 of 30 SOXX
constituents return **402** `"This value set for 'symbol' is not available under your
current subscription"`. Only AMD, NVDA, INTC and TSM resolve — **26.59% of the fund's
99.90% weight**. XLK's top ten reaches 6/10, covering 42.80% of its 59.24%.

The gaps are **not random**. In XLK, MU / AVGO / AMAT / LRCX are blocked while
NVDA / AAPL / MSFT / AMD / INTC / CSCO pass — the blocked cohort is semis and semicap,
systematically the highest-multiple names. Renormalising over the survivors therefore
biases the aggregate P/E **downward** by a sector-dependent amount that drifts with
leadership. Worse: the bias *anti-correlates with the signal* — a semis-led melt-up is
exactly when the missing names dominate the true aggregate, so the indicator would read
calmest precisely when the thing it measures is happening. That is a confidently wrong
number, not a noisy one.

**② Estimates arrive in reporting currency, with no field to detect it.** TSM returns
`epsAvg=323.34` and `revenueAvg=3.81e12` — TWD (its USD revenue is ~1.2e11) — divided
into a USD 403 ADR price, printing a P/E of **0.65**. The response carries 22 fields and
none of them is a currency. Every foreign constituent (TSM, ASML, ASX, ARM) is silently
mis-united; fixing it needs an FX rate *and* the ADR-to-ordinary ratio from elsewhere.

The SOXX aggregate printed **3.61**, which is how ② surfaced at all.

**Single-name NTM P/E for a whitelisted ticker does work today** — NVDA came out clean
at 19.03 (price 206.84, NTM EPS 10.87). Only the ETF-level aggregate is blocked. ① is a
402, so an FMP upgrade would buy it; ② needs a second source regardless.

**Three traps.** ① FMP's `limit` truncates from the **furthest-out** year:
`limit=3` returns FY2029–2031 and silently omits the years NTM needs, as a clean 200.
Use `limit=10`. ② `period=quarter` is 402, so NTM must be interpolated from annual
figures — wrong for seasonal sectors. ③ `/api/v3/*` and `/api/v4/*` are **403 retired
legacy** since 2025-08-31; use `/stable/`. Note **403 = retired, 402 = plan lacks it** —
only the latter is buyable.

**The wall that stands.** All three vendors return the *current* estimate per period,
never what it was on a past date. UW's archive shows all 109 NVDA quarters
`inserted_at 2026-03-10` / `updated_at 2026-07-25`, split-adjusted retroactively — a
restated bulk load, not contemporaneous capture. So `PE_level` (needs a 5–10y
percentile) and `EPS_revision_3m` (needs the estimate's path) have **no historical
series**. Point-in-time consensus is an I/B/E/S / Refinitiv / FactSet product.

---

## 6. Open defects

| # | Defect | Evidence | Severity |
|---|---|---|---|
| 1 | **Price leg reads `close` off UW's flow endpoint**, inheriting flow outages as price outages | §3 — SOXX read CROWDED, is NORMAL | **High — corrupts the score** |
| 2 | **Windows are row-indexed, not calendar-anchored** — a data gap redefines the statistic | 135d vs 92d spans | **High — silent amplifier** |
| 3 | `flow_score(0.0)` = 20, below `BAND_NORMAL` = 25 → structurally near-zero SPDR flows pin the flow leg **COLD**, and min-band propagates it to the whole row | 9 of 15 rows read COLD on flow or premium | **Medium — calibration judgment call** |
| 4 | UW serves **zero holdings for SMH and MAGS** (`{"data": []}` at HTTP 200; SMH's own `/info` declares 26). FMP fallback is 402 | §5 probe | Medium — blocks bottom-up for 2 tickers |
| 5 | UW `/holdings` **truncates at 250 rows** (SPY: 91.25% of weight) | §5 probe | Low — irrelevant to sector legs, but a hard cap to respect |
| 6 | All 15 rows divide **every historical bar by today's AUM** — `etf_aum_cache` keeps one row per ticker, so older bars read low if the fund grew | Documented in code; charts are a shape cue only | Low — by design, needs a table to fix |
| 7 | MAGS is **not in the universe** | `SECTOR_CROWDING_TICKERS` is 14, MAGS absent | Low — user-requested addition |
| 8 | apex bars carry **adjustment seams** for XLE/SMH at 2021-06-11/18/21 (~±100% single-day moves); both series also end 2026-07-13, 11 sessions behind the others | §4 backtest excluded them via `START` | Low — research-only, livewire issue |

---

## 7. Recommendation

**Do not merge the branch as it stands.** Defect #1 means the shipped panel can print
a false CROWDED badge, and it did.

**Minimum to make it honest** (one PR, on the existing branch):

1. Repoint the price leg at `daily_ohlc.close` (massive.com) — the data is already
   captured, gap-free, and contains exactly what UW dropped. Breaks the single-vendor
   dependency for the leg that matters most.
2. Calendar-anchor both windows so a future gap shortens the series instead of
   silently restretching it.
3. Add MAGS.
4. Re-derive the probe fixtures and affected unit tests.

**Do not add a fourth leg, NTM or otherwise.** §4 shows the best-powered existing leg
predicts nothing stable and the min-band aggregator has no empirical support. A fourth
leg adds surface, not signal.

**Reframe the display rather than the rule.** The `binding_leg` reduction hides three
leg values behind one label. The empirical work gives no reason to prefer min over any
other aggregator — but none to prefer a *fitted* aggregator either. Show all three
bands and mark which are absent. That is a display change, not a new rule dressed up
as calibrated.

**The one candidate still worth considering** is a daily capture of FMP's forward EPS
curve — as a standalone per-stock series, not an ETF leg. It is the only way
`EPS_revision` will ever exist (every vendor overwrites in place), it needs **no long
history to be meaningful** because a revision is a change rather than a level, and it is
immune to the provenance problem because the timestamps would be ours. Its ceiling is
now known, though: the per-symbol whitelist caps it at the names FMP will serve, so it
is a **watchlist-scoped** capture, not a universe-scoped one, and it cannot roll up to
an unbiased sector aggregate. Scope it to the tickers already on the watchlist, let it
accrue a quarter, then test the revision term against forward returns before it touches
any panel.

---

## Artifacts

| File | Contents |
|---|---|
| `docs/research/2026-07-26-sector-crowding-probe.md` / `.json` | Original validation probe (committed) |
| `docs/research/2026-07-26-sector-crowding-lifecycle.md` / `.json` | §4 empirical study, full 16,706-row panel |
| `docs/research/2026-07-26-ntm-pe-sourcing-probe.md` | §5 three-vendor entitlement probe |
| `docs/research/2026-07-26-ntm-pe-feasibility.json` | §5 end-to-end SOXX build: per-constituent HTTP code, weight, price, NTM EPS |
| `scripts/research/sector_crowding_probe.py` | Reproduces the original probe |
| `scripts/research/sector_crowding_lifecycle.py` | Reproduces §4 |
| `scripts/research/ntm_pe_sourcing_probe.py` | Reproduces §5's entitlement probe (~7 FMP calls) |
| `scripts/research/ntm_pe_feasibility.py` | Reproduces §5's SOXX build (1 UW + 1 massive + 1 FMP call per constituent) |
| `docs/superpowers/plans/2026-07-26-sector-crowding-panel.md` | Implementation plan (reviewed SHIP, executed) |

```bash
uv run python scripts/research/sector_crowding_lifecycle.py
uv run --with pyyaml python scripts/research/ntm_pe_sourcing_probe.py
```
