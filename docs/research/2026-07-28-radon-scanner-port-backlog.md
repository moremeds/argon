# Radon scanner port — recon + backlog

**Date:** 2026-07-28
**Source repo:** `/Users/chenxi/projects/radon` (read-only recon, nothing modified)
**Status:** Theta Harvester picked up now; the other three logged here, not started.

Radon's web UI exposes four options scanners as tabs: `THETA HARVESTER`,
`7-STEP STRENGTH`, `LEAP`, `GARCH`. The goal is to land them under argon's
`/scanner` page as sub-tabs, with the existing flow scanner becoming a sub-tab
alongside them. This doc records what each one actually is, so the remaining
three can be picked up later without re-reading radon.

## Radon's shared architecture (and why we don't port it)

| Piece | Radon | Argon equivalent |
|---|---|---|
| Scan trigger | FastAPI `POST /<name>/scan` shells out to a standalone script via subprocess, with a per-scanner in-process cooldown lock | APScheduler job in `worker/jobs/` |
| Persistence | Script writes `data/<name>.json` atomically, then best-effort mirrors a whole-JSON blob into Turso (`payload TEXT` column, one row per scan) | Postgres table with real per-row columns, `storage/<domain>_repository.py` |
| Read path | Next.js route reads Turso row vs disk JSON, whichever is fresher, 6h staleness threshold | Read-only FastAPI router → `web/lib/api.ts` |
| Code shape | No shared base class or registry. Each scanner is a 700–950-line standalone module with its own `scan_ticker` / `build_output` / `save_cache` / `main()` | `src/uw_scan/scanner/` already splits pipeline / signals / ranking / gates / discovery |
| Tab strip | `web/components/ScannerModeTabs.tsx` — static `TABS` array, hand-edited per scanner | to build |

Radon has **no shared scanner scaffolding worth porting**. The subprocess +
JSON-blob-cache pattern is strictly worse than what argon already has. The port
is a port of *compute logic only* — plumbing gets rewritten to argon's shape.

Every radon scanner fetches Unusual Whales live, per-ticker, per-scan, and
persists only a summary blob. None of them read a durable options-surface
warehouse, because radon has none. Argon does
(`option_surface_grid_daily`, 2025-12-26→present). That difference is the
central design decision for each port and is **not yet settled** — see
"Open decisions" below.

## 1. Theta Harvester — IN PROGRESS

`scripts/theta_harvester_scanner.py` (715 lines) + API handler (~90) +
web routes (183) + `ThetaHarvesterScanner.tsx` (440). ~1430 lines total.

Short-strangle candidate finder. Constants: `MIN_DTE=7`, `MAX_DTE=45`,
`TARGET_DELTA=0.16`, `NEAR_ZERO_DELTA=0.10`, `RISK_FREE_RATE=0.045`.

**Leg selection** (`select_short_strangle`): filter chain to `7 <= dte <= 45`;
candidate calls `strike > spot and 0.05 <= delta <= 0.35`, candidate puts
`strike < spot and 0.05 <= abs(delta) <= 0.35`; iterate all call×put combos
sharing an expiry, pick the minimum of:

```python
score = (abs(net_delta) * 100
         + abs(abs(call.delta) - 0.16) * 20
         + abs(abs(put.delta)  - 0.16) * 20
         + abs(dte - 30) / 10
         + (0 if theta > 0 else 20))
```

**Verdict** (`_score`): six gates, four of them "critical".

```python
delta_gate  = abs(net_delta) <= 0.10
iv_gate     = iv_rv_edge >= 5 or iv_rv_ratio >= 1.10
dealer_gate = dealer_support == "SUPPORT"
theta_gate  = theta > 0
gamma_gate  = gamma < 0 and abs(net_delta) <= 0.20
range_gate  = range_score >= 0.35

score = (max(0, 25 - abs(net_delta)/0.10*25)      # delta neutrality, 25
       + max(0, min(25, iv_rv_edge * 2.5))        # vol edge, 25
       + (20 if dealer_gate else 0)
       + (15 if theta_gate else 0)
       + max(0, min(10, range_score * 10))
       + (5 if gamma_gate else 0))                # max 100

critical = delta_gate and iv_gate and theta_gate and dealer_gate
verdict = ("THETA_HARVEST"        if critical and score >= 70
      else "DIRECTIONAL_DISGUISE" if abs(net_delta) > 0.20 or not iv_gate
      else "WATCHLIST")
```

**Dealer support** (`analyze_dealer_support`): sum `call_gex + put_gex` per
strike, find the highest strike at/below spot where net GEX flips negative→
positive (the "gex flip"), flag `SUPPORT` when total net GEX > 0 **and** spot
is at/above the flip.

**Range score** (`range_metrics`): `trend` = 21-session pct change;
`expected` = HV20-scaled 20-day move;
`range_score = clamp(0, 1 - abs(trend)/(expected*1.25), 1)`.

**Inputs** (all UW in radon): daily OHLC ≥21 bars (HV20/HV60, spot, 21d trend),
IV rank, full option chain with per-contract `strike/right/iv/delta/theta/
gamma/vega/bid/ask/volume/open_interest`, and greek-exposure-by-strike
(`call_gex`, `put_gex`). Radon computes Black-Scholes greeks itself
(`bs_greeks`) as a fallback when UW omits them.

## 2. 7-Step Strength — NOT STARTED

`scripts/strength_confirmation_scanner.py` (956 lines) + ~1478 total.

Seven factor groups, each 2–3 boolean checks; a group passes only if all its
checks pass. `verdict = REAL_STRENGTH_CONFIRMED if 7/7, WATCHLIST if >=5, else
WEAK`. `score = groups_passed / 7 * 100`.

Groups: (1) Q-scores, (2) net GEX, (3) call positioning, (4) term structure,
(5) vol smile, (6) systematic positioning, (7) market breadth.

**Port this one with eyes open.** Three of the seven groups are self-labelled
`source="APPROX"` in radon's own code — reconstructed because radon has no feed
for them:

- **Q-scores** is invented arithmetic with no external referent:
  `option_score = clamp(1 + call_ratio*3.2 + call_buy_ratio*0.8, 0, 5)` and
  friends. There is no "Q-score" data source; the numbers are a fabrication
  dressed as a factor.
- **Term structure** and **systematic positioning** (CTA / vol-control /
  risk-parity) are proxied from radon's own CRI scanner output read off disk
  (`data/cri.json`), plus a `vvix_vix_ratio` fudge (×1.04 / ×0.98) to
  synthesize a back-month VIX. Radon's code says outright: "No direct CTA
  net-flow, vol-control, or risk-parity allocation feed found."
- **Market breadth** reads a second cross-scanner disk cache
  (`data/breadth.json`) with a 5-day freshness check, falling back to a
  momentum proxy.

Argon has real CRI/VCG (`src/uw_scan/scanners/{cri,vcg}.py`) and could
substitute for groups 4 and 6 properly. Group 1 has no honest port — either
drop it (making it 6-step) or find a real data source. Heaviest data cost of
the four: ~8 UW calls per ticker plus shared market context.

## 3. LEAP — NOT STARTED

`scripts/leap_scanner_uw.py` (802 lines) + ~1146 total. Simplest of the four,
and the thinnest in actual content.

No gates, no verdict system. Pull the chain, keep **calls with expiry year ≥
2027** (a hardcoded absolute year, not a DTE offset — it silently returns zero
results once the calendar passes it; port as DTE-relative, e.g. DTE > 270).
Bucket by a crude moneyness lookup table (`approximate_delta`, not
Black-Scholes: 0.8/0.6/0.5/0.35/0.2/0.1 by price/strike bands) into
50Δ/30Δ/20Δ/10Δ. Per bucket take mean IV; `gap_20 = HV20 - avg_iv`,
`gap_60 = HV60 - avg_iv`. Flag `is_mispriced` when any bucket's gap ≥
`MIN_IV_GAP = 15`.

Note: radon's LEAP scanner falls back to **Yahoo Finance** for price history
when UW returns <60 bars, flagged in-file as against policy. Argon bans Yahoo
outright (enforced by `scripts/check_no_yahoo.py` in CI) — use the lake /
massive OHLC path instead.

Argon already stores a full IV surface. Most of this scanner's 800 lines are
chain-fetching and OCC-symbol parsing that argon's surface capture already
did. The remaining logic is roughly a 40-line query. **Do not port 1100
lines to reimplement a `GROUP BY` over data we already have.**

## 4. GARCH — NOT STARTED, AND IT IS NOT GARCH

`scripts/garch_convergence.py` (854 lines) + ~1377 total.

There is **no GARCH model in it**. No ARCH-family estimation of any kind, and
no `arch` / `statsmodels` / `pmdarima` dependency anywhere in radon's
`requirements.txt`, `requirements-forecasting.txt`, or `pyproject.toml`. The
name appears to come from the idea that vol clusters and mean-reverts across
correlated pairs, not from any fitted process.

What it actually does: hardcoded pair presets (`semis`: NVDA/AMD, TSM/ASML,
AVGO/QCOM, MU/AMAT; plus `mega-tech`, `energy`, `china-etf`), each with a
free-text `vol_driver` string used only as a boolean "is non-empty" gate.
For each pair, compute `iv_hv60 = leap_atm_iv / hv60` per leg, call the higher
one the leader, and:

```python
divergence         = leader.iv_hv60 - lagger.iv_hv60
lagger_hv_iv_gap   = lagger.hv20 - lagger.leap_atm_iv
expected_iv        = leader.iv_hv60 * lagger.hv60
expected_move      = expected_iv - lagger.leap_atm_iv

gates = [leader.iv_hv60 >= 1.0 and divergence >= 0.15,
         lagger_hv_iv_gap >= 10.0,
         bool(vol_driver),            # always true for preset pairs
         lagger.iv_rank < 50.0,
         lagger.has_leaps]
signal = STRONG   if divergence>=0.30 and gap>=20 and iv_rank<30
    else MODERATE if divergence>=0.20 and gap>=15 and iv_rank<40
    else WEAK     if all(gates) else NONE
```

Two paths if this gets picked up: port the heuristic under an honest name
(pair IV/HV divergence), or build an actual GARCH(1,1) vol forecast — which
would be genuinely new work, needs `arch` as a new dependency, and should be
gated through signal-lab like any other candidate signal rather than shipped
straight to a UI tab.

## Open decisions (deferred, settle per scanner)

1. **Warm store vs live UW.** Argon has `option_surface_grid_daily` and a
   120k/day UW budget governor; radon has neither and fetches live per scan.
   Reading the warm store makes scans near-free, reproducible, and
   backtestable, at the cost of EOD-rather-than-intraday freshness. This is
   being settled for Theta Harvester first; the answer likely generalizes.
2. **Sub-tab shell.** All four land under `/scanner` as sub-tabs with the
   existing flow scanner becoming one. Build the shell with the first
   scanner, not upfront.
3. **Backtestability.** Radon persists a JSON blob per scan, so none of its
   scanners can be evaluated after the fact. If argon's versions persist real
   per-candidate rows keyed `(ticker, as_of)`, forward performance becomes
   measurable — which is the whole point of the goal ladder's Stage-2 gate.
   Note: a new `(ticker, as_of)` table needs a `DatasetRegistryEntry` and a
   regenerated policy doc in the same PR.

## Recommendation on the remaining three

Port order by honest value, if they get picked up at all:

- **LEAP** — cheapest, but should be a query against the existing surface, not
  a 1100-line port. Worth doing as a thin panel.
- **7-Step Strength** — port at most the four groups backed by real data (GEX,
  call positioning, vol smile, breadth), substituting argon's CRI/VCG for term
  structure and systematic positioning. Drop Q-scores unless a real source
  turns up. Call it what it is once groups are removed.
- **GARCH** — lowest priority. Either rename to what it does, or treat "build
  a real vol forecast" as a separate research project, not a port.
